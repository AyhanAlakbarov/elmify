"""What one account measured about the tag, and who may move the shared status.

The rule (plan 3, security review M2): a report governs its own account only;
PortalForm.tag_status is moved by a human (set_tag_status), never by a report.
"""

from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db

HOST = "apply.example.edu"


def _account(agency, student, *, address="leyla.apply+ab12cd@outlook.com", host=HOST):
    from apps.portals.models import PortalAccount

    return PortalAccount.objects.create(
        tenant=agency, student=student, portal_host=host, tag="ab12cd", address=address
    )


def _form(host=HOST, **kwargs):
    from apps.portals.models import PortalForm

    return PortalForm.objects.create(portal_host=host, form_key=f"f-{uuid4()}", **kwargs)


def _status(host=HOST):
    from apps.portals.models import PortalForm

    return set(PortalForm.objects.filter(portal_host=host).values_list("tag_status", flat=True))


def test_plain_of_removes_only_our_own_tag(agency_a, membership_a):
    from apps.portals.models import PortalAccount
    from apps.portals.tags import plain_of

    ours = PortalAccount(tag="ab12cd", address="leyla.apply+ab12cd@outlook.com")
    theirs = PortalAccount(tag="ab12cd", address="leyla+work@outlook.com")

    assert plain_of(ours) == "leyla.apply@outlook.com"
    assert plain_of(theirs) == ""


def test_a_report_measures_its_account_and_never_the_shared_row(agency_a, membership_a):
    from apps.funding.models import AuditEvent
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form(), _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = _account(agency_a, membership_a)
        assert record_tag_outcome(account, PortalForm.TagStatus.KEEPS)
        account.refresh_from_db()
        audited = AuditEvent.objects.filter(event="portal.tag_status_set").exists()

    assert account.tag_outcome == "KEEPS"
    assert _status() == {"UNKNOWN"}
    assert audited is False


def test_one_tenant_cannot_overturn_a_set_status(
    agency_a, membership_a, agency_b, membership_b, caplog
):
    """The cross-tenant rule: KEEPS stays KEEPS whatever another tenant reports,
    and the report is logged for a human instead."""
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form(tag_status=PortalForm.TagStatus.KEEPS)
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        account = _account(agency_b, membership_b)
        moved = record_tag_outcome(account, PortalForm.TagStatus.REJECTS)
        account.refresh_from_db()

    assert moved is True  # the reporter's own account still takes its own evidence
    assert account.tag_outcome == "REJECTS"
    assert account.address == "leyla.apply@outlook.com"
    assert _status() == {"KEEPS"}
    assert "TagStatusDisputed" in caplog.text


def test_an_account_measures_once(agency_a, membership_a):
    """The account's first observation wins."""
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = _account(agency_a, membership_a)
        record_tag_outcome(account, PortalForm.TagStatus.KEEPS)
        second = record_tag_outcome(account, PortalForm.TagStatus.STRIPS)
        account.refresh_from_db()

    assert second is False
    assert account.tag_outcome == "KEEPS"


def test_a_shared_rejects_never_rebases_a_registered_account(agency_a, membership_a):
    """Another tenant's REJECTS arrives after this student registered with the
    tag: the portal holds the tagged address, so the student keeps being handed it."""
    from apps.portals.models import Application, PortalForm
    from apps.portals.tags import portal_address

    form = _form(tag_status=PortalForm.TagStatus.REJECTS)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        account = _account(agency_a, membership_a)
        account.registered_at = timezone.now()
        account.save(update_fields=["registered_at"])
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        assert portal_address(application) == "leyla.apply+ab12cd@outlook.com"


def test_a_rejected_tag_falls_back_to_the_issued_address_not_a_new_one(agency_a, membership_a):
    """The student changed application_email after the tag was issued. The
    portal holds the old mailbox, so the fallback is the old plain address."""
    from apps.portals.models import Application, PortalForm
    from apps.portals.tags import portal_address, record_tag_outcome

    form = _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        membership_a.application_email = "leyla.new@outlook.com"
        membership_a.save(update_fields=["application_email"])
        account = _account(agency_a, membership_a)
        record_tag_outcome(account, PortalForm.TagStatus.REJECTS)
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        assert portal_address(application) == "leyla.apply@outlook.com"


def test_a_human_moves_a_set_status():
    from apps.portals.models import PortalForm

    _form(tag_status=PortalForm.TagStatus.KEEPS)
    call_command("set_tag_status", HOST, "REJECTS")

    assert _status() == {"REJECTS"}


def test_an_unknown_status_is_refused_by_the_database():
    from django.db import IntegrityError, transaction

    from apps.portals.models import PortalForm

    form = _form()
    with pytest.raises(IntegrityError), transaction.atomic():
        PortalForm.objects.filter(pk=form.pk).update(tag_status="MAYBE")


