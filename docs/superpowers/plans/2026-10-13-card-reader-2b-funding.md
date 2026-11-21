# Card Reader, Slice 2b: The Funding Question Set Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the funding question set on the merged card engine: group a page's lines into
awards, ask §5.2's catalogue under definitions v3 per award, parse every decision into a typed
value by code, read country groups through a code-owned fallback, assemble a typed, track-shaped
card in which every field is shown, held with a reason, or not stated, and read one programme
page on demand inside 30 s and $0.25.

**Architecture:** A new package `apps/research/card_funding/` beside `card_engine/`. `groups.py`
and `years.py` are the two code-owned tables of §5.2.1 (data in `docs/research/`, rules in code).
`awards.py` turns `readable_text` output into lines and asks the engine one judgement per
heading ("is this the name of an award?"); code does the grouping. `questions.py` is the
`QuestionSet`, in batches that fit the reader's output cap. `parse.py` turns decisions plus slice
1's candidates into typed values; `card.py` makes fields, holds and tracks; `entry.py` fetches,
screens and reads one page through a `Guard` transport that holds the deadline and the dollar
stop. Edits outside the package: `candidates/who.py` learns the group phrases the fallback reads
(Task 1); Task 7 adds three seams to shared code, each defaulting to today's behaviour so no
existing caller changes — `documents/letter_terms.py` learns Azerbaijani and Kazakh stopwords, and
`fetch_page` (with its two vendors) and D8 (`screen`, `decisions.ask`) take a `timeout_s`. No
model is called in any test; no storage, no migration.

**Tech Stack:** Python 3 (repo pin), Django settings and cache, the card engine
(`apps/research/card_engine/`), slice 1's finders (`apps/research/candidates/`), Babel (already a
dependency), `concurrent.futures`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-verified-catalog-one-reader-design.md` on branch
`claude/slice2-spec-amend` @ 0de03cde — §3.2 (EMJM tracks), §3.3 (typed programmes, the
single-page read), §5 (opening block and steps 0–7), §5.1, §5.2, §5.2.1, §5.5 (serve rule, hold
queue, the cycle rule of step 4; the hunt itself is 2c); owner decisions
`docs/superpowers/research/2026-10-12-slice2-owner-decisions.md`, and the country-group research
`2026-10-12-country-group-standard-lists.md` and `2026-10-12-country-group-policy.md` (same
branch). Carried items: PR #203's body and ledger comment.

## Plan 3 slice 2 as a whole (this is 2b of 2a–2c)

Plan 3 is the funding reader (verified-catalog §5, §11). Slice 1 (code finders,
`2026-10-05-card-reader-1-finders.md`) and slice 2a (the engine core,
`2026-10-12-card-reader-2a-engine-core.md`, PR #203, cecdb69f) are merged. Slice 2 is "the
engine, the funding question set, the site hunt (§5.5 step 4), the typed card, the single-page
entry and track-shaped output" (§5), in three plans, each its own PR:

- **2a — the engine core (merged).** The question-set interface, the reader stack as one
  setting, the two transports, the byte-exact quote check, D8, agreement and the decider, the
  per-decision record of who said what, one retry, the rate limit, cost and latency per call.
- **2b — the funding question set (this plan).** Lines and award grouping (§5 steps 1 and 3);
  the §5.2 catalogue under definitions v3 as batched `Question`s with one proposal (step 4);
  code parsing of every decision into typed values; the year-of-study table and the
  country-group fallback (§5.2.1); the typed card with its hold reasons and track shape (step 6,
  §3.2); the single-page entry for one `Program` and one URL (§3.3) with the 30 s deadline, the
  $0.25 stop, the language from code and the key check — and with it `tenant_limit`'s first
  caller.
- **2c — the site hunt (§5.5 step 4).** Its input is this plan's card: every field held
  `needs_hunt`, every `unresolved_split`, and every field `not_stated` because code found no
  candidate. The `sitejob` funnel (DOCUMENTS → MAP/GUIDED_MAP → NAVIGATOR), URLs only; Part-B
  proof of every hunted page, another official domain allowed; strict attach by code; the
  cycle rule across pages; 6 extra pages per award per cycle; what is left goes to the hold
  queue. The funder's own country list on another page is found there; 2b reads it only when it
  is on the page.

After slice 2: slice 3 (storage of cards and the hold queue, the serve rule wired into
`pipeline._fund_page`, deleting `funding_judge.py`'s vote, Batch API submission for the sweep
through `batch_reading.py` — and its wrapper transport must call `require_keys`, as `entry.py`
does here); slice 4 (the cycle verifier); then owner round 2 (§5.5).

## Global Constraints

- Lint only, never `ruff format`: `uv run ruff check .` (CLAUDE.md).
- Types: `uv run mypy apps config`.
- Tests: `POSTGRES_DB=elmify_card_funding uv run pytest -q` (per-branch DB name, CLAUDE.md).
- Never hand-edit `uv.lock`; this plan adds no dependency. No migration.
- Do not touch `apps/research/funding_judge.py` or `pipeline._fund_page`: slice 3 rewires or
  deletes them. Importing a public helper of another module is fine; importing from
  `funding_judge` is not (its vote is deleted in slice 3).
- "Code finds the candidates, and a model may only point … Code parses every value." (§5)
- "No reader is asked to calculate, compare dates, count, or write text." (§5)
- "A value is shown, verified, or the award is hidden. There is no 'not stated' for a value the
  engine was unsure about … A field is left off the card only when code finds no candidate at
  all for it." (§5 step 7)
- "Question text stays English on every page." (§5.1) Question sets refer to page text by key
  and never embed it in `Question.text` or `criteria` (2a carry, `QuestionSet` docstring).
- `Section.lang` comes from code (a detector or a validated code), never from page HTML (2a
  carry).
- "A page a student waits on … runs synchronously at standard price and must finish in under
  30 s"; "at most $0.25 of model spend per page" (§5, §0.28). The engine has no deadline; the
  2b caller enforces it (2a carry), over the whole read: fetch, D8 and readers (owner, 2026-10-13).
- A seam in shared code takes a keyword whose default is today's behaviour; existing callers and
  their tests are unchanged.
- Any wrapper transport must call `require_keys` (2a carry).
- "The funder's own list always comes first … Only a page that names a group and gives no list
  falls back to this table. Each list is bound to the page's date." (§5.2.1)
- "Every value records which reader answered what" (§5.5): each `Value` keeps its `Decision`s.
- Worker-side only: `fetch_page` writes `FetchAttempt`/`HostProfile`, which `runtime_web` cannot
  touch; a student-facing view queues the read (CLAUDE.md, catalogue boundary).
- Never log a prompt, a reply or page text; log reader, question id, key and reason only.
- Not in 2b: the hunt (2c); storage, models, migrations, the hold queue's table, the serve rule
  in `pipeline._fund_page`, `funding_judge`'s vote, the Batch API (slice 3); the application
  routes and file-rule question sets (other plans).

## Decisions this plan takes where the spec is silent

1. **Grouping asks one judgement per heading and nothing per line.** §5 step 3 asks a Choice per
   funding line too; that is replaced by the step's own fallback rule, done by code: a line
   belongs to the nearest award heading above it, and an award runs until the next heading at its
   own level or above. Lines above the first award are not read and are counted
   (`Card.unread_lines`). A heading whose judgement comes back unresolved is not an award name.
   The brief's "code groups lines into awards using headings and structure, and the engine is
   asked only what needs judgement".
2. **The optional cheap line filter (§5 step 2) is not built.** Whole award sections are read;
   nothing is filtered, so nothing can be filtered away.
3. **One proposal, for requirements only.** The proposer's measured lift was requirements 7/50 →
   28/50; amounts 21 → 22, dates 35 → 36 (§5). Each kept proposed quote gets one closed
   question, `kind_N`, over the requirement kinds of definitions v3 (prior degree, excluded
   degree, test or certificate, residence limit, stateless, compatriot …). A proposed quote that
   only repeats a code requirement on its line is not asked again.
4. **Batches of 20 questions.** The reader's reply is capped at 4,000 tokens, "about 25 answers
   with full quotes" (`readers.MAX_OUTPUT_TOKENS`), and an award asks 60–100 questions. Batch 0
   is the proposal plus its kinds; batches 1.. are code's questions, which do not depend on the
   proposals, so every batch of every award runs in parallel (8 workers). That is what keeps a
   page inside 30 s: about 2.4 s per cheap call (§5) plus the decider on a split.
5. **`target_level` gains the option `year_of_study`.** Whether the page names its students by
   year of study is the readers' judgement; which level that year is, is the table's, by code.
   **Owner decision, 2026-10-13: the FUNDER's country decides.** Wording that names no country
   ("1st–3rd year students") is looked up in the row for the funder's country and the wording's
   language; a funder whose country is unknown (`""`), or whose country has no row for that
   language, holds the field (`unparseable_value`, detail `target_level`) — never guessed, and
   no country is a default. The funder's country is `read_page`'s `funder_country`; left `None`
   it is the programme's own (`Program.country_code`), because the single-page read is of the
   programme's own page (§3.3 step 3 proves it is on the institution's domain); slice 3's sweep
   passes the lead's funder country, `""` when it has none. Rows, each a source read on
   2026-10-13: (AZ, az) and (AZ, en), years 1–4, Erasmus+ networks, "Bachelor's programmes in
   Azerbaijan typically last for four years."; (DE, en), years 1–3, Hochschulrahmengesetz §19(2),
   "Die Regelstudienzeit beträgt mindestens drei und höchstens vier Jahre." — so a German fourth
   year, which may be a master's first, is held; (RU, ru), years 1–4, Alberta IQAS, "General
   bachelor's degrees involve 4 years of full-time study." **Sources (owner, 2026-10-13):** AZ
   and RU keep the sources above; for any row added or re-sourced, prefer the country's own
   ministry or education law where one is readily found (as DE's row does), and the row's
   `source_url` names whichever was used. `test_every_row_is_a_country_a_level_and_a_cited_source`
   covers every row.
6. **Funding duration is a yes/no per duration candidate** (`funds_uN`), not §5.2's Choice gated
   by a `has_duration` question: one property per question, and no dependent second round.
7. **`route_order` is asked always and read only when `route` is not
   `considered_with_admission`** — §5.2's condition, applied by code, so no second round.
8. **"The funder's own list first", on one page:** when an award names at least one eligible
   *country*, a group phrase in it is funder prose beside that list and is not expanded (recorded
   as `GROUP:beside_list`). A *region* (EU, ASEAN …) is a list of its own and is unioned with a
   group's expansion. So "citizens of the EU or of developing countries" holds an Azerbaijani
   applicant (developing → DAC → held), and "developing countries, namely Azerbaijan and Kenya"
   is exactly AZ and KE.
9. **"Low- and middle-income" as the whole criterion is a judgement:** `sole_pN` ("is this the
   whole condition on who may apply, with nothing added to it?") is asked for an LMY phrase, and
   code expands to World Bank LMY only on yes; otherwise everyone is held, like a bare "LMIC".
10. **The page's date** binds the dated rows (Moldova in the CIS until 2027-04-08, Nauru on the
    DAC list until 2027-01-01): the newest date the readers marked `page_published_or_updated`,
    else the read date. A row past its `until` is **held**, never dropped: the operator re-checks
    it (the policy note's "MD: … review after").
11. **A group phrase with no fallback row** ("partner countries", "programme countries", "third
    countries", "non-EU", OIC, Turkic states) is `unparseable_value`: held, and the operator's
    fix is a data row. "International" or "foreign" students is `needs_hunt` (definitions v3: not
    a condition; 2c hunts the funder's list, and only then "all countries except the host").
12. **Hold reasons, enumerated** (`card.HOLD_REASONS`): `unresolved_split`, `held_country_group`,
    `conflicting_values`, `unparseable_value` (the brief's four), `needs_hunt` (2c's input), and
    three from the read itself: `not_read` (the section was never read: rate limit, too large),
    `deadline`, `page_budget`. A country group held for *some* countries (CIS → UA; developing →
    DAC members) keeps the field shown and adds a `Hold` naming those countries, so only a
    student from one of them is held; a group held for everyone holds the field.
13. **Conflicts on one page** are checked for the single-valued date roles only
    (`application_deadline`, `application_opening`, `fee_deadline`) and never for a date stated
    for named places. The newest stated cycle wins (the cycle is an intake candidate on the
    date's own line, parsed by code); two different dates of one cycle, or of no cycle, are
    `conflicting_values` (§5.5 step 4's rule, applied within a page).
14. **The deadline and the dollar stop live in a transport, `Guard`.** It refuses to start a call
    with under 2 s left or once $0.25 is spent, and cuts each HTTP wait to the time left; a
    refused call is a failed attempt, so the question ends unresolved and the award is held
    `deadline` or `page_budget` — never a guess. A call the vendor did not price is counted
    (`Card.unpriced_calls`), never $0.
    **The fetch and D8 are inside the same 30 s (owner decision, 2026-10-13).** The clock starts
    before the fetch; `read_page` hands each of them the time left as `timeout_s`, and checks the
    clock when each returns: under `MIN_CALL_S` left, the read stops with outcome `deadline` —
    the page (when there is one) as one award held `deadline`, no reader asked; a fetch that
    ran out with no page is outcome `deadline` with no tracks. Neither took a timeout before
    this plan, so each gets the smallest seam, a keyword defaulting to today's behaviour:
    - `fetch_page(..., timeout_s=None)`: no rung starts once the time is spent (the ladder stops
      `UNREACHABLE`, reason `deadline`, recorded as a `FetchAttempt` and never taught to the
      `HostProfile`); each vendor call gets the time left (`firecrawl.scrape` and
      `scrapedo.scrape` cap the vendor's own page timeout and the HTTP read at it, and Firecrawl
      does not back off and retry under it); and the archive rung, two calls of its own, is not
      tried under a deadline. Rung 5's retry schedule is unchanged: it is a row, not a wait.
    - `screen(..., timeout_s=None)` and `decisions.ask(..., timeout_s=None)`: each D8 call gets
      the time left, a chunk with none left is not asked (`unscreened`, reason `deadline`), and
      Jev's client passes it to the SDK as the request timeout and the retry budget. The adapter
      route (`SystemOneAdapterClient`) has no timeout to pass, and an injected client carries its
      own, so on those routes only `read_page`'s clock check bounds D8 — D8 is Jev unless
      `DECISIONS_PROVIDER` says otherwise.
15. **The language is `documents.letter_terms.detect_language(text)`** with no `html_lang`:
    code only. It knows en de es fr it nl pt ru tr by stopwords and ko ja zh by script.
    **Owner decision, 2026-10-13: Azerbaijani and Kazakh are detected now.** Task 7 adds
    stopword rows `az` and `kk` and scores every stopword row, not only the letter-term rows, so
    `az`/`kk` can come back although `TERMS` has no row for them (the letter path, `derive.py`,
    reads `TERMS.get(language)` and so treats them as it treats `""`). The words are taken from
    NLTK's stopword corpus (Azerbaijani list, nltk_data PR #100; Kazakh list, PR #52;
    https://github.com/nltk/nltk_data/blob/gh-pages/packages/corpora/stopwords.zip, read
    2026-10-13 — stopwords-iso has neither language), choosing words that share none with the
    `tr` and `ru` rows: Azerbaijani writes "və", "üçün", "ilə" where Turkish writes "ve",
    "için", "ile", and Kazakh "үшін", "бұл", "арқылы" are not Russian. Tests pin both
    directions: a short Azerbaijani and Kazakh paragraph are detected, a Turkish and a Russian
    paragraph are not. An unknown language still comes back `""`, and the year-of-study lookup
    then tries every row of the funder's country.
16. **The entry fetches with `require_origin=url`** and runs no Part-B proof itself: in the
    typed-programme flow `provenance_job.check_named_url` runs before it (§3.3 step 3), and the
    serve rule's proof check is slice 3's. `readable_text(..., terms=funding_terms())` keeps its
    default `select_only_over_cap=True`, so a page that fits is read whole (fails open, §5.4).
17. **Track shape:** `Card.tracks`, each `Track(name, awards)`. A single page read here is one
    track `""`; the EMJM programme reader (§3.2) fills several.
18. **The DAC list's source is the OECD PDF "for reporting 2025 flows"** (141 recipients), the
    current one: the 2026 review was postponed to 2027 (research §3).
19. **The award's name is its heading** (or the page title for a page with no award heading),
    copied by code with its quote; §5.2's `name` Choice is not asked, because the heading
    judgement of decision 1 already decided it.
20. **`scope` is not derived here.** §5 step 6 derives it from `apply_here`, `apply_elsewhere`,
    `institution_wide` and the page's kind (a university's, a programme's or a funder's own
    page); the page's kind is the lead's, which slice 3's caller holds. The three flags are on
    the card, so slice 3 derives scope without a re-read.

## Review Focus

Every code block below was run before it was written here. First written (2026-10-13) in a
scratch worktree off `origin/master` 0e05f495; then, after the owner's answers of 2026-10-13
were folded in, **this file's own blocks were extracted mechanically and applied task by task to
a fresh detached worktree off this branch's head (95786736)** — every file a task writes, every
exact old → new replacement in shared code (each old text must occur exactly once), every
appended test — and each task's tests were run at that task's own state. Results:
- each task's tests fail first (Tasks 1–6 with `ModuleNotFoundError`; Task 7 with
  `ImportError: cannot import name 'entry'`, and 8 failing seam tests — the `az` and `kk`
  detector cases and one `timeout_s` test per seam, while the `tr` and `ru` cases already pass),
  then pass at that task's state: Task 1 17 (with slice 1's 175 finder tests still passing
  after the `who.py` edit), Task 2 4, Task 3 5, Task 4 5, Task 5 12, Task 6 5, Task 7 9 — 57 in
  `tests/research/card_funding`; with the six seam modules, Task 7's command runs 288;
- `uv run ruff check .` clean; `uv run mypy apps config` clean (721 files); `manage.py check`
  clean; `makemigrations --check --dry-run`: no changes;
- full suite at Task 7's state: 8,544 passed, 64 skipped, 429 deselected (the default `live`
  deselection), and 2 failed, both in `tests/documents/test_ocr_prepare.py` with
  `FileNotFoundError: .../ocr/.venv/bin/python` — its OCR sub-environment is not built in a fresh
  worktree, and it fails the same way on untouched master.

The data in Task 1 was checked against its sources before it was written, and the check ships as
a test (`test_groups.py`): every code is a Babel territory code and not a grouping code; the DAC
row carries the PDF's 141 recipients (names mapped to codes by Babel plus explicit
overrides, printed and read side by side); the LDC row is the 44 flags of the M49 LDC column,
equal to the DAC PDF's own LDC column; the SSA rows are the 53 rows of M49 region 202 with
Djibouti held, plus Sudan held (M49 puts it in Northern Africa); the LMY row is the 131
economies the World Bank API classifies L, LM or UM (25 + 47 + 59, matching the research note).

The likeliest remaining risks, each pinned by a test in its owning task:

1. **A page whose award headings all fail** (or whose judgements come back unresolved) is read as
   one award, so two awards' amounts land on one card. The readers' judgement is the only guard;
   round 2 measures it. Owner: `test_no_award_heading_makes_the_page_one_award` (Task 3).
2. **Hostile text in a heading or a table header** must still sit inside what D8 screened, or the
   engine refuses the section. Owner: `test_an_award_runs_to_the_next_heading_at_its_own_level`
   asserts every award section's texts are inside the page's (Task 3).
3. **A quote that sits in one award but is scripted for another** is not on that award's page
   section, so the engine drops it and the field is held or not stated — never borrowed from a
   neighbour. Owner: `test_a_page_becomes_a_track_of_typed_award_cards` (Task 7: "Tuition
   waiver of 50%" is printed only under Merit, and Rector's `tuition_level` stays not stated).
4. **The rate limit or the dollar stop mid-page** holds the awards it could not pay for and keeps
   every call already made. Owners: `test_an_award_the_rate_limit_refused_is_held_not_read`,
   `test_the_dollar_stop_holds_what_it_could_not_pay_for` (Task 7).
5. **Two deadlines on one page** for one award. Owners:
   `test_two_deadlines_of_one_cycle_or_of_no_cycle_conflict`,
   `test_the_newest_stated_cycle_wins_and_place_dates_never_conflict` (Task 6).
6. **A slow fetch or a slow D8 eats the 30 s** (owner, 2026-10-13). Owners:
   `test_a_slow_fetch_or_a_slow_screen_ends_the_read_at_the_deadline` and
   `test_past_the_deadline_no_call_starts_and_every_award_is_held` (Task 7), and one test per
   seam that the time left reaches the vendor or Jev and that a spent deadline starts nothing
   (`test_a_deadline_hands_each_rung_the_time_left_and_ends_the_ladder_at_it`,
   `test_a_deadline_never_waits_for_the_archive`,
   `test_a_deadline_caps_the_vendor_clock_and_the_http_wait_and_never_backs_off`,
   `test_a_deadline_caps_scrape_dos_clock_and_the_http_wait`,
   `test_a_timeout_bounds_one_jev_call_retries_included`,
   `test_a_timeout_reaches_every_d8_call_and_an_expired_one_asks_nothing`).
7. **Azerbaijani read as Turkish, or Kazakh as Russian**, which would send a page through the
   wrong year-of-study row. Owner:
   `test_azerbaijani_and_kazakh_are_told_apart_from_turkish_and_russian` (Task 7), both ways.
8. **A year of study mapped through the wrong country.** The funder's country decides, and an
   unknown one is held. Owners: `test_the_funders_country_decides_what_a_year_of_study_means`
   (Task 2), `test_year_of_study_names_a_level_through_the_funders_country` (Task 5),
   `test_the_funders_country_decides_a_year_of_study_and_none_is_the_programmes` (Task 7).

Known and accepted: a call already in flight at the deadline runs to its own cut-down timeout in
a background thread (`pool.shutdown(wait=False)`); its cost is not in `Card.cost_usd`. Bounded by
the guard to the time left, so it is seconds, not minutes. D8 on the adapter route, or through an
injected client, has no timeout to take (decision 14); there only `read_page`'s clock check after
the screen bounds it. urllib3's `total` caps connect plus each read, not a body that trickles in
for longer; such a fetch returns late and the read then ends `deadline`.

---

## File Structure

| file | responsibility |
|---|---|
| `docs/research/country-groups.csv` | the fallback lists: group, status, until, codes, source, as_of |
| `docs/research/year-of-study-levels.csv` | country, locale, pattern, years, level, source_url (country = the funder's) |
| `apps/research/candidates/who.py` | `_GROUPS` learns the group phrases the fallback reads |
| `apps/research/card_funding/__init__.py` | the package docstring |
| `apps/research/card_funding/groups.py` | phrase → group; `expand`, the owner's rules over the lists |
| `apps/research/card_funding/years.py` | `level_of_year` over the year-of-study table |
| `apps/research/card_funding/awards.py` | `page_lines`, `AwardNames`, `heading_sections`, `group`, `award_section` |
| `apps/research/card_funding/questions.py` | the `Funding` question set, `code_questions`, `kind_questions`, `batches` |
| `apps/research/card_funding/parse.py` | `parse_award`: decisions + candidates → `Parsed` fields of typed `Value`s |
| `apps/research/card_funding/card.py` | `Field`, `Hold`, `AwardCard`, `Track`, `Card`; `award_card`, `unread_award` |
| `apps/research/card_funding/entry.py` | `Guard`; `read_page(program, url, *, limit, funder_country, …) -> Card` |
| `tests/research/card_funding/` | one test module per source module, plus `oracle.py`, a scripted reader stack |
| `apps/documents/letter_terms.py` | `detect_language` learns `az` and `kk` stopwords (Task 7) |
| `apps/research/fetch/__init__.py`, `fetch/firecrawl.py`, `fetch/scrapedo.py` | `timeout_s`, default `None` = today (Task 7) |
| `apps/research/decisions.py`, `card_engine/screen.py` | `timeout_s` for D8, default `None` = today (Task 7) |
| `tests/documents/test_letter_terms.py`, `tests/research/test_fetch_{ladder,firecrawl,scrapedo}.py`, `tests/research/test_decisions.py`, `tests/research/card_engine/test_screen.py` | one appended test per seam (Task 7) |

---

### Task 1: Country groups — the fallback lists, the phrases, and `expand`

**Files:**
- Create: `docs/research/country-groups.csv`
- Create: `apps/research/card_funding/__init__.py`
- Create: `apps/research/card_funding/groups.py`
- Modify: `apps/research/candidates/who.py` (`_GROUPS`)
- Create: `tests/research/card_funding/__init__.py` (empty)
- Test: `tests/research/card_funding/test_groups.py`

**Why these shapes:** §5.2.1's table is a rule per phrase over a handful of published lists. The
lists are data with a source each (one row per group and status, codes space-separated, an
`until` for the two dated memberships); the rules are code, copied from the owner's table, so a
rule change is a reviewed diff and a list refresh is a data row. The slice-1 place finder already
marks group phrases `unknown_group`; it learns the phrases it did not know ("Global South",
"emerging economies", "low- and middle-income countries", "sub-Saharan Africa", the Russian,
Azerbaijani, Turkish and German forms), so each becomes a keyed candidate the readers can be
asked about.

**Interfaces:**
- Consumes: `apps.funding.regions.REGIONS`; `apps.research.candidates.who.find_places`.
- Produces: `GROUPS_FILE`; `PHRASES`; `EVERYONE_HELD`; `Row(group, status, until, codes, source,
  as_of)`; `Expansion(group, eligible, held, everyone_held=False, sources=())`;
  `rows() -> tuple[Row, ...]`; `group_of(text) -> str | None`;
  `expand(group, *, on: date, page_says_dac=False, sole_criterion=False) -> Expansion | None`.

- [ ] **Step 1: Write the failing tests**

`tests/research/card_funding/test_groups.py`:

```python
from datetime import date

