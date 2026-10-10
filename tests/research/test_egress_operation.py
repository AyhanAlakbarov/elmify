"""start_json_operation: the one egress call that answers 202 and a polling URL."""

import pytest

from apps.research import egress
from apps.research.egress import SourceBlocked, start_json_operation


class _Resp:
    def __init__(self, status, headers):
        self.status, self.headers = status, headers

    def read(self, amount, decode_content=True):
        return b""

    def release_conn(self):
        pass


def _transport(status, headers, seen):
    def send(target, path, *, method, body, extra_headers, **kwargs):
        seen.append((target.host, path, method, body, extra_headers))
        return _Resp(status, headers)

    return send


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(
        egress.socket, "getaddrinfo", lambda host, port: [(0, 0, 0, "", ("20.50.1.1", port))]
    )


def test_returns_the_operation_location_on_202():
    seen = []
    location = start_json_operation(
        "https://tehsil.cognitiveservices.azure.com/x:analyze?api-version=2024-11-30",
        payload={"base64Source": "QUJD"},
        headers={"Ocp-Apim-Subscription-Key": "k"},
        transport=_transport(
            202, {"Operation-Location": "https://tehsil.cognitiveservices.azure.com/op/1"}, seen
        ),
    )
    assert location == "https://tehsil.cognitiveservices.azure.com/op/1"
    assert seen[0][2] == "POST" and seen[0][4]["Content-Type"] == "application/json"


def test_any_other_status_is_blocked():
    with pytest.raises(SourceBlocked, match="HTTP 400"):
        start_json_operation(
            "https://tehsil.cognitiveservices.azure.com/x", payload={}, headers={},
            transport=_transport(400, {}, []),
        )


def test_a_location_on_another_host_is_refused():
    with pytest.raises(SourceBlocked, match="another host"):
        start_json_operation(
            "https://tehsil.cognitiveservices.azure.com/x", payload={}, headers={},
            transport=_transport(202, {"Operation-Location": "https://evil.example/op"}, []),
        )


def test_a_missing_location_is_refused():
    with pytest.raises(SourceBlocked, match="no Operation-Location"):
        start_json_operation(
            "https://tehsil.cognitiveservices.azure.com/x", payload={}, headers={},
            transport=_transport(202, {}, []),
        )


def _locate(location):
    return start_json_operation(
        "https://tehsil.cognitiveservices.azure.com/x", payload={}, headers={},
        transport=_transport(202, {"Operation-Location": location}, []),
    )


def test_a_location_on_another_port_is_refused():
    with pytest.raises(SourceBlocked, match="another host"):
        _locate("https://tehsil.cognitiveservices.azure.com:8443/op")


def test_a_location_resolving_to_a_private_address_is_blocked(monkeypatch):
    def resolve(host, port):
        ip = "10.0.0.1" if host == "internal.example" else "20.50.1.1"
        return [(0, 0, 0, "", (ip, port))]

    monkeypatch.setattr(egress.socket, "getaddrinfo", resolve)
    with pytest.raises(SourceBlocked, match="not a public https URL"):
        _locate("https://internal.example/op")


def test_an_http_location_is_blocked():
    with pytest.raises(SourceBlocked, match="not a public https URL"):
        _locate("http://tehsil.cognitiveservices.azure.com/op")
