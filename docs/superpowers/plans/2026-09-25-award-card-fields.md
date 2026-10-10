# The Card the Reader Owes — Implementation Plan (build item 13)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every award the reader serves the facts its card owes (master spec §8.3, §10.4): **amount, currency, period, duration, `timing`, `cycle`, `required_documents`, and `contact`** — each one a value the page printed, tied to the sentence that printed it, marked *unconfirmed* where the readings split, and never a number the page did not state.

**Architecture:** Three parts, landing at three different times, because they depend on three different things.

- **Part A (Tasks 1–7) lands now, on master.** Amount, currency, period, duration, `timing` and `cycle` are printed on the *money lines* the funding judge (`apps/research/funding_judge.py`) already reads three times. They become fields of `LineVerdict`, agreed per line and per award by the tiered rule (a split is `UNCONFIRMED`, never a hidden award), and every copied value is checked by code against its line. Figures, currencies and months are computed by code in `apps/research/card_fields.py`; the readings only copy text and pick labels from closed lists. The writer stores them on `FundingOpportunity` and `FundingBenefit`, `apps/funding/card.py` reads them back as an `AwardCard`, and the facts translator stops counting a figure the page did not state as a total.
- **Part B (Tasks 8–10) waits for the typed-decision layer and the reader plan.** `required_documents` and `contact` are not on money lines, so the funding judge never sees them; they are *classification* over a page's sentences, which is exactly what `docs/superpowers/plans/2026-09-23-reader-and-multilingual-layer.md` (D4 + D5) and `2026-09-23-decision-layer-and-rule-grammar.md` (`decisions.ask`) build. Part B writes those two fields *through* that machinery instead of building a second one.
- **Part C (Task 11) waits for build item 11.** The pack's refusal of an incomplete card needs a deadline state, and deadline evidence is item 11's to store.
- **Task 12 is the gate:** cards filled on the 58-host re-run, and the 30-card hand check.

**Tech Stack:** Django 5.2, PostgreSQL row-level security, pydantic 2 (the verdict schema), the two model clients already used by the funding judge (`OPENAI_EXTRACTION_MODEL`, `ANTHROPIC_JUDGE_MODEL`), and — Part B only — `apps.research.decisions` (Jev through `typesafe-sdk`, or its adapter), pytest with the repo's test database.

**Spec:** `docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md` — read §3 (principles), §8.1–§8.7 (the reader), §9.2 "Whose deadline?" and the nomination paragraph (the contact), §10.2–§10.4 (facts, gates, the card), §15 (measurement) and decision-log row 39. Then `docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md` §2 (what it leaves out), §3.1a (how questions are written), §4 (D4, D5), §9 (security), §13 ("Jev for deadlines, amounts, dates") — and the two 2026-09-23 plans named above, whose interfaces Part B consumes unchanged.

**Base branch:** `master` at `115c752` (2026-09-25). Work on `claude/award-card`: `git fetch origin master && git switch -c claude/award-card origin/master`. Test database: `POSTGRES_DB=tehsil_card` — never share a test database between sessions (CLAUDE.md).

---

## What the code says item 13 is — read before Task 1

Measured against `master` at `115c752`, not taken from the spec:

1. **`LineVerdict` carries none of the card's fields.** It has `applies_to`, `stated_on`, `deadline`, `deadline_for` and `conditions`, and nothing for amount, currency, period, duration, `timing`, `cycle`, documents or contact (`funding_judge.py:149`).
2. **The spec's "columns exist" (§8.3) is true of three fields only.** `FundingBenefit` has `amount`, `currency` and `period` (`apps/funding/models.py:913`). Nothing holds duration, `timing`, `cycle`, documents or contact, and nothing holds the coverage *level* either: `_benefit_kinds` turns `tuition=FULL` and `tuition=PARTIAL` into the same `TUITION` benefit row, so "a full waiver" and "a 10% discount" are the same row today.
3. **The writer never sets an amount.** `funding_reader._write_rows` creates every benefit with `amount=None` and `period="FULL_PROGRAM"` hard-coded. So `affordability.calculate_affordability` counts every read benefit as zero — which is also why nothing is overstated *yet*. The moment Task 5 writes a monthly figure, `affordability._normalize_to_program_total` multiplies it by the **programme's** length, so a one-year stipend on a two-year degree would count twice. Task 6 closes that in the same part, before any row carries a figure a pack could read.
4. **There is no card object.** "The card" in code is `AwardCandidateFacts` (`apps/funding/evaluation.py:522`) carried into `PackedAward` (`apps/funding/pack.py:58`); no view or template renders one. This plan gives both a typed `AwardCard` and stops there — rendering it is the presentation layer's (CLAUDE.md, "Frontend and design").
5. **The funding judge is not what the reader plan rewrites.** `2026-09-23-reader-and-multilingual-layer.md` replaces the *programme-page* reader (`reader.extract_statements`, `_READS`, `verified_statements`) with Jev's D4/D5. The funding judge stays three frontier readings, two families (master spec §8.2), and the typed-decisions spec puts "deadlines and amounts (the discovery design's card)" **out** of its own scope (§2) and lists "Jev for deadlines, amounts, dates" as *not built*, with "the discovery session's card work" as its trigger (§13). This plan is that card work, and it decides the question below.

## Which parts wait for the reader plan, and which land before it

The brief asks for this explicitly, so it is stated once here and restated at the head of each part.

| field | lands | why |
|---|---|---|
| amount, currency, period | **before** (Part A) | printed on the money line the judge already reads; one more output field on readings already paid for |
| duration | **before** (Part A) | same line ("for 24 months"), same readings |
| `timing`, `cycle` | **before** (Part A) | closed labels about the award, read with the listing as context, exactly like `route` |
| `required_documents` | **after** the decision layer and reader plan Tasks 2, 6, 7 (Part B) | a document checklist states no money, so the judge gives it no verdict, and `_FUNDING_TERMS` section selection drops a "Required documents" section that never mentions money. Selecting the sentences that list documents is D4's *documents* Noul and D5's `DOCUMENT` label — building a second selector now is the parallel implementation the brief forbids |
| `contact` | **after** the decision layer and reader plan Tasks 2, 3 (Part B) | "an office address, never a named person's" is a classification. The owner's 2026-09-22 decision gives every classification to the decision layer, and the only code-only alternative — a word list over e-mail local parts (`info@`, `office@` …) — is precisely the kind of English word list the typed-decisions spec §1 exists to remove. Task 3's hardened `normalize` is what lets a contact line in Uzbek or Kazakh verify |

**Why the Part A fields ride on the frontier readings and not on Jev.** Typed-decisions §13 names this card work as the trigger for "Jev for amounts". It is not adopted here, for three reasons: the judge already reads every money line three times, so the fields cost output tokens and no call; moving amounts alone to Jev would split one line's reading across two systems whose agreement rules differ; and principle 6 says measure before adopting. What *is* adopted from that design is its rule — **code finds and computes, the model only picks and copies** (§3.1a) — so a reading copies `"€1,200"` and picks `MONTHLY`, and code decides it is 1,200 euros. The Jev alternative (code finds every figure on the line, Jev picks the amount) is recorded in "Deliberately not in this plan" with the measurement that would adopt it.

**What Part A shares with the reader plan, so neither breaks the other:**

- `card_fields.on_line` compares through `reader.normalize`. Reader plan Task 3 hardens `normalize` for every script under the same name, so Part A inherits the fix with no edit; Task 10 adds the Uzbek-apostrophe case to Part A's tests once Task 3 is on master.
- Reader plan Task 2 moves `_HEADING_LINE` into `sentences.py` and re-exports it from `reader`; `funding_judge.py`'s import is unchanged by design.
- Reader plan Task 1 edits one line in `pipeline._fund_page` and one in `funding_yield._read_page` (the `readable_text` keyword — master already spells it `select_only_over_cap=False`, the plan `select_over=0`). Part A edits `funding_yield.py` elsewhere in the file; whichever merges second takes a trivial textual merge. Part B edits `_fund_page` itself, which is one more reason it lands after.

## Global Constraints

- **Never a number the page did not print.** A reading copies text; code decides whether the copy is on its line (`on_line`) and what figure, currency and month count it states. A copy not on its line is dropped and counted (`card_off_line`), never repaired.
- **Tiered agreement, unchanged in kind** (master spec §8.6, decision-log row 23). Every card field is a *detail*: a split makes that field `UNCONFIRMED` — blank on the row, named in `unconfirmed`, shown beside its quote — and never touches `served`. The existence set stays exactly `offered`, `holder`, `scope`. **`_served` is not edited by this plan.**
- **What the catalogue does not say, the facts do not say** (`apps/funding/facts.py` docstring). An "up to" figure, a monthly figure with no stated duration, a figure in an ambiguous currency: shown as printed, counted as nothing.
- **LLM baseline (CLAUDE.md, "LLM/AI security"; master spec principle 9).** Part A adds no model call: it widens the schema of calls `_fund_page` already pays for and rate-limits, and it keeps `extra="forbid"`, the capped `max_output_tokens`, `store=False` and the data-not-instructions framing. Part B adds decision-layer requests and carries its own `rate_limited()` in the same change (Task 10).
- **Country is data, never a branch** (master spec §3). Nothing names a country, funder or page. Currency symbols and names are rows in `docs/research/currency-evidence.csv`.
- **No person in the pipeline.** The 30-card hand check in Task 12 is a build-time measurement a person runs once, not a step anything waits on.
- **RLS is verified against a `NOBYPASSRLS` role or it is not verified** (CLAUDE.md, "Row-level security"). The test role bypasses RLS; every policy assertion here goes through `runtime_connection` (`tests/conftest.py:118`).
- **Tenancy of everything added:** every column and the one new table (`FundingRequiredDocument`, Task 8) are **shared catalogue** — an award's amount or documents are the same fact for every agency — under `shared_catalog_select` + `catalog_ingestion_write`, the pattern of `apps/funding/migrations/0030_program_awarding_institutions_rls.py`. No student data is ever written to any of them.
- **Migration numbers are never hard-coded.** `funding`'s leaf on master is `0048_merge_20260925_0838` today; generate with `makemigrations funding --name <name>`, and before committing run `ls apps/funding/migrations | sort | tail -4`. Two leaves means master moved: run `uv run python manage.py makemigrations funding --merge` and commit the merge migration with yours (the 2026-09-15 collision in CLAUDE.md is what this prevents).
- **Never run `ruff format`** — the repo is lint-only and it churns 26 files.
- **After every task:** `uv run ruff check apps config tests scripts`, `uv run mypy apps config`, `POSTGRES_DB=tehsil_card uv run pytest`, `uv run python manage.py makemigrations --check --dry-run` — all clean before the commit.

## Deliberately not in this plan, and where each belongs

§16 item 13's wording is wider than the brief's field list. Each item it names that this plan does not build, and why:

| not built here | where it belongs |
|---|---|
| **deadline and "key dates" storage** | build item 11 — `FundingCycleVerification.evidence` holds `stated_on`, `deadline`, `deadline_for` per quote (§9.3). `FundingDecision` already carries `deadlines`; nothing stores them today, which is why `facts.award_facts` builds `Evidence` with no deadline. Part C consumes item 11's output rather than duplicating it. |
| **`conditions` → `BenefitRule` rows, `NATIONALITY` scope rows, `GRADE`, `degree_levels`** | **a gap this plan found and does not close.** `FundingDecision.conditions` holds agreed `ConditionTriple`s and `write_funding_decision` stores none of them, so the pool never sees an agreed eligibility condition. It is eligibility, not the card's own fields, and it touches `benefit_rule_condition_type_shape_valid`, whose reconciliation `BenefitRule.ConditionType`'s docstring defers to "a later task". It needs its own plan. |
| the programme card's required documents | reader plan Task 9 writes them as `ProgramStatement(kind=DOCUMENT)`; showing them on a programme card is the programme card's work, not the award card's. |
| conditional amounts ("€1,000 for EU, €1,400 for non-EU") | a per-condition `amount_for`, the twin of `deadline_for`. Until then two agreed figures for one purpose on one award make that amount `UNCONFIRMED` (Task 3), which is the honest outcome. Build when Task 12's check counts them. |
| a `SEMESTER` period | adding it to `Period` would reach `CostComponent` too, and `affordability._normalize_to_program_total` treats any unknown period as a single charge. A per-semester figure is kept as printed with no number (Task 3). Build when Task 12 counts enough of them to matter. |
| number words ("two thousand euros"), lakh grouping, multipliers ("1.5 million") | `parse_amount` refuses them; the text stays on the card. Reader plan Task 4's `number_words` vocabulary is the future input. |
| Jev picking amounts over code-found figures | typed-decisions §13's candidate. **Trigger:** once the decision layer is on master, run it through the adapter beside the readings over the same 58 hosts; adopt only if its amount precision on Task 12's hand-checked set is ≥ the readings' and its cost per served card is lower. |

## File Structure

| file | part | responsibility |
|---|---|---|
| `apps/research/card_fields.py` (new) | A | `on_line`, `parse_amount`, `currencies_in`, `confirmed_currency`, `duration_months`, `evidence_rows` — pure |
| `docs/research/currency-evidence.csv` (new) | A | currency symbols, names and abbreviations as data; ambiguous forms listed so they confirm nothing |
| `apps/research/funding_judge.py` (modify) | A | `AmountStated`; `LineVerdict.amounts/duration/duration_unit/timing/cycle`; the question; `_MAX_OUTPUT_TOKENS`; `DecidedAmount`; `_card`; `FundingDecision`'s card fields |
| `apps/funding/models.py` (modify) | A, B | A: `FundingOpportunity.tuition/living/timing/cycle/duration_text/duration_months/card_quotes`, `FundingBenefit.amount_text/amount_bound/amount_quote`. B: `FundingOpportunity.contact_*`, `documents_read_at`; `FundingRequiredDocument` |
| `apps/funding/migrations/<leaf+1>_award_card_fields.py` (new, generated) | A | the Part A columns and their check constraints; no policy (table-level policies cover new columns) |
| `apps/funding/migrations/<leaf+1>_award_documents_and_contact.py` (new, generated + RunSQL) | B | the Part B columns, the new table, and its two policies in the same migration |
| `apps/research/funding_reader.py` (modify) | A, B | A: write the card columns and amounts; `card_of`. B: `write_award_documents`, `write_award_contact` |
| `apps/funding/card.py` (new) | A, C | `AwardCard`, `AmountLine`, `award_card`, `card_fill`, `card_values`; C: `deadline_state` |
| `apps/funding/facts.py` (modify) | A, B | read amounts counted only when stated as totals; `durations`; the card on `AwardCandidateFacts` |
| `apps/funding/evaluation.py`, `apps/funding/pack.py` (modify) | A, C | `AwardCandidateFacts.card`, `PackedAward.card`; C: the refusal |
| `apps/research/spine.py` (modify) | A, B | pass `durations`; B: fetch documents |
| `apps/research/card_questions.py` (new) | B | `award_documents`, `documents_for`, `contact_candidates`, `award_contact` — the only module that builds the contact question |
| `apps/research/pipeline.py` (modify) | B | `_read_card` after the decisions are written, with its own `rate_limited` |
| `apps/research/management/commands/funding_yield.py` (modify) | A | card tallies; `--cards-csv` |
| `apps/research/management/commands/card_check.py` (new) | A | the 30-card sample and its score |
| `tests/tenancy/test_database_isolation.py` (modify) | B | `funding_fundingrequireddocument` joins `_SHARED_TABLES` |
| tests (new) | A–C | `tests/research/test_card_fields.py`, `test_funding_judge_card.py`, `test_card_questions.py`, `test_award_card_rls.py`, `test_card_check.py`; `tests/funding/test_card.py`, `test_award_card_columns.py` |

---

# Part A — lands now, on master

### Task 1: The card's values, checked by code against their line

Spec §8.3 ("as written"), typed-decisions §3.1a ("code counts, computes and finds candidates"). Pure; nothing wires it in yet.

**Files:**
- Create: `apps/research/card_fields.py`, `docs/research/currency-evidence.csv`
- Test: `tests/research/test_card_fields.py`

**Interfaces:**
- Consumes: `apps.research.reader.normalize`, `apps.reference_data.ISO_4217_CODES`
- Produces: `on_line(value, line) -> bool`, `parse_amount(text) -> Decimal | None`, `currencies_in(text) -> frozenset[str]`, `confirmed_currency(claimed, amount_text) -> str | None`, `duration_months(text, unit) -> int | None`, `EvidenceRow`, `evidence_rows(path=EVIDENCE_FILE)`, `EVIDENCE_FILE`

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_card_fields.py
"""The card's values, checked by code against the line they were copied from.

A reading copies text and picks a label; this module is where "1.200" becomes
twelve hundred and "2 years" becomes 24 months. Every case a page could print
ambiguously is pinned to NO number rather than a guessed one.
"""

from decimal import Decimal

import pytest

from apps.reference_data import ISO_4217_CODES
from apps.research.card_fields import (
    confirmed_currency,
    currencies_in,
    duration_months,
    evidence_rows,
    on_line,
    parse_amount,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("€1,200", Decimal("1200")),
        ("992 Euro", Decimal("992")),
        ("1.200 €", Decimal("1200")),
        ("1 500 AZN", Decimal("1500")),
        ("1 500 AZN", Decimal("1500")),
        ("CHF 1'200", Decimal("1200")),
        ("€1,200.50", Decimal("1200.50")),
        ("1.200,50 €", Decimal("1200.50")),
        ("12.000.000 TL", Decimal("12000000")),
        ("€10000", Decimal("10000")),
        ("٢٥٠٠ AZN", Decimal("2500")),
    ],
)
def test_one_figure_is_read_the_way_the_page_printed_it(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "full tuition",        # no figure at all
        "€800–1,200",          # a range is two figures
        "1.5 million euros",   # one digit after a mark: money's rules do not explain it
        "12,50,000 INR",       # lakh grouping -- refused, never guessed
        "1,200.000",           # two different marks in the whole part
        "€1,200 and €300",     # two amounts copied as one
    ],
)
def test_anything_but_one_unambiguous_figure_is_no_number(text):
    assert parse_amount(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("€1,200", {"EUR"}),
        ("992 Euro", {"EUR"}),
        ("1 500 AZN", {"AZN"}),
        ("₼500", {"AZN"}),
        ("5.000 TL", {"TRY"}),
        ("US$5,000", {"USD"}),
        ("CA$1,000", {"CAD"}),        # "a$" inside "ca$" is not the Australian sign
        ("5000元", {"CNY"}),           # a sign may touch its figure
        ("300 000 теңге", {"KZT"}),
        ("$5,000", set()),            # a dollar of which country: the page did not say
        ("1,000 manat", set()),       # Azerbaijani or Turkmen
        ("¥300,000", set()),          # yen or yuan
        ("€1,000 or US$1,100", {"EUR", "USD"}),
    ],
)
def test_a_currency_is_what_the_copy_names_and_nothing_ambiguous(text, expected):
    assert currencies_in(text) == frozenset(expected)


def test_a_currency_is_confirmed_only_when_the_copy_names_it_alone():
    assert confirmed_currency("EUR", "€1,200") == "EUR"
    assert confirmed_currency("USD", "$5,000") is None            # not evidenced
    assert confirmed_currency("GBP", "€1,200") is None            # the copy names another
    assert confirmed_currency("EUR", "€1,000 or US$1,100") is None  # names two
    assert confirmed_currency("UNSTATED", "€1,200") is None


