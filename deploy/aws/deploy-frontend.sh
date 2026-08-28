#!/usr/bin/env bash
# Build the frontend as static files and publish them to S3 + CloudFront.
#
#   S3_BUCKET=my-bucket CLOUDFRONT_DISTRIBUTION_ID=E123ABC ./deploy/aws/deploy-frontend.sh
#
# NEXT_PUBLIC_API_BASE_URL is left empty on purpose. CloudFront serves the app
# and the API from one distribution, so the bundle asks for "/api/..." on
# whatever origin it was loaded from — no hostname to bake in, no CORS, and
# the same build works from the CloudFront URL or a custom domain later.
set -euo pipefail

: "${S3_BUCKET:?set S3_BUCKET to the bucket holding the static site}"
: "${CLOUDFRONT_DISTRIBUTION_ID:?set CLOUDFRONT_DISTRIBUTION_ID to invalidate the edge cache}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/frontend"

echo "==> installing"
npm ci

echo "==> building static export"
STATIC_EXPORT=1 \
NEXT_PUBLIC_API_BASE_URL="" \
NEXT_TELEMETRY_DISABLED=1 \
  npm run build

echo "==> uploading"
# Two passes, because the two kinds of file want opposite cache headers.
#
# Everything under _next/static is content-hashed, so it can be cached for a
# year and never revalidated. A new build writes new filenames.
aws s3 sync out/ "s3://$S3_BUCKET/" \
  --delete \
  --exclude "*.html" \
  --exclude "*.txt" \
  --cache-control "public, max-age=31536000, immutable"

# The HTML is not hashed — it is the thing that points at the new hashes. It
# must revalidate, or a browser keeps loading last week's bundle.
aws s3 sync out/ "s3://$S3_BUCKET/" \
  --exclude "*" \
  --include "*.html" \
  --include "*.txt" \
  --cache-control "public, max-age=0, must-revalidate"

echo "==> invalidating"
# Only the HTML needs purging; the hashed assets are new paths at the edge.
INVALIDATION_ID=$(aws cloudfront create-invalidation \
  --distribution-id "$CLOUDFRONT_DISTRIBUTION_ID" \
  --paths "/" "/index.html" "/*/" "/*/index.html" \
  --query 'Invalidation.Id' --output text)

echo "==> done (invalidation $INVALIDATION_ID)"
