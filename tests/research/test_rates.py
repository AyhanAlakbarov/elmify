"""The worker's exchange-rate table: CBAR first, the ECB second, never invented."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.research import rates
from apps.research.egress import FetchResult, SourceBlocked

TODAY = date(2026, 10, 26)  # a Monday

CBAR = b"""<?xml version="1.0" encoding="UTF-8"?>
<ValCurs Date="26.10.2026" Name="AZN">
  <ValType Type="Xarici valyutalar">
    <Valute Code="USD"><Nominal>1</Nominal><Name>1 ABS dollari</Name><Value>1.7</Value></Valute>
    <Valute Code="EUR"><Nominal>1</Nominal><Name>1 Avro</Name><Value>1.9</Value></Valute>
    <Valute Code="KZT"><Nominal>100</Nominal><Name>100 tenge</Name><Value>0.33</Value></Valute>
  </ValType>
</ValCurs>"""

ECB = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
  xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube time="2026-10-26"><Cube currency="USD" rate="1.09"/></Cube></Cube>
</gesmes:Envelope>"""


def _fetcher(answers: dict[str, bytes]):  # type: ignore[no-untyped-def]
    asked: list[str] = []

    def fetch(url: str, **_kwargs: object) -> FetchResult:
        asked.append(url)
        if url not in answers:
            raise SourceBlocked("source returned HTTP 404")
        return FetchResult(url, (), "text/xml", answers[url])

    fetch.asked = asked  # type: ignore[attr-defined]
    return fetch


@pytest.fixture(autouse=True)
def _empty_cache() -> None:
    cache.delete(rates.CACHE_KEY)


def test_cbar_is_used_first_and_covers_regional_currencies() -> None:
    fetch = _fetcher({rates.CBAR_URL.format(day=TODAY): CBAR})
    table = rates.load_rates(fetch=fetch, today=TODAY)
    assert table is not None
    assert table.source == "CBAR"
    assert table.rates["KZT"] == Decimal("0.0033")
    assert fetch.asked == [rates.CBAR_URL.format(day=TODAY)]  # the ECB is never asked


def test_a_day_without_a_cbar_file_steps_back() -> None:
    friday = date(2026, 10, 23)
    fetch = _fetcher({rates.CBAR_URL.format(day=friday): CBAR.replace(b"26.10", b"23.10")})
    table = rates.load_rates(fetch=fetch, today=TODAY)
    assert table is not None and table.retrieved_on == friday


def test_the_ecb_is_the_fallback() -> None:
    table = rates.load_rates(fetch=_fetcher({rates.ECB_URL: ECB}), today=TODAY)
    assert table is not None and table.source == "ECB"


def test_nothing_answering_is_none_never_a_made_up_table() -> None:
    assert rates.load_rates(fetch=_fetcher({}), today=TODAY) is None


def test_a_stale_table_is_refused() -> None:
    old = ECB.replace(b"2026-10-26", b"2026-09-01")
    assert rates.load_rates(fetch=_fetcher({rates.ECB_URL: old}), today=TODAY) is None


def test_the_table_is_cached_between_runs() -> None:
    fetch = _fetcher({rates.CBAR_URL.format(day=TODAY): CBAR})
    first = rates.current_rates(fetch=fetch, today=TODAY)
    second = rates.current_rates(fetch=_fetcher({}), today=TODAY)
    assert first == second
    assert second is not None and second.rates["EUR"] == Decimal("1.9")
