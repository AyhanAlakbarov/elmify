# Design: CV identity sourcing and the generation precondition

> **Amended 2026-09-15** by `2026-09-15-student-owned-mailbox-design.md`. The platform-issued mailbox
> is not built and will not be: `Membership.application_email` keeps its column and its gate but
> means *the address the student applies with* — a connected OAuth mailbox or a declared, confirmed
> address. The identity half (name from the ledger, confirmed once) stands unchanged.

Status: design, not yet implemented. Scope: where `CVContent.personal_information.full_name` and `.email` come from, and what `generate_cv` refuses to do without them. Extends the ledger and generation path built in `docs/superpowers/specs/2026-08-21-phase2-cv-engine-design.md` and the ingestion path in `2026-08-22-document-ingestion-design.md`.

## Out of scope here

- **Document requirements** — turning `ExtractedClaims.required_documents` (a tuple of free-text strings scraped from a programme's official source) into a typed per-student requirement set. Needs a document kind on `DocumentVersion`, which has none today.
- **A submission surface** — per-requirement slots, completeness state, "you still owe a transcript". `DocumentVersion` today is `student`, `object_key`, `state`, `scan_result`, `created_at` and nothing else.
- **Mailbox provisioning** — the service that creates a student's `application_email`, registers it on university and funder portals, and scrapes it for results and required actions. This design consumes that address and gates on it; it does not create it. See "Dependency on unbuilt work".
- **Typed ingestion of credential documents** — `ingest_uploaded_cv` extracts `CVContent` from an uploaded CV. A diploma run through it yields near-empty content plus a name, which is all identity needs, so it works. Understanding a transcript *as a transcript* belongs with document requirements.
- `phone`, `date_of_birth`, `sex`, `citizenship` on `PersonalInformation`. SISGP mandates the latter three (R-079) and they have no source today. Same shape of problem as `full_name`; deliberately not solved here.

## The problem

`CVContent` requires `personal_information.full_name` (`min_length=1`) and `.email` (pattern-validated). Nothing supplies either.

- `_facts_payload` (`apps/documents/generation.py:77`) serialises only ledger facts.
- `verification.py`'s `_SPECS` has no entry for `personal_information`, so it is never checked.
- `profile_bridge.py` never writes a name — correctly, because `StudentProfileSnapshot` (`apps/accounts/schemas.py:112`) holds nationality, academic history, budget and weights but no identity at all. It is a matching document, not an identity document.
- `ingest_uploaded_cv` **does** extract identity — it parses the upload into a full `CVContent`, which cannot validate without a name and email — and then discards it. `_SECTIONS` (`apps/documents/ingestion.py:44`) lists seven fields and `personal_information` is not among them, so line 164 iterates past it.

The model is instructed never to invent, and handed a required field with no source. Run against the live API it returns `full_name=' '`, which fails `min_length=1` inside `responses.parse`; on another run it produced an email that died at the hygiene gate. Both are the engine refusing to fabricate and having nowhere to go.

The identity is already being read off the student's document. It is thrown away one module before it is needed.

## Two addresses, and why conflating them is the expensive mistake

| | What it is | Who ever sees it |
|---|---|---|
| `user.email` | Signup and login for this platform | Us. No application code reads it today, and none should |
| `Membership.application_email` | The platform-issued mailbox: the address we register on university and funder portals, and scrape for results and required actions | The funder. This is the CV's contact line |

A CV carries the address a funder replies to. If that is the signup address, the reply lands in a mailbox nothing monitors and the automation that reads results never sees it. If it is the provisioned mailbox, correspondence arrives where it is already being scraped.

**There is no fallback from one to the other.** An `application_email` that defaults to `user.email` when unprovisioned fails silently: nothing raises, and the login address is published to a scholarship committee. `application_email` is nullable and its absence is a hard precondition (below). The field carries a docstring saying so, because the failure mode is a future contributor reaching for `student.user.email` and it looking correct.

The codebase has no `EmailField` anywhere today, so nothing has to be untangled — only kept apart.

## Data model

**`VerifiedFact.Category.IDENTITY`.** Payload `{"full_name": ...}` and nothing else. Adding a choice produces an `AlterField` migration with no data change; CI runs `manage.py makemigrations --check --dry-run` (`.github/workflows/ci.yml:43`), so the migration is mandatory.

Email is not a fact. It is system-of-record data the platform issues; there is nothing to confirm and nothing to fabricate.

**`Membership.application_email`** — nullable `EmailField`, docstring stating the distinction above.

**The verification spec** needs no special-casing:

```python
_CategorySpec(field="personal_information", category=VerifiedFact.Category.IDENTITY,
              identity=("full_name",), detail=(), label=("full_name",))
```

`_PAYLOAD_KEYS[IDENTITY]` becomes `("full_name",)`, so `fact_payload(PersonalInformation(...), category=IDENTITY)` returns exactly `{"full_name": ...}` through the existing `model_dump`-and-filter path.

### The non-tuple field problem

Every field in `_SPECS` is a tuple except `summary`, which is a `str` and is wrapped explicitly:

```python
if isinstance(entries, str):
    entries = (entries,)
```

`personal_information` is a pydantic `BaseModel`, and a v2 model **is iterable** — it yields `(key, value)` pairs. So the existing code would not crash on it. It would emit one verdict per attribute name and look plausible in passing output.

Both `verify_against_facts` and `ingestion._SECTIONS`'s comprehension need the identical rule, so it becomes one helper in `verification.py` — which `ingestion.py` already imports `fact_payload` from — that yields the entries for a spec field, wrapping anything that is not a tuple. Two callers, one rule.

## Ingestion

`_SECTIONS` gains `("personal_information", VerifiedFact.Category.IDENTITY)` and the comprehension routes through the helper above.

Everything else is unchanged. The name is written as an unconfirmed candidate at `source_tier=STUDENT_STATEMENT` with `source_ref=f"upload:{document.id}"`, invisible to generation until a human confirms it — exactly the treatment an OCR'd name deserves. Note this is `STUDENT_STATEMENT` and not `AUTHORITATIVE_DOCUMENT`: `ingest_uploaded_cv` writes every fact at that tier, because an uploaded file is unattested until someone checks it. Identity inherits that unchanged.

**Ingestion does not dedup or supersede, for any category.** Every upload writes fresh candidates, so two uploads mean two name candidates and a human confirms one. That is existing behaviour across the board, and the correction mechanism already exists: a new row with `supersedes` pointing at the one it replaces, which `unsuperseded_facts` then filters out through the `superseded_by` reverse relation. No dedup is added here.

### What if two identity facts are both confirmed

Nothing prevents a human confirming two name candidates without superseding the first. Both then reach DATA, the model picks one, and the verifier finds a matching fact for whichever it picked — so it reads SUPPORTED either way, and the choice was the model's.

This design does **not** special-case that. Two confirmed contradictory facts is the same class of error as two confirmed contradictory employers, which the ledger already tolerates the same way, and identity gets no bespoke machinery for it. The honest reason is that a uniqueness guard belongs on the confirmation step — confirming a correction should supersede what it corrects — not on the read side, and that step is part of the counselor review surface, not this spec.

It is recorded here because the consequence is sharper for identity than for anything else: the wrong name on a funder submission is not a cosmetic defect. If the confirmation surface does not grow that guard, the upgrade path is a check in the gate that refuses more than one unsuperseded confirmed IDENTITY fact, raising alongside the two preconditions below.

## Generation

**The ledger-to-prompt hop needs no code.** `generatable_facts` already filters to confirmed-and-unsuperseded, and `_facts_payload` already serialises every fact as `{id, category, payload}`. Once IDENTITY facts exist and are confirmed, the name flows into DATA on its own.

**Email takes a different route and must not enter DATA.** DATA is labelled untrusted student content in the prompt; the platform's own address is trusted system configuration. It is stated in the developer instructions instead, which means the instruction *"Generate a CV using only the facts provided below, labelled DATA"* gains an explicit exception rather than an implied one.

The model must still emit a schema-valid email or `responses.parse` fails before anything can be corrected, so the address is passed **and** stamped. The stamp overwrites `email` only, never `full_name`:

```python
personal = content.personal_information.model_copy(update={"email": application_email})
content = content.model_copy(update={"personal_information": personal})
```

This belongs inside `_call_model`. `generate_cv` has two return paths — a clean first pass and a post-retry return — and stamping at one of them is the bug that ships.

**Why email is stamped and the name is not.** The platform issues the address, so the model has no authority over it and a stamp removes the failure mode rather than detecting it. A name can genuinely be wrong in a way a human must catch: an OCR misread, a passport that disagrees with a diploma. Stamping the name would manufacture a clean verdict for a value nobody checked, which is the opposite of what this engine is for.

### The gate

Two preconditions, checked in `generate_cv` **before** the rate-limit call:

1. a confirmed, unsuperseded IDENTITY fact exists
2. `student.application_email` is set

`rate_limited()` increments a fixed-window counter, so checking second would burn a token on a student for a state that waiting cannot fix. Both checks are indexed reads and cost nothing worth protecting.

Two exception types, both `RuntimeError` siblings of `GenerationRateLimited` and deliberately **not** under `GenerationError`, whose docstring scopes it to errors raised out of a generation call — a precondition failure never reaches the API:

- `IdentityNotConfirmed("no confirmed identity fact for this student")`
- `ApplicationEmailMissing("no application email provisioned for this student")`

Two types rather than one with two messages, because a UI branches here: "confirm your name" and "your application mailbox is not ready" are different actions taken by different people. Neither message carries content — no name, no address — matching the rule that document text never reaches anything log-shaped (`approval.ApprovalBlocked`'s docstring).

`manage.py generate_cv` surfaces both as `CommandError`, like `GenerationRateLimited`. `_DEMO_FACTS` gains an IDENTITY entry and the demo student gets an `application_email`, which is the command satisfying its own gate honestly instead of handing the model a required field with no source.

## Verification semantics

`_BLOCKING_VERDICTS` is `{CONFLICTING, UNSUPPORTED}` (`apps/documents/approval.py:14`). A model that emits a name other than the confirmed one produces UNSUPPORTED, so `is_blocked` fires the existing single retry with `personal_information[0]` in the correction note. If the second pass also deviates the draft is still returned carrying the verdict — the verifier classifies and does not raise — and `mark_ready` refuses to approve it. All of that is existing machinery; the spec only gives it something to point at.

**Email is never compared.** There is no spec for it, so it receives no verdict. `verification.py`'s module docstring lists the never-compared fields and must name it, or the next reader will assume the platform address was checked against something.

**One behaviour migration.** Adding the spec means every draft gains a verdict it did not have, and `verdicts_for` re-runs against the live ledger at approval time. A draft created before this change, for a student with no confirmed identity fact, becomes un-approvable until one exists. Going forward the gate makes that state unreachable. Accept it rather than special-case it: an unapprovable draft is the correct reading of "we cannot vouch for whose CV this is", and absent production data it affects nothing.

## Testing

Red-first throughout. The tests marked *pins a decision* guard a choice rather than a behaviour; those are the ones that rot silently when someone edits two lines.

| Test | What it holds |
|---|---|
| Ingestion writes an IDENTITY candidate | Red today — the name is dropped. Uses the existing fake-client and `fake_store` fixtures in `test_ingestion.py` |
| The entries helper yields one entry for a model field | A v2 `BaseModel` iterates as `(key, value)` pairs, so the wrong implementation emits a verdict per attribute and looks plausible |
| `("personal_information", IDENTITY, ...)` added to `CATEGORY_CASES` | That table's comment says a new category cannot be added without a verification test; membership yields SUPPORTED / UNCERTAIN / UNSUPPORTED coverage. Its `_content` helper does `base[field] = (entry,)` and needs the same non-tuple awareness as production |
| `generate_cv` raises `IdentityNotConfirmed`, fake client records zero calls | The gate refuses before spending anything |
| `generate_cv` raises `ApplicationEmailMissing` likewise | |
| Gate runs before the rate limiter — *pins a decision* | Exhaust the window against a student with no identity, confirm identity, assert generation is still allowed. Without it, two reordered lines break nothing visibly |
| Email stamped on a clean first pass — *pins a decision* | |
| Email stamped after a retry — *pins a decision* | Two tests, because one covers only the return path someone happened to think of |
| `full_name` is **not** stamped — *pins a decision* | Fake returns a wrong name; the result still carries the model's name and an UNSUPPORTED verdict rather than being silently corrected. This is the test that keeps the anti-fabrication guarantee honest |
| `application_email` is nullable and never falls back to `user.email` | |

**Acceptance, not CI:** one manual live-API run of `manage.py generate_cv --demo`, confirming the confirmed name reaches the document and the stamped address appears as the contact line. It needs a key, costs money and is not deterministic, so it stays out of the suite.

## Dependency on unbuilt work

Gating on `application_email` means that once this ships, `generate_cv` refuses in production until either mailbox provisioning lands or the field is set by hand. This is intended: nothing should generate before a student is actually ready to apply. `--demo` sets its own, so the command keeps working, and a fixture or admin edit covers real students in the interim.

**Whatever provisions the address must validate it at the write boundary.** Nothing in this design does, and today nothing has to: no application code writes `application_email`, so the only writer is an admin or a fixture. That changes the moment provisioning derives an address from anything a student influences, and two validators that look like they apply do not run. Django's `EmailField` validates through `full_clean()` and ModelForms, never on `save()`; pydantic's `model_copy` — which the stamp uses — does not re-validate either. So an unvalidated value would reach both the developer-instruction channel of the prompt and the rendered PDF unchecked. Validate where it is written, with `full_clean()` or a form, not where it is read.

The larger flow this belongs to — student approves programmes, we derive the documents they owe, they submit into a place built for it, and only then do CV and letter generation begin — is three further subsystems. Two of them are listed under "Out of scope here"; the gate designed above is the seam they extend, by adding preconditions beside the two defined here rather than by restructuring the check.
