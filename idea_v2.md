# Scholarship Application Platform — Idea v2

Status: Approved product source. This document separates explicit statements and confirmed decisions from historical assumptions, questions, and refinements. Later confirmed decisions in this document and `phased requirements.md` supersede conflicting earlier proposals.

## 1. Explicit statements and confirmed decisions

### Product and audience

- Build a paid agentic platform for students seeking scholarships and university admission.
- Serve master's applicants only.
- Operate the platform interface in English. Default discovery to English-taught master's programs, while allowing the student to select additional acceptable teaching languages.
- Cover master's programs in every country; do not restrict discovery by geography.
- The commercial MVP is a full-service concierge application service: the student receives the end-to-end experience and sees every application stage in a polished dashboard, while consultants initially perform operations that are not yet automated.
- Keep the internal technical phases incremental: automate Funding Intelligence and the dashboard first, then progressively replace repeated consultant work with reliable agent execution.
- Serve both direct students and external education agencies through one strictly isolated multi-tenant platform.
- Let each agency present the platform under its own logo, colors, domain, legal links and support identity.
- Provide separate agency-owner, counselor, student and platform-administrator roles and views.
- Build the fellowships-and-events product as a separate service only after the master's application platform.
- The product should be a well-designed website.

### Scholarship discovery and eligibility

- Find scholarships based on each student's goals and preferences.
- Search broadly across government scholarships, university-specific scholarships, program-specific scholarships, Erasmus Mundus programs, and other scholarship types.
- Check each scholarship's eligibility requirements against the student's profile.
- Account for funding gaps and scholarship-specific details. For example, TUM has substantial tuition fees that a DAAD scholarship may not cover.

### Initial consultation and application strategy

- Begin with a consultation that asks about the student's goals, affordability constraints, and budget for university applications.
- Ask whether the student can attend only with a scholarship or can afford some costs without one.
- Ask whether the student wants a balanced-fit strategy or wants verified fully funded opportunities prioritized even when academic, program, career, or location fit is weaker, and record which preferences remain non-negotiable.
- Ask whether the student prefers a one-year master's, a two-year master's or has no duration preference; whether the preference is mandatory or weighted; whether the goal is rapid industry entry, research or PhD preparation, a field change or still undecided; and which funding, internship or research advantages would justify a longer program.
- Answer the student's questions about scholarships and the application process.
- Charge a small consultation fee. After payment and consultant approval, give the student a versioned, downloadable Consultation Recommendation Report covering the recommended application pack and why each program was selected, even if the student does not purchase the full application service. Credit the consultation fee toward the platform fee when the student proceeds.
- If it is beneficial for customer acquisition and the business strategy, use the consultation to explain honestly why the application process is difficult and how the platform reduces that burden.
- Present a proposed set of countries, universities, and scholarships for the student to approve.
- Consider application order and funding timing so the student does not pay avoidable university application costs when a scholarship decision can come first.
- After approval, show a roadmap and the current stage of every university and scholarship application.

### Application automation

- Handle application processes that differ across scholarship and university websites.
- Fill forms despite frequent changes to HTML structure, selectors, buttons, and step transitions.
- Use an authorized consultant exception desk for CAPTCHA, unfamiliar portals, payment failures and other delegable actions that are not yet reliably automated.
- During the MVP, have a consultant complete CAPTCHA in the preserved portal session. In later phases, allow an integrated CAPTCHA-resolution service only where lawful and permitted by the portal's terms, with consultant fallback when the service is prohibited, unavailable or unsuccessful. Do not use unauthorized CAPTCHA circumvention. Ask the student only for identity verification, personal MFA, legally binding signatures, personal attestations, new facts, personal decisions or spending beyond approved authority.
- Create a dedicated email account for the student and use it for all later university and scholarship applications and communication.
- Keep the dedicated email platform-managed throughout the application service; do not design an ownership-transfer or service-offboarding workflow for the MVP.
- *Superseded 2026-09-15:* the two bullets above are replaced by the student connecting their own mailbox through OAuth, read-only and pack-filtered, with no platform-domain address — `phased requirements.md` §4.3 amendment and `docs/superpowers/specs/2026-09-15-student-owned-mailbox-design.md`.
- After the student approves the application pack and budget, consultants initially execute permitted applications and payments on the student's behalf; the agent progressively assumes the normal workflow while consultants become an exception desk.
- *Amended 2026-09-15:* the automated successor to consultant portal work is a browser extension that fills the portal in the student's own logged-in tab while they watch, and the student submits — never an agent acting in the student's place. CAPTCHA and personal verification are the student's own acts in that session. `phased requirements.md` §5.1–§5.2 amendments; `docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md`.

