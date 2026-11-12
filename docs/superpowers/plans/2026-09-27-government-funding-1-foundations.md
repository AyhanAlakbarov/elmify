# Government funding discovery, plan 1 of 5 -- foundations: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the five shared pieces every government-funding route needs: an answer key to grade the
routes, one list of government domains, funding words per language, a citable page for a national
agency whose host is also a catalogue, and pointer names that turn into leads. The reader also
learns which degree level each award track is for, and stops writing loans.

**Architecture:** Mostly changes to modules that already exist in `apps/research`: `domains.py`,
`discovery.py`, `funding_judge.py`, `funding_reader.py`, `resolve_entries.py`, `resolution/`, and
`resolve_register`. There are three new modules:

- `answer_key.py`: the yardstick.
- `pointers.py`: pointer names become `pointer` register rows, then leads.
- `management/commands/read_pointers.py`.

Two tables gain columns: `FundingOpportunity.target_level`, and `RegisterEntry.pointer_quote` and
`pointer_url`. No table is added. The pointer path reuses the resolver pipeline that already reads
every other register: `RegisterEntry`, `resolve_register`, and the `SITE_UNKNOWN` queue kind and its
applier. It adds no second name-to-site path.

**Tech stack:** Django 5.2, Postgres 17 with RLS, Pydantic v2 (`extra="forbid"`), the OpenAI
Responses API and the Anthropic Messages API through the existing `ResponsesAPI` / `MessagesAPI`
protocols, and pytest. There are no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-27-government-funding-discovery-design.md`. This plan covers:

- §3: the answer key.
- §4.1: "one list of government domains" only. The body list is plan 2.
- §4.2: funding words, and the routing-host agency exemption. Site reading is plan 2.
- §4.7: pointers become leads.
- §7.1: target level and no loans.
- §8 step 1: the provenance merge, as this plan's gate.

The master spec (`2026-09-22-funding-search-engine-master-design.md`) is read where §4.7 says its
"pointers become leads (built 2026-09-18)" is stale. It is: nothing on `master` turns a pointer name
into anything.

**Base:** `origin/master` after `claude/provenance-gate-design` has merged (Task 0). Cut a work branch
from there. The worktree is `/home/orkhan/Desktop/gov-funding-design`. **Always use
`git -C /home/orkhan/Desktop/gov-funding-design`**, because the shell's cwd resets. The test database
is `POSTGRES_DB=elmify_gov`, and it is never shared.

---

## What this plan depends on

| needs | from | state on 2026-09-27 | what this plan does |
|---|---|---|---|
| `recognition.GOVERNMENT_ZONES` / `government_zone()` | `claude/provenance-gate-design` (tip `6429e905`) | **unmerged** | Task 0 refuses to start until it is on `origin/master`; Task 2 folds it into `domains.py` |
| `docs/research/closed-lists/national_scholarship_agencies.csv` (the reviewed agency list) | the same branch | unmerged | Task 4 reads it |
| `resolve_register` + `resolver.Resolver` + `record_resolution` | build item 8, on master | built; **writes gated by `RESOLVER_WRITES_ENABLED`, off by default** | pointers ride it. So until the resolver's hold-out gate is switched on, pointer rows are resolved dry-run only and no pointer becomes a lead. That is the existing gate, and it is not bypassed here |
| `SITE_UNKNOWN` kind + its applier (`resolution/apply._site_unknown`) | the resolution queue, on master | built; **nothing files one yet** | Task 9 adds the first filer, for pointer rows only |

The provenance branch carries `research/0012_provenance`, `0013_closedlist_terms_restricted` and
`funding/0052_provenance`. Both apps will therefore have merge migrations after it lands. That is
why every migration step here reads the real leaf, and never uses the numbers quoted in this plan.

## Deliberately not in this plan (spec split, 2026-09-27)

- **Plan 2: the body list and the routes that are not social.** It covers:
  - §4.1 bodies, ministries of every sector, the Wikidata class × country rows, and the ten-city sample;
  - `OrganisationDomain.path_prefix` for embassies;
  - §4.2 site reading (map the site, keep pages with a funding word; this plan only supplies the words);
  - `HOST_UNREACHABLE` for a body's site;
  - §4.3 gazettes, §4.4 the receiving side, §4.5 Wikidata scheme entries, and §4.6 news names;
  - the per-route answer-key measurement;
  - adding reviewed agencies as `FUNDING_READ` rows, so that Task 4's exemption has a page to read;
  - regenerating `tr_outbound_gov` / `az_outbound_gov` (§10).

  Two items are left there on purpose:
  1. **Pointers from programme pages.** `pipeline._fund_page` counts a programme page's POINTER lines
     and throws their names away. §4.4 ("destination universities' pages that name outside funders")
     is where they start feeding `record_pointers`. Wiring them here would change a route plan 2 owns.
  2. **The reader's section selector.** `funding_reader._FUNDING_TERMS` is English plus three
     cognates. An Azerbaijani, Turkish or Russian page that matches no term is read whole, so it is
     not lost. But one that matches an English word somewhere is narrowed to that section. Plan 2
     decides whether that selector reads the funding words, with a measurement.
- **Plan 3:** the social reader (§5, §5.1, §5.2), with `SocialAccount`, `SocialPost` and the
  post-sourced serving rule.
- **Plan 4:** same-scheme links (§6), with `SchemeLink`, `SAME_SCHEME`, and funder vs. administrator.
- **Plan 5:** the one-tap eligibility card (§7.2). This plan makes each **decision** carry only its
  own track's conditions (§7.1). The reader persists no condition to the database today: it reads
  `FundingDecision.conditions`, and only `manage.py funding_yield` does anything with them. Making
  them reach a student is plan 5's.
- **§10's `ClosedList.Terms.UNREAD` removal.** The provenance branch already rewrites the
  "read by hand" docstrings (`73e27c4a`, "terms are recorded, not a gate"). Whatever remains after
  it merges belongs with plan 2's regeneration of the two government lists.

---

## Global constraints

- **Students first: Azerbaijani and Turkish.** Adding a home country is data, never code (spec
  header). No code path here names a country.
- **What counts: "only money that can fund a master's degree... No loans."** `LOAN` rows are no
  longer written. `FORGIVABLE_LOAN` and bonded scholarships "**count** and are shown with the
  obligation stated" (§7.1). That reading is still owed an owner confirmation (§12), and is listed
  again under "Open decisions".
- **"A scheme with no `MASTER` or `ANY` track is not written"** (§7.1). A track whose level the page
  never states is written, with `target_level=UNSTATED`. See Open decisions.
- **A pointer is a name, never provenance.** Nothing here reads a URL printed in page text, and a
  `pointer` register row vouches for nothing.
- **No new table in this plan.** New columns on `FundingOpportunity` and `RegisterEntry` inherit
  their table's RLS:
  - `shared_catalog_select`;
  - `runtime_engine_write` TO `runtime_engine` (repointed from `catalog_ingestion` by `funding/0049`);
  - no grant for `runtime_web`.

  Each new column still gets a test through a real `NOBYPASSRLS` login (`runtime_connection` /
  `role_connection`), because the test role bypasses RLS (CLAUDE.md). **Never
  `catalog_ingestion`.**
- **Never hard-code a migration number.** Before generating, run
  `ls apps/<app>/migrations/ | sort | tail -3`. After the provenance merge, `research` will be past
  `0017_merge_20260927_0833` and `funding` past `0054_pack_coverage`. If `makemigrations` reports
  conflicting leaves, run `makemigrations <app> --merge` first, and name the real leaf in
  `dependencies`.
- **Model calls follow the reference pattern.** That means data-labelled input, `extra="forbid"`,
  capped `max_output_tokens`, and `store=False`. **Any new or changed model-calling path carries
  `rate_limited()` in the same change:**
  - Tasks 5 and 7 change the judge's answer schema and add no caller. Every existing caller already
    pays through `pipeline._pay_for_funding` (`rate_limited("discovery-extraction", ...)`) or
    `cycle_verification`'s meter.
  - Task 10's `read_pointers` is a new caller. It goes through `run_discovery`, so the same limiter
    applies per page before the first reading. No new limiter is written.
- **Only a URL is read from a provider.** The resolver already keeps nothing but a registrable
  domain, and this plan does not change that.
- **No test makes a network, vendor or model call.** Fakes only. The live steps in Tasks 1, 2 and 3
  are research steps. They run by hand, not in `pytest`.
- **Spend.** Tasks 1 to 3 fetch about 40 public pages through `fetch_page`, at about 1 Firecrawl
  credit each (under $0.50). This is the answer-key measurement §8 already permits, plus zone and
  word citations. Nothing else in this plan is billed.
- **After every task, run all of these. Never `ruff format`:**

  ```bash
  POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research tests/funding tests/tenancy
  uv run ruff check apps tests config scripts
  uv run mypy apps config
  POSTGRES_DB=elmify_gov uv run python manage.py makemigrations --check --dry-run
  uv run bandit -c pyproject.toml -r apps config -q
  ```

## Review Focus

These are the five inputs most likely to bite a student or an operator. Each has a test in its
owning task.

1. **A scheme page with bachelor's, master's and doctoral tracks under one heading.** This is the
   State Programme's own shape. A master's applicant must get only the master's track's conditions
   and the general ones, never the bachelor's age bar. The test is Task 5,
   `test_three_tracks_under_one_heading_keep_only_the_master_s_conditions`.
2. **A page that never names a degree level.** Most foundation and ministry pages don't. It must
   still be written, never silently dropped. The tests are Task 5,
   `test_a_page_that_names_no_level_is_still_decided`, and Task 6,
   `test_a_row_records_the_track_it_was_read_for`.
3. **An operator answering a disputed `money_form` with `LOAN` in the queue.** That must not serve a
   loan through the back door. The test is Task 6,
   `test_an_operator_cannot_serve_a_loan_through_the_queue`.
4. **A programme listing on DAAD's or Campus France's host.** Only the agency's own schemes become
   citable; a listing of other people's programmes stays routing-only. The test is Task 4,
   `test_a_programme_listing_on_an_agency_host_stays_routing_only`.
5. **A pointer the resolver could not place because a fetch failed, or a dry run.** Neither may file
   a person's question: the first is retried by the resolver after a week, and the second writes
   nothing. The tests are Task 9, `test_a_fetch_failure_asks_nobody_yet` and
   `test_a_dry_run_asks_nobody`.

## File map

| file | change |
|---|---|
| `apps/research/answer_key.py` | new: loader and validator (Task 1) |
| `docs/research/government-funding-answer-key.csv` | new: researched rows (Task 1) |
| `apps/research/domains.py` | `Zone`, `VERIFIED_ZONES` replacing `VERIFIED_SECOND_LEVEL`, `government_zone_of` (Task 2); `AGENCY_LIST`, `reviewed_agency_domains`, `is_reviewed_agency` (Task 4) |
| `apps/research/recognition.py` | `GOVERNMENT_ZONES` deleted; `government_zone` reads `domains` (Task 2) |
| `docs/research/cycle-vocabulary.csv`, `apps/research/cycle_vocabulary.py` | the `funding` role and its rows (Task 3) |
| `apps/research/discovery.py` | `ResearchLead.from_url`: the agency exemption (Task 4) |
| `apps/research/funding_judge.py` | `target_level` (Task 5); `funder` on pointers (Task 7) |
| `apps/research/pipeline.py` | `FundingCounts.other_levels` (Task 5); `take_pointers` records rows (Task 8) |
| `apps/funding/models.py` + `apps/funding/migrations/<leaf+1>_opportunity_target_level.py` | `target_level` (Task 6) |
| `apps/research/funding_reader.py` | writes `target_level`, never a `LOAN` (Task 6) |
| `apps/research/resolution/apply.py` | refuses an operator's `LOAN` (Task 6) |
| `apps/research/models.py` + `apps/research/migrations/<leaf+1>_register_entry_pointer.py` | `pointer_quote`, `pointer_url` (Task 8) |
| `apps/research/pointers.py` | new: `record_pointers` (Task 8); `pointer_route`, `ask_for_site` (Task 9); `PointerSource` (Task 10) |
| `apps/research/resolution/writers.py` | `file_site_unknown` (Task 9) |
| `apps/research/resolve_entries.py` | `record_resolution(found_via=)` (Task 9) |
| `apps/research/management/commands/resolve_register.py` | serves `pointer`; tags and asks (Task 9) |
| `apps/research/management/commands/read_pointers.py` | new (Task 10) |
| `tests/research/test_answer_key.py`, `test_funding_words.py`, `test_agency_exemption.py`, `test_funding_judge_level.py`, `test_funding_judge_pointer.py`, `test_pointers.py`, `test_target_level_rls.py`, `test_register_entry_pointer_rls.py` | new |
| `tests/research/test_domains.py`, `test_recognition_lists.py`, `test_funding_reader.py`, `test_pipeline_funding.py`, `test_resolve_register_command.py`, `resolution/test_apply.py` | extended |

---

## Task 0: The gate: the provenance branch is on master, and the files are re-read

This is not a code task. It decides whether the plan may start, and against which lines.

- [ ] **Step 1: Refuse to start until the branch is merged.** A squash merge leaves no ancestry, so
  the test checks for the content, not the commit:

```bash
git -C /home/orkhan/Desktop/gov-funding-design fetch origin
git -C /home/orkhan/Desktop/gov-funding-design show origin/master:apps/research/recognition.py | grep -n "GOVERNMENT_ZONES\|^def government_zone"
git -C /home/orkhan/Desktop/gov-funding-design show origin/master:docs/research/closed-lists/national_scholarship_agencies.csv | head -1
```

  If it is merged, the output is two or more `recognition.py` lines, then
  `external_key,name,kind,website,page_url,...`.

  If git prints `fatal: path 'apps/research/recognition.py' does not exist in 'origin/master'`,
  **STOP.** Report "Plan 1 is blocked: claude/provenance-gate-design is not merged", and do nothing
  else.

- [ ] **Step 2: Cut the work branch from master.**

```bash
git -C /home/orkhan/Desktop/gov-funding-design switch -c claude/gov-funding-1-foundations origin/master
```

- [ ] **Step 3: Re-read the real files, and compare them with what this plan quotes.** The plan was
  written against branch tip `6429e905` and master `a67820e5`. Run:

```bash
cd /home/orkhan/Desktop/gov-funding-design
sed -n '/^GOVERNMENT_ZONES/,/^def name_variants/p' apps/research/recognition.py
grep -n "GOVERNMENT_ZONES" tests/research/test_recognition_lists.py
sed -n '/^VERIFIED_SECOND_LEVEL/,/^}/p' apps/research/domains.py
grep -n "^def registrable_domain" -A 16 apps/research/hosts.py
ls apps/research/migrations | sort | tail -3; ls apps/funding/migrations | sort | tail -3
grep -n "def from_url" -A 40 apps/research/discovery.py | grep -n "is_catalogue"
```

  Expected:
  - the six-zone tuple and the loop-shaped `government_zone`, as quoted in Task 2 Step 3;
  - the test file imports `GOVERNMENT_ZONES` and uses it in `test_every_zone_cites_its_registry_policy`;
  - `VERIFIED_SECOND_LEVEL` holds the 23 zones Task 2 rewrites;
  - `registrable_domain` still takes a host or a URL;
  - one research leaf and one funding leaf. Write both names down for Tasks 6 and 8.

  **If a quoted shape differs**, adapt the one step that uses it, and name the difference in that
  task's commit message. If `government_zone` no longer returns a `Recognition` built from a zone and
  a citation, stop and report: Task 2's design rests on that shape.

- [ ] **Step 4: Prove the baseline is green before any change.**

```bash
cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research tests/funding tests/tenancy
```

  Expected: every test passes (the `live` ones are deselected). Record the count. A red baseline is
  reported, never fixed silently in this plan.

---

## Task 1: The answer key, built first and independent of what it grades (§3)

**Files:**
- Create: `apps/research/answer_key.py`
- Create: `docs/research/government-funding-answer-key.csv`
- Test: `tests/research/test_answer_key.py`

**Interfaces:**
- Consumes: `apps.research.hosts.registrable_domain(value: str) -> str`.
- Produces:
  - `read_answer_key(path: Path = ANSWER_KEY, *, today: dt.date | None = None) -> tuple[KeyRow, ...]`;
  - `KeyRow(scheme, funder, funder_domain, official_url, checked_on: dt.date, found_by: frozenset[str], notes)`, with the `only_web_search: bool` property;
  - `AnswerKeyError(ValueError)`, `COLUMNS`, `FOUND_BY`, `ANSWER_KEY`.

  Task 3 and plan 2's measurement read these.

- [ ] **Step 1: Write the failing tests.** Create `tests/research/test_answer_key.py`:

```python
"""The government-funding answer key (spec 2026-09-27 §3) is data; these pin how it is read."""

import datetime as dt
from pathlib import Path

import pytest

from apps.research.answer_key import COLUMNS, AnswerKeyError, read_answer_key

HEADER = ",".join(COLUMNS)
TODAY = dt.date(2026, 9, 27)
GOOD = (
    "Scheme A,Example Ministry,example-ministry.az,https://example-ministry.az/scheme-a,"
    "2026-09-27,direct_site|web_search,"
)


def _key(tmp_path: Path, *rows: str, header: str = HEADER) -> Path:
    path = tmp_path / "key.csv"
    path.write_text("\n".join((header, *rows)) + "\n", encoding="utf-8")
    return path


