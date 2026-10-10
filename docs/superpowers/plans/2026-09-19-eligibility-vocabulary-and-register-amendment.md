# Eligibility Vocabulary and Register Amendment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace four partial eligibility vocabularies with one closed list of keys that the reader emits, the catalog stores, and both the evaluator and the validity function decide against — and amend the organisation register to carry it before that register is built.

**Architecture:** One pure module `apps/funding/eligibility.py` holds the keys, the operators, the value forms and one three-valued decider per key. `BenefitRule` stores a row per condition (attached to a funding route, a programme, or both — at least one, not exactly one; see spec §2.5). The evaluator's two existing condition functions become thin filters over `decide()`, so today's behaviour and its 41 tests are preserved. `validity.py` imports the same deciders for whose-deadline-is-this. The register gains plural domains, the holder taxonomy, a real foreign key from an award, read state and cadence.

**Tech Stack:** Django 5.2, Postgres, Pydantic v2 (`extra="forbid"`), pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-19-eligibility-vocabulary-and-register-amendment-design.md`

## Global Constraints

- **Three values, never two.** Every decider returns `SATISFIED`, `FAILED` or `UNDECIDABLE`. A key with no profile source returns `UNDECIDABLE` with the reason naming the missing field — never `FAILED`.
- **Nothing is converted.** Grades decide only when the two grading scales are the same string; an hours-denominated experience bar is `UNDECIDABLE`, never divided into months (a 2,800-hour bar read as months shuts every route in the catalog).
- **`FIELD` no-match is `UNDECIDABLE`, never `FAILED`** — "engineering" does not demonstrably exclude "robotics".
- **The verbatim sentence rides on every row** (`BenefitRule.rule_text`, `ConditionTriple.quote`); quote verification in the judge already covers it.
- **Migrations:** the funding chain tip is `0037_snapshot_fetched_via`; the research chain tip is `0003_hostfetchcost`. Verify with `ls apps/funding/migrations | tail -3` before generating — another session may have added one.
- **Never run `ruff format`** in this repo (it produces invalid Python here). Run `uv run ruff check`, `uv run mypy apps`, and `POSTGRES_DB=tehsil_reader_holder uv run python manage.py makemigrations --check --dry-run` after every task.
- **Test database:** `POSTGRES_DB=tehsil_reader_holder` on every pytest invocation.
- **Commit with a pathspec**, never `git add -A` — other sessions share this repository.

## File Structure

| file | responsibility |
|---|---|
| `apps/funding/eligibility.py` (new) | the closed key list, operators, value forms, `REGIONS`, `ConditionTriple`, `Decision`, `decide()`, one decider per key. Pure: no Django import |
| `apps/funding/regions.py` (new) | `REGIONS: dict[str, Region]` — named country sets with a source URL each. Data, kept apart so a new region is a row in a file nobody else edits |
| `apps/funding/models.py` (modify) | `BenefitRule`: `key`/`operator`/`value` columns, nullable `benefit`, the at-least-one constraint (`benefit_rule_target_present`; see spec §2.5); `Organisation`, `OrganisationDomain`, `OrganisationIdentifier`; `FundingOpportunity.organisation` |
| `apps/funding/evaluation.py` (modify) | `_unmet_conditions` and `unevaluable_condition_reasons` become filters over `decide()` |
| `apps/funding/validity.py` (modify) | `_CONDITION_FIELDS` replaced by the shared deciders; the four deadline-partition keys kept, separately labelled |
| `apps/research/funding_judge.py` (modify) | `LineVerdict.conditions: tuple[ConditionTriple, ...]`; the prompt text for them; per-condition agreement |
| `apps/research/funding_reader.py` (modify) | write `BenefitRule` rows from a decision's conditions |
| `apps/research/organisations.py` (new) | `known_domains`, `record_organisation` — amended for plural domains |
| `apps/research/management/commands/funding_yield.py` (modify) | fetch through the vendor ladder |
| tests | `tests/funding/test_eligibility.py` (new), `tests/funding/test_organisation_register.py` (new), plus additions to `test_hard_gates.py`, `test_validity.py`, `tests/research/test_funding_judge.py`, `test_funding_reader.py` |

---

### Task 1: The key vocabulary and the region table

**Files:**
- Create: `apps/funding/regions.py`
- Create: `apps/funding/eligibility.py`
- Test: `tests/funding/test_eligibility.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `KEYS: tuple[str, ...]` (19 values); `OPERATORS: tuple[str, ...]`; `Key`, `Operator`, `Unit` literals; `ConditionTriple` (Pydantic, `extra="forbid"`, frozen, fields `key`, `operator`, `value`, `unit`, `quote`); `Decision` (frozen dataclass: `outcome`, `reason`); `REGIONS: dict[str, Region]` with `Region(name, countries: tuple[str, ...], source: str)`; `expand_countries(value: str) -> tuple[str, ...] | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/funding/test_eligibility.py`:

```python
"""One vocabulary: the keys, the value forms, and what a region expands to."""

import pytest
from pydantic import ValidationError

from apps.funding.eligibility import (
    KEYS,
    ConditionTriple,
    expand_countries,
)


def test_the_key_list_is_closed_and_holds_the_specs_nineteen():
    assert len(KEYS) == 19
    for key in (
        "CITIZENSHIP", "RESIDENCE", "DESCENT", "FIELD", "PRIOR_DEGREE", "PRIOR_INSTITUTION",
        "TALENT", "WORK_EXPERIENCE", "LANGUAGE", "AGE", "GENDER", "NEED",
        "REFUGEE_OR_DISPLACED", "DISABILITY", "EMPLOYMENT", "AFFINITY", "GUARANTOR",
        "OPEN", "OTHER",
    ):
        assert key in KEYS, key
    # UNSTATED is deliberately absent: a page that states nothing writes no row.
    assert "UNSTATED" not in KEYS
    assert "REGION" not in KEYS and "LEVEL" not in KEYS


def test_a_triple_is_closed_and_carries_its_sentence():
    triple = ConditionTriple(
        key="CITIZENSHIP", operator="IN", value="AZ,TR", quote="Open to citizens of Azerbaijan and Türkiye."
    )
    assert triple.key == "CITIZENSHIP" and triple.value == "AZ,TR"
    with pytest.raises(ValidationError):
        ConditionTriple(key="NATIONALITY", operator="IN", value="AZ", quote="x")
    with pytest.raises(ValidationError):
        ConditionTriple(key="CITIZENSHIP", operator="CONTAINS", value="AZ", quote="x")
    with pytest.raises(ValidationError):
        ConditionTriple(key="CITIZENSHIP", operator="IN", value="AZ", quote="x", extra="no")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("AZ,TR", ("AZ", "TR")),
        ("az, tr", ("AZ", "TR")),
        ("WESTERN_BALKANS", ("AL", "BA", "ME", "MK", "RS", "XK")),
    ],
)
def test_a_country_set_expands_from_codes_or_a_named_region(value, expected):
    assert expand_countries(value) == expected


def test_a_region_the_table_does_not_know_expands_to_nothing():
    """None, never a guess: an unknown region must become UNDECIDABLE upstream."""
    assert expand_countries("GLOBAL_NORTH_ISH") is None
    assert expand_countries("") is None


def test_every_region_carries_a_source_url():
    from apps.funding.regions import REGIONS

    assert REGIONS
    for name, region in REGIONS.items():
        assert region.countries, name
        assert region.source.startswith("https://"), name
        assert all(len(code) == 2 and code.isupper() for code in region.countries), name
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /home/orkhan/Desktop/reader-holder
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_eligibility.py -q
```

Expected: `ModuleNotFoundError: No module named 'apps.funding.eligibility'`.

- [ ] **Step 3: Write the region table**

Create `apps/funding/regions.py`:

```python
"""Named country sets, as data with a source each.

A funder writes "citizens of Western Balkan countries", not a list of six codes.
Expanding that is a lookup, never a model's guess: a region this table does not
know makes its condition UNDECIDABLE, which a human then resolves by adding a
row here with the URL that defines the membership.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    name: str
    countries: tuple[str, ...]
    #: Where the membership is defined. A region without one is a guess.
    source: str


REGIONS: dict[str, Region] = {
    "EU": Region(
        "European Union",
        (
            "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR",
            "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
        ),
        "https://european-union.europa.eu/principles-countries-history/eu-countries_en",
    ),
    "EEA": Region(
        "European Economic Area",
        (
            "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR",
            "HU", "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MT", "NL", "NO", "PL", "PT",
            "RO", "SE", "SI", "SK",
        ),
        "https://www.efta.int/eea",
    ),
    "WESTERN_BALKANS": Region(
        "Western Balkans",
        ("AL", "BA", "ME", "MK", "RS", "XK"),
        "https://neighbourhood-enlargement.ec.europa.eu/enlargement-policy/western-balkans_en",
    ),
    "EASTERN_PARTNERSHIP": Region(
        "Eastern Partnership",
        ("AM", "AZ", "GE", "MD", "UA"),
        "https://www.eeas.europa.eu/eeas/eastern-partnership_en",
    ),
    "ASEAN": Region(
        "Association of Southeast Asian Nations",
        ("BN", "ID", "KH", "LA", "MM", "MY", "PH", "SG", "TH", "VN"),
        "https://asean.org/member-states/",
    ),
    "AFRICAN_UNION": Region(
        "African Union",
        (
            "AO", "BF", "BI", "BJ", "BW", "CD", "CF", "CG", "CI", "CM", "CV", "DJ", "DZ",
            "EG", "EH", "ER", "ET", "GA", "GH", "GM", "GN", "GQ", "GW", "KE", "KM", "LR",
            "LS", "LY", "MA", "MG", "ML", "MR", "MU", "MW", "MZ", "NA", "NE", "NG", "RW",
            "SC", "SD", "SL", "SN", "SO", "SS", "ST", "SZ", "TD", "TG", "TN", "TZ", "UG",
            "ZA", "ZM", "ZW",
        ),
        "https://au.int/en/member_states/countryprofiles2",
    ),
    "COMMONWEALTH": Region(
        "Commonwealth of Nations",
        (
            "AG", "AU", "BB", "BD", "BN", "BS", "BW", "BZ", "CA", "CM", "CY", "DM", "FJ",
            "GA", "GB", "GD", "GH", "GM", "GY", "IN", "JM", "KE", "KI", "KN", "LC", "LK",
            "LS", "MT", "MU", "MV", "MW", "MY", "MZ", "NA", "NG", "NR", "NZ", "PG", "PK",
            "RW", "SB", "SC", "SG", "SL", "SS", "SZ", "TO", "TT", "TV", "TZ", "UG", "VC",
            "VU", "WS", "ZA", "ZM",
        ),
        "https://thecommonwealth.org/our-member-countries",
    ),
}
```

- [ ] **Step 4: Write the vocabulary module's first half**

Create `apps/funding/eligibility.py`:

```python
"""One eligibility vocabulary: who an award or a programme is open to.

Spec: docs/superpowers/specs/2026-09-19-eligibility-vocabulary-and-register-amendment-design.md

Four partial vocabularies existed before this module and none was the one the
specs named -- the catalog stored six condition types, the evaluator read the
same six, the validity function used seven different ones for whose-deadline,
and the engine design listed eighteen keys in prose. A writer for those would
have written in one language and been read in another.

Pure: no Django import, so the judge (research) and the evaluator (funding) can
both import it without a direction problem, and every decider is testable
against a plain profile object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from apps.funding.regions import REGIONS

Key = Literal[
    #: Who the award is for. A country set decides these three.
    "CITIZENSHIP",
    "RESIDENCE",
    "DESCENT",
    #: What the applicant has studied or achieved.
    "FIELD",
    "PRIOR_DEGREE",
    "PRIOR_INSTITUTION",
    "TALENT",
    "WORK_EXPERIENCE",
    "LANGUAGE",
    #: Who the applicant is. None of these is decidable from a profile that
    #: does not carry the field, and each says so rather than guessing.
    "AGE",
    "GENDER",
    "NEED",
    "REFUGEE_OR_DISPLACED",
    "DISABILITY",
    "EMPLOYMENT",
    "AFFINITY",
    "GUARANTOR",
    #: The page says "open to all" -- an answer, not an absence.
    "OPEN",
    #: A stated condition no key fits. Kept with its sentence, always
    #: undecidable, never dropped.
    "OTHER",
]
KEYS: tuple[str, ...] = get_args(Key)

Operator = Literal["IN", "NOT_IN", "EQ", "GTE", "LTE", "PRESENT"]
OPERATORS: tuple[str, ...] = get_args(Operator)

#: MONTHS/HOURS for WORK_EXPERIENCE, YEARS for AGE, an ISO 4217 code for NEED.
Unit = Literal["MONTHS", "HOURS", "YEARS"]

Outcome = Literal["SATISFIED", "FAILED", "UNDECIDABLE"]


class ConditionTriple(BaseModel):
    """One condition as a page states it, in the closed vocabulary.

    `value` is carried as written text rather than a parsed structure: a country
    set is "AZ,TR" or "WESTERN_BALKANS", a bar is "35", a level is "C1". Parsing
    belongs to the decider that knows the key, and keeping the raw form means a
    re-read compares like with like.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Key
    operator: Operator
    value: str = Field(default="", max_length=200)
    unit: Unit | None = None
    #: The sentence the page printed, verbatim. Quote verification covers it.
    quote: str = Field(min_length=1, max_length=4_000)


@dataclass(frozen=True)
class Decision:
    """Three values, never two.

    UNDECIDABLE is not a soft FAILED: passing a condition silently offers a
    route that may be shut, failing one silently hides a route that may be
    open, and the reason is what a consultant acts on.
    """

    outcome: Outcome
    reason: str


def expand_countries(value: str) -> tuple[str, ...] | None:
    """A country set from ISO codes or one named region, or None if unknown.

    None, never a partial answer: a region this build does not know must make
    its condition undecidable rather than silently matching nobody.
    """
    text = value.strip()
    if not text:
        return None
    region = REGIONS.get(text.upper())
    if region is not None:
        return region.countries
    codes = tuple(part.strip().upper() for part in text.split(",") if part.strip())
    if codes and all(len(code) == 2 and code.isalpha() for code in codes):
        return codes
    return None
```

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_eligibility.py -q
```

Expected: all pass.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check apps/funding/eligibility.py apps/funding/regions.py tests/funding/test_eligibility.py
uv run mypy apps/funding/eligibility.py apps/funding/regions.py
git add apps/funding/eligibility.py apps/funding/regions.py tests/funding/test_eligibility.py
git commit -m "funding: one eligibility vocabulary -- the keys, and what a region expands to

Four partial vocabularies existed and none was the one the specs named. This
is the closed list: nineteen keys, six operators, a country set that expands
from ISO codes or one named region, and a triple that carries the page's own
sentence. A region the table does not know expands to None so its condition
becomes undecidable rather than silently matching nobody.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The deciders — one per key, three-valued

**Files:**
- Modify: `apps/funding/eligibility.py`
- Test: `tests/funding/test_eligibility.py`

**Interfaces:**
- Consumes: `ConditionTriple`, `Decision`, `expand_countries` (Task 1).
- Produces: `decide(condition: ConditionTriple, profile: object) -> Decision`; `DEADLINE_PARTITION_KEYS: tuple[str, ...]` = `("APPLICANT_CLASS", "FUNDING", "ROUTE", "ROUND")`.

`profile` is typed `object` and read by `getattr` on purpose: this module must not import `apps.accounts.schemas`, which imports Django settings, or the judge could not use it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/funding/test_eligibility.py`:

```python
import datetime as dt
from dataclasses import dataclass, field as dc_field

from apps.funding.eligibility import DEADLINE_PARTITION_KEYS, decide


@dataclass
class _Experience:
    kind: str
    months: int


@dataclass
class _Academic:
    qualification: str = "Bachelor of Science"
    field: str = "robotics"
    institution: str = "Example University"
    country_code: str = "AZ"
    grade: str = "3.6"
    grading_scale: str = "GPA 4.0"


@dataclass
class _Language:
    language: str = "German"
    level: str = "C1"


@dataclass
class _Profile:
    nationality: str = "AZ"
    country_of_residence: str = "AZ"
    target_field: str = "robotics"
    academic_history: tuple = dc_field(default_factory=lambda: (_Academic(),))
    experience: tuple = dc_field(default_factory=tuple)
    language_evidence: tuple = dc_field(default_factory=tuple)
    date_of_birth: dt.date | None = None
    gender: str = ""


def _t(key, operator, value="", unit=None, quote="a published sentence"):
    return ConditionTriple(key=key, operator=operator, value=value, unit=unit, quote=quote)


def test_citizenship_in_a_country_set_is_satisfied_or_failed():
    assert decide(_t("CITIZENSHIP", "IN", "AZ,TR"), _Profile()).outcome == "SATISFIED"
    assert decide(_t("CITIZENSHIP", "IN", "DE,FR"), _Profile()).outcome == "FAILED"
    assert decide(_t("CITIZENSHIP", "NOT_IN", "DE,FR"), _Profile()).outcome == "SATISFIED"
    assert decide(_t("CITIZENSHIP", "IN", "EASTERN_PARTNERSHIP"), _Profile()).outcome == "SATISFIED"


def test_an_unknown_region_is_undecidable_and_names_itself():
    outcome = decide(_t("CITIZENSHIP", "IN", "THE_LEVANT"), _Profile())
    assert outcome.outcome == "UNDECIDABLE" and "THE_LEVANT" in outcome.reason


def test_residence_reads_its_own_field_not_nationality():
    profile = _Profile(nationality="AZ", country_of_residence="DE")
    assert decide(_t("RESIDENCE", "IN", "DE"), profile).outcome == "SATISFIED"
    assert decide(_t("CITIZENSHIP", "IN", "DE"), profile).outcome == "FAILED"


def test_descent_is_undecidable_because_the_profile_does_not_carry_it():
    outcome = decide(_t("DESCENT", "IN", "AM"), _Profile())
    assert outcome.outcome == "UNDECIDABLE" and "descent" in outcome.reason.casefold()


def test_a_field_that_does_not_match_is_undecidable_never_failed():
    """'engineering' does not demonstrably exclude 'robotics'."""
    assert decide(_t("FIELD", "IN", "robotics"), _Profile()).outcome == "SATISFIED"
    assert decide(_t("FIELD", "IN", "medicine"), _Profile()).outcome == "UNDECIDABLE"


def test_work_experience_in_months_is_decided_and_in_hours_is_not():
    profile = _Profile(experience=(_Experience("WORK", 30),))
    assert decide(_t("WORK_EXPERIENCE", "GTE", "24", "MONTHS"), profile).outcome == "SATISFIED"
    assert decide(_t("WORK_EXPERIENCE", "GTE", "36", "MONTHS"), profile).outcome == "FAILED"
    # 2,800 hours read as months would shut every route in the catalog.
    assert decide(_t("WORK_EXPERIENCE", "GTE", "2800", "HOURS"), profile).outcome == "UNDECIDABLE"


def test_only_work_counts_toward_a_professional_experience_bar():
    profile = _Profile(experience=(_Experience("INTERNSHIP", 30),))
    assert decide(_t("WORK_EXPERIENCE", "GTE", "24", "MONTHS"), profile).outcome == "FAILED"


def test_a_grade_decides_only_when_the_scales_are_the_same_string():
    profile = _Profile()  # 3.6 on "GPA 4.0"
    assert decide(_t("TALENT", "GTE", "3.0 GPA 4.0"), profile).outcome == "SATISFIED"
    assert decide(_t("TALENT", "GTE", "3.9 GPA 4.0"), profile).outcome == "FAILED"
    # Grades are never converted between systems (CLAUDE.md).
    assert decide(_t("TALENT", "GTE", "2.0 German 1-5"), profile).outcome == "UNDECIDABLE"


def test_a_language_is_present_or_compared_only_in_cefr():
    profile = _Profile(language_evidence=(_Language("German", "C1"),))
    assert decide(_t("LANGUAGE", "PRESENT", "German"), profile).outcome == "SATISFIED"
    assert decide(_t("LANGUAGE", "PRESENT", "French"), profile).outcome == "FAILED"
    assert decide(_t("LANGUAGE", "GTE", "German B2"), profile).outcome == "SATISFIED"
    assert decide(_t("LANGUAGE", "GTE", "German C2"), profile).outcome == "FAILED"
    profile_native = _Profile(language_evidence=(_Language("German", "mother tongue"),))
    assert decide(_t("LANGUAGE", "GTE", "German B2"), profile_native).outcome == "UNDECIDABLE"


def test_prior_degree_and_prior_institution():
    profile = _Profile()
    assert decide(_t("PRIOR_DEGREE", "GTE", "BACHELOR"), profile).outcome == "SATISFIED"
    assert decide(_t("PRIOR_DEGREE", "GTE", "MASTER"), profile).outcome == "FAILED"
    assert decide(_t("PRIOR_INSTITUTION", "IN", "AZ"), profile).outcome == "SATISFIED"
    assert decide(_t("PRIOR_INSTITUTION", "IN", "DE"), profile).outcome == "FAILED"


def test_age_is_decided_once_a_birth_date_exists():
    born = _Profile(date_of_birth=dt.date(1996, 5, 1))
    assert decide(_t("AGE", "LTE", "35", "YEARS"), born).outcome == "SATISFIED"
    assert decide(_t("AGE", "LTE", "20", "YEARS"), born).outcome == "FAILED"
    assert decide(_t("AGE", "LTE", "35", "YEARS"), _Profile()).outcome == "UNDECIDABLE"


def test_gender_is_decided_once_asked_and_undecidable_when_declined():
    assert decide(_t("GENDER", "EQ", "female"), _Profile(gender="female")).outcome == "SATISFIED"
    assert decide(_t("GENDER", "EQ", "female"), _Profile(gender="male")).outcome == "FAILED"
    assert decide(_t("GENDER", "EQ", "female"), _Profile(gender="")).outcome == "UNDECIDABLE"


@pytest.mark.parametrize(
    "key", ["NEED", "REFUGEE_OR_DISPLACED", "DISABILITY", "EMPLOYMENT", "AFFINITY", "GUARANTOR", "OTHER"]
)
def test_the_keys_no_profile_can_decide_say_which_field_is_missing(key):
    outcome = decide(_t(key, "PRESENT", "x"), _Profile())
    assert outcome.outcome == "UNDECIDABLE"
    assert outcome.reason


def test_open_is_an_answer_not_an_absence():
    assert decide(_t("OPEN", "PRESENT"), _Profile()).outcome == "SATISFIED"


def test_the_deadline_partition_keys_are_not_eligibility_keys():
    """They say whose deadline a date is, never who may apply."""
    assert DEADLINE_PARTITION_KEYS == ("APPLICANT_CLASS", "FUNDING", "ROUTE", "ROUND")
    for key in DEADLINE_PARTITION_KEYS:
        assert key not in KEYS
```

