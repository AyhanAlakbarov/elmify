# Design: the Europass render pipeline in production

Status: design, not yet implemented. Scope: make the `EUROPASS_API` render path safe to run
as a commercial service on AWS at 1,000+ renders/day with deadline-driven spikes. Builds on
`docs/superpowers/specs/2026-08-25-europass-api-render-design.md`, which designed the API
call itself and is already implemented.

## Out of scope, deliberately

- **The trigger and the student-facing status surface.** Nothing calls `render_draft` today —
  who presses what, and how a student learns their CV is ready, is greenfield product work
  with its own spec. This document ends at "the artefact exists and is stored."
- **Autoscaling the web tier.** Unrelated to this path.
- **Anything that renders a non-Europass CV when europa.eu fails.** Settled: there is no
  fallback, for either requirement value. An outage is a delay, never a substitution.

## The problem

The `EUROPASS_API` variant works and is well tested, but it was designed as a function call.
Three things break when it becomes a business running on a server:

**It is synchronous.** `render_draft` calls europa.eu inline — four HTTP round trips to a
third party. On a web request that is seconds of held connection, and any outage becomes a
user-facing error rather than a retry.

**Its rate limiter does not work on more than one process.** There is no `CACHES` setting, so
Django falls back to `LocMemCache`: per-process, in-memory. `apps/ratelimit.py` counts in it.
`WebDesiredCount`/`WorkerDesiredCount` default to `1`, so it is correct today and silently
wrong the moment anyone scales — N tasks means N× the limit, with no error. The counter also
resets on every deploy and task replacement, so a daily window is really "per task, per
however long that task lives."

**A daily cap is the wrong control anyway.** What gets an IP blocked is *rate*, not total. A
counter permitting 1,000/day permits all 1,000 in ten minutes, which is exactly the shape a
deadline produces and exactly the shape that reads as an attack.

All egress leaves through a single NAT Elastic IP (`infra/template.yaml`, `NATElasticIp`), so
europa.eu sees every tenant as one address. A block is not degraded service for one customer;
it is total outage for all of them.

## The core idea: the queue is the rate limiter

If the **only** thing that ever calls europa.eu is a single worker draining a queue, then the
outbound rate is not a counter to be enforced — it is arithmetic:

```
requests per minute = worker_task_count × (60 / inter_call_delay_seconds)
```

Set the delay, pin the task count, and the rate is a property of the deployment. No
distributed counter, no shared cache, no new AWS resource, and no silent failure mode: the
number cannot drift from what the code intends, because there is no number in the code.

**Concrete default: one task, a 2-second inter-call delay — a ceiling of 30 requests/minute.**
The arithmetic that justifies it: 1,000 renders spread over a 10-hour working day averages
~1.7/minute, so 30/minute leaves roughly 17× headroom for a spike. A 500-student deadline
burst drains in about 17 minutes, which is acceptable for a queued job and is emphatically
not a thundering herd. The delay is the only knob that should ever be turned to change rate,
and it should be turned *up* on europa.eu's request, not down for our convenience.

This also solves three other problems at once. Retry becomes SQS redelivery. A spike becomes
queue depth rather than concurrent load. And the web request returns immediately.

**This is why approach A was chosen over shared counters.** A counter tells you when to say
no. A drained queue means you rarely have to.

### The constraint that must not be lost

Because rate is `tasks × 1/delay`, **the Europass worker's task count is a rate knob, not a
throughput knob.** Two consequences, both of which must be enforced in the infrastructure and
not merely documented:

1. **It gets its own ECS service.** Not the existing research worker. If Europass consumption
   shared that service, scaling the research worker for research throughput would multiply
   the Europass request rate at europa.eu as a side effect.
2. **It is never autoscaled, and `DesiredCount` is pinned to 1.** The template currently has
   no autoscaling at all, which is accidentally correct here. That accident must become a
   stated decision with a comment beside it, or a well-meaning engineer will "fix" the
   bottleneck and silently 4× the traffic to a public EU service.

If throughput ever genuinely needs to rise, the lever is the delay — reduced only to a rate
europa.eu has agreed to, per the Q2 email.

## Architecture

```
release request ──▶ enqueue EuropassRenderMessage ──▶ SQS ──▶ EuropassRenderWorker (1 task)
                    (returns immediately)                          │
                                                                   ├─ content-hash cache hit? ──▶ done, no call
                                                                   ├─ circuit open? ──▶ return to queue
                                                                   ├─ sleep(delay)
                                                                   ├─ render_europass_pdf()
                                                                   ├─ assert_europass_provenance()
                                                                   └─ store_document()
```

