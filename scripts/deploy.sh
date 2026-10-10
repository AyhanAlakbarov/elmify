#!/usr/bin/env bash
# Deploys the Phase 1 stack for one environment: infra/template.yaml plus
# infra/parameters/<env>.json, a one-off migration task, a forced
# redeployment of the web/worker services, then scripts/smoke.sh.
#
# See docs/runbooks/deploy.md for the full first-deploy checklist (DB role
# bootstrap via scripts/create_runtime_role.sql, DNS, secrets).
set -Eeuo pipefail
umask 077

usage() {
  cat <<'EOF'
usage: scripts/deploy.sh <test|production>

Environment variables:
  STACK_NAME   CloudFormation stack name (default: tehsil-agent-<env>)
  AWS_REGION   Must be eu-central-1 (Phase 1's single supported region)
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

ENVIRONMENT="${1:?usage: scripts/deploy.sh <test|production>}"
case "$ENVIRONMENT" in
  test|production) ;;
  *)
    echo "environment must be 'test' or 'production'" >&2
    exit 2
    ;;
esac

[[ "${AWS_REGION:-}" == "eu-central-1" ]] || {
  echo "AWS_REGION must be eu-central-1" >&2
  exit 2
}

STACK_NAME="${STACK_NAME:-tehsil-agent-${ENVIRONMENT}}"
PARAMETERS_FILE="infra/parameters/${ENVIRONMENT}.json"
CLUSTER="${STACK_NAME}-probe"

[[ -f "$PARAMETERS_FILE" ]] || {
  echo "missing $PARAMETERS_FILE" >&2
  exit 2
}

parameter_overrides() {
  uv run python -c '
import json, sys
for p in json.load(open(sys.argv[1])):
    print(p["ParameterKey"] + "=" + p["ParameterValue"])
' "$PARAMETERS_FILE"
}

stack_output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text
}

echo "Deploy: applying $PARAMETERS_FILE to stack $STACK_NAME"
# Assigned first, not inlined: inside $(...) a failure here is swallowed by
# set -e and the stack deploys with default parameters instead.
OVERRIDES="$(parameter_overrides)"
[[ -n "$OVERRIDES" ]] || {
  echo "no parameter overrides rendered from $PARAMETERS_FILE" >&2
  exit 1
}
# shellcheck disable=SC2086
aws cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file infra/template.yaml \
  --parameter-overrides $OVERRIDES \
  --capabilities CAPABILITY_IAM \
  --tags Project=tehsil-agent Environment="$ENVIRONMENT"

MIGRATION_TASK_DEF="$(stack_output MigrationTaskDefinitionArn)"
SUBNET_A="$(stack_output WorkerPrivateSubnetAId)"
SUBNET_B="$(stack_output WorkerPrivateSubnetBId)"
SECURITY_GROUP="$(stack_output WorkerSecurityGroupId)"

echo "Migration: running one-off migration task"
TASK_ARN="$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE \
  --task-definition "$MIGRATION_TASK_DEF" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$SECURITY_GROUP],assignPublicIp=DISABLED}" \
  --query 'tasks[0].taskArn' --output text)"
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN"
EXIT_CODE="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].containers[0].exitCode' --output text)"
[[ "$EXIT_CODE" == "0" ]] || {
  echo "migration task failed (exit $EXIT_CODE) — see $STACK_NAME/migration log group" >&2
  exit 1
}

echo "Check: Django deploy checks"
uv run python manage.py check --deploy --settings=config.settings.production

# Worker first, and WAIT for it, before the web tier. The consumer must be new
# before the producer can be: every queue message in this repo forbids extra
# fields, so an old worker raises on a message carrying a field added this
# release, consume_once leaves it on the queue, and after maxReceiveCount it
# dead-letters. ECS rolling deployments run old and new tasks side by side, so
# updating web first opens a window in which those messages are simply lost --
# at VisibilityTimeout 900 x 3 the DLQ alarm fires up to 45 minutes later, well
# after this script and smoke.sh have reported success.
# Pinned by tests/infra/test_template.py::test_deploy_rolls_the_worker_before_the_web_tier.
echo "Deploy: forcing a new worker deployment"
aws ecs update-service --cluster "$CLUSTER" --service worker --force-new-deployment >/dev/null
aws ecs wait services-stable --cluster "$CLUSTER" --services worker

echo "Deploy: forcing a new web deployment"
aws ecs update-service --cluster "$CLUSTER" --service web --force-new-deployment >/dev/null
aws ecs wait services-stable --cluster "$CLUSTER" --services web

echo "Smoke: verifying the deployment"
bash scripts/smoke.sh "$STACK_NAME"
