"""RDAP registration dates for the domain-takeover signal (spec §5.5).

IANA's bootstrap names each TLD's registry; the registry is called directly,
because rdap.org redirects. Port-43 WHOIS and the .az web form are not used:
they would be new outbound paths with no SSRF guard. Measured 2026-09-26:
.com, .gov, .kr (ac.kr included), .uk under Nominet and .fr give a date; .az,
.de, .tr and ac.uk do not, and those are recorded as skipped, never passed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime

from .egress import FetchResult, SourceBlocked, UnsafeTarget, fetch_data_file
from .provenance import RdapResult

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
#: Registered by Jisc, which does not answer Nominet's RDAP.
NO_REGISTRATION_DATE: tuple[str, ...] = ("ac.uk",)
#: RDAP bodies are small JSON documents; never a data-file-sized fetch.
MAX_RDAP_BYTES = 2 * 1024 * 1024

FetchFile = Callable[..., FetchResult]


def load_bootstrap(*, fetch: FetchFile | None = None) -> dict[str, str]:
    body = json.loads(
        (fetch or fetch_data_file)(
            BOOTSTRAP_URL, require_https=True, max_bytes=MAX_RDAP_BYTES
        ).body
    )
    table: dict[str, str] = {}
    for tlds, urls in body.get("services", []):
        https = [str(url) for url in urls if str(url).startswith("https://")]
        if https:
            for tld in tlds:
                table[str(tld).casefold()] = https[0]
    return table


def registration_date(
    domain: str, bootstrap: Mapping[str, str], *, fetch: FetchFile | None = None
) -> RdapResult:
    if any(domain == suffix or domain.endswith(f".{suffix}") for suffix in NO_REGISTRATION_DATE):
        detail = "ac.uk is registered by Jisc, which does not answer RDAP"
        return RdapResult("skipped", detail=detail)
    try:
        label = domain.encode("idna").decode("ascii")
    except UnicodeError as error:
        return RdapResult("skipped", detail=f"not a valid domain: {error}"[:200])
    tld = label.rsplit(".", 1)[-1]
    base = bootstrap.get(tld)
    if base is None:
        return RdapResult("skipped", detail=f"no RDAP service for .{tld} in IANA's bootstrap")
    getter = fetch or fetch_data_file
    url = f"{base.rstrip('/')}/domain/{label}"
    try:
        answer = json.loads(getter(url, require_https=True, max_bytes=MAX_RDAP_BYTES).body)
    except (SourceBlocked, UnsafeTarget, ValueError) as error:
        return RdapResult("failed", detail=str(error)[:200])
    events = answer.get("events", []) if isinstance(answer, dict) else []
    for event in events:
        action = str(event.get("eventAction", "")).casefold() if isinstance(event, dict) else ""
        if action == "registration":
            try:
                registered = datetime.fromisoformat(str(event["eventDate"])).date()
                return RdapResult("ok", registered=registered)
            except (KeyError, ValueError):
                break
    return RdapResult("skipped", detail="the registry reports no registration date")
