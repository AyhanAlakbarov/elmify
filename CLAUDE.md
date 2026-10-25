# tehsil_agent

## Frontend and design

No stack, template system, or design-authority skill is pinned here. The presentation layer (which
UI stack, which skills arbitrate design decisions, animation approach, form-rendering conventions) is
decided fresh from the idea by the frontend/orchestrator skill in use (`spec-to-site-orchestrator`)
at build time — not prewritten in this file or in `phased requirements.md`.

## Tenant branding

- White-label rule: tenant `brand_primary_color` is the only tenant-variable color. `apps/tenancy/services.py::validate_brand_contrast` (WCAG AA) and `validate_brand_palette` (also checks the derived `--brand-tint` mix, see that file's own comments for the derivation math) are the source of truth — this logic is stack-independent and survives whatever presentation layer is chosen.

## Security tooling

- `uv run bandit -c pyproject.toml -r apps config` — code-level vuln scan (config in `pyproject.toml`'s `[tool.bandit]`)
- `uv run pip-audit` — dependency CVE scan
- Both run in CI (`.github/workflows/ci.yml`) as blocking checks; treat a finding as a real bug to fix or a documented `# nosec <code>` false positive, not something to silence in CI config.
- `.github/workflows/ci.yml` also runs a blocking `gitleaks` secret scan (`secrets` job) on every push/PR. `gitleaks-action` is free for personal-account repos; if this repo moves to an organization, add a `GITLEAKS_LICENSE` repo secret or the job fails.
- Local safety net: `uv run pre-commit install --hook-type pre-commit --hook-type pre-push` runs Bandit on every commit and `pip-audit` on every push, before either reaches GitHub — see `.pre-commit-config.yaml`. Run this once after cloning.
- `.github/workflows/security-aws.yml` (Prowler, AWS account posture) is manual-dispatch only, dormant until `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` exist as repo secrets — enable it once real AWS infra exists for this project.
- AI code review on PRs comes from Claude Code via `.github/workflows/claude-code-review.yml` (automatic on every PR) and `claude.yml` (on an `@claude` mention), authenticated by the `CLAUDE_CODE_OAUTH_TOKEN` repo secret. CodeRabbit was removed 2026-09-14 so PRs get one AI review, not two. A PR that edits either workflow file gets no review: the action refuses to run a workflow that differs from the default branch's copy, logs a warning, and still reports success.

## Row-level security: what actually filters a query

Tenant isolation is enforced in two independent places, and code that satisfies one while assuming
it satisfied both is the most expensive mistake available in this repo. It has now been made twice.

- **Django's `TenantManager`** filters on the `tenant_scope()` contextvar. `Model._base_manager`
  skips it, and so does any forward-FK traversal.
- **Postgres row-level security** filters on the `app.tenant_id` GUC, set by `set_local_tenant()`.
  Tenant tables are `ENABLE` + **`FORCE ROW LEVEL SECURITY`** (`apps/tenancy/migrations/0002_rls.py`)
  and both production runtime roles are `NOBYPASSRLS` (`scripts/create_runtime_role.sql` refuses
  one that is not).

Three distinct failure modes, none of which any test in this repo can catch:

1. **GUC unset.** The policy compares `tenant_id` against `NULL` and every row disappears — a query
   that is legal SQL and returns nothing. Documented at `apps/portals/services.py` (reads that need
   a transaction) and `apps/audit/redaction.py` (writes that silently match zero rows).
2. **GUC set, but you wanted a cross-tenant read.** `_base_manager` removes the ORM filter and leaves
   RLS as the only one, so you get the *current* tenant's rows, not all of them. Documented at
   `apps/portals/worker.py` for forward-FK traversal — and it still happened again in
   `apps/audit/identity.py`, which is why it is repeated here.
3. **`SECURITY DEFINER` owned by the table owner.** `FORCE ROW LEVEL SECURITY` applies policies to
   the owner as well, so such a function is filtered exactly like ordinary code. It reads like a fix
   for (2), changes nothing, and passes every test. **Only a `BYPASSRLS` role escapes.**

**Why no test catches any of this: the test database role bypasses RLS.** A test asserting a
cross-tenant read works passes whether or not it would work in production, and dumping the SQL Django
generates proves nothing either — the predicate is added by Postgres, not written by Django. Verify
against a `NOBYPASSRLS` role, through the `runtime_connection` fixture in
`tests/conftest.py` (or `role_connection` / `web_role_orm` for grants), or you have verified nothing.

**Only a role that already has `BYPASSRLS` can create one** (measured: a `CREATEROLE NOSUPERUSER`
role gets "permission denied to create role"). So `tehsil_erasure_guard` — the one role in this
system with `BYPASSRLS`, `NOLOGIN`, owning exactly one function — is created by
**`scripts/create_erasure_guard.sql`, an admin script run by hand after migrations** (and
granting `EXECUTE` to `runtime_engine` alone — the one caller is the worker's
`execute_due_erasures`; the owner console makes only non-`EXECUTED` transitions)
(`docs/runbooks/deploy.md`), never by a migration. A migration that tried would pass every local
check, because CI and developer databases migrate as a superuser, and fail at deploy. Pinned by
`tests/infra/test_template.py::test_no_migration_creates_a_bypassrls_role`.

Keeping it out of the migration is also what keeps the migration role out of it. Transferring the
function's ownership from a migration needs `GRANT tehsil_erasure_guard TO tehsil_migration`, and
that grant is one `SET ROLE` from full cross-tenant read for whoever holds the migration password —
role *attributes* are not inherited through membership, but `SET ROLE` does not need them to be.

**Deleting that `GRANT` from the bootstrap revokes nothing.** Role membership is database state, not
file text, so a database bootstrapped by the older script keeps it. `create_erasure_guard.sql`
therefore *revokes* every membership of the guard role except the running admin's, on every run, and
asserts none survives — the removal is an action, not an absence. Verified against a database carrying
the stale grant: before, the migration credential could `SET ROLE`; after, `permission denied`.

Two ordering facts in that script are load-bearing and were both measured on PG 17:

- **`REVOKE ... FROM PUBLIC` must precede `ALTER FUNCTION ... OWNER TO`.** Postgres grants `EXECUTE`
  to `PUBLIC` on every new function, and after the transfer the revoke runs only on the strength of
  the caller's membership of the new owner. A `NOINHERIT` caller has none, so Postgres emits
  `WARNING: no privileges could be revoked` — and a warning fails nothing. Revoking after leaves
  `{=X/guard,guard=X/guard}`; before leaves `{guard=X/guard}`. The script asserts the outcome.
- **`ALTER FUNCTION ... OWNER TO` requires the NEW owner to hold `CREATE` on the schema.** Without
  it: `permission denied for schema public`. Superusers skip the check, so no test can see this.

`scripts/create_runtime_role.sql` **refuses to bootstrap a database whose `migration_role` is a
superuser, `BYPASSRLS`, or one of the two runtime roles**. It owns every table, so leaving it unconstrained makes tenant isolation
a property of how the database happened to be bootstrapped rather than of the policies.

### The role model: two runtime roles, and the catalogue boundary is a GRANT (2026-09-25)

There is no `runtime` role any more. There are three connection roles, chosen by
`DATABASE_ROLE` (`config/settings/database.py`), and the split between the first two is by
**caller**, not by tenant:

- **`runtime_engine`** — the worker, Europass worker and document worker task definitions, and
  every management command run from them. DML on every table; the catalogue's **only** writer — the
  old `catalog_ingestion_write` policies were repointed and renamed `runtime_engine_write`, and
  `catalog_ingestion`, a name in a policy nobody could log in as, is dropped
  (`apps/funding/migrations/0049_catalog_grants.py`).
- **`runtime_web`** — the agency-facing web tier only. DML on every tenant table and **no privilege
  at all** on the 27 tables carrying the `shared_catalog_select` policy (the catalogue, plus the
  fetch engine's `FetchAttempt`/`HostProfile` telemetry — owner, 2026-09-25: no exceptions).
  The **portal** task definition is `runtime_web` too, with its own execution role that cannot
  read the engine secret: its code reads no catalogue, and its security rests on a renderer
  sandbox holding against hostile pages — as the engine, an escape could write the catalogue.
- **`migration`** — owns every table, runs only the one-off migration task.

**The catalogue boundary is a table `GRANT`, not a policy, and that is the point.** A missing grant
fails closed with `permission denied for table …` — loud, on the whole query, whatever rows it
would return. A policy returning zero rows looks exactly like an empty table, which is failure mode
1 above. **RLS is unchanged and is tenant isolation and nothing else**: both runtime roles are
filtered by `app.tenant_id` exactly as `runtime` was. Never express "the web may not see X" as a
policy.

Consequences that bind new code:

- A web path that reads the catalogue — a `select_related`, an `.exists()`, a join to `Program` —
  fails in production and passes every superuser test. Three did, found by audit before the revoke
  (the kit's checklist, a programme-existence check at the generate door, a join feeding download
  filenames); each now reads a tenant-side copy the worker wrote. The generate door now accepts a
  `programme_id` only if it is in the student's own pack — a candidate in `current_pack` or one of
  their `Application` rows, matched on the `program_id` column — else 400 `programme_not_in_pack`.
  That answers from rows the student already holds, so it is no oracle over which catalogue ids
  exist; the worker's drop of an unknown programme stays as defence in depth.
- **A student-facing action that needs a fetch queues it to the worker** (spec §6). `fetch_page`
  writes telemetry the web role cannot touch.
- **The Firecrawl webhook receiver (`apps/research/views.py`, `FETCH_WEBHOOKS_ENABLED`) must stay
  off until its write moves.** It is a web route and it UPDATEs `OfficialSourceSnapshot`, a catalogue
  table, so under `runtime_web` every signed delivery 500s with `permission denied` (pinned by
  `tests/research/test_firecrawl_webhook.py`). Enabling it needs the write queued to `runtime_engine`
  **and** an UPDATE policy on that table — the engine has only an INSERT policy there, so the same
  statement on the worker matches zero rows (`poll_monitor_checks._mark`, silently inert today).
- **`explanations.draft_explanation`, when wired, writes its result to a tenant row** (spec §11); it
  must not compute from catalogue content at render.
- `runtime_web` is never a member of `runtime_engine`: `SET ROLE` needs no inherited attributes, so
  membership would make the boundary a discipline. The bootstrap revokes every membership of both.
- **Not catalogue, and deliberately still web-readable:** `research_domainlease`,
  `portals_portalform`, `portals_fieldmap` — shared, non-RLS, and without `shared_catalog_select`.
  The extension API reads field maps from the web tier.
- **A new catalogue table is web-readable until its migration revokes it.** Default privileges
  cannot tell a catalogue table from a tenant table at `CREATE`, so they grant every future table to
  both roles. The guard is a test, not a privilege: `tests/tenancy/test_catalog_grants.py` asserts
  `has_table_privilege('runtime_web', t, 'SELECT')` is false for every table `pg_policies` lists
  under `shared_catalog_select`, and fails until the revoke lands.
- **Recipe for a new catalogue table.** Its RLS block is `CREATE POLICY shared_catalog_select ...
  FOR SELECT USING (true)` plus `CREATE POLICY runtime_engine_write ... FOR ALL TO runtime_engine
  USING (true) WITH CHECK (true)` — never `TO catalog_ingestion`, which no longer exists on a fresh
  database — and the same migration runs `REVOKE ALL ON public.<table> FROM runtime_web` (and on any
  serial/identity sequence it owns). A migration written before 0049 that names `catalog_ingestion`
  (as `research/0007` and `research/0009_site_job_record_rls` do) must be in 0049's dependencies
  instead, so 0049's rename covers it — 0049 depends on the newest such research leaf, 0009.

**Testing it.** All in `tests/conftest.py`: `catalogue_tables(cursor)` reads the list from
`pg_policies` (never from migration text, which names dropped tables); `role_connection(name)`
connects as a throwaway login that is a *member* of a fixed role, because `runtime_engine` and
`runtime_web` are cluster-global and shared by every worktree's test database — never `ALTER` them;
`web_role_orm` puts Django's default connection behind `runtime_web` (request it last,
`transaction=True`); `reads_no_catalogue()` fails a block whose SQL names a catalogue table (default
connection, quoted names only). `runtime_connection` is neither runtime role: a throwaway
`NOBYPASSRLS` login with `SELECT` on every table and no membership, so a `runtime_engine_write`
policy never applies to it — use it for tenant policies, `role_connection` for grants and writes.

**Two bootstrap facts, measured on PG 17 on 2026-09-25, that no superuser test can see:**

- **A non-superuser `CREATEROLE` role may `ALTER`, set the password of, or revoke memberships from
  only a role it holds `ADMIN OPTION` on**, and creating a role gives that option to its creator
  alone ("Only roles with the CREATEROLE attribute and the ADMIN option on role … may alter this
  role"). So **`scripts/create_runtime_role.sql` runs BEFORE the first migrate**: the admin creates
  both roles and 0049's `CREATE ROLE` is a no-op. Run after, the migration role created them and the
  script refuses, saying why. The RDS master user is not a superuser.
- **Only a role holding `SUPERUSER`, `CREATEDB`, `REPLICATION` or `BYPASSRLS` may set that
  attribute — even to `NO`.** The old bootstrap's `ALTER ROLE … NOSUPERUSER NOBYPASSRLS` therefore
  only ever worked as a superuser. It now *asserts* those four are off and refuses a role that
  carries one, instead of setting them.

**Not yet met a real database.** Nothing is deployed; every grant is verified against roles in a
test database. First deploy re-runs `test_catalog_grants.py`'s assertions against RDS before any
agency has a login (`docs/runbooks/deploy.md`, step 4).

### The rule for crossing tenants

There are exactly two sanctioned ways, and a third that looks reasonable and is not:

1. **A fact that is not about a person** → a named `SECURITY DEFINER` function, reviewed one at a
   time, returning the narrowest possible answer. `user_has_active_membership` returns one boolean.
   Every such read must also leave an `AuditEvent`: `phased requirements.md` §349 requires privileged
   cross-tenant operations to be least-privilege, reason-bound **and audited**, and the first two
   without the third is what the erasure path shipped with before this change.
2. **A person's data** → never cross tenants. A platform admin takes a `SupportGrant`
   (`apps/tenancy/models.py`, `require_active_support_grant`, `docs/runbooks/support-access.md`) for
   the one agency they need: time-boxed, reason-carrying, and alarmed on every use.
3. **Not this:** widening the policies for a platform-admin GUC, or giving any connection role
   `BYPASSRLS`. The support-access runbook rules it out by name, and the measurement rules it out on
   merits — it exposes every membership row in every tenant to answer questions that need one bit.

To test any of this, use the `rls_enforced_orm` fixture (`tests/portals/test_rls_spine.py`), which
repoints Django's default connection at a real `NOBYPASSRLS` role so managers and FK descriptors run
behind the policy too.

Measured 2026-09-09 on the real policy shape, not inferred: with `app.tenant_id` set to tenant A and a
user holding an active membership in tenant B, a plain `_base_manager` SELECT and a `SECURITY
DEFINER` function owned by the table owner both returned **zero** rows; the same function owned by a
`BYPASSRLS` role returned the row. Reasoning and the full option comparison:
`docs/superpowers/specs/2026-09-09-identity-erasure-design.md`.

## Migrations: squash once, in the one window where it is cheap

There are 94 migrations and no production database, so the schema is free — rename,
drop, restructure a model and let Django write the migration. Nothing about the AWS
design is shaped by the count; the only deploy-time constraint is *who* runs them
(`tehsil_migration`, non-superuser, `NOBYPASSRLS`).

**Before launch, squash to one initial migration per app.** Not done yet, deliberately,
and the reason is the cost, not the value:

- **32 of the 94 migrations carry hand-written `RunSQL`/`RunPython`** — the RLS policies,
  `FORCE ROW LEVEL SECURITY`, tenant guards, per-table GRANTs. Django's regenerated
  initial recreates tables and constraints and **none of that**. A squash is therefore a
  hand-merge of the highest-risk SQL in the repo, and per the RLS section above **no test
  can catch a mistake in it** — the test role bypasses RLS. Verify against the
  `runtime_connection` / `rls_enforced_orm` fixtures or you have verified nothing.
- **Every unmerged branch carries migrations on the current chain** (8 at the time of
  writing). A squash invalidates all of them at once.

So the window is: tree quiet, nothing long-lived in flight, **before the first real
database exists**. Earlier means doing it twice; later means never, because the first row
of production data ends it.

**It does not fix branch collisions, and squashing for that reason is a mistake.** Two
branches editing the same chain in parallel collide at any migration count — measured
2026-09-15, when master renumbered `funding/0030_cv_directives_undecided_unreadable` to
`0031` while the letter-engine branch built `0031_application_prompt` on top of the old
name. The merge was textually clean and the dependency pointed at a node that no longer
existed. What caught it was `makemigrations --check` in CI, which is already there.

## Python version: five declarations, one number

`requires-python`, ruff's `target-version`, mypy's `python_version`, `ci.yml`'s
`python-version` and the `Dockerfile`'s `FROM python:` must all name the same major.minor.
`tests/test_bootstrap.py::test_every_declared_python_version_agrees` enforces it.

This is not tidiness. `uv sync` builds the venv against `requires-python`, so when a
base-image bump moved the image to 3.14 while the pin stayed 3.12, the container got
`.venv/lib/python3.12` under a 3.14 interpreter and **could not import Django at all** —
web, worker, browser, portal and migration alike. Nothing failed: the test suite runs on
the host's interpreter, and until the `portal-sandbox` job existed CI never built an
image, so a dead container passed every check. Dependabot's docker updater reads `FROM`
lines and knows nothing about `requires-python`; it will propose the bump again, and the
test is what turns that from a silent break into a loud one.

Changing Python is therefore a five-file change plus a re-lock, never a base-image bump.

## Static files: tests cannot see a production-only failure

`config/settings/test.py` swaps in `StaticFilesStorage`; production (`base.py`) uses
`CompressedManifestStaticFilesStorage`, which raises on any `{% static %}` path missing from the
manifest. When a change adds templates or static references, run `collectstatic` under production
settings — the `Dockerfile` and CI (`ci.yml`) both run it now, so a missing path fails the build.

## Web fetching

**Every research page fetch goes through one seam: `apps/research/fetch.fetch_page`.** It walks a
ladder of vendor rungs — Firecrawl, then scrape.do, then the Internet Archive — and never our own
egress. Tavily is not in this path: it lost the fallback-vendor role to scrape.do on 2026-09-19 and
keeps only `/map` and name-to-site resolution, neither of which is a fetch. `robots.txt`/TDM
reservations and content retention are the fetching vendor's questions, not ours (owner decision
2026-09-18); aggregator pages are fetched for organisation names only, never as provenance. Design:
`docs/superpowers/specs/2026-09-22-fetch-engine-design.md`. The tier order and the cost measurements
behind it:
`docs/superpowers/specs/2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md` §4.

**The funnel, 2026-09-23.** Finding a programme's requirements pages is five stages, cheapest
first — the page's own document links, `/map` + D2 rank + `/crawl`, Tavily's guided `/map`,
Firecrawl `/agent`, then the recorded outcome — and `apps/research/sitejob.py` owns the order.
**Every stage returns URLs only**; each is fetched through the ladder and `require_origin`-checked,
which is what makes `/agent`'s open-web search safe rather than any vendor flag
(`strictConstrainToURLs` confines it to *exactly* the seeds and makes it useless). **The trap:
`GET /v2/crawl/{id}/errors` is read on every crawl and is not optional** — `completed == total`
on every finished crawl because failed pages are excluded from both counters, so a crawl read
from its status alone reports a perfect run over a site it half-read.

| rung | call | bought when | cost |
|---|---|---|---|
| 1 | Firecrawl `POST /v2/scrape` — `formats: ["markdown", "links", "html"]` plus `changeTracking`, a PDF parser at `FETCH_PDF_MAX_PAGES`, `blockAds`, `skipTlsVerification`, `onlyMainContent: False`, **no `proxy`** (deprecated; `auto` is the default and escalates to the enhanced proxy on 401/403/429 at no extra charge) | always, unless the host profile starts higher | 1 credit — **a PDF costs one per parsed page** (`firecrawl.py`: `credits = page_count`) |
| 2 | rung 1 plus `actions` (wait, scroll, wait) | rung 1 returned a **shell** | a browser-minute |
| 3 | scrape.do `render=false&super=false` | rung 1 got no document | 1 credit |
| 4 | scrape.do `render=true&super=true`, `sessionId` fixed per host | **only** an escalating failure — see the two questions below | 25 credits |
| 5 | the retry queue: a `FetchAttempt` row carrying `retry_after`, replayed by `manage.py retry_due_fetches` | rungs 1–4 all failed; three rounds, then rung 6 | free — **and it has no scheduler; see Erasure, below** |
| 6 | the Internet Archive capture (`web.archive.org/web/<ts>id_/<url>`), fetched through scrape.do | the three retry rounds are spent | scrape.do's |
| 7 | a person | — | **the ladder does not do this.** `fetch_page` deliberately never calls `record_blocked_source`: that row is tenant-scoped under FORCE RLS and the catalog read runs **tenantless**, where `current_tenant_id()` raises, so a bare call would crash every catalog read of a blocked page. The caller inside a `tenant_scope` files it (`pipeline._open_task`). |

**`Outcome` has twelve members — eleven terminal plus `RETRY_SCHEDULED` — and `fetch_page` returns
every one of them rather than raising.** That is the reason the engine exists. Before it, a blocked
fetch and a page that genuinely states nothing arrived at the reader as the same thing, and this
file records the repo meeting that failure twice (the markdown body, and the JS shells). A refusal
now carries the rung that earned it, the reason, and the whole attempt trail. Only a programming
error leaves `fetch_page`.

**The one place values become exceptions again is `discovery.retrieve_official_source`, and it is
the boundary on purpose.** All eight callers of it predate the engine and are written against a
raised `SourceBlocked`, so an unserved outcome becomes one there — a refusal returned to them
instead would arrive as an *empty success*, the worst failure documented in this file. New code
calls `fetch_page` and reads `page.outcome`. What the translation collapses — which rung answered,
what it cost, whether a retry is already scheduled — survives on the `FetchAttempt` rows.
`UNCHANGED` is served, not refused: Firecrawl builds it from the same payload as a `FETCHED` page,
body and all, and the reader's digest short-circuit needs those bytes.

**Every `fetch_page` call writes a `FetchAttempt` — on every rung — and every terminal one writes a
`HostProfile`, and both tables are writable only by `runtime_engine`** (`runtime_engine_write`,
repointed from `catalog_ingestion` by `apps/funding/migrations/0049_catalog_grants.py`). Until
2026-09-25 that role could not log in, so every fetching command ran under
`DATABASE_ROLE=migration`; that stopgap is over — every worker task definition runs as
`runtime_engine`. Under `runtime_web` the first rung fails with `permission denied`, on purpose: a
student-facing fetch queues to the worker. **No superuser test sees the RLS half of this; the
`role_connection` fixture does.**

**`HostProfile` remembers only expensive rungs, and only ever downward.** Success at rung 3 or 4
writes `start_rung`; success at rung 1 or 2 *resets* it to 1. A memory that can only entrench a cost
is a tariff, not a memory — so a host with `start_rung > 1` and a `last_probe_at` older than
`FETCH_REPROBE_DAYS` is tried once from rung 1 first. A `BLOCKED` outcome sets a cool-off that
doubles from six hours and stops at a week; anything carrying bytes clears it.

**`credits_30d` and `attempts_30d` are not what their names say, and nothing reads them.** Both are
incremented only inside `remember()`, and a `RETRY_SCHEDULED` stop never reaches it — so they miss
every credit spent on a URL that ends in a scheduled retry, which is exactly the hosts that fail
most. Neither decays, either: they are downward-biased **lifetime** totals wearing a 30-day name.
Whoever builds the per-domain surcharge guard they were added for should sum `FetchAttempt` rows
(`credits`, `created_at`, `sweep_id` are all on the row) and treat these two columns as a rename
waiting to happen.

**Social hosts are a third path, and the rule reversed on 2026-09-24.** They were not fetched at
all; they are now read through **Browser Use** (`browser-use.com`, remote browsers on the vendor's
own infrastructure, $0.02/browser-hour, agents at model cost + 20%). **Owner decision, taken on
their lawyer's advice** — Meta's terms §3.2(3) still forbid automated access "without our prior
permission", and Browser Use's own Terms bar "data mining, robots, scraping", place compliance
solely on the customer and carry an indemnity; the owner took counsel with those clauses stated.
The advice moved, not our reading of the terms. What did **not** change, because none of it rested
on the terms:

- **A social post is a pointer, never provenance.** `facebook.com`, `instagram.com`, `x.com`,
  `linkedin.com`, `bsky.app` stay on `AGGREGATOR_DOMAINS`, so `is_catalogue` still refuses them as
  catalog rows. They give a **name and a link**; the origin is fetched and verified; the claim
  cites the origin.
- **Nothing about a person is ingested** — commenters, reactors, followers and subscriber lists
  are discarded at the boundary.
- **No vendor is ever pointed at a portal.** Browser Use reads public pages, exactly as Firecrawl
  and scrape.do do. `apps/portals/` still hands a CAPTCHA to a human, because that rule is about
  circumventing an access control on an authenticated system and was never about cost or terms of
  fetching (see "Application automation" below).

Master design §6.4 carries the full record, including the superseded text.

**What lands in `FetchedPage.body` is HTML, and that is not a preference.** Firecrawl is asked for
`formats: ["markdown", "html", changeTracking]` with `onlyMainContent: False`, and the **html** is
what becomes the body at `content_type="text/html"`. Four consumers parse markup off that body —
`harvest.anchors` (every `HtmlCatalogue` in `seeds.py`, and the aggregator hop in `harvest.py`),
`search._sitemap`'s `ElementTree`, `reader.readable_text` and `harvest.content_digest` — and
markdown has no `<a href>`, no `<loc>` and no `<main>`. Shipped once as markdown, it cost: EACEA and
DAAD yielded **zero leads in silence** (the run reports success, `blocked` equal to the lead count),
every AGGREGATOR lead became "no official programme link", and `content_sha256` was permanently
empty, so the unchanged-page short-circuit never fired — **six model calls per `read_program_page`,
every run**, which is the opposite of what `changeTracking` was bought for. The whole suite passed,
because every test stub returned HTML. `onlyMainContent` must stay **False**: anchor harvesting reads
exactly the navigation links it strips, and `readable_text` does its own main-content narrowing
anyway. Both formats cost the same one credit; only the JSON format adds 4.

**scrape.do reports the URL it landed on, in `scrape.do-resolved-url`, and that is what
`final_url` is.** Redirection is left on, the header is read through the existing case-insensitive
lookup, run through `validate_public_url`, and **absent is a failure, never a fallback to the
requested URL** — the same rule Firecrawl's `metadata.url` gets, for the same reason: falling back
asserts "it did not move" on the one response carrying no evidence for it, which is exactly what
`reader.require_same_origin` then checks. So that guard compares two real origins on both tiers.
The earlier design — `disableRedirection=true` plus refusing any non-2xx
`Scrape.do-Initial-Status-Code` — rested on a capture taken at the **1-credit** tier. Measured
2026-09-19 at `render=true&super=true`, the only tier we ever reach scrape.do on, the response
carries `scrape.do-resolved-url` and `scrape.do-target-url`, and reports initial status **301** for
`https://globed.eu/how-to-apply/` — a Cloudflare bounce landing on the identical URL. The guard
refused that page and was billed 25 credits for refusing it. The initial status is still read, for
the log only. **The limit, exactly:** for HTTP redirects the resolved URL is the landed location;
for a meta-refresh or a JS navigation under `render=true` it is *plausibly* the browser's final
location — undocumented, unmeasured, and not to be written down as closed.

**A vendor failure answers one of two different questions, and the router acts on which.** Both
`VendorUnavailable` and `ChargedFailure` carry `escalate`. *"This host beat us"* — Firecrawl's
HTTP 200 + `success: false` ("all scraping engines failed"), a relayed 403, its own 408 — earns the
25-credit residue tier, because that is what the residue tier is for. *"Not now"* — an outer 429, a
5xx, a dropped connection, a 402 — does not: the host was never asked, so a second vendor answers a
question about **us**. Firecrawl's free tier is 10 requests/minute and a `discover` sweep paces per
**domain**, so 58 distinct hosts go out at 30–60/minute; before this, most of that sweep 429'd and
**every 429 spent 25 credits on a page Firecrawl would have served for 1 a minute later**. The
provider now backs off and retries instead, reusing `egress._backoff_seconds` / `_RETRY_ATTEMPTS`
(`Retry-After` honoured) rather than a second implementation, and the message says "vendor
throttled, retry later" because `pipeline.py` files it verbatim as a consultant task. A dead link is
the same mistake from the other end: Firecrawl bills 1 credit for a target 404, and **scrape.do's
published billing counts 2XX, 400, 404 and 410 as *successful* requests**, so escalating one costs
1 + 25 credits and returns a 404 page. 404 and 410 do not escalate; 403, 401, 429 and 5xx do.

**A sweep's credit ceiling is checked AFTER the vendor reports the cost, so it is an alarm and not
a guard.** scrape.do's per-domain multiplier (10–200 credits) is applied server-side and is not
knowable before the request, so `SweepBudget.spend` records the overspend and the *next* rung's
`check` is what stops the ladder — one surprise lands, once per sweep rather than once per page.
**The control that cannot be outrun is configuration, not code: a per-key credit spend limit set in
each vendor's dashboard** (`docs/runbooks/deploy.md`). It survives a bug in `SweepBudget`; nothing
in the codebase does. Every figure the ladder uses is a setting with an env override
(`FETCH_SWEEP_CREDITS`, `FETCH_MAX_RETRIES`, `FETCH_RETRY_HOURS`, `FETCH_REPROBE_DAYS`,
`FETCH_PDF_MAX_PAGES`, `FETCH_ARCHIVE_MAX_AGE_DAYS`, `FETCH_BUDGET_RETRY_HOURS`).

Three things keep a first-party transport instead of a vendor, each for its own reason:

- **`apps/documents/europass.py` (europa.eu).** It POSTs a student's name, date of birth,
  education and employment history in a four-call stateful cookie/XSRF session — not a page a
  fetcher scrapes once. Its transport resolves the host, then connects to the *validated address*
  with `assert_hostname`/`server_hostname` pinned and `redirect=False`, closing the
  DNS-rebinding window on the one path carrying student PII. No vendor session could carry this,
  and none is asked to.
  **`fetched_via="EGRESS"` — the label that names our own client — is held to this one host by two
  tests** in `tests/research/test_fetch_ladder.py`: no page *carrying bytes* leaves the ladder
  labelled EGRESS (the refusals are labelled EGRESS on purpose — `FETCHED_VIA` admits no "nobody",
  and a page with no bytes has no provenance to lie about), and only four code sites in `apps/` may
  mint the label at all, checked by an `ast` walk over every assignment, annotated assignment and
  call keyword named `fetched_via` — not a regex, which a reviewer showed passing on the same label
  spelled with single quotes. Its one residual gap: an *indirect* assignment through a module
  constant (`fetched_via = _SOME_LABEL` where `_SOME_LABEL = "EGRESS"` is defined elsewhere) is
  invisible to it, because the walk only inspects the expression written at the `fetched_via` site,
  never a name's definition elsewhere in the file. Both structural and runtime halves are needed:
  `snapshot.persist_snapshot` copies `fetch.fetched_via` onto the snapshot row unexamined, so a new
  first-party rung would inherit `FetchResult`'s default and write a true-looking provenance row
  that no downstream assertion could catch.
- **`egress.fetch_json_api`.** Contracted APIs carrying our own keys — not content a vendor
  should see or bill for extracting.
- **`egress.fetch_data_file`.** **XML sitemaps** (`search.sitemap_urls`) and the JSON fixture in
  `services.py`. It was written for DEQAR's daily CSVs; that caller left with the
  institution-safety screen on 2026-09-14 and the transport stayed, because the sitemap case is
  the same case. Firecrawl hands back markdown or its own processed HTML, and neither is a data
  file; scrape.do's `output=markdown` does the same and cannot be told not to. A file meant to be
  parsed as data is fetched as bytes, not read as a page. The sitemap case is measured, and its
  failure mode is worth knowing because it is not the obvious one: Firecrawl's `html` for
  `globed.eu/sitemap_index.xml` is a **browser-viewer wrapper** — the XML declaration turned into an
  HTML comment and the root wrapped in `<html><body>`. It does not fail to parse. It parses with
  root tag `html`, so `search._sitemap`'s index hop never fires, it returns the child sitemap
  *files* as if they were content URLs, the funding-path filter drops every one of them, and
  `EntityExpansionSource` yields **zero programme URLs per organisation while reporting success**.
  Never unwrap a vendor's markup and never ask for `rawHtml` to get around this; fetch the bytes.
  (PDFs are the opposite case and stay with Firecrawl: its `html` holds the document's own parsed
  text — measured on the Rhodes CV template, 1 credit — so a PDF never reaches scrape.do at all.)

Four more outbound paths are data sources rather than fetches, and are listed here because
they are outbound and deliberately not vendor traffic:

- **Every EMJM, and who awards it → the EACEA project API.** A JSON API, not a page to
  scrape. **It is the complete EMJM list, not a supplement:** every EMJM is an EU-funded
  project, so the funder's own project records are the authoritative catalogue. Measured
  2026-09-14 and re-measured 2026-09-15: **415 projects — 166 under the 2021-2027 action
  code, 249 under 2014-2020** — 2,026 participation rows and 576 distinct organisations.
  Per organisation it carries name, country, city, **EU-PIC** and website, which answers
  the question the HTML catalogue cannot: **which universities award a joint programme**.
  For scale, `seed:eacea`'s HTML catalogue yields 169 leads.
  **The catalogue is still what the pipeline harvests today** (`pipeline.py::default_sources`
  registers `EACEA_ERASMUS_MUNDUS` and nothing else), and it is not redundant — it links to
  each consortium's own site, which is the origin a claim must come from, where the API
  gives the roster. `manage.py enumerate_eacea` (build item 7, `apps/research/eacea.py`) now
  writes every project and a PIC-first partner binding into the register; matching a project
  to a `Program` row is still a person's job. It is operator-run and read-only toward the
  network, and anything that *schedules* it must first put the fetch behind
  `LocalEgressProxy`. **Its project-level keys (`projectIdentifier`, `title`, `startDate`,
  `endDate`) are unverified placeholders**: egress to `ec.europa.eu` was blocked when the
  adapter was written (2026-09-26), so its fixture is hand-built from the 09-14 design's
  documented organisation keys. A wrong project key yields zero projects, which the gate
  reads as `listed != printed`; capture one live page before the first real run.
  - The endpoint is **`POST https://ec.europa.eu/programmes/service/search/project/search`**,
    and it answers **200 to plain `curl`** — no browser, no session, no token.
  - **The 403 is two URL families, not a platform that refuses us.** Re-measured 2026-09-14:
    `erasmus-plus.ec.europa.eu/projects/search/details/<id>` returns 403 (still true, and
    why `seeds.py` stopped harvesting it), `/projects/search` returns 200, and the API
    above returns 200. The wider reading cost three wrong attempts. The second family:
    `webgate.ec.europa.eu/eyp/valor/api` 403s on every path and is a base string the
    page concatenates at runtime, never the host actually called.
  - **The filter field is `projectLevel3`.** `level3` and `actionType` are accepted,
    silently ignored, and return the whole corpus — 341,611 projects on 2026-09-15, a
    full-corpus fetch that looks exactly like a successful filtered query. The two action
    codes are `43690363` (2021-2027) and `31046261` (2014-2020), and **both are needed**.
    Assert the total against the hundreds, never the hundreds of thousands.
  - **Persisting this is permitted, and that does not generalise.** EACEA's terms govern
    uploading and point retrieval at the Commission's open-reuse notice. The
    never-persist-a-provider-result rule below governs *search providers*, whose licences
    forbid retaining results. Do not carry either rule onto the other.
- **Korean programmes → an anonymous XLSX; Korean institutions → a keyed JSON API.** Two
  data.go.kr datasets, both KOGL (free, 이용허락범위 제한 없음), and the split between them is
  the whole point — **neither file is served from where its catalogue card lives.**
  Spec'd and measured 2026-08-28, **not built**: nothing in `apps/` mentions `data.go.kr`.
  Full detail and the field lists:
  `docs/superpowers/specs/2026-08-28-funding-led-discovery-design.md` §"Korea".
  - **Programmes — dataset `#15139338`.** data.go.kr holds only metadata (제공형태
    *기관자체에서 다운로드*); the file itself is served by 대학알리미 (`academyinfo.go.kr`) as
    `학교별 교육편제단위 정보_20241007기준.xlsx` to an **anonymous GET, no key**. School →
    college → department/major → degree level. **55,228 rows over 1,880 institutions**, of
    which **12,169 live master's-bearing rows across 1,185 institutions** — the largest
    single supplier in the build by an order of magnitude.
  - **Institutions — dataset `#15107736`.** Its file download 404s anonymously; the Open API
    (`api.data.go.kr/openapi/tn_pubr_public_univ_info_api`) needs a service key and is the
    only route. Seventeen fields, and **`홈페이지주소` is the institution website** — which is
    exactly what `OrganisationFrame` exists to fetch from ROR, so Korea's frame comes direct
    and current with no ROR join. Registration also escapes the 50,000-row grid ceiling; it
    buys nothing for the programme list, which is already anonymous.
  - **49.1% of the programme rows are dead, and they look alive.** 27,124 of 55,228 are
    폐과 — abolished departments the dataset keeps for statistical disclosure, warned about
    in its own 기타 유의사항 and repeated inside the workbook on sheet row 2. `학과상태`
    partitions them: eight live values (기존, 신설, 변경[신설]…) against four 폐지 values. An
    adapter that ignores the field emits a catalogue half-full of departments nobody
    recruits for, each as claim-capable-looking as a live one.
  - **`학위과정` is a comma-separated multi-value string, not an enum.** Eleven raw values
    (`석사`, `석사, 박사`, `석사,박사, 석박사통합`, `학석사통합`, `전문기술석사`…) with
    inconsistent spacing after the comma. Substring match; equality against `'석사'` silently
    drops the **8,117** rows where master's is bundled with a doctoral track.
  - The file is dated `20241007` against a stated 수시/자동갱신 cycle, so it lags. Official and
    current are different properties.
- **Wikidata SPARQL → `apps/research/wikidata.py`.** CC0, operator-run
  (`manage.py enumerate_wikidata`), read through `egress.fetch_json_api` with the SPARQL JSON
  content type named explicitly (`accept=`). It writes `CANDIDATE` only and never vouches: a
  crowd-sourced count is never a denominator, so its lists are `is_denominator=no`. The query
  pins class, the P576 dissolution filter and P856 website, and the module docstring quotes
  them. `WIKIDATA_USER_AGENT` carries a contact because Wikimedia's User-Agent policy throttles
  or refuses a generic client. Its row bounds were set from spec §6.2's 229 and have **not**
  been tightened against a live count (egress blocked 2026-09-26).
  **Build item 8 reads it two more ways, from the same module:** the entity API
  (`wikidata.find_item`) as the name→site resolver's first stop — an exact label or alias in
  the right country (P17), not dissolved (P576, including an undated `somevalue`), and only when
  exactly one item passes; a fuzzy top hit is never a match — and the query service
  (`wikidata.sparql`) for the resolver's vocabulary (`manage.py build_resolver_vocabulary`,
  committed under `apps/research/resolver_data/`). **Those files do not exist yet**: the build is
  owed to the first environment with Wikidata egress, and until then `resolve_register` refuses
  with `VocabularyMissing` and the committed-data tests skip.
- **The resolver's residue → Diffbot Enhance** (`apps/research/providers/diffbot.py`). One
  homepage URL per name, `type=Organization` only, nothing else read or kept; 400 entities a
  month metered on `RegisterEntry.diffbot_asked_at`, which only `--write` records — so
  `resolve_register --diffbot` needs `--write`, and `--write` is off until the resolver's
  fresh-script hold-out passes (`RESOLVER_WRITES_ENABLED`). Its terms carry no effective date, so
  both `resolve_register --diffbot` and `resolver_gate --diffbot` refuse unless
  `DIFFBOT_TERMS_READ_ON` is within 31 days; they were **not** re-read when this was built
  (`docs/legal/2026-09-provider-terms.md`).
- **ROR v2 → `apps/research/ror.py`.** CC0, an exact `domains:` lookup and a country × type
  enumeration only — never a name lookup's top hit ("the fuzzy top hit is sometimes a
  different organisation", spec §6.2). Gated: `manage.py ror_gate` must show ≥ 95% website
  agreement on the 58 yield hosts before ROR writes anything, and the enumeration half (build
  item 7, Task 11) is **not built** because that gate has not been run live.

Both are operator-run and read-only toward the network; anything that *schedules* them must
first put the call behind `LocalEgressProxy`, the same rule the EACEA bullet states.

- **LLM calls → the OpenAI SDK**, plus the Anthropic SDK for one CV-format judge reading
  (`derive._claude_reading`). Not a fetching concern.

The rest of this section is the record of why the deleted tier existed and how it was retired —
kept because the measurements in it are the answer the next time someone proposes a browser
again, not because any of it still runs.

- **Why a research browser existed at all, and why it does not now.** A JS-only render path
  (Scrapling's `StealthyFetcher`, behind `LocalEgressProxy` for the SSRF guard, `block_webrtc` on
  to stop it leaking the local address around that proxy) covered pages a plain fetch could not
  read. The owner lifted the "no paid solving service is ever added" limit on 2026-09-19 when
  scrape.do was adopted: a vendor solving a challenge from its own address does not spend the
  shared egress address that limit was protecting, so a rented solver replaced the in-house one at
  a fraction of the operational surface. **This never touched portal automation** —
  `apps/portals/` still detects a CAPTCHA and hands it to a human (§5.2), because there the agent
  acts as an authenticated applicant and `phased requirements.md` §2 and §3.4 (numbered §3.6 when
  this was written) forbid circumventing a portal's access controls. That rule was never about
  cost and the vendor switch does not touch it.
- **The Chromium sandbox is unavailable on Fargate — do not spend a day rediscovering this.**
  Chromium launches with `--no-sandbox` because Playwright pushes it whenever `chromiumSandbox
  !== true`, and the flag cannot be flipped on our platform: Fargate does not permit unprivileged
  containers to create user namespaces (an open request on the AWS containers roadmap, issue
  #2102), and neither workaround is available to us — Fargate allows *dropping* capabilities but
  not adding `CAP_SYS_ADMIN`, and custom seccomp profiles are an EC2-launch-type feature. Passing
  `chromium_sandbox=True` on Fargate does not degrade gracefully; Chromium fails to launch. It
  does work on an ordinary Linux host with unprivileged userns enabled, which is exactly why this
  is worth writing down: it will test fine locally and break in production.
  Measured on our own account (us-east-1, 2026-08-26), not taken from the roadmap issue: a
  Fargate task running `unshare --user --map-root-user true` on `ubuntu:24.04` exited 44 under
  a probe whose codes separate a missing binary (43) from a refused syscall (44). The binary is
  present and the kernel refuses it. Re-measure before believing any future claim that this
  changed -- it is a throwaway cluster, one task definition and three API calls.
- **The browser did not run in a task holding application credentials, and that was
  measured, not assumed.** It existed because the sandbox could not be the answer:
  `WorkerTaskDefinition` carried `POSTGRES_RUNTIME_PASSWORD`, `DJANGO_SECRET_KEY` and
  `WorkerTaskRole`, and a browser process that is a *child* of the worker reads
  `/proc/self/environ` and has the database, whatever the container hardening says. So
  `apps/research/browser_server.py` served `POST /render` in its own ECS task
  (`BrowserTaskDefinition`), and that task had **no `TaskRoleArn` at all** — stronger than an
  empty role, because it means `169.254.170.2` has nothing to hand out even if something on the
  task asked. Design: `docs/superpowers/specs/2026-08-26-browser-isolation-design.md`.
  **Measured, 2026-08-26.** Earlier attempts to show that secrets reach the browser process were
  methodologically broken and returned null results; the working method is to read the
  *Chromium* process's own `/proc/<pid>/environ` while a render is in flight. Run with secrets
  in the container's environment (the old worker shape), that environ contained
  `DJANGO_SECRET_KEY`, `POSTGRES_RUNTIME_PASSWORD` and `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`.
  Run as `BrowserTaskDefinition` actually configured it, it contained none of them.
  `--no-sandbox` was still on the live command line — what the task-role removal changed is that
  escaping the sandbox yielded nothing. Do not re-derive this if a browser tier is proposed
  again; the exposure and its removal are both demonstrated, on this account, on this date.

### Search providers: what may be kept

A sixth outbound path is coming — a live-search `LeadSource` that discovers URLs. Its terms question
is settled; the rules that keep it settled are not self-enforcing.

- **Exa and Brave are permitted, under written permission carrying one condition: no
  competing-search training.** Owner, 2026-09-17. Both were previously barred here by their own
  definitions — Brave's ToS defines "Search Results" as "**any outputs from calls made to the API**",
  barred "in whole or in part", and Exa §4.2(a) bars reproducing anything "obtained from or through
  the Services". That reading was correct against the public terms and is now superseded by the
  grant, not by a re-reading. **The condition is the live constraint:** their output may not train a
  competing search index. So no embedding corpus, no learned reranker, no derived index built from
  provider results — the day someone proposes "we could train a ranker on what Exa returns", this
  line is why the answer is no.
- **The retention prohibition is lifted; the discipline is kept anyway.** With storage permitted,
  "never persist a provider result object" is no longer a terms requirement — and it stays, on
  merits. Only a URL is read from any provider response; the origin is then fetched and validated;
  nothing from a provider object is persisted. A snippet is a vendor's rendering of someone else's
  page, it goes stale silently, and a SERP cache is a second source of truth for a question the
  origin already answers. Keep it because it is right, not because a contract said so.
- **Provenance comes from the origin, never the provider.** What lands in `OfficialSource.canonical_url`
  is a URL *we* fetched and verified against the institution's own server; the snapshot, digest and
  `final_url` are all origin-derived. The provider was a pointer, and a pointer is not retained as a
  provider artifact. **This one was never a terms rule**, so nothing about the Exa/Brave grant
  touches it. The clauses themselves are quoted in `docs/legal/2026-09-provider-terms.md`; Exa's
  `/search` restricted to an institution's domain is the research-fit site search
  (`apps/research/providers/exa.py`).
- **Tavily's terms are still the cleanest and it keeps its jobs, but it is no longer "the provider".**
  Its restrictions attach to "the Services", which it defines to exclude "Output", so its retention
  is permitted by structure rather than by silence — which is why it remains the fetch/extract path
  (owner decision 2026-09-15) and the name-to-site resolver. Provider *choice* is now settled by
  measurement instead: **the roster lives in
  `docs/superpowers/specs/2026-09-17-role-routed-discovery-design.md` §4.13**, one table with each
  source's role, its measured-best configuration, its terms standing and its ceiling. Read it before
  adding, swapping or re-proposing a provider — it also records what was **rejected and why**
  (Perplexity, Yandex, Seznam, Coc Coc, Mojeek, Google Custom Search), which is the part that
  otherwise gets re-derived. Google-derived indexes remain unusable as a source of catalog rows:
  SerpApi cannot grant rights to indexes it resells, so Google via SerpApi is a transient yardstick
  only. Baidu and Naver via SerpApi are the roster's one recorded exception (owner decisions
  2026-09-17 and 2026-09-18: free tier, no legal shield — §4.13 and §8 carry the position).
  **Still true of any index whose terms have not been read: definitions decide this question, not
  caching clauses.**
- **Tavily §3.2(xvi) forbids** using Output "to make automated decisions without human oversight that
  have a significant adverse impact on individual rights in high-risk areas". Education is not
  enumerated there, which is the leg this rests on. **Whether that leg carries the clause on its own
  is an open legal question** — it belongs with §10's unresolved privacy items, not in a comment.
  Do not treat it as settled.

  What this note used to say — that every recommendation is counselor-reviewed — is false, and was
  false when written. `phased requirements.md` §38 publishes the pool and pack to the student
  immediately, *deliberately* un-gated by counselor review, because a gate would add a day of
  latency for a check the agents already perform. `apps/funding/services.py` says the same in its
  own words: "No counselor approval, no `Approval` row". So for recommendations, the "agent decides
  unaided" case this clause is about is not hypothetical — it is what ships.

  Human oversight is real, but it sits **downstream** of recommendation, at the two places §38 puts
  it: document approval (`apps/documents/approval.py`, recorded as `ConsentEvent`), and application
  execution, where the agent escalates to a consultant on six triggers — `MISSING_FACT`,
  `PERSONAL_ATTESTATION`, `APPLICANT_MFA`, `UNSOLVED_CHALLENGE`, `AMBIGUOUS_DECISION`, `PORTAL_ERROR`
  (`apps/portals/escalation.py`). A compliance argument may rest on those. It may not rest on a
  counselor gate over recommendations, because there isn't one.

  Read the clause before proposing any further unaided-agent feature.

Evidence, provider comparison and the adjudication of two conflicting research runs:
`docs/superpowers/research/2026-08-30-live-search-synthesis.md`.

## The institution-safety screen was removed — 2026-09-14, and this is the record

**Deleted:** `apps/research/registers.py` (the DEQAR and WHED readers), `manage.py
refresh_register`, `manage.py load_institution_identifiers`,
`docs/research/institution-identifiers.csv`, the `InstitutionIdentifier`, `RegisterListing`
and `RegisterCoverage` models (migration `0032`), `Institution.kind`/`parent`, and six test
modules. ~2,900 lines. **Do not rebuild any of it without reading this section first.**

**Why.** The screen answered one question — *is this institution on a list* — and accreditation
is not a product requirement: `phased requirements.md` and `idea_v2.md` contain zero mentions of
accreditation, recognition or diploma mills. It came from a 2026-08-31 research track whose own
design names the fear it defends against: *a convincing website is enough to enter the
catalogue*. That is true of exactly one door, open-web search, and **provenance answers it more
cheaply than a register does** — a funder's catalogue or a ministry's register is already a list,
and a human confirming an unknown institution is a list. Registers also cover less: DEQAR is
EHEA-only, WHED is ~21,000 institutions, and neither answers the question families actually ask
(*will this degree be recognised back home*), which the research itself routed to a consultant.

Nothing ever read it. `screen.py` was never built, `RegisterListing` appeared only in its own
migration, and the whole system held **one** binding row (`institution:houston`, IPEDS), which
neither register matched. Keeping it dormant was not free: three tables every schema, erasure and
tenant-isolation sweep must account for, a 737-line module inviting someone to finish it, and a
note whose only job is to say "don't".

**The door this leaves open, stated plainly.** `EntityExpansionSource` is active whenever
`pipeline.py::default_sources` receives a search key. It walks each search-found organisation's
own host, yields `DIRECT` claim-capable leads, and `write_catalog_entry` mints an `Institution`
from any of them — **with nothing marking it unconfirmed**. That is safe today only because
discovery is operator-run, has no production caller (`apps/research/services.py` still fetches a
placeholder URL) and no scheduled run carries a search key. Every seed in `default_sources` is a
body that vouches by listing: EACEA selects and funds each consortium; the planned Korea
(`data.go.kr`) and Finland (`konfo`) sources are ministry registers.

**So, before either of these — not after:**

- a scheduled or production discovery run carrying a search key (`phased requirements.md` §7), or
- a seed added to `default_sources` that is not a funder's or a ministry's list,

**build the provenance guard, which is not a register.** An `Institution` created from a
non-vouching source is not student-facing until a human confirms it, through the §2.6
consultant-task pattern the pipeline already uses for blocked sources. A flag and a queue. A
content farm's programme is student-facing the moment it is written, so this is the deadline.

**What would justify registers coming back**, and it is a product decision rather than a safety
one: selling *"every university verified against official registers"* as a feature. WHED's
one-lookup-per-institution is the cheap shape for that; DEQAR's daily 103 MB file is not. Decide
it as marketing, with a spec, not by reviving this.

**The expensive part was never the code.** The research, the measurements and IAU's consent
survive in `docs/superpowers/research/2026-08-31-*`, `2026-09-11-whed-recon.md` and the specs
`2026-08-31-institution-safety-screen-design.md` / `2026-09-11-deqar-register-adapter-design.md`
— including the rehearsal numbers worth having if this ever returns: 375 MB peak RSS for DEQAR's
103 MB file, and S3 bucket versioning being load-bearing (an unversioned bucket silently records
the string `"null"` for every snapshot). Those documents are now **history, not plans**.

**Two designs this supersedes in part.** The 2026-09-14 EMJM partner-source design keeps its
purpose — *which universities award a joint programme*, for the student's report and
`evaluation.py`'s LOCATION gate — but its join no longer goes through a register: EACEA already
supplies name, country, city and website per organisation, so a binding resolves against our own
`Institution` rows directly. And the 2026-09-14 scheduled-work design's `refresh_register`
schedule (§5.2) is void; `catalog_ingestion` itself was dropped 2026-09-25, and `runtime_engine`
writes the other catalogue tables.

### Recognition returns behind the provenance gate — 2026-09-26

Owner decision, 2026-09-26: recognition returns, to keep fake universities from students and to
judge recognition at home in Azerbaijan. This section's condition for bringing registers back ("a
product decision") is met. Registers return as **evidence sources behind a gate**, not as the
deleted screen (`docs/superpowers/specs/2026-09-26-institution-provenance-gate-design.md`, plan
`docs/superpowers/plans/2026-09-26-provenance-gate.md`). The open door above is closed at
`candidate_pool`. A programme is admissible only when its OWN evidence domain
(`Program.evidence_domain`) is a `RECOGNISED` body's bound domain. The `Institution` row and
`Institution.official_website` decide nothing, because they are found by name.

- **The switch is `PROVENANCE_GATE_ENFORCED`, on by default since 2026-10-03 (verified-only: no
  unconfirmed body reaches a student, whoever placed it).** A database that held data before the
  gate: set it off, run `backfill_evidence_domain` then `provenance_check --all`, then turn it on.
  One template parameter, `ProvenanceGateEnforced`, feeds web and worker; order: `deploy.md`.
- **Forward rule (§7.5):** whatever first creates a `portals.Application` checks the candidate's
  tenant copy `provenance_reason_code` and refuses a BLOCKED one. Nothing creates one today.
- **Schedule requirement (§7.6):** `ProvenanceRecheckRule` (daily, `provenance_recheck`) ships
  ENABLED and must stay so before any real student. Without it UNCONFIRMED is never retried and a
  good school is lost silently.
- **The State Programme PDF is the one stated exception to "PDFs go to Firecrawl" (§6):** a data
  table, parsed as bytes through `fetch_data_file` into a reviewed closed list. It is never a page
  read. Not built yet; Plan 2 needs it.
- **Jev goes through OpenRouter** (`apps/research/jev.py`, the provenance vetoes' client;
  `JEV_API_KEY` from `OPENROUTER_API_KEY`; `JEV_MODEL` pinned). It is a second Jev client beside
  the typed-decision layer's `apps/research/decisions.py`; unifying them is an open design
  decision. It only ever vetoes, and it is skipped and recorded when unkeyed.
- **Register terms are recorded, never a gate** (owner, 2026-09-27). HRK Hochschulkompass permits
  personal use only and is read anyway; its data file sits on `hs-kompass.de`, so it counts only
  because the vouched `hochschulkompass.de` downloads page links it. Korea's register needs no key
  (anonymous JSON, served as `text/html`).
- **Coverage is five countries** (GB, DE, KR, TR, AZ). A body elsewhere is UNCONFIRMED with reason
  `no_register`, visibly, until a register or WHED is added.
- **Verify, don't assume:** verdict writes are proven as `runtime_engine` (`role_connection`), and
  the sweep and the named-programme worker through `rls_enforced_orm`, because the test role
  bypasses both.

## Two browsers, two opposite security models — both deliberate

> **Direction change, 2026-09-15 — read before touching the portal row.** The portal tier below is
> being replaced by a browser extension that fills the portal in the *student's own* logged-in tab,
> with the student pressing Submit (`docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md`).
> Its security premise is a third one: nothing of ours is in the browser to steal — no portal
> credential exists anywhere, the model key never leaves the server, and the extension holds only a
> revocable device token for one membership. The EC2 tier, `PortalTaskRole`, `PortalSecurityGroup`,
> `auth.py`, `profiles.py`, `engine.py`, `resolve.py` and `dispatch.py` are retired by a separate
> deletion plan once the extension passes the ported tests; until then they stay dormant at
> `PortalDesiredCount: 0`. Everything the table says about the research browser still holds.

This system used to run Chromium in two places on **opposite** premises — a credential-free
research browser (`BrowserTaskDefinition`, "there is nothing to steal") and an authenticated
portal browser (`PortalTaskDefinition`, "the sandbox holds"). The research browser is gone
(retired with the rest of the Scrapling tier, see Web fetching above); the measurement that
justified its premise — the task's own `/proc/<pid>/environ` carried none of the worker's
secrets — is kept there as history, for whoever proposes a research browser again. What remains
is the portal tier, and its premise was never the credential-free one, so the deletion of the
other tier changes nothing about it:

| | `PortalTaskDefinition` |
|---|---|
| Task role | `PortalTaskRole` |
| Database role | `runtime_web` — no grant on the catalogue (`PortalExecutionRole` cannot read the engine secret) |
| Secrets in the process | DB password, `ANTHROPIC_API_KEY`, per-tenant portal logins |
| Launch type | **EC2** |
| Renderer sandbox | engaged, and required |
| Security rests on | **the sandbox holds** |

The portal tier cannot take the credential-free route. It must act **as the student**, authenticated: it
reads field maps and writes the §5.5 audit trail while it types, so a credential-free
portal task cannot do its job at all. Its mitigation is the renderer sandbox
(`apps/portals/engine.py` refuses to run without it), and the EC2 launch type exists
solely to make that sandbox possible — Fargate cannot grant the unprivileged user
namespaces it needs. **`LaunchType: EC2` here is load-bearing security, not a deployment
preference.** Moving the portal service to Fargate silently removes the only thing
standing between a hostile portal page and the database password.

Consequences worth stating, because each is a plausible "cleanup" that breaks something:

- `DatabaseSecurityGroup` admits exactly `WebSecurityGroup`, `WorkerSecurityGroup` and
  `PortalSecurityGroup` — the research browser's security group is gone along with the tier, and
  re-adding one to reach Postgres would be the same mistake the original design avoided.
  `tests/infra/test_template.py` pins the list.
- `WorkerTaskRole` holds `secretsmanager:DeleteSecret` on `tehsil/portal/*` because
  `advance_deletion` must destroy portal credentials on the same path it deletes
  documents. Remove it and GDPR erasure fails with `AccessDenied`, leaving a deleted
  student's portal passwords behind.
- `PortalDesiredCount` defaults to **0** — the tier ships stopped, gated on §10's
  portal-terms blocker. Turning it on is a separate decision, and the pause/hand-off/resume
  spike listed as untested below is a prerequisite for that decision, not for merging.

## Application automation (Phase 3) — decided in advance, and now partly built

> **Direction change, 2026-09-15.** The agent-fills-for-the-student model is retired in favour of
> the glass-box co-pilot: a Manifest V3 extension paired invisibly to the dashboard session fills the
> visible portal tab from a server-minted fill packet, attaches approved PDFs through the existing
> `download_document` route, reads back, and reports; **the extension types, the student clicks** —
> it never dispatches a click on navigation, consent or submit. Kept unchanged: `PortalForm` /
> `FieldMap`, `FILL_METHODS` (plus `setFiles`), `profile.py`, `already_correct`/`read_back`,
> `escalation.py`, the `ApplicationStep` trail. Retired: portal credentials, reauthentication,
> browser profiles, the CAPTCHA service, `counselor-submit` and the 48-hour auto-submit (§5.1
> amendment), and the pause/hand-off/resume spike — in the student's own tab the question dissolves.
> The mailbox changes in the same direction: no platform address, an OAuth read-only / metadata
> connection to the student's own inbox filtered to the pack's institutions, nothing sent
> (`docs/superpowers/specs/2026-09-15-student-owned-mailbox-design.md`). Several bullets below still
> describe the retired design; they are left as the record of why each decision was taken.
> Owner decisions of the same evening, recorded in that spec: two layers (an Application Kit the
> student can apply by hand on any device, and the extension that applies it fast); install and
> pairing enforced at onboarding; the student presses Next between pages; verification links
> auto-open in the student's own browser; a 14/7/3/1-day + 6-hour reminder ladder; a per-portal
> `terms_posture` from a seven-portal sample in which none forbids autofill and all forbid credential
> sharing; and an agency-level counselor mode defaulting to "counselor prepares, student applies".

**Built, 2026-09-15: the kit and the packet** (`apps/portals/packets.py`). `build_kit` and
`mint_packet` are one preparation with two renderings and a test pins that they cannot
disagree. The asymmetry is the design: `build_kit` never raises and degrades (no field map ->
held answers plus the programme's REQUIRED statements; `PROHIBITS_AUTOMATION` -> `fillable=False`),
`mint_packet` refuses with a stable reason (`no_portal`, `automation_prohibited`, `missing_fact`,
`unsafe_action`, `malformed_field_map`, or `NoFieldMap`). Checked in that order: `no_portal` ->
`automation_prohibited` -> `NoFieldMap` -> `malformed_field_map` -> `missing_fact` -> `unsafe_action`.
Every FieldMap row is read through one function, `_parse_entry`, which refuses the whole packet on
any row it cannot read (no `profile_field`, no `action`, or an `action` that fails schema
validation) -- so a malformed row is always caught before `missing_fact` or `unsafe_action` gets to
reason about it. The posture check is first, so a prohibited portal never reads a verified value. The `PACKET` `ApplicationStep` is
the authoritative record of what the platform prepared; whatever the extension later reports is
an attestation from a device we do not control. `Application.deadline` and `deadline_timezone`
are the first deadline columns in this codebase -- the catalog still holds none.

**Since 2026-09-25 the kit reads no catalogue; it reads a copy.** `build_kit` is served from a web
view and `runtime_web` holds no grant on `ProgramStatement` or `ApplicationPrompt`, so
`capture_requirements(application)` copies the checklist, the student's letter actions and the
letter cycle onto the `Application` row, **in the worker**, and `build_kit` reads only that copy.
Two things follow, and neither is built. **Whatever creates an `Application` must call
`capture_requirements` in the worker** before the kit is served — nothing in production creates one
yet, so it has no caller, and an uncaptured kit shows an empty checklist that looks exactly like a
programme stating nothing. And **the copy goes stale when the programme page is re-read**: nothing
re-captures it. Download filenames follow the same rule — `DocumentDraft.rendered_filename` is
written by the worker at render and the web tier never resolves a variant live.

**Built, 2026-09-17: pairing and the extension API** (`apps/portals/pairing.py`, `ext_api.py`,
`snapshot.py`, `actions.py`, plan 2 of 5). Two rules from its security review bind anything built
on top of it:

- **A `FieldMap` learned from a snapshot is scoped to the tenant that sent it.**
  `FieldMap.learned_by_tenant` is NULL only for a map the PLATFORM verified by driving a real
  browser at the real form; a snapshot is a claim by a client, and the server cannot check its
  selectors against the page. Read-back cannot catch a bad one either -- it reads back the same
  selector it typed into, so a wrong-but-consistent map verifies clean. Shared, that let one
  tenant's student decide where every other tenant's students' identity fields get typed.
  `current_for(portal_form, tenant_id)` therefore takes the tenant and **has no default**: a caller
  that forgets it silently gets shared-only maps. Do not add one. Superseding is per-scope for the
  same reason; the version counter stays global because `field_map_form_version_uniq` is
  `(portal_form, version)`. Promotion of a tenant map to the shared row -- on agreement between
  tenants, or after a human looks -- is deliberately not built.
- **A device token must die with the account it names.** `authenticate_device` filters on
  `membership__active=True`, and `_device_endpoint` applies `deletion_lock_target`. Both exist
  because the session path enforces those in `current_membership` and `TenantMembershipMiddleware`,
  **inside `if request.user.is_authenticated`** -- a device token carries no session and runs past
  both. Without them, `advance_deletion`'s `active = False` is not load-bearing on this surface and
  a locked-out student's extension keeps being handed packets of their own verified facts for the
  whole thirty-day window. `request_deletion` also revokes every pairing at request time, not at
  `EXECUTED`: `DELETE /ext/pair` authenticates with the very token you would be revoking, so a
  device the student no longer holds cannot revoke itself.

Full reasoning in `docs/superpowers/specs/2026-08-25-application-automation-decisions-design.md`.

**This section said "work that has not started yet" until 2026-09-12, by which point
`apps/portals/` was 2,396 lines across 20 modules with 25 test modules.** It misled a
session into reporting that portal automation did not exist; the heading now says
otherwise so the next one does not repeat it. Built: the learn/fill passes and their
action allowlist, read-back verification, origin pinning, the escalation surface
(`escalation.py`), challenge detection and bounded resolution (`challenge.py`,
`resolve.py`), reauthentication and recovery (`auth.py`, `recovery.py`), per-tenant
browser profiles, a portal queue and worker, and the sandboxed EC2 portal tier described
in the section above — shipped stopped at `PortalDesiredCount: 0`.

The decisions below still bind, and most are now honoured rather than pending, so check
before "adding" one. What is genuinely still open is the §5.2 pause-hand-to-a-consultant-
and-resume **spike** named at the end of this section: `resolve.py` and `recovery.py`
implement a resume path, but the load-bearing question — that a session survives being
handed to a human and picked up again on ephemeral infrastructure — is answered by
running it, not by reading it.

- **Portal credentials never live in the database.** `phased requirements.md` §5.2 has the
  platform reauthenticating with managed credentials, so passwords will be held. They go in
  a dedicated secret store (Secrets Manager under a KMS key), keyed per student-portal — never
  a model field, never a `JSONField`, never in the evidence bucket, never logged or in an
  exception message. The IAM grant is per-secret-prefix and belongs to the portal-execution
  role only. Erasure ships with storage: `apps/audit/deletion.py::advance_deletion` must
  destroy a student's secrets on the same path it deletes their documents, or GDPR erasure
  leaves credentials behind. The failure mode this rule exists to prevent is a password column
  added in passing during a sprint.
- **CAPTCHA is detected and delegated, never circumvented.** The strategy is detect → preserve
  the session → hand to a human → resume, per §5.2. Browser stealth is not a CAPTCHA strategy
  and must not be adopted as one; §2 forbids unauthorized circumvention and §3.4 (formerly §3.6) excludes
  proxy infrastructure intended to evade portal access controls. A resolution service may be
  integrated only per-approved-portal, after the portal-terms and legal gates, with consultant
  fallback. This is also the better engineering position: CAPTCHA triggering is driven by IP
  reputation and behaviour far more than fingerprint, the platform runs behind one NAT IP, and
  a strategy of not being detected fails silently mid-application at a deadline.
- **No fetch vendor is ever pointed at a portal.** Firecrawl and scrape.do read public,
  unauthenticated programme pages (Web fetching, above) — the same rule the Scrapling tier they
  replaced carried, because it is a legal boundary, not a property of which client does the
  fetching. Defeating an access control on an authenticated third-party system is a different act
  from reading a public page. Portal execution gets its own client.
- **Stable egress is reserved; evasive egress is not.** The distinction is purpose, and it is
  testable: egress that makes the platform consistently identifiable is permitted; egress that
  makes it look like many unrelated ordinary users is not. Reserve the ability to allocate
  stable per-tenant or per-portal egress in the network design. Do not adopt rotating or
  residential pools.
  **Amended 2026-09-22 — this binds the portal path only** (owner decisions 2026-09-19 and
  2026-09-22). The *research* fetch path — public, unauthenticated programme, funder and register
  pages — runs through paid vendors from **their** addresses, not ours: Firecrawl with enhanced
  proxies, scrape.do with residential and mobile addresses, headless rendering and anti-bot bypass.
  The line above exists to keep the platform identifiable *as an applicant's agent on a portal*; a
  vendor reading a public page from its own pool spends nothing that rule protects, and no portal is
  ever pointed at a vendor. Design: `docs/superpowers/specs/2026-09-22-fetch-engine-design.md`.
- **Portal automation goes in a new app, never in `apps/concierge`.** That module's docstring
  guarantees every action in it is a human-recorded fact, and
  `tests/concierge/test_roadmap.py::test_no_payment_or_portal_automation_call` enforces it.
  When Phase 3 lands, the temptation is to delete that test. Don't — narrow the scope by
  putting automation elsewhere. `ManualOperation` gains no automated writer.
- **Agent actions are already representable.** `AuditEvent.actor_kind` distinguishes an agent
  write from a platform write (both carry `actor=NULL`), and `RoadmapItem.owner_kind` lets the
  agent own a step without a synthetic `Membership`. Use them; do not add a fake member row.
- **Untested and load-bearing:** that a browser session can be paused, handed to a consultant
  and resumed without repeating completed steps, on ephemeral Fargate workers. §5.2 depends on
  it in six places. Run that spike before designing Phase 3, not after.

## Who reads a CV warning — the student, not a counsellor

No counsellor reviews CVs (owner, 2026-09-14). The AI writes the CV, the student sees it, and
changes are made through a planned chatbot (the CV-requirement programme, part 6). So every
`undecided` / `unapplied` rule and every render warning has ONE audience: the student, through
that surface, which does not exist yet. Comments in `apps/documents/constraints.py` and
`derive.py`, and three lines in this file, used to say "the counsellor"; they were corrected
2026-09-15 with this note. The design is unchanged — a rule nothing can act on is shown, never
dropped — only the reader is.

## One ledger, every consumer

The platform is one synchronized system over the student's fact ledger (`VerifiedFact`). Every
consumer reads the same ledger: CV generation and rendering, the letter and storyline prompts,
skill tailoring, portal autofill (`portals.profile.verified_values`) and europa.eu
(`europass.europass_payload`). A category is never hidden from one consumer to protect it from
another; each consumer guards how it uses the fact instead. Example: the letter prompt may tell a
TIMELINE fact (an illness, a caring period) and may not add a diagnosis, cause, severity, person or
detail beyond the statement's own words. So a new category is wired to every consumer in the same
change, and any exclusion is an owner decision recorded here. Today there are none.

Europass carries a gap row in the captured work-experience shape (statement as occupation, empty
employer). `manage.py europass_canary` sends one and checks it is printed: verified live
2026-10-06. Rationale: owner decision 2026-10-06, after a branch that kept gap statements CV-only
(`claude/cv-timeline-entry`).

## The CV-requirement corpus — read this before measuring discovery or derivation

`docs/research/cv-corpus-programmes.csv` and `cv-corpus-rules.csv` are the hand-adjudicated
ground truth for "did we find the CV requirements this programme publishes"
(`docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md`). Loader and scorer:
`apps/research/corpus.py`. The live runner `tests/research/test_cv_corpus.py` prints
recall/precision/localization per stratum and asserts hand-ratcheted floors; the headline is
**recall on BINDING requirements**, because a missed binding rule costs a student an
application and an invented one costs an edit they can decline. Rules of the file:
`seed_url` is the programme's front page, never a documents page (seeding with the rule page
defines discovery away); a `requirement_key` is always one the engine already has, with
`unapplied` for what the vocabulary cannot carry; hosts from `cv-format-eval.csv` and the
2026-09-15 survey may be `dev`, never `heldout` (`corpus.contaminated_hosts`). `manage.py
pool_cv_corpus --digest` fills source digests; `--pass vendor` pools candidate sentences into
`cv-corpus-candidates.csv` for adjudication. **That crawl is pinned to the seed's own domain**
(`tavily_crawl`, `allow_external: False`) — Tavily's documented default is `true`, and the first
vendor pass followed DAAD's "use the europass template" link and crawled
europass.cedefop.europa.eu, whose **single** page yielded 76 of that programme's 79 candidate
rows — its language picker, one row per `[dansk](…/da)` link. It read like a `CANDIDATE_TERMS`
problem (every one matched on the word "europass") and was a crawl-scope one; the 76 rows were
pruned by hand, since re-pooling spends credit for an answer the filter already gives. **One
page, so the crawl budget was not consumed off-site** — this is a precision fix and will not
recover the six programmes whose crawl returned nothing. Tavily is not measured as honouring
the flag, nor as counting a sibling subdomain (`static.daad.de`) internal to its seed. At 45
programmes the corpus demonstrates ≥95% and diagnoses losses; it cannot demonstrate 99%
(spec, "The measurement ceiling").

## The rule catalogs — read these before researching CV or letter conventions

`docs/research/` holds **194 already-researched rules**, each with a source URL, a
provenance tier, binding-vs-advisory, a confidence grade and a verified-for-cycle year,
cross-checked across two independent research runs:

- `cv-rules.csv` (93) — CV content rules
- `cv-style-rules.csv` (33) — CV style: layout, typography, elements, country norms,
  machine parsing. IDs are `S-0NN` and are cited by ID in code (`S-010`, `S-011`,
  `S-013`, `S-026`).
- `letter-rules.csv` (71) — motivation and reference letters
- `2026-09-14-letter-storytelling-evidence.md` (19 `N-` findings) — how the engine chooses
  and tells a letter's story per reader, and what it may invent (the why; anything a
  submitted document could check comes only from the ledger — owner's line, 2026-09-14, in
  the note's §4). Read it before researching narrative, "authentic voice" or
  AI-vs-human text again; the humanizer and detector questions are answered there too.

**Consult these before running a new research pass on how a CV should be written.** On
2026-09-11 a live-search pass re-derived the action-verb, outcome-first and
no-"responsible for" rules from scratch; all of it was already S-026, sourced to Oxford
Careers, at a better tier than the pass that rediscovered it. Nothing pointed to the
catalogs from here, which is why this section exists.

Two traps the catalog itself records:

- **Only the funder rules (`R-*`) are seeded as `CatalogRules` and checked mechanically**
  (`apps/documents/catalog_seed.py`). Every `S-*` rule is prose in a CSV, enforced only
  where a human happened to cite it — so a new writer path inherits none of them by
  default. That is how `evidence/extraction.py` came to write CV prose that obeyed no
  style rule for weeks.
- **S-032 vs S-008 is resolved — the table layouts stay.** Machine parsers do mangle
  multi-column and table layouts, and `cv_german_tabular.html`, `cv_europass.html` and
  `cv_funder_sisgp.html` are all real HTML tables. It binds nothing here, for two
  independent reasons: every source for the rule describes corporate job-application ATS,
  and a targeted search found no evidence either way about graduate-admissions portals;
  and nothing in this platform hands a CV to a parser — the only exit for a rendered
  document is `storage.py`'s download (`Content-Disposition: attachment`, read by a
  human), and portal automation *types* values (`session.py::FILL_METHODS` allows only
  `fill`, `type`, `selectOption`, `selectOptionFromDropdown`, so there is no file-upload
  action). What would make it live: a destination shown to parse an upload, or a portal
  step that uploads a file. The answer then is a per-destination variant —
  `format_resolution.py` already picks one from what the programme requires — never a
  weakening of S-008.

