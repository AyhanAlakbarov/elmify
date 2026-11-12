"""A replaced upload (DocumentVersion.retired_at) is disowned: what it was read into is
served and offered nowhere, and the ledger keeps it."""

from __future__ import annotations

from html import unescape

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents.models import DocumentReading, VerifiedFact
from apps.documents.verification import disowned_refs, retired_refs
from apps.portals.profile import document_offers, verified_values
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _passport(agency, student, number, expiry):
    document = register(agency.id, student.id, kind="PASSPORT")
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        VerifiedFact.objects.create(
            student=student, category="ID_DOCUMENT",
            payload={"document_type": "passport", "number": number, "expiry_date": expiry},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
            confirmed_by=student, confirmed_at=timezone.now(), created_by=student)
        DocumentReading.objects.create(student=student, document=document, kind="PASSPORT",
                                       reader_version="id-1", state="READ")
    return document


def _retire(agency, document):
    with tenant_scope(agency.id):
        DocumentVersion.objects.filter(id=document.id).update(retired_at=timezone.now())


def _values(agency, student):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return verified_values(student)


def test_a_replaced_passport_is_not_served_and_the_new_one_is(agency_a, membership_a):
    old = _passport(agency_a, membership_a, "OLD", "2033-01-01")  # the later expiry
    _passport(agency_a, membership_a, "NEW", "2031-01-01")
    assert _values(agency_a, membership_a)["id_document.number"] == "OLD"
    _retire(agency_a, old)
    assert _values(agency_a, membership_a)["id_document.number"] == "NEW"
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert retired_refs(membership_a) == {f"document:{old.id}"}
        assert disowned_refs(membership_a) == set()
        assert VerifiedFact.objects.filter(source_ref=f"document:{old.id}").exists()


def test_a_replaced_passport_awaiting_its_replacement_reading_serves_nothing(
    agency_a, membership_a
):
    old = _passport(agency_a, membership_a, "OLD", "2033-01-01")
    register(agency_a.id, membership_a.id, kind="PASSPORT")  # B: promoted, not yet read
    _retire(agency_a, old)
    assert "id_document.number" not in _values(agency_a, membership_a)


def test_a_replaced_passport_is_not_a_passport_to_choose_between(
    client, domain_a, user_a, agency_a, membership_a
):
    old = _passport(agency_a, membership_a, "OLD", "2033-01-01")
    _passport(agency_a, membership_a, "NEW", "2031-01-01")
    client.force_login(user_a)
    page = reverse("student-documents")
    assert "Which passport should we use?" in client.get(
        page, HTTP_HOST=domain_a.host).content.decode()
    _retire(agency_a, old)
    html = client.get(page, HTTP_HOST=domain_a.host).content.decode()
    assert "Which passport should we use?" not in html
    assert client.post(reverse("student-id-document-primary", args=[old.id]),
                       HTTP_HOST=domain_a.host).status_code == 404


