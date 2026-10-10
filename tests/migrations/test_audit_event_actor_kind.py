# tests/migrations/test_audit_event_actor_kind.py
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import IntegrityError, ProgrammingError

from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope


def _targets(executor: MigrationExecutor, selected: dict[str, str]):
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] not in selected]
    targets.extend(selected.items())
    return targets


#: research/0022 depends on funding/0049 (it creates the `runtime_engine`
#: role its write policy targets), so leaving `research` unselected -- at its
#: own head -- while a caller pins `funding` behind 0049 asks the executor
#: for an infeasible mixed forward/backward plan. Pin research at its
#: pre-decision-layer leaf whenever a call also pins `funding`; never when
#: `funding` is absent, so a bare `_migrate({})` still reaches research's
#: true head.
# privacy/0002 also depends on funding/0049 (the owner-only grant), same hazard.
_RESEARCH_PIN = {"research": "0009_site_job_record_rls", "privacy": "0001_initial"}


def _migrate(selected: dict[str, str]):
    executor = MigrationExecutor(connection)
    if "funding" in selected:
        selected = {**_RESEARCH_PIN, **selected}
    executor.migrate(_targets(executor, selected))


def _restore_latest() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(_targets(executor, {}))


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
        with pytest.raises(IntegrityError, match="event_actor_kind_matches_actor"):
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
        with pytest.raises(IntegrityError, match="event_actor_kind_matches_actor"):
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
    with pytest.raises(ProgrammingError, match="append-only"):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE funding_auditevent SET event = 'tampered' WHERE id = %s",
                    [str(event.id)],
                )


@pytest.mark.django_db(transaction=True)
def test_an_empty_actor_kind_is_rejected_even_when_save_is_bypassed(agency_a):
    """save() derives actor_kind, so the only way to reach an out-of-enum
    value is to go around it -- bulk_create, .update(), or raw SQL. The
    constraint, not save(), is what has to refuse it."""
    with tenant_scope(agency_a.id):
        with pytest.raises(IntegrityError, match="event_actor_kind_matches_actor"):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO funding_auditevent "
                        "(id, tenant_id, actor_id, actor_kind, event, object_id, created_at) "
                        "VALUES (gen_random_uuid(), %s, NULL, '', 'bogus', gen_random_uuid(), now())",
                        [str(agency_a.id)],
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


@pytest.mark.django_db
def test_force_row_level_security_is_still_enabled_after_the_migration():
    """The migration toggles NO FORCE / FORCE ROW LEVEL SECURITY around the
    backfill (see its comment). A half-completed toggle would silently end
    tenant isolation on the audit table for the table owner role, with every
    other test in the suite still green -- the same class of failure the
    trigger assertion above guards."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relforcerowsecurity FROM pg_class WHERE oid = 'funding_auditevent'::regclass"
        )
        assert cursor.fetchone() == (True,)


@pytest.mark.django_db(transaction=True)
def test_every_pre_existing_audit_event_carries_the_current_meaning_after_migrating(
    agency_a, membership_a
):
    """The spec's headline migration requirement (Testing section): every
    pre-existing AuditEvent carries the current meaning after migrating.

    Every other test in this file exercises the post-migration model on an
    empty table -- the backfill UPDATE inside 0015 itself is never run. If
    someone narrowed its CASE back to `WHERE actor_id IS NULL` (the exact
    mistake the migration's own comment warns about), a human-authored row
    would keep actor_kind='' and nothing here would catch it. This test
    inserts rows at 0014 -- before actor_kind exists -- migrates forward
    through the real backfill, and checks what came out.
    """
    human_id = uuid4()
    system_id = uuid4()
    try:
        _migrate({"funding": "0014_constraint_override_tenant_guards"})
        with connection.cursor() as cursor:
            # INSERT is not blocked by the append-only trigger; only UPDATE
            # and DELETE are (migration 0011).
            cursor.execute(
                "INSERT INTO funding_auditevent "
                "(id, tenant_id, actor_id, event, object_id, created_at) "
                "VALUES (%s, %s, %s, 'document.approved', %s, now())",
                [human_id, agency_a.id, membership_a.id, agency_a.id],
            )
            cursor.execute(
                "INSERT INTO funding_auditevent "
                "(id, tenant_id, actor_id, event, object_id, created_at) "
                "VALUES (%s, %s, NULL, 'document.format_unverified', %s, now())",
                [system_id, agency_a.id, agency_a.id],
            )

        _migrate({"funding": "0015_audit_event_actor_kind"})

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, actor_kind FROM funding_auditevent WHERE id IN (%s, %s)",
                [human_id, system_id],
            )
            actor_kind_by_id = dict(cursor.fetchall())
        assert actor_kind_by_id[human_id] == "HUMAN"
        assert actor_kind_by_id[system_id] == "SYSTEM"
    finally:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE funding_auditevent DISABLE TRIGGER USER")
            cursor.execute(
                "DELETE FROM funding_auditevent WHERE id IN (%s, %s)", [human_id, system_id]
            )
            cursor.execute("ALTER TABLE funding_auditevent ENABLE TRIGGER USER")
        _restore_latest()
