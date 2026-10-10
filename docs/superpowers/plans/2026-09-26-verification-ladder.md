# The Verification Ladder (funding engine item 11) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A student sees an award as an option only when its own site says the money is there for
*their* intake, or when its history shows it opens again before that intake starts. The system
verifies this without a counsellor. Every verification records which step of the ladder settled it
and what it cost in dollars, taken from what the vendors actually billed.

**Architecture:** The **decision** stays exactly where it is. `apps/funding/validity.py::cycle_validity`
is built, pure and unchanged by every task here except two read-only public names (Task 5). This plan
builds the **evidence** that function decides on, in seven parts:

- `FundingCycleVerification` (shared catalog), one row per `(opportunity, intake_start_year)`.
- The reader's writers record the dates they already read as step-0 evidence.
- `apps/funding/cycle_evidence.py`, a pure translator from stored evidence rows to `validity.Evidence`.
- `apps/funding/cycle_schedule.py`, a pure scheduler: cadence, tracked intakes and expiry.
- `apps/research/cycle_verification.py`, the ladder: 0 own pages → 1 cycle-vocabulary crawl →
  1b Wayback → 1c register cadence → 2 one own-site hop → 3 Exa, then Brave, site search. Each step
  runs only while the state is still `UNVERIFIED`.
- `manage.py verify_due_cycles`, the scheduled worker, plus a DISABLED EventBridge rule.
- `manage.py cycle_verify --truth`, the gate.

The interim rule in `evaluate_award` ("hide only what is known shut") retires in the last task, and
only if the gate passes.

**Tech Stack:** Django 5.2, PostgreSQL row-level security, the fetch engine already on master
(`fetch_page`, `fetch/site.py::crawl`, `fetch/archive.py`), Firecrawl `changeTracking`, the Wayback
availability API, Exa `/search` with `includeDomains`, Brave web search, the funding reader
(`funding_judge.read_funding`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md`. This plan is
§16 build item 11. Read §9 in full (9.1 states, 9.2 evidence, 9.3 cadence, expiry, cost and the
gate). Also read §3 (principles 2, 5, 6, 7, 9), §7.1–7.4 (the fetch seam, outcomes), §7.5 (crawl
parameters), §7.6 (refresh — the monitors this plan must not collide with), §8.3 (`applies_to`,
`stated_on`, `deadline`, `deadline_for`), §8.6 (the serve rule and its cycle clause), §12 (data),
§13 (the verification cost row) and §15 (the readiness-ledger row
"cycle verification ≥ 95% precision on `OPEN`/`UPCOMING`"). The 2026-09-18 holder-axis plan's
Tasks 9–10 (`docs/superpowers/plans/2026-09-18-funding-reader-holder-axis.md`) sketched this work
first. Its validity half landed and its ladder half did not. This plan supersedes that ladder half
and keeps its test cases.

**Base:** `master` at `115c752` (2026-09-26). Work on the branch this plan is committed to, in a fresh
worktree. Test database: `POSTGRES_DB=tehsil_verification_ladder` — never share a test DB between
sessions (CLAUDE.md).

---

## What exists, measured against master `115c752` — read before Task 1

| fact | where | consequence for this plan |
|---|---|---|
| `cycle_validity`, `select_deadline`, `project_window`, `intake_start_year`, `Evidence`, `RegisterCadence` are built and pure | `apps/funding/validity.py` (360 lines), `tests/funding/test_validity.py` | This plan never edits a branch of `cycle_validity`. Task 5 adds only two public names; every existing test must pass unchanged |
| The reader **already reads** `applies_to`, `stated_on`, `deadline`, `deadlines[(date, deadline_for)]` per award per intake | `funding_judge.FundingDecision` (lines 496–556), `_intake_buckets`, `_decide` | Step 0 costs ~$0 **only if these are stored**. They are not stored today (next row) |
| The writers persist **only** `suspended_for` and `suspension_quote` of those fields | `funding_reader._suspension`, `write_holder_decision`, `write_funding_decision` | Task 6 records the rest as step-0 evidence |
| **One award, several intakes, one row:** `_intake_buckets` emits one `FundingDecision` per `(heading, kind, scope, intake)`, but `canonical_key` omits the intake, so each later decision overwrites the row. Last write wins, `served` and `suspension_quote` included | `funding_reader.write_holder_decision` (`canonical_key = …:{heading}:{kind}`) | Not fixed here (it is the writer's identity rule, §8.7). Task 6 records **every** intake's evidence, so validity no longer depends on which decision was written last. Reported to the owner in the PR |
| `evaluate_award` gate 2 is the interim rule: an award is hidden only when shut; `UNVERIFIED` passes | `apps/funding/evaluation.py:564–640`; pinned by `tests/funding/test_award_gates.py::test_an_unverified_award_is_still_eligible_and_that_is_deliberate` | Task 14 retires it, **conditional on the Task 13 gate** |
| `facts.award_facts` builds `Evidence` from the row's suspension fields only | `apps/funding/facts.py:193–200`, called from `apps/research/spine.py:201` | Task 14 feeds it the verification row |
| `Organisation.cadence_open_month`, `cadence_deadline_month`, `cadence_source`, `cadence_verified_for_cycle` exist | `apps/research/models.py:122–129` | Step 1c is free: no fetch |
| `fetch_page(url, *, purpose, tag, require_origin, budget)`; `site.crawl(url, *, api_key, limit, tag, include_paths)`; `site.crawl_ceiling(limit)` (no caller yet); `archive.latest_capture` hard-wired to "closest to now, ≤ 365 days" | `apps/research/fetch/` | Task 9 adds `archive.capture_near(url, *, at, …)` by factoring `latest_capture`, and leaves `latest_capture`'s behaviour and tests untouched |
| `exa_site_search(*, query, domain, num_results)` → `SiteSearchResult(urls, cost_usd, provider)` | `apps/research/providers/exa.py` | Step 3 uses it as is |
| Brave has only the open-web `BraveProvider` — no site-restricted shape | `apps/research/providers/brave.py` | Task 10 adds `brave_site_search` |
| `SweepBudget` meters vendor credits and reports `usd()` at `USD_PER_CREDIT` (plan rates) | `apps/research/fetch/__init__.py:105–186` | Fetch cost comes from here, never estimated |
| No token usage is captured on the funding reader's model calls | `funding_judge` (`parser.parse`, `claude_parsed_or_none`) | Task 4 meters them by wrapping the two clients. `funding_judge` is not edited |
| No `deadline_for` normaliser exists; validity expects `NATIONALITY:IN`, `APPLICANT_CLASS:NON_EU`, `ROUND:2`, … | `validity._condition_outcome` | Task 2 builds it, from data |
| `docs/research/2026-09-cycle-truth-set.csv` is named in validity's docstring and **does not exist** | — | Task 12 builds it |
| `funding` migrations end at the merge node `0048_merge_20260925_0838`. The brief's "`research` at `0009_site_job_record_rls`" is also true. This plan's migrations are in **funding** | `apps/funding/migrations/` | See Global Constraints: take the real leaf and expect a merge migration |

## Decisions this plan takes where the spec is silent or conflicts — each is flagged in the PR

1. **The one hop never leaves the organisation's own registrable domains.** §9.2 says "one hop to the
   apply/portal link". CLAUDE.md says "**No fetch vendor is ever pointed at a portal**". That rule is a
   legal boundary, not a cost preference, and it is written in the repo's own instructions. So step 2
   fetches a link only when its registrable domain is one of the organisation's `OrganisationDomain`
   rows or its `primary_domain`. Every off-domain apply link is recorded in the trail as
   `hop_withheld:<host>` and never fetched. Widening this is an owner decision. The trail counts what
   it would have bought.
2. **Step-0 evidence lives on the verification rows, with no second table.** The writer appends it to
   the row of every tracked intake. The spec gives `FundingCycleVerification.evidence` exactly this
   job, and tracked intakes are few (Task 5).
3. **A past cycle counts toward `past_calls` only with a dated opening** (`stated_on` on a YES line of
   that cycle). A cycle seen only by its deadline is kept in `cycles_observed` with `open: null` and
   counted in the gate report as `cycles_without_opening`. The decision side (`project_window`)
   needs an opening date, and inventing one from a deadline is the guess §9.1 forbids. If the gate
   shows this strictness costs `UPCOMING` recall, that is a decision-side amendment for the owner.
4. **Expiry is done on the evidence side.** A projection that lapsed 45 days without a call is
   *withheld* from `Evidence` (no `past_calls`, no cadence). Unchanged, `cycle_validity` then answers
   `UNVERIFIED`. No branch of the decision changes.
5. **Model cost is priced from a sourced list-price table in settings.** A model or a token class
   missing from the table leaves `cost_complete = False` on the row. The price is never guessed.
   Token counts are always stored, so a late price can be applied.
6. **The verifier writes award rows in exactly one case:** a changed own page that is the award's
   only source no longer describes it. The row is then `WITHDRAWN` by the same rule as
   `funding_reader.withdraw_unread`. This is §19's owed "unserve sweep". Nothing else here writes
   `served`.
7. **The per-intake check is enforced where the intake is known — the evaluator — not on `served`.**
   §8.6 says `served` needs `OPEN`/`UPCOMING` "once §9 lands". But `served` is one flag per award,
   and validity is per intake: the same award is `CLOSED_FOR_INTAKE` for 2026 and `UPCOMING` for
   2027. Task 14 therefore puts the rule in `evaluate_award`, which reads the row for the student's
   own intake. The pool still never reads an unserved row.
8. **The rate-limit actor is the platform.** No tenant triggers a verification, so a per-tenant
   limiter would limit nothing. `rate_limited("cycle-verification", PLATFORM_ACTOR, …)` is the
   model-call circuit-breaker. The per-award and per-run USD ceilings are the cost ones.
9. **Vocabularies are data** (principle 7): `docs/research/cycle-vocabulary.csv`,
   `docs/research/deadline-condition-terms.csv` and `docs/research/country-labels.csv`. Each row
   carries a source and a verified-on date. The CSVs ship **only** the terms the spec itself names
   (§9.2) and English condition phrases. The gate's per-country recall shows where a language is
   missing; terms are added then, each with a source, never ahead of a measurement.
10. **The step-3 query is English plus the award's own name** ("<name> <year> call for applications
    deadline"). §9.2 asks for the local language, and a translation authored here would be a guess
    with no source. Exa is multilingual and the name is usually local already; the gate reports
    step-3 recall per country.

## Decision-side findings, not fixed here (reported to the owner in the PR)

- **Autumn deadlines project a year late.** `project_window` measures the shift from
  `deadline.year`. A call opening October 2025 with a **November 2025** deadline for the 2026 intake
  "served" 2025 by that rule. Projected to target 2027 it becomes November 2027, after the intake
  starts, and `cycle_validity` still returns `UPCOMING` while that date is ahead. January deadlines,
  the docstring's own case, are right. Task 7 pins the behaviour with an `xfail(strict=True)` test so
  a later fix shows up.
- **Class-conditioned deadlines match nobody today.** `evaluate_award` builds the student dict from
  `nationality` and `country_of_residence` only. Every `APPLICANT_CLASS:…` condition is therefore
  `FAILED` for every student, and a non-EU student is shown the general date. Universities giving
  non-EU applicants an earlier date is §9.2's own example. This is latent today: no deadline reaches
  `Evidence` yet. It goes live the moment this plan feeds deadlines. So Task 14, the change that
  makes deadlines live, adds `applicant_class` (`EU`/`NON_EU`, from the sourced `REGIONS["EU"]`) to
  the student dict. `INTERNATIONAL`/`DOMESTIC` stay single-valued equality in validity, which cannot
  hold both of a student's classes. The gate's conditional-deadline rows measure this.

## Depends on / does not depend on

| item | relation |
|---|---|
| items 0–6 (lineage, register, tiered agreement, spine, fetch core, providers) | **consumed as built on master**: `Organisation`, `OrganisationDomain`, `fetch_page`, `crawl`, `archive`, `exa_site_search`, `read_funding`, `evaluate_award`, `award_facts` |
| item 7 (enumerators), item 8 (resolver), item 10 (sweep harness) | **not depended on.** Verification runs over awards that already exist. It needs no denominator and no new host |
| item 9 (site jobs, monitors) | **complementary, must not collide.** The monitors use the `<cycle>:<host>` tags. Every fetch here uses the tag `cycle-verify:<intake_year>`, so neither consumer ever sees the other's `changed` as `same` |
| item 12 (resolution queue) | **not depended on.** No counsellor or operator is in this loop (§9 owner requirement). `UNVERIFIED` is a state, not a question |
| item 13 (the card) | **consumes this.** The card's "deadline and whose deadline it is" and "verification state for the student's intake with its evidence" read `FundingCycleVerification`. Item 13 may land before or after this plan |
| item 14 (demand cells) | **not depended on** |
| item 15 (Batch/Flex, cheap first read) | **not assumed.** Ladder reads are background work and are the natural first Batch customer. The `read` seam (Task 8) is the one function item 15 would change |
| `docs/superpowers/plans/2026-09-23-reader-and-multilingual-layer.md` | **not affected.** It rewrites the *programme-requirements* reader (`reader.py`). The funding reader (`funding_judge`) this plan calls is untouched by it |

## Global Constraints

- **The decision side is frozen.** Task 5 adds `ASSUMED_INTAKE_START` and `projected_window(...)` to
  `validity.py` as public names over existing private ones. No branch of `cycle_validity`,
  `select_deadline` or `project_window` changes. `tests/funding/test_validity.py` passes unmodified
  after every task.
- **The origin is the only evidence** (principle 2). Every stored quote carries the URL we fetched,
  the `sha256` of the bytes, the date and, for a capture, `captured_at`. Search providers yield URLs
  only, never a snippet or a title (principle 3).
- **Own site plus one hop, never further** (§9.2). Every URL a step produces is fetched through
  `fetch_page` with `require_origin`. Crawl and search results whose registrable domain is not the
  organisation's own are dropped before any fetch.
- **No vendor is pointed at a portal** (CLAUDE.md). See decision 1.
- **Every model call** goes through `read_funding` (untrusted text as data, schema-constrained,
  capped tokens), is paid for before it is made through the same `pay` pattern as
  `pipeline._pay_for_funding`, and is rate-limited in the same change that wires it (principle 9,
  CLAUDE.md "LLM/AI security").
- **Every cost is recorded, never estimated** (§9.3). Fetch cost comes from `SweepBudget`, model cost
  from metered tokens at list price, Exa cost from its `costDollars`, and Brave's from
  `BRAVE_USD_PER_REQUEST` × requests made.
- **Every plan-dependent number is a setting with an env override** — the spec's numbers are the
  defaults.
- **Nothing names a scheme, funder, country or page in code** (principle 7). Named pages are rows in
  the truth set, never logic.
- **RLS is verified against a `NOBYPASSRLS` role or it is not verified.** Use `runtime_connection`
  (`tests/conftest.py`). The test role bypasses RLS (CLAUDE.md "Row-level security").
- **Every vendor call in a test goes through an injected seam.** No test makes a network call except
  `-m live` tests, which `addopts = "-m 'not live'"` excludes.
- **Migrations: never hard-code a number.** Before Task 3, run `ls apps/funding/migrations/`, take
  the real leaf and name the files `<next>_cycle_verification.py` / `<next+1>_cycle_verification_rls.py`.
  If another branch lands a `funding` migration first, `makemigrations --check` in CI fails. Merge
  master and create a merge migration with `uv run python manage.py makemigrations funding --merge`.
  Never renumber by hand (the 2026-09-15 collision in CLAUDE.md).
- **Never run `ruff format`** — the repo's gate is lint-only.
- **After every task:** `uv run ruff check apps config tests scripts`, `uv run mypy apps config`,
  `POSTGRES_DB=tehsil_verification_ladder uv run pytest`,
  `uv run python manage.py makemigrations --check --dry-run`,
  `uv run bandit -c pyproject.toml -r apps config`. All clean.
- **Commits** use a pathspec (`git commit -- <paths>`), never `git add -A`.

## File Structure

| file | responsibility |
|---|---|
| `config/settings/base.py` (modify) | the `CYCLE_*` block, `MODEL_LIST_PRICES_*`, `BRAVE_USD_PER_REQUEST` |
| `docs/research/cycle-vocabulary.csv` (new) | the §9.2 crawl and apply vocabulary, as data |
| `docs/research/deadline-condition-terms.csv` (new) | `deadline_for` phrases → condition vocabulary, as data |
| `docs/research/country-labels.csv` (new, generated) | Wikidata country labels and demonyms → ISO 3166-1 alpha-2 |
| `apps/research/cycle_vocabulary.py` (new) | loads the vocabulary; `include_paths`, `year_tokens`, `mentions_award`, `apply_links` |
| `apps/funding/deadline_conditions.py` (new) | `normalise_condition(text, *, countries, terms) -> str` |
| `apps/research/management/commands/refresh_country_labels.py` (new) | regenerates `country-labels.csv` from Wikidata (CC0) |
| `apps/funding/models.py` (modify) | `FundingCycleVerification` |
| `apps/funding/migrations/<leaf+1>_cycle_verification.py`, `<leaf+2>_cycle_verification_rls.py` (new) | the table; `shared_catalog_select` + `catalog_ingestion_write` |
| `apps/research/metering.py` (new) | `Meter`, `MeteredResponses`, `MeteredMessages` |
| `apps/funding/validity.py` (modify, additive only) | `ASSUMED_INTAKE_START`, `projected_window(...)` |
| `apps/funding/cycle_evidence.py` (new, pure) | `EvidenceEntry`, `to_evidence`, `observations`, `past_calls`, `deadline_student` |
| `apps/funding/cycle_schedule.py` (new, pure) | `tracked_intakes`, `next_check`, `projection_lapsed` |
| `apps/research/cycle_verification.py` (new) | `entries_from_decision`, `record_read_evidence`, `Subject`, `Seams`, `verify_cycle`, `joins`, `persist_verdict` |
| `apps/research/funding_reader.py` (modify) | both writers call `record_read_evidence` |
| `apps/research/fetch/archive.py` (modify) | `capture_near`; `latest_capture` factored, behaviour unchanged |
| `apps/research/providers/brave.py` (modify) | `brave_site_search` |
| `apps/research/management/commands/verify_due_cycles.py` (new) | the scheduled worker |
| `apps/research/management/commands/cycle_verify.py` (new) | the gate |
| `infra/template.yaml` (modify) | `VerifyDueCyclesRule`, `State: DISABLED` |
| `docs/research/2026-09-cycle-truth-set.csv` (new) | the hand-labelled truth set |
| `docs/superpowers/2026-09-cycle-verification-gate.md` (new) | the gate's recorded result |
| `apps/funding/facts.py`, `apps/funding/evaluation.py`, `apps/research/spine.py` (modify, Task 14 only) | the interim rule retires |
| `tests/tenancy/test_database_isolation.py` (modify) | `funding_fundingcycleverification` joins `_SHARED_TABLES` |
| tests: `tests/research/test_cycle_vocabulary.py`, `tests/funding/test_deadline_conditions.py`, `tests/funding/test_cycle_verification_rls.py`, `tests/research/test_metering.py`, `tests/funding/test_cycle_evidence.py`, `tests/funding/test_cycle_schedule.py`, `tests/research/test_cycle_verification.py`, `tests/research/test_fetch_archive.py` (extend), `tests/research/test_providers.py` (extend), `tests/research/test_cycle_commands.py`, `tests/infra/test_template.py` (extend), `tests/funding/test_award_gates.py` (Task 14) | |

---

### Task 1: Settings and the cycle vocabulary, as data

**Files:**
- Modify: `config/settings/base.py`
- Create: `docs/research/cycle-vocabulary.csv`
- Create: `apps/research/cycle_vocabulary.py`
- Test: `tests/research/test_cycle_vocabulary.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/test_cycle_vocabulary.py
"""The cycle vocabulary is data (spec principle 7); these pin how it is read."""
import datetime as dt

import pytest

from apps.research import cycle_vocabulary as vocab


@pytest.fixture
def csv_file(tmp_path, monkeypatch):
    path = tmp_path / "cycle-vocabulary.csv"
    path.write_text(
        "language,role,term,source,verified_on\n"
        "en,cycle,deadline,spec#9.2,2026-09-22\n"
        "de,cycle,bewerbung,spec#9.2,2026-09-22\n"
        "tr,cycle,son tarih,spec#9.2,2026-09-22\n"
        "tr,cycle,başvuru,spec#9.2,2026-09-22\n"
        "en,apply,apply,spec#9.2,2026-09-22\n",
        encoding="utf-8",
    )
    vocab.terms.cache_clear()
    monkeypatch.setattr(vocab, "_CSV", path)
    yield path
    vocab.terms.cache_clear()


def test_a_row_without_a_source_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "bad.csv"
    path.write_text("language,role,term,source,verified_on\nen,cycle,call,,2026-09-22\n")
    vocab.terms.cache_clear()
    monkeypatch.setattr(vocab, "_CSV", path)
    with pytest.raises(ValueError, match="incomplete"):
        vocab.terms()
    vocab.terms.cache_clear()


def test_english_always_joins_the_hosts_languages(csv_file):
    assert vocab.for_languages("cycle", ["de"]) == ("deadline", "bewerbung")


def test_a_host_with_no_recorded_language_gets_every_term(csv_file):
    assert set(vocab.for_languages("cycle", [])) == {"deadline", "bewerbung", "son tarih", "başvuru"}


def test_path_patterns_carry_an_ascii_fold_and_a_hyphenated_form(csv_file):
    paths = vocab.include_paths(["tr"], today=dt.date(2026, 9, 26))
    assert {"başvuru", "basvuru", "son-tarih"} <= set(paths)


def test_year_tokens_are_the_previous_two_the_current_and_the_next():
    assert vocab.year_tokens(dt.date(2026, 9, 26)) == ("2024", "2025", "2026", "2027")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The Example Fellowship opens soon", True),   # the award's name
        ("Applications for 2027 open in March", True),  # a year token
        ("Our campus has a new library", False),
        ("Call 020261234", False),  # digits inside a number are not a year
    ],
)
def test_a_page_reaches_the_reader_only_by_name_or_year(text, expected):
    years = ("2025", "2026", "2027")
    assert vocab.mentions_award(text, name="Example Fellowship", years=years) is expected
