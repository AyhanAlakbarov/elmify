# Transcript Reader 2 — Pages, Retakes, the Paid Cycle and the Delayed State — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A transcript becomes a set of pages read once each. A student pays for an academic-year cycle before uploading or searching, the cycle carries 50 pages, a refused page is retaken alone (twice at most), and an Azure outage leaves the reading *delayed* and resumed by a sweep instead of failed.

**Architecture:** A new `concierge.StudentCycle` row is the paid cycle and the page counter. Each transcript upload gets a `documents.TranscriptUpload` (role, mode, retake slot, reading state). Each page it yields becomes a `documents.TranscriptPage` holding the read `OcrPage` as JSON, which doubles as the layout cache. `apps/documents/transcript_pages.py::process_upload` reads one upload into pages: inventory, allowance, Azure, write. Then it assembles the cycle's live pages into a `TranscriptReading` through Jev. The worker calls it. A scheduled `resume_transcript_readings` command retries delayed and stuck uploads.

**Tech Stack:** Django 5.2, Python 3.14, PostgreSQL 17 with FORCE row-level security, pydantic, pytest. Infrastructure is CloudFormation (`infra/template.yaml`), with EventBridge driving ECS RunTask.

**Spec:** `docs/superpowers/specs/2026-10-03-transcript-reader-redesign-design.md` (§2 R3/R5/R13, §3.1, §4 "When Azure is down", §5, §7.1, §10). Plan 1 is merged as PR #176: `docs/superpowers/plans/2026-10-05-transcript-reader-1-azure-swap.md`.

