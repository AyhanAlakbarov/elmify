# Cloud Architecture

Status: Approved design draft for review. This document defines the cloud architecture for the phased product described in `idea_v2.md` and `phased requirements.md`. It does not authorize source-code creation or infrastructure deployment.

## 1. Architecture principles

- Use the smallest architecture that supports the Phase 1 Funding Intelligence core and the commercial concierge MVP.
- Deploy in one AWS region. The Phase 1 default is `eu-central-1` (Frankfurt); a mandatory legal or data-residency requirement may change the production region before launch.
- Keep one Django web application and one Python research worker.
- Use PostgreSQL for application and Funding Intelligence data.
- Enforce agency tenancy primarily through fail-closed Django application and ORM scoping, with database constraints and row-level security as secondary safeguards across requests, jobs, rows, object keys and exports.
- Treat official web content as untrusted input and preserve evidence provenance.
- Keep deterministic eligibility, affordability, budget and threshold rules outside the LLM.
- Require human review before publishing each initial Phase 1 recommendation pack.
- Let consultants deliver unautomated concierge operations through approved procedures, then add later-phase application automation without introducing speculative services now.

## 2. Phase 1 system boundary

Phase 1 provides:

- Consultation and progressive student-profile intake.
- Worldwide hybrid discovery across all approved funding categories.
- Research Ecosystem Mapping for hard-to-find funded programs.
- Official-source evidence collection and freshness tracking.
- Personalized evaluation and recommendation classification.
- A broader student-objective recommendation pool and a budget-based recommended application pack.
- An agency-branded, versioned Consultation Recommendation Report delivered after payment and consultant approval.
- Chat-driven program additions, removals and replacements.
- Consultant review and a student roadmap dashboard.
- Manually updated roadmap statuses during the pilot.
- Agency subdomains, controlled branding, separate counselor and student views, document approvals and audit exports.
- Verified custom domains with managed TLS before the first external agency is onboarded.

Phase 1 does not automate CV or motivation-letter production, dedicated student email, portal submission, application-fee custody, payments, portal monitoring or interview services. Consultants may provide these as controlled commercial concierge operations once their launch blockers are cleared; later phases progressively automate them.

### 2.1 Commercial operations boundary

- The dashboard represents consultant and agent work through the same application stages, owners, deadlines and audit events.
- Consultants initially operate permitted applications, CAPTCHA, payments, monitoring and other delegable work through assignment-scoped access. Later phases may integrate a CAPTCHA-resolution service only for portals that pass legal and terms-of-service approval, with preserved-session consultant fallback.
- Students are contacted only for non-delegable identity, personal authentication, signature, attestation, new-fact, personal-decision or additional-spending actions.
- Manual delivery does not relax security, portal-terms, payment or legal launch gates.
- Phase 1 code does not include dormant browser or payment automation for later use.

## 3. Logical architecture

```text
Student / Counselor / Agency Owner / Platform Administrator
                  |
        Agency domain or subdomain
                  v
       Application Load Balancer
                  |
                  v
       Django web application
       on Amazon ECS/Fargate
       |          |           |
       |          |           +--> Amazon S3
       |          |                source snapshots
       |          |
       |          +--------------> Amazon SQS
       |                           research queue + dead-letter queue
       |
       +-------------------------> Amazon RDS for PostgreSQL
                                       ^
                                       |
                         Python research worker
                         on Amazon ECS/Fargate
                         |        |         |
                         |        |         +--> OpenAI Responses API
                         |        +------------> Official APIs/RSS/sitemaps
                         +---------------------> Search, HTTP and browser fallback
```

## 4. Runtime components

### 4.1 Django web application

The web application owns:

- Authentication, sessions, roles and permissions.
- Host-to-tenant resolution, agency branding and custom-domain verification state.
- Tenant-branded login, dashboard and transactional-message templates.
- Agency-owner, counselor, student and platform-administrator views.
- Consultation and progressive profile forms.
- Student preferences, non-negotiable constraints and personalized weights.
- Research-run creation and progress display.
- Recommendation pool, recommended pack and budget calculations.
- Paid-consultation report generation, version history and download access.
- Chat requests to add, reject or replace programs.
- Consultant review and internal administration.
- Counselor assignments, mandatory approval gates and document-review workflows.
- Student-facing evidence explanations and roadmap.
- Append-only audit events and agency-branded dossier exports.