```

- [ ] **Step 2: Run to confirm they fail**

Run: `POSTGRES_DB=tehsil_verification_ladder uv run pytest tests/research/test_cycle_vocabulary.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.cycle_vocabulary'`.

- [ ] **Step 3: Write the data file**

`docs/research/cycle-vocabulary.csv` — exactly the terms §9.2 names, sourced to it:

```csv
language,role,term,source,verified_on
en,cycle,call,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,cycle,apply,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,cycle,deadline,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,cycle,news,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,cycle,announcement,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
de,cycle,bewerbung,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
de,cycle,frist,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
de,cycle,ausschreibung,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
tr,cycle,başvuru,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
tr,cycle,son tarih,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
tr,cycle,duyuru,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
az,cycle,müraciət,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
az,cycle,elan,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,apply,apply,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,apply,application,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,apply,portal,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
de,apply,bewerbung,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
tr,apply,başvuru,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
az,apply,müraciət,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
```

- [ ] **Step 4: Write the loader**

```python
# apps/research/cycle_vocabulary.py
"""The cycle vocabulary of spec 9.2 -- data, never a list in code (principle 7).

Two roles. `cycle` terms steer the step-1 crawl (`includePaths`) toward the
pages where a funder announces a call; `apply` terms pick the one own-site hop
of step 2. Neither decides anything: a path pattern that matches nothing costs
nothing, and whether a page is evidence is the reader's and validity's question.

The file ships only the terms the spec names. A language missing here shows up
as low per-country recall in the gate (Task 13) and is added then, with a
source -- never ahead of a measurement.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from apps.research.harvest import anchors

_CSV = Path(__file__).resolve().parents[2] / "docs" / "research" / "cycle-vocabulary.csv"
_ROLES = frozenset({"cycle", "apply"})


@dataclass(frozen=True)
class Term:
    language: str
    role: str
    term: str
    source: str
    verified_on: str


@cache
def terms() -> tuple[Term, ...]:
    with _CSV.open(encoding="utf-8", newline="") as handle:
        rows = tuple(
            Term(**{key: (value or "").strip() for key, value in row.items()})
            for row in csv.DictReader(handle)
        )
    for row in rows:
        if row.role not in _ROLES or not (row.term and row.source and row.verified_on):
            raise ValueError(f"cycle-vocabulary row is incomplete: {row}")
    return rows


def for_languages(role: str, languages: Iterable[str]) -> tuple[str, ...]:
    """English plus the host's languages; every language when none is recorded.

    Every language, not English alone, for an unknown host: a missing local term
    costs the page, an extra one costs nothing.
    """
    wanted = {language.casefold() for language in languages}
    rows = [row for row in terms() if row.role == role]
    if wanted:
        rows = [row for row in rows if row.language in {"en", *wanted}]
    return tuple(dict.fromkeys(row.term for row in rows))


def _fold(term: str) -> str:
    return unicodedata.normalize("NFKD", term).encode("ascii", "ignore").decode()


def include_paths(languages: Iterable[str], *, today: dt.date) -> tuple[str, ...]:
    """Plain terms for `site.crawl(include_paths=...)`, which escapes them.

    A URL path carries `basvuru` or `son-tarih` far more often than `başvuru`
    or `son tarih`, so each term also goes out folded and hyphenated. Unmeasured
    per host; the gate's step-1 recall is what says whether it is enough.
    """
    found: list[str] = []
    for term in (*for_languages("cycle", languages), *year_tokens(today)):
        for variant in (term, _fold(term)):
            hyphenated = variant.replace(" ", "-")
            if hyphenated and hyphenated not in found:
                found.append(hyphenated)
    return tuple(found)


def year_tokens(today: dt.date) -> tuple[str, ...]:
    """The previous two, the current and the next year (spec 9.2)."""
    return tuple(str(today.year + delta) for delta in (-2, -1, 0, 1))


def mentions_award(text: str, *, name: str, years: Iterable[str]) -> bool:
    """Spec 9.2: a crawled page reaches the reader only if it names the award
    or carries a year token. String matching, no model."""
    folded = text.casefold()
    if name and name.casefold() in folded:
        return True
    return any(re.search(rf"(?<!\d){re.escape(year)}(?!\d)", folded) for year in years)


def apply_links(body: bytes, *, base_url: str, languages: Iterable[str]) -> tuple[str, ...]:
    """Anchors whose href or text carries an `apply` term, in page order."""
    from urllib.parse import urljoin

    wanted = [term.casefold() for term in for_languages("apply", languages)]
    found: list[str] = []
    for anchor in anchors(body):
        absolute = urljoin(base_url, anchor.href)
        haystack = f"{absolute} {anchor.text}".casefold()
        if absolute.startswith(("http://", "https://")) and any(t in haystack for t in wanted):
            if absolute not in found:
                found.append(absolute)
    return tuple(found)
```

- [ ] **Step 5: Add the settings block** after `FETCH_BUDGET_RETRY_HOURS` in `config/settings/base.py`

```python
# --- Cycle verification (funding engine item 11; master spec 9.2-9.3) ----------
#: Step 1's crawl: spec 9.2's `limit: 15`, not FETCH_CRAWL_LIMIT's 25.
CYCLE_CRAWL_LIMIT = int(os.getenv("CYCLE_CRAWL_LIMIT", "15"))
#: Step 3: Exa `numResults`.
CYCLE_SEARCH_RESULTS = int(os.getenv("CYCLE_SEARCH_RESULTS", "10"))
#: Step 1b: how many previous cycles' captures, and how far a capture may sit
#: from the date asked for before it describes a different cycle.
CYCLE_ARCHIVE_YEARS_BACK = int(os.getenv("CYCLE_ARCHIVE_YEARS_BACK", "2"))
CYCLE_ARCHIVE_SKEW_DAYS = int(os.getenv("CYCLE_ARCHIVE_SKEW_DAYS", "120"))
#: How many upcoming intakes each award is verified for.
CYCLE_TRACKED_INTAKES = int(os.getenv("CYCLE_TRACKED_INTAKES", "2"))
#: Cadence (spec 9.3): monthly; weekly in the two months before last cycle's
#: call and from one month before a projected opening; daily within 14 days of
#: a known deadline; a projection 45 days late with no call lapses.
CYCLE_CHECK_DAYS_DEFAULT = int(os.getenv("CYCLE_CHECK_DAYS_DEFAULT", "30"))
CYCLE_CHECK_DAYS_SEASON = int(os.getenv("CYCLE_CHECK_DAYS_SEASON", "7"))
CYCLE_CHECK_DAYS_DEADLINE = int(os.getenv("CYCLE_CHECK_DAYS_DEADLINE", "1"))
CYCLE_DEADLINE_WINDOW_DAYS = int(os.getenv("CYCLE_DEADLINE_WINDOW_DAYS", "14"))
CYCLE_SEASON_WINDOW_DAYS = int(os.getenv("CYCLE_SEASON_WINDOW_DAYS", "61"))
CYCLE_PROJECTION_LEAD_DAYS = int(os.getenv("CYCLE_PROJECTION_LEAD_DAYS", "30"))
CYCLE_PROJECTION_LAPSE_DAYS = int(os.getenv("CYCLE_PROJECTION_LAPSE_DAYS", "45"))
#: Cost ceilings. Per award: spec 9.3's upper estimate. Per run: what one
#: scheduled invocation may spend across every award it verifies.
CYCLE_VERIFY_MAX_USD_PER_AWARD = float(os.getenv("CYCLE_VERIFY_MAX_USD_PER_AWARD", "0.40"))
CYCLE_VERIFY_RUN_BUDGET_USD = float(os.getenv("CYCLE_VERIFY_RUN_BUDGET_USD", "10"))
CYCLE_RUN_CREDITS = {
    "FIRECRAWL": int(os.getenv("CYCLE_RUN_CREDITS_FIRECRAWL", "1000")),
    "SCRAPE_DO": int(os.getenv("CYCLE_RUN_CREDITS_SCRAPE_DO", "1000")),
}
#: The model-call circuit-breaker (CLAUDE.md "LLM/AI security"), per platform.
CYCLE_VERIFY_MODEL_CALLS_PER_HOUR = int(os.getenv("CYCLE_VERIFY_MODEL_CALLS_PER_HOUR", "600"))
#: Brave's list price, $5 per 1,000 requests (master spec 13).
BRAVE_USD_PER_REQUEST = float(os.getenv("BRAVE_USD_PER_REQUEST", "0.005"))
```

The model price table goes in with its consumer, in Task 4.

- [ ] **Step 6: Run the tests** — same command; expected: 9 passed.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check apps config tests scripts && uv run mypy apps config
git commit -m "feat(research): the cycle vocabulary as data, and the cycle-verification settings" -- \
  config/settings/base.py docs/research/cycle-vocabulary.csv apps/research/cycle_vocabulary.py \
  tests/research/test_cycle_vocabulary.py
```

---

### Task 2: `deadline_for` → the condition vocabulary, from data

§9.2: "`deadline_for` is recorded as written and normalised by a small mapper to `ALL`,
`NATIONALITY:<ISO2|region>`, `RESIDENCE:<…>`, `APPLICANT_CLASS: …`, `FUNDING: …`, `ROUTE: …`,
`ROUND:<n>`, anything unmapped kept as `OTHER:<text>` … (country and region names from Wikidata
labels — data, never a typed table)."

**Files:**
- Create: `docs/research/deadline-condition-terms.csv`
- Create: `apps/funding/deadline_conditions.py`
- Create: `apps/research/management/commands/refresh_country_labels.py`
- Create (generated in Step 6): `docs/research/country-labels.csv`
- Test: `tests/funding/test_deadline_conditions.py`, `tests/research/test_cycle_commands.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/funding/test_deadline_conditions.py
"""deadline_for as written -> the vocabulary validity.select_deadline reads."""
import datetime as dt

import pytest

from apps.funding.deadline_conditions import ConditionTerm, normalise_condition
from apps.funding.validity import Evidence, select_deadline

COUNTRIES = {
    "india": "IN", "indian": "IN", "türkiye": "TR", "turkey": "TR", "türkei": "TR",
    "pakistan": "PK", "guinea": "GN", "papua new guinea": "PG",
}
TERMS = (
    ConditionTerm(r"\bnon[- ]?eu\b", "APPLICANT_CLASS:NON_EU"),
    ConditionTerm(r"\beu\b", "NATIONALITY:EU"),
    ConditionTerm(r"\bself[- ]funded\b", "FUNDING:SELF_FUNDED"),
    ConditionTerm(r"\bnominat\w*", "ROUTE:NOMINATION"),
    ConditionTerm(r"\bround\s*(\d+)", "ROUND:{0}"),
    ConditionTerm(r"\bresiden(?:t|ts|ce)\b", "RESIDENCE:*"),
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ALL", "ALL"),
        ("", "ALL"),
        ("NATIONALITY:IN", "NATIONALITY:IN"),  # the judge may already write the form
        ("applicants from India", "NATIONALITY:IN"),
        ("Bewerber aus der Türkei", "NATIONALITY:TR"),
        ("applicants from India and Pakistan", "NATIONALITY:IN,PK"),
        ("citizens of Papua New Guinea", "NATIONALITY:PG"),  # longest label wins its span
        ("residents of Türkiye", "RESIDENCE:TR"),
        ("non-EU citizens", "APPLICANT_CLASS:NON_EU"),  # earliest match beats "eu"
        ("EU citizens", "NATIONALITY:EU"),
        ("self-funded students", "FUNDING:SELF_FUNDED"),
        ("nominating institutions", "ROUTE:NOMINATION"),
        ("round 2", "ROUND:2"),
        ("members of the Karajan-Akademie", "OTHER:members of the Karajan-Akademie"),
        ("residents", "OTHER:residents"),  # a residence phrase naming no place
    ],
)
def test_conditions_normalise_from_data_not_a_hand_table(text, expected):
    assert normalise_condition(text, countries=COUNTRIES, terms=TERMS) == expected


def test_a_normalised_nationality_is_what_select_deadline_matches():
    whose = normalise_condition("applicants from India", countries=COUNTRIES, terms=TERMS)
    evidence = Evidence(
        deadlines=((dt.date(2026, 10, 15), whose), (dt.date(2026, 12, 15), "ALL"))
    )
    chosen = select_deadline(evidence, {"nationality": "IN"})
    assert (chosen.date, chosen.condition) == (dt.date(2026, 10, 15), "NATIONALITY:IN")
```

- [ ] **Step 2: Run** `POSTGRES_DB=tehsil_verification_ladder uv run pytest tests/funding/test_deadline_conditions.py -q`
  Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write the data file** `docs/research/deadline-condition-terms.csv`. English only: these
  are the spec's own examples, and each other language is added with a source once the gate shows it
  missing.

```csv
language,pattern,condition,source,verified_on
en,\bnon[- ]?eu\b,APPLICANT_CLASS:NON_EU,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,\beu\b,NATIONALITY:EU,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,\binternational (?:students|applicants)\b,APPLICANT_CLASS:INTERNATIONAL,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,\bdomestic (?:students|applicants)\b,APPLICANT_CLASS:DOMESTIC,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,\bself[- ]funded\b,FUNDING:SELF_FUNDED,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,\bscholarship (?:applicants|candidates)\b,FUNDING:SCHOLARSHIP,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,\bnominat\w*,ROUTE:NOMINATION,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,\bdirect (?:applicants|applications)\b,ROUTE:DIRECT,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,\bround\s*(\d+),ROUND:{0},docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
en,\bresiden(?:t|ts|ce)\b,RESIDENCE:*,docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md#92,2026-09-22
```

`"EU"` maps to `NATIONALITY:EU` rather than `APPLICANT_CLASS:EU`. The eligibility vocabulary
already decides a region value through the sourced `REGIONS` table, while `APPLICANT_CLASS` is
plain equality against a key the student dict does not carry (see "Decision-side findings").

- [ ] **Step 4: Write the normaliser**

```python
# apps/funding/deadline_conditions.py
"""`deadline_for` as a page writes it -> the condition vocabulary (spec 9.2).

Pure. Both vocabularies are data: the phrase patterns in
docs/research/deadline-condition-terms.csv, the country names in
docs/research/country-labels.csv (Wikidata labels and demonyms, CC0,
regenerated by `manage.py refresh_country_labels`). Nothing unmapped is ever
guessed: it is `OTHER:<text>`, shown to the student as written.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from apps.funding.regions import REGIONS

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "research"
_NORMALISED = re.compile(
    r"(?:NATIONALITY|RESIDENCE|APPLICANT_CLASS|FUNDING|ROUTE|ROUND|DESCENT|OTHER):.+"
)
#: validity keeps a condition in a CharField-sized string; so do we.
_OTHER_MAX = 60


@dataclass(frozen=True)
class ConditionTerm:
    pattern: str
    condition: str
    regex: re.Pattern[str] = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "regex", re.compile(self.pattern, re.IGNORECASE))


@cache
def default_terms() -> tuple[ConditionTerm, ...]:
    with (_DOCS / "deadline-condition-terms.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if not (row["pattern"] and row["condition"] and row["source"] and row["verified_on"]):
            raise ValueError(f"deadline-condition-terms row is incomplete: {row}")
    return tuple(ConditionTerm(row["pattern"], row["condition"]) for row in rows)


@cache
def default_countries() -> dict[str, str]:
    with (_DOCS / "country-labels.csv").open(encoding="utf-8", newline="") as handle:
        return {row["label"].casefold(): row["iso2"].upper() for row in csv.DictReader(handle)}


def _countries_in(text: str, countries: Mapping[str, str]) -> list[str]:
    """ISO codes of every country the text names, in the order it names them.

    Longest label first, and a matched span is blanked before shorter labels
    are tried, so "Papua New Guinea" is never also "Guinea".
    """
    remaining = text.casefold()
    hits: list[tuple[int, str]] = []
    for label in sorted(countries, key=len, reverse=True):
        for match in re.finditer(rf"(?<!\w){re.escape(label)}(?!\w)", remaining):
            hits.append((match.start(), countries[label]))
            remaining = remaining[: match.start()] + " " * len(label) + remaining[match.end():]
    return list(dict.fromkeys(code for _start, code in sorted(hits)))


def _region_in(text: str) -> str:
    folded = text.casefold()
    for key, region in REGIONS.items():
        for name in (key, region.name):
            if re.search(rf"(?<!\w){re.escape(name.casefold())}(?!\w)", folded):
                return key
    return ""


def normalise_condition(
    text: str,
    *,
    countries: Mapping[str, str] | None = None,
    terms: Sequence[ConditionTerm] | None = None,
) -> str:
    raw = " ".join((text or "").split())
    if not raw or raw.upper() == "ALL":
        return "ALL"
    if _NORMALISED.fullmatch(raw):
        return raw
    countries = default_countries() if countries is None else countries
    terms = default_terms() if terms is None else terms

    prefix = "NATIONALITY"
    best: tuple[re.Match[str], ConditionTerm] | None = None
    for term in terms:
        match = term.regex.search(raw)
        if match and (
            best is None
            or (match.start(), -len(match.group())) < (best[0].start(), -len(best[0].group()))
        ):
            best = (match, term)
    if best is not None:
        match, term = best
        if term.condition == "RESIDENCE:*":
            prefix = "RESIDENCE"
        else:
            return term.condition.format(*match.groups())

    codes = _countries_in(raw, countries)
    if codes:
        return f"{prefix}:{','.join(codes)}"
    region = _region_in(raw)
    if region and prefix == "RESIDENCE":
        return f"RESIDENCE:{region}"
    return f"OTHER:{raw[:_OTHER_MAX]}"
```

A region in a *nationality* phrase is already caught by its CSV term (`\beu\b`). A region with no
term reaches `_region_in` only under a residence phrase. Every other region name stays `OTHER:` until
a term row with a source says what it means.

- [ ] **Step 5: Run** the test file. Expected: 16 passed.

- [ ] **Step 6: The label generator.** Write the test first, in `tests/research/test_cycle_commands.py`:

```python
import csv

from django.core.management import call_command

from apps.research.management.commands import refresh_country_labels as command


def test_country_labels_are_written_from_wikidata_rows(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, *, params, headers):
        calls.append((url, params, headers))
        return {"results": {"bindings": [
            {"code": {"value": "tr"}, "label": {"value": "Türkiye", "xml:lang": "tr"},
             "kind": {"value": "label"}},
            {"code": {"value": "IN"}, "label": {"value": "Indian", "xml:lang": "en"},
             "kind": {"value": "demonym"}},
        ]}}

    monkeypatch.setattr(command, "fetch_json_api", fake_get)
    out = tmp_path / "labels.csv"
    call_command("refresh_country_labels", "--out", str(out))

    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert {(r["label"], r["iso2"], r["kind"]) for r in rows} == {
        ("Türkiye", "TR", "label"), ("Indian", "IN", "demonym"),
    }
    assert all(r["source"] == command.SPARQL_URL and r["fetched_on"] for r in rows)
    assert calls[0][2]["User-Agent"].startswith("tehsil")
```

Then the command:

```python
# apps/research/management/commands/refresh_country_labels.py
"""Regenerate docs/research/country-labels.csv from Wikidata (CC0).