### Application materials

- After the student approves the plan, restructure the student's CV and write a motivation letter.
- Avoid generic, one-shot documents.
- Iterate on the documents and tailor them to each scholarship or university when necessary.
- Show counselors the generated CV, SOP or motivation letter beside verified facts and source documents, with source-linked highlights, conflicts and unsupported-claim warnings.
- Require counselor approval of the exact document version before application use; any later change invalidates the approval.

### Ongoing support

- Provide a centralized dashboard and notification center for missing documents, application changes, interview invitations, and application status.
- Give counselors an assigned-student work queue for deadlines, document approvals, exceptions, payments and interventions.
- Let the student upload a requested document once through the platform; the agent then uploads it to the relevant university or scholarship portal.
- Notify the student when action is required.

### Service and payment model

- Charge one platform fee covering university and scholarship application services, ongoing monitoring, and the centralized dashboard.
- Sell the same platform to education agencies as a white-label service while keeping tenant data, permissions, branding and audit records isolated.
- Students pay university application fees themselves, in their own portal session (owner, 2026-10-03); the platform never holds or pays them.
- Treat the service as one end-to-end engagement rather than a voluntarily cancellable sequence of stages.
- Do not offer a voluntary refund, cancellation, or outcome-guarantee policy; any mandatory consumer rights still need to be identified for the jurisdictions served.

## 2. Assumptions inferred from the original idea

These points were initially implied and are retained as context unless a later approved decision supersedes them:

- The student knowingly authorizes the platform to use their information and act on their behalf.
- The platform will collect and store sensitive personal, academic, financial, and application data.
- Scholarship and university information must be refreshed continuously because requirements, deadlines, fees, and web flows change.
- Recommendations will consider total affordability, not only the advertised scholarship amount.
- A single student may manage several scholarship and university applications concurrently.
- Application documents and form answers must use only facts stated by the student or extracted from authoritative documents supplied by the student. Verify material facts against those sources where possible; when evidence does not exist, require explicit student confirmation and record the fact as student-attested. Require the student to resolve conflicts or ambiguities before use.
- Some steps will require the student's direct participation even if most of the workflow is automated.

## 3. Historical decision questions

These questions are retained as the decision record. Their approved resolutions are defined in `phased requirements.md`.

### Scope and users

- Are any scholarship families excluded from the first release?
- What measurable threshold defines a "strong match" and a "good reason" for MVP acceptance?
- Which dashboard information and workflows must function for the MVP to count as complete?

### Recommendation quality

- What student profile data is required before searching and checking eligibility?
- How should uncertain or ambiguous eligibility rules be handled?
- What evidence must accompany each recommendation: official source, deadline, last-checked date, estimated costs, funding gaps, and confidence level?
- How will the platform distinguish authoritative sources from aggregators or outdated listings?
- What exactly qualifies as a scholarship decision that should precede a university application?

### Autonomy, consent, and compliance

- Which actions may the agent take automatically, and which require explicit student approval?
- Should the student approve each final submission, declaration, and payment?
- How should CAPTCHA, identity checks, multi-factor authentication, signatures, and other anti-bot or identity-verification steps be handled?
- Do target universities and scholarship providers permit automated form completion or submission under their terms?
- Who is responsible when a site changes, an automation step fails, or submitted information is incorrect?
- What audit trail is required to show what the agent changed, what the student approved, and what was submitted?

### Accounts, data, and communication

- Which email provider will be used, and do its terms permit automated account creation and agent access?
- How will credentials, identity documents, financial records, and application data be secured, retained, exported, and deleted?
- Which communications may the platform read or send automatically?
- Which notification channels are required in addition to the dashboard?

### Service model

- Are consultation, CV and motivation-letter work included in the platform fee or priced separately?
- How will university application fees be collected, held, reconciled, returned when a submission fails, and evidenced to the student?
- Does the student approve each third-party fee, or authorize a total application budget in advance?
- When does a human consultant review recommendations, writing, or exceptional cases?
- How many revision rounds are included for CVs and motivation letters?
- Which mandatory refund, cancellation, disclosure, and consumer-protection rights apply despite the intended no-voluntary-refund policy?

## 4. Approved refinements

### A. Deliver a concierge MVP and automate it progressively

