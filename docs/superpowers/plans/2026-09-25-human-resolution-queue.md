# The Human Resolution Queue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every question about the shared catalog that the machine cannot answer goes to exactly one place: a platform-only queue. The platform's own operators, and nobody else, see it and answer it with one click, and each answer is written back to the catalog so that the same question is never asked again. No agency ever sees the queue, and no row in it names a person.

**Architecture:** One model, `research.ResolutionItem`: platform-only, outside tenant RLS, readable and updatable by the runtime role only when the request's `app.tenant_id` is the platform agency. It lives in one package, `apps/research/resolution/`, split by who calls it:

- `kinds.py`: the closed registry of kinds, with per-kind evidence and resolution schemas.
- `writers.py`: `file_item` / `withdraw_item`. Only the catalog-side roles call it.
- `operator.py`: the listing, `decide` and `park`, reached from the web request.
- `apply.py`: the write-backs. This runs under a catalog-writing role, because the runtime role cannot write the shared catalog.
- `priority.py`: the read-time ordering.

The lifecycle has three steps:

1. **An operator decides.** This happens in the web request, as the runtime role.
2. **A command applies the decision.** `manage.py apply_resolutions` runs as `migration` or `catalog_ingestion`.
3. **The row is deleted.** Once the answer is in the catalog, the catalog is the memory and the queue holds nothing.

Every transition leaves an `AuditEvent` under the platform agency.

**Tech Stack:** Django 5.2, Postgres 17 RLS, Pydantic v2 (`extra="forbid"`), pytest with the repo's test DB and the `runtime_connection` / `rls_enforced_orm` fixtures.

**Spec:** `docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md` §11. Read that section in full, plus §12 (the "platform-only" row), §16 item 12, and decision-log rows 26, 27 and 33. This plan is §16 item 12. Read the "Row-level security" section of `CLAUDE.md` before Task 2. Tasks 2, 5 and 13 are the three failure modes it describes.

**Base branch:** `origin/master` at `115c752` (2026-09-25). Work in a fresh worktree. Test database: `POSTGRES_DB=tehsil_resolution_queue`. Never share a test DB between sessions.

---

## Corrections to the spec, found by reading the code

These change the design. Each one was checked against `master` on 2026-09-25. None is left for the executor to rediscover.

1. **`/owner/` is the *agency* owner's console, not the platform's.**
   - §11 says the queue is "listed on the owner console (`/owner/`, where `deletion_console` already lives)". But `apps/audit/views.py::deletion_console` gates on `current_membership(request, Membership.Role.OWNER)`, which is every agency's own owner, and it lists that agency's own `DeletionRequest` rows through the tenant-scoped manager.
   - Putting the queue under `/owner/` would put it next to a screen every B2B client's owner opens. The one thing decision 26 rules out is an agency seeing the queue.
   - **This plan mounts it at `/platform/resolution/`.** It is gated on `Membership.Role.PLATFORM_ADMIN` *and* on the request's host resolving to the platform agency.
   - "Owner console" in §11 is read as "the platform owner's console". The spec text is left alone, per the shared rules; the PR description flags it.
2. **No "platform agency" exists in the code.**
   - `tenancy.Agency` has no marker, and there is no setting for it (checked by grepping for `PLATFORM_AGENCY`, `MASTER_AGENCY` and `is_platform`).
   - `Membership.Role.PLATFORM_ADMIN` exists, but any agency can hold one. So "the master agency sees everything" has nothing to key on.
   - Task 1 adds `Agency.is_platform`. A partial unique constraint allows at most one such agency. It is set by an admin command, never by a view.
3. **The runtime role cannot write the shared catalog, so a one-click write-back cannot happen inside the click.**
   - The web runs as the runtime role.
   - Every shared-catalog table carries only `shared_catalog_select` (SELECT for everyone) and `catalog_ingestion_write` (ALL for `catalog_ingestion`). `test_shared_catalog_runtime_dml_is_denied_by_rls` pins this.
   - A console view that tried to set `Organisation.official_website` would run legal SQL and match zero rows. That is `CLAUDE.md` failure mode 1 in a new place.
   - So the click records a **decision**, and `manage.py apply_resolutions` applies it under the role that may write the catalog (Task 7). This is also what lets the applier re-check a decision against evidence that changed between the click and the write.
4. **`resolved_by` cannot be a column.**
   - §11 lists `resolved_by (a platform operator)`. The same section's own rule is that the item "carries nothing about a person … never a student, a membership or a tenant id", and a test asserts it declares no FK to `Membership`.
   - An operator *is* a `Membership`.
   - The operator is therefore recorded where people are recorded: `AuditEvent.actor`, tenant-scoped under the platform agency, which erasure reaches. The row keeps no operator pointer.
   - "A second operator for a parked item" and the per-operator daily cap are both answered from `AuditEvent` (Task 5).
5. **`priority` is not a column either.** §11 lists it as a field and, in the same paragraph, says it is "computed at read time … so the number lives in a query and never in a row". This plan follows the second statement.
6. **`OrganisationIdentifier(source=HUMAN)` has no field to land in.**
   - The model has `scheme` and `value`, with a closed `_IDENTIFIER_SCHEMES` and a CHECK constraint.
   - Task 7 adds `HUMAN` as a scheme, with `value = "<register>:<external_key>"`. This is the binding a person made, and the existing `(scheme, value)` unique constraint is what makes it "never asked again".
7. **§11 now has five kinds; the brief names four.**
   - `SITE_UNVOUCHED` was added on 2026-09-24 (§6.4a item 5, decision 33). Its writer is the hidden-gems programme pass, which is item 10's.
   - This plan builds the four kinds the brief names.
   - Task 3 makes the kind registry the only place a kind is declared, and a test pins that. Item 10 then adds `SITE_UNVOUCHED` as one registry entry, one applier function and one constraint migration. It does not need a second design.
8. **`KIND_OR_COUNTRY_UNSURE` must also carry `funds_students`.**
   - §11's option list is "kind · country · not an organisation". But `classify_organisation` abstains when the confidence is below `ORG_CLASSIFY_MIN_P` **or** when `funds_students` is None (`apps/research/classify.py:233`).
   - If an operator answered only kind and country, the applier would have to set `classified_at` (or the item is re-filed on the next run) and leave `funds_students` NULL. That caches a non-answer to the one question the classifier exists to settle.
   - So the resolution requires `funds_students` as well.

---

## Why platform-only is a deliberate third RLS case

The repo has two RLS shapes today, and this table fits neither:

| | tenant-scoped (`ENABLE` + `FORCE`, `tenant_isolation`) | shared catalog (`ENABLE`, `shared_catalog_select` + `catalog_ingestion_write`) | **platform-only (this table)** |
|---|---|---|---|
| who reads | the one tenant in `app.tenant_id` | every tenant, and no GUC at all | **only a request whose `app.tenant_id` is the platform agency** |
| who writes | that tenant | `catalog_ingestion` (and the owner, since it is not FORCE) | **writers and the applier as `catalog_ingestion` / owner; the operator updates, never inserts or deletes** |
| carries | one agency's data | facts about the web | **questions about the web that only the platform may see** |

Tenant-scoped is wrong for three reasons:

- One question about a shared host would become one row per agency that happened to meet it. The cross-tenant dedupe §11 depends on ("one resolution serves every agency") would then be impossible by construction.
- Every row would carry a `tenant_id`, which §11 forbids.
- Every agency could see its slice, which decision 26 forbids.

Shared-catalog is wrong because `shared_catalog_select` is `FOR SELECT USING (true)` to `PUBLIC`. Every agency's request could list the queue: which hosts we cannot open, which awards our readers disagree on, and what blocks whom. That is precisely what decision 26 says agencies never see.

So the policy asks a different question from both: *is this the platform's own request?* The question is phrased through the tenant GUC the host middleware already sets from the **verified domain** (`HostTenantContextMiddleware`). A request arriving on an agency's host carries that agency's id and sees zero rows, whatever the view code does.

This is **not** `CLAUDE.md`'s forbidden "widening the policies for a platform-admin GUC":

- That rule is about tenant tables, where such a widening exposes every agency's people.
- This predicate widens nothing. It *narrows* a table that holds no tenant data to one tenant.
- It adds no GUC. It reads the existing `app.tenant_id` and looks it up in `tenancy_agency`, which carries no RLS and which the runtime role can already read.

**What the database boundary does and does not stop:**

- **It stops:** an agency-host request reading the queue, whether through a bug, a new view or a forgotten filter.
- **It does not stop:** compromised runtime code, which can call `set_config('app.tenant_id', …)` as easily as any policy could check it. It also does not stop a runtime session that flips `tenancy_agency.is_platform`, since the runtime role holds UPDATE on that table.

The platform-agency check is therefore a fail-closed guard against mistakes. It is not a privilege boundary against the application itself. It is written down here so nobody later cites it as one.

**Not `FORCE`**, on purpose, matching the shared catalog:

- Every writer of this table runs today as the table owner (`DATABASE_ROLE=migration`, which is how `manage.py discover`, `funding_review` and `classify_organisations` run: `CATALOG_ROLE_NOTE`) or as `catalog_ingestion`.
- `FORCE` would filter the owner through the platform predicate too. Every writer would then need the platform GUC set, which re-creates failure mode 1 for any writer that forgets.

---

## The writers today, and which of them become queue writers

`ConsultantResearchTask` (tenant-scoped, `FORCE` RLS) has one writer, `apps/research/services.py::record_blocked_source`, and one direct `get_or_create`. The call sites are below.

**Nothing in `apps/` lists the table: no view, no template, no command.** That is why the retired uses need no migration of rows, only of writers.

| caller today | what it files | becomes |
|---|---|---|
| `pipeline.py:605` `_open_task` on `SourceBlocked` whose outcome is `BLOCKED` or `UNREACHABLE` | "we could not open this lead" | **`HOST_UNREACHABLE` writer** (Task 9), subject `host:<hostname>` |
| `pipeline.py:564` the vendor rendered an empty shell | "no readable content" | **`HOST_UNREACHABLE` writer** (Task 9), same subject; the trail says "rendered empty" |
| `pipeline.py:605` on `SourceBlocked` with `DEAD` / `OFF_SITE` / `INVALID` / `RETRY_SCHEDULED`, on `DomainBusy`, or on `ValueError` (`UnsafeTarget`, canonicalisation) | the raw exception text | **not a writer; retired.** A 404 is a known answer. `OFF_SITE` and `UnsafeTarget` are safety refusals a person must not be sent to open. A scheduled retry and a busy domain are "not now", and the retry queue already owns them. They go to the run's `degraded` list, which `DiscoveryReport` already returns and `discover` prints. |
| `pipeline.py:707` `_extraction_failure_reason` | "extraction failed: …" | **not a writer; retired.** It is our defect, not a question an operator can answer without research. It goes to `degraded`. |
| `pipeline.py:733`, `:771` "no evidence for a catalog row" | a page with no programme fields | **not a writer; retired** to `degraded`. There is no closed question to ask. |
| `pipeline.py:524`, `:553` an aggregator with no official link / a hop that landed on a catalogue | a name without a site | **not a writer; retired** to `degraded`. An aggregator is fetched for names only (§6.4). Resolving the name is item 8's resolver, whose *residue* files `SITE_UNKNOWN` through the interface Task 11 provides. |
| `services.py::handle_research_message`, `result.review` (`POSSIBLY_ELIGIBLE_REVIEW`) | one student's condition | **stays tenant-side.** §11 keeps it with the agency, because it concerns that student. Unchanged. |
| `services.py`: low-confidence candidate, empty pool | one run's candidate or pack | **stays tenant-side.** It is about a student's run. Unchanged. |
| `services.py`: no-origin programme or award | a catalogue row with no official source | **stays as is in this plan.** It is a catalog invariant breach, not a closed question, so it is not a queue kind. It is tenant-filed because it is raised inside a student's run. The fix belongs in `pool.py` (never return an origin-less row). Named in "Out of scope". |
| `services.py`: `result.degraded` | a catalogue row that failed translation | **stays as is in this plan**, for the same reason as the previous row. |
| `funding/services.py::consider_named_program` | a programme a student named | **stays tenant-side.** `resolve_named_program` is a counsellor's action on the agency's own candidate and writes nothing shared (decision 27 is about the engine, and this is not the engine). |
| `manage.py funding_review` (not a `ConsultantResearchTask` writer) | lists `FundingOpportunity` rows with `kind^=I`, `served=False` and `review=""` | **its AGREED-but-unservable and UNAGREED rows become `AWARD_DISPUTED` items**, filed by the reader (Task 8). The command becomes a CLI over the same queue and the same `decide`, so the console and the terminal cannot disagree. ABSTAINED and WITHDRAWN rows leave its listing (see Task 8). |
| `classify.py::classify_organisation` "abstained" from the last rung (not a writer today) | nothing; the row stays askable | **`KIND_OR_COUNTRY_UNSURE` writer** (Task 10) |
| item 8's resolver residue (not built) | — | **`SITE_UNKNOWN` writer**, through `file_site_unknown` (Task 11) |
| `poll_monitor_checks` "removed" and `fetch/__init__.py`'s refusal paths | deliberately nothing (their own comments say why) | **unchanged.** The monitor's `removed` becomes a snapshot fact, and the fetch engine stays tenantless and queue-free. The pipeline, which knows it is a lead, decides what reaches a person. |

`manage.py discover --tenant` stays. It is also the cost-attribution actor (`pipeline.py:482`), so dropping it is a separate change.

---

## It is a queue, not a ledger: what moves an item out, and who may

A row exists only while a question is **live**. The answer lives in the catalog, which is the memory. The record of who answered lives in `AuditEvent`. So a row is **deleted** when it leaves, and nothing is kept in a terminal state. A `state` of `APPLIED` would be a ledger growing inside a queue: the thing `SiteJobRecord`'s docstring warns about, in reverse.