A contracted-API call through `egress.fetch_json_api` (master spec 7) -- a data
source, not a page, so never a fetch vendor. Run by hand when a language is
added to the truth set; commit the file it writes.
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.research.egress import fetch_json_api

SPARQL_URL = "https://query.wikidata.org/sparql"
#: The truth set's languages (master spec 9.3) plus English.
LANGUAGES = ("en", "de", "tr", "az", "fr", "nl", "sv", "hu", "it")
_QUERY = """
SELECT ?code ?label ?kind WHERE {{
  ?country wdt:P297 ?code .
  {{ ?country rdfs:label ?label . BIND("label" AS ?kind) }}
  UNION {{ ?country wdt:P1549 ?label . BIND("demonym" AS ?kind) }}
  FILTER(LANG(?label) IN ({languages}))
}}
"""


class Command(BaseCommand):
    help = "Write docs/research/country-labels.csv from Wikidata labels and demonyms."

    def add_arguments(self, parser):
        default = Path(__file__).resolve().parents[4] / "docs" / "research" / "country-labels.csv"
        parser.add_argument("--out", default=str(default))

    def handle(self, *args, **options):
        languages = ", ".join(f'"{language}"' for language in LANGUAGES)
        data = fetch_json_api(
            SPARQL_URL,
            params={"query": _QUERY.format(languages=languages), "format": "json"},
            headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": "tehsil-agent/1.0 (country-labels; contact via repository)",
            },
        )
        today = timezone.now().date().isoformat()
        rows = sorted(
            {
                (
                    binding["label"]["value"],
                    binding["code"]["value"].upper(),
                    binding["label"].get("xml:lang", ""),
                    binding["kind"]["value"],
                )
                for binding in data["results"]["bindings"]
                if len(binding["code"]["value"]) == 2
            }
        )
        with Path(options["out"]).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("label", "iso2", "language", "kind", "source", "fetched_on"))
            for label, code, language, kind in rows:
                writer.writerow((label, code, language, kind, SPARQL_URL, today))
        self.stdout.write(f"{len(rows)} labels -> {options['out']}")
```

Run the test (expected PASS). Then generate the committed file once, live:
`uv run python manage.py refresh_country_labels`. Expected output: `N labels -> …/country-labels.csv`
with N in the low thousands. Open the file and check that `Türkiye,TR`, `Deutschland,DE` and
`Azərbaycan,AZ` are present. If a label that is also a common word leaks in (a two-letter label, say),
delete that row by hand and say so in the commit message.

- [ ] **Step 7: Lint, type-check, commit**

```bash
git commit -m "feat(funding): normalise deadline_for to the condition vocabulary, from data" -- \
  docs/research/deadline-condition-terms.csv docs/research/country-labels.csv \
  apps/funding/deadline_conditions.py apps/research/management/commands/refresh_country_labels.py \
  tests/funding/test_deadline_conditions.py tests/research/test_cycle_commands.py
```

---

### Task 3: `FundingCycleVerification`, its RLS, and the isolation suite

**Shared catalog.** Whether an award's money is there for an intake is the same fact for every
tenant. The row describes a page and a scheme, never a person, and no column references a tenant
table. So: `ENABLE ROW LEVEL SECURITY`, `shared_catalog_select`, `catalog_ingestion_write`, and a
place in `_SHARED_TABLES` — the pattern of `funding/0030_program_awarding_institutions_rls.py`.

**Files:**
- Modify: `apps/funding/models.py` (after `FundingOpportunity`'s related models)
- Create: `apps/funding/migrations/<leaf+1>_cycle_verification.py` (generated), `<leaf+2>_cycle_verification_rls.py` (hand-written)
- Modify: `tests/tenancy/test_database_isolation.py`
- Test: `tests/funding/test_cycle_verification_rls.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/funding/test_cycle_verification_rls.py
"""RLS on FundingCycleVerification, verified through a role that cannot bypass it.

The write test grants INSERT first: an ungranted role is refused with the same
SQLSTATE a real policy raises, so only the message separates the two (the
negative control from test_site_job_record_rls.py).
"""
import psycopg
import pytest
from django.db import IntegrityError, connection
from psycopg import sql

from apps.funding.models import FundingCycleVerification, FundingOpportunity
from apps.tenancy.models import TenantScopedModel

pytestmark = pytest.mark.django_db
TABLE = "funding_fundingcycleverification"


def _opportunity():
    return FundingOpportunity.objects.create(
        canonical_key="read:test-award", name="Test Award", family="PRIVATE_FOUNDATION",
        scope_type="GLOBAL",
    )


@pytest.mark.django_db(transaction=True)
def test_a_verification_is_readable_by_every_tenant(runtime_connection):
    FundingCycleVerification.objects.create(opportunity=_opportunity(), intake_start_year=2027)
    with runtime_connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert cursor.fetchone()[0] == 1


@pytest.mark.django_db(transaction=True)
def test_a_runtime_role_cannot_write_one(runtime_connection):
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT INSERT ON TABLE {} TO {}").format(sql.Identifier("public", TABLE), role)
        )
    opportunity = _opportunity()
    with runtime_connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_table_privilege(%s, %s, 'INSERT')",
            [runtime_connection.info.user, f"public.{TABLE}"],
        )
        assert cursor.fetchone() == (True,), "grant did not take"
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(
                f"INSERT INTO {TABLE} (id, opportunity_id, intake_start_year, state, evidence, "
                "trail, cycles_observed, projection_lapsed, page_removed, ladder_step, cost_usd, "
                "cost_detail, cost_complete, created_at, updated_at) VALUES (gen_random_uuid(), "
                "%s, 2027, 'UNVERIFIED', '[]', '[]', '[]', false, false, '', 0, '{}', true, "
                "now(), now())",
                [opportunity.id],
            )
        assert "row-level security policy" in str(refused.value)


def test_one_row_per_award_per_intake():
    opportunity = _opportunity()
    FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    with pytest.raises(IntegrityError):
        FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)


def test_the_row_can_reach_no_person():
    """No FK to a tenant-scoped model: a shared row that could reach a student
    is a personal datum outside the erasure sweep (CLAUDE.md, derived data)."""
    for field in FundingCycleVerification._meta.get_fields():
        target = getattr(field, "related_model", None)
        if target is not None:
            assert not issubclass(target, TenantScopedModel), field.name
```

In `tests/tenancy/test_database_isolation.py`, append to `_SHARED_TABLES`:

```python
    # Cycle verification (funding engine item 11). Whether an award's money is
    # there for an intake is the same fact for every tenant; the row describes
    # a page and a scheme, never a person.
    "funding_fundingcycleverification",
```

- [ ] **Step 2: Run** `POSTGRES_DB=tehsil_verification_ladder uv run pytest tests/funding/test_cycle_verification_rls.py tests/tenancy/test_database_isolation.py -q`
  Expected: FAIL, `ImportError: cannot import name 'FundingCycleVerification'`.

- [ ] **Step 3: Add the model**

```python
class FundingCycleVerification(models.Model):
    """Is this award's money there for ONE intake, and on what evidence (spec 9.3).

    The decision is `validity.cycle_validity`, pure; this row is what it was
    fed, what it said, which rung of the evidence ladder settled it, and what
    that cost as the vendors billed it. Shared catalog, written by
    `catalog_ingestion` only (RLS in the migration beside this one).

    `evidence` is a list of `cycle_evidence.EvidenceEntry` dicts -- a quote,
    the URL we fetched it from, the digest of those bytes and the dates it
    states. A student is never in it and nothing here may point at one.
    """

    class State(models.TextChoices):
        OPEN = "OPEN"
        UPCOMING = "UPCOMING"
        CLOSED_FOR_INTAKE = "CLOSED_FOR_INTAKE"
        SUSPENDED = "SUSPENDED"
        ENDED = "ENDED"
        UNVERIFIED = "UNVERIFIED"

    class Step(models.TextChoices):
        NONE = "", "never run"
        OWN_PAGES = "0", "own pages already read"
        CRAWL = "1", "site crawl on the cycle vocabulary"
        WAYBACK = "1b", "Wayback captures of earlier cycles"
        CADENCE = "1c", "register cadence"
        HOP = "2", "one own-site hop"
        SEARCH = "3", "domain-restricted search"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    opportunity = models.ForeignKey(
        FundingOpportunity, on_delete=models.PROTECT, related_name="cycle_verifications"
    )
    intake_start_year = models.PositiveSmallIntegerField()
    state = models.CharField(max_length=20, choices=State.choices, default=State.UNVERIFIED)
    evidence = models.JSONField(default=list)
    #: Every past cycle the evidence shows: {"intake_year", "open", "deadline",
    #: "url", "captured_at"}. `open` is null when only a deadline was seen --
    #: such a cycle is not a "dated call" (plan decision 3).
    cycles_observed = models.JSONField(default=list)
    #: What was looked at and how it ended: {"step", "url", "outcome", "note"}.
    #: The Wayback lookups here are the "read once, cached for good" of 9.2.
    trail = models.JSONField(default=list)
    projected_open = models.DateField(null=True, blank=True)
    projected_deadline = models.DateField(null=True, blank=True)
    #: 45 days past a projected opening with no call: the projection is
    #: withheld from the evidence and the state degrades (spec 9.3).
    projection_lapsed = models.BooleanField(default=False)
    page_removed = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)
    ladder_step = models.CharField(max_length=2, choices=Step.choices, blank=True, default="")
    #: Recorded, never estimated: Firecrawl and scrape.do credits at plan rate,
    #: model tokens at list price, Exa `costDollars`, Brave requests at list.
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    cost_detail = models.JSONField(default=dict)
    #: False when some spend could not be priced (a model missing from
    #: MODEL_LIST_PRICES_USD_PER_MTOK, a call that raised before reporting
    #: usage). The number is then a floor, and says so.
    cost_complete = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("opportunity", "intake_start_year"), name="cycle_verification_intake_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[choice for choice, _label in State.choices]),
                name="cycle_verification_state_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(ladder_step__in=[choice for choice, _label in Step.choices]),
                name="cycle_verification_step_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(intake_start_year__gte=2000, intake_start_year__lte=2100),
                name="cycle_verification_intake_range",
            ),
        ]
        indexes = [models.Index(fields=("next_check_at",), name="cycle_verify_due_idx")]
```

(`State.choices` / `Step.choices` inside `Meta` are resolved at class-body time. If mypy or Django
complains, hoist them to module-level tuples, as `_HOLDER_VALUES` is.)

- [ ] **Step 4: Generate the table migration, then write the RLS one by hand**

```bash
ls apps/funding/migrations/ | tail -3        # take the real leaf
uv run python manage.py makemigrations funding -n cycle_verification
```

```python
# apps/funding/migrations/<leaf+2>_cycle_verification_rls.py
# funding_fundingcycleverification joins _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py): whether an award's money is there
# for an intake is the same fact for every tenant, and the row carries no
# person. Both policies from the start, as 0030 has them. Verified through
# runtime_connection -- the test role bypasses RLS (CLAUDE.md).
from django.db import migrations

TABLE = "funding_fundingcycleverification"

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


class Migration(migrations.Migration):
    dependencies = [("funding", "<leaf+1>_cycle_verification")]
    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
```

Replace `<leaf+1>_cycle_verification` with the file name Step 4's `makemigrations` actually wrote.
That is the only substitution in this plan, and it cannot be known before running.

- [ ] **Step 5: Run** Step 2's command. Expected: every test passes, including
  `test_task7_rls_policy_shapes_and_runtime_acl`, which now also checks this table's policy shape
  and ACL.

- [ ] **Step 6: Lint, type-check, `makemigrations --check`, commit**

```bash
git commit -m "feat(funding): FundingCycleVerification, shared catalog, RLS from the start" -- \
  apps/funding/models.py apps/funding/migrations/ tests/funding/test_cycle_verification_rls.py \
  tests/tenancy/test_database_isolation.py
```

---

### Task 4: Metering — cost recorded as billed, never estimated

**Files:**
- Modify: `config/settings/base.py`
- Create: `apps/research/metering.py`
- Test: `tests/research/test_metering.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/test_metering.py
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.research.fetch import SweepBudget
from apps.research.metering import Meter, MeteredMessages, MeteredResponses

PRICES = {"gpt-x": {"input": 1.0, "output": 4.0, "cache_read": 0.1},
          "claude-y": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75}}


def _meter(settings):
    settings.MODEL_LIST_PRICES_USD_PER_MTOK = PRICES
    run = SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})
    return run, Meter(run)


class _Parser:
    def __init__(self, usage):
        self.usage = usage

    def parse(self, **kwargs):
        return SimpleNamespace(usage=self.usage)


def test_openai_cached_tokens_are_priced_as_cache_reads_not_twice(settings):
    _run, meter = _meter(settings)
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=0,
                            input_tokens_details=SimpleNamespace(cached_tokens=400_000))
    MeteredResponses(_Parser(usage), meter).parse(model="gpt-x")
    usd, detail, complete = meter.total()
    # 600k uncached at $1 + 400k cached at $0.10
    assert usd == Decimal("0.640000") and complete
    assert detail["tokens"]["gpt-x"]["cache_read_input_tokens"] == 400_000


def test_anthropic_usage_is_read_as_reported(settings):
    _run, meter = _meter(settings)
    usage = SimpleNamespace(input_tokens=100_000, output_tokens=10_000,
                            cache_read_input_tokens=0, cache_creation_input_tokens=0)
    MeteredMessages(_Parser(usage), meter).parse(model="claude-y")
    assert meter.total()[0] == Decimal("0.450000")


def test_a_model_with_no_list_price_makes_the_cost_a_floor_never_a_guess(settings):
    _run, meter = _meter(settings)
    usage = SimpleNamespace(input_tokens=10, output_tokens=10)
    MeteredResponses(_Parser(usage), meter).parse(model="unpriced-model")
    usd, detail, complete = meter.total()
    assert usd == Decimal("0") and complete is False
    assert detail["unpriced"] == ["unpriced-model"]


def test_a_call_that_raises_is_counted_unmetered(settings):
    _run, meter = _meter(settings)

    class Boom:
        def parse(self, **kwargs):
            raise ValueError("off schema")

    with pytest.raises(ValueError):
        MeteredResponses(Boom(), meter).parse(model="gpt-x")
    assert meter.total()[2] is False


def test_fetch_cost_is_the_run_budgets_delta_since_this_award_began(settings):
    run, _ = _meter(settings)
    run.spend("FIRECRAWL", 50)          # an earlier award in the same run
    meter = Meter(run)
    run.spend("FIRECRAWL", 12)
    run.spend("SCRAPE_DO", 25)
    _usd, detail, _ = meter.total()
    assert detail["credits"] == {"FIRECRAWL": 12, "SCRAPE_DO": 25}


def test_search_spend_is_added_as_the_provider_reported_it(settings):
    _run, meter = _meter(settings)
    meter.add_search("exa", 0.0097)
    assert meter.total()[0] == Decimal("0.009700")