Deliver the full end-to-end service from the commercial MVP while keeping the initial technical implementation narrow. Automate search, evidence collection, eligibility screening, planning and dashboard tracking first. Consultants initially handle document operations, unfamiliar portals, CAPTCHA, permitted submissions, payments and monitoring through controlled procedures. Later phases may use a CAPTCHA-resolution service only where lawful and permitted by portal terms, with consultant fallback. Progressively automate the normal workflow and retain consultants for exceptions. The student handles only genuinely non-delegable identity, authentication, signature, attestation, factual or spending decisions.

### B. Constrain by degree and teaching language, not geography

Cover every country from the first release. Default to English-taught master's programs, but include programs in additional teaching languages explicitly selected by the student. A selected-language program may become a confirmed recommendation only when the student meets, or can meet by the deadline, its language-evidence requirement. Keep local job-market language as a separate evaluation criterion. Keep the first release focused through four core capabilities:

1. Student profile and affordability assessment.
2. Evidence-backed scholarship discovery and eligibility screening.
3. An approved application shortlist and roadmap.
4. A dashboard for deadlines, documents, costs, and next actions.

Add document tailoring and assisted form completion after the recommendation workflow is reliable. Build fellowships and events later as a separate service.

### C. Make recommendations evidence-backed

For every opportunity, show the official source, eligibility rationale, exclusions, deadline, last-checked date, expected application cost, estimated funding coverage, uncovered costs, required documents, and any uncertainty. Use clear outcomes such as `eligible`, `possibly eligible—review needed`, and `not eligible`, each with reasons.

### D. Model affordability explicitly

Separate scholarship value from total cost. The proposed plan should include tuition, application fees, living costs, travel, insurance, deposits, and known funding gaps. Respect the student's maximum application budget and whether attendance is possible only with full funding.

Lead with a city-specific, lower-end realistic student budget rather than an average consumer budget or an unrealistically absolute minimum. Use current primary evidence for local housing, food, transport, utilities, insurance and other necessary costs. Include a social or student benefit in the calculated baseline only when an official source verifies that it applies in that country or city, the student appears eligible and ordinary access is sufficiently reliable. Show food banks and emergency aid as possible support, but do not subtract them from the minimum viable budget or uncovered funding gap. Never transfer a benefit assumption from one country or city to another.

*Amended 2026-09-17.* Living cost is shown as a **range for a named city**, never a single number, and the range is researched once per city from official sources and cached, never searched per student. Its low end is the cheapest a student can realistically obtain — the public student-housing body's own published rent, such as a Studierendenwerk or CROUS room. Its middle is what a student can secure unaided: a shared room or flat-share at the figure the university's own cost-of-living page or the national student survey publishes. Private listing sites are never a source: they are the average consumer budget this section already rules out.

**The low end is quoted only with its access reality, in the same breath.** A subsidised room is capacity-limited: state the waiting list, the application window and, where the system allocates that way, that it is a lottery. Showing a cheap figure without that is disinformation even when the figure is true.

**Display may lean low; the affordability decision may not.** The funding gap and every decision about whether a student can afford an option are computed on the **middle** figure, so that no recommendation rests on winning a housing lottery. The subsidised case is shown beside it as a conditional improvement — what the gap becomes *if* the room is obtained — which supersedes the former instruction to treat capacity-limited housing only as a conditional saving.

**Be realistic in both directions, and never present a floor as an expectation.** A figure below what a student can actually live on is as harmful as an inflated one: it produces a plan that collapses after arrival. Every end of every range carries its source, its quoted sentence, its city, its cycle year and its basis — the visa financial-proof norm, the institution's own estimate, the student-housing rate card or the national student survey. Where a city has no primary evidence for a component, say so and show the range as incomplete rather than filling it by inference from another city.

Recommendations must follow the student's declared objective. When the student requires full funding and chooses a funding-first strategy, verified fully funded opportunities may rank highly despite weaker academic competitiveness, program alignment, career fit, or negotiable personal preferences. Explain that trade-off prominently. Funding may not override confirmed ineligibility, an unworkable deadline or language requirement, or a preference the student marked non-negotiable. Students who do not choose funding-first ranking receive the normal balanced-fit strategy.

### E. Keep the dedicated email platform-managed

Create and manage the dedicated email throughout the end-to-end application service. Skip ownership-transfer and service-offboarding workflows in the MVP. Confirm that the email provider permits the account-creation and access model. Record the approved facts and application pack, the submitted data, timestamps, fees, receipts and every consultant or agent action.