## LLM/AI security

- `apps/research/extraction.py` and `apps/funding/explanations.py` are the reference pattern for any new LLM-calling code: untrusted content is explicitly labeled as data (not instructions) in the prompt, output is schema-constrained via Pydantic (`extra="forbid"`), and `max_output_tokens` is capped. Follow it, don't weaken it.
- Neither module is wired to a view or task yet. Before wiring one up, add per-tenant/per-user rate limiting in the same change — reuse `apps/ratelimit.py`'s `rate_limited()` (the fixed-window cache counter already used by the pack-command, MFA-verify, and student-message endpoints) rather than writing a new limiter, and an LLM-calling endpoint without one has no cost circuit-breaker. See the global `engineering.md`'s "LLM and AI-Feature Security Baseline" for the full rule.
- **The letter engine has a caller now: `manage.py draft_letter`** (`apps/documents/management/commands/draft_letter.py`). A console entry point, the same choice `ingest_evidence` made and for the same reason — §10 still gates the interaction surface, and a command opens none. It generates one letter for one student and one programme inside `tenant_scope`, reads **confirmed** facts only (`generatable_facts`), writes a `DocumentDraft` in `DRAFT`, and stops: `mark_letter_ready` takes an `accepted_by` because a person accepts a letter, and nothing in a command is a person. Two things it cannot work out for itself and says so rather than implying: without `--forbid` names the wrong-institution gate checks nothing, and `--render` writes to a path you name, never into the evidence bucket. The rate limit is inside `generate_letter` already (20/hour/student, two model calls per generation plus up to six for the written-requirement check). Everything the engine measures was arithmetic about output nothing produced until this existed — which is why the defects six review rounds kept finding were all hypotheses.