- [ ] **Step 2: Run to verify they fail**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_eligibility.py -q
```

Expected: `ImportError: cannot import name 'decide'`.

- [ ] **Step 3: Implement the deciders**

Append to `apps/funding/eligibility.py`:

```python
#: What a deadline row's condition partitions on. Not eligibility: these say
#: WHOSE deadline a date is, and validity.select_deadline reads them.
DEADLINE_PARTITION_KEYS: tuple[str, ...] = ("APPLICANT_CLASS", "FUNDING", "ROUTE", "ROUND")

#: CEFR is the one language scale two sides can be compared on. "mother tongue",
#: "fluent" and a test score are not points on it, so a bar stated against them
#: escalates rather than being ranked on a guess.
_CEFR = ("A1", "A2", "B1", "B2", "C1", "C2")
_DEGREE_ORDER = ("BACHELOR", "MASTER", "DOCTORATE")
#: Substrings that identify a degree level in a qualification a student typed.
_DEGREE_WORDS = {
    "BACHELOR": ("bachelor", "bsc", "ba ", "b.a", "b.s", "licence", "lisans"),
    "MASTER": ("master", "msc", "m.a", "m.s", "magister", "diplom"),
    "DOCTORATE": ("doctor", "phd", "ph.d", "doktor"),
}


def _undecidable(reason: str) -> Decision:
    return Decision("UNDECIDABLE", reason)


def _verdict(satisfied: bool, reason: str) -> Decision:
    return Decision("SATISFIED" if satisfied else "FAILED", reason)


def _country_decision(condition: ConditionTriple, held: str, field_name: str) -> Decision:
    countries = expand_countries(condition.value)
    if countries is None:
        return _undecidable(
            f"{condition.key}: '{condition.value}' is not a country list this build knows"
        )
    if not held:
        return _undecidable(f"{condition.key}: the profile does not carry {field_name}")
    inside = held.upper() in countries
    satisfied = inside if condition.operator != "NOT_IN" else not inside
    return _verdict(
        satisfied, f"{condition.key}: {field_name} {held.upper()} against {condition.value}"
    )


def _degree_level(qualification: str) -> str | None:
    text = qualification.casefold()
    for level in reversed(_DEGREE_ORDER):
        if any(word in text for word in _DEGREE_WORDS[level]):
            return level
    return None


def _split_scale(value: str) -> tuple[str, str]:
    """"3.0 GPA 4.0" -> ("3.0", "GPA 4.0"). A bar with no scale named has none."""
    head, _, tail = value.strip().partition(" ")
    return head, tail.strip()


def decide(condition: ConditionTriple, profile: object) -> Decision:  # noqa: C901
    """Whether this student satisfies one published condition.

    `profile` is read by getattr rather than typed: this module is imported by
    the judge (apps.research), and importing the Django profile schema here
    would make a pure module depend on settings.
    """
    key = condition.key
    if key == "OPEN":
        return Decision("SATISFIED", "the page states the award is open to all")
    if key == "CITIZENSHIP":
        return _country_decision(condition, str(getattr(profile, "nationality", "")), "nationality")
    if key == "RESIDENCE":
        return _country_decision(
            condition, str(getattr(profile, "country_of_residence", "")), "country of residence"
        )
    if key == "DESCENT":
        return _undecidable("DESCENT: the profile does not carry descent; a human decides it")
    if key == "FIELD":
        target = str(getattr(profile, "target_field", "")).casefold()
        wanted = [part.strip().casefold() for part in condition.value.split(",") if part.strip()]
        if target and any(part in target or target in part for part in wanted):
            return Decision("SATISFIED", f"FIELD: {target} matches {condition.value}")
        # No match is not exclusion: "engineering" does not exclude "robotics".
        return _undecidable(
            f"FIELD: {condition.value} against '{target}' -- a human decides whether they overlap"
        )
    if key == "PRIOR_DEGREE":
        levels = [
            _degree_level(str(getattr(record, "qualification", "")))
            for record in getattr(profile, "academic_history", ())
        ]
        held = [level for level in levels if level is not None]
        if not held:
            return _undecidable("PRIOR_DEGREE: no qualification in the profile names a level")
        wanted = condition.value.strip().upper()
        if wanted not in _DEGREE_ORDER:
            return _undecidable(f"PRIOR_DEGREE: '{condition.value}' is not a known level")
        best = max(_DEGREE_ORDER.index(level) for level in held)
        return _verdict(
            best >= _DEGREE_ORDER.index(wanted), f"PRIOR_DEGREE: holds {_DEGREE_ORDER[best]}"
        )
    if key == "PRIOR_INSTITUTION":
        records = tuple(getattr(profile, "academic_history", ()))
        countries = expand_countries(condition.value)
        if countries is not None:
            held = {str(getattr(record, "country_code", "")).upper() for record in records}
            return _verdict(
                bool(held & set(countries)), f"PRIOR_INSTITUTION: studied in {sorted(held)}"
            )
        names = {str(getattr(record, "institution", "")).casefold() for record in records}
        wanted = condition.value.strip().casefold()
        if wanted in names:
            return Decision("SATISFIED", f"PRIOR_INSTITUTION: studied at {condition.value}")
        return _undecidable(
            f"PRIOR_INSTITUTION: '{condition.value}' is a name, not a country list -- "
            "a human decides whether it matches"
        )
    if key == "TALENT":
        bar, scale = _split_scale(condition.value)
        for record in getattr(profile, "academic_history", ()):
            if str(getattr(record, "grading_scale", "")).casefold() != scale.casefold():
                continue
            try:
                return _verdict(
                    float(str(getattr(record, "grade", ""))) >= float(bar),
                    f"TALENT: {getattr(record, 'grade', '')} on {scale} against {bar}",
                )
            except ValueError:
                break
        # Conversion between grading systems is one-way and never done here.
        return _undecidable(
            f"TALENT: no qualification is graded on '{scale}', and grades are not converted"
        )
    if key == "WORK_EXPERIENCE":
        if condition.unit not in (None, "MONTHS"):
            return _undecidable(
                f"WORK_EXPERIENCE: a bar in {condition.unit} cannot be compared to months"
            )
        months = sum(
            int(getattr(record, "months", 0))
            for record in getattr(profile, "experience", ())
            if str(getattr(record, "kind", "")) == "WORK"
        )
        try:
            bar = float(condition.value)
        except ValueError:
            return _undecidable(f"WORK_EXPERIENCE: '{condition.value}' is not a number of months")
        return _verdict(months >= bar, f"WORK_EXPERIENCE: {months} months against {bar}")
    if key == "LANGUAGE":
        language, _, level = condition.value.strip().partition(" ")
        evidence = {
            str(getattr(item, "language", "")).casefold(): str(getattr(item, "level", ""))
            for item in getattr(profile, "language_evidence", ())
        }
        held_level = evidence.get(language.casefold())
        if held_level is None:
            return _verdict(False, f"LANGUAGE: no evidence for {language}")
        if not level:
            return Decision("SATISFIED", f"LANGUAGE: evidence for {language} is present")
        if held_level.upper() not in _CEFR or level.upper() not in _CEFR:
            return _undecidable(
                f"LANGUAGE: '{held_level}' and '{level}' are not both CEFR levels"
            )
        return _verdict(
            _CEFR.index(held_level.upper()) >= _CEFR.index(level.upper()),
            f"LANGUAGE: {language} at {held_level} against {level}",
        )
    if key == "AGE":
        born = getattr(profile, "date_of_birth", None)
        if born is None:
            return _undecidable("AGE: the profile does not carry a date of birth")
        try:
            bar = float(condition.value)
        except ValueError:
            return _undecidable(f"AGE: '{condition.value}' is not a number of years")
        today = _date.today()
        years = (
            today.year
            - born.year
            - ((today.month, today.day) < (born.month, born.day))
        )
        satisfied = years <= bar if condition.operator == "LTE" else years >= bar
        return _verdict(satisfied, f"AGE: {years} against {condition.operator} {bar}")
    if key == "GENDER":
        held = str(getattr(profile, "gender", "")).strip()
        if not held:
            return _undecidable("GENDER: the profile does not state a gender")
        return _verdict(
            held.casefold() == condition.value.strip().casefold(),
            f"GENDER: {held} against {condition.value}",
        )
    # NEED, REFUGEE_OR_DISPLACED, DISABILITY, EMPLOYMENT, AFFINITY, GUARANTOR, OTHER.
    # Special-category or unasked by decision (spec section 4); a human decides.
    return _undecidable(_UNASKED.get(key, f"{key}: no profile field decides this"))


_UNASKED: dict[str, str] = {
    "NEED": "NEED: the profile does not carry income; a human decides a means test",
    "REFUGEE_OR_DISPLACED": (
        "REFUGEE_OR_DISPLACED: not asked in the consultation; a human decides it"
    ),
    "DISABILITY": "DISABILITY: not asked in the consultation; a human decides it",
    "EMPLOYMENT": "EMPLOYMENT: the profile does not carry an employer; a human decides it",
    "AFFINITY": "AFFINITY: a membership the profile does not record; a human decides it",
    "GUARANTOR": "GUARANTOR: whether a guarantor can be produced is not in the profile",
    "OTHER": "OTHER: the page states a condition no key fits; read the sentence",
}
```

Add `from datetime import date as _date` to the module's imports.

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_eligibility.py -q
```

Expected: all pass.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check apps/funding/eligibility.py tests/funding/test_eligibility.py
uv run mypy apps/funding/eligibility.py
git add apps/funding/eligibility.py tests/funding/test_eligibility.py
git commit -m "funding: one decider per eligibility key, three-valued

Satisfied, failed, or undecidable with the reason naming the field the
profile lacks -- passing silently offers a shut route and failing silently
hides an open one. The rules that refuse to guess are the point: a field
that does not match is undecidable rather than failed, an hours bar is never
divided into months, and a grade decides only against its own scale.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The evaluator reads the shared deciders

**Files:**
- Modify: `apps/funding/evaluation.py` (`_is_decidable` ~line 243, `_unmet_conditions` ~line 256, `unevaluable_condition_reasons` ~line 510)
- Test: `tests/funding/test_hard_gates.py`

**Interfaces:**
- Consumes: `decide`, `ConditionTriple` (Task 2).
- Produces: no new public name. `ApplicantConditionFact` gains `key`, `operator` and `value` fields mirroring the triple, and `condition_type` is kept as a deprecated alias so no caller breaks in this task.

- [ ] **Step 1: Write the failing test**

Append to `tests/funding/test_hard_gates.py`:

