#!/usr/bin/env bash
# The last mile: the CloudFront distribution, the bucket policy that lets it
# read S3, and the security group rule that closes the instance behind it.
#
#   ./deploy/aws/finish-cloudfront.sh
#
# Split out from the rest because a new AWS account cannot create a
# distribution until AWS has verified it:
#
#   AccessDenied: Your account must be verified before you can add new
#   CloudFront resources. To verify your account, please contact AWS Support.
#
# Everything else — bucket, instance, VPC origin, uploaded frontend — can be
# built while that request is open. This script is what runs afterwards, and
# it is idempotent: rerunning it reuses whatever already exists.
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
BUCKET="${BUCKET:?set BUCKET to the frontend bucket}"
VPC_ORIGIN_NAME="${VPC_ORIGIN_NAME:-forecast-api-origin}"
SG_NAME="${SG_NAME:-forecast-api}"
INSTANCE_NAME="${INSTANCE_NAME:-forecast-api}"

# A container can arrive with AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
# already set to something that is not this account — the sandbox this was
# written in does exactly that — and they shadow the configured profile. Drop
# them, but only once the CLI has been shown to name an account without them,
# so a machine that authenticates *by* those variables is left alone rather
# than stripped of the only credentials it has.
if [ -n "${AWS_ACCESS_KEY_ID:-}" ] &&
   env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY \
     "$(command -v aws)" sts get-caller-identity > /dev/null 2>&1; then
  aws() { command env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY "$(command -v aws)" "$@"; }
  echo "==> ignoring the AWS_* variables in the environment; using the profile"
fi

aws sts get-caller-identity --query Account --output text > /dev/null

# `--output text` renders a null query result as the literal string "None", and
# the result is null rather than empty whenever the queried key is absent
# altogether — which is exactly what an account that has never created a
# distribution returns for DistributionList.Items. Left alone, "None" is a
# non-empty string and defeats every emptiness test below.
denull() { case "$1" in None) ;; *) printf '%s' "$1" ;; esac; }

echo "==> resolving the pieces built earlier"
VPCO=$(aws cloudfront list-vpc-origins \
  --query "VpcOriginList.Items[?Name=='$VPC_ORIGIN_NAME'].Id" --output text)
PRIV=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$INSTANCE_NAME" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PrivateDnsName' --output text)
SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$SG_NAME" \
  --query 'SecurityGroups[0].GroupId' --output text)
VPCO=$(denull "$VPCO"); PRIV=$(denull "$PRIV"); SG=$(denull "$SG")
: "${VPCO:?no VPC origin found}"
: "${PRIV:?no running instance found}" "${SG:?no security group found}"
echo "    vpc-origin=$VPCO origin=$PRIV sg=$SG"

# Managed policy ids are stable per account but cheap to look up, and looking
# them up beats hardcoding a uuid that means nothing to a reader.
pol() { aws cloudfront list-cache-policies --type managed \
  --query "CachePolicyList.Items[?CachePolicy.CachePolicyConfig.Name=='$1'].CachePolicy.Id" --output text; }
OPT=$(pol Managed-CachingOptimized)
DIS=$(pol Managed-CachingDisabled)
AVX=$(aws cloudfront list-origin-request-policies --type managed \
  --query "OriginRequestPolicyList.Items[?OriginRequestPolicy.OriginRequestPolicyConfig.Name=='Managed-AllViewerExceptHostHeader'].OriginRequestPolicy.Id" --output text)

DIST=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='forecast-hub'].Id" --output text 2>/dev/null || true)
DIST=$(denull "$DIST")

if [ -z "$DIST" ]; then
  echo "==> creating the distribution"
  python3 - "$BUCKET" "$REGION" "$PRIV" "$VPCO" "$OPT" "$DIS" "$AVX" > /tmp/forecast-dist.json <<'PY'
import json, sys, time
bucket, region, priv, vpco, opt, dis, avx = sys.argv[1:8]
ALL7 = ["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"]

def api(path):
    # CachingDisabled is not only about caching: it is what turns off request
    # collapsing, so two viewers opening the same progress stream are not
    # merged onto one origin connection. Compress off keeps the edge from
    # buffering that stream.
    return {"PathPattern": path, "TargetOriginId": "api-origin",
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {"Quantity": 7, "Items": ALL7,
                "CachedMethods": {"Quantity": 2, "Items": ["GET","HEAD"]}},
            "CachePolicyId": dis, "OriginRequestPolicyId": avx,
            "Compress": False, "SmoothStreaming": False,
            "FieldLevelEncryptionId": "",
            "LambdaFunctionAssociations": {"Quantity": 0},
            "FunctionAssociations": {"Quantity": 0}}