## Not in this plan
- **Plan 3 (checks and confirm screen):**
  - ordering pages by printed page numbers, and `page_missing`;
  - crops, polygons and per-cell confirm choices;
  - typed values after the last retake (R3's "type the flagged cells");
  - telling the student a reading was accepted.
- **Plan 4:** the audit.
- **The fees design:** a real checkout. Until it exists, `manage.py mark_cycle_paid` sets `paid_at` (owner decision 2026-10-05: "Minimal cycle record").
- **HEIC conversion.** A HEIC upload is refused with the reason `heic` ("Upload a JPEG or PDF"), which is the spec's own §3.1 fallback. `pillow-heif` wheels bundle libheif (LGPL) and, on some platforms, an x265 encoder (GPL). That licence question is **Unverified** and not worth opening for a fallback the spec already allows. §9 gate 8, a real iPhone upload, still decides whether conversion is needed.
- **Per-page digests inside a PDF.** Duplicates are caught per file (sha256 of the upload). The common case is the same photo uploaded twice.
- **Refusal wording in az/tr/ru/en.** The API returns reason codes. Turning them into text belongs to the presentation layer (`CLAUDE.md`, "Frontend and design").

## Global Constraints
- **Allowance:** 50 pages per paid academic-year cycle (spec §7.1). It counts every page read, by Azure or from a text layer. A retake counts as a page. Our own re-reads never count.
- **Over the allowance:** an upload that would pass 50 is refused whole, with the number of pages left, before anything is read. Nothing already read is lost.
- **Retakes:** at most 2 per page (R3). The API refuses a third with `409 retakes_used`.
- **Pay first (R13):** a transcript upload and the programme search both require a paid cycle. CV uploads are not gated.
- **Translations (R5):** when any live page of the cycle came from a TRANSLATION upload, the reading is built from translation pages only. A page inside a translation upload that is not in English is skipped, not refused, and still counts toward the allowance.
- **Outages:** when Azure is down or the per-tenant daily ceiling is hit, the upload is DELAYED and resumed. It is never dropped and never read by another engine ("no silent fallback").
- **Storage:** Azure's raw response is never stored. A page stores only its `OcrPage` (lines, tables, cell confidences).
- **Tenant tables:** every new table gets ENABLE and FORCE ROW LEVEL SECURITY, the `tenant_isolation` policy, and composite `(tenant_id, fk)` foreign keys, the way `apps/documents/migrations/0021_transcript_reading_tenant_guards.py` does. It is listed in a `tests/migrations/test_*_tenant_guards.py`.
- **Erasure:** every new student-reachable field is classified in `apps/audit/redaction.py` (REDACT or KEEP), or `tests/audit/test_redaction_classification.py` fails.
- **Commands:**
  - Lint: `uv run ruff check .` (never `ruff format`).
  - Types: `uv run mypy apps config`.
  - Tests: `POSTGRES_DB=tehsil_transcript uv run pytest -q`.
  - Migrations: `uv run python manage.py makemigrations --check --dry-run`.
  - Never hand-edit an applied migration.
- **Worktree:** work in `/home/orkhan/Desktop/transcript-redesign` (branch `claude/transcript-reader-2-pages`). Use `git -C` for git. The shell's working directory resets between calls.

## Review Focus
1. **The same photo uploaded twice** (a double tap). The second upload is charged nothing and creates no slot (Task 7 test).
2. **The scan event redelivered after pages were written.** No second inventory or Azure call, and the allowance is unchanged (Task 8 test).
3. **The allowance boundary.** At 48 pages used, a 3-page PDF is refused `allowance_exceeded` with 2 left and nothing read. A 2-page PDF is accepted and reaches 50 (Task 7 test).
4. **A translation uploaded after the original was read.** The next reading uses only the translation's pages, and the original's pages stay live but unused (Task 8 test).
5. **An upload registered and never sent** (the student closed the tab). Other uploads still assemble into a reading (Task 8 test). Separately, **erasure still completes** for a student with uploads and pages, despite the new PROTECT foreign keys (Task 3 test).

---

### Task 1: The paid cycle

**Files:**
- Modify: `apps/concierge/models.py` (add `StudentCycle` after `ServiceEngagement`)
- Create: `apps/concierge/cycles.py`
- Create: `apps/concierge/management/commands/mark_cycle_paid.py` (create `management/` and `management/commands/` with empty `__init__.py` if absent)
- Create: migrations `apps/concierge/migrations/0008_studentcycle.py` (generated) and `0009_studentcycle_tenant_guards.py` (hand-written)
- Modify: `apps/audit/redaction.py` (KEEP entry)
- Create: `tests/concierge/test_cycles.py`, `tests/migrations/test_concierge_tenant_guards.py`
- Modify: `docs/runbooks/deploy.md` (one paragraph)

**Interfaces:**
- Produces:
  - `apps.concierge.models.StudentCycle` with fields `student`, `academic_year: str` ("2026-2027"), `paid_at: datetime | None`, `pages_used: int` and `created_at`.
  - `apps.concierge.cycles.paid_cycle(student_id: UUID) -> StudentCycle | None`.
  - The command `manage.py mark_cycle_paid --tenant <uuid> --student <membership uuid> --academic-year YYYY-YYYY`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/concierge/test_cycles.py
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError

from apps.concierge.cycles import paid_cycle
from apps.concierge.models import StudentCycle
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _mark(agency, membership, year="2026-2027"):
    out = StringIO()
    call_command(
        "mark_cycle_paid",
        tenant=str(agency.id),
        student=str(membership.id),
        academic_year=year,
        stdout=out,
    )
    return out.getvalue()


def test_no_cycle_means_unpaid(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        assert paid_cycle(membership_a.id) is None


def test_an_unpaid_cycle_row_is_still_unpaid(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        StudentCycle.objects.create(student=membership_a, academic_year="2026-2027")
        assert paid_cycle(membership_a.id) is None


def test_marking_a_cycle_paid_is_audited_and_found(agency_a, membership_a):
    assert "paid" in _mark(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        cycle = paid_cycle(membership_a.id)
        assert cycle is not None and cycle.academic_year == "2026-2027"
        assert cycle.pages_used == 0
        assert AuditEvent.objects.filter(event="cycle.marked_paid", object_id=cycle.id).count() == 1


def test_marking_twice_changes_nothing(agency_a, membership_a):
    _mark(agency_a, membership_a)
    assert "already paid" in _mark(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(event="cycle.marked_paid").count() == 1


def test_the_newest_paid_cycle_wins(agency_a, membership_a):
    _mark(agency_a, membership_a, "2026-2027")
    _mark(agency_a, membership_a, "2027-2028")
    with tenant_scope(agency_a.id):
        assert paid_cycle(membership_a.id).academic_year == "2027-2028"


@pytest.mark.parametrize("year", ["2026", "2026-2028", "26-27", "2026/2027"])
def test_a_malformed_year_is_refused(agency_a, membership_a, year):
    with pytest.raises(CommandError):
        _mark(agency_a, membership_a, year)


def test_an_unknown_student_is_refused(agency_a):
    with pytest.raises(CommandError):
        call_command(
            "mark_cycle_paid",
            tenant=str(agency_a.id),
            student=str(uuid4()),
            academic_year="2026-2027",
            stdout=StringIO(),
        )


def test_one_cycle_per_student_and_year(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        StudentCycle.objects.create(student=membership_a, academic_year="2026-2027")
        with pytest.raises(IntegrityError):
            StudentCycle.objects.create(student=membership_a, academic_year="2026-2027")
```

```python
# tests/migrations/test_concierge_tenant_guards.py
import pytest
from django.db import connection

_RLS_TABLES = ("concierge_studentcycle",)
_COMPOSITE_FKS = {"concierge_studentcycle": {"studentcycle_student_tenant_fk"}}


@pytest.mark.django_db
@pytest.mark.parametrize("table", _RLS_TABLES)
def test_table_forces_row_level_security_with_a_tenant_policy(table):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass",
            [f"public.{table}"],
        )
        assert cursor.fetchone() == (True, True)
        cursor.execute("SELECT polname FROM pg_policy WHERE polrelid = %s::regclass", [f"public.{table}"])
        assert {row[0] for row in cursor.fetchall()} == {"tenant_isolation"}


@pytest.mark.django_db
@pytest.mark.parametrize(("table", "expected"), sorted(_COMPOSITE_FKS.items()))
def test_composite_tenant_foreign_keys_exist(table, expected):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'",
            [f"public.{table}"],
        )
        names = {row[0] for row in cursor.fetchall()}
    assert expected <= names, f"missing on {table}: {sorted(expected - names)}"
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/concierge/test_cycles.py tests/migrations/test_concierge_tenant_guards.py -q`
Expected: FAIL with `ImportError: cannot import name 'paid_cycle'` (or `StudentCycle`).

- [ ] **Step 3: The model**

Add to `apps/concierge/models.py`, after `ServiceEngagement`:

```python
class StudentCycle(TenantScopedModel):
    """One academic-year cycle a student pays for (transcript spec R13, §7.1).

    Nothing is uploaded as a transcript and no programme search starts until `paid_at` is set:
    today by `manage.py mark_cycle_paid`, later by a checkout. `pages_used` is the transcript
    reader's allowance counter -- 50 pages a cycle -- kept here and not in the rate-limit cache,
    because a cycle outlives any cache window.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    academic_year = models.CharField(max_length=9)
    paid_at = models.DateTimeField(null=True, blank=True)
    pages_used = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="studentcycle_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("student", "academic_year"), name="studentcycle_student_year_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(academic_year__regex=r"^\d{4}-\d{4}$"),
                name="studentcycle_academic_year_shape",
            ),
        ]
```

- [ ] **Step 4: The migrations**

Run: `cd /home/orkhan/Desktop/transcript-redesign && uv run python manage.py makemigrations concierge -n studentcycle`
Then trim its `dependencies` to the minimum: `("concierge", "0007_documentversion_kind")`, plus whatever `tenancy` migration the generator names. Do not depend on the leaf `makemigrations` picks for other apps (see the comment in `apps/documents/migrations/0020_transcript_reading.py`).

Create `apps/concierge/migrations/0009_studentcycle_tenant_guards.py`:

```python
from django.db import migrations

TABLE = "concierge_studentcycle"

RLS_SQL = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {TABLE}
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE {TABLE}
    ADD CONSTRAINT studentcycle_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
"""

REVERSE_SQL = f"""
ALTER TABLE {TABLE} DROP CONSTRAINT studentcycle_student_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("concierge", "0008_studentcycle"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
```

- [ ] **Step 5: The lookup and the command**

```python
# apps/concierge/cycles.py
"""The paid academic-year cycle (transcript spec R13, §7.1)."""

from __future__ import annotations

from uuid import UUID

from .models import StudentCycle


def paid_cycle(student_id: UUID) -> StudentCycle | None:
    """The student's newest paid cycle, or None: no transcript upload and no search without one."""
    return (
        StudentCycle.objects.filter(student_id=student_id, paid_at__isnull=False)
        .order_by("-academic_year")
        .first()
    )
```

```python
# apps/concierge/management/commands/mark_cycle_paid.py
"""Mark one student's academic-year cycle paid -- the stand-in for a checkout (R13).

Owner decision 2026-10-05: a minimal cycle record now, the payment provider later. Whoever runs
this is attesting that the fee was received; the AuditEvent is the record that they did.
"""

import re
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from apps.concierge.models import StudentCycle
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Membership


class Command(BaseCommand):
    help = "Mark a student's academic-year cycle paid (until a checkout exists)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", type=UUID, required=True)
        parser.add_argument("--student", type=UUID, required=True)
        parser.add_argument("--academic-year", required=True)

    def handle(self, *args: object, **options: object) -> None:
        tenant = options["tenant"]
        student = options["student"]
        year = str(options["academic_year"])
        assert isinstance(tenant, UUID) and isinstance(student, UUID)
        if not re.fullmatch(r"\d{4}-\d{4}", year) or int(year[5:]) != int(year[:4]) + 1:
            raise CommandError("the academic year is two consecutive years, e.g. 2026-2027")
        with tenant_scope(tenant), transaction.atomic():
            set_local_tenant(tenant)
            if not Membership.objects.filter(id=student, role=Membership.Role.STUDENT).exists():
                raise CommandError("no student with that id in that tenant")
            cycle, _ = StudentCycle.objects.select_for_update().get_or_create(
                student_id=student, academic_year=year
            )
            if cycle.paid_at is not None:
                self.stdout.write(f"already paid on {cycle.paid_at:%Y-%m-%d}")
                return
            cycle.paid_at = timezone.now()
            cycle.save(update_fields=["paid_at"])
            AuditEvent.objects.create(
                actor=None,
                actor_kind=AuditEvent.ActorKind.SYSTEM,
                event="cycle.marked_paid",
                object_id=cycle.id,
            )
        self.stdout.write(f"cycle {year} paid")
```

- [ ] **Step 6: Classify for erasure**

In `apps/audit/redaction.py` KEEP, add the entry below. Nothing in it describes the person, and the record of a paid fee is kept.

```python
    "concierge.StudentCycle": ("academic_year", "paid_at", "pages_used", "created_at"),
```

- [ ] **Step 7: Run the tests and the erasure classification**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/concierge/test_cycles.py tests/migrations/test_concierge_tenant_guards.py tests/audit -q`
Expected: PASS.

- [ ] **Step 8: The runbook line**

Append to `docs/runbooks/deploy.md`:

"**Marking a cycle paid.** Until a checkout exists, a student's academic-year cycle is marked paid by hand: `python manage.py mark_cycle_paid --tenant <agency uuid> --student <membership uuid> --academic-year 2026-2027`. It writes a `cycle.marked_paid` AuditEvent. Transcript uploads and the programme search are refused until it has run (transcript spec R13)."

- [ ] **Step 9: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/concierge apps/audit/redaction.py tests/concierge/test_cycles.py tests/migrations/test_concierge_tenant_guards.py docs/runbooks/deploy.md
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(concierge): a paid academic-year cycle, and the command that marks one paid

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Pay first — transcript uploads and the search

**Files:**
- Modify: `apps/documents/api.py` (`uploads`)
- Modify: `apps/accounts/views.py` (`profile`, the `confirm` branch)
- Modify: `tests/conftest.py` (a `paid_cycle_a` fixture beside `membership_a`)
- Test: `tests/documents/test_api.py`, and the accounts test module that covers profile confirm (find it with `grep -rln "action.*confirm" tests/accounts`)

**Interfaces:**
- Consumes: `paid_cycle(student_id)` (Task 1).
- Produces:
  - `POST /api/documents/uploads` with `kind=TRANSCRIPT` answers `402 {"error": "cycle_unpaid"}` without a paid cycle.
  - Profile confirm answers 402 and starts no `RecommendationRun` without one.
  - The fixture `paid_cycle_a` returns the paid `StudentCycle` of `membership_a`.

- [ ] **Step 1: The fixture**

In `tests/conftest.py`, after `membership_a`:

```python
@pytest.fixture
def paid_cycle_a(agency_a, membership_a):
    from django.utils import timezone

    from apps.concierge.models import StudentCycle
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        return StudentCycle.objects.create(
            student=membership_a, academic_year="2026-2027", paid_at=timezone.now()
        )
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/documents/test_api.py`, reusing that module's `UPLOADS`, client and `domain_a` pattern:

```python
def test_a_transcript_upload_needs_a_paid_cycle(client, user_a, membership_a, domain_a):
    client.force_login(user_a)
    response = client.post(
        UPLOADS, {"kind": "TRANSCRIPT", "role": "ORIGINAL"},
        content_type="application/json", HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 402
    assert response.json() == {"error": "cycle_unpaid"}


def test_a_cv_upload_is_not_gated_on_payment(client, user_a, membership_a, domain_a):
    client.force_login(user_a)
    response = client.post(
        UPLOADS, {"kind": "CV"}, content_type="application/json", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 201
```

Use the presign patch the module's existing upload tests use (`grep -n presigned tests/documents/test_api.py`). Add `role` now: Task 4 makes it required. Until Task 4, `uploads` ignores it.

In the profile-confirm test module, copy the existing successful-confirm test and drop `paid_cycle_a` from it:

```python
def test_confirm_without_a_paid_cycle_starts_no_search(...same fixtures as the passing confirm test...):
    # ...same draft setup as the existing confirm test...
    response = client.post(PROFILE_URL, {"action": "confirm"}, HTTP_HOST=domain_a.host)
    assert response.status_code == 402
    with tenant_scope(agency_a.id):
        assert not RecommendationRun.objects.exists()
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_api.py tests/accounts -q`
Expected: the two new gate tests FAIL (201 or 302 instead of 402).

- [ ] **Step 4: The gates**

In `apps/documents/api.py::uploads`, right after the `invalid_kind` check:

```python
    if kind == "TRANSCRIPT" and paid_cycle(student.id) is None:
        # Spec R13: nothing is read for an unpaid profile, so an unpaid sign-up costs nothing.
        raise _ApiError(402, "cycle_unpaid")
```

In `apps/accounts/views.py::profile`, inside `if request.POST.get("action") == "confirm":`, right after the `next_profile_question` check:

```python
        if paid_cycle(membership.id) is None:
            # Spec R13: the programme search starts only for a paid academic-year cycle.
            return _render_review(
                request,
                draft,
                error="Your application cycle is not paid yet. The search starts once it is.",
                status=402,
            )
```

Import `paid_cycle` from `apps.concierge.cycles` in both files.

- [ ] **Step 5: Existing tests that confirm a profile or upload a transcript now need a paid cycle**

Run the full suite. Every test that now fails with 402 gets the `paid_cycle_a` fixture (or an equivalent paid cycle for its agency). Nothing else changes in it. List the touched tests in the report.

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents/api.py apps/accounts/views.py tests
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat: pay first -- a transcript upload and the programme search need a paid cycle

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Uploads and pages as rows; a reading per cycle

**Files:**
- Modify: `apps/documents/models.py` (add `TranscriptUpload` and `TranscriptPage`; change `TranscriptReading.document`; add `TranscriptReading.cycle`)
- Create: migrations `apps/documents/migrations/0025_transcript_pages.py` (generated) and `0026_transcript_pages_tenant_guards.py` (hand-written)
- Modify: `config/settings/base.py` (`TRANSCRIPT_PAGES_PER_CYCLE`, `TRANSCRIPT_MAX_RETAKES`)
- Modify: `apps/audit/redaction.py`
- Modify: `tests/migrations/test_documents_tenant_guards.py`
- Test: `tests/documents/test_transcript_pages_models.py`, and `tests/privacy/test_erasure.py` (one new case)

**Interfaces:**
- Consumes: `StudentCycle` (Task 1).
- Produces:
  - **`TranscriptUpload`** (one per transcript `DocumentVersion`):
    - Fields: `student`, `cycle`, `document`, `role` (`ORIGINAL`/`TRANSLATION`), `language` (`az`/`tr`/`ru`/""), `mode` (`ADD`/`RETAKE`/`REPLACE`), `retake_slot`, `state` (`PENDING`/`READING`/`DELAYED`/`READ`/`REFUSED`/`FAILED`), `refusal`, `refusal_page`, `pages_counted`, `attempts`, `next_attempt_at`, `assembled`, `file_sha256`, `updated_at`, `created_at`.
    - Choices are nested classes `TranscriptUpload.Role`, `.Mode` and `.State`.
  - **`TranscriptPage`**:
    - Fields: `student`, `cycle`, `upload` (related name `pages`), `number`, `slot`, `retakes`, `state` (`READ`/`REFUSED`/`SKIPPED`), `refusal`, `skipped_because` (`blank`/`original_language`/""), `source` (`text_layer`/`azure`), `api_version`, `page` (JSON of `OcrPage`, or None), `superseded_at`, `created_at`.
    - At most one live page (`superseded_at IS NULL`) per `(cycle, slot)`.
  - **`TranscriptReading`:** `document` becomes a `ForeignKey`, so the upload that completed the reading can have more than one. `cycle` is a nullable `ForeignKey` to `StudentCycle`.
  - **Settings:** `TRANSCRIPT_PAGES_PER_CYCLE = 50` and `TRANSCRIPT_MAX_RETAKES = 2`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_transcript_pages_models.py
import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.concierge.documents import register
from apps.documents.models import TranscriptPage, TranscriptUpload
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _upload(agency, membership, cycle, **fields):
    document = register(agency.id, membership.id, kind="TRANSCRIPT")
    with tenant_scope(agency.id):
        return TranscriptUpload.objects.create(
            student=membership, cycle=cycle, document=document,
            role=fields.pop("role", "ORIGINAL"), **fields,
        )


def _page(upload, slot, **fields):
    return TranscriptPage.objects.create(
        student=upload.student, cycle=upload.cycle, upload=upload, number=1, slot=slot,
        state=fields.pop("state", "READ"), source="azure", **fields,
    )


def test_a_new_upload_is_pending_and_charged_nothing(agency_a, membership_a, paid_cycle_a):
    upload = _upload(agency_a, membership_a, paid_cycle_a)
    assert (upload.state, upload.pages_counted, upload.attempts, upload.assembled) == (
        "PENDING", None, 0, False,
    )


def test_one_live_page_per_slot(agency_a, membership_a, paid_cycle_a):
    upload = _upload(agency_a, membership_a, paid_cycle_a)
    with tenant_scope(agency_a.id):
        _page(upload, 1)
        with pytest.raises(IntegrityError), transaction.atomic():
            _page(upload, 1)


def test_a_superseded_page_frees_its_slot(agency_a, membership_a, paid_cycle_a):
    upload = _upload(agency_a, membership_a, paid_cycle_a)
    with tenant_scope(agency_a.id):
        old = _page(upload, 1)
        old.superseded_at = timezone.now()
        old.save(update_fields=["superseded_at"])
        _page(upload, 1, retakes=1)
        assert TranscriptPage.objects.filter(slot=1, superseded_at__isnull=True).count() == 1


def test_a_retake_names_its_slot_and_nothing_else_does(agency_a, membership_a, paid_cycle_a):
    with pytest.raises(IntegrityError), transaction.atomic():
        _upload(agency_a, membership_a, paid_cycle_a, mode="RETAKE")
    with pytest.raises(IntegrityError), transaction.atomic():
        _upload(agency_a, membership_a, paid_cycle_a, mode="ADD", retake_slot=2)
```

Add the four new tables or columns to `tests/migrations/test_documents_tenant_guards.py`:
- `_RLS_TABLES` += `"documents_transcriptupload"`, `"documents_transcriptpage"`.
- `_COMPOSITE_FKS`:
  - `"documents_transcriptupload"`: `{"transcriptupload_student_tenant_fk", "transcriptupload_cycle_tenant_fk", "transcriptupload_document_tenant_fk"}`.
  - `"documents_transcriptpage"`: `{"transcriptpage_student_tenant_fk", "transcriptpage_cycle_tenant_fk", "transcriptpage_upload_tenant_fk"}`.
  - `"documents_transcriptreading"`: `{"transcriptreading_student_tenant_fk", "transcriptreading_document_tenant_fk", "transcriptreading_cycle_tenant_fk"}`.

Add one case to `tests/privacy/test_erasure.py`, modelled on the case there that erases a student with a `TranscriptReading`. The student has a `StudentCycle`, a `TranscriptUpload` and a `TranscriptPage` whose `page` holds text, and the erasure must complete. Assert the page's `page` field is blanked the way `TranscriptReading.record` is.

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_transcript_pages_models.py tests/migrations/test_documents_tenant_guards.py -q`
Expected: FAIL with `ImportError: cannot import name 'TranscriptPage'`.

- [ ] **Step 3: The models**

In `apps/documents/models.py`:

```python
class TranscriptUpload(TenantScopedModel):
    """One transcript file and what reading it came to (spec 2026-10-03 §3.1).

    `pages_counted` is set once, when the upload's pages are charged to the cycle's allowance:
    a redelivery never charges again. `assembled` says the cycle's reading was rebuilt after this
    upload's pages were written; until then the resume sweep may pick it up.
    """

    class Role(models.TextChoices):
        ORIGINAL = "ORIGINAL"
        TRANSLATION = "TRANSLATION"

    class Mode(models.TextChoices):
        ADD = "ADD"
        RETAKE = "RETAKE"
        REPLACE = "REPLACE"

    class State(models.TextChoices):
        PENDING = "PENDING"
        READING = "READING"
        DELAYED = "DELAYED"
        READ = "READ"
        REFUSED = "REFUSED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    cycle = models.ForeignKey("concierge.StudentCycle", on_delete=models.PROTECT)
    document = models.OneToOneField("concierge.DocumentVersion", on_delete=models.PROTECT)
    role = models.CharField(max_length=12, choices=Role.choices)
    #: The language of an ORIGINAL, sent to Azure as its locale hint (spec §4); "" when unsaid.
    language = models.CharField(max_length=2, blank=True)
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.ADD)
    retake_slot = models.PositiveSmallIntegerField(null=True, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.PENDING)
    #: Why the whole upload was refused or failed: a page-gate or file reason, `heic`,
    #: `allowance_exceeded`, `retake_one_page`, `not_a_transcript`, `reader_unavailable`...
    refusal = models.CharField(max_length=30, blank=True)
    #: The page a refusal names -- or, for `allowance_exceeded`, how many pages are left.
    refusal_page = models.PositiveSmallIntegerField(null=True, blank=True)
    pages_counted = models.PositiveSmallIntegerField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    assembled = models.BooleanField(default=False)
    file_sha256 = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="transcriptupload_tenant_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(mode="RETAKE", retake_slot__isnull=False)
                | (~models.Q(mode="RETAKE") & models.Q(retake_slot__isnull=True)),
                name="transcriptupload_retake_names_a_slot",
            ),
        ]


class TranscriptPage(TenantScopedModel):
    """One page of the student's transcript, read once and kept (spec §3.1).

    `page` is the read OcrPage -- the layout cache: a redelivery, a retake of another page or a
    new reading never reads or bills this page again. A retake supersedes the page in its slot.
    """

    class State(models.TextChoices):
        READ = "READ"
        REFUSED = "REFUSED"
        SKIPPED = "SKIPPED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    cycle = models.ForeignKey("concierge.StudentCycle", on_delete=models.PROTECT)
    upload = models.ForeignKey(TranscriptUpload, on_delete=models.PROTECT, related_name="pages")
    #: The page's number within its upload's file.
    number = models.PositiveSmallIntegerField()
    #: Its place in the transcript, from 1.
    slot = models.PositiveSmallIntegerField()
    retakes = models.PositiveSmallIntegerField(default=0)
    state = models.CharField(max_length=8, choices=State.choices)
    refusal = models.CharField(max_length=30, blank=True)
    skipped_because = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=10)
    api_version = models.CharField(max_length=20, blank=True)
    page = models.JSONField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="transcriptpage_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("cycle", "slot"),
                condition=models.Q(superseded_at__isnull=True),
                name="transcriptpage_one_live_page_per_slot",
            ),
        ]
```

On `TranscriptReading`:

```python
    #: The upload whose arrival completed this reading. A cycle has a reading per completion; the
    #: newest is the student's (consultation.prefill_from_latest_reading).
    document = models.ForeignKey("concierge.DocumentVersion", on_delete=models.PROTECT)
    cycle = models.ForeignKey(
        "concierge.StudentCycle", null=True, blank=True, on_delete=models.PROTECT
    )
```

`grep -rn "\.transcriptreading\b" apps tests` must print nothing. That was the one-to-one accessor; the `transcriptreading__isnull` query lookup still works on a ForeignKey.

Settings, in `config/settings/base.py` beside `TRANSCRIPT_LOW_CONFIDENCE_BELOW`:

```python
#: Spec 2026-10-03 §7.1: pages one paid academic-year cycle may have read, retakes included.
TRANSCRIPT_PAGES_PER_CYCLE = 50
#: Spec R3: retakes of one page before the student is asked to type its flagged cells instead.
TRANSCRIPT_MAX_RETAKES = 2
```

- [ ] **Step 4: The migrations**

Run: `cd /home/orkhan/Desktop/transcript-redesign && uv run python manage.py makemigrations documents -n transcript_pages`
Trim its dependencies to `("documents", "0024_merge_20260927_0906")` and `("concierge", "0009_studentcycle_tenant_guards")`.

Create `apps/documents/migrations/0026_transcript_pages_tenant_guards.py`, following `0021_transcript_reading_tenant_guards.py`:
- `TABLES = ("documents_transcriptupload", "documents_transcriptpage")`. For each, ENABLE and FORCE RLS plus the `tenant_isolation` policy (copy the four lines from 0021).
- These composite FKs, each `FOREIGN KEY (tenant_id, <col>_id) REFERENCES <table> (tenant_id, id)`:
  - `transcriptupload_student_tenant_fk` → `tenancy_membership`;
  - `transcriptupload_cycle_tenant_fk` → `concierge_studentcycle`;
  - `transcriptupload_document_tenant_fk` → `concierge_documentversion`;
  - `transcriptpage_student_tenant_fk` → `tenancy_membership`;
  - `transcriptpage_cycle_tenant_fk` → `concierge_studentcycle`;
  - `transcriptpage_upload_tenant_fk` → `documents_transcriptupload`;
  - `transcriptreading_cycle_tenant_fk` on `documents_transcriptreading (tenant_id, cycle_id)` → `concierge_studentcycle`.
- A reverse SQL that drops each constraint, then the policies, then disables RLS.
- Dependencies: `("documents", "0025_transcript_pages")`, `("concierge", "0009_studentcycle_tenant_guards")`, `("tenancy", "0002_rls")`.

- [ ] **Step 5: Classify for erasure**

In `apps/audit/redaction.py`:
- **REDACT:**
  - `"documents.TranscriptPage": RedactSpec("student_id", ("page",))`, because it holds the transcript's text.
  - `"documents.TranscriptUpload": RedactSpec("student_id", ("file_sha256",))`, because a digest identifies the file.
- **KEEP:**
  - `"documents.TranscriptPage": ("number", "slot", "retakes", "state", "refusal", "skipped_because", "source", "api_version", "superseded_at", "created_at")`.
  - `"documents.TranscriptUpload": ("role", "language", "mode", "retake_slot", "state", "refusal", "refusal_page", "pages_counted", "attempts", "next_attempt_at", "assembled", "updated_at", "created_at")`.

If the erasure test shows a PROTECT foreign key blocking deletion, follow how `TranscriptReading` (already PROTECT on `DocumentVersion`) is handled there. Do not change `on_delete` to CASCADE without reading that path first. Report what you found.

- [ ] **Step 6: Run the tests**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_transcript_pages_models.py tests/migrations tests/audit tests/privacy -q && uv run python manage.py makemigrations --check --dry-run`
Expected: PASS and "No changes detected".

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents/models.py apps/documents/migrations config/settings/base.py apps/audit/redaction.py tests
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(documents): transcript uploads and pages as rows; a reading per completion, per cycle

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The upload API learns role, mode and slot; the student sees the transcript

**Files:**
- Modify: `apps/documents/api.py` (`uploads`, `upload_status`, new `transcript` view)
- Modify: `apps/documents/urls.py` (`api/documents/transcript`)
- Test: `tests/documents/test_api.py`, `tests/documents/test_transcript_worker.py` (update its upload-status assertions)

**Interfaces:**
- Consumes: `paid_cycle` (Task 1); `TranscriptUpload`, `TranscriptPage`, `TranscriptReading.cycle` and both settings (Task 3).
- Produces:
  - **`POST /api/documents/uploads`** with `kind=TRANSCRIPT`:
    - Requires `role` (`ORIGINAL`/`TRANSLATION`).
    - Optional `mode` (`ADD` default, `RETAKE`, `REPLACE`), `slot` (an int, required for and only allowed with `RETAKE`), and `language` (`az`/`tr`/`ru`, allowed only with `ORIGINAL`).
    - Creates the `DocumentVersion` and its `TranscriptUpload` in one transaction.
    - Errors: `400 invalid_role` / `invalid_mode` / `invalid_slot` / `invalid_language`, `404 slot_not_found`, `409 retakes_used`.
  - **`GET /api/documents/uploads/<id>`** for a transcript returns `{"state", "scan_result", "reading": {"state", "refusal", "refusal_page"} | None}`. The old `read` key is removed.
  - **`GET /api/documents/transcript`** returns `{"pages_left", "waiting", "delayed", "reading_id", "pages": [{"slot", "state", "refusal", "skipped_because", "retakes_left"}]}` for the paid cycle, or `402 cycle_unpaid`.

- [ ] **Step 1: Write the failing tests** (in `tests/documents/test_api.py`; reuse its presign patch and client pattern)

```python
def _post(client, domain, **body):
    return client.post(UPLOADS, {"kind": "TRANSCRIPT", **body}, content_type="application/json", HTTP_HOST=domain.host)


def test_a_transcript_upload_records_its_role_and_language(client, user_a, membership_a, domain_a, paid_cycle_a, agency_a):
    client.force_login(user_a)
    response = _post(client, domain_a, role="ORIGINAL", language="az")
    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        upload = TranscriptUpload.objects.get(document_id=response.json()["document_id"])
    assert (upload.role, upload.language, upload.mode, upload.retake_slot, upload.cycle_id) == (
        "ORIGINAL", "az", "ADD", None, paid_cycle_a.id,
    )


@pytest.mark.parametrize(("body", "error"), [
    ({}, "invalid_role"),
    ({"role": "COPY"}, "invalid_role"),
    ({"role": "ORIGINAL", "mode": "APPEND"}, "invalid_mode"),
    ({"role": "ORIGINAL", "mode": "RETAKE"}, "invalid_slot"),
    ({"role": "ORIGINAL", "mode": "RETAKE", "slot": True}, "invalid_slot"),
    ({"role": "ORIGINAL", "slot": 1}, "invalid_slot"),
    ({"role": "TRANSLATION", "language": "az"}, "invalid_language"),
    ({"role": "ORIGINAL", "language": "de"}, "invalid_language"),
    ({"role": "ORIGINAL", "language": ["az"]}, "invalid_language"),
])
def test_a_malformed_transcript_upload_is_refused(client, user_a, membership_a, domain_a, paid_cycle_a, body, error):
    client.force_login(user_a)
    response = _post(client, domain_a, **body)
    assert (response.status_code, response.json()) == (400, {"error": error})


def test_a_retake_needs_a_live_page_in_that_slot(client, user_a, membership_a, domain_a, paid_cycle_a):
    client.force_login(user_a)
    response = _post(client, domain_a, role="ORIGINAL", mode="RETAKE", slot=3)
    assert (response.status_code, response.json()) == (404, {"error": "slot_not_found"})


def test_a_third_retake_is_refused(client, user_a, membership_a, domain_a, paid_cycle_a, agency_a):
    client.force_login(user_a)
    first = _post(client, domain_a, role="ORIGINAL").json()["document_id"]
    with tenant_scope(agency_a.id):
        upload = TranscriptUpload.objects.get(document_id=first)
        TranscriptPage.objects.create(
            student=membership_a, cycle=paid_cycle_a, upload=upload, number=1, slot=1,
            state="REFUSED", refusal="unreadable", source="azure", retakes=2,
        )
    response = _post(client, domain_a, role="ORIGINAL", mode="RETAKE", slot=1)
    assert (response.status_code, response.json()) == (409, {"error": "retakes_used"})


def test_the_transcript_view_lists_live_pages_and_pages_left(client, user_a, membership_a, domain_a, paid_cycle_a, agency_a):
    client.force_login(user_a)
    first = _post(client, domain_a, role="ORIGINAL").json()["document_id"]
    with tenant_scope(agency_a.id):
        upload = TranscriptUpload.objects.get(document_id=first)
        TranscriptPage.objects.create(
            student=membership_a, cycle=paid_cycle_a, upload=upload, number=1, slot=1,
            state="REFUSED", refusal="cut_off", source="azure", retakes=1,
        )
        paid_cycle_a.pages_used = 7
        paid_cycle_a.save(update_fields=["pages_used"])
    body = client.get("/api/documents/transcript", HTTP_HOST=domain_a.host).json()
    assert body["pages_left"] == 43
    assert body["pages"] == [
        {"slot": 1, "state": "REFUSED", "refusal": "cut_off", "skipped_because": "", "retakes_left": 1}
    ]
    assert (body["waiting"], body["delayed"], body["reading_id"]) == (False, False, None)
```

In `tests/documents/test_transcript_worker.py`, the upload-status assertions that expect `"read": ...` now expect `"reading": {...}` or `None`. Update them to the new shape.

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_api.py -q`
Expected: the new tests FAIL (no `TranscriptUpload` is created; `/api/documents/transcript` gives 404).

- [ ] **Step 3: Implement**

In `apps/documents/api.py`:

```python
_ROLES = frozenset({"ORIGINAL", "TRANSLATION"})
_MODES = frozenset({"ADD", "RETAKE", "REPLACE"})
_LANGUAGES = frozenset({"az", "tr", "ru"})


def _transcript_upload(body: dict[str, object], cycle: StudentCycle) -> dict[str, object]:
    """The TranscriptUpload fields a request asks for, or the _ApiError it earns."""
    role = body.get("role")
    if not isinstance(role, str) or role not in _ROLES:
        raise _ApiError(400, "invalid_role")
    mode = body.get("mode", "ADD")
    if not isinstance(mode, str) or mode not in _MODES:
        raise _ApiError(400, "invalid_mode")
    language = body.get("language", "")
    if not isinstance(language, str) or (language and (language not in _LANGUAGES or role != "ORIGINAL")):
        raise _ApiError(400, "invalid_language")
    slot = body.get("slot")
    if mode != "RETAKE":
        if slot is not None:
            raise _ApiError(400, "invalid_slot")
        return {"role": role, "mode": mode, "language": language, "retake_slot": None}
    if not isinstance(slot, int) or isinstance(slot, bool) or slot < 1:
        raise _ApiError(400, "invalid_slot")
    page = TranscriptPage.objects.filter(cycle=cycle, slot=slot, superseded_at__isnull=True).first()
    if page is None:
        raise _ApiError(404, "slot_not_found")
    if page.retakes >= settings.TRANSCRIPT_MAX_RETAKES:
        raise _ApiError(409, "retakes_used")
    return {"role": role, "mode": mode, "language": language, "retake_slot": slot}
```

In `uploads`, replace the body from the `kind` read onward. Task 2's gate becomes the `cycle is None` line:

```python
    body = _json_body(request)
    kind = body.get("kind", "CV")
    if not isinstance(kind, str) or kind not in {"CV", "TRANSCRIPT"}:
        raise _ApiError(400, "invalid_kind")
    fields: dict[str, object] | None = None
    if kind == "TRANSCRIPT":
        cycle = paid_cycle(student.id)
        if cycle is None:
            # Spec R13: nothing is read for an unpaid profile, so an unpaid sign-up costs nothing.
            raise _ApiError(402, "cycle_unpaid")
        fields = {**_transcript_upload(body, cycle), "cycle": cycle}
    with transaction.atomic():
        document = register(current_tenant_id(), student.id, kind=kind)
        if fields is not None:
            TranscriptUpload.objects.create(student=student, document=document, **fields)
    presigned = presigned_upload(document)
```

(The `JsonResponse(... status=201)` return stays.) Then:
- **In `upload_status`**, replace the `body["read"]` lines with:

```python
    if document.kind == "TRANSCRIPT":
        upload = TranscriptUpload.objects.filter(document=document).first()
        body["reading"] = None if upload is None else {
            "state": upload.state, "refusal": upload.refusal, "refusal_page": upload.refusal_page,
        }
```

- **Add the `transcript` view:**

```python
@require_GET
@_student_endpoint
def transcript(request: HttpRequest, student: Membership) -> HttpResponse:
    """The student's transcript as the reader holds it: its live pages and what is left to read."""
    cycle = paid_cycle(student.id)
    if cycle is None:
        raise _ApiError(402, "cycle_unpaid")
    pages = TranscriptPage.objects.filter(cycle=cycle, superseded_at__isnull=True).order_by("slot")
    uploads = TranscriptUpload.objects.filter(cycle=cycle)
    reading = TranscriptReading.objects.filter(cycle=cycle).order_by("-created_at").first()
    return JsonResponse({
        "pages_left": max(0, settings.TRANSCRIPT_PAGES_PER_CYCLE - cycle.pages_used),
        "waiting": uploads.filter(state__in=("READING", "DELAYED")).exists(),
        "delayed": uploads.filter(state="DELAYED").exists(),
        "reading_id": str(reading.id) if reading else None,
        "pages": [
            {
                "slot": page.slot, "state": page.state, "refusal": page.refusal,
                "skipped_because": page.skipped_because,
                "retakes_left": max(0, settings.TRANSCRIPT_MAX_RETAKES - page.retakes),
            }
            for page in pages
        ],
    })
```

- **Route it** in `apps/documents/urls.py`, next to the uploads routes: `path("api/documents/transcript", api.transcript, name=...)`, naming it like its neighbours.

- [ ] **Step 4: Run the tests**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest -q`
Expected: PASS. An existing test that posts a TRANSCRIPT upload without `role` now gets `400 invalid_role`; give it `"role": "ORIGINAL"` and list it in the report.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents/api.py apps/documents/urls.py tests/documents
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(documents): transcript uploads carry role, mode and slot; the student can see the transcript's pages

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The OCR seam answers per page

**Files:**
- Modify: `apps/documents/ocr.py`
- Test: `tests/documents/test_ocr.py`

**Interfaces:**
- Produces:
  - `InventoryPage` (renamed from `_InventoryPage`, now public; same fields).
  - `inventory(document: DocumentVersion, content: bytes) -> tuple[InventoryPage, ...]`. It raises `PageRefused` for a parser refusal and `OcrUnavailable` for an unparseable answer.
  - `PageRead(number: int, page: OcrPage | None = None, refusal: str | None = None, blank: bool = False)`, a frozen dataclass.
  - `read_inventory(content: bytes, pages: tuple[InventoryPage, ...], *, locale: str | None = None, analyze=analyze_layout) -> tuple[PageRead, ...]`, in inventory order. A gate refusal is a `PageRead` with `refusal`, not an exception. An Azure page with no words is `blank=True`.
  - `read_pages` stays, as a wrapper, until Task 8 removes it: `read_inventory(inventory(...))`, then it raises the first refusal and `not_a_transcript` as today.

- [ ] **Step 1: Write the failing tests** (in `tests/documents/test_ocr.py`, reusing its `_answering`, `_layout` and Azure-page helpers)

```python
def test_a_refused_page_does_not_stop_the_others_being_read(tmp_path, monkeypatch):
    # Copy the inventory and layout setup of the existing mixed-PDF test:
    # page 1 an image page that reads well, page 2 an image page whose words are 5 px tall.
    pages = ocr.inventory(_DOCUMENT, b"%PDF")
    reads = ocr.read_inventory(b"%PDF", pages, analyze=lambda content, **k: layout)
    assert [r.number for r in reads] == [1, 2]
    assert reads[0].page is not None and reads[0].refusal is None
    assert (reads[1].page, reads[1].refusal) == (None, "text_too_small")


def test_an_azure_page_with_no_words_is_blank_not_refused(tmp_path, monkeypatch):
    # one image page; Azure answers it with words=()
    [read] = ocr.read_inventory(b"\x89PNG", ocr.inventory(_DOCUMENT, b"\x89PNG"), analyze=lambda c, **k: layout)
    assert (read.blank, read.page, read.refusal) == (True, None, None)


def test_a_parser_refusal_still_raises(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"refused": {"reason": "too_many_pages", "page": 31}})
    with pytest.raises(PageRefused) as refused:
        ocr.inventory(_DOCUMENT, b"%PDF")
    assert (refused.value.reason, refused.value.page) == ("too_many_pages", 31)
```

Fill in the `layout` construction from the module's existing helpers. Delete or convert the existing test that `_gate` returns "unreadable" for a page with no words, because `_gate` now only sees pages with words.

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_ocr.py -q`
Expected: FAIL with `AttributeError: module 'apps.documents.ocr' has no attribute 'inventory'`.

- [ ] **Step 3: Implement**

In `apps/documents/ocr.py`:
- Rename `_InventoryPage` to `InventoryPage`.
- Remove `_gate`'s `if not words: return "unreadable"` branch.
- Replace `read_pages` with:

```python
@dataclass(frozen=True)
class PageRead:
    """One inventoried page after reading: its page, the gate's refusal, or blank."""

    number: int
    page: OcrPage | None = None
    refusal: str | None = None
    #: Azure found no words: a blank back page, skipped rather than refused (plan 2).
    blank: bool = False


def inventory(document: DocumentVersion, content: bytes) -> tuple[InventoryPage, ...]:
    """The upload's pages as the isolated parser found them, before anything is billed."""
    raw = _invoke(document.object_key) if settings.OCR_FUNCTION_NAME else _run_child(content)
    try:
        output = _Output.model_validate_json(raw)
    except ValidationError as error:
        raise OcrUnavailable("unparseable output") from error
    if output.refused is not None:
        raise PageRefused(output.refused.reason, output.refused.page)
    return output.pages


def read_inventory(
    content: bytes,
    pages: tuple[InventoryPage, ...],
    *,
    locale: str | None = None,
    analyze: Callable[..., AzureLayout] = analyze_layout,
) -> tuple[PageRead, ...]:
    """Each inventoried page read: text-layer pages as they are, image pages through Azure and the
    gate. Only image pages are sent -- as the original bytes, with Azure's own page selector."""
    image_pages = [page for page in pages if page.source == "image"]
    read: dict[int, PageRead] = {}
    if image_pages:
        is_pdf = content.startswith(b"%PDF")  # the same sniff as the upload gate and the inventory
        selector = ",".join(str(p.number) for p in image_pages) if is_pdf else None
        layout = analyze(content, pages=selector, locale=locale)
        by_number = {page.pageNumber: page for page in layout.pages}
        for inventoried in image_pages:
            azure_page = by_number.get(inventoried.number)
            if azure_page is None and not is_pdf and len(pages) == 1 and layout.pages:
                azure_page = layout.pages[0]  # a bare image is one page, whatever Azure numbers it
            if azure_page is None:
                raise OcrUnavailable(f"Azure returned no page {inventoried.number}")
            if not azure_page.words:
                read[inventoried.number] = PageRead(inventoried.number, blank=True)
                continue
            reason = _gate(azure_page, inventoried.scan_ppi)
            read[inventoried.number] = (
                PageRead(inventoried.number, refusal=reason)
                if reason is not None
                else PageRead(inventoried.number, page=_azure_page(layout, azure_page))
            )
    return tuple(
        read[p.number]
        if p.source == "image"
        else PageRead(p.number, page=OcrPage(lines=p.lines, tables=p.tables, source="text_layer"))
        for p in pages
    )


def read_pages(
    document: DocumentVersion,
    content: bytes,
    *,
    locale: str | None = None,
    analyze: Callable[..., AzureLayout] = analyze_layout,
) -> tuple[OcrPage, ...]:
    """Every page, or PageRefused for the first one refused. Kept for read_transcript until
    plan 2 Task 8 retires the file path; deleted there."""
    reads = read_inventory(content, inventory(document, content), locale=locale, analyze=analyze)
    for read in reads:
        if read.refusal is not None:
            raise PageRefused(read.refusal, read.number)
    found = tuple(read.page for read in reads if read.page is not None)
    if not any(page.tables for page in found):
        raise PageRefused("not_a_transcript", 1)
    return found
```

- [ ] **Step 4: Run the tests**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_ocr.py tests/documents/test_transcript.py -q && uv run mypy apps config`
Expected: PASS. Existing `read_pages` tests still pass, except the blank page: it used to be refused `unreadable` and is now skipped. If no other page has a table, that ends in `not_a_transcript`. Update that one test's expectation and say so in the report.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents/ocr.py tests/documents/test_ocr.py
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(documents): the OCR seam answers per page -- a refused page no longer stops the rest; a blank page is skipped

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The transcript reader reads pages, not a file

**Files:**
- Modify: `apps/documents/transcript.py`
- Test: `tests/documents/test_transcript.py`

**Interfaces:**
- Produces:
  - `check_gates() -> None`. It holds the provider check and both launch gates, moved verbatim out of `read_transcript`, and raises `DecisionsUnavailable` or `TranscriptReadingDisabled` exactly as before.
  - `read_from_pages(pages: tuple[OcrPage, ...], names: frozenset[str], *, client: Client | None = None) -> Reading`, which is `read_transcript`'s body from `_minimised(...)` onward.
  - `read_transcript` stays, as a thin wrapper the worker still uses until Task 8: `check_gates()`, open, the file checks, the rate limit, `read_pages`, then `read_from_pages`. Task 8 deletes it, the hourly limit and `ocr.read_pages` together.

- [ ] **Step 1: Point the tests at the pages entry point**

In `tests/documents/test_transcript.py`:
- Rewrite the `_read` helper so it calls `read_from_pages(pages, names, client=client or _jev())` directly. It no longer patches `read_pages` or builds a document.
- Keep the tests of the gates, the file checks and the rate limit on `read_transcript` for now. Task 8 moves the file checks' tests and deletes the rest.

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_transcript.py -q`
Expected: FAIL with `ImportError: cannot import name 'read_from_pages'`.

- [ ] **Step 2: Split the function**

In `apps/documents/transcript.py`:

```python
def check_gates() -> None:
    """The provider check and both launch gates (spec T19, §3.1, §4), before any file is opened."""
    # ... the provider check and the two TRANSCRIPT_*_ENABLED checks, with their comments, verbatim


def read_from_pages(
    pages: tuple[OcrPage, ...], names: frozenset[str], *, client: Client | None = None
) -> Reading:
    """Turn read pages into a Reading: minimise, ask Jev, copy what it chose (module docstring)."""
    lines, tables, confidences = _minimised(pages, names)
    # ... the rest of read_transcript's body, verbatim


def read_transcript(*, document, names, store=None, client=None) -> Reading:  # signature unchanged
    check_gates()
    content = open_document(document, store=store)
    # ... the size check, the magic-byte check and the rate limit, verbatim
    return read_from_pages(read_pages(document, content, locale=None), names, client=client)
```

The comments in `...` mean move the existing lines unchanged; nothing in them is rewritten.

- [ ] **Step 3: Run the tests**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents -q && uv run ruff check . && uv run mypy apps config`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents/transcript.py tests/documents/test_transcript.py
git -C /home/orkhan/Desktop/transcript-redesign commit -m "refactor(documents): the reader reads pages; the gates and the file checks are separable

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Reading an upload into pages — the allowance, the cache, retakes, translations

**Files:**
- Create: `apps/documents/transcript_pages.py`
- Modify: `config/settings/base.py` (`TRANSCRIPT_TENANT_DAILY_AZURE_PAGES`)
- Test: `tests/documents/test_transcript_pages.py`

**Interfaces:**
- Consumes:
  - `inventory`, `read_inventory`, `PageRead` and `InventoryPage` (Task 5);
  - `check_gates` (Task 6);
  - `TranscriptUpload` and `TranscriptPage` (Task 3);
  - `open_document`, `ReadableObjectStore` (`apps.concierge.documents`);
  - `analyze_layout` (`apps.documents.azure_layout`).
- Produces:
  - `read_upload(tenant_id: UUID, upload_id: UUID, *, store: ReadableObjectStore | None = None, analyze=analyze_layout) -> bool`. It returns True when the upload's pages are written (state READ), and False otherwise: refused, failed, delayed, or nothing to do.
  - `delay(tenant_id: UUID, upload_id: UUID, *, reason: str) -> None`.
  - `is_english(page: OcrPage) -> bool`.
  - Constants `MAX_ATTEMPTS = 12` and `MAX_UPLOAD_BYTES = 10_000_000`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_transcript_pages.py
"""An upload is read once into pages; the allowance is charged once; retakes replace one slot."""

import hashlib
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.concierge.documents import register
from apps.concierge.models import StudentCycle
from apps.documents.models import TranscriptPage, TranscriptUpload
from apps.documents.ocr import InventoryPage, OcrPage, PageRead
from apps.documents.ocr_errors import OcrUnavailable, PageRefused
from apps.documents.transcript_pages import MAX_ATTEMPTS, delay, is_english, read_upload
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG" + b"\x00" * 64
TABLE = (("Course", "ECTS", "Grade"), ("Organic Chemistry", "6", "A"))


def _page(*, tables=(TABLE,), lines=("Transcript of Records",)):
    return OcrPage(lines=lines, tables=tables, source="azure", api_version="2024-11-30")


def _inv(*numbers, source="image"):
    return tuple(
        InventoryPage(number=n, source=source, scan_ppi=300.0, lines=(), tables=()) for n in numbers
    )


def _upload(agency, membership, cycle, *, content=PNG, **fields):
    document = register(agency.id, membership.id, kind="TRANSCRIPT")
    with tenant_scope(agency.id):
        _scanned_clean(document)
        upload = TranscriptUpload.objects.create(
            student=membership, cycle=cycle, document=document,
            role=fields.pop("role", "ORIGINAL"), **fields,
        )
    return upload, content


def _scanned_clean(document):
    """open_document reads only what GuardDuty passed."""
    document.state = "AVAILABLE"
    document.save(update_fields=["state"])


def _run(agency, upload, content, *, inventory, reads):
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=inventory) as inv,
        patch("apps.documents.transcript_pages.read_inventory", return_value=reads) as read,
    ):
        done = read_upload(agency.id, upload.id)
    return done, inv, read


def _live(agency, cycle):
    with tenant_scope(agency.id):
        return list(
            TranscriptPage.objects.filter(cycle=cycle, superseded_at__isnull=True)
            .order_by("slot").values_list("slot", "state", "refusal", "retakes")
        )


def test_an_upload_is_read_into_pages_and_charged_once(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    reads = (PageRead(1, page=_page()), PageRead(2, refusal="cut_off"))
    assert _run(agency_a, upload, content, inventory=_inv(1, 2), reads=reads)[0] is True
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0), (2, "REFUSED", "cut_off", 0)]
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (upload.state, upload.pages_counted, paid_cycle_a.pages_used) == ("READ", 2, 2)
        stored = TranscriptPage.objects.get(slot=1)
        assert OcrPage.model_validate(stored.page) == _page()


def test_a_second_run_reads_nothing_and_charges_nothing(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, upload, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    done, inv, read = _run(agency_a, upload, content, inventory=_inv(1), reads=())
    assert (inv.call_count, read.call_count) == (0, 0)
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 1


def test_the_allowance_boundary(agency_a, membership_a, paid_cycle_a):
    with tenant_scope(agency_a.id):
        StudentCycle.objects.filter(id=paid_cycle_a.id).update(pages_used=48)
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    done, _, read = _run(agency_a, upload, content, inventory=_inv(1, 2, 3), reads=())
    assert done is False and read.call_count == 0
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal, upload.refusal_page) == ("REFUSED", "allowance_exceeded", 2)
    second, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"2")
    reads = (PageRead(1, page=_page()), PageRead(2, page=_page()))
    assert _run(agency_a, second, content, inventory=_inv(1, 2), reads=reads)[0] is True
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 50


def test_the_same_file_twice_is_charged_once_and_adds_no_slot(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    again, _ = _upload(agency_a, membership_a, paid_cycle_a)
    done, inv, _ = _run(agency_a, again, content, inventory=_inv(1), reads=())
    assert done is True and inv.call_count == 0
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0)]
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        again.refresh_from_db()
        assert (paid_cycle_a.pages_used, again.pages_counted, again.file_sha256) == (
            1, None, hashlib.sha256(content).hexdigest(),
        )


def test_a_retake_replaces_its_slot_and_counts(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1, 2),
         reads=(PageRead(1, page=_page()), PageRead(2, refusal="unreadable")))
    retake, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"r",
                              mode="RETAKE", retake_slot=2)
    assert _run(agency_a, retake, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))[0]
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0), (2, "READ", "", 1)]


def test_a_retake_must_be_one_page(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, refusal="cut_off"),))
    retake, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"r",
                              mode="RETAKE", retake_slot=1)
    assert _run(agency_a, retake, content, inventory=_inv(1, 2), reads=())[0] is False
    with tenant_scope(agency_a.id):
        retake.refresh_from_db()
        assert (retake.state, retake.refusal) == ("REFUSED", "retake_one_page")


def test_replace_supersedes_every_live_page(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1, 2),
         reads=(PageRead(1, page=_page()), PageRead(2, page=_page())))
    new, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"n", mode="REPLACE")
    _run(agency_a, new, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0)]


def test_add_appends_after_the_last_slot(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    second, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"2")
    _run(agency_a, second, content, inventory=_inv(1), reads=(PageRead(1, page=_page(tables=())),))
    assert [slot for slot, *_ in _live(agency_a, paid_cycle_a)] == [1, 2]


def test_a_first_upload_with_no_table_is_not_a_transcript(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, upload, content, inventory=_inv(1), reads=(PageRead(1, page=_page(tables=())),))
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("REFUSED", "not_a_transcript")
    assert _live(agency_a, paid_cycle_a) == []


def test_a_blank_page_is_skipped(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, upload, content, inventory=_inv(1, 2),
         reads=(PageRead(1, page=_page()), PageRead(2, blank=True)))
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0), (2, "SKIPPED", "", 0)]


def test_a_translations_original_language_pages_are_skipped(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a, role="TRANSLATION")
    azerbaijani = _page(lines=("Fənnin adı Qiymət Kredit Məmmədova Əliyev Şəki",),
                        tables=((("Kimya", "6", "Əla"),),))
    _run(agency_a, upload, content, inventory=_inv(1, 2),
         reads=(PageRead(1, page=_page()), PageRead(2, page=azerbaijani)))
    with tenant_scope(agency_a.id):
        skipped = TranscriptPage.objects.get(slot=2)
        assert (skipped.state, skipped.skipped_because, skipped.page) == (
            "SKIPPED", "original_language", None,
        )


@pytest.mark.parametrize(("content", "reason"), [
    (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16, "heic"),
    (b"PK\x03\x04docx", "unsupported_file"),
    (b"%PDF" + b"\x00" * 10_000_001, "unsupported_file"),
])
def test_a_file_the_reader_cannot_take_is_refused_before_the_parser(agency_a, membership_a, paid_cycle_a, content, reason):
    upload, _ = _upload(agency_a, membership_a, paid_cycle_a)
    done, inv, _ = _run(agency_a, upload, content, inventory=(), reads=())
    assert done is False and inv.call_count == 0
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("REFUSED", reason)


def test_a_parser_refusal_refuses_the_upload(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", side_effect=PageRefused("low_resolution", 3)),
    ):
        assert read_upload(agency_a.id, upload.id) is False
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal, upload.refusal_page) == ("REFUSED", "low_resolution", 3)


def test_azure_down_delays_and_never_double_charges(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=OcrUnavailable("down")),
    ):
        assert read_upload(agency_a.id, upload.id) is False
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (upload.state, upload.attempts, paid_cycle_a.pages_used) == ("DELAYED", 1, 1)
        assert upload.next_attempt_at > timezone.now()
        TranscriptUpload.objects.filter(id=upload.id).update(next_attempt_at=timezone.now())
    _run(agency_a, upload, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 1


def test_a_delayed_upload_waits_for_its_time(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    delay(agency_a.id, upload.id, reason="test")
    done, inv, _ = _run(agency_a, upload, content, inventory=_inv(1), reads=())
    assert done is False and inv.call_count == 0


def test_delays_end_in_failure(agency_a, membership_a, paid_cycle_a):
    upload, _ = _upload(agency_a, membership_a, paid_cycle_a)
    for _ in range(MAX_ATTEMPTS):
        delay(agency_a.id, upload.id, reason="test")
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("FAILED", "reader_unavailable")


@override_settings(TRANSCRIPT_TENANT_DAILY_AZURE_PAGES=1)
def test_the_tenant_daily_ceiling_delays_rather_than_reads(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    second, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"2")
    done, _, read = _run(agency_a, second, content, inventory=_inv(1), reads=())
    assert done is False and read.call_count == 0
    with tenant_scope(agency_a.id):
        second.refresh_from_db()
        assert second.state == "DELAYED"


def test_a_closed_launch_gate_fails_the_upload_at_once(agency_a, membership_a, paid_cycle_a):
    from apps.documents.transcript import TranscriptReadingDisabled

    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    with patch("apps.documents.transcript_pages.check_gates", side_effect=TranscriptReadingDisabled("off")):
        assert read_upload(agency_a.id, upload.id) is False
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("FAILED", "reading_off")


def test_english_is_told_from_azerbaijani_turkish_and_russian():
    assert is_english(_page(lines=("Transcript of Records, Aysel Məmmədova",)))
    assert not is_english(_page(lines=("Fənnin adı Qiymət Əla Məmmədova",), tables=()))
    assert not is_english(_page(lines=("Dersin adı Başarı Notu Öğrenci Işık",), tables=()))
    assert not is_english(_page(lines=("Наименование дисциплины Оценка",), tables=()))
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_transcript_pages.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.transcript_pages'`.

- [ ] **Step 3: The setting**

In `config/settings/base.py`, beside the other `TRANSCRIPT_*` settings:

```python
#: Spec §7.1: Azure pages one tenant may have read in a UTC day; past it, readings wait (DELAYED)
#: rather than bill without bound. The value is open (spec §11) -- 2,000 pages is about $20.
TRANSCRIPT_TENANT_DAILY_AZURE_PAGES = int(os.environ.get("TRANSCRIPT_TENANT_DAILY_AZURE_PAGES", "2000"))
```

- [ ] **Step 4: Implement**

```python
# apps/documents/transcript_pages.py
"""A transcript is a set of pages (spec 2026-10-03 §3.1). Each upload is read once into
TranscriptPage rows -- the cache that keeps a redelivery, a retake of another page or a new
reading from re-reading or re-billing a page -- and charged to its cycle's allowance once.

Every slow step (the file download, the parser, Azure) runs outside a transaction; each write is
a short one under the tenant's RLS scope, with the cycle row locked where slots or the allowance
change, so two uploads finishing together cannot take the same slot or overspend the allowance.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.concierge.documents import ReadableObjectStore, open_document
from apps.concierge.models import StudentCycle
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant

from .azure_layout import AzureLayout, analyze_layout
from .models import TranscriptPage, TranscriptUpload
from .ocr import InventoryPage, OcrPage, PageRead, inventory, read_inventory
from .ocr_errors import OcrUnavailable, PageRefused
from .transcript import TranscriptReadingDisabled, check_gates

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10_000_000
#: Delays before an upload is FAILED: 5 min doubling to a 6-hour cap -- about two days in all.
MAX_ATTEMPTS = 12
_FIRST_DELAY = timedelta(minutes=5)
_LONGEST_DELAY = timedelta(hours=6)
#: The ISO-BMFF brands an iPhone photo carries at bytes 4-12 (HEIC/HEIF).
_HEIC_BRANDS = frozenset(
    {b"ftypheic", b"ftypheix", b"ftypheim", b"ftypheis", b"ftyphevc", b"ftypmif1", b"ftypmsf1"}
)
_NOT_ENGLISH = re.compile(r"[əğışƏĞİŞЀ-ӿ]")
_LETTER = re.compile(r"[^\W\d_]")

State = TranscriptUpload.State


class _Refused(Exception):
    def __init__(self, reason: str, page: int | None = None) -> None:
        super().__init__(reason)
        self.reason, self.page = reason, page


class _OverCeiling(Exception):
    pass


def is_english(page: OcrPage) -> bool:
    """A translation office's PDF often binds the English translation with a copy of the
    original (R5), whose pages are skipped. Azerbaijani and Turkish need ə ğ ı ş, Russian is
    Cyrillic: a page where those are more than 2% of its letters is not the translation. A name
    printed in Azerbaijani on an English page stays well under that."""
    text = " ".join([*page.lines, *(cell for table in page.tables for row in table for cell in row)])
    letters = len(_LETTER.findall(text))
    return letters == 0 or len(_NOT_ENGLISH.findall(text)) <= 0.02 * letters


def delay(tenant_id: UUID, upload_id: UUID, *, reason: str) -> None:
    """Azure or Jev did not answer, or the tenant's daily ceiling is reached (spec §4, §7.1): the
    upload waits and the resume sweep retries it -- after MAX_ATTEMPTS, it has FAILED. An upload
    whose pages are already written keeps READ and only waits for its reading to be assembled."""
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        upload = TranscriptUpload.objects.select_for_update().filter(id=upload_id).first()
        if upload is None or upload.state in (State.REFUSED, State.FAILED):
            return
        if upload.state == State.READ and upload.assembled:
            return
        upload.attempts += 1
        if upload.attempts >= MAX_ATTEMPTS:
            upload.state, upload.refusal, upload.next_attempt_at = State.FAILED, "reader_unavailable", None
        else:
            if upload.state != State.READ:
                upload.state = State.DELAYED
            upload.next_attempt_at = timezone.now() + min(
                _FIRST_DELAY * 2 ** (upload.attempts - 1), _LONGEST_DELAY
            )
        upload.save(update_fields=["state", "refusal", "attempts", "next_attempt_at", "updated_at"])
    logger.warning(
        "TranscriptDelayed upload=%s attempts=%s reason=%s", upload_id, upload.attempts, reason
    )


def read_upload(
    tenant_id: UUID,
    upload_id: UUID,
    *,
    store: ReadableObjectStore | None = None,
    analyze: Callable[..., AzureLayout] = analyze_layout,
) -> bool:
    """Read one upload into pages. True once its pages are written (now or before)."""
    upload = _claim(tenant_id, upload_id)
    if upload is None:
        return False
    if upload.state == State.READ:
        return True
    try:
        check_gates()
    except TranscriptReadingDisabled:
        _finish(tenant_id, upload.id, State.FAILED, "reading_off")
        return False
    try:
        _read(tenant_id, upload, store=store, analyze=analyze)
    except (_Refused, PageRefused) as refused:
        _finish(tenant_id, upload.id, State.REFUSED, refused.reason, refused.page)
        return False
    except (OcrUnavailable, _OverCeiling) as error:
        delay(tenant_id, upload.id, reason=type(error).__name__)
        return False
    return True


def _claim(tenant_id: UUID, upload_id: UUID) -> TranscriptUpload | None:
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        upload = (
            TranscriptUpload.objects.select_for_update(of=("self",))
            .select_related("document")
            .filter(id=upload_id)
            .first()
        )
        if upload is None or upload.state in (State.REFUSED, State.FAILED):
            return None
        due = upload.next_attempt_at is None or upload.next_attempt_at <= timezone.now()
        if not due:
            return None
        if upload.state != State.READ:
            upload.state = State.READING
            upload.save(update_fields=["state", "updated_at"])
        return upload


def _finish(tenant_id: UUID, upload_id: UUID, state: str, refusal: str, page: int | None = None) -> None:
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        TranscriptUpload.objects.filter(id=upload_id).update(
            state=state, refusal=refusal, refusal_page=page, next_attempt_at=None,
            updated_at=timezone.now(),
        )
    logger.warning("TranscriptUpload%s upload=%s reason=%s", state.title(), upload_id, refusal)


def _read(
    tenant_id: UUID,
    upload: TranscriptUpload,
    *,
    store: ReadableObjectStore | None,
    analyze: Callable[..., AzureLayout],
) -> None:
    content = open_document(upload.document, store=store)
    if len(content) > MAX_UPLOAD_BYTES:
        raise _Refused("unsupported_file")
    if content[4:12] in _HEIC_BRANDS:
        raise _Refused("heic")
    if not content.startswith((b"%PDF", b"\x89PNG", b"\xff\xd8\xff")):
        raise _Refused("unsupported_file")
    digest = hashlib.sha256(content).hexdigest()
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        TranscriptUpload.objects.filter(id=upload.id).update(file_sha256=digest)
        duplicate = TranscriptPage.objects.filter(
            cycle_id=upload.cycle_id, upload__file_sha256=digest, superseded_at__isnull=True
        ).exists()
    if duplicate:
        if upload.mode == TranscriptUpload.Mode.RETAKE:
            raise _Refused("same_file")
        _write(tenant_id, upload, ())  # the same file again: nothing read, nothing charged
        return
    pages = inventory(upload.document, content)
    if upload.mode == TranscriptUpload.Mode.RETAKE and len(pages) != 1:
        raise _Refused("retake_one_page")
    _reserve(tenant_id, upload.id, len(pages))
    _check_ceiling(tenant_id, pages)
    _write(tenant_id, upload, read_inventory(content, pages, locale=upload.language or None, analyze=analyze))


def _reserve(tenant_id: UUID, upload_id: UUID, count: int) -> None:
    """Charge the pages to the cycle once (spec §7.1): a redelivery finds pages_counted set."""
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        upload = TranscriptUpload.objects.select_for_update().get(id=upload_id)
        if upload.pages_counted is not None:
            return
        cycle = StudentCycle.objects.select_for_update().get(id=upload.cycle_id)
        left = settings.TRANSCRIPT_PAGES_PER_CYCLE - cycle.pages_used
        if count > left:
            raise _Refused("allowance_exceeded", max(left, 0))
        cycle.pages_used += count
        cycle.save(update_fields=["pages_used"])
        upload.pages_counted = count
        upload.save(update_fields=["pages_counted", "updated_at"])


def _check_ceiling(tenant_id: UUID, pages: tuple[InventoryPage, ...]) -> None:
    wanted = sum(1 for page in pages if page.source == "image")
    if not wanted:
        return
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        used = TranscriptPage.objects.filter(source="azure", created_at__gte=midnight).count()
    if used + wanted > settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES:
        raise _OverCeiling()


def _fields(read: PageRead, role: str) -> dict[str, object]:
    azure = {"source": "azure", "api_version": settings.AZURE_DI_API_VERSION}
    if read.blank:
        return {"state": TranscriptPage.State.SKIPPED, "skipped_because": "blank", **azure}
    if read.page is None:
        return {"state": TranscriptPage.State.REFUSED, "refusal": read.refusal or "", **azure}
    origin = {"source": read.page.source, "api_version": read.page.api_version}
    if role == TranscriptUpload.Role.TRANSLATION and not is_english(read.page):
        return {"state": TranscriptPage.State.SKIPPED, "skipped_because": "original_language", **origin}
    return {"state": TranscriptPage.State.READ, "page": read.page.model_dump(mode="json"), **origin}


def _write(tenant_id: UUID, upload: TranscriptUpload, reads: tuple[PageRead, ...]) -> None:
    now = timezone.now()
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        cycle = StudentCycle.objects.select_for_update().get(id=upload.cycle_id)  # serialises slots
        fresh = TranscriptUpload.objects.select_for_update().get(id=upload.id)
        if fresh.state == State.READ:
            return
        live = TranscriptPage.objects.filter(cycle=cycle, superseded_at__isnull=True)
        if reads and not any(read.page is not None and read.page.tables for read in reads) and (
            fresh.mode == TranscriptUpload.Mode.REPLACE
            or not any(page.page and page.page.get("tables") for page in live.filter(state="READ"))
        ):
            raise _Refused("not_a_transcript", 1)
        retakes = 0
        if fresh.mode == TranscriptUpload.Mode.REPLACE:
            live.update(superseded_at=now)
            first = 1
        elif fresh.mode == TranscriptUpload.Mode.RETAKE:
            old = live.filter(slot=fresh.retake_slot).first()
            if old is None:
                raise _Refused("slot_not_found")
            if old.retakes >= settings.TRANSCRIPT_MAX_RETAKES:
                raise _Refused("retakes_used")
            old.superseded_at = now
            old.save(update_fields=["superseded_at"])
            first, retakes = old.slot, old.retakes + 1
        else:
            first = (live.aggregate(last=Max("slot"))["last"] or 0) + 1
        for offset, read in enumerate(reads):
            TranscriptPage.objects.create(
                student_id=fresh.student_id, cycle=cycle, upload=fresh, number=read.number,
                slot=first + offset, retakes=retakes, **_fields(read, fresh.role),
            )
        fresh.state, fresh.refusal, fresh.next_attempt_at = State.READ, "", None
        fresh.save(update_fields=["state", "refusal", "next_attempt_at", "updated_at"])
```

`_Refused` raised inside `_write`'s transaction rolls the transaction back, so no slot changes. `read_upload` then records the refusal in its own short transaction. The allowance stays charged, because the pages were read; that matches spec §7.1.

- [ ] **Step 5: Run the tests**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_transcript_pages.py -q && uv run ruff check . && uv run mypy apps config`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents/transcript_pages.py config/settings/base.py tests/documents/test_transcript_pages.py
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(documents): read an upload once into pages -- allowance, cache, retakes, translations, delays

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Assembling the reading, and the worker

**Files:**
- Modify: `apps/documents/transcript_pages.py` (`assemble`, `process_upload`)
- Modify: `apps/documents/document_worker.py` (`handle_scan_result`, `mark_read_failed`, `_read_transcript`)
- Test: `tests/documents/test_transcript_pages.py` (assembly cases), `tests/documents/test_transcript_worker.py` (rewritten onto uploads)

**Interfaces:**
- Consumes:
  - `read_upload` and `delay` (Task 7);
  - `read_from_pages` and `personal_names` (`apps.documents.transcript`);
  - `academic_record`, `highlights` and `key_numbers`, exactly as the worker uses them today.
- Produces:
  - `assemble(tenant_id: UUID, upload_id: UUID, *, client: Client | None = None) -> None`.
  - `process_upload(tenant_id: UUID, upload_id: UUID, *, store=None, analyze=analyze_layout, client=None) -> None`, which runs `read_upload` and then `assemble`.
  - The worker calls `process_upload` for every clean transcript.
  - On the last failed delivery, `mark_read_failed` delays the upload instead of failing it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/documents/test_transcript_pages.py`:

```python
from apps.documents.models import TranscriptReading
from apps.documents.transcript_pages import assemble, process_upload
from apps.research.decisions import DecisionsUnavailable


def _reading():
    from datetime import date

    from apps.documents.transcript import Reading, Row, TranscriptContent, TranscriptCourse

    return Reading(
        content=TranscriptContent(
            institution="Baku State University", country_code="AZ", qualification="BSc",
            field="Chemistry", credit_unit="ECTS",
            courses=(TranscriptCourse(title="Organic Chemistry I", credits=6, status="COMPLETED"),),
            expected_completion=date(2027, 6, 30),
        ),
        rows=(Row(0, "course", "Organic Chemistry I", "6", "91", "COMPLETED"),),
        total_credits_line=None,
        doubts=(),
    )


def _read_all(agency, membership, cycle, *uploads):
    """Write pages for each (fields, reads) without assembling."""
    made = []
    for n, (fields, reads) in enumerate(uploads):
        upload, content = _upload(agency, membership, cycle, content=PNG + bytes([n]), **fields)
        _run(agency, upload, content, inventory=_inv(*range(1, len(reads) + 1)), reads=reads)
        made.append(upload)
    return made


def test_a_reading_is_assembled_from_live_read_pages_in_slot_order(agency_a, membership_a, paid_cycle_a):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a,
                         ({}, (PageRead(1, page=_page()), PageRead(2, page=_page(lines=("p2",))))))
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()) as read:
        assemble(agency_a.id, upload.id)
    pages = read.call_args.args[0]
    assert [page.lines for page in pages] == [("Transcript of Records",), ("p2",)]
    with tenant_scope(agency_a.id):
        reading = TranscriptReading.objects.get(document=upload.document)
        upload.refresh_from_db()
        assert (reading.cycle_id, upload.assembled) == (paid_cycle_a.id, True)


def test_a_page_waiting_for_its_retake_holds_the_reading_back(agency_a, membership_a, paid_cycle_a):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a,
                         ({}, (PageRead(1, page=_page()), PageRead(2, refusal="cut_off"))))
    with patch("apps.documents.transcript_pages.read_from_pages") as read:
        assemble(agency_a.id, upload.id)
    read.assert_not_called()
    with tenant_scope(agency_a.id):
        assert not TranscriptReading.objects.exists()


def test_a_page_out_of_retakes_no_longer_holds_it_back(agency_a, membership_a, paid_cycle_a):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a,
                         ({}, (PageRead(1, page=_page()), PageRead(2, refusal="cut_off"))))
    with tenant_scope(agency_a.id):
        TranscriptPage.objects.filter(slot=2).update(retakes=2)
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()) as read:
        assemble(agency_a.id, upload.id)
    assert len(read.call_args.args[0]) == 1


def test_an_upload_still_reading_holds_it_back_but_an_abandoned_one_does_not(agency_a, membership_a, paid_cycle_a):
    [read_one] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    abandoned, _ = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"x")  # PENDING forever
    busy, _ = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"y")
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=busy.id).update(state="READING")
    with patch("apps.documents.transcript_pages.read_from_pages") as read:
        assemble(agency_a.id, read_one.id)
    read.assert_not_called()
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=busy.id).update(state="REFUSED")
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()) as read:
        assemble(agency_a.id, read_one.id)
    read.assert_called_once()


def test_once_a_translation_is_read_only_translation_pages_are_used(agency_a, membership_a, paid_cycle_a):
    original, translation = _read_all(
        agency_a, membership_a, paid_cycle_a,
        ({}, (PageRead(1, page=_page(lines=("original",))),)),
        ({"role": "TRANSLATION"}, (PageRead(1, page=_page(lines=("translation",))),)),
    )
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()) as read:
        assemble(agency_a.id, translation.id)
    assert [page.lines for page in read.call_args.args[0]] == [("translation",)]


def test_jev_down_after_pages_are_written_delays_the_assembly_only(agency_a, membership_a, paid_cycle_a):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    with patch("apps.documents.transcript_pages.read_from_pages", side_effect=DecisionsUnavailable("down")):
        assemble(agency_a.id, upload.id)
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.assembled, upload.attempts) == ("READ", False, 1)
```

In `tests/documents/test_transcript_worker.py`, rewrite the transcript cases onto uploads:
- Each test creates its transcript through a `TranscriptUpload` (role ORIGINAL, cycle `paid_cycle_a`).
- It patches `apps.documents.document_worker.process_upload` (to assert the worker hands over) or the `transcript_pages` seams (for end-to-end cases).

Keep these cases:
- **A redelivered scan event runs `process_upload` again and it reads nothing** (Review Focus 2): patch `transcript_pages.inventory`, `read_inventory` and `read_from_pages`. Call `handle_scan_result` twice. Assert `inventory.call_count == 1` and `read_from_pages.call_count == 1`, the allowance is charged once, and exactly one `TranscriptReading` exists.
- A transcript `DocumentVersion` with no `TranscriptUpload` (registered outside the API) is marked `READ_FAILED` and never read.
- **The last failed delivery delays.** On the last delivery, `mark_read_failed` turns a READING upload into `DELAYED` with `attempts == 1`, never `READ_FAILED`. A CV is not touched.
- **Closed launch gate.** The upload ends `FAILED`/`reading_off` without crashing (the old `TranscriptReadingDisabled` case, moved).

Delete every remaining worker test of the old `read_transcript` seam.

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_transcript_pages.py tests/documents/test_transcript_worker.py -q`
Expected: FAIL with `ImportError: cannot import name 'assemble'`.

- [ ] **Step 3: Assembly**

Add to `apps/documents/transcript_pages.py`:

```python
from dataclasses import asdict

from apps.research.decisions import Client, DecisionsUnavailable

from .models import TranscriptReading
from .transcript import academic_record, personal_names, read_from_pages
from .transcript_checks import highlights, key_numbers


def assemble(tenant_id: UUID, upload_id: UUID, *, client: Client | None = None) -> None:
    """Rebuild the cycle's reading from its live pages, unless the transcript is not ready.

    Not ready means another upload of the cycle is still being read or waiting on Azure, or a
    refused page still has a retake left. The upload that finishes last assembles: each writes
    READ before it looks, so two finishing together both see the other done, and the cost of
    that race is one extra reading -- the newest is the student's. An upload registered and never
    sent stays PENDING and holds nothing back.
    """
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        upload = TranscriptUpload.objects.select_related("student").get(id=upload_id)
        busy = (
            TranscriptUpload.objects.filter(cycle_id=upload.cycle_id, state__in=(State.READING, State.DELAYED))
            .exclude(id=upload.id)
            .exists()
        )
        live = list(
            TranscriptPage.objects.filter(cycle_id=upload.cycle_id, superseded_at__isnull=True)
            .select_related("upload")
            .order_by("slot")
        )
        names = personal_names(upload.student)
    waiting = any(
        page.state == TranscriptPage.State.REFUSED and page.retakes < settings.TRANSCRIPT_MAX_RETAKES
        for page in live
    )
    readable = [page for page in live if page.state == TranscriptPage.State.READ]
    if any(page.upload.role == TranscriptUpload.Role.TRANSLATION for page in readable):
        readable = [page for page in readable if page.upload.role == TranscriptUpload.Role.TRANSLATION]
    if busy or waiting or not readable:
        _assembled(tenant_id, upload.id)
        return
    try:
        reading = read_from_pages(
            tuple(OcrPage.model_validate(page.page) for page in readable), names, client=client
        )
    except DecisionsUnavailable:
        delay(tenant_id, upload.id, reason="DecisionsUnavailable")
        return
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        TranscriptReading.objects.get_or_create(
            document_id=upload.document_id,
            defaults={
                "student_id": upload.student_id,
                "cycle_id": upload.cycle_id,
                "record": academic_record(reading.content),
                "highlights": [highlight.model_dump() for highlight in highlights(reading)],
                "key_numbers": key_numbers(reading).model_dump(mode="json"),
                "rows": [asdict(row) for row in reading.rows],
            },
        )
        TranscriptUpload.objects.filter(id=upload.id).update(
            assembled=True, next_attempt_at=None, updated_at=timezone.now()
        )


def _assembled(tenant_id: UUID, upload_id: UUID) -> None:
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        TranscriptUpload.objects.filter(id=upload_id).update(
            assembled=True, next_attempt_at=None, updated_at=timezone.now()
        )


def process_upload(
    tenant_id: UUID,
    upload_id: UUID,
    *,
    store: ReadableObjectStore | None = None,
    analyze: Callable[..., AzureLayout] = analyze_layout,
    client: Client | None = None,
) -> None:
    """Read one upload into pages, then rebuild the cycle's reading. Safe to run again: pages are
    never read twice, the allowance is never charged twice, and a reading is one per upload."""
    if read_upload(tenant_id, upload_id, store=store, analyze=analyze):
        with tenant_scope(tenant_id), transaction.atomic():
            set_local_tenant(tenant_id)
            done = TranscriptUpload.objects.filter(id=upload_id, assembled=True).exists()
        if not done:
            assemble(tenant_id, upload_id, client=client)
```

If importing `transcript_checks` or `transcript` here makes an import cycle, move the imports inside the function and say so.

- [ ] **Step 4: The worker**

In `apps/documents/document_worker.py`:
- **In `handle_scan_result`**, replace everything from `if TranscriptReading.objects.filter(document=document).exists():` to the end with:

```python
        upload = TranscriptUpload.objects.filter(document=document).values_list("id", flat=True).first()
        if upload is None:
            # Registered outside the upload API, so no cycle was ever checked as paid (R13).
            logger.warning("TranscriptWithoutUpload document=%s", document.id)
            document.state = "READ_FAILED"
            document.save(update_fields=["state"])
            return
    process_upload(tenant_id, upload)
```

- **Replace `mark_read_failed`'s transcript update** with a delay. `process_upload` raised on the last delivery, so the sweep takes it from here:

```python
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        upload = TranscriptUpload.objects.filter(document__object_key=event.object_key).values_list("id", flat=True).first()
    if upload is not None:
        delay(tenant_id, upload, reason="last_delivery")
```

- **Rewrite its docstring:** the last delivery's failure leaves the upload DELAYED for the resume sweep, which fails it after `MAX_ATTEMPTS`.
- **Delete `_read_transcript`** and the imports only it used: `read_transcript`, `TranscriptRateLimited`, `PageRefused`, `academic_record`, `highlights`, `key_numbers`, `asdict` and `personal_names`, unless something else in the module uses them.
- **Delete the old file path** now that nothing calls it:
  - in `apps/documents/transcript.py`: `read_transcript`, `_MAX_UPLOAD_BYTES`, `_RATE_LIMIT`, `_RATE_WINDOW_SECONDS`, `TranscriptRateLimited`, and the imports only they used;
  - in `apps/documents/ocr.py`: `read_pages`.
  - The 50-page allowance replaces the hourly limit (spec §7.1). Tests of the file checks already exist in `test_transcript_pages.py` (Task 7). Delete the `read_transcript` tests in `test_transcript.py`, keeping the gate tests by pointing them at `check_gates()`.
  - Point `tests/documents/test_transcript_live.py` at `ocr.inventory`, `ocr.read_inventory` and `read_from_pages`; its spy wraps `ocr.read_inventory`.
  - Then `grep -rn "read_pages\|read_transcript\|TranscriptRateLimited" apps tests` prints nothing.
- **Update the module docstring's ponytail paragraph:** the transcript path runs in `transcript_pages.process_upload`, in short transactions around each slow step.

- [ ] **Step 5: Run the tests**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents tests/accounts -q && uv run ruff check . && uv run mypy apps config`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents tests/documents
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(documents): the worker reads uploads into pages and assembles the cycle's reading

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The resume sweep and its schedule

**Files:**
- Create: `apps/documents/management/commands/resume_transcript_readings.py`
- Modify: `config/settings/base.py` (`TRANSCRIPT_STUCK_AFTER_MINUTES`)
- Modify: `infra/template.yaml` (`TranscriptResumeRule`)
- Modify: `docs/runbooks/deploy.md`
- Test: `tests/documents/test_resume_transcript_readings.py`, `tests/infra/test_template.py`

**Interfaces:**
- Consumes: `process_upload` and `delay` (Tasks 7–8).
- Produces:
  - `manage.py resume_transcript_readings`, which retries, per agency:
    - DELAYED uploads that are due;
    - READ but unassembled uploads that are due, or stuck;
    - READING uploads stuck longer than `TRANSCRIPT_STUCK_AFTER_MINUTES` (30), which closes the dead-letter gap of spec §7.1;
    - PENDING uploads whose file was scanned clean and that are stuck (a lost scan message).
  - An EventBridge rule runs it every 15 minutes on `DocumentWorkerTaskDefinition`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_resume_transcript_readings.py
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.concierge.documents import register
from apps.documents.models import TranscriptUpload
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _upload(agency, membership, cycle, **fields):
    document = register(agency.id, membership.id, kind="TRANSCRIPT")
    with tenant_scope(agency.id):
        document.state = fields.pop("document_state", "AVAILABLE")
        document.save(update_fields=["state"])
        upload = TranscriptUpload.objects.create(
            student=membership, cycle=cycle, document=document, role="ORIGINAL", **fields
        )
        if "updated_at" in fields:
            TranscriptUpload.objects.filter(id=upload.id).update(updated_at=fields["updated_at"])
    return upload


def _sweep():
    with patch("apps.documents.management.commands.resume_transcript_readings.process_upload") as run:
        call_command("resume_transcript_readings", stdout=StringIO())
    return {call.args[1] for call in run.call_args_list}


def test_due_delayed_stuck_and_lost_uploads_are_resumed_and_nothing_else(agency_a, membership_a, paid_cycle_a):
    now, old = timezone.now(), timezone.now() - timedelta(hours=2)
    due = _upload(agency_a, membership_a, paid_cycle_a, state="DELAYED", next_attempt_at=now - timedelta(minutes=1))
    not_yet = _upload(agency_a, membership_a, paid_cycle_a, state="DELAYED", next_attempt_at=now + timedelta(hours=1))
    stuck = _upload(agency_a, membership_a, paid_cycle_a, state="READING", updated_at=old)
    busy = _upload(agency_a, membership_a, paid_cycle_a, state="READING")
    lost = _upload(agency_a, membership_a, paid_cycle_a, state="PENDING", updated_at=old)
    unsent = _upload(agency_a, membership_a, paid_cycle_a, state="PENDING", updated_at=old, document_state="QUARANTINED")
    unassembled = _upload(agency_a, membership_a, paid_cycle_a, state="READ", updated_at=old)
    done = _upload(agency_a, membership_a, paid_cycle_a, state="READ", assembled=True, updated_at=old)
    refused = _upload(agency_a, membership_a, paid_cycle_a, state="REFUSED", updated_at=old)
    assert _sweep() == {due.id, stuck.id, lost.id, unassembled.id}


def test_one_upload_crashing_does_not_stop_the_rest_and_is_delayed(agency_a, membership_a, paid_cycle_a):
    old = timezone.now() - timedelta(hours=2)
    first = _upload(agency_a, membership_a, paid_cycle_a, state="READING", updated_at=old)
    second = _upload(agency_a, membership_a, paid_cycle_a, state="READING", updated_at=old)
    calls = []

    def run(tenant_id, upload_id, **kwargs):
        calls.append(upload_id)
        if len(calls) == 1:
            raise RuntimeError("boom")

    with patch("apps.documents.management.commands.resume_transcript_readings.process_upload", side_effect=run):
        call_command("resume_transcript_readings", stdout=StringIO())
    assert set(calls) == {first.id, second.id}
    with tenant_scope(agency_a.id):
        crashed = TranscriptUpload.objects.get(id=calls[0])
        assert crashed.attempts == 1
```

In `tests/infra/test_template.py`:

```python
def test_the_transcript_resume_sweep_runs_every_fifteen_minutes_with_the_azure_key(template):
    rule = template["Resources"]["TranscriptResumeRule"]["Properties"]
    assert rule["ScheduleExpression"] == "rate(15 minutes)" and rule["State"] == "ENABLED"
    [target] = rule["Targets"]
    assert target["EcsParameters"]["TaskDefinitionArn"] == {"Ref": "DocumentWorkerTaskDefinition"}
    assert "resume_transcript_readings" in str(target["Input"])
```

Use the module's own template fixture and its existing loader's names.

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_resume_transcript_readings.py tests/infra/test_template.py -q`
Expected: FAIL (unknown command; no `TranscriptResumeRule`).

- [ ] **Step 3: Implement**

`config/settings/base.py`:

```python
#: Spec §7.1: an upload still READING (or scanned clean and never picked up) this long after its
#: last write was lost with a killed worker; the resume sweep takes it up again.
TRANSCRIPT_STUCK_AFTER_MINUTES = 30
```

```python
# apps/documents/management/commands/resume_transcript_readings.py
"""Resume transcript readings that are waiting or were lost (spec 2026-10-03 §4, §7.1).

Run every 15 minutes by TranscriptResumeRule (infra/template.yaml) on the document worker's task
definition -- the only one holding the Azure key. Picks up, per agency: DELAYED uploads now due,
pages written but never assembled into a reading, uploads stuck READING past the timeout (the
worker died mid-read: the dead-letter gap), and clean-scanned uploads never picked up (a lost
scan message). Each runs alone; one that raises is delayed, so it fails for good after
MAX_ATTEMPTS instead of being retried forever.
"""

import logging
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.documents.models import TranscriptUpload
from apps.documents.transcript_pages import delay, process_upload
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency

logger = logging.getLogger(__name__)

#: Per agency per run: a burst waits for the next run rather than one run outliving the next.
_BATCH = 200


class Command(BaseCommand):
    help = "Resume delayed, stuck and unassembled transcript readings"

    def handle(self, *args: object, **options: object) -> None:
        # Agency carries no RLS policy, so listing it works from the runtime role (the same
        # loop execute_due_erasures uses); every query below runs in that agency's own scope.
        for agency in Agency.objects.all():
            for upload_id in _due(agency.id):
                try:
                    process_upload(agency.id, upload_id)
                except Exception as error:  # one upload must not strand the batch
                    logger.warning(
                        "TranscriptResumeFailed upload=%s error=%s", upload_id, type(error).__name__
                    )
                    delay(agency.id, upload_id, reason=type(error).__name__)


def _due(tenant_id: UUID) -> list[UUID]:
    now = timezone.now()
    stuck = now - timedelta(minutes=settings.TRANSCRIPT_STUCK_AFTER_MINUTES)
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        return list(
            TranscriptUpload.objects.filter(
                Q(state="DELAYED", next_attempt_at__lte=now)
                | Q(state="READ", assembled=False, next_attempt_at__lte=now)
                | Q(state="READ", assembled=False, next_attempt_at__isnull=True, updated_at__lt=stuck)
                | Q(state="READING", updated_at__lt=stuck)
                | Q(state="PENDING", document__state="AVAILABLE", updated_at__lt=stuck)
            )
            .order_by("updated_at")
            .values_list("id", flat=True)[:_BATCH]
        )
```

`infra/template.yaml`: add `TranscriptResumeRule` after `EuropassCanaryRule`, modelled on it. It has:
- `ScheduleExpression: "rate(15 minutes)"`, `State: ENABLED`.
- `TaskDefinitionArn: !Ref DocumentWorkerTaskDefinition`, on the cluster `DocumentWorkerService` runs in (`!GetAtt ValidationCluster.Arn`).
- `RoleArn: !GetAtt EventsInvokeEcsRole.Arn`.
- The worker subnets and `WorkerSecurityGroup`.
- An `Input` command override `["python","manage.py","resume_transcript_readings"]` naming the document worker's container. Read its `Name` from `DocumentWorkerTaskDefinition`.

Check that `EventsInvokeEcsRole`'s `ecs:RunTask` and `iam:PassRole` resources cover `DocumentWorkerTaskDefinition` and its roles. If they list task definitions one by one, add this one, and assert it in the infra test.

Comment it like `ReminderLadderRule`: shipped enabled, because a sweep nothing invokes leaves a delayed reading "still reading" forever.

- [ ] **Step 4: Run the tests and lint the template**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_resume_transcript_readings.py tests/infra -q && uv run cfn-lint infra/template.yaml`
Expected: PASS, cfn-lint clean.

- [ ] **Step 5: The runbook line**

Append to `docs/runbooks/deploy.md`:

"**Transcript readings resume themselves.** `TranscriptResumeRule` runs `manage.py resume_transcript_readings` every 15 minutes on the document worker's task definition. It retries readings delayed by an Azure outage or by the per-tenant daily ceiling (`TRANSCRIPT_TENANT_DAILY_AZURE_PAGES`, default 2,000). It also retries readings lost with a killed worker. After 12 attempts (about two days) an upload is FAILED with `reader_unavailable`."

- [ ] **Step 6: The full gate**

Run: `cd /home/orkhan/Desktop/transcript-redesign && unset VIRTUAL_ENV; uv run ruff check . && uv run mypy apps config && POSTGRES_DB=tehsil_transcript uv run pytest -q && uv run python manage.py makemigrations --check --dry-run && uv run bandit -c pyproject.toml -r apps config`
Expected: every command clean.

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents/management config/settings/base.py infra/template.yaml docs/runbooks/deploy.md tests
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(documents): a 15-minute sweep resumes delayed, stuck and unassembled transcript readings

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