def test_a_replaced_diplomas_waiting_values_are_not_offered(
    client, domain_a, user_a, agency_a, membership_a
):
    document = register(agency_a.id, membership_a.id, kind="DIPLOMA")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        degree = VerifiedFact.objects.create(
            student=membership_a, category="EDUCATION", payload={"degree_as_awarded": "Bachelor"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv", confirmed_by=membership_a,
            confirmed_at=timezone.now(), created_by=membership_a)
        DocumentReading.objects.create(
            student=membership_a, document=document, kind="DIPLOMA", reader_version="doc-1",
            state="READ", values=[{"key": "education.degree_as_awarded", "value": "Bakalavr",
                                   "snippet": "BAKALAVR", "proven": False,
                                   "why": "document_differs", "target": str(degree.id)}])
    client.force_login(user_a)
    page = reverse("student-documents")
    assert "Bakalavr" in unescape(client.get(page, HTTP_HOST=domain_a.host).content.decode())
    _retire(agency_a, document)
    assert "Bakalavr</strong>" not in unescape(
        client.get(page, HTTP_HOST=domain_a.host).content.decode())


# Final review 2, C1: a clearer scan of the same document must not take its values with it.


def _read(agency, student, values, kind="PASSPORT"):
    from apps.documents.fact_writer import write_facts

    document = register(agency.id, student.id, kind=kind, mode="ADD")
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        reading = DocumentReading.objects.create(
            student=student, document=document, kind=kind, reader_version="id-1",
            state="READ", values=[v.as_dict() for v in values], file_sha256=str(document.id))
        write_facts(reading)
        reading.refresh_from_db()
    return reading


def _v(key, value, proven=True, why="check_digit"):
    from apps.documents.id_reading import ReadValue

    return ReadValue(key, value, value, proven, why)


_PASSPORT = [_v("identity.surname", "ALIYEV"), _v("identity.date_of_birth", "1998-03-14"),
             _v("id_document.number", "C01234567"), _v("id_document.expiry_date", "2033-01-01"),
             _v("id_document.document_type", "passport")]


def test_replacing_a_passport_with_a_clearer_scan_keeps_its_identity_values(
        agency_a, membership_a):
    first = _read(agency_a, membership_a, _PASSPORT)
    assert _values(agency_a, membership_a)["identity.surname"] == "ALIYEV"
    _retire(agency_a, first.document)
    _read(agency_a, membership_a, _PASSPORT)
    after = _values(agency_a, membership_a)
    assert after.get("id_document.number") == "C01234567"
    assert after.get("identity.surname") == "ALIYEV"
    assert after.get("identity.date_of_birth") == "1998-03-14"


def test_a_students_correction_survives_replacing_the_passport(agency_a, membership_a):
    from apps.documents.fact_writer import correct_fact

    first = _read(agency_a, membership_a, _PASSPORT)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (row,) = [f for f in VerifiedFact.objects.filter(
            student=membership_a, category="IDENTITY", superseded_by__isnull=True)
            if "surname" in f.payload]
        correct_fact(student=membership_a, fact_id=row.id, key="surname", value="Aliyeva")
    _retire(agency_a, first.document)
    _read(agency_a, membership_a, _PASSPORT)
    # The new read's differing ALIYEV waits on the dashboard; the student's entry is served.
    assert _values(agency_a, membership_a).get("identity.surname") == "Aliyeva"


def test_replacing_a_diploma_with_a_clearer_scan_keeps_the_degree(agency_a, membership_a):
    degree = [_v("education.institution_original", "Baku State University", why="readers_agree"),
              _v("education.end_date", "2020-06-30", why="readers_agree"),
              _v("education.degree_as_awarded", "Bachelor", why="readers_agree")]
    first = _read(agency_a, membership_a, degree, kind="DIPLOMA")
    assert _values(agency_a, membership_a).get("education.institution_original")
    _retire(agency_a, first.document)
    _read(agency_a, membership_a, degree, kind="DIPLOMA")
    assert (_values(agency_a, membership_a).get("education.institution_original")
            == "Baku State University")


def test_an_added_valid_passport_with_a_doubtful_expiry_is_offered_not_called_expired(
        agency_a, membership_a):
    from apps.portals.profile import document_offers, expired_id_document

    _read(agency_a, membership_a, [_v("id_document.number", "OLD1"),
                                   _v("id_document.expiry_date", "2020-01-01"),
                                   _v("id_document.document_type", "passport")])
    _read(agency_a, membership_a, [_v("id_document.number", "NEW2"),
                                   _v("id_document.expiry_date", "2034-05-05", False,
                                      "low_confidence"),
                                   _v("id_document.document_type", "passport")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert expired_id_document(membership_a) == ""
        assert "id_document.expiry_date" in document_offers(membership_a)


# Final re-review: retirement hides by ID-document group, not by ref (probes P1-P6).


def _probe_row(agency, student, category, key):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        (row,) = [f for f in VerifiedFact.objects.filter(
            student=student, category=category, superseded_by__isnull=True)
            if key in f.payload and f.confirmed_at]
        return row


_ID = [_v("id_document.number", "C01234567"), _v("id_document.expiry_date", "2033-01-01"),
       _v("id_document.document_type", "passport"), _v("id_document.issue_date", "2023-01-02")]


def test_an_id_document_correction_survives_a_clearer_rescan(agency_a, membership_a):
    from apps.documents.fact_writer import correct_fact

    first = _read(agency_a, membership_a, _ID)
    row = _probe_row(agency_a, membership_a, "ID_DOCUMENT", "issue_date")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        correct_fact(student=membership_a, fact_id=row.id, key="issue_date", value="2023-01-03")
    assert _values(agency_a, membership_a)["id_document.issue_date"] == "2023-01-03"
    _retire(agency_a, first.document)
    _read(agency_a, membership_a, _ID)
    assert _values(agency_a, membership_a)["id_document.issue_date"] == "2023-01-03"


def test_an_id_document_correction_survives_an_added_rescan(agency_a, membership_a):
    from apps.documents.fact_writer import correct_fact

    _read(agency_a, membership_a, _ID)
    row = _probe_row(agency_a, membership_a, "ID_DOCUMENT", "issue_date")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        correct_fact(student=membership_a, fact_id=row.id, key="issue_date", value="2023-01-03")
    _read(agency_a, membership_a, _ID)  # ADD, not retired
    assert _values(agency_a, membership_a)["id_document.issue_date"] == "2023-01-03"


def test_a_doubtful_value_read_again_on_the_rescan_is_still_offered(agency_a, membership_a):
    pob = _v("identity.place_of_birth", "BAKU", proven=False, why="low_confidence")
    first = _read(agency_a, membership_a, _ID + [pob])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert "identity.place_of_birth" in document_offers(membership_a)
    _retire(agency_a, first.document)
    _read(agency_a, membership_a, _ID + [pob])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        offers = document_offers(membership_a)
    assert "identity.place_of_birth" in offers


def test_a_citizenship_correction_beats_the_rescans_waiting_value(agency_a, membership_a):
    from apps.documents.fact_writer import correct_fact

    cit = _v("identity.citizenship", "AZE")
    first = _read(agency_a, membership_a, _ID + [cit])
    row = _probe_row(agency_a, membership_a, "IDENTITY", "citizenship")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        correct_fact(student=membership_a, fact_id=row.id, key="citizenship", value="Azerbaijan")
    assert _values(agency_a, membership_a)["identity.citizenship"] == "Azerbaijan"
    _retire(agency_a, first.document)
    _read(agency_a, membership_a, _ID + [cit])
    assert _values(agency_a, membership_a)["identity.citizenship"] == "Azerbaijan"


def test_replaced_passport_number_not_served_or_offered(agency_a, membership_a):
    first = _read(agency_a, membership_a, [_v("id_document.number", "OLD1"),
                                           _v("id_document.expiry_date", "2033-01-01"),
                                           _v("id_document.document_type", "passport"),
                                           _v("id_document.issue_date", "2023-01-01", False,
                                              "low_confidence")])
    _retire(agency_a, first.document)
    vals = _values(agency_a, membership_a)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        offers = document_offers(membership_a)
    assert not any(k.startswith("id_document.") for k in vals), vals
    assert not offers, offers


def test_owner_mismatch_serves_nothing(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.surname", "MAMMADOVA", why="owner_mismatch"),
                                   _v("id_document.number", "X1", why="owner_mismatch")])
    assert _values(agency_a, membership_a) == {} or not any(
        k.startswith(("identity.", "id_document.")) for k in _values(agency_a, membership_a))


def test_clearer_rescan_keeps_citizenship(agency_a, membership_a):
    cit = _v("identity.citizenship", "AZE")
    first = _read(agency_a, membership_a, _ID + [cit])
    assert _values(agency_a, membership_a)["identity.citizenship"] == "AZE"
    _retire(agency_a, first.document)
    _read(agency_a, membership_a, _ID + [cit])
    assert _values(agency_a, membership_a).get("identity.citizenship") == "AZE"
