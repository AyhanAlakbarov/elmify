"""Spec 2026-10-12 §7.1: a portal asking for a field queues the unread upload
that can supply it, and never raises into mint_packet."""

import pytest

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents.models import DocumentReading
from apps.portals import fact_reading
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _on(settings, monkeypatch):
    settings.FACT_READING_ENABLED = True
    settings.TRANSCRIPT_AZURE_ENABLED = True
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    fact_reading._sqs_client.cache_clear()


def _application(agency, student):
    return type("App", (), {"tenant_id": agency.id, "student_id": student.id,
                            "student": student, "id": None})()


def _available(agency, student, kind="PASSPORT"):
    document = register(agency.id, student.id, kind=kind)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        DocumentVersion.objects.filter(id=document.id).update(state="AVAILABLE")
    return document


def test_an_unread_passport_is_queued_once(agency_a, membership_a, monkeypatch):
    sent = []
    monkeypatch.setattr(fact_reading, "enqueue_document_work",
                        lambda message, **k: sent.append(message))
    document = _available(agency_a, membership_a)
    app = _application(agency_a, membership_a)
    fact_reading.request_fact_reading(app, ["identity.date_of_birth", "id_document.number"])
    fact_reading.request_fact_reading(app, ["identity.date_of_birth"])
    assert [m.document_id for m in sent] == [document.id]
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert DocumentReading.objects.get(document=document).state == "QUEUED"


def test_fields_no_document_supplies_queue_nothing(agency_a, membership_a, monkeypatch):
    sent = []
    monkeypatch.setattr(fact_reading, "enqueue_document_work",
                        lambda message, **k: sent.append(message))
    _available(agency_a, membership_a)
    fact_reading.request_fact_reading(_application(agency_a, membership_a), ["experience.title"])
    assert sent == []


def test_a_failure_never_reaches_the_packet(agency_a, membership_a, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(fact_reading, "enqueue_document_work", boom)
    _available(agency_a, membership_a)
    fact_reading.request_fact_reading(_application(agency_a, membership_a),
                                      ["identity.date_of_birth"])  # no raise


def test_a_language_field_queues_the_unread_certificate(agency_a, membership_a, monkeypatch,
                                                        settings):
    settings.FACT_READING_READERS = ["deepseek/a", "openai/b"]
    settings.OPENROUTER_API_KEY = "k"
    sent = []
    monkeypatch.setattr(fact_reading, "enqueue_document_work",
                        lambda message, **k: sent.append(message))
    document = _available(agency_a, membership_a, kind="LANGUAGE_CERTIFICATE")
    fact_reading.request_fact_reading(_application(agency_a, membership_a),
                                      ["language.test_score"])
    assert [m.document_id for m in sent] == [document.id]


def test_a_diploma_is_not_queued_while_the_reader_pair_is_unset(agency_a, membership_a,
                                                                monkeypatch, settings):
    settings.FACT_READING_READERS = []
    sent = []
    monkeypatch.setattr(fact_reading, "enqueue_document_work",
                        lambda message, **k: sent.append(message))
    _available(agency_a, membership_a, kind="DIPLOMA")
    fact_reading.request_fact_reading(_application(agency_a, membership_a),
                                      ["education.diploma_number"])
    assert sent == []


def test_the_hooks_queue_client_gives_up_in_seconds():
    """Plan 1 final review T8, before FACT_READING_ENABLED is on."""
    config = fact_reading._sqs_client().meta.config
    assert (config.connect_timeout, config.read_timeout) == (2, 3)
    assert config.retries["total_max_attempts"] == 1


def test_the_queue_call_uses_the_short_timeout_client(agency_a, membership_a, monkeypatch):
    seen = []
    monkeypatch.setattr(fact_reading, "enqueue_document_work",
                        lambda message, **k: seen.append(k["client"]))
    _available(agency_a, membership_a)
    fact_reading.request_fact_reading(_application(agency_a, membership_a),
                                      ["identity.date_of_birth"])
    assert seen == [fact_reading._sqs_client()]


def test_a_replaced_passport_is_not_queued_for_reading(agency_a, membership_a, monkeypatch):
    from django.utils import timezone

    sent = []
    monkeypatch.setattr(fact_reading, "enqueue_document_work",
                        lambda message, **k: sent.append(message))
    document = _available(agency_a, membership_a)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentVersion.objects.filter(id=document.id).update(retired_at=timezone.now())
    fact_reading.request_fact_reading(_application(agency_a, membership_a),
                                      ["identity.date_of_birth"])
    assert sent == []
