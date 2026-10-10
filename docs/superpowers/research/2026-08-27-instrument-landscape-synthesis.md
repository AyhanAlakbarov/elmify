# National and state scholarship instruments — synthesis and design consequences

**Date:** 2026-08-27. **Inputs:** two independent deep-research runs over the same 12-scheme
sample, filed as `2026-08-27-instrument-landscape-review-1.md` (better sourced; carries the
crawler seed index) and `-review-2.md` (weaker sourcing, three findings run 1 missed).

**Purpose of the sample:** validate the funding-route attribute model in
`docs/superpowers/specs/2026-08-27-risk-aware-portfolio-design.md` §4 against real instruments,
and find the official index pages an instrument crawler should seed from. It was never intended as
a census.

**Verdict: the attribute model survives, with four changes.** Every scheme is representable, but
`initiation` has to become multi-valued, `origin` needs a fourth value, nationality eligibility is
rule-shaped rather than a list, and dates must be allowed to be decentralised.

---

## 1. The correction that matters most

The premise that prompted this sweep — that a student from India can access the state scholarships
of Azerbaijan, Georgia and similar countries — is **only partly true, and the reason is the
`initiation` field.**

- **Azerbaijan's Heydar Aliyev International Education Grant** requires **nomination by the
  applicant's own national government**, on top of an application through SIACAS. Eligibility is
  restricted to citizens of OIC members, the Non-Aligned Movement, Small Island Developing States,
  and countries with shared cultural or historical ties to Azerbaijan. India is in the Non-Aligned
  Movement, so eligible in principle — but the student cannot simply apply. 100 awards per year,
  all levels.
- **Georgia has no open national inbound scholarship at all.** The International Education Center
  funds *outbound* Georgian citizens. What exists inbound is a set of **bilateral reciprocal
  allocations** — 10 places a year with Armenia, a Czech arrangement — negotiated per country pair.

So the accessible-instrument set for any given student is far narrower than "state schemes of
friendly countries", and what narrows it is not the academic bar but **who is allowed to initiate
the application**. Five of the twelve schemes cannot be applied to directly by a student at all.
That makes `initiation` the highest-value field in the model, which both runs concluded
independently.

---

## 2. Changes to the funding-route model (spec §4)

**2.1 `initiation` becomes multi-valued, via tracks.** GKS and MEXT each run an **embassy track**
and a **university track** with different quotas, different deadlines and different selection
bodies. A scheme is therefore not one route but a set of **tracks**, each carrying its own
initiation, timeline, quota and sometimes its own eligible-country list. Modelling a scheme as a
single row with one `initiation` value cannot represent GKS.

Observed initiation values across the sample:

| Value | Schemes |
|---|---|
| Student applies directly | Türkiye Bursları, Chevening, CSC Type A, GKS embassy track, EMJM |
| Institution or consortium nominates | Eiffel (the university applies for you), DAAD EPOS (apply to the university, DAAD selects), MEXT university track, Stipendium Hungaricum (Sending Partner) |
| **Home government nominates** | Azerbaijan, Russia, Commonwealth (national nominating agency) |
| Joint selection (two bodies must both approve) | GKS, MEXT, Stipendium Hungaricum, CSC Type A |

**2.2 `origin` needs a fourth value: `BILATERAL`.** Georgia↔Armenia and Georgia↔Czechia are keyed
by a *country pair*, not by a single funder country. The existing home / destination / third /
supranational values cannot express a reciprocal allocation.

**2.3 Nationality eligibility is a rule, not a list.** Observed forms:

- membership of a bloc — OIC, Non-Aligned Movement, SIDS, Commonwealth, "MEXT-designated
  countries", Hungary's 90+ partner countries;
