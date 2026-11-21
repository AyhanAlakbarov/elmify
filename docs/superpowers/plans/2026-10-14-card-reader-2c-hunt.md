# Card Reader, Slice 2c: The Site Hunt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Look for a funding card's missing facts on the rest of the official site, and on another
official domain the site links to: find pages through the `sitejob` funnel (URLs only), prove each
by Part B, read it with the same engine restricted to the hunted fields, attach a value only when
the page names the same award (by code), and merge by the newest stated cycle, labelling a value
that is only last cycle's (a date, an amount or an eligibility rule alike) and holding what cannot
be ordered. It runs as a worker step after the read, never inside the 30 s on-demand read.

**Architecture:** Two new modules in `apps/research/card_funding/`. `seek.py` decides where to
look: the funnel's stages (DOCUMENTS → MAP → GUIDED_MAP → NAVIGATOR) as URL sources, link ranking
by a hunt vocabulary kept as data (`docs/research/hunt-terms.csv`), and Part B for every page by
reading the provenance gate's verdict. `hunt.py` decides what to look for and what to keep: the
triggers on a 2b card, `merge` (the cycle rule, the last-cycle label, the hold reasons) and
`hunt_card`, the worker step. The 2b modules get small seams: `questions.py` restricts the set to
fields, `entry.read_page` takes `attach_to` and `fields`, `awards.py` matches names, `card.py`
carries `hunt_not_found`, `Field.label`, `AwardCard.cycle`, `AwardHunt` and `holds_of`, and
`parse.py` carries the "every country but the host" fallback and `stated_cycle`. No model is called
in any test; nothing is stored; no migration; no new dependency.

**Tech Stack:** Python 3 (repo pin), Django settings, the card engine
(`apps/research/card_engine/`), 2b's funding set (`apps/research/card_funding/`), the fetch ladder
and site endpoints (`apps/research/fetch/`), Tavily's guided map (`apps/research/providers/`), the
provenance gate (`apps/research/provenance.py`), `unicodedata`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-verified-catalog-one-reader-design.md` on branch
`claude/slice2-spec-amend` @ 0de03cde — §5.5 step 4 (the hunt) and steps 5–6 (the ladder, the hold
queue), §5.4 ("one engine, generic from the start … the site-hunt step"; filters fail open), §4
(Part B), §3.4 (an `ApplicationSystem` host — not built yet, see Global Constraints); owner
decisions `docs/superpowers/research/2026-10-12-slice2-owner-decisions.md` ("Site hunt", "Hold
queue"); the hunt spike `~/agent-workspace/elmify-runs/slice2-spike/hunt/summary.md` (the
6-of-29 and 19-of-23 figures); the peer rule relayed by the owner on 2026-10-14 (before a target
level is left unsaid, follow the application form or the rules PDF one link away); the owner's answers of 2026-10-14
to this plan's first draft (decisions 3, 4 and 13). The 2b ledger's
`SLICE-3 CARRY` lines bind slice 3 and nothing here contradicts them.

## Plan 3 slice 2 as a whole (this is 2c of 2a–2c)

Plan 3 is the funding reader (verified-catalog §5, §11). Slice 1 (the code finders) and slice 2a
(the engine core, PR #203) are merged; slice 2b (the funding set, the typed card and the 30 s
single-page read, `2026-10-13-card-reader-2b-funding.md`, branch `claude/card-reader-funding`) is
being merged. Slice 2 is "the engine, the funding question set, the site hunt (§5.5 step 4), the
typed card, the single-page entry and track-shaped output" (§5):

- **2a — the engine core (merged).**
- **2b — the funding set (merging).** Its card holds `needs_hunt`, `unresolved_split` and the
  not-stated fields that are this plan's input.
- **2c — the site hunt (this plan).** Triggers from a 2b card; URLs from the funnel; Part B per
  page, another official domain allowed through a printed link; the same engine restricted to the
  hunted fields; strict attach by code; the newest-cycle merge with the last-cycle label and the
  hold reasons; 6 pages per award per hunt, $0.25 and a deadline per page; the record of what was
  done (`Card.hunts`).

After slice 2: slice 3 stores cards, `Card.hunts` and the hold queue; queues `hunt_card` behind an
on-demand read for which `hunt_owed` is true and runs it in the sweep; counts `AwardHunt.pages`
against the cap per cycle across runs; **in the background sweep, runs the provenance check on
every domain a hunt recorded as having no verdict (`AwardHunt.unproven`), then hunts that award
again** (owner, 2026-10-14; 2c itself still follows only domains that already carry a verdict);
hides a target level still not stated after the hunt and files a staff-review item; wires the
serve rule; submits the sweep through the Batch API. Then slice 4
(the cycle verifier) and owner round 2.

## Global Constraints

- Lint only, never `ruff format`: `uv run ruff check .` (CLAUDE.md).
- Types: `uv run mypy apps config`.
- Tests: `POSTGRES_DB=elmify_card_hunt uv run pytest -q` (per-branch DB name, CLAUDE.md).
- `WT` is the plan's worktree; every git command is `git -C "$WT" …`, every commit names its
  paths (sessions share checkouts; never `git add -A`, never `git stash`).
- Never hand-edit `uv.lock`; this plan adds no dependency. No model, no migration.
- Do not touch `apps/research/funding_judge.py` or `pipeline._fund_page` (slice 3).
- The funnel: "every stage returns URLs and nothing else" (`sitejob.py`). No vendor's reading of a
  page, title or snippet is kept, logged or sent to a reader.
- "Every page found must pass Part B: on the proven site, or an `ApplicationSystem` host linked
  from it" and "the hunt may follow a link to a different domain when that domain passes the same
  Part B check" (§5.5 step 4). `ApplicationSystem` (§3.4) does not exist in code yet; an
  application-system host counts here exactly when it has its own RECOGNISED verdict.
- "A hunted value attaches to an award only when the page or section it came from names that same
  award or scheme, matched by code. Otherwise it is discarded." (§5.5 step 4)
- "'Newest' is the cycle the page itself states … parsed by code from a quote. The higher cycle
  wins." "A page stating a cycle beats one stating none." "Only two cases go to the hold queue:
  neither page states a cycle or date, or both state the same cycle with different values."
  (§5.5 step 4)
- "Last cycle's value is shown, labelled … It is not held and not hidden." (§5.5 step 4)
- "Cap: 6 extra pages per award per cycle, charged to the platform budget." (§5.5 step 4)
- Pages a student waits on finish in under 30 s; the sweep may take hours (§0.28; owner
  decisions, "Targets"). At most $0.25 of model spend per page.
- Every reader call goes through `read_page`: D8, the `Guard` (deadline, dollar stop, the
  caller's `Limit` via `rate_limited`), schema-constrained replies (CLAUDE.md LLM rules).
- Worker-side only: `fetch_page` writes `FetchAttempt`/`HostProfile`, which `runtime_web` cannot
  touch; a student-facing view queues the hunt (CLAUDE.md, catalogue boundary).
- Never log a prompt, a reply, a page's text or a link's anchor text; log stage, reason, counts.
- `fetch.site.agent` "returns ARBITRARY OPEN-WEB URLs … Do not wire a caller onto this function
  without `require_origin` (or equivalent) sitting between it and any read": this plan is that
  seam (Part B, then `fetch_page(require_origin=lead)`).
- Not in 2c: storage, models, migrations, the hold queue's table, the serve rule, the Batch API,
  scheduling and the queue message (slice 3); running a provenance check for a new domain;
  host-and-path proof for shared government hosts and P3 (plan 4).

## Decisions this plan takes where the spec is silent

1. **The hunt is a separate worker step; the on-demand read never hunts.** One hunted page is a
   fetch (seconds to tens of seconds on the ladder), a D8 screen and a few reader calls (about
   2.4 s each, §5), and an award may need six of them plus a `/map` call — more than the 30 s a
   student waits for the whole read. So `read_page` stays as 2b built it and returns its card with
   the fields held (`needs_hunt`, `unresolved_split`) or not stated, which the serve rule hides or
   shows as it decides; `hunt_owed(card, today)` tells slice 3's caller to queue
   `hunt_card(card, …)` to the worker, where it runs with the sweep's time and its own per-page
   deadline (decision 14). The student's page updates when the hunt's card is stored (slice 3).
2. **Triggers, exactly** (`hunt.wanted`): a field held `needs_hunt` or `unresolved_split`; a field
   not stated among `dates`, `nationality`, `target_level`, `benefits` — the facts a student is
   matched on or acts on, `target_level` by the peer rule, `benefits` because the spike measured
   amounts; and `dates` when no application date (`application_deadline`, `application_period`)
   is still ahead, so last cycle's deadline sends the hunt after this cycle's. An award whose route
   is `automatic_on_admission` is never hunted for a date (the spike's four misses that "cannot
   exist" were such awards and a repealed one). Not hunted: `held_country_group`,
   `unparseable_value`, `conflicting_values` (the operator fixes wording or a data row); `not_read`,
   `deadline`, `page_budget` (the page is re-read, not hunted); other labels and `requirements`
   when not stated (§5 step 7: not stated is honest when code finds no candidate, and hunting every
   empty label would spend six pages on almost every award).
3. **What a hunt that finds nothing leaves.** `needs_hunt` with "international students" and a
   known host: every country but the host, minus the page's own exclusions (definitions v3);
   any other `needs_hunt`: `hunt_not_found` (the hold queue's "a fact the site hunt could not
   find"); `unresolved_split`: unchanged, so the operator sees the split; a field not stated: not
   stated (code found it nowhere); dates whose application dates have all passed: shown, labelled
   `last_cycle`. **Owner, 2026-10-14:** a `target_level` still not stated after the hunt is hidden
   in slice 3 and a staff-review item is filed (the owner's level rule, relayed through session
   elmify-8c); a nationality with no candidate on any page stays not stated (§5 step 7).
   2c leaves both not stated, and slice 3's serve rule acts on them.
4. **Part B per page reads the gate and never runs it.** A page is proven when
   `provenance_of_named(url)` (its registrable domain's verdict, institutional URL, not a hosting
   platform, body not rejected) is RECOGNISED. A domain with no verdict is not followed and is
   reported in `AwardHunt.unproven`. Running `provenance_job.check_named_url` here would write
   `Organisation`/`ProvenanceVerdict` rows and buy fetches and RDAP inside a hunt, and 2c persists
   nothing. **Owner, 2026-10-14:** the slice-3 background sweep runs the provenance check on
   every domain in `AwardHunt.unproven`, then hunts the award again; 2c's behaviour is unchanged.
   So the 19 of 23 misses the spike found on another official domain are reached on that second
   hunt, once their domains carry a verdict.
5. **Another domain only through a printed link.** DOCUMENTS leads (links a proven page prints, at
   either hop) may sit on any proven domain; MAP and GUIDED_MAP are confined to the start page's
   registrable domain; NAVIGATOR's open-web answer is cut to it. A vendor's open-web pick on a
   recognised but unrelated domain (another university's "Merit Scholarship") would pass both Part
   B and a name match; a link the official site printed is the site vouching for it.
6. **The funnel buys cheapest first and reads what it bought.** DOCUMENTS always (free); MAP when
   DOCUMENTS gave fewer than 6 usable leads (1–2 credits, searched with up to 8 of the hunted
   facts' words in English and the page's language); GUIDED_MAP only when nothing usable was found;
   NAVIGATOR only when still nothing, or always under `FETCH_NAVIGATOR_POLICY=always` (its
   `maxCredits` is `FETCH_AGENT_MAX_CREDITS`). A failed stage is counted (`<stage>_failed`) and the
   next one still runs. Ranking: one point per hunted-fact term a link's folded anchor text and path
   start a word with, plus one for a document (`DOCUMENT_SUFFIXES`) or a vendor's pick; a page link
   with no point is never fetched, so navigation does not spend the cap. The vocabulary covers en,
   az, tr, ru, kk, de, fr, es and is data, reviewed like `funding-terms.csv`.
7. **Hop 2.** Each hunted page's own proven links queue behind the first leads; all count against
   the 6 (the spike found 2 of its 6 at hop 2).
8. **No early stop.** Every lead up to the cap is read, so the cycle rule sees every page found.
   Measured cost per page is about $0.01–0.02 of models plus a credit.
9. **Strict attach by code** (`awards.names_award`): the award's name, folded (case, accents,
   punctuation; dotless ı as i), appears as whole words in order in the name of an award section
   on the hunted page — a heading the readers judged an award name, or the page title when no
   heading passed (2b's grouping, unchanged). A name made only of generic words ("Scholarships",
   "Master's Scholarship 2026") never attaches, and that award is hunted nowhere: the result is the
   same as finding nothing. No transliteration: a Latin "Bolashak" never matches a Cyrillic
   "Болашак", so that value is not attached (the safe direction).
10. **A restricted read asks each hunted field's whole question set** (Task 1), and the rest of a
    hunted card is held unasked and never read by `merge`.
11. **A page's cycle is `stated_cycle`**: the newest intake start year or dated line's year in the
    award's own section, by code. Dates merge through 2b's `_date_conflict` with each date's own
    year as its cycle for ordering, and are shown as their page printed them. Other fields: the
    page with the newest cycle wins, a cycle beats none, and two left disagreeing are held
    `conflicting_values` with detail `hunt:<field>`. Values compare by their parsed value, never
    by quote or source.
12. **Neither `Last-Modified` nor the crawl date breaks a tie.** The spec allows it; the owner file
    sends same-cycle and undated conflicts to the hold queue; `FetchedPage` carries no
    `Last-Modified`, and pages fetched in one hunt are seconds apart. The owner file is newer
    (its own preamble), so precision wins: a tie is held.
13. **The last-cycle label is on every hunted field** (owner, 2026-10-14). Dates: every
    application date shown has passed. Any other field (an amount, a benefit, nationality, level,
    requirements): its value comes from a page whose stated cycle is older than a cycle the award
    states elsewhere -- the start page, another page that named it, an application date still
    ahead -- or, when every application date has passed, is not newer than the latest of them. A
    page stating no cycle cannot be placed and is never labelled. The value is still shown, with
    its source; the label is `Field.label == "last_cycle"`.
14. **Each hunted page is a `read_page`** with its own `Guard`: $0.25 (`PAGE_BUDGET_USD`), a 60 s
    deadline (`HUNT_PAGE_S`, a worker page), the caller's `limit` (the sweep's
    `readers.run_limit`). A URL is fetched once per hunt, whichever awards read it.
15. **`Card.hunts` records each hunted award**: the fields looked for, the pages read and those that
    named the award, each stage's vendor figure, the unproven domains. URLs and numbers only; slice
    3 stores it and enforces "per cycle" across runs.
16. **The fallback's host is the funder's country** — `funder_country`, `None` meaning the
    programme's own (2b decision 5); `""` (unknown) carries no fallback, so a failed hunt holds.

## Review Focus

Every code block below was run before it was written here. The tasks were built in a scratch
worktree off this branch's head (0c9b1547); then **this file's own operations were applied
mechanically, task by task, to a fresh detached worktree off the same head** — every created file,
every exact old → new replacement (each old text occurs exactly once), every appended test — and
each task's tests were run at that task's own state:
- each task's tests fail first (Tasks 1, 2, 4 with failures; Tasks 3, 5, 6, 7 with a collection
  error on the missing module or name), then pass: Task 1 8, Task 2 67 (both files), Task 3 4,
  Task 4 29, Task 5 9, Task 6 11, Task 7 4 — and the whole `tests/research/card_funding` package
  passes at every task's state (132 → 161). Amended 2026-10-15 for the owner's answers (decision
  13): the new `test_a_value_found_only_on_an_older_cycles_page_is_labelled_last_cycle` was run
  first against the earlier `merge` (1 failed), then passes; the operations were re-applied to a
  fresh worktree off b8e8c650 with the same results;
- `uv run ruff check .` clean and `uv run mypy apps/research/card_funding` clean after every task;
  at the end `uv run mypy apps config` clean (734 files), `manage.py check` clean,
  `makemigrations --check --dry-run`: no changes;
- full suite at Task 7's state (`--ignore=tests/documents/test_ocr_prepare.py`, whose OCR
  sub-environment is not built in a fresh worktree; it fails the same way on untouched master):
  8,804 passed, 64 skipped, 429 deselected (the default `live` deselection), measured before the
  amendment, which touches only `card_funding` (its package and `mypy apps config` re-run clean).

The likeliest risks, each pinned by a test in its owning task:

1. **Another scheme's value on the card** (the Bolashak trap: "с 30 марта по 31 мая 2026" belongs
   to an in-country scheme). Owners: `test_a_page_attaches_only_when_it_names_the_same_award_by_code`
   (Task 3), `test_a_hunted_page_that_names_no_such_award_reads_nothing_else` (Task 4), and
   Task 7's end-to-end test, where a Rector's Scholarship page is read and not attached.
2. **An open-web or off-site lead read as official.** Owners:
   `test_the_dear_stages_are_bought_only_when_the_cheaper_found_nothing` (a navigator answer on
   another domain is cut), `test_another_official_domain_counts_only_through_a_link_and_only_when_proven`
   (a map lead off the site is dropped, a printed link to a proven ministry is kept),
   `test_an_unproven_start_site_hunts_nowhere` (Task 5),
   `test_a_domain_never_checked_is_reported_for_its_check` (Task 7).
3. **A stale value shown over a newer one, or an undated page over a dated one.** Owners:
   `test_the_newest_stated_cycle_wins_and_a_dated_page_beats_an_undated_one`,
   `test_pages_that_cannot_be_ordered_go_to_the_hold_queue`,
   `test_only_last_cycles_date_is_shown_labelled_and_nothing_found_keeps_or_holds`,
   `test_a_value_found_only_on_an_older_cycles_page_is_labelled_last_cycle` (Task 6).
4. **A vendor outage read as "this site has no such page"**, which would show the fallback or
   skip to the dearer stage silently. Owner: `test_a_failed_stage_is_counted_and_never_reads_as_no_pages`
   (Task 5).
5. **A generic name attaching every scholarship on a site.** Owner:
   `test_a_name_made_only_of_generic_words_never_attaches` (Task 3).
6. **Runaway spend.** Owners: `test_the_hunt_reads_at_most_six_extra_pages_per_award` (Task 7),
   the dear-stage test above (Task 5); each page's $0.25 and deadline are 2b's `Guard`, already
   pinned there.
7. **The peer's form/PDF rule.** Owner: `test_a_target_level_left_unsaid_follows_the_form_and_the_rules_pdf`
   (Task 5) and `test_the_hunt_looks_for_pointers_splits_missing_facts_and_a_passed_deadline`
   (Task 3: a target level not stated is hunted).

Known and accepted:
- Names match by words in order, so "Vice-Rector's Scholarship" contains "Rector's Scholarship".
  The page must also be proven and reached from the award's own site, and a hunted heading naming
  a different award is the readers' judgement; round 2 measures it.
- A hunted page with no award heading is one award under its title (2b's grouping): a title that
  names the award attaches the whole page, even text that belongs to another scheme without its
  own heading. The readers' heading judgement is the guard, as 2b's risk 1.
- The guided map's and the navigator's brief carries the award's name, which is page text, to
  Tavily and Firecrawl. Only URLs come back, each proven and fetched with `require_origin`.
- A domain with no verdict is not followed (decision 4); until slice 3 queues its check, the hunt
  finds nothing there.

---

## File Structure

| file | responsibility |
|---|---|
| `apps/research/card_funding/questions.py` | `code_questions(c, fields)`, `Funding.fields`, `batches(section, fields)`: the set restricted to the hunted fields (Task 1) |
| `apps/research/card_funding/parse.py` | `stated_cycle`; the "all but the host" fallback carried beside `needs_hunt` (Task 2) |
| `apps/research/card_funding/card.py` | `hunt_not_found`, `Field.label`, `AwardCard.cycle` (Task 2); `holds_of` (Task 6); `AwardHunt`, `Card.hunts` (Task 7) |
| `apps/research/card_funding/awards.py` | `fold`, `nameable`, `names_award`: strict attach by code (Task 3) |
| `apps/research/card_funding/entry.py` | `read_page(..., attach_to, fields)` and each award's `cycle` (Task 4) |
| `docs/research/hunt-terms.csv` | the hunt vocabulary: field (or `*`), term, language (Task 5) |
| `apps/research/card_funding/seek.py` | the funnel's stages, link ranking, Part B per page, `find_leads` (Task 5) |
| `apps/research/card_funding/hunt.py` | triggers (Task 3), `merge` (Task 6), `hunt_owed`, `hunt_card` (Task 7) |
| `tests/research/card_funding/test_{questions,parse,card,entry}.py` | appended tests (Tasks 1, 2, 4) |
| `tests/research/card_funding/test_{hunt,seek,hunt_card}.py` | new (Tasks 3, 5, 6, 7) |

---

### Task 1: The funding set, restricted to the hunted fields

**Files:**
- Modify: `apps/research/card_funding/questions.py` (`AWARD_FIELD`, `_place`, `wants`,
  `code_questions(c, fields)`, `Funding.fields`, `batches(section, fields)`)
- Test: `tests/research/card_funding/test_questions.py` (append)

**Interfaces:**
- Consumes: 2b's `code_questions`, `Funding`, `batches`, `AWARD`, `EXTRAS`, `OBLIGATIONS`.
- Produces: `AWARD_FIELD: dict[str, str]`; `wants(fields: frozenset[str], *names: str) -> bool`;
  `code_questions(c: Candidates, fields: frozenset[str] = frozenset()) -> list[Question]`;
  `Funding(batch: int = 0, fields: frozenset[str] = frozenset())`;
  `batches(section: Section, fields: frozenset[str] = frozenset()) -> int`. Empty `fields` is
  2b's behaviour exactly (same questions, same order, so the same batches).

A field is parsed from a fixed set of questions (`parse.py`): dates from each date's
`role_`/`order_`/`for_all_`/`for_<place>_` questions, nationality from every place's
`eligible_`/`excluded_`/`sole_` plus `place_basis`, `internationals` and `eligibility_elsewhere`,
benefits and fees from every amount's questions, and so on. A restricted read asks a hunted
field's *whole* set, because `parse` holds a field any of its questions left unanswered
(`unresolved_split`). Batch 0's requirement proposal is asked only when `requirements` is hunted;
an empty batch 0 costs nothing (`engine._read` returns before any call when there is nothing to
ask).

- [ ] **Step 1: Write the failing test**

Append to `tests/research/card_funding/test_questions.py`:

```python


