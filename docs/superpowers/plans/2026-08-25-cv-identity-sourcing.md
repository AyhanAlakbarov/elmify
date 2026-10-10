# CV Identity Sourcing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `CVContent.personal_information` come from real sources — the name from the student's uploaded documents through the fact ledger, the email from a platform-issued mailbox — and make `generate_cv` refuse to run without both.

**Architecture:** The name already exists: `ingest_uploaded_cv` extracts it and throws it away. This adds an `IDENTITY` fact category so it survives, a verification spec so it is checked like any other claim, and a precondition gate on generation. Email takes a separate route — it is platform-issued system data, so it is stamped onto the content after generation and never goes through the ledger.

**Tech Stack:** Django 5, pydantic v2, pytest + pytest-django, `uv` for everything.

**Spec:** `docs/superpowers/specs/2026-08-25-cv-identity-sourcing-design.md`

## Global Constraints

- Branch: `claude/cv-render-fidelity`, in the worktree `/home/orkhan/Desktop/tehsil_agent/.worktrees/phase2-cv-engine`.
- Every command runs through `uv run`. Never invoke `python` or `pytest` bare.
- Gates before any commit: `uv run ruff check apps tests`, `uv run mypy apps`, `uv run pytest -q`, `uv run bandit -c pyproject.toml -r apps config`. A pre-commit hook runs Bandit on commit, so a Bandit failure blocks the commit itself.
- Line length is 100. Ruff enforces it; `uv run ruff check` catches E501.
- CI runs `uv run python manage.py makemigrations --check --dry-run`. Any model change without its migration fails the build.
- Never mutate a `VerifiedFact` in place. The ledger is append-only; corrections are new rows with `supersedes` set.
- Error messages must never carry document content — no names, no email addresses. See `apps/documents/approval.py`'s `ApprovalBlocked` docstring.
- `tests/test_aws_boundary_run_controller.py::test_image_publication_uses_substituted_commands_without_printing_registry` is a known pre-existing flake. It passes in isolation. It is unrelated to this work; do not investigate it.

## Deferred: two spec items that cannot be done on this branch

The spec calls for `_DEMO_FACTS` to gain an IDENTITY entry and for a manual live-API acceptance run of `manage.py generate_cv --demo`. **`apps/documents/management/` does not exist on `claude/cv-render-fidelity`** — the command lives only on `claude/phase2-motivation-letter-engine`. Neither item is a task here.

When that branch rebases onto this work it must, in the same change: add an IDENTITY entry to `_DEMO_FACTS`, set `application_email` on the demo student in `_seed_demo_student`, and catch `IdentityNotConfirmed` and `ApplicationEmailMissing` in `Command.handle` alongside `GenerationRateLimited`. The live acceptance run happens there.

## Two spec decisions that are deliberately not tasks

Both are recorded so an executor does not mistake them for gaps.

**Two confirmed identity facts.** Nothing stops a human confirming two name candidates without superseding the first; both reach DATA and the model picks one. The spec does not special-case this — a uniqueness guard belongs on the confirmation step, which is part of the counselor review surface, not here. Do not add one.

**Existing drafts become un-approvable.** Task 3 gives every draft a verdict it did not have, and `verdicts_for` re-runs against the live ledger at approval time, so a pre-existing draft for a student with no confirmed identity fact will now block at `mark_ready`. That is the correct reading of "we cannot vouch for whose CV this is". Do not special-case it, and do not write a data migration.

---

### Task 1: `Membership.application_email`

**Files:**
- Modify: `apps/tenancy/models.py:75-100` (the `Membership` model)
- Create: `apps/tenancy/migrations/0009_membership_application_email.py` (generated)
- Test: `tests/tenancy/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Membership.application_email: str` — a `models.EmailField(blank=True)`. Empty string means unprovisioned. Later tasks read `student.application_email` and treat `""` as absent.

- [ ] **Step 1: Write the failing test**

Append to `tests/tenancy/test_models.py`:

