# Portfolio engine — data availability research

**Date:** 2026-08-27. **Purpose:** answer the six questions that gate the risk-aware portfolio
design. Each finding is a primary-source fact; each ends with what it changes in the design.

Method: narrow per-question fetches against named official sources, not a bundled deep-research
call (per the 2026-08-22 observation that bundled calls time out and get re-fetched anyway).

---

## Q1 — Admission regimes and difficulty data

**Germany.** A programme's admission-restriction status (`zulassungsfrei` — open admission, vs
`zulassungsbeschränkt` — restricted) is **published per programme** by Hochschulkompass. But the NC
value itself "is only ever calculated retrospectively, after all applications have been received";
prior-semester values are published only as reference. Institutions may add further criteria —
motivation letter, tests, interviews.
Sources: <https://www.hochschulkompass.de/en/degree-programmes/application-admission/admissions-procedure/local-admission-restrictions.html>,
<https://www.uni-assist.de/en/tools/glossary-of-terms/description/term/numerus-clausus-nc/>

**United Kingdom.** Postgraduate taught admission is conditions-based: an offer is made against
stated academic and English-language conditions and becomes unconditional when they are met.
Source: <https://www.manchester.ac.uk/study/masters/admissions/after-you-apply/acceptance-deposits/>

**What it changes.** The `AdmissionBand` ladder must lead with **distance from the published bar**,
not with base rates. A retrospectively-computed NC is not a threshold anyone can be measured
against in advance, and a conditions-based offer is *definitionally* rule-based. The extractable
fact is the **regime flag** (open / restricted / exam-gated), not a numeric admission threshold.

---

## Q2 — Are award and applicant counts published?

**DAAD** publishes country statistics giving the **number of scholarship recipients** per country.
It does **not** publish applications received. The numerator without the denominator.
Source: <https://www.daad.de/en/the-daad/communication-publications/facts-figures/daad-country-statistics/>

**Chevening** publishes neither raw count year-by-year, but states the **selection rate directly**
— "only 1% of those who apply eventually being selected" — alongside ~1,500 awards available for
2025/26.
Source: <https://www.chevening.org/scholarships/>

**What it changes.** Rung 1 of the band ladder (awards ÷ applicants) will be **sparse**, because the
denominator is the scarce half. But a *published rate* is sometimes given where the counts are not,
so the extraction contract needs `published_selection_rate` as a field in its own right — not only
`awards_per_cycle` and `applicants_per_cycle`.

---

## Q3 — Are deadlines and decision dates published?

**Yes, and in full, for major schemes.** Chevening publishes a complete dated timeline for the
2027-28 cycle: applications open 4 August 2026; deadline 6 October 2026 at 11:00 UTC; shortlisting
mid-February 2027; interviews March–April 2027; **results from mid-June 2027**; and an **offer
deadline of 17:00 BST on 8 July 2027**.
Source: <https://www.chevening.org/scholarships/application-timeline/>

**The structural finding.** That offer deadline reads: *"The deadline to receive and submit at least
one unconditional UK university offer is … 8 July 2027."* The scholarship **requires the student to
already hold an unconditional university offer** before it will fund them. The university
applications must therefore happen *before* the scholarship result — the opposite of "wait for the
scholarship, then apply to programmes".

**What it changes.** Staging is not one pattern but three, and the pattern is a property of the
funding route:

| Pattern | Meaning |
|---|---|
| `SCHOLARSHIP_RESOLVES_FIRST` | The decision lands before any programme commitment is due. Waiting is free |
| `REQUIRES_OFFER_BY_DATE` | The scholarship demands an admission offer in hand by a stated date (Chevening). Waiting is **impossible** — programme applications must be paid for first |
| `INDEPENDENT` | Neither constrains the other |

---

## Q4 — Deposits

UK postgraduate taught deposits are **standard practice, non-refundable, and time-boxed to the
offer**: the payment deadline is "typically four to six weeks from the date of your offer", the
deposit is a precondition for issuing the CAS (and therefore for the visa), and non-payment means
the offer may be withdrawn. Refunds exist in narrow cases — a refused visa, or the course not
running — **not** for a lost scholarship.
Sources: <https://www.manchester.ac.uk/study/masters/admissions/after-you-apply/acceptance-deposits/>,
<https://study.ed.ac.uk/postgraduate/fees-funding/tuition-fees/deposits>,
<https://sheffield.ac.uk/fees/fee-deposits>, <https://www.leeds.ac.uk/masters-fees/doc/tuition-fee-deposits-masters-applicants>

