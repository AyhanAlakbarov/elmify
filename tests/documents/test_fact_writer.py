# tests/documents/test_fact_writer.py
"""Spec 2026-10-12 §6.2: precedence, one test per rule."""

import pytest
from django.utils import timezone

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents.fact_writer import correct_fact, write_facts
from apps.documents.id_reading import ReadValue
from apps.documents.models import DocumentReading, VerifiedFact
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _read(agency, student, values, kind="PASSPORT"):
    document = register(agency.id, student.id, kind=kind)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        reading = DocumentReading.objects.create(
            student=student, document=document, kind=kind, reader_version="id-1",
            state="READ", values=[v.as_dict() for v in values],
        )
        write_facts(reading)
        reading.refresh_from_db()
    return reading


def _v(key, value, proven=True, why="check_digit"):
    return ReadValue(key, value, value, proven, why)


def _current(student, category, key):
    return [f for f in VerifiedFact.objects.filter(student=student, category=category,
                                                   superseded_by__isnull=True)
            if key in f.payload]


def test_a_proven_value_is_a_confirmed_fact_the_machine_wrote(agency_a, membership_a):
    reading = _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    with tenant_scope(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "date_of_birth")
        assert fact.confirmed_at is not None and fact.confirmed_by == membership_a
        assert fact.source_ref == f"document:{reading.document_id}"
        event = AuditEvent.objects.get(object_id=fact.id)
        assert (event.event, event.actor_id, event.actor_kind) == (
            "fact.read_from_document", None, "AGENT")
    assert reading.facts_written


def test_a_doubtful_value_waits_unconfirmed(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", False, "low_confidence")])
    with tenant_scope(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "place_of_birth")
        assert fact.confirmed_at is None


def test_the_students_own_entry_wins(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        own = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"date_of_birth": "1998-03-15"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv", confirmed_by=membership_a,
            confirmed_at=timezone.now(), created_by=membership_a,
        )
    reading = _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    with tenant_scope(agency_a.id):
        rows = _current(membership_a, "IDENTITY", "date_of_birth")
        assert own in rows
        read = next(f for f in rows if f.id != own.id)
        assert read.confirmed_at is None
    assert reading.values[0]["why"] == "student_entry_differs"


def test_an_agreeing_read_writes_nothing(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    with tenant_scope(agency_a.id):
        assert len(_current(membership_a, "IDENTITY", "date_of_birth")) == 1


def test_a_renewal_with_a_new_surname_becomes_a_detail_to_check(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.surname", "ALIYEVA")])
    _read(agency_a, membership_a, [_v("identity.surname", "HUSEYNOVA")])
    with tenant_scope(agency_a.id):
        rows = _current(membership_a, "IDENTITY", "surname")
        confirmed = [f.payload["surname"] for f in rows if f.confirmed_at]
        waiting = [f.payload["surname"] for f in rows if not f.confirmed_at]
    assert confirmed == ["ALIYEVA"] and waiting == ["HUSEYNOVA"]


def test_a_newer_proven_unprotected_value_supersedes_an_older_read(agency_a, membership_a):
    # Ages must be known (confirmed issue dates) for a newer document to replace.
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKI", why="confident"),
                                   _v("id_document.issue_date", "2020-01-01")])
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", why="confident"),
                                   _v("id_document.issue_date", "2024-01-01")])
    with tenant_scope(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "place_of_birth")
        assert fact.payload["place_of_birth"] == "BAKU" and fact.supersedes is not None


