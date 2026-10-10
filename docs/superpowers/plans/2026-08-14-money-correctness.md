# Money Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every monetary and eligibility figure the platform reports correct, by storing student nationality and residence, scoping benefits by nationality, converting all money to one currency before arithmetic, and displaying figures in the student's home currency.

**Architecture:** Money gets three representations — the immutable source amount, a comparison amount normalised to the platform currency (euro) that is the *only* input to arithmetic, and a presentation amount in the student's home currency converted once at pack build. Exchange rates come from the ECB for destination currencies and from the student's national central bank for home currencies. Nationality becomes a first-class profile field because benefit eligibility depends on it.

**Tech Stack:** Python 3.12, Django 5.2, Pydantic 2.11, PostgreSQL (psycopg 3), pytest + pytest-django, Ruff, Mypy (strict).

**Spec:** `docs/superpowers/specs/2026-08-14-multi-currency-money-design.md`

Companion spec (explicitly **out of scope** for this plan): `docs/superpowers/specs/2026-08-14-llm-scored-recommendations-design.md`. The LLM scoring layer is blocked on an open `LOCATION` design question and must not be started here.

## Global Constraints

- All money arithmetic uses `Decimal`. No `float` anywhere in a money path.
- Platform comparison currency is **EUR**. Every comparison-layer figure is in EUR.
- Currency codes are validated against `ISO_4217_CODES`; country codes against `ISO_3166_ALPHA2_CODES`, both from `apps/reference_data.py`.
- Pydantic profile models use `_PROFILE_CONFIG` (`extra="forbid"`, `frozen=True`, `str_strip_whitespace=True`). Candidate fact models use `_CANDIDATE_CONFIG` (`extra="forbid"`, `frozen=True`).
- The original source amount and currency are never overwritten. Conversion produces new values alongside.
- Conversion is one-way. Never round-trip a converted value through a second conversion.
- Every conversion carries its rate, source, and retrieval date.
- Ruff line length is 100, target `py312`. Mypy runs `strict = true`.
- Tests never touch the network. Rate-source parsing is tested against recorded fixture bytes committed to the repo.
- **Black is not a dependency of this repository.** The declared dev group is `django-stubs`, `mypy`, `pytest`, `pytest-cov`, `pytest-django`, `ruff`. Use Ruff for both linting and formatting.

**Verification commands** (declared in `pyproject.toml`; run from the repository root):

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

---

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `apps/funding/fx.py` | `RateTable`, `convert`, `UnconvertibleCurrency`. Pure Decimal conversion, no I/O. |
| `apps/funding/rate_sources.py` | Per-source parsers turning fetched bytes into a `RateTable`. Parsing only, no network. |
| `tests/funding/fixtures/ecb_daily.xml` | Recorded ECB response. |
| `tests/funding/fixtures/cbar_daily.xml` | Recorded CBAR response. |
| `tests/funding/test_fx.py` | Conversion arithmetic and failure paths. |
| `tests/funding/test_rate_sources.py` | Parser tests per source. |

**Modified:**

| Path | Change |
| --- | --- |
| `apps/accounts/schemas.py:112-135` | `schema_version` 1 → 2; add `nationality`, `country_of_residence`. |
| `apps/accounts/models.py:27-29` | Check constraint accepts schema version 2. |
| `apps/accounts/profile_versions.py:43` | Persist schema version 2. |
| `apps/accounts/consultation.py:30-58` | Two new questions. |
| `apps/accounts/forms.py:25-31` | Country fields. |
| `apps/funding/evaluation.py:48-67,85-108,138-145,199-250` | `NATIONALITY` benefit scope; `benefit_applies` takes the profile; `excluded_nationalities` on `CandidateFacts`; two new hard gates. |
| `apps/funding/affordability.py` | Convert before summing; `currency` is always the platform currency. |
| `apps/funding/pack.py:44-54` | Thread the rate table; add home-currency presentation. |
| `tests/funding/conftest.py` | Fixture factories for the new fields and rate table. |

Rate *fetching* (HTTP) is deliberately excluded from this plan. Parsers take bytes; the scheduled fetcher is a separate deliverable with its own egress review, and `apps/research/` already owns controlled egress.

---

## Task 1: Student nationality and residence at schema version 2

**Files:**
- Modify: `apps/accounts/schemas.py:112-135`
- Modify: `apps/accounts/models.py:26-29`
- Modify: `apps/accounts/profile_versions.py:43`
- Modify: `apps/accounts/consultation.py:30-58`
- Modify: `apps/accounts/forms.py:25-38`
- Create: `apps/accounts/migrations/0004_profile_schema_version_2.py` (generated)
- Modify: `tests/funding/conftest.py:35-70`
- Test: `tests/accounts/test_profile_versions.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `StudentProfileSnapshot.nationality: str` and `StudentProfileSnapshot.country_of_residence: str`, both ISO 3166-1 alpha-2, both required. `StudentProfileSnapshot.schema_version: Literal[2] = 2`. Task 2 reads `profile.nationality`; Task 5 reads `profile.country_of_residence`.

- [x] **Step 1: Confirm whether stored version-1 snapshots exist**

This decides whether the migration is a pure constraint change or needs a backfill. Nationality cannot be invented for an existing row, so the answer changes the task.

```bash
uv run python manage.py shell -c "from apps.accounts.models import StudentProfileVersion; print(StudentProfileVersion.objects.filter(schema_version=1).count())"
```

Expected: `0` on a pre-launch database. **If the count is non-zero, stop and report it** — those rows need a consultant-driven re-confirmation flow, which is not in this plan.

- [x] **Step 2: Write the failing test**

Add to `tests/accounts/test_profile_versions.py`:

```python
def test_profile_snapshot_requires_nationality_and_residence() -> None:
    from pydantic import ValidationError

    from tests.funding.conftest import make_profile

    profile = make_profile(nationality="AZ", country_of_residence="AZ")

    assert profile.schema_version == 2
    assert profile.nationality == "AZ"
    assert profile.country_of_residence == "AZ"

    with pytest.raises(ValidationError):
        make_profile(nationality="ZZ")


