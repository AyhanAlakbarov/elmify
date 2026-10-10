# Reminder Ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remind a student at 14 days, 7 days, 3 days, 1 day and 6 hours before an application deadline — on the dashboard, by email, and (inside 24 hours) by a counselor task saying to message them on WhatsApp — stopping the moment the application is submitted.

**Architecture:** One pure-logic module (`apps/portals/reminders.py`) decides which rung is owed and whether the student's quiet hours block it; one management command drives it per tenant on an hourly EventBridge schedule. A `ReminderSent` row per (application, rung) makes the sweep idempotent through a unique constraint rather than a read-then-write check. The sweep lives in `apps/portals/`, never `apps/concierge/` — that module's docstring guarantees every action in it is a human-recorded fact and `tests/concierge/test_roadmap.py::test_no_payment_or_portal_automation_call` enforces it.

**Tech Stack:** Django 5, Postgres 17 with row-level security, `uv` for every command, pytest, CloudFormation (`infra/template.yaml`).

**Spec:** `docs/superpowers/specs/2026-09-19-reminder-ladder-design.md`

## Global Constraints

- **Run the suite against this worktree's own database: `POSTGRES_DB=tehsil_mailbox uv run pytest -q`.** `config/settings/database.py` defaults `POSTGRES_DB` to `"tehsil"`, so every worktree otherwise shares one `test_tehsil` and concurrent sessions kill each other's runs.
- Every command runs through `uv run`. Never invoke `pytest`, `python`, `ruff` or `mypy` directly.
- **Never run `uv run ruff format` on a directory or on a pre-existing file.** ruff 0.16.6 rewrites this repo's `except (A, B, C):` tuples into invalid Python, and nothing in CI runs the formatter, so there is nothing to conform to. Format only a brand-new file you wrote, then confirm it still parses.
- Run `uv run ruff check`, `uv run mypy` and `uv run bandit -c pyproject.toml -r apps config` before each commit.
- Python, ruff, mypy, CI and the Dockerfile must all name the same major.minor version. Do not change any of them in this plan.
- Tenant-scoped reads must happen inside `tenant_transaction(tenant_id)` (`apps.tenancy.db`), which issues the `SET LOCAL app.tenant_id` that row-level security compares against. A read outside one returns zero rows in production and passes in tests, because the test role is `BYPASSRLS`.
- Every new tenant table needs its RLS policy and composite tenant foreign keys written by hand in the migration. Django's autodetector writes neither.
- Every new field on a student-reachable model is classified in `apps/audit/redaction.py` in the same change that adds it.
- No new dependency is added by this plan.
- Never log a student value, an email address, or a deadline tied to a named person.

---

### Task 1: `ReminderSent`, the rung enum, and the application's reminder item

**Files:**
- Modify: `apps/portals/models.py` (add to the end; `Application` gains one field near `exception_item` at line 224)
- Create: `apps/portals/migrations/0014_reminder_ladder.py`
- Test: `tests/portals/test_reminder_model.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `portals.models.Rung` (a `TextChoices` with members `D14`, `D7`, `D3`, `D1`, `H6`), `portals.models.ReminderSent` (fields `id`, `tenant`, `application`, `rung`, `sent_at`), and `Application.reminder_item` (nullable FK to `concierge.RoadmapItem`).

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_reminder_model.py`:

```python
import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.portals.models import Application, PortalForm, ReminderSent, Rung
from apps.tenancy.context import tenant_scope


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


@pytest.fixture
def application(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        return Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
        )


def test_the_same_rung_cannot_be_recorded_twice(agency_a, application):
    with tenant_scope(agency_a.id):
        ReminderSent.objects.create(tenant=agency_a, application=application, rung=Rung.D7)
        with pytest.raises(IntegrityError), transaction.atomic():
            ReminderSent.objects.create(tenant=agency_a, application=application, rung=Rung.D7)


def test_two_different_rungs_on_one_application_are_fine(agency_a, application):
    with tenant_scope(agency_a.id):
        ReminderSent.objects.create(tenant=agency_a, application=application, rung=Rung.D7)
        ReminderSent.objects.create(tenant=agency_a, application=application, rung=Rung.D3)

        assert ReminderSent.objects.filter(application=application).count() == 2


def test_an_application_starts_with_no_reminder_item(application):
    assert application.reminder_item_id is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_reminder_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'ReminderSent' from 'apps.portals.models'`

- [ ] **Step 3: Add the model and the field**

In `apps/portals/models.py`, add `Rung` and `ReminderSent` at the end of the file:

```python
class Rung(models.TextChoices):
    """The five reminder points, named rather than numbered.

    A symbolic value, never a raw hour count: changing the cadence must not
    silently re-key the ReminderSent rows already written under the old one.
    """

    D14 = "D14", "14 days"
    D7 = "D7", "7 days"
    D3 = "D3", "3 days"
    D1 = "D1", "1 day"
    H6 = "H6", "6 hours"


class ReminderSent(TenantScopedModel):
    """One row per reminder actually delivered.

    The unique constraint is the idempotency mechanism, not an `.exists()`
    check in the sweep: the check races two sweeps against each other, the
    constraint cannot. It doubles as the record of what was sent when, which
    is what makes "was this student warned" answerable after a missed
    deadline.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="reminders_sent"
    )
    rung = models.CharField(max_length=4, choices=Rung.choices)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="remindersent_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "application", "rung"), name="remindersent_once_per_rung"
            ),
        ]
```

In `apps/portals/models.py`, immediately after the `exception_item` field on `Application` (line 226), add:

```python
    #: The roadmap item the reminder ladder hangs its notifications on, created
    #: on the first rung and reused by the rest. Separate from exception_item:
    #: that one means "blocked on a person", this one means "this is due".
    #: Nullable because most applications never reach a rung.
    reminder_item = models.ForeignKey(
        "concierge.RoadmapItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
```

- [ ] **Step 4: Generate the migration, then hand-write its RLS**

Run: `POSTGRES_DB=tehsil_mailbox uv run python manage.py makemigrations portals --name reminder_ladder`

