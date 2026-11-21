# CV Stage 2: A Newer CV Replaces Older Facts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second CV upload supersedes the facts it restates instead of duplicating them, and the student settles every changed value in one "Changed since your last CV" list.

**Architecture:**
- **One new module, `apps/documents/reupload.py`.** It walks each supersession chain, matches a newly read entry to a chain by category and identity, and plans what to write. It also lists the pending changes and settles them.
- **Ingestion.** `ingest_uploaded_cv` calls the planner instead of writing one row per entry.
- **Settling.** A ticked change goes through the existing `confirmation.confirm_facts`. An unticked one gets a confirmed row that restores the old payload, so the ledger stays append-only.
- **Guard.** Generation refuses while changes are pending, because a pending change hides the entry from `generatable_facts`.
- **Page.** The documents page shows old beside new, with one form and one button.

**Tech Stack:** Django 5, PostgreSQL row-level security, pytest. No new dependency, no migration.

**Spec:** `docs/superpowers/specs/2026-10-12-cv-engine-quality-design.md` §4 (and §2 build order). Evidence: `docs/research/2026-10-12-cv-engine/section-2-refined.md` §2.6 (match the whole chain) and §7 edge cases 1, 4, 5.

**Depends on:** nothing. Stage 1 (layout and typography) is independent of this stage. Stage 3 depends on this stage (`verification.fact_identity` below).

## Decisions made in this plan

1. **A pending change stays a candidate until the student settles it, and generation is refused meanwhile.**
   - The upload writes the superseding row unconfirmed, as every upload row is today. While it is pending, `generatable_facts` no longer sees the entry: the old row is superseded and the new one is unconfirmed.
   - So `generate_cv` raises `ChangesPending` and `POST /api/documents/generate` answers 409 `cv_changes_pending`. A CV with the entry silently missing would otherwise be produced.
   - The alternative was to make generation read the newest *confirmed* row of each chain. It lost because `verify_against_facts` and `approval` read the tips, so the printed old value would read CONFLICTING against the pending new one.
2. **"Unticked keeps the old value" writes a restoring row.** It is a new row, confirmed by the student, that supersedes the pending one and copies the newest confirmed payload, `source_tier` and `source_ref`. Copying `source_ref` keeps `gaps._already_created` working for a fact that a gap answer created. Nothing is deleted or edited, so the ledger stays append-only.
3. **One tick per changed entry, not per changed value.** Each row lists every changed value of one entry, old beside new. A per-value tick would need a merged payload no one typed.
4. **What counts as a change:**
   - A value the new CV leaves empty never overwrites a stored one.
   - A value equal to an older row of the same chain is ignored. This is how a corrected title survives a re-upload of the old abbreviation.
   - An entry with no remaining difference writes nothing.
5. **Matching:**
   - Each chain is claimed by at most one entry of the new CV, in document order, newest chain first. Two posts with the same employer and title therefore match two chains, not one. Among chains with the same identity, the one whose start date is unchanged wins.
   - An IDENTITY entry matches the student's one IDENTITY chain whatever the name. A re-spelled name is then shown old beside new, instead of becoming a second identity.
   - A chain whose tip is `AUTHORITATIVE_DOCUMENT` (a document reading) is never superseded by a CV. The CV's entry for it is dropped.
6. **Only changes to something the student confirmed are "changes".** An upload row superseding a never-confirmed candidate simply replaces it, and it shows in the ordinary "Facts read from your CV" list. A pending change is an unconfirmed upload row whose chain holds a confirmed row. "Old" is the newest confirmed row in that chain. So a third upload stacked on an unsettled second still shows against what the student last confirmed.
7. **The JSON API is unchanged.** `GET /api/documents/facts/candidates` still lists pending rows, and `POST /api/documents/facts/confirm` may confirm them: that is the student accepting the change. Only the HTML page separates the two lists.
8. **A worker that meets `ChangesPending` drops the job with a warning**, like the unknown-programme case. The API already refused the request, so this only fires in a race.

## Global Constraints

- Master's applicants only. English CVs only (MVP).
- No model writes a sentence. Nothing the student did not provide may appear on the CV.
- Lint only: `uv run ruff check .`. Never `ruff format`.
- Types: `uv run mypy apps config`.
- Tests: `POSTGRES_DB=elmify_cv_engine_design uv run pytest -q`.
- `uv run python manage.py makemigrations --check --dry-run` must stay clean. This stage adds no migration.
- Never hand-edit an applied migration.
- A new tenant table follows `apps/documents/migrations/0026_transcript_pages_tenant_guards.py` and gets `apps/audit/redaction.py` entries. This stage adds none.
- Cross-tenant tests go through `rls_enforced_orm`, because the test database role bypasses RLS.
- Worktree `/home/orkhan/Desktop/cv-engine-design`, branch `claude/cv-engine-quality-design`. Use `git -C` for every git command. Commit with a pathspec: another session shares this checkout. Never `git add -A`.
- Never log a fact's payload, a title or a bullet. Log ids and counts only.

## Review Focus

1. **The same CV uploaded twice.** Expected: the second upload writes nothing, and nothing appears in "Changed since your last CV". Pinned in Task 2 (`test_reuploading_the_same_cv_writes_nothing`).
2. **The newer CV omits a detail the older one had** (no city, no end date). Expected: the stored value stays; a blank never reads as a change. Pinned in Task 1 (`test_a_blank_in_the_new_cv_never_wipes_a_stored_value`).
3. **The student opens the page, a third upload lands, and they press Confirm on the stale page.** Expected: only the changes they saw are settled. The new one stays pending and is never silently declined. Pinned in Task 3 (`test_only_the_changes_shown_are_settled`).
4. **Two presses of Confirm in quick succession.** Expected: the second press changes nothing and does not fork a chain. Pinned in Task 3 (`test_settling_twice_changes_nothing_the_second_time`).
5. **A CV is generated while changes are pending.** Expected: a clear 409 telling the student to settle the list, not a CV with the changed entries missing. Pinned in Task 4.