**What it changes.** Two things, both structural:

1. **The binding date for "can we wait?" is the deposit deadline, not the application deadline.**
   The design's current pivot (`scholarship_decision_deadline` vs `application_deadline`) tests the
   wrong pair. A student can apply cheaply and still be forced to commit £2,000 months before the
   scholarship answers.
2. **The deposit window is relative to the offer date**, which is unknown when the pack is built. So
   the catalog holds `deposit_required`, `deposit_amount`, `deposit_window_days`, and the schedule
   reasons in relative time — "≈4–6 weeks after an offer you may receive in February".

It also breaks the current budget model: `application_budget` covers fees only, but a student faces
**four money buckets with different timing** — application fees, at-risk deposits, visa financial
proof, and tuition/living.

---

## Q5 — Visa: financial proof and refusal risk

**Financial proof is a hard cash gate that funding does not remove.**

- **United Kingdom:** £1,529/month for London, £1,171/month outside London, for up to 9 months
  (≈£10,539 outside London), *plus* tuition. The money "must have this money for at least 28 days in
  a row", ending within 31 days of the application. A sponsored student is **not exempt** — they
  evidence the sponsorship instead.
  Source: <https://www.gov.uk/student-visa/money>
- **Germany:** €992 per month since 1 January 2025 → a blocked account (Sperrkonto) of **€11,904**
  for twelve months. Alternatives exist (parental income, a §66–68 AufenthG declaration of
  commitment, an annually renewable bank guarantee).
  Source: <https://www.auswaertiges-amt.de/en/sperrkonto-388600>

**Refusal risk is measurable, at least for the UK.** The Home Office publishes entry clearance visa
applications and outcomes **by nationality and visa type** (detailed datasets Vis_D01, Vis_D02),
updated to year ending March 2026, in ODS/Excel.
Source: <https://www.gov.uk/government/statistical-data-sets/immigration-system-statistics-data-tables>

**What it changes.** Visa enters the design twice: as a **hard gate** (can this student show the
required funds, scholarship or not?) and as a **third risk axis** with real rung-1 data for the UK.
Critically it is a *destination-level* risk correlated across every candidate in that country — so
the diversification rule, which currently counts funders, would score three German programmes as
diversified when they share one visa decision.

---

## Q6 — Accreditation and recognition (the legitimacy gate)

**DEQAR** (Database of External Quality Assurance Results, run by EQAR) holds records on **4,000+
institutions across 42 European countries**, harvested from ETER/OrgReg, and exposes a
**machine-readable API**. Access requires registration: `https://backend.deqar.eu/webapi/v2/...`
returns **HTTP 403** without a token, confirming the design's §7 open item 4.
Sources: <https://www.eqar.eu/qa-results/find-out-more/essential-info/>, <https://docs.deqar.eu/stable/quick_start_guide/>

**What it changes.** A legitimacy gate is automatable for Europe once DEQAR registration is done —
that becomes a prerequisite task, not an open item. It does **not** cover Japan, Korea or China, nor
does it establish **home-country recognition**, which is the binding list for a state-scholarship
holder and is what `phased requirements.md` line 203 means by "degree-portability". Those remain
consultant-verified per corridor.

---

## Consolidated design corrections

| # | Correction | Source |
|---|---|---|
| 1 | `AdmissionBand` ladder leads with distance-from-published-bar; counts are secondary | Q1 |
| 2 | Extract `published_selection_rate`, not only raw counts | Q2 |
| 3 | Extract the admission **regime flag** per programme, not a numeric threshold | Q1 |
| 4 | Staging has three patterns; `REQUIRES_OFFER_BY_DATE` forbids waiting entirely | Q3 |
| 5 | The wait/commit pivot is the **deposit deadline**, expressed in relative time | Q4 |
| 6 | Budget is four buckets — fees, deposits, financial proof, tuition/living — not one | Q4, Q5 |
| 7 | Visa is a hard gate (financial proof) **and** a third risk axis, correlated per destination | Q5 |
| 8 | Diversification must count destinations (visa) as well as funders | Q5 |
| 9 | Legitimacy gate via DEQAR for Europe; consultant elsewhere; registration is a prerequisite | Q6 |

## Not yet answered

- Whether Japan, Korea and China publish admission or award statistics at all (not probed).
- Whether Schengen/national-visa refusal rates are published per nationality for Germany and France
  the way the UK publishes them.
- Deposit practice outside the UK (Germany charges no deposit in the usual case, but this was not
  verified against a primary source).
- Azerbaijan's own recognition list and state-programme approved-destination list.
