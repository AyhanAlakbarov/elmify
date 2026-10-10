# Phased Requirements

Status: Approved design draft for review. `idea_v2.md` is the authoritative product source. This document converts the approved decisions into phased, testable requirements. It does not authorize source-code creation, Graphify or external submissions.

## 1. Product objective

Build a paid, English-language agentic platform for applicants to master's programs worldwide. Default discovery to English-taught programs and allow each student to select additional acceptable teaching languages. Serve direct students and external education agencies through one white-label, multi-tenant product. Its primary differentiator is a Funding Intelligence Engine that finds, verifies and explains strong opportunities—including hard-to-find research-linked funding. The commercial MVP delivers the complete application service through a consultant-operated concierge workflow, while the technical phases progressively replace repeated consultant work with reliable agent automation.

The later fellowships-and-events product remains a separate future service.

## 2. Product-wide rules

These requirements apply across phases:

- Support government, Erasmus Mundus and other multilateral, industrial, university, departmental, program-specific and research-ecosystem funding.
- Treat research-linked “gold” programs as one funding category, not the entire product.
- Use general aggregators only for coverage comparison and navigation to official sources.
- Support material claims with current primary sources.
- Keep direct funding, competitive funding, formal pipelines and ecosystem clues distinct.
- Never infer guaranteed master's funding solely from a nearby grant, famous lab or institutional partnership.
- Use only applicant facts stated by the student or extracted from authoritative documents supplied by the student. Verify material facts against supplied evidence where possible; otherwise require explicit student confirmation and record the fact as student-attested. Require the student to resolve conflicts or ambiguities before use.
- Keep the platform interface in English while treating teaching language as a student-configurable eligibility constraint.
- Make recommendations serve the student's declared objective and approved negotiability choices.
- Use personalized weights after non-negotiable hard gates. When the student chooses funding-first ranking because attendance depends on full funding, make verified total affordability dominant and allow eligible fully funded opportunities to rank highly despite disclosed weaknesses in soft-fit dimensions.
- Never let funding override confirmed ineligibility, an unworkable deadline or teaching-language requirement, or a student-defined non-negotiable constraint.
- Explain why each recommended university was selected.
- Record actions and evidence without storing private model chain-of-thought.
- Use maximum autonomy only inside a verified profile, approved plan and approved spending authority.
- Pause for missing facts, material changes, spending beyond authority or genuinely non-delegable personal actions.
- Treat CAPTCHA as delegable application work: consultants complete it during the MVP, while later phases may use an integrated CAPTCHA-resolution service only where lawful and permitted by portal terms, with consultant fallback when it is prohibited, unavailable or unsuccessful. Do not use unauthorized CAPTCHA circumvention.
  - Amendment 2026-09-15 (`docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md`): once portal filling runs as a browser extension in the applicant's own session, CAPTCHA is the applicant's own act, performed in their own browser at the moment it appears. No consultant completes it, no resolution service is integrated, and the service gate in this bullet lapses. Consultant completion of CAPTCHA remains only within the manual concierge MVP, which this amendment neither enables nor forbids.
- Never circumvent identity verification, personal MFA, legally binding signatures, personal attestations or other controls that specifically require the applicant.
- Treat the agency tenant as a mandatory security boundary for every student record, job, document, payment, approval and audit event.
- Keep tenant personal data out of cross-tenant training and optimization unless the later opt-in privacy pipeline is activated under an approved data-use agreement.

### 2.1 Commercial MVP operating model

- Present the complete end-to-end service to the student from the commercial MVP: discovery, application strategy, documents, applications, payments, monitoring and status visibility.
- Publish the AI-generated recommendation pool and pack to the student immediately once P1-6's gates are met, deliberately un-gated by counselor review — agents search and evaluate programs more thoroughly than manual review would, and a counselor gate would add a day of latency for a check agents already perform. Human oversight applies at the document and application-execution stages instead (§4.2.1, P1-14), not to recommendation generation.
- Keep technical delivery incremental. Phase 1 automates Funding Intelligence, recommendation control and dashboard tracking; consultants may deliver later-phase capabilities manually through approved operational procedures.
- Represent every manual or automated operation as a visible application stage with an owner, deadline and audit event.
- Use consultants initially for permitted portal applications, CAPTCHA, monitoring, low-confidence application-execution cases and other delegable work that is not yet automated.
  - Amendment 2026-09-15: the automated successor to consultant portal work is the glass-box co-pilot extension (§5.2 amendment), not an agent acting on the student's behalf. Payment execution, monitoring and low-confidence review keep this bullet's shape.
- Amendment 2026-10-03 (owner): students pay application fees themselves (Section 5.3 amendment). The platform never pays a third-party fee, so the ledger, virtual-card and refund controls no longer apply.
- Ask the student only for genuinely non-delegable identity, personal authentication, signature, attestation, new-fact, personal-decision or additional-spending actions.
- Do not accept production customers for a manually delivered capability until its security, portal-terms, payment and legal launch blockers are resolved.

## 3. Phase 1 — Funding Intelligence Core and Concierge MVP

### 3.1 Outcome

Phase 1 proves that the platform can find more high-quality funded opportunities than an aggregator-led process, evaluate them reliably and present an actionable application portfolio. It also provides the dashboard and consultant operations needed to expose the complete concierge service to pilot customers without automating every internal step.

Phase 1 technical delivery is complete when a pilot student can finish consultation, receive a recommendation pool and recommended application pack based on the student's declared objective, modify the pack through chat and view a roadmap with evidence-backed explanations. It must also prove one branded agency-owner, counselor and student workflow through an external-style custom domain without cross-tenant access. Commercial concierge launch additionally requires approved procedures and cleared launch blockers for every manually delivered service.

### 3.2 Included capabilities

#### P1-1 Consultation and progressive profile

The system shall:

- Collect academic history, grading context, target field, intended intake, language ability, acceptable teaching languages, available proficiency evidence and evidence deadlines, experience, research interests, career goals, application budget, funding dependency, program preferences, location constraints and mobility priorities.
- Ask whether the student prefers a one-year program, a two-year program or has no duration preference; whether that preference is non-negotiable or weighted; whether the primary goal is rapid industry entry, research or PhD preparation, a field change or still undecided; and which funding, internship or research advantages would justify a longer program.
- Ask only for information required at the current evaluation stage.
- Let the student classify funding as mandatory, important or optional.
- Let the student choose a balanced-fit or funding-first strategy, set non-negotiable constraints, identify negotiable preferences and define personalized evaluation priorities.
- Preserve versioned verified facts used by each recommendation run.
- Ask one targeted question when missing information blocks a criterion.

Sensitive identity and application documents are not required for initial discovery.

#### P1-2 Worldwide hybrid discovery

The system shall:

- Maintain a growing catalog of previously verified programs, funding channels and ecosystem relationships.
- Treat cached claims as research leads until revalidated for the current student and cycle.
- Run targeted live research for each student's profile rather than attempting a complete worldwide crawl before launch.
- Constrain program discovery to English and the student's explicitly selected additional teaching languages.
- Reuse newly verified findings for later students.
- Search official feeder channels including government and multilateral funding, Erasmus Mundus, industrial sponsors, universities, departments, programs, doctoral schools, research institutes, labs, grants and institutional partnerships.
- Use official APIs, RSS feeds and sitemaps when available; otherwise use targeted search and direct retrieval.
- Use browser rendering only for JavaScript-dependent pages that ordinary retrieval cannot read.
- Keep aggregators outside recommendation evidence and ranking.