@pytest.mark.parametrize(
    ("text", "unit", "expected"),
    [
        ("24 months", "MONTHS", 24),
        ("for up to 12 months", "MONTHS", 12),
        ("2 years", "YEARS", 24),
        ("24 ay", "MONTHS", 24),        # the unit is the readings'; the figure is code's
        ("two years", "YEARS", None),   # a number word keeps its text and gives no figure
        ("4 semesters", "OTHER", None),  # a semester is not a fixed number of months
        ("12-24 months", "MONTHS", None),  # a range
        ("200 months", "MONTHS", None),  # longer than any master's award runs
    ],
)
def test_months_come_from_the_one_figure_and_the_readings_unit(text, unit, expected):
    assert duration_months(text, unit) == expected


def test_a_copy_is_on_its_line_the_way_quotes_are_compared():
    line = "Scholars receive  €1,200 per month for 24 months."
    assert on_line("€1,200", line)
    assert on_line("24 MONTHS", line)   # case and whitespace do not count, as for quotes
    assert not on_line("€1,300", line)
    assert not on_line("", line)


def test_every_evidence_row_names_a_real_currency_and_is_reviewable():
    rows = evidence_rows()
    assert rows, "the evidence file is empty"
    for row in rows:
        assert row.currency in ISO_4217_CODES, row
        assert row.kind in ("symbol", "name", "abbreviation"), row
        assert row.review_status in ("drafted", "reviewed"), row
    pairs = [(row.form.casefold(), row.currency) for row in rows]
    assert len(pairs) == len(set(pairs)), "a form is listed twice for one currency"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_card_fields.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.research.card_fields'`

- [ ] **Step 3: Write the data file**

```csv
form,currency,kind,review_status
€,EUR,symbol,drafted
euro,EUR,name,drafted
euros,EUR,name,drafted
евро,EUR,name,drafted
еуро,EUR,name,drafted
avro,EUR,name,drafted
£,GBP,symbol,drafted
pound sterling,GBP,name,drafted
pounds sterling,GBP,name,drafted
$,USD,symbol,drafted
$,CAD,symbol,drafted
$,AUD,symbol,drafted
$,NZD,symbol,drafted
$,SGD,symbol,drafted
$,HKD,symbol,drafted
$,MXN,symbol,drafted
us$,USD,symbol,drafted
us dollars,USD,name,drafted
u.s. dollars,USD,name,drafted
c$,CAD,symbol,drafted
ca$,CAD,symbol,drafted
a$,AUD,symbol,drafted
au$,AUD,symbol,drafted
₺,TRY,symbol,drafted
tl,TRY,abbreviation,drafted
türk lirası,TRY,name,drafted
turkish lira,TRY,name,drafted
₼,AZN,symbol,drafted
manat,AZN,name,drafted
manat,TMT,name,drafted
azərbaycan manatı,AZN,name,drafted
₸,KZT,symbol,drafted
tenge,KZT,name,drafted
теңге,KZT,name,drafted
тенге,KZT,name,drafted
₽,RUB,symbol,drafted
₾,GEL,symbol,drafted
lari,GEL,name,drafted
ლარი,GEL,name,drafted
֏,AMD,symbol,drafted
դրամ,AMD,name,drafted
₮,MNT,symbol,drafted
төгрөг,MNT,name,drafted
so'm,UZS,name,drafted
soʻm,UZS,name,drafted
сўм,UZS,name,drafted
som,UZS,name,drafted
som,KGS,name,drafted
сом,KGS,name,drafted
₹,INR,symbol,drafted
₨,PKR,symbol,drafted
₨,LKR,symbol,drafted
₨,NPR,symbol,drafted
₩,KRW,symbol,drafted
₴,UAH,symbol,drafted
zł,PLN,symbol,drafted
kč,CZK,symbol,drafted
ft,HUF,abbreviation,drafted
forint,HUF,name,drafted
kr,SEK,abbreviation,drafted
kr,NOK,abbreviation,drafted
kr,DKK,abbreviation,drafted
kr,ISK,abbreviation,drafted
¥,JPY,symbol,drafted
¥,CNY,symbol,drafted
円,JPY,symbol,drafted
元,CNY,symbol,drafted
yen,JPY,name,drafted
yuan,CNY,name,drafted
renminbi,CNY,name,drafted
```

Save as `docs/research/currency-evidence.csv`. Rows are `drafted`: before Task 12's run, check each symbol and name against Unicode CLDR's `currencies.json` for its language (`cldr-json/cldr-numbers-full/main/<lang>/currencies.json` — `en`, `de`, `tr`, `ru`, `az`, `kk`, `uz`, `ka`, `hy`, `mn`) and mark the row `reviewed`. A form that CLDR lists for a *second* currency gets that currency as another row, which makes it ambiguous and confirm nothing — the safe direction. Ruble *names* (`руб.`, `рублей`) are deliberately absent: "белорусских рублей" is Belarusian and would confirm RUB.

- [ ] **Step 4: Write the module**

```python
# apps/research/card_fields.py
"""The card's own fields, checked by code against the line they came from.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
section 8.3 -- amount, currency, period and duration "as written" -- and 10.4,
the card. Pure apart from reading one data file once.

The readings copy a value as the page wrote it; this module decides whether
the copy is on the line and which number, if any, it states. A reading can
therefore mislabel a figure the page printed but never put one on a card that
the page did not print -- the guarantee `funding_lines` already gives the quote.

**Code computes; the readings only copy and classify.** A reading never
converts a figure, a currency or a duration: "1.200" becomes twelve hundred and
"2 years" becomes 24 months here, where a test pins it. That is the typed-
decisions spec's rule (section 3.1a) applied to the readings this reader keeps.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

from apps.reference_data import ISO_4217_CODES

from .reader import normalize

#: Data, not code (spec section 3, principle 7). Deliberately NOT a vocabulary
#: in docs/research/vocabulary.csv: a vocabulary there may only ever ADD a
#: candidate, and this file decides whether a number is written at all. So only
#: an unambiguous form confirms. A missing form costs a number -- the card shows
#: the text as printed -- while a wrong one would put a figure in the wrong
#: currency in front of a student, which is the failure worth paying to avoid.
EVIDENCE_FILE = (
    Path(__file__).resolve().parents[2] / "docs" / "research" / "currency-evidence.csv"
)

#: Digits in any script -- a str pattern's \d is Unicode-aware -- joined by the
#: marks pages print between digit groups.
_NUMBER = re.compile(r"\d[\d.,'’   ]*\d|\d")
_GROUP_SPACE = re.compile(r"['’   ]")
_GROUP = re.compile(r"[_.,]")
_CENTS = re.compile(r"[.,](\d{2})$")
#: An ISO 4217 code as a page prints one: three capitals standing alone.
_CODE = re.compile(r"(?<![A-Za-z])[A-Z]{3}(?![A-Za-z])")
#: No master's award runs longer than ten years; a figure above it is a misread.
_MAX_MONTHS = 120


@dataclass(frozen=True)
class EvidenceRow:
    form: str
    currency: str
    kind: str
    review_status: str


def on_line(value: str, line: str) -> bool:
    """Whether `value` is printed on `line`, compared the way quotes are."""
    wanted = normalize(value)
    return bool(wanted) and wanted in normalize(line)


def _ascii_digits(text: str) -> str:
    return "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() else ch for ch in text)


def _figure(token: str) -> Decimal | None:
    """One printed number, or None when its marks are ambiguous.

    Money's rules, not a locale's: a mark followed by exactly two final digits
    is the decimal mark (1.200,50 and 1,200.50); every other mark separates
    groups of exactly three (1.200, 1,200, 1 200, 1'200). A lakh grouping, one
    digit after a mark, or two different marks in the whole part is refused.
    """
    plain = _GROUP_SPACE.sub("_", _ascii_digits(token))
    whole, cents = plain, ""
    tail = _CENTS.search(plain)
    if tail is not None and any(ch.isdigit() for ch in plain[: tail.start()]):
        whole, cents = plain[: tail.start()], tail.group(1)
    groups = _GROUP.split(whole)
    if len(set(_GROUP.findall(whole))) > 1 or not all(group.isdigit() for group in groups):
        return None
    if len(groups) > 1 and not (
        1 <= len(groups[0]) <= 3 and all(len(group) == 3 for group in groups[1:])
    ):
        return None
    try:
        return Decimal("".join(groups) + (f".{cents}" if cents else ""))
    except InvalidOperation:
        return None


def parse_amount(text: str) -> Decimal | None:
    """The one figure `text` states, or None when it states none or several."""
    found = [match.group().strip() for match in _NUMBER.finditer(text)]
    return _figure(found[0]) if len(found) == 1 else None


def evidence_rows(path: Path = EVIDENCE_FILE) -> tuple[EvidenceRow, ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(
            EvidenceRow(row["form"], row["currency"], row["kind"], row["review_status"])
            for row in csv.DictReader(handle)
        )


def _pattern(form: str, kind: str) -> re.Pattern[str]:
    """A sign may touch its figure ("5000元", "₼500") but, when it begins with a
    letter, may not continue a word ("ca$" is not "a$"). A name or an
    abbreviation stands alone ("euro" is not inside "euros")."""
    if kind == "symbol":
        start = r"(?<![^\W\d_])" if form[0].isalpha() else ""
        return re.compile(start + re.escape(form))
    return re.compile(r"(?<!\w)" + re.escape(form) + r"(?!\w)")


@cache
def _forms() -> tuple[tuple[re.Pattern[str], str], ...]:
    """Every form that names exactly one currency, as a pattern.

    A form listed for two currencies ($, kr, ¥, manat, som) is left out
    entirely: it confirms neither.
    """
    by_form: dict[str, tuple[str, set[str]]] = {}
    for row in evidence_rows():
        kind, codes = by_form.setdefault(row.form.casefold(), (row.kind, set()))
        codes.add(row.currency)
    return tuple(
        (_pattern(form, kind), next(iter(codes)))
        for form, (kind, codes) in by_form.items()
        if len(codes) == 1
    )


def currencies_in(text: str) -> frozenset[str]:
    """Every currency `text` names unambiguously: an ISO code, or a listed form."""
    named = {code for code in _CODE.findall(text) if code in ISO_4217_CODES}
    folded = text.casefold()
    named.update(code for pattern, code in _forms() if pattern.search(folded))
    return frozenset(named)


def confirmed_currency(claimed: str, amount_text: str) -> str | None:
    """The reading's currency, when the copied amount names it and nothing else.

    Checked on the copy, not on the whole line: a line saying "€1,000 (about
    US$1,100)" names two, and only the copy says which one the figure is in.
    """
    return claimed if currencies_in(amount_text) == {claimed} else None


def duration_months(text: str, unit: str) -> int | None:
    """Months, from the one figure the copy prints and the unit the readings chose.

    The readings classify the unit (MONTHS, YEARS, OTHER); code multiplies. A
    number word, a range, a semester count or an implausible figure keeps its
    text on the card and gives no number.
    """
    figures = re.findall(r"\d+", _ascii_digits(text))
    if unit not in ("MONTHS", "YEARS") or len(figures) != 1:
        return None
    months = int(figures[0]) * (12 if unit == "YEARS" else 1)
    return months if 0 < months <= _MAX_MONTHS else None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_card_fields.py -v`
Expected: PASS (all parametrised cases)

- [ ] **Step 6: The after-every-task checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
git add apps/research/card_fields.py docs/research/currency-evidence.csv tests/research/test_card_fields.py
git commit -m "feat(research): the card's values, checked by code against their line"
```

---

### Task 2: The verdict carries the card's fields

Spec §8.3's table. The readings copy an amount and a duration as printed and pick every other value from a closed list. **No new call**: these ride on the three readings `_fund_page` already pays for.

**Files:**
- Modify: `apps/research/funding_judge.py`
- Test: `tests/research/test_funding_judge_card.py` (new)

**Interfaces:**
- Consumes: nothing new
- Produces: `AmountStated`; `LineVerdict.amounts`, `.duration`, `.duration_unit`, `.timing`, `.cycle`; `_MAX_OUTPUT_TOKENS = 10_000`

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_funding_judge_card.py
"""The card's fields on a reading, and how three readings agree about them.

Spec 8.3 (the fields), 8.6 (a split detail is UNCONFIRMED, never a hidden award).
"""

import json

import pytest
from django.conf import settings
from pydantic import ValidationError

from apps.research.funding_judge import (
    _MAX_OUTPUT_TOKENS,
    _QUESTION,
    AmountStated,
    FundingVerdicts,
    Line,
    judge,
)
from tests.research.conftest import FakeResponse, FakeResponses, verdict

STIPEND = AmountStated(covers="LIVING", amount="€1,200", currency="EUR", period="MONTHLY")


def test_a_verdict_carries_the_cards_fields_and_defaults_to_unstated():
    plain = verdict(0)
    assert (plain.amounts, plain.duration, plain.duration_unit, plain.timing, plain.cycle) == (
        (), "UNSTATED", "UNSTATED", "UNSTATED", "UNSTATED",
    )
    full = verdict(
        0, amounts=(STIPEND,), duration="24 months", duration_unit="MONTHS",
        timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
    )
    assert full.amounts[0].bound == "EXACT"


@pytest.mark.parametrize(
    "bad",
    [
        {"covers": "SALARY"}, {"period": "WEEKLY"}, {"currency": "euro"},
        {"amount": ""}, {"amount": "x" * 41}, {"bound": "ABOUT"},
    ],
)
def test_an_amount_is_a_closed_shape(bad):
    fields = {"covers": "LIVING", "amount": "€1,200", "currency": "EUR", "period": "MONTHLY"}
    with pytest.raises(ValidationError):
        AmountStated(**{**fields, **bad})


@pytest.mark.parametrize(
    ("field", "value"), [("timing", "SOON"), ("cycle", "BIENNIAL"), ("duration_unit", "WEEKS")]
)
def test_timing_cycle_and_the_duration_unit_are_closed_lists(field, value):
    with pytest.raises(ValidationError):
        verdict(0, **{field: value})


def test_a_line_states_at_most_four_amounts():
    with pytest.raises(ValidationError):
        verdict(0, amounts=(STIPEND,) * 5)


def test_the_question_asks_for_copies_and_forbids_arithmetic():
    for phrase in (
        "amounts:", "copied exactly as the line writes it", "never compute or convert",
        "duration_unit", "timing:", "cycle:", "ROLLING", "PRE_ARRIVAL", "UP_TO",
    ):
        assert phrase in _QUESTION


def test_claudes_doubled_cap_stays_under_the_sdks_non_streaming_wall():
    """funding_judge's own comment on _MAX_OUTPUT_TOKENS: above 21,333 the
    installed SDK refuses a non-streaming call and every Claude reading is lost
    in silence. Claude's reading gets twice the cap."""
    assert 2 * _MAX_OUTPUT_TOKENS <= 21_333


def test_the_real_anthropic_sdk_accepts_a_verdict_with_the_cards_fields():
    """Offline, through the installed SDK, as the existing schema test does:
    the nested AmountStated must survive the SDK's schema transform."""
    anthropic = pytest.importorskip("anthropic")
    import httpx2

    answer = FundingVerdicts(verdicts=(verdict(
        1, amounts=(STIPEND,), duration="24 months", duration_unit="MONTHS",
        timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
    ),))

    def _handler(request):
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant",
            "model": settings.ANTHROPIC_JUDGE_MODEL, "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": answer.model_dump_json()}],
        })

    claude = anthropic.Anthropic(
        api_key="test-key-not-a-secret",
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(_handler)),
    ).messages
    openai = FakeResponses(FakeResponse(output_parsed=FundingVerdicts()))
    chunk = (Line("Scholarships", ""), Line("Scholars receive €1,200 per month.", "Scholarships"))
    readings = judge(openai, claude, source_id="s", chunk=chunk)
    assert readings[-1] == answer
    assert json.loads(answer.model_dump_json())["verdicts"][0]["amounts"][0]["covers"] == "LIVING"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_funding_judge_card.py -v`
Expected: FAIL — `ImportError: cannot import name 'AmountStated'`

- [ ] **Step 3: Add the closed lists and `AmountStated`**

In `apps/research/funding_judge.py`, after `_HOLDERS: tuple[str, ...] = get_args(_Holder)`:

```python
#: What a stated sum pays for. LIVING is a stipend or monthly allowance;
#: TOTAL is one sum the page does not split by purpose ("a scholarship of
#: €10,000"). The writer maps each onto a FundingBenefit kind.
_Covers = Literal[
    "TUITION", "LIVING", "TRAVEL", "HOUSING", "INSURANCE", "RELOCATION", "TOTAL", "OTHER"
]
#: OTHER is any period the Period enum cannot carry -- a semester, a term. The
#: figure is then kept as printed and never counted (card_fields, facts).
_AmountPeriod = Literal["MONTHLY", "ANNUAL", "ONE_OFF", "FULL_PROGRAM", "OTHER"]
#: "up to €10,000" is a ceiling, not an amount: shown, never counted as coverage.
_Bound = Literal["EXACT", "UP_TO", "AT_LEAST"]
_DurationUnit = Literal["MONTHS", "YEARS", "OTHER", "UNSTATED"]
_Timing = Literal["PRE_ARRIVAL", "POST_ARRIVAL", "EITHER", "UNSTATED"]
_Cycle = Literal["ANNUAL_FIXED", "ROLLING", "WITH_ADMISSION_CYCLE", "ONE_OFF", "UNSTATED"]


class AmountStated(BaseModel):
    """One sum a line states, copied -- never computed -- by a reading.

    `amount` is the page's own characters, currency sign or word included
    ("€1,200", "992 Euro"), so card_fields can find the figure and the
    currency in the copy and check the copy is on the line. `currency` is the
    reading's ISO code, trusted only when the copy names it alone.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    covers: _Covers
    amount: str = Field(min_length=1, max_length=40)
    currency: str = Field(default="UNSTATED", pattern=r"^[A-Z]{3}$|^UNSTATED$")
    period: _AmountPeriod
    bound: _Bound = "EXACT"
```

- [ ] **Step 4: Add the fields to `LineVerdict`**

In `LineVerdict`, after `conditions: ...` and before `name`:

```python
    #: The card's own fields (spec 8.3; build item 13). An amount and a
    #: duration are COPIED as the line writes them; every other value is a
    #: label from a closed list. apps.research.card_fields does the arithmetic.
    #: Four amounts per line at most: a line naming more is a fee table, and
    #: the cap stops one line consuming the verdict budget, as for conditions.
    amounts: tuple[AmountStated, ...] = Field(default=(), max_length=4)
    duration: str = Field(default="UNSTATED", max_length=40)
    duration_unit: _DurationUnit = "UNSTATED"
    timing: _Timing = "UNSTATED"
    cycle: _Cycle = "UNSTATED"
```

- [ ] **Step 5: Extend the question**

In `_QUESTION`, replace the final `"Lines may be in any language."` with:

```python
    "amounts: every sum of money the line states for the award, each with covers (TUITION; "
    "LIVING for a stipend or monthly allowance; TRAVEL; HOUSING; INSURANCE; RELOCATION; TOTAL "
    "for one sum the line does not split by purpose; OTHER), amount copied exactly as the line "
    "writes it together with its currency sign, code or word and nothing else (\"€1,200\", "
    "\"992 Euro\", \"1 500 AZN\"), currency as its ISO 4217 code or UNSTATED, period (MONTHLY, "
    "ANNUAL, ONE_OFF, FULL_PROGRAM for the whole programme, OTHER for any other period such as "
    "a semester), and bound (EXACT; UP_TO for \"up to\" or \"a maximum of\"; AT_LEAST). Give no "
    "amount for a line that states none, and never compute or convert one.\n"
    "duration: how long the award is paid, copied exactly as the line writes it (\"24 months\", "
    "\"for two years\"), or UNSTATED. duration_unit: MONTHS or YEARS when that copy counts "
    "months or years, OTHER for any other unit or wording, UNSTATED when there is no duration.\n"
    "timing: PRE_ARRIVAL when the award is decided before the student arrives, POST_ARRIVAL "
    "when only students already enrolled there can apply, EITHER, or UNSTATED. cycle: "
    "ANNUAL_FIXED for one call a year with a fixed deadline, ROLLING for applications taken at "
    "any time, WITH_ADMISSION_CYCLE when it is decided with the admission application, ONE_OFF "
    "for a single call, or UNSTATED.\n"
    "Lines may be in any language."
```

- [ ] **Step 6: Raise the output cap, with the arithmetic beside it**

Replace `_MAX_OUTPUT_TOKENS = 9_000` and extend its comment's last paragraph:

```python
#: Raised to 10_000 for the card's fields (build item 13): an amount is a
#: covers label, a copy of at most 40 characters, a code and two labels, and a
#: funding line states one or two -- call it another ~40 tokens on the lines
#: that state money, which are a minority of any chunk. Claude's doubled cap
#: is then 20_000, still under the 21_333 non-streaming wall measured above,
#: and tests/research/test_funding_judge_card.py pins that.
_MAX_OUTPUT_TOKENS = 10_000
```

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_funding_judge_card.py tests/research/test_funding_judge.py -v`
Expected: PASS. `test_the_two_openai_readings_share_an_identical_prefix` still passes: the prefix changed for every reading at once.

- [ ] **Step 8: Checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
git add apps/research/funding_judge.py tests/research/test_funding_judge_card.py
git commit -m "feat(research): the funding verdict carries the card's fields, copied not computed"
```

---

### Task 3: Three readings agree on a card, one field at a time

Spec §8.6 tiered agreement, applied to the card. **Per line**, a field is agreed when every YES verdict on that line gives the same value; **per award**, lines that state nothing do not contradict lines that do, and two lines stating different values make the field `UNCONFIRMED`. The card fields are deliberately **not** added to `_DECIDED`: that tuple also drives `_representative` and a line's own agreed/disputed status, and adding six details to it would change which lines merge and which name an award — the verbosity penalty §8.8 already records.

**Files:**
- Modify: `apps/research/funding_judge.py`
- Test: `tests/research/test_funding_judge_card.py`

**Interfaces:**
- Consumes: `card_fields.{on_line, parse_amount, confirmed_currency, duration_months}`
- Produces: `DecidedAmount`; `FundingDecision.amounts`, `.duration`, `.duration_months`, `.timing`, `.cycle`, `.card_quotes`, `.card_off_line`; card field names (`amount`, `duration`, `timing`, `cycle`) in `disputed` and, on an `AGREED` award, in `unconfirmed`

- [ ] **Step 1: Write the failing tests** (append to `tests/research/test_funding_judge_card.py`)

```python
from decimal import Decimal  # noqa: E402

from apps.research.funding_judge import DecidedAmount, awards, line_outcomes  # noqa: E402

LINE = "Scholars receive €1,200 per month for 24 months, paid before arrival."
OTHER = "The scholarship is renewed every year."
CHUNK = (Line("Scholarships", ""), Line(LINE, "Scholarships"), Line(OTHER, "Scholarships"))
CARD = dict(
    living="FULL", amounts=(STIPEND,), duration="24 months", duration_unit="MONTHS",
    timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
)


def _r(*verdicts):
    return FundingVerdicts(verdicts=verdicts)


def _decide(*readings, chunk=CHUNK):
    (decision,) = awards(line_outcomes(chunk, list(readings))).decisions
    return decision


def test_three_readings_agreeing_on_a_line_write_its_card():
    reading = _r(verdict(1, **CARD))
    decision = _decide(reading, reading, reading)
    assert decision.agreement == "AGREED"
    assert decision.amounts == (DecidedAmount(
        covers="LIVING", amount_text="€1,200", amount=Decimal("1200"), currency="EUR",
        period="MONTHLY", bound="EXACT", quote=LINE,
    ),)
    assert (decision.duration, decision.duration_months) == ("24 months", 24)
    assert (decision.timing, decision.cycle) == ("PRE_ARRIVAL", "ANNUAL_FIXED")
    assert dict(decision.card_quotes) == {
        "amount:LIVING": LINE, "duration": LINE, "timing": LINE, "cycle": LINE,
    }
    assert decision.unconfirmed == () and decision.card_off_line == 0


def test_a_figure_one_reading_invented_unconfirms_the_amount_not_the_award():
    good = _r(verdict(1, **CARD))
    invented = _r(verdict(1, **{**CARD, "amounts": (STIPEND.model_copy(update={"amount": "€1,400"}),)}))
    decision = _decide(good, good, invented)
    assert decision.agreement == "AGREED"
    assert decision.amounts == ()
    assert "amount" in decision.unconfirmed
    assert decision.card_off_line == 1


def test_a_figure_all_three_readings_invented_is_written_nowhere_and_counted():
    invented = _r(verdict(1, **{**CARD, "amounts": (STIPEND.model_copy(update={"amount": "€1,300"}),)}))
    decision = _decide(invented, invented, invented)
    assert decision.amounts == () and "amount" not in decision.unconfirmed
    assert decision.card_off_line == 3


def test_an_ambiguous_currency_keeps_the_text_and_writes_no_number():
    line = "Each scholar receives a one-time award of $5,000."
    stated = AmountStated(covers="TOTAL", amount="$5,000", currency="USD", period="ONE_OFF")
    reading = _r(verdict(0, amounts=(stated,)))
    (amount,) = _decide(reading, reading, reading, chunk=(Line(line, "Awards"),)).amounts
    assert (amount.amount_text, amount.amount, amount.currency) == ("$5,000", None, None)


def test_a_per_semester_figure_keeps_its_text_and_no_number():
    line = "Tuition is reduced by €500 per semester."
    stated = AmountStated(covers="TUITION", amount="€500", currency="EUR", period="OTHER")
    reading = _r(verdict(0, amounts=(stated,)))
    (amount,) = _decide(reading, reading, reading, chunk=(Line(line, "Fees"),)).amounts
    assert (amount.amount, amount.currency, amount.period) == (None, None, "OTHER")


def test_a_split_on_timing_blanks_timing_and_keeps_the_award_shown():
    a = _r(verdict(1, **CARD))
    b = _r(verdict(1, **{**CARD, "timing": "UNSTATED"}))
    decision = _decide(a, a, b)
    assert decision.agreement == "AGREED" and decision.timing == "UNSTATED"
    assert "timing" in decision.unconfirmed and "timing" in decision.disputed
    assert "timing" not in dict(decision.card_quotes)
    assert decision.cycle == "ANNUAL_FIXED"   # one split field blanks one field


def test_a_line_that_states_nothing_does_not_contradict_one_that_does():
    reading = _r(verdict(1, **CARD), verdict(2, living="FULL"))
    decision = _decide(reading, reading, reading)
    assert (decision.timing, decision.duration_months) == ("PRE_ARRIVAL", 24)
    assert decision.unconfirmed == ()


def test_two_lines_stating_different_durations_unconfirm_the_duration():
    top = "Top scholars are funded for 12 months."
    chunk = (Line(LINE, "Scholarships"), Line(top, "Scholarships"))
    reading = _r(
        verdict(0, **CARD),
        verdict(1, living="FULL", duration="12 months", duration_unit="MONTHS"),
    )
    decision = _decide(reading, reading, reading, chunk=chunk)
    assert (decision.duration, decision.duration_months) == ("UNSTATED", None)
    assert "duration" in decision.unconfirmed


def test_an_unagreed_award_keeps_its_card_but_names_nothing_unconfirmed():
    """`unconfirmed` is only ever reported on a shown award (spec 8.6); on an
    UNAGREED one the whole row is the caveat. `disputed` keeps the names for
    the operator either way."""
    a = _r(verdict(1, **CARD))
    b = _r(verdict(1, **{**CARD, "holder": "PRIVATE_FOUNDATION", "timing": "UNSTATED"}))
    decision = _decide(a, a, b)
    assert decision.agreement == "UNAGREED"
    assert decision.unconfirmed == () and "timing" in decision.disputed
```

- [ ] **Step 2: Run to verify it fails**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_funding_judge_card.py -v -k "card or figure or currency or semester or timing or states_nothing or durations or unagreed"`
Expected: FAIL — `ImportError: cannot import name 'DecidedAmount'`

- [ ] **Step 3: Add `DecidedAmount` and the card fields on `FundingDecision`**

In `apps/research/funding_judge.py`, add to the imports:

```python
from decimal import Decimal

from .card_fields import confirmed_currency, duration_months, on_line, parse_amount
from .reader import _HEADING_LINE, normalize
```

(replacing the existing `from .reader import _HEADING_LINE`). Before `class FundingDecision`:

```python
@dataclass(frozen=True)
class DecidedAmount:
    """One sum an award's readings agreed a line states.

    `amount` and `currency` are set together or not at all -- the database's
    funding_benefit_amount_currency_pair says the same -- and only when code
    found exactly one figure in the copy, the copy names exactly the reading's
    currency, and the period is one the arithmetic can use. Otherwise the card
    shows `amount_text` as the page printed it and nothing counts it.
    """

    covers: str
    amount_text: str
    amount: Decimal | None
    currency: str | None
    period: str
    bound: str
    quote: str
```

At the end of `FundingDecision`, after `disputed_conditions`:

```python
    #: The card's own fields (spec 8.3, 10.4; build item 13). A field the
    #: readings split on is UNSTATED here and named in `disputed` (and, on an
    #: AGREED award, in `unconfirmed`), exactly like route or money_form.
    amounts: tuple[DecidedAmount, ...] = ()
    duration: str = "UNSTATED"
    duration_months: int | None = None
    timing: str = "UNSTATED"
    cycle: str = "UNSTATED"
    #: (field, the verbatim line that stated it); amounts are keyed "amount:<covers>".
    card_quotes: tuple[tuple[str, str], ...] = ()
    #: Copies a reading gave that are not on their line -- dropped, never
    #: repaired. The 58-host tally prints it: a rising count is a reading
    #: inventing figures, which agreement alone would only sometimes catch.
    card_off_line: int = 0
```

- [ ] **Step 4: Write `_card`**

After `_modal` in `apps/research/funding_judge.py`:

```python
_CARD_LABELS = ("timing", "cycle")


@dataclass(frozen=True)
class _Card:
    amounts: tuple[DecidedAmount, ...]
    duration: str
    duration_months: int | None
    timing: str
    cycle: str
    quotes: tuple[tuple[str, str], ...]
    unconfirmed: frozenset[str]
    off_line: int


def _amount_key(stated: AmountStated) -> tuple[object, ...]:
    """What two readings must agree on for one sum: the figure when code can
    read one (so "€1,200" and "€ 1,200" agree), the copy otherwise."""
    figure = parse_amount(stated.amount)
    return (
        stated.covers,
        figure if figure is not None else normalize(stated.amount),
        stated.currency,
        stated.period,
        stated.bound,
    )


def _decided_amount(stated: AmountStated, line: str) -> DecidedAmount:
    figure = parse_amount(stated.amount)
    currency = confirmed_currency(stated.currency, stated.amount)
    countable = figure is not None and currency is not None and stated.period != "OTHER"
    return DecidedAmount(
        covers=stated.covers,
        amount_text=stated.amount,
        amount=figure if countable else None,
        currency=currency if countable else None,
        period=stated.period,
        bound=stated.bound,
        quote=line,
    )


def _card(members: list[LineOutcome]) -> _Card:
    """The card's fields for one award, from its lines' YES verdicts.

    Per line: a field is agreed when every YES verdict on the line gives it the
    same value; a copy not on the line is dropped first and counted, so it can
    only ever cost agreement, never add a figure. Per award: a line stating
    nothing does not contradict a line stating something, and two lines
    stating different values make the field unconfirmed.
    """
    unconfirmed: set[str] = set()
    quotes: dict[str, str] = {}
    off_line = 0
    labels: dict[str, set[str]] = {name: set() for name in _CARD_LABELS}
    durations: dict[tuple[str, str], str] = {}
    by_covers: dict[str, dict[tuple[object, ...], DecidedAmount]] = {}
    split_covers: set[str] = set()
    for member in members:
        yes = [v for v in member.verdicts if v.offered == "YES"]
        if not yes:
            continue
        line = member.line.text
        for name in _CARD_LABELS:
            values = {getattr(v, name) for v in yes}
            if len(values) > 1:
                unconfirmed.add(name)
            elif (value := next(iter(values))) != "UNSTATED":
                labels[name].add(value)
                quotes.setdefault(name, line)
        copies: list[tuple[str, str]] = []
        for v in yes:
            if v.duration == "UNSTATED":
                copies.append(("UNSTATED", "UNSTATED"))
            elif on_line(v.duration, line):
                copies.append((v.duration, v.duration_unit))
            else:
                off_line += 1
                copies.append(("", "UNSTATED"))  # a different answer from every real one
        if len({(normalize(text), unit) for text, unit in copies}) > 1:
            unconfirmed.add("duration")
        elif copies[0][0] not in ("", "UNSTATED"):
            text, unit = copies[0]
            durations.setdefault((normalize(text), unit), text)
            quotes.setdefault("duration", line)
        per_reading: list[dict[tuple[object, ...], AmountStated]] = []
        for v in yes:
            kept: dict[tuple[object, ...], AmountStated] = {}
            for stated in v.amounts:
                if on_line(stated.amount, line):
                    kept[_amount_key(stated)] = stated
                else:
                    off_line += 1
            per_reading.append(kept)
        if len({frozenset(kept) for kept in per_reading}) > 1:
            split_covers |= {key[0] for kept in per_reading for key in kept}  # type: ignore[misc]
            continue
        for key, stated in per_reading[0].items():
            by_covers.setdefault(stated.covers, {})[key] = _decided_amount(stated, line)
    decided: list[DecidedAmount] = []
    for covers, found in by_covers.items():
        if covers in split_covers or len(found) > 1:
            unconfirmed.add("amount")
            continue
        (amount,) = found.values()
        decided.append(amount)
        quotes[f"amount:{covers}"] = amount.quote
    if split_covers - set(by_covers):
        unconfirmed.add("amount")
    chosen: dict[str, str] = {}
    for name, found in labels.items():
        if name in unconfirmed or len(found) > 1:
            unconfirmed.add(name)
            quotes.pop(name, None)
            chosen[name] = "UNSTATED"
        else:
            chosen[name] = next(iter(found), "UNSTATED")
    duration, months = "UNSTATED", None
    if "duration" in unconfirmed or len(durations) > 1:
        unconfirmed.add("duration")
        quotes.pop("duration", None)
    elif durations:
        [((_, unit), duration)] = durations.items()
        months = duration_months(duration, unit)
    return _Card(
        amounts=tuple(sorted(decided, key=lambda a: (a.covers, a.amount_text))),
        duration=duration,
        duration_months=months,
        timing=chosen["timing"],
        cycle=chosen["cycle"],
        quotes=tuple(sorted(quotes.items())),
        unconfirmed=frozenset(unconfirmed),
        off_line=off_line,
    )
```

The one `type: ignore[misc]` is for `key[0]` on a `tuple[object, ...]` feeding a `set[str]`; if mypy accepts it without the ignore, drop the comment rather than keep a dead one.

- [ ] **Step 5: Call it from `_decide`**

In `_decide`, directly after `disputed |= _differing(labels)`:

```python
    card = _card(members)
    # Card fields are details (spec 8.6): a split names the field and blanks
    # it, and never reaches the existence set, so `agreement` below is decided
    # exactly as before.
    disputed |= card.unconfirmed
```

and in the returned `FundingDecision(...)`, after `disputed_conditions=...`:

```python
            amounts=card.amounts,
            duration=card.duration,
            duration_months=card.duration_months,
            timing=card.timing,
            cycle=card.cycle,
            card_quotes=card.quotes,
            card_off_line=card.off_line,
```

`unconfirmed` needs no edit: it is already `disputed - _EXISTENCE` on an `AGREED` award, so the card names reach it and nowhere else.

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_funding_judge_card.py tests/research/test_funding_judge.py tests/research/test_funding_reader.py tests/research/test_pipeline_funding.py -v`
Expected: PASS — the existing judge and writer tests are unchanged, because a verdict with no card fields yields an empty card and no new `disputed` name.

- [ ] **Step 7: Checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
git add apps/research/funding_judge.py tests/research/test_funding_judge_card.py
git commit -m "feat(research): agree the card one field at a time; a split is unconfirmed, never hidden"
```

---

### Task 4: The columns the card needs

Shared catalogue: an award's amount, duration and coverage are the same fact for every agency. No new table, so no new policy — `shared_catalog_select` and `catalog_ingestion_write` are table-level and cover an added column — **and that is verified through a `NOBYPASSRLS` role below, not assumed.**

**Files:**
- Modify: `apps/funding/models.py`
- Create: the generated migration `apps/funding/migrations/<leaf+1>_award_card_fields.py`
- Test: `tests/funding/test_award_card_columns.py`, `tests/research/test_award_card_rls.py`

**Interfaces:**
- Produces: `FundingOpportunity.{tuition, living, timing, cycle, duration_text, duration_months, card_quotes}`; `FundingBenefit.{amount_text, amount_bound, amount_quote}`; constraints `funding_opportunity_coverage_valid`, `_timing_valid`, `_cycle_valid`, `_duration_months_range`, `funding_benefit_amount_bound_valid`

- [ ] **Step 1: Write the failing tests**

```python
# tests/funding/test_award_card_columns.py
"""The card's columns and the closed values the database holds them to."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from apps.funding.models import FundingBenefit, FundingOpportunity

pytestmark = pytest.mark.django_db


def _opportunity(**fields):
    return FundingOpportunity.objects.create(
        canonical_key=f"read:{uuid4()}", name="Award", family="UNIVERSITY_WIDE",
        scope_type="GLOBAL", **fields,
    )


def test_a_row_holds_every_card_field():
    row = _opportunity(
        tuition="FULL", living="PARTIAL", timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
        duration_text="24 months", duration_months=24,
        card_quotes={"timing": "Decided before arrival."},
    )
    row.refresh_from_db()
    assert (row.tuition, row.timing, row.duration_months) == ("FULL", "PRE_ARRIVAL", 24)
    assert row.card_quotes == {"timing": "Decided before arrival."}


def test_a_row_no_reader_wrote_leaves_every_card_field_blank():
    row = _opportunity()
    assert (row.tuition, row.timing, row.cycle, row.duration_text) == ("", "", "", "")
    assert row.duration_months is None and row.card_quotes == {}


@pytest.mark.parametrize(
    "fields",
    [
        {"tuition": "HALF"}, {"living": "ALL"}, {"timing": "SOON"}, {"cycle": "BIENNIAL"},
        {"duration_months": 0}, {"duration_months": 121},
    ],
)
def test_the_database_refuses_a_value_outside_the_closed_lists(fields):
    with pytest.raises(IntegrityError), transaction.atomic():
        _opportunity(**fields)


def test_a_benefit_keeps_the_words_its_figure_was_read_from():
    award = _opportunity()
    benefit = FundingBenefit.objects.create(
        opportunity=award, kind="STIPEND", amount=Decimal("1200"), currency="EUR",
        period="MONTHLY", description="x", amount_text="€1,200", amount_bound="EXACT",
        amount_quote="Scholars receive €1,200 per month.",
    )
    benefit.refresh_from_db()
    assert (benefit.amount_text, benefit.amount_bound) == ("€1,200", "EXACT")


def test_an_amount_bound_outside_the_closed_list_is_refused():
    award = _opportunity()
    with pytest.raises(IntegrityError), transaction.atomic():
        FundingBenefit.objects.create(
            opportunity=award, kind="STIPEND", period="MONTHLY", description="x",
            amount_bound="ABOUT",
        )
```

```python
# tests/research/test_award_card_rls.py
"""The card's new columns sit behind the catalogue's own policies.