def test_profile_nationality_and_residence_may_differ() -> None:
    from tests.funding.conftest import make_profile

    profile = make_profile(nationality="AZ", country_of_residence="TR")

    assert profile.nationality == "AZ"
    assert profile.country_of_residence == "TR"
```

- [x] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/accounts/test_profile_versions.py -k nationality -v`
Expected: FAIL — `Extra inputs are not permitted` for `nationality`, because `_PROFILE_CONFIG` sets `extra="forbid"`.

- [x] **Step 4: Add the fields to the schema**

In `apps/accounts/schemas.py`, change the `StudentProfileSnapshot` header block:

```python
class StudentProfileSnapshot(BaseModel):
    model_config = _PROFILE_CONFIG

    schema_version: Literal[2] = 2
    nationality: CountryCode
    country_of_residence: CountryCode
    academic_history: tuple[AcademicRecord, ...] = Field(min_length=1, max_length=20)
```

Extend the existing country validator so the new fields are checked against the pinned ISO set:

```python
    @field_validator("nationality", "country_of_residence")
    @classmethod
    def student_country_is_active(cls, value: str) -> str:
        if value not in ISO_3166_ALPHA2_CODES:
            raise ValueError("country must be an active ISO 3166-1 alpha-2 code")
        return value
```

- [x] **Step 5: Update the shared test factory**

In `tests/funding/conftest.py`, add two entries to the `payload` dict inside `make_profile`, immediately after `"target_field"`:

```python
        "nationality": "AZ",
        "country_of_residence": "AZ",
```

- [x] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/accounts/test_profile_versions.py -k nationality -v`
Expected: PASS

- [x] **Step 7: Allow schema version 2 in the database constraint**

In `apps/accounts/models.py`, change the check constraint:

```python
(
    models.CheckConstraint(
        condition=models.Q(schema_version__in=(0, 1, 2)),
        name="profile_schema_version_valid",
    ),
)
```

In `apps/accounts/profile_versions.py:43`, change:

```python
    schema_version = 2 if isinstance(validated, StudentProfileSnapshot) else 0
```

- [x] **Step 8: Generate and inspect the migration**

```bash
uv run python manage.py makemigrations accounts --name profile_schema_version_2
```

Open the generated file. It must contain exactly one `RemoveConstraint` and one `AddConstraint` for `profile_schema_version_valid`. If it contains anything else, stop and report.

- [x] **Step 9: Add the two consultation questions**

In `apps/accounts/consultation.py`, insert into `QUESTIONS` immediately after the `target_field` entry:

```python
(_question("nationality", lambda _draft: True),)
(_question("country_of_residence", lambda _draft: True),)
```

In `apps/accounts/forms.py`, add to `_COMMA_SEPARATED`… no — these are single values. Add a new branch to `question_field` before the `_OPTION_VALUES` check:

```python
    if key in {"nationality", "country_of_residence"}:
        return forms.CharField(required=True, min_length=2, max_length=2)
```

- [x] **Step 10: Run the full accounts and funding suites**

Run: `uv run pytest tests/accounts tests/funding -v`
Expected: PASS. Every test constructing a profile flows through `make_profile`, which now supplies both fields.

- [x] **Step 11: Run the declared gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

Expected: clean.

- [x] **Step 12: Commit**

```bash
git add apps/accounts tests/accounts tests/funding/conftest.py
git commit -m "feat: store student nationality and residence at profile schema version 2"
```

---

## Task 2: Nationality-scoped benefit eligibility

A benefit restricted to citizens of a country is currently matched against the *program's* country (`apps/funding/evaluation.py:138-145`), so it applies to every student. That overstates `covered`, understates `gap`, and can wrongly satisfy the mandatory-funding gate.

**Files:**
- Modify: `apps/funding/evaluation.py:29,48-67,138-145,199-210`
- Modify: `apps/funding/affordability.py:44-53,56-58`
- Modify: `tests/funding/conftest.py` (`make_benefit`)
- Test: `tests/funding/test_affordability.py`, `tests/funding/test_hard_gates.py`

**Interfaces:**
- Consumes: `StudentProfileSnapshot.nationality` from Task 1.
- Produces: `BenefitScope` gains `"NATIONALITY"`; `BenefitFact.nationality_code: str | None`; `benefit_applies(benefit: BenefitFact, candidate: CandidateFacts, profile: StudentProfileSnapshot) -> bool`. Task 4 calls `benefit_applies` with all three arguments.

- [x] **Step 1: Write the failing tests**

Add to `tests/funding/test_affordability.py`:

```python
def test_nationality_scope_benefit_applies_to_a_matching_student() -> None:
    profile = make_profile(nationality="AZ")
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "1000.00"),),
        benefits=(make_benefit(scope_type="NATIONALITY", nationality_code="AZ", amount="1000.00"),),
    )

    result = calculate_affordability(profile, candidate)

    assert result.gap == Decimal("0.00")


