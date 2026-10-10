"""The login identity is outside the redaction walk, so it needs its own guard.

student_reachable_models() grows by adding models whose FKs point INTO the
reached set. Membership.user points the other way, so no walk seeded at
Membership will ever reach auth.User. Nothing else covers these fields.
"""

import pytest

from apps.audit.identity import (
    IDENTITY_KEEP,
    IDENTITY_REDACT,
    IdentityRetention,
    identity_fields,
)

pytestmark = pytest.mark.django_db


def test_every_user_field_is_classified_exactly_once():
    """auth.User has gained fields across Django releases and will again.

    A new field holding identity must fail the build, not ship unnoticed.
    """
    redact = set(IDENTITY_REDACT)
    keep = set(IDENTITY_KEEP)
    unclassified = [f for f in identity_fields() if f not in redact and f not in keep]
    both = sorted(redact & keep)
    assert not unclassified, f"unclassified auth.User fields: {sorted(unclassified)}"
    assert not both, f"classified twice: {both}"


def test_classification_names_no_field_that_does_not_exist():
    """A typo classifies nothing and silently hides a real field."""
    real = set(identity_fields())
    stale = sorted((set(IDENTITY_REDACT) | set(IDENTITY_KEEP)) - real)
    assert not stale, f"classified fields that do not exist on auth.User: {stale}"


def test_the_identifying_fields_are_redacted_not_kept():
    """Pins the four that matter, so a later edit cannot quietly move one to KEEP."""
    for field in ("email", "first_name", "last_name", "username"):
        assert field in IDENTITY_REDACT, f"{field} must be redacted"
    assert "password" in IDENTITY_REDACT, "the password is a credential, not a record"


def test_a_second_erasure_does_not_collide_on_the_unique_username(
    agency_a, django_user_model
):
    """Blanking a unique column works once and raises on the second erasure.

    The scrubbed username must therefore differ per user. Nothing else proves
    this: the single-user scrub test only checks the "deleted-" prefix, which a
    constant would also satisfy.
    """
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    assert django_user_model._meta.get_field("username").unique
    scrubbed = []
    with tenant_scope(agency_a.id):
        for name in ("amina", "kwame"):
            user = django_user_model.objects.create_user(
                username=name, email=f"{name}@example.test", password="pw"
            )
            Membership.objects.create(
                tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=False
            )
            assert redact_identity(user_id=user.id, membership_role=Membership.Role.STUDENT) is None
            user.refresh_from_db()
            scrubbed.append(user.username)

    assert scrubbed[0] != scrubbed[1], f"both erasures produced {scrubbed[0]!r}"


def test_deletion_request_can_record_a_retained_identity(agency_a, membership_a):
    """An erasure that knowingly leaves the login alive must say so.

    Without this the request reads EXECUTED while the person is still
    identifiable -- the false-claim defect the erasure design exists to prevent,
    one level up.
    """
    from apps.audit.models import DeletionRequest
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
        assert request.identity_retained is False
        request.identity_retained = True
        request.save(update_fields=["identity_retained"])
        request.refresh_from_db()
        assert request.identity_retained is True


def test_scrubs_the_login_when_no_active_membership_remains(
    agency_a, django_user_model
):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="amina", email="amina@example.test", first_name="Amina", last_name="Yusuf",
        password="pw",
    )
    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    with tenant_scope(agency_a.id):
        membership = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=False
        )
        retention = redact_identity(user_id=user.id, membership_role=membership.role)

    user.refresh_from_db()
    assert retention is None
    assert user.email == ""
    assert user.first_name == ""
    assert user.last_name == ""
    assert user.username != "amina"
    assert user.username.startswith("deleted-")
    assert not user.has_usable_password()
    assert user.is_active is False
    assert not TOTPDevice.objects.filter(user=user).exists()


def test_keeps_the_login_when_the_person_is_active_at_another_agency(
    agency_a, agency_b, django_user_model
):
    """Criterion 2 beats criterion 1: an erasure at one agency must never lock
    the person out of another agency they still belong to."""
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="amina", email="amina@example.test", password="pw"
    )
    with tenant_scope(agency_a.id):
        erased = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=False
        )
    with tenant_scope(agency_b.id):
        Membership.objects.create(
            tenant=agency_b, user=user, role=Membership.Role.STUDENT, active=True
        )
    with tenant_scope(agency_a.id):
        retention = redact_identity(user_id=user.id, membership_role=erased.role)

    user.refresh_from_db()
    assert retention is IdentityRetention.STILL_ENROLLED
    assert user.email == "amina@example.test"
    assert user.is_active is True


def test_the_guard_is_not_tenant_scoped(agency_a, agency_b, django_user_model):
    """The regression this design is most likely to acquire later.

    The other-membership query must use Membership._base_manager. Through the
    tenant-scoped default manager it sees only agency A, finds nothing, and
    scrubs a login that agency B is still using. This test is the only thing
    standing between that one-word change and a locked-out user.
    """
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="kwame", email="kwame@example.test", password="pw"
    )
    with tenant_scope(agency_b.id):
        Membership.objects.create(
            tenant=agency_b, user=user, role=Membership.Role.STUDENT, active=True
        )
    with tenant_scope(agency_a.id):
        erased = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=False
        )
        assert (
            redact_identity(user_id=user.id, membership_role=erased.role)
            is IdentityRetention.STILL_ENROLLED
        )

    user.refresh_from_db()
    assert user.email == "kwame@example.test"


def test_refuses_a_django_staff_account(agency_a, django_user_model):
    """A staff or superuser account reaching this path is a misconfiguration,
    not an erasure. Refusing is the recoverable outcome."""
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="ops", email="ops@example.test", password="pw", is_staff=True
    )
    with tenant_scope(agency_a.id):
        membership = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=False
        )
        assert (
            redact_identity(user_id=user.id, membership_role=membership.role)
            is IdentityRetention.STAFF_ACCOUNT
        )

    user.refresh_from_db()
    assert user.email == "ops@example.test"


