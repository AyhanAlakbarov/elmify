# External audit — the answer

Received 2026-10-24. This is the reviewer's answer to the audit brief, saved word for word; only the headings, lists and tables were rebuilt after copy-paste flattened them. Section references (A.x, B.x, C.x) point into the brief. Sections 1–8 are the first answer, section 9 the reviewer's follow-up on hidden gems, section 10 a spot-check of both against the code.

## Owner decisions (2026-10-24)

The owner rejects these recommendations; each stays as it is:

- **Social-media reading through the remote-browser vendor** — kept (rejects finding 12, section 3 "Scraping posture", section 5 row 2).
- **The register whose terms allow personal use only** — kept (rejects finding 12 and section 3 "Scraping posture").
- **Baidu / Naver sweeps** — kept (rejects section 5 row 3).
- **Employer-sponsorship domain sweeps** — kept (rejects section 5 row 4).
- **Paid proxies that get past a site's blocks (fetch Rung 4, scrape.do premium proxies)** — kept (rejects finding 12 and section 3 "Scraping posture").

Every other recommendation is still open, not accepted.

---

## 1. Executive Summary

### The Verdict

Elmify is a classic case of AI-accelerated architectural inversion: because agentic workflows (B.10) made writing specs, code, and tests cheap, you built a 130k-line, multi-tenant, 15-vendor distributed intelligence platform before generating a single end-to-end recommendation pack for a real human (A.2, C.1.2).

Your core engineering instincts—deterministic arithmetic over model hallucinations (B.1.6 08-14), byte-for-byte quote verification (B.4.2), forced Row-Level Security (B.7), and separating world facts from student profiles (B.4.2)—are genuinely world-class. However, your pipeline's strict gates currently multiply together to produce an empty pipe:

- The provenance gate blocks institutions outside 5 countries (B.4.12, C.2.6).
- The Gen-1 reader's unanimity rule served only 2 of 69 Erasmus Mundus rows (B.4.9).
- The Gen-2 card engine cannot store or serve yet (B.4.9, C.2.3).
- Per-student search ("the tap") is switched off and disconnected from the reader (B.4.15, C.2.2).
- Fit scoring is hardcoded to 50, causing every "balanced-strategy" student to receive zero programme recommendations (B.4.14, C.2.1).

If a student in Baku paid you today and completed the 22-question onboarding, the system would either fail to return a usable pack or recommend almost nothing outside a tiny seeded slice.

### Top 5 Recommendations

1. **Kill the Per-Student Search Wallet ("The Tap") and Pre-Warm by Corridor (B.4.15, B.1.4):** Master's programmes and scholarships belong to (destination_country, field_family), not individual students. Giving a student a USD 100 search wallet (up to USD 200/year) destroys B2C unit economics before you set a price. Make student pack generation a 100% read-only query against pre-warmed Postgres tables (cost: ~USD 0.02, latency: under 3 seconds).
2. **Fix the Four Pipeline Blockers in 3 Weeks (B.4.9, B.4.12, B.4.14):** (a) Finish Gen-2 card engine storage ("slice 3") and delete Gen-1; (b) replace the hardcoded 50 fit score with deterministic ISCED-F field matching plus pgvector embeddings inside your existing PostgreSQL 17 instance; (c) expand the provenance gate from 5 to 40+ countries in 48 hours by ingesting the EU ECHE (Erasmus Charter), WHED, DEQAR, and Azerbaijan's State Programme (DP) / TKTA lists; (d) build the missing erasure executor (B.8.3).
3. **Stop Building a Worldwide Open-Web Scraper; Curate the Top 8 Corridors First (B.4.4, B.4.5):** Roughly 85% of funded outcomes for Azerbaijani and Turkish master's applicants come from ~50 flagship schemes (Dövlət Proqramı, Türkiye Bursları, Stipendium Hungaricum, DAAD, Erasmus Mundus, Chevening, Visby/SI, Italian DSU/MAECI, Eiffel, Fulbright, IsDB) and ~400 public European/Turkish universities. Pre-sweep and operator-verify those 8 corridors to 100% completion before writing another line of capture-recapture code for Indonesian foundations.
4. **Reverse Portal Password Storage and the "Extension-Only" Lock (B.6.1, B.6.2, B.1.6 10-09 & 10-10):** Storing student portal passwords in AWS Secrets Manager costs USD 0.40/secret/month, creates a toxic honeypot, and violates the very portal credential-sharing terms that justified building the extension (C.4.1). Furthermore, refusing to show a manual "Application Kit" when the desktop Chromium extension breaks on a university portal will cause missed deadlines.
5. **Show Official Source URLs on Cards with Per-Card AI Provenance (B.1.6 08-28, B.8.2):** Hiding official URLs to protect your catalogue moat while serving unreviewed AI extractions with only a one-time platform notice creates severe legal and trust exposure. Gate URLs behind the paid Consultation Report, never hide them from paying students, and attach a verified-date + source link to every card.

### The Single Biggest Risk

**The Compounding False-Negative Trap (B.4.2, B.4.9, B.4.12, B.4.14).** You optimized every layer for near-zero false positives (provenance gate, verbatim origin-only sentences, 3-model unanimity, hard fit bar at 80/60), ignoring that in a 6-stage serial pipeline, if each stage has a 65% pass rate on valid opportunities, end-to-end recall drops to $0.65^6 \approx 7.5\%$. A student will forgive a card that says "Tuition: Unconfirmed — click here to check the university's PDF"; they will never forgive Elmify for missing Stipendium Hungaricum or a tuition-free German M.Sc. that their friend found in 10 minutes on ChatGPT.

---

## 2. Findings Table

Note on notation: Effort is graded as S (under 1 week), M (1–4 weeks), or L (over 1 month).

