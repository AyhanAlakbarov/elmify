"""run_area_sweeps (item 14 Task 12) and the funder-sweep switch."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.research.models import AreaSweep, SweepRun
from apps.research.tap_seams import SweepOutcome

pytestmark = pytest.mark.django_db

HELD = "funder level check not live (card reader slice 3)"


class _Sweeper:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float]] = []
        self.run_id = None

    def run(self, country, family, *, budget_usd):
        self.calls.append((country, family, budget_usd))
        run = SweepRun.objects.create(
            country_code=country, family=family, languages=["en"], rung=4,
            cycle="2026-2027", started_at=timezone.now(),
        )
        return SweepOutcome(7, Decimal("0.5"), 3, "PLATEAU", run.id)


@pytest.fixture
def live(settings):
    settings.FUNDER_SWEEP_LEVEL_CHECK_LIVE = True


def test_sweeps_run_in_demand_order_and_each_is_bounded(live, settings) -> None:
    AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION", demand=1)
    AreaSweep.objects.create(country_code="DE", family="INDUSTRIAL_SPONSORSHIP", demand=5)
    sweeper = _Sweeper()
    call_command("run_area_sweeps", "--limit", "1", sweeper=sweeper)
    assert sweeper.calls == [("DE", "INDUSTRIAL_SPONSORSHIP", settings.CELL_SWEEP_BUDGET_USD)]
    done = AreaSweep.objects.get(country_code="DE")
    assert (done.state, done.provider_calls, done.cost_usd, done.new_hosts, done.stop_reason) == (
        "DONE", 7, Decimal("0.5"), 3, "PLATEAU")
    assert done.finished_at is not None and done.sweep_run is not None
    assert AreaSweep.objects.get(country_code="AZ").state == "QUEUED"


def test_no_sweeper_marks_the_row_unavailable_not_done(live) -> None:
    row = AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION")
    call_command("run_area_sweeps", "--limit", "1", sweeper=SimpleNamespace(
        run=lambda *a, **k: None))
    row.refresh_from_db()
    assert row.state == "UNAVAILABLE" and row.stop_reason


def test_the_area_sweep_never_imports_the_tap_query_module() -> None:
    import inspect

    import apps.research.management.commands.run_area_sweeps as cmd

    assert "tap_query" not in inspect.getsource(cmd)  # the cell pass is profile-free (spec 6.7)


def test_a_funder_row_stays_queued_while_the_level_check_is_not_live(settings) -> None:
    settings.FUNDER_SWEEP_LEVEL_CHECK_LIVE = False
    row = AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION")
    sweeper = _Sweeper()
    call_command("run_area_sweeps", sweeper=sweeper)
    row.refresh_from_db()
    assert row.state == "QUEUED" and sweeper.calls == []


def test_a_sweeper_exception_leaves_the_row_unavailable_and_the_next_row_runs(live) -> None:
    bad = AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION", demand=9)
    good = AreaSweep.objects.create(country_code="DE", family="INDUSTRIAL_SPONSORSHIP", demand=1)
    real = _Sweeper()

    class Flaky:
        def run(self, country, family, *, budget_usd):
            if country == "AZ":
                raise RuntimeError("provider down")
            return real.run(country, family, budget_usd=budget_usd)

    call_command("run_area_sweeps", sweeper=Flaky())
    bad.refresh_from_db()
    good.refresh_from_db()
    assert (bad.state, bad.stop_reason) == ("UNAVAILABLE", "error: RuntimeError")
    assert good.state == "DONE"


def test_a_harness_refusal_gives_unavailable(live) -> None:
    row = AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION")
    call_command("run_area_sweeps", sweeper=SimpleNamespace(run=lambda *a, **k: None))
    row.refresh_from_db()
    assert row.state == "UNAVAILABLE"


def test_a_diaspora_row_is_unavailable_without_calling_the_sweeper(live) -> None:
    row = AreaSweep.objects.create(country_code="DE", family="AFFINITY_OR_DIASPORA")
    sweeper = _Sweeper()
    call_command("run_area_sweeps", sweeper=sweeper)
    row.refresh_from_db()
    assert row.state == "UNAVAILABLE" and sweeper.calls == []
    assert row.stop_reason == (
        "diaspora area needs a home language, which area rows do not carry")


def _untouched() -> bool:
    return AreaSweep.objects.filter(state="QUEUED").count() == 1


def test_a_connection_that_cannot_write_the_catalogue_is_refused(live, monkeypatch) -> None:
    AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION")
    monkeypatch.setattr(
        "apps.research.management.commands.run_area_sweeps.can_write_catalogue", lambda: False)
    with pytest.raises(CommandError, match="runtime_engine"):
        call_command("run_area_sweeps", sweeper=_Sweeper())
    assert _untouched()


def test_no_provider_key_is_refused_before_any_row_changes(live, settings, monkeypatch) -> None:
    AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION")
    settings.EXA_API_KEY = settings.BRAVE_API_KEY = ""
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    with pytest.raises(CommandError, match="no provider key"):
        call_command("run_area_sweeps")
    assert _untouched()


def test_no_openai_key_is_refused_before_any_row_changes(live, settings, monkeypatch) -> None:
    AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION")
    settings.EXA_API_KEY, settings.BRAVE_API_KEY = "k", ""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(CommandError, match="OPENAI_API_KEY"):
        call_command("run_area_sweeps")
    assert _untouched()


def test_sweep_organisations_refuses_a_funder_family_while_not_live(settings) -> None:
    settings.FUNDER_SWEEP_LEVEL_CHECK_LIVE = False
    with pytest.raises(CommandError, match="card reader slice 3"):
        call_command("sweep_organisations", "--country", "AZ", "--family", "PRIVATE_FOUNDATION")


def test_sweep_organisations_runs_while_live(settings, capsys) -> None:
    settings.FUNDER_SWEEP_LEVEL_CHECK_LIVE = True
    settings.EXA_API_KEY, settings.BRAVE_API_KEY = "k", ""
    call_command("sweep_organisations", "--country", "AZ", "--family", "PRIVATE_FOUNDATION",
                 "--language", "az", "--dry-run")
    assert "would sweep AZ/PRIVATE_FOUNDATION" in capsys.readouterr().out