- **The letter engine has a student door too (2026-10-13): "CV & letters"** (`apps/documents/writing.py`, `/student/writing/`). The web tier only records `Application.letter_state` and queues a `DocumentWorkMessage` (`generate` with kind `MOTIVATION_LETTER`, or `approve_letter`); everything that reads the catalogue runs in `apps/documents/letter_worker.py` as `runtime_engine`. `mark_letter_ready` trusts its caller for gate violations, so the worker stores the generator's own record on the draft (`DocumentDraft.letter_gates`, `letter_retried`) and approval reads only that. `api._SUPPORTED_KINDS` stays CV-only. A flagged letter (an UNRESOLVED prompt is one) stays a DRAFT and says the counsellor must read it. **`/counselor/letters/` (`documents/review.py`, 2026-10-25) lists them for the assigned counsellor, read-only: its Approve is disabled until the worker runs `mark_letter_ready` with the counsellor as `accepted_by`.** The same day added front ends whose backend is still owed, each disabled and labelled "Coming soon" so nothing pretends to save: per-letter answers and the scholarship essay (`documents/workspace.py`), recommendation requests (`/student/writing/references/`) and card payment (`concierge/plan.py`). Scholarship cards get no letter: only an `Application` whose candidate is a catalogue programme is writable. Rate limits: `letter-request` 10/hour at the door, plus `generate_letter`'s own.
- **A DEBUG machine spools queue work to `.local-queue/` and stores objects under `.local-store/`** (`apps/queue.is_local_queue`, `apps/research/storage._LocalS3`), only while a queue or bucket is still named by its `test-` placeholder; `scripts/local_research.py --watch` runs spooled document work through the real handler. Production names every queue and bucket, so neither branch is reachable there.