---

### Task 1: Chains, identity matching and the upload plan

**Files:**
- Modify: `apps/documents/verification.py` (add `fact_identity` beside `_identity`, around line 433)
- Create: `apps/documents/reupload.py`
- Test: `tests/documents/test_reupload.py` (create)

**Interfaces:**
- Consumes: `verification._SPEC_BY_CATEGORY`, `verification._identity`, `verification._fact_payload` (all module-private today).
- Produces:
  - `verification.fact_identity(category: str, payload: Mapping[str, object]) -> tuple[str, ...]`. It returns `()` for a category with no spec.
  - `reupload.UPLOAD_REF_PREFIX = "upload:"`.
  - `reupload.Chain`, a frozen dataclass with `tip: VerifiedFact` and `rows: tuple[VerifiedFact, ...]` (tip first, then every row it superseded, newest to oldest).
  - `reupload.chains(student: Membership, category: str) -> list[Chain]`, newest tip first.
  - `reupload.merged_payload(chain: Chain, new: Mapping[str, object]) -> dict[str, object]`.
  - `reupload.Write`, a frozen dataclass with `payload: dict[str, object]` and `supersedes: VerifiedFact | None`.
  - `reupload.plan_upload(category: str, payloads: Sequence[dict[str, object]], existing: list[Chain]) -> list[Write]`.

- [ ] **Step 1: Write the failing tests** (`tests/documents/test_reupload.py`)

```python
"""Stage 2 (spec 2026-10-12 §4): a newer CV replaces the facts it restates."""

from datetime import date

import pytest
from django.utils import timezone

from apps.documents.models import VerifiedFact
from apps.documents.reupload import chains, merged_payload, plan_upload
from apps.documents.schemas import EducationEntry, ExperienceEntry
from apps.documents.verification import fact_identity, fact_payload
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

EDU = VerifiedFact.Category.EDUCATION
EXP = VerifiedFact.Category.EXPERIENCE


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _degree(**over):
    fields = {
        "degree_as_awarded": "B.Sc. of Chem. Eng.",
        "institution_original": "UFAZ",
        "city": "Baku",
        "country": "AZ",
        "start_date": date(2019, 9, 1),
        "end_date": date(2023, 6, 1),
    }
    fields.update(over)
    return fact_payload(EducationEntry(**fields), category=EDU)


def _fact(student, payload, *, category=EDU, confirmed=True, supersedes=None,
          tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, ref="upload:first"):
    return VerifiedFact.objects.create(
        student=student, category=category, payload=payload, source_tier=tier,
        source_ref=ref, confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        supersedes=supersedes, created_by=student,
    )


def test_fact_identity_is_the_verifiers_identity():
    payload = _degree()
    assert fact_identity(EDU, payload) == ("ufaz", "b.sc. of chem. eng.")
    assert fact_identity("NO_SUCH_CATEGORY", payload) == ()


def test_a_chain_lists_its_tip_then_every_older_row(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "chain")
        old = _fact(student, _degree())
        new = _fact(student, _degree(degree_as_awarded="Bachelor of Chemical Engineering"),
                    supersedes=old, ref="gap-interview")
        found = chains(student, EDU)
    assert len(found) == 1
    assert found[0].tip.id == new.id
    assert [row.id for row in found[0].rows] == [new.id, old.id]


def test_a_changed_date_supersedes_the_matching_fact(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "changed")
        old = _fact(student, _degree())
        writes = plan_upload(EDU, [_degree(end_date=date(2023, 7, 1))], chains(student, EDU))
    assert len(writes) == 1
    assert writes[0].supersedes is not None and writes[0].supersedes.id == old.id
    assert writes[0].payload["end_date"] == "2023-07-01"


def test_an_unchanged_entry_writes_nothing(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "same")
        _fact(student, _degree())
        assert plan_upload(EDU, [_degree()], chains(student, EDU)) == []


def test_a_new_entry_is_added_and_an_old_only_entry_stays(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "added")
        _fact(student, _degree())
        msc = _degree(degree_as_awarded="MSc Chemoinformatics", institution_original="Unistra")
        writes = plan_upload(EDU, [msc], chains(student, EDU))
    assert len(writes) == 1
    assert writes[0].supersedes is None
    assert writes[0].payload["degree_as_awarded"] == "MSc Chemoinformatics"


def test_a_corrected_title_survives_a_reupload_of_the_abbreviation(
    agency_a, django_user_model
):
    """Matching runs over the whole chain (spec §4): the old abbreviation still
    names this degree, and it is a value the chain already moved away from."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "corrected")
        old = _fact(student, _degree())
        _fact(student, _degree(degree_as_awarded="Bachelor of Chemical Engineering"),
              supersedes=old, ref="gap-interview")
        assert plan_upload(EDU, [_degree()], chains(student, EDU)) == []


def test_a_blank_in_the_new_cv_never_wipes_a_stored_value(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "blank")
        _fact(student, _degree())
        assert plan_upload(EDU, [_degree(city=None, end_date=None)], chains(student, EDU)) == []


def test_merged_payload_keeps_what_only_the_ledger_knows(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "merge")
        _fact(student, {**_degree(), "thesis_title": "AZIMUTH"})
        merged = merged_payload(chains(student, EDU)[0], _degree(end_date=date(2023, 7, 1)))
    assert merged["thesis_title"] == "AZIMUTH"
    assert merged["end_date"] == "2023-07-01"


def test_two_posts_with_one_identity_claim_two_chains(agency_a, django_user_model):
    def post(start):
        return fact_payload(
            ExperienceEntry(employer="SOCAR", title="Intern", start_date=start,
                            bullets=("Logged well data.",)),
            category=EXP,
        )

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "twins")
        first = _fact(student, post(date(2021, 6, 1)), category=EXP)
        second = _fact(student, post(date(2022, 6, 1)), category=EXP)
        writes = plan_upload(EXP, [post(date(2021, 6, 1)), post(date(2022, 7, 1))],
                             chains(student, EXP))
    # The unchanged post claims its own chain by start date; the changed one
    # takes the other chain instead of becoming a third post.
    assert [w.supersedes.id for w in writes] == [second.id]
    assert first.id not in {w.supersedes.id for w in writes}


def test_an_authoritative_tip_is_never_superseded_by_a_cv(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "diploma")
        _fact(student, _degree(), tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
              ref="diploma:1")
        assert plan_upload(EDU, [_degree(end_date=date(2023, 7, 1))], chains(student, EDU)) == []


def test_a_renamed_identity_matches_the_one_identity_chain(agency_a, django_user_model):
    ident = VerifiedFact.Category.IDENTITY
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "named")
        old = _fact(student, {"full_name": "Orxan Abdullayev"}, category=ident)
        writes = plan_upload(ident, [{"full_name": "Orkhan Abdullayev"}], chains(student, ident))
    assert len(writes) == 1 and writes[0].supersedes.id == old.id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_reupload.py -q`
