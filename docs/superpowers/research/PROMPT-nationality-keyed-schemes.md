# Deep research prompt — nationality-keyed master's funding schemes

**Status:** ready to run. Written 2026-08-28. Run it twice, independently, so the two results can be
adjudicated against each other the way the corridor and worldwide-sources runs were.

**Why this one first:** the discovery engine is destination-indexed, but a student's real leverage is
often nationality-indexed. One scheme naming Azerbaijan as eligible is worth more to our primary
population than a thousand generic programmes they compete for on open terms. Nationality-scoped
eligibility is invisible to any programme census, and no index of these schemes exists.

---

## Prompt

You are researching **master's-level (graduate, not doctoral, not undergraduate) funding schemes
whose eligibility is keyed to the applicant's nationality or region of origin**, rather than to the
destination alone.

The population of interest, in priority order: **Azerbaijan, Turkiye, Georgia, Armenia**, then the wider
**South Caucasus, Central Asia (Kazakhstan, Uzbekistan, Kyrgyzstan, Tajikistan, Turkmenistan), and
Turkic states**. A scheme qualifies if a citizen of one of these countries can apply to it, or be
nominated for it, to fund a master's degree.

### What counts, and what does not

**In scope:**
- Regional and bloc-scoped programmes with nationality-based eligibility — for example
  Visegrad Fund (including its Eastern Partnership strands), CEEPUS, the Czech Government
  Scholarships for developing countries, Stipendium Hungaricum's per-country quotas.
- Multilateral and inter-governmental organisation schemes — Organization of Turkic States / TURKSOY,
  Black Sea Economic Cooperation, GUAM, Islamic Development Bank, OIC bodies, Commonwealth,
  Organisation internationale de la Francophonie, Colombo Plan, UN agencies, regional development
  banks.
- Bilateral country-pair scholarship agreements where a *published* scheme page exists that a student
  could actually apply through.
- Diaspora, community and religious foundations that fund master's study for these nationalities.
- Any scheme that funds study **in** these countries for foreign nationals, if it is nationality-keyed.

**Out of scope:** doctoral and postdoctoral funding; undergraduate-only schemes; research grants to
academics; institution-local waivers and assistantships.

**Also out of scope, but only because another run covers them:** general destination-inbound schemes
with **no** nationality restriction — DAAD, GKS, CSC, Türkiye Bursları, Chevening, MEXT, Eiffel,
Stipendium Hungaricum's open track and their equivalents. These belong to
`PROMPT-government-inbound-sweep.md`, which sweeps them across ~50 countries. Leaving them out here
is a division of labour, **not** a claim that they are already known — most are not.

**The boundary is the nationality restriction, and it is the only test.** If a scheme's eligibility
names our students' countries, or names a bloc they belong to, it is in scope here however
well-known it is. Stipendium Hungaricum's **per-country quota table** is in scope even though its
open track is not; GKS's **per-country embassy quotas** likewise. Where a famous scheme has both a
general track and a nationality-keyed one, cover the nationality-keyed track and say the general one
is out of scope. **When in doubt, include it** — a duplicate row costs a line, a missed
nationality-keyed scheme costs the student the option.

### Deliverable

**Part A — a scheme table.** One row per scheme. Columns:

| Column | Notes |
|---|---|
| Scheme name | Official name, and in its own language where that differs |
| Funder | The body that pays, and its type (government / bloc / IGO / foundation / other) |
| Eligible nationalities | **Verbatim from the source.** If a quota table exists, reproduce the rows for our priority countries |
| Destination(s) | Where the money can be spent |
| Degree level | Confirm it covers master's specifically |
| **Application route** | **`DIRECT` (the student applies) / `NOMINATED` (a university, ministry, club or partner must nominate) / `HYBRID`.** State which, and quote the sentence that establishes it |
| What it covers | Tuition / stipend / travel / insurance / accommodation, per the source |
| Annual cycle | Opening and closing dates, if published |
| Official URL | The scheme's own page, not an aggregator |
| Terms for automated retrieval | Whether the site publishes reuse or access terms, and what they say |

**The `Application route` column is the most important in the table.** A nominated scheme can never
be a safety option for a student, no matter how generous it is, because the student cannot initiate
it. Do not infer this from tone — quote the sentence.

**Part B — which of these are indexed anywhere.** For each scheme, state whether it appears in any
aggregate directory, database or machine-readable feed, or only on its own site. If any real index
of nationality-keyed schemes exists, that is the single most valuable finding in this run — name it,
give its coverage and its terms.

**Part C — the ones you looked for and could not confirm.** Blocs and bodies you checked that appear
to run no master's scheme, or whose scheme could not be confirmed from a primary source. A confirmed
absence is a result; list it as such.

**Out of scope for this run: institutions funding students *into* the region.** Universities in
Azerbaijan, Türkiye and the Caucasus that fund incoming international master's students are covered
by a separate prompt (`PROMPT-leading-institutions-outside-high-income.md`, Part A). They are a
different question — an institution funding foreigners is not a scheme keyed to *our* students'
nationality — and covering them here would duplicate that run. Do not spend budget on them.

### Sourcing rules

1. **Primary sources only for any load-bearing claim.** The funder's own page, the government
   gazette, the bloc's own site. Study-abroad blogs and scholarship-aggregator sites may be used to
   *find* a scheme but never to establish a fact about it.
2. **Quote the operative sentence** for eligibility, application route and degree level. A
   paraphrase is not checkable.
3. **Date every fact.** These schemes change annually; a 2019 quota table is not a current one, and
   should be labelled with its year rather than presented as live.
4. **Where something is not published, say so explicitly** — "no applicant count is published",
   "no reuse terms are stated". Do not fill a gap with a weaker source, and do not infer a number
   from a related one. A stated unknown is more useful than a plausible guess, because the guess
   will be encoded and the unknown will be verified.
5. **Do not extrapolate a scheme's contents from a directory listing.** Open the scheme's own page
   before asserting what it funds.
6. Where sources conflict, present both with their dates and sources rather than picking one.

### What would change our plans

Flag explicitly if you find: an actual index of nationality-keyed schemes; a bloc scheme with a
machine-readable feed; a scheme that is both `DIRECT` and full-cost for our priority nationalities
(that is a floor-maker and matters more than breadth); or a scheme that has closed or changed
eligibility since 2024.