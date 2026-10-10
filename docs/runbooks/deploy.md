# Runbook: deploy

Deploys or updates the Phase 1 one-region stack (`infra/template.yaml`) for
`test` or `production`.

## Prerequisites (first deploy to an environment only)

1. Build and push `web`/`worker` images to ECR (same Dockerfile, same
   revision; `web`/`worker` are separate build stages), tag with the
   immutable `@sha256:...` digest, and fill in `AppImage`/`ProbeImage` in
   `infra/parameters/<env>.json`.

   Build and push the transcript OCR image separately -- its own Dockerfile and
   context, single-architecture, as Lambda requires:
   `docker build --platform linux/amd64 --provenance=false -t <repo>:ocr ocr/`,
   push it, and fill in `OcrImage` with its `@sha256:...` digest. Before the first
   deploy to a new account, check Service Quotas: new accounts start with a reduced
   Lambda memory quota and `OcrFunction` asks for 10,240 MB. Request the increase the week
   before the first deploy; if it is refused, deploy at 8,192 MB (spec §3.1).
2. Create/confirm the Route53 hosted zone for the environment's domain and
   fill in `HostedZoneId` and `DomainName` in the parameters file.
3. Fill in `DjangoAllowedHosts` with the environment's tenant domain
   suffix(es), leading dot (e.g. `.tehsil-agent.example`).