| # | Area | Finding | Evidence (Type + Section) | Severity | Recommendation | Effort | Confidence |
|---|------|---------|---------------------------|----------|----------------|--------|------------|
| 1 | Search / Recs | **Broken "Balanced" Fit Scoring:** Fit dimensions are hardcoded to 50, while the balanced strategy requires overall at least 80 and every dimension at least 60, resulting in zero programme recommendations for balanced users. | Stated (B.4.14, C.2.1) | Critical | Implement deterministic ISCED-F taxonomy + pgvector cosine similarity for programme/academic fit, and lookup rules for career/mobility fit. | M | High |
| 2 | Search / Recs | **Provenance Gate Choke-Point:** Only 5 countries have registers loaded (HRK, OfS, YÖK, Korea, Azerbaijan). All other global institutions default to Unconfirmed and are excluded from packs. | Stated (B.4.12, C.2.6) | Critical | Ingest bulk supranational/official datasets: EU Erasmus Charter (ECHE), DEQAR/EQAR, WHED, and Azerbaijan's State Programme (DP) + TKTA lists. | S | High |
| 3 | Search / Recs | **Dual Page-Reader Technical Debt & Disconnected Pipeline:** Gen-1 has catastrophic recall (2 of 69 Erasmus rows served; 0 of 10 after holder axis); Gen-2 ("card engine") cannot store or serve ("slice 3" unbuilt); per-student search doesn't pass hosts to any reader. | Stated (B.4.9, B.4.15, C.2.2, C.2.3) | Critical | Freeze and delete Gen-1. Finish Gen-2 "slice 3" storage/serving immediately and wire host discovery directly into Gen-2. | M | High |
| 4 | Data / Privacy | **Missing Erasure Executor & Orphaned Cache:** Requesting erasure locks the student out immediately, but the scheduled executor is unbuilt (Missing), leaving accounts permanently locked and un-erased. One CV digest cache bypasses erasure. | Stated (B.3, B.8.3, C.4.3) | Critical | Build the scheduled erasure job calling the `erasure_guard` DB function and include the CV digest cache table before any real user onboarding. | S | High |
| 5 | Security / Legal | **Server-Side Portal Password Custody:** Storing student portal passwords in AWS Secrets Manager reverses the 09-15 security model, violates portal ToS against credential sharing, and costs USD 0.40/secret/month. | Stated (B.1.6 10-09, B.6.2, C.4.1) + Inferred cost | Critical | Stop storing portal passwords on AWS. Generate/store credentials locally in the browser's native password manager or extension local encrypted storage. | S | High |
| 6 | Business / Ops | **Inverted Unit Economics on Per-Student Search ("The Tap"):** Allocating a USD 100 wallet per student per cycle (up to USD 200/year) for runtime web search when no pricing or payment gateway exists guarantees negative gross margins on B2C reports. | Stated (B.1.4, B.4.15, C.7.1) + Inferred | Critical | Replace per-student runtime search with offline corridor pre-warming. Cap any per-student niche delta-search at USD 1.50 max. | S | High |
| 7 | Business | **Zero Commercial Infrastructure:** 130k LOC built, but no registered legal entity, no payment processor, no set prices for consultation or platform fees, and no production stack. | Stated (A.2, B.1.4, C.1.3) | Critical | Register entity (Azerbaijan LLC for local AZN acquiring via Kapital/Pasha/Epoint, or US LLC via Stripe), fix prices, and deploy staging-to-prod. | M | High |
| 8 | Product | **Extension-Only Application Lock:** Forcing all applications through a desktop Chromium extension with zero manual fallback ("how to apply by hand" kit removed 10-10) will cause missed deadlines when portal DOMs change. | Stated (B.1.6 10-10, B.6.1, C.6.1) + Opinion | High | Always provide a downloadable "Application Kit" (tailored PDFs + copy-paste field sheet + direct portal link) alongside the extension. | S | High |
| 9 | Product / Trust | **Hiding Official Source URLs from Students:** Withholding source URLs (08-28) while serving unreviewed AI extractions (09-23, 10-08) destroys user trust and shifts 100% of hallucination/parsing risk onto the student without a way to self-verify. | Stated (B.1.6 08-28, B.8.2) + Opinion | High | Show the official source URL and verification date on every card in paid reports. Protect against scraping via rate limits, not dark patterns. | S | High |
| 10 | Search / Recs | **Over-Strict Origin-Only Discovery Rule:** Refusing to use structured aggregators (DAAD, StudyPortals, ScholarshipPortal) as discovery scaffolding forces cold web searches where no single config beat 18% recall (B.4.5). | Stated (B.4.2, B.4.5) + Inferred | High | Use aggregators and official national study portals to enumerate (institution, programme_name, degree_url) tuples, then verify facts on the origin site. | M | High |
| 11 | Legal / Data | **Flawed Jurisdiction & Cross-Border Data Assumption:** Treating only Azerbaijan's Personal Data Law as binding (B.8.1) ignores (a) Azerbaijan's strict cross-border transfer/registration rules when sending data to Frankfurt/US LLM APIs, (b) EU Europass API transfers, and (c) Turkey KVKK / GDPR Art. 3(2). | Stated (B.8.1, B.5, C.4.4) + Opinion | High | Add explicit cross-border transfer consent at signup, require an explicit user click before sending data to the EU Europass API, and align DPA to GDPR/KVKK. | S | High |
| 12 | Legal | **Misplaced Liability Shield on Vendor Scraping:** Delegating robots.txt, TDM opt-outs, and proxy block-bypassing (scrape.do premium proxies) to vendors (B.4.6), plus reading a personal-use-only register and scraping social media (C.5.1), does not legally absolve the principal (Elmify). | Stated (B.4.6, C.5.1) + Opinion | High | Drop social media remote-browser scraping and personal-use-only registers. Respect hard HTTP 403/blocks via official APIs or operator curation rather than residential proxy evasion. | S | High |
| 13 | AI / ML | **Anthropic High-Risk Policy & Unreviewed Serving:** Serving automated admissions/eligibility filtering without human review and with only a one-time signup banner (B.1.6 10-08, B.8.2) risks vendor ToS suspension and EU AI Act transparency non-compliance. | Stated (B.1.6 10-08, B.8.2, C.5.2) | High | Add per-card AI confidence/verification badges, expose the source URL for human-in-the-loop verification by the student, and log student sign-off. | S | High |
| 14 | Search / Recs | **Naive Pool Selection & Missing Living Costs:** Pool selection is currently a naive substring match on programme name (B.4.14, C.2.4), and city living costs are unpopulated (C.2.9), skewing affordability math (`1 - gap / total_cost`). | Stated (B.4.14, C.2.4, C.2.9) | High | Seed a static country/city monthly living-cost table (from official visa financial-proof minimums, e.g., Germany Sperrkonto EUR 992/mo) and map fields via ISCED-F tags. | S | High |
| 15 | Ops / Cost | **Vendor & Infrastructure Sprawl:** 15 external vendors (B.4.16, C.7.2), 12 SQS queues, 4 separate Fargate worker services (B.3), and two separate Jev clients in code prior to first dollar of revenue. | Stated (B.3, B.4.16, C.7.2) | Medium | Consolidate to 1–2 Fargate worker containers handling multiple queues; unify the Jev client; drop Diffbot and Tavily once registers + Exa/Brave are tuned. | M | High |
| 16 | Security | **Retired EC2 Portal Tier Left in CloudFormation:** A retired EC2 tier still sits in the IaC template at count 0 with broad Secrets Manager access (B.3, C.4.2). | Stated (B.3, C.4.2) | Medium | Delete the EC2 resources and IAM roles from the CloudFormation template completely. | S | High |
| 17 | Architecture | **Disabled Critical Schedules (Retries & Cycle Verification):** Fetch retry Rung 5 (B.4.6) and scheduled cycle verification (B.3, B.4.11) are disabled because retry callbacks aren't wired to the caller. | Stated (B.3, B.4.6, B.4.11, C.7.3) | Medium | Wire Rung 5 retry completion to trigger an idempotent host-read event, and enable cycle verification for the top 8 target corridors. | M | High |
| 18 | Product | **Azerbaijan Degree Recognition (TKTA) Unbuilt:** Designed as 10 checks against TKTA rules (B.4.12), but mostly unbuilt. For Azerbaijani applicants returning home, TKTA recognition and military deferment eligibility are dealbreakers. | Stated (B.4.12, B.4.18) + Market knowledge | Medium | Implement the 4 core deterministic TKTA rules first (study mode = in-person, accredited register, language, high-refusal warning badge). | S | High |
| 19 | Product / UX | **Onboarding Friction & Gated Letter UI:** Onboarding recently had raw JSON boxes and session-only drafts (C.6.2), and the motivation letter UI is still gated behind an operator command (B.5, B.9). | Stated (B.5, B.9, C.6.2) | High | Persist questionnaire drafts in Postgres per step, eliminate any remaining raw JSON inputs, and expose the letter generation UI for pilot users. | M | High |
| 20 | Process | **Documentation Drift & Inverted Phase Execution:** 300+ docs contradict the codebase (e.g., Python 3.12 vs 3.14, OpenAI-only vs 5+ vendors, consultant review vs auto-publish, Phase 5 built before Phase 1 baseline). | Stated (B.9, B.10, C.1.1, C.3) | Low | Archive stale specs into `/docs/archive/` and maintain a single `ARCHITECTURE_CURRENT.md` truth file enforced in CI. | S | High |

---

## 3. Direct Answers to Your Core Checklist (Section A.5)

### Search Engine and Recommendations (B.4)

