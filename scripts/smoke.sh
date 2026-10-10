#!/usr/bin/env bash
# Walking-skeleton smoke check against a deployed Phase 1 stack. No
# destructive actions; requires AWS credentials to read stack outputs and
# network access to the deployed ALB.
set -Eeuo pipefail
umask 077

usage() {
  cat <<'EOF'
usage: scripts/smoke.sh <stack-name>

Checks, in order:
  1. Health: GET https://<ALB DNS>/ returns a live app response. 400 counts
     as healthy — HostTenantContextMiddleware (apps/tenancy/middleware.py)
     rejects any Host it can't resolve to a verified tenant domain, and the
     ALB's own DNS name is never one; a 400 still proves the process and DB
     connectivity are up.
  2. Tenant host: GET with Host: $SMOKE_TENANT_HOST returns 200, proving a
     real pre-provisioned tenant domain resolves end to end.
  3. Queue: enqueues one research message (SMOKE_TENANT_ID/SMOKE_RUN_ID,
     pre-seeded by ops per docs/runbooks/deploy.md) and waits for the
     worker to drain it.
  4. Report: downloads SMOKE_REPORT_ID through /reports/<id>/download/ to
     confirm the evidence bucket path is reachable end to end. Skipped
     with a warning if SMOKE_SESSION_COOKIE is unset — obtaining an
     authenticated session is an ops runbook step, not this script's job.

Required environment variables (except for --help):
  SMOKE_TENANT_HOST     Host header for a pre-provisioned verified tenant domain
  SMOKE_TENANT_ID       UUID of that tenant
  SMOKE_RUN_ID          UUID of a research run owned by that tenant
  SMOKE_REPORT_ID       UUID of a report to download (step 4)

Optional:
  SMOKE_SESSION_COOKIE  "sessionid=..." cookie for the report download step
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" || $# -eq 0 ]]; then
  usage
  exit 0
fi

STACK_NAME="$1"

for var in SMOKE_TENANT_HOST SMOKE_TENANT_ID SMOKE_RUN_ID SMOKE_REPORT_ID; do
  [[ -n "${!var:-}" ]] || {
    echo "missing required environment variable: $var" >&2
    exit 2
  }
done

stack_output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text
}

LB_DNS="$(stack_output LoadBalancerDnsName)"
QUEUE_URL="$(stack_output ResearchQueueUrl)"

echo "Health: GET https://${LB_DNS}/"
STATUS="$(curl -sk -o /dev/null -w '%{http_code}' "https://${LB_DNS}/")"
[[ "$STATUS" == "200" || "$STATUS" == "400" ]] || {
  echo "health check failed: HTTP $STATUS" >&2
  exit 1
}

echo "Tenant host: GET https://${LB_DNS}/ with Host: ${SMOKE_TENANT_HOST}"
STATUS="$(curl -sk -o /dev/null -w '%{http_code}' -H "Host: ${SMOKE_TENANT_HOST}" "https://${LB_DNS}/")"
[[ "$STATUS" == "200" ]] || {
  echo "tenant host request failed: HTTP $STATUS" >&2
  exit 1
}

echo "Queue: enqueueing one smoke-test research message"
BODY="{\"schema_version\":1,\"kind\":\"run_research\",\"tenant_id\":\"${SMOKE_TENANT_ID}\",\"run_id\":\"${SMOKE_RUN_ID}\"}"
aws sqs send-message --queue-url "$QUEUE_URL" --message-body "$BODY" >/dev/null

echo "Queue: waiting for the worker to drain the smoke-test message"
DEPTH="unknown"
for _ in $(seq 1 30); do
  DEPTH="$(aws sqs get-queue-attributes --queue-url "$QUEUE_URL" \
    --attribute-names ApproximateNumberOfMessages \
    --query 'Attributes.ApproximateNumberOfMessages' --output text)"
  [[ "$DEPTH" == "0" ]] && break
  sleep 10
done
[[ "$DEPTH" == "0" ]] || {
  echo "queue did not drain within 5 minutes: depth=$DEPTH" >&2
  exit 1
}

if [[ -n "${SMOKE_SESSION_COOKIE:-}" ]]; then
  echo "Report: downloading https://${LB_DNS}/reports/${SMOKE_REPORT_ID}/download/"
  STATUS="$(curl -sk -o /dev/null -w '%{http_code}' -H "Host: ${SMOKE_TENANT_HOST}" \
    --cookie "$SMOKE_SESSION_COOKIE" \
    "https://${LB_DNS}/reports/${SMOKE_REPORT_ID}/download/")"
  [[ "$STATUS" == "200" ]] || {
    echo "report download failed: HTTP $STATUS" >&2
    exit 1
  }
else
  echo "Report: skipped (SMOKE_SESSION_COOKIE not set) — see docs/runbooks/deploy.md" >&2
fi

echo "Smoke test passed"