```python
def test_the_evaluator_decides_a_citizenship_condition_through_the_shared_vocabulary() -> None:
    """Before this, only WORK_EXPERIENCE was decided and everything else escalated."""
    profile = make_profile(nationality="AZ")
    candidate = make_candidate(
        benefits=(make_benefit(id="daad"),),
        applicant_conditions=(
            make_applicant_condition(
                "CITIZENSHIP",
                benefit_id="daad",
                value="DE,FR",
                operator="IN",
                rule_text="Open to citizens of Germany and France.",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert any("daad" in reason for reason in result.reasons)


def test_an_undecidable_key_still_routes_to_review_with_its_reason() -> None:
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="kas"),),
        applicant_conditions=(
            make_applicant_condition(
                "DISABILITY",
                benefit_id="kas",
                operator="PRESENT",
                rule_text="Reserved for applicants with a recognised disability.",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("kas" in reason for reason in result.reasons)


def test_work_experience_behaviour_is_unchanged_by_the_shared_deciders() -> None:
    """The one key decided before this change must decide identically after it."""
    profile = make_profile(experience_months=12)
    candidate = make_candidate(
        benefits=(make_benefit(id="adb-jsp"),),
        applicant_conditions=(
            make_applicant_condition(
                "WORK_EXPERIENCE",
                benefit_id="adb-jsp",
                comparable_value="24",
                operator="GTE",
                value="24",
                rule_text="Two years of full-time professional experience.",
            ),
        ),
    )

    assert evaluate(profile, candidate, EUR_RATES).outcome == "NOT_ELIGIBLE"
```

Update the `make_applicant_condition` helper in that file to accept and pass through `operator` (default `"GTE"`) and `value` (default `""`), keeping every existing call working.

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_hard_gates.py -q
```

Expected: `ValidationError` for the unexpected `key`/`operator`/`value` fields, or `CITIZENSHIP` rejected by `ApplicantConditionType`.

- [ ] **Step 3: Implement**

In `apps/funding/evaluation.py`, widen the fact and route both functions through `decide`:

```python
from apps.funding.eligibility import ConditionTriple, Decision, decide

# ApplicantConditionType stays for the rows written before the vocabulary
# landed; `key` is what decides from here on.
ApplicantConditionType = Literal[
    "WORK_EXPERIENCE", "AGE_CAP", "MEANS_TEST", "AFFILIATION", "LANGUAGE", "GUARANTOR"
]
```

On `ApplicantConditionFact`, after `condition_type`:

```python
    #: The shared vocabulary (apps/funding/eligibility.py). condition_type is the
    #: pre-vocabulary name for the same thing and is mapped to a key when absent.
    key: str = ""
    operator: str = "GTE"
    value: str = ""
```

Replace `_is_decidable`, `_unmet_conditions` and `unevaluable_condition_reasons`:

```python
#: The six pre-vocabulary condition types, in the vocabulary's words.
_LEGACY_KEYS = {
    "WORK_EXPERIENCE": "WORK_EXPERIENCE",
    "AGE_CAP": "AGE",
    "MEANS_TEST": "NEED",
    "AFFILIATION": "AFFINITY",
    "LANGUAGE": "LANGUAGE",
    "GUARANTOR": "GUARANTOR",
}


def _as_triple(condition: ApplicantConditionFact) -> ConditionTriple:
    key = condition.key or _LEGACY_KEYS.get(condition.condition_type, "OTHER")
    value = condition.value or (
        str(condition.comparable_value) if condition.comparable_value is not None else ""
    )
    unit = condition.comparable_unit if key == "WORK_EXPERIENCE" else None
    return ConditionTriple(
        key=key, operator=condition.operator, value=value, unit=unit, quote=condition.rule_text
    )


def _decision_for(
    condition: ApplicantConditionFact, profile: StudentProfileSnapshot
) -> Decision:
    return decide(_as_triple(condition), profile)


def _unmet_conditions(
    benefit: BenefitFact, candidate: CandidateFacts, profile: StudentProfileSnapshot
) -> tuple[ApplicantConditionFact, ...]:
    """Conditions on this route the profile shows the student does not meet.

    FAILED only. UNDECIDABLE is not a soft fail -- evaluate() picks those up and
    routes the candidate to review rather than filtering it out silently.
    """
    return tuple(
        condition
        for condition in candidate.applicant_conditions
        if condition.benefit_id == benefit.id
        and _decision_for(condition, profile).outcome == "FAILED"
    )
```

and

```python
def unevaluable_condition_reasons(
    profile: StudentProfileSnapshot, candidate: CandidateFacts
) -> tuple[str, ...]:
    """Conditions on still-open routes that no profile field can decide.

    The reason comes from the decider, which names the field the profile lacks,
    so a consultant is told what to ask rather than that something was unclear.
    """
    routes = open_routes(profile, candidate)
    return tuple(
        f"{decision.reason} (funding route {condition.benefit_id}): {condition.rule_text}"
        for condition in candidate.applicant_conditions
        if condition.benefit_id in routes
        and (decision := _decision_for(condition, profile)).outcome == "UNDECIDABLE"
    )
```

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_hard_gates.py tests/funding -q
```

Expected: all pass, including the 41 that predate this change.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check apps/funding/evaluation.py tests/funding/test_hard_gates.py
uv run mypy apps/funding
git add apps/funding/evaluation.py tests/funding/test_hard_gates.py
git commit -m "funding: the evaluator decides through the shared vocabulary

_unmet_conditions becomes the FAILED filter over decide() and
unevaluable_condition_reasons the UNDECIDABLE filter, so a citizenship or
age bar now decides where before only work experience did, and every
escalation carries the decider's reason -- which names the field the
profile lacks. The six pre-vocabulary condition types map onto keys, so
rows written before this still read.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The validity function shares the same deciders

**Files:**
- Modify: `apps/funding/validity.py` (`_CONDITION_FIELDS` ~line 45, `_matches` ~line 199)
- Test: `tests/funding/test_validity.py`

**Interfaces:**
- Consumes: `decide`, `ConditionTriple`, `DEADLINE_PARTITION_KEYS` (Task 2).
- Produces: no new public name; `_matches` keeps its signature so `select_deadline` and `cycle_validity` are untouched.

- [ ] **Step 1: Write the failing test**

Append to `tests/funding/test_validity.py`:

```python
def test_a_deadline_condition_uses_the_same_decider_as_eligibility():
    """NATIONALITY:IN on a deadline row and CITIZENSHIP on an award row must
    agree about the same student, or the pack shows one date and gates on another."""
    evidence = Evidence(
        offered="YES",
        deadlines=(
            (dt.date(2026, 10, 15), "NATIONALITY:EASTERN_PARTNERSHIP"),
            (dt.date(2026, 12, 15), "ALL"),
        ),
    )
    chosen = select_deadline(evidence, student={"nationality": "AZ"})
    assert chosen is not None and chosen.date == dt.date(2026, 10, 15)

    other = select_deadline(evidence, student={"nationality": "BR"})
    assert other is not None and other.date == dt.date(2026, 12, 15)


def test_a_partition_condition_is_still_matched_verbatim():
    """ROUND and APPLICANT_CLASS are not eligibility keys and decide by equality."""
    evidence = Evidence(
        offered="YES",
        deadlines=((dt.date(2026, 10, 1), "ROUND:2"), (dt.date(2026, 12, 15), "ALL")),
    )
    chosen = select_deadline(evidence, student={"round": "2"})
    assert chosen is not None and chosen.date == dt.date(2026, 10, 1)
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_validity.py -q
```

Expected: the first test fails — `NATIONALITY:EASTERN_PARTNERSHIP` compares by string equality today, so the Azerbaijani student falls through to the `ALL` date.

- [ ] **Step 3: Implement**

In `apps/funding/validity.py`, replace `_CONDITION_FIELDS` and `_matches`:

```python
from apps.funding.eligibility import DEADLINE_PARTITION_KEYS, ConditionTriple, decide

#: A deadline condition names either an eligibility key (decided by the shared
#: vocabulary, so a country list or a region works exactly as it does on an
#: award) or one of the four partition keys, which are not eligibility and
#: decide by equality against the student's own answer.
_ELIGIBILITY_ALIASES = {"NATIONALITY": "CITIZENSHIP"}


def _matches(condition: str, student: dict[str, object]) -> bool:
    if condition == "ALL":
        return True
    kind, _, value = condition.partition(":")
    if kind in DEADLINE_PARTITION_KEYS:
        return str(student.get(kind.casefold(), "")).casefold() == value.casefold()
    key = _ELIGIBILITY_ALIASES.get(kind, kind)
    triple = ConditionTriple(key=key, operator="IN", value=value, quote=condition)
    return decide(triple, _StudentView(student)).outcome == "SATISFIED"


class _StudentView:
    """getattr over the student dict, so the shared deciders read it unchanged."""

    def __init__(self, student: dict[str, object]) -> None:
        self._student = student

    def __getattr__(self, name: str) -> object:
        return self._student.get(name, "")
```

`_StudentView` must be defined above `_matches`. A condition whose key is neither a partition key nor a vocabulary key raises `ValidationError` from `ConditionTriple`; catch it and return `False`, which is today's behaviour for an unknown kind:

```python
    try:
        triple = ConditionTriple(key=key, operator="IN", value=value, quote=condition)
    except ValidationError:
        return False
```

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_validity.py -q
```

Expected: all 30+ pass, including the existing table.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check apps/funding/validity.py tests/funding/test_validity.py
uv run mypy apps/funding
git add apps/funding/validity.py tests/funding/test_validity.py
git commit -m "funding: whose-deadline uses the same deciders as who-is-eligible

A deadline row saying NATIONALITY:EASTERN_PARTNERSHIP now expands the region
exactly as an award's citizenship condition does; before, it compared by
string equality and an Azerbaijani student silently fell through to the
general date. The four partition keys -- applicant class, funding, route,
round -- are not eligibility and keep deciding by equality.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `BenefitRule` stores the vocabulary, for an award or a programme

**Files:**
- Modify: `apps/funding/models.py` (`BenefitRule` and its `Meta.constraints`)
- Create: `apps/funding/migrations/0038_eligibility_vocabulary.py` (generated)
- Test: `tests/funding/test_catalog_models.py`

**Interfaces:**
- Consumes: `KEYS`, `OPERATORS` (Task 1).
- Produces: `BenefitRule.key`, `.operator`, `.value` columns; `benefit` nullable; constraints `benefit_rule_key_valid`, `benefit_rule_target_exactly_one`.

- [ ] **Step 1: Write the failing test**

Append to `tests/funding/test_catalog_models.py`:

```python
def test_a_rule_belongs_to_a_benefit_or_a_programme_never_both_nor_neither(db) -> None:
    from django.db import IntegrityError

    from apps.funding.models import BenefitRule

    with pytest.raises(IntegrityError):
        BenefitRule.objects.create(
            benefit=None, program=None, kind="APPLICANT_CONDITION",
            condition_type="WORK_EXPERIENCE", key="WORK_EXPERIENCE", operator="GTE",
            value="24", rule_text="Two years of experience.", scope_type="GLOBAL",
        )


def test_the_database_refuses_a_key_outside_the_vocabulary(db) -> None:
    from django.db import IntegrityError

    from apps.funding.models import BenefitRule

    with pytest.raises(IntegrityError):
        BenefitRule.objects.create(
            program=None, benefit=None, kind="APPLICANT_CONDITION",
            key="NATIONALITY", operator="IN", value="AZ",
            rule_text="x", scope_type="GLOBAL",
        )