Every piece follows the rail `apps/research/` already established — `queue.consume_once`, a
typed pydantic message, `dispatch.recover_undispatched_runs` for outbox recovery, and a
`run_*_worker` management command. This is deliberate: that pattern is already in production,
already has alarms, and already has tests. A second, different queueing idiom in the same
codebase would be the expensive choice.

### Components

| Unit | Responsibility |
|---|---|
| `apps/documents/europass_queue.py` | Enqueue a render request; typed `EuropassRenderMessage` (tenant, draft id, payload hash). Mirrors `apps/research/queue.py`. |
| `apps/documents/management/commands/run_europass_worker.py` | Poll SQS, enforce the delay, invoke the service function. Mirrors `run_research_worker`. |
| `apps/documents/europass_render.py` | The unit of work: cache check → circuit check → render → verify → store. Pure of AWS concerns so it is testable. |
| `EuropassRenderCache` (model) | `payload_hash` → `object_key`. Doubles as the idempotency key. |
| `EuropassCircuit` (model) | One row: `paused_until`, `reason`. Shared state without Redis. |

Nothing in `apps/documents/europass.py` changes. It already does exactly one thing — turn a
`CVContent` into verified Europass PDF bytes — and it does it well.

## The content-hash cache

Hash the canonical JSON of `europass_payload(content)` (sorted keys). If a row exists for that
hash, reuse the stored artefact and **make no call at all**.

This is the single biggest lever on request volume. A student approving, then re-downloading,
then a counsellor downloading the same CV is one call, not three. Re-releasing an unchanged
draft is zero calls.

It also gives idempotency for free. SQS is at-least-once, so the worker *will* occasionally
see a message twice; the second delivery finds the cached artefact and returns without calling
europa.eu. One mechanism, two jobs — which is why there is no separate dedupe table.

The cache key is the payload, not the draft id, so two students with genuinely identical CV
content would share an artefact. That cannot happen in practice — the payload contains their
name and application email — but the key is scoped per tenant regardless, because a cross-tenant
artefact share would be a data leak and this codebase's RLS posture treats that as unthinkable.

## The circuit breaker

One row, checked before each call. Opened when europa.eu returns `429`, or on the third
consecutive `5xx`; closed when `paused_until` passes.

**The circuit is global, not tenant-scoped** — a deliberate exception to this codebase's rule
that everything carries a tenant. It has to be: all egress leaves through one NAT Elastic IP,
so when europa.eu throttles us they throttle *us*, not a customer. A per-tenant circuit would
let 49 other agencies keep calling an endpoint that has just asked us to stop. Because the
table is global it sits outside the RLS pattern, so it holds no tenant data and no student
data — only a timestamp and a reason string — and that constraint should be enforced by
keeping the model to exactly those columns.

When open, the worker returns the message to the queue rather than failing it — SQS
visibility timeout does the waiting, so no work is lost and nothing spins.

The current transport treats `429` as a generic `>= 400` failure and raises. That must change:
`429` is the one status where the remote is explicitly telling us the rate is wrong, and
honouring `Retry-After` is the strongest signal available that we are a well-behaved client.
Ignoring it is how a throttle becomes a ban.

## Failure handling

| Failure | Behaviour |
|---|---|
| europa.eu timeout / 5xx | Message returns to queue; SQS retries; DLQ after `maxReceiveCount: 3`. Three consecutive 5xx also opens the circuit |
| `429` with `Retry-After` | Circuit opens for that duration; message returns to queue |
| Provenance missing | **Fail the message to the DLQ immediately.** Not retryable — a PDF without `attachment.xml` means something changed at europa.eu, and retrying cannot fix it. This is the alarm that means "go read the canary." |
| Payload rejected (`500`) | DLQ. Signals the undocumented API changed shape — the case the canary exists to catch. |
| Circuit open | Return to queue, no call |

`EuropassUnavailable` remains the single exception type the caller handles; the worker maps it
onto queue behaviour. No failure path ever produces a non-Europass artefact.

**Nothing is written before the PDF is in hand**, so a failure leaves the draft exactly as it
was and re-running is always safe. That property is already pinned by a test and must survive
this change.

## Observability

Following the existing custom-metric pattern (`ModelCostUsd`, `ReviewBacklogCount`,
`CrossTenantDenials` are already emitted and alarmed):

| Metric | Alarm meaning |
|---|---|
| `EuropassQueueAge` (`ApproximateAgeOfOldestMessage`) | Backlog is not draining — the deadline-night alarm |
| `EuropassDlqDepth` | Something is structurally broken; read the canary |
| `EuropassCircuitOpenSeconds` | We are being throttled |
| `EuropassCallsTotal` | Actual outbound volume, for the Q2 conversation |
| `EuropassCacheHitRatio` | Whether the cache is doing its job |

