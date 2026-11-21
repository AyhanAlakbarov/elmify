"""HTTP for fixed, trusted hosts.

Deliberately NOT apps/research/egress.py. That module pins DNS and validates
every redirect hop because it fetches hosts a student named; this package only
ever talks to constants we chose (api.crossref.org, api.openalex.org,
api.github.com), so the SSRF machinery would imply a threat that sources.py and
github.py have already removed.

Every call answers (status, body, headers), header names lower-cased. A
non-200 keeps its headers: github.py reads x-ratelimit-remaining and
retry-after off a 403 to tell a rate limit from a refusal.

The protocol exists so every fetcher takes a fake in tests and no test needs a
network or a mocked HTTP library.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit

import urllib3

logger = logging.getLogger(__name__)

_TIMEOUT = urllib3.Timeout(connect=5, read=20)
_USER_AGENT = "elmify/1.0 (+https://github.com/0rkhann/elmify)"

#: Response headers, names lower-cased.
Headers = Mapping[str, str]


class Transport(Protocol):
    def get_json(
        self, url: str, *, headers: dict[str, str] | None = None
    ) -> tuple[int, Any, Headers]: ...

    def post_json(
        self, url: str, body: object, *, headers: dict[str, str] | None = None
    ) -> tuple[int, Any, Headers]: ...

    def get_bytes(
        self, url: str, *, headers: dict[str, str] | None = None, max_bytes: int
    ) -> tuple[int, bytes, Headers]: ...


def _lowered(headers: Any) -> dict[str, str]:
    return {str(name).lower(): str(value) for name, value in dict(headers or {}).items()}


class Urllib3Transport:
    def __init__(self) -> None:
        self._pool = urllib3.PoolManager(timeout=_TIMEOUT, retries=urllib3.Retry(2))

    @staticmethod
    def _merged(headers: dict[str, str] | None, accept: str) -> dict[str, str]:
        merged = {"User-Agent": _USER_AGENT, "Accept": accept}
        merged.update(headers or {})
        return merged

    def get_json(
        self, url: str, *, headers: dict[str, str] | None = None
    ) -> tuple[int, Any, Headers]:
        return self._json("GET", url, self._merged(headers, "application/json"), None)

    def post_json(
        self, url: str, body: object, *, headers: dict[str, str] | None = None
    ) -> tuple[int, Any, Headers]:
        merged = self._merged(headers, "application/json")
        merged["Content-Type"] = "application/json"
        return self._json("POST", url, merged, json.dumps(body).encode())

    def _json(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, Any, Headers]:
        host = urlsplit(url).hostname or "unknown"
        try:
            response = self._pool.request(method, url, headers=headers, body=body)
        except urllib3.exceptions.HTTPError as error:
            # A connection failure, timeout or retry exhaustion is one of this
            # protocol's outcomes, not an exception escaping the module: every
            # caller treats status 0 as "not a 200".
            reason = getattr(error, "reason", None)
            logger.warning(
                "EvidenceTransportError host=%s method=%s error=%s reason=%s",
                host,
                method,
                type(error).__name__,
                type(reason).__name__ if reason is not None else "-",
            )
            return 0, {}, {}
        found = _lowered(response.headers)
        if response.status != 200:
            return response.status, {}, found
        try:
            return response.status, json.loads(response.data), found
        except ValueError as error:
            logger.warning(
                "EvidenceTransportInvalidJson host=%s method=%s status=%d error=%s",
                host,
                method,
                response.status,
                type(error).__name__,
            )
            return response.status, {}, found

    def get_bytes(
        self, url: str, *, headers: dict[str, str] | None = None, max_bytes: int
    ) -> tuple[int, bytes, Headers]:
        host = urlsplit(url).hostname or "unknown"
        try:
            response = self._pool.request(
                "GET", url, headers=self._merged(headers, "*/*"), preload_content=False
            )
        except urllib3.exceptions.HTTPError as error:
            logger.warning(
                "EvidenceTransportError host=%s method=GET error=%s",
                host,
                type(error).__name__,
            )
            return 0, b"", {}
        try:
            found = _lowered(response.headers)
            if response.status != 200:
                return response.status, b"", found
            data = response.read(max_bytes + 1)
        except urllib3.exceptions.HTTPError as error:
            logger.warning(
                "EvidenceTransportReadError host=%s method=GET error=%s",
                host,
                type(error).__name__,
            )
            return 0, b"", {}
        finally:
            response.release_conn()
        # Over the cap is absent, never a prefix: a cut file reads as a different file.
        return (200, b"", found) if len(data) > max_bytes else (200, data, found)