Then edit `apps/portals/migrations/0014_reminder_ladder.py` so it reads as below, keeping the `CreateModel` and `AddField` operations the autodetector wrote and appending the two `RunSQL` operations. The RLS block is copied from `apps/mailbox/migrations/0001_initial.py`.

```python
#: The policy every tenant table in this repository carries. Generated
#: migrations create tables and constraints and none of this.
TABLES = ("portals_remindersent",)

RLS_SQL = "\n".join(
    f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON {table}
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """
    for table in TABLES
)

REVERSE_RLS_SQL = "\n".join(
    f"""
    DROP POLICY IF EXISTS tenant_isolation ON {table};
    ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
    """
    for table in reversed(TABLES)
)
```

Append these two operations to the migration's `operations` list, after the generated ones:

```python
        # The composite guard every tenant table here carries. Without it a row
        # may name an application in ANOTHER tenant, which the policy above
        # would then happily show to this one -- the policy checks the row's own
        # tenant_id, not its parent's.
        migrations.RunSQL(
            """
            ALTER TABLE portals_remindersent
                ADD CONSTRAINT remindersent_app_tenant_fk
                FOREIGN KEY (tenant_id, application_id)
                REFERENCES portals_application (tenant_id, id);
            """,
            """
            ALTER TABLE portals_remindersent DROP CONSTRAINT remindersent_app_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_reminder_model.py tests/tenancy/test_database_isolation.py -v`
Expected: PASS. The isolation suite is included because it is what proves the new table actually carries its policy.

- [ ] **Step 6: Check and commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
POSTGRES_DB=tehsil_mailbox uv run python manage.py makemigrations --check --dry-run
git add apps/portals/models.py apps/portals/migrations/0014_reminder_ladder.py tests/portals/test_reminder_model.py
git commit -m "feat(portals): a reminder is recorded once, by constraint"
```

---

### Task 2: The student's timezone and quiet hours

**Files:**
- Modify: `apps/tenancy/models.py` (the `Membership` model, after `academic_email` at line 100)
- Create: `apps/tenancy/migrations/0011_membership_quiet_hours.py`
- Modify: `apps/audit/redaction.py:125`
- Test: `tests/tenancy/test_quiet_hours_fields.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Membership.timezone` (`CharField`, blank when unknown, IANA name), `Membership.quiet_hours_start` and `Membership.quiet_hours_end` (nullable `TimeField`s), and `apps.tenancy.models.validate_timezone_name`.

- [ ] **Step 1: Write the failing test**

Create `tests/tenancy/test_quiet_hours_fields.py`:

```python
from datetime import time

import pytest
from django.core.exceptions import ValidationError

from apps.audit.redaction import REDACT
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import validate_timezone_name


def test_a_membership_starts_with_no_zone_and_no_quiet_hours(membership_a):
    assert membership_a.timezone == ""
    assert membership_a.quiet_hours_start is None
    assert membership_a.quiet_hours_end is None


def test_a_real_zone_validates():
    validate_timezone_name("Europe/Berlin")


def test_junk_in_the_timezone_field_is_refused():
    with pytest.raises(ValidationError):
        validate_timezone_name("Not/AZone")