`EuropassCallsTotal` is the one that matters commercially: it turns "we think it's about
1,000/day" into a number you can put in an email to `EMPL-ELM-SUPPORT@ec.europa.eu` and hold
yourself to.

## DevOps assessment

Asked for explicitly, so this covers the whole picture rather than just this feature.

**Sound already, and reused rather than re-litigated here:** SQS with KMS encryption and a DLQ
on `maxReceiveCount: 3`; 15 CloudWatch alarms including business and security metrics, not just
CPU; log retention set; actions pinned to commit SHAs; base images pinned by digest; both
containers dropping to a non-root uid; narrowly-prefixed IAM; a blocking security job in CI
(Bandit, pip-audit, gitleaks). That is a better baseline than most projects this size.

**Gaps worth naming:**

1. **There is no deploy pipeline.** `.github/workflows/` has `ci.yml` and a dormant
   `security-aws.yml`; nothing deploys. Every release is a human running CloudFormation and
   ECS commands by hand. For a business this is the largest operational risk on the list — it
   makes releases unrepeatable, rollback improvised, and the deployed state unknowable from
   the repo. It is out of scope for this spec, but it should be the next infrastructure task
   after it.
2. **No autoscaling anywhere.** For the Europass worker that is correct and must be made
   deliberate (above). For the web tier it is a real gap at 50+ agencies, and a separate
   piece of work.
3. **One health check in the whole template.** The new worker service needs one that reflects
   queue processing, not just process liveness — a worker stuck on a wedged HTTP call is
   "running" by any naive definition.
4. **The canary has no schedule.** The spec calls it "the entire early-warning system" for an
   undocumented API, and nothing runs it. It needs an EventBridge rule and an alarm on
   failure, otherwise the first notice that europa.eu changed shape is a DLQ full of students'
   CVs.

Items 3 and 4 are in scope for this design. Items 1 and 2 are named so they are not
rediscovered later.

## Security and privacy

Unchanged from the implemented design and not weakened here: host pinned in code with no
settings knob, `validate_public_url` on every URL, connection to the validated address rather
than a re-resolved name, redirects refused, response capped, content type checked per call,
connect and read timeouts, connection released on every path, remote-supplied ids
percent-encoded before entering a URL path.

Two additions this design introduces:

- **The queue message carries no PII** — tenant id, draft id and payload hash only. The
  content is read from the database inside the worker, under tenant scope. A queue is a
  durable store with its own retention; putting a student's employment history in it would
  create a second copy of the data with different rules from the first.
- **The delay is not a security control but a courtesy one**, and should be set from whatever
  europa.eu answers to Q2 rather than from what we can get away with.

## Testing

| Test | What it holds |
|---|---|
| The worker makes no call on a cache hit | The cache is doing its job, and idempotency holds |
| A duplicate SQS delivery renders once | At-least-once delivery does not double-call a third party |
| An open circuit returns the message without calling | Backpressure actually applies |
| A `429` opens the circuit for `Retry-After` | We honour throttling rather than ignoring it |
| Missing provenance goes to the DLQ, not a retry | An unretryable failure is not retried forever |
| A failed render leaves the draft untouched | Retryability — already pinned, must not regress |
| The queue message contains no PII fields | Pins a privacy decision that is easy to erode |
| The rate arithmetic test: N messages take ≥ N×delay | The rate guarantee is a real guarantee |

The last one is the guard on the whole design. If someone removes the delay for a faster test
suite, the rate limiter silently ceases to exist — so the test asserts elapsed time with a
patched clock, not a real sleep.

## What is deliberately not built

- **No Redis / ElastiCache.** The drain rate bounds the request rate, so exact shared counters
  buy precision nothing needs. If europa.eu answers Q2 with a specific contractual ceiling,
  exact counting starts to matter and this is the upgrade path.
- **No autoscaling on this worker.** It is the rate control.
- **No retry loop inside the render call.** SQS is the retry mechanism; a second one nested
  inside it would multiply load during exactly the outage that caused the failure.
- **No daily budget counter.** Rate is the control that matters; a daily total permits the
  burst that actually gets you blocked.

## Dependency this design cannot close

The `EMPL-ELM-SUPPORT@ec.europa.eu` email is still unsent. At pilot scale it was a courtesy.
At 1,000+/day, sustained, against a public European Commission service from a single
datacentre IP, sanctioned access stops being a nicety and becomes a dependency: the delay
value in this design is a guess until they supply a real one, and being blocked takes the
feature down for every tenant simultaneously.

Build this pipeline regardless — it is the right shape either way, and it is what makes the
volume answerable in the email. But do not scale into the thousands before there is a reply.
