---
paths:
  - "apps/audit/**"
  - "tests/audit/**"
  - "apps/privacy/**"
  - "infra/**"
---

## Derived data and the ML corpus — deliberately incomplete

`phased requirements.md` §6.1 specifies an opt-in platform-intelligence pipeline. **Almost none of it
is built, and that is a recorded MVP decision (2026-09-11), not an oversight.** Read
`docs/superpowers/specs/2026-09-10-erasure-console-design.md` before extending any of it.

**What exists:** `audit.Pseudonym` — a random UUID primary key, a tenant, a unique FK to the student.
Nothing writes it. `advance_deletion` deletes its row on the `EXECUTED` path.

**The one rule, and it is load-bearing:** any table holding data derived from a student points at
`Pseudonym` with **`on_delete=models.CASCADE`**, never at `Membership` directly and never with
`SET_NULL` or `PROTECT`. That foreign key *is* the GDPR deletion-propagation guarantee — erasure
deletes the `Pseudonym` row and the database removes the derived rows. A test pins it. The reason the
empty table ships before any writer is `documents.EuropassRenderCache`, which stores a digest derived
from a student's CV with no FK back to them, so the erasure completeness test cannot see it and it
survives erasures today. Nobody decided that; nobody was thinking about deletion when it was written.

**What is deliberately absent:** the extractor, the feature schema, banding, the *k*-threshold, the
generalized second variant, `SET_NULL`, the re-identification assessment, and the data lake. §6.1
holds the requirements for all of it. **Nothing today retains a derived row through an erasure**, and
nothing should until that assessment exists — full precision and survival-through-erasure cannot both
be had, because anonymity means a row describes more than one person and an exact institution plus
exact degree title plus programme plus intake year sometimes describes exactly one. Aggregating does
not escape it: a counter cell of 1 is a person.

**Two prerequisites block the whole pipeline, and both are invisible from inside the ML work:**

- **Outcomes now exist, for the dashboard, not yet as a training label.** `portals.Application.outcome`
  (with `outcome_source`/`outcome_evidence`) and `mailbox.MailSignal.funding_outcome` (86053ef4) record
  what a student was told. Nothing derives a training row from them; whether they are reliable enough
  to be a label (a MAIL-sourced one is a model's reading of a letter) is §6.1's open prerequisite.
- **Direct-to-student training consent has no model.** `tenancy.AgencyDataUseAgreementVersion` covers
  agency tenants only, and `documents.ConsentEvent` is document-approval consent, not privacy consent, and `privacy.Acceptance` records acceptance of
  the Terms or Privacy Notice, not an opt-in to training.
  The platform sells both direct-to-student and white-label (`phased requirements.md:687`), so the B2C
  half of the opt-in gate does not exist.

**"Store everything" is already true and is not what these rules constrain.** The tenant database
keeps CVs, statements, documents, facts, notes and messages at full fidelity, and erasure reaches
them — every field on every model reachable from `Membership`, classified in
`apps/audit/redaction.py` and pinned by `tests/audit/test_redaction_classification.py`. Every restriction above governs a *derived copy built for
training*, which does not exist. When the deferred "which features matter" analysis happens, it
happens inside the tenant against live data under RLS — not by exporting a table or assembling a
cross-tenant CSV. §6.1 prohibits copying raw tenant databases; that clause bites exactly when someone
first says "let me pull the data and have a look".

**Grades are stored as awarded, with the scale, never converted.** Conversion between grading systems
is one-way — a normalized figure derives from an awarded grade, never the reverse — so normalization
and banding are modelling decisions taken when there is data to take them against.

## Erasure: the schedule is deferred, and that is a deployment blocker

`apps/audit/management/commands/execute_due_erasures.py` moves a `DeletionRequest` from `APPROVED` to
`EXECUTED` once its thirty-day window expires. **It is built and tested. Nothing invokes it on a
schedule** — the EventBridge rule was deliberately deferred (2026-09-11) because nothing is deployed
for it to run against. Until then, erasures execute by running the command by hand.

**Before the first real student reaches the deletion flow, that rule must exist.** Model it on
`EuropassCanaryRule` in `infra/template.yaml`: ECS `RunTask` against `WorkerTaskDefinition`,
`ScheduleExpression: "rate(1 day)"`.

The failure this guards against is silent and worse than either half alone. A student who requests
deletion is locked out immediately and their statutory month starts running. If the command is never
invoked, they are locked out **indefinitely and never erased** — and every screen says the right
thing, so nothing surfaces it. Design:
`docs/superpowers/specs/2026-09-10-erasure-console-design.md`.

The owner console (`/owner/deletions/`) is the only exit from `RETENTION_REVIEW` and the only place a
partial erasure is ever reported — after an erasure the student is gone and cannot be told anything,
so `identity_retained` has exactly one audience. `apps/audit/views.py::deletion_console` passes that
list as `.values()` rows **on purpose**: a retained identity is by definition unscrubbed, so a
`Membership` reachable from the template reaches `display_name` and `auth.User`, putting an erased
person's real name back on the screen of the agency that erased them. Do not "improve" it into
`select_related("student")` — `test_the_partial_erasure_list_carries_no_name` asserts the row cannot
reach a `Membership` at all.

One more thing the command's own tests cannot show you: a *caught* exception inside
`transaction.atomic()` is a Python error, not a database one, so it never marks the transaction for
rollback. A test that asserts "one student's failure did not roll back another's erasure" using an
error the command catches passes under a single per-agency transaction too, and proves nothing. The
atomicity boundary is pinned by `test_a_completed_erasure_survives_a_later_failure_in_the_batch`,
which raises something the command does **not** catch. Measured, 2026-09-11.
