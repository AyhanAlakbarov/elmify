# tests/portals/test_packet_offers.py
"""Spec 2026-10-12 §7.2: what a packet says about values read from the student's
own documents."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from tests.portals.test_kit import _application
from tests.portals.test_packet import _clean_upload

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reading_on(monkeypatch):
    """An upload prompt is shown only for a kind some reader reads (final review I1);
    these tests are about the prompt, not the gate, so every kind reads. Only the
    packet's view is patched: the upload hook keeps the real, default-off switch."""
    from types import SimpleNamespace

    from apps.portals import packets

    monkeypatch.setattr(packets, "document_reading", SimpleNamespace(kind_enabled=lambda k: True))


def _entry(field, selector, sure=True):
    return {"profile_field": field, "sure": sure,
            "action": {"selector": selector, "method": "fill", "arguments": ["%value%"]}}


def _fact(student, document, category, payload, *, confirmed, tier="AUTHORITATIVE_DOCUMENT"):
    return VerifiedFact.objects.create(
        student=student, category=category, payload=payload, source_tier=tier,
        source_ref=f"document:{document.id}", confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None, created_by=student,
    )


def _hint(packet, field):
    return next(h for h in packet.hints if h.profile_field == field)


def _add_upload(agency, student, kind="PASSPORT"):
    """A clean upload added beside the one held (master's replace-or-add form: a dual
    national holds two passports; a plain register would REPLACE the first)."""
    from apps.concierge.documents import register
    from apps.concierge.models import DocumentVersion

    document = register(agency.id, student.id, kind=kind, mode="ADD")
    DocumentVersion.objects.filter(id=document.id).update(
        state="AVAILABLE", scan_result="NO_THREATS_FOUND", promoted_key=f"p/{document.id}",
        content_type="application/pdf",
    )
    return document


def test_a_doubtful_read_is_offered_on_its_hint_and_recorded(agency_a, membership_a):
    from apps.portals.models import ApplicationStep
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        fact = _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
                     confirmed=False)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("identity.date_of_birth", "#dob")])
        packet = mint_packet(application)
        step = ApplicationStep.objects.get(application=application, kind="PACKET")
    hint = _hint(packet, "identity.date_of_birth")
    assert hint.reason == "no_fact" and hint.offer is not None
    assert (hint.offer.fact_id, hint.offer.value, hint.offer.method, hint.offer.source_kind) == (
        fact.id, "1998-03-14", "fill", "passport")
    assert step.detail["hints"][0]["offer_fact_id"] == str(fact.id)
    assert "1998-03-14" not in str(step.detail["hints"])  # the step names the fact, not the value


def test_an_unsure_box_is_never_offered_a_value(agency_a, membership_a):
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
              confirmed=False)
        application = _application(
            agency_a, membership_a, entries=[_entry("identity.date_of_birth", "#dob", sure=False)])
        packet = mint_packet(application)
    assert _hint(packet, "identity.date_of_birth").offer is None


def test_nothing_uploaded_asks_for_the_upload_once(agency_a, membership_a):
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=[
            _entry("id_document.number", "#pno"), _entry("identity.phone", "#tel")])
        packet = mint_packet(application)
        _clean_upload(agency_a, membership_a, "PASSPORT")
        again = mint_packet(application)
    assert _hint(packet, "id_document.number").upload_kind == "PASSPORT"
    # identity.* maps to PASSPORT for the hook, but no passport fills a phone box.
    assert _hint(packet, "identity.phone").upload_kind == ""
    assert _hint(again, "id_document.number").upload_kind == ""  # uploaded, reading pending


def test_an_expired_passport_says_so_and_is_never_typed(agency_a, membership_a):
    from apps.portals.packets import mint_packet

    expired = (date.today() - timedelta(days=30)).isoformat()
    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "ID_DOCUMENT",
              {"document_type": "passport", "number": "OLD1", "expiry_date": expired},
              confirmed=True)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("id_document.number", "#pno")])
        packet = mint_packet(application)
    assert packet.entries == ()
    assert _hint(packet, "id_document.number").expired_on == expired


def test_a_value_proven_by_a_document_is_marked_and_a_corrected_one_is_not(agency_a,
                                                                          membership_a):
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
              confirmed=True)
        _fact(membership_a, passport, "IDENTITY", {"place_of_birth": "Baku"}, confirmed=True,
              tier="STUDENT_STATEMENT")
        application = _application(agency_a, membership_a, entries=[
            _entry("identity.date_of_birth", "#dob"), _entry("identity.place_of_birth", "#pob")])
        packet = mint_packet(application)
    kinds = {e.profile_field: e.source_kind for e in packet.entries}
    assert kinds == {"identity.date_of_birth": "passport", "identity.place_of_birth": ""}