4. **The first deploy is a loop, and its first pass fails by design.**
   `scripts/deploy.sh` runs the stack deploy and then the migration task back
   to back, and on a new database nothing the migration needs exists yet:

   1. Run `scripts/deploy.sh <env>`. The stack deploy creates the `Database`
      resource (master credential auto-managed in Secrets Manager); the
      migration task then fails -- `tehsil_migration` does not exist, so it
      cannot log in (or, if it does exist, `funding/0049_catalog_grants`
      refuses with "run scripts/create_runtime_role.sql as the admin role, then
      re-run the migration" and creates nothing). The script exits non-zero.
      The web and worker services the stack deploy started crash-loop on
      database login until step 3 finishes; that is expected, not an incident.
   2. As the admin (the RDS master user), create the migration role and let it
      create tables in `public`. On PG 15+ `PUBLIC` no longer holds `CREATE` on
      schema `public`; this runbook uses an explicit **grant**, not database
      ownership, so the migration role owns tables but not the database:

      ```bash
      aws secretsmanager get-secret-value --secret-id <Database MasterUserSecret ARN> \
        --query SecretString --output text | jq -r .password
      psql "host=<DatabaseEndpointAddress> dbname=<DBName> user=<DBMasterUsername> sslmode=require"
      ```
      ```sql
      CREATE ROLE tehsil_migration LOGIN CREATEROLE NOSUPERUSER NOBYPASSRLS;
      \password tehsil_migration      -- the value in MigrationDatabaseSecret
      GRANT CREATE ON SCHEMA public TO tehsil_migration;
      ```

      Then, in the same admin session's shell, bootstrap the two runtime roles:

      ```bash
      psql "host=<DatabaseEndpointAddress> dbname=<DBName> user=<DBMasterUsername> sslmode=require" \
        -v migration_role=tehsil_migration \
        -f scripts/create_runtime_role.sql
      ```
   3. Run `scripts/deploy.sh <env>` again. The migration now finds both runtime
      roles, 0049's `CREATE ROLE` is a no-op, and the services recover on the
      forced redeployment.

   The script creates `runtime_engine` (workers: the catalogue's reader and writer,
   and the fetch engine's telemetry) and `runtime_web` (the agency web tier:
   every tenant table, **no grant at all** on the 25 shared-catalogue tables).
   The names are fixed, not variables — `apps/funding/migrations/0049_catalog_grants.py`
   grants and revokes by name — and every table grant lives in that migration,
   not in the script. The script makes both roles `LOGIN`, prompts for each
   password (`\password`), strips any role membership, and grants `CONNECT`.

   **The order is load-bearing, measured on PG 17 (2026-09-25).** A
   non-superuser `CREATEROLE` role may `ALTER`, set the password of, or revoke
   memberships from only a role it holds `ADMIN OPTION` on, and creating a role
   gives that option to its creator alone. So the admin must create both roles:
   0049 refuses to create them unless it runs as a superuser (dev, CI, tests),
   which is what makes the first pass above fail safely instead of stranding
   two roles nobody but `tehsil_migration` could ever make logins. Were they
   created by the migration role anyway, the script refuses with "run this
   script as the admin role BEFORE the first migrate". The RDS master user is
   not a superuser, so there is no way round this except a superuser.

   `tehsil_migration` (used only by the one-off migration task via
   `MigrationDatabaseSecret`, created in step 2) must be `NOSUPERUSER
   NOBYPASSRLS`, and hold `CREATEROLE` (historical migrations create and 0049
   drops the old `catalog_ingestion` role). The script refuses a migration role
   that is a superuser, `BYPASSRLS`, or one of the two runtime roles. It
   *asserts* the runtime roles are not `SUPERUSER`/`CREATEDB`/`REPLICATION`/
   `BYPASSRLS` rather than setting them `NO`: PG 17 lets only a role holding
   an attribute change it, even to `NO`, so setting them would make the script
   superuser-only.

   Set the passwords to match the generated secrets: `runtime_engine`'s from
   `EngineDatabaseSecret`, `runtime_web`'s from `WebDatabaseSecret`,
   `tehsil_migration`'s from `MigrationDatabaseSecret`. Each task definition's
   execution role reads only its own secret (`WebExecutionRole` reads only
   `WebDatabaseSecret`).

   **First deploy only: before any agency has a login, re-run the assertions of
   `tests/tenancy/test_catalog_grants.py` against the real database.** Every
   grant here has been verified against roles in a test database, which is the
   right instrument and still not RDS. At minimum, as the admin:
   `SELECT tablename FROM pg_policies WHERE policyname = 'shared_catalog_select'`
   (expect the catalogue list), then for each,
   `has_table_privilege('runtime_web', tablename, 'SELECT')` must be false and
   `has_table_privilege('runtime_engine', tablename, 'SELECT')` true; and
   `pg_auth_members` must list no membership for either runtime role.

5. Put the OpenAI API key into `OpenAiApiKeySecret`. The template creates that
   secret with no value — a third party issues the key, so CloudFormation can
   only own the container:

   ```bash
   aws secretsmanager put-secret-value \
     --secret-id <OpenAiApiKeySecret ARN> --secret-string "$OPENAI_API_KEY"
   ```

   Until this runs, the research and document workers start normally and then
   fail at their first LLM call: nothing in `config/settings` reads
   `OPENAI_API_KEY`, so there is no startup check to catch it.

   Put the two research fetch keys in the same way, into `FirecrawlApiKeySecret`
   and `ScrapeDoApiKeySecret`:

   ```bash
   aws secretsmanager put-secret-value \
     --secret-id <FirecrawlApiKeySecret ARN> --secret-string "$FIRECRAWL_API_KEY"
   aws secretsmanager put-secret-value \
     --secret-id <ScrapeDoApiKeySecret ARN> --secret-string "$SCRAPEDO_API_KEY"
   ```

   Their absence fails *more quietly* than the OpenAI key's. Every research page
   fetch goes through `apps/research/fetch`, and an unset key raises
   `VendorUnavailable`, which subclasses `SourceBlocked` — the pipeline's
   degrade-do-not-abort path. A sweep run without them opens a consultant task
   per lead, writes nothing, and exits 0.

   Transcript reading needs Azure Document Intelligence: create the resource in an
   EU region (S0 tier), put its key into `AzureDocumentIntelligenceKeySecret` the
   same way, and pass its endpoint as the `AzureDocumentIntelligenceEndpoint`
   stack parameter. Leave `TRANSCRIPT_AZURE_ENABLED` unset until the owner records
   the Microsoft data-processing review; the template never sets it.

   There is no `FIRECRAWL_WEBHOOK_SECRET` to set. Nothing in this repo reads
   one: the crawl webhook it belongs to is plan 2's, behind a feature flag until
   a public endpoint exists.

   **Then set a per-key credit spend limit in each vendor's dashboard**
   (Firecrawl: API keys page → *Set limit*; scrape.do: the equivalent on its
   account page), at whatever the corridor's monthly budget is. This is layer 1
   of the cost controls and it is *configuration, not code* — deliberately. The
   in-code ceiling (`SweepBudget`, `FETCH_SWEEP_CREDITS`) is checked **after**
   the vendor reports a call's cost, because scrape.do's per-domain multiplier
   (10–200 credits) is applied server-side and is not knowable beforehand. So
   the in-code ceiling records an overspend and refuses the *next* rung; the
   dashboard limit is the only one that survives a bug in `SweepBudget`, and
   nothing in the codebase can replace it.

6. Once per environment, **after** the first migration task has run, create the
   cross-tenant erasure guard. It grants `EXECUTE` to `runtime_engine` only —
   the one caller is the worker's `execute_due_erasures` — and takes no psql
   variables. It is not a migration because only a role that
   already has `BYPASSRLS` may create one with it, and `tehsil_migration` has
   neither — see the script's header:

   ```bash
   psql "host=<DatabaseEndpointAddress> dbname=<DBName> user=<DBMasterUsername> sslmode=require" \
     -f scripts/create_erasure_guard.sql
   ```

   Skipping it scrubs nothing wrongly, but it is not free. `redact_identity`
   raises `UndefinedFunction` the first time an erasure runs — after
   `advance_deletion` has already called `delete_student_documents` and
   `delete_student_portal_credentials`, both irreversible and both *outside*
   the transaction. The request stays `APPROVED` and the login is untouched, so
   nothing is falsely recorded as erased; that student's documents and portal
   credentials are gone regardless.

   The script also states the privileges it needs in its own header. **They have
   not been verified against a real RDS master user, which is not a superuser** —
   nothing is deployed yet. Do that before the first production run. It is one
   transaction, so a shortfall fails loudly and changes nothing.

7. Once per environment, after the platform's own agency exists, mark it as the
   platform. Run it as the migration role, the only role that can write
   `research_platformagency`: both runtime roles hold SELECT on it and nothing
   else, and a trigger refuses any other writer too (`research/0013`). That is
   deliberate, because moving the platform moves who can read the resolution
   queue:

   ```bash
   DATABASE_ROLE=migration uv run python manage.py set_platform_agency <agency-uuid>
   ```

   (With `POSTGRES_MIGRATION_USER` / `POSTGRES_MIGRATION_PASSWORD` set, the same
   credentials `MigrationTaskDefinition` runs with.) Under `runtime_engine` or
   `runtime_web` the command stops with "this role cannot write
   research_platformagency". It refuses a second platform with "already the
   platform"; moving it is a hand edit by the database owner. Until this step
   runs, the resolution queue is invisible to everyone, and
   `/platform/resolution/` answers 403. It fails closed, never open.

## Every deploy

```bash
export AWS_REGION=eu-central-1
bash scripts/deploy.sh test         # or: production
```

This runs, in order:

1. `aws cloudformation deploy` with `infra/parameters/<env>.json`.
2. A one-off `aws ecs run-task` of `MigrationTaskDefinition` (runs
   `manage.py migrate` as the `tehsil_migration` role); the script fails
   loudly if the task's exit code is nonzero.
3. `manage.py check --deploy --settings=config.settings.production`.
4. `aws ecs update-service --force-new-deployment` for `worker`, **waited to
   stable**, and only then the same for `web`. The order is load-bearing, not
   tidiness: queue messages forbid extra fields, so an old worker cannot parse
   a message carrying a field added this release — it dead-letters, and the
   alarm fires up to 45 minutes after this script reports success. Roll the
   consumer first. Pinned by
   `tests/infra/test_template.py::test_deploy_rolls_the_worker_before_the_web_tier`.
5. `scripts/smoke.sh` against the freshly deployed stack.

If any step fails, the previous task set keeps serving traffic (ECS rolling
deployment) — no rollback action is required unless `smoke.sh` also fails,
in which case treat it as an incident and `aws ecs update-service` back to
the last known-good task definition revision.

### After a release that changes the requirement reader

A new grammar operation, or a changed question definition, reaches programmes already read only
when their stored sentences are read again. `manage.py rederive_rules` does that from
`ProgramStatement` rows, with no page fetched. Run it as a one-off task on
`WorkerTaskDefinition` (`runtime_engine` is the catalogue's only writer). Do a `--dry-run` first:
it still spends decision tokens, but writes nothing and prints what would change.

The first release that needs it is the one carrying #183 (oldest-first order, plus defined scope
questions, which stops ordinary rules being held back as conditional) and #185
(`Program.referee_requirements`). Until rederive runs, every programme read before that release
has no referee facts.

## Scheduled commands — run by hand until the schedule exists

One management command is a deployment gate, not a convenience: nothing invokes it on a schedule
yet (see `docs/superpowers/specs/2026-09-14-scheduled-work-deployment-design.md` §5.1), so until it
gets its EventBridge rule (model it on `EuropassCanaryRule` in `infra/template.yaml` — ECS `RunTask`
against `WorkerTaskDefinition`), run it by hand:

- `manage.py execute_due_erasures` — moves a `DeletionRequest` from `APPROVED` to `EXECUTED` once
  its thirty-day window expires, `rate(1 day)`. Skipping it leaves a student who asked to be erased
  locked out indefinitely and never erased, while every screen says the right thing. See CLAUDE.md,
  "Erasure: the schedule is deferred".

**Before it can reach a real student, its EventBridge rule must exist.** It is not required for the
first deploy of the base stack.

Two hourly commands are scheduled and need nothing by hand: `send_due_reminders`
(`ReminderLadderRule`) and `watch_applications` (`WatchApplicationsRule`, which raises
overdue-confirmation alerts and escalates unacknowledged urgent ones). Each records its last
finished run in `watch_jobrun` and logs `JobSilent job=<name>` when the other has not
finished within two hours; `JobSilentAlarm` counts those lines. That only sees one job stopping:
both share one image and task definition, so a bad deploy can kill both and leave nobody to log
`JobSilent`. Every finished run therefore also logs `JobFinished job=<name>`, and
`JobFinishedMissingAlarm` fires after two hours with none (missing data breaches). Expect it to
be in ALARM on a fresh stack until the first hourly run finishes. The alarms have no action
attached yet — wire them to a notification topic when one exists.

## Student mailboxes: the sweep, push, and the mailbox worker

- **`SyncMailboxesRule`** runs `manage.py sync_mailboxes` on `WorkerTaskDefinition` every 6 hours,
  shipped enabled. It is the backstop for every Graph notification that is dropped, the only
  reader for connections push does not cover (Gmail, an agency with no verified host, push off),
  and the subscription upkeep: each run creates, renews (under two days left) or recreates every
  Microsoft connection's subscription before syncing it. The heartbeat expects it within 13 hours
  (`JobSilent job=sync_mailboxes`); `SyncMailboxesRuleFailedInvocationsAlarm` covers a rule that
  stops invoking.
- **`MailboxWorkerService`** (`mailbox-worker`, one Fargate task) runs `manage.py
  run_mailbox_worker`, draining `MailboxQueue`, which the web tier fills from Graph's webhook and
  the OAuth callback. `MailboxQueueAgeAlarm`, `MailboxDeadLetterDepthAlarm` and
  `MailboxWorkerCrashAlarm` watch it. `scripts/deploy.sh` does not roll it; a new `AppImage`
  digest rolls it through the stack update.
- **`MailboxPushEnabled`** (default `"0"`, feeds `MAILBOX_PUSH_ENABLED` on web, worker and mailbox
  worker). Set it to `"1"` only once **both** hold: a tenant has a verified public HTTPS host
  (`TenantDomain`) Graph can reach, and `mailbox-worker` is running and stable. Before that, the
  sweep alone reads mail, which is correct, just slower.
- **Rotating the Django secret key turns push off silently.** Each subscription's `clientState` is
  an HMAC under it and a renewal cannot resend it, so every notification is rejected until the
  subscription is recreated. After a rotation, as the worker, clear `push_subscription_id` on every
  Microsoft `MailboxConnection`; the next sweep recreates them, and reads the mail meanwhile
  (watch spec §3a).
- **OAuth client credentials.** Unset, settings default to `""`: no student can connect and
  every token refresh fails. Web gets both client IDs, both client secrets and
  `MAILBOX_OAUTH_REDIRECT_BASE`; worker and mailbox worker get the IDs and secrets (refresh only).
  - **Secret, once per environment.** One secret, both JSON keys present (ECS reads each by key;
    a missing key stops all three tasks starting). Until Gmail is enabled, `google` holds the
    placeholder `unused`, not `""`: whether ECS injects an empty JSON value has not been
    measured, and a placeholder is never read while `MAILBOX_PROVIDERS` excludes GOOGLE:

    ```bash
    aws secretsmanager create-secret --name tehsil/mailbox/oauth-client \
      --secret-string '{"microsoft":"<value>","google":"unused"}'
    ```

    Type the value in your own terminal; never paste a real one into a shared log, ticket or
    chat. Put the **full ARN the command prints** (with its six-character suffix) in
    `MailboxOAuthClientSecretArn`; a partial ARN fails both ECS's lookup and the IAM grant.
  - **Parameters.** `MicrosoftOAuthClientId` (the app's Application (client) ID, a GUID),
    `GoogleOAuthClientId` (empty until Gmail), `MailboxOAuthRedirectBase` (absolute `https://`
    base, no trailing path, e.g. `https://agency.example.com`).
  - **Microsoft app registration.** Supported account types: *any organizational directory and
    personal Microsoft accounts* (multitenant + personal). The Web redirect URI must equal
    `MailboxOAuthRedirectBase` + `/mailbox/callback/MICROSOFT/` exactly — case and trailing
    slash included.
  - **Client secrets expire (24 months at most).** Set a calendar reminder a month before the
    expiry date shown in Entra, create the new secret there, `put-secret-value` it into the same
    secret (keep the `google` key), and force a new deployment of web, worker and mailbox-worker:
    ECS reads secrets only at task start.
  - **Publisher verification** (a Microsoft AI Cloud Partner Program ID on the app registration)
    is required before students whose accounts sit in *other* organisations' Microsoft 365
    tenants can consent.

## The provenance gate: rollout order (spec §7.7)

Once per environment, as the worker (`DATABASE_ROLE=runtime_engine`), in this order:

1. `manage.py rederive_domains` -- only on a database that held data before the private-suffix fix.
2. `manage.py load_closed_lists`
3. `manage.py verify_list_origins` -- read the output. A reviewed row that does not verify stays
   `unmapped_list_row` until a person fixes its website in the list file.
4. `manage.py backfill_evidence_domain` -- every programme catalogued before the gate has an empty
   evidence domain and would be silently excluded from every pack.
5. `manage.py provenance_check --all` -- the backfill of verdicts.
6. The stack parameter `ProvenanceGateEnforced` defaults to `"1"` (verified-only, verified-catalog
   spec §0.18). On a fresh environment with no catalogued programmes, steps 4-5 have nothing to
   backfill, so no flip is needed. On a database that held data before the gate, set `"0"` first,
   run steps 1-5 to completion, then set `"1"` in its own reviewed change: enforcing on an empty
   verdict table empties every pack. It feeds both the web and worker task definitions.

`ProvenanceRecheckRule` then runs `provenance_recheck` daily. Without `OPENROUTER_API_KEY` in the
worker's secrets, the two content vetoes are recorded as skipped. Add it once Jev's DPA is filed
(spec §13.4).

**A RECOGNISED domain is never fully re-checked on a schedule** (verified-catalog spec §4.1, owner
2026-10-03). It leaves RECOGNISED through an explicit `manage.py provenance_check --all` or
`--domain`, or through the free yearly screen in `provenance_recheck`
(`PROVENANCE_RECOGNISED_SCREEN_DAYS`, default 365): RDAP and the local mill list only, no page
fetch. The RDAP takeover check and a later mill-list addition therefore reach a proven pair through
that screen, and only a flagged pair is fully re-checked. Until the off-origin reset of Part F lands,
a recogniser withdrawing its vouch link and a register delisting still cannot reach a proven pair on
their own. Run `provenance_check --all` after loading a new mill list if you cannot wait for the
screen. A failed RDAP lookup is unknown (no takeover found, retried next run), not proof of continuity.

`manage.py mill_list_diff` is not scheduled: run it by hand each cycle and read its output. The
pinned list revision is what admits, so a skipped run delays a change, never admits a mill.

## The fetch engine's role (and rung 5)

`fetch_page` writes a `FetchAttempt` on every rung and a `HostProfile` on every
terminal one, and both tables are write-restricted to `runtime_engine` (the
`runtime_engine_write` policies, repointed from the dropped `catalog_ingestion`
by `apps/funding/migrations/0049_catalog_grants.py`). Every task definition
except web, portal and migration — worker, Europass worker, document worker,
mailbox worker — runs as `DATABASE_ROLE=runtime_engine`, and the commands run on
`WorkerTaskDefinition`, so `discover`, `fetch_ladder`,
`funding_yield` and `retry_due_fetches` need nothing special. The earlier
advice to run them under `DATABASE_ROLE=migration` is over (2026-09-25).
`RetryDueFetchesRule` still ships `DISABLED`, though — not for a login reason
any more, but because a successful retry delivers its page to nobody
(`retry_due_fetches`'s own docstring: no snapshot persisted, no reader re-run,
no task closed), so enabling it on a schedule would spend vendor credits every
six hours for a result nothing downstream receives. See CLAUDE.md, "Rung 5 of
the fetch ladder has a schedule, and it stays off".

Under `DATABASE_ROLE=runtime_web` the same call fails with `permission denied
for table research_fetchattempt` — deliberately: the web tier holds no grant on
the catalogue, and a student-facing action that needs a fetch queues it to the
worker instead.

## The live fetch gate: what a run costs

`tests/research/test_fetch_live.py` is excluded from every default run by
`addopts = "-m 'not live'"` in `pyproject.toml`. It spends real vendor credits,
so it is run deliberately:

```bash
FIRECRAWL_API_KEY=... SCRAPEDO_API_KEY=... \
  POSTGRES_DB=<a database this developer owns> \
  uv run pytest tests/research/test_fetch_live.py -m live -v
```

19 tests. **Ceiling: 267 credits** — 3 Firecrawl and 50 scrape.do for the five
vendor-contract tests (two of them at `render=true&super=true`, 25 each), 202 for
the twelve hard hosts (the sum of their per-host ceilings, each enforced by its
own `SweepBudget`), 10 for the PDF case and 2 for the unchanged-page pair. At
Firecrawl's $83/100k that ceiling is $0.22; at scrape.do's $29/250k it is $0.031;
the real bill sits between them, because the ladder stops at the first rung that
serves. A host that has become harder costs more and fails its ceiling assertion
— which is the alarm, not a bug.

Record the actual per-host credits from a run. They are the first real numbers
the engine produces and the next tier decision rests on them.

## The shared rate-limit cache (node-based Valkey, cluster mode disabled)

`apps/ratelimit.py`'s counters and research-fit's daily spend cap need a real
atomic `INCR` that keeps its own TTL — Django's SQL-backed `DatabaseCache` does
not have one (its `incr` is a non-atomic get-then-set that resets the key's
expiry), so it was rejected on review. ElastiCache **Serverless** for Valkey was
tried next and rejected on a second review: AWS documents it as speaking only
the Valkey/Redis OSS cluster protocol, and Django's built-in `RedisCache` uses
the plain non-cluster client. `infra/template.yaml`'s `Cache` resource
(`AWS::ElastiCache::ReplicationGroup`, `Engine: valkey`, `NumCacheClusters: 1`,
cluster mode disabled) is what that client actually speaks; each app task's
`CACHE_URL` environment variable is built from its
`PrimaryEndPoint.Address`/`PrimaryEndPoint.Port` at deploy time (`rediss://` —
`TransitEncryptionEnabled: true`). Nothing to run by hand: the cache exists
before any task starts, unlike the database, and needs no bootstrap script.
`config/settings/production.py` reads `CACHE_URL` via `os.environ[...]` like
every other required setting, so a task definition missing it fails at import,
before any command logic runs — the same failure shape as a missing queue URL
(this also means an operator running `manage.py check --deploy
--settings=config.settings.production` by hand, as `scripts/deploy.sh` does,
needs `CACHE_URL` exported locally too — a gap that already existed for
`DJANGO_SECRET_KEY` and the queue URLs and is not new here).
`CacheSecurityGroup` admits exactly the web, worker and portal security groups
(the same three `DatabaseSecurityGroup` admits), never the OCR function's.

**One node, no failover, by design for now** (`NumCacheClusters: 1`, no
`AutomaticFailoverEnabled`) — a pilot-scale ceiling, not a final answer: the
counters this backs are not a source of truth for anything (a lost counter
degrades to "the limit resets", never data loss), so a node's rare loss is an
acceptable outage, not a data-loss event. Add a second node
(`NumCacheClusters: 2`) and `AutomaticFailoverEnabled: true` when that stops
being acceptable. `cache.t4g.micro`'s monthly on-demand cost in `eu-central-1`
is **unverified** — AWS's pricing page gives worked examples for other node
types but no queryable per-type-per-region rate table was reachable from the
build environment that wrote this.

## Region

Phase 1 supports exactly one region (`eu-central-1`, enforced by the
`Region` template parameter and the `AWS_REGION` guard in `deploy.sh`). Do
not deploy this template anywhere else.

**Marking a cycle paid.** Until a checkout exists, a student's academic-year cycle is marked paid by hand: `python manage.py mark_cycle_paid --tenant <agency uuid> --student <membership uuid> --academic-year 2026-2027`. It writes a `cycle.marked_paid` AuditEvent. Transcript uploads and the programme search are refused until it has run (transcript spec R13).

**Transcript readings resume themselves.** `TranscriptResumeRule` runs `manage.py resume_transcript_readings` every 15 minutes on the document worker's task definition. It retries readings delayed by an Azure outage or by the per-tenant daily ceiling (`TRANSCRIPT_TENANT_DAILY_AZURE_PAGES`, default 2,000). It also retries readings lost with a killed worker. After 12 attempts (about a day and a half) an upload is FAILED with `reader_unavailable`.