def test_an_id_document_is_one_row_with_its_doubtful_keys_beside_it(agency_a, membership_a):
    reading = _read(agency_a, membership_a, [
        _v("id_document.number", "C01X00T47"),
        _v("id_document.expiry_date", "2031-05-19"),
        _v("id_document.issue_date", "2021-05-20", False, "low_confidence"),
    ])
    ref = f"document:{reading.document_id}"
    with tenant_scope(agency_a.id):
        rows = list(VerifiedFact.objects.filter(student=membership_a, category="ID_DOCUMENT",
                                                source_ref=ref))
        confirmed = [f for f in rows if f.confirmed_at]
        assert len(confirmed) == 1
        assert confirmed[0].payload == {"number": "C01X00T47", "expiry_date": "2031-05-19"}
        assert [f.payload for f in rows if not f.confirmed_at] == [{"issue_date": "2021-05-20"}]
        document = DocumentVersion.objects.get(id=reading.document_id)
        assert str(document.expires_on) == "2031-05-19"


def test_a_typed_expiry_is_never_overwritten(agency_a, membership_a):
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentVersion.objects.filter(id=document.id).update(expires_on="2030-01-01")
        reading = DocumentReading.objects.create(
            student=membership_a, document=document, kind="PASSPORT", reader_version="id-1",
            state="READ", values=[_v("id_document.expiry_date", "2031-05-19").as_dict()],
        )
        write_facts(reading)
        assert str(DocumentVersion.objects.get(id=document.id).expires_on) == "2030-01-01"


def test_a_correction_supersedes_with_the_students_own_entry(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKI", False, "low_confidence")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "place_of_birth")
        new = correct_fact(student=membership_a, fact_id=fact.id, key="place_of_birth",
                           value="Baku")
        assert new.supersedes_id == fact.id and new.source_tier == "STUDENT_STATEMENT"
        assert new.confirmed_by == membership_a and new.payload == {"place_of_birth": "Baku"}


def test_a_correction_refuses_a_bad_date_and_someone_elses_fact(agency_a, membership_a,
                                                                membership_b):
    from apps.documents.confirmation import FactNotFound

    _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "date_of_birth")
        with pytest.raises(ValueError):
            correct_fact(student=membership_a, fact_id=fact.id, key="date_of_birth",
                         value="14/03/1998")
        with pytest.raises(FactNotFound):
            correct_fact(student=membership_b, fact_id=fact.id, key="date_of_birth",
                         value="1998-03-14")


# --- fix round 1: reviewer probes ---------------------------------------------------

from apps.documents.verification import payload_keys  # noqa: E402
from apps.portals.profile import verified_values  # noqa: E402


def _reread(agency, student, values, document, rv):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        reading = DocumentReading.objects.create(
            student=student, document=document, kind="PASSPORT", reader_version=rv,
            state="READ", values=[v.as_dict() for v in values],
        )
        write_facts(reading)
        reading.refresh_from_db()
    return reading


def _served(agency, student):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return verified_values(student)


def _passport(number="C01X00T47", authority="MIA", extra=()):
    return [_v("id_document.document_type", "passport"), _v("id_document.number", number),
            _v("id_document.expiry_date", "2031-05-19"),
            _v("id_document.issuing_authority", authority, why="confident"), *extra]


def test_a_reread_never_replaces_the_students_correction(agency_a, membership_a):
    reading = _read(agency_a, membership_a, _passport())
    document = reading.document
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (main,) = [f for f in VerifiedFact.objects.filter(
            student=membership_a, category="ID_DOCUMENT", superseded_by__isnull=True,
            confirmed_at__isnull=False)]
        correct_fact(student=membership_a, fact_id=main.id, key="issuing_authority",
                     value="Ministry of Internal Affairs")
    again = _reread(agency_a, membership_a, _passport(), document, "id-2")
    assert _served(agency_a, membership_a)["id_document.issuing_authority"] == (
        "Ministry of Internal Affairs")
    row = next(v for v in again.values if v["key"] == "id_document.issuing_authority")
    assert (row["proven"], row["why"]) == (False, "student_entry_differs")


