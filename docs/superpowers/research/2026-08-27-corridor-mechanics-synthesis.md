# Corridor mechanics — synthesis and design consequences

**Date:** 2026-08-27. **Inputs:** two independent deep-research runs over eight destinations
(Germany, France, Japan, South Korea, China, UK, Turkey, Hungary), filed as
`2026-08-27-corridor-mechanics-review-1.md` (better sourced, dates its policy findings) and
`-review-2.md` (conflicts on Korea; found four registers run 1 missed).

**What it answers:** the last three gaps before the portfolio spec is implementable — admission
regime per corridor, the money a student must show and commit, and post-study work rights, which
`phased requirements.md` lines 142/203 demand and which feed the *utility function* rather than the
risk model.

---

## 1. The finding that changes the utility function

**Post-study work rights differ enormously, are officially published, and are changing.**

| Destination | Post-study route | Duration |
|---|---|---|
| UK | Graduate route, unsponsored, no salary floor | **2 years now; 18 months for applications on/after 1 Jan 2027** |
| Germany | §20 AufenthG job-seeking permit | 18 months, non-renewable |
| Japan | 特定活動 job-hunting (6+6), **plus J-Find** for top-100 graduates | 12 months; J-Find up to 2 years |
| South Korea | D-10 job-seeker, points-based | 2 or 3 years — **runs conflict, see §4** |
| France | RECE (replaced APS) | 12 months, non-renewable |
| Hungary | Job-seeking permit, Act XC of 2023 | 9 months, non-extendable |
| China | **No national route.** Shanghai and free-trade-zone pilots only | — |
| Turkey | **No dedicated route.** Employer-sponsored work permit only | — |

This is a genuine differential in the value of an outcome, and the engine currently cannot see it.
A one-year UK master's with two years of unsponsored work rights is worth materially more to most
students than the same degree with none — and the UK's own figure drops by a quarter in January
2027, which changes the ranking of an entire corridor mid-design.

**It also sharpens the corridor decision.** Türkiye Bursları makes Turkey the most accessible
*funding* in the sample — 75% bar, no language certificate, direct application, full package. And
Turkey has **no post-study work route at all**. That is exactly the trade-off the two-axis design
exists to surface honestly: excellent as a floor, poor on mobility. Hungary is similar but milder
(9 months).

**Modelling consequence:** post-study work is a *destination-level* fact, not a programme-level one.
Together with visa financial proof, refusal-data availability and the accreditation register, it
belongs in a new per-country **destination policy** record rather than being copied onto every
programme.

---

## 2. Visa money: five published, three not

| Destination | Required proof |
|---|---|
| UK | **£1,529/month London, £1,171 outside, max 9 months** (£13,761 / £10,539) plus outstanding tuition; held 28 consecutive days. Rates effective for applications on/after 11 Nov 2025, up from £1,483/£1,023 |
| Germany | **€992/month → €11,904** blocked account, tied to the BAföG maximum, in force 2025 and 2026 |
| France | **€877.50/month** (~€10,530/year) from **1 Aug 2026**, up from €615 — indexed to 47% of gross SMIC, so it moves on every SMIC revision |
| South Korea | ₩20m Seoul metro / ₩16m elsewhere — **disputed, see §4** |
| Japan | **No statutory amount.** ~¥2m is a university convention, not an official figure |
| China | **No published threshold** for the X1 visa |
| Turkey | Law 6458 Art. 38 requires "sufficient means"; **no fixed amount published** |
| Hungary | Subsistence proof required; **no single national figure** on oif.gov.hu |

Two consequences. The §5 visa gate can compute cleanly for four corridors and degrades everywhere
else to "proof required, amount assessed" — which must be *disclosed as unknown*, never estimated.
And France's figure is indexed, so it needs re-fetching on a schedule rather than being stored as a
constant.

