"""Spec 2026-10-12 §4: the keys a passport read writes, and the consumers that
must keep finding the full-name row among more IDENTITY rows."""

import pytest
from django.utils import timezone

from apps.documents.models import VerifiedFact
from apps.documents.verification import ID_DOCUMENT_KEYS, generatable_facts, payload_keys
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_identity_carries_the_passport_person_keys():
    keys = payload_keys(VerifiedFact.Category.IDENTITY)
    for key in ("date_of_birth", "sex", "citizenship", "given_names", "surname", "place_of_birth"):
        assert key in keys


def test_id_document_has_its_own_keys():
    assert ID_DOCUMENT_KEYS == (
        "document_type", "number", "issuing_country", "issue_date", "expiry_date",
        "issuing_authority",
    )
    assert payload_keys(VerifiedFact.Category.ID_DOCUMENT) == ID_DOCUMENT_KEYS


def test_every_new_key_is_learnable():
    from apps.portals.profile import LEARNABLE_FIELDS

    assert "identity.date_of_birth" in LEARNABLE_FIELDS
    assert "identity.citizenship" in LEARNABLE_FIELDS
    assert "id_document.number" in LEARNABLE_FIELDS
    assert "id_document.expiry_date" in LEARNABLE_FIELDS


def _fact(student, category, payload, confirmed=True):
    return VerifiedFact.objects.create(
        student=student, category=category, payload=payload,
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref="document:test", confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None, created_by=student,
    )


def test_generation_never_sees_an_id_document(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _fact(membership_a, VerifiedFact.Category.ID_DOCUMENT, {"number": "C01X00T47"})
        assert not generatable_facts(membership_a).filter(
            category=VerifiedFact.Category.ID_DOCUMENT
        ).exists()


def test_a_passport_identity_row_is_not_a_cv_identity(agency_a, membership_a):
    """CV generation refuses a student with no confirmed full name, even when a
    passport read wrote their date of birth."""
    from apps.documents.generation import IdentityNotConfirmed, generate_cv

    with tenant_scope(agency_a.id):
        _fact(membership_a, VerifiedFact.Category.IDENTITY, {"date_of_birth": "1999-04-12"})
        with pytest.raises(IdentityNotConfirmed):
            generate_cv(student=membership_a)


def test_missing_contact_reads_the_full_name_row(agency_a, membership_a):
    from apps.documents.gaps import missing_contact

    with tenant_scope(agency_a.id):
        name = _fact(membership_a, VerifiedFact.Category.IDENTITY, {"full_name": "Ana Lee"})
        _fact(membership_a, VerifiedFact.Category.IDENTITY, {"date_of_birth": "1999-04-12"})
        questions = missing_contact(membership_a)
    assert questions and all(q.fact_id == name.id for q in questions)


def test_language_carries_the_certificate_keys_apart_from_the_self_assessment():
    keys = payload_keys(VerifiedFact.Category.LANGUAGE)
    for key in ("test_variant", "test_date", "certificate_number", "score_listening",
                "score_reading", "score_writing", "score_speaking"):
        assert key in keys
    # Europass self-assessment levels keep their own names.
    assert "listening" in keys and "writing" in keys


def test_education_carries_the_diploma_number():
    assert "diploma_number" in payload_keys(VerifiedFact.Category.EDUCATION)


def test_a_read_value_carries_its_target_through_the_reading_row():
    from apps.documents.id_reading import ReadValue

    value = ReadValue("education.end_date", "2023-06-30", "30.06.2023", False,
                      "document_differs", target="abc")
    assert ReadValue.from_dict(value.as_dict()) == value
    old = {"key": "k", "value": "v", "snippet": "s", "proven": True, "why": "check_digit"}
    assert ReadValue.from_dict(old).target == ""  # rows written by plan 1


def test_a_cv_never_builds_the_document_only_keys():
    """As plan 1 ruled for the passport-only IDENTITY keys (final review I1): a CV
    row keeps master's shape, so a document read is the only writer of these keys."""
    from apps.documents.schemas import EducationEntry, LanguageEntry
    from apps.documents.verification import fact_payload

    language = fact_payload(LanguageEntry(language="English", test_name="IELTS",
                                          test_score="7.0"),
                            category=VerifiedFact.Category.LANGUAGE)
    assert "test_date" not in language and "score_writing" not in language
    assert language["test_score"] == "7.0"
    degree = fact_payload(EducationEntry(degree_as_awarded="BSc", institution_original="ADA"),
                          category=VerifiedFact.Category.EDUCATION)
    assert "diploma_number" not in degree