Expected: FAIL with `ImportError: cannot import name 'chains' from 'apps.documents.reupload'` (module missing).

- [ ] **Step 3: Add `fact_identity` to `apps/documents/verification.py`** (directly after `_identity`)

```python
def fact_identity(category: str, payload: Mapping[str, object]) -> tuple[str, ...]:
    """What the verifier treats as "the same entry", for any writer that must agree.

    Public for apps/documents/reupload.py (a newer CV supersedes the fact it
    restates) and the generation stamps: both must match exactly the way
    verify_against_facts matches, or an entry the verifier calls one thing is
    two things to them. () for a category with no spec.
    """
    spec = _SPEC_BY_CATEGORY.get(category)
    return () if spec is None else _identity(spec, dict(payload))
```

Add `Mapping` to the existing `from collections.abc import Iterable` line: `from collections.abc import Iterable, Mapping`.

- [ ] **Step 4: Create `apps/documents/reupload.py`**

```python
"""A newer CV replaces the facts it restates (spec 2026-10-12 §4).

Before this, every upload wrote one candidate row per entry, so a second CV
duplicated every fact. A changed date then made two confirmed facts disagree,
the verifier read CONFLICTING, and the draft was blocked with nothing the
student could do about it.

An entry is matched to a supersession chain by category and identity -- the
verifier's own identity (verification.fact_identity) -- against EVERY row of
the chain, not only its tip. The tip alone is not enough: a student who
corrected "B.Sc. of Chem. Eng." would otherwise see the abbreviation come back
as a second degree on the next upload.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from apps.tenancy.models import Membership

from .models import VerifiedFact
from .verification import fact_identity

#: The prefix ingest_uploaded_cv stamps on every row it writes.
UPLOAD_REF_PREFIX = "upload:"


@dataclass(frozen=True)
class Chain:
    tip: VerifiedFact
    #: The tip first, then every row it superseded, newest to oldest.
    rows: tuple[VerifiedFact, ...]


@dataclass(frozen=True)
class Write:
    payload: dict[str, object]
    #: The tip this row replaces, or None for an entry only the new CV has.
    supersedes: VerifiedFact | None


def _payload(fact: VerifiedFact) -> dict[str, object]:
    # Same tolerance as verification._fact_payload: a malformed JSON payload
    # states nothing rather than crashing an upload.
    return fact.payload if isinstance(fact.payload, dict) else {}


def _empty(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def chains(student: Membership, category: str) -> list[Chain]:
    """Every supersession chain of one category, newest tip first."""
    rows = list(
        VerifiedFact.objects.filter(student=student, category=category).order_by(
            "-created_at", "-id"
        )
    )
    by_id = {row.id: row for row in rows}
    superseded = {row.supersedes_id for row in rows if row.supersedes_id is not None}
    found: list[Chain] = []
    for tip in rows:
        if tip.id in superseded:
            continue
        members = [tip]
        while members[-1].supersedes_id in by_id:
            members.append(by_id[members[-1].supersedes_id])
        found.append(Chain(tip=tip, rows=tuple(members)))
    return found


def merged_payload(chain: Chain, new: Mapping[str, object]) -> dict[str, object]:
    """The tip, with only what the new CV says differently AND newly.

    A blank is never a change: a CV that leaves out a city has not said the
    city changed. A value an older row of this chain already held is never a
    change either: the chain moved away from it, so the new CV is repeating a
    superseded value.
    """
    merged = dict(_payload(chain.tip))
    for key, value in new.items():
        if _empty(value) or value == merged.get(key):
            continue
        if any(_payload(row).get(key) == value for row in chain.rows[1:]):
            continue
        merged[key] = value
    return merged


def _match(category: str, payload: Mapping[str, object], open_chains: list[Chain]) -> Chain | None:
    if category == VerifiedFact.Category.IDENTITY:
        # One person per ledger: a re-spelled name is a change to show, not a
        # second identity.
        return open_chains[0] if open_chains else None
    identity = fact_identity(category, payload)
    if not any(identity):
        return None
    candidates = [
        chain
        for chain in open_chains
        if any(fact_identity(category, _payload(row)) == identity for row in chain.rows)
    ]
    # Two posts can share an identity (same employer and title); the start
    # date tells them apart when it did not change.
    return next(
        (c for c in candidates if _payload(c.tip).get("start_date") == payload.get("start_date")),
        candidates[0] if candidates else None,
    )


def plan_upload(
    category: str, payloads: Sequence[dict[str, object]], existing: list[Chain]
) -> list[Write]:
    """What one category of a newly read CV writes, in document order.

    Each chain is claimed at most once, so two posts sharing an identity match
    two chains. An AUTHORITATIVE_DOCUMENT tip is read off a document and is
    never overwritten by a CV.
    """
    open_chains = list(existing)
    writes: list[Write] = []
    for payload in payloads:
        chain = _match(category, payload, open_chains)
        if chain is None:
            writes.append(Write(payload=payload, supersedes=None))
            continue
        open_chains = [other for other in open_chains if other is not chain]
        if chain.tip.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT:
            continue
        merged = merged_payload(chain, payload)
        if merged != _payload(chain.tip):
            writes.append(Write(payload=merged, supersedes=chain.tip))
    return writes
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_reupload.py tests/documents/test_verification.py -q`
Expected: PASS.