def test_nationality_scope_benefit_is_excluded_for_a_different_nationality() -> None:
    profile = make_profile(nationality="KZ")
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "1000.00"),),
        benefits=(make_benefit(scope_type="NATIONALITY", nationality_code="AZ", amount="1000.00"),),
    )

    result = calculate_affordability(profile, candidate)

    assert result.gap == Decimal("1000.00")
```

Add to `tests/funding/test_hard_gates.py`:

```python
def test_mandatory_funding_gate_rejects_a_benefit_for_another_nationality() -> None:
    profile = make_profile(nationality="KZ", funding_dependency="MANDATORY")
    candidate = make_candidate(
        benefits=(
            make_benefit(
                scope_type="NATIONALITY",
                nationality_code="AZ",
                accessibility="ORDINARY",
                eligibility_confidence="VERIFIED",
            ),
        ),
    )

    outcome = evaluate(profile, candidate)

    assert outcome.outcome == "NOT_ELIGIBLE"
    assert any("funding is mandatory" in reason for reason in outcome.reasons)
```

If `tests/funding/test_hard_gates.py` does not already import `evaluate`, `make_profile`, `make_candidate` and `make_benefit`, add them:

```python
from apps.funding.evaluation import evaluate
from tests.funding.conftest import make_benefit, make_candidate, make_profile
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/funding/test_affordability.py -k nationality tests/funding/test_hard_gates.py -k nationality -v`
Expected: FAIL — `Input should be 'GLOBAL', 'COUNTRY', 'CITY' or 'PROGRAM'`, because `NATIONALITY` is not yet a member of `BenefitScope`.

- [x] **Step 3: Add the scope and the field**

In `apps/funding/evaluation.py`, change the scope literal:

```python
BenefitScope = Literal["GLOBAL", "COUNTRY", "CITY", "PROGRAM", "NATIONALITY"]
```

Add the field to `BenefitFact`, immediately after `country_code`:

```python
    nationality_code: str | None = None
```

Add a validator to `BenefitFact` so a nationality-scoped benefit cannot be silently unscoped:

```python
    @model_validator(mode="after")
    def nationality_scope_names_a_nationality(self) -> BenefitFact:
        if self.scope_type == "NATIONALITY" and self.nationality_code is None:
            raise ValueError("a NATIONALITY-scoped benefit requires nationality_code")
        return self
```

- [x] **Step 4: Make `benefit_applies` consider the student**

Replace `apps/funding/evaluation.py:138-145` with:

```python
def benefit_applies(
    benefit: BenefitFact, candidate: CandidateFacts, profile: StudentProfileSnapshot
) -> bool:
    if benefit.scope_type == "GLOBAL":
        return True
    if benefit.scope_type == "NATIONALITY":
        return benefit.nationality_code == profile.nationality
    if benefit.scope_type == "COUNTRY":
        return benefit.country_code == candidate.program_country_code
    if benefit.scope_type == "CITY":
        return benefit.location_key == candidate.location_key
    return benefit.program_id == candidate.program_id
```

Update the caller inside `_mandatory_funding_route_gate` (`apps/funding/evaluation.py:208`):

```python
        and benefit_applies(benefit, candidate, profile)
```

- [x] **Step 5: Update the affordability caller**

In `apps/funding/affordability.py`, `_bucket_for` needs the profile:

```python
def _bucket_for(
    benefit: BenefitFact, candidate: CandidateFacts, profile: StudentProfileSnapshot
) -> str:
    if not benefit.is_current or not benefit_applies(benefit, candidate, profile):
        return "EXCLUDED"
```

and its call site inside `calculate_affordability`:

```python
        bucket = _bucket_for(benefit, candidate, profile)
```

- [x] **Step 6: Extend the benefit factory**

In `tests/funding/conftest.py`, add a `nationality_code` keyword to `make_benefit` alongside `country_code`:

```python
nationality_code: str | None = (None,)
```

and include it in the `BenefitFact` construction inside that function.

- [x] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/funding -v`
Expected: PASS, including the pre-existing scope tests, which must be unaffected.

- [x] **Step 8: Run the declared gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

- [x] **Step 9: Commit**

```bash
git add apps/funding tests/funding
git commit -m "fix: scope nationality-restricted benefits to the student's nationality"
```

---

## Task 2b: Country and nationality admission gates

`allowed_countries`, `excluded_countries` and the student's nationality are collected and validated but read by no code. `grep` across `apps/` finds no consumer outside `schemas.py`, `forms.py` and `consultation.py`. A student who excludes a country can currently be recommended a program there, and a program that does not admit a nationality is not filtered.

`HARD_GATES` has eight entries and none of them checks a country. This task adds two.

**Files:**
- Modify: `apps/funding/evaluation.py:85-108,219-250`
- Modify: `tests/funding/conftest.py` (`make_candidate`)
- Test: `tests/funding/test_hard_gates.py`

**Interfaces:**
- Consumes: `profile.nationality` (Task 1); `profile.allowed_countries`, `profile.excluded_countries` (already present).
- Produces: `CandidateFacts.excluded_nationalities: tuple[str, ...]` defaulting to `()`; two new `HardGate` entries. No later task depends on these.

