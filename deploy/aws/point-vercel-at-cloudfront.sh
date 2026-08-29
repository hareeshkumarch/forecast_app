#!/usr/bin/env bash
# Move the Vercel rewrites from the instance's public hostname to the
# CloudFront distribution, once there is a distribution that works.
#
#   ./deploy/aws/point-vercel-at-cloudfront.sh
#
# Run it after finish-cloudfront.sh, and before revoking the open :80 rule.
# That order is not incidental — see the note this prints at the end.
#
# Why a script rather than a committed edit: Vercel deploys from main and
# reads frontend/vercel.json on the way past, so a placeholder domain sitting
# in that file is a broken site for as long as it sits there. The value cannot
# be known until the distribution exists, so it gets written in when it does.
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
COMMENT="${DIST_COMMENT:-forecast-hub}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERCEL_JSON="$ROOT/frontend/vercel.json"

if [ -n "${AWS_ACCESS_KEY_ID:-}" ] &&
   env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY \
     "$(command -v aws)" sts get-caller-identity > /dev/null 2>&1; then
  aws() { command env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY "$(command -v aws)" "$@"; }
fi

denull() { case "$1" in None) ;; *) printf '%s' "$1" ;; esac; }

echo "==> finding the distribution"
DIST=$(denull "$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='$COMMENT'].Id" --output text 2>/dev/null || true)")
: "${DIST:?no distribution commented '$COMMENT' — run finish-cloudfront.sh first}"

read -r DOMAIN STATUS <<EOF
$(aws cloudfront get-distribution --id "$DIST" \
  --query 'Distribution.[DomainName,Status]' --output text)
EOF
echo "    $DIST  $DOMAIN  ($STATUS)"

if [ "$STATUS" != "Deployed" ]; then
  echo "    !! still $STATUS. A distribution answers 403 or 502 until it reaches" >&2
  echo "       Deployed, so switching Vercel over now would break the site for" >&2
  echo "       the 10-15 minutes it takes. Wait, then rerun:" >&2
  echo "         aws cloudfront wait distribution-deployed --id $DIST" >&2
  exit 1
fi

# The whole point of the cutover is that the API is reachable this way. Prove
# it before editing anything, because the failure mode of not checking is a
# site that 502s on every request with no obvious cause.
echo "==> checking the API answers through the edge"
# Some places this gets run from cannot reach the edge at all — a CI runner or
# a sandbox behind an egress proxy will fail this check while the distribution
# is perfectly healthy from anywhere a browser is. HEALTH_VERIFIED=1 says the
# operator has already made this exact call from somewhere that can. It skips
# the check and nothing else; the Deployed test above still had to pass.
if [ "${HEALTH_VERIFIED:-}" = "1" ]; then
  echo "    skipped: HEALTH_VERIFIED=1, taking it as checked elsewhere"
  HEALTH='"database_target":"supabase" (asserted, not measured)'
else
HEALTH=$(curl -fsS --max-time 25 "https://$DOMAIN/api/health") || {
  echo "    !! https://$DOMAIN/api/health did not answer." >&2
  echo "       Nothing has been changed. Usual causes, in order:" >&2
  echo "         - the CloudFront-VPCOrigins-Service-SG rule was never added;" >&2
  echo "           rerun finish-cloudfront.sh now the distribution exists" >&2
  echo "         - the instance is stopped" >&2
  echo "         - the /api/* behaviour is pointed at the S3 origin" >&2
  exit 1
}
fi
echo "    $HEALTH"
case "$HEALTH" in
  *'"database_target":"supabase"'*) ;;
  *) echo "    !! health did not report supabase as the store of record. Look at" >&2
     echo "       it before cutting over — the box may be serving its local node." >&2
     exit 1 ;;
esac

echo "==> rewriting $VERCEL_JSON"
python3 - "$VERCEL_JSON" "https://$DOMAIN" <<'PY'
import json, re, sys

path, origin = sys.argv[1], sys.argv[2]
with open(path, encoding="utf8") as handle:
    config = json.load(handle)

# Parse to find what to change, then edit the raw text rather than dumping the
# structure back out. json.dump would reformat the whole file — expanding every
# hand-compacted array and object — and bury three real changes in a diff of
# fifty. The destinations are unique strings, so a plain replace is exact.
with open(path, encoding="utf8") as handle:
    raw = handle.read()

changed = []
for rule in config.get("rewrites", []):
    before = rule["destination"]
    # Replace the scheme+host and keep whatever path pattern follows it.
    after = re.sub(r"^https?://[^/]+", origin, before)
    if after == before:
        continue
    quoted = json.dumps(before)
    if raw.count(quoted) != 1:
        sys.exit(f"    !! {before} appears {raw.count(quoted)} times; not editing blind")
    raw = raw.replace(quoted, json.dumps(after), 1)
    changed.append((before, after))

if not changed:
    print("    already pointed there; nothing to do")
    sys.exit(0)

# Never write something Vercel cannot read.
json.loads(raw)

with open(path, "w", encoding="utf8") as handle:
    handle.write(raw)

for before, after in changed:
    print(f"    {before}\n      -> {after}")
PY

cat <<EOF

Next, in this order. The order is the whole trick: the instance has to keep
accepting Vercel's proxy until Vercel has stopped being the thing proxying.

  1. Commit and push, and let Vercel deploy it:

       git add frontend/vercel.json
       git commit -m "Point the Vercel rewrites at CloudFront"
       git push origin main

  2. Confirm the deployed site is being served through the edge — open it and
     run a forecast. The progress indicator has to say it is streaming. If it
     says polling, the /api/* behaviour lost CachingDisabled or gained
     compression, and the fix is in finish-cloudfront.sh, not here.

  3. Only then close the instance. This is the step the whole exercise was
     for, and until it runs the API is still served over plain HTTP to
     anybody who knows the hostname:

       SG=\$(aws ec2 describe-security-groups \\
         --filters Name=group-name,Values=forecast-api \\
         --query 'SecurityGroups[0].GroupId' --output text)

       aws ec2 describe-security-groups --group-ids "\$SG" \\
         --query 'SecurityGroups[0].IpPermissions'          # look first

       aws ec2 revoke-security-group-ingress --group-id "\$SG" \\
         --protocol tcp --port 80 --cidr 0.0.0.0/0          # then this

     Leave the CloudFront-VPCOrigins-Service-SG rule in place; it is the one
     that keeps the site up.

  4. Check it took:

       curl --max-time 10 http://<instance-public-dns>/api/health   # must fail
       curl -fsS "https://$DOMAIN/api/health"                       # must work

If anything goes wrong at step 2 or 3, putting the open rule back is one
command and the old rewrites are one \`git revert\` away.
EOF
