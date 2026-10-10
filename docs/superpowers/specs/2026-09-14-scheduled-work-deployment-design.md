# Where the scheduled work runs, and how a missed run becomes visible

## 0. Scope

Where each batch and scheduled job runs in production, what schedules it, and what makes a run that
did not happen **loud**.

**In scope:** the three homes a job can have and the rule that picks one; EventBridge Scheduler over
scheduled Rules; the heartbeat alarm; the three jobs that need a home now.

**Out of scope:** the long-running services (web, worker, portal, browser), which are already in
`infra/template.yaml`. Nothing here turns on `PortalDesiredCount` or `BrowserDesiredCount` — those
are gated on their own decisions.

## 1. What exists, and what does not

`infra/template.yaml` carries the whole runtime: 6 ECS services, 8 task definitions, 10 queues, 30
alarms, 11 log-metric filters. **Nothing is deployed.**

There are 14 management commands. **Two `AWS::Events::Rule` resources exist and neither runs a
management command on a business schedule** — `EuropassCanaryRule` exercises a third-party API every
6 hours to detect a shape change.

So every batch job in this system is, today, something a person remembers to type.

## 2. Three homes, and the rule that picks one

A job goes where its **output** goes, not where its code lives.

| The job's output is | Home | Why |
| --- | --- | --- |
| Rows in the production database | **ECS scheduled task** | it needs the VPC, the database and a role |
| A reviewed diff in the repository | **GitHub Actions**, opening a pull request | the artifact is a PR; ECS would need a path for a container to commit to git |
| A change a human must decide to make | **run by hand**, from the runbook | `load_*` commands and the admin SQL scripts |

The middle row is the one that gets misfiled. A job that reads public data and emits a CSV for review
needs no VPC, no database, no secret and no AWS credential. Putting it in ECS buys nothing and costs
a deployment path.

## 3. EventBridge Scheduler, not a scheduled Rule

**AWS recommends EventBridge Scheduler for invoking targets on a schedule, and its documentation page
for scheduled Rules is titled "(legacy)".** Scheduler adds time zones, a retry policy of up to 185
attempts, a dead-letter queue, and a schedule dashboard.

`EuropassCanaryRule` is the older mechanism. It is not broken and this design does not require
rewriting it; new schedules use Scheduler.

**Unverified, and it decides whether that is a migration or a rewrite:** whether Scheduler's ECS
`RunTask` target accepts every field the Rules target uses here — specifically capacity-provider
strategy and the `containerOverrides` `Input` shape. Confirm against the ECS documentation before
writing the template, rather than assuming parity.

## 4. The alarm that must break this template's own convention

A schedule's dead-letter queue catches a failed **invocation**. It does not catch the dangerous case:
the schedule fires, the task starts, and the work does not happen. From the outside those look
identical, and one of them is a GDPR breach.

**Measured 2026-09-14: all 16 `TreatMissingData` settings in `infra/template.yaml` are
`notBreaching`,** with a comment recording why — no publisher exists yet, so the alarms are kept
quiet until one does. That is right for an undeployed system and **exactly wrong for a heartbeat**:
a task that never runs writes no logs, produces no datapoints, and leaves a green alarm.

So each scheduled job that matters publishes a heartbeat, and its alarm sets
**`TreatMissingData: breaching`**. This is a deliberate exception to the house style and must be
commented as one, or a later tidying pass will "fix" it back.

The mechanism already exists and should be copied rather than invented: a `Logs::MetricFilter` over
the job's log group with `DefaultValue: 0`, exactly as `EuropassCallsFilter` does. `DefaultValue: 0`
covers "ran but did nothing"; `TreatMissingData: breaching` covers "never ran". **Both are needed;
neither substitutes for the other.**

## 5. The three jobs

### 5.1 `execute_due_erasures` — the deployment blocker

`CLAUDE.md` states the failure plainly: a student who requests deletion is locked out immediately and
their statutory month starts running. If the command is never invoked they are locked out
**indefinitely and never erased**, and every screen says the right thing.

- EventBridge Scheduler → ECS `RunTask` on `WorkerTaskDefinition`, `rate(1 day)`.
- Dead-letter queue on the schedule, for invocation failure.
- Heartbeat metric on every run, alarm `TreatMissingData: breaching` over a window of **two days**,
  so one transient miss does not page but a stopped schedule does.
- A second alarm on erasures that **failed** inside a run — the command catches per-student errors
  and continues, by design, so a failure is a log line and not a non-zero exit.

**This blocks the first real student reaching the deletion flow, not the first deploy.**

### 5.2 `refresh_register` — blocked on a database role that does not exist

- **Prerequisite, and it is code not infrastructure:** `config/settings/database.py` accepts only
  `runtime` and `migration`. The register tables are writable only under the `catalog_ingestion`
  policy, and `refresh_register`'s own docstring says a scheduled job must not hold migration
  credentials. Scheduling this before that role exists means a cron job with migration rights.
- Its **own** task definition, not the worker service. **Measured: 375 MB peak RSS, 63 s wall** for
  the 103 MB register file. The worker is 512 CPU / 1024 MB; give this task **2048 MB**. The measured
  peak came from a host with 31 GB free where the allocator never came under pressure, a 1 GB cgroup
  is a different environment, and the job runs for a minute a day. An OOM mid-refresh is worth more
  than the cents.
- Daily is ample: DEQAR regenerates its CSVs once a day (`last-modified` 06:00 GMT).
- Heartbeat as in §4, plus the existing counters the command already prints.

### 5.3 `propose_program_providers` — GitHub Actions, not AWS

Per the 2026-09-14 EMJM partner-source design, this command reads a public EU API and a public CSV
and emits candidate CSV rows. It resolves no `Program`, writes no database row, and holds no secret.

**It therefore needs no VPC, no task role, no database credential and no AWS access at all.** A
scheduled GitHub Actions workflow runs it and opens a pull request with the updated
`docs/research/program-providers.csv`. That produces exactly the reviewed diff the design depends on,
with no infrastructure.

It also keeps this traffic off the single NAT address the rest of the platform shares.

## 6. Order

1. **Now, independent of AWS:** `propose_program_providers` in GitHub Actions.
2. Base stack deployed. Nothing student-facing yet.
3. `catalog_ingestion` DATABASE_ROLE (code) → its secret → `refresh_register` schedule.
4. **Before any real student can reach the deletion flow:** the erasure schedule, its DLQ and its
   breaching heartbeat alarm.

Step 4 is the only one with a hard external deadline, and it is the one most easily forgotten because
nothing fails until someone is harmed.

## 7. What this does not decide

- **The other 11 management commands.** `load_*` and the admin SQL scripts stay manual by design —
  they apply a human's reviewed decision. `run_*_worker` are services, already in the template.
  `ingest_evidence` and `discover` need their own decision and do not have one.
- **Whether `EuropassCanaryRule` migrates to Scheduler.** It works. Leave it until §3's parity
  question is answered.
- **Alerting destination.** 30 alarms exist and this adds more; where they *go* — SNS topic,
  on-call, email — is not settled anywhere in the template and is not settled here.
- **Cost.** Not modelled. The additions are small (alarms at cents each, two short daily tasks), but
  "small" is an assertion until someone runs the numbers against a deployed stack.
