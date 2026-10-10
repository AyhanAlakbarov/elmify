import socket

import pytest
import urllib3
import urllib3.exceptions

from apps.research.egress import (
    MAX_RESPONSE_BYTES,
    USER_AGENT,
    FetchResult,
    LocalEgressProxy,
    OffSiteRedirect,
    ResponseTooLarge,
    SourceBlocked,
    UnsafeTarget,
    _request,
    fetch_data_file,
    fetch_json_api,
    looks_unrendered,
    require_same_origin,
    validate_public_url,
)
from apps.research.fetch.types import usable


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes = b"official",
    ) -> None:
        self.status = status
        self.headers = headers or {"Content-Type": "text/html"}
        self._body = body

    def read(self, amount: int, decode_content: bool = True) -> bytes:
        chunk, self._body = self._body[:amount], self._body[amount:]
        return chunk

    def release_conn(self) -> None:
        pass


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://user:password@example.org/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
    ],
)
def test_private_or_credentialed_targets_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeTarget):
        validate_public_url(url)


def test_mixed_public_and_private_dns_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(UnsafeTarget):
        validate_public_url("https://official.test/")


def test_redirect_target_is_revalidated(monkeypatch) -> None:
    def resolve(host: str, port: int, *_args, **_kwargs):
        address = "93.184.216.34" if host == "official.test" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    with pytest.raises(UnsafeTarget):
        fetch_data_file(
            "https://official.test/",
            transport=lambda _target, _path: FakeResponse(
                302, {"Location": "https://internal.test/"}
            ),
        )


