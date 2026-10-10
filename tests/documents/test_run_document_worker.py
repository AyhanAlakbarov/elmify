import pytest

from apps.documents.generation import GenerationRateLimited
from apps.documents.ingestion import IngestionRateLimited
from apps.documents.management.commands import run_document_worker

pytestmark = pytest.mark.django_db


def test_both_queues_are_drained_in_one_pass(monkeypatch, settings):
    """One task, two queues. A worker that polls only one leaves either every
    upload unscanned-for or every generation unrun, with no signal but a
    growing backlog."""
    settings.DOCUMENT_SCAN_QUEUE_URL = "scan-q"
    settings.DOCUMENT_QUEUE_URL = "work-q"
    monkeypatch.setattr(run_document_worker.boto3, "client", lambda *a, **kw: object())
    polled = []

    def _consume_once(*, queue_url, **kwargs):
        polled.append(queue_url)
        return 0

    monkeypatch.setattr(run_document_worker, "consume_once", _consume_once)

    run_document_worker.Command().handle(once=True)

    assert polled == ["scan-q", "work-q"]


@pytest.mark.parametrize(
    "error",
    [GenerationRateLimited("too many"), IngestionRateLimited("too many")],
    ids=["generation", "ingestion"],
)
def test_a_rate_limited_message_is_deferred_not_crashed(monkeypatch, error):
    """Our own limiter firing is a designed outcome, not a crash. An uncaught
    exception kills the ECS task; each restart re-polls the same message and
    burns its limited redelivery budget faster than the window rolls over,
    driving a student's CV to the DLQ for no reason. The message is never
    deleted, so SQS redelivers it after the visibility timeout."""
    monkeypatch.setattr(run_document_worker.boto3, "client", lambda *a, **kw: object())

    def _consume_once(**kwargs):
        raise error

    monkeypatch.setattr(run_document_worker, "consume_once", _consume_once)

    run_document_worker.Command().handle(once=True)


def test_an_unexpected_error_is_not_swallowed(monkeypatch):
    """Only the designed failures are caught. A blanket except would hide a
    genuine bug behind an endlessly redelivering message."""
    monkeypatch.setattr(run_document_worker.boto3, "client", lambda *a, **kw: object())

    def _consume_once(**kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(run_document_worker, "consume_once", _consume_once)

    with pytest.raises(RuntimeError):
        run_document_worker.Command().handle(once=True)


def test_a_scan_queue_deferral_does_not_starve_the_work_queue(monkeypatch, settings):
    """A rate-limited message on one queue must not suppress the other queue's
    poll in the same pass. The two queues share a lifecycle; starving one is
    leaving a student's upload unprocessed."""
    settings.DOCUMENT_SCAN_QUEUE_URL = "scan-q"
    settings.DOCUMENT_QUEUE_URL = "work-q"
    monkeypatch.setattr(run_document_worker.boto3, "client", lambda *a, **kw: object())
    polled = []

    def _consume_once(*, queue_url, **kwargs):
        if queue_url == "scan-q":
            polled.append(queue_url)
            raise GenerationRateLimited("too many")
        else:
            polled.append(queue_url)
            return 0

    monkeypatch.setattr(run_document_worker, "consume_once", _consume_once)

    run_document_worker.Command().handle(once=True)

    assert polled == ["scan-q", "work-q"]
