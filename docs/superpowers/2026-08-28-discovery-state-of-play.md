# Discovery and portfolio — state of play, 2026-08-28

Written at the user's request after a long working session, to re-ground the problem frame,
record what was decided and why, and audit where the reasoning in that session was wrong. It
describes state; it decides nothing new.

---

## 1. The problem, framed

A B2B concierge platform. Partner agencies pay for it. Students move along corridors — origin
Azerbaijan and nearby, destinations Germany, France, Japan, South Korea, China, Turkey, Hungary.

**What is sold is not a list of programmes.** It is citable, reproducible evidence: for every claim
(tuition, deadline, stipend, eligibility) an immutable S3-versioned snapshot of the origin page, the
retrieval timestamp, the final URL and redirect chain, and a per-claim freshness window. Agencies
show these to students and to visa authorities.

**The optimization is stated and researched.** `risk-aware-portfolio-design.md` §2: *maximize the
expected value of the best offer the student ends up holding, subject to a floor constraint and an
application-fee budget the portfolio aims to spend in full.* This is Chade & Smith's simultaneous
search (Econometrica 2006), in the correlated regime of Ali & Shorrer (AER 2025). Two facts from
that literature govern most downstream design:

- Under correlation the optimal portfolio contains **both a reach and a safety** — the floor is not
  a paternalistic guardrail, it is what the optimum looks like.
- **The student's fee budget is a parameter of the recursion** (`b − gᵢ`), so questions of the form
  "is this catalog good enough" have no answer independent of the student asking.

**Correlation groups by destination** — one visa authority spans a destination; one home-origin
instrument decides once for its whole approved list. This is why destination is load-bearing
everywhere, and why filtering discovery by destination is harmful rather than merely narrow.

---

## 2. Subsystem map

