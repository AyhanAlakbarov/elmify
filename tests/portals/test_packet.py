"""mint_packet: what the extension types, and the record of what we prepared.

The PACKET step is the authoritative "what the platform prepared" row in the
§5.5 trail. The extension's later report is an attestation from a device we do
not control; this row is ours.
"""

import pytest

from apps.tenancy.context import tenant_scope
from tests.portals.test_kit import ENTRIES, _application

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
        {"selector": "#name", "value": "Ada Byron", "profile_field": "identity.full_name"},
        {"selector": "#city", "value": "London", "profile_field": "personal.city"},
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
        {"selector": "#shared", "value": "Ada Byron", "profile_field": "identity.full_name"},
        {"selector": "#shared", "value": "London", "profile_field": "personal.city"},
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


def test_an_unsure_entry_is_a_hint_with_no_value(agency_a, membership_a, monkeypatch) -> None:
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    entries = [{**ENTRIES[0], "sure": True}, {**ENTRIES[1], "sure": False}]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=entries)
        packet = packets.mint_packet(application)

    assert [e.profile_field for e in packet.entries] == ["identity.full_name"]
    assert [(h.selector, h.profile_field, h.reason) for h in packet.hints] == [
        ("#city", "personal.city", "unsure"),
    ]
    assert "value" not in packet.hints[0].model_dump()


