# Slice 2 — owner decisions (grilling 2026-10-08 … 2026-10-12)

Authority: the owner's answers in the plan-3 session. The spec (verified-catalog, branch
`claude/verified-catalog-design`, owned by elmify-3d) is being updated to match; where the spec
at its HEAD disagrees with this file, this file is newer — flag the difference, do not silently pick.

## Targets
- ≤1% wrong values per SHOWN field, every field kind (deadlines included). Precision first.
- Model spend ≤ $0.25 per page; measured design ≈ $0.01–0.02/page.
- Background catalogue sweep may take hours per page → Batch API pricing (−50%). Pages a student
  waits on (typed programmes, on-demand single-page read) must finish < 30 s.
- First job: the catalogue sweep.

## Reading unit
- The AWARD, read with its page section (headings, neighbouring lines, links). A cheap line filter
  may first select which lines matter. Not line-by-line yes/no as the final decision.
- Code finders (slice 1, `apps/research/candidates/`) supply candidates; a model may propose quotes,
  kept only if byte-exact substrings of the page; code parses values.

## Readers (provisional; round 2 confirms; reader list is configuration)
- DeepSeek V4.1 Flash (`deepseek/deepseek-v4.1-flash`, OpenRouter; pin ONE stable host) and
  GPT-6-luna (`openai/gpt-6-luna`; no `temperature` param — it 404s) read every award.
- Both agree → accepted. Disagree (~8%) → Claude Opus 5.5 (`claude-opus-5-5`) decides.
- No Sonnet. Jev and Kimi K3 are not in the reader (Jev may return later as a measured filter).
- Measured on 211 owner-judged hard cards: pair→Opus precision 0.980 recall 0.925; Opus alone
  0.980/0.932; third reader or Sonnet changed 1–3 cards (noise). Remaining errors are shared by all
  models (definitions, missing context, values on other pages).
- Every reader call: untrusted page text labelled as data not instructions; schema-constrained
  output (`extra="forbid"`); max output tokens capped; per-tenant/per-run rate limit via
  `apps/ratelimit.rate_limited()` (CLAUDE.md LLM rules).

## Definitions v3 (question criteria)
- level = the TARGET level the award is FOR. A prerequisite ("completed a first degree", "2 years'
  work after the bachelor's", "PhD holders cannot apply") is its own field: required prior degree /
  exclusions — never level. Year of study ("1st–3rd year students", "I, II və III kurs",
  "3–4 курс бакалавриата") maps to bachelor's via a per-country code table.
- nationality = a named list of countries/regions/citizenships. Generic "international/foreign
  students" is NOT a condition → hunt the funder's site for the list; none found → "all countries
  except the host".
- Residence limits ("not resident in Germany > 15 months"), stateless persons, compatriots abroad
  (соотечественники) all count as eligibility conditions. Record whether the funder tests
  citizenship or residence.
- application dates = dates of applying to THIS award. Olympiad/exam/event dates are never award
  dates unless the page says applying = that event. "Applications are open" with no date → not a date.
- A required test or certificate (SAT/ACT, a language-certificate copy) is a requirement.

## Country groups (funder's own list always first; this is the fallback)
- CIS → AZ AM BY KZ KG TJ TM UZ, + MD while the page predates 2027-04-08 (Rossotrudnichestvo 2026
  list); Ukraine → hold queue; Georgia, Türkiye → not eligible.
- "developing countries" → off the OECD DAC ODA-recipient list = not eligible; on it → hold queue,
  unless the page itself says DAC/ODA.
- "Global South", "emerging economies", "newly industrialised" → hold queue.
- "low- and middle-income" → World Bank income groups (LMY), only when that phrase is the whole criterion.
- LDC → UN M49 LDC column (re-check after 2026-11-24 graduations).
- Sub-Saharan Africa → funder's list; else UN M49, with SD and DJ → hold queue.
- Existing `apps/funding/regions.py` REGIONS (EU, EEA, WESTERN_BALKANS, EASTERN_PARTNERSHIP,
  ASEAN, AFRICAN_UNION, COMMONWEALTH); Commonwealth/ASEAN fixed in PR #195.

## Site hunt (spec §5.5 step 4, commits 3c7a70d9 / 73e4a6b0 / 7b0d3a7c)
- Trigger: a field with no candidate, pointed-to elsewhere, or reader disagreement unresolved.
- Uses the existing `sitejob` funnel (DOCUMENTS → MAP/GUIDED_MAP → NAVIGATOR), URLs only; each page
  Part-B proven and read by the same engine with its own quote and source.
- May cross to another domain only if that domain passes the same provenance check.
- Cap: 6 extra pages per award per cycle.
- Strict attach: a hunted value attaches only if its page/section names the same award (code match).
- Pages disagree → the page stating the higher cycle (parsed by code from a quote) wins;
  Last-Modified/crawl date only breaks ties; a page stating a cycle beats one stating none.
  Undated-vs-undated and same-cycle conflicts → hold queue.
- Only last cycle's value found → shown labelled ("Last cycle: … — new date not announced yet").
- Measured (15 pages): same-domain hunt found 6/29 missing fields; 19/23 misses live on another
  official domain.

## Hold queue (platform operator)
- Hunt-not-found, unresolved conflicts, hold-listed country groups → hidden from ALL students
  (B2C included) until the operator acts. The operator fixes the WORDING (criteria, finder, example,
  data row), never a one-off value, then re-runs. Ceiling: 15% of real awards. `funding_review`
  returns in this role. Agencies never browse/export/bulk-read the catalogue.

## Engine shape
- Generic from the start: one question-set interface (candidates in; typed decisions with
  byte-exact quotes out; link-candidate answers; the hunt). Question sets: funding (first),
  application routes (spec §3.4), document file-naming rules (spec §3.5).
- Slice 2 builds: engine + funding set + hunt + typed card + single-page entry + track-shaped output.
  NOT slice 2: storage, serve rule wiring into `pipeline._fund_page`, deleting `funding_judge.py`'s
  vote (slice 3); cycle verifier (slice 4).
- D8 injection screen: spec says nothing in this reader ships before it.

## After slice 2: owner round 2
- ~250 card VALUES on ~35 fresh pages, random from real sources (EACEA, funder seeds, destination
  list), ~3 per language: en de fr es it nl ko ja zh az tr ru kk. owner answers blind (no model pre-answers, 2026-10-12);
  checks. Count how often vague country phrases appear.