**Worldwide catalogue vs. licensing/aggregators/hand-curation (A.5 Search #1):** Building a general worldwide discovery engine first was the wrong sequencing (C.1.1), though the schema you built (B.4.4, B.4.5) is strong. Do not run open-web sweeps across 190 countries. Instead, curate and pre-sweep 8 high-density destination corridors for Azerbaijani/Turkish students (Germany, Hungary, Turkey, Italy, Estonia/Baltics, Poland, Netherlands, France/UK) plus the ~50 major bilateral/government scholarships. Use official national portals (DAAD, Study in Italy/Holland/Sweden/Hungary, EACEA) as your primary programme enumerators rather than paying Exa/Brave to rediscover universities via search queries.

**Origin-only verbatim sentences vs. aggregators (A.5 Search #2):** Requiring verbatim origin quotes for displayed card facts (B.4.2) is worth keeping—it is your strongest defence against LLM hallucinations. However, refusing to use aggregators for programme enumeration and baseline expectation setting costs you massive recall (B.4.5, B.4.9). Let aggregators tell you "TU Munich has an M.Sc. in Informatics taught in English with a May 31 deadline", then send your site-job (B.4.6) to tum.de specifically to locate and quote those exact facts.

**Serve rule precision (95.6%) vs. recall (A.5 Search #3):** The balance is skewed too far toward precision at the expense of fatal false negatives (B.4.9, B.4.10). Requiring 3 models to agree on existence is fine, but hiding an entire card when a detail field is "held" in Gen-2 (B.4.9: "A held field hides its award until fixed") will decimate recall. Fix: If existence, institution, and level are confirmed, serve the card and render held details explicitly as "Not confirmed on page — verify before applying" with a direct link to the source URL.

**Consolidate the two generations of page reader now? (A.5 Search #4):** Yes, immediately (B.4.9, C.2.3). Complete "slice 3" (storage and serving) of Gen-2 (the card engine) and delete Gen-1. Gen-2's architecture—deterministic regex/parser candidate extraction followed by cheap dual readers (DeepSeek V4.1 Flash + Luna) and Claude Opus only as a tie-breaker—is faster (under 30s), cheaper (under USD 0.25), and eliminates Gen-1's 3-way prompt-phrasing deadlocks.

**USD 100 per-student search wallet & first-student pays (A.5 Search #5):** Wrong economic shape (B.4.15). Search is a capital expenditure (CapEx) on a shared data asset, not a per-user variable cost (COGS). If Student #1 searches "M.Sc. Computer Science in Germany", why should their wallet pay USD 15–100 to populate a shared catalogue that Student #2 gets for free? Move sweeps entirely to platform-scheduled background jobs budgeted per corridor. Student pack generation should query the existing Postgres database for USD 0.00 in search fees.

**How should fit be scored? (A.5 Search #6):** Replace the hardcoded 50 placeholder (B.4.14, C.2.1) with a 3-tier hybrid scorer:

- **Tier 1 (Academic & Programme Fit — Deterministic + Embeddings):** Map every programme and student degree to ISCED-F 2013 4-digit field codes (exact match = 90, same broad group = 70, adjacent = 50). Combine 50/50 with cosine similarity over text-embedding-3-small vectors stored in PostgreSQL pgvector (comparing student courses/projects/interests to programme curriculum text).
- **Tier 2 (Career & Mobility Fit — Deterministic Lookup):** Score based on data rows keyed by (destination_country, student_career_goal)—e.g., post-study work visa duration (Germany 18 months = 95 for "work abroad"), PhD track access, or TKTA recognition for "return home".
- **Tier 3 (LLM Anchored Rubric):** Run only on the top 20 programmes that pass hard gates and Tier 1/2 scoring, keeping latency under 5 seconds and cost under USD 0.05 per student.

**Provenance gate principle and scaling beyond 5 countries (A.5 Search #7):** The principle ("admit only on evidence a fraudster can't write", B.4.12) is sound, but country-by-country scraping of 53 separate ENIC-NARIC registers is too slow. Scale to 40+ countries in one week by loading four bulk authoritative datasets:

- **EU ECHE (Erasmus Charter for Higher Education):** Official EU CSV/API of every accredited higher-education institution in 33 European countries (~5,000+ institutions with PIC codes and domains).
- **DEQAR (Database of External Quality Assurance Results):** Official European EQAR register API with ROR/ETER IDs and domains.
- **Azerbaijan State Programme (DP) & TKTA Lists:** The exact universities approved by the Azerbaijani Ministry of Science and Education.
- **ROR + Wikidata Cross-Check:** While ROR alone had 7/13 diploma mills in your test (B.4.5), requiring ROR active AND (ECHE OR DEQAR OR WHED OR established before 2010 with national accreditation ID in Wikidata) eliminates diploma mills while unlocking global coverage.

### Business and Product

**Beachhead (A.5 Business #1):** Keep "Master's applicants from Azerbaijan (then Turkey)", but narrow the initial supply promise to "Top 10 European & Regional Destination Corridors + Global Flagship Scholarships". Don't advertise "any country, any script worldwide" on Day 1 when Korean abolish-filtering works (B.4.5) but French, Dutch, and Italian national registers aren't even loaded in the provenance gate (B.4.12).

**Pricing & Consultation Funnel (A.5 Business #2):** The "paid Consultation Recommendation Report credited toward the full platform fee" (B.1.3, B.1.4) is an excellent acquisition wedge for a low-trust market where traditional agencies demand 1,500–4,000 AZN up front.

Recommended B2C Pricing (Azerbaijan):

- **Consultation Report:** 49 AZN (~USD 29). Impulse-buy price for a student/family; covers compute + gateway fees with >85% gross margin once search is pre-warmed.
- **Full Admission Cycle Pass (up to 6–8 applications):** 349 AZN (~USD 205) (with the 49 AZN credited, so 300 AZN upgrade).
- **Anti-Abuse:** In the 49 AZN report, show the full pack, fit scores, gaps, requirements, and official source links. Reserve the CV/Letter generator, Europass export, and Extension autofill for the 349 AZN tier.

**B2B white-label vs. B2C first (A.5 Business #3):** Pause B2B sales until you complete 20–50 B2C cycles (B.1.2). Traditional brick-and-mortar agencies in Baku and Istanbul rely heavily on university commission kickbacks (15–25% of first-year tuition from private UK, Polish, Turkish, or North Cyprus universities). An objective engine that tells their client "Don't pay USD 12,000 for a private university; go to this tuition-free public university in Germany or Italy with a DSU grant" cannibalizes the agency's commission revenue. Your true B2B buyers will be independent freelance admission mentors, university career centres, and boutique fee-only consultancies—and they will only buy once B2C proves the engine works.

**Scope removals & extension-only applying (A.5 Business #4):**

- **Removing interview prep / mock interviews (B.1.4):** Correct. High maintenance, easily done by students in ChatGPT Voice Mode.
- **Students pay application fees directly; platform never holds money (B.1.4):** 100% Correct. Avoids PCI-DSS, escrow accounting, FX slippage, and money-transmitter regulations.
- **Extension-only applying on desktop Chromium (B.1.6 10-10, B.6.1):** Incorrect. Make the extension optional and restore the downloadable "Apply-by-Hand Kit" (C.6.1).

**What a 5–10 student shadow pilot must measure (A.5 Business #5):** See Section 6.1 below for the exact 6-metric scorecard and protocol.

### Architecture, Security, AI

**Operational burden for team size (A.5 Arch #1):** Django 5.2 + HTMX + Postgres 17 + Fargate (B.3) is a great foundation, but 12 SQS queues and 4 separate Fargate worker services (research, document, europass, mailbox) is over-segmented for zero traffic. Merge the 4 Fargate worker definitions into one multi-queue worker service (plus the isolated no-network OCR Lambda) to cut baseline AWS Fargate spend and deployment wait times.

**Two-layer tenant isolation (A.5 Arch #2):** ORM scoping + Postgres `FORCE ROW LEVEL SECURITY` (B.7) is strong and already built—keep it. Three attack vectors to audit now:

- **Connection Pool Transaction Scope:** Ensure `SET LOCAL app.current_tenant_id = ...` is strictly executed inside `transaction.atomic()`. If `SET` (session-level) is ever called outside a transaction on a pooled DB connection, tenant context will leak to the next request.
- **S3 Object Key Verification:** GuardDuty scans uploads (B.3), but ensure every authenticated download route (B.6.1) queries an RLS-protected Postgres row to resolve the S3 key rather than accepting a path parameter from the request.
- **Background Task Enqueueing:** Verify that when an SQS message is enqueued, the worker validates that the payload's `student_id` actually belongs to the SQS message's `tenant_id` before setting the RLS context.

**Holding portal passwords in Secrets Manager (A.5 Arch #3):** No (B.6.2, C.4.1). Delete this feature. See Finding #5 and Section 4.1.

**Consolidating 5+ model vendors (A.5 Arch #4):** Yes (B.4.16, C.7.2). Keep OpenRouter (with provider pinning + Zero Data Retention enforced in account settings) for DeepSeek V4.1 Flash and Jev, one direct frontier vendor (Anthropic or OpenAI—or route Claude via AWS Bedrock in eu-central-1 so student data never leaves your Frankfurt VPC!), and Azure Document Intelligence (also provisionable in EU West/Central). Unify the two separate Jev clients (B.4.16).

**AI disclosure position (A.5 Arch #5):** Not defensible as currently designed (B.8.2, C.5.2). A one-time signup banner without per-card provenance or source URLs leaves you exposed if a student relies on a misparsed deadline or eligibility rule. Add per-card extraction timestamps, source links, and an explicit student click-through confirmation before document export or portal submission.

### Data and Legal

**Scraping posture (A.5 Data #1, B.4.6, C.5.1):** Unacceptable risk on 3 of the 4 points:

- **Delegating robots.txt / TDM to Firecrawl & scrape.do:** Low practical risk for public university brochure pages (universities want prospective students to read admission requirements), except when using Rung 4 (scrape.do with premium proxies to bypass blocks). If a university WAF blocks you, fall back to the Internet Archive (Rung 6) or operator queue (Rung 7)—do not pay for residential proxy block-evasion.
- **Social media via remote-browser vendor:** Stop. High legal risk under Meta/Telegram ToS and CFAA/anti-scraping laws, high cost, and unstructured noise.
- **Reading a personal-use-only register:** Stop. Use that register only for manual human research to verify official domains, or switch to public ministry/ENIC lists.

**Azerbaijan Personal Data Law vs. GDPR (A.5 Data #2, B.8.1):** Flawed. Even if you incorporate in Baku and serve only residents in Azerbaijan:

- Azerbaijan's Law on Personal Data ("Fərdi məlumatlar haqqında" Azərbaycan Respublikasının Qanunu, Art. 14) strictly regulates transboundary (cross-border) data transfers. Because your AWS stack is in Frankfurt (eu-central-1) and you call US/EU LLM providers, you must collect explicit written/electronic consent for cross-border transfer to specified jurisdictions.
- Furthermore, as soon as an Azerbaijani student currently studying a bachelor's in Hungary, Germany, or Turkey uses Elmify, GDPR (Art. 3(2)) or Turkish KVKK applies directly. Draft your Privacy Policy and Agency DPA to a GDPR + Azerbaijan Cross-Border Consent standard from Day 1.

---

## 4. Decisions to Reverse or Revisit (With Reversal Pricing)

### 4.1 Reverse: Server-Side Portal Password Custody (B.1.6 10-09, B.6.2)

- **Why it's wrong:** It directly contradicts your 09-15 architectural premise ("credential sharing prohibited everywhere sampled"), creates a catastrophic breach target, and costs USD 0.40 per secret per month in AWS Secrets Manager (C.4.1).
- **What to replace it with:** The student creates their own portal account password using their browser's built-in password manager (or the extension generates a random password locally in the browser and triggers the browser's native `CredentialsContainer` / password save prompt without ever sending the password to Elmify's backend).
- **Cost of reversal:** Effort: S (2–3 days). Remove the Secrets Manager write/read endpoints and KMS key from CloudFormation (B.3) and the extension pairing handshake.
- **Risk of reversing:** Near zero. Students are already in their own desktop browser when using the extension.
- **Gain:** Eliminates your #1 security/ToS liability and saves thousands of dollars in Secrets Manager bills at scale.

### 4.2 Reverse: Per-Student USD 100 Runtime Search Wallet ("The Tap") (B.1.6 10-14, B.4.15)

- **Why it's wrong:** Discovery of universities and scholarships is a global/corridor concern, not a per-student concern. Running live multi-language Exa/Brave/Tavily sweeps triggered by student onboarding makes unit economics unpredictable (up to USD 100/cycle), introduces long background wait times, and currently doesn't even connect to the page reader (C.2.2).
- **What to replace it with:** Keep the sweep harness (B.4.5) strictly as an offline operator/cron pipeline that pre-populates the shared catalogue by (destination_country, funding_family, broad_field). When a student submits their questionnaire, Layer 5 (B.4.14) runs immediately against the existing Postgres catalogue. If a cell is thin, flag it in the coverage line (B.4.14) and queue a low-priority platform cell sweep capped at USD 2.00—never a USD 100 student wallet.
- **Cost of reversal:** Effort: S (3–4 days). Leave the wallet code switched off (B.4.15), decouple questionnaire submission from live search triggers, and run offline corridor sweeps for your top 8 destination countries.
- **Risk of reversing:** Niche fields (e.g., "M.Sc. in Ethnomusicology in Finland") may have thin initial results until the offline cell sweep runs.
- **Gain:** Predictable ~90% gross margins, instant Recommendation Pack generation (seconds instead of hours), and simplified billing.

### 4.3 Reverse: Hiding Official Source URLs from the Student Report (B.1.6 08-28)

- **Why it's wrong:** You require every fact to be a verbatim quote from the official site (B.4.2), yet you hide the URL from the student (B.1.6 08-28) while serving packs with zero human review (B.1.6 09-23, 10-08). If a date or fee condition has nuance on the page, hiding the link prevents the student from verifying it and makes Elmify look secretive compared to ChatGPT or Perplexity (which cite links openly).
- **What to replace it with:** Show the exact official source URL and "Verified on YYYY-MM-DD" badge on every card inside the paid Consultation Report and dashboard.
- **Cost of reversal:** Effort: S (1 day). Expose the already-stored `source_url` field in the Django template for authenticated, paid reports.
- **Risk of reversing:** Competitors could copy links if they buy a report—which they can already do in 5 minutes with Google. Your moat is the verified structured facts, eligibility math, documents, and workflow, not secret URLs.
- **Gain:** Massive boost in student trust, compliance with AI transparency norms, and reduced liability if a parser misreads a condition.

### 4.4 Reverse: Removing the "How to Apply by Hand" Kit (B.1.6 10-10, C.6.1)

- **Why it's wrong:** University portals (Uni-Assist, Studielink, Campus France, DreamApply, bespoke Java/SAP portals) break autofill extensions routinely, or forbid automation in their terms (B.6.1). Right now, if a portal prohibits automation or a read-back fails, the student is stuck waiting for a counsellor task (B.6.1).
- **What to replace it with:** Keep the extension as the primary happy path, but auto-generate a clean "Self-Apply Dossier" on every application lane: downloadable tailored CV/Letter PDFs, a table of exact verified values to copy-paste, and the official portal login link.
- **Cost of reversal:** Effort: S (2–4 days). Render existing Fill Packet data (B.6.1) into an HTML/PDF checklist view on the application lane page.
- **Risk of reversing:** None.
- **Gain:** Unblocks students on mobile, Safari/Firefox, macOS/iPad, and unsupported portals; eliminates emergency deadline support bottlenecks.

### 4.5 Revisit: Auto-Calling the EU Europass API Without Per-Student Confirmation (B.5, C.4.4)

- **Why it's wrong:** Sending a student's full PII and academic history to an external government API (EU Europass) automatically whenever 3 model readings think a programme requires Europass (B.5, C.4.4) crosses a privacy boundary without an active user gesture.
- **What to replace it with:** When the engine detects a Europass requirement, show a "Generate Official Europass CV" button on the student's dashboard with a clear notice: "Clicking this sends your verified profile facts to the European Union's Europass service to build your PDF."
- **Cost of reversal:** Effort: S (1 day). Change the automatic worker trigger to an HTMX button action initiated by the student.
- **Gain:** Clean privacy posture and zero wasted Europass API calls on programmes the student decides not to apply to.

---

## 5. Things to Stop, Cut, or Postpone

| Item | Action | Why (with Section Reference) |
|------|--------|------------------------------|
| Gen-1 Three-Reading Funding Judge (B.4.9) | STOP & DELETE | Maintaining two generations of readers doubles prompt/vendor maintenance (C.2.3), and Gen-1's 2/69 Erasmus yield proves its unanimity logic is too brittle. Finish Gen-2 "slice 3" and delete Gen-1. |
| Social Media Remote-Browser Scraping (B.1.6 09-24, B.4.5) | STOP | Not built yet (B.4.5), legally treacherous under Meta/Telegram ToS (C.5.1), expensive, and violates Principle 2 ("the origin is the only evidence", B.4.2). |
| Baidu / Naver / Non-Core Corridor Sweeps (B.4.5, B.4.16) | POSTPONE | Fewer than 2% of Azerbaijani/Turkish master's applicants apply to Chinese- or Korean-taught programmes requiring Baidu/Naver discovery. Focus 100% on Europe, Turkey, UK, and US/Global flagships first. |
| Open-Web Employer Sponsorship Domain Sweeps (B.4.5) | POSTPONE | Sweeping every company on a national stock exchange via Exa (B.4.5) yields mostly internal employee tuition-reimbursement policies, not international master's scholarships. Stick to named national/industrial fellows (e.g., SOCAR, Pasha, KOC, TEV, DAAD). |
| B2B White-Label Onboarding & Custom Domain Provisioning (B.1.2) | PAUSE | Keep the multi-tenant RLS code (B.7) in place, but freeze all B2B agency features, custom domain routing, and agency billing until B2C achieves 20+ paid students. |
| Cross-Tenant Learning Pipeline (B.8.4, B.9) | KEEP DEFERRED | Requires large outcome sample sizes (hundreds of admissions/rejections) to be statistically valid and raises complex GDPR/consent issues. Do not touch until Year 2. |
| Diffbot & Tavily Search Legs (B.4.5, B.4.16) | CUT / CONSOLIDATE | Your own measurements (B.4.5) show Diffbot added only +7% at 28% precision, and Tavily decayed fastest (62 → 5) while taking a perpetual licence over query text (B.4.15). Standardize on Registers + Exa + Brave. |

---

## 6. Unknowns, Experiments, and the 8-Week Launch Plan

### 6.1 The 10-Student Shadow Pilot (Answering A.5 Business #5)

Before launching publicly or writing new features, recruit 10 real prospective master's applicants in Azerbaijan (across STEM, Business/Economics, and Humanities; 5 funding-mandatory, 5 balanced-strategy) and run them through the live pipeline. Measure these 6 go/no-go metrics:

| Metric | Target Gate for Launch | Why It Matters |
|--------|------------------------|----------------|
| 1. Expert Recall Parity | At least 85% of flagship opportunities found by a 2-hour human expert check are present in the student's served pack | Proves your strict gates (B.4.9, B.4.12, B.4.14) aren't silently dropping the obvious best scholarships (e.g., DP, Hungaricum, DAAD, Erasmus Mundus, DSU). |
| 2. Non-Empty Pack Rate | 10 of 10 students receive at least 8 viable programmes and 3 viable funding routes | Validates that fixing the 50 fit score placeholder (B.4.14) and expanding the provenance gate (B.4.12) actually fills packs. |
| 3. Live Fact Accuracy | At least 95% accuracy across all served cards when manually audited against live university websites | Validates Gen-2 card engine accuracy (B.4.10) on complete end-to-end packs rather than isolated lines. |
| 4. Unit Compute Cost per Pack | Under USD 2.50 per student (onboarding → pack → 1 CV + 1 motivation letter) | Validates that pre-warmed catalogue queries replace the USD 100 tap (B.4.15). |
| 5. Onboarding Completion Time | Under 20 minutes median (including transcript upload and cell confirmation) | Tests whether the 22-question progressive flow (B.1.3) and Azure OCR review (B.5) cause drop-offs (C.6.2). |
| 6. Willingness to Pay (WTP) | At least 4 of 10 pay a real 39–49 AZN fee for the final Consultation Report, or 2 of 10 commit to the full cycle | Tests commercial demand against "40 tabs + ChatGPT". |

### 6.2 What I Would Build in the Next 8 Weeks (Answering A.5 Open Discovery #3)

If this were my company, I would impose a strict feature freeze on new search/scraping architectures and execute this 8-week critical path:

**Weeks 1–2: Unblock the Core Pipeline & Security Blocker**

- Build Gen-2 card engine "slice 3" (storage & serving) and rip out Gen-1 (B.4.9).
- Build the scheduled erasure executor (B.8.3) and remove the CV digest cache leak (C.4.3).
- Remove server-side portal password storage from Secrets Manager and CloudFormation (B.6.2, C.4.1, C.4.2).
- Expand the provenance gate (B.4.12) by importing the EU ECHE list, DEQAR, WHED, and Azerbaijan State Programme / TKTA lists.

**Weeks 3–4: Wire Fit Scoring, Living Costs & Pre-Warm Top 6 Corridors**

- Replace the 50 fit placeholder (B.4.14) with ISCED-F field matching + pgvector embeddings + career lookup rules.
- Seed static monthly living-cost baselines for the top 30 European/Turkish student cities (C.2.9).
- Run offline operator-supervised sweeps + Gen-2 reads for Germany, Hungary, Turkey, Italy, Poland, and Erasmus Mundus, plus the top 40 outbound scholarships for Azerbaijani citizens (including Dövlət Proqramı, Türkiye Bursları, Stipendium Hungaricum, DAAD, Chevening, Visby, MAECI/DSU, IsDB). Clear the operator resolution queue (B.4.17).

**Weeks 5–6: Product Polish, Manual Apply Kit & Payment Integration**

- Un-gate the Motivation Letter UI (B.5, B.9) and build the downloadable "Apply-by-Hand Kit" (B.1.6 10-10) so students aren't trapped if the extension fails.
- Expose official source URLs on paid cards (B.1.6 08-28) and add per-card verification timestamps.
- Incorporate entity and integrate a payment gateway (e.g., Epoint.az / Kapital Bank for AZN cards, or Stripe via US LLC).

**Weeks 7–8: 10-Student Shadow Pilot & Paid Beta Launch**

- Run the 10-student shadow pilot (Section 6.1), audit every card produced, fix rule edge cases, and open paid B2C Beta in time for the January–March 2027 master's and scholarship deadlines (Erasmus Mundus, Hungaricum, Türkiye Bursları, DAAD, Italian regional calls).

---

## 7. Opportunities You Haven't Considered (Open Discovery)

### 7.1 Defensibility Against "40 Tabs + ChatGPT" and Incumbents (A.3 Discovery, A.5 Open #1)

Why won't a bright student just use Perplexity + ChatGPT?

Where ChatGPT fails catastrophically:

- **Combinatorial Funding Math:** ChatGPT doesn't know that an Azerbaijani citizen admitted to the University of Bologna or Sapienza with a family income under EUR 24,000 (ISEE Parificato) qualifies for an Italian regional DSU grant (free tuition + EUR 7,000–8,000 stipend + canteen), or how to prepare the exact Azerbaijani notarized/apostilled income and property documents required for ISEE Parificato.
- **The Azerbaijan State Programme (Dövlət Proqramı / DP) Matrix:** Every year, the Azerbaijani Ministry of Science and Education publishes an exact spreadsheet of eligible foreign universities and priority master's programmes for full state funding. Navigating which programmes are on the DP list, have open deadlines, match the student's bachelor's degree (TKTA compatibility), and meet IELTS/GPA cutoffs is a painful relational join problem that ChatGPT hallucinates constantly.
- **Bilateral Intergovernmental Quotas (HTP / Hökumətlərarası Təqaüd Proqramları):** In Azerbaijan (Hungary, China, Romania, Latvia, Kazakhstan, Turkey), students must apply through both the portal (portal.edu.az / SIAC) and the host country system (e.g., Tempus DreamApply for Stipendium Hungaricum) on strict staggered deadlines.

**Your Unfair Moat:** Turn Dövlət Proqramı (DP), HTP dual-application workflows, TKTA degree recognition + military deferment rules, and Italian ISEE Parificato / German Sperrkonto financial calculators into first-class deterministic modules in Elmify. No global aggregator (StudyPortals, ScholarshipPortal) or US AI wrapper (ondere, ApplyBoard, LeapScholar) will ever build localized bureaucratic intelligence for Baku and Istanbul.

### 7.2 Competitors & Adjacent Products to Study (A.5 Open #1)

- **B2B / Commission Aggregators:** ApplyBoard, Adventus.io, Edvoy, idp.com. Lesson: They monetize university commissions from tuition-charging Anglo universities (UK, Canada, Australia) and ignore tuition-free continental Europe and external scholarships. Position Elmify explicitly as the "Fiduciary, Commission-Free Alternative" that shows free and funded public universities agencies hide.
- **Scholarship Directories:** ScholarshipPortal / StudyPortals, DAAD Database, MastersPortal, Scholars4Dev, WeMakeScholars (India). Lesson: High traffic, terrible personalization, stale deadlines, no document/application execution.
- **AI Grad-School Copilots:** Kollegio.ai, Cialfo, Ambitio (India). Lesson: Heavy focus on US undergraduate/grad essays; weak on verified European/bilateral funding math and multi-document evidence ledgers.

### 7.3 Missed Regulations & Platform Policies (A.5 Open #2)

- **Chrome Web Store "Single Purpose" & User Data Policies (B.8.1):** Google's Chrome Web Store review team aggressively rejects MV3 extensions that request broad host permissions (`*://*/*` or `<all_urls>`) to read DOM snapshots and inject scripts across arbitrary university portals (B.6.1). Mitigation: Use `activeTab` permission triggered explicitly when the user clicks the extension icon on a portal page, rather than persistent `<all_urls>` content scripts; otherwise CWS review will delay your launch by weeks.
- **Google OAuth Restricted Scope (CASA Tier 2) Delay (B.6.3):** You noted Google requires CASA above 100 users (B.6.3). What you may not realize is that Google Workspace / Gmail restricted scope verification + TAC security lab review takes 4 to 10 weeks and can cost USD 500–4,500 depending on the assessor tier. Alternative: Instead of full inbox OAuth (`gmail.readonly`), give each student a unique forwarding/inbound address or have them set up a 1-click Gmail auto-forwarding filter for emails from university domains, OR rely on manual status updates for the first 100 users while CASA is pending.
- **Azerbaijan Education Consulting & Tax Nuances:** Ensure your terms explicitly frame Elmify as a Self-Service Software & Document Formatting Tool rather than a guaranteed placement intermediary, and verify VAT (ƏDV 18%) and simplified tax (Sadələşdirilmiş vergi) rules if incorporating locally in Azerbaijan vs. cross-border digital service rules if billing from a US/EU entity.

---

## 8. Questions Back to You

To finalize any follow-up architectural or financial modelling, I need your answers to these 7 pivotal questions:

1. **Runway & Team Bandwidth (A.2, B.10):** Is the engineering team strictly a solo founder working with AI coding agents, or are there other engineers/counsellors on payroll? What is your monthly cash burn limit before revenue must cover AWS + API vendor bills?
2. **Target Launch Window vs. Admission Calendar:** Master's scholarship deadlines for the Autumn 2027 intake peak between November 2026 and March 2027 (e.g., Erasmus Mundus: Dec–Feb; Stipendium Hungaricum: Jan 15; Türkiye Bursları: Jan–Feb; DAAD: Oct–Dec; Azerbaijan DP: Spring/Summer). Are you aiming to catch the Jan–March 2027 wave (requiring a live product within 6–8 weeks)?
3. **Target Price Anchor (B.1.4):** What rough price range in AZN were you envisioning for the Consultation Report and the Full Platform Fee?
4. **Gen-1 vs. Gen-2 Cutover (B.4.9):** Is anything outside the funding search pipeline coupled to Gen-1's schema, or can Gen-1 be deleted the moment Gen-2 "slice 3" writes to the catalogue tables?
5. **Transaction Wrapping on RLS (B.7):** Is `ATOMIC_REQUESTS = True` enabled globally in Django settings for `runtime_web`, and does every SQS worker task wrap its DB session in `transaction.atomic()` before calling `SET LOCAL` for the RLS tenant ID?
6. **State Programme (DP) Integration (B.4.5, B.4.12):** Have you already parsed the Azerbaijani Ministry of Science and Education's official 2026/2027 Dövlət Proqramı (DP) priority universities and programmes PDF/list into your closed lists (B.4.5), or is that still pending?
7. **Counsellor Capacity (B.1.5, B.6.1):** Since flagged documents, first applications on each new portal, and extension read-back mismatches still route to a human counsellor (B.1.5), who is acting as that counsellor at launch—you alone, or a contracted specialist?

---

## 9. Follow-up: Hidden Gems (reviewer's second answer)

Received 2026-10-24, after the owner pushed back that narrowing to flagships throws away the moat. Saved word for word; formatting rebuilt.

Fair pushback. If Elmify only returns DAAD, Stipendium Hungaricum, Erasmus Mundus, and Türkiye Bursları, a student with ChatGPT and two hours on Google doesn't need you. The long tail—the funding an LLM can't regurgitate because it isn't on Top-20 aggregator blogs—is your actual moat.

Here is the problem: your current pipeline rules in B.4.9, B.4.12, and B.4.13 are accidentally configured as an anti-hidden-gem filter.

Right now, your search layer (B.4.5) is built to find hidden gems, while your reading, provenance, and serving layers (B.4.9–B.4.14) are built to throw them away.

### 9.1 The Hidden-Gem Paradox in Your Code

Think about what a flagship scholarship looks like on the web versus what a true hidden gem looks like:

**Flagship schemes (DAAD, Chevening, Hungaricum):** Have dedicated portals and 15-page call PDFs that explicitly state the exact monthly stipend, duration, periodicity, intake year, nationality list, and deadline in clean prose. They pass every strict completeness gate in B.4.9 and B.4.13.

**True hidden gems:**

- A German Stiftung (from your 353-funder sweep, B.4.5) or one of the 4,076 Turkish VGM foundations whose 300-word local-language webpage says: "We award master's grants to promising chemistry and engineering students; apply by letter to the board before May 15"—without stating the exact EUR/TRY monthly amount on the public page.
- A university faculty page or Excellence Cluster / Graduate School that buries a two-sentence paragraph inside the curriculum tab: "Up to 5 incoming international M.Sc. students per cohort receive an excellence tuition waiver + EUR 800/month stipend from industry sponsors; all applicants admitted before March 1 are automatically considered."
- A regional, diaspora, or municipal fund that only states the previous cycle's call date and a contact office.

Look at what happens when those hidden gems hit your pipeline today:

- **The Card Completeness Gate (B.4.13 & B.4.9):** B.4.13 states: "An award page that states no amount or deadline is a candidate the pack can't show." And in Gen-2 (B.4.9): "A held field hides its award until fixed." Because small foundations and departmental fellowships frequently omit at least one schema field (e.g., exact amount is "according to need" or deadline is "with programme admission"), your strict completeness rule kills the hidden gems and only lets the big bureaucratic flagships survive.
- **The 5-Country Provenance Choke-Point (B.4.12):** If your page-voiced search discovers an obscure, fully funded departmental fellowship at Uppsala University (Sweden), ETH/EPFL (Switzerland), KU Leuven (Belgium), or TU Wien (Austria), your provenance gate marks it Unconfirmed and blocks it from the pack because only Germany, England, Turkey, Korea, and Azerbaijan have registers loaded (C.2.6).
- **The Disconnected Tap (B.4.15):** Even if a student has a $100 wallet to hunt for niche awards in their exact subfield, Stage 2 (reading the newly discovered hosts) isn't wired up (C.2.2).

### 9.2 Where "Hidden Gems" Actually Live (and Why ChatGPT Misses Them)

To keep the hidden-gem promise without going broke on $100 per-student web sweeps, separate hidden gems into four distinct buckets:

| Hidden Gem Bucket | Why ChatGPT / Aggregators Miss It | Your Best Weapon in B.4 |
|---|---|---|
| 1. Buried Departmental & Graduate-School Funding (The #1 Master's goldmine: LabEx/EUR grants in France, DFG/Max Planck grad schools in Germany, faculty non-EU tuition waivers in NL/Sweden/Italy) | Buried 3–4 clicks deep on faculty subdomains; never indexed as a "scholarship" by aggregators; changes by department. | Domain-restricted Exa pass per university ($0.022/institution, B.4.5) + Site-job /map (B.4.6). |
| 2. "Dark Matter" Register Funders (4,076 VGM foundations in Turkey, 353+ German Stiftungen, Swiss cantonal/private trusts, religious & affinity funds) | Zero English SEO; written in first-person local language ("Vakfımız...", "Unsere Stiftung..."); <1% reachable by topic search (B.4.5). | The Register Ladder + Name→Site Resolver + Jev Host Classifier ($0.0001/host, B.4.5). |
| 3. Structural "De Facto Free" Routes (Conditional differential-fee exemptions, income-tested brackets like ISEE Parificato, automatic merit waivers on admission) | Requires cross-referencing university fee regulations with nationality/income rules—not a single "scholarship" page. | In-scope fee rules (B.4.4) + Affordability Calculator (B.4.14). |
| 4. Hyper-Niche Subfield / Profile Grants (Professional societies, industrial chairs, specific research-topic trusts, bilateral city/diaspora funds) | Only surfaces when querying the exact intersection of (subfield + local language + funding angle). | Per-Student Surgical Tap (B.4.15) using page-voiced queries. |

### 9.3 How to Keep the Hidden-Gem Engine (Without the $100 Burn or Empty Packs)

You don't need to abandon global hidden-gem discovery. You need to fix four mechanisms so the engine actually delivers them at sustainable unit economics:

**Fix 1: Create a "Verified Lead / Hidden Gem" Card Tier (B.4.9, B.4.13)**

Stop requiring a small Stiftung or a departmental grant to have the same 12-field bureaucratic completeness as Erasmus Mundus.

- **Tier A — Fully Specified Award Card:** Has verified existence, eligibility, exact amount, and exact deadline. Enters the Affordability gap math directly (B.4.14).
- **Tier B — Verified Hidden-Gem Lead Card (New):** Requires unanimous model agreement + verbatim quote on Existence ("Yes, this body/department funds master's students") and Eligibility (no hard failure for the student), even if the exact amount or exact deadline is unstated on the page (e.g., "Amount not published online — awarded upon foundation board review" or "Considered automatically with M.Sc. admission").
- **How it renders:** Show it in a dedicated "Hidden Gems & Unadvertised Funding to Pursue" section of the pack, with the exact verbatim quote, the official URL, and a 1-click drafted inquiry email (B.4.11 style) to the foundation or department coordinator.

**Fix 2: Split "Spine Pre-Warming" from the "Surgical Student Tap" (B.4.5, B.4.15)**

In my audit, I told you to kill the $100 per-student search wallet (B.4.15). Here is the nuance: kill the $100 wallet for broad corridor discovery, and replace it with a $2–$4 Surgical Niche Tap per student.

- **Why your Tap currently costs up to $100:** Because the catalogue is nearly empty (B.4.18), the first student interested in "Chemistry in Germany or France" pays out of their wallet to run broad coverage passes across those countries (B.4.15).
- **The Better Split:**
  - **Offline Spine (Platform CapEx, run once per cycle):** Run the $0.022 domain-restricted Exa pass across the top 1,500 accredited research universities (~$33 total!, B.4.5) and run the Jev host classifier across the national foundation registers (~$4 per 4,000 foundations, B.4.5). That builds 90% of your hidden-gem repository before a student ever logs in.
  - **Runtime Student Tap ($2–$4 cap, run on onboarding):** When a student finishes the questionnaire with a specific niche (e.g., "M.Sc. in Chemoinformatics / Computational Chemistry, looking for funded lab/fellowship tracks in Europe"), the Tap runs only 15–25 hyper-targeted page-voiced queries combining their exact research keywords + local languages. That finds the last-mile hidden gems specific to their profile for $2.50 instead of $100.

**Fix 3: Open the Provenance Gate via Bulk Registers + Parent-Domain Inheritance (B.4.12)**

Hidden gems die if B.4.12 only trusts 5 countries.

- **Bulk-load 40+ countries this week:** Ingest the EU ECHE list (every Erasmus-chartered university in 33 countries with official domains), DEQAR, and WHED. That takes 2 days of engineering and immediately unlocks Europe, EEA, Turkey, and major global research hubs.
- **Verify Departmental Gems via Parent-Domain Inheritance:** You already have the rule in B.4.5 (keying on registrable domain via the Public Suffix List) and B.4.12 (structural links from a recognized parent). Make sure that any lab, graduate school, or excellence cluster hosted on a subdomain of a recognized university (e.g., csc.unistra.fr under unistra.fr, or imprs.mpg.de under mpg.de) automatically inherits Recognised provenance without needing an operator click.

**Fix 4: Use the "Anchor + Alpha" Pack Design (B.4.14)**

If you only show hidden gems and miss an obvious flagship (because a flagship page blocked your scraper on Rung 1–4), the student loses trust. If you only show flagships, the student says "ChatGPT told me this for free."

Structure every Consultation Report around Anchor + Alpha:

- **The Anchor Layer (100% Curated Recall):** The ~50 major bilateral, government, and Erasmus Mundus schemes pre-verified by your team so you never have an embarrassing false negative on DP, Hungaricum, DAAD, Eiffel, DSU, or Türkiye Bursları.
- **The Alpha Layer (The Hidden-Gem Moat):**
  - Departmental / University-Specific Waivers & Fellowships found via the $0.022 domain-restricted institution sweeps (B.4.5).
  - Non-SEO Private Foundations (Stiftungen / Vakıflar / Trusts) extracted from national registers and local-language page-voiced sweeps (B.4.5).
  - Nomination & Inquiry Targets where the platform drafts the exact cold email to the programme coordinator or foundation office (B.4.11).

### 9.4 Summary of What Changes in My Recommendation

| Dimension | Original Audit Recommendation | Revised "Hidden-Gem First" Recommendation |
|---|---|---|
| Geographical Scope | Narrow to 8 corridors + 50 flagships. | Unlock 40+ countries immediately via bulk ECHE/DEQAR/WHED provenance lists (B.4.12), and run the $0.022/uni domain pass across the top 1,500–2,000 target universities (~$33–$44 total search cost). |
| Per-Student Tap (B.4.15) | Kill the $100 runtime search wallet completely. | Keep the Tap, but rescope it to a $2–$4 "Niche Subfield Hunt" (15–25 page-voiced queries on the student's specific field/thesis keywords) while moving broad country/register sweeps offline. |
| Card Serving Rule (B.4.9, B.4.13) | Serve partial cards with unconfirmed badges. | Explicitly introduce a "Hidden-Gem Lead Card" tier: if existence + verbatim funding quote + eligibility pass, serve the card even if amount or deadline is unstated, paired with an auto-drafted inquiry email. |
| The Value Pitch | End-to-end affordable application execution. | "ChatGPT gives you the same 10 famous scholarships 50,000 people are fighting over. Elmify reads 2,000+ university faculty subdomains and national foundation registers in their native languages to find the unadvertised grants you can actually win." |

To pressure-test this right now: pick one real student profile (e.g., an Azerbaijani B.Sc. graduate in Chemical Engineering or Computer Science with a 16/20 GPA and 7.0 IELTS, needing full or near-full funding). If we run your existing B.4.5 sweep + Gen-2 reader on that profile today, how many departmental or foundation hidden gems does it actually extract before the provenance and completeness gates filter them out?

### 9.5 Decisions on the hidden-gem follow-up (2026-10-24)

Checked against `origin/master` (`e5258ea2`); see also section 10 and the round-3 decisions in section 11.

| Point | What the code shows | Decision |
|---|---|---|
| 9.1 "An award with no amount or deadline can't be shown" | **Mostly false for the live reader.** Gen-1 serves an award that is agreed, offered, and names a benefit kind or a money form; no amount is required (`apps/research/funding_reader.py::_served`). The award gate passes when no deadline is stated (`evaluation.py`, deadline check needs a date). The sentence the reviewer quotes is not in the code. Gen-2: only a `held` field hides an award; `not_stated` does not | No change for Gen-1. Gen-2's serve rule is the core/detail split (11.2, item 2.1) |
| 9.1 Provenance covers 5 countries | True: registers for GB (England, Scotland), DE, KR, TR, plus Azerbaijan's curated list; Sweden, Switzerland, Belgium, Austria are `no_register` | Bulk lists (11.2, item 4.2) |
| 9.1 The tap's stage 2 is not connected | True (`tap_seams.bound_host_reader` → `NullSeams`) | Waits for slice 3 |
| 9.2 Weapons: domain-restricted Exa pass, Jev host classifier | `exa_site_search` exists with no discovery caller; only the frontier classifier exists (~$0.002 a host, so ~$8 rather than ~$4 for 4,000 foundations) | Wire the domain pass (11.2, item 3.2); a Jev classifier stays optional |
| Fix 1: "lead card" tier + drafted inquiry email | The card already distinguishes `not_stated` from `held`. Nothing in `apps/` drafts an inquiry email today | **Accept the tier** as part of the slice-3 serve rule. **Defer the email** to after slice 3 (owner call: it is a new student-facing feature) |
| Fix 2: offline spine + $2–4 niche tap | Wallet is `SEARCH_WALLET_USD` = $100; a FIRST search has no query cap. Platform-paid area sweeps already exist ($5, run by hand) | **Accept the direction, owner call on the numbers.** Lower the wallet to a few dollars and keep the FIRST search to the student's own niche; broad coverage moves to scheduled area sweeps. Nothing changes until stage 2 reads hosts |
| Fix 3: bulk registers + subdomain inheritance | Subdomains already inherit: verdicts are keyed on the registrable domain (`tests/research/test_hosts.py`: `sub.dept.uni-hamburg.de` → `uni-hamburg.de`) and `hosts.is_institutional_url` accepts institutional subdomains, refusing only user-content labels and `/~user` paths | **Inheritance: no change needed.** Bulk lists as in 11.2, item 4.2; DEQAR/WHED only as evidence behind the gate, never the deleted screen (`.claude/rules/institution-safety-screen.md`) |
| Fix 4: "Anchor + Alpha" pack | The anchor schemes exist as closed lists (`az_outbound_gov`, `az_bilateral`, `tr_outbound_gov`, `tr_bilateral`, `igo_regional_global`), but the enumerators gate failed and their origins are unverified | **Accept.** Anchor: verify those lists' origins and read them. Alpha needs slice 3. The report's layout is an owner call |
| The new pitch | — | Owner's call |
| The pressure test | — | Protocol written: `docs/superpowers/2026-10-24-hidden-gem-pressure-test.md` |

---

## 10. Code check (not the reviewer's text)

Spot-check of the claims both answers rest on, read on `origin/master` at `e5258ea2` (2026-10-20). Not a full audit: claims not listed here are unchecked.

| Claim | What the code shows | Verdict |
|---|---|---|
| Fit dimensions hardcoded to 50; balanced needs 80 overall / 60 each (finding 1) | `apps/funding/facts.py:66` `_NEUTRAL = Decimal("50")` for every upstream dimension; `apps/funding/evaluation.py:67-68` sets the 80 / 60 bars. The comment at `facts.py:60-65` says the fix is upstream fit scoring. | True |
| Gen-2 card engine cannot store or serve (finding 3) | Every `apps/research/card_funding/*` module says nothing is stored until slice 3. | True |
| Tap stage 2 is not wired (finding 3; 9.1 "Disconnected Tap") | `apps/research/tap_seams.py:177` `bound_host_reader()` returns `NullSeams`: stage 2 records new hosts, reads none, and the tap ends `STAGE2_UNAVAILABLE`. | True |
| The tap is switched off (finding 6) | `apps/research/tap.py:296` does nothing unless `TAP_AUTOMATIC`. | True |
| Portal passwords in Secrets Manager (finding 5) | `apps/portals/credentials.py`: one secret per student per portal, under its own KMS key. | True |
| Retired EC2 portal tier still in CloudFormation (finding 16) | `infra/template.yaml:3491-3603` still holds the role, profile and auto-scaling group. Branch `claude/retire-portal-tier` (`e024e058`) deletes it but is not merged and sits on an old base. | True |
| Erasure executor unbuilt (finding 4) | `apps/audit/management/commands/execute_due_erasures.py` is built and tested; no EventBridge rule runs it (`.claude/rules/derived-data-and-erasure.md`). | Partly: only the schedule is missing |
| An unstated amount or deadline hides a hidden-gem award (9.1 "Completeness Gate") | Gen-2 has three field states (`apps/research/card_funding/card.py:40`): `shown`, `held`, `not_stated`. Only `held` (readers disagree or code cannot read the value) hides the award; a field the readers agree the page leaves out is `not_stated`. Whether a card with a `not_stated` amount reaches the pack is slice 3's serve rule, which is unbuilt. In the pack math, an amount that is missing or not `EXACT` is not counted (`apps/funding/facts.py:90-93`). | Partly: true of `held`, not shown for `not_stated` |
| Subdomains must inherit the parent's provenance (Fix 3) | Provenance is looked up by `registrable_domain` (`apps/research/provenance.py:243`), so `csc.unistra.fr` is judged as `unistra.fr`. | Appears already true; not tested |
| Source URLs hidden from students (finding 9) | The pack page shows an "Official source" link with its domain and last-checked date (`templates/student/_candidate.html:15-16`). The application board card uses the URL only as its "Open programme page" button, and the Consultation Report shows no link. | Mostly false: shown on the pack, missing from the report |

---

## 11. Reviewer round 3 (2026-10-24): fixes before real students, and what we decided

The reviewer read the full engine description (`docs/superpowers/2026-10-24-search-engine-how-it-works.md`) and proposed five "silent killer" fixes, three Gen-2 rule changes before slice 3, a programme-discovery spine, gate unblocks, a keep list, and a 6-commit sequence. Below, each item is checked against `origin/master` (`e5258ea2`) and given a decision. "Owner call" marks a product decision the owner must make; the recommendation is ours.

### 11.1 Code checks behind the decisions

| Reviewer's premise | What the code shows | Holds? |
|---|---|---|
| Mandatory-funding students pass gate 10 only on automatic funding | `apps/funding/evaluation.py:331-341`: needs a current benefit that is `ORDINARY` and `VERIFIED`; only `AUTOMATIC_ON_ADMISSION` becomes `ORDINARY` (`facts.py`) | Yes |
| `self_funding_capacity` is ignored | Its only reader is `apps/research/tap_query.py:59` (a search-output filter); the evaluator and affordability never read it | Yes |
| An unknown application fee bypasses the budget | `apps/funding/pack.py:277-280`: `fee_known` is false but the fee is 0, so the programme lands in `fee_free` and spends no budget; the stored copy shows the fee as unknown (`services.py:197`) | Yes for the budget; the display is already honest |
| The tap rebuilds without exchange rates | `apps/research/tap.py:416, 963` call `rebuild_pack(run)`; `rates` defaults to `None` (`services.py:160`) | Yes |
| The hunt stays on the start site | `apps/research/card_funding/seek.py:207-211`: a lead must share the start page's registrable domain *and* be provenance-recognised | Yes |
| The hunt does not transliterate | `awards.names_award` matches on `names.fold()`, which is `anyascii` + casefold; "Bolashak"/"Болашак", "Türkiye Bursları"/"Turkiye Burslari", "Dövlət Proqramı"/"Dovlet Proqrami" all fold equal (run 2026-10-24). The plan text saying "no transliteration" is stale | **No** — already done |
| The EACEA run's 424 blocked leads were Gen-1's fault | The 09-16 run's `blocked=424` are fetch-level blocks (no egress at the time), not reader refusals; the 08-30 run lost rows before reading too (494 leads → 9 rows) | **No** — the bottleneck was fetching as much as reading |
| Fixing fit with ISCED makes balanced packs non-empty | The balanced bar needs **every** dimension ≥ 60. ACADEMIC, PROGRAM, CAREER and AFFORDABILITY always apply; ISCED informs only the first two, so CAREER at a neutral 50 still fails the floor | **Incomplete** — CAREER needs a score too |
| A transliteration library must be added | `anyascii` is already a direct dependency (`pyproject.toml`) | No new dependency needed |

### 11.2 Decisions

| # | Recommendation | Decision | Notes |
|---|---|---|---|
| 1.1 | Mandatory-funding gate passes when a selective award could close the gap | **Accept, owner call on wording.** Pass gate 10 when the guaranteed gap fits self-funding *or* an eligible, not-ended selective award would close it if won. Keep the money math as it is (selective money stays conditional), label the programme "affordable only if you win X", and order it scholarship-first. | "Open or upcoming" cannot be checked yet (cycle verification is off), so use the existing award gate: not suspended or ended, deadline not passed |
| 1.2a | Gen-2 writes `CostComponent` (tuition, application fee) | **Accept** as part of slice 3; retire `reader.py` once Gen-2 writes cost rows | Gen-2's card already asks `fees` |
| 1.2b | Unknown fee must not ride free | **Accept, owner call on the number.** Put unknown-fee programmes in their own "fee not known" group and cap how many a pack holds. Don't use a made-up default fee, because that would invent a number | Owner sets the cap |
| 1.3 | Use `self_funding_capacity` in the gap | **Accept.** Shortfall = max(gap − capacity, 0); use it in gate 10 and in affordability | Capacity is optional for mandatory students, so treat missing as 0 |
| 1.4 | Tag programmes with ISCED-F buckets; pool by bucket | **Accept, extended.** Tag at ingestion (cheap model call against the existing 27 buckets). Score ACADEMIC/PROGRAM from bucket match + keyword overlap first; add embeddings only if a measurement shows the need. **CAREER also needs a real score** or the 60 floor still empties balanced packs | No pgvector until measured |
| 1.5a | Pass rates into the tap's rebuild | **Accept** | One-line change at two call sites |
| 1.5b | Render the empty-pack reason and coverage line | **Accept** | Already computed, never shown |
| 1.5c | Source link in the Consultation Report | **Owner call (corrected 2026-10-24).** Leaving the URL out of the report is a recorded owner decision: P1-7.1 as amended 2026-08-28, which the 2026-10-04 dashboard amendment lifted for the pages but not the report. A test pins it (`tests/reports/test_consultation_report.py::test_report_content_has_required_sections_and_no_internal_reasoning`) | Not changed in the fixes branch |
| 2.1 | Split card fields into blocking core and non-blocking detail | **Accept, owner call (it changes the slice-2 rule "a held field hides its award").** The core set should also hold the fields that decide eligibility or status: holder kind, target level, nationality, money form, discontinued, window closed. Detail fields that are held are shown as "Unconfirmed on page — check the official source" and never enter the money math | "Offered/existence" is the award itself, not a field |
| 2.2 | Let the hunt leave the start site onto recognised domains | **Accept.** Drop the same-site test in `seek.py:211` and keep the provenance-recognised test (government zones are already recognition sources). Keep the 6-page cap and strict name attach | The strict attach is what stops a same-named award on another site from attaching wrongly |
| 2.3a | Transliterate award names | **Reject: already built** (`anyascii` fold) | Add a test with the Kazakh form "Болашақ" (қ folds to "q", not "k") |
| 2.3b | Attach to a page's only award without a name match | **Defer** until the hunt measurement shows misses caused by name mismatch | Strict attach is the deliberate safe direction |
| 3.1 | Re-read the 169 EACEA sites with Gen-2 as the first end-to-end run | **Accept** after slice 3 | The "9 → 120+ rows" figure is the reviewer's guess; measure it, and check the fetch path first |
| 3.2 | Replace sitemap expansion with domain-restricted Exa + Firecrawl `/map` on recognised universities | **Accept** | `exa_site_search` already exists; it needs a discovery caller |
| 3.3 | Harvest (institution, page URL) from 6 national catalogues; read pages on the university | **Accept, owner call on terms.** Start with Finland's Studyinfo API (already measured: 1,285 master's) | The repo refused a DAAD adapter on terms grounds; each catalogue needs the same terms check unless the owner decides otherwise |
| 4.1 | Unblock funder sweeps with a master's-level check | **Accept, using Gen-2's `target_level`** on the funder's award page after slice 3. A homepage classifier question would mostly answer "unclear" | Can ship as a cheap pre-filter where "unclear" passes |
| 4.2 | Add ECHE, an official Azerbaijani HEI list, and the State Programme university list | **Accept.** Add them as curated or funder lists with a hand reason (ECHE is a charter, not an ENIC-NARIC register). First confirm the ECHE file carries websites, because without them nothing binds. For Azerbaijan, run `verify_list_origins` against the ministry page `az_heis` already cites | Unverified: the ECHE file's columns |
| 4.3 | Turn on resolver writes for rung 0 (own-domain e-mail) and rung 1 (Wikidata exact); send lower rungs under 0.90 to the operator queue | **Accept** | Splits `RESOLVER_WRITES_ENABLED` by rung; the `SITE_UNKNOWN` queue exists |
| 5 | Keep the fetch ladder, Gen-2's architecture, page-voiced sweeps and the money rules | **Agree.** Leave rung 5 off | — |
| Plan | Six commits in 10 days, slice 3 first | **Reorder.** Ship the small, independent fixes first (1.5a–c, 1.2b, 1.3, 1.1), because they don't wait on slice 3. Then ISCED tagging and pool. Then provenance lists. Then slice 3 with the core/detail split and the cross-domain hunt. Delete Gen-1 only once Gen-2 serves. Then the EACEA end-to-end run | Slice 3 is the critical path and the largest item; its design spec is on branch `claude/verified-catalog-design`, and owner round 2 (which proves the ≤ 1% target) is still owed |

### 11.3 Owner decisions (2026-10-24)

1. **Gate 10 (mandatory funding):** pass when an eligible, still-open selective scholarship would close the gap if won. Money math stays strict, the programme is labelled "affordable only if you win X", and it is ordered scholarship-first. **Scope (owner, same day):** two kinds of money count. The first is the programme's own selective funding, whose amounts must close a costed gap. The second is a big scheme (Hungaricum, Türkiye Bursları and the like) that the student is eligible for, that states FULL tuition and FULL living, and that the page's grouping rule links to the programme: its list, its institution, or the same country. A scheme from the student's own country (the State Programme, HTP) is never linked by country, because its country is the holder's and it pays for study abroad. It counts once it carries its university list.
2. **Card serving (slice 3):** split the fields. Blocking core: holder kind, target level, nationality, money form, discontinued, window closed. Any other held field is shown as "Unconfirmed — check the official source" and never enters the money math.
3. **Unknown application fee:** its own "fee not known" group, at most 3 per pack, never counted as free.
4. **National programme catalogues:** use all of them. The owner states we have permission, so no per-catalogue terms check.
5. **Consultation Report:** show official source links (the pack page's citation: link, domain, last-checked date). This reverses the 2026-08-28 decision for the report.
6. **Per-student search:** about $5 per student for the student's own niche only; broad country and register sweeps become platform-paid, scheduled area sweeps.
7. **Uncosted programmes:** show "not yet costed" instead of "Funding gap: 0.00", and leave them out of the total.
8. **Self-funding on the page:** keep the funding gap and add a line, "After the X a year you said you can cover: Y left to find".
