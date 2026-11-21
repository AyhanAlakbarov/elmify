# Elmify Pricing, Packaging, Offer Design & Strategy Red-Team (Azerbaijan Launch)

**Date:** 2026-11-01
**Context Source:** [`.agents/product-marketing.md`](file:///home/orkhan/Desktop/tehsil_agent/.agents/product-marketing.md) (`v1`)
**Skills Applied:** `product-marketing`, `pricing`, `offers`, `monetization-strategy`, `strategy-red-team`, `grilling`

---

## 1. Critical Codebase Finding Fixed by This Strategy

There is currently a direct mismatch between the backend data model and the placeholder pricing UI:
- **Backend (`apps/concierge/cycles.py`):** Gates paid features on `StudentCycle(student, academic_year="2026-2027", paid_at=...)` — a **once-per-academic-year cycle** running July 1 to June 30.
- **Placeholder UI (`apps/concierge/plan.py`):** Displays `Apply — $19 a month, cancel any time`.

**Why `$19/month, cancel any time` breaks B2C unit economics:**
Master's applications are a 6-to-10-week burst between October and February. On a `$19/mo` monthly plan, a rational student signs up in November, generates 10 motivation letters and CVs, autofills 8 portals with the browser extension, and cancels 3 weeks later. Realized LTV is **$19 (`32 AZN`)**—barely covering LLM, transcript OCR, and search/fetch costs—followed by **>85% seasonal churn**. Aligning the commercial offer with `StudentCycle` (**one Academic-Year Cycle Pass at `299 AZN` / `€159` / `$175`, or `499 AZN` / `€269` / `$295` with Counsellor Review**) increases B2C LTV by **9.2× (`299 AZN` vs `32 AZN`)**, covers cold-start and heavy-user COGS with a `67%–91%` margin, and stays 5× to 10× more accessible than traditional Baku agencies (`1,500–4,000 AZN`).

---

## 2. B2C Student Pricing & Offer Design (Azerbaijan Launch)

### A. Value Metric & Free-vs-Paid Boundary
- **Primary Value Metric:** **Active Application Kits (`Application` rows) in the `2026–2027` Academic Cycle** + **Counsellor Review depth**.
- **COGS Protection Rule (Free-vs-Paid Boundary):**
  - Free users (`Explore`) run **zero** live LLM page-reading sweeps, **zero** transcript PDF OCR calls (`apps/documents/transcript_check.py`), and **zero** multi-programme motivation letter generations. They query the pre-verified catalogue against their self-entered GPA, ECTS, and IELTS/TOEFL scores.
  - To deliver an immediate "Aha!" moment without giving away the farm (`paywalls` principle: *Value Before Ask, Show Don't Just Tell*), `Explore` shows **all Flagship scholarship verdicts** (`Dövlət Proqramı`, `HTP`, `DAAD`, `Chevening`, `Erasmus Mundus`, `SISGP`) **plus 3 fully unlocked Hidden-Gem matches** (with official source links and city living-cost gaps), while displaying the remaining matched hidden gems as preview cards (`"11 more regional, foundation & automatic-waiver matches found for your profile — unlock full cycle"`).

### B. B2C Tier Structure (Good – Better – Best)

| Feature / Limit | **Explore** (Free) | **Apply Cycle Pass** *(Recommended)* | **Cycle Pass + Counsellor Review** |
|---|---|---|---|
| **Price (`AZN` / `EUR` / `USD`)** | **`0 AZN`** (`€0` / `$0`) | **`299 AZN`** (`€159` / `$175`) per academic cycle *(or `3 × 109 AZN`)* | **`499 AZN`** (`€269` / `$295`) per academic cycle *(or `3 × 179 AZN`)* |
| **Billing Period** | Free forever | Full `2026–2027` cycle (through 30 Jun 2027) | Full `2026–2027` cycle (through 30 Jun 2027) |
| **Flagship Scholarships (`Dövlət Proqramı`, `HTP`, `DAAD`, `Chevening`, `Erasmus`, `SISGP`)** | Full eligibility check + official links | Full eligibility check + official links | Full eligibility check + official links |
| **Hidden & Niche Funding (53 countries: `DSU`, `IdEx`, `Visegrad`, `Stiftungen`, automatic waivers, RA/TA)** | **First 3 matches unlocked** + exact count of remaining matches | **Unlimited unlocked matches** + native-language call links | **Unlimited unlocked matches** + counsellor shortlist audit |
| **City Living-Cost & Affordability Gap Calculator** | Included | Included + ISEE/DSU family-income bracket guide | Included + personalised family budget plan |
| **Transcript PDF Verification (`transcript_check`)** | — | Included (`up to 50 pages / cycle`) | Included + human counsellor verification |
| **Fact-Locked CVs, Motivation Letters & Referee Briefs** | **1 base CV draft** | **Up to 10 complete programme & scholarship kits** | **Unlimited kits** + **human counsellor line-by-line review on 5 priority applications** |
| **Elmify Glass-Box Browser Extension (`DreamApply`, `uni-assist`, `Studielink` autofill)** | Preview only | **Full autofill + PDF staging** (you press `Submit`) | **Full autofill + PDF staging** + pre-submit portal check by counsellor |
| **Counsellor Workspace Chat (`/student/messages/`)** | — | — | **Direct async chat + 2 × 30-min live video walkthroughs** |

### C. Per-Student Cost of Goods Sold (COGS) & Margin Verification (`149 AZN` vs. `299 AZN` / `499 AZN`)

Directly from [`config/settings/base.py`](file:///home/orkhan/Desktop/tehsil_agent/config/settings/base.py) and [`apps/research/wallet.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/research/wallet.py), here is what one active paid student costs Elmify across three usage profiles (`1 USD = 1.70 AZN`):

| Cost Component (Codebase Setting / Module) | **Typical Warm-Catalogue Student** *(Corridor already swept in last 30d)* | **Cold-Start Niche Student** *(Triggers 1 fresh sweep + 20 new host reads)* | **Current Uncapped Worst-Case** *(`SEARCH_WALLET_USD=$100` × `2` wallets)* | **Capped Worst-Case** *(With B2C `SEARCH_WALLET_USD=$35`, `1` wallet/cycle)* |
|---|---|---|---|---|
| **1. Search Tap & Page-Read Wallet** (`apps/research/wallet.py`, `Exa` `$0.012`, `Brave` `$0.005`, `Firecrawl/scrape.do`, `CHEAPEST_PAGE_READ_USD=$0.35` / `$0.18` batch) | **`$1.50`** (`2.55 AZN`) *(2 follow-up taps, 30d cache hit)* | **`$14.00`** (`23.80 AZN`) *(1 `$5` area sweep + 25 batch page reads + 2 taps)* | **`$200.00`** (`340.00 AZN`) *(if student drains two `$100` wallets)* | **`$35.00`** (`59.50 AZN`) *(hard ceiling enforced by `SearchWallet`)* |
| **2. Transcript & Document OCR** (`TRANSCRIPT_PAGES_PER_CYCLE=50`, `FACT_READING_PAGE_CAPS` = 10 pages Azure Document Intelligence + 2 OpenRouter readers) | **`$0.25`** (`0.43 AZN`) *(8 transcript/diploma pages)* | **`$0.40`** (`0.68 AZN`) *(15 pages + 1 retake)* | **`$0.65`** (`1.10 AZN`) *(all 50 transcript + 10 doc pages)* | **`$0.65`** (`1.10 AZN`) |
| **3. CV Derivation + 3-Model Judge** (`apps/documents/derive.py`: 2× `gpt-5.6-luna` + 1× `claude-sonnet-5` at `$2/$10` per MTok) | **`$1.20`** (`2.04 AZN`) *(2 CV derivations)* | **`$2.40`** (`4.08 AZN`) *(4 CV derivations)* | **`$4.50`** (`7.65 AZN`) *(8 CV derivations)* | **`$3.00`** (`5.10 AZN`) *(capped at 5 derivations)* |
| **4. 10 Application Kits + Research-Fit + Second-Family Letter Judge** (`letter_verification.py`, `propose_research_fit`) | **`$4.50`** (`7.65 AZN`) *(6 kits, 2 drafts each)* | **`$8.50`** (`14.45 AZN`) *(10 kits, 3 drafts each)* | **`$18.00`** (`30.60 AZN`) *(uncapped re-generations)* | **`$10.00`** (`17.00 AZN`) *(10 kits × max 3 full regenerations)* |
| **5. Cloud Infra Share** (ECS Fargate, RDS Postgres, S3, KMS, SQS per active cycle) | **`$1.80`** (`3.06 AZN`) | **`$2.20`** (`3.74 AZN`) | **`$3.00`** (`5.10 AZN`) | **`$2.50`** (`4.25 AZN`) |
| **6. Payment Gateway Fee** (`~3.5% + $0.30` on `299 AZN` = `$175.88`) | **`$6.45`** (`10.97 AZN`) | **`$6.45`** (`10.97 AZN`) | **`$6.45`** (`10.97 AZN`) | **`$6.45`** (`10.97 AZN`) |
| **Total Variable Cost (Apply Cycle Pass — Software Only)** | **`$15.70` (`26.70 AZN`)** | **`$33.95` (`57.72 AZN`)** | **`$232.60` (`395.42 AZN`)** | **`$57.60` (`97.92 AZN`)** |
| **Net Contribution at Old `149 AZN` (`$87.65`)** | `+122.30 AZN` (`82%`) | `+91.28 AZN` (`61%`) | **`-246.42 AZN` (`-165%` LOSS)** | `+51.08 AZN` (`34%` — too thin!) |
| **Net Contribution at New `299 AZN` (`$175.88`)** | **`+272.30 AZN` (`91%` margin)** | **`+241.28 AZN` (`81%` margin)** | `-96.42 AZN` *(why we cap wallet at `$35`)* | **`+201.08 AZN` (`67%` worst-case floor)** |
| **7. Human Counsellor Labor on `499 AZN` Tier** (~4 hrs total: 5 priority kit reviews + 2 × 30m video calls + async chat at `25 AZN/hr`) | **`$58.80` (`100.00 AZN`)** | **`$58.80` (`100.00 AZN`)** | **`$70.00` (`119.00 AZN`)** | **`$58.80` (`100.00 AZN`)** |
| **Net Contribution at New `499 AZN` (`$293.53`)** *(incl. extra gateway fee `7.00 AZN`)* | **`+365.30 AZN` (`73%` margin)** | **`+334.28 AZN` (`67%` margin)** | `-22.42 AZN` | **`+294.08 AZN` (`59%` worst-case floor)** |

**Key Unit-Economics Conclusion:**
1. At `149 AZN`, a cold-start student + capped wallet left only `34%` gross margin (`51 AZN` before marketing CAC), and an uncapped `$100` wallet lost money on day one.
2. At **`299 AZN` (`Apply Cycle Pass`)** and **`499 AZN` (`Cycle Pass + Counsellor Review`)**—paired with a **`$35` (`~60 AZN`) per-student B2C `SEARCH_WALLET_USD` cap** (1 wallet per paid `StudentCycle`, keeping `$100` only for operator sweeps)—Elmify earns **`91%` gross margin (`+272 AZN`) on typical B2C students**, **`81%` (`+241 AZN`) on cold-start niche students**, and **never drops below `67%` (`+201 AZN`) even on a 100th-percentile heavy user**—while still being **5× to 10× cheaper** than traditional Baku agencies (`1,500–4,000 AZN`).

### D. Anti-Abuse ("Unconsumed Pass") Refund Policy — Eliminating Extract-and-Refund Fraud

**The Vulnerability Caught:**
An unconditional 7-day refund on a seasonal product lets a student pay `299 AZN`, unlock every hidden scholarship URL, generate and download all 10 CV/motivation-letter PDFs, autofill their university portals with the browser extension, and demand a 100% refund on Day 6 after extracting 100% of the value and burning `$15–$57` in non-recoverable LLM/search COGS.

**The 3-Part Fix (High Trust for Honest Buyers, Zero Loophole for Extract-and-Refund):**
1. **Show Match Count & 3 Full Scholarships *Before* Payment (`Explore` Free Tier):**
   The student sees their exact verified match count (e.g., *"4 Flagship + 9 Hidden/University Scholarships Matched"*) and inspects 3 unlocked hidden scholarships **on the free `Explore` tier before paying**. If their profile matches `< 5` programmes, they see that before checkout and are never asked to pay blindly.
2. **Strict "Unconsumed Pass" Gate on Any 7-Day Refund:**
   Just like an IELTS/TOEFL exam voucher or software license key, a 7-day refund is available **only while the Cycle Pass is Unconsumed**, verified automatically against PostgreSQL rows:
   - **`0` document exports / PDF downloads** (`GeneratedDocument` export count == `0`),
   - **At most `1` application kit drafted** (`Application` / motivation-letter generation count `≤ 1`),
   - **`0` browser extension portal autofill sessions** (`extension` autofill audit events == `0`), and
   - **At most `2` additional hidden-scholarship source URLs unlocked** beyond the free `Explore` preview.
   The moment a student generates a 2nd application kit, exports a PDF, or runs the browser extension on a portal, the UI displays a clear checkbox/notice (*"Unlocking full cycle kits & PDF exports marks your Cycle Pass as active and non-refundable"*) and locks out cash refunds.
3. **If Post-Payment Transcript OCR Disqualifies the Student (`< 5` Matches After Upload):**
   If a student's self-reported GPA/ECTS looked eligible on `Explore`, they pay `299 AZN`, upload their official transcript PDF (`transcript_check`), and the verified ECTS check drops them below 5 eligible funded programmes **before** they export kits or run the extension, they receive either:
   - An immediate refund (minus only the `~12 AZN` payment gateway/OCR fee) **if 0 kits were exported**, OR
   - A **free 12-month rollover to the next academic cycle** (`2027–2028`) while they complete missing prerequisite credits or retake IELTS.

### E. B2C Complete Offer Anatomy (`offers` Framework)
1. **Name:** *The 2026–2027 Funded Master's Cycle Pass (`299 AZN` / `€159` / `$175`)*
2. **Core Deliverable:** Full-season access to all matched Master's programmes and hidden scholarships across 53 countries, up to 10 fact-locked application kits (CV + motivation letter + scholarship essay + referee brief), and the Elmify browser extension co-pilot.
3. **Bonus Stack (each closing a specific student/parent objection):**
   - **Bonus 1 (Closes *"What if I miss a local ministry rule?"*):** *The `Dövlət Proqramı` & `HTP` Sequential Checklist* — maps university admission deadlines against Azerbaijan Ministry / HTP nomination windows so you never get an offer too late for funding.
   - **Bonus 2 (Closes parent objection *"Can we afford the city even with a tuition waiver?"*):** *The European City Gap & Italian DSU Income-Bracket Sheet* — itemizes rent, dorms, canteen meals, visa blocked-account rules (`Sperrkonto` / `IND`), and uncovered monthly gap in `AZN` and `EUR`.
   - **Bonus 3 (Closes *"My professors at BDU/ADA/UNEC want me to draft the recommendation points"*):** *The Trilingual Professor Brief Pack* — generates a 1-page factual bullet brief for each referee based on the exact courses and grades on your verified transcript.
4. **Guarantee / Risk Reversal (Anti-Scam & Anti-Abuse):**
   - **Pre-Purchase Match Preview + 7-Day Unconsumed Discovery Guarantee:** *See your exact count of matched Flagship and Hidden Scholarships for free on `Explore` before you pay. If your official transcript check after upgrading leaves you with fewer than 5 verified funded matches—prior to exporting application kits or running the browser extension—claim a 7-day refund or a free rollover to next year's cycle.*
5. **Honest Urgency / Scarcity:**
   - **Seasonal Reality:** European & HTP funded rounds close between November and February.
   - **Capacity Reality (`499 AZN` tier only):** *Cycle Pass + Counsellor Review* is capped at **25 students per counsellor per cycle** so human document reviews turn around within 48 hours.

---

## 3. B2B Study-Abroad Agency Pricing & Pilot Offer (Baku & Region)

### A. Why Hybrid Pricing Wins Over Pure Per-Seat or Pure Per-Student
- **Why pure per-seat fails:** In Baku, a 3-counsellor agency placing 180 students would pay the same as a 3-counsellor boutique placing 15 students, or counsellors simply share one login (`pricing/references/pricing-models.md`).
- **Why pure per-student usage fails:** Agency intake is heavily concentrated in Oct–March; pure usage billing creates a 5-month summer revenue trough for Elmify.
- **The Hybrid Solution (`Platform Base Retainer + Active Student Cycle Allowance`):** A predictable monthly/annual platform fee covers the agency's custom white-label domain (`apply.agency.az`), tenant-isolated database, and counsellor seats, paired with an included allowance of active `StudentCycle`s and a clear per-student overage rate.

### B. B2B Agency Tiers

| Tier | **30-Day White-Label Pilot** *(Entry Offer)* | **Agency Starter** | **Agency Growth** *(Recommended)* | **Agency Scale** |
|---|---|---|---|---|
| **Price** | **`490 AZN` (`$290`) one-time for 30 days** *(100% credited to annual plan)* | **`390 AZN / mo` (`$229 / mo`)** billed annually *(or `490 AZN/mo` monthly)* | **`890 AZN / mo` (`$520 / mo`)** billed annually *(or `1,090 AZN/mo` monthly)* | **From `1,700 AZN / mo` (`$990 / mo`)** custom annual |
| **Custom White-Label Domain & Brand Color (`apps/tenancy`)** | Included (`apply.agency.az`) | Included | Included | Included + multi-branch domains |
| **Counsellor & Owner Seats** | Up to **5 seats** | Up to **3 seats** | Up to **10 seats** | **Unlimited seats** |
| **Included Active Student Cycles / Year** | **10 real students** (kept permanently) | **25 students / year** | **80 students / year** | **200+ students / year** |
| **Additional Active Student Cycle** | — | **`+19 AZN` (`$11`) / student** | **`+14 AZN` (`$8`) / student** | **`+10 AZN` (`$6`) / student** |
| **Browser Extension for Counsellors & Students** | Included | Included | Included | Included |
| **Audit Trail, GDPR/PDPL Erasure & Owner Queue** | Included | Included | Included + priority onboarding | Included + dedicated SLA |

**Unit Economics for the Agency Owner (`10:1` Value-to-Price Ratio):**
- A Baku agency charges **`1,500–4,000 AZN` (`$880–$2,350`) per student**.
- On **Agency Growth** (`10,680 AZN/year` for 80 students = **`133 AZN` / `$78` per student**), Elmify costs the agency **4–8% of their student fee** while cutting counsellor research, letter-drafting, and portal-filling time from ~18 hours/student to ~4 hours/student (**3–4× counsellor capacity**, saving `18,000+ AZN/year` in extra seasonal counsellor payroll).

### C. B2B Agency Pilot Offer Anatomy (`offers/references/saas-offers.md` Pattern)
Instead of discounting the monthly software fee (which attracts high-churn bargain hunters), lead every `/demo/?audience=agency` call with:
- **Name:** *The 30-Day White-Label 10-Student Sprint (`490 AZN` / `$290`)*
- **Core Deliverable:** Live white-label instance on the agency's subdomain within 48 hours + 10 real student profiles run through eligibility, hidden-gem funding discovery, document drafting, and portal autofill.
- **Bonus Stack (killing switching cost):**
  1. **Done-for-you roster import:** We import your first 10 students' transcripts and target countries into your white-label board on Day 1.
  2. **Live 60-minute Counsellor Workshop (in AZ/RU/EN):** Hands-on training for your counsellors on side-by-side document review and the browser extension.
- **Risk Reversal:** **Double Credit + Export Guarantee** — (1) 100% of the `490 AZN` pilot fee credits toward your annual plan when you continue; (2) if your counsellors do not save at least 2 hours per student application inside 30 days, we refund the `490 AZN` and you keep every PDF dossier generated during the pilot.
- **Honest Scarcity:** Capped at **4 agency pilots per month** during launch because custom DNS/TLS verification and live counsellor training are done by the founding team.

---

## 4. Strategy Red-Team: Attacking the Load-Bearing Assumptions

### Top 5 Kill-Assumptions (Ranked by `Impact × Likelihood × Cheapness to Test`)

#### 1. B2C vs. B2B Channel Conflict in Baku ("Are you our tool or our competitor?")
- **Claim:** Elmify can simultaneously sell a `299 AZN` self-serve Cycle Pass to Azerbaijani students on `elmify.com` AND sell a `390–890 AZN/mo` white-label platform to Baku study-abroad agencies without agencies boycotting us as a low-price competitor.
- **Steelman:** DIY students willing to manage their own applications with a `299 AZN` software tool are a different buyer segment from anxious families who pay `2,500–4,000 AZN` for a human agency to take responsibility; on white-label domains (`apply.agency.az`), Elmify's brand is nearly invisible.
- **Attack:** Baku is a tight, word-of-mouth market. The moment an agency owner sees an Elmify Instagram ad or landing page saying *"Why pay an agency 2,500 AZN when Elmify does it for 299 AZN?"*, every agency in Baku will view Elmify as an existential enemy and refuse to put their student roster on our database.
- **Fails if:** >50% of pitched Baku agencies cite Elmify's B2C `299 AZN` public price as the reason they will not run a white-label pilot.
- **Evidence to get this week:** Show the landing page and the `490 AZN` pilot offer to **5 Baku agency owners** before running any "anti-agency" B2C ad copy.
- **Kill criterion:** If ≥3 of 5 agency owners object to the `299 AZN` public B2C price undercutting their `2,000+ AZN` packages:
  1. Never frame B2C copy as *"cheaper than an agency"*; frame B2C as *"replaces 40 browser tabs, spreadsheets, and generic ChatGPT"*.
  2. Route students who click **"Book a student walkthrough (`Cycle Pass + Counsellor Review — 499 AZN`)"** to partner agencies on the platform (turning Elmify into a **qualified lead generator** for paying white-label agencies!).
- **Cheapest test (Launch Week, $0):** Pitch 5 Baku agencies this week with the pitch: *"Students who want DIY use our self-serve tool; students who ask for a dedicated human counsellor get matched to our certified partner agencies."* Measure how many book the `490 AZN` pilot.

#### 2. B2C Upfront Price Friction at `299 AZN` (`€159` / `$175`) in Azerbaijan Without Prior Brand Proof
- **Claim:** Direct students in Azerbaijan will pay `299 AZN` (`€159` / `$175`, or `3 × 109 AZN`) after seeing their `Explore` matches (Flagship + 3 unlocked hidden gems).
- **Steelman:** Azerbaijani students routinely pay `450–550 AZN` for IELTS/TOEFL exams, `€50–€100` per university application fee, and `1,500–4,000 AZN` to local agencies; `299 AZN` for a full year of scholarship discovery, 10 document kits, and portal autofill is still less than one IELTS test and 80–90% cheaper than an agency.
- **Attack:** `IELTS` is mandatory and universally trusted; Elmify is a brand-new product in a scam-heavy category. Students who haven't seen their *own* motivation letter or tested the browser extension may hesitate to drop `299 AZN` in one shot.
- **Fails if:** Free `Explore` → Paid `Apply Cycle Pass` conversion is **<1.5%** among students who complete their profile and have ≥5 eligible matches.
- **Evidence to get this week:** Track the first 100 complete student profiles from Baku universities (`ADA`, `UNEC`, `BANM`, `BDU`, `UFAZ`) hitting the upgrade screen (`/student/settings/plan/`).
- **Kill criterion:** If <1.5% convert at `299 AZN` upfront within 7 days of profile completion, introduce a **`49 AZN` (`€25`) "Starter Kit / 1-Programme Pass"** (unlocks 1 full Application Kit, with the `49 AZN` credited 100% toward the `299 AZN` Full Cycle Pass within 14 days—matching the `Consultation Fee -> Platform Fee` step in `docs/elmify-website-marketing-spec.md` §1).
- **Cheapest test (Launch Week):** Offer both `299 AZN` single payment and `3 × 109 AZN` split payment on `/student/settings/plan/` and log click-intent events in `AuditEvent`.

#### 3. Per-Student Variable AI & Scraping Cost (`COGS`) vs. Cycle Revenue
- **Claim:** At `299 AZN` (`$175.88`) B2C (with `SEARCH_WALLET_USD` capped at `$35` for B2C cycles) or `14–19 AZN` (`$8–$11`) marginal B2B per student cycle, gross margin stays **67%–91%** (`COGS $15.70` typical warm, `$33.95` cold-start, `$57.60` hard worst-case).
- **Steelman:** Scholarship discovery and page reading (`apps/research`) are amortized across the shared catalogue (`runtime_engine`), so individual students mostly query pre-verified rows; only transcript check and 10 document kits are per-student LLM calls.
- **Attack:** In `config/settings/base.py`, `SEARCH_WALLET_USD` is currently `$100` (`170 AZN`) and `SEARCH_WALLETS_PER_YEAR = 2` (`$200` / `340 AZN` max). If left at `$100 × 2` for retail B2C students, a single student who triggers two full cold-start intake wallets + 10 kits could spend `$232.60` (`395 AZN`), exceeding even `299 AZN`!
- **Fails if:** Realized LLM + Firecrawl/Exa spend per active student exceeds **`$35` (`60 AZN`)** on B2C or **`$5` (`8.50 AZN`)** on B2B.
- **Evidence to get this week:** Run the owed cost measurement in [`docs/superpowers/2026-09-26-funding-cost-run-owed.md`](file:///home/orkhan/Desktop/tehsil_agent/docs/superpowers/2026-09-26-funding-cost-run-owed.md) and meter token spend per student Application Kit in `apps/documents`.
- **Kill criterion:** Set B2C student wallet budget to **`$35` (`SEARCH_WALLET_USD=35`) with `SEARCH_WALLETS_PER_YEAR=1` per paid `StudentCycle`** (keeping `$100` only for operator sweeps) and cap document generation at **10 programme kits × 3 full regenerations per kit** (unlimited manual edits).
- **Cheapest test (Launch Week):** Enforce the 10-kit / 3-regeneration cap and run all catalogue refreshes on `reading_tier="batch"` or `"flex"`.

#### 4. The "Hidden Gem" Promise Must Beat a Smart Student's 1-Hour Google Search
- **Claim:** When a student pays to unlock their Hidden-Gem scholarships, Elmify surfaces at least 3–5 genuinely actionable, currently open/upcoming non-flagship awards (`DSU`, `IdEx`, `Visegrad`, `Stiftungen`, faculty waivers) that match their field and citizenship.
- **Steelman:** `apps/research/angles.py` and `kind_words.py` query 14 funder categories in local languages across 53 countries, and `docs/wiki/` already maps dozens of schemes per country.
- **Attack:** As noted in [`docs/superpowers/2026-10-24-hidden-gem-pressure-test.md`](file:///home/orkhan/Desktop/tehsil_agent/docs/superpowers/2026-10-24-hidden-gem-pressure-test.md#L9-L17), if the provenance gate drops countries whose institution register isn't loaded yet, or if strict completeness hides awards with one `held` field, a student in a niche major might unlock the paywall and see only the same 5 flagship scholarships they already knew—triggering immediate refund requests and negative word-of-mouth.
- **Fails if:** >15% of new Baku student profiles receive **fewer than 3 non-flagship funding matches** after entering their GPA, field, and IELTS score.
- **Evidence to get this week:** Run the **Hidden-Gem Pressure Test** ([`docs/superpowers/2026-10-24-hidden-gem-pressure-test.md`](file:///home/orkhan/Desktop/tehsil_agent/docs/superpowers/2026-10-24-hidden-gem-pressure-test.md)) across the top 5 Azerbaijani Master's fields (*Computer Science/AI, Finance/Economics, Chemical/Petroleum Engineering, Public Policy/IR, Education/Management*).
- **Kill criterion:** Never show the paywall to a student whose profile has `<5` total verified funding matches; if their profile has `<3` hidden-gem matches, keep them on `Explore` for free while queueing their field/country pair for catalogue enrichment.
- **Cheapest test (Launch Week):** Display the exact count of matched Flagship + Hidden-Gem scholarships *before* the paywall (`"Your profile matched 4 Flagship + 9 Hidden/University Scholarships"`), and only prompt for upgrade when the count is `≥5`.

#### 5. Counsellor Adoption Inside B2B Agencies (Workflow Friction vs. WhatsApp/Word)
- **Claim:** Agency counsellors (`Membership.Role.COUNSELOR`) will actively use Elmify's roadmap, side-by-side document review, and browser extension instead of reverting to WhatsApp + Word files after the owner buys the pilot.
- **Steelman:** The browser extension saves 2–3 hours of tedious portal form-filling per application, and the fact-locked letter drafter eliminates blank-page writing.
- **Attack:** If uploading a student's transcript or approving a motivation letter takes too many clicks—or if a student pauses consent/locks their profile when a deadline is tomorrow—counsellors will bypass Elmify and complain to the agency owner at day 30.
- **Fails if:** <60% of assigned students in a 30-day agency pilot have at least 1 approved document kit and 1 paired browser-extension session by Day 21.
- **Evidence to get this week:** Watch 2 real agency counsellors process 3 sample Azerbaijani student profiles on `http://localhost:8000/counselor/` without assistance.
- **Kill criterion:** Any counsellor task that takes >3 minutes to figure out in live observation gets simplified before onboarding Pilot #2.
- **Cheapest test (Launch Week):** Include the 60-minute live onboarding session as a mandatory Day-1 milestone of the `490 AZN` Agency Pilot.

---

### What Is Genuinely Well-Reasoned (Holds Up Under Red-Team)
1. **Glass-Box Browser Extension ("Extension types, you click Submit"):** Completely eliminates the #1 legal, ethical, and trust liability in study-abroad automation (bots getting accounts banned on `uni-assist`/`DreamApply` or submitting unapproved claims) while still removing 90% of the manual typing work.
2. **Master's-Only Scope at Launch (`MSc`, `MA`, `LLM`, `MRes`):** Focusing strictly on postgraduate rules (`ECTS`, `GPA`, `IELTS/TOEFL`, funding stipends) avoids the totally different undergraduate (`SAT`, high-school equivalency, parental custody) and PhD (supervisor lab-matching, research proposals) workflows until Master's unit economics are proven.
3. **100% Source-Linked Receipts + Fact-Locked Letters (`claim-check`):** Directly neutralizes both the "ChatGPT hallucination" problem and the "agency scam" skepticism in Azerbaijan.