- an explicit published country list — Chevening's 160+, DAAD EPOS's developing-country list;
- a bilateral agreement — Georgia;
- **a per-nationality quota** — GKS publishes them (the 2026 graduate quota is 2,000 total, split
  800 embassy / 1,200 university, with per-country allocations such as Georgia's 4 + 2);
- **a per-nationality cap linked to the applicant pool** — Erasmus Mundus applies a **10% rule**:
  no more than 10% of scholarship holders in an intake may share one nationality (some regions
  exempted).

The 10% rule is the sharpest case: a student's chance depends on how many of their compatriots
apply. No other scheme in the sample does that, and it cannot be modelled as a static eligibility
flag.

**2.4 Portability, confirmed as a three-value enum plus reciprocal.** Nine of twelve fund study
**only in the funder's country**. Chevening and Commonwealth are portable *within* the UK — the
student picks the university. Erasmus Mundus is multi-country by construction and *mandates*
mobility across at least two countries. Georgia's bilateral schemes are reciprocal.

---

## 3. Dates: "decentralised" is a first-class state

Only Eiffel, GKS, Türkiye, Stipendium Hungaricum, Chevening and Commonwealth publish a clean
scheme-wide calendar. **DAAD, CSC, MEXT, Russia and Erasmus Mundus have no single global deadline**
— dates live at the course, embassy or consortium level.

The spec's date fields must therefore be nullable *with an explicit `DECENTRALISED` marker*, and
the staging engine must be able to say "this scheme's deadline is resolved per target, not per
scheme". Forcing a date would fabricate one.

Confirmed against the portfolio spec's §8.2: **Chevening's `REQUIRES_OFFER_BY_DATE` pattern is
real and dated** — an unconditional UK offer by 9 July 2026 for the 2026/27 cycle, 8 July 2027 for
2027/28.

---

## 4. Selectivity: better for instruments than for programmes

The earlier corridor research found the denominator largely unpublished for programme admission.
For instruments it is published more often:

| Scheme | Published |
|---|---|
| Türkiye Bursları | **Both halves** — 121,830 applications from 170 countries in 2024, ~200,000 in 2026, against ~5,000 awards a year (YTB) |
| GKS | Award quota, **including per-country allocations** |
| Azerbaijan | 100 awards a year |
| Chevening | 1,545 awards for the 2023 academic year |
| DAAD, Eiffel, MEXT, CSC, Commonwealth, Stipendium, EMJM | Not published |

Two consequences. The band ladder's ordering still stands — the published bar leads — but for
instruments rungs 2 and 3 will fire more often than they will for programmes. And GKS's
per-country quota is a **nationality-level denominator**, which is a better base rate than a global
one and should be preferred where it exists.

The widely-quoted CSC "~30,000 scholarships a year" figure is agency-sourced only and must not be
treated as official.

---

## 5. A new floor rule

A route whose `initiation` is a nomination — by an institution, a consortium or the student's own
government — **cannot satisfy the floor**, because the student cannot cause it to happen. Eiffel,
Azerbaijan, Russia and Commonwealth are upside, not safety. This extends the rule the portfolio
spec already has for `INSTITUTION_NOMINATES` to government nomination, and it is the difference
between a promise the product can keep and one it cannot.

---

## 6. The crawler seed index

This is what the sweep was really for. Instrument discovery seeds from **official index portals
that enumerate schemes**, not from individual scheme pages:

| Country / body | Index portal |
|---|---|
| Germany | `funding-guide.de` / the DAAD scholarship database (stable `?detail=` URLs per programme) |
| France | `campusfrance.org` scholarship directory |
| Japan | `studyinjapan.go.jp` scholarships section (+ `mext.go.jp`, embassy sites) |
| South Korea | `studyinkorea.go.kr` GKS notice board (+ `niied.go.kr`) |
| China | `campuschina.org` (CSC Information System) |
| UK | `chevening.org`; `cscuk.fcdo.gov.uk` (with eligible-country subpages) |
| Turkey | `turkiyeburslari.gov.tr` (+ `ytb.gov.tr` for statistics) |
| Hungary | `stipendiumhungaricum.hu` (news + Call-for-Applications PDFs) |
| Azerbaijan | `studyinazerbaijan.edu.az` (+ `edu.gov.az`) |
| Georgia | `mes.gov.ge`, `iec.gov.ge` — flag as no open inbound scheme; crawl universities directly |
| Russia | `education-in-russia.com` (Rossotrudnichestvo) + embassy pages |
| EU | the Erasmus Mundus catalogue on `erasmus-plus.ec.europa.eu` / `eacea.ec.europa.eu` |

Two of these — the DAAD scholarship database and the EACEA catalogue — are already named in the
discovery plan as seed adapters, and one, the Erasmus Mundus catalogue, is already built.

Schemes named as outside the sample but worth adding later: Italy (DSU, Invest Your Talent), the
Netherlands (Orange Knowledge, Holland Scholarship), Sweden (Swedish Institute), Switzerland
(Government Excellence Scholarships), Taiwan (MOE).

---

## 7. Structural mismatches worth keeping as test cases

- **Georgia** — a country with no open inbound scheme. The schema must be able to say so rather
  than leaving a gap that looks like missing data.
- **Russia** — administered entirely by overseas Rossotrudnichestvo offices; no central calendar.
- **Eiffel** — no applicant-facing portal exists at all.
- **CSC** — carries four-digit agency codes that the extractor must parse to link university, track
  and central record.
- **Erasmus Mundus** — the 10% per-nationality cap, dependent on the compatriot applicant pool.

## 8. Where the two runs conflict

Run 1 states Georgia has no national inbound scheme; run 2 describes IEC-administered reciprocal
schemes for Armenian and Czech citizens. Both are right about different things: there is no *open
competition*, and there *are* bilateral allocations. The model needs both facts, which is why §2.2
adds `BILATERAL` rather than choosing between them.

Run 2's Erasmus Mundus figures (€1,400/month living plus €750/month institutional costs) and run
1's (€1,400/month up to €33,600 total) are not obviously reconcilable; re-fetch from the Erasmus+
programme guide before either is used.