- `apps/documents/evidence/extraction.py` is the third LLM-calling module and follows the same reference pattern. Its caller is `manage.py ingest_evidence` (`apps/documents/management/commands/ingest_evidence.py`) — a console entry point, not a view: the interaction surface is still out of scope. That command is also where `owner_login`'s "must come from a verified account link, never a free-text field" constraint is enforced today: it takes the handle from a **confirmed** IDENTITY fact (the student's own CV printed it, a human accepted it) and refuses a repository whose owner does not match. Do not add a caller that passes an unverified `owner_login`. It does, however, already carry the per-student `rate_limited()` call the rule above requires, so wiring it up is not blocked on adding one. The package's whole point is that authorship is never inferred here — a model may draft a project description, but nothing it writes becomes a `VerifiedFact` until a human accepts or edits it (see that package's own docstrings for the full design). Its tests declare a `live` marker for the handful that hit real external APIs (Crossref, OpenAlex, GitHub); `pyproject.toml`'s `addopts = "-m 'not live'"` excludes them from a default `pytest` run, so don't be surprised when they don't show up — run them explicitly with `-m live` when you need to.
- **`generate_cv(programme=...)` costs a second model call.** `apps/documents/tailoring.py::tailor_skills` is wired into generation and runs only when a programme is passed and that programme has `ProgramStatement` rows; it carries its own per-student limiter (`skill-match`, 20/hour) on top of generation's own (10/hour). It may only ever reorder and drop skills — never add one, and never copy a statement's text into the document, which is the programme's own wording appearing as the applicant's claim.
- `apps/research/reader.py::extract_statements` is the fourth LLM-calling module and
  `apps/documents/derive.py::derive_cv_constraints` is the fifth. Both are reached only
  through `apps/documents/program_rules.py::read_and_derive`, which has no production
  caller: the chain runs from tests and the live check only, so no request path reaches
  either model today. Four constraints bind whoever wires it:
  - the per-tenant rate limiting the rule above requires (`read_program_page`'s existing
    `rate_limited` call is a per-programme cost circuit-breaker, not the per-tenant/per-user
    limiting a view or task needs);
  - only ever profiling `OfficialSource` rows the catalog vouches for, below;
  - `read_and_derive` holds one database transaction open across the HTTP fetch and up to
    two OpenAI calls. Correct for consistency -- it is what makes a programme's statements
    and its derived rules roll back together -- and expensive at catalog-ingestion scale:
    idle-in-transaction for tens of seconds per programme. Wiring this up means deciding
    whether that cost is acceptable at the expected call volume, not assuming the current
    shape scales unchanged. **Since 2026-09-26 that transaction also spans the back-to-back
    grammar requests (slots, values, page facts) and holds uncommitted `DecisionRecord`
    inserts**, so two workers reading the same shared page both pay for the same answers and
    the later insert waits on the earlier row's unique-key lock; the structural fix --
    decision writes on their own autocommit connection -- is plan 2's. And
    `read_and_derive(budget=None)` applies no run budget or monthly ceiling, so whoever
    wires a production caller must pass `decisions.run_budget()`;
  - a standalone re-derivation sweep -- the follow-up this design promises, re-running
    `derive_cv_constraints` from stored statements without a refetch, so a new constraint
    key can reach every programme already read -- calls `derive_cv_constraints` directly
    rather than through `read_program_page`, which is the only place `rate_limited` is
    called. Such a sweep makes an unbounded model call per programme unless it adds its own
    limiter.