- [x] **Step 1: Write the failing tests**

Add to `tests/funding/test_hard_gates.py`:

```python
def test_a_program_in_an_excluded_country_is_rejected() -> None:
    profile = make_profile(excluded_countries=("RU",))
    candidate = make_candidate(program_country_code="RU")

    outcome = evaluate(profile, candidate)

    assert outcome.outcome == "NOT_ELIGIBLE"
    assert any("excluded" in reason for reason in outcome.reasons)


def test_a_program_outside_the_allowed_countries_is_rejected() -> None:
    profile = make_profile(allowed_countries=("DE", "NL"))
    candidate = make_candidate(program_country_code="FR")

    outcome = evaluate(profile, candidate)

    assert outcome.outcome == "NOT_ELIGIBLE"


def test_an_empty_allowed_list_means_no_country_restriction() -> None:
    profile = make_profile(allowed_countries=())
    candidate = make_candidate(program_country_code="FR")

    outcome = evaluate(profile, candidate)

    assert outcome.outcome == "ELIGIBLE"


def test_a_program_that_does_not_admit_the_students_nationality_is_rejected() -> None:
    profile = make_profile(nationality="AZ")
    candidate = make_candidate(excluded_nationalities=("AZ",))

    outcome = evaluate(profile, candidate)

    assert outcome.outcome == "NOT_ELIGIBLE"
    assert any("nationality" in reason for reason in outcome.reasons)


def test_a_nationality_restriction_for_another_country_does_not_apply() -> None:
    profile = make_profile(nationality="KZ")
    candidate = make_candidate(excluded_nationalities=("AZ",))

    outcome = evaluate(profile, candidate)

    assert outcome.outcome == "ELIGIBLE"
```

An empty `allowed_countries` means "no preference", not "nothing is allowed". Getting that backwards would exclude every candidate for most students, so it has its own test.

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/funding/test_hard_gates.py -k "country or nationality" -v`
Expected: FAIL — the two country tests return `ELIGIBLE` because no gate checks the country; the nationality tests error with `Extra inputs are not permitted` for `excluded_nationalities`.

- [x] **Step 3: Add the candidate field**

In `apps/funding/evaluation.py`, add to `CandidateFacts` immediately after `program_country_code`:

```python
    excluded_nationalities: tuple[str, ...] = ()
```

This carries an institution's own admission restriction, sourced from its official page by the research pipeline. It is not a visa judgement — see Out of Scope.

- [x] **Step 4: Implement the gates**

Add to `apps/funding/evaluation.py`, next to the other gate functions:

```python
def _country_preference_gate(profile: StudentProfileSnapshot, candidate: CandidateFacts) -> bool:
    if candidate.program_country_code in profile.excluded_countries:
        return False
    if (
        profile.allowed_countries
        and candidate.program_country_code not in profile.allowed_countries
    ):
        return False
    return True


def _nationality_admission_gate(profile: StudentProfileSnapshot, candidate: CandidateFacts) -> bool:
    return profile.nationality not in candidate.excluded_nationalities
```

Add two entries to `HARD_GATES`, after the non-negotiables gate:

```python
(
    HardGate(
        "the program is in a country the student excluded, or outside the countries the "
        "student allowed",
        _country_preference_gate,
    ),
)
(
    HardGate(
        "the institution does not admit applicants of the student's nationality",
        _nationality_admission_gate,
    ),
)
```

- [x] **Step 5: Extend the candidate factory**

In `tests/funding/conftest.py`, add to the `payload` dict inside `make_candidate`:

```python
        "excluded_nationalities": (),
```

- [x] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/funding -v`
Expected: PASS. Existing tests use `allowed_countries=()` and `excluded_countries=()` from the factory, so they are unaffected.

- [x] **Step 7: Run the declared gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

- [x] **Step 8: Commit**

```bash
git add apps/funding tests/funding
git commit -m "fix: enforce student country preferences and institutional nationality restrictions"
```

---

## Task 3: The FX comparison layer

**Files:**
- Create: `apps/funding/fx.py`
- Create: `apps/funding/rate_sources.py`
- Create: `tests/funding/test_fx.py`
- Create: `tests/funding/test_rate_sources.py`
- Create: `tests/funding/fixtures/ecb_daily.xml`, `tests/funding/fixtures/cbar_daily.xml`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `RateTable(base: str, rates: Mapping[str, Decimal], source: str, retrieved_on: date)` where `rates[c]` is units of `c` per one unit of `base`.
  - `convert(amount: Decimal, source_currency: str, target_currency: str, table: RateTable) -> Decimal`
  - `UnconvertibleCurrency(Exception)`
  - `parse_ecb_daily(payload: bytes) -> RateTable`, `parse_cbar_daily(payload: bytes) -> RateTable`

Tasks 4 and 5 both consume `RateTable` and `convert`.

- [x] **Step 1: Record the fixtures**

```bash
mkdir -p tests/funding/fixtures
curl -s https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml -o tests/funding/fixtures/ecb_daily.xml
curl -s "https://www.cbar.az/currencies/$(date +%d.%m.%Y).xml" -o tests/funding/fixtures/cbar_daily.xml
wc -c tests/funding/fixtures/*.xml
```

Expected: roughly 1,500 bytes for ECB and 12,000+ for CBAR. These are committed so tests never touch the network.