Django templates and HTMX provide interactive screens. A separate frontend application and public internal API are not required in Phase 1.

The verified host and authenticated agency membership establish an explicit tenant context before tenant-owned ORM access. Missing, invalid or conflicting context fails closed. Tenant-aware managers and querysets scope ordinary access, and privileged cross-tenant support uses a separate reason-bound, audited path. `django-multitenant` may be evaluated during implementation, but it is not selected until its supported Django version and missing-context behavior pass the isolation tests.

### 4.2 Research worker

The worker owns long-running tasks:

- Targeted discovery across government, multilateral, Erasmus Mundus, industrial, university, program-specific and research-ecosystem channels.
- Direct retrieval of official pages and documents.
- Browser rendering only when ordinary retrieval cannot read a JavaScript-dependent page.
- Source snapshotting, structured evidence extraction and confidence assignment.
- Eligibility and affordability-gate evaluation.
- Personalized scoring and explanation drafting.
- Retry, escalation and stale-evidence revalidation.

Every worker job carries an immutable tenant identifier that is validated and installed as fail-closed job context before tenant-owned data access or writes. Missing or conflicting context rejects the job. Failed jobs use bounded retries and then move to a dead-letter queue for counselor review. A failed replacement run never overwrites the last reviewed result.

### 4.3 PostgreSQL

PostgreSQL stores:

- Agencies, verified domains, branding tokens, users, roles, counselor assignments and versioned data-use permissions.
- Versioned student profiles and preferences.
- Institutions, departments, programs and relevant research organizations.
- Funding opportunities, funding benefits and eligibility conditions.
- City-specific cost components, student-benefit rules, geographic scope, availability constraints, source dates and confidence.
- Program-to-funding and program-to-research relationships.
- Official sources, evidence claims, retrieval dates and confidence.
- Recommendation runs, dimension scores and explanations.
- Recommendation pools, recommended packs, student decisions and budgets.
- Consultation payments and report versions linked to the exact counselor-approved recommendation pack.
- Approval policies, exact approved versions, review records and append-only audit events.

Every tenant-owned table carries `tenant_id`. Composite uniqueness and foreign-key constraints include the tenant where needed so records cannot reference another tenant accidentally. Application and ORM scoping is the primary control. PostgreSQL row-level security is a secondary default-deny failsafe, not the source of tenant context.

The application must not use connection-scoped `SET` for tenant identity. If an RLS policy reads a PostgreSQL tenant setting, each request or worker operation wraps its database work in a transaction and establishes the value with `SET LOCAL`, which expires on commit or rollback. The runtime role must neither own protected tables nor have `BYPASSRLS`; missing settings deny access. Administrative cross-tenant operations use a separate least-privilege, audited path.

No graph database or vector database is required. Ordinary relational relationships and indexed queries cover Phase 1.

### 4.4 Amazon S3

Private S3 buckets store immutable or versioned official-source snapshots, generated Consultation Recommendation Reports and tenant-isolated student documents used by the commercial concierge workflow. Later phases add raw platform-managed email messages with separate prefixes, access policies and retention rules.

The database stores metadata and object keys, not large source documents. Tenant-owned objects use tenant-scoped prefixes and access checks. Objects are encrypted, blocked from public access and accessed through scoped application roles.

### 4.5 Amazon SQS

SQS separates interactive web requests from long-running research. Phase 1 uses one Standard research queue and one dead-letter queue. Every message includes a validated `tenant_id` and sets `MessageGroupId` to that same internal tenant identifier, enabling Standard-queue fair scheduling without FIFO ordering. Fair scheduling mitigates noisy-neighbor dwell time but does not impose per-tenant rate or concurrency quotas. Dedicated queues or application-level tenant throttles are added only when measured workload requires different retry, priority, scaling or hard-isolation behavior.

### 4.6 OpenAI model routing

Phase 1 uses the OpenAI Responses API without a multi-provider abstraction:

- GPT-5.6 Luna: high-volume extraction, classification and normalization.
- GPT-5.6 Terra: recommendation reasoning and student-facing explanations.
- GPT-5.6 Sol or human review: difficult, low-confidence exceptions only.

Model outputs must use structured schemas. Deterministic application code applies eligibility gates, budget arithmetic, threshold rules and final score calculations. Model upgrades require the approved recommendation evaluation suite.

## 5. Discovery data flow

