# The erasure console

Status: design, awaiting review. Gives `apps/audit/deletion.py::advance_deletion` its first caller.

**The derived-data half of this document is deliberately incomplete.** It specifies `Pseudonym` and a
cascade and nothing else; the extraction pipeline, the feature schema, the threshold and the
generalized variant that survives an erasure are all named here, specified in
`phased requirements.md` §6.1, and **not built** — an MVP decision taken 2026-09-11 and recorded in
CLAUDE.md so it is not mistaken for an oversight. Everything else in this document is a complete
design.

Depends on `docs/superpowers/specs/2026-09-09-identity-erasure-design.md`, which shipped the login
scrub this console is now allowed to trigger. Its "What this does not do" section named this
document.

## The gap

Two of them, and the second is the larger surprise.

`advance_deletion` erases 124 fields across 32 models, purges S3, destroys portal credentials,
scrubs the login and writes `EXECUTED`. **Nothing calls it.**

**Nothing creates a `DeletionRequest` either.** The uncalled function is the last step of a
lifecycle that has no first step. So this design owns the whole path — request, review, execution,
reversal — not just the missing trigger.

## What "best" means here

Ranked. The ranking is situation-specific and the situation is unusual: **the same code serves two
legal roles.** `phased requirements.md:687` requires the platform to "support direct-to-student
service and white-label agency sales from the same platform", so:

- On an **agency tenant**, the agency is the data controller and Tehsil is the processor. The
  student is a third party to that contract, with paid work in flight.
- On **Tehsil's own tenant**, Tehsil is the controller and the student is the paying customer.

The mechanics of erasure are identical on both. The obligations around them are not. A student
deleting their account here is also not a student deleting a note-taking app: they may hold a live
application to a university with a deadline.

1. **Never destroy work the student did not mean to destroy.** They may hold a live application to a
   university with a deadline. Erasure is their right; a one-click path to it that does not tell them
   what they are giving up is a trap, not a feature.
2. **One flow, two legal roles, no branch.** Every path must be correct whether Tehsil is controller
   or processor. A branch on "which kind of tenant is this" is a silent legal failure waiting to
   happen — a wrong branch is invisible until a regulator finds it. Default to the strictest reading
   on both channels rather than tailoring behaviour to one.
3. **Never claim more than happened.** `EXECUTED` must not read as "fully erased" when the login
   survived, and "scheduled for deletion" must not be worded as "deleted".
4. **No state without an exit.** Every state a request can enter needs something that moves it out.
   A blocked request nobody can see is worse than a refused one.
5. **Fails closed, and every transition is attributable.**
6. **Reuses existing seams.** `advance_deletion` unchanged where possible; `current_membership`,
   `rate_limited`, and the `EuropassCanaryRule` scheduling shape already exist.
7. **No duplicated state.** Two sources of truth for one fact drift, and drift here means a student
   locked out forever or erased while working.
8. **Smallest thing that is true.**

**Criteria 1 and 8 conflict, and 1 wins.** The pure one-click flow is the smallest thing and it is
the one that can silently destroy an in-flight application. **This is the judgement call in this
document.** Inverting it means a student who clicks delete while an application sits at a German
university loses the agency's ability to service it, having been told nothing.

## Two decisions taken during design

**The window is thirty days, not fourteen.** Decided 2026-09-10. It matches what the large consumer
products do, and GDPR's one-month limit is a limit on *responding*, which happens the moment the
student clicks — the request is acknowledged, the account is locked and the execution date is stated
on the screen. Execution then falls at the edge of that month rather than inside it, which is the
deliberate trade: a longer window is a longer chance to undo a decision that cannot be undone
afterwards.

`DELETION_WINDOW` is one constant in `apps/audit/deletion.py`. Changing it never moves a date a
student has already been shown, because `execute_after` is stored (see below).

**The agency is notified, not consulted.** Decided 2026-09-10. The student's click is the decision;
the agency finds out.

On a **direct-to-student tenant** this needs no justification beyond the ordinary: Tehsil is the
controller and the customer is closing their own account.

On an **agency tenant** it is Tehsil, the processor, acting on a decision that formally belongs to
the controller. That is lawful as a **standing documented instruction**, which means
`tenancy.AgencyDataUseAgreementVersion` has to carry that term. A paperwork obligation, not a code
one, recorded here so a pilot does not discover it.

**The code does not branch on the difference, and must not start.** Criterion 2: one flow, both
roles. The notification is the owner screen below, and it needs no `Agency` flag for "this tenant is
Tehsil's own, do not notify" — it is the same obligation discharged two ways, the agency's
notification on one channel and Tehsil's own operations queue on the other. A boolean to suppress it
would buy nothing and introduce exactly the branch this criterion forbids.

