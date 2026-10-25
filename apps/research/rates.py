"""Today's exchange-rate table for the research worker.

Until this module, `handle_research_message` was always called with
``rates=None`` on a deployed worker, so every pack came out empty with "No
exchange-rate table is loaded" (spine.build_student_pack). The parsers in
``funding.rate_sources`` existed; nothing fetched anything for them.

Two official sources, in order:

1. **CBAR** (Central Bank of Azerbaijan), base AZN. Covers the region's
   currencies (KZT, UZS, GEL, TRY, CNY, KRW...) as well as EUR/USD/GBP, which
   the ECB does not: a student's budget in AZN or KZT is the common case.
2. **ECB** euro reference rates, base EUR, as the fallback.

Rates are data files, fetched as bytes through ``egress.fetch_data_file``
(CLAUDE.md, "Web fetching": a file meant to be parsed as data is never a page).
A failure returns ``None`` -- never a made-up table -- and the spine then
publishes its loud empty pack, exactly as before. A table older than
``MAX_AGE_DAYS`` is refused for the same reason: a confident wrong gap is worse
than none.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache

from apps.funding.fx import RateTable
from apps.funding.rate_sources import parse_cbar_daily, parse_ecb_daily

from .egress import FetchResult, SourceBlocked, UnsafeTarget, fetch_data_file

logger = logging.getLogger(__name__)

CBAR_URL = "https://www.cbar.az/currencies/{day:%d.%m.%Y}.xml"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
#: CBAR publishes no file for some days (weekends, holidays): step back this far.
CBAR_LOOKBACK_DAYS = 4
#: Older than this, a table is not used at all.
MAX_AGE_DAYS = 7
CACHE_KEY = "research:rate-table:v1"
CACHE_SECONDS = 6 * 3600

Fetch = Callable[..., FetchResult]


def _encode(table: RateTable) -> str:
    return json.dumps(
        {
            "base": table.base,
            "rates": {code: str(rate) for code, rate in table.rates.items()},
            "source": table.source,
            "retrieved_on": table.retrieved_on.isoformat(),
        }
    )


def _decode(raw: str) -> RateTable:
    data = json.loads(raw)
    return RateTable(
        base=str(data["base"]),
        rates={str(code): Decimal(rate) for code, rate in data["rates"].items()},
        source=str(data["source"]),
        retrieved_on=date.fromisoformat(data["retrieved_on"]),
    )


def _fresh(table: RateTable, today: date) -> bool:
    return (today - table.retrieved_on).days <= MAX_AGE_DAYS


def _from_cbar(fetch: Fetch, today: date) -> RateTable | None:
    for back in range(CBAR_LOOKBACK_DAYS + 1):
        day = today - timedelta(days=back)
        try:
            result = fetch(CBAR_URL.format(day=day), require_https=True)
            return parse_cbar_daily(result.body)
        except (SourceBlocked, UnsafeTarget, ValueError) as error:
            logger.info("CBAR rates for %s unavailable: %s", day.isoformat(), error)
    return None


def _from_ecb(fetch: Fetch) -> RateTable | None:
    try:
        return parse_ecb_daily(fetch(ECB_URL, require_https=True).body)
    except (SourceBlocked, UnsafeTarget, ValueError) as error:
        logger.warning("ECB rates unavailable: %s", error)
        return None


def load_rates(*, fetch: Fetch = fetch_data_file, today: date | None = None) -> RateTable | None:
    """Fetch a fresh table from CBAR, else the ECB. No cache; see `current_rates`."""
    day = today or date.today()
    table = _from_cbar(fetch, day)
    if table is not None and _fresh(table, day):
        return table
    # Asked only when CBAR had nothing fresh.
    table = _from_ecb(fetch)
    if table is not None and _fresh(table, day):
        return table
    logger.warning("no fresh exchange-rate table from CBAR or the ECB")
    return None


def current_rates(*, fetch: Fetch = fetch_data_file, today: date | None = None) -> RateTable | None:
    """The table the worker uses, cached for six hours between runs."""
    today = today or date.today()
    try:
        cached = cache.get(CACHE_KEY)
    except Exception:  # a cache outage must not stop a pack; fetch instead
        logger.warning("rate cache unavailable", exc_info=True)
        cached = None
    if cached is not None:
        try:
            table = _decode(cached)
        except (ValueError, KeyError, TypeError):
            table = None
        if table is not None and _fresh(table, today):
            return table
    table = load_rates(fetch=fetch, today=today)
    if table is not None:
        try:
            cache.set(CACHE_KEY, _encode(table), CACHE_SECONDS)
        except Exception:
            logger.warning("rate cache unavailable", exc_info=True)
    return table
