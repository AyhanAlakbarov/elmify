# Design: decisions that keep Phase 3 application automation reachable

> **Amended 2026-09-15** by `2026-09-15-glass-box-copilot-design.md`. Decisions 1, 2 and 6 stand.
> Decision 3 (portal credentials in a secret store) is moot — no portal credential exists in the
> extension design; its erasure-with-storage rule moves to mailbox tokens
> (`2026-09-15-student-owned-mailbox-design.md`). Decision 4 (CAPTCHA detect → preserve → hand to
> a human → resume) becomes "detect → the student, who is present, does it"; no resolution service
> is ever integrated. Decision 5 (stable egress reserved) no longer applies to portals, which see
> only the student's own address. Note also that the proxy/anti-bot text this record cites as §3.6
> now lives under `phased requirements.md` §3.4.

Status: decision record, binding on current work. Scope: the choices that must be made *now*,
while Phase 2 is being built, because making them wrong forecloses Phase 3 or makes it
expensive. Constrains `phased requirements.md` §5 (Phase 3 — Autonomous application execution
and monitoring); does not design it.

## Out of scope, deliberately

- **The Phase 3 portal-execution subsystem.** Browser session lifecycle, form mapping,
  duplicate protection, fee execution. §5 already specifies the behaviour; the engine that
  delivers it is its own spec, written when Phase 2 gates pass.
- **Building the credential store.** Decision 3 fixes *where* credentials will live and what
  must be true of that place. Provisioning it now would ship infrastructure nothing calls —
  the pattern that left `playwright` in `pyproject.toml` for a renderer that no longer
  existed.
- **Whether session preservation is feasible at all.** It is unproven and load-bearing; see
  "The one thing this record cannot settle."

## Why a decision record and not a design

Two candidate end-states were raised: a bot submits applications, or the platform prepares
everything and the student submits. §5.1 already settles this — they are `counselor-submit`
and `student-submit`, a per-engagement authority flag, and *"the two modes differ only in who
performs the submission."* One pipeline, two exit conditions. There is no architecture to
choose between.

What is genuinely open is narrower and more urgent: the current schema and the current
operational posture contain assumptions that Phase 3 will contradict. Some are cheap to
change now and expensive later, because the cost is not the migration — it is the backfill,
where the true value is unrecoverable and someone has to guess.

## The decisions

### 1. An audit event must record what *kind* of actor acted

`apps/funding/models.py::AuditEvent.actor` is `ForeignKey(Membership, null=True)`.
`apps/documents/audit.py::record_event` documents the null case precisely: it means there was
no tenant context to write into.

In Phase 3 the agent becomes an actor. It has no `Membership`, so every agent action would
also record `actor=None` — landing in the same bucket as "system write, no tenant." The two
become indistinguishable at exactly the moment the distinction starts to matter, because
§3.2 requires recording *"every automated, counselor, student and platform-administrator
action"* and the exported dossier must show *"portal actions, submissions, payments, refunds
and failures"* attributably.

**Decision.** Add an actor-kind discriminator to `AuditEvent` now, defaulting existing rows
to the meaning they already have. Null `actor` keeps meaning "no membership"; the
discriminator carries *why*.

**Why now.** Events are append-only and accumulate continuously. A discriminator added after
Phase 3 starts writing cannot be backfilled from the data — nothing in an existing row
distinguishes a system write from an agent write, so the backfill would be a guess applied to
the audit trail. Adding it while only one meaning exists makes the migration total and exact.

### 2. A roadmap item must be able to be owned by the agent

`RoadmapItem.owner` is a non-null `ForeignKey(Membership, on_delete=PROTECT)`. Every owner is
a person. §5.2 requires the dashboard to *"show the institution, required action, owner,
deadline and expected duration."* When the agent holds a step, the owner is the agent.