def test_the_key_constant_matches_the_vocabulary() -> None:
    """A hand-kept copy, like _IDENTIFIER_SCHEMES, because a nested choices class
    is not in scope inside its own Meta."""
    from apps.funding import models
    from apps.funding.eligibility import KEYS, OPERATORS

    assert models._ELIGIBILITY_KEYS == KEYS
    assert models._ELIGIBILITY_OPERATORS == OPERATORS
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_catalog_models.py -q
```

Expected: `TypeError: BenefitRule() got unexpected keyword arguments: 'key'`.

- [ ] **Step 3: Implement the model change**

In `apps/funding/models.py`, beside `_IDENTIFIER_SCHEMES` near the top:

```python
#: Hand-kept copies of apps.funding.eligibility's tuples. A nested choices class
#: is not in scope inside its own Meta, so the CHECK constraint cannot name them;
#: tests/funding/test_catalog_models.py holds the two together.
from apps.funding.eligibility import KEYS as _ELIGIBILITY_KEYS
from apps.funding.eligibility import OPERATORS as _ELIGIBILITY_OPERATORS
```

On `BenefitRule`, make `benefit` nullable and add the three columns:

```python
    benefit = models.ForeignKey(FundingBenefit, on_delete=models.PROTECT, null=True, blank=True)
    #: The shared vocabulary. condition_type is the pre-vocabulary name and stays
    #: for rows written before it; new rows write both.
    key = models.CharField(max_length=24, blank=True, default="")
    operator = models.CharField(max_length=10, blank=True, default="")
    value = models.CharField(max_length=200, blank=True, default="")
```

In `Meta.constraints`, append:

```python
            models.CheckConstraint(
                condition=models.Q(key="") | models.Q(key__in=_ELIGIBILITY_KEYS),
                name="benefit_rule_key_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(operator="") | models.Q(operator__in=_ELIGIBILITY_OPERATORS),
                name="benefit_rule_operator_valid",
            ),
            models.CheckConstraint(
                # Exactly one target: a funding route's condition or a programme's
                # admission condition. Neither is an uninterpretable row; both would
                # make one sentence close two different things.
                condition=(
                    models.Q(benefit__isnull=False, program__isnull=True)
                    | models.Q(benefit__isnull=True, program__isnull=False)
                ),
                name="benefit_rule_target_exactly_one",
            ),
```

- [ ] **Step 4: Generate and hand-check the migration**

```bash
ls apps/funding/migrations | tail -3          # confirm 0037 is still the tip
uv run python manage.py makemigrations funding --name eligibility_vocabulary
```

It must contain: `AlterField` on `benefit` (nullable), three `AddField` (`key`, `operator`, `value`), three `AddConstraint`. Nothing else. If it also renames `condition_type` values, delete that operation — the rename lands in Task 6 with its data migration.

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding -q
uv run python manage.py makemigrations --check --dry-run
```

Expected: all pass; `No changes detected`.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check apps/funding/models.py tests/funding/test_catalog_models.py
uv run mypy apps/funding
git add apps/funding/models.py apps/funding/migrations/0038_eligibility_vocabulary.py tests/funding/test_catalog_models.py
git commit -m "catalog: a condition row carries the vocabulary, for an award or a programme

key, operator and value beside the sentence, with the database refusing a key
outside the closed list. benefit becomes nullable and exactly one of benefit
or program must be set, so a programme's admission condition is the same row
shape as a funding route's -- one gate reads both.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Rename the six stored condition types

**Files:**
- Create: `apps/funding/migrations/0039_condition_type_to_key.py` (hand-written)
- Modify: `apps/funding/models.py` (`BenefitRule.ConditionType` docstring)
- Test: `tests/funding/test_catalog_models.py`

**Interfaces:**
- Consumes: Task 5's columns.
- Produces: every `APPLICANT_CONDITION` row carries `key`; `AGE_CAP`, `MEANS_TEST` and `AFFILIATION` are gone from new writes.

This is free today and expensive the day a real row exists: `grep -rn "BenefitRule.objects.create" apps` returns nothing, so the data migration runs over an empty table. Run the grep first and **stop if it returns anything** — a writer landed while this plan was in flight and the rename needs its own review.

- [ ] **Step 1: Write the failing test**

Append to `tests/funding/test_catalog_models.py`:

```python
def test_every_stored_condition_type_has_a_vocabulary_key(db) -> None:
    """The rename is a data migration; this pins that nothing was left behind."""
    from apps.funding.models import BenefitRule

    assert not BenefitRule.objects.filter(
        kind="APPLICANT_CONDITION", key=""
    ).exists()
    assert not BenefitRule.objects.filter(
        condition_type__in=("AGE_CAP", "MEANS_TEST", "AFFILIATION")
    ).exists()
```

- [ ] **Step 2: Run it**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_catalog_models.py -q -k vocabulary_key
```

Expected: PASS on an empty table — the test is a guard for the migration, not a driver. Write the migration anyway; step 4 proves it runs.

- [ ] **Step 3: Write the data migration**

Create `apps/funding/migrations/0039_condition_type_to_key.py`:

```python
"""Fill `key` from the six pre-vocabulary condition types.

Free today: no code writes a BenefitRule row, so this runs over an empty
table. It is written as a real backfill anyway, because a fixture or a
hand-seeded row is exactly the case a no-op migration would strand.
"""

from django.db import migrations

_KEYS = {
    "WORK_EXPERIENCE": ("WORK_EXPERIENCE", "GTE"),
    "AGE_CAP": ("AGE", "LTE"),
    "MEANS_TEST": ("NEED", "LTE"),
    "AFFILIATION": ("AFFINITY", "PRESENT"),
    "LANGUAGE": ("LANGUAGE", "PRESENT"),
    "GUARANTOR": ("GUARANTOR", "PRESENT"),
}


def fill_keys(apps, schema_editor):
    BenefitRule = apps.get_model("funding", "BenefitRule")
    for condition_type, (key, operator) in _KEYS.items():
        BenefitRule.objects.filter(condition_type=condition_type, key="").update(
            key=key, operator=operator
        )


def clear_keys(apps, schema_editor):
    BenefitRule = apps.get_model("funding", "BenefitRule")
    BenefitRule.objects.update(key="", operator="", value="")


class Migration(migrations.Migration):
    dependencies = [("funding", "0038_eligibility_vocabulary")]
    operations = [migrations.RunPython(fill_keys, clear_keys)]
```

- [ ] **Step 4: Prove it runs, both ways**

```bash
POSTGRES_DB=tehsil_reader_holder uv run python manage.py migrate funding 0039
POSTGRES_DB=tehsil_reader_holder uv run python manage.py migrate funding 0038
POSTGRES_DB=tehsil_reader_holder uv run python manage.py migrate funding
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding -q
```

Expected: forward, backward and forward again all clean; tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/funding/migrations/0039_condition_type_to_key.py tests/funding/test_catalog_models.py
git commit -m "catalog: fill the vocabulary key from the six old condition types

A real backfill over what is today an empty table, reversible, because a
fixture row is exactly the case a no-op migration would strand. AGE_CAP
becomes AGE, MEANS_TEST becomes NEED, AFFILIATION becomes AFFINITY.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The reader emits conditions

**Files:**
- Modify: `apps/research/funding_judge.py` (`LineVerdict` ~line 113, `_QUESTION` ~line 141, `_decide` grouping)
- Test: `tests/research/test_funding_judge.py`

**Interfaces:**
- Consumes: `ConditionTriple` (Task 1).
- Produces: `LineVerdict.conditions: tuple[ConditionTriple, ...] = ()`; `FundingDecision.conditions: tuple[ConditionTriple, ...] = ()` (agreed conditions only); `FundingDecision.disputed_conditions: tuple[str, ...] = ()` (quotes of conditions the readings split on).

- [ ] **Step 1: Write the failing tests**

Append to `tests/research/test_funding_judge.py`:

```python
def test_a_verdict_carries_the_conditions_the_page_states():
    from apps.funding.eligibility import ConditionTriple

    v = verdict(
        1,
        conditions=(
            ConditionTriple(
                key="CITIZENSHIP", operator="IN", value="AZ,TR",
                quote="Open to citizens of Azerbaijan and Türkiye.",
            ),
        ),
    )
    assert v.conditions[0].key == "CITIZENSHIP"


def test_conditions_all_three_readings_agree_on_reach_the_award():
    from apps.funding.eligibility import ConditionTriple

    condition = ConditionTriple(
        key="AGE", operator="LTE", value="35", unit="YEARS", quote="Applicants must be under 35."
    )
    readings = [_reading(verdict(1, conditions=(condition,)))] * 3
    (decision,) = awards(line_outcomes(PAGE_CHUNK, readings)).decisions
    assert decision.conditions == (condition,)
    assert decision.disputed_conditions == ()


def test_a_condition_the_readings_split_on_is_disputed_not_dropped():
    """Tiered agreement: the award still serves; the condition is unconfirmed and
    never filtered on."""
    from apps.funding.eligibility import ConditionTriple

    quote = "Applicants must be under 35."
    strict = ConditionTriple(key="AGE", operator="LTE", value="35", unit="YEARS", quote=quote)
    loose = ConditionTriple(key="AGE", operator="LTE", value="30", unit="YEARS", quote=quote)
    readings = [
        _reading(verdict(1, conditions=(strict,))),
        _reading(verdict(1, conditions=(strict,))),
        _reading(verdict(1, conditions=(loose,))),
    ]
    (decision,) = awards(line_outcomes(PAGE_CHUNK, readings)).decisions
    assert decision.conditions == ()
    assert decision.disputed_conditions == (quote,)
    # The award itself is unaffected -- existence agreed.
    assert decision.agreement == "AGREED"


def test_the_question_names_every_eligibility_key():
    from apps.funding.eligibility import KEYS
    from apps.research.funding_judge import _QUESTION

    for key in KEYS:
        if key in ("OTHER", "OPEN"):
            continue
        assert key in _QUESTION, key
```

- [ ] **Step 2: Run to verify they fail**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/research/test_funding_judge.py -q -k "condition"
```

Expected: `ValidationError: Extra inputs are not permitted [conditions]`.

- [ ] **Step 3: Implement**

In `apps/research/funding_judge.py`:

```python
from apps.funding.eligibility import KEYS as _ELIGIBILITY_KEYS
from apps.funding.eligibility import ConditionTriple
```

On `LineVerdict`, after `deadline_for`:

```python
    #: Who the award is open to, in the shared vocabulary
    #: (apps/funding/eligibility.py). At most eight per line: a line stating
    #: more conditions than that is a checklist, and the cap stops one line
    #: consuming the whole verdict budget.
    conditions: tuple[ConditionTriple, ...] = Field(default=(), max_length=8)
```

In `_QUESTION`, after the `deadline_for` sentence:

```python
    "conditions: every condition the line states about WHO may apply, each as key, "
    "operator, value and the sentence. Keys: CITIZENSHIP (a country list or a named "
    "region), RESIDENCE, DESCENT, FIELD, PRIOR_DEGREE (BACHELOR/MASTER/DOCTORATE), "
    "PRIOR_INSTITUTION, TALENT (a grade and its scale), WORK_EXPERIENCE (with unit "
    "MONTHS or HOURS), LANGUAGE (language and CEFR level), AGE (with unit YEARS), "
    "GENDER, NEED, REFUGEE_OR_DISPLACED, DISABILITY, EMPLOYMENT, AFFINITY, GUARANTOR. "
    "Operators: IN, NOT_IN, EQ, GTE, LTE, PRESENT. Use OPEN when the line states the "
    "award is open to everyone, and OTHER when it states a condition no key fits. "
    "Copy country codes as ISO two-letter codes where the line names countries. Give "
    "no condition for a line that states none.\n"
```