## The flow

A student clicks "Delete my account", picks a reason from a fixed list, and confirms. Immediately:

- Their account is locked. Every page shows one screen: *"Scheduled for deletion on 10 October.
  Restore my account."*
- Nothing is erased yet.
- On day 30 a scheduled job runs the erasure engine.
- Until then, one click restores everything.

If something blocks the erasure — a legal hold, a missing retention policy, or an application in
flight — the lock still happens, the screen says which and why, and the request waits on the agency
owner's screen instead of on the clock.

## The state machine changes almost nothing

`_TRANSITIONS` in `apps/audit/deletion.py` gains one target:

```python
_TRANSITIONS = {
    "REQUESTED": {"RETENTION_REVIEW", "CANCELLED"},
    "RETENTION_REVIEW": {"APPROVED", "DENIED", "CANCELLED"},
    "APPROVED": {"EXECUTED", "CANCELLED"},
    "DENIED": {"CANCELLED"},
}
```

`CANCELLED` needs no entry of its own: `_TRANSITIONS.get("CANCELLED", set())` is already empty, so
it is terminal for free. `EXECUTED` is terminal the same way, and already is.

`DENIED -> CANCELLED` exists so a student whose erasure the agency refused is not stranded behind a
lock with no way back in.

**The student's click walks the request straight to `APPROVED` in the same web request.** That is
not ceremony. The `APPROVED` transition is where `legal_hold` and the `RetentionPolicy` check live,
so running it synchronously is how the student learns *at the moment they click* whether something
is held. `DeletionBlocked` leaves the request in `RETENTION_REVIEW`.

`RETENTION_REVIEW` therefore now means **"requested, not yet approvable"** — which is a fair reading
of its own name, and the reason this design adds no state for it. `DENIED` keeps its existing
meaning: the agency's answer after that review.

`APPROVED` means the clock is running. Nothing else drives `EXECUTED`.

## Four new fields on `DeletionRequest`

| Field | Type | Why |
|---|---|---|
| `reason` | `CharField(choices=...)` | The student's answer to "why are you leaving": `NO_LONGER_APPLYING`, `PLACE_ACCEPTED`, `SWITCHING_AGENCY`, `PRIVACY`, `OTHER`. **A fixed list, no free text.** Free text from a student is personal data that would itself need redacting; a fixed list avoids the problem entirely and gives the agency a usable signal. |
| `execute_after` | `DateTimeField(null=True)` | The date the student was *told*. Stored, not computed from `created_at + 30 days`, because changing the window later must never silently move a date someone has already seen. |
| `review_reason` | `CharField(choices=..., blank=True)` | Why the request stopped in `RETENTION_REVIEW`: `LEGAL_HOLD`, `NO_RETENTION_POLICY`, `APPLICATIONS_IN_FLIGHT`. This is what the owner screen displays. |
| `identity_retained_reason` | `CharField(choices=..., blank=True)` | Which of three cases left the login alive. See "Splitting `identity_retained`". |

All four are **`KEEP`**, added to `KEEP["audit.DeletionRequest"]` in the same change. They are the
record of *what was erased*, which must survive the erasure. The classification-completeness test
fails until they are classified; that failure is the enforcement working.

`execute_after` is written by `advance_deletion` itself on the `APPROVED` transition —
`timezone.now() + DELETION_WINDOW`, a module constant of 30 days. One writer, so the student-initiated
path and the owner's release path cannot disagree.

**That transition's save must gain the field.** `advance_deletion` ends its non-`EXECUTED` path with
`request.save(update_fields=["state"])`, which would drop a freshly-assigned `execute_after` without
error. The result is an `APPROVED` request with `execute_after=NULL` that the scheduler's
`execute_after__lte` filter never matches — an erasure that silently never runs, on a request the
student was shown a date for. `update_fields` becomes `["state", "execute_after"]`.

## The in-flight check

`apps/portals/models.py::Application.State` has `SUBMITTED` and `CONFIRMED`: an application sitting
with a university right now. Thirty days after a student clicks delete, `ApplicationStep.detail`
and every document are redacted. The application still exists at the university; the agency can no
longer act on it, contact the applicant, or answer a request for documents.

Neither existing guard catches this. `legal_hold` is a manual flag nobody has set. The
`RetentionPolicy` check only asserts a policy row exists.

So `request_deletion` counts the student's applications in `SUBMITTED` or `CONFIRMED` and, when any
exist, stops at `RETENTION_REVIEW` with `review_reason="APPLICATIONS_IN_FLIGHT"` rather than walking
to `APPROVED`. The student is told plainly, on the lock screen:

> You have 2 applications in progress. Deleting now means we cannot act on them. Your agency will
> review this request.

**This check lives in the service, not in `advance_deletion`.** It is product policy, and the engine
holds mechanics. The ordinary student — nothing submitted — still gets the pure one-click flow.

## The lock

One check in `TenantMembershipMiddleware`, immediately after `require_staff_mfa`: for a `STUDENT`
membership, on a path that is not one of the two deletion URLs, redirect to the pending screen when
an open `DeletionRequest` exists. Exactly the shape `_MFA_SETUP_PATH` already uses to keep the MFA
setup page reachable for a user the gate would otherwise block.

**Deliberately a query, not a column.** An earlier draft of this design put a
`Membership.deletion_scheduled_at` flag on the membership row that middleware has already fetched,
to save the query. That was wrong twice over. It is a second source of truth for a fact
`DeletionRequest.state` already holds, and the two drift silently in both directions: a flag left
set after a cancellation locks a student out permanently, and a flag cleared while the request is
still `APPROVED` lets someone be erased mid-session. It also optimised a query nobody had measured.

```python
# ponytail: one .exists() per authenticated student request. Add a denormalised
# flag on Membership only if this is ever measured to matter -- it is a second
# source of truth for DeletionRequest.state and it drifts.
```

**"Open" is every state except `CANCELLED` and `EXECUTED`.** `REQUESTED`, `RETENTION_REVIEW` and
`APPROVED` are self-evidently open. `DENIED` is open too: the agency refused the erasure, so nothing
was erased, but the student asked to leave and their access stays closed until they restore it.
`EXECUTED` needs no entry — `advance_deletion` has already set `Membership.active = False`, so
`middleware.py:64` finds no membership and the request never reaches this check.

`Membership.active` cannot serve as the lock either: the identity-erasure design established that
`active=False` makes `middleware.py:64` find no membership, which 403s the student out of the very
restore screen they need. `active` is written only by `advance_deletion` on the `EXECUTED` path, as
it is today.

The check needs `models.Index(fields=("tenant", "student", "state"))` on `DeletionRequest`.

## Restore

`POST` to the restore URL moves the request to `CANCELLED`. Nothing was erased, so nothing is
undone — the lock simply stops applying, because the middleware query no longer matches. That is the
whole reversal mechanism, and it is a property of having one source of truth rather than a feature
that had to be built.

Available from `REQUESTED`, `RETENTION_REVIEW`, `APPROVED` and `DENIED`. Not from `EXECUTED`, where
there is nothing left to restore.

**`DENIED` needs its own words on that screen**, and they are the hardest to write: the request was
refused, nothing will be erased, and the account stays closed until the student reopens it
themselves. A student left staring at a countdown that will never fire would be the exact
claim-more-than-happened failure criterion 3 forbids, pointing the other way.

## The scheduler

`apps/audit/management/commands/execute_due_erasures.py`.

**The command is built. Its schedule is deferred, 2026-09-11.** The EventBridge rule that runs it
daily — mirroring `EuropassCanaryRule` in `infra/template.yaml`, same ECS `RunTask` shape against
`WorkerTaskDefinition`, `ScheduleExpression: "rate(1 day)"` — is the one piece of this design left
unbuilt. Nothing is deployed for it to run against, so it would be a scheduled job with no work and
no way to observe it working.

Until it exists, `EXECUTED` is reached by running the command by hand.

> **Deployment gate — this is not a nice-to-have.** A student whose request sits in `APPROVED` is
> locked out and waiting, and their statutory month is running. A deployment where the command is
> never invoked turns every erasure request into an indefinite lockout with no erasure: the worst of
> both outcomes, and invisible, because the screens all say the right thing. **The rule must exist
> before the first real student reaches this flow.** Recorded in CLAUDE.md as well, because the
> person who deploys is not necessarily the person who read this.

Four things it must get right, and every one of them fails silently.

**It must open a transaction and set the GUC, exactly as the middleware does.**
`HostTenantContextMiddleware` wraps every web request in `transaction.atomic()` with
`set_local_tenant`, and `advance_deletion` relies on that ambient context for the work it does
*before* its own `transaction.atomic()` — notably `delete_student_documents`, which reads
tenant-scoped `DocumentVersion` rows. A management command has no middleware. Without the wrapper,
those reads match zero rows under RLS and the erasure records `EXECUTED` over documents nothing
touched. This is the same failure the comment in `deletion.py` already warns about, one layer out.
`set_local_tenant` issues `SET LOCAL`, so it must be re-issued inside **every** transaction, not
once per agency.