import pytest
from babel import Locale

from apps.research.candidates.who import find_places
from apps.research.card_funding.groups import expand, group_of, rows

#: Babel's territory codes include these non-countries; a list row may not use one.
_NOT_COUNTRIES = {"EU", "EZ", "UN", "QO", "ZZ"}
ON = date(2026, 10, 13)

# Counts and memberships as each source states them, checked by hand on 2026-10-12/13 (plan 2b,
# Task 1): the DAC PDF lists 141 recipients; M49 flags 44 LDCs and puts 53 rows in region 202,
# Sudan in Northern Africa (015); the World Bank API classifies 25 L + 47 LM + 59 UM economies.
COUNTS = {"DAC": 141, "LDC": 44, "SSA": 54, "LMY": 131, "CIS": 10}


def test_every_code_is_a_country_and_every_row_cites_its_source():
    territories = {code for code in Locale("en").territories if len(code) == 2}
    for row in rows():
        assert row.codes and row.codes <= territories - _NOT_COUNTRIES, row.group
        assert row.source.startswith("https://") and row.as_of, row.group
        assert row.status in {"eligible", "held"}, row.group


def test_each_group_has_the_count_its_source_states():
    for group, count in COUNTS.items():
        assert len(set().union(*(r.codes for r in rows() if r.group == group))) == count, group


def test_memberships_the_research_checked_on_the_sources():
    dac = expand("DAC", on=ON)
    assert {"AZ", "AM", "BY", "GE", "KZ", "KG", "MD", "TJ", "TM", "TR", "UA", "UZ"} <= dac.eligible
    assert "RU" not in dac.eligible
    ssa = expand("SSA", on=ON)
    assert ssa.held == {"SD", "DJ"} and "SD" not in ssa.eligible and "KE" in ssa.eligible
    assert {"KI", "SB", "TV", "HT"} <= expand("LDC", on=ON).eligible
    assert expand("LDC", on=ON).eligible <= dac.eligible  # the DAC PDF's own LDC column


def test_cis_follows_the_owners_table():
    cis = expand("CIS", on=ON)
    assert cis.eligible == {"AZ", "AM", "BY", "KZ", "KG", "TJ", "TM", "UZ", "MD"}
    assert cis.held == {"UA"} and "GE" not in cis.eligible | cis.held
    after = expand("CIS", on=date(2027, 4, 8))
    assert "MD" in after.held and "MD" not in after.eligible


def test_developing_is_held_on_the_dac_list_and_out_off_it():
    developing = expand("DEVELOPING", on=ON)
    assert developing.eligible == set() and "AZ" in developing.held and "RU" not in developing.held
    assert expand("DEVELOPING", on=ON, page_says_dac=True).eligible == expand("DAC", on=ON).eligible


def test_vague_groups_hold_everyone_and_lmy_needs_to_be_the_whole_criterion():
    for group in ("GLOBAL_SOUTH", "EMERGING", "NEWLY_INDUSTRIALISED", "LMIC"):
        assert expand(group, on=ON).everyone_held, group
    assert expand("LMY", on=ON).everyone_held
    assert "AZ" in expand("LMY", on=ON, sole_criterion=True).eligible
    assert expand("INTERNATIONAL", on=ON) is None
    assert expand("EU", on=ON).eligible >= {"DE", "FR"}


@pytest.mark.parametrize(("line", "group"), [
    ("Open to citizens of developing countries.", "DEVELOPING"),
    ("for applicants from development and newly industrialised countries", "DEVELOPING"),
    ("граждане государств-участников СНГ", "CIS"),
    ("students from the Global South", "GLOBAL_SOUTH"),
    ("nationals of low- and middle-income countries", "LMY"),
    ("Applicants from LMICs only", "LMIC"),
    ("citizens of sub-Saharan Africa", "SSA"),
    ("least developed countries (LDCs)", "LDC"),
    ("countries on the DAC list", "DAC"),
    ("emerging economies", "EMERGING"),
    ("open to international students", "INTERNATIONAL"),
])
def test_each_phrase_is_a_place_candidate_naming_its_group(line, group):
    groups = [group_of(p.text) for p in find_places(line) if p.kind == "unknown_group"]
    assert groups == [group], (line, [p.text for p in find_places(line)])
```

Also create the empty `tests/research/card_funding/__init__.py`.

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_groups.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.card_funding'`

- [ ] **Step 3: Implement**

`docs/research/country-groups.csv` (the codes were read off each source on 2026-10-12/13; see
Review Focus):

```csv
group,status,until,codes,source,as_of
CIS,eligible,,AZ AM BY KZ KG TJ TM UZ,https://education-in-russia.com/news/provedenie-proktoringa-dlya-stran-sng-ukrainy-i-yuzhnoy-osetii,2026-04-01
CIS,eligible,2027-04-08,MD,https://education-in-russia.com/news/provedenie-proktoringa-dlya-stran-sng-ukrainy-i-yuzhnoy-osetii,2026-04-01
CIS,held,,UA,https://education-in-russia.com/news/provedenie-proktoringa-dlya-stran-sng-ukrainy-i-yuzhnoy-osetii,2026-04-01
DAC,eligible,,AF AL AM AO AR AZ BA BD BF BI BJ BO BR BT BW BY BZ CD CF CG CI CM CN CO CR CU CV DJ DM DO DZ EC EG ER ET FJ FM GA GD GE GH GM GN GQ GT GW GY HN HT ID IN IQ IR JM JO KE KG KH KI KM KP KZ LA LB LC LK LR LS LY MA MD ME MG MH MK ML MM MN MR MS MU MV MW MX MY MZ NA NE NG NI NP NU PA PE PG PH PK PS PW PY RS RW SB SD SH SL SN SO SR SS ST SV SY SZ TD TG TH TJ TK TL TM TN TO TR TV TZ UA UG UZ VC VE VN VU WF WS XK YE ZA ZM ZW,https://www.oecd.org/content/dam/oecd/en/topics/policy-sub-issues/oda-eligibility-and-conditions/DAC-List-of-ODA-Recipients-for-reporting-2025-flows.pdf,2025
DAC,eligible,2027-01-01,NR,https://www.oecd.org/content/dam/oecd/en/topics/policy-sub-issues/oda-eligibility-and-conditions/DAC-List-of-ODA-Recipients-for-reporting-2025-flows.pdf,2025
LDC,eligible,,AF AO BD BF BI BJ CD CF DJ ER ET GM GN GW HT KH KI KM LA LR LS MG ML MM MR MW MZ NE NP RW SB SD SL SN SO SS TD TG TL TV TZ UG YE ZM,https://unstats.un.org/unsd/methodology/m49/overview/,2026-10-12
SSA,eligible,,AO BF BI BJ BW CD CF CG CI CM CV ER ET GA GH GM GN GQ GW IO KE KM LR LS MG ML MR MU MW MZ NA NE NG RE RW SC SH SL SN SO SS ST SZ TD TF TG TZ UG YT ZA ZM ZW,https://unstats.un.org/unsd/methodology/m49/overview/,2026-10-12
SSA,held,,DJ SD,https://unstats.un.org/unsd/methodology/m49/overview/,2026-10-12
LMY,eligible,,AF AL AM AO AR AZ BA BD BF BI BJ BO BR BT BW BY BZ CD CF CG CI CM CN CO CU CV DJ DM DO DZ EC EG ER ET FJ FM GA GD GE GH GM GN GQ GT GW HN HT ID IN IQ IR JM JO KE KG KH KI KM KP KZ LA LB LC LK LR LS LY MA MD ME MG MH MK ML MM MN MR MU MV MW MX MY MZ NA NE NG NI NP PE PG PH PK PS PY RS RW SB SD SL SN SO SR SS ST SV SY SZ TD TG TH TJ TL TM TN TO TR TV TZ UA UG UZ VC VE VN VU WS XK YE ZA ZM ZW,https://api.worldbank.org/v2/country?format=json&per_page=400,2026-10-13
```

`apps/research/card_funding/__init__.py`:

```python
"""The funding question set on the card engine, and the single-page read (verified-catalog §5).

`groups` and `years` are the code-owned tables of §5.2.1; `awards` makes a page's lines and groups
them into awards; `questions` is the funding question set; `parse` turns decisions and slice-1
candidates into typed values; `card` assembles the typed, track-shaped card; `entry` reads one
programme page on demand inside 30 s and $0.25. Nothing here stores anything (slice 3).
"""
```

`apps/research/card_funding/groups.py`:

```python
"""Country-group phrases, read through the fallback table (verified-catalog §5.2.1).

The funder's own list always comes first: a page that names countries is read as those countries,
and this table is only for a page that names a group and lists nothing. Each list is data with its
source (`docs/research/country-groups.csv`, one row per group and status, codes space-separated);
the rules of what a phrase means are code, here, copied from the owner's table:

- CIS: AZ AM BY KZ KG TJ TM UZ, MD until 2027-04-08; UA held; GE and TR not eligible.
- "developing countries": off the DAC list not eligible, on it held -- unless the page itself says
  DAC or ODA, when the DAC list applies.
- "Global South", "emerging", "newly industrialised", a bare "LMIC": held for everyone.
- "low- and middle-income": World Bank LMY, only when it is the whole criterion; else held.
- LDC: the M49 LDC column. Sub-Saharan Africa: M49 region 202, Sudan and Djibouti held.

A row past its `until` date is held, never dropped: the operator re-checks it (Moldova's exit,
Nauru's graduation). "International" or "foreign" students is not a condition at all (§5.2.1): it
has no expansion, and the caller hunts the funder's list instead.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from apps.funding.regions import REGIONS

GROUPS_FILE = Path(__file__).resolve().parents[3] / "docs" / "research" / "country-groups.csv"

#: Matched against a place candidate's text (who.py finds these as `unknown_group`). First wins.
PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (group, re.compile(pattern, re.IGNORECASE)) for group, pattern in (
        ("DEVELOPING", r"develop\w* and (?:emerging|newly industriali[sz]ed)|developing countr|"
                       r"развивающ|inkişaf etməkdə olan|gelişmekte olan|Entwicklungsländer"),
        ("DAC", r"(?<!\w)(?-i:DAC|ODA)(?!\w)"),
        ("LDC", r"least developed|en az gelişmiş|наименее развит"),
        ("CIS", r"(?<!\w)(?-i:CIS)(?!\w)|Commonwealth of Independent States|(?-i:СНГ)|"
                r"Müstəqil Dövlətlər Birliyi|Bağımsız Devletler Topluluğu"),
        ("LMY", r"low-?\s*and[- ]middle[- ]income"),
        ("LMIC", r"(?<!\w)(?-i:LMICs?)(?!\w)"),
        ("GLOBAL_SOUTH", r"Global South|Глобальн\w* Юг"),
        ("EMERGING", r"emerging|Schwellenländer"),
        ("NEWLY_INDUSTRIALISED", r"newly industriali[sz]ed"),
        ("SSA", r"sub-Saharan|к югу от Сахары"),
        ("INTERNATIONAL", r"foreign|international|иностранн|xarici|əcnəbi|yabancı|uluslararası"),
    )
)
#: Groups with no list anywhere: whoever reads them is held, whatever their country.
EVERYONE_HELD = frozenset({"LMIC", "GLOBAL_SOUTH", "EMERGING", "NEWLY_INDUSTRIALISED"})


@dataclass(frozen=True)
class Row:
    group: str
    status: str  # "eligible" | "held"
    until: date | None
    codes: frozenset[str]
    source: str
    as_of: str


@dataclass(frozen=True)
class Expansion:
    """Who a group phrase lets apply. A country in neither set is not eligible."""

    group: str
    eligible: frozenset[str]
    held: frozenset[str]
    everyone_held: bool = False
    sources: tuple[str, ...] = ()


@cache
def rows() -> tuple[Row, ...]:
    with GROUPS_FILE.open(encoding="utf-8", newline="") as handle:
        return tuple(
            Row(r["group"], r["status"], date.fromisoformat(r["until"]) if r["until"] else None,
                frozenset(r["codes"].split()), r["source"], r["as_of"])
            for r in csv.DictReader(handle)
        )


def group_of(text: str) -> str | None:
    """The group a place candidate's text names, or None."""
    return next((group for group, pattern in PHRASES if pattern.search(text)), None)


def _listed(group: str, on: date) -> Expansion:
    eligible: set[str] = set()
    held: set[str] = set()
    sources: list[str] = []
    for row in rows():
        if row.group != group:
            continue
        expired = row.until is not None and on >= row.until
        (held if row.status == "held" or expired else eligible).update(row.codes)
        sources.append(row.source)
    return Expansion(group, frozenset(eligible), frozenset(held - eligible),
                     sources=tuple(dict.fromkeys(sources)))


def expand(group: str, *, on: date, page_says_dac: bool = False,
           sole_criterion: bool = False) -> Expansion | None:
    """The fallback for `group` (a PHRASES key or a REGIONS key) as read on `on`, the page's
    date. None for a group with no expansion ("INTERNATIONAL"), which is not a condition."""
    if group in REGIONS:
        region = REGIONS[group]
        return Expansion(group, frozenset(region.countries), frozenset(), sources=(region.source,))
    if group in EVERYONE_HELD or (group == "LMY" and not sole_criterion):
        return Expansion(group, frozenset(), frozenset(), everyone_held=True)
    if group == "DEVELOPING":
        dac = _listed("DAC", on)
        if page_says_dac:
            return Expansion(group, dac.eligible, dac.held, sources=dac.sources)
        return Expansion(group, frozenset(), dac.eligible | dac.held, sources=dac.sources)
    if group in {"CIS", "DAC", "LDC", "SSA", "LMY"}:
        return _listed(group, on)
    return None
```

In `apps/research/candidates/who.py`, replace the first line of the `_GROUPS` alternation:

```python
_GROUPS = re.compile(
    r"(?<!\w)(?:developing countries|partner countries|programme countries|program countries|"
```

with:

```python
_GROUPS = re.compile(
    r"(?<!\w)(?:develop\w* and (?:emerging|newly industriali[sz]ed) (?:countries|economies)|"
    r"Global South|Глобальн\w* Юг|emerging (?:economies|countries|markets)|Schwellenländer|"
    r"newly industriali[sz]ed (?:countries|economies)|"
    r"low-?\s*and[- ]middle[- ]income (?:countries|economies)|(?-i:LMICs?)|"
    r"sub-Saharan Africa|Африк\w* к югу от Сахары|ODA recipients|"
    r"Müstəqil Dövlətlər Birliyi|Bağımsız Devletler Topluluğu|наименее развит\w* стран|"
    r"развивающ\w* стран|inkişaf etməkdə olan ölkələr|gelişmekte olan ülkeler|"
    r"Entwicklungsländer|"
    r"developing countries|partner countries|programme countries|program countries|"
```

