"""One tagged address per student per portal host, handed out by packet and kit."""

import pytest

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.portals.test_kit import _application

pytestmark = pytest.mark.django_db

EMAIL_ENTRY = {
    "profile_field": "contact.email",
    "action": {
        "selector": "#email",
        "description": "Email",
        "method": "fill",
        "arguments": ["%value%"],
    },
}


@pytest.fixture
def with_address(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])


def test_tagged_puts_the_tag_before_the_at_sign():
    from apps.portals.tags import tagged

    assert tagged("leyla@outlook.com", "ab12cd") == "leyla+ab12cd@outlook.com"


@pytest.mark.parametrize("address", ["leyla+x@outlook.com", "no-at-sign", "@outlook.com"])
def test_an_address_that_cannot_take_a_tag_is_returned_unchanged(address):
    from apps.portals.tags import tagged

    assert tagged(address, "ab12cd") == address


def test_one_portal_host_gets_one_address(agency_a, membership_a, with_address):
    from apps.portals.models import Application, PortalAccount
    from apps.portals.tags import portal_address

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        first = _application(agency_a, membership_a)
        second = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=first.program_id,
            portal_form=first.portal_form,
        )
        a, b = portal_address(first), portal_address(second)
        assert PortalAccount.objects.filter(student=membership_a).count() == 1

    assert a == b
    local, _, domain = a.partition("@")
    assert domain == "outlook.com"
    assert local.startswith("leyla.apply+") and len(local) == len("leyla.apply+") + 6


def test_a_portal_that_rejects_tags_gets_the_plain_address(agency_a, membership_a, with_address):
    """At first issue. An address already issued is never re-based by the
    shared status (final review I1): test_tag_outcomes pins that side."""
    from apps.portals.models import PortalForm
    from apps.portals.tags import portal_address

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        application = _application(agency_a, membership_a)
        PortalForm.objects.filter(pk=application.portal_form_id).update(
            tag_status=PortalForm.TagStatus.REJECTS
        )
        application.portal_form.refresh_from_db()
        assert portal_address(application) == "leyla.apply@outlook.com"


def test_no_application_email_means_no_address(agency_a, membership_a):
    from apps.portals.tags import portal_address

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert portal_address(_application(agency_a, membership_a)) == ""


def test_the_packet_fills_the_email_field_with_the_tagged_address(
    agency_a, membership_a, with_address, monkeypatch
):
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=[EMAIL_ENTRY])
        packet = packets.mint_packet(application)

    [entry] = packet.entries
    assert entry.profile_field == "contact.email"
    assert entry.value.startswith("leyla.apply+") and entry.value.endswith("@outlook.com")


def test_the_kit_shows_the_tagged_address(agency_a, membership_a, with_address, monkeypatch):
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        kit = packets.build_kit(_application(agency_a, membership_a))

    assert kit.apply_with_email.startswith("leyla.apply+")


def test_a_student_with_no_address_gets_missing_fact_on_a_map_with_the_email_field(
    agency_a, membership_a, monkeypatch
):
    """The documented consequence of T5 (final review): the agency's map always
    may carry contact.email, and a student with no application_email cannot
    fill it."""
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=[EMAIL_ENTRY])
        with pytest.raises(packets.PacketRefused, match="missing_fact"):
            packets.mint_packet(application)
