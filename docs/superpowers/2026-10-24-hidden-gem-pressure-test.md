# Hidden-gem pressure test — how we will run it

Date: 2026-10-24. Answers the reviewer's closing question in the hidden-gem follow-up: *for one real student profile, how many departmental or foundation hidden gems does the current sweep + Gen-2 reader extract before the provenance and completeness gates filter them out?*

This is a measurement, not a build. It changes no gate and adds no feature. Its output is one funnel table that shows, for every hidden gem a human expert knows about, the stage where the pipeline found it or lost it.

## 1. What today's code can and cannot do (read on `master`, 2026-10-20)

The test has to work around three gaps, so the numbers mean "what the pipeline would serve", not "what a student sees today":

| Gap | What it means for the test |
|---|---|
| Gen-2 card engine has no storage or serving yet ("slice 3") | No real pack can be built. We read each page with Gen-2 and apply the serve rules offline (section 5, stage 5). |
| The tap's stage 2 reads nothing (`bound_host_reader()` returns `NullSeams`) | The per-student tap cannot carry a found host to the reader. We run discovery and reading as separate operator steps and join them by hand. |
| Fit dimensions are a neutral 50, under the 80/60 balanced bar | Ranking and the fit bar are left out. We test with a funding-first profile, which has no fit bar, so fit cannot hide anything. |

One more limit, which the test is meant to show rather than hide: Gen-2's `read_page` reads a page *for a programme*. A foundation page belongs to no programme, so foundation gems (bucket 2) are read by the older funder-page reader, and we record which reader handled each page.

## 2. The profile

Synthetic, with no real student's data:

- Azerbaijani citizen, B.Sc. Chemical Engineering, GPA 16/20, IELTS 7.0.
- M.Sc. intake autumn 2027, full or near-full funding required (`FUNDING_FIRST` strategy).
- Target fields: chemical / process engineering, with computational chemistry as the niche angle.
- Destinations: Germany, Turkey, France, Netherlands, Sweden, Italy. This mixes countries whose institution register is loaded with countries whose register is not, so the provenance gate's effect shows up in the numbers. Which side each country is on is recorded at run time, not assumed.

## 3. Ground truth, built before the machine runs

A human researcher who has not seen the machine output spends a fixed 4 hours building two lists for this profile:

1. **Anchor list.** The flagship schemes this student is eligible for (for example State Programme, Türkiye Bursları, DAAD, Eiffel, Erasmus Mundus programmes in the field, Italian DSU). This checks that the gates do not drop the obvious.
2. **Hidden-gem list.** Every departmental, graduate-school, foundation, regional or society award they can find, each with its URL, a verbatim quote showing it funds master's students like this one, and its bucket:
   - B1: department or graduate-school funding.
   - B2: foundation found through a register (Stiftung, vakıf, trust).
   - B3: a structural "de facto free" route (fee exemption, income-tested bracket, automatic waiver).
   - B4: a niche subfield or profile grant (society, industrial chair, diaspora or city fund).

The list is frozen before stage 1 runs. Gems the machine finds that the human missed are checked by hand and added as a separate "machine-only" count, so a short human list cannot make recall look better than it is.

## 4. Where it runs

- A separate database, so the sweep's new register rows and fetch records do not enter the shared catalogue. The repo's settings already give each checkout its own test database (`POSTGRES_DB`).
- Live vendor calls (search, fetch, models) with the normal ladder. The owner-kept settings stay as they are, including the paid-proxy fetch rung.
- A hard spending cap per stage (section 7). A stage that hits its cap stops, and the report says so.

## 5. The stages and what each one counts

Every candidate gets one row in a single CSV, with its stage outcomes in columns, so any gem can be followed from discovery to the end.

| Stage | What runs | What it counts |
|---|---|---|
| 0. Universe | Pick the institutions: the 40 universities with the strongest chemical-engineering departments across the six countries, plus the German and Turkish foundation registers. | Institutions and register rows in scope. |
| 1. Discovery | (a) For each university, a site-restricted search (`exa_site_search`, limited to the university's domain and its subdomains) with about 10 queries in the page's own voice, in English and the local language. (b) `manage.py sweep_organisations --country DE --family PRIVATE_FOUNDATION` and the same for `TR`. (c) The register rows already loaded for those countries. | Candidate pages and hosts; how many gems on the ground-truth list appear here at all. |
| 2. Classification | `manage.py classify_organisations` on new hosts (does this body fund master's students?). | Hosts kept vs. rejected, and any ground-truth gem lost here. |
| 3. Provenance | `manage.py provenance_check --domain <d>` for every surviving domain. | The gate's verdict per domain; gems lost because their country has no register loaded, counted apart from gems lost for any other reason. |
| 4. Reading | Gen-2 `read_page` per candidate programme page (its default stop: 30 s and $0.25 per page); the funder-page reader for foundation pages. | Per award: each field `shown`, `held` (with its reason) or `not_stated`. |
| 5. Serve simulation | Three serve rules applied offline to the same cards: **Strict** (every field shown), **Current** (any held field hides the award, as the card module says; not-stated fields allowed, which is our reading, since slice 3's serve rule is not written yet), **Lead tier** (the reviewer's Tier B: existence and eligibility quoted and shown; amount and deadline may be held or not stated). | Awards that would reach the student under each rule. |
| 6. Correctness | `manage.py card_check` on every card that survives the Lead-tier rule, marked by hand against the page. | Precision per rule; any wrong amount or wrong eligibility condition is reported on its own, because those are the two errors a student acts on. |

## 6. What we report back

1. **The funnel table.** One row per stage, one column per bucket (B1–B4, plus anchors). Each cell holds the count still alive and the share of the ground-truth list it represents.
2. **Where gems die.** For every ground-truth gem lost, the stage and the reason (not found, classified out, no register, held field and which one, read failure).
3. **Serve-rule comparison.** Recall and precision under Strict, Current and Lead tier. This is the evidence for or against the reviewer's Fix 1.
4. **Cost and time per stage**, in USD and minutes.
5. **Machine-only finds.** Hand-checked real gems the human missed.

## 7. Budget (proposed; the owner sets the final caps)

| Stage | Cap |
|---|---|
| 1. Discovery (site-restricted search + two foundation sweeps) | USD 20 |
| 2. Classification | USD 5 |
| 4. Reading (at most 150 pages at USD 0.25 each) | USD 40 |
| Total | USD 65 |

Human time is about 4 hours for the ground truth and 2–3 hours for the stage 6 hand check.

## 8. What would count as an answer

- If most lost gems die at **stage 1 or 2**, discovery is the problem and the gates are not.
- If they die at **stage 3**, loading bulk university registers (the reviewer's Fix 3) comes first.
- If they die at **stage 5 under Current but survive under Lead tier with high precision**, the lead-card tier (Fix 1) is worth building into slice 3.
- If Lead-tier precision falls below 90%, or any served amount or eligibility condition is wrong, the lead tier needs a stricter existence test before it ships.

## 9. Open points for the reviewer

1. Is 40 universities plus two foundation registers a fair size for one profile, or would you rather have fewer institutions read more deeply?
2. Do the three serve rules in stage 5 cover the variants you meant, or is there a fourth you want measured?
3. Should the anchor list be fixed in advance by you, so its recall cannot be tuned?