def test_a_reread_keeps_a_corrected_doubtful_key(agency_a, membership_a):
    doubtful = _passport(extra=[_v("id_document.issue_date", "2021-05-20", False,
                                   "low_confidence")])
    reading = _read(agency_a, membership_a, doubtful)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (wait,) = [f for f in VerifiedFact.objects.filter(
            student=membership_a, category="ID_DOCUMENT", superseded_by__isnull=True,
            confirmed_at__isnull=True)]
        correct_fact(student=membership_a, fact_id=wait.id, key="issue_date", value="2021-05-21")
    _reread(agency_a, membership_a, doubtful, reading.document, "id-2")
    assert _served(agency_a, membership_a)["id_document.issue_date"] == "2021-05-21"
    with tenant_scope(agency_a.id):
        mains = VerifiedFact.objects.filter(student=membership_a, category="ID_DOCUMENT",
                                            superseded_by__isnull=True, confirmed_at__isnull=False,
                                            source_tier="AUTHORITATIVE_DOCUMENT")
        assert mains.count() == 1


def test_a_cv_identity_row_with_null_keys_blocks_nothing(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        payload = dict.fromkeys(payload_keys("IDENTITY"))
        payload["full_name"] = "Leyla Aliyeva"
        VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload=payload,
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv", confirmed_by=membership_a,
            confirmed_at=timezone.now(), created_by=membership_a,
        )
    reading = _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    assert reading.values[0]["proven"] is True
    assert _served(agency_a, membership_a)["identity.date_of_birth"] == "1998-03-14"


def test_a_doubtful_value_later_proven_is_confirmed(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", False, "low_confidence")])
    reading = _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU")])
    with tenant_scope(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "place_of_birth")
        assert fact.confirmed_at is not None
        assert AuditEvent.objects.filter(object_id=fact.id, actor_kind="AGENT").exists()
    assert reading.values[0]["proven"] is True


def test_values_report_what_the_ledger_did_for_a_waiting_row(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"date_of_birth": "1998-03-15"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv", confirmed_by=membership_a,
            confirmed_at=timezone.now(), created_by=membership_a,
        )
    _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    second = _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    assert (second.values[0]["proven"], second.values[0]["why"]) == (
        False, "student_entry_differs")


def test_an_older_document_never_supersedes_a_newer_one(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", why="confident"),
                                   _v("id_document.issue_date", "2024-01-01")])
    old = _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKI", why="confident"),
                                         _v("id_document.issue_date", "2014-01-01")])
    assert _served(agency_a, membership_a)["identity.place_of_birth"] == "BAKU"
    row = next(v for v in old.values if v["key"] == "identity.place_of_birth")
    assert (row["proven"], row["why"]) == (False, "older_document")


# --- fix round 2 ------------------------------------------------------------------

from apps.documents.confirmation import confirm_facts  # noqa: E402


def _pob(agency, student):
    with tenant_scope(agency.id):
        return [(f.payload["place_of_birth"], f.confirmed_at is not None, f.source_ref)
                for f in _current(student, "IDENTITY", "place_of_birth")]


def _why(reading, key):
    row = next(v for v in reading.values if v["key"] == key)
    return row["proven"], row["why"]


def test_an_undated_current_document_cannot_be_ordered(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", why="confident")])
    new = _read(agency_a, membership_a, [_v("identity.place_of_birth", "SUMQAYIT", why="confident"),
                                         _v("id_document.issue_date", "2025-06-01")])
    assert _why(new, "identity.place_of_birth") == (False, "document_differs")
    assert _served(agency_a, membership_a)["identity.place_of_birth"] == "BAKU"
    assert ("SUMQAYIT", False) in [(p, c) for p, c, _ in _pob(agency_a, membership_a)]


def test_a_doubtful_issue_date_decides_no_age(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", why="confident"),
                                   _v("id_document.issue_date", "2024-01-01")])
    old = _read(agency_a, membership_a, [
        _v("identity.place_of_birth", "BAKI", why="confident"),
        _v("id_document.issue_date", "2041-01-01", False, "low_confidence")])
    assert _why(old, "identity.place_of_birth") == (False, "document_differs")
    assert _served(agency_a, membership_a)["identity.place_of_birth"] == "BAKU"