```

- [ ] **Step 2: Run** — expected FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Add the price table** to the Task 1 settings block:

```python
#: USD per million tokens at LIST price, by model, per token class --
#: "input" (uncached input), "output", "cache_read", "cache_write". Filled from
#: the vendors' own pricing pages on the date below; a model or class missing
#: here leaves a verification's `cost_complete` False rather than a guessed
#: price (plan decision 5). Env override: a JSON object of the same shape.
MODEL_LIST_PRICES_USD_PER_MTOK: dict[str, dict[str, float]] = json.loads(
    os.getenv("MODEL_LIST_PRICES_USD_PER_MTOK", "null") or "null"
) or {
    OPENAI_EXTRACTION_MODEL: {"input": ..., "output": ..., "cache_read": ...},
    ANTHROPIC_JUDGE_MODEL: {"input": ..., "output": ..., "cache_read": ..., "cache_write": ...},
}
MODEL_LIST_PRICES_SOURCE = (
    "https://openai.com/api/pricing/ ; https://www.anthropic.com/pricing#api"
)
MODEL_LIST_PRICES_VERIFIED_ON = "<the date you read them>"
```

**This step is a measurement, not a placeholder.** Open both pricing pages on the day you execute
this task. Write the four numbers for the two models the settings name, and the date you read them.
Do not copy numbers from this plan, from memory or from another repository — the whole point of the
setting is that the number has a source and a date. Add `import json` at the top of `base.py` if it
is not already imported.

- [ ] **Step 4: Write the meter**

```python
# apps/research/metering.py
"""What one cycle verification spent, as the vendors billed it (spec 9.3).

Three sources, none estimated:
- fetch: the run's `SweepBudget`, which every `fetch_page` call spends against
  -- this award's share is the delta since it began;
- models: token counts read off each response, priced at the sourced list
  price in settings;
- search: the provider's own figure (`SiteSearchResult.cost_usd`).

The two client wrappers exist so `funding_judge` needs no change: the reader
keeps calling `.parse(...)`, and the wrapper reads `.usage` on the way back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.conf import settings

from apps.research.fetch import USD_PER_CREDIT, SweepBudget

_CLASSES = ("input", "output", "cache_read", "cache_write")
_FIELD = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_input_tokens",
    "cache_write": "cache_creation_input_tokens",
}


@dataclass
class Meter:
    run: SweepBudget
    tokens: dict[str, dict[str, int]] = field(default_factory=dict)
    search_usd: float = 0.0
    searches: dict[str, int] = field(default_factory=dict)
    unmetered_calls: int = 0
    _start: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        self._start = dict(self.run.spent)

    def add_tokens(self, model: str, counts: dict[str, int]) -> None:
        bucket = self.tokens.setdefault(model, dict.fromkeys(_FIELD.values(), 0))
        for name, value in counts.items():
            bucket[name] = bucket.get(name, 0) + value

    def add_search(self, provider: str, usd: float) -> None:
        self.search_usd += usd
        self.searches[provider] = self.searches.get(provider, 0) + 1

    def credits(self) -> dict[str, int]:
        return {vendor: self.run.spent[vendor] - self._start.get(vendor, 0) for vendor in self.run.spent}

    def total(self) -> tuple[Decimal, dict[str, Any], bool]:
        credits = self.credits()
        fetch_usd = sum(USD_PER_CREDIT[vendor] * n for vendor, n in credits.items())
        prices = settings.MODEL_LIST_PRICES_USD_PER_MTOK
        model_usd = 0.0
        unpriced: list[str] = []
        for model, counts in self.tokens.items():
            price = prices.get(model)
            used = [cls for cls in _CLASSES if counts.get(_FIELD[cls], 0)]
            if price is None or any(cls not in price for cls in used):
                unpriced.append(model)
                continue
            model_usd += sum(counts[_FIELD[cls]] * price[cls] for cls in used) / 1_000_000
        usd = Decimal(str(round(fetch_usd + model_usd + self.search_usd, 6))).quantize(
            Decimal("0.000001")
        )
        detail = {
            "credits": credits,
            "fetch_usd": round(fetch_usd, 6),
            "tokens": self.tokens,
            "model_usd": round(model_usd, 6),
            "search_usd": round(self.search_usd, 6),
            "searches": self.searches,
            "unpriced": sorted(unpriced),
            "unmetered_calls": self.unmetered_calls,
            "prices_verified_on": settings.MODEL_LIST_PRICES_VERIFIED_ON,
        }
        return usd, detail, not unpriced and not self.unmetered_calls


class _Metered:
    def __init__(self, inner: Any, meter: Meter) -> None:
        self._inner = inner
        self._meter = meter

    def parse(self, **kwargs: object) -> object:
        try:
            response = self._inner.parse(**kwargs)
        except Exception:
            # Billed or not, the usage never reached us: the total is a floor.
            self._meter.unmetered_calls += 1
            raise
        self._meter.add_tokens(str(kwargs.get("model", "")), self._counts(response))
        return response

    def _counts(self, response: object) -> dict[str, int]:
        raise NotImplementedError


class MeteredResponses(_Metered):
    """OpenAI: `input_tokens` INCLUDES the cached ones, so they are split out."""

    def _counts(self, response: object) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        total_in = getattr(usage, "input_tokens", 0) or 0
        cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0
        return {
            "input_tokens": total_in - cached,
            "cache_read_input_tokens": cached,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        }


class MeteredMessages(_Metered):
    """Anthropic: cache reads and writes are reported beside `input_tokens`."""

    def _counts(self, response: object) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        return {name: getattr(usage, name, 0) or 0 for name in _FIELD.values()}
```

- [ ] **Step 5: Run** — expected: 6 passed.
- [ ] **Step 6: Lint, type-check, commit**

```bash
git commit -m "feat(research): meter a verification's spend as billed -- credits, tokens, search" -- \
  config/settings/base.py apps/research/metering.py tests/research/test_metering.py
```

---

### Task 5: Pure evidence and schedule — `cycle_evidence.py`, `cycle_schedule.py`

Both live in `apps/funding`. `facts.award_facts` (Task 14) needs `to_evidence`, and funding never
imports research (CLAUDE.md, `SiteJobRecord`'s docstring).

**Files:**
- Modify: `apps/funding/validity.py` (two public names, nothing else)
- Create: `apps/funding/cycle_evidence.py`, `apps/funding/cycle_schedule.py`
- Test: `tests/funding/test_cycle_evidence.py`, `tests/funding/test_cycle_schedule.py`

- [ ] **Step 1: Write the failing tests.** The known-answer rows of §9.3 go here as data.

```python
# tests/funding/test_cycle_evidence.py
"""Stored evidence -> validity.Evidence. One known-answer row per state (spec 9.3)."""
import datetime as dt

from apps.funding.cycle_evidence import deadline_student, observations, past_calls, to_evidence
from apps.funding.validity import RegisterCadence, cycle_validity

TODAY = dt.date(2026, 9, 26)


def _entry(**overrides):
    entry = {
        "step": "0", "url": "https://funder.example/award", "sha256": "a" * 64,
        "at": "2026-09-20", "archived": False, "captured_at": "", "offered": "YES",
        "applies_to": "UNSTATED", "intake_year": None, "stated_on": None,
        "deadlines": [], "quote": "The Example Award funds master's study.",
    }
    entry.update(overrides)
    return entry


def _state(entries, intake, **kwargs):
    evidence = to_evidence(entries, target_year=intake, cadence=kwargs.pop("cadence", None),
                           page_removed=False, lapsed=kwargs.pop("lapsed", False))
    return cycle_validity(evidence, student=kwargs.pop("student", {}),
                          target_intake=str(intake), today=kwargs.pop("today", TODAY))


def test_suspended_the_chemoinformatics_shape():
    """A dated disclaimer naming the intake beats an undated 'about 20 each year'."""
    entries = [
        _entry(quote="about 20 Erasmus Mundus scholarships"),
        _entry(offered="NO", applies_to="2026-2028", intake_year=2026, stated_on="2025-10-15",
               quote="the 2026-2028 intake will be without scholarship"),
    ]
    assert _state(entries, 2026, today=dt.date(2025, 11, 1)) == "SUSPENDED"


def test_upcoming_a_march_may_scheme_in_september_with_two_past_calls():
    entries = [
        _entry(stated_on="2026-03-03", deadlines=[["2026-05-15", "ALL", "ALL"]]),
        _entry(archived=True, captured_at="2025-04-01", stated_on="2025-03-04",
               deadlines=[["2025-05-16", "ALL", "ALL"]]),
    ]
    assert _state(entries, 2027) == "UPCOMING"


def test_unverified_a_first_year_scheme():
    entries = [_entry(stated_on="2026-03-03", deadlines=[["2026-05-15", "ALL", "ALL"]])]
    assert _state(entries, 2027) == "UNVERIFIED"


def test_last_cycles_deadline_is_an_observation_not_this_intakes_deadline():
    """An undated line 'Deadline: 15 January 2026' says nothing about 2027 --
    read as 2027's deadline it would close an award that has not opened."""
    entries = [_entry(deadlines=[["2026-01-15", "ALL", "ALL"]])]
    evidence = to_evidence(entries, target_year=2027, cadence=None, page_removed=False,
                           lapsed=False)
    assert evidence.deadlines == ()
    assert [o["intake_year"] for o in observations(entries)] == [2026]


def test_a_cycle_seen_only_by_its_deadline_is_observed_but_not_a_dated_call():
    entries = [_entry(deadlines=[["2025-05-16", "ALL", "ALL"]]),
               _entry(deadlines=[["2026-05-15", "ALL", "ALL"]])]
    assert past_calls(observations(entries), before=2027) == ()


def test_a_lapsed_projection_is_withheld_so_validity_says_unverified():
    entries = [
        _entry(stated_on="2026-03-03", deadlines=[["2026-05-15", "ALL", "ALL"]]),
        _entry(archived=True, stated_on="2025-03-04", deadlines=[["2025-05-16", "ALL", "ALL"]]),
    ]
    cadence = RegisterCadence(open_month=3, deadline_month=5, source="https://r.example",
                              verified_for_cycle=2026)
    assert _state(entries, 2027, cadence=cadence, lapsed=True) == "UNVERIFIED"


def test_the_students_own_deadline_survives_the_round_trip():
    entries = [_entry(deadlines=[["2026-10-15", "applicants from India", "NATIONALITY:IN"],
                                 ["2026-12-15", "ALL", "ALL"]])]
    assert _state(entries, 2027, student={"nationality": "IN"},
                  today=dt.date(2026, 11, 1)) == "CLOSED_FOR_INTAKE"
    assert _state(entries, 2027, student={"nationality": "TR"},
                  today=dt.date(2026, 11, 1)) == "OPEN"


def test_deadline_student_carries_the_eu_class_from_the_sourced_region():
    assert deadline_student("DE", "DE")["applicant_class"] == "EU"
    assert deadline_student("AZ", "TR")["applicant_class"] == "NON_EU"
    assert deadline_student("", "")["applicant_class"] == ""
```

```python
# tests/funding/test_cycle_schedule.py
import datetime as dt

from apps.funding.cycle_schedule import next_check, projection_lapsed, tracked_intakes

TODAY = dt.date(2026, 9, 26)


def test_tracked_intakes_are_the_next_two_that_have_not_started():
    assert tracked_intakes(dt.date(2026, 8, 31)) == (2026, 2027)
    assert tracked_intakes(TODAY) == (2027, 2028)


def test_monthly_by_default():
    assert next_check(today=TODAY, deadlines=(), last_call_open=None,
                      projected_open=None) == TODAY + dt.timedelta(days=30)


def test_daily_within_fourteen_days_of_a_known_deadline():
    assert next_check(today=TODAY, deadlines=(dt.date(2026, 10, 5),), last_call_open=None,
                      projected_open=None) == TODAY + dt.timedelta(days=1)


def test_weekly_in_the_two_months_before_last_cycles_call_date():
    assert next_check(today=TODAY, deadlines=(), last_call_open=dt.date(2025, 11, 10),
                      projected_open=None) == TODAY + dt.timedelta(days=7)


def test_weekly_from_one_month_before_a_projected_opening():
    assert next_check(today=TODAY, deadlines=(), last_call_open=None,
                      projected_open=dt.date(2026, 10, 20)) == TODAY + dt.timedelta(days=7)


def test_a_projection_lapses_45_days_late_with_no_call():
    assert projection_lapsed(dt.date(2026, 8, 1), today=TODAY, call_seen=False) is True
    assert projection_lapsed(dt.date(2026, 8, 15), today=TODAY, call_seen=False) is False
    assert projection_lapsed(dt.date(2026, 8, 1), today=TODAY, call_seen=True) is False
```

- [ ] **Step 2: Run** both files. Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Two public names in `validity.py`, appended at the end of the module**

```python
#: Public for the evidence side (apps/funding/cycle_evidence.py), which must
#: put a deadline in the same intake window this module compares against.
ASSUMED_INTAKE_START = _ASSUMED_INTAKE_START


def projected_window(
    evidence: Evidence, *, target_intake: str, today: dt.date,
    intake_starts_on: dt.date | None = None,
) -> tuple[dt.date, dt.date | None] | None:
    """The window `cycle_validity` projected, for display and scheduling only.

    A read-only view of `_projection`: it decides nothing and changes nothing
    `cycle_validity` returns.
    """
    target = intake_start_year(target_intake)
    start = _intake_start(target_intake, intake_starts_on)
    if target is None or start is None:
        return None
    return _projection(evidence, target_year=target, start=start, today=today)
```

- [ ] **Step 4: Write `cycle_evidence.py`**

```python
# apps/funding/cycle_evidence.py
"""Stored cycle evidence -> `validity.Evidence`. Pure; the decision is validity's.

An `EvidenceEntry` is one award decision read off one page: the quote, where we
fetched it (URL, digest, date; `captured_at` for a Wayback capture), and the
dates it states. Entries are facts about pages, not about intakes, so one list
serves every intake; `to_evidence` picks what speaks to the target.

Two rules here are the evidence side's own, and each closes a way the pure
function would otherwise be fed a wrong fact:

- A deadline belongs to the intake whose window it falls in -- (start - 365
  days, start] -- never to "whatever intake is asked about". An undated line
  "Deadline: 15 January 2026" is last cycle's deadline when 2027 is asked.
- A past cycle is a DATED CALL (`past_calls`) only when a line of that cycle
  carried a date of its own. A cycle seen only by its deadline is observed and
  counted, never given an invented opening (plan decision 3).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from typing import Any, TypedDict

from apps.funding.regions import REGIONS
from apps.funding.validity import ASSUMED_INTAKE_START, Evidence, RegisterCadence


class EvidenceEntry(TypedDict):
    step: str
    url: str
    sha256: str
    at: str
    archived: bool
    captured_at: str
    offered: str
    applies_to: str
    intake_year: int | None
    stated_on: str | None
    #: [[iso date, as written, normalised condition], ...]
    deadlines: list[list[str]]
    quote: str


def _date(value: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def intake_start(year: int) -> dt.date:
    month, day = ASSUMED_INTAKE_START
    return dt.date(year, month, day)


def intake_of(date: dt.date) -> int:
    """The intake whose window (previous start, start] contains `date`."""
    return date.year if date <= intake_start(date.year) else date.year + 1


def observations(entries: Iterable[EvidenceEntry] | Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every cycle the YES entries show, one row per (intake, deadline)."""
    seen: dict[tuple[int, str], dict[str, Any]] = {}
    for entry in entries:
        if entry["offered"] != "YES":
            continue
        opened = _date(entry["stated_on"])
        for iso, _raw, _condition in entry["deadlines"]:
            deadline = _date(iso)
            if deadline is None:
                continue
            year = intake_of(deadline)
            # An opening counts only when it precedes its own deadline by less
            # than a year: a page's "updated" stamp after the deadline is not
            # when the call opened.
            dated = opened if opened and deadline - dt.timedelta(days=365) < opened <= deadline else None
            key = (year, iso)
            current = seen.get(key)
            if current is None or (dated and (current["open"] is None or dated.isoformat() < current["open"])):
                seen[key] = {"intake_year": year, "open": dated.isoformat() if dated else None,
                             "deadline": iso, "url": entry["url"], "captured_at": entry["captured_at"]}
        if not entry["deadlines"] and opened and entry["intake_year"]:
            key = (entry["intake_year"], "")
            seen.setdefault(key, {"intake_year": entry["intake_year"], "open": opened.isoformat(),
                                  "deadline": None, "url": entry["url"],
                                  "captured_at": entry["captured_at"]})
    return sorted(seen.values(), key=lambda row: (row["intake_year"], row["deadline"] or ""))


def past_calls(
    observed: Sequence[dict[str, Any]], *, before: int
) -> tuple[tuple[dt.date, dt.date | None], ...]:
    """Dated calls of intakes before `before`, earliest opening per intake."""
    by_year: dict[int, tuple[dt.date, dt.date | None]] = {}
    for row in observed:
        opened = _date(row["open"])
        if opened is None or row["intake_year"] >= before:
            continue
        pair = (opened, _date(row["deadline"]))
        if row["intake_year"] not in by_year or pair[0] < by_year[row["intake_year"]][0]:
            by_year[row["intake_year"]] = pair
    return tuple(by_year[year] for year in sorted(by_year, reverse=True))


def _rank(entry: EvidenceEntry, target: int) -> tuple[bool, bool, str]:
    return (entry["intake_year"] == target, entry["stated_on"] is not None, entry["stated_on"] or "")


def to_evidence(
    entries: Sequence[EvidenceEntry],
    *,
    target_year: int,
    cadence: RegisterCadence | None,
    page_removed: bool,
    lapsed: bool,
) -> Evidence:
    start = intake_start(target_year)
    low = start - dt.timedelta(days=365)
    relevant = [
        e for e in entries
        if e["intake_year"] == target_year or (e["intake_year"] is None and not e["archived"])
    ]
    yes = [e for e in relevant if e["offered"] == "YES"]
    no = [e for e in relevant if e["offered"] == "NO"]
    offered, best = "YES", None
    # Across pages as within one (spec 9.2): the more specific statement wins
    # for this intake -- naming it, then dated, then the later date. A tie
    # goes to the NO: hiding an open award costs a student one option,
    # showing a closed one costs them an application.
    if no and (not yes or _rank(max(no, key=lambda e: _rank(e, target_year)), target_year)
               >= _rank(max(yes, key=lambda e: _rank(e, target_year)), target_year)):
        offered, best = "NO", max(no, key=lambda e: _rank(e, target_year))
    elif yes:
        best = max(yes, key=lambda e: _rank(e, target_year))
    deadlines = tuple(
        dict.fromkeys(
            (date, condition)
            for e in yes
            for iso, _raw, condition in e["deadlines"]
            if (date := _date(iso)) is not None and low < date <= start
        )
    )
    observed = observations(entries)
    return Evidence(
        offered=offered,
        applies_to=str(target_year) if best and best["intake_year"] == target_year else "UNSTATED",
        stated_on=_date(best["stated_on"]) if best else None,
        deadlines=deadlines,
        past_calls=() if lapsed else past_calls(observed, before=target_year),
        register_cadence=None if lapsed else cadence,
        page_removed=page_removed,
        cycles_observed=tuple(str(row["intake_year"]) for row in observed),
    )


def deadline_student(nationality: str, country_of_residence: str) -> dict[str, object]:
    """The student keys `validity.select_deadline` reads, from a profile's own answers.

    `applicant_class` is derived from the sourced EU membership in `REGIONS`,
    because a page's "non-EU applicants" deadline is otherwise matched by
    nobody (plan, decision-side findings). Blank when nationality is unknown --
    an unknown class matches no class, which is right.
    """
    code = (nationality or "").upper()
    klass = "" if not code else ("EU" if code in REGIONS["EU"].countries else "NON_EU")
    return {
        "nationality": code,
        "country_of_residence": (country_of_residence or "").upper(),
        "applicant_class": klass,
    }
```

- [ ] **Step 5: Write `cycle_schedule.py`**

```python
# apps/funding/cycle_schedule.py
"""When to look again, which intakes to watch, and when a projection lapses (spec 9.3). Pure."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from django.conf import settings

from apps.funding.cycle_evidence import intake_start


def tracked_intakes(today: dt.date) -> tuple[int, ...]:
    """The next CYCLE_TRACKED_INTAKES intakes that have not started."""
    first = today.year if today < intake_start(today.year) else today.year + 1
    return tuple(first + n for n in range(settings.CYCLE_TRACKED_INTAKES))


def _next_anniversary(value: dt.date, today: dt.date) -> dt.date:
    for year in (today.year, today.year + 1):
        try:
            candidate = value.replace(year=year)
        except ValueError:  # 29 February
            candidate = value.replace(year=year, day=28)
        if candidate >= today:
            return candidate
    return value


def next_check(
    *,
    today: dt.date,
    deadlines: Iterable[dt.date],
    last_call_open: dt.date | None,
    projected_open: dt.date | None,
) -> dt.date:
    days = dt.timedelta
    ahead = [d for d in deadlines if d >= today]
    if ahead and min(ahead) - today <= days(settings.CYCLE_DEADLINE_WINDOW_DAYS):
        return today + days(settings.CYCLE_CHECK_DAYS_DEADLINE)
    if projected_open is not None and (
        projected_open - days(settings.CYCLE_PROJECTION_LEAD_DAYS)
        <= today
        <= projected_open + days(settings.CYCLE_PROJECTION_LAPSE_DAYS)
    ):
        return today + days(settings.CYCLE_CHECK_DAYS_SEASON)
    if last_call_open is not None and (
        _next_anniversary(last_call_open, today) - today <= days(settings.CYCLE_SEASON_WINDOW_DAYS)
    ):
        return today + days(settings.CYCLE_CHECK_DAYS_SEASON)
    return today + days(settings.CYCLE_CHECK_DAYS_DEFAULT)


def projection_lapsed(projected_open: dt.date | None, *, today: dt.date, call_seen: bool) -> bool:
    if projected_open is None or call_seen:
        return False
    return today > projected_open + dt.timedelta(days=settings.CYCLE_PROJECTION_LAPSE_DAYS)
```

- [ ] **Step 6: Run** both new test files **and** `tests/funding/test_validity.py` (it must pass
  unmodified). Expected: all pass.

- [ ] **Step 7: Lint, type-check, commit**

```bash
git commit -m "feat(funding): stored cycle evidence to validity.Evidence, and the 9.3 schedule -- pure" -- \
  apps/funding/validity.py apps/funding/cycle_evidence.py apps/funding/cycle_schedule.py \
  tests/funding/test_cycle_evidence.py tests/funding/test_cycle_schedule.py
```

---

### Task 6: Step 0 is stored — the reader's writers record what they already read

**Files:**
- Create: `apps/research/cycle_verification.py` (first part: `entries_from_decision`, `record_read_evidence`)
- Modify: `apps/research/funding_reader.py`
- Test: `tests/research/test_cycle_verification.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/test_cycle_verification.py
import datetime as dt
from dataclasses import replace

import pytest

from apps.funding.models import FundingCycleVerification, FundingOpportunity
from apps.research.cycle_verification import entries_from_decision, record_read_evidence
from apps.research.funding_judge import FundingDecision

pytestmark = pytest.mark.django_db
TODAY = dt.date(2026, 9, 26)


def _decision(**overrides):
    base = FundingDecision(
        kind="I0_HOLDER_AWARD", scope="HOLDER_OWN", offered="YES",
        internationals_included="YES", nationality_shape="ANY", route="STUDENT_APPLIES",
        money_form="GRANT", holder="PRIVATE_FOUNDATION", tuition="FULL", living="FULL",
        extras=(), obligation=(), agreement="AGREED",
        quotes=("The Example Fellowship funds master's study.",), name="Example Fellowship",
        disputed=(), heading="Example Fellowship",
    )
    return replace(base, **overrides)


def _opportunity():
    return FundingOpportunity.objects.create(
        canonical_key="read:example", name="Example Fellowship", family="PRIVATE_FOUNDATION",
        scope_type="GLOBAL", agreement="AGREED",
    )


def test_an_entry_carries_the_quote_the_digest_and_the_normalised_deadline():
    decision = _decision(applies_to="2027-2028", stated_on="2026-09-01",
                         deadlines=(("2026-11-30", "applicants from India"),))
    [entry] = entries_from_decision(decision, step="0", url="https://f.example/a",
                                    sha256="b" * 64, at=TODAY)
    assert entry["intake_year"] == 2027
    assert entry["deadlines"] == [["2026-11-30", "applicants from India", "NATIONALITY:IN"]]
    assert entry["quote"].startswith("The Example Fellowship")


def test_the_writer_records_every_intakes_decision_on_every_tracked_row():
    opportunity = _opportunity()
    for decision in (
        _decision(applies_to="2027-2028", deadlines=(("2027-01-15", "ALL"),)),
        _decision(offered="NO", applies_to="2028-2030", stated_on="2026-09-01",
                  suspension_quote="no scholarships for the 2028 intake"),
    ):
        record_read_evidence(opportunity, decision, url="https://f.example/a",
                             sha256="c" * 64, at=TODAY, today=TODAY)
    rows = {r.intake_start_year: r for r in FundingCycleVerification.objects.all()}
    assert set(rows) == {2027, 2028}
    assert rows[2027].state == "OPEN"
    assert rows[2028].state == "SUSPENDED"
    assert all(len(r.evidence) == 2 for r in rows.values())
    # The first ladder run is due at once: a row nobody schedules is never verified.
    assert all(r.next_check_at is not None for r in rows.values())


def test_a_changed_page_replaces_its_own_old_entries_but_keeps_archive_captures():
    opportunity = _opportunity()
    record_read_evidence(opportunity, _decision(deadlines=(("2027-01-15", "ALL"),)),
                         url="https://f.example/a", sha256="d" * 64, at=TODAY, today=TODAY)
    row = FundingCycleVerification.objects.get(intake_start_year=2027)
    row.evidence.append({**row.evidence[0], "archived": True, "sha256": "e" * 64,
                         "captured_at": "2025-04-01"})
    row.save()
    record_read_evidence(opportunity, _decision(deadlines=(("2027-02-01", "ALL"),)),
                         url="https://f.example/a", sha256="f" * 64, at=TODAY, today=TODAY)
    row.refresh_from_db()
    assert {e["sha256"] for e in row.evidence} == {"e" * 64, "f" * 64}
```

- [ ] **Step 2: Run** — expected FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write the first part of `cycle_verification.py`**

```python
# apps/research/cycle_verification.py
"""Cycle verification: the evidence ladder of master spec 9.2, per (award, intake).

