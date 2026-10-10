from datetime import timedelta

import pytest
from django.utils import timezone

from apps.documents.europass import (
    EuropassProvenanceMissing,
    EuropassThrottled,
    EuropassUnavailable,
)
from apps.documents.europass_render import CircuitOpen
from apps.documents.management.commands import run_europass_worker
from apps.documents.models import EuropassCircuit
from apps.documents.render import RenderRateLimited

pytestmark = pytest.mark.django_db


def test_an_open_circuit_is_waited_out_not_crashed(monkeypatch):
    """Ruling F-I: CircuitOpen is a routine, designed pause. The command must
    wait it out rather than let it kill the process -- a crash restarts the
    ECS task, and each restart re-polls the same message, burning its
    limited SQS redelivery budget faster than the pause elapses."""
    monkeypatch.setattr(run_europass_worker.boto3, "client", lambda *a, **kw: object())

    circuit = EuropassCircuit.load()
    circuit.paused_until = timezone.now() + timedelta(seconds=5)
    circuit.save(update_fields=["paused_until"])

    slept = []

    def _consume_once(**kwargs):
        raise CircuitOpen("paused")

    monkeypatch.setattr(run_europass_worker, "consume_once", _consume_once)
    monkeypatch.setattr(run_europass_worker.time, "sleep", slept.append)

    run_europass_worker.Command().handle(once=True)

    assert len(slept) == 1
    assert 0 < slept[0] <= 5


@pytest.mark.parametrize(
    "make_error",
    [
        lambda: EuropassThrottled("slow down", retry_after_seconds=60),
        lambda: EuropassUnavailable("europa.eu returned HTTP 500"),
        lambda: EuropassProvenanceMissing("no attachment.xml"),
        lambda: RenderRateLimited("Europass render rate limit reached; retry later"),
    ],
    ids=["throttled", "unavailable", "provenance-missing", "rate-limited"],
)
def test_a_designed_failure_is_deferred_not_crashed(monkeypatch, make_error):
    """Every member of the EuropassUnavailable family is a documented,
    expected failure mode -- not a crash. The identical reasoning as
    CircuitOpen above applies: an uncaught exception here kills the ECS
    task, each restart re-polls and burns the maxReceiveCount: 3 redelivery
    budget faster than the condition clears, and the traceback would print
    to the log group the canary alarm also reads (EuropassCanaryFailureFilter),
    paging someone for an ordinary europa.eu outage instead of leaving the
    message for SQS to redeliver."""
    monkeypatch.setattr(run_europass_worker.boto3, "client", lambda *a, **kw: object())

    def _consume_once(**kwargs):
        raise make_error()

    monkeypatch.setattr(run_europass_worker, "consume_once", _consume_once)

    # Must not raise -- the process stays alive to poll again. consume_once
    # never reaches its delete_message call before raising, so the message
    # (never fetched here at all, since consume_once itself is mocked) is
    # left for SQS to redeliver -- that contract is consume_once's own, and
    # is pinned separately in tests/documents/test_europass_queue.py.
    run_europass_worker.Command().handle(once=True)


def test_an_unexpected_error_is_not_swallowed(monkeypatch):
    """A genuinely unexpected exception must still propagate and kill the
    task -- only CircuitOpen is a routine pause. A blanket except would hide
    real failures instead of surfacing them as a container restart."""
    monkeypatch.setattr(run_europass_worker.boto3, "client", lambda *a, **kw: object())

    def _consume_once(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(run_europass_worker, "consume_once", _consume_once)

    with pytest.raises(RuntimeError):
        run_europass_worker.Command().handle(once=True)
