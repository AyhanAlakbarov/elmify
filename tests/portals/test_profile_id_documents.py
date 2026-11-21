# tests/portals/test_profile_id_documents.py
"""Spec 2026-10-12 §4.2: which ID document a portal gets."""

import pytest
from django.utils import timezone

from apps.concierge.documents import register
from apps.documents.models import DocumentReading, VerifiedFact
from apps.portals.profile import verified_values
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _document(agency, student, payload):
    document = register(agency.id, student.id, kind="PASSPORT")
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        VerifiedFact.objects.create(
            student=student, category="ID_DOCUMENT", payload=payload,
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
            confirmed_by=student, confirmed_at=timezone.now(), created_by=student,
        )
        DocumentReading.objects.create(student=student, document=document, kind="PASSPORT",
                                       reader_version="id-1", state="READ")
    return document


def _values(agency, student):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return verified_values(student)


def test_the_valid_passport_with_the_latest_expiry_is_served(agency_a, membership_a):
    _document(agency_a, membership_a, {"document_type": "passport", "number": "OLD",
                                       "expiry_date": "2027-01-01"})
    _document(agency_a, membership_a, {"document_type": "passport", "number": "NEW",
                                       "expiry_date": "2031-01-01"})
    _document(agency_a, membership_a, {"document_type": "national_id", "number": "CARD",
                                       "expiry_date": "2035-01-01"})
    assert _values(agency_a, membership_a)["id_document.number"] == "NEW"


def test_an_expired_document_is_never_served(agency_a, membership_a):
    _document(agency_a, membership_a, {"document_type": "passport", "number": "GONE",
                                       "expiry_date": "2020-01-01"})
    assert "id_document.number" not in _values(agency_a, membership_a)


def test_the_students_choice_wins(agency_a, membership_a):
    chosen = _document(agency_a, membership_a, {"document_type": "passport", "number": "MINE",
                                                "expiry_date": "2028-01-01"})
    _document(agency_a, membership_a, {"document_type": "passport", "number": "OTHER",
                                       "expiry_date": "2031-01-01"})
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.filter(document=chosen).update(primary_chosen_at=timezone.now())
    assert _values(agency_a, membership_a)["id_document.number"] == "MINE"


def test_doubtful_keys_of_a_document_are_not_served(agency_a, membership_a):
    document = _document(agency_a, membership_a, {"document_type": "passport", "number": "N1",
                                                  "expiry_date": "2031-01-01"})
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a, category="ID_DOCUMENT", payload={"issue_date": "2021-01-01"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
            created_by=membership_a,
        )
    assert "id_document.issue_date" not in _values(agency_a, membership_a)


def _citizenship(agency, student, document, value, *, confirmed, proven, why):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        VerifiedFact.objects.create(
            student=student, category="IDENTITY", payload={"citizenship": value},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
            confirmed_by=student if confirmed else None,
            confirmed_at=timezone.now() if confirmed else None, created_by=student,
        )
        DocumentReading.objects.filter(document=document).update(values=[
            {"key": "identity.citizenship", "value": value, "snippet": value,
             "proven": proven, "why": why}])


def _dual_national(agency, student):
    """AZ read first (its citizenship is the confirmed ledger value), TR second:
    its differing citizenship waits as a detail to check."""
    az = _document(agency, student, {"document_type": "passport", "number": "AZ1",
                                     "expiry_date": "2031-01-01"})
    tr = _document(agency, student, {"document_type": "passport", "number": "TR1",
                                     "expiry_date": "2029-01-01"})
    _citizenship(agency, student, az, "Azerbaijan", confirmed=True, proven=True, why="strip_agrees")
    _citizenship(agency, student, tr, "Turkey", confirmed=False, proven=False,
                 why="document_differs")
    return az, tr


def test_a_chosen_passport_travels_with_its_own_citizenship(agency_a, membership_a):
    _, tr = _dual_national(agency_a, membership_a)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.filter(document=tr).update(primary_chosen_at=timezone.now())
    values = _values(agency_a, membership_a)
    assert values["id_document.number"] == "TR1"
    assert values["identity.citizenship"] == "Turkey"


def test_an_unchosen_passport_travels_with_its_own_citizenship(agency_a, membership_a):
    _dual_national(agency_a, membership_a)
    values = _values(agency_a, membership_a)
    assert values["id_document.number"] == "AZ1"
    assert values["identity.citizenship"] == "Azerbaijan"


def test_a_passport_that_proved_no_citizenship_keeps_the_ledgers(agency_a, membership_a):
    az, _ = _dual_national(agency_a, membership_a)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.filter(document=az).update(primary_chosen_at=timezone.now())
        VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"citizenship": "Georgia"},
            source_tier="STUDENT_STATEMENT", confirmed_by=membership_a,
            confirmed_at=timezone.now(), created_by=membership_a,
        )
        DocumentReading.objects.filter(document=az).update(values=[])
    assert _values(agency_a, membership_a)["identity.citizenship"] == "Georgia"


def test_a_single_passport_is_unchanged(agency_a, membership_a):
    doc = _document(agency_a, membership_a, {"document_type": "passport", "number": "AZ1",
                                             "expiry_date": "2031-01-01"})
    _citizenship(agency_a, membership_a, doc, "Azerbaijan", confirmed=True, proven=True,
                 why="strip_agrees")
    assert _values(agency_a, membership_a)["identity.citizenship"] == "Azerbaijan"
