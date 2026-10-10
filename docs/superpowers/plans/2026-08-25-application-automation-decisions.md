# Application-Automation Decisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agent-performed actions representable in the audit trail and the roadmap, before Phase 3 starts writing them, and record the four constraints that govern how Phase 3 gets built.

**Architecture:** Two schema changes and no behaviour change. `funding.AuditEvent` gains an `actor_kind` discriminator so an agent action is distinguishable from a system write — today both would carry `actor=NULL`. `concierge.RoadmapItem` gains `owner_kind` and a nullable `owner` so the agent can hold a step without a fake `Membership` row. Both get a CHECK constraint tying the discriminator to the FK, so the invariant is enforced by the database rather than by convention.

**Tech Stack:** Django 5.2, PostgreSQL (row-level security + composite tenant FKs), pytest + pytest-django, `uv` for all commands.

**Spec:** `docs/superpowers/specs/2026-08-25-application-automation-decisions-design.md`

## Global Constraints

- **`funding_auditevent` is append-only, enforced by a row trigger.** `apps/funding/migrations/0011_audit_event_append_only.py` installs `funding_auditevent_no_update` and `funding_auditevent_no_delete`, both `BEFORE ... FOR EACH ROW`, both raising `'audit_event rows are append-only'`. **Any ordinary data migration that UPDATEs this table will fail.** Task 1 disables the trigger for exactly one statement and re-enables it, and tests that it is armed again afterwards.
- **Every model here extends `TenantScopedModel`** (`apps/tenancy/models.py:47`), which forces `tenant_id` on save and raises `ValueError("tenant mismatch")` on a cross-tenant write. Model writes in tests must happen inside `with tenant_scope(agency.id):`.
- **Both tables already carry RLS and composite tenant FKs.** `funding_auditevent` from `funding/0002_tenant_guards.py` (`event_actor_tenant_fk`), `concierge_roadmapitem` from `concierge/0002_tenant_guards.py` (`roadmap_owner_tenant_fk`, `roadmap_student_tenant_fk`). Do not drop or recreate these.
- **No behaviour changes.** No view, template, service or `record_event` signature changes in this plan. `record_event` gains its `actor_kind` argument in Phase 3, not here.
- **`tests/concierge/test_roadmap.py::test_no_payment_or_portal_automation_call` must remain untouched and passing.** It is a decision, not scaffolding (spec Decision 6).
- Run everything through `uv run`. Full suite: `uv run pytest tests/ -q`. Checks: `uv run ruff check apps config tests`, `uv run mypy apps config`, `uv run python manage.py makemigrations --check --dry-run`.
- Next migration numbers: **`funding/0015_...`**, **`concierge/0005_...`**.

---

### Task 1: `AuditEvent.actor_kind`

Distinguishes an agent action from a system write. Today `apps/documents/audit.py::record_event` is called with `actor=None` by exactly one caller (`apps/documents/format_resolution.py:167`, `document.format_unverified`), and that null means "no human actor". In Phase 3 an agent action would also carry `actor=None`. After this task, `actor_id IS NOT NULL` ⟺ `HUMAN`, and the two null cases are told apart by `actor_kind`.

**Files:**
- Modify: `apps/funding/models.py:189-200` (the `AuditEvent` class)
- Create: `apps/funding/migrations/0015_audit_event_actor_kind.py`
- Test: `tests/migrations/test_audit_event_actor_kind.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `AuditEvent.ActorKind` — a `models.TextChoices` with members `HUMAN = "HUMAN"`, `SYSTEM = "SYSTEM"`, `AGENT = "AGENT"`; and field `AuditEvent.actor_kind: CharField(max_length=10, choices=ActorKind.choices, default=ActorKind.HUMAN)`. Task 2 mirrors this shape but does **not** import it.

- [ ] **Step 1: Write the failing test**

Create `tests/migrations/test_audit_event_actor_kind.py`:

```python
# tests/migrations/test_audit_event_actor_kind.py
import pytest
from django.db import connection, transaction
from django.db.utils import InternalError, ProgrammingError

