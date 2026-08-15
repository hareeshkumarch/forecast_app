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
OAC_NAME="${OAC_NAME:-forecast-s3-oac}"
SG_NAME="${SG_NAME:-forecast-api}"
INSTANCE_NAME="${INSTANCE_NAME:-forecast-api}"

aws() { command env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY "$(command -v aws)" "$@"; }

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

echo "==> resolving the pieces built earlier"
OAC=$(aws cloudfront list-origin-access-controls \
  --query "OriginAccessControlList.Items[?Name=='$OAC_NAME'].Id" --output text)
VPCO=$(aws cloudfront list-vpc-origins \
  --query "VpcOriginList.Items[?Name=='$VPC_ORIGIN_NAME'].Id" --output text)
PRIV=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$INSTANCE_NAME" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PrivateDnsName' --output text)
SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$SG_NAME" \
  --query 'SecurityGroups[0].GroupId' --output text)
: "${OAC:?no origin access control found}" "${VPCO:?no VPC origin found}"
: "${PRIV:?no running instance found}" "${SG:?no security group found}"
echo "    oac=$OAC vpc-origin=$VPCO origin=$PRIV sg=$SG"

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

if [ -z "$DIST" ]; then
  echo "==> creating the distribution"
  python3 - "$BUCKET" "$REGION" "$PRIV" "$OAC" "$VPCO" "$OPT" "$DIS" "$AVX" > /tmp/forecast-dist.json <<'PY'
import json, sys, time
bucket, region, priv, oac, vpco, opt, dis, avx = sys.argv[1:9]
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
   {"Id": "s3-frontend", "DomainName": f"{bucket}.s3.{region}.amazonaws.com",
    "OriginPath": "", "CustomHeaders": {"Quantity": 0},
    "S3OriginConfig": {"OriginAccessIdentity": ""},
    "OriginAccessControlId": oac,
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

echo "==> bucket policy, so only this distribution can read S3"
cat > /tmp/forecast-bucket-policy.json <<EOF
{"Version":"2008-10-17","Statement":[{
  "Sid":"AllowCloudFrontServicePrincipalReadOnly",
  "Effect":"Allow","Principal":{"Service":"cloudfront.amazonaws.com"},
  "Action":"s3:GetObject","Resource":"arn:aws:s3:::$BUCKET/*",
  "Condition":{"StringEquals":{"AWS:SourceArn":"arn:aws:cloudfront::$ACCOUNT:distribution/$DIST"}}}]}
EOF
aws s3api put-bucket-policy --bucket "$BUCKET" --policy file:///tmp/forecast-bucket-policy.json
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