**One transaction per request, never one per agency.** An earlier draft of this section wrapped a
whole agency's batch in a single `atomic()`. That loses data: `delete_student_documents` purges S3
*outside* the database, so an S3 error on the fourth student rolls back the first three students'
`EXECUTED` rows while their objects are already gone. Those three then re-run tomorrow against
documents that no longer exist, and in between the database says they were never erased. The unit of
atomicity is one erasure, because the unit of irreversible side effect is one erasure.

**It must lock the row and re-read the state.** A student can restore at any moment, including
between the scan and the erasure. `advance_deletion` checks `request.state` on the **in-memory**
object, so a `DeletionRequest` scanned as `APPROVED` and cancelled a second later is erased anyway —
irreversibly, against a request that no longer exists. `select_for_update()` plus a state re-check
closes it: the restore view blocks on the lock, and if it won the race the re-check skips the row.

**It must not hold an outer scope.** `tenant_scope` refuses to *switch* tenants
(`TenantContextConflict`), so the loop enters and leaves one scope per agency. `Agency` is not
tenant-scoped and carries no RLS policy, so listing agencies from the runtime role works.

```python
for agency in Agency.objects.all():
    with tenant_scope(agency.id):
        with transaction.atomic():
            set_local_tenant(agency.id)
            due_ids = list(
                DeletionRequest.objects.filter(
                    state="APPROVED", execute_after__lte=timezone.now()
                ).values_list("id", flat=True)
            )
        # One transaction per erasure: an S3 failure on one student must not
        # roll back another student's completed erasure.
        for request_id in due_ids:
            try:
                with transaction.atomic():
                    set_local_tenant(agency.id)
                    request = DeletionRequest.objects.select_for_update().get(id=request_id)
                    if request.state != "APPROVED":
                        continue  # restored between the scan and now
                    advance_deletion(request, "EXECUTED")
            except (DeletionBlocked, ObjectStoreError) as error:
                self.stderr.write(f"{request_id}: {error}")
```

Failures are caught per request so one stuck row does not strand the batch, and because each request
owns its transaction, a caught failure leaves every other erasure committed.

## The audit trail

`advance_deletion` writes `deletion.executed` and `deletion.identity_retained` today, both with
`actor=None` and `actor_kind="SYSTEM"`. That covers the machine's own act and nothing else: criterion
5 asks for every transition to be attributable, and four of them are now driven by people.

Each writes one `AuditEvent` with `object_id=request.id`, at the point the transition is made:

| Event | Actor | Written by |
|---|---|---|
| `deletion.requested` | the student's `Membership`, `actor_kind="HUMAN"` | `request_deletion` |
| `deletion.cancelled` | the student's `Membership`, `actor_kind="HUMAN"` | the restore view |
| `deletion.released` | the owner's `Membership`, `actor_kind="HUMAN"` | the owner screen |
| `deletion.denied` | the owner's `Membership`, `actor_kind="HUMAN"` | the owner screen |

`AuditEvent.actor` is a `PROTECT` FK to `Membership`, so a student's own request event pins their
membership row — which survives erasure as an opaque key by design, since redaction deletes no rows.

`DeletionRequest` gains no `requested_by` column. The subject is already `request.student`, and the
actor of each transition is in the audit trail where a reviewer can query it. A column would be a
fifth field carrying what two existing structures already say.

`deletion.requested` and `deletion.cancelled` are written **before** the walk to `APPROVED`, so a
request that is diverted into `RETENTION_REVIEW` still records that the student asked.

## The owner screen

Three lists, gated on `current_membership(request, Membership.Role.OWNER)`: requests in
`RETENTION_REVIEW` awaiting a decision, requests in `APPROVED` counting down (this is the
notification the agency gets, and the only one there is), and recently `EXECUTED` requests where
`identity_retained` is true.

The first list is the one with actions. Each row shows the student, the request date,
and `review_reason`. Two actions, both calling `advance_deletion` unchanged: **release**
(`-> APPROVED`, which starts the 30-day clock) and **refuse** (`-> DENIED`).

`review_reason` is not cleared on release. It is the record of why the request was held, and the
`AuditEvent` says who released it; erasing the reason would leave a released request
indistinguishable from one that was never held.

This screen is not optional, for three reasons that are easy to miss.

**It is the only exit from `RETENTION_REVIEW`.** There is no agency work queue in this codebase —
`concierge.RequiredAction` is student-facing and `report_portal_interventions` is a CLI report.
Without this screen, a held request is seen by nobody while the student has been told their records
are being kept.

**It is the only place a partial erasure is ever reported.** After erasure the student is gone and
cannot be told anything, so `identity_retained` has exactly one audience and this is it, with the
reason spelled out.