- [x] **Step 2: Write the failing conversion test**

Create `tests/funding/test_fx.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from apps.funding.fx import RateTable, UnconvertibleCurrency, convert

TABLE = RateTable(
    base="EUR",
    rates={"EUR": Decimal("1"), "USD": Decimal("1.0850"), "INR": Decimal("94.5000")},
    source="ECB",
    retrieved_on=date(2026, 8, 14),
)


def test_converting_from_the_base_currency_uses_the_rate_directly() -> None:
    assert convert(Decimal("100.00"), "EUR", "USD", TABLE) == Decimal("108.50")


def test_converting_to_the_base_currency_inverts_the_rate() -> None:
    assert convert(Decimal("108.50"), "USD", "EUR", TABLE) == Decimal("100.00")


def test_cross_conversion_goes_through_the_base_currency() -> None:
    assert convert(Decimal("1085.00"), "USD", "INR", TABLE) == Decimal("94500.00")


def test_converting_a_currency_to_itself_is_the_identity() -> None:
    assert convert(Decimal("42.42"), "USD", "USD", TABLE) == Decimal("42.42")


def test_an_unknown_currency_raises_rather_than_guessing() -> None:
    with pytest.raises(UnconvertibleCurrency):
        convert(Decimal("100.00"), "AZN", "EUR", TABLE)


def test_the_result_is_quantized_to_two_places() -> None:
    result = convert(Decimal("33.33"), "EUR", "INR", TABLE)
    assert result == result.quantize(Decimal("0.01"))
```

- [x] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/funding/test_fx.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.funding.fx'`

- [x] **Step 4: Implement the conversion module**

Create `apps/funding/fx.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


class UnconvertibleCurrency(Exception):
    """Raised when a rate table cannot express a requested conversion."""


@dataclass(frozen=True)
class RateTable:
    base: str
    rates: Mapping[str, Decimal]
    source: str
    retrieved_on: date


def convert(
    amount: Decimal, source_currency: str, target_currency: str, table: RateTable
) -> Decimal:
    if source_currency == target_currency:
        return amount
    try:
        source_rate = table.rates[source_currency]
        target_rate = table.rates[target_currency]
    except KeyError as exc:
        raise UnconvertibleCurrency(f"{table.source} has no rate for {exc.args[0]}") from exc
    in_base = amount / source_rate
    return (in_base * target_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

- [x] **Step 5: Run it to verify it passes**

Run: `uv run pytest tests/funding/test_fx.py -v`
Expected: PASS

- [x] **Step 6: Write the failing parser tests**

Create `tests/funding/test_rate_sources.py`:

```python
from decimal import Decimal
from pathlib import Path

import pytest

from apps.funding.rate_sources import parse_cbar_daily, parse_ecb_daily

FIXTURES = Path(__file__).parent / "fixtures"


def test_ecb_parses_into_a_eur_based_table() -> None:
    table = parse_ecb_daily((FIXTURES / "ecb_daily.xml").read_bytes())

    assert table.base == "EUR"
    assert table.source == "ECB"
    assert table.rates["EUR"] == Decimal("1")
    assert table.rates["USD"] > Decimal("0")


def test_ecb_does_not_cover_origin_currencies() -> None:
    table = parse_ecb_daily((FIXTURES / "ecb_daily.xml").read_bytes())

    assert "AZN" not in table.rates
    assert "KZT" not in table.rates


def test_cbar_parses_into_an_azn_based_table() -> None:
    table = parse_cbar_daily((FIXTURES / "cbar_daily.xml").read_bytes())

    assert table.base == "AZN"
    assert table.source == "CBAR"
    assert table.rates["AZN"] == Decimal("1")
    assert table.rates["EUR"] > Decimal("0")


def test_an_empty_body_is_rejected_rather_than_yielding_an_empty_table() -> None:
    with pytest.raises(ValueError):
        parse_ecb_daily(b"")
```

The last test is the important one. Tajikistan's central bank returns HTTP 200 with a zero-byte body; a status-only check would call that healthy and produce a table with no rates.

- [x] **Step 7: Run it to verify it fails**

Run: `uv run pytest tests/funding/test_rate_sources.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.funding.rate_sources'`

- [x] **Step 8: Implement the parsers**

Create `apps/funding/rate_sources.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree

from apps.funding.fx import RateTable
from apps.reference_data import ISO_4217_CODES


def _require_rates(rates: dict[str, Decimal], source: str) -> None:
    if len(rates) < 2:
        raise ValueError(f"{source} returned no usable rates")


def parse_ecb_daily(payload: bytes) -> RateTable:
    if not payload.strip():
        raise ValueError("ECB returned an empty body")
    root = ElementTree.fromstring(payload)
    namespace = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
    day = root.find(".//ecb:Cube[@time]", namespace)
    if day is None:
        raise ValueError("ECB payload has no dated cube")
    rates: dict[str, Decimal] = {"EUR": Decimal("1")}
    for entry in day.findall("ecb:Cube", namespace):
        code = entry.get("currency")
        value = entry.get("rate")
        if code is None or value is None or code not in ISO_4217_CODES:
            continue
        rates[code] = Decimal(value)
    _require_rates(rates, "ECB")
    return RateTable(
        base="EUR",
        rates=rates,
        source="ECB",
        retrieved_on=date.fromisoformat(str(day.get("time"))),
    )


def parse_cbar_daily(payload: bytes) -> RateTable:
    if not payload.strip():
        raise ValueError("CBAR returned an empty body")
    root = ElementTree.fromstring(payload)
    rates: dict[str, Decimal] = {"AZN": Decimal("1")}
    for entry in root.iter("Valute"):
        code = entry.get("Code")
        nominal = entry.findtext("Nominal")
        value = entry.findtext("Value")
        if code is None or value is None or code not in ISO_4217_CODES:
            continue
        divisor = Decimal(nominal) if nominal and nominal.strip().isdigit() else Decimal("1")
        rates[code] = Decimal(value) / divisor
    _require_rates(rates, "CBAR")
    stamp = root.get("Date")
    if stamp is None:
        raise ValueError("CBAR payload has no date")
    return RateTable(
        base="AZN",
        rates=rates,
        source="CBAR",
        retrieved_on=datetime.strptime(stamp, "%d.%m.%Y").date(),
    )
```

