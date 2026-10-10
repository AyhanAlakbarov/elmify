import json
import random
import re
import selectors
import socket
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Literal, Protocol, cast
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import urllib3

#: The "page is a shell" floor: fewer than this many readable characters while
#: the raw page is at least this many bytes. Lives here, rather than in
#: reader.py where it is consumed (reader.is_shell), because fetch/firecrawl.py
#: needs the same numbers and cannot import reader.py -- reader imports
#: discovery, which imports the fetch package firecrawl.py is a submodule of,
#: a real circular import (measured). egress.py has no apps.research imports
#: of its own, so both sides can import it. Two-sided on purpose: a 300-byte
#: page with 90 characters of prose is not a shell, its text is the page.
#: Measured 2026-09-12/13, see reader.py's is_shell for the readings.
_MIN_READABLE_CHARS = 1_500
_MIN_BYTES_FOR_FLOOR = 20_000

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/pdf",
    "application/xml",
    "text/html",
    "text/plain",
    "text/xml",
}
#: `fetch_data_file` only (provenance gate spec §6): registry RDAP answers and
#: register files published as CSV/TSV/XLSX. Kept out of ALLOWED_CONTENT_TYPES,
#: which `fetch.types.usable` also reads: there a vendor's raw XLSX or CSV is
#: readable only through the markdown the vendor made of it.
DATA_FILE_TYPES = ALLOWED_CONTENT_TYPES | {
    "application/rdap+json",
    "text/csv",
    "text/tab-separated-values",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class UnsafeTarget(ValueError):
    pass


class SourceBlocked(RuntimeError):
    def __init__(self, message: str = "", *, outcome: str | None = None) -> None:
        super().__init__(message)
        #: The fetch Outcome, when a ladder produced one. None from the
        #: first-party transport, which has no ladder. Callers decide on THIS,
        #: never on the message -- pipeline.py files BLOCKED/UNREACHABLE hosts
        #: to the resolution queue and reports the rest.
        self.outcome = outcome


class ResponseTooLarge(SourceBlocked):
    pass


class RedirectLimitExceeded(SourceBlocked):
    pass


class Response(Protocol):
    status: int
    headers: Mapping[str, str]

    def read(self, amount: int, decode_content: bool = True) -> bytes: ...

    def release_conn(self) -> None: ...


@dataclass(frozen=True)
class ResolvedTarget:
    scheme: Literal["http", "https"]
    host: str
    port: int
    addresses: tuple[str, ...]


@dataclass(frozen=True)
class FetchResult:
    final_url: str
    redirects: tuple[str, ...]
    content_type: str
    body: bytes
    browser_required: bool = False
    #: Which tier produced the body: EGRESS (our client), SCRAPE_DO, FIRECRAWL.
    #: Provenance for the snapshot -- a vendor's HTML is its rendering, not origin bytes.
    fetched_via: str = "EGRESS"


class OffSiteRedirect(ValueError):
    """The fetch ended somewhere other than the source the catalog vouched for.

    Why origin rather than the whole URL, and why this must not be tightened:
    CLAUDE.md, "Decision B vouches for the SOURCE ROW, not the BYTES". Its one
    caller is reader.py::read_program_page; it had a second in the register
    adapter until that was deleted on 2026-09-14, which is why it lives here
    rather than beside its caller.
    """


def _origin(url: str) -> tuple[str, str]:
    """Scheme and host, lowercased -- the part a redirect must not change."""
    parsed = urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower()


def require_same_origin(requested: str, fetched: FetchResult) -> None:
    """Raise OffSiteRedirect unless the fetch ended on the requested origin.

    Call it before persist_snapshot: off-site bytes must not be archived under
    the source's provenance either.
    """
    if _origin(fetched.final_url) != _origin(requested):
        raise OffSiteRedirect(f"{requested} redirected off-site to {fetched.final_url}")


def validate_public_url(url: str) -> ResolvedTarget:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or not parsed.hostname
    ):
        raise UnsafeTarget(url)
    try:
        host = parsed.hostname.encode("idna").decode("ascii")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = tuple(sorted({str(item[4][0]) for item in socket.getaddrinfo(host, port)}))
    except (UnicodeError, ValueError, OSError) as error:
        raise UnsafeTarget(url) from error
    if not addresses or any(not ip_address(address).is_global for address in addresses):
        raise UnsafeTarget(url)
    return ResolvedTarget(cast(Literal["http", "https"], parsed.scheme), host, port, addresses)


#: Sent on every outbound fetch. Measured 2026-09-19 on globed.eu/how-to-apply/, one of the
#: hosts the 2026-09-18 recovery run recorded as SourceBlocked: **no** User-Agent -> 403,
#: `python-urllib3/2.0` -> 403, `TehsilAgent/1.0 (+...)` -> 200. So that 403 was never a bot
#: wall we had to pay a vendor to climb -- it was a headerless request, and one of the
#: fifteen labelled rules was lost to it.
#:
#: It names us on purpose. CLAUDE.md's egress rule is that egress making the platform
#: "consistently identifiable is permitted; egress that makes it look like many unrelated
#: ordinary users is not" -- so this is a stable identifier carrying a contact URL, never a
#: browser string. A browser mimic also returned 200 in that measurement and is still not
#: what goes here; the vendor tiers exist for hosts an honest client cannot read.
USER_AGENT = "TehsilAgent/1.0 (+https://tehsil-agent.example/bot)"


def _request(
    target: ResolvedTarget,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    extra_headers: Mapping[str, str] | None = None,
    read_timeout: float = 20.0,
) -> Response:
    # Caller headers first: Host is derived from the validated target and a
    # caller must not be able to shadow it. Drop any caller "host"/"HOST" key
    # by casefold, not just the exact-cased "Host", so exactly one Host header
    # ever reaches urllib3 -- two would be a vhost-routing primitive.
    # USER_AGENT is defaulted, not forced: a caller that sets its own (europass.py
    # speaks to an API, not a site) keeps it, because only "host" is stripped above.
    merged = {k: v for k, v in dict(extra_headers or {}).items() if k.casefold() != "host"}
    if not any(k.casefold() == "user-agent" for k in merged):
        merged["User-Agent"] = USER_AGENT
    headers = {**merged, "Host": target.host}
    # Every resolved address in turn, not just the first. addresses is sorted
    # lexically, so "2a0e:..." sorts ahead of "91.199...." and an IPv6-first host
    # was unreachable from a v4-only network even with an A record present
    # (crt.sh, 2026-08-28). Each address is already validated as global by
    # validate_public_url, so trying another one widens nothing.
    last: Exception | None = None
    for address in target.addresses:
        if target.scheme == "https":
            pool: urllib3.HTTPConnectionPool = urllib3.HTTPSConnectionPool(
                address,
                target.port,
                assert_hostname=target.host,
                server_hostname=target.host,
                maxsize=1,
            )
        else:
            pool = urllib3.HTTPConnectionPool(address, target.port, maxsize=1)
        try:
            return cast(
                Response,
                pool.urlopen(
                    method,
                    path,
                    body=body,
                    headers=headers,
                    redirect=False,
                    preload_content=False,
                    timeout=urllib3.Timeout(connect=5, read=read_timeout),
                    retries=False,
                ),
            )
        except (
            urllib3.exceptions.NewConnectionError,
            urllib3.exceptions.NameResolutionError,
        ) as error:
            # Only "could not reach this address". A TLS failure, a timeout or a
            # protocol error is the server answering, and retrying another
            # address would mask it.
            last = error
    raise last if last is not None else urllib3.exceptions.HTTPError("no address resolved")


#: Statuses that mean "come back later", not "no". Anything else is a refusal.
_THROTTLED = {429, 503}
_MAX_BACKOFF_SECONDS = 20.0
_RETRY_ATTEMPTS = 3
#: Below this much visible text, an HTML response has nothing in it for an
#: extractor and the caller escalates to a browser.
#:
#: An absolute floor, not a share of the markup. The share was measured against
#: one EACEA detail page (172 KB of markup, 2.7 KB of text, 1.6%) and generalised
#: badly: measured on 2026-08-30 against the five live consortium sites of shadow
#: run 2, a 5% ratio called *every one of them* a JavaScript shell, and all five
#: in fact served 3,900 to 7,300 characters of ordinary readable text -- three of
#: them sitting at 4.8-4.9%, decided by the threshold rather than by the page.
#: What separates a shell from a page is how much text there is, not how much
#: markup surrounds it: Opintopolku's shell carries one word, and a heavy CMS
#: page carries hundreds regardless of its chrome.
_MIN_VISIBLE_WORDS = 40
#: Short pages are not JS shells -- an error page or a stub would otherwise be
#: sent to a browser for nothing. Lowered from 20 KB on 2026-08-28: Opintopolku
#: serves a 7,127-byte shell carrying 11 characters of text, which the old floor
#: let through as rendered. Only stubs and error pages sit below this.
_SHELL_MIN_BYTES = 2_000
_TAGS = re.compile(rb"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>|<[^>]+>")


