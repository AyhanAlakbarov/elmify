"""The DEBUG-only spool that stands in for SQS on a developer machine."""

from unittest.mock import MagicMock

from pydantic import BaseModel

from apps.queue import drain_local, enqueue, is_local_queue


class _Msg(BaseModel):
    value: int


def test_only_a_debug_machine_with_a_placeholder_queue_spools(settings, tmp_path) -> None:
    settings.BASE_DIR = tmp_path
    settings.DEBUG = False
    assert not is_local_queue("test-document-queue")
    settings.DEBUG = True
    assert is_local_queue("test-document-queue")
    assert not is_local_queue("https://sqs.eu-central-1.amazonaws.com/1/real")


def test_spooled_messages_drain_once_in_order(settings, tmp_path) -> None:
    settings.BASE_DIR = tmp_path
    settings.DEBUG = True
    enqueue(_Msg(value=1), queue_url="test-q")
    enqueue(_Msg(value=2), queue_url="test-q")
    assert [_Msg.model_validate_json(b).value for b in drain_local("test-q")] == [1, 2]
    assert drain_local("test-q") == []


def test_an_explicit_client_is_always_used(settings, tmp_path) -> None:
    settings.BASE_DIR = tmp_path
    settings.DEBUG = True
    client = MagicMock()
    enqueue(_Msg(value=1), client=client, queue_url="test-q")
    client.send_message.assert_called_once()
    assert drain_local("test-q") == []
