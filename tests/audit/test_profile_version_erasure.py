"""Erasure against the profile-version immutability trigger.

`accounts_profile_version_immutable` refused every UPDATE, and redaction blanks
`snapshot`, so every student holding a profile version -- every student with a
published pack -- was locked out at request time and never erased. The trigger
now admits exactly one change, the erasure's own: `snapshot` set to `{}` with
every other column as it was. Anything else is still refused, DELETE included.

Proved as the real worker role (`runtime_engine`, NOBYPASSRLS, not the table
owner), because the suite's default connection is a superuser and proves
nothing about what production can do.
"""

from datetime import timedelta

import psycopg
import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import StudentProfileVersion
from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.audit.redaction import redact_student
from apps.funding.models import PackVersion, RecommendationRun
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

TABLE = "accounts_studentprofileversion"


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch):
    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_mailbox_tokens", lambda **kw: 0)


def _student_with_published_pack(agency, django_user_model, name):
    """Two profile versions, the second one a published pack was built from."""
    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    versions = [
        StudentProfileVersion.objects.create(
            tenant=agency, student=student, version=n, schema_version=3,
            snapshot={"name": f"{name} v{n}", "nationality": "AZ"},
        )
        for n in (1, 2)
    ]
    run = RecommendationRun.objects.create(
        tenant=agency, profile_version=versions[1], state=RecommendationRun.State.PUBLISHED
    )
    PackVersion.objects.create(tenant=agency, run=run, version=1, published_at=timezone.now())
    return student, versions


def _due_request(agency, student):
    RetentionPolicy.objects.create(tenant=agency, version=1, effective_at=timezone.now())
    request = DeletionRequest.objects.create(tenant=agency, student=student, state="REQUESTED")
    advance_deletion(request, "RETENTION_REVIEW")
    advance_deletion(request, "APPROVED")
    DeletionRequest.objects.filter(id=request.id).update(
        execute_after=timezone.now() - timedelta(days=1)
    )
    return request


@pytest.mark.django_db
def test_redaction_blanks_every_profile_version_and_nothing_else(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, versions = _student_with_published_pack(agency_a, django_user_model, "amina")
        bystander, kept = _student_with_published_pack(agency_a, django_user_model, "kwame")

        redact_student(tenant_id=agency_a.id, student_id=student.id)

        for before in versions:
            after = StudentProfileVersion.objects.get(pk=before.pk)
            assert after.snapshot == {}
            assert (after.version, after.schema_version, after.created_at) == (
                before.version, before.schema_version, before.created_at,
            )
        for before in kept:
            assert StudentProfileVersion.objects.get(pk=before.pk).snapshot == before.snapshot


@pytest.fixture
def due_student(agency_a, django_user_model):
    """Committed as the superuser before `engine_role_orm` swaps the role --
    so it must precede that fixture in the test's arguments."""
    with tenant_scope(agency_a.id):
        student, _versions = _student_with_published_pack(agency_a, django_user_model, "amina")
        return student, _due_request(agency_a, student)


@pytest.mark.django_db(transaction=True)
def test_the_command_erases_a_student_with_a_published_pack_as_the_worker_role(
    agency_a, due_student, engine_role_orm
):
    student, request = due_student

    call_command("execute_due_erasures")

    # tenant_transaction: behind a NOBYPASSRLS role, tenant_scope alone never
    # reaches Postgres and these rows would simply be invisible.
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        request.refresh_from_db()
        snapshots = list(
            StudentProfileVersion.objects.filter(student=student).values_list("snapshot", flat=True)
        )
    assert request.state == "EXECUTED"
    assert snapshots == [{}, {}]


@pytest.fixture
def worker_cursor(agency_a, django_user_model, role_connection):
    """A raw cursor as runtime_engine, the tenant GUC set, one version committed."""
    with tenant_scope(agency_a.id):
        _student, versions = _student_with_published_pack(agency_a, django_user_model, "amina")
    with role_connection("runtime_engine") as conn, conn.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, false)", [str(agency_a.id)])
        yield cursor, versions[0].id


@pytest.mark.django_db(transaction=True)
def test_the_worker_role_may_blank_a_snapshot(worker_cursor):
    """The positive control for every refusal below: the row is reachable
    under RLS, so a refusal there is the trigger, not a hidden row."""
    cursor, pk = worker_cursor
    cursor.execute(f"UPDATE {TABLE} SET snapshot = '{{}}'::jsonb WHERE id = %s", [pk])
    assert cursor.rowcount == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "statement",
    [
        # An ordinary content edit.
        f"UPDATE {TABLE} SET snapshot = '{{\"name\": \"forged\"}}'::jsonb WHERE id = %s",
        # Blanking is not a licence to change anything else on the way.
        f"UPDATE {TABLE} SET snapshot = '{{}}'::jsonb, version = 7 WHERE id = %s",
        f"UPDATE {TABLE} SET snapshot = '{{}}'::jsonb, created_at = now() WHERE id = %s",
        # Another column alone, snapshot untouched.
        f"UPDATE {TABLE} SET schema_version = 2 WHERE id = %s",
        # Not an empty value of another type: '[]' and 'null' are not '{}'.
        f"UPDATE {TABLE} SET snapshot = '[]'::jsonb WHERE id = %s",
        f"UPDATE {TABLE} SET snapshot = 'null'::jsonb WHERE id = %s",
        f"DELETE FROM {TABLE} WHERE id = %s",
    ],
)
def test_the_worker_role_may_change_nothing_else(worker_cursor, statement):
    cursor, pk = worker_cursor
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="immutable"):
        cursor.execute(statement, [pk])
