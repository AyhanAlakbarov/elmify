# SEO & Generative Engine Optimization (GEO) for Elmify (Master's-Only Scope)

**Date:** 2026-11-01  
**Evidence Base:** `scilit` (`--profile argon` via `codex/argon` subscription; run `20261101T150837Z-d8815b85`, 229 papers consulted across arXiv, OpenAlex, and Semantic Scholar, 25 top papers judged at Relevance 3/3) + 2026 primary documentation and open-source tool repositories.

---

## 1. Platform Scope Constraint: Master's Programmes Only (Never PhD or Bachelor's)

Elmify exclusively serves **Master's programmes (`MSc`, `MA`, `LLM`, `MRes`, `MBA`) and Master's-level scholarships abroad**.
- **Codebase enforcement:**
  - [`apps/research/search.py`](../../apps/research/search.py) (`_PHD_ONLY_PATH_TERMS`) and [`apps/research/catalogue_hop.py`](../../apps/research/catalogue_hop.py) (`_PHD_PATH_RE`, `_PHD_ONLY_RE`, `_UNDERGRAD_ONLY_RE`) filter out doctoral, postdoctoral, and undergraduate URLs and announcements.
  - [`apps/research/card_funding/store.py`](../../apps/research/card_funding/store.py) enforces Spec §3.1: `bachelor`, `phd`, and `postdoc`-only tracks are never written to student cards.
  - [`apps/accounts/consultation.py`](../../apps/accounts/consultation.py), [`apps/accounts/question_widgets.py`](../../apps/accounts/question_widgets.py), and [`apps/accounts/forms.py`](../../apps/accounts/forms.py) now label the post-Master's research career option as `"Go into academic research"` / `"Go into academic research after graduating"` so the word `"PhD"` never appears as a student-facing option in the consultation or review screens.
