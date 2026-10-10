# Application Watch — Core (plan 1 of 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the platform notice when an expected confirmation has not arrived, escalate any urgent alert nobody has acknowledged, and raise an alarm when a scheduled job stops running — so a student with no mailbox connected is still protected.

**Architecture:** A new Django app, `apps/watch`, owns three things: an `Expectation` row per application (first kind: the portal's confirmation after submission), two per-tenant sweeps (watchdog, escalation) run hourly by one management command, and a platform-wide `JobRun` heartbeat table that each scheduled command writes and the others check. Alerts are ordinary `concierge.Notification` rows with two new fields (`urgent`, `escalation_level`). Infra adds one EventBridge rule and three CloudWatch alarms.

**Tech Stack:** Django 5.2, PostgreSQL 17 with row-level security, pytest + pytest-django, CloudFormation (`infra/template.yaml`), uv.

**Spec:** `docs/superpowers/specs/2026-09-25-application-watch-design.md` (§1 timeline, §4 watchdog and alerts, §5 self-monitoring, "Data it needs", "Cases the design must handle"). Plan 2 (mail recognition: tagged addresses, registrable-domain filter, learned senders, application inbox, delivery test, extension-triggered check, the mailbox sweep's schedule) follows this one.

**Not in this plan, on purpose:**
- The daily summary of non-urgent items (spec §4) and every screen: no dashboard exists
  yet, and the presentation layer is chosen by the frontend orchestrator (CLAUDE.md,
  "Frontend and design"). This plan leaves the data a dashboard reads: urgent
  notifications, their level, and `acknowledged_at` via the existing acknowledge endpoint.
- Decision and offer-acceptance expectations: they need an outcome record (spec §1).
- Mailbox health beyond today's `announce_lost_grant`, and the mailbox sweep's schedule:
  plan 2, which also gives the worker the OAuth settings that schedule needs.

## Global Constraints

- Work in `/home/orkhan/Desktop/mailbox-port`, branch `claude/mailbox-port`. Always `git -C /home/orkhan/Desktop/mailbox-port …` — the shell's cwd resets to the main repo and a bare `git commit` lands on the wrong branch.
- Test DB: prefix every pytest/manage.py command with `POSTGRES_DB=tehsil_mailbox_port`. Never another worktree's DB name.
- Lint: `uv run ruff check .` only. **Never run `ruff format`** (it churns unrelated files).
- Types: `uv run mypy apps config`. Security: `uv run bandit -c pyproject.toml -r apps config`. Migrations: `POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations --check --dry-run`.
- Line length 100.
- Every tenant-scoped query outside a request runs inside `tenant_scope(tenant_id)` **and** `tenant_transaction(tenant_id)`. Missing the transaction is legal SQL that returns zero rows in production (CLAUDE.md, RLS failure mode 1), and no test catches it except one run under `rls_enforced_orm` with `@pytest.mark.django_db(transaction=True)`.
- Every new tenant table gets `ENABLE` + `FORCE ROW LEVEL SECURITY`, the `tenant_isolation` policy, and a composite `(tenant_id, <fk>_id)` foreign key to each tenant-scoped parent, in its migration.
- Every field of a model FK-reachable from `Membership` must be classified in `apps/audit/redaction.py` (`REDACT` or `KEEP`) or `tests/audit/test_redaction_classification.py` fails.
- `apps/portals/` modules other than `ext_api.py` and `models.py` must not contain the string `SUBMITTED` (`tests/portals/test_boundary.py::test_nothing_in_the_app_can_submit`). The watchdog therefore lives in `apps/watch`.
- Quiet hours are honoured **without exception** (owner decision 2026-09-19): an alert or escalation inside the student's quiet window is deferred to the next sweep, never skipped, never forced.
- Logs carry ids and portal hosts only, never message text, email addresses or names.
- Commits end with: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

## Review Focus

1. **Two overlapping sweeps (EventBridge is at-least-once).** Expected: one alert per expectation and one escalation per level, never two. The `select_for_update` lock is implemented but NOT pinned: this single-threaded suite cannot run two sweeps at once, so no test exercises it. What is pinned is the sequential idempotency guard (a second sweep alerts and escalates nothing), in Tasks 3 and 4.
2. **A student inside quiet hours when an alert falls due.** Expected: nothing sent now, sent on the first sweep after the window. Pinned in Tasks 3 and 4.
3. **A direct-to-student account (no counsellor) reaching escalation level 2.** Expected: the level is recorded, nothing is sent to anyone else, an INFO log says the chain ended. Pinned in Task 4.
4. **The sweeps running as the production runtime role (NOBYPASSRLS).** Expected: the same result as under the test superuser. Pinned by the `rls_enforced_orm` command test in Task 5.
5. **A job that has never run at all (first deploy, disabled rule).** Expected: reported silent, not treated as healthy. Pinned in Task 5.

---

### Task 1: The `watch` app, its tables, and the two new notification fields

**Files:**
- Create: `apps/watch/__init__.py` (empty), `apps/watch/apps.py`, `apps/watch/models.py`, `apps/watch/migrations/__init__.py` (empty), `apps/watch/migrations/0001_initial.py` (generated, then edited)
- Create: `apps/concierge/migrations/0007_notification_urgent_escalation.py` (generated)
- Modify: `apps/concierge/models.py` (class `Notification`, after `acknowledged_at`)
- Modify: `config/settings/base.py` (`INSTALLED_APPS`, after `"apps.mailbox",`)
- Modify: `apps/audit/redaction.py` (`KEEP` map)
- Test: `tests/watch/__init__.py` (empty), `tests/watch/test_models.py`

**Interfaces:**
- Produces: `apps.watch.models.Expectation` (fields `tenant`, `application`, `kind`, `due_at`, `alerted`, `created_at`; `Expectation.Kind.CONFIRMATION`), `apps.watch.models.JobRun` (fields `name` primary key, `last_success_at`), `Notification.urgent: bool` (default False), `Notification.escalation_level: int` (default 0; 0 = dashboard only, 1 = emailed, 2 = counsellor told).

- [ ] **Step 1: Write the failing tests**

`tests/watch/test_models.py`:

```python
"""The watch app's two tables and the tenant guards Django cannot write."""

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.portals.models import Application, PortalForm
from apps.tenancy.context import tenant_scope
from apps.watch.models import Expectation, JobRun

pytestmark = pytest.mark.django_db


@pytest.fixture
def portal_form():
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


def _application(agency, student, portal_form):
    with tenant_scope(agency.id):
        return Application.objects.create(
            tenant=agency, student=student, program_id=uuid.uuid4(), portal_form=portal_form
        )


def test_one_expectation_per_application_and_kind(agency_a, membership_a, portal_form):
    application = _application(agency_a, membership_a, portal_form)
    due = timezone.now() + timedelta(hours=48)
    with tenant_scope(agency_a.id):
        Expectation.objects.create(
            tenant=agency_a, application=application, kind="CONFIRMATION", due_at=due
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Expectation.objects.create(
                tenant=agency_a, application=application, kind="CONFIRMATION", due_at=due
            )


def test_an_expectation_cannot_name_another_tenants_application(
    agency_a, agency_b, membership_b, portal_form
):
    application_b = _application(agency_b, membership_b, portal_form)
    with (
        pytest.raises(IntegrityError) as caught,
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO watch_expectation (id, tenant_id, application_id, kind, due_at, created_at)
            VALUES (%s, %s, %s, 'CONFIRMATION', now(), now())
            """,
            [uuid.uuid4(), agency_a.id, application_b.id],
        )
    assert caught.value.__cause__.diag.constraint_name == "expectation_app_tenant_fk"


def test_an_expectation_cannot_name_another_tenants_notification(
    agency_a, agency_b, membership_a, membership_b, portal_form
):
    application_a = _application(agency_a, membership_a, portal_form)
    with tenant_scope(agency_b.id):
        item_b = RoadmapItem.objects.create(
            tenant=agency_b,
            student=membership_b,
            stage=RoadmapItem.Stage.MONITORING,
            owner=membership_b,
            deadline=timezone.now(),
        )
        note_b = Notification.objects.create(
            tenant=agency_b, recipient=membership_b, roadmap_item=item_b, message="x"
        )
    with (
        pytest.raises(IntegrityError) as caught,
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO watch_expectation
                (id, tenant_id, application_id, kind, due_at, alerted_id, created_at)
            VALUES (%s, %s, %s, 'CONFIRMATION', now(), %s, now())
            """,
            [uuid.uuid4(), agency_a.id, application_a.id, note_b.id],
        )
    assert caught.value.__cause__.diag.constraint_name == "expectation_alert_tenant_fk"


def test_expectation_is_forced_behind_row_level_security():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'public.watch_expectation'::regclass"
        )
        assert cursor.fetchone() == (True, True)


def test_a_notification_starts_unurgent_at_level_zero(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.MONITORING,
            owner=membership_a,
            deadline=timezone.now(),
        )
        note = Notification.objects.create(
            tenant=agency_a, recipient=membership_a, roadmap_item=item, message="x"
        )
    assert note.urgent is False
    assert note.escalation_level == 0


def test_a_job_run_is_one_row_per_job():
    for _ in range(2):
        JobRun.objects.update_or_create(
            name="send_due_reminders", defaults={"last_success_at": timezone.now()}
        )
    assert JobRun.objects.count() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/orkhan/Desktop/mailbox-port && POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch/test_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.watch'`.

- [ ] **Step 3: Create the app and models**

`apps/watch/apps.py`:

```python
from django.apps import AppConfig


class WatchConfig(AppConfig):
    name = "apps.watch"
```

`apps/watch/models.py`:

```python
"""What the platform is waiting for on each application, and whether its own jobs run.

Design: docs/superpowers/specs/2026-09-25-application-watch-design.md. Lives
outside apps/portals because the watchdog must name the submitted state, which
tests/portals/test_boundary.py reserves there for ext_api.py and models.py.
"""

from __future__ import annotations

from uuid import uuid4

from django.db import models

from apps.tenancy.models import TenantScopedModel


class Expectation(TenantScopedModel):
    """Something that should happen to one application by a time.

    Met is not a column: an expectation is met when the application's state has
    moved past the one that created it, which the watchdog reads directly. A
    column would be a second copy of the state that could disagree with it.
    `alerted` is the idempotency record: set once, in the same transaction as the
    alert, so a second sweep never alerts twice.
    """

    class Kind(models.TextChoices):
        #: The portal acknowledges a submission. Decision and offer kinds wait
        #: for an outcome record (spec §1).
        CONFIRMATION = "CONFIRMATION", "Portal confirms the submission"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    application = models.ForeignKey(
        "portals.Application", on_delete=models.CASCADE, related_name="expectations"
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    due_at = models.DateTimeField()
    alerted = models.ForeignKey(
        "concierge.Notification", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="expectation_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("application", "kind"), name="expectation_once_per_kind"
            ),
        ]


class JobRun(models.Model):
    """The last time a scheduled command finished. Platform-wide; names no one.

    Not tenant-scoped: a job runs across every agency, and "did the reminder
    ladder run" is one fact, not one per tenant.
    """

    name = models.CharField(max_length=64, primary_key=True)
    last_success_at = models.DateTimeField()
```

Add to `config/settings/base.py` `INSTALLED_APPS`, directly after `"apps.mailbox",`:

```python
    "apps.watch",
```

In `apps/concierge/models.py`, class `Notification`, directly after the `acknowledged_at` line:

```python
    #: Needs a person to acknowledge it; unanswered, apps/watch escalates it.
    #: Everything else waits for the daily summary (spec §4).
    urgent = models.BooleanField(default=False)
    #: How far escalation has gone: 0 dashboard only, 1 emailed, 2 counsellor told.
    escalation_level = models.PositiveSmallIntegerField(default=0)
```

- [ ] **Step 4: Generate the migrations, then add the SQL Django cannot write**

Run:
```bash
cd /home/orkhan/Desktop/mailbox-port
POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations concierge --name notification_urgent_escalation
POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations watch
```

Open `apps/watch/migrations/0001_initial.py`. Make its `dependencies` exactly:

```python
    dependencies = [
        ("concierge", "0007_notification_urgent_escalation"),
        ("portals", "0017_merge_20260925_0848"),
        ("tenancy", "0002_rls"),
    ]
```

(Drop any later `tenancy` migration makemigrations adds — `Expectation.tenant` needs only `tenancy.Agency`; see the same note in `apps/portals/migrations/0014_reminder_ladder.py`.)

Add above the `Migration` class:

```python
RLS_SQL = """
ALTER TABLE watch_expectation ENABLE ROW LEVEL SECURITY;
ALTER TABLE watch_expectation FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON watch_expectation
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
"""

REVERSE_RLS_SQL = """
DROP POLICY IF EXISTS tenant_isolation ON watch_expectation;
ALTER TABLE watch_expectation DISABLE ROW LEVEL SECURITY;
"""
```

Append to `operations`, after the `CreateModel`s:

```python
        # The composite guards every tenant table here carries: the policy
        # checks the row's own tenant_id, never its parent's, so without these a
        # row could name another tenant's application or notification.
        migrations.RunSQL(
            """
            ALTER TABLE watch_expectation
                ADD CONSTRAINT expectation_app_tenant_fk
                FOREIGN KEY (tenant_id, application_id)
                REFERENCES portals_application (tenant_id, id);
            ALTER TABLE watch_expectation
                ADD CONSTRAINT expectation_alert_tenant_fk
                FOREIGN KEY (tenant_id, alerted_id)
                REFERENCES concierge_notification (tenant_id, id);
            """,
            """
            ALTER TABLE watch_expectation DROP CONSTRAINT expectation_alert_tenant_fk;
            ALTER TABLE watch_expectation DROP CONSTRAINT expectation_app_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
```

- [ ] **Step 5: Classify the new fields for erasure**

In `apps/audit/redaction.py`, `KEEP` map: change the `"concierge.Notification"` entry to

```python
    "concierge.Notification": ("acknowledged_at", "urgent", "escalation_level", "created_at"),
```

and add, next to `"portals.ReminderSent"`:

```python
    # kind is a closed enum and the times are operational; the identifying
    # link is the application relation, excluded from classification.
    "watch.Expectation": ("kind", "due_at", "created_at"),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch/test_models.py tests/audit/test_redaction_classification.py tests/tenancy/test_database_isolation.py -q`
Expected: all PASS. If `test_redaction_classification` names `watch.Expectation.alerted`, it is an FK and is skipped by `classifiable_fields`; if it is listed anyway, add `"alerted"` to the KEEP tuple.

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/watch apps/concierge config/settings/base.py apps/audit/redaction.py tests/watch
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(watch): expectations, job heartbeats, and urgent notifications

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The timing rules, as pure functions

**Files:**
- Create: `apps/watch/rules.py`
- Test: `tests/watch/test_rules.py`

**Interfaces:**
- Produces: `CONFIRMATION_WINDOW: timedelta` (48h); `confirmation_due(submitted_at: datetime) -> datetime`; `escalation_target(created_at: datetime, now: datetime, deadline: datetime | None) -> int` returning 0, 1 or 2.

- [ ] **Step 1: Write the failing tests**

`tests/watch/test_rules.py`:

```python
from datetime import UTC, datetime, timedelta

from apps.watch.rules import CONFIRMATION_WINDOW, confirmation_due, escalation_target

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
FAR = T0 + timedelta(days=30)


def test_a_confirmation_is_due_two_days_after_submission():
    assert CONFIRMATION_WINDOW == timedelta(hours=48)
    assert confirmation_due(T0) == T0 + timedelta(hours=48)


def test_a_fresh_alert_is_not_escalated():
    assert escalation_target(T0, T0 + timedelta(hours=11), FAR) == 0


def test_far_from_a_deadline_email_at_12h_and_counsellor_at_24h():
    assert escalation_target(T0, T0 + timedelta(hours=12), FAR) == 1
    assert escalation_target(T0, T0 + timedelta(hours=23), FAR) == 1
    assert escalation_target(T0, T0 + timedelta(hours=24), FAR) == 2


def test_within_48h_of_a_deadline_email_at_2h_and_counsellor_at_4h():
    near = T0 + timedelta(hours=40)
    assert escalation_target(T0, T0 + timedelta(hours=1), near) == 0
    assert escalation_target(T0, T0 + timedelta(hours=2), near) == 1
    assert escalation_target(T0, T0 + timedelta(hours=4), near) == 2


def test_no_deadline_uses_the_slow_ladder():
    assert escalation_target(T0, T0 + timedelta(hours=2), None) == 0
    assert escalation_target(T0, T0 + timedelta(hours=24), None) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch/test_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.watch.rules'`.

- [ ] **Step 3: Implement**

`apps/watch/rules.py`:

```python
"""When things are due and when an unanswered alert climbs. No database, no clock.

Platform-wide defaults (spec §1): a portal gets its own timing only when real
data shows it behaves differently.
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: How long a portal gets to confirm a submission before we ask the student to
#: look. Two days covers a weekend-free acknowledgement; tune from data.
CONFIRMATION_WINDOW = timedelta(hours=48)

#: Inside this distance of the deadline the ladder tightens.
NEAR_DEADLINE = timedelta(hours=48)

#: (email after, counsellor after) -- slow far from a deadline, fast near one.
_SLOW = (timedelta(hours=12), timedelta(hours=24))
_FAST = (timedelta(hours=2), timedelta(hours=4))


def confirmation_due(submitted_at: datetime) -> datetime:
    return submitted_at + CONFIRMATION_WINDOW


def escalation_target(created_at: datetime, now: datetime, deadline: datetime | None) -> int:
    """The escalation level an unacknowledged urgent alert should have reached.

    0 dashboard only, 1 email the student, 2 tell the counsellor. Levels are
    cumulative; the caller performs every level between the current one and this.
    """
    near = deadline is not None and deadline - now <= NEAR_DEADLINE
    email_after, counsellor_after = _FAST if near else _SLOW
    waited = now - created_at
    if waited >= counsellor_after:
        return 2
    if waited >= email_after:
        return 1
    return 0
```

- [ ] **Step 4: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch/test_rules.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/watch/rules.py tests/watch/test_rules.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(watch): confirmation window and escalation timing

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The watchdog sweep

**Files:**
- Create: `apps/watch/watchdog.py`
- Modify: `apps/portals/reminders.py` — rename `_held_for_quiet_hours` to `held_for_quiet_hours` (definition and its one call in `_remind_one`); no behaviour change.
- Test: `tests/watch/test_watchdog.py`

**Interfaces:**
- Consumes: `Expectation` (Task 1), `confirmation_due` (Task 2), `apps.portals.reminders.held_for_quiet_hours(student: Membership, now: datetime) -> bool`.
- Produces: `watch_applications_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int` — number of alerts raised. Each alert is a `Notification(urgent=True)` on a new `RoadmapItem(stage=MONITORING)`.

- [ ] **Step 1: Write the failing tests**

`tests/watch/test_watchdog.py`:

```python
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.concierge.models import Notification
from apps.portals.models import Application, ApplicationStep, PortalForm
from apps.tenancy.context import tenant_scope
from apps.watch.models import Expectation
from apps.watch.watchdog import watch_applications_for_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def portal_form():
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


def _submitted(agency, student, portal_form, *, hours_ago, state="SUBMITTED"):
    """An application submitted `hours_ago`, with the SUBMITTED step the
    extension writes (ext_api.py) dated to match."""
    with tenant_scope(agency.id):
        application = Application.objects.create(
            tenant=agency,
            student=student,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
            state=state,
            deadline=timezone.now() + timedelta(days=20),
        )
        step = ApplicationStep.objects.create(
            tenant=agency, application=application, sequence=1, kind="SUBMITTED"
        )
        ApplicationStep.objects.filter(pk=step.pk).update(
            created_at=timezone.now() - timedelta(hours=hours_ago)
        )
        return application


def test_an_overdue_confirmation_raises_one_urgent_alert(agency_a, membership_a, portal_form):
    application = _submitted(agency_a, membership_a, portal_form, hours_ago=49)

    assert watch_applications_for_tenant(agency_a.id) == 1

    with tenant_scope(agency_a.id):
        note = Notification.objects.get(recipient=membership_a)
        expectation = Expectation.objects.get(application=application)
    assert note.urgent is True
    assert "portal.example.test" in note.message
    assert expectation.alerted_id == note.id


def test_a_second_sweep_does_not_alert_again(agency_a, membership_a, portal_form):
    _submitted(agency_a, membership_a, portal_form, hours_ago=49)
    watch_applications_for_tenant(agency_a.id)

    assert watch_applications_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1


def test_a_recent_submission_is_expected_but_not_alerted(agency_a, membership_a, portal_form):
    application = _submitted(agency_a, membership_a, portal_form, hours_ago=5)

    assert watch_applications_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        expectation = Expectation.objects.get(application=application)
        assert Notification.objects.filter(recipient=membership_a).count() == 0
    step_time = timezone.now() - timedelta(hours=5)
    assert abs(expectation.due_at - (step_time + timedelta(hours=48))) < timedelta(minutes=1)


def test_a_confirmed_application_is_left_alone(agency_a, membership_a, portal_form):
    _submitted(agency_a, membership_a, portal_form, hours_ago=100, state="CONFIRMED")

    assert watch_applications_for_tenant(agency_a.id) == 0


def test_quiet_hours_defer_the_alert_and_never_skip_it(agency_a, membership_a, portal_form):
    """Owner decision 2026-09-19: quiet hours hold without exception."""
    _submitted(agency_a, membership_a, portal_form, hours_ago=49)
    now = timezone.now()
    with tenant_scope(agency_a.id):
        # A window around `now`, so the test holds at any hour it runs.
        membership_a.timezone = "UTC"
        membership_a.quiet_hours_start = (now - timedelta(hours=1)).time()
        membership_a.quiet_hours_end = (now + timedelta(hours=1)).time()
        membership_a.save(update_fields=["timezone", "quiet_hours_start", "quiet_hours_end"])

    assert watch_applications_for_tenant(agency_a.id, now=now) == 0

    with tenant_scope(agency_a.id):
        membership_a.quiet_hours_start = None
        membership_a.quiet_hours_end = None
        membership_a.save(update_fields=["quiet_hours_start", "quiet_hours_end"])
    assert watch_applications_for_tenant(agency_a.id, now=now) == 1


def test_another_tenant_is_not_touched(agency_a, membership_a, agency_b, membership_b, portal_form):
    _submitted(agency_b, membership_b, portal_form, hours_ago=49)

    assert watch_applications_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_b.id):
        assert Notification.objects.filter(recipient=membership_b).count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch/test_watchdog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.watch.watchdog'`.

- [ ] **Step 3: Rename the quiet-hours helper**

In `apps/portals/reminders.py` replace both occurrences of `_held_for_quiet_hours` with `held_for_quiet_hours` (the `def` and the call inside `_remind_one`). Run `grep -rn "_held_for_quiet_hours" apps tests` — expected: no output.

- [ ] **Step 4: Implement the watchdog**

`apps/watch/watchdog.py`:

```python
"""Notice what should have happened and has not.

First expectation: a portal confirms a submission within CONFIRMATION_WINDOW.
The confirmation arriving -- by mail, by the extension reading the portal, by
the student saying so -- moves the application to CONFIRMED, and that alone
meets the expectation; this module never needs to be told.

Design: docs/superpowers/specs/2026-09-25-application-watch-design.md §1, §4.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.portals.models import Application, ApplicationStep
from apps.portals.reminders import held_for_quiet_hours
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .models import Expectation
from .rules import confirmation_due

logger = logging.getLogger(__name__)

#: RoadmapItem.deadline is NOT NULL. An application with no known deadline gets
#: this, so the card still sorts and still reads as due soon.
_NO_DEADLINE_HORIZON = timedelta(days=7)


def watch_applications_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int:
    """Raise every alert this tenant is owed. Returns how many were raised.

    One transaction per application, as the reminder ladder does: a failure on
    one must not roll back the alerts already recorded for the others.
    """
    moment = now or timezone.now()
    with tenant_scope(tenant_id):
        with tenant_transaction(tenant_id):
            submitted = list(
                Application.objects.filter(
                    state=Application.State.SUBMITTED, student__active=True
                ).values_list("id", flat=True)
            )
        raised = 0
        for application_id in submitted:
            try:
                with tenant_transaction(tenant_id):
                    if _watch_one(application_id, moment):
                        raised += 1
            except Exception:
                logger.exception("WatchFailed application=%s", application_id)
        return raised


def _submitted_at(application: Application) -> datetime:
    """When the student pressed Submit, from the step ext_api.py records."""
    step_time = (
        ApplicationStep.objects.filter(
            application=application, kind=ApplicationStep.Kind.SUBMITTED
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    return step_time or application.created_at


def _watch_one(application_id: UUID, moment: datetime) -> bool:
    application = Application.objects.select_related("student", "portal_form").get(
        id=application_id
    )
    Expectation.objects.get_or_create(
        application=application,
        kind=Expectation.Kind.CONFIRMATION,
        defaults={
            "tenant": application.tenant,
            "due_at": confirmation_due(_submitted_at(application)),
        },
    )
    # Locked, then re-read: two overlapping sweeps both reaching here would
    # otherwise both see alerted=None and alert twice.
    expectation = Expectation.objects.select_for_update().get(
        application=application, kind=Expectation.Kind.CONFIRMATION
    )
    if expectation.alerted_id is not None or moment < expectation.due_at:
        return False
    if held_for_quiet_hours(application.student, moment):
        # Deferred, never skipped: nothing is recorded, so the next sweep
        # outside the window raises it.
        return False

    host = application.portal_form.portal_host
    item = RoadmapItem.objects.create(
        tenant=application.tenant,
        student=application.student,
        stage=RoadmapItem.Stage.MONITORING,
        owner=application.student,
        owner_kind=RoadmapItem.OwnerKind.HUMAN,
        deadline=application.deadline or moment + _NO_DEADLINE_HORIZON,
    )
    note = Notification.objects.create(
        tenant=application.tenant,
        recipient=application.student,
        roadmap_item=item,
        urgent=True,
        message=(
            f"We haven't seen a confirmation from {host} since you submitted. "
            f"Open your {host} portal and check your application arrived."
        ),
    )
    expectation.alerted = note
    expectation.save(update_fields=["alerted"])
    logger.info("ConfirmationOverdue application=%s portal=%s", application.id, host)
    return True
```


- [ ] **Step 5: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch/test_watchdog.py tests/portals/test_reminder_sweep.py tests/portals/test_boundary.py -q`
Expected: all PASS (the boundary test proves nothing in `apps/portals` newly names the submitted state).

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/watch/watchdog.py apps/portals/reminders.py tests/watch/test_watchdog.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(watch): alert when a submitted application is never confirmed

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Escalating unacknowledged urgent alerts

**Files:**
- Create: `apps/watch/escalation.py`
- Test: `tests/watch/test_escalation.py`

**Interfaces:**
- Consumes: `Notification.urgent`, `Notification.escalation_level` (Task 1); `escalation_target` (Task 2); `held_for_quiet_hours` (Task 3); `settings.REMINDER_EMAIL_FROM` (existing, empty = dormant).
- Produces: `escalate_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int` — number of notifications whose level rose.

- [ ] **Step 1: Write the failing tests**

`tests/watch/test_escalation.py`:

```python
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.concierge.services import acknowledge_notification
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from apps.watch.escalation import escalate_for_tenant

pytestmark = pytest.mark.django_db


def _alert(agency, student, *, hours_ago, urgent=True, deadline_in=timedelta(days=30)):
    with tenant_scope(agency.id):
        item = RoadmapItem.objects.create(
            tenant=agency,
            student=student,
            stage=RoadmapItem.Stage.MONITORING,
            owner=student,
            deadline=timezone.now() + deadline_in,
        )
        note = Notification.objects.create(
            tenant=agency, recipient=student, roadmap_item=item, message="TUM: act", urgent=urgent
        )
        Notification.objects.filter(pk=note.pk).update(
            created_at=timezone.now() - timedelta(hours=hours_ago)
        )
        note.refresh_from_db()
        return note


@pytest.fixture
def with_email(settings, user_a):
    settings.REMINDER_EMAIL_FROM = "alerts@example.test"
    user_a.email = "leyla@example.test"
    user_a.save(update_fields=["email"])


@pytest.fixture
def counselled(agency_a, membership_a, counselor_membership):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    return counselor_membership


def test_after_12h_the_student_is_emailed_at_the_address_they_sign_in_with(
    agency_a, membership_a, with_email
):
    note = _alert(agency_a, membership_a, hours_ago=13)

    assert escalate_for_tenant(agency_a.id) == 1

    note.refresh_from_db()
    assert note.escalation_level == 1
    assert [m.to for m in mail.outbox] == [["leyla@example.test"]]


def test_after_24h_the_counsellor_is_told_too(
    agency_a, membership_a, counselled, with_email
):
    _alert(agency_a, membership_a, hours_ago=25)

    escalate_for_tenant(agency_a.id)

    with tenant_scope(agency_a.id):
        told = Notification.objects.filter(recipient=counselled)
        assert told.count() == 1
        assert "WhatsApp" in told.get().message
    assert len(mail.outbox) == 1


def test_an_acknowledged_alert_never_escalates(agency_a, membership_a, with_email):
    note = _alert(agency_a, membership_a, hours_ago=25)
    with tenant_scope(agency_a.id):
        acknowledge_notification(note)

    assert escalate_for_tenant(agency_a.id) == 0
    assert mail.outbox == []


def test_a_non_urgent_notification_is_never_escalated(agency_a, membership_a, with_email):
    _alert(agency_a, membership_a, hours_ago=100, urgent=False)

    assert escalate_for_tenant(agency_a.id) == 0


def test_each_level_happens_once(agency_a, membership_a, counselled, with_email):
    _alert(agency_a, membership_a, hours_ago=25)
    escalate_for_tenant(agency_a.id)

    assert escalate_for_tenant(agency_a.id) == 0
    assert len(mail.outbox) == 1
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=counselled).count() == 1


def test_near_a_deadline_the_ladder_is_fast(agency_a, membership_a, with_email):
    note = _alert(agency_a, membership_a, hours_ago=3, deadline_in=timedelta(hours=30))

    escalate_for_tenant(agency_a.id)

    note.refresh_from_db()
    assert note.escalation_level == 1


def test_no_counsellor_records_the_level_and_tells_no_one_else(
    agency_a, membership_a, with_email, caplog
):
    """Direct-to-student accounts: the chain ends at the student (spec, open decision 1)."""
    note = _alert(agency_a, membership_a, hours_ago=25)

    with caplog.at_level("INFO"):
        escalate_for_tenant(agency_a.id)

    note.refresh_from_db()
    assert note.escalation_level == 2
    with tenant_scope(agency_a.id):
        assert Notification.objects.exclude(recipient=membership_a).count() == 0
    assert "EscalationEnds" in caplog.text


def test_dormant_email_still_advances_the_level(settings, agency_a, membership_a):
    """No sending domain yet: the level rises so the counsellor step is not held up."""
    settings.REMINDER_EMAIL_FROM = ""
    note = _alert(agency_a, membership_a, hours_ago=13)

    escalate_for_tenant(agency_a.id)

    note.refresh_from_db()
    assert note.escalation_level == 1
    assert mail.outbox == []


def test_quiet_hours_defer_escalation(agency_a, membership_a, with_email):
    note = _alert(agency_a, membership_a, hours_ago=13)
    now = timezone.now()
    with tenant_scope(agency_a.id):
        # A window around `now`, so the test holds at any hour it runs.
        membership_a.timezone = "UTC"
        membership_a.quiet_hours_start = (now - timedelta(hours=1)).time()
        membership_a.quiet_hours_end = (now + timedelta(hours=1)).time()
        membership_a.save(update_fields=["timezone", "quiet_hours_start", "quiet_hours_end"])

    assert escalate_for_tenant(agency_a.id, now=now) == 0
    note.refresh_from_db()
    assert note.escalation_level == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch/test_escalation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.watch.escalation'`.

- [ ] **Step 3: Implement**

`apps/watch/escalation.py`:

```python
"""An urgent alert counts once a person acknowledges it; until then it climbs.

Level 1 emails the student at the address they sign in to us with (User.email),
not application_email -- that may be the application inbox they rarely open
(spec §4). Level 2 asks the assigned counsellor to reach them on WhatsApp, the
channel the reminder-ladder design found this cohort actually reads.

Design: docs/superpowers/specs/2026-09-25-application-watch-design.md §4.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.concierge.models import Notification
from apps.portals.reminders import held_for_quiet_hours
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import CounselorAssignment

from .rules import escalation_target

logger = logging.getLogger(__name__)

_TOP_LEVEL = 2


def escalate_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int:
    moment = now or timezone.now()
    with tenant_scope(tenant_id):
        with tenant_transaction(tenant_id):
            pending = list(
                Notification.objects.filter(
                    urgent=True,
                    acknowledged_at__isnull=True,
                    escalation_level__lt=_TOP_LEVEL,
                ).values_list("id", flat=True)
            )
        raised = 0
        for notification_id in pending:
            try:
                with tenant_transaction(tenant_id):
                    if _escalate_one(notification_id, moment):
                        raised += 1
            except Exception:
                logger.exception("EscalationFailed notification=%s", notification_id)
        return raised


def _escalate_one(notification_id: UUID, moment: datetime) -> bool:
    # Locked: two overlapping sweeps must not both send level 1.
    note = (
        Notification.objects.select_for_update()
        .select_related("recipient__user", "roadmap_item")
        .get(id=notification_id)
    )
    if note.acknowledged_at is not None:
        return False
    target = escalation_target(note.created_at, moment, note.roadmap_item.deadline)
    if target <= note.escalation_level:
        return False
    if held_for_quiet_hours(note.recipient, moment):
        return False
    for level in range(note.escalation_level + 1, target + 1):
        if level == 1:
            _email_student(note)
        elif level == 2:
            _tell_counselor(note)
    note.escalation_level = target
    note.save(update_fields=["escalation_level"])
    return True


def _email_student(note: Notification) -> None:
    if not settings.REMINDER_EMAIL_FROM:
        logger.info("EscalationEmailSkipped reason=unconfigured notification=%s", note.id)
        return
    address = note.recipient.user.email
    if not address:
        logger.info("EscalationEmailSkipped reason=no_address notification=%s", note.id)
        return
    send_mail(
        subject="Action needed on your applications",
        message=f"{note.message}\n\nOpen your dashboard to see it and mark it done.",
        from_email=settings.REMINDER_EMAIL_FROM,
        recipient_list=[address],
    )


def _tell_counselor(note: Notification) -> None:
    assignment = (
        CounselorAssignment.objects.filter(student=note.recipient, active=True)
        .select_related("counselor")
        .first()
    )
    if assignment is None:
        # Direct-to-student account: nobody else to tell (spec, open decision 1).
        logger.info("EscalationEnds reason=no_counselor notification=%s", note.id)
        return
    Notification.objects.create(
        tenant=note.tenant,
        recipient=assignment.counselor,
        roadmap_item=note.roadmap_item,
        message=(
            f"Unanswered by your student: {note.message} "
            "Message this student on WhatsApp now."
        ),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch/test_escalation.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/watch/escalation.py tests/watch/test_escalation.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(watch): escalate an unacknowledged urgent alert to email, then the counsellor

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Heartbeats, and the command that runs both sweeps

**Files:**
- Create: `apps/watch/heartbeat.py`, `apps/watch/management/__init__.py` (empty), `apps/watch/management/commands/__init__.py` (empty), `apps/watch/management/commands/watch_applications.py`
- Modify: `apps/portals/management/commands/send_due_reminders.py` (end of `handle`)
- Modify: `apps/mailbox/management/commands/sync_mailboxes.py` (end of `handle`)
- Test: `tests/watch/test_heartbeat.py`, `tests/watch/test_command.py`

**Interfaces:**
- Consumes: `JobRun` (Task 1), `watch_applications_for_tenant` (Task 3), `escalate_for_tenant` (Task 4).
- Produces: `record_run(name: str, *, now: datetime | None = None) -> None`; `silent_jobs(*, now: datetime | None = None) -> list[str]`; `report_silent(*, now: datetime | None = None) -> list[str]` (logs `JobSilent job=<name>` at ERROR for each); `EXPECTED_JOBS: dict[str, timedelta]`; management command `watch_applications`.

- [ ] **Step 1: Write the failing tests**

`tests/watch/test_heartbeat.py`:

```python
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.watch.heartbeat import EXPECTED_JOBS, record_run, report_silent, silent_jobs

pytestmark = pytest.mark.django_db


def test_a_job_that_has_never_run_is_silent():
    """First deploy, or a rule shipped disabled: never having run is not health."""
    assert set(silent_jobs()) == set(EXPECTED_JOBS)


def test_a_recent_run_is_not_silent():
    for name in EXPECTED_JOBS:
        record_run(name)
    assert silent_jobs() == []


def test_a_run_older_than_its_window_is_silent():
    now = timezone.now()
    for name, window in EXPECTED_JOBS.items():
        record_run(name, now=now - window - timedelta(minutes=1))
    assert set(silent_jobs(now=now)) == set(EXPECTED_JOBS)


def test_silence_is_logged_by_name_for_the_alarm(caplog):
    with caplog.at_level("ERROR"):
        report_silent()
    for name in EXPECTED_JOBS:
        assert f"JobSilent job={name}" in caplog.text


def test_both_hourly_jobs_are_watched():
    assert set(EXPECTED_JOBS) == {"send_due_reminders", "watch_applications"}
```

`tests/watch/test_command.py`:

```python
import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.concierge.models import Notification
from apps.portals.models import Application, ApplicationStep, PortalForm
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.watch.models import JobRun


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


def _overdue(agency, student, portal_form):
    application = Application.objects.create(
        tenant=agency,
        student=student,
        program_id=uuid.uuid4(),
        portal_form=portal_form,
        state="SUBMITTED",
    )
    step = ApplicationStep.objects.create(
        tenant=agency, application=application, sequence=1, kind="SUBMITTED"
    )
    ApplicationStep.objects.filter(pk=step.pk).update(
        created_at=timezone.now() - timedelta(hours=49)
    )


@pytest.mark.django_db
def test_the_command_watches_every_agency_and_records_its_run(
    agency_a, membership_a, agency_b, membership_b, portal_form
):
    with tenant_scope(agency_a.id):
        _overdue(agency_a, membership_a, portal_form)
    with tenant_scope(agency_b.id):
        _overdue(agency_b, membership_b, portal_form)

    call_command("watch_applications")

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1
    with tenant_scope(agency_b.id):
        assert Notification.objects.filter(recipient=membership_b).count() == 1
    assert JobRun.objects.filter(name="watch_applications").exists()


@pytest.mark.django_db
def test_the_reminder_command_records_its_run_too(agency_a):
    call_command("send_due_reminders")
    assert JobRun.objects.filter(name="send_due_reminders").exists()


@pytest.mark.django_db(transaction=True)
def test_the_command_works_behind_real_row_level_security(
    agency_a, membership_a, portal_form, rls_enforced_orm
):
    """As the production runtime role a scan missing its GUC returns zero rows,
    exits 0, and no alert is ever raised."""
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _overdue(agency_a, membership_a, portal_form)

    call_command("watch_applications")

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch/test_heartbeat.py tests/watch/test_command.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.watch.heartbeat'`.

- [ ] **Step 3: Implement the heartbeat**

`apps/watch/heartbeat.py`:

```python
"""Every scheduled job says when it finished; each checks the others.

A job that stops is otherwise invisible: the reminders simply never arrive and
every screen looks right. The ERROR line is what the CloudWatch metric filter
on the worker log group counts (infra/template.yaml, JobSilentAlarm). Both
hourly commands call report_silent, so either one notices the other stopping.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.utils import timezone

from .models import JobRun

logger = logging.getLogger(__name__)

#: Job name (the management command) -> how long without a finished run is
#: silence. Two hours for an hourly job tolerates one missed run's jitter.
#: sync_mailboxes joins this list when its schedule ships (plan 2) -- listing it
#: before then would alarm on a job nothing is meant to run yet.
EXPECTED_JOBS: dict[str, timedelta] = {
    "send_due_reminders": timedelta(hours=2),
    "watch_applications": timedelta(hours=2),
}


def record_run(name: str, *, now: datetime | None = None) -> None:
    JobRun.objects.update_or_create(
        name=name, defaults={"last_success_at": now or timezone.now()}
    )


def silent_jobs(*, now: datetime | None = None) -> list[str]:
    moment = now or timezone.now()
    last = dict(JobRun.objects.values_list("name", "last_success_at"))
    return [
        name
        for name, window in EXPECTED_JOBS.items()
        if name not in last or moment - last[name] > window
    ]


def report_silent(*, now: datetime | None = None) -> list[str]:
    silent = silent_jobs(now=now)
    for name in silent:
        logger.error("JobSilent job=%s", name)
    return silent
```

- [ ] **Step 4: Implement the command**

`apps/watch/management/commands/watch_applications.py`:

```python
"""Raise overdue-expectation alerts and escalate unacknowledged urgent ones.

Invoked hourly by WatchApplicationsRule (infra/template.yaml).
Design: docs/superpowers/specs/2026-09-25-application-watch-design.md §4, §5.
"""

from django.core.management.base import BaseCommand

from apps.tenancy.models import Agency
from apps.watch.escalation import escalate_for_tenant
from apps.watch.heartbeat import record_run, report_silent
from apps.watch.watchdog import watch_applications_for_tenant


class Command(BaseCommand):
    help = "Alert on overdue expectations and escalate unacknowledged urgent alerts"

    def handle(self, *_args: object, **_options: object) -> None:
        # Agency carries no RLS policy, so listing it as the runtime role works.
        # Each sweep sets its own tenant_scope; none is held across the loop,
        # because tenant_scope refuses to switch tenants.
        for agency in Agency.objects.all():
            watch_applications_for_tenant(agency.id)
            escalate_for_tenant(agency.id)
        # Recorded only after the loop: a run that died halfway did not finish.
        record_run("watch_applications")
        report_silent()
```

In `apps/portals/management/commands/send_due_reminders.py` add the import and extend `handle`:

```python
from apps.watch.heartbeat import record_run, report_silent
```

```python
        for agency in Agency.objects.all():
            send_due_reminders_for_tenant(agency.id)
        record_run("send_due_reminders")
        report_silent()
```

In `apps/mailbox/management/commands/sync_mailboxes.py` add `from apps.watch.heartbeat import record_run` and, as the last line of `handle` (after the agency loop):

```python
        record_run("sync_mailboxes")
```

- [ ] **Step 5: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch tests/portals/test_send_due_reminders_command.py tests/mailbox/test_command.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/watch tests/watch apps/portals/management/commands/send_due_reminders.py apps/mailbox/management/commands/sync_mailboxes.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(watch): the hourly command, and jobs that notice each other stopping

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The schedule and the alarms

**Files:**
- Modify: `infra/template.yaml` — add `WatchApplicationsRule` directly after `ReminderLadderRule`; add `ReminderLadderRuleFailedInvocationsAlarm`, `WatchApplicationsRuleFailedInvocationsAlarm`, `JobSilentMetricFilter`, `JobSilentAlarm` after `WorkerLogGroup`.
- Modify: `docs/runbooks/deploy.md` — "Scheduled commands" section.
- Test: `tests/infra/test_template.py` (append a section)

**Interfaces:**
- Consumes: the `watch_applications` command (Task 5) and the `JobSilent job=<name>` log line (Task 5).

- [ ] **Step 1: Write the failing tests**

Append to `tests/infra/test_template.py`:

```python
# --- The application watch's schedule and its alarms ---------------------------


def test_the_watch_runs_hourly_and_ships_enabled(template: Template) -> None:
    rule = template.resource("WatchApplicationsRule")["Properties"]
    assert rule["ScheduleExpression"] == "rate(1 hour)"
    assert rule["State"] == "ENABLED"
    parameters = rule["Targets"][0]["EcsParameters"]
    assert parameters["TaskDefinitionArn"] == {"Ref": "WorkerTaskDefinition"}


def test_the_watch_invokes_the_command_that_exists(template: Template) -> None:
    raw_input = template.resource("WatchApplicationsRule")["Properties"]["Targets"][0]["Input"]
    overrides = json.loads(raw_input["Fn::Sub"])["containerOverrides"][0]
    assert overrides["name"] == "worker"
    assert overrides["command"] == ["python", "manage.py", "watch_applications"]


@pytest.mark.parametrize("rule", ["ReminderLadderRule", "WatchApplicationsRule"])
def test_a_schedule_that_stops_invoking_sets_off_an_alarm(template: Template, rule: str) -> None:
    alarm = template.resource(f"{rule}FailedInvocationsAlarm")["Properties"]
    assert alarm["Namespace"] == "AWS/Events"
    assert alarm["MetricName"] == "FailedInvocations"
    assert alarm["Dimensions"] == [{"Name": "RuleName", "Value": {"Ref": rule}}]
    assert alarm["Threshold"] == 0
    assert alarm["ComparisonOperator"] == "GreaterThanThreshold"


def test_a_silent_job_sets_off_an_alarm(template: Template) -> None:
    """A task that starts and dies is a successful invocation; only the jobs'
    own heartbeat check can see it (apps/watch/heartbeat.py)."""
    metric_filter = template.resource("JobSilentMetricFilter")["Properties"]
    assert metric_filter["LogGroupName"] == {"Ref": "WorkerLogGroup"}
    assert "JobSilent" in metric_filter["FilterPattern"]
    transformation = metric_filter["MetricTransformations"][0]
    alarm = template.resource("JobSilentAlarm")["Properties"]
    assert alarm["Namespace"] == transformation["MetricNamespace"]
    assert alarm["MetricName"] == transformation["MetricName"]
    assert alarm["Threshold"] == 0
    assert alarm["ComparisonOperator"] == "GreaterThanThreshold"
    assert alarm["TreatMissingData"] == "notBreaching"
```

(Check the top of the file already imports `json` and `pytest`; add either import if missing.)

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/infra/test_template.py -q -k "watch or silent or stops_invoking"`
Expected: FAIL — `WatchApplicationsRule is not defined in infra/template.yaml`.

- [ ] **Step 3: Add the resources**

In `infra/template.yaml`, directly after the `ReminderLadderRule` resource:

```yaml
  # Hourly, like the ladder it complements: an escalation's fast ladder steps
  # at 2 and 4 hours, which a daily job cannot hit. Shipped enabled -- a watch
  # nothing invokes watches nothing, with every screen saying the right thing.
  WatchApplicationsRule:
    Type: AWS::Events::Rule
    Properties:
      Description: Alert on overdue expectations and escalate unacknowledged alerts
      ScheduleExpression: "rate(1 hour)"
      State: ENABLED
      Targets:
        - Id: watch-applications
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
             "command":["python","manage.py","watch_applications"]}]}

  ReminderLadderRuleFailedInvocationsAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: AWS/Events
      MetricName: FailedInvocations
      Dimensions:
        - Name: RuleName
          Value: !Ref ReminderLadderRule
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching

  WatchApplicationsRuleFailedInvocationsAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: AWS/Events
      MetricName: FailedInvocations
      Dimensions:
        - Name: RuleName
          Value: !Ref WatchApplicationsRule
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
```

Directly after the `WorkerLogGroup` resource:

```yaml
  # apps/watch/heartbeat.py logs "JobSilent job=<name>" at ERROR when a scheduled
  # command has not finished within its window. A task that starts and dies is
  # a successful EventBridge invocation, so the FailedInvocations alarms cannot
  # see it; this can.
  JobSilentMetricFilter:
    Type: AWS::Logs::MetricFilter
    Properties:
      LogGroupName: !Ref WorkerLogGroup
      FilterPattern: '"JobSilent"'
      MetricTransformations:
        - MetricNamespace: Tehsil/Jobs
          MetricName: JobSilent
          MetricValue: "1"

  JobSilentAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: Tehsil/Jobs
      MetricName: JobSilent
      Statistic: Sum
      Period: 3600
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
```

- [ ] **Step 4: Update the runbook**

In `docs/runbooks/deploy.md`, at the end of the "Scheduled commands — run by hand until the schedule exists" section, add:

```markdown
Two hourly commands are scheduled and need nothing by hand: `send_due_reminders`
(`ReminderLadderRule`) and `watch_applications` (`WatchApplicationsRule`, which raises
overdue-confirmation alerts and escalates unacknowledged urgent ones). Each records its last
finished run in `watch_jobrun` and logs `JobSilent job=<name>` when the other has not
finished within two hours; `JobSilentAlarm` counts those lines. The alarms have no action
attached yet — wire them to a notification topic when one exists.
```

- [ ] **Step 5: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/infra/test_template.py -q`
Expected: all PASS. If an existing test pins an exact list of alarms or rules and now fails, add the new names to that list — do not loosen it to a subset check.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add infra/template.yaml tests/infra/test_template.py docs/runbooks/deploy.md
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(infra): schedule the application watch and alarm on silent jobs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Whole-branch verification

**Files:** none new.

- [ ] **Step 1: Run every repository gate**

```bash
cd /home/orkhan/Desktop/mailbox-port
uv run ruff check .
uv run mypy apps config
uv run bandit -q -c pyproject.toml -r apps config
POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=tehsil_mailbox_port uv run pytest -q
```

Expected: ruff "All checks passed!", mypy "Success", bandit no issues, "No changes detected", and the full suite passing with no new failures against the 3963-passed baseline.

- [ ] **Step 2: Prove the idempotency tests bite (mutation check, then restore)**

Temporarily replace `select_for_update().get(` with `.get(` in `apps/watch/watchdog.py`, then run
`POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch -q`. The row lock cannot be exercised by a single-threaded test, so expect this to still pass — record that in the report as a known limit, restore the file with `git -C /home/orkhan/Desktop/mailbox-port checkout apps/watch/watchdog.py`, and confirm `git status` is clean. Then make `_watch_one` skip the `alerted_id is not None` check and confirm `test_a_second_sweep_does_not_alert_again` fails; restore.

- [ ] **Step 3: Report**

List the commands run and their results, the mutation outcomes, and the known limit (concurrency is protected by the row lock but not proven by a test).