Note the `Nominal` divisor. Several banks quote per 10 or per 100 units; ignoring it silently scales money by an order of magnitude.

- [x] **Step 9: Run it to verify it passes**

Run: `uv run pytest tests/funding/test_rate_sources.py -v`
Expected: PASS. If the CBAR element names differ from `Valute`/`Code`/`Value`, open `tests/funding/fixtures/cbar_daily.xml` and correct the parser to match the recorded fixture — the fixture is the authority, not this plan.

- [x] **Step 10: Run the declared gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

- [x] **Step 11: Commit**

```bash
git add apps/funding/fx.py apps/funding/rate_sources.py tests/funding/test_fx.py tests/funding/test_rate_sources.py tests/funding/fixtures
git commit -m "feat: add Decimal FX conversion and central-bank rate parsers"
```

---

## Task 4: Fix mixed-currency summation in affordability

`apps/funding/affordability.py:66` and `:90` take whichever line item comes first as the label for the whole result, and `:99` subtracts across currencies regardless. Tuition of ₹800,000 against a €5,000 scholarship currently reports a ₹795,000 gap; the real gap is roughly ₹350,000.

**Files:**
- Modify: `apps/funding/affordability.py` (whole module)
- Modify: `apps/funding/evaluation.py:315-317`
- Modify: `apps/funding/pack.py:44-54`
- Modify: `tests/funding/conftest.py`
- Test: `tests/funding/test_affordability.py`

**Interfaces:**
- Consumes: `RateTable`, `convert`, `UnconvertibleCurrency` from Task 3; `benefit_applies(benefit, candidate, profile)` from Task 2.
- Produces: `calculate_affordability(profile: StudentProfileSnapshot, candidate: CandidateFacts, rates: RateTable) -> AffordabilityResult` with `AffordabilityResult.currency: str` (no longer optional) always equal to `rates.base`. Task 5 consumes this result.

- [x] **Step 1: Add a rate-table fixture**

In `tests/funding/conftest.py`, add:

```python
from datetime import date as _date

from apps.funding.fx import RateTable

EUR_RATES = RateTable(
    base="EUR",
    rates={
        "EUR": Decimal("1"),
        "USD": Decimal("1.0850"),
        "INR": Decimal("94.5000"),
        "AZN": Decimal("1.8450"),
    },
    source="TEST",
    retrieved_on=_date(2026, 8, 14),
)
```

- [x] **Step 2: Write the failing test**

Add to `tests/funding/test_affordability.py`:

```python
def test_a_benefit_in_another_currency_is_converted_before_subtraction() -> None:
    profile = make_profile()
    candidate = make_candidate(
        duration_months=12,
        cost_components=(make_cost("TUITION", "800000.00", currency="INR", period="FULL_PROGRAM"),),
        benefits=(
            make_benefit(
                scope_type="GLOBAL", amount="5000.00", currency="EUR", period="FULL_PROGRAM"
            ),
        ),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.currency == "EUR"
    assert result.baseline_cost == Decimal("8465.61")
    assert result.covered == Decimal("5000.00")
    assert result.gap == Decimal("3465.61")


def test_an_unconvertible_currency_raises_instead_of_summing_across_currencies() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "1000.00", currency="KZT"),),
    )

    with pytest.raises(UnconvertibleCurrency):
        calculate_affordability(profile, candidate, EUR_RATES)
```

Add the imports at the top of the file:

```python
import pytest

from apps.funding.fx import UnconvertibleCurrency
from tests.funding.conftest import EUR_RATES
```

`800000 / 94.5 = 8465.608...`, quantized to `8465.61`. If the assertion is off by a cent, verify the arithmetic by hand before changing the expectation — a rounding mode disagreement is exactly the kind of bug this test exists to catch.