| transition | who | enforced by |
|---|---|---|
| (none) → `OPEN` | a **writer** (Tasks 8–11), running as `catalog_ingestion` / owner | no runtime INSERT policy exists, so the console cannot create one |
| `OPEN` → `PARKED` ("I don't know") | an **operator** | `operator.park`; `AuditEvent resolution.parked` |
| `OPEN` → `DECIDED` | an **operator** | `operator.decide`; the resolution is validated against the kind's schema; `AuditEvent resolution.decided` |
| `PARKED` → `DECIDED` | a **different** operator from any who parked it | `operator.decide` reads `resolution.parked` events for this item |
| `DECIDED` → deleted (applied) | the **applier** (`apply_resolutions`) | no runtime DELETE policy; `AuditEvent resolution.applied` (SYSTEM) |
| `DECIDED` → `OPEN` (stale or refused) | the **applier**, when the evidence changed or the write-back refuses | sets `apply_error`; the item returns to the listing with the reason shown |
| `OPEN` / `PARKED` → deleted (withdrawn) | a **writer**, when the machine answered the question itself (the award is now served, the host now opens, the classifier now decides) | `writers.withdraw_item`; never touches `DECIDED` |
| `OPEN` unopened for 30 days → deleted (expired) | the **applier** | `expires_at`; a writer re-files it with fresh evidence if the question is still live |
| anything | **an agency, ever** | no policy admits a non-platform tenant; Task 2's tests pin this through a real `NOBYPASSRLS` role |

An operator is a `Membership` with `role=PLATFORM_ADMIN`, active, MFA-verified, on a request whose host resolves to the platform agency. Nobody else can decide, park, open, or see an item.

---

## Depends on, and what this plan offers others

**Depends on nothing unmerged.** Everything it reads is on `master` at `115c752`: `Organisation`, `OrganisationDomain`, `OrganisationIdentifier`, `RegisterEntry`, `HostProfile`, `FetchAttempt`, `FundingOpportunity`'s review columns, `review_funding`, `classify_organisation`, `record_organisation`, `fetch_page`, `retrieve_official_source`, `registrable_domain`, `validate_public_url`, `AuditEvent`, `Membership.Role.PLATFORM_ADMIN`, `require_staff_mfa`, and both RLS fixtures.

**Offers:**

| to | interface | Task |
|---|---|---|
| item 8 (resolver) | `writers.file_site_unknown(entry: RegisterEntry, *, names: Sequence[str], candidates: Sequence[tuple[str, str]]) -> ResolutionItem \| None`. Call it only for residue the six rules and Diffbot could not resolve. It returns None when the entry is already answered. | 11 |
| item 10 (hidden gems) | the kind registry: add `SITE_UNVOUCHED` as one `KindSpec` plus one `apply._site_unvouched`, and widen the kind CHECK in one migration | 3, 7 |
| item 11 (verification) | nothing yet. A verification that cannot decide is a new kind, added through the registry. | — |

---

## Global constraints

- **No row names a person.** No FK to `Membership`, `Pseudonym`, `auth.User` or any `TenantScopedModel`. No tenant id in any column or in `evidence`. `evidence` is validated by a per-kind Pydantic model with `extra="forbid"` whose fields hold hosts, URLs, page titles, quotes from official pages and model verdicts only. A test pins all of it (Task 2).
- **The runtime role never writes the shared catalog.** Every write-back is in `apply.py`, called only from `manage.py apply_resolutions`, which refuses to start under the runtime role (the same check `discover` makes through `CATALOG_ROLE_NOTE`).
- **RLS is verified against a `NOBYPASSRLS` role or it is not verified.** Use `runtime_connection` for policy shape and `rls_enforced_orm` for the view. The test role bypasses RLS, so a passing ORM test proves nothing about the policy (`CLAUDE.md`).
- **Never hard-code a migration number.**
  - Before writing a migration, run `ls apps/<app>/migrations | sort | tail -3` and `uv run python manage.py showmigrations <app> | tail -3`, and depend on the real leaf.
  - As of 2026-09-25 the leaves are `research/0009_site_job_record_rls` and `tenancy/0011_membership_quiet_hours`.
  - Expect parallel item branches (7, 8, 10, 11, 13) to add `research` migrations. When two leaves appear after a merge from master, run `uv run python manage.py makemigrations --merge research`. Do not renumber anyone's migration (`CLAUDE.md`, the 2026-09-15 renumber).
- **Every new table carries its RLS in the same change and appears in `tests/tenancy/test_database_isolation.py`:**
  - `ResolutionItem` in a new `_PLATFORM_TABLES`.
  - `MovedPage` (Task 7) in `_SHARED_TABLES`.
- **Never run `ruff format`.** This repo's gate is lint-only.
- **After every task:** `uv run ruff check apps config tests scripts`, `uv run mypy apps config`, `POSTGRES_DB=tehsil_resolution_queue uv run pytest`, and `uv run python manage.py makemigrations --check --dry-run` stay clean. `uv run bandit -c pyproject.toml -r apps config` also stays clean; Task 13 adds SQL.
- **Every number is a setting with an env override:** `RESOLUTION_DAILY_CAP_PER_OPERATOR` (20) and `RESOLUTION_EXPIRY_DAYS` (30).
- **Templates exist only under `tests/templates/`**, as `deletion_console` does. The production presentation layer is chosen at build time by the orchestrator (`CLAUDE.md` "Frontend and design"; §11 names Aykhan as its author). Markup assertions carry `@pytest.mark.frontend`.

---

## File structure

| file | status | responsibility |
|---|---|---|
| `apps/tenancy/models.py` | modify | `Agency.is_platform`, partial unique |
| `apps/tenancy/services.py` | modify | `platform_agency()` |
| `apps/tenancy/management/commands/set_platform_agency.py` | create | the one writer of `is_platform` |
| `apps/research/models.py` | modify | `ResolutionItem`; `MovedPage`; `HostProfile.retired_at`; `OrganisationIdentifier` scheme `HUMAN`; `Organisation.RejectedReason.NOT_AN_ORGANISATION`; `RegisterEntry.Resolution.REFUSED` + `refused_reason` |
| `apps/research/migrations/<leaf+1>_resolution_item.py` | create | schema |
| `apps/research/migrations/<leaf+2>_resolution_item_rls.py` | create | the platform-only policies |
| `apps/research/migrations/<leaf+3>_resolution_writebacks.py` | create | schema for Task 7's write-back targets |
| `apps/research/migrations/<leaf+4>_moved_page_rls.py` | create | `MovedPage` shared-catalog policies |
| `apps/research/resolution/__init__.py` | create | package docstring: the lifecycle table above, in brief |
| `apps/research/resolution/kinds.py` | create | `KindSpec`, the registry, evidence and resolution schemas, `render_ask` |
| `apps/research/resolution/writers.py` | create | `file_item`, `withdraw_item`, and the four `file_*` wrappers |
| `apps/research/resolution/operator.py` | create | `require_operator`, `listing`, `open_item`, `decide`, `park`, `decisions_today` |
| `apps/research/resolution/apply.py` | create | `apply_decided`, `expire_unopened`, the four write-backs |
| `apps/research/resolution/priority.py` | create | `QueueRow`, the sort, `corridor_share`, the `PackCounter` seam |
| `apps/research/views.py`, `apps/research/urls.py` | modify | `/platform/resolution/` list, detail, decide, park |
| `apps/research/management/commands/apply_resolutions.py` | create | the applier |
| `apps/research/management/commands/file_award_disputes.py` | create | one-off backfill of existing unserved rows |
| `apps/research/management/commands/funding_review.py` | modify | a CLI over the queue |
| `apps/research/funding_reader.py` | modify | the AWARD_DISPUTED writer and withdrawal |
| `apps/research/discovery.py` | modify | `SourceBlocked.outcome`; `MovedPage` and `retired_at` consulted |
| `apps/research/egress.py` | modify | `SourceBlocked` gains an optional `outcome` |
| `apps/research/pipeline.py` | modify | `_open_task` retired; HOST_UNREACHABLE filed; the rest go to `degraded` |
| `apps/research/classify.py` | modify | the KIND_OR_COUNTRY_UNSURE writer |
| `config/settings/base.py` | modify | the two settings |
| `scripts/create_queue_counter.sql` | create (Task 13 only) | the cross-tenant pack count |
| `tests/research/resolution/…` | create | one module per source module, plus `test_rls.py` |
| `tests/templates/research/resolution_*.html` | create | stubs |
| `tests/tenancy/test_database_isolation.py` | modify | `_PLATFORM_TABLES`; `research_movedpage` in `_SHARED_TABLES` |
| `tests/infra/test_template.py` | modify (Task 13 only) | the second BYPASSRLS role |
| `CLAUDE.md`, `docs/runbooks/deploy.md` | modify | the third RLS case; the platform-agency step; (Task 13) the counter role |

---

## Task 1: The platform agency

**Files:**
- Modify: `apps/tenancy/models.py`, `apps/tenancy/services.py`
- Create: `apps/tenancy/migrations/<leaf+1>_agency_is_platform.py`, `apps/tenancy/management/commands/set_platform_agency.py`
- Test: `tests/tenancy/test_platform_agency.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_platform_agency.py
"""At most one agency is the platform, and only an admin command says which.

Spec 2026-09-22 section 11: "the master agency sees everything". Until this
column there was nothing to key that on -- PLATFORM_ADMIN is a role any agency
can hold.
"""

import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError

from apps.tenancy.models import Agency
from apps.tenancy.services import platform_agency

pytestmark = pytest.mark.django_db


def test_no_platform_agency_is_an_error_not_a_default(agency_a) -> None:
    with pytest.raises(Agency.DoesNotExist):
        platform_agency()


def test_two_platform_agencies_are_refused_by_the_database(agency_a, agency_b) -> None:
    Agency.objects.filter(id=agency_a.id).update(is_platform=True)
    with pytest.raises(IntegrityError):
        Agency.objects.filter(id=agency_b.id).update(is_platform=True)


def test_the_command_sets_one_and_refuses_a_second(agency_a, agency_b) -> None:
    call_command("set_platform_agency", str(agency_a.id))
    assert platform_agency().id == agency_a.id
    with pytest.raises(CommandError, match="already the platform"):
        call_command("set_platform_agency", str(agency_b.id))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `POSTGRES_DB=tehsil_resolution_queue uv run pytest tests/tenancy/test_platform_agency.py -v`
Expected: FAIL. The import error is on `platform_agency`, or the `is_platform` field is unknown.

- [ ] **Step 3: Implement**

In `apps/tenancy/models.py`, add to `Agency`:

```python
    #: The one agency that is the platform itself (spec 2026-09-22 section 11).
    #: Its PLATFORM_ADMIN members are the only people who may see or answer the
    #: catalog's resolution queue, and research_resolutionitem's RLS policy reads
    #: this column. Set by `manage.py set_platform_agency`, never by a view.
    is_platform = models.BooleanField(default=False)
```

and, in `Agency.Meta.constraints`:

```python
            models.UniqueConstraint(
                fields=("is_platform",),
                condition=models.Q(is_platform=True),
                name="agency_one_platform",
            ),
```

In `apps/tenancy/services.py`:

```python
def platform_agency() -> Agency:
    """The platform's own agency. Raises Agency.DoesNotExist when none is set.

    Deliberately no fallback: a queue that silently resolved "the platform" to
    some agency would show every catalog question to that agency's staff.
    """
    return Agency.objects.get(is_platform=True)
```

(Import `Agency` from `.models`.) The command:

```python
# apps/tenancy/management/commands/set_platform_agency.py
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.tenancy.models import Agency


class Command(BaseCommand):
    help = "Mark the one agency that is the platform (resolution queue, spec 11)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("agency_id")

    def handle(self, *_args: object, **options: object) -> None:
        target = Agency.objects.filter(id=str(options["agency_id"])).first()
        if target is None:
            raise CommandError(f"no agency {options['agency_id']}")
        current = Agency.objects.filter(is_platform=True).exclude(id=target.id).first()
        if current is not None:
            raise CommandError(
                f"{current.id} is already the platform; unset it by hand first -- "
                "moving the platform moves who can read the resolution queue"
            )
        Agency.objects.filter(id=target.id).update(is_platform=True)
        self.stdout.write(f"{target.id} is the platform agency")
```

Run `uv run python manage.py makemigrations tenancy --name agency_is_platform`. Check it depends on the real leaf.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `POSTGRES_DB=tehsil_resolution_queue uv run pytest tests/tenancy/test_platform_agency.py -v`
Expected: 3 passed.

- [ ] **Step 5: Runbook line**

In `docs/runbooks/deploy.md`, under "Once per environment", after the erasure-guard step, add:

> 7. Mark the platform agency, once, after creating it:
>    `uv run python manage.py set_platform_agency <agency-uuid>`.
>    Until this runs, `/platform/resolution/` is a 403 for everyone and the queue is invisible. It fails closed, never open.

- [ ] **Step 6: Commit**

```bash
git add apps/tenancy tests/tenancy/test_platform_agency.py docs/runbooks/deploy.md
git commit -m "feat(tenancy): mark the one platform agency"
```

---

## Task 2: `ResolutionItem`, platform-only

**Files:**
- Modify: `apps/research/models.py`
- Create: `apps/research/migrations/<leaf+1>_resolution_item.py`, `apps/research/migrations/<leaf+2>_resolution_item_rls.py`
- Modify: `tests/tenancy/test_database_isolation.py`
- Test: `tests/research/resolution/__init__.py`, `tests/research/resolution/test_rls.py`, `tests/research/resolution/test_model.py`

- [ ] **Step 1: Write the model test (no person, no tenant)**

```python
# tests/research/resolution/test_model.py
"""Spec 11: "The item carries nothing about a person, and that is a rule."

A platform table sits outside tenant RLS and outside advance_deletion's sweep.
A person pointer here is the documents.EuropassRenderCache shape: a personal
datum nothing erases.
"""

import pytest
from django.apps import apps
from django.db import IntegrityError
from django.utils import timezone

from apps.research.models import ResolutionItem
from apps.tenancy.models import TenantScopedModel

pytestmark = pytest.mark.django_db

_PERSON_MODELS = {"tenancy.membership", "audit.pseudonym", "auth.user", "accounts.user"}


def _new(**fields):
    now = timezone.now()
    defaults = {"evidence": {}, "ask": "?", "options": [], "refreshed_at": now, "expires_at": now}
    return ResolutionItem.objects.create(**{**defaults, **fields})