The tempting workaround — a synthetic `Membership` row representing "the agent" — is wrong,
and it is worth saying why so nobody reaches for it later. `Membership` is the tenancy
primitive: it carries roles, authentication, MFA and notification routing, and it is the
subject of RLS policies. A fake member is a real principal that can be assigned permissions,
receive notifications, and appear in counselor lists. It would also corrupt the very
distinction Decision 1 exists to preserve, by giving agent actions a `Membership` id.

**Decision.** Represent agent ownership without a `Membership` row: make `owner` nullable and
pair it with the same actor-kind discriminator used for audit events, so "owner is the agent"
is a distinct, queryable state rather than an absent human.

**Why now.** `owner` is non-null today and referenced by `PROTECT`. Relaxing it later means a
migration plus an audit of every read path that assumes a person is present — and those read
paths are being written right now, in Phase 2.

### 3. Portal credentials live in a dedicated secret store, never in the database

§5.2 requires *"normal reauthentication with platform-managed credentials"*, so the platform
will hold student portal passwords. Nothing in the codebase stores a credential today
(`grep` across every app's models returns nothing), which makes this a clean decision rather
than a migration.

**Decision.** Portal credentials live in a dedicated secret store (AWS Secrets Manager under a
KMS key), keyed per student-portal pair. Specifically:

- Never a model field, never a `JSONField`, never in `EvidenceBucket`.
- Fetched at point of use and dropped; never logged, never in an exception message, never in
  an audit event. `record_event`'s signature already has no room for content, and that is the
  pattern to follow.
- The IAM grant is per-secret-prefix and belongs to the portal-execution role only — not to
  the web tier, and not to the existing worker roles.
- Erasure is defined at the same time as storage. `apps/audit/deletion.py::advance_deletion`
  already calls `delete_student_documents`; a student's secrets must be destroyed on the same
  path, or GDPR erasure silently leaves credentials behind.

**Why now.** Not because the store is needed yet, but because the *absence* of this decision
is what produces the bad outcome. The default path for "we need to remember a portal password"
is a model field added in passing during a sprint. Writing the rule down before anyone needs
one is the entire point.

### 4. CAPTCHA is detected and delegated, never circumvented

This decision is already made in `phased requirements.md` and is restated here because it was
recently questioned on technical grounds.

§2: *"Treat CAPTCHA as delegable application work… Do not use unauthorized CAPTCHA
circumvention."* §5.2: *"Detect CAPTCHA explicitly. During the MVP, create a scoped consultant
task in the preserved session. In later phases, invoke the configured resolution service only
for approved portals and fall back to the same consultant task without losing completed form
state."* §3.6 excludes *"rotating or residential proxy infrastructure intended to evade portal
access controls."*

**Decision.** The portal strategy is detect → preserve session → hand to a human → resume.
Browser stealth is not a CAPTCHA strategy and shall not be adopted as one. A resolution
service may be integrated only per-approved-portal, after the portal-terms and legal gates,
with consultant fallback.

**Why this is also the better engineering position.** CAPTCHA triggering on authenticated
portals is driven by IP reputation, behavioural signals and session history far more than by
browser fingerprint. The platform runs behind a single NAT IP; no fingerprint work changes
that. A strategy built on not being detected fails silently and at the worst possible moment —
mid-application, at a deadline. A strategy built on detecting and handing off degrades into a
consultant task, which is a business cost, not a lost application.

**Boundary with the discovery fetcher.** `apps/research/discovery.py::render_with_scrapling`
uses Scrapling's `StealthyFetcher` against *public, unauthenticated programme pages*, to read
pages that refuse plain HTTP clients. That is a different act from defeating an access control
on an authenticated third-party system, and this decision does not license extending it to
portals. `CLAUDE.md` records the distinction; portal execution gets its own client.

### 5. Stable egress identity is reserved; evasive egress is not

§3.6 forbids *"rotating or residential proxy infrastructure intended to evade portal access
controls."* It does not address the legitimate opposite need: a *stable, attributable* egress
address, because portals commonly invalidate a session whose IP changes mid-flow, and
§5.2 requires resuming a preserved session after a pause that may last hours.

Conflating the two is the risk in both directions — reading the exclusion too broadly blocks
session continuity we will genuinely need; reading it too narrowly licenses exactly what it
prohibits.

**Decision.** The distinction is *purpose*, and it is testable: egress that makes the platform
consistently identifiable is permitted; egress that makes it appear to be many unrelated
ordinary users is not. Reserve the ability to allocate stable per-tenant or per-portal egress
addresses in the network design. Do not build it now, and do not adopt rotating or residential
pools.

**Why now.** This is the only decision here that constrains infrastructure rather than code.
Retrofitting egress segmentation after the VPC and NAT layout have accreted more services is
disproportionately expensive, and `infra/template.yaml` is under active change.

### 6. The portal-automation ban is narrowed deliberately, never deleted

`apps/concierge/services.py` opens with a docstring that is itself the guarantee:

> *"Every action in this module is a human-recorded fact (a counselor manually filed a form,
> acknowledged a task, sent a message) — never an automated call into a payment processor or a
> portal."*