from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope


@pytest.mark.django_db
def test_a_human_event_records_a_membership_actor(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        event = AuditEvent.objects.create(
            actor=membership_a, event="document.approved", object_id=membership_a.id
        )
    assert event.actor_kind == AuditEvent.ActorKind.HUMAN


@pytest.mark.django_db
def test_an_agent_event_is_distinguishable_from_a_system_event(agency_a):
    """The whole point of the discriminator: before it, both of these were
    actor=NULL and indistinguishable."""
    with tenant_scope(agency_a.id):
        system = AuditEvent.objects.create(
            actor=None,
            actor_kind=AuditEvent.ActorKind.SYSTEM,
            event="document.format_unverified",
            object_id=agency_a.id,
        )
        agent = AuditEvent.objects.create(
            actor=None,
            actor_kind=AuditEvent.ActorKind.AGENT,
            event="portal.form_prepared",
            object_id=agency_a.id,
        )
    assert system.actor_kind != agent.actor_kind


@pytest.mark.django_db(transaction=True)
def test_a_human_event_cannot_have_a_null_actor(agency_a):
    with tenant_scope(agency_a.id):
        with pytest.raises((InternalError, ProgrammingError, Exception)):
            with transaction.atomic():
                AuditEvent.objects.create(
                    actor=None,
                    actor_kind=AuditEvent.ActorKind.HUMAN,
                    event="bogus",
                    object_id=agency_a.id,
                )


@pytest.mark.django_db(transaction=True)
def test_an_agent_event_cannot_carry_a_membership(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        with pytest.raises((InternalError, ProgrammingError, Exception)):
            with transaction.atomic():
                AuditEvent.objects.create(
                    actor=membership_a,
                    actor_kind=AuditEvent.ActorKind.AGENT,
                    event="bogus",
                    object_id=agency_a.id,
                )


@pytest.mark.django_db(transaction=True)
def test_the_append_only_trigger_is_still_armed_after_the_migration(agency_a, membership_a):
    """The migration disables this trigger to backfill. If it fails to
    re-enable it, the audit trail silently stops being append-only and every
    other test in the suite still passes."""
    with tenant_scope(agency_a.id):
        event = AuditEvent.objects.create(
            actor=membership_a, event="document.approved", object_id=membership_a.id
        )
    with pytest.raises(Exception, match="append-only"):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE funding_auditevent SET event = 'tampered' WHERE id = %s",
                    [str(event.id)],
                )


@pytest.mark.django_db
def test_both_append_only_triggers_are_enabled_in_pg_catalog():
    """tgenabled 'O' means origin-enabled; 'D' means the migration left it
    disabled. Asserted directly because a DISABLE/ENABLE pair is easy to get
    half-right."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tgname, tgenabled FROM pg_trigger
            WHERE tgrelid = 'funding_auditevent'::regclass AND NOT tgisinternal
            ORDER BY tgname
            """
        )
        rows = dict(cursor.fetchall())
    assert rows == {
        "funding_auditevent_no_delete": "O",
        "funding_auditevent_no_update": "O",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/migrations/test_audit_event_actor_kind.py -q`
Expected: FAIL. The first errors are `AttributeError: type object 'AuditEvent' has no attribute 'ActorKind'`.

- [ ] **Step 3: Add the field to the model**

In `apps/funding/models.py`, replace the `AuditEvent` class body with:

```python
class AuditEvent(TenantScopedModel):
    class ActorKind(models.TextChoices):
        HUMAN = "HUMAN", "Human"
        SYSTEM = "SYSTEM", "Platform, no actor"
        AGENT = "AGENT", "Autonomous agent"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    actor = models.ForeignKey(Membership, null=True, on_delete=models.PROTECT)
    #: Which of the three wrote this. `actor` alone cannot answer it: a
    #: platform write and a Phase 3 agent write both carry actor=NULL, and
    #: `phased requirements.md` §3.2 requires them to be distinguishable in
    #: the exported dossier. Counselor vs student stays derivable from the
    #: Membership's own role, so this discriminates only what the FK cannot.
    actor_kind = models.CharField(
        max_length=10, choices=ActorKind.choices, default=ActorKind.HUMAN
    )
    event = models.CharField(max_length=100)
    object_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="event_tenant_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(actor_kind="HUMAN", actor__isnull=False)
                | models.Q(actor__isnull=True) & ~models.Q(actor_kind="HUMAN"),
                name="event_actor_kind_matches_actor",
            ),
        ]
