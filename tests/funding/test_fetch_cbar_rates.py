from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.funding.fx import convert
from apps.funding.management.commands import fetch_cbar_rates
from apps.funding.models import ExchangeRate
from apps.funding.rates import BAKU, latest_table
from apps.research.egress import FetchResult, SourceBlocked
from apps.watch.models import JobRun

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"


def _fetcher(asked, ecb=None):
    def fetch(url: str, *, require_https: bool) -> FetchResult:
        asked.append((url, require_https))
        if "ecb.europa.eu" in url:
            if ecb is None:
                raise SourceBlocked("HTTP 503")
            body = ecb
        else:
            body = (FIXTURES / "cbar_daily.xml").read_bytes()
        return FetchResult(final_url=url, redirects=(), content_type="text/xml", body=body)

    return fetch


def test_the_command_stores_both_tables_and_records_its_run(monkeypatch) -> None:
    asked: list[tuple[str, bool]] = []
    ecb = (FIXTURES / "ecb_daily.xml").read_bytes()
    monkeypatch.setattr(fetch_cbar_rates, "fetch_data_file", _fetcher(asked, ecb))

    call_command("fetch_cbar_rates")

    today = timezone.localdate(timezone=BAKU)
    assert asked == [
        (f"https://www.cbar.az/currencies/{today:%d.%m.%Y}.xml", True),
        ("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", True),
    ]
    table = latest_table(on=date(2026, 8, 14))
    assert table.retrieved_on == date(2026, 8, 14)
    assert convert(Decimal("100.00"), "EUR", "AZN", table) == Decimal("196.15")
    assert "MYR" in table.cross
    assert ExchangeRate.objects.filter(base="EUR", source="ECB", currency="MYR").exists()
    assert JobRun.objects.filter(name="fetch_cbar_rates").exists()


def test_an_ecb_failure_keeps_the_cbar_rows_and_records_no_run(monkeypatch) -> None:
    monkeypatch.setattr(fetch_cbar_rates, "fetch_data_file", _fetcher([]))

    with pytest.raises(SourceBlocked):
        call_command("fetch_cbar_rates")

    assert ExchangeRate.objects.filter(base="AZN").exists()
    assert not ExchangeRate.objects.filter(base="EUR").exists()
    assert not JobRun.objects.filter(name="fetch_cbar_rates").exists()


def test_a_failed_fetch_stores_nothing_and_records_no_run(monkeypatch) -> None:
    """The heartbeat notices a missing run within 26 hours; a run recorded
    after a failure would hide exactly that."""

    def refuse(url: str, *, require_https: bool) -> FetchResult:
        raise SourceBlocked("HTTP 503")

    monkeypatch.setattr(fetch_cbar_rates, "fetch_data_file", refuse)

    with pytest.raises(SourceBlocked):
        call_command("fetch_cbar_rates")

    assert not ExchangeRate.objects.exists()
    assert not JobRun.objects.filter(name="fetch_cbar_rates").exists()