That list shows the **membership id and the reason, never the name.** `Membership.display_name`
reads through to `auth.User`, and in all three retention cases the login was deliberately *not*
scrubbed — so rendering it would put an erased person's real name back on the screen of the agency
that erased them. The reason is what the agency has to act on; two of the three cases are
misconfigurations to fix rather than people to look up, and the audit trail carries the identity for
anyone with a lawful need for it.

**It is the agency's notification.** No email exists in this codebase, so the `APPROVED` list is how
an agency learns a student is leaving — in time to act on it, since the window is thirty days.

## Splitting `identity_retained`

`redact_identity` returns a bare `bool` today, which conflates three cases that need different words
and different human responses:

| Case | What it means | What the agency should do |
|---|---|---|
| `STILL_ENROLLED` | the person holds an active membership at another agency | nothing — lawful and expected |
| `STAFF_ACCOUNT` | `is_staff` or `is_superuser` was set | a misconfiguration; someone must look |
| `NOT_A_STUDENT` | the erased membership's role was not `STUDENT` | wrong operation; erasure is a student right |

So `redact_identity` returns `IdentityRetention | None` — a `TextChoices` defined in
`apps/audit/identity.py`, with `None` meaning the login was scrubbed. `advance_deletion` becomes:

```python
retention = redact_identity(user_id=..., membership_role=...)
request.identity_retained = retention is not None
request.identity_retained_reason = retention or ""
```

`identity_retained` keeps its meaning, its classification and its existing tests. The reason is
additive.

## Two kinds of retention, and only one of them is `legal_hold`

Routine statutory retention and an exceptional preservation order are different things, and this
design was briefly confused about which one `legal_hold` is.

**Routine statutory retention is already handled, statically, by the classification map.**
`KEEP["concierge.Receipt"]` survives every erasure, with the German §147 AO eight-year basis written
into its own comment. So an ordinary erasure already means *account gone on day 30, records the law
requires kept*. No flag, no review, no state — the map is a per-record retention mechanism and it
does exactly this.

**`legal_hold` is the other thing: a per-student preservation order.** Litigation, or a regulator
telling the agency to destroy nothing about this person. All-or-nothing is the *correct* semantics
there — a preservation order that erased everything except the receipts would not be one. Blocking
the whole request and routing it to a human is right.

So `legal_hold` stays a boolean and the redaction engine is unchanged. An earlier draft treated the
routine case as `legal_hold`'s job, concluded the engine needed per-record holds, and recorded that
as an open question. It was never open; the requirement was already met by a different mechanism.

Nothing sets `legal_hold` today. Giving it a writer is the operator surface for preservation orders,
which is a separate change with its own approval trail.

## Derived data and the ML corpus

**Governed by `phased requirements.md` §6.1, "Opt-in platform-intelligence pipeline", which already
decides this.** That section is quoted rather than reasoned around, because it is more specific than
anything this document would derive.

### Extraction happens during ordinary use, never at erasure

§6.1: *"Extract an allowlisted minimum feature set **inside the tenant boundary** rather than copying
raw tenant databases."*

So a training row is created while the student is active, by the opt-in pipeline, under an agreement
that already permits it. **Erasure never manufactures a dataset.** Converting a student's record into
a pseudonymous training row at the moment they ask to be deleted is redundant when the pipeline has
already run, and impermissible when it has not — the one moment the platform is least entitled to
hold someone's data is not the moment to start holding it for a new purpose.

This is also the only reading compatible with the engine that exists: `redact_student` overwrites
`snapshot`, `payload`, `content` and `result` in place. There is nothing left to extract by the time
`EXECUTED` is reached.

### `Pseudonym`

A UUID primary key, a tenant, and a unique FK to the student. Derived rows carry the pseudonym and
never `student_id` — §6.1: *"Use random cohort-scoped tokens or keyed pseudonyms with **keys isolated
from the derived dataset**; predictable hashes are prohibited."* A random UUID primary key satisfies
both halves.

**The pseudonym is the primary key deliberately.** `Pseudonym` is student-reachable, so the
completeness test demands every field be classified. `classifiable_fields()` skips primary keys and
relations, so this leaves exactly one field: `KEEP["audit.Pseudonym"] = ("created_at",)`, a bare
timestamp on a row the erasure deletes outright. A separate `key` column would be a second thing to
classify and a second thing to get wrong.

**Nothing writes `Pseudonym`, and that is the point.** The delete path has to exist before the data
does — `documents.EuropassRenderCache` is already in this repo as derived data that escaped the
completeness test because nobody thought about it at the time. A tripwire test mirrors the existing
`test_receipt_has_no_writer_yet`.