- **`apps/documents/research_fit/` is the sixth LLM-calling module** (topic phrase, classifier,
  three-reading judge) and the first caller of a search provider from a per-student path. Its
  query never carries the student — `anchors.guard_phrase`, pinned by
  `tests/documents/research_fit/test_service.py::test_no_query_ever_carries_the_student` — because
  Exa ToS §1.2(c) and Tavily §9.2 license query text (`docs/legal/2026-09-provider-terms.md`). It
  has its own `research-fit` limiter (20/hour per student) and a per-tenant daily billed-cost
  ceiling (`RESEARCH_FIT_DAILY_CEILING_USD`) — **but that ceiling meters SEARCH spend only**, and
  for a while nothing metered the models: the search space is 2 anchors x N domains x 2 queries x
  `TOP_PAGES`, each page costing one classification plus a three-reading judgement, so one letter
  could spend **96 model calls** — all of them when nothing matched, which is the common case —
  against a `judge.py` docstring that said "one pair per letter, so three calls". `rate_limited`
  counts proposals, not calls, so 20/hour meant ~2,000 calls/student/hour. The brake is a cap
  rather than a price, because a dollar figure needs a per-model price table that goes stale in
  silence: `service.MAX_PAGES_CLASSIFIED` (6) bounds the pages one proposal classifies and judges,
  checked at every level of the search, giving `MAX_MODEL_CALLS` = 28; the calls made are counted
  onto `ResearchFitOutcome.model_calls` and logged with every outcome. Raising the cap re-opens the
  tail. Sentences are split by code and models only classify
  them, so no model ever authors a name the letter cites. Research-fit classifies through
  `research_fit.classify.FrontierClassifier` only; any other Jev use goes through the
  typed-decision client, `apps/research/decisions.py`, except the provenance vetoes'
  `apps/research/jev.py` (2026-09-27: the unwired second Jev client at
  `research_fit/jev.py` was deleted -- a duplicate, never a default, that the "no student text to
  Jev before the DPA" condition was written only against). Design:
  `docs/superpowers/specs/2026-09-22-letter-research-fit-from-the-student-design.md`.
- `apps/research/funding_judge.py` is the seventh LLM-calling module, reached only from
  `run_discovery(funding_parser=..., funding_claude=...)`, i.e. `manage.py discover --funding`, which
  refuses to start without `ANTHROPIC_API_KEY`. Every line of a page's funding sections gets a closed
  verdict from three readings -- two `OPENAI_EXTRACTION_MODEL` phrasings and one `ANTHROPIC_JUDGE_MODEL`
  -- and a row is served only when all three agree on every deciding label of every line of the award
  (`docs/superpowers/specs/2026-09-14-funding-reader-precision-design.md`). Everything short of that
  waits in `manage.py funding_review` for a platform operator; a decision there is bound to the page
  version (`reviewed_sha256`) and every tenant sees it, so it is never a tenant action.
  **`FundingOpportunity.served` is the only flag a student-facing path may read, and nothing reads it
  yet.** Before anything does: an award withdrawn from a page keeps its `served` flag until that page
  is re-read, and it reads only `one_programme_per_site` catalogue leads (`pipeline._fund_page`) until
  an INSTITUTION-scope row's origin is checked against `institution.official_website`. Anthropic's
  Usage Policy lists admissions as high-risk and wants human review before dissemination; served rows
  have no human, which is an open terms question alongside §10's, not settled here.
  Measured live 2026-09-16 on 497 real EACEA leads,
  `docs/superpowers/2026-09-16-funding-reader-precision-run.md` — read it before assuming what
  `served` actually captures; a 2026-09-22 follow-up in the same file separates reading-quality gaps
  from a schema gap (temporal/administrative phrasing) from a verbosity penalty in the per-line
  grouping rule.
- `apps/research/angles.py` is the eighth LLM-calling module: one schema-constrained call per
  (country, family, language), following the reference pattern (the request labelled DATA,
  Pydantic output `extra="forbid"`, `max_output_tokens` 3,000, `store=False`) and its own
  `sweep-angles` limiter (`SWEEP_ANGLE_GENERATIONS_PER_DAY` per (country, family)). Its only
  caller is `manage.py generate_sweep_angles`, operator-run, which refuses to generate until a
  per-language kind-word vocabulary adapter exists — kind words are never translated by the
  model — and `--from-steering` writes one hand-written angle as the interim. Its input carries
  no student field.
- **Funding readings are bought three ways (`model_cost.ReadingTier`): standard, OpenAI flex, or
  both vendors' batch APIs (`batch_reading.py`).** The prompts and the decision are the synchronous
  path's byte for byte (`funding_judge.reading_prompts`, `decide`); only the transport differs, and
  `test_batch_reading` pins that a batched read decides what a synchronous one does. Two rules:
  a request a batch did not finish is *missing*, and a page with a missing reading writes nothing —
  never ABSTAINED rows, which would let `withdraw_unread` unserve awards the page still states; and
  nothing may hold a transaction across `read_funding_batched`, which can wait 24 hours per batch
  — up to 48 when a tie-break batch follows. **A programme page a batch did not finish is not read
  again by the next run unless its text changed**: `run_discovery`'s unchanged-page short-circuit
  checks claims, not `funding_read_at`, so it stays PENDING in `funding_recall`. The sync path has
  the same gap when the budget cuts a read short; batch mode makes it the ordinary failure. Known,
  not fixed (it changes the short-circuit, not a cost). A flex 400
  raises `ReadingTierRefused` instead of becoming a lost reading, because a lost reading on every page
  reads as a catalog that states no funding. Every reading's tokens are recorded (`CostMeter`, and
  `OfficialSourceSnapshot.funding_read_cost` per page read) and priced from
  `MODEL_PRICES_USD_PER_MTOK`; a model with no row is *unpriced*, never zero. An answer that came
  back off-schema was still billed, so it is never counted `lost` (a call that raised, whether it
  was billed unknown): synchronously its usage is gone with the SDK's rejected parse, so it counts
  `unmetered` (billed, usage unknown); in a batch its body still carries `usage`, so it is priced.