@pytest.mark.django_db(transaction=True)
def test_record_tag_outcome_writes_behind_the_policy(
    agency_a, membership_a, agency_b, membership_b, rls_enforced_orm
):
    """RED if record_tag_outcome's write escapes its tenant_transaction: the
    conditional UPDATE matches zero rows under a NOBYPASSRLS role, so the
    account stays unmoved -- passing as the superuser (every other test in
    this file) proves nothing about production, where every runtime role is
    NOBYPASSRLS. Two tenants' contradicting reports each move their own
    account and nothing shared."""
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = _account(agency_a, membership_a)
        assert record_tag_outcome(account, PortalForm.TagStatus.REJECTS)
        account.refresh_from_db()
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        other = _account(
            agency_b, membership_b, address="hasan.apply+zz99yy@outlook.com", host=HOST
        )
        assert record_tag_outcome(other, PortalForm.TagStatus.KEEPS)
        other.refresh_from_db()

    assert account.tag_outcome == PortalForm.TagStatus.REJECTS
    assert other.tag_outcome == PortalForm.TagStatus.KEEPS
    assert _status() == {"UNKNOWN"}


def test_a_later_form_does_not_take_a_status_contradicting_its_host(agency_a, membership_a, caplog):
    """A report contradicting a set form on the host is logged for a human,
    and no form on the host moves -- the set one or the later UNKNOWN one."""
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form(tag_status=PortalForm.TagStatus.KEEPS)
    _form()  # F2, added later, still UNKNOWN

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = _account(agency_a, membership_a)
        moved = record_tag_outcome(account, PortalForm.TagStatus.REJECTS)

    assert moved is True  # the reporter's own account still takes its own evidence
    assert _status() == {"KEEPS", "UNKNOWN"}  # F2 stays UNKNOWN, not REJECTS
    assert "TagStatusDisputed" in caplog.text


def test_record_tag_outcome_refuses_unknown_as_an_outcome(agency_a, membership_a):
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = _account(agency_a, membership_a)
        with pytest.raises(ValueError):
            record_tag_outcome(account, PortalForm.TagStatus.UNKNOWN)


def test_set_tag_status_logs_the_override(caplog):
    from apps.portals.models import PortalForm

    _form(tag_status=PortalForm.TagStatus.KEEPS)
    call_command("set_tag_status", HOST, "REJECTS")

    assert "TagStatusOverride" in caplog.text
    assert "KEEPS" in caplog.text
    assert "REJECTS" in caplog.text


def test_a_shared_rejects_never_rebases_an_account_with_its_own_measurement(
    agency_a, membership_a
):
    """F1: a shared REJECTS is set after this account already
    holds its own measurement (KEEPS), and the student's email then changes.
    The account keeps the address its own measurement implies -- it must not
    be re-based onto the (changed) current application_email just because it
    was never `registered_at`."""
    from apps.portals.models import Application, PortalForm
    from apps.portals.tags import portal_address, record_tag_outcome

    form = _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        account = _account(agency_a, membership_a)
        # This account's own measurement: KEEPS, via its own tenant's report.
        assert record_tag_outcome(account, PortalForm.TagStatus.KEEPS)
        assert account.tag_outcome == PortalForm.TagStatus.KEEPS

        # A shared REJECTS then arrives -- another tenant's report on the
        # form, never through this account.
        PortalForm.objects.filter(portal_host=HOST).update(
            tag_status=PortalForm.TagStatus.REJECTS
        )
        # The student's email changes.
        membership_a.application_email = "leyla.new@outlook.com"
        membership_a.save(update_fields=["application_email"])

        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        assert portal_address(application) == account.address
        assert portal_address(application) == "leyla.apply+ab12cd@outlook.com"


def test_a_shared_rejects_never_rebases_a_kit_issued_address(agency_a, membership_a):
    """I1 (final review): the kit handed the student the tagged address and
    they registered by hand, so registered_at is still NULL and no mail has
    arrived. The platform then sets REJECTS for the host. The server cannot
    see a hand registration, so an issued address is never re-based by the
    shared status -- only a first issue follows it."""
    from apps.portals.models import Application
    from apps.portals.tags import portal_address

    form = _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        app_a = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        first = portal_address(app_a)
    call_command("set_tag_status", HOST, "REJECTS")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        second = portal_address(Application.objects.get(pk=app_a.pk))

    assert "+" in first
    assert second == first


def test_an_agreeing_report_is_not_a_dispute(agency_a, membership_a, caplog):
    """M5 (final review): a form on the host still UNKNOWN is not a disagreement.
    A KEEPS report on a host whose set form says KEEPS logs no dispute."""
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form(tag_status=PortalForm.TagStatus.KEEPS)
    _form()  # added later, still UNKNOWN
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = _account(agency_a, membership_a)
        record_tag_outcome(account, PortalForm.TagStatus.KEEPS)

    assert _status() == {"KEEPS", "UNKNOWN"}
    assert "TagStatusDisputed" not in caplog.text