```python
def test_application_email_is_empty_until_provisioned(agency_a, django_user_model):
    """The platform-issued mailbox is not the signup address.

    There is deliberately no fallback: an application_email that defaulted to
    user.email would publish the login address to a funder and send the reply
    to a mailbox nothing scrapes.
    """
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(
            username="identity-1", email="signup@example.com"
        )
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        assert student.application_email == ""
        assert student.user.email == "signup@example.com"
```

Check the imports already at the top of that file; add `from apps.tenancy.context import tenant_scope` and `from apps.tenancy.models import Membership` only if they are missing.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tenancy/test_models.py::test_application_email_is_empty_until_provisioned -q`
Expected: FAIL with `AttributeError: 'Membership' object has no attribute 'application_email'`

- [ ] **Step 3: Add the field**

In `apps/tenancy/models.py`, inside `class Membership`, directly after the `active` field:

```python
    #: The platform-issued mailbox: the address we register on university and
    #: funder portals with, and scrape for results and required actions. This
    #: is the address a CV carries -- NEVER user.email, which is signup and
    #: login only. There is deliberately no fallback between them: publishing
    #: the login address to a funder sends the reply where nothing is
    #: watching. Empty means unprovisioned, and generation refuses to run.
    application_email = models.EmailField(blank=True)
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations tenancy -n membership_application_email`
Expected: creates `apps/tenancy/migrations/0009_membership_application_email.py` with a single `AddField`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/tenancy/test_models.py::test_application_email_is_empty_until_provisioned -q`
Expected: PASS

- [ ] **Step 6: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q && uv run python manage.py makemigrations --check --dry-run
```
Expected: all pass, and `makemigrations --check` reports no changes.

- [ ] **Step 7: Commit**

```bash
git add apps/tenancy/models.py apps/tenancy/migrations/0009_membership_application_email.py tests/tenancy/test_models.py
git commit -m "feat(tenancy): add Membership.application_email

The platform-issued mailbox, kept strictly separate from user.email. A CV
carries the address a funder replies to; if that is the signup address the
reply lands in a mailbox nothing monitors. Empty until provisioned, with
no fallback -- a silent fallback publishes the wrong address and nothing
raises."
```

---

### Task 2: `VerifiedFact.Category.IDENTITY`

**Files:**
- Modify: `apps/documents/models.py:17-25` (the `Category` choices)
- Create: `apps/documents/migrations/0008_identity_category.py` (generated)
- Test: `tests/documents/test_verified_fact.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `VerifiedFact.Category.IDENTITY == "IDENTITY"`. Later tasks write facts with `payload={"full_name": ...}` under this category.

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/test_verified_fact.py`:

```python
def test_identity_facts_round_trip(agency_a, django_user_model):
    """A name read off a document is a fact like any other -- unconfirmed
    until a human checks it, and invisible to generation until then."""
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="identity-fact-1")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        fact = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Leyla Mammadova"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            confirmed_by=None,
            created_by=student,
        )
        fact.refresh_from_db()
        assert fact.category == "IDENTITY"
        assert fact.payload == {"full_name": "Leyla Mammadova"}
        assert fact.confirmed_by_id is None
```

Add any of `tenant_scope`, `Membership`, `VerifiedFact` to the imports only if that file does not already have them.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/documents/test_verified_fact.py::test_identity_facts_round_trip -q`
Expected: FAIL with `AttributeError: IDENTITY` on `VerifiedFact.Category`

- [ ] **Step 3: Add the choice**

In `apps/documents/models.py`, inside `class Category(models.TextChoices)`, after `PERSONAL = "PERSONAL"`:

```python
        #: Who the CV is about. Payload is {"full_name": ...} and nothing
        #: else -- the contact address is platform-issued (see
        #: Membership.application_email), not a fact anyone confirms.
        IDENTITY = "IDENTITY"
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations documents -n identity_category`
Expected: creates `apps/documents/migrations/0008_identity_category.py` with an `AlterField` on `verifiedfact.category`. No data migration — the column is unchanged, only its choices.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/documents/test_verified_fact.py::test_identity_facts_round_trip -q`
Expected: PASS

- [ ] **Step 6: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q && uv run python manage.py makemigrations --check --dry-run
```

- [ ] **Step 7: Commit**

```bash
git add apps/documents/models.py apps/documents/migrations/0008_identity_category.py tests/documents/test_verified_fact.py
git commit -m "feat(documents): add the IDENTITY fact category

Who the CV is about, carried through the ledger like every other claim so
a name read off a scanned document is confirmed by a human before it
reaches a funder. Payload is {\"full_name\": ...} only -- the contact
address is platform-issued, not a fact."
```

---

### Task 3: The entries helper and the identity verification spec

**Files:**
- Modify: `apps/documents/verification.py` — module docstring, `_SPECS`, new `spec_entries`, `verify_against_facts`
- Test: `tests/documents/test_verification.py`, `tests/documents/test_generation.py`

**Interfaces:**
- Consumes: `VerifiedFact.Category.IDENTITY` (Task 2).
- Produces:
  - `spec_entries(content: CVContent, field: str) -> tuple[object, ...]` — the claim entries for one spec field, wrapping any non-tuple. Task 4 imports this.
  - A `_CategorySpec` for `personal_information`, so `verify_against_facts` now emits a `personal_information[0]` verdict. `_PAYLOAD_KEYS[IDENTITY] == ("full_name",)`.

**Why the helper exists:** every field in `_SPECS` is a tuple except `summary` (a `str`, wrapped by an explicit `isinstance` check). `personal_information` is a pydantic `BaseModel`, and a v2 model **is iterable** — it yields `(key, value)` pairs. Iterating one directly does not crash; it emits one verdict per attribute name and looks plausible. The helper is the guard.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_verification.py`:

```python
def test_spec_entries_wraps_a_model_field_as_one_entry():
    """A pydantic v2 model is iterable over (key, value) pairs, so iterating
    personal_information directly yields a verdict per attribute name rather
    than one verdict for the person. This is the guard against that."""
    content = _content("education", _EDUCATION)
    entries = spec_entries(content, "personal_information")
    assert len(entries) == 1
    assert entries[0] is content.personal_information


def test_spec_entries_passes_a_tuple_field_through():
    content = _content("education", _EDUCATION)
    assert spec_entries(content, "education") == content.education


def test_spec_entries_treats_an_unset_optional_as_no_claim():
    content = _content("education", _EDUCATION)
    assert spec_entries(content, "summary") == ()
```

Add `spec_entries` to the `from apps.documents.verification import ...` line at the top of that file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_verification.py -k spec_entries -q`
Expected: FAIL at import — `ImportError: cannot import name 'spec_entries'`

- [ ] **Step 3: Write the helper and route the verifier through it**

In `apps/documents/verification.py`, add above `verify_against_facts`:

```python
def spec_entries(content: CVContent, field: str) -> tuple[object, ...]:
    """The claim entries for one spec field.

    Most CVContent fields are tuples. ``summary`` is a ``str`` and
    ``personal_information`` is a ``BaseModel`` -- and a pydantic v2 model is
    iterable, yielding (key, value) pairs, so iterating one directly produces
    a verdict per attribute name instead of one verdict for the entry.
    Anything that is not already a tuple is wrapped. ``None`` means no claim
    was made (summary is the only Optional field among _SPECS), not an empty
    claim, so it yields no entry at all.
    """
    entries = getattr(content, field)
    if entries is None:
        return ()
    return entries if isinstance(entries, tuple) else (entries,)
```

Then replace the loop body inside `verify_against_facts`:

```python
    for spec in _SPECS:
        for index, entry in enumerate(spec_entries(content, spec.field)):
            verdicts.append(_classify(spec, index, entry, fact_list))
```

This deletes the `if entries is None: continue` and `if isinstance(entries, str)` blocks, whose comments move into the helper's docstring.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_verification.py -q`
Expected: PASS, all of them — this step is a pure refactor and must not change any existing verdict.

- [ ] **Step 5: Write the failing test for the identity spec**

Add `("personal_information", VerifiedFact.Category.IDENTITY, PersonalInformation(full_name="Jane Doe", email="jane@example.com"))` as a new row at the end of the `CATEGORY_CASES` tuple in `tests/documents/test_verification.py`. That table is already parametrized over SUPPORTED, UNCERTAIN and UNSUPPORTED, so one row buys all three.

The table's `_content` helper does `base[field] = (entry,)`, which would set a tuple where `CVContent` expects a model. Fix it:

```python
def _content(field, entry):
    base = dict(
        personal_information=PersonalInformation(
            full_name="Jane Doe", email="jane@example.com"
        ),
        education=(_EDUCATION,),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )
    # personal_information is a single model, not a tuple of entries.
    base[field] = entry if field == "personal_information" else (entry,)
    return CVContent(**base)
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_verification.py -k personal_information -q`
Expected: FAIL — `test_confirmed_fact_yields_supported[personal_information-...]` finds no matching verdict, because no spec maps that field yet.

- [ ] **Step 7: Add the spec**

Append to `_SPECS` in `apps/documents/verification.py`, after the `summary` entry. **Append, do not insert** — `_SPECS` order is verdict order, and `tests/documents/test_generation.py:92` asserts on `verdicts[0]`:

```python
    _CategorySpec(
        # The name is a claim like any other: it is read off a scanned
        # document, so it can be an OCR misread or disagree with a passport,
        # and a human confirms it before it reaches a funder. The contact
        # address is not here -- it is platform-issued (see
        # Membership.application_email) and stamped, never claimed.
        field="personal_information",
        category=VerifiedFact.Category.IDENTITY,
        identity=("full_name",),
        detail=(),
        label=("full_name",),
    ),
```

- [ ] **Step 8: Update the module docstring**

In `apps/documents/verification.py`, the never-compared list must name the email, or the next reader assumes the platform address was checked against something. Leave the existing paragraph alone and insert a new one directly after it — that paragraph ends with `...or drop the field.` and is followed by a blank line, then `Tasks 5 and 6: treat ``SUPPORTED`` as ...`. The new paragraph goes between them:

```
``PersonalInformation.email`` is not compared either, and for a different
reason: it has no spec at all. The platform issues that address and stamps
it onto generated content, so there is nothing to agree or disagree with.
```

- [ ] **Step 9: Run tests to verify the spec tests pass**

Run: `uv run pytest tests/documents/test_verification.py -q`
Expected: PASS

- [ ] **Step 10: Repair the generation tests the new verdict breaks**

Every generation test now gets a `personal_information[0]` verdict, and without a matching fact it reads UNSUPPORTED — which blocks, which fires the retry, which breaks three tests. In `tests/documents/test_generation.py`, give `_student` an identity fact:

```python
def _student(agency, django_user_model, name, *, identity_confirmed=True):
    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    _identity_fact(student, confirmed=identity_confirmed)
    return student


def _identity_fact(student, *, confirmed=True, full_name="Jane Doe"):
    """personal_information is a verified claim now, so every generation test
    needs a fact backing the name _content() produces. Without one every
    verdict set contains an UNSUPPORTED and every first pass retries."""
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.IDENTITY,
        payload={"full_name": full_name},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="upload:test",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        created_by=student,
    )
```

Then in `test_a_claim_matching_an_unconfirmed_fact_reads_uncertain` (line ~105), which asserts *every* verdict is UNCERTAIN, make the identity fact unconfirmed too so it also reads UNCERTAIN:

```python
        student = _student(agency_a, django_user_model, "g3", identity_confirmed=False)
```

- [ ] **Step 11: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS apart from the known AWS flake named in Global Constraints. If any other test fails, it is a real break — fix it rather than adjusting the assertion.

- [ ] **Step 12: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run bandit -c pyproject.toml -r apps config
```

- [ ] **Step 13: Commit**

```bash
git add apps/documents/verification.py tests/documents/test_verification.py tests/documents/test_generation.py
git commit -m "feat(documents): verify personal_information against the ledger

The name becomes a claim like any other, so an OCR misread or a passport
that disagrees with a diploma produces UNSUPPORTED and blocks approval
instead of reaching a funder unchecked.

The entries helper is the load-bearing part. Every spec field was a tuple
except summary, wrapped by an isinstance check; personal_information is a
pydantic model, and a v2 model is iterable over (key, value) pairs. The
old loop would not have crashed on it -- it would have emitted a verdict
per attribute name and looked plausible.

The spec is appended rather than inserted: _SPECS order is verdict order
and a generation test asserts on verdicts[0]."
```

---

### Task 4: Ingestion stops discarding the name

**Files:**
- Modify: `apps/documents/ingestion.py:44-52` (`_SECTIONS`) and `:154-166` (the fact comprehension)
- Test: `tests/documents/test_ingestion.py`

**Interfaces:**
- Consumes: `spec_entries` (Task 3), `VerifiedFact.Category.IDENTITY` (Task 2).
- Produces: `ingest_uploaded_cv` now returns an IDENTITY fact among its candidates.

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/test_ingestion.py`. Read `test_ingestion_writes_unconfirmed_student_statement_facts` (line ~131) first and mirror its fixture setup exactly — the same `fake_store`, the same fake client, the same document construction:

```python
def test_ingestion_keeps_the_name_it_extracted(agency_a, django_user_model, fake_store):
    """The upload is parsed into a full CVContent, which cannot validate
    without a name -- so the name is already read, and _SECTIONS used to
    iterate straight past it. A name dropped here is a name the model must
    later invent, which is the one thing this engine exists to prevent."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ingest-identity")
        document = _document(student)
        facts = ingest_uploaded_cv(
            document=document, student=student, client=_mock_client(), store=fake_store
        )
        identity = [f for f in facts if f.category == VerifiedFact.Category.IDENTITY]
        assert len(identity) == 1
        assert identity[0].payload == {"full_name": "Jane Doe"}
        assert identity[0].confirmed_by_id is None
        assert identity[0].source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT
```

Replace `_student`, `_document` and `_mock_client` with whatever that module's existing helpers are actually called, and make sure the mock client's `output_parsed` carries `personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com")`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/documents/test_ingestion.py::test_ingestion_keeps_the_name_it_extracted -q`
Expected: FAIL with `assert len([]) == 1` — no IDENTITY fact is written.

- [ ] **Step 3: Add the section and route through the helper**

In `apps/documents/ingestion.py`, append to `_SECTIONS`:

```python
    ("personal_information", VerifiedFact.Category.IDENTITY),
