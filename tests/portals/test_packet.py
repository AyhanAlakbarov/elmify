"""mint_packet: what the extension types, and the record of what we prepared.

The PACKET step is the authoritative "what the platform prepared" row in the
§5.5 trail. The extension's later report is an attestation from a device we do
not control; this row is ours.
"""

import pytest

from apps.tenancy.context import tenant_scope
from tests.portals.test_kit import _application

pytestmark = pytest.mark.django_db


def test_the_packet_carries_one_entry_per_mapped_field(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        packet = packets.mint_packet(application)

    assert [(e.selector, e.method, e.value) for e in packet.entries] == [
        ("#name", "fill", "Ada Byron"),
        ("#city", "fill", "London"),
    ]
    assert packet.field_map_version == 1
    assert packet.form_url == "https://apply.example.edu/personal"
    assert packet.expires_at > packet.issued_at


def test_minting_records_a_packet_step_carrying_what_we_prepared(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets
    from apps.portals.models import ApplicationStep

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        packets.mint_packet(application)

        step = ApplicationStep.objects.get(application=application, kind="PACKET")

    assert step.detail["field_map_version"] == 1
    assert step.detail["values"] == [
        {"selector": "#name", "value": "Ada Byron"},
        {"selector": "#city", "value": "London"},
    ]
    assert step.detail["documents"] == []


def test_two_entries_targeting_the_same_selector_both_survive_the_audit_row(
    agency_a, membership_a, monkeypatch
) -> None:
    """The PACKET step is the authoritative record of what the platform
    prepared. A dict keyed by selector would collapse two field-map entries
    that target the same selector into one recorded value -- a list of
    {selector, value} objects keeps both."""
    from apps.portals import packets
    from apps.portals.models import ApplicationStep

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    dupe_selector = [
        {
            "profile_field": "identity.full_name",
            "action": {"selector": "#shared", "method": "fill", "arguments": ["%value%"]},
        },
        {
            "profile_field": "personal.city",
            "action": {"selector": "#shared", "method": "fill", "arguments": ["%value%"]},
        },
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=dupe_selector)

        packets.mint_packet(application)

        step = ApplicationStep.objects.get(application=application, kind="PACKET")

    assert step.detail["values"] == [
        {"selector": "#shared", "value": "Ada Byron"},
        {"selector": "#shared", "value": "London"},
    ]


def test_the_kit_and_the_packet_never_disagree(agency_a, membership_a, monkeypatch) -> None:
    """The load-bearing claim of the design: one object, two renderings.

    If these ever drift, a student reads one set of answers on the dashboard
    and a different set gets typed into the portal.
    """
    from apps.portals import packets

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        kit = packets.build_kit(application)
        packet = packets.mint_packet(application)

    assert [q.answer for q in kit.questions] == [e.value for e in packet.entries]
    assert [d.draft_id for d in kit.documents] == [d.draft_id for d in packet.documents]


def test_the_kit_and_the_packet_never_disagree_on_the_tagged_email(
    agency_a, membership_a, monkeypatch
) -> None:
    """Regression: build_kit must fold the tagged portal address into
    `values` exactly like mint_packet does. Before the fix, a field map
    entry for contact.email showed as missing on the kit while the packet
    filled it with the tagged address -- the two disagreeing on the one
    thing this module promises they cannot disagree on."""
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    email_entry = [
        {
            "profile_field": "contact.email",
            "action": {
                "selector": "#email",
                "description": "Email",
                "method": "fill",
                "arguments": ["%value%"],
            },
        }
    ]
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        application = _application(agency_a, membership_a, entries=email_entry)

        kit = packets.build_kit(application)
        packet = packets.mint_packet(application)

    assert [q.answer for q in kit.questions] == [e.value for e in packet.entries]
    assert not kit.questions[0].missing


def test_a_portal_that_prohibits_automation_refuses_before_anything_else(
    agency_a, membership_a, monkeypatch
) -> None:
    """Checked first, deliberately: a prohibited portal must not escalate a
    missing fact, write a step, or read a single verified value."""
    from apps.portals import packets
    from apps.portals.models import ApplicationStep, PortalForm

    def _explode(student):
        raise AssertionError("verified_values must not be read for a prohibited portal")

    monkeypatch.setattr(packets, "verified_values", _explode)
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a,
            membership_a,
            terms_posture=PortalForm.TermsPosture.PROHIBITS_AUTOMATION,
        )

        with pytest.raises(packets.PacketRefused) as refusal:
            packets.mint_packet(application)

        assert ApplicationStep.objects.filter(application=application).count() == 0

    assert refusal.value.reason == "automation_prohibited"


def test_an_unlearned_portal_raises_no_field_map(agency_a, membership_a) -> None:
    from apps.portals import packets

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=None)

        with pytest.raises(packets.NoFieldMap):
            packets.mint_packet(application)