In `_decide` (Task 8 of the holder-axis plan's `awards()`), after the existing field merge:

```python
    # Tiered agreement per condition (engine design section 6.2): a condition all
    # readings state identically reaches the award; one they split on is recorded
    # as disputed by its sentence and never filtered on. The award's own agreement
    # is untouched -- existence is what gates serving.
    per_reading = [
        {(c.key, c.operator, c.value, c.unit): c for c in _representative(m.verdicts).conditions}
        for m in members
    ]
    seen: dict[tuple[str, ...], list[ConditionTriple]] = {}
    for reading in per_reading:
        for signature, condition in reading.items():
            seen.setdefault(condition.quote, []).append(condition)
    agreed: list[ConditionTriple] = []
    disputed_conditions: list[str] = []
    for quote, group in seen.items():
        signatures = {(c.key, c.operator, c.value, c.unit) for c in group}
        if len(signatures) == 1 and len(group) == len(members):
            agreed.append(group[0])
        else:
            disputed_conditions.append(quote)
```

and pass `conditions=tuple(agreed)`, `disputed_conditions=tuple(sorted(disputed_conditions))` to `FundingDecision`, which gains both fields at the end of the dataclass with defaults `()`.

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/research -q
```

Expected: all pass.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check apps/research/funding_judge.py tests/research/test_funding_judge.py
uv run mypy apps
git add apps/research/funding_judge.py tests/research/test_funding_judge.py
git commit -m "reader: every verdict says who the award is open to

Conditions in the shared vocabulary, capped at eight per line, agreed per
condition rather than per award: one the readings state identically reaches
the award, one they split on is recorded by its sentence and never filtered
on. The award's own agreement is untouched, because existence is what gates
serving -- ten awards decided and none shown was the failure this closes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The writer stores them — `BenefitRule` gets its first writer

**Files:**
- Modify: `apps/research/funding_reader.py` (`_write_rows`)
- Test: `tests/research/test_funding_reader.py`

**Interfaces:**
- Consumes: `FundingDecision.conditions` (Task 7); `BenefitRule` columns (Task 5).
- Produces: `_write_conditions(opportunity, decision, *, benefit, source, snapshot, checked_at) -> int`.

- [ ] **Step 1: Write the failing test**

Append to `tests/research/test_funding_reader.py`:

```python
def test_an_awards_conditions_become_benefit_rules_with_their_sentences(program, snapshot):
    from apps.funding.eligibility import ConditionTriple
    from apps.funding.models import BenefitRule

    quote = "Open to citizens of Azerbaijan and Türkiye."
    row = write_funding_decision(
        _decision(
            conditions=(
                ConditionTriple(key="CITIZENSHIP", operator="IN", value="AZ,TR", quote=quote),
            )
        ),
        program=program, lead=LEAD, source=snapshot.source, snapshot=snapshot,
    )
    assert row is not None
    rule = BenefitRule.objects.get(key="CITIZENSHIP")
    assert rule.operator == "IN" and rule.value == "AZ,TR" and rule.rule_text == quote
    assert rule.benefit is not None and rule.program_id is None
    assert rule.kind == "APPLICANT_CONDITION"
    assert rule.evidence_claims.count() == 1


def test_a_disputed_condition_is_not_written_as_a_rule(program, snapshot):
    """Unconfirmed must not become a filter."""
    from apps.funding.models import BenefitRule

    write_funding_decision(
        _decision(disputed_conditions=("Applicants must be under 35.",)),
        program=program, lead=LEAD, source=snapshot.source, snapshot=snapshot,
    )
    assert not BenefitRule.objects.filter(kind="APPLICANT_CONDITION").exists()


def test_a_reread_replaces_the_conditions_it_previously_wrote(program, snapshot):
    from apps.funding.eligibility import ConditionTriple
    from apps.funding.models import BenefitRule

    first = ConditionTriple(key="AGE", operator="LTE", value="35", unit="YEARS", quote="Under 35.")
    second = ConditionTriple(key="AGE", operator="LTE", value="30", unit="YEARS", quote="Under 30.")
    write_funding_decision(
        _decision(conditions=(first,)), program=program, lead=LEAD,
        source=snapshot.source, snapshot=snapshot,
    )
    write_funding_decision(
        _decision(conditions=(second,)), program=program, lead=LEAD,
        source=snapshot.source, snapshot=snapshot,
    )
    rules = BenefitRule.objects.filter(key="AGE")
    assert rules.count() == 1 and rules.get().value == "30"
```

- [ ] **Step 2: Run to verify they fail**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/research/test_funding_reader.py -q -k condition
```

Expected: `BenefitRule.DoesNotExist`.

- [ ] **Step 3: Implement**

In `apps/research/funding_reader.py`, inside `_write_rows` after the benefits loop:

```python
    _write_conditions(
        opportunity, decision, source=source, snapshot=snapshot, checked_at=checked_at,
        visibility=visibility, strength=strength,
    )
```

and:

```python
def _write_conditions(
    opportunity: FundingOpportunity,
    decision: FundingDecision,
    *,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    checked_at: datetime,
    visibility: str,
    strength: str,
) -> int:
    """The award's agreed conditions as BenefitRule rows, one per condition.

    Only agreed ones: a condition the readings split on is unconfirmed, and an
    unconfirmed condition that became a rule would filter a student out of an
    award on a bar no two readings could agree the page stated.

    Attached to the award's first benefit, because a condition closes the route
    it is published on. An award with no benefit at all writes no conditions --
    there is no route for them to close.
    """
    benefit = FundingBenefit.objects.filter(opportunity=opportunity).order_by("id").first()
    if benefit is None or not decision.conditions:
        return 0
    written = 0
    for condition in decision.conditions:
        claim = OfficialEvidenceClaim.objects.create(
            source=source,
            snapshot=snapshot,
            claim=condition.quote,
            evidence_strength=strength,
            visibility=visibility,
            claim_class=OfficialEvidenceClaim.ClaimClass.FUNDING,
            last_checked_at=checked_at,
        )
        rule = BenefitRule.objects.create(
            benefit=benefit,
            program=None,
            kind=BenefitRule.Kind.APPLICANT_CONDITION,
            key=condition.key,
            operator=condition.operator,
            value=condition.value,
            comparable_unit=condition.unit if condition.unit in ("MONTHS", "HOURS") else None,
            condition_type=_LEGACY_CONDITION_TYPE.get(condition.key),
            rule_text=condition.quote[:4_000],
            scope_type=BenefitRule.Scope.GLOBAL,
        )
        BenefitRuleEvidenceClaim.objects.create(benefit_rule=rule, evidence_claim=claim)
        written += 1
    return written


#: The pre-vocabulary column is NOT NULL-checked by an existing constraint for
#: APPLICANT_CONDITION rows, so a key that had an old name still fills it.
_LEGACY_CONDITION_TYPE = {
    "WORK_EXPERIENCE": "WORK_EXPERIENCE",
    "AGE": "AGE_CAP",
    "NEED": "MEANS_TEST",
    "AFFINITY": "AFFILIATION",
    "LANGUAGE": "LANGUAGE",
    "GUARANTOR": "GUARANTOR",
}
```

In `_write_rows`'s delete block (the "a re-read replaces the quotes" section), delete this award's condition rows before rewriting, in PROTECT-safe order:

```python
    BenefitRuleEvidenceClaim.objects.filter(benefit_rule__benefit__opportunity=opportunity).delete()
    BenefitRule.objects.filter(benefit__opportunity=opportunity).delete()
```

placed **before** the `FundingBenefit` delete, since rules point at benefits.

If the existing `benefit_rule_condition_type_shape_valid` constraint rejects a key with no legacy name (`CITIZENSHIP` and the rest map to `None`), relax it in the same migration as Task 5's — change it to require `condition_type` **or** `key` for an `APPLICANT_CONDITION` row. Verify with the `test_a_rule_belongs_to_a_benefit_or_a_programme` test from Task 5.

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/research tests/funding -q
```

Expected: all pass.

- [ ] **Step 5: Lint, type-check, migration check, commit**

```bash
uv run ruff check apps/research/funding_reader.py tests/research/test_funding_reader.py
uv run mypy apps
uv run python manage.py makemigrations --check --dry-run
git add apps/research/funding_reader.py tests/research/test_funding_reader.py
git commit -m "reader: an award's agreed conditions become catalog rows

BenefitRule gets its first writer, two months after the table was designed.
Only agreed conditions are written: an unconfirmed one that became a rule
would filter a student out of an award on a bar no two readings could agree
the page stated. A re-read replaces them, as it already does the quotes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The organisation register, with plural domains

**Files:**
- Modify: `apps/funding/models.py` (append after `InstitutionIdentifier`)
- Create: `apps/funding/migrations/0040_organisation_register.py` (generated)
- Create: `apps/research/organisations.py`
- Test: `tests/funding/test_organisation_register.py`

**Interfaces:**
- Consumes: `registrable_domain` (`apps/research/hosts.py`, already built); `_HOLDER_VALUES` (`apps/funding/models.py`).
- Produces: `Organisation` (fields below), `OrganisationDomain`, `OrganisationIdentifier`; `known_domains(domains: Iterable[str]) -> frozenset[str]`; `record_organisation(*, domain: str, name: str, kind: str, country_code: str, official_website: str, status: str, found_via: str, identifiers: Mapping[str, str] | None = None) -> tuple[Organisation, bool]`.

- [ ] **Step 1: Write the failing test**

Create `tests/funding/test_organisation_register.py`:

```python
"""The register's key is a domain, and one organisation may hold several."""

import pytest

from apps.funding.models import Organisation, OrganisationDomain
from apps.research.organisations import known_domains, record_organisation

pytestmark = pytest.mark.django_db


def _record(**overrides):
    fields = dict(
        domain="cusanuswerk.de", name="Cusanuswerk", kind="RELIGIOUS", country_code="DE",
        official_website="https://www.cusanuswerk.de", status="REGISTERED", found_via="ROR",
    )
    fields.update(overrides)
    return record_organisation(**fields)


def test_a_new_domain_creates_one_organisation():
    org, created = _record()
    assert created is True and org.primary_domain == "cusanuswerk.de"
    assert OrganisationDomain.objects.filter(organisation=org).count() == 1


def test_the_same_domain_twice_adds_its_route_and_does_not_duplicate():
    _record()
    org, created = _record(found_via="POINTER:daad.de")
    assert created is False
    assert Organisation.objects.count() == 1
    assert set(org.found_via) == {"ROR", "POINTER:daad.de"}


def test_a_second_domain_joins_an_existing_organisation_through_a_shared_identifier():
    """The measured case: ROR gives bwstiftung.de, our award rows key on
    bw-stipendium.de, and they are one foundation."""
    first, _ = _record(
        domain="bwstiftung.de", name="Baden-Wuerttemberg Stiftung", kind="PRIVATE_FOUNDATION",
        identifiers={"ROR": "https://ror.org/05kjnjg67"},
    )
    second, created = _record(
        domain="bw-stipendium.de", name="Baden-Wuerttemberg-STIPENDIUM",
        kind="PRIVATE_FOUNDATION", identifiers={"ROR": "https://ror.org/05kjnjg67"},
    )
    assert created is False and second.id == first.id
    assert Organisation.objects.count() == 1
    assert set(
        OrganisationDomain.objects.filter(organisation=first).values_list(
            "registrable_domain", flat=True
        )
    ) == {"bwstiftung.de", "bw-stipendium.de"}


def test_a_name_match_alone_never_merges_two_organisations():
    """Two foundations may share a name; only an identifier is evidence."""
    _record(domain="stiftung-a.de", name="Deutsche Stiftung", kind="PRIVATE_FOUNDATION")
    _, created = _record(domain="stiftung-b.de", name="Deutsche Stiftung", kind="PRIVATE_FOUNDATION")
    assert created is True and Organisation.objects.count() == 2


def test_known_domains_answers_for_every_domain_an_organisation_holds():
    _record(domain="bwstiftung.de", identifiers={"ROR": "https://ror.org/05kjnjg67"})
    _record(domain="bw-stipendium.de", identifiers={"ROR": "https://ror.org/05kjnjg67"})
    assert known_domains(["bw-stipendium.de", "unseen.example.de"]) == frozenset(
        {"bw-stipendium.de"}
    )


def test_the_kind_is_the_holder_vocabulary_and_the_database_refuses_another():
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        Organisation.objects.create(
            primary_domain="x.example.de", name="X", kind="FUNDER_FOUNDATION",
            country_code="DE", official_website="https://x.example.de", status="REGISTERED",
        )


def test_research_institute_is_a_holder_value():
    from apps.funding.models import _HOLDER_VALUES
    from apps.research.funding_judge import _HOLDERS

    assert "RESEARCH_INSTITUTE" in _HOLDER_VALUES
    assert _HOLDER_VALUES == _HOLDERS
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_organisation_register.py -q
```

Expected: `ImportError: cannot import name 'Organisation'`.

- [ ] **Step 3: Add `RESEARCH_INSTITUTE` to the holder vocabulary**

In `apps/research/funding_judge.py`, add `"RESEARCH_INSTITUTE",` to `_Holder` after `"PROFESSIONAL_BODY"`; in the `holder:` prompt sentence add `RESEARCH_INSTITUTE (a research institute or national laboratory that funds theses)`. In `apps/funding/models.py` add the same value to `_HOLDER_VALUES` in the same position. In `apps/research/funding_reader.py` add `"RESEARCH_INSTITUTE": "RESEARCH_ECOSYSTEM_PATHWAY",` to `_FAMILY_BY_HOLDER`.

- [ ] **Step 4: Write the models**

In `apps/funding/models.py`, after `InstitutionIdentifier`:

```python
class Organisation(models.Model):
    """A body that holds money or grants degrees. One row, several domains.

    Keyed on registrable domains rather than a name because a name is not an
    identity: two foundations share one, and one foundation writes its own
    three ways. `primary_domain` is what a card shows; every domain the body
    answers on is an OrganisationDomain row, because ROR returns the
    organisation's site (bwstiftung.de) where an award's page may live on
    another (bw-stipendium.de), and an award keyed on one must still find the
    body registered under the other.
    """

    class Status(models.TextChoices):
        #: A register or the body's own site vouched for this domain.
        REGISTERED = "REGISTERED"
        #: Found by search or a pointer; not yet verified.
        CANDIDATE = "CANDIDATE"
        REJECTED = "REJECTED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    primary_domain = models.CharField(max_length=253, unique=True)
    name = models.CharField(max_length=300)
    #: The holder vocabulary (funding_judge._HOLDERS): a funder's kind IS its
    #: holder type, so an award and its holder can never disagree about what
    #: the body is. A university is INSTITUTION; a faculty is INSTITUTION with
    #: a parent.
    kind = models.CharField(max_length=24)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="units"
    )
    country_code = models.CharField(max_length=2)
    official_website = models.URLField(max_length=2048)
    status = models.CharField(max_length=12, choices=Status.choices)
    found_via = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    names = ArrayField(models.CharField(max_length=300), default=list, blank=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_verified = models.DateTimeField(null=True, blank=True)
    #: Read state (engine design Layer 2). Latest only: a history table is what
    #: someone needs to ask "what did we read last month", and nobody has.
    last_read_at = models.DateTimeField(null=True, blank=True)
    pages_read = models.PositiveIntegerField(default=0)
    pages_unreadable = models.PositiveIntegerField(default=0)
    #: Cadence, curated and expiring (funder spec 3.5.1); validity.RegisterCadence
    #: reads these four and the year they were verified for.
    cadence = models.CharField(max_length=16, blank=True, default="")
    cadence_open_month = models.PositiveSmallIntegerField(null=True, blank=True)
    cadence_deadline_month = models.PositiveSmallIntegerField(null=True, blank=True)
    cadence_source = models.URLField(max_length=2048, blank=True, default="")
    cadence_verified_for_cycle = models.PositiveSmallIntegerField(null=True, blank=True)
    institution = models.ForeignKey(
        Institution, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=_HOLDER_VALUES), name="organisation_kind_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("REGISTERED", "CANDIDATE", "REJECTED")),
                name="organisation_status_valid",
            ),
        ]


class OrganisationDomain(models.Model):
    """One registrable domain, one organisation. The lookup key."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, related_name="domains"
    )
    registrable_domain = models.CharField(max_length=253, unique=True)
    found_via = models.CharField(max_length=40, blank=True, default="")
    first_seen = models.DateTimeField(auto_now_add=True)


class OrganisationIdentifier(models.Model):
    """A register's id for this organisation. The only evidence that merges two."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, related_name="identifiers"
    )
    scheme = models.CharField(max_length=16)
    value = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("scheme", "value"), name="organisation_identifier_scheme_value_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    scheme__in=(*_IDENTIFIER_SCHEMES, "WIKIDATA", "EACEA_PIC")
                ),
                name="organisation_identifier_scheme_valid",
            ),
        ]
```

- [ ] **Step 5: Write the recorder**

Create `apps/research/organisations.py`:

```python
"""Recording an organisation: the dedupe seam.

Two domains are one organisation only when a register says so -- a shared ROR,
Wikidata or EACEA id. Never on a name match: two foundations share a name, and
merging them loses one. Measured 2026-09-19 (dual-seed review): ROR returned
bwstiftung.de for the foundation whose scholarship page is bw-stipendium.de.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from django.db import transaction

from apps.funding.models import Organisation, OrganisationDomain, OrganisationIdentifier

from .hosts import registrable_domain


def known_domains(domains: Iterable[str]) -> frozenset[str]:
    """Which of these registrable domains the register already holds."""
    wanted = {registrable_domain(domain) for domain in domains} - {""}
    return frozenset(
        OrganisationDomain.objects.filter(registrable_domain__in=wanted).values_list(
            "registrable_domain", flat=True
        )
    )


@transaction.atomic
def record_organisation(
    *,
    domain: str,
    name: str,
    kind: str,
    country_code: str,
    official_website: str,
    status: str,
    found_via: str,
    identifiers: Mapping[str, str] | None = None,
) -> tuple[Organisation, bool]:
    """Upsert by domain, merging onto an existing organisation by identifier.

    Returns (organisation, created). On an existing row it adds the route tag
    and never downgrades status.
    """
    key = registrable_domain(domain)
    if not key:
        raise ValueError(f"no registrable domain in {domain!r}")
    existing = OrganisationDomain.objects.filter(registrable_domain=key).first()
    if existing is not None:
        organisation = existing.organisation
        if found_via and found_via not in organisation.found_via:
            organisation.found_via = [*organisation.found_via, found_via]
            organisation.save(update_fields=["found_via"])
        return organisation, False
    for scheme, value in (identifiers or {}).items():
        match = OrganisationIdentifier.objects.filter(scheme=scheme, value=value).first()
        if match is not None:
            OrganisationDomain.objects.create(
                organisation=match.organisation, registrable_domain=key, found_via=found_via
            )
            return match.organisation, False
    organisation = Organisation.objects.create(
        primary_domain=key,
        name=name,
        kind=kind,
        country_code=country_code,
        official_website=official_website,
        status=status,
        found_via=[found_via] if found_via else [],
        names=[name],
    )
    OrganisationDomain.objects.create(
        organisation=organisation, registrable_domain=key, found_via=found_via
    )
    for scheme, value in (identifiers or {}).items():
        OrganisationIdentifier.objects.get_or_create(
            scheme=scheme, value=value, defaults={"organisation": organisation}
        )
    return organisation, True
```

- [ ] **Step 6: Generate the migration, run, lint, commit**

```bash
ls apps/funding/migrations | tail -3
uv run python manage.py makemigrations funding --name organisation_register
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding/test_organisation_register.py tests/research -q
uv run ruff check apps/funding/models.py apps/research/organisations.py apps/research/funding_judge.py apps/research/funding_reader.py tests/funding/test_organisation_register.py
uv run mypy apps
uv run python manage.py makemigrations --check --dry-run
git add apps/funding/models.py apps/funding/migrations/0040_organisation_register.py apps/research/organisations.py apps/research/funding_judge.py apps/research/funding_reader.py tests/funding/test_organisation_register.py
git commit -m "register: one organisation, several domains, merged only by identifier

The register's key is a registrable domain and a body may answer on more
than one: ROR returns bwstiftung.de for the foundation whose scholarship
page is bw-stipendium.de, and an award keyed on one must find the body
registered under the other. Two domains merge only on a shared ROR,
Wikidata or EACEA id -- never on a name, because two foundations share one.

kind is the holder vocabulary, so an award and its holder cannot disagree
about what the body is, and RESEARCH_INSTITUTE joins it: Max Planck, CNRS
and EMBL fund theses and fitted none of the fifteen. Read state and cadence
land with the model that needs them.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: The award points at its organisation

**Files:**
- Modify: `apps/funding/models.py` (`FundingOpportunity`)
- Create: `apps/funding/migrations/0041_opportunity_organisation.py` (generated + hand-written backfill)
- Modify: `apps/research/funding_reader.py` (`write_holder_decision`)
- Test: `tests/research/test_funding_reader.py`

**Interfaces:**
- Consumes: `Organisation`, `record_organisation` (Task 9).
- Produces: `FundingOpportunity.organisation` FK; `write_holder_decision` sets it.

- [ ] **Step 1: Write the failing test**

Append to `tests/research/test_funding_reader.py`:

```python
def test_a_holder_award_points_at_its_organisation(snapshot, funder_lead):
    from apps.funding.models import Organisation
    from apps.research.funding_reader import write_holder_decision

    row = write_holder_decision(
        _holder_decision(), holder_domain="foundation-example.de",
        holder_name="Example Foundation", lead=funder_lead, source=snapshot.source,
        snapshot=snapshot,
    )
    assert row is not None and row.organisation_id is not None
    organisation = Organisation.objects.get(id=row.organisation_id)
    assert organisation.primary_domain == "foundation-example.de"
    assert organisation.kind == "PRIVATE_FOUNDATION"


def test_two_awards_on_one_holders_domains_share_one_organisation(snapshot, funder_lead):
    from apps.funding.models import Organisation
    from apps.research.funding_reader import write_holder_decision

    write_holder_decision(
        _holder_decision(kind="I0_HOLDER_AWARD"), holder_domain="foundation-example.de",
        holder_name="Example Foundation", lead=funder_lead, source=snapshot.source,
        snapshot=snapshot,
    )
    write_holder_decision(
        _holder_decision(name="Second award"), holder_domain="foundation-example.de",
        holder_name="Example Foundation", lead=funder_lead, source=snapshot.source,
        snapshot=snapshot,
    )
    assert Organisation.objects.count() == 1
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/research/test_funding_reader.py -q -k organisation
```

Expected: `AttributeError: 'FundingOpportunity' object has no attribute 'organisation_id'`.

- [ ] **Step 3: Implement**

On `FundingOpportunity`, after `holder_name`:

```python
    #: The body that holds the money. Replaces holder_domain as the anchor; the
    #: string column stays until a test asserts every HOLDER row has this FK.
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, null=True, blank=True, related_name="awards"
    )