```

Note: `condition=` is the Django 5.1+ spelling; this repo is on Django 5.2. If a `TypeError` mentions `check`, the installed Django is older than assumed — stop and report rather than switching spellings blindly.

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations funding --name audit_event_actor_kind`
Expected: creates `apps/funding/migrations/0015_audit_event_actor_kind.py` with an `AddField` and an `AddConstraint`.

- [ ] **Step 5: Add the trigger-safe backfill to the migration**

Open `apps/funding/migrations/0015_audit_event_actor_kind.py`. Keep the generated `AddField`, then insert the backfill **between** the `AddField` and the `AddConstraint` — the constraint cannot be added while mislabelled rows exist. The file's `operations` list must end up in this order:

```python
_BACKFILL_SQL = """
-- funding_auditevent carries BEFORE UPDATE/DELETE row triggers that raise on
-- every write (migration 0011). AddField above is a catalog-only change on
-- PostgreSQL 11+ and does not fire them, but this backfill is a real UPDATE
-- and would. Disabling for one statement is the narrow, auditable exception;
-- tests/migrations/test_audit_event_actor_kind.py asserts both triggers are
-- back to 'O' (origin-enabled) afterwards.
ALTER TABLE funding_auditevent DISABLE TRIGGER USER;
UPDATE funding_auditevent SET actor_kind = 'SYSTEM' WHERE actor_id IS NULL;
ALTER TABLE funding_auditevent ENABLE TRIGGER USER;
"""

_REVERSE_BACKFILL_SQL = """
ALTER TABLE funding_auditevent DISABLE TRIGGER USER;
UPDATE funding_auditevent SET actor_kind = 'HUMAN' WHERE actor_id IS NULL;
ALTER TABLE funding_auditevent ENABLE TRIGGER USER;
"""
```

and in `operations`, after the `AddField` and before the `AddConstraint`:

```python
        migrations.RunSQL(_BACKFILL_SQL, _REVERSE_BACKFILL_SQL),
```

`ALTER TABLE ... DISABLE TRIGGER USER` requires ownership of the table. If it raises `must be owner of relation funding_auditevent`, the migration role differs from the table owner — stop and report; do not switch to `SESSION_REPLICATION_ROLE`, which needs superuser and would disable RLS too.

- [ ] **Step 6: Apply the migration and run the tests**

Run: `uv run pytest tests/migrations/test_audit_event_actor_kind.py -q`
Expected: PASS, 6 passed.

- [ ] **Step 7: Confirm nothing else broke**

Run: `uv run pytest tests/ -q && uv run ruff check apps config tests && uv run mypy apps config && uv run python manage.py makemigrations --check --dry-run`
Expected: full suite green, `No changes detected`.

If `tests/test_aws_boundary_run_controller.py::test_image_publication_uses_substituted_commands_without_printing_registry` fails, it is a known pre-existing flake unrelated to this work — `scripts/run_aws_boundary_validation.sh:90` pipes `aws_cli ecr get-login-password` into `docker_cli login`, and both halves append to the same trace file concurrently, so their order flips under load. Re-run to confirm, and do not "fix" it in this task.

- [ ] **Step 8: Commit**