def test_a_valid_row_reads_with_every_method_that_found_it(tmp_path: Path) -> None:
    (row,) = read_answer_key(_key(tmp_path, GOOD), today=TODAY)
    assert row.scheme == "Scheme A" and row.funder_domain == "example-ministry.az"
    assert row.checked_on == TODAY
    assert row.found_by == {"direct_site", "web_search"}
    assert row.only_web_search is False


def test_a_row_found_only_by_web_search_is_marked_for_separate_reporting(tmp_path: Path) -> None:
    row = GOOD.replace("direct_site|web_search", "web_search")
    (read,) = read_answer_key(_key(tmp_path, row), today=TODAY)
    assert read.only_web_search is True


@pytest.mark.parametrize(
    ("row", "why"),
    [
        (GOOD.replace("Scheme A,", ",", 1), "scheme and funder"),
        (GOOD.replace(",example-ministry.az,", ",www.example-ministry.az,"), "registrable"),
        (GOOD.replace("https://example-ministry.az", "http://example-ministry.az"), "https"),
        (GOOD.replace("2026-09-27", "2026-09-28"), "future"),
        (GOOD.replace("2026-09-27", "27.09.2026"), "ISO"),
        (GOOD.replace("direct_site|web_search", "google"), "found_by"),
        (GOOD.replace("direct_site|web_search", ""), "found_by"),
    ],
)
def test_a_bad_row_refuses_the_whole_file_naming_its_line(
    tmp_path: Path, row: str, why: str
) -> None:
    with pytest.raises(AnswerKeyError, match=rf"line 2: .*{why}"):
        read_answer_key(_key(tmp_path, row), today=TODAY)


def test_a_wrong_header_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AnswerKeyError, match="header"):
        read_answer_key(_key(tmp_path, GOOD, header="scheme,funder"), today=TODAY)


def test_one_scheme_listed_twice_for_one_funder_is_refused(tmp_path: Path) -> None:
    twice = GOOD.replace("Scheme A,", "SCHEME A,", 1)
    with pytest.raises(AnswerKeyError, match="line 3: .*already listed"):
        read_answer_key(_key(tmp_path, GOOD, twice), today=TODAY)


def test_the_committed_key_reads_and_opens_with_mystart() -> None:
    """The owner's bar (spec header): MyStart is row one. And at least one row
    was found by something other than web search, or the search routes would be
    graded on their own output alone (§3)."""
    rows = read_answer_key()
    assert rows, "the answer key is empty: Task 1 Step 5 has not been done"
    assert "mystart" in rows[0].scheme.casefold()
    assert any(not row.only_web_search for row in rows)
```

- [ ] **Step 2: Run them, and confirm that they fail.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_answer_key.py`

  Expected: FAIL (collection error), `ModuleNotFoundError: No module named 'apps.research.answer_key'`.

- [ ] **Step 3: Write the loader.** Create `apps/research/answer_key.py`:

```python
"""The government-funding answer key (spec 2026-09-27 §3): a yardstick, never a limit.

Built by hand from online research, before any route it grades exists, so it
cannot be the output of the routes it measures. Rows found only by web search
are reported apart (`only_web_search`): the search routes would otherwise be
graded on their own findings. Matching a route's finding to a row is a
person's call in the measurement report -- names differ by language -- so
nothing here compares names. It grows; it never limits what is served.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from django.utils import timezone

from .hosts import registrable_domain

ANSWER_KEY = (
    Path(__file__).resolve().parents[2] / "docs" / "research" / "government-funding-answer-key.csv"
)
COLUMNS = ("scheme", "funder", "funder_domain", "official_url", "checked_on", "found_by", "notes")
#: How a row was found: browsing the funder's own site, a government portal or
#: directory, a search engine, or the owner. Several joined by "|".
FOUND_BY = frozenset({"direct_site", "gov_portal", "web_search", "owner"})


class AnswerKeyError(ValueError):
    """A row the key cannot hold, named by its line number."""


@dataclass(frozen=True)
class KeyRow:
    scheme: str
    funder: str
    funder_domain: str
    #: The scheme's official page, or the post URL for a post-only scheme.
    official_url: str
    checked_on: dt.date
    found_by: frozenset[str]
    notes: str

    @property
    def only_web_search(self) -> bool:
        return self.found_by == {"web_search"}


def _row(line: int, raw: dict[str, str | None], today: dt.date) -> KeyRow:
    cell = {name: (raw.get(name) or "").strip() for name in COLUMNS}

    def refused(why: str) -> AnswerKeyError:
        return AnswerKeyError(f"answer key line {line}: {why}")

    if not cell["scheme"] or not cell["funder"]:
        raise refused("scheme and funder are required")
    domain = cell["funder_domain"].casefold()
    if not domain or registrable_domain(domain) != domain:
        raise refused(f"funder_domain {cell['funder_domain']!r} is not a registrable domain")
    url = urlsplit(cell["official_url"])
    if url.scheme != "https" or not url.hostname:
        raise refused(f"official_url {cell['official_url']!r} is not an https URL")
    try:
        checked = dt.date.fromisoformat(cell["checked_on"])
    except ValueError:
        raise refused(f"checked_on {cell['checked_on']!r} is not an ISO date") from None
    if checked > today:
        raise refused(f"checked_on {checked} is in the future")
    found_by = frozenset(part.strip() for part in cell["found_by"].split("|") if part.strip())
    if not found_by or not found_by <= FOUND_BY:
        raise refused(f"found_by must be one or more of {sorted(FOUND_BY)} joined by '|'")
    return KeyRow(
        scheme=cell["scheme"],
        funder=cell["funder"],
        funder_domain=domain,
        official_url=cell["official_url"],
        checked_on=checked,
        found_by=found_by,
        notes=cell["notes"],
    )


def read_answer_key(
    path: Path = ANSWER_KEY, *, today: dt.date | None = None
) -> tuple[KeyRow, ...]:
    """Every row, validated, in file order. One bad row refuses the whole file:
    a yardstick with a silently skipped row grades against a different key."""
    day = today or timezone.localdate()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise AnswerKeyError(f"answer key header must be {','.join(COLUMNS)}")
        rows = tuple(_row(number, raw, day) for number, raw in enumerate(reader, start=2))
    seen: set[tuple[str, str]] = set()
    for number, row in enumerate(rows, start=2):
        key = (row.funder_domain, row.scheme.casefold())
        if key in seen:
            raise AnswerKeyError(
                f"answer key line {number}: {row.scheme!r} is already listed for "
                f"{row.funder_domain}"
            )
        seen.add(key)
    return rows
```

  Create `docs/research/government-funding-answer-key.csv` with the header line only:

```csv
scheme,funder,funder_domain,official_url,checked_on,found_by,notes
```

- [ ] **Step 4: Run the tests.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_answer_key.py`

  Expected: 11 passed, 1 failed. The failure is
  `test_the_committed_key_reads_and_opens_with_mystart` ("the answer key is empty"). It stays red
  until Step 5.

- [ ] **Step 5: Research the rows online. Never invent one.** The target is **about 30 government
  schemes that can fund an Azerbaijani's or a Turkish citizen's master's study**, from every level
  of government (§3, header).

  **Rules for every row:**
  1. **Row one is MyStart**, the Azerbaijani Ministry of Culture's scheme. It is the owner's bar.
  2. A row exists only for a scheme you found **online** today, whose page (or, for a post-only
     scheme, whose official account's post) you opened and read. The page must say, in its own
     words, that it pays for master's study or waives its tuition. Leave out loans. Leave out
     conference and short-course travel, research visits, and bachelor's-only and PhD-only schemes
     (spec header).
  3. `funder_domain` is the registrable domain of the **funder's own site**. For a body whose site
     is a path on another domain, such as an embassy under `gov.uk`, use that domain and say so in
     `notes`. A body with no website at all is out of scope (§4.1): note it in the commit message,
     not in the file.
  4. `found_by` names every method that found the row, independently:
     - `direct_site`: you browsed the funder's own site from its home page;
     - `gov_portal`: a government portal or directory led to it;
     - `web_search`: a search engine returned it;
     - `owner`: the owner named it.

     Try at least two methods per row. A row found only by `web_search` is allowed, and it is
     reported apart.
  5. `checked_on` is the day you fetched it (Step 6 does the fetch). `notes` says what the page
     states: the level, the country, and any obligation such as bonded service.

  **Where to look.** These are search leads, not rows:
  - Azerbaijan: every ministry on `*.gov.az` (culture, youth and sports, digital development,
    health, agriculture, economy, education), the State Programme page the `az_outbound_gov` list
    already cites, the president's decrees, the central bank, SOCAR, and the Baku and Ganja city
    executive powers.
  - Türkiye: YLSY (the `tr_outbound_gov` list), TÜBİTAK BİDEB, the ministries on `*.gov.tr`, and
    metropolitan municipalities on `*.bel.tr`.
  - Destination side: DAAD, Campus France, the Swedish Institute, Chevening, Stipendium Hungaricum
    and CSC (the reviewed agency list), and the embassies of those countries in Baku and Ankara.

  Write the rows into `docs/research/government-funding-answer-key.csv`, MyStart first.

- [ ] **Step 6: Fetch every row live, through the vendor ladder (never our own egress).** Run:

```bash
cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run python manage.py shell -c '
from apps.research.answer_key import read_answer_key
from apps.research.fetch import fetch_page
for row in read_answer_key():
    page = fetch_page(row.official_url, purpose="read", tag="answer-key")
    print(page.outcome, page.final_url, "|", row.scheme)
'
```

  Expected: each line reads `FETCHED` or `FETCHED_PARTIAL`, followed by a final URL on the funder's
  domain, or on the platform for a post.

  If a row prints `BLOCKED` or `UNREACHABLE`, open the URL yourself. Keep the row if a person can
  read it, and write the outcome in `notes`. That is exactly the host a route will meet.

  If a row prints `DEAD`, re-find the scheme or delete the row.

- [ ] **Step 7: Run the tests again.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_answer_key.py`

  Expected: 12 passed.

- [ ] **Step 8: Commit.**

```bash
git -C /home/orkhan/Desktop/gov-funding-design add apps/research/answer_key.py docs/research/government-funding-answer-key.csv tests/research/test_answer_key.py
git -C /home/orkhan/Desktop/gov-funding-design commit -m "feat(research): the government-funding answer key and its loader (spec 2026-09-27 §3)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 9: Hand the file to the owner.** §3 says "the owner reviews the file last and adds
  what they know", and §12 names the sign-off as the owner's. In the task report, give the row
  count, the number of rows found only by web search, and every row whose fetch was not `FETCHED`.

---

## Task 2: One list of government domains (§4.1 "one list")

`domains.VERIFIED_SECOND_LEVEL` (master) maps a zone to a holder kind, and the classifier reads it.
`recognition.GOVERNMENT_ZONES` (provenance) maps a zone to a citation, and provenance reads it. They
become one table, `domains.VERIFIED_ZONES`, with one `Zone(kind, government, citation)` per zone.

- **Classifier behaviour is unchanged**, except for the zones below whose citation could not be
  found.
- **Provenance recognition widens** to master's government zones (`gov.az`, `bel.tr`, `gov.uk`, and
  the rest), which is what "one list" asks for.
- The provenance branch's zones carry `kind=""`, so the classifier never starts answering for them.
  `.gov`, for example, admits federal, state and city bodies alike.

**Citations, requested on 2026-09-27 while writing this plan:**

- **TRABİS `https://www.trabis.gov.tr/content/Belgeli`** covers `gov.tr`, `bel.tr`, `edu.tr` and
  `k12.tr`. It reads "Belge ibraz edilerek tahsis edilebilecek olan “av.tr”, “bel.tr”, ... “edu.tr”,
  “gov.tr”, “k12.tr” ...".
- **`gov.az`:** `scis.gov.az` reads "Domain registration in the GOV.az zone The State Body ... applies
  in written form to the Special State Protection Service".
- **`gov.in`:** MeitY's guidelines read "3.1 Eligibility for securing registration under .GOV.IN".
- **`ac.in` / `edu.in`:** ERNET's registration guidelines.
- **`gov.pk`:** PKNIC reads "GOV.PK is used primarily for the Federal Government of Pakistan".
- **`edu.pk`:** PKNIC reads "must be a bona fide educational institute".
- **`go.id` / `ac.id`:** PANDI's registration policy v9.0 reads ".ac.id, is allocated for Higher
  Educational Institution ..." and ".go.id ... regulated in the Regulation of the Ministry".
- **`gov.vn` / `edu.vn`:** VNNIC reads "GOV.VN: chỉ dành cho các cơ quan nhà nước ..." and "EDU.VN:
  chỉ dành cho ... giáo dục, đào tạo".
- **`gov.uk`:** GOV.UK reads "Only the following organisations can apply for a .gov.uk domain name".
- **`gov.au` / `edu.au`:** auDA.
- **The branch's six:** as the branch cites them.

**Not confirmed:**
- **`ac.uk`:** Jisc's eligibility policy is indexed by search engines, but it answered 403 to a plain
  client. Step 5 confirms it through the vendor.
- **`gov.kz`, `edu.kz`, `gov.uz`, `gov.ge`:** no registry page stating the restriction was reachable.
  They leave the list unless Step 5 finds one.
- **`edu.az` is dropped, on its own registry's evidence.** `whois.az`'s Rules §2.2 list "‘edu.az’,
  ‘gov.az’ ... are defined for general use". Nothing there says the registry checks an `edu.az`
  registrant. `.edu.az` hosts go to the classifier, like any flat namespace.

**Files:**
- Modify: `apps/research/domains.py` (the `VERIFIED_SECOND_LEVEL` block and `verified_kind`)
- Modify: `apps/research/recognition.py` (the `GOVERNMENT_ZONES` block and `government_zone`)
- Test: `tests/research/test_domains.py` (extend), `tests/research/test_recognition_lists.py` (edit)

**Interfaces:**
- Consumes: `provenance.Recognition`, `provenance.Reason.GOVERNMENT_ZONE` (provenance branch, merged).
- Produces:
  - `domains.Zone(kind: str, government: bool, citation: str)`;
  - `domains.VERIFIED_ZONES: dict[str, Zone]`;
  - `domains.verified_kind(host: str) -> str`, with an unchanged signature;
  - `domains.government_zone_of(host: str) -> tuple[str, str] | None`, which returns
    `(zone, citation)`;
  - `recognition.government_zone(domain: str) -> Recognition | None`, with an unchanged signature.

- [ ] **Step 1: Write the failing tests.** Append to `tests/research/test_domains.py`:

```python
def test_every_verified_zone_cites_its_registry() -> None:
    """Spec 2026-09-27 §4.1: one list, one citation per zone. A zone with no
    registry page saying the registrant is checked is not a verified zone."""
    from apps.research.domains import VERIFIED_ZONES

    assert VERIFIED_ZONES
    for zone, entry in VERIFIED_ZONES.items():
        assert entry.citation.startswith("https://"), zone


def test_the_provenance_zones_and_master_s_government_zones_are_one_list() -> None:
    from apps.research.domains import government_zone_of

    assert government_zone_of("ed.gov") == ("gov", "https://get.gov/domains/eligibility/")
    assert government_zone_of("mext.go.jp")[0] == "go.jp"  # type: ignore[index]
    assert government_zone_of("turkiyeburslari.gov.tr")[0] == "gov.tr"  # type: ignore[index]
    # Master's zones now vouch for a government body too.
    assert government_zone_of("mincult.gov.az")[0] == "gov.az"  # type: ignore[index]
    assert government_zone_of("ankara.bel.tr")[0] == "bel.tr"  # type: ignore[index]
    # An institution zone is verified, but it is not government.
    assert government_zone_of("itu.edu.tr") is None


def test_a_provenance_only_zone_never_starts_answering_for_the_classifier() -> None:
    """.gov admits federal, state and city bodies; go.jp admits research
    institutes. The registry vouches "government", not a holder kind."""
    from apps.research.domains import verified_kind

    for host in ("ed.gov", "mext.go.jp", "europa.eu", "auswaertiges-amt.de"):
        assert verified_kind(host) == "", host


def test_edu_az_is_open_by_its_own_registry_s_rules() -> None:
    """whois.az Rules 2.2: "'edu.az', 'gov.az' ... are defined for general use".
    Nothing there checks an edu.az registrant, so the classifier decides."""
    from apps.research.domains import verified_kind

    assert verified_kind("bsu.edu.az") == ""
    assert verified_kind("mincult.gov.az") == "NATIONAL_GOVERNMENT"
```

  In `tests/research/test_recognition_lists.py`:
  - delete the line `    GOVERNMENT_ZONES,` from the `from apps.research.recognition import (` block;
  - delete the whole `test_every_zone_cites_its_registry_policy` function, which now lives in
    `test_domains.py`;
  - add one case to the `test_a_government_zone_recognises_a_funder` parametrize list, after
    `("auswaertiges-amt.de", "auswaertiges-amt.de"),`:

```python
        ("mincult.gov.az", "gov.az"),
```

- [ ] **Step 2: Run them, and confirm that they fail.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_domains.py tests/research/test_recognition_lists.py`

  Expected: FAIL. `ImportError: cannot import name 'VERIFIED_ZONES'` and `'government_zone_of'`, and
  the new `mincult.gov.az` case returns `None`.

- [ ] **Step 3: Implement the list.** In `apps/research/domains.py`, replace everything from the
  comment line `#: Second-level domains whose registry verifies eligibility before allocating` down
  to the end of `def verified_kind` (its closing `)`) with:

```python
@dataclass(frozen=True)
class Zone:
    """A namespace whose registry checks who the registrant is before allocating a name."""

    #: The holder kind that check establishes, or "" when it establishes only
    #: "a public body" (.gov admits federal, state and city bodies alike). ""
    #: leaves the classifier to decide the kind, exactly as in a flat namespace.
    kind: str
    #: The check is "a public body": provenance's government-zone recognition
    #: reads this (institution provenance gate spec §5.7); the classifier does not.
    government: bool
    #: The registry's own eligibility page, fetched when the row was written.
    citation: str


_TRABIS = "https://www.trabis.gov.tr/content/Belgeli"
_ERNET = "https://registry.ernet.in/guidelines"
_PANDI = (
    "https://pandi.id/public/files/2024/10/"
    "kebijakan-pendaftaran-nama-domain-versi-9-0-bilingual-new-1729151599.pdf"
)
_VNNIC = "https://vnnic.vn/vi/dns/he-thong-dns-quoc-gia/he-thong-ten-mien"

#: The one list of verified zones (spec 2026-09-27 §4.1): the classifier's free
#: kinds and provenance's government zones, each with the page that says so.
#: Not a keyword rule and not a guess about a name: the registrar did the check,
#: so a host here carries its answer with no fetch and no model call.
#:
#: **It does not generalise, and the blanks are the point.** DENIC: ".de domains
#: are available to everyone"; the Netherlands and Sweden are flat too; and
#: whois.az's own Rules 2.2 call edu.az "defined for general use", so edu.az is
#: not here. A zone is added only with its registry's page; a country with no
#: structure has no row, which is visibly incomplete rather than silently wrong.
#: Pinned by tests/research/test_domains.py. Each page read 2026-09-27:
VERIFIED_ZONES: dict[str, Zone] = {
    # Türkiye -- TRABİS "Belge ibraz edilerek tahsis edilebilecek olan ... “bel.tr”,
    # ... “edu.tr”, “gov.tr”, “k12.tr” ...": documents before allocation.
    "gov.tr": Zone("NATIONAL_GOVERNMENT", True, _TRABIS),
    "bel.tr": Zone("SUBNATIONAL_GOVERNMENT", True, _TRABIS),
    "edu.tr": Zone("INSTITUTION", False, _TRABIS),
    "k12.tr": Zone("INSTITUTION", False, _TRABIS),
    # Azerbaijan -- "Domain registration in the GOV.az zone The State Body ...
    # applies in written form to the Special State Protection Service".
    "gov.az": Zone(
        "NATIONAL_GOVERNMENT", True, "https://scis.gov.az/en/pages/view/dns-xidmeti"
    ),
    # India -- MeitY, "3.1 Eligibility for securing registration under .GOV.IN";
    # ERNET is the sole registrar for AC.IN and EDU.IN and checks recognition.
    "gov.in": Zone(
        "NATIONAL_GOVERNMENT",
        True,
        "https://www.meity.gov.in/static/uploads/2024/02/Guidelines_for_register.pdf",
    ),
    "ac.in": Zone("INSTITUTION", False, _ERNET),
    "edu.in": Zone("INSTITUTION", False, _ERNET),
    # Pakistan -- PKNIC: "GOV.PK is used primarily for the Federal Government of
    # Pakistan"; ".edu.pk ... must be a bona fide educational institute".
    "gov.pk": Zone(
        "NATIONAL_GOVERNMENT", True, "https://www.pknic.net.pk/gov-requirements.html"
    ),
    "edu.pk": Zone("INSTITUTION", False, "https://www.pknic.net.pk/edu-requirements.html"),
    # Indonesia -- PANDI policy v9.0: ".ac.id, is allocated for Higher
    # Educational Institution"; ".go.id ... regulated in the Regulation of the Ministry".
    "go.id": Zone("NATIONAL_GOVERNMENT", True, _PANDI),
    "ac.id": Zone("INSTITUTION", False, _PANDI),
    # Vietnam -- VNNIC: "GOV.VN: chỉ dành cho các cơ quan nhà nước ...";
    # "EDU.VN: chỉ dành cho ... giáo dục, đào tạo".
    "gov.vn": Zone("NATIONAL_GOVERNMENT", True, _VNNIC),
    "edu.vn": Zone("INSTITUTION", False, _VNNIC),
    # United Kingdom -- "Only the following organisations can apply for a
    # .gov.uk domain name"; Jisc's ac.uk eligibility policy.
    "gov.uk": Zone(
        "NATIONAL_GOVERNMENT",
        True,
        "https://www.gov.uk/guidance/check-if-your-organisation-can-get-a-govuk-domain-name",
    ),
    "ac.uk": Zone(
        "INSTITUTION",
        False,
        "https://community.jisc.ac.uk/library/janet-services-documentation/eligibility-policy",
    ),
    # Australia -- auDA: gov.au "Domain names for Australian governments and
    # government bodies"; edu.au, "Schedule A Part 2 of the .au Licensing Rules".
    "gov.au": Zone(
        "NATIONAL_GOVERNMENT",
        True,
        "https://www.auda.org.au/au-domain-names/the-different-au-domain-names/",
    ),
    "edu.au": Zone(
        "INSTITUTION",
        False,
        "https://www.auda.org.au/au-domain-names/the-different-au-domain-names/"
        "edu-au-domain-names/",
    ),
    # From the provenance gate (spec 2026-09-26 §5.7), each re-read 2026-09-27:
    # - gov: ".gov domains ... are only available to U.S.-based government organizations";
    # - go.jp: JPRS, "GO.JP Japanese government authorities, research institutes
    #   under Japanese authority's jurisdiction, and government-affiliated corporations";
    # - go.kr: KISA, "go Administrative agencies or legislative/judicial agencies";
    # - europa.eu: a single-owner domain -- the Commission's legal notice names
    #   "the European Union's websites within the europa.eu domain";
    # - auswaertiges-amt.de: a single-owner domain -- its Impressum names the
    #   Auswärtiges Amt as publisher.
    # Kind "" on all six: the classifier never answered for them, and a zone
    # joining this list is not a reason for it to start.
    "gov": Zone("", True, "https://get.gov/domains/eligibility/"),
    "go.jp": Zone("", True, "https://jprs.co.jp/en/jpdomain.html"),
    "go.kr": Zone(
        "",
        True,
        "https://xn--3e0bx5euxnjje69i70af08bea817g.xn--3e0b707e/jsp/eng/domain/kr/"
        "qualification.jsp",
    ),
    "europa.eu": Zone("", True, "https://commission.europa.eu/legal-notice_en"),
    "auswaertiges-amt.de": Zone("", True, "https://www.auswaertiges-amt.de/de/impressum"),
}


def _zone(host: str) -> tuple[str, Zone] | None:
    """The longest verified zone `host` sits in. Longest first, so a zone is
    never shadowed by a shorter one that also matches."""
    normalized = host.casefold().strip(".")
    for suffix in sorted(VERIFIED_ZONES, key=len, reverse=True):
        if normalized == suffix or normalized.endswith(f".{suffix}"):
            return suffix, VERIFIED_ZONES[suffix]
    return None


def verified_kind(host: str) -> str:
    """The holder kind a registry already verified for this host, or "".

    "" is the common answer and is not a failure: it means the host is in a
    flat namespace (`.de`, `.nl`, `.se`), under an unrestricted suffix (`.org.tr`
    is open), or in a zone that vouches "government" without a level. Never
    guess from "" -- it is the absence of a check, not evidence of anything.
    """
    found = _zone(host)
    return found[1].kind if found else ""


def government_zone_of(host: str) -> tuple[str, str] | None:
    """`(zone, citation)` when a registry vouches that this host is a public
    body's; None otherwise. A `gov`-looking name alone is never proof."""
    found = _zone(host)
    if found is None or not found[1].government:
        return None
    zone, entry = found
    return zone, entry.citation
```

  In `apps/research/recognition.py`, replace everything from the comment line
  `#: Government-only zones, each with the registry policy that restricts it` down to the end of
  `def government_zone` (its final `return None`) with:

```python
def government_zone(domain: str) -> Recognition | None:
    """A body on a zone whose registry admits only public bodies (spec §5.7).
    The zones and their citations are `domains.VERIFIED_ZONES` -- one list,
    shared with the classifier (government funding spec 2026-09-27 §4.1)."""
    found = government_zone_of(domain)
    if found is None:
        return None
    zone, citation = found
    return Recognition(
        reason=Reason.GOVERNMENT_ZONE, bound_domain=domain,
        source_slug=f"zone:{zone}", source_url=citation,
    )
```

  Add `from .domains import government_zone_of` to `recognition.py`'s imports, in isort order after
  `from .closed_lists import (...)`.

- [ ] **Step 4: Run the tests.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_domains.py tests/research/test_recognition_lists.py tests/research/test_classify.py tests/research/test_provenance_decide.py`

  Expected: all passed. `git grep -n VERIFIED_SECOND_LEVEL -- apps tests` prints nothing.

- [ ] **Step 5: Confirm or drop the five uncited zones.** They are `ac.uk` (in the list now) and
  `gov.kz`, `edu.kz`, `gov.uz`, `gov.ge` (out of the list now). Run the two candidates through the
  vendor ladder:

```bash
cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run python manage.py shell -c '
from apps.research.fetch import fetch_page
from apps.research.harvest import page_text
for zone, url in {
    "ac.uk": "https://community.jisc.ac.uk/library/janet-services-documentation/eligibility-policy",
    "gov.ge": "https://nic.ge/_cdn/f/24/38/SLIPhFp7p0acMj1jVbr5Hw/2025.08.07.Domain_Regulation_Amendments_ENG_V.5.0_FINAL.pdf",
}.items():
    page = fetch_page(url, purpose="read", tag="zone-citation")
    text = (page.markdown or page_text(page.body or b"")).casefold()
    print(zone, page.outcome, page.final_url, "mentions zone:", zone in text)
'
```

  Expected: one line per zone.
  - **`ac.uk`:** keep the row only if the page states who may register, and put its sentence in the
    comment. Otherwise delete the row, and change `test_a_registry_verified_domain_carries_its_kind_for_free`'s
    `abertay.ac.uk` assertion to `== ""`, with a one-line comment giving the reason.
  - **`gov.ge`:** add it only if the document states that `gov.ge` is restricted.
  - **`gov.kz`, `edu.kz`, `gov.uz`:** search their registry's own site (`nic.kz`, `cctld.uz`) for a
    rules page, and run it through the same snippet. Add a zone only when the registry's own page
    states the restriction.

  Each added row has this shape, with its quote above it:

```python
    # Georgia -- <the registry's own sentence, quoted>.
    "gov.ge": Zone("NATIONAL_GOVERNMENT", True, "<the URL the snippet printed as final_url>"),
```

  Re-run Step 4.

- [ ] **Step 6: Commit.** Name every dropped zone in the message: `edu.az`, and whichever of the five
  stayed out.

```bash
git -C /home/orkhan/Desktop/gov-funding-design add apps/research/domains.py apps/research/recognition.py tests/research/test_domains.py tests/research/test_recognition_lists.py
git -C /home/orkhan/Desktop/gov-funding-design commit -m "feat(research): one cited list of verified zones for the classifier and provenance

Dropped, no registry page stating a check: edu.az (whois.az Rules 2.2: general use),
and each of ac.uk, gov.kz, edu.kz, gov.uz, gov.ge that Step 5 did not confirm (name them here).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Funding words, in every country's official languages, from Wikidata's labels and the answer key's pages (§4.2)

A third role, `funding`, joins `cycle` and `apply` in `docs/research/cycle-vocabulary.csv`, which is
data and never a list in code. Plan 2 reads it through the existing
`cycle_vocabulary.for_languages("funding", languages)`.

**Owner decision, 2026-09-27: students can apply to any country, so the language set is every current
country's official language, built by code, never a hand-typed list of four.** `apps/research/languages.py`
already does this shape for a single country's sweep angles (`WikidataLanguages`, decision 38): Wikidata
`wdt:P31 wd:Q6256` for a current country, `FILTER NOT EXISTS { wdt:P576 [] }` to drop dissolved ones,
`wdt:P37` for its official languages, `wdt:P424` for each language's Wikimedia code. That class takes one
`country_code` and returns that country's languages -- it cannot return every country's set in one query,
so this task does not call it; it queries the same shape with the per-country filter removed, and
validates codes against `languages._LANG`'s pattern and the 12-character cap `models.py`'s
`CharField(max_length=12)` already enforces on a language column.

**Where the words come from:**
- **Wikidata labels** of scholarship (`Q188823`), grant (`Q230788`) and student financial aid
  (`Q6305411`), in every language that query returns, plus English and Russian (Azerbaijani government
  sites and channels publish in Russian, so it is added unconditionally, not only when some country's
  `P37` happens to name it).
- **Words verified on the answer key's own pages** -- today's four (az, tr, ru, en); every other
  language in the built set gets its page-sourced words from plan 2's per-agency answer-key rows, not
  from this task. A language Wikidata gives no label for is reported, never silently absent.

**Spec gap, recorded:** Wikidata has **no tuition-waiver item**. On 2026-09-27, searching "tuition
waiver" returned only a journal article (`Q120587914`). Waiver words therefore come only from
answer-key pages.

**Files:**
- Modify: `apps/research/cycle_vocabulary.py:24-35` (`_ROLES`, docstring, plus a new
  `_funding_languages(sparql=wikidata.sparql)` that builds the set; the label fetch itself is a
  one-off shell lookup, same as today, not a function -- Step 5)
- Modify: `docs/research/cycle-vocabulary.csv` (append rows)
- Test: `tests/research/test_funding_words.py`

**Interfaces:**
- Consumes: `cycle_vocabulary.terms() -> tuple[Term, ...]`,
  `for_languages(role, languages) -> tuple[str, ...]`, Task 1's `read_answer_key()`, and
  `apps/research/languages.py`'s `_LANG` code-shape pattern (read, not imported private -- this task
  defines its own copy in `cycle_vocabulary.py`, noted where it's used, because `_LANG` is a
  module-private name in `languages.py`).
- Produces: `for_languages("funding", ["az"])` returns the funding words for Azerbaijani plus English;
  `for_languages("funding", ["is"])` (a country this task's query reaches but the answer key doesn't
  cite pages for) returns Icelandic's Wikidata-labelled words plus English, or English alone when
  Wikidata has none.

- [ ] **Step 1: Write the failing tests.** Create `tests/research/test_funding_words.py`:

```python
"""Funding words (spec 2026-09-27 §4.2) are data with a source, never a list in code."""

import re
from pathlib import Path

import pytest

from apps.research import cycle_vocabulary as vocab
from apps.research.answer_key import read_answer_key

_WIKIDATA = re.compile(r"^https://www\.wikidata\.org/wiki/Q\d+$")


@pytest.fixture(autouse=True)
def _fresh():
    vocab.terms.cache_clear()
    yield
    vocab.terms.cache_clear()


def _funding() -> list[vocab.Term]:
    return [term for term in vocab.terms() if term.role == "funding"]


def test_every_language_the_spec_names_has_a_funding_word() -> None:
    """az, tr, ru ("Azerbaijani government sites and channels publish in
    Russian") and en are the floor -- the answer key's four -- kept even
    though the built language set is now every current country's official
    languages, not these four alone."""
    assert {"az", "tr", "ru", "en"} <= {term.language for term in _funding()}


def test_every_funding_word_comes_from_wikidata_or_an_answer_key_page() -> None:
    pages = {row.official_url for row in read_answer_key()}
    for term in _funding():
        assert _WIKIDATA.match(term.source) or term.source in pages, term


def test_the_language_set_is_built_from_wikidata_not_hand_typed() -> None:
    """A canned multi-country SPARQL response, not the real endpoint: the
    builder unions each country's codes with English and Russian."""

    def fake_sparql(query: str) -> list[dict[str, str]]:
        return [{"code": "az"}, {"code": "tr"}, {"code": "is"}]

    languages = vocab._funding_languages(sparql=fake_sparql)
    assert {"az", "tr", "is", "en", "ru"} <= set(languages)


def test_a_code_that_fails_the_shape_is_dropped_and_reported(caplog: pytest.LogCaptureFixture) -> None:
    """Wikidata is untrusted past the shape languages.py already checks (`_LANG`)
    and the 12-character cap `models.py`'s language columns enforce. A bad code
    is dropped, never raised past, and the drop is logged -- never silent."""

    def fake_sparql(query: str) -> list[dict[str, str]]:
        return [{"code": "az"}, {"code": "not-a-real-language-code-this-is-too-long"}]

    with caplog.at_level("WARNING"):
        languages = vocab._funding_languages(sparql=fake_sparql)
    assert "az" in languages
    assert "not-a-real-language-code-this-is-too-long" not in languages
    assert "not a language code" in caplog.text.lower()


def test_funding_words_are_casefolded_and_listed_once_per_language() -> None:
    rows = [(term.language, term.term) for term in _funding()]
    assert all(word == word.casefold() for _, word in rows)
    assert len(rows) == len(set(rows))


def test_a_role_nobody_reads_is_refused(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "language,role,term,source,verified_on\n"
        "en,fund,grant,https://www.wikidata.org/wiki/Q230788,2026-09-27\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(vocab, "_CSV", path)
    with pytest.raises(ValueError, match="incomplete"):
        vocab.terms()


def test_funding_words_are_read_like_every_other_role() -> None:
    words = vocab.for_languages("funding", ["az"])
    assert "qrant" in words and "grant" in words
    assert "грант" not in words  # Russian only when the host's languages include it
```

