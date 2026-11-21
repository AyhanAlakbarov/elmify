"""Urllib3Transport: three values on every call, headers kept on a refusal.

GitHub's rate-limit handling (github.py) reads x-ratelimit-remaining and
retry-after off the response, and a 403 is only a rate limit when those say
so -- so a non-200 must still carry its headers.
"""

from __future__ import annotations

import json

import urllib3

from apps.documents.evidence.transport import Urllib3Transport


class _FakeResponse:
    def __init__(self, status: int, data: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.data = data
        self.headers = headers or {}
        self._left = data
        self.released = False

    def read(self, amt: int | None = None) -> bytes:
        chunk = self._left if amt is None else self._left[:amt]
        self._left = self._left[len(chunk):]
        return chunk

    def release_conn(self) -> None:
        self.released = True


def _answering(monkeypatch, transport, response):
    seen = []

    def _request(method, url, **kwargs):
        seen.append((method, url, kwargs))
        return response

    monkeypatch.setattr(transport._pool, "request", _request)
    return seen


def test_a_json_array_body_survives_with_lower_cased_headers(monkeypatch):
    transport = Urllib3Transport()
    _answering(
        monkeypatch,
        transport,
        _FakeResponse(200, b'[{"login": "0rkhann"}]', {"X-RateLimit-Remaining": "12"}),
    )
    status, body, headers = transport.get_json("https://api.github.com/repos/x/y/commits")
    assert (status, body) == (200, [{"login": "0rkhann"}])
    assert headers["x-ratelimit-remaining"] == "12"


def test_a_non_json_body_comes_back_as_an_empty_dict(monkeypatch):
    transport = Urllib3Transport()
    _answering(monkeypatch, transport, _FakeResponse(200, b"not json"))
    assert transport.get_json("https://api.github.com/x")[:2] == (200, {})


def test_a_refusal_keeps_its_headers(monkeypatch):
    transport = Urllib3Transport()
    _answering(
        monkeypatch, transport, _FakeResponse(403, b"{}", {"X-RateLimit-Remaining": "0"})
    )
    status, body, headers = transport.get_json("https://api.github.com/x")
    assert (status, body, headers["x-ratelimit-remaining"]) == (403, {}, "0")


def test_a_connection_failure_comes_back_as_a_non_200_not_an_exception(monkeypatch):
    def _explode(method, url, **kwargs):
        raise urllib3.exceptions.MaxRetryError(pool=None, url=url)

    transport = Urllib3Transport()
    monkeypatch.setattr(transport._pool, "request", _explode)
    assert transport.get_json("https://api.crossref.org/works/10.1/x") == (0, {}, {})
    assert transport.post_json("https://api.github.com/graphql", {}) == (0, {}, {})
    assert transport.get_bytes("https://api.github.com/x", max_bytes=10) == (0, b"", {})


def test_post_json_sends_a_json_body(monkeypatch):
    transport = Urllib3Transport()
    seen = _answering(monkeypatch, transport, _FakeResponse(200, b'{"data": {}}'))
    status, body, _ = transport.post_json(
        "https://api.github.com/graphql", {"query": "q"}, headers={"Authorization": "Bearer t"}
    )
    method, _url, kwargs = seen[0]
    assert (status, body, method) == (200, {"data": {}}, "POST")
    assert json.loads(kwargs["body"]) == {"query": "q"}
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["Authorization"] == "Bearer t"


def test_get_bytes_streams_under_the_cap_and_refuses_over_it(monkeypatch):
    transport = Urllib3Transport()
    small = _FakeResponse(200, b"x" * 10)
    _answering(monkeypatch, transport, small)
    assert transport.get_bytes("https://api.github.com/f", max_bytes=10)[:2] == (200, b"x" * 10)
    assert small.released

    _answering(monkeypatch, transport, _FakeResponse(200, b"x" * 11))
    # Over the cap is absent, never a prefix: a cut notebook is a different notebook.
    assert transport.get_bytes("https://api.github.com/f", max_bytes=10)[:2] == (200, b"")

    _answering(monkeypatch, transport, _FakeResponse(404, b"nope"))
    assert transport.get_bytes("https://api.github.com/f", max_bytes=10)[:2] == (404, b"")