(the rest of the pattern is unchanged; the longer phrases come first so "developing and emerging
countries" is one candidate, not "emerging countries").

- [ ] **Step 4: Run the tests, and slice 1's finder tests, to verify they pass**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_groups.py tests/research/candidates -q`
Expected: 17 + 175 passed (the slice-1 finders are unchanged on every line they already read).

- [ ] **Step 5: Commit**

```bash
git add docs/research/country-groups.csv apps/research/card_funding/__init__.py \
  apps/research/card_funding/groups.py apps/research/candidates/who.py \
  tests/research/card_funding/__init__.py tests/research/card_funding/test_groups.py
git commit -m "feat(research): country-group fallback lists and phrases for the funding card"
```

---

### Task 2: The year-of-study table

**Files:**
- Create: `docs/research/year-of-study-levels.csv`
- Create: `apps/research/card_funding/years.py`
- Test: `tests/research/card_funding/test_years.py`

**Why:** §5.2.1: "Year-of-study wording maps to a level by code, through a per-country data
table … columns `country,locale,pattern,years,level,source_url` … a phrase in a country with no
row is `no_candidate`: counted, never guessed." The readers decide *that* a level is stated as a
year of study (Task 4's `year_of_study` option); this table decides *which* level, for the
FUNDER's country (owner, 2026-10-13, decision 5): `country` is the funder's, `locale` the
wording's language, and `years` the study years the row's pattern accepts — a German row stops at
3 because a German fourth year may be a master's first. Seed rows and their sources: decision 5.
**When adding or re-sourcing a row, prefer the country's own ministry or education law where one
is readily found** (DE's row cites the Hochschulrahmengesetz); `source_url` names whichever source
is used, and the first test below checks every row.

**Interfaces:**
- Produces: `YEARS_FILE`; `YearRow(country, locale, pattern, years, level, source_url)`;
  `year_rows() -> tuple[YearRow, ...]`;
  `level_of_year(text: str, funder_country: str, lang: str = "") -> str | None` (`""` funder
  country: None, so the caller holds the field).

- [ ] **Step 1: Write the failing tests**

`tests/research/card_funding/test_years.py`:

```python
import re

from babel import Locale

from apps.research.card_funding.years import level_of_year, year_rows


def test_every_row_is_a_country_a_level_and_a_cited_source():
    territories = set(Locale("en").territories)
    for row in year_rows():
        assert row.country in territories and len(row.country) == 2, row
        assert row.level in {"bachelor", "master", "phd"}, row
        assert re.fullmatch(r"[1-9]-[1-9]", row.years), row
        assert row.source_url.startswith("https://"), row


def test_the_funders_country_decides_what_a_year_of_study_means():
    english = "for 1st–3rd year students"  # names no country
    assert level_of_year(english, "AZ", "en") == "bachelor"  # an Azerbaijani funder
    assert level_of_year(english, "DE", "en") == "bachelor"  # a German funder
    assert level_of_year(english, "", "en") is None  # an unknown funder: held, no default
    assert level_of_year(english, "FR", "en") is None  # a funder with no row: held
    fourth = "open to 4th year students"
    assert level_of_year(fourth, "AZ", "en") == "bachelor"  # a four-year bachelor's
    assert level_of_year(fourth, "DE", "en") is None  # three to four years: maybe a master's


def test_the_owners_seed_examples_name_bachelor():
    assert level_of_year("Open to I, II və III kurs tələbələri", "AZ", "az") == "bachelor"
    assert level_of_year("студенты 3–4 курс бакалавриата", "RU", "ru") == "bachelor"
    assert level_of_year("студенты 3–4 курс бакалавриата", "RU", "") == "bachelor"


def test_no_row_is_no_level():
    assert level_of_year("5th year students", "AZ", "en") is None  # beyond the bachelor's years
    assert level_of_year("I, II və III kurs", "AZ", "ru") is None  # wrong page language
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_years.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.card_funding.years'`

- [ ] **Step 3: Implement**

`docs/research/year-of-study-levels.csv`:

```csv
country,locale,pattern,years,level,source_url
AZ,az,"(?<!\w)(?:IV|I{1,3}|[1-4])(?:\s*(?:,|və|-|–)\s*(?:IV|I{1,3}|[1-4]))*\s+kurs",1-4,bachelor,https://erasmus-networks.ec.europa.eu/book-page/country-page-azerbaijan
AZ,en,"(?<!\w)(?:1st|2nd|3rd|4th|first|second|third|fourth)(?:\s*(?:,|and|to|-|–)\s*(?:1st|2nd|3rd|4th|first|second|third|fourth))*[\s-]+years?\s+(?:undergraduate\s+|bachelor'?s\s+)?students",1-4,bachelor,https://erasmus-networks.ec.europa.eu/book-page/country-page-azerbaijan
DE,en,"(?<!\w)(?:1st|2nd|3rd|first|second|third)(?:\s*(?:,|and|to|-|–)\s*(?:1st|2nd|3rd|first|second|third))*[\s-]+years?\s+(?:undergraduate\s+|bachelor'?s\s+)?students",1-3,bachelor,https://www.gesetze-im-internet.de/hrg/__19.html
RU,ru,"(?<!\w)[1-4](?:\s*(?:,|и|-|–)\s*[1-4])*(?:-?(?:го|й))?\s+курс\w*",1-4,bachelor,https://www.alberta.ca/iqas-education-guide-russia
```

`apps/research/card_funding/years.py`:

```python
"""Year-of-study wording names a level through a per-country table (verified-catalog §5.2.1).

"1st–3rd year students", "I, II və III kurs" and "3–4 курс бакалавриата" are bachelor's students
where the bachelor's lasts long enough. Whether a page states its target level as a year of study
is the readers' judgement (`target_level=year_of_study`); which level that year is, is this
table's: `docs/research/year-of-study-levels.csv`, one row per country and wording language, each
citing its source for the bachelor's length. The country is the FUNDER's (owner, 2026-10-13):
wording that names no country means the funder's own system. An unknown funder country, or one
with no row, maps to nothing -- held, never guessed, and no country is a default; the operator's
fix is a row.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

YEARS_FILE = Path(__file__).resolve().parents[3] / "docs" / "research" / "year-of-study-levels.csv"


@dataclass(frozen=True)
class YearRow:
    country: str  # the funder's country
    locale: str  # the wording's language
    pattern: re.Pattern[str]
    years: str  # "1-4": the study years the pattern accepts, as the source counts them
    level: str
    source_url: str


@cache
def year_rows() -> tuple[YearRow, ...]:
    with YEARS_FILE.open(encoding="utf-8", newline="") as handle:
        return tuple(
            YearRow(r["country"], r["locale"], re.compile(r["pattern"], re.IGNORECASE), r["years"],
                    r["level"], r["source_url"])
            for r in csv.DictReader(handle)
        )


def level_of_year(text: str, funder_country: str, lang: str = "") -> str | None:
    """The level `text` names as a year of study under a funder from `funder_country`, or None.
    An unknown page language ("") tries every row of the country; a known one only its own."""
    for row in year_rows():
        if (funder_country and row.country == funder_country and lang in ("", row.locale)
                and row.pattern.search(text)):
            return row.level
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_years.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add docs/research/year-of-study-levels.csv apps/research/card_funding/years.py \
  tests/research/card_funding/test_years.py
git commit -m "feat(research): year-of-study table names a level by the funder's country"
```

---

### Task 3: A page as lines, and its lines grouped into awards

**Files:**
- Create: `apps/research/card_funding/awards.py`
- Test: `tests/research/card_funding/test_awards.py`

**Why:** §5 step 1 — lines under their headings, a table row with its header row, a long line
split at sentence ends (`funding_judge.funding_lines`'s rule, re-done here so the heading *level*
survives; `funding_judge` itself is not imported). Step 3 — award grouping, with the one judgement
asked of the engine and the rest done by code (decision 1). The heading lines are the page's own
`Line` objects, so the grouping section and every award section sit inside what D8 screened.

**Interfaces:**
- Consumes: `apps.research.candidates.Line`, `Candidates`; `apps.research.card_engine.Section`,
  `Question`, `Quote`, `yes_no`.
- Produces: `Page(title, lang, lines, levels)` with `section() -> Section`;
  `page_lines(text, *, lang, title="") -> Page`; `AWARD_NAME`, `AWARD_NAME_CRITERIA`,
  `HEADINGS_PER_CALL`; `AwardNames` (a `QuestionSet`: ids `award_L<n>`);
  `heading_sections(page) -> list[tuple[Section, tuple[int, ...]]]` (each section with the page
  line index of its lines); `Award(name, name_line, lines)`;
  `group(page, names: set[int]) -> tuple[tuple[Award, ...], int]` (awards, lines no award holds);
  `award_section(page, award) -> Section`.

- [ ] **Step 1: Write the failing tests**

`tests/research/card_funding/test_awards.py`:

```python
from apps.research.candidates import find_all
from apps.research.card_funding.awards import (
    AWARD_NAME,
    AWARD_NAME_CRITERIA,
    AwardNames,
    award_section,
    group,
    heading_sections,
    page_lines,
)

TEXT = """# Scholarships at Baku University
Our university supports students.
## Rector's Scholarship
Monthly stipend of AZN 300.
### How to apply
- Apply by 15 May 2027.
| Level | Amount |
| Master | AZN 400 |
## Merit Award
Tuition waiver of 50%.
## Contact
Write to us.
"""


def test_lines_keep_headings_levels_and_table_headers():
    page = page_lines(TEXT, lang="en")
    assert page.title == "Scholarships at Baku University"
    texts = [line.text for line in page.lines]
    assert texts[4] == "How to apply" and page.levels[4] == 3
    assert page.lines[5].text == "Apply by 15 May 2027." and page.lines[5].heading == "How to apply"
    assert page.lines[6].header == "" and page.lines[7].header == "| Level | Amount |"
    assert page.lines[8].header == ""  # a heading ends the table


def test_a_long_line_splits_at_sentence_ends():
    long = "A" * 200 + ". " + "B" * 200 + "."
    assert [line.text for line in page_lines(long, lang="en").lines] == ["A" * 200 + ".",
                                                                          "B" * 200 + "."]


def test_an_award_runs_to_the_next_heading_at_its_own_level():
    page = page_lines(TEXT, lang="en")
    awards, unread = group(page, {2, 8})
    assert [(a.name, a.lines) for a in awards] == [
        ("Rector's Scholarship", (2, 3, 4, 5, 6, 7)),  # its "How to apply" subsection included
        ("Merit Award", (8, 9)),  # stops at "Contact", a heading at its level
    ]
    assert unread == 4  # the page heading, its intro line, "Contact" and its line
    section = award_section(page, awards[1])
    assert [line.text for line in section.lines] == ["Merit Award", "Tuition waiver of 50%."]
    assert section.texts() <= page.section().texts()  # inside what D8 screened


def test_no_award_heading_makes_the_page_one_award():
    page = page_lines(TEXT, lang="en")
    awards, unread = group(page, set())
    assert awards[0].name == page.title and len(awards[0].lines) == len(page.lines)
    assert unread == 0


def test_the_heading_question_refers_to_lines_by_key_only():
    page = page_lines(TEXT, lang="en")
    [(section, index)] = heading_sections(page)
    assert index == (0, 2, 4, 8, 10)
    questions = AwardNames().questions(section, find_all(section.lines), {})
    assert [q.id for q in questions] == ["award_L0", "award_L1", "award_L2", "award_L3", "award_L4"]
    # page text never travels outside the untrusted wrapper: the wording is fixed, the key varies
    assert {(q.text.replace(q.id[6:], "KEY"), q.criteria) for q in questions} == {
        (AWARD_NAME.format(key="KEY"), AWARD_NAME_CRITERIA)}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_awards.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.card_funding.awards'`

- [ ] **Step 3: Implement**

`apps/research/card_funding/awards.py`:

```python
"""A page as lines, and its lines grouped into awards (verified-catalog §5 steps 1 and 3).

Code does the grouping: an award is a heading the readers say names one scholarship, grant or
award, plus every line under it until the next heading at its own level or above. The readers are
asked only the judgement -- "is this heading the name of an award?" -- and never assign lines
(§5 step 3's own rule: a line stays with the nearest award above it). No heading passes: the whole
page is one award under its title. Lines above the first award are not read, and are counted.

Measured 2026-09-27: grouping by raw headings made Türkiye Bursları's benefit sections fourteen
awards and "Childpage navigation" one, which is why a heading must pass the question first.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from apps.research.candidates import Candidates, Line
from apps.research.card_engine import Question, Quote, Section, yes_no

_HEADING = re.compile(r"^(#{1,6}) (.*)$")
#: funding_judge's split: a long line breaks after sentence punctuation, so a quote stays a
#: sentence the page printed.
_MAX_LINE_CHARS = 300
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
#: Headings asked per call: one short answer each, well inside the reader's output cap.
HEADINGS_PER_CALL = 25

AWARD_NAME = (
    "Is the line `{key}` the name of one scholarship, grant or award programme?"
)
AWARD_NAME_CRITERIA = (
    "yes: a named award or scheme. no: a benefit it includes (\"Monthly stipend\", "
    "\"Accommodation\"), a section such as \"How to apply\", \"Eligibility\" or \"FAQ\", or "
    "navigation."
)


@dataclass(frozen=True)
class Page:
    """A page's readable text as lines. `levels[n]` is line n's heading level, 0 for a line that
    is not a heading. A table row carries the table's first row as its `header`."""

    title: str
    lang: str
    lines: tuple[Line, ...]
    levels: tuple[int, ...]

    def section(self) -> Section:
        return Section(self.title, self.lang, self.lines)


def page_lines(text: str, *, lang: str, title: str = "") -> Page:
    """`readable_text` output as lines, each under the heading above it; headings are lines too.
    `title` defaults to the first heading."""
    lines: list[Line] = []
    levels: list[int] = []
    heading = ""
    table_header = ""
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        marked = _HEADING.match(line)
        if marked:
            line = marked.group(2).strip()
        elif line.startswith("- "):
            line = line[2:].strip()
        header = ""
        if line.startswith("|"):
            header, table_header = (table_header, table_header or line)
        else:
            table_header = ""
        pieces = [line] if len(line) <= _MAX_LINE_CHARS else _SENTENCE_END.split(line)
        for piece in (p for p in pieces if p):
            lines.append(Line(piece, heading=heading, header=header))
            levels.append(len(marked.group(1)) if marked else 0)
        if marked:
            heading = line
    first = next((line.text for line, level in zip(lines, levels, strict=True) if level), "")
    return Page(title or first, lang, tuple(lines), tuple(levels))


@dataclass(frozen=True)
class AwardNames:
    """The one judgement grouping needs, asked of a section of heading lines."""

    name: str = "funding-awards"
    version: str = "v3"
    criteria: str = ""

    def proposals(self, section: Section) -> Sequence[Question]:
        return ()

    def questions(self, section: Section, candidates: Candidates,
                  proposed: Mapping[str, tuple[Quote, ...]]) -> Sequence[Question]:
        return tuple(yes_no(f"award_L{n}", AWARD_NAME.format(key=f"L{n}"), AWARD_NAME_CRITERIA)
                     for n in range(len(section.lines)))


def heading_sections(page: Page) -> list[tuple[Section, tuple[int, ...]]]:
    """The page's headings in sections of `HEADINGS_PER_CALL`, each with the page line index of
    its section lines, so an answer about `L3` maps back to the page."""
    heads = [n for n, level in enumerate(page.levels) if level]
    out = []
    for start in range(0, len(heads), HEADINGS_PER_CALL):
        chunk = tuple(heads[start:start + HEADINGS_PER_CALL])
        out.append((Section(page.title, page.lang, tuple(page.lines[n] for n in chunk)), chunk))
    return out


@dataclass(frozen=True)
class Award:
    name: str
    name_line: int | None  # the heading's page line; None for the page award
    lines: tuple[int, ...]  # page line indexes, the heading first


def group(page: Page, names: set[int]) -> tuple[tuple[Award, ...], int]:
    """Awards from the heading lines that passed, and how many lines no award holds."""
    if not names:
        return (Award(page.title, None, tuple(range(len(page.lines)))),), 0
    awards: list[Award] = []
    held: set[int] = set()
    for start in sorted(names):
        level = page.levels[start]
        end = start + 1
        while end < len(page.lines) and end not in names and not (
                page.levels[end] and page.levels[end] <= level):
            end += 1
        awards.append(Award(page.lines[start].text, start, tuple(range(start, end))))
        held.update(range(start, end))
    return tuple(awards), len(page.lines) - len(held)


def award_section(page: Page, award: Award) -> Section:
    return Section(page.title, page.lang, tuple(page.lines[n] for n in award.lines))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_awards.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/research/card_funding/awards.py tests/research/card_funding/test_awards.py
git commit -m "feat(research): funding page lines and award grouping by heading"
```

---

### Task 4: The funding question set

**Files:**
- Create: `apps/research/card_funding/questions.py`
- Create: `tests/research/card_funding/oracle.py`
- Test: `tests/research/card_funding/test_questions.py`

**Why these shapes:** §5.2's call-3 catalogue, wording A, with definitions v3 as the set's
criteria (sent with every call). Each question names one property and refers to page text only
by key (`amounts.m2`, `places.p1`, `proposed.requirements.0`). Per amount: who pays, what it
covers (one yes/no per purpose), how often, for how long, bound (only when code did not already
read a range or "approx."), for whom, for all or per place on its own line, per level and intake
on its line. A conversion ("HUF 43,700 (approx. 110 EUR)") is asked about once, with the amount
it converts. Per date: its role (definitions v3), day-or-month order only when code flags it, for
all or per place. Per place: eligible, excluded, and for a low- and middle-income phrase whether
it is the whole condition (decision 9). Per code requirement: is it a condition. Per duration: is
it the funding's (decision 6). Batching is decision 4.

`oracle.py` is the test double every later task uses: a scripted reader stack that answers from a
table by question id, falls back to each question's absence option, answers a scripted quote
only where it is printed in the section being read, and can split or silence a question.

**Interfaces:**
- Consumes: `find_all`, `Candidates`; `Question`, `Quote`, `Section`, `proposal`, `yes_no`;
  `groups.group_of` (Task 1).
- Produces: `BATCH = 20`; `CRITERIA`; the option tuples `COVERS`, `BENEFICIARIES`, `DATE_ROLES`,
  `REQUIREMENT_KINDS`, `EXTRAS`, `OBLIGATIONS`; `REQUIREMENTS` (the proposal); `AWARD` (the
  per-award rows); `code_questions(c: Candidates) -> list[Question]`;
  `kind_questions(c, proposed) -> list[Question]`; `Funding(batch=0)` (a `QuestionSet`, name
  `funding`, version `v3`); `batches(section) -> int` (code batches; batch 0 comes on top).
  Question ids: `pays_mN`, `covers_<x>_mN`, `frequency_mN`, `duration_mN`, `bound_mN`,
  `for_<who>_mN`, `for_all_mN`, `for_pK_mN`, `level_mN`, `intake_mN`, `role_dN`/`role_rN`,
  `order_dN`, `for_all_dN`, `for_pK_dN`, `eligible_pN`, `excluded_pN`, `sole_pN`,
  `requires_cN`, `funds_uN`, `kind_N`, and the `AWARD` ids (`target_level`, `place_basis`,
  `money_form`, `holder_kind`, `route`, `route_order`, `tuition_level`, `living_level`,
  `apply_here`, `apply_elsewhere`, `institution_wide`, `renewal_condition`, `internationals`,
  `eligibility_elsewhere`, `discontinued`, `window_closed`, `funding_period`, `extra_<x>`,
  `obligation_<x>`).
- Test helper: `Oracle(answers=None, *, split=(), silent=(), cost=0.0001, latency=0.1)`, a
  `Transport`; `.asked` lists `(reader, [question ids])`; `.ids(reader="deepseek")` flattens
  one reader's question ids.

- [ ] **Step 1: Write the test helper and the failing tests**

`tests/research/card_funding/oracle.py`:

```python
"""A scripted reader stack for the funding tests: no model is ever called.

`Oracle(answers)` answers every question it is asked from `answers` (question id -> (value,
quote)); anything not scripted gets the question's absence option. A proposal id maps to a list of
quotes. `split` names questions on which the two cheap readers disagree, so the decider answers
them; `silent` names questions nobody answers, which the engine records as unresolved.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping

from apps.research.card_engine.readers import Attempt, Reply


class Oracle:
    def __init__(self, answers: Mapping[str, object] | None = None, *, split: Iterable[str] = (),
                 silent: Iterable[str] = (), cost: float = 0.0001, latency: float = 0.1):
        self.answers = dict(answers or {})
        self.split, self.silent = set(split), set(silent)
        self.cost, self.latency = cost, latency
        self.asked: list[tuple[str, list[str]]] = []
        self.lock = threading.Lock()

    def __call__(self, spec, prompt) -> Attempt:
        questions = json.loads(prompt.ask)["questions"]
        with self.lock:
            self.asked.append((spec.name, [q["id"] for q in questions]))
        out = []
        for q in questions:
            qid = q["id"]
            if qid in self.silent:
                continue
            if q["options"] == ["quote"]:
                out += [{"id": qid, "value": "quote", "quote": text}
                        for text in self.answers.get(qid, [])  # type: ignore[union-attr]
                        if text in prompt.data]
                continue
            value, quote = self.answers.get(qid, (q["no_quote_for"][0], ""))  # type: ignore[misc]
            if quote and quote not in prompt.data:
                value, quote = q["no_quote_for"][0], ""
            if qid in self.split and spec.name == "luna":
                value, quote = q["no_quote_for"][0], ""
            out.append({"id": qid, "value": value, "quote": quote})
        reply = Reply.model_validate({"answers": out})
        return Attempt(reply, "", self.cost, self.latency)

    def ids(self, reader: str = "deepseek") -> list[str]:
        return [qid for name, ids in self.asked if name == reader for qid in ids]
```

`tests/research/card_funding/test_questions.py`:

```python
from uuid import uuid4

from apps.research.candidates import Line, find_all
from apps.research.card_engine import Limit, Quote, Section
from apps.research.card_engine.engine import read
from apps.research.card_engine.screen import Screen
from apps.research.card_funding.questions import (
    AWARD,
    BATCH,
    CRITERIA,
    Funding,
    batches,
    code_questions,
    kind_questions,
)

from .oracle import Oracle

SECTION = Section("Stipendium Hungaricum", "en", (
    Line("Stipendium Hungaricum", heading=""),
    Line("Monthly stipend of HUF 43,700 (approx. 110 EUR) for master students",
         heading="Stipendium Hungaricum"),
    Line("Tuition support between EUR 1,000 and EUR 2,000", heading="Stipendium Hungaricum"),
    Line("Apply by 10/11/2026 if you are from Azerbaijan", heading="Stipendium Hungaricum"),
    Line("Open to citizens of low- and middle-income countries. IELTS 6.0 required.",
         heading="Stipendium Hungaricum"),
    Line("Applicants must not have lived in Hungary for more than 12 months.",
         heading="Stipendium Hungaricum"),
))


def _limit():
    return Limit("card-funding-test", uuid4(), 500, 3600)


def test_every_question_refers_to_page_text_by_key_only():
    questions = code_questions(find_all(SECTION.lines))
    page_only = ("Hungaricum", "43,700", "10/11/2026", "Azerbaijan", "Hungary", "IELTS", "low-")
    for q in questions:
        assert not [w for w in page_only if w in q.text + q.criteria + " ".join(q.options)], q.id
    assert len({q.id for q in questions}) == len(questions)
    assert "HUF" not in CRITERIA


def test_code_questions_follow_the_candidates():
    c = find_all(SECTION.lines)
    ids = {q.id for q in code_questions(c)}
    assert {qid for qid, *_ in AWARD} <= ids
    [conversion] = c.conversion_of  # "(approx. 110 EUR)" converts HUF 43,700: asked once, with it
    assert f"pays_{conversion}" not in ids and f"pays_{c.conversion_of[conversion]}" in ids
    ranged = next(k for k, f in c.amounts.items() if f.value.bound == "range")
    assert f"pays_{ranged}" in ids and f"bound_{ranged}" not in ids  # code set the range
    [date] = c.dates  # 10/11/2026: day or month first is asked, never guessed
    assert f"order_{date}" in ids
    places = {f.value.text: k for k, f in c.places.items()}
    assert f"for_{places['Azerbaijan']}_{date}" in ids  # a place on the date's own line
    lmy = places["low- and middle-income countries"]
    assert f"sole_{lmy}" in ids and f"sole_{places['Azerbaijan']}" not in ids
    level = next(iter(c.levels))
    first = next(k for k in c.amounts if k not in c.conversion_of)
    assert any(q.id == f"level_{first}" and level in q.options for q in code_questions(c))


def test_batches_cover_every_code_question_once():
    c = find_all(SECTION.lines)
    every = [q.id for q in code_questions(c)]
    seen = []
    for n in range(1, batches(SECTION) + 1):
        asked = Funding(batch=n).questions(SECTION, c, {})
        assert 0 < len(asked) <= BATCH
        seen += [q.id for q in asked]
    assert seen == every
    assert Funding(batch=1).proposals(SECTION) == ()
    assert [q.id for q in Funding(batch=0).proposals(SECTION)] == ["requirements"]


def test_a_proposed_quote_that_repeats_a_code_candidate_is_not_asked_again():
    c = find_all(SECTION.lines)
    proposed = {"requirements": (
        Quote("IELTS 6.0 required", "L4.text"),
        Quote("must not have lived in Hungary for more than 12 months", "L5.text"),
    )}
    assert [q.id for q in kind_questions(c, proposed)] == ["kind_1"]


def test_batch_zero_reads_the_proposals_and_asks_their_kinds():
    oracle = Oracle({
        "requirements": ["must not have lived in Hungary for more than 12 months"],
        "kind_0": ("residence_limit", "must not have lived in Hungary for more than 12 months"),
    })
    reading = read(Funding(batch=0), SECTION, screen=Screen("clear", SECTION.texts()),
                   limit=_limit(), transport=oracle)
    assert reading.proposed["requirements"] == (
        Quote("must not have lived in Hungary for more than 12 months", "L5.text"),)
    [kind] = reading.decisions
    assert (kind.question, kind.status, kind.value) == ("kind_0", "agreed", "residence_limit")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_questions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.card_funding.questions'`

- [ ] **Step 3: Implement**

`apps/research/card_funding/questions.py`:

```python
"""The funding question set: §5.2's catalogue under definitions v3, per award (verified-catalog §5).

Every question refers to page text by key -- `amounts.m2`, `places.p1`, `proposed.requirements.0`,
`L4` -- and never carries it: question text and criteria travel outside the untrusted wrapper.
Wording is §5.2's wording A; the criteria are §5.2.1's definitions v3.

One reading answers at most `BATCH` questions, because the reader's reply is capped
(`readers.MAX_OUTPUT_TOKENS`, about 25 answers with quotes). So a section is read in batches:
batch 0 carries the one proposal (requirements, where code alone found 7 of 50 and the proposer
lifted it to 28 of 50, §5) and the kind of each proposed quote; batches 1.. carry the questions
about code's own candidates, which do not depend on the proposals and so run in parallel with it.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from apps.research.candidates import Candidates, find_all
from apps.research.card_engine import Question, Quote, Section, proposal, yes_no

from .groups import group_of

logger = logging.getLogger(__name__)

BATCH = 20

CRITERIA = """Definitions (version 3). Read the section in its own language; answer in the options.
- Level: the TARGET level the award is for. A degree the applicant must already hold ("completed a
  first degree", "2 years' work after the bachelor's") is a prior_degree requirement, and "PhD
  holders cannot apply" an excluded_degree requirement; neither is the level. When the section
  names its students by year of study ("1st-3rd year students", "I, II ve III kurs"), the level is
  year_of_study.
- Nationality: a condition is a named list of countries, regions or citizenships. Generic
  "international" or "foreign" students is not a list. Residence limits, stateless persons and
  compatriots abroad are conditions for applying.
- Application dates are dates of applying to THIS award. An olympiad, exam, event or competition
  date, or another programme's date, is "other" unless the section says applying happens through
  that event. "Applications are open" with no date is not a date.
- A required test or certificate (SAT, ACT, a copy of a language certificate) is a condition for
  applying even with no score.
- "The programme does not pay X" is none for X, never a waiver: a waiver says the student is not
  charged."""

_PAYS = ("paid_to_student", "fee_charged_to_student", "application_fee", "fee_reduction",
         "in_kind_value", "cost_estimate", "total_budget_or_count", "other", "not_stated")
COVERS = ("tuition", "living", "travel", "housing", "insurance", "relocation", "total")
BENEFICIARIES = ("student", "spouse_or_partner", "children", "family_or_dependants")
_FREQUENCY = ("monthly", "annual", "per_semester", "one_off", "instalments", "not_stated")
_DURATION = ("whole_programme", "first_year_only", "from_second_year", "one_semester",
             "two_semesters", "during_mobility_or_internship", "until_next_assessment", "other",
             "not_stated")
_BOUND = ("exact", "up_to", "at_least", "approximately", "not_stated")
DATE_ROLES = ("application_deadline", "application_opening", "fee_deadline", "application_period",
              "results_announced", "selection_or_award", "funding_period", "programme_start",
              "page_published_or_updated", "other", "not_stated")
REQUIREMENT_KINDS = ("prior_degree", "excluded_degree", "language_test", "test_or_certificate",
                     "grade", "age", "residence_limit", "stateless", "compatriot",
                     "other_condition", "none")
EXTRAS = ("travel", "insurance", "housing", "language_year", "visa_support", "family_support")
OBLIGATIONS = ("return_home", "work_in_host", "serve_funder", "repay_on_breach")
#: The closed lists of funding_judge (spec §3.1), lower-cased; copied, not imported, because
#: slice 3 deletes that module's vote.
_HOLDER = ("national_government", "subnational_government", "political_foundation", "religious",
           "private_foundation", "employer", "intergovernmental", "regional_fund",
           "embassy_bilateral", "diaspora_affinity", "professional_body", "bank_or_lender",
           "alumni", "institution", "not_stated")
_ROUTE = ("automatic_on_admission", "considered_with_admission", "student_applies_separately",
          "institution_nominates", "home_government_nominates", "joint_selection", "other",
          "not_stated")
_MONEY = ("grant", "fee_waiver", "subsidy", "loan", "forgivable_loan", "mixed", "other",
          "not_stated")
_COVER_LEVEL = ("none", "partial", "full", "not_stated")

REQUIREMENTS = proposal(
    "requirements",
    "Point at every span that states a condition for applying to this award: a degree held or "
    "excluded, a test or certificate, a grade, an age, a residence limit, being stateless, or "
    "being a compatriot abroad.",
)

#: Asked once per award: (id, wording A, options, criteria). None as options means yes/no.
AWARD: tuple[tuple[str, str, tuple[str, ...] | None, str], ...] = (
    ("target_level", "Which degree level is this award for?",
     ("master", "bachelor", "phd", "postdoc", "any", "year_of_study", "not_stated"),
     "The level the award is FOR, never a degree the applicant must already hold."),
    ("place_basis", "Do these lines test the applicant's citizenship, residence, or both?",
     ("citizenship", "residence", "both", "not_stated"), ""),
    ("money_form", "What form does the money take?", _MONEY, ""),
    ("holder_kind", "Which kind of body gives the money described in these lines?", _HOLDER, ""),
    ("route", "How does a student obtain this money?", _ROUTE, ""),
    ("route_order", "When the money and the admission are applied for separately, which comes "
     "first?", ("before_admission", "after_admission", "parallel", "not_stated"), ""),
    ("tuition_level", "How much of tuition does this award cover?", _COVER_LEVEL,
     "A sentence saying the programme does not pay tuition is none, never a waiver."),
    ("living_level", "How much of living costs does this award cover?", _COVER_LEVEL, ""),
    ("apply_here", "Do these lines state that students apply to the organisation whose page "
     "this is for this money?", None, ""),
    ("apply_elsewhere", "Do these lines state that students apply to a different organisation "
     "than the one whose page this is for this money?", None, ""),
    ("institution_wide", "Do these lines state that students of any programme at the "
     "organisation whose page this is can receive this money?", None, ""),
    ("renewal_condition", "Do these lines state a condition for keeping or renewing the award "
     "after its first period?", None, ""),
    ("internationals", "Do these lines state that international or foreign students are "
     "eligible?", None, ""),
    ("eligibility_elsewhere", "Do these lines say the list of who may apply is given somewhere "
     "else (an agreement, a country list, a drop-down menu, another page)?", None, ""),
    ("discontinued", "Do these lines state that this award is discontinued or not offered in "
     "the coming round?", None, ""),
    ("window_closed", "Do these lines state that applications for this award are currently "
     "closed?", None, ""),
    ("funding_period", "Do these lines state the years during which this award is funded or "
     "offered?", None, ""),
    *((f"extra_{x}", f"Do these lines state that the award includes {x.replace('_', ' ')}?",
       None, "") for x in EXTRAS),
    *((f"obligation_{x}", "Do these lines state that the holder must "
       f"{x.replace('_', ' ').replace('host', 'the host country')}?", None, "")
      for x in OBLIGATIONS),
)


def _q(qid: str, text: str, options: tuple[str, ...] | None, criteria: str = "") -> Question:
    return yes_no(qid, text, criteria) if options is None else Question(qid, text, options,
                                                                         criteria)


def _on_line[T](group: Mapping[str, T], line: int) -> list[str]:
    return [key for key, found in group.items() if found.line == line]  # type: ignore[attr-defined]


def _amount(key: str, c: Candidates) -> list[Question]:
    found = c.amounts[key]
    ref = f"`amounts.{key}`"
    qs = [_q(f"pays_{key}", f"Who pays the amount in {ref}?", _PAYS,
             "A sentence saying a cost is NOT paid by the programme is never fee_reduction.")]
    qs += [_q(f"covers_{x}_{key}", f"Does the text state that the amount in {ref} is for {x}?",
              None, "yes only when the text names it as what this amount pays for; a "
              "scholarship or stipend whose purpose is not named is no.") for x in COVERS]
    qs.append(_q(f"frequency_{key}", f"How often is the amount in {ref} paid or charged?",
                 _FREQUENCY))
    qs.append(_q(f"duration_{key}", f"For how long is the amount in {ref} paid?", _DURATION))
    if found.value.bound is None:  # code sets range and approximately; it never asks them
        qs.append(_q(f"bound_{key}", f"Is the amount in {ref} an exact sum, a maximum, a "
                     "minimum, or approximate?", _BOUND))
    qs += [_q(f"for_{x}_{key}", f"Does the text state that the amount in {ref} is for the "
              f"{x.replace('_', ' ')}?", None, "A sum paid to the student with no beneficiary "
              "named is for the student.") for x in BENEFICIARIES]
    qs.append(_q(f"for_all_{key}", f"Does {ref} apply to all applicants alike?", None))
    qs += [_q(f"for_{p}_{key}", f"Does {ref} apply to applicants from `places.{p}`?", None)
           for p in _on_line(c.places, found.line)]
    if levels := _on_line(c.levels, found.line):
        qs.append(_q(f"level_{key}", f"Which study level does the amount in {ref} apply to?",
                     (*levels, "all_levels", "not_stated")))
    if intakes := _on_line(c.intakes, found.line):
        qs.append(_q(f"intake_{key}", f"Which intake or year does the amount in {ref} apply "
                     "to?", (*intakes, "not_stated")))
    return qs


def _date(key: str, group: str, c: Candidates) -> list[Question]:
    found = (c.dates if group == "dates" else c.relative_dates)[key]
    ref = f"`{group}.{key}`"
    qs = [_q(f"role_{key}", f"What is the date in {ref}?", DATE_ROLES)]
    if getattr(found.value, "order_ambiguous", False):
        qs.append(_q(f"order_{key}", f"In {ref}, is the first number the day or the month?",
                     ("day_first", "month_first", "not_stated")))
    qs.append(_q(f"for_all_{key}", f"Does {ref} apply to all applicants alike?", None))
    qs += [_q(f"for_{p}_{key}", f"Does {ref} apply to applicants from `places.{p}`?", None)
           for p in _on_line(c.places, found.line)]
    return qs


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


def _line_of(quote: Quote) -> int:
    return int(quote.where[1:].split(".")[0]) if quote.where.startswith("L") else -1


def kind_questions(c: Candidates, proposed: Mapping[str, tuple[Quote, ...]]) -> list[Question]:
    """What condition each proposed quote states, skipping a quote that only repeats a code
    candidate on its line (code's requirement is already asked about)."""
    qs = []
    for n, quote in enumerate(proposed.get("requirements", ())):
        line = _line_of(quote)
        if any(found.line == line and found.value.text in quote.text
               for found in c.requirements.values()):
            continue
        qs.append(Question(f"kind_{n}", f"What condition for applying does the quote "
                           f"`proposed.requirements.{n}` state?", REQUIREMENT_KINDS))
    if len(qs) > BATCH:
        logger.warning("funding: %d proposed requirements, %d asked", len(qs), BATCH)
    return qs[:BATCH]


@dataclass(frozen=True)
class Funding:
    """One batch of the funding set over one award's section. Batch 0: the proposal and the
    kinds of what it found. Batch n >= 1: slice n of `code_questions`."""

    batch: int = 0
    name: str = "funding"
    version: str = "v3"
    criteria: str = CRITERIA

    def proposals(self, section: Section) -> Sequence[Question]:
        return (REQUIREMENTS,) if self.batch == 0 else ()

    def questions(self, section: Section, candidates: Candidates,
                  proposed: Mapping[str, tuple[Quote, ...]]) -> Sequence[Question]:
        if self.batch == 0:
            return kind_questions(candidates, proposed)
        return code_questions(candidates)[(self.batch - 1) * BATCH:self.batch * BATCH]


def batches(section: Section) -> int:
    """How many code batches the section needs (batch 0 comes on top)."""
    return math.ceil(len(code_questions(find_all(section.lines))) / BATCH)

```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_questions.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/research/card_funding/questions.py tests/research/card_funding/oracle.py \
  tests/research/card_funding/test_questions.py
git commit -m "feat(research): the funding question set under definitions v3, in batches"
```

---

### Task 5: Parse — decisions and candidates become typed values

**Files:**
- Create: `apps/research/card_funding/parse.py`
- Test: `tests/research/card_funding/test_parse.py`

**Why these shapes:** "Code parses every value" (§5). An amount, date, relative date, duration,
intake, place or requirement on the card *is* the slice-1 candidate — its own parsed numbers and
its own byte-exact span as the quote — and a label is the option the readers agreed on or the
decider chose. A field that cannot be read comes back as a problem with a hold reason and a key,
never page text, and stops only that field. The identities of §5 step 6 are enforced here: a fee
or cost is never a benefit; a conversion pair is one benefit; a place both eligible and excluded
is neither; an ambiguous day/month needs its order; a date needs a year; year of study goes
through Task 2's table for the funder's country (decision 5); group phrases through Task 1's fallback (decisions 8–11). An impossible
date never arrives: slice 1's finder keeps only real calendar dates ("30 February 2027" is read
as "February 2027").

**Interfaces:**
- Consumes: `Candidates`, `Found`, `Amount`, `Date`, `RelativeDate`, `Intake`, `Requirement`,
  `who.find_requirements`; `Decision`, `Quote`; `groups.expand`, `groups.group_of`;
  `questions.BENEFICIARIES`, `COVERS`, `EXTRAS`, `OBLIGATIONS`; `years.level_of_year`.
- Produces: `ABSENT`, `BENEFIT_PAYS`, `FEE_PAYS`, `SHOWN_ROLES`, `LABELS`, `FLAGS`;
  `Value(value, quote, source, decisions)`; `Parsed(values=(), problem="", detail="")`;
  `Benefit(amount, conversion, pays, bound, covers, frequency, duration, for_whom, for_all,
  places, level, intake)`; `AwardDate(role, date, for_all, places, cycle=None)`;
  `Nationality(eligible, excluded, held, basis, groups)`; `Condition(kind, requirement)`;
  `page_date(decisions, c, default) -> date`;
  `parse_award(decisions, c, proposed, *, source: str, funder_country: str, lang: str,
  today: date) -> dict[str, Parsed]`
  with keys `benefits`, `fees`, `dates`, `target_level`, `nationality`, `requirements`,
  `funding_duration`, `funding_period`, the `LABELS`, the `FLAGS`, `extras`, `obligations`.

- [ ] **Step 1: Write the failing tests**

`tests/research/card_funding/test_parse.py`:

```python
import datetime as dt
from decimal import Decimal

from apps.research.candidates import Line, find_all
from apps.research.card_engine import Decision, Quote, Section, locate
from apps.research.card_funding.parse import (
    AwardDate,
    Benefit,
    Condition,
    Nationality,
    parse_award,
)
from apps.research.card_funding.questions import code_questions

URL = "https://example.edu.az/scholarships"
TODAY = dt.date(2026, 10, 13)


def _section(*texts):
    return Section("Rector's Scholarship", "en", tuple(Line(t) for t in texts))


def _decisions(section, answers, unresolved=()):
    """An agreed decision for every code question: scripted (value, quote) or its absence."""
    out = []
    for q in code_questions(find_all(section.lines)):
        if q.id in unresolved:
            out.append(Decision(q.id, "unresolved", None, None, {}))
            continue
        value, quote = answers.get(q.id, (sorted(set(q.options) & q.unquoted)[0], ""))
        out.append(Decision(q.id, "agreed", value, locate(quote, section) if quote else None, {}))
    return out


def _parse(section, answers, unresolved=(), proposed=None, funder_country="", **extra):
    decisions = _decisions(section, answers, unresolved) + list(extra.pop("more", ()))
    return parse_award(decisions, find_all(section.lines), proposed or {}, source=URL,
                       funder_country=funder_country, lang="en", today=TODAY)


def _key(section, group, text):
    c = find_all(section.lines)
    return next(k for k, f in getattr(c, group).items() if f.value.text == text)


def test_an_amount_is_the_candidate_code_read_with_the_labels_the_readers_chose():
    s = _section("Monthly stipend of AZN 300 for living costs",
                 "Application fee: AZN 20")
    m1, m2 = _key(s, "amounts", "AZN 300"), _key(s, "amounts", "AZN 20")
    fields = _parse(s, {
        f"pays_{m1}": ("paid_to_student", "Monthly stipend of AZN 300"),
        f"covers_living_{m1}": ("yes", "living costs"),
        f"frequency_{m1}": ("monthly", "Monthly"),
        f"bound_{m1}": ("exact", "AZN 300"),
        f"for_student_{m1}": ("yes", "stipend"),
        f"pays_{m2}": ("application_fee", "Application fee"),
        f"frequency_{m2}": ("one_off", "Application fee"),
    })
    [stipend] = fields["benefits"].values
    benefit = stipend.value
    assert isinstance(benefit, Benefit)
    assert (benefit.amount.low, benefit.amount.currency) == (Decimal("300"), "AZN")
    assert (benefit.covers, benefit.frequency, benefit.bound) == ({"living"}, "monthly", "exact")
    assert stipend.quote == Quote("AZN 300", "L0.text") and stipend.source == URL
    assert {d.question for d in stipend.decisions} >= {f"pays_{m1}", f"frequency_{m1}"}
    [fee] = fields["fees"].values  # a fee charged to the student never becomes a benefit
    assert fee.value.pays == "application_fee"


def test_an_unresolved_label_holds_the_field_and_only_that_field():
    s = _section("Monthly stipend of AZN 300", "Apply by 15 May 2027.")
    m1, d1 = _key(s, "amounts", "AZN 300"), _key(s, "dates", "15 May 2027")
    fields = _parse(s, {f"pays_{m1}": ("paid_to_student", "AZN 300"),
                        f"role_{d1}": ("application_deadline", "Apply by 15 May 2027.")},
                    unresolved={f"frequency_{m1}"})
    assert (fields["benefits"].problem, fields["benefits"].detail) == (
        "unresolved_split", f"frequency_{m1}")
    [deadline] = fields["dates"].values
    assert deadline.value == AwardDate("application_deadline", find_all(s.lines).dates[d1].value,
                                       False, ())


def test_an_ambiguous_date_needs_its_order_and_a_year():
    s = _section("Deadline 10/11/2026", "Opens 1 March")
    d1, d2 = _key(s, "dates", "10/11/2026"), _key(s, "dates", "1 March")
    roles = {f"role_{d1}": ("application_deadline", "Deadline 10/11/2026"),
             f"role_{d2}": ("application_opening", "Opens 1 March")}
    fields = _parse(s, {**roles, f"order_{d1}": ("day_first", "10/11/2026")})
    assert (fields["dates"].problem, fields["dates"].detail) == ("unparseable_value", d2)
    fields = _parse(_section("Deadline 10/11/2026"),
                    {f"role_{d1}": roles[f"role_{d1}"], f"order_{d1}": ("day_first", "10/11/2026")})
    [deadline] = fields["dates"].values
    assert (deadline.value.date.day, deadline.value.date.month) == (10, 11)
    fields = _parse(_section("Deadline 10/11/2026"), {f"role_{d1}": roles[f"role_{d1}"]})
    assert fields["dates"].problem == "unparseable_value"  # order not answered: never guessed


def test_a_page_date_moves_the_group_lists_to_its_own_day():
    s = _section("Open to citizens of CIS countries.", "Updated 1 May 2027")
    p1, d1 = _key(s, "places", "CIS countries"), _key(s, "dates", "1 May 2027")
    [value] = _parse(s, {f"eligible_{p1}": ("yes", "CIS countries"),
                         f"role_{d1}": ("page_published_or_updated", "Updated 1 May 2027")})[
        "nationality"].values
    assert "MD" in value.value.held  # Moldova's exit took effect on 2027-04-08


def test_year_of_study_names_a_level_through_the_funders_country():
    s = _section("Open to 1st–3rd year students")
    answer = {"target_level": ("year_of_study", "1st–3rd year students")}
    for funder_country in ("AZ", "DE"):  # an Azerbaijani and a German funder
        assert _parse(s, answer, funder_country=funder_country)["target_level"].values[
            0].value == "bachelor", funder_country
    held = _parse(s, answer, funder_country="")["target_level"]  # an unknown funder
    assert (held.values, held.problem, held.detail) == ((), "unparseable_value", "target_level")


def test_a_named_country_list_is_the_nationality_and_both_answers_are_not_stated():
    s = _section("Citizens of Azerbaijan and Georgia may apply; Georgia excluded this year.")
    az, ge = _key(s, "places", "Azerbaijan"), _key(s, "places", "Georgia")
    fields = _parse(s, {f"eligible_{az}": ("yes", "Citizens of Azerbaijan"),
                        f"eligible_{ge}": ("yes", "Georgia may apply"),
                        f"excluded_{ge}": ("yes", "Georgia excluded"),
                        "place_basis": ("citizenship", "Citizens")})
    [value] = fields["nationality"].values
    assert value.value == Nationality(frozenset({"AZ"}), frozenset(), frozenset(), "citizenship",
                                      ())


def test_a_group_with_no_list_on_the_page_reads_through_the_fallback():
    s = _section("Open to citizens of CIS countries.")
    p1 = _key(s, "places", "CIS countries")
    [value] = _parse(s, {f"eligible_{p1}": ("yes", "citizens of CIS countries")})[
        "nationality"].values
    assert "AZ" in value.value.eligible and value.value.held == {"UA"}
    assert "GE" not in value.value.eligible | value.value.held


def test_developing_countries_holds_a_dac_country_unless_the_page_says_dac():
    s = _section("Open to applicants from developing countries.")
    p1 = _key(s, "places", "developing countries")
    [value] = _parse(s, {f"eligible_{p1}": ("yes", "developing countries")})["nationality"].values
    assert value.value.eligible == set() and "AZ" in value.value.held
    s = _section("Open to applicants from developing countries (DAC list).")
    p1 = _key(s, "places", "developing countries")
    [value] = _parse(s, {f"eligible_{p1}": ("yes", "developing countries")})["nationality"].values
    assert "AZ" in value.value.eligible and value.value.held == set()


def test_the_funders_own_list_comes_before_the_group():
    s = _section("Developing countries, namely Azerbaijan and Kenya, are eligible.")
    keys = {f.value.text: k for k, f in find_all(s.lines).places.items()}
    answers = {f"eligible_{k}": ("yes", "are eligible") for k in keys.values()}
    [value] = _parse(s, answers)["nationality"].values
    assert value.value.eligible == {"AZ", "KE"} and value.value.held == set()
    assert value.value.groups == ("DEVELOPING:beside_list",)


def test_vague_groups_and_pointers_hold_or_hunt():
    s = _section("Open to students from the Global South.")
    p1 = _key(s, "places", "Global South")
    fields = _parse(s, {f"eligible_{p1}": ("yes", "Global South")})
    assert (fields["nationality"].problem, fields["nationality"].detail) == (
        "held_country_group", "GLOBAL_SOUTH")
    s = _section("International students are welcome to apply.")
    fields = _parse(s, {"internationals": ("yes", "International students are welcome")})
    assert fields["nationality"].problem == "needs_hunt"
    s = _section("See the list of eligible countries.")
    fields = _parse(s, {"eligibility_elsewhere": ("yes", "See the list of eligible countries")})
    assert (fields["nationality"].problem, fields["nationality"].detail) == (
        "needs_hunt", "eligibility_elsewhere")
    s = _section("Open to partner countries only.")
    p1 = _key(s, "places", "partner countries")
    fields = _parse(s, {f"eligible_{p1}": ("yes", "partner countries")})
    assert (fields["nationality"].problem, fields["nationality"].detail) == (
        "unparseable_value", p1)


def test_requirements_union_code_and_proposed_quotes():
    s = _section("IELTS 6.5 required.", "Stateless persons may also apply.")
    c1 = _key(s, "requirements", "IELTS 6.5")
    proposed = {"requirements": (Quote("Stateless persons may also apply", "L1.text"),)}
    kind = Decision("kind_0", "agreed", "stateless",
                    Quote("Stateless persons may also apply", "L1.text"), {})
    fields = _parse(s, {f"requires_{c1}": ("yes", "IELTS 6.5 required")}, proposed=proposed,
                    more=[kind])
    conditions = [v.value for v in fields["requirements"].values]
    assert conditions[0].kind == "language_test" and conditions[0].requirement.score == Decimal(
        "6.5")
    assert conditions[1] == Condition("stateless", None)


def test_labels_flags_and_route_order():
    s = _section("Students apply to the ministry before admission. Travel is covered.")
    fields = _parse(s, {"route": ("student_applies_separately", "Students apply"),
                        "route_order": ("before_admission", "before admission"),
                        "extra_travel": ("yes", "Travel is covered"),
                        "apply_elsewhere": ("yes", "apply to the ministry")})
    assert fields["route_order"].values[0].value == "before_admission"
    assert fields["extras"].values[0].value == {"travel"}
    assert fields["apply_elsewhere"].values[0].value == "yes"
    assert fields["discontinued"].values == ()
    fields = _parse(s, {"route": ("considered_with_admission", "Students apply"),
                        "route_order": ("before_admission", "before admission")})
    assert fields["route_order"].values == ()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_parse.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.card_funding.parse'`

- [ ] **Step 3: Implement**

`apps/research/card_funding/parse.py`:

```python
"""Decisions plus code's candidates become typed values (verified-catalog §5 steps 4 and 6).

The readers pointed and judged; code reads every value. An amount, a date, a duration, a place or
a requirement is the slice-1 candidate itself -- its parsed numbers, never a reader's retyping --
and a label is the option the readers agreed on (or the decider chose). Each field comes back as
`Parsed`: the values with the quote and the decisions they were built from, or a problem that
names a hold reason and a key (never page text):

- `unresolved_split`: a decision the field needs came back unresolved;
- `unparseable_value`: code cannot read the value the readers chose (an ambiguous figure, a date
  with no year or an unanswered day/month order, a year of study with no table row, a group
  phrase with no fallback row);
- `held_country_group`: the fallback holds everyone for the group named (§5.2.1);
- `needs_hunt`: the value is elsewhere -- a pointer to a list, or only "international students"
  (§5.2.1). Slice 2c hunts it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from functools import partial
from typing import Any

from apps.research.candidates import (
    Amount,
    Candidates,
    Date,
    Found,
    Intake,
    RelativeDate,
    Requirement,
)
from apps.research.candidates.who import find_requirements
from apps.research.card_engine import Decision, Quote

from .groups import expand, group_of
from .questions import BENEFICIARIES, COVERS, EXTRAS, OBLIGATIONS
from .years import level_of_year

ABSENT = frozenset({"no", "not_stated", "none"})
BENEFIT_PAYS = frozenset({"paid_to_student", "fee_reduction", "in_kind_value"})
FEE_PAYS = frozenset({"fee_charged_to_student", "application_fee"})
#: Date roles a card shows; the rest are context ("other") or the page's own date.
SHOWN_ROLES = frozenset({"application_deadline", "application_opening", "fee_deadline",
                         "application_period", "results_announced", "selection_or_award",
                         "funding_period", "programme_start"})
LABELS = ("money_form", "holder_kind", "route", "route_order", "tuition_level", "living_level")
FLAGS = ("apply_here", "apply_elsewhere", "institution_wide", "renewal_condition",
         "discontinued", "window_closed")


@dataclass(frozen=True)
class Value:
    value: object
    quote: Quote | None
    source: str
    decisions: tuple[Decision, ...]  # who said what, for every decision the value rests on


@dataclass(frozen=True)
class Parsed:
    values: tuple[Value, ...] = ()
    problem: str = ""
    detail: str = ""  # a candidate key, a question id or a group key


@dataclass(frozen=True)
class Benefit:
    amount: Amount
    conversion: Amount | None
    pays: str
    bound: str | None
    covers: frozenset[str]
    frequency: str
    duration: str
    for_whom: frozenset[str]
    for_all: bool
    places: tuple[str, ...]  # place codes the amount is limited to
    level: str | None
    intake: Intake | None


@dataclass(frozen=True)
class AwardDate:
    role: str
    date: Date | RelativeDate
    for_all: bool
    places: tuple[str, ...]
    cycle: int | None = None  # the first year of an intake stated on the date's own line


@dataclass(frozen=True)
class Nationality:
    eligible: frozenset[str]
    excluded: frozenset[str]
    held: frozenset[str]  # a student from one of these is held, not told yes or no
    basis: str  # citizenship | residence | both | not_stated
    groups: tuple[str, ...]  # group phrases read; "CIS:beside_list" when the page lists countries


@dataclass(frozen=True)
class Condition:
    kind: str  # REQUIREMENT_KINDS, or the code candidate's kind ("language_test", "cefr", ...)
    requirement: Requirement | None  # code's parse of the span, when it has one


class _Unresolved(Exception):
    def __init__(self, qid: str) -> None:
        self.qid = qid


class _Problem(Exception):
    def __init__(self, problem: str, detail: str) -> None:
        self.problem, self.detail = problem, detail


def _failed(error: _Unresolved | _Problem) -> Parsed:
    if isinstance(error, _Unresolved):
        return Parsed(problem="unresolved_split", detail=error.qid)
    return Parsed(problem=error.problem, detail=error.detail)


def _safe(build: Callable[[], Parsed]) -> Parsed:
    try:
        return build()
    except (_Unresolved, _Problem) as error:
        return _failed(error)


class _Answers:
    def __init__(self, decisions: Iterable[Decision]) -> None:
        self.by = {d.question: d for d in decisions}

    def get(self, qid: str, used: list[Decision]) -> str:
        """The decided value; raises when it is unresolved or was never answered."""
        decision = self.by.get(qid)
        if decision is None or decision.value is None:
            raise _Unresolved(qid)
        used.append(decision)
        return decision.value

    def yes(self, qid: str, used: list[Decision]) -> bool:
        return self.get(qid, used) == "yes"

    def opt(self, qid: str, used: list[Decision]) -> str | None:
        """Like get, but a question that was not asked (a conditional one) is None."""
        return self.get(qid, used) if qid in self.by else None


def _quote(found: Found[Any]) -> Quote:
    part = "header" if found.from_header else "text"
    return Quote(found.value.text, f"L{found.line}.{part}")


def _place_code(c: Candidates, key: str) -> str | None:
    place = c.places[key].value
    return place.code if place.code else group_of(place.text)


def _benefits(a: _Answers, c: Candidates, source: str) -> tuple[Parsed, Parsed]:
    benefits: list[Value] = []
    fees: list[Value] = []
    converted = {base: c.amounts[conv].value for conv, base in c.conversion_of.items()}
    for key, found in c.amounts.items():
        if key in c.conversion_of:
            continue
        used: list[Decision] = []
        pays = a.get(f"pays_{key}", used)
        if pays not in BENEFIT_PAYS | FEE_PAYS:
            continue
        if found.value.low is None:
            raise _Problem("unparseable_value", key)
        level = a.opt(f"level_{key}", used)
        intake = a.opt(f"intake_{key}", used)
        benefit = Benefit(
            amount=found.value, conversion=converted.get(key), pays=pays,
            bound=found.value.bound or _present(a.opt(f"bound_{key}", used)),
            covers=frozenset(x for x in COVERS if a.yes(f"covers_{x}_{key}", used)),
            frequency=a.get(f"frequency_{key}", used),
            duration=a.get(f"duration_{key}", used),
            for_whom=frozenset(x for x in BENEFICIARIES if a.yes(f"for_{x}_{key}", used)),
            for_all=a.yes(f"for_all_{key}", used),
            places=tuple(code for p in sorted(_keys_on(c, found.line))
                         if a.yes(f"for_{p}_{key}", used) and (code := _place_code(c, p))),
            level=("all" if level == "all_levels" else
                   c.levels[level].value.level if level in c.levels else None),
            intake=c.intakes[intake].value if intake in c.intakes else None,
        )
        (benefits if pays in BENEFIT_PAYS else fees).append(
            Value(benefit, _quote(found), source, tuple(used)))
    return Parsed(tuple(benefits)), Parsed(tuple(fees))


def _keys_on(c: Candidates, line: int) -> set[str]:
    return {key for key, found in c.places.items() if found.line == line}


def _present(value: str | None) -> str | None:
    return None if value in ABSENT else value


def _resolved(date: Date, order: str | None, key: str) -> Date:
    """The date with its day and month in place. An impossible date never arrives: the slice-1
    finder keeps only real calendar dates ("30 February 2027" is read as "February 2027"), and
    an ambiguous order is two numbers of 12 or less, real either way."""
    if date.order_ambiguous:
        if order == "day_first":
            date = replace(date, day=date.first, month=date.second, end_day=date.end_first,
                           end_month=date.end_second, order_ambiguous=False)
        elif order == "month_first":
            date = replace(date, month=date.first, day=date.second, end_month=date.end_first,
                           end_day=date.end_second, order_ambiguous=False)
        else:
            raise _Problem("unparseable_value", key)
    if date.year is None:
        raise _Problem("unparseable_value", key)
    return date


def _dates(a: _Answers, c: Candidates, source: str) -> Parsed:
    out: list[Value] = []
    every: list[tuple[str, Found[Any]]] = [*c.dates.items(), *c.relative_dates.items()]
    for key, found in every:
        used: list[Decision] = []
        role = a.get(f"role_{key}", used)
        if role not in SHOWN_ROLES:
            continue
        value: Date | RelativeDate = found.value
        if isinstance(value, Date):
            value = _resolved(value, a.opt(f"order_{key}", used), key)
        places = tuple(code for p in sorted(_keys_on(c, found.line))
                       if a.yes(f"for_{p}_{key}", used) and (code := _place_code(c, p)))
        cycle = min((i.value.start_year for i in c.intakes.values() if i.line == found.line),
                    default=None)
        out.append(Value(AwardDate(role, value, a.yes(f"for_all_{key}", used), places, cycle),
                         _quote(found), source, tuple(used)))
    return Parsed(tuple(out))


def page_date(decisions: Iterable[Decision], c: Candidates, default: dt.date) -> dt.date:
    """The page's own published/updated date when the readers found one; else `default`."""
    by = {d.question: d.value for d in decisions}
    found = [f.value for k, f in c.dates.items()
             if by.get(f"role_{k}") == "page_published_or_updated" and f.value.year
             and f.value.month and not f.value.order_ambiguous]
    days = [dt.date(d.year, d.month, d.day or 1) for d in found if d.year and d.month]
    return max(days, default=default)


def _level(a: _Answers, funder_country: str, lang: str, source: str) -> Parsed:
    used: list[Decision] = []
    value = a.get("target_level", used)
    if value in ABSENT:
        return Parsed()
    quote = used[0].quote
    if value == "year_of_study":  # the funder's country decides; unknown is held (decision 5)
        mapped = level_of_year(quote.text, funder_country, lang) if quote else None
        if mapped is None:
            return Parsed(problem="unparseable_value", detail="target_level")
        value = mapped
    return Parsed((Value(value, quote, source, tuple(used)),))


def _nationality(a: _Answers, c: Candidates, on: dt.date, source: str) -> Parsed:
    used: list[Decision] = []
    eligible_keys = [k for k in c.places if a.yes(f"eligible_{k}", used)]
    excluded_keys = [k for k in c.places if a.yes(f"excluded_{k}", used)]
    both = set(eligible_keys) & set(excluded_keys)  # contradicts itself: not stated (§5 step 6)
    eligible_keys = [k for k in eligible_keys if k not in both]
    excluded_keys = [k for k in excluded_keys if k not in both]
    elsewhere = a.yes("eligibility_elsewhere", used)
    internationals = a.yes("internationals", used)
    basis = a.get("place_basis", used)
    named = any(c.places[k].value.kind == "country" for k in eligible_keys)
    says_dac = any(group_of(f.value.text) == "DAC" for f in c.places.values()
                   if f.value.kind == "unknown_group")
    eligible: set[str] = set()
    excluded: set[str] = set()
    held: set[str] = set()
    groups: list[str] = []
    hunt = elsewhere
    for key, into in [*((k, "eligible") for k in eligible_keys),
                      *((k, "excluded") for k in excluded_keys)]:
        place = c.places[key].value
        if place.kind == "country" and place.code:
            (eligible if into == "eligible" else excluded).add(place.code)
            continue
        group = place.code or group_of(place.text)
        if group == "INTERNATIONAL":
            hunt = hunt or into == "eligible"
            continue
        if group is None:
            raise _Problem("unparseable_value", key)
        if into == "eligible" and named and place.kind != "region":
            groups.append(f"{group}:beside_list")  # the funder's own list comes first
            continue
        sole = a.yes(f"sole_{key}", used) if f"sole_{key}" in a.by else False
        expansion = expand(group, on=on, page_says_dac=says_dac, sole_criterion=sole)
        if expansion is None:
            raise _Problem("unparseable_value", key)
        if expansion.everyone_held:
            raise _Problem("held_country_group", group)
        groups.append(group)
        if into == "eligible":
            eligible |= expansion.eligible
            held |= expansion.held
        else:
            excluded |= expansion.eligible
    if internationals and not eligible and not held:
        hunt = True
    if hunt:
        raise _Problem("needs_hunt", "eligibility_elsewhere" if elsewhere else "internationals")
    if not (eligible or excluded or held):
        return Parsed()
    quote = next((d.quote for d in used if d.quote is not None and d.value == "yes"), None)
    value = Nationality(frozenset(eligible - excluded), frozenset(excluded),
                        frozenset(held - eligible - excluded), basis, tuple(groups))
    return Parsed((Value(value, quote, source, tuple(used)),))


def _requirements(a: _Answers, c: Candidates, proposed: Mapping[str, tuple[Quote, ...]],
                  source: str) -> Parsed:
    out: list[Value] = []
    for key, found in c.requirements.items():
        used: list[Decision] = []
        if a.yes(f"requires_{key}", used):
            out.append(Value(Condition(found.value.kind, found.value), _quote(found), source,
                             tuple(used)))
    for n, quote in enumerate(proposed.get("requirements", ())):
        used = []
        kind = a.opt(f"kind_{n}", used)
        if kind is None or kind in ABSENT:
            continue
        parsed = next(iter(find_requirements(quote.text)), None)
        out.append(Value(Condition(kind, parsed), quote, source, tuple(used)))
    return Parsed(tuple(out))


def _durations(a: _Answers, c: Candidates, source: str) -> Parsed:
    out = []
    for key, found in c.durations.items():
        used: list[Decision] = []
        if a.yes(f"funds_{key}", used):
            out.append(Value(found.value, _quote(found), source, tuple(used)))
    return Parsed(tuple(out))


def _label(a: _Answers, qid: str, source: str) -> Parsed:
    used: list[Decision] = []
    value = a.get(qid, used)
    if value in ABSENT:
        return Parsed()
    return Parsed((Value(value, used[0].quote, source, tuple(used)),))


def _set(a: _Answers, prefix: str, items: tuple[str, ...], source: str) -> Parsed:
    used: list[Decision] = []
    found = frozenset(x for x in items if a.yes(f"{prefix}_{x}", used))
    if not found:
        return Parsed()
    quote = next((d.quote for d in used if d.value == "yes"), None)
    return Parsed((Value(found, quote, source, tuple(used)),))


def _funding_period(a: _Answers, c: Candidates, source: str) -> Parsed:
    used: list[Decision] = []
    if not a.yes("funding_period", used):
        return Parsed()
    if not c.intakes:
        return Parsed(problem="unparseable_value", detail="funding_period")
    return Parsed(tuple(Value(f.value, _quote(f), source, tuple(used))
                        for f in c.intakes.values()))


def parse_award(decisions: Iterable[Decision], c: Candidates,
                proposed: Mapping[str, tuple[Quote, ...]], *, source: str,
                funder_country: str, lang: str, today: dt.date) -> dict[str, Parsed]:
    """Every field of one award. A field's problem stops that field only: the others still
    parse, so the card can say exactly what is held and why. `funder_country` ("" unknown)
    decides what a year of study means (decision 5)."""
    decisions = tuple(decisions)
    a = _Answers(decisions)
    on = page_date(decisions, c, today)
    fields: dict[str, Parsed] = {}
    try:
        fields["benefits"], fields["fees"] = _benefits(a, c, source)
    except (_Unresolved, _Problem) as error:
        fields["benefits"] = fields["fees"] = _failed(error)
    fields["dates"] = _safe(partial(_dates, a, c, source))
    fields["target_level"] = _safe(partial(_level, a, funder_country, lang, source))
    fields["nationality"] = _safe(partial(_nationality, a, c, on, source))
    fields["requirements"] = _safe(partial(_requirements, a, c, proposed, source))
    fields["funding_duration"] = _safe(partial(_durations, a, c, source))
    fields["funding_period"] = _safe(partial(_funding_period, a, c, source))
    for name in (*LABELS, *FLAGS):
        fields[name] = _safe(partial(_label, a, name, source))
    route = fields["route"].values
    if not route or route[0].value == "considered_with_admission":
        fields["route_order"] = Parsed()  # asked always, read only when it applies (§5.2)
    fields["extras"] = _safe(partial(_set, a, "extra", EXTRAS, source))
    fields["obligations"] = _safe(partial(_set, a, "obligation", OBLIGATIONS, source))
    return fields
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_parse.py -q`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/research/card_funding/parse.py tests/research/card_funding/test_parse.py
git commit -m "feat(research): parse funding decisions into typed card values by code"
```

---

### Task 6: The typed card

**Files:**
- Create: `apps/research/card_funding/card.py`
- Test: `tests/research/card_funding/test_card.py`

**Why these shapes:** "Per award, every field is shown, held (with a reason) or not stated, and
each value carries its quote and source" (the brief), with the hold reasons of decision 12 and
the one-page conflict rule of decision 13. The card is track-shaped (§3.2, decision 17). A
partly held country group is a `Hold` with countries, so a student from elsewhere still sees the
award.

**Interfaces:**
- Consumes: `Call`, `Quote`; `parse.AwardDate`, `Nationality`, `Parsed`, `Value`.
- Produces: `HOLD_REASONS`; `FIELDS`; `SINGLE_ROLES`; `Field(name, state, values=(), hold="",
  detail="")`; `Hold(reason, field, detail="", countries=frozenset())`;
  `AwardCard(name, name_quote, fields, holds)`; `Track(name, awards)`;
  `Card(program_id, source_url, lang, outcome, tracks=(), calls=(), unread_lines=0, notes=(),
  cost_usd=0.0, unpriced_calls=0, seconds=0.0)`; `award_card(name, name_quote, parsed) ->
  AwardCard`; `unread_award(name, name_quote, reason, detail="") -> AwardCard`.

- [ ] **Step 1: Write the failing tests**

`tests/research/card_funding/test_card.py`:

```python
from apps.research.candidates import Date
from apps.research.card_engine import Quote
from apps.research.card_funding.card import (
    FIELDS,
    HOLD_REASONS,
    Hold,
    award_card,
    unread_award,
)
from apps.research.card_funding.parse import AwardDate, Nationality, Parsed, Value

URL = "https://example.edu.az/scholarships"


def _date(role, day, cycle=None, places=()):
    date = Date(f"{day} May 2027", 0, 10, 2027, 5, day)
    return Value(AwardDate(role, date, False, places, cycle), Quote(f"{day} May 2027", "L1.text"),
                 URL, ())


def test_every_field_is_shown_held_or_not_stated():
    card = award_card("Rector's Scholarship", Quote("Rector's Scholarship", "L0.text"), {
        "target_level": Parsed((Value("master", Quote("master", "L2.text"), URL, ()),)),
        "benefits": Parsed(problem="unresolved_split", detail="pays_m1"),
    })
    assert tuple(card.fields) == FIELDS
    assert {f.state for f in card.fields.values()} <= {"shown", "held", "not_stated"}
    assert card.fields["target_level"].state == "shown"
    assert card.fields["benefits"].state == "held" and card.fields["dates"].state == "not_stated"
    assert card.holds == (Hold("unresolved_split", "benefits", "pays_m1"),)
    assert {h.reason for h in card.holds} <= set(HOLD_REASONS)


def test_two_deadlines_of_one_cycle_or_of_no_cycle_conflict():
    dates = Parsed((_date("application_deadline", 15), _date("application_deadline", 20)))
    card = award_card("A", None, {"dates": dates})
    assert (card.fields["dates"].state, card.fields["dates"].hold, card.fields["dates"].detail) == (
        "held", "conflicting_values", "application_deadline")
    dates = Parsed((_date("application_deadline", 15, 2026),
                    _date("application_deadline", 20, 2026)))
    assert award_card("A", None, {"dates": dates}).fields["dates"].hold == "conflicting_values"


def test_the_newest_stated_cycle_wins_and_place_dates_never_conflict():
    old, new = _date("application_deadline", 15, 2026), _date("application_deadline", 20, 2027)
    for_az = _date("application_deadline", 1, places=("AZ",))
    card = award_card("A", None, {"dates": Parsed((old, new, for_az))})
    assert card.fields["dates"].state == "shown"
    assert set(card.fields["dates"].values) == {new, for_az}
    same = Parsed((_date("application_deadline", 15), _date("application_deadline", 15)))
    assert len(award_card("A", None, {"dates": same}).fields["dates"].values) == 1


def test_a_partly_held_group_is_shown_and_held_for_its_countries_only():
    nationality = Nationality(frozenset({"AZ", "KZ"}), frozenset(), frozenset({"UA"}),
                              "citizenship", ("CIS",))
    card = award_card("A", None, {"nationality": Parsed((Value(nationality, None, URL, ()),))})
    assert card.fields["nationality"].state == "shown"
    assert card.holds == (Hold("held_country_group", "nationality", "CIS", frozenset({"UA"})),)


def test_an_unread_award_holds_every_field_for_one_reason():
    card = unread_award("A", None, "deadline")
    assert {(f.state, f.hold) for f in card.fields.values()} == {("held", "deadline")}
    assert card.holds == (Hold("deadline", "*", ""),)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_card.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.card_funding.card'`

- [ ] **Step 3: Implement**

`apps/research/card_funding/card.py`:

```python
"""The typed card: per award, every field shown, held with a reason, or not stated (§5 step 6-7).

A field is `not_stated` only when code found nothing for it, or the readers agreed the page states
nothing -- code-certain or agreed absence, never doubt. Anything short of a value both readers
agreed on (or the decider chose) and code could read is `held`, with the reason the operator's
hold queue sorts by (§5.5 step 6). A held field hides its award from every student until the
operator fixes the wording or a data row and re-runs; slice 3 stores and serves this.

The card is track-shaped (§3.2): a programme carries one or more tracks, each with its awards. A
single page read here is one track (""); the EMJM programme reader fills the others.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from apps.research.card_engine import Call, Quote

from .parse import AwardDate, Nationality, Parsed, Value

#: Why a field or an award is held. The first five arise from reading; the last three from the
#: read itself (a section never read, the on-demand deadline, the page's dollar stop).
HOLD_REASONS = ("unresolved_split", "held_country_group", "conflicting_values",
                "unparseable_value", "needs_hunt", "not_read", "deadline", "page_budget")
#: Every field a funding card has, in display order.
FIELDS = ("benefits", "fees", "dates", "target_level", "nationality", "requirements",
          "funding_duration", "funding_period", "money_form", "holder_kind", "route",
          "route_order", "tuition_level", "living_level", "extras", "obligations", "apply_here",
          "apply_elsewhere", "institution_wide", "renewal_condition", "discontinued",
          "window_closed")
#: Date roles an award has one of per cycle; two different values on one page are a conflict.
SINGLE_ROLES = frozenset({"application_deadline", "application_opening", "fee_deadline"})

State = Literal["shown", "held", "not_stated"]


@dataclass(frozen=True)
class Field:
    name: str
    state: State
    values: tuple[Value, ...] = ()
    hold: str = ""  # a HOLD_REASONS member when held
    detail: str = ""  # a candidate key, question id or group key; never page text


@dataclass(frozen=True)
class Hold:
    reason: str
    field: str
    detail: str = ""
    #: Empty: held for every student. Otherwise held only for a student from one of these.
    countries: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AwardCard:
    name: str
    name_quote: Quote | None
    fields: Mapping[str, Field]
    holds: tuple[Hold, ...]


@dataclass(frozen=True)
class Track:
    name: str  # "" for a programme with one track
    awards: tuple[AwardCard, ...]


@dataclass(frozen=True)
class Card:
    program_id: UUID | None
    source_url: str
    lang: str
    #: "read", "fetch:<Outcome>", "quarantined", "unscreened:<reason>", "deadline"
    outcome: str
    tracks: tuple[Track, ...] = ()
    calls: tuple[Call, ...] = ()
    unread_lines: int = 0  # lines above the first award, which no award holds
    notes: tuple[tuple[str, float], ...] = ()  # D8's review band, carried to whatever shows this
    cost_usd: float = 0.0
    unpriced_calls: int = 0
    seconds: float = 0.0


def _date(value: Value) -> AwardDate:
    return cast(AwardDate, value.value)


def _date_conflict(values: tuple[Value, ...]) -> tuple[tuple[Value, ...], str]:
    """Keep the newest stated cycle of each single-valued role; two different dates with the
    same cycle, or with no cycle stated, are a conflict (§5.5 step 4's cycle rule, on one page).
    A date stated for named places only is that place's, never a conflict."""
    kept = [v for v in values if _date(v).role not in SINGLE_ROLES or _date(v).places]
    for role in sorted(SINGLE_ROLES):
        same = [v for v in values if _date(v).role == role and not _date(v).places]
        cycles = [_date(v).cycle for v in same]
        newest = max((c for c in cycles if c is not None), default=None)
        top = same if len({_date(v).date for v in same}) <= 1 else [
            v for v in same if _date(v).cycle == newest]
        if len({_date(v).date for v in top}) > 1 or (top is not same and None in cycles):
            return values, role
        kept += top[:1]
    return tuple(kept), ""


def _field(name: str, parsed: Parsed) -> Field:
    if parsed.problem:
        return Field(name, "held", hold=parsed.problem, detail=parsed.detail)
    if not parsed.values:
        return Field(name, "not_stated")
    if name == "dates":
        values, conflict = _date_conflict(parsed.values)
        if conflict:
            return Field(name, "held", parsed.values, "conflicting_values", conflict)
        return Field(name, "shown", values)
    return Field(name, "shown", parsed.values)


def award_card(name: str, name_quote: Quote | None, parsed: Mapping[str, Parsed]) -> AwardCard:
    fields = {key: _field(key, parsed.get(key, Parsed())) for key in FIELDS}
    holds = [Hold(f.hold, f.name, f.detail) for f in fields.values() if f.state == "held"]
    nationality = fields["nationality"]
    if nationality.state == "shown":
        value = nationality.values[0].value
        assert isinstance(value, Nationality)
        if value.held:
            holds.append(Hold("held_country_group", "nationality", ",".join(value.groups),
                              value.held))
    return AwardCard(name, name_quote, fields, tuple(holds))


def unread_award(name: str, name_quote: Quote | None, reason: str, detail: str = "") -> AwardCard:
    """An award whose section was never fully read: every field held for one reason."""
    fields = {key: Field(key, "held", hold=reason, detail=detail) for key in FIELDS}
    return AwardCard(name, name_quote, fields, (Hold(reason, "*", detail),))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_card.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/research/card_funding/card.py tests/research/card_funding/test_card.py
git commit -m "feat(research): the typed, track-shaped funding card with hold reasons"
```

---

### Task 7: The single-page entry, its three shared-code seams, and the full gates

**Files:**
- Create: `apps/research/card_funding/entry.py`
- Test: `tests/research/card_funding/test_entry.py`
- Modify: `apps/documents/letter_terms.py` (`_STOPWORDS` gains `az` and `kk`; `detect_language`)
- Modify: `apps/research/fetch/__init__.py` (`fetch_page`, `_call`), `apps/research/fetch/firecrawl.py`
  (`_post`, `scrape`), `apps/research/fetch/scrapedo.py` (`Get`, `_get`, `scrape`)
- Modify: `apps/research/decisions.py` (`ask`, `_typesafe_client`),
  `apps/research/card_engine/screen.py` (`Screen.reason`, `screen`)
- Test (append one test each): `tests/documents/test_letter_terms.py`,
  `tests/research/test_fetch_ladder.py`, `tests/research/test_fetch_firecrawl.py`,
  `tests/research/test_fetch_scrapedo.py`, `tests/research/test_decisions.py`,
  `tests/research/card_engine/test_screen.py`

**Why these shapes:** §3.3 step 4: "It is one of the reads a student waits on, so it runs
synchronously at standard price and must finish in under 30 s." One `Program`, one URL: fetch
through the vendor ladder pinned to the URL's origin, `readable_text` with the funding terms,
the language by code (decision 15), D8 over the whole page, the heading judgement, then every
batch of every award in parallel through `Guard` (decision 14), then parse and card. The guard
wraps the real transport, so the engine's own key check is skipped and `read_page` calls
`require_keys` first, before the fetch is paid for (2a carry). `limit` is the caller's: a
student's typed programme passes `readers.tenant_limit(tenant_id)`, the sweep `run_limit`.
`funder_country` is decision 5's: `None` reads `Program.country_code`.

The 30 s covers the fetch and D8 as well (owner, 2026-10-13; decision 14). Neither took a
timeout, so each gets a keyword whose default is today's behaviour — every existing caller, and
every existing provider stub, is called exactly as before (the vendors are handed `timeout_s`
only when it is given). The detector learns `az` and `kk` here because this task is its first
caller that needs them (decision 15).

**Interfaces:**
- Consumes: everything above (`parse_award(..., funder_country=...)`, `unread_award`, `Track`,
  `Card`, `Page`, `AwardNames`, `Funding`, `batches`, …); `card_engine.engine.read`, `Reading`,
  `Transport`; `readers.stack`, `require_keys`, `openrouter`, `anthropic_reader`,
  `READ_TIMEOUT_S`, `Attempt`, `Prompt`, `ReaderSpec`, `Stack`; `screen.screen`, `Screen`,
  `ScreenLimited`; `fetch.fetch_page`, `fetch.types.Outcome`; `reader.readable_text`;
  `funding_terms.funding_terms`; `documents.letter_terms.detect_language`;
  `egress.fetch_json_api`; `extraction.MessagesAPI`.
- Produces: `DEADLINE_S = 30.0`, `PAGE_BUDGET_USD = 0.25`, `MIN_CALL_S = 2.0`, `WORKERS = 8`;
  `Guard(deadline, budget_usd, *, inner=None, clock=time.monotonic)` (a `Transport` with
  `spent`, `unpriced`, `tripped`); `read_page(program, url, *, limit: Limit,
  funder_country: str | None = None, today=None, readers=None, transport=None,
  fetch=fetch_page, screen_page=screen, deadline_s=DEADLINE_S, budget_usd=PAGE_BUDGET_USD) ->
  Card`; `fetch` is called `fetch(url, purpose="read", require_origin=url, timeout_s=<left>)`
  and `screen_page` `screen_page(section, limit=limit, timeout_s=<left>)`. `Card.outcome` is
  `read`, `deadline`, `fetch:<Outcome>`, `quarantined` or `unscreened:<reason>`.
- Seams (each default = today): `fetch_page(url, *, purpose, tag, require_origin, budget,
  profile, providers, timeout_s: float | None = None) -> FetchedPage` (a spent deadline returns
  `Outcome.UNREACHABLE`, reason `deadline`; a ladder that fails every rung under a deadline
  returns its `BLOCKED` or `UNREACHABLE`, reason `deadline`, instead of trying the archive); `firecrawl.scrape(..., timeout_s: float | None
  = None)` and `firecrawl._post(..., total_s: float | None = None)`; `scrapedo.scrape(...,
  timeout_s: float | None = None)` and `scrapedo._get(url, total_s: float | None = None)`;
  `screen(page, *, limit, budget=None, record=True, client=None, timeout_s: float | None =
  None) -> Screen` (`Screen.reason` gains `deadline`); `decisions.ask(..., timeout_s: float |
  None = None)` and `decisions._typesafe_client(..., timeout_s: float | None = None)`;
  `detect_language` may return `az` or `kk`.

- [ ] **Step 1: Write the failing tests**

`tests/research/card_funding/test_entry.py`:

```python
import datetime as dt
import time
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.research.card_engine import Limit
from apps.research.card_engine.readers import Attempt, ReadersNotConfigured, stack
from apps.research.card_engine.screen import Screen
from apps.research.card_funding import entry
from apps.research.card_funding.card import Hold
from apps.research.card_funding.entry import Guard, read_page
from apps.research.fetch.types import FetchedPage, Outcome

from .oracle import Oracle

URL = "https://beu.edu.az/scholarships"
HTML = b"""<html lang="de"><head><title>Scholarships</title></head><body><main>
<h1>Scholarships at Baku Engineering University</h1>
<p>The university offers the following scholarships for the academic year.</p>
<h2>Rector's Scholarship</h2>
<p>Monthly stipend of AZN 300 for master students.</p>
<p>Applications close on 15 May 2027.</p>
<h2>Merit Award</h2>
<p>Tuition waiver of 50% for master students from Azerbaijan.</p>
</main></body></html>"""
ANSWERS = {
    "award_L1": ("yes", "Rector's Scholarship"),
    "award_L2": ("yes", "Merit Award"),
    "pays_m1": ("paid_to_student", "Monthly stipend of AZN 300"),
    "frequency_m1": ("monthly", "Monthly stipend"),
    "bound_m1": ("exact", "AZN 300"),
    "for_student_m1": ("yes", "stipend"),
    "role_d1": ("application_deadline", "Applications close on 15 May 2027."),
    "target_level": ("master", "master students"),
    "tuition_level": ("partial", "Tuition waiver of 50%"),
    "eligible_p1": ("yes", "students from Azerbaijan"),
    "place_basis": ("not_stated", ""),
}
PROGRAM = SimpleNamespace(id=uuid4(), country_code="AZ")


@pytest.fixture(autouse=True)
def _keys(settings, monkeypatch):
    settings.OPENROUTER_API_KEY = "test-openrouter-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")


def _fetch(outcome=Outcome.FETCHED, body=HTML):
    calls = []

    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return FetchedPage(final_url=url, redirects=(), content_type="text/html", body=body,
                           fetched_via="FIRECRAWL", outcome=outcome)
    fetch.calls = calls
    return fetch


def _clear(section, *, limit, timeout_s=None):
    return Screen("clear", section.texts())


def _no_screen(section, **kwargs):  # pragma: no cover - the assertion is the point
    raise AssertionError("D8 must not be asked")


def _read(oracle, **kwargs):
    kwargs.setdefault("fetch", _fetch())
    kwargs.setdefault("screen_page", _clear)
    return read_page(PROGRAM, URL, limit=Limit("card-funding-test", uuid4(), 500, 3600),
                     today=dt.date(2026, 10, 13), transport=oracle, **kwargs)


def test_a_page_becomes_a_track_of_typed_award_cards():
    oracle = Oracle(ANSWERS)
    fetch = _fetch()
    card = _read(oracle, fetch=fetch)
    [(url, kwargs)] = fetch.calls
    assert url == URL and 0 < kwargs.pop("timeout_s") <= entry.DEADLINE_S
    assert kwargs == {"purpose": "read", "require_origin": URL}
    assert (card.outcome, card.lang, card.unread_lines) == ("read", "en", 2)  # not <html lang>
    [track] = card.tracks
    rector, merit = track.awards
    assert (rector.name, merit.name) == ("Rector's Scholarship", "Merit Award")
    [stipend] = rector.fields["benefits"].values
    assert (stipend.value.amount.low, stipend.value.frequency) == (Decimal("300"), "monthly")
    assert stipend.source == URL
    [deadline] = rector.fields["dates"].values
    assert (deadline.value.role, deadline.value.date.day) == ("application_deadline", 15)
    assert rector.fields["target_level"].values[0].value == "master"
    assert rector.fields["nationality"].state == "not_stated"
    assert merit.fields["tuition_level"].values[0].value == "partial"
    # "Tuition waiver of 50%" is printed only under Merit: Rector's card never borrows it
    assert rector.fields["tuition_level"].state == "not_stated"
    assert merit.fields["nationality"].values[0].value.eligible == {"AZ"}
    assert merit.fields["benefits"].state == "not_stated"
    assert rector.holds == () and merit.holds == ()
    assert card.cost_usd == pytest.approx(sum(c.cost_usd for c in card.calls))
    assert {c.reader for c in card.calls} == {"deepseek", "luna"}  # nothing split


def test_a_refused_fetch_or_a_quarantined_page_reads_nothing():
    oracle = Oracle(ANSWERS)
    card = _read(oracle, fetch=_fetch(Outcome.BLOCKED))
    assert (card.outcome, card.tracks, oracle.asked) == ("fetch:BLOCKED", (), [])

    def hostile(section, *, limit, timeout_s=None):
        return Screen("quarantined", section.texts(), (("ignore all rules", 0.9),))
    card = _read(oracle, screen_page=hostile)
    assert (card.outcome, card.tracks, oracle.asked) == ("quarantined", (), [])


def test_a_missing_key_is_refused_before_anything_is_fetched(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    fetch = _fetch()
    with pytest.raises(ReadersNotConfigured):
        _read(Oracle(ANSWERS), fetch=fetch, readers=stack())
    assert fetch.calls == []


def test_past_the_deadline_no_call_starts_and_every_award_is_held():
    oracle = Oracle(ANSWERS)
    card = _read(oracle, deadline_s=0.0, screen_page=_no_screen)
    assert oracle.asked == [] and card.outcome == "deadline"
    [award] = card.tracks[0].awards  # no heading judgement: the page is one award
    assert {(f.state, f.hold) for f in award.fields.values()} == {("held", "deadline")}


def test_a_slow_fetch_or_a_slow_screen_ends_the_read_at_the_deadline():
    """Owner, 2026-10-13: the fetch and D8 are inside the 30 s. Each is handed the time left,
    and the clock is read when each returns."""
    deadline_s = entry.MIN_CALL_S + 0.5
    seen = []
    fetch = _fetch()

    def slow_fetch(url, **kwargs):
        seen.append(("fetch", kwargs["timeout_s"]))
        time.sleep(0.6)
        return fetch(url, **kwargs)

    def slow_screen(section, *, limit, timeout_s):
        seen.append(("screen", timeout_s))
        time.sleep(0.6)
        return Screen("clear", section.texts())

    for slow in ({"fetch": slow_fetch}, {"screen_page": slow_screen}):
        oracle = Oracle(ANSWERS)
        card = _read(oracle, deadline_s=deadline_s, **slow)
        assert card.outcome == "deadline" and oracle.asked == []
        [award] = card.tracks[0].awards
        assert award.holds == (Hold("deadline", "*", ""),)
    assert [what for what, _ in seen] == ["fetch", "screen"]
    assert all(0 < left <= deadline_s for _, left in seen)


def test_the_funders_country_decides_a_year_of_study_and_none_is_the_programmes():
    html = HTML.replace(b"for master students.", b"for 4th year students.")
    answers = {**ANSWERS, "target_level": ("year_of_study", "4th year students")}
    levels = {}
    for funder_country in (None, "DE", ""):
        card = _read(Oracle(answers), fetch=_fetch(body=html), funder_country=funder_country)
        level = card.tracks[0].awards[0].fields["target_level"]
        levels[funder_country] = (level.state, level.values[0].value if level.values
                                  else level.hold)
    assert levels == {None: ("shown", "bachelor"),  # the programme's AZ: a 4-year bachelor's
                      "DE": ("held", "unparseable_value"),  # a German 4th year may be a master's
                      "": ("held", "unparseable_value")}  # an unknown funder is never guessed


def test_the_dollar_stop_holds_what_it_could_not_pay_for():
    oracle = Oracle(ANSWERS, cost=0.2)
    card = _read(oracle, budget_usd=0.25)
    assert card.cost_usd == pytest.approx(0.4)  # the heading pair, started before the stop
    assert all(h.reason == "page_budget" for a in card.tracks[0].awards for h in a.holds)
    assert card.tracks[0].awards


def test_the_guard_counts_unpriced_calls_and_bounds_each_wait(settings, monkeypatch):
    now = [0.0]
    guard = Guard(10.0, 0.25, inner=lambda spec, prompt: Attempt(None, "off_schema", None, 1.0),
                  clock=lambda: now[0])
    spec = stack().pair[0]
    assert guard(spec, None).reason == "off_schema" and guard.unpriced == 1
    now[0] = 8.5  # 1.5 s left: under MIN_CALL_S, so no call starts
    assert guard(spec, None).reason == "failed:deadline" and guard.tripped == "deadline"
    seen = {}

    def post(url, **kwargs):
        seen.update(kwargs)
        raise TimeoutError
    monkeypatch.setattr(entry, "fetch_json_api", post)
    entry._bounded(spec, SimpleNamespace(system="s", data="d", ask="a"), left=4.0)
    assert seen["read_timeout"] == 4.0


def test_an_award_the_rate_limit_refused_is_held_not_read():
    oracle = Oracle(ANSWERS)
    card = read_page(PROGRAM, URL, limit=Limit("card-funding-test", uuid4(), 2, 3600),
                     today=dt.date(2026, 10, 13), transport=oracle, fetch=_fetch(),
                     screen_page=_clear)
    awards = card.tracks[0].awards
    assert [a.name for a in awards] == ["Rector's Scholarship", "Merit Award"]
    assert {(h.reason, h.detail) for a in awards for h in a.holds} == {("not_read",
                                                                        "ReaderLimited")}
    assert len(card.calls) == 2  # the heading pair it could pay for, kept
```

Append to `tests/documents/test_letter_terms.py`:

```python
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Təqaüd magistr tələbələri üçün nəzərdə tutulub və müraciətlər 15 mayadək qəbul "
         "edilir. Namizədlər həm də IELTS sertifikatı təqdim etməlidir.", "az"),
        ("Бұл стипендия магистранттар үшін арналған, өтінімдер 15 мамырға дейін "
         "қабылданады. Үміткерлер IELTS сертификатын осы портал арқылы ұсынады.", "kk"),
        ("Bu burs yüksek lisans öğrencileri için verilir ve başvurular 15 Mayıs tarihine "
         "kadar kabul edilir. Adaylar ayrıca bir IELTS belgesi sunmalıdır.", "tr"),
        ("Эта стипендия предназначена для студентов магистратуры, и заявки принимаются до "
         "15 мая. Кандидаты подают сертификат IELTS по почте.", "ru"),
    ],
)
def test_azerbaijani_and_kazakh_are_told_apart_from_turkish_and_russian(text, expected) -> None:
    """Owner, 2026-10-13: az and kk are detected now, and their neighbours are not taken for
    them -- the shared Turkic and Cyrillic words are kept out of the az and kk rows."""
    assert detect_language(text) == expected
```

Append to `tests/research/test_fetch_ladder.py`:

```python
def test_a_deadline_hands_each_rung_the_time_left_and_ends_the_ladder_at_it() -> None:
    """The single-page funding read waits on this ladder (owner, 2026-10-13: 30 s in all)."""
    seen = []

    def firecrawl(url, *, api_key, tag=None, actions=False, profile=None, request_id=None,
                  screenshot=False, timeout_s=None):
        seen.append(timeout_s)
        return _page(Outcome.FETCHED)

    providers = {**_providers(), "firecrawl": firecrawl}
    page = fetch_page("https://e.test/a", providers=providers, timeout_s=20.0)
    assert page.outcome is Outcome.FETCHED and 0 < seen[0] <= 20.0

    spent = fetch_page("https://e.test/a", providers=_providers(firecrawl=_explode),
                       timeout_s=0.0)
    assert (spent.outcome, spent.reason) == (Outcome.UNREACHABLE, "deadline")
    assert FetchAttempt.objects.filter(reason="deadline").count() == 1


def test_a_deadline_never_waits_for_the_archive() -> None:
    for attempt_no in (1, 2, 3):
        FetchAttempt.objects.create(
            url="https://e.test/a", host="e.test", rung=5, vendor="NONE",
            outcome=Outcome.RETRY_SCHEDULED, attempt_no=attempt_no,
        )
    providers = {"firecrawl": _blocked, "scrapedo": _blocked, "archive": _explode}
    page = fetch_page("https://e.test/a", providers=providers, timeout_s=30.0)
    assert (page.outcome, page.reason) == (Outcome.BLOCKED, "deadline")
```

Append to `tests/research/test_fetch_firecrawl.py`:

```python
def test_a_deadline_caps_the_vendor_clock_and_the_http_wait_and_never_backs_off():
    seen = []

    def post(url, *, json_body, headers, timeout, total_s=None):
        seen.append((json_body["timeout"], timeout, total_s))
        return 429, b"{}", {}

    def sleep(seconds):  # pragma: no cover - the assertion is the point
        raise AssertionError("no back-off under a deadline")

    with pytest.raises(VendorUnavailable):
        firecrawl.scrape("https://example.test/a", api_key="k", post=post, sleep=sleep,
                         timeout_s=4.0)
    assert seen == [(4000, 4000, 4.0)]  # one call, every clock at the time left
```

Append to `tests/research/test_fetch_scrapedo.py`:

```python
def test_a_deadline_caps_scrape_dos_clock_and_the_http_wait(public_dns):
    seen = {}

    def get(url, total_s=None):
        seen["url"], seen["total_s"] = url, total_s
        return 200, b"y" * 1000, urllib3.HTTPHeaderDict(
            {"scrape.do-resolved-url": "https://example.test/a"})

    scrapedo.scrape("https://example.test/a", api_key="k", get=get, timeout_s=4.0)
    assert "timeout=4000" in seen["url"] and seen["total_s"] == 4.0
```

Append to `tests/research/test_decisions.py`:

```python
def test_a_timeout_bounds_one_jev_call_retries_included(openrouter, sdk):
    seen = sdk(_response({"q": {"type": "noul", "noul": 0.9}}))
    ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D8", record=False,
        timeout_s=4.0)
    assert seen["call"]["timeout"] == 4.0 and seen["call"]["retry"].timeout == 4.0
    ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D8", record=False)
    assert "timeout" not in seen["call"] and "retry" not in seen["call"]  # today's call
```

Append to `tests/research/card_engine/test_screen.py`:

```python
def test_a_timeout_reaches_every_d8_call_and_an_expired_one_asks_nothing(monkeypatch):
    import apps.research.card_engine.screen as screen_module

    seen = []

    def ask(state, questions, **kwargs):
        seen.append(kwargs["timeout_s"])
        return _jev({})(state, questions, model="jev", provider="typesafe")

    monkeypatch.setattr(screen_module, "ask", ask)
    assert screen(PAGE, limit=_limit(), record=False, timeout_s=5.0).status == "clear"
    assert len(seen) == 1 and 0 < seen[0] <= 5.0
    expired = screen(PAGE, limit=_limit(), record=False, timeout_s=0.0)
    assert (expired.status, expired.reason, len(seen)) == ("unscreened", "deadline", 1)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding/test_entry.py tests/documents/test_letter_terms.py tests/research/test_fetch_ladder.py tests/research/test_fetch_firecrawl.py tests/research/test_fetch_scrapedo.py tests/research/test_decisions.py tests/research/card_engine/test_screen.py -q`
Expected: FAIL — `test_entry.py` with `ImportError: cannot import name 'entry' from
'apps.research.card_funding'`; the az and kk detector cases (the tr and ru cases already pass);
and each seam test with `TypeError: ... unexpected keyword argument 'timeout_s'`.

- [ ] **Step 3: Implement**

**The detector (decision 15).**

In `apps/documents/letter_terms.py`, replace:

```python
    "tr": ("ve", "bir", "için", "ile", "bu", "olarak", "da", "veya"),
}
```

with:

```python
    "tr": ("ve", "bir", "için", "ile", "bu", "olarak", "da", "veya"),
    # Detection only (owner, 2026-10-13): no letter-terms row exists for these two, so TERMS
    # never carries them and derive.py reads them as it reads "" (`TERMS.get`). The words are
    # NLTK's stopword corpus (Azerbaijani list, nltk_data PR #100; Kazakh list, PR #52;
    # https://github.com/nltk/nltk_data/blob/gh-pages/packages/corpora/stopwords.zip, read
    # 2026-10-13; stopwords-iso has neither), chosen to share none with the tr and ru rows.
    "az": ("və", "üçün", "ilə", "də", "isə", "həm", "hər", "edir", "deyil", "qədər"),
    "kk": ("мен", "үшін", "бұл", "осы", "арқылы", "туралы", "бар", "емес", "дейін", "кейін"),
}
```

In `apps/documents/letter_terms.py`, replace:

```python
    """The page's language as a seeded two-letter code, or "" when unknown.
```

with:

```python
    """The page's language as a two-letter code -- a `TERMS` row, or a detection-only stopword
    row (az, kk) -- or "" when unknown.
```

In `apps/documents/letter_terms.py`, replace:

```python
    scores = {
        code: len(words.intersection(row.stopwords))
        for code, row in TERMS.items()
        if row.stopwords
    }
```

with:

```python
    # Every stopword row, not only the letter-term rows, so az and kk are detected without one.
    scores = {code: len(words.intersection(stop)) for code, stop in _STOPWORDS.items()}
```

**The fetch ladder and its two vendors (decision 14).**

In `apps/research/fetch/__init__.py`, replace:

```python
import zlib
from collections.abc import Callable
```

with:

```python
import time
import zlib
from collections.abc import Callable
```

In `apps/research/fetch/__init__.py`, replace:

```python
    providers: dict[str, Callable[..., FetchedPage]],
) -> FetchedPage:
    """Exactly one vendor call. The walk records every one of them, so a rung
    that escalates within a vendor (1 -> 2) is a second trip round the loop, not
    a second call hidden in here."""
    if rung in {1, 2}:
        return providers["firecrawl"](
            url, api_key=settings.FIRECRAWL_API_KEY, tag=tag, actions=rung == 2,
            profile=profile, request_id=str(uuid4()),
        )
    return providers["scrapedo"](
        url, api_key=settings.SCRAPEDO_API_KEY, rung=rung, profile=profile,
        session_id=_session_id(url),
    )
```

with:

```python
    providers: dict[str, Callable[..., FetchedPage]],
    timeout_s: float | None = None,
) -> FetchedPage:
    """Exactly one vendor call. The walk records every one of them, so a rung
    that escalates within a vendor (1 -> 2) is a second trip round the loop, not
    a second call hidden in here. `timeout_s` is handed on only when given, so a
    provider written before it is called exactly as it was."""
    bound = {} if timeout_s is None else {"timeout_s": timeout_s}
    if rung in {1, 2}:
        return providers["firecrawl"](
            url, api_key=settings.FIRECRAWL_API_KEY, tag=tag, actions=rung == 2,
            profile=profile, request_id=str(uuid4()), **bound,
        )
    return providers["scrapedo"](
        url, api_key=settings.SCRAPEDO_API_KEY, rung=rung, profile=profile,
        session_id=_session_id(url), **bound,
    )
```

In `apps/research/fetch/__init__.py`, replace:

```python
    providers: dict[str, Callable[..., FetchedPage]] | None = None,
) -> FetchedPage:
```

with:

```python
    providers: dict[str, Callable[..., FetchedPage]] | None = None,
    timeout_s: float | None = None,
) -> FetchedPage:
```

In `apps/research/fetch/__init__.py`, replace:

```python
    Engine-only: every call writes FetchAttempt/HostProfile, catalogue tables
```

with:

```python
    `timeout_s` is for a caller someone waits on (the single-page funding read,
    owner 2026-10-13: 30 s for the whole read). No rung starts once it is spent
    -- the ladder stops UNREACHABLE with reason "deadline", recorded as an
    attempt and never taught to the HostProfile, because the host was not slow,
    the caller could not wait -- each vendor call is handed the time left, and
    the archive rung (a probe and a fetch of its own) is not tried. None, the
    default, is the ladder as it was.

    Engine-only: every call writes FetchAttempt/HostProfile, catalogue tables
```

In `apps/research/fetch/__init__.py`, replace:

```python
    providers = providers or _default_providers()
    budget = budget or default_budget()
```

with:

```python
    providers = providers or _default_providers()
    budget = budget or default_budget()
    deadline = None if timeout_s is None else time.monotonic() + timeout_s
```

In `apps/research/fetch/__init__.py`, replace:

```python
        vendor = _VENDOR_BY_RUNG[rung]
        try:
            budget.check(vendor)
```

with:

```python
        left = None if deadline is None else deadline - time.monotonic()
        if left is not None and left <= 0:
            return stop(Outcome.UNREACHABLE, "deadline", rung)
        vendor = _VENDOR_BY_RUNG[rung]
        try:
            budget.check(vendor)
```

In `apps/research/fetch/__init__.py`, replace:

```python
            page = _call(rung, url, tag=tag, profile=profile, providers=providers)
```

with:

```python
            page = _call(rung, url, tag=tag, profile=profile, providers=providers,
                         timeout_s=left)
```

In `apps/research/fetch/__init__.py`, replace:

```python
    try:
        budget.check(_VENDOR_BY_RUNG[6])
```

with:

```python
    if deadline is not None:
        return stop(Outcome.BLOCKED if blocked else Outcome.UNREACHABLE, "deadline", 6)
    try:
        budget.check(_VENDOR_BY_RUNG[6])
```

In `apps/research/fetch/firecrawl.py`, replace:

```python
def _post(url: str, *, json_body: dict[str, Any], headers: dict[str, str], timeout: int
          ) -> tuple[int, bytes, Mapping[str, str]]:
    response = urllib3.request(
        "POST", url, json=json_body, headers=headers,
        timeout=urllib3.Timeout(connect=10, read=timeout / 1000 + 30), retries=False,
    )
```

with:

```python
def _post(url: str, *, json_body: dict[str, Any], headers: dict[str, str], timeout: int,
          total_s: float | None = None) -> tuple[int, bytes, Mapping[str, str]]:
    # `total_s` caps connect and read together for a caller with a deadline; None is urllib3's
    # own default, no cap.
    response = urllib3.request(
        "POST", url, json=json_body, headers=headers,
        timeout=urllib3.Timeout(connect=10, read=timeout / 1000 + 30, total=total_s),
        retries=False,
    )
```

In `apps/research/fetch/firecrawl.py`, replace:

```python
    sleep: Callable[[float], None] = time.sleep,
) -> FetchedPage:
```

with:

```python
    sleep: Callable[[float], None] = time.sleep,
    timeout_s: float | None = None,
) -> FetchedPage:
```

In `apps/research/fetch/firecrawl.py`, replace:

```python
    timeout_ms = getattr(profile, "timeout_ms", 0) or settings.FETCH_DEFAULT_TIMEOUT_MS
```

with:

```python
    timeout_ms = getattr(profile, "timeout_ms", 0) or settings.FETCH_DEFAULT_TIMEOUT_MS
    bound: dict[str, float] = {}
    retries = _RETRY_ATTEMPTS
    if timeout_s is not None:
        # A caller someone waits on (fetch_page's `timeout_s`): the vendor's page timeout and
        # the HTTP wait both end at the time left, and there is no time to back off and retry.
        timeout_ms = min(timeout_ms, max(1, int(timeout_s * 1000)))
        bound, retries = {"total_s": timeout_s}, 0
```

In `apps/research/fetch/firecrawl.py`, replace:

```python
    for attempt in range(_RETRY_ATTEMPTS + 1):
        last = attempt == _RETRY_ATTEMPTS
        try:
            status, raw, response_headers = post(
                ENDPOINT, json_body=body, headers=headers, timeout=timeout_ms
            )
```

with:

```python
    for attempt in range(retries + 1):
        last = attempt == retries
        try:
            status, raw, response_headers = post(
                ENDPOINT, json_body=body, headers=headers, timeout=timeout_ms, **bound
            )
```

In `apps/research/fetch/scrapedo.py`, replace:

```python
Get = Callable[[str], tuple[int, bytes, Mapping[str, str]]]


def _get(url: str) -> tuple[int, bytes, Mapping[str, str]]:
    response = urllib3.request(
        "GET", url, timeout=urllib3.Timeout(connect=10, read=120), retries=False
    )
```

with:

```python
Get = Callable[..., tuple[int, bytes, Mapping[str, str]]]


def _get(url: str, total_s: float | None = None) -> tuple[int, bytes, Mapping[str, str]]:
    # `total_s` caps connect and read together for a caller with a deadline; None: no cap.
    response = urllib3.request(
        "GET", url, timeout=urllib3.Timeout(connect=10, read=120, total=total_s), retries=False
    )
```

In `apps/research/fetch/scrapedo.py`, replace:

```python
    get: Get = _get,
) -> FetchedPage:
```

with:

```python
    get: Get = _get,
    timeout_s: float | None = None,
) -> FetchedPage:
```

In `apps/research/fetch/scrapedo.py`, replace:

```python
        "timeout": getattr(profile, "timeout_ms", 0) or settings.FETCH_DEFAULT_TIMEOUT_MS,
    }
```

with:

```python
        "timeout": getattr(profile, "timeout_ms", 0) or settings.FETCH_DEFAULT_TIMEOUT_MS,
    }
    bound: dict[str, float] = {}
    if timeout_s is not None:  # fetch_page's deadline: scrape.do's clock and ours end together
        params["timeout"] = min(params["timeout"], max(1, int(timeout_s * 1000)))
        bound = {"total_s": timeout_s}
```

In `apps/research/fetch/scrapedo.py`, replace:

```python
        status, body, headers = get(f"{ENDPOINT}?{urlencode(params)}")
```

with:

```python
        status, body, headers = get(f"{ENDPOINT}?{urlencode(params)}", **bound)
```

**D8 (decision 14).**

In `apps/research/decisions.py`, replace:

```python
from dataclasses import dataclass, field
from datetime import timedelta
```

with:

```python
from dataclasses import dataclass, field
from datetime import timedelta
from functools import partial
```

In `apps/research/decisions.py`, replace:

```python
    model: str,
    provider: str,
) -> dict[str, Answer]:
    """Jev through DECISIONS_BASE_URL. Both the key and the base URL are passed
    explicitly, so the SDK's own TYPESAFE_API_KEY / TYPESAFE_BASE_URL
    environment fallbacks never choose the route. The SDK retries 408/429/5xx
    itself (2 retries, Retry-After honoured, 30 s per call); what still fails is
    `failed`."""
    _require_configured("typesafe")
    _, key = _decisions_key()
    try:
        with typesafe_sdk.TypeSafeClient(
            api_key=key, base_url=settings.DECISIONS_BASE_URL
        ) as client:
            response = client.system_one(state=state, questions=_to_sdk(questions), model=model)
```

with:

```python
    model: str,
    provider: str,
    timeout_s: float | None = None,
) -> dict[str, Answer]:
    """Jev through DECISIONS_BASE_URL. Both the key and the base URL are passed
    explicitly, so the SDK's own TYPESAFE_API_KEY / TYPESAFE_BASE_URL
    environment fallbacks never choose the route. The SDK retries 408/429/5xx
    itself (2 retries, Retry-After honoured, 30 s per call); what still fails is
    `failed`. `timeout_s`, when given, is both the request timeout and the
    retry budget, so one call -- retries included -- ends inside it."""
    _require_configured("typesafe")
    _, key = _decisions_key()
    bound: dict[str, Any] = {} if timeout_s is None else {
        "timeout": timeout_s, "retry": typesafe_sdk.RetryPolicy(timeout=timeout_s)}
    try:
        with typesafe_sdk.TypeSafeClient(
            api_key=key, base_url=settings.DECISIONS_BASE_URL
        ) as client:
            response = client.system_one(state=state, questions=_to_sdk(questions), model=model,
                                         **bound)
```

In `apps/research/decisions.py`, replace:

```python
    client: Client | None = None,
) -> dict[str, Answer]:
    """Answer every question against the state, independently and in parallel.
```

with:

```python
    client: Client | None = None,
    timeout_s: float | None = None,
) -> dict[str, Answer]:
    """Answer every question against the state, independently and in parallel.

    `timeout_s` bounds the call for a read someone waits on (D8 inside the
    single-page funding read). Only Jev's own client takes it: the adapter SDK
    has no timeout, and an injected client carries its own. None, the default,
    calls exactly as before.
```

In `apps/research/decisions.py`, replace:

```python
    call: Client = client or (_typesafe_client if provider == "typesafe" else _adapter_client)
```

with:

```python
    call: Client = client or (_typesafe_client if provider == "typesafe" else _adapter_client)
    if client is None and provider == "typesafe" and timeout_s is not None:
        call = partial(_typesafe_client, timeout_s=timeout_s)
```

In `apps/research/card_engine/screen.py`, replace:

```python
import math
import re
```

with:

```python
import math
import re
import time
```

In `apps/research/card_engine/screen.py`, replace:

```python
    #: "bad_probability"), so a caller can tell retry-later from never-screens; "" otherwise
```

with:

```python
    #: "bad_probability", "deadline"), so a caller can tell retry-later from never-screens;
    #: "" otherwise
```

In `apps/research/card_engine/screen.py`, replace:

```python
    client: Client | None = None,
) -> Screen:
```

with:

```python
    client: Client | None = None,
    timeout_s: float | None = None,
) -> Screen:
```

In `apps/research/card_engine/screen.py`, replace:

```python
    (from `decisions.ask`) propagates when the run budget is spent; both happen before a paid call.
    """
```

with:

```python
    (from `decisions.ask`) propagates when the run budget is spent; both happen before a paid call.
    `timeout_s` bounds a read someone waits on (owner, 2026-10-13): each D8 call is handed the
    time left, and a chunk with none left is not asked -- `unscreened`, reason "deadline", which
    fails closed like every other unscreened page. None, the default, is today's screen.
    """
```

In `apps/research/card_engine/screen.py`, replace:

```python
    for chunk in pack(texts, _request):
        if rate_limited(limit.bucket, limit.actor_id, limit=limit.limit,
```

with:

```python
    deadline = None if timeout_s is None else time.monotonic() + timeout_s
    for chunk in pack(texts, _request):
        left = None if deadline is None else deadline - time.monotonic()
        if left is not None and left <= 0:
            logger.warning("D8 ran out of time before a chunk")
            return Screen("unscreened", frozenset(), _ranked(worst), "deadline")
        if rate_limited(limit.bucket, limit.actor_id, limit=limit.limit,
```

In `apps/research/card_engine/screen.py`, replace:

```python
                          record=record, client=client)
```

with:

```python
                          record=record, client=client, timeout_s=left)
```

**The entry.**

`apps/research/card_funding/entry.py`:

```python
"""Read one programme page on demand and return its funding card (verified-catalog §3.3, §5).

Fetch through the vendor ladder (pinned to the page's origin), make lines, take the language from
code, screen with D8, ask which headings name awards, then read every award's batches in
parallel and assemble the card. A page a student waits on must finish in under 30 s and spend at
most $0.25 on models (§0.28). The clock starts before the fetch and covers it and D8 too (owner,
2026-10-13): each is handed the time left as `timeout_s`, and the clock is read when each
returns. `Guard` holds the rest, because the engine itself has neither limit (2a's carried
items): every reader call goes through it, it refuses to start a call past the deadline or the
dollar stop, and it bounds each call's HTTP wait by the time left.

Worker-side only: `fetch_page` writes `FetchAttempt`/`HostProfile`, which `runtime_web` cannot
touch, so a student-facing view QUEUES this (CLAUDE.md, "A student-facing action that needs a
fetch queues it to the worker"). Nothing is stored here; slice 3 stores the card.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any, cast

from apps.documents.letter_terms import detect_language
from apps.funding.models import Program
from apps.research.candidates import find_all
from apps.research.card_engine import Call, Decision, Limit, Quote
from apps.research.card_engine.engine import Reading, Transport, read
from apps.research.card_engine.readers import (
    READ_TIMEOUT_S,
    Attempt,
    Prompt,
    ReaderSpec,
    Stack,
    anthropic_reader,
    openrouter,
    require_keys,
    stack,
)
from apps.research.card_engine.screen import Screen, ScreenLimited, screen
from apps.research.egress import fetch_json_api
from apps.research.extraction import MessagesAPI
from apps.research.fetch import fetch_page
from apps.research.fetch.types import Outcome
from apps.research.funding_terms import funding_terms
from apps.research.reader import readable_text

from .awards import AwardNames, Page, award_section, group, heading_sections, page_lines
from .card import AwardCard, Card, Track, award_card, unread_award
from .parse import parse_award
from .questions import Funding, batches

logger = logging.getLogger(__name__)

DEADLINE_S = 30.0
PAGE_BUDGET_USD = 0.25
#: No call is started with less time left than this: it could not finish anyway.
MIN_CALL_S = 2.0
WORKERS = 8
_SERVED = frozenset({Outcome.FETCHED, Outcome.FETCHED_PARTIAL, Outcome.ARCHIVED,
                     Outcome.UNCHANGED})


def _bounded(spec: ReaderSpec, prompt: Prompt, left: float) -> Attempt:
    """The real transport with every HTTP wait cut to `left` seconds."""
    if spec.transport == "openrouter":
        def post(url: str, **kwargs: Any) -> dict[str, object]:
            return fetch_json_api(url, **{**kwargs, "read_timeout": min(left, READ_TIMEOUT_S)})
        return openrouter(spec, prompt, post=post)

    def messages() -> MessagesAPI:
        import anthropic  # the key comes from ANTHROPIC_API_KEY, checked by require_keys

        client = anthropic.Anthropic(max_retries=0, timeout=min(left, READ_TIMEOUT_S))
        return cast(MessagesAPI, client.messages)
    return anthropic_reader(spec, prompt, messages=messages)


class Guard:
    """A transport that keeps one page inside its deadline and its dollar stop.

    A refused call is an Attempt that failed (`failed:deadline`, `failed:page_budget`), so the
    engine records it like any failure and the question ends unresolved -- never a guess. An
    unpriced call (cost None) is counted, never treated as free: the stop can only see what the
    vendors priced, which the card reports."""

    def __init__(self, deadline: float, budget_usd: float, *, inner: Transport | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.deadline, self.budget_usd = deadline, budget_usd
        self.inner, self.clock = inner, clock
        self.spent, self.unpriced, self.tripped = 0.0, 0, ""
        self.lock = threading.Lock()

    def __call__(self, spec: ReaderSpec, prompt: Prompt) -> Attempt:
        left = self.deadline - self.clock()
        with self.lock:
            if self.spent >= self.budget_usd:
                self.tripped = self.tripped or "page_budget"
                return Attempt(None, "failed:page_budget", None, 0.0)
            if left < MIN_CALL_S:
                self.tripped = self.tripped or "deadline"
                return Attempt(None, "failed:deadline", None, 0.0)
        attempt = self.inner(spec, prompt) if self.inner else _bounded(spec, prompt, left)
        with self.lock:
            if attempt.cost_usd is None:
                self.unpriced += 1
            else:
                self.spent += attempt.cost_usd
        return attempt


def _calls(error: BaseException) -> tuple[Call, ...]:
    return tuple(getattr(error, "calls", ()))


def read_page(
    program: Program,
    url: str,
    *,
    limit: Limit,
    funder_country: str | None = None,
    today: dt.date | None = None,
    readers: Stack | None = None,
    transport: Transport | None = None,
    fetch: Callable[..., Any] = fetch_page,
    screen_page: Callable[..., Screen] = screen,
    deadline_s: float = DEADLINE_S,
    budget_usd: float = PAGE_BUDGET_USD,
) -> Card:
    """The funding card of one page for one programme.

    `funder_country` decides what a year of study means (decision 5): None is the programme's
    own country (`Program.country_code`), the funder of its own page; "" is unknown and holds
    such a field. `transport` replaces the real readers (tests); it is still wrapped in the
    guard, so the deadline and the stop hold either way."""
    started = time.monotonic()
    readers = readers or stack()
    require_keys(readers)  # the guard wraps the transport, so the engine will not check (2a)
    today = today or dt.date.today()
    country = program.country_code if funder_country is None else funder_country

    def left() -> float:
        return started + deadline_s - time.monotonic()

    def done(outcome: str, **extra: Any) -> Card:
        return Card(program.id, url, extra.pop("lang", ""), outcome,
                    seconds=time.monotonic() - started, **extra)

    def out_of_time(page: Page) -> Card:
        """No reader was asked: the page is one award under its title, held `deadline`."""
        return done("deadline", lang=page.lang,
                    tracks=(Track("", (unread_award(page.title, None, "deadline"),)),))

    fetched = fetch(url, purpose="read", require_origin=url, timeout_s=max(0.0, left()))
    if fetched.outcome not in _SERVED:
        return done("deadline" if left() < MIN_CALL_S else f"fetch:{fetched.outcome}")
    text = readable_text(fetched, terms=funding_terms())
    lang = detect_language(text)  # from code, never the page's own <html lang> (2a carry)
    page = page_lines(text, lang=lang)
    if not page.lines:
        return done("read", lang=lang, tracks=(Track("", ()),))
    if left() < MIN_CALL_S:  # the fetch took the time
        return out_of_time(page)
    try:
        cleared = screen_page(page.section(), limit=limit, timeout_s=left())
    except ScreenLimited:
        return done("unscreened:rate_limited", lang=lang)
    if cleared.status == "quarantined":
        return done("quarantined", lang=lang, notes=cleared.notes)
    if left() < MIN_CALL_S:  # D8 took the time, or ran out of it ("unscreened", "deadline")
        return out_of_time(page)
    if cleared.status != "clear":
        return done(f"unscreened:{cleared.reason}", lang=lang, notes=cleared.notes)

    guard = Guard(started + deadline_s, budget_usd, inner=transport)
    calls: list[Call] = []
    pool = ThreadPoolExecutor(max_workers=WORKERS)

    def run(qset: Any, section: Any) -> Future[Reading]:
        return pool.submit(read, qset, section, screen=cleared, limit=limit, readers=readers,
                           transport=guard)

    def result(future: Future[Reading]) -> Reading | BaseException:
        if not future.done():
            return TimeoutError("deadline")
        try:
            reading = future.result()
        except Exception as error:  # noqa: BLE001 - the award is held, the calls are kept
            calls.extend(_calls(error))
            return error
        calls.extend(reading.calls)
        return reading

    try:
        heads = [(run(AwardNames(), section), index) for section, index in heading_sections(page)]
        wait([f for f, _ in heads], timeout=max(0.0, guard.deadline - time.monotonic()))
        names: set[int] = set()
        for future, index in heads:
            outcome = result(future)
            if isinstance(outcome, Reading):
                names |= {index[int(d.question.removeprefix("award_L"))]
                          for d in outcome.decisions if d.value == "yes"}
        awards, unread = group(page, names)
        jobs = []
        for award in awards:
            section = award_section(page, award)
            jobs.append((award, section, [run(Funding(batch=n), section)
                                          for n in range(batches(section) + 1)]))
        wait([f for *_, futures in jobs for f in futures],
             timeout=max(0.0, guard.deadline - time.monotonic()))
        cards: list[AwardCard] = []
        source = fetched.final_url or url
        for award, section, futures in jobs:
            quote = Quote(award.name, "L0.text") if award.name_line is not None else None
            outcomes = [result(f) for f in futures]
            failed = [o for o in outcomes if not isinstance(o, Reading)]
            if failed:
                late = any(isinstance(o, TimeoutError) for o in failed)
                reason = "deadline" if late else guard.tripped or "not_read"
                cards.append(unread_award(award.name, quote, reason, type(failed[0]).__name__))
                continue
            readings = cast(list[Reading], outcomes)
            decisions: list[Decision] = [d for r in readings for d in r.decisions]
            parsed = parse_award(decisions, find_all(section.lines), readings[0].proposed,
                                 source=source, funder_country=country, lang=lang, today=today)
            card = award_card(award.name, quote, parsed)
            if guard.tripped and any(h.reason == "unresolved_split" for h in card.holds):
                card = unread_award(award.name, quote, guard.tripped)
            cards.append(card)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return done("deadline" if guard.tripped == "deadline" else "read", lang=lang,
                tracks=(Track("", tuple(cards)),), calls=tuple(calls), unread_lines=unread,
                notes=cleared.notes, cost_usd=guard.spent, unpriced_calls=guard.unpriced)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_card_funding uv run pytest tests/research/card_funding tests/documents/test_letter_terms.py tests/research/test_fetch_ladder.py tests/research/test_fetch_firecrawl.py tests/research/test_fetch_scrapedo.py tests/research/test_decisions.py tests/research/card_engine/test_screen.py -q`
Expected: 288 passed — 57 in `tests/research/card_funding` (Task 7's 9 among them), and the six
seam modules' existing tests unchanged beside their 8 new ones.

- [ ] **Step 5: Full gates**

Run: `uv run ruff check . && uv run mypy apps config && uv run python manage.py check && uv run python manage.py makemigrations --check --dry-run && POSTGRES_DB=elmify_card_funding uv run pytest -q`
Expected: all clean; no migrations; the full suite passes (apart from
`tests/documents/test_ocr_prepare.py`, which fails the same way on untouched master when the OCR
sub-environment `ocr/.venv` is not built).

- [ ] **Step 6: Commit**

```bash
git add apps/research/card_funding/entry.py tests/research/card_funding/test_entry.py \
  apps/documents/letter_terms.py tests/documents/test_letter_terms.py \
  apps/research/fetch/__init__.py apps/research/fetch/firecrawl.py apps/research/fetch/scrapedo.py \
  tests/research/test_fetch_ladder.py tests/research/test_fetch_firecrawl.py \
  tests/research/test_fetch_scrapedo.py apps/research/decisions.py \
  apps/research/card_engine/screen.py tests/research/test_decisions.py \
  tests/research/card_engine/test_screen.py
git commit -m "feat(research): read one programme page into a funding card within 30 s and \$0.25"
```

---


## Self-review notes (writer's)

- Spec coverage: lines (§5 step 1, Task 3); award grouping with the judgement asked and the rest
  by code (step 3, Task 3, decision 1); the §5.2 catalogue under definitions v3 — target level
  apart from prior degree and exclusions (`target_level` criteria, `kind_N`'s `prior_degree` /
  `excluded_degree`), nationality as a named list and "international" as no list (Task 5's
  `_nationality`), residence, stateless and compatriots (`kind_N`), event dates not application
  dates (`CRITERIA`, `role_*`), year of study through the per-country CSV keyed by the funder's
  country (Tasks 2, 5, 7; owner 2026-10-13), tests and
  certificates as requirements (`CRITERIA`, `test_or_certificate`) — Tasks 4–5; proposals unioned
  with code's candidates (Tasks 4–5); the parse step for amounts with range and approximately,
  dates with roles and order, relative dates, durations, intakes, places, regions and groups,
  levels and requirements (Task 5); the country-group fallback with sources and the shipped
  check (Task 1); the typed card, hold reasons, conflicts and tracks (Task 6); the single-page
  entry with fetch, the 30 s deadline over fetch, D8 and readers, the $0.25 stop, the language
  from code (az and kk included) and the key check (Task 7). Out of this plan by design: the hunt (2c), storage and serving (slice 3).
- Carried items from PR #203: `Section.lang` from code (decision 15, Task 7); the deadline
  (decision 14, `Guard`); `require_keys` in the wrapper's caller (`read_page`); page text by key
  only (tests in Tasks 3 and 4); how decisions become typed values (Task 5); one `Quote` per
  `Decision` — a value built from several decisions keeps all of them (`Value.decisions`) and
  quotes the candidate's own span.
- Placeholder scan: no TBD/TODO; every new file is given whole; every edit to an existing file
  (`who.py` in Task 1, the seams in Task 7) shows the exact old and new text, and every appended
  test is given whole. The owner's 2026-10-13 answers are decisions 5, 14 and 15.
- Type consistency: `Page`, `Award`, `Funding`, `Value`, `Parsed`, `Benefit`, `AwardDate`,
  `Nationality`, `Condition`, `Field`, `Hold`, `AwardCard`, `Track`, `Card`, `Guard` are used with
  the same fields in every task; `parse_award(..., funder_country=...)` (Task 5) is what
  `read_page` calls (Task 7); `level_of_year(text, funder_country, lang)` (Task 2) is what
  `parse._level` calls; `read_page(program, url, *, limit, funder_country=None, ...)` matches its
  tests; each seam's `timeout_s` keyword is the name its caller passes.
- Not run: any live vendor (no keys used in writing this plan, and none needed: every test
  scripts the readers); `fetch_page` and D8 against a real page (both stubbed; their own tests
  cover them), and so neither Firecrawl's nor scrape.do's answer to a short `timeout` nor the
  TypeSafe SDK's to a short retry budget has been seen live.
