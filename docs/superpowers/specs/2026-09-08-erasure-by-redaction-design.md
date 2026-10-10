# Erasure by redaction

Status: design, awaiting review. Supersedes nothing; `apps/audit/deletion.py` is the code this changes.

## The defect

`advance_deletion` destroys S3 objects and Secrets Manager entries, writes `state = "EXECUTED"`, and
deletes no database rows. A student exercises their right to erasure, the agency's screen says it
happened, and the following survive in Postgres indefinitely:

- `VerifiedFact.payload` — the parsed CV: employment, education, identity facts
- `DocumentDraft.content` — the generated CV, name and contact email included
- `StudentProfileVersion.snapshot` — the profile the recommendations were computed from
- `ApplicationStep.detail["values"]` — the literal values typed into a third-party application form
- `ConversationMessage.body`, `RequiredAction.description`, `Notification.message`,
  `RoadmapItem.result`, `ManualOperation.description`, `RevisionRequest.note` — free text counselors
  and the agent wrote about a named person

Two independent security reviewers found this from opposite ends of the codebase on 2026-09-08.

The failure is not "some data was missed". It is that **the system records a legal claim that is
false**. A later subject-access request, a counselor query, or a database compromise still yields the
complete CV.

Not reachable today: `advance_deletion` has no caller in `apps/`. What made it material is that
`register()` gained an HTTP door, so real uploaded CVs and ingested `VerifiedFact` rows now exist.

## What "best" means here

Ranked. The first is binding; the rest break ties.

1. **Legally true, not aspirational.** If anything surviving can single out the person, the record
   says erased and is not. Under GDPR, anonymisation is irreversible; data that remains
   re-identifiable is *pseudonymised*, is still personal data, and does not satisfy Article 17.
2. **Enforced, not documented.** A rule that lives only in prose drifts. This repository produced
   three such drifts in a single day — Postgres 16 against a suite that tests 17, a Python base image
   against a venv built for another version, and this erasure gap. Enforcement must be a test or a
   database constraint.
3. **Fails closed.** A partial erasure leaves the request `APPROVED`. `EXECUTED` is written only
   after everything else succeeded.
4. **Compatible with §10 unresolved.** `phased requirements.md` §10 lists "Final retention, export and
   deletion periods" as an open launch blocker. The design must not require inventing them.
5. **Preserves the data the ML models need.** The stated product rule: hold the client's information
   while they are a client, then anonymise and keep only what the models require.
6. **Reuses existing seams** rather than inventing machinery.
7. **Weakens no existing invariant.**

## Why deleting rows is the wrong axis

Walking Django's model graph outward from `Membership` reaches **30 models**. Every edge is `PROTECT`
except four `CASCADE`s. The deepest chain:

```
StudentProfileVersion → RecommendationRun → PackVersion → Approval            (counselor record)
                                                        → ConsultationReport  (a deliverable)
                      → RecommendationCandidate → StudentDecision             (the student's choices)
```

`RecommendationRun.profile_version` is `PROTECT`, so deleting `StudentProfileVersion` raises
`ProtectedError`. Deleting the run cascades to `PackVersion`, which `Approval` and
`ConsultationReport` protect in turn.

**The schema was built so student-linked rows cannot be deleted.** Any delete-based erasure must
either relax `PROTECT` — weakening an invariant that exists to stop accountability trails being
orphaned — or destroy records belonging to other people and to the agency's own books. Both fail
criterion 7, and the first two delete-based designs drafted for this problem would have failed at
runtime.

## The design: redact in place

**Overwrite every field that can carry personal data. Delete nothing. Keep every row, FK and
timestamp.**

This hits no `PROTECT` wall, so it cannot fail the way a delete list does. The `Membership` row
survives as an opaque key, which keeps `AuditEvent`'s `HUMAN ⇒ actor IS NOT NULL` check constraint
satisfied — a constraint that rules out the otherwise-obvious "null the actor" approach. Decisions,
amounts, currencies, states, categories and timestamps all survive, which is exactly the structured
residue the models want and exactly what carries no name.

### Field classification, not field-shape heuristics

The obvious enforcement rule — "a retained row may hold no `TextField` or unconstrained `CharField`"
— was tested against the real schema and **rejected**. It both over- and under-fires:

| Field | Type | Heuristic says | Truth |
|---|---|---|---|
| `ServiceEngagement.currency` | unconstrained `CharField` | redact | 3-letter code, no prose |
| `DocumentVersion.scan_result` | unconstrained `CharField` | redact | enum in all but declaration |
| `ConsultationReport.sha256` | unconstrained `CharField` | redact | a digest |
| `RecommendationCandidate.program_name` | unconstrained `CharField` | redact | a *programme*, not a person |
| `ApplicationStep.detail` | `JSONField` | depends | the values typed into an application form |

So the rule is an **explicit per-field classification**, and the test enforces that the classification
is *complete* — not that a heuristic holds.

Three classes:

- **REDACT** — overwritten on erasure.
- **KEEP** — structural, enum-like, numeric, or about a programme rather than a person.
- **UNDECIDED** — depends on §10; erasure refuses to run while any field is in this class, so the
  question cannot be silently skipped.

### Initial classification

REDACT:

| Model | Field |
|---|---|
| `accounts.StudentProfileVersion` | `snapshot` |
| `documents.VerifiedFact` | `payload`, `source_ref` |
| `documents.DocumentDraft` | `content` |
| `documents.RevisionRequest` | `note` |
| `concierge.RoadmapItem` | `result` |
| `concierge.RequiredAction` | `description` |
| `concierge.Notification` | `message` |
| `concierge.ManualOperation` | `description` |
| `concierge.ConversationMessage` | `body` |
| `portals.ApplicationStep` | `detail` |
| `tenancy.Membership` | `application_email`, `academic_email` |
| `funding.Approval` | `reason` |

Each REDACT entry also needs a **subject path** — the FK chain from that model to the student the
erasure is about. These are written by hand, never derived. A shortest-path search finds *a*
`Membership` FK, not the student's, and picks the wrong one on three models:
`ManualOperation.actor` and `Approval.actor` are staff, and `RevisionRequest.requested_by` is the
requester. Filtering `ManualOperation` by `actor` would redact operations performed *by* the erased
person and leave every operation written *about* them.

KEEP: every `currency`, `state`, `status`, `kind`, `scan_result`, `content_type`, `sha256`,
`s3_version_id`; `AuditEvent.event`; `RecommendationCandidate.program_name`.

KEEP, resolved 2026-09-08, each with the constraint that makes it true:

- `funding.ConstraintOverride.risk_text_shown` — `apps/documents/overrides.py` sets it to
  `violation.rule.rule_text`, the catalog rule's own wording. Identical for every student who hits
  that rule; it exists to prove which warning was shown, since rule text changes. No personal data.
- `funding.EvaluationExample.expected_structured_result` — this is the data the product exists to
  keep: labelled corrections for model evaluation. **Nothing writes it today.** So this is a
  constraint on whoever builds the writer, not an observation: it may hold schema-constrained model
  output only, never free text or an identifier, and `allowed_purposes` governs reuse. The
  classification test cannot check the content of a field with no writer — see "Owed" below.
- `concierge.ApplicationFeeLedgerEntry.masked_card_reference` — a masked financial reference. Kept
  with the ledger entry it belongs to; whether the ledger itself has a statutory retention floor is
  §10's question, and redaction does not prejudge it.

  KEEP **by constraint**, added 2026-09-08 after review: `ApplicationFeeLedgerEntry` has no writer,
  so this field is kept on the strength of its *name* implying the value arrives already masked, and
  nothing enforces that. The constraint on whoever builds the writer: it may hold a masked reference
  only — last four digits or a processor token — never a full card number, never a cardholder name,
  never anything identifying the payer. A fuller reference makes it REDACT with subject path
  `student_id`, not KEEP. Tripwire: `test_masked_card_reference_has_no_writer_yet`.