1. The student completes enough of the progressive profile to support matching, including acceptable teaching languages, available proficiency evidence, preferred program duration, duration flexibility and career intent.
2. Django creates a versioned recommendation run and places a job on SQS.
3. The worker retrieves relevant cached leads. Cached claims are treated as research hints until revalidated.
4. The worker performs targeted live research based on the student's field, goals, funding requirement and mobility preferences.
5. Official pages, documents or API responses are saved to S3 with retrieval metadata.
6. Luna extracts structured claims and attaches each claim to supporting evidence.
7. Direct funding, competitive funding, formal pipelines and ecosystem clues remain distinct.
8. Deterministic hard gates reject confirmed ineligibility, missed deadlines, unsupported evidence and unmet non-negotiable constraints.
9. Terra produces dimension-level reasoning from the verified claims.
10. Deterministic code calculates the personalized score and budget-based pack.
11. A consultant reviews the evidence, conflicts, scores and explanations.
12. The approved recommendation pool and recommended pack become visible to the student.
13. After consultation payment, Django generates a versioned, agency-branded Consultation Recommendation Report from the exact counselor-approved pack and makes it downloadable to the student.

## 6. Evidence and freshness controls

Every material claim records:

- Official URL and source type.
- Retrieved timestamp and applicable admissions cycle.
- Supporting excerpt or structured field.
- Extraction model and schema version.
- Confidence and review state.
- Source snapshot reference.

Evidence rules:

- Aggregators may identify coverage gaps or route research to an official page; their claims never support a recommendation.
- A grant, famous lab or institutional partnership is an ecosystem clue unless an official source connects it to master's-level access or funding.
- Tuition, stipend, relocation, housing, insurance and other benefits require explicit official evidence.
- A cost reduction from a social or student benefit requires current primary evidence for the exact country or city, likely student eligibility and sufficiently reliable ordinary access; never copy a benefit assumption between locations.
- Capacity-limited benefits remain conditional scenarios. Food banks and emergency aid may be displayed as support resources but never reduce the minimum viable affordability calculation.
- Relevant cached records are revalidated before entering a recommended pack.
- Active recommendation sources are monitored; inactive entries are refreshed when a new search makes them relevant.
- Conflicting or ambiguous sources block recommendation publication until resolved.

## 7. Recommendation controls

Hard gates run before scoring:

- Master's program taught in English or another language explicitly selected by the student.
- A viable path to satisfy the required teaching-language evidence by the applicable deadline.
- No confirmed eligibility failure.
- Viable deadline.
- Adequate current evidence.
- Student non-negotiable constraints.
- A viable funding route when funding is mandatory.

Affordability arithmetic uses a city-specific lower-end realistic student baseline supported by current primary evidence. It itemizes necessary costs and includes only verified, ordinarily accessible student benefits. Conditional benefits produce a separate lower scenario and uncertainty label rather than silently reducing the baseline or uncovered gap.

The student's versioned, approved strategy selects one of two ranking modes after hard gates:

- Balanced-fit mode requires at least `80/100` overall, no critical applicable soft-fit dimension below `60/100` and at least medium evidence confidence.
- Funding-first mode applies when the student declares that attendance depends on full funding and asks the platform to prioritize financially viable study-abroad opportunities. Verified total affordability becomes the dominant soft-ranking dimension; an eligible fully funded program may rank above a better-fit unaffordable program without a universal per-dimension soft-fit floor. The result must identify every material weakness and explain that funding-first ranking reflects the student's stated objective.

Neither mode may override confirmed ineligibility, an unworkable deadline or teaching-language requirement, inadequate evidence, or a student-defined non-negotiable constraint.

The score covers academic and career fit, affordability and funding, post-study mobility, legal mechanics, job-market language, degree portability, program structure and pedagogy, institutional ecosystem, operational friction and conditional professor or laboratory fit. Non-applicable dimensions are excluded and their weights are redistributed explicitly.

Duration is never inferred from a generic career label. Deterministic rules apply the student's explicit one-year, two-year or no-preference choice as either a hard constraint or a weighted preference. The explanation compares total degree cost, full-duration funding, study intensity, time to industry entry, internship or thesis access, research depth and post-study work conditions.

## 8. Network and security