- [ ] **Step 6: Lint, types, commit**

```bash
uv run ruff check apps/documents/reupload.py apps/documents/verification.py tests/documents/test_reupload.py
uv run mypy apps config
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/reupload.py apps/documents/verification.py tests/documents/test_reupload.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): plan which facts a newer CV supersedes" -- apps/documents/reupload.py apps/documents/verification.py tests/documents/test_reupload.py
```

---

### Task 2: Ingestion writes the plan

**Files:**
- Modify: `apps/documents/ingestion.py:540-554` (the `facts = [...]` block at the end of `ingest_uploaded_cv`)
- Test: `tests/documents/test_ingestion.py`

**Interfaces:**
- Consumes: `reupload.chains`, `reupload.plan_upload`, `reupload.Write` (Task 1); `verification.fact_payload`, `verification.spec_entries`.
- Produces: `ingest_uploaded_cv(...) -> tuple[VerifiedFact, ...]`. The signature is unchanged. It now returns only the rows actually written: new entries and superseding rows.

- [ ] **Step 1: Write the failing tests** (append to `tests/documents/test_ingestion.py`)

```python
# --- Stage 2: a newer CV replaces older facts ---------------------------------

def _confirm_all(student):
    from django.utils import timezone

    VerifiedFact.objects.filter(student=student).update(
        confirmed_by=student, confirmed_at=timezone.now()
    )


def _second_upload(agency, student, fake_store, content):
    from apps.documents.ingestion import ingest_uploaded_cv as ingest

    client = _openai_client()
    client.responses.parse.return_value.output_parsed = content
    document = promoted_upload(register(agency.id, student.id, mode="ADD"), fake_store, _pdf())
    return document, ingest(document=document, student=student, client=client, store=fake_store)


def test_a_reupload_with_one_changed_date_leaves_one_current_fact(
    agency_a, django_user_model, fake_store
):
    from apps.documents.verification import unsuperseded_facts

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-reupload")
        first = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        ingest_uploaded_cv(document=first, student=student, client=_openai_client(),
                           store=fake_store)
        _confirm_all(student)
        degree = _content().education[0].model_copy(update={"end_date": date(2024, 6, 30)})
        _, written = _second_upload(
            agency_a, student, fake_store, _content().model_copy(update={"education": (degree,)})
        )
        current = list(unsuperseded_facts(student).filter(category=VerifiedFact.Category.EDUCATION))
    assert len(written) == 1
    assert len(current) == 1
    assert current[0].payload["end_date"] == "2024-06-30"
    assert current[0].supersedes is not None
    assert current[0].supersedes.payload["end_date"] is None
    assert current[0].confirmed_by is None


def test_reuploading_the_same_cv_writes_nothing(agency_a, django_user_model, fake_store):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-same")
        first = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        ingest_uploaded_cv(document=first, student=student, client=_openai_client(),
                           store=fake_store)
        _confirm_all(student)
        before = VerifiedFact.objects.filter(student=student).count()
        _, written = _second_upload(agency_a, student, fake_store, _content())
        assert written == ()
        assert VerifiedFact.objects.filter(student=student).count() == before


def test_the_first_upload_still_writes_every_entry(agency_a, django_user_model, fake_store):
    """Unchanged behaviour on an empty ledger: three entries, three candidates."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-first")
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        facts = ingest_uploaded_cv(document=document, student=student,
                                   client=_openai_client(), store=fake_store)
    assert len(facts) == 3
    assert all(fact.supersedes_id is None for fact in facts)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_ingestion.py -q -k "reupload or same_cv or first_upload"`
Expected: `test_a_reupload_with_one_changed_date_leaves_one_current_fact` FAILS: there are two current EDUCATION facts. `test_reuploading_the_same_cv_writes_nothing` FAILS: three rows were written. `test_the_first_upload_still_writes_every_entry` passes already.

- [ ] **Step 3: Replace the write block in `ingest_uploaded_cv`** (`apps/documents/ingestion.py`)

Add to the imports: `from .reupload import chains, plan_upload`.

Replace everything from `facts = [` to `return tuple(facts)` with:

```python
    written: list[VerifiedFact] = []
    for field, category in _SECTIONS:
        # personal_information is a model, not a tuple -- see spec_entries.
        payloads = [
            fact_payload(entry, category=category)
            for entry in spec_entries(extracted, field)
        ]
        # Stage 2 (spec §4): an entry the ledger already holds supersedes it,
        # an unchanged one writes nothing, and one only this CV has is added.
        for write in plan_upload(category, payloads, chains(student, category)):
            written.append(
                VerifiedFact.objects.create(
                    student=student,
                    category=category,
                    payload=write.payload,
                    source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                    source_ref=f"upload:{document.id}",
                    confirmed_by=None,
                    supersedes=write.supersedes,
                    created_by=student,
                )
            )
    return tuple(written)
```

Update the docstring's last paragraph to add: "A fact this CV restates is superseded rather than duplicated (reupload.py); an unchanged one writes nothing, so a re-delivered message re-reads the document and writes nothing again."

- [ ] **Step 4: Run the ingestion and worker tests**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_ingestion.py tests/documents/test_document_worker.py tests/documents/test_end_to_end.py -q`
Expected: PASS. If a worker test asserts an exact fact count after two ingestions of the same content, it is pinning the duplication this stage removes. Change its expectation to the new count and say why in the test.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/ingestion.py tests/documents/test_ingestion.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): a newer CV supersedes the facts it restates" -- apps/documents/ingestion.py tests/documents/test_ingestion.py
```

---

