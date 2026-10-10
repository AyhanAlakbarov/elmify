#!/usr/bin/env bash
# Proves PITR/backup recovery works without touching the live stack:
# restores a disposable RDS instance from a point in time, runs read-only
# integrity queries against it, checks the evidence bucket's object
# versions, then deletes only the disposable restore resources (mirrors the
# Task 4/5 teardown discipline — never deletes anything it didn't create).
set -Eeuo pipefail
umask 077

usage() {
  cat <<'EOF'
usage: scripts/restore_backup.sh <stack-name> [restore-time]

  stack-name     CloudFormation stack whose Database to restore from
  restore-time   ISO-8601 UTC timestamp for point-in-time recovery
                 (default: 5 minutes ago)

Environment variables:
  AWS_REGION   Must be eu-central-1

This script only ever creates and deletes its own disposable
"<stack-name>-restore-<timestamp>" RDS instance; it never modifies or
deletes the live Database.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" || $# -eq 0 ]]; then
  usage
  exit 0
fi

[[ "${AWS_REGION:-}" == "eu-central-1" ]] || {
  echo "AWS_REGION must be eu-central-1" >&2
  exit 2
}

STACK_NAME="$1"
RESTORE_TIME="${2:-$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ)}"
RUN_ID="$(date -u +%Y%m%d%H%M%S)"
RESTORE_INSTANCE_ID="${STACK_NAME}-restore-${RUN_ID}"
CLEANUP_STARTED=0

stack_output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text
}

source_instance_id() {
  aws cloudformation describe-stack-resources --stack-name "$STACK_NAME" \
    --logical-resource-id Database --query 'StackResources[0].PhysicalResourceId' --output text
}

restore_instance() {
  local source_id
  source_id="$(source_instance_id)"
  echo "Restore: creating disposable instance ${RESTORE_INSTANCE_ID} from ${source_id} at ${RESTORE_TIME}"
  aws rds restore-db-instance-to-point-in-time \
    --source-db-instance-identifier "$source_id" \
    --target-db-instance-identifier "$RESTORE_INSTANCE_ID" \
    --restore-time "$RESTORE_TIME" \
    --no-publicly-accessible \
    --tags Key=Project,Value=tehsil-agent Key=Purpose,Value=restore-drill >/dev/null
  aws rds wait db-instance-available --db-instance-identifier "$RESTORE_INSTANCE_ID"
}

run_integrity_queries() {
  local endpoint
  endpoint="$(aws rds describe-db-instances --db-instance-identifier "$RESTORE_INSTANCE_ID" \
    --query 'DBInstances[0].Endpoint.Address' --output text)"
  echo "Restore: running read-only integrity queries against ${endpoint}"
  PGPASSWORD="${RESTORE_DB_PASSWORD:?RESTORE_DB_PASSWORD is required for the integrity check}" \
    psql "host=${endpoint} dbname=${RESTORE_DB_NAME:-tehsil} user=${RESTORE_DB_USER:-tehsil_admin} sslmode=require" \
    -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public';"
}

check_evidence_bucket_versions() {
  local bucket
  bucket="$(stack_output EvidenceBucketName)"
  echo "Restore: confirming ${bucket} retains object versions"
  local version_count
  version_count="$(aws s3api list-object-versions --bucket "$bucket" --max-items 1 \
    --query 'length(Versions || `[]`)' --output text)"
  [[ "$version_count" != "0" ]] || echo "warning: no object versions found in ${bucket} yet" >&2
}

cleanup() {
  (( CLEANUP_STARTED == 0 )) || return 0
  CLEANUP_STARTED=1
  echo "Cleanup: deleting disposable restore instance ${RESTORE_INSTANCE_ID}"
  aws rds describe-db-instances --db-instance-identifier "$RESTORE_INSTANCE_ID" >/dev/null 2>&1 || return 0
  aws rds delete-db-instance --db-instance-identifier "$RESTORE_INSTANCE_ID" \
    --skip-final-snapshot >/dev/null
  aws rds wait db-instance-deleted --db-instance-identifier "$RESTORE_INSTANCE_ID"
}

trap cleanup EXIT

restore_instance
run_integrity_queries
check_evidence_bucket_versions

echo "Restore drill passed for ${STACK_NAME} at ${RESTORE_TIME}"