- `concierge.Receipt.object_key` — **the receipt survives erasure, because tax law outranks the
  request.** GDPR Article 17(3)(b) withdraws the right to erasure where processing is necessary to
  comply with a legal obligation, and a statutory accounting-retention duty is exactly that. In
  Germany accounting receipts run **8 years** under §147 AO — reduced from ten on 1 January 2025 by
  BEG IV — counted from the end of the calendar year the document was created, not its date. The
  agency's own jurisdiction sets the number; Article 17(3)(b) sets the shape, and the shape does not
  vary.

  This is KEEP **by constraint, not by inspection**: nothing writes `Receipt` today, so there is no
  content to look at, and the classification is a promise about code that does not exist yet. Four
  rules make the promise true, and each one silently falsifies it if broken:

  1. **The key stays opaque.** `object_key` is kept, so whatever string it holds outlives the
     erasure. Every existing key in the codebase is UUID-shaped — `quarantine/{tenant}/{document}`,
     `tenants/{tenant}/reports/{pack}/{digest}.html`. A human-readable key naming the payer would
     put a name in a field this document promises is safe to keep.
  2. **Retained means restricted, not available.** The exemption keeps the receipt *for the tax
     purpose*. It does not license leaving it reachable in the product; that is GDPR Article 18.
     `apps/audit/services.py` already pulls receipts into the student dossier via
     `ledger_entry__student_id`, so that surface must honour the restriction or "erased" means
     "still in the report we hand people".
  3. **It is destroyed when the period expires.** Retention is a floor, not permission to keep it
     forever: when the statutory window closes the ordinary duty to delete returns. The period is
     §10's to set; `created_at` is already there to count from.
  4. **It covers the receipt and nothing else.** The exemption is for the financial record. It is
     not a reason to keep the CV, the profile snapshot or the correspondence. This rule exists
     because "we are legally required to keep records" is the usual way a narrow retention duty gets
     widened into keeping the whole file.

  Enforcement is a tripwire, not a check: the completeness test cannot inspect a field with no
  writer, so a test asserts `Receipt` has no rows and fails the day someone builds the writer,
  forcing these four rules to be read. Same pattern as `EvaluationExample` above.

REDACT, with the stored object purged first:

- `reports.ConsultationReport.object_key` — **the delivered PDF may name the client.** Putting the
  student's name on their own consultation report is the correct product behaviour and the template
  is not constrained. What changes is the *stored* copy: at erasure the S3 object is purged and
  `object_key` redacted, exactly as `DocumentVersion` is handled.

  Nothing is lost by this, which is why it is the cheap answer rather than a sacrifice. The report is
  a rendering of rows that survive anyway — `RecommendationCandidate` holds `program_name`,
  `funding_gap`, `currency`, `eligible` and `evidence_confidence`, and `PackCandidate` ties them to
  the pack version, all KEEP-class. The recommendations outlive the erasure; the personalised
  rendering of them does not. Re-rendering an anonymised replacement was considered and rejected: it
  makes erasure depend on a template's behaviour, which is the fragility this design exists to avoid.

`tenancy.AgencyDataUseAgreementVersion` is out of scope: tenant-level, not about the student.

### `concierge.Notification` has no link to the student it is about

REDACT, but not reachable as the schema stands. Found 2026-09-08 while deriving subject paths.

A `Notification` records only its **recipient**. There is no field for who the message concerns, and
that is not a hypothetical gap: `apps/portals/escalation.py::_recipient` routes only
`PERSONAL_ATTESTATION` and `APPLICANT_MFA` to the student. The other four triggers —
`MISSING_FACT`, `UNSOLVED_CHALLENGE`, `AMBIGUOUS_DECISION`, `PORTAL_ERROR` — go to the assigned
counselor, carrying free text about the student's application (`MISSING_FACT` passes
`", ".join(sorted(missing))`, the list of facts missing about that person).

So redacting by `recipient_id` empties the notifications sent *to* the student and leaves the ones
sent *about* her to her counselor — and leaves them unfindable, since nothing in the row names her.

**Fix: give `Notification` a non-null FK to `RoadmapItem`, and redact by
`roadmap_item__student_id`.** Both writers already create a `RoadmapItem` immediately before the
notification, and that row already carries `student=application.student` whoever the recipient is.
One path then covers both cases, because the roadmap item names the subject even when the recipient
is someone else. A `subject` FK straight to `Membership` would work equally well and was rejected as
a second place to record a fact the schema already holds correctly.

### Redaction values

Not `NULL`, and not deletion. Each REDACT field is set to the **empty value for its type** — `""` for
text, `{}` for JSON — so `NOT NULL` constraints hold and "redacted" is distinguishable from "never
set" only through the `DeletionRequest`, which is where that fact belongs.

`object_key` fields on `DocumentVersion` are redacted **after** the S3 purge, because
`delete_student_documents` reads them to find the objects. Order is load-bearing; the existing code
already purges first.

## Enforcement

Three tests. The first is the one that survives contact with future code.