def test_the_item_points_at_no_person_and_no_tenant() -> None:
    assert not issubclass(ResolutionItem, TenantScopedModel)
    for field in ResolutionItem._meta.get_fields():
        related = getattr(field, "related_model", None)
        if related is None:
            continue
        label = related._meta.label_lower
        assert label not in _PERSON_MODELS, field.name
        assert not issubclass(related, TenantScopedModel), field.name
    assert "tenant" not in {f.name for f in ResolutionItem._meta.get_fields()}


def test_no_other_model_points_at_the_item() -> None:
    """Rows are deleted when applied (plan: queue, not ledger); an inbound FK
    would either block that delete or cascade into something that remembers."""
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if getattr(field, "related_model", None) is ResolutionItem and field.concrete:
                pytest.fail(f"{model._meta.label}.{field.name} points at ResolutionItem")


def test_one_live_question_per_subject() -> None:
    _new(kind="HOST_UNREACHABLE", subject_key="host:a.test")
    with pytest.raises(IntegrityError):
        _new(kind="HOST_UNREACHABLE", subject_key="host:a.test")


def test_the_subject_prefix_matches_the_kind() -> None:
    with pytest.raises(IntegrityError):
        _new(kind="HOST_UNREACHABLE", subject_key="award:x")


def test_a_decided_item_carries_its_resolution() -> None:
    with pytest.raises(IntegrityError):
        _new(kind="HOST_UNREACHABLE", subject_key="host:b.test", state="DECIDED")
```

(Add `tests/research/resolution/__init__.py`, empty.)

- [ ] **Step 2: Write the policy test against a real `NOBYPASSRLS` role**

```python
# tests/research/resolution/test_rls.py
"""The third RLS case, verified where it can be verified.

The test role bypasses RLS (CLAUDE.md), so every assertion here runs on
`runtime_connection`, a real NOBYPASSRLS login. Every write-refusal test first
GRANTs the DML and asserts the grant, so a refusal is the POLICY's and not the
permission layer's: both raise 42501.
"""

import psycopg
import pytest
from django.db import connection
from django.utils import timezone
from psycopg import sql

from apps.research.models import ResolutionItem
from apps.tenancy.models import Agency

TABLE = "public.research_resolutionitem"


@pytest.fixture
def platform(db):
    return Agency.objects.create(name="Platform", is_platform=True)


@pytest.fixture
def item(db):
    now = timezone.now()
    return ResolutionItem.objects.create(
        kind="HOST_UNREACHABLE", subject_key="host:shut.test", evidence={}, ask="?",
        options=[], refreshed_at=now, expires_at=now,
    )


def _grant_dml(runtime_connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}").format(
                sql.Identifier("public", "research_resolutionitem"),
                sql.Identifier(runtime_connection.info.user),
            )
        )
    with runtime_connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_table_privilege(current_user, %s, 'INSERT'),"
            "       has_table_privilege(current_user, %s, 'DELETE')",
            [TABLE, TABLE],
        )
        assert cursor.fetchone() == (True, True)


def _as_tenant(cursor, tenant_id) -> None:
    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])


@pytest.mark.django_db(transaction=True)
def test_no_gucs_sees_nothing(runtime_connection, item) -> None:
    with runtime_connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert cursor.fetchone() == (0,)


@pytest.mark.django_db(transaction=True)
def test_an_agency_sees_nothing_and_changes_nothing(
    runtime_connection, item, platform, agency_a
) -> None:
    _grant_dml(runtime_connection)
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        _as_tenant(cursor, agency_a.id)
        cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert cursor.fetchone() == (0,)
        cursor.execute(f"UPDATE {TABLE} SET state = 'PARKED'")
        assert cursor.rowcount == 0


@pytest.mark.django_db(transaction=True)
def test_the_platform_reads_and_updates_but_never_inserts_or_deletes(
    runtime_connection, item, platform
) -> None:
    _grant_dml(runtime_connection)
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        _as_tenant(cursor, platform.id)
        cursor.execute(f"SELECT id FROM {TABLE}")
        assert cursor.fetchall() == [(item.id,)]
        cursor.execute(f"UPDATE {TABLE} SET state = 'PARKED' WHERE id = %s", [item.id])
        assert cursor.rowcount == 1
        cursor.execute(f"DELETE FROM {TABLE} WHERE id = %s", [item.id])
        assert cursor.rowcount == 0
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        _as_tenant(cursor, platform.id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                f"INSERT INTO {TABLE} (id, kind, subject_key, evidence, ask, options, state,"
                " created_at, refreshed_at, expires_at, apply_error)"
                " VALUES (gen_random_uuid(), 'HOST_UNREACHABLE', 'host:x.test', '{{}}', '?',"
                " '[]', 'OPEN', now(), now(), now(), '')"
            )


@pytest.mark.django_db(transaction=True)
def test_a_platform_update_cannot_move_a_row_out_of_the_platform(
    runtime_connection, item, platform, agency_a
) -> None:
    """WITH CHECK is the same predicate. It is trivially true for this table,
    since no row carries a tenant, but the policy must have one: an UPDATE policy
    without WITH CHECK falls back to USING, and the shape test pins both."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT qual, with_check FROM pg_policies WHERE tablename = 'research_resolutionitem'"
            " AND policyname = 'platform_operator_update'"
        )
        qual, with_check = cursor.fetchone()
    assert qual == with_check
```

- [ ] **Step 3: Extend the isolation suite**

In `tests/tenancy/test_database_isolation.py`, after `_TASK7_TABLES`, add:

```python
#: Platform-only (the third RLS case, research/<leaf+2>): outside tenant RLS,
#: readable and updatable only when app.tenant_id is the platform agency,
#: written by catalog_ingestion and the owner. Never in _SHARED_TABLES --
#: shared_catalog_select would show the queue to every agency, which is what
#: spec 2026-09-22 decision 26 forbids.
_PLATFORM_TABLES = ("research_resolutionitem",)

_PLATFORM_PREDICATE_FRAGMENT = "is_platform"


@pytest.mark.django_db
def test_platform_tables_have_exactly_the_platform_policies() -> None:
    with connection.cursor() as cursor:
        for table in _PLATFORM_TABLES:
            assert table not in _SHARED_TABLES
            cursor.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass",
                [f"public.{table}"],
            )
            assert cursor.fetchone() == (True, False)
            cursor.execute(
                "SELECT policyname, cmd, roles::text FROM pg_policies"
                " WHERE schemaname = 'public' AND tablename = %s ORDER BY policyname",
                [table],
            )
            assert cursor.fetchall() == [
                ("catalog_ingestion_write", "ALL", "{catalog_ingestion}"),
                ("platform_operator_select", "SELECT", "{public}"),
                ("platform_operator_update", "UPDATE", "{public}"),
            ]
            cursor.execute(
                "SELECT qual FROM pg_policies WHERE tablename = %s"
                " AND policyname LIKE 'platform_operator_%%'",
                [table],
            )
            for (qual,) in cursor.fetchall():
                assert _PLATFORM_PREDICATE_FRAGMENT in qual
                assert "app.tenant_id" in qual
```

- [ ] **Step 4: Run all three modules and watch them fail**

Run: `POSTGRES_DB=tehsil_resolution_queue uv run pytest tests/research/resolution tests/tenancy/test_database_isolation.py -v -k "resolution or platform"`
Expected: FAIL (`ResolutionItem` does not exist).

- [ ] **Step 5: Implement the model**

Append to `apps/research/models.py`:

```python
#: Every kind's subject is keyed by one prefix. The prefix IS the dedupe rule of
#: spec 11: a registrable domain or register row for organisations, the
#: canonical_key for awards, the full hostname for reachability. One question
#: per subject, whichever tenants' runs met it.
_RESOLUTION_PREFIXES = {
    "SITE_UNKNOWN": "register:",
    "AWARD_DISPUTED": "award:",
    "HOST_UNREACHABLE": "host:",
    "KIND_OR_COUNTRY_UNSURE": "organisation:",
}


class ResolutionItem(models.Model):
    """One live question about the shared catalog, for the platform only.

    Platform-only (the third RLS case -- see the migration beside this file and
    CLAUDE.md): no tenant, no person, invisible to every agency. A queue, not a
    ledger. A row exists only while its question is live and is DELETED when
    answered, expired or withdrawn. The answer lives in the catalog it was
    written back to, and who answered lives in AuditEvent under the platform
    agency. Nothing here points at an operator, because an operator is a
    Membership.

    Plan: docs/superpowers/plans/2026-09-25-human-resolution-queue.md.
    Spec: 2026-09-22-funding-search-engine-master-design.md section 11.
    """

    class Kind(models.TextChoices):
        SITE_UNKNOWN = "SITE_UNKNOWN"
        AWARD_DISPUTED = "AWARD_DISPUTED"
        HOST_UNREACHABLE = "HOST_UNREACHABLE"
        KIND_OR_COUNTRY_UNSURE = "KIND_OR_COUNTRY_UNSURE"

    class State(models.TextChoices):
        OPEN = "OPEN"
        #: An operator said "I don't know". Only a different operator may decide it.
        PARKED = "PARKED"
        #: Decided in the console; waiting for `apply_resolutions`.
        DECIDED = "DECIDED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    subject_key = models.CharField(max_length=300)
    #: Validated by the kind's evidence model (resolution/kinds.py, extra=forbid).
    evidence = models.JSONField()
    #: The one closed question, rendered once at filing so the console and the
    #: CLI show the same words.
    ask = models.CharField(max_length=300)
    options = models.JSONField(default=list)
    state = models.CharField(max_length=8, choices=State.choices, default=State.OPEN)
    #: Validated by the kind's resolution model. Set only with DECIDED.
    resolution = models.JSONField(null=True, blank=True)
    #: Why the applier sent a decision back (evidence changed, write-back refused).
    apply_error = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    refreshed_at = models.DateTimeField()
    opened_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    #: created_at + RESOLUTION_EXPIRY_DAYS. Honoured only while never opened.
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("kind", "subject_key"), name="resolution_one_per_subject"
            ),
            models.CheckConstraint(
                condition=Q(kind__in=list(_RESOLUTION_PREFIXES)), name="resolution_kind_valid"
            ),
            models.CheckConstraint(
                condition=functools.reduce(
                    operator.or_,
                    (
                        Q(kind=kind, subject_key__startswith=prefix)
                        for kind, prefix in _RESOLUTION_PREFIXES.items()
                    ),
                ),
                name="resolution_subject_prefix",
            ),
            models.CheckConstraint(
                condition=Q(state__in=("OPEN", "PARKED", "DECIDED")),
                name="resolution_state_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="DECIDED", resolution__isnull=False, decided_at__isnull=False)
                    | (~Q(state="DECIDED") & Q(resolution__isnull=True))
                ),
                name="resolution_decided_shape",
            ),
        ]
        indexes = [models.Index(fields=("state", "created_at"), name="resolution_state_idx")]
```

(Add `import functools` and `import operator` at the top of the module. Name the import `operator` does not collide with: `apps/research/resolution/operator.py` is a different module, imported by its package path. `refreshed_at` and `expires_at` have no defaults on purpose. `writers.file_item` (Task 4) is the one writer and sets both, and the tests above set them through `_new`.)

Run `uv run python manage.py makemigrations research --name resolution_item`.

- [ ] **Step 6: Implement the policies, in their own migration**

```python
# apps/research/migrations/<leaf+2>_resolution_item_rls.py
# The third RLS case: platform-only. Neither tenant-scoped (one row per agency
# would defeat cross-tenant dedupe, and put a tenant id in a row spec 11
# forbids) nor shared catalog (shared_catalog_select would list the queue for
# every agency, which decision 26 forbids). Readable and updatable only by a
# request whose app.tenant_id is the platform agency -- set by
# HostTenantContextMiddleware from the VERIFIED domain, so an agency-host request
# sees zero rows whatever the view does. No INSERT or DELETE for anyone but
# catalog_ingestion and the owner: an operator decides, the applier writes back
# and deletes. ENABLE without FORCE, like the shared catalog, because every
# writer runs as the owner today.
#
# This narrows a table holding no tenant data to one tenant. It is NOT the
# "widen tenant policies for a platform-admin GUC" that CLAUDE.md rules out: no
# GUC is added and no tenant table is touched. Verify against runtime_connection
# (tests/research/resolution/test_rls.py) -- the test role bypasses RLS.
from django.db import migrations

TABLE = "research_resolutionitem"

_PLATFORM = """
EXISTS (
    SELECT 1 FROM public.tenancy_agency AS agency
    WHERE agency.id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
      AND agency.is_platform
)
"""

RLS_SQL = f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY platform_operator_select ON public.{TABLE}
    FOR SELECT USING ({_PLATFORM});
CREATE POLICY platform_operator_update ON public.{TABLE}
    FOR UPDATE USING ({_PLATFORM}) WITH CHECK ({_PLATFORM});
CREATE POLICY catalog_ingestion_write ON public.{TABLE}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{TABLE};
DROP POLICY IF EXISTS platform_operator_update ON public.{TABLE};
DROP POLICY IF EXISTS platform_operator_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("research", "<leaf+1>_resolution_item"),
        # The predicate reads tenancy_agency.is_platform.
        ("tenancy", "<the migration Task 1 created>"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
```

Replace the two `<…>` dependency names with the real file names. Do not guess them.

- [ ] **Step 7: Run and watch it pass**

Run: `POSTGRES_DB=tehsil_resolution_queue uv run pytest tests/research/resolution tests/tenancy/test_database_isolation.py -v`
Expected: all pass. If `test_an_agency_sees_nothing…` passes but `test_the_platform_reads…` returns zero rows, the predicate is wrong. It is **not** a grant problem, because `_grant_dml` asserted the grant.

- [ ] **Step 8: Commit**

```bash
git add apps/research/models.py apps/research/migrations tests/research/resolution tests/tenancy/test_database_isolation.py
git commit -m "feat(research): ResolutionItem, the platform-only queue table"
```

---

## Task 3: The kind registry

**Files:**
- Create: `apps/research/resolution/__init__.py`, `apps/research/resolution/kinds.py`
- Test: `tests/research/resolution/test_kinds.py`

The registry is the **only** place a kind is declared. Everything else looks kinds up in it: the console, the CLI, the applier and the writers. That is how item 10 adds `SITE_UNVOUCHED` with one entry.

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/resolution/test_kinds.py
import pytest
from pydantic import ValidationError

from apps.research.models import _RESOLUTION_PREFIXES, ResolutionItem
from apps.research.resolution.kinds import KINDS, evidence_for, resolution_for


def test_the_registry_is_the_one_declaration_of_kinds() -> None:
    assert set(KINDS) == set(ResolutionItem.Kind.values) == set(_RESOLUTION_PREFIXES)
    for kind, spec in KINDS.items():
        assert spec.subject_prefix == _RESOLUTION_PREFIXES[kind]


def test_evidence_refuses_a_field_it_does_not_name() -> None:
    """extra=forbid is the person-free guarantee: a writer cannot slip a
    student id or a tenant into evidence without a schema change a test sees."""
    with pytest.raises(ValidationError):
        evidence_for("HOST_UNREACHABLE", {"host": "a.test", "url": "https://a.test/",
                                          "trail": [], "tenant_id": "x"})


def test_site_unknown_pick_must_be_one_of_the_candidates() -> None:
    evidence = evidence_for("SITE_UNKNOWN", {
        "register": "vgm_tr", "external_key": "1", "names": ["Vakfı"], "country_code": "TR",
        "candidates": [{"url": "https://vakfi.org.tr/", "title": "Vakfı"}],
    })
    with pytest.raises(ValidationError):
        resolution_for("SITE_UNKNOWN", {"option": "pick", "url": "https://elsewhere.test/"},
                       evidence=evidence)
    assert resolution_for("SITE_UNKNOWN", {"option": "pick", "url": "https://vakfi.org.tr/"},
                          evidence=evidence).option == "pick"


def test_award_accept_must_answer_every_disputed_field_from_its_choices() -> None:
    evidence = evidence_for("AWARD_DISPUTED", {
        "canonical_key": "read:k", "award_name": "A", "page_url": "https://u.test/f",
        "snapshot_sha256": "0" * 64, "quotes": ["q"],
        "disputed": [{"field": "money_form", "choices": ["GRANT", "FEE_WAIVER", "LOAN", "MIXED"]}],
    })
    with pytest.raises(ValidationError):
        resolution_for("AWARD_DISPUTED", {"option": "accept", "fields": {}}, evidence=evidence)
    with pytest.raises(ValidationError):
        resolution_for("AWARD_DISPUTED", {"option": "accept", "fields": {"money_form": "GIFT"}},
                       evidence=evidence)
    assert resolution_for(
        "AWARD_DISPUTED", {"option": "accept", "fields": {"money_form": "GRANT"}},
        evidence=evidence,
    ).fields == {"money_form": "GRANT"}


def test_host_paste_must_stay_on_the_hosts_registrable_domain() -> None:
    """A page that moved to another organisation's domain is SITE_UNKNOWN's
    question, not this one's -- and a pasted off-domain URL is exactly how a
    hostile page would get itself into the catalog."""
    evidence = evidence_for("HOST_UNREACHABLE", {"host": "www.uni.test",
                                                 "url": "https://www.uni.test/x", "trail": []})
    with pytest.raises(ValidationError):
        resolution_for("HOST_UNREACHABLE", {"option": "paste", "url": "https://other.test/x"},
                       evidence=evidence)
    assert resolution_for("HOST_UNREACHABLE",
                          {"option": "paste", "url": "https://apply.uni.test/x"},
                          evidence=evidence).url == "https://apply.uni.test/x"


def test_kind_or_country_requires_funds_students() -> None:
    evidence = evidence_for("KIND_OR_COUNTRY_UNSURE", {
        "primary_domain": "f.test", "homepage_title": "F", "guess_kind": "PRIVATE_FOUNDATION",
        "guess_country": "TR", "confidence": 0.4,
    })
    with pytest.raises(ValidationError):
        resolution_for("KIND_OR_COUNTRY_UNSURE",
                       {"option": "set", "kind": "PRIVATE_FOUNDATION", "country_code": "TR"},
                       evidence=evidence)


def test_every_kind_renders_a_closed_question_under_300_characters() -> None:
    for kind, spec in KINDS.items():
        assert spec.options, kind
        assert len(spec.render_ask(spec.example_evidence())) <= 300
```

- [ ] **Step 2: Run and watch it fail**

Run: `POSTGRES_DB=tehsil_resolution_queue uv run pytest tests/research/resolution/test_kinds.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `kinds.py`**

Each resolution model checks itself against the item's evidence. The evidence is passed as Pydantic **validation context**, so a bad click raises an ordinary `ValidationError` and there is one error type for the caller to catch. `validate_public_url` raises `UnsafeTarget`, which is a `ValueError`. Inside a validator, Pydantic turns that into a `ValidationError` too.

```python
# apps/research/resolution/kinds.py
"""The closed set of questions the platform asks a person, and nothing else.