def _read_as(student, document, why):
    from apps.documents.models import DocumentReading

    return DocumentReading.objects.create(
        student=student, document=document, kind="PASSPORT", reader_version="id-1",
        state="READ", file_sha256=f"sha-{document.id}",
        values=[{"key": "identity.date_of_birth", "value": "1998-03-14", "snippet": "",
                 "proven": False, "why": why}])


@pytest.mark.parametrize("why", ["owner_mismatch", "owner_unknown"])
def test_a_passport_not_tied_to_the_student_offers_nothing(agency_a, membership_a, why):
    """Carried from plan 1: no one-tap path for a value whose reading could not tie the
    passport to this student. owner_mismatch disowns the document (verification.
    disowned_refs), so it is not "held" either and the box asks for the student's own."""
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
              confirmed=False)
        _read_as(membership_a, passport, why)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("identity.date_of_birth", "#dob")])
        packet = mint_packet(application)
    hint = _hint(packet, "identity.date_of_birth")
    assert hint.offer is None
    assert hint.upload_kind == ("PASSPORT" if why == "owner_mismatch" else "")


def test_a_passport_value_is_offered_only_from_the_passport_portals_get(agency_a,
                                                                        membership_a):
    """Number, expiry and citizenship travel together (owner, 2026-10-13): a second
    passport's waiting values are never offered beside the served passport's."""
    from apps.portals.packets import mint_packet

    future = (date.today() + timedelta(days=900)).isoformat()
    with tenant_scope(agency_a.id):
        served = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, served, "ID_DOCUMENT",
              {"document_type": "passport", "number": "C01", "expiry_date": future},
              confirmed=True)
        other = _add_upload(agency_a, membership_a)
        _fact(membership_a, other, "ID_DOCUMENT", {"issue_date": "2015-05-05"}, confirmed=False)
        _fact(membership_a, other, "IDENTITY", {"citizenship": "Türkiye"}, confirmed=False)
        _fact(membership_a, served, "ID_DOCUMENT", {"issue_date": "2021-01-01"}, confirmed=False)
        application = _application(agency_a, membership_a, entries=[
            _entry("id_document.issue_date", "#issued"), _entry("identity.citizenship", "#cit")])
        packet = mint_packet(application)
    assert _hint(packet, "id_document.issue_date").offer.value == "2021-01-01"
    assert _hint(packet, "identity.citizenship").offer is None


def test_an_expired_passports_waiting_value_is_never_offered(agency_a, membership_a):
    from apps.portals.packets import mint_packet

    expired = (date.today() - timedelta(days=30)).isoformat()
    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "ID_DOCUMENT",
              {"document_type": "passport", "number": "OLD1", "expiry_date": expired},
              confirmed=True)
        _fact(membership_a, passport, "ID_DOCUMENT", {"issue_date": "2016-01-01"},
              confirmed=False)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("id_document.issue_date", "#issued")])
        packet = mint_packet(application)
    hint = _hint(packet, "id_document.issue_date")
    assert hint.offer is None and hint.expired_on == expired


def test_a_date_the_code_could_not_read_is_never_offered(agency_a, membership_a):
    """Plan 2 ruling (final review I3): no tap writes a date the ledger cannot hold as
    printed (fact_writer.needs_typing); the student types it."""
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "14 Mart 1998"},
              confirmed=False)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("identity.date_of_birth", "#dob")])
        packet = mint_packet(application)
    assert _hint(packet, "identity.date_of_birth").offer is None


def test_a_replaced_passport_offers_nothing_and_does_not_count_as_held(agency_a, membership_a):
    """Ruling 2026-10-14: a retired upload (master's Replace) is disowned
    (verification.disowned_refs), so its waiting values are offered nowhere and the
    box asks for the new upload."""
    from apps.concierge.models import DocumentVersion
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
              confirmed=False)
        DocumentVersion.objects.filter(id=passport.id).update(retired_at=timezone.now())
        application = _application(agency_a, membership_a,
                                   entries=[_entry("identity.date_of_birth", "#dob")])
        packet = mint_packet(application)
    hint = _hint(packet, "identity.date_of_birth")
    assert hint.offer is None and hint.upload_kind == "PASSPORT"


def _passport_in_state(agency, student, state):
    from apps.concierge.documents import register
    from apps.concierge.models import DocumentVersion

    document = register(agency.id, student.id, kind="PASSPORT")
    DocumentVersion.objects.filter(id=document.id).update(state=state)
    return document