The DECISION is `apps.funding.validity.cycle_validity` -- pure, model-free and
not edited here. This module only gathers what it decides on, cheapest first,
and stops as soon as the answer is not UNVERIFIED:

    0  the award's own pages, already read (their dates were stored by the
       reader's writer) and re-checked through changeTracking
    1  a site crawl on the cycle vocabulary, limit 15
    1b Wayback captures of the call page from the previous two cycles
    1c the register's cadence row
    2  one hop from an own page to an apply link ON THE ORGANISATION'S OWN
       DOMAINS (plan decision 1: never a portal, never another host)
    3  one Exa search restricted to the registrable domain; Brave `site:` only
       when Exa returns nothing

What each step costs is recorded as billed (`metering.Meter`). What it looked
at is the row's `trail`, so "not found" always says what was searched.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.funding.cycle_evidence import EvidenceEntry, to_evidence
from apps.funding.cycle_schedule import tracked_intakes
from apps.funding.deadline_conditions import normalise_condition
from apps.funding.models import FundingCycleVerification, FundingOpportunity
from apps.funding.validity import cycle_validity, intake_start_year
from apps.research.funding_judge import FundingDecision


def _iso(value: str) -> str | None:
    try:
        return dt.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return None


def entries_from_decision(
    decision: FundingDecision,
    *,
    step: str,
    url: str,
    sha256: str,
    at: dt.date,
    captured_at: str = "",
) -> list[EvidenceEntry]:
    return [
        EvidenceEntry(
            step=step,
            url=url,
            sha256=sha256,
            at=at.isoformat(),
            archived=bool(captured_at),
            captured_at=captured_at,
            offered=decision.offered,
            applies_to=decision.applies_to,
            intake_year=intake_start_year(decision.applies_to),
            stated_on=_iso(decision.stated_on),
            deadlines=[
                [iso, whose, normalise_condition(whose)]
                for date, whose in decision.deadlines
                if (iso := _iso(date)) is not None
            ],
            quote=(decision.suspension_quote or " / ".join(decision.quotes))[:600],
        )
    ]


def _merge(existing: list[dict[str, Any]], new: list[EvidenceEntry]) -> list[dict[str, Any]]:
    """A re-read of a URL supersedes that URL's live entries; captures stay."""
    replaced = {(e["url"]) for e in new if not e["archived"]}
    new_shas = {e["sha256"] for e in new}
    kept = [
        e for e in existing
        if e["archived"] or e["url"] not in replaced or e["sha256"] in new_shas
    ]
    seen = {_key(e) for e in kept}
    return kept + [e for e in new if _key(e) not in seen]


def _key(entry: dict[str, Any]) -> tuple[Any, ...]:
    return (entry["url"], entry["sha256"], entry["quote"], entry["offered"], entry["applies_to"],
            str(entry["deadlines"]))


def _cadence(opportunity: FundingOpportunity):
    from apps.funding.validity import RegisterCadence

    org = opportunity.organisation
    if org is None or None in (org.cadence_open_month, org.cadence_deadline_month,
                               org.cadence_source, org.cadence_verified_for_cycle):
        return None
    return RegisterCadence(open_month=org.cadence_open_month,
                           deadline_month=org.cadence_deadline_month,
                           source=org.cadence_source,
                           verified_for_cycle=org.cadence_verified_for_cycle)


@transaction.atomic
def record_read_evidence(
    opportunity: FundingOpportunity,
    decision: FundingDecision,
    *,
    url: str,
    sha256: str,
    at: dt.date,
    today: dt.date,
) -> None:
    """Step 0, stored: the reader already read these dates -- keep them.

    Written on every tracked intake's row, because a line naming no intake is
    evidence for each of them and `to_evidence` decides which intake a dated
    line speaks to. The row's first ladder run is due at once.
    """
    new = entries_from_decision(decision, step="0", url=url, sha256=sha256, at=at)
    for year in tracked_intakes(today):
        row, _ = FundingCycleVerification.objects.select_for_update().get_or_create(
            opportunity=opportunity, intake_start_year=year
        )
        row.evidence = _merge(row.evidence, new)
        evidence = to_evidence(row.evidence, target_year=year, cadence=_cadence(opportunity),
                               page_removed=row.page_removed, lapsed=row.projection_lapsed)
        row.state = cycle_validity(evidence, student={}, target_intake=str(year), today=today)
        if row.next_check_at is None:
            row.next_check_at = timezone.now()
        row.save()
```

- [ ] **Step 4: Call it from both writers.** In `apps/research/funding_reader.py`, at the end of
  `write_holder_decision`, after `_write_rows(...)` and before `return opportunity`:

```python
    # Step 0 of the verification ladder (spec 9.2): the dates this read found,
    # kept per intake -- this row's own fields keep only the last decision's.
    record_read_evidence(
        opportunity, decision, url=snapshot.final_url or source.canonical_url,
        sha256=snapshot.sha256, at=checked_at.date(), today=checked_at.date(),
    )
```

  Add the same call in `write_funding_decision` after its row is written. Guard it with
  `if opportunity is not None:`, because that writer returns `None` for a jointly provided
  institution award. Import at the top: `from .cycle_verification import record_read_evidence`.
  `cycle_verification` does not import `funding_reader`, so this is not a cycle.

- [ ] **Step 5: Run** the new file plus `tests/research/test_funding_reader.py`,
  `tests/research/test_award_identity.py`, `tests/research/test_tiered_agreement.py` and
  `tests/research/test_pipeline_funding.py`. Expected: all pass. A writer test that counts queries
  exactly will now see more; update that count and say why in the commit message.

- [ ] **Step 6: Lint, type-check, commit**

```bash
git commit -m "feat(research): store the reader's dates as step-0 cycle evidence, per intake" -- \
  apps/research/cycle_verification.py apps/research/funding_reader.py \
  tests/research/test_cycle_verification.py
```

---

### Task 7: The ladder's frame and step 0 — `Subject`, `Seams`, `joins`, `verify_cycle`

**Files:**
- Modify: `apps/research/cycle_verification.py`
- Test: `tests/research/test_cycle_verification.py` (extend)

- [ ] **Step 1: Write the failing tests.** The ladder is tested against scripted seams: no network,
  and every call is counted.

```python
# append to tests/research/test_cycle_verification.py
from apps.research.cycle_verification import Seams, Subject, joins, verify_cycle
from apps.research.fetch import SweepBudget
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.metering import Meter
from apps.research.providers.base import SiteSearchResult


def _page(url, text, outcome=Outcome.FETCHED, body=None):
    return FetchedPage(final_url=url, redirects=(), content_type="text/html",
                       body=body if body is not None else f"<main>{text}</main>".encode(),
                       markdown=text, outcome=outcome, fetched_via="FIRECRAWL", cost_credits=1)


class Script:
    """Scripted seams. `reads` maps a URL to the decisions its read returns."""

    def __init__(self, pages=None, reads=None, crawl_urls=(), captures=None, search=()):
        # The award's own page is live by default. Without it every own page is
        # DEAD, the award is ENDED at step 0, and a test of a later step would
        # pass without the step ever running.
        own = "https://f.example/award"
        self.pages = {own: _page(own, "Example Fellowship"), **(pages or {})}
        self.reads = reads or {}
        self.crawl_urls, self.captures, self.search_urls = crawl_urls, captures or {}, search
        self.calls: list[tuple[str, str]] = []

    def seams(self):
        from apps.research.fetch.site import CrawlResult

        def fetch(url, **kw):
            self.calls.append(("fetch", url))
            return self.pages.get(url, _page(url, "", Outcome.DEAD))

        def crawl(url, **kw):
            self.calls.append(("crawl", url))
            return CrawlResult(job_id="j", urls=tuple(self.crawl_urls), dead=(), errors=(),
                               robots_blocked=(), credits=len(self.crawl_urls), status="completed")

        def capture_near(url, *, at, **kw):
            self.calls.append(("wayback", f"{url}@{at.year}"))
            return self.captures.get((url, at.year), _page(url, "", Outcome.BLOCKED))

        def read(page):
            self.calls.append(("read", page.final_url))
            return tuple(self.reads.get(page.final_url, ()))

        def search(*, query, domain, **kw):
            self.calls.append(("exa", query))
            return SiteSearchResult(urls=tuple(self.search_urls), cost_usd=0.01, provider="exa")

        def brave(*, query, domain, **kw):
            self.calls.append(("brave", query))
            return SiteSearchResult(urls=(), cost_usd=0.005, provider="brave")

        return Seams(fetch=fetch, crawl=crawl, capture_near=capture_near, read=read,
                     site_search=search, fallback_search=brave, store=_Store())


class _Store:
    def put(self, key, body):
        return "v1"


SUBJECT = Subject(name="Example Fellowship", kind="I0_HOLDER_AWARD", scope="HOLDER_OWN",
                  own_urls=("https://f.example/award",), domains=frozenset({"f.example"}),
                  primary_domain="f.example", ambiguous=False, cadence=None, languages=())


def _run(script, stored=(), today=TODAY, subject=SUBJECT, year=2027):
    meter = Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000}))
    return verify_cycle(subject, intake_year=year, today=today, seams=script.seams(),
                        meter=meter, stored=list(stored))


def test_step_zero_decisive_makes_no_crawl_and_no_search():
    script = Script(pages={"https://f.example/award": _page(
        "https://f.example/award", "x", Outcome.UNCHANGED)})
    stored = entries_from_decision(_decision(applies_to="2027-2028",
                                             deadlines=(("2027-01-15", "ALL"),)),
                                   step="0", url="https://f.example/award",
                                   sha256="a" * 64, at=TODAY)
    verdict = _run(script, stored)
    assert (verdict.state, verdict.step) == ("OPEN", "0")
    assert [kind for kind, _ in script.calls] == ["fetch"]  # one credit, no reading


def test_an_unchanged_own_page_is_not_read_again():
    script = Script(pages={"https://f.example/award": _page(
        "https://f.example/award", "x", Outcome.UNCHANGED)})
    stored = entries_from_decision(_decision(), step="0", url="https://f.example/award",
                                   sha256="a" * 64, at=TODAY)
    _run(script, stored)
    assert ("read", "https://f.example/award") not in script.calls


DEAD = {"https://f.example/award": _page("https://f.example/award", "", Outcome.DEAD)}


def test_every_own_page_dead_is_page_removed_and_ended():
    verdict = _run(Script(pages=DEAD))
    assert verdict.page_removed and verdict.state == "ENDED"


@pytest.mark.parametrize(
    ("decision_overrides", "ambiguous", "expected"),
    [
        ({}, False, True),
        ({"kind": "I1_UNIVERSITY_WIDE"}, False, False),       # another kind is another award
        ({"scope": "PROGRAM"}, False, False),
        ({"quotes": ("Our other grant",), "heading": "Grants", "name": "Other Grant"}, True, False),
        ({"quotes": ("The Example Fellowship 2027 call",)}, True, True),
    ],
)
def test_a_decision_joins_its_award_by_kind_scope_and_when_ambiguous_by_name(
    decision_overrides, ambiguous, expected
):
    subject = replace(SUBJECT, ambiguous=ambiguous)
    assert joins(_decision(**decision_overrides), subject) is expected


@pytest.mark.xfail(strict=True, reason="decision-side finding: autumn deadlines project a year "
                   "late (validity.project_window measures from deadline.year) -- owner's call")
def test_an_october_call_with_a_november_deadline_projects_before_the_intake():
    from apps.funding.validity import Evidence

    evidence = Evidence(past_calls=((dt.date(2025, 10, 1), dt.date(2025, 11, 30)),
                                    (dt.date(2024, 10, 1), dt.date(2024, 11, 30))))
    assert cycle_validity(evidence, student={}, target_intake="2027",
                          today=dt.date(2027, 6, 1)) == "CLOSED_FOR_INTAKE"
```

Import `cycle_validity` from `apps.funding.validity` at the top of the test module.

- [ ] **Step 2: Run** — expected FAIL, `ImportError: cannot import name 'Seams'`.

- [ ] **Step 3: Implement the frame and step 0** (append to `cycle_verification.py`)

```python
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

from apps.funding.cycle_schedule import projection_lapsed
from apps.funding.validity import RegisterCadence, Validity, projected_window
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.metering import Meter
from apps.research.snapshot import ObjectStore

_ORDER = ("0", "1", "1b", "1c", "2", "3")
#: The judge's scope for each catalog scope (funding_reader writes HOLDER rows
#: from HOLDER_OWN decisions).
_JUDGE_SCOPE = {"HOLDER": "HOLDER_OWN", "PROGRAM": "PROGRAM", "INSTITUTION": "INSTITUTION"}


@dataclass(frozen=True)
class Subject:
    """What the ladder knows about one award -- from a catalog row (`subject_for`)
    or from a truth-set row (Task 12). Never a student."""

    name: str
    kind: str
    scope: str
    own_urls: tuple[str, ...]
    #: Registrable domains that count as the award's own site (plan decision 1).
    domains: frozenset[str]
    primary_domain: str
    #: True when the organisation holds another award of the same kind, so a
    #: decision must also name this one to join it.
    ambiguous: bool
    cadence: RegisterCadence | None
    languages: tuple[str, ...] = ()


@dataclass(frozen=True)
class Seams:
    fetch: Callable[..., FetchedPage]
    crawl: Callable[..., Any]
    capture_near: Callable[..., FetchedPage]
    read: Callable[[FetchedPage], tuple[FundingDecision, ...]]
    site_search: Callable[..., Any]
    fallback_search: Callable[..., Any]
    store: ObjectStore


@dataclass(frozen=True)
class Verdict:
    state: Validity
    step: str
    entries: list[dict[str, Any]]
    trail: list[dict[str, str]]
    page_removed: bool
    own_page_silent: bool
    projected_open: dt.date | None
    projected_deadline: dt.date | None
    lapsed: bool


@dataclass
class _Run:
    subject: Subject
    year: int
    today: dt.date
    seams: Seams
    meter: Meter
    entries: list[dict[str, Any]]
    trail: list[dict[str, str]] = field(default_factory=list)
    fetched: dict[str, FetchedPage] = field(default_factory=dict)
    page_removed: bool = False
    own_page_silent: bool = False

    def note(self, step: str, url: str, outcome: str, note: str = "") -> None:
        self.trail.append({"step": step, "url": url, "outcome": outcome, "note": note[:200]})

    def state(self, through: str) -> Validity:
        use_cadence = _ORDER.index(through) >= _ORDER.index("1c")
        evidence = to_evidence(self.entries, target_year=self.year,
                               cadence=self.subject.cadence if use_cadence else None,
                               page_removed=self.page_removed, lapsed=False)
        return cycle_validity(evidence, student={}, target_intake=str(self.year),
                              today=self.today)


def joins(decision: FundingDecision, subject: Subject) -> bool:
    """Does this decision, read off some page, describe THIS award?

    Kind and scope must match -- the judge's own award identity minus the page
    and heading, which differ on every page the ladder reads. When the
    organisation holds another award of the same kind, the decision must also
    name this one; otherwise it joins nothing and is counted, never guessed
    onto the wrong award. That applies to negations too: a NO that cannot be
    placed suspends nothing.
    """
    if decision.kind != subject.kind or decision.scope != subject.scope:
        return False
    if not subject.ambiguous:
        return True
    text = " ".join((decision.heading, decision.name, *decision.quotes)).casefold()
    return bool(subject.name) and subject.name.casefold() in text


def _absorb(run: _Run, page: FetchedPage, *, step: str) -> int:
    """Read one page, keep the decisions that join this award, archive its bytes."""
    decisions = [d for d in run.seams.read(page) if joins(d, run.subject)]
    if not decisions:
        run.note(step, page.final_url, "read", "no decision joins this award")
        return 0
    sha256 = hashlib.sha256(page.body).hexdigest()
    run.seams.store.put(f"cycle-evidence/{sha256}", page.body)
    new: list[EvidenceEntry] = []
    for decision in decisions:
        new += entries_from_decision(decision, step=step, url=page.final_url, sha256=sha256,
                                     at=run.today, captured_at=page.captured_at)
    run.entries = _merge(run.entries, new)
    run.note(step, page.final_url, "evidence", f"{len(decisions)} decision(s)")
    return len(decisions)


def _tag(year: int) -> str:
    # Never the monitors' `<cycle>:<host>`: two consumers on one tag would each
    # see the other's `changed` as `same` (spec 7.6).
    return f"cycle-verify:{year}"


def _step_zero(run: _Run) -> None:
    dead = 0
    for url in run.subject.own_urls:
        page = run.seams.fetch(url, tag=_tag(run.year), require_origin=url,
                               budget=run.meter.run)
        run.fetched[url] = page
        if page.outcome == Outcome.DEAD:
            dead += 1
            run.note("0", url, "DEAD")
            continue
        stored = any(e["url"] == url and not e["archived"] for e in run.entries)
        if page.outcome == Outcome.UNCHANGED and stored:
            run.note("0", url, "UNCHANGED")
            continue
        if not page.ok and page.outcome != Outcome.UNCHANGED:
            run.note("0", url, str(page.outcome), page.reason)
            continue
        found = _absorb(run, page, step="0")
        if not found and len(run.subject.own_urls) == 1 and stored:
            # The award's only page, changed, no longer describes it (Task 11).
            run.own_page_silent = True
    run.page_removed = bool(run.subject.own_urls) and dead == len(run.subject.own_urls)