**A scholarship substituting for financial proof is a first-class route attribute.** Both runs
agree it holds for DAAD, French government (MEAE), GKS, CSC, Chevening, Türkiye Bursları and
Stipendium Hungaricum. Germany states the scholarship must meet or exceed the monthly amount, or
the difference must still be shown. The UK exempts students with a recognised official sponsor
outright.

---

## 3. "Deposit" is a UK-shaped concept that does not generalise

| Destination | Money committed before enrolment |
|---|---|
| UK | Tuition deposit, commonly £2,000–£4,000+, required before the CAS is issued; deducted from the tuition figure evidenced for the visa |
| Japan | **入学金 enrolment fee ¥282,000** (MEXT statutory), non-refundable on enrolment |
| South Korea | 입학금 being phased out; run 2 claims full first-semester tuition prepayment is now required before the Certificate of Admission — **disputed, see §4** |
| Germany, France | **No deposit culture at public universities.** A Semesterbeitrag or CVEC is paid after enrolment |
| China, Turkey, Hungary | Per-university; no national rule |

So the money model needs a **commitment payment with a type** — deposit, enrolment fee, tuition
prepayment, or none — rather than a field called "deposit" that is null for half the world. The
timing rule from the portfolio spec (§8.3) still holds where a payment exists; where none exists,
the wait-for-the-scholarship strategy is unconstrained by it.

---

## 4. Where the runs conflict — Korea, three times

| Fact | Run 1 | Run 2 | Position taken |
|---|---|---|---|
| D-10 duration | 3-year cap, reformed effective **29 Oct 2025**, 1-year renewal increments | 2-year maximum, 6-month initial | **Run 1, provisionally.** It is specific and dated; run 2 reads like the pre-reform position. Run 1 flags it could not pin the change to a stable HiKorea URL — verify before use |
| D-2 financial proof | ₩20m / ₩16m, KRW-denominated | **$20,000 USD** | **Run 1.** It explicitly states the USD figure is superseded by the KRW standard. Run 1 also flags its source was a visa-application-centre page, not the ministry — verify |
| Deposits | 입학금 phased out; per-university | Full first-semester tuition prepaid before the Certificate of Admission; refundable on visa denial | ~~Unresolved.~~ **RESOLVED 2026-08-28 by round 2** (`2026-08-28-corridor-mechanics-round2-synthesis.md` §1). Both runs were right about different things: the 입학금 phase-out excludes graduate programmes, so it never applied here, and the tuition prepayment is real and nationally mandated by MOE directive. Amount stays per university |

One more disagreement worth noting: run 2's executive summary characterises Germany as
"retrospective, capacity-driven", which run 1 contradicts with the more careful finding that
**NC-style retrospective cutoffs generally do not apply to international master's applicants** —
they are chiefly an undergraduate and limited-programme mechanism. Run 1 is right, and the
distinction matters: it is what makes Germany rule-based at master's level.

---

## 5. What both runs agree on, and what it settles

**Admission difficulty for international applicants is essentially unpublished everywhere.** Japan's
倍率, Korea's 경쟁률 and China's 报录比 exist, but are university-published, usually aggregate, and
usually domestic — international tracks are not broken out. France publishes capacity per programme
on monmaster.gouv.fr but not applicant ratios, and non-EU applicants resident abroad do not use that
platform at all. The UK publishes no postgraduate acceptance-rate dataset.

That **settles the band ladder ordering**: distance from the published bar leads, and the
counts rung will almost never fire for admission. It fires for *instruments*, not for programmes.

**Admission regimes, confirmed:**

- Rule-based, bar published in advance: **UK, Germany, Turkey, Hungary**
- Competitive against published capacity: **France** (but non-EU applicants abroad go through
  Études en France, not monmaster)
- Exam-gated, per-university: **Japan** — and international applicants are often routed through a
  non-degree 研究生 year first, which is a structural fact the model must be able to express