Each kind is one closed question (spec 11: "ask (one closed question,
rendered), options"). Evidence and resolution are Pydantic models with
extra="forbid". The evidence model is what keeps a person out of a platform
table, and the resolution model is the trust boundary between an operator's
click and a write to the shared catalog.

Adding a kind (item 10's SITE_UNVOUCHED) is one KindSpec here, one write-back
in apply.py, and one migration widening ResolutionItem's two kind CHECKs.
test_kinds.py fails until all three agree.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from apps.research.egress import validate_public_url
from apps.research.hosts import registrable_domain
from apps.research.models import _RESOLUTION_PREFIXES, Organisation

_STRICT = ConfigDict(extra="forbid", frozen=True)


def _evidence(info: ValidationInfo) -> Any:
    context = info.context or {}
    if "evidence" not in context:
        raise ValueError("a resolution is only ever validated against its item's evidence")
    return context["evidence"]


# --- SITE_UNKNOWN -----------------------------------------------------------


class Candidate(BaseModel):
    model_config = _STRICT
    url: str = Field(max_length=2048)
    title: str = Field(max_length=300)


class SiteUnknownEvidence(BaseModel):
    model_config = _STRICT
    register: str = Field(max_length=40)
    external_key: str = Field(max_length=120)
    names: list[str] = Field(min_length=1, max_length=20)
    country_code: str = Field(max_length=2)
    candidates: list[Candidate] = Field(max_length=3)


class SiteUnknownResolution(BaseModel):
    model_config = _STRICT
    option: Literal["pick", "paste", "not_a_funder", "does_not_exist"]
    url: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def _against_evidence(self, info: ValidationInfo) -> SiteUnknownResolution:
        evidence: SiteUnknownEvidence = _evidence(info)
        if self.option == "pick" and self.url not in {c.url for c in evidence.candidates}:
            raise ValueError("pick must be one of the offered candidates")
        if self.option in {"pick", "paste"}:
            validate_public_url(self.url)
        elif self.url:
            raise ValueError(f"{self.option} takes no url")
        return self


# --- AWARD_DISPUTED ---------------------------------------------------------


class DisputedField(BaseModel):
    model_config = _STRICT
    field: str = Field(max_length=40)
    choices: list[str] = Field(min_length=2, max_length=12)


class AwardDisputedEvidence(BaseModel):
    model_config = _STRICT
    canonical_key: str = Field(max_length=255)
    award_name: str = Field(max_length=80)
    page_url: str = Field(max_length=2048)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quotes: list[str] = Field(min_length=1, max_length=12)
    disputed: list[DisputedField] = Field(max_length=8)


class AwardDisputedResolution(BaseModel):
    model_config = _STRICT
    option: Literal["accept", "not_an_award", "third_party"]
    fields: dict[str, str] = Field(default_factory=dict)
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _against_evidence(self, info: ValidationInfo) -> AwardDisputedResolution:
        evidence: AwardDisputedEvidence = _evidence(info)
        if self.option != "accept":
            if self.fields:
                raise ValueError(f"{self.option} decides the whole row and takes no fields")
            return self
        choices = {d.field: set(d.choices) for d in evidence.disputed}
        if set(self.fields) != set(choices):
            raise ValueError("accept must answer every disputed field, and only those")
        for name, value in self.fields.items():
            if value not in choices[name]:
                raise ValueError(f"{value!r} is not a choice for {name}")
        return self


# --- HOST_UNREACHABLE -------------------------------------------------------


class TrailStep(BaseModel):
    model_config = _STRICT
    vendor: str = Field(max_length=20)
    rung: int = Field(ge=0, le=9)
    outcome: str = Field(max_length=20)
    reason: str = Field(default="", max_length=300)
    at: str = Field(max_length=40)


class HostUnreachableEvidence(BaseModel):
    model_config = _STRICT
    host: str = Field(max_length=253)
    url: str = Field(max_length=2048)
    trail: list[TrailStep] = Field(max_length=10)
    screenshot_object_key: str = Field(default="", max_length=500)


class HostUnreachableResolution(BaseModel):
    model_config = _STRICT
    option: Literal["paste", "closed"]
    url: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def _against_evidence(self, info: ValidationInfo) -> HostUnreachableResolution:
        evidence: HostUnreachableEvidence = _evidence(info)
        if self.option == "closed":
            if self.url:
                raise ValueError("closed takes no url")
            return self
        validate_public_url(self.url)
        pasted = registrable_domain(urlsplit(self.url).hostname or "")
        if not pasted or pasted != registrable_domain(evidence.host):
            raise ValueError("a pasted page must be on the same organisation's domain")
        return self


# --- KIND_OR_COUNTRY_UNSURE -------------------------------------------------


class KindOrCountryEvidence(BaseModel):
    model_config = _STRICT
    primary_domain: str = Field(max_length=253)
    homepage_title: str = Field(default="", max_length=300)
    guess_kind: str = Field(max_length=24)
    guess_country: str = Field(default="", max_length=2)
    confidence: float = Field(ge=0.0, le=1.0)


class KindOrCountryResolution(BaseModel):
    model_config = _STRICT
    option: Literal["set", "not_an_organisation"]
    kind: str = Field(default="", max_length=24)
    country_code: str = Field(default="", max_length=2)
    funds_students: bool | None = None

    @model_validator(mode="after")
    def _shape(self, info: ValidationInfo) -> KindOrCountryResolution:
        _evidence(info)
        if self.option == "not_an_organisation":
            if self.kind or self.country_code or self.funds_students is not None:
                raise ValueError("not_an_organisation takes no other answer")
            return self
        if self.kind not in dict(Organisation.KIND_CHOICES):
            raise ValueError(f"{self.kind!r} is not an organisation kind")
        if self.country_code and not (len(self.country_code) == 2 and self.country_code.isupper()):
            raise ValueError("country_code is ISO 3166 alpha-2 or empty")
        if self.funds_students is None:
            # Plan "Corrections" 8: without it classified_at caches a non-answer.
            raise ValueError("say whether it funds students")
        return self


# --- the registry -----------------------------------------------------------


@dataclass(frozen=True)
class KindSpec:
    kind: str
    subject_prefix: str
    evidence: type[BaseModel]
    resolution: type[BaseModel]
    options: tuple[str, ...]
    render_ask: Callable[[Any], str]
    example_evidence: Callable[[], BaseModel]


def _award_ask(e: AwardDisputedEvidence) -> str:
    fields = ", ".join(d.field for d in e.disputed) or "its benefit"
    return f"Is {e.award_name[:80]} an award on this page, and if so what is {fields}?"


KINDS: dict[str, KindSpec] = {
    "SITE_UNKNOWN": KindSpec(
        kind="SITE_UNKNOWN",
        subject_prefix=_RESOLUTION_PREFIXES["SITE_UNKNOWN"],
        evidence=SiteUnknownEvidence,
        resolution=SiteUnknownResolution,
        options=("pick", "paste", "not_a_funder", "does_not_exist"),
        render_ask=lambda e: f"Which site is {e.names[0][:200]}'s own?",
        example_evidence=lambda: SiteUnknownEvidence(
            register="vgm_tr", external_key="1", names=["Örnek Vakfı"], country_code="TR",
            candidates=[],
        ),
    ),
    "AWARD_DISPUTED": KindSpec(
        kind="AWARD_DISPUTED",
        subject_prefix=_RESOLUTION_PREFIXES["AWARD_DISPUTED"],
        evidence=AwardDisputedEvidence,
        resolution=AwardDisputedResolution,
        options=("accept", "not_an_award", "third_party"),
        render_ask=_award_ask,
        example_evidence=lambda: AwardDisputedEvidence(
            canonical_key="read:x", award_name="Example Scholarship",
            page_url="https://uni.test/funding", snapshot_sha256="0" * 64, quotes=["q"],
            disputed=[DisputedField(field="money_form", choices=["GRANT", "LOAN"])],
        ),
    ),
    "HOST_UNREACHABLE": KindSpec(
        kind="HOST_UNREACHABLE",
        subject_prefix=_RESOLUTION_PREFIXES["HOST_UNREACHABLE"],
        evidence=HostUnreachableEvidence,
        resolution=HostUnreachableResolution,
        options=("paste", "closed"),
        render_ask=lambda e: f"We could not open {e.host[:200]}. Where is this page now?",
        example_evidence=lambda: HostUnreachableEvidence(
            host="www.uni.test", url="https://www.uni.test/x", trail=[]
        ),
    ),
    "KIND_OR_COUNTRY_UNSURE": KindSpec(
        kind="KIND_OR_COUNTRY_UNSURE",
        subject_prefix=_RESOLUTION_PREFIXES["KIND_OR_COUNTRY_UNSURE"],
        evidence=KindOrCountryEvidence,
        resolution=KindOrCountryResolution,
        options=("set", "not_an_organisation"),
        render_ask=lambda e: f"What is {e.primary_domain[:200]}, where is it, "
        "and does it fund students?",
        example_evidence=lambda: KindOrCountryEvidence(
            primary_domain="vakfi.org.tr", guess_kind="PRIVATE_FOUNDATION", confidence=0.5
        ),
    ),
}


def evidence_for(kind: str, data: dict[str, object]) -> BaseModel:
    return KINDS[kind].evidence.model_validate(data)


def resolution_for(kind: str, data: dict[str, object], *, evidence: BaseModel) -> BaseModel:
    """Raises pydantic.ValidationError on any answer the closed question does not admit."""
    return KINDS[kind].resolution.model_validate(data, context={"evidence": evidence})
```

`PRIVATE_FOUNDATION` is one of `apps/funding/models.py::_HOLDER_VALUES`, which `Organisation.KIND_CHOICES` is built from.

- [ ] **Step 4: Run and watch it pass**

Run: `POSTGRES_DB=tehsil_resolution_queue uv run pytest tests/research/resolution/test_kinds.py -v`
Expected: 7 passed. The URL checks resolve DNS through `validate_public_url`. If they are slow or offline in CI, monkeypatch `apps.research.resolution.kinds.validate_public_url` to a no-op in `tests/research/resolution/conftest.py`, and keep one test that uses the real function on `https://127.0.0.1/` to prove a private address is refused.

- [ ] **Step 5: Commit**

```bash
git add apps/research/resolution tests/research/resolution/test_kinds.py
git commit -m "feat(resolution): the closed registry of kinds and their schemas"
```

---

## Task 4: Filing and withdrawing

**Files:**
- Create: `apps/research/resolution/writers.py`
- Modify: `config/settings/base.py`
- Test: `tests/research/resolution/test_writers.py`

`file_item` is the only function that inserts a row. It dedupes by `(kind, subject_key)`. It refreshes evidence **only while `OPEN`**: a parked item keeps the evidence the parking operator saw, and a decided one keeps what the decision was made against. It refuses to file anything the catalog already answers.

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/resolution/test_writers.py
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.research.models import ResolutionItem
from apps.research.resolution.writers import file_item, withdraw_item

pytestmark = pytest.mark.django_db

_HOST = {"host": "shut.test", "url": "https://shut.test/p", "trail": []}


def test_filing_twice_is_one_item_with_the_latest_evidence() -> None:
    first = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST)
    again = file_item("HOST_UNREACHABLE", "host:shut.test", {**_HOST, "url": "https://shut.test/q"})
    assert first.id == again.id
    assert ResolutionItem.objects.get().evidence["url"] == "https://shut.test/q"


