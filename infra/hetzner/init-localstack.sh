#!/usr/bin/env sh
set -eu

for q in research-queue europass-queue document-queue document-scan-queue mailbox-queue; do
  awslocal sqs create-queue --queue-name "$q" >/dev/null
done

for b in "${EVIDENCE_BUCKET_NAME:-elmify-evidence}" "${DOCUMENT_BUCKET_NAME:-elmify-documents}"; do
  awslocal s3 mb "s3://$b" >/dev/null 2>&1 || true
  awslocal s3api put-bucket-versioning --bucket "$b" --versioning-configuration Status=Enabled >/dev/null 2>&1 || true
done