```

In `write_holder_decision`, before `update_or_create`:

```python
    organisation, _created = record_organisation(
        domain=holder_domain,
        name=holder_name,
        kind=decision.holder if decision.holder != "UNSTATED" else "PRIVATE_FOUNDATION",
        country_code="",
        official_website=f"https://{holder_domain}",
        status="CANDIDATE",
        found_via=lead.discovered_by[:40],
    )
```

and add `"organisation": organisation,` to the `defaults` dict.

`country_code=""` is deliberate: the reader does not know the body's country, and the register plan's Task 3 sweep is what fills it. The model allows a blank country; a later task tightens it when the sweep exists.

- [ ] **Step 4: Generate the migration with its backfill**

```bash
uv run python manage.py makemigrations funding --name opportunity_organisation
```

Then append a `RunPython` to the generated file that creates an `Organisation` and `OrganisationDomain` for every distinct `holder_domain` on a `HOLDER` row and points the award at it, reversing by nulling the FK:

```python
def backfill(apps, schema_editor):
    FundingOpportunity = apps.get_model("funding", "FundingOpportunity")
    Organisation = apps.get_model("funding", "Organisation")
    OrganisationDomain = apps.get_model("funding", "OrganisationDomain")
    rows = FundingOpportunity.objects.filter(scope_type="HOLDER").exclude(holder_domain="")
    for domain in sorted({row.holder_domain for row in rows}):
        existing = OrganisationDomain.objects.filter(registrable_domain=domain).first()
        if existing is not None:
            organisation = existing.organisation
        else:
            sample = rows.filter(holder_domain=domain).first()
            organisation = Organisation.objects.create(
                primary_domain=domain,
                name=sample.holder_name or domain,
                kind=sample.holder or "PRIVATE_FOUNDATION",
                country_code="",
                official_website=f"https://{domain}",
                status="CANDIDATE",
                found_via=["BACKFILL"],
                names=[sample.holder_name or domain],
            )
            OrganisationDomain.objects.create(
                organisation=organisation, registrable_domain=domain, found_via="BACKFILL"
            )
        rows.filter(holder_domain=domain).update(organisation=organisation)