def verify_cycle(
    subject: Subject,
    *,
    intake_year: int,
    today: dt.date,
    seams: Seams,
    meter: Meter,
    stored: list[dict[str, Any]],
) -> Verdict:
    run = _Run(subject=subject, year=intake_year, today=today, seams=seams, meter=meter,
               entries=list(stored))
    reached = "0"
    _step_zero(run)
    state = run.state("0")
    for step, action in _LATER_STEPS:
        if state != "UNVERIFIED" or run.page_removed or meter_exhausted(run):
            break
        reached = step
        action(run)
        state = run.state(step)
    return _finish(run, state, reached)


def meter_exhausted(run: _Run) -> bool:
    from django.conf import settings

    usd, _detail, _complete = run.meter.total()
    if float(usd) >= settings.CYCLE_VERIFY_MAX_USD_PER_AWARD:
        run.note("budget", "", "STOP", f"per-award ceiling reached at ${usd}")
        return True
    return False


def _finish(run: _Run, state: Validity, reached: str) -> Verdict:
    evidence = to_evidence(run.entries, target_year=run.year, cadence=run.subject.cadence,
                           page_removed=run.page_removed, lapsed=False)
    window = projected_window(evidence, target_intake=str(run.year), today=run.today)
    opened, deadline = window if window else (None, None)
    call_seen = any(e["intake_year"] == run.year for e in run.entries) or bool(evidence.deadlines)
    lapsed = projection_lapsed(opened, today=run.today, call_seen=call_seen)
    if lapsed:
        evidence = to_evidence(run.entries, target_year=run.year, cadence=run.subject.cadence,
                               page_removed=run.page_removed, lapsed=True)
        state = cycle_validity(evidence, student={}, target_intake=str(run.year), today=run.today)
    return Verdict(state=state, step=reached, entries=run.entries, trail=run.trail,
                   page_removed=run.page_removed, own_page_silent=run.own_page_silent,
                   projected_open=opened, projected_deadline=deadline, lapsed=lapsed)


#: Filled by Tasks 8-10, in spec order. Each entry runs only while the state is
#: still UNVERIFIED.
_LATER_STEPS: list[tuple[str, Callable[[_Run], None]]] = []
```

Import only what each task's code uses. ruff's F401 fails the lint step on an import a later task
will need, so that task adds it.

- [ ] **Step 4: Run** the test file. Expected: every test passes, and the `xfail` test reports
  XFAIL (strict — it fails loudly the day the decision side is fixed).
- [ ] **Step 5: Lint, type-check, commit**

```bash
git commit -m "feat(research): the verification ladder's frame and step 0 over scripted seams" -- \
  apps/research/cycle_verification.py tests/research/test_cycle_verification.py
```

---

### Task 8: Step 1 — the cycle-vocabulary crawl, filtered, then read

**Files:** modify `apps/research/cycle_verification.py`; extend `tests/research/test_cycle_verification.py`.

- [ ] **Step 1: Failing tests**

```python
def test_step_zero_empty_crawls_with_the_cycle_vocabulary_and_limit_15(settings):
    settings.CYCLE_CRAWL_LIMIT = 15
    calls = {}
    script = Script(crawl_urls=("https://f.example/news/2027-call",),
                    pages={"https://f.example/news/2027-call": _page(
                        "https://f.example/news/2027-call", "The Example Fellowship 2027 call")},
                    reads={"https://f.example/news/2027-call": (
                        _decision(applies_to="2027", deadlines=(("2027-01-15", "ALL"),)),)})
    seams = script.seams()
    original = seams.crawl

    def spy(url, **kw):
        calls.update(kw)
        return original(url, **kw)

    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY,
                           seams=replace(seams, crawl=spy),
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=[])
    assert (verdict.state, verdict.step) == ("OPEN", "1")
    assert calls["limit"] == 15 and "deadline" in calls["include_paths"]
    assert calls["tag"] == "cycle-verify:2027"


def test_a_crawled_page_naming_neither_the_award_nor_a_year_is_not_read():
    script = Script(crawl_urls=("https://f.example/about",),
                    pages={"https://f.example/about": _page("https://f.example/about",
                                                            "About our foundation")})
    _run(script)
    assert ("read", "https://f.example/about") not in script.calls


def test_a_crawled_url_off_the_organisations_domains_is_never_fetched():
    script = Script(crawl_urls=("https://cdn.other.example/call.pdf",))
    _run(script)
    assert ("fetch", "https://cdn.other.example/call.pdf") not in script.calls


def test_a_crawl_that_cannot_fit_the_run_budget_is_not_submitted(settings):
    settings.FETCH_PDF_MAX_PAGES = 60
    script = Script(crawl_urls=("https://f.example/news",))
    meter = Meter(SweepBudget({"FIRECRAWL": 100, "SCRAPE_DO": 1000}))
    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=script.seams(),
                           meter=meter, stored=[])
    assert ("crawl", "https://f.example/award") not in script.calls
    assert any(t["note"].startswith("crawl ceiling") for t in verdict.trail)
```

- [ ] **Step 2: Run** — expected FAIL (no step 1 registered; state stays UNVERIFIED and `step` is `"0"`).

- [ ] **Step 3: Implement**

```python
from django.conf import settings as _settings

from apps.research import cycle_vocabulary
from apps.research.fetch import FetchBudgetExhausted
from apps.research.fetch.site import FirecrawlSiteError, crawl_ceiling
from apps.research.hosts import registrable_domain


def _own(url: str, subject: Subject) -> bool:
    return registrable_domain(url) in subject.domains


def _read_url(run: _Run, url: str, *, step: str, filtered: bool = True) -> None:
    if url in run.fetched or not _own(url, run.subject):
        return
    page = run.seams.fetch(url, tag=_tag(run.year), require_origin=url, budget=run.meter.run)
    run.fetched[url] = page
    if not page.ok:
        run.note(step, url, str(page.outcome), page.reason)
        return
    text = page.markdown or page.body.decode("utf-8", "ignore")
    if filtered and not cycle_vocabulary.mentions_award(
        text, name=run.subject.name, years=cycle_vocabulary.year_tokens(run.today)
    ):
        run.note(step, url, "filtered", "names neither the award nor a year")
        return
    _absorb(run, page, step=step)


def _step_crawl(run: _Run) -> None:
    run_budget = run.meter.run
    remaining = run_budget.caps["FIRECRAWL"] - run_budget.spent["FIRECRAWL"]
    limit = _settings.CYCLE_CRAWL_LIMIT
    if crawl_ceiling(limit) > remaining:
        run.note("1", run.subject.own_urls[0] if run.subject.own_urls else "", "SKIPPED",
                 f"crawl ceiling {crawl_ceiling(limit)} credits > {remaining} left in the run")
        return
    if not run.subject.own_urls:
        return
    try:
        result = run.seams.crawl(
            run.subject.own_urls[0], limit=limit, tag=_tag(run.year),
            include_paths=cycle_vocabulary.include_paths(run.subject.languages, today=run.today),
        )
    except FirecrawlSiteError as error:
        run.note("1", run.subject.own_urls[0], "CRAWL_FAILED", str(error))
        return
    try:
        run_budget.spend("FIRECRAWL", result.credits)
    except FetchBudgetExhausted as error:
        run.note("1", "", "BUDGET", str(error))
        return
    for url in result.urls:
        if run.state("1") != "UNVERIFIED" or meter_exhausted(run):
            return
        _read_url(run, url, step="1")


_LATER_STEPS.append(("1", _step_crawl))
```

- [ ] **Step 4: Run** — expected: all pass.
- [ ] **Step 5: Lint, type-check, commit** — `"feat(research): ladder step 1, the cycle-vocabulary crawl"`,
  pathspec as in Task 7.

---

### Task 9: Step 1b Wayback and step 1c cadence — and `archive.capture_near`

**Files:**
- Modify: `apps/research/fetch/archive.py`, `apps/research/cycle_verification.py`
- Test: `tests/research/test_fetch_archive.py` (extend), `tests/research/test_cycle_verification.py` (extend)

- [ ] **Step 1: Failing tests** — first the archive:

```python
# append to tests/research/test_fetch_archive.py
def test_capture_near_asks_for_the_date_it_was_given(monkeypatch):
    import datetime as dt
    import json

    from apps.research.egress import FetchResult
    from apps.research.fetch import archive

    asked = []

    def probe(lookup):
        asked.append(lookup)
        body = json.dumps({"archived_snapshots": {"closest": {
            "available": True, "timestamp": "20250402120000",
            "url": "http://web.archive.org/web/20250402120000/https://f.example/award"}}})
        return FetchResult(final_url=lookup, redirects=(), content_type="application/json",
                           body=body.encode())

    def fetch(raw, **kw):
        return archive.FetchedPage(
            final_url="https://web.archive.org/web/20250402120000id_/https://f.example/award",
            redirects=(), content_type="text/html", body=b"<main>x</main>" * 100,
            markdown="x", outcome=archive.Outcome.FETCHED, fetched_via="SCRAPE_DO", rung=3,
            cost_credits=1)

    page = archive.capture_near("https://f.example/award", at=dt.date(2025, 3, 26),
                                api_key="k", fetch=fetch, probe=probe)
    assert "timestamp=20250326" in asked[0]
    assert page.outcome == archive.Outcome.ARCHIVED and page.captured_at == "2025-04-02"


def test_capture_near_refuses_a_capture_from_another_cycle(monkeypatch, settings):
    import datetime as dt
    import json

    from apps.research.egress import FetchResult
    from apps.research.fetch import archive

    settings.CYCLE_ARCHIVE_SKEW_DAYS = 120

    def probe(lookup):
        body = json.dumps({"archived_snapshots": {"closest": {
            "available": True, "timestamp": "20230101120000",
            "url": "http://web.archive.org/web/20230101120000/https://f.example/award"}}})
        return FetchResult(final_url=lookup, redirects=(), content_type="application/json",
                           body=body.encode())

    page = archive.capture_near("https://f.example/award", at=dt.date(2025, 3, 26),
                                api_key="k", fetch=lambda *a, **k: None, probe=probe)
    assert page.outcome == archive.Outcome.BLOCKED and page.reason.startswith("archive_skew")
```

then the ladder:

```python
def test_wayback_captures_of_two_earlier_cycles_make_it_upcoming():
    url = "https://f.example/award"
    captures = {
        (url, 2025): replace(_page(url, "Example Fellowship 2025 call"), outcome=Outcome.ARCHIVED,
                             captured_at="2025-04-01"),
        (url, 2024): replace(_page(url, "Example Fellowship 2024 call"), outcome=Outcome.ARCHIVED,
                             captured_at="2024-04-01"),
    }
    reads = {url: (_decision(stated_on="2026-03-03", deadlines=(("2026-05-15", "ALL"),)),)}
    script = Script(pages={url: _page(url, "Example Fellowship")}, captures=captures, reads=reads)
    # The capture read returns the older cycle; the scripted read is keyed by final_url,
    # so give each capture its own year's decision through a side table.
    year_reads = {2025: _decision(stated_on="2025-03-04", deadlines=(("2025-05-16", "ALL"),)),
                  2024: _decision(stated_on="2024-03-05", deadlines=(("2024-05-17", "ALL"),))}
    seams = script.seams()

    def read(page):
        if page.captured_at:
            return (year_reads[int(page.captured_at[:4])],)
        return seams.read(page)

    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY,
                           seams=replace(seams, read=read, crawl=lambda *a, **k: _empty_crawl()),
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=[])
    assert (verdict.state, verdict.step) == ("UPCOMING", "1b")


def test_a_wayback_lookup_is_made_once_and_cached_for_good():
    url = "https://f.example/award"
    stored_trail = [{"step": "1b", "url": f"{url}@2025", "outcome": "LOOKED", "note": ""},
                    {"step": "1b", "url": f"{url}@2024", "outcome": "LOOKED", "note": ""}]
    script = Script(pages={url: _page(url, "x")})
    meter = Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000}))
    verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=script.seams(), meter=meter,
                 stored=[], looked=stored_trail)
    assert not [c for c in script.calls if c[0] == "wayback"]


def test_a_current_register_cadence_is_step_1c_and_costs_nothing():
    from apps.funding.validity import RegisterCadence

    subject = replace(SUBJECT, cadence=RegisterCadence(open_month=3, deadline_month=5,
                                                       source="https://r.example",
                                                       verified_for_cycle=2026))
    verdict = _run(Script(pages={"https://f.example/award": _page(
        "https://f.example/award", "x")}), subject=subject)
    assert (verdict.state, verdict.step) == ("UPCOMING", "1c")
```

with a helper:

```python
def _empty_crawl():
    from apps.research.fetch.site import CrawlResult

    return CrawlResult(job_id="j", urls=(), dead=(), errors=(), robots_blocked=(), credits=0,
                       status="completed")
```

This test file therefore extends `verify_cycle`'s signature with a keyword `looked:
list[dict[str, str]] = ()`, the previous trails' `1b` lookups. Its default keeps Task 7's calls
valid.

- [ ] **Step 2: Run** — expected FAIL (`capture_near` missing; the ladder has no step 1b/1c).

- [ ] **Step 3: Factor `archive.py`.** Move everything in `latest_capture` after the probe into
  `_from_closest(url, closest, *, api_key, fetch, age_check)`, where `age_check(captured) -> str | None`
  returns a refusal reason or `None`. Then:

```python
def latest_capture(url, *, api_key, now=None, fetch=scrape, probe=fetch_data_file):
    now = now or datetime.now(UTC)
    closest = _closest(url, timestamp=now, probe=probe)
    if isinstance(closest, FetchedPage):
        return closest
    max_age = timedelta(days=settings.FETCH_ARCHIVE_MAX_AGE_DAYS)
    return _from_closest(
        url, closest, api_key=api_key, fetch=fetch,
        age_check=lambda captured: (
            f"archive_stale:{captured:%Y-%m-%d}" if now - captured > max_age else None
        ),
    )


def capture_near(url, *, at, api_key, fetch=scrape, probe=fetch_data_file):
    """The capture closest to `at` -- evidence of an EARLIER cycle (spec 9.2, step 1b).

    Not subject to FETCH_ARCHIVE_MAX_AGE_DAYS, which bounds how old a capture
    may be when it stands in for the page as it is NOW (rung 6). A capture
    asked for as history is meant to be old; it must only be near the date
    asked for, or it describes a different cycle.
    """
    moment = datetime(at.year, at.month, at.day, tzinfo=UTC)
    closest = _closest(url, timestamp=moment, probe=probe)
    if isinstance(closest, FetchedPage):
        return closest
    skew = timedelta(days=settings.CYCLE_ARCHIVE_SKEW_DAYS)
    return _from_closest(
        url, closest, api_key=api_key, fetch=fetch,
        age_check=lambda captured: (
            f"archive_skew:{captured:%Y-%m-%d}" if abs(captured - moment) > skew else None
        ),
    )
```

  `_closest(url, *, timestamp, probe)` holds the bare-URL lookup, the probe and its exception
  handling, the JSON parse, the `available` check and the timestamp validation — lines 125–155 of
  today's `latest_capture`, unchanged. It returns either the validated `closest` dict (with a parsed
  `captured` datetime added) or the `_refused(...)` page those lines already build. Every existing
  test in `tests/research/test_fetch_archive.py` must pass unmodified. That is the proof the refactor
  changed nothing.

- [ ] **Step 4: The ladder steps**

```python
def _step_wayback(run: _Run) -> None:
    looked = {t["url"] for t in run.looked if t["step"] == "1b"}
    for url in run.subject.own_urls[:1]:  # the call page: the award's first own page
        for back in range(1, _settings.CYCLE_ARCHIVE_YEARS_BACK + 1):
            at = run.today.replace(year=run.today.year - back) if not (
                run.today.month == 2 and run.today.day == 29
            ) else run.today.replace(year=run.today.year - back, day=28)
            key = f"{url}@{at.year}"
            if key in looked:
                continue  # read once, cached for good (spec 9.2)
            page = run.seams.capture_near(url, at=at)
            try:
                run.meter.run.spend("SCRAPE_DO", page.cost_credits)
            except FetchBudgetExhausted as error:
                run.note("1b", key, "BUDGET", str(error))
                return
            run.note("1b", key, "LOOKED", str(page.outcome))
            if page.ok:
                _absorb(run, page, step="1b")


def _step_cadence(run: _Run) -> None:
    run.note("1c", "", "CADENCE",
             "register cadence considered" if run.subject.cadence else "no register cadence")


_LATER_STEPS.extend((("1b", _step_wayback), ("1c", _step_cadence)))
```

  Add `looked: list[dict[str, str]] = field(default_factory=list)` to `_Run`, and
  `looked: Sequence[dict[str, str]] = ()` to `verify_cycle`, passed through as `list(looked)`.
  `_step_cadence` does no work: `run.state("1c")` includes the cadence from 1c onward. The step
  exists so the trail and `ladder_step` say which evidence settled the state.

- [ ] **Step 5: Run** both test files — expected: all pass, including every pre-existing archive test.
- [ ] **Step 6: Lint, type-check, commit** — `"feat(research): ladder steps 1b (Wayback, cached for good) and 1c (register cadence); archive.capture_near"`.

---

### Task 10: Step 2 (one own-site hop) and step 3 (Exa, then Brave) — and `brave_site_search`

**Files:**
- Modify: `apps/research/providers/brave.py`, `apps/research/cycle_verification.py`
- Test: `tests/research/test_providers.py` (extend), `tests/research/test_cycle_verification.py` (extend)

- [ ] **Step 1: Failing tests**

```python
# append to tests/research/test_providers.py
def test_brave_site_search_asks_one_page_and_reports_its_list_price(settings):
    from apps.research.providers.brave import brave_site_search

    settings.BRAVE_USD_PER_REQUEST = 0.005
    seen = {}

    def get(url, *, params, headers):
        seen.update(params)
        return {"web": {"results": [{"url": "https://f.example/2027-call"},
                                    {"url": "https://aggregator.example/f"}]}}

    result = brave_site_search(query="Example Fellowship 2027", domain="f.example",
                               api_key="k", get=get)
    assert seen["q"] == "site:f.example Example Fellowship 2027" and seen["count"] == 10
    assert result.urls == ("https://f.example/2027-call",)  # off-domain dropped
    assert result.cost_usd == 0.005 and result.provider == "brave"
```

```python
# append to tests/research/test_cycle_verification.py
def test_the_hop_follows_an_own_domain_apply_link_and_withholds_every_other():
    url = "https://f.example/award"
    body = (b'<main><a href="https://apply.f.example/2027">Apply now</a>'
            b'<a href="https://portal.other.example/login">Application portal</a></main>')
    script = Script(pages={url: _page(url, "Example Fellowship", body=body),
                           "https://apply.f.example/2027": _page(
                               "https://apply.f.example/2027", "Apply by 15 January 2027")},
                    reads={"https://apply.f.example/2027": (
                        _decision(applies_to="2027", deadlines=(("2027-01-15", "ALL"),)),)})
    seams = replace(script.seams(), crawl=lambda *a, **k: _empty_crawl())
    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=seams,
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=[])
    assert (verdict.state, verdict.step) == ("OPEN", "2")
    assert ("fetch", "https://portal.other.example/login") not in script.calls
    assert any(t["outcome"] == "hop_withheld" for t in verdict.trail)


def test_search_runs_only_when_steps_0_to_2_found_nothing_and_brave_only_after_empty_exa():
    script = Script(pages={"https://f.example/award": _page("https://f.example/award", "x")})
    seams = replace(script.seams(), crawl=lambda *a, **k: _empty_crawl())
    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=seams,
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=[])
    kinds = [kind for kind, _ in script.calls]
    assert kinds.index("exa") < kinds.index("brave")
    assert verdict.step == "3" and verdict.state == "UNVERIFIED"
    [(_, query)] = [c for c in script.calls if c[0] == "exa"]
    assert query == "Example Fellowship 2027 call for applications deadline"


