# Runtime and boundary decisions

## Runtime

Phase 1 uses Python 3.12 and Django 5.2. Django 5.2 is an LTS release, supports
Python 3.12, and receives extended support through April 2028. PostgreSQL is the
only application database.

Sources: [Django downloads](https://www.djangoproject.com/download/) and
[Django/Python compatibility](https://docs.djangoproject.com/en/6.0/faq/install/).

`django-multitenant` is deliberately excluded. Its published compatibility table
stops at Django 4.2 and missing tenant context falls back to the native unscoped
ORM. Tenant access therefore uses a small fail-closed context/manager plus
tenant-inclusive database constraints and PostgreSQL RLS.

Production selects one of three explicit database credential pairs with
`DATABASE_ROLE` (`config/settings/database.py`): `runtime_engine` uses
`POSTGRES_ENGINE_USER`/`POSTGRES_ENGINE_PASSWORD`, `runtime_web` uses
`POSTGRES_WEB_USER`/`POSTGRES_WEB_PASSWORD`, and `migration` uses
`POSTGRES_MIGRATION_USER`/`POSTGRES_MIGRATION_PASSWORD`. All three share
`POSTGRES_DB`, `POSTGRES_HOST`, and optional `POSTGRES_PORT`. The two runtime
roles are split by caller (2026-09-25): `runtime_engine` is every worker task,
the catalogue's reader and only writer; `runtime_web` is the agency-facing web
tier and holds no grant at all on the shared-catalogue tables, so a web path
that reaches the catalogue fails with `permission denied` rather than reading
it. `migration` owns every table and runs only the one-off migration task. RLS
is unchanged and remains the tenant-isolation mechanism for both runtime roles;
the catalogue boundary is a table `GRANT`, not a policy.

The role names are fixed literals, because the grants in
`apps/funding/migrations/0049_catalog_grants.py` name them. Every table and
sequence grant lives in that migration. `scripts/create_runtime_role.sql` runs
through `psql` as a privileged administrator, **before the first migrate**
(a non-superuser `CREATEROLE` admin can alter only roles it created), and takes
one variable, `migration_role`. It refuses a migration role that is a superuser,
`BYPASSRLS`, or one of the runtime roles; creates both runtime roles when
absent; makes them `LOGIN` with a non-expiring login and unlimited connection
limit; asserts rather than sets that they are not `SUPERUSER`, `CREATEDB`,
`REPLICATION` or `BYPASSRLS` (only a holder may change those, even to `NO`);
clears their role and database settings; revokes every membership under its
recorded grantor with `CASCADE` and checks none remain; refuses if either owns
an RLS-enabled table; and grants `CONNECT`. Passwords are set interactively
through psql's `\password`, so no cleartext password is passed in arguments or
SQL. All mutations are transactional. Automated AWS password injection and
rotation remain deferred.

Source: [django-multitenant README](https://github.com/citusdata/django-multitenant#supported-django-versionspre-requisites).

## External boundaries

- Standard SQS messages always include a validated tenant identifier and send the
  same value as `MessageGroupId` for fair scheduling. Fair queues improve quiet
  tenant dwell time; they are not quotas.
- Private Fargate tasks use controlled NAT egress, VPC Flow Logs, and VPC endpoints
  for supported AWS services.
- Research retrieval accepts only validated public HTTP(S) destinations and repeats
  validation after DNS resolution and redirects.
- Official sources are evidence. Retrieved content is untrusted data, never agent
  instructions.

Sources: [SQS fair queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-fair-queues-detailed.html),
[SQS metrics](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-available-cloudwatch-metrics.html#sqs-fair-queue-metrics),
[ECS outbound networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/networking-outbound.html), and
[Fargate task networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html).

## Model and UI choices

The application uses the OpenAI Responses API directly: GPT-5.6 Luna for
high-volume extraction, Terra for recommendation reasoning, and Sol or a human
for difficult exceptions. There is no multi-provider abstraction.

Source: [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model).

Staff MFA uses django-otp's TOTP implementation; version 1.6 added Django 5.2 to
its test matrix. Server-rendered screens vendor HTMX 2.0.10 rather than adding a
JavaScript build.

Sources: [django-otp change log](https://django-otp-official.readthedocs.io/en/stable/changes.html)
and [HTMX installation](https://htmx.org/docs/).

Uploaded documents remain quarantined until GuardDuty Malware Protection for S3
tags the object with a clean scan result.

Sources: [CloudFormation malware protection plan](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-guardduty-malwareprotectionplan.html)
and [GuardDuty scan-result tags](https://docs.aws.amazon.com/guardduty/latest/ug/how-malware-protection-for-s3-gdu-works.html).
