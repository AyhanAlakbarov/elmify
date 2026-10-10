# The catalogue is not an agency's to read — splitting `runtime` by caller

**Status:** design, approved in brainstorm 2026-09-25. **Implemented 2026-09-25** on
`claude/catalog-read-split`; the text below is the design as approved and is not rewritten.

> **As built (2026-09-25) — where it differs from what follows.**
> - Role names are fixed literals, `runtime_engine` and `runtime_web`, not bootstrap variables:
>   migration grants and policies must name them.
> - Table grants live in `apps/funding/migrations/0049_catalog_grants.py`, not the bootstrap
>   script (a grant only in a psql script is invisible to every test). The catalogue list is read
>   from `pg_policies` at run time: **27 tables** once merged with master's `research_registerentry` and
>   `research_sitejobrecord` (25 before either), not the 13 §12 counted (M2M and evidence-claim through-tables), including `FetchAttempt`/`HostProfile` (owner: no exceptions).
> - `catalog_ingestion_write` policies are repointed to `runtime_engine` and renamed
>   `runtime_engine_write`; `catalog_ingestion` is dropped.
> - The "future catalogue tables" guard is a test (`tests/tenancy/test_catalog_grants.py`), not
>   default privileges, which cannot tell a catalogue table from a tenant table.
> - `PortalTaskDefinition` connects as **`runtime_web`**, not `runtime_engine` as the table below
>   says, through its own `PortalExecutionRole` (web secret + LLM key, never the engine secret).
>   `packets.py` is not on the portal worker's path: a scan of `run_portal_worker`'s import
>   closure finds no catalogue read, and as the engine a sandbox escape could write the catalogue.
> - `funding/0049` creates the two roles only as a superuser; any other caller with either role
>   missing is refused ("run scripts/create_runtime_role.sql as the admin role, then re-run the
>   migration"), so the first production deploy is a two-pass loop (`docs/runbooks/deploy.md`).
> - A new catalogue table's write policy is `TO runtime_engine` and its migration revokes
>   `runtime_web`; a migration that still names `catalog_ingestion` must precede 0049.
> - `scripts/create_runtime_role.sql` runs **before** the first migrate (PG 16+: a non-superuser
>   `CREATEROLE` admin alters only roles it holds ADMIN OPTION on) and asserts rather than sets
>   `NOSUPERUSER`/`NOCREATEDB`/`NOREPLICATION`/`NOBYPASSRLS` (PG 17: only a holder may change
>   those, even to NO).
> - The web tier had three catalogue reads, not one: the kit (now a worker-written copy on
>   `Application`, `capture_requirements`), a programme-existence check at the generate door (now
>   shape-only; the worker drops an unknown id with a WARNING), and a join feeding download
>   filenames (now `DocumentDraft.rendered_filename`, written at render).
> - `user_has_active_membership` is granted to `runtime_engine` only (erasure executes in the worker).
> - `research_domainlease`, `portals_portalform`, `portals_fieldmap` stay web-readable: shared but
>   not catalogue (no `shared_catalog_select`).
**Supersedes:** nothing. **Amends:** the `catalog_ingestion` write model and
`CLAUDE.md`'s "Row-level security: what actually filters a query".

## 1. Why this exists

We sell white-label as well as direct-to-student (`phased requirements.md:687`).
The fetched catalogue — every programme, every scholarship, every quoted
requirement — is the asset the company is built on. **An agency tenant must not
be able to read it.** They see their own students and what those students were
recommended; they do not see the corpus behind it.

Today they can. `shared_catalog_select` is `FOR SELECT USING (true)` on every
shared-catalogue table, and `scripts/create_runtime_role.sql:96` gives the runtime role
`SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public`. Nothing filters
a catalogue read by tenant, because the catalogue is deliberately shared. Any
connection that reaches the database reads all of it.

**"Us" and "an agency" are the same database identity.** `config/settings/
database.py` accepts exactly two roles, `runtime` and `migration`. Tenant
isolation is the `app.tenant_id` GUC on tenant tables; the catalogue has no such
axis and was never meant to.

## 2. What made this visible

The fetch engine (2026-09-25, PR #130) added `FetchAttempt` and `HostProfile`
and fitted them into the shared-catalogue pattern: read by all, written only by
`catalog_ingestion`. Two consequences followed, and both are symptoms of the
same confusion.

**`catalog_ingestion` has never been a real role.** It is `NOLOGIN` and holds no
table `GRANT` anywhere in the repo. The policy that names it therefore blocks
*everyone*, which is why `RetryDueFetchesRule` ships `State: DISABLED` and why
`discover`, `fetch_ladder`, `funding_yield` and the research-fit path are
documented to run as `migration` — a *more* privileged role than the one they
were meant to be constrained below.

**And the grant layer and the policy layer disagree.** `runtime` holds table
GRANTs for every table; RLS is the only thing refusing the write. A reader of
either layer alone draws the wrong conclusion.

## 3. The finding this design rests on

**`RecommendationCandidate` denormalises.** `apps/funding/models.py:91-95`
carries `program_name`, `funding_gap`, `currency` and `eligible` on the
tenant-scoped row, with only *nullable* FKs to `Program` and
`FundingOpportunity` for provenance. An agency renders a student's pack from
tenant tables alone.

**But a first measurement of mine was over-broad, and correcting it is what
§11 exists for.** I first checked the nine `views.py` modules and found one
match — `apps/funding/views.py:242`, a string inside an error message — and
concluded no agency-facing code reads the catalogue. That is true of the view
*files* and false of the web tier, because the reads are one import deep:

- `apps/portals/urls.py` routes `ext/<id>/packet` to `ext_api.packet`, which
  calls `mint_packet`; `apps/portals/views.py:37` renders `kit.html` via
  `build_kit`. **Both read `ProgramStatement` and `ApplicationPrompt`**
  (`apps/portals/packets.py:214`), per student, on a live request path.
- `apps/documents/render.py:147` reads `cv_format_requirement` off a programme
  or opportunity while rendering a CV.

So the pack path is clean — `RecommendationCandidate` really does carry what a
pack renders — but the **application** path is not. §11 is the open fork this
creates.

Verified separately and still true: **nothing traverses a foreign key from a
tenant row into the catalogue** (no `select_related` into `program`/
`opportunity` outside tests). That is the property the design depends on, and
it must stay true — see §7.

## 4. Design

**Replace one `runtime` role with two, split by caller.**

| role | catalogue | tenant tables | telemetry |
|---|---|---|---|
| `runtime_engine` | SELECT + write | SELECT + write | write |
| `runtime_web` | **no GRANT at all** (but see §11) | SELECT + write | none |
| `migration` | owner, unchanged | owner | owner |

**Six task definitions carry `DATABASE_ROLE`, not two.** The mapping is part of
the design, because getting one wrong is a silent outage or a silent leak:

| task definition | role | why |
|---|---|---|
| `WorkerTaskDefinition` | `runtime_engine` | discovery, the fetch ladder, pack building |
| `DocumentWorkerTaskDefinition` | `runtime_engine` | research-fit fetches; `render.py` reads `cv_format_requirement` |
| `EuropassWorkerTaskDefinition` | `runtime_engine` | same render path |
| `PortalTaskDefinition` | `runtime_engine` | `packets.py` reads `ProgramStatement` |
| `WebTaskDefinition` | `runtime_web` | serves agencies — **and the owner console, see §10** |
| `MigrationTaskDefinition` | `migration` | unchanged |

`catalog_ingestion` is **dropped**, not kept alongside. It was a name in a
policy with nobody able to be it; `runtime_engine` is that role made real. The
write policies carrying `catalog_ingestion_write` are repointed to
`runtime_engine`, on the same list §8 derives from `pg_policies`.

### 4.1 The mechanism is GRANT, not RLS

An agency connection must not read the catalogue **at all**. That is precisely
what a table `GRANT` expresses, and it fails closed with
`permission denied for table`, loudly, at the first query.

RLS is for filtering *rows within a table a caller may read*. Using it as an
all-or-nothing ACL is what produced the present state, where the grant layer
says yes and the policy layer says no. **RLS stays exactly as it is for tenant
isolation**, which is the job it is right for.

### 4.2 Why not a filtered catalogue read

The alternative — let agencies read catalogue rows that reached one of their
students — was considered and rejected. It needs a join from every catalogue row
back to a recommendation on every query, it is materially slower, it is far more
code, and it still leaks the shape of the corpus through what is absent. It also
protects nothing the denormalisation does not already protect.

### 4.3 How a connection picks its role, and what that costs to provision

`config/settings/database.py` accepts exactly `runtime` and `migration` today.
It gains `runtime_engine` and `runtime_web` and **loses `runtime`** — an
unrecognised value must keep raising `ImproperlyConfigured`, so a task
definition that was missed fails at boot rather than quietly connecting as
something.

Each new role needs its own credential pair (`POSTGRES_ENGINE_USER` /
`_PASSWORD`, `POSTGRES_WEB_USER` / `_PASSWORD`), which means **two new Secrets
Manager secrets** and the IAM to read them on the task roles that need them —
and only those. `scripts/create_runtime_role.sql` becomes the script that
creates both, keeping its existing refusal to bootstrap against a superuser or
`BYPASSRLS` migration role.

**Nothing is deployed** (AWS account 367842306577 is empty), so no live
credential is being rotated and no running task changes identity. This is the
cheap window, and it closes the first time something runs in anger.

### 4.4 The test fixtures have to grow a second role

`tests/conftest.py`'s `runtime_connection` and `rls_enforced_orm` each build one
role. Both need a per-role variant, because the thing under test is now *which
role you are*. A suite that keeps testing one role proves half the design — and
per §7 the default test role proves none of it.

## 5. What this fixes for free

- `FetchAttempt` and `HostProfile` are written by `runtime_engine`. No third
  credential, no ingestion role, no `SET ROLE`.
- `RetryDueFetchesRule`'s login blocker is gone, but it still ships
  `State: DISABLED` — a successful retry delivers its page to nobody
  (`retry_due_fetches`'s own docstring), so the schedule stays off until a
  retry hands its page to the caller that needed it.
- `discover`, `fetch_ladder`, `funding_yield` and research-fit stop needing
  `migration`. Their `--help` text and the deploy runbook lose that note.

**Never `GRANT runtime_engine TO runtime_web`.** Role attributes are not
inherited through membership, but `SET ROLE` does not need them to be — the
erasure-guard lesson in `CLAUDE.md`. Membership would make the boundary a
discipline instead of a boundary.

## 6. The constraint this places on the interaction surface

`apps/documents/research_fit/` **fetches**, and it hangs off
`letter_approval.mark_letter_ready`, which `apps/documents/api.py` fronts. No
view imports it today (verified 2026-09-25), so nothing is broken now. But when
§10's interaction gate lifts, an agency request that triggers a fit re-check
would need to fetch — which needs catalogue write in the web tier, reopening
exactly what this design closes.

**The rule: a student-facing action that needs a fetch queues it to the worker.**
It does not fetch in-request. That belongs in the interaction surface's own
design; it is recorded here because this is the design that makes it binding.

## 7. What breaks, and how it will announce itself

Any code path that reaches the catalogue from the web tier fails with
`permission denied for table` on its first query — loudly, not silently. That is
the intended failure mode and the reason for choosing GRANT.

**The one way this fails quietly is a foreign key.** Nothing traverses a FK from
a tenant row into the catalogue today (verified §3), and while that holds, a web
query never touches a catalogue table. The day someone writes
`select_related("program")` on a `RecommendationCandidate`, the web tier starts
asking for a table it has no grant on. It fails loudly — but it is worth naming
because this is the same forward-FK hazard `CLAUDE.md` already records for
`TenantManager`, arriving one layer down and in a new disguise.

**No test in this repo can prove any of it.** The test role is a superuser and
bypasses both grants and RLS, so a passing suite says nothing about a role's
real surface — the same trap `CLAUDE.md` records for RLS, one layer down.
Verification must connect as each role, in the shape of the `runtime_connection`
fixture in `tests/conftest.py`.

## 8. Verification

1. A test per role asserting its **grant surface**, connected as that role: that
   `runtime_web` gets `permission denied` on **every** table carrying
   `shared_catalog_select`, and that `runtime_engine` reads them. Derive that
   list at implementation time from `pg_policies` on a migrated database, never
   by grepping the migrations: several tables named in migration text were
   later dropped (`funding_registerlisting`, `funding_institutionidentifier`
   went with the 2026-09-14 register removal), so a grep over-counts and a
   hardcoded list goes stale the next time a catalogue table is added.
2. A test that a student's pack renders end to end under `runtime_web` — proving
   the denormalisation claim in §3 rather than restating it.
3. `runtime_web` must hold no membership of `runtime_engine`; assert it, the way
   `scripts/create_erasure_guard.sql` asserts its own revocations.
4. The existing tenant-isolation suite must still pass under `runtime_web`.

## 9. Out of scope

- **IAM database authentication.** RDS supports it and it would remove the
  stored password from the task definition, but tokens expire in 15 minutes
  while Django holds connections via `CONN_MAX_AGE`, so it needs a connection
  factory that refreshes. Orthogonal; its own decision.
- The interaction surface itself (§6 states the constraint, not the build).
- Anything about tenant-table RLS, which this design does not touch.

## 10. The owner console is in the web tier — "we can see all" is not yet true

`apps/audit/urls.py:24` serves `owner/deletions/` from the **same Django app and
the same `WebTaskDefinition`** as the agency UI. So `runtime_web` having no
catalogue grant means *we* cannot read the catalogue from a platform screen
either, which is the opposite of the requirement that produced this design.

Nothing breaks today: the deletion console reads no catalogue table. But the
moment a platform-side catalogue view exists, it cannot live in that tier.

**Decision, recorded rather than deferred:** platform catalogue access is
ops-side — management commands and the worker, running as `runtime_engine`.
No web-tier catalogue read exists, for us or for an agency. If a platform
catalogue *UI* is later wanted, it gets its **own task definition and its own
role**, so that an agency request cannot reach it even by routing mistake.
Reversible, and it costs nothing until that UI is asked for.

## 11. DECIDED — copy forward; the web tier never opens the library

**Owner decision, 2026-09-25:** an agency sees the recommendation pack and
everything in it — the links, the reasons — and has no access to the corpus.
Option (a) below. The rule that follows: **anything an agency sees is copied
onto that tenant's own rows by the worker; the web tier reads tenant rows only.**

Scoping it against the code made the job smaller than the fork implied:

- **The pack path already complies and needs no change.** `EvidenceClaim` is a
  `TenantScopedModel` carrying `source_url` and `claim`
  (`apps/funding/models.py:47-50`), and `RecommendationCandidate` carries the
  name, gap, currency and eligibility. The links and reasons an agency shows a
  student are already tenant-scoped.
- **The application path is the real work**: `mint_packet` / `build_kit` read
  `ProgramStatement` and `ApplicationPrompt` live. These get copied onto the
  packet at mint time.
- **CV rendering** reads `cv_format_requirement`, but only from
  `DocumentWorkerTaskDefinition` / `EuropassWorkerTaskDefinition`, which are
  `runtime_engine`. No change.
- **The "why for you" text does not exist yet.** `explanations.draft_explanation`
  has no caller and there is no field storing its output. **Constraint for
  whoever wires it:** it must write to a tenant-scoped row, not compute at
  render time from catalogue content — same shape as §6's rule.

### The fork as it stood, kept for the record

§3 establishes that `mint_packet` and `build_kit` read `ProgramStatement` and
`ApplicationPrompt` on a live request, and `render.py` reads
`cv_format_requirement`. Those are not corpus enumerations — they are "what does
*this* programme require of *this* student" — but they are catalogue reads from
a tier that is supposed to have none. Three ways out, and this one needs the
owner:

**(a) Denormalise into the packet, like the pack.** The worker captures the
required statements onto the packet row at mint time; the web tier serves its
own stored row. Consistent with `RecommendationCandidate` and with the `PACKET`
`ApplicationStep` already being "the authoritative record of what the platform
prepared". Costs: `mint_packet` moves behind the worker, which changes its
latency contract — the extension currently asks for a packet and gets one now.

**(b) Grant `runtime_web` SELECT on those two tables only.** One line, no
restructuring. Costs: `ProgramStatement` is the quoted-requirement content —
a meaningful slice of the corpus, readable wholesale by any agency connection.

**(c) Row-filtered read.** Statements for programmes this tenant has an
application against. Costs: the join §4.2 rejects, though bounded by application
rather than by corpus, so cheaper than the general case.

**Recommendation: (a)**, because it is the pattern already proven one layer over
and it is the only one of the three where an agency connection genuinely cannot
read corpus content. But it is the most work, and the latency question is a
product call, not a security one.

## 12. Open question for the owner

**Is every `shared_catalog_select` table off-limits to an agency?** The
`funding` corpus and the `research` organisation register are clearly ours. `FetchAttempt` and `HostProfile`
are telemetry and belong to the engine alone — an agency has no reason to read
them either, so the simplest answer is that `runtime_web` gets none of the 13.
That is the assumption this design proceeds on; say so if any of them must
remain agency-readable.
