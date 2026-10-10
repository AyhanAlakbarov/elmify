"""Pins that Urllib3Transport does not coerce a JSON array body to {}.

GitHub's /contributors, /commits and /contents endpoints all return JSON
arrays. The transport used to end `body if isinstance(body, dict) else {}`,
which silently discarded every one of those bodies on real traffic -- no
test caught it because FakeTransport in test_repo.py returns lists directly
and never goes through this class.
"""

from __future__ import annotations

import urllib3

from apps.documents.evidence.transport import Urllib3Transport


class _FakeResponse:
    def __init__(self, status: int, data: bytes) -> None:
        self.status = status
        self.data = data


def test_a_json_array_body_survives_the_transport_intact(monkeypatch):
    transport = Urllib3Transport()
    monkeypatch.setattr(
        transport._pool,
        "request",
        lambda method, url, headers=None: _FakeResponse(200, b'[{"login": "0rkhann"}]'),
    )
    status, body = transport.get_json("https://api.github.com/repos/x/y/contributors")
    assert status == 200
    assert body == [{"login": "0rkhann"}]


def test_a_non_json_body_still_comes_back_as_an_empty_dict(monkeypatch):
    transport = Urllib3Transport()
    monkeypatch.setattr(
        transport._pool,
        "request",
        lambda method, url, headers=None: _FakeResponse(200, b"not json"),
    )
    status, body = transport.get_json("https://api.github.com/x")
    assert status == 200
    assert body == {}


def test_a_urllib3_connection_failure_comes_back_as_a_non_200_not_an_exception(
    monkeypatch,
):
    """A Crossref timeout raises urllib3.exceptions.MaxRetryError (an
    HTTPError subclass) out of PoolManager.request. Every caller treats
    (0, {}) as a non-200 -- ingest_evidence must return FAILED or NEEDS_INPUT
    for a dead network, not let urllib3's exception escape the three-outcome
    contract."""

    def _explode(method, url, headers=None):
        raise urllib3.exceptions.MaxRetryError(pool=None, url=url)

    transport = Urllib3Transport()
    monkeypatch.setattr(transport._pool, "request", _explode)
    status, body = transport.get_json("https://api.crossref.org/works/10.1/x")
    assert (status, body) == (0, {})