CLAUDE.md: the test role bypasses RLS, so this runs as a real NOBYPASSRLS role
through `runtime_connection`. The UPDATE carries the negative control
`test_fetch_models_rls.py` uses: the role is GRANTed UPDATE first, so zero rows
touched is the policy's doing, not a missing privilege.
"""

from uuid import uuid4

import pytest
from django.db import connection
from psycopg import sql

from apps.funding.models import FundingOpportunity

pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
def test_the_card_columns_are_readable_with_no_tenant_and_writable_by_nobody_else(
    runtime_connection,
):
    FundingOpportunity.objects.create(
        canonical_key=f"read:{uuid4()}", name="Award", family="UNIVERSITY_WIDE",
        scope_type="GLOBAL", timing="PRE_ARRIVAL", duration_text="24 months",
        duration_months=24,
    )
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT, UPDATE ON TABLE public.funding_fundingopportunity TO {}")
            .format(role)
        )
    with runtime_connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_table_privilege(%s, 'public.funding_fundingopportunity', 'UPDATE')",
            [runtime_connection.info.user],
        )
        assert cursor.fetchone() == (True,), "the grant did not take"
        cursor.execute(
            "SELECT timing, duration_text, duration_months FROM public.funding_fundingopportunity"
        )
        assert cursor.fetchall() == [("PRE_ARRIVAL", "24 months", 24)]
        cursor.execute("UPDATE public.funding_fundingopportunity SET timing = 'ROLLING'")
        assert cursor.rowcount == 0
    assert FundingOpportunity.objects.get().timing == "PRE_ARRIVAL"
```

- [ ] **Step 2: Run to verify they fail**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/funding/test_award_card_columns.py tests/research/test_award_card_rls.py -v`
Expected: FAIL — `TypeError: FundingOpportunity() got unexpected keyword arguments: 'tuition', ...`

- [ ] **Step 3: Add the fields**

In `FundingOpportunity`, after `suspension_quote`:

```python
    # The card's own fields (spec 8.3, 10.4; build item 13), written by
    # apps.research.funding_reader from what the readings agreed a line states.
    # Blank on a row no reader has written since. A value the readings split on
    # is UNSTATED here and named in `unconfirmed`, so a blank and a split are
    # never confused. `tuition`/`living` keep the LEVEL that `_benefit_kinds`
    # reduces to a benefit row -- without them "a full waiver" and "a 10%
    # discount" are the same row, and a waiver's card has no amount to show.
    tuition = models.CharField(max_length=10, blank=True, default="")
    living = models.CharField(max_length=10, blank=True, default="")
    timing = models.CharField(max_length=12, blank=True, default="")
    cycle = models.CharField(max_length=20, blank=True, default="")
    duration_text = models.CharField(max_length=40, blank=True, default="")
    duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Which verbatim line stated each card field: {"timing": "...", "amount:LIVING": "..."}.
    card_quotes = models.JSONField(default=dict, blank=True)
```

and in its `Meta.constraints`, after `funding_opportunity_served_not_suspended`:

```python
            models.CheckConstraint(
                condition=models.Q(tuition__in=("", "NONE", "PARTIAL", "FULL", "UNSTATED"))
                & models.Q(living__in=("", "NONE", "PARTIAL", "FULL", "UNSTATED")),
                name="funding_opportunity_coverage_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    timing__in=("", "PRE_ARRIVAL", "POST_ARRIVAL", "EITHER", "UNSTATED")
                ),
                name="funding_opportunity_timing_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    cycle__in=(
                        "", "ANNUAL_FIXED", "ROLLING", "WITH_ADMISSION_CYCLE", "ONE_OFF",
                        "UNSTATED",
                    )
                ),
                name="funding_opportunity_cycle_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_months__isnull=True)
                | models.Q(duration_months__gte=1, duration_months__lte=120),
                name="funding_opportunity_duration_months_range",
            ),
```

In `FundingBenefit`, after `service_charge_text`:

```python
    #: The figure as the page printed it, the bound it was stated with, and the
    #: line (build item 13). `amount` is set only when code could read one
    #: figure in a confirmed currency from `amount_text`; otherwise the card
    #: shows the text and nothing counts it. Blank on a row no reader wrote.
    amount_text = models.CharField(max_length=40, blank=True, default="")
    amount_bound = models.CharField(max_length=8, blank=True, default="")
    amount_quote = models.CharField(max_length=1_000, blank=True, default="")
```

and in its constraints:

```python
            models.CheckConstraint(
                condition=models.Q(amount_bound__in=("", "EXACT", "UP_TO", "AT_LEAST")),
                name="funding_benefit_amount_bound_valid",
            ),
```

- [ ] **Step 4: Generate the migration**

```bash
ls apps/funding/migrations | sort | tail -4
uv run python manage.py makemigrations funding --name award_card_fields
```

Expected: one new file whose `dependencies` names the leaf you just listed, with ten `AddField` and five `AddConstraint` operations and no `RunSQL`. If `ls` showed two leaves, first run `uv run python manage.py makemigrations funding --merge` and commit that merge with this change.

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/funding/test_award_card_columns.py tests/research/test_award_card_rls.py tests/tenancy/test_database_isolation.py -v`
Expected: PASS

- [ ] **Step 6: Checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
uv run python manage.py makemigrations --check --dry-run
git add apps/funding/models.py apps/funding/migrations/ tests/funding/test_award_card_columns.py tests/research/test_award_card_rls.py
git commit -m "feat(funding): the columns the award card needs, behind the catalogue's policies"
```

---

### Task 5: The writer writes the card, and `card_of` reads a decision as one

**Files:**
- Modify: `apps/research/funding_reader.py`
- Create: `apps/funding/card.py` (the `AwardCard` type the writer's `card_of` returns; `award_card`/`card_fill` land here too, tested in Task 6)
- Test: `tests/research/test_funding_reader.py` (append)

**Interfaces:**
- Consumes: `FundingDecision`'s card fields, `DecidedAmount`
- Produces: the card columns written by both `write_funding_decision` and `write_holder_decision`; one `FundingBenefit` per decided amount; `card_of(decision) -> AwardCard`; in `apps/funding/card.py`: `AmountLine`, `AwardCard`, `award_card`, `card_fill`, `card_values`, `FieldState`, `CARD_FIELDS`

- [ ] **Step 1: Write the failing tests** (append to `tests/research/test_funding_reader.py`)

```python
from decimal import Decimal  # noqa: E402

from apps.funding.card import award_card, card_fill  # noqa: E402
from apps.research.funding_judge import DecidedAmount  # noqa: E402
from apps.research.funding_reader import card_of  # noqa: E402

STIPEND_LINE = "Scholars receive €1,200 per month for 24 months."


def _amount(**overrides):
    fields = dict(
        covers="LIVING", amount_text="€1,200", amount=Decimal("1200"), currency="EUR",
        period="MONTHLY", bound="EXACT", quote=STIPEND_LINE,
    )
    fields.update(overrides)
    return DecidedAmount(**fields)  # type: ignore[arg-type]


def test_an_agreed_amount_lands_on_its_benefit_with_its_words(program, snapshot):
    row = _write(
        _decision(living="FULL", quotes=(WAIVER, STIPEND_LINE), amounts=(_amount(),)),
        program, snapshot,
    )
    (stipend,) = FundingBenefit.objects.filter(opportunity=row, kind="STIPEND")
    assert (stipend.amount, stipend.currency, stipend.period) == (Decimal("1200"), "EUR", "MONTHLY")
    assert (stipend.amount_text, stipend.amount_bound, stipend.amount_quote) == (
        "€1,200", "EXACT", STIPEND_LINE,
    )


def test_a_sum_for_no_stated_purpose_gets_a_benefit_of_its_own(program, snapshot):
    row = _write(_decision(amounts=(_amount(
        covers="TOTAL", amount_text="€5,000", amount=Decimal("5000"), period="ONE_OFF",
    ),)), program, snapshot)
    other = FundingBenefit.objects.get(opportunity=row, kind="OTHER")
    assert (other.amount, other.period) == (Decimal("5000"), "ONE_OFF")


def test_two_sums_of_one_kind_are_two_benefits_never_one_overwritten(program, snapshot):
    row = _write(_decision(amounts=(
        _amount(covers="TOTAL", amount_text="€5,000", amount=Decimal("5000"), period="ONE_OFF"),
        _amount(covers="OTHER", amount_text="€300", amount=Decimal("300"), period="ONE_OFF"),
    )), program, snapshot)
    figures = sorted(
        FundingBenefit.objects.filter(opportunity=row, kind="OTHER").values_list("amount", flat=True)
    )
    assert figures == [Decimal("300"), Decimal("5000")]


def test_a_figure_the_arithmetic_cannot_use_keeps_its_words_and_no_number(program, snapshot):
    row = _write(_decision(amounts=(_amount(
        covers="TUITION", amount_text="€500", amount=None, currency=None, period="OTHER",
    ),)), program, snapshot)
    tuition = FundingBenefit.objects.get(opportunity=row, kind="TUITION")
    assert (tuition.amount, tuition.currency, tuition.amount_text) == (None, None, "€500")


def test_the_card_columns_are_written_and_a_reread_replaces_them(program, snapshot):
    row = _write(_decision(
        duration="24 months", duration_months=24, timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
        card_quotes=(("timing", WAIVER),),
    ), program, snapshot)
    assert (row.duration_text, row.duration_months, row.timing, row.cycle) == (
        "24 months", 24, "PRE_ARRIVAL", "ANNUAL_FIXED",
    )
    assert (row.tuition, row.living, row.card_quotes) == ("PARTIAL", "NONE", {"timing": WAIVER})
    again = _write(_decision(), program, snapshot)
    assert (again.duration_text, again.duration_months, again.timing) == ("", None, "UNSTATED")


def test_a_holder_award_writes_its_card_too(snapshot, funder_lead):
    from apps.research.funding_reader import write_holder_decision

    quote = "Das Stipendium beträgt 992 Euro monatlich."
    row = write_holder_decision(
        _holder_decision(amounts=(_amount(amount_text="992 Euro", amount=Decimal("992"),
                                          quote=quote),)),
        holder_domain="foundation.example.test", holder_name="Foundation", lead=funder_lead,
        source=snapshot.source, snapshot=snapshot,
    )
    stipend = FundingBenefit.objects.get(opportunity=row, kind="STIPEND")
    assert (stipend.amount, stipend.amount_text) == (Decimal("992"), "992 Euro")


def test_the_card_of_a_decision_and_of_its_written_row_are_the_same_card(program, snapshot):
    decision = _decision(
        living="FULL", quotes=(WAIVER, STIPEND_LINE), amounts=(_amount(),),
        duration="24 months", duration_months=24, timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
        card_quotes=(("timing", WAIVER),),
    )
    row = _write(decision, program, snapshot)
    written = award_card(row, list(FundingBenefit.objects.filter(opportunity=row)))
    assert written.amounts == card_of(decision).amounts
    assert card_fill(written) == card_fill(card_of(decision))
```

- [ ] **Step 2: Run to verify they fail**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_funding_reader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.funding.card'`

- [ ] **Step 3: Write `apps/funding/card.py`**

```python
# apps/funding/card.py
"""The award card's own fields -- what the reader owes the pack (spec 10.4).

Two constructors and one judgement. `award_card` reads a catalogue row and its
benefits; `apps.research.funding_reader.card_of` builds the same value from a
decision nothing has written yet, so the 58-host measurement and the pack count
a card the same way. `card_fill` is the judgement, per field:

- FILLED -- the page states it and the readings agreed;
- UNCONFIRMED -- the readings split; shown beside its quote, never filtered on;
- UNSTATED -- read, and the page says nothing;
- NOT_READ -- no reader for that field has run on this row;
- NOT_APPLICABLE -- a contact on an award that comes with the place.

Pure, like facts.py: rows in, a value out, no query. Rendering the card is the
presentation layer's (CLAUDE.md, "Frontend and design"); this is the data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from apps.funding.models import FundingBenefit, FundingOpportunity

FieldState = Literal["FILLED", "UNCONFIRMED", "UNSTATED", "NOT_READ", "NOT_APPLICABLE"]
CARD_FIELDS = ("amount", "duration", "timing", "cycle", "required_documents", "contact")
#: The one route on which nobody is written to: the money comes with the place.
_NO_CONTACT_ROUTE = "AUTOMATIC_ON_ADMISSION"


@dataclass(frozen=True)
class AmountLine:
    kind: str
    amount_text: str
    amount: Decimal | None
    currency: str | None
    period: str
    bound: str
    quote: str


@dataclass(frozen=True)
class AwardCard:
    route: str
    tuition: str
    living: str
    amounts: tuple[AmountLine, ...]
    duration_text: str
    duration_months: int | None
    timing: str
    cycle: str
    unconfirmed: tuple[str, ...]
    quotes: tuple[tuple[str, str], ...] = ()
    #: Part B of the build-item-13 plan fills these; until then NOT_READ.
    required_documents: tuple[str, ...] = ()
    documents_read: bool = False
    contact_email: str = ""
    contact_url: str = ""
    contact_quote: str = ""
    contact_read: bool = False


def _split(value: str) -> tuple[str, ...]:
    return tuple(part for part in value.split(";") if part)


def amount_lines(benefits: Sequence[FundingBenefit]) -> tuple[AmountLine, ...]:
    """The benefits a reader wrote a figure for, in a stable order."""
    return tuple(sorted(
        (
            AmountLine(
                kind=benefit.kind, amount_text=benefit.amount_text, amount=benefit.amount,
                currency=benefit.currency, period=benefit.period,
                bound=benefit.amount_bound, quote=benefit.amount_quote,
            )
            for benefit in benefits
            if benefit.amount_text
        ),
        key=lambda line: (line.kind, line.amount_text),
    ))


def award_card(award: FundingOpportunity, benefits: Sequence[FundingBenefit]) -> AwardCard:
    """The card a catalogue row carries. `benefits` are the row's own, fetched by the caller."""
    return AwardCard(
        route=award.route,
        tuition=award.tuition or "UNSTATED",
        living=award.living or "UNSTATED",
        amounts=amount_lines(benefits),
        duration_text=award.duration_text,
        duration_months=award.duration_months,
        timing=award.timing or "UNSTATED",
        cycle=award.cycle or "UNSTATED",
        unconfirmed=_split(award.unconfirmed),
        quotes=tuple(sorted(award.card_quotes.items())),
    )


def _state(name: str, filled: bool, card: AwardCard) -> FieldState:
    """A value written wins over a split elsewhere: a blanked value is never written."""
    if filled:
        return "FILLED"
    return "UNCONFIRMED" if name in card.unconfirmed else "UNSTATED"


def card_fill(card: AwardCard) -> dict[str, FieldState]:
    """What the card says about each of its fields.

    A FULL coverage level is a stated amount -- "full tuition" is what the page
    printed, and it is the amount a student reads -- while PARTIAL with no
    figure is not: "a partial waiver" tells nobody how much.
    """
    contact: FieldState
    if card.route == _NO_CONTACT_ROUTE:
        contact = "NOT_APPLICABLE"
    elif not card.contact_read:
        contact = "NOT_READ"
    else:
        contact = _state("contact", bool(card.contact_email or card.contact_url), card)
    return {
        "amount": _state(
            "amount", bool(card.amounts) or "FULL" in (card.tuition, card.living), card
        ),
        "duration": _state("duration", bool(card.duration_text), card),
        "timing": _state("timing", card.timing != "UNSTATED", card),
        "cycle": _state("cycle", card.cycle != "UNSTATED", card),
        "required_documents": (
            _state("required_documents", bool(card.required_documents), card)
            if card.documents_read
            else "NOT_READ"
        ),
        "contact": contact,
    }


def card_values(card: AwardCard) -> dict[str, str]:
    """Each filled field as one line a person checks against the page (Task 12)."""
    amounts = "; ".join(
        f"{line.amount_text} [{line.kind} {line.period} {line.bound}"
        + (f" = {line.amount} {line.currency}]" if line.amount is not None else ", no number]")
        for line in card.amounts
    )
    if not amounts and "FULL" in (card.tuition, card.living):
        amounts = f"tuition {card.tuition}, living {card.living}"
    return {
        "amount": amounts,
        "duration": card.duration_text
        + (f" = {card.duration_months} months" if card.duration_months else ""),
        "timing": card.timing,
        "cycle": card.cycle,
        "required_documents": " | ".join(card.required_documents),
        "contact": card.contact_email or card.contact_url,
    }
```

- [ ] **Step 4: Write the card from the writer**

In `apps/research/funding_reader.py`, extend the model import with `Period`, add `from apps.funding.card import AmountLine, AwardCard`, and extend `from .funding_judge import FundingDecision` to `from .funding_judge import DecidedAmount, FundingDecision`. Then, after `_OTHER_BENEFIT`:

```python
#: A stated sum's purpose -> the benefit row that carries it. LIVING is the
#: one purpose whose kind depends on the award (_benefit_kinds says the same).
_BENEFIT_FOR = {
    "TUITION": "TUITION", "TRAVEL": "TRAVEL", "HOUSING": "HOUSING",
    "INSURANCE": "INSURANCE", "RELOCATION": "RELOCATION", "TOTAL": "OTHER", "OTHER": "OTHER",
}


def _benefit_kind(covers: str, decision: FundingDecision) -> str:
    if covers == "LIVING":
        return "ASSISTANTSHIP" if decision.kind == "I3_STIPEND_OR_ASSISTANTSHIP" else "STIPEND"
    return _BENEFIT_FOR[covers]


def _period_of(amount: DecidedAmount) -> str:
    """The Period a figure is stored under. OTHER has none, and then `amount`
    is already None, so the stored FULL_PROGRAM describes no number."""
    return amount.period if amount.period in Period.values else Period.FULL_PROGRAM


def _card_columns(decision: FundingDecision) -> dict[str, object]:
    return {
        "tuition": decision.tuition,
        "living": decision.living,
        "timing": decision.timing,
        "cycle": decision.cycle,
        "duration_text": "" if decision.duration == "UNSTATED" else decision.duration[:40],
        "duration_months": decision.duration_months,
        "card_quotes": {field: quote[:1_000] for field, quote in decision.card_quotes},
    }


def card_of(decision: FundingDecision) -> AwardCard:
    """The card a decision would write, before it is written -- for measuring.

    Task 5's test holds it to `award_card` of the written row, so a tally
    computed from decisions counts exactly what the pack will read.
    """
    return AwardCard(
        route=decision.route,
        tuition=decision.tuition,
        living=decision.living,
        amounts=tuple(sorted(
            (
                AmountLine(
                    kind=_benefit_kind(a.covers, decision), amount_text=a.amount_text[:40],
                    amount=a.amount, currency=a.currency, period=_period_of(a),
                    bound=a.bound, quote=a.quote[:1_000],
                )
                for a in decision.amounts
            ),
            key=lambda line: (line.kind, line.amount_text),
        )),
        duration_text="" if decision.duration == "UNSTATED" else decision.duration[:40],
        duration_months=decision.duration_months,
        timing=decision.timing,
        cycle=decision.cycle,
        unconfirmed=decision.unconfirmed,
        quotes=tuple(sorted((field, quote[:1_000]) for field, quote in decision.card_quotes)),
    )