- [x] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/funding/test_affordability.py -k currency -v`
Expected: FAIL — `calculate_affordability() takes 2 positional arguments but 3 were given`

- [x] **Step 4: Convert every line item before summing**

Rewrite `calculate_affordability` in `apps/funding/affordability.py`:

```python
def calculate_affordability(
    profile: StudentProfileSnapshot, candidate: CandidateFacts, rates: RateTable
) -> AffordabilityResult:
    application_fee = Decimal("0.00")
    cost_items: list[CostItem] = []
    for component in candidate.cost_components:
        total = _normalize_to_program_total(
            component.amount, component.period, candidate.duration_months
        )
        total = convert(total, component.currency, rates.base, rates)
        cost_items.append(CostItem(kind=component.kind, program_total=total))
        if component.kind == "APPLICATION_FEE":
            application_fee += total

    baseline_cost = sum(
        (item.program_total for item in cost_items if item.kind != "APPLICATION_FEE"),
        Decimal("0.00"),
    )

    covered = Decimal("0.00")
    conditional_savings = Decimal("0.00")
    benefit_items: list[BenefitItem] = []
    for benefit in candidate.benefits:
        bucket = _bucket_for(benefit, candidate, profile)
        if benefit.amount is None or benefit.currency is None:
            total = Decimal("0.00")
        else:
            total = _normalize_to_program_total(
                benefit.amount, benefit.period, candidate.duration_months
            )
            total = convert(total, benefit.currency, rates.base, rates)
        benefit_items.append(
            BenefitItem(id=benefit.id, kind=benefit.kind, program_total=total, bucket=bucket)
        )
        if bucket == "BASELINE":
            covered += total
        elif bucket == "CONDITIONAL":
            conditional_savings += total

    gap = max(baseline_cost - covered, Decimal("0.00"))

    return AffordabilityResult(
        currency=rates.base,
        baseline_cost=baseline_cost,
        covered=covered,
        gap=gap,
        conditional_savings=conditional_savings,
        application_fee=application_fee,
        cost_items=tuple(cost_items),
        benefit_items=tuple(benefit_items),
    )
```

Change the dataclass field so the type stops admitting `None`:

```python
@dataclass(frozen=True)
class AffordabilityResult:
    currency: str
```

Add the imports:

```python
from apps.funding.fx import RateTable, convert
```

The two `currency = currency or ...` lines are deleted. That deletion is the fix; everything else is plumbing.

- [x] **Step 5: Thread the rate table through the callers**

In `apps/funding/evaluation.py:315-317`:

```python
    from apps.funding.affordability import calculate_affordability

    affordability = calculate_affordability(profile, candidate, rates)
```

`evaluate` and `score_dimensions` gain a `rates: RateTable` parameter. In `apps/funding/pack.py`, `rank_candidates(profile, candidates, rates)` passes it through to both `evaluate` and `calculate_affordability`, and `build_pack` (if it calls `rank_candidates`) does the same.

- [x] **Step 6: Run the full funding suite**

Run: `uv run pytest tests/funding -v`
Expected: PASS. Existing single-currency tests must produce identical numbers — a EUR-to-EUR conversion is the identity branch in `convert`.

- [x] **Step 7: Run the declared gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

- [x] **Step 8: Commit**

```bash
git add apps/funding tests/funding
git commit -m "fix: convert money to the platform currency before affordability arithmetic"
```

---

## Task 5: Home-currency presentation

**Files:**
- Modify: `apps/funding/fx.py`
- Modify: `apps/funding/pack.py`
- Modify: `apps/reference_data.py`
- Test: `tests/funding/test_fx.py`, `tests/funding/test_ranking.py`

**Interfaces:**
- Consumes: `RateTable`, `convert` (Task 3); `AffordabilityResult.currency` (Task 4); `profile.country_of_residence` (Task 1).
- Produces: `home_currency_for(country_code: str) -> str | None`; `PresentedMoney(amount: Decimal, currency: str, rate: Decimal, source: str, retrieved_on: date)`; `present(amount: Decimal, source_currency: str, home_currency: str, table: RateTable) -> PresentedMoney`.

- [x] **Step 1: Write the failing test**

Add to `tests/funding/test_fx.py`:

```python
def test_presented_money_carries_its_rate_and_provenance() -> None:
    from apps.funding.fx import present

    shown = present(Decimal("1000.00"), "EUR", "AZN", TABLE_WITH_AZN)

    assert shown.currency == "AZN"
    assert shown.rate == Decimal("1.8450")
    assert shown.source == "TEST"
    assert shown.retrieved_on == date(2026, 8, 14)


def test_an_unknown_home_country_has_no_currency_rather_than_a_default() -> None:
    from apps.funding.fx import home_currency_for

    assert home_currency_for("AZ") == "AZN"
    assert home_currency_for("ZZ") is None
```

Define `TABLE_WITH_AZN` at module level alongside `TABLE`, adding `"AZN": Decimal("1.8450")` to the rates.

- [x] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/funding/test_fx.py -k present -v`
Expected: FAIL with `ImportError: cannot import name 'present'`

- [x] **Step 3: Implement presentation**

Add to `apps/reference_data.py`:

```python
COUNTRY_TO_CURRENCY: dict[str, str] = {
    "AZ": "AZN",
    "KZ": "KZT",
    "UZ": "UZS",
    "KG": "KGS",
    "TJ": "TJS",
    "GE": "GEL",
    "TR": "TRY",
}
```

Launch markets only. A country absent from this map has no home currency, and the caller falls back to the platform currency rather than guessing.

Add to `apps/funding/fx.py`:

```python
from apps.reference_data import COUNTRY_TO_CURRENCY


@dataclass(frozen=True)
class PresentedMoney:
    amount: Decimal
    currency: str
    rate: Decimal
    source: str
    retrieved_on: date


def home_currency_for(country_code: str) -> str | None:
    return COUNTRY_TO_CURRENCY.get(country_code)


def present(
    amount: Decimal, source_currency: str, home_currency: str, table: RateTable
) -> PresentedMoney:
    converted = convert(amount, source_currency, home_currency, table)
    return PresentedMoney(
        amount=converted,
        currency=home_currency,
        rate=table.rates[home_currency] / table.rates[source_currency],
        source=table.source,
        retrieved_on=table.retrieved_on,
    )
```

