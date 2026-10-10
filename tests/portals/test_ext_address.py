"""The extension reports what happened to the portal address it typed (spec §2a)."""

import json

import pytest

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.portals.test_ext_api import _application, _pair

pytestmark = pytest.mark.django_db

EMAIL_ENTRIES = [
    {
        "profile_field": "contact.email",
        "action": {"selector": "#email", "method": "fill", "arguments": ["%value%"]},
    }
]


@pytest.fixture
def emailed(agency_a, membership_a, monkeypatch):
    """An application whose map asks for contact.email, and a student with an
    application inbox address -- so the packet issues a tagged address."""
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        return _application(agency_a, membership_a, entries=EMAIL_ENTRIES)


@pytest.fixture
def untagged(agency_a, membership_a, monkeypatch):
    """An application_email that already carries a '+' -- tagged() (F1) leaves
    it unchanged, so the account this issues has no tag of ours to reject."""
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla+apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        return _application(agency_a, membership_a, entries=EMAIL_ENTRIES)


def _packet(client, application, token, host):
    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _report(client, application, token, host, body):
    return client.post(
        f"/ext/applications/{application.id}/address",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _account(agency, student):
    from apps.portals.models import PortalAccount

    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return PortalAccount.objects.get(student=student)


def test_the_packet_carries_the_plain_address_beside_the_tagged_one(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    token = _pair(client, agency_a, membership_a, domain_a)

    packet = _packet(client, emailed, token, domain_a.host)

    [entry] = packet["entries"]
    assert entry["value"].startswith("leyla.apply+")
    assert packet["plain_email"] == "leyla.apply@outlook.com"


def test_the_first_given_report_opens_the_registration_window(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    from apps.portals.models import ApplicationStep

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    first = _report(client, emailed, token, domain_a.host, {"event": "given"})
    registered_at = _account(agency_a, membership_a).registered_at
    second = _report(client, emailed, token, domain_a.host, {"event": "given"})

    assert first.status_code == 200
    assert first.json()["awaiting_mail"] is True
    assert first.json()["ask_after_seconds"] == 300
    assert second.json()["awaiting_mail"] is False
    assert _account(agency_a, membership_a).registered_at == registered_at
    with tenant_scope(agency_a.id):
        assert ApplicationStep.objects.filter(application=emailed, kind="SIGNUP").count() == 1


def test_a_rejection_seen_on_the_form_hands_this_account_the_plain_address(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    from apps.portals.models import PortalForm

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    response = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": "form"}
    )
    packet = _packet(client, emailed, token, domain_a.host)

    assert response.json()["address"] == "leyla.apply@outlook.com"
    assert packet["entries"][0]["value"] == "leyla.apply@outlook.com"
    assert packet["plain_email"] == ""
    assert PortalForm.objects.get(pk=emailed.portal_form_id).tag_status == "UNKNOWN"


def test_one_tenant_s_form_rejection_never_changes_another_tenant_s_address(
    client, agency_a, domain_a, membership_a, user_a, emailed, agency_b, membership_b
):
    """Security review M2: a device report is a claim by a client the server
    does not control, so it governs the reporting account only. Tenant B's
    student, first issued an address on the same portal afterwards, still gets
    the tagged one."""
    from apps.portals.models import Application
    from apps.portals.tags import portal_address

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)
    response = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": "form"}
    )
    assert response.json()["address"] == "leyla.apply@outlook.com"

    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        membership_b.application_email = "hasan.apply@outlook.com"
        membership_b.save(update_fields=["application_email"])
        theirs = Application.objects.create(
            tenant=agency_b,
            student=membership_b,
            program_id=emailed.program_id,
            portal_form_id=emailed.portal_form_id,
        )
        # Fresh from the database, so the shared row is read as it now stands.
        address = portal_address(Application.objects.get(pk=theirs.pk))

    assert address.startswith("hasan.apply+") and address.endswith("@outlook.com")


def test_the_student_s_button_moves_their_account_and_nothing_shared(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    from apps.portals.models import PortalForm

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    response = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": "student"}
    )

    assert response.json()["address"] == "leyla.apply@outlook.com"
    assert PortalForm.objects.get(pk=emailed.portal_form_id).tag_status == "UNKNOWN"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"event": "rejected"},
        {"event": "rejected", "evidence": "rumour"},
        {"event": "kept"},
        # Evidence only ever accompanies a rejection; a `given` carrying one is
        # a client that does not know the vocabulary.
        {"event": "given", "evidence": "form"},
    ],
)
def test_a_report_the_server_does_not_know_is_refused(
    client, agency_a, domain_a, membership_a, user_a, emailed, body
):
    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    response = _report(client, emailed, token, domain_a.host, body)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_report"}