*Superseded 2026-09-15.* No dedicated email is created. The student connects their own mailbox with the least OAuth scope that works; the platform reads only mail from institutions in the student's pack and sends nothing. The recording sentence stands. See `docs/superpowers/specs/2026-09-15-student-owned-mailbox-design.md`.

### F. Treat each application as a tracked workflow

Give every university and scholarship application a visible status, deadline, document checklist, fee, owner of the next action, and history. If a portal requests a missing document, let the student upload it to the dashboard once, validate that it is intended for the application, and have the AI agent place it in the correct portal. When automation cannot proceed, create a specific student or consultant task rather than silently failing.

### G. Make writing iterative and verifiable

Maintain a verified base profile of the student's education, experience, achievements, and goals. Produce tailored CV and motivation-letter versions from that profile, explain major changes, check factual consistency, and require student approval before use.

### H. Position consultation as escalation and quality control

Use consultation for ambiguous eligibility, affordability trade-offs, unusual application rules, strategic review, and cases where automated evidence is insufficient. If consultation is an effective acquisition channel, explain the process's real complexity and show concretely how the platform saves work, reduces missed steps, and centralizes applications. Keep these claims accurate rather than exaggerating difficulty or pressuring the student. Keep tailored interview preparation and paid mock interviews as distinct services.

### I. Separate service revenue from third-party fees

Itemize the platform fee and every university fee even if the student pays them together. Use a payment provider and a clear ledger rather than treating university fees as platform revenue. Define what happens to unused or failed-submission funds; a no-voluntary-refund policy cannot override mandatory law or justify retaining money that was never spent as authorized.

### J. Make agency tenancy a first-class boundary

Use one shared application with strict agency-level isolation. Every student, counselor, document, application, payment, job, approval and audit event belongs to one tenant. Platform support access is time-limited, reason-bound and audited. Start with manual agency provisioning and defer dedicated deployments, self-service billing and workflow builders until demand proves they are necessary.

### K. Constrain white-label customization

Allow an agency name, logo, validated color tokens, agency subdomain, verified custom domain, branded messages, support details and legal links. Do not allow arbitrary tenant CSS, JavaScript or HTML. Keep required legal and safety notices even when platform branding is hidden.

### L. Prove human oversight

Give counselors a side-by-side document review with verified facts, source provenance, automated red flags, inline quick edits and focused diffs. Mandatory safety approvals cannot be disabled, although an agency may add stricter gates. Record every automated and human action in an append-only audit history and export an agency-branded application dossier without storing private model chain-of-thought or secrets.

### M. Defer cross-tenant learning behind a privacy gate

Do not train directly on raw tenant databases or reuse one agency's personal data for another. A later opt-in platform-intelligence pipeline may process only contractually eligible records through minimized feature extraction, PII and quasi-identifier transformation, quarantine, privacy testing and human privacy approval. Treat derived data as personal while re-identification remains reasonably possible and preserve source lineage for deletion and revocation handling.

### N. Make the paid consultation independently useful

After the consultation fee is paid and a consultant approves the recommendation pack, deliver an agency-branded Consultation Recommendation Report even when the student does not continue to the full application service. The report shall summarize the student's approved goals and assumptions; the recommended universities, programs and funding routes; why each was selected; fit, affordability, duration, mobility, risks, deadlines, fees, evidence and next actions. Keep internal research leads out of the report. Make it a timestamped, versioned snapshot with official sources and last-checked dates rather than a guarantee. Decide its final visual design, downloadable format and whether to provide an additional interactive web version later.

### O. Add direct-only standalone document services later

In Phase 2, the company may sell CV polishing and tailored motivation-letter writing as separately charged standalone services for master's applicants who do not buy consultation, discovery or application management. A customer may buy either service or a bundle. Motivation-letter work may target any master's program, including one outside the platform's recommendation catalog, after the official program information and prompt are verified. Reuse the same verified-fact, counselor-review, versioning and revision controls as the end-to-end service. Full-service customers shall not be charged again for document work already included in their platform fee. Offer these standalone services only through the company's direct-to-consumer channel; white-label agency customers receive only the end-to-end pipeline platform. Decide standalone pricing, turnaround, bundles and public-page design later.

## Approval boundary

This document records the approved problem framing and product direction. It authorizes derived architecture and requirements documentation only; it does not authorize Graphify, source-code creation, infrastructure deployment, website automation, account creation, payments or external submissions.