def test_equal_ages_let_the_later_read_win(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", why="confident"),
                                   _v("id_document.issue_date", "2024-01-01")])
    later = _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKI", why="confident"),
                                           _v("id_document.issue_date", "2024-01-01")])
    assert _why(later, "identity.place_of_birth")[0] is True
    assert _served(agency_a, membership_a)["identity.place_of_birth"] == "BAKI"


def test_a_use_choice_survives_a_reread_that_adds_a_key(agency_a, membership_a):
    reading = _read(agency_a, membership_a, _passport())
    document = reading.document
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (main,) = VerifiedFact.objects.filter(
            student=membership_a, category="ID_DOCUMENT",
            superseded_by__isnull=True, confirmed_at__isnull=False)
        correct_fact(student=membership_a, fact_id=main.id, key="issuing_authority",
                     value="Ministry of Internal Affairs")
    _reread(agency_a, membership_a, _passport(), document, "id-2")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (waiting,) = VerifiedFact.objects.filter(student=membership_a, category="ID_DOCUMENT",
                                                 superseded_by__isnull=True,
                                                 confirmed_at__isnull=True)
        confirm_facts(student=membership_a, fact_ids=[waiting.id], actor=membership_a)
    assert _served(agency_a, membership_a)["id_document.issuing_authority"] == "MIA"
    _reread(agency_a, membership_a, _passport(extra=[_v("id_document.issue_date", "2021-05-20")]),
            document, "id-3")
    served = _served(agency_a, membership_a)
    assert served["id_document.issuing_authority"] == "MIA"
    assert served["id_document.issue_date"] == "2021-05-20"


def test_a_proof_writes_its_own_row_and_leaves_no_stale_waiting_row(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", False, "low_confidence"),
                                   _v("id_document.issue_date", "2014-01-01")])
    proof = _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", why="confident"),
                                           _v("id_document.issue_date", "2024-01-01")])
    ((value, confirmed, ref),) = _pob(agency_a, membership_a)
    assert (value, confirmed, ref) == ("BAKU", True, f"document:{proof.document_id}")
    older = _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKI", why="confident"),
                                           _v("id_document.issue_date", "2018-01-01")])
    assert _why(older, "identity.place_of_birth") == (False, "older_document")
    assert _served(agency_a, membership_a)["identity.place_of_birth"] == "BAKU"


# --- fix round 3 ------------------------------------------------------------------

def test_a_merge_never_carries_a_key_the_student_owns(agency_a, membership_a):
    first = _read(agency_a, membership_a, _passport())
    document = first.document
    doubtful = [_v("id_document.issuing_authority", "MlA", False, "low_confidence")]
    _reread(agency_a, membership_a, _passport()[:3] + doubtful, document, "id-2")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (waiting,) = VerifiedFact.objects.filter(
            student=membership_a, category="ID_DOCUMENT", superseded_by__isnull=True,
            confirmed_at__isnull=True)
        correct_fact(student=membership_a, fact_id=waiting.id, key="issuing_authority",
                     value="Ministry of Internal Affairs")
    _reread(agency_a, membership_a,
            _passport(extra=[_v("id_document.issue_date", "2021-05-20")]), document, "id-3")
    served = _served(agency_a, membership_a)
    assert served["id_document.issuing_authority"] == "Ministry of Internal Affairs"
    assert served["id_document.issue_date"] == "2021-05-20"


def test_a_proof_never_supersedes_a_cv_row(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        payload = dict.fromkeys(payload_keys("IDENTITY"))
        payload.update(full_name="Leyla Aliyeva", date_of_birth="1998-03-14")
        cv = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload=payload,
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv", created_by=membership_a)
    _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert not VerifiedFact.objects.filter(supersedes=cv).exists()
        confirm_facts(student=membership_a, fact_ids=[cv.id], actor=membership_a)
        cv.refresh_from_db()
        assert cv.confirmed_at is not None