def test_a_parked_or_decided_item_keeps_the_evidence_it_was_judged_on() -> None:
    item = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST)
    ResolutionItem.objects.filter(id=item.id).update(state="PARKED")
    file_item("HOST_UNREACHABLE", "host:shut.test", {**_HOST, "url": "https://shut.test/z"})
    assert ResolutionItem.objects.get().evidence["url"] == "https://shut.test/p"


def test_the_expiry_is_counted_from_first_filing(settings) -> None:
    settings.RESOLUTION_EXPIRY_DAYS = 30
    now = timezone.now()
    item = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST, now=now)
    file_item("HOST_UNREACHABLE", "host:shut.test", _HOST, now=now + timedelta(days=5))
    assert ResolutionItem.objects.get(id=item.id).expires_at == now + timedelta(days=30)


def test_withdraw_removes_an_open_item_and_never_a_decided_one() -> None:
    item = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST)
    assert withdraw_item("HOST_UNREACHABLE", "host:shut.test") is True
    assert not ResolutionItem.objects.filter(id=item.id).exists()
    item = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST)
    ResolutionItem.objects.filter(id=item.id).update(
        state="DECIDED", resolution={"option": "closed"}, decided_at=timezone.now()
    )
    assert withdraw_item("HOST_UNREACHABLE", "host:shut.test") is False
    assert ResolutionItem.objects.filter(id=item.id).exists()


def test_bad_evidence_never_reaches_the_table() -> None:
    with pytest.raises(ValueError):
        file_item("HOST_UNREACHABLE", "host:shut.test", {**_HOST, "student": "x"})
    assert not ResolutionItem.objects.exists()
```

- [ ] **Step 2: Run and watch it fail**

Run: `POSTGRES_DB=tehsil_resolution_queue uv run pytest tests/research/resolution/test_writers.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add to `config/settings/base.py`, next to the other research settings:

```python
#: Spec 11: "a daily cap per operator (default 20)" and "expires_at (30 days unopened)".
RESOLUTION_DAILY_CAP_PER_OPERATOR = int(os.getenv("RESOLUTION_DAILY_CAP_PER_OPERATOR", "20"))
RESOLUTION_EXPIRY_DAYS = int(os.getenv("RESOLUTION_EXPIRY_DAYS", "30"))
```

(The same `int(os.getenv(...))` form as `FETCH_PDF_MAX_PAGES`, a few lines away.)

```python
# apps/research/resolution/writers.py
"""The only code that inserts a ResolutionItem, and the only code that withdraws one.

Called from catalog-side runs (discover, classify_organisations, the funding
reader, item 8's resolver), which run as the table owner or catalog_ingestion.
The runtime role has no INSERT policy on this table, so a console view that
called this would be refused by the database, not merely by convention.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from apps.research.models import ResolutionItem

from .kinds import KINDS


@transaction.atomic
def file_item(
    kind: str, subject_key: str, evidence: dict[str, object], *, now: datetime | None = None
) -> ResolutionItem:
    spec = KINDS[kind]
    if not subject_key.startswith(spec.subject_prefix):
        raise ValueError(f"{kind} subjects start with {spec.subject_prefix!r}")
    try:
        parsed = spec.evidence.model_validate(evidence)
    except ValidationError as error:
        raise ValueError(f"{kind} evidence refused: {error.error_count()} error(s)") from error
    at = now or timezone.now()
    item, created = ResolutionItem.objects.select_for_update().get_or_create(
        kind=kind,
        subject_key=subject_key,
        defaults={
            "evidence": parsed.model_dump(mode="json"),
            "ask": spec.render_ask(parsed)[:300],
            "options": list(spec.options),
            "refreshed_at": at,
            "expires_at": at + timedelta(days=settings.RESOLUTION_EXPIRY_DAYS),
        },
    )
    if not created and item.state == ResolutionItem.State.OPEN:
        item.evidence = parsed.model_dump(mode="json")
        item.ask = spec.render_ask(parsed)[:300]
        item.refreshed_at = at
        item.save(update_fields=["evidence", "ask", "refreshed_at"])
    return item


def withdraw_item(kind: str, subject_key: str) -> bool:
    """The machine answered it. Never touches a DECIDED item -- a person's
    answer is applied or refused by the applier, not silently dropped."""
    deleted, _ = ResolutionItem.objects.filter(
        kind=kind,
        subject_key=subject_key,
        state__in=(ResolutionItem.State.OPEN, ResolutionItem.State.PARKED),
    ).delete()
    return bool(deleted)
```

- [ ] **Step 4: Run and watch it pass**

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/research/resolution/writers.py config/settings/base.py tests/research/resolution/test_writers.py
git commit -m "feat(resolution): file and withdraw, deduped per subject across tenants"
```

---

## Task 5: The operator — listing, deciding, parking

**Files:**
- Create: `apps/research/resolution/operator.py`, `apps/research/resolution/priority.py`
- Test: `tests/research/resolution/test_operator.py`

- [ ] **Step 1: Write the failing tests**

Fixtures (put them in `tests/research/resolution/conftest.py`):
- `platform`: an `Agency(is_platform=True)` with a verified `TenantDomain` at `platform.example.test`.
- `operator_user` and `operator`: a `Membership(role=PLATFORM_ADMIN)` in `platform`, created inside `tenant_scope(platform.id)`.
- `second_operator`: the same, for a second user.

The tests:

```python
# tests/research/resolution/test_operator.py
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.funding.models import AuditEvent
from apps.research.models import ResolutionItem
from apps.research.resolution.operator import DecisionRefused, decide, listing, open_item, park
from apps.research.resolution.writers import file_item
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

_HOST = {"host": "shut.test", "url": "https://shut.test/p", "trail": []}


def _item(subject="host:shut.test"):
    return file_item("HOST_UNREACHABLE", subject, {**_HOST, "host": subject[5:]})


def test_deciding_records_the_resolution_and_the_operator_in_audit(platform, operator) -> None:
    item = _item()
    with tenant_scope(platform.id):
        decide(item.id, operator, {"option": "closed"}, now=timezone.now())
        event = AuditEvent.objects.get(object_id=item.id, event="resolution.decided")
    item.refresh_from_db()
    assert item.state == "DECIDED" and item.resolution == {"option": "closed", "url": ""}
    assert event.actor_id == operator.id


def test_a_parked_item_needs_a_second_operator(platform, operator, second_operator) -> None:
    item = _item()
    with tenant_scope(platform.id):
        park(item.id, operator)
        with pytest.raises(DecisionRefused, match="second operator"):
            decide(item.id, operator, {"option": "closed"}, now=timezone.now())
        assert item.id not in {row.item.id for row in listing(operator, now=timezone.now())}
        assert item.id in {row.item.id for row in listing(second_operator, now=timezone.now())}
        decide(item.id, second_operator, {"option": "closed"}, now=timezone.now())


def test_the_daily_cap_bounds_both_listing_and_deciding(settings, platform, operator) -> None:
    settings.RESOLUTION_DAILY_CAP_PER_OPERATOR = 2
    items = [_item(f"host:h{i}.test") for i in range(3)]
    with tenant_scope(platform.id):
        assert len(listing(operator, now=timezone.now())) == 2
        decide(items[0].id, operator, {"option": "closed"}, now=timezone.now())
        decide(items[1].id, operator, {"option": "closed"}, now=timezone.now())
        assert listing(operator, now=timezone.now()) == []
        with pytest.raises(DecisionRefused, match="daily cap"):
            decide(items[2].id, operator, {"option": "closed"}, now=timezone.now())


def test_a_click_outside_the_closed_question_is_refused(platform, operator) -> None:
    item = _item()
    with tenant_scope(platform.id), pytest.raises(DecisionRefused):
        decide(item.id, operator, {"option": "delete_everything"}, now=timezone.now())
    item.refresh_from_db()
    assert item.state == "OPEN"


def test_opening_stamps_once(platform, operator) -> None:
    item = _item()
    first = timezone.now()
    with tenant_scope(platform.id):
        open_item(item.id, operator, now=first)
        open_item(item.id, operator, now=first + timedelta(minutes=5))
    item.refresh_from_db()
    assert item.opened_at == first


def test_pack_counts_are_not_computed_until_task_13(platform, operator) -> None:
    """Pack counts are Task 13's. Until then the listing says so -- never 0."""
    _item()
    with tenant_scope(platform.id):
        rows = listing(operator, now=timezone.now())
    assert all(row.packs is None for row in rows)


@pytest.mark.django_db(transaction=True)
def test_the_listing_behind_a_real_nobypassrls_role(rls_enforced_orm, platform, operator,
                                                    agency_a) -> None:
    """The ORM path, not only the raw policy: under agency A's GUC the manager
    returns nothing; under the platform's it returns the item."""
    from apps.tenancy.db import tenant_transaction

    _item()
    with tenant_transaction(agency_a.id):
        assert ResolutionItem.objects.count() == 0
    with tenant_transaction(platform.id):
        assert ResolutionItem.objects.count() == 1
```

The last test writes `_item()` as the test superuser before the fixture swaps the connection. That fixture's role gets DML on all tables, but only SELECT and UPDATE are admitted by the policy. Write the item **before** requesting `rls_enforced_orm`: put it in a fixture ordered ahead of it, or create it with `django_db_blocker.unblock()` on a separate superuser cursor. Read `tests/audit/test_identity_rls.py` for how that module seeds rows under this fixture, and copy its shape.

- [ ] **Step 2: Run and watch it fail**

Expected: FAIL.

- [ ] **Step 3: Implement**

```python
# apps/research/resolution/priority.py
"""Read-time ordering (spec 11). No priority is ever stored in a row."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from apps.research.hosts import registrable_domain
from apps.research.models import Organisation, OrganisationDomain, ResolutionItem

#: Task 13 supplies the real one. None means "not computed", and the console
#: prints exactly that -- never a 0 nobody measured.
PackCounter = Callable[[ResolutionItem], int | None]


def no_pack_count(_item: ResolutionItem) -> int | None:
    return None


@dataclass(frozen=True)
class QueueRow:
    item: ResolutionItem
    packs: int | None
    registered: bool
    country_code: str


def organisation_for(item: ResolutionItem) -> Organisation | None:
    """The organisation this subject belongs to, if the register holds one."""
    prefix, _, key = item.subject_key.partition(":")
    if prefix in {"host", "organisation"}:
        domain = registrable_domain(key)
        match = OrganisationDomain.objects.select_related("organisation").filter(
            registrable_domain=domain
        ).first()
        return match.organisation if match else None
    if prefix == "award":
        from apps.funding.models import FundingOpportunity

        row = FundingOpportunity.objects.filter(canonical_key=key).select_related(
            "organisation"
        ).first()
        return row.organisation if row else None
    return None  # register: -- by definition no organisation yet


def rows(items: list[ResolutionItem], *, pack_count: PackCounter) -> list[QueueRow]:
    out = []
    for item in items:
        org = organisation_for(item)
        out.append(
            QueueRow(
                item=item,
                packs=pack_count(item),
                registered=bool(org and org.status == Organisation.Status.REGISTERED),
                country_code=(org.country_code if org else item.evidence.get("country_code", "")),
            )
        )
    # Spec 11: most live packs blocked first, whichever tenants'; then registered
    # hosts; then candidates; oldest first within a tier.
    out.sort(key=lambda r: (-(r.packs or 0), not r.registered, r.item.created_at))
    return out
```

```python
# apps/research/resolution/operator.py
"""What a platform operator may do, and nothing an agency may.

Runs inside a web request on the platform agency's host, so app.tenant_id is
the platform's and research_resolutionitem's policy admits SELECT and UPDATE.
The operator is recorded in AuditEvent (tenant-scoped, the platform agency),
never on the item -- see the plan's "Corrections" item 4.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from uuid import UUID

from django.conf import settings
from django.db import transaction
from pydantic import ValidationError

from apps.funding.models import AuditEvent
from apps.research.models import ResolutionItem
from apps.tenancy.models import Membership

from .kinds import KINDS, resolution_for
from .priority import PackCounter, QueueRow, no_pack_count, rows

_COUNTED = ("resolution.decided", "resolution.parked")


class DecisionRefused(ValueError):
    pass