**The model carries its own docstring saying so.** A table with no writer and no obvious purpose is
the kind of thing a later reader deletes as dead code, and deleting it silently removes the deletion
guarantee from every derived table that would have pointed at it. The docstring states what it is
for, that `CASCADE` is mandatory for anything referencing it, and that the absence of a writer is the
design rather than an omission. CLAUDE.md carries the same, for readers who never open the model.

### One dataset, deleted on erasure. That is the whole rule.

Decided 2026-09-11, and it is an MVP decision with a stated expiry. Nothing is deployed, no student
exists, and which features carry signal is a question for analysis on a real corpus rather than for
argument now. So the platform keeps everything it has, at full precision, and a student's erasure
takes their derived rows with them.

Concretely, and this is the entire derived-data contract this document specifies:

- Every derived table's FK to `Pseudonym` is **`on_delete=models.CASCADE`**.
- `advance_deletion` deletes the `Pseudonym` row on the `EXECUTED` path, and the derived rows cascade
  away with it.

Propagation is enforced by the schema. Nothing depends on a policy comment, a review, or anyone
remembering.

**No threshold, no second variant, no `SET_NULL`, no re-identification assessment — none of it is
built here.** Those remain in `phased requirements.md` §6.1 as what the opt-in pipeline must satisfy
*when it is built*, and they are the only lawful route to a row outliving the person it describes.
Today there is no such route and no need for one.

### Why full precision forces the cascade

Worth stating so the decision is not quietly reversed later by someone who reads only the table.

Anonymity is not "the key is gone" — it is *this row describes more than one person*. With an exact
institution name, an exact degree title, a programme and an intake year, sometimes it describes
exactly one. Counting whether it does is the entire content of a threshold, and a design that keeps
full precision **and** retains rows through an erasure has no answer to the question.

Aggregating instead does not escape it: a counter reading
`Baku State, BSc CS, TUM MSc, 2026, rejected -> 1` says one person with those attributes was
rejected. Same problem, fewer columns.

So full precision and survival-through-erasure are the two things that cannot both be had. This
document takes precision, because precision is what an MVP needs and survival is what a mature
corpus needs, and the platform is the former.

### What this costs, measured rather than feared

**A trained model does not unlearn.** An erasure removes a student from *future* training sets, not
from a model that already learned from them. What is actually lost is the ability to reproduce a past
training run exactly, plus one student's marginal contribution to the next retrain — across the small
fraction of users who ever delete.

The threshold in §6.1 is what buys that back, later, on a corpus large enough for it to mean
anything. Until then it would be machinery guarding data that does not exist.

### The application stores everything, and nothing here changes that

Said plainly because the table below is easy to misread as a storage rule. It is not.

**Everything the platform already collects, it keeps.** CVs, statements, documents, verified facts,
grades as awarded, counselor notes, messages, application steps — all of it, in the tenant's own
database, at full fidelity. That is the status quo, it needs no change, and the erasure engine
already reaches it: 124 fields across 32 models.

The table below governs a **second, derived copy built for training** — one that does not exist and
will not until §6.1's pipeline is designed. "Never extract" means *not copied into that derived
dataset*, never *not stored*.

### Where the deferred analysis happens

The MVP decision above defers a question — *which features carry signal?* — to analysis on a real
corpus. That analysis has a boundary, and it is the moment this design is most likely to be
undone by someone who means well.

**It happens inside the tenant, against live data, under RLS.** Not by exporting a table, not by
copying a database to a laptop, not by assembling a cross-tenant CSV to look at in a notebook.
`phased requirements.md` §6.1 prohibits copying raw tenant databases and prohibits training on them
directly; :318 prohibits cross-tenant reuse of personal data by default. Those clauses bite precisely
when someone first says "let me just pull the data and have a look".

A cross-tenant corpus is the thing the opt-in pipeline exists to produce, lawfully, under an
agreement. There is no informal version of it.

### What a derived extract would carry

Provisional, and `phased requirements.md` §6.1 now says so: this list is a starting point recorded
before the pipeline is built, to be revised by analysis on a real corpus.

| Extract | Never extract into the derived dataset |
|---|---|
| Degree title, level, field | Name, email, phone, address, date of birth |
| Institution name and country | **Named** societies, posts, employers, fellowship names |
| **Grade as awarded, plus its scale** | CV and statement-of-purpose text |
| Language test result | Document files, counselor notes, messages |
| Extracurriculars as counts by category | Portal credentials |
| Fellowships and awards as counts by tier | |
| Programme applied to, intake year | |
| Admission outcome | |
| Funding outcome and award band | |