def test_refuses_a_non_student_membership(agency_a, django_user_model):
    """Erasure is a student right. Offboarding a counselor is a different
    operation and must not run this."""
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="counselor", email="c@example.test", password="pw"
    )
    with tenant_scope(agency_a.id):
        membership = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.COUNSELOR, active=False
        )
        assert (
            redact_identity(user_id=user.id, membership_role=membership.role)
            is IdentityRetention.NOT_A_STUDENT
        )

    user.refresh_from_db()
    assert user.email == "c@example.test"


def _approved_request(agency, student):
    from django.utils import timezone

    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    RetentionPolicy.objects.create(tenant=agency, version=1, effective_at=timezone.now())
    request = DeletionRequest.objects.create(tenant=agency, student=student, state="REQUESTED")
    advance_deletion(request, "RETENTION_REVIEW")
    advance_deletion(request, "APPROVED")
    return request


def test_executed_revokes_access_and_scrubs_the_login(
    agency_a, django_user_model, monkeypatch
):
    """Membership.active is what middleware.py:64 uses to resolve a request's
    tenant. Left True, an erased person keeps access to the agency that erased
    them."""
    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)

    user = django_user_model.objects.create_user(
        username="amina", email="amina@example.test", password="pw"
    )
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        request = _approved_request(agency_a, student)
        advance_deletion(request, "EXECUTED")
        request.refresh_from_db()
        student.refresh_from_db()

    user.refresh_from_db()
    assert request.state == "EXECUTED"
    assert student.active is False
    assert request.identity_retained is False
    assert user.email == ""
    assert user.is_active is False


def test_executed_records_a_retained_identity(
    agency_a, agency_b, django_user_model, monkeypatch
):
    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)

    user = django_user_model.objects.create_user(
        username="amina", email="amina@example.test", password="pw"
    )
    with tenant_scope(agency_b.id):
        Membership.objects.create(
            tenant=agency_b, user=user, role=Membership.Role.STUDENT, active=True
        )
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        request = _approved_request(agency_a, student)
        advance_deletion(request, "EXECUTED")
        request.refresh_from_db()

    user.refresh_from_db()
    assert request.state == "EXECUTED"
    assert request.identity_retained is True
    assert user.email == "amina@example.test"


# The next two live here rather than in test_deletion.py because they need the
# same EXECUTED end-to-end setup as the two above -- test_deletion.py stops at
# APPROVED and has no storage monkeypatches.


def test_executed_records_an_audit_event(agency_a, django_user_model, monkeypatch):
    """An erasure that leaves no trail cannot be shown to have happened.

    `phased requirements.md` §349 requires privileged cross-tenant operations to
    be audited, and redact_identity's guard is one -- it reads membership rows
    at every agency. DeletionRequest.state cannot serve: it is a current-value
    field that says the request *is* EXECUTED, not that anything ran or when,
    and redaction rewrites the rest of the row around it.
    """
    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.funding.models import AuditEvent
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)

    user = django_user_model.objects.create_user(username="amina", email="amina@example.test")
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        request = _approved_request(agency_a, student)
        advance_deletion(request, "EXECUTED")

        events = list(AuditEvent.objects.filter(object_id=request.id))

    assert [event.event for event in events] == ["deletion.executed"]
    # SYSTEM, not HUMAN: the erasure engine has no actor, and actor_kind is what
    # distinguishes a platform write from a Phase 3 agent one.
    assert events[0].actor is None
    assert events[0].actor_kind == "SYSTEM"


def test_a_retained_identity_is_audited_separately(
    agency_a, agency_b, django_user_model, monkeypatch
):
    """The exceptional case needs its own row, not a flag on the request.

    identity_retained lives on DeletionRequest, which redaction rewrites; the
    event is the durable record that this erasure deliberately left a login
    alive, and it is the one case a reviewer must be able to find by query.
    """
    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.funding.models import AuditEvent
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)

    user = django_user_model.objects.create_user(username="amina", email="amina@example.test")
    with tenant_scope(agency_b.id):
        Membership.objects.create(
            tenant=agency_b, user=user, role=Membership.Role.STUDENT, active=True
        )
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        request = _approved_request(agency_a, student)
        advance_deletion(request, "EXECUTED")

        events = {event.event for event in AuditEvent.objects.filter(object_id=request.id)}

    assert events == {"deletion.executed", "deletion.identity_retained"}


def test_the_three_retention_cases_are_distinguishable(agency_a, django_user_model):
    """identity_retained=True means three different things, two of which are
    somebody's mistake. A bare boolean cannot tell an agency which.
    """
    from apps.audit.identity import IdentityRetention, redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        staff = django_user_model.objects.create_user(
            username="staff-person", email="staff@example.test", password="pw", is_staff=True
        )
        counselor = django_user_model.objects.create_user(
            username="a-counselor", email="c@example.test", password="pw"
        )

        assert (
            redact_identity(user_id=staff.id, membership_role=Membership.Role.STUDENT)
            is IdentityRetention.STAFF_ACCOUNT
        )
        assert (
            redact_identity(user_id=counselor.id, membership_role=Membership.Role.COUNSELOR)
            is IdentityRetention.NOT_A_STUDENT
        )


def test_a_scrubbed_login_returns_none(agency_a, django_user_model):
    """None is the "it was erased" answer, so `retention is not None` is the
    flag advance_deletion records.
    """
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create_user(
            username="leaving", email="leaving@example.test", password="pw"
        )
        assert redact_identity(user_id=user.id, membership_role=Membership.Role.STUDENT) is None