Approved amendment, 2026-08-20: in Phase 1 these obligations are satisfied by an approved, access-controlled consultant procedure operating the platform's retrieval primitives, not by automated lead discovery. Phase 1 software shall provide controlled retrieval, browser rendering for JavaScript-dependent pages, source snapshotting, freshness tracking and the consultant task queue for blocked or low-confidence sources. Automated channel search, catalog gap-filling and bulk extraction are deferred to Section 7. The catalog, revalidation, language-constraint, feeder-channel, official-API-first and aggregator rules above bind both the manual procedure and its later automation.

#### P1-3 Funding classification

Every funding opportunity shall be categorized by family and evidence strength.

Funding families include:

- Government scholarships.
- Erasmus Mundus and other multilateral funding.
- Industrial sponsorships.
- University-wide scholarships.
- Departmental or program-specific support.
- Tuition waivers.
- Stipends and assistantships.
- Relocation, housing, insurance and travel support.
- Research-ecosystem programs and formal master's-to-lab pathways.

Evidence strengths are:

1. Direct program or student funding.
2. Competitive funding with explicit eligibility.
3. Formal research, employer or progression pipeline.
4. Ecosystem clue requiring deeper research.

Only the first three may appear as student-facing claims, and each must use accurate qualifiers. Ecosystem clues remain internal until upgraded by primary evidence.

#### P1-4 Official-source evidence

For every material recommendation claim, the system shall store and display as appropriate:

- Official source.
- Applicable rule or evidence.
- Deadline.
- Last-checked date.
- Tuition and application fees.
- Program duration, study intensity and documented thesis, internship, industry or research-track structure.
- A city-specific lower-end realistic student living-cost estimate, monthly and annual.
- An itemized cost basis covering housing, food, transport, utilities, insurance and other necessary local expenses.
- Applicable country- or city-specific social and student benefits, with official source, eligibility conditions, expected amount, access or capacity limits and last-checked date.
- Conditional savings and emergency-support options shown separately from the baseline.
- Funding coverage and uncovered gap.
- Required documents.
- Teaching language, required proficiency evidence and evidence deadline.
- Uncertainty and confidence.

Official sources include university, program, scholarship, government, immigration, regulator, funder, research-organization, municipal, public student-service and official statistical sources. A conflicting or ambiguous rule keeps the opportunity an internal research lead rather than a confirmed recommendation, consistent with P1-6, until revalidated evidence resolves it.

The primary displayed estimate shall use the lower end of a realistic student budget for the program's city, not an average consumer budget or an unsupported theoretical minimum. A benefit may reduce that estimate only when current primary evidence verifies its geographic scope, the student's likely eligibility and sufficiently reliable ordinary access. Capacity-limited benefits such as subsidized housing shall appear as conditional savings rather than guaranteed reductions. Food banks and emergency aid may be listed as possible support but shall not reduce the minimum viable budget or uncovered funding gap. The system shall never infer that a benefit available in one country or city exists elsewhere. Missing or conflicting local evidence shall exclude the reduction and lower confidence rather than produce an estimated benefit.

#### P1-5 Evaluation matrix

The system shall evaluate applicable dimensions covering:

- Academic and curriculum fit.
- Student goals and career alignment.
- Admission realism.
- Funding strength and total affordability.
- Post-study work rights and mobility.
- Local job-market language requirements.
- Degree portability.
- One-year versus two-year structure relative to the student's explicit duration preference and career intent.
- Thesis, internship and industry-track options.
- Pedagogy and cohort characteristics.
- Department-specific industry pipelines.
- Career-center and placement support.
- Master's-level access to research or computing facilities.
- Rolling admissions, credential evaluation, document burden and hidden fees.
- Professor, supervisor or laboratory fit only when materially applicable.

Weights shall be personalized from the student's approved strategy and consultation. A non-negotiable duration excludes programs outside the selected length; a weighted duration preference affects ranking without excluding alternatives. Under funding-first ranking, verified total affordability shall be the dominant soft-ranking dimension. Non-applicable dimensions shall be excluded and their weights redistributed explicitly.

Duration evaluation shall compare total degree cost, full-period scholarship coverage, workload intensity, time before employment, thesis or internship access, research depth and applicable post-study work conditions. The system shall not infer that every industry-oriented student wants one year or that every research-oriented student wants two years.

#### P1-6 Recommendation qualification rules

Every student recommendation shall:

- Pass every hard gate.
- Have at least medium evidence confidence.

A balanced-fit strong match shall additionally score at least `80/100` overall and at least `60/100` on every critical applicable soft-fit dimension.

A funding-first opportunity shall instead have verified funding that meets the student's required affordability threshold. It has no universal minimum for an individual soft-fit dimension and may rank above a better-fit unaffordable program. The system shall disclose each material weakness and state that the recommendation is prioritized because it is financially viable for the student's declared objective.

Hard gates include:

- Master's degree taught in English or another teaching language explicitly selected by the student.
- A viable path to satisfy the program's required teaching-language evidence by the applicable deadline.
- No confirmed eligibility failure.
- Viable deadline.
- Adequate official evidence.
- Student non-negotiable constraints.
- A viable verified funding route when funding is mandatory.

Ambiguous opportunities may remain internal research leads but cannot be published as confirmed student recommendations.

#### P1-7 Recommendation pool and recommended pack

The dashboard shall show:

- A broader pool containing balanced-fit strong matches and, when the student chooses that strategy, eligible funding-first opportunities.
- A highlighted recommended application pack optimized for the student's budget, funding requirement, fees, deadlines and portfolio balance.
- When funding-first mode is active, every verified fully funded, application-fee-free opportunity that passes the student's hard gates, even when it has disclosed soft-fit weaknesses or does not consume application budget.
- Paid applications in priority order until reaching the student's approved budget.
- A concise explanation of fit, weaknesses, uncertainties, funding and costs, and how the program serves the student's declared objective. Per the P1-7.1 amendment of 2026-08-28, the explanation is evidence-backed. Amendment, 2026-10-04 (owner, `docs/superpowers/specs/2026-10-04-student-dashboard-design.md` §5): the dashboard's programme and funding pages show each item's official source link and its last-checked date, `https` links only; the student-facing report keeps the 2026-08-28 rule.

Confirmed-ineligible, closed, unaffordable-under-the-selected-strategy or materially unverified candidates shall not appear as ordinary student recommendations. A weaker-fit fully funded opportunity may appear only when funding-first ranking reflects the student's declared objective. Internal reviewers may inspect excluded candidates.

#### P1-7.1 Paid Consultation Recommendation Report

After the consultation fee is paid, the system shall give the student an agency-branded, downloadable Consultation Recommendation Report even if the student does not purchase the full application service.

The report shall include:

- The student's approved goals, priorities, constraints and material assumptions used for matching.
- Every university, program and funding route in the highlighted recommended application pack.
- Why each program was selected, including academic, program, career, duration and relevant personal-fit analysis.
- Funding type and coverage, city-specific lower-end realistic living costs, uncovered gap, application fees and total application budget.
- Application priority, deadlines, mobility, post-study work, local-language and degree-portability considerations.
- Material weaknesses, admission risks, uncertainties, conditional benefits and recommended next actions.
- Last-checked dates and the exact report and pack version identifiers.

Amendment, 2026-08-28 (user-directed): **official source URLs are internal-only and shall not appear in the student-facing report.** "Internal" here means the platform and the tenant's counselors, who continue to see source snapshots, extracted claims, conflicts and confidence under Section 3.2; it does not extend to the student by default. Last-checked dates remain in the report, because a fact's age is a property of the advice rather than a disclosure of where it came from.

The change was made to reduce the platform's exposure under source licences, which constrain redistribution rather than retrieval. It is also a deliberate positioning choice: routine source display was the visible difference between this service and a conventional education agency, and the service now competes on the correctness of its advice rather than on the student's ability to verify it.