def looks_unrendered(content_type: str, body: bytes) -> bool:
    """True when plain retrieval returned markup with no substance in it.

    Not a heuristic about *quality*: it answers whether there is anything for an
    extractor to read at all. The caller escalates to a browser; it never
    discards the page on this alone.
    """
    if content_type != "text/html" or len(body) < _SHELL_MIN_BYTES:
        return False
    return len(_TAGS.sub(b" ", body).split()) < _MIN_VISIBLE_WORDS


def _backoff_seconds(response: object, attempt: int) -> float:
    """How long to wait before retrying a throttled host.

    ``Retry-After`` is honoured when the host sends a sane one, because it is
    the host telling us its own limit. An absurd value is clamped rather than
    obeyed: a broken or hostile header must not be able to park a run.
    """
    stated = _header(getattr(response, "headers", None), "Retry-After")
    if stated is not None and stated.strip().isdigit():
        return min(float(stated.strip()), _MAX_BACKOFF_SECONDS)
    # Exponential with jitter, so a fleet of workers does not resynchronise on
    # the same second and re-trigger the limiter they are backing off from.
    return min(2.0 ** (attempt + 1) + random.uniform(0, 1), _MAX_BACKOFF_SECONDS)  # nosec B311


def _header(headers: object, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    return value if isinstance(value, str) else None


def fetch_data_file(
    url: str,
    *,
    transport: Callable[[ResolvedTarget, str], Response] = _request,
    require_https: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> FetchResult:
    """Our own transport, kept on purpose for DATA FILES -- never pages.

    Pages go through the vendor router now (`discovery.retrieve_official_source`).
    This one survives because its callers are not fetching a page at all:
    `search.sitemap_urls` reads XML sitemaps -- Firecrawl renders one into a
    `<html><body>` viewer wrapper whose root tag is no longer `sitemapindex`
    (see that function's docstring) -- and `services.py` fetches a JSON fixture
    the same way. It was written for a third: `registers.py` parsed DEQAR's
    daily CSVs with `csv`, and left with the institution-safety screen on
    2026-09-14. A vendor returns markdown or its own processed HTML, which
    would mangle XML or JSON beyond parsing rather than merely reformat it,
    and these are public static endpoints, not bot-walled pages a vendor
    exists to climb. Pages to vendors, data files to us.

    `max_bytes` is per call: a source's cap lives in its provenance-sources
    row; the 10 MB default is unchanged.
    """
    current = url
    redirects: list[str] = []
    waited = 0
    for redirect_count in range(6 + _RETRY_ATTEMPTS):
        target = validate_public_url(current)
        if require_https and target.scheme != "https":
            raise UnsafeTarget(current)
        parsed = urlsplit(current)
        path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        try:
            response = transport(target, path)
        except urllib3.exceptions.HTTPError as error:
            # urllib3's own exceptions (timeouts, TLS failures, DNS failures,
            # connection resets) all inherit from HTTPError -> Exception, NOT
            # from OSError, and retries=False in _request means urllib3 raises
            # them directly. Without this they crash the whole discovery run
            # instead of degrading one source (design promise, three
            # docstrings, whole-branch review Fix 2).
            # A dropped connection is usually transient -- a reset, a DNS
            # blip, an idle tunnel closed by an egress hop -- so it earns the
            # same bounded wait as a throttle before the source is given up
            # on. The budget is shared with throttling so the total number of
            # waits per fetch stays inside the loop bound above.
            if waited >= _RETRY_ATTEMPTS:
                raise SourceBlocked(f"{type(error).__name__}: {error}") from error
            sleep(_backoff_seconds(None, waited))
            waited += 1
            continue
        try:
            if response.status in {301, 302, 303, 307, 308}:
                location = _header(response.headers, "Location")
                if not location:
                    raise SourceBlocked("redirect missing Location")
                if len(redirects) == 5:
                    raise RedirectLimitExceeded(current)
                current = urljoin(current, location)
                redirects.append(current)
                continue
            if response.status in _THROTTLED:
                # Come back later, not no. A burst limiter refused the live run
                # against erasmus-plus.ec.europa.eu on 2026-08-28; waiting is
                # the correct response to it, and giving up after a bounded
                # number of waits is the correct response to a host that means
                # it.
                if waited >= _RETRY_ATTEMPTS:
                    raise SourceBlocked(f"source returned HTTP {response.status}")
                delay = _backoff_seconds(response, waited)
                waited += 1
                sleep(delay)
                continue
            if response.status >= 400:
                raise SourceBlocked(f"source returned HTTP {response.status}")
            content_type = (_header(response.headers, "Content-Type") or "").split(";", 1)[0]
            if content_type not in DATA_FILE_TYPES:
                raise SourceBlocked(f"disallowed content type: {content_type or 'missing'}")
            chunks: list[bytes] = []
            size = 0
            try:
                while chunk := response.read(64 * 1024, decode_content=True):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ResponseTooLarge(current)
                    chunks.append(chunk)
            except urllib3.exceptions.HTTPError as error:
                # response.read() raises the same HTTPError subclasses as the
                # connect/open call above (ReadTimeoutError, ProtocolError,
                # SSLError from urllib3's _error_catcher) -- a server that
                # accepts the connection and stalls mid-body hits this path,
                # not the transport() call. ResponseTooLarge is a RuntimeError,
                # not an HTTPError, so it still propagates untouched.
                raise SourceBlocked(f"{type(error).__name__}: {error}") from error
            body = b"".join(chunks)
            return FetchResult(
                current,
                tuple(redirects),
                content_type,
                body,
                browser_required=looks_unrendered(content_type, body),
            )
        finally:
            response.release_conn()
    raise RedirectLimitExceeded(current)


class LocalEgressProxy:
    def __init__(
        self, *, tunnel_seconds: float = 30.0, max_bytes: int = MAX_RESPONSE_BYTES
    ) -> None:
        self.tunnel_seconds = tunnel_seconds
        self.max_bytes = max_bytes
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def address(self) -> tuple[str, int]:
        if self._listener is None:
            raise RuntimeError("proxy is not running")
        host, port = self._listener.getsockname()
        return str(host), int(port)

    def __enter__(self) -> LocalEgressProxy:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self._listener.settimeout(0.2)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.close()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def validate_connect_target(self, authority: str) -> ResolvedTarget:
        return validate_public_url(f"https://{authority}")

    def _serve(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                client, peer = self._listener.accept()
            except (TimeoutError, OSError):
                continue
            if not ip_address(peer[0]).is_loopback:
                client.close()
                continue
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        with client:
            client.settimeout(5)
            request = b""
            while b"\r\n\r\n" not in request and len(request) <= 8192:
                chunk = client.recv(4096)
                if not chunk:
                    return
                request += chunk
            try:
                method, authority, _version = request.split(b"\r\n", 1)[0].decode().split()
                if method != "CONNECT":
                    # ponytail: browser fallback is HTTPS-only; add normalized plain-HTTP
                    # forwarding if a required official source has no HTTPS endpoint.
                    client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                    return
                target = self.validate_connect_target(authority)
            except (UnicodeError, ValueError, UnsafeTarget):
                client.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            try:
                upstream = socket.create_connection((target.addresses[0], target.port), timeout=5)
            except OSError:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                return
            with upstream:
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._tunnel(client, upstream)

    def _tunnel(self, client: socket.socket, upstream: socket.socket) -> None:
        sockets = {client: upstream, upstream: client}
        transferred = 0
        deadline = time.monotonic() + self.tunnel_seconds
        with selectors.DefaultSelector() as selector:
            for source in sockets:
                source.setblocking(False)
                selector.register(source, selectors.EVENT_READ)
            while time.monotonic() < deadline and transferred <= self.max_bytes:
                events = selector.select(timeout=1)
                if not events:
                    continue
                for key, _mask in events:
                    fileobj = key.fileobj
                    if not isinstance(fileobj, socket.socket):
                        return
                    source = fileobj
                    try:
                        chunk = source.recv(64 * 1024)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        return
                    sockets[source].sendall(chunk)
                    transferred += len(chunk)


def fetch_json_api(
    url: str,
    *,
    payload: Mapping[str, object] | None = None,
    params: Mapping[str, object] | None = None,
    headers: Mapping[str, str],
    transport: Callable[..., Response] = _request,
    read_timeout: float | None = None,
    accept: tuple[str, ...] = ("application/json",),
) -> dict[str, object]:
    """Call a contracted JSON API under the same egress rules as a fetch.

    `payload` POSTs a JSON body; `params` GETs a query string. Exactly one,
    because accepting both would leave which-one-wins to argument order.

    Same private-network block, same size cap, HTTPS only, and no redirect
    following either way: a redirected API call is a refusal, not a hop
    (design §3.4). The GET path lives here rather than in the adapter that
    needed it (Brave's API is a GET) precisely so it cannot skip any of that
    -- a provider reaching for urllib3 directly would have none of it.

    `read_timeout` exists for the one API whose call is a server-side crawl; a
    plain fetch keeps the egress default.

    `accept` widens the content types a caller will parse (SPARQL's
    `application/sparql-results+json`); the default is unchanged.
    """
    if payload is not None and params is not None:
        raise ValueError("fetch_json_api takes payload or params, never both")
    target = validate_public_url(url)
    if target.scheme != "https":
        raise UnsafeTarget(url)
    parsed = urlsplit(url)
    # Caller headers first: Host is pinned to the validated target here too,
    # not just in the default `_request` transport, because a caller-supplied
    # transport must not be able to see a shadowed Host. Drop any caller
    # "host"/"HOST" key by casefold for the same reason as `_request` above.
    sent: dict[str, str] = {
        **{k: v for k, v in dict(headers).items() if k.casefold() != "host"},
        "Host": target.host,
        "Accept": ", ".join(accept),
    }
    if params is not None:
        query = urlencode(
            {**dict(parse_qsl(parsed.query)), **{k: str(v) for k, v in params.items()}}
        )
        path = urlunsplit(("", "", parsed.path or "/", query, ""))
        method, body = "GET", None
    else:
        path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        method = "POST"
        body = json.dumps(payload or {}, sort_keys=True).encode()
        # Only a request that carries a JSON body says it carries one.
        sent["Content-Type"] = "application/json"
    try:
        timeout_kwargs = {} if read_timeout is None else {"read_timeout": read_timeout}
        response = transport(
            target, path, method=method, body=body, extra_headers=sent, **timeout_kwargs
        )
    except urllib3.exceptions.HTTPError as error:
        # Same reasoning as fetch_data_file: urllib3's own exceptions do
        # not inherit from OSError, and retries=False means they surface raw.
        raise SourceBlocked(f"{type(error).__name__}: {error}") from error
    try:
        if response.status >= 300:
            raise SourceBlocked(f"api returned HTTP {response.status}")
        content_type = (_header(response.headers, "Content-Type") or "").split(";", 1)[0]
        if content_type not in accept:
            raise SourceBlocked(f"api returned content type: {content_type or 'missing'}")
        chunks: list[bytes] = []
        size = 0
        try:
            while chunk := response.read(64 * 1024, decode_content=True):
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ResponseTooLarge(url)
                chunks.append(chunk)
        except urllib3.exceptions.HTTPError as error:
            # Same reasoning as fetch_data_file's read loop: a stalled
            # body mid-stream raises here, not from the transport() open call.
            raise SourceBlocked(f"{type(error).__name__}: {error}") from error
        parsed_body = json.loads(b"".join(chunks) or b"{}")
        if not isinstance(parsed_body, dict):
            raise SourceBlocked("api returned a non-object body")
        return cast(dict[str, object], parsed_body)
    finally:
        response.release_conn()


def start_json_operation(
    url: str,
    *,
    payload: Mapping[str, object],
    headers: Mapping[str, str],
    transport: Callable[..., Response] = _request,
) -> str:
    """POST a JSON body to an API that answers 202 and a URL to poll (Azure's analyze call).

    Same rules as fetch_json_api -- HTTPS only, the private-network block, Host pinned, no
    redirect -- and one more: the polling URL must stay on the host that was called, so a
    tampered response cannot point the next request (which carries the same key) elsewhere.
    """
    target = validate_public_url(url)
    if target.scheme != "https":
        raise UnsafeTarget(url)
    parsed = urlsplit(url)
    sent: dict[str, str] = {
        **{k: v for k, v in dict(headers).items() if k.casefold() != "host"},
        "Host": target.host,
        "Content-Type": "application/json",
    }
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    body = json.dumps(payload, sort_keys=True).encode()
    try:
        response = transport(target, path, method="POST", body=body, extra_headers=sent)
    except urllib3.exceptions.HTTPError as error:
        raise SourceBlocked(f"{type(error).__name__}: {error}") from error
    try:
        if response.status != 202:
            raise SourceBlocked(f"api returned HTTP {response.status}")
        location = _header(response.headers, "Operation-Location")
        if not location:
            raise SourceBlocked("api answered 202 with no Operation-Location")
        try:
            polled = validate_public_url(location)
        except UnsafeTarget as error:
            raise SourceBlocked("Operation-Location is not a public https URL") from error
        if polled.scheme != "https":
            raise SourceBlocked("Operation-Location is not a public https URL")
        if polled.host != target.host or polled.port != target.port:
            raise SourceBlocked("Operation-Location points at another host")
        return location
    finally:
        response.release_conn()
