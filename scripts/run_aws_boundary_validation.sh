#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

EXPECTED_PROFILE="tehsil-sandbox"
EXPECTED_REGION="eu-central-1"
STACK_NAME="tehsil-phase1-validation"
REPOSITORY_NAME="tehsil-phase1-validation-probe"
CONTROLLED_OUTPUT="docs/validation/controlled-egress.md"
SQS_OUTPUT="docs/validation/sqs-fair-queue.md"
RUN_OUTPUT="docs/validation/aws-boundary-run.md"
IMAGE_DIGEST=""
REPOSITORY_URI=""
PROBE_IMAGE=""
QUEUE_URL=""
CLUSTER_ARN=""
PROBE_STATUS=1
CLEANUP_STATUS=1
STACK_DELETE_STATUS=1
REPOSITORY_DELETE_STATUS=1
AUDIT_STATUS=1
CLEANUP_STARTED=0
RUN_STARTED_AT=""
RUN_TIMEOUT_SECONDS=1800
WATCHDOG_PID=""
DOCKER_COMMAND=()

aws_cli() {
  aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@" 2>/dev/null
}

docker_cli() {
  "${DOCKER_COMMAND[@]}" "$@"
}

run_python() {
  uv run python -m "$@"
}

require_context() {
  [[ "${AWS_PROFILE:-}" == "$EXPECTED_PROFILE" ]] || {
    echo "AWS profile must be $EXPECTED_PROFILE" >&2
    return 2
  }
  [[ "${AWS_REGION:-}" == "$EXPECTED_REGION" ]] || {
    echo "AWS region must be $EXPECTED_REGION" >&2
    return 2
  }
  export AWS_DEFAULT_REGION="$AWS_REGION"
}

select_docker_command() {
  if docker info >/dev/null 2>&1; then
    DOCKER_COMMAND=(docker)
  elif sudo -n docker info >/dev/null 2>&1; then
    DOCKER_COMMAND=(sudo -n docker)
  else
    echo "Docker access unavailable; run sudo -v and retry" >&2
    return 2
  fi
}

stack_count() {
  aws_cli cloudformation list-stacks \
    --query "length(StackSummaries[?StackName=='${STACK_NAME}' && StackStatus!='DELETE_COMPLETE'])" \
    --output text
}

repository_count() {
  aws_cli ecr describe-repositories \
    --query "length(repositories[?repositoryName=='${REPOSITORY_NAME}'])" \
    --output text
}

preflight() {
  echo "Preflight: validating identity, names, and region"
  [[ "$(aws_cli sts get-caller-identity --query 'Account != null && Arn != null' --output text)" == "True" ]]
  [[ "$(stack_count)" == "0" ]]
  [[ "$(repository_count)" == "0" ]]
  [[ "$(aws_cli logs describe-log-groups --log-group-name-prefix "/tehsil/validation/${STACK_NAME}/" --query 'length(logGroups)' --output text)" == "0" ]]
}

publish_image() {
  echo "Deploy: publishing immutable probe image"
  REPOSITORY_URI="$(aws_cli ecr create-repository \
    --repository-name "$REPOSITORY_NAME" \
    --tags Key=Project,Value=tehsil-agent Key=Purpose,Value=aws-boundary-validation \
    --query 'repository.repositoryUri' --output text)"
  local registry="${REPOSITORY_URI%%/*}"
  aws_cli ecr get-login-password | docker_cli login --username AWS --password-stdin "$registry" >/dev/null 2>&1
  docker_cli build --platform linux/amd64 --target web --tag tehsil-agent:aws-boundary . >/dev/null 2>&1
  docker_cli tag tehsil-agent:aws-boundary "${REPOSITORY_URI}:validation" >/dev/null 2>&1
  docker_cli push "${REPOSITORY_URI}:validation" >/dev/null 2>&1
  IMAGE_DIGEST="$(aws_cli ecr describe-images --repository-name "$REPOSITORY_NAME" \
    --image-ids imageTag=validation --query 'imageDetails[0].imageDigest' --output text)"
  [[ "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
  PROBE_IMAGE="${REPOSITORY_URI}@${IMAGE_DIGEST}"
}

stack_output() {
  local key=$1
  aws_cli cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='${key}'].OutputValue | [0]" --output text
}

deploy_stack() {
  echo "Deploy: creating disposable validation stack"
  aws_cli cloudformation deploy \
    --stack-name "$STACK_NAME" \
    --template-file infra/template.yaml \
    --parameter-overrides "ProbeImage=${PROBE_IMAGE}" \
    --capabilities CAPABILITY_IAM \
    --tags Project=tehsil-agent Purpose=aws-boundary-validation >/dev/null
  QUEUE_URL="$(stack_output ResearchQueueUrl)"
  CLUSTER_ARN="$(stack_output ProbeClusterArn)"
}

run_controlled_probe() {
  echo "Probe: controlled egress and Flow Logs"
  run_python scripts.validate_controlled_egress \
    --stack-name "$STACK_NAME" --output "$CONTROLLED_OUTPUT"
}

run_sqs_probe() {
  echo "Probe: three SQS fairness trials"
  run_python scripts.validate_sqs_fairness \
    --queue-url "$QUEUE_URL" --trials 3 --metric-timeout-seconds 900 --output "$SQS_OUTPUT"
}

run_interruptible() {
  local child status=0 monitor_was_on=0
  case $- in
    *m*) monitor_was_on=1 ;;
    *) set -m ;;
  esac
  "$@" &
  child=$!
  (( monitor_was_on == 1 )) || set +m
  trap "kill -TERM -$child 2>/dev/null || kill $child 2>/dev/null || true; wait $child 2>/dev/null || true; exit 124" INT TERM
  wait "$child" || status=$?
  trap 'exit 124' INT TERM
  return "$status"
}