def test_the_quiet_window_round_trips(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        membership_a.timezone = "Asia/Baku"
        membership_a.quiet_hours_start = time(22, 0)
        membership_a.quiet_hours_end = time(7, 0)
        membership_a.save(
            update_fields=["timezone", "quiet_hours_start", "quiet_hours_end"]
        )
        membership_a.refresh_from_db()

    assert membership_a.timezone == "Asia/Baku"
    assert membership_a.quiet_hours_start == time(22, 0)


def test_the_new_fields_are_classified_for_erasure():
    """A quiet window and a zone say when someone sleeps and where they live."""
    spec = REDACT["tenancy.Membership"]

    assert "timezone" in spec.fields
    assert "quiet_hours_start" in spec.fields
    assert "quiet_hours_end" in spec.fields
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/tenancy/test_quiet_hours_fields.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_timezone_name'`

- [ ] **Step 3: Add the validator and the three fields**

At the top of `apps/tenancy/models.py`, add to the imports:

```python
from zoneinfo import available_timezones
```

and `from django.core.exceptions import ValidationError` if it is not already imported.

Add the validator above the `Membership` class:

```python
def validate_timezone_name(value: str) -> None:
    """Refuse anything ZoneInfo cannot resolve.

    A trust boundary, not tidiness: the reminder sweep reads this field to
    decide whether a student is asleep, and an unresolvable name would raise
    inside a loop that is meant to serve every student in the tenant.
    """
    if value and value not in available_timezones():
        raise ValidationError(f"{value} is not an IANA time zone name")
```

In `Membership`, after `academic_email` (line 100):

```python
    #: IANA name, e.g. "Asia/Baku". Blank when unknown, which the reminder
    #: ladder reads as "no quiet hours" and sends on time -- degrading the
    #: other way, holding reminders until a zone is known, drops them silently.
    timezone = models.CharField(max_length=64, blank=True, validators=[validate_timezone_name])
    #: The window in which the ladder will not send. Both null means none.
    #: A window normally crosses midnight (22:00-07:00), which is why the
    #: comparison in reminders.in_quiet_hours is not a simple between.
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
```

In `apps/audit/redaction.py`, replace line 125 with:

```python
    "tenancy.Membership": RedactSpec(
        "id",
        ("application_email", "academic_email", "timezone", "quiet_hours_start", "quiet_hours_end"),
    ),
```

- [ ] **Step 4: Generate the migration**

Run: `POSTGRES_DB=tehsil_mailbox uv run python manage.py makemigrations tenancy --name membership_quiet_hours`

No hand-written SQL is needed: `tenancy_membership` is an existing table that already carries its policy, and these are plain column additions.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/tenancy/test_quiet_hours_fields.py tests/audit -v`
Expected: PASS. The audit suite is included because `tests/audit/test_redaction_classification.py` is what fails if a new student-reachable field is left unclassified.

- [ ] **Step 6: Check and commit**

```bash
uv run ruff check apps/tenancy apps/audit tests/tenancy
uv run mypy apps/tenancy apps/audit
git add apps/tenancy/models.py apps/tenancy/migrations/0011_membership_quiet_hours.py apps/audit/redaction.py tests/tenancy/test_quiet_hours_fields.py
git commit -m "feat(tenancy): a student has a zone and hours they are not disturbed in"
```

---

### Task 3: Which rung is owed, and whether the student is asleep

**Files:**
- Create: `apps/portals/reminders.py`
- Test: `tests/portals/test_reminder_logic.py`

**Interfaces:**
- Consumes: `portals.models.Rung` from Task 1.
- Produces, all pure functions with no database access:
  - `RUNG_LEAD: dict[Rung, timedelta]`
  - `COUNSELOR_RUNGS: frozenset[Rung]` — `{Rung.D1, Rung.H6}`
  - `due_rungs(deadline: datetime, now: datetime) -> tuple[Rung, ...]`
  - `owed_rung(due: Sequence[Rung], already_sent: Container[Rung]) -> Rung | None`
  - `in_quiet_hours(local: time, start: time | None, end: time | None) -> bool`
  - `remaining_phrase(remaining: timedelta) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_reminder_logic.py`:

```python
from datetime import datetime, time, timedelta, timezone as dt_timezone

from apps.portals.models import Rung
from apps.portals.reminders import (
    due_rungs,
    in_quiet_hours,
    owed_rung,
    remaining_phrase,
)

DEADLINE = datetime(2026, 12, 1, 12, 0, tzinfo=dt_timezone.utc)


def _at(**delta):
    return DEADLINE - timedelta(**delta)


def test_nothing_is_due_a_month_out():
    assert due_rungs(DEADLINE, _at(days=30)) == ()


def test_the_first_rung_opens_at_fourteen_days():
    assert due_rungs(DEADLINE, _at(days=14)) == (Rung.D14,)


def test_every_earlier_rung_stays_due():
    assert due_rungs(DEADLINE, _at(days=5)) == (Rung.D14, Rung.D7)


def test_the_last_rung_opens_at_six_hours():
    assert due_rungs(DEADLINE, _at(hours=6)) == (Rung.D14, Rung.D7, Rung.D3, Rung.D1, Rung.H6)


def test_a_passed_deadline_owes_nothing():
    """Not a missed-deadline notice -- that is a different feature nobody asked for."""
    assert due_rungs(DEADLINE, DEADLINE + timedelta(minutes=1)) == ()


def test_the_tightest_unsent_rung_is_the_one_owed():
    due = (Rung.D14, Rung.D7, Rung.D3)

    assert owed_rung(due, {Rung.D14}) == Rung.D3


def test_nothing_is_owed_once_every_due_rung_is_sent():
    assert owed_rung((Rung.D14, Rung.D7), {Rung.D14, Rung.D7}) is None


def test_no_window_means_never_quiet():
    assert in_quiet_hours(time(3, 0), None, None) is False


def test_a_window_that_crosses_midnight_covers_the_small_hours():
    """The normal case: 22:00-07:00. A plain between() is empty here."""
    assert in_quiet_hours(time(3, 0), time(22, 0), time(7, 0)) is True
    assert in_quiet_hours(time(23, 30), time(22, 0), time(7, 0)) is True
    assert in_quiet_hours(time(12, 0), time(22, 0), time(7, 0)) is False


def test_a_window_inside_one_day_also_works():
    assert in_quiet_hours(time(13, 30), time(13, 0), time(14, 0)) is True
    assert in_quiet_hours(time(15, 0), time(13, 0), time(14, 0)) is False


def test_the_phrase_counts_days_when_there_are_days_left():
    assert remaining_phrase(timedelta(days=3, hours=2)) == "3 days"


def test_the_phrase_counts_hours_inside_two_days():
    assert remaining_phrase(timedelta(hours=6)) == "6 hours"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_reminder_logic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.portals.reminders'`

- [ ] **Step 3: Write the module**

Create `apps/portals/reminders.py`:

```python
"""The reminder ladder's decisions, with no database and no side effects.

Everything here is a pure function so the awkward parts -- a quiet window that
crosses midnight, a rung that opens while the student is asleep -- can be
tested without a tenant, a transaction or a clock.

Design: docs/superpowers/specs/2026-09-19-reminder-ladder-design.md
"""

from __future__ import annotations

from collections.abc import Container, Sequence
from datetime import datetime, time, timedelta

from .models import Rung

#: How long before the deadline each rung opens. §8's cadence; the 1-hour rung
#: was dropped deliberately -- a failed upload cannot be recovered in an hour.
RUNG_LEAD: dict[Rung, timedelta] = {
    Rung.D14: timedelta(days=14),
    Rung.D7: timedelta(days=7),
    Rung.D3: timedelta(days=3),
    Rung.D1: timedelta(days=1),
    Rung.H6: timedelta(hours=6),
}

#: The rungs that also open a counselor task. Owner decision 2026-09-19, moved
#: in from §8's 3 days: three days out an automated reminder still has room to
#: work, inside 24 hours it does not.
COUNSELOR_RUNGS = frozenset({Rung.D1, Rung.H6})


def due_rungs(deadline: datetime, now: datetime) -> tuple[Rung, ...]:
    """Every rung whose lead time has been reached, widest first.

    Empty once the deadline has passed: "your deadline is in 6 hours" sent
    afterwards is worse than silence, and a missed-deadline notice is a
    different feature nobody has asked for.
    """
    if now >= deadline:
        return ()
    remaining = deadline - now
    return tuple(rung for rung in Rung if remaining <= RUNG_LEAD[rung])


def owed_rung(due: Sequence[Rung], already_sent: Container[Rung]) -> Rung | None:
    """The tightest due rung not yet sent, or None.

    Tightest rather than widest so an application that appears five days
    before its deadline gets one message saying five days, not a burst of
    every rung it slept through. The sweep records the whole `due` set as
    sent, so the ones passed over never fire later.
    """
    outstanding = [rung for rung in due if rung not in already_sent]
    return outstanding[-1] if outstanding else None


def in_quiet_hours(local: time, start: time | None, end: time | None) -> bool:
    """Whether `local` falls in the student's quiet window.

    A window normally crosses midnight (22:00-07:00), for which the test is
    `local >= start or local <= end`. The plain `start <= local <= end` is
    empty for every window anyone would actually set, which is the bug this
    function exists to not have.
    """
    if start is None or end is None:
        return False
    if start <= end:
        return start <= local <= end
    return local >= start or local <= end


def remaining_phrase(remaining: timedelta) -> str:
    """How long is left, in the units a person would say it in."""
    hours = int(remaining.total_seconds() // 3600)
    if hours >= 48:
        return f"{hours // 24} days"
    return f"{hours} hours"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_reminder_logic.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Check and commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
git add apps/portals/reminders.py tests/portals/test_reminder_logic.py
git commit -m "feat(portals): the ladder's arithmetic, including the window that crosses midnight"
```

---

### Task 4: The dashboard notification and the counselor's WhatsApp task

**Files:**
- Modify: `apps/portals/reminders.py`
- Test: `tests/portals/test_reminder_channels.py`

**Interfaces:**
- Consumes: `Rung`, `COUNSELOR_RUNGS`, `remaining_phrase` from Task 3; `Application.reminder_item` from Task 1.
- Produces:
  - `reminder_item(application: Application) -> RoadmapItem` — get-or-create, stored on `Application.reminder_item`
  - `notify_student(application: Application, item: RoadmapItem, remaining: timedelta) -> Notification`
  - `notify_counselor(application: Application, item: RoadmapItem, remaining: timedelta) -> Notification | None` — `None` when the student has no active counselor

Both writers assume the caller already holds the tenant transaction.

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_reminder_channels.py`:

```python
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.portals.models import Application, PortalForm
from apps.portals.reminders import notify_counselor, notify_student, reminder_item
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


@pytest.fixture
def application(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        return Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
            deadline=timezone.now() + timedelta(days=3),
            deadline_timezone="Europe/Berlin",
        )


def test_the_reminder_item_is_created_once_and_reused(agency_a, application):
    with tenant_scope(agency_a.id):
        first = reminder_item(application)
        second = reminder_item(application)

    assert first.id == second.id
    assert RoadmapItem.objects.filter(student=application.student).count() == 1
    application.refresh_from_db()
    assert application.reminder_item_id == first.id


def test_the_reminder_item_carries_the_portal_deadline(agency_a, application):
    with tenant_scope(agency_a.id):
        item = reminder_item(application)

    assert item.deadline == application.deadline
    assert item.stage == RoadmapItem.Stage.SUBMISSION


def test_the_student_is_told_how_long_is_left(agency_a, application):
    with tenant_scope(agency_a.id):
        item = reminder_item(application)
        note = notify_student(application, item, timedelta(days=3))

    assert note.recipient_id == application.student_id
    assert "3 days" in note.message
    assert "portal.example.test" in note.message


def test_the_counselor_is_asked_to_use_whatsapp(
    agency_a, application, counselor_membership
):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a,
            counselor=counselor_membership,
            student=application.student,
            active=True,
        )
        item = reminder_item(application)
        note = notify_counselor(application, item, timedelta(hours=6))

    assert note is not None
    assert note.recipient_id == counselor_membership.id
    assert "WhatsApp" in note.message
    assert note.roadmap_item_id == item.id