```

In both `update_or_create(... defaults={...})` calls — `write_funding_decision` and `write_holder_decision` — add `**_card_columns(decision),` directly after `**_suspension(decision),`.

In `_write_rows`, replace the benefit loop with:

```python
    created: list[FundingBenefit] = []
    for kind in _benefit_kinds(decision):
        benefit = FundingBenefit.objects.create(
            opportunity=opportunity,
            kind=kind,
            period="FULL_PROGRAM",
            description=decision.quotes[0] if decision.quotes else "",
            repayable_share=Decimal("1") if decision.money_form == "LOAN" else Decimal("0"),
        )
        for claim in claims:
            FundingBenefitEvidenceClaim.objects.get_or_create(benefit=benefit, evidence_claim=claim)
        created.append(benefit)
    for amount in decision.amounts:
        _write_amount(opportunity, decision, amount, benefits=created, claims=claims)
```

and add, after `_write_rows`:

```python
def _write_amount(
    opportunity: FundingOpportunity,
    decision: FundingDecision,
    amount: DecidedAmount,
    *,
    benefits: list[FundingBenefit],
    claims: list[OfficialEvidenceClaim],
) -> None:
    """One decided sum onto its benefit: the level's row when it has no figure
    yet, a row of its own otherwise -- two sums of one kind are two rows, never
    one overwritten."""
    kind = _benefit_kind(amount.covers, decision)
    benefit = next((b for b in benefits if b.kind == kind and not b.amount_text), None)
    if benefit is None:
        benefit = FundingBenefit.objects.create(
            opportunity=opportunity,
            kind=kind,
            period="FULL_PROGRAM",
            description=amount.quote[:2_000],
            repayable_share=Decimal("1") if decision.money_form == "LOAN" else Decimal("0"),
        )
        for claim in claims:
            FundingBenefitEvidenceClaim.objects.get_or_create(benefit=benefit, evidence_claim=claim)
        benefits.append(benefit)
    benefit.amount = amount.amount
    benefit.currency = amount.currency
    benefit.period = _period_of(amount)
    benefit.amount_text = amount.amount_text[:40]
    benefit.amount_bound = amount.bound
    benefit.amount_quote = amount.quote[:1_000]
    # update_fields makes a write the runtime role's policy silently refused
    # raise ("did not affect any rows") instead of reporting success.
    benefit.save(update_fields=[
        "amount", "currency", "period", "amount_text", "amount_bound", "amount_quote",
    ])
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_funding_reader.py tests/research/test_pipeline_funding.py tests/research/test_funding_review.py -v`
Expected: PASS

- [ ] **Step 6: Checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
git add apps/funding/card.py apps/research/funding_reader.py tests/research/test_funding_reader.py
git commit -m "feat(research): the writer stores the card; card_of reads a decision as one"
```

---

### Task 6: The facts count only a figure the page stated as a total, and carry the card

**This task must land in the same part as Task 5**, before any pack reads a written figure: `affordability._normalize_to_program_total` multiplies a monthly or annual figure by the *programme's* months, and a read figure is the award's.

**Files:**
- Modify: `apps/funding/facts.py`, `apps/funding/evaluation.py`, `apps/funding/pack.py`, `apps/research/spine.py`
- Test: `tests/funding/test_facts.py` (append), `tests/funding/test_card.py` (new), `tests/funding/test_pack_awards.py` (append)

**Interfaces:**
- Consumes: `apps.funding.card.{award_card, AwardCard}`, `apps.funding.fx.round_money`
- Produces: `program_facts(..., durations=None)`; `AwardCandidateFacts.card`; `PackedAward.card`

- [ ] **Step 1: Write the failing tests**

```python
# tests/funding/test_card.py
"""What a card says about each of its fields. Pure; no database."""

from decimal import Decimal

from apps.funding.card import AmountLine, AwardCard, card_fill, card_values


def _card(**overrides):
    fields = dict(
        route="STUDENT_APPLIES_SEPARATELY", tuition="UNSTATED", living="UNSTATED", amounts=(),
        duration_text="", duration_months=None, timing="UNSTATED", cycle="UNSTATED",
        unconfirmed=(),
    )
    fields.update(overrides)
    return AwardCard(**fields)  # type: ignore[arg-type]


STIPEND = AmountLine(
    kind="STIPEND", amount_text="€1,200", amount=Decimal("1200"), currency="EUR",
    period="MONTHLY", bound="EXACT", quote="Scholars receive €1,200 per month.",
)


def test_an_empty_card_is_unstated_and_not_read_never_filled():
    assert card_fill(_card()) == {
        "amount": "UNSTATED", "duration": "UNSTATED", "timing": "UNSTATED",
        "cycle": "UNSTATED", "required_documents": "NOT_READ", "contact": "NOT_READ",
    }


def test_full_coverage_is_a_stated_amount_and_partial_is_not():
    assert card_fill(_card(tuition="FULL"))["amount"] == "FILLED"
    assert card_fill(_card(tuition="PARTIAL"))["amount"] == "UNSTATED"


def test_a_split_field_is_unconfirmed_not_unstated():
    assert card_fill(_card(unconfirmed=("timing",)))["timing"] == "UNCONFIRMED"


def test_a_written_amount_is_filled_even_beside_an_unconfirmed_one():
    assert card_fill(_card(amounts=(STIPEND,), unconfirmed=("amount",)))["amount"] == "FILLED"


def test_an_award_that_comes_with_the_place_needs_no_contact():
    assert card_fill(_card(route="AUTOMATIC_ON_ADMISSION"))["contact"] == "NOT_APPLICABLE"


def test_a_value_shows_the_printed_words_beside_the_number():
    values = card_values(_card(amounts=(STIPEND,), duration_text="24 months", duration_months=24))
    assert values["amount"] == "€1,200 [STIPEND MONTHLY EXACT = 1200 EUR]"
    assert values["duration"] == "24 months = 24 months"
```

Append to `tests/funding/test_facts.py`:

```python
from apps.funding.card import card_fill  # noqa: E402


def _programme_award(program, *, duration_months=None):
    return FundingOpportunity.objects.create(
        canonical_key=f"read:program:{uuid4()}", name="Programme stipend",
        family="DEPARTMENT_OR_PROGRAM", scope_type="PROGRAM", program=program,
        agreement="AGREED", served=True, route="AUTOMATIC_ON_ADMISSION",
        duration_months=duration_months,
    )


def _read_benefit(opportunity, **fields):
    values = dict(
        kind="STIPEND", amount=Decimal("1000"), currency="EUR", period="MONTHLY",
        description="x", amount_text="€1,000", amount_bound="EXACT",
        amount_quote="€1,000 a month.",
    )
    values.update(fields)
    return FundingBenefit.objects.create(opportunity=opportunity, **values)


def _one_benefit(program, profile, benefit, durations):
    facts = program_facts(
        program, profile.intended_intake, costs=(), benefits=(benefit,), rules=(),
        routes={benefit.opportunity_id: "AUTOMATIC_ON_ADMISSION"}, durations=durations,
    )
    (fact,) = facts.benefits
    return fact


def test_a_monthly_figure_counts_only_for_the_months_the_page_states(program, profile):
    award = _programme_award(program, duration_months=12)
    fact = _one_benefit(program, profile, _read_benefit(award), {award.id: 12})
    assert (fact.amount, fact.currency, fact.period) == (Decimal("12000.00"), "EUR", "FULL_PROGRAM")


def test_an_award_longer_than_the_programme_counts_for_the_programme(program, profile):
    award = _programme_award(program, duration_months=36)
    fact = _one_benefit(program, profile, _read_benefit(award), {award.id: 36})
    assert fact.amount == Decimal("24000.00")   # the programme runs 24 months


def test_a_monthly_figure_with_no_stated_duration_is_no_coverage(program, profile):
    """Not the programme's length: that would count a one-year stipend twice
    on a two-year degree, which is exactly the overstatement this closes."""
    award = _programme_award(program)
    fact = _one_benefit(program, profile, _read_benefit(award), {award.id: None})
    assert (fact.amount, fact.currency) == (None, None)


def test_an_up_to_figure_is_shown_but_never_counted(program, profile):
    award = _programme_award(program)
    benefit = _read_benefit(award, period="ONE_OFF", amount_bound="UP_TO")
    assert _one_benefit(program, profile, benefit, {}).amount is None


def test_a_row_no_reader_wrote_passes_through_unchanged(program, profile):
    award = _programme_award(program)
    benefit = _read_benefit(award, amount_text="", amount_bound="", amount_quote="")
    fact = _one_benefit(program, profile, benefit, {})
    assert (fact.amount, fact.period) == (Decimal("1000"), "MONTHLY")


def test_an_award_fact_carries_its_card(award):
    award.duration_text, award.duration_months, award.timing = "12 months", 12, "PRE_ARRIVAL"
    benefit = _read_benefit(award, period="ONE_OFF", amount_text="€5,000", amount=Decimal("5000"))
    facts = award_facts(award, benefits=(benefit,), rules=())
    assert facts.card is not None and facts.card.duration_months == 12
    assert card_fill(facts.card)["amount"] == "FILLED"
```

Append to `tests/funding/test_pack_awards.py`:

```python
from decimal import Decimal  # noqa: E402

from apps.funding.card import AmountLine, AwardCard  # noqa: E402


def test_a_packed_award_carries_its_card(profile):
    card = AwardCard(
        route="STUDENT_APPLIES_SEPARATELY", tuition="UNSTATED", living="FULL",
        amounts=(AmountLine("STIPEND", "€1,200", Decimal("1200"), "EUR", "MONTHLY", "EXACT", "q"),),
        duration_text="24 months", duration_months=24, timing="PRE_ARRIVAL",
        cycle="ANNUAL_FIXED", unconfirmed=(),
    )
    pack = build_pack(profile, [_candidate()], EUR_RATES, awards=[_award(card=card)], today=TODAY)
    (packed,) = pack.awards
    assert packed.card == card
```

- [ ] **Step 2: Run to verify they fail**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/funding/test_card.py tests/funding/test_facts.py tests/funding/test_pack_awards.py -v`
Expected: `test_card.py` PASSES (Task 5 wrote the module); the facts tests FAIL with `TypeError: program_facts() got an unexpected keyword argument 'durations'`; the pack test FAILS with `TypeError: ... unexpected keyword argument 'card'`.

- [ ] **Step 3: The facts**

In `apps/funding/facts.py`, add `from apps.funding.card import award_card` and `from apps.funding.fx import round_money`, then replace `_benefit_facts` with:

```python
def _counted(
    benefit: FundingBenefit, *, award_months: int | None, programme_months: int | None
) -> tuple[Decimal | None, str | None, str]:
    """(amount, currency, period) as the arithmetic may use them.

    A row no reader wrote (`amount_text` blank) passes through unchanged. A
    read figure counts only when the page stated it as the amount -- EXACT,
    never "up to" -- and a monthly or annual one only over a duration the
    page stated: it becomes a programme total over min(award, programme)
    months. `affordability` would otherwise multiply it by the PROGRAMME's
    length, and a one-year stipend on a two-year degree would count twice.
    """
    if not benefit.amount_text or benefit.amount is None:
        return benefit.amount, benefit.currency or None, benefit.period
    if benefit.amount_bound != "EXACT":
        return None, None, benefit.period
    if benefit.period not in ("MONTHLY", "ANNUAL"):
        return benefit.amount, benefit.currency, benefit.period
    if award_months is None or programme_months is None:
        return None, None, benefit.period
    per_month = benefit.amount if benefit.period == "MONTHLY" else benefit.amount / Decimal(12)
    total = round_money(per_month * Decimal(min(award_months, programme_months)))
    return total, benefit.currency, "FULL_PROGRAM"


def _benefit_facts(
    benefits: Sequence[FundingBenefit],
    routes: Mapping[object, str] | None = None,
    *,
    durations: Mapping[object, int | None] | None = None,
    programme_months: int | None = None,
) -> tuple[BenefitFact, ...]:
    """`routes` is opportunity id -> published route, for the programme side;
    `durations` is opportunity id -> the months the award's page states.

    Omitted, every benefit is ORDINARY -- an award's own benefits describe the
    award the student is applying FOR, so there is no second route to qualify
    them by -- and no read periodic figure is totalled, because there is no
    programme to total it over.
    """
    facts: list[BenefitFact] = []
    for benefit in benefits:
        amount, currency, period = _counted(
            benefit,
            award_months=(durations or {}).get(benefit.opportunity_id),
            programme_months=programme_months,
        )
        facts.append(
            BenefitFact(
                id=str(benefit.id),
                kind=cast(Any, benefit.kind),
                amount=amount,
                currency=currency,
                period=cast(Any, period),
                scope_type="GLOBAL",
                accessibility=(
                    "ORDINARY"
                    if routes is None or routes.get(benefit.opportunity_id) == GUARANTEED_ROUTE
                    else "CAPACITY_LIMITED"
                ),
                repayable_share=benefit.repayable_share,
            )
        )
    return tuple(facts)
```

In `award_facts`, add `card=award_card(award, benefits),` after `coverage_is_unstated=not benefits,`.

`program_facts` gains a keyword-only parameter after `routes`:

```python
    durations: Mapping[object, int | None] | None = None,
```

and its `benefits=` line becomes:

```python
        benefits=_benefit_facts(
            benefits, routes, durations=durations, programme_months=program.duration_months
        ),
```

- [ ] **Step 4: Carry the card to the pack**

In `apps/funding/evaluation.py`, extend the `TYPE_CHECKING` block with `from apps.funding.card import AwardCard`, and add as the last field of `AwardCandidateFacts` (after `coverage_is_unstated`):

```python
    #: The card's own fields (spec 10.4). None only for a fact built by hand in
    #: a test; award_facts always sets it.
    card: AwardCard | None = None
```

In `apps/funding/pack.py`, add the same `TYPE_CHECKING` import and, as the last field of `PackedAward`:

```python
    card: AwardCard | None = None
```

and in `build_pack`'s `PackedAward(...)`, add `card=award.card,` after `unconfirmed=award.unconfirmed,`.

- [ ] **Step 5: The spine passes each award's duration**

In `apps/research/spine.py`, in the `FundingOpportunityProgram` loop, add `"opportunity__duration_months"` to `values_list`, unpack it, and record it:

```python
    durations: dict[object, int | None] = {}
    for program_id, opportunity_id, route, months in FundingOpportunityProgram.objects.filter(
        # ... the filter is unchanged ...
    ).values_list(
        "program_id", "opportunity_id", "opportunity__route", "opportunity__duration_months"
    ):
        attached_by_program.setdefault(program_id, []).append(opportunity_id)
        routes[opportunity_id] = route
        durations[opportunity_id] = months
```

(declare `durations` beside `routes`), and pass `durations=durations,` to `program_facts` after `routes=routes,`.

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/funding tests/research/test_funding_reader.py -v`
Expected: PASS, including `tests/funding/test_spine.py` and `test_affordability.py` unchanged.

- [ ] **Step 7: Checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
git add apps/funding/facts.py apps/funding/evaluation.py apps/funding/pack.py apps/research/spine.py tests/funding/
git commit -m "feat(funding): count a read figure only as the page stated it, and carry the card to the pack"
```

---

### Task 7: The instrument — card tallies, the hand-check sample, and one live reading

The gate (Task 12) needs three things this task builds: the 58-host command printing cards filled, a file of every served card's values with their quotes, and a scorer for the hand check. Plus one `live` test that three real readings copy a figure off a real-shaped line.

**Files:**
- Modify: `apps/research/management/commands/funding_yield.py`
- Create: `apps/research/management/commands/card_check.py`
- Test: `tests/research/test_funding_yield.py` (append), `tests/research/test_card_check.py` (new), `tests/research/test_funding_judge_card.py` (append the live test)

**Interfaces:**
- Produces: `Tally.cards: Counter[str]` (`"<field>=<state>"` over served decisions), `Tally.card_off_line`, `Tally.card_rows`; `funding_yield --cards-csv PATH`; `card_check --sample CARDS.csv --count N --seed S --out CHECK.csv` and `card_check --score CHECK.csv`

- [ ] **Step 1: Write the failing tests**

Append to `tests/research/test_funding_yield.py`:

```python
from decimal import Decimal  # noqa: E402

from apps.research.funding_judge import DecidedAmount, FundingDecision, FundingReadResult  # noqa: E402
from apps.research.management.commands.funding_yield import Tally  # noqa: E402


def _served(**card):
    fields = dict(
        kind="I2_PROGRAMME_ATTACHED", scope="PROGRAM", offered="YES", internationals_included="YES",
        nationality_shape="OPEN", route="STUDENT_APPLIES_SEPARATELY", money_form="GRANT",
        holder="INSTITUTION", tuition="UNSTATED", living="FULL", extras=(), obligation=(),
        agreement="AGREED", quotes=("Scholars receive €1,200 per month.",), name="Stipend",
        disputed=(),
    )
    fields.update(card)
    return FundingDecision(**fields)  # type: ignore[arg-type]


def test_the_tally_counts_each_served_cards_fields_and_the_invented_copies():
    amount = DecidedAmount("LIVING", "€1,200", Decimal("1200"), "EUR", "MONTHLY", "EXACT",
                           "Scholars receive €1,200 per month.")
    tally = Tally()
    tally.record(
        FundingReadResult(decisions=(_served(amounts=(amount,), card_off_line=2),)),
        page_url="https://example.test/funding",
    )
    assert tally.cards["amount=FILLED"] == 1
    assert tally.cards["duration=UNSTATED"] == 1
    assert tally.cards["contact=NOT_READ"] == 1
    assert tally.card_off_line == 2
    assert "cards=" in tally.line() and "off-line=2" in tally.line()
    assert {row["field"] for row in tally.card_rows} >= {"amount", "duration"}
```

```python
# tests/research/test_card_check.py
"""The 30-card hand check: a seeded sample, and a score that fails loudly."""

import csv

import pytest
from django.core.management import CommandError, call_command

_FIELDS = ("page_url", "award", "field", "state", "value", "quote")


def _cards(path, awards):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS)
        writer.writeheader()
        for index in range(awards):
            for field in ("amount", "duration"):
                writer.writerow({
                    "page_url": f"https://h{index}.test/", "award": f"Award {index}",
                    "field": field, "state": "FILLED", "value": "v", "quote": "q",
                })


def _mark(path, verdicts):
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for row, verdict in zip(rows, verdicts, strict=True):
        row["correct"] = verdict
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_the_sample_is_seeded_and_takes_whole_cards(tmp_path):
    cards, one, two = tmp_path / "cards.csv", tmp_path / "a.csv", tmp_path / "b.csv"
    _cards(cards, 50)
    for out in (one, two):
        call_command("card_check", sample=str(cards), count=30, seed=13, out=str(out))
    assert one.read_text() == two.read_text()
    rows = list(csv.DictReader(one.open(encoding="utf-8")))
    assert len({row["award"] for row in rows}) == 30 and len(rows) == 60
    assert all(row["correct"] == "" for row in rows)


