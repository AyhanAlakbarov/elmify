# Runbook: research queue / DLQ

`ResearchQueue` is a Standard SQS queue (`infra/template.yaml`, Tasks 4/5)
with `RedrivePolicy.maxReceiveCount: 3` to `ResearchDeadLetterQueue`, both
KMS-encrypted (`alias/aws/sqs`).

## Alarms

| Alarm | Signal | Meaning |
|---|---|---|
| `ResearchQueueAgeAlarm` | `ApproximateAgeOfOldestMessage` > 300s | Worker is falling behind or stuck |
| `QuietGroupAgeAlarm` | age of oldest message in quiet tenant groups > 120s | A low-traffic tenant is being starved by fairness batching |
| `NoisyGroupsAlarm` | count of noisy tenant groups > 0 | One tenant is dominating queue throughput |
| `DeadLetterDepthAlarm` | DLQ `ApproximateNumberOfMessagesVisible` > 0 | A message failed all 3 delivery attempts |
| `FailedResearchRateAlarm` | `Tehsil/App FailedResearchMessages` > 3 / 5 min | Worker tracebacks (see filter below) |

## DLQ triage

1. Inspect without deleting:
   ```bash
   aws sqs receive-message --queue-url <ResearchDeadLetterQueue URL> \
     --max-number-of-messages 10 --visibility-timeout 0
   ```
2. Decode each `Body` as `apps.research.schemas.ResearchMessage` JSON;
   note `tenant_id` and `run_id`.
3. Check `WorkerLogGroup` (`/tehsil/app/<stack>/worker`) around the
   message's approximate send time for the traceback that sent it to the
   DLQ (`FailedResearchMetricFilter` matches
   `"Traceback (most recent call last)"`).
4. If the failure is transient (e.g. a flaky external fetch) and the
   underlying bug is fixed or was a one-off, redrive:
   ```bash
   aws sqs start-message-move-task \
     --source-arn <ResearchDeadLetterQueue ARN> \
     --destination-arn <ResearchQueue ARN>
   ```
5. If the failure is a real bug, leave the message in the DLQ (it does not
   expire the underlying `AuditEvent`/`ResearchRun` state — the run stays
   visibly incomplete) and open an incident; do not redrive until the fix
   ships, or the same message will loop back to the DLQ after 3 more
   attempts.

## Never

- Never purge the DLQ without triaging every message first — that is
  silent tenant-visible research-run data loss.
- Never raise `maxReceiveCount` past what the underlying handler can
  safely retry (each retry re-enters `process_research_message`'s
  `tenant_scope`/`transaction.atomic()` block from scratch).