start_run_timeout() {
  (
    sleep "$RUN_TIMEOUT_SECONDS" &
    local sleeper=$!
    trap 'kill "$sleeper" 2>/dev/null || true; exit 0' TERM
    wait "$sleeper" || exit 0
    if [[ "${AWS_BOUNDARY_CONTROLLER_SESSION:-}" == "1" ]]; then
      kill -TERM -- "-$$"
    else
      kill -TERM "$$"
    fi
  ) >/dev/null 2>&1 &
  WATCHDOG_PID=$!
}

stop_run_timeout() {
  [[ -z "$WATCHDOG_PID" ]] && return 0
  kill "$WATCHDOG_PID" 2>/dev/null || true
  wait "$WATCHDOG_PID" 2>/dev/null || true
  WATCHDOG_PID=""
}

stack_is_owned() {
  [[ "$(aws_cli cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Tags[?Key=='Project'].Value | [0]" --output text)" == "tehsil-agent" ]] &&
  [[ "$(aws_cli cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Tags[?Key=='Purpose'].Value | [0]" --output text)" == "aws-boundary-validation" ]]
}

repository_is_owned() {
  local repository_arn
  repository_arn="$(aws_cli ecr describe-repositories --repository-names "$REPOSITORY_NAME" \
    --query 'repositories[0].repositoryArn' --output text)"
  [[ "$(aws_cli ecr list-tags-for-resource --resource-arn "$repository_arn" \
    --query "tags[?Key=='Project'].Value | [0]" --output text)" == "tehsil-agent" ]] &&
  [[ "$(aws_cli ecr list-tags-for-resource --resource-arn "$repository_arn" \
    --query "tags[?Key=='Purpose'].Value | [0]" --output text)" == "aws-boundary-validation" ]]
}

delete_owned_stack() {
  [[ "$(stack_count)" == "0" ]] && return 0
  stack_is_owned || { echo "Refusing to delete an unowned stack" >&2; return 3; }
  CLUSTER_ARN="${CLUSTER_ARN:-$(stack_output ProbeClusterArn 2>/dev/null || true)}"
  local tasks
  if [[ -n "$CLUSTER_ARN" && "$CLUSTER_ARN" != "None" ]]; then
    tasks="$(aws_cli ecs list-tasks --cluster "$CLUSTER_ARN" --desired-status RUNNING \
      --query 'taskArns[]' --output text)"
    for task in $tasks; do
      aws_cli ecs stop-task --cluster "$CLUSTER_ARN" --task "$task" >/dev/null
    done
  fi
  aws_cli cloudformation delete-stack --stack-name "$STACK_NAME"
  aws_cli cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
}

delete_owned_repo() {
  [[ "$(repository_count)" == "0" ]] && return 0
  repository_is_owned || { echo "Refusing to delete an unowned repository" >&2; return 3; }
  aws_cli ecr delete-repository --repository-name "$REPOSITORY_NAME" --force >/dev/null
}

audit_absence() {
  local failed=0
  [[ "$(stack_count)" == "0" ]] || failed=1
  [[ "$(repository_count)" == "0" ]] || failed=1
  [[ "$(aws_cli ec2 describe-nat-gateways \
    --filter Name=tag:aws:cloudformation:stack-name,Values="$STACK_NAME" \
    --query "length(NatGateways[?State!='deleted'])" --output text)" == "0" ]] || failed=1
  [[ "$(aws_cli ec2 describe-vpc-endpoints \
    --filters Name=tag:aws:cloudformation:stack-name,Values="$STACK_NAME" \
    --query 'length(VpcEndpoints)' --output text)" == "0" ]] || failed=1
  [[ "$(aws_cli ec2 describe-addresses \
    --filters Name=tag:aws:cloudformation:stack-name,Values="$STACK_NAME" \
    --query 'length(Addresses)' --output text)" == "0" ]] || failed=1
  [[ "$(aws_cli logs describe-log-groups \
    --log-group-name-prefix "/tehsil/validation/${STACK_NAME}/" \
    --query 'length(logGroups)' --output text)" == "0" ]] || failed=1
  [[ "$(aws_cli ecs describe-clusters --clusters "${STACK_NAME}-probe" \
    --query "length(clusters[?status=='ACTIVE'])" --output text)" == "0" ]] || failed=1
  return "$failed"
}

cleanup() {
  (( CLEANUP_STARTED == 0 )) || return 0
  CLEANUP_STARTED=1
  echo "Cleanup: deleting stack, repository, and validating absence"
  [[ "$(stack_count)" == "0" ]] || stack_is_owned || {
    echo "Refusing cleanup because the stack ownership tags do not match" >&2
    return 3
  }
  [[ "$(repository_count)" == "0" ]] || repository_is_owned || {
    echo "Refusing cleanup because the repository ownership tags do not match" >&2
    return 3
  }
  local failed=0
  if delete_owned_stack; then
    STACK_DELETE_STATUS=0
  else
    failed=1
  fi
  if delete_owned_repo; then
    REPOSITORY_DELETE_STATUS=0
  else
    failed=1
  fi
  if audit_absence; then
    AUDIT_STATUS=0
  else
    failed=1
  fi
  return "$failed"
}

cleanup_only() {
  cleanup
}

source_provenance() {
  local revision tree_hash
  revision="$(git rev-parse HEAD)"
  if git diff --quiet HEAD; then
    printf '%s\n' "$revision"
    return
  fi
  tree_hash="$(git diff --binary HEAD | sha256sum | awk '{print $1}')"
  printf '%s+dirty:%s\n' "$revision" "$tree_hash"
}

write_run_summary() {
  local _controller_status=$1
  local cleanup_status=$2
  local revision digest started ended probe_verdict stack_verdict repository_verdict
  local audit_verdict teardown_verdict overall_verdict temporary
  revision="$(source_provenance)"
  digest="${IMAGE_DIGEST:-unavailable}"
  started="${RUN_STARTED_AT:-unavailable}"
  ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  probe_verdict="failed"
  stack_verdict="failed"
  repository_verdict="failed"
  audit_verdict="failed"
  teardown_verdict="failed"
  overall_verdict="failed"
  (( PROBE_STATUS == 0 )) && probe_verdict="passed"
  (( STACK_DELETE_STATUS == 0 )) && stack_verdict="passed"
  (( REPOSITORY_DELETE_STATUS == 0 )) && repository_verdict="passed"
  (( AUDIT_STATUS == 0 )) && audit_verdict="passed"
  (( cleanup_status == 0 )) && teardown_verdict="passed"
  if [[ "$probe_verdict" == "passed" && "$teardown_verdict" == "passed" ]]; then
    overall_verdict="passed"
  fi
  temporary="${RUN_OUTPUT}.tmp"
  printf '# AWS boundary validation run\n\n```json\n{\n' > "$temporary"
  printf '  "audit_verdict": "%s",\n' "$audit_verdict" >> "$temporary"
  printf '  "ended_at": "%s",\n' "$ended" >> "$temporary"
  printf '  "image_digest": "%s",\n' "$digest" >> "$temporary"
  printf '  "overall_verdict": "%s",\n' "$overall_verdict" >> "$temporary"
  printf '  "probe_verdict": "%s",\n' "$probe_verdict" >> "$temporary"
  printf '  "repository_deletion_verdict": "%s",\n' "$repository_verdict" >> "$temporary"
  printf '  "region": "%s",\n' "$AWS_REGION" >> "$temporary"
  printf '  "source_revision": "%s",\n' "$revision" >> "$temporary"
  printf '  "stack_deletion_verdict": "%s",\n' "$stack_verdict" >> "$temporary"
  printf '  "started_at": "%s",\n' "$started" >> "$temporary"
  printf '  "teardown_verdict": "%s",\n' "$teardown_verdict" >> "$temporary"
  printf '  "time_limit": "30 minutes"\n}\n```\n' >> "$temporary"
  mv "$temporary" "$RUN_OUTPUT"
}

finish() {
  local original_status=$?
  stop_run_timeout
  trap - EXIT INT TERM
  if cleanup; then
    CLEANUP_STATUS=0
  else
    CLEANUP_STATUS=$?
  fi
  write_run_summary "$original_status" "$CLEANUP_STATUS"
  if (( original_status == 0 && CLEANUP_STATUS == 0 )); then
    exit 0
  fi
  exit 1
}

main() {
  require_context
  preflight
  select_docker_command
  trap finish EXIT
  trap 'exit 124' INT TERM
  start_run_timeout
  RUN_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  publish_image
  deploy_stack
  run_interruptible run_controlled_probe
  run_interruptible run_sqs_probe
  PROBE_STATUS=0
}

if [[ "${BASH_SOURCE[0]}" == "$0" && "${AWS_BOUNDARY_CONTROLLER_SESSION:-}" != "1" ]]; then
  export AWS_BOUNDARY_CONTROLLER_SESSION=1
  exec setsid --wait bash "$0" "$@"
fi

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-}" in
    --preflight-only)
      require_context
      preflight
      ;;
    --cleanup-only)
      require_context
      cleanup_only
      ;;
    "")
      main
      ;;
    *)
      echo "usage: $0 [--preflight-only|--cleanup-only]" >&2
      exit 2
      ;;
  esac
fi
