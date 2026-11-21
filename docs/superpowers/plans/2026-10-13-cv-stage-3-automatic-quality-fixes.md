# CV Stage 3: Automatic Quality Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generation fixes four recurring CV defects by itself and shows every change with its original beside it. The four defects are bullets that do not start with what the student did, soft-skill filler, abbreviated degree titles, and a thesis filed as a job. The student can undo any change, and no model writes a sentence.

**Architecture:**
- **One pure module, `apps/documents/cv_fixes.py`.** It holds the two ledger stamps, the soft-skill filter, thesis placement, full titles and the `AppliedFix` record.
- **One Jev module, `apps/documents/cv_verbs.py`.** It detects verb-opener lines, asks one closed question per line, and attaches the chosen opening in front of the student's own words. The opening comes from a fixed list, and the list is filtered by code so a verb can never be stronger than the entry's own words.
- **Where the fixes run.** `generation.generate_cv` runs all of them after the model returns and before tailoring and verification. It writes the list to a new `DocumentDraft.applied_fixes`.
- **Undo store.** A new tenant table, `CvFixRevert`, records the student's "undo" and "put back" choices.
- **The two non-generation changes.** A gap question asks for an abbreviated title in full, and a render transform prints a thesis once.

**Tech Stack:** Django 5, PostgreSQL row-level security, the TypeSafe SDK behind `apps/research/decisions.py::ask` (Jev `typesafe/jev-1.13` through OpenRouter), Django's cache, WeasyPrint, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-cv-engine-quality-design.md` §5 (and §10 for data and erasure). Evidence: `docs/research/2026-10-12-cv-engine/section-2-refined.md` §2.5, §3, §4, §5 and §6 (detection rules and measured cases); `2026-10-12-cv-wordlists-and-merit-items.md` §2 (English soft-skill list); `2026-10-12-faithful-rewriting-checks.md` (why no model rewrites).

**Depends on:**
- **Stage 2** (`docs/superpowers/plans/2026-10-13-cv-stage-2-newer-cv-replaces-facts.md`). The stamps and fixes assume one current fact per real thing, and they use `verification.fact_identity`, which Stage 2 adds.
- **Stage 1** (`docs/superpowers/plans/2026-10-13-cv-stage-1-layout-and-typography.md`). `_render_pdf` already takes `today`, `compact`, `font_family` and `font_pt`, and `render.without_future_starts` exists. Task 8 adds one line at the top of `_render_pdf` and does not touch those parameters.

## Decisions made in this plan

1. **The fixes run at generation, on the generated content, not on the ledger.** A fix the student undoes simply stops applying on the next generation. The ledger changes only when the student presses "Keep this wording" (decision 9).
2. **The verb list has fixed strength levels, and code picks which ones Jev may choose from.**
   - Level 1, always allowed: Worked on, Contributed to, Assisted with, Used, Studied.
   - Level 2: Developed, Implemented, Built, Wrote, Tested, Designed.
   - Level 3: Led, Managed, Coordinated, Supervised.
   - A level is unlocked only when the entry's own title or bullets already use a verb of that level. A higher level unlocks the lower ones.
   - Jev chooses only among the unlocked openings, or `leave_unchanged`. Inflation is therefore impossible by construction, not merely discouraged.
3. **Present tense for an ongoing post, past tense otherwise.** Each opening has both forms ("Work on" / "Worked on").
4. **"I built X" becomes "Built X" in plain code, with no Jev call.** Attaching an opening to "I built" would be ungrammatical, and dropping the pronoun claims nothing new. Lines opening with "We", "Our", "My", a duty phrase ("Responsible for") or a preposition stay as written: a prefix cannot fix them, and dropping "we" would turn team work into solo work.
5. **Jev settings:**
   - **Bar.** An answer below 0.9 confidence is doubt, and doubt keeps the line. This is the same starting bar as the relevance engine.
   - **Cap.** At most 30 bullets are asked about per CV.
   - **Limiter.** A new `cv-verb` bucket in `rate_limited`, 10 calls per hour per student, the same as `cv_generation`. It is counted only when an uncached line is asked.
   - **Cache.** Answers live in Django's cache (Valkey in production) for 30 days, keyed by student, question version and a SHA-256 of the line and its allowed openings. There is no new table: the cache holds an option id under a digest, no student text, and it expires by itself.
6. **Jev is behind a launch gate, `CV_VERB_JEV_ENABLED`, off by default.**
   - This follows `TRANSCRIPT_JEV_ENABLED`: student text reaches OpenRouter only after the DPA and terms review.
   - With the gate off, §5.1 does nothing except the "I" fix. The other three fixes need no model and are always on.
   - `decisions.ask` is called with `record=False`, because `DecisionRecord` is shared-catalog data.
7. **Soft-skill list: 28 English terms plus spelling variants**, from the two verified sources (National Careers Service, Loughborough).
   - "networking" (a technical skill for a network engineer), "planning" (urban planning) and "negotiating" are left off. `section-2-refined.md` also leaves off negotiation.
   - Skills of kind `language`, `library` or `technique`, and skills backed by an `AUTHORITATIVE_DOCUMENT` fact, are never filtered.
8. **Full titles (§5.3):**
   - A title is replaced only from an `AUTHORITATIVE_DOCUMENT` EDUCATION fact (a diploma or transcript reading). That fact must have the same institution and the same end year. Every cut-off word of the abbreviation ("Chem.", "Eng.") must also start a word of the full title, in order. Exactly one fact may match.
   - The replacement is kept only when the verifier still reads that entry SUPPORTED or UNCERTAIN. Otherwise the title prints as written.
   - **The line budget is the schema's limit:** 200 characters for a degree title and 300 for an institution. A longer title is refused, both from a document and from the student's answer.
   - No code writes authoritative EDUCATION facts today; the document fact-reading branch is not merged. Until it is, every abbreviation prints as written and the new gap question asks for it.
9. **"One-tap fixes from the student" (§5.5) means "Keep this wording" on a verb fix.** It writes the fixed bullet into the ledger as a superseding EXPERIENCE fact, confirmed by the student, with a `fact.cv_fix_kept` audit event. The other fixes need no ledger write: placement and omission are presentation, and an undo row covers them.
10. **An abbreviation the student retypes unchanged is remembered as "as printed".** It is stored as a `CvFixRevert` row with fix `abbreviated_name`, and the question stops. Without this, a student whose diploma really says "UFAZ" would be asked forever.
11. **The thesis prints once only in the three `cv_base.html` paths** (`_render_pdf`). There a Research entry whose title equals a degree's thesis title is headed "Thesis research" and loses its own supervisor line. The Europass API sends no thesis per degree (`europass.py`), so the Research entry stays the only place it names the thesis there. The funder templates keep their own forms.
12. **Erasure:**
    - `CvFixRevert.subject` is classified REDACT. The rows are also deleted in `advance_deletion` before `redact_student` runs, because redacting every subject to `""` would collide on the table's unique constraint. This is the `PortalAnswer` precedent.
    - `DocumentDraft.applied_fixes` is REDACT, since it holds the student's original text.
13. **§3.2's opt-in for a not-yet-started place is not in this plan.** It needs the undo store built here, plus a `kept` argument threaded through every render path, including the Europass cache key (`europass_render.payload_hash` hashes `europass_content`). That threading is its own small follow-up plan. Until then, a not-yet-started place behaves as Stage 1 left it.
14. **What "undo" means after the CV exists.** An undo or put-back takes effect on the next generated CV, and the page says so, as Stage 2's changes do. An already approved PDF is never altered.

## Global Constraints

- Master's applicants only. English CVs only (MVP): every word list and the verb fix are English. A CV whose bullets are not detected as English (`letter_terms.detect_language`) gets no verb fix.
- No model writes a sentence. Jev only chooses an option id; code attaches it.
- Nothing the student did not provide may appear on the CV. Every change either moves the student's words, leaves an item out, adds one opening from the fixed list, or copies a title from a document the platform read.
- Lint only: `uv run ruff check .`. Never `ruff format`.
- Types: `uv run mypy apps config`.
- Tests: `POSTGRES_DB=elmify_cv_engine_design uv run pytest -q`.
- `uv run python manage.py makemigrations --check --dry-run` must be clean after Task 2's two migrations.
- Never hand-edit an applied migration.
- A new tenant table follows `apps/documents/migrations/0026_transcript_pages_tenant_guards.py` (ENABLE and FORCE RLS, the `tenant_isolation` policy, composite tenant FKs) and gets `apps/audit/redaction.py` entries.
- Cross-tenant tests go through `rls_enforced_orm`, because the test database role bypasses RLS.
- LLM rules (CLAUDE.md "LLM/AI security"):
  - the bullet text is labelled as data, through `decisions.ask`'s state;
  - the output is a closed Choice;
  - the call is rate-limited per student;
  - Jev sees the bullet text only: never the name, the employer or another line.
- Never log a bullet, a title or a skill name. Log check names and counts only.
- Worktree `/home/orkhan/Desktop/cv-engine-design`, branch `claude/cv-engine-quality-design`. Use `git -C` for every git command. Commit with a pathspec: another session builds in this checkout. Never `git add -A`.

## Review Focus

1. **A noun line Jev should leave alone** ("The best poster award, EuChemS 2024."). Expected: when Jev answers `leave_unchanged` or is under 0.9, the line is byte-identical to the student's. Pinned in Task 5 (`test_doubt_keeps_the_line`).
2. **A modest entry that would read better with "Led"** (no leading verb anywhere in the entry). Expected: "Led" is never offered to Jev, so it can never appear. Pinned in Task 4 (`test_a_stronger_verb_needs_the_entrys_own_words`).
3. **Generation's model rewords a bullet the student kept, or invents a skill heading.** Expected: the ledger's bullets and headings win. Pinned in Task 1.
4. **A student undoes a fix, then generates again.** Expected: the original prints, the fix is listed as undone, and "Apply again" restores it. Pinned in Tasks 3 and 11.
5. **Jev is down, rate-limited or switched off.** Expected: the CV generates with every line as written, with no error. Pinned in Task 5 (`test_an_unavailable_jev_leaves_every_line`, `test_the_gate_off_asks_nothing`).

---

### Task 1: The two ledger stamps (§5.6)

**Files:**
- Create: `apps/documents/cv_fixes.py`
- Modify: `apps/documents/generation.py` (`generate_cv`, after each `_call_model(...)`)
- Test: `tests/documents/test_cv_fixes.py` (create), `tests/documents/test_generation.py`

**Interfaces:**
- Consumes: `verification.fact_identity(category, payload) -> tuple[str, ...]` (Stage 2); `verification.fact_payload`; `hygiene.normalize_text`.
- Produces:
  - `cv_fixes.fold(text: str) -> str`.
  - `cv_fixes.stamp_from_ledger(content: CVContent, facts: Sequence[VerifiedFact]) -> CVContent`.
  - It is called in `generate_cv` with `prompt_facts` (the confirmed facts the model saw).

- [ ] **Step 1: Write the failing tests** (`tests/documents/test_cv_fixes.py`)

```python
"""Stage 3 (spec 2026-10-12 §5): automatic quality fixes."""

from datetime import date

import pytest
from django.utils import timezone

from apps.documents.cv_fixes import stamp_from_ledger
from apps.documents.models import VerifiedFact
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    ExperienceEntry,
    PersonalInformation,
    SkillEntry,
)
from apps.documents.verification import fact_payload
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

EXP = VerifiedFact.Category.EXPERIENCE
SKILL = VerifiedFact.Category.SKILL
EDU = VerifiedFact.Category.EDUCATION


def _cv(**over):
    fields = dict(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(
            EducationEntry(
                degree_as_awarded="MSc Chemoinformatics",
                institution_original="University of Strasbourg",
                start_date=date(2024, 9, 1),
                end_date=date(2026, 6, 30),
            ),
        ),
        experience=(), research=(), publications=(), awards=(), skills=(), languages=(),
        document_language="en",
    )
    fields.update(over)
    return CVContent(**fields)


def _post(**over):
    fields = dict(
        employer="EPFL", title="Research Intern", start_date=date(2025, 6, 1),
        end_date=date(2025, 9, 1),
        bullets=("Benchmarked the models for the group and wrote the report.",),
    )
    fields.update(over)
    return ExperienceEntry(**fields)


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _fact(student, category, payload, *, tier=VerifiedFact.SourceTier.STUDENT_STATEMENT):
    return VerifiedFact.objects.create(
        student=student, category=category, payload=payload, source_tier=tier,
        source_ref="upload:test", confirmed_by=student, confirmed_at=timezone.now(),
        created_by=student,
    )


def test_reworded_bullets_are_restored_from_the_ledger(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp-b")
        fact = _fact(student, EXP, fact_payload(_post(), category=EXP))
        reworded = _cv(experience=(_post(bullets=("Spearheaded benchmarking.",)),))
        stamped = stamp_from_ledger(reworded, [fact])
    assert stamped.experience[0].bullets == (
        "Benchmarked the models for the group and wrote the report.",
    )


def test_an_invented_skill_heading_is_replaced_by_the_ledgers(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp-s")
        fact = _fact(student, SKILL, {"name": "Python", "category": None})
        renamed = _cv(skills=(SkillEntry(name="python", category="Core Competencies"),))
        stamped = stamp_from_ledger(renamed, [fact])
    assert stamped.skills[0].category is None


def test_an_entry_with_two_matching_facts_is_left_alone(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp-2")
        payload = fact_payload(_post(), category=EXP)
        facts = [_fact(student, EXP, payload),
                 _fact(student, EXP, {**payload, "bullets": ["Other line."]})]
        content = _cv(experience=(_post(bullets=("Model's line.",)),))
        assert stamp_from_ledger(content, facts).experience[0].bullets == ("Model's line.",)
```

Append to `tests/documents/test_generation.py`:

```python
def test_generation_restores_the_ledgers_bullets(agency_a, django_user_model):
    from datetime import date as _date

    from apps.documents.schemas import ExperienceEntry

    post = ExperienceEntry(employer="EPFL", title="Research Intern",
                           start_date=_date(2025, 6, 1), bullets=("Wrote the pipeline.",))
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g-stamp")
        _fact(student, confirmed=True)
        VerifiedFact.objects.create(
            student=student, category=VerifiedFact.Category.EXPERIENCE,
            payload=fact_payload(post, category=VerifiedFact.Category.EXPERIENCE),
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:test",
            confirmed_by=student, confirmed_at=timezone.now(), created_by=student,
        )
        reworded = _content().model_copy(update={
            "experience": (post.model_copy(update={"bullets": ("Spearheaded a pipeline.",)}),)
        })
        result = generate_cv(student=student, client=_mock_client(reworded))
    assert result.content.experience[0].bullets == ("Wrote the pipeline.",)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fixes.py tests/documents/test_generation.py -q -k "ledger or heading or two_matching or restores"`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.cv_fixes'`.