- **`ProgramStatement` is shared-catalog data with third-party content in it.** Every tenant
  reads that table (`tests/tenancy/test_database_isolation.py::_SHARED_TABLES`), and its `text`
  and `label` come from a web page a model quoted. So whoever wires the writer decides
  *which URLs may be profiled*, and that decision is a cross-tenant one: if a tenant can steer
  the URL, a hostile page becomes content every other tenant reads. Profile only URLs already
  reachable from an `OfficialSource` the catalog vouches for — never a URL supplied per-request.
  Writes are RLS-restricted to the `runtime_engine` role, which limits who can write but not
  what the page said. Its rows are verbatim sentences verified against the archived page, never
  a model's paraphrase — `reader.verified_statements` drops anything not on the page, which is
  what makes a re-read stable.
- **Decision B vouches for the SOURCE ROW, not the BYTES — `reader.py` now enforces that.**
  `read_program_page` reaches a page through `retrieve_official_source` → `fetch_page`
  (Firecrawl, then scrape.do on failure — Web fetching, above), and each vendor's final URL runs
  through `validate_public_url`, which rejects *private* addresses but does not require the vendor
  to have stayed on one origin — a public attacker-controlled host is followed happily. Without a
  further check, an off-site redirect from a compromised official URL becomes shared-catalog rows
  every tenant reads. `read_program_page` therefore calls `require_same_origin`, which compares
  the ORIGIN (scheme
  + host) of `fetched.final_url` against `source.canonical_url` and raises `OffSiteRedirect`
  **before** `persist_snapshot`, so off-site bytes reach neither the model nor the evidence
  bucket. `final_url` itself comes from whichever vendor answered: Firecrawl's own re-validated
  `data.metadata.url`, or, for scrape.do, the URL we requested (§4.3 of the funder spec — scrape.do
  reports no final URL of its own).
  **Origin, not the whole URL, and do not "tighten" it to one.** Official pages redirect `/x/`
  to `/x` and `/x` to `/x/2027-intake` as ordinary housekeeping; whole-URL equality rejects the
  real FAU programme page over a trailing slash. Scheme is part of the comparison because
  `validate_public_url` permits http, so an https source could otherwise be walked down to http
  on its own host. A source that genuinely moved hosts is a catalog fix — update
  `canonical_url` — which is a human decision, recorded, and that is the point.
- **Never hand a programme page's raw HTML to a model; use `reader.py::readable_text`.**
  `extract_statements` caps its input at 24,000 characters and a modern university page
  spends its first 24,000 on `<head>` and inlined CSS — FAU's AI M.Sc. page is 422,515
  characters in which "admission" first appears at 163,315. The model reads a stylesheet, finds
  no statements, and `read_program_page` treats a read that verifies no quotes the same as one
  that returned none — it keeps the previous rows standing — so the whole path fails
  **silently**: a page that reads as saying nothing is indistinguishable from one that says
  nothing. `readable_text` strips chrome and prefers `<main>` (that page: 422,515 -> 10,408
  characters, all prose). Measured, not inferred.
- **`readable_text` emits structure, not a run of prose, and that is load-bearing.** Headings
  keep a `#` marker, list items a `- `, table rows their pipes. `text_content()` did not: it
  turned a document checklist into flat prose in which "no longer than two pages" no longer
  belonged to any particular document. The association lived in the markup, so flattening
  destroys information no prompt can recover — do not "simplify" the markers away. Measured on
  TUM's Informatics M.Sc. page (416,585 raw): the new output carries `Credits` / `- 120 ECTS`
  and `Admission Category` / `- Aptitude Assessment for Master` as label-and-value; the old one
  ran them together.
