# Handover — fetch-engine core, from claude/fetch-spec-refresh to claude/fetch-engine-core

Owner decision 2026-09-23: two sessions were executing this plan in parallel. `claude/fetch-engine-core`
continues; this branch stops at Task 2. Nothing here was deleted.

**Both branches already share the docs.** `claude/fetch-engine-core` branched from `25a8c5c`, so it
carries the plan reconciliation (`545ecd2`) and the labelled-corpus spec (`25a8c5c`).

**`claude/fetch-spec-refresh` now carries no code at all** — it is docs only. Its two duplicate task
commits were dropped at the owner's instruction once this handover was written, so
`apps/research/migrations/0004_fetch_engine.py` and `0005_fetch_engine_rls.py` exist on
`claude/fetch-engine-core` alone and the two branches cannot collide on the migration chain. Whatever
this file says about Task 1 and Task 2 is a *finding*, not a diff you can cherry-pick: the code it
describes lives on your branch, not mine.

## Rulings made here — carry these or hit the same traps

1. **Task 6 is struck. `apps/research/fetch/budget.py` must never be created.** Master already has
   `SweepBudget` in `apps/research/fetch/__init__.py`: constructor takes `Mapping[str, int]` of
   per-vendor caps, `check(vendor)` before a rung, `spend(vendor, credits)` after, `usd()` to report.
   `budget.default_budget` does not exist — the ladder takes `budget=None` and the caller builds one
   from `settings.FETCH_SWEEP_CREDITS`, as `fetch_ladder` already does. Task 7 adds only
   `observe_remaining(vendor, credits)` and `sweep_id`, in `__init__.py`.
   *Why it matters:* a second budget with per-vendor caps that disagree with the one
   `tests/research/test_fetch_router.py` pins re-creates the 58-host-sweep overspend master measured.

2. **Task 9's produced signature is master's**, `retrieve_official_source(url, *, fetch=..., tag=...,
   budget=...)`. The plan's `plain_fetch=` / `browser_render=` were parameters of the deleted
   Scrapling tier. The task's real content is translating the ladder's outcome values into the
   `SourceBlocked` subclasses the callers already catch. **There are eight callers, not five** —
   `reader`, `program_rules`, `pipeline`, `seeds`, `fetch_ladder`, `funding_yield`, and both
   `apps/documents/research_fit/service.py` and `pages.py`.

3. **`fetch.types.SERVED` in Task 9's Consumes** is Task 1's `Outcome` member for a served page, not
   a separate constant. Resolve against the real enum.

4. **Task 12 extends `tests/research/test_fetch_live.py`; it does not create it.** Master already has it.

5. **Task 11 is struck.** `fetch_official_source`, the Scrapling tier, `browser_server.py`,
   `BROWSER_SERVICE_URL`, `plain_fetch`, `browser_render` are all already absent at 40f8400. The step
   is a grep that must return nothing.

6. **Use a test database named after the worktree**, e.g. `POSTGRES_DB=elmify_fetch_engine_core`.
   Both sessions used the plan's literal `elmify_fetch_engine` and the two suites dropped and
   re-migrated the database under each other — a failing suite that means nothing.

7. **`HostProfile`'s PK is the full lowercased hostname, not `hosts.registrable_domain`.** What it
   remembers is per server: robots.txt, WAF behaviour, whether this host needs a render.
   `ai.study.fau.eu` rendering says nothing about `www.fau.eu`.

## Task 2's three deviations from the brief — all correct, keep them

- Index names lose the `_idx` suffix: Django caps an index name at 30 characters and
  `research_fetchattempt_retry_idx` is 31. The brief mandated an impossible name.
- The RLS test needs `django_db(transaction=True)`: `runtime_connection` is a second psycopg
  connection and cannot see the test's uncommitted rows.
- `pytest.raises(Exception)` narrowed to `psycopg.errors.InsufficientPrivilege`, with the probe INSERT
  spelling out every NOT NULL column — otherwise a NOT NULL violation passes for a policy refusal.

## The one Important finding from Task 2's review — UNFIXED here, and it applies to you too

**`tests/conftest.py` — the widened `runtime_connection` grant covers tables but not sequences.**
`scripts/create_runtime_role.sql:97` gives the production runtime role
`GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public`; the fixture role gets none. Any future RLS
test on a table with a `BigAutoField` PK that inserts without an explicit id fails on
`permission denied for sequence …` — SQLSTATE 42501, `psycopg.errors.InsufficientPrivilege`,
**indistinguishable from the policy refusing.** That is the same "passes on a permission error rather
than on the policy" failure the widening was meant to close, one level down.

Fix, one line beside the table grant, which also makes the fixture role match the production role it
is named after:

    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}

## Minors worth knowing (from the same review)

- `0005_fetch_engine_rls.py` creates a policy `TO catalog_ingestion` with **no migration-graph edge**
  to the migration that creates that role (`apps/funding/migrations/0006_official_snapshots.py:40`).
  The `research` chain declares no `funding` dependency at all. It works today only because `funding`
  sorts before `research`. Add `("funding", "0006_official_snapshots")` to 0005's `dependencies`.
- `_grant_task7_runtime_dml` in `tests/tenancy/test_database_isolation.py` is now inert (verified: same
  four privileges, same grantor, strict subset of the fixture's schema-wide grant) but is left in place
  at five call sites, where a reader will credit it with DML the fixture actually provides. One comment
  fixes it.
- `tests/portals/test_rls_spine.py:8` still points at `tests/tenancy/test_database_isolation.py::runtime_connection`,
  which has moved.
- `HostProfile`'s docstring promises a lowercased key and nothing enforces it; on a shared-catalog
  table `Host-Profile` and `host-profile` are two memories of one server.
  `CheckConstraint(condition=Q(host=Lower("host")))` is one line.
- `FetchAttempt.outcome` is a bare `CharField(max_length=20)` beside `fetch.types.Outcome`; a typo'd
  value silently never matches the `(outcome, retry_after)` retry sweep.
- `test_an_attempt_records_what_a_call_cost_and_why_it_ended` asserts neither cost nor reason
  (brief-verbatim); `test_the_attempt_index_supports_the_retry_sweep` checks `_meta.indexes`, not
  `pg_indexes`, so it cannot see whether the index exists in the database.

## Open question the reviewer raised for a human

`apps/research/models.py` — `timeout_ms = 60_000` is the only plan-dependent number in Task 2, and the
plan's Global Constraints say every such number is a setting with an env override. The implementer
argues it is per-host state rather than a knob, and that a settings-derived model default makes the
migration non-deterministic. Both readings are defensible. Decide whether the fetch engine's *default*
timeout belongs in settings with the column default as a mirror, or whether it lands with the task
that reads it.