```bash
git add apps/funding/models.py apps/funding/migrations/0015_audit_event_actor_kind.py tests/migrations/test_audit_event_actor_kind.py
git commit -m "feat(audit): discriminate agent actions from platform writes

AuditEvent.actor is nullable, and null means 'no human actor'. A Phase 3
agent action would land in that same bucket, at exactly the point
phased requirements.md §3.2 requires automated, counselor, student and
platform-administrator actions to be distinguishable in the exported
dossier. Nothing in an existing row could separate them afterwards, so a
later backfill would be a guess written into the audit trail.

actor_kind discriminates only what the FK cannot: counselor vs student
stays derivable from the Membership's own role. A CHECK constraint ties
the value to the FK so the invariant is the database's, not a
convention.

The backfill disables the append-only triggers from migration 0011 for a
single statement, because they raise on every UPDATE. A test asserts
both are back to origin-enabled in pg_trigger afterwards -- a
half-completed DISABLE/ENABLE pair would silently end the append-only
guarantee with every other test still green."
```

---

### Task 2: `RoadmapItem` owned by the agent

`RoadmapItem.owner` is a non-null FK to `Membership`, so every owner is a person. `phased requirements.md` §5.2 requires the dashboard to show the **owner** of an agent-held step. Spec Decision 2 rejects a synthetic "agent" `Membership` because that row would be a real principal with roles, MFA and RLS standing — and would defeat Task 1 by giving agent actions a `Membership` id.

**Files:**
- Modify: `apps/concierge/models.py:10-45` (the `RoadmapItem` class)
- Create: `apps/concierge/migrations/0005_roadmap_item_agent_owner.py`
- Test: `tests/concierge/test_roadmap_agent_owner.py`

**Interfaces:**
- Consumes: nothing from Task 1. The discriminator shape is deliberately duplicated rather than shared — the two models have different value sets (`RoadmapItem` has no `SYSTEM`), and a shared enum would couple `concierge` to `funding`.
- Produces: `RoadmapItem.OwnerKind` — a `models.TextChoices` with `HUMAN = "HUMAN"`, `AGENT = "AGENT"`; field `RoadmapItem.owner_kind: CharField(max_length=10, choices=OwnerKind.choices, default=OwnerKind.HUMAN)`; and `RoadmapItem.owner` becomes `null=True`.

- [ ] **Step 1: Write the failing test**

Create `tests/concierge/test_roadmap_agent_owner.py`:

```python
# tests/concierge/test_roadmap_agent_owner.py
from datetime import timedelta

import pytest
from django.db import transaction
from django.db.utils import IntegrityError, InternalError, ProgrammingError
from django.utils import timezone

from apps.concierge.models import RoadmapItem
from apps.tenancy.context import tenant_scope


def _deadline():
    return timezone.now() + timedelta(days=14)


@pytest.mark.django_db
def test_a_counselor_owned_item_is_unchanged(agency_a, membership_a, counselor_membership):
    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.DOCUMENTS,
            owner=counselor_membership,
            deadline=_deadline(),
        )
    assert item.owner_kind == RoadmapItem.OwnerKind.HUMAN
    assert item.owner == counselor_membership


@pytest.mark.django_db
def test_the_agent_can_own_an_item_without_a_membership(agency_a, membership_a):
    """§5.2 requires showing the owner of an agent-held step. This must not
    require a synthetic Membership row -- see the spec's Decision 2."""
    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.PORTAL_EXCEPTION,
            owner=None,
            owner_kind=RoadmapItem.OwnerKind.AGENT,
            deadline=_deadline(),
        )
    assert item.owner is None
    assert item.owner_kind == RoadmapItem.OwnerKind.AGENT


@pytest.mark.django_db(transaction=True)
def test_an_unowned_item_is_not_silently_an_agent_item(agency_a, membership_a):
    """Nullable owner without the discriminator would make 'nobody owns this'
    and 'the agent owns this' the same row. The constraint forbids the first."""
    with tenant_scope(agency_a.id):
        with pytest.raises((IntegrityError, InternalError, ProgrammingError)):
            with transaction.atomic():
                RoadmapItem.objects.create(
                    tenant=agency_a,
                    student=membership_a,
                    stage=RoadmapItem.Stage.DOCUMENTS,
                    owner=None,
                    owner_kind=RoadmapItem.OwnerKind.HUMAN,
                    deadline=_deadline(),
                )


@pytest.mark.django_db(transaction=True)
def test_an_agent_item_cannot_also_carry_a_person(agency_a, membership_a, counselor_membership):
    with tenant_scope(agency_a.id):
        with pytest.raises((IntegrityError, InternalError, ProgrammingError)):
            with transaction.atomic():
                RoadmapItem.objects.create(
                    tenant=agency_a,
                    student=membership_a,
                    stage=RoadmapItem.Stage.DOCUMENTS,
                    owner=counselor_membership,
                    owner_kind=RoadmapItem.OwnerKind.AGENT,
                    deadline=_deadline(),
                )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/concierge/test_roadmap_agent_owner.py -q`