- [ ] **Step 2: Run them, and confirm that they fail.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_funding_words.py`

  Expected: FAIL. `test_every_language_the_spec_names_has_a_funding_word` fails because the set is
  empty, `test_funding_words_are_read_like_every_other_role` fails because `qrant` is missing, and
  `test_the_language_set_is_built_from_wikidata_not_hand_typed` and
  `test_a_code_that_fails_the_shape_is_dropped_and_reported` fail with `AttributeError` because
  `vocab._funding_languages` doesn't exist yet.

- [ ] **Step 3: Accept the role.** In `apps/research/cycle_vocabulary.py`, replace the docstring's
  second paragraph:

```python
Three roles. `cycle` terms steer the step-1 crawl (`includePaths`) toward the
pages where a funder announces a call; `apply` terms pick the one own-site hop
of step 2; `funding` terms (government funding spec 2026-09-27 §4.2) say which
of a body's pages is about money at all, sourced from Wikidata's labels of
scholarship, grant and student aid and from the answer key's own pages. None
decides anything: a word that matches nothing costs nothing, and whether a page
is evidence is the reader's and validity's question.
```

  and change `_ROLES`:

```python
_ROLES = frozenset({"cycle", "apply", "funding"})
```

- [ ] **Step 4: Build the language set by code.** In `apps/research/cycle_vocabulary.py`, add a
  function that queries Wikidata for every current country's official languages, the same shape
  `languages.py`'s `WikidataLanguages` uses for one country (`wdt:P31 wd:Q6256`, `FILTER NOT EXISTS
  { wdt:P576 [] }`, `wdt:P37`, `wdt:P424`) minus the per-country filter, and unions it with `en` and
  `ru`. Codes are validated and bad ones dropped and logged, never raised past:

```python
import logging
from collections.abc import Callable

from apps.research import wikidata

logger = logging.getLogger(__name__)

#: Same shape as languages.py's `_LANG` -- codes come back from Wikidata (P424)
#: and must not be trusted further than that.
_LANG = re.compile(r"^[a-z]{2,3}(-[a-z0-9]+)*$")
_LANG_MAX_LENGTH = 12  # models.py's language columns: CharField(max_length=12)

_COUNTRY_LANGUAGES_QUERY = """SELECT DISTINCT ?code WHERE {
  ?country wdt:P31 wd:Q6256 .
  FILTER NOT EXISTS { ?country wdt:P576 [] }
  ?country wdt:P37 ?language .
  ?language wdt:P424 ?code .
}"""


def _funding_languages(
    *, sparql: Callable[[str], list[dict[str, str]]] = wikidata.sparql
) -> tuple[str, ...]:
    """Every current country's official language, as a Wikimedia code, plus
    English and Russian (Azerbaijani government sites and channels publish in
    Russian, spec 2026-09-27 §4.2) -- built from Wikidata, never a hand-typed
    list of four."""
    codes = {"en", "ru"}
    for row in sparql(_COUNTRY_LANGUAGES_QUERY):
        raw = row.get("code", "").lower()
        if _LANG.match(raw) and len(raw) <= _LANG_MAX_LENGTH:
            codes.add(raw)
        else:
            logger.warning("not a language code from Wikidata: %r", raw)
    return tuple(sorted(codes))
```

  Run it and print what it found:

```bash
cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run python manage.py shell -c '
from apps.research.cycle_vocabulary import _funding_languages
languages = _funding_languages()
print(len(languages), "languages:", languages)
'
```

  Expected: a warning line for any dropped code, printed by the logger, and a count in the tens (one
  country can repeat a language another country also has -- Wikidata gives ~180-200 distinct codes
  across ~195 current countries). Record the count in the commit message (Step 8) as the expected
  output this step produced.

- [ ] **Step 5: Take the Wikidata labels for that whole set, in one batch. Run the lookup; don't type
  the words.**

```bash
cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run python manage.py shell -c '
from apps.research.cycle_vocabulary import _funding_languages
from apps.research.wikidata import sparql
languages = _funding_languages()
wanted = ", ".join(f"\"{code}\"" for code in languages)
rows = sparql(f"""SELECT ?item ?lang ?label WHERE {{
  VALUES ?item {{ wd:Q188823 wd:Q230788 wd:Q6305411 }}
  {{ ?item rdfs:label ?label }} UNION {{ ?item skos:altLabel ?label }}
  BIND(LANG(?label) AS ?lang) FILTER(?lang IN ({wanted}))
}} ORDER BY ?item ?lang ?label""")
found_langs = {r["lang"] for r in rows}
missing = sorted(set(languages) - found_langs)
print("no Wikidata label in:", len(missing), missing)
for r in rows:
    print(r["item"].rsplit("/", 1)[1], r["lang"], r["label"], sep=" | ")