@pytest.mark.parametrize(
    ("state", "prompts"),
    [("BLOCKED", True), ("QUARANTINED", True), ("REJECTED_TYPE", True),
     ("REJECTED_ACTIVE_CONTENT", True), ("AVAILABLE", False), ("CHECKING", False),
     ("REVIEW_REQUIRED", True)],
)
# "Held" is apps/documents/table.py's rule: AVAILABLE or CHECKING.
def test_only_a_usable_upload_counts_as_held(agency_a, membership_a, state, prompts):
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        _passport_in_state(agency_a, membership_a, state)
        application = _application(agency_a, membership_a,
                                   entries=[_entry("id_document.number", "#pno")])
        packet = mint_packet(application)
    assert _hint(packet, "id_document.number").upload_kind == ("PASSPORT" if prompts else "")


def test_a_retired_available_upload_does_not_count_as_held(agency_a, membership_a):
    from apps.concierge.models import DocumentVersion
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        passport = _passport_in_state(agency_a, membership_a, "AVAILABLE")
        DocumentVersion.objects.filter(id=passport.id).update(retired_at=timezone.now())
        application = _application(agency_a, membership_a,
                                   entries=[_entry("id_document.number", "#pno")])
        packet = mint_packet(application)
    assert _hint(packet, "id_document.number").upload_kind == "PASSPORT"


def test_the_owner_check_judges_a_file_once_across_twin_uploads(agency_a, membership_a):
    """A read clean, then a twin upload B of the same file read owner_unknown: B's
    verdict decides the file (verification.disowned_refs), so A's waiting value is
    not offered either. Grouped per document, A would be offered."""
    from apps.documents.models import DocumentReading
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        first = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, first, "IDENTITY", {"date_of_birth": "1998-03-14"}, confirmed=False)
        twin = _add_upload(agency_a, membership_a)
        for document, why in ((first, ""), (twin, "owner_unknown")):
            DocumentReading.objects.create(
                student=membership_a, document=document, kind="PASSPORT",
                reader_version="id-1", state="READ", file_sha256="same-file",
                values=[{"key": "identity.date_of_birth", "value": "1998-03-14",
                         "snippet": "", "proven": False, "why": why}])
        application = _application(agency_a, membership_a,
                                   entries=[_entry("identity.date_of_birth", "#dob")])
        packet = mint_packet(application)
    assert _hint(packet, "identity.date_of_birth").offer is None


@pytest.mark.parametrize(
    ("kind", "category", "payload", "field", "mark"),
    [("DIPLOMA", "EDUCATION", {"institution_original": "BSU"},
      "education.institution_original", "diploma"),
     ("LANGUAGE_CERTIFICATE", "LANGUAGE", {"test_name": "IELTS"},
      "language.test_name", "certificate")],
)
def test_diploma_and_certificate_values_are_marked(agency_a, membership_a, kind, category,
                                                   payload, field, mark):
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        document = _clean_upload(agency_a, membership_a, kind)
        _fact(membership_a, document, category, payload, confirmed=True)
        application = _application(agency_a, membership_a, entries=[_entry(field, "#x")])
        packet = mint_packet(application)
    assert {e.profile_field: e.source_kind for e in packet.entries} == {field: mark}


def test_a_retired_documents_confirmed_identity_row_keeps_its_mark(agency_a, membership_a):
    from apps.portals.profile import document_sources

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, passport, "IDENTITY", {"date_of_birth": "1998-03-14"},
              confirmed=True)
        values = {"identity.date_of_birth": "1998-03-14"}
        assert document_sources(membership_a, values) == {"identity.date_of_birth": "passport"}
        from apps.concierge.models import DocumentVersion
        DocumentVersion.objects.filter(id=passport.id).update(retired_at=timezone.now())
        # Final review 2 C1: it is still served (a clearer scan agrees with it), so the
        # mark follows the value; only the ID-document group and waiting values go.
        assert document_sources(membership_a, values) == {"identity.date_of_birth": "passport"}


def test_a_valid_passport_beside_an_expired_one_says_nothing_expired(agency_a, membership_a):
    from apps.portals.packets import mint_packet

    past = (date.today() - timedelta(days=30)).isoformat()
    future = (date.today() + timedelta(days=900)).isoformat()
    with tenant_scope(agency_a.id):
        old = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, old, "ID_DOCUMENT",
              {"document_type": "passport", "number": "OLD", "expiry_date": past},
              confirmed=True)
        new = _add_upload(agency_a, membership_a)
        _fact(membership_a, new, "ID_DOCUMENT",
              {"document_type": "passport", "number": "NEW", "expiry_date": future},
              confirmed=True)
        _fact(membership_a, new, "ID_DOCUMENT", {"issue_date": "2021-01-01"}, confirmed=False)
        application = _application(agency_a, membership_a, entries=[
            _entry("id_document.issue_date", "#issued")])
        packet = mint_packet(application)
    hint = _hint(packet, "id_document.issue_date")
    assert hint.expired_on == "" and hint.offer.value == "2021-01-01"


# Final review (plan 3): the reviewer's probes.