- [x] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/funding/test_fx.py -v`
Expected: PASS

- [x] **Step 5: Write the failing obligation-currency test**

Add to `tests/funding/test_ranking.py`:

```python
def test_the_application_fee_stays_in_the_destination_currency() -> None:
    profile = make_profile(country_of_residence="AZ")
    candidate = make_candidate(
        cost_components=(
            make_cost("TUITION", "10000.00", currency="EUR"),
            make_cost("APPLICATION_FEE", "75.00", currency="EUR", period="ONE_OFF"),
        ),
    )

    ranked = rank_candidates(profile, [candidate], EUR_RATES)

    assert ranked[0].affordability.application_fee == Decimal("75.00")
    assert ranked[0].affordability.currency == "EUR"
```

An application fee is an obligation the student must actually pay in the destination currency. Converting it and presenting the converted figure as the amount due is how a student underfunds a visa financial requirement.

- [x] **Step 6: Run it, then make it pass**

Run: `uv run pytest tests/funding/test_ranking.py -k application_fee -v`

`rank_candidates` already returns `AffordabilityResult` in `rates.base`, so this should pass once the Task 4 signature change is in. If it fails, the failure is in the Task 4 plumbing, not here.

- [x] **Step 7: Run every declared gate**

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

Expected: all clean. Record the actual output; do not claim completion without it.

- [x] **Step 8: Commit**

```bash
git add apps/funding apps/reference_data.py tests/funding
git commit -m "feat: present money in the student's home currency with rate provenance"
```

---

## Out of scope, deliberately

- **Rate fetching over the network.** Parsers take bytes. The scheduled fetcher, its staleness bounds, and its stored `ExchangeRateSnapshot` rows belong with the controlled-egress work in `apps/research/` and need their own egress review.
- **Freezing rates onto `RecommendationRun`.** Required by the spec for reproducibility, but it depends on the fetcher above.
- **The remaining central banks** (NBK, CBU, NBKR, NBG). Task 3 establishes the parser pattern with two sources; the rest are mechanical repeats, each needing its own recorded fixture, and several use windows-1251 encoding with comma decimal separators.
- **The LLM scoring layer** in its entirety, per this plan's scope.
- **Visa-feasibility risk.** Approved on 2026-08-15 as a *disclosed risk*, never a silent gate. A destination that is realistically hard to reach for a given nationality (sanctions, travel bans, refusal rates) must not remove the candidate from the recommendation. Instead the candidate carries a risk flag citing the specific government policy and its date, the consultant sees it at review, and the program cannot enter the paid application pack until the student's acknowledgement is recorded with a timestamp and the exact text disclosed. This needs a sourced, dated dataset and an acknowledgement record with an audit trail, so it is its own deliverable. Rationale for keeping it out of the gates: visa outcomes are probabilistic rather than binary, sanctions change faster than the catalogue refreshes, and silently deleting options is invisible to the student — the one failure mode they can never detect or appeal.
- **Rewriting the `mobility_priorities` question.** The field is collected but unused, and its only defined examples (`"Public transport"`) come from test fixtures rather than a product decision. Deciding what to actually ask a Master's-abroad applicant — direct flights home, diaspora community, halal food, part-time work rights, whether a spouse can come — is consultation design, tracked with the elicitation work.

## Follow-up review gates

After the final task: `ponytail:ponytail-review` on the assembled diff, then `security-review` for the read-only application-code pass — this feature touches eligibility and money — then `superpowers:verification-before-completion` before any claim that it is done.

---

## Self-Review

**Spec coverage.** Three-layer money model — source preserved (Task 4 never mutates `CostLineItem`), comparison in EUR (Task 4), presentation in home currency (Task 5). Nationality as an eligibility field — Tasks 1 and 2. Rate sources with the empty-body trap — Task 3. Per-source staleness bounds and rate freezing — **not covered**, and named in Out of Scope with the reason. Display rule splitting decision from obligation numbers — partially covered by Task 5 Step 5; the full report copy is a presentation-layer concern outside this plan.

**Placeholder scan.** No TBDs. Every code step carries real code. Task 3 Step 9 tells the implementer to trust the recorded fixture over the plan if CBAR's element names differ, which is a genuine instruction rather than a deferral.

**Type consistency.** `benefit_applies` takes three arguments from Task 2 onward and Task 4 calls it that way. `calculate_affordability` takes `rates` from Task 4 onward and Task 5 relies on it. `RateTable` field names are identical in Tasks 3, 4, and 5. `AffordabilityResult.currency` narrows from `str | None` to `str` in Task 4, and no earlier task depends on the `None` case.

**Known risk.** Task 4 changes the signature of `evaluate`, which is called at `apps/funding/pack.py:50` and `:123` and at six places in `tests/funding/test_duration.py`. `rank_candidates` is called at `apps/funding/pack.py:116` and three places in `tests/funding/test_ranking.py`. `score_dimensions` does **not** need a `rates` parameter — it already receives a computed `AffordabilityResult` — so its two call sites in `tests/funding/test_duration.py:72,83` need only a rate table passed to the `calculate_affordability` call above them. Task 4 Step 6 runs the full funding suite to confirm every one of these.