def test_https_only_fetch_rejects_http_redirect_before_request(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, port, *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    requested_schemes: list[str] = []

    def transport(target, _path):
        requested_schemes.append(target.scheme)
        return FakeResponse(302, {"Location": "http://official.test/final"})

    with pytest.raises(UnsafeTarget):
        fetch_data_file(
            "https://official.test/",
            transport=transport,
            require_https=True,
        )

    assert requested_schemes == ["https"]


def test_response_body_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, port, *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    with pytest.raises(ResponseTooLarge):
        fetch_data_file(
            "https://official.test/",
            transport=lambda _target, _path: FakeResponse(body=b"x" * (MAX_RESPONSE_BYTES + 1)),
        )


def test_fetch_preserves_provenance(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, port, *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    responses = iter(
        [
            FakeResponse(302, {"Location": "/final"}),
            FakeResponse(body=b"evidence"),
        ]
    )
    result = fetch_data_file(
        "https://official.test/start",
        transport=lambda _target, _path: next(responses),
    )
    assert result.final_url == "https://official.test/final"
    assert result.redirects == ("https://official.test/final",)
    assert result.body == b"evidence"


def test_browser_proxy_reuses_the_same_target_validation() -> None:
    proxy = LocalEgressProxy()
    with pytest.raises(UnsafeTarget):
        proxy.validate_connect_target("169.254.169.254:443")


def test_browser_proxy_rejects_private_connect_before_upstream() -> None:
    with LocalEgressProxy() as proxy, socket.create_connection(proxy.address) as client:
        client.sendall(b"CONNECT 169.254.169.254:443 HTTP/1.1\r\nHost: 169.254.169.254:443\r\n\r\n")
        assert client.recv(64).startswith(b"HTTP/1.1 403")


def test_a_urllib3_timeout_degrades_the_source_instead_of_crashing_the_run(monkeypatch) -> None:
    """Whole-branch review Fix 2.

    urllib3's own exceptions (ConnectTimeoutError, ReadTimeoutError, SSLError,
    NameResolutionError, ProtocolError, NewConnectionError) inherit from
    urllib3.exceptions.HTTPError -> Exception, never from OSError, and
    `_request` sets retries=False so urllib3 raises them directly. Nothing
    upstream of `_request` catches a bare Exception, so one flaky host used to
    end the entire discovery run instead of just that source.
    """
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, port, *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )

    def timing_out(_target, _path):
        raise urllib3.exceptions.ReadTimeoutError(None, "/", "read timed out")

    slept: list[float] = []
    with pytest.raises(SourceBlocked, match="ReadTimeoutError"):
        fetch_data_file(
            "https://official.test/", transport=timing_out, sleep=slept.append
        )

    assert len(slept) == 3, "a host that keeps dropping is retried a bounded number of times"


def test_a_urllib3_timeout_on_the_json_api_path_also_degrades_not_crashes(public_dns) -> None:
    def timing_out(_target, _path, **_kwargs):
        raise urllib3.exceptions.ConnectTimeoutError("connect timed out")

    with pytest.raises(SourceBlocked, match="ConnectTimeoutError"):
        fetch_json_api(
            "https://api.exa.ai/search", payload={}, headers={}, transport=timing_out
        )


class StallingMidBodyResponse:
    """A response that opens fine but raises reading the body, like urllib3
    does from HTTPResponse.read()'s own _error_catcher on a stalled host."""

    def __init__(self, content_type: str = "text/html") -> None:
        self.status = 200
        self.headers = {"Content-Type": content_type}
        self._read_count = 0

    def read(self, amount: int, decode_content: bool = True) -> bytes:
        self._read_count += 1
        if self._read_count == 1:
            return b"partial"
        raise urllib3.exceptions.ReadTimeoutError(None, "/", "read timed out")

    def release_conn(self) -> None:
        pass


def test_a_stall_mid_body_degrades_the_source_instead_of_crashing_the_run(
    monkeypatch,
) -> None:
    """Fix 2 covered only the connect/open call. The body is streamed via
    response.read() in a loop with preload_content=False and a 20s read
    timeout, so a host that accepts the connection and then stalls mid-body
    raises ReadTimeoutError from read() itself, not from transport()."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, port, *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    with pytest.raises(SourceBlocked, match="ReadTimeoutError"):
        fetch_data_file(
            "https://official.test/",
            transport=lambda _target, _path: StallingMidBodyResponse(),
        )


def test_a_stall_mid_body_on_the_json_api_path_also_degrades_not_crashes(
    public_dns,
) -> None:
    with pytest.raises(SourceBlocked, match="ReadTimeoutError"):
        fetch_json_api(
            "https://api.exa.ai/search",
            payload={},
            headers={},
            transport=lambda _target, _path, **_kwargs: StallingMidBodyResponse(
                "application/json"
            ),
        )


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


# --- browser_required detection and throttling backoff -------------------------

_SHELL = (
    b"<html><head><title>Search</title>" + b"<style>" + b"x{a:b}" * 4000 + b"</style></head>"
    b"<body><nav>Menu Home Disclaimer</nav>" + b'<div class="ecl-x" data-drupal="1"></div>' * 900
    + b"</body></html>"
)
_CONTENT = (
    b"<html><body><h1>MSc Robotics</h1><p>"
    + b"Taught in English over four semesters. " * 400
    + b"</p></body></html>"
)


def _resp(status=200, headers=None, body=b"", ):
    class R:
        def __init__(self) -> None:
            self.status = status
            self.headers = headers or {"Content-Type": "text/html"}
            self._b = body

        def read(self, amount, decode_content=True):
            chunk, self._b = self._b[:amount], self._b[amount:]
            return chunk

        def release_conn(self):
            pass

    return R()


def test_a_javascript_shell_is_flagged_as_needing_a_browser(public_dns) -> None:
    """EACEA's detail pages are 172KB of markup with 2.7KB of text.

    Plain retrieval "succeeds" and returns nothing worth extracting, so the
    fetch has to say so rather than hand a parser page furniture.
    """
    result = fetch_data_file(
        "https://x.example/p", transport=lambda *a, **k: _resp(body=_SHELL)
    )

    assert result.browser_required is True


def test_a_normal_content_page_is_not_flagged(public_dns) -> None:
    result = fetch_data_file(
        "https://x.example/p", transport=lambda *a, **k: _resp(body=_CONTENT)
    )

    assert result.browser_required is False


def test_a_small_page_is_never_flagged(public_dns) -> None:
    """A short page is not a JS shell; flagging it would send every 404 to a browser."""
    result = fetch_data_file(
        "https://x.example/p", transport=lambda *a, **k: _resp(body=b"<html><body>hi</body></html>")
    )

    assert result.browser_required is False


def test_json_is_never_flagged(public_dns) -> None:
    result = fetch_data_file(
        "https://x.example/p",
        transport=lambda *a, **k: _resp(
            headers={"Content-Type": "application/json"}, body=b'{"a":' + b'1,' * 9000 + b'2}'
        ),
    )

    assert result.browser_required is False


def test_a_throttled_host_is_retried_with_backoff_then_succeeds(public_dns) -> None:
    """Today's live run was refused by a burst limiter. Waiting is the fix."""
    slept: list[float] = []
    seq = [_resp(status=429, headers={"Content-Type": "text/html", "Retry-After": "2"}),
           _resp(body=_CONTENT)]

    def transport(*_a, **_k):
        return seq.pop(0)

    result = fetch_data_file(
        "https://x.example/p", transport=transport, sleep=slept.append
    )

    assert result.body == _CONTENT
    assert slept == [2.0], "Retry-After must be honoured verbatim when the host sends one"


def test_backoff_without_a_retry_after_header_grows_and_is_jittered(public_dns) -> None:
    slept: list[float] = []
    seq = [_resp(status=503), _resp(status=503), _resp(body=_CONTENT)]

    result = fetch_data_file(
        "https://x.example/p",
        transport=lambda *a, **k: seq.pop(0),
        sleep=slept.append,
    )

    assert result.body == _CONTENT
    assert len(slept) == 2
    assert slept[1] > slept[0], "backoff must grow"
    assert all(0 < s <= 20 for s in slept), "and stay bounded"


def test_a_host_that_keeps_throttling_is_blocked_not_retried_forever(public_dns) -> None:
    slept: list[float] = []

    with pytest.raises(SourceBlocked) as excinfo:
        fetch_data_file(
            "https://x.example/p",
            transport=lambda *a, **k: _resp(status=429),
            sleep=slept.append,
        )

    assert "429" in str(excinfo.value)
    assert len(slept) == 3, "bounded attempts, then give up and record it"


def test_a_dropped_connection_is_retried_with_backoff_then_succeeds(public_dns) -> None:
    """A reset or a closed idle tunnel is transient; the source is not lost to it."""
    slept: list[float] = []
    seq: list = [
        urllib3.exceptions.ProtocolError("connection reset by peer"),
        _resp(body=_CONTENT),
    ]

    def transport(*_a, **_k):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    result = fetch_data_file(
        "https://x.example/p", transport=transport, sleep=slept.append
    )

    assert result.body == _CONTENT
    assert len(slept) == 1 and 0 < slept[0] <= 20


def test_a_nonsense_retry_after_is_ignored_rather_than_obeyed(public_dns) -> None:
    """A hostile or broken host must not be able to park the run for a day."""
    slept: list[float] = []
    seq = [_resp(status=429, headers={"Content-Type": "text/html", "Retry-After": "86400"}),
           _resp(body=_CONTENT)]

    fetch_data_file(
        "https://x.example/p", transport=lambda *a, **k: seq.pop(0), sleep=slept.append
    )

    assert slept[0] <= 20


def test_a_small_javascript_shell_is_detected_as_unrendered() -> None:
    # Opintopolku's real shape, 2026-08-28: 7,127 bytes of markup carrying 11
    # characters of text. The old 20 KB floor let this pass as rendered.
    shell = (
        b"<html><head><title>Opintopolku</title></head><body><div id=root></div>"
        + b"<div class='x'></div>" * 300
        + b"</body></html>"
    )
    assert 2_000 < len(shell) < 20_000
    assert looks_unrendered("text/html", shell) is True


def test_a_short_error_stub_is_not_treated_as_a_shell() -> None:
    assert looks_unrendered("text/html", b"<html><body><h1>404</h1></body></html>") is False


def test_a_second_address_is_tried_when_the_first_is_unreachable(monkeypatch) -> None:
    # crt.sh resolves IPv6-first and addresses are sorted lexically, so an
    # IPv6-only attempt failed on a v4-only host even though an A record existed.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [
            (socket.AF_INET6, None, None, "", ("2a0e:ac00::1", port, 0, 0)),
            (socket.AF_INET, None, None, "", ("91.199.212.73", port)),
        ],
    )
    target = validate_public_url("https://crt.sh/")
    assert target.addresses[0].startswith("2a0e")

    attempted: list[str] = []

    class Pool:
        def __init__(self, address, port, **kwargs) -> None:
            attempted.append(address)
            self._address = address

        def urlopen(self, *args, **kwargs):
            if self._address.startswith("2a0e"):
                raise urllib3.exceptions.NewConnectionError(None, "network unreachable")
            return FakeResponse()

    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    response = _request(target, "/")

    assert attempted == ["2a0e:ac00::1", "91.199.212.73"]
    assert response.status == 200