- The load balancer is public; Django tasks, workers and RDS run in private subnets.
- All worker outbound access passes through controlled, auditable egress.
- Retrieval prefers official APIs, RSS feeds, sitemaps and downloadable documents, then uses ordinary HTTP and browser rendering only when necessary.
- Cache reuse, per-domain rate limits, bounded concurrency and exponential backoff reduce source load and blocking risk.
- A fixed egress proxy or data provider may be used only after security, legal and source-terms approval. Rotating or residential proxies, fingerprint evasion and attempts to bypass IP or anti-bot blocks are prohibited.
- A source that blocks compliant retrieval creates a consultant research task instead of triggering an evasive fallback.
- RDS and S3 are not publicly reachable.
- TLS protects external and service connections where supported.
- RDS, S3, backups and queues use encryption at rest.
- AWS Secrets Manager stores database, model and external-service credentials.
- IAM roles grant each runtime only the permissions it needs.
- Staff and administrator accounts require multi-factor authentication.
- Students verify their personal email; stronger authentication becomes mandatory before high-risk later phases.
- Application logs exclude secrets, raw student documents and unnecessary personal content.
- Every tenant-owned database row and object key carries a tenant identifier; fail-closed application and ORM scoping provide the primary enforcement, while database constraints, secondary RLS and automated isolation tests provide defense in depth.
- Cross-tenant platform support requires a time-limited grant, recorded reason and audit event.
- Agency owners and counselors require multi-factor authentication.
- Tenant-provided branding is limited to validated assets and tokens; arbitrary CSS, JavaScript and HTML are prohibited.

### Untrusted-source protections

- Validate requested URLs and reject loopback, link-local, private-network and cloud-metadata destinations.
- Revalidate redirects and resolved addresses to reduce server-side request-forgery risk.
- Apply response-size, content-type and time limits.
- Store and render source content as untrusted data; never execute retrieved scripts.
- Ignore instructions contained in retrieved pages. Web content cannot grant tools, change system rules or authorize actions.
- Escape source excerpts before displaying them.
- Malware-scan uploaded student documents.
- Resolve tenants only from verified hosts and reject unknown hosts before authentication or data access.

## 9. Reliability and recovery

- RDS automated backups and point-in-time recovery are enabled.
- S3 source snapshots are versioned or immutable by application convention.
- SQS retries are bounded and observable.
- Dead-letter jobs create consultant tasks instead of disappearing.
- Recommendation runs are versioned; publication is atomic.
- The last reviewed recommendation remains available when a refresh fails.
- Backup restoration is tested before the shadow pilot.
- Multi-region failover and Kubernetes are deferred; the initial recovery path is infrastructure recreation plus database and object restoration.

## 10. Observability

CloudWatch receives structured operational logs, metrics and alarms for:

- HTTP errors and latency.
- Queue age, retry count, dead-letter volume and SQS fair-queue quiet-group metrics.
- Research-run duration and completion rate.
- Retrieval and model failures by source type.
- Evidence staleness and consultant-review backlog.
- Model usage, latency and cost by task type.
- Authentication failures and suspicious access patterns.
- Cross-tenant authorization denials, support-access grants and mandatory-approval bypass attempts.

Student data is identified by internal IDs rather than personal content in logs.

## 11. Environments and delivery

- Development uses safe synthetic or explicitly approved test data.
- Testing runs the recommendation benchmark and application checks.
- Production uses separate AWS resources, secrets and access roles.
- Infrastructure is reproducible, but the implementation plan will select the minimum infrastructure-as-code mechanism.
- Database migrations are versioned and backed up before destructive changes.
- Deployment requires focused tests, full checks, migration verification and a production smoke test.

## 12. Later-phase extensions

The existing architecture can add:

- CV and motivation-letter jobs using the same worker pattern, plus a company-operated direct-to-consumer standalone order flow for CV Polish, motivation-letter and bundle purchases.
- Amazon SES inbound and outbound email for a real platform-domain address per student.
- S3-backed dashboard inbox and AI email handling.
  - *Superseded 2026-09-15:* no per-student platform address, no SES inbound, no S3 inbox. Mailboxes are the student's own, connected by OAuth at metadata or content tier and read through a pack-derived sender filter; refresh tokens live in Secrets Manager under `tehsil/mailbox/*`. SES stays for outbound notifications only. `docs/superpowers/specs/2026-09-15-student-owned-mailbox-design.md`.