def test_a_student_with_no_counselor_gets_no_counselor_task(agency_a, application):
    """A direct-to-student account has nobody to hand the task to. Silence here
    is correct, and is stated in a test because it looks exactly like a bug."""
    with tenant_scope(agency_a.id):
        item = reminder_item(application)
        note = notify_counselor(application, item, timedelta(hours=6))

    assert note is None
    assert Notification.objects.filter(roadmap_item=item).count() == 0


def test_an_inactive_assignment_is_not_a_counselor(
    agency_a, application, counselor_membership
):
    """Same trap escalation.py records: the model keeps inactive rows, so
    dropping the filter routes a task to someone who left the agency."""
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a,
            counselor=counselor_membership,
            student=application.student,
            active=False,
        )
        item = reminder_item(application)

        assert notify_counselor(application, item, timedelta(hours=6)) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_reminder_channels.py -v`
Expected: FAIL — `ImportError: cannot import name 'notify_student' from 'apps.portals.reminders'`

- [ ] **Step 3: Add the two writers**

Add these imports to `apps/portals/reminders.py`, and **extend** the existing `from .models import Rung` line rather than adding a second one:

```python
from apps.concierge.models import Notification, RoadmapItem
from apps.tenancy.models import CounselorAssignment

from .models import Application, Rung  # was: from .models import Rung
```

Append to `apps/portals/reminders.py`:

```python
def reminder_item(application: Application) -> RoadmapItem:
    """The roadmap item every rung's notification hangs on, created on demand.

    One per application rather than one per rung: Notification.roadmap_item is
    not nullable, and five items for five reminders about one deadline is five
    rows on the dashboard saying the same thing. Its deadline is the portal's,
    so RoadmapItem.deadline_urgency colours it without the ladder saying
    anything.
    """
    if application.reminder_item is not None:
        return application.reminder_item
    item = RoadmapItem.objects.create(
        tenant=application.tenant,
        student=application.student,
        stage=RoadmapItem.Stage.SUBMISSION,
        owner=application.student,
        owner_kind=RoadmapItem.OwnerKind.HUMAN,
        deadline=application.deadline,
    )
    application.reminder_item = item
    application.save(update_fields=["reminder_item"])
    return item


def notify_student(
    application: Application, item: RoadmapItem, remaining: timedelta
) -> Notification:
    """Tell the student how long is left and where."""
    return Notification.objects.create(
        tenant=application.tenant,
        recipient=application.student,
        roadmap_item=item,
        message=(
            f"{application.portal_form.portal_host}: your application is due in "
            f"{remaining_phrase(remaining)}."
        ),
    )