'
```

  One or a few batched queries over the whole set built in Step 4, never one query per language.
  **Print and keep the `missing` list and its count** -- those languages get no row from this task;
  they get funding words later from an agency's own answer-key pages, in plan 2 (never silently
  absent, never blocking this task). Record the count in the commit message.

  Expected for az, tr, ru and en, as measured live on 2026-09-27 (labels change; take what the run
  prints, and take the rest of the batch's output for every other language it found):

```text
Q188823 | az | Təhsil təqaüdü
Q188823 | en | fellowships and scholarships
Q188823 | en | scholarship
Q188823 | ru | стипендии
Q188823 | ru | стипендия
Q188823 | tr | burs
Q230788 | az | qrant
Q230788 | en | grant
Q230788 | ru | грант
Q230788 | tr | hibe
Q6305411 | az | Tələbələrə maddi yardım
Q6305411 | en | student aid
Q6305411 | en | student benefit
Q6305411 | en | student financial aid
```

  Append one CSV row per printed line to `docs/research/cycle-vocabulary.csv`. Use
  `<lang>,funding,<label casefolded>,https://www.wikidata.org/wiki/<QID>,<today>`. For the az/tr/ru/en
  slice above, that is (append the rest of the batch's other languages the same way):

```csv
az,funding,təhsil təqaüdü,https://www.wikidata.org/wiki/Q188823,2026-09-27
en,funding,fellowships and scholarships,https://www.wikidata.org/wiki/Q188823,2026-09-27
en,funding,scholarship,https://www.wikidata.org/wiki/Q188823,2026-09-27
ru,funding,стипендии,https://www.wikidata.org/wiki/Q188823,2026-09-27
ru,funding,стипендия,https://www.wikidata.org/wiki/Q188823,2026-09-27
tr,funding,burs,https://www.wikidata.org/wiki/Q188823,2026-09-27
az,funding,qrant,https://www.wikidata.org/wiki/Q230788,2026-09-27
en,funding,grant,https://www.wikidata.org/wiki/Q230788,2026-09-27
ru,funding,грант,https://www.wikidata.org/wiki/Q230788,2026-09-27
tr,funding,hibe,https://www.wikidata.org/wiki/Q230788,2026-09-27
az,funding,tələbələrə maddi yardım,https://www.wikidata.org/wiki/Q6305411,2026-09-27
en,funding,student aid,https://www.wikidata.org/wiki/Q6305411,2026-09-27
en,funding,student benefit,https://www.wikidata.org/wiki/Q6305411,2026-09-27
en,funding,student financial aid,https://www.wikidata.org/wiki/Q6305411,2026-09-27
```

- [ ] **Step 6: Take the words the answer key's pages actually carry, for az, tr, ru and en.** Every
  other language in the built set gets its page-sourced words later, from plan 2's per-agency answer
  key -- this task does not fetch pages for languages the answer key names no page in. A page names
  money in its own
  inflection or stem, such as `təqaüd`, `bursu`, `стипенди`, a waiver phrase, or a Russian word on
  an Azerbaijani ministry's site. So the candidates are **stems of the labels above, plus words you
  copy from each page's title or funding heading**. The run prints only the ones actually present:

```bash
cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run python manage.py shell -c '
from apps.research.answer_key import read_answer_key
from apps.research.fetch import fetch_page
from apps.research.harvest import page_text
CANDIDATES = {"az": ["təqaüd", "qrant"], "tr": ["burs", "hibe"], "ru": ["стипенди", "грант"],
              "en": ["scholarship", "grant", "waiver"]}
for row in read_answer_key():
    page = fetch_page(row.official_url, purpose="read", tag="funding-words")
    text = (page.markdown or page_text(page.body or b"")).casefold()
    found = [(lang, w) for lang, words in CANDIDATES.items() for w in words
             if w in text or w in row.official_url.casefold()]
    print(row.official_url, found)
'
```

  Add to `CANDIDATES` any word you copied from a page's title or funding heading before running it,
  for example a waiver phrase in Turkish. Then append one row per printed `(language, word)`, with
  that row's page URL as `source`:

```csv
<language>,funding,<word>,<the official_url the run printed it for>,<today>
```

  A word already present for the same language keeps its first row; the uniqueness test refuses a
  second.

- [ ] **Step 7: Run the tests.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_funding_words.py tests/research/test_cycle_vocabulary.py`

  Expected: all passed.

- [ ] **Step 8: Commit.** Name the language-set count from Step 4 and the missing-label count from
  Step 5 in the message.

```bash
git -C /home/orkhan/Desktop/gov-funding-design add apps/research/cycle_vocabulary.py docs/research/cycle-vocabulary.csv tests/research/test_funding_words.py
git -C /home/orkhan/Desktop/gov-funding-design commit -m "feat(research): funding words in every country's official languages, sourced to Wikidata and the answer key

Language set built from Wikidata P31/P37/P424 (<N> languages, see Step 4's run) plus en and ru,
never a hand-typed list of four. <M> of those had no Wikidata label for scholarship/grant/student
aid (see Step 5's run) and get page-sourced words later, in plan 2. az, tr, ru and en additionally
keep answer-key-page words, as before.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: A reviewed agency's own schemes are citable on a routing host (§4.2)

`daad.de` and `campusfrance.org` sit in `domains._ROUTING`, so `ResearchLead.from_url` demotes every
lead on them to `AGGREGATOR`. The lead then cannot support a claim, and `_served` refuses it. §4.2
says: "a page on a routing host is citable **for the host's own schemes** when the host is on the
reviewed agency list; programme listings on it stay routing-only".

- **The mechanism:** a **`FUNDER`** lead on a reviewed agency's host keeps `FUNDER`.
- **Why it is safe:** `pipeline._fund_holder_page` writes only `HOLDER_OWN` decisions. Anything the
  page says about other bodies' programmes is `PROGRAM`, `INSTITUTION` or `POINTER`, and is not
  written as the agency's.
- **The limit:** every other source type on those hosts, and every non-agency catalogue, is demoted
  exactly as before.

**Files:**
- Modify: `apps/research/domains.py` (after `from .hosts import registrable_domain  # noqa: E402`)
- Modify: `apps/research/discovery.py:98-102` (`ResearchLead.from_url`)
- Test: `tests/research/test_agency_exemption.py`

**Interfaces:**
- Consumes: `docs/research/closed-lists/national_scholarship_agencies.csv` (provenance branch;
  columns `external_key,name,kind,website,page_url,...,rejected_reason,...`).
- Produces:
  - `domains.AGENCY_LIST: Path`;
  - `domains.reviewed_agency_domains() -> frozenset[str]` (cached);
  - `domains.is_reviewed_agency(host: str) -> bool`.

- [ ] **Step 1: Write the failing tests.** Create `tests/research/test_agency_exemption.py`:

```python
"""Spec 2026-09-27 §4.2: an agency host that is also a catalogue is citable
for the agency's own schemes, and for nothing else."""

from pathlib import Path

import pytest

from apps.research import domains
from apps.research.discovery import ResearchLead

DAAD = "https://www.daad.de/de/studieren-und-forschen-in-deutschland/stipendien-finden/"


@pytest.fixture(autouse=True)
def _fresh():
    domains.reviewed_agency_domains.cache_clear()
    yield
    domains.reviewed_agency_domains.cache_clear()


def test_a_reviewed_agency_s_own_scheme_page_stays_citable() -> None:
    lead = ResearchLead.from_url(
        DAAD, source_type="FUNDER", funding_family="GOVERNMENT_SCHOLARSHIP"
    )
    assert lead.source_type == "FUNDER" and lead.can_support_claim is True


def test_a_programme_listing_on_an_agency_host_stays_routing_only() -> None:
    for source_type in ("PROGRAM", "SCHOLARSHIP", "UNIVERSITY"):
        lead = ResearchLead.from_url(DAAD, source_type=source_type, funding_family="")
        assert lead.source_type == "AGGREGATOR" and lead.can_support_claim is False


def test_a_catalogue_that_is_not_a_reviewed_agency_gets_nothing() -> None:
    for url in ("https://www.mastersportal.com/x", "https://www.uni-assist.de/x"):
        lead = ResearchLead.from_url(url, source_type="FUNDER", funding_family="")
        assert lead.source_type == "AGGREGATOR" and lead.can_support_claim is False, url


def test_the_exemption_reads_the_reviewed_list_by_registrable_domain() -> None:
    assert domains.is_reviewed_agency("www.campusfrance.org") is True
    assert domains.is_reviewed_agency("daad-scholarships.org") is False
    assert domains.is_reviewed_agency("") is False


def test_a_row_the_list_rejected_is_not_reviewed_in(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "agencies.csv"
    path.write_text(
        "external_key,name,kind,website,page_url,country_code,home_cells,host_cells,"
        "rejected_reason,source_url,verified_on,notes\n"
        "daad,DAAD,NATIONAL_GOVERNMENT,https://www.daad.de,,DE,ANY,DE,DOES_NOT_EXIST,"
        "https://www.daad.de/,2026-09-26,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(domains, "AGENCY_LIST", path)
    assert domains.is_reviewed_agency("daad.de") is False
```

- [ ] **Step 2: Run them, and confirm that they fail.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_agency_exemption.py`

  Expected: FAIL, `AttributeError: module 'apps.research.domains' has no attribute 'reviewed_agency_domains'`.

- [ ] **Step 3: Implement.** In `apps/research/domains.py`, add `import csv`,
  `from functools import cache` and `from pathlib import Path` to the imports at the top. Append
  after the `FREE_MAIL_DOMAINS` block, anywhere below `from .hosts import registrable_domain`:

```python
#: The reviewed agency list (government funding spec 2026-09-27 §4.2): national
#: scholarship agencies a person compiled from each body's own page. A host on it
#: may also sit in _ROUTING (daad.de, campusfrance.org): it is a catalogue of
#: other people's programmes AND a funder of its own schemes.
AGENCY_LIST = (
    Path(__file__).resolve().parents[2]
    / "docs" / "research" / "closed-lists" / "national_scholarship_agencies.csv"
)


@cache
def reviewed_agency_domains() -> frozenset[str]:
    """The registrable domains of the list's live rows. A row carrying a
    rejected_reason is a person's "no" and is not reviewed in."""
    with AGENCY_LIST.open(encoding="utf-8", newline="") as handle:
        return frozenset(
            key
            for row in csv.DictReader(handle)
            if not (row.get("rejected_reason") or "").strip()
            and (key := registrable_domain(row.get("website") or ""))
        )


def is_reviewed_agency(host: str) -> bool:
    key = registrable_domain(host) if host else ""
    return bool(key) and key in reviewed_agency_domains()
```

  In `apps/research/discovery.py`, change the import line to
  `from .domains import is_catalogue, is_reviewed_agency`. Then, in `ResearchLead.from_url`, replace:

```python
        canonical = canonicalize_url(url)
        # The host decides, not the caller. A search hit on a catalogue is a
        # catalogue lead: it routes research and cannot support a claim (§7.2).
        if is_catalogue(urlsplit(canonical).hostname or ""):
            source_type = "AGGREGATOR"
```

  with:

```python
        canonical = canonicalize_url(url)
        host = urlsplit(canonical).hostname or ""
        # The host decides, not the caller. A search hit on a catalogue is a
        # catalogue lead: it routes research and cannot support a claim (§7.2).
        # One exception (government funding spec 2026-09-27 §4.2): a reviewed
        # agency's host is also a funder, so a FUNDER lead on it -- the agency's
        # page about its own schemes -- stays citable. The holder path writes
        # HOLDER_OWN awards only, so its listings of other people's programmes
        # never become the agency's; every other lead type is demoted as before.
        if is_catalogue(host) and not (source_type == "FUNDER" and is_reviewed_agency(host)):
            source_type = "AGGREGATOR"
```

- [ ] **Step 4: Run the tests.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_agency_exemption.py tests/research/test_discovery.py tests/research/test_domains.py tests/research/test_pipeline_funding.py`

  Expected: all passed.

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/gov-funding-design add apps/research/domains.py apps/research/discovery.py tests/research/test_agency_exemption.py
git -C /home/orkhan/Desktop/gov-funding-design commit -m "feat(research): a reviewed agency's own schemes are citable on a routing host

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: The judge reads the target level of each award track (§7.1, reader side)

**What changes.** The judge labels each line with a `target_level`, one of `MASTER`, `BACHELOR`,
`PHD`, `ANY` or `UNSTATED`. The added `UNSTATED` is the vocabulary's own word for "the page did not
say", as it is for every other field. `awards()` then keeps each award's **master's track**, which is:

- the lines labelled `MASTER` or `ANY`;
- the lines naming no level, which describe the whole scheme;
- **no** `BACHELOR` or `PHD` line.

An award whose named levels include neither `MASTER` nor `ANY` produces **no decision**. It is
counted in `other_levels`, so a page of bachelor's awards is never silence.

**Why this is the smallest correct change:**
- **The canonical key does not change.** At most one decision per `(heading, kind, scope)` is
  written, as today, so `cycle_verification._heading`, which parses the key, is untouched.
- **Conditions become per track for free.** A bachelor's line's condition never reaches the master's
  decision.
- **A level the readings split on is conservative.** The line becomes `UNSTATED`, so it is kept. The
  split is recorded in `disputed`, and in `unconfirmed` on an agreed award.

**Files:**
- Modify: `apps/research/funding_judge.py`: `_Level` area (a new `_TargetLevel`), `LineVerdict`,
  `_QUESTION`, `FundingDecision`, `FundingReadResult`, `awards()`, `_decide()`
- Modify: `apps/research/pipeline.py`: `FundingCounts` (`other_levels`)
- Test: `tests/research/test_funding_judge_level.py`

**Interfaces:**
- Consumes: `tests.research.conftest.verdict(line, **overrides) -> LineVerdict`.
- Produces:
  - `LineVerdict.target_level: Literal["MASTER", "BACHELOR", "PHD", "ANY", "UNSTATED"] = "UNSTATED"`;
  - `FundingDecision.target_level: str = "UNSTATED"` (only `MASTER`, `ANY` or `UNSTATED` ever appear);
  - `FundingReadResult.other_levels: int = 0`;
  - `FundingCounts.other_levels: int = 0`.

  Task 6 writes `decision.target_level`.

- [ ] **Step 1: Write the failing tests.** Create `tests/research/test_funding_judge_level.py`:

```python
"""Spec 2026-09-27 §7.1: a scheme's master's track, and only it, is decided."""

from apps.funding.eligibility import ConditionTriple
from apps.research.funding_judge import (
    _QUESTION,
    FundingVerdicts,
    Line,
    LineVerdict,
    awards,
    line_outcomes,
)
from tests.research.conftest import verdict

HEADING = "State Programme"
BACHELOR = "Bachelor's students receive 500 AZN a month."
MASTER = "Master's students receive 800 AZN a month."
DOCTORAL = "Doctoral students receive 1,000 AZN a month."
CITIZENS = "Applicants must be citizens of Azerbaijan."
EVERY_LEVEL = "The scholarship is open to students at every level of study."
NO_BACHELOR = "No bachelor's scholarships are offered this year."


def _age(bar: str, quote: str) -> ConditionTriple:
    return ConditionTriple(key="AGE", operator="LTE", value=bar, unit="YEARS", quote=quote)


CITIZEN = ConditionTriple(key="CITIZENSHIP", operator="IN", value="AZ", quote=CITIZENS)


def _state(line: int, level: str, *conditions: ConditionTriple, **over: object) -> LineVerdict:
    fields: dict[str, object] = dict(
        kind="I0_HOLDER_AWARD", scope="HOLDER_OWN", holder="NATIONAL_GOVERNMENT",
        route="STUDENT_APPLIES_SEPARATELY", money_form="GRANT", tuition="UNSTATED",
        living="FULL", name="State Programme", target_level=level, conditions=conditions,
    )
    fields.update(over)
    return verdict(line, **fields)


def _page(*texts: str) -> tuple[Line, ...]:
    return (Line(HEADING, ""), *(Line(text, HEADING) for text in texts))


def _three(*verdicts: LineVerdict) -> list[FundingVerdicts]:
    return [FundingVerdicts(verdicts=verdicts)] * 3


def test_three_tracks_under_one_heading_keep_only_the_master_s_conditions() -> None:
    """The State Programme's shape: one heading, three levels, one general line."""
    chunk = _page(BACHELOR, MASTER, DOCTORAL, CITIZENS)
    readings = _three(
        _state(1, "BACHELOR", _age("23", BACHELOR)),
        _state(2, "MASTER", _age("30", MASTER)),
        _state(3, "PHD", _age("35", DOCTORAL)),
        _state(4, "UNSTATED", CITIZEN),
    )
    result = awards(line_outcomes(chunk, readings))
    (decision,) = result.decisions
    assert decision.target_level == "MASTER"
    assert decision.conditions == (_age("30", MASTER), CITIZEN)
    assert decision.quotes == (MASTER, CITIZENS)
    assert result.other_levels == 0


def test_a_bachelor_s_only_award_is_not_decided_and_is_counted() -> None:
    chunk = _page(BACHELOR, CITIZENS)
    readings = _three(_state(1, "BACHELOR"), _state(2, "UNSTATED", CITIZEN))
    result = awards(line_outcomes(chunk, readings))
    assert result.decisions == ()
    assert result.other_levels == 1


def test_an_any_level_award_is_decided_as_any() -> None:
    chunk = _page(EVERY_LEVEL)
    (decision,) = awards(line_outcomes(chunk, _three(_state(1, "ANY")))).decisions
    assert decision.target_level == "ANY"


def test_a_page_that_names_no_level_is_still_decided() -> None:
    """Most foundation and ministry pages never name a level; dropping them
    would lose the schemes the discovery exists to find."""
    chunk = _page(MASTER)
    (decision,) = awards(line_outcomes(chunk, _three(_state(1, "UNSTATED")))).decisions
    assert decision.target_level == "UNSTATED"
    assert decision.agreement == "AGREED"


def test_a_level_the_readings_split_on_is_kept_and_marked_unconfirmed() -> None:
    chunk = _page(MASTER)
    readings = [
        FundingVerdicts(verdicts=(_state(1, "MASTER"),)),
        FundingVerdicts(verdicts=(_state(1, "MASTER"),)),
        FundingVerdicts(verdicts=(_state(1, "BACHELOR"),)),
    ]
    (decision,) = awards(line_outcomes(chunk, readings)).decisions
    assert decision.target_level == "UNSTATED"
    assert "target_level" in decision.disputed
    assert "target_level" in decision.unconfirmed
    assert decision.agreement == "AGREED"


def test_a_bachelor_s_negation_does_not_suspend_the_master_s_award() -> None:
    """Before tracks, the two lines were one award of equal specificity, and
    the dated-disclaimer rule left it NO -- a master's scheme withdrawn by a
    sentence about bachelor's students."""
    chunk = _page(MASTER, NO_BACHELOR)
    readings = _three(_state(1, "MASTER"), _state(2, "BACHELOR", offered="NO"))
    (decision,) = awards(line_outcomes(chunk, readings)).decisions
    assert decision.offered == "YES" and decision.suspension_quote == ""


def test_the_question_defines_every_target_level() -> None:
    assert "target_level" in _QUESTION
    for value in ("MASTER", "BACHELOR", "PHD", "ANY"):
        assert value in _QUESTION, value
```

- [ ] **Step 2: Run them, and confirm that they fail.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_funding_judge_level.py`

  Expected: FAIL, `pydantic_core._pydantic_core.ValidationError: ... target_level Extra inputs are not permitted`.

- [ ] **Step 3: Implement the label.** In `apps/research/funding_judge.py`:

  After the `_Cycle = Literal[...]` line, add:

```python
#: Which degree an award TRACK is for (government funding spec 2026-09-27 §7.1).
#: The spec names four; UNSTATED is the vocabulary's own "the page did not say".
_TargetLevel = Literal["MASTER", "BACHELOR", "PHD", "ANY", "UNSTATED"]
#: The levels a master's applicant's award may be for. UNSTATED lines join them.
_MASTER_LEVELS = frozenset({"MASTER", "ANY"})
```

  In `class LineVerdict`, between `cycle: _Cycle = "UNSTATED"` and `name: str = ...`, add:

```python
    #: The degree level of the award track this line belongs to. A scheme with
    #: bachelor's, master's and doctoral tracks under one heading is three
    #: tracks; `awards` keeps the master's and drops the rest (spec 7.1).
    target_level: _TargetLevel = "UNSTATED"
```

  In `_QUESTION`, replace the last line `    "Lines may be in any language."` with:

```python
    "target_level: the degree level of the award track this line belongs to -- MASTER for "
    "master's study, BACHELOR, PHD for doctoral study, ANY when the line states the award is "
    "open at every level including master's, or UNSTATED when the line names no level. A "
    "scheme with separate bachelor's, master's and doctoral tracks gives each line its own "
    "track's level.\n"
    "Lines may be in any language."
```

  Leave `_MAX_OUTPUT_TOKENS` alone. The label is one closed word per verdict, about 4 tokens, and
  `test_funding_judge_card.py`'s pin on the non-streaming wall still holds.

  In `class FundingDecision`, after `card_off_line: int = 0`, add:

```python
    #: MASTER, ANY or UNSTATED -- the track this decision is (spec 2026-09-27
    #: 7.1). BACHELOR and PHD never appear: such a track is not decided.
    target_level: str = "UNSTATED"
```

  In `class FundingReadResult`, after `pointer_leads: tuple[PointerLead, ...] = ()`, add:

```python
    #: Awards whose named levels were all bachelor's or doctoral: read, counted,
    #: not decided (spec 2026-09-27 7.1).
    other_levels: int = 0
```

  Add these two functions directly above `def awards(`:

```python
def _line_level(member: LineOutcome) -> tuple[str, bool]:
    """(the line's target level, whether its readings split on it).

    Unanimity, like every other label: one reading's BACHELOR must not drop a
    line two readings called MASTER. A split reads as UNSTATED -- kept, and
    named as a caveat -- which is the direction that loses no scheme.
    """
    pool = [v for v in member.verdicts if v.offered == "YES"] or list(member.verdicts)
    levels = {v.target_level for v in pool}
    if len(levels) == 1:
        return next(iter(levels)), False
    return "UNSTATED", True


def _master_track(members: list[LineOutcome]) -> tuple[str, list[LineOutcome], bool] | None:
    """(level, the lines a master's applicant is subject to, a level split), or
    None when the award names only bachelor's or doctoral levels.

    Lines naming no level describe the whole scheme and join the track; lines
    naming another level leave it, with their conditions and their negations.
    """
    levels = [_line_level(member) for member in members]
    named = {level for level, _split in levels if level != "UNSTATED"}
    if named and not named & _MASTER_LEVELS:
        return None
    kept = [
        (member, split)
        for member, (level, split) in zip(members, levels, strict=True)
        if level in _MASTER_LEVELS or level == "UNSTATED"
    ]
    level = "MASTER" if "MASTER" in named else "ANY" if "ANY" in named else "UNSTATED"
    return level, [member for member, _split in kept], any(split for _m, split in kept)
```

  In `awards()`, replace the decision loop and the return:

```python
    decisions: list[FundingDecision] = []
    for (heading, kind, scope), award_members in groups.items():
        for intake, members in _intake_buckets(award_members).items():
            decisions.append(_decide(heading, kind, scope, intake, members))
    return FundingReadResult(tuple(decisions), pointers, negations, noise, tuple(leads))
```

  with:

```python
    decisions: list[FundingDecision] = []
    other_levels = 0
    for (heading, kind, scope), award_members in groups.items():
        track = _master_track(award_members)
        if track is None:
            # Spec 2026-09-27 7.1: a scheme with no master's (or any-level)
            # track is not written. Counted, so it is never silence.
            other_levels += 1
            continue
        level, kept, level_split = track
        for intake, members in _intake_buckets(kept).items():
            decisions.append(_decide(
                heading, kind, scope, intake, members, level=level, level_split=level_split
            ))
    return FundingReadResult(
        tuple(decisions), pointers, negations, noise, tuple(leads), other_levels
    )
```

  Change `_decide`'s signature to:

```python
def _decide(
    heading: str,
    kind: str,
    scope: str,
    intake: str,
    members: list[LineOutcome],
    *,
    level: str = "UNSTATED",
    level_split: bool = False,
) -> FundingDecision:
```

  In `_decide`, directly after the line `disputed |= card.unconfirmed`, add:

```python
    if level_split:
        # A detail, never existence: the track is kept and the split is named.
        disputed.add("target_level")
```

  In `_decide`'s `FundingDecision(...)` call, after `card_off_line=card.off_line,`, add:

```python
            target_level=_or_unstated(level, "target_level", unconfirmed),
```

  In `apps/research/pipeline.py`, in `class FundingCounts`, after `withdrawn: int = 0`, add:

```python
    #: Awards read and left undecided because every level they name is
    #: bachelor's or doctoral (spec 2026-09-27 7.1).
    other_levels: int = 0
```

  and in `FundingCounts.record`, after `self.noise += read.noise`, add:

```python
        self.other_levels += read.other_levels
```

- [ ] **Step 4: Run the tests.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_funding_judge_level.py tests/research/test_funding_judge.py tests/research/test_funding_judge_card.py tests/research/test_pipeline_funding.py tests/research/test_funding_yield.py`

  Expected: all passed.

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/gov-funding-design add apps/research/funding_judge.py apps/research/pipeline.py tests/research/test_funding_judge_level.py
git -C /home/orkhan/Desktop/gov-funding-design commit -m "feat(research): the funding judge reads each award track's degree level; only the master's track is decided

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: The row records its track, and a loan is never written (§7.1, §10, writer side)

**Files:**
- Modify: `apps/funding/models.py`: `FundingOpportunity` (a field after `card_quotes`, and a constraint)
- Create: `apps/funding/migrations/<leaf+1>_opportunity_target_level.py` (generated)
- Modify: `apps/research/funding_reader.py`: `write_funding_decision`, `write_holder_decision`
- Modify: `apps/research/resolution/apply.py`: `_award_disputed`
- Test: `tests/research/test_funding_reader.py` (edit), `tests/research/resolution/test_apply.py`
  (extend), `tests/research/test_target_level_rls.py` (new)

**Interfaces:**
- Consumes: `FundingDecision.target_level` from Task 5.
- Produces:
  - `FundingOpportunity.target_level: CharField(max_length=10, blank, default "")`, constrained to
    `"" | MASTER | ANY | UNSTATED`;
  - both writers return `None` for `money_form == "LOAN"`;
  - the applier refuses an operator's `LOAN`.

- [ ] **Step 1: Write the failing tests.** In `tests/research/test_funding_reader.py`, replace the
  whole function `test_a_loan_is_recorded_as_repayable` with:

```python
def test_a_loan_writes_no_row(program, snapshot):
    """Spec 2026-09-27 7.1: "No loans." The page still said it; the writer
    declines, and withdraw_unread retires a row an older read left behind."""
    loan = _decision(money_form="LOAN", tuition="FULL", extras=())
    assert _write(loan, program, snapshot) is None
    assert not FundingOpportunity.objects.exists()


def test_a_forgivable_loan_is_written_served_and_carries_its_obligation(program, snapshot):
    """Bonded money counts (spec 7.1; owner to confirm, 12) -- shown with the
    obligation, never repayable by default."""
    opportunity = _write(
        _decision(money_form="FORGIVABLE_LOAN", obligation=("SERVE_FUNDER",)), program, snapshot
    )
    assert opportunity is not None and opportunity.served is True
    assert opportunity.obligation == "SERVE_FUNDER"
    shares = {str(b.repayable_share) for b in FundingBenefit.objects.filter(opportunity=opportunity)}
    assert shares == {"0.000"}
```

  Append to the same file:

```python
def test_a_holder_s_loan_writes_no_row(snapshot, funder_lead):
    from apps.research.funding_reader import write_holder_decision

    row = write_holder_decision(
        _holder_decision(money_form="LOAN"), holder_domain="example-foundation.org",
        holder_name="Example Foundation", lead=funder_lead, source=snapshot.source,
        snapshot=snapshot,
    )
    assert row is None and not FundingOpportunity.objects.exists()


def test_a_row_records_the_track_it_was_read_for(snapshot, funder_lead):
    from apps.research.funding_reader import write_holder_decision

    master = write_holder_decision(
        _holder_decision(target_level="MASTER"), holder_domain="example-foundation.org",
        holder_name="Example Foundation", lead=funder_lead, source=snapshot.source,
        snapshot=snapshot,
    )
    unstated = write_holder_decision(
        _holder_decision(heading="Another scheme"), holder_domain="example-foundation.org",
        holder_name="Example Foundation", lead=funder_lead, source=snapshot.source,
        snapshot=snapshot,
    )
    assert master is not None and master.target_level == "MASTER"
    assert unstated is not None and unstated.target_level == "UNSTATED" and unstated.served


def test_the_database_refuses_a_bachelor_s_row():
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError, match="funding_opportunity_target_level_valid"):
        with transaction.atomic():
            FundingOpportunity.objects.create(
                canonical_key="x", name="x", family="UNIVERSITY_WIDE", scope_type="GLOBAL",
                target_level="BACHELOR",
            )
```

  Append to `tests/research/resolution/test_apply.py`:

```python
def test_an_operator_cannot_serve_a_loan_through_the_queue(platform, disputed_award) -> None:
    """Spec 2026-09-27 7.1: "No loans." `money_form`'s choices are the judge's
    own vocabulary, LOAN included; accepting it would serve what the writer
    refuses to write."""
    item = _award_item(disputed_award, {"option": "accept", "fields": {"money_form": "LOAN"},
                                        "note": ""})
    assert apply_decided(now=NOW).reopened == 1
    assert _reopened(item).apply_error.startswith("a loan is not served")
    disputed_award.refresh_from_db()
    assert disputed_award.served is False and disputed_award.review == ""
```

  Create `tests/research/test_target_level_rls.py`:

```python
"""FundingOpportunity.target_level sits behind the catalogue's own policies.

No new table: the column inherits `shared_catalog_select` and
`runtime_engine_write`. CLAUDE.md: the test role bypasses RLS, so this runs
through `runtime_connection`, a NOBYPASSRLS role that belongs to neither
runtime role. UPDATE is granted first, so zero rows is the policy's refusal,
not a missing privilege.
"""

from uuid import uuid4

import pytest
from django.db import connection
from psycopg import sql

from apps.funding.models import FundingOpportunity

pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
def test_target_level_is_readable_by_a_tenant_and_writable_by_nobody_else(runtime_connection):
    FundingOpportunity.objects.create(
        canonical_key=f"read:{uuid4()}", name="Award", family="UNIVERSITY_WIDE",
        scope_type="GLOBAL", target_level="MASTER",
    )
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT, UPDATE ON TABLE public.funding_fundingopportunity TO {}")
            .format(role)
        )
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT target_level FROM public.funding_fundingopportunity")
        assert cursor.fetchall() == [("MASTER",)]
        cursor.execute("UPDATE public.funding_fundingopportunity SET target_level = 'ANY'")
        assert cursor.rowcount == 0
    assert FundingOpportunity.objects.get().target_level == "MASTER"
```

- [ ] **Step 2: Run them, and confirm that they fail.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_funding_reader.py tests/research/resolution/test_apply.py tests/research/test_target_level_rls.py`

  Expected: FAIL. `test_a_loan_writes_no_row` fails because a row is returned. The target-level tests
  fail with `TypeError: FundingOpportunity() got unexpected keyword arguments: 'target_level'`. The
  queue test fails because the item is applied.

- [ ] **Step 3: Implement the column.** In `apps/funding/models.py`, in `FundingOpportunity`, after
  `card_quotes = models.JSONField(default=dict, blank=True)`, add:

```python
    #: The award track this row was read for (government funding spec
    #: 2026-09-27 7.1): MASTER, ANY, or UNSTATED when the page names no level.
    #: A bachelor's- or doctoral-only track is never written, and the check
    #: below refuses one. "" on a row no reader has written since.
    target_level = models.CharField(max_length=10, blank=True, default="")
```

  and, as the last entry of `Meta.constraints` (after
  `funding_opportunity_duration_months_range`), add:

```python
            models.CheckConstraint(
                condition=models.Q(target_level__in=("", "MASTER", "ANY", "UNSTATED")),
                name="funding_opportunity_target_level_valid",
            ),
```

- [ ] **Step 4: Generate the migration against the real leaf.**

```bash
cd /home/orkhan/Desktop/gov-funding-design && ls apps/funding/migrations | sort | tail -3
POSTGRES_DB=elmify_gov uv run python manage.py makemigrations funding --name opportunity_target_level
```

  Expected: `Migrations for 'funding': apps/funding/migrations/<leaf+1>_opportunity_target_level.py`,
  with `+ Add field target_level to fundingopportunity` and
  `+ Create constraint funding_opportunity_target_level_valid on model fundingopportunity`.

  If Django reports conflicting leaves, run `makemigrations funding --merge` first. Open the file and
  confirm that `dependencies` names the leaf `ls` printed. It holds exactly one `AddField` and one
  `AddConstraint`, and no `RunSQL`. The column needs no policy of its own, because
  `funding_fundingopportunity`'s policies are table-wide.

- [ ] **Step 5: Implement the writers and the applier.** In `apps/research/funding_reader.py`:

  In `write_funding_decision`, directly after `raise ValueError("a POINTER writes no funding row")`,
  add:

```python
    if decision.money_form == "LOAN":
        # Spec 2026-09-27 7.1: "No loans." FORGIVABLE_LOAN counts and is written.
        return None
```

  In `write_holder_decision`, directly after
  `raise ValueError("a holder row needs the holder's registrable domain")`, add the same four lines.

  In both `update_or_create(... defaults={...})` dicts, after `"cycle"` is spread in by
  `**_card_columns(decision),`, add:

```python
            "target_level": decision.target_level,
```

  In `apps/research/resolution/apply.py`, in `_award_disputed`, directly after
  `if resolution.option == "accept":`, add:

```python
        if resolution.fields.get("money_form") == "LOAN":
            raise Refused(
                "a loan is not served (spec 2026-09-27 7.1): reject the row instead"
            )
```

- [ ] **Step 6: Run the tests.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research tests/funding tests/tenancy`

  Expected: all passed. Then run
  `POSTGRES_DB=elmify_gov uv run python manage.py makemigrations --check --dry-run`, which prints
  `No changes detected`.

- [ ] **Step 7: Commit.**

```bash
git -C /home/orkhan/Desktop/gov-funding-design add apps/funding/models.py apps/funding/migrations apps/research/funding_reader.py apps/research/resolution/apply.py tests/research/test_funding_reader.py tests/research/resolution/test_apply.py tests/research/test_target_level_rls.py
git -C /home/orkhan/Desktop/gov-funding-design commit -m "feat(funding): a funding row records its track; a loan is never written or served

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: A pointer carries the body's own name, copied from its line (§4.7, reader side)

**Spec gap, recorded.** `PointerLead.name` is `label.name[:80]`, and the question defines that as
"the award's name in at most six words", for example "DAAD scholarship" or "MyStart təqaüdü". It is
not the **body**. The resolver scores a name against sites, so it needs "Mədəniyyət Nazirliyi".

The judge therefore gains `funder`, filled only on POINTER lines and **copied** from the line. Any
copy not printed on its line is dropped, by the same `card_fields.on_line` rule that guards the
amounts. So a reading can never supply a name the page did not print.

**Files:**
- Modify: `apps/research/funding_judge.py`: `LineVerdict`, `_QUESTION`, `PointerLead`, `awards()`
- Test: `tests/research/test_funding_judge_pointer.py`

**Interfaces:**
- Consumes: `card_fields.on_line(value: str, line: str) -> bool` (already imported).
- Produces:
  - `LineVerdict.funder: str = ""` (max 120);
  - `PointerLead(quote: str, name: str, holder: str, funder: str = "")`.

  Task 8 reads `pointer.funder`.

- [ ] **Step 1: Write the failing tests.** Create `tests/research/test_funding_judge_pointer.py`:

```python
"""Spec 2026-09-27 §4.7: a pointer names a BODY, copied from its own line."""

from apps.research.funding_judge import (
    _QUESTION,
    FundingVerdicts,
    Line,
    LineVerdict,
    PointerLead,
    awards,
    line_outcomes,
)

LINE = Line("Students may also apply for the Ministry of Culture's MyStart scholarship.", "Funding")


def _pointer(funder: str) -> LineVerdict:
    return LineVerdict(
        line=0, offered="YES", kind="I1_UNIVERSITY_WIDE", scope="POINTER",
        internationals_included="UNSTATED", nationality_shape="UNSTATED",
        route="STUDENT_APPLIES_SEPARATELY", money_form="GRANT", tuition="UNSTATED",
        living="UNSTATED", holder="NATIONAL_GOVERNMENT", name="MyStart scholarship",
        funder=funder,
    )


def _read(*funders: str) -> tuple[PointerLead, ...]:
    readings = [FundingVerdicts(verdicts=(_pointer(f),)) for f in funders]
    return awards(line_outcomes((LINE,), readings)).pointer_leads


def test_the_body_a_pointer_names_is_copied_from_its_line() -> None:
    (lead,) = _read("Ministry of Culture", "Ministry of Culture", "Ministry of Culture")
    assert lead == PointerLead(
        quote=LINE.text, name="MyStart scholarship", holder="NATIONAL_GOVERNMENT",
        funder="Ministry of Culture",
    )


def test_a_funder_no_reading_copied_from_the_line_is_dropped() -> None:
    """A paraphrase is a name the page never printed; the resolver would search
    for it as if it had."""
    (lead,) = _read(
        "Azerbaijan Ministry of Culture", "Azerbaijan Ministry of Culture",
        "Ministry of Culture of Azerbaijan",
    )
    assert lead.funder == ""


def test_the_most_common_copy_wins_among_copies_on_the_line() -> None:
    (lead,) = _read("Ministry of Culture", "Ministry of Culture", "the Ministry")
    assert lead.funder == "Ministry of Culture"


def test_the_question_asks_for_the_funder_only_on_pointer_lines() -> None:
    assert "funder: on a POINTER line only" in _QUESTION
```

- [ ] **Step 2: Run them, and confirm that they fail.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_funding_judge_pointer.py`

  Expected: FAIL, `ValidationError: ... funder Extra inputs are not permitted`.

- [ ] **Step 3: Implement.** In `apps/research/funding_judge.py`:

  In `class LineVerdict`, directly after the `target_level` field from Task 5, add:

```python
    #: POINTER lines only: the body that holds the money, COPIED as the line
    #: writes it. `name` is the award's label; the resolver needs the body's.
    funder: str = Field(default="", max_length=120)
```

  In `_QUESTION`, replace the last line `    "Lines may be in any language."` with:

```python
    "funder: on a POINTER line only, the name of the body that holds the money, copied exactly "
    "as the line writes it (\"the Ministry of Culture\", \"DAAD\"), or empty when the line names "
    "none. Leave funder empty on every other line.\n"
    "Lines may be in any language."
```

  Replace `class PointerLead` with:

```python
@dataclass(frozen=True)
class PointerLead:
    """A line naming money held by a body other than this page's -- a lead into
    the organisation register, never an award. One Turkish page named 31."""

    quote: str
    #: The award's label, at most six words.
    name: str
    holder: str
    #: The body's own name as the line prints it, or "" when no reading copied
    #: one that is on the line (spec 2026-09-27 4.7).
    funder: str = ""
```

  Directly above `def awards(` (above Task 5's `_line_level`), add:

```python
def _pointer_funder(outcome: LineOutcome) -> str:
    """The body a pointer names, copied from its own line -- never a reading's
    paraphrase. The most common copy that is on the line; "" when none is."""
    copies = Counter(
        v.funder for v in outcome.verdicts if v.funder and on_line(v.funder, outcome.line.text)
    )
    return copies.most_common(1)[0][0] if copies else ""
```

  In `awards()`, replace:

```python
            leads.append(
                PointerLead(quote=outcome.line.text, name=label.name[:80], holder=label.holder)
            )
```

  with:

```python
            leads.append(
                PointerLead(
                    quote=outcome.line.text, name=label.name[:80], holder=label.holder,
                    funder=_pointer_funder(outcome),
                )
            )
```

- [ ] **Step 4: Run the tests.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_funding_judge_pointer.py tests/research/test_funding_judge.py tests/research/test_funding_judge_level.py tests/research/test_pipeline_funding.py tests/research/test_funding_yield.py`

  Expected: all passed. The existing
  `test_a_pointer_line_is_returned_as_a_lead_with_its_quote` still passes, because `funder` defaults
  to `""` on both sides.

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/gov-funding-design add apps/research/funding_judge.py tests/research/test_funding_judge_pointer.py
git -C /home/orkhan/Desktop/gov-funding-design commit -m "feat(research): a pointer carries the body's own name, copied from its line

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Pointers become `pointer` register rows (§4.7, persistence)

**What changes.** Every pointer a funder page yields becomes one `RegisterEntry` of register
`pointer`, keyed by the folded name. The row keeps:

- the body's name first, then the award label;
- the holder kind;
- the country of the naming page's own body, or else the run's country, because the name is written
  in that page's language and the resolver reads it with that country's vocabulary;
- the first quote and page, in two new columns.

**Why a register row, and not a new table:** the resolver, its retry schedule, its Diffbot meter, its
`CONFLICT` handling and the `SITE_UNKNOWN` applier all key on `RegisterEntry`. A row is how a pointer
gets every one of them without a second path.

**Files:**
- Modify: `apps/research/models.py`: `RegisterEntry` (two fields after `page_url`)
- Create: `apps/research/migrations/<leaf+1>_register_entry_pointer.py` (generated)
- Create: `apps/research/pointers.py`
- Modify: `apps/research/pipeline.py`: `run_discovery`'s `take_pointers` and its two call sites
- Test: `tests/research/test_pointers.py` (new), `tests/research/test_register_entry_pointer_rls.py`
  (new), `tests/research/test_pipeline_funding.py` (extend the wire test)

**Interfaces:**
- Consumes: `PointerLead.funder` (Task 7), `names.fold(text) -> str`,
  `hosts.registrable_domain`, `RegisterEntry`, `OrganisationDomain`.
- Produces:
  - `pointers.POINTER_REGISTER = "pointer"`;
  - `pointers.record_pointers(pointers: Iterable[PointerLead], *, page_url: str, fallback_country: str, now: datetime | None = None) -> int`;
  - `RegisterEntry.pointer_quote: CharField(300)`;
  - `RegisterEntry.pointer_url: URLField(2048)`.

- [ ] **Step 1: Write the failing tests.** Create `tests/research/test_pointers.py`:

```python
"""Spec 2026-09-27 §4.7: every pointer a page names is kept as a register row."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.research.funding_judge import PointerLead
from apps.research.models import RegisterEntry
from apps.research.pointers import POINTER_REGISTER, record_pointers
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db

NOW = timezone.now()
PAGE = "https://example-agency.az/tehsil/teqaud"
QUOTE = "Tələbələr Mədəniyyət Nazirliyinin MyStart təqaüdünə də müraciət edə bilərlər."
MYSTART = PointerLead(
    quote=QUOTE, name="MyStart təqaüdü", holder="NATIONAL_GOVERNMENT",
    funder="Mədəniyyət Nazirliyi",
)


def test_a_pointer_becomes_one_row_with_its_quote_and_page() -> None:
    record_organisation(domain="example-agency.az", name="Example Agency",
                        kind="NATIONAL_GOVERNMENT", country_code="AZ", found_via="test")
    assert record_pointers([MYSTART], page_url=PAGE, fallback_country="TR", now=NOW) == 1
    entry = RegisterEntry.objects.get(register=POINTER_REGISTER)
    assert entry.name == "Mədəniyyət Nazirliyi"
    assert entry.names == ["Mədəniyyət Nazirliyi", "MyStart təqaüdü"]
    assert (entry.kind, entry.resolution) == ("NATIONAL_GOVERNMENT", "UNRESOLVED")
    assert entry.country_code == "AZ"  # the naming page's body, not the run's
    assert (entry.pointer_quote, entry.pointer_url) == (QUOTE, PAGE)


def test_the_run_s_country_stands_in_when_the_page_s_body_has_none() -> None:
    record_pointers([MYSTART], page_url=PAGE, fallback_country="AZ", now=NOW)
    assert RegisterEntry.objects.get().country_code == "AZ"


def test_one_body_named_on_many_pages_is_one_row_keeping_its_first_sighting() -> None:
    record_pointers([MYSTART], page_url=PAGE, fallback_country="AZ", now=NOW)
    later = NOW + timedelta(days=3)
    again = PointerLead(quote="Başqa cümlə.", name="MyStart", holder="UNSTATED",
                        funder="MƏDƏNİYYƏT NAZİRLİYİ")
    assert record_pointers([again], page_url="https://other.example.az/x",
                           fallback_country="AZ", now=later) == 0
    entry = RegisterEntry.objects.get()
    assert (entry.pointer_quote, entry.pointer_url) == (QUOTE, PAGE)
    assert entry.last_seen == later


def test_a_row_someone_answered_is_never_reopened() -> None:
    record_pointers([MYSTART], page_url=PAGE, fallback_country="AZ", now=NOW)
    RegisterEntry.objects.update(resolution="REFUSED", refused_reason="NOT_A_FUNDER")
    record_pointers([MYSTART], page_url=PAGE, fallback_country="AZ", now=NOW)
    assert RegisterEntry.objects.get().resolution == "REFUSED"


def test_a_pointer_with_no_body_name_falls_back_to_its_award_label() -> None:
    label_only = PointerLead(quote="See the DAAD scholarship.", name="DAAD scholarship",
                             holder="NATIONAL_GOVERNMENT")
    record_pointers([label_only], page_url=PAGE, fallback_country="AZ", now=NOW)
    assert RegisterEntry.objects.get().names == ["DAAD scholarship"]
```

  Create `tests/research/test_register_entry_pointer_rls.py`:

```python
"""The pointer columns on RegisterEntry, through roles that cannot bypass RLS.

No new table, so the columns inherit research/0007's policies as funding/0049
left them. The engine's UPDATE matching one row is the control that shows the
tenant's zero is the policy's refusal, not a WHERE clause that matched nothing.
"""

import pytest
from django.db import connection
from django.utils import timezone
from psycopg import sql

from apps.research.models import RegisterEntry

pytestmark = pytest.mark.django_db

_UPDATE = (
    "UPDATE research_registerentry SET pointer_quote = 'a line', "
    "pointer_url = 'https://example-agency.az/x' WHERE external_key = 'k'"
)


def _entry() -> RegisterEntry:
    return RegisterEntry.objects.create(
        register="pointer", external_key="k", name="Body", names=["Body"],
        resolution=RegisterEntry.Resolution.UNRESOLVED, last_seen=timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_the_engine_writes_the_pointer_columns(role_connection) -> None:
    _entry()
    with role_connection("runtime_engine") as conn, conn.cursor() as cursor:
        cursor.execute(_UPDATE)
        assert cursor.rowcount == 1
    assert RegisterEntry.objects.get().pointer_quote == "a line"


@pytest.mark.django_db(transaction=True)
def test_a_tenant_reads_the_row_and_its_update_matches_nothing(runtime_connection) -> None:
    _entry()
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("GRANT UPDATE ON TABLE {} TO {}").format(
            sql.Identifier("public", "research_registerentry"), role))
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT pointer_quote FROM research_registerentry")
        assert cursor.fetchall() == [("",)]
        cursor.execute(_UPDATE)
        assert cursor.rowcount == 0
    assert RegisterEntry.objects.get().pointer_url == ""
```

  In `tests/research/test_pipeline_funding.py`, at the end of
  `test_run_discovery_routes_a_funder_lead_past_extraction_to_the_holder_path`, after
  `assert report.pointer_names == (("DAAD", "NATIONAL_GOVERNMENT"),)`, add:

```python
    # Spec 2026-09-27 4.7: the name is kept, not only printed.
    from apps.research.models import RegisterEntry

    entry = RegisterEntry.objects.get(register="pointer")
    assert (entry.name, entry.kind, entry.country_code) == ("DAAD", "NATIONAL_GOVERNMENT", "DE")
    assert (entry.pointer_quote, entry.pointer_url) == ("Ein DAAD-Stipendium.", url)
```

- [ ] **Step 2: Run them, and confirm that they fail.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_pointers.py tests/research/test_register_entry_pointer_rls.py tests/research/test_pipeline_funding.py`

  Expected: FAIL, `ModuleNotFoundError: No module named 'apps.research.pointers'`. The RLS tests fail
  with `column "pointer_quote" ... does not exist`.

- [ ] **Step 3: Implement the columns.** In `apps/research/models.py`, in `class RegisterEntry`,
  directly after `page_url = models.URLField(max_length=2048, blank=True, default="")`, add:

```python
    #: A `pointer` row only (government funding spec 2026-09-27 4.7): the line
    #: of another body's page that named this body, verbatim, and that page's
    #: URL. The first sighting is kept; a later one only moves `last_seen`. A
    #: pointer is a name, never provenance -- neither column vouches for anything.
    pointer_quote = models.CharField(max_length=300, blank=True, default="")
    pointer_url = models.URLField(max_length=2048, blank=True, default="")
```

  Generate the migration against the real leaf:

```bash
cd /home/orkhan/Desktop/gov-funding-design && ls apps/research/migrations | sort | tail -3
POSTGRES_DB=elmify_gov uv run python manage.py makemigrations research --name register_entry_pointer
```

  Expected: `+ Add field pointer_quote to registerentry` and `+ Add field pointer_url to registerentry`.
  If Django reports conflicting leaves, run `makemigrations research --merge` first. Confirm that
  `dependencies` names the real leaf, and that there is no `RunSQL`.

- [ ] **Step 4: Implement the writer.** Create `apps/research/pointers.py`:

```python
"""Pointers become leads (government funding spec 2026-09-27 §4.7).

A funding page that names another body's money yields a `PointerLead`: the
line, the award's label and -- copied from the line -- the body's own name.
Each is kept as a row of the `pointer` register, so the resolver that already
reads every other register reads these too (`manage.py resolve_register
--register pointer`), a person answers the ones it cannot place (SITE_UNKNOWN),
and a body it places is read like any other funder (`manage.py read_pointers`).

A pointer is a NAME, never provenance: nothing here trusts a URL printed in
page text, and the row it becomes vouches for nothing but "a page said this".
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from django.utils import timezone

from .funding_judge import PointerLead
from .hosts import registrable_domain
from .models import OrganisationDomain, RegisterEntry
from .names import fold

#: The register slug every pointer row is kept under.
POINTER_REGISTER = "pointer"


def _country(page_url: str, fallback: str) -> str:
    """Where the naming page's own body is, else the run's country: the name is
    written in that page's language, and the resolver reads a name with its
    country's vocabulary."""
    domain = registrable_domain(page_url)
    known = (
        OrganisationDomain.objects.filter(registrable_domain=domain)
        .values_list("organisation__country_code", flat=True)
        .first()
        if domain
        else None
    )
    return str(known) if known else fallback


def record_pointers(
    pointers: Iterable[PointerLead],
    *,
    page_url: str,
    fallback_country: str,
    now: datetime | None = None,
) -> int:
    """One `pointer` register row per body named; returns how many are new.

    Keyed by the folded name, so one body named on fifty pages is one row.
    The first sighting's quote and page are kept; a later one only moves
    `last_seen`, and never reopens a row a person or the resolver answered.
    """
    at = now or timezone.now()
    country = _country(page_url, fallback_country)
    created = 0
    for pointer in pointers:
        names = list(dict.fromkeys(
            name.strip()[:300] for name in (pointer.funder, pointer.name) if name.strip()
        ))
        key = fold(names[0])[:120] if names else ""
        if not key:
            continue
        entry, new = RegisterEntry.objects.get_or_create(
            register=POINTER_REGISTER,
            external_key=key,
            defaults={
                "name": names[0],
                "names": names,
                "country_code": country,
                "kind": pointer.holder,
                "resolution": RegisterEntry.Resolution.UNRESOLVED,
                "last_seen": at,
                "pointer_quote": pointer.quote[:300],
                "pointer_url": page_url[:2048],
            },
        )
        if not new:
            RegisterEntry.objects.filter(pk=entry.pk).update(last_seen=at)
        created += int(new)
    return created
```

- [ ] **Step 5: Wire the pipeline.** In `apps/research/pipeline.py`, add
  `from .pointers import record_pointers` to the imports, in isort order after
  `from .model_cost import CostMeter, ReadingTier`. Replace `take_pointers` in `run_discovery`:

```python
    def take_pointers(pointers: list[PointerLead]) -> None:
        for pointer in pointers:
            if pointer.name.casefold() not in pointer_seen:
                pointer_seen.add(pointer.name.casefold())
                pointer_names.append((pointer.name, pointer.holder))
```

  with:

```python
    def take_pointers(pointers: list[PointerLead], page_url: str) -> None:
        for pointer in pointers:
            if pointer.name.casefold() not in pointer_seen:
                pointer_seen.add(pointer.name.casefold())
                pointer_names.append((pointer.name, pointer.holder))
        # Kept, not only printed (spec 2026-09-27 4.7): each name becomes a
        # `pointer` register row, which the resolver reads.
        record_pointers(
            pointers, page_url=page_url, fallback_country=query.country_code, now=now
        )
```

  Change the two call sites.

  In the funder branch, change `take_pointers(\n                _fund_holder_page(` so that the
  closing lines read:

```python
                    counters=funding, tier=reading_tier, deferred=deferred,
                ),
                source.canonical_url,
            )
```

  In the batch loop, change `take_pointers(pending.finish(read))` to:

```python
            take_pointers(pending.finish(read), pending.url)
```

- [ ] **Step 6: Run the tests.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research tests/tenancy`

  Expected: all passed. Then run
  `POSTGRES_DB=elmify_gov uv run python manage.py makemigrations --check --dry-run`, which prints
  `No changes detected`.

- [ ] **Step 7: Commit.**

```bash
git -C /home/orkhan/Desktop/gov-funding-design add apps/research/models.py apps/research/migrations apps/research/pointers.py apps/research/pipeline.py tests/research/test_pointers.py tests/research/test_register_entry_pointer_rls.py tests/research/test_pipeline_funding.py
git -C /home/orkhan/Desktop/gov-funding-design commit -m "feat(research): pointer names become pointer register rows with their quote and page

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Resolving pointers: a site, tagged `POINTER:<host>`, or a person's question (§4.7)

**What changes.** `resolve_register` serves the `pointer` register. Every step below runs only under
`--write`, and so only once `RESOLVER_WRITES_ENABLED` is on:

- **A pointer the resolver places** becomes an `Organisation` whose route tag is
  `POINTER:<naming host>`. That is the tag `closed_lists.has_signal` already reads, and nothing
  wrote it until now.
- **A pointer it cannot place, for a final reason,** files the first `SITE_UNKNOWN` item. Its `why`
  carries the quote.
- **A `FETCH_FAILED` pointer asks nobody.** The resolver retries it after a week
  (`resolve_entries.FETCH_RETRY_AFTER`).
- **Other registers are untouched.** Filing `SITE_UNKNOWN` for VGM's thousands of unresolved rows is
  the resolution queue plan's decision, not this one's.

**Files:**
- Modify: `apps/research/resolve_entries.py`: `record_resolution` gains `found_via`
- Modify: `apps/research/resolution/writers.py`: `file_site_unknown`
- Modify: `apps/research/pointers.py`: `pointer_route`, `ask_for_site`
- Modify: `apps/research/management/commands/resolve_register.py`
- Test: `tests/research/test_resolve_register_command.py` (extend, and edit two messages),
  `tests/research/resolution/test_apply.py` (extend)

**Interfaces:**
- Consumes:
  - `resolver.Resolution(domain, via, reason, wikidata_qid, names, diffbot_asked)`;
  - `UnresolvedReason.FETCH_FAILED`;
  - `writers.file_item(kind, subject_key, evidence, *, country_code, registered, now) -> ResolutionItem`;
  - `writers.subject_facts(subject_key, evidence) -> tuple[str, bool]`;
  - `closed_lists.has_signal(org) -> bool`.
- Produces:
  - `record_resolution(entry, resolution, *, spec, now, found_via: str = "") -> None`;
  - `writers.file_site_unknown(entry: RegisterEntry, *, names: Sequence[str], why: str) -> ResolutionItem`;
  - `pointers.pointer_route(entry: RegisterEntry) -> str`;
  - `pointers.ask_for_site(entry: RegisterEntry, resolution: Resolution) -> ResolutionItem | None`.

- [ ] **Step 1: Write the failing tests.** In `tests/research/test_resolve_register_command.py`,
  change two expected messages:
  - `match="one of: az_banks, vgm_tr"` becomes `match="one of: az_banks, pointer, vgm_tr"`;
  - `match="one of: vgm_tr$"` becomes `match="one of: pointer, vgm_tr$"`.

  Then append:

```python
from apps.research.closed_lists import has_signal  # noqa: E402
from apps.research.models import ResolutionItem  # noqa: E402

POINTER_QUOTE = "Tələbələr Mədəniyyət Nazirliyinin MyStart təqaüdünə də müraciət edə bilərlər."


def _pointer(name: str = "Mədəniyyət Nazirliyi") -> RegisterEntry:
    return RegisterEntry.objects.create(
        register="pointer", external_key="medeniyyet nazirliyi", name=name,
        names=[name, "MyStart təqaüdü"], resolution="UNRESOLVED", last_seen=timezone.now(),
        country_code="AZ", kind="NATIONAL_GOVERNMENT",
        pointer_quote=POINTER_QUOTE, pointer_url="https://example-agency.az/tehsil/teqaud",
    )


def test_a_placed_pointer_s_body_carries_the_pointer_route(keys, monkeypatch) -> None:
    _pointer()
    _fake(monkeypatch, {"Mədəniyyət Nazirliyi": Resolution(
        "example-ministry.az", "SEARCH_SLUG", names=("Mədəniyyət Nazirliyi",))})
    call_command("resolve_register", "--register", "pointer", "--write")
    org = Organisation.objects.get(primary_domain="example-ministry.az")
    assert org.found_via == ["POINTER:example-agency.az"]
    assert (org.kind, org.country_code) == ("NATIONAL_GOVERNMENT", "AZ")
    assert has_signal(org) is True
    assert not ResolutionItem.objects.exists()


def test_an_unplaceable_pointer_asks_a_person_with_its_quote(keys, monkeypatch) -> None:
    entry = _pointer()
    _fake(monkeypatch, {"Mədəniyyət Nazirliyi": Resolution(
        reason="NO_CANDIDATE", names=("Mədəniyyət Nazirliyi", "MyStart təqaüdü"))})
    call_command("resolve_register", "--register", "pointer", "--write")
    item = ResolutionItem.objects.get(kind="SITE_UNKNOWN")
    assert item.subject_key == f"register:pointer:{entry.external_key}"
    assert item.evidence["register"] == "pointer" and item.evidence["candidates"] == []
    assert POINTER_QUOTE[:80] in item.evidence["why"]
    assert item.ask.startswith("Which site is Mədəniyyət Nazirliyi's own?")
    assert item.country_code == "AZ"


def test_a_fetch_failure_asks_nobody_yet(keys, monkeypatch) -> None:
    """The resolver retries a fetch failure after a week; a person asked now
    would be answering the resolver's own transient problem."""
    _pointer()
    _fake(monkeypatch, {"Mədəniyyət Nazirliyi": Resolution(
        reason="FETCH_FAILED", names=("Mədəniyyət Nazirliyi",))})
    call_command("resolve_register", "--register", "pointer", "--write")
    assert not ResolutionItem.objects.exists()


def test_a_dry_run_asks_nobody(keys, monkeypatch) -> None:
    _pointer()
    _fake(monkeypatch, {"Mədəniyyət Nazirliyi": Resolution(
        reason="NO_CANDIDATE", names=("Mədəniyyət Nazirliyi",))})
    call_command("resolve_register", "--register", "pointer")
    assert not ResolutionItem.objects.exists()


def test_another_register_s_unplaced_row_asks_nobody(keys, monkeypatch) -> None:
    _entries("ÖRNEK VAKFI")
    _fake(monkeypatch, {"ÖRNEK VAKFI": Resolution(reason="NO_CANDIDATE",
                                                  names=("ÖRNEK VAKFI",))})
    call_command("resolve_register", "--register", "vgm_tr", "--write")
    assert not ResolutionItem.objects.exists()
```

  Append to `tests/research/resolution/test_apply.py`:

```python
def test_a_person_s_answer_to_a_pointer_binds_its_row(platform) -> None:
    """The applier was built for register rows; a pointer row is one."""
    from apps.research.resolution.writers import file_site_unknown

    entry = RegisterEntry.objects.create(
        register="pointer", external_key="medeniyyet nazirliyi", name="Mədəniyyət Nazirliyi",
        names=["Mədəniyyət Nazirliyi"], resolution="UNRESOLVED", last_seen=NOW,
        country_code="AZ", kind="NATIONAL_GOVERNMENT",
        pointer_quote="a line", pointer_url="https://example-agency.az/x",
    )
    item = file_site_unknown(entry, names=entry.names, why='named on example-agency.az: "a line"')
    ResolutionItem.objects.filter(id=item.id).update(
        state="DECIDED", resolution={"option": "paste", "url": "https://example-ministry.az/"},
        decided_at=timezone.now(),
    )
    assert apply_decided(now=NOW).applied == 1
    entry.refresh_from_db()
    assert (entry.resolution, entry.resolved_via) == ("RESOLVED", "HUMAN")
    assert entry.organisation is not None
    assert entry.organisation.primary_domain == "example-ministry.az"
```

- [ ] **Step 2: Run them, and confirm that they fail.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_resolve_register_command.py tests/research/resolution/test_apply.py`

  Expected: FAIL. `unknown register 'pointer'`, the two message tests fail, and
  `ImportError: cannot import name 'file_site_unknown'`.

- [ ] **Step 3: Implement the route tag.** In `apps/research/resolve_entries.py`, change
  `record_resolution`'s signature and docstring head:

```python
def record_resolution(
    entry: RegisterEntry,
    resolution: Resolution,
    *,
    spec: RegisterSpec,
    now: datetime,
    found_via: str = "",
) -> None:
    """Write one answer onto the row it answers, or refuse (see module docstring).

    `spec` is `spec_for(entry, register_spec)`: an organisation is written
    with the country and kind the list vouched for, so both must be known.
    `found_via` overrides the route tag the organisation is recorded with --
    a pointer's body is `POINTER:<naming host>`, the route that FOUND it
    (spec 2026-09-27 4.7); the resolver is only how it was placed, which
    `resolved_via` on the row still records.
    """
```

  and, in its `record_organisation(...)` call, replace `found_via=f"RESOLVER:{resolution.via}",`
  with:

```python
                    found_via=found_via or f"RESOLVER:{resolution.via}",
```

- [ ] **Step 4: Implement the question.** In `apps/research/resolution/writers.py`, add
  `RegisterEntry` to the `from apps.research.models import (...)` block. Then add, after
  `withdraw_item`:

```python
def file_site_unknown(
    entry: RegisterEntry, *, names: Sequence[str], why: str
) -> ResolutionItem:
    """File (or refresh) "which site is this body's own?" for one register row.

    No candidates: the resolver keeps a domain or a reason, never a candidate
    list (resolver.Resolution), so the operator pastes one. The applier binds
    the row exactly as for any register (apply._site_unknown).
    """
    subject = f"register:{entry.register}:{entry.external_key}"
    evidence: dict[str, object] = {
        "register": entry.register,
        "external_key": entry.external_key,
        "names": [name[:300] for name in names][:20] or [entry.name],
        "country_code": entry.country_code,
        "candidates": [],
        "why": why[:300],
    }
    country_code, registered = subject_facts(subject, evidence)
    return file_item(
        "SITE_UNKNOWN", subject, evidence, country_code=country_code, registered=registered
    )
```

  Append to `apps/research/pointers.py`. Add `from typing import TYPE_CHECKING` and
  `from urllib.parse import urlsplit` to the stdlib imports, add `ResolutionItem` and
  `UnresolvedReason` to the `.models` import, add `from .resolution.writers import file_site_unknown`,
  and add, below the imports:

```python
if TYPE_CHECKING:
    from .resolver import Resolution
```

  Then append:

```python
def pointer_route(entry: RegisterEntry) -> str:
    """`POINTER:<naming host>` for a pointer row -- the route tag
    `closed_lists.has_signal` already reads -- and "" for any other register."""
    if entry.register != POINTER_REGISTER:
        return ""
    host = (urlsplit(entry.pointer_url).hostname or "unknown").lower()
    return f"POINTER:{host}"[:120]


def ask_for_site(entry: RegisterEntry, resolution: Resolution) -> ResolutionItem | None:
    """SITE_UNKNOWN for a pointer the resolver could not place, for good.

    None for any other register (that is the resolution queue plan's call, not
    this one's), for a placed pointer, and for a fetch failure -- the resolver
    retries that after a week (`resolve_entries.FETCH_RETRY_AFTER`), and a
    person asked now would be answering its transient problem.
    """
    if entry.register != POINTER_REGISTER or resolution.domain:
        return None
    if resolution.reason == UnresolvedReason.FETCH_FAILED:
        return None
    host = urlsplit(entry.pointer_url).hostname or "another body's page"
    return file_site_unknown(
        entry,
        names=resolution.names or tuple(entry.names or [entry.name]),
        why=f'named on {host}: "{entry.pointer_quote}"',
    )
```

- [ ] **Step 5: Serve the register.** In
  `apps/research/management/commands/resolve_register.py`:
  - add `from apps.research.pointers import POINTER_REGISTER, ask_for_site, pointer_route` to the
    imports;
  - below `VGM_SPEC = ...`, add:

```python
#: A pointer row carries its own country and kind (pointers.record_pointers:
#: the naming page's country, the reading's holder); the register asserts none.
POINTER_SPEC = RegisterSpec(country_code="", kind="")
```

  - in `registers()`, change `found = {vgm.REGISTER: VGM_SPEC}` to:

```python
    found = {vgm.REGISTER: VGM_SPEC, POINTER_REGISTER: POINTER_SPEC}
```

  - in `handle`, replace the write block:

```python
            if options["write"]:
                try:
                    record_resolution(entry, resolution, spec=spec, now=now)
                except EntryMovedOn as error:
                    # Bound, renamed or queued for a person by someone else
                    # meanwhile: theirs stands, and the run goes on.
                    self.stdout.write(f"  not written: {error}")
                    outcome = "MOVED_ON"
```

    with:

```python
            if options["write"]:
                try:
                    record_resolution(
                        entry, resolution, spec=spec, now=now, found_via=pointer_route(entry)
                    )
                except EntryMovedOn as error:
                    # Bound, renamed or queued for a person by someone else
                    # meanwhile: theirs stands, and the run goes on.
                    self.stdout.write(f"  not written: {error}")
                    outcome = "MOVED_ON"
                else:
                    if ask_for_site(entry, resolution) is not None:
                        self.stdout.write("  asked: SITE_UNKNOWN")
```

- [ ] **Step 6: Run the tests.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research`

  Expected: all passed.

- [ ] **Step 7: Commit.**

```bash
git -C /home/orkhan/Desktop/gov-funding-design add apps/research/resolve_entries.py apps/research/resolution/writers.py apps/research/pointers.py apps/research/management/commands/resolve_register.py tests/research/test_resolve_register_command.py tests/research/resolution/test_apply.py
git -C /home/orkhan/Desktop/gov-funding-design commit -m "feat(research): pointers resolve through resolve_register; the unplaceable ask SITE_UNKNOWN

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: A placed pointer is a lead, read by `manage.py read_pointers` (§4.7)

`PointerSource` is a `LeadSource`. It yields one `FUNDER` lead per placed, non-rejected body: its
homepage, with `discovered_by = POINTER:<naming host>`.

- **How it is read:** `read_pointers` runs it through `run_discovery`, the same reader, budget and
  rate limit that `read_closed_list` uses. A holder row written from it records its body through
  `write_holder_decision`'s `record_organisation(found_via="READER:POINTER:<host>")`.
- **The snowball closes:** the pointers those pages name come back through Task 8's `take_pointers`.
- **The limit:** only the homepage is read. Reading the body's other funding pages is §4.2, in
  plan 2.

**Files:**
- Modify: `apps/research/pointers.py`: `PointerSource`
- Create: `apps/research/management/commands/read_pointers.py`
- Test: `tests/research/test_pointers.py` (extend)

**Interfaces:**
- Consumes:
  - `discovery.ResearchLead.from_url(url, *, source_type, funding_family, discovered_by)`;
  - `discovery.DiscoveryQuery`;
  - `funding_reader.FAMILY_BY_HOLDER: dict[str, str]`;
  - `pipeline.run_discovery`, `pipeline.PacedFetch`;
  - Task 9's `pointer_route`.
- Produces:
  - `pointers.PointerSource()`, which has `name == "pointer"` and
    `find(query) -> Iterator[ResearchLead]`;
  - `manage.py read_pointers --tenant <uuid> [--max-leads N] [--cycle YYYY]`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/research/test_pointers.py`:

```python
import os  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

from django.core.management import CommandError, call_command  # noqa: E402

from apps.research.discovery import DiscoveryQuery  # noqa: E402
from apps.research.models import Organisation  # noqa: E402
from apps.research.pointers import PointerSource  # noqa: E402


def _placed(key: str, domain: str, *, host: str = "example-agency.az", status: str = "") -> None:
    org = record_organisation(domain=domain, name=domain, kind="NATIONAL_GOVERNMENT",
                              country_code="AZ", found_via=f"POINTER:{host}")
    if status:
        Organisation.objects.filter(pk=org.pk).update(status=status)
    RegisterEntry.objects.create(
        register=POINTER_REGISTER, external_key=key, name=key, names=[key],
        resolution="RESOLVED", resolved_via="SEARCH_SLUG", organisation=org,
        last_seen=NOW, country_code="AZ", kind="NATIONAL_GOVERNMENT",
        pointer_quote="a line", pointer_url=f"https://{host}/page",
    )


def test_a_placed_body_is_one_funder_lead_found_via_its_pointer() -> None:
    _placed("medeniyyet nazirliyi", "example-ministry.az")
    _placed("medeniyyet nazirliyi ii", "example-ministry.az", host="other.example.az")
    _placed("gone", "example-gone.az", status="REJECTED")
    RegisterEntry.objects.create(
        register=POINTER_REGISTER, external_key="unplaced", name="unplaced",
        resolution="UNRESOLVED", last_seen=NOW,
    )
    leads = list(PointerSource().find(DiscoveryQuery(field="pointer", country_code="")))
    (lead,) = leads  # one body, however many pointers named it
    assert urlsplit(lead.canonical_url).hostname == "example-ministry.az"
    assert (lead.source_type, lead.can_support_claim) == ("FUNDER", True)
    assert lead.funding_family == "GOVERNMENT_SCHOLARSHIP"
    assert lead.discovered_by.startswith("POINTER:")


def test_read_pointers_refuses_without_both_model_families(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "OPENAI_API_KEY" not in os.environ
    with pytest.raises(CommandError, match="OPENAI_API_KEY is unset"):
        call_command("read_pointers", "--tenant", "00000000-0000-0000-0000-000000000001")
```

- [ ] **Step 2: Run them, and confirm that they fail.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research/test_pointers.py`

  Expected: FAIL, `ImportError: cannot import name 'PointerSource'` (collection error).

- [ ] **Step 3: Implement the source.** In `apps/research/pointers.py`, add
  `from collections.abc import Iterable, Iterator` (which replaces the `Iterable` import),
  `from dataclasses import dataclass` and `from uuid import UUID` to the imports, then add
  `from .discovery import DiscoveryQuery, ResearchLead`,
  `from .funding_reader import FAMILY_BY_HOLDER`, and `Organisation` to the `.models` import.
  Append:

```python
@dataclass(frozen=True)
class PointerSource:
    """Placed pointers as FUNDER leads -- a `LeadSource` (spec 2026-09-27 4.7).

    One lead per body, its homepage, most recently named first. Ignores
    `query.country_code`, like `ClosedListSource`: a pointer is scoped by the
    page that named it, not by the run. Reading the body's other funding pages
    is spec 4.2's site reading (plan 2); the reader already finds a homepage's
    funding lines.
    """

    one_programme_per_link: bool = False
    awards_jointly: bool = False

    @property
    def name(self) -> str:
        return POINTER_REGISTER

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        entries = (
            RegisterEntry.objects.filter(
                register=POINTER_REGISTER,
                resolution=RegisterEntry.Resolution.RESOLVED,
                organisation__isnull=False,
            )
            .exclude(organisation__status=Organisation.Status.REJECTED)
            .select_related("organisation")
            .order_by("-last_seen", "external_key")
        )
        seen: set[UUID] = set()
        for entry in entries:
            org = entry.organisation
            assert org is not None  # filtered above; for mypy
            if org.pk in seen:
                continue
            seen.add(org.pk)
            yield ResearchLead.from_url(
                org.official_website or f"https://{org.primary_domain}/",
                source_type="FUNDER",
                funding_family=FAMILY_BY_HOLDER.get(entry.kind or org.kind, ""),
                discovered_by=pointer_route(entry),
            )
```

- [ ] **Step 4: Implement the command.** Create
  `apps/research/management/commands/read_pointers.py`:

```python
"""Read the bodies pointers named, once the resolver placed them (spec 2026-09-27 4.7).

The same reader every other route uses -- `run_discovery` with both model
families, each page paid for and rate-limited before its first reading by
`pipeline._pay_for_funding` (`rate_limited("discovery-extraction", ...)`) --
fed by `PointerSource`. Placing is `manage.py resolve_register --register
pointer --write`; a name nothing placed is a SITE_UNKNOWN item, not a lead.
"""

from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID

import anthropic
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.utils import ProgrammingError
from django.utils import timezone
from openai import OpenAI

from apps.research.discovery import DiscoveryQuery, RunBudget
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import CATALOG_ROLE_NOTE, SweepBudget
from apps.research.funding_judge import FUNDING_READS, MAX_CHUNKS
from apps.research.pipeline import PacedFetch, run_discovery
from apps.research.pointers import POINTER_REGISTER, PointerSource
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope


class Command(BaseCommand):
    help = "Read the bodies pointers named, once the resolver placed them." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--max-leads", type=int, default=60)
        parser.add_argument("--cycle", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            if not os.environ.get(key):
                raise CommandError(f"{key} is unset: a row is served only when two families agree")
        tenant_id = UUID(options["tenant"])
        max_leads = int(options["max_leads"])
        # As read_closed_list counts it: a homepage fetch, and up to three chunks
        # of three readings.
        budget = RunBudget(
            searches=0, fetches=max_leads * 3,
            extractions=max_leads * (1 + FUNDING_READS * MAX_CHUNKS),
        )
        fetch = PacedFetch(
            actor_id=tenant_id, budget=budget, credits=SweepBudget(settings.FETCH_SWEEP_CREDITS)
        )
        try:
            with tenant_scope(tenant_id):
                report = run_discovery(
                    DiscoveryQuery(field=POINTER_REGISTER, country_code="", max_leads=max_leads),
                    [PointerSource()],
                    tenant_id=tenant_id,
                    store=S3ObjectStore(),
                    admissions_cycle=options["cycle"] or str(timezone.now().year + 1),
                    fetch=fetch,
                    budget=budget,
                    funding_parser=cast(ResponsesAPI, OpenAI().responses),
                    funding_claude=cast(MessagesAPI, anthropic.Anthropic().messages),
                )
        except ProgrammingError as error:
            raise CommandError(
                "a database write was refused: the shared catalogue is writable only by "
                f"runtime_engine (run with DATABASE_ROLE=runtime_engine). ({error})"
            ) from error
        self.stdout.write(
            f"leads={report.leads} blocked={report.blocked} "
            f"degraded={','.join(report.degraded) or 'none'} funding: {report.funding}"
        )
        self.stdout.write(f"pointers these pages named: {len(report.pointer_names)}")
```

- [ ] **Step 5: Run the tests.**

  Run: `cd /home/orkhan/Desktop/gov-funding-design && POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly tests/research`

  Expected: all passed.

- [ ] **Step 6: Commit.**

```bash
git -C /home/orkhan/Desktop/gov-funding-design add apps/research/pointers.py apps/research/management/commands/read_pointers.py tests/research/test_pointers.py
git -C /home/orkhan/Desktop/gov-funding-design commit -m "feat(research): a placed pointer is a funder lead, read by manage.py read_pointers

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: The whole branch, through every gate

- [ ] **Step 1: Run every CI gate.**

```bash
cd /home/orkhan/Desktop/gov-funding-design
POSTGRES_DB=elmify_gov uv run pytest -q -p no:randomly
uv run ruff check apps tests config scripts
uv run mypy apps config
POSTGRES_DB=elmify_gov uv run python manage.py check
POSTGRES_DB=elmify_gov uv run python manage.py makemigrations --check --dry-run
uv run bandit -c pyproject.toml -r apps config -q
uv run pip-audit
```

  Expected:
  - pytest reports no failures, with the count above Task 0's baseline by this plan's new tests;
  - ruff reports `All checks passed!`;
  - mypy reports `Success: no issues found`;
  - `check` reports `System check identified no issues`;
  - `makemigrations` reports `No changes detected`;
  - bandit reports no issues;
  - pip-audit reports `No known vulnerabilities found`.

- [ ] **Step 2: Read the delta.** Run
  `git -C /home/orkhan/Desktop/gov-funding-design diff origin/master --stat`. Every file must be in
  the file map. A file outside it is explained or reverted.

---

## Open decisions this plan surfaces (for the owner, not the executor)

1. **Bonded and forgivable money counts** (§7.1, §12). Task 6 writes `FORGIVABLE_LOAN` and shows the
   obligation. Only `LOAN` is dropped.
2. **A track whose level the page never states is written**, as `target_level=UNSTATED`. A literal
   reading of §7.1 ("a scheme with no `MASTER` or `ANY` track is not written") would drop most
   foundation and ministry pages. The plan reads the rule as "a scheme whose named levels exclude
   master's".
3. **`edu.az` leaves the verified zones.** Its own registry's rules call it "defined for general use".
   `gov.kz`, `edu.kz`, `gov.uz` and `gov.ge` leave too, unless Task 2 Step 5 finds their registry's
   page. The classifier then decides those hosts, at one model call each.
4. **Pointer country.** A pointer is read with the country of the body whose page named it, else the
   run's. A Turkish foundation naming DAAD is therefore resolved with Turkish vocabulary (the name is
   in Turkish), and Wikidata is asked within Türkiye first. The resolver's own search rung still
   finds `daad.de`.
5. **Nothing becomes a lead until `RESOLVER_WRITES_ENABLED` is on.** This plan does not move that
   gate.

---

## Self-review (done while writing, 2026-09-27)

**1. Spec coverage for plan 1's sections.**

- **§3:** Task 1 covers the columns, `found_by`, live fetch, separate web-search reporting,
  "MyStart row one", and the owner's review last. Matching a finding to a row is a person's call, so
  no code does it.
- **§4.1 "one list":** Task 2. Bodies, `path_prefix`, renames and cities are plan 2.
- **§4.2 funding words:** Task 3. The language set is built from Wikidata (every current country's
  official languages, `P31`/`P37`/`P424`) plus en and ru, never a hand-typed list -- owner decision
  2026-09-27, students can apply to any country. az, tr, ru and en additionally get answer-key-page
  words today; every other language in the built set gets its page-sourced words as agencies are
  added in plan 2.
- **§4.2 routing-host exemption:** Task 4.
- **§4.7:**
  - Tasks 7 to 10: names become register rows, then `resolver.Resolver`, then
    `record_organisation` with `POINTER:<host>` or a `SITE_UNKNOWN` item, then a `ResearchLead`.
  - The quote is kept on the row and in `SITE_UNKNOWN`'s `why`.
  - The snowball runs through `take_pointers`.
  - Routes §4.3 to §4.6 feed `record_pointers` in plan 2.
- **§7.1:**
  - Task 5 adds the label per track, and conditions per track at the decision.
  - Task 6 adds the column and migration, no `LOAN` rows, `FORGIVABLE_LOAN` kept, and the applier
    guard.
- **§8 step 1:** Task 0.
- **§9:** Global constraints. No new limiter is needed, and `read_pointers` goes through
  `_pay_for_funding`.
- **§10, the lines in scope:** routing hosts (Task 4) and the reader (Tasks 5 and 6).

**2. Placeholder scan.** No code step carries TBD, TODO or "similar to". Three steps carry data, not
code, and each gives a fixed procedure, format and acceptance rule:

- Task 1 Step 5: the answer-key rows;
- Task 2 Step 5: the uncited zones;
- Task 3 Step 5: the page-sourced words.

The migration steps name the leaf by command, not by number, on purpose (Global constraints).

**3. Type consistency.** These names are checked across tasks:

- `read_answer_key` / `KeyRow.official_url` (Tasks 1 and 3);
- `Zone` / `VERIFIED_ZONES` / `government_zone_of` (Task 2);
- `is_reviewed_agency` (Task 4);
- `LineVerdict.target_level`, `FundingDecision.target_level`, `FundingReadResult.other_levels` and
  `FundingCounts.other_levels` (Tasks 5 and 6);
- `LineVerdict.funder` and `PointerLead.funder` (Tasks 7 and 8);
- `POINTER_REGISTER` and `record_pointers` (Task 8);
- `pointer_route`, `ask_for_site`, `file_site_unknown` and `record_resolution(found_via=)` (Task 9);
- `PointerSource` (Task 10).

The existing names were checked against `origin/master` at `a67820e5`: `resolver.Resolution`,
`resolve_entries.record_resolution`, `writers.file_item` / `subject_facts`, `closed_lists.has_signal`,
`funding_reader.FAMILY_BY_HOLDER`, `names.fold`, `card_fields.on_line`, `pipeline.PacedFetch` /
`run_discovery`, and `wikidata.sparql`. `provenance.Recognition` / `Reason.GOVERNMENT_ZONE` were
checked on `claude/provenance-gate-design` at `6429e905`.

**4. Review Focus.** There are five lines, each with its test named in its owning task (Tasks 4, 5,
6 and 9). Checked as covered by ordinary tests, not listed:

- the same body named on many pages (Task 8);
- a row a person answered being reopened (Task 8);
- a paraphrased funder name (Task 7);
- a rejected agency-list row (Task 4);
- a tenant writing the new columns (Tasks 6 and 8, RLS).
