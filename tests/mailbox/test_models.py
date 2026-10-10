"""A connection and its signals belong to one tenant, enforced by Postgres.

The suite's own role is BYPASSRLS, so a test that only uses the ORM proves
nothing about isolation. rls_enforced_orm (tests/conftest.py) repoints Django's
default connection at a NOBYPASSRLS role, which is the only way the policy is
in the picture at all.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.db import transaction

from apps.mailbox.models import MailboxConnection, MailSignal
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency, Membership


@pytest.fixture
def two_tenants(django_db_blocker):
    """Two agencies, each with one student and one connection, committed.

    Committed rather than created inside the test transaction because
    rls_enforced_orm reconnects: rows written on the old connection and not
    committed are invisible to the new one.
    """
    with django_db_blocker.unblock(), transaction.atomic():
        made = []
        for index in (0, 1):
            agency = Agency.objects.create(name=f"agency-{index}")
            user = User.objects.create(username=f"student-{index}-{uuid4().hex}")
            with tenant_scope(agency.id), transaction.atomic():
                set_local_tenant(agency.id)
                student = Membership.objects.create(
                    tenant=agency, user=user, role="STUDENT", active=True
                )
                connection_row = MailboxConnection.objects.create(
                    tenant=agency,
                    membership=student,
                    provider=MailboxConnection.Provider.GOOGLE,
                    address=f"student{index}@example.test",
                )
                MailSignal.objects.create(
                    tenant=agency,
                    connection=connection_row,
                    provider_message_id=f"msg-{index}",
                    sender_domain="tum.de",
                    received_at="2026-09-18T09:00:00Z",
                )
            made.append((agency, student))
    yield made


@pytest.mark.django_db(transaction=True)
def test_a_tenant_sees_only_its_own_connection(rls_enforced_orm, two_tenants) -> None:
    (first, _student), _second = two_tenants[0], two_tenants[1]
    with tenant_scope(first.id), transaction.atomic():
        set_local_tenant(first.id)
        assert MailboxConnection.objects.count() == 1
        assert MailSignal.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_policy_hides_the_other_tenant_from_the_base_manager(
    rls_enforced_orm, two_tenants
) -> None:
    """_base_manager skips TenantManager; the row must still be gone.

    This is the check CLAUDE.md says no ordinary test can make: without the
    NOBYPASSRLS role this assertion passes whether or not the policy exists.
    """
    first, _student = two_tenants[0]
    with transaction.atomic():
        set_local_tenant(first.id)
        assert MailboxConnection._base_manager.count() == 1
        assert MailSignal._base_manager.count() == 1


@pytest.mark.django_db
def test_erasure_survives_two_learned_senders_and_two_signals(connection) -> None:
    """Redaction blanks LearnedSender.domain and MailSignal.provider_message_id
    to "" in one UPDATE each. With two rows apiece those blanks used to collide
    on the per-student / per-connection unique constraints, and the erasure
    batch died on the IntegrityError every day it retried.

    ``connection`` rather than ``connection_with_pack``: a published pack
    carries a StudentProfileVersion, whose own immutability trigger refuses
    redaction first and would mask the constraint this test is about."""
    from datetime import UTC, datetime

    from apps.audit.redaction import redact_student
    from apps.mailbox.models import LearnedSender
    from apps.tenancy.db import tenant_transaction

    student = connection.membership
    with tenant_scope(student.tenant_id), tenant_transaction(student.tenant_id):
        for domain in ("a.org", "b.org"):
            LearnedSender.objects.create(
                tenant_id=student.tenant_id, student=student, domain=domain, portal_host="x"
            )
        for message_id in ("m1", "m2"):
            MailSignal.objects.create(
                tenant_id=student.tenant_id,
                connection=connection,
                provider_message_id=message_id,
                sender_domain="tum.de",
                received_at=datetime(2026, 9, 20, tzinfo=UTC),
            )
        redact_student(tenant_id=student.tenant_id, student_id=student.id)

        assert set(LearnedSender.objects.values_list("domain", flat=True)) == {""}
        assert set(MailSignal.objects.values_list("provider_message_id", flat=True)) == {""}
