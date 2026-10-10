# Rounding-Mode Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make `ROUND_HALF_UP` the single rounding rule for the whole money pipeline by routing `convert()` and `_normalize_to_program_total`'s `ANNUAL` proration through one shared helper, instead of two call sites that quantize to 2dp independently (one implicitly `ROUND_HALF_EVEN`, one explicitly `ROUND_HALF_UP`).

**Architecture:** Add `round_money(amount: Decimal) -> Decimal` to `apps/funding/fx.py` — the module that already owns `ROUND_HALF_UP` and the 2dp quantize convention via `convert()`. Route `convert()`'s two quantize call sites and `affordability.py`'s `_normalize_to_program_total` ANNUAL branch through it. No other behavior changes.

**Tech Stack:** Python, `decimal.Decimal`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-multi-currency-money-design.md` (see `## Open` → "Rounding-mode disagreement — RESOLVED")

## Global Constraints

- `ROUND_HALF_UP` governs every money-quantization step in this pipeline — no other rounding mode may be introduced.
- Quantization is always to 2 decimal places (`Decimal("0.01")`) — this plan does not change precision, only the rounding rule and where it's stated.
- Scope is limited to this one residual item. Do not touch: multi-currency-fee test coverage, home-currency presentation wiring, or precious-metal currency codes (the other three residual items in the same spec section).

---

### Task 1: Add `round_money` helper and route `convert()` through it

**Files:**
- Modify: `apps/funding/fx.py:23-34` (the `convert` function)
- Test: `tests/funding/test_fx.py`

**Interfaces:**
- Produces: `round_money(amount: Decimal) -> Decimal` in `apps/funding/fx.py` — quantizes to 2dp with `ROUND_HALF_UP`. This is what Task 2 imports.

- [x] **Step 1: Write the failing test for `round_money`**

Add to `tests/funding/test_fx.py` (after the existing imports, which already include `from decimal import Decimal` and `date`):

```python
def test_round_money_rounds_half_up_at_the_exact_boundary() -> None:
    from apps.funding.fx import round_money

    assert round_money(Decimal("500.025")) == Decimal("500.03")
```

This value is chosen because `500.025` sits exactly on a rounding boundary where `ROUND_HALF_EVEN` (Python's default) would produce `500.02` (2 is even) but `ROUND_HALF_UP` produces `500.03` — so the test fails if the wrong mode is ever used.

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/funding/test_fx.py::test_round_money_rounds_half_up_at_the_exact_boundary -v`
Expected: FAIL with `ImportError` or `AttributeError` — `round_money` does not exist yet.

- [x] **Step 3: Add `round_money` and route `convert()` through it**

In `apps/funding/fx.py`, replace the `convert` function body:

```python
def round_money(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def convert(
    amount: Decimal, source_currency: str, target_currency: str, table: RateTable
) -> Decimal:
    if source_currency == target_currency:
        return round_money(amount)
    try:
        source_rate = table.rates[source_currency]
        target_rate = table.rates[target_currency]
    except KeyError as exc:
        raise UnconvertibleCurrency(f"{table.source} has no rate for {exc.args[0]}") from exc
    in_base = amount / source_rate
    return round_money(in_base * target_rate)
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/funding/test_fx.py -v`
Expected: All tests PASS, including the new `test_round_money_rounds_half_up_at_the_exact_boundary`. The existing `convert()` tests must still pass unchanged since `round_money` reproduces the exact same quantize call.

- [x] **Step 5: Commit**

```bash
git add apps/funding/fx.py tests/funding/test_fx.py
git commit -m "refactor: extract round_money helper for convert()'s ROUND_HALF_UP quantize"
```

---

### Task 2: Route `_normalize_to_program_total`'s ANNUAL branch through `round_money`

**Files:**
- Modify: `apps/funding/affordability.py:9,12-17`
- Test: `tests/funding/test_affordability.py`

**Interfaces:**
- Consumes: `round_money(amount: Decimal) -> Decimal` from `apps/funding/fx.py` (produced in Task 1).

- [x] **Step 1: Write the failing test for the proration boundary**

Add to `tests/funding/test_affordability.py` (new top-level test, using the private helper directly since it's the unit under test):

```python
def test_annual_proration_rounds_half_up_at_the_exact_boundary() -> None:
    from apps.funding.affordability import _normalize_to_program_total

    # 1000.05 * 6 / 12 = 500.025 exactly — ROUND_HALF_EVEN would give 500.02,
    # ROUND_HALF_UP (the pipeline-wide rule) must give 500.03.
    result = _normalize_to_program_total(Decimal("1000.05"), "ANNUAL", 6)

    assert result == Decimal("500.03")
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/funding/test_affordability.py::test_annual_proration_rounds_half_up_at_the_exact_boundary -v`
Expected: FAIL — `assert Decimal('500.02') == Decimal('500.03')`, proving the current code uses `ROUND_HALF_EVEN`.

- [x] **Step 3: Route the ANNUAL branch through `round_money`**

In `apps/funding/affordability.py`, change the import on line 9 from:

```python
from apps.funding.fx import RateTable, convert
```

to:

```python
from apps.funding.fx import RateTable, convert, round_money
```

Then change `_normalize_to_program_total` (lines 12-17):

```python
def _normalize_to_program_total(amount: Decimal, period: str, duration_months: int) -> Decimal:
    if period == "MONTHLY":
        return amount * Decimal(duration_months)
    if period == "ANNUAL":
        return round_money(amount * Decimal(duration_months) / Decimal(12))
    return amount  # ONE_OFF and FULL_PROGRAM already describe a single program-total charge
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/funding/test_affordability.py -v`
Expected: All tests PASS, including the new boundary test. Every pre-existing `calculate_affordability` test must still pass — none of the existing fixtures land on a HALF_EVEN/HALF_UP disagreement boundary, so their expected values are unaffected.

- [x] **Step 5: Commit**

```bash
git add apps/funding/affordability.py tests/funding/test_affordability.py
git commit -m "fix: prorate ANNUAL costs with ROUND_HALF_UP to match the rest of the money pipeline"
```

---

### Task 3: Run the full funding test suite

**Files:**
- None modified — verification only.

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing — this task is a checkpoint, not a deliverable.

- [x] **Step 1: Run the full funding test suite**

Run: `pytest tests/funding/ -v`
Expected: All tests PASS. This confirms no other code path (e.g. `pack.py`, `evaluation.py`) depended on the old `ROUND_HALF_EVEN` behavior of `_normalize_to_program_total`.

- [x] **Step 2: If anything fails, stop and report**

Do not silently adjust fixture expectations to match new output without checking whether the fixture's original expected value was itself computed assuming `ROUND_HALF_EVEN` — that would mean the fixture's real-world dollar amount is wrong, not just the assertion.