- Dedicated application-execution workers using resumable browser sessions, an approved-portal CAPTCHA-resolution service with scoped consultant fallback, student handoff only for non-delegable actions and verified draft recovery.
  - *Superseded 2026-09-15:* portal filling runs as a browser extension in the student's own session against a server-minted fill packet; no execution workers, no resumable platform sessions, no CAPTCHA service, no portal credentials. The EC2 portal tier is retired by a deletion plan. `docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md`.
- Legally approved consultant-operated payments using a per-student ledger and controlled per-application virtual cards, followed by agent-operated ordinary payments with consultant exception handling.
- Portal monitoring, document requests and notifications.

These are later-phase automation additions. Consultants may deliver the corresponding end-to-end concierge work manually before the automation exists; they are not dormant Phase 1 scaffolding. The standalone document service shall not launch until the Phase 2 document engines and counselor-review controls pass their evaluations.

The standalone document storefront is available only on the company's direct channel. Host-to-tenant resolution and product entitlements shall prevent agency tenants from accessing, branding, publishing or reselling standalone document products; agency tenants receive only the end-to-end pipeline platform. The document engines and counselor-review workflow remain shared internally so the company does not duplicate implementation.

### 12.1 Later opt-in platform intelligence

Phase 1 stores only versioned agency data-use permissions and source lineage. It does not build a cross-tenant ETL service or data lake.

A later asynchronous pipeline may add:

- Tenant-isolated, allowlisted feature extraction.
- Identifier and quasi-identifier transformation with quarantined intermediate datasets.
- Automated PII and re-identification-risk checks followed by human privacy approval.
- A separate, platform-owned, access-controlled S3 intelligence data-lake area with immutable dataset and consent manifests.
- Deletion and revocation propagation while data remains identifiable or pseudonymous.
- Dataset-version binding for evaluation, optimization and fine-tuning jobs.

Direct training on tenant databases is prohibited. Derived data is not treated as anonymous or independent of tenant deletion merely because identifiers were removed or hashed.

## 13. Explicitly excluded from Phase 1

- Microservices.
- Kubernetes.
- Redis.
- A graph database.
- A vector database without a measured retrieval requirement.
- A separate JavaScript frontend.
- A custom internet-scale crawler.
- Rotating or residential proxy infrastructure intended to evade portal access controls.
- Multi-cloud or multi-region deployment.
- Fine-tuning.
- Cross-tenant ETL or a centralized training data lake.
- Multi-provider LLM routing.
- Autonomous portal submissions.
- Graphify generation or runtime dependency.

## 14. Commercial launch blockers outside Phase 1 software implementation

The production launch cannot proceed until the following are resolved:

- Whether the company is registered in Azerbaijan or the United States.
- Applicable privacy, consumer, cancellation and mandatory-refund rules.
- Final data-retention periods and data-processing agreements.
- Legal and payment-provider approval for holding student application-fee balances, maintaining the ledger and issuing or using controlled virtual cards.
- Terms governing automated access to each application portal and communication provider.
- Production domain, email reputation controls and sender-verification setup.
- Agency data-processing terms, tenant export and deletion procedures, and support-access rules.
- Verified custom-domain ownership, TLS provisioning and branded-email verification.

## 15. Authoritative references

- [Django authentication](https://docs.djangoproject.com/en/dev/topics/auth/)
- [Django admin](https://docs.djangoproject.com/en/stable/ref/contrib/admin/)
- [HTMX documentation](https://htmx.org/docs/)
- [AWS container decision guide](https://docs.aws.amazon.com/pdfs/decision-guides/latest/containers-on-aws-how-to-choose/containers-on-aws-how-to-choose.pdf)
- [Amazon SQS fair queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-fair-queues.html)
- [Django persistent database connections](https://docs.djangoproject.com/en/6.0/ref/databases/#persistent-connections)
- [PostgreSQL `SET`](https://www.postgresql.org/docs/current/sql-set.html)
- [PostgreSQL row security policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [Amazon SES email receiving](https://docs.aws.amazon.com/ses/latest/dg/receiving-email.html)
- [Amazon SES regional endpoints](https://docs.aws.amazon.com/general/latest/gr/ses.html)
- [OpenAI model catalog](https://developers.openai.com/api/docs/models)
- [European Commission controller and processor guidance](https://commission.europa.eu/law/law-topic/data-protection/rules-business-and-organisations/obligations/controllerprocessor/what-data-controller-or-data-processor_en)
- [ICO anonymisation and pseudonymisation guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-sharing/anonymisation/introduction-to-anonymisation/)