def decisions_today(operator: Membership, *, now: datetime) -> int:
    # UTC midnight. django.utils.timezone.utc was removed in Django 5.0.
    start = datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)
    return AuditEvent.objects.filter(
        actor=operator, event__in=_COUNTED, created_at__gte=start
    ).count()


def _parked_by(item_id: UUID) -> set[UUID]:
    return set(
        AuditEvent.objects.filter(event="resolution.parked", object_id=item_id).values_list(
            "actor_id", flat=True
        )
    )


def listing(
    operator: Membership, *, now: datetime, pack_count: PackCounter = no_pack_count
) -> list[QueueRow]:
    remaining = settings.RESOLUTION_DAILY_CAP_PER_OPERATOR - decisions_today(operator, now=now)
    if remaining <= 0:
        return []
    mine = set(
        AuditEvent.objects.filter(event="resolution.parked", actor=operator).values_list(
            "object_id", flat=True
        )
    )
    live = list(
        ResolutionItem.objects.filter(
            state__in=(ResolutionItem.State.OPEN, ResolutionItem.State.PARKED)
        ).exclude(id__in=mine)
    )
    return rows(live, pack_count=pack_count)[:remaining]


def open_item(item_id: UUID, operator: Membership, *, now: datetime) -> ResolutionItem:
    item = ResolutionItem.objects.get(id=item_id)
    if item.opened_at is None:
        ResolutionItem.objects.filter(id=item_id, opened_at__isnull=True).update(opened_at=now)
        item.opened_at = now
    return item


@transaction.atomic
def decide(
    item_id: UUID, operator: Membership, data: dict[str, object], *, now: datetime
) -> ResolutionItem:
    item = ResolutionItem.objects.select_for_update().get(
        id=item_id, state__in=(ResolutionItem.State.OPEN, ResolutionItem.State.PARKED)
    )
    if operator.id in _parked_by(item.id):
        raise DecisionRefused("you parked this; it needs a second operator")
    if decisions_today(operator, now=now) >= settings.RESOLUTION_DAILY_CAP_PER_OPERATOR:
        raise DecisionRefused("daily cap reached")
    spec = KINDS[item.kind]
    try:
        resolution = resolution_for(
            item.kind, data, evidence=spec.evidence.model_validate(item.evidence)
        )
    except ValidationError as error:
        raise DecisionRefused(f"not an answer to this question: {error.error_count()} error(s)") from error
    item.state = ResolutionItem.State.DECIDED
    item.resolution = resolution.model_dump(mode="json")
    item.decided_at = now
    item.apply_error = ""
    item.save(update_fields=["state", "resolution", "decided_at", "apply_error"])
    AuditEvent.objects.create(actor=operator, event="resolution.decided", object_id=item.id)
    return item


@transaction.atomic
def park(item_id: UUID, operator: Membership) -> ResolutionItem:
    """ "I don't know" (spec 11): parks the item for a second operator."""
    item = ResolutionItem.objects.select_for_update().get(
        id=item_id, state__in=(ResolutionItem.State.OPEN, ResolutionItem.State.PARKED)
    )
    item.state = ResolutionItem.State.PARKED
    item.save(update_fields=["state"])
    AuditEvent.objects.create(actor=operator, event="resolution.parked", object_id=item.id)
    return item
```

`select_for_update()` under the runtime role needs the UPDATE policy's USING, which the platform predicate provides. Under an agency's GUC the `get` raises `DoesNotExist`, and the view turns that into a 404.

- [ ] **Step 4: Run and watch it pass**

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/research/resolution tests/research/resolution
git commit -m "feat(resolution): the operator's listing, decision, park and daily cap"
```

---

## Task 6: The console surface — `/platform/resolution/`

**Files:**
- Modify: `apps/research/views.py`, `apps/research/urls.py`
- Create: `tests/templates/research/resolution_queue.html`, `tests/templates/research/resolution_item.html`
- Test: `tests/research/resolution/test_views.py`

Four routes:

| route | method | does |
|---|---|---|
| `platform/resolution/` | GET | `listing()`; the coverage line (Task 12); the count of `DECIDED` items waiting for the applier |
| `platform/resolution/<uuid>/` | GET | `open_item()`; shows `ask`, `evidence`, `options` and `apply_error` |
| `platform/resolution/<uuid>/decide/` | POST | `decide()` from the form; a 400 on `DecisionRefused`; a redirect to the list on success |
| `platform/resolution/<uuid>/park/` | POST | `park()` |

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/resolution/test_views.py
"""Who may reach the queue. Every refusal is a 403 or a 404, never an empty 200."""

import pytest

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import verify_mfa_session

pytestmark = pytest.mark.django_db


def test_an_agency_owner_on_their_own_host_is_refused(client, agency_a, domain_a, django_user_model):
    user = django_user_model.objects.create_user(username="owner-a")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.OWNER)
    client.force_login(user)
    verify_mfa_session(client, user)
    assert client.get("/platform/resolution/", HTTP_HOST=domain_a.host).status_code == 403


def test_a_platform_admin_of_an_ordinary_agency_is_refused(client, agency_a, domain_a,
                                                            django_user_model):
    """PLATFORM_ADMIN is a role any agency can hold; the platform is one agency."""
    user = django_user_model.objects.create_user(username="padmin-a")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.PLATFORM_ADMIN)
    client.force_login(user)
    verify_mfa_session(client, user)
    assert client.get("/platform/resolution/", HTTP_HOST=domain_a.host).status_code == 403


def test_an_operator_without_mfa_is_refused(client, platform, platform_domain, operator_user,
                                            operator):
    client.force_login(operator_user)
    assert client.get("/platform/resolution/", HTTP_HOST=platform_domain.host).status_code == 403


def test_the_operator_sees_the_queue(client, platform, platform_domain, operator_user, operator):
    client.force_login(operator_user)
    verify_mfa_session(client, operator_user)
    assert client.get("/platform/resolution/", HTTP_HOST=platform_domain.host).status_code == 200


def test_a_refused_decision_is_a_400_and_changes_nothing(client, platform, platform_domain,
                                                         operator_user, operator):
    from apps.research.resolution.writers import file_item

    item = file_item("HOST_UNREACHABLE", "host:shut.test",
                     {"host": "shut.test", "url": "https://shut.test/p", "trail": []})
    client.force_login(operator_user)
    verify_mfa_session(client, operator_user)
    response = client.post(f"/platform/resolution/{item.id}/decide/", {"option": "nonsense"},
                           HTTP_HOST=platform_domain.host)
    assert response.status_code == 400
    item.refresh_from_db()
    assert item.state == "OPEN"
```

Add a `platform_domain` fixture to `tests/research/resolution/conftest.py`: a verified `TenantDomain` at `platform.example.test`.

- [ ] **Step 2: Run and watch it fail** (404s)

- [ ] **Step 3: Implement**

```python
# in apps/research/views.py
def _operator(request: HttpRequest) -> Membership:
    """The only way into the resolution queue.

    Three checks, and each closes a different door:
    - the host must be the platform agency's: an agency's owner is an OWNER on
      /owner/, and PLATFORM_ADMIN is a role any agency can hold;
    - the membership must be PLATFORM_ADMIN;
    - MFA is checked HERE, explicitly. TenantMembershipMiddleware checks it
      against the user's FIRST active membership, which for a user who also holds
      a STUDENT membership is not this one.
    """
    if not request.tenant.is_platform:  # type: ignore[attr-defined]
        raise PermissionDenied("the resolution queue is the platform's")
    operator = current_membership(request, Membership.Role.PLATFORM_ADMIN)
    require_staff_mfa(request.user, Membership.Role.PLATFORM_ADMIN)
    return operator
```

The four views use `_operator(request)` first. `decide_view` builds `data` from `request.POST`:
- `option` and `url` are read directly.
- For `AWARD_DISPUTED`, every `field:<name>` key becomes `fields[name]`, plus `note`.
- For `KIND_OR_COUNTRY_UNSURE`, it reads `kind` and `country_code`, and `funds_students` as `"yes"` / `"no"` → bool.

It catches `DecisionRefused` → `HttpResponseBadRequest`, and `ResolutionItem.DoesNotExist` → `Http404`. Decorate with `@login_required`, plus `@require_POST` on the two POSTs.

Routes go in `apps/research/urls.py` with names `resolution-queue`, `resolution-item`, `resolution-decide` and `resolution-park`.

The stub templates in `tests/templates/research/` print only `ask`, the options and each row's `packs` (or the words "not computed"). Follow `tests/templates/README.md`: stubs are not enriched to make tests pass.

- [ ] **Step 4: Run and watch it pass**

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/research/views.py apps/research/urls.py tests/templates/research tests/research/resolution
git commit -m "feat(resolution): /platform/resolution/, for platform operators only"
```

---

## Task 7: Write-backs and the applier

**Files:**
- Modify: `apps/research/models.py` (write-back targets)
- Create: `apps/research/migrations/<leaf>_resolution_writebacks.py`, `apps/research/migrations/<leaf>_moved_page_rls.py`
- Create: `apps/research/resolution/apply.py`, `apps/research/management/commands/apply_resolutions.py`
- Modify: `tests/tenancy/test_database_isolation.py` (`research_movedpage` in `_SHARED_TABLES`)
- Test: `tests/research/resolution/test_apply.py`

**The write-back targets.** Each one is a place the answer lands, so the writer's "already answered" check finds it and the question is never asked again:

| kind / option | writes | "already answered" check (Tasks 8–11) |
|---|---|---|
| `SITE_UNKNOWN` pick / paste | `record_organisation(domain=<url host>, name=entry.name, names=evidence.names, kind="UNSTATED", country_code=evidence.country_code, status=REGISTERED, found_via=f"HUMAN:{item.id}", identifiers=(("HUMAN", f"{register}:{key}"),))`. If the organisation already existed as `CANDIDATE`, it is upgraded to `REGISTERED` (a register row vouches for it). `official_website = url` when blank. `entry.organisation = org`; `entry.resolution = RESOLVED`. | `RegisterEntry.resolution != UNRESOLVED` |
| `SITE_UNKNOWN` not_a_funder / does_not_exist | `entry.resolution = REFUSED`; `entry.refused_reason = NOT_A_FUNDER / DOES_NOT_EXIST` | same |
| `AWARD_DISPUTED` accept | the chosen `fields` set on the row, then `review_funding(row, accepted=True, note=…)`, which binds `reviewed_sha256` | `row.review != ""` and `row.reviewed_sha256 ==` the latest snapshot's; this is the existing rule in `write_funding_decision` |
| `AWARD_DISPUTED` not_an_award / third_party | `review_funding(row, accepted=False, note="not an award" / "third party's money")` | same |
| `HOST_UNREACHABLE` paste | `fetch_page(url, require_origin=url)`; on `SERVED`: `MovedPage(from_url=canonicalize_url(evidence.url), to_url=canonicalize_url(page.final_url))`, and every `OfficialSource` whose `canonical_url` is `evidence.url` repointed (the "catalog fix, a human decision, recorded" `CLAUDE.md` names). Not served → back to `OPEN` with `apply_error="the ladder still cannot open <url>: <outcome>"`. | a `MovedPage` for the URL, or `HostProfile(host).retired_at` |
| `HOST_UNREACHABLE` closed | `HostProfile(host).retired_at = now` (get_or_create). If `host` is an organisation's `primary_domain` or `www.` + it, also `status=REJECTED, rejected_reason=UNREACHABLE`. | same |
| `KIND_OR_COUNTRY_UNSURE` set | `Organisation.kind`, `country_code`, `funds_students`, `classified_at=now`, `classified_by="HUMAN"`, `classifier_confidence=1.0`. A `REGISTERED` row keeps its register-vouched kind and country (the classifier's own rule), so only `funds_students` is written to it. | `classified_at is not None` |
| `KIND_OR_COUNTRY_UNSURE` not_an_organisation | `status=REJECTED`, `rejected_reason=NOT_AN_ORGANISATION` | `status == REJECTED` |

**The model changes this needs**, all in one schema migration, `<leaf>_resolution_writebacks`:
- `"HUMAN"` appended to `_IDENTIFIER_SCHEMES` (the CHECK constraint is regenerated).
- `Organisation.RejectedReason.NOT_AN_ORGANISATION`.
- `RegisterEntry.Resolution.REFUSED` and `RegisterEntry.refused_reason` (`CharField(16, blank=True, default="")`, with a CHECK: `refused_reason` is non-blank iff `resolution == "REFUSED"`).
- `HostProfile.retired_at` (`DateTimeField(null=True, blank=True)`).
- The new model `MovedPage(id, from_url URLField(2048) unique, to_url URLField(2048), created_at)`. It is shared catalog: which page replaced which is the same fact for every tenant, and not a person.

`MovedPage`'s RLS goes in `<leaf>_moved_page_rls`, copied from `0009_site_job_record_rls.py` with the table name changed. `research_movedpage` joins `_SHARED_TABLES`, whose shape test then covers it.

**Check before writing `record_vgm`'s side:** `apps/research/vgm.py::record_vgm` re-reads the register every run. Read it. If it writes `resolution` on an existing row, make it leave `REFUSED` and a `RESOLVED` whose organisation carries a `HUMAN` identifier untouched, and add a test. Otherwise the next register read undoes the operator's answer and re-files the question. That would fail the gate's third criterion.

- [ ] **Step 1: Write the failing tests** (one per row of the table, plus these three)

```python
# tests/research/resolution/test_apply.py (the cross-cutting three; one test per
# table row above follows the same shape)
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.funding.models import AuditEvent
from apps.research.models import ResolutionItem
from apps.research.resolution.apply import apply_decided, expire_unopened
from apps.research.resolution.writers import file_item
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _decided(kind, subject, evidence, resolution):
    item = file_item(kind, subject, evidence)
    ResolutionItem.objects.filter(id=item.id).update(
        state="DECIDED", resolution=resolution, decided_at=timezone.now()
    )
    return item


def test_an_applied_item_is_gone_and_the_audit_remains(platform) -> None:
    item = _decided("HOST_UNREACHABLE", "host:shut.test",
                    {"host": "shut.test", "url": "https://shut.test/p", "trail": []},
                    {"option": "closed", "url": ""})
    report = apply_decided(now=timezone.now())
    assert report.applied == 1
    assert not ResolutionItem.objects.filter(id=item.id).exists()
    with tenant_scope(platform.id):
        assert AuditEvent.objects.filter(object_id=item.id, event="resolution.applied").exists()


def test_a_stale_award_decision_goes_back_to_the_operator(platform, disputed_award) -> None:
    """The page changed between the click and the write: the operator judged
    quotes that are no longer the page's, so the decision is not applied."""
    item = _decided("AWARD_DISPUTED", f"award:{disputed_award.canonical_key}",
                    disputed_award.evidence_with_sha("f" * 64),
                    {"option": "not_an_award", "fields": {}, "note": ""})
    report = apply_decided(now=timezone.now())
    item.refresh_from_db()
    assert report.reopened == 1
    assert item.state == "OPEN" and item.resolution is None
    assert "changed" in item.apply_error


def test_only_never_opened_items_expire(platform, settings) -> None:
    now = timezone.now()
    stale = file_item("HOST_UNREACHABLE", "host:a.test",
                      {"host": "a.test", "url": "https://a.test/", "trail": []},
                      now=now - timedelta(days=31))
    opened = file_item("HOST_UNREACHABLE", "host:b.test",
                       {"host": "b.test", "url": "https://b.test/", "trail": []},
                       now=now - timedelta(days=31))
    ResolutionItem.objects.filter(id=opened.id).update(opened_at=now - timedelta(days=2))
    assert expire_unopened(now=now) == 1
    assert not ResolutionItem.objects.filter(id=stale.id).exists()
    assert ResolutionItem.objects.filter(id=opened.id).exists()
```

The `disputed_award` fixture builds a `FundingOpportunity` with `agreement="UNAGREED"`, one `OfficialEvidenceClaim` and a snapshot whose `sha256` is `"0" * 64`. `evidence_with_sha(sha)` returns the AWARD_DISPUTED evidence dict with that sha. Model it on the fixtures in `tests/research/test_funding_review.py`.

- [ ] **Step 2: Run and watch it fail**

- [ ] **Step 3: Implement `apply.py`**

The skeleton:

```python
# apps/research/resolution/apply.py
"""Write each decided answer back to the catalog, then delete the item.

Runs ONLY from manage.py apply_resolutions, as the owner or catalog_ingestion:
the runtime role has no write policy on any shared table, so doing this in the
console's request would be legal SQL matching zero rows (CLAUDE.md failure
mode 1). One transaction per item: one refused write-back never rolls back
another's.
"""

@dataclass
class ApplyReport:
    applied: int = 0
    reopened: int = 0
    lines: list[str] = field(default_factory=list)


class Refused(Exception):
    """The write-back cannot be made as decided; the item goes back to OPEN."""


_WRITEBACKS: dict[str, Callable[[ResolutionItem, BaseModel, BaseModel, datetime], None]] = {
    "SITE_UNKNOWN": _site_unknown,
    "AWARD_DISPUTED": _award_disputed,
    "HOST_UNREACHABLE": _host_unreachable,
    "KIND_OR_COUNTRY_UNSURE": _kind_or_country,
}


def apply_decided(*, now: datetime) -> ApplyReport:
    report = ApplyReport()
    platform = platform_agency()
    for item_id in ResolutionItem.objects.filter(state="DECIDED").values_list("id", flat=True):
        with transaction.atomic():
            set_local_tenant(platform.id)  # AuditEvent is FORCE RLS, and so is the owner
            item = ResolutionItem.objects.select_for_update().get(id=item_id)
            spec = KINDS[item.kind]
            evidence = spec.evidence.model_validate(item.evidence)
            resolution = spec.resolution.model_validate(item.resolution)
            try:
                _WRITEBACKS[item.kind](item, evidence, resolution, now)
            except Refused as why:
                item.state, item.resolution, item.decided_at = "OPEN", None, None
                item.apply_error = str(why)[:200]
                item.save(update_fields=["state", "resolution", "decided_at", "apply_error"])
                report.reopened += 1
                continue
            seconds = (
                (item.decided_at - item.opened_at).total_seconds() if item.opened_at else None
            )
            report.lines.append(f"{item.kind} {item.subject_key} {seconds}")
            with tenant_scope(platform.id):
                AuditEvent.objects.create(event="resolution.applied", object_id=item.id)
            item.delete()
            report.applied += 1
    return report


def expire_unopened(*, now: datetime) -> int:
    deleted, _ = ResolutionItem.objects.filter(
        state="OPEN", opened_at__isnull=True, expires_at__lte=now
    ).delete()
    return deleted
```

Write the four `_WRITEBACKS` functions exactly as the table says. Each raises `Refused` with a one-line reason for:
- `SITE_UNKNOWN`: the entry is no longer `UNRESOLVED`, or the chosen domain belongs to a `REJECTED` organisation.
- `AWARD_DISPUTED`: the latest snapshot's `sha256` is not `evidence.snapshot_sha256` ("the page changed since this was decided"), or `review_funding` raised `ValueError` (its suspension guard). That error's message is the `apply_error`.
- `HOST_UNREACHABLE` paste: the fetch outcome is not in `SERVED`.

`AuditEvent(actor=None)` is `SYSTEM` by `AuditEvent.save`'s own derivation.

`manage.py apply_resolutions`:
1. Refuses to start unless the connection can write the catalog. `CATALOG_ROLE_NOTE` (`apps/research/fetch/__init__.py`) is help text only, not a check, so the command makes the check itself, as its first query:

   ```sql
   SELECT pg_has_role(current_user, 'catalog_ingestion', 'USAGE')
       OR current_user = (SELECT tableowner FROM pg_tables
                          WHERE schemaname = 'public' AND tablename = 'research_organisation')
   ```

   It raises `CommandError(... + CATALOG_ROLE_NOTE)` when the answer is false. Test it through `runtime_connection`'s role: the runtime role gets the error, not a run that writes nothing.
2. Calls `expire_unopened`, then `apply_decided`.
3. Prints `applied=N reopened=N expired=N`, then every `report.lines` entry. The gate reads those lines.

- [ ] **Step 4: Run and watch it pass**

Also run `tests/tenancy/test_database_isolation.py`. `research_movedpage` must pass the shared-catalog shape test.

- [ ] **Step 5: Commit**

```bash
git add apps/research tests/research/resolution tests/tenancy/test_database_isolation.py
git commit -m "feat(resolution): write-backs, the applier, and 30-day expiry"
```

---

## Task 8: `AWARD_DISPUTED` — the reader files, `funding_review` becomes a view of the queue

**Files:**
- Modify: `apps/research/funding_reader.py`, `apps/research/management/commands/funding_review.py`
- Create: `apps/research/management/commands/file_award_disputes.py`, and `file_award_dispute` / `award_evidence` in `apps/research/resolution/writers.py`
- Test: `tests/research/resolution/test_award_writer.py`; modify `tests/research/test_funding_review.py`

**What files, and what does not:**

| row after a write | files? | why |
|---|---|---|
| `agreement="UNAGREED"`, not reviewed | **yes** | the readings disagreed on an existence field; §11's "only the disputed fields, each as a choice" |
| `agreement="AGREED"`, `served=False`, no suspension, not reviewed | **yes**, with `disputed=[]` | agreed but names no benefit or form of money (`_why`'s second case). The only choices are the whole-row ones: accept, not an award, third party. |
| `agreement="ABSTAINED"` | **no** | a reading failed. That is the reader's retry to make (`derive._with_one_retry`'s pattern), not a person's question. It is counted by `funding_yield`. |
| `agreement="WITHDRAWN"` or a `suspension_quote` | **no** | the page's own words decided it, and `review_funding` refuses to serve one anyway |
| `served=True` or reviewed on this sha | **withdraws** any open item | the machine or a person already answered |

**Which disputed fields become choices:** a field in `row.disputed` becomes a `DisputedField` only when it has a closed vocabulary. The vocabularies live in `apps/research/funding_judge.py` as `Literal` aliases, not on the model (`FundingOpportunity.money_form` is a bare `CharField`):

| field | vocabulary |
|---|---|
| `money_form` | `_Money` |
| `route` | `_Route` |
| `nationality_shape` | `_Nationality` |
| `internationals_included` | `_Stated` |
| `kind` | `_Kind` |

Read each with `typing.get_args(funding_judge._Money)` and so on, dropping `UNSTATED`, which is not an answer. Do not hand-copy the lists. A test asserts every `DisputedField.choices` equals `get_args` of its alias minus `UNSTATED`, so the two cannot drift. A disputed existence field (`offered`, `holder`, `scope`) contributes no field choice: "not an award" and "third party's money" are exactly the answers to those.

- [ ] **Step 1: Write the failing tests**
  - Writing an UNAGREED decision through `write_funding_decision` files exactly one `AWARD_DISPUTED` item. Its `subject_key` is `award:<canonical_key>`, its `evidence.snapshot_sha256` is the snapshot's, and its evidence names only the disputed fields that have vocabularies.
  - Writing the same decision again from a second run (a second tenant's `discover`) leaves one item. This is the cross-tenant dedupe.
  - A later AGREED + served write withdraws it.
  - An ABSTAINED write files nothing, and so does a suspension.
  - `write_holder_decision` behaves the same.
  - `funding_review list` prints the queue's AWARD_DISPUTED items.
  - `funding_review accept <item-id> --operator <email> --field money_form=GRANT` records a decision through `operator.decide`. It then leaves the row unserved until `apply_resolutions` runs. Assert both halves.

- [ ] **Step 2: Implement**
  - Add `file_award_dispute(row, snapshot)` to `writers.py`. It calls `file_item("AWARD_DISPUTED", f"award:{row.canonical_key}", award_evidence(row, snapshot))`.
  - At the end of both `write_*_decision` functions, after `_write_rows`, apply the table above. Either call `file_award_dispute(opportunity, snapshot)` or `withdraw_item("AWARD_DISPUTED", f"award:{opportunity.canonical_key}")`.
  - Both run inside the existing `@transaction.atomic`, under the role the run already has.

  **`funding_review`:**
  - `list` reads `ResolutionItem(kind="AWARD_DISPUTED", state__in=OPEN/PARKED)` and prints `ask`, the quotes, the page and `_why`'s sentence, keyed by **item** id.
  - `accept` / `reject` take `--operator <email>`, which is resolved to an active `PLATFORM_ADMIN` membership in `platform_agency()`. They call `decide()` inside `tenant_transaction(platform.id)`.
  - The terminal and the console then share one decision path, one cap and one audit trail. The docstring changes to say that.
  - Keep `review_funding` exactly as it is. It is now the applier's write-back.

  `manage.py file_award_disputes` is a one-off backfill. It walks existing rows matching the "files" rows of the table above and calls `file_award_dispute` for each, reading the latest claim's snapshot. It prints `filed=N skipped=N`.

- [ ] **Step 3: Update `tests/research/test_funding_review.py`** to the new CLI shape. Do not delete its suspension test: the guard now fires in the applier, and the test asserts the item comes back `OPEN` with the suspension quote as `apply_error`.

- [ ] **Step 4: Run, and commit**

```bash
git commit -m "feat(resolution): the reader files AWARD_DISPUTED; funding_review reads the queue"
```

---

## Task 9: `HOST_UNREACHABLE` — the pipeline files, and the rest of `_open_task` retires

**Files:**
- Modify: `apps/research/egress.py` (`SourceBlocked.outcome`), `apps/research/discovery.py`, `apps/research/pipeline.py`
- Create: `file_host_unreachable` in `writers.py`
- Test: `tests/research/resolution/test_host_writer.py`; modify `tests/research/test_discovery_pipeline.py`, `tests/research/test_egress_coordination.py` and any other test asserting a pipeline-filed `ConsultantResearchTask` (grep `ConsultantResearchTask` under `tests/research/`)

- [ ] **Step 1: Give `SourceBlocked` the outcome it was raised for.** Callers must stop parsing `f"{page.outcome}: …"` back out of a message:

```python
class SourceBlocked(RuntimeError):
    def __init__(self, message: str, *, outcome: str | None = None) -> None:
        super().__init__(message)
        #: The fetch Outcome, when a ladder produced one. None from the
        #: first-party transport, which has no ladder.
        self.outcome = outcome
```

`retrieve_official_source` raises `SourceBlocked(message, outcome=str(page.outcome))`.

- [ ] **Step 2: Consult the answers before fetching.** At the top of `retrieve_official_source`:
  1. If a `MovedPage` exists for `canonicalize_url(url)`, fetch its `to_url` instead.
  2. If `HostProfile(host).retired_at` is set, raise `SourceBlocked("retired by an operator", outcome="DEAD")` **without a vendor call**.

  Test both. The second is also the saving: a human-declared dead host costs nothing on every later run.

- [ ] **Step 3: Replace `_open_task`.** Delete `_open_task`. At each of its seven call sites:

  - **`SourceBlocked` with `outcome in {"BLOCKED", "UNREACHABLE"}`, and the empty-shell case** → `file_host_unreachable(url, reason, trail)`:
    - `host = urlsplit(url).hostname.lower()`.
    - `trail` is the last ten `FetchAttempt` rows for the URL, as `TrailStep`s. `FetchAttempt` is shared catalog and readable.
    - It **first** checks the table's "already answered" column (`MovedPage`, `retired_at`) and files nothing if it is set.
  - **Everything else** (`DEAD`, `OFF_SITE`, `INVALID`, `RETRY_SCHEDULED`, `DomainBusy`, `ValueError`, extraction failure, no evidence, aggregator without a link) → `degraded.append(f"{url}: {reason}"[:300])` and `blocked += 1`. Nothing else changes: `DiscoveryReport` already carries `degraded` and `blocked`.
  - On a **successful** fetch of a host with an open `HOST_UNREACHABLE` item → `withdraw_item("HOST_UNREACHABLE", f"host:{host}")`. The host answered on its own.

  `record_blocked_source` keeps its tenant-side callers in `services.py`. Update its docstring: it is the **tenant** queue now, and catalog questions go to `apps/research/resolution/`.

- [ ] **Step 4: Update the pipeline tests.** Every assertion that a blocked lead produced a `ConsultantResearchTask` becomes one of two assertions:
  - for `BLOCKED` / `UNREACHABLE` / shell: exactly one `ResolutionItem(kind="HOST_UNREACHABLE")` for the host, and **zero** `ConsultantResearchTask` rows;
  - otherwise: the reason is in `report.degraded` and no row of either kind exists.

  Add one test: two runs under two different `--tenant`s meeting the same blocked host produce **one** item. This is the dedupe §11 is for.

- [ ] **Step 5: Run the whole research suite, and commit**

Run: `POSTGRES_DB=tehsil_resolution_queue uv run pytest tests/research -q`

```bash
git commit -m "feat(resolution): blocked hosts file HOST_UNREACHABLE; catalog-side consultant tasks retire"
```

---

## Task 10: `KIND_OR_COUNTRY_UNSURE` — the classifier files its residue

**Files:**
- Modify: `apps/research/classify.py`
- Create: `file_kind_unsure` in `writers.py`
- Test: `tests/research/resolution/test_classify_writer.py`

- [ ] **Step 1: Tests**
  - A `verdict` returned below `ORG_CLASSIFY_MIN_P`, or with `funds_students=None`, files one item.
  - A `verdict is None` (the classifier refused or failed) files nothing. That is a retry, not a question.
  - `contradicts_register` files nothing, and stays askable exactly as today. It is a disagreement between a register and a model about `funds_students`, which is not this kind's question. It is listed in "Out of scope".
  - A later `classified` outcome withdraws the item.
  - The evidence's `homepage_title` is the fetched page's `<title>` text, capped at 300. Take it from `fetched.body` with `lxml.html.fromstring(...).findtext(".//title")`.

- [ ] **Step 2: Implement.** In `classify_organisation`, at the `word == "abstained"` branch *with* a verdict, call `file_kind_unsure(org, title, verdict)`. At the `classified` return, call `withdraw_item("KIND_OR_COUNTRY_UNSURE", f"organisation:{org.primary_domain}")`.

  Today the frontier model is the last rung. When Jev lands in front of it (§6.6), only the **frontier's** abstention files. That will be one `by == "FRONTIER"` guard, written now so the ladder's order cannot drift.

- [ ] **Step 3: Run, commit**

```bash
git commit -m "feat(resolution): classifier abstentions file KIND_OR_COUNTRY_UNSURE"
```

---

## Task 11: `SITE_UNKNOWN` — the interface item 8 calls

**Files:**
- Create: `file_site_unknown` in `writers.py`
- Test: `tests/research/resolution/test_site_writer.py`

**No production caller lands here, on purpose.** The robustness ladder of §11 puts "resolution with every name variant and the six general rules → Diffbot Enhance on the residue" **before** anything is queued. Filing every `UNRESOLVED` `RegisterEntry` today would put **2,611** Turkish rows in front of a person (4,028 listed − 1,417 bound, §16 item 6a). That is the opposite of "under one host in ten reaching a person", and it would spend the daily cap on questions item 8's resolver answers for fractions of a cent.

- [ ] **Step 1: Tests**
  - `file_site_unknown(entry, names=[…], candidates=[(url, title), …])`:
    - files one item keyed `register:<register>:<external_key>`;
    - keeps at most three candidates, in the order given;
    - files nothing when `entry.resolution != UNRESOLVED`;
    - refuses candidates that fail `validate_public_url`, dropping them rather than failing.
  - A test asserts that no module under `apps/` except `writers.py` calls `file_site_unknown` yet. Item 8 deletes that test in the same change that adds its caller, so the first caller is a reviewed decision and not a drift.

- [ ] **Step 2: Implement, run, commit**

```bash
git commit -m "feat(resolution): file_site_unknown, the resolver's residue interface"
```

---

## Task 12: The coverage line on the console

**Files:**
- Modify: `apps/research/resolution/priority.py`, the list view
- Test: `tests/research/resolution/test_corridor_share.py`

§11: "Target **under one host in ten per corridor reaching a person**, measured and shown on the console."

- [ ] **Step 1: Test** `corridor_share()` → `{country_code: (items_waiting, organisations_known)}`:
  - `items_waiting` counts `OPEN` + `PARKED` + `DECIDED` rows whose `organisation_for()` (or, for `register:`, `evidence.country_code`) is in that country.
  - `organisations_known` is `Organisation.objects.filter(country_code=cc).exclude(status="REJECTED").count()`.
  - Unknown country is bucketed as `""`.

- [ ] **Step 2: Implement.** The list view prints one line per country: `TR: 12 waiting / 1,417 known (0.8%)`.

  **It is a snapshot, not a rate, and says so on the line.** A cumulative "share that ever reached a person" needs history. The queue deletes rows by design and `AuditEvent` carries no subject. §18's "a history table" trigger applies here too: build it the day someone needs the cumulative number.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(resolution): the per-corridor share waiting on a person"
```

---

## Task 13: Priority by live packs blocked — needs an owner decision first

**Do not start this task until the owner has answered "Decisions this plan needs", item 1.** Tasks 1–12 stand without it, and the console orders by "registered, then oldest" meanwhile, printing "not computed".

**Files:**
- Create: `scripts/create_queue_counter.sql`
- Modify: `apps/research/resolution/priority.py`, `tests/infra/test_template.py`, `CLAUDE.md`, `docs/runbooks/deploy.md`
- Test: `tests/research/resolution/test_pack_count_rls.py`

**Why this needs a `BYPASSRLS` role:**
- "Items blocking the most live packs first, whichever tenants'" is a count over `funding_packversion`, `funding_packcandidate` and `funding_recommendationcandidate`. All three are tenant-scoped and `FORCE` RLS.
- The console's request carries the platform agency's GUC, so an ORM count returns the **platform's own** packs (failure mode 2).
- A `SECURITY DEFINER` function owned by the table owner is filtered exactly the same way (failure mode 3).
- Only a `BYPASSRLS` owner answers it. This is `CLAUDE.md`'s rule 1 for crossing tenants: *a fact that is not about a person, one named function, the narrowest answer, audited.*

**The function (in the admin script, never a migration):**

```sql
-- Returns ONE integer: how many live packs (published, not superseded), in any
-- agency, contain a candidate for any of these catalogue programmes. Never a
-- run, a student, a tenant or a pack id.
CREATE OR REPLACE FUNCTION public.live_pack_count(program_ids uuid[])
RETURNS integer
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    -- Fail loudly if the owner cannot actually cross tenants (failure mode 3):
    -- an owner-owned copy of this function would return the CALLER's tenant's
    -- count and look exactly like a real one.
    IF NOT (SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'live_pack_count is owned by a role without BYPASSRLS';
    END IF;
    RETURN (
        SELECT count(DISTINCT pv.id)::integer
        FROM public.funding_packversion AS pv
        JOIN public.funding_packcandidate AS pc ON pc.pack_version_id = pv.id
        JOIN public.funding_recommendationcandidate AS rc ON rc.id = pc.candidate_id
        WHERE pv.published_at IS NOT NULL
          AND pv.superseded_at IS NULL
          AND rc.program_id = ANY(program_ids)
    );
END $$;
```

The rest of the script is a copy of `create_erasure_guard.sql`'s load-bearing order, for a new role `tehsil_queue_counter NOLOGIN NOINHERIT BYPASSRLS`:
- revoke every membership except the running admin's;
- `GRANT CREATE ON SCHEMA public` to the new owner;
- `REVOKE ALL … FROM PUBLIC` **before** `ALTER FUNCTION … OWNER TO`;
- `GRANT SELECT` on exactly the three tables;
- `GRANT EXECUTE` to `:"runtime_role"`;
- assert `PUBLIC` holds no `EXECUTE`.

Read `CLAUDE.md`'s two measured ordering facts before writing it. Do not re-derive them.

**Subject → programme ids (Python, shared catalog, readable by runtime):**
- `award:` → the award's `programs` plus, for `INSTITUTION` scope, every `Program` at its institution.
- `host:` → programmes whose `OfficialSource.canonical_url` host, or whose institution's `official_website` host, is that host.
- `organisation:` and `register:` → none, which is 0. By construction neither is in any pack yet, so registered-first ordering carries them.

**Every call leaves an `AuditEvent`** (`resolution.pack_count_read`, object_id = item id), per `CLAUDE.md`'s rule 1 and `phased requirements.md` §349.

**A count of 1 is one student's pack.** It is shown only to the platform, which decision 26 already lets see every agency. So it is not a disclosure to anyone who lacks the right. It is still written here, because the same number on any agency-facing surface would be.

- [ ] **Step 1: Tests**
  - Through `runtime_connection`:
    - with the function owned by an ordinary role, it **raises**, and does not return a number;
    - after running the script's role section in the fixture, two packs in two agencies containing one programme count as **2**, under the platform agency's GUC.
  - `test_template.py`: `test_only_the_erasure_guard_role_gets_bypassrls` becomes `test_only_the_two_admin_roles_get_bypassrls`, asserting each script's lines exactly, and `test_no_migration_creates_a_bypassrls_role` still passes.

- [ ] **Step 2: Implement.** Implement `pack_counter()` in `priority.py`, which calls the function and writes the audit event. Pass it from the list view. Add a runbook step 8, after the erasure guard.

- [ ] **Step 3: `CLAUDE.md`.** In the RLS section:
  - change "the one role in this system with `BYPASSRLS`" to name both roles, each owning exactly one function;
  - add a paragraph for the third RLS case (platform-only), with a pointer to this plan's justification section.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(resolution): priority by live packs blocked, via a second audited BYPASSRLS function"
```

---

## Task 14: `CLAUDE.md` — the third RLS case, whatever Task 13's fate

If Task 13 is deferred, still add the platform-only paragraph to `CLAUDE.md`'s RLS section in this change, in five sentences:
1. What the predicate is.
2. Why it is not the forbidden platform-admin widening.
3. What it does not protect against.
4. That it is `ENABLE` without `FORCE`, and why.
5. That the write-back runs in `apply_resolutions` because the runtime role cannot write the shared catalog.

Commit: `docs(claude): the platform-only RLS case`.

---

## Measurement gate (§11, §16 item 12)

**Thirty items worked by one operator with a stopwatch: median < 60 s, zero needing outside research, every resolution provably absent from the next run's queue.**

**How the thirty are assembled.** Assemble them from what exists today, not from `SITE_UNKNOWN`, whose writer is item 8's:

1. `manage.py file_award_disputes` over the 58-host re-run's catalog. §16 item 3's gate produces UNAGREED and AGREED-unservable rows. Take up to 15.
2. `manage.py discover` on the EACEA seed with `--max-leads 60`. Its blocked hosts file `HOST_UNREACHABLE`. Take up to 10.
3. `manage.py classify_organisations` over a VGM slice of 200 unclassified bodies (≈ $0.20). Its abstentions file `KIND_OR_COUNTRY_UNSURE`. Take up to 10.
4. Fill to 30 in that proportion. If a source yields fewer, take more from the others and **record the shortfall per kind**. A kind absent from the thirty is a kind the gate did not test, and the result says so.

**How it is run:**
- One operator, on `/platform/resolution/`, with the daily cap raised to 30 for the session (`RESOLUTION_DAILY_CAP_PER_OPERATOR=30`).
- For each item, the operator notes "needed outside research: yes/no". *Yes* means they left the console to decide: opened a new tab, or searched.
- Then `manage.py apply_resolutions` runs. Its per-item lines carry `opened_at → decided_at` in seconds; that is the stopwatch, and a hand stopwatch cross-checks the first five.
- Then the three writers re-run on the same subjects (`discover` with the same leads, `classify_organisations` on the same organisations, the funding reader on the same pages). The same subjects are read from a saved list, and one query checks them: `ResolutionItem.objects.filter(subject_key__in=<the thirty>)` must be empty.

**What would fail it** (any one fails the gate):
- the median of the thirty `seconds` values is ≥ 60;
- one or more items were marked "needed outside research";
- one or more of the thirty subject keys is present after the re-run;
- `apply_resolutions` reopened an item for any reason other than "the page changed". Any other reopen means the one-click answer was not actually one click.

**What is recorded:** `docs/superpowers/2026-MM-DD-resolution-queue-gate.md`, with:
- the thirty lines;
- the per-kind counts and shortfalls;
- the median;
- the research flags;
- the re-run check's output;
- the corridor share line for TR before and after.

This is a measurement, not a test. Nothing asserts it in CI.

---

## Decisions this plan needs from the owner

1. **Task 13's role.** A second `BYPASSRLS` role (`tehsil_queue_counter`, recommended), or `tehsil_erasure_guard` owning a second function?
   - Recommended: the second role. `CLAUDE.md` describes the guard as "owning exactly one function", and a reviewer reasons from that invariant.
   - The cost is one more admin-script step per environment.
   - Or: defer Task 13 until packs exist at a volume where ordering matters. The queue works without it.
2. **`/platform/resolution/` rather than `/owner/`** (Correction 1). Recommended because `/owner/` is every agency's.
3. **`KIND_OR_COUNTRY_UNSURE` asks for `funds_students` too** (Correction 8). This widens §11's option list by one required field.
4. **`contradicts_register` stays out of the queue.** When the register says funder and the homepage says not, should that be a fifth question, or should the register simply win? This plan leaves today's behaviour ("askable next run, forever").

## Out of scope, named so nobody assumes it was done

- **`SITE_UNVOUCHED`, its writer and its pool-side exclusion** — item 10 (§6.4a item 5). The registry takes it as one entry.
- **Origin-less or untranslatable catalog rows reached inside a student's run** (`services.py` no-origin and degraded). They are catalog defects, still tenant-filed. The fix is a `pool.py` invariant, not a queue kind.
- **`ABSTAINED` funding rows.** No longer listed by `funding_review` after Task 8. The reader's retry is their path; `funding_yield` counts them.
- **`fetch_page` honouring `HostProfile.retired_at`.** Only `retrieve_official_source` does (Task 9). The fetch engine's other callers still spend on a retired host.
- **The production console's markup and interaction design** — the orchestrator's, against the behaviour Tasks 5–6 pin.
- **A history of resolutions** — `AuditEvent` carries who and when, and the catalog carries what; a table of "what was asked" waits for someone to need it (§18).