def test_a_fact_the_student_lacks_is_a_hint_and_blocks_nothing(
    agency_a, membership_a, monkeypatch
) -> None:
    """Owner, 2026-10-09 (decision A): the red "You fill this" box is enough.
    No counsellor escalation, no blocked application; the field is recorded and
    handed to the background fact reader's hook."""
    from apps.portals import packets
    from apps.portals.models import Application, ApplicationStep

    asked: list[tuple[object, list[str]]] = []
    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    monkeypatch.setattr(
        packets, "request_fact_reading",
        lambda application, fields: asked.append((application.id, list(fields))),
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        packet = packets.mint_packet(application)
        application.refresh_from_db()
        step = ApplicationStep.objects.get(application=application, kind="PACKET")
        escalated = ApplicationStep.objects.filter(
            application=application, kind="ESCALATION"
        ).exists()

    assert [(h.profile_field, h.reason) for h in packet.hints] == [("personal.city", "no_fact")]
    assert step.detail["missing_fields"] == ["personal.city"]
    assert step.detail["hints"] == [
        {"selector": "#city", "profile_field": "personal.city", "reason": "no_fact",
         "offer_fact_id": ""}
    ]
    assert asked == [(application.id, ["personal.city"])]
    assert not escalated
    assert application.state != Application.State.BLOCKED_MISSING_FACT


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


TRANSCRIPT_SLOTS = [
    {"selector": "#t1o", "kind": "TRANSCRIPT", "variant": "ORIGINAL", "degree": 1, "sure": True},
    {"selector": "#t1e", "kind": "TRANSCRIPT", "variant": "TRANSLATION", "degree": 1,
     "sure": True},
]


def _clean_upload(agency, student, kind: str):
    from apps.concierge.documents import register
    from apps.concierge.models import DocumentVersion

    document = register(agency.id, student.id, kind=kind)
    DocumentVersion.objects.filter(id=document.id).update(
        state="AVAILABLE", scan_result="NO_THREATS_FOUND", promoted_key=f"p/{document.id}",
        content_type="application/pdf",
    )
    return document


def test_a_translation_goes_to_the_translation_box_by_selector(
    agency_a, membership_a, paid_cycle_a, monkeypatch
) -> None:
    from apps.documents.models import TranscriptUpload
    from apps.portals import packets
    from apps.portals.models import ApplicationStep, FieldMap

    monkeypatch.setattr(
        packets, "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        FieldMap.objects.filter(portal_form=application.portal_form).update(
            slots=TRANSCRIPT_SLOTS
        )
        upload = _clean_upload(agency_a, membership_a, "TRANSCRIPT")
        TranscriptUpload.objects.create(
            tenant=agency_a, student=membership_a, cycle=paid_cycle_a, document_id=upload.id,
            role=TranscriptUpload.Role.TRANSLATION,
        )
        packet = packets.mint_packet(application)
        step = ApplicationStep.objects.get(application=application, kind="PACKET")

    [document] = packet.documents
    assert (document.selector, document.upload_id, document.kind) == (
        "#t1e", upload.id, "TRANSCRIPT",
    )
    assert document.filename == f"transcript-{upload.id}.pdf"
    assert step.detail["uploads"] == [{"upload_id": str(upload.id)}]
    assert step.detail["documents"] == []


def test_only_the_newest_clean_upload_of_a_kind_is_held(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets
    from apps.portals.models import FieldMap

    monkeypatch.setattr(
        packets, "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    cv_slot = [{"selector": "#cv", "kind": "CV", "variant": "ANY", "degree": None, "sure": True}]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        FieldMap.objects.filter(portal_form=application.portal_form).update(slots=cv_slot)
        _clean_upload(agency_a, membership_a, "CV")
        newest = _clean_upload(agency_a, membership_a, "CV")
        packet = packets.mint_packet(application)
    assert [d.upload_id for d in packet.documents] == [newest.id]


def test_a_two_degree_student_holds_both_transcripts(agency_a, membership_a, monkeypatch) -> None:
    """Per-degree kinds keep one upload per degree; the two boxes become a choice."""
    from apps.portals import packets
    from apps.portals.models import FieldMap

    monkeypatch.setattr(packets, "verified_values", lambda student: {
        "education.1.institution_original": "BSU", "education.2.institution_original": "ADA",
    })
    slots = [
        {"selector": "#t1", "kind": "TRANSCRIPT", "variant": "ORIGINAL", "degree": 1, "sure": True},
        {"selector": "#t2", "kind": "TRANSCRIPT", "variant": "ORIGINAL", "degree": 2, "sure": True},
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        FieldMap.objects.filter(portal_form=application.portal_form).update(slots=slots)
        first = _clean_upload(agency_a, membership_a, "TRANSCRIPT")
        second = _clean_upload(agency_a, membership_a, "TRANSCRIPT")
        packet = packets.mint_packet(application)
    assert {c.upload_id for c in packet.choices} == {first.id, second.id}


def _cv_slot_application(agency, student, monkeypatch, slots=None):
    from apps.portals import packets
    from apps.portals.models import FieldMap

    monkeypatch.setattr(
        packets, "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    application = _application(agency, student)
    FieldMap.objects.filter(portal_form=application.portal_form).update(
        slots=slots or [
            {"selector": "#cv", "kind": "CV", "variant": "ANY", "degree": None, "sure": True}
        ]
    )
    return application


def test_a_cv_upload_is_not_held_when_the_kit_has_an_approved_cv_draft(
    agency_a, membership_a, monkeypatch
) -> None:
    """Controller ruling (Task 4 review): the approved draft is the CV. A CV
    upload is then never paired, never named in `uploads`, never servable --
    so the draft, alone on the CV box, is assigned to it."""
    from apps.portals import packets
    from apps.portals.models import ApplicationStep
    from tests.portals.test_kit import _approved_cv

    with tenant_scope(agency_a.id):
        application = _cv_slot_application(agency_a, membership_a, monkeypatch)
        draft = _approved_cv(agency_a, membership_a)
        _clean_upload(agency_a, membership_a, "CV")
        packet = packets.mint_packet(application)
        step = ApplicationStep.objects.get(application=application, kind="PACKET")

    [document] = packet.documents
    assert (document.draft_id, document.upload_id, document.selector) == (draft.id, None, "#cv")
    assert packet.choices == ()
    assert step.detail["uploads"] == []
    assert step.detail["documents"] == [
        {"draft_id": str(draft.id), "prepared_id": None, "filename": draft.rendered_filename}
    ]


def test_a_draft_with_one_box_and_a_rival_keeps_the_name_match_path(
    agency_a, membership_a, monkeypatch
) -> None:
    """Two approved CV drafts (version 1 and version 2) against one CV box:
    since CV build step 4.2, kit_cv_drafts serves only the newest approved
    version, so version 2 pairs directly with the #cv slot without version 1
    acting as a rival."""
    from apps.documents.models import DocumentDraft
    from apps.portals import packets
    from apps.portals.models import ApplicationStep
    from tests.portals.test_kit import _approved_cv

    with tenant_scope(agency_a.id):
        application = _cv_slot_application(agency_a, membership_a, monkeypatch)
        _approved_cv(agency_a, membership_a, rendered_filename="cv-a.pdf")
        # (student, kind, version) is unique, so the second is version 2.
        second = DocumentDraft.objects.create(
            tenant=agency_a, student=membership_a, kind=DocumentDraft.Kind.CV, version=2,
            content={}, status=DocumentDraft.Status.APPROVED, rendered_filename="cv-b.pdf",
        )
        packet = packets.mint_packet(application)
        step = ApplicationStep.objects.get(application=application, kind="PACKET")

    assert [(d.draft_id, d.selector) for d in packet.documents] == [
        (second.id, "#cv"),
    ]
    assert packet.choices == ()
    assert [d["draft_id"] for d in step.detail["documents"]] == [str(second.id)]
    assert step.detail["uploads"] == []


def test_an_older_upload_and_an_unslotted_upload_are_never_named(
    agency_a, membership_a, monkeypatch
) -> None:
    """The serving boundary at the packet: `uploads` is what ext_api serves,
    so a superseded version of a kind, and a kind no box asks for, must be
    absent from it -- only the newest upload that fills a box is named."""
    from apps.portals import packets
    from apps.portals.models import ApplicationStep

    with tenant_scope(agency_a.id):
        application = _cv_slot_application(agency_a, membership_a, monkeypatch)
        older = _clean_upload(agency_a, membership_a, "CV")
        newest = _clean_upload(agency_a, membership_a, "CV")
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        packets.mint_packet(application)
        step = ApplicationStep.objects.get(application=application, kind="PACKET")

    named = [u["upload_id"] for u in step.detail["uploads"]]
    assert named == [str(newest.id)]
    assert str(older.id) not in named and str(passport.id) not in named


def test_the_packet_carries_formatted_values_and_the_portals_equivalences(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "2001-03-07"},
    )
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a, membership_a,
            value_formats={"personal.city": "DD.MM.YYYY"},
            readback_equivalences={"identity.full_name": "casefold"},
        )
        packet = packets.mint_packet(application)
        kit = packets.build_kit(application)
    assert [e.value for e in packet.entries] == ["Ada Byron", "07.03.2001"]
    assert packet.equivalences == {"identity.full_name": "casefold"}
    assert [q.answer for q in kit.questions] == [e.value for e in packet.entries]


def test_prose_fields_respect_control_max_length_at_sentence_boundaries(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    essay = (
        "First sentence about my academic preparation. "
        "Second sentence about why this programme fits my goals. "
        "Third sentence that pushes the essay past the character cap."
    )
    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    monkeypatch.setattr(
        packets,
        "narrative_values",
        lambda student, **kwargs: {"narrative.motivation_letter": essay},
    )
    entries = [
        {
            "profile_field": "narrative.motivation_letter",
            "sure": True,
            "max_length": 110,
            "action": {"selector": "#essay", "method": "fill", "arguments": ["%value%"]},
        }
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=entries)
        packet = packets.mint_packet(application)
        kit = packets.build_kit(application)

    expected = (
        "First sentence about my academic preparation. "
        "Second sentence about why this programme fits my goals."
    )
    assert packet.entries[0].value == expected
    assert len(packet.entries[0].value) <= 110
    assert kit.questions[0].answer == expected


def test_prose_entries_respect_word_and_char_limits_in_description(
    agency_a, membership_a
) -> None:
    from apps.portals.packets import _fit_entry_limits

    essay = (
        "First sentence has five words. "
        "Second sentence also has six words here. "
        "Third sentence is much longer than the limit allows."
    )
    trimmed_words = _fit_entry_limits(
        "narrative.why_programme",
        essay,
        None,
        "Why do you want to study here? (max 8 words)",
    )
    assert trimmed_words == "First sentence has five words."

    trimmed_chars = _fit_entry_limits(
        "narrative.career_plan",
        essay,
        None,
        "Career goals (maximum 40 characters)",
    )
    assert trimmed_chars == "First sentence has five words."