def test_no_search_query_ever_carries_anything_but_the_award_and_the_year():
    """Catalog path: there is no student here to leak -- pinned so one is never added."""
    import inspect

    from apps.research import cycle_verification

    source = inspect.getsource(cycle_verification._step_search)
    assert "profile" not in source and "student" not in source
```

- [ ] **Step 2: Run** — expected FAIL.

- [ ] **Step 3: `brave_site_search`** (append to `providers/brave.py`)

```python
def brave_site_search(
    *,
    query: str,
    domain: str,
    api_key: str | None = None,
    get: Callable[..., dict[str, object]] = fetch_json_api,
    count: int = 10,
) -> SiteSearchResult:
    """One `site:` page: the step-3 fallback when Exa returns nothing (spec 9.2).

    One request, never paginated -- a fallback that walks ten pages is not a
    fallback. The cost is Brave's list price per request (master spec 13);
    Brave's response carries no cost field of its own.
    """
    from django.conf import settings

    key = api_key if api_key is not None else settings.BRAVE_API_KEY
    if not key:
        raise ProviderUnavailable("BRAVE_API_KEY is not set")
    try:
        data = get(
            BRAVE_SEARCH_URL,
            params={"q": f"site:{domain} {query}", "count": count, "result_filter": "web"},
            headers={"Accept": "application/json", "X-Subscription-Token": key},
        )
    except Exception as error:  # transport, HTTP status, JSON -- one outcome here
        raise ProviderUnavailable("brave search failed") from error
    results = (data.get("web") or {}).get("results") if isinstance(data, dict) else None
    return SiteSearchResult(
        urls=urls_on_domain(results, domain),
        cost_usd=settings.BRAVE_USD_PER_REQUEST,
        provider="brave",
    )
```

  Import `ProviderUnavailable`, `SiteSearchResult` and `urls_on_domain` from `.base`.

- [ ] **Step 4: The ladder steps**

```python
from apps.research.providers.base import ProviderUnavailable


def _step_hop(run: _Run) -> None:
    candidates: list[str] = []
    for page in list(run.fetched.values()):
        if not page.body:
            continue
        for link in cycle_vocabulary.apply_links(page.body, base_url=page.final_url,
                                                 languages=run.subject.languages):
            if link in run.fetched or link in candidates:
                continue
            if not _own(link, run.subject):
                # Plan decision 1: an apply link off the organisation's own
                # domains may be a portal, and no vendor is ever pointed at one.
                # Every such link is noted, not only the first, so the gate can
                # count what the rule withheld.
                run.note("2", link, "hop_withheld", "off the organisation's own domains")
                continue
            candidates.append(link)
    if candidates:
        _read_url(run, candidates[0], step="2", filtered=False)  # one hop, never further


def _step_search(run: _Run) -> None:
    query = f"{run.subject.name} {run.year} call for applications deadline"
    urls: tuple[str, ...] = ()
    for search in (run.seams.site_search, run.seams.fallback_search):
        try:
            result = search(query=query, domain=run.subject.primary_domain)
        except ProviderUnavailable as error:
            run.note("3", "", "SEARCH_UNAVAILABLE", str(error))
            continue
        run.meter.add_search(result.provider, result.cost_usd)
        urls = result.urls
        if urls:
            break
    for url in urls[: _settings.CYCLE_SEARCH_RESULTS]:
        if run.state("3") != "UNVERIFIED" or meter_exhausted(run):
            return
        _read_url(run, url, step="3")


_LATER_STEPS.extend((("2", _step_hop), ("3", _step_search)))
```

  `exa_site_search` is passed through `Seams` with `num_results=settings.CYCLE_SEARCH_RESULTS` bound
  (Task 11 builds the real seams).

- [ ] **Step 5: Run** — expected: all pass.
- [ ] **Step 6: Lint, type-check, commit** — `"feat(research): ladder steps 2 (own-site hop, portals withheld) and 3 (Exa, Brave fallback)"`.

---

### Task 11: Persisting a verdict, withdrawal, and the scheduled worker

**Files:**
- Modify: `apps/research/cycle_verification.py` (`subject_for`, `persist_verdict`, `default_seams`, `funding_reader_for`)
- Create: `apps/research/management/commands/verify_due_cycles.py`
- Modify: `infra/template.yaml`
- Test: `tests/research/test_cycle_verification.py`, `tests/research/test_cycle_commands.py`, `tests/infra/test_template.py`

- [ ] **Step 1: Failing tests**

```python
# append to tests/research/test_cycle_verification.py
from apps.research.cycle_verification import persist_verdict, subject_for


def test_persisting_a_verdict_writes_state_step_cost_and_the_next_check(settings):
    opportunity = _opportunity()
    row = FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    meter = Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000}))
    meter.run.spend("FIRECRAWL", 3)
    meter.add_search("exa", 0.0097)
    verdict = _run(Script(pages=DEAD), subject=SUBJECT)  # all own pages DEAD -> ENDED
    persist_verdict(row, verdict, meter=meter, today=TODAY)
    row.refresh_from_db()
    assert row.state == "ENDED" and row.page_removed and row.ladder_step == "0"
    assert row.cost_usd > 0 and row.cost_detail["credits"]["FIRECRAWL"] == 3
    assert row.next_check_at.date() == TODAY + dt.timedelta(days=30)


def test_a_changed_only_page_that_no_longer_describes_the_award_withdraws_it():
    opportunity = _opportunity()
    opportunity.served = True
    opportunity.save()
    row = FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    verdict = replace(_run(Script()), own_page_silent=True, page_removed=False)
    persist_verdict(row, verdict, meter=Meter(SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})),
                    today=TODAY, sole_source=True)
    opportunity.refresh_from_db()
    assert (opportunity.agreement, opportunity.served) == ("WITHDRAWN", False)


def test_a_reviewed_row_is_never_withdrawn_by_the_verifier():
    opportunity = _opportunity()
    opportunity.review = "ACCEPTED"
    opportunity.save()
    row = FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    verdict = replace(_run(Script()), own_page_silent=True)
    persist_verdict(row, verdict, meter=Meter(SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})),
                    today=TODAY, sole_source=True)
    opportunity.refresh_from_db()
    assert opportunity.agreement == "AGREED"
```

```python
# append to tests/research/test_cycle_commands.py
import datetime as dt

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.funding.models import FundingCycleVerification, FundingOpportunity


@pytest.mark.django_db
def test_verify_due_cycles_refuses_to_start_without_the_second_model_family(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(CommandError, match="ANTHROPIC_API_KEY"):
        call_command("verify_due_cycles")


@pytest.mark.django_db
def test_dry_run_lists_due_rows_oldest_first_and_spends_nothing(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    opportunity = FundingOpportunity.objects.create(
        canonical_key="read:a", name="A", family="PRIVATE_FOUNDATION", scope_type="GLOBAL",
        agreement="AGREED")
    now = timezone.now()
    FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2028,
                                            next_check_at=now - dt.timedelta(days=1))
    FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027,
                                            next_check_at=now - dt.timedelta(days=2))
    call_command("verify_due_cycles", "--dry-run")
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("due 2") and "2027" in out[1] and "2028" in out[2]


@pytest.mark.django_db
def test_a_rejected_or_unagreed_award_is_never_verified(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    for key, agreement, review in (("b", "UNAGREED", ""), ("c", "AGREED", "REJECTED")):
        opportunity = FundingOpportunity.objects.create(
            canonical_key=f"read:{key}", name=key, family="PRIVATE_FOUNDATION",
            scope_type="GLOBAL", agreement=agreement, review=review)
        FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027,
                                                next_check_at=timezone.now())
    call_command("verify_due_cycles", "--dry-run")
    assert capsys.readouterr().out.startswith("due 0")
```

```python
# append to tests/infra/test_template.py
def test_the_cycle_verification_schedule_exists_and_ships_disabled(template: Template) -> None:
    rule = template["Resources"]["VerifyDueCyclesRule"]["Properties"]
    assert rule["State"] == "DISABLED"
    assert rule["ScheduleExpression"] == "rate(1 day)"
    assert '"verify_due_cycles"' in rule["Targets"][0]["Input"]
```

- [ ] **Step 2: Run** — expected FAIL.

- [ ] **Step 3: Implement `subject_for`, `persist_verdict`, the reader seam, the real seams**

```python
from decimal import Decimal
from functools import partial

from apps.funding.cycle_evidence import observations as _observations
from apps.funding.cycle_schedule import next_check
from apps.research.funding_judge import FUNDING_READS, funding_chunks, read_funding
from apps.research.reader import _MIN_BYTES_FOR_FLOOR, _MIN_READABLE_CHARS, readable_text


def subject_for(opportunity: FundingOpportunity) -> Subject:
    urls = tuple(
        opportunity.evidence_claims.values_list("source__canonical_url", flat=True).distinct()
    )
    org = opportunity.organisation
    domains = {registrable_domain(url) for url in urls}
    languages: tuple[str, ...] = ()
    if org is not None:
        domains |= set(org.domains.values_list("registrable_domain", flat=True))
        domains.add(org.primary_domain)
        siblings = FundingOpportunity.objects.filter(organisation=org, kind=opportunity.kind)
    else:
        siblings = FundingOpportunity.objects.filter(
            institution=opportunity.institution, program=opportunity.program,
            kind=opportunity.kind,
        )
    from apps.research.models import HostProfile

    hosts = [urlsplit(url).hostname or "" for url in urls]
    for profile in HostProfile.objects.filter(host__in=hosts):
        languages += tuple(profile.languages or ())
    return Subject(
        name=opportunity.name, kind=opportunity.kind,
        scope=_JUDGE_SCOPE.get(opportunity.scope_type, opportunity.scope_type),
        own_urls=urls, domains=frozenset(d for d in domains if d),
        primary_domain=org.primary_domain if org else (registrable_domain(urls[0]) if urls else ""),
        ambiguous=siblings.exclude(pk=opportunity.pk).exclude(agreement="WITHDRAWN").exists(),
        cadence=_cadence(opportunity), languages=tuple(dict.fromkeys(languages)),
    )


def funding_reader_for(parser, claude, *, pay: Callable[[int], bool], source_id: str):
    """The `read` seam: the funding reader over one page, paid for up front.

    The same shell floor and chunking as `pipeline._fund_page`, and the same
    rule that a read that cannot be paid for in full makes no call at all.
    """
    # Imported here, not at module top: funding_reader imports this module
    # (Task 6), so a top-level import back into it would be a cycle.
    from apps.research.funding_reader import _FUNDING_TERMS

    def read(page: FetchedPage) -> tuple[FundingDecision, ...]:
        if len(readable_text(page, terms=None)) < _MIN_READABLE_CHARS and (
            len(page.body) >= _MIN_BYTES_FOR_FLOOR
        ):
            return ()
        chunks = funding_chunks(
            readable_text(page, terms=_FUNDING_TERMS, select_only_over_cap=False)
        )
        if not chunks or not pay(FUNDING_READS * len(chunks)):
            return ()
        return read_funding(parser, claude, source_id=source_id, chunks=chunks,
                            pay_for_tie_break=lambda: pay(1)).decisions

    return read


@transaction.atomic
def persist_verdict(
    row: FundingCycleVerification,
    verdict: Verdict,
    *,
    meter: Meter,
    today: dt.date,
    sole_source: bool = False,
) -> None:
    usd, detail, complete = meter.total()
    evidence = to_evidence(verdict.entries, target_year=row.intake_start_year,
                           cadence=None, page_removed=verdict.page_removed, lapsed=verdict.lapsed)
    observed = _observations(verdict.entries)
    last_open = max((dt.date.fromisoformat(o["open"]) for o in observed if o["open"]),
                    default=None)
    row.state = verdict.state
    row.ladder_step = verdict.step
    row.evidence = verdict.entries
    row.cycles_observed = observed
    row.trail = (row.trail + verdict.trail)[-200:]
    row.projected_open, row.projected_deadline = verdict.projected_open, verdict.projected_deadline
    row.projection_lapsed = verdict.lapsed
    row.page_removed = verdict.page_removed
    row.cost_usd = Decimal(row.cost_usd) + usd
    row.cost_detail = detail
    row.cost_complete = row.cost_complete and complete
    row.verified_at = timezone.now()
    due = next_check(today=today, deadlines=[d for d, _ in evidence.deadlines],
                     last_call_open=last_open, projected_open=verdict.projected_open)
    row.next_check_at = timezone.make_aware(dt.datetime.combine(due, dt.time(6)))
    row.save()
    opportunity = row.opportunity
    # Plan decision 6: the one award-row write the verifier makes, by
    # withdraw_unread's own rule -- never a reviewed row, never a row another
    # page still supports.
    if verdict.own_page_silent and sole_source and not opportunity.review:
        opportunity.agreement, opportunity.served = "WITHDRAWN", False
        opportunity.save(update_fields=["agreement", "served"])
```

  `cost_usd` accumulates across runs, so the row carries the award's total verification spend for
  that intake. `cost_detail` holds the latest run's breakdown. Import `urlsplit` from `urllib.parse`.

- [ ] **Step 4: The command**

```python
# apps/research/management/commands/verify_due_cycles.py
"""Run the verification ladder for every (award, intake) whose check is due.

Platform work: the catalog is shared, so no tenant triggers this and none is
charged for it. Writes shared-catalog rows, so it runs as DATABASE_ROLE=migration
or under SET ROLE catalog_ingestion -- as the runtime role every write matches
zero rows in silence (CLAUDE.md, RLS failure mode 1), which is why its
EventBridge rule ships DISABLED beside RetryDueFetchesRule for the same reason.
"""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID

import anthropic
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone
from openai import OpenAI

from apps.funding.cycle_schedule import tracked_intakes
from apps.funding.models import FundingCycleVerification, FundingOpportunity
from apps.ratelimit import rate_limited
from apps.research.cycle_verification import (
    Seams, funding_reader_for, persist_verdict, subject_for, verify_cycle,
)
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import SweepBudget, fetch_page
from apps.research.fetch import archive, site
from apps.research.metering import Meter, MeteredMessages, MeteredResponses
from apps.research.providers.brave import brave_site_search
from apps.research.providers.exa import exa_site_search
from apps.research.storage import S3ObjectStore

#: No tenant asks for a verification, so a per-tenant limiter would limit
#: nothing; the platform is the actor (plan decision 8).
PLATFORM_ACTOR = UUID(int=0)


def _verifiable() -> Q:
    return Q(opportunity__agreement="AGREED") & ~Q(opportunity__review="REJECTED")


class Command(BaseCommand):
    help = "Verify every due (award, intake) through the evidence ladder (master spec 9.2-9.3)."

    def add_arguments(self, parser):
        parser.add_argument("--max", type=int, default=50)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise CommandError(
                "verify_due_cycles needs ANTHROPIC_API_KEY: an award's evidence is read by two "
                "model families, as it is everywhere else"
            )
        today = timezone.now().date()
        if not options["dry_run"]:
            self._ensure_tracked(today)
        due = list(
            FundingCycleVerification.objects.filter(_verifiable(), next_check_at__lte=timezone.now())
            .select_related("opportunity__organisation")
            .order_by("next_check_at")[: options["max"]]
        )
        self.stdout.write(f"due {len(due)}")
        for row in due:
            self.stdout.write(f"  {row.intake_start_year} {row.opportunity.name} [{row.state}]")
        if options["dry_run"]:
            return
        run = SweepBudget(settings.CYCLE_RUN_CREDITS)
        parser = cast(ResponsesAPI, OpenAI().responses)
        claude = cast(MessagesAPI, anthropic.Anthropic().messages)
        spent = 0.0
        for row in due:
            if spent >= settings.CYCLE_VERIFY_RUN_BUDGET_USD:
                self.stdout.write(f"run budget ${settings.CYCLE_VERIFY_RUN_BUDGET_USD} reached")
                break
            meter = Meter(run)
            seams = self._seams(meter, parser, claude, row)
            subject = subject_for(row.opportunity)
            siblings = FundingCycleVerification.objects.filter(opportunity=row.opportunity)
            stored = [e for other in siblings for e in other.evidence]
            looked = [t for other in siblings for t in other.trail if t["step"] == "1b"]
            verdict = verify_cycle(subject, intake_year=row.intake_start_year, today=today,
                                   seams=seams, meter=meter, stored=stored, looked=looked)
            persist_verdict(row, verdict, meter=meter, today=today,
                            sole_source=len(subject.own_urls) == 1)
            usd = float(meter.total()[0])
            spent += usd
            self.stdout.write(f"{row.intake_start_year} {row.opportunity.name}: {verdict.state} "
                              f"at step {verdict.step}, ${usd:.4f}")

    def _seams(self, meter, parser, claude, row) -> Seams:
        def pay(calls: int) -> bool:
            for _ in range(calls):
                if rate_limited("cycle-verification", PLATFORM_ACTOR,
                                limit=settings.CYCLE_VERIFY_MODEL_CALLS_PER_HOUR,
                                window_seconds=3_600):
                    return False
            return float(meter.total()[0]) < settings.CYCLE_VERIFY_MAX_USD_PER_AWARD

        return Seams(
            fetch=fetch_page,
            crawl=lambda url, **kw: site.crawl(url, api_key=settings.FIRECRAWL_API_KEY, **kw),
            capture_near=lambda url, *, at: archive.capture_near(
                url, at=at, api_key=settings.SCRAPEDO_API_KEY),
            read=funding_reader_for(MeteredResponses(parser, meter), MeteredMessages(claude, meter),
                                    pay=pay, source_id=str(row.opportunity_id)),
            site_search=lambda *, query, domain: exa_site_search(
                query=query, domain=domain, num_results=settings.CYCLE_SEARCH_RESULTS),
            fallback_search=brave_site_search,
            store=S3ObjectStore(),
        )

    def _ensure_tracked(self, today) -> None:
        """Every agreed award has a row for each tracked intake; rows whose
        intake has started stop being scheduled."""
        years = tracked_intakes(today)
        FundingCycleVerification.objects.filter(intake_start_year__lt=years[0]).update(
            next_check_at=None
        )
        for opportunity in FundingOpportunity.objects.filter(agreement="AGREED").exclude(
            review="REJECTED"
        ):
            for year in years:
                FundingCycleVerification.objects.get_or_create(
                    opportunity=opportunity, intake_start_year=year,
                    defaults={"next_check_at": timezone.now()},
                )
```

- [ ] **Step 5: The EventBridge rule**, in `infra/template.yaml` directly after `RetryDueFetchesRule`.
  Same shape. Its comment points at that rule's for the RLS reason it ships disabled.

```yaml
  # Same reason as RetryDueFetchesRule above for shipping DISABLED: this command
  # writes shared-catalog tables (funding_fundingcycleverification, and
  # funding_fundingopportunity on a withdrawal), which only catalog_ingestion may
  # write, and the worker task runs as DATABASE_ROLE=runtime. Enable both rules
  # together, in the change that builds the catalog_ingestion connection option.
  VerifyDueCyclesRule:
    Type: AWS::Events::Rule
    Properties:
      Description: Run the cycle-verification ladder for every award whose check is due
      ScheduleExpression: "rate(1 day)"
      State: DISABLED
      Targets:
        - Id: verify-due-cycles
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
             "command":["python","manage.py","verify_due_cycles"]}]}
```

  Daily, not hourly. The finest cadence §9.3 asks for is daily (within 14 days of a deadline), and
  `next_check_at` is what makes a monthly row wait. The worker task definition does not carry
  `ANTHROPIC_API_KEY` today (CLAUDE.md, the format-decision section). Adding it is part of enabling
  the rule, not of this plan.

- [ ] **Step 6: Run** the three test files — expected: all pass.
- [ ] **Step 7: Lint, type-check, bandit, commit**

```bash
git commit -m "feat(research): persist verdicts, withdraw a silent sole page, verify_due_cycles + disabled daily rule" -- \
  apps/research/cycle_verification.py apps/research/management/commands/verify_due_cycles.py \
  infra/template.yaml tests/research/test_cycle_verification.py tests/research/test_cycle_commands.py \
  tests/infra/test_template.py