Expected: FAIL with `AttributeError: type object 'RoadmapItem' has no attribute 'OwnerKind'`.

- [ ] **Step 3: Change the model**

In `apps/concierge/models.py`, inside `class RoadmapItem`, add the enum after the existing `State` class, change the `owner` field, add `owner_kind`, and add the constraint to `Meta`:

```python
    class OwnerKind(models.TextChoices):
        HUMAN = "HUMAN", "Human"
        AGENT = "AGENT", "Autonomous agent"

    owner = models.ForeignKey(
        Membership, null=True, on_delete=models.PROTECT, related_name="owned_roadmap_items"
    )
    #: The agent owns steps too (`phased requirements.md` §5.2 shows an owner
    #: for every step), and it has no Membership. A synthetic "agent" member
    #: was rejected: Membership is the tenancy primitive, so that row would be
    #: a real principal carrying roles, MFA and RLS standing. Nullable `owner`
    #: alone would make "unowned" and "agent-owned" the same row, so the two
    #: fields are constrained together.
    owner_kind = models.CharField(
        max_length=10, choices=OwnerKind.choices, default=OwnerKind.HUMAN
    )
```

and in `class Meta`, alongside the existing constraint:

```python
            models.CheckConstraint(
                condition=models.Q(owner_kind="HUMAN", owner__isnull=False)
                | models.Q(owner_kind="AGENT", owner__isnull=True),
                name="roadmapitem_owner_kind_matches_owner",
            ),
```

`RoadmapItem.Meta.constraints` already exists and holds `UniqueConstraint(fields=("tenant", "id"), name="roadmap_tenant_id_uniq")`. Append to that list; do not replace it.

- [ ] **Step 4: Generate and inspect the migration**

Run: `uv run python manage.py makemigrations concierge --name roadmap_item_agent_owner`
Expected: `apps/concierge/migrations/0005_roadmap_item_agent_owner.py` with `AddField(owner_kind)`, `AlterField(owner)` and `AddConstraint`.

No data migration is needed: every existing row has a non-null `owner` and takes the `HUMAN` default, which already satisfies the constraint. There is no append-only trigger on this table.

`concierge_roadmapitem` carries the composite FK `roadmap_owner_tenant_fk (tenant_id, owner_id)` from `concierge/0002_tenant_guards.py`. Dropping `NOT NULL` does not affect it — PostgreSQL's default `MATCH SIMPLE` skips the check when any referencing column is NULL. Do not drop or recreate that constraint.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/concierge/ -q`
Expected: PASS, including the pre-existing `test_no_payment_or_portal_automation_call`.

- [ ] **Step 6: Check the read paths that assume an owner exists**

Two places read `owner`, and both must still be correct now that it can be NULL:

- `apps/concierge/views.py:54` — `get_object_or_404(RoadmapItem, id=item_id, owner=counselor)`. Filtering by a concrete counselor never matches a NULL owner, so an agent-owned item is simply not returned. Correct as-is; make no change.
- `templates/owner/dashboard.html:9` — `Counselor: {{ item.owner.display_name }}`. Django renders an empty string for an attribute on `None` rather than raising, so an agent-owned item would display `Counselor: ` with nothing after it.

Fix only the template, minimally:

```html
    <span>{% if item.owner %}Counselor: {{ item.owner.display_name }}{% else %}Owner: Agent{% endif %}</span>
```

- [ ] **Step 7: Run the full suite and the checks**

Run: `uv run pytest tests/ -q && uv run ruff check apps config tests && uv run mypy apps config && uv run python manage.py makemigrations --check --dry-run`
Expected: full suite green, `No changes detected`. (See Task 1 Step 7 for the known boundary-controller flake.)

- [ ] **Step 8: Commit**

```bash
git add apps/concierge/models.py apps/concierge/migrations/0005_roadmap_item_agent_owner.py tests/concierge/test_roadmap_agent_owner.py templates/owner/dashboard.html
git commit -m "feat(concierge): let the agent own a roadmap item

RoadmapItem.owner was a non-null FK to Membership, so every owner was a
person -- but phased requirements.md §5.2 requires showing the owner of
an agent-held step, and Stage already has PORTAL_EXCEPTION and
SUBMISSION waiting for one.

A synthetic 'agent' Membership was the obvious workaround and is
rejected: Membership is the tenancy primitive, so that row would be a
real principal with roles, MFA, notification routing and RLS standing,
assignable to permissions and visible in counselor lists.

Nullable owner alone would conflate 'unowned' with 'agent-owned', so
owner_kind is constrained against owner in the database. The owner
dashboard now names the agent instead of rendering an empty
'Counselor: '."
```

---

### Task 3: Record the constraints that add no code

Spec Decisions 3–6 govern work that has not started. They belong where the next person writing that work will actually see them, which in this repo is `CLAUDE.md` — it is loaded into every session and already carries the web-fetching rules this extends.

**Files:**
- Modify: `CLAUDE.md` (add one section after the existing `## Web fetching` section, before `## LLM/AI security`)
- Test: none. This task changes no code; the full suite is run to confirm that.

**Interfaces:**
- Consumes: the field names produced by Tasks 1 and 2 (`AuditEvent.actor_kind`, `RoadmapItem.owner_kind`), referenced in the text.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the section to `CLAUDE.md`**

Insert immediately before the `## LLM/AI security` heading:

```markdown
## Application automation (Phase 3) — decided in advance

Full reasoning in `docs/superpowers/specs/2026-08-25-application-automation-decisions-design.md`.
These bind work that has not started yet, which is exactly why they are written down.

- **Portal credentials never live in the database.** `phased requirements.md` §5.2 has the
  platform reauthenticating with managed credentials, so passwords will be held. They go in
  a dedicated secret store (Secrets Manager under a KMS key), keyed per student-portal — never
  a model field, never a `JSONField`, never in the evidence bucket, never logged or in an
  exception message. The IAM grant is per-secret-prefix and belongs to the portal-execution
  role only. Erasure ships with storage: `apps/audit/deletion.py::advance_deletion` must
  destroy a student's secrets on the same path it deletes their documents, or GDPR erasure
  leaves credentials behind. The failure mode this rule exists to prevent is a password column
  added in passing during a sprint.
- **CAPTCHA is detected and delegated, never circumvented.** The strategy is detect → preserve
  the session → hand to a human → resume, per §5.2. Browser stealth is not a CAPTCHA strategy
  and must not be adopted as one; §2 forbids unauthorized circumvention and §3.6 excludes
  proxy infrastructure intended to evade portal access controls. A resolution service may be
  integrated only per-approved-portal, after the portal-terms and legal gates, with consultant
  fallback. This is also the better engineering position: CAPTCHA triggering is driven by IP
  reputation and behaviour far more than fingerprint, the platform runs behind one NAT IP, and
  a strategy of not being detected fails silently mid-application at a deadline.
- **The Scrapling tier does not extend to portals.** `render_with_scrapling` reads public,
  unauthenticated programme pages. Defeating an access control on an authenticated third-party
  system is a different act. Portal execution gets its own client.
- **Stable egress is reserved; evasive egress is not.** The distinction is purpose, and it is
  testable: egress that makes the platform consistently identifiable is permitted; egress that
  makes it look like many unrelated ordinary users is not. Reserve the ability to allocate
  stable per-tenant or per-portal egress in the network design. Do not adopt rotating or
  residential pools.
- **Portal automation goes in a new app, never in `apps/concierge`.** That module's docstring
  guarantees every action in it is a human-recorded fact, and
  `tests/concierge/test_roadmap.py::test_no_payment_or_portal_automation_call` enforces it.
  When Phase 3 lands, the temptation is to delete that test. Don't — narrow the scope by
  putting automation elsewhere. `ManualOperation` gains no automated writer.
- **Agent actions are already representable.** `AuditEvent.actor_kind` distinguishes an agent
  write from a platform write (both carry `actor=NULL`), and `RoadmapItem.owner_kind` lets the
  agent own a step without a synthetic `Membership`. Use them; do not add a fake member row.
- **Untested and load-bearing:** that a browser session can be paused, handed to a consultant
  and resumed without repeating completed steps, on ephemeral Fargate workers. §5.2 depends on
  it in six places. Run that spike before designing Phase 3, not after.
```

- [ ] **Step 2: Verify nothing else changed**

Run: `uv run pytest tests/ -q && uv run ruff check apps config tests`
Expected: full suite green. (See Task 1 Step 7 for the known boundary-controller flake.)

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the Phase 3 constraints that add no code today

Spec decisions 3-6 govern work that has not started, so they have no
migration to carry them. CLAUDE.md is where the next person writing that
work will actually see them, and it already carries the web-fetching
rules these extend.

The credential rule is the one most likely to be violated by reflex --
the default path for 'we need to remember a portal password' is a model
field added in passing -- so it names the prohibited shapes explicitly
and ties erasure to storage in the same breath."
```

---

## Self-Review

**Spec coverage.** Decision 1 → Task 1. Decision 2 → Task 2. Decisions 3, 4, 5, 6 → Task 3 (no code, by design; the spec's "What this changes in the code" section says exactly two migrations). The spec's Testing section asks for migration tests preserving current meaning (Task 1 Steps 1–6), a test that agent ownership is distinguishable from a missing owner (Task 2 Step 1, `test_an_unowned_item_is_not_silently_an_agent_item`), and that `test_no_payment_or_portal_automation_call` stays untouched (Global Constraints, verified in Task 2 Step 5). The spec's "one thing this record cannot settle" is a future spike, correctly not a task here.

**Placeholder scan.** No TBDs. Every code step carries the actual code. The two enums are written out in full in both tasks rather than cross-referenced, since a subagent may read Task 2 without Task 1.

**Type consistency.** `AuditEvent.ActorKind` (HUMAN/SYSTEM/AGENT) and `RoadmapItem.OwnerKind` (HUMAN/AGENT) are deliberately separate types with different members; the Interfaces block in Task 2 says so explicitly so nobody "unifies" them. Field names `actor_kind` and `owner_kind` are used consistently in the models, tests, constraints and `CLAUDE.md` text. Constraint names `event_actor_kind_matches_actor` and `roadmapitem_owner_kind_matches_owner` each appear once.

**Known risk carried into execution.** Task 1 Step 5 depends on the migration role owning `funding_auditevent`. The step says to stop and report rather than escalate to `SESSION_REPLICATION_ROLE`, because that requires superuser and would also disable RLS.