def test_a_hunt_asks_only_the_questions_its_fields_are_parsed_from():
    """2c: the same set, restricted to the hunted fields; no fields is every question, in order."""
    c = find_all(SECTION.lines)
    assert code_questions(c, frozenset()) == code_questions(c)
    assert [q.id for q in code_questions(c, frozenset({"target_level"}))] == ["target_level"]
    places = {f"{side}_{k}" for k in c.places for side in ("eligible", "excluded")}
    nationality = {q.id for q in code_questions(c, frozenset({"nationality"}))}
    assert nationality - places == {"place_basis", "internationals", "eligibility_elsewhere",
                                    *(f"sole_{k}" for k in c.places
                                      if c.places[k].value.text.startswith("low-"))}
    dates = [q.id for q in code_questions(c, frozenset({"dates"}))]
    [date] = c.dates
    assert dates[0] == f"role_{date}" and all(q.endswith(date) for q in dates)
    money = {q.id for q in code_questions(c, frozenset({"fees"}))}
    assert money == {q.id for q in code_questions(c, frozenset({"benefits"}))}
    assert all(not q.startswith(("role_", "eligible_", "target_level")) for q in money)


def test_a_hunt_without_requirements_proposes_nothing_and_batches_only_its_own_questions():
    c = find_all(SECTION.lines)
    only = frozenset({"target_level", "dates"})
    assert Funding(batch=0, fields=only).proposals(SECTION) == ()
    assert [q.id for q in Funding(batch=0, fields=frozenset({"requirements"})).proposals(
        SECTION)] == ["requirements"]
    assert batches(SECTION, only) == 1 < batches(SECTION)
    asked = [q.id for q in Funding(batch=1, fields=only).questions(SECTION, c, {})]
    assert asked == [q.id for q in code_questions(c, only)]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_questions.py`
Expected: 2 failed (`TypeError`: `code_questions` takes no `fields`).

- [ ] **Step 3: Implement**

In `apps/research/card_funding/questions.py`, replace:

```python

def _q(qid: str, text: str, options: tuple[str, ...] | None, criteria: str = "") -> Question:
```

with:

```python

#: The card field an AWARD question is parsed into, where it is not the question's own id.
AWARD_FIELD = {"place_basis": "nationality", "internationals": "nationality",
               "eligibility_elsewhere": "nationality",
               **{f"extra_{x}": "extras" for x in EXTRAS},
               **{f"obligation_{x}": "obligations" for x in OBLIGATIONS}}


def _q(qid: str, text: str, options: tuple[str, ...] | None, criteria: str = "") -> Question:
```

In `apps/research/card_funding/questions.py`, replace:

```python

def code_questions(c: Candidates) -> list[Question]:
    """Every question about the award and code's own candidates, in a stable order."""
    qs = [_q(qid, text, options, criteria) for qid, text, options, criteria in AWARD]
    for key in c.amounts:
        if key not in c.conversion_of:  # a conversion is asked about once, with its amount
            qs += _amount(key, c)
    for key in c.dates:
        qs += _date(key, "dates", c)
    for key in c.relative_dates:
        qs += _date(key, "relative_dates", c)
    for key, found in c.places.items():
        ref = f"`places.{key}`"
        qs.append(_q(f"eligible_{key}", f"Do these lines state that applicants connected to {ref} "
                     "can apply, as citizens or residents of it, or as students of an "
                     "institution whose name contains it?", None))
        qs.append(_q(f"excluded_{key}", f"Do these lines state that applicants from {ref} cannot "
                     "apply?", None))
        if group_of(found.value.text) == "LMY":
            qs.append(_q(f"sole_{key}", f"Is {ref} the whole condition on who may apply, with "
                         "nothing added to it?", None))
    qs += [_q(f"requires_{key}", f"Do these lines state `requirements.{key}` as a condition for "
              "applying?", None) for key in c.requirements]
    qs += [_q(f"funds_{key}", f"Does `durations.{key}` state how long the funding lasts, not how "
              "long the programme is?", None) for key in c.durations]
    return qs
```

with:

```python

def _place(key: str, c: Candidates) -> list[Question]:
    ref = f"`places.{key}`"
    qs = [_q(f"eligible_{key}", f"Do these lines state that applicants connected to {ref} "
             "can apply, as citizens or residents of it, or as students of an "
             "institution whose name contains it?", None),
          _q(f"excluded_{key}", f"Do these lines state that applicants from {ref} cannot "
             "apply?", None)]
    if group_of(c.places[key].value.text) == "LMY":
        qs.append(_q(f"sole_{key}", f"Is {ref} the whole condition on who may apply, with "
                     "nothing added to it?", None))
    return qs


def wants(fields: frozenset[str], *names: str) -> bool:
    """Whether a read restricted to `fields` (empty: every field) parses any of `names`."""
    return not fields or bool(fields.intersection(names))


def code_questions(c: Candidates, fields: frozenset[str] = frozenset()) -> list[Question]:
    """Every question about the award and code's own candidates, in a stable order. With
    `fields` (the site hunt, 2c), only the questions those card fields are parsed from -- each
    field's whole set, because `parse` holds a field any of its questions left unanswered."""
    qs = [_q(qid, text, options, criteria) for qid, text, options, criteria in AWARD
          if wants(fields, AWARD_FIELD.get(qid, qid))]
    if wants(fields, "benefits", "fees"):
        for key in c.amounts:
            if key not in c.conversion_of:  # a conversion is asked about once, with its amount
                qs += _amount(key, c)
    if wants(fields, "dates"):
        for key in c.dates:
            qs += _date(key, "dates", c)
        for key in c.relative_dates:
            qs += _date(key, "relative_dates", c)
    if wants(fields, "nationality"):
        for key in c.places:
            qs += _place(key, c)
    if wants(fields, "requirements"):
        qs += [_q(f"requires_{key}", f"Do these lines state `requirements.{key}` as a condition "
                  "for applying?", None) for key in c.requirements]
    if wants(fields, "funding_duration"):
        qs += [_q(f"funds_{key}", f"Does `durations.{key}` state how long the funding lasts, not "
                  "how long the programme is?", None) for key in c.durations]
    return qs
```

In `apps/research/card_funding/questions.py`, replace:

```python
    batch: int = 0
    name: str = "funding"
```

with:

```python
    batch: int = 0
    #: The site hunt reads only these card fields (2c); empty is every field.
    fields: frozenset[str] = frozenset()
    name: str = "funding"
```

In `apps/research/card_funding/questions.py`, replace:

```python
    def proposals(self, section: Section) -> Sequence[Question]:
        return (REQUIREMENTS,) if self.batch == 0 else ()
```

with:

```python
    def proposals(self, section: Section) -> Sequence[Question]:
        return (REQUIREMENTS,) if self.batch == 0 and wants(self.fields, "requirements") else ()
```

In `apps/research/card_funding/questions.py`, replace:

```python
            return kind_questions(candidates, proposed)
        return code_questions(candidates)[(self.batch - 1) * BATCH:self.batch * BATCH]


def batches(section: Section) -> int:
    """How many code batches the section needs (batch 0 comes on top)."""
    return math.ceil(len(code_questions(find_all(section.lines))) / BATCH)
```

with:

```python
            return kind_questions(candidates, proposed)
        return code_questions(candidates, self.fields)[(self.batch - 1) * BATCH:
                                                       self.batch * BATCH]