def test_all_addresses_unreachable_still_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [(socket.AF_INET, None, None, "", ("91.199.212.73", port))],
    )

    class Pool:
        def __init__(self, address, port, **kwargs) -> None:
            pass

        def urlopen(self, *args, **kwargs):
            raise urllib3.exceptions.NewConnectionError(None, "refused")

    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    with pytest.raises(urllib3.exceptions.NewConnectionError):
        _request(validate_public_url("https://crt.sh/"), "/")


def _headers_seen(monkeypatch, extra_headers=None) -> dict:
    seen: dict = {}

    class Pool:
        def __init__(self, address, port, **kwargs) -> None:
            pass

        def urlopen(self, method, path, **kwargs):
            seen.update(kwargs.get("headers") or {})
            return FakeResponse()

    monkeypatch.setattr(socket, "getaddrinfo",
        lambda host, port, *a, **k: [(socket.AF_INET, None, None, "", ("91.199.212.73", port))])
    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    _request(validate_public_url("https://crt.sh/"), "/", extra_headers=extra_headers)
    return seen


def test_every_fetch_identifies_itself(monkeypatch) -> None:
    """A headerless request is refused by ordinary official sites, and the refusal is
    indistinguishable from a bot wall worth paying a vendor to climb. Measured 2026-09-19 on
    globed.eu, which the 2026-09-18 recovery run recorded as SourceBlocked: no User-Agent
    -> 403, an identifying one -> 200, and R-056 was readable all along.

    It must stay an identifier, not a browser string: CLAUDE.md permits egress that makes
    this platform consistently identifiable and forbids egress that makes it look like many
    unrelated ordinary users."""
    seen = _headers_seen(monkeypatch)

    assert seen["User-Agent"] == USER_AGENT
    assert "Mozilla" not in seen["User-Agent"]