def unbackfill(apps, schema_editor):
    apps.get_model("funding", "FundingOpportunity").objects.update(organisation=None)
```

- [ ] **Step 5: Run everything**

```bash
POSTGRES_DB=tehsil_reader_holder uv run python manage.py migrate funding
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/funding tests/research -q
uv run ruff check apps/funding/models.py apps/research/funding_reader.py tests/research/test_funding_reader.py
uv run mypy apps
uv run python manage.py makemigrations --check --dry-run
```

- [ ] **Step 6: Commit**

```bash
git add apps/funding/models.py apps/funding/migrations/0041_opportunity_organisation.py apps/research/funding_reader.py tests/research/test_funding_reader.py
git commit -m "catalog: an award points at the organisation that holds it

A real foreign key where holder_domain was a string 'because the register
lives on another branch' -- since the consolidation it does not. Every
holder award registers its body as it is written, so two awards on one
foundation's pages reach one organisation, and the backfill does the same
for rows written before this.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: The gate harness reads through the vendor ladder

**Files:**
- Modify: `apps/research/management/commands/funding_yield.py`
- Test: `tests/research/test_funding_yield.py`

**Interfaces:**
- Consumes: `retrieve_official_source` (`apps/research/discovery.py`, which routes to `fetch_via_vendors`).
- Produces: no new name; `--fetch egress|vendor` with `vendor` the default.

- [ ] **Step 1: Write the failing test**

Append to `tests/research/test_funding_yield.py`:

```python
def test_the_harness_fetches_through_the_vendor_ladder_by_default(monkeypatch):
    """Gate 3.4 must measure the path the product uses; our own client alone
    re-measures the JavaScript shells the vendor tier was bought to close."""
    from apps.research.management.commands import funding_yield as module

    seen: list[str] = []

    def fake_retrieve(url, **kwargs):
        seen.append(url)
        return FetchResult(url, (), "text/html", b"<html><body><p>Stipendium.</p></body></html>")

    monkeypatch.setattr(module, "retrieve_official_source", fake_retrieve)
    monkeypatch.setattr(
        module, "read_funding", lambda *a, **k: FundingReadResult((), 0, 0, 0, ())
    )
    command = module.Command()
    command.stdout, command.stderr = StringIO(), StringIO()
    command._read_host(
        "foundation-example.de", pages=1, parser=object(), claude=object(),
        fetch=module.default_fetch(),
    )
    assert seen and seen[0].startswith("https://foundation-example.de")
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/research/test_funding_yield.py -q -k vendor
```

Expected: `AttributeError: module has no attribute 'retrieve_official_source'`.

- [ ] **Step 3: Implement**

In `funding_yield.py`, replace the `fetch_official_source` import with:

```python
from apps.research.discovery import retrieve_official_source


def default_fetch() -> Callable[..., FetchResult]:
    """The product's path: our own client, then the vendor ladder on a refusal
    or a JavaScript shell. Gate 3.4 measures what ships, not what shipped."""
    return retrieve_official_source
```

and add the argument:

```python
        parser.add_argument("--fetch", choices=("vendor", "egress"), default="vendor")
```

with `handle` choosing `default_fetch()` or `fetch_official_source` accordingly. Keep `fetch_official_source` imported for `--fetch egress`, which is how the before/after comparison stays runnable.

- [ ] **Step 4: Run, lint, commit**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/research/test_funding_yield.py -q
uv run ruff check apps/research/management/commands/funding_yield.py tests/research/test_funding_yield.py
uv run mypy apps
git add apps/research/management/commands/funding_yield.py tests/research/test_funding_yield.py
git commit -m "research: the yield harness reads through the vendor ladder

Gate 3.4 measured our own client while the product had moved to the vendor
path, so it re-measured the JavaScript shells the vendor tier closed -- five
of fifteen pages on 2026-09-19. --fetch egress keeps the old path runnable
so the before and after stay comparable.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: The consultation asks for date of birth and gender

**Files:**
- Modify: `apps/accounts/schemas.py` (`StudentProfileSnapshot`)
- Modify: `apps/accounts/consultation.py` (`QUESTIONS`)
- Test: `tests/accounts/test_consultation_progress.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `StudentProfileSnapshot.date_of_birth: date | None`, `.gender: str` — both optional, so `AGE` and `GENDER` become decidable for a student who answers.

- [ ] **Step 1: Write the failing test**

Append to `tests/accounts/test_consultation_progress.py`:

```python
def test_the_profile_carries_an_optional_birth_date_and_gender() -> None:
    from apps.accounts.schemas import StudentProfileSnapshot

    fields = StudentProfileSnapshot.model_fields
    assert "date_of_birth" in fields and "gender" in fields
    assert fields["date_of_birth"].default is None
    assert fields["gender"].default == ""


def test_a_blank_answer_leaves_the_condition_undecidable_not_failed() -> None:
    """Optional on purpose: a student who declines must not be filtered out."""
    import datetime as dt

    from apps.funding.eligibility import ConditionTriple, decide

    class _P:
        date_of_birth = None
        gender = ""

    assert decide(
        ConditionTriple(key="AGE", operator="LTE", value="35", unit="YEARS", quote="Under 35."),
        _P(),
    ).outcome == "UNDECIDABLE"
    assert decide(
        ConditionTriple(key="GENDER", operator="EQ", value="female", quote="Women only."), _P()
    ).outcome == "UNDECIDABLE"
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/accounts/test_consultation_progress.py -q
```

Expected: `assert 'date_of_birth' in fields` fails.

- [ ] **Step 3: Implement**

On `StudentProfileSnapshot`, after `country_of_residence`:

```python
    #: Optional, and optional is load-bearing: a national scheme capping at 35 is
    #: one of the commonest conditions there is, and a student who declines must
    #: be UNDECIDABLE on it rather than filtered out (eligibility.decide).
    date_of_birth: date | None = None
    #: Free text over an enum so a student is never forced into a box; "" is
    #: "prefer not to say" and decides nothing.
    gender: str = Field(default="", max_length=40)
```

In `consultation.py`, add two optional questions to `QUESTIONS` following the file's existing question shape, both with an `asked_when` that is always true and neither required for `validate_draft` to pass.

- [ ] **Step 4: Run, lint, commit**

```bash
POSTGRES_DB=tehsil_reader_holder uv run pytest tests/accounts tests/funding -q
uv run ruff check apps/accounts/schemas.py apps/accounts/consultation.py tests/accounts/test_consultation_progress.py
uv run mypy apps
git add apps/accounts/schemas.py apps/accounts/consultation.py tests/accounts/test_consultation_progress.py
git commit -m "accounts: the consultation asks for a birth date and gender, optionally

Two fields unlock the two conditions funders use most -- a national scheme's
age cap and a women-in-STEM award. Both optional, and that is the
load-bearing part: a student who declines is UNDECIDABLE on the condition, a
human decides it, and nobody is filtered out by a blank. Disability, refugee
status and income stay unasked by decision.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**

| spec section | task |
|---|---|
| §2.1 keys, §2.2 value forms | 1 |
| §2.3 the triple the reader emits | 1 (schema), 7 (emission) |
| §2.4 the `BenefitRule` row | 5, 6 |
| §2.5 one decision function, evaluator and validity sharing it | 2, 3, 4 |
| §2.5 programmes use the same rows | 5 (the exactly-one constraint) |
| §3.1 domains plural | 9 |
| §3.2 one taxonomy, `RESEARCH_INSTITUTE` | 9 |
| §3.3 the award's foreign key | 10 |
| §3.4 read state, §3.5 cadence | 9 (fields land with the model) |
| §4 the profile's two new fields | 12 |
| §5 the gate harness | 11 |
| §6 testing | every task's test step |

**Known gap, deliberate:** §3.3's "the string column is dropped once the backfill is verified" is not a task here. Dropping `holder_domain` needs a migration after a release where both exist, which is a separate, later change; Task 10 leaves the column in place and populated.

**Type consistency:** `decide(condition, profile) -> Decision` is used with that signature in Tasks 2, 3, 4 and 12. `ConditionTriple(key, operator, value, unit, quote)` is constructed identically in Tasks 1, 2, 4, 7, 8 and 12. `record_organisation(**kwargs) -> tuple[Organisation, bool]` is defined in Task 9 and called with the same keywords in Task 10. `KEYS`/`OPERATORS` are produced in Task 1 and imported in Tasks 5, 7 and 9.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-19-eligibility-vocabulary-and-register-amendment.md`. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks.

**2. Inline Execution** — tasks executed in this session with checkpoints.

Which approach?