print(json.dumps({
 "CallerReference": f"forecast-{int(time.time())}",
 "Comment": "forecast-hub",
 "Enabled": True, "DefaultRootObject": "index.html",
 "PriceClass": "PriceClass_All",   # PriceClass_100 excludes India
 "HttpVersion": "http2and3", "IsIPV6Enabled": True,
 "Origins": {"Quantity": 2, "Items": [
   # The website endpoint, not the REST one, and it is not a preference.
   # A static export routes /dashboard/ to /dashboard/index.html, and only
   # the website endpoint does that resolution:
   #
   #   REST     /  403   /dashboard/  403   /dashboard/index.html  200
   #   website  /  200   /dashboard/  200   /dashboard/index.html  200
   #
   # Against the REST endpoint every sub-route would fall through to the
   # 403 handler below and render as a 404. DefaultRootObject only rescues
   # "/", which is why this is easy to miss until someone clicks a link.
   #
   # The cost is that a website endpoint is a custom origin: no origin
   # access control, so the bucket stays publicly readable. It holds the
   # compiled marketing site and nothing else, so that is a fair trade. To
   # close it, keep the REST endpoint and attach a CloudFront Function that
   # appends index.html to directory paths — which needs a CloudFront
   # resource this account cannot create yet.
   {"Id": "s3-frontend",
    "DomainName": f"{bucket}.s3-website.{region}.amazonaws.com",
    "OriginPath": "", "CustomHeaders": {"Quantity": 0},
    # S3 website endpoints do not speak HTTPS.
    "CustomOriginConfig": {"HTTPPort": 80, "HTTPSPort": 443,
        "OriginProtocolPolicy": "http-only",
        "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
        "OriginReadTimeout": 30, "OriginKeepaliveTimeout": 5},
    "ConnectionAttempts": 3, "ConnectionTimeout": 10,
    "OriginShield": {"Enabled": False}},
   {"Id": "api-origin", "DomainName": priv,
    "OriginPath": "", "CustomHeaders": {"Quantity": 0},
    # 30s read timeout against a 15s SSE keep-alive, so the stream never
    # idles long enough to be cut. Leave completion timeout unset: that one
    # caps total duration rather than the gap between packets.
    "VpcOriginConfig": {"VpcOriginId": vpco,
        "OriginReadTimeout": 30, "OriginKeepaliveTimeout": 5},
    "ConnectionAttempts": 3, "ConnectionTimeout": 10,
    "OriginShield": {"Enabled": False}}]},
 "DefaultCacheBehavior": {"TargetOriginId": "s3-frontend",
   "ViewerProtocolPolicy": "redirect-to-https",
   "AllowedMethods": {"Quantity": 2, "Items": ["GET","HEAD"],
       "CachedMethods": {"Quantity": 2, "Items": ["GET","HEAD"]}},
   "CachePolicyId": opt, "Compress": True, "SmoothStreaming": False,
   "FieldLevelEncryptionId": "",
   "LambdaFunctionAssociations": {"Quantity": 0},
   "FunctionAssociations": {"Quantity": 0}},
 "CacheBehaviors": {"Quantity": 3,
   "Items": [api("/api/*"), api("/docs*"), api("/openapi.json")]},
 # A static export has no server to rewrite unknown paths onto its 404.
 "CustomErrorResponses": {"Quantity": 2, "Items": [
   {"ErrorCode": 403, "ResponsePagePath": "/404.html",
    "ResponseCode": "404", "ErrorCachingMinTTL": 10},
   {"ErrorCode": 404, "ResponsePagePath": "/404.html",
    "ResponseCode": "404", "ErrorCachingMinTTL": 10}]},
}, indent=1))
PY
  DIST=$(aws cloudfront create-distribution \
    --distribution-config file:///tmp/forecast-dist.json \
    --query 'Distribution.Id' --output text)
fi

DOMAIN=$(aws cloudfront get-distribution --id "$DIST" --query 'Distribution.DomainName' --output text)
echo "    distribution=$DIST  domain=$DOMAIN"

echo "==> bucket policy: public read"
# A website endpoint is a custom origin, so CloudFront arrives as an ordinary
# anonymous client and cannot be identified by an OAC condition. The bucket
# holds only the compiled public marketing site.
#
# The bucket was created with all four access blocks on, which is right for the
# OAC shape the runbook first described but not for this one. Two of them have
# to come off before the policy below will take, and each fails differently:
# BlockPublicPolicy makes PutBucketPolicy itself return AccessDenied, while
# RestrictPublicBuckets accepts the policy and then serves 403 to the anonymous
# reader anyway — a distribution that deploys clean and answers every request
# with the 404 page. The two ACL blocks stay on: nothing here grants access by
# ACL, so keeping them costs nothing.
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=false,RestrictPublicBuckets=false"

cat > /tmp/forecast-bucket-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{
  "Sid":"PublicReadForWebsiteOrigin",
  "Effect":"Allow","Principal":"*",
  "Action":"s3:GetObject","Resource":"arn:aws:s3:::$BUCKET/*"}]}
EOF
aws s3api put-bucket-policy --bucket "$BUCKET" --policy file:///tmp/forecast-bucket-policy.json
aws s3api put-bucket-website --bucket "$BUCKET" --website-configuration \
  '{"IndexDocument":{"Suffix":"index.html"},"ErrorDocument":{"Key":"404.html"}}'
echo "    done"

echo "==> closing the instance to everything except this distribution"
CF_SG=$(aws ec2 describe-security-groups \
  --filters Name=group-name,Values=CloudFront-VPCOrigins-Service-SG \
  --query 'SecurityGroups[0].GroupId' --output text)
if [ "$CF_SG" != "None" ] && [ -n "$CF_SG" ]; then
  aws ec2 authorize-security-group-ingress --group-id "$SG" \
    --ip-permissions "IpProtocol=tcp,FromPort=80,ToPort=80,UserIdGroupPairs=[{GroupId=$CF_SG}]" \
    2>/dev/null && echo "    allowed :80 from $CF_SG" \
    || echo "    rule already present"
else
  echo "    !! CloudFront-VPCOrigins-Service-SG not found — the instance is still" >&2
  echo "       unreachable, which is safe but means nothing will serve. Rerun once" >&2
  echo "       the distribution has finished deploying." >&2
fi

cat <<EOF

  Distribution : $DIST
  URL          : https://$DOMAIN

It takes 10-15 minutes to reach Deployed. Then:

  curl -fsS  "https://$DOMAIN/api/health"
  curl -fsSI "https://$DOMAIN/" | head -1

Health should report "database_target":"supabase" and "status":"ok". Run a
forecast and the progress indicator should say it is streaming; if it says
polling, the /api/* behaviour lost CachingDisabled or gained compression.
EOF