def test_a_caller_with_its_own_user_agent_keeps_it(monkeypatch) -> None:
    """europass.py speaks to a JSON API with its own session, not to a site."""
    seen = _headers_seen(monkeypatch, {"User-Agent": "caller/9"})

    assert seen["User-Agent"] == "caller/9"


def test_a_markup_heavy_page_with_real_text_is_not_a_shell() -> None:
    """Measured 2026-08-30: the five live consortium sites of shadow run 2.

    Each served 3,900-7,300 characters of ordinary readable text inside 50 KB to
    1.25 MB of CMS markup, and a 5% text-ratio test called every one of them a
    JavaScript shell -- three of them at 4.8-4.9%, i.e. decided by the threshold.
    Every one was blocked and never extracted. This is that shape.
    """
    page = (
        b"<html><body>"
        + b"<div class='nav-item-wrapper' data-controller='x'><span></span></div>" * 700
        + b"<main><p>" + b"Les bourses Erasmus Mundus couvrent la formation. " * 40
        + b"</p></main></body></html>"
    )
    assert len(page) > 50_000
    assert looks_unrendered("text/html", page) is False


# require_same_origin's live caller is reader.py::read_program_page. The URLs
# below are just fixtures: they name a real register host because the register
# adapter was the first caller, and it was deleted on 2026-09-14.
@pytest.mark.parametrize(
    "final_url",
    [
        "https://attacker.example/deqar-reports.csv",
        # A subdomain is a different origin: subdomain takeover lands here.
        "https://evil.backend.deqar.eu/deqar-reports.csv",
        # Same host, scheme walked down. validate_public_url permits http.
        "http://backend.deqar.eu/deqar-reports.csv",
    ],
)
def test_require_same_origin_refuses_another_origin(final_url: str) -> None:
    with pytest.raises(OffSiteRedirect):
        require_same_origin(
            "https://backend.deqar.eu/static/daily-csv/deqar-reports.csv",
            FetchResult(final_url, (), "application/octet-stream", b""),
        )