- Holistic per-university review against institutional international quotas: **South Korea**
- **China: internationals are exempt from 考研** entirely and apply directly to universities under
  自主招生 — the headline national exam does not apply to them

**Visa refusal rates by nationality:** only the **UK** publishes them cleanly (Home Office Vis_D02 /
Vis_04). Turkey publishes grants by nationality but not refusals; Hungary has only Eurostat-level
data; Germany, France, Japan and Korea publish aggregates; China publishes nothing. So visa risk is
a *band* for the UK and a *gate plus disclosure* everywhere else.

**Accreditation registers:**

| Machine-readable | Human-readable, scrape and cache |
|---|---|
| UK — Office for Students Register (CSV) | Germany — Hochschulkompass, Akkreditierungsrat, anabin |
| France — RNCP via data.gouv.fr | China — jsj.moe.gov.cn |
| Korea — 대학알리미 open API on data.go.kr (run 2) | Turkey — YÖK / YÖKSİS |
| Japan — e-Stat API, but statistical census data, **not** an accreditation-status endpoint (run 2) | Hungary — Oktatási Hivatal FIR |

**Recognition back home (`R§203` degree portability).** ENIC-NARIC publishes a directory of national
recognition centres covering 56 Lisbon Convention countries. Most centres assess **case by case** and
issue individual comparability statements. Four publish actual lists, and they are the ones worth
ingesting: **Germany's anabin** (H+/H−/H+- status per foreign institution), **China's
jsj.moe.gov.cn** (10,000+ recognised foreign universities), **Ireland's QQI** foreign-qualifications
database (2,000+ qualifications from 160+ countries) and **Poland's NAWA KWALIFIKATOR**.

So degree portability can be automated for a handful of home countries and must otherwise be a
disclosure or a consultant task — not silently omitted.

---

## 6. Design consequences

| # | Consequence | Basis |
|---|---|---|
| 1 | Add a **destination policy** record per country: financial-proof rule, post-study work route and duration, refusal-data availability, accreditation register, commitment-payment norm | §1, §2, §3 |
| 2 | Post-study work rights feed `MOBILITY_FIT`, which already exists as a weighted dimension — this is a **utility** input, not a risk input | §1 |
| 3 | `satisfies_financial_proof` becomes a funding-route attribute | §2 |
| 4 | Replace "deposit" with a typed **commitment payment** — deposit / enrolment fee / tuition prepayment / none | §3 |
| 5 | The visa gate computes for UK, Germany, France and Korea; elsewhere it discloses "amount assessed, not published" | §2 |
| 6 | Visa risk is a band for the UK only; a gate plus disclosure elsewhere | §5 |
| 7 | Band ladder ordering confirmed: published bar first; counts fire for instruments, not admission | §5 |
| 8 | Admission regime flag needs five values, not three: rule-based, capacity-competitive, exam-gated, holistic-with-quota, and **research-student-precursor** (Japan) | §5 |
| 9 | The legitimacy gate automates for UK and France now, Korea and Japan partially; scrape-and-cache elsewhere | §5 |
| 10 | Degree portability automates via anabin, jsj.moe.gov.cn, QQI and NAWA; disclosure elsewhere | §5 |
| 11 | France's threshold is SMIC-indexed and the UK's Graduate route changes on 1 Jan 2027 — **destination policy needs a freshness window and a re-fetch schedule**, like any other claim | §1, §2 |

---

## 7. Must be verified before encoding

1. Korea's D-10 cap — 2 years or 3 — against a Ministry of Justice or HiKorea page.
2. Korea's D-2 financial threshold against 법무부 or studyinkorea.go.kr rather than a visa-centre page.
3. Korea's deposit/tuition-prepayment practice — the two runs disagree and the amount at risk is large.
4. Germany's 2026 Sperrkonto figure on auswaertiges-amt.de directly.
5. Japan's ~¥2m convention — confirm it is convention, and that no statutory figure exists.
