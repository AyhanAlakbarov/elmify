"""Diffbot Knowledge Graph Enhance -- the resolver's residue rung (spec 6.5).

A resolver, never a classifier and never an enumerator: its categories are
wrong (Cusanuswerk -> "Software Companies") and its confidence runs 0.16-0.54
even when right, so its answer is one URL that takes the same title check as
any search candidate. Nothing else in the response is read or kept --
the confidence included; spec 15's "Diffbot confidence threshold on the next
50" is measured by the gate, not stored on a row.

Organisations only, enforced here rather than by convention: the Knowledge
Graph holds PEOPLE as entities, and its terms bar using the data "in any
manner that violates the rights of any person" (2026-09-17 recon, section 1).
So the request is pinned to `type=Organization` and an entity the response
labels as anything else is skipped, not read.

The token travels as a query parameter, so an exception raised under it is
re-raised without its cause: urllib3 errors print the request path.

The response shape (`data[].entity.homepageUri`) is the DOCUMENTED one: no
token existed when this was written, so the test fixture is hand-built and a
live capture is owed before the rung is trusted.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

from ..egress import SourceBlocked, fetch_json_api
from .base import ProviderUnavailable

DIFFBOT_ENHANCE_URL = "https://kg.diffbot.com/kg/v3/enhance"
#: The one entity type ever asked for or read.
_ORGANIZATION = "Organization"
#: Free tier: 5 calls a minute.
_MIN_INTERVAL = 12.0
#: Diffbot's terms carry no effective date, so they are re-read on this cycle
#: (spec 6.2) -- every caller, checked once, here, rather than pasted at each
#: command that spends an entity.
_TERMS_FRESH = timedelta(days=31)


class DiffbotEnhance:
    def __init__(
        self,
        *,
        token: str,
        get: Callable[..., dict[str, object]] = fetch_json_api,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        terms_read_on: str | None = None,
        today: date | None = None,
    ) -> None:
        """`terms_read_on`/`today` default to `settings.DIFFBOT_TERMS_READ_ON`
        and the real date; both are overridable for a test that does not want
        to patch settings or the clock."""
        read_on_raw = settings.DIFFBOT_TERMS_READ_ON if terms_read_on is None else terms_read_on
        try:
            read_on = date.fromisoformat(read_on_raw)
        except ValueError:
            read_on = date.min
        now = today or timezone.now().date()
        # A future date is a typo or a pre-dated promise, never a reading.
        if read_on > now or now - read_on > _TERMS_FRESH:
            raise ValueError("Diffbot's terms carry no effective date; re-read them and "
                             "set DIFFBOT_TERMS_READ_ON (spec 6.2)")
        self._token, self._get, self._sleep, self._clock = token, get, sleep, clock
        self._last: float | None = None

    def __repr__(self) -> str:
        return "DiffbotEnhance(token=***)"

    def homepage(self, name: str) -> str:
        """The first organisation entity's homepage as a URL, or "" for none."""
        now = self._clock()
        if self._last is not None and now - self._last < _MIN_INTERVAL:
            wait = _MIN_INTERVAL - (now - self._last)
            self._sleep(wait)
            now += wait
        self._last = now
        try:
            data = self._get(DIFFBOT_ENHANCE_URL, params={
                "token": self._token, "type": _ORGANIZATION, "name": name,
            }, headers={})
        except (SourceBlocked, ValueError):
            # ValueError covers UnsafeTarget and a body that is not JSON; none
            # of them may carry the token out in a chained cause.
            raise ProviderUnavailable("diffbot enhance failed") from None
        items = data.get("data")
        for item in items if isinstance(items, list) else []:
            entity = item.get("entity") if isinstance(item, dict) else None
            if not isinstance(entity, dict):
                continue
            if entity.get("type", _ORGANIZATION) != _ORGANIZATION:
                continue
            uri = str(entity.get("homepageUri") or "").strip()
            if uri:
                return uri if "//" in uri else f"https://{uri}"
        return ""