def test_require_same_origin_allows_a_path_or_case_change_on_the_same_origin() -> None:
    require_same_origin(
        "https://backend.deqar.eu/static/daily-csv/deqar-reports.csv",
        FetchResult("https://BACKEND.deqar.eu/moved/", (), "application/octet-stream", b""),
    )


def test_reader_re_exports_the_one_off_site_error() -> None:
    from apps.research import reader

    assert reader.OffSiteRedirect is OffSiteRedirect


class _JsonBody:
    def __init__(self, content_type: str) -> None:
        self.status, self.headers = 200, {"Content-Type": content_type}
        self._chunks = [b'{"results": {"bindings": []}}']

    def read(self, amount: int, decode_content: bool = True) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def release_conn(self) -> None:
        pass


def test_fetch_json_api_accepts_a_declared_json_dialect(public_dns) -> None:
    """SPARQL answers application/sparql-results+json. The default stays strict;
    a caller widens it by name, and the Accept header says the same thing."""
    sent: dict[str, str] = {}

    def transport(_target, _path, **kwargs):
        sent.update(kwargs["extra_headers"])
        return _JsonBody("application/sparql-results+json; charset=utf-8")

    body = fetch_json_api(
        "https://query.wikidata.org/sparql", params={"query": "ASK {}"}, headers={},
        transport=transport, accept=("application/sparql-results+json",),
    )
    assert body == {"results": {"bindings": []}}
    assert sent["Accept"] == "application/sparql-results+json"
    with pytest.raises(SourceBlocked, match="content type"):
        fetch_json_api(
            "https://query.wikidata.org/sparql", params={"query": "ASK {}"}, headers={},
            transport=lambda *_a, **_k: _JsonBody("application/sparql-results+json"),
        )


def test_the_byte_cap_is_per_call(public_dns) -> None:
    """Provenance gate spec §6: a source's cap is its own; the default stays 10 MB."""
    with pytest.raises(ResponseTooLarge):
        fetch_data_file(
            "https://official.test/", max_bytes=5,
            transport=lambda _target, _path: FakeResponse(body=b"x" * 6),
        )
    assert fetch_data_file(
        "https://official.test/", max_bytes=6,
        transport=lambda _target, _path: FakeResponse(body=b"x" * 6),
    ).body == b"x" * 6


@pytest.mark.parametrize(
    "content_type",
    [
        "application/rdap+json",
        'application/rdap+json;extensions="rdap_level_0 jscontact";charset=UTF-8',
        "text/csv",
        "text/tab-separated-values",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ],
)
def test_register_and_rdap_types_are_data_files(public_dns, content_type: str) -> None:
    result = fetch_data_file(
        "https://official.test/",
        transport=lambda _target, _path: FakeResponse(headers={"Content-Type": content_type}),
    )
    assert result.body == b"official"


def test_data_file_types_do_not_widen_what_a_vendor_page_may_be() -> None:
    """A vendor's raw XLSX or CSV stays unreadable without its markdown."""
    for content_type in ("text/csv",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
        assert usable(content_type, b"a,b\n" * 2_000, 200) == (
            False, f"content_type:{content_type}"
        )