def test_no_upload_prompt_while_the_reader_is_off(agency_a, membership_a, settings,
                                                   monkeypatch):
    """I1: a prompt promises 'we'll fill this'; with no reader for the kind none will."""
    from apps.documents import document_reading
    from apps.portals.packets import mint_packet

    monkeypatch.undo()  # the real gate, not the file's all-kinds-read stand-in
    settings.FACT_READING_ENABLED = False
    assert document_reading.kind_enabled("PASSPORT") is False
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=[
            _entry("id_document.number", "#pno"), _entry("language.test_score", "#ielts")])
        packet = mint_packet(application)
    assert _hint(packet, "id_document.number").upload_kind == ""
    assert _hint(packet, "language.test_score").upload_kind == ""


def test_no_certificate_prompt_with_the_passport_reader_on_but_no_reader_pair(
        agency_a, membership_a, settings, monkeypatch):
    from apps.documents import document_reading, fact_readers
    from apps.portals.packets import mint_packet

    monkeypatch.undo()
    settings.FACT_READING_ENABLED = True
    settings.TRANSCRIPT_AZURE_ENABLED = True
    monkeypatch.setattr(fact_readers, "readers_configured", lambda: False)
    assert document_reading.kind_enabled("LANGUAGE_CERTIFICATE") is False
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=[
            _entry("language.test_score", "#ielts")])
        packet = mint_packet(application)
    assert _hint(packet, "language.test_score").upload_kind == ""


def test_a_renewed_passport_with_a_doubtful_expiry_is_not_called_expired(
        agency_a, membership_a):
    """M1: the old passport expired; a new one is owned and unretired, its expiry
    waiting and in the future. Not 'all expired': the expiry is offered."""
    from apps.portals.packets import mint_packet

    old = (date.today() - timedelta(days=30)).isoformat()
    new = (date.today() + timedelta(days=3000)).isoformat()
    with tenant_scope(agency_a.id):
        a = _clean_upload(agency_a, membership_a, "PASSPORT")
        _fact(membership_a, a, "ID_DOCUMENT",
              {"document_type": "passport", "number": "OLD1", "expiry_date": old},
              confirmed=True)
        b = _add_upload(agency_a, membership_a)
        _fact(membership_a, b, "ID_DOCUMENT", {"document_type": "passport"}, confirmed=True)
        _fact(membership_a, b, "ID_DOCUMENT", {"number": "NEW2"}, confirmed=True)
        _fact(membership_a, b, "ID_DOCUMENT", {"expiry_date": new}, confirmed=False)
        from apps.documents.models import DocumentReading
        DocumentReading.objects.create(
            student=membership_a, document=b, kind="PASSPORT", reader_version="id-1",
            state="READ", file_sha256="sha-b", values=[])
        application = _application(agency_a, membership_a, entries=[
            _entry("id_document.expiry_date", "#exp"), _entry("id_document.number", "#pno")])
        packet = mint_packet(application)
    exp = _hint(packet, "id_document.expiry_date")
    assert exp.offer is not None and exp.offer.value == new and exp.expired_on == ""


def test_disowned_retired_and_refused_uploads_are_excluded_from_held_uploads(
    agency_a, membership_a, paid_cycle_a
):
    from apps.concierge.models import DocumentVersion
    from apps.documents.models import DocumentReading, TranscriptUpload
    from apps.portals.packets import _held_uploads

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=[])
        retired_doc = _clean_upload(agency_a, membership_a, "PASSPORT")
        DocumentVersion.objects.filter(id=retired_doc.id).update(
            retired_at=timezone.now(), content_type="application/pdf"
        )
        mismatched_cert = _clean_upload(agency_a, membership_a, "LANGUAGE_CERTIFICATE")
        DocumentVersion.objects.filter(id=mismatched_cert.id).update(
            content_type="application/pdf"
        )
        DocumentReading.objects.create(
            student=membership_a,
            document=mismatched_cert,
            kind="LANGUAGE_CERTIFICATE",
            reader_version="text-1",
            state="READ",
            file_sha256="friend-ielts",
            values=[
                {
                    "key": "language.test_score",
                    "value": "7.5",
                    "snippet": "7.5",
                    "proven": False,
                    "why": "owner_mismatch",
                }
            ],
        )
        refused_tx = _clean_upload(agency_a, membership_a, "TRANSCRIPT")
        DocumentVersion.objects.filter(id=refused_tx.id).update(
            content_type="application/pdf"
        )
        TranscriptUpload.objects.create(
            student=membership_a,
            cycle=paid_cycle_a,
            document=refused_tx,
            role="ORIGINAL",
            state="REFUSED",
            refusal="owner_mismatch",
        )
        held = _held_uploads(application, degree_count=1)
    assert held == []