- **HTML comments are stripped explicitly, and with `strip_elements(..., with_tail=False)`.**
  `text_content()` dropped them for free because XPath `string()` does; the block walk recurses
  into anything that is not a leaf block, so the filter had to become deliberate — otherwise
  invisible page text reaches the model and a keyword in a comment can keep a section the
  visible prose never mentioned. Use `strip_elements`, never `getparent().remove()`: a comment
  sits inside a sentence, and `remove()` takes its tail with it (measured — "A degree<!-- note
  --> is required." lost " is required.").
- **The structure change has NOT been shown to improve extraction, and that is recorded on
  purpose.** Measured live 2026-09-12 against FAU's AI M.Sc. application page
  (`ai.study.fau.eu/prospective-students/master-ai/application-master/`, 141,274 bytes),
  `gpt-5.6-luna`, three `extract_program_profile` calls per input (that function is now
  deleted; its replacement is `extract_statements`, below): flattened text returned 13,
  17 and 10 competencies with no duplicates; structured text returned 18, 18 and 16 with a
  duplicate in two of three. Neither ever attached an ECTS threshold to its subject. A single
  earlier run that did looked like the predicted attribution win and was sampling variance --
  do not cite it. Both pages tested state their requirements as separate lines already, so
  neither exercises the case flattening is supposed to destroy; a page that does would settle
  it. What the change is actually justified by is a more faithful input and three closed
  failure modes (comments, boundary-cut cap, positional truncation), not a better model read.
  **This 13/17/10 instability is what the reader redesign (2026-09-12 spec) exists to fix** —
  see `verified_statements` above and `tests/research/test_reader.py`'s live
  `test_three_live_reads_of_a_real_page_derive_the_same_rules` for whether it did.
- **It didn't, not fully, and that is recorded here rather than left for the live test to
  answer silently.** 18 real reads of the FAU AI M.Sc. application page across 6 runs of
  that live test produced 29–40 statements each, and no two reads produced an identical
  set. `dropped_quotes` was non-zero in only 2 of those 18 reads, and never more than 1.
  Read those two numbers together: **verification removes fabrication; it does not remove
  selection variance.** The model is not inventing text it quotes — it is choosing a
  different subset of genuinely-on-the-page sentences on almost every read, and nothing in
  `verified_statements` constrains which true sentences get selected, only whether a
  selected one is true.
- **One read is now three, unioned (`reader.py::_READS = 3`).** Each call to
  `read_program_page` asks the model three times against the same archived page and pours
  every response into one `verified_statements` pass, so the stored set is the union of the
  three. A union member is verified against the page exactly like any other quote, so it can
  only ever be a true sentence the other two calls missed — union was chosen over a quorum
  for that reason: a 2-of-3 rule discards precisely the sentence one read found, which is the
  observed failure (DAAD PRIME derived `europass_preferred` on one run and `any` on the next,
  same page, same code). **The cost lands only on a page whose text changed** — the
  `content_sha256` cache returns before any model call — so the ceiling is `_READ_LIMIT` ×
  `_READS` = 12 model calls per programme per hour. Two consequences worth knowing before
  changing anything here: `dropped_quotes` is now a sum over the three calls, so an
  unverifiable quote counts three times; and when two calls label the same sentence
  differently, dedup's existing last-occurrence-wins settles it arbitrarily. That last point
  is left arbitrary on purpose — demoting a sentence from FORMAT to DOCUMENT hides it from
  `derive_cv_format`, so the cost is a missed mandate, never a student's PII sent to europa.eu
  on a misread.
- **Union narrows the variance and does not remove it. Measured 2026-09-13, same page, same
  live test.** Three unioned reads of the FAU AI M.Sc. application page returned **47 / 42 / 48**
  statements — three designs have now failed set equality on this page.
  Read that against the 29–40 from single reads: coverage rose by roughly a third and the
  spread fell from 11 statements on a mean of ~34 to 6 on a mean of ~46, so the union is a
  real improvement and **not** a fix. `dropped_quotes` was 1, 2 and 1 — one or two unverifiable
  quotes per *nine* model calls, so fabrication stays as rare as it was. Do not re-derive this;
  do not report the union as having settled stability.
- **The live check now asserts the DERIVED RULES, not the statement set, and that narrowing was
  made on a measurement.** Set equality was the original theory of stability and three designs
  have failed it, while what actually broke in production was a derived *value* (DAAD PRIME:
  `europass_preferred` on one run, `any` on the next). The reads above disagreed on sentences
  like "wait for notification from fau." — real page text that derives nothing and reaches
  nobody. `cv_constraints` is compared on `(key, value)`, never verbatim: `rule_id` carries the
  sentence's index on the page, so two reads quoting a different number of earlier sentences
  write different ids for the same rule. The statement-set spread is still printed every run,
  so a collapse in coverage stays visible.
- **It passes — and on the FAU page that is close to vacuous. Do not cite it as proof.**
  Measured 2026-09-13: 44 / 52 / 50 statements, **44 of them in all three**, 10 peripheral;
  all three derived `cv_format_requirement=any` and `cv_constraints=[]`. Three reads agreeing
  there are no rules is agreement on an empty set, and the common core being exactly the size
  of the smallest read says the variance is entirely additive — each read sees the same 44
  sentences plus a different tail. **The check needs a second page, one that actually derives a
  value, before the union can be called settled.** The natural candidate is whichever page
  produced the DAAD PRIME flip; its URL is not recorded in this repo, which is the first thing
  to fix. A page whose derivation is empty can only ever prove the absence of a regression.
- **`<main>` is used only when `<main>` really is the page** (`_body_lines`, `_MAIN_SHARE`).
  It was always a proxy for "the relevant part" and section selection replaced it as the mechanism,
  so where the proxy is wrong it is now dropped. Measured: `<main>` holds 99.7% of SISGP's prose,
  87% of Sciences Po's, 80% of Rhodes', 63% of JASSO's — and 15% of Türkiye Bursları', whose
  headings and body copy all sit in siblings, so preferring it discarded 85% of the page. A shell
  `<main>` is not a page that says nothing, and the two were indistinguishable before this. The 0.6
  threshold rests on that ONE calibrating case and the fact that the change leaves the other five
  pages byte-identical; re-derive it if a page lands between 15% and 63%.
- **Only the sections mentioning admission are kept** (`_ADMISSION_TERMS`, `_selected`), and a
  page matching nothing degrades to the whole page rather than to silence — silence is the
  failure mode that hides, for the same reason as above: a read that verifies nothing keeps
  the previous rows rather than emptying the catalog. That vocabulary is
  what this caller reads FOR; a second extractor reading for something else (CV-format rules,
  say) needs its own, never a widening of this one. Widened until it matches everything, it is
  the same as not selecting at all.
  **Since 2026-09-18 it runs only on a page that would not fit `_MAX_PAGE_TEXT_CHARS`, and it
  logs what it dropped.** The cap is the only reason to select; on a page that fits, an English
  vocabulary can only lose. Measured over ten real programme and funder pages (AMIR, MEMBIOMED,
  i-MESC, MathMods, WE-TEAM, EuroPubHealth, EMJM-Imaging, SISGP, Eiffel/Paris-Saclay, FAU):
  **selection keeps 95–100% of the prose on every one, and nine of the ten are under the cap** —
  so it was removing a couple of percent while carrying the whole risk that a section it cannot
  read (a CV requirement in Turkish, Russian or Kazakh) is dropped before any model sees it,
  silently, on a page whose one incidentally-matching section stops the no-match fallback firing.
  **A share floor is the unsound alternative — do not re-propose it:** the case where selection is
  most right (mostly campus life, one admission section) and the case where it is most wrong (a
  page in a language the vocabulary misses) both keep a tiny share, so share cannot tell them
  apart. Fitting the cap can. The 95–100% figure also says the filter earns very little; deleting
  it is a live question, and an owner decision rather than a cleanup.
- **A PDF is read as a PDF** (`apps/research/pdf.py::pdf_text`), not decoded as UTF-8. egress allows
  `application/pdf` and a funder's checklist is often one; the old branch handed the model mojibake.
  The pypdf call, its wider error set (`PyPdfError` **plus** `AttributeError`/`ValueError` out of
  pypdf's own recovery code — measured on 300 corrupted PDFs) and the kerning repair moved out of
  `documents/ingestion.py` into `research/` because the import direction is documents → research;
  ingestion now wraps it and still raises `UnsupportedUpload`. A PDF with no text layer, or one pypdf
  refuses, is `UNPARSEABLE` — never a document that states nothing. And **`harvest.change_digest` is
  the one rule for "did this source change?"**, used by `persist_snapshot` and `read_program_page`
  alike: while only one of them knew about PDFs, a PDF source never cache-hit and every run re-read
  and re-paid for it.
- **Overflow is logged, not swallowed.** `page_text[:24_000]` cut mid-word and told nobody.
  `_capped` cuts between blocks and emits a WARNING naming how many lines were dropped, because
  a page we only partly read must not look like a page that said nothing.
- **A programme rule may not lower a key's enforcement.** `resolve_rules` applies programme rules
  last and at the highest rank, but it now refuses to let an `ADVISORY_*` rule replace a `BINDING`
  one on the same key. **This is a PII boundary, not tidiness.** Every derived rule is
  `ADVISORY_HIGH_RISK`, four of the seven derivable keys have `BINDING` seeds, and
  `render.py::_blocked_by_content_only_rules` inspects `BINDING` rules only — so before the guard,
  a sentence a model read off a third-party page downgraded a funder's requirement for every
  tenant, and on `date_of_issue_required` (a content-only key *because* `EUROPASS_API` can never
  satisfy it) that downgrade stopped the pre-render gate firing and shipped a student's name, date
  of birth, education and employment history to europa.eu on a render that had been refused before
  any egress. Pinned by four tests in `tests/documents/test_catalog_rules.py`, one of them asserting
  the gate directly. Specificity still applies where it is safe: an advisory programme rule on a key
  nothing BINDING covers wins as before, and a *hand-curated* BINDING programme rule still replaces
  a BINDING catalog one — the guard is about enforcement level, never about provenance.
- **Since 2026-09-26 a page is read by the typed grammar, and the three-reading judge below is the
  fallback.** With a decision provider configured (`OPENROUTER_API_KEY`, Jev through OpenRouter),
  `derive_page_rules` asks two typed requests per page plus one page-level request, over four
  slots and closed lists, and projects the answers onto sinks that already exist
  (`rule_sinks.py`). The bar is 0.85, with three phrasings on the Europass format. An uncertain
  reading becomes a note on the document; no person is waiting on it. With no key at all, the
  judge described below runs unchanged, so a missing key degrades cost, not correctness. An
  outage is not a missing key: it raises and the page's previous rows stand
  (`DecisionsUnavailable.kind`, `not_configured` vs `failed`, tells the two apart). The judge is deleted only when the page-corpus
  gates of the 2026-09-26 addendum §8 pass on Jev. Its measurements stay the record: the keyword
  rule's 61%, the Swiss supervisor's-CV attribution error, and the rule that a programme rule may
  not lower a key's enforcement. Design:
  `docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md` §6, as
  amended by `2026-09-26-requirement-reader-addendum-design.md`.
- **The grammar is closed on purpose, and `unapplied` is a feature.** A page can state a
  requirement no operation carries, such as the first "publications in APA style". The sentence is
  kept, shown on the document and counted. It is never passed to the writing model as a free
  instruction: that is the door a hostile page would use to reach the generator, and the way the
  old attribution errors got in. When the count shows a kind is real, add the operation and its
  handler in code, then run `manage.py rederive_rules`. Every programme that ever stated the rule
  gets it without a page being refetched.
- **The CV-format decision is three readings, from two model families, agreeing on the ACTION, and
  nothing else — the keyword rule is gone.** Design and measurement:
  `docs/superpowers/specs/2026-09-13-format-decision-guarantee-design.md`. Measured on 48 real and
  synthetic sentences (`docs/research/cv-format-eval.csv`, pinned by a `live` gate in
  `tests/documents/test_derive.py`): the keyword rule scored 61% and was wrong in the PII direction
  on phrasing it did not know ("we suggest", "advisable", "Wir empfehlen" → `europass_required`); a
  local NLI classifier 54%; `OPENAI_EXTRACTION_MODEL` 100% unanimous on the renderer choice. So:
  `derive.py::candidates` finds the sentences by code over the WHOLE page (every `europass` line,
  every CV-term line ∪ the statement read's DOCUMENT/FORMAT sentences — the vocabulary does not
  know özgeçmiş); `_judge` asks one closed question `_SAMPLES` times in three phrasings;
  `decide` writes the format action, a constraint or a directive only where EVERY surviving sample
  agreed (advisory rules were a majority for part of 2026-09-14, see below) — an advisory
  rule that is wrong costs a warning the student reads beside the quote, one that abstains costs
  the criterion never reaching the CV, while a wrong action ships the student's data to europa.eu.
  Anything short of its bar writes `any` + `UNDECIDED` + an `undecided` rule carrying the sentence,
  which `render_cv_with_warnings` puts in front of the student. Negation, softening and a stated
  choice are all things the closed question answers, each pinned in the gate by the real sentence
  that motivated the old guard. **A sentence naming a referee, supervisor, host or employer is the
  one that it does not answer**: it never yields a rule or a directive, and `derive._THIRD_PARTY`
  enforces that in code — measured live 2026-09-14, two of three readings attributed "Short CV (max.
  2 pages) from this academic supervisor." to the applicant. The guard marks the OUTCOME
  `undecided`/`third_party`; it never drops the sentence, because a skipped sentence is silent.
  **Two voices since 2026-09-18: the regex, and a required `about_whom` field on every directive
  verdict** (`applicant | third_party | unclear`, no default — a skipped answer must not read as
  "the applicant's"). Either one withholds the line, `unclear` included. Ten English words cannot
  read a German or Kazakh page; the schema field can, measured 21 of 21 right across four
  languages on 2026-09-18, at no cost in abstention on the 48-row gate.
  **Since 2026-09-14 the third reading is `ANTHROPIC_JUDGE_MODEL` (`claude-sonnet-5`)**, owner decision,
  because three samples of one model share its systematic bias. So a Europass action needs both
  families to agree while Claude's reading survives. Two limits stay: a refused, truncated or
  off-schema reading from either family is dropped and the page is decided by the two survivors,
  as two survivors always were (logged either way; a lost Claude reading logs "judged by one model
  family"), and a reading is dropped only after its one retry also fails; and a *unanimous wrong*
  answer still never abstains. **Measured 2026-09-14, 17 live
  rounds of the 48-row gate, and the 48/48 above was one lucky run.** Zero wrong Europass actions
  in any round, either judge. The gate itself is flaky on master: OpenAI-only passed 2 of 4 rounds,
  failing both times on d2 ("details on the quality/recognition of the institution" written as
  `include(education.institution_english)` by a majority). Adding Claude first passed 4 of 8: Claude
  read "A Europass CV is not accepted." as `other_template` in 6 of 7 logged rounds, contradicting the
  prompt's own definition, so s7 abstained and spent the one-row format budget. The `other_template`
  definition now says refusing Europass without naming another template is `not_required`; after
  that, 5 rounds passed 4, s7 never abstained, and the failure was d5 written wrong by a majority plus
  emship undecided. Per-reader votes over 4 more rounds showed who forms those majorities: on d2 and
  d5 the OpenAI readings cast 4 stray votes of 16, Claude 0 of 8. **So advisory rules went back to
  unanimity (owner decision, same day).** Over 8 rounds under it: no Europass mistake and no wrong
  advisory rule in any round with all three readings; advisory abstentions 1-5 of 14 per full round
  (gate cap back to ceil(30%)). What now fails the gate is readers dropping out, not disagreement: an
  OpenAI reading off-schema (a round left with two readings, which then wrote "Yes, any CV format is
  accepted." as a format action on a line with no europass word, so no egress was possible), a round
  left with ONE reading, and a round with three readings where every row came back undecided — the
  last two unexplained. Under unanimity one thin reading abstains the whole page, **so each reading
  is now asked once more when it comes back missing (refused, cut off, off-schema) or thin (skips any
  line)** — `derive._with_one_retry`, never a loop. After it, 5 live rounds (4 by script, 1 the pytest
  gate) all passed with three readings, 0 wrong, 0-1 format and 1-3 advisory abstentions; the retry
  recovered an off-schema OpenAI reading in one of them. **Cost:** at most six judge calls per changed
  page, not three, and only on a failure. Both SDKs raise `ValidationError` inside `parse()` on an off-schema answer; the OpenAI
  readings did not catch it and one crashed a whole round — now one dropped vote. Wiring a caller
  owes `ANTHROPIC_API_KEY` (the worker task definition does not carry it) as well as the rate limit. **Anthropic's Usage
  Policy lists "Academic testing, accreditation and admissions" as high-risk**, requiring qualified
  human review before dissemination and AI disclosure where outputs reach individuals. The owner chose
  Sonnet 5 with that clause in front of them; whether it binds this path is open, like the Tavily
  clause above, and the portal tier's Anthropic use raises it too. **Cost:** six model
  calls per changed page (three statement reads plus three judgements) now run inside the one open
  transaction `read_and_derive` holds, so the idle-in-transaction cost flagged above is doubled.
- **A reader block is not a sentence, and two things assume it is.** Measured 2026-09-18 on
  MEMBIOMED's real how-to-apply page: `candidates()` returned two, and the longer was **1,935
  characters** — a whole document checklist in one `<p>`. (1) Both quote stores cap at
  `constraints.QUOTE_MAX_CHARS` (1,000), so the page raised `ValidationError` out of
  `derive_page_rules` and, because `read_and_derive` holds one transaction, took the statement
  write with it — and `PageDirective` is re-validated on *read*, so such a row would have broken
  `generation.py` and `gaps.py` too. `derive._quote` now clips with a `[...]` marker instead:
  splitting blocks into sentences would change what the judge is asked about on every page, which
  is a measured surface, and needs a splitter for every language the catalog reads. (2) The same
  block contains "Reference letters", so `_THIRD_PARTY` matches the whole paragraph and withholds
  the applicant's own rule with it — right about the block, wrong about the sentence. That one is
  **open**; it is the real argument for sentence splitting, to be measured against the 48-row gate.
  Recovery measurement and the full table: `docs/superpowers/research/2026-09-18-cv-rule-recovery-given-the-page.md`.
- **`Program.cv_directives` is the third thing a page can set, and it is typed.** `include(<field>)`,
  `order(<section>, chronological|reverse_chronological)`, `emphasise(<section>)` over the closed
  lists `derive._INCLUDE_TARGETS`/`_SECTIONS`, pinned to `CVContent` by test. `include` reaches the
  generation prompt as a field name (never the page's sentence) and, when the ledger lacks the
  field, becomes a `PROGRAMME_REQUIRED` gap question (`gaps.programme_required`) with the sentence as
  evidence; `order` and `emphasise` are applied at render (`render.apply_directives`,
  `_section_order(emphasise=)`). **There is no `exclude`**: the one directive a hostile page would
  want is the one that hides a field. A sentence all three readings agree states a CV requirement
  no field, section or key can carry is written as an `unapplied` rule — shown, never dropped.
  `constraints._MULTI_KEYS` keeps every `undecided`/`unapplied` rule through `resolve_rules`, which
  otherwise merges by key.
- **A page under 1,500 readable characters at 20,000+ bytes is `unreadable`, on the snapshot, and
  derives nothing.** Measured shells: 289 / 265 / ~1,000 characters at 52,998–458,728 bytes; the
  smallest page that read fine is 3,095. Two-sided because a 300-byte page whose text is the page
  is not a shell. Previous rows stand; the page is the browser tier's to render.

### A requirement the reader can see and the engine cannot act on

`derive_cv_format` never derives `funder_template` or `structured_fields_only`, and that is correct:
the first needs a template module (`render.py::_funder_dispatch` knows only SISGP and RHODES), so
deriving it from a sentence would route every other funder to `UnsupportedRenderVariant`.

The consequence is measured, 2026-09-12, against the Swedish Institute's real SISGP page. The reader
stored "You must use SI's provided template for CV 2026/2027." as a REQUIRED FORMAT statement — it
read the requirement correctly — and `cv_format_requirement` stayed `any`. For SISGP that is
harmless, because `SEED_FUNDERS` carries `funder_template` by hand. For a funder nobody has
curated, the CV renders STANDARD, the student sees no warning, and the page's own "use our
template" sits in `ProgramStatement` with nothing reading it.

Closed 2026-09-13: a FORMAT sentence naming a template the engine does not know is the
`other_template` verdict, which writes `any` + `UNDECIDED` and an `undecided` rule with the
quote — visible to a human, never resolved to "no requirement".

### A programme page the reader could not see — solved by the vendor path, 2026-09-19

`readable_text` reads whatever HTML it is handed, and a served page is often a shell whose
criteria render client-side. Measured 2026-09-12, on our own egress: Türkiye Bursları'
application-requirements page is 88,646 bytes and yielded ~1,000 characters of prose — section
headings and teaser copy, nothing else. Sciences Po's 458,728-byte page yielded 289. JASSO's
52,998 yielded 265. Each read returned zero statements — the honest outcome for that input, but on
the outside indistinguishable from a page that states no requirements.

**Re-measured 2026-09-14: rendering does not recover these pages, and the premise above is not
established.** Five live under-floor pages (JASSO's MEXT, Honors and exchange scholarship pages,
Türkiye Bursları' programme index, Sciences Po's Eiffel page) were rendered through the real
`browser_server` running locally and gained **zero** readable characters. Their total visible text,
navigation included, is under 4,000 characters: short pages inside heavy templates, not JavaScript
shells. A render-first fallback was built, measured to recover nothing, and dropped by owner decision
the same day. Two of the figures above are corrected by that run:

- **JASSO's 52,998 bytes / 265 characters was a not-found page.** Retired JASSO URLs redirect on-origin
  to `/notfound.html`, exactly that size and text. It passes `require_same_origin` and is archived as
  the page. Any probe of this path must print its final URL.
  **Detected since 2026-09-18, in two checks, and the flag is now a reason.**
  `OfficialSourceSnapshot.readability` is `OK | SHELL | SOFT_404 | UNPARSEABLE` in place of the old `unreadable`
  boolean, because "we could not read it" and "it says nothing" are the same silence from outside and
  each cause needs a different answer. The checks are `reader.redirected_to_a_not_found_page` (the
  final URL's path changed and is /404-shaped — free, URLs only, so a thin real page and a programme
  about error analysis cannot trip it; measured live 2026-09-18, a missing path under jasso.go.jp
  lands on `/notfound.html` at **HTTP 200**, which `fetch_official_source` cannot see because it
  raises on status ≥ 400 only) and a per-host control fetch of `reader._CONTROL_PATH`, cached a day,
  whose `content_digest` is compared with the page's. A control that redirected off that path is
  discarded rather than trusted — accepting it would mark every read of wherever it landed a soft 404.
  **Consequence for tests: a fake `retrieve=` that returns the same body for every URL now describes
  a host whose every page is its not-found page**, and the read is correctly recorded `SOFT_404`
  instead of derived. The doubles in `tests/research/test_reader.py` and `tests/documents/test_derive.py`
  raise `SourceBlocked` for that path, which is what a polite host does.
- **The floor marks short real pages unreadable.** Sciences Po's Eiffel page is 467,380 bytes and
  1,093 readable characters, all real prose, so it derives nothing. That is loud, not silent, but it is
  a coverage loss on the long tail. Do not lower the floor on these five pages alone: without a render
  that demonstrably adds text, a short page and a shell whose script failed look the same.


**And rendering by a vendor does recover the pages that genuinely are shells — the two measurements are about different pages, not about each other.** Measured 2026-09-19 against a
Türkiye Bursları checklist page
(`turkiyeburslari.gov.tr/sayfa/the-ultimate-checklist-for-turkiye-scholarships-applicants-61`):
Firecrawl returned 6,445 characters of markdown with the requirement text present, scrape.do
7,050. So the vendor path closes the JS-rendering half of this section. It closes nothing on the
2026-09-14 five, because there was no hidden text to render: three were a soft 404, and the other
two are short real pages inside heavy templates.

**What did not go away: a shell page and a page that genuinely states no requirements are still
indistinguishable from the outside**, and `read_program_page` still keeps the previous rows in
both cases. That hazard is about silence, not about JS rendering, so a vendor closing the
rendering gap does not close it — a page a vendor also returns empty still needs `readable_text`'s
1,500-character `unreadable` floor and a human eventually confirming which case it is.

## Derived data and the ML corpus — deliberately incomplete

`phased requirements.md` §6.1 specifies an opt-in platform-intelligence pipeline. **Almost none of it
is built, and that is a recorded MVP decision (2026-09-11), not an oversight.** Read
`docs/superpowers/specs/2026-09-10-erasure-console-design.md` before extending any of it.

**What exists:** `audit.Pseudonym` — a random UUID primary key, a tenant, a unique FK to the student.
Nothing writes it. `advance_deletion` deletes its row on the `EXECUTED` path.

**The one rule, and it is load-bearing:** any table holding data derived from a student points at
`Pseudonym` with **`on_delete=models.CASCADE`**, never at `Membership` directly and never with
`SET_NULL` or `PROTECT`. That foreign key *is* the GDPR deletion-propagation guarantee — erasure
deletes the `Pseudonym` row and the database removes the derived rows. A test pins it. The reason the
empty table ships before any writer is `documents.EuropassRenderCache`, which stores a digest derived
from a student's CV with no FK back to them, so the erasure completeness test cannot see it and it
survives erasures today. Nobody decided that; nobody was thinking about deletion when it was written.

**What is deliberately absent:** the extractor, the feature schema, banding, the *k*-threshold, the
generalized second variant, `SET_NULL`, the re-identification assessment, and the data lake. §6.1
holds the requirements for all of it. **Nothing today retains a derived row through an erasure**, and
nothing should until that assessment exists — full precision and survival-through-erasure cannot both
be had, because anonymity means a row describes more than one person and an exact institution plus
exact degree title plus programme plus intake year sometimes describes exactly one. Aggregating does
not escape it: a counter cell of 1 is a person.

**Two prerequisites block the whole pipeline, and both are invisible from inside the ML work:**

- **No admission or funding outcome exists anywhere.** Checked across all 73 models, 2026-09-11.
  `portals.Application.State` ends at `CONFIRMED`, which means the *portal* accepted the submission,
  not that the institution accepted the applicant; `funding.StudentDecision` records a *student*
  rejecting a recommendation. There is no training label. §6.1 now makes recording one a prerequisite.
- **Direct-to-student training consent has no model.** `tenancy.AgencyDataUseAgreementVersion` covers
  agency tenants only, and `documents.ConsentEvent` is document-approval consent, not privacy consent.
  The platform sells both direct-to-student and white-label (`phased requirements.md:687`), so the B2C
  half of the opt-in gate does not exist.

**"Store everything" is already true and is not what these rules constrain.** The tenant database
keeps CVs, statements, documents, facts, notes and messages at full fidelity, and erasure reaches
them — 124 fields across 32 models. Every restriction above governs a *derived copy built for
training*, which does not exist. When the deferred "which features matter" analysis happens, it
happens inside the tenant against live data under RLS — not by exporting a table or assembling a
cross-tenant CSV. §6.1 prohibits copying raw tenant databases; that clause bites exactly when someone
first says "let me pull the data and have a look".

**Grades are stored as awarded, with the scale, never converted.** Conversion between grading systems
is one-way — a normalized figure derives from an awarded grade, never the reverse — so normalization
and banding are modelling decisions taken when there is data to take them against.

## Erasure: the schedule is deferred, and that is a deployment blocker

`apps/audit/management/commands/execute_due_erasures.py` moves a `DeletionRequest` from `APPROVED` to
`EXECUTED` once its thirty-day window expires. **Since 2026-10-25 it runs daily from
`ExecuteDueErasuresRule`** (`infra/template.yaml`, ENABLED, `WorkerTaskDefinition`, pinned by
`tests/infra/test_template.py::test_erasure_ships_with_its_schedule_enabled`). The rule was
deliberately deferred on 2026-09-11 because nothing was deployed; it is still unexercised against a
real stack, and it needs `scripts/create_erasure_guard.sql` run first (`docs/runbooks/deploy.md`).
Do not disable it.

The failure this guards against is silent and worse than either half alone. A student who requests
deletion is locked out immediately and their statutory month starts running. If the command is never
invoked, they are locked out **indefinitely and never erased** — and every screen says the right
thing, so nothing surfaces it. Design:
`docs/superpowers/specs/2026-09-10-erasure-console-design.md`.

**Rung 5 of the fetch ladder has a schedule, and it stays off.** `manage.py retry_due_fetches` runs
from `RetryDueFetchesRule` in `infra/template.yaml`, still `State: DISABLED`. It shipped disabled
because `WorkerTaskDefinition` ran as `runtime`, which `HostProfile`/`FetchAttempt`'s write policy
did not name — so the reschedule `UPDATE` matched zero rows in silence (failure mode 1) and the
first `fetch_page` died on "new row violates row-level security policy". That reason is gone
(2026-09-25): the worker now runs as `runtime_engine`, the role those policies name. It stays
`DISABLED` for a different reason — `retry_due_fetches`'s own docstring says a successful retry
persists no snapshot, re-runs no reader and closes no task, so the caller that originally needed
the page still fetches and pays for it again. Enabled on a six-hour schedule, that spends vendor
credits every run for a result nothing downstream receives. Enable when a retry hands its
delivered page to the caller that needed it.

The owner console (`/owner/deletions/`) is the only exit from `RETENTION_REVIEW` and the only place a
partial erasure is ever reported — after an erasure the student is gone and cannot be told anything,
so `identity_retained` has exactly one audience. `apps/audit/views.py::deletion_console` passes that
list as `.values()` rows **on purpose**: a retained identity is by definition unscrubbed, so a
`Membership` reachable from the template reaches `display_name` and `auth.User`, putting an erased
person's real name back on the screen of the agency that erased them. Do not "improve" it into
`select_related("student")` — `test_the_partial_erasure_list_carries_no_name` asserts the row cannot
reach a `Membership` at all.

One more thing the command's own tests cannot show you: a *caught* exception inside
`transaction.atomic()` is a Python error, not a database one, so it never marks the transaction for
rollback. A test that asserts "one student's failure did not roll back another's erasure" using an
error the command catches passes under a single per-agency transaction too, and proves nothing. The
atomicity boundary is pinned by `test_a_completed_erasure_survives_a_later_failure_in_the_batch`,
which raises something the command does **not** catch. Measured, 2026-09-11.