| Subsystem | Status |
|---|---|
| Egress, snapshot, extraction, catalog writer | **Built**, tested |
| Discovery pipeline (`run_discovery`, `LeadSource`, budgets, leases, consultant tasks) | **Built**, tested, discovers nothing — all inputs closed |
| Risk-aware portfolio (objective, bands, gates, floor, staging, display) | **Specified**, not built. Explicitly gated behind a manual-consultant baseline over one admissions cycle |
| Funding-led discovery (this session's spec) | **Specified**; three defect fixes built |
| Instrument mode (funding opportunities, per-destination sweep) | Specified, separate increment, not built |

The engine is correct and finds nothing. The 2026-08-28 shadow run produced zero catalog rows: DAAD
on unverified terms, EACEA refusing on `robots.txt`, live search with no key and a provider whose
ToS forbids storing results. **The problem was never the pipeline; it is the supply of leads.**

---

## 3. What was decided this session

**Discovery is funding-led, not catalogue-led.** Grant databases (CORDIS, data.europa.eu, ANR) yield
*funded organisations*; entity expansion resolves them to origin pages. Rationale: elite funded
programmes never appear in commercial aggregators (they do not buy listings) and often sit on their
own subdomain, invisible to a university's main sitemap. This restores the repo's own §2.3, which
already said gems resolve by entity expansion from a funded organisation.

**Discovery runs worldwide; country is an output, not a filter.** `--country` survives as a
results filter that never reaches a `LeadSource`. Three grounds: R§7.2 constrains discovery by
language not geography; R§7.1 already reports coverage *per country*, which a filter cannot also
decide; and destination is the dominant correlation axis, so a country-filtered run cannot construct
the reach-and-safety portfolio the theory requires. The safety and the reach are usually in
different countries — Türkiye Bursları (75% bar, no language certificate, full package, but no
post-study work route) against Germany or the UK.

**The per-destination *instrument* sweep stays per-destination.** An instrument is a country-level
object. Two sweeps, two scopes.

**Coverage is an optimizer outcome rate, not a catalog count and not a human gate.** See §5 below —
this was decided twice wrongly before landing.

**Explicitly not built:** residential proxies, CAPTCHA solving, stealth fingerprinting, robots
bypass, unrestricted spiders, search-engine scraping, DNS brute-force enumeration, aggregators as a
spine. Each lost on engineering merit before any rule was invoked — rotating exit IPs corrupt
geo-varying tuition data and make snapshots unreproducible; evasion converts clear refusals into
plausible 200s full of garbage (this project already misdiagnosed EACEA that way); a CAPTCHA marks
an aggregator surface whose data may never support a claim.

**Three defects fixed and shipped** (`b5d120d`, 213 tests green, ruff/mypy/bandit clean): raw-body
hashing that re-ran extraction on unchanged pages; a 20 KB shell-detection floor that missed
Opintopolku's 7,127-byte React shell; and no address-family fallback in egress.

---

## 4. Empirical findings, all from execution

- **Institution sitemaps are a weak spine.** 2 of 5 universities usable. TUM publishes ~180
  programme detail pages; RWTH publishes only an index; Sorbonne, Bologna, U-Tokyo nothing usable.
- **A widened multilingual path regex made triage worse, not better** — 0 matches on Sorbonne where
  the existing term list matched 128; 451 mostly-irrelevant matches on TUM. Path shape is a CMS
  artifact, not a semantic signal.
- **Finland is a tier-1 source, and the sitemap was a red herring.** Its 26,686-URL sitemap is React
  shells (7,127 bytes, 11 characters of text). Its backend is a public JSON API: 1,285 master's
  programmes, structured, filterable. **The generalisable rule is "is there a JSON API behind the
  SPA", not "does it publish a sitemap".**
- **The recurring obstacle is a closed enumeration surface over open records** — not bot defence.
  EACEA disallows `/search/`; Hochschulkompass disallows its eight search paths but not detail
  pages; ANR disallows exactly its search-results path. GEPRIS alone is `Disallow: /`.
- **Grant databases are largely open.** CORDIS disallows only export formats; data.europa.eu is a
  standard Drupal robots.

---

## 5. Audit of this session's reasoning — where it was wrong

Recorded because the pattern matters more than the individual errors.

| # | Error | Caught by | Root cause |
|---|---|---|---|
| 1 | Designed an institution-level "census frame" (ETER/ROR → sitemaps) as the primary spine over two rounds, including five live probes | **User**, pointing at the repo's own §2.3 | Did not read the existing plan before proposing an architecture it had already rejected with evidence |
| 2 | Spec claimed "no migration"; implementation needed one | Self, during implementation | Asserted a consequence without tracing it |
| 3 | Claimed Venice's `include_venice_system_prompt` flag worked | Self, on the next run | Attributed an effect to the flag when supplying a system message was the cause |
| 4 | Specced a coverage gate with invented numeric thresholds, flipped by a human | **User** | Designed a parallel mechanism for something the optimizer already computes |
| 5 | Described coverage first as post-launch observation, then as a gate, then as a rate | **User**, twice | Same as 4 |

**The pattern: repeatedly designing new mechanisms for problems the existing specs already solved.**
Errors 1, 4 and 5 are the same failure. Three of five were caught by the user, not by self-review.
The corrective is procedural — grep the existing specs and plans for the decision *before* proposing
an architecture, and treat a prior probe's recorded finding as stronger evidence than fresh opinion.

**What is well-founded:** the probe findings (executed, reproducible), the portfolio theory (two
independent research runs plus a synthesis), the three shipped fixes (tested), and the evidence-chain
reasoning (deduced from a stated product requirement, not researched — and labelled as such).

---

## 6. Open items, ranked by what they block

1. **Azerbaijan outbound instrument research** — blocks the floor rule for the primary student
   population. Prompt written and handed to the user to run in two tools.
2. **Four access-terms checks** — Opintopolku (blocks increment 1), CORDIS and data.europa.eu, ANR
   (block increment 2), the CT log endpoint (blocks increment 3). The project's rule is that an
   adapter for an unverified host is not written at all.
3. **Suppliers outside the EU** — Japan, Korea and China have no tier-0 supplier and no usable
   registry. Three of seven declared corridors. Worldwide scope made this blocking.
4. **Three permission requests**, outside engineering: DAAD, HRK/Hochschulkompass, DFG/GEPRIS.
5. **Two spec defects found and not yet amended** — the Azerbaijan instrument row conflates two
   unrelated schemes, and §7.4's exclusion list wrongly bars "Azerbaijan" from being a floor on the
   strength of the inbound grant. Deliberately held until the research lands.
6. **The discipline taxonomy** for coverage rates — the student's field is LLM-deduced free text and
   each source has its own subject vocabulary; both must land on one bucket set.
7. **Index-page harvest** — RWTH-class pages (sitemap yields an index, not detail pages) currently
   go straight to extraction. Identified, never specced.

---

## 7. Facts supplied by the user, load-bearing and unverified

These came from a practitioner, not a source, and several design consequences already rest on them.
The Azerbaijan research prompt lists them explicitly as claims to verify or refute.

- Azerbaijani state scholarship results are released in **June**.
- The approved list for the cycle is published in **March–April**.
- Students apply to universities either before the list is published, using the previous year's
  list, or after waiting for the new one.
- Students never hold the scholarship before applying: they apply first and win afterwards.
- Application fees are paid by the student and are **never refunded**.

The third and fourth together produce a design consequence with no home in any current spec: an
**approved list has its own clock**, distinct from the award decision. Money is committed before both
the list is certain and the award is known. Provisionally called *list-version risk*: a candidate
verified only against the previous cycle's list is disclosed as such and cannot be the floor.

---

## 8. Recommendation

Nothing here needs a new decision. The sequence that follows from the above:

1. Land the Azerbaijan research, then make the four spec amendments with real values.
2. Clear the Opintopolku terms question, then ship increment 1.
3. Research the worldwide supplier set — grant databases and national registries with access
   terms — as a separate run from the Azerbaijan one. Different question, different sources.
4. Leave the portfolio subsystem specified and unbuilt until the catalog holds rows. It is gated on
   a manual-consultant baseline regardless.

Deep research would help on item 3 and on nothing else currently blocking. Items 1 and 2 are
already scoped; items 5–7 are design work, not research.
