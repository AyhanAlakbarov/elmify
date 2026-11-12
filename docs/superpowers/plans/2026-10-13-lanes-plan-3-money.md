# Lanes Plan 3 — Money Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the Central Bank of Azerbaijan's daily rates and build packs with them. Keep over-budget programmes in the pool with their rank. Give every application a fee state the student (or a trusted receipt email) can mark paid. Show each amount as "original ≈ AZN", the "at risk" line, the budget line, the student-only budget and stretch, and "New for you".

**Architecture:**
- Rates are a non-tenant table (`funding.ExchangeRate`) written once a day by a worker command and read back as the `RateTable` that `apps/funding/fx.py` already converts with. The research worker builds packs from the newest stored day; the board converts at render time.
- Money on the board is computed on every view, never stored: `apps/dashboard/money.py` is pure (amounts, the position line, the budget line) and `board_for` stays the one querying function.
- The budget lives in the profile, as today. Changing it writes a new profile version through `create_profile_version`; nothing re-runs research. "New for you" is computed from the current pack's run against the new budget.
- Everything that depends on data plans 1b and 2b have not written yet (award result dates, fee deadlines, cascades, rounds) is listed under "Deferred to plan 3b" and is not built here.

**Tech Stack:** Django 5.2 views and plain templates, frozen dataclasses, pydantic `Money` / `StudentProfileSnapshot` (`apps/accounts/schemas.py`), `defusedxml` (already used by `rate_sources.py`), CloudFormation (`infra/template.yaml`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-programme-lanes-and-money-design.md`. Plan 3 covers §7.1 (the Safe and Pay-first positions), §7.4 (unknown and paid fees), §7.5 (the budget line), §7.6, §7.7, §7.8, §7.9, the §3.2 fee fields, and §15's money tests.

## Scope ruling: plan 3 now, plan 3b later

Plan 3 builds what today's data supports. Nothing writes an award's `results_date` or a step's `fee_deadline` yet (plan 1b), and the §6 cascades are plan 2b.

**Deferred to plan 3b**, each blocked on the data named:

| Spec | Deferred item | Blocked on |
|---|---|---|
| §7.1–§7.3 | The fee hold: `HELD` / `RELEASED`, `fee_held_until`, "Apply now anyway", the last-safe-day item "Result not in yet — pay now or skip", and the "Wait, then pay" position | An award `results_date` and a step `fee_deadline` (plan 1b), and the §6 cascades (plan 2b), without which a held fee never unlocks on a result. `HELD` and `RELEASED` exist as `fee_state` values; nothing sets them. |
| §7.4 | One fee per round | `portal_system.one_fee_per_round` (plan 1b) and rounds (§8, plan 2b). |
| §7.4 | "A fee waiver may apply" | An award's `pays=fee_reduction` (plan 1b). |
| §7.5 | The lane money line per year | Won awards (`funding_outcome`, plan 2b) and renewal conditions (the award copy, plan 1b). |
| §7.7 | Stretch reason 3: MANDATORY funding and a verified funding route the plan doesn't already cover | Verified routes are §3.4 data (plan 1b). Reasons 1 (fully funded) and 2 (ranks above the last paid item) are built here. |
| §7.9 | "A fee-free item found or published later" as a trigger | The catalogue refresh flow. The computed New-for-you list already shows any such candidate once it exists in the current run. |

## Global Constraints

- **Gates:**
  - tests: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider` (this worktree's own DB name; never run two suites on one DB);
  - lint: `uv run ruff check .`, never `ruff format`;
  - types: `uv run mypy apps config`;
  - Django: `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run`;
  - security: `uv run bandit -c pyproject.toml -r apps config`.
- **Git:** run every git command as `git -C /home/orkhan/Desktop/lanes-plan-3 …`, because the shell's cwd resets to the main repo. Never push to master. Never hand-edit `uv.lock` or an applied migration. No new dependency.
- **Reads:** the web tier reads tenant tables only, plus `funding_exchangerate` (non-tenant, deliberately web-readable, never web-writable). Every board and page test runs inside `reads_no_catalogue()` (`tests/conftest.py:572`). Never read `candidate.program` or `candidate.opportunity`; `*_id` access is fine.
- **Only the student** sets the budget, marks a fee paid, adds a stretch item, and adds an over-budget programme (on the confirmation page) (owner). A counsellor's over-budget add is refused (Task 8). The counsellor sees the budget read-only: no edit or propose control, and `action_url(counselor_view=True, …)` returns "" for every money action.
- **Amounts:** each amount is the original currency first, then "≈ N AZN". Totals and the budget are in AZN only. The rate appears only as a note: "Converted at the CBAR rate of 8 Oct; your bank may charge more".
- **An unknown fee** is "Fee not known yet" and "not counted", never 0.
- **Untrusted mail never changes `fee_state`** (spec §15).
- **Every new field** is classified in `apps/audit/redaction.py`.
- **Student words:** Scholarship, Tuition waiver, Discount, Assistantship. Never "award", "HOLDER", "scope" or route codes in student-facing text, and never "not stated" (verified-catalog §5.5).
- **Tests never reach the network:** the CBAR fetch is stubbed at `fetch_data_file`.

## Review Focus

1. **A fee in a currency the CBAR table lacks** (ISK, say): the card shows "120.00 ISK" alone, never a guessed AZN figure, and the budget line says "1 fee without a rate yet — not counted". Pinned in Task 4 (`approx`) and Task 5 (`budget_line`).
2. **The first day, before any rate row exists:** the research worker passes `rates=None` and publishes the existing "No exchange-rate table is loaded" pack. The board shows original currencies only and no rate note. Pinned in Task 1 (the worker) and Task 4 (the board with no rows).
3. **A budget in EUR, not AZN:** the budget line converts it and shows "Application budget 500 AZN … (≈, see note)". With no rate table it shows nothing rather than a wrong figure. Pinned in Task 5.
4. **A paid fee, then the budget lowered below it:** the change is refused, naming the paid figure, and no profile version is written. Pinned in Task 7.
5. **Two tabs racing the "I've paid this fee" POST:** one `PAID`, one `AuditEvent`, and the second request is told it is already marked. Pinned in Task 3.

---

### Task 1: Daily CBAR rates, stored and used

**Files:**
- Modify: `apps/funding/rate_sources.py` (`parse_cbar_daily`: invert the quote)
- Modify: `tests/funding/test_rate_sources.py` (the JPY assertion; a direction test)
- Modify: `apps/funding/models.py` (new `ExchangeRate`, at module level after `PackCandidate`)
- Create: `apps/funding/migrations/0060_exchangerate.py` (generated, then one `RunSQL` appended by hand — see Step 5; it is unapplied, so editing it is safe)
- Create: `apps/funding/rates.py`
- Create: `apps/funding/management/commands/fetch_cbar_rates.py`
- Modify: `apps/watch/heartbeat.py` (`EXPECTED_JOBS`), `tests/watch/test_heartbeat.py` (`test_every_scheduled_job_is_watched`)
- Modify: `infra/template.yaml` (`FetchCbarRatesRule` and its alarm, after `SyncMailboxesRuleFailedInvocationsAlarm` — see Step 7), `tests/infra/test_template.py`
- Modify: `apps/research/management/commands/run_research_worker.py` (`_handle`), `apps/research/services.py` (the `handle_research_message` docstring)
- Test: `tests/funding/test_rates.py`, `tests/funding/test_fetch_cbar_rates.py`, `tests/research/test_worker_rates.py`

**Interfaces:**
- Consumes: `apps.funding.fx.RateTable(base, rates, source, retrieved_on)`, `fx.convert`, `apps.funding.rate_sources.parse_cbar_daily(bytes) -> RateTable`, `apps.research.egress.fetch_data_file(url, *, require_https) -> FetchResult` (`.body: bytes`), `apps.watch.heartbeat.record_run(name)`, `report_silent()`.
- Produces:
  - `funding.ExchangeRate(day: date, base: str = "AZN", currency: str, rate: Decimal(30, 20), source: str = "CBAR")`, unique `(day, base, currency)`. `rate` is **units of `currency` per one unit of `base`** — the convention `RateTable.rates` and `fx.convert` already use.
  - `apps.funding.rates.BAKU: ZoneInfo`;
  - `apps.funding.rates.store(table: RateTable) -> int` (rows written; a second run for the same day overwrites);
  - `apps.funding.rates.latest_table(*, on: date | None = None, base: str = "AZN") -> RateTable | None` (the newest day `<= on`, default today in Baku; `None` when nothing is stored).
  - Management command `fetch_cbar_rates`; heartbeat job name `"fetch_cbar_rates"` (26 h).
  - `run_research_worker._handle` passes `rates=latest_table()`.

**Why the parser changes.** `fx.convert` reads `rates[c]` as "units of c per one base unit" (`in_base = amount / source_rate`); the ECB parser stores that. `parse_cbar_daily` stores CBAR's quote as written — AZN per unit — so `convert(100, "EUR", "AZN", cbar)` returns 50.98 instead of 196.15. It has no caller today; this task gives it one, so it is fixed first.

- [ ] **Step 1: Write the failing parser tests**

In `tests/funding/test_rate_sources.py`, add `from apps.funding.fx import convert` to the imports and replace `test_cbar_divides_by_nominal_for_rates_quoted_per_multiple_units` with:

```python
def test_cbar_divides_by_nominal_for_rates_quoted_per_multiple_units() -> None:
    table = parse_cbar_daily((FIXTURES / "cbar_daily.xml").read_bytes())

    # The fixture quotes 100 JPY = 1.0668 AZN.
    assert convert(Decimal("100"), "JPY", "AZN", table) == Decimal("1.07")


def test_a_cbar_table_converts_the_right_way_round() -> None:
    """CBAR quotes 1 EUR = 1.9615 AZN. Stored as quoted, fx.convert read
    100 EUR as 50.98 AZN -- inverted, off by a factor of almost four."""
    table = parse_cbar_daily((FIXTURES / "cbar_daily.xml").read_bytes())

    assert convert(Decimal("100.00"), "EUR", "AZN", table) == Decimal("196.15")
    assert convert(Decimal("196.15"), "AZN", "EUR", table) == Decimal("100.00")
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/funding/test_rate_sources.py`
Expected: FAIL — `Decimal('50.98') == Decimal('196.15')` and the JPY figure.

- [ ] **Step 3: Invert the quote in `parse_cbar_daily`**

In `apps/funding/rate_sources.py`, replace the two lines

```python
        divisor = Decimal(nominal) if nominal and nominal.strip().isdigit() else Decimal("1")
        rates[code] = Decimal(value) / divisor
```

with

```python
        divisor = Decimal(nominal) if nominal and nominal.strip().isdigit() else Decimal("1")
        quoted = Decimal(value)
        if quoted == 0:
            continue
        # CBAR quotes AZN per `nominal` units. RateTable holds units of the
        # currency per ONE base unit -- what fx.convert reads, and what the ECB
        # table holds -- so the quote is inverted, never stored as written.
        rates[code] = divisor / quoted
```

Run Step 2's command again. Expected: PASS (all five tests in the file).

- [ ] **Step 4: Write the failing storage tests**

`tests/funding/test_rates.py`:

```python
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from apps.funding.fx import RateTable, convert
from apps.funding.models import ExchangeRate
from apps.funding.rate_sources import parse_cbar_daily
from apps.funding.rates import latest_table, store

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"


def _table(day: date, eur: str = "0.5") -> RateTable:
    return RateTable(
        base="AZN",
        rates={"AZN": Decimal("1"), "EUR": Decimal(eur)},
        source="CBAR",
        retrieved_on=day,
    )


def test_a_stored_day_reads_back_as_the_same_table() -> None:
    assert store(_table(date(2026, 10, 8))) == 2

    table = latest_table(on=date(2026, 10, 8))

    assert table == _table(date(2026, 10, 8))
    assert convert(Decimal("100.00"), "EUR", "AZN", table) == Decimal("200.00")


def test_storing_a_day_twice_keeps_one_row_per_currency_with_the_newer_rate() -> None:
    store(_table(date(2026, 10, 8)))
    store(_table(date(2026, 10, 8), eur="0.4"))

    assert ExchangeRate.objects.filter(day=date(2026, 10, 8)).count() == 2
    assert latest_table(on=date(2026, 10, 8)).rates["EUR"] == Decimal("0.4")


def test_the_newest_day_on_or_before_the_date_is_used() -> None:
    store(_table(date(2026, 10, 6), eur="0.4"))
    store(_table(date(2026, 10, 8)))

    assert latest_table(on=date(2026, 10, 7)).retrieved_on == date(2026, 10, 6)
    assert latest_table(on=date(2026, 10, 9)).retrieved_on == date(2026, 10, 8)


def test_nothing_stored_is_none_not_an_empty_table() -> None:
    """The first day: the spine's "No exchange-rate table is loaded" pack is
    the honest answer, and an empty table would raise inside convert()."""
    assert latest_table() is None


def test_a_real_cbar_quote_survives_storage() -> None:
    store(parse_cbar_daily((FIXTURES / "cbar_daily.xml").read_bytes()))

    table = latest_table(on=date(2026, 8, 14))

    assert table.source == "CBAR"
    assert convert(Decimal("100.00"), "EUR", "AZN", table) == Decimal("196.15")
    assert convert(Decimal("100"), "JPY", "AZN", table) == Decimal("1.07")


def test_the_web_tier_may_read_rates_and_never_write_them(db_cursor) -> None:
    """Not tenant data, so no RLS: the grant is the guard. Default privileges
    gave runtime_web full DML when the table was made; 0060's RunSQL takes the
    writes back. `has_table_privilege` evaluates the NAMED role, so the superuser
    cursor is honest here (tests/tenancy/test_catalog_grants.py does the same)."""
    for privilege, web in (
        ("SELECT", True), ("INSERT", False), ("UPDATE", False), ("DELETE", False),
    ):
        db_cursor.execute(
            "SELECT has_table_privilege('runtime_web', 'public.funding_exchangerate', %s), "
            "has_table_privilege('runtime_engine', 'public.funding_exchangerate', %s)",
            [privilege, privilege],
        )
        assert db_cursor.fetchone() == (web, True), privilege
```

- [ ] **Step 5: Add the model, the migrations and `rates.py`**

In `apps/funding/models.py` (a plain `models.Model`, like `Program`; `uuid4` and `models` are already imported there):

```python
class ExchangeRate(models.Model):
    """One currency on one day's official table (lanes spec §7.6).

    Not tenant data: every agency reads the same CBAR rate, so there is no
    tenant column and no RLS. The web tier reads it -- the board converts at
    render time -- and only the worker's ``fetch_cbar_rates`` writes it;
    migration 0060 revokes runtime_web's writes so that stays true.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    day = models.DateField()
    base = models.CharField(max_length=3, default="AZN")
    currency = models.CharField(max_length=3)
    #: Units of ``currency`` per ONE unit of ``base`` -- RateTable.rates'
    #: convention, the one fx.convert reads (1 AZN = 0.51 EUR is stored 0.51).
    rate = models.DecimalField(max_digits=30, decimal_places=20)
    source = models.CharField(max_length=10, default="CBAR")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("day", "base", "currency"), name="exchange_rate_day_uniq"
            )
        ]
```

Generate: `cd /home/orkhan/Desktop/lanes-plan-3 && uv run python manage.py makemigrations funding -n exchangerate` (writes `0060_exchangerate.py`).

Then append one operation, by hand, to the END of the generated `operations` list in `0060_exchangerate.py` (after the `CreateModel`; the file is unapplied, so editing it is safe). One file rather than a separate `0061` keeps plan 4's numbering as written ("funding `0062` after plan 3"): plan 3 takes funding `0060` and `0061` only.

```python
        # The web tier reads exchange rates and never writes them (lanes spec
        # §7.6). funding_exchangerate is not tenant data and carries no RLS.
        # Default privileges (funding/0049) gave both runtime roles full DML on
        # it at the CreateModel above; only the worker's fetch_cbar_rates
        # writes, so runtime_web keeps SELECT and loses the rest. 0049 made sure
        # both roles exist, and it runs before this in the same app's chain.
        migrations.RunSQL(
            "REVOKE INSERT, UPDATE, DELETE ON public.funding_exchangerate FROM runtime_web;",
            "GRANT INSERT, UPDATE, DELETE ON public.funding_exchangerate TO runtime_web;",
        ),
```

`apps/funding/rates.py`:

```python
"""The daily official rates, stored and read back (lanes spec §7.6)."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from django.utils import timezone

from .fx import RateTable
from .models import ExchangeRate

#: CBAR publishes one table per Baku calendar day.
BAKU = ZoneInfo("Asia/Baku")


def store(table: RateTable) -> int:
    """Write one day's table. A second run for the same day overwrites it."""
    rows = [
        ExchangeRate(
            day=table.retrieved_on, base=table.base, currency=code, rate=rate, source=table.source
        )
        for code, rate in table.rates.items()
    ]
    ExchangeRate.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["day", "base", "currency"],
        update_fields=["rate", "source"],
    )
    return len(rows)


def latest_table(*, on: date | None = None, base: str = "AZN") -> RateTable | None:
    """The newest stored day on or before ``on`` (today in Baku), or None."""
    on = on or timezone.localdate(timezone=BAKU)
    day = (
        ExchangeRate.objects.filter(base=base, day__lte=on)
        .order_by("-day")
        .values_list("day", flat=True)
        .first()
    )
    if day is None:
        return None
    rows = list(
        ExchangeRate.objects.filter(base=base, day=day).values_list("currency", "rate", "source")
    )
    return RateTable(
        base=base,
        rates={currency: rate for currency, rate, _source in rows},
        source=rows[0][2],
        retrieved_on=day,
    )
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/funding/test_rates.py`
Expected: PASS.

- [ ] **Step 6: The command, test first**

`tests/funding/test_fetch_cbar_rates.py`:

```python
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


def test_the_command_stores_todays_table_and_records_its_run(monkeypatch) -> None:
    body = (FIXTURES / "cbar_daily.xml").read_bytes()
    asked: list[tuple[str, bool]] = []

    def fetch(url: str, *, require_https: bool) -> FetchResult:
        asked.append((url, require_https))
        return FetchResult(final_url=url, redirects=(), content_type="text/xml", body=body)

    monkeypatch.setattr(fetch_cbar_rates, "fetch_data_file", fetch)

    call_command("fetch_cbar_rates")

    today = timezone.localdate(timezone=BAKU)
    assert asked == [(f"https://www.cbar.az/currencies/{today:%d.%m.%Y}.xml", True)]
    table = latest_table(on=date(2026, 8, 14))
    assert table.retrieved_on == date(2026, 8, 14)
    assert convert(Decimal("100.00"), "EUR", "AZN", table) == Decimal("196.15")
    assert JobRun.objects.filter(name="fetch_cbar_rates").exists()


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
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/funding/test_fetch_cbar_rates.py`
Expected: FAIL — `cannot import name 'fetch_cbar_rates'`.

`apps/funding/management/commands/fetch_cbar_rates.py`:

```python
"""Fetch and store the Central Bank of Azerbaijan's official rates for today.

Invoked daily by FetchCbarRatesRule (infra/template.yaml). The research worker
builds every pack from the newest stored day, and the board converts with it
(lanes spec §7.6). A data file, so our own transport (egress.fetch_data_file),
never a page vendor. A failure raises and records no run: the heartbeat then
reports the job silent.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.funding.rate_sources import parse_cbar_daily
from apps.funding.rates import BAKU, store
from apps.research.egress import fetch_data_file
from apps.watch.heartbeat import record_run, report_silent

_URL = "https://www.cbar.az/currencies/{day:%d.%m.%Y}.xml"


class Command(BaseCommand):
    help = "Fetch today's CBAR official rates and store them"

    def handle(self, *_args: object, **_options: object) -> None:
        today = timezone.localdate(timezone=BAKU)
        result = fetch_data_file(_URL.format(day=today), require_https=True)
        stored = store(parse_cbar_daily(result.body))
        record_run("fetch_cbar_rates")
        report_silent()
        self.stdout.write(f"stored {stored} rates for {today:%d %b %Y}")
```

Run the command test again. Expected: PASS.

- [ ] **Step 7: The heartbeat and the schedule**

In `apps/watch/heartbeat.py`, add to `EXPECTED_JOBS`:

```python
    #: Daily; 26 h tolerates one late start (lanes spec §7.6).
    "fetch_cbar_rates": timedelta(hours=26),
```

In `tests/watch/test_heartbeat.py::test_every_scheduled_job_is_watched`, add `"fetch_cbar_rates": timedelta(hours=26),` to the expected dict.

In `infra/template.yaml`, insert after `SyncMailboxesRuleFailedInvocationsAlarm` (before the `ProvenanceRecheckRule` comment):

```yaml
  # Daily (lanes spec §7.6): the CBAR's official rates for the Baku day. The
  # research worker builds every pack from the newest stored day
  # (run_research_worker._handle); with none stored it publishes the "no
  # exchange-rate table" pack. The heartbeat expects it within 26 h
  # (apps/watch/heartbeat.py).
  FetchCbarRatesRule:
    Type: AWS::Events::Rule
    Properties:
      Description: Fetch and store the Central Bank of Azerbaijan's daily rates
      ScheduleExpression: "rate(1 day)"
      State: ENABLED
      Targets:
        - Id: fetch-cbar-rates
          Arn: !GetAtt ValidationCluster.Arn
          RoleArn: !GetAtt EventsInvokeEcsRole.Arn
          EcsParameters:
            TaskDefinitionArn: !Ref WorkerTaskDefinition
            LaunchType: FARGATE
            NetworkConfiguration:
              AwsVpcConfiguration:
                Subnets: [!Ref WorkerPrivateSubnetA, !Ref WorkerPrivateSubnetB]
                SecurityGroups: [!Ref WorkerSecurityGroup]
          Input: !Sub |
            {"containerOverrides":[{"name":"worker",
             "command":["python","manage.py","fetch_cbar_rates"]}]}

  FetchCbarRatesRuleFailedInvocationsAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: AWS/Events
      MetricName: FailedInvocations
      Dimensions:
        - Name: RuleName
          Value: !Ref FetchCbarRatesRule
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
```

In the `EventsInvokeEcsRole` policy comment (`# ReminderLadderRule, WatchApplicationsRule, SyncMailboxesRule,`), add `FetchCbarRatesRule` to the list of rules that run `WorkerTaskDefinition`.

In `tests/infra/test_template.py`, add `"FetchCbarRatesRule"` to the `@pytest.mark.parametrize("rule", [...])` list of `test_a_schedule_that_stops_invoking_sets_off_an_alarm`, and add:

```python
def test_the_cbar_rates_are_fetched_daily_by_the_worker(template: Template) -> None:
    """A rate table nothing fetches leaves every pack saying "No exchange-rate
    table is loaded", with every screen otherwise looking right."""
    rule = template.resource("FetchCbarRatesRule")["Properties"]
    assert rule["ScheduleExpression"] == "rate(1 day)"
    assert rule["State"] == "ENABLED"
    target = rule["Targets"][0]
    assert target["EcsParameters"]["TaskDefinitionArn"] == {"Ref": "WorkerTaskDefinition"}
    overrides = json.loads(target["Input"]["Fn::Sub"])["containerOverrides"][0]
    assert overrides == {"name": "worker", "command": ["python", "manage.py", "fetch_cbar_rates"]}
```

**Egress:** nothing to list. `scripts/validate_controlled_egress.py` is a boundary probe, not an allowlist, and `WorkerSecurityGroup` egress is `0.0.0.0/0` through the NAT.

- [ ] **Step 8: Wire the research worker, test first (Review Focus 2)**

`tests/research/test_worker_rates.py`:

```python
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
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/research/test_worker_rates.py`
Expected: FAIL on the first test (`None == RateTable(...)`).

In `apps/research/management/commands/run_research_worker.py`, add `from apps.funding.rates import latest_table` and change `_handle` to:

```python
def _handle(message: ResearchMessage) -> None:
    # The newest stored CBAR day (fetch_cbar_rates). None on the first day,
    # and the spine then publishes a pack that says so.
    handle_research_message(message, rates=latest_table())
```

In `apps/research/services.py::handle_research_message`'s docstring, replace the paragraph that begins "`rates` is injected and **has no production source yet**" with:

```python
    `rates` is the newest stored CBAR table (`funding.rates.latest_table`,
    passed by `run_research_worker._handle`). None means nothing is stored
    yet, and the spine publishes an empty pack saying so rather than
    comparing currencies with a table somebody made up.
```

- [ ] **Step 9: Run the tests and the gates**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/funding tests/research tests/watch tests/infra tests/tenancy`
Expected: PASS. Then `uv run ruff check . && uv run mypy apps config && uv run python manage.py check && uv run python manage.py makemigrations --check --dry-run`.

- [ ] **Step 10: Commit**

```bash
git -C /home/orkhan/Desktop/lanes-plan-3 add apps/funding/rate_sources.py apps/funding/models.py apps/funding/migrations/0060_exchangerate.py apps/funding/rates.py apps/funding/management/commands/fetch_cbar_rates.py apps/watch/heartbeat.py infra/template.yaml apps/research/management/commands/run_research_worker.py apps/research/services.py tests/funding/test_rate_sources.py tests/funding/test_rates.py tests/funding/test_fetch_cbar_rates.py tests/research/test_worker_rates.py tests/watch/test_heartbeat.py tests/infra/test_template.py
git -C /home/orkhan/Desktop/lanes-plan-3 commit -m "feat(funding): daily CBAR rates, stored, fetched by the worker and used to build packs (lanes §7.6)

parse_cbar_daily stored CBAR's quote the wrong way round for fx.convert; fixed first.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The pack — a 3% bank margin, and over-budget programmes kept in the pool with a rank

**Files:**
- Modify: `apps/funding/fx.py` (`BANK_MARGIN`)
- Modify: `apps/funding/pack.py` (`PackedApplication`, `Pack`, `build_pack`)
- Modify: `apps/funding/models.py` (`RecommendationCandidate.rank`)
- Create: `apps/funding/migrations/0061_recommendationcandidate_rank.py` (generated)
- Modify: `apps/research/services.py` (`_program_copy`, `_publish`)
- Modify: `apps/audit/redaction.py` (KEEP `rank`)
- Test: `tests/funding/test_ranking.py`, `tests/research/test_publish_pool.py`
- Modify: `tests/research/test_candidate_copies.py` (line 65 asserted a fee copy for the slice's programme, which states no fee; measured 2026-10-14, it fails once the copy is `None`)

**Interfaces:**
- Consumes: Task 1's tables (nothing else).
- Produces:
  - `apps.funding.fx.BANK_MARGIN = Decimal("1.03")`;
  - `PackedApplication` gains `rank: int | None = None` (1 = best, position in `rank_candidates` order) and `fee_known: bool = True` (False when the programme states no `APPLICATION_FEE`);
  - `Pack.over_budget: tuple[PackedApplication, ...] = ()`;
  - `RecommendationCandidate.rank: int | None` (`PositiveIntegerField(null=True, blank=True)`), written for every programme candidate `_publish` writes;
  - over-budget programmes become `RecommendationCandidate` rows with copies and provenance, and **no** `PackCandidate` row;
  - a programme with no stated fee is copied with `application_fee=None`, `application_fee_currency=""` (it used to be copied as 0.00, which reads as "no fee").

The spine needs no change: `SpineResult.programs` and `.origins` already hold every translated pool row, not only packed ones (`apps/research/spine.py`, the `programs[facts.program_id] = program` loop and `_origins(pool.programs, …)`).

- [ ] **Step 1: Write the failing pack tests**

Append to `tests/funding/test_ranking.py`:

```python
def test_a_fee_fits_only_with_three_percent_left_for_bank_charges() -> None:
    """Spec §7.6: a fee that fits only at the exact rate "may not fit". 100 USD
    is 92.17 EUR; 97 USD is 89.40 EUR and 92.08 with the margin, which fits;
    98 USD is 90.32 EUR and 93.03 with it, which does not."""
    profile = make_profile(application_budget={"amount": Decimal("100.00"), "currency": "USD"})
    fits = make_candidate(
        program_id="fits",
        cost_components=(make_cost("APPLICATION_FEE", "97.00", currency="USD", period="ONE_OFF"),),
    )
    tight = make_candidate(
        program_id="tight",
        cost_components=(make_cost("APPLICATION_FEE", "98.00", currency="USD", period="ONE_OFF"),),
    )

    assert [item.program_id for item in build_pack(profile, [fits], EUR_RATES).paid] == ["fits"]
    pack = build_pack(profile, [tight], EUR_RATES)
    assert pack.paid == ()
    assert [item.program_id for item in pack.over_budget] == ["tight"]
    assert [item.reason_code for item in pack.excluded] == ["APPLICATION_BUDGET_EXCEEDED"]


def test_the_budget_is_spent_at_the_plain_fee_not_the_margin() -> None:
    """The margin is a check, not a charge. 300 USD is 276.50 EUR; the first fee
    (97 USD, 89.40 EUR) leaves 187.10, and 180 EUR needs 185.40 with its
    margin. Spending the margin too would have left 184.42 and refused it."""
    profile = make_profile(
        strategy="FUNDING_FIRST",
        application_budget={"amount": Decimal("300.00"), "currency": "USD"},
    )
    first = make_candidate(
        program_id="first",
        cost_components=(make_cost("APPLICATION_FEE", "97.00", currency="USD", period="ONE_OFF"),),
    )
    second = make_candidate(
        program_id="second",
        cost_components=(make_cost("APPLICATION_FEE", "180.00", currency="EUR", period="ONE_OFF"),),
    )

    pack = build_pack(profile, [first, second], EUR_RATES)

    assert [item.program_id for item in pack.paid] == ["first", "second"]


def test_every_ranked_programme_carries_its_place_and_whether_its_fee_is_known() -> None:
    profile = make_profile(strategy="FUNDING_FIRST")
    stated = make_candidate(
        program_id="stated",
        cost_components=(make_cost("APPLICATION_FEE", "50.00", period="ONE_OFF"),),
    )
    silent = make_candidate(program_id="silent", cost_components=())

    pack = build_pack(profile, [stated, silent], EUR_RATES)

    assert [(i.program_id, i.rank, i.fee_known) for i in (*pack.fee_free, *pack.paid)] == [
        ("silent", 2, False),
        ("stated", 1, True),
    ]
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/funding/test_ranking.py`
Expected: FAIL — `'Pack' object has no attribute 'over_budget'`, `'PackedApplication' object has no attribute 'rank'`, and the plain-fee test passes already (it pins the decrement against Step 3).

- [ ] **Step 3: Implement the margin, the rank and the over-budget list**

In `apps/funding/fx.py`, after `round_money`:

```python
#: A fee fits the budget only with 3% left for bank charges (lanes spec §7.6).
#: One place: the pack, the board and New for you all read it.
BANK_MARGIN = Decimal("1.03")
```

In `apps/funding/pack.py`:
- change the import to `from apps.funding.fx import BANK_MARGIN, RateTable, convert`;
- add two fields at the end of `PackedApplication`:

```python
    #: Place in rank_candidates order, 1 = best. The pool's order for "New for
    #: you" and the stretch rule "ranks above the last paid item" (spec §7.7).
    rank: int | None = None
    #: False when the programme states no application fee. Its fee then arrives
    #: as 0.00 from affordability, which is "not known", never "no fee" (§7.4).
    fee_known: bool = True
```

- add a field at the end of `Pack`:

```python
    #: Ranked and eligible, refused only by the application budget. Kept so the
    #: worker writes them into the pool (never the pack): a raised budget or a
    #: stretch offers them as "New for you" (spec §7.8, §7.9). Each also stays in
    #: `excluded` as APPLICATION_BUDGET_EXCEEDED, so coverage reads it unchanged.
    over_budget: tuple[PackedApplication, ...] = ()
```

- in `build_pack`, replace the loop from `fee_free: list[PackedApplication] = []` down to the end of the `for item in ranked:` loop with:

```python
    fee_free: list[PackedApplication] = []
    paid: list[PackedApplication] = []
    over_budget: list[PackedApplication] = []
    budget_remaining = convert(
        profile.application_budget.amount,
        profile.application_budget.currency,
        rates.base,
        rates,
    )
    for position, item in enumerate(ranked, start=1):
        candidate = by_id[item.program_id]
        fee = item.affordability.application_fee
        currency = item.affordability.application_fee_currency
        ordering, reason = _ordering_for(candidate)
        # The fee is quoted in the destination's currency and the budget in the student's,
        # so budgeting compares them in the base currency while the packed figure stays
        # the amount actually payable.
        fee_in_base = convert(fee, currency, rates.base, rates)
        packed = PackedApplication(
            candidate.program_id,
            fee,
            currency,
            item.affordability.gap,
            item.affordability.currency,
            ordering,
            reason,
            rank=position,
            fee_known=any(c.kind == "APPLICATION_FEE" for c in candidate.cost_components),
        )
        if fee == 0:
            fee_free.append(packed)
        elif fee_in_base * BANK_MARGIN <= budget_remaining:
            paid.append(packed)
            # The margin is a check, not a charge: the budget is spent at the fee.
            budget_remaining -= fee_in_base
        else:
            over_budget.append(packed)
            excluded.append(
                ExcludedCandidate(
                    program_id=candidate.program_id,
                    reason_code="APPLICATION_BUDGET_EXCEEDED",
                    reasons=("the application fee would exceed the remaining application budget",),
                )
            )
```

- and in the final `return Pack(...)` add `over_budget=tuple(over_budget),`.

Run Step 2's command again. Expected: PASS (the whole file).

- [ ] **Step 4: Write the failing publish test**

`tests/research/test_publish_pool.py`:

```python
"""An over-budget programme is written into the pool with its rank and copies,
never into the pack (lanes spec §7.8, §7.9)."""

from decimal import Decimal

import pytest

from apps.funding.models import CostComponent, PackCandidate, RecommendationCandidate
from apps.research.services import handle_research_message
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import EUR_RATES
from tests.funding.test_spine import _catalogue, _message, _run

pytestmark = pytest.mark.django_db(transaction=True)


def test_an_over_budget_programme_is_kept_in_the_pool_with_its_rank(agency_a, membership_a):
    silent, _ = _catalogue(with_award=False)
    dear, _ = _catalogue(with_award=False, program_name="MSc Computer Science Plus")
    CostComponent.objects.create(
        program=dear, kind="APPLICATION_FEE", amount=Decimal("600"), currency="EUR",
        period="ONE_OFF",
    )
    run = _run(agency_a, membership_a)  # make_profile's budget: 500.00 USD

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        kept = RecommendationCandidate.objects.get(run=run, program=dear)
        packed = RecommendationCandidate.objects.get(run=run, program=silent)

        assert not PackCandidate.objects.filter(pack_version=pack, candidate=kept).exists()
        assert PackCandidate.objects.filter(pack_version=pack, candidate=packed).exists()
        assert kept.state == RecommendationCandidate.State.VISIBLE
        assert (kept.application_fee, kept.application_fee_currency) == (Decimal("600.00"), "EUR")
        assert kept.provenance_reason_code == packed.provenance_reason_code
        assert kept.institution_name == "Example University"
        assert {kept.rank, packed.rank} == {1, 2}
        # No fee stated is "not known", never 0.00 (spec §7.4).
        assert (packed.application_fee, packed.application_fee_currency) == (None, "")
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/research/test_publish_pool.py`
Expected: FAIL — `RecommendationCandidate.DoesNotExist` for `dear`.

- [ ] **Step 5: Add `rank` and write the pool**

In `apps/funding/models.py`, in `RecommendationCandidate` after `funding_card`:

```python
    #: The programme's place in the engine's ranking for this run, 1 = best
    #: (pack.rank_candidates). Written for packed AND over-budget programmes;
    #: None for awards and student-named programmes. "New for you" orders by
    #: it and the stretch rule compares it (lanes spec §7.7, §7.9).
    rank = models.PositiveIntegerField(null=True, blank=True)
```

Generate: `cd /home/orkhan/Desktop/lanes-plan-3 && uv run python manage.py makemigrations funding -n recommendationcandidate_rank`.

In `apps/audit/redaction.py`, add `"rank",` to the `"funding.RecommendationCandidate"` KEEP tuple after `"funding_card",`, with the comment `# the engine's order for the pool: a fact about the programme list, not the person.`

In `apps/research/services.py::_program_copy`, replace the two fee lines with:

```python
        # No stated fee is "not known" (lanes spec §7.4): None, never 0.00, which
        # the board would show as "no fee".
        "application_fee": application.application_fee if application.fee_known else None,
        "application_fee_currency": (
            application.application_fee_currency if application.fee_known else ""
        ),
```

In `_publish`, replace the first loop header and its body's tail. The loop becomes:

```python
    # Packed programmes go into the pack; over-budget ones only into the pool
    # (spec §7.9: offered as "New for you" when the budget gains room).
    programmes = (
        *((application, True) for application in (*result.pack.fee_free, *result.pack.paid)),
        *((application, False) for application in result.pack.over_budget),
    )
    for application, in_pack in programmes:
        program = result.programs.get(application.program_id)
        if program is None:
            continue
        origin = result.origins.get(application.program_id)
        if origin is None:
            # No origin means no provenance (the existing comment stays here).
            record_blocked_source(
                f"https://review.invalid/no-origin/{run.id}/program/{program.id}",
                f"{program.name[:120]} has no official source to cite",
            )
            continue
        # The tenant copy the web tier renders from; it never reads the catalogue.
        body_id, code = provenance_of_program(program)
        candidate = RecommendationCandidate.objects.create(
            run=run,
            evidence=_evidence_for(origin, f"Catalogue entry for {program.name}"),
            program=program,
            program_name=program.name,
            funding_gap=application.gap,
            currency=application.gap_currency,
            eligible=True,
            provenance_reason_code=code,
            provenance_body_id=body_id,
            rank=application.rank,
            **_program_copy(program, application),
        )
        if not _is_publishable_confidence(candidate.evidence_confidence):
            record_blocked_source(
                f"https://review.invalid/low-confidence/{run.id}/{candidate.id}",
                f"{program.name[:120]}: low-confidence evidence",
            )
            continue
        if in_pack:
            PackCandidate.objects.create(pack_version=pack, candidate=candidate)
            packed_any = True
```

Keep the existing comments on `funding_gap` (the "real figure from the evaluator" note) and on the missing origin in place. The award loop is unchanged.

In `tests/research/test_candidate_copies.py::test_the_worker_copies_what_the_board_shows_onto_each_candidate`, the slice's programme states no application fee, so replace `assert programme.application_fee is not None` with:

```python
    # The slice's programme states no fee: "not known", never 0.00 (spec §7.4).
    assert (programme.application_fee, programme.application_fee_currency) == (None, "")
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/research tests/funding tests/audit`
Expected: PASS.

- [ ] **Step 6: Gates and commit**

Run: `uv run ruff check . && uv run mypy apps config && uv run python manage.py makemigrations --check --dry-run`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-3 add apps/funding/fx.py apps/funding/pack.py apps/funding/models.py apps/funding/migrations/0061_recommendationcandidate_rank.py apps/research/services.py apps/audit/redaction.py tests/funding/test_ranking.py tests/research/test_publish_pool.py tests/research/test_candidate_copies.py
git -C /home/orkhan/Desktop/lanes-plan-3 commit -m "feat(funding): 3% bank margin, over-budget programmes kept in the pool with their rank (lanes §7.6, §7.9)

A programme stating no fee is copied as None, not 0.00.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Fee state on the application, and "I've paid this fee"

**Files:**
- Modify: `apps/portals/models.py` (`Application.FeeState`, `FeePaidSource`, three fields, two CHECK constraints)
- Create: `apps/portals/migrations/0037_application_fee_state.py` (generated), `apps/portals/migrations/0038_application_fee_state_backfill.py` (hand-written)
- Create: `apps/portals/fees.py`
- Modify: `apps/portals/applications.py` (`_create`)
- Modify: `apps/portals/views.py`, `apps/portals/urls.py` (the student-only POST)
- Modify: `apps/dashboard/routes.py` (`_STUDENT["fee_paid"]`), `apps/dashboard/board.py` (`Card.fee_state`, `Card.fee_paid_url`), `apps/dashboard/needs.py` (no fee item for a paid card)
- Modify: `templates/student/_card.html` (the fee lines)
- Modify: `tests/dashboard/conftest.py` (`add_card` sets the fee state the way `_create` does)
- Modify: `apps/audit/redaction.py`
- Test: `tests/dashboard/test_fees.py`, `tests/migrations/test_application_fee_state.py`

**Interfaces:**
- Consumes: `RecommendationCandidate.application_fee` (None = not known, after Task 2).
- Produces:
  - `Application.FeeState`: `NONE`, `UNKNOWN`, `OPEN`, `HELD`, `RELEASED`, `PAID`, `SKIPPED` (default `UNKNOWN`); `Application.FeePaidSource`: `STUDENT`, `MAIL`; fields `fee_state`, `fee_paid_at: datetime | None`, `fee_paid_source: str` ("" until paid).
  - `apps.portals.fees.PAYABLE: tuple[str, str]` = (`OPEN`, `UNKNOWN`);
  - `apps.portals.fees.fee_state_for(candidate: RecommendationCandidate | None) -> str`;
  - `apps.portals.fees.mark_fee_paid(application: Application, *, source: str, at: datetime, actor: Membership | None) -> bool` (False when it was not `OPEN`/`UNKNOWN`; one conditional UPDATE, so two racing requests mark it once);
  - route `student/applications/<uuid:application_id>/fee-paid/`, name `student-application-fee-paid`;
  - `Card.fee_state: str = ""`, `Card.fee_paid_url: str = ""` (student, `OPEN`/`UNKNOWN`, and never on a scholarship card).

- [ ] **Step 1: Write the failing tests**

`tests/dashboard/test_fees.py`:

```python
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.dashboard.board import board_for
from apps.funding.models import AuditEvent, RecommendationCandidate
from apps.portals.applications import add_application
from apps.portals.fees import fee_state_for, mark_fee_paid
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import reads_no_catalogue

from .conftest import add_card

pytestmark = pytest.mark.django_db
NOW = timezone.now()


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.parametrize(
    ("fee", "state"),
    [(None, "UNKNOWN"), (Decimal("0.00"), "NONE"), (Decimal("75.00"), "OPEN")],
)
def test_the_fee_state_comes_from_the_candidates_copy(fee, state) -> None:
    assert fee_state_for(RecommendationCandidate(application_fee=fee)) == state


def test_a_card_with_no_candidate_does_not_know_its_fee() -> None:
    assert fee_state_for(None) == "UNKNOWN"


def test_adding_a_programme_and_a_scholarship_sets_their_fee_states(
    agency_a, membership_a, pack
) -> None:
    programme, award = pack
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        award_card = add_application(student=membership_a, candidate_id=award.id, actor=membership_a)
    assert card.fee_state == "OPEN"
    assert award_card.fee_state == "UNKNOWN"  # an award candidate copies no fee


def test_the_student_marks_a_fee_paid(client, agency_a, domain_a, user_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme)
    client.force_login(user_a)

    response = client.post(f"/student/applications/{card.id}/fee-paid/", HTTP_HOST=domain_a.host)

    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        card.refresh_from_db()
        assert (card.fee_state, card.fee_paid_source) == ("PAID", "STUDENT")
        assert card.fee_paid_at is not None
        assert AuditEvent.objects.filter(
            actor=membership_a, event="application.fee_paid", object_id=card.id
        ).count() == 1


def test_two_tabs_racing_mark_the_fee_once(agency_a, membership_a, pack) -> None:
    """Review Focus 5. Both tabs loaded the card while it was OPEN; the
    conditional UPDATE lets exactly one of them through."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme)
        first = Application.objects.get(id=card.id)
        second = Application.objects.get(id=card.id)

        assert mark_fee_paid(first, source="STUDENT", at=NOW, actor=membership_a) is True
        assert mark_fee_paid(second, source="STUDENT", at=NOW, actor=membership_a) is False
        assert AuditEvent.objects.filter(event="application.fee_paid").count() == 1


def test_a_second_press_is_told_it_is_already_marked(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    url = f"/student/applications/{card.id}/fee-paid/"
    client.post(url, HTTP_HOST=domain_a.host)

    body = client.post(url, HTTP_HOST=domain_a.host, follow=True).content.decode()

    assert "already marked as paid" in body
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(event="application.fee_paid").count() == 1


def test_another_students_card_is_a_404(
    client, agency_a, domain_a, user_a, user_b, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        card = add_card(agency_a, other, programme)
    client.force_login(user_a)
    response = client.post(f"/student/applications/{card.id}/fee-paid/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_the_counsellor_never_gets_the_paid_button(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
        student_card = board_for(membership_a).cards[0]
        counselor_card = board_for(membership_a, counselor_view=True).cards[0]
    assert student_card.fee_paid_url.endswith("/fee-paid/")
    assert counselor_card.fee_paid_url == ""


def test_a_scholarship_card_shows_no_fee_line_and_no_paid_button(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    """An award copies no fee, so its card is UNKNOWN; "Fee not known yet" and
    "I've paid this fee" on every scholarship would be noise (programmes only)."""
    _programme, award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, award, portal=False)
        [card] = board_for(membership_a).cards
    assert (card.fee_state, card.fee_paid_url) == ("UNKNOWN", "")
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "DAAD Study Scholarship" in body  # the card rendered
    assert "Fee not known yet" not in body


def test_the_card_shows_the_fee_then_that_it_is_paid(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(
            agency_a, membership_a, programme, deadline=NOW + timedelta(days=5),
        )
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "I've paid this fee" in body
    assert "Application fee for M.Sc. Informatics" in body  # the Needs item

    with tenant_scope(agency_a.id):
        Application.objects.filter(id=card.id).update(fee_state="PAID", fee_paid_source="STUDENT")
    with reads_no_catalogue():
        body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Application fee paid" in body
    assert "Application fee for M.Sc. Informatics" not in body
    assert "paid this fee" not in body


def test_an_unknown_fee_says_so_and_never_shows_zero(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(
            application_fee=None, application_fee_currency=""
        )
        programme.refresh_from_db()
        add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Fee not known yet" in body
    assert "Application fee:" not in body
```

`tests/migrations/test_application_fee_state.py`:

```python
"""portals/0038 sets every existing card's fee state from its candidate's fee
copy. portals_application and funding_recommendationcandidate are FORCE RLS
and the migration sets no app.tenant_id, so it lifts FORCE around its UPDATE
(the concierge/0016 pattern) and the test checks FORCE is back afterwards."""

from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.funding.models import RecommendationCandidate
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_run

BEFORE = {"portals": "0036_reference_letter_slots"}
AFTER = {"portals": "0038_application_fee_state_backfill"}


def _migrate(selected: dict[str, str]) -> None:
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] not in selected]
    executor.migrate([*targets, *selected.items()])


def _state(application_id) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT fee_state FROM portals_application WHERE id = %s", [application_id])
        return cursor.fetchone()[0]


def _forced(table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", [table])
        return cursor.fetchone()[0]


@pytest.mark.django_db(transaction=True)
def test_existing_cards_take_their_fee_state_from_their_candidate(agency_a, membership_a):
    run = make_run(agency_a, membership_a)
    cards = {}
    try:
        with tenant_scope(agency_a.id):
            for name, fee in (("paid", "75.00"), ("free", "0.00"), ("silent", None)):
                candidate = make_db_candidate(agency_a, run, program_name=name)
                RecommendationCandidate.objects.filter(id=candidate.id).update(
                    application_fee=fee
                )
                cards[name] = Application.objects.create(
                    tenant=agency_a, student=membership_a, program_id=uuid4(),
                    candidate=candidate,
                ).id
            cards["none"] = Application.objects.create(
                tenant=agency_a, student=membership_a, program_id=uuid4(), name="Offer"
            ).id

        _migrate(BEFORE)  # drops the columns; the rows stay
        _migrate(AFTER)   # adds them at UNKNOWN, then backfills

        assert {name: _state(card) for name, card in cards.items()} == {
            "paid": "OPEN", "free": "NONE", "silent": "UNKNOWN", "none": "UNKNOWN",
        }
        assert _forced("portals_application") and _forced("funding_recommendationcandidate")
    finally:
        _migrate({})
        with tenant_scope(agency_a.id):
            Application.objects.filter(student=membership_a).delete()
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard/test_fees.py tests/migrations/test_application_fee_state.py`
Expected: FAIL — `No module named 'apps.portals.fees'`.

- [ ] **Step 3: The model, the migrations, `fees.py` and `_create`**

In `apps/portals/models.py`, inside `Application` after `OutcomeSource`:

```python
    class FeeState(models.TextChoices):
        """Lanes spec §3.2. HELD and RELEASED belong to the fee hold (plan 3b);
        nothing sets them yet."""

        NONE = "NONE", "No application fee"
        UNKNOWN = "UNKNOWN", "Fee not known yet"
        OPEN = "OPEN", "To pay"
        HELD = "HELD", "On hold"
        RELEASED = "RELEASED", "Released by the student"
        PAID = "PAID", "Paid"
        SKIPPED = "SKIPPED", "Skipped"

    class FeePaidSource(models.TextChoices):
        STUDENT = "STUDENT", "Marked by the student"
        MAIL = "MAIL", "A receipt email"
```

and after `outcome_evidence`:

```python
    #: The application fee's state (lanes spec §3.2, §7.4). Set from the
    #: candidate's fee copy when the card is made (portals.fees.fee_state_for).
    fee_state = models.CharField(max_length=10, choices=FeeState.choices, default=FeeState.UNKNOWN)
    fee_paid_at = models.DateTimeField(null=True, blank=True)
    fee_paid_source = models.CharField(max_length=10, choices=FeePaidSource.choices, blank=True)
```

and in `Meta.constraints`:

```python
            models.CheckConstraint(
                condition=models.Q(
                    fee_state__in=(
                        "NONE", "UNKNOWN", "OPEN", "HELD", "RELEASED", "PAID", "SKIPPED"
                    )
                ),
                name="portal_app_fee_state_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(fee_paid_source__in=("", "STUDENT", "MAIL")),
                name="portal_app_fee_paid_source_valid",
            ),
```

Generate: `cd /home/orkhan/Desktop/lanes-plan-3 && uv run python manage.py makemigrations portals -n application_fee_state` (writes `0037_application_fee_state.py`).

Write `apps/portals/migrations/0038_application_fee_state_backfill.py`:

```python
"""Existing cards take their fee state from their candidate's fee copy.

None -> UNKNOWN (the default 0037 already wrote), 0 -> NONE, more -> OPEN.
Both tables are FORCE RLS and a migration sets no app.tenant_id, so the
UPDATE would silently match nothing for the (NOBYPASSRLS) migration role;
FORCE is lifted around it and put back, as concierge/0016 does.

No ("funding", "0057_dashboard_fields") dependency, on purpose: portals depends
on funding only at 0001, and a later edge turns the mixed plans in
tests/migrations (test_task7_migrations, test_audit_event_actor_kind, the
holder backfill) into InvalidMigrationPlan -- measured, 8 failures. The block
instead runs only when the fee column exists: every existing database has it
(funding/0057 is on master), and a fresh one has no cards to backfill.
"""

from django.db import migrations

FORWARD = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'funding_recommendationcandidate'
       AND column_name = 'application_fee'
  ) THEN
    ALTER TABLE portals_application NO FORCE ROW LEVEL SECURITY;
    ALTER TABLE funding_recommendationcandidate NO FORCE ROW LEVEL SECURITY;
    UPDATE portals_application AS app
       SET fee_state = CASE WHEN candidate.application_fee = 0 THEN 'NONE' ELSE 'OPEN' END
      FROM funding_recommendationcandidate AS candidate
     WHERE candidate.id = app.candidate_id
       AND candidate.application_fee IS NOT NULL;
    ALTER TABLE funding_recommendationcandidate FORCE ROW LEVEL SECURITY;
    ALTER TABLE portals_application FORCE ROW LEVEL SECURITY;
  END IF;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("portals", "0037_application_fee_state")]

    operations = [migrations.RunSQL(FORWARD, migrations.RunSQL.noop)]
```

`apps/portals/fees.py`:

```python
"""The application fee's state (lanes spec §3.2, §7.4).

One writer for "paid", shared by the student's button and a trusted receipt
email (apps/mailbox/actions.py), so a separate module that imports neither.
"""

from __future__ import annotations

from datetime import datetime

from apps.funding.models import AuditEvent, RecommendationCandidate
from apps.tenancy.models import Membership

from .models import Application

#: The states a fee can be marked paid from. An unknown fee can still have been paid.
PAYABLE = (Application.FeeState.OPEN, Application.FeeState.UNKNOWN)


def fee_state_for(candidate: RecommendationCandidate | None) -> str:
    """A new card's fee state from the candidate's copy. No copy (an award, a
    named programme, an accepted offer, a programme stating no fee) is UNKNOWN."""
    fee = candidate.application_fee if candidate is not None else None
    if fee is None:
        return Application.FeeState.UNKNOWN
    return Application.FeeState.NONE if fee == 0 else Application.FeeState.OPEN


def mark_fee_paid(
    application: Application, *, source: str, at: datetime, actor: Membership | None
) -> bool:
    """PAID, if the fee was OPEN or UNKNOWN; False otherwise.

    One conditional UPDATE, not read-then-write: two tabs pressing at once
    both pass any check made on a stale row, and only the database can let
    exactly one of them through.
    """
    updated = Application.objects.filter(id=application.id, fee_state__in=PAYABLE).update(
        fee_state=Application.FeeState.PAID, fee_paid_at=at, fee_paid_source=source
    )
    if not updated:
        return False
    AuditEvent.objects.create(actor=actor, event="application.fee_paid", object_id=application.id)
    application.refresh_from_db(fields=["fee_state", "fee_paid_at", "fee_paid_source"])
    return True
```

In `apps/portals/applications.py`, add `from .fees import fee_state_for` and in `_create` add `fee_state=fee_state_for(candidate),` to the `Application.objects.create(...)` call, after `route_snapshot=…`.

In `tests/dashboard/conftest.py::add_card`, add `from apps.portals.fees import fee_state_for` and, before the `return`, `fields.setdefault("fee_state", fee_state_for(candidate))` — the helper then makes a card the way `_create` does.

In `apps/audit/redaction.py`, add to the `"portals.Application"` KEEP tuple after `"started_at",`:

```python
        # the fee's state, when it was marked paid and by which route:
        # operational, like started_at.
        "fee_state",
        "fee_paid_at",
        "fee_paid_source",
```

- [ ] **Step 4: The route, the card and Needs**

In `apps/portals/views.py`, add `from apps.ratelimit import pack_command_rate_limited, rate_limited` (replacing the `rate_limited`-only import), `from .fees import mark_fee_paid`, and:

```python
@login_required
@require_POST
def application_fee_paid(request: HttpRequest, application_id: UUID) -> HttpResponse:
    """"I've paid this fee" (lanes spec §7.4). Only the student: there is no
    counsellor route, because spending is the student's own record."""
    student, application = _own_application(request, application_id)
    if pack_command_rate_limited(student.id):
        messages.error(request, REFUSALS["rate_limited"])
    elif mark_fee_paid(
        application, source=Application.FeePaidSource.STUDENT, at=timezone.now(), actor=student
    ):
        messages.success(request, f"Marked the application fee for {application.title} as paid.")
    else:
        messages.error(request, "This fee is already marked as paid, or has nothing to pay.")
    return redirect("concierge-student-dashboard")
```

In `apps/portals/urls.py`, after the `student-application-remove` path:

```python
    path(
        "student/applications/<uuid:application_id>/fee-paid/",
        views.application_fee_paid,
        name="student-application-fee-paid",
    ),
```

In `apps/dashboard/routes.py`, add `"fee_paid": "student-application-fee-paid",` to `_STUDENT` only.

In `apps/dashboard/board.py`:
- add `from apps.portals.fees import PAYABLE`;
- add to `Card` (after `last_checked`): `fee_state: str = ""` and `fee_paid_url: str = ""`;
- in `build_card`'s `Card(...)` call, add:

```python
        fee_state=application.fee_state,
        fee_paid_url=(
            action_url(counselor_view, "fee_paid", student_id, application.id)
            # A scholarship card copies no fee, so it is always UNKNOWN; a paid
            # button on every scholarship would be noise (programmes only).
            if application.fee_state in PAYABLE and (candidate is None or is_programme)
            else ""
        ),
```

In `apps/dashboard/needs.py::items_from_cards`, change the fee item's condition to skip a paid fee:

```python
        if (
            card.fee
            and card.fee_state != "PAID"
            and card.portal_url
            and card.column in (Column.TO_START, Column.IN_PROGRESS)
        ):
```

In `templates/student/_card.html`, replace the line `{% if card.fee %}<p>Application fee: …</p>{% endif %}` with:

```django
  {% if card.fee_state == "PAID" %}
    <p>Application fee paid</p>
  {% elif card.fee %}
    <p>Application fee: {{ card.fee }} {{ card.fee_currency }} — you pay this at submission</p>
  {% elif card.fee_state == "UNKNOWN" and not card.is_award %}
    <p>Fee not known yet</p>
  {% endif %}
  {% if card.fee_paid_url and not read_only %}
    <form method="post" action="{{ card.fee_paid_url }}">{% csrf_token %}<button type="submit">I've paid this fee</button></form>
  {% endif %}
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard tests/portals tests/migrations tests/funding/test_funding_models.py tests/audit`
Expected: PASS — the whole of `tests/migrations`, not only the new test: those modules roll funding back with portals at its leaf, which is why 0038 carries no funding edge. If another migration test pins portals' leaf node, add the new leaf there.

- [ ] **Step 6: Gates and commit**

Run: `uv run ruff check . && uv run mypy apps config && uv run python manage.py check && uv run python manage.py makemigrations --check --dry-run`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-3 add apps/portals/models.py apps/portals/migrations/0037_application_fee_state.py apps/portals/migrations/0038_application_fee_state_backfill.py apps/portals/fees.py apps/portals/applications.py apps/portals/views.py apps/portals/urls.py apps/dashboard/routes.py apps/dashboard/board.py apps/dashboard/needs.py templates/student/_card.html apps/audit/redaction.py tests/dashboard/conftest.py tests/dashboard/test_fees.py tests/migrations/test_application_fee_state.py
git -C /home/orkhan/Desktop/lanes-plan-3 commit -m "feat(portals): a fee state on every application, and the student's 'I've paid this fee' (lanes §3.2, §7.4)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Amounts in AZN, the rate note, and the "at risk" line

**Files:**
- Create: `apps/dashboard/money.py`
- Modify: `apps/dashboard/board.py` (`Card.fee_text`, `Card.risk_line`, `Card.converted`; `Board.rates`, `.home`, `.rate_note`; `build_card`; `board_for`)
- Modify: `apps/dashboard/needs.py` (the fee item reads `fee_text`)
- Modify: `apps/dashboard/views.py` (`_programme_page` passes `rate_note`)
- Modify: `templates/student/_card.html`, `templates/student/_board.html`, `templates/student/programme.html`
- Test: `tests/dashboard/test_money.py`, `tests/dashboard/test_board.py`, `tests/dashboard/conftest.py` (`AZN_RATES`, `set_profile`)

**Interfaces:**
- Consumes: Task 1's `latest_table()`; Task 3's `Card.fee_state`; `apps.funding.fx.convert`, `UnconvertibleCurrency`, `home_currency_for`; `apps.portals.award_links.award_lines_for` (`AwardLine.kind`).
- Produces (`apps/dashboard/money.py`):
  - `WITH_APPLICATION: frozenset[str]` = {`AUTOMATIC`, `SAME_APPLICATION`, `COMBINED`};
  - `Position = Literal["SAFE", "AT_RISK", ""]`;
  - `whole(amount: Decimal, *, up: bool = False) -> str` ("195"; `up=True` rounds a floor or shortfall upward, for Task 7's refusals);
  - `home_currency(country_of_residence: str) -> str` ("" when unknown);
  - `in_home(amount: Decimal, currency: str, table: RateTable | None, home: str) -> Decimal | None`;
  - `approx(amount: Decimal, currency: str, table: RateTable | None, home: str) -> str` ("100.00 EUR ≈ 200 AZN", or the original alone);
  - `rate_note(table: RateTable | None) -> str`;
  - `position(*, mandatory: bool, fee: Decimal | None, fee_state: str, fee_text: str, linked_award_titles: Sequence[str], funded_with_application: bool) -> tuple[Position, str]`.
- `Card` gains `fee_text: str = ""`, `risk_line: str = ""`, and the property `converted: bool`. `Board` gains `rates: RateTable | None = None`, `home: str = ""`, `rate_note: str = ""`.
- `build_card` gains `rates: RateTable | None = None`, `home: str = ""`, `linked_award_titles: Sequence[str] = ()`, `funded_with_application: bool = False`.

- [ ] **Step 1: Write the failing pure tests**

`tests/dashboard/test_money.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from apps.dashboard.money import approx, home_currency, position, rate_note, whole
from apps.funding.fx import RateTable

RATES = RateTable(
    base="AZN",
    rates={"AZN": Decimal("1"), "EUR": Decimal("0.5"), "USD": Decimal("0.625")},
    source="CBAR",
    retrieved_on=date(2026, 10, 8),
)


def test_the_home_currency_follows_the_country_of_residence() -> None:
    assert home_currency("AZ") == "AZN"
    assert home_currency("") == ""


@pytest.mark.parametrize(
    ("amount", "currency", "table", "expected"),
    [
        (Decimal("100.00"), "EUR", RATES, "100.00 EUR ≈ 200 AZN"),
        (Decimal("85.00"), "USD", RATES, "85.00 USD ≈ 136 AZN"),
        (Decimal("50.00"), "AZN", RATES, "50.00 AZN"),
        # Review Focus 1: a currency the table lacks is never guessed at.
        (Decimal("120.00"), "ISK", RATES, "120.00 ISK"),
        # Review Focus 2: the first day, before any rate is stored.
        (Decimal("100.00"), "EUR", None, "100.00 EUR"),
    ],
)
def test_each_amount_is_the_original_then_about_so_much_in_azn(
    amount, currency, table, expected
) -> None:
    assert approx(amount, currency, table, "AZN") == expected


def test_a_floor_rounds_up_and_a_total_rounds_to_nearest() -> None:
    assert (whole(Decimal("150.40")), whole(Decimal("150.40"), up=True)) == ("150", "151")
    assert (whole(Decimal("150.50")), whole(Decimal("150.00"), up=True)) == ("151", "150")


def test_no_home_currency_shows_the_original_alone() -> None:
    assert approx(Decimal("100.00"), "EUR", RATES, "") == "100.00 EUR"


def test_the_rate_is_a_note_with_its_day() -> None:
    assert rate_note(RATES) == "Converted at the CBAR rate of 8 Oct; your bank may charge more"
    assert rate_note(None) == ""


_FEE = "85.00 EUR ≈ 170 AZN"


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        # Pay first, at risk: mandatory, a fee to pay, a separate scholarship card.
        (
            {},
            ("AT_RISK", f"{_FEE} at risk: if SI Scholarship isn't won, you can't afford this programme."),
        ),
        (
            {"linked_award_titles": ("SI Scholarship", "KTH Tuition waiver")},
            (
                "AT_RISK",
                f"{_FEE} at risk: if SI Scholarship or KTH Tuition waiver isn't won, "
                "you can't afford this programme.",
            ),
        ),
        # Safe: funding comes with the application, or there is no fee.
        ({"funded_with_application": True}, ("SAFE", "")),
        ({"fee": Decimal("0")}, ("SAFE", "")),
        # Not at risk: paid already, not known, or no separate scholarship to wait on.
        ({"fee_state": "PAID"}, ("", "")),
        ({"fee_state": "UNKNOWN", "fee": None}, ("", "")),
        ({"linked_award_titles": ()}, ("", "")),
        # IMPORTANT and OPTIONAL students see fees, never positions (§7.1).
        ({"mandatory": False}, ("", "")),
    ],
)
def test_the_position_line(fields, expected) -> None:
    arguments = {
        "mandatory": True,
        "fee": Decimal("85.00"),
        "fee_state": "OPEN",
        "fee_text": _FEE,
        "linked_award_titles": ("SI Scholarship",),
        "funded_with_application": False,
        **fields,
    }
    assert position(**arguments) == expected
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard/test_money.py`
Expected: FAIL — `No module named 'apps.dashboard.money'`.

- [ ] **Step 2: Write `apps/dashboard/money.py`**

```python
"""Money on the board (lanes spec §7.1, §7.5, §7.6). Pure: no queries.

Each amount is its original currency first, then "≈ N AZN" at the stored CBAR
rate. A currency the table lacks, or no table at all, shows the original
alone: a guessed figure is worse than an unconverted one.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Literal

from apps.funding.fx import RateTable, UnconvertibleCurrency, convert, home_currency_for

#: Award lines whose funding comes with the programme's own application (§2):
#: nothing separate to win, so the fee is not at risk on it (§7.1 "Safe").
WITH_APPLICATION: frozenset[str] = frozenset({"AUTOMATIC", "SAME_APPLICATION", "COMBINED"})

Position = Literal["SAFE", "AT_RISK", ""]


def whole(amount: Decimal, *, up: bool = False) -> str:
    """A home-currency figure in whole units: totals and "≈" parts never show cents.

    ``up`` rounds a floor or a shortfall upward, so a refusal never names a
    figure that the student could type and still be refused at (150.40 paid
    reads "151", not "150")."""
    rounding = ROUND_CEILING if up else ROUND_HALF_UP
    return str(amount.quantize(Decimal("1"), rounding=rounding))


def home_currency(country_of_residence: str) -> str:
    """The student's home currency (§7.6: per country; AZN at launch). "" when unknown."""
    return home_currency_for(country_of_residence) or ""


def in_home(amount: Decimal, currency: str, table: RateTable | None, home: str) -> Decimal | None:
    """``amount`` in the home currency, or None when it cannot be converted honestly."""
    if not home:
        return None
    if currency == home:
        return amount
    if table is None:
        return None
    try:
        return convert(amount, currency, home, table)
    except UnconvertibleCurrency:
        return None


def approx(amount: Decimal, currency: str, table: RateTable | None, home: str) -> str:
    original = f"{amount} {currency}"
    if currency == home:
        return original
    converted = in_home(amount, currency, table, home)
    return original if converted is None else f"{original} ≈ {whole(converted)} {home}"


def rate_note(table: RateTable | None) -> str:
    if table is None:
        return ""
    day = table.retrieved_on
    return f"Converted at the {table.source} rate of {day.day} {day:%b}; your bank may charge more"


def position(
    *,
    mandatory: bool,
    fee: Decimal | None,
    fee_state: str,
    fee_text: str,
    linked_award_titles: Sequence[str],
    funded_with_application: bool,
) -> tuple[Position, str]:
    """§7.1's positions this plan can tell apart, and the card's sentence.

    "Wait, then pay" needs a result date and a fee deadline nobody writes yet
    (plan 3b), so a fee due on a separate scholarship's result is always "Pay
    first, at risk" here -- the spec's own rule when "the result date isn't
    stated". Only a MANDATORY student gets a position.
    """
    if not mandatory:
        return "", ""
    if funded_with_application or fee == 0:
        return "SAFE", ""
    if fee is None or fee_state != "OPEN" or not linked_award_titles:
        return "", ""
    awards = " or ".join(linked_award_titles)
    return "AT_RISK", f"{fee_text} at risk: if {awards} isn't won, you can't afford this programme."
```

Run the Step 1 command again. Expected: PASS.

- [ ] **Step 3: Write the failing board tests**

In `tests/dashboard/conftest.py` add (with the imports `from datetime import date`, `from decimal import Decimal`, `from apps.accounts.models import StudentProfileVersion`, `from apps.funding.fx import RateTable`):

```python
#: 1 EUR = 2 AZN and 1 USD = 1.6 AZN: round figures to assert on. A day well in
#: the past, so latest_table() finds it whatever today is.
AZN_RATES = RateTable(
    base="AZN",
    rates={"AZN": Decimal("1"), "EUR": Decimal("0.5"), "USD": Decimal("0.625")},
    source="CBAR",
    retrieved_on=date(2026, 1, 8),
)


def set_profile(agency, student, **snapshot) -> None:
    """A newer profile version holding only the keys board_for reads."""
    with tenant_scope(agency.id):
        version = StudentProfileVersion.objects.filter(student=student).count() + 1
        StudentProfileVersion.objects.create(student=student, version=version, snapshot=snapshot)
```

Append to `tests/dashboard/test_board.py` (add `from apps.funding.rates import store`, `from apps.portals.models import ApplicationLink` and `from .conftest import AZN_RATES, add_card, set_profile`):

```python
@pytest.mark.django_db
def test_a_fee_reads_original_then_azn_and_at_risk_on_a_separate_scholarship(
    agency_a, membership_a, pack
) -> None:
    programme, award = pack
    store(AZN_RATES)
    set_profile(agency_a, membership_a, funding_dependency="MANDATORY", country_of_residence="AZ")
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme)
        award_card = add_card(agency_a, membership_a, award, portal=False)
        ApplicationLink.objects.create(
            tenant=agency_a, from_app=award_card, to_app=card, order="LINKED_ONLY"
        )
        with reads_no_catalogue():
            board = board_for(membership_a)

    cards = {c.title: c for c in board.cards}
    lead = cards["M.Sc. Informatics"]
    assert lead.fee_text == "75.00 EUR ≈ 150 AZN"
    assert lead.risk_line == (
        "75.00 EUR ≈ 150 AZN at risk: if DAAD Study Scholarship isn't won, "
        "you can't afford this programme."
    )
    assert board.rate_note == "Converted at the CBAR rate of 8 Jan; your bank may charge more"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("award_outcome", "programme_outcome"), [("REJECTED", ""), ("ADMITTED", ""), ("", "WITHDRAWN")]
)
def test_a_decided_card_puts_nothing_at_risk(
    agency_a, membership_a, pack, award_outcome, programme_outcome
) -> None:
    """Once the scholarship's result is in (won or not), "if X isn't won" is
    stale; once the programme itself is decided, its fee is no longer a bet."""
    programme, award = pack
    store(AZN_RATES)
    set_profile(agency_a, membership_a, funding_dependency="MANDATORY", country_of_residence="AZ")
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme, outcome=programme_outcome)
        award_card = add_card(agency_a, membership_a, award, portal=False, outcome=award_outcome)
        ApplicationLink.objects.create(
            tenant=agency_a, from_app=award_card, to_app=card, order="LINKED_ONLY"
        )
        with reads_no_catalogue():
            board = board_for(membership_a)
    assert {c.title: c for c in board.cards}["M.Sc. Informatics"].risk_line == ""


@pytest.mark.django_db
def test_on_the_first_day_the_board_shows_originals_and_no_note(
    agency_a, membership_a, pack
) -> None:
    """Review Focus 2: no rate stored yet."""
    programme, _award = pack
    set_profile(agency_a, membership_a, country_of_residence="AZ")
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
        with reads_no_catalogue():
            board = board_for(membership_a)
    assert board.cards[0].fee_text == "75.00 EUR"
    assert board.rate_note == ""
```

In `tests/dashboard/test_home.py`, add:

```python
def test_the_rate_note_appears_once_however_many_amounts(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    from apps.funding.rates import store

    from .conftest import AZN_RATES, set_profile

    programme, award = pack
    store(AZN_RATES)
    set_profile(agency_a, membership_a, country_of_residence="AZ")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            application_fee="20.00", application_fee_currency="USD"
        )
        award.refresh_from_db()
        add_card(agency_a, membership_a, programme)
        add_card(agency_a, membership_a, award, portal=False)
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Application fee: 75.00 EUR ≈ 150 AZN — you pay this at submission" in body
    assert "20.00 USD ≈ 32 AZN" in body
    assert body.count("Converted at the CBAR rate") == 1
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard/test_board.py tests/dashboard/test_home.py`
Expected: FAIL — `'Card' object has no attribute 'fee_text'`.

- [ ] **Step 4: Wire the board**

In `apps/dashboard/board.py`:
- imports: `from apps.funding.fx import RateTable`, `from apps.funding.rates import latest_table`, `from .money import WITH_APPLICATION, approx, home_currency, position, rate_note`;
- `Card` gains, after `fee_paid_url`:

```python
    fee_text: str = ""
    risk_line: str = ""

    @property
    def converted(self) -> bool:
        """An amount on this card was converted, so the board shows the rate note."""
        return "≈" in self.fee_text
```

- `Board` gains three fields after `done`:

```python
    rates: RateTable | None = None
    home: str = ""
    #: Shown once on the board and the programme page, never per card (§7.6).
    rate_note: str = ""
```

- `build_card` gains four keyword arguments after `student_zone`:

```python
    rates: RateTable | None = None,
    home: str = "",
    linked_award_titles: Sequence[str] = (),
    funded_with_application: bool = False,
```

  and, before `return Card(`:

```python
    fee = candidate.application_fee if candidate is not None else None
    fee_currency = candidate.application_fee_currency if candidate is not None else ""
    fee_text = approx(fee, fee_currency, rates, home) if fee else ""
    # A decided programme's fee is no longer a bet on a result (§7.1).
    _position, risk_line = ("", "") if application.outcome else position(
        mandatory=mandatory,
        fee=fee,
        fee_state=application.fee_state,
        fee_text=fee_text,
        linked_award_titles=linked_award_titles,
        funded_with_application=funded_with_application,
    )
```

  In the `Card(...)` call replace `fee=candidate.application_fee if …` and `fee_currency=…` with `fee=fee,` and `fee_currency=fee_currency,`, and add `fee_text=fee_text,` and `risk_line=risk_line,`.

- in `board_for`, replace everything from `profile = StudentProfileVersion…` to the end of the function with:

```python
    profile = StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
    # The money below reads `snapshot` too: plan 4's funding_mandatory(student)
    # replaces only the `mandatory =` line, never these two.
    snapshot = profile.snapshot if profile else None
    mandatory = (snapshot or {}).get("funding_dependency") == "MANDATORY"
    home = home_currency(str((snapshot or {}).get("country_of_residence") or ""))
    rates = latest_table()
    links = list(
        ApplicationLink.objects.filter(from_app__in=applications).values_list(
            "from_app_id", "to_app_id"
        )
    )
    lines = award_lines_for(applications)
    # Only scholarships whose result is not in yet: one won or refused no
    # longer decides whether the fee is at risk (WAITLISTED is still waiting).
    pending = {
        application.id: application.title
        for application in applications
        if application.outcome in ("", Application.Outcome.WAITLISTED)
    }
    # (award card, programme card): the scholarships a programme's fee rides on.
    linked_awards: dict[UUID, list[str]] = {}
    for award_id, programme_id in links:
        if award_id in pending:
            linked_awards.setdefault(programme_id, []).append(pending[award_id])
    cards = [
        build_card(
            application,
            # Only the packet issues an address; reading the board writes nothing.
            kit=build_kit(application, issue_address=False, documents=False),
            table=table,
            signals=by_application.get(application.id, []),
            awards=awards,
            counselor_view=counselor_view,
            now=now,
            mandatory=mandatory,
            student_zone=student.timezone,
            rates=rates,
            home=home,
            linked_award_titles=tuple(linked_awards.get(application.id, ())),
            funded_with_application=any(
                line.kind in WITH_APPLICATION for line in lines.get(application.id, ())
            ),
        )
        for application in applications
    ]
    open_lanes, done = lanes_for(
        cards,
        links,
        page_url=lambda key: action_url(counselor_view, "programme", student.id, key),
    )
    open_lanes = tuple(
        replace(lane, award_lines=tuple(
            replace(line, add_url=action_url(counselor_view, "add", student.id, line.candidate_id))
            if line.kind == "ASK" else line
            # A closed lane has nothing left to do: no "Yes, add" either.
            for line in lines.get(lane.key, [])
            if not (line.kind == "ASK" and lane.lead.closed)
        ))
        for lane in open_lanes
    )
    return Board(
        lanes=open_lanes,
        done=done,
        rates=rates,
        home=home,
        rate_note=rate_note(rates) if any(card.converted for card in cards) else "",
    )
```

In `apps/dashboard/needs.py`, the fee item's text becomes `f"Application fee for {card.title}: {card.fee_text} — you pay this at submission"`, and `tests/dashboard/test_needs.py::_card` gains `fee_text=""` in its defaults (the two fee tests pass `fee_text="75 EUR"` alongside `fee=75`).

In `templates/student/_card.html`:
- the fee line becomes `<p>Application fee: {{ card.fee_text }} — you pay this at submission</p>`;
- add, right after the fee block, `{% if card.risk_line %}<p>{{ card.risk_line }}</p>{% endif %}`.

In `templates/student/_board.html`, right after `<h2 id="board-heading">Your applications</h2>`:

```django
  {% if board.rate_note %}<p>{{ board.rate_note }}</p>{% endif %}
```

In `templates/student/programme.html`, replace the `Money` section's fee line with:

```django
    {% if lead.fee_state == "PAID" %}<p>Application fee paid</p>
    {% elif lead.fee %}<p>Application fee: {{ lead.fee_text }} — you pay this at submission</p>
    {% elif lead.fee_state == "UNKNOWN" and not lead.is_award %}<p>Fee not known yet</p>{% endif %}
    {% if lead.risk_line %}<p>{{ lead.risk_line }}</p>{% endif %}
    {% if rate_note %}<p>{{ rate_note }}</p>{% endif %}
```

In `apps/dashboard/views.py::_programme_page`, add `"rate_note": board.rate_note,` to the context.

**`reads_no_catalogue`:** `funding_exchangerate` carries no `shared_catalog_select` policy, so the fixture (which reads the catalogue list from `pg_policies`) does not count it. The tests above run the board inside it to confirm.

- [ ] **Step 5: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard tests/concierge tests/portals tests/tenancy/test_catalog_grants.py`, then `uv run ruff check . && uv run mypy apps config && uv run python manage.py check`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-3 add apps/dashboard/money.py apps/dashboard/board.py apps/dashboard/needs.py apps/dashboard/views.py templates/student/_card.html templates/student/_board.html templates/student/programme.html tests/dashboard/conftest.py tests/dashboard/test_money.py tests/dashboard/test_board.py tests/dashboard/test_home.py tests/dashboard/test_needs.py
git -C /home/orkhan/Desktop/lanes-plan-3 commit -m "feat(dashboard): fees in the original currency then ≈ AZN, one rate note, and the at-risk line (lanes §7.1, §7.6)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The budget line

**Files:**
- Modify: `apps/dashboard/money.py` (`money_from`, `BudgetLine`, `budget_line`)
- Modify: `apps/dashboard/board.py` (`Board.budget`; `board_for`)
- Modify: `templates/student/_board.html`
- Test: `tests/dashboard/test_money.py`, `tests/dashboard/test_counselor_board.py`

**Interfaces:**
- Consumes: Task 3's `Card.fee_state`; Task 4's `in_home`, `whole`, `Board.rates`, `Board.home`.
- Produces:
  - `money_from(snapshot: Mapping[str, object] | None, key: str) -> Money | None` (a short-form profile's bare-number budget has no currency, so None);
  - `BudgetLine(currency: str, plan: Decimal, extra: Decimal | None, paid: Decimal, committed: Decimal, not_known: int, no_rate: int, converted: bool)` with properties `free`, `used_from_extra`, `text`, `stretch_text` (all in the home currency);
  - `budget_line(*, budget: Money | None, stretch: Money | None, cards: Sequence[Card], table: RateTable | None, home: str) -> BudgetLine | None`;
  - `Board.budget: BudgetLine | None = None`.

The counted cards, per spec §7.5:
- **paid:** `PAID`;
- **committed:** `OPEN` and `RELEASED`, on a card with no outcome and not closed. A withdrawn or refused application, or one whose intake closed, will never be paid (§7.9 counts an unused deadline as room regained);
- **not counted:** an undecided `UNKNOWN` programme card with no fee, whether or not its portal is recorded yet ("not known"; a scholarship card is never counted), and a fee the table cannot convert ("without a rate yet").

- [ ] **Step 1: Write the failing tests**

Append to `tests/dashboard/test_money.py` (add `from datetime import UTC, datetime`, `from uuid import uuid4`, `from apps.accounts.schemas import Money`, `from apps.dashboard.board import Card, Column` and `from apps.dashboard.money import budget_line, money_from`):

```python
NOW = datetime(2026, 10, 13, tzinfo=UTC)


def _card(fee=None, currency="EUR", state="OPEN", **overrides) -> Card:
    fields = dict(
        application_id=uuid4(), title="TUM M.Sc.", institution="TUM", country="DE",
        column=Column.TO_START, created_at=NOW, deadline=None, days_left=None,
        documents=(0, 0), answers=(0, 0), funding=(), funding_outcome_line="", gap="",
        fee=Decimal(fee) if fee is not None else None, fee_currency=currency, badges=(),
        missing=(), outcome_line="", offer=None, button=None, has_portal=True, portal_url="",
        kit_url="", documents_url="", outcome_url="", remove_url="", portal_record_url="",
        outcome="", conditions=(), fee_state=state,
    )
    fields.update(overrides)
    return Card(**fields)


def _azn(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="AZN")


def test_the_budget_line_reads_like_the_spec() -> None:
    line = budget_line(
        budget=_azn("500"), stretch=None, table=RATES, home="AZN",
        cards=[_card("95.00", state="PAID"), _card("70.00"), _card(None, state="UNKNOWN")],
    )
    assert line.text == (
        "Application budget 500 AZN · Paid 190 · Committed 140 · Free 170 (≈, see note)"
        " · 1 fee not known — not counted"
    )
    assert line.stretch_text == ""


def test_with_a_stretch_the_line_shows_the_extra_and_what_is_used() -> None:
    line = budget_line(
        budget=_azn("400"), stretch=_azn("150"), table=RATES, home="AZN",
        cards=[_card("95.00", state="PAID"), _card("142.50")],
    )
    assert line.free == 0
    assert line.stretch_text == (
        "Plan 400 AZN · Extra allowed for exceptional cases: up to 150 · Used from extra: 75"
    )


def test_a_budget_in_eur_is_shown_in_azn() -> None:
    """Review Focus 3."""
    line = budget_line(
        budget=Money(amount=Decimal("250.00"), currency="EUR"), stretch=None, cards=[],
        table=RATES, home="AZN",
    )
    assert line.text == "Application budget 500 AZN · Paid 0 · Committed 0 · Free 500 (≈, see note)"


def test_a_budget_that_cannot_be_converted_shows_nothing() -> None:
    eur = Money(amount=Decimal("250.00"), currency="EUR")
    assert budget_line(budget=eur, stretch=None, cards=[], table=None, home="AZN") is None
    assert budget_line(budget=None, stretch=None, cards=[], table=RATES, home="AZN") is None


def test_a_fee_without_a_rate_is_not_counted_and_says_so() -> None:
    """Review Focus 1 and 2: an ISK fee, and a EUR fee before any rate is stored."""
    line = budget_line(
        budget=_azn("500"), stretch=None, table=RATES, home="AZN", cards=[_card("90", "ISK")],
    )
    assert line.text.endswith("Free 500 · 1 fee without a rate yet — not counted")
    first_day = budget_line(
        budget=_azn("500"), stretch=None, table=None, home="AZN", cards=[_card("70.00")],
    )
    assert first_day.text == (
        "Application budget 500 AZN · Paid 0 · Committed 0 · Free 500"
        " · 1 fee without a rate yet — not counted"
    )


def test_an_unknown_programme_fee_is_not_known_with_or_without_a_portal() -> None:
    """Most programme cards have no portal yet (_ask_for_portal); a
    scholarship card copies no fee and is never a fee "not known"."""
    line = budget_line(
        budget=_azn("500"), stretch=None, table=RATES, home="AZN",
        cards=[
            _card(None, state="UNKNOWN", has_portal=False),
            _card(None, state="UNKNOWN", is_award=True),
        ],
    )
    assert line.not_known == 1


def test_a_decided_or_closed_card_commits_nothing() -> None:
    line = budget_line(
        budget=_azn("500"), stretch=None, table=RATES, home="AZN",
        cards=[_card("70.00", outcome="WITHDRAWN"), _card("70.00", closed=True)],
    )
    assert (line.paid, line.committed) == (0, 0)


def test_a_short_form_budget_has_no_currency_so_no_money() -> None:
    assert money_from({"application_budget": "150"}, "application_budget") is None
    assert money_from(None, "application_budget") is None
    assert money_from(
        {"application_budget": {"amount": "150.00", "currency": "EUR"}}, "application_budget"
    ) == Money(amount=Decimal("150.00"), currency="EUR")
```

Append to `tests/dashboard/test_counselor_board.py` (add `from apps.funding.rates import store` and `from .conftest import AZN_RATES, add_card, set_profile`):

```python
def test_the_budget_line_shows_on_both_boards(
    counselor_client, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    store(AZN_RATES)
    set_profile(
        agency_a, membership_a, country_of_residence="AZ",
        application_budget={"amount": "500.00", "currency": "AZN"},
    )
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
    expected = "Application budget 500 AZN · Paid 0 · Committed 150 · Free 350 (≈, see note)"
    body = counselor_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    assert expected in body
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard/test_money.py tests/dashboard/test_counselor_board.py`
Expected: FAIL — `cannot import name 'budget_line'`.

- [ ] **Step 2: Implement**

Append to `apps/dashboard/money.py` (add `from collections.abc import Mapping`, `from dataclasses import dataclass`, `from typing import TYPE_CHECKING`, `from pydantic import ValidationError`, `from apps.accounts.schemas import Money`, and under `if TYPE_CHECKING: from .board import Card`):

```python
#: Fees counted as committed while unpaid (§7.5). HELD joins as "on hold" in plan 3b.
COMMITTED = frozenset({"OPEN", "RELEASED"})


def money_from(snapshot: Mapping[str, object] | None, key: str) -> Money | None:
    """A Money answer from a stored profile, or None. A short-form profile's
    budget is a bare number with no currency, so it cannot be shown in AZN."""
    value = (snapshot or {}).get(key)
    if not isinstance(value, dict):
        return None
    try:
        return Money.model_validate(value)
    except ValidationError:
        return None


def _fees(count: int, reason: str) -> str:
    return f"{count} fee{'s' if count != 1 else ''} {reason} — not counted"


@dataclass(frozen=True)
class BudgetLine:
    """The board's money line (§7.5, §7.7), in the home currency. Never stored."""

    currency: str
    plan: Decimal
    extra: Decimal | None
    paid: Decimal
    committed: Decimal
    not_known: int
    no_rate: int
    converted: bool

    @property
    def free(self) -> Decimal:
        return max(Decimal("0"), self.plan - self.paid - self.committed)

    @property
    def used_from_extra(self) -> Decimal:
        return max(Decimal("0"), self.paid + self.committed - self.plan)

    @property
    def text(self) -> str:
        parts = [
            f"Application budget {whole(self.plan)} {self.currency}",
            f"Paid {whole(self.paid)}",
            f"Committed {whole(self.committed)}",
            f"Free {whole(self.free)}" + (" (≈, see note)" if self.converted else ""),
        ]
        if self.not_known:
            parts.append(_fees(self.not_known, "not known"))
        if self.no_rate:
            parts.append(_fees(self.no_rate, "without a rate yet"))
        return " · ".join(parts)

    @property
    def stretch_text(self) -> str:
        if not self.extra:
            return ""
        return (
            f"Plan {whole(self.plan)} {self.currency} · Extra allowed for exceptional cases: "
            f"up to {whole(self.extra)} · Used from extra: {whole(self.used_from_extra)}"
        )


def budget_line(
    *,
    budget: Money | None,
    stretch: Money | None,
    cards: Sequence[Card],
    table: RateTable | None,
    home: str,
) -> BudgetLine | None:
    """None when the budget itself cannot be shown in the home currency:
    nothing is better than a wrong figure."""
    if budget is None:
        return None
    plan = in_home(budget.amount, budget.currency, table, home)
    if plan is None:
        return None
    extra = in_home(stretch.amount, stretch.currency, table, home) if stretch else None
    paid = committed = Decimal("0")
    not_known = no_rate = 0
    converted = budget.currency != home
    for card in cards:
        live = not card.outcome and not card.closed
        # A programme (or accepted offer) with no stated fee, portal recorded
        # or not; a scholarship copies no fee and is not counted at all.
        if card.fee_state == "UNKNOWN" and not card.fee and not card.is_award and live:
            not_known += 1
            continue
        counted = card.fee_state == "PAID" or (card.fee_state in COMMITTED and live)
        if not counted or not card.fee:
            continue
        amount = in_home(card.fee, card.fee_currency, table, home)
        if amount is None:
            no_rate += 1
            continue
        converted = converted or card.fee_currency != home
        if card.fee_state == "PAID":
            paid += amount
        else:
            committed += amount
    return BudgetLine(home, plan, extra, paid, committed, not_known, no_rate, converted)
```

In `apps/dashboard/board.py`:
- import `BudgetLine, budget_line, money_from` from `.money`;
- `Board` gains `budget: BudgetLine | None = None` after `rate_note`;
- in `board_for`, replace the final `return Board(...)` with:

```python
    budget = budget_line(
        budget=money_from(snapshot, "application_budget"),
        stretch=money_from(snapshot, "budget_stretch"),
        cards=cards,
        table=rates,
        home=home,
    )
    converted = any(card.converted for card in cards) or (budget is not None and budget.converted)
    return Board(
        lanes=open_lanes,
        done=done,
        rates=rates,
        home=home,
        rate_note=rate_note(rates) if converted else "",
        budget=budget,
    )
```

In `templates/student/_board.html`, right after `<h2 id="board-heading">Your applications</h2>` and before the rate note:

```django
  {% if board.budget %}
    <p>{{ board.budget.text }}</p>
    {% if board.budget.stretch_text %}<p>{{ board.budget.stretch_text }}</p>{% endif %}
  {% endif %}
```

(The "Change my application budget" link is added in Task 7, when its URL exists.)

- [ ] **Step 3: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard tests/concierge`, then `uv run ruff check . && uv run mypy apps config`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-3 add apps/dashboard/money.py apps/dashboard/board.py templates/student/_board.html tests/dashboard/test_money.py tests/dashboard/test_counselor_board.py
git -C /home/orkhan/Desktop/lanes-plan-3 commit -m "feat(dashboard): the budget line -- paid, committed, free, and what is not counted (lanes §7.5, §7.7)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `budget_stretch` in the profile and the consultation

**Files:**
- Modify: `apps/accounts/schemas.py` (`StudentProfileSnapshot.budget_stretch`)
- Modify: `apps/accounts/consultation.py` (`QUESTION_LABELS`, `QUESTIONS`)
- Modify: `apps/accounts/forms.py` (`_JSON_VALUES`, `_OPTIONAL_VALUES`, `_canonical_value`)
- Modify: `tests/accounts/test_consultation_progress.py` (totals), `tests/acceptance/helpers.py` (`complete_consultation`)
- Test: `tests/accounts/test_budget_stretch.py`

**Interfaces:**
- Produces: `StudentProfileSnapshot.budget_stretch: Money | None = None` (no `schema_version` bump; snapshots without the key stay valid); the consultation question `budget_stretch`, asked always, after `application_budget`. Blank or 0 is stored as `None`.

The other tests the inventory named (`tests/accounts/test_question_labels.py`, `test_consultation.py`, `test_profile_schema_v3.py`, `test_profile_versions.py`, `tests/research/test_handle_research_message.py:41`, `tests/research/test_dispatch_recovery.py:26`, `tests/funding/test_spine.py:219`, `tests/funding/conftest.py:91`) build their payloads by key or use the short form, and an optional field with a default leaves them valid. Step 5 runs them to confirm; change one only if it fails.

- [ ] **Step 1: Write the failing tests**

`tests/accounts/test_budget_stretch.py`:

```python
from decimal import Decimal

import pytest
from django import forms

from apps.accounts.consultation import QUESTIONS
from apps.accounts.forms import _canonical_value, question_field
from apps.accounts.schemas import StudentProfileSnapshot
from tests.accounts.test_profile_schema_v3 import _answers


def test_the_stretch_is_asked_right_after_the_budget() -> None:
    keys = [question.key for question in QUESTIONS]
    assert keys[keys.index("application_budget") + 1] == "budget_stretch"


def test_the_stretch_question_may_be_left_blank() -> None:
    field = question_field("budget_stretch")
    assert isinstance(field, forms.JSONField)
    assert field.required is False


@pytest.mark.parametrize("value", [None, "", {"amount": "0", "currency": "AZN"}])
def test_blank_or_zero_means_no_stretch(value) -> None:
    assert _canonical_value("budget_stretch", value) is None


def test_a_stretch_is_kept_as_money() -> None:
    stored = _canonical_value("budget_stretch", {"amount": "150", "currency": "AZN"})
    assert stored["currency"] == "AZN"
    assert Decimal(stored["amount"]) == Decimal("150")


def test_an_old_snapshot_without_the_key_is_still_valid() -> None:
    assert StudentProfileSnapshot.model_validate(_answers()).budget_stretch is None


def test_a_snapshot_carries_the_stretch() -> None:
    profile = StudentProfileSnapshot.model_validate(
        _answers(budget_stretch={"amount": "150", "currency": "AZN"})
    )
    assert profile.budget_stretch.amount == Decimal("150")
```

Check `_answers` in `tests/accounts/test_profile_schema_v3.py` takes `**overrides` (it does: `return {**values, **overrides}`).

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/accounts/test_budget_stretch.py`
Expected: FAIL.

- [ ] **Step 2: The schema field**

In `apps/accounts/schemas.py`, in `StudentProfileSnapshot` after `funding_dependency`:

```python
    #: Optional extra the student allows ONLY for exceptional items (lanes spec
    #: §7.7). None means no stretch; blank and 0 are both stored as None.
    budget_stretch: Money | None = None
```

- [ ] **Step 3: The question**

In `apps/accounts/consultation.py`:
- add to `QUESTION_LABELS` after `"application_budget"`:

```python
    "budget_stretch": (
        "If an exceptional opportunity appears, how much more could you spend on "
        "application fees?"
    ),
```

- add `_question("budget_stretch", _always),` to `QUESTIONS` right after `_question("application_budget", _always),`.

In `apps/accounts/forms.py`:
- add `"budget_stretch",` to `_JSON_VALUES` and to `_OPTIONAL_VALUES`;
- in `_canonical_value`, replace

```python
    elif key in _JSON_VALUES and value in (None, ""):
        value = [] if key not in {"application_budget", "self_funding_capacity"} else value
```

  with

```python
    elif key in _JSON_VALUES and value in (None, ""):
        if key == "budget_stretch":
            return None  # blank: no stretch (lanes spec §7.7)
        value = [] if key not in {"application_budget", "self_funding_capacity"} else value
```

  and, after `validated = adapter.validate_python(value)` (inside the `try`'s success path, before the `return`):

```python
    if key == "budget_stretch" and validated is not None and validated.amount == 0:
        return None  # 0 means no stretch, as blank does
```

- [ ] **Step 4: The tests that count or order the questions**

In `tests/accounts/test_consultation_progress.py::test_the_short_set_totals_fourteen_or_fifteen_with_self_funding`, rename it `test_the_short_set_totals_fifteen_or_sixteen_with_self_funding` and change `14`, `15`, `16` to `15`, `16`, `17`.

In `tests/acceptance/helpers.py::complete_consultation`, add `("budget_stretch", ""),` right after the `("application_budget", …)` pair.

- [ ] **Step 5: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/accounts tests/acceptance tests/research/test_handle_research_message.py tests/research/test_dispatch_recovery.py tests/funding/test_spine.py`, then `uv run ruff check . && uv run mypy apps config`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-3 add apps/accounts/schemas.py apps/accounts/consultation.py apps/accounts/forms.py tests/accounts/test_budget_stretch.py tests/accounts/test_consultation_progress.py tests/acceptance/helpers.py
git -C /home/orkhan/Desktop/lanes-plan-3 commit -m "feat(accounts): the consultation asks for an optional budget stretch (lanes §7.7)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: "Change my application budget" (student only)

**Files:**
- Modify: `apps/accounts/views.py` (`budget_settings`), `apps/accounts/urls.py`
- Create: `templates/student/settings_budget.html`
- Modify: `templates/student/settings.html` (a link), `templates/student/_board.html` (the link on the budget line)
- Modify: `apps/dashboard/routes.py` (`_STUDENT["budget"]`), `apps/dashboard/board.py` (`Board.budget_url`)
- Test: `tests/dashboard/test_budget_settings.py` (beside the `pack` fixture in `tests/dashboard/conftest.py`)

**Interfaces:**
- Consumes: Task 5's `budget_line`, `BudgetLine.plan/paid/committed`, `in_home`, `whole`; Task 4's `Board.rates`, `Board.home`; Task 6's `budget_stretch`; `apps.portals.applications.remove_application(application, *, actor)`, `REFUSALS`, `ApplicationRefused`; `create_profile_version(*, student, snapshot)`.
- Produces: route `student/settings/budget/`, name `student-settings-budget` (GET and POST); `Board.budget_url: str = ""` (student only); `AuditEvent` `"profile.budget_changed"`.

Rules (spec §7.8): only the student; a raise is saved at once; below what is **paid** is refused with the paid figure; below **paid + committed** the student ticks which unpaid applications to drop, and the ticked fees must cover the shortfall; nothing is dropped unless ticked, and ticks are ignored when there is no shortfall. Saving writes a new profile version with every other answer unchanged. No research run starts: "New for you" (Task 8) reads the current run's pool against the new figure.

- [ ] **Step 1: Write the failing tests**

`tests/dashboard/test_budget_settings.py`:

```python
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.accounts.models import StudentProfileVersion
from apps.accounts.profile_versions import create_profile_version
from apps.accounts.schemas import Money
from apps.funding.models import AuditEvent, RecommendationCandidate
from apps.funding.rates import store
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import verify_mfa_session
from tests.funding.conftest import make_db_candidate, make_profile

from .conftest import AZN_RATES, add_card, set_profile

pytestmark = pytest.mark.django_db
PAGE = "/student/settings/budget/"


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


def _profile(agency, student, amount="500.00"):
    with tenant_scope(agency.id):
        return create_profile_version(
            student=student,
            snapshot=make_profile(
                country_of_residence="AZ",
                application_budget=Money(amount=Decimal(amount), currency="AZN"),
            ),
        )


def _latest(agency, student) -> dict:
    with tenant_scope(agency.id):
        return (
            StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
        ).snapshot


@pytest.fixture
def two_cards(agency_a, membership_a, pack, program_factory):
    """75 EUR (150 AZN) and 100 EUR (200 AZN), both unpaid: 350 AZN committed."""
    programme, _award = pack
    store(AZN_RATES)
    _profile(agency_a, membership_a)
    physics = make_db_candidate(agency_a, programme.run, program_name="M.Sc. Physics")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=physics.id).update(
            program_id=program_factory(name="M.Sc. Physics").id,
            application_fee="100.00", application_fee_currency="EUR",
        )
        physics.refresh_from_db()
        return add_card(agency_a, membership_a, programme), add_card(agency_a, membership_a, physics)


def test_a_student_raises_the_budget_and_every_other_answer_is_kept(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    before = _latest(agency_a, membership_a)
    client.force_login(user_a)

    response = client.post(
        PAGE, {"amount": "800", "currency": "AZN", "stretch": "100"}, HTTP_HOST=domain_a.host
    )

    assert response.status_code == 302
    after = _latest(agency_a, membership_a)
    assert Decimal(after["application_budget"]["amount"]) == 800
    assert after["application_budget"]["currency"] == "AZN"
    assert Decimal(after["budget_stretch"]["amount"]) == 100
    assert after["budget_stretch"]["currency"] == "AZN"
    unchanged = {k: v for k, v in before.items() if k not in ("application_budget", "budget_stretch")}
    assert {k: after[k] for k in unchanged} == unchanged
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(event="profile.budget_changed").count() == 1


def test_a_counsellor_cannot_reach_the_page(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a, two_cards
):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    other_settings = client.get("/student/settings/extension/", HTTP_HOST=domain_a.host)

    assert client.get(PAGE, HTTP_HOST=domain_a.host).status_code == other_settings.status_code
    response = client.post(PAGE, {"amount": "1", "currency": "AZN"}, HTTP_HOST=domain_a.host)
    assert response.status_code in (403, 404)
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 500


def test_below_what_is_paid_is_refused_with_the_paid_figure(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    """Review Focus 4."""
    informatics, _physics = two_cards
    with tenant_scope(agency_a.id):
        Application.objects.filter(id=informatics.id).update(
            fee_state="PAID", fee_paid_source="STUDENT"
        )
    client.force_login(user_a)

    response = client.post(PAGE, {"amount": "100", "currency": "AZN"}, HTTP_HOST=domain_a.host)

    assert response.status_code == 400
    assert "already paid 150 AZN" in response.content.decode()
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 500


def test_below_what_is_committed_needs_a_choice_and_drops_only_the_chosen(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    informatics, physics = two_cards
    client.force_login(user_a)

    refused = client.post(PAGE, {"amount": "200", "currency": "AZN"}, HTTP_HOST=domain_a.host)
    assert refused.status_code == 400
    # The error itself: the fieldset's legend says "Choose which…" on every GET.
    assert "150 AZN below the fees you've committed to" in refused.content.decode()
    with tenant_scope(agency_a.id):
        assert Application.objects.filter(student=membership_a).count() == 2

    saved = client.post(
        PAGE, {"amount": "200", "currency": "AZN", "drop": [str(physics.id)]},
        HTTP_HOST=domain_a.host,
    )

    assert saved.status_code == 302
    with tenant_scope(agency_a.id):
        assert list(
            Application.objects.filter(student=membership_a).values_list("id", flat=True)
        ) == [informatics.id]
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 200


def test_a_ticked_card_that_commits_nothing_frees_nothing(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    """A forged tick on a withdrawn card: its fee was never committed, so it
    cannot cover the shortfall and the budget is not saved."""
    informatics, physics = two_cards
    with tenant_scope(agency_a.id):
        Application.objects.filter(id=physics.id).update(outcome="WITHDRAWN")
    client.force_login(user_a)

    # Committed is now 150 (informatics); 100 is 50 short, and only physics is ticked.
    response = client.post(
        PAGE, {"amount": "100", "currency": "AZN", "drop": [str(physics.id)]},
        HTTP_HOST=domain_a.host,
    )

    assert response.status_code == 400
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 500


def test_a_short_form_profile_is_asked_to_finish_the_consultation(
    client, agency_a, domain_a, user_a, membership_a
):
    # The short form stores the budget as a bare number, with no currency.
    set_profile(agency_a, membership_a, funding_dependency="OPTIONAL", application_budget="150")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Finish your consultation first" in body


def test_the_board_links_the_student_and_not_the_counsellor(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert f'href="{PAGE}"' in body
    assert "Change my application budget" in body
```

The counsellor half of the last check (no link on the counsellor board) is added to `tests/dashboard/test_counselor_board.py::test_the_budget_line_shows_on_both_boards` as `assert "Change my application budget" not in body`.

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard/test_budget_settings.py`
Expected: FAIL — 404 on `/student/settings/budget/`.

- [ ] **Step 2: The view and the route**

In `apps/accounts/views.py`, add the imports:

```python
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.views.decorators.http import require_http_methods

from apps.dashboard.board import Board, Card, board_for
from apps.dashboard.money import budget_line, in_home, whole
from apps.funding.models import AuditEvent
from apps.portals.applications import REFUSALS, ApplicationRefused, remove_application
from apps.portals.models import Application
from apps.ratelimit import rate_limited
from apps.tenancy.services import current_membership

from .models import StudentProfileVersion
from .profile_versions import create_profile_version
from .schemas import Money, StudentProfileSnapshot
```

(merge with the existing `from .profile_versions import ProfileVersionRejected` line and the existing pydantic `ValidationError` import), then:

```python
_BUDGET_PAGE = "student/settings_budget.html"


def _droppable(card: Card) -> bool:
    """An unpaid fee the budget counts as committed (§7.5). The page lists only
    these, and only these may be ticked: a forged tick on a decided card would
    count money that was never committed towards the shortfall."""
    return card.fee_state == "OPEN" and bool(card.fee) and not card.outcome and not card.closed


def _latest_full_profile(student: Membership) -> StudentProfileSnapshot | None:
    """The newest full profile, or None for the short form (its budget is a
    bare number with no currency, so there is nothing to change it from)."""
    version = StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
    if version is None or version.schema_version != 3:
        return None
    try:
        return StudentProfileSnapshot.model_validate(version.snapshot)
    except ValidationError:
        return None


def _budget_page(
    request: HttpRequest,
    *,
    profile: StudentProfileSnapshot | None,
    board: Board | None = None,
    values: dict[str, str] | None = None,
    error: str = "",
    status: int = 200,
) -> HttpResponse:
    unpaid = [card for card in board.cards if _droppable(card)] if board is not None else []
    return render(
        request,
        _BUDGET_PAGE,
        {"profile": profile, "board": board, "values": values or {}, "unpaid": unpaid,
         "error": error},
        status=status,
    )


@login_required
@require_http_methods(["GET", "POST"])
def budget_settings(request: HttpRequest) -> HttpResponse:
    """"Change my application budget" (lanes spec §7.8). Only the student: a
    counsellor gets the same refusal every student settings page gives."""
    student = current_membership(request, Membership.Role.STUDENT)
    profile = _latest_full_profile(student)
    if profile is None:
        return _budget_page(request, profile=None)
    board = board_for(student)
    if request.method == "GET":
        stretch = profile.budget_stretch
        return _budget_page(request, profile=profile, board=board, values={
            "amount": str(profile.application_budget.amount),
            "currency": profile.application_budget.currency,
            "stretch": str(stretch.amount) if stretch else "",
        })
    values = {key: request.POST.get(key, "").strip() for key in ("amount", "currency", "stretch")}

    def refuse(error: str, status: int = 400) -> HttpResponse:
        return _budget_page(
            request, profile=profile, board=board, values=values, error=error, status=status
        )

    if rate_limited("budget-change", student.id, limit=10, window_seconds=3600):
        return refuse("Too many changes. Try again in an hour.", 429)
    try:
        budget = Money(amount=Decimal(values["amount"]), currency=values["currency"].upper())
        extra = Decimal(values["stretch"] or "0")
        stretch = Money(amount=extra, currency=budget.currency) if extra else None
    except (ValidationError, InvalidOperation):
        return refuse(
            "Enter the amounts as numbers and the currency as a 3-letter code, like 500 and AZN."
        )
    line = budget_line(
        budget=budget, stretch=None, cards=board.cards, table=board.rates, home=board.home
    )
    if line is None:
        return refuse(
            f"We can't convert {budget.currency} yet. Enter the budget in {board.home or 'AZN'}."
        )
    if line.plan < line.paid:
        return refuse(
            f"You've already paid {whole(line.paid, up=True)} {line.currency} in fees, so "
            "your budget can't go below that."
        )
    shortfall = line.paid + line.committed - line.plan
    chosen: list[Card] = []
    if shortfall > 0:
        picked = set(request.POST.getlist("drop"))
        chosen = [
            card for card in board.cards if str(card.application_id) in picked and _droppable(card)
        ]
        freed = sum(
            (in_home(c.fee, c.fee_currency, board.rates, board.home) or Decimal("0")
             for c in chosen if c.fee is not None),
            Decimal("0"),
        )
        if freed < shortfall:
            return refuse(
                f"Your new budget is {whole(shortfall, up=True)} {line.currency} below the "
                "fees you've committed to. Choose which unpaid applications to drop."
            )
    try:
        with transaction.atomic():
            for card in chosen:
                remove_application(
                    Application.objects.get(id=card.application_id, student=student),
                    actor=student,
                )
            create_profile_version(
                student=student,
                snapshot=profile.model_copy(
                    update={"application_budget": budget, "budget_stretch": stretch}
                ),
            )
            AuditEvent.objects.create(
                actor=student, event="profile.budget_changed", object_id=student.id
            )
    except ApplicationRefused as refused:
        return refuse(REFUSALS[refused.reason])
    messages.success(request, "Your application budget is saved.")
    return redirect("concierge-student-dashboard")
```

In `apps/accounts/urls.py`, import `budget_settings` and add `path("student/settings/budget/", budget_settings, name="student-settings-budget"),`.

In `apps/dashboard/routes.py`, add `"budget": "student-settings-budget",` to `_STUDENT` only.

In `apps/dashboard/board.py`, add `budget_url: str = ""` to `Board` after `budget`, and `budget_url=action_url(counselor_view, "budget", student.id),` to the final `Board(...)` in `board_for`.

- [ ] **Step 3: The templates**

`templates/student/settings_budget.html`:

```django
{% extends "base.html" %}
{% block title %}Application budget{% endblock %}
{% block content %}
<h1>Change my application budget</h1>
{% if not profile %}
  <p>Finish your consultation first: <a href="/student/profile/">Profile</a>.</p>
{% else %}
  {% if board.budget %}
    <p>{{ board.budget.text }}</p>
    {% if board.budget.stretch_text %}<p>{{ board.budget.stretch_text }}</p>{% endif %}
  {% endif %}
  {% if board.rate_note %}<p>{{ board.rate_note }}</p>{% endif %}
  {% if error %}<p role="alert" id="budget-error">{{ error }}</p>{% endif %}
  <form method="post">
    {% csrf_token %}
    <p>
      <label for="budget-amount">Budget for application fees</label>
      <input id="budget-amount" name="amount" inputmode="decimal" required value="{{ values.amount }}"{% if error %} aria-describedby="budget-error"{% endif %}>
    </p>
    <p>
      <label for="budget-currency">Currency (3 letters, like AZN)</label>
      <input id="budget-currency" name="currency" maxlength="3" required value="{{ values.currency }}">
    </p>
    <p>
      <label for="budget-stretch">Extra you'd allow for an exceptional opportunity (same currency; leave empty for none)</label>
      <input id="budget-stretch" name="stretch" inputmode="decimal" value="{{ values.stretch }}">
    </p>
    {% if unpaid %}
      <fieldset>
        <legend>Choose which unpaid applications to drop</legend>
        <p>Only needed when the new budget is below what you've committed to. Nothing is dropped unless you tick it.</p>
        {% for card in unpaid %}
          <p>
            <input type="checkbox" id="drop-{{ card.application_id }}" name="drop" value="{{ card.application_id }}">
            <label for="drop-{{ card.application_id }}">{{ card.title }} — fee {{ card.fee_text }}</label>
          </p>
        {% endfor %}
      </fieldset>
    {% endif %}
    <button type="submit">Save</button>
  </form>
{% endif %}
<p><a href="/student/settings/">Back to settings</a></p>
{% endblock %}
```

In `templates/student/settings.html`, add after the Profile item:

```django
    <li><a href="/student/settings/budget/">Application budget</a> — change my application budget</li>
```

In `templates/student/_board.html`, inside the `{% if board.budget %}` block, after the stretch line:

```django
    {% if board.budget_url %}<p><a href="{{ board.budget_url }}">Change my application budget</a></p>{% endif %}
```

- [ ] **Step 4: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/accounts tests/dashboard tests/tenancy/test_catalog_grants.py`, then `uv run ruff check . && uv run mypy apps config && uv run python manage.py check && uv run bandit -c pyproject.toml -r apps config`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-3 add apps/accounts/views.py apps/accounts/urls.py templates/student/settings_budget.html templates/student/settings.html templates/student/_board.html apps/dashboard/routes.py apps/dashboard/board.py tests/dashboard/test_budget_settings.py tests/dashboard/test_counselor_board.py
git -C /home/orkhan/Desktop/lanes-plan-3 commit -m "feat(accounts): the student changes their application budget and stretch; floors at paid and committed (lanes §7.8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The over-budget confirmation, and New for you (computed, never stored)

**Owner decision 2026-10-14:** adding any programme that does not fit the student's free budget needs the student's explicit confirmation, on one page, with plain numbers and one tick box saying how much more it costs. One page serves every path: Add, Replace (swapping a programme into the pack), and New for you. A counsellor may still add a programme that fits; an over-budget one is refused, because only the student spends.

**Files:**
- Modify: `apps/dashboard/money.py` (`OverKind`, `Overrun`, `over_budget`)
- Modify: `apps/dashboard/board.py` (`Board.budget_set`; `board_for`; `overrun_for`)
- Modify: `apps/portals/applications.py` (`own_candidate`; `add_application` uses it)
- Modify: `apps/portals/views.py` (`application_add`), `apps/funding/views.py` (`replace_candidate_view`), `apps/dashboard/views.py` (counsellor `add`)
- Create: `templates/student/over_budget.html`
- Create: `apps/dashboard/new_for_you.py`
- Modify: `apps/concierge/views.py` (`_student_dashboard_page`), `templates/student/dashboard.html`
- Test: `tests/dashboard/test_over_budget.py`, `tests/dashboard/test_new_for_you.py`

**Interfaces:**
- Consumes: Task 2's `RecommendationCandidate.rank` and over-budget pool rows, `BANK_MARGIN`; Task 4's `approx`, `in_home`, `whole(..., up=True)`, `Board.rates`, `Board.home`; Task 5's `money_from`, `BudgetLine` (`currency`, `free`, `extra`, `used_from_extra`), `Board.budget`; Task 7's route `student-settings-budget`; `apps.funding.services.current_pack`, `replace_candidate`; `apps.dashboard.pack.applied_candidate_ids`; `add_application`; `action_url`.
- Produces:
  - `apps/dashboard/money.py`: `OverKind = Literal["OVER", "STRETCH", "NO_RATE", "UNKNOWN", "BUDGET_NO_RATE"]`; `Overrun(kind: OverKind, fee_text: str = "", free: str = "", over: str = "", extra: str = "")` (amounts carry their unit, "40 AZN") with properties `body` and `tick`; `over_budget(*, fee: Decimal | None, currency: str, line: BudgetLine | None, budget_set: bool, table: RateTable | None, home: str) -> Overrun | None` (pure; `None` means it fits);
  - `apps/dashboard/board.py`: `Board.budget_set: bool = False` (the profile holds a budget with a currency, whether or not it converts); `overrun_for(student: Membership, candidate: RecommendationCandidate) -> Overrun | None`;
  - `apps/portals/applications.py`: `own_candidate(student: Membership, candidate_id: UUID) -> RecommendationCandidate | None`;
  - template `student/over_budget.html` (context: `overrun`, `action`, `hidden`, `refused`);
  - `AuditEvent`s `"application.added_over_budget"` (object: the card) and `"candidate.replaced_over_budget"` (object: the candidate swapped in); no amounts in either;
  - `Offer(candidate_id: UUID, title: str, fee_text: str, kind: Literal["FITS", "STRETCH", "OVER"], over_by: str, add_url: str)` with a `text` property; `add_url` is always the student's `student-application-add` URL;
  - `offers_for(student: Membership, *, board: Board, table: RateTable | None, home: str) -> tuple[Offer, ...]`.
  - There is no `student-application-add-stretch` route: the confirmation page replaced it.

**The fit rule** (`over_budget`, the one place it lives):
- **Fits:** fee in the home currency × `BANK_MARGIN` ≤ `BudgetLine.free`. Added at once, no page, as today. A stated fee of 0 always fits.
- **STRETCH:** doesn't fit, a stretch is set, and the shortfall (fee × margin − free) ≤ stretch − used from extra.
- **OVER:** doesn't fit, and no stretch (or it doesn't reach).
- **NO_RATE:** the fee's currency isn't in the rate table.
- **UNKNOWN:** the candidate states no fee.
- **BUDGET_NO_RATE:** the profile holds a budget, but it can't be shown in the home currency (a EUR budget before any rate row exists), so nothing can be compared.
- **No budget at all** (a short-form profile's bare number, or no budget answer): nothing to exceed, so no page, whatever the fee.
- "Left in your budget" is `whole(free)`. "Over" and "uses about N of your extra" are both the shortfall, `whole(..., up=True)`. "Your 150 AZN extra" is `whole(extra)`, the full stretch amount.

**The page** (exact wording, title "This is over your application budget"; the fee is `approx(...)`, so the original currency comes first, then "≈ N AZN"; "about" because the figure includes the 3% bank margin):

| Kind | Body | Tick box |
|---|---|---|
| OVER | "The application fee is 75.00 EUR ≈ 150 AZN. You have 100 AZN left in your budget, so adding it puts you about 55 AZN over." | "I understand this takes me about 55 AZN over my budget" |
| STRETCH | "The application fee is 75.00 EUR ≈ 150 AZN. It doesn't fit your plan, but it fits the extra you allowed: it uses about 55 AZN of your 100 AZN extra." | "Use about 55 AZN from my extra" |
| NO_RATE | "The application fee is 1200.00 ISK. We can't convert this currency yet, so we can't tell whether it fits your budget." | "Add it anyway" |
| UNKNOWN | "We don't know this programme's application fee yet, so we can't tell whether it fits your budget." | "Add it anyway" |
| BUDGET_NO_RATE | "The application fee is 75.00 EUR. We can't convert your budget's currency yet, so we can't tell whether it fits your budget." | "Add it anyway" |

Under the box, an [Add anyway] button that submits the form. The server refuses it unless the box was ticked (`confirm=1`). Without the tick it re-renders the page with "Tick the box to add it.". Next to the button are a "Change my budget" link (Task 7's page) and a "Cancel" link back to the recommendations page.

**Where it is enforced.** Each check runs on the server, in the view, before anything is written:
1. **Add** (`student-application-add`, `application_add`). If the programme doesn't fit and the POST has no `confirm=1`, the page renders (200) and nothing is created. With `confirm=1`, the programme is added and `application.added_over_budget` is recorded. A second confirmed POST finds the card through the existing `portal_app_one_per_candidate` path and says "This is already in your applications." That is never a 500 or a second card.
2. **Replace** (`student-replace-candidate`, `replace_candidate_view`). The same check runs on the candidate being swapped in, with the same page and the same tick. The page carries `replacement_candidate_id` as a hidden field. A confirmed swap records `candidate.replaced_over_budget`. This closes the Task 2 review finding (controller ruling, SDD ledger): over-budget pool rows could be swapped in with no check.
3. **New for you.** FITS rows add directly. STRETCH and OVER rows post to the same Add, which renders the page. Each row has one "Add to my applications" button.
4. **Counsellor add** (`counselor-student-application-add`, the dashboard `add`). An OVER or STRETCH programme is refused with "This is over {student.display_name}'s application budget. Only the student can add it." and nothing is created. A counsellor never gets the confirmation page or a tick box.

**Choices the code forced** (the brief did not make them):
- **A scholarship is never checked.** An award copies no fee (owner question 1), so every scholarship add would otherwise show the UNKNOWN page. `overrun_for` returns `None` for `opportunity_id` rows.
- **A candidate already on the board is never checked.** Its fee is already counted in `committed`, so checking it again would count it twice. This also makes the double-POST case land on "already in your applications".
- **A budget the system can't convert gets the BUDGET_NO_RATE kind and sentence** (the brief named the case, not the words).
- **A counsellor's add is refused only for OVER and STRETCH.** UNKNOWN, NO_RATE and BUDGET_NO_RATE programmes are not known to exceed anything, so the counsellor can add them as today (owner question 5).
- **The Replace view checks only a `VISIBLE` replacement.** `replace_candidate` keeps its own refusals (provenance, already in pack) and runs them after the page is confirmed, so a programme blocked for another reason is refused after its page, not before.
- **Every check builds the board (`board_for`) once per POST** for the budget line. Nothing new is stored.

New for you rules (unchanged in substance): which candidates come from the current pack's run, `VISIBLE`, eligible (`eligibility_status == ELIGIBLE`), a programme (`opportunity_id` is null) the engine ranked (`rank` set; this also leaves out student-named programmes), with a fee copy, not in the current pack and not already a card (by candidate, or by `program_id` for a card made from an earlier run's row), in `rank` order. Kinds come from `over_budget`: `None` is **FITS**. **STRETCH** and **OVER** are shown only for an **exceptional** item (§7.7 reasons 1 and 2: fully funded, meaning `funding_gap == 0` and not a placeholder; or `rank` smaller than the largest `rank` among the pack's paid programme candidates). A non-exceptional item that doesn't fit is not shown, and nor is a fee the table can't convert.

- [ ] **Step 1: Write the failing tests**

`tests/dashboard/test_over_budget.py`:

```python
"""One over-budget confirmation for every way a programme reaches the plan
(owner 2026-10-14): Add, Replace and New for you. A counsellor is refused."""

import html
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.dashboard.money import BudgetLine, over_budget
from apps.funding.models import AuditEvent, PackCandidate, PackVersion, RecommendationCandidate
from apps.funding.rates import store
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import reads_no_catalogue, verify_mfa_session
from tests.funding.conftest import make_db_candidate

from .conftest import AZN_RATES, set_profile

pytestmark = pytest.mark.django_db

TITLE = "This is over your application budget"


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


# --- the pure rule -----------------------------------------------------------


def _line(free: str, extra: str | None = None) -> BudgetLine:
    return BudgetLine(
        currency="AZN", plan=Decimal(free), extra=Decimal(extra) if extra else None,
        paid=Decimal("0"), committed=Decimal("0"), not_known=0, no_rate=0, converted=False,
    )


def _check(fee, *, line, budget_set=True, currency="AZN"):
    return over_budget(
        fee=None if fee is None else Decimal(fee), currency=currency, line=line,
        budget_set=budget_set, table=AZN_RATES, home="AZN",
    )


def test_an_exact_fit_is_not_over() -> None:
    assert _check("100.00", line=_line("103")) is None  # 100 x 1.03 == 103


def test_a_stated_zero_fee_always_fits() -> None:
    assert _check("0.00", line=_line("0")) is None


def test_one_cent_over_is_over_by_a_whole_unit_rounded_up() -> None:
    overrun = _check("100.01", line=_line("103"))
    assert (overrun.kind, overrun.free, overrun.over) == ("OVER", "103 AZN", "1 AZN")


@pytest.mark.parametrize(
    ("fee", "kind", "over"), [("109.70", "STRETCH", "10 AZN"), ("109.71", "OVER", "11 AZN")]
)
def test_the_extra_reaches_exactly_as_far_as_its_amount(fee, kind, over) -> None:
    # 109.70 x 1.03 = 112.991, 9.991 over 103; 109.71 x 1.03 = 113.0013, 10.0013 over.
    overrun = _check(fee, line=_line("103", extra="10"))
    assert (overrun.kind, overrun.over) == (kind, over)


def test_no_budget_has_nothing_to_exceed_but_one_we_cannot_convert_asks() -> None:
    assert _check("50.00", line=None, budget_set=False) is None
    overrun = _check("50.00", line=None)
    assert overrun.kind == "BUDGET_NO_RATE"
    assert overrun.body == (
        "The application fee is 50.00 AZN. We can't convert your budget's currency yet, "
        "so we can't tell whether it fits your budget."
    )
    assert overrun.tick == "Add it anyway"


# --- the student's Add -------------------------------------------------------


def _budget(agency, student, amount, stretch=None):
    snapshot = {
        "country_of_residence": "AZ",
        "application_budget": {"amount": amount, "currency": "AZN"},
    }
    if stretch:
        snapshot["budget_stretch"] = {"amount": stretch, "currency": "AZN"}
    set_profile(agency, student, **snapshot)


def _fee(agency, candidate, fee, currency="EUR"):
    with tenant_scope(agency.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(
            application_fee=fee, application_fee_currency=currency
        )


def _cards(agency, candidate) -> int:
    with tenant_scope(agency.id):
        return Application.objects.filter(candidate=candidate).count()


def _page(client, url, host, data=None) -> tuple[int, str]:
    """A POST that is expected to render the page: no write, no catalogue read."""
    with reads_no_catalogue():
        response = client.post(url, data or {}, HTTP_HOST=host)
    return response.status_code, html.unescape(response.content.decode())


def _add(candidate) -> str:
    return f"/student/applications/add/{candidate.id}/"


@pytest.fixture
def signed_in(client, user_a, pack):
    """The pack's programme: 75.00 EUR, 150 AZN, 154.50 with the bank margin."""
    store(AZN_RATES)
    client.force_login(user_a)
    return client


def test_an_over_budget_add_asks_first_and_adds_once_confirmed(
    signed_in, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    _budget(agency_a, membership_a, "100.00")

    status, body = _page(signed_in, _add(programme), domain_a.host)
    assert status == 200
    assert TITLE in body
    assert (
        "The application fee is 75.00 EUR ≈ 150 AZN. You have 100 AZN left in your budget, "
        "so adding it puts you about 55 AZN over."
    ) in body
    assert "I understand this takes me about 55 AZN over my budget" in body
    assert "Change my budget" in body
    assert _cards(agency_a, programme) == 0

    # Submitted without the tick (the browser's `required` bypassed): refused.
    status, body = _page(signed_in, _add(programme), domain_a.host, {"seen": "1"})
    assert status == 200 and "Tick the box to add it." in body
    assert _cards(agency_a, programme) == 0

    added = signed_in.post(_add(programme), {"confirm": "1"}, HTTP_HOST=domain_a.host)
    assert added.status_code == 302
    assert _cards(agency_a, programme) == 1

    again = signed_in.post(
        _add(programme), {"confirm": "1"}, HTTP_HOST=domain_a.host, follow=True
    )
    assert again.status_code == 200
    assert "This is already in your applications." in again.content.decode()
    assert _cards(agency_a, programme) == 1
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(
            actor=membership_a, event="application.added_over_budget"
        ).count() == 1


def test_a_programme_that_fits_is_added_at_once(signed_in, agency_a, domain_a, membership_a, pack):
    programme, _award = pack
    _budget(agency_a, membership_a, "200.00")
    response = signed_in.post(_add(programme), HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert _cards(agency_a, programme) == 1


@pytest.mark.parametrize(
    ("stretch", "fee", "currency", "sentence", "tick"),
    [
        (
            "100.00", "75.00", "EUR",
            "The application fee is 75.00 EUR ≈ 150 AZN. It doesn't fit your plan, but it fits "
            "the extra you allowed: it uses about 55 AZN of your 100 AZN extra.",
            "Use about 55 AZN from my extra",
        ),
        (
            None, "1200.00", "ISK",
            "The application fee is 1200.00 ISK. We can't convert this currency yet, so we "
            "can't tell whether it fits your budget.",
            "Add it anyway",
        ),
        (
            None, None, "",
            "We don't know this programme's application fee yet, so we can't tell whether it "
            "fits your budget.",
            "Add it anyway",
        ),
    ],
    ids=["stretch", "no-rate", "unknown"],
)
def test_the_page_says_why_it_asks(
    signed_in, agency_a, domain_a, membership_a, pack, stretch, fee, currency, sentence, tick
):
    programme, _award = pack
    _budget(agency_a, membership_a, "100.00", stretch=stretch)
    _fee(agency_a, programme, fee, currency)
    status, body = _page(signed_in, _add(programme), domain_a.host)
    assert status == 200
    assert sentence in body
    assert tick in body
    assert _cards(agency_a, programme) == 0


def test_a_scholarship_copies_no_fee_and_is_added_without_the_page(
    signed_in, agency_a, domain_a, membership_a, pack
):
    _programme, award = pack
    _budget(agency_a, membership_a, "100.00")
    assert signed_in.post(_add(award), HTTP_HOST=domain_a.host).status_code == 302
    assert _cards(agency_a, award) == 1


def test_a_short_form_budget_has_nothing_to_exceed(
    signed_in, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    set_profile(agency_a, membership_a, country_of_residence="AZ", application_budget="50")
    _fee(agency_a, programme, None, "")
    assert signed_in.post(_add(programme), HTTP_HOST=domain_a.host).status_code == 302
    assert _cards(agency_a, programme) == 1


# --- Replace -------------------------------------------------------------------


@pytest.fixture
def swap_in(agency_a, pack):
    """A pool item outside the pack: 120.00 EUR, 240 AZN, 247.20 with the margin."""
    programme, _award = pack
    item = make_db_candidate(agency_a, programme.run, program_name="MSc Pool")
    _fee(agency_a, item, "120.00")
    return item


def _replace(candidate) -> str:
    return f"/student/recommendation/candidates/{candidate.id}/replace/"


def _in_pack(agency, candidate) -> bool:
    with tenant_scope(agency.id):
        latest = PackVersion.objects.filter(run_id=candidate.run_id).order_by("-version").first()
        return PackCandidate.objects.filter(pack_version=latest, candidate=candidate).exists()


def test_an_over_budget_swap_in_asks_first_and_swaps_once_confirmed(
    signed_in, agency_a, domain_a, membership_a, pack, swap_in
):
    programme, _award = pack
    _budget(agency_a, membership_a, "200.00")
    choice = {"replacement_candidate_id": str(swap_in.id)}

    status, body = _page(signed_in, _replace(programme), domain_a.host, choice)
    assert status == 200
    assert (
        "The application fee is 120.00 EUR ≈ 240 AZN. You have 200 AZN left in your budget, "
        "so adding it puts you about 48 AZN over."
    ) in body
    assert f'value="{swap_in.id}"' in body  # the page carries the choice to the confirm
    assert not _in_pack(agency_a, swap_in)

    done = signed_in.post(_replace(programme), {**choice, "confirm": "1"}, HTTP_HOST=domain_a.host)
    assert done.status_code == 302
    assert _in_pack(agency_a, swap_in)
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(
            actor=membership_a, event="candidate.replaced_over_budget", object_id=swap_in.id
        ).exists()


def test_a_swap_in_that_fits_is_made_at_once(
    signed_in, agency_a, domain_a, membership_a, pack, swap_in
):
    programme, _award = pack
    _budget(agency_a, membership_a, "300.00")
    done = signed_in.post(
        _replace(programme), {"replacement_candidate_id": str(swap_in.id)},
        HTTP_HOST=domain_a.host,
    )
    assert done.status_code == 302
    assert _in_pack(agency_a, swap_in)


# --- the counsellor ------------------------------------------------------------


@pytest.fixture
def counselor_client(client, agency_a, counselor_user, counselor_membership, membership_a, pack):
    store(AZN_RATES)
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    return client


def _counselor_add(client, student, candidate, host):
    return client.post(
        f"/counselor/students/{student.id}/applications/add/{candidate.id}/",
        HTTP_HOST=host, follow=True,
    )


def test_a_counsellor_cannot_add_an_over_budget_programme(
    counselor_client, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    _budget(agency_a, membership_a, "100.00")
    body = html.unescape(
        _counselor_add(counselor_client, membership_a, programme, domain_a.host).content.decode()
    )
    assert (
        f"This is over {membership_a.display_name}'s application budget. "
        "Only the student can add it."
    ) in body
    assert _cards(agency_a, programme) == 0
    # The counsellor never gets the confirmation page or a tick box.
    assert TITLE not in body
    assert "Add anyway" not in body
    assert 'name="confirm"' not in body


def test_a_counsellor_still_adds_a_programme_that_fits(
    counselor_client, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    _budget(agency_a, membership_a, "200.00")
    _counselor_add(counselor_client, membership_a, programme, domain_a.host)
    assert _cards(agency_a, programme) == 1
```

`tests/dashboard/test_new_for_you.py`:

```python
import pytest
from django.core.cache import cache

from apps.dashboard.board import board_for
from apps.dashboard.new_for_you import offers_for
from apps.funding.models import RecommendationCandidate
from apps.funding.rates import store
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import reads_no_catalogue, verify_mfa_session
from tests.funding.conftest import make_db_candidate

from .conftest import AZN_RATES, set_profile

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


def _pool_item(agency, run, name, *, rank, gap="500.00", fee="120.00"):
    """A ranked programme in the run's pool, not in the pack: 120 EUR is 240 AZN,
    247.20 with the bank margin."""
    candidate = make_db_candidate(agency, run, program_name=name, funding_gap=gap)
    with tenant_scope(agency.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(
            application_fee=fee, application_fee_currency="EUR", rank=rank
        )
    return candidate


@pytest.fixture
def pool(agency_a, membership_a, pack):
    """The pack's programme is the last paid item, at rank 3."""
    programme, _award = pack
    store(AZN_RATES)
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(rank=3)
    return {
        "above": _pool_item(agency_a, programme.run, "MSc Above", rank=2),
        "funded": _pool_item(agency_a, programme.run, "MSc Funded", rank=9, gap="0.00"),
        "ordinary": _pool_item(agency_a, programme.run, "MSc Ordinary", rank=8),
    }


def _offers(agency, student):
    with tenant_scope(agency.id), reads_no_catalogue():
        board = board_for(student)
        return {o.title: o for o in offers_for(student, board=board, table=board.rates,
                                               home=board.home)}


def _budget(agency, student, amount, stretch=None):
    snapshot = {
        "country_of_residence": "AZ",
        "application_budget": {"amount": amount, "currency": "AZN"},
    }
    if stretch:
        snapshot["budget_stretch"] = {"amount": stretch, "currency": "AZN"}
    set_profile(agency, student, **snapshot)


def test_a_raised_budget_offers_the_over_budget_programmes_that_now_fit(
    agency_a, membership_a, pool
):
    _budget(agency_a, membership_a, "300.00")
    offers = _offers(agency_a, membership_a)
    assert {title: o.kind for title, o in offers.items()} == {
        "MSc Above": "FITS", "MSc Funded": "FITS", "MSc Ordinary": "FITS",
    }
    assert offers["MSc Above"].text == "MSc Above — fee 120.00 EUR ≈ 240 AZN, fits your plan"
    assert offers["MSc Above"].add_url == f"/student/applications/add/{pool['above'].id}/"
    assert list(offers) == ["MSc Above", "MSc Ordinary", "MSc Funded"]  # rank order


@pytest.mark.parametrize("name", ["MSc Above", "MSc Funded"])
def test_each_exceptional_reason_is_worth_stretching_for_with_a_stretch(
    agency_a, membership_a, pool, name
):
    _budget(agency_a, membership_a, "200.00", stretch="100.00")
    offer = _offers(agency_a, membership_a)[name]
    assert offer.kind == "STRETCH"
    assert offer.text == (
        f"Worth stretching for: {name} — fee 120.00 EUR ≈ 240 AZN, 48 AZN over your plan "
        "(within the extra you allowed)"
    )
    # The same Add as every other row: it renders the over-budget page.
    assert offer.add_url == f"/student/applications/add/{offer.candidate_id}/"


@pytest.mark.parametrize("name", ["MSc Above", "MSc Funded"])
def test_without_a_stretch_an_exceptional_item_is_over_your_plan(
    agency_a, membership_a, pool, name
):
    _budget(agency_a, membership_a, "200.00")
    offer = _offers(agency_a, membership_a)[name]
    assert offer.kind == "OVER"
    assert offer.add_url == f"/student/applications/add/{offer.candidate_id}/"
    assert offer.text == f"{name} — fee 120.00 EUR ≈ 240 AZN. Over your plan by 48 AZN"


def test_an_ordinary_item_that_does_not_fit_is_not_shown(agency_a, membership_a, pool):
    _budget(agency_a, membership_a, "200.00", stretch="100.00")
    assert "MSc Ordinary" not in _offers(agency_a, membership_a)


def test_an_item_already_a_card_or_in_the_pack_is_not_offered(agency_a, membership_a, pool):
    from apps.portals.applications import add_application

    _budget(agency_a, membership_a, "300.00")
    with tenant_scope(agency_a.id):
        # A pool item names no catalogue row, so the card takes its own id.
        add_application(student=membership_a, candidate_id=pool["above"].id, actor=membership_a)
    offers = _offers(agency_a, membership_a)
    assert "MSc Above" not in offers
    assert "M.Sc. Informatics" not in offers


def test_a_programme_already_a_card_from_an_earlier_run_is_not_offered(
    agency_a, membership_a, pool, program_factory
):
    """A newer run copies the programme as a new candidate row; the card made
    from the older row (here an accepted offer naming it) is still that programme."""
    _budget(agency_a, membership_a, "300.00")
    row = program_factory(name="MSc Above")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=pool["above"].id).update(program_id=row.id)
        Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=row.id, name="MSc Above"
        )
    offers = _offers(agency_a, membership_a)
    assert "MSc Above" not in offers
    assert "MSc Ordinary" in offers  # the rest of the pool is still offered


def test_new_for_you_is_on_the_student_home_and_never_on_the_counsellor_board(
    client, agency_a, domain_a, user_a, membership_a, counselor_user, counselor_membership, pool
):
    _budget(agency_a, membership_a, "300.00")
    client.force_login(user_a)
    assert "New for you" in client.get("/student/", HTTP_HOST=domain_a.host).content.decode()

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    body = client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    # The counsellor's page does render this student's money (the budget
    # line), so the absence below is about the offers, not an empty page.
    assert "Application budget 300 AZN" in body
    assert "New for you" not in body
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard/test_over_budget.py tests/dashboard/test_new_for_you.py`
Expected: FAIL. `test_over_budget.py` fails with `ImportError: cannot import name 'over_budget' from 'apps.dashboard.money'`, and `test_new_for_you.py` fails with `No module named 'apps.dashboard.new_for_you'`.

- [ ] **Step 2: The rule, in `apps/dashboard/money.py`**

Add `BANK_MARGIN` to the existing `from apps.funding.fx import …` line, then append:

```python
OverKind = Literal["OVER", "STRETCH", "NO_RATE", "UNKNOWN", "BUDGET_NO_RATE"]


@dataclass(frozen=True)
class Overrun:
    """Why adding a programme needs the student's tick (owner 2026-10-14).
    Amounts carry their unit ("40 AZN"); "about" because they include the
    bank margin."""

    kind: OverKind
    fee_text: str = ""
    free: str = ""
    over: str = ""
    extra: str = ""

    @property
    def body(self) -> str:
        fee = f"The application fee is {self.fee_text}."
        cannot_tell = "so we can't tell whether it fits your budget."
        if self.kind == "OVER":
            return (
                f"{fee} You have {self.free} left in your budget, so adding it puts you "
                f"about {self.over} over."
            )
        if self.kind == "STRETCH":
            return (
                f"{fee} It doesn't fit your plan, but it fits the extra you allowed: it uses "
                f"about {self.over} of your {self.extra} extra."
            )
        if self.kind == "NO_RATE":
            return f"{fee} We can't convert this currency yet, {cannot_tell}"
        if self.kind == "BUDGET_NO_RATE":
            return f"{fee} We can't convert your budget's currency yet, {cannot_tell}"
        return f"We don't know this programme's application fee yet, {cannot_tell}"

    @property
    def tick(self) -> str:
        if self.kind == "OVER":
            return f"I understand this takes me about {self.over} over my budget"
        if self.kind == "STRETCH":
            return f"Use about {self.over} from my extra"
        return "Add it anyway"


def over_budget(
    *,
    fee: Decimal | None,
    currency: str,
    line: BudgetLine | None,
    budget_set: bool,
    table: RateTable | None,
    home: str,
) -> Overrun | None:
    """None when the fee fits what is free (fee x BANK_MARGIN <= free), else why
    the student must confirm. A stated 0 always fits. With no budget at all
    (``budget_set`` False: a short-form profile) there is nothing to exceed;
    a budget that exists but cannot be compared still asks."""
    if fee == 0 or (line is None and not budget_set):
        return None
    if fee is None:
        return Overrun("UNKNOWN")
    fee_text = approx(fee, currency, table, home)
    if line is None:
        return Overrun("BUDGET_NO_RATE", fee_text)
    amount = in_home(fee, currency, table, home)
    if amount is None:
        return Overrun("NO_RATE", fee_text)
    over = amount * BANK_MARGIN - line.free
    if over <= 0:
        return None
    unit = line.currency
    room = (line.extra - line.used_from_extra) if line.extra else None
    return Overrun(
        "STRETCH" if room is not None and over <= room else "OVER",
        fee_text,
        free=f"{whole(line.free)} {unit}",
        over=f"{whole(over, up=True)} {unit}",
        extra=f"{whole(line.extra)} {unit}" if line.extra else "",
    )
```

(`Literal` and `dataclass` are already imported in `money.py` by Tasks 4 and 5.)

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard/test_over_budget.py -k "exact_fit or zero_fee or one_cent or reaches_exactly or one_we_cannot_convert"`
Expected: the five pure tests PASS. The view tests still fail, and so does `test_new_for_you.py`.

- [ ] **Step 3: `overrun_for`, `own_candidate`, and the three views**

In `apps/dashboard/board.py`:
- import `Overrun, over_budget` from `.money` (merge with the existing `.money` import);
- `Board` gains `budget_set: bool = False` after `budget_url`;
- in `board_for`, replace the `budget = budget_line(budget=money_from(snapshot, "application_budget"), …)` call's first argument with a named value, and pass it on:

```python
    budget_money = money_from(snapshot, "application_budget")
    budget = budget_line(
        budget=budget_money,
        stretch=money_from(snapshot, "budget_stretch"),
        cards=cards,
        table=rates,
        home=home,
    )
```

and add `budget_set=budget_money is not None,` to the final `Board(...)`;
- after `board_for`, add:

```python
def overrun_for(student: Membership, candidate: RecommendationCandidate) -> Overrun | None:
    """The over-budget check every Add and swap-in shares, and the counsellor's
    refusal (owner 2026-10-14). None: go ahead, no page.

    A scholarship copies no fee (owner question 1), so it has nothing to weigh.
    A candidate already on the board is counted there already: checking it
    again would count its fee twice."""
    if candidate.opportunity_id is not None:
        return None
    if Application.objects.filter(student=student, candidate=candidate).exists():
        return None
    board = board_for(student)
    return over_budget(
        fee=candidate.application_fee,
        currency=candidate.application_fee_currency,
        line=board.budget,
        budget_set=board.budget_set,
        table=board.rates,
        home=board.home,
    )
```

In `apps/portals/applications.py`, add above `add_application`:

```python
def own_candidate(student: Membership, candidate_id: UUID) -> RecommendationCandidate | None:
    """A reviewed candidate from one of this student's own runs, or None."""
    return RecommendationCandidate.objects.filter(
        id=candidate_id,
        run__profile_version__student=student,
        state=RecommendationCandidate.State.VISIBLE,
    ).first()
```

Then, in `add_application`, replace the `candidate = RecommendationCandidate.objects.filter(…).first()` statement with `candidate = own_candidate(student, candidate_id)`.

In `apps/portals/views.py`:
- add `from django.urls import reverse` and `from apps.dashboard.board import overrun_for`;
- add `own_candidate` to the `.applications` import;
- replace `application_add` with:

```python
_OVER_BUDGET_PAGE = "student/over_budget.html"


@login_required
@require_POST
def application_add(request: HttpRequest, candidate_id: UUID) -> HttpResponse:
    """Add to my applications. A programme that doesn't fit the free budget
    renders the over-budget page first, and only its ticked box (``confirm=1``)
    adds it (owner 2026-10-14): enforced here, not by the template."""
    student = current_membership(request, Membership.Role.STUDENT)
    candidate = own_candidate(student, candidate_id)
    already = (
        candidate is not None
        and Application.objects.filter(student=student, candidate=candidate).exists()
    )
    overrun = overrun_for(student, candidate) if candidate is not None else None
    if overrun is not None and request.POST.get("confirm") != "1":
        return render(request, _OVER_BUDGET_PAGE, {
            "overrun": overrun,
            "action": reverse("student-application-add", args=[candidate_id]),
            "hidden": {},
            "refused": request.POST.get("seen") == "1",
        })
    try:
        card = add_application(student=student, candidate_id=candidate_id, actor=student)
    except ApplicationRefused as refused:
        if refused.reason == "not_found":
            raise Http404 from refused
        messages.error(request, REFUSALS[refused.reason])
        return redirect("student-recommendation")
    if already:
        messages.info(request, "This is already in your applications.")
        return redirect("concierge-student-dashboard")
    if overrun is not None:
        AuditEvent.objects.create(
            actor=student, event="application.added_over_budget", object_id=card.id
        )
    messages.success(request, "Added to your applications.")
    return redirect("concierge-student-dashboard")
```

In `apps/funding/views.py`:
- add `from django.urls import reverse` and `from apps.dashboard.board import overrun_for`;
- add `AuditEvent` to the `.models` import;
- in `replace_candidate_view`, replace the final `try: replace_candidate(…) … return _render(request, student)` with:

```python
    # The same over-budget page as Add (owner 2026-10-14), for the programme
    # being swapped in. replace_candidate's own refusals still run after it.
    replacement = RecommendationCandidate.objects.filter(
        id=replacement_id, run_id=pack.run_id, state=RecommendationCandidate.State.VISIBLE
    ).first()
    overrun = overrun_for(student, replacement) if replacement is not None else None
    if overrun is not None and request.POST.get("confirm") != "1":
        return render(request, "student/over_budget.html", {
            "overrun": overrun,
            "action": reverse("student-replace-candidate", args=[candidate_id]),
            "hidden": {"replacement_candidate_id": str(replacement_id)},
            "refused": request.POST.get("seen") == "1",
        })
    try:
        replace_candidate(pack, candidate_id, replacement_id, student)
    except (PackCommandError, ValueError, ValidationError) as error:
        return _replace_error(str(error))
    if overrun is not None:
        AuditEvent.objects.create(
            actor=student, event="candidate.replaced_over_budget", object_id=replacement_id
        )
    return _render(request, student)
```

In `apps/dashboard/views.py`:
- add `overrun_for` to the `.board` import, and `own_candidate` to the `apps.portals.applications` import;
- in `add`, between the `paused` check and the `try:`:

```python
    # Only the student spends (owner 2026-10-14): a counsellor adds what fits,
    # and gets no confirmation page for what doesn't.
    candidate = own_candidate(student, candidate_id)
    overrun = overrun_for(student, candidate) if candidate is not None else None
    if overrun is not None and overrun.kind in ("OVER", "STRETCH"):
        messages.error(
            request,
            f"This is over {student.display_name}'s application budget. "
            "Only the student can add it.",
        )
        return _back(student)
```

Create `templates/student/over_budget.html`:

```django
{% extends "base.html" %}
{% block title %}Over your budget{% endblock %}
{% block content %}
  <h1>This is over your application budget</h1>
  {% if refused %}<p role="alert" id="confirm-error">Tick the box to add it.</p>{% endif %}
  <p>{{ overrun.body }}</p>
  <form method="post" action="{{ action }}">
    {% csrf_token %}
    {% for name, value in hidden.items %}<input type="hidden" name="{{ name }}" value="{{ value }}">{% endfor %}
    <input type="hidden" name="seen" value="1">
    <p>
      <input type="checkbox" id="confirm" name="confirm" value="1" required{% if refused %} aria-describedby="confirm-error"{% endif %}>
      <label for="confirm">{{ overrun.tick }}</label>
    </p>
    <button type="submit">Add anyway</button>
  </form>
  <p><a href="{% url 'student-settings-budget' %}">Change my budget</a> · <a href="{% url 'student-recommendation' %}">Cancel</a></p>
{% endblock %}
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard/test_over_budget.py tests/portals/test_applications.py tests/funding/test_student_controls.py tests/funding/test_named_program_gate.py tests/dashboard/test_counselor_board.py`
Expected: PASS. The existing add and replace tests store no budget (`make_run` writes an empty snapshot), so they never see the page.

- [ ] **Step 4: Write `apps/dashboard/new_for_you.py`**

```python
"""New for you (lanes spec §7.7, §7.9): pool items the budget now has room for.

Computed on every view from the current pack's run, never stored. Only the
student sees it; the counsellor board never renders it. Adding is always one
click and never automatic. An item that doesn't fit goes through the same
over-budget confirmation page as every other Add (owner 2026-10-14).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from apps.funding.fx import RateTable
from apps.funding.models import PackCandidate, RecommendationCandidate
from apps.funding.services import current_pack
from apps.portals.models import Application
from apps.tenancy.models import Membership

from .board import Board
from .money import approx, over_budget
from .pack import applied_candidate_ids
from .routes import action_url

Kind = Literal["FITS", "STRETCH", "OVER"]


@dataclass(frozen=True)
class Offer:
    candidate_id: UUID
    title: str
    fee_text: str
    kind: Kind
    #: How much more the plan would need, margin included: "48 AZN". "" for FITS.
    over_by: str
    #: Always the student's Add; one that doesn't fit renders the confirmation page.
    add_url: str

    @property
    def text(self) -> str:
        if self.kind == "FITS":
            return f"{self.title} — fee {self.fee_text}, fits your plan"
        if self.kind == "STRETCH":
            return (
                f"Worth stretching for: {self.title} — fee {self.fee_text}, "
                f"{self.over_by} over your plan (within the extra you allowed)"
            )
        return f"{self.title} — fee {self.fee_text}. Over your plan by {self.over_by}"


def _exceptional(candidate: RecommendationCandidate, last_paid: int | None) -> bool:
    """§7.7 reasons 1 and 2: fully funded, or ranked above the plan's last paid item."""
    if candidate.funding_gap == 0 and not candidate.funding_gap_is_placeholder:
        return True
    return last_paid is not None and candidate.rank is not None and candidate.rank < last_paid


def offers_for(
    student: Membership, *, board: Board, table: RateTable | None, home: str
) -> tuple[Offer, ...]:
    budget = board.budget
    pack = current_pack(student)
    if budget is None or pack is None:
        return ()
    members = [
        member.candidate
        for member in PackCandidate.objects.filter(pack_version=pack).select_related("candidate")
    ]
    # The last paid item the plan holds (§7.7 reason 2): the worst-ranked paid programme.
    last_paid = max(
        (
            c.rank for c in members
            if c.opportunity_id is None and c.rank is not None and (c.application_fee or 0) > 0
        ),
        default=None,
    )
    taken = {c.id for c in members} | applied_candidate_ids(student)
    pool = (
        RecommendationCandidate.objects.filter(
            run_id=pack.run_id,
            state=RecommendationCandidate.State.VISIBLE,
            opportunity_id__isnull=True,
            rank__isnull=False,
            application_fee__isnull=False,
        )
        .exclude(id__in=taken)
        # Each run copies a programme as a new candidate row, so a card made
        # from an older run's row is the same programme: not "new".
        .exclude(program_id__in=Application.objects.filter(student=student).values("program_id"))
        .order_by("rank")
    )
    offers: list[Offer] = []
    for candidate in pool:
        if candidate.eligibility_status != RecommendationCandidate.EligibilityStatus.ELIGIBLE:
            continue
        assert candidate.application_fee is not None
        overrun = over_budget(
            fee=candidate.application_fee,
            currency=candidate.application_fee_currency,
            line=budget,
            budget_set=True,
            table=table,
            home=home,
        )
        kind: Kind
        if overrun is None:
            kind = "FITS"
        elif overrun.kind in ("STRETCH", "OVER") and _exceptional(candidate, last_paid):
            kind = "STRETCH" if overrun.kind == "STRETCH" else "OVER"
        else:
            continue  # an ordinary item that doesn't fit, or a fee we can't convert
        offers.append(Offer(
            candidate.id,
            candidate.program_name,
            approx(candidate.application_fee, candidate.application_fee_currency, table, home),
            kind,
            overrun.over if overrun is not None else "",
            action_url(False, "add", student.id, candidate.id),
        ))
    return tuple(offers)
```

- [ ] **Step 5: The page**

In `apps/concierge/views.py::_student_dashboard_page`, add `from apps.dashboard.new_for_you import offers_for` and the context key:

```python
            "offers": offers_for(student, board=board, table=board.rates, home=board.home),
```

In `templates/student/dashboard.html`, after `{% include "student/_needs.html" %}`:

```django
  {% if offers %}
    <section aria-labelledby="new-heading">
      <h2 id="new-heading">New for you</h2>
      <ul>
        {% for offer in offers %}
          <li>
            <p>{{ offer.text }}</p>
            <form method="post" action="{{ offer.add_url }}">{% csrf_token %}<button type="submit">Add to my applications</button></form>
          </li>
        {% endfor %}
      </ul>
    </section>
  {% endif %}
```

- [ ] **Step 6: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/dashboard tests/concierge tests/portals tests/funding tests/tenancy/test_catalog_grants.py`, then `uv run ruff check . && uv run mypy apps config && uv run python manage.py check && uv run bandit -c pyproject.toml -r apps config`.
Expected: all pass.

```bash
git -C /home/orkhan/Desktop/lanes-plan-3 add apps/dashboard/money.py apps/dashboard/board.py apps/dashboard/new_for_you.py apps/dashboard/views.py apps/portals/applications.py apps/portals/views.py apps/funding/views.py apps/concierge/views.py templates/student/over_budget.html templates/student/dashboard.html tests/dashboard/test_over_budget.py tests/dashboard/test_new_for_you.py
git -C /home/orkhan/Desktop/lanes-plan-3 commit -m "feat(dashboard): one over-budget confirmation for add, replace and New for you (lanes §7.7, §7.9)

Owner 2026-10-14: a programme that doesn't fit the free budget needs the
student's tick on one page; a counsellor's over-budget add is refused.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: A fee receipt in the mail marks the fee paid

**Files:**
- Modify: `apps/mailbox/models.py` (`MailSignal.Label.FEE_PAID`)
- Create: `apps/mailbox/migrations/0011_mail_signal_fee_paid.py` (generated)
- Modify: `apps/mailbox/classify.py` (`MailVerdict.label`, `_DEVELOPER`)
- Modify: `apps/mailbox/actions.py` (`_ALERTS`, `apply_verdict`)
- Test: `tests/mailbox/test_actions.py`, `tests/mailbox/test_classify.py`

**Interfaces:**
- Consumes: Task 3's `mark_fee_paid`, `Application.FeePaidSource.MAIL`.
- Produces: label `FEE_PAID` ("Fee payment received"). Only a **trusted** message (`authenticated=True`) on an application whose fee is `OPEN` or `UNKNOWN` marks it `PAID`, with `fee_paid_source=MAIL` and `fee_paid_at` = the signal's `received_at`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/mailbox/test_actions.py`:

```python
@pytest.mark.django_db
def test_a_trusted_fee_receipt_marks_the_fee_paid(signal_on_application) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        Application.objects.filter(id=signal.application_id).update(fee_state="OPEN")

        apply_verdict(
            signal, MailVerdict(label="FEE_PAID"), link_hosts=ALLOWED, authenticated=True
        )

        application = Application.objects.get(id=signal.application_id)
    assert (application.fee_state, application.fee_paid_source) == ("PAID", "MAIL")
    assert application.fee_paid_at == signal.received_at


@pytest.mark.django_db
@pytest.mark.parametrize("vouched", [False, True])
def test_an_untrusted_fee_receipt_never_changes_the_fee_state(
    signal_on_application, vouched
) -> None:
    """Spec §15: untrusted mail never changes fee_state. Anyone can write a
    university's address into a From line."""
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        Application.objects.filter(id=signal.application_id).update(fee_state="OPEN")

        apply_verdict(
            signal, MailVerdict(label="FEE_PAID"), link_hosts=ALLOWED,
            authenticated=False, vouched=vouched,
        )

        application = Application.objects.get(id=signal.application_id)
    assert (application.fee_state, application.fee_paid_source) == ("OPEN", "")


@pytest.mark.django_db
def test_a_receipt_after_the_student_marked_it_keeps_the_students_record(
    signal_on_application,
) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        Application.objects.filter(id=signal.application_id).update(
            fee_state="PAID", fee_paid_source="STUDENT"
        )

        apply_verdict(
            signal, MailVerdict(label="FEE_PAID"), link_hosts=ALLOWED, authenticated=True
        )

        application = Application.objects.get(id=signal.application_id)
    assert application.fee_paid_source == "STUDENT"
```

Append to `tests/mailbox/test_classify.py`:

```python
def test_the_prompt_tells_a_receipt_from_a_fee_due_and_a_receipt_of_the_application() -> None:
    from apps.mailbox.classify import _DEVELOPER

    assert "FEE_PAID" in _DEVELOPER
    assert MailVerdict(label="FEE_PAID").label == "FEE_PAID"
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/mailbox/test_actions.py tests/mailbox/test_classify.py`
Expected: FAIL — `FEE_PAID` is not a valid `MailVerdict.label`.

- [ ] **Step 2: Implement**

In `apps/mailbox/models.py`, add to `MailSignal.Label` after `FEE`:

```python
        FEE_PAID = "FEE_PAID", "Fee payment received"
```

Generate: `cd /home/orkhan/Desktop/lanes-plan-3 && uv run python manage.py makemigrations mailbox -n mail_signal_fee_paid`.

In `apps/mailbox/classify.py`, add `"FEE_PAID",` to the `MailVerdict.label` Literal after `"FEE",`, and append to `_DEVELOPER` (before its closing parenthesis):

```python
    " FEE_PAID only when the email confirms a payment the applicant already made, such as "
    "a receipt for the application fee. A fee still to be paid is FEE, and confirmation "
    "that the application itself arrived is RECEIVED."
```

In `apps/mailbox/actions.py`:
- add `from apps.portals.fees import mark_fee_paid`;
- add to `_ALERTS` after `"FEE"`:

```python
    "FEE_PAID": (
        RoadmapItem.Stage.FEE_EXECUTION,
        "{domain} confirms your fee payment.",
    ),
```

- in `apply_verdict`, inside `if application is not None:` after the `RECEIVED` block (this is below the `if not authenticated: … return None` gate, so untrusted mail never reaches it):

```python
        if verdict.label == "FEE_PAID":
            # A receipt marks the fee paid only behind the trust gate above, and
            # only from OPEN or UNKNOWN: a student's own record is never rewritten.
            mark_fee_paid(
                application, source=Application.FeePaidSource.MAIL, at=signal.received_at,
                actor=None,
            )
```

- [ ] **Step 3: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/mailbox tests/dashboard`, then `uv run ruff check . && uv run mypy apps config && uv run python manage.py makemigrations --check --dry-run`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-3 add apps/mailbox/models.py apps/mailbox/migrations/0011_mail_signal_fee_paid.py apps/mailbox/classify.py apps/mailbox/actions.py tests/mailbox/test_actions.py tests/mailbox/test_classify.py
git -C /home/orkhan/Desktop/lanes-plan-3 commit -m "feat(mailbox): a trusted fee receipt marks the fee paid; untrusted mail never does (lanes §7.4, §15)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: A refresh never touches a started lane (P1-11), and the spec records plan 3b

**Files:**
- Test: `tests/research/test_provenance_sweep.py`, `tests/dashboard/test_started_lane.py`
- Modify: `docs/superpowers/specs/2026-10-09-programme-lanes-and-money-design.md` (§14, §16)

Checked while writing this plan: no pack-changing path deletes or changes an `Application`. `provenance_sweep._sweep_student`, `reject_candidate`, `reject_for_student` and `replace_candidate` write `PackVersion`, `PackCandidate`, `RecommendationCandidate.state`, `StudentDecision` and `AuditEvent` only. `rebuild_pack` and `handle_research_message` write new candidates and versions. `Application.candidate` is `SET_NULL` and candidates are never deleted. So the lock is already true and this task pins it; re-grep before writing the tests (`grep -n "Application" apps/research/provenance_sweep.py apps/funding/services.py apps/research/services.py`) and fix the path there if that is no longer so.

- [ ] **Step 1: Write the tests**

In `tests/research/test_provenance_sweep.py`, add `from apps.portals.models import Application` and:

```python
@pytest.fixture
def started_on_blocked(world, agency_a, membership_a):
    """A card on the candidate the sweep is about to withdraw: started, fee paid."""
    with tenant_scope(agency_a.id):
        candidate = RecommendationCandidate.objects.get(program_name="MSc Blocked")
        card = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=candidate.program_id,
            candidate=candidate, started_at=NOW, fee_state="PAID", fee_paid_source="STUDENT",
            fee_paid_at=NOW,
        )
        return card.id, Application.objects.filter(id=card.id).values().get()


@pytest.mark.django_db(transaction=True)
def test_a_sweep_never_touches_a_started_paid_card(
    started_on_blocked, agency_a, rls_enforced_orm
) -> None:
    """P1-11, lanes spec §7.9: a started lane is locked from pack refreshes.
    The candidate leaves the pack; the student's application stays as it was."""
    card_id, before = started_on_blocked

    sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert RecommendationCandidate.objects.get(program_name="MSc Blocked").state == "REJECTED"
        assert Application.objects.filter(id=card_id).values().get() == before
```

`tests/dashboard/test_started_lane.py`:

```python
"""P1-11: replacing a pack item never changes the student's application on it."""

import pytest
from django.utils import timezone

from apps.funding.services import current_pack, replace_candidate
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate

from .conftest import add_card

pytestmark = pytest.mark.django_db
NOW = timezone.now()


def test_replacing_a_candidate_leaves_its_started_paid_card_untouched(
    agency_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(
            agency_a, membership_a, programme, started_at=NOW, fee_state="PAID",
            fee_paid_source="STUDENT", fee_paid_at=NOW,
        )
        before = Application.objects.filter(id=card.id).values().get()
        spare = make_db_candidate(agency_a, programme.run, program_name="M.Sc. Physics")

        replace_candidate(current_pack(membership_a), programme.id, spare.id, membership_a)

        assert Application.objects.filter(id=card.id).values().get() == before
```

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider tests/research/test_provenance_sweep.py tests/dashboard/test_started_lane.py`
Expected: PASS on first run — these pin behaviour that already holds. If either fails, the failing path is the bug: fix it in that function, not in the test.

- [ ] **Step 2: Record the split in the spec**

In spec §14's table:
- change the plan 3 row's "Contents" to: `the Safe and Pay-first positions (§7.1), unknown and paid fees and the fee state (§7.4), the budget line (§7.5), CBAR currency with the 3% margin (§7.6), the student-only budget and stretch with the new consultation answer (§7.7, §7.8), New for you (§7.9), a trusted receipt marking a fee paid. The rest is 3b.`;
- add a row after it: `| 3b. Money, the rest | the fee hold, "Apply now anyway" and the last safe day (§7.2, §7.3), "Wait, then pay" (§7.1), one fee per round and the fee waiver (§7.4), the lane money line (§7.5), stretch reason 3 (§7.7), fee-free items found later (§7.9) | plan 1b, plan 2b |`.

In §16, add one bullet:

```markdown
- **Deferred from plan 3 to plan 3b:** the fee hold and its last safe day, "Wait, then pay", one fee per round, the fee waiver, the lane money line, stretch reason 3, and fee-free items found later (each blocked on the data named in the table in `docs/superpowers/plans/2026-10-13-lanes-plan-3-money.md`, "Scope ruling: plan 3 now, plan 3b later").
```

- [ ] **Step 3: Run the full suite and every gate**

Run: `POSTGRES_DB=elmify_lanes3 uv run pytest -q -p no:cacheprovider`. Then all five gates from Global Constraints: `uv run ruff check .`, `uv run mypy apps config`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`, `uv run bandit -c pyproject.toml -r apps config`. All must be clean.

- [ ] **Step 4: Commit**

```bash
git -C /home/orkhan/Desktop/lanes-plan-3 add tests/research/test_provenance_sweep.py tests/dashboard/test_started_lane.py docs/superpowers/specs/2026-10-09-programme-lanes-and-money-design.md
git -C /home/orkhan/Desktop/lanes-plan-3 commit -m "test: a pack refresh never touches a started, paid lane (P1-11); spec records plan 3b

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Notes from writing

Where the code disagreed with the brief, this plan follows the code:

1. **`parse_cbar_daily` stored the rate upside down for `fx.convert`.** It kept CBAR's quote (AZN per unit); `convert` and the ECB parser use units per base. Converting 100 EUR gave 50.98 AZN instead of 196.15. Task 1 fixes the parser first. `ExchangeRate` therefore stores `rate` in `RateTable`'s convention (`Decimal(30, 20)`), not the brief's `per_unit` "base units per currency" (`Decimal(18, 8)`). Storing CBAR's quote would have meant inverting twice on every read.
2. **No list exists for "shared, web-readable, non-tenant" tables.** `_SHARED_TABLES` holds RLS shared-catalogue tables, and `test_catalog_grants.py` revokes the web role from those. `ExchangeRate` belongs in neither. Instead `funding/0060` (a RunSQL appended to the generated migration) revokes `runtime_web`'s INSERT, UPDATE and DELETE (it keeps SELECT), pinned by a `has_table_privilege` test.
3. **No egress allowlist to update.** `scripts/validate_controlled_egress.py` is a boundary probe, and `WorkerSecurityGroup` allows all egress through the NAT. Checked 2026-10-13: `https://www.cbar.az/currencies/11.10.2026.xml` (a Saturday) returns 200 with a full table, so a daily job has a file every day.
4. **The spine needs no change.** `SpineResult.programs` and `.origins` already cover every translated pool row, so over-budget items reach `_publish` without one.
5. **An unknown programme fee was copied as 0.00.** Affordability returns 0 when no `APPLICATION_FEE` component exists, and `_program_copy` wrote it, so the card would read "no fee". Task 2 adds `PackedApplication.fee_known` and copies `None`. The Task 3 backfill follows the brief (0 → NONE); existing dev rows with 0 may really be unknown. There is no production database.
6. **`BudgetLine` holds Decimals, with `text` and `stretch_text` properties,** not the brief's string fields. Task 7's floors and Task 8's offers need the numbers. A fee the table can't convert is counted separately, as "without a rate yet", so it is never folded into "not known".
7. **"Committed" leaves out decided and closed cards.** A withdrawn or refused application, or one whose intake closed, will never be paid, and §7.9 counts an unused deadline as room regained.
8. **`position()` also takes `fee_text`,** since its sentence starts with the fee.
9. **New for you:**
   - "no known passed deadline" has nothing to read, because programme candidates carry no deadline copy;
   - the pool is limited to engine-ranked rows (`rank` set), which also keeps student-named programmes out;
   - "shown once" is read as one line per item, because nothing is stored to remember a showing.
10. **The budget link arrives in Task 7, not Task 5.** Task 5's template cannot reverse a URL that doesn't exist yet.
11. **A short-form profile's budget is a bare number with no currency.** It gets no budget line, and the budget page asks the student to finish the consultation.
12. **`mark_fee_paid` lives in a new `apps/portals/fees.py`.** That way `apps/mailbox/actions.py` can import it without `apps/portals/applications.py`, which imports mailbox modules itself.
13. **The backfill lifts FORCE RLS around its UPDATE,** as `concierge/0016` does. Without that, it would match nothing for the NOBYPASSRLS migration role. It has no funding dependency (see its docstring): the existing migration tests' mixed plans refuse one.
14. **With CBAR rates, packs compare in AZN.** A new candidate's `funding_gap` and `currency` are therefore in AZN (the table's base), where tests using `EUR_RATES` saw EUR.
15. **The "I've paid this fee" button shows for `UNKNOWN` as well as `OPEN`,** because the route accepts both: an unknown fee can still have been paid.
16. **Plan 4 collision (board_for).** Plan 4's Task 4 says to replace "the three lines that read the profile" in `board_for` with `mandatory = funding_mandatory(student)` and drop the `StudentProfileVersion` import. After this plan, `snapshot` also feeds the home currency and the budget line, so plan 4 must replace only the `mandatory =` line and keep `profile`, `snapshot` and the import (Task 4 leaves a comment there saying so).

## Questions for the owner

Each has the default this plan builds meanwhile.

1. **Scholarship cards and fees.** An award copies no fee, so its card is always `UNKNOWN`. Should a scholarship card say "Fee not known yet", offer "I've paid this fee" and count as "1 fee not known" on the budget line? *Default: no to all three; programme and accepted-offer cards only (Tasks 3, 4, 5).*
2. **What "free" subtracts.** The budget line and New for you subtract only fees on cards (paid and committed), not the pack's paid suggestions the student has not added yet. So New for you can offer an item that fits only because a planned pack item is not a card yet. *Default: cards only, as spec §7.5 defines committed by fee state.*
3. **A paid fee with no rate yet.** On the first day, or for a currency CBAR does not quote, a paid foreign fee cannot be converted, so the "can't go below what is paid" floor does not count it and the budget can be lowered below it. *Default: allowed; the budget line says "1 fee without a rate yet — not counted".*
4. **An unverified receipt's alert.** Untrusted mail never changes `fee_state`, but a vouched sender's receipt still raises the usual unverified alert ("… (unverified) confirms your fee payment."), like every other label. *Default: keep it; the student marks the fee paid themselves.*
5. **A counsellor adding a programme whose fee we can't weigh.** A counsellor's add is refused only when the programme is known to exceed the free budget (OVER or STRETCH). When the fee is unknown, or its currency (or the budget's) has no rate yet, the counsellor can still add it, while the student would see the confirmation page. *Default: allowed (Task 8); refusing it would block most counsellor adds, because many programmes state no fee yet.*

## Review changes (2026-10-14)

Checked against the code on `claude/lanes-plan-3` (`da135da0`), with Tasks 1–3's code applied to a scratch copy and run on `elmify_lanes3_review`.

1. Task 1: the `runtime_web` REVOKE is appended to the generated `0060_exchangerate.py` instead of a separate `0061`, so plan 3 takes funding `0060`/`0061` and plan 4's "funding `0062` after plan 3" holds as written.
2. Task 2: the rank migration is `0061_recommendationcandidate_rank` (follows from 1).
3. Task 2: `tests/research/test_candidate_copies.py:65` asserted a fee copy for a programme that states none; it failed in the scratch run once the copy became `None`, so the plan now updates it.
4. Task 3: no "I've paid this fee" button and no "Fee not known yet" on a scholarship card (it copies no fee, so it is always `UNKNOWN`); new test (owner question 1).
5. Task 4: the at-risk line ignores linked scholarships whose result is in (won, refused or withdrawn) and decided programme cards; a stale "if X isn't won" was shown before. New parametrised test.
6. Task 4: `board_for` carries a comment for plan 4: keep `snapshot`, replace only the `mandatory` line.
7. Task 5: "fee not known" counts every undecided programme card with no fee, portal recorded or not (most cards have no portal yet), and never a scholarship card; it keyed on `has_portal` before. New test.
8. Task 4/7: `whole(..., up=True)` rounds refusal figures up, so "already paid 150 AZN" is never shown for 150.40 paid (a student typing 150 would be refused again). New test.
9. Task 7: one `_droppable` rule for both the list and the ticks; a forged tick on a withdrawn card freed money that was never committed. New test.
10. Task 7: the "below committed" test asserted the fieldset legend, which renders on every GET; it now asserts the refusal sentence.
11. Task 7: the short-form test now stores a short-form profile; before, it ran with no profile at all.
12. Task 8: New for you excludes a programme already on the board through an older run's candidate row (each run copies programmes as new rows). New test.
13. Task 8: the counsellor test now proves the counsellor page renders the budget line before asserting "New for you" is absent; the absence alone passed on any page.
14. Task 3: `portals/0038` drops its `("funding", "0057_dashboard_fields")` dependency and guards its body on the fee column existing. With the edge, 8 existing migration tests (`test_task7_migrations`, `test_audit_event_actor_kind`, the holder backfill) failed with `InvalidMigrationPlan` in the scratch run; without it all 62 pass, the new backfill test included. Step 5 now runs all of `tests/migrations`.
15. Verified, no change: the CBAR inversion (`parse_cbar_daily` stores AZN per unit; `convert(100 EUR)` gave 50.98, the fix gives 196.15 and the JPY nominal case 1.07), the 3% margin tests, the publish test, and the whole funding + research suites pass with Tasks 1–2 applied, and `tests/funding/test_rates.py` (the grant test included), `tests/migrations` and `tests/tenancy` pass with the REVOKE inside `0060` (181 passed). The `portals/0038` backfill passes its migration test; lifting FORCE is safe because the migration role owns both tables (NO FORCE exempts only the owner), it is one transaction, and its reverse is a no-op before `0037` drops the columns. No test can show the RLS half (the test role bypasses RLS), as CLAUDE.md says.
16. Owner 2026-10-14: one over-budget confirmation page for add, replace and New for you; counsellor over-budget add refused. Task 8 is rewritten around it: `over_budget`/`Overrun` in `money.py`, `overrun_for` and `Board.budget_set` in `board.py`, `own_candidate` in `applications.py`, the checks in `application_add`, `replace_candidate_view` and the counsellor `add`, and `templates/student/over_budget.html`. The `student-application-add-stretch` route and its tick box are gone, and owner question 3 is answered and removed.
