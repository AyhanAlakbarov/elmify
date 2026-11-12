# Programme search, round 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry out the owner's decisions of 2026-10-15 on the merged per-student search (PR #216), so it can later be switched on safely.

**Architecture:** All changes are to `apps/research/tap.py`, `tap_query.py`, `seam_bindings.py`, `tap_seams.py`, the `TapQueryRun` / `SearchTap` models and their tests. Nothing is switched on: `TAP_AUTOMATIC` and `FUNDER_SWEEP_LEVEL_CHECK_LIVE` stay `False`.

**Tech Stack:** Django 6, Postgres 17 with row-level security, Exa and Brave providers, the research SQS queue.

**Spec:** what governs, in order (a later row wins where they differ):

| Document | Governs |
|---|---|
| `docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md` §10.5, incl. the "Amended 2026-10-14" block | first search and follow-ups, $100 wallet, reuse |
| `docs/superpowers/plans/2026-10-14-programme-angles-and-the-tap.md` | how the merged code is built |
| Owner decisions 2026-10-15 (this plan's tasks) | everything below; they supersede the 30-day reuse rule for programme queries and the 840 s ceiling as an ending |

## Global Constraints

- Never `ruff format`. Gates: `uv run ruff check .`, `uv run mypy apps config`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`, `POSTGRES_DB=elmify_programme_search_2 uv run pytest -q`.
- Every database touch inside `tenant_transaction(...)`; never a transaction held across a provider call. Tavily is never a tap provider. No model composes per-student query text.
- Money: a FIRST search never spends `SEARCH_FOLLOWUP_RESERVE_USD`, checked live.
- Shared tables keep the `research/0012` RLS shape; a new column on one needs no new policy.
- Never hand-edit an applied migration. Migrations on this branch are new (research `0029+`).
- No real provider or model call in a test.

## Review Focus

1. A search run before stage 2 exists must leave its queries un-marked and its hosts readable later. Covered in Task 1.
2. Continuation must never double-spend or double-run a query, and must stop when the budget or the plateau says so. Covered in Task 6.
3. Parallel calls must not hold one DB connection across threads or lose a charge. Covered in Task 6.
4. "Anywhere" must respect `excluded_countries`. Covered in Task 5.
5. Funding queries reused across a cycle boundary would hide a new cycle's call; programme queries likewise. Covered in Task 2.

---

### Task 1: Unread sites stay readable

**Owner decision:** a search counts as done only once its hosts were handed to reading; a host recorded but never read counts as new.

**Files:** `apps/research/tap.py` (`_Stage1._record`, `_remember` and its callers, `_stage_two`), `tests/research/test_tap.py`.

**Behaviour:**
- **(a)** While `bound_host_reader()` cannot read (`NullSeams`, i.e. `read()` returns `None`), `run_tap` writes **no** `TapQueryRun` rows. The queries stay unmarked and run again later.
  - When stage 2 is available, a query's `TapQueryRun` row is written after stage 2 handled the hosts that query found. Simplest correct form: collect the (hash, provider, results) of the calls made in this tap and write them at the end of stage 2, only if stage 2 ran (did not end `STAGE2_UNAVAILABLE`).
  - The `DatabaseError` guard on `_remember` stays.
- **(b)** In `_Stage1._record`, a domain counts as **known** only if its `OrganisationDomain` row's organisation is not an unread candidate. An unread candidate is `status=CANDIDATE` and `last_verified IS NULL`.
  - An unread candidate is treated as new: it is counted in `hosts_new` and handed to stage 2, and `record_organisation` is not called a second time (it already exists).
  - Registered, rejected or verified organisations stay known.

**Tests:**
- a tap with the null reader writes no `TapQueryRun`;
- a tap with a scripted reader writes them after stage 2;
- a host recorded by an earlier tap (CANDIDATE, `last_verified` null) is handed to stage 2 by a later tap;
- a REGISTERED host is not.

**Commit:** `fix(research): a search before site reading exists marks nothing done, and unread hosts stay new`

### Task 2: Reuse window by kind and cycle

**Owner decision:** programme queries are reused for the whole academic cycle; money and recency queries for 30 days; a new cycle starts fresh.

**Files:**
- `apps/research/tap_seams.py`: `AngleRow` gains `kind: str = "PROGRAMME"`.
- `apps/research/seam_bindings.py`: `ProgrammeAngleSource` fills it.
- `apps/research/tap_query.py`: the kind rides beside each rendered request; extend the `(angle_id, request)` tuple, or return the `AngleRow`, as the code reads best.
- `apps/research/models.py`: `TapQueryRun` gains `kind CharField(10)` and `cycle CharField(9)`. A new migration with defaults; no RLS change, since the table is already shared.
- `apps/research/tap.py` (`_reused`, `_remember`).
- Tests in `tests/research/test_tap.py`.

**Behaviour:**
- `_remember` stores the request's kind and `angles.cycle_label(now)`.
- `_reused` uses the window that matches the row's kind:
  - **PROGRAMME:** a row with `cycle == cycle_label(now)` counts as reused, whatever its age.
  - **MONEY and RECENCY:** `ran_at` within `TAP_QUERY_REUSE_DAYS` (30) counts, and only within the same cycle.
- A row from an earlier cycle never counts.

**Tests:**
- a PROGRAMME query run 200 days ago in this cycle is reused;
- a MONEY query run 40 days ago is not;
- a PROGRAMME query from last cycle is not.

**Commit:** `feat(research): programme queries are reused for the academic cycle, funding queries for 30 days`

### Task 3: A crashed first search falls back to a follow-up

**Owner decision:** when a FIRST search is owed but nothing is above the reserve, run the follow-up from the reserve instead of refusing and stopping.

**Files:** `apps/research/tap.py` (`on_profile_saved` and `_first_search_owed` / `request_tap`), `tests/research/test_tap.py`.

**Behaviour:**
- When a FIRST is owed and `request_tap(kind=FIRST)` raises `TapRefused` because the wallet has nothing above the reserve, `on_profile_saved` goes on to the FOLLOW_UP path for this save, with its usual delta.
- Any other refusal (`TAP_PER_DAY`, a queue outage) is logged and stops, as today.
- Distinguish the cases by a specific exception subclass or reason, not by matching message text.

**Tests:**
- a FIRST tap ended FAILED with the wallet spent to the reserve; an added country queues a FOLLOW_UP naming it;
- a `TAP_PER_DAY` refusal still queues nothing.

**Commit:** `fix(research): a first search that spent the budget and failed falls back to follow-ups`

### Task 4: `queries_reused` stays internal

**Owner decision:** keep `SearchTap.queries_reused` for us only.

**Files:** a new test, e.g. `tests/research/test_internal_counters.py`.

**Behaviour:** a test fails if the string `queries_reused` appears in any template under `templates/` or any `apps/*/templates/`, or in any non-test module outside `apps/research/` (views, serializers, API code). Read how the repo's existing grep-style tests are written, e.g. `tests/test_instruction_files.py`, and follow their style. Allow `apps/research/` (the engine and its models), migrations, and `apps/audit/redaction.py` (the erasure classification).

**Commit:** `test(research): the searches-skipped count never reaches an agency-facing surface`

### Task 5: "Anywhere" means all 53 target countries

**Owner decision:** an empty country list searches every target country, also in its own language, thinnest-catalogue countries first.

**Files:** `apps/research/destinations.py` (new, one constant plus one function), `apps/research/tap_query.py` (`inputs_from`), tests.

**Behaviour:**
- `TARGET_COUNTRIES: tuple[str, ...]` holds these 53 ISO codes:
  - the 27 EU members: AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE;
  - and NO CH IS GB SA AE QA KW BH AU NZ SG BN RS TR CN JP KR RU VN AM AZ GE KZ US CA.
  - The comment cites the owner's list of 2026-09-26, and says Africa, South America and Mexico ("top universities only") stay out until a top-universities mechanism exists.
  - Add an assert-style test that the tuple has 53 unique valid codes.
- `inputs_from`: when `allowed_countries` is empty, `destinations` = `TARGET_COUNTRIES` minus `excluded_countries`. The student's home country stays in: they may study at home.
- **Order:** ascending by how many known organisations of kind INSTITUTION the catalogue holds in that country (`Organisation.objects.filter(country_code=..., kind="INSTITUTION", status__in=[REGISTERED, CANDIDATE])` counted once per call), so the thinnest come first. Ties are broken by the tuple order.
  - This read happens where `inputs_from` is called in the worker, not in the web hook (`runtime_web` cannot read the catalogue).
  - If `inputs_from` also runs in the web hook for the delta, keep the raw empty list there and expand only in `run_tap`, by passing an `expand_anywhere` flag or expanding inside `run_tap` before rendering.
- The follow-up delta still compares raw profile values. "Anywhere" to "anywhere" is no change.

**Tests:**
- empty countries with `excluded_countries=("RU",)` gives 52 destinations without RU;
- order follows the per-country institution count;
- the web-hook path does not read `research_organisation`.

**Commit:** `feat(research): a student who picks no country is searched across the 53 target countries`

### Task 6: First search — parallel calls and continuation

**Owner decision:** about 8 provider calls at once; when time runs out, save the place and continue in a new job; only the budget and the plateau end a first search.

**Files:**
- `apps/research/tap.py` (`_ask`, the FIRST stages, `run_tap`'s claim);
- `apps/research/models.py`: `SearchTap.resume` JSONField, null, holding the stage index, the position in the stage's request list, the plateau window and the deep-stage ranking inputs. Plus a `SearchTap.Ending` value `CONTINUED` if needed, and a migration.
- `config/settings/base.py`: `TAP_PARALLEL_CALLS = 8`, `FIRST_SEARCH_MAX_CONTINUATIONS = 6`.
- `run_research_worker.py` if routing changes; tests.

**Behaviour:**
- **Parallel:**
  - Within a stage, up to `TAP_PARALLEL_CALLS` requests are in flight at once, through `concurrent.futures.ThreadPoolExecutor`.
  - Provider calls run in worker threads with no DB access.
  - Every DB write (`_record`, charges, `_remember`, counters) happens on the main thread as results return, in submission order for determinism, so no connection or GUC crosses threads.
  - Preflight and the reserve check run on the main thread before each submit, so in-flight spend never exceeds the live check by more than the in-flight calls' preflight prices. Count in-flight preflight prices against the allowance when deciding to submit.
  - Before choosing 8, check Exa's and Brave's published rate limits in `apps/research/providers/` comments or settings, and stay under them. If either is lower, cap that provider's concurrency at its limit.
- **Continuation:**
  - When `FIRST_SEARCH_MAX_SECONDS` is reached mid-stage, stop submitting and drain in-flight calls (record their results).
  - Then store `resume`, set the tap back to `QUEUED` (state machine: a continuation is a fresh claim of the same tap), increment a continuation counter in `resume`, and enqueue a new `search_tap` message for the same `tap_id`.
  - `run_tap` claims a QUEUED tap with `resume` set and continues from it.
  - Only plateau, money, `NO_PROVIDER` or a failure end a FIRST search. After `FIRST_SEARCH_MAX_CONTINUATIONS` continuations it ends `TIME_CAP` (a runaway guard, not the normal end).
  - FOLLOW_UP keeps its single-run 180 s cap.
- **Charges:** charges and `queries_reused` accumulate across continuations on the same tap row. The query-reuse records of Tasks 1-2 make a resumed run skip nothing it should run, and re-run nothing it already ran in this tap, because the resume position does that.

**Tests:**
- 8 requests are in flight at most (a scripted provider that blocks and counts);
- a time-capped FIRST stores `resume`, re-queues, and the next claim continues from the saved position without re-running a request;
- money still stops it at the reserve across a continuation;
- after `FIRST_SEARCH_MAX_CONTINUATIONS` it ends `TIME_CAP`;
- DB writes happen on the main thread (assert via a thread-name check in the scripted `_record` path).

**Commit:** `feat(research): the first search calls providers in parallel and continues in a new job when time runs out`