### Task 3: Pending changes and settling them

**Files:**
- Modify: `apps/documents/reupload.py` (append)
- Test: `tests/documents/test_reupload.py` (append)

**Interfaces:**
- Consumes: `chains`, `UPLOAD_REF_PREFIX`, `_payload` (Task 1); `confirmation.confirm_facts(*, student, fact_ids, actor) -> int`; `audit.record_event(*, actor, event, object_id)`; `verification.unsuperseded_facts`.
- Produces:
  - `reupload.PendingChange`, a frozen dataclass with `fact: VerifiedFact` (the unconfirmed upload row), `kept: VerifiedFact` (the newest confirmed row it would replace) and `changes: tuple[tuple[str, object, object], ...]` (`(key, old, new)`).
  - `reupload.pending_changes(student: Membership) -> list[PendingChange]`, oldest change first.
  - `reupload.has_pending_changes(student: Membership) -> bool`.
  - `reupload.settle_changes(*, student: Membership, shown: Iterable[UUID], accepted: Iterable[UUID], actor: Membership) -> tuple[int, int]`, returning `(accepted, kept_old)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/documents/test_reupload.py`)

```python
from uuid import uuid4

from apps.documents.reupload import has_pending_changes, pending_changes, settle_changes
from apps.documents.verification import generatable_facts, unsuperseded_facts
from apps.funding.models import AuditEvent


def _pending(student):
    """A confirmed degree, then an upload row changing its end date."""
    old = _fact(student, _degree())
    new = _fact(student, _degree(end_date=date(2023, 7, 1)), supersedes=old,
                confirmed=False, ref="upload:second")
    return old, new


def test_a_change_to_a_confirmed_fact_is_pending(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "pending")
        old, new = _pending(student)
        [change] = pending_changes(student)
        assert has_pending_changes(student)
    assert change.fact.id == new.id and change.kept.id == old.id
    assert change.changes == (("end_date", "2023-06-01", "2023-07-01"),)


def test_a_new_entry_or_a_gap_answer_is_not_a_pending_change(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "notpending")
        _fact(student, _degree(), confirmed=False, ref="upload:only")
        confirmed = _fact(student, _degree(institution_original="ADA University"))
        _fact(student, _degree(institution_original="ADA University", city="Ganja"),
              supersedes=confirmed, confirmed=False, ref="gap-interview")
        assert pending_changes(student) == []


def test_a_ticked_change_is_confirmed(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ticked")
        _, new = _pending(student)
        assert settle_changes(student=student, shown=[new.id], accepted=[new.id],
                              actor=student) == (1, 0)
        new.refresh_from_db()
        assert new.confirmed_by_id == student.id
        assert not has_pending_changes(student)


def test_an_unticked_change_keeps_the_old_value(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "unticked")
        old, new = _pending(student)
        assert settle_changes(student=student, shown=[new.id], accepted=[],
                              actor=student) == (0, 1)
        [tip] = unsuperseded_facts(student).filter(category=EDU)
        assert tip.supersedes_id == new.id
        assert tip.payload == old.payload
        assert tip.source_ref == old.source_ref
        assert tip.confirmed_by_id == student.id
        assert [f.id for f in generatable_facts(student).filter(category=EDU)] == [tip.id]
        assert AuditEvent.objects.filter(event="fact.change_declined", object_id=tip.id).exists()


def test_only_the_changes_shown_are_settled(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stale")
        _, shown = _pending(student)
        other = _fact(student, _degree(institution_original="Unistra",
                                       degree_as_awarded="MSc Chemistry"))
        unseen = _fact(student, _degree(institution_original="Unistra",
                                        degree_as_awarded="MSc Chemistry", city="Strasbourg"),
                       supersedes=other, confirmed=False, ref="upload:third")
        settle_changes(student=student, shown=[shown.id], accepted=[], actor=student)
        assert [c.fact.id for c in pending_changes(student)] == [unseen.id]


def test_settling_twice_changes_nothing_the_second_time(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "twice")
        _, new = _pending(student)
        settle_changes(student=student, shown=[new.id], accepted=[], actor=student)
        count = VerifiedFact.objects.filter(student=student).count()
        assert settle_changes(student=student, shown=[new.id], accepted=[],
                              actor=student) == (0, 0)
        assert VerifiedFact.objects.filter(student=student).count() == count


def test_an_id_that_is_not_a_pending_change_is_ignored(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "forged")
        _pending(student)
        assert settle_changes(student=student, shown=[uuid4()], accepted=[uuid4()],
                              actor=student) == (0, 0)
        assert has_pending_changes(student)


def test_a_third_upload_is_shown_against_what_the_student_last_confirmed(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stacked")
        old, second = _pending(student)
        third = _fact(student, _degree(end_date=date(2023, 8, 1)), supersedes=second,
                      confirmed=False, ref="upload:third")
        [change] = pending_changes(student)
    assert change.fact.id == third.id and change.kept.id == old.id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_reupload.py -q`
Expected: FAIL with `ImportError: cannot import name 'has_pending_changes'`.

- [ ] **Step 3: Append to `apps/documents/reupload.py`**

Add the imports `from collections.abc import Iterable`, `from uuid import UUID`, `from django.db import transaction`, `from django.utils import timezone`, `from .audit import record_event` and `from .confirmation import confirm_facts`, and `from .verification import unsuperseded_facts` beside `fact_identity`. Then:

```python
@dataclass(frozen=True)
class PendingChange:
    #: The unconfirmed row the newer CV wrote.
    fact: VerifiedFact
    #: The newest row of the same chain the student confirmed: what "keep the
    #: old value" restores, and what "old" means on the page.
    kept: VerifiedFact
    #: (payload key, old value, new value), in the new row's key order.
    changes: tuple[tuple[str, object, object], ...]


def pending_changes(student: Membership) -> list[PendingChange]:
    """Every upload row waiting for the student to accept or decline it.

    Pending means: an unconfirmed tip written by an upload, whose chain holds a
    confirmed row. A change to a never-confirmed candidate is not pending -- it
    replaces a value nobody stood behind and joins the ordinary candidate list.
    """
    tips = unsuperseded_facts(student).filter(
        confirmed_by__isnull=True, source_ref__startswith=UPLOAD_REF_PREFIX
    )
    found: list[PendingChange] = []
    for category in {tip.category for tip in tips}:
        for chain in chains(student, category):
            tip = chain.tip
            if tip.confirmed_by_id is not None or not tip.source_ref.startswith(
                UPLOAD_REF_PREFIX
            ):
                continue
            kept = next((row for row in chain.rows[1:] if row.confirmed_by_id is not None), None)
            if kept is None:
                continue
            old, new = _payload(kept), _payload(tip)
            changes = tuple(
                (key, old.get(key), value) for key, value in new.items() if value != old.get(key)
            )
            found.append(PendingChange(fact=tip, kept=kept, changes=changes))
    return sorted(found, key=lambda change: (change.fact.created_at, change.fact.id))


def has_pending_changes(student: Membership) -> bool:
    return bool(pending_changes(student))


@transaction.atomic
def settle_changes(
    *,
    student: Membership,
    shown: Iterable[UUID],
    accepted: Iterable[UUID],
    actor: Membership,
) -> tuple[int, int]:
    """The student's one press: ticked changes are confirmed, unticked ones are
    declined by a confirmed row that restores the old payload.

    Only ids that were SHOWN and are STILL pending are touched. A change that
    arrived after the page was rendered stays pending rather than being
    declined unseen. A replayed or forged id is not pending and is ignored.

    A concurrent second press can still race to supersede the same row; the
    verifiedfact_one_superseder index refuses it and the IntegrityError
    propagates for the view to report.
    """
    pending = {change.fact.id: change for change in pending_changes(student)}
    shown_ids = set(shown) & set(pending)
    accepted_ids = set(accepted) & shown_ids
    if accepted_ids:
        confirm_facts(student=student, fact_ids=accepted_ids, actor=actor)
    declined = sorted(shown_ids - accepted_ids)
    now = timezone.now()
    for fact_id in declined:
        change = pending[fact_id]
        restored = VerifiedFact.objects.create(
            student=student,
            category=change.kept.category,
            payload=dict(_payload(change.kept)),
            source_tier=change.kept.source_tier,
            # The old row's provenance, not ours: this row IS the old claim, and
            # gaps._already_created finds a gap-created fact by this stamp.
            source_ref=change.kept.source_ref,
            confirmed_by=actor,
            confirmed_at=now,
            supersedes=change.fact,
            created_by=actor,
        )
        record_event(actor=actor, event="fact.change_declined", object_id=restored.id)
    return len(accepted_ids), len(declined)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_reupload.py tests/documents/test_confirmation.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/reupload.py tests/documents/test_reupload.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): list and settle the changes a newer CV made" -- apps/documents/reupload.py tests/documents/test_reupload.py
```

---

### Task 4: No CV while changes are pending

**Files:**
- Modify: `apps/documents/generation.py` (new exception beside `IdentityNotConfirmed`; first check in `generate_cv`)
- Modify: `apps/documents/api.py` (`generate`, before the identity check, around line 421)
- Modify: `apps/documents/document_worker.py` (`_generate`, the `result = generate_cv(...)` line around 431)
- Test: `tests/documents/test_generation.py`, `tests/documents/test_api.py`, `tests/documents/test_document_worker.py`

**Interfaces:**
- Consumes: `reupload.has_pending_changes` (Task 3).
- Produces:
  - `generation.ChangesPending(RuntimeError)`.
  - The API error code `"cv_changes_pending"` with HTTP 409.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_generation.py`:

```python
def _pending_change(student):
    old = _fact(student, confirmed=True)
    return VerifiedFact.objects.create(
        student=student, category=VerifiedFact.Category.EDUCATION,
        payload={**old.payload, "city": "Hamburg"},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:second",
        supersedes=old, created_by=student,
    )


def test_generation_refuses_while_a_newer_cv_awaits_confirmation(agency_a, django_user_model):
    from apps.documents.generation import ChangesPending

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g-pending")
        _pending_change(student)
        client = _mock_client()
        with pytest.raises(ChangesPending):
            generate_cv(student=student, client=client)
    client.responses.parse.assert_not_called()


def test_the_pending_check_runs_before_the_identity_check(agency_a, django_user_model):
    """A re-spelled name is itself a pending change; the student must be told
    to settle the list, not that they have no name."""
    from apps.documents.generation import ChangesPending

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g-order", identity_confirmed=True)
        identity = VerifiedFact.objects.get(student=student)
        VerifiedFact.objects.create(
            student=student, category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Jane Q. Doe"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:second",
            supersedes=identity, created_by=student,
        )
        with pytest.raises(ChangesPending):
            generate_cv(student=student, client=_mock_client())
