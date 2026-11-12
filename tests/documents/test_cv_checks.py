from types import SimpleNamespace

import pytest

from apps.documents.cv_checks import consistency_notes, name_notes
from apps.documents.models import VerifiedFact
from apps.documents.schemas import EducationEntry

from .test_render import _content


def _identity(payload, tier=VerifiedFact.SourceTier.STUDENT_STATEMENT):
    return SimpleNamespace(payload=payload, source_tier=tier)


def _named(name):
    content = _content()
    personal = content.personal_information.model_copy(update={"full_name": name})
    return content.model_copy(update={"personal_information": personal})


def test_the_same_name_in_another_order_or_case_is_no_note():
    assert name_notes(_named("Aliyev Leyla"), [_identity({"full_name": "LEYLA ALIYEV"})]) == []


def test_a_passport_spelling_that_differs_is_a_note_naming_both():
    """Azerbaijani passports print Ə as A in the English spelling (spec §9)."""
    passport = _identity({"full_name": "Leyla Aliyeva"},
                         VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT)
    (note,) = name_notes(_named("Leyla Əliyeva"), [passport])
    assert "Leyla Əliyeva" in note and "Leyla Aliyeva" in note and "the passport" in note


def test_a_surname_the_cv_name_lacks_is_a_note():
    notes = name_notes(_named("Leyla Aliyeva"),
                       [_identity({"full_name": "Leyla Aliyeva", "surname": "Mammadova"})])
    assert notes == ["The CV name “Leyla Aliyeva” does not contain the surname "
                     "“Mammadova” the student gave as in their passport."]


def test_a_passport_given_names_key_the_cv_name_lacks_is_a_note():
    notes = name_notes(
        _named("L. Aliyeva"),
        [
            _identity(
                {"given_names": "Leyla", "surname": "Aliyeva"},
                VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            )
        ],
    )
    assert notes == [
        "The CV name “L. Aliyeva” does not contain the given name "
        "“Leyla” the student gave as in their passport."
    ]


def test_a_malformed_identity_payload_is_skipped():
    assert name_notes(_named("Leyla Aliyeva"), [_identity("junk"), _identity({})]) == []


def _degrees():
    return _content(education=(
        EducationEntry(degree_as_awarded="BSc Chemistry", institution_original="ADA University",
                       start_date="2020-09-01", end_date="2024-06-30", grade_native="3.8"),
        EducationEntry(degree_as_awarded="Attestat", institution_original="School No. 6",
                       end_date="2020-06-30"),
    ))


def _value(field, value, selector="#f"):
    return {"selector": selector, "value": value, "profile_field": field}


def test_matching_form_values_are_no_note():
    """Oldest first, as the packet indexes degrees (portals.profile.verified_values)."""
    values = [_value("education.1.degree_as_awarded", "Attestat"),
              _value("education.2.end_date", "2024-06-30"),
              _value("education.2.grade_native", "3.8")]
    assert consistency_notes(_degrees(), title="MSc Chemistry, TUM", packet_values=values,
                             typed_over={}) == []


def test_a_date_the_form_states_differently_is_a_note():
    (note,) = consistency_notes(_degrees(), title="MSc Chemistry, TUM",
                                packet_values=[_value("education.2.end_date", "2024-07-31")],
                                typed_over={})
    assert note == ("MSc Chemistry, TUM: the application form gives degree 2 end date "
                    "“2024-07”, the CV says “2024-06”.")


def test_what_the_student_typed_over_our_value_is_what_the_form_says():
    values = [_value("education.2.grade_native", "3.8", selector="#gpa")]
    (note,) = consistency_notes(_degrees(), title="MSc Chemistry, TUM", packet_values=values,
                                typed_over={"#gpa": "3.6"})
    assert "“3.6”" in note and "“3.8”" in note


def test_unindexed_or_unknown_fields_and_extra_degrees_are_ignored():
    values = [_value("education.end_date", "1999-01-01"),          # unindexed: ambiguous
              _value("experience.title", "CEO"),                   # not compared
              _value("education.3.end_date", "2030-01-01"),        # no third degree on the CV
              {"selector": "#x", "value": None, "profile_field": "education.1.end_date"}]
    assert consistency_notes(_degrees(), title="T", packet_values=values, typed_over={}) == []


@pytest.mark.django_db
def test_counsellor_notes_pair_each_packet_with_the_draft_it_attached(
    agency_a, membership_a, program_factory
):
    from apps.documents.cv_checks import counsellor_notes
    from apps.documents.drafts import create_draft
    from apps.documents.models import DocumentDraft
    from apps.portals.models import Application, ApplicationStep
    from apps.tenancy.context import tenant_scope

    from .conftest import make_identity_fact

    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a, full_name="Jane Doe")
        draft = create_draft(student=membership_a, kind=DocumentDraft.Kind.CV,
                             content=_degrees())
        application = Application.objects.create(student=membership_a,
                                                 program_id=program_factory().id,
                                                 name="MSc Chemistry, TUM")
        ApplicationStep.objects.create(
            application=application, sequence=1, kind="PACKET",
            detail={"values": [_value("education.2.end_date", "2024-07-31")],
                    "documents": [{"draft_id": str(draft.id)}]},
        )
        notes = counsellor_notes(membership_a, [draft])
    assert notes[draft.id] == [
        "MSc Chemistry, TUM: the application form gives degree 2 end date “2024-07”, "
        "the CV says “2024-06”."
    ]


@pytest.mark.django_db
def test_a_redacted_draft_gets_no_notes_and_no_error(agency_a, membership_a):
    """Review Focus 2: redaction writes {} into content."""
    from apps.documents.cv_checks import counsellor_notes
    from apps.documents.drafts import create_draft
    from apps.documents.models import DocumentDraft
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        draft = create_draft(student=membership_a, kind=DocumentDraft.Kind.CV,
                             content=_degrees())
        DocumentDraft.objects.filter(id=draft.id).update(content={}, render_warnings={})
        draft.refresh_from_db()
        assert counsellor_notes(membership_a, [draft]) == {draft.id: []}