- [ ] **Step 3: Create `apps/documents/cv_fixes.py`**

```python
"""Stage 3 (spec 2026-10-12 §5): automatic CV quality fixes, every one a
constrained edit.

No model writes a sentence here. A fix moves the student's own words (thesis
placement), leaves an item out (soft skills), copies a title from a document
the platform read (full titles), or puts one opening from a fixed list in front
of the student's own line (cv_verbs.py; Jev only chooses which). One controlled
study found invented or inflated claims in half of model-rewritten résumés
under a strict prompt (docs/research/2026-10-12-cv-engine/
2026-10-12-faithful-rewriting-checks.md), which is why nothing freer exists.

Every fix is recorded as an AppliedFix with the original beside it. The
student's undo is a CvFixRevert row, and an undone fix stops applying on the
next generation.
"""

from __future__ import annotations

from collections.abc import Sequence

from .hygiene import normalize_text
from .models import VerifiedFact
from .schemas import CVContent
from .verification import fact_identity, fact_payload

_EXP = VerifiedFact.Category.EXPERIENCE
_SKILL = VerifiedFact.Category.SKILL
#: ExperienceEntry.bullets' own limits (schemas.py): a ledger list outside them
#: is not stamped, so a malformed row can never make a draft fail validation.
_MAX_BULLETS = 12
_MAX_BULLET_CHARS = 500


def fold(text: str) -> str:
    """Whole-name comparison form: NFC-normalised, curly apostrophe straightened,
    case-folded."""
    return normalize_text(text).replace("’", "'").casefold().strip()


def _payload(fact: VerifiedFact) -> dict[str, object]:
    return fact.payload if isinstance(fact.payload, dict) else {}


def _ledger_bullets(fact: VerifiedFact) -> tuple[str, ...] | None:
    bullets = _payload(fact).get("bullets")
    if not isinstance(bullets, list) or not 0 < len(bullets) <= _MAX_BULLETS:
        return None
    if not all(isinstance(b, str) and 0 < len(b) <= _MAX_BULLET_CHARS for b in bullets):
        return None
    return tuple(bullets)


def stamp_from_ledger(content: CVContent, facts: Sequence[VerifiedFact]) -> CVContent:
    """Spec §5.6: the two values the verifier never compares are copied from the
    ledger after the model returns, the way generation already stamps the
    contact address -- stamping removes the failure mode instead of detecting it.

    - Bullets: an experience entry matching exactly one experience fact by the
      verifier's identity gets that fact's bullets. Without this the model can
      reword a line the student kept and every verdict stays SUPPORTED.
    - Skill headings: a skill gets the category of the skill fact with the same
      folded name, None included, so a heading the model invented is removed.
    """
    experience_facts = [f for f in facts if f.category == _EXP]
    experience = []
    for entry in content.experience:
        identity = fact_identity(_EXP, fact_payload(entry, category=_EXP))
        matches = [f for f in experience_facts if fact_identity(_EXP, _payload(f)) == identity]
        bullets = _ledger_bullets(matches[0]) if len(matches) == 1 else None
        experience.append(entry.model_copy(update={"bullets": bullets}) if bullets else entry)
    headings = {
        fold(str(_payload(f).get("name") or "")): _payload(f).get("category")
        for f in facts
        if f.category == _SKILL
    }
    skills = tuple(
        skill.model_copy(update={"category": headings[fold(skill.name)]})
        if fold(skill.name) in headings
        else skill
        for skill in content.skills
    )
    return content.model_copy(update={"experience": tuple(experience), "skills": skills})
```

- [ ] **Step 4: Call it in `generate_cv`** (`apps/documents/generation.py`)

Add `from .cv_fixes import stamp_from_ledger`. In `generate_cv`, directly after the first `content = _call_model(...)` statement, add:

```python
    content = stamp_from_ledger(content, prompt_facts)
```

Add the same line directly after the retry's `content = _call_model(...)`, before `content = _apply_tailoring(content, tailored)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fixes.py tests/documents/test_generation.py tests/documents/test_cv_skills_grouping.py -q`
Expected: PASS. If `test_cv_skills_grouping.py` pins a heading the mock model invented while the ledger has none, it pinned the defect this task removes. Change it to the ledger's heading and say so in the test.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/cv_fixes.py apps/documents/generation.py tests/documents/test_cv_fixes.py tests/documents/test_generation.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): stamp bullets and skill headings from the ledger after generation" -- apps/documents/cv_fixes.py apps/documents/generation.py tests/documents/test_cv_fixes.py tests/documents/test_generation.py
```

---

### Task 2: Storage for undo and for the "what we changed" list

**Files:**
- Modify: `apps/documents/models.py` (new `CvFixRevert`; `DocumentDraft.applied_fixes`)
- Create: `apps/documents/migrations/0028_cv_fix_revert_and_applied_fixes.py` (generated)
- Create: `apps/documents/migrations/0029_cv_fix_revert_tenant_guards.py` (hand-written RunSQL)
- Modify: `apps/audit/redaction.py` (REDACT and KEEP entries)
- Modify: `apps/audit/deletion.py` (delete the rows before `redact_student`)
- Modify: `apps/documents/cv_fixes.py` (append the store helpers)
- Test: `tests/documents/test_cv_fix_revert_rls.py` (create), `tests/audit/test_erasure_deletes_cv_fix_reverts.py` (create)

**Interfaces:**
- Produces:
  - The model `documents.CvFixRevert(student, fix: str, subject: str, created_at)`, unique on `(tenant, student, fix, subject)`.
  - The field `DocumentDraft.applied_fixes: JSONField(default=list)`.
  - `cv_fixes.reverted_subjects(student: Membership, fix: str | None = None) -> frozenset[str]`.
  - `cv_fixes.remember_revert(student: Membership, fix: str, subject: str) -> None`.
  - `cv_fixes.forget_revert(student: Membership, subject: str) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/documents/test_cv_fix_revert_rls.py`:

```python
"""CvFixRevert behind a role that cannot bypass row-level security.

Shape from tests/documents/test_transcript_reading_rls.py: transaction=True
because the fixture reconnects, and setup fixtures before rls_enforced_orm so
they write as the superuser.
"""

from uuid import uuid4

import pytest

from apps.documents.cv_fixes import remember_revert, reverted_subjects
from apps.documents.models import CvFixRevert
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def revert_a(agency_a, django_user_model):
    user = django_user_model.objects.create(username=f"rv-{uuid4().hex[:8]}")
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        remember_revert(student, "soft_skill", "a" * 64)
        return CvFixRevert.objects.get(student=student)


def test_the_owning_tenant_reads_its_reverts(revert_a, rls_enforced_orm):
    with tenant_scope(revert_a.tenant_id), tenant_transaction(revert_a.tenant_id):
        student = Membership.objects.get(id=revert_a.student_id)
        assert reverted_subjects(student) == frozenset({"a" * 64})


def test_another_tenant_sees_nothing_even_without_the_orm_filter(
    revert_a, agency_b, rls_enforced_orm
):
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert not CvFixRevert._base_manager.filter(id=revert_a.id).exists()
        assert CvFixRevert._base_manager.filter(id=revert_a.id).update(subject="b" * 64) == 0
```

Create `tests/audit/test_erasure_deletes_cv_fix_reverts.py`. Its shape is `tests/audit/test_erasure_deletes_portal_passwords.py`:

```python
"""Erasure removes the student's undone-fix rows (CV design 2026-10-12 §10).

Two rows on purpose: redacting both subjects to "" without the delete would
collide on cvfixrevert_one_per_subject and fail the whole erasure.
"""

import pytest
from django.utils import timezone

from apps.audit import deletion
from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.documents.cv_fixes import remember_revert
from apps.documents.models import CvFixRevert
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def test_executing_a_deletion_removes_the_students_cv_fix_reverts(
    agency_a, django_user_model, monkeypatch
) -> None:
    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="erase-fixes")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        remember_revert(student, "soft_skill", "c" * 64)
        remember_revert(student, "verb_opener", "d" * 64)
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")
        assert not CvFixRevert.objects.filter(student_id=student.id).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fix_revert_rls.py -q`
Expected: FAIL with `ImportError: cannot import name 'CvFixRevert'`.

- [ ] **Step 3: Add the model and the field** (`apps/documents/models.py`)

On `DocumentDraft`, after `approval_mode`:

```python
    #: Spec §5.5: every automatic fix generation applied (or skipped because the
    #: student undid it), each with the student's original text beside it, as
    #: cv_fixes.AppliedFix.as_json() rows. Student text, so REDACTED on erasure.
    #: Defaults to [] so drafts written before Stage 3 need no data migration.
    applied_fixes = models.JSONField(default=list, blank=True)
```

New model at the end of the file:

```python
class CvFixRevert(TenantScopedModel):
    """The student undid an automatic CV fix, or said a short name is printed
    exactly so (spec §5.5). The row's presence is the decision.

    `subject` is cv_fixes.subject_of(fix, text): a SHA-256 of the fix name and
    the student's text, never the text. Keyed on the text rather than a fact
    id, so the decision survives a re-upload of the same CV and an unrelated
    answer on the same fact; changed text is a new subject and is fixed again.
    advance_deletion deletes these rows before redaction: redacting every
    subject to "" would collide on the unique constraint.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    fix = models.CharField(max_length=30)
    subject = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="cvfixrevert_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "student", "fix", "subject"), name="cvfixrevert_one_per_subject"
            ),
        ]
```

- [ ] **Step 4: Generate the model migration, then write the tenant guards**

Run: `uv run python manage.py makemigrations documents --name cv_fix_revert_and_applied_fixes`
Expected: `apps/documents/migrations/0028_cv_fix_revert_and_applied_fixes.py` is created with `AddField` and `CreateModel`. If the number differs because Stage 1 or 2 added a migration, use whatever number Django assigns and point the next file's dependency at it.

Create `apps/documents/migrations/0029_cv_fix_revert_tenant_guards.py`:

```python
from django.db import migrations

RLS_SQL = """
ALTER TABLE documents_cvfixrevert ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents_cvfixrevert FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents_cvfixrevert
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE documents_cvfixrevert
    ADD CONSTRAINT cvfixrevert_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