**A grade is stored as awarded, never converted.** Conversion between grading systems is one-way:
German 1.0-5.0 is inverted, a British classification is neither scale, and a normalized figure can
always be derived later from the awarded grade and its scale while the awarded grade can never be
recovered from someone's normalization. Banding and normalization are modelling decisions, taken
when there is data to take them against.

**Counts, never names — in the extract.** "President of the Azerbaijani Robotics Society, 2024" is
one person and no treatment repairs that, so a derived row carries the count and the category. The
tenant's own record keeps the full text, as it does today; this is a rule about the copy, not the
original.

**Undecided: nationality.** It matters for admission probability through visa and quota rules, and it
is not special-category data under GDPR Article 9, but it is close enough to deserve a decision of
its own rather than silent inclusion. Country of the prior institution is in the list and proxies
much of it.

### The outcome label does not exist yet, and nothing here works without it

Found while writing this section, across all 73 models in the repository. **Nothing records whether a
student was admitted, rejected or funded.**

- `portals.Application.State` ends at `CONFIRMED`, which means the *portal* accepted the submission —
  not that the institution accepted the applicant.
- `funding.StudentDecision.Decision` is `REJECTED`/`REPLACED`/`CONSIDERED`, recording a *student*
  rejecting a recommendation.

So the corpus this design protects has no label to train against, and §6.1's own rule — extract only
records carrying a resolved outcome — is currently unsatisfiable by construction. Terminal admission
states, a funding award result, and the date each was learned are a prerequisite for the whole
pipeline. `phased requirements.md` §6.1 now says so.

**This is not this design's job to fix**, and it changes nothing here: `Pseudonym` and its cascade
are correct whether or not a label exists. It is recorded because the gap is invisible from inside
the ML work — it looks like a modelling problem right up until someone goes looking for the column.

### Who may authorise training at all is a different question, with two different owners

Not this design's decision, but named here so nobody wires a trainer without passing the gate.
`phased requirements.md:318` prohibits cross-tenant reuse of personal data by default, and :319
requires a separate approved agreement and an applicable lawful basis.

- **Agency tenants:** `tenancy.AgencyDataUseAgreementVersion` — `permitted_purposes`,
  `eligible_categories`, `lawful_basis_review_state`, `revoked_at`. Built.
- **Direct-to-student tenants:** the student's own consent, given to Tehsil as controller. **No model
  exists for this.** `documents.ConsentEvent` is not it — that records who approved a document for
  use, which is a different consent entirely. This is a real gap in the opt-in pipeline and belongs
  to its spec, not this one.

Whichever gate applies, a student who has asked for erasure has objected. **The erasure path acts
regardless of what any agreement permits**, which is what the `CASCADE` default already guarantees.

### Two things that are true and cannot be fixed here

- **A model already trained on a student does not forget them when the key dies.** Nothing practical
  follows from this at the erasure layer; it is recorded so it is not discovered later. §6.1 already
  requires every run to be bound to approved dataset versions, which is where the question belongs.
- **Platform ownership is not anonymity.** `phased requirements.md` says so directly: *"Contractual
  platform ownership of approved datasets and model assets does not itself make the data anonymous or
  remove privacy obligations."*

## Wording

The screen says **"scheduled for deletion on <date>"**, never "your data has been deleted". If it can
be reversed for thirty days it is not deleted, and a false statement to a data subject about the
status of their erasure is the one sentence in this flow a regulator would actually read.

## Rate limiting and confirmation

`rate_limited("account-deletion", membership.id, limit=5, window_seconds=3600)` on the request POST,
reusing `apps/ratelimit.py` as CLAUDE.md requires rather than writing a new limiter. The request is a
`POST` behind an explicit confirmation step; no destructive action is reachable by `GET`.

## Enforcement

1. **The happy path.** A student POST creates a `DeletionRequest`, reaches `APPROVED`, and sets
   `execute_after` thirty days out.
2. **The lock applies.** With an open request, any student page redirects to the pending screen; the
   pending screen and restore URL do not.
3. **Restore works and erases nothing.** `CANCELLED` lifts the lock and every field survives.
4. **An in-flight application diverts the request.** A student with a `SUBMITTED` application lands
   in `RETENTION_REVIEW` with `review_reason="APPLICATIONS_IN_FLIGHT"` and **no** `execute_after`.
5. **A legal hold diverts the request**, with `review_reason="LEGAL_HOLD"`.
6. **The scheduler respects the clock.** Only requests past `execute_after` execute.
6a. **A restore that wins the race is honoured.** Set a request to `CANCELLED` after the scan and
   before the erasure, and assert nothing was erased. Without the `select_for_update` re-check this
   passes only by luck, and the failure it guards is an irreversible erasure of a request the
   student had already withdrawn.
6b. **One failure does not roll back another erasure.** Two due requests, the second raising from
   the S3 purge: assert the first is still `EXECUTED` after the command returns. Confirmed RED
   against a version that wraps the agency's batch in one `atomic()`.
6c. **`execute_after` survives the `APPROVED` save.** Assert it is non-null on the row *reloaded
   from the database*, not on the in-memory object — `update_fields` drops it silently and an
   in-memory assertion cannot see that.
7. **The scheduler actually purges, under real RLS.** Behind the `rls_enforced_orm` fixture: run the
   command and assert the student's documents are gone. This is the only test that can observe the
   missing-`set_local_tenant` failure — on the ordinary suite the test role is `BYPASSRLS` and the
   command passes whether or not it would work in production. Same reasoning as
   `tests/audit/test_identity_rls.py`, and it must be confirmed RED against a version of the command
   with the wrapper removed.
8. **The three retention reasons are distinguished.** One test per case.
9. **The owner screen is tenant-scoped and role-gated.** A `COUNSELOR` gets 403; agency A's owner
   cannot see agency B's requests.
10. **`Pseudonym` has no writer** (tripwire), and `advance_deletion` leaves no `Pseudonym` row for
    the erased student.
11. **Deletion propagates to derived rows.** A throwaway test-only model with a `CASCADE` FK to
    `Pseudonym`, a row for the erased student, and an assertion that the row is gone after
    `EXECUTED`. The whole propagation guarantee is one `on_delete` argument; nothing else would
    notice it being changed to `SET_NULL` or `PROTECT`, and this test does.
12. **The rate limit holds.**
13. **Every human transition is audited.** One test asserting `deletion.requested`,
    `deletion.cancelled`, `deletion.released` and `deletion.denied` each carry the acting
    membership and `actor_kind="HUMAN"` — and that a request diverted into `RETENTION_REVIEW` still
    records `deletion.requested`.

## Scope: this is three plans, not one

Written as one design because the pieces only make sense together, but it should be *implemented* in
three slices, each of which leaves the repository working and tested:

1. **Model and engine.** The four fields and the index, `CANCELLED` in `_TRANSITIONS`,
   `execute_after` on the `APPROVED` transition, `redact_identity` returning a reason, `Pseudonym`
   and its `on_delete` contract, and the classification-map entries. No UI, no scheduler. Every test
   in this slice runs against `advance_deletion` directly, which is how the engine is tested today.
2. **The student flow.** `request_deletion` with the in-flight check, the three views, the
   middleware lock, restore, the rate limit, and the audit events.
3. **The command and the owner screen.** The management command with its per-request transactions
   and locking, the RLS test, and the three owner lists. **Not the EventBridge rule** — see the
   deployment gate above.

Slice 1 is the one that must not be rushed: it changes a shipped, tested erasure engine, and
everything after it is additive.

## What this does not do

- **No email.** This codebase sends none, anywhere. The locked screen is the notification.
- **No new `concierge.Notification` rows.** Its `roadmap_item` FK is required and a deletion notice
  is not a roadmap item.
- **No per-record legal hold, and none is needed.** See "Two kinds of retention" above.
- **No agency-initiated erasure.** An agency closing its account, or tenant termination
  (`phased requirements.md:320`), is a different operation over a different subject.
- **No cross-tenant console.** Tehsil staff reach these pages on the agency's own host through the
  existing `SupportGrant`, which already works. No platform change.
- **No ML pipeline.** `Pseudonym` gets a model and an `on_delete` contract, nothing more. The §6.1
  extraction path, its banding and suppression, the schema assessment, the agreement gate and the
  missing direct-to-student consent record are all its own spec.
- **Does not implement a threshold, a second variant or `SET_NULL`.** Those are §6.1's, for the
  pipeline that does not exist. Nothing here retains a derived row through an erasure.
- **Does not schedule the erasure command.** Built and tested; the EventBridge rule that invokes it
  is deferred, under the deployment gate above.
- **Does not add the admission or funding outcome.** Named above as a prerequisite and written into
  §6.1; it belongs to the application data model, not to an erasure path.
- **Does not decide the retention period.** `docs/runbooks/shadow-pilot.md` still carries that as
  unsigned.
- **Does not close `documents.EuropassRenderCache`.** Inherited from the parent design.

## Open questions for review

None. The three questions this document opened were all closed during review, and each is now
recorded where the decision lives rather than in a list at the end:

- **The window** — thirty days. See "Two decisions taken during design".
- **The controller/processor question** — the agency is notified, not consulted, on both channels.
  Same section, plus criterion 2.
- **The legal-hold outcome** — never actually open. See "Two kinds of retention".
