# AWS Live Boundary Validation Design

**Date:** 2026-08-11
**Status:** Approved for implementation planning; no AWS deployment is authorized by this document alone
**Region:** `eu-central-1`
**AWS CLI profile:** `tehsil-sandbox`

## Goal

Run the existing Phase 1 controlled-egress and SQS fair-queue harnesses once in a disposable AWS environment, preserve privacy-safe evidence, prove teardown, and then mark only the corresponding live-validation tasks complete.

## Non-goals

- Deploying the Phase 1 product.
- Creating persistent development infrastructure.
- Adding another infrastructure framework or a second AWS account.
- Treating AWS Budgets as a hard spending cap.
- Marking unrelated Phase 1 tasks complete.

## Fixed constraints

- Use only `eu-central-1`.
- Use the existing `tehsil-sandbox` profile and its temporary login session; create no long-lived access keys.
- Keep the zero-spend budget and Free Tier alerts enabled.
- Treat `$2 USD` as an operational ceiling, not a guaranteed hard cap.
- Start teardown no later than 30 minutes after the first billable resource is created.
- Delete resources immediately after the probes, including after any failure or interruption.
- Do not commit AWS account IDs, IAM user names, sign-in URLs, raw queue URLs, raw resource ARNs, credentials, MFA material, or secret values.
- Add no dependency solely for this run.

AWS Budgets is an alerting control rather than a real-time circuit breaker: AWS documents that updates typically occur every 8–12 hours and that charges can exceed a notification threshold before an alert arrives. CloudFormation also charges for resources while they operate and can retain resources when deletion fails. The run therefore relies on a short local deadline, automatic cleanup, and an explicit absence audit rather than on the budget alert alone.

References:

- [Managing costs with AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)
- [Managing resources with CloudFormation stacks](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacks.html)
- [Deleting a CloudFormation stack](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-delete-stack.html)
- [Deleting an ECR repository](https://docs.aws.amazon.com/AmazonECR/latest/APIReference/API_DeleteRepository.html)

## Chosen architecture

Use the existing CloudFormation template as one disposable validation stack and create one temporary ECR repository outside that stack. The repository must exist first so Docker can push the probe image and CloudFormation can receive its immutable digest URI through `ProbeImage`.

```text
local source + Docker
        |
        v
temporary ECR repository -- immutable image digest
        |
        v
one CloudFormation validation stack
        |
        +--> one disposable Fargate controlled-egress task
        |        +--> public HTTPS through one NAT gateway
        |        +--> AWS APIs through VPC endpoints
        |        +--> bounded VPC Flow Log evidence polling
        |
        +--> one disposable Standard SQS queue
                 +--> three fairness traffic trials
                 +--> bounded five-metric CloudWatch polling
        |
        v
privacy-safe Markdown evidence
        |
        v
stack deletion + ECR deletion + absence audit
```

The alternatives are rejected as unnecessary:

- A separate bootstrap stack for ECR would require a multi-stage stack lifecycle without improving this one-off proof.
- Manual console resource creation would be harder to reproduce and easier to leave running.

## Required pre-deployment corrections

No AWS resource may be created until these local corrections pass tests:

1. Invoke both harnesses as modules: `python -m scripts.validate_controlled_egress` and `python -m scripts.validate_sqs_fairness`.
2. Apply the same module invocation to the Fargate task definition and the controller's ECS command override.
3. Update the operator documentation to show the working module commands.
4. Make committed evidence privacy-safe at construction time:
   - record only `authenticated: true` for STS;
   - record the queue name, not its URL or ARN;
   - record the stack name, not its stack ID or raw outputs;
   - record the ECS task ID, not its task ARN;
   - retain region, source revision, timestamps, limits, probe results, metric values, and the immutable image digest.
5. Add exact-command `--help` smoke tests so imported-module tests cannot hide a broken documented entry point.

The confirmed root cause is Python script-mode path resolution: direct filesystem execution places `scripts/` on the import path and cannot import the repository's `apps` package. Module execution from the repository root works without a path mutation or packaging workaround.

## Disposable run controller

Add one small Bash controller because the job is primarily a sequence of existing AWS CLI, Docker, and Python commands. It must use native shell failure handling instead of introducing a deployment library.

The controller must:

- use `set -Eeuo pipefail` and `umask 077`;
- require explicit `AWS_PROFILE=tehsil-sandbox` and `AWS_REGION=eu-central-1`;
- reject any other profile or region;
- use fixed validation-only stack and repository names;
- abort if either name already exists, rather than deleting or adopting an unknown resource;
- tag the stack and ECR repository with `Project=tehsil-agent` and `Purpose=aws-boundary-validation`;
- register an idempotent `EXIT`, `INT`, and `TERM` cleanup trap before the first AWS write;
- run under `timeout --signal=TERM 30m`; its `TERM` handler starts cleanup and may continue beyond the 30-minute creation-to-teardown deadline until deletion is proven;
- suppress or sanitize AWS CLI and Docker output that contains login material, account IDs, repository URIs, or raw ARNs;
- return failure unless both probes pass and cleanup is proven.

The controller is not an AWS-side kill switch. Loss of local power, network access, credentials, or AWS service availability can prevent its cleanup call. That residual risk is accepted, but a run with incomplete cleanup remains failed and cannot close the Phase 1 gate.

## Execution flow

### 1. Local and authenticated preflight

Before any AWS write:

- confirm the repository is at the intended source revision;
- run focused harness tests, exact `--help` smoke tests, Ruff, and CloudFormation template validation;
- confirm Docker is available;
- confirm the CLI session is authenticated without displaying identity details;
- confirm the active region is exactly `eu-central-1`;
- confirm the validation stack and ECR repository do not already exist;
- present the expected resource inventory and ask for one final go/no-go.

### 2. Image publication

- Create the temporary private ECR repository.
- Authenticate Docker to ECR without writing the token to disk.
- Build the already-tested secure Docker context for Linux `amd64`.
- Push one validation tag.
- Resolve its digest and use only the immutable `repository@sha256:...` reference for CloudFormation.

### 3. Stack deployment

- Deploy `infra/template.yaml` with the immutable `ProbeImage` value and `CAPABILITY_IAM`.
- Keep normal rollback enabled.
- Wait for `CREATE_COMPLETE`; a creation failure immediately enters cleanup.
- Read required outputs into process memory only.

The cost-bearing shape is intentionally bounded: one NAT gateway, five interface endpoint services across two Availability Zones, one 0.25-vCPU/0.5-GB Fargate task, one secret, two log groups, one queue and DLQ, and four alarms. The traffic volume is only the validation traffic. No RDS instance, load balancer, or persistent service is created.

### 4. Controlled-egress proof

Run the controlled-egress controller first so a Fargate or networking defect stops the run before waiting for SQS metrics. Success requires:

- the one-off Fargate task stops successfully;
- the approved public HTTPS request succeeds;
- loopback, private, link-local, and instance-metadata targets remain blocked;
- S3, SQS, and Secrets Manager calls succeed through the intended endpoints;
- bounded Flow Log polling finds the expected accepted public-egress record;
- the evidence verdict is `passed`.

### 5. SQS fair-queue proof

Run three trials against the disposable Standard queue. Success requires:

- every trial satisfies the existing quiet-tenant receipt-order threshold;
- all five fair-queue CloudWatch metrics are captured within the bounded polling window;
- the evidence verdict is `passed`.

### 6. Teardown and absence audit

Cleanup runs whether the preceding steps pass or fail:

1. Stop any still-running validation task.
2. Request standard CloudFormation deletion with no retained resources.
3. Wait for deletion to complete; do not use express deletion.
4. Force-delete only the known temporary ECR repository so its one image is removed with it.
5. Confirm the stack and repository are absent.
6. Query for cost-sensitive resources carrying the validation stack identity and confirm no active NAT gateway, VPC endpoint, EIP, ECS task, or log group remains.
7. If CloudFormation reaches `DELETE_FAILED`, inspect its events and delete the exact failed resources before retrying. Do not declare success by retaining them.

CloudFormation `DELETE_COMPLETE` plus the explicit cost-sensitive-resource audit is the teardown proof. Cleanup failure leaves the Phase 1 gate open and receives immediate operator attention.

## Evidence contract

The committed evidence set is:

- `docs/validation/controlled-egress.md`
- `docs/validation/sqs-fair-queue.md`
- `docs/validation/aws-boundary-run.md`

The run summary records:

- source revision;
- region;
- immutable image digest without repository/account identity;
- both probe verdicts;
- run start/end times and the 30-minute limit;
- stack deletion result;
- ECR deletion result;
- cost-sensitive-resource audit result;
- final overall verdict.

No raw evidence file containing sensitive identifiers is written. Values needed to call AWS exist only in process memory. Evidence is committed only when both probes pass, teardown passes, the absence audit passes, and a final secret-pattern/account-identifier scan is clean.

## Failure semantics

- A validation timeout produces `evidence_unavailable`, not a pass.
- Any Fargate non-zero exit, missing Flow Log record, failed fairness trial, or missing metric fails the run.
- Any controller command failure triggers cleanup.
- A failed cleanup overrides successful probes and makes the overall run fail.
- An interrupted local session is recoverable with a cleanup-only mode that first verifies both fixed names carry the exact validation ownership tags. A tag mismatch stops without deleting anything.
- The controller never deletes a pre-existing stack or repository discovered during preflight.

## Verification strategy

Implementation remains test-first:

- RED: exact documented/module CLI smoke tests and Fargate-command assertions fail against current direct-script commands.
- GREEN: switch only the affected invocations to module form.
- RED: evidence tests reject account IDs, IAM names, raw ARNs, queue URLs, and stack outputs.
- GREEN: construct the minimal privacy-safe evidence fields.
- RED: controller tests with fake `aws` and `docker` commands prove cleanup is attempted after success, probe failure, timeout, and interruption.
- GREEN: implement the minimal shell controller and tag-verified cleanup-only path.
- Verify with focused tests, the non-AWS suite, Ruff, `bash -n`, Docker build, CloudFormation validation, and a secrets/identifier scan before the live run.

The live run is successful only when the two probe documents say `passed`, the run summary says `passed`, and the teardown audit says no cost-sensitive validation resources remain.

## Operator walkthrough

The user-facing sequence after the implementation plan is approved is intentionally short:

1. Keep the computer online and Docker running.
2. Renew `aws login --profile tehsil-sandbox` only if the temporary session has expired.
3. Review the read-only preflight summary; it will not display account identifiers.
4. Give the final go/no-go before ECR creation.
5. Leave the terminal running while the agent reports deploy, probe, and cleanup progress.
6. Review the three sanitized evidence documents and the clean teardown result.
7. Check Billing the following day because AWS cost data is delayed; this follow-up does not replace immediate teardown.

The agent runs the repository and AWS commands. The user does not need to copy a long command sequence or handle resource identifiers.

## Completion boundary

After successful evidence and teardown, update only the Phase 1 checklist entries for the SQS fair-queue and controlled-egress live validations. The broader Phase 1 implementation remains in progress.