def batches(section: Section, fields: frozenset[str] = frozenset()) -> int:
    """How many code batches the section needs (batch 0 comes on top)."""
    return math.ceil(len(code_questions(find_all(section.lines), fields)) / BATCH)
```

- [ ] **Step 4: Run the tests, the package and the gates**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_questions.py tests/research/card_funding && uv run ruff check . && uv run mypy apps config`
Expected: all pass; ruff and mypy clean.

- [ ] **Step 5: Commit** (pathspec only: worktrees share checkouts)

```bash
git -C "$WT" commit -m "feat(card-funding): restrict the funding set to the fields a hunt looks for" -- apps/research/card_funding/questions.py tests/research/card_funding/test_questions.py
```

---

### Task 2: What the card carries for the hunt

**Files:**
- Modify: `apps/research/card_funding/card.py` (`HOLD_REASONS` + `hunt_not_found`,
  `Field.label`, `AwardCard.cycle`, a held field keeps its values, `award_card(..., cycle)`)
- Modify: `apps/research/card_funding/parse.py` (`stated_cycle`; `_nationality` carries the
  "every country but the host" fallback beside `needs_hunt`)
- Test: `tests/research/card_funding/test_parse.py`, `tests/research/card_funding/test_card.py`
  (append)

**Interfaces:**
- Consumes: 2b's `Parsed`, `Nationality`, `parse_award(..., funder_country=...)`.
- Produces: `parse.stated_cycle(c: Candidates) -> int | None`; `Field.label: str` (`""` or
  `"last_cycle"`); `AwardCard.cycle: int | None`; `award_card(name, name_quote, parsed,
  cycle: int | None = None)`; `"hunt_not_found"` in `HOLD_REASONS`. A `needs_hunt` nationality
  with detail `internationals` and a known host carries one value: `Nationality(eligible=∅,
  excluded=page's exclusions ∪ {host}, held=uncertain exclusions, …, groups=(…,
  "INTERNATIONAL"))`, quoted from the readers' "international students" answer. A held field is
  never shown, whatever values it carries (2b already carries values on a held `dates`).