def test_a_missing_fact_escalates_and_refuses(agency_a, membership_a, monkeypatch) -> None:
    """Same behaviour prepare_application had, for the same reason: there is no
    point opening a portal tab for an application that cannot be completed."""
    from apps.portals import packets
    from apps.portals.models import Application, ApplicationStep

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        with pytest.raises(packets.PacketRefused) as refusal:
            packets.mint_packet(application)

        application.refresh_from_db()
        step = ApplicationStep.objects.get(application=application, kind="ESCALATION")
        assert not ApplicationStep.objects.filter(application=application, kind="PACKET").exists()

    assert refusal.value.reason == "missing_fact"
    assert application.state == Application.State.BLOCKED_MISSING_FACT
    assert step.detail["detail"] == "personal.city"


def test_a_malformed_field_map_entry_refuses_with_a_stable_reason(
    agency_a, membership_a, monkeypatch
) -> None:
    """FieldMap is a shared table this plan never writes. A row missing the
    action key, or carrying one FieldAction can't validate, must not escape
    as a raw KeyError/ValidationError -- mint_packet's whole contract is a
    stable machine-readable reason."""
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    no_action_key = [{"profile_field": "identity.full_name"}]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=no_action_key)

        with pytest.raises(packets.PacketRefused) as refusal:
            packets.mint_packet(application)

    assert refusal.value.reason == "malformed_field_map"


def test_an_entry_with_no_profile_field_refuses_with_a_stable_reason(
    agency_a, membership_a, monkeypatch
) -> None:
    """The same contract as the missing-action case above, for the other half
    of a FieldMap row: no usable profile_field. mint_packet's missing-fact
    computation reads profile_field before it ever reaches the action loop,
    so this path must refuse there rather than raising a raw KeyError."""
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    no_profile_field = [
        {"action": {"selector": "#mystery", "method": "fill", "arguments": ["%value%"]}}
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=no_profile_field)

        with pytest.raises(packets.PacketRefused) as refusal:
            packets.mint_packet(application)

    assert refusal.value.reason == "malformed_field_map"


def test_an_action_that_fails_schema_validation_refuses_with_a_stable_reason(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    unvalidatable = [
        {
            "profile_field": "identity.full_name",
            # selector is required by FieldAction; this entry has none.
            "action": {"method": "fill", "arguments": ["%value%"]},
        }
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=unvalidatable)

        with pytest.raises(packets.PacketRefused) as refusal:
            packets.mint_packet(application)

    assert refusal.value.reason == "malformed_field_map"


def test_a_stored_action_that_would_do_more_than_type_is_refused(
    agency_a, membership_a, monkeypatch
) -> None:
    """A map row stored before is_fillable existed outlives it. A click stored
    in a shared field map would fire for every student of every tenant."""
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {"identity.full_name": "Ada"})
    unsafe = [
        {
            "profile_field": "identity.full_name",
            "action": {"selector": "#submit", "method": "click", "arguments": ["%value%"]},
        }
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=unsafe)

        with pytest.raises(packets.PacketRefused) as refusal:
            packets.mint_packet(application)

    assert refusal.value.reason == "unsafe_action"


def test_every_packet_entry_names_the_field_it_fills(
    agency_a, membership_a, monkeypatch
) -> None:
    """The extension cannot verify a selector it cannot name.

    A control's accessible name is judged against the FIELD, so an entry
    without one degrades the check to "something exists here", which is what
    the spec's plan-3 section rules out.
    """
    from apps.portals import packets

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        packet = packets.mint_packet(application)

    assert [entry.profile_field for entry in packet.entries] == [
        "identity.full_name",
        "personal.city",
    ]


def test_the_packet_carries_the_forms_confirmation_markers(
    agency_a, membership_a, monkeypatch
) -> None:
    """detectConfirmation has been dead code since the extension shipped.

    `content/page_signals.ts::detectConfirmation` reads
    `packet.confirmation_markers`, the column did not exist, so the extension
    was handed nothing, returned false, and no SUBMITTED row was ever written
    from the page itself. The handshake the spec's third box describes turns on
    here, with no extension change.
    """
    from apps.portals import packets

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        application.portal_form.confirmation_markers = [
            "Your application has been submitted",
            "/application/confirmation",
        ]
        application.portal_form.save(update_fields=["confirmation_markers"])

        packet = packets.mint_packet(application)

    assert packet.confirmation_markers == (
        "Your application has been submitted",
        "/application/confirmation",
    )


def test_a_form_with_no_markers_sends_none_rather_than_an_empty_list(
    agency_a, membership_a, monkeypatch
) -> None:
    """None and [] are different instructions to the extension.

    An unconfigured portal must leave detectConfirmation off. `[]` would read
    as "these are the markers, and none of them matched", which is the same
    answer a genuinely unsubmitted page gives -- so a portal nobody has
    configured would look identical to one the student never submitted.
    """
    from apps.portals import packets

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        packet = packets.mint_packet(application)

    assert packet.confirmation_markers is None
