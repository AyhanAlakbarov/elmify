from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.funding.fx import RateTable
from apps.funding.rates import latest_table, store
from apps.research.management.commands import run_research_worker
from apps.research.schemas import ResearchMessage

pytestmark = pytest.mark.django_db

TABLE = RateTable(
    base="AZN",
    rates={"AZN": Decimal("1"), "EUR": Decimal("0.5")},
    source="CBAR",
    retrieved_on=date(2026, 1, 8),
)


def _seen(monkeypatch) -> dict[str, object]:
    seen: dict[str, object] = {}

    def handle(message: ResearchMessage, *, rates: RateTable | None = None) -> None:
        seen["rates"] = rates

    monkeypatch.setattr(run_research_worker, "handle_research_message", handle)
    return seen


def _message() -> ResearchMessage:
    return ResearchMessage(kind="run_research", tenant_id=uuid4(), run_id=uuid4())


def test_the_worker_builds_packs_with_the_latest_stored_rates(monkeypatch) -> None:
    """Before this, `_handle` passed nothing, so a deployed worker published
    the "No exchange-rate table is loaded" pack for every student."""
    store(TABLE)
    seen = _seen(monkeypatch)

    run_research_worker._handle(_message())

    assert seen["rates"] == latest_table()
    assert seen["rates"].retrieved_on == date(2026, 1, 8)


def test_on_the_first_day_the_worker_passes_no_table(monkeypatch) -> None:
    seen = _seen(monkeypatch)

    run_research_worker._handle(_message())

    assert seen["rates"] is None