Everything the evidence chain exists for other than routine display is unchanged and remains required:

- **On request or in dispute**, the platform shall be able to produce the official source, its retrieval timestamp and its stored snapshot for any claim it has made. Withholding a source by default is not the same as being unable to produce one.
- Freshness windows per claim class (Section 7.1) continue to govern what may be served, because that is a correctness rule and not a citation rule.
- The application audit dossier (P1-14) continues to retain detailed evidence per application.
- Cross-tenant reuse of verified findings (Section 7.2) continues to require provenance on every claim.

The report shall exclude internal research leads and private model chain-of-thought. It shall be a timestamped snapshot rather than a promise that evidence, admission or funding will remain unchanged. It is a pre-application recommendation deliverable and is distinct from the application audit dossier in P1-14. The final visual design, downloadable format and whether to provide an additional interactive web version remain later design decisions.

#### P1-8 Student control through chat

The student shall be able to:

- Reject a recommended program.
- Replace it with another program from the recommendation pool.
- Ask the platform to consider a named program, including an Erasmus Mundus program.
- See the pack's updated application-fee total.

A named program shall appear immediately with a `Checking` state. It may enter the application pack after eligibility, fit, funding, deadline and fee checks. A confirmed ineligible or closed program remains visible with the reason and is not treated as an application candidate.

Amendment, 2026-08-21 (user-directed): those checks shall be performed automatically, without counselor review, so that naming a program is ungated for the student in the same way rejecting and replacing are. Until they complete, the candidate's placeholder source shall never be displayed as a verified official-source citation, and the candidate shall remain outside every pack version. Because a named program is a catalog miss and therefore the one student action with unbounded marginal research cost, the system shall apply a per-student rate limit to it.

Rejected programs shall remain in decision history so they are not recommended again accidentally.

#### P1-9 Roadmap dashboard

**Amendment 2026-10-03 (owner):** the first dashboard is plain, unstyled HTML, built only so every feature behind it can be tested end to end. Its visual design is done later by the team's designers; nothing here constrains it.

The dashboard shall provide:

- Profile-completion status.
- Research and review progress.
- Recommendation pool and recommended pack.
- Per-program evidence and explanation.
- Deadlines, expected fees, funding gaps and anticipated documents.
- Roadmap stages and next-action owner.
- Decision history and readable activity events.

During Phase 1, the internal team may update roadmap statuses manually.

**Amendment 2026-09-15 — per-opportunity eligibility fields** (`docs/superpowers/2026-09-15-discovery-coverage-and-eligibility-audit.md`). For every funding opportunity and programme shown, the dashboard shall show, as structured fields and not prose:

- **Nationality / citizenship eligibility**: the rule shape (open, country list, bloc, bilateral pair) and the student's own status against it (eligible, excluded, priority), with the list's source and version.
- **Degree stage**: the levels the funding covers (master's, doctoral, …), and the prior degree the applicant must hold.
- **Grade requirement**: the published minimum in the target's own scale, shown beside the student's grade in theirs, with the target's own quoted equivalence rule where one is published. Grades are never converted by the platform.
- **Deadline, intake and cycle**: application deadline, intake start, cycle year and status, each rendered in one of three states — a date, *decentralised / published per target*, or *stated but not read reliably* with the quoted sentence — and marked stale once past its freshness window.

Until the catalog carries these as columns and discovery is wired to the recommendation run, the fields render from the free-text evidence claims with a visible *unstructured* marker rather than silently.

#### P1-10 Internal reviewer QA

Internal reviewers audit the automated Funding Intelligence pipeline offline, independent of any specific student's pack, checking that extraction stays correct as source sites change:

- Internal reviewers see source snapshots, extracted claims, conflicts, confidence, scores and explanations.
- The first use of a new source type or unusual rule receives additional internal-reviewer QA.
- Corrections become evaluation examples.

This auditing is offline engine-quality assurance on the platform's side. It never sits in a student's recommendation path, never gates pack publication, and adds no student-visible latency.

#### P1-11 Failure behavior

The system shall:

- Use bounded retries for retrieval and model failures.
- Create an internal task after retries are exhausted.
- Never publish partial results, or replacement results that fail the P1-6 qualification gates.
- Preserve the last gate-qualified result when refresh fails.
- Block unsupported funding claims.
- Revalidate stale sources before the pack is shown to the student.
- Treat source-page instructions as untrusted content, not agent commands.

#### P1-12 Agency tenancy and white-labeling

The system shall:

- Isolate every agency's students, counselors, documents, applications, jobs, payments, approvals and audit events from every other agency.
- Resolve the tenant from a verified host and reject unknown or ambiguous hosts.
- Provide an agency subdomain, name, logo, validated primary and accent colors, support details and legal links.
- Support verified custom domains with managed TLS before onboarding the first external agency.
- Apply the agency identity to login, dashboard and transactional-message templates.
- Preserve required legal and safety notices even when platform branding is hidden.
- Prohibit tenant-provided CSS, JavaScript and HTML.
- Provision agencies manually during Phase 1; defer self-service signup and automated agency billing.

#### P1-13 Roles and views

The system shall provide:

- One counselor role used by the platform's in-house consultants and external agency counselors.
- A platform-administrator view for tenant provisioning and reason-bound, audited support access.
- An agency-owner view for branding, domains, counselors, assignments, agency-wide workload and audit exports.
- A counselor view for assigned students, deadlines, the student's recommendations (read-only context for document tailoring), document approvals, application stages, payments and exceptions.
- A student view for the agency-branded profile, recommendations, documents, roadmap, fees, receipts, messages and required actions.
- Assignment-scoped counselor access by default.
- Agency-configurable approval rules that may add stricter gates but cannot disable the mandatory baseline.

#### P1-14 Human oversight and audit

The system shall:

- Require counselor approval for every CV/SOP/motivation-letter version used in an application, the first application on each new portal, and low-confidence or ambiguous application-execution decisions.
- Require renewed student authorization for spending beyond the approved limit or a new non-delegable declaration; counselor approval cannot substitute for it.
- Record every automated, counselor, student and platform-administrator action as an append-only audit event.
- Include tenant, student, application, actor, timestamp, action, result, affected object versions, confidence or escalation reason, approval requirement and approval decision where applicable.
- Record platform support access with the administrator, reason, tenant, scope, start and end time.
- Provide readable student timelines and detailed agency audit exports.
- Produce an agency-branded application dossier containing approved facts, document history, counselor reviews, student actions, portal actions, submissions, payments, refunds and failures.
- Create corrections as new events rather than rewriting history.
- Exclude private model chain-of-thought, passwords, raw card data and unnecessary document content from audit records.

#### P1-15 Tenant data boundary

The system shall:

- Keep agency student data, counselor notes, outcomes, documents and proprietary workflows isolated from other tenants.
- Treat official program, funding and research-ecosystem evidence as shared platform intelligence.
- Provide agency and student access, correction, export and deletion workflows subject to applicable retention duties.
- Record the agency data-use agreement version, permitted purposes, eligible categories and revocation state needed by the later opt-in pipeline.
- Prohibit model training on raw tenant databases and cross-tenant reuse of personal data by default.
- Require a separate approved agreement and applicable lawful basis before any tenant record becomes eligible for later platform-intelligence processing.
- Define tenant export and deletion behavior when an agency relationship ends.

### 3.3 Phase 1 technical requirements

- Python and Django for the web application and internal tools.
- One Python research worker.
- PostgreSQL for relational product and Funding Intelligence data.
- S3 for official-source snapshots.
- One Standard SQS research queue and one dead-letter queue; every research message shall include a validated `tenant_id` and use the same value as `MessageGroupId` for fair scheduling.
- AWS ECS/Fargate in one region.
- OpenAI Responses API with Luna for bulk extraction, Terra for recommendation reasoning and Sol for difficult exceptions. An internal reviewer (not a counselor) is a QA fallback only when model-tier escalation itself fails, auditing offline; this fallback never blocks or delays the student's pack.
- Deterministic code for gates, arithmetic, thresholds and final scoring. Approved amendment, 2026-08-14: "final scoring" means the weighted sum, the threshold comparisons and the final ordering, all of which remain deterministic. The reasoning model may supply qualitative dimension judgements as inputs to that arithmetic, emitted as anchored rubric levels with cited excerpts rather than as numbers. The model shall not compute or influence money, eligibility, weights, thresholds or ordering.
- Fail-closed application and ORM tenant scoping for requests, background jobs, administrator actions and exports from the first migration.
- Tenant identifiers and tenant-aware database uniqueness and foreign-key constraints for every tenant-owned relationship.
- PostgreSQL row-level security only as a secondary default-deny safeguard, never as the primary tenant-context mechanism.
- No graph database, vector database, Redis, Kubernetes or microservices.

### 3.4 Phase 1 security requirements

- Encrypt network traffic and stored data.
- Keep RDS and S3 private.
- Store secrets in managed secret storage.
- Apply least-privilege runtime roles.
- Require multi-factor authentication for platform administrators.
- Verify student personal email.
- Prevent cross-student data access.
- Prevent cross-tenant data access in requests, administrator actions, background jobs, exports, object storage and cache keys.
- Establish tenant context from the verified host and authenticated agency membership before tenant-owned ORM access; reject missing, invalid or conflicting context rather than executing an unscoped query.
- Prohibit connection-scoped PostgreSQL tenant settings on persistent or pooled connections. Any RLS tenant setting shall use transaction-scoped `SET LOCAL`, expire on commit or rollback and deny access when absent.
- Ensure runtime database roles neither own RLS-protected tables nor have `BYPASSRLS`; privileged cross-tenant operations require a separate least-privilege, reason-bound and audited path.
- Require multi-factor authentication for agency owners and counselors.
- Make platform support access time-limited, reason-bound and auditable.
- Keep secrets and unnecessary student content out of logs.
- Validate outbound research URLs and block private-network targets.
- Route worker traffic through controlled, auditable egress; apply caching, per-domain rate limits, bounded concurrency and exponential backoff.
- Permit a fixed proxy or data provider only after security, legal and source-terms approval. Prohibit rotating or residential proxies, fingerprint evasion and bypassing IP or anti-bot blocks; escalate blocked compliant retrieval to a consultant.
- Escape retrieved source content before display.
- Provide pilot-data export and deletion handling.
- Test backup restoration before the shadow pilot.
- Malware-scan student documents and isolate tenant object-storage prefixes.

### 3.5 Phase 1 validation

Validation uses three layers:

1. An independent researcher creates reference opportunity lists for five representative profiles without seeing AI results.
2. An internal reviewer reviews every recommendation for at least 20 diverse profiles.
3. Five to ten real students use AI-generated packs in a shadow pilot; the founder reviews and comments on pack quality as evaluation input, not as a publication gate.

The MVP acceptance gates are:

- At least `90%` precision for published student recommendations across both ranking modes.
- At least `80%` recall on the independent five-profile benchmark.
- `100%` official-source support for material claims.
- Zero unsupported funding claims.
- At least `20%` more verified funded recommendations than an aggregator-only baseline.
- No unresolved critical security, data-loss or cross-account-access failures.
- Zero cross-tenant access in authorization, background-job and export tests, including missing-context and sequential reused-connection cases.
- Producer integration tests confirm every research message type sets `MessageGroupId` to its validated `tenant_id`; a two-tenant burst test confirms quiet-tenant messages remain serviceable and emits the SQS fair-queue metrics.
- Controlled-egress tests confirm per-domain limits and backoff, private-network blocking and consultant escalation without an evasive proxy fallback.
- `100%` of mandatory counselor approvals linked to the exact approved object version and audit event.
- One verified external-style agency domain resolves the correct branding and roles, while an unknown host is rejected before data access.
- One exported application dossier proves the human approvals and automated actions for a pilot workflow.
- One paid pilot consultation produces an agency-branded, downloadable, versioned Consultation Recommendation Report tied to the paid pack version, containing every required section and no internal research leads.
- One benchmark profile with an explicitly selected non-English teaching language returns only programs whose language-evidence requirement is viable.
- One funding-dependent benchmark profile ranks an eligible fully funded program above a better-fit unaffordable program, preserves every student non-negotiable and explains the fit trade-off.
- A five-city affordability benchmark confirms that each primary estimate is plausible for a frugal student, every deducted benefit has current location-specific primary evidence and likely student eligibility, no benefit is transferred between cities or countries, and no capacity-limited or emergency support reduces the baseline.
- A paired duration benchmark ranks a suitable funded one-year program higher for a student prioritizing rapid industry entry, while ranking a thesis- or research-intensive two-year program higher for a student prioritizing research preparation; both results must follow the student's declared flexibility and explain the trade-off.

Real admission and scholarship outcomes shall be tracked later but do not delay the Phase 1 MVP for an admissions cycle.

## 4. Phase 2 — Application materials and communication foundation

Phase 2 begins only after Phase 1 recommendation-quality gates pass. It automates document and communication work that consultants may already provide in the commercial concierge service.

### 4.1 CV engine

- Maintain a verified base profile of education, experience, achievements, skills and goals.
- Produce one primary CV.
- Produce a Europass variant when required for an approved Erasmus Mundus application.
- Explain major changes and preserve factual consistency.
- Allow two student-requested style or structure revision rounds.
- Allow unlimited corrections of objectively wrong facts.

### 4.2 Motivation-letter engine

- Maintain an approved core narrative.
- Allow two student-requested style or structure revision rounds for the core narrative.
- Allow unlimited corrections of objectively wrong facts.
- Cluster genuinely similar programs by discipline, goals and prompt requirements.
- Reuse the core narrative and regenerate only program-specific sections when appropriate.
- Fully regenerate when the prompt, discipline, scholarship or program expectations materially differ.
- Tailor curriculum, research fit, goals, institution evidence and scholarship rationale.
- Check wrong institution names, factual contradictions and unsupported claims before use.
- Optimize for clarity, machine readability and relevance without fabricating qualifications or promising to manipulate admissions systems.

### 4.2.1 Counselor document review

- Show the generated CV, SOP or motivation letter on the left and verified facts and source documents on the right.
- Highlight grades, dates, projects, employment and research claims with links to the supporting source.
- Use a stable color or key for each source document across the draft highlights and fact overlay.
- Mark each material claim as supported, conflicting, unsupported or uncertain.
- Flag chronology conflicts, quantitative mismatches, wrong institution names, missing prompt requirements and distinctive unsupported claims.
- Let the counselor approve, quick-edit or request an inline AI revision.
- Show a focused diff after every manual or AI change and rerun the fact checks.
- Block application use while a blocking red flag remains unresolved.
- Allow a documented counselor override only for non-blocking warnings.
- Invalidate approval whenever the approved document changes.
- Store the exact approved version, source references, checks, counselor, timestamp and decision in the audit history.

Amendment, 2026-08-23. A draft carrying no blocking red flag and no warning is approved automatically on the student's acceptance and becomes usable without counselor review; the counselor queue holds flagged drafts only. Facts stated by the student are accepted on the student's attestation, recorded with a timestamp, and used immediately — counselors do not verify facts. The student is told at intake and in the terms that they are responsible for the truth of facts they assert and that funders treat false claims as fraud. The blocks on fabricated (model-invented) claims, wrong institution names and binding format limits are unchanged. See `docs/superpowers/specs/2026-08-22-phase2-motivation-letter-engine-design.md`, settled decisions 8–9.

### 4.2.2 Direct-only standalone document services

After the Phase 2 document engines and counselor-review controls pass their evaluations, the company may sell the following separately charged services directly to master's applicants:

- CV Polish, improving an existing CV's structure, clarity, wording, formatting and machine readability.
- A tailored motivation letter for any master's program, including a program outside the platform's recommendation catalog, after obtaining and verifying its official program information and application prompt.
- An optional bundle containing both services.

These standalone orders shall:

- Require neither a paid consultation nor program discovery, application management, monitoring or dashboard enrollment beyond the document workflow.
- Use only verified applicant facts and the same fact overlay, red-flag checks, counselor approval, version history, two style or structure revision rounds and unlimited factual corrections required by Sections 4.1, 4.2 and 4.2.1.
- Offer a Europass CV variant when the target application requires it.
- Avoid fabricated qualifications, admission guarantees and claims that the service can manipulate admissions systems.
- Remain separate charges for standalone customers while remaining included, without a duplicate charge, for end-to-end platform customers.
- Be sold only through the company's direct-to-consumer channel. Agency tenants shall receive and resell only the end-to-end pipeline platform and shall not expose the standalone storefront or standalone product catalog.

### 4.2.3 Generated document output hygiene

Amendment, 2026-08-21. Applies to every document the platform generates under Sections 4.1 and 4.2, and to the standalone services in Section 4.2.2.

The platform shall:

- Strip toolchain and authoring metadata from every generated PDF and DOCX before release, including `Producer`, `Creator`, `Author`, XMP packets, editing history and application fingerprints, leaving only the fields the tenant or the target application requires.
- Normalise generated and extracted text before rendering: remove zero-width, control and other non-printing characters; normalise quotation marks, apostrophes and dashes to their intended forms; and repair encoding artifacts introduced by document extraction.
- Treat both as document-quality requirements rather than optional post-processing. Leaked toolchain metadata undermines an agency tenant's white-label identity, and non-printing characters corrupt text extraction on the receiving side — the same extraction the platform depends on being clean elsewhere.

This section permits metadata, text hygiene, not removing, not obscuring and not defeating signals indicating that a document was produced with AI assistance

Standalone prices, bundle discounts, turnaround commitments and public-page design remain later commercial decisions. Phase 2 validation shall complete one CV-only order, one motivation-letter-only order for a master's outside the recommendation catalog and one bundle through the direct channel, while proving that an agency tenant cannot access or publish these products.

### 4.3 Dedicated application email

- Create one real platform-domain email address per student.
- Provide its inbox inside the dashboard.
- Use the address for later portal accounts, applications and communications.
- Keep the address platform-managed throughout the service.
- Use Amazon SES or an equivalent approved mail transport; do not depend on Amazon WorkMail.

**Amendment 2026-09-15 — §4.3 is superseded** (`docs/superpowers/specs/2026-09-15-student-owned-mailbox-design.md`). No platform-domain, disposable or proxy address is created per student. Instead:

- The student connects the mailbox they already use (Gmail, Outlook.com, or a university Google Workspace / Microsoft 365 account) through OAuth with the smallest scope that does the job.
- Default access is **metadata only** (headers — sender, subject, date — and labels). Reading message bodies and attachments is a separate, per-student opt-in.
- The platform reads only messages whose sender belongs to an institution, funder or portal in the student's own approved pack; that filter is derived from the pack and shown to the student.
- The platform holds no send scope and never sends as the student.
- The address the student applies with is the connected mailbox address or, without a connection, an address the student declares and confirms once. A student with no connected mailbox reports status and uploads decision letters through the dashboard.
- Refresh tokens are stored in the secret store, never in the database, and are destroyed on erasure.
- SES (or equivalent) remains for outbound notifications to the student under §4.5 only.

### 4.4 AI email handling

- Read and classify application-related messages automatically.
- Answer routine messages using verified information.
- Provide existing approved documents and update roadmap status.
- Ask the student only for new facts, personal choices, interview availability, additional spending or legally significant commitments.
- Never invent an answer.

**Amendment 2026-09-15:** reading and classification require the content tier of the §4.3 amendment and operate only on pack-filtered messages. "Answer routine messages" becomes **draft** routine replies from verified information and approved documents; the student sends every reply from their own mail client. Attachments such as decision letters are saved only when the student chooses to save them.

### 4.5 Notifications

- Provide a dashboard notification center.
- Send alerts to the student's personal email.
- Repeat urgent reminders for missing documents, deadlines, interviews, additional payments or required personal action until acknowledged.
- Defer WhatsApp and native mobile push until usage demonstrates need.
  - Amendment 2026-09-15: the deadline reminder ladder is 14 days, 7 days, 3 days, 1 day and 6 hours before each application deadline, automatic, on the dashboard and by notification mail, stopping the moment the application is submitted. At 3 days a counselor task opens as well. Deadlines are stored in the portal's time zone and shown in the student's; reminders respect the student's quiet hours.

## 5. Phase 3 — Autonomous application execution and monitoring

Phase 3 begins after document and communication workflows meet their evaluations. It progressively moves normal application execution from consultants to the agent while retaining a consultant exception desk.

### 5.1 Authority model

- The student approves verified facts and the application pack once.
- The student shall select a submission authority for the engagement: `counselor-submit`, in which the platform performs each submission within the student's one-time authority, or `student-submit`, in which the platform prepares each application to a ready-to-submit state and the student performs the submission after reviewing it. The student may change the setting while applications remain unsubmitted.
- The agent may then prepare, communicate, complete and monitor applications within that authority, and may submit them when `counselor-submit` is selected.
- The two modes differ only in who performs the submission. Counselor approval under P1-14 of every CV, statement-of-purpose and motivation-letter version binds identically in both, and the mode setting shall never weaken it.
- Under `student-submit`, the student shall authorize at mode selection that any application still unsubmitted 48 hours before its deadline is submitted on the student's behalf under the same one-time pack and spending authority. The authorization is granted once, with the mode, recorded as an approval event, and the student is notified when it triggers. A student who declines it shall be told plainly that applications left unsubmitted at their deadline will not be submitted.
- The agent pauses for missing or changed facts, spending beyond the cap or a provider-required personal action.
- Rare identity-verification, legally binding signature, personal attestation and bank-authentication steps remain student-operated in both submission modes. Neither mode implies the student is uninvolved, and no surface shall present `counselor-submit` as requiring nothing of the student.
- During the MVP, a consultant completes CAPTCHA in the preserved session when delegated portal access is permitted. In later phases, the platform may use an integrated CAPTCHA-resolution service only after the portal-terms and legal gates approve it; otherwise, or when resolution fails, the preserved session is assigned to a consultant.
- The student receives a low-friction, specific handoff task only for genuinely non-delegable personal actions.

**Amendment 2026-09-15 — one submission mode** (`docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md`). Portal filling runs as a browser extension inside the student's own authenticated session, so the platform has no path that could submit an application and none is planned. Consequently:

- `counselor-submit` is withdrawn. The only mode is `student-submit`: the platform prepares each application to ready-to-submit in the student's own portal tab and the student performs the submission.
- The 48-hours-before-deadline automatic submission authorization is withdrawn; nothing can act on it. The deadline safety net is §4.5's repeated reminders until acknowledged, a counselor outreach task for any application still unsubmitted 72 hours before its deadline, and an explicit *unsubmitted at deadline* outcome on the roadmap. A student is told plainly at pack approval that applications they do not submit are not submitted.
- CAPTCHA, applicant MFA, attestations and signatures are the student's own acts in their own browser as they appear; the "preserved session assigned to a consultant" mechanism and the CAPTCHA-resolution service gate lapse.
- P1-14 counselor approval of every document version is unchanged.

### 5.2 Portal execution

- Use browser automation that tolerates ordinary layout and selector changes.
- Validate every prepared form against the verified profile and approved documents.
- Detect CAPTCHA explicitly. During the MVP, create a scoped consultant task in the preserved session. In later phases, invoke the configured resolution service only for approved portals and fall back to the same consultant task without losing completed form state.
- Require consultant review for the first prepared application on each new portal during the early Phase 3 rollout.
- Detect site changes and create review tasks rather than guessing.
- Record portal confirmations and recoverable failure states.
- When automation cannot proceed, preserve the authenticated browser session, pause agent input and create a scoped consultant task for the relevant portal tab. Create a student task instead only when the action cannot be delegated.
- Show the institution, required action, owner, deadline and expected duration on the student dashboard; notify the assigned consultant or student through the appropriate channel.
- Detect completion of the action and resume automatically without repeating completed application steps.
- If a portal session expires, first attempt normal reauthentication with platform-managed credentials. Route reauthentication to a consultant, requesting student action only for personal authentication such as applicant-specific MFA.
- After reauthentication, recover the existing application by its portal identifier, compare it with the last verified application snapshot and resume from the last confirmed step.
- Repopulate a lost draft from the verified snapshot only after checking that doing so will not create a duplicate application.

**Amendment 2026-09-15 — the glass-box co-pilot replaces server-side portal execution** (`docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md`). The bullets above describe an agent operating a platform-run browser with platform-managed credentials; that design is retired. In its place:

- The dashboard prepares a **fill packet** for each application from the verified profile and approved documents, after the same missing-fact check as before. A browser extension paired invisibly to the student's dashboard session opens the portal in a visible tab, in which the student is already logged in, and populates the form field by field while the student watches a progress dock.
- **The extension types; the student clicks.** It performs only value-setting actions (fill, type, select, attach a file) from a stored field map. It never clicks navigation, consent or submit controls. Multi-step forms advance on the student's click and are filled step by step.
- Approved documents are attached to the portal's file inputs by the extension from the dashboard's existing authenticated download route; no public or presigned link is created.
- Read-back against the rendered page remains and is reported to the dashboard; a mismatch is shown to the student and creates a counselor review task, never a retry.
- Site changes are handled by re-learning the field map from a value-free snapshot of the form sent to the platform; the model call runs on the platform, never in the browser.
- CAPTCHA, MFA, attestation and signature steps are detected and handed to the student in the dock as they appear; no session is preserved for anyone else, and no platform-managed credentials exist.
- Submission is the student's click. The extension records the confirmation page as evidence and moves the application to *submitted*; *confirmed* follows a portal confirmation or a connected-mailbox signal (§4.3 amendment).
- The first prepared application on each new portal still receives counselor review — of the field map and packet, before the student launches.
- Fills occur only while the student is present, in a Chromium-family desktop browser; the dashboard says so where that is not the case.
- Beneath the extension sits the **Application Kit**: for every application, the portal's questions in the portal's order with the platform's answers, the approved document per requirement, the registration address, the deadline and the status, readable and copyable on any device. The extension applies the kit; where it cannot act, the student applies the kit by hand and nothing is lost.
- Installing and pairing the extension is a required onboarding step for automated filling: the dashboard detects the extension, pairs it to the student's account silently, shows the connection and a revoke control, and the extension refuses to fill unpaired or paired to another account.
- Verification links a portal sends to the connected mailbox are opened automatically by the extension in the student's own browser (default on, per-student switch); verification codes are shown and typed. Portal status pages the student opens are read by the extension to update the application's card.
- Between form pages the student presses Next; the extension fills each page as it appears. Only value-setting actions are ever performed by the extension.
- For agency tenants, an owner-enabled counselor mode lets counselors prepare kits for their students; a counselor filling inside a student's own portal account is permitted only where the agency owner has accepted that portal's recorded terms posture, because the portal terms sampled on 2026-09-15 prohibit credential sharing while none prohibits autofill in the applicant's own session.

### 5.3 Application fees

**Amendment 2026-10-03 (owner): the student pays every application fee.** The student pays each university or scholarship application fee directly, in their own portal session, with their own payment method. The platform never collects, holds or pays a third-party fee, so there is no student-funds ledger, no virtual card and no refund handling. This follows from the glass-box co-pilot (§5.2 amendment): only the student acts inside their own portal session. The bullets this replaces (consultant-paid fees, per-student ledger, virtual cards, refund crediting) are retired.

- Show each application's expected fee, currency and payment deadline before the student commits to applying, and the pack's total expected fees.
- The extension never fills or submits a payment form; payment fields are left to the student.
- Record whether a fee was paid as a student-reported step on the application, so the budget view and reminders stay correct.
- Charge the platform fee separately; application fees are never platform revenue.

Fee-free applications proceed without a payment task. The dashboard shows the verified fee, currency, payment status and receipt for every paid application.

### 5.4 Consultant exception desk

Consultants handle:

- CAPTCHA fallback and permitted human-verification challenges that the configured service cannot or may not resolve.
- First use of a new or materially changed portal.
- Ambiguous questions and low-confidence agent decisions.
- Submission inconsistencies and recovery cases.

**Amendment 2026-09-15:** CAPTCHA fallback, human-verification challenges and portal reauthentication leave this list — the student performs them in their own session (§5.2 amendment). The desk keeps first use of a new portal (field-map review), ambiguous questions and low-confidence decisions, payment exceptions, and read-back mismatches. The autonomy target is restated as: fewer than `10%` of prepared applications requiring counselor intervention, with student portal action being the design, not an exception to count.

Consultant access is assignment-scoped and audited. The long-term operating target is at least `90%` autonomous application steps, fewer than `10%` requiring consultant intervention and fewer than `2%` requiring student portal action.

### 5.5 Application audit trail

Each application shall retain a readable timeline and detailed evidence covering:

- Recommendation and selection.
- Profile and document versions used.
- Form answers and uploaded documents.
- Agent and consultant actions.
- Messages.
- Fees, receipts and refunds.
- Submission time and confirmation.
- Failures, retries and later status changes.

The system records actions and evidence, not private model chain-of-thought.

### 5.6 Monitoring and document requests

- Monitor the platform-managed mailbox and permitted portal status.
- Notify the student when a new fact, document or personal action is required.
- Let the student upload a requested document once through the dashboard.
- Verify the document's intended application before uploading it to the relevant portal.
- Create a specific student or consultant task when automation cannot continue.

**Amendment 2026-09-15:** "the platform-managed mailbox" reads as the student's connected mailbox within the pack-derived sender filter (§4.3 amendment). A requested document uploaded once through the dashboard is attached to the relevant portal by the extension in the student's own session (§5.2 amendment), after the dashboard verifies its intended application.

## 6. Phase 4 — Operational hardening

**Amendment 2026-10-03 (owner):** interview guidance, interview preparation and mock interviews are removed from the requirements. Reminders about interview invitations an institution sends (§5) stay.

- Use real outcome data to recalibrate recommendation weights and explanations without treating admission outcomes as a pure measure of program fit.
- Move from universal counselor document review to exception-based document review only after measured reliability supports the change.
- Add higher availability, scaling and additional notification channels when usage requires them.

### 6.1 Opt-in platform-intelligence pipeline

This later-phase capability may launch only after privacy and legal review. Phase 1 stores only the agency data-use agreement version, permitted purposes, eligible categories, revocation state and source lineage needed to avoid a future migration.

The later pipeline shall:

- Trigger asynchronously only for an agency with an active, explicit platform-intelligence agreement and an applicable lawful basis for the eligible records.
- Extract an allowlisted minimum feature set inside the tenant boundary rather than copying raw tenant databases.
- Cover in that allowlist, at minimum: the prior degree title, with its level and field; the awarding institution by name; the grade point average as awarded together with the grading scale it was awarded on; the language test result; extracurricular and leadership involvement as counts by category; prior fellowships and awards as counts by tier; the programme applied to and its intake year; the admission outcome; and the funding outcome with an award band.
- Store a grade as awarded and never as a converted value. Conversion between grading systems is one-way and lossy, a German 1.0 to 5.0 scale being inverted against a 4.0 scale and a British classification being neither, so a normalized figure can always be derived later from the awarded grade and scale while the awarded grade can never be recovered from a normalization. Banding and normalization are modelling decisions, taken when the data exists.
- Treat this allowlist as provisional until it has been tested against real data. It is a starting point recorded before the pipeline is built, not a conclusion; which features carry signal is a question for analysis on an actual corpus, and revising it is expected rather than exceptional.
- Maintain that allowlist in two variants. A detailed variant may carry finer values and free-text-derived structure, remains inside the tenant, and is deleted when its student is erased. A generalized variant may survive a student erasure once its schema has passed the assessment below. Neither variant shall carry curriculum-vitae entries as text: a named society, post or award is an identifier, and only its count and category may be extracted.
- Suppress rather than generalize the institution name and the degree title. Both are retained at full precision when a row's combination meets the threshold, and the whole row is omitted from the surviving variant when it does not. Neither field shall be approximated: a row carries the exact institution and exact degree title, or the row does not exist. A row coarsened to a country and a ranking tier has little value to a model keyed on institution identity, so the information suppression forgoes is information generalization would not have preserved.
- Band the remaining quasi-identifiers before applying the threshold, deriving those bands from the awarded values rather than storing them in their place. Coarsening collapses distinct combinations and is what raises a row above the threshold while its institution and degree title stay exact; the bands are the budget that buys that precision, not a separate loss.
- Apply the threshold against the corpus as it stands when the row is produced, and do not re-derive a surviving row from a detailed row that has since been erased. A record extracted early is more likely to be suppressed than one extracted at scale, which is a consequence of the threshold rather than a defect.
- Extract only records carrying a resolved application outcome, admission and funding decisions in both directions, and exclude records that never reached one. The models estimate admission probability, so positive and negative outcomes are both required; a record with no outcome carries no signal and its retention is not a minimum feature set.
- Record that outcome first. As of 2026-09-10 no model in the system holds one: `portals.Application.State` ends at `CONFIRMED`, which means the portal accepted the submission rather than the institution accepted the applicant, and `funding.StudentDecision` records a student rejecting a recommendation rather than an institution's decision. Terminal admission states, a funding award result and the date each was learned are a prerequisite for this entire pipeline, and shall be added to the application data model before any extraction is built.
- Prefer structured features and document structure over complete CV or SOP text.
- Combine deterministic identifier rules with NER detection, quasi-identifier generalization and suppression of rare combinations.
- Use random cohort-scoped tokens or keyed pseudonyms with keys isolated from the derived dataset; predictable hashes are prohibited.
- Treat free text, embeddings and pseudonymous records as potentially personal data.
- Quarantine candidate datasets until automated PII scans, re-identification-risk tests and human privacy approval pass.
- Promote only approved datasets into a centralized, platform-owned intelligence data lake with purpose-limited access. A promoted dataset shall carry no pseudonym, token or other column linking a row to the tenant record it derives from; promotion is where that link is destroyed, for a whole cohort at once.
- Store immutable dataset manifests with agreement, transformation, source-lineage, purpose and approval versions.
- Propagate deletion and revocation through derived datasets while records remain identifiable or pseudonymous. A student erasure shall remove that student's candidate rows, unless the feature schema those rows use has passed the assessment below, in which case it shall instead destroy the pseudonym link and retain the row.
- Decouple a dataset from tenant deletion only after a documented assessment concludes that identification is no longer reasonably possible. The assessment is of the feature schema and its suppression rule, not of one dataset, so that it is performed once and holds for every extraction using that schema.
- State in that assessment a minimum cohort size below which extraction is refused, and enforce it at extraction rather than at review. No generalization makes a record non-identifying in a small population, so a schema that is safe at scale is unsafe on the same platform early.
- Bind every evaluation, optimization or fine-tuning run to approved dataset versions.
- Prohibit direct training on raw tenant databases.

Contractual platform ownership of approved datasets and model assets does not itself make the data anonymous or remove privacy obligations.

## 7. Phase 5 — Automated program discovery and catalog

Phase 5 replaces the manual consultant discovery procedure defined by the P1-2 amendment with agent execution. It begins only after the manual procedure has produced a recorded quality baseline on the Section 3.5 metrics for at least one admissions cycle; without that baseline there is nothing to prove the automation against.

This phase changes how leads are found and how retrieved pages become claims. It does not change what qualifies as evidence, how funding is classified, how packs are scored or who approves them. P1-3 through P1-7, the deterministic-scoring boundary in Section 3.3 and the tenant-isolation requirements in Section 3.4 continue to bind unchanged.

### 7.1 Progressive catalog

- Maintain the P1-2 catalog as a persistent, platform-owned store of verified programs, funding channels and ecosystem relationships.
- Serve a cached entry without live retrieval when it is within its freshness window for the requested claim class.
- Treat every cached claim as a research lead until revalidated for the current student and cycle, as P1-2 already requires.
- Define a freshness window per claim class. Tuition, deadlines, application windows and funding amounts decay faster than program existence, degree type, teaching language or institution identity.
- Dispatch background research to fill catalog gaps rather than blocking the student's request on live retrieval.
- Never admit a cached claim past its freshness window into recommendation evidence; revalidate or drop it.
- Record catalog coverage and cache-hit rate per discipline and country so gaps are visible rather than inferred.

### 7.2 Discovery channels

- Use official APIs, RSS feeds and sitemaps first, as P1-2 requires.
- Use a semantic or neural search provider for lead generation only. Search results are leads, never evidence and never a source of claims.
- Constrain automated discovery to English and the student's explicitly selected additional teaching languages.
- Keep aggregators outside recommendation evidence and ranking. An aggregator may route research to an official source; it may not support a claim.
- Reuse newly verified findings for later students, subject to Section 9's separation of shared platform evidence from tenant-private data.

Open design item, 2026-08-22 — how the lead-generation search is built. Decided in principle, to be researched before Phase 5 design:

- One official search API behind a single retriever interface, rate-limited with the platform's existing `rate_limited()`, returning candidate URLs only; candidates enter the Phase 1 fetch → snapshot → extract → verify chain unchanged. Candidates evaluated so far: Tavily, Brave Search, Exa, Perplexity Search API (structured results, no model answer). Selection criteria to research: coverage of official university and funder domains outside the Anglosphere, domain/language filters, cost per 1,000 queries, terms permitting stored results.
- No deep-research or answer-synthesis agent in the product path (gpt-researcher, Perplexity `sonar-deep-research`, Jina DeepSearch and similar). They synthesise across secondary sources, which is exactly the aggregator-sourced-claim failure §7.2 forbids; the 2026-08-22 letter research recorded one such error (a coaching-blog word count attributed to a funder). Those tools stay in the research workflow where a human reads the output; the retriever abstraction is the only idea taken from them.
- Seed discovery from catalogues before search: national funder databases (DAAD, EACEA Erasmus Mundus catalogue, CampusChina, Study in Japan, Study in Korea, Campus France), university funding pages and sitemaps. Search covers the long tail, not the head.
- The search provider is a Section 3.4 egress destination: its results are untrusted data, never evidence, and must be recorded in snapshot lineage as the technique that produced the lead.

### 7.3 Content extraction

- Convert retrieved pages to text and remove navigation, scripts and boilerplate before any model input.
- Label retrieved content as untrusted data rather than instructions, constrain model output to a schema that rejects unknown fields, and cap output tokens.
- Keep the model a parser, not a calculator. It extracts facts and supplies anchored qualitative judgements with cited excerpts; it computes no money, eligibility, weights, thresholds or ordering, per the Section 3.3 amendment of 2026-08-14.
- Persist the source snapshot, its digest and the extracted text so every claim remains traceable to the exact retrieved bytes.
- Escalate a page the extractor cannot parse confidently to a consultant task rather than emitting a low-confidence claim.

### 7.4 Retrieval conduct

- Continue Section 3.4's controlled, auditable egress, outbound URL validation, private-network blocking, per-domain rate limits, bounded concurrency and exponential backoff. Scale does not relax these.
- Use browser rendering only for JavaScript-dependent pages that ordinary retrieval cannot read.
- Respect published access terms and machine-readable access controls for every source.
- Section 3.4's prohibition on fingerprint evasion and anti-bot bypass, and Section 3.6's exclusion of rotating and residential proxy infrastructure, are Phase 1 scoped. In Phase 5 the platform may use stealth retrieval, adaptive fetching or a fixed proxy for a specific source class only after security, legal and source-terms review approves that source class in writing, on the same gating pattern as the CAPTCHA-resolution service in Section 5.1.
- Absent that approval, and whenever an approved technique fails, escalate the blocked source to a consultant. A blocked source is never silently dropped.
- Record which technique retrieved each source in the snapshot lineage, so an approval later withdrawn can be traced to the claims it produced.

### 7.5 Catalog storage and search

- Section 3.3's exclusion of a vector database is Phase 1 scoped. Phase 5 may add embedding storage and vector search for catalog lookup and deduplication.
- Prefer an extension to the existing PostgreSQL instance over a separate datastore; a separate vector service requires the same justification as any new infrastructure component.
- Embeddings of official program, funding and research-ecosystem content are shared platform evidence under Section 9.
- Embeddings derived from student or tenant content are potentially personal data under Section 6.1 and shall not enter the shared catalog.
- Vector similarity may rank and deduplicate leads. It shall not establish, support or weaken a claim.

### 7.6 Cost and rate control

- Apply per-tenant and per-user rate limiting to every automated discovery and extraction path before it is enabled, using the platform's existing rate limiter.
- Enforce a bounded budget for background discovery, separate from student-triggered research, and degrade to cached results rather than exceeding it.
- Record model and retrieval cost per run so a query class that stops paying for itself is visible.

### 7.7 Validation

- Run automated discovery in shadow mode alongside the manual procedure until it meets or exceeds the manual baseline on the Section 3.5 precision, recall, official-claim-support and verified-funded-lift metrics.
- Prove that automated discovery introduces no unsupported funding claim and no aggregator-sourced claim.
- Prove that a stale cached claim cannot reach a student-facing pack.
- Keep the manual consultant procedure available as the fallback for any discipline or country where the automation has not met the baseline.

## 8. Separate future service — Fellowships and events

The fellowships-and-events product is not an extension of the master's application workflow. It receives its own discovery model, requirements, design, validation and commercial decisions only after the master's platform succeeds.

## 9. Commercial requirements

- Charge a small initial consultation fee and deliver the Consultation Recommendation Report after payment even when the student does not purchase the full application service.
- Credit that fee toward the platform fee when the student proceeds.
- The platform fee ultimately covers discovery, the recommended pack, CV restructuring, tailored motivation letters, applications, monitoring, and dashboard access.
- In Phase 2, sell CV polishing and motivation-letter writing separately only to direct-to-consumer standalone customers; do not charge end-to-end customers again for included document work.
- Restrict B2B and white-label agency sales to the end-to-end pipeline platform; agencies cannot expose or resell the standalone document services.
- Treat the service as an end-to-end engagement.
- Do not promise admission, scholarship or employment outcomes.
- Do not offer voluntary cancellation or a platform-fee refund after work begins, subject to mandatory law and remedies for service failure.
- A no-voluntary-refund policy for the platform fee cannot override mandatory law.
- Third-party application-fee balances and provider refunds remain separate from platform revenue.
- Support direct-to-student service and white-label agency sales from the same platform.
- Provision agencies manually during the MVP and defer self-service agency billing.
- Allow agencies to strengthen approval requirements but not weaken the mandatory oversight baseline.
- Keep agency-specific notes, counselor judgments, student outcomes and proprietary workflows isolated by default.
- Keep official program, funding and research-ecosystem evidence as shared platform intelligence.

## 10. Launch blockers that do not block Phase 1 implementation

Before accepting production customers or application-fee balances, resolve:

- Company registration in Azerbaijan or the United States.
- Applicable consumer, privacy, cancellation and refund law.
- Final retention, export and deletion periods.
- ~~Payment-provider support and legal treatment of held student funds, the per-student ledger and controlled virtual cards.~~ Closed 2026-10-03: students pay fees themselves (§5.3).
- Portal terms governing automated access, delegated form completion and submission.
  - Amendment 2026-09-15: with the glass-box co-pilot there is no platform access to any portal, no delegated credential and no platform submission. The question narrows to portal terms on form-completion assistance and file attachment performed in the applicant's own authenticated session, initiated by the applicant. It remains a blocker in that narrower form.
  - Sample read 2026-09-15 (universityadmissions.se, uni-assist, Studielink, TUMonline, campusfrance.org, UCAS agent terms; table in `docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md`): no portal read prohibits automated tools or autofill in the applicant's own session; all make the account personal and prohibit credential sharing; uni-assist allows representation by power of attorney and UCAS runs a sanctioned agent portal. Each portal's posture is recorded on its form record; a portal that explicitly prohibits automation is served kit-only.
- Source terms governing automated retrieval of official program and funding pages, including published access terms, machine-readable access controls and the per-source-class approval that Section 7.4 requires before any stealth or adaptive retrieval technique.
- Email-provider terms, sender reputation and production-domain configuration.
  - Amendment 2026-09-15: narrowed to outbound notification mail under §4.5. Added in its place: Google OAuth restricted-scope app verification and the annual security assessment (CASA) required before more than 100 Google users can connect a mailbox; Microsoft publisher verification; and, per university, whether its Workspace or Microsoft 365 tenant permits third-party consent (`docs/superpowers/specs/2026-09-15-student-owned-mailbox-design.md`).
- Data-processing agreements for cloud, model, email and payment providers.
  - Amendment 2026-09-15: for connected mailboxes Google and Microsoft act on the student's own grant and are not the platform's sub-processors; the platform is controller of the derived signals. Extension distribution adds the Chrome Web Store developer terms.
- Agency data-processing terms, controller/processor responsibilities, tenant termination, export and deletion procedures.
- DNS ownership, TLS provisioning and branded-email verification for each external agency domain.

## 11. Approval boundary

Approval of these requirements authorizes later implementation planning only. It does not authorize source-code creation, infrastructure deployment, Graphify, external account creation, payments, portal access or submissions.
