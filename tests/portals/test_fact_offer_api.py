# tests/portals/test_fact_offer_api.py
"""Spec 2026-10-12 §7.3: the student's one tap confirms one offered value."""

import pytest

from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from tests.portals.test_ext_api import _pair
from tests.portals.test_kit import _application
from tests.portals.test_packet import _clean_upload

pytestmark = pytest.mark.django_db

ENTRY = {"profile_field": "identity.date_of_birth", "sure": True,
         "action": {"selector": "#dob", "method": "fill", "arguments": ["%value%"]}}

@pytest.fixture(autouse=True)
def _reading_on(monkeypatch):
    """An upload prompt is shown only for a kind some reader reads (final review I1);
    these tests are about the prompt, not the gate, so every kind reads. Only the
    packet's view is patched: the upload hook keeps the real, default-off switch."""
    from types import SimpleNamespace

    from apps.portals import packets

    monkeypatch.setattr(packets, "document_reading", SimpleNamespace(kind_enabled=lambda k: True))


def _offered(agency, student):
    from apps.portals.packets import mint_packet

    with tenant_scope(agency.id):
        passport = _clean_upload(agency, student, "PASSPORT")
        fact = VerifiedFact.objects.create(
            student=student, category="IDENTITY", payload={"date_of_birth": "1998-03-14"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{passport.id}",
            created_by=student,
        )
        application = _application(agency, student, entries=[ENTRY])
        mint_packet(application)
    return application, fact


def _tap(client, domain, token, application, fact_id):
    return client.post(
        f"/ext/applications/{application.id}/facts/{fact_id}/confirm",
        data="{}", content_type="application/json",
        HTTP_HOST=domain.host, HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_a_tap_confirms_the_offered_value_and_returns_it(client, agency_a, domain_a,
                                                         membership_a):
    from apps.funding.models import AuditEvent

    application, fact = _offered(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    response = _tap(client, domain_a, token, application, fact.id)
    assert response.status_code == 201
    assert response.json() == {"profile_field": "identity.date_of_birth", "value": "1998-03-14"}
    with tenant_scope(agency_a.id):
        used = VerifiedFact.objects.get(supersedes=fact)
        assert used.confirmed_by == membership_a and used.payload == fact.payload
        assert (used.source_ref, used.source_tier) == (fact.source_ref, fact.source_tier)
        assert AuditEvent.objects.filter(object_id=used.id, event="fact.confirmed").exists()


def test_the_tapped_value_is_a_new_row_and_the_one_served_next(client, agency_a, domain_a,
                                                               membership_a):
    """Carried from plan 1: a row confirmed in place keeps its old created_at and can
    lose to a row written after it; the tap's row is the newest of the student's."""
    from apps.portals.profile import verified_values

    application, fact = _offered(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _tap(client, domain_a, token, application, fact.id).status_code == 201
    with tenant_scope(agency_a.id):
        newest = VerifiedFact.objects.filter(student=membership_a).latest("created_at")
        assert newest.supersedes_id == fact.id and newest.confirmed_at is not None
        assert verified_values(membership_a)["identity.date_of_birth"] == "1998-03-14"


@pytest.mark.parametrize("why", ["owner_mismatch", "owner_unknown"])
def test_a_passport_disowned_after_the_packet_is_refused(client, agency_a, domain_a,
                                                         membership_a, why):
    """The packet offered it; a later read found the passport is someone else's (plan 1:
    a disowned document serves nothing), or could not tie it to the student (plan 2:
    owner_unknown is offered on no surface). The route re-asks document_offers, so
    the tap confirms nothing."""
    from apps.documents.models import DocumentReading

    application, fact = _offered(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        DocumentReading.objects.create(
            student=membership_a, document_id=fact.source_ref.removeprefix("document:"),
            kind="PASSPORT", reader_version="id-1", state="READ", file_sha256="mum",
            values=[{"key": "identity.date_of_birth", "value": "1998-03-14", "snippet": "",
                     "proven": False, "why": why}])
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _tap(client, domain_a, token, application, fact.id).status_code == 404
    with tenant_scope(agency_a.id):
        assert not VerifiedFact.objects.filter(supersedes=fact).exists()


def test_a_fact_the_latest_packet_did_not_offer_is_refused(client, agency_a, domain_a,
                                                           membership_a):
    application, _fact = _offered(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        other = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"sex": "F"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref="document:x",
            created_by=membership_a,
        )
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _tap(client, domain_a, token, application, other.id).status_code == 404


def test_someone_elses_fact_is_refused_even_if_the_step_names_it(
    client, agency_a, domain_a, membership_a, django_user_model
):
    """The step is our record: a step naming another student's fact still confirms
    nothing (refused at the offers check; the student filter itself is pinned by
    test_the_writer_itself_refuses_another_students_fact)."""
    from apps.portals.models import ApplicationStep
    from tests.portals.test_answers import _student

    application, _fact = _offered(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        stranger = _student(agency_a, django_user_model, "stranger")
        theirs = VerifiedFact.objects.create(
            student=stranger, category="IDENTITY", payload={"date_of_birth": "2001-01-01"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref="document:x", created_by=stranger,
        )
        step = ApplicationStep.objects.get(application=application, kind="PACKET")
        step.detail["hints"][0]["offer_fact_id"] = str(theirs.id)
        step.save(update_fields=["detail"])
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _tap(client, domain_a, token, application, theirs.id).status_code == 404
    with tenant_scope(agency_a.id):
        theirs.refresh_from_db()
        assert theirs.confirmed_at is None


def test_a_second_tap_types_nothing_new(client, agency_a, domain_a, membership_a):
    application, fact = _offered(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _tap(client, domain_a, token, application, fact.id).status_code == 201
    assert _tap(client, domain_a, token, application, fact.id).status_code == 404


def test_a_locked_account_is_refused(client, agency_a, domain_a, membership_a):
    from apps.audit.models import DeletionRequest

    application, fact = _offered(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="APPROVED", reason="PRIVACY"
        )
    response = _tap(client, domain_a, token, application, fact.id)
    assert response.status_code == 403 and response.json()["error"] == "account_locked"


def test_taps_are_rate_limited(client, agency_a, domain_a, membership_a, monkeypatch):
    from apps.portals import ext_api

    monkeypatch.setattr(ext_api, "_FACT_CONFIRM_RATE_LIMIT", 1)
    application, _fact = _offered(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    _tap(client, domain_a, token, application, "00000000-0000-4000-8000-000000000000")
    response = _tap(client, domain_a, token, application, "00000000-0000-4000-8000-000000000000")
    assert response.status_code == 429


def test_no_tap_writes_a_value_the_ledger_cannot_hold(agency_a, membership_a):
    from apps.documents.confirmation import FactNotFound
    from apps.documents.fact_writer import use_document_value

    with tenant_scope(agency_a.id):
        fact = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"date_of_birth": "14 Marh 98"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref="document:x",
            created_by=membership_a,
        )
        with pytest.raises(FactNotFound):
            use_document_value(student=membership_a, fact_id=fact.id)


def test_the_writer_itself_refuses_another_students_fact(agency_a, membership_a,
                                                         django_user_model):
    from apps.documents.confirmation import FactNotFound
    from apps.documents.fact_writer import use_document_value
    from tests.portals.test_answers import _student

    with tenant_scope(agency_a.id):
        stranger = _student(agency_a, django_user_model, "stranger2")
        theirs = VerifiedFact.objects.create(
            student=stranger, category="IDENTITY", payload={"date_of_birth": "2001-01-01"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref="document:x", created_by=stranger,
        )
        with pytest.raises(FactNotFound):
            use_document_value(student=membership_a, fact_id=theirs.id)
        theirs.refresh_from_db()
        assert theirs.confirmed_at is None and not VerifiedFact.objects.filter(
            supersedes=theirs).exists()


def test_a_stale_tap_does_not_beat_the_students_own_entry(client, agency_a, domain_a,
                                                          membership_a):
    """Final review M2 (spec D5: the student's own entry always wins): mint offered
    BAKU; the student then entered their own; the open panel's tap is refused."""
    from django.utils import timezone

    from apps.portals.packets import mint_packet
    from apps.portals.profile import verified_values
    from tests.portals.test_packet_offers import _entry, _hint

    with tenant_scope(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        fact = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"place_of_birth": "BAKU"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{passport.id}",
            created_by=membership_a)
        from tests.portals.test_kit import _application
        application = _application(agency_a, membership_a,
                                   entries=[_entry("identity.place_of_birth", "#pob")])
        assert _hint(mint_packet(application), "identity.place_of_birth").offer is not None
        VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"place_of_birth": "Sumgait"},
            source_tier="STUDENT_STATEMENT", source_ref="gap:own",
            confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    response = _tap(client, domain_a, token, application, fact.id)
    assert response.status_code == 404
    with tenant_scope(agency_a.id):
        assert verified_values(membership_a)["identity.place_of_birth"] == "Sumgait"
