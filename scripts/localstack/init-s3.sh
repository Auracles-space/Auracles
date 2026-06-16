#!/bin/sh
# Auto-provision local S3 buckets + CORS on LocalStack startup.
#
# LocalStack runs every script in /etc/localstack/init/ready.d once the
# services are ready. This recreates the dev buckets the backend expects
# (matching backend/.env S3_*_BUCKET) so they survive container restarts
# without a manual `awslocal s3 mb`. Community LocalStack has no persistence,
# so this hook is how the buckets come back each boot.
set -e

BUCKETS="auracles-artifacts-dev auracles-avatars-dev auracles-reports-dev auracles-thumbnails-dev"

for bucket in $BUCKETS; do
  awslocal s3 mb "s3://$bucket" 2>/dev/null || true
done

# Allow the Next.js dev origin to PUT/POST presigned uploads from the browser.
cat >/tmp/auracles-cors.json <<'JSON'
{"CORSRules":[{"AllowedOrigins":["http://localhost:3000"],"AllowedMethods":["GET","PUT","POST"],"AllowedHeaders":["*"],"ExposeHeaders":["ETag"]}]}
JSON

for bucket in $BUCKETS; do
  awslocal s3api put-bucket-cors \
    --bucket "$bucket" \
    --cors-configuration file:///tmp/auracles-cors.json
done

echo "localstack: provisioned dev S3 buckets + CORS"