def test_an_unknown_field_in_the_report_is_refused(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    response = _report(
        client, emailed, token, domain_a.host, {"event": "given", "extra": "nope"}
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_report"}


def test_a_form_rejection_on_an_untagged_account_is_refused_and_writes_nothing(
    client, agency_a, domain_a, membership_a, user_a, untagged
):
    """F1: an account tagged() left unchanged has nothing of ours to reject --
    answering anything else would move the shared status on evidence that
    isn't evidence of anything."""
    from apps.portals.models import PortalAccount, PortalForm

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, untagged, token, domain_a.host)

    response = _report(
        client, untagged, token, domain_a.host, {"event": "rejected", "evidence": "form"}
    )

    assert response.status_code == 409
    assert response.json() == {"error": "not_tagged"}
    assert PortalForm.objects.get(pk=untagged.portal_form_id).tag_status == "UNKNOWN"
    with tenant_scope(agency_a.id):
        assert PortalAccount.objects.get(student=membership_a).tag_outcome == "UNKNOWN"


@pytest.mark.parametrize("evidence", ["form", "page", "after_submit", "student"])
def test_device_evidence_never_moves_the_shared_status(
    client, agency_a, domain_a, membership_a, user_a, emailed, evidence
):
    """Security review M2: no device evidence moves the platform-wide row --
    only `manage.py set_tag_status` does. Every kind still moves the
    account's own measurement to REJECTS."""
    from apps.portals.models import PortalForm

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    response = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": evidence}
    )

    assert response.status_code == 200
    assert PortalForm.objects.get(pk=emailed.portal_form_id).tag_status == "UNKNOWN"
    assert _account(agency_a, membership_a).tag_outcome == "REJECTS"


def test_the_student_s_button_overrides_an_earlier_keeps_measurement(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    """Controller ruling on F6: the student's own evidence always governs
    their own account, even over an earlier KEEPS -- and still never touches
    the shared row."""
    from apps.portals.models import PortalAccount, PortalForm

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        PortalAccount.objects.filter(student=membership_a).update(tag_outcome="KEEPS")

    response = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": "student"}
    )

    assert response.status_code == 200
    assert response.json()["address"] == "leyla.apply@outlook.com"
    assert _account(agency_a, membership_a).tag_outcome == "REJECTS"
    assert PortalForm.objects.get(pk=emailed.portal_form_id).tag_status == "UNKNOWN"


def test_no_address_issued_yet_is_a_conflict(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _report(client, emailed, token, domain_a.host, {"event": "given"})

    assert response.status_code == 409


def test_a_repeated_form_rejection_after_the_address_moved_to_plain_is_a_no_op(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    """Round 2: record_tag_outcome rewrites account.address to the plain
    address on the first REJECTS, so plain_of(account) reads "" on any later
    report -- indistinguishable, by that check alone, from an account that
    never carried our tag. A repeat report (extension retry, double-press)
    must still be the harmless 200 no-op it was before, never a 409."""
    from apps.funding.models import AuditEvent
    from apps.portals.models import PortalForm

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    first = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": "form"}
    )
    second = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": "form"}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["address"] == "leyla.apply@outlook.com"
    assert PortalForm.objects.get(pk=emailed.portal_form_id).tag_status == "UNKNOWN"
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(event="portal.tag_status_set").count() == 0


def test_a_repeated_student_rejection_after_the_address_moved_to_plain_is_a_no_op(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    """Same hazard, the 'student' path: force=True on the first call already
    rewrote the address to plain, so a second press must stay a 200 no-op."""
    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    first = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": "student"}
    )
    second = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": "student"}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["address"] == "leyla.apply@outlook.com"


def test_another_student_s_application_is_404(
    client, agency_a, domain_a, membership_a, user_a, emailed, agency_b, membership_b, domain_b
):
    token = _pair(client, agency_b, membership_b, domain_b)

    response = _report(client, emailed, token, domain_b.host, {"event": "given"})

    assert response.status_code == 404


def test_the_extension_s_evidence_vocabulary_is_the_server_s():
    """One definition each side, pinned equal: an evidence value the extension
    sends and the server does not know is a 400 the student cannot act on."""
    import pathlib
    import re

    from apps.portals.ext_api import _REJECTION_EVIDENCE

    types = pathlib.Path(__file__).resolve().parents[2] / "extension" / "src" / "types.ts"
    [union] = re.findall(r"export type RejectionEvidence =([^;]+);", types.read_text())
    assert set(re.findall(r'"(\w+)"', union)) == set(_REJECTION_EVIDENCE)