Definitions v3: "international students" is not a condition; the hunt looks for the
funder's list, and only when none is found is the award open to "all countries except the host".
`parse` is the one place that has the page's exclusions and the readers' quote, so it builds that
value now and `card` keeps it beside the hold; Task 6 shows it only after a hunt that found
nothing. The host is `funder_country` (2b decision 5's funder: `Program.country_code` on the
programme's own page); unknown (`""`) carries nothing, so a failed hunt holds `hunt_not_found`.
`Field.label` is `"last_cycle"` on any field whose value is only last cycle's (decision 13).
`stated_cycle` is the cycle the spec says code parses from a quote: the newest intake start year
("2026/27") or dated line's year in the award's own section.

- [ ] **Step 1: Write the failing test**

Append to `tests/research/card_funding/test_parse.py`:

```python


def test_international_students_carry_the_all_but_the_host_fallback_for_the_hunt():
    """Definitions v3: "international students" is no list, so it is hunted; the value the hunt
    shows if it finds none -- every country but the host, minus the page's own exclusions -- is
    carried beside the hold, never shown by 2b."""
    s = _section("International students may apply, except citizens of Russia.")
    p1 = _key(s, "places", "Russia")
    fields = _parse(s, {"internationals": ("yes", "International students may apply"),
                        f"excluded_{p1}": ("yes", "except citizens of Russia")},
                    funder_country="HU")
    nationality = fields["nationality"]
    assert (nationality.problem, nationality.detail) == ("needs_hunt", "internationals")
    [fallback] = nationality.values
    assert fallback.value.eligible == set() and fallback.value.excluded == {"HU", "RU"}
    assert fallback.quote.text == "International students may apply"
    unknown = _parse(s, {"internationals": ("yes", "International students may apply")})
    assert unknown["nationality"].values == ()  # no host known: nothing to fall back to
    s = _section("See the list of eligible countries.")
    elsewhere = _parse(s, {"eligibility_elsewhere": ("yes", "See the list of eligible countries")},
                       funder_country="HU")
    assert elsewhere["nationality"].values == ()  # the page says a list exists: never assumed


def test_a_sections_stated_cycle_is_its_newest_intake_or_dated_year():
    from apps.research.card_funding.parse import stated_cycle

    assert stated_cycle(find_all(_section("Call for applications 2026/27").lines)) == 2026
    assert stated_cycle(find_all(_section("Apply by 15 January 2027.",
                                          "Academic year 2025-2026").lines)) == 2027
    assert stated_cycle(find_all(_section("Apply by 15 January.").lines)) is None
```

Append to `tests/research/card_funding/test_card.py`:

```python


def test_a_held_field_keeps_what_the_hunt_may_fall_back_to_and_the_card_its_cycle():
    from apps.research.card_funding.card import Field

    fallback = Value(Nationality(frozenset(), frozenset({"HU"}), frozenset(), "not_stated",
                                 ("INTERNATIONAL",)), None, URL, ())
    card = award_card("A", None, {"nationality": Parsed((fallback,), "needs_hunt",
                                                        "internationals")}, cycle=2026)
    nationality = card.fields["nationality"]
    assert (nationality.state, nationality.hold, nationality.values) == (
        "held", "needs_hunt", (fallback,))
    assert card.cycle == 2026 and nationality.label == ""
    assert "hunt_not_found" in HOLD_REASONS
    assert Field("dates", "shown", label="last_cycle").label == "last_cycle"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_parse.py tests/research/card_funding/test_card.py`
Expected: 3 failed (no `stated_cycle`, no fallback value, `award_card` takes no `cycle`).

- [ ] **Step 3: Implement**

In `apps/research/card_funding/card.py`, replace:

```python

#: Why a field or an award is held. The first five arise from reading; the last three from the
#: read itself (a section never read, the on-demand deadline, the page's dollar stop).
HOLD_REASONS = ("unresolved_split", "held_country_group", "conflicting_values",
                "unparseable_value", "needs_hunt", "not_read", "deadline", "page_budget")
#: Every field a funding card has, in display order.
```

with:

```python

#: Why a field or an award is held. The first five arise from reading; the next three from the
#: read itself (a section never read, the on-demand deadline, the page's dollar stop); the last
#: from the site hunt (2c): a pointer it followed and did not resolve.
HOLD_REASONS = ("unresolved_split", "held_country_group", "conflicting_values",
                "unparseable_value", "needs_hunt", "not_read", "deadline", "page_budget",
                "hunt_not_found")
#: Every field a funding card has, in display order.
```

In `apps/research/card_funding/card.py`, replace:

```python
    detail: str = ""  # a candidate key, question id or group key; never page text
```

with:

```python
    detail: str = ""  # a candidate key, question id or group key; never page text
    #: "last_cycle": shown, but only last cycle's -- every application date shown has passed,
    #: or (any other field) the value comes only from an older cycle's page -- so a student reads
    #: "Last cycle: ... -- new date not announced yet" (§5.5 step 4; owner, 2026-10-14)
    label: str = ""
```

In `apps/research/card_funding/card.py`, replace:

```python
    holds: tuple[Hold, ...]
```

with:

```python
    holds: tuple[Hold, ...]
    #: the newest year code reads in the award's own section (`parse.stated_cycle`): what the
    #: site hunt orders pages by (§5.5 step 4); None states none
    cycle: int | None = None
```

In `apps/research/card_funding/card.py`, replace:

```python
def _field(name: str, parsed: Parsed) -> Field:
    if parsed.problem:
        return Field(name, "held", hold=parsed.problem, detail=parsed.detail)
    if not parsed.values:
```

with:

```python
def _field(name: str, parsed: Parsed) -> Field:
    if parsed.problem:  # values beside a hold are never shown: the hunt's fallback (2c)
        return Field(name, "held", parsed.values, parsed.problem, parsed.detail)
    if not parsed.values:
```

In `apps/research/card_funding/card.py`, replace:

```python

def award_card(name: str, name_quote: Quote | None, parsed: Mapping[str, Parsed]) -> AwardCard:
    if set(parsed) - set(FIELDS):
```

with:

```python

def award_card(name: str, name_quote: Quote | None, parsed: Mapping[str, Parsed],
               cycle: int | None = None) -> AwardCard:
    if set(parsed) - set(FIELDS):
```

In `apps/research/card_funding/card.py`, replace:

```python
            holds.append(Hold("held_country_group", key, groups, held))
    return AwardCard(name, name_quote, fields, tuple(holds))
```

with:

```python
            holds.append(Hold("held_country_group", key, groups, held))
    return AwardCard(name, name_quote, fields, tuple(holds), cycle)
```

In `apps/research/card_funding/parse.py`, replace:

```python
- `needs_hunt`: the value is elsewhere -- a pointer to a list, or only "international students"
  (§5.2.1). Slice 2c hunts it.
"""
```

with:

```python
- `needs_hunt`: the value is elsewhere -- a pointer to a list, or only "international students"
  (§5.2.1). Slice 2c hunts it. For "international students" the field also carries the value the
  hunt shows if it finds no list: every country but the funder's own (definitions v3).
"""
```

In `apps/research/card_funding/parse.py`, replace:

```python

def page_date(decisions: Iterable[Decision], c: Candidates, default: dt.date) -> dt.date:
```

with:

```python

def stated_cycle(c: Candidates) -> int | None:
    """The newest year a section states, read by code: an intake's first year ("2026/27") or a
    dated line's own year. The hunt orders pages by it (§5.5 step 4); None states none."""
    years = [f.value.start_year for f in c.intakes.values()]
    years += [f.value.year for f in c.dates.values() if f.value.year]
    return max(years, default=None)


def page_date(decisions: Iterable[Decision], c: Candidates, default: dt.date) -> dt.date:
```

In `apps/research/card_funding/parse.py`, replace:

```python

def _nationality(a: _Answers, c: Candidates, on: dt.date, source: str) -> Parsed:
    used: list[Decision] = []
```

with:

```python

def _nationality(a: _Answers, c: Candidates, on: dt.date, source: str, host: str) -> Parsed:
    used: list[Decision] = []
```

In `apps/research/card_funding/parse.py`, replace:

```python
        hunt = True
    if hunt:
        raise _Problem("needs_hunt", "eligibility_elsewhere" if elsewhere else "internationals")
    if not (eligible or excluded or held or held_by_exclusion):
        return Parsed()
    quote = next((d.quote for d in used if d.quote is not None and d.value == "yes"), None)
    # a page naming a country eligible outright AND excluding it (through a group it certainly
```

with:

```python
        hunt = True
    quote = next((d.quote for d in used if d.quote is not None and d.value == "yes"), None)
    if hunt:
        if elsewhere or not host:  # a list exists somewhere, or no host to fall back from
            raise _Problem("needs_hunt", "eligibility_elsewhere" if elsewhere else "internationals")
        out = excluded | {host}  # carried for the hunt, shown only when it finds no list (2c)
        fallback = Nationality(frozenset(), frozenset(out), frozenset(held_by_exclusion - out),
                               basis, (*groups, "INTERNATIONAL"))
        said = next((d.quote for d in used if d.value == "yes" and d.quote is not None and (
            d.question == "internationals" or d.question.startswith("eligible_"))), quote)
        return Parsed((Value(fallback, said, source, tuple(used)),), "needs_hunt",
                      "internationals")
    if not (eligible or excluded or held or held_by_exclusion):
        return Parsed()
    # a page naming a country eligible outright AND excluding it (through a group it certainly
```

In `apps/research/card_funding/parse.py`, replace:

```python
    fields["target_level"] = _safe(partial(_level, a, funder_country, lang, source))
    fields["nationality"] = _safe(partial(_nationality, a, c, on, source))
    fields["requirements"] = _safe(partial(_requirements, a, c, proposed, source))
```

with:

```python
    fields["target_level"] = _safe(partial(_level, a, funder_country, lang, source))
    fields["nationality"] = _safe(partial(_nationality, a, c, on, source, funder_country))
    fields["requirements"] = _safe(partial(_requirements, a, c, proposed, source))
```

- [ ] **Step 4: Run the tests, the package and the gates**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_parse.py tests/research/card_funding/test_card.py tests/research/card_funding && uv run ruff check . && uv run mypy apps config`
Expected: all pass; ruff and mypy clean.

- [ ] **Step 5: Commit** (pathspec only: worktrees share checkouts)

```bash
git -C "$WT" commit -m "feat(card-funding): carry a hunt's fallback, a page's cycle and the last-cycle label" -- apps/research/card_funding/card.py apps/research/card_funding/parse.py tests/research/card_funding/test_card.py tests/research/card_funding/test_parse.py
```

---

### Task 3: Triggers and strict attach

**Files:**
- Modify: `apps/research/card_funding/awards.py` (append `fold`, `GENERIC`, `nameable`,
  `names_award`)
- Create: `apps/research/card_funding/hunt.py` (`WHEN_EMPTY`, `HUNTED_HOLDS`, `APPLY_ROLES`,
  `applies_by`, `wanted`)
- Create: `tests/research/card_funding/test_hunt.py`

**Interfaces:**
- Consumes: Task 2's `AwardCard`, `Field`; 2b's `AwardDate`, `Date`.
- Produces: `awards.fold(text: str) -> str`, `awards.nameable(name: str) -> bool`,
  `awards.names_award(text: str, name: str) -> bool`; `hunt.wanted(award: AwardCard,
  today: dt.date) -> frozenset[str]`, `hunt.applies_by(award, today) -> bool`,
  `hunt.WHEN_EMPTY`, `hunt.HUNTED_HOLDS`, `hunt.APPLY_ROLES`, `hunt._ahead(value, today)`.
  Name matching lives in `awards.py` because `entry.read_page` uses it (Task 4) and `hunt.py`
  imports `entry` (Task 7).

Decisions 2, 3 and 9. `wanted` is §5.5 step 4's three triggers, read off the 2b card:
a held `needs_hunt` or `unresolved_split` field, a fact a student is matched on or acts on with no
candidate (`dates`, `nationality`, `target_level` -- the peer's form/PDF rule -- and `benefits`),
and a dates field with no application date still ahead. An award given on admission is never
hunted for a date. `names_award` is the "matched by code" of strict attach: folded whole words,
in order, and never for a name made only of generic words.

- [ ] **Step 1: Write the failing test**

Create `tests/research/card_funding/test_hunt.py`:

```python
import datetime as dt

from apps.research.candidates import Date
from apps.research.card_engine import Quote
from apps.research.card_funding.awards import nameable, names_award
from apps.research.card_funding.card import award_card
from apps.research.card_funding.hunt import wanted
from apps.research.card_funding.parse import AwardDate, Nationality, Parsed, Value

URL = "https://example.edu.az/scholarships"
TODAY = dt.date(2026, 10, 14)


def _date(role, year, month, day):
    date = Date(f"{day}.{month}.{year}", 0, 10, year, month, day)
    return Value(AwardDate(role, date, True, ()), Quote(date.text, "L1.text"), URL, ())


def _label(value):
    return Parsed((Value(value, Quote(value, "L2.text"), URL, ()),))


def test_the_hunt_looks_for_pointers_splits_missing_facts_and_a_passed_deadline():
    card = award_card("A", None, {
        "nationality": Parsed(problem="needs_hunt", detail="eligibility_elsewhere"),
        "holder_kind": Parsed(problem="unresolved_split", detail="holder_kind"),
        "fees": Parsed(problem="unparseable_value", detail="m1"),  # a wording fix, not a hunt
        "dates": Parsed((_date("application_deadline", 2026, 1, 15),)),  # last cycle's
    })
    # target_level and benefits are not stated: code found nothing, so they are looked for
    assert wanted(card, TODAY) == {"nationality", "holder_kind", "dates", "target_level",
                                   "benefits"}
    ahead = award_card("A", None, {"dates": Parsed((_date("application_deadline", 2027, 1, 15),)),
                                   "target_level": _label("master"),
                                   "nationality": Parsed(problem="held_country_group",
                                                         detail="GLOBAL_SOUTH"),
                                   "benefits": Parsed(problem="page_budget")})
    assert wanted(ahead, TODAY) == set()


def test_an_award_given_on_admission_is_not_hunted_for_a_date():
    card = award_card("A", None, {"route": _label("automatic_on_admission"),
                                  "target_level": _label("master"),
                                  "benefits": Parsed(problem="page_budget"),
                                  "nationality": Parsed((Value(Nationality(
                                      frozenset({"AZ"}), frozenset(), frozenset(), "citizenship",
                                      ()), None, URL, ()),))})
    assert wanted(card, TODAY) == set()


def test_a_page_attaches_only_when_it_names_the_same_award_by_code():
    assert names_award("TÜRKİYE BURSLARI 2026 Başvuru Takvimi", "Türkiye Bursları")
    assert names_award("How to apply for the Stipendium Hungaricum", "Stipendium Hungaricum")
    # the Bolashak trap (§5.5 step 4): a different scheme's window on the same site
    assert not names_award("Стипендиальная программа для обучения в вузах Казахстана",
                           "Международная стипендия «Болашак»")
    assert names_award("Стипендия «Болашак» — сроки приёма", "Стипендия Болашак")
    assert not names_award("Hungaricumfoo", "Hungaricum")  # whole words only


def test_a_name_made_only_of_generic_words_never_attaches():
    assert not nameable("Scholarships") and not nameable("Master's Scholarship 2026")
    assert not names_award("Merit Scholarships", "Scholarships")
    assert nameable("Rector's Scholarship") and nameable("DAAD")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_hunt.py`
Expected: collection error (`ModuleNotFoundError: apps.research.card_funding.hunt`).

- [ ] **Step 3: Implement**

In `apps/research/card_funding/awards.py`, replace:

```python
import re
from collections.abc import Mapping, Sequence
```

with:

```python
import re
import unicodedata
from collections.abc import Mapping, Sequence
```

Append to `apps/research/card_funding/awards.py`:

```python


def fold(text: str) -> str:
    """How code compares names: case, accents and punctuation removed, words single-spaced.
    Dotless ı is i, so Turkish capitals (BURSLARI) and lower case (bursları) meet."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("ı", "i"))
    kept = "".join(" " if not ch.isalnum() else ch for ch in decomposed
                   if not unicodedata.combining(ch))
    return " ".join(kept.split())


#: Words that name no award by themselves, folded. A name made only of these (and of numbers)
#: matches every scholarship on a site, so it never attaches a hunted value.
GENERIC = frozenset(fold(w) for w in (
    "a", "an", "and", "for", "in", "of", "the", "to", "s", "award", "awards", "bursary",
    "bursaries", "fellowship", "fellowships", "fund", "funding", "grant", "grants",
    "international", "master", "masters", "phd", "bachelor", "programme", "programmes",
    "program", "programs", "scholarship", "scholarships", "stipend", "stipends", "student",
    "students", "university", "burs", "bursu", "bursları", "təqaüd", "təqaüdü", "стипендия",
    "стипендии", "грант", "гранты", "программа", "stipendium", "stipendien", "bourse",
    "bourses", "beca", "becas", "borsa", "borse", "beurs"))


def nameable(name: str) -> bool:
    """Whether code can match this award's name at all: one word that is not generic."""
    return any(w not in GENERIC and not w.isdigit() for w in fold(name).split())


def names_award(text: str, name: str) -> bool:
    """Whether `text` (a heading or a page title) names the award `name`: its folded words appear
    in it, whole and in order. A name code cannot tell from any other scholarship never does."""
    return nameable(name) and f" {fold(name)} " in f" {fold(text)} "
```

Create `apps/research/card_funding/hunt.py`:

```python
"""The site hunt: a card's missing facts looked for on the other official pages (§5.5 step 4).

A field is hunted when the page points elsewhere (`needs_hunt`), when the readers' split was never
settled (`unresolved_split`), when code found no candidate for a fact a student is matched on or
acts on, or when every application date it shows has passed. The pages come from the `sitejob`
funnel (`seek.py`), URLs only; each is proven by Part B, fetched, and read by the same engine
with the funding set restricted to the hunted fields. A page's value attaches to an award only
when the page or its section names that award, matched by code. Nothing is stored (slice 3).

The hunt runs as its own worker step, never inside the 30 s on-demand read: that read returns
its card with the fields held, and this step follows it (decision 1 of the 2c plan).
"""

from __future__ import annotations

import datetime as dt

from apps.research.candidates import Date

from .card import AwardCard
from .parse import AwardDate, Value

#: Fields hunted when code found no candidate for them: the facts a student is matched on or
#: acts on. A hunt that finds nothing leaves them not stated (§5 step 7; slice 3's serve rule).
WHEN_EMPTY = ("dates", "nationality", "target_level", "benefits")
#: Holds the rest of the site can answer: a pointer elsewhere, a split no reader settled.
HUNTED_HOLDS = frozenset({"needs_hunt", "unresolved_split"})
#: The dates a student applies by: the dates field is hunted while none of these is still ahead.
APPLY_ROLES = frozenset({"application_deadline", "application_period"})


def _ahead(value: Value, today: dt.date) -> bool:
    """A date a student can still apply by; a relative date has no calendar position, so it
    counts as ahead (it moves with the student)."""
    date = value.value.date if isinstance(value.value, AwardDate) else None
    if not isinstance(date, Date):
        return True
    year = date.end_year or date.year or 0
    last = (year, (date.end_month or 12) if date.end_year else (date.month or 12),
            (date.end_day or 31) if date.end_year else (date.day or 31))
    return last >= (today.year, today.month, today.day)


def applies_by(award: AwardCard, today: dt.date) -> bool:
    """Whether the award shows an application date still ahead."""
    dates = award.fields["dates"]
    return dates.state == "shown" and any(
        isinstance(v.value, AwardDate) and v.value.role in APPLY_ROLES and _ahead(v, today)
        for v in dates.values)


def wanted(award: AwardCard, today: dt.date) -> frozenset[str]:
    """The fields the hunt looks for on this award (§5.5 step 4's triggers)."""
    out = {name for name, f in award.fields.items()
           if (f.state == "held" and f.hold in HUNTED_HOLDS)
           or (f.state == "not_stated" and name in WHEN_EMPTY)}
    route = award.fields["route"]
    automatic = route.state == "shown" and route.values[0].value == "automatic_on_admission"
    if award.fields["dates"].state != "held" and not applies_by(award, today):
        out.add("dates")
    if automatic:  # nothing to apply by: an award given on admission has no deadline of its own
        out.discard("dates")
    return frozenset(out)
```

- [ ] **Step 4: Run the tests, the package and the gates**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_hunt.py tests/research/card_funding && uv run ruff check . && uv run mypy apps config`
Expected: all pass; ruff and mypy clean.

- [ ] **Step 5: Commit** (pathspec only: worktrees share checkouts)

```bash
git -C "$WT" add tests/research/card_funding/test_hunt.py apps/research/card_funding/hunt.py
git -C "$WT" commit -m "feat(card-funding): the hunt's triggers and strict attach by name" -- apps/research/card_funding/awards.py apps/research/card_funding/hunt.py tests/research/card_funding/test_hunt.py
```

---

### Task 4: `read_page` reads a hunted page: one award, the hunted fields

**Files:**
- Modify: `apps/research/card_funding/entry.py` (`read_page(..., attach_to="",
  fields=frozenset())`; `AwardCard.cycle` from the section)
- Test: `tests/research/card_funding/test_entry.py` (append)

**Interfaces:**
- Consumes: Task 1's `Funding(batch, fields)`, `batches(section, fields)`; Task 2's
  `stated_cycle`, `award_card(..., cycle)`; Task 3's `names_award`.
- Produces: `read_page(program, url, *, limit, ..., attach_to: str = "", fields: frozenset[str]
  = frozenset()) -> Card`. With `attach_to`, the card's one track holds only the awards whose
  name (heading, or page title when no heading passed) names `attach_to`; none is an empty track
  and a `read` outcome. Every award card now carries `cycle`. Defaults are 2b exactly.

"Read by the same engine with its own quote and source": the hunted page goes through
the same fetch (`require_origin` = the lead itself, so a redirect off it is refused), the same D8
screen, the same award-heading judgement and grouping, the same `Guard`. Strict attach filters the
awards before any funding question is asked, so a page about another scheme costs only its
heading judgement. Each value's `source` is the hunted page's final URL, as 2b already writes.

- [ ] **Step 1: Write the failing test**

Append to `tests/research/card_funding/test_entry.py`:

```python


HUNTED = b"""<html><head><title>Calls</title></head><body><main>
<h1>Open calls</h1>
<h2>Rector's Scholarship</h2>
<p>Applications close on 15 May 2027.</p>
<h2>Merit Award</h2>
<p>Call for applications 2027/28: master students from Azerbaijan.</p>
<p>Applications close on 1 June 2027.</p>
</main></body></html>"""


def test_a_hunted_page_reads_only_the_award_it_names_and_only_the_hunted_fields():
    """2c: strict attach by code, and the funding set restricted to what is hunted."""
    oracle = Oracle({**ANSWERS, "award_L1": ("yes", "Rector's Scholarship"),
                     "award_L2": ("yes", "Merit Award")})
    card = _read(oracle, fetch=_fetch(body=HUNTED), attach_to="Merit Award",
                 fields=frozenset({"target_level"}))
    [merit] = card.tracks[0].awards
    assert merit.name == "Merit Award" and merit.cycle == 2027
    assert merit.fields["target_level"].values[0].value == "master"
    asked = set(oracle.ids())
    assert {q for q in asked if not q.startswith("award_L")} == {"target_level"}
    assert merit.fields["dates"].hold == "unresolved_split"  # never asked: never used


def test_a_hunted_page_that_names_no_such_award_reads_nothing_else():
    oracle = Oracle({**ANSWERS, "award_L1": ("yes", "Rector's Scholarship"),
                     "award_L2": ("yes", "Merit Award")})
    card = _read(oracle, fetch=_fetch(body=HUNTED), attach_to="Bolashak",
                 fields=frozenset({"dates"}))
    assert card.outcome == "read" and card.tracks[0].awards == ()
    assert all(q.startswith("award_L") for q in oracle.ids())
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_entry.py`
Expected: 2 failed (`TypeError`: unexpected keyword `attach_to`).

- [ ] **Step 3: Implement**

In `apps/research/card_funding/entry.py`, replace:

```python
    heading_sections,
    page_lines,
```

with:

```python
    heading_sections,
    names_award,
    page_lines,
```

In `apps/research/card_funding/entry.py`, replace:

```python
from .card import AwardCard, Card, Track, award_card, unread_award
from .parse import parse_award
from .questions import Funding, batches
```

with:

```python
from .card import AwardCard, Card, Track, award_card, unread_award
from .parse import parse_award, stated_cycle
from .questions import Funding, batches
```

In `apps/research/card_funding/entry.py`, replace:

```python
    clock: Callable[[], float] = time.monotonic,
) -> Card:
```

with:

```python
    clock: Callable[[], float] = time.monotonic,
    attach_to: str = "",
    fields: frozenset[str] = frozenset(),
) -> Card:
```

In `apps/research/card_funding/entry.py`, replace:

```python
    guard, so the deadline and the stop hold either way. `limit` is the caller's: a student's
    typed programme passes `readers.tenant_limit`, the sweep `readers.run_limit`."""
    started = clock()
```

with:

```python
    guard, so the deadline and the stop hold either way. `limit` is the caller's: a student's
    typed programme passes `readers.tenant_limit`, the sweep `readers.run_limit`.

    The site hunt (2c) passes `attach_to`, an award's name, and `fields`: only an award this
    page names by code is read (strict attach), and only the questions those fields are parsed
    from are asked. Every other field of that card is held unasked and is never used."""
    started = clock()
```

In `apps/research/card_funding/entry.py`, replace:

```python
            awards, unread = (whole, *awards), 0
        jobs: list[tuple[Award, Section | None, list[Future[Reading]]]] = []
```

with:

```python
            awards, unread = (whole, *awards), 0
        if attach_to:  # the hunt: an award this page does not name is never read (§5.5)
            awards = tuple(a for a in awards if names_award(a.name, attach_to))
        jobs: list[tuple[Award, Section | None, list[Future[Reading]]]] = []
```

In `apps/research/card_funding/entry.py`, replace:

```python
            lines = award_section(page, award)
            jobs.append((award, lines, [run(Funding(batch=n), lines)
                                        for n in range(batches(lines) + 1)]))
        settle(f for *_, futures in jobs for f in futures)
```

with:

```python
            lines = award_section(page, award)
            jobs.append((award, lines, [run(Funding(batch=n, fields=fields), lines)
                                        for n in range(batches(lines, fields) + 1)]))
        settle(f for *_, futures in jobs for f in futures)
```

In `apps/research/card_funding/entry.py`, replace:

```python
            decisions: list[Decision] = [d for r in readings for d in r.decisions]
            parsed = parse_award(decisions, find_all(section.lines), readings[0].proposed,
                                 source=source, funder_country=country, lang=lang, today=today)
            cards.append(award_card(award.name, quote, parsed))
    finally:
```

with:

```python
            decisions: list[Decision] = [d for r in readings for d in r.decisions]
            found = find_all(section.lines)
            parsed = parse_award(decisions, found, readings[0].proposed,
                                 source=source, funder_country=country, lang=lang, today=today)
            cards.append(award_card(award.name, quote, parsed, stated_cycle(found)))
    finally:
```

- [ ] **Step 4: Run the tests, the package and the gates**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_entry.py tests/research/card_funding && uv run ruff check . && uv run mypy apps config`
Expected: all pass; ruff and mypy clean.

- [ ] **Step 5: Commit** (pathspec only: worktrees share checkouts)

```bash
git -C "$WT" commit -m "feat(card-funding): read a hunted page for one award and its hunted fields" -- apps/research/card_funding/entry.py tests/research/card_funding/test_entry.py
```

---

### Task 5: Where to look: the funnel, the hunt vocabulary and Part B per page

**Files:**
- Create: `docs/research/hunt-terms.csv` (field, term, language, note)
- Create: `apps/research/card_funding/seek.py`
- Create: `tests/research/card_funding/test_seek.py`

**Interfaces:**
- Consumes: `sitejob.Stage`, `DOCUMENT_SUFFIXES`, `navigator_policy`; `harvest.anchors`;
  `fetch.site.map_site`, `agent`, `FirecrawlSiteError`; `providers.tavily.tavily_guided_map`,
  `ProviderUnavailable`; `provenance.provenance_of_named`, `RECOGNISED_REASONS`;
  `hosts.registrable_domain`; Task 3's `fold`.
- Produces: `CAP = 6`; `Lead(url, stage, words, base)`; `Vendors(map, guided, navigator)` and
  `vendors() -> Vendors` (the real stages); `term_rows()`; `links(page) -> list[Lead]`;
  `rank(leads, fields) -> list[Lead]`; `brief(award, fields) -> str`; `proven(url) -> bool |
  None`; `usable(url, prove, unproven) -> bool`; `page_leads(page, fields, *, prove, unproven)
  -> list[Lead]`; `find_leads(start, award, fields, *, lang, vendors, spend, unproven,
  prove=proven) -> list[Lead]`.

Decisions 4–7. `sitejob.py` names the stages but has no driver; this is the driver for
the hunt, and it is the seam `fetch.site.agent`'s docstring demands before `/agent` gets a
caller: every URL any stage returns is proven by Part B and then fetched through the ladder with
`require_origin` (Task 4) before anything is read. The vocabulary is data, like
`funding-terms.csv`, folded at load and matched at word starts against a link's anchor text and
path. A document link is a lead whatever its words; a page link needs a hit.

- [ ] **Step 1: Write the failing test**

Create `tests/research/card_funding/test_seek.py`:

```python
from collections import Counter

import pytest

from apps.research.card_funding import seek
from apps.research.card_funding.seek import Lead, Vendors, find_leads, links, rank
from apps.research.fetch.types import FetchedPage
from apps.research.providers.base import ProviderUnavailable
from apps.research.sitejob import Stage

START = "https://beu.edu.az/scholarships/merit"
BODY = b"""<html><body>
<a href="/news/2026">News</a>
<a href="/apply">How to apply</a>
<a href="/merit/eligible-countries">Eligible countries</a>
<a href="/docs/rules.pdf">Rules (PDF)</a>
<a href="https://edu.gov.az/decree-2026.pdf">Decree</a>
<a href="https://blog.example.com/deadline-tips">Application deadline tips</a>
<a href="mailto:office@beu.edu.az">Mail us</a>
</body></html>"""


def _page(body=BODY, url=START):
    return FetchedPage(final_url=url, redirects=(), content_type="text/html", body=body,
                       fetched_via="FIRECRAWL")


def _prove(verdicts):
    """A Part-B stand-in: registrable domain -> True, False or None (never checked)."""
    from apps.research.hosts import registrable_domain

    return lambda url: verdicts.get(registrable_domain(url))


class Stub:
    """Vendors that answer from a script and count what was bought."""

    def __init__(self, mapped=(), guided=(), navigated=(), fail=()):
        self.mapped, self.guided_urls, self.navigated, self.fail = mapped, guided, navigated, fail
        self.bought: list[str] = []

    def vendors(self):
        def stage(name, urls, cost):
            def call(*args):
                self.bought.append(name)
                if name in self.fail:
                    raise ProviderUnavailable(f"{name} down")
                return tuple(urls), cost
            return call
        return Vendors(stage("map", self.mapped, 1.0), stage("guided", self.guided_urls, 0.01),
                       stage("navigator", self.navigated, 40.0))


def test_a_pages_links_are_ranked_by_the_hunted_facts_words_and_documents():
    found = links(_page())
    assert [lead.url for lead in found][:2] == ["https://beu.edu.az/news/2026",
                                                "https://beu.edu.az/apply"]
    assert all(lead.stage == Stage.DOCUMENTS for lead in found)
    assert "mailto:office@beu.edu.az" not in {lead.url for lead in found}
    ranked = [lead.url for lead in rank(found, frozenset({"nationality"}))]
    assert ranked[0] == "https://beu.edu.az/merit/eligible-countries"  # eligib + countr
    assert "https://beu.edu.az/news/2026" not in ranked  # names no hunted fact: never a lead
    assert {"https://beu.edu.az/docs/rules.pdf", "https://edu.gov.az/decree-2026.pdf"} <= set(
        ranked)  # a document is a lead whatever its words


def test_another_official_domain_counts_only_through_a_link_and_only_when_proven():
    stub = Stub(mapped=("https://beu.edu.az/merit/calendar", "https://other.edu.az/calendar"))
    spend: Counter[str] = Counter()
    unproven: set[str] = set()
    leads = find_leads(_page(), "Merit Award", frozenset({"dates"}), lang="en",
                       vendors=stub.vendors(), spend=spend, unproven=unproven,
                       prove=_prove({"beu.edu.az": True, "edu.gov.az": True,
                                     "other.edu.az": True}))
    urls = [lead.url for lead in leads]
    assert "https://edu.gov.az/decree-2026.pdf" in urls  # printed by the proven site
    assert "https://beu.edu.az/merit/calendar" in urls
    assert "https://other.edu.az/calendar" not in urls  # a map lead off the site: dropped
    assert "https://blog.example.com/deadline-tips" not in urls
    assert unproven == {"example.com"}  # never checked: counted for its check, not followed
    assert stub.bought == ["map"] and spend == Counter({"map_credits": 1.0})


def test_the_dear_stages_are_bought_only_when_the_cheaper_found_nothing():
    stub = Stub(guided=(), navigated=("https://beu.edu.az/merit/2027",
                                      "https://www.aggregator.example/merit"))
    spend: Counter[str] = Counter()
    leads = find_leads(_page(b"<html><body></body></html>"), "Merit Award",
                       frozenset({"dates"}), lang="en", vendors=stub.vendors(), spend=spend,
                       unproven=set(), prove=_prove({"beu.edu.az": True}))
    assert stub.bought == ["map", "guided", "navigator"]
    assert [(lead.url, lead.stage) for lead in leads] == [
        ("https://beu.edu.az/merit/2027", Stage.NAVIGATOR)]  # the open web cut to the site
    assert spend["navigator_credits"] == 40.0


def test_a_failed_stage_is_counted_and_never_reads_as_no_pages():
    stub = Stub(guided=("https://beu.edu.az/merit/deadline",), fail=("map",))
    spend: Counter[str] = Counter()
    leads = find_leads(_page(b"<html><body></body></html>"), "Merit Award",
                       frozenset({"dates"}), lang="en", vendors=stub.vendors(), spend=spend,
                       unproven=set(), prove=_prove({"beu.edu.az": True}))
    assert spend["map_failed"] == 1 and stub.bought == ["map", "guided"]
    assert [lead.url for lead in leads] == ["https://beu.edu.az/merit/deadline"]


def test_an_unproven_start_site_hunts_nowhere():
    stub = Stub(mapped=("https://beu.edu.az/merit/calendar",))
    unproven: set[str] = set()
    leads = find_leads(_page(), "Merit Award", frozenset({"dates"}), lang="en",
                       vendors=stub.vendors(), spend=Counter(), unproven=unproven,
                       prove=_prove({}))
    assert leads == [] and stub.bought == [] and "beu.edu.az" in unproven


@pytest.mark.django_db
def test_part_b_reads_the_domains_recognised_verdict_and_nothing_else():
    from tests.research.provenance_helpers import make_body, recognise

    recognise(make_body("beu.edu.az"), "beu.edu.az")
    assert seek.proven("https://www.beu.edu.az/merit/rules.pdf") is True
    assert seek.proven("https://edu.gov.az/decree.pdf") is None  # never checked
    assert seek.proven("https://merit.github.io/page") is False  # a hosting platform


def test_every_term_row_names_a_field_the_hunt_looks_for():
    from apps.research.card_funding.hunt import WHEN_EMPTY

    rows = seek.term_rows()
    assert rows and {field for field, _, _ in rows} <= {"*", *WHEN_EMPTY}
    assert all(term == seek.fold(term) for _, term, _ in rows)  # folded once, at load
    assert len({(f, t) for f, t, _ in rows}) == len(rows)


def test_the_brief_names_the_award_and_the_facts_and_asks_for_urls_only():
    brief = seek.brief("Merit Award", frozenset({"dates", "holder_kind"}))
    assert '"Merit Award"' in brief and "application dates" in brief
    assert "URLs only" in brief and len(brief) < 1_000
    assert isinstance(Lead("u", Stage.MAP, "", 0), Lead)


def test_a_target_level_left_unsaid_follows_the_form_and_the_rules_pdf():
    """Peer rule (owner-relayed 2026-10-14): before the level is left unsaid, the application
    form or the rules PDF one link away is read: a check of 19 Turkish foundations found the
    level only in an application form, and two kept their rules in a PDF."""
    page = _page(b"""<html><body><a href="/contacts">Contacts</a>
<a href="/apply-online">Apply online</a>
<a href="/forms/application.docx">Application form</a>
<a href="/rules.pdf">Scholarship rules</a></body></html>""")
    assert [lead.url.rsplit("/", 1)[1] for lead in rank(links(page), frozenset({"target_level"}))
            ] == ["application.docx", "rules.pdf", "apply-online"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_seek.py`
Expected: collection error (`ModuleNotFoundError: apps.research.card_funding.seek`).

- [ ] **Step 3: Implement**

Create `docs/research/hunt-terms.csv`:

```csv
field,term,language,note
*,apply,en,"apply, applying"
*,applica,en,"application, applicant"
*,requirement,en,
*,criteri,en,"criteria, criterion"
*,condition,en,
*,guideline,en,
*,regulation,en,
*,rules,en,
*,faq,en,
*,form,en,"form, forms"
*,call,en,"call, call for applications"
*,handbook,en,
dates,deadline,en,
dates,dates,en,
dates,calendar,en,
dates,timeline,en,
dates,schedule,en,
nationality,eligib,en,"eligible, eligibility"
nationality,who can,en,
nationality,countr,en,"country, countries"
nationality,citizen,en,
nationality,nationalit,en,
target_level,level,en,
target_level,degree,en,
benefits,amount,en,
benefits,coverage,en,
benefits,benefit,en,
benefits,stipend,en,
benefits,allowance,en,
benefits,payment,en,
*,müraciət,az,application
*,ərizə,az,application form
*,tələb,az,requirement
*,qayda,az,rules
dates,son tarix,az,deadline
dates,təqvim,az,calendar
nationality,kimlər,az,who
nationality,ölkə,az,country
benefits,məbləğ,az,amount
*,başvuru,tr,application
*,şart,tr,condition
*,koşul,tr,condition
*,yönetmelik,tr,regulation
*,yönerge,tr,directive
*,sss,tr,FAQ
dates,takvim,tr,calendar
dates,son başvuru,tr,deadline
nationality,kimler,tr,who
nationality,ülke,tr,country
benefits,tutar,tr,amount
benefits,miktar,tr,amount
benefits,kapsam,tr,coverage
benefits,ödeme,tr,payment
*,заявк,ru,"заявка, заявки"
*,требован,ru,requirements
*,услови,ru,conditions
*,положени,ru,regulations
*,правил,ru,rules
*,анкет,ru,form
dates,срок,ru,"срок, сроки"
dates,приём,ru,"admission; folds to прием, so ё and е both match"
nationality,кто может,ru,who can
nationality,гражда,ru,"граждане, гражданство"
target_level,магистр,ru,master
target_level,бакалавр,ru,bachelor
benefits,размер,ru,amount
benefits,выплат,ru,payments
*,өтінім,kk,application
*,талап,kk,requirement
*,ереже,kk,rules
dates,мерзім,kk,deadline
*,bewerb,de,"Bewerbung, Bewerber"
*,voraussetz,de,requirements
*,richtlinie,de,guidelines
*,merkblatt,de,information sheet
*,formular,de,form
dates,frist,de,deadline
dates,termin,de,dates
nationality,länder,de,countries
benefits,höhe,de,amount
benefits,leistung,de,benefits
*,candidat,fr,"candidature, candidat"
*,règlement,fr,regulations
*,formulaire,fr,form
dates,date limite,fr,deadline
dates,calendrier,fr,calendar
nationality,pays,fr,countries
benefits,montant,fr,amount
*,convocatoria,es,call
*,requisito,es,requirements
*,bases,es,rules of a call
*,solicitud,es,application
dates,plazo,es,deadline
benefits,cuantía,es,amount
```

Create `apps/research/card_funding/seek.py`:

```python
"""Where the site hunt looks: the `sitejob` funnel's stages, URLs only, and Part B per page.

Stages, cheapest first (verified-catalog §5.5 step 4; `sitejob.Stage`), each returning URLs and
nothing else -- no vendor's reading of a page is kept, whichever stage found it:

- DOCUMENTS: the links a fetched page prints -- its documents (a rules PDF, an application form)
  and pages whose anchor text or address names a hunted fact. Free: the page is already fetched.
  The only stage whose leads may sit on another domain, because the official site printed them.
- MAP: Firecrawl /map of the start page's own site, searched with the hunted facts' words.
  Bought when the page's own links gave fewer than `CAP` leads.
- GUIDED_MAP: Tavily's guided map of the same site, only when nothing usable was found so far.
- NAVIGATOR: Firecrawl /agent, only when every cheaper stage found nothing, or always under
  `FETCH_NAVIGATOR_POLICY=always`. Its open-web answer is cut to the start page's own domain.

Every lead passes Part B before it is fetched: its registrable domain carries a RECOGNISED
provenance verdict and the URL is the institution's own voice on it (`proven`). A domain never
checked is not followed; it is counted, so the caller can queue its check (2c decision 4). A
failed stage is counted and the next stage still runs: a vendor outage never reads as "this site
has no such page".
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from django.conf import settings

from apps.research.fetch.site import FirecrawlSiteError, agent, map_site
from apps.research.fetch.types import FetchedPage
from apps.research.harvest import anchors
from apps.research.hosts import registrable_domain
from apps.research.provenance import RECOGNISED_REASONS, provenance_of_named
from apps.research.providers.base import ProviderUnavailable
from apps.research.providers.tavily import tavily_guided_map
from apps.research.sitejob import DOCUMENT_SUFFIXES, Stage, navigator_policy

from .awards import fold

logger = logging.getLogger(__name__)

HUNT_TERMS_FILE = Path(__file__).resolve().parents[3] / "docs" / "research" / "hunt-terms.csv"
#: Extra pages read per award per cycle (owner, 2026-10-09); slice 3 counts it across runs.
CAP = 6
#: Words a /map search carries: the vendor ranks by them, so a short, specific list.
MAP_WORDS = 8

#: (site url, words) -> (urls, credits); (site url, instructions, domain) -> (urls, usd);
#: (start url, brief) -> (urls, credits). Each raises on a vendor failure.
MapStage = Callable[[str, Sequence[str]], tuple[Sequence[str], float]]
GuidedStage = Callable[[str, str, str], tuple[Sequence[str], float]]
NavigatorStage = Callable[[str, str], tuple[Sequence[str], float]]
#: What a stage may raise when the vendor, not the site, failed.
VENDOR_FAILURES = (FirecrawlSiteError, ProviderUnavailable)


@dataclass(frozen=True)
class Vendors:
    map: MapStage
    guided: GuidedStage
    navigator: NavigatorStage


@dataclass(frozen=True)
class Lead:
    url: str
    stage: Stage
    #: folded anchor text and address path: what ranking reads; never stored, logged or sent
    words: str
    #: 1 when the lead is a document or a vendor picked it for the facts; 0 when only its words
    #: can make it a lead
    base: int


@cache
def term_rows() -> tuple[tuple[str, str, str], ...]:
    """(field or "*", folded term, language) per row of `docs/research/hunt-terms.csv`."""
    with HUNT_TERMS_FILE.open(encoding="utf-8", newline="") as handle:
        return tuple((r["field"], fold(r["term"]), r["language"]) for r in csv.DictReader(handle))


def _patterns(fields: frozenset[str]) -> list[re.Pattern[str]]:
    return [re.compile(rf"(?<!\w){re.escape(term)}") for field, term, _ in term_rows()
            if field == "*" or field in fields]


def links(page: FetchedPage) -> list[Lead]:
    """DOCUMENTS: every http(s) link the page prints, once, in page order, with its words."""
    out: dict[str, Lead] = {}
    for anchor in anchors(page.body):
        url = urljoin(page.final_url, anchor.href).split("#")[0]
        if not url.startswith(("http://", "https://")) or url in out or url == page.final_url:
            continue
        path = unquote(urlsplit(url).path)
        document = path.casefold().endswith(DOCUMENT_SUFFIXES)
        out[url] = Lead(url, Stage.DOCUMENTS, fold(f"{anchor.text} {path}"), int(document))
    return list(out.values())


def rank(leads: Sequence[Lead], fields: frozenset[str]) -> list[Lead]:
    """The leads worth a fetch, best first: one hit per hunted-fact term in its words, plus its
    base. A lead with neither is never fetched; ties keep the order they were found in."""
    patterns = _patterns(fields)
    scored = [(sum(1 for p in patterns if p.search(lead.words)) + lead.base, n, lead)
              for n, lead in enumerate(leads)]
    return [lead for score, _, lead in sorted(scored, key=lambda s: (-s[0], s[1])) if score]


_FACTS = {"dates": "the application dates and deadline",
          "nationality": "who may apply (the eligible countries or nationalities)",
          "target_level": "the degree level it is for",
          "benefits": "the amount and what it covers"}


def brief(award: str, fields: frozenset[str]) -> str:
    """The guided map's and the navigator's one instruction. The award's name is page text; a
    vendor reads it, and only URLs come back, each proven before it is fetched."""
    facts = [_FACTS[f] for f in sorted(fields) if f in _FACTS]
    if set(fields) - set(_FACTS):
        facts.append("its conditions and details")
    return (f'Find the pages and files on this site that state {", ".join(facts)} for the award '
            f'"{award[:200]}". Return the URLs only. Do not summarise the pages: we read them '
            "ourselves from the official server.")


def proven(url: str) -> bool | None:
    """Part B for one page: True when its domain carries a RECOGNISED verdict and the URL is the
    institution's own voice on it, False when checked and not recognised (or not institutional),
    None when the domain was never checked. Reads the gate; never runs a check (2c decision 4)."""
    found = provenance_of_named(url)
    if found is None:
        return None
    return found[1] in RECOGNISED_REASONS


def usable(url: str, prove: Callable[[str], bool | None], unproven: set[str]) -> bool:
    """Part B passed; a domain never checked is added to `unproven` and is not usable."""
    domain = registrable_domain(url)
    verdict = prove(url) if domain else False
    if verdict is None:
        unproven.add(domain)
    return bool(verdict)


def page_leads(page: FetchedPage, fields: frozenset[str], *,
               prove: Callable[[str], bool | None], unproven: set[str]) -> list[Lead]:
    """DOCUMENTS for one fetched page: its ranked links that pass Part B, on any domain -- an
    official page printed them (§5.5 step 4, "another official domain counts")."""
    return [lead for lead in rank(links(page), fields) if usable(lead.url, prove, unproven)]


def vendors() -> Vendors:
    """The real stages: Firecrawl /map and /agent on `FIRECRAWL_API_KEY`, Tavily's guided map on
    `SEARCH_API_KEY`. /agent's `maxCredits` is `FETCH_AGENT_MAX_CREDITS` (`site.agent`)."""
    def key() -> str:
        if not settings.FIRECRAWL_API_KEY:
            raise ProviderUnavailable("FIRECRAWL_API_KEY is not set")
        return str(settings.FIRECRAWL_API_KEY)

    def mapped(site: str, words: Sequence[str]) -> tuple[Sequence[str], float]:
        result = map_site(site, api_key=key(), search=words)
        return result.urls, float(result.credits)

    def guided(site: str, instructions: str, domain: str) -> tuple[Sequence[str], float]:
        result = tavily_guided_map(url=site, instructions=instructions, select_domains=[domain])
        return result.urls, result.cost_usd

    def navigated(start: str, prompt: str) -> tuple[Sequence[str], float]:
        result = agent(api_key=key(), urls=[start], prompt=prompt)
        return tuple(url for url, _ in result.leads), float(result.credits)

    return Vendors(mapped, guided, navigated)


def find_leads(start: FetchedPage, award: str, fields: frozenset[str], *, lang: str,
               vendors: Vendors, spend: dict[str, float], unproven: set[str],
               prove: Callable[[str], bool | None] = proven) -> list[Lead]:
    """The proven leads for one award's hunted fields, best first, cheapest stage first.
    `spend` gains each stage's vendor figure (`map_credits`, `guided_usd`,
    `navigator_credits`) or a `<stage>_failed` count; `unproven` gains each domain never
    checked. An unproven start page hunts nowhere: its site is what every lead is proven from."""
    site = registrable_domain(start.final_url)

    def ok(url: str, *, off_site: bool) -> bool:
        return (off_site or registrable_domain(url) == site) and usable(url, prove, unproven)

    if not ok(start.final_url, off_site=False):
        return []
    found = page_leads(start, fields, prove=prove, unproven=unproven)

    def buy(name: str, stage: Stage, unit: str, run: Callable[[], tuple[Sequence[str], float]],
            base: int) -> None:
        try:
            urls, cost = run()
        except VENDOR_FAILURES as error:
            logger.warning("hunt: %s failed (%s)", name, type(error).__name__)
            spend[f"{name}_failed"] = spend.get(f"{name}_failed", 0) + 1
            return
        spend[f"{name}_{unit}"] = spend.get(f"{name}_{unit}", 0) + cost
        seen = {lead.url for lead in found}
        leads = [Lead(url, stage, fold(unquote(urlsplit(url).path)), base) for url in urls
                 if url not in seen and url != start.final_url]
        found.extend(lead for lead in rank(leads, fields) if ok(lead.url, off_site=False))

    words = [t for f, t, lang_ in sorted(term_rows(), key=lambda r: r[0] == "*")
             if (f == "*" or f in fields) and lang_ in {"en", lang}][:MAP_WORDS]
    if len(found) < CAP:
        buy("map", Stage.MAP, "credits", lambda: vendors.map(start.final_url, words), 0)
    if not found:
        buy("guided", Stage.GUIDED_MAP, "usd",
            lambda: vendors.guided(start.final_url, brief(award, fields), site), 1)
    if not found or navigator_policy() == "always":
        buy("navigator", Stage.NAVIGATOR, "credits",
            lambda: vendors.navigator(start.final_url, brief(award, fields)), 1)
    return found
```

- [ ] **Step 4: Run the tests, the package and the gates**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_seek.py tests/research/card_funding && uv run ruff check . && uv run mypy apps config`
Expected: all pass; ruff and mypy clean.

- [ ] **Step 5: Commit** (pathspec only: worktrees share checkouts)

```bash
git -C "$WT" add tests/research/card_funding/test_seek.py docs/research/hunt-terms.csv apps/research/card_funding/seek.py
git -C "$WT" commit -m "feat(card-funding): the hunt's funnel, vocabulary and per-page Part B" -- apps/research/card_funding/seek.py docs/research/hunt-terms.csv tests/research/card_funding/test_seek.py
```

---

### Task 6: Merging what the pages say: the cycle rule, last cycle, the hold queue

**Files:**
- Modify: `apps/research/card_funding/card.py` (`holds_of`, split out of `award_card`)
- Modify: `apps/research/card_funding/hunt.py` (`_dated`, `_dates`, `_newest`, `merge`)
- Test: `tests/research/card_funding/test_hunt.py` (append)

**Interfaces:**
- Consumes: 2b's `card._date_conflict`; Task 2's `Field.label`, `AwardCard.cycle`,
  `hunt_not_found`; Task 3's `_ahead`, `APPLY_ROLES`.
- Produces: `card.holds_of(fields: Mapping[str, Field]) -> tuple[Hold, ...]`;
  `hunt.merge(award: AwardCard, hunted: frozenset[str], found: Sequence[AwardCard],
  today: dt.date) -> AwardCard`. Only hunted fields change; every value keeps its own page's
  `source` and quote; a field whose value is only last cycle's carries `label="last_cycle"`,
  dates or not; the award's holds are recomputed.

Decisions 3, 11, 12, 13. Dates reuse 2b's own cycle rule (`_date_conflict`) across
pages, with each date's own year as its cycle for the ordering only, so "a dated page beats an
undated one" and the newest year wins, while a same-year disagreement and an undated one are
held (`conflicting_values`, detail `hunt:<role>`). Every other field takes the page stating the
newest cycle (`AwardCard.cycle`); a page stating one beats a page stating none; two left
disagreeing are held (`hunt:<field>`). A value from an older cycle's page is shown labelled
`last_cycle` (owner, 2026-10-14; decision 13), computed after the dates so it can read them.
Nothing found: passed dates are shown labelled
`last_cycle`; "international students" shows Task 2's fallback; any other pointer is
`hunt_not_found`; a split stays `unresolved_split`; a field code found nowhere stays not stated.

- [ ] **Step 1: Write the failing test**

In `tests/research/card_funding/test_hunt.py`, replace:

```python
from apps.research.card_funding.card import award_card
from apps.research.card_funding.hunt import wanted
from apps.research.card_funding.parse import AwardDate, Nationality, Parsed, Value
```

with:

```python
from apps.research.card_funding.card import award_card
from apps.research.card_funding.hunt import merge, wanted
from apps.research.card_funding.parse import AwardDate, Nationality, Parsed, Value
```

Append to `tests/research/card_funding/test_hunt.py`:

```python


def _found(cycle, source, **parsed):
    """One hunted page's restricted card of the award, its values sourced to that page."""
    sourced = {name: Parsed(tuple(Value(v.value, v.quote, source, v.decisions)
                                  for v in p.values), p.problem, p.detail)
               for name, p in parsed.items()}
    return award_card("Merit Award", None, sourced, cycle)


def _nat(*eligible):
    return Parsed((Value(Nationality(frozenset(eligible), frozenset(), frozenset(), "citizenship",
                                     ()), None, URL, ()),))


def test_the_newest_stated_cycle_wins_and_a_dated_page_beats_an_undated_one():
    start = award_card("Merit Award", None, {
        "dates": Parsed((_date("application_deadline", 2026, 1, 15),))})
    new = _date("application_deadline", 2027, 1, 15)
    merged = merge(start, frozenset({"dates", "nationality"}), [
        _found(2027, "https://beu.edu.az/calendar", dates=Parsed((new,))),
        _found(None, "https://beu.edu.az/old", nationality=_nat("AZ", "KZ")),
        _found(2026, "https://edu.gov.az/list", nationality=_nat("AZ")),
    ], TODAY)
    [deadline] = merged.fields["dates"].values
    assert (deadline.value.date.year, deadline.source) == (2027, "https://beu.edu.az/calendar")
    assert merged.fields["dates"].label == ""
    [who] = merged.fields["nationality"].values
    assert (who.value.eligible, who.source) == ({"AZ"}, "https://edu.gov.az/list")


def test_pages_that_cannot_be_ordered_go_to_the_hold_queue():
    start = award_card("Merit Award", None, {})
    undated = merge(start, frozenset({"nationality"}), [
        _found(None, "https://a.edu.az/x", nationality=_nat("AZ")),
        _found(None, "https://a.edu.az/y", nationality=_nat("KZ"))], TODAY)
    assert (undated.fields["nationality"].hold, undated.fields["nationality"].detail) == (
        "conflicting_values", "hunt:nationality")
    same = merge(start, frozenset({"nationality"}), [
        _found(2026, "https://a.edu.az/x", nationality=_nat("AZ")),
        _found(2026, "https://a.edu.az/y", nationality=_nat("KZ"))], TODAY)
    assert same.fields["nationality"].hold == "conflicting_values"
    agree = merge(start, frozenset({"nationality"}), [
        _found(None, "https://a.edu.az/x", nationality=_nat("AZ")),
        _found(None, "https://a.edu.az/y", nationality=_nat("AZ"))], TODAY)
    assert agree.fields["nationality"].state == "shown"
    dates = merge(start, frozenset({"dates"}), [
        _found(None, "https://a.edu.az/x",
               dates=Parsed((_date("application_deadline", 2027, 1, 15),))),
        _found(None, "https://a.edu.az/y",
               dates=Parsed((_date("application_deadline", 2027, 2, 1),)))], TODAY)
    assert dates.fields["dates"].hold == "conflicting_values"
    assert ("conflicting_values", "dates") in {(h.reason, h.field) for h in dates.holds}


def test_only_last_cycles_date_is_shown_labelled_and_nothing_found_keeps_or_holds():
    start = award_card("Merit Award", None, {
        "dates": Parsed((_date("application_deadline", 2026, 1, 15),)),
        "nationality": Parsed(problem="needs_hunt", detail="eligibility_elsewhere"),
        "holder_kind": Parsed(problem="unresolved_split", detail="holder_kind")})
    merged = merge(start, frozenset({"dates", "nationality", "holder_kind", "target_level"}), [],
                   TODAY)
    assert (merged.fields["dates"].state, merged.fields["dates"].label) == ("shown", "last_cycle")
    assert (merged.fields["nationality"].hold, merged.fields["nationality"].detail) == (
        "hunt_not_found", "eligibility_elsewhere")
    assert merged.fields["holder_kind"].hold == "unresolved_split"  # the operator's, as it was
    assert merged.fields["target_level"].state == "not_stated"  # code found it nowhere
    assert ("hunt_not_found", "nationality") in {(h.reason, h.field) for h in merged.holds}


def test_no_list_found_for_international_students_shows_every_country_but_the_host():
    fallback = Value(Nationality(frozenset(), frozenset({"HU"}), frozenset(), "not_stated",
                                 ("INTERNATIONAL",)), None, URL, ())
    start = award_card("Merit Award", None, {
        "nationality": Parsed((fallback,), "needs_hunt", "internationals")})
    merged = merge(start, frozenset({"nationality"}), [], TODAY)
    assert (merged.fields["nationality"].state, merged.fields["nationality"].values) == (
        "shown", (fallback,))
    assert merged.holds == ()


def test_a_hunted_page_never_touches_a_field_that_was_not_hunted():
    start = award_card("Merit Award", None, {"target_level": _label("master")})
    merged = merge(start, frozenset({"dates"}), [
        _found(2027, "https://a.edu.az/x", target_level=_label("phd"))], TODAY)
    assert merged.fields["target_level"] == start.fields["target_level"]


def test_a_date_is_shown_as_its_page_printed_it():
    new = _date("application_deadline", 2027, 1, 15)
    merged = merge(award_card("Merit Award", None, {}), frozenset({"dates"}),
                   [_found(2027, URL, dates=Parsed((new,)))], TODAY)
    assert merged.fields["dates"].values == (new,) and new.value.cycle is None


def test_a_value_found_only_on_an_older_cycles_page_is_labelled_last_cycle():
    """Owner, 2026-10-14: amounts, benefits and eligibility rules are labelled as dates are."""
    start = award_card("Merit Award", None, {}, cycle=2027)
    merged = merge(start, frozenset({"nationality", "target_level"}), [
        _found(2026, "https://a.edu.az/2026", nationality=_nat("AZ")),
        _found(None, "https://a.edu.az/x", target_level=_label("master"))], TODAY)
    assert (merged.fields["nationality"].state, merged.fields["nationality"].label) == (
        "shown", "last_cycle")  # the start page states 2027; this list is 2026's
    assert merged.fields["target_level"].label == ""  # an undated page has no cycle to place
    current = merge(start, frozenset({"nationality"}), [
        _found(2027, "https://a.edu.az/2027", nationality=_nat("AZ"))], TODAY)
    assert current.fields["nationality"].label == ""
    passed = award_card("Merit Award", None, {
        "dates": Parsed((_date("application_deadline", 2026, 1, 15),))})
    merged = merge(passed, frozenset({"dates", "nationality"}), [
        _found(2026, "https://a.edu.az/2026", nationality=_nat("AZ"))], TODAY)
    # every application date has passed, and the list is that cycle's: both are last cycle's
    assert merged.fields["dates"].label == merged.fields["nationality"].label == "last_cycle"
    ahead = award_card("Merit Award", None, {
        "dates": Parsed((_date("application_deadline", 2027, 1, 15),))})
    merged = merge(ahead, frozenset({"nationality"}), [
        _found(2026, "https://a.edu.az/2026", nationality=_nat("AZ"))], TODAY)
    assert merged.fields["nationality"].label == "last_cycle"  # a 2027 deadline is still ahead
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_hunt.py`
Expected: collection error (`ImportError: cannot import name 'merge'`).

- [ ] **Step 3: Implement**

In `apps/research/card_funding/card.py`, replace:

```python
    fields = {key: _field(key, parsed.get(key, Parsed())) for key in FIELDS}
    holds = [Hold(f.hold, f.name, f.detail) for f in fields.values() if f.state == "held"]
```

with:

```python
    fields = {key: _field(key, parsed.get(key, Parsed())) for key in FIELDS}
    return AwardCard(name, name_quote, fields, holds_of(fields), cycle)


def holds_of(fields: Mapping[str, Field]) -> tuple[Hold, ...]:
    """Every hold the fields carry: each held field, and the countries a shown value holds."""
    holds = [Hold(f.hold, f.name, f.detail) for f in fields.values() if f.state == "held"]
```

In `apps/research/card_funding/card.py`, replace:

```python
            holds.append(Hold("held_country_group", key, groups, held))
    return AwardCard(name, name_quote, fields, tuple(holds), cycle)
```

with:

```python
            holds.append(Hold("held_country_group", key, groups, held))
    return tuple(holds)
```

In `apps/research/card_funding/hunt.py`, replace:

```python
import datetime as dt
```

with:

```python
import datetime as dt
from collections.abc import Sequence
from dataclasses import replace
```

In `apps/research/card_funding/hunt.py`, replace:

```python

from .card import AwardCard
from .parse import AwardDate, Value
```

with:

```python

from .card import AwardCard, Field, _date_conflict, holds_of
from .parse import AwardDate, Value
```

Append to `apps/research/card_funding/hunt.py`:

```python


def _dated(value: Value) -> Value:
    """Across pages a date's own year is the cycle it states (owner, 2026-10-09: "a dated page
    beats an undated one"); a date with an intake on its line keeps that intake's year."""
    d = value.value
    if isinstance(d, AwardDate) and d.cycle is None and isinstance(d.date, Date) and d.date.year:
        return replace(value, value=replace(d, cycle=d.date.year))
    return value


def _dates(start: Field, pages: list[Field], today: dt.date) -> Field:
    """Every page's dates and the start page's -- each already settled on its own page -- ordered
    by 2b's cycle rule with each date's year as its cycle: the newest wins, a stated year beats
    none, and what that cannot order is held (§5.5 step 4)."""
    values = (*(start.values if start.state == "shown" else ()),
              *(v for f in pages for v in f.values))
    if not values:
        return start
    dated = tuple(map(_dated, values))
    printed = {id(d): v for v, d in zip(values, dated, strict=True)}
    ordered, conflict = _date_conflict(dated)
    if conflict:
        return Field("dates", "held", values, "conflicting_values", f"hunt:{conflict}")
    kept = tuple(printed[id(v)] for v in ordered)  # shown as the pages printed them
    applies = [v for v in kept if isinstance(v.value, AwardDate) and v.value.role in APPLY_ROLES]
    passed = bool(applies) and not any(_ahead(v, today) for v in applies)
    return Field("dates", "shown", kept, label="last_cycle" if passed else "")


def _newest(name: str, start: Field,
            pages: list[tuple[int | None, Field]]) -> tuple[Field, int | None]:
    """One page's value and that page's cycle: the page stating the newest cycle; a page stating
    one beats a page stating none; two pages left disagreeing are held. Nothing found keeps the
    start page's field, except a pointer the hunt followed: "international students" with no
    list found is every country but the host (definitions v3), and any other pointer is
    `hunt_not_found`."""
    if not pages:
        if start.hold == "needs_hunt" and start.detail == "internationals" and start.values:
            return Field(name, "shown", start.values), None
        if start.hold == "needs_hunt":
            return Field(name, "held", hold="hunt_not_found", detail=start.detail), None
        return start, None
    newest = max((cycle for cycle, _ in pages if cycle is not None), default=None)
    top = [field for cycle, field in pages if cycle == newest]
    if len({tuple(v.value for v in field.values) for field in top}) > 1:
        return Field(name, "held", tuple(v for f in top for v in f.values), "conflicting_values",
                     f"hunt:{name}"), newest
    return Field(name, "shown", top[0].values), newest


def _year(value: Value) -> int | None:
    d = value.value
    if not isinstance(d, AwardDate):
        return None
    if d.cycle is not None:
        return d.cycle
    return (d.date.end_year or d.date.year) if isinstance(d.date, Date) else None


def _last_cycle(cycle: int | None, award: AwardCard, found: Sequence[AwardCard], dates: Field,
                today: dt.date) -> bool:
    """Whether a value from a page stating `cycle` is only last cycle's (owner, 2026-10-14:
    amounts and eligibility rules are labelled as dates are): the award states a newer cycle
    somewhere -- its start page, another page that named it, an application date still ahead --
    or every application date has passed and this page's cycle is not newer than the latest of
    them. An undated page cannot be placed in a cycle and is never labelled."""
    if cycle is None:
        return False
    shown = dates.values if dates.state == "shown" else ()
    applies = [v for v in shown if isinstance(v.value, AwardDate) and v.value.role in APPLY_ROLES]
    stated = [award.cycle, *(card.cycle for card in found),
              *(_year(v) for v in applies if _ahead(v, today))]
    if any(c is not None and cycle < c for c in stated):
        return True
    passed = [y for v in applies if (y := _year(v)) is not None]
    return dates.label == "last_cycle" and bool(passed) and cycle <= max(passed)


def merge(award: AwardCard, hunted: frozenset[str], found: Sequence[AwardCard],
          today: dt.date) -> AwardCard:
    """The award with what the hunt found: each hunted field from the pages that named the
    award, each value keeping its own page as its source, labelled `last_cycle` when it is only
    last cycle's; every other field as it was."""
    def shown(name: str) -> list[tuple[int | None, Field]]:
        return [(card.cycle, card.fields[name]) for card in found
                if card.fields[name].state == "shown"]

    fields = dict(award.fields)
    if "dates" in hunted:  # first: the other fields' labels read the dates
        fields["dates"] = _dates(award.fields["dates"], [f for _, f in shown("dates")], today)
    for name in sorted(hunted - {"dates"}):
        field, cycle = _newest(name, award.fields[name], shown(name))
        if field.state == "shown" and _last_cycle(cycle, award, found, fields["dates"], today):
            field = replace(field, label="last_cycle")
        fields[name] = field
    return replace(award, fields=fields, holds=holds_of(fields))
```

- [ ] **Step 4: Run the tests, the package and the gates**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_hunt.py tests/research/card_funding && uv run ruff check . && uv run mypy apps config`
Expected: all pass; ruff and mypy clean.

- [ ] **Step 5: Commit** (pathspec only: worktrees share checkouts)

```bash
git -C "$WT" commit -m "feat(card-funding): merge hunted values by the newest stated cycle" -- apps/research/card_funding/card.py apps/research/card_funding/hunt.py tests/research/card_funding/test_hunt.py
```

---

### Task 7: `hunt_card`: the worker step, its caps and its record

**Files:**
- Modify: `apps/research/card_funding/card.py` (`AwardHunt`, `Card.hunts`)
- Modify: `apps/research/card_funding/hunt.py` (`HUNT_PAGE_S`, `hunt_owed`, `hunt_card`)
- Create: `tests/research/card_funding/test_hunt_card.py`

**Interfaces:**
- Consumes: everything above; `entry.read_page`, `entry.PAGE_BUDGET_USD`;
  `fetch.fetch_page`, `CARRIES_BYTES`.
- Produces: `AwardHunt(award, fields, pages, attached, spend, unproven)`; `Card.hunts:
  tuple[AwardHunt, ...]`; `hunt.hunt_owed(card: Card, today: dt.date) -> bool`;
  `hunt.hunt_card(card, program, *, limit, funder_country=None, today=None, readers=None,
  transport=None, fetch=fetch_page, screen_page=screen, vendors=None, prove=proven,
  page_deadline_s=HUNT_PAGE_S, budget_usd=PAGE_BUDGET_USD, clock=time.monotonic) -> Card`.
  Slice 3's worker calls `hunt_card` on a card for which `hunt_owed` is true and stores the
  result with `Card.hunts`.

Decisions 1, 8, 14, 15. The on-demand read never calls this. Per award: `wanted`, the
funnel's proven leads, then at most `CAP` pages read through `read_page(attach_to=award.name,
fields=wanted)` -- each with its own `Guard` ($0.25, `HUNT_PAGE_S`) and the caller's `limit` --
with each fetched page's own proven links queued behind (hop 2), then `merge`. One fetch per URL
per hunt, whichever awards read it. Calls, spend, unpriced and running calls are added to the
card's own; the record per award is URLs and figures only.

- [ ] **Step 1: Write the failing test**

Create `tests/research/card_funding/test_hunt_card.py`:

```python
import datetime as dt
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.research.card_engine import Limit
from apps.research.card_engine.screen import Screen
from apps.research.card_funding.entry import read_page
from apps.research.card_funding.hunt import hunt_card, hunt_owed
from apps.research.card_funding.seek import CAP, Vendors
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.hosts import registrable_domain

from .oracle import Oracle

START = "https://beu.edu.az/scholarships"
PROGRAM = SimpleNamespace(id=uuid4(), country_code="AZ")
TODAY = dt.date(2026, 10, 14)
PAGES = {
    START: b"""<html><body><main><h1>Scholarships</h1><p>Our scholarships.</p>
<h2>Merit Award</h2><p>Tuition waiver for international master students.</p>
<p><a href="/merit/calendar">Application calendar</a>
<a href="https://edu.gov.az/merit-countries">Eligible countries</a>
<a href="/rector">Rector's Scholarship</a> <a href="/news">News</a></p></main></body></html>""",
    "https://beu.edu.az/merit/calendar": b"""<html><body><main><h1>Merit Award calendar</h1>
<p>Applications close on 1 June 2027.</p></main></body></html>""",
    "https://edu.gov.az/merit-countries": b"""<html><body><main>
<h1>Merit Award: eligible countries</h1>
<p>Citizens of Azerbaijan and Kazakhstan may apply.</p></main></body></html>""",
    "https://beu.edu.az/other-dates": b"""<html><body><main><h1>Rector's Scholarship</h1>
<p>Applications close on 5 May 2027.</p></main></body></html>""",
}
ANSWERS = {
    "award_L1": ("yes", "Merit Award"),
    "internationals": ("yes", "international master students"),
    "target_level": ("master", "master students"),
    "role_d1": ("application_deadline", "Applications close on 1 June 2027."),
    "eligible_p1": ("yes", "Citizens of Azerbaijan and Kazakhstan may apply."),
    "eligible_p2": ("yes", "Citizens of Azerbaijan and Kazakhstan may apply."),
    "place_basis": ("citizenship", "Citizens of"),
}


@pytest.fixture(autouse=True)
def _keys(settings, monkeypatch):
    settings.OPENROUTER_API_KEY = "test-openrouter-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")


def _fetch(pages):
    asked = []

    def fetch(url, **kwargs):
        asked.append(url)
        if url not in pages:
            return FetchedPage(final_url=url, redirects=(), content_type="", body=b"",
                               fetched_via="FIRECRAWL", outcome=Outcome.UNREACHABLE)
        return FetchedPage(final_url=url, redirects=(), content_type="text/html",
                           body=pages[url], fetched_via="FIRECRAWL")
    fetch.asked = asked
    return fetch


def _clear(section, *, limit, timeout_s=None):
    return Screen("clear", section.texts())


def _vendors(mapped=()):
    bought = []

    def stage(name, urls, cost):
        def call(*args):
            bought.append(name)
            return tuple(urls), cost
        return call
    vendors = Vendors(stage("map", mapped, 1.0), stage("guided", (), 0.01),
                      stage("navigator", (), 40.0))
    return vendors, bought


def _prove(url):
    return {"beu.edu.az": True, "edu.gov.az": True}.get(registrable_domain(url))


def _limit():
    return Limit("card-hunt-test", uuid4(), 500, 3600)


def _start(oracle, fetch):
    return read_page(PROGRAM, START, limit=_limit(), today=TODAY, transport=oracle, fetch=fetch,
                     screen_page=_clear)


def test_the_hunt_finds_a_cards_missing_facts_on_proven_pages_that_name_the_award():
    oracle, fetch = Oracle(ANSWERS), _fetch(PAGES)
    card = _start(oracle, fetch)
    [merit] = card.tracks[0].awards
    assert merit.fields["nationality"].hold == "needs_hunt" and hunt_owed(card, TODAY)
    vendors, bought = _vendors(mapped=("https://beu.edu.az/other-dates",))
    hunted = hunt_card(card, PROGRAM, limit=_limit(), today=TODAY, transport=oracle,
                       fetch=fetch, screen_page=_clear, vendors=vendors, prove=_prove)
    [merit] = hunted.tracks[0].awards
    [deadline] = merit.fields["dates"].values
    assert (deadline.value.date.month, deadline.source) == (6, "https://beu.edu.az/merit/calendar")
    [who] = merit.fields["nationality"].values  # another official domain, printed as a link
    assert (who.value.eligible, who.source) == ({"AZ", "KZ"}, "https://edu.gov.az/merit-countries")
    assert merit.fields["target_level"] == card.tracks[0].awards[0].fields["target_level"]
    assert merit.fields["benefits"].state == "not_stated"  # looked for, found nowhere
    assert merit.holds == () and not hunt_owed(hunted, TODAY)
    [report] = hunted.hunts
    assert report.award == "Merit Award"
    assert report.fields == ("benefits", "dates", "nationality")
    assert report.pages == ("https://beu.edu.az/merit/calendar",
                            "https://edu.gov.az/merit-countries", "https://beu.edu.az/other-dates")
    assert report.attached == report.pages[:2]  # the Rector's page names another award
    assert bought == ["map"] and dict(report.spend) == {"map_credits": 1.0}
    assert hunted.cost_usd > card.cost_usd and len(hunted.calls) > len(card.calls)
    assert fetch.asked.count(START) == 2  # the read, then the hunt's own fetch for its links


def test_the_hunt_reads_at_most_six_extra_pages_per_award():
    links = "".join(f'<a href="/merit/calendar-{n}">Calendar {n}</a>' for n in range(CAP + 3))
    pages = {START: PAGES[START].replace(b"<a href=\"/news\">News</a>", links.encode())}
    oracle, fetch = Oracle(ANSWERS), _fetch(pages)
    card = _start(oracle, fetch)
    vendors, _ = _vendors()
    hunted = hunt_card(card, PROGRAM, limit=_limit(), today=TODAY, transport=oracle,
                       fetch=fetch, screen_page=_clear, vendors=vendors, prove=_prove)
    [report] = hunted.hunts
    assert len(report.pages) == CAP and report.attached == ()
    [merit] = hunted.tracks[0].awards
    assert merit.fields["nationality"].state == "shown"  # no list anywhere: all but the host
    assert merit.fields["nationality"].values[0].value.excluded == {"AZ"}


def test_a_card_with_nothing_to_hunt_or_nothing_read_is_returned_as_it_was():
    oracle, fetch = Oracle(ANSWERS), _fetch({START: b"<html></html>"})
    unread = _start(oracle, fetch)
    assert unread.outcome.startswith("unreadable") and not hunt_owed(unread, TODAY)
    vendors, bought = _vendors()
    assert hunt_card(unread, PROGRAM, limit=_limit(), today=TODAY, transport=oracle,
                     fetch=fetch, screen_page=_clear, vendors=vendors, prove=_prove) is unread
    assert bought == []


def test_a_domain_never_checked_is_reported_for_its_check():
    oracle, fetch = Oracle(ANSWERS), _fetch(PAGES)
    card = _start(oracle, fetch)
    vendors, _ = _vendors()
    hunted = hunt_card(card, PROGRAM, limit=_limit(), today=TODAY, transport=oracle,
                       fetch=fetch, screen_page=_clear, vendors=vendors,
                       prove=lambda url: True if "beu.edu.az" in url else None)
    [report] = hunted.hunts
    assert report.unproven == ("edu.gov.az",)
    assert "https://edu.gov.az/merit-countries" not in report.pages
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_hunt_card.py`
Expected: collection error (`ImportError: cannot import name 'hunt_card'`).

- [ ] **Step 3: Implement**

In `apps/research/card_funding/card.py`, replace:

```python
@dataclass(frozen=True)
class Card:
```

with:

```python
@dataclass(frozen=True)
class AwardHunt:
    """What the site hunt did for one award (2c): URLs and counts, never page text. Slice 3
    stores it, and counts `pages` against the cap of 6 extra pages per award per cycle."""

    award: str
    fields: tuple[str, ...]  # the fields looked for
    pages: tuple[str, ...]  # every page read, in order
    attached: tuple[str, ...]  # of those, the pages that named the award
    spend: tuple[tuple[str, float], ...]  # vendor figures per stage, or "<stage>_failed" counts
    unproven: tuple[str, ...]  # domains never checked by Part B: not followed, owed a check


@dataclass(frozen=True)
class Card:
```

In `apps/research/card_funding/card.py`, replace:

```python
    seconds: float = 0.0
```

with:

```python
    seconds: float = 0.0
    hunts: tuple[AwardHunt, ...] = ()  # the site hunt's record, one per award it hunted (2c)
```

In `apps/research/card_funding/hunt.py`, replace:

```python
import datetime as dt
from collections.abc import Sequence
from dataclasses import replace

from apps.research.candidates import Date

from .card import AwardCard, Field, _date_conflict, holds_of
from .parse import AwardDate, Value
```

with:

```python
import datetime as dt
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from apps.funding.models import Program
from apps.research.candidates import Date
from apps.research.card_engine import Limit
from apps.research.card_engine.engine import Transport
from apps.research.card_engine.readers import Stack
from apps.research.card_engine.screen import Screen, screen
from apps.research.fetch import CARRIES_BYTES, fetch_page
from apps.research.fetch.types import FetchedPage

from . import seek
from .awards import nameable
from .card import AwardCard, AwardHunt, Card, Field, Track, _date_conflict, holds_of
from .entry import PAGE_BUDGET_USD, read_page
from .parse import AwardDate, Value
from .seek import CAP, Lead, Vendors, find_leads, page_leads, proven
```

In `apps/research/card_funding/hunt.py`, replace:

```python
APPLY_ROLES = frozenset({"application_deadline", "application_period"})
```

with:

```python
APPLY_ROLES = frozenset({"application_deadline", "application_period"})
#: Each hunted page is a worker read, not one a student waits on: its own deadline, generous but
#: bounded, and the same $0.25 model stop as any page (§0.28).
HUNT_PAGE_S = 60.0
```

Append to `apps/research/card_funding/hunt.py`:

```python


def hunt_owed(card: Card, today: dt.date) -> bool:
    """Whether a card read on demand must be handed to the hunt: its worker step (decision 1)."""
    return card.outcome == "read" and not card.hunts and any(
        wanted(award, today) for track in card.tracks for award in track.awards)


def hunt_card(
    card: Card,
    program: Program,
    *,
    limit: Limit,
    funder_country: str | None = None,
    today: dt.date | None = None,
    readers: Stack | None = None,
    transport: Transport | None = None,
    fetch: Callable[..., FetchedPage] = fetch_page,
    screen_page: Callable[..., Screen] = screen,
    vendors: Vendors | None = None,
    prove: Callable[[str], bool | None] = proven,
    page_deadline_s: float = HUNT_PAGE_S,
    budget_usd: float = PAGE_BUDGET_USD,
    clock: Callable[[], float] = time.monotonic,
) -> Card:
    """The card with each award's missing facts looked for on the rest of the official site.

    Worker-side only, like `read_page`: every page goes through `fetch_page`. Per award: its
    wanted fields (`wanted`), the funnel's proven leads (`seek.find_leads`), at most `CAP` of
    them read by `read_page` restricted to that award and those fields, each page's own proven
    links queued behind them, then `merge`. A page is fetched once per hunt whichever awards
    read it. A card that was not read, or wants nothing, is returned as it was."""
    today = today or dt.date.today()
    if card.outcome != "read" or not any(wanted(a, today) for t in card.tracks
                                         for a in t.awards):
        return card
    pages: dict[str, FetchedPage] = {}

    def fetch_once(url: str, **kwargs: Any) -> FetchedPage:
        if url not in pages:
            pages[url] = fetch(url, **kwargs)
        return pages[url]

    start = fetch_once(card.source_url, purpose="read", require_origin=card.source_url)
    if start.outcome not in CARRIES_BYTES:
        return card
    stages = vendors or seek.vendors()
    started = clock()
    calls, cost, unpriced, running = list(card.calls), card.cost_usd, card.unpriced_calls, 0
    tracks, hunts = [], []
    for track in card.tracks:
        awards = []
        for award in track.awards:
            fields = wanted(award, today)
            if not fields:
                awards.append(award)
                continue
            spend: dict[str, float] = {}
            unproven: set[str] = set()
            queue: list[Lead] = (find_leads(start, award.name, fields, lang=card.lang,
                                            vendors=stages, spend=spend, unproven=unproven,
                                            prove=prove)
                                 if nameable(award.name) else [])
            tried = {start.final_url}
            read: list[str] = []
            attached: list[str] = []
            found: list[AwardCard] = []
            while queue and len(read) < CAP:
                lead = queue.pop(0)
                if lead.url in tried:
                    continue
                tried.add(lead.url)
                read.append(lead.url)
                page = read_page(program, lead.url, limit=limit, funder_country=funder_country,
                                 today=today, readers=readers, transport=transport,
                                 fetch=fetch_once, screen_page=screen_page,
                                 deadline_s=page_deadline_s, budget_usd=budget_usd,
                                 clock=clock, attach_to=award.name, fields=fields)
                calls += page.calls
                cost += page.cost_usd
                unpriced += page.unpriced_calls
                running += page.running_calls
                named = [a for t in page.tracks for a in t.awards]
                if named:
                    attached.append(lead.url)
                    found += named
                fetched = pages.get(lead.url)
                if fetched is not None and fetched.outcome in CARRIES_BYTES:
                    queue += page_leads(fetched, fields, prove=prove, unproven=unproven)
            awards.append(merge(award, fields, found, today))
            hunts.append(AwardHunt(award.name, tuple(sorted(fields)), tuple(read),
                                   tuple(attached), tuple(sorted(spend.items())),
                                   tuple(sorted(unproven))))
        tracks.append(Track(track.name, tuple(awards)))
    return replace(card, tracks=tuple(tracks), calls=tuple(calls), cost_usd=cost,
                   unpriced_calls=unpriced, running_calls=card.running_calls + running,
                   seconds=card.seconds + clock() - started, hunts=tuple(hunts))
```

- [ ] **Step 4: Run the tests, the package and the gates**

Run: `POSTGRES_DB=elmify_card_hunt uv run pytest -q tests/research/card_funding/test_hunt_card.py tests/research/card_funding && uv run ruff check . && uv run mypy apps config`
Expected: all pass; ruff and mypy clean.

- [ ] **Step 5: Commit** (pathspec only: worktrees share checkouts)

```bash
git -C "$WT" add tests/research/card_funding/test_hunt_card.py
git -C "$WT" commit -m "feat(card-funding): hunt a card's missing facts as a worker step" -- apps/research/card_funding/card.py apps/research/card_funding/hunt.py tests/research/card_funding/test_hunt_card.py
```

---

## Carried to slice 3 (binding on whoever wires this)

- **Queue the hunt behind an on-demand read**: when `hunt_owed(card, today)` is true, queue
  `hunt_card` to the worker (it fetches; `runtime_web` cannot) and store its card, replacing the
  read's. Never call `hunt_card` from a request.
- **The cap is per cycle**: count `AwardHunt.pages` per award and cycle across runs, and pass the
  remainder; `hunt_card` caps one run at `seek.CAP`.
- **A held field may carry values** (2b already did for `dates`; Task 2 adds the nationality
  fallback). The serve rule reads `state`, never the presence of values.
- **`Field.label == "last_cycle"`**, on any field (decision 13), is shown as "Last cycle: … — new
  date not announced yet" with the value's own source, and is never held for being past.
- **Domains without a verdict** (owner, 2026-10-14): the background sweep runs the provenance
  check on every `AwardHunt.unproven` domain, then hunts the award again.
- **A target level still not stated after the hunt** is hidden and a staff-review item is filed
  (owner's level rule via elmify-8c); a nationality with no candidate anywhere stays not
  stated (§5 step 7).
- **`hunt_not_found`** is a hold-queue reason with the pointer it followed as its detail
  (`eligibility_elsewhere`, `internationals`).
- The sweep passes `readers.run_limit` and the lead's funder country, as for `read_page`.

## Self-review

- **Spec coverage.** Trigger (no candidate, pointed elsewhere, split unresolved): Task 3. Funnel,
  URLs only, cheapest first, navigator on a miss: Task 5. Part B per page, another official domain:
  Tasks 5 and 7. Same engine, own quote and source: Task 4. Strict attach by code: Tasks 3 and 4.
  Cap of 6: Tasks 5 and 7. Newest cycle wins, dated beats undated, two hold cases: Task 6. Last
  cycle labelled: Tasks 2 and 6. Hold queue reasons: Tasks 2 and 6. 30 s versus the sweep:
  decision 1, Task 7. Peer form/PDF rule: Tasks 3 and 5. Cost and time guards: decisions 6, 8, 14.
- **Placeholders.** None: every step carries its code, every command its expected result.
- **Names across tasks.** `wanted`, `names_award`, `nameable`, `fold`, `stated_cycle`,
  `holds_of`, `merge`, `find_leads`, `page_leads`, `usable`, `proven`, `Vendors`, `Lead`, `CAP`,
  `AwardHunt`, `hunt_owed`, `hunt_card` are each defined once and used with the same signature
  (checked mechanically: the plan's own operations, applied in order, pass every gate).
- **Ambiguities resolved.** Tie-breaking by `Last-Modified` or crawl date (decision 12); where
  the hunt runs (decision 1); which empty fields are hunted (decision 2); what a failed hunt leaves
  (decision 3); whether 2c may run a provenance check (decision 4); which stages may leave the site
  (decision 5); the last-cycle label on every field (decision 13, owner).

## Owner answers (2026-10-14), folded in

1. Domains without a verdict: the slice-3 sweep checks them, then hunts again (decision 4, the
   slice-3 carries above). 2c is unchanged.
2. "Last cycle" labels amounts, benefits and eligibility rules too, not only dates (decision 13,
   Tasks 2 and 6).
3. A target level not stated after the hunt is hidden with a staff-review item in slice 3; a
   nationality with no candidate anywhere stays not stated (decision 3).
