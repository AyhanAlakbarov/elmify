"""Spec 8: one monitor per admissions cycle, checked monthly.

On the free plan with no per-monitor fee; each check pays 1 credit per page
scraped. The judge is OFF: the reader a changed page wakes costs about a
tenth of a cent (typed-decisions 10), less than the 1-credit vendor judge
that would decide whether to wake it. Paying more to decide than to do is the
whole argument, and it is the same one that removed typed-decisions D7 on the
same day.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import batched

import urllib3
from django.conf import settings

from .site import _BASE, Get, Post, _call, _get, _get_json, _headers, _post

logger = logging.getLogger(__name__)

#: Monthly, at 06:00 on the 1st. Firecrawl spreads its own monitors across the
#: window, so this is a request, not a guarantee of the minute.
MONITOR_CRON = "0 6 1 * *"
#: Firecrawl's documented ceiling per monitor. A site with more is split, and
#: the split is explicit because a create call that silently kept the first 50
#: leaves the rest unmonitored with nothing saying so.
MAX_TARGETS = 50
#: One admissions cycle.
RETENTION_DAYS = 365


class MonitorBudgetExceeded(RuntimeError):
    """The cycle's monitors would not fit the monthly credit ceiling."""


class MonitorEstimateMissing(RuntimeError):
    """`estimatedCreditsPerMonth` was absent or non-numeric on the create
    response. An unknown cost is not a zero cost: coercing it to 0 would make
    the pre-flight ceiling check pass trivially and create the whole cycle's
    monitors unmetered, against a field the vendor could rename tomorrow."""


@dataclass(frozen=True)
class MonitorCreated:
    monitor_id: str
    estimated_credits_per_month: int


@dataclass(frozen=True)
class CheckPage:
    url: str
    status: str
    check_id: str


def build_targets(
    urls: Sequence[str],
    *,
    hosts: Sequence[str],
    include_paths: Sequence[str],
    limit: int | None = None,
) -> list[list[dict[str, object]]]:
    """A scrape target per rule-bearing URL, plus a crawl target per site.

    The crawl target carries the SAME `includePaths` and `limit` as the sweep
    (spec 7.3), so a NEW requirements page -- not a change to any known URL --
    is reported as `new`. Different paths would monitor a different site than
    the one the sweep read.
    """
    targets: list[dict[str, object]] = [
        {"type": "scrape", "url": url} for url in dict.fromkeys(urls)
    ]
    for host in dict.fromkeys(hosts):
        targets.append(
            {
                "type": "crawl",
                "url": f"https://{host}/",
                "includePaths": [f".*{re.escape(term)}.*" for term in include_paths],
                "limit": int(limit if limit is not None else settings.FETCH_CRAWL_LIMIT),
            }
        )
    return [list(batch) for batch in batched(targets, MAX_TARGETS)]


#: DELETE /v2/monitor/{id} -- url and headers only, no body, same shape as `Get`.
Delete = Get


def _delete(url: str, headers: dict[str, str]) -> tuple[int, bytes, Mapping[str, str]]:
    response = urllib3.request(
        "DELETE", url, body=b"", headers=headers,
        timeout=urllib3.Timeout(connect=10, read=30), retries=False,
    )
    return response.status, response.data, response.headers


def _delete_orphan(monitor_id: str, *, api_key: str, delete: Delete) -> None:
    """Best-effort cleanup for a monitor the create call already made, that a
    pre-flight check then refused. A failure here must never mask the
    original refusal -- the caller puts the id in its own exception message
    so the orphan is recoverable by hand if this also fails."""
    if not monitor_id:
        return
    try:
        status, _raw, _headers_out = delete(f"{_BASE}/monitor/{monitor_id}", _headers(api_key))
    except urllib3.exceptions.HTTPError:
        logger.warning("could not delete orphaned monitor %s (transport error)", monitor_id)
        return
    if status not in (200, 204):
        logger.warning("could not delete orphaned monitor %s (HTTP %s)", monitor_id, status)


def create_monitor(
    *,
    api_key: str,
    name: str,
    targets: Sequence[dict[str, object]],
    already_committed: int = 0,
    reserve: int = 0,
    post: Post = _post,
    delete: Delete = _delete,
) -> MonitorCreated:
    """POST /v2/monitor. Refuses to create one the cycle cannot pay for.

    `estimatedCreditsPerMonth` comes back on the create call and is the only
    honest figure available before the first check runs. A monitor whose
    checks cannot be paid for reports `skipped_no_credits` forever, and from
    outside that is a site that never changes -- the silent staleness this
    cadence exists to remove.

    The vendor call above this docstring already CREATES the monitor -- the
    ceiling check that follows only decides whether to keep it. Refusing
    without a DELETE would abandon a monitor Firecrawl keeps checking (and
    charging for) forever, which is exactly the silent staleness the cadence
    exists to remove, just billed instead of stale. So both refusal branches
    below call `_delete_orphan` before raising, and the monitor id is folded
    into the exception message either way, so the orphan is recoverable by
    hand if the delete call itself fails.
    """
    payload = {
        "name": name,
        "targets": list(targets),
        "cron": MONITOR_CRON,
        "retentionDays": RETENTION_DAYS,
        # Off, deliberately, and `goal` is omitted with it: a goal with no
        # judge is a field the vendor ignores, and leaving it in would read
        # like the judge is doing something.
        "judgeEnabled": False,
    }
    document = _call("/monitor", payload, api_key=api_key, post=post)
    monitor_id = str(document.get("id") or "")
    estimate_raw = document.get("estimatedCreditsPerMonth")
    if not isinstance(estimate_raw, (int, float)):
        _delete_orphan(monitor_id, api_key=api_key, delete=delete)
        raise MonitorEstimateMissing(
            f"{name}: estimatedCreditsPerMonth missing or non-numeric on the "
            f"create response -- refusing to treat an unknown cost as free "
            f"(monitor {monitor_id or '<no id>'} created, delete attempted)"
        )
    estimate = int(estimate_raw)
    ceiling = int(settings.FIRECRAWL_MONTHLY_CREDITS) - reserve
    if already_committed + estimate > ceiling:
        _delete_orphan(monitor_id, api_key=api_key, delete=delete)
        raise MonitorBudgetExceeded(
            f"{name}: {estimate} credits/month would take the cycle to "
            f"{already_committed + estimate} of {ceiling} "
            f"(monitor {monitor_id or '<no id>'} created, delete attempted)"
        )
    return MonitorCreated(monitor_id=monitor_id, estimated_credits_per_month=estimate)


def list_checks(
    *, api_key: str, monitor_id: str, get: Get = _get
) -> tuple[CheckPage, ...]:
    """GET /v2/monitor/{id}/checks -- the delivery path until a public HTTPS
    endpoint exists. Polling costs no credits.

    A check with `skipped_no_credits` yields no pages and is NOT an error: it
    resumes when credits do, and a monitor reported as failing gets disabled
    by whoever is on call -- a disabled monitor is a site that stops being
    watched.
    """
    document = _get_json(
        f"https://api.firecrawl.dev/v2/monitor/{monitor_id}/checks",
        _headers(api_key),
        get=get,
    )
    pages: list[CheckPage] = []
    checks_raw = document.get("checks")
    for check in checks_raw if isinstance(checks_raw, list) else []:
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "")
        for page in check.get("pages") or []:
            if isinstance(page, dict) and page.get("url"):
                pages.append(
                    CheckPage(
                        url=str(page["url"]),
                        status=str(page.get("status") or ""),
                        check_id=check_id,
                    )
                )
    return tuple(pages)