`tests/concierge/test_roadmap.py::test_no_payment_or_portal_automation_call` enforces it by
inspecting the module source for `requests.post(`, `stripe.`, `playwright.` and `selenium.`.

When Phase 3 arrives, the obvious move is to delete the test. That would be a mistake: the
test is not an obstacle to automation, it is the statement that *this module* records human
facts. That statement should stay true forever.

**Decision.** Portal automation lands in a new app, not in `apps/concierge`. The ban keeps
binding `apps/concierge.services` unchanged. `ManualOperation` remains what it is — the record
that a human did something — and gains no automated writer.

**Why now.** Because the decision costs nothing today and prevents a specific future pull
request from quietly removing a safety property while adding a feature.

## The one thing this record cannot settle

All of §5 rests on an assumption nobody has tested: that an authenticated browser session can
be **paused, transferred into a consultant's hands, and resumed** without repeating completed
steps — on infrastructure where workers are ephemeral Fargate tasks. §5.2 depends on it in six
separate places, including CAPTCHA handoff, reauthentication and post-interruption recovery.

If it is infeasible as specified, the failure is not in any decision above; it is in §5's
shape, and the Phase 3 design would need to change before it is written.

**This should be a spike, run before Phase 3 design begins, not before these decisions land.**
Its outcome does not change any of the six: the audit discriminator, the agent owner, the
credential rule, the CAPTCHA posture, the egress reservation and the preserved ban are correct
whether the session engine is a long-lived task, a remote browser service, or something else.

## What this changes in the code

Two migrations and no behaviour:

- `AuditEvent` gains an actor-kind discriminator, with existing rows migrated to their current
  meaning.
- `RoadmapItem.owner` becomes nullable and gains the same discriminator, so agent ownership is
  representable and queryable.

Decisions 3, 4, 5 and 6 are constraints on future work and add no code now. They belong in
`CLAUDE.md` alongside the existing web-fetching rules, so they reach whoever writes the next
change rather than living only here.

## Testing

- Migration tests in the existing `tests/migrations/` pattern: every pre-existing `AuditEvent`
  carries the current meaning after migrating, and tenant guards still hold on both tables.
- A test that a `RoadmapItem` owned by the agent is representable and distinguishable from one
  with a missing owner — the distinction Decision 2 exists to create.
- `test_no_payment_or_portal_automation_call` stays exactly as it is. It is a decision, not
  scaffolding.

## Risks

- **The discriminator is guessed wrong.** Its values are drawn from §3.2's own list (automated,
  counselor, student, platform-administrator). If Phase 3 needs a distinction not in that list,
  adding a value is cheap — unlike adding the column later.
- **Decisions 3–6 are prose, and prose gets skipped.** Mitigated by putting them in
  `CLAUDE.md`; the credential rule in particular is one an agent or a hurried developer would
  otherwise violate by reflex.
- **Reserving egress shape costs review time for a need that is a year out.** Accepted: the
  alternative is re-planning a VPC that by then carries production traffic.
