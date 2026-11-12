---
paths:
  - "apps/**/*.py"
  - "tests/**/*.py"
  - "scripts/**"
  - "infra/**"
  - "config/**"
---

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
therefore *revokes* every membership of the guard role except the running admin's, on every run — the removal is an action, not an absence. It needs no separate assertion: a
`REVOKE` the admin cannot perform is an ERROR, so the loop revokes every member or aborts. Verified against a database carrying
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

- **`runtime_engine`** — the worker, Europass worker, mailbox worker and document worker task definitions, and
  every management command run from them. DML on every table; the catalogue's **only** writer — the
  old `catalog_ingestion_write` policies were repointed and renamed `runtime_engine_write`, and
  `catalog_ingestion`, a name in a policy nobody could log in as, is dropped
  (`apps/funding/migrations/0049_catalog_grants.py`).
- **`runtime_web`** — the agency-facing web tier only. DML on every tenant table and **no privilege
  at all** on every table carrying the `shared_catalog_select` policy (27 at 0049, more since;
  `catalogue_tables()` reads the live list) (the catalogue, plus the
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
`rls_enforced_orm` repoints Django's default connection at a throwaway `NOBYPASSRLS` role, so
managers and FK descriptors run behind the policy too.

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
2. **A person's data** → never cross tenants in the database. A platform admin (Membership role
   `PLATFORM_ADMIN`) works inside the one agency they need, in that agency's own site. **Owner decision,
   2026-10-11:** staff may *view and download* any student's files in an agency without a
   `SupportGrant`, because every view and download is recorded first (a `StaffFileAccess` row the agency
   owner sees on their console, plus a `StaffFileView` log line listed across agencies by
   `manage.py staff_file_views` and counted by the `StaffFileViews` metric, no alarm:
   `apps/audit/staff_access.py`).
   Counsellors stay view-only. Everything else (editing, acting for a student, other personal data)
   still takes a `SupportGrant` (`apps/tenancy/models.py`, `require_active_support_grant`,
   `docs/runbooks/support-access.md`): time-boxed, reason-carrying, alarmed on every use.
3. **Not this:** widening the policies for a platform-admin GUC, or giving any connection role
   `BYPASSRLS`. The support-access runbook rules it out by name, and the measurement rules it out on
   merits — it exposes every membership row in every tenant to answer questions that need one bit.
   The 2026-10-11 decision does not change this: staff work inside each agency's own site, so one
   agency's login cannot reach another agency's students; a widened policy or `BYPASSRLS` role would.

To test any of this, use `rls_enforced_orm` (Testing it, above).

Measured 2026-09-09 on the real policy shape, not inferred: with `app.tenant_id` set to tenant A and a
user holding an active membership in tenant B, a plain `_base_manager` SELECT and a `SECURITY
DEFINER` function owned by the table owner both returned **zero** rows; the same function owned by a
`BYPASSRLS` role returned the row. Reasoning and the full option comparison:
`docs/superpowers/specs/2026-09-09-identity-erasure-design.md`.
