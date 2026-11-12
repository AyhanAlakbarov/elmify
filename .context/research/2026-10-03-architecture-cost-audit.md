# Architecture, cost and breadth audit — verified catalogue + one decision engine

Date 2026-10-03. Read-only audit. Specs: `2026-09-27-verified-catalog-one-reader-design.md` (working
tree, uncommitted edits included), `2026-10-03-one-decision-engine-design.md` (commit 74903833),
`2026-09-22-funding-search-engine-master-design.md` (master). Code: `origin/master` 02926ac2.
"Measured" means run here today; "spec" means a figure quoted from a spec, not re-measured.

## Verdict

**The design holds only after rework.** The reader (Part C) and the measurement (Part E) fit the code.
Part B (proof), the rate limit, and the freshness and past-deadline proposals were written as if no
code existed. Each one duplicates something master already built, and in two cases contradicts it:

- the provenance gate (PR #158);
- the cycle wallet;
- `cycle_validity` and `FundingCycleVerification`.

Three structural exclusions shut out funders the owner wants:

- bodies that share a registrable domain;
- Facebook-only schemes;
- calls hosted on third-party portals.

**On cost, the dominant term is search, about 85% of a tap, not reading.** The cheapest equal-quality
move is to stop running per-tap search on warm cells. At catalogue-build scale, cycle verification and
vouching dominate, not reading.

## Findings, by severity

### H1. Part B re-designs the provenance gate that is already merged
- **Evidence.** `apps/research/provenance.py:405` `decide()` already turns evidence into a verdict, with these reasons:
  - `REGISTER`, `CURATED_LIST`, `FUNDER_LIST`, `VOUCHED_BY_LINK`, `GOVERNMENT_ZONE` (`models.py:886-890`);
  - lapsed-domain detection, `_taken_over` (`provenance.py:501`, RDAP registration after first binding), which is stronger than the spec's re-check of whether the name still appears;
  - mill lists and content vetoes;
  - `WAITING_REASONS` for "not checked yet" (`provenance.py:39`).

  `provenance_job.py` already checks "only bodies in play", which is the spec's "only when a student needs it". `provenance_sweep.py` already pushes verdict changes into published packs.
- **Mapping.** Spec P1 is `REGISTER`, P2 is `GOVERNMENT_ZONE`, and "stale proof" is `_taken_over` plus a re-check. Only P3 (register number, or address and phone, on the site) is new. The spec names none of this; `provenance`, `ProvenanceVerdict` and `decide` appear nowhere in it.
- **Breaks.** Plan 4, built as written, gives the system two writers of "is this website the body's". Step 7's show rule ("the page's website carries a recorded proof") would read a different table from `pool.py`/`provenance_of_award`. A body can then be RECOGNISED in one and unproven in the other.
- **Refine.** Restate Part B as an extension of `decide()`. Add one reason, `REGISTER_DETAILS` (P3). Add P2's site-identity condition (title or `og:site_name`) as a precondition of `GOVERNMENT_ZONE`, if that zone does not already require it. Make step 7 read `provenance_of_award(award)` and require `RECOGNISED`. Drop the separate stale-proof triggers in favour of `_taken_over` and the sweep.

### H2. One registrable domain = one organisation, with no human to merge
- **Evidence.**
  - `OrganisationDomain.registrable_domain` is `unique=True`, documented as "a collision is a merge question a human answers" (`models.py:153+`).
  - `Organisation.primary_domain` is unique (`models.py:45`).
  - The spec adds "if one website is proven for two different organisations, neither is saved".
  - The owner removed the human.
- **Measured** with `hosts.registrable_domain`:
  - `eacea.ec.europa.eu` and `ec.europa.eu` both give `europa.eu`;
  - `www.gov.uk/world/organisations/british-embassy-baku` and `…/department-for-education` both give `www.gov.uk`;
  - `baku.mfa.gov.tr` gives `mfa.gov.tr`.
- **Breaks.** The register row for EACEA and the one for the European Commission collide on `europa.eu`, so neither is saved. Every UK department and embassy collides on `www.gov.uk`. So do a university and a foundation hosted under its domain (`uni.edu/foundation`).
- **Refine.** Bind proof to `(host, path prefix)` for a short, data-driven list of shared government hosts (`www.gov.uk`, `europa.eu`, `canada.ca`, `gov.pl`…). Elsewhere, a second body on an already-proven domain becomes a child of the first (`Organisation.parent` exists, `models.py:65`), not a conflict. Keep "neither is saved" only for two unrelated register rows claiming the same host, path and identity.

### H3. Facebook-only schemes cannot pass, against the owner's 2026-09-27 decision
- **Evidence.**
  - `facebook.com` is in `domains._ROUTING` (`domains.py:145`), which feeds `AGGREGATOR_DOMAINS` (`:261`).
  - Spec P1: "it is not on `AGGREGATOR_DOMAINS`".
  - Step 7: a card is shown only when the website "carries a recorded proof".
  - Owner decision 2026-09-27 (memory `facebook-only-schemes-served`): a ministry scheme announced only on Facebook is shown, citing the post.
- **Breaks.** Example input: the Azerbaijani ministry announces a bilateral scheme only at `facebook.com/edu.gov.az`. No proof is possible, so the scheme is never shown.
- **Extend.** Add a `SOCIAL_OFFICIAL` proof: the body's own RECOGNISED website links to the social page from a structural position (the `vouch.py` mechanism, one hop). The card cites the post; the post is re-fetched before every show and withdrawn when it is gone. Only where no official page exists, as the owner ruled.

### H4. The proposed rate limit duplicates the built cycle wallet
- **Evidence.** `apps/research/wallet.py` already implements:
  - $50 per `(student, intended_intake)`;
  - a per-tap share of what remains;
  - a tenant runaway ceiling;
  - `preflight` before a call and `charge` after;
  - 2 taps a day, and the pack-command limiter at 20/min (master §10.5, §13).

  The spec's "20 new organisations checked per student per hour" plus a tenant daily cap is a second, unrelated budget.
- **Breaks.** A pioneer student in a cold cell whose pack meets 60 unchecked bodies is throttled to 20 an hour by the new limit while the wallet still has money. The two ceilings disagree, and the stricter, unmeasured one wins.
- **Refine.** Charge proof, fetch and read to the wallet through `preflight` and `charge`. Keep `rate_limited()` only as abuse control on the request endpoint, which already exists. Owner question 5 is mostly answered by the wallet.

### H5. Owner questions 2 and 3 are already designed, and partly built, elsewhere
- **Past deadlines.** `apps/funding/validity.py:304` `cycle_validity` already produces `UPCOMING` ("expected to open March 2027 (opened 3 March 2026 and 4 March 2025)"), but only for a scheme verified to recur: two dated past cycles, or the page stating annual recurrence (master §9.1). A first-year scheme stays `UNVERIFIED`. The spec's "last cycle: February 2026" is weaker; it projects from one cycle.
- **Freshness.** Master §9.3 sets funder pages to monthly, weekly and daily checks: a schedule. The provenance-gate spec §10 sets programme pages to once per cycle, on entering a pack, and about 30 and 7 days before the deadline. The verified-catalog spec's §0.3 "no scheduled retries" and its 7-day window contradict §9.3, and nothing reconciles the three.
- **Refine.** Adopt `cycle_validity` and `FundingCycleVerification` as the card's deadline logic. Use one cadence for funder and programme pages: the provenance-gate §10 rule, applied only to awards in a current pack. Record in the verified-catalog spec that it supersedes §9.3's monthly default.

### M1. The pioneer pays, and waits
- **Evidence.** Master §10.5: "the first student in a cell pays for everyone after them". Its mitigation is a platform-funded sweep of the closed universe before the first student arrives. The verified-catalog §0.3 says paid work runs only when a student needs it, which forbids that sweep.
- **Breaks.** The first Azerbaijani student targeting Hungary spends their wallet rediscovering Stipendium Hungaricum.
- **Refine.** Allow one platform-paid seed pass over the closed lists and home-side lists, a few hundred bodies. At the new per-body price (cost table below) that is under about $20.

### M2. Single-flight already exists in part
- **Evidence.** `services.py:54` `acquire_domain_lease` (a `select_for_update` lease that raises `DomainBusy`); `provenance_job` runs one body at a time; the verdict row is the shared result. The spec's §4 proposes a new job table with `SKIP LOCKED`.
- **Refine.** Reuse the lease and verdict row. The one gap is that `DomainBusy` hands the second student nothing. `provenance_sweep`'s "resolved checks re-run students" already covers that, and the spec should cite it.

### M3. Registers-first covers 5 destination countries today
- **Evidence.** `docs/research/closed-lists.csv` has 21 lists:
  - country registers for AZ, TR, GB (England and Scotland only), KR and DE;
  - the EACEA, intergovernmental and national-agency lists.

  The destination list covers about 70 countries.
- **Breaks.** For France, Italy, Japan, the US and most others, organisations still come from search and the resolver, and P1 never applies.
- **Extend.**
  1. Use ROR (CC0, global, websites and identifiers) as a `CURATED_LIST` recogniser for institutions wherever no national register is loaded.
  2. Load the EACEA project API: 576 organisations with website and EU-PIC, free, designed but not built (`2026-09-14-emjm-partner-source-design.md`). It is a register for every EMJM partner.
  3. Order country adapters by student demand per destination.

### M4. Calls hosted off the holder's origin are hidden
- **Evidence.** `egress.py:117` `require_same_origin`. Step 7 requires the final URL on the proven website's origin.
- **Breaks.** A foundation whose call text lives on `foundation.smapply.io`, Submittable, or a Google Form linked from its proven site produces no card.
- **Extend.** This is the same mechanism as H3: a page the proven site links to structurally is admitted as the holder's own words, one hop only.

### M5. Calls published as images
- **Evidence.** Firecrawl returns html and markdown with no OCR. `transcript.py` has on-demand OCR for student documents only.
- **Breaks.** Ministries in Azerbaijan and Türkiye often post a call as a JPEG poster, and the reader sees nothing. This is silent: an empty read keeps prior rows.
- **Extend.** Count image-only funding pages (`no_candidate` with an `<img>` in a funding section) before building anything. Reuse the transcript OCR seam if the count is material.

### M6. `_FUNDING_TERMS` has 9 callers
- **Evidence.** `git grep _FUNDING_TERMS` gives 9 hits outside its definition: `pipeline.py` (×2), `cycle_verification.py:780`, `first_read_gate.py`, `funding_yield.py` and others.
- **Refine.** The per-language table in spec step 1 must replace the regex in every one of them. Otherwise cycle verification keeps dropping Turkish sections after the reader stops.

### L1. Second reader and Jev outage
A Jev outage means "not yet checked", with no failover (engine §3.9). This is acceptable. Note only that every new card waits on one vendor.

### L2. Step 6's INSTITUTION scope
The step uses the proven website's origin. A subdomain such as `scholarships.uni.edu` resolves to the same registrable domain. It holds.

## Cost model

Unit prices. "Spec" marks a figure quoted from a spec, not re-measured here:

| Item | Price |
|---|---|
| Firecrawl credit | $0.00083 (Standard plan, $83/100k; master §13) |
| scrape.do page | 25 credits ≈ $0.0029 (Hobby, $29/250k) |
| Jev read | ≈ 0.25¢ a page (spec) |
| Second reader | ≈ 0.05¢ on 10–20% of questions (engine §9, least certain) |
| Stage-1 search per tap | ≈ $0.59 (≈ 38 calls: Exa ≈ $0.097 per 100-result call, Brave $0.005 × ~6 a query; master §10.5) |
| Vouching | ≤ 21 fetches per body, so ≤ $0.017 (`vouch.py:1-9`) |
| Cycle verification | $0.15–0.40 per scholarship per cycle with the ladder, ≈ $0.05 after the cheap read (master §9.3) |

**One student, first tap, cold cell** (30 pages, about 10 new bodies, about 10 awards to verify):

| Term | $ | Share |
|---|---|---|
| Search, stage 1 | 0.59 | **≈ 45%** |
| Verification, 10 × $0.05 | 0.50 | ≈ 38% |
| Proof, 10 bodies (vouching worst case) | 0.17 | ≈ 13% |
| Read, 30 × 0.30¢ | 0.09 | 7% |
| Fetch, 30 pages plus /map | 0.03 | 2% |
| **Total** | **≈ 1.3–1.4** | |

**Warm cell:** about $0.59, almost all search, because provider calls fire before dedupe (master §10.5).

**EU catalogue build:** 2,000 bodies × 2.5 pages, per master §13:

| Term | $ per cycle |
|---|---|
| Verification, 2,000 × $0.05 | **≈ 100** |
| Proof, vouching worst case | ≈ 34; ≈ 0 for bodies proven by register or zone |
| Read, 5,000 × 0.30¢ | ≈ 15 |
| Fetch plus /map | ≈ 6 |
| **Total** | **≈ $150 per cycle**, against the spec's "well under $1,000" and today's ≈ $13,000 |

**The dominant terms: search per tap, and verification per cycle. Reading is no longer one of them.**

Cheaper alternatives at the same quality, largest first:

1. **No per-tap search on warm cells.** Serve the catalogue, and search on the funder's calendar per cell, not per student. Master §10.5 already says "a mature cell plausibly should not search on a tap at all". This saves ≈ $0.59 per warm tap, the single biggest lever.
2. **Verification ladder:** stop at step 0 or 1 (own pages and `changeTracking` at 1 credit) when the page states its own call. Run the Exa step only for `UNVERIFIED` awards that a student actually holds.
3. **Proof order:** register, then zone, then P3 (≤ 2 credits), then vouching (≤ 21 fetches). Vouching only for bodies nothing cheaper proves.
4. **Registers with websites** (ROR, EACEA API, national registers) remove resolver search for those bodies entirely.
5. **Firecrawl /map** (1 credit a site) plus F3 ranking, instead of crawling. Already in the design.
6. **Batch APIs** no longer matter for reading, since Jev output is free and it has no cache. They matter only if the second reader's share grows.
7. **Shared catalogue across tenants** is already the design's cache. Note that it makes M1's seed pass cheap and reusable.

## Breadth: what gets in, and what is shut out

**Channels that exist:**
- the 21 closed lists;
- the EACEA catalogue seed;
- stage-1 per-tap search (Exa and Brave);
- bounded cell sweeps;
- aggregator hop (names only);
- `EntityExpansionSource` (walking an organisation's own host);
- Firecrawl /map site jobs;
- Wikidata enumerators;
- national scholarship databases (leads only, per spec §3).

**Shut out by structure:**

| Excluded | Cause | Fix |
|---|---|---|
| Bodies sharing a registrable domain (EU agencies, GOV.UK, university-hosted foundations) | H2 | host and path proof, parent link |
| Facebook-only ministry schemes | H3 | `SOCIAL_OFFICIAL` via link from the proven site |
| Calls on third-party portals or forms | M4 | one-hop admit |
| Image-only calls | M5 | measure, then OCR |
| Countries with no loaded register and no search hit | M3 | ROR and EACEA as recognisers |
| Telegram-only announcements (common in AZ and RU) | not modelled anywhere | same rule as H3, if the owner wants it |
| Diaspora and affinity funders with no register | only the hand-seeded home-side list (spec §3) | the seed list's coverage is the ceiling; measure it |

## Next step for the spec

Restate Part B on top of `provenance.decide`. Fold the rate limit into the wallet and freshness into
`cycle_validity`. Add host-and-path proof and one-hop social and portal admission. Then the
architecture holds end to end.