```

Change the import from `.verification` to bring in the helper:

```python
from .verification import fact_payload, spec_entries
```

And change the comprehension (currently `for entry in getattr(extracted, field)`):

```python
    facts = [
        VerifiedFact.objects.create(
            student=student,
            category=category,
            payload=fact_payload(entry, category=category),
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref=f"upload:{document.id}",
            confirmed_by=None,
            created_by=student,
        )
        for field, category in _SECTIONS
        for entry in spec_entries(extracted, field)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/documents/test_ingestion.py -q`
Expected: PASS

- [ ] **Step 5: Run the full suite and gates**

```bash
uv run pytest -q && uv run ruff check apps tests && uv run mypy apps && uv run bandit -c pyproject.toml -r apps config
```

- [ ] **Step 6: Commit**

```bash
git add apps/documents/ingestion.py tests/documents/test_ingestion.py
git commit -m "fix(documents): stop ingestion discarding the extracted name

ingest_uploaded_cv parses the upload into a full CVContent, which cannot
validate without a name and email, then iterated _SECTIONS -- which listed
seven fields and not personal_information -- and dropped it. The identity
was already being read off the student's document and thrown away one
module before it was needed. Same shape as the _PAYLOAD_KEYS drop in
4a68575.

It lands as an unconfirmed candidate at STUDENT_STATEMENT tier, like every
other ingested fact: a name read off a scan is exactly the thing a human
should check before it reaches a funder."
```

---

### Task 5: The generation gate

**Files:**
- Modify: `apps/documents/generation.py` — two new exceptions, preconditions in `generate_cv`
- Test: `tests/documents/test_generation.py`

**Interfaces:**
- Consumes: `Membership.application_email` (Task 1), `VerifiedFact.Category.IDENTITY` (Task 2), the identity spec (Task 3).
- Produces: `IdentityNotConfirmed` and `ApplicationEmailMissing`, both `RuntimeError` subclasses exported from `apps.documents.generation`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_generation.py`:

```python
def test_generation_refuses_without_a_confirmed_identity(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gate1", identity_confirmed=False)
        student.application_email = "leyla@applications.example"
        student.save(update_fields=["application_email"])
        client = _mock_client()
        with pytest.raises(IdentityNotConfirmed):
            generate_cv(student=student, client=client)
        assert client.responses.parse.call_count == 0


def test_generation_refuses_without_an_application_email(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gate2")
        client = _mock_client()
        with pytest.raises(ApplicationEmailMissing):
            generate_cv(student=student, client=client)
        assert client.responses.parse.call_count == 0


def test_the_gate_runs_before_the_rate_limiter(agency_a, django_user_model):
    """Pins the ordering. rate_limited() increments a fixed-window counter, so
    checking preconditions second would burn tokens on a student for a state
    that waiting cannot fix. Reordering two lines must break something."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gate3", identity_confirmed=False)
        student.application_email = "leyla@applications.example"
        student.save(update_fields=["application_email"])
        for _ in range(_CV_GENERATION_RATE_LIMIT + 5):
            with pytest.raises(IdentityNotConfirmed):
                generate_cv(student=student, client=_mock_client())
        # The window was never consumed, so confirming identity is enough.
        _identity_fact(student, confirmed=True)
        result = generate_cv(student=student, client=_mock_client())
        assert isinstance(result.content, CVContent)


def test_gate_messages_carry_no_document_content(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gate4", identity_confirmed=False)
        student.application_email = "leyla@applications.example"
        student.save(update_fields=["application_email"])
        with pytest.raises(IdentityNotConfirmed) as caught:
            generate_cv(student=student, client=_mock_client())
        assert "Jane Doe" not in str(caught.value)
        assert "applications.example" not in str(caught.value)
```

Extend the import at the top of the file:

```python
from apps.documents.generation import (
    _CV_GENERATION_RATE_LIMIT,
    ApplicationEmailMissing,
    GenerationFailure,
    GenerationRateLimited,
    GenerationRefused,
    GenerationSchemaError,
    IdentityNotConfirmed,
    generate_cv,
)
```

`test_the_gate_runs_before_the_rate_limiter` calls `_identity_fact` directly — Task 3 added it as a module-level helper, so it is already available.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_generation.py -k "gate or refuses" -q`
Expected: FAIL at import — `ImportError: cannot import name 'IdentityNotConfirmed'`

- [ ] **Step 3: Add the exceptions**

In `apps/documents/generation.py`, directly after `class GenerationRateLimited(RuntimeError)`:

```python
class IdentityNotConfirmed(RuntimeError):
    """No confirmed IDENTITY fact for this student.

    A precondition, not a generation error: nothing reached the API. Kept out
    of the GenerationError family for that reason, alongside
    GenerationRateLimited. Separate from ApplicationEmailMissing because a UI
    branches here -- "confirm your name" and "your mailbox is not ready" are
    different actions taken by different people.
    """


class ApplicationEmailMissing(RuntimeError):
    """No platform-issued mailbox for this student. See IdentityNotConfirmed."""
```

- [ ] **Step 4: Add the preconditions**

In `generate_cv`, **above** the existing `if _rate_limited(student.id):` block:

```python
    # Before the rate limiter on purpose: rate_limited() increments a
    # fixed-window counter, and burning a token on a student who is missing a
    # precondition punishes them for a state waiting cannot fix. Both checks
    # are indexed reads.
    if not generatable_facts(student).filter(category=VerifiedFact.Category.IDENTITY).exists():
        raise IdentityNotConfirmed("no confirmed identity fact for this student")
    if not student.application_email:
        raise ApplicationEmailMissing("no application email provisioned for this student")
```

Messages carry no name and no address, per Global Constraints.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_generation.py -k "gate or refuses" -q`
Expected: PASS

- [ ] **Step 6: Give every other generation test an application_email**

The gate now rejects every existing test in the module. In `tests/documents/test_generation.py`, set it in `_student` so all of them satisfy it:

```python
def _student(agency, django_user_model, name, *, identity_confirmed=True):
    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency,
        user=user,
        role=Membership.Role.STUDENT,
        active=True,
        application_email=f"{name}@applications.example",
    )
    _identity_fact(student, confirmed=identity_confirmed)
    return student
```

Then delete the two-line `student.application_email = ...` / `student.save(...)` pairs from the three tests written in Step 1 that set it by hand — `_student` now covers them. Leave `test_generation_refuses_without_an_application_email` working by clearing it explicitly instead:

```python
        student = _student(agency_a, django_user_model, "gate2")
        student.application_email = ""
        student.save(update_fields=["application_email"])
```

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS apart from the known AWS flake.

- [ ] **Step 8: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run bandit -c pyproject.toml -r apps config
```

- [ ] **Step 9: Commit**

```bash
git add apps/documents/generation.py tests/documents/test_generation.py
git commit -m "feat(documents): refuse to generate without identity and a mailbox

Two preconditions on generate_cv: a confirmed IDENTITY fact, and a
provisioned application_email. Both are checked before the rate limiter,
because rate_limited() increments a fixed-window counter and burning a
token on a student punishes them for a state that waiting cannot fix.

Two exception types rather than one with two messages: a UI branches here.
'Confirm your name' and 'your application mailbox is not ready' are
different actions taken by different people. Both sit outside the
GenerationError family, whose docstring scopes it to errors raised out of
a generation call -- a precondition failure never reaches the API.

This is the flow the product intends: the student approves programmes, we
derive the documents they owe, they submit, and only then does generation
begin. It also means generation refuses in production until mailbox
provisioning ships or the field is set by hand. That is the gate working."
```

---

### Task 6: Stamp the platform email onto generated content

**Files:**
- Modify: `apps/documents/generation.py` — `_call_model` signature and body, both `_call_model` call sites in `generate_cv`, the prompt instructions
- Test: `tests/documents/test_generation.py`

**Interfaces:**
- Consumes: `Membership.application_email` (Task 1), the gate (Task 5) guaranteeing it is non-empty.
- Produces: `generate_cv` returns content whose `personal_information.email` is always `student.application_email`, on every return path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_generation.py`:

```python
def _content_with_email(email, full_name="Jane Doe"):
    base = _content()
    personal = base.personal_information.model_copy(
        update={"email": email, "full_name": full_name}
    )
    return base.model_copy(update={"personal_information": personal})


def test_email_is_stamped_on_a_clean_first_pass(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp1")
        _fact(student, confirmed=True)
        client = _mock_client(_content_with_email("hallucinated@example.com"))
        result = generate_cv(student=student, client=client)
        assert result.content.personal_information.email == student.application_email


def test_email_is_stamped_after_a_retry(agency_a, django_user_model):
    """Pins the second return path. generate_cv returns in two places -- a
    clean first pass and a post-retry return -- and stamping at one of them
    is the bug that ships."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp2")
        # No education fact, so the education claim reads UNSUPPORTED, blocks,
        # and forces the retry.
        client = _mock_client(_content_with_email("hallucinated@example.com"))
        result = generate_cv(student=student, client=client)
        assert result.retried is True
        assert result.content.personal_information.email == student.application_email


def test_full_name_is_never_stamped(agency_a, django_user_model):
    """The name is not corrected into agreement. Stamping it would manufacture
    a clean verdict for a value nobody checked -- the opposite of what the
    verifier is for. A wrong name must survive as an UNSUPPORTED verdict."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp3")
        _fact(student, confirmed=True)
        client = _mock_client(_content_with_email("x@example.com", full_name="Someone Else"))
        result = generate_cv(student=student, client=client)
        assert result.content.personal_information.full_name == "Someone Else"
        identity = [v for v in result.verdicts if v.claim_path == "personal_information[0]"]
        assert identity and identity[0].verdict == Verdict.UNSUPPORTED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_generation.py -k stamp -q`
Expected: FAIL — `assert 'hallucinated@example.com' == 'stamp1@applications.example'`

- [ ] **Step 3: Stamp inside `_call_model`**

Add the parameter and the stamp. `_call_model` is the single place both passes flow through, which is why the stamp goes here and not at either `return` in `generate_cv`:

```python
def _call_model(
    parser: ResponsesAPI,
    *,
    student_id: str,
    facts_json: str,
    retry_note: str | None,
    application_email: str,
) -> CVContent:
```

At the end of the function, replace `return _parse_content(response)` with:

```python
    content = _parse_content(response)
    # The platform issues this address, so the model has no authority over it:
    # stamping removes the failure mode instead of detecting it. full_name is
    # deliberately NOT stamped -- a name can be wrong in a way a human must
    # catch, and correcting it here would manufacture a clean verdict for a
    # value nobody checked.
    personal = content.personal_information.model_copy(update={"email": application_email})
    return content.model_copy(update={"personal_information": personal})
```

- [ ] **Step 4: Pass it at both call sites**

In `generate_cv`, both `_call_model(...)` calls gain `application_email=student.application_email`. The first:

```python
    content = _call_model(
        parser,
        student_id=str(student.id),
        facts_json=facts_json,
        retry_note=None,
        application_email=student.application_email,
    )
```

and the retry call the same way, keeping its existing `retry_note=` argument.

- [ ] **Step 5: State the address in the instructions**

The model must still emit a schema-valid email or `responses.parse` fails before anything can be stamped. In `_call_model`'s `instructions` string, append after the existing final sentence:

```python
        "The contact email is not part of DATA and is not a fact to verify: "
        f"use exactly {application_email} as personal_information.email."
```

This goes in the developer instructions, not in DATA. DATA is labelled untrusted student content; the platform's own address is trusted system configuration and must not be mixed into it.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_generation.py -q`
Expected: PASS

- [ ] **Step 7: Run the full suite and gates**

```bash
uv run pytest -q && uv run ruff check apps tests && uv run mypy apps && uv run bandit -c pyproject.toml -r apps config
```

- [ ] **Step 8: Commit**

```bash
git add apps/documents/generation.py tests/documents/test_generation.py
git commit -m "feat(documents): stamp the platform email onto generated content

The platform issues the address, so the model has no authority over it.
Stamping removes the failure mode rather than detecting it, and the
address is stated in the developer instructions rather than in DATA --
DATA is labelled untrusted student content and the platform's own
configuration must not be mixed into it.

full_name is deliberately not stamped. A name can be wrong in a way a
human must catch, and correcting it here would manufacture a clean verdict
for a value nobody checked. A wrong name survives as UNSUPPORTED and
blocks approval, which is the point.

The stamp lives in _call_model because generate_cv returns in two places,
and stamping at one of them is the bug that ships."
```

---

## Verification

After Task 6, the whole feature is in place. Run once more from a clean tree:

```bash
uv run ruff check apps tests
uv run mypy apps
uv run pytest -q
uv run bandit -c pyproject.toml -r apps config
uv run python manage.py makemigrations --check --dry-run
```

Expected: all pass, with only the known AWS flake permitted to fail and only intermittently.

The live-API acceptance run named in the spec is **not** possible on this branch — it needs `manage.py generate_cv --demo`, which lives on `claude/phase2-motivation-letter-engine`. It happens there, as part of the deferred work described at the top of this plan.