def test_the_score_passes_at_ninety_percent_with_no_wrong_amount(tmp_path):
    cards, check = tmp_path / "cards.csv", tmp_path / "check.csv"
    _cards(cards, 10)
    call_command("card_check", sample=str(cards), count=10, seed=1, out=str(check))
    rows = list(csv.DictReader(check.open(encoding="utf-8")))
    _mark(check, ["no" if row["field"] == "duration" and row["award"] == "Award 3" else "yes"
                  for row in rows])
    call_command("card_check", score=str(check))   # 19 of 20, no amount wrong


def test_one_wrong_amount_fails_the_gate_whatever_the_rate(tmp_path):
    cards, check = tmp_path / "cards.csv", tmp_path / "check.csv"
    _cards(cards, 10)
    call_command("card_check", sample=str(cards), count=10, seed=1, out=str(check))
    rows = list(csv.DictReader(check.open(encoding="utf-8")))
    _mark(check, ["no" if row["field"] == "amount" and row["award"] == "Award 3" else "yes"
                  for row in rows])
    with pytest.raises(CommandError, match="wrong amount"):
        call_command("card_check", score=str(check))


def test_an_unmarked_row_fails_the_score(tmp_path):
    cards, check = tmp_path / "cards.csv", tmp_path / "check.csv"
    _cards(cards, 3)
    call_command("card_check", sample=str(cards), count=3, seed=1, out=str(check))
    with pytest.raises(CommandError, match="unmarked"):
        call_command("card_check", score=str(check))
```

Append to `tests/research/test_funding_judge_card.py`:

```python
import os  # noqa: E402


@pytest.mark.live
def test_three_live_readings_copy_a_monthly_stipend_and_its_duration():
    """One real call per family: the figure, the currency and the months all
    come out of code, from copies three readings agreed on."""
    if not (os.environ.get("OPENAI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        pytest.skip("an award is agreed only when two model families agree")
    import anthropic
    from openai import OpenAI

    from apps.research.funding_judge import read_funding

    chunk = (
        Line("Stipendium", ""),
        Line("Das Stipendium beträgt 992 Euro monatlich für 24 Monate.", "Stipendium"),
    )
    read = read_funding(
        OpenAI().responses, anthropic.Anthropic().messages, source_id="live-card", chunks=[chunk]
    )
    (decision,) = read.decisions
    assert decision.agreement == "AGREED"
    (amount,) = decision.amounts
    assert (amount.amount, amount.currency, amount.period) == (Decimal("992"), "EUR", "MONTHLY")
    assert decision.duration_months == 24
```

- [ ] **Step 2: Run to verify they fail**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_funding_yield.py tests/research/test_card_check.py -v`
Expected: FAIL — `TypeError: Tally.record() got an unexpected keyword argument 'page_url'`, and `CommandError: Unknown command: 'card_check'`

- [ ] **Step 3: The tallies**

In `apps/research/management/commands/funding_yield.py`, add `import csv`, `from apps.funding.card import card_fill, card_values` and extend the `funding_reader` import with `card_of`. In `Tally`, after `pointer_names`:

```python
    #: "<field>=<state>" over SERVED decisions only (spec 10.4: discovery is
    #: measured on cards filled, and an unserved row is no card).
    cards: Counter[str] = field(default_factory=Counter)
    #: Copies a reading gave that were not on their line (Task 3).
    card_off_line: int = 0
    #: One row per served card field, for --cards-csv and the hand check.
    card_rows: list[dict[str, str]] = field(default_factory=list)
```

`record` gains `page_url: str = ""` and, inside its decision loop:

```python
            self.card_off_line += decision.card_off_line
```

and in the `if served_by_gate(decision):` branch, after `self.names.append(...)`:

```python
                card = card_of(decision)
                values = card_values(card)
                quotes = dict(card.quotes)
                for name, state in card_fill(card).items():
                    self.cards[f"{name}={state}"] += 1
                    self.card_rows.append({
                        "page_url": page_url, "award": decision.name, "field": name,
                        "state": state, "value": values[name],
                        "quote": next(
                            (q for key, q in quotes.items() if key.split(":")[0] == name), ""
                        ),
                    })
                for condition in decision.conditions:
                    # The same file carries the spec's "zero false eligibility"
                    # half of the 30-card check (8.8).
                    self.card_rows.append({
                        "page_url": page_url, "award": decision.name, "field": "condition",
                        "state": "FILLED",
                        "value": f"{condition.key} {condition.operator} {condition.value} "
                                 f"{condition.unit or ''}".strip(),
                        "quote": condition.quote,
                    })
```

`add` merges the three: `self.cards.update(other.cards)`, `self.card_off_line += other.card_off_line`, `self.card_rows.extend(other.card_rows)`. `line()` appends:

```python
            + (f" cards={dict(sorted(self.cards.items()))}" if self.cards else "")
            + f" off-line={self.card_off_line}"
```

In `_read_page`, the last line becomes:

```python
        tally.record(
            read_funding(parser, claude, source_id=page.final_url, chunks=chunks),
            page_url=page.final_url,
        )
```

In `add_arguments`: `parser.add_argument("--cards-csv", default="")`. In `handle`, keep the `Tally` `_run` returns and, when `options["cards_csv"]` is set, write `totals.card_rows` with `csv.DictWriter(fieldnames=("page_url", "award", "field", "state", "value", "quote"))`.

- [ ] **Step 4: The hand-check command**

```python
# apps/research/management/commands/card_check.py
"""The 30-card hand check (spec 8.8; build item 13's gate). Writes no row.

    card_check --sample cards.csv --count 30 --seed 13 --out check.csv
    card_check --score check.csv

`--sample` takes WHOLE cards -- every filled field of each sampled award --
because the question is "is this card right", not "is this field right".
A person marks each row's `correct` column yes or no against the quote and the
page; `--score` then fails on: any row left unmarked; any wrong `amount` (the
figure a student budgets on); any wrong `condition` (the spec's zero false
eligibility); or overall precision below 90%.
"""

from __future__ import annotations

import csv
import random
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

_PASS = 0.90
_ZERO_TOLERANCE = ("amount", "condition")


class Command(BaseCommand):
    help = "Sample served cards for a hand check, or score a checked sample."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--sample", default="")
        parser.add_argument("--count", type=int, default=30)
        parser.add_argument("--seed", type=int, default=13)
        parser.add_argument("--out", default="")
        parser.add_argument("--score", default="")

    def handle(self, *_args: object, **options: object) -> None:
        if options["sample"]:
            self._sample(
                Path(str(options["sample"])), int(str(options["count"])),
                int(str(options["seed"])), Path(str(options["out"])),
            )
        elif options["score"]:
            self._score(Path(str(options["score"])))
        else:
            raise CommandError("give --sample or --score")

    def _sample(self, source: Path, count: int, seed: int, out: Path) -> None:
        rows = [
            row for row in csv.DictReader(source.open(encoding="utf-8"))
            if row["state"] == "FILLED"
        ]
        cards = sorted({(row["page_url"], row["award"]) for row in rows})
        if len(cards) < count:
            raise CommandError(f"only {len(cards)} filled cards to sample from, asked for {count}")
        chosen = set(random.Random(seed).sample(cards, count))
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[*rows[0], "correct", "note"])
            writer.writeheader()
            for row in rows:
                if (row["page_url"], row["award"]) in chosen:
                    writer.writerow({**row, "correct": "", "note": ""})
        self.stdout.write(f"{count} cards written to {out}; mark `correct` yes or no")

    def _score(self, path: Path) -> None:
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        unmarked = [row for row in rows if row["correct"] not in ("yes", "no")]
        if unmarked:
            raise CommandError(f"{len(unmarked)} unmarked rows; mark every row yes or no")
        wrong = Counter(row["field"] for row in rows if row["correct"] == "no")
        total = Counter(row["field"] for row in rows)
        for name in sorted(total):
            self.stdout.write(f"{name}: {total[name] - wrong[name]}/{total[name]} correct")
        right = sum(total.values()) - sum(wrong.values())
        precision = right / sum(total.values())
        self.stdout.write(f"overall {right}/{sum(total.values())} = {precision:.1%}")
        for name in _ZERO_TOLERANCE:
            if wrong[name]:
                raise CommandError(f"gate FAILED: {wrong[name]} wrong {name} row(s)")
        if precision < _PASS:
            raise CommandError(f"gate FAILED: {precision:.1%} is under {_PASS:.0%}")
        self.stdout.write("gate PASSED")
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_funding_yield.py tests/research/test_card_check.py tests/research/test_funding_judge_card.py -v`
Expected: PASS (the live test is excluded by the default `-m 'not live'`)

- [ ] **Step 6: Checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
git add apps/research/management/commands/ tests/research/test_funding_yield.py tests/research/test_card_check.py tests/research/test_funding_judge_card.py
git commit -m "feat(research): cards-filled tallies, the hand-check sample and its score"
```

**Part A ends here.** Open the PR for Part A alone, and run Task 12's steps 1–3 on it before Part B starts: the fill rates decide whether Part B's two fields are the bottleneck or not.

---

# Part B — waits for the decision layer and the reader plan

**Do not start Part B until all of these are on `master`:** the whole of `docs/superpowers/plans/2026-09-23-decision-layer-and-rule-grammar.md` (`apps/research/decisions.py`: `ask`, `Noul`, `Choice`, `Answer`, `Question`, `DecisionBudget`, `DecisionsUnavailable`, `DecisionBudgetExhausted`, `run_budget`; `DecisionRecord`), and reader-plan Tasks 2 (`apps/research/sentences.py`: `Sentence`, `page_sentences`, `heading_text`), 3 (`normalize` hardened), 6 (`apps/research/page_questions.py::select_sentences`, `Selection`) and 7 (`label_sentences`, `Labelled`, `LABEL_BAR`). Check with:

```bash
git fetch origin master
git grep -n "def ask\|def run_budget" origin/master -- apps/research/decisions.py
git grep -n "def page_sentences\|def select_sentences\|def label_sentences" origin/master -- apps/research/
```

Every name must be found. Where one landed under a different name or signature, use the landed one and record the difference at the top of your PR description; do not add a shim. Then `git merge origin/master` into `claude/award-card` (or branch Part B fresh from master if Part A has merged).

### Task 8: The document table and the contact columns

`FundingRequiredDocument` is **shared catalogue** (the same award asks every agency's students for the same documents) and carries third-party page text, like `ProgramStatement` — so, like it, it is written only from pages `_fund_page` already vouches for (`can_support_claim` and `one_programme_per_site`, or a `HOLDER` page), never from a URL supplied per request.

**Files:**
- Modify: `apps/funding/models.py`, `tests/tenancy/test_database_isolation.py`
- Create: the generated migration `<leaf+1>_award_documents_and_contact.py`, with its RunSQL appended
- Test: `tests/research/test_award_card_rls.py` (append)

**Interfaces:**
- Produces: `FundingRequiredDocument(opportunity, snapshot, text, heading_path, position, requirement, probability, model_version)`; `FundingOpportunity.{contact_email, contact_url, contact_quote, contact_probability, contact_read_at, documents_read_at}`

- [ ] **Step 1: Write the failing test** (append to `tests/research/test_award_card_rls.py`)

```python
import psycopg  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.funding.models import (  # noqa: E402
    FundingRequiredDocument,
    OfficialSource,
    OfficialSourceSnapshot,
)


@pytest.mark.django_db(transaction=True)
def test_a_required_document_is_shared_catalogue_under_a_real_policy(runtime_connection):
    award = FundingOpportunity.objects.create(
        canonical_key=f"read:{uuid4()}", name="Award", family="UNIVERSITY_WIDE",
        scope_type="GLOBAL",
    )
    source = OfficialSource.objects.create(
        canonical_url=f"https://award.example.test/{uuid4()}", publisher="award.example.test",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, sha256="a" * 64, s3_key="k", s3_version_id="v", byte_size=10,
        final_url=source.canonical_url, redirect_chain=[], admissions_cycle="2027",
        retrieved_at=timezone.now(),
    )
    FundingRequiredDocument.objects.create(
        opportunity=award, snapshot=snapshot, text="Transcript of records.",
        heading_path="Scholarship › Documents", position=4, requirement="REQUIRED",
        probability=0.93, model_version="jev-1.13.0",
    )
    table = "funding_fundingrequireddocument"
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}").format(
                sql.Identifier("public", table), role
            )
        )
    with runtime_connection.cursor() as cursor:
        cursor.execute(f"SELECT text FROM public.{table}")
        assert cursor.fetchall() == [("Transcript of records.",)]
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(
                f"INSERT INTO public.{table} (id, opportunity_id, snapshot_id, text, "
                "heading_path, position, requirement, probability, model_version) "
                "VALUES (gen_random_uuid(), %s, %s, 'Injected.', '', 0, 'REQUIRED', 1, 'x')",
                [award.id, snapshot.id],
            )
        # The grant above is the control: the same SQLSTATE without it would
        # prove nothing about the policy (test_fetch_models_rls.py).
        assert "row-level security policy" in str(refused.value)
    with runtime_connection.cursor() as cursor:
        cursor.execute(f"UPDATE public.{table} SET text = 'x'")
        assert cursor.rowcount == 0
        cursor.execute(f"DELETE FROM public.{table}")
        assert cursor.rowcount == 0
    assert FundingRequiredDocument.objects.count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_award_card_rls.py -v`
Expected: FAIL — `ImportError: cannot import name 'FundingRequiredDocument'`

- [ ] **Step 3: The model and the columns**

In `FundingOpportunity`, after `card_quotes`:

```python
    #: Whom to write to (spec 8.3, 9.2; decision-log row 39): an OFFICE address
    #: or contact page on the holder's own registrable domain, never a named
    #: person's address -- that is personal data about someone who is not our
    #: user. Read only where the route is not AUTOMATIC_ON_ADMISSION.
    #: `contact_read_at` is what tells "no contact printed" from "never read".
    contact_email = models.CharField(max_length=254, blank=True, default="")
    contact_url = models.URLField(max_length=2048, blank=True, default="")
    contact_quote = models.CharField(max_length=1_000, blank=True, default="")
    contact_probability = models.FloatField(null=True, blank=True)
    contact_read_at = models.DateTimeField(null=True, blank=True)
    documents_read_at = models.DateTimeField(null=True, blank=True)
```

with the constraint:

```python
            models.CheckConstraint(
                condition=models.Q(contact_email="") | models.Q(contact_email__contains="@"),
                name="funding_opportunity_contact_email_shape",
            ),
```

After `FundingBenefit`:

```python
class FundingRequiredDocument(models.Model):
    """One sentence an award's own page gives as a document to submit.

    Spec 8.3 and 10.4. Verbatim page text, selected and labelled by the decision
    layer (D4 + D5, the same two requests a programme page gets) and never
    written by a model. Shared catalogue, and third-party text in it -- written
    only from pages the funding reader already vouches for.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    opportunity = models.ForeignKey(
        FundingOpportunity, on_delete=models.PROTECT, related_name="required_documents"
    )
    snapshot = models.ForeignKey("OfficialSourceSnapshot", on_delete=models.PROTECT)
    text = models.CharField(max_length=1_000)
    heading_path = models.CharField(max_length=500, blank=True, default="")
    position = models.PositiveIntegerField()
    requirement = models.CharField(max_length=10)
    probability = models.FloatField()
    model_version = models.CharField(max_length=40)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("opportunity", "snapshot", "position"),
                name="funding_required_document_once_per_sentence",
            ),
            models.CheckConstraint(
                condition=models.Q(requirement__in=("REQUIRED", "DESIRED", "unstated")),
                name="funding_required_document_requirement_valid",
            ),
        ]
```

Check `ProgramStatement.Requirement.values` on master before writing the second constraint and use exactly its values plus `"unstated"` (D5's own extra option): the constraint must admit every value `label_sentences` can return.

- [ ] **Step 4: Generate the migration and append its policies**

```bash
ls apps/funding/migrations | sort | tail -4
uv run python manage.py makemigrations funding --name award_documents_and_contact
```

Append to the generated file, and add `migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),` as the **last** operation (after the `CreateModel`):

```python
# funding_fundingrequireddocument joins _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalogue: the documents
# an award asks for are the same fact for every tenant. Same shape as
# 0030_program_awarding_institutions_rls, in the same migration as the table.
TABLE = "funding_fundingrequireddocument"

RLS_SQL = f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{TABLE}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""
```

In `tests/tenancy/test_database_isolation.py`, add `"funding_fundingrequireddocument",` to `_SHARED_TABLES` after `"funding_fundingbenefit_evidence_claims",`.

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_award_card_rls.py tests/tenancy/test_database_isolation.py -v`
Expected: PASS

- [ ] **Step 6: Checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
uv run python manage.py makemigrations --check --dry-run
git add apps/funding/models.py apps/funding/migrations/ tests/research/test_award_card_rls.py tests/tenancy/test_database_isolation.py
git commit -m "feat(funding): required documents and the contact, shared catalogue under its policies"
```

---

### Task 9: `required_documents` through D4 and D5

Reader-plan Tasks 6–7 decide which of a page's sentences list documents; this task runs those two requests over an award page's **whole** text — not the `_FUNDING_TERMS` selection, which drops a documents section that never mentions money — and attaches the sentences to the award they belong to.

**Files:**
- Create: `apps/research/card_questions.py`
- Modify: `apps/research/funding_reader.py`
- Test: `tests/research/test_card_questions.py`, `tests/research/test_funding_reader.py` (append)

**Interfaces:**
- Consumes: `page_questions.{select_sentences, label_sentences, Labelled}`, `sentences.{Sentence, page_sentences}`, `decisions.DecisionBudget`, `ProgramStatement.Kind.DOCUMENT`
- Produces: `AwardDocument`, `award_documents(sentences, *, language="", budget=None, client=None) -> tuple[AwardDocument, ...]`, `documents_for(heading, documents, *, awards_on_page) -> tuple[AwardDocument, ...]`; `funding_reader.write_award_documents(opportunity, snapshot, documents, *, now)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/test_card_questions.py
"""The card's two decided fields: which sentences list documents, and whom to write to."""

import pytest

from apps.research import card_questions
from apps.research.card_questions import AwardDocument, award_documents, documents_for
from apps.research.funding_judge import funding_lines
from apps.research.page_questions import Labelled, Selection
from apps.research.sentences import Sentence, page_sentences

PAGE = "\n".join([
    "# Scholarships",
    "## Excellence Scholarship",
    "The scholarship pays €1,200 a month.",
    "### Documents",
    "- Transcript of records",
    "## Mobility Grant",
    "A travel grant of €500.",
    "### Documents",
    "- Proof of enrolment",
])


def _labelled(sentence, kind="DOCUMENT", confidence=0.95, third_party=False):
    return Labelled(
        sentence=sentence, kind=kind, requirement="REQUIRED", confidence=confidence,
        third_party=third_party, third_party_probability=0.9 if third_party else 0.02,
        probabilities={kind: confidence}, model="jev-test",
    )


def test_only_confident_first_party_document_sentences_are_kept(monkeypatch):
    sentences = page_sentences(PAGE)
    documents = [s for s in sentences if s.text.startswith(("Transcript", "Proof"))]
    monkeypatch.setattr(card_questions, "select_sentences",
                        lambda found, **_: Selection(selected=tuple(documents)))
    monkeypatch.setattr(card_questions, "label_sentences", lambda found, **_: (
        _labelled(documents[0]),
        _labelled(documents[1], confidence=0.4),          # below the bar
    ))
    kept = award_documents(sentences)
    assert [d.sentence.text for d in kept] == ["Transcript of records"]


