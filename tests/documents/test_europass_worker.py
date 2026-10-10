import io
import logging
from uuid import uuid4

import pytest

from apps.documents import europass_render, europass_worker
from apps.documents.europass import EuropassThrottled, EuropassUnavailable
from apps.documents.europass_queue import EuropassRenderMessage
from apps.documents.europass_render import CircuitOpen, RenderOutcome
from apps.documents.europass_worker import process_europass_message
from apps.documents.models import DocumentDraft, EuropassCircuit
from apps.documents.render import RenderRateLimited
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _approved_draft(agency, django_user_model, name):
    from apps.documents.drafts import create_draft

    from .test_render import _content

    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
    DocumentDraft.objects.filter(id=draft.id).update(
        status=DocumentDraft.Status.APPROVED, render_variant="EUROPASS_API"
    )
    draft.refresh_from_db()
    return draft


def test_europass_call_made_actually_reaches_a_handler():
    """Ruling F-L: with no LOGGING config, DEBUG=False (what these test
    settings already run with, matching production) leaves apps.* loggers
    unconfigured -- they propagate to a handler-less root and
    logging.lastResort drops anything below WARNING, so EuropassCallsTotal
    (infra/template.yaml) reads zero forever. This redirects the REAL
    handler that config.settings.base's LOGGING attaches to the "apps"
    logger (not a synthetic one added just for this test, which would pass
    regardless of settings) and confirms the exact logger
    process_europass_message uses (apps/documents/europass_worker.py:68)
    both passes its level filter and actually reaches it."""
    apps_logger = logging.getLogger("apps")
    assert apps_logger.handlers, "the 'apps' logger has no handler -- EuropassCallsTotal reads zero"
    handler = apps_logger.handlers[0]
    buffer = io.StringIO()
    original_stream = handler.stream
    handler.stream = buffer
    try:
        logging.getLogger("apps.documents.europass_worker").info(
            "EuropassCallMade draft=%s", "log-emission-smoke-test"
        )
    finally:
        handler.stream = original_stream
    assert "EuropassCallMade draft=log-emission-smoke-test" in buffer.getvalue()


def test_a_remote_call_is_followed_by_the_delay(agency_a, django_user_model, monkeypatch):
    """THE rate guarantee. If the delay stops being applied, the rate limiter
    silently ceases to exist -- there is no counter anywhere to catch it."""
    slept = []
    monkeypatch.setattr(
        europass_worker,
        "render_and_store",
        lambda **kw: RenderOutcome(object_key="k", called_remote=True),
    )
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "rate-1")
        message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
        process_europass_message(message, sleep=slept.append)
    assert slept == [europass_worker._INTER_CALL_DELAY_SECONDS]


def test_a_cache_hit_does_not_sleep(agency_a, django_user_model, monkeypatch):
    """The delay paces calls to europa.eu, not work. Sleeping on a cache hit
    would throttle the queue for no reason."""
    slept = []
    monkeypatch.setattr(
        europass_worker,
        "render_and_store",
        lambda **kw: RenderOutcome(object_key="k", called_remote=False),
    )
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "rate-2")
        message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
        process_europass_message(message, sleep=slept.append)
    assert slept == []


def test_the_configured_rate_is_at_most_thirty_per_minute():
    """Pins the agreed ceiling. Lowering the delay raises the rate at a public
    EU service, so it should require changing this test on purpose."""
    assert europass_worker._INTER_CALL_DELAY_SECONDS >= 2
    assert 60 / europass_worker._INTER_CALL_DELAY_SECONDS <= 30


def test_an_open_circuit_propagates_so_sqs_redelivers(
    agency_a, django_user_model, monkeypatch
):
    def _open(**kwargs):
        raise CircuitOpen("paused")

    monkeypatch.setattr(europass_worker, "render_and_store", _open)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "rate-3")
        message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
        with pytest.raises(CircuitOpen):
            process_europass_message(message, sleep=lambda _s: None)


def test_an_open_circuit_does_not_sleep(agency_a, django_user_model, monkeypatch):
    """Ruling F-H: CircuitOpen means no call reached europa.eu -- nothing to
    pace."""
    slept = []

    def _open(**kwargs):
        raise CircuitOpen("paused")

    monkeypatch.setattr(europass_worker, "render_and_store", _open)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "rate-5")
        message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
        with pytest.raises(CircuitOpen):
            process_europass_message(message, sleep=slept.append)
    assert slept == []


def test_a_local_rate_limit_rejection_does_not_sleep(agency_a, django_user_model, monkeypatch):
    """Ruling F-H: RenderRateLimited means WE stopped ourselves before ever
    reaching europa.eu -- also nothing to pace."""
    slept = []

    def _limited(**kwargs):
        raise RenderRateLimited("too soon")

    monkeypatch.setattr(europass_worker, "render_and_store", _limited)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "rate-6")
        message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
        with pytest.raises(RenderRateLimited):
            process_europass_message(message, sleep=slept.append)
    assert slept == []


def test_a_failed_remote_call_still_sleeps(agency_a, django_user_model, monkeypatch):
    """Ruling F-H, the new guarantee: pacing defaults to sleeping on any
    attempt. A europa.eu call that ends in an exception still cost a
    request, so skipping the delay here would let a failure storm blow
    straight through the 30/minute ceiling."""
    slept = []

    def _boom(**kw):
        raise EuropassUnavailable("europa.eu 500")

    monkeypatch.setattr(europass_worker, "render_and_store", _boom)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "rate-7")
        message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
        with pytest.raises(EuropassUnavailable):
            process_europass_message(message, sleep=slept.append)
    assert slept == [europass_worker._INTER_CALL_DELAY_SECONDS]


def test_a_missing_draft_raises_rather_than_silently_succeeding(agency_a):
    message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=uuid4())
    with pytest.raises(DocumentDraft.DoesNotExist):
        process_europass_message(message, sleep=lambda _s: None)


def test_a_throttle_during_a_real_call_leaves_the_circuit_open(
    agency_a, django_user_model, monkeypatch
):
    """Ruling F-G regression (Finding 1). process_europass_message wraps a
    short transaction around tenant-scoped DB work, but render_and_store's
    breaker writes must never live inside that transaction -- otherwise the
    exception that reports the throttle also rolls the breaker write back,
    and the breaker goes inert. Drives the REAL render_and_store, not a
    monkeypatched stand-in: only render_draft (the actual network call) is
    replaced."""

    def _throttled(*, draft):
        raise EuropassThrottled("slow down", retry_after_seconds=180)

    monkeypatch.setattr(europass_render, "render_draft", _throttled)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "circuit-1")
        message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
        with pytest.raises(EuropassThrottled):
            process_europass_message(message, sleep=lambda _s: None)
    assert EuropassCircuit.load().is_open() is True


def test_consecutive_failures_during_real_calls_survive_the_transaction(
    agency_a, django_user_model, monkeypatch
):
    """Same regression as above, for the plain-failure counter: three real
    EuropassUnavailable failures driven through process_europass_message
    must trip the breaker, not silently reset because each failure's write
    lived inside a transaction that later rolled back."""

    def _unavailable(*, draft):
        raise EuropassUnavailable("europa.eu is down")

    monkeypatch.setattr(europass_render, "render_draft", _unavailable)
    with tenant_scope(agency_a.id):
        for i in range(3):
            draft = _approved_draft(agency_a, django_user_model, f"circuit-2-{i}")
            message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
            with pytest.raises(EuropassUnavailable):
                process_europass_message(message, sleep=lambda _s: None)
    circuit = EuropassCircuit.load()
    assert circuit.is_open() is True
    assert circuit.reason == "consecutive failures"