```

Append to `tests/documents/test_api.py` (it already has `_candidate`, `_post`, `GENERATE` and the `queued` fixture):

```python
def test_generate_is_409_while_a_newer_cv_awaits_confirmation(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    from django.utils import timezone

    with tenant_scope(agency_a.id):
        identity = _candidate(membership_a)
        VerifiedFact.objects.filter(id=identity.id).update(
            confirmed_by=membership_a, confirmed_at=timezone.now()
        )
        old = VerifiedFact.objects.create(
            student=membership_a, category=VerifiedFact.Category.EDUCATION,
            payload={"degree_as_awarded": "BSc", "institution_original": "UFAZ", "city": "Baku"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:first",
            confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a,
        )
        VerifiedFact.objects.create(
            student=membership_a, category=VerifiedFact.Category.EDUCATION,
            payload={**old.payload, "city": "Sumqayit"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:second",
            supersedes=old, created_by=membership_a,
        )
        membership_a.application_email = "student@mail.example.test"
        membership_a.save(update_fields=["application_email"])
    client.force_login(user_a)

    response = _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    assert response.status_code == 409
    assert response.json() == {"error": "cv_changes_pending"}
    assert queued == []
```

Append to `tests/documents/test_document_worker.py`. It already imports `document_worker`, `DocumentWorkMessage`, `DocumentDraft`, `tenant_scope` and `make_identity_fact`:

```python
def test_a_generate_job_meeting_pending_changes_is_dropped(
    agency_a, membership_a, monkeypatch, caplog
):
    from apps.documents.generation import ChangesPending

    def _pending(**kwargs):
        raise ChangesPending("settle the changes from the newer CV first")

    monkeypatch.setattr(document_worker, "generate_cv", _pending)
    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a)

    with caplog.at_level("WARNING", logger="apps.documents.document_worker"):
        document_worker.handle_document_work(
            DocumentWorkMessage(
                action="generate",
                kind=DocumentDraft.Kind.CV,
                tenant_id=agency_a.id,
                student_id=membership_a.id,
            )
        )

    assert "DocumentGenerateChangesPending" in caplog.text
    with tenant_scope(agency_a.id):
        assert not DocumentDraft.objects.filter(student=membership_a).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_generation.py tests/documents/test_api.py tests/documents/test_document_worker.py -q -k "pending"`
Expected: FAIL with `ImportError: cannot import name 'ChangesPending'`, and with the API test getting 202.

- [ ] **Step 3: Implement**

In `apps/documents/generation.py`, add `from .reupload import has_pending_changes` to the imports and this class after `ApplicationEmailMissing`:

```python
class ChangesPending(RuntimeError):
    """A newer CV changed confirmed facts and the student has not settled them.

    While a change is pending the entry's old row is superseded and its new row
    is unconfirmed, so generatable_facts sees neither: a CV generated now would
    silently leave the entry out. A precondition, like IdentityNotConfirmed.
    """
```

Make this the first statement of `generate_cv`'s body, before the identity check:

```python
    if has_pending_changes(student):
        raise ChangesPending("settle the changes from the newer CV first")
```

In `apps/documents/api.py::generate`, insert directly after `programme_id = _programme_id(body, student)`:

```python
    if has_pending_changes(student):
        raise _ApiError(409, "cv_changes_pending")
```

Import it with `from .reupload import has_pending_changes`.

In `apps/documents/document_worker.py::_generate`, wrap the call:

```python
        try:
            result = generate_cv(student=student, programme=programme)
        except ChangesPending:
            # The API refuses this up front; only a CV uploaded between that
            # check and this job reaches here. Dropped, not raised, like an
            # unknown programme: retrying cannot settle the student's list.
            logger.warning(
                "DocumentGenerateChangesPending student=%s: not generated", message.student_id
            )
            return
```

Add `ChangesPending` to the existing `from .generation import ...` line in that module.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_generation.py tests/documents/test_api.py tests/documents/test_document_worker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/generation.py apps/documents/api.py apps/documents/document_worker.py tests/documents/test_generation.py tests/documents/test_api.py tests/documents/test_document_worker.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): no CV is generated while a newer CV's changes are unsettled" -- apps/documents/generation.py apps/documents/api.py apps/documents/document_worker.py tests/documents/test_generation.py tests/documents/test_api.py tests/documents/test_document_worker.py
```

---

### Task 5: "Changed since your last CV" on the documents page

**Files:**
- Modify: `apps/documents/views.py` (`page_context`, around line 182; new view `settle_cv_changes`)
- Modify: `apps/documents/urls.py` (one path)
- Modify: `templates/student/_documents.html` (new section directly above `<section aria-labelledby="facts-heading" ...>`, inside the same `{% if not staff_view %}`)
- Test: `tests/documents/test_documents_page.py`

**Interfaces:**
- Consumes: `reupload.pending_changes`, `reupload.settle_changes`, `reupload.PendingChange` (Task 3).
- Produces:
  - The URL name `student-cv-changes` → `POST /student/documents/cv-changes/`, with form fields `shown` (repeated, fact ids) and `accept` (repeated, fact ids).
  - A `page_context` key `cv_changes: list[PendingChange]`.
  - `facts` and `confirm_body` now exclude pending rows.

- [ ] **Step 1: Write the failing tests** (append to `tests/documents/test_documents_page.py`)

```python
from apps.documents.models import VerifiedFact

CHANGES = "/student/documents/cv-changes/"


def _changed_degree(student):
    old = VerifiedFact.objects.create(
        student=student, category=VerifiedFact.Category.EDUCATION,
        payload={"degree_as_awarded": "BSc", "institution_original": "UFAZ", "city": "Baku"},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:first",
        confirmed_by=student, confirmed_at=timezone.now(), created_by=student,
    )
    new = VerifiedFact.objects.create(
        student=student, category=VerifiedFact.Category.EDUCATION,
        payload={**old.payload, "city": "Sumqayit"},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:second",
        supersedes=old, created_by=student,
    )
    return old, new


def test_a_changed_value_is_shown_old_beside_new_and_not_in_the_confirm_list(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _, new = _changed_degree(membership_a)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Changed since your last CV" in body
    assert "city Baku → Sumqayit" in body
    assert f'name="accept" value="{new.id}" checked' in body
    assert str(new.id) not in body.split('id="facts-heading"')[1]


def test_an_unticked_change_keeps_the_old_value_through_the_page(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        old, new = _changed_degree(membership_a)
    client.force_login(user_a)
    response = client.post(CHANGES, {"shown": [str(new.id)]}, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        tip = VerifiedFact.objects.get(supersedes=new)
    assert tip.payload["city"] == "Baku" and tip.confirmed_by_id == membership_a.id


def test_a_ticked_change_is_confirmed_through_the_page(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _, new = _changed_degree(membership_a)
    client.force_login(user_a)
    client.post(CHANGES, {"shown": [str(new.id)], "accept": [str(new.id)]},
                HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        new.refresh_from_db()
    assert new.confirmed_by_id == membership_a.id


def test_a_malformed_id_is_404(client, agency_a, domain_a, user_a, membership_a) -> None:
    client.force_login(user_a)
    response = client.post(CHANGES, {"shown": ["not-a-uuid"]}, HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_the_counselor_sees_the_changes_but_no_form(agency_a, membership_a, rf) -> None:
    with tenant_scope(agency_a.id):
        _changed_degree(membership_a)
        html = render_to_string(
            "student/_documents.html", page_context(membership_a, counselor_view=True),
            request=rf.get("/"),
        )
    assert "city Baku → Sumqayit" in html
    assert CHANGES not in html
    assert 'name="accept"' not in html
```

Also add `"/student/documents/cv-changes/"` to nothing in `test_the_counselor_view_carries_no_student_only_action`: that test already asserts `"/student/documents/"` is absent from the counsellor HTML, which covers the new form action.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_documents_page.py -q -k "changed or unticked or ticked or malformed or counselor_sees"`
Expected: FAIL. The section is absent and the POST returns 404 (no such URL).

- [ ] **Step 3: Implement the view and context** (`apps/documents/views.py`)

Imports: `from django.db import IntegrityError` and `from .reupload import pending_changes, settle_changes`.

In `page_context`, replace the line `facts = list(unsuperseded_facts(student).filter(confirmed_by__isnull=True))` with:

```python
    cv_changes = pending_changes(student)
    pending_ids = {change.fact.id for change in cv_changes}
    # A pending change is settled in its own list, old beside new; confirming
    # it from the plain list would accept it without the student seeing the
    # value it replaces.
    facts = [
        fact
        for fact in unsuperseded_facts(student).filter(confirmed_by__isnull=True)
        if fact.id not in pending_ids
    ]
```

Add `"cv_changes": cv_changes,` to the returned dict, next to `"facts": facts,`.

Add the view after `documents_page`:

```python
@login_required
@require_POST
def settle_cv_changes(request: HttpRequest) -> HttpResponse:
    """Spec §4: one press settles the "changed since your last CV" list.

    `shown` names every change the page displayed and `accept` the ticked ones;
    an unticked change keeps the old value. settle_changes ignores any id that
    is not one of this student's pending changes, so a stale page or a forged
    id changes nothing.
    """
    student = current_membership(request, Membership.Role.STUDENT)
    shown = [_uuid(value) for value in request.POST.getlist("shown")]
    accepted = [_uuid(value) for value in request.POST.getlist("accept")]
    try:
        settle_changes(student=student, shown=shown, accepted=accepted, actor=student)
    except IntegrityError:
        messages.error(request, "Your choices were not saved -- the list below is current.")
    else:
        messages.success(request, "Saved. Your next CV uses these facts.")
    return redirect("student-documents")
```

In `apps/documents/urls.py`, add after the `student-document-submit` path:

```python
    path(
        "student/documents/cv-changes/",
        views.settle_cv_changes,
        name="student-cv-changes",
    ),
```

- [ ] **Step 4: Add the section to `templates/student/_documents.html`**

Insert directly after `{% if not staff_view %}` and before `<section aria-labelledby="facts-heading" id="facts">`:

```django
{% if cv_changes %}
<section aria-labelledby="changes-heading" id="cv-changes">
  <h2 id="changes-heading">Changed since your last CV</h2>
  {% if not counselor_view %}
  <form method="post" action="{% url 'student-cv-changes' %}">
    {% csrf_token %}
    <p>Untick a change to keep what we had before.</p>
  {% endif %}
    <ul>
      {% for change in cv_changes %}
        <li>
          {% if not counselor_view %}<input type="hidden" name="shown" value="{{ change.fact.id }}"><label><input type="checkbox" name="accept" value="{{ change.fact.id }}" checked> {% endif %}{{ change.fact.category|lower }}: {% for key, old, new in change.changes %}{{ key }} {{ old|default:"(none)" }} → {{ new }}{% if not forloop.last %}; {% endif %}{% endfor %}{% if not counselor_view %}</label>{% endif %}
        </li>
      {% endfor %}
    </ul>
  {% if not counselor_view %}
    <button type="submit">Confirm these changes</button>
  </form>
  {% endif %}
</section>
{% endif %}
```

Auto-escaping stays on: the values are the student's own text, and the counsellor view shows another person's text.

- [ ] **Step 5: Run the page tests and the suite**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents tests/dashboard -q`
Expected: PASS.

- [ ] **Step 6: Full gates and commit**

```bash
uv run ruff check .
uv run mypy apps config
POSTGRES_DB=elmify_cv_engine_design uv run pytest -q
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/views.py apps/documents/urls.py templates/student/_documents.html tests/documents/test_documents_page.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): the student settles a newer CV's changes in one list" -- apps/documents/views.py apps/documents/urls.py templates/student/_documents.html tests/documents/test_documents_page.py
```

Expected: every gate passes and `makemigrations --check` reports "No changes detected".

---

## Self-review

- **Spec coverage (§4).**
  - Matching by category and identity over the whole chain: Task 1.
  - Entries only in the new CV are added, and entries only in the old one stay: Task 1, `test_a_new_entry_is_added_and_an_old_only_entry_stays`.
  - One confirmation, old beside new, unticked keeps the old: Tasks 3 and 5.
  - The dead end goes away: Task 2, one current fact after a changed date, so no CONFLICTING pair.
  - The three named tests: Task 2 (one changed date), Task 3 (unticked keeps old), Task 1 (corrected title survives).
- **Placeholders.** None. Every test uses helpers that exist in its module today (`_candidate`, `_post`, `queued`, `make_identity_fact`, `_openai_client`, `promoted_upload`).
- **Types.** `fact_identity`, `chains`, `plan_upload`, `pending_changes`, `has_pending_changes`, `settle_changes` and `ChangesPending` keep the same names and signatures in every task that uses them.
- **Review Focus.** Lines 1–5 are each pinned by a named test in the owning task.