def test_a_referees_document_is_not_the_applicants(monkeypatch):
    (sentence,) = [s for s in page_sentences(PAGE) if s.text.startswith("Transcript")]
    monkeypatch.setattr(card_questions, "select_sentences",
                        lambda found, **_: Selection(selected=(sentence,)))
    monkeypatch.setattr(card_questions, "label_sentences",
                        lambda found, **_: (_labelled(sentence, third_party=True),))
    assert award_documents((sentence,)) == ()


def test_an_empty_page_asks_nothing(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("no request for an empty page")

    monkeypatch.setattr(card_questions, "select_sentences", refuse)
    assert award_documents(()) == ()


def _document(text):
    (sentence,) = [s for s in page_sentences(PAGE) if s.text == text]
    return AwardDocument(sentence=sentence, requirement="REQUIRED", probability=0.95, model="m")


def test_one_award_on_the_page_takes_every_document():
    documents = (_document("Transcript of records"), _document("Proof of enrolment"))
    assert documents_for("", documents, awards_on_page=1) == documents


def test_several_awards_each_take_only_the_documents_under_their_own_heading():
    documents = (_document("Transcript of records"), _document("Proof of enrolment"))
    kept = documents_for("Excellence Scholarship", documents, awards_on_page=2)
    assert [d.sentence.text for d in kept] == ["Transcript of records"]
    assert documents_for("", documents, awards_on_page=2) == ()


def test_the_judges_heading_and_the_sentence_heading_path_name_the_same_heading():
    """The attach rule compares a FundingDecision.heading (from funding_lines)
    with a Sentence.heading_path (from page_sentences). Two splitters, one page:
    if their heading text ever drifts, every multi-award page attaches nothing."""
    award_line = next(line for line in funding_lines(PAGE) if line.text.startswith("The scholarship"))
    (sentence,) = [s for s in page_sentences(PAGE) if s.text.startswith("The scholarship")]
    assert award_line.heading in sentence.heading_path
```

Append to `tests/research/test_funding_reader.py`:

```python
from apps.funding.models import FundingRequiredDocument  # noqa: E402
from apps.research.card_questions import AwardDocument  # noqa: E402
from apps.research.funding_reader import write_award_documents  # noqa: E402
from apps.research.sentences import page_sentences  # noqa: E402


def test_documents_are_written_verbatim_and_a_reread_of_the_page_replaces_them(program, snapshot):
    row = _write(_decision(), program, snapshot)
    (sentence,) = page_sentences("## Documents\n- Transcript of records")[1:]
    document = AwardDocument(sentence=sentence, requirement="REQUIRED", probability=0.93,
                             model="jev-1.13.0")
    now = timezone.now()
    write_award_documents(row, snapshot, (document,), now=now)
    write_award_documents(row, snapshot, (document,), now=now)
    (stored,) = FundingRequiredDocument.objects.filter(opportunity=row)
    assert (stored.text, stored.requirement) == ("Transcript of records", "REQUIRED")
    row.refresh_from_db()
    assert row.documents_read_at == now


def test_a_read_that_finds_no_documents_is_recorded_as_read(program, snapshot):
    row = _write(_decision(), program, snapshot)
    write_award_documents(row, snapshot, (), now=timezone.now())
    row.refresh_from_db()
    assert row.documents_read_at is not None
    assert not FundingRequiredDocument.objects.filter(opportunity=row).exists()
```

If `page_sentences` on master returns the heading as its own `Sentence` first (reader plan Task 2: "a heading is a sentence too"), the `[1:]` above is right; if it does not, drop the slice.

- [ ] **Step 2: Run to verify they fail**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_card_questions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.research.card_questions'`

- [ ] **Step 3: Write `card_questions.py` (documents half)**

```python
# apps/research/card_questions.py
"""The award card's two decided fields: the documents it asks for, and whom to write to.

Spec 8.3, 9.2 (the contact) and 10.4. Built on the decision layer
(apps/research/decisions.py) and the reader's own selection
(apps/research/page_questions.py): the documents are D4 + D5 run over the award
page's sentences -- the same two requests a programme page gets, never a second
selector -- and the contact's questions are the only ones this module builds,
which keeps typed-decisions section 3.2's rule that every question lives in a
named question module beside its threshold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from apps.funding.models import ProgramStatement

from .decisions import DecisionBudget
from .page_questions import label_sentences, select_sentences
from .sentences import Sentence


@dataclass(frozen=True)
class AwardDocument:
    sentence: Sentence
    requirement: str
    probability: float
    model: str


def award_documents(
    sentences: Sequence[Sentence],
    *,
    language: str = "",
    budget: DecisionBudget | None = None,
    client: object | None = None,
) -> tuple[AwardDocument, ...]:
    """The sentences of an award page that list a document the applicant submits.

    D4 selects for recall and D5 labels for precision (reader plan Tasks 6-7):
    only a sentence D5 labels DOCUMENT at its own bar, about the applicant and
    not a referee, is kept. A page with no sentence costs no request.
    """
    if not sentences:
        return ()
    selection = select_sentences(sentences, language=language, budget=budget, client=client)
    if not selection.selected:
        return ()
    labelled = label_sentences(
        selection.selected, language=language, budget=budget, client=client
    )
    return tuple(
        AwardDocument(
            sentence=item.sentence, requirement=item.requirement,
            probability=item.confidence, model=item.model,
        )
        for item in labelled
        if item.is_statement
        and item.kind == ProgramStatement.Kind.DOCUMENT
        and not item.third_party
    )


def documents_for(
    heading: str, documents: Sequence[AwardDocument], *, awards_on_page: int
) -> tuple[AwardDocument, ...]:
    """Which of a page's document sentences belong to one award.

    One award on the page: all of them. Several: only those under the award's
    own heading -- a page listing three schemes lists three sets of documents,
    and attaching all of them to each puts another scheme's requirements on
    this card. A document under no award's heading on such a page is attached
    to none; the card says NOT a list, never a wrong one.
    """
    if awards_on_page == 1:
        return tuple(documents)
    if not heading:
        return ()
    return tuple(document for document in documents if heading in document.sentence.heading_path)
```

- [ ] **Step 4: The writer**

In `apps/research/funding_reader.py`, import `FundingRequiredDocument` and `from .card_questions import AwardDocument`, then:

```python
@transaction.atomic
def write_award_documents(
    opportunity: FundingOpportunity,
    snapshot: OfficialSourceSnapshot,
    documents: tuple[AwardDocument, ...],
    *,
    now: datetime,
) -> None:
    """Replace this page's documents on the award, and record that it was read.

    Only rows from THIS page's source are replaced: a programme award is keyed
    across pages, and a re-read of one page may not delete what another said.
    An empty read is still a read -- `documents_read_at` is what separates "the
    page lists no documents" from "nobody has looked".
    """
    FundingRequiredDocument.objects.filter(
        opportunity=opportunity, snapshot__source=snapshot.source
    ).delete()
    FundingRequiredDocument.objects.bulk_create([
        FundingRequiredDocument(
            opportunity=opportunity,
            snapshot=snapshot,
            text=document.sentence.text[:1_000],
            heading_path=" › ".join(document.sentence.heading_path)[:500],
            position=document.sentence.position,
            requirement=document.requirement,
            probability=document.probability,
            model_version=document.model[:40],
        )
        for document in documents
    ])
    opportunity.documents_read_at = now
    opportunity.save(update_fields=["documents_read_at"])
```

(Use `sentences.heading_text(document.sentence.heading_path)` instead of the literal `" › ".join` if Task 2 landed `heading_text` with that separator — one spelling of a heading path in the codebase, not two.)

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_card_questions.py tests/research/test_funding_reader.py -v`
Expected: PASS

- [ ] **Step 6: Checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
git add apps/research/card_questions.py apps/research/funding_reader.py tests/research/test_card_questions.py tests/research/test_funding_reader.py
git commit -m "feat(research): an award's required documents, through D4 and D5"
```

---

### Task 10: The contact, and both decided fields wired into the read

Decision-log row 39 and §9.2. Code finds the candidates — an address or a link printed on the page, on one of the holder's own registrable domains, never a free-mail one — and the decision layer answers two things per candidate set: *which one is the office an applicant writes to about this award*, and, per address, *does the page attribute it to a named person*. Only an office address clears; otherwise the contact page; otherwise nothing, and the card says the office printed no contact.

**Files:**
- Modify: `apps/research/card_questions.py`, `apps/research/funding_reader.py`, `apps/research/pipeline.py`, `apps/funding/card.py`, `apps/funding/facts.py`, `apps/research/spine.py`
- Test: `tests/research/test_card_questions.py`, `tests/research/test_funding_reader.py`, `tests/research/test_pipeline_funding.py`, `tests/research/test_card_fields.py` (append), `tests/funding/test_card.py`

**Interfaces:**
- Consumes: `decisions.{Noul, Choice, Answer, Question, ask}`, `domains.email_domain`, `hosts.registrable_domain`, `harvest.{anchors, Anchor}`
- Produces: `EmailCandidate`, `LinkCandidate`, `Contact`, `contact_candidates(...)`, `award_contact(...)`, `PERSON_FLOOR`, `CONTACT_BAR`; `write_award_contact(opportunity, contact, *, now)`; `pipeline._read_card`, `CARD_READS_PER_HOUR`; `award_card(award, benefits, documents=())`, `award_facts(..., documents=())`

- [ ] **Step 1: Write the failing tests** (append to `tests/research/test_card_questions.py`)

```python
from apps.research.card_questions import (  # noqa: E402
    CONTACT_BAR,
    Contact,
    award_contact,
    contact_candidates,
)
from apps.research.decisions import Answer  # noqa: E402
from apps.research.harvest import Anchor  # noqa: E402

CONTACT_PAGE = "\n".join([
    "## Nomination",
    "Candidates are nominated by the university; write to intl@uni.example.edu.",
    "Questions about your file: Dr. Ayşe Demir, a.demir@uni.example.edu.",
    "Personal help: helper@gmail.com.",
    "Our partner office: office@other.example.org.",
])
DOMAINS = frozenset({"example.edu"})


def _answer(qid, value, confidence):
    return Answer(id=qid, value=value, confidence=confidence, probabilities={},
                  model="jev-test", provider="typesafe")


def _client(answers):
    def call(state, questions, **_kwargs):
        return {qid: answers[qid] for qid in questions}
    return call


def _candidates():
    return contact_candidates(
        page_sentences(CONTACT_PAGE),
        [Anchor(href="/contact", text="International Office", css_class=""),
         Anchor(href="https://elsewhere.example.org/x", text="Elsewhere", css_class="")],
        base_url="https://www.uni.example.edu/scholarships", domains=DOMAINS,
    )


def test_only_addresses_and_links_on_the_holders_own_domain_are_candidates():
    emails, links = _candidates()
    assert [c.address for c in emails] == ["intl@uni.example.edu", "a.demir@uni.example.edu"]
    assert [(c.url, c.text) for c in links] == [
        ("https://www.uni.example.edu/contact", "International Office"),
    ]


def test_an_office_address_the_decision_picks_is_the_contact():
    emails, links = _candidates()
    contact = award_contact("Excellence Scholarship", "Nomination", emails, links, client=_client({
        "e0:person": _answer("e0:person", False, 0.96),
        "e1:person": _answer("e1:person", True, 0.97),
        "email": _answer("email", "e0", 0.93),
        "link": _answer("link", "l0", 0.9),
    }))
    assert contact == Contact(email="intl@uni.example.edu", url="",
                              quote=emails[0].sentence.text, probability=0.93)


def test_a_named_persons_address_is_never_stored_and_the_office_page_is_used():
    emails, links = _candidates()
    contact = award_contact("Excellence Scholarship", "Nomination", emails, links, client=_client({
        "e0:person": _answer("e0:person", False, 0.96),
        "e1:person": _answer("e1:person", True, 0.97),
        "email": _answer("email", "e1", 0.95),
        "link": _answer("link", "l0", 0.9),
    }))
    assert contact is not None and contact.email == ""
    assert contact.url == "https://www.uni.example.edu/contact"


def test_below_the_bar_there_is_no_contact():
    emails, links = _candidates()
    contact = award_contact("Excellence Scholarship", "Nomination", emails, links, client=_client({
        "e0:person": _answer("e0:person", False, 0.96),
        "e1:person": _answer("e1:person", True, 0.97),
        "email": _answer("email", "e0", CONTACT_BAR - 0.1),
        "link": _answer("link", "none", 0.8),
    }))
    assert contact is None


def test_no_candidate_asks_nothing():
    def refuse(*_args, **_kwargs):
        raise AssertionError("no candidates, no request")

    assert award_contact("Award", "", (), (), client=refuse) is None
```

Append to `tests/research/test_card_fields.py` — **the reader plan's Task 3 case, now that `normalize` carries it**:

```python
def test_a_copy_in_uzbek_matches_its_line_whichever_apostrophe_either_used():
    assert on_line("5 000 000 so‘m", "Stipendiya miqdori 5 000 000 soʻm.")
```

Append to `tests/research/test_funding_reader.py`:

```python
from apps.research.card_questions import Contact  # noqa: E402
from apps.research.funding_reader import write_award_contact  # noqa: E402


def test_a_contact_is_written_with_its_line_and_no_contact_is_still_a_read(program, snapshot):
    row = _write(_decision(route="INSTITUTION_NOMINATES"), program, snapshot)
    write_award_contact(row, Contact("intl@uni.example.edu", "", "Write to intl@uni.example.edu.",
                                     0.93), now=timezone.now())
    row.refresh_from_db()
    assert (row.contact_email, row.contact_quote) == (
        "intl@uni.example.edu", "Write to intl@uni.example.edu.",
    )
    write_award_contact(row, None, now=timezone.now())
    row.refresh_from_db()
    assert row.contact_email == "" and row.contact_read_at is not None
```

Append to `tests/funding/test_card.py`:

```python
def test_a_read_card_reports_its_documents_and_its_contact():
    card = _card(documents_read=True, required_documents=("Transcript of records",),
                 contact_read=True, contact_url="https://uni.example.edu/contact")
    fill = card_fill(card)
    assert (fill["required_documents"], fill["contact"]) == ("FILLED", "FILLED")
    assert card_fill(_card(contact_read=True))["contact"] == "UNSTATED"
```

- [ ] **Step 2: Run to verify they fail**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research/test_card_questions.py tests/research/test_card_fields.py -v`
Expected: FAIL — `ImportError: cannot import name 'CONTACT_BAR'`

- [ ] **Step 3: The contact half of `card_questions.py`**

Extend the imports:

```python
import logging
import re
from urllib.parse import urljoin, urlsplit

from .decisions import Answer, Choice, DecisionBudget, Noul, Question, ask
from .domains import email_domain
from .harvest import Anchor
from .hosts import registrable_domain
from .sentences import Sentence, heading_text

logger = logging.getLogger(__name__)
```

and add:

```python
#: An address the decision chose is kept only when P(named person) is under
#: this. Low on purpose: storing a person's address is the error with a victim,
#: and missing an office address costs a fallback to its contact page.
PERSON_FLOOR = 0.3
#: A contact is an action a student takes -- they write to it. The vendor's own
#: routing pattern acts at 0.85 (typed-decisions 3.1a); Task 12 re-measures it.
CONTACT_BAR = 0.85
_MAX_EMAILS = 40
_MAX_LINKS = 200  # a Choice takes 255 options; "none" is one of them
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


@dataclass(frozen=True)
class EmailCandidate:
    address: str
    sentence: Sentence


@dataclass(frozen=True)
class LinkCandidate:
    url: str
    text: str


@dataclass(frozen=True)
class Contact:
    email: str
    url: str
    quote: str
    probability: float


def contact_candidates(
    sentences: Sequence[Sentence],
    page_anchors: Sequence[Anchor],
    *,
    base_url: str,
    domains: frozenset[str],
) -> tuple[tuple[EmailCandidate, ...], tuple[LinkCandidate, ...]]:
    """Addresses printed in the page's text and https links, both on one of the
    holder's own registrable domains. Code decides this, not a question: "on
    origin" (spec 9.2) is a fact about a host, and a free-mail address names a
    mailbox, never an office (domains.email_domain)."""
    emails = [
        EmailCandidate(address, sentence)
        for sentence in sentences
        for address in _EMAIL.findall(sentence.text)
        if email_domain(address) in domains
    ]
    links: list[LinkCandidate] = []
    seen: set[str] = set()
    for anchor in page_anchors:
        url = urljoin(base_url, anchor.href)
        text = " ".join(anchor.text.split())
        if (
            not text or url in seen or urlsplit(url).scheme != "https"
            or registrable_domain(url) not in domains
        ):
            continue
        seen.add(url)
        links.append(LinkCandidate(url, text))
    if len(emails) > _MAX_EMAILS or len(links) > _MAX_LINKS:
        logger.warning(
            "contact candidates capped: %d addresses, %d links", len(emails), len(links)
        )
    return tuple(emails[:_MAX_EMAILS]), tuple(links[:_MAX_LINKS])


def _ask(state: object, questions: dict[str, Question], **kwargs: object) -> dict[str, Answer]:
    """One seam, so a test injects a client the way page_questions' tests do."""
    client = kwargs.pop("client", None)
    if client is not None:
        return client(state, questions, **kwargs)  # type: ignore[operator]
    return ask(state, questions, **kwargs)  # type: ignore[arg-type]


def _p_yes(answer: Answer) -> float:
    return answer.confidence if answer.value is True else 1 - answer.confidence


def award_contact(
    name: str,
    heading: str,
    emails: Sequence[EmailCandidate],
    links: Sequence[LinkCandidate],
    *,
    language: str = "",
    budget: DecisionBudget | None = None,
    client: object | None = None,
) -> Contact | None:
    """Whom an applicant writes to about one award: an office address, else the
    office's contact page, else None. One request per award."""
    if not emails and not links:
        return None
    state = {
        "award": {"name": name, "heading": heading},
        "addresses": [
            {"id": f"e{i}", "address": c.address,
             "heading": heading_text(c.sentence.heading_path), "text": c.sentence.text}
            for i, c in enumerate(emails)
        ],
        "links": [{"id": f"l{i}", "text": c.text, "url": c.url} for i, c in enumerate(links)],
    }
    questions: dict[str, Question] = {}
    for i in range(len(emails)):
        questions[f"e{i}:person"] = Noul(
            question="Does the text attribute this e-mail address to a named individual "
                     "person rather than to an office, department, team or role?",
            inspect=f"`addresses[{i}]`",
            criteria={
                "true": "A person's name stands with the address, or the address is "
                        "introduced as a particular person's own.",
                "false": "The address is given for an office, a service or a function, "
                         "even when a job title is nearby.",
            },
        )
    if emails:
        questions["email"] = Choice(
            question="Which address should an applicant write to about the award in "
                     "`award`, for example to ask to be nominated for it?",
            options=(*(f"e{i}" for i in range(len(emails))), "none"),
            inspect="`addresses`",
        )
    if links:
        questions["link"] = Choice(
            question="Which link leads to the contact page of the office an applicant asks "
                     "about the award in `award`?",
            options=(*(f"l{i}" for i in range(len(links))), "none"),
            inspect="`links`",
        )
    answers = _ask(
        state, questions, decision="CARD_CONTACT", language=language, budget=budget,
        client=client,
    )
    email = answers.get("email")
    if email is not None and email.value != "none" and email.confidence >= CONTACT_BAR:
        index = int(str(email.value)[1:])
        if _p_yes(answers[f"e{index}:person"]) < PERSON_FLOOR:
            chosen = emails[index]
            return Contact(chosen.address, "", chosen.sentence.text, email.confidence)
    link = answers.get("link")
    if link is not None and link.value != "none" and link.confidence >= CONTACT_BAR:
        chosen_link = links[int(str(link.value)[1:])]
        return Contact("", chosen_link.url, chosen_link.text, link.confidence)
    return None
```

The addresses in `state` are public page text of the same standing as the funding section the readings already send to OpenAI and Anthropic; no student data is in it (typed-decisions §3.3). If `provider_for` on master keys decisions by a closed list rather than defaulting unknown IDs, add `"CARD_CONTACT"` to that list in the same commit.

- [ ] **Step 4: The contact writer**

In `apps/research/funding_reader.py`, extend the `card_questions` import with `Contact`, and add:

```python
@transaction.atomic
def write_award_contact(
    opportunity: FundingOpportunity, contact: Contact | None, *, now: datetime
) -> None:
    """The office to write to, or the record that the page printed none."""
    opportunity.contact_email = contact.email if contact else ""
    opportunity.contact_url = contact.url if contact else ""
    opportunity.contact_quote = contact.quote[:1_000] if contact else ""
    opportunity.contact_probability = contact.probability if contact else None
    opportunity.contact_read_at = now
    opportunity.save(update_fields=[
        "contact_email", "contact_url", "contact_quote", "contact_probability",
        "contact_read_at",
    ])
```

- [ ] **Step 5: The card reads both fields**

In `apps/funding/card.py`, import `FundingRequiredDocument` and change `award_card`:

```python
def award_card(
    award: FundingOpportunity,
    benefits: Sequence[FundingBenefit],
    documents: Sequence[FundingRequiredDocument] = (),
) -> AwardCard:
```

adding to the returned `AwardCard(...)`:

```python
        required_documents=tuple(
            document.text for document in sorted(documents, key=lambda d: d.position)
        ),
        documents_read=award.documents_read_at is not None,
        contact_email=award.contact_email,
        contact_url=award.contact_url,
        contact_quote=award.contact_quote,
        contact_read=award.contact_read_at is not None,
```

In `apps/funding/facts.py`, `award_facts` gains `documents: Sequence[FundingRequiredDocument] = (),` and passes it: `card=award_card(award, benefits, documents)`. In `apps/research/spine.py`, beside the benefits query:

```python
    documents_by_opportunity: dict[object, list[FundingRequiredDocument]] = {}
    for document in FundingRequiredDocument.objects.filter(opportunity_id__in=award_ids):
        documents_by_opportunity.setdefault(document.opportunity_id, []).append(document)
```

and `award_facts(award, benefits=benefits, rules=rules, documents=tuple(documents_by_opportunity.get(award.id, ())))`.

- [ ] **Step 6: Wire both reads after the decisions are written**

In `apps/research/pipeline.py`, add imports:

```python
from apps.funding.models import FundingOpportunity  # extend the existing import
from apps.research.models import OrganisationDomain

from .card_questions import award_contact, award_documents, contact_candidates, documents_for
from .decisions import DecisionBudgetExhausted, DecisionsUnavailable, run_budget
from .funding_reader import write_award_contact, write_award_documents  # extend existing
from .harvest import anchors  # extend the existing harvest import
from .sentences import page_sentences
```

and add, after `_fund_page`:

```python
#: Card reads per actor per hour: D4 and D5 once per award page, plus one
#: contact request per nomination-route award. Jev costs a fraction of a cent
#: a request; this is the runaway guard principle 9 wants beside the call.
CARD_READS_PER_HOUR = 120


def _read_card(
    page: FetchResult,
    written: list[tuple[FundingDecision, FundingOpportunity]],
    *,
    snapshot: OfficialSourceSnapshot,
    domains: frozenset[str],
    actor: UUID,
    degraded: list[str],
    now: datetime | None,
) -> None:
    """The two card fields a decision reads: the documents and whom to write to.

    After the rows exist, never before: a page whose awards did not agree has no
    card to fill. A refused or failed request leaves both fields NOT_READ and
    says so in `degraded` -- never an empty list that reads as "the page lists
    no documents".
    """
    if not written:
        return
    if rate_limited("award-card", actor, limit=CARD_READS_PER_HOUR, window_seconds=3_600):
        degraded.append(f"award card reads rate-limited: {snapshot.source.canonical_url}")
        return
    at = now or timezone.now()
    # The WHOLE page, not the funding selection: a documents section that never
    # mentions money is exactly what _FUNDING_TERMS drops.
    sentences = page_sentences(readable_text(page, terms=None))
    budget = run_budget()
    try:
        documents = award_documents(sentences, budget=budget)
        for decision, row in written:
            write_award_documents(
                row, snapshot,
                documents_for(decision.heading, documents, awards_on_page=len(written)),
                now=at,
            )
        emails, links = contact_candidates(
            sentences, anchors(page.body), base_url=page.final_url, domains=domains
        )
        for decision, row in written:
            if decision.route == "AUTOMATIC_ON_ADMISSION":
                continue
            write_award_contact(
                row, award_contact(decision.name, decision.heading, emails, links, budget=budget),
                now=at,
            )
    except (DecisionsUnavailable, DecisionBudgetExhausted) as error:
        degraded.append(
            f"award card not read ({type(error).__name__}): {snapshot.source.canonical_url}"
        )


def _programme_domains(program: Program, source: OfficialSource) -> frozenset[str]:
    found = {registrable_domain(source.canonical_url)}
    if program.institution is not None:
        found.add(registrable_domain(program.institution.official_website))
    return frozenset(domain for domain in found if domain)


def _holder_domains(holder_domain: str, organisation_id: object) -> frozenset[str]:
    found = {holder_domain, *OrganisationDomain.objects.filter(
        organisation_id=organisation_id
    ).values_list("registrable_domain", flat=True)}
    return frozenset(domain for domain in found if domain)
```

In `_fund_page`, collect the written rows — replace the write loop with:

```python
    decided: set[str] = set()
    written: list[tuple[FundingDecision, FundingOpportunity]] = []
    for decision in read.decisions:
        opportunity = write_funding_decision(
            decision, program=program, lead=lead, source=source, snapshot=snapshot, now=now
        )
        if opportunity is None:
            continue
        decided.add(opportunity.canonical_key)
        written.append((decision, opportunity))
        if opportunity.served:
            counters.served += 1
    counters.withdrawn += withdraw_unread(source, snapshot, decided)
    _read_card(
        page, written, snapshot=snapshot, domains=_programme_domains(program, source),
        actor=actor, degraded=degraded, now=now,
    )
```

and in `_fund_holder_page` the same shape: collect `written.append((decision, row))` in its loop, then after `withdraw_unread`:

```python
    if written:
        _read_card(
            page, written, snapshot=snapshot,
            domains=_holder_domains(holder_domain, written[0][1].organisation_id),
            actor=actor, degraded=degraded, now=now,
        )
```

Append a pipeline test to `tests/research/test_pipeline_funding.py` following that file's existing `_fund_page` fixtures: monkeypatch `pipeline.award_documents` to return one `AwardDocument` and `pipeline.award_contact` to return a `Contact`, run the page through `_fund_page`, and assert the written row has one `FundingRequiredDocument`, a `contact_email`, and both `*_read_at` set; then a second test where `award_documents` raises `DecisionsUnavailable` and assert `degraded` names the URL and `documents_read_at` stays `None`.

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/research tests/funding -v`
Expected: PASS, including the Uzbek-apostrophe `on_line` case (it passes only because reader-plan Task 3's `normalize` is on master — if it fails, Part B was started too early).

- [ ] **Step 8: Checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
git add apps/ tests/
git commit -m "feat(research): whom to write to -- an office, on origin, never a person; both decided fields wired"
```

---

# Part C — waits for build item 11

**Do not start Part C until item 11 has landed** and `apps/research/spine.py`'s awards reach `award_facts` with deadline evidence in `Evidence.deadline` / `Evidence.deadlines` (check: in `tests/funding/test_spine.py`'s end-to-end student, the served award's `AwardCandidateFacts.evidence.deadlines` is non-empty). Before it, every award's deadline state is `NOT_READ` and this task would empty the award list of every pack.

### Task 11: The pack refuses a card it cannot show

Spec §10.4: "an award whose page states no amount or deadline is a `CANDIDATE` the pack cannot show, and the tally says so." Deadline has three render states — a date, *decentralised*, *stated but not read* — never a silent null.

**Files:**
- Modify: `apps/funding/card.py`, `apps/funding/pack.py`
- Test: `tests/funding/test_card.py`, `tests/funding/test_pack_awards.py`

**Interfaces:**
- Consumes: `validity.{Evidence, select_deadline}`
- Produces: `DeadlineState`, `deadline_state(evidence, student) -> DeadlineState`; `ExcludedCandidate(reason_code="CARD_INCOMPLETE")`

- [ ] **Step 1: Write the failing tests**

Append to `tests/funding/test_card.py`:

```python
import datetime as dt  # noqa: E402

from apps.funding.card import deadline_state  # noqa: E402
from apps.funding.validity import Evidence  # noqa: E402

STUDENT = {"nationality": "AZ", "country_of_residence": "AZ"}


def test_a_deadline_is_a_date_stated_but_not_read_or_not_read_never_a_silent_null():
    assert deadline_state(Evidence(deadline=dt.date(2027, 1, 15)), STUDENT) == "DATE"
    assert deadline_state(
        Evidence(deadlines=((dt.date(2027, 1, 15), "NATIONALITY:IN"),)), STUDENT
    ) == "STATED_NOT_READ"
    assert deadline_state(Evidence(), STUDENT) == "NOT_READ"
```

Append to `tests/funding/test_pack_awards.py`:

```python
import datetime as dt  # noqa: E402

from apps.funding.card import AwardCard  # noqa: E402
from apps.funding.validity import Evidence  # noqa: E402

SHOWN = AwardCard(
    route="STUDENT_APPLIES_SEPARATELY", tuition="FULL", living="UNSTATED", amounts=(),
    duration_text="", duration_months=None, timing="UNSTATED", cycle="UNSTATED", unconfirmed=(),
)
DATED = Evidence(deadline=dt.date(2027, 1, 15))


def test_an_award_with_no_stated_amount_is_excluded_with_the_reason(profile):
    empty = AwardCard(**{**SHOWN.__dict__, "tuition": "UNSTATED"})
    pack = build_pack(profile, [_candidate()], EUR_RATES,
                      awards=[_award(card=empty, evidence=DATED)], today=TODAY)
    assert pack.awards == ()
    (excluded,) = [e for e in pack.excluded if e.reason_code == "CARD_INCOMPLETE"]
    assert "states no amount" in excluded.reasons[0]


def test_an_award_with_no_deadline_read_is_excluded_with_the_reason(profile):
    pack = build_pack(profile, [_candidate()], EUR_RATES,
                      awards=[_award(card=SHOWN, evidence=Evidence())], today=TODAY)
    assert pack.awards == ()
    assert any("deadline" in reason for e in pack.excluded for reason in e.reasons)


def test_an_unconfirmed_amount_is_still_a_stated_one(profile):
    split = AwardCard(**{**SHOWN.__dict__, "tuition": "UNSTATED", "unconfirmed": ("amount",)})
    pack = build_pack(profile, [_candidate()], EUR_RATES,
                      awards=[_award(card=split, evidence=DATED)], today=TODAY)
    assert len(pack.awards) == 1
```

Then, in the same file, every existing test that expects its award in `pack.awards` gets `card=SHOWN` and, if it passes no `evidence`, `evidence=DATED` — the rule, not a list, because item 11 may have added tests: **an award a test expects to be shown must carry a stated amount and a read deadline, or the test is asserting the behaviour this task removes.**

- [ ] **Step 2: Run to verify they fail**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/funding/test_card.py tests/funding/test_pack_awards.py -v`
Expected: FAIL — `ImportError: cannot import name 'deadline_state'`

- [ ] **Step 3: `deadline_state`**

In `apps/funding/card.py`, add `from apps.funding.validity import Evidence, select_deadline` and:

```python
DeadlineState = Literal["DATE", "DECENTRALISED", "STATED_NOT_READ", "NOT_READ"]


def deadline_state(evidence: Evidence, student: dict[str, object]) -> DeadlineState:
    """Spec 10.4's three states, plus the one that means nobody looked.

    DATE: this student's own deadline is known. STATED_NOT_READ: the page gives
    deadlines, or names this student's group, and no date for them was read --
    the card says so rather than showing somebody else's date (validity's
    `missing_for`). NOT_READ: no deadline evidence at all. DECENTRALISED is
    item 11's to set from its evidence; this function returns it only when
    `evidence` says so.
    """
    if getattr(evidence, "decentralised", False):
        return "DECENTRALISED"
    chosen = select_deadline(evidence, student)
    if chosen is not None and not chosen.missing_for:
        return "DATE"
    if chosen is not None or evidence.deadlines or evidence.conditions_without_dates:
        return "STATED_NOT_READ"
    return "NOT_READ"
```

If item 11 landed a decentralised marker under another name on `Evidence`, read that name here and drop the `getattr` — the `getattr` exists only so this task does not invent a field item 11 owns.

- [ ] **Step 4: The refusal**

In `apps/funding/pack.py`, import `card_fill, deadline_state` from `apps.funding.card`, and add:

```python
def _card_missing(award: AwardCandidateFacts, student: dict[str, object]) -> tuple[str, ...]:
    """What the card lacks that the pack needs before it may show the award (spec 10.4).

    An UNCONFIRMED amount counts as stated: the page stated one and the
    readings split on it, which tiered agreement shows beside its quote.
    """
    reasons: list[str] = []
    fill = card_fill(award.card) if award.card is not None else {}
    if fill.get("amount") not in ("FILLED", "UNCONFIRMED"):
        reasons.append(f"{award.name}'s own page states no amount")
    if deadline_state(award.evidence, student) == "NOT_READ":
        reasons.append(f"no deadline has been read for {award.name}")
    return tuple(reasons)
```

and in `build_pack`'s award loop, directly after the `NOT_ELIGIBLE` / `ELIGIBLE_BELOW_FIT_BAR` exclusion:

```python
        missing = _card_missing(
            award,
            {"nationality": profile.nationality, "country_of_residence": profile.country_of_residence},
        )
        if missing:
            # P1-7 and spec 10.4: shown as excluded with the reason, never
            # silently short -- and the tally counts it as a CANDIDATE.
            excluded.append(
                ExcludedCandidate(
                    program_id=award.award_id, reason_code="CARD_INCOMPLETE", reasons=missing
                )
            )
            continue
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_card uv run pytest tests/funding tests/research/test_spine.py -v` (and `tests/funding/test_spine.py`)
Expected: PASS. If `test_spine`'s end-to-end award is now excluded as `CARD_INCOMPLETE`, stop: either item 11's evidence is not reaching `award_facts`, or the spine's fixture award states no amount — fix the cause, never the assertion.

- [ ] **Step 6: Checks, then commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
git add apps/funding/card.py apps/funding/pack.py tests/funding/
git commit -m "feat(funding): the pack refuses a card with no amount or no deadline read, and says why"
```

---

# Task 12: The gate — cards filled, and the 30-card hand check

§16 item 13's gate. **Run steps 1–4 after Part A, again after Part B**, and record each run. Nothing here is asserted by a test: recall is printed and recorded, never asserted (§15); precision is scored by a person.

- [ ] **Step 1: The 58-host re-run, with cards**

The host list is the one the 2026-09-18 and item-3 runs used (the `--hosts` file named in `docs/superpowers/2026-09-16-funding-reader-precision-run.md` and its follow-ups). Run it under the catalog role, both keys set:

```bash
uv run python manage.py funding_yield --hosts <that file> --pages 4 --cards-csv /tmp/cards-$(date +%F).csv | tee /tmp/yield-$(date +%F).txt
```

Record from the `TOTAL` line: `served`, each `cards=` count, `off-line`. **The number the brief calls "cards filled"** is reported three ways, all over served awards: (a) per field, `FILLED ÷ served`; (b) *showable* — `amount ∈ {FILLED, UNCONFIRMED}` (Part C's amount leg); (c) `off-line ÷ amounts read`.

- [ ] **Step 2: The printed-but-missed amount rate** — a correctness check on recall, not a threshold on it

From `/tmp/cards-*.csv`, for every served award whose `amount` is `UNSTATED`, run `card_fields.currencies_in` and `parse_amount` over its quotes. An award whose own quote carries a currency-evidenced single figure but whose card says `UNSTATED` is **an amount printed and not written**. Report that count over served awards. **Proposed stop rule (for the owner to confirm, not in the spec):** above 20%, diagnose before Part B — the split is either the readings not copying (question wording), copies failing `on_line` (normalisation), or splits (`amount` in `unconfirmed`) — and the fix goes where the count says.

- [ ] **Step 3: The 30-card hand check**

```bash
uv run python manage.py card_check --sample /tmp/cards-<date>.csv --count 30 --seed 13 \
    --out docs/superpowers/research/<date>-award-card-hand-check.csv
```

A person opens each row's page and marks `correct` yes or no against the quote **and** the page (a value can match its quote and still be wrong about the award — the reading may have tied the line to the wrong award). Then:

```bash
uv run python manage.py card_check --score docs/superpowers/research/<date>-award-card-hand-check.csv
```

**Fails when:** any row unmarked; **any wrong amount** (a figure, a currency or a period a student budgets on) — *zero tolerance is this plan's proposal, extending the spec's zero-false-eligibility rule to the number a student acts on; confirm with the owner*; **any wrong condition** (§8.8's zero false eligibility); or overall precision under 90% (§8.8). Fewer than 30 served cards with a filled field is itself the result: record it, and the gate waits for yield (item 3's gate), not for this plan.

- [ ] **Step 4: Record it**

Write `docs/superpowers/research/<date>-award-card-gate.md` with: the commit measured, the host list, the three fill numbers, the missed-amount rate, the hand-check score per field and overall, the cost of the run (the vendors' credit headers and the readings' token counts as `funding_yield` logs them), and — per failure — which field and why. Commit it with the hand-check CSV. Repeat the hand check every 200 served awards (§8.8).

- [ ] **Step 5: The live test, once**

```bash
POSTGRES_DB=tehsil_card uv run pytest -m live tests/research/test_funding_judge_card.py -v
```

Record pass or fail in the gate note. A failure here with a passing hand check means the question reads German figures differently from the corridor's pages — worth a line, not a stop.

---

## Self-review against the brief

- **Every field the brief names has a task:** amount, currency, period, duration, `timing`, `cycle` — Tasks 2–6; `required_documents` — Tasks 8–9; `contact` — Tasks 8, 10, office-only by decision with a person-attribution Noul and code-checked origin.
- **"Read the typed decisions spec first … which parts must wait and which can land before it"** — stated in its own section and restated at the head of Parts B and C, with the check commands that prove the prerequisites landed.
- **Never a hard-coded migration number** — both migrations are generated by name against the leaf the executor lists, with the merge path spelled out.
- **The new table** states its tenancy (shared catalogue), carries its RLS policies in the same migration, joins `_SHARED_TABLES`, and is verified through `runtime_connection` with the grant-first negative control.
- **No `apps/`, `tests/` or `config/` file is modified by this plan's commit** — only this document.
- **Ends with a gate**, with what fails it: Task 12.

## After the plan

Part A is one PR. Part B is a second PR, opened only after its prerequisites are on master. Part C is a third, after item 11. Each PR links this plan, reports the after-every-task checks, and — for A and B — carries the Task 12 gate note for its commit.