"""

REVERSE_SQL = """
ALTER TABLE documents_cvfixrevert DROP CONSTRAINT cvfixrevert_student_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON documents_cvfixrevert;
ALTER TABLE documents_cvfixrevert DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0028_cv_fix_revert_and_applied_fixes"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
```

If `scripts/create_runtime_role.sql` or a later tenancy migration grants table privileges per table rather than by default privileges, add `documents_cvfixrevert` to the same grant the transcript tables received: grep for `documents_transcriptpage` across `scripts/` and `apps/*/migrations/`, and mirror each hit.

- [ ] **Step 5: Store helpers** (append to `apps/documents/cv_fixes.py`)

Add `import hashlib` and `from apps.tenancy.models import Membership`, and import `CvFixRevert` beside `VerifiedFact`:

```python
def subject_of(fix: str, text: str) -> str:
    """The undo key for one fix of one piece of text: a digest, never the text."""
    return hashlib.sha256(f"{fix}\x00{fold(text)}".encode()).hexdigest()


def reverted_subjects(student: Membership, fix: str | None = None) -> frozenset[str]:
    rows = CvFixRevert.objects.filter(student=student)
    if fix is not None:
        rows = rows.filter(fix=fix)
    return frozenset(rows.values_list("subject", flat=True))


def remember_revert(student: Membership, fix: str, subject: str) -> None:
    CvFixRevert.objects.get_or_create(student=student, fix=fix, subject=subject)


def forget_revert(student: Membership, subject: str) -> None:
    CvFixRevert.objects.filter(student=student, subject=subject).delete()
```

- [ ] **Step 6: Redaction and erasure**

In `apps/audit/redaction.py` `REDACT`:
- change `"documents.DocumentDraft": RedactSpec("student_id", ("content",)),` to `RedactSpec("student_id", ("content", "applied_fixes"))`;
- add:

```python
    # A digest of the student's own text (cv_fixes.subject_of). advance_deletion
    # deletes these rows first; this entry is the classification, and the
    # backstop if that order ever changes.
    "documents.CvFixRevert": RedactSpec("student_id", ("subject",)),
```

In `KEEP`, add `"documents.CvFixRevert": ("fix", "created_at"),`. `fix` is a closed set of check names.

In `apps/audit/deletion.py`, directly after `set_local_tenant(request.tenant_id)` and before `redact_student(...)`:

```python
                # Before redaction, not after: every subject would become "" and
                # collide on cvfixrevert_one_per_subject. Inside this block for
                # the reason PortalAnswer's delete is -- FORCE RLS.
                CvFixRevert.objects.filter(student_id=request.student_id).delete()
```

Import it with `from apps.documents.models import CvFixRevert`.

- [ ] **Step 7: Run the tests and the classification sweeps**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fix_revert_rls.py tests/audit tests/tenancy -q`
Expected: PASS, including `tests/audit/test_redaction_classification.py` and the RLS sweep in `tests/tenancy/test_database_isolation.py`.

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected".

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/models.py apps/documents/migrations/0028_cv_fix_revert_and_applied_fixes.py apps/documents/migrations/0029_cv_fix_revert_tenant_guards.py apps/audit/redaction.py apps/audit/deletion.py apps/documents/cv_fixes.py tests/documents/test_cv_fix_revert_rls.py tests/audit/test_erasure_deletes_cv_fix_reverts.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): store undone fixes and the applied-fix list" -- apps/documents/models.py apps/documents/migrations/0028_cv_fix_revert_and_applied_fixes.py apps/documents/migrations/0029_cv_fix_revert_tenant_guards.py apps/audit/redaction.py apps/audit/deletion.py apps/documents/cv_fixes.py tests/documents/test_cv_fix_revert_rls.py tests/audit/test_erasure_deletes_cv_fix_reverts.py
```

Add any grant file touched in Step 4 to both commands.

---

### Task 3: Soft-skill filler left out (§5.2), and the fixes reach the draft

**Files:**
- Modify: `apps/documents/cv_fixes.py` (append)
- Modify: `apps/documents/generation.py` (`GenerationResult`, `_quality_fixes`, `generate_cv`; the new `decisions_client` parameter)
- Modify: `apps/documents/drafts.py` (`create_draft` takes `applied_fixes`)
- Modify: `apps/documents/document_worker.py` (`_generate` passes `applied_fixes`)
- Test: `tests/documents/test_cv_fixes.py`, `tests/documents/test_generation.py`, `tests/documents/test_document_worker.py`

**Interfaces:**
- Consumes: `fold`, `subject_of`, `reverted_subjects`, `stamp_from_ledger` (Tasks 1–2).
- Produces:
  - `cv_fixes.SOFT_SKILL = "soft_skill"`, `VERB_OPENER = "verb_opener"`, `THESIS_PLACEMENT = "thesis_placement"`, `FULL_TITLE = "full_title"`, `ABBREVIATED_NAME = "abbreviated_name"`.
  - `cv_fixes.AppliedFix`, a frozen dataclass with `fix: str`, `subject: str`, `where: str`, `original: str`, `changed: str` (`""` when left out), `undone: bool = False`, and `as_json() -> dict[str, object]`.
  - `cv_fixes.is_soft_skill(name: str, kind: str | None) -> bool`.
  - `cv_fixes.drop_soft_skills(content, facts, undone: frozenset[str]) -> tuple[CVContent, tuple[AppliedFix, ...]]`.
  - `generation.GenerationResult.applied_fixes: tuple[AppliedFix, ...] = ()`.
  - `generation._quality_fixes(content, *, student, facts, verification_facts, decisions_client) -> tuple[CVContent, tuple[AppliedFix, ...]]`.
  - `generate_cv(..., decisions_client: Client | None = None)`.
  - `create_draft(..., applied_fixes: Sequence[Mapping[str, object]] = ())`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_cv_fixes.py`:

```python
from apps.documents.cv_fixes import SOFT_SKILL, drop_soft_skills, is_soft_skill, subject_of


@pytest.mark.parametrize(
    "name, kind, soft",
    [
        ("Teamwork", None, True),
        ("Team-work", None, True),
        ("Excellent communication skills", None, True),
        ("Problem solving", None, True),
        ("Time-management", None, True),
        ("Organisational skills", None, True),
        ("Analytical ability", None, True),
        ("Communication protocols (TCP/IP)", None, False),
        ("Team Foundation Server", None, False),
        ("LEED (Leadership in Energy and Environmental Design)", None, False),
        ("Networking", None, False),
        ("Project management", None, False),
        ("Leadership", "technique", False),
    ],
)
def test_the_soft_skill_list(name, kind, soft):
    assert is_soft_skill(name, kind) is soft


def test_soft_skills_are_left_out_and_listed():
    content = _cv(skills=(SkillEntry(name="Python"), SkillEntry(name="Teamwork")))
    kept, fixes = drop_soft_skills(content, [], frozenset())
    assert [s.name for s in kept.skills] == ["Python"]
    [fix] = fixes
    assert (fix.fix, fix.original, fix.changed, fix.undone) == (SOFT_SKILL, "Teamwork", "", False)


def test_a_put_back_skill_stays_and_is_listed_as_undone():
    content = _cv(skills=(SkillEntry(name="Teamwork"),))
    kept, fixes = drop_soft_skills(content, [], frozenset({subject_of(SOFT_SKILL, "Teamwork")}))
    assert [s.name for s in kept.skills] == ["Teamwork"]
    assert fixes[0].undone is True


def test_a_skill_a_document_vouches_for_is_never_left_out(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "soft-auth")
        fact = _fact(student, SKILL, {"name": "Leadership"},
                     tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT)
        kept, fixes = drop_soft_skills(_cv(skills=(SkillEntry(name="Leadership"),)), [fact],
                                       frozenset())
    assert [s.name for s in kept.skills] == ["Leadership"] and fixes == ()
```

Append to `tests/documents/test_generation.py`:

```python
def test_generation_leaves_a_soft_skill_out_and_records_it(agency_a, django_user_model):
    from apps.documents.schemas import SkillEntry

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g-soft")
        _fact(student, confirmed=True)
        for name in ("Python", "Teamwork"):
            VerifiedFact.objects.create(
                student=student, category=VerifiedFact.Category.SKILL, payload={"name": name},
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:test",
                confirmed_by=student, confirmed_at=timezone.now(), created_by=student,
            )
        content = _content().model_copy(update={
            "skills": (SkillEntry(name="Python"), SkillEntry(name="Teamwork"))
        })
        result = generate_cv(student=student, client=_mock_client(content))
    assert [s.name for s in result.content.skills] == ["Python"]
    assert [f.original for f in result.applied_fixes] == ["Teamwork"]


def test_an_omitted_soft_skill_stays_omitted_through_tailoring():
    """Fixes run before _apply_tailoring, whose empty-intersection fallback
    returns the content it was given -- already without the soft skill."""
    from apps.documents.generation import _apply_tailoring

    kept = _content_with_skills("Python")
    assert [s.name for s in _apply_tailoring(kept, _tailored("Teamwork")).skills] == ["Python"]
```

Append to `tests/documents/test_document_worker.py`, beside `test_a_generate_message_writes_a_draft`:

```python
def test_a_generate_message_stores_the_applied_fixes(agency_a, membership_a, monkeypatch):
    from apps.documents.cv_fixes import AppliedFix

    fix = AppliedFix("soft_skill", "e" * 64, "skills", "Teamwork", "")
    monkeypatch.setattr(
        document_worker,
        "generate_cv",
        lambda **kwargs: GenerationResult(
            content=_content(), verdicts=(), retried=False, applied_fixes=(fix,)
        ),
    )
    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a)
    document_worker.handle_document_work(
        DocumentWorkMessage(action="generate", kind=DocumentDraft.Kind.CV,
                            tenant_id=agency_a.id, student_id=membership_a.id)
    )
    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.get(student=membership_a)
    assert draft.applied_fixes == [fix.as_json()]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fixes.py tests/documents/test_generation.py tests/documents/test_document_worker.py -q -k "soft or applied_fixes"`
Expected: FAIL with `ImportError: cannot import name 'SOFT_SKILL'`.

- [ ] **Step 3: Append the record and the filter to `apps/documents/cv_fixes.py`**

Add `import re` and `from dataclasses import asdict, dataclass`:

```python
SOFT_SKILL = "soft_skill"
VERB_OPENER = "verb_opener"
THESIS_PLACEMENT = "thesis_placement"
FULL_TITLE = "full_title"
#: Not a fix: the student said a short name is printed exactly so (Task 10).
ABBREVIATED_NAME = "abbreviated_name"


@dataclass(frozen=True)
class AppliedFix:
    fix: str
    #: subject_of(fix, original): the undo key.
    subject: str
    #: Where in the generated content, e.g. "experience[0].bullets[2]".
    where: str
    #: The student's own text before the fix.
    original: str
    #: What the CV prints instead; "" when the item was left out.
    changed: str
    #: The student undid it, so the CV prints the original.
    undone: bool = False

    def as_json(self) -> dict[str, object]:
        return asdict(self)


#: English only (MVP). From the two verified sources in docs/research/
#: 2026-10-12-cv-engine/2026-10-12-cv-wordlists-and-merit-items.md §2 (UK
#: National Careers Service; Loughborough University), folded, hyphens as
#: spaces, with the spelling variants the research lists. Left off on purpose:
#: networking (a technical skill for a network engineer), planning (urban
#: planning), negotiating, and every field skill section-2-refined.md §3 names
#: (data analysis, project management, research, teaching, statistics).
SOFT_SKILLS = frozenset({
    "communication", "leadership", "time management", "conflict management",
    "problem solving", "mentoring", "positivity", "flexibility", "team player",
    "teamwork", "team work", "analytical ability", "commercial awareness", "creativity",
    "decision making", "emotional intelligence", "entrepreneurial", "influencing",
    "initiative", "interpersonal", "organisation", "organization", "organisational",
    "organizational", "people management", "presentation", "resilience", "self awareness",
    "self confidence", "self development", "self management", "self motivation",
})
_SOFT_PREFIX = re.compile(r"^(?:strong|excellent|good|effective|great)\s+")
_SOFT_SUFFIX = re.compile(r"\s+(?:skills?|abilities)$")
#: Measured or read from the student's own code (SkillEntry.kind): never filler.
_TECHNICAL_KINDS = frozenset({"language", "library", "technique"})


def is_soft_skill(name: str, kind: str | None) -> bool:
    """Whole-name match only, never a substring: "Communication protocols" and
    "Team Foundation Server" are technical skills."""
    if kind in _TECHNICAL_KINDS:
        return False
    folded = fold(name).replace("-", " ")
    core = _SOFT_SUFFIX.sub("", _SOFT_PREFIX.sub("", folded))
    return folded in SOFT_SKILLS or core in SOFT_SKILLS


def drop_soft_skills(
    content: CVContent, facts: Sequence[VerifiedFact], undone: frozenset[str]
) -> tuple[CVContent, tuple[AppliedFix, ...]]:
    """Spec §5.2 (S-025): general qualities listed as skills are left out of the
    Skills section and listed as left out. The ledger keeps them, so the letter
    engine and tailoring still see them. A skill a document vouches for stays."""
    vouched = {
        fold(str(_payload(f).get("name") or ""))
        for f in facts
        if f.category == _SKILL and f.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
    }
    kept, fixes = [], []
    for skill in content.skills:
        if not is_soft_skill(skill.name, skill.kind) or fold(skill.name) in vouched:
            kept.append(skill)
            continue
        subject = subject_of(SOFT_SKILL, skill.name)
        put_back = subject in undone
        fixes.append(AppliedFix(SOFT_SKILL, subject, "skills", skill.name, "", undone=put_back))
        if put_back:
            kept.append(skill)
    return content.model_copy(update={"skills": tuple(kept)}), tuple(fixes)
```

- [ ] **Step 4: Wire the fixes into generation and the draft**

In `apps/documents/generation.py`:
- import `from apps.research.decisions import Client`;
- import `from .cv_fixes import AppliedFix, drop_soft_skills, reverted_subjects, stamp_from_ledger`;
- add to `GenerationResult`:

```python
    #: Spec §5.5: every automatic fix, applied or undone, with its original.
    applied_fixes: tuple[AppliedFix, ...] = ()
```

Add this function above `generate_cv`:

```python
def _quality_fixes(
    content: CVContent,
    *,
    student: Membership,
    facts: list[VerifiedFact],
    verification_facts: list[VerifiedFact],
    decisions_client: Client | None,
) -> tuple[CVContent, tuple[AppliedFix, ...]]:
    """Spec §5.6 then §5.1-§5.4, after the model and before tailoring and
    verification. Before tailoring on purpose: _apply_tailoring falls back to
    the content it is given, so an omitted skill cannot come back through it."""
    undone = reverted_subjects(student)
    content = stamp_from_ledger(content, facts)
    content, soft = drop_soft_skills(content, facts, undone)
    return content, soft
```

In `generate_cv`:
- add the keyword-only parameter `decisions_client: Client | None = None`;
- replace both `content = stamp_from_ledger(content, prompt_facts)` lines from Task 1 with:

```python
    content, fixes = _quality_fixes(
        content, student=student, facts=prompt_facts,
        verification_facts=verification_facts, decisions_client=decisions_client,
    )
```

- pass `applied_fixes=fixes` to both `GenerationResult(...)` returns.

In `apps/documents/drafts.py::create_draft`:
- add the parameter `applied_fixes: Sequence[Mapping[str, object]] = ()`;
- pass `applied_fixes=[dict(fix) for fix in applied_fixes]` to `DocumentDraft.objects.create`;
- import `Mapping` and `Sequence` from `collections.abc`.

In `apps/documents/document_worker.py::_generate`, add `applied_fixes=[fix.as_json() for fix in result.applied_fixes],` to the `create_draft(...)` call.

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents -q`
Expected: PASS. A test whose mock model returns a soft skill and asserts it prints now sees it left out. Update that assertion to the new behaviour and say so in the test.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/cv_fixes.py apps/documents/generation.py apps/documents/drafts.py apps/documents/document_worker.py tests/documents/test_cv_fixes.py tests/documents/test_generation.py tests/documents/test_document_worker.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): leave soft-skill filler out of Skills and record every fix on the draft" -- apps/documents/cv_fixes.py apps/documents/generation.py apps/documents/drafts.py apps/documents/document_worker.py tests/documents/test_cv_fixes.py tests/documents/test_generation.py tests/documents/test_document_worker.py
```

---

### Task 4: Verb-opener detection and composition (§5.1, plain code)

**Files:**
- Create: `apps/documents/cv_verbs.py`
- Test: `tests/documents/test_cv_verbs.py` (create)

**Interfaces:**
- Consumes: `cv_fixes.fold`, `cv_fixes.subject_of`, `cv_fixes.VERB_OPENER`; `letter_terms.detect_language(page_text: str) -> str`.
- Produces:
  - `cv_verbs.Opener`, a frozen dataclass with `id: str`, `past: str`, `present: str` and `strength: int`.
  - `cv_verbs.OPENERS: tuple[Opener, ...]`.
  - `cv_verbs.needs_opener(bullet: str) -> bool`.
  - `cv_verbs.without_first_person(bullet: str) -> str | None`.
  - `cv_verbs.allowed_openers(entry_text: str) -> tuple[str, ...]`.
  - `cv_verbs.compose(bullet: str, opener_id: str, *, present: bool) -> str | None`.
  - `cv_verbs.Flagged`, a frozen dataclass with `subject: str`, `text: str`, `allowed: tuple[str, ...]` and `present: bool`.
  - `cv_verbs.flagged_bullets(content: CVContent) -> tuple[Flagged, ...]`. It is English only and capped at `MAX_BULLETS = 30`.
  - `cv_verbs.is_english(content: CVContent) -> bool`.

- [ ] **Step 1: Write the failing tests** (`tests/documents/test_cv_verbs.py`)

```python
"""§5.1 detection and composition. Rows are section-2-refined.md §4's measured table."""

from datetime import date

import pytest

from apps.documents.cv_verbs import (
    allowed_openers,
    compose,
    flagged_bullets,
    needs_opener,
    without_first_person,
)
from apps.documents.schemas import CVContent, EducationEntry, ExperienceEntry, PersonalInformation


@pytest.mark.parametrize(
    "line, flagged",
    [
        ("A map-agnostic framework that visualizes the chemical space of the dataset.", True),
        ("Python scripts for the cleaning of the lab data.", True),
        ("The best poster award, EuChemS 2024.", True),  # flagged; Jev should leave it
        ("Development of an automated framework for the group.", True),
        ("Engineered three PyTorch-based models.", False),
        ("Maintain the group's GPU cluster.", False),
        ("Develops the evaluation pipeline.", False),
        ("Tools: Python, RDKit.", False),
        ("Advanced Python course for 40 students.", False),  # -ed: a known miss
        ("I developed three PyTorch models.", False),  # the code-only "I" fix
        ("We built a robot with the team.", False),
        ("Responsible for managing the lab inventory.", False),
        ("In collaboration with Bosch, built a test rig.", False),
        ("3 papers under review.", False),
    ],
)
def test_needs_opener(line, flagged):
    assert needs_opener(line) is flagged


def test_the_first_person_is_dropped_and_nothing_added():
    assert without_first_person("I developed three PyTorch models.") == (
        "Developed three PyTorch models."
    )
    assert without_first_person("I am a fast learner.") is None


def test_a_stronger_verb_needs_the_entrys_own_words():
    modest = allowed_openers("Research Intern Helped with the models.")
    assert "led" not in modest and "built" not in modest and "worked_on" in modest
    did = allowed_openers("Research Intern Wrote the evaluation scripts.")
    assert "built" in did and "led" not in did
    led = allowed_openers("Team Lead Managed four students.")
    assert {"led", "built", "worked_on"} <= set(led)


def test_compose_keeps_every_other_character():
    line = "A map-agnostic framework that visualizes 10B+ compounds."
    assert compose(line, "built", present=False) == (
        "Built a map-agnostic framework that visualizes 10B+ compounds."
    )
    assert compose("PyTorch models for 3.88M molecules.", "built", present=False) == (
        "Built PyTorch models for 3.88M molecules."
    )
    assert compose("Python scripts for the lab.", "wrote", present=True) == (
        "Write Python scripts for the lab."
    )
    assert compose("x" * 495, "contributed_to", present=False) is None


def _cv(bullets, end=date(2025, 9, 1), title="Research Intern"):
    return CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="j@example.com"),
        education=(EducationEntry(degree_as_awarded="MSc Chemistry",
                                  institution_original="University of Strasbourg"),),
        experience=(ExperienceEntry(employer="EPFL", title=title, start_date=date(2025, 6, 1),
                                    end_date=end, bullets=bullets),),
        research=(), publications=(), awards=(), skills=(), languages=(), document_language="en",
    )


def test_only_flagged_english_lines_are_returned():
    content = _cv((
        "Wrote the evaluation scripts for the group.",
        "A framework for the visualisation of chemical space.",
    ))
    [item] = flagged_bullets(content)
    assert item.text == "A framework for the visualisation of chemical space."
    assert "built" in item.allowed and item.present is False


def test_a_non_english_cv_gets_nothing():
    content = _cv(("Entwicklung eines Modells für die Gruppe und der Daten.",
                   "Ein Rahmenwerk für die Visualisierung der Daten."))
    assert flagged_bullets(content) == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_verbs.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.cv_verbs'`.

- [ ] **Step 3: Create `apps/documents/cv_verbs.py`**

```python
"""Spec §5.1 (S-026): a bullet that does not start with what the student did
gets one opening from a fixed list, in front of the student's own words.

Code decides everything except one choice. It finds the line, filters the
openings, attaches the chosen one and refuses an over-long result. Jev only
picks which allowed opening fits the line, or leave_unchanged (Task 5 adds
that call). The opening verb IS a claim -- "Built" and "Used" say different
things about the same line -- so the openings Jev may pick are capped by code
at the strength the student's own words in the same entry already show.

English only (MVP): S-026's sources are English-language guides, and German,
French and Turkish lines rightly open with a noun or end with the verb
(docs/research/2026-10-12-cv-engine/section-2-refined.md §4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .cv_fixes import VERB_OPENER, subject_of
from .letter_terms import detect_language
from .schemas import CVContent

MAX_BULLETS = 30
#: Bullet's own max_length (schemas.py).
_MAX_BULLET = 500


@dataclass(frozen=True)
class Opener:
    id: str
    past: str
    present: str
    #: 1 says the student was involved; 2 that they did it; 3 that they led it.
    strength: int


OPENERS: tuple[Opener, ...] = (
    Opener("worked_on", "Worked on", "Work on", 1),
    Opener("contributed_to", "Contributed to", "Contribute to", 1),
    Opener("assisted_with", "Assisted with", "Assist with", 1),
    Opener("used", "Used", "Use", 1),
    Opener("studied", "Studied", "Study", 1),
    Opener("developed", "Developed", "Develop", 2),
    Opener("implemented", "Implemented", "Implement", 2),
    Opener("built", "Built", "Build", 2),
    Opener("wrote", "Wrote", "Write", 2),
    Opener("tested", "Tested", "Test", 2),
    Opener("designed", "Designed", "Design", 2),
    Opener("led", "Led", "Lead", 3),
    Opener("managed", "Managed", "Manage", 3),
    Opener("coordinated", "Coordinated", "Coordinate", 3),
    Opener("supervised", "Supervised", "Supervise", 3),
)
BY_ID = {opener.id: opener for opener in OPENERS}

#: Words that, in the entry's own title or bullets, unlock a strength (§5.1: a
#: stronger verb only when the student's text already uses one of equal strength).
_STRENGTH_FORMS: dict[int, frozenset[str]] = {
    2: frozenset({
        "develop", "developed", "developing", "develops", "implement", "implemented",
        "implementing", "build", "built", "building", "builds", "write", "wrote", "written",
        "writing", "test", "tested", "testing", "design", "designed", "designing", "designs",
        "created", "engineered", "programmed", "coded", "constructed", "authored",
        "benchmarked", "trained", "deployed",
    }),
    3: frozenset({
        "lead", "led", "leading", "leads", "manage", "managed", "managing", "manages",
        "manager", "coordinate", "coordinated", "coordinating", "coordinator", "supervise",
        "supervised", "supervising", "supervisor", "headed", "directed", "chaired",
    }),
}

#: Base forms of verbs a CV line commonly opens with. A line opening with one
#: of these, its -s/-es form, an irregular past below, or any -ed word is
#: already a verb line.
_VERB_BASES = frozenset({
    "achieve", "add", "administer", "advise", "analyse", "analyze", "apply", "assess",
    "assist", "attend", "automate", "build", "calculate", "chair", "choose", "coach", "code",
    "collaborate", "collect", "compile", "complete", "compute", "conduct", "configure",
    "construct", "contribute", "convert", "coordinate", "create", "curate", "debug",
    "define", "deliver", "demonstrate", "deploy", "design", "develop", "direct", "draft",
    "edit", "engineer", "establish", "evaluate", "examine", "execute", "expand", "explore",
    "extract", "facilitate", "find", "fix", "gather", "generate", "give", "guide", "handle",
    "help", "identify", "implement", "improve", "increase", "integrate", "interview",
    "investigate", "lead", "learn", "maintain", "manage", "measure", "mentor", "migrate",
    "model", "monitor", "optimise", "optimize", "organise", "organize", "perform", "plan",
    "prepare", "present", "process", "produce", "program", "propose", "prototype",
    "publish", "reduce", "refactor", "report", "represent", "research", "review", "run",
    "scale", "set", "simulate", "solve", "speak", "streamline", "study", "supervise",
    "support", "synthesise", "synthesize", "teach", "test", "train", "translate", "tutor",
    "use", "validate", "visualise", "visualize", "volunteer", "win", "work", "write",
})
_IRREGULAR_PAST = frozenset({
    "built", "chose", "drew", "found", "gave", "held", "kept", "led", "made", "met", "ran",
    "saw", "set", "spoke", "taught", "took", "won", "wrote", "began", "brought", "did",
    "got", "put", "read", "sold", "sent", "spent", "understood", "oversaw", "undertook",
})
#: Openings a prefix cannot make grammatical, or would change the claim of:
#: "we" -> solo work, duty phrases, and prepositions.
_NOT_PREFIXABLE = frozenset({
    "we", "our", "my", "us", "responsible", "duties", "tasks", "in", "on", "at", "for",
    "with", "as", "during", "under", "from", "by", "to",
})
#: First words lower-cased after an opening. Everything else keeps its case,
#: because a capital is often a name ("Python scripts", "PyTorch models").
_LOWERCASE_FIRST = frozenset({
    "a", "an", "the", "this", "these", "those", "one", "two", "three", "four", "five",
    "several", "multiple", "various", "some", "each", "all", "both", "new", "over", "more",
})
_NOMINAL_ENDINGS = ("ment", "tion", "sion", "ance", "ence", "ing", "ysis")

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_LABEL = re.compile(r"^[^:]{1,30}:\s")
_FIRST_PERSON = re.compile(r"I\s+([A-Za-z][A-Za-z'-]*)(.*)$", re.DOTALL)


def _is_verb(word: str) -> bool:
    w = word.casefold()
    return (
        w in _VERB_BASES
        or w in _IRREGULAR_PAST
        or w.endswith("ed")
        or (w.endswith("es") and w[:-2] in _VERB_BASES)
        or (w.endswith("s") and w[:-1] in _VERB_BASES)
    )


def needs_opener(bullet: str) -> bool:
    text = bullet.strip()
    first = _WORD.match(text)
    if first is None or _LABEL.match(text):
        return False
    word = first.group().casefold()
    return word != "i" and word not in _NOT_PREFIXABLE and not _is_verb(word)


def without_first_person(bullet: str) -> str | None:
    """'I built X' -> 'Built X'. Deletes the pronoun and adds nothing: the line
    already said the student did it."""
    match = _FIRST_PERSON.match(bullet.strip())
    if match is None or not _is_verb(match.group(1)):
        return None
    verb = match.group(1)
    return verb[0].upper() + verb[1:] + match.group(2)


def allowed_openers(entry_text: str) -> tuple[str, ...]:
    words = {word.casefold() for word in _WORD.findall(entry_text)}
    strength = max(
        (level for level, forms in _STRENGTH_FORMS.items() if words & forms), default=1
    )
    return tuple(opener.id for opener in OPENERS if opener.strength <= strength)


def compose(bullet: str, opener_id: str, *, present: bool) -> str | None:
    """The opening plus the student's line. Only the first letter's case can
    change; None when the result would exceed a Bullet's limit."""
    opener = BY_ID[opener_id]
    text = bullet.strip()
    first = _WORD.match(text)
    word = first.group().casefold() if first else ""
    lower = word in _LOWERCASE_FIRST or word.endswith(_NOMINAL_ENDINGS)
    tail = text[0].lower() + text[1:] if lower else text
    new = f"{opener.present if present else opener.past} {tail}"
    return new if len(new) <= _MAX_BULLET else None


@dataclass(frozen=True)
class Flagged:
    subject: str
    text: str
    allowed: tuple[str, ...]
    present: bool


def is_english(content: CVContent) -> bool:
    return detect_language(" ".join(b for e in content.experience for b in e.bullets)) == "en"


def flagged_bullets(content: CVContent) -> tuple[Flagged, ...]:
    if not is_english(content):
        return ()
    found: list[Flagged] = []
    for entry in content.experience:
        allowed = allowed_openers(" ".join((entry.title, *entry.bullets)))
        for bullet in entry.bullets:
            if needs_opener(bullet):
                found.append(
                    Flagged(subject_of(VERB_OPENER, bullet), bullet, allowed, entry.end_date is None)
                )
    return tuple(found[:MAX_BULLETS])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_verbs.py -q`
Expected: PASS. If `detect_language` reads a test CV as something other than English, add English function words to that test's bullets. Do not weaken `is_english`.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/cv_verbs.py tests/documents/test_cv_verbs.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): find bullets that do not open with a verb and compose a capped opening" -- apps/documents/cv_verbs.py tests/documents/test_cv_verbs.py
```

---

### Task 5: Jev picks the opening

**Files:**
- Modify: `apps/documents/cv_verbs.py` (append)
- Modify: `config/settings/base.py` (one gate setting, beside `TRANSCRIPT_JEV_ENABLED`)
- Test: `tests/documents/test_cv_verbs.py` (append)

**Interfaces:**
- Consumes: `decisions.ask(state, questions, *, decision, record, client)`, `decisions.Choice`, `decisions.Answer`, `decisions.Client`, `decisions.DecisionsUnavailable`, `decisions.provider_for`; `ratelimit.rate_limited`; `Flagged` (Task 4).
- Produces:
  - `cv_verbs.DECISION = "cv_verb_opener"`, `cv_verbs.LEAVE = "leave_unchanged"`, `cv_verbs.BAR = 0.9`.
  - `cv_verbs.choose_openers(items: Sequence[Flagged], *, student_id: UUID, client: Client | None = None) -> dict[str, str]`, mapping subject to opener id. A missing subject means the line stays as written.
  - The setting `CV_VERB_JEV_ENABLED: bool`.

- [ ] **Step 1: Write the failing tests** (append to `tests/documents/test_cv_verbs.py`)

```python
from uuid import uuid4

from django.core.cache import cache

from apps.documents import cv_verbs
from apps.documents.cv_verbs import LEAVE, Flagged, choose_openers
from apps.research.decisions import Answer, DecisionsUnavailable


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


def _item(text="A framework for the visualisation of chemical space.", allowed=("worked_on", "built")):
    return Flagged(subject=f"s-{text}", text=text, allowed=allowed, present=False)


def _jev(value, confidence=0.97, states=None):
    def call(state, questions, *, model, provider):
        if states is not None:
            states.append(state)
        return {
            qid: Answer(id=qid, value=value, confidence=confidence,
                        probabilities={value: confidence}, model=model, provider=provider)
            for qid in questions
        }
    return call


@pytest.fixture
def gate_on(settings):
    settings.CV_VERB_JEV_ENABLED = True
    settings.DECISIONS_PROVIDER = {"default": "typesafe"}


def test_a_confident_allowed_answer_is_used(gate_on):
    item = _item()
    assert choose_openers([item], student_id=uuid4(), client=_jev("built")) == {
        item.subject: "built"
    }


def test_doubt_keeps_the_line(gate_on):
    item = _item()
    assert choose_openers([item], student_id=uuid4(), client=_jev(LEAVE)) == {}
    cache.clear()
    assert choose_openers([item], student_id=uuid4(), client=_jev("built", 0.6)) == {}


def test_an_answer_outside_the_allowed_list_is_refused(gate_on):
    assert choose_openers([_item()], student_id=uuid4(), client=_jev("led")) == {}


def test_jev_sees_the_bullet_text_only(gate_on):
    states = []
    choose_openers([_item()], student_id=uuid4(), client=_jev("built", states=states))
    assert states == [{"bullets": {"b0": "A framework for the visualisation of chemical space."}}]


def test_a_cached_answer_is_not_asked_again(gate_on):
    student = uuid4()
    choose_openers([_item()], student_id=student, client=_jev("built"))
    states = []
    assert choose_openers([_item()], student_id=student, client=_jev("worked_on", states=states))
    assert states == []


def test_an_unavailable_jev_leaves_every_line(gate_on):
    def down(state, questions, *, model, provider):
        raise DecisionsUnavailable("down")

    assert choose_openers([_item()], student_id=uuid4(), client=down) == {}


def test_the_gate_off_asks_nothing(settings):
    settings.CV_VERB_JEV_ENABLED = False
    states = []
    assert choose_openers([_item()], student_id=uuid4(), client=_jev("built", states=states)) == {}
    assert states == []


def test_the_limiter_stops_the_call(gate_on, monkeypatch):
    monkeypatch.setattr(cv_verbs, "rate_limited", lambda *a, **k: True)
    states = []
    assert choose_openers([_item()], student_id=uuid4(), client=_jev("built", states=states)) == {}
    assert states == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_verbs.py -q`
Expected: FAIL with `ImportError: cannot import name 'LEAVE'`.

- [ ] **Step 3: Add the gate** (`config/settings/base.py`, after `TRANSCRIPT_JEV_ENABLED`)

```python
#: Launch gate for apps/documents/cv_verbs.py (CV design 2026-10-12 §5.1): a
#: student's CV bullets go to Jev, through OpenRouter, only after the same DPA
#: and terms review TRANSCRIPT_JEV_ENABLED waits for. Off: lines stay as written.
CV_VERB_JEV_ENABLED = os.getenv("CV_VERB_JEV_ENABLED", "") == "1"
```

- [ ] **Step 4: Append the Jev call to `apps/documents/cv_verbs.py`**

Imports to add: `hashlib`, `logging`, `from collections.abc import Sequence`, `from uuid import UUID`, `from django.conf import settings`, `from django.core.cache import cache`, `from apps.ratelimit import rate_limited`, and `from apps.research.decisions import Choice, Client, DecisionsUnavailable, ask, provider_for`. Then:

```python
logger = logging.getLogger(__name__)

DECISION = "cv_verb_opener"
#: Part of every cache key: changing the question or the list re-asks.
QUESTION_VERSION = "v1"
LEAVE = "leave_unchanged"
#: Below this an answer is doubt, and doubt keeps the line (spec §5.1).
BAR = 0.9
_RATE_LIMIT = 10
_RATE_WINDOW_SECONDS = 3600
_CACHE_SECONDS = 30 * 24 * 3600

_QUESTION = (
    "This is one line from the work-experience section of a CV. Which opening, put in "
    "front of the line exactly as it stands, says what the applicant did without "
    "claiming more than the line itself says? Choose leave_unchanged if the line names "
    "an award, a course, a topic or a title rather than work the applicant did, or if "
    "every opening would claim more than the line says."
)


def _question(item: Flagged, key: str) -> Choice:
    return Choice(
        question=_QUESTION,
        options=(*item.allowed, LEAVE),
        criteria={
            **{oid: f"Start the line with '{BY_ID[oid].past}'." for oid in item.allowed},
            LEAVE: "Keep the line exactly as written.",
        },
        inspect=f"`bullets.{key}`",
    )


def _cache_key(student_id: UUID, item: Flagged) -> str:
    digest = hashlib.sha256(
        f"{QUESTION_VERSION}\x00{item.text}\x00{','.join(item.allowed)}".encode()
    ).hexdigest()
    return f"cv-verb:{student_id}:{digest}"


def choose_openers(
    items: Sequence[Flagged], *, student_id: UUID, client: Client | None = None
) -> dict[str, str]:
    """subject -> opener id for every line Jev placed an allowed opening on with
    confidence. Anything else -- doubt, leave_unchanged, the gate off, the
    limiter, an unavailable provider -- keeps the line as written.

    Jev sees each bullet's text and nothing else: no name, no employer, no other
    line. record=False: DecisionRecord is shared-catalog data, and this state is
    one student's text (decisions.ask's own rule).
    """
    if not items or not settings.CV_VERB_JEV_ENABLED or provider_for(DECISION) != "typesafe":
        return {}
    chosen: dict[str, str] = {}
    todo: list[Flagged] = []
    for item in items:
        hit = cache.get(_cache_key(student_id, item))
        if hit is None:
            todo.append(item)
        elif hit != LEAVE:
            chosen[item.subject] = hit
    if not todo:
        return chosen
    if rate_limited("cv-verb", student_id, limit=_RATE_LIMIT, window_seconds=_RATE_WINDOW_SECONDS):
        logger.info("cv verb openers rate limited: %d lines left as written", len(todo))
        return chosen
    try:
        answers = ask(
            {"bullets": {f"b{n}": item.text for n, item in enumerate(todo)}},
            {f"b{n}": _question(item, f"b{n}") for n, item in enumerate(todo)},
            decision=DECISION,
            record=False,
            client=client,
        )
    except DecisionsUnavailable as error:
        logger.warning("cv verb openers unavailable (%s): %d lines left as written",
                       error.kind, len(todo))
        return chosen
    for n, item in enumerate(todo):
        answer = answers[f"b{n}"]
        value = (
            str(answer.value)
            if answer.confidence >= BAR and answer.value in item.allowed
            else LEAVE
        )
        cache.set(_cache_key(student_id, item), value, _CACHE_SECONDS)
        if value != LEAVE:
            chosen[item.subject] = value
    return chosen
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_verbs.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/cv_verbs.py config/settings/base.py tests/documents/test_cv_verbs.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): Jev picks a capped opening for each flagged bullet, cached and limited" -- apps/documents/cv_verbs.py config/settings/base.py tests/documents/test_cv_verbs.py
```

---

### Task 6: Verb fixes run in generation

**Files:**
- Modify: `apps/documents/cv_verbs.py` (append `verb_fixes`)
- Modify: `apps/documents/generation.py` (`_quality_fixes`)
- Test: `tests/documents/test_cv_verbs.py`, `tests/documents/test_generation.py`

**Interfaces:**
- Consumes: `flagged_bullets`, `choose_openers`, `compose`, `without_first_person`, `is_english` (Tasks 4–5); `AppliedFix`, `subject_of`, `VERB_OPENER` (Task 3).
- Produces: `cv_verbs.verb_fixes(content: CVContent, *, student_id: UUID, undone: frozenset[str], client: Client | None = None) -> tuple[CVContent, tuple[AppliedFix, ...]]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_cv_verbs.py`:

```python
from apps.documents.cv_fixes import VERB_OPENER, subject_of
from apps.documents.cv_verbs import verb_fixes

_NOUN = "A framework for the visualisation of chemical space."
_LINES = ("Wrote the evaluation scripts for the group.", _NOUN,
          "I trained the models on the cluster.")


def test_verb_fixes_change_only_the_opening(gate_on):
    content, fixes = verb_fixes(_cv(_LINES), student_id=uuid4(), undone=frozenset(),
                                client=_jev("built"))
    assert content.experience[0].bullets == (
        "Wrote the evaluation scripts for the group.",
        "Built a framework for the visualisation of chemical space.",
        "Trained the models on the cluster.",
    )
    assert [(f.where, f.original) for f in fixes] == [
        ("experience[0].bullets[1]", _NOUN),
        ("experience[0].bullets[2]", "I trained the models on the cluster."),
    ]


def test_an_undone_verb_fix_prints_the_original(gate_on):
    undone = frozenset({subject_of(VERB_OPENER, _NOUN)})
    content, fixes = verb_fixes(_cv(_LINES), student_id=uuid4(), undone=undone,
                                client=_jev("built"))
    assert content.experience[0].bullets[1] == _NOUN
    assert fixes[0].undone is True


def test_the_i_fix_runs_with_the_gate_off(settings):
    settings.CV_VERB_JEV_ENABLED = False
    content, fixes = verb_fixes(_cv(_LINES), student_id=uuid4(), undone=frozenset())
    assert content.experience[0].bullets[1] == _NOUN
    assert content.experience[0].bullets[2] == "Trained the models on the cluster."
```

Append to `tests/documents/test_generation.py`:

```python
def test_generation_records_a_verb_fix(agency_a, django_user_model, settings):
    from datetime import date as _date

    from apps.documents.schemas import ExperienceEntry
    from apps.research.decisions import Answer

    settings.CV_VERB_JEV_ENABLED = True
    settings.DECISIONS_PROVIDER = {"default": "typesafe"}

    def jev(state, questions, *, model, provider):
        return {q: Answer(id=q, value="built", confidence=0.97, probabilities={"built": 0.97},
                          model=model, provider=provider) for q in questions}

    post = ExperienceEntry(
        employer="EPFL", title="Research Intern", start_date=_date(2025, 6, 1),
        end_date=_date(2025, 9, 1),
        bullets=("Wrote the scripts for the group.", "A pipeline for the lab and the team."),
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g-verb")
        _fact(student, confirmed=True)
        VerifiedFact.objects.create(
            student=student, category=VerifiedFact.Category.EXPERIENCE,
            payload=fact_payload(post, category=VerifiedFact.Category.EXPERIENCE),
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:test",
            confirmed_by=student, confirmed_at=timezone.now(), created_by=student,
        )
        content = _content().model_copy(update={"experience": (post,)})
        result = generate_cv(student=student, client=_mock_client(content), decisions_client=jev)
    assert result.content.experience[0].bullets[1] == "Built a pipeline for the lab and the team."
    assert result.applied_fixes[-1].original == "A pipeline for the lab and the team."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_verbs.py tests/documents/test_generation.py -q -k "verb_fix or i_fix or records_a_verb"`
Expected: FAIL with `ImportError: cannot import name 'verb_fixes'`.

- [ ] **Step 3: Append `verb_fixes` to `apps/documents/cv_verbs.py`**

Add `AppliedFix` to the import from `.cv_fixes`:

```python
def verb_fixes(
    content: CVContent,
    *,
    student_id: UUID,
    undone: frozenset[str],
    client: Client | None = None,
) -> tuple[CVContent, tuple[AppliedFix, ...]]:
    """Apply §5.1 to every experience bullet. 'I <verb>' is fixed by code; a
    flagged line gets Jev's opening when Jev chose one; every other line is
    untouched. An undone fix is listed and not applied."""
    if not is_english(content):
        return content, ()
    items = flagged_bullets(content)
    chosen = choose_openers(items, student_id=student_id, client=client)
    by_text = {item.text: item for item in items}
    experience, fixes = [], []
    for i, entry in enumerate(content.experience):
        bullets: list[str] = []
        for j, bullet in enumerate(entry.bullets):
            new = without_first_person(bullet)
            item = by_text.get(bullet)
            if new is None and item is not None and item.subject in chosen:
                new = compose(bullet, chosen[item.subject], present=entry.end_date is None)
            if new is None or new == bullet:
                bullets.append(bullet)
                continue
            subject = subject_of(VERB_OPENER, bullet)
            was_undone = subject in undone
            fixes.append(AppliedFix(VERB_OPENER, subject, f"experience[{i}].bullets[{j}]",
                                    bullet, new, undone=was_undone))
            bullets.append(bullet if was_undone else new)
        experience.append(entry.model_copy(update={"bullets": tuple(bullets)}))
    return content.model_copy(update={"experience": tuple(experience)}), tuple(fixes)
```

- [ ] **Step 4: Call it from `_quality_fixes`** (`apps/documents/generation.py`)

Add `from .cv_verbs import verb_fixes`. Replace the body's last line `return content, soft` with:

```python
    content, verbs = verb_fixes(
        content, student_id=student.id, undone=undone, client=decisions_client
    )
    return content, (*soft, *verbs)
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents -q`
Expected: PASS. With the gate off by default, only the "I" fix can change an existing test's output. If one pins an "I ..." bullet, update it and say so.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/cv_verbs.py apps/documents/generation.py tests/documents/test_cv_verbs.py tests/documents/test_generation.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): apply verb openers at generation and list each change" -- apps/documents/cv_verbs.py apps/documents/generation.py tests/documents/test_cv_verbs.py tests/documents/test_generation.py
```

---

### Task 7: The CV reader stops calling a thesis a job (§5.4, reader)

**Files:**
- Modify: `apps/documents/ingestion.py:356-361` (the experience-title sentence of the prompt)
- Modify: `tests/documents/test_render.py:313-334` (`test_a_research_position_in_experience_names_its_supervisor`)
- Test: `tests/documents/test_ingestion.py`

**Interfaces:**
- Produces: no new names. The prompt no longer offers "Master's Thesis" or "Summer Fellowship" as role examples, and it says a thesis is not a role.

- [ ] **Step 1: Write the failing test** (append to `tests/documents/test_ingestion.py`)

```python
def test_the_reader_is_not_taught_that_a_thesis_is_a_role(agency_a, django_user_model, fake_store):
    """S-037a: the old prompt gave "Master's Thesis" and "Summer Fellowship" as
    example roles, which taught the model to file a thesis as a job."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-thesis")
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        client = _openai_client()
        ingest_uploaded_cv(document=document, student=student, client=client, store=fake_store)
        prompt = "".join(
            str(message["content"])
            for call in client.responses.parse.call_args_list
            for message in call.kwargs["input"]
        )
    assert "\"Master's Thesis\"" not in prompt
    assert "\"Summer Fellowship\"" not in prompt
    assert "A thesis or dissertation is not a role" in prompt
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_ingestion.py -q -k thesis_is_a_role`
Expected: FAIL on the first assert.

- [ ] **Step 3: Change the prompt** (`apps/documents/ingestion.py`)

Replace:

```python
                        "An experience entry's title is the role alone -- \"Research "
                        "Intern\", \"Master's Thesis\", \"Summer Fellowship\" -- never the "
                        "project. When DATA names the project or thesis that role worked "
```

with:

```python
                        "An experience entry's title is the role alone -- \"Research "
                        "Intern\", \"Teaching Assistant\", \"Laboratory Technician\" -- never "
                        "the project. "
                        # S-037a: a thesis printed as a job was taught by the old
                        # examples. The reader may still not invent a role, so a
                        # CV that heads an entry "Master's Thesis" keeps that
                        # title; generation places the thesis under the degree.
                        "A thesis or dissertation is not a role: when DATA lists thesis "
                        "work as an entry of its own, keep the entry and copy the title DATA "
                        "prints for it, and also fill that degree's thesis_title and "
                        "supervisor when DATA makes clear which degree it was written for. "
                        "When DATA names the project or thesis that role worked "
```

- [ ] **Step 4: Update the render fixture** (`tests/documents/test_render.py`, `test_a_research_position_in_experience_names_its_supervisor`)

Change `title="Master's Thesis",` to `title="Research Intern",`, and the final `assert "Master's Thesis" in text` to `assert "Research Intern" in text`. Keep the comment above it, but replace "Master's Thesis" in it with "Research Intern". The behaviour it checks (supervisor line, employer on its own line) is unchanged; only the role is now a real role.

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_ingestion.py tests/documents/test_render.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/ingestion.py tests/documents/test_ingestion.py tests/documents/test_render.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "fix(cv): stop teaching the CV reader that a thesis is a job title" -- apps/documents/ingestion.py tests/documents/test_ingestion.py tests/documents/test_render.py
```

---

### Task 8: The thesis prints under its degree, once (§5.4, placement)

**Files:**
- Modify: `apps/documents/cv_fixes.py` (append `is_thesis_title`, `place_theses`)
- Modify: `apps/documents/generation.py` (`_quality_fixes`)
- Modify: `apps/documents/render.py` (new `thesis_printed_once`; first line of `_render_pdf`)
- Modify: `apps/documents/schemas.py:306` (the comment "Duplicating ResearchEntry.thesis_title is the point")
- Test: `tests/documents/test_cv_fixes.py`, `tests/documents/test_render.py`

**Interfaces:**
- Consumes: `AppliedFix`, `subject_of`, `fold`, `THESIS_PLACEMENT` (Task 3).
- Produces:
  - `cv_fixes.is_thesis_title(title: str) -> bool`.
  - `cv_fixes.place_theses(content: CVContent, undone: frozenset[str]) -> tuple[CVContent, tuple[AppliedFix, ...]]`.
  - `render.thesis_printed_once(content: CVContent) -> CVContent`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_cv_fixes.py`:

```python
from apps.documents.cv_fixes import THESIS_PLACEMENT, is_thesis_title, place_theses


@pytest.mark.parametrize(
    "title, thesis",
    [
        ("Master’s Thesis", True), ("Master Thesis", True), ("MSc Thesis", True),
        ("Bachelor's thesis work", True), ("Thesis", True), ("Final Year Project", True),
        ("Master's thesis student", False), ("Thesis Supervisor", False),
        ("Research Intern", False),
    ],
)
def test_is_thesis_title(title, thesis):
    assert is_thesis_title(title) is thesis


def _thesis_post(**over):
    fields = dict(employer="University of Strasbourg", title="Master's Thesis",
                  project="AZIMUTH: a map of chemical space", supervisor="Prof. Varnek",
                  start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))
    fields.update(over)
    return _post(**fields)


def test_the_thesis_is_copied_under_its_degree_and_the_post_stays():
    content, [fix] = place_theses(_cv(experience=(_thesis_post(),)), frozenset())
    degree = content.education[0]
    assert (degree.thesis_title, degree.supervisor) == ("AZIMUTH: a map of chemical space",
                                                       "Prof. Varnek")
    assert content.experience[0].title == "Master's Thesis"
    assert fix.fix == THESIS_PLACEMENT and fix.where == "education[0]"


def test_a_degree_naming_another_thesis_is_left_alone():
    cv = _cv(experience=(_thesis_post(),))
    cv = cv.model_copy(update={"education": (cv.education[0].model_copy(
        update={"thesis_title": "Something else", "supervisor": "Dr. X"}),)})
    content, fixes = place_theses(cv, frozenset())
    assert content.education[0].thesis_title == "Something else" and fixes == ()


def test_two_candidate_degrees_place_nothing():
    cv = _cv(experience=(_thesis_post(),))
    other = cv.education[0].model_copy(update={"institution_original": "ETH Zurich"})
    content, fixes = place_theses(
        cv.model_copy(update={"education": (*cv.education, other)}).model_copy(
            update={"experience": (_thesis_post(employer="Elsewhere"),)}),
        frozenset(),
    )
    assert fixes == ()
```

Append to `tests/documents/test_render.py`. It already has `_content`, `_text`, `render_cv`, `EducationEntry` and `ResearchEntry` imported; add any that are missing to its imports:

```python
def test_a_thesis_with_its_own_research_entry_prints_its_title_once():
    content = _content(
        education=(EducationEntry(
            degree_as_awarded="MSc Chemoinformatics", institution_original="University of Strasbourg",
            start_date=date(2024, 9, 1), end_date=date(2026, 6, 30),
            thesis_title="AZIMUTH", supervisor="Prof. Varnek",
        ),),
        research=(ResearchEntry(thesis_title="AZIMUTH", supervisor="Prof. Varnek",
                                methods="Generative topographic mapping."),),
    )
    text = _text(render_cv(content, variant="STANDARD"))
    assert text.count("AZIMUTH") == 1
    assert "Thesis research" in text
    assert text.count("Prof. Varnek") == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fixes.py tests/documents/test_render.py -q -k "thesis"`
Expected: FAIL with `ImportError: cannot import name 'THESIS_PLACEMENT'`, and the render test counting "AZIMUTH" twice.

- [ ] **Step 3: Append placement to `apps/documents/cv_fixes.py`**

```python
#: section-2-refined.md §6's English pattern, matched on the folded title
#: without closing punctuation. "Master's thesis student" and "Thesis
#: Supervisor" are roles and do not match, which is the point.
_THESIS_TITLE = re.compile(
    r"^(?:(?:m\.?\s?sc\.?|b\.?\s?sc\.?|master'?s?|bachelor'?s?|diploma|honou?rs|graduation|"
    r"final[- ]year|capstone|undergraduate|graduate|degree)\s+)*"
    r"(?:thesis|dissertation|final year project|graduation project|capstone project)"
    r"(?:\s+(?:work|project|research))?$"
)


def is_thesis_title(title: str) -> bool:
    return bool(_THESIS_TITLE.match(fold(title).rstrip(".:;")))


def _thesis_degree(content: CVContent, post: ExperienceEntry) -> int | None:
    """The one degree this thesis was written for: its dates hold the post's
    start, and among those one at the post's employer. None unless exactly one."""
    if post.start_date is None:
        return None
    start = post.start_date
    holding = [
        index for index, degree in enumerate(content.education)
        if degree.start_date is not None and degree.start_date <= start
        and (degree.end_date is None or start <= degree.end_date)
    ]
    employer = fold(post.employer)
    same_place = [
        index for index in holding
        if employer in fold(content.education[index].institution_original)
        or fold(content.education[index].institution_original) in employer
    ]
    pick = same_place or holding
    return pick[0] if len(pick) == 1 else None


def place_theses(
    content: CVContent, undone: frozenset[str]
) -> tuple[CVContent, tuple[AppliedFix, ...]]:
    """Spec §5.4 (S-037a, S-040): a thesis filed as a job prints its title and
    supervisor under the degree. The post stays -- Education entries cannot hold
    bullets -- and a degree that already names a thesis or supervisor is left
    alone. The student's own strings move between two of their own entries."""
    education = list(content.education)
    fixes: list[AppliedFix] = []
    for post in content.experience:
        if not is_thesis_title(post.title):
            continue
        index = _thesis_degree(content, post)
        if index is None:
            continue
        degree = education[index]
        update: dict[str, str] = {}
        if post.project and not degree.thesis_title:
            update["thesis_title"] = post.project
        if post.supervisor and not degree.supervisor:
            update["supervisor"] = post.supervisor
        if not update:
            continue
        subject = subject_of(THESIS_PLACEMENT, f"{post.employer}\x00{post.title}")
        was_undone = subject in undone
        changed = "; ".join(
            f"{'Thesis' if key == 'thesis_title' else 'Supervisor'}: {value}"
            for key, value in update.items()
        )
        fixes.append(AppliedFix(THESIS_PLACEMENT, subject, f"education[{index}]",
                                f"{post.title}, {post.employer}", changed, undone=was_undone))
        if not was_undone:
            education[index] = degree.model_copy(update=update)
    return content.model_copy(update={"education": tuple(education)}), tuple(fixes)
```

Add `ExperienceEntry` to the `.schemas` import.

- [ ] **Step 4: Call it from `_quality_fixes`** (`apps/documents/generation.py`)

Import `place_theses`. After the `drop_soft_skills` line add `content, theses = place_theses(content, undone)`, and return `(*soft, *theses, *verbs)`.

- [ ] **Step 5: Print once** (`apps/documents/render.py`)

Add after `without_duplicated_posts`:

```python
def thesis_printed_once(content: CVContent) -> CVContent:
    """Spec §5.4: a Research entry describing the thesis a degree already names
    is headed "Thesis research", and its own supervisor line goes, so the title
    and supervisor print once, under the degree. Only for the cv_base.html
    paths, which print the thesis under the degree. The Europass API sends no
    thesis per degree, so there the Research entry stays the only place it is
    named."""
    theses = {
        normalize_text(d.thesis_title).casefold() for d in content.education if d.thesis_title
    }
    return content.model_copy(
        update={
            "research": tuple(
                entry.model_copy(update={"thesis_title": "Thesis research", "supervisor": None})
                if normalize_text(entry.thesis_title).casefold() in theses
                else entry
                for entry in content.research
            )
        }
    )
```

Import `normalize_text` from `.hygiene` if render.py does not already. Make `content = thesis_printed_once(content)` the first statement of `_render_pdf`'s body, above `template = ...`. Leave Stage 1's parameters as they are.

In `apps/documents/schemas.py` near line 306, replace the comment sentence "Duplicating ResearchEntry.thesis_title is the point" with: "It may equal a ResearchEntry's thesis_title; the cv_base.html render then prints the title once, under the degree (render.thesis_printed_once, CV design 2026-10-12 §5.4)."

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fixes.py tests/documents/test_render.py tests/documents/test_academic_track.py tests/documents/test_generation.py -q`
Expected: PASS. If `test_academic_track.py` asserts the thesis title appears in both the Education and Research sections, it pinned the duplication §5.4 removes. Change it to one occurrence plus "Thesis research", and say so in the test.

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/cv_fixes.py apps/documents/generation.py apps/documents/render.py apps/documents/schemas.py tests/documents/test_cv_fixes.py tests/documents/test_render.py tests/documents/test_academic_track.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): print a thesis filed as a job under its degree, once" -- apps/documents/cv_fixes.py apps/documents/generation.py apps/documents/render.py apps/documents/schemas.py tests/documents/test_cv_fixes.py tests/documents/test_render.py tests/documents/test_academic_track.py
```

---

### Task 9: Abbreviated titles are never guessed (§5.3, generation)

**Files:**
- Modify: `apps/documents/cv_fixes.py` (append detectors, `full_title_for`, `full_titles`)
- Modify: `apps/documents/generation.py` (`_quality_fixes`)
- Test: `tests/documents/test_cv_fixes.py`

**Interfaces:**
- Consumes: `verification.verify_against_facts`, `verification.Verdict`.
- Produces:
  - `cv_fixes.cut_stems(text: str) -> list[str]`.
  - `cv_fixes.abbreviated_degree(text: str) -> bool`.
  - `cv_fixes.abbreviated_institution(text: str) -> bool`.
  - `cv_fixes.TITLE_MAX = {"degree_as_awarded": 200, "institution_original": 300}`.
  - `cv_fixes.full_title_for(degree: str, institution: str, end_year: int | None, facts: Sequence[VerifiedFact]) -> str | None`.
  - `cv_fixes.full_titles(content, facts, undone) -> tuple[CVContent, tuple[AppliedFix, ...]]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/documents/test_cv_fixes.py`)

```python
from apps.documents.cv_fixes import (
    FULL_TITLE,
    abbreviated_degree,
    abbreviated_institution,
    full_title_for,
    full_titles,
)


@pytest.mark.parametrize(
    "degree, flagged",
    [
        ("B.Sc. of Chem. Eng.", True), ("BSc", True), ("Bakalavr", True),
        ("Lisans, Kimya Müh.", True), ("Бакалавр, прикл. математика", True),
        ("MSc. of Complex Systems Chemistry (CSC)", False), ("M.Sc. Informatik", False),
        ("Dipl.-Ing. Maschinenbau", False), ("Licence Génie Chimique", False),
        ("Ph.D. in Chemoinformatics", False),
    ],
)
def test_abbreviated_degree(degree, flagged):
    assert abbreviated_degree(degree) is flagged


@pytest.mark.parametrize(
    "institution, flagged",
    [
        ("UFAZ", True), ("İTÜ", True), ("ODTÜ (METU)", True), ("Univ. of Strasbourg", True),
        ("ADA University", False), ("ETH Zurich", False), ("St. Petersburg State University", False),
        ("J. W. Goethe-Universität", False),
    ],
)
def test_abbreviated_institution(institution, flagged):
    assert abbreviated_institution(institution) is flagged


def _diploma(student, title, *, institution="UFAZ", end="2023-06-30"):
    return _fact(student, EDU, {"degree_as_awarded": title, "institution_original": institution,
                                "end_date": end},
                 tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT)


def test_the_full_title_comes_only_from_a_matching_document(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "full")
        right = _diploma(student, "Bachelor of Science in Chemical Engineering")
        wrong_place = _diploma(student, "Bachelor of Chemistry and English", institution="BDU")
        facts = [right, wrong_place]
    assert full_title_for("B.Sc. of Chem. Eng.", "UFAZ", 2023, facts) == (
        "Bachelor of Science in Chemical Engineering")
    assert full_title_for("B.Sc. of Chem. Eng.", "UFAZ", 2021, facts) is None
    assert full_title_for("B.Sc. of Mech. Eng.", "UFAZ", 2023, facts) is None


def test_two_matching_documents_choose_nothing(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "full2")
        facts = [_diploma(student, "Bachelor of Chemical Engineering"),
                 _diploma(student, "Bachelor of Chemistry Engineering")]
    assert full_title_for("B.Sc. of Chem. Eng.", "UFAZ", 2023, facts) is None


def test_an_overlong_document_title_is_refused(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "full3")
        facts = [_diploma(student, "Bachelor of Chemical Engineering " + "x" * 200)]
    assert full_title_for("B.Sc. of Chem. Eng.", "UFAZ", 2023, facts) is None


def test_full_titles_replace_and_list_the_change(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "full4")
        diploma = _diploma(student, "Bachelor of Science in Chemical Engineering")
        abbreviated = EducationEntry(degree_as_awarded="B.Sc. of Chem. Eng.",
                                     institution_original="UFAZ", end_date=date(2023, 6, 30))
        content, [fix] = full_titles(_cv(education=(abbreviated,)), [diploma], frozenset())
    assert content.education[0].degree_as_awarded == "Bachelor of Science in Chemical Engineering"
    assert (fix.fix, fix.original) == (FULL_TITLE, "B.Sc. of Chem. Eng.")


def test_no_document_prints_the_title_as_written():
    abbreviated = EducationEntry(degree_as_awarded="B.Sc. of Chem. Eng.",
                                 institution_original="UFAZ", end_date=date(2023, 6, 30))
    content, fixes = full_titles(_cv(education=(abbreviated,)), [], frozenset())
    assert content.education[0].degree_as_awarded == "B.Sc. of Chem. Eng." and fixes == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fixes.py -q -k "abbreviated or full"`
Expected: FAIL with `ImportError: cannot import name 'FULL_TITLE'` (or `abbreviated_degree`).

- [ ] **Step 3: Append to `apps/documents/cv_fixes.py`**

Import `Verdict` and `verify_against_facts` from `.verification`, and `EducationEntry` from `.schemas`:

```python
#: Degree marks removed before looking for a cut-off word, so "B.Sc." alone is
#: never flagged (section-2-refined.md §5). "Mt" joins them ("Mt. Holyoke").
_DEGREE_MARKS = re.compile(
    r"(?<![^\W\d_])(?:b\.?\s?sc|m\.?\s?sc|b\.?\s?a|m\.?\s?a|b\.?\s?eng|m\.?\s?eng|ph\.?\s?d|"
    r"ll\.?\s?b|ll\.?\s?m|m\.?\s?phil|m\.?\s?res|b\.?\s?tech|m\.?\s?tech|dipl\.?-ing|mba|dr|"
    r"st|prof|mt)\.?(?![^\W\d_])",
    re.IGNORECASE,
)
#: Two or more letters then a full stop: a cut-off word. One letter is an initial.
_CUT_WORD = re.compile(r"(?<![^\W\d_])([^\W\d_]{2,})\.(?=\s|,|\)|$)")
_LETTERS = re.compile(r"[^\W\d_]+")
#: The CV's line budget for a title is the schema's own limit (schemas.py).
TITLE_MAX = {"degree_as_awarded": 200, "institution_original": 300}


def cut_stems(text: str) -> list[str]:
    return [m.group(1).casefold() for m in _CUT_WORD.finditer(_DEGREE_MARKS.sub(" ", text))]


def abbreviated_degree(text: str) -> bool:
    """A cut-off word ("Chem."), nothing left beside the degree mark ("BSc"),
    or a one-word title ("Bakalavr")."""
    rest = _LETTERS.findall(_DEGREE_MARKS.sub(" ", text))
    return bool(cut_stems(text)) or not rest or len(_LETTERS.findall(text)) == 1


def abbreviated_institution(text: str) -> bool:
    """A cut-off word, or no word with three lower-case letters ("UFAZ", "İTÜ")."""
    if cut_stems(text):
        return True
    return not any(sum(c.islower() for c in word) >= 3 for word in _LETTERS.findall(text))


def _stems_in_order(stems: list[str], words: list[str]) -> bool:
    position = 0
    for stem in stems:
        while position < len(words) and not words[position].startswith(stem):
            position += 1
        if position == len(words):
            return False
        position += 1
    return True


def full_title_for(
    degree: str, institution: str, end_year: int | None, facts: Sequence[VerifiedFact]
) -> str | None:
    """Spec §5.3: the full title, only from a document the platform read.

    An AUTHORITATIVE_DOCUMENT education fact qualifies when it is at the same
    institution, ends in the same year (when both state one), is itself not
    abbreviated, fits the line budget, and every cut-off word of the CV's
    title starts a word of it, in order. Exactly one must qualify -- "Chem.
    Eng." could be several titles, and the engine never picks one.
    """
    stems = cut_stems(degree)
    found: list[str] = []
    for fact in facts:
        if (
            fact.category != VerifiedFact.Category.EDUCATION
            or fact.source_tier != VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
        ):
            continue
        payload = _payload(fact)
        full = str(payload.get("degree_as_awarded") or "")
        if not full or len(full) > TITLE_MAX["degree_as_awarded"] or abbreviated_degree(full):
            continue
        if fold(str(payload.get("institution_original") or "")) != fold(institution):
            continue
        year = str(payload.get("end_date") or "")[:4]
        if end_year is not None and year.isdigit() and int(year) != end_year:
            continue
        if _stems_in_order(stems, [w.casefold() for w in _LETTERS.findall(full)]):
            found.append(full)
    return found[0] if len(found) == 1 else None


def full_titles(
    content: CVContent, facts: Sequence[VerifiedFact], undone: frozenset[str]
) -> tuple[CVContent, tuple[AppliedFix, ...]]:
    """Replace an abbreviated degree title with the document's, and keep the
    replacement only when the verifier still reads that entry SUPPORTED or
    UNCERTAIN against `facts` (the verification set). Otherwise the title
    prints as written and the gap question (gaps.abbreviated_names) asks."""
    education = list(content.education)
    fixes: list[AppliedFix] = []
    for index, entry in enumerate(content.education):
        if not abbreviated_degree(entry.degree_as_awarded):
            continue
        end_year = entry.end_date.year if entry.end_date else None
        full = full_title_for(entry.degree_as_awarded, entry.institution_original, end_year, facts)
        if full is None:
            continue
        subject = subject_of(FULL_TITLE, entry.degree_as_awarded)
        was_undone = subject in undone
        if not was_undone:
            trial = [*education]
            trial[index] = entry.model_copy(update={"degree_as_awarded": full})
            verdicts = verify_against_facts(
                content.model_copy(update={"education": tuple(trial)}), facts
            )
            verdict = next(v.verdict for v in verdicts if v.claim_path == f"education[{index}]")
            if verdict not in (Verdict.SUPPORTED, Verdict.UNCERTAIN):
                continue
            education = trial
        fixes.append(AppliedFix(FULL_TITLE, subject, f"education[{index}]",
                                entry.degree_as_awarded, full, undone=was_undone))
    return content.model_copy(update={"education": tuple(education)}), tuple(fixes)
```

- [ ] **Step 4: Call it from `_quality_fixes`**

Import `full_titles`. After `place_theses`, add `content, titles = full_titles(content, verification_facts, undone)`, and return `(*soft, *theses, *titles, *verbs)`.

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fixes.py tests/documents/test_generation.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/cv_fixes.py apps/documents/generation.py tests/documents/test_cv_fixes.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): take a full degree title only from a document the platform read" -- apps/documents/cv_fixes.py apps/documents/generation.py tests/documents/test_cv_fixes.py
```

---

### Task 10: The gap question for an abbreviated name, and its length guard (§5.3, questions)

**Files:**
- Modify: `apps/documents/gaps.py` (`Kind.ABBREVIATED_NAME`; new detector `abbreviated_names`; `gap_questions` order; `answer_questions` guard)
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Consumes: `abbreviated_degree`, `abbreviated_institution`, `full_title_for`, `TITLE_MAX`, `subject_of`, `reverted_subjects`, `remember_revert`, `ABBREVIATED_NAME` (Tasks 2, 9).
- Produces:
  - `gaps.Kind.ABBREVIATED_NAME`.
  - `gaps.abbreviated_names(student: Membership) -> tuple[GapQuestion, ...]`.
  - It sits in `gap_questions` directly after `missing_degree_detail`.

- [ ] **Step 1: Write the failing tests** (append to `tests/documents/test_gaps.py`)

```python
from apps.documents.gaps import Kind, UnanswerableQuestion, abbreviated_names, answer_questions


def _degree_fact(student, degree="B.Sc. of Chem. Eng.", institution="UFAZ"):
    from django.utils import timezone

    return VerifiedFact.objects.create(
        student=student, category=VerifiedFact.Category.EDUCATION,
        payload={"degree_as_awarded": degree, "institution_original": institution,
                 "end_date": "2023-06-30"},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:test",
        confirmed_by=student, confirmed_at=timezone.now(), created_by=student,
    )


def test_an_abbreviated_degree_and_institution_are_asked_for_in_full(
    agency_a, membership_a
):
    with tenant_scope(agency_a.id):
        _degree_fact(membership_a)
        questions = abbreviated_names(membership_a)
    assert [(q.kind, q.payload_key) for q in questions] == [
        (Kind.ABBREVIATED_NAME, "degree_as_awarded"),
        (Kind.ABBREVIATED_NAME, "institution_original"),
    ]


def test_a_full_name_is_not_asked(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _degree_fact(membership_a, "Bachelor of Chemical Engineering", "ADA University")
        assert abbreviated_names(membership_a) == ()


def test_a_name_retyped_unchanged_is_remembered_and_not_asked_again(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        fact = _degree_fact(membership_a, "Bachelor of Chemical Engineering", "UFAZ")
        [question] = abbreviated_names(membership_a)
        assert answer_questions([(question, "UFAZ")], student=membership_a) == ()
        assert abbreviated_names(membership_a) == ()
        assert not VerifiedFact.objects.filter(supersedes=fact).exists()


def test_an_overlong_full_title_is_refused_before_it_is_stored(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _degree_fact(membership_a)
        question = abbreviated_names(membership_a)[0]
        with pytest.raises(UnanswerableQuestion):
            answer_questions([(question, "B" * 201)], student=membership_a)


def test_the_question_sits_after_the_degree_detail_questions(agency_a, membership_a):
    from apps.documents.gaps import gap_questions

    with tenant_scope(agency_a.id):
        _degree_fact(membership_a)
        kinds = [q.kind for q in gap_questions(membership_a)]
    assert kinds.index(Kind.ABBREVIATED_NAME) > kinds.index(Kind.MISSING_DEGREE_DETAIL)
```

If `tests/documents/test_gaps.py` lacks `VerifiedFact`, `tenant_scope` or `pytest` imports, add them.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_gaps.py -q -k "abbreviated or retyped or overlong_full or after_the_degree"`
Expected: FAIL with `ImportError: cannot import name 'abbreviated_names'`.

- [ ] **Step 3: Implement in `apps/documents/gaps.py`**

Add to `Kind`, after `MISSING_DEGREE_DETAIL`:

```python
    #: A degree title or institution written short ("B.Sc. of Chem. Eng.",
    #: "UFAZ"), asked for as the diploma prints it. The engine never expands a
    #: short form itself (R-034, R-061, S-029; CV design 2026-10-12 §5.3).
    ABBREVIATED_NAME = "ABBREVIATED_NAME"
```

Import the helpers: `from .cv_fixes import ABBREVIATED_NAME, TITLE_MAX, abbreviated_degree, abbreviated_institution, full_title_for, remember_revert, reverted_subjects, subject_of`.

Add the detector after `missing_degree_detail`:

```python
def abbreviated_names(student: Membership) -> tuple[GapQuestion, ...]:
    """CV design §5.3: ask for a short degree title or institution in full.

    Not asked when a document the platform read already supplies the full
    degree title (generation takes it from there), nor for a value the student
    already retyped unchanged -- that is their diploma's own wording and is
    remembered as such (cv_fixes.ABBREVIATED_NAME).
    """
    facts = _current(student, VerifiedFact.Category.EDUCATION)
    as_printed = reverted_subjects(student, ABBREVIATED_NAME)
    questions: list[GapQuestion] = []
    for fact in facts:
        if fact.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT:
            continue
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        degree = str(payload.get("degree_as_awarded") or "")
        institution = str(payload.get("institution_original") or "")
        year = str(payload.get("end_date") or "")[:4]
        if (
            degree
            and abbreviated_degree(degree)
            and subject_of(ABBREVIATED_NAME, degree) not in as_printed
            and full_title_for(degree, institution, int(year) if year.isdigit() else None,
                               facts) is None
        ):
            questions.append(GapQuestion(
                kind=Kind.ABBREVIATED_NAME, fact_id=fact.id, payload_key="degree_as_awarded",
                prompt=("Write this degree in full, exactly as your diploma states it. "
                        "If your diploma writes it exactly like this, type it again unchanged."),
                evidence=f"Your CV writes it as “{degree}”.",
            ))
        if (
            institution
            and abbreviated_institution(institution)
            and subject_of(ABBREVIATED_NAME, institution) not in as_printed
        ):
            questions.append(GapQuestion(
                kind=Kind.ABBREVIATED_NAME, fact_id=fact.id, payload_key="institution_original",
                prompt=("Write your university's name in full, exactly as your diploma states "
                        "it. If your diploma writes it exactly like this, type it again "
                        "unchanged."),
                evidence=f"Your CV writes it as “{institution}”.",
            ))
    return tuple(questions)
```

In `gap_questions`, change `+ missing_degree_detail(student)` to `+ missing_degree_detail(student)` followed by a new line `+ abbreviated_names(student)`.

In `answer_questions`, inside the `for question, answer in answers:` loop, directly before `if question.payload_key in _NAME_PART_KEYS and ...`, add:

```python
        if question.kind == Kind.ABBREVIATED_NAME:
            limit = TITLE_MAX[question.payload_key]
            if len(value) > limit:
                # No input in the message: it is the student's own data.
                raise UnanswerableQuestion(f"keep it to {limit} characters")
            current = unsuperseded_facts(student).filter(id=question.fact_id).first()
            stated = current.payload.get(question.payload_key) if current and isinstance(
                current.payload, dict) else None
            if stated == value:
                # Retyped unchanged: the diploma prints it so. Remembered, not
                # written, so the question stops instead of re-asking forever.
                remember_revert(student, ABBREVIATED_NAME, subject_of(ABBREVIATED_NAME, value))
                continue
```

Update the module docstring's detector count ("Fourteen deterministic detectors" or similar) by one, and add a one-line entry for `abbreviated_names`.

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_gaps.py tests/documents/test_gap_intake.py tests/documents/test_gap_interview_view.py -q`
Expected: PASS. If `test_gap_interview_view.py` counts `<input type="text"` for a fixture whose degree is abbreviated ("BSc" in many fixtures), the count rises by the new questions. Update the count from the fixture's own facts and say why in the test.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/gaps.py tests/documents/test_gaps.py tests/documents/test_gap_interview_view.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): ask for an abbreviated degree or university in full, with a length guard" -- apps/documents/gaps.py tests/documents/test_gaps.py tests/documents/test_gap_interview_view.py
```

---

### Task 11: "What we changed" on the documents page, with undo (§5.5)

**Files:**
- Modify: `apps/documents/views.py` (`page_context`; new view `cv_fix_decision`)
- Modify: `apps/documents/urls.py`
- Modify: `templates/student/_documents.html` (new section after the "Your CV" section)
- Test: `tests/documents/test_documents_page.py`

**Interfaces:**
- Consumes: `remember_revert`, `forget_revert` (Task 2); `DocumentDraft.applied_fixes` (Task 2); `audit.record_event`.
- Produces:
  - The URL name `student-cv-fix` → `POST /student/documents/cv-fixes/`, with fields `subject` and `action` (`undo`, `redo` or, from Task 12, `keep`).
  - A `page_context` key `applied_fixes: list[dict]`, holding the newest CV draft's list.

- [ ] **Step 1: Write the failing tests** (append to `tests/documents/test_documents_page.py`)

```python
from apps.documents.models import CvFixRevert

FIXES = "/student/documents/cv-fixes/"
_FIX = {"fix": "soft_skill", "subject": "f" * 64, "where": "skills",
        "original": "Teamwork", "changed": "", "undone": False}


def _cv_draft(agency, student, fixes):
    return DocumentDraft.objects.create(
        tenant=agency, student=student, kind=DocumentDraft.Kind.CV, version=1, content={},
        status=DocumentDraft.Status.DRAFT, applied_fixes=fixes,
    )


def test_the_page_lists_what_we_changed(client, agency_a, domain_a, user_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        _cv_draft(agency_a, membership_a, [_FIX, {**_FIX, "fix": "verb_opener",
                  "subject": "a" * 64, "original": "A tool for the lab.",
                  "changed": "Built a tool for the lab."}])
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "What we changed" in body
    assert "Left out: Teamwork" in body
    assert "A tool for the lab. → Built a tool for the lab." in body


def test_undo_and_apply_again(client, agency_a, domain_a, user_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        _cv_draft(agency_a, membership_a, [_FIX])
    client.force_login(user_a)
    client.post(FIXES, {"subject": "f" * 64, "action": "undo"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert CvFixRevert.objects.filter(student=membership_a, subject="f" * 64).exists()
    client.post(FIXES, {"subject": "f" * 64, "action": "redo"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert not CvFixRevert.objects.filter(student=membership_a).exists()


def test_a_subject_the_latest_draft_does_not_list_is_404(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _cv_draft(agency_a, membership_a, [_FIX])
    client.force_login(user_a)
    response = client.post(FIXES, {"subject": "9" * 64, "action": "undo"},
                           HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_the_counselor_sees_the_list_without_buttons(agency_a, membership_a, rf) -> None:
    with tenant_scope(agency_a.id):
        _cv_draft(agency_a, membership_a, [_FIX])
        html = render_to_string("student/_documents.html",
                                page_context(membership_a, counselor_view=True),
                                request=rf.get("/"))
    assert "Left out: Teamwork" in html and FIXES not in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_documents_page.py -q -k "what_we_changed or undo or latest_draft or without_buttons"`
Expected: FAIL. The section is absent and the URL returns 404 for every POST.

- [ ] **Step 3: Implement the view and context** (`apps/documents/views.py`)

Imports: `from .audit import record_event` and `from .cv_fixes import forget_revert, remember_revert`.

In `page_context`, before the `return`:

```python
    latest_cv = (
        DocumentDraft.objects.filter(student=student, kind=DocumentDraft.Kind.CV)
        .order_by("-version")
        .first()
    )
```

Add `"applied_fixes": list(latest_cv.applied_fixes) if latest_cv else [],` to the returned dict.

Add the view:

```python
def _latest_fix(student: Membership, subject: str) -> tuple[DocumentDraft, dict]:
    """The fix named by `subject` on the student's newest CV draft, or 404.
    The fix's kind and text come from the stored list, never from the form."""
    draft = (
        DocumentDraft.objects.filter(student=student, kind=DocumentDraft.Kind.CV)
        .order_by("-version")
        .first()
    )
    if draft is None:
        raise Http404
    for fix in draft.applied_fixes:
        if isinstance(fix, dict) and fix.get("subject") == subject:
            return draft, fix
    raise Http404


@login_required
@require_POST
def cv_fix_decision(request: HttpRequest) -> HttpResponse:
    """Spec §5.5: the student undoes an automatic fix, or applies it again.

    Takes effect on the next CV the student writes; an existing draft or PDF
    is never altered. Student-only: current_membership refuses a counsellor,
    who sees the same list without buttons."""
    student = current_membership(request, Membership.Role.STUDENT)
    subject = request.POST.get("subject", "")
    action = request.POST.get("action", "")
    draft, fix = _latest_fix(student, subject)
    if action == "undo":
        remember_revert(student, str(fix["fix"]), subject)
    elif action == "redo":
        forget_revert(student, subject)
    else:
        raise Http404
    record_event(actor=student, event=f"document.cv_fix_{action}", object_id=draft.id)
    messages.success(request, "Saved. It shows on the next CV you write.")
    return redirect("student-documents")
```

In `apps/documents/urls.py`, add `path("student/documents/cv-fixes/", views.cv_fix_decision, name="student-cv-fix"),`.

- [ ] **Step 4: Add the section** (`templates/student/_documents.html`, directly after the closing `</section>` of `id="drafts"`)

```django
{% if applied_fixes %}
<section aria-labelledby="fixes-heading" id="cv-fixes">
  <h2 id="fixes-heading">What we changed</h2>
  <p>Changes show on the next CV you write.</p>
  <ul>
    {% for fix in applied_fixes %}
      <li>
        {% if fix.changed %}{{ fix.original }} → {{ fix.changed }}{% else %}Left out: {{ fix.original }}{% endif %}{% if fix.undone %} (undone){% endif %}
        {% if not counselor_view %}
          <form method="post" action="{% url 'student-cv-fix' %}">
            {% csrf_token %}
            <input type="hidden" name="subject" value="{{ fix.subject }}">
            {% if fix.undone %}<button type="submit" name="action" value="redo">Apply again</button>
            {% elif fix.changed %}<button type="submit" name="action" value="undo">Undo</button>
            {% else %}<button type="submit" name="action" value="undo">Put back</button>{% endif %}
          </form>
        {% endif %}
      </li>
    {% endfor %}
  </ul>
</section>
{% endif %}
```

Auto-escaping stays on: `original` is the student's own text, and the counsellor sees another person's text.

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_documents_page.py tests/dashboard -q`
Expected: PASS. `test_the_counselor_view_carries_no_student_only_action` still holds, because the form is inside `{% if not counselor_view %}`.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/views.py apps/documents/urls.py templates/student/_documents.html tests/documents/test_documents_page.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): show what we changed, with undo and put back" -- apps/documents/views.py apps/documents/urls.py templates/student/_documents.html tests/documents/test_documents_page.py
```

---

### Task 12: "Keep this wording": a verb fix becomes the student's own fact (§5.5)

**Files:**
- Modify: `apps/documents/cv_fixes.py` (append `keep_wording`)
- Modify: `apps/documents/views.py` (`cv_fix_decision` takes `action=keep`)
- Modify: `templates/student/_documents.html` (one button on verb fixes)
- Test: `tests/documents/test_cv_fixes.py`, `tests/documents/test_documents_page.py`

**Interfaces:**
- Consumes: `verification.generatable_facts`; `audit.record_event`; `VERB_OPENER`.
- Produces: `cv_fixes.keep_wording(*, student: Membership, original: str, changed: str) -> VerifiedFact | None`. It returns None when no single current confirmed experience fact holds `original`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_cv_fixes.py`:

```python
from apps.documents.cv_fixes import keep_wording
from apps.funding.models import AuditEvent


def test_keeping_a_verb_fix_writes_a_confirmed_superseding_fact(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "keep")
        post = _post(bullets=("A tool for the lab.", "Wrote the report."))
        fact = _fact(student, EXP, fact_payload(post, category=EXP))
        row = keep_wording(student=student, original="A tool for the lab.",
                           changed="Built a tool for the lab.")
        assert row is not None and row.supersedes_id == fact.id
        assert row.payload["bullets"] == ["Built a tool for the lab.", "Wrote the report."]
        assert row.confirmed_by_id == student.id and row.source_ref == "cv-fix:S-026"
        assert AuditEvent.objects.filter(event="fact.cv_fix_kept", object_id=row.id).exists()


def test_keeping_a_line_no_fact_holds_writes_nothing(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "keep-none")
        assert keep_wording(student=student, original="Gone.", changed="Built gone.") is None
```

Append to `tests/documents/test_documents_page.py`:

```python
def test_keep_this_wording_through_the_page(client, agency_a, domain_a, user_a, membership_a) -> None:
    from django.utils import timezone

    with tenant_scope(agency_a.id):
        fact = VerifiedFact.objects.create(
            student=membership_a, category=VerifiedFact.Category.EXPERIENCE,
            payload={"employer": "EPFL", "title": "Intern", "bullets": ["A tool for the lab."]},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:t",
            confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a,
        )
        _cv_draft(agency_a, membership_a, [{**_FIX, "fix": "verb_opener", "subject": "a" * 64,
                  "original": "A tool for the lab.", "changed": "Built a tool for the lab."}])
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert 'value="keep"' in body
    client.post(FIXES, {"subject": "a" * 64, "action": "keep"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.get(supersedes=fact).payload["bullets"] == [
            "Built a tool for the lab."]


def test_keep_is_refused_for_a_fix_that_is_not_wording(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _cv_draft(agency_a, membership_a, [_FIX])
    client.force_login(user_a)
    assert client.post(FIXES, {"subject": "f" * 64, "action": "keep"},
                       HTTP_HOST=domain_a.host).status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fixes.py tests/documents/test_documents_page.py -q -k "keep"`
Expected: FAIL with `ImportError: cannot import name 'keep_wording'`.

- [ ] **Step 3: Append `keep_wording` to `apps/documents/cv_fixes.py`**

Imports: `from django.db import transaction`, `from django.utils import timezone`, `from .audit import record_event`, and `generatable_facts` from `.verification`:

```python
@transaction.atomic
def keep_wording(*, student: Membership, original: str, changed: str) -> VerifiedFact | None:
    """Spec §5.5: the student's one tap makes a verb fix their own wording.

    A new EXPERIENCE fact supersedes the one current confirmed fact holding the
    line, with that line replaced (every occurrence of it) and every other
    bullet untouched; confirmed by the student, since the student tapped. The
    opening came from the fixed list and the rest is the student's line, so no
    model authored it. None when no single fact holds the line -- a stale page.
    The one-superseder index refuses a concurrent second tap.
    """
    owners = [
        fact
        for fact in generatable_facts(student).filter(category=_EXP)
        if original in (_payload(fact).get("bullets") or [])
    ]
    if len(owners) != 1:
        return None
    tip = owners[0]
    bullets = [changed if line == original else line for line in _payload(tip)["bullets"]]
    row = VerifiedFact.objects.create(
        student=student, category=_EXP, payload={**_payload(tip), "bullets": bullets},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="cv-fix:S-026",
        confirmed_by=student, confirmed_at=timezone.now(), supersedes=tip, created_by=student,
    )
    record_event(actor=student, event="fact.cv_fix_kept", object_id=row.id)
    return row
```

- [ ] **Step 4: Accept `keep` in the view, and add the button**

In `apps/documents/views.py::cv_fix_decision`, import `VERB_OPENER` and `keep_wording`, plus `IntegrityError` if Stage 2 did not already import it. Add a branch before `else: raise Http404`:

```python
    elif action == "keep" and fix.get("fix") == VERB_OPENER:
        try:
            kept = keep_wording(student=student, original=str(fix["original"]),
                                changed=str(fix["changed"]))
        except IntegrityError:
            kept = None
        if kept is None:
            messages.error(request, "That line has changed since this CV -- write it again.")
            return redirect("student-documents")
```

The success message and `record_event` below it then run for `keep` as well.

In the template, inside the `{% elif fix.changed %}` branch, after the Undo button:

```django
            {% if fix.fix == "verb_opener" %}<button type="submit" name="action" value="keep">Keep this wording</button>{% endif %}
```

- [ ] **Step 5: Full gates**

```bash
uv run ruff check .
uv run mypy apps config
POSTGRES_DB=elmify_cv_engine_design uv run pytest -q
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

Expected: every gate passes, and `makemigrations --check` reports "No changes detected".

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/cv_fixes.py apps/documents/views.py templates/student/_documents.html tests/documents/test_cv_fixes.py tests/documents/test_documents_page.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): one tap keeps a verb fix as the student's own wording" -- apps/documents/cv_fixes.py apps/documents/views.py templates/student/_documents.html tests/documents/test_cv_fixes.py tests/documents/test_documents_page.py
```

---

## Self-review

- **Spec coverage:**
  - §5.1: detection and composition (Task 4); Jev, cache, limiter and gate (Task 5); wiring (Task 6); English only (`is_english`); no inflation (`allowed_openers`); doubt keeps the line (`BAR`, `LEAVE`).
  - §5.2: Task 3. Headings are stamped from the ledger in Task 1.
  - §5.3: never guessed (Task 9's single-match rule); full title only from a document fact (Task 9); otherwise the gap question (Task 10); the line-budget guard (Tasks 9 and 10).
  - §5.4: placement (Task 8); reader prompt and `test_render.py:313` (Task 7); detection words (`is_thesis_title`); print once (Task 8).
  - §5.5: the list with originals (Tasks 3 and 11); counsellor read-only (Task 11); undo and put back (Tasks 2 and 11); one-tap fixes as confirmed superseding facts with an audit event (Task 12); `applied_fixes` REDACTED (Task 2).
  - §5.6: both stamps (Task 1).
  - §10, this stage's part: the put-back table with RLS, guards, redaction and deletion (Task 2); `applied_fixes` defaults to empty (Task 2). The relevance cache table and `render_warnings` are Stage 4.
- **Not covered, and why:** §3.2's opt-in (decision 13).
- **Placeholders.** None. Every test uses helpers that exist in its module today, or that an earlier task of this plan defines.
- **Type consistency:**
  - `AppliedFix(fix, subject, where, original, changed, undone)` has the same field order wherever it is constructed (Tasks 3, 6, 8, 9).
  - `subject_of(fix, text)`, `reverted_subjects(student, fix=None)` and `remember_revert(student, fix, subject)` keep the same signatures in Tasks 2, 3, 6, 8, 9, 10 and 11.
  - `_quality_fixes` returns `(*soft, *theses, *titles, *verbs)` after Task 9, in that order.
- **Review Focus.** Each line names the test that pins it in its owning task.