def notify_counselor(
    application: Application, item: RoadmapItem, remaining: timedelta
) -> Notification | None:
    """Ask the counselor to reach the student on WhatsApp, or nobody.

    Returns None for a direct-to-student account, which has no counselor. That
    is the correct outcome and not a configuration error -- unlike
    escalation.py, which falls back to the student, because an escalation must
    reach somebody and this is a second copy of a message the student already
    has.
    """
    assignment = (
        # active=True, not merely assigned: the model keeps the inactive rows,
        # so dropping the filter routes the task to someone who has left.
        CounselorAssignment.objects.filter(student=application.student, active=True)
        .select_related("counselor")
        .first()
    )
    if assignment is None:
        return None
    return Notification.objects.create(
        tenant=application.tenant,
        recipient=assignment.counselor,
        roadmap_item=item,
        message=(
            f"{application.portal_form.portal_host}: due in {remaining_phrase(remaining)}. "
            "Message this student on WhatsApp now -- email will not reach them in time."
        ),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_reminder_channels.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Check and commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
git add apps/portals/reminders.py tests/portals/test_reminder_channels.py
git commit -m "feat(portals): the dashboard rung, and the counselor's WhatsApp task"
```

---

### Task 5: The email channel, shipped dormant

**Files:**
- Modify: `config/settings/base.py` (append, beside the other `os.getenv` settings)
- Modify: `apps/portals/reminders.py`
- Test: `tests/portals/test_reminder_email.py`

**Interfaces:**
- Consumes: `remaining_phrase` from Task 3.
- Produces: `settings.REMINDER_EMAIL_FROM` (empty string by default) and `email_student(application: Application, remaining: timedelta) -> bool` — `True` when a message was handed to Django's mail backend, `False` when the channel was skipped.

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_reminder_email.py`:

```python
import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.portals.models import Application, PortalForm
from apps.portals.reminders import email_student
from apps.tenancy.context import tenant_scope


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


@pytest.fixture
def application(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        membership_a.application_email = "student@example.test"
        membership_a.save(update_fields=["application_email"])
        return Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
            deadline=timezone.now() + timedelta(days=3),
        )


def test_nothing_is_sent_while_no_from_address_is_configured(settings, application):
    """Dormant is the shipped state: no company domain exists yet."""
    settings.REMINDER_EMAIL_FROM = ""

    assert email_student(application, timedelta(days=3)) is False
    assert mail.outbox == []


def test_a_configured_sender_reaches_the_application_address(settings, application):
    settings.REMINDER_EMAIL_FROM = "reminders@tehsil.example"

    assert email_student(application, timedelta(days=3)) is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["student@example.test"]
    assert mail.outbox[0].from_email == "reminders@tehsil.example"
    assert "3 days" in mail.outbox[0].body


def test_a_student_with_no_confirmed_address_is_skipped(
    settings, agency_a, application
):
    """No fallback to user.email -- that address is signup and login only, and
    Membership.application_email's own docstring says so."""
    settings.REMINDER_EMAIL_FROM = "reminders@tehsil.example"
    with tenant_scope(agency_a.id):
        application.student.application_email = ""
        application.student.save(update_fields=["application_email"])

    assert email_student(application, timedelta(days=3)) is False
    assert mail.outbox == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_reminder_email.py -v`
Expected: FAIL — `ImportError: cannot import name 'email_student'`

- [ ] **Step 3: Add the setting and the channel**

Append to `config/settings/base.py`, before the `LOGGING` block:

```python
#: The address deadline reminders are sent from. Empty by default and empty in
#: production today: no company sending domain exists yet (owner, 2026-09-19),
#: and an unset value is what keeps the channel dormant rather than failing.
#: Setting it, plus an SES-backed EMAIL_BACKEND, is the whole switch-on.
REMINDER_EMAIL_FROM = os.getenv("REMINDER_EMAIL_FROM", "")
```

Add to the imports of `apps/portals/reminders.py`:

```python
import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)
```

Append to `apps/portals/reminders.py`:

```python
def email_student(application: Application, remaining: timedelta) -> bool:
    """Mail the student, or say why not. True when a message was handed off.

    Two ways to decline, both ordinary rather than exceptional: the channel is
    unconfigured (no sending domain exists yet), or the student has no
    confirmed address. Neither fails the sweep -- the dashboard rung has
    already fired, and a reminder is not worth stranding a tenant's whole run.
    """
    if not settings.REMINDER_EMAIL_FROM:
        logger.info("ReminderEmailSkipped reason=unconfigured application=%s", application.id)
        return False
    address = application.student.application_email
    if not address:
        # Deliberately no fallback to user.email: that address is signup and
        # login only (Membership.application_email's own docstring), and
        # publishing the login address is how replies go where nothing watches.
        logger.info("ReminderEmailSkipped reason=no_address application=%s", application.id)
        return False
    phrase = remaining_phrase(remaining)
    host = application.portal_form.portal_host
    send_mail(
        subject=f"Your application on {host} is due in {phrase}",
        message=(
            f"Your application on {host} is due in {phrase}.\n\n"
            "Open your dashboard to finish and submit it."
        ),
        from_email=settings.REMINDER_EMAIL_FROM,
        recipient_list=[address],
    )
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_reminder_email.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Check and commit**

```bash
uv run ruff check apps/portals config tests/portals
uv run mypy apps/portals config
git add config/settings/base.py apps/portals/reminders.py tests/portals/test_reminder_email.py
git commit -m "feat(portals): the email rung, dormant until a domain exists"
```

---

### Task 6: The sweep for one tenant

**Files:**
- Modify: `apps/portals/reminders.py`
- Test: `tests/portals/test_reminder_sweep.py`

**Interfaces:**
- Consumes: everything from Tasks 1 and 3-5.
- Produces: `send_due_reminders_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int`, returning how many applications were reminded. It opens its own `tenant_transaction` per application.

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_reminder_sweep.py`:

```python
import uuid
from datetime import time, timedelta

import pytest
from django.utils import timezone

from apps.concierge.models import Notification
from apps.portals.models import Application, PortalForm, ReminderSent, Rung
from apps.portals.reminders import send_due_reminders_for_tenant
from apps.tenancy.context import tenant_scope


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


def _application(agency, student, portal_form, **overrides):
    fields = {
        "tenant": agency,
        "student": student,
        "program_id": uuid.uuid4(),
        "portal_form": portal_form,
        "deadline": timezone.now() + timedelta(days=3, hours=1),
    }
    fields.update(overrides)
    return Application.objects.create(**fields)


def test_a_due_application_is_reminded_once(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, portal_form)

    assert send_due_reminders_for_tenant(agency_a.id) == 1

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1
        # D3 is NOT here: the fixture deadline is 3 days and 1 hour out, so the
        # 3-day rung has not opened yet. D14 and D7 both have, and both are
        # recorded even though only one message was sent.
        assert set(
            ReminderSent.objects.filter(application=application).values_list("rung", flat=True)
        ) == {Rung.D14, Rung.D7}


def test_a_second_sweep_sends_nothing(agency_a, membership_a, portal_form):
    """The constraint, not a check: this is the test that fails if the sweep
    re-notifies every hour forever."""
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form)

    send_due_reminders_for_tenant(agency_a.id)

    assert send_due_reminders_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1


def test_a_later_rung_fires_on_a_later_sweep(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, portal_form)

    send_due_reminders_for_tenant(agency_a.id)
    later = application.deadline - timedelta(hours=5)

    assert send_due_reminders_for_tenant(agency_a.id, now=later) == 1
    with tenant_scope(agency_a.id):
        assert ReminderSent.objects.filter(application=application, rung=Rung.H6).exists()
        assert Notification.objects.filter(recipient=membership_a).count() == 2


def test_an_application_with_no_deadline_is_not_swept(
    agency_a, membership_a, portal_form
):
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form, deadline=None)

    assert send_due_reminders_for_tenant(agency_a.id) == 0


@pytest.mark.parametrize(
    "state",
    [
        Application.State.SUBMITTED,
        Application.State.CONFIRMED,
        Application.State.BLOCKED_MISSING_FACT,
    ],
)
def test_a_finished_or_blocked_application_is_not_reminded(
    agency_a, membership_a, portal_form, state
):
    """Submitted and confirmed are done. A blocked one is already waiting on a
    human, so telling the student to hurry is noise aimed at someone who
    cannot act."""
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form, state=state)

    assert send_due_reminders_for_tenant(agency_a.id) == 0


def test_a_rung_due_inside_quiet_hours_is_held(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        membership_a.timezone = "UTC"
        membership_a.quiet_hours_start = time(22, 0)
        membership_a.quiet_hours_end = time(7, 0)
        membership_a.save(
            update_fields=["timezone", "quiet_hours_start", "quiet_hours_end"]
        )
        application = _application(agency_a, membership_a, portal_form)

    asleep = application.deadline.replace(hour=3, minute=0) - timedelta(days=1)

    assert send_due_reminders_for_tenant(agency_a.id, now=asleep) == 0
    with tenant_scope(agency_a.id):
        assert not ReminderSent.objects.filter(application=application).exists()


def test_a_held_rung_fires_once_the_window_ends(agency_a, membership_a, portal_form):
    """Deferral, not a skip. A test asserting only silence at 03:00 passes on a
    version that drops the reminder forever, which is the opposite of the
    feature."""
    with tenant_scope(agency_a.id):
        membership_a.timezone = "UTC"
        membership_a.quiet_hours_start = time(22, 0)
        membership_a.quiet_hours_end = time(7, 0)
        membership_a.save(
            update_fields=["timezone", "quiet_hours_start", "quiet_hours_end"]
        )
        application = _application(agency_a, membership_a, portal_form)

    asleep = application.deadline.replace(hour=3, minute=0) - timedelta(days=1)
    awake = asleep.replace(hour=8)
    send_due_reminders_for_tenant(agency_a.id, now=asleep)

    assert send_due_reminders_for_tenant(agency_a.id, now=awake) == 1
    with tenant_scope(agency_a.id):
        assert ReminderSent.objects.filter(application=application).exists()


def test_a_student_with_no_zone_is_never_held(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        membership_a.quiet_hours_start = time(22, 0)
        membership_a.quiet_hours_end = time(7, 0)
        membership_a.save(update_fields=["quiet_hours_start", "quiet_hours_end"])
        application = _application(agency_a, membership_a, portal_form)

    asleep = application.deadline.replace(hour=3, minute=0) - timedelta(days=1)

    assert send_due_reminders_for_tenant(agency_a.id, now=asleep) == 1


def test_a_student_with_no_address_still_gets_the_dashboard_rung(
    settings, agency_a, membership_a, portal_form
):
    """Email declining must not take the notification down with it: the
    dashboard is the channel that always works."""
    from django.core import mail

    settings.REMINDER_EMAIL_FROM = "reminders@tehsil.example"
    with tenant_scope(agency_a.id):
        membership_a.application_email = ""
        membership_a.save(update_fields=["application_email"])
        _application(agency_a, membership_a, portal_form)

    assert send_due_reminders_for_tenant(agency_a.id) == 1
    assert mail.outbox == []
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1


def test_the_counselor_is_only_asked_inside_a_day(
    agency_a, membership_a, portal_form, counselor_membership
):
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a,
            counselor=counselor_membership,
            student=membership_a,
            active=True,
        )
        application = _application(agency_a, membership_a, portal_form)

    send_due_reminders_for_tenant(agency_a.id)

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=counselor_membership).count() == 0

    send_due_reminders_for_tenant(
        agency_a.id, now=application.deadline - timedelta(hours=5)
    )

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=counselor_membership).count() == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_reminder_sweep.py -v`
Expected: FAIL — `ImportError: cannot import name 'send_due_reminders_for_tenant'`

- [ ] **Step 3: Write the sweep**

Add these imports to `apps/portals/reminders.py`. `Membership` is imported for the type annotation on `_held_for_quiet_hours`; **extend** the two existing lines rather than duplicating them:

```python
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone as dj_timezone

from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import CounselorAssignment, Membership  # Membership is new

from .models import Application, ReminderSent, Rung  # ReminderSent is new
```

Append to `apps/portals/reminders.py`:

```python
#: An application in one of these states is not reminded. The first two are
#: done; a BLOCKED_* one is already waiting on a human through escalation.py,
#: and telling the student to hurry is noise aimed at someone who cannot act.
_QUIET_STATES = frozenset(
    {
        Application.State.SUBMITTED,
        Application.State.CONFIRMED,
        Application.State.BLOCKED_MISSING_FACT,
        Application.State.BLOCKED_PERSONAL_ACTION,
        Application.State.BLOCKED_CHALLENGE,
        Application.State.BLOCKED_PORTAL_ERROR,
    }
)


def _held_for_quiet_hours(student: Membership, now: datetime) -> bool:
    """Whether this student is inside their own night.

    No zone means no quiet hours and the rung fires on time. Degrading the
    other way -- holding until a zone is known -- drops reminders silently,
    which is the failure this whole ladder exists to prevent.
    """
    if not student.timezone:
        return False
    local = now.astimezone(ZoneInfo(student.timezone)).time()
    return in_quiet_hours(local, student.quiet_hours_start, student.quiet_hours_end)


def send_due_reminders_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int:
    """Remind every application in one tenant that has a rung owed.

    One transaction per application, never one per tenant: a failure on the
    fortieth student must not roll back the thirty-nine ReminderSent rows
    already written, or every one of them sends again on the next sweep.
    """
    moment = now or dj_timezone.now()
    with tenant_transaction(tenant_id):
        due_ids = list(
            Application.objects.filter(deadline__isnull=False)
            .exclude(state__in=_QUIET_STATES)
            .values_list("id", flat=True)
        )

    reminded = 0
    for application_id in due_ids:
        try:
            with tenant_transaction(tenant_id):
                if _remind_one(application_id, moment):
                    reminded += 1
        except Exception:
            # Per application, so one bad row does not strand the tenant. The
            # next sweep retries it: nothing was recorded as sent.
            logger.exception("ReminderFailed application=%s", application_id)
    return reminded


def _remind_one(application_id: UUID, moment: datetime) -> bool:
    application = (
        Application.objects.select_related("student", "portal_form", "reminder_item")
        .filter(id=application_id)
        .first()
    )
    if application is None or application.deadline is None:
        return False
    due = due_rungs(application.deadline, moment)
    if not due:
        return False
    already = set(
        ReminderSent.objects.filter(application=application).values_list("rung", flat=True)
    )
    rung = owed_rung(due, already)
    if rung is None:
        return False
    if _held_for_quiet_hours(application.student, moment):
        # Deferred, never skipped: nothing is recorded, so the next sweep
        # outside the window picks the same rung up. A rung whose deadline
        # passes while held simply stops being due, which is correct.
        return False

    remaining = application.deadline - moment
    item = reminder_item(application)
    notify_student(application, item, remaining)
    email_student(application, remaining)
    if rung in COUNSELOR_RUNGS:
        notify_counselor(application, item, remaining)
    # Every due rung, not just the one sent: an application that appears five
    # days before its deadline has slept through D14 and D7, and recording them
    # is what stops them firing later as stale news.
    ReminderSent.objects.bulk_create(
        [
            ReminderSent(tenant=application.tenant, application=application, rung=value)
            for value in due
        ],
        ignore_conflicts=True,
    )
    logger.info(
        "ReminderSent rung=%s application=%s portal=%s",
        rung.value,
        application.id,
        application.portal_form.portal_host,
    )
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_reminder_sweep.py -v`
Expected: PASS, 12 tests (the state parametrisation counts as three).

- [ ] **Step 5: Check and commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
git add apps/portals/reminders.py tests/portals/test_reminder_sweep.py
git commit -m "feat(portals): the sweep, one transaction per application"
```

---

### Task 7: The management command, and the RLS check no other test can make

**Files:**
- Create: `apps/portals/management/commands/send_due_reminders.py`
- Test: `tests/portals/test_send_due_reminders_command.py`

**Interfaces:**
- Consumes: `send_due_reminders_for_tenant` from Task 6.
- Produces: `manage.py send_due_reminders`, the entry point the EventBridge rule in Task 8 invokes.

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_send_due_reminders_command.py`:

```python
import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.concierge.models import Notification
from apps.portals.models import Application, PortalForm
from apps.tenancy.context import tenant_scope


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


def _application(agency, student, portal_form):
    return Application.objects.create(
        tenant=agency,
        student=student,
        program_id=uuid.uuid4(),
        portal_form=portal_form,
        deadline=timezone.now() + timedelta(days=3, hours=1),
    )


def test_the_command_reminds_across_every_agency(
    agency_a, membership_a, agency_b, membership_b, portal_form
):
    """tenant_scope refuses to switch tenants, so a scope held across the loop
    raises on the second agency. This is the test that catches that."""
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form)
    with tenant_scope(agency_b.id):
        _application(agency_b, membership_b, portal_form)

    call_command("send_due_reminders")

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1
    with tenant_scope(agency_b.id):
        assert Notification.objects.filter(recipient=membership_b).count() == 1


def test_the_command_is_quiet_when_nothing_is_due(agency_a):
    call_command("send_due_reminders")


def test_the_sweep_works_behind_real_row_level_security(
    rls_enforced_orm, agency_a, membership_a, portal_form
):
    """The suite otherwise runs as a BYPASSRLS superuser, so a scan missing its
    set_local_tenant passes here and returns zero rows in production -- the
    command finds nothing, exits 0, and no reminder is ever sent.
    """
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form)

    call_command("send_due_reminders")

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_send_due_reminders_command.py -v`
Expected: FAIL — `CommandError: Unknown command: 'send_due_reminders'`

- [ ] **Step 3: Write the command**

Create `apps/portals/management/commands/send_due_reminders.py`:

```python
"""Send every deadline reminder that has come due, in every tenant.

Invoked hourly by ReminderLadderRule (infra/template.yaml). Hourly and not
daily: the 6-hour rung cannot be hit by a daily job, and it is the rung whose
whole purpose is being the last one.

Design: docs/superpowers/specs/2026-09-19-reminder-ladder-design.md
"""

from django.core.management.base import BaseCommand

from apps.portals.reminders import send_due_reminders_for_tenant
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Agency


class Command(BaseCommand):
    help = "Send deadline reminders whose rung has come due"

    def handle(self, *_args: object, **_options: object) -> None:
        # Agency is not tenant-scoped and carries no RLS policy, so listing it
        # from the runtime role works. One scope per agency: tenant_scope
        # refuses to SWITCH tenants (TenantContextConflict), so an outer scope
        # held across the loop would raise on the second agency.
        for agency in Agency.objects.all():
            with tenant_scope(agency.id):
                send_due_reminders_for_tenant(agency.id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/portals/test_send_due_reminders_command.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Check and commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
uv run bandit -c pyproject.toml -r apps config
git add apps/portals/management/commands/send_due_reminders.py tests/portals/test_send_due_reminders_command.py
git commit -m "feat(portals): send_due_reminders, verified behind a NOBYPASSRLS role"
```

---

### Task 8: The hourly schedule

**Files:**
- Modify: `infra/template.yaml` (add beside `EuropassCanaryRule`, around line 2017)
- Test: `tests/infra/test_template.py` (append)

**Interfaces:**
- Consumes: `manage.py send_due_reminders` from Task 7.
- Produces: the `ReminderLadderRule` resource.

- [ ] **Step 1: Write the failing test**

Append to `tests/infra/test_template.py`:

```python
def test_the_reminder_ladder_runs_hourly(template: Template) -> None:
    """Hourly, not daily: a daily job cannot hit the 6-hour rung at all."""
    rule = template.resource("ReminderLadderRule")

    assert rule["Properties"]["ScheduleExpression"] == "rate(1 hour)"
    assert rule["Properties"]["State"] == "ENABLED"


def test_the_reminder_ladder_runs_the_worker_task(template: Template) -> None:
    target = template.resource("ReminderLadderRule")["Properties"]["Targets"][0]
    parameters = target["EcsParameters"]

    assert parameters["TaskDefinitionArn"] == {"Ref": "WorkerTaskDefinition"}
    assert parameters["LaunchType"] == "FARGATE"
    assert parameters["NetworkConfiguration"]["AwsVpcConfiguration"]["SecurityGroups"] == [
        {"Ref": "WorkerSecurityGroup"}
    ]


def test_the_reminder_ladder_invokes_the_command_that_exists(template: Template) -> None:
    """The container name and the command are a pair: a rename on either side
    leaves a rule that runs hourly and does nothing."""
    raw_input = template.resource("ReminderLadderRule")["Properties"]["Targets"][0]["Input"]
    overrides = json.loads(raw_input["Fn::Sub"])["containerOverrides"][0]

    assert overrides["name"] == "worker"
    assert overrides["command"] == ["python", "manage.py", "send_due_reminders"]


def test_the_ladder_ships_with_its_schedule(template: Template) -> None:
    """The erasure command shipped without its rule and that is now a
    documented deployment blocker: the command exists, nothing invokes it, and
    every screen says the right thing. An hourly sweep nobody invokes fails the
    same silent way."""
    assert "ReminderLadderRule" in template.resource_ids()
```

`Template`, its `resource()` / `resource_ids()` helpers and the module-scoped `template` fixture are already defined at the top of that file — add nothing.

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/infra/test_template.py -k reminder_ladder -v`
Expected: FAIL — `AssertionError: ReminderLadderRule is not defined in infra/template.yaml`

- [ ] **Step 3: Add the rule**

In `infra/template.yaml`, immediately after the `EuropassCanaryRule` resource (it ends at line 2036), add:

```yaml
  # Hourly, not daily: the ladder's last rung is 6 hours before the deadline,
  # which a daily job cannot hit. Shipped enabled, unlike the erasure schedule
  # that was deferred -- a sweep nothing invokes is a ladder that silently
  # never fires, with every screen saying the right thing.
  ReminderLadderRule:
    Type: AWS::Events::Rule
    Properties:
      Description: Send deadline reminders whose rung has come due
      ScheduleExpression: "rate(1 hour)"
      State: ENABLED
      Targets:
        - Id: reminder-ladder
          Arn: !GetAtt ValidationCluster.Arn
          RoleArn: !GetAtt EventsInvokeEcsRole.Arn
          EcsParameters:
            TaskDefinitionArn: !Ref WorkerTaskDefinition
            LaunchType: FARGATE
            NetworkConfiguration:
              AwsVpcConfiguration:
                Subnets: [!Ref WorkerPrivateSubnetA, !Ref WorkerPrivateSubnetB]
                SecurityGroups: [!Ref WorkerSecurityGroup]
          Input: !Sub |
            {"containerOverrides":[{"name":"worker",
             "command":["python","manage.py","send_due_reminders"]}]}
```

`ValidationCluster` is the only `AWS::ECS::Cluster` in this template and every service already runs on it; `worker` is `WorkerTaskDefinition`'s only container name (`infra/template.yaml:1426`). Both were checked when this plan was written — do not substitute either.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_mailbox uv run pytest tests/infra/test_template.py -v`
Expected: PASS, including the four new tests.

- [ ] **Step 5: Run the whole suite and commit**

```bash
POSTGRES_DB=tehsil_mailbox uv run pytest -q
uv run ruff check apps tests config
uv run mypy apps
uv run bandit -c pyproject.toml -r apps config
git add infra/template.yaml tests/infra/test_template.py
git commit -m "feat(infra): the reminder ladder runs hourly"
```

---

## Deliberately not in this plan

Each of these is in the spec's own "deliberately not built" section; none is an oversight.

- **Automatic WhatsApp sending.** Blocked on Meta business verification against a registered legal entity, pre-approved templates, and recorded opt-in. The counselor sends by hand until then.
- **A missed-deadline notice.** `due_rungs` returns nothing once the deadline passes.
- **Per-student channel preferences.** Quiet hours already carry the "stop bothering me at night" case.
- **A UI for setting quiet hours or a timezone.** The fields exist and the ladder honours them; the form that fills them is frontend work and belongs to Aykhan, per the standing rule. Leave a `SHOULD BE DONE BY AYKHAN` note if a view stub becomes necessary.
- **SES resources in CloudFormation.** A resource pointing at an unverified sending identity fails the stack. The channel is designed to be dormant without one.