1. **Classification completeness.** Walk the model graph from `Membership`; every field on every
   reachable model must appear in exactly one class. An unclassified field fails CI. This covers
   models nobody has written yet — add a `TextField` to anything student-reachable and the build stops
   until erasure has an answer for it. This is the criterion-2 test.

   **The walk must scan forward foreign keys across `apps.get_models()`, never
   `Membership._meta.related_objects`.** Nine FKs to `Membership` declare `related_name="+"`, which
   creates no reverse accessor, so a reverse walk cannot see `concierge.ConversationMessage`,
   `documents.ConsentEvent`, `documents.RevisionRequest` or `funding.ConstraintOverride`.
   `ConversationMessage.body` is the counselor's free-text correspondence about the student — the
   single most obviously personal field in the schema, and invisible to the obvious implementation.
   The first draft of this design used a reverse walk and missed it. Do not "simplify" the test back
   to `related_objects`.

   **The walk must also be transitive, not one hop. Corrected 2026-09-08 against the real schema.**
   An earlier draft of this section said "a forward scan sees 22". That is the count of models with
   a *direct* FK to `Membership`. The transitive closure is **32**, and nine models are reachable
   only through a chain: `concierge.Receipt`, `documents.DocumentDraftFact`,
   `funding.EvaluationExample`, `funding.PackCandidate`, `funding.PackVersion`,
   `funding.RecommendationCandidate`, `funding.RecommendationRun`, `portals.ApplicationStep`,
   `reports.ConsultationReport`.

   **Four of those nine are classified in this document's own tables** — `ApplicationStep.detail`
   and `ConsultationReport.object_key` (both REDACT), `RecommendationCandidate.program_name` and
   `EvaluationExample.expected_structured_result` (both KEEP). A one-hop test reaches none of them.
   `ApplicationStep` sits behind `Application` and `ConsultationReport` behind
   `PackVersion → RecommendationRun → StudentProfileVersion`; `detail` holds the values typed into a
   third-party application form, named in this document's own defect list. The failure is the same
   one the paragraph above describes, one level up: a walk that stops early classifies nothing it
   cannot see, and silence reads as safety.
2. **Redaction actually happened.** Create a student with data in every REDACT field, run erasure,
   assert each is empty and each KEEP field is unchanged.
3. **Fails closed.** Make one redaction raise; assert the request is still `APPROVED`, `EXECUTED` was
   not written, and nothing was partially redacted.

Tests 2 and 3 mirror the existing `delete_student_documents` tests, which already assert the
all-or-nothing rule for S3.

## What this does not do

- **Does not decide retention periods.** §10 stays open. Rows survive, so any period §10 later
  settles still applies to them.
- **Anonymises the `User` only when no active membership remains.** Closed by
  `docs/superpowers/specs/2026-09-09-identity-erasure-design.md`: the login is scrubbed and the
  membership deactivated on the `EXECUTED` path. When the person is still active at another agency
  the login survives by design, and `DeletionRequest.identity_retained` records that the erasure was
  partial.
- **Does not delete `funding.Approval` or the unused `PackVersion` approval scaffolding.** They are
  fossils of the abandoned counselor-gate design and have no writers or readers, but removing them is
  a separate deliverable.
- **Does not give `advance_deletion` a caller.** Still unreachable in production; that is a separate
  interaction-surface decision.

## Owed: one test that enforces a decision the code cannot yet check

Written now, while the feature it constrains is unbuilt, so it is already in place when someone
builds it.

1. **`EvaluationExample` holds no identifier.** When a writer exists, assert that what it persists
   contains no value drawn from a REDACT field. Until then the model is documented as constrained
   and the classification test records it as KEEP-by-constraint rather than KEEP-by-inspection.

## Open questions for review

All four questions from the first draft were resolved on 2026-09-08 and folded into the
classification above. One remains:

1. Whether redaction should record *that* a field was redacted, beyond the `DeletionRequest` row.
   Argued no: a per-field marker is another place a name could be reconstructed from context.

## Noted while writing this: three fossils of the abandoned counselor gate

Not in scope, recorded because each is a trap — a reader infers a review step the product removed.

- `funding.Approval` and the `PackVersion` approval scaffolding: no writers, no readers.
  `apps/funding/services.py` says why in its own words.
- `apps/concierge/services.py::send_message` accepts the assigned counselor as sender, but no
  counselor ever types: `PERSONAL_ATTESTATION` and `APPLICANT_MFA` escalate straight to the student
  (`apps/portals/escalation.py`), and the consultant's only role is a browser hand-off for
  `UNSOLVED_CHALLENGE`. Chat is student-to-platform.
- `funding.EvaluationExample`: no writers, though this one is a feature not yet built rather than one
  removed.