- **SEO/GEO implication:** Both human visitors and AI answer engines (ChatGPT Search, Perplexity, Google AI Overviews, Gemini, Claude) frequently conflate "graduate school scholarships" with PhD fellowships. Every page title, meta description, `JSON-LD` entity definition, `llms.txt` file, and FAQ block must explicitly declare that Elmify covers **Master's programmes and Master's scholarships only** (excluding Bachelor's, PhD/doctoral, and postdoctoral tracks).

---

## 2. Empirical Science of GEO & SEO (`scilit` + `argon` Literature Synthesis)

### 2.1 Foundational & Competitive Content Signals
1. **Aggarwal et al. (ACM KDD 2024 / `arXiv:2311.09735`, *GEO: Generative Engine Optimization*):**
   - Evaluated 9 black-box optimization strategies across **10,000 queries** (`GEO-bench`, 25 domains) and live **Perplexity.ai** using Position-Adjusted Word Count (`Word` + `Pos`) and Subjective Impression:
     - **Quotation Addition** (attributable statements/quotes from named sources): **+40.9%** relative improvement in Position-Adjusted Word Count (+28% Subjective Impression; +22% on live Perplexity).
     - **Statistics Addition** (replacing vague claims with concrete quantitative metrics, thresholds, and counts): **+30.6%** improvement in Position-Adjusted Word Count (+23% Subjective Impression; +37% on Perplexity).
     - **Cite Sources** (verifiable references to primary sources): **+27.5%** overall improvement, and **+115.1%** visibility increase for lower-ranked websites (SERP Rank 5).
     - **Fluency Optimization & Easy-to-Understand** (clean syntax, plain prose): **+15% to +30%** lift.
     - **Technical Terms** (domain-accurate terminology such as `ECTS`, `CEFR B2/C1`, `CGPA`, `Erasmus Mundus`): **+18%** lift.
     - **Keyword Stuffing** (repeating keywords unnaturally): **-8.3% to -10%** *reduction* in generative visibility (penalized by LLM synthesis).
2. **Vishwakarma, Kumar & Jamidar (ACM 2026, `DOI: 10.1145/3805712.3808445`, *What Gets Cited: Competitive GEO in AI Answer Engines*):**
   - Executed **252,000 controlled RAG trials** across **6 LLMs** and **18 content factors** testing which of two retrieved sources receives the **first citation marker**:
     - **Topical relevance** and **early list/chunk position** are the strongest predictors of first-citation selection.
     - **Explicit price/cost information** (e.g., `"free during early access"`, exact tuition/stipend coverage) and **recent timestamps** (`2026`) consistently increase first-citation probability across all 6 LLMs.
     - Cosmetic formatting-only edits without new factual completeness yield negligible gains.
3. **Zhang, He & Yao (`arXiv:2604.25707`, 2026, *From Citation Selection to Citation Absorption*):**
   - Analyzed **21,143 valid search-layer citations** across ChatGPT, Google AI Overview/Gemini, and Perplexity (602 prompts, 72 page features):
     - Distinguishes **Citation Selection** (being linked) from **Citation Absorption** (having the page's exact definitions, facts, and structure incorporated into the AI's synthesized answer).
     - Perplexity and Google cite more URLs on average (breadth), whereas ChatGPT cites fewer URLs but absorbs significantly more text per cited page (depth).
     - High-absorption pages are rich in **extractable evidence**: self-contained entity definitions, numerical facts, explicit comparisons, and numbered procedural steps.
4. **Chen & Koudas (2026, *What Drives AI Citations? Content, Retrieval and Model Knowledge in GEO*; & `arXiv:2509.08919`, 2025, *How to Dominate AI Search*):**
   - Analyzed **158,099 AI answers** and **468,037 citations**:
     - **Sub-query semantic matching dominates:** ChatGPT rewrites user prompts into specific search sub-queries. Whether a page is retrieved by those rewritten sub-queries explains **32%** of citation variance (vs. 2.8% for isolated page-level cosmetic tweaks).
     - **Within-site winner signal:** Pages whose headings (`<h1>`–`<h3>`, `<summary>`) and lead paragraphs directly match the natural-language questions users ask are cited significantly more often.
     - **Cross-site baseline signals:** FAQ blocks, `JSON-LD` structured data, summary boxes, and fast page speed act as cross-website eligibility gates.
     - **Earned media bias:** AI engines heavily weight third-party earned media (Reddit, YouTube, editorial comparisons, `.edu`/official directories) alongside corporate websites (which account for ~78% of direct brand citations in Kumar, `arXiv:2606.20065`, 2026).
5. **Yu, Yang, Ding & Sato (`arXiv:2603.29979`, 2026, *GEO-SFE: Structural Feature Engineering for GEO*):**
   - Decomposed page structure into **macro-structure** (logical H1→H2→H3 hierarchy), **meso-structure** (atomic 40–60 word information chunking, ordered lists, `<dl>` definition lists), and **micro-structure** (semantic emphasis). Across 6 generative engines, structural optimization alone improved citation rate by **+17.3%** and subjective quality by **+18.5%**.
6. **Yu et al. (`arXiv:2609.40069`, 2026, *Conversational Capture in Multi-turn Human-Agent Interaction*):**
   - Proved via Pólya-urn reinforcement modeling that a source cited in **Turn 1** of a user's AI conversation achieves a compounding capture ratio exceeding **2x within 10 turns** because follow-up user questions and history-conditioned RAG retrieval anchor on the entities named by the first-cited source.
7. **Ullrich (`DOI: 10.5281/zenodo.21434669`, 2026, *The Retrieval-to-Citation Funnel in AI Search*):**
   - Across 13,200 domain-engine observations, pooled retrieval-to-citation conversion is **55.6%** (**40.9%** in ChatGPT, **76.8%** in Google AI Overviews), and cited domain overlap across engines is low (**Jaccard 0.12–0.21**), requiring coverage in **both Google Search Console and Bing Webmaster Tools** (which feeds ChatGPT Search and Copilot).

---

## 3. Best Free & Open-Source SEO / GEO Tools (2026 Stack)

### 3.1 Open-Source & Self-Hosted GEO / AEO Toolkits (100% Free, MIT/Apache)
| Tool | Repository / Access | What It Does | Best Use for Elmify |
|---|---|---|---|
| **GEO Optimizer** | `github.com/Auriti-Labs/geo-optimizer-skill` (Python CLI + MCP, MIT, 1.1k★) | Audits on-page GEO readiness (`llms.txt`, `JSON-LD`, heading hierarchy, citation-ready chunks, crawler access) and tracks whether ChatGPT, Perplexity, Gemini, and AI Overviews cite your domain. | Run locally in CI or CLI against `web/` before every release to verify GEO score and schema completeness. |
| **Elmo** | `github.com/elmohq/elmo` (TypeScript, MIT, 464★) | Self-hosted AEO/GEO tracking platform across ChatGPT, Claude, Perplexity, Gemini, Copilot, Grok, and Google AI Overviews with auditable code metrics. | Self-host with your own API keys to track weekly share-of-voice on 30–50 funded Master's prompts. |
| **GetCito Open-Source** | `github.com/ai-search-guru/getcito-worlds-first-open-source-aio-aeo-or-geo-tool` (Next.js/TS, MIT, 491★) | Open-source AI visibility tracker + AI Crawlability Clinic monitoring bot behavior and prompt trends. | Track competitor agencies and scholarship portals across AI engines. |
| **GEORank** | `github.com/yaojingang/GEORank` (Next.js + FastAPI, 504★) | Open-source GEO ranking and citation absorption evaluator (aligned with `geo-citation-lab` / `arXiv:2604.25707`). | Measure not just whether Elmify is linked, but how much of Elmify's explanation is absorbed into AI answers. |
| **eGEOagents** | `github.com/mverab/eGEOagents` (Python CLI + MCP, 204★) | Multi-agent content optimizer for ChatGPT, Perplexity, Gemini, and Claude citation readiness. | Test landing page and guide copy drafts against simulated RAG retrieval before publishing. |

### 3.2 Free Hosted GEO / AI Visibility Graders (No Credit Card Required)
| Tool | Free Tier Scope | Engines Covered | What It Measures |
|---|---|---|---|
| **HubSpot AI Search Grader** | 100% Free (no account required) | ChatGPT, Perplexity, Gemini | Baseline brand visibility, share of voice, sentiment, and archetype perception in AI answers. |
| **Mangools AI Search Grader** | 100% Free (full 6-model set with free account) | ChatGPT, Gemini, Claude, Mistral, Llama 4, DeepSeek | Calculates an AI Search Score (0–100) comparing your brand against competitors across 6 distinct LLM families. |
| **AthenaHQ Free Tier** | Free tier (300 credits) + 10-minute GEO audit | ChatGPT, Perplexity, Google AI Overviews, AI Mode, Gemini, Claude, Copilot | Prompt-level citation tracking, source URL attribution, and hallucination detection (checking if an LLM falsely claims Elmify covers PhDs). |
| **Geoptie Free GEO Audit & Rank Tracker** | 100% Free web tools | ChatGPT, Perplexity, Google AI Overviews | On-page GEO content audit, citation density check, and free AI keyword/prompt finder. |
| **Gumshoe AI** | Free (Public Beta) | ChatGPT, Perplexity, Gemini, Claude | Persona-based visibility analysis (e.g., "Pakistani BSc CS student looking for funded Master's in Germany"). |
| **Ahrefs Free SEO & AI Tools** | Free Webmaster Tools (`ahrefs.com/webmaster-tools`) + Free Keyword Generator | Google, Bing, YouTube + Site Audit | Full technical site audit, backlink monitor, and keyword difficulty for verified domain owners at $0. |

### 3.3 Mandatory Free Search & AI Crawler Infrastructure
1. **Google Search Console (GSC):** Essential for Google organic ranking, Google AI Overviews, and Gemini grounding. Submit `/sitemap.xml` and inspect URL indexing.
2. **Bing Webmaster Tools + IndexNow (Free):** **Critical for GEO.** ChatGPT Search (`OAI-SearchBot`) and Microsoft Copilot rely heavily on the Bing index alongside OpenAI's own crawler. Verified GSC sites can be imported into Bing Webmaster Tools in 1 click, and `IndexNow` pings Bing/ChatGPT immediately when pages change.
3. **Cloudflare AI Audit (Free Tier):** Monitors live HTTP requests from `OAI-SearchBot`, `ChatGPT-User`, `GPTBot`, `PerplexityBot`, `ClaudeBot`, `Claude-SearchBot`, and `Google-Extended` so you can verify that AI search bots are actually fetching `/` and `/llms.txt` with `HTTP 200`.
4. **Schema Markup Validator (`validator.schema.org`) & Google Rich Results Test (`search.google.com/test/rich-results`):** Free official validators for `SoftwareApplication`, `FAQPage`, `Organization`, and `WebSite` JSON-LD graphs.

---

## 4. High-Intent Keyword & Conversational Prompt Map (Master's-Only)

Traditional searches average **4.2 words**, while AI search prompts average **23 words** (`awesome-generative-engine-optimization`, 2026). Optimizing Elmify's copy requires bridging both:

| Cluster | Traditional SEO Keywords (Google / Bing) | Conversational GEO Prompts (ChatGPT / Perplexity / Gemini / Claude) | Target Entities & Proof Points Required on Page |
|---|---|---|---|
| **1. Funded Master's Discovery** | `funded master's programmes in Europe`, `fully funded master's scholarships 2026`, `master's scholarships for international students` | *"Which fully funded master's scholarships in Europe are open to students from Azerbaijan, Pakistan, India, or Turkey, and how do I check if my GPA qualifies?"* | **Erasmus Mundus Joint Masters**, **DAAD Study Scholarships**, **Stipendium Hungaricum**, **Swedish Institute Scholarships**, **Chevening**, **Türkiye Bursları**, **NL Scholarship**; grouped by funding source with tuition, monthly stipend, travel allowance, and intake deadlines. |
| **2. Eligibility & Requirement Matching** | `master's eligibility checker Europe`, `check GPA and IELTS for master's abroad`, `master's scholarship requirement matcher` | *"Is there an AI tool that reads official university master's pages and checks my transcript, ECTS credits, GPA, and IELTS score against admission rules?"* | **Primary-source sentence links**, **ECTS credit thresholds** in prior Bachelor's coursework, **CGPA conversion**, **CEFR language rules** (`B2`/`C1`, IELTS Academic, TOEFL iBT, TestDaF, Medium of Instruction waivers), **application fee budgets**. |
| **3. Zero-Fabrication Document Preparation** | `AI motivation letter for master's scholarship`, `academic CV builder for master's application`, `scholarship essay and reference letter planner` | *"What is the best AI tool to prepare a master's motivation letter and academic CV without hallucinating or inventing achievements?"* | **Zero-fabrication guarantee** (every line traced to confirmed transcript/CV facts), **programme-specific motivation letters**, **scholarship essays**, **distinct referee briefing points** per recommender, **side-by-side portal submission workspace**. |
| **4. Master's-Only Disambiguation** | `master's application tracker`, `study abroad agency software for master's` | *"Does Elmify support PhD or undergraduate applications, or is it only for master's degrees?"* | Explicit statement: **Master's degrees (`MSc`, `MA`, `LLM`, `MRes`) and Master's scholarships only** — Bachelor's, PhD/doctoral, and postdoctoral calls are excluded by design. |

---

## 5. Website Copy & Technical GEO/SEO Changes Applied (`web/`)

Based on the empirical findings above, the following changes were implemented in [`web/`](../../web/):

1. **Metadata & Canonical/Robots Configuration ([`web/app/layout.tsx`](../../web/app/layout.tsx)):**
   - Updated `<title>` and OpenGraph/Twitter titles to `"Elmify — AI Platform for Funded Master's Programmes & Scholarships Abroad"`.
   - Updated meta description to name concrete Master's degree types (`MSc`, `MA`, `LLM`, `MRes`), major scholarship families, profile matching (grades, ECTS credits, IELTS/TOEFL, budget), and verified document drafting.
   - Added `metadataBase`, `alternates.canonical`, `keywords`, and explicit `robots` directives (`max-snippet: -1`, `max-image-preview: "large"`).
2. **Structured Data `@graph` ([`web/app/page.tsx`](../../web/app/page.tsx)):**
   - Added sanitized `<script type="application/ld+json">` containing linked `Organization`, `WebSite`, `SoftwareApplication` (`applicationCategory: "EducationalApplication"`, `offers.price: "0"`, `featureList`), and `FAQPage` (generated directly from the exported `faqs` array in `sections.tsx` so visible HTML and structured data never drift).
3. **Entity-Rich, Zero-Fluff Copy ([`web/app/_components/hero.tsx`](../../web/app/_components/hero.tsx) & [`web/app/_components/sections.tsx`](../../web/app/_components/sections.tsx)):**
   - **`Hero`:** Added an explicit Master's-only scope eyebrow (`Master's programmes & scholarships only`) and sharpened the subheadline to name exact matching dimensions (transcript grades, ECTS credits, IELTS/TOEFL scores, and budget) and document outputs (CV, motivation letters, and referee briefs).
   - **`HowItWorks`:** Enriched the 3 stages with concrete domain entities (`MSc, MA, LLM, and MRes` official pages; `ECTS credit rules, GPA minimums, language certificates (IELTS, TOEFL, TestDaF, or Medium of Instruction waivers), nationality rules, and fee budgets`; `academic CV, motivation letters, scholarship essays, and distinct referee talking points`).
   - **`Product`:** Named real scholarship programmes (`Erasmus Mundus, DAAD, Stipendium Hungaricum, Chevening, Swedish Institute, and university waivers`) and concrete board/document capabilities while keeping the compact bento card layout intact.
   - **`Faq`:** Expanded to 7 self-contained, 40–60 word citation-ready answers covering pricing, covered countries/scholarships, explicitly excluding PhD and Bachelor's programmes, how primary-source verification prevents AI fabrication, how CV/letters/referee briefs are prepared, browser-side submission control, and data privacy.
4. **AI Crawler & Sitemap Routes ([`web/app/robots.ts`](../../web/app/robots.ts), [`web/app/sitemap.ts`](../../web/app/sitemap.ts), [`web/public/llms.txt`](../../web/public/llms.txt)):**
   - `robots.ts` explicitly permits `*`, `Googlebot`, `Bingbot`, `OAI-SearchBot`, `ChatGPT-User`, `GPTBot`, `PerplexityBot`, `ClaudeBot`, `Claude-SearchBot`, `Applebot`, and `Google-Extended`.
   - `sitemap.ts` exposes the canonical landing page and `/llms.txt`.
   - `public/llms.txt` provides a clean Markdown reference for LLM agents and answer engines, explicitly stating the Master's-only scope, supported scholarships, 3-step verification workflow, agency white-label capabilities, and canonical URLs.