```

---

### Task 12: The truth set — labelled by hand, blind, before the first run

**Files:**
- Create: `docs/research/2026-09-cycle-truth-set.csv` (the path `validity.py` already names)

§9.3's gate: "a truth set of ~40 organisations across AZ, TR, DE, NL, SE, FR, HU, IT labelled by
hand from their own sites, plus Wayback historical cases; a known-answer row per state …; ≥ 10
conditional-deadline rows".

- [ ] **Step 1: The columns** — header row, exactly:

```csv
organisation_domain,country,award_name,award_kind,award_scope,own_url,intake,nationality,country_of_residence,expected_state,expected_deadline,deadline_condition,evidence_url,sentence,last_call_opened,prior_call_opened,labelled_on,labelled_by
```

  - `award_kind` / `award_scope` use the judge's vocabulary (`I0_HOLDER_AWARD`/`HOLDER_OWN`, …).
    The gate builds a `Subject` from them.
  - `nationality` / `country_of_residence` are the **profile** a row is labelled for. A
    conditional-deadline award appears twice, once per profile, with different `expected_deadline`s.
  - `last_call_opened` / `prior_call_opened` are the two most recent past openings, read by hand from
    the site or its Wayback captures. They feed the projection backtest. Empty when the site shows
    none.
  - `sentence` is the verbatim sentence that decides the label. `evidence_url` is where it was read
    (a `web.archive.org/web/<ts>/…` URL for a historical row).

- [ ] **Step 2: Coverage the file must meet before Task 13 runs** (check by counting, and record the
  counts in the commit message):
  - ≥ 40 distinct `organisation_domain`s, at least 3 in each of AZ, TR, DE, NL, SE, FR, HU, IT;
  - at least one row for each of `OPEN`, `UPCOMING`, `CLOSED_FOR_INTAKE`, `SUSPENDED`, `ENDED`,
    `UNVERIFIED`. §9.3 names three known-answer rows, and each must be present:
    ChEMoinformatics+ labelled `SUSPENDED` for the 2026 intake from its dated 15/10/2025 statement;
    a March–May scheme labelled `UPCOMING` in September with two past calls; a first-year scheme
    labelled `UNVERIFIED`;
  - ≥ 8 `UPCOMING` rows across ≥ 4 countries and ≥ 3 families, each with both `*_call_opened` dates;
  - ≥ 10 conditional-deadline rows: a per-country-of-origin page, an EU/non-EU university page and a
    nomination scheme with an internal date, each labelled for two profiles.

- [ ] **Step 3: Blind labelling.** Label from the organisations' own sites and Wayback only, **before**
  running any command from this plan against them. `labelled_by` is a person's name. Record it here
  because the gate compares against it, and nothing else in this plan names a person.
  A row a labeller cannot decide from the site is labelled `UNVERIFIED` with the sentence that shows
  why. That is a real answer for this gate, not a gap.

- [ ] **Step 4: Commit** — `"docs(research): the cycle-verification truth set, labelled blind"`,
  pathspec the CSV.

---

### Task 13: The gate — `manage.py cycle_verify --truth`, and running it

**Files:**
- Create: `apps/research/management/commands/cycle_verify.py`
- Create: `docs/superpowers/2026-09-cycle-verification-gate.md` (the recorded result)
- Test: `tests/research/test_cycle_commands.py` (extend)

- [ ] **Step 1: Failing tests** — the scoring is pure and is tested on a fixture:

```python
from apps.research.management.commands.cycle_verify import GateRow, score


def _row(expected, got, **kw):
    return GateRow(domain=kw.get("domain", "a.example"), expected=expected, got=got,
                   expected_deadline=kw.get("expected_deadline", ""),
                   got_deadline=kw.get("got_deadline", ""), contradicted=kw.get("contradicted", False),
                   projected_open=kw.get("projected_open"), actual_open=kw.get("actual_open"),
                   step=kw.get("step", "0"), cost_usd=kw.get("cost_usd", 0.1),
                   country=kw.get("country", "DE"))


def test_precision_on_open_and_upcoming_is_what_the_gate_reads():
    report = score([_row("OPEN", "OPEN"), _row("UNVERIFIED", "OPEN"), _row("UPCOMING", "UPCOMING")])
    assert report.precision["OPEN"] == 0.5 and report.precision["UPCOMING"] == 1.0
    assert report.passed is False  # OPEN below 95%


def test_a_single_contradicted_open_row_fails_the_gate_whatever_the_precision():
    rows = [_row("OPEN", "OPEN")] * 40 + [_row("OPEN", "OPEN", contradicted=True)]
    assert score(rows).passed is False


def test_the_projection_backtest_counts_calls_within_45_days():
    import datetime as dt

    rows = [
        _row("UPCOMING", "UPCOMING", projected_open=dt.date(2026, 3, 1),
             actual_open=dt.date(2026, 3, 20)),
        _row("UPCOMING", "UPCOMING", projected_open=dt.date(2026, 3, 1),
             actual_open=dt.date(2026, 6, 1)),
    ]
    assert score(rows).projection_hit_rate == 0.5


def test_cost_per_verified_scholarship_divides_by_open_and_upcoming_only():
    report = score([_row("OPEN", "OPEN", cost_usd=0.3), _row("UNVERIFIED", "UNVERIFIED",
                                                            cost_usd=0.1)])
    assert report.cost_per_verified == 0.4
```

- [ ] **Step 2: Run** — expected FAIL.

- [ ] **Step 3: Write the command.**
  - `score(rows) -> GateReport`, pure. Per-state precision and recall; the confusion matrix;
    `contradicted` count; `projection_hit_rate` over rows with both dates; deadline accuracy on
    conditional rows (`got_deadline == expected_deadline`); the ladder-step distribution;
    per-country recall of `OPEN`+`UPCOMING`; `cost_per_verified` = total cost ÷ rows the engine
    called `OPEN` or `UPCOMING`.
  - `passed` = precision on `OPEN` ≥ 0.95 **and** on `UPCOMING` ≥ 0.95 **and** `contradicted == 0`.
    Projection hit rate, conditional-deadline accuracy and per-country recall are **reported, never
    asserted** (§15: recall is printed and recorded, never asserted by a test). They are what the
    owner reads beside the pass.
  - `handle`:
    1. Read the CSV and build a `Subject` per row (`domains` from `organisation_domain`, `own_urls`
       from `own_url`, `ambiguous=False`, `cadence=None` — a truth row tests the site, not the
       register).
    2. Build the real seams exactly as `verify_due_cycles._seams` does. Move that method to a
       module-level `build_seams(meter, parser, claude, *, source_id)` in `cycle_verification.py` so
       both commands share it.
    3. Run `verify_cycle(..., stored=[])` per distinct `(own_url, intake)`, reusing the verdict for
       the second profile of a conditional row.
    4. For each profile, evaluate
       `cycle_validity(to_evidence(verdict.entries, …), student=deadline_student(nationality,
       country_of_residence), …)` and `select_deadline` for `got_deadline`.
    5. `contradicted` is true when the engine says `OPEN`/`UPCOMING` and the row's `sentence`,
       labelled `SUSPENDED`/`ENDED`/`CLOSED_FOR_INTAKE`, is among the verdict's own evidence quotes.
    6. The projection backtest: `project_window(((prior_call_opened, None),), target_year=<year of
       last_call_opened>)` against `last_call_opened`.
    7. Print the report and, for every disagreement, the row, the engine's state and step, its
       quotes, and the trail.
  - Flags: `--truth <csv>`, `--dry-run` (lists the rows, estimates the credit ceiling as rows ×
    (own pages + `crawl_ceiling(CYCLE_CRAWL_LIMIT)`), spends nothing), `--out <md>` (appends the
    report).
  - It never writes a catalog row. A truth row is not an award in the catalog, and the gate must not
    make it one.

- [ ] **Step 4: Run the tests** — expected: pass.
- [ ] **Step 5: Commit** — `"feat(research): cycle_verify --truth, the 9.3 gate"`.

- [ ] **Step 6: Run the gate, live.** First the estimate:

```bash
uv run python manage.py cycle_verify --truth docs/research/2026-09-cycle-truth-set.csv --dry-run
```

  **Stop and ask the owner if the estimate exceeds what is left of the month's Firecrawl quota.** On
  the free tier (1,000 credits a month, §7) one crawl's worst case is 15 × (1 + 60) = 915 credits.
  The paid plans are not bought (decision log row 24). The gate may therefore need the plan, two
  months of free quota, or a temporary `FETCH_PDF_MAX_PAGES` override for this run. That is the
  owner's choice, and the override must be written into the gate note if taken. Then:

```bash
DATABASE_ROLE=migration uv run python manage.py cycle_verify \
  --truth docs/research/2026-09-cycle-truth-set.csv --out docs/superpowers/2026-09-cycle-verification-gate.md
```

- [ ] **Step 7: Record the result** in `docs/superpowers/2026-09-cycle-verification-gate.md` (never
  under `specs/`). Include:
  - the full report;
  - the date and the vendor plan in force;
  - `MODEL_LIST_PRICES_VERIFIED_ON`;
  - cost per verified scholarship against §9.3's $0.15–0.40;
  - the share of rows settled at step 0;
  - `cycles_without_opening` (plan decision 3);
  - the count of `hop_withheld` links and how many truth rows had no evidence except behind one
    (plan decision 1);
  - per-country recall (plan decisions 9–10);
  - the conditional-deadline accuracy per condition kind (the decision-side finding).

  **If the gate fails, the design changes, not the threshold** (§8.8's rule, repeated for this gate).
  Task 14 does not run. Open a follow-up with the disagreements.

- [ ] **Step 8: Commit** — `"docs: cycle-verification gate result, <PASS|FAIL>"`, pathspec the note.

---

### Task 14: Retire the interim rule — **only if Task 13 recorded PASS**

§16 item 11: "**Gate:** the truth set at ≥ 95%; the interim validity rule retires." Before this task,
`evaluate_award` hides only what is known shut. After it, only `OPEN` and `UPCOMING` for the
student's own intake are options (§9.1). An award with no verification row, or one still
`UNVERIFIED`, stays out of the recommended pack. It is excluded with the reason written out, never
silently.

**Files:**
- Modify: `apps/funding/facts.py`, `apps/funding/evaluation.py`, `apps/research/spine.py`
- Test: `tests/funding/test_award_gates.py`, `tests/funding/test_facts.py`, `tests/funding/test_spine.py`

- [ ] **Step 1: Change the tests first**
  - `tests/funding/test_award_gates.py`: the `_award` helper's default `evidence=Evidence()`
    becomes an OPEN evidence — `Evidence(deadline=dt.date(2027, 1, 15))` for the fixture's intake.
    Then `test_an_award_with_nothing_against_it_is_eligible` still means what it says.
  - Replace `test_an_unverified_award_is_still_eligible_and_that_is_deliberate` with:

```python
def test_an_unverified_award_is_not_an_option_and_says_why(profile):
    """Spec 9.1: only OPEN and UPCOMING are shown. The interim rule this
    replaces let UNVERIFIED through because no ladder existed; one does now,
    and the gate that licensed this change is recorded in
    docs/superpowers/2026-09-cycle-verification-gate.md."""
    outcome = evaluate_award(profile, _award(evidence=Evidence()), today=TODAY)
    assert outcome.outcome == "NOT_ELIGIBLE"
    assert "not yet verified" in outcome.reasons[0]


def test_an_upcoming_award_is_an_option(profile):
    evidence = Evidence(past_calls=((dt.date(2026, 3, 3), dt.date(2026, 5, 15)),
                                    (dt.date(2025, 3, 4), dt.date(2025, 5, 16))))
    assert evaluate_award(profile, _award(evidence=evidence), today=TODAY).outcome == "ELIGIBLE"


def test_a_non_eu_student_gets_the_non_eu_deadline(profile):
    """The decision-side finding the plan records: without applicant_class a
    non-EU student was shown the general (later) date."""
    evidence = Evidence(deadlines=((dt.date(2026, 11, 1), "APPLICANT_CLASS:NON_EU"),
                                   (dt.date(2027, 1, 15), "ALL")))
    non_eu = profile.model_copy(update={"nationality": "AZ"})
    outcome = evaluate_award(non_eu, _award(evidence=evidence), today=dt.date(2026, 12, 1))
    assert outcome.outcome == "NOT_ELIGIBLE" and "2026-11-01" in outcome.reasons[0]
```

  Adapt `profile.model_copy(...)` to however the fixture builds `StudentProfileSnapshot`, and keep
  `TODAY` before the fixture intake's 1 September.
  - `tests/funding/test_facts.py`: `award_facts(award, benefits=..., rules=..., verification=row)`
    builds `Evidence` through `cycle_evidence.to_evidence`; with `verification=None`, it builds
    `Evidence()` → `UNVERIFIED`.
  - `tests/funding/test_spine.py`: the pack for a student whose award has an `OPEN` row for their
    intake includes it; the same award with only a row for another intake does not.

- [ ] **Step 2: Run** — expected FAIL on exactly the new and changed tests.

- [ ] **Step 3: Implement**
  - `facts.award_facts(..., verification: FundingCycleVerification | None = None)`. The evidence is
    `to_evidence(verification.evidence, target_year=verification.intake_start_year,
    cadence=<the organisation's RegisterCadence or None>, page_removed=verification.page_removed,
    lapsed=verification.projection_lapsed)` when a row exists, else `Evidence()`. The suspension
    fields on the row stay as they are; `to_evidence` already carries the per-intake NO. Replace the
    comment "Step-0 evidence only…" with one line pointing at the row.
  - `evaluation.evaluate_award`: the student dict becomes
    `deadline_student(profile.nationality, profile.country_of_residence)`. Gate 2 becomes:

```python
    if validity not in ("OPEN", "UPCOMING"):
        reason = {
            "SUSPENDED": f"{award.name} is not offered for {target_intake} on its own page",
            "ENDED": f"{award.name} is no longer offered on its own page",
            "CLOSED_FOR_INTAKE": f"{award.name} has closed for the {target_intake} intake",
            "UNVERIFIED": f"{award.name} is not yet verified as open for {target_intake}",
        }[validity]
        return RecommendationOutcome("NOT_ELIGIBLE", (reason,), None)
```

    The docstring paragraph beginning "**Gate 2 is deliberately weaker…**" is replaced by one
    sentence: "Gate 2 is §9.1's rule: only OPEN and UPCOMING for the student's own intake, decided
    from the award's `FundingCycleVerification` row; the gate that licensed this is recorded in
    docs/superpowers/2026-09-cycle-verification-gate.md."
  - `spine.py`: prefetch
    `FundingCycleVerification.objects.filter(opportunity__in=pool.awards,
    intake_start_year=profile.intended_intake.year)` into a dict by `opportunity_id`, and pass
    `verification=` to `award_facts`.

- [ ] **Step 4: Run** the whole suite — expected: all pass.
- [ ] **Step 5: Lint, type-check, commit** — `"feat(funding): only OPEN and UPCOMING for the student's own intake -- the interim validity rule retires (gate: <link>)"`.

---

## Self-Review

**Spec coverage.**

| requirement (master spec) | task |
|---|---|
| §9.2 ladder step 0: own pages already read, ~$0 | 6 (stored at write time), 7 (changeTracking re-check, unchanged = no read) |
| §9.2 step 1: crawl on the cycle vocabulary + year tokens, `limit: 15`, name/year string filter, no model | 1, 8 |
| §9.2 step 1b: Wayback captures of the call page, previous two cycles, read once, cached for good | 9 |
| §9.2 step 1c: register cadence, expiring | 5 (`to_evidence` → `RegisterCadence`, whose expiry validity already applies), 9 |
| §9.2 step 2: one hop from the crawl's links, as a single page | 10 (own domains only — decision 1) |
| §9.2 step 3: one Exa `includeDomains`, `numResults: 10`; Brave `site:` only if Exa returns nothing | 10 |
| §9.2 each step only when the previous found nothing decisive | 7 (`verify_cycle` loop) |
| §9.2 negations join their award; the more specific wins; the latest date wins a contradiction | 7 (`joins`), 5 (`_rank`) |
| §9.2 intakes normalise to a start year by one tested helper | reuses `validity.intake_start_year` |
| §9.2 whose deadline: `deadline_for` → the condition vocabulary, Wikidata labels as data, `OTHER:` kept | 2 |
| §9.2 `cycle_validity` selects the student's deadline | unchanged; 14 feeds it and adds `applicant_class` |
| §9.3 cadence: monthly; weekly two months before last call; daily within 14 days; weekly from one month before a projection | 5 (`next_check`), 11 |
| §9.3 `OPEN` closes itself at its deadline; becomes `UPCOMING` for the next intake when it recurs | validity already does the first; 5 (`tracked_intakes`) + 11 (`_ensure_tracked`) give the next intake its own row |
| §9.3 `UPCOMING` with no call 45 days past the projection → `UNVERIFIED` | 5 (`projection_lapsed`), 7 (`_finish`) — evidence side, decision 4 |
| §9.3 every check through `changeTracking` | 7 (`fetch_page(tag=...)`), a distinct tag from the monitors |
| §9.3 `FundingCycleVerification` fields, `cost_usd` recorded never estimated | 3, 4, 11 |
| §9.3 "the pack version bumps and the student is told" | **not here** — see below |
| §9.3 gate: truth set, known-answer rows, ≥ 10 conditional rows, precision ≥ 95% on OPEN and UPCOMING, projection hit rate, zero contradicted | 12, 13 |
| §9.3 "the sweep report prints cost per verified scholarship" | 13 (the gate), 11 (per row, per run) |
| §8.6 withdrawal; §19 the owed unserve sweep for a page nothing re-reads | 11 (the verifier re-reads the page monthly; a silent sole page withdraws the award) |
| §12 shared catalog, RLS, `_SHARED_TABLES`, verified through `runtime_connection` | 3 |
| §16 item 11: "the interim validity rule retires" | 14, conditional on 13 |
| brief: no hard-coded migration number; expect a merge migration | Global Constraints, Task 3 Step 4 |

**Deliberately not in this plan, with the trigger that would build it:**

| not built | trigger |
|---|---|
| "the pack version bumps and the student is told" when a state degrades (§9.3) | The first pack published to a real student after Task 14. It needs a pack re-run trigger and a notification path that belong to the serving side (items 4/14), not to verification |
| the internal university deadline for `INSTITUTION_NOMINATES` holder awards (§9.2) | It is a per-(award, institution) pair, and the catalog cannot enumerate those pairs without demand. Item 14's demand cells are the trigger. Until then validity's `missing_for` and the card's "stated but not read" carry it |
| `recurrence_stated` ("the page says every March") | The judge has no field for a stated month. Build it when item 13 writes `cycle` with a month the reader verified |
| off-domain hops (portal landing pages) | An owner decision reversing plan decision 1, measured by the gate's `hop_withheld` count |
| local-language search queries, vocabulary beyond §9.2's terms | The gate's per-country recall shows a language losing evidence. Each term is then added with a source |
| Batch/Flex for ladder reads | Item 15 |
| `served` carrying the cycle clause | Never, per decision 7. The evaluator carries it per intake. Revisit only if a consumer other than the evaluator reads `served` as "open" |

**Known gaps, flagged in place:** the two decision-side findings (autumn deadlines; `APPLICANT_CLASS`
matching); the one-award-several-intakes row collision in `write_holder_decision`; the Firecrawl
free-tier quota against the gate's crawl ceiling (Task 13 Step 6); the worker task definition's
missing `ANTHROPIC_API_KEY` and the `catalog_ingestion` connection option, both prerequisites to
enabling `VerifyDueCyclesRule`, as they already are for `RetryDueFetchesRule`.

**Placeholder scan:** Task 3's `<leaf+1>`/`<leaf+2>` and Task 4's price numbers are values that can
only be known when the task runs: a migration leaf and a vendor's price on the day. Each has an exact
instruction for obtaining it. Nothing else is left to the executor's invention.
