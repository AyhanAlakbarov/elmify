"""HTTP for fixed, trusted hosts.

Deliberately NOT apps/research/egress.py. That module pins DNS and validates
every redirect hop because it fetches hosts a student named; this package only
ever talks to constants we chose (api.crossref.org, api.openalex.org,
api.github.com, gitlab.com), so the SSRF machinery would imply a threat that
sources.py has already removed.

The protocol exists so every fetcher takes a fake in tests and no test needs a
network or a mocked HTTP library.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import urllib3

_TIMEOUT = urllib3.Timeout(connect=5, read=20)
_USER_AGENT = "tehsil-agent/1.0 (+https://github.com/0rkhann/tehsil_agent)"


class Transport(Protocol):
    def get_json(
        self, url: str, *, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]: ...


class Urllib3Transport:
    def __init__(self) -> None:
        self._pool = urllib3.PoolManager(timeout=_TIMEOUT, retries=urllib3.Retry(2))

    def get_json(
        self, url: str, *, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        merged = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        merged.update(headers or {})
        try:
            response = self._pool.request("GET", url, headers=merged)
        except urllib3.exceptions.HTTPError:
            # A connection failure, timeout or retry exhaustion (e.g. a
            # Crossref timeout raising MaxRetryError) is one of this
            # protocol's three outcomes, not an exception escaping the
            # module -- every caller already treats (0, {}) as "not a 200".
            return 0, {}
        if response.status != 200:
            return response.status, {}
        try:
            body = json.loads(response.data)
        except ValueError:
            return response.status, {}
        return response.status, body
