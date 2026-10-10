# Risk-Aware Application Portfolio (Design)

**Status:** design, 2026-08-27. **Supersedes §3 of**
`docs/superpowers/specs/2026-08-27-phase5-discovery-and-pack-optimizer-design.md`, which described
a competitiveness tier plus a fixed reach cap. Both of those are withdrawn — see §3.

**Requirements covered:** `phased requirements.md` P1-3, P1-4, P1-6, P1-7, R§2.1, R§3.3
(deterministic-scoring boundary), R§6.1 (personal data), R§7.1 (freshness), R§9 (no outcome
promises), and lines 142/203 (post-study work, mobility, degree portability), which the superseded design
dropped.

**Section references:** `§n` means a section of *this* document; `R§n` means `phased
requirements.md`.

**Research inputs, all filed under `docs/superpowers/research/`:**
`2026-08-27-portfolio-data-availability.md` (what the corridors actually publish),
`2026-08-27-portfolio-theory-synthesis.md` (what the literature proves), and the two deep-research
runs behind it.

---

## 1. What this subsystem does

Given a student profile, a budget, and a catalog of programmes and funding opportunities, produce
an application portfolio: which applications to make, in what order to commit money, and what each
one is for — with every claim traceable to an official source.

**In scope:** the objective, the funding-route model, the two risk bands, the gates, the optimizer,
the staged money schedule, and the display contract.

**Out of scope:** discovery itself (`§2` of the superseded document, being built now); the
awardee-profile layer; and any calibrated per-student probability, which requires outcome data
that does not exist yet (§10).

**Phase gate — lifted by the owner 2026-09-25.** This used to read: nothing here serves students
until the manual consultant procedure has produced a recorded §3.5 baseline over one admissions
cycle. The owner removed that condition "for now"
(`2026-09-25-tailored-programme-finding-design.md`, decision T18). What still holds: no
probability is shown to a student (§9, R§9).

---

## 2. The objective

**Maximize the expected value of the best offer the student ends up holding, subject to a floor
constraint and an application-fee budget that the portfolio aims to spend in full.**

The earlier framing — maximize the probability of at least one acceptable outcome — is wrong, and
wrong in a way that matters. For a strong applicant that probability is already ≈ 1, so the
objective is degenerate and would happily recommend a portfolio of safe options the student does
not want. Securing an acceptable outcome is a **constraint**; the quality of the best outcome is
the **objective**.

This is exactly the objective Chade & Smith formalise (`Simultaneous Search`, Econometrica 74(5),
2006): choose a set of options, each with a cost and an uncertain outcome, maximising the expected
maximum utility over the offers received.

**Utility is already built.** `StudentProfileSnapshot.weights` over the evaluation dimensions —
academic fit, programme fit, career fit, affordability, duration, mobility fit, research fit —
scored in `apps/funding/evaluation.py`, *is* the cardinal utility these models assume as a
primitive. Every paper in the literature assumes it and none elicits it; we happen to have it
already.

Each candidate carries **two** utilities, because the outcome is not binary: `u_funded` and
`u_unfunded`. They differ mainly on the affordability dimension. A candidate whose unfunded cost
exceeds what the student can cover has no `u_unfunded` — that outcome is not available to them.

**"What the student can cover" must include permitted work income — a defect found 2026-08-29**
(`research/2026-08-29-synthesis-crosscheck.md` §1). The corridor research established post-study
work rights thoroughly and never asked whether a student may work *while enrolled*. They usually
may, and the amounts are not marginal: Germany permits 20 h/week (140 full days a year) at a
€13.90 minimum wage — **about €1,112/month, the same order as the €992/month DAAD stipend** — and
public universities charge only a semester fee. South Korea permits 20 h/week in term and unlimited
hours in official vacations.

So the availability test as written **discards outcomes that are genuinely available**, silently and
with no disclosure that a widening exists. A German programme can be unaffordable unfunded on paper
and affordable in practice.

Three constraints on how it enters:

1. **It is not a funding route.** It is a property of the *destination and study mode* that shifts
   the affordability threshold. It must never contribute to `covers_commitment_payment`, and never
   make a funded outcome look better than it is.
2. **It is not guaranteed.** The income depends on finding work, often in a language the student
   does not speak. Where it is what makes a candidate affordable, the pack says so explicitly rather
   than folding it into a single number.
3. **It interacts with study mode, and getting that wrong is a real error.** A UK student sponsored
   for a **part-time** postgraduate course **may not work at all**. Recommending one to a student
   relying on work income is wrong in a way nothing else in this model would catch.

`DestinationPolicy` therefore carries term-time and vacation work limits alongside the post-study
work route it already holds — the two are different facts serving different parts of the model, one
affordability and one utility.

**And a repayable award is not coverage — a second affordability defect, found 2026-08-29**
(`research/2026-08-29-gapfill-openitem-verification.md` §2). The Aga Khan Foundation's International
Scholarship Programme, open to Kyrgyz and Tajik nationals, states it plainly:

> "AKF ISP awards are structured as **half grant and half loan** – where you need to repay 50 percent
> of the award amount. […] A **guarantor is required to co-sign** the award agreement. Repayment of
> the loan component, which **includes a service charge**, begins six months after […] graduation."

`FundingBenefit` has no concept of repayment. An award recorded as coverage would tell a student a
place is funded when half of it is debt, and netting it against cost overstates what they have by
the repayable half plus its service charge. Two consequences:

1. **A benefit carries a repayable share** — nil for a grant, a fraction or an amount for a
   half-loan, with the service charge where one is stated. Only the non-repayable part reduces the
   affordability gap; the repayable part is disclosed as an obligation the student is accepting.
   Prodigy and Mpower, which AKF itself lists alongside its award, are pure loans and must never be
   recorded as coverage at all.
2. **A guarantor requirement is a hard gate, and not a number.** It cannot be compared against any
   profile field, so it belongs with the applicant conditions of §4 that route to review rather than
   to a pass or a fail — and for a student without family able to co-sign it may be the binding
   constraint, not the money. A pack that names a half-loan award without naming the guarantor has
   not told the student what they are accepting.

The two defects are the same shape: the model was treating a *quantity* of money as the whole
question, when the money's **conditions** — may I earn it, must I repay it — decide whether the
outcome is available at all.

**An outcome the student cannot commit to is not available either.** The same rule extends to
§5.1's commitment payment, and it has to: a UK offer requires £2,000–£4,000 within four to six
weeks, before the CAS and therefore before the visa. A student who cannot produce that money has
not won a place, whatever the offer letter says. Without this rule the optimizer would spend the
fee budget on outcomes that were never takeable, which is worse than recommending nothing.

**Unless a route the student is taking covers it — and many national schemes do.** A government
scholarship that pays tuition ordinarily settles the enrolment fee or deposit as well: MEXT covers
Japan's ¥282,000 入学金, and Türkiye Bursları, GKS and Stipendium Hungaricum each cover the
institutional charges that would otherwise fall due at commitment. So the availability test runs
**per route**, not per candidate: an outcome funded by a route whose coverage includes the
commitment payment is available even when the student could not pay it themselves.

Whether a route covers it is a **cited fact about that scheme, never an assumption** — a scholarship
that pays tuition does not automatically pay a deposit, and the UK deposit in particular is deducted
from tuition rather than added to it, so the two interact per institution. Where no claim states it
either way, the coverage is unknown, the outcome is treated as unavailable, and the pack says which
fact would change that. This is what §12's `covers_commitment_payment` exists to carry.

### 2.1 The fee budget is a target, not only a ceiling

**Decided 2026-08-27.** A fee is **not** deducted from an application's value. It consumes budget
and nothing else, and the portfolio aims to **spend the student's fee budget in full**. A student
who allocated €300 to applications did so meaning to use it; handing €150 back is a worse outcome
than one more real attempt, and the engine treats unspent budget as a result to be justified rather
than a saving to be congratulated.

The alternative was considered and rejected: netting the fee against the application's marginal
value would leave budget unspent whenever the next-best application improved prospects by less than
its own fee. That is defensible in the abstract and wrong for this product.

**The one thing it may not do is buy an application worth nothing.** Two candidates are worth
exactly nothing, and neither is a matter of degree:

- a second application on a funder already in the portfolio — §7.2 makes that outcome identical to
  the first, so the second fee buys a duplicate of a decision already made;
- an application whose every outcome is worse than the floor the student already holds — §7.3's
  outside option zeroes it mechanically, without a rule of its own.

So the ordering is: **among portfolios of equal expected value, prefer the one that spends most of
the budget; never spend on a zero.** Where the remaining budget can buy only zeros, the pack
**states the unspent amount, why nothing was worth buying with it, and which of §7.5's widenings
would produce something that is.** Silent underspend is forbidden — a student who sees €150 unspent
and no explanation cannot tell a careful decision from a broken one.

**In the recursion (§7.3) this is already the behaviour**: `g_i` appears only as `b − g_i`, never
subtracted from `t_i`. The spend-the-budget preference is a tie-break over portfolios the DP scores
equally, not a change to the recursion.

---

## 3. What the theory permits, and what it forbids

Recorded in full in `2026-08-27-portfolio-theory-synthesis.md`. Four consequences bind this design:

**3.1 Greedy is out.** Chade & Smith's Marginal Improvement Algorithm is proven optimal only under
independence *and* costs identical across options. We violate both: application fees range from €0
to about €150 with deposits on top, and outcomes are correlated. Either violation alone removes the
guarantee (Kapur & Hong, arXiv:2205.01869, 2022, prove the heterogeneous-cost case NP-complete with
no greedy guarantee; Ali & Shorrer, AER 115(2), 2025, show optimal portfolios are not nested under
correlation, so their algorithm is explicitly not greedy).

**3.2 Exact is affordable anyway.** NP-completeness is asymptotic. A student's candidate set is
tens of options, not thousands, so the exact dynamic program is tractable and we need no
approximation. §7 gives the recursion.

**3.3 The floor is the shape of the optimum, not a guardrail.** Ali & Shorrer, Theorem 1: under
correlated outcomes, an optimal portfolio of more than one application contains **both a reach and
a safety**. Under *independence* the opposite holds — Chade & Smith's "No Safety Schools Theorem"
says the optimum gambles up and includes no safety at all. Our floor is justified by the
correlation structure specifically, and the spec says so rather than appealing to prudence.

**3.4 No fixed reach/target/safety ratio has any empirical support.** The `floor(paid_slots / 3)`
reach cap in the superseded design is withdrawn. The mix is derived from the objective, the
correlation structure, and the outside option.

**3.5 The behavioural evidence — added 2026-08-29, and it is the warrant for this product.** §§3.1–3.4
establish what the *optimal* portfolio is. They say nothing about whether students build one, and
the literature on that is strong, experimental and directly on point.

Hoxby & Avery find that *"the vast majority of very high-achieving students who are low-income do
not apply to any selective college or university."* Hoxby & Turner's Expanding College Opportunities
project — a **randomised controlled trial** — found that semi-customised information on the
application process and net prices *"substantially raises students' probability of applying to,
being admitted at, enrolling at, and progressing at selective colleges"*, with treated students
admitted to **12% more colleges** and **31% more likely** to be admitted to a peer institution.

Two things follow, and the second is a design constraint rather than encouragement:

1. **The intervention is evidenced.** An RCT shows that information changes application behaviour
   and outcomes for a population defined by information scarcity rather than by ability — which is
   this product's population.
2. **Expect the student's prior to be skewed against the reach.** §7 produces a reach-and-safety
   portfolio; the undermatching literature says the student will be disposed to drop the reach. A
   pack that merely *offers* one is therefore not sufficient — it has to say why the reach is in
   there, in terms the student can act on. **Undermatching rate is a candidate calibration metric
   for §10**: the share of students who decline the reach the optimizer selected.

Both citations are **unverified** and fall under §14 item 6's rule — read the papers before anything
load-bearing rests on them. They are recorded because their absence from
`2026-08-27-portfolio-theory-synthesis.md` is itself the finding: that synthesis searched
optimal-portfolio theory and never the behavioural literature beside it.

---

## 4. The route to yes

Each candidate carries one or more **funding routes** — concrete ways the money could work. A
candidate is *achievable* if at least one route is viable. This replaces the single
`funding_dependency` filter and makes every row explainable in one line: *you get in because you
meet the published bar; you pay for it with X.*

A route is not a name from a list; it is a set of attributes, because the examples differ along
axes that each change the algorithm differently.

| Attribute | Values | What it changes | Already modelled |
|---|---|---|---|
| Source | the **eleven** `FundingFamily` values (below) | Which student facts are relevant | `FundingFamily` |
| Binding | global / country / institution / programme | Portable across an approved list, or attached to one target | `OpportunityScope` + `programs` M2M |
| **Origin** | home country / destination country / third country / supranational / **bilateral** | **Correlation grouping** (§7.2) | **new field** |
| **Initiation** | see below | Whether it costs a slot, can be staged, can be a floor | **new field** |
| Coverage | tuition / stipend / housing / travel, amount, period | Affordability and the unfunded gap | `FundingBenefit` |
| Own gates | eligibility rules, caps, field limits, approved list | Hard filters, before any band | `BenefitRule` |
| **Applicant conditions** | work experience, age cap, means test, values or affiliation, return service | **Hard filters a nationality list cannot express** — see below | **new field** |
| **Satisfies financial proof** | yes / partly / no | Whether the award removes the §5.1 visa cash gate | **new field** |
| **Dates** | application deadline, decision date, offer-required-by date | The staged schedule (§8) | **partial** |

**Applicant conditions is a 2026-08-29 addition, and it is not an edge case.** The nationality-keyed
research found the same pattern in scheme after scheme: **ADB-JSP** requires two years' post-degree
professional experience, an age under 35, a means test (family income ≤ USD 50,000, individual
≤ USD 25,000, verified by certified tax returns) and a signed two-year return commitment;
**JJ/WBGSP** requires "relevant professional experience"; **Fulbright Uzbekistan** requires two
years; **TEV** requires a bachelor's from a YÖK university, GPA ≥ 3.0/4.0 and an age under 35;
**Konrad-Adenauer-Stiftung** expects endorsement of Christian Democratic values.

A model that filters only on nationality **offers students schemes they cannot enter**, which is
worse than omitting them — the pack would name a route the student then discovers is closed. The
recurring one is the professional-experience gate: the large development-flavoured schemes
systematically exclude fresh graduates, who are most of our population.

**Return service belongs here too.** ADB-JSP, Bolashak and YLSY all bind the graduate to return
home for a stated period. A bonded award is a materially different product from an unbonded one and
the student must be told which they are accepting, so this is a disclosure obligation and not merely
a filter.

**But the funder is not the only source of a bond.** Fulbright imposes no service obligation of its
own and its grantees are still bound for two years, by §212(e) of the US Immigration and Nationality
Act attaching to the J-1 visa. That obligation belongs on `DestinationPolicy` keyed to the visa class
(§8.3), not here — it applies to every J-1-sponsored award including the schemes whose own pages never
mention it, and restating it per scheme would both duplicate it and miss it wherever a page is silent.
`RETURN_SERVICE` on the route means *the funder imposes this*; the visa rule is a property of the
destination. A student may be subject to both, and concurrent obligations are not additive.

**Two new `FundingFamily` values — eleven, not nine.** Both express funder behaviour no existing
value can, and neither is a relabelling:

| New value | Why the existing nine cannot hold it |
|---|---|
| **`AFFINITY_OR_DIASPORA`** | Eligibility keyed to **descent, heritage or religion rather than citizenship**. AGBU funds students "of Armenian descent" *worldwide*, including non-citizens of Armenia; Calouste Gulbenkian and the Aga Khan Foundation are the same shape. This is a different *kind* of eligibility, not a different funder — no other family implies a rule the student's passport cannot answer |
| **`PRIVATE_FOUNDATION`** | Endowments pursuing their own agenda: Germany's party-affiliated *Stiftungen* (Konrad-Adenauer €992/month, Heinrich-Böll €934/month, Friedrich-Ebert) and national education foundations such as **Türk Eğitim Vakfı**, which is the principal outbound master's channel for Turkish citizens. `INDUSTRIAL_SPONSORSHIP` is plainly wrong — there is no employer, no commercial interest and no bonding to a company |

**Deliberately *not* added**, because the attribute model already carries them:

- **Sub-national government** (Bavaria's state programme; BAYHOST, which funds graduate students from
  ten named countries) stays `GOVERNMENT_SCHOLARSHIP`. What differs is where you *find* it, which is
  a discovery concern, not a portfolio one.
- **Bilateral commissions** (Fulbright's ~160 national commissions) stay `GOVERNMENT_SCHOLARSHIP`
  with `Origin = bilateral`, a value this table already has.
- **Development banks** (ADB, IsDB, World Bank) are `MULTILATERAL`, which fits.

Adding a family for each of those would grow the enum without changing a single decision the
optimizer makes.

**Initiation** does the most work:

| Value | Example | Consequence |
|---|---|---|
| `AUTOMATIC_ON_ADMISSION` | many tuition waivers | One decision. `FundingBand` = `AdmissionBand`. Can be a floor |
| `CONSIDERED_WITH_ADMISSION` | ICIQ master's, most departmental awards | One application, two outcomes. No second fee or deadline |
| `STUDENT_APPLIES_SEPARATELY` | DAAD EPOS, TotalEnergies, the Azerbaijani state programme | Own form, deadline, sometimes fee. Consumes a slot. Stageable |
| `INSTITUTION_NOMINATES` | Eiffel — no applicant-facing portal exists at all | The student **cannot apply**. Free upside on an admission; never a slot, never a floor |
| `HOME_GOVERNMENT_NOMINATES` | Azerbaijan's Heydar Aliyev grant, Russia's quota, Commonwealth | The student's own government must put them forward. Never a floor, for the same reason |
| `JOINT_SELECTION` | CSC at UNISTRA, GKS, MEXT, Stipendium Hungaricum | Two bodies must both say yes. Band is the worse of the two; both timelines must align |

Eiffel is why the field is necessary: without it the engine would tell a student to apply for
something they have no way to apply for. The 2026-08-27 instrument sweep found this is not an edge
case — **five of twelve national schemes cannot be applied to directly by a student.** What limits
a student's accessible set is far more often the initiation rule than the academic bar.

### 4.1 A scheme is a set of tracks, not a single route

GKS and MEXT each run an **embassy track** and a **university track**, with different quotas,
different deadlines and different selection bodies. A scheme modelled as one row with one
`initiation` value cannot represent either. So a funding opportunity carries one or more **tracks**,
and initiation, timeline, quota and sometimes the eligible-country list all hang off the track
rather than the scheme.

### 4.2 Nationality eligibility is a rule, not a list

Observed forms, all from published sources:

- **Bloc membership** — OIC, the Non-Aligned Movement, Small Island Developing States, the
  Commonwealth, "MEXT-designated countries", Hungary's 90+ partner countries.
- **An explicit country list** — Chevening's 160+, DAAD EPOS's developing-country list.
- **A bilateral agreement** — Georgia's reciprocal allocations with Armenia and Czechia, which is
  why `origin` needs `BILATERAL`: the key is a country *pair*.
- **A per-nationality quota** — GKS publishes them. The 2026 graduate quota is 2,000, split 800
  embassy / 1,200 university, with per-country allocations.
- **A per-nationality cap tied to the applicant pool** — Erasmus Mundus caps any one nationality at
  **10% of an intake**. A student's chance therefore depends on how many compatriots apply, which
  no static eligibility flag can express.

**A per-nationality quota is a better denominator than a global rate**, and where one exists the
band ladder must prefer it (§7.1).

### 4.3 Dates may be decentralised, and that is a value, not a gap

DAAD, CSC, MEXT, Russia and Erasmus Mundus publish **no scheme-wide calendar** — deadlines live at
the course, embassy or consortium level. Only Eiffel, GKS, Türkiye Bursları, Stipendium
Hungaricum, Chevening and Commonwealth have clean central dates. Date fields are therefore nullable
with an explicit `DECENTRALISED` marker; the staging engine resolves those per target and never
fabricates a date.

**Satisfies financial proof** earns its place because the corridor sweep found it holds across the
board: DAAD, the French government (MEAE), GKS, CSC, Chevening, Türkiye Bursları and Stipendium
Hungaricum all substitute for the visa's cash requirement. Germany qualifies it — the award must
meet or exceed the monthly amount or the difference must still be shown — and the UK exempts a
student with a recognised official sponsor outright. Without this field the engine would tell a
fully funded student they cannot afford a place they can.

**Origin** matters more than it looks. DAAD and the Azerbaijani state programme are both
`GOVERNMENT_SCHOLARSHIP` and behave nothing alike. A destination-origin instrument is a separate
decision per country. A **home-origin instrument is one decision, made once, covering every
destination on its approved list** — so eight candidates funded by it are one funding bet crossed
with eight admission bets, not eight bets. That is the correlation §7.2 must model, and it is also
why a home-origin instrument is the natural stage-1 application (§8).

---

## 5. Gates: the bar is a gate, the competition is a band

A precision that removes most of the confusion in ranking weak profiles:

- The student misses a **published, formal** requirement — a stated minimum grade, a required
  certificate, a nationality exclusion → **excluded, with the citation**. Not a reach. Applying is
  a wasted fee.
- The student meets the bar but many good people also do → that is a **REACH**, and a legitimate
  use of budget.

Stanford for a 70-GPA student is a gate failure, not a reach. A UK taught master's for the same
student, bar met and admission rule-based, is LIKELY. Same student, both facts, no contradiction.

Four gate families run before any band is computed:

1. **Existing hard gates** — `apps/funding/evaluation.py`, unchanged.
2. **Published-bar gate** — per criterion, using *that target's own* published conversion rule for
   grades. No rule → `NOT_COMPARABLE`, which is disclosed, never guessed.
3. **Instrument gate** — if the student holds or intends a portable instrument, its published
   approved list, caps and field restrictions are a hard filter. Anything off the list cannot be
   funded by it, and the pack says exactly that rather than ranking it lower.
4. **Legitimacy gate** — accreditation and home-country recognition (§6).

**Visa financial proof is a fifth gate, and funding does not remove it.** Germany requires €992 per
month, i.e. a blocked account of **€11,904**, since 1 January 2025. The UK requires **£1,171 per
month outside London** (£1,529 in London) for up to 9 months, held for 28 consecutive days ending
within 31 days of the application — and a sponsored student is *not* exempt; they evidence the
sponsorship instead. A student who cannot show the funds cannot take a place they have won.

---

### 5.1 Destination policy — country-level facts the model had nowhere to put

Financial proof, post-study work rights, refusal-data availability, the accreditation register and
the local commitment-payment norm are properties of a **destination country**, not of a programme.
Copying them onto every programme row would duplicate them thousands of times and let them drift.
They live in one `DestinationPolicy` record per country, cited and versioned like any other claim.

**Financial proof, verified 2026-08-27.** Four destinations publish a computable threshold; four do
not, and for those the gate discloses rather than estimates.

| Country | Requirement |
|---|---|
| UK | £1,529/month London, £1,171 outside, max 9 months, plus outstanding tuition; held 28 consecutive days. Rates effective for applications on/after 11 Nov 2025 |
| Germany | €992/month → **€11,904** blocked account (verified on Auswärtiges Amt mission pages; the top-level page defers to missions, so the figure is fetched per mission) |
| France | €877.50/month from 1 Aug 2026, up from €615 — **indexed to 47% of gross SMIC**, so it moves on each SMIC revision |
| South Korea | **₩20,000,000** Seoul metropolitan area / **₩16,000,000** regional, held **6 months** (verified on Korean embassy pages, `overseas.mofa.go.kr`) |
| Japan | **No statutory amount.** The Immigration Services Agency requires 経費支弁 evidence and publishes no figure (verified on `moj.go.jp/isa`). The ~¥2m in circulation is university convention |
| China, Turkey, Hungary | No published threshold |

**Post-study work rights, which feed utility rather than risk.** `MOBILITY_FIT` is already a
weighted evaluation dimension with nothing behind it; this is what goes behind it.

| Country | Route | Duration |
|---|---|---|
| UK | Graduate route, unsponsored, no salary floor | 2 years — **18 months for applications on/after 1 Jan 2027** |
| Germany | §20 AufenthG job-seeking permit | 18 months, non-renewable |
| Japan | 特定活動 job-hunting (6+6); **J-Find** for top-100 graduates | 12 months; J-Find up to 2 years |
| South Korea | D-10 job-seeker, points-based | **3 years**, in 1-year increments — raised from 2 years by the Ministry of Justice, press release 2025-10-27 (verified) |
| France | RECE, replacing the APS | 12 months, non-renewable |
| Hungary | Job-seeking permit, Act XC of 2023 | 9 months, non-extendable |
| China | **No national route**; Shanghai and free-trade-zone pilots only | — |
| Turkey | **No dedicated route**; employer-sponsored work permit only | — |

**Commitment payment — a typed field, because "deposit" is a UK-shaped concept.** Germany and
France have no deposit culture at public universities at all; Japan charges a statutory
non-refundable enrolment fee; Korea mandates the *sequence* nationally and leaves the *amount* to
each university.

| Type | Where |
|---|---|
| `TUITION_DEPOSIT` | UK — commonly £2,000–£4,000+, required before the CAS is issued, deducted from the tuition evidenced for the visa |
| `ENROLMENT_FEE` | Japan — 入学金 ¥282,000, MEXT statutory, non-refundable |
| `TUITION_PREPAYMENT` | South Korea — **full first-semester tuition, before the 표준입학허가서 is issued.** National: MOE's 「외국인 유학생 및 어학연수생 표준업무처리요령」 issues the Certificate of Admission only to those who have paid tuition in full. Refundable on visa refusal. **Amount is per university and per college — no national figure**, verify from the institution's 등록금 일람표 before encoding |
| `NONE` | Germany, France public universities — a Semesterbeitrag or CVEC is paid *after* enrolment |
| `PER_INSTITUTION` | China, Turkey, Hungary |

**Visa refusal risk.** Only the UK publishes outcomes by nationality (Home Office Vis_D02 / Vis_04),
so visa risk is a **band** for the UK and a **gate plus disclosure** everywhere else. Turkey
publishes grants but not refusals; Hungary has only Eurostat-level data; Germany, France, Japan and
Korea publish aggregates; China publishes nothing.

**Destination policy is a claim like any other** — it gets a freshness window and a re-fetch
schedule. Two entries in this table are already known to move: France's threshold is SMIC-indexed,
and the UK's Graduate route shortens on 1 January 2027. A cached policy fact that has gone stale
must not decide a student's portfolio.

---

## 6. The legitimacy gate

The destinations where admission is easiest and tuition-driven are also where degree mills live.
Recommending one to a weak student is the worst failure this product can produce, and without this
gate the design would rank it as an excellent floor: bar met, admission rule-based, self-funding
sufficient.

- **Europe:** DEQAR (EQAR's database of external quality-assurance results) covers 4,000+
  institutions across 42 countries and exposes a machine-readable API. It returns HTTP 403 without
  a token, so **free registration is a prerequisite task**, not an open item.
- **Elsewhere (JP/KR/CN):** national registers or a consultant check. No automation this
  increment.
- **Home-country recognition** is separate and often binding — a degree the student's own
  government will not recognise is worthless to a returning graduate, and for a state-scholarship
  holder the recognition list *is* the approved list. This is what R§203 means by
  "degree-portability".

**Automation tiers, from the 2026-08-27 corridor sweep:**

| Tier | Registers |
|---|---|
| Machine-readable now | UK Office for Students register (CSV); France RNCP via `data.gouv.fr`; South Korea 대학알리미 open API on `data.go.kr` |
| Structured but not an accreditation endpoint | Japan e-Stat API — statistical census data, not real-time accreditation status |
| Scrape and cache | Germany (Hochschulkompass, Akkreditierungsrat, anabin), China (`jsj.moe.gov.cn`), Turkey (YÖK/YÖKSİS), Hungary (Oktatási Hivatal FIR) |
| Europe-wide | DEQAR, after registration |

**Recognition back home** runs through the ENIC-NARIC directory of national centres, covering 56
Lisbon Convention countries. Most centres assess **case by case** and issue individual comparability
statements — which means portability is a *disclosure*, not a computable gate, for most home
countries. Four publish actual lists and are worth ingesting: Germany's **anabin** (H+/H−/H+-
status per foreign institution), China's **`jsj.moe.gov.cn`** (10,000+ recognised foreign
universities), Ireland's **QQI** foreign-qualifications database, and Poland's **NAWA
KWALIFIKATOR**.

---

## 7. The optimizer

### 7.1 Bands

Two bands per candidate, because the two questions have different answers and are routinely
inverted (a German public master's: attainable admission, lottery scholarship; Oxford: the reverse).

- `AdmissionBand` ∈ LIKELY / TARGET / REACH / UNKNOWN
- `FundingBand` ∈ AUTOMATIC / LIKELY / TARGET / REACH / NONE / UNKNOWN

Each resolves through a deterministic ladder, first rung with data wins. **The order is
evidence-led, and the research changed it:**

1. **Distance from the published bar**, grades converted by the target's own published rule.
2. **Published selection rate**, where the funder states one directly.
3. **Published counts** — awards ÷ applicants — where both halves exist.
4. **Cited selectivity prose**, quoted, mapped conservatively.
5. **Consultant tier.**
6. **UNKNOWN.**

**The admission-regime flag needs five values, not three** — the corridor sweep found each of these
in the field:

| Regime | Where |
|---|---|
| Rule-based, bar published in advance | UK, Germany (NC-style retrospective cutoffs chiefly affect undergraduate and limited programmes, **not** international master's), Turkey, Hungary |
| Capacity-competitive against published criteria | France — though non-EU applicants resident abroad go through Études en France, not `monmaster.gouv.fr` |
| Exam-gated, per-university | Japan (大学院入試) |
| Holistic review against an institutional international quota | South Korea |
| **Research-student precursor** | Japan again — international applicants are frequently routed through a non-degree 研究生 year to prepare for the entrance exam. The model must be able to say the path to the degree starts somewhere other than the degree |

China is a special case worth stating: internationals are **exempt from 考研** entirely and apply
directly to universities under 自主招生, so the headline national exam does not describe their path.

Rung 1 leads because the corridors mostly do not publish what rungs 2–3 need. DAAD publishes
scholarship *recipients* per country and not applications — a numerator with no denominator.
German NC values are computed *retrospectively*, after applications close, so they are reference
figures and not a bar anyone can be measured against in advance; what *is* published per programme
is the admission-restriction status (`zulassungsfrei` vs `zulassungsbeschränkt`). UK postgraduate
offers are conditions-based by construction. Chevening publishes a selection rate directly ("only
1% of those who apply"), which is why rung 2 exists as its own rung.

**MEXT is the second occupant of rung 2, found by the round-2 corridor research.** It publishes no
applicant counts — rung 3 stays empty for it — but it states its own competitiveness in its own
documents: **over 20倍 for the embassy-mission track** (MEXT self-inspection document,
2026-08-25), roughly 2–3倍 for master's courses (FY2010 business-results report) and a 10倍 policy
target (FY2006). Only the first is current; the other two are dated and are recorded for context,
not for computation. All three are the publisher describing its own selectivity rather than a rate
derived from released counts, which is precisely what rung 2 is for — and each must carry its year
and the label *publisher-stated* wherever it is shown.

This does not disturb the rule below. MEXT is a **funder**, so the rate is a `FundingBand` input;
the `AdmissionBand` position is untouched.

**Cutoffs** (product constants, not science; the underlying figures are always shown alongside):
≥33% LIKELY, 10–33% TARGET, <10% REACH.

**Admission-difficulty data for international applicants is unpublished essentially everywhere**,
which is the corridor sweep's most decisive finding for this ladder. Japan's 倍率, Korea's 경쟁률
and China's 报录比 exist but are university-published, aggregate and usually domestic-only; the UK
publishes no postgraduate acceptance-rate dataset; France publishes capacity but not applicant
ratios. Rungs 2 and 3 therefore fire for **instruments**, not for admission.

**Confirmed for Japan, Korea and China by two independent round-2 runs**, which searched
university-side and returned the same answer: no institution publishes a matched international
applicant/admitted count for master's. Korea University's own Spring 2026 international guide sets
모집인원 to 제한없음, so there is not even a published admit denominator. The three national
statistical systems — e-Stat 学校基本調査, KEDI/대학알리미 and data.go.kr, moe.gov.cn 来华留学统计
— are **enrolment stock series, not admissions-competition series**. That distinction is load-bearing:
they are the wrong *kind* of data rather than data behind an access barrier, so no further
access or licensing work would produce a rate.

**UNKNOWN is common, not exceptional** — most departmental awards, institute stipends and small
foundations publish nothing. Its handling: **shown, spendable, never the floor, never counted as a
reach.** Absence of data is not evidence of selectivity, and a promise of safety needs evidence
behind it.

**Bands are intervals, not point estimates.** We have no calibrated probabilities and will not for
at least an admissions cycle. Each band maps to a probability *interval*. This is a weaker and
defensible claim: the band has to be a correct interval, not a correct number. The literature has
no robust or ordinal version of this problem — this is a documented heuristic filling a known gap,
and the spec labels it as one rather than as a proven optimum.

**How the optimizer consumes an interval is deferred, by decision 2026-08-27.** It belongs to the
odds-prediction design, which is the **last** piece built — after discovery, after the catalog is
populated, and after §10's outcome capture has run long enough to say anything. Until that design
exists, §7.3 is specified against a single probability per candidate and the interval is carried
alongside for display and for §10's calibration record. Nothing may ship to students on the
single-number path, and an interval that has been silently
collapsed to its midpoint is exactly the false precision R§9 forbids. The candidate procedure at
the time of deferral — evaluate the DP at both endpoints and prefer portfolios optimal or
near-optimal at both — is recorded here as a starting point for that design, not as a decision.

### 7.2 Correlation groups

Correlation is what makes safeties optimal, so it is modelled rather than approximated away. There
are **two** structures here, not one list of groups, because the two behave differently and an
earlier draft that treated them alike produced advice nobody would accept.

**A. One decision, applied to all members: the funder.** A funding committee reads one file and
says yes or no. If DAAD refuses, it refuses every DAAD application the student made; a home-origin
instrument decides once for its *whole approved list*. Within a funder group, outcomes are
**comonotone** — one draw, applied to all members.

**B. One shared gate over independent decisions: the destination country.** Three German
programmes decide admission separately — three admissions offices, three files, three decisions —
but Germany issues one visa. So the country is not a group whose members share an outcome; it is a
**multiplier over independent outcomes**:

```
P(a usable outcome at programme j in country c) = P(visa | c) · P(admit | j)
```

`P(visa | c)` comes from §5.1's `DestinationPolicy` — a band for the UK, which publishes refusals
by nationality, and a disclosure everywhere else.

**Institution grouping is withdrawn.** One admissions office running two master's programmes runs
two decisions, and nothing measured says otherwise.

**Why the distinction is load-bearing.** Comonotone means *identical* outcomes, so the second
member of a group adds exactly nothing: applying to a higher- and a lower-utility member of one
group returns the higher one's utility either way, minus a second fee. That is correct for a
funder — a second DAAD application really is worth nothing. Applied to a country or an institution
it says never apply to two programmes in Germany, or two at one university, which is advice no
student would take and no consultant would give. The visa multiplier captures the real shared risk
without that consequence.

`# ponytail: two structures — comonotone for funders, a shared visa multiplier for countries — is
the coarsest model that still gives usable advice; move to a latent-score model only if measured
portfolios show it mattering.`

**Consequence: the diversification quota is withdrawn.** With funder correlation modelled, a second
candidate on the same funder has zero marginal value and the optimizer avoids stacking on its own.
An imposed "at most half the slots per funder" rule would be a second, conflicting mechanism. A
validation case (§11) asserts the optimizer does not stack one funder rather than a constraint
forcing it.

### 7.3 The recursion

Sort candidates by utility descending. Let `t_i` be the candidate's utility, `f_i` its combined
success probability for the route being taken, `g_i` its application cost, and `u₀` the outside
option's utility.

```
V(i, b) = max(
    V(i + 1, b),                                    # skip this candidate
    f_i · t_i + (1 − f_i) · V(i + 1, b − g_i)       # apply, and if rejected continue below
)
V(n + 1, b) = u₀
```

An exact O(n · B) dynamic program over the budget. Three properties fall straight out of it:

- **The outside option is a truncator.** Setting the base case to `u₀` automatically zeroes the
  marginal value of every candidate worth less than the guaranteed option, and pushes the whole
  remaining budget upward into reaches. **This is the mechanism behind "a student who will
  certainly get the state scholarship should reach higher"** — no conditional branching, no special
  case. Ali & Shorrer prove the same shift as a comparative static.

  **`u₀` is the floor's expected value, not its face value** (decided 2026-08-27). The floor is
  LIKELY, not certain, and treating it as certain overstates the safety net by exactly the
  probability it fails. A floor the student would rate 70 and gets with probability 0.8 enters as
  `0.8 · 70 + 0.2 · u_none = 56` where the student has nothing to fall back on — not as 70. With
  a genuinely guaranteed instrument the two coincide and the truncator behaves as described above;
  the correction only bites where the floor is uncertain, which is most of the time.

  Overstating it is not a rounding error in the student's favour. It discards the middle-ranked
  candidates worth 60 or 65 — precisely the ones that carry the student in the one-in-five world
  where the floor falls through — and it does so while telling them they are safe. The
  under-confident direction merely wastes a fee; this direction removes the safety it advertised.
- **The reach/safety mix is derived**, varying with applicant strength exactly as it should.
- **Two-stage admission-then-funding collapses cleanly** where the funder is distinct and the
  student always accepts funding offered:
  `f_i · t_i` becomes `p_admit · [p_fund · u_funded + (1 − p_fund) · u_unfunded]`. That keeps
  `AUTOMATIC_ON_ADMISSION` and `CONSIDERED_WITH_ADMISSION` inside the tractable framework. A shared
  funder re-introduces correlation and is handled by §7.2's grouping.

### 7.4 The floor

One slot, chosen and funded before anything else, and the theory says the optimum contains one
anyway (§3.3). It is an explicit constraint regardless, because it is a product promise and because
`UNKNOWN` must be barred from satisfying it.

- `MANDATORY` funding dependency → the best `FundingBand` among candidates with a verified route.
- Otherwise → the best candidate whose unfunded total cost fits the student's stated self-funding
  capacity **and** whose `AdmissionBand` is LIKELY, falling back to TARGET labelled as a weaker
  floor.
- **A nomination-initiated route can never be the floor.** `INSTITUTION_NOMINATES` and
  `HOME_GOVERNMENT_NOMINATES` both depend on someone other than the student choosing to act, so
  the student cannot cause the outcome. Eiffel, Azerbaijan, Russia and Commonwealth are upside,
  never safety. This is the difference between a promise the product can keep and one it cannot.
- **The floor enters the optimizer as `u₀`, discounted by its own chance.** The floor is chosen
  first, its fee is deducted from the budget, and the DP then runs over the remaining candidates
  with `u₀` set to the floor's *expected* value per §7.3 — never its face value. A floor banded
  TARGET rather than LIKELY therefore truncates less, which is the correct behaviour: a weaker
  safety net should justify fewer long shots above it, not the same number.
- **No floor is not an empty pack.** Every candidate is still shown, ranked and grouped. What
  changes is one sentence: no row is labelled safe, why not, and which of §7.5's widenings would
  produce one. Promoting the least-bad reach into looking like safety is forbidden.

### 7.5 When no floor is found: widen, then report

An ordered, disclosed ladder — not "report and stop":

1. Add destinations with rule-based admission where the student's bar is met.
2. Add tuition-funded options within the student's self-funding capacity.
3. Add the approved lists of every instrument the student holds or intends to apply for.
4. Only then report no floor, naming which widening would have produced one.

This also imposes a **coverage requirement on discovery**: if the catalog holds only competitive,
well-known institutions, a weaker student's pack is structurally empty no matter how good the
optimizer is. Per corridor and field, the catalog must hold rule-based and tuition-funded options
alongside competitive ones. That is a measurable property, tested in §11.

---

## 8. Money and time

### 8.1 Four budgets, not one

`application_budget` models fees only. A student faces four buckets with different amounts, timing
and refundability:

| Bucket | Timing | Refundable |
|---|---|---|
| Application fees | At application | No |
| **Commitment payment** | ≈4–6 weeks after an offer (UK); on enrolment (Japan); none at all in Germany and France | No — except in narrow cases such as a refused visa. See §5.1 for the type per country |
| **Visa financial proof** | Before the visa; held 28 days (UK) or 12 months blocked (DE) | It is the student's own money, but it must be *available* |
| Tuition and living | Per year | — |

The first two are spent to *pursue* outcomes; the third and fourth decide whether an outcome can be
*taken*. A student may be able to afford applying and unable to afford accepting.

### 8.2 Staging: three patterns

Whether waiting for a scholarship decision is possible is a property of the route, not a preference:

| Pattern | Meaning |
|---|---|
| `SCHOLARSHIP_RESOLVES_FIRST` | The decision lands before any programme commitment is due. Waiting is free; hold budget in reserve |
| `REQUIRES_OFFER_BY_DATE` | The scholarship demands an admission offer in hand by a stated date. **Waiting is impossible** — programme applications must be made and paid for first |
| `INDEPENDENT` | Neither constrains the other |

`REQUIRES_OFFER_BY_DATE` is not hypothetical. Chevening's published 2027-28 timeline: applications
close 6 October 2026, results from mid-June 2027, and *"the deadline to receive and submit at least
one unconditional UK university offer is 17:00 BST on 8 July 2027."* The scholarship will not fund a
student who does not already hold an offer.

**South Korea excludes `SCHOLARSHIP_RESOLVES_FIRST` whenever the decision lands after the
university's registration deadline.** The §5.1 `TUITION_PREPAYMENT` rule is what forces it: a
self-funded student pays a full semester's tuition to obtain the Certificate of Admission, and
therefore to obtain the visa at all, so waiting is not free. Typical exposure is ₩6–9m against a
former entrance fee averaging ₩637,000 — an order of magnitude, which is why the pattern flips
rather than merely costing more.

The disclosure is **not** the UK's. Korea's prepayment is recoverable along both published paths: it
is refunded on visa refusal, and a scholarship confirmed after payment is disbursed in cash rather
than kept (SKKU publishes both; a scholarship known *before* billing is simply deducted at source
as 감면고지 and never fronted). So a Korean row states a **cash-flow risk with a refund path**,
where a UK row states forfeiture. Conflating the two would overstate Korean risk and understate
British.

GKS is the benign case and stays `SCHOLARSHIP_RESOLVES_FIRST`: NIIED pays tuition directly to the
university and selection is normally confirmed before enrolment, so the student never fronts it.

### 8.3 The wait/commit pivot is the deposit deadline

Not the application deadline. UK postgraduate deposits are standard, non-refundable, due
**four to six weeks after the offer**, and a precondition for the CAS and therefore the visa. A
student can apply cheaply in January and still be forced to commit £2,000 in March against a June
scholarship result.

The deposit window is relative to an **offer date that is unknown when the pack is built**, so the
catalog holds `deposit_required`, `deposit_amount` and `deposit_window_days`, and the schedule
reasons in relative time — "roughly 4–6 weeks after an offer you may receive in February". Where
the deposit would fall before the scholarship decision, the pack states the amount at risk
explicitly rather than implying a free option.

**The visa is a second pivot, and it can bind earlier than the deposit — a defect found 2026-08-29**
(`research/2026-08-29-synthesis-crosscheck.md` §5). This section reasons from offer to deposit to
start date and never asks how long the visa takes. German student-visa *processing* runs 4–12 weeks
and varies by post — Türkiye min. 4 weeks, Russia 6–8, Ukraine 12–15, India 12 — and the
**appointment queue is a separate, larger delay**, with Mumbai reporting 10–12 weeks for a slot and
one post an 8-month waiting list.

Where a queue runs months, the binding constraint is at **application** time, a year ahead of any
deadline the schedule currently models. A student can be admitted, funded, pay the deposit and still
not arrive before the start date — the worst outcome in the whole model, because every cost has been
paid and no outcome obtained.

**And funding changes the timeline, not only the money.** Several German posts process faster for
students holding a scholarship from a German public institution such as DAAD. So `u_funded` and
`u_unfunded` differ on a second axis beyond affordability: the funded route can be the only one that
arrives in time.

`DestinationPolicy` therefore carries visa processing time and appointment-queue length **per origin
post rather than per destination** — these figures vary by consulate, and a student in Baku faces a
different queue from one in Mumbai. Where the queue plus processing exceeds the time from a
realistic offer date to the start date, the pack says so at pack-build time rather than letting the
student discover it after paying.

**The same record must also carry return-service obligations imposed by the visa rather than by the
funder — found 2026-08-29** (`research/2026-08-29-fulbright-per-country-verification.md` §2). §4
models return service as a `RETURN_SERVICE` term the funder imposes: ADB-JSP, Bolashak and YLSY bind
the graduate because the scheme says so. Fulbright is bound too, but by a different mechanism, and
the Turkish Fulbright Commission draws the distinction itself:

> "Alınan bursun karşılığında herhangi bir **zorunlu hizmet bulunmamakla beraber**, bursiyerin […]
> ABD **J-1 Vizesi kuralı gereği** Türkiye'ye dönme ve iki yıl kalma **zorunluluğu vardır**."
>
> *"While there is **no mandatory service** in return for the scholarship, the scholar is obliged,
> **by rule of the US J-1 visa**, to return to Türkiye and remain two years."*

That is §212(e) of the US Immigration and Nationality Act. It attaches to the **visa class**, so it
binds every J-1-sponsored award and not only Fulbright — and of the nine national competitions
checked, only Georgia and Kyrgyzstan mention it at all. A student reading Azerbaijan's page would
never learn they are accepting a two-year home-residency obligation.

So return service has **two independent sources**, and modelling only the funder's misses the other:

- **Funder-imposed** stays on the route, as §4 has it — it varies by scheme and is quoted from the
  funder.
- **Visa-imposed** belongs here, keyed to the visa class the award routes through, so it is stated
  once per destination-and-class and applies to every award using it, including the schemes whose
  own pages are silent.

A student may be subject to both, to either, or to neither, and the disclosure must not double-count
them: two years' J-1 residency and a two-year funder bond served concurrently are one obligation of
two years, not four. Where a scheme is silent, the visa rule still binds — silence is not absence,
which is exactly why this cannot live only on the route.

Reserved budget is only held back where a viable stage-2 pool exists whose deadlines fall after the
decision date. If the good options close before the scholarship answers, waiting is a wasted cycle
and the pack says to apply in parallel.

---

## 9. Display

**Three orderings, deliberately separate.** Conflating any two is where this goes wrong — today's
`build_pack` walks the ranked list spending the budget top-down, which under a funding-first
ranking buys the lotteries first.

| Ordering | Decides | Rule |
|---|---|---|
| Display | What the student reads | Grouped Reach → Target → Likely, floor flagged |
| Allocation | What the budget buys | §7.3's DP, floor first |
| Payment timing | When each fee is actually paid | Existing `_ordering_for` (`pack.py:99`), unchanged |

Every row shows both bands, its route, the mechanism, the published figures behind the band, and
the citation. Never a personalised percentage — requirements R§9 prohibits promising outcomes, and
the numbers we show are the funder's own.

---

## 10. Recording for calibration

Every band decision is persisted with its inputs, the rung that produced it, and a version stamp.
When outcomes start arriving, band accuracy becomes measurable retroactively without re-running
anything. This is what turns today's uncalibrated intervals into tomorrow's fitted model, and it is
the only reason the §7.1 heuristic is acceptable in the interim.

Outcome capture — (profile, applied-to, result), rejections included — is first-party and
consented, and is the only dataset with the denominator that published statistics lack. It needs a
capture flow the product does not have yet; that flow is a prerequisite for any calibrated
successor, not for this design.

---

## 11. Validation

- **Golden case, weak profile:** a 70-GPA student with a portable state scholarship gets a
  non-empty pack containing a floor, and the floor is on the instrument's approved list.
- **Golden case, strong profile:** a student with a near-certain home instrument gets a portfolio
  weighted toward reaches, and the optimizer produces that without a reach quota.
- **No-floor case:** a student for whom no widening produces a floor gets a full pack, no row
  labelled safe, and a stated reason.
- **Correlation:** the optimizer does not stack applications on one funder, with no diversification
  constraint imposed — **and does not refuse to place two applications in one country**, which is
  the failure the §7.2 rewrite exists to prevent.
- **Budget exhaustion (§2.1):** a student whose budget can buy another worthwhile application gets
  one; a student whose remainder buys only zeros gets the unspent amount, the reason, and the
  widening that would change it. Underspend with no stated reason fails the case.
- **Discounted floor (§7.3, §7.4):** two students with identical candidate sets and identical floor
  utility, one whose floor is LIKELY and one whose floor is TARGET, get different portfolios — the
  weaker floor justifies fewer reaches. A floor entering at face value fails the case.
- **Gate vs band:** a student below a published minimum grade is excluded with a citation, not
  banded as a reach.
- **Catalogue provenance:** no claim supporting any band traces to an aggregator host.
- **Coverage:** for each corridor and field, the catalog contains rule-based and tuition-funded
  options, not only competitive ones.
- **Staging:** a `REQUIRES_OFFER_BY_DATE` route never produces a plan that waits.
- **Deposits:** where a deposit falls due before a scholarship decision, the pack states the amount
  at risk.

---

## 12. Interface to discovery — fields that must be extracted now

Discovery increment 1 is being built. These must enter the extraction contract before the catalog
is populated, or the optimizer forces a re-fetch of every page:

| Field | Why |
|---|---|
| `funding_mechanism` / initiation | Decides whether admission-without-funding is a possible outcome, and whether a route costs a slot (§4) |
| `origin` | Correlation grouping (§7.2) |
| Structured published eligibility criteria | The rung-1 band input and the §5 gate |
| `published_selection_rate` | Rung 2 — published where counts are not |
| Admission regime flag | Rule-based / competitive / exam-gated (§7.1) |
| Full date set | Application deadline, decision date, offer-required-by date (§8.2) |
| `covers_commitment_payment` (yes / partly / no), **per route** | Whether an award settles the deposit or enrolment fee, which decides whether the outcome is takeable at all (§2). Unknown is treated as "no" and disclosed |
| Funder identity | Correlation grouping (§7.2) |
| Track structure | One scheme, many tracks, each with its own initiation, quota and dates (§4.1) |
| Nationality-eligibility rule | Bloc, list, bilateral pair, or quota (§4.2) |
| Per-nationality quota, where published | The preferred denominator for the band ladder (§4.2, §7.1) |
| `DECENTRALISED` date marker | Five of twelve schemes publish no central calendar (§4.3) |
| `satisfies_financial_proof` | Whether an award removes the visa cash gate (§4) |
| Destination policy, per country | Financial proof, post-study work, refusal-data availability, register, commitment-payment norm (§5.1) — a country-level fetch, not a per-programme one |
| Commitment-payment type, amount and window | Typed, because "deposit" does not generalise (§5.1, §8.3). Supersedes the untyped `deposit_required` / `deposit_amount` / `deposit_window_days` an earlier draft listed — one field, not two sets |
| Admission regime, five values | Including Japan's research-student precursor (§7.1) |
| Destination financial-proof amount | The §5 visa gate |
| Accreditation / recognition status | The §6 legitimacy gate |
| **Repayable share of an award, and any service charge** | A half-loan is not coverage (§2). Nil for a grant; AKF ISP repays 50% with a charge. Without it the affordability gap is understated by the repayable half |
| **Guarantor requirement** | A hard gate that is not a number, so it routes to review like the other unquantifiable applicant conditions (§2, §4) |
| **Award cap, where the award is capped rather than full-cost** | Türkiye's Fulbright covers up to USD 60,000/year and the student pays the excess. A capped award recorded as full coverage is wrong precisely at expensive institutions |
| **Visa class the award routes through** | Carries the §212(e)-style return obligation on `DestinationPolicy` (§8.3), which binds even where the scheme page is silent |

## 13. Profile schema additions

`StudentProfileSnapshot` (currently v2) needs, in a new version:

- **Self-funding capacity** — an amount and currency. `application_budget` is the *fee* budget;
  there is no field today for what the student can cover in tuition and living, and §7.4's floor
  depends on it.
- **Held or intended funding instruments** — which portable instrument, and whether held or being
  applied for. `funding_dependency` describes need, not source.

`AffordabilityResult` computes a `gap` and compares it to nothing, because there is nothing to
compare it to. These two fields are what make the gap actionable.

---

## 14. Open items

1. ~~Whether Japan, Korea and China publish admission or award statistics at all.~~
   **CLOSED 2026-08-28 as a confirmed negative**
   (`docs/superpowers/research/2026-08-28-corridor-mechanics-round2-synthesis.md` §2). Two
   independent runs: no university in the three countries publishes a matched international
   applicant/admitted count for master's, and the national statistical systems are enrolment stock
   series rather than admissions-competition series. §7's ladder already assumed this; it is now
   evidenced rather than presumed, and §7 records it.

   What *is* published: **GKS award counts with per-country quotas — 2,000 graduate awards for
   2026** (Embassy 800 / University 1,200), plus final selection lists by candidate number and
   nationality, so per-nationality awards are verifiable after the fact. This is the only
   nationality-resolved scarcity signal in the three corridors, and it is a **numerator with no
   denominator**: NIIED publishes no applicant count and states that pass/fail reasons are not
   disclosed. It must never be rendered as a rate. MEXT and CSC publish recipient/enrolment
   aggregates only (CSC: 63,041 scholarship holders of all international students in 2018, 12.81%,
   from 49,022 in 2016 — a stock, not an annual award count; widely-quoted "30,000–60,000 awards per
   year" third-party figures are unofficial and are not the same quantity).
2. **Corridor set — decided 2026-08-27: Turkey and Hungary are in**, alongside Germany, France,
   Japan, Korea and China. Both enter as *floor-makers*, and the trade-off is stated in the pack,
   never hidden. Türkiye Bursları has a 75% bar, needs no language certificate at application, is
   applied for directly, requires no prior admission letter, and funds tuition, stipend,
   accommodation and flights. **And Turkey has no post-study work route at all** (§5.1), so it ranks
   strongly on affordability and weakly on `MOBILITY_FIT` — exactly the trade-off the two-axis
   design exists to surface. A Turkish row must therefore always display its `MOBILITY_FIT` score
   and the "no post-study work route" fact alongside its funding coverage; a floor that is silent
   about what it costs the student afterwards is a mis-sold floor. Hungary is the same shape,
   milder: a 9-month job-seeking permit under Act XC of 2023.

   Consequences of the decision, none of which block discovery increment 1: neither country has a
   seed catalogue, so both are reached by live search only (blocked on the provider key, §7 open
   item 2 of the discovery design) — `COUNTRY_NAMES` in `apps/research/search.py` gains `TR` and
   `HU` and nothing else changes. Both sit in the §6 legitimacy gate's "scrape and cache" tier
   (YÖK/YÖKSİS, Oktatási Hivatal FIR), so each adds a manual accreditation check until that tier is
   automated. Georgia has no open inbound scheme; Russia is nomination-gated with no central
   calendar and is not recommended.
3. ~~South Korea's commitment payment is unresolved.~~ **CLOSED 2026-08-28**
   (`…-corridor-mechanics-round2-synthesis.md` §1). The two round-1 runs were describing different
   things and both were right: 입학금 *is* being phased out — but 고등교육법 Art. 11(2) excludes
   graduate degree and research programmes from the ban, so it never applied to this population;
   and full first-semester tuition *is* prepaid before the Certificate of Admission.

   **The sequence is a national rule.** Round 1 concluded there was none and inferred a convention
   from five universities' calendars; round 2 found the instrument that convention implements —
   MOE's 「외국인 유학생 및 어학연수생 표준업무처리요령」, under which the 표준입학허가서 is issued
   only to those who have paid tuition in full after acceptance. Round 1 is not overturned, it is
   explained.

   **The encoding decision is unchanged, and its reason inverts.** No national figure is encoded and
   the amount is verified per university from that institution's 등록금 일람표 — not because the
   research conflicts, but because the rule is per-university by construction. A Korean row still
   states that its amount at risk is unknown until its target is verified.

   What *does* change is §8.2: the wait-for-the-scholarship strategy is now known to be unavailable
   in Korea whenever the decision lands after the registration deadline, and the accompanying
   disclosure is a recoverable cash-flow risk rather than the UK's forfeiture. Both are written up
   there.
4. DEQAR registration — a prerequisite task, not a research question.

4a. **Origin markets — decided 2026-08-29. Launch with Azerbaijan and Türkiye**, then expand to
   India, Pakistan, Central Asia, Vietnam and Indonesia. This is market-fit sequencing, not a
   discovery constraint.

   **An origin market is a different axis from a destination corridor, and the specs have only had
   the second.** Item 2's corridor set — Germany, France, Japan, Korea, China, UK, Türkiye,
   Hungary — names where students *go*. This names where they *come from*. Türkiye is now both, and
   that is not a redundancy: it changes what we owe Turkish students.

   Four consequences, none of which change the optimizer:

   - **Türkiye's outbound provision becomes load-bearing and is entirely uncovered.** Every spec
     treats Türkiye as a destination — Türkiye Bursları, the 75% bar, no post-study work route. A
     Turkish student going abroad is a different person with a different instrument set, and
     **YLSY** (the Ministry of National Education's overseas graduate scholarship) is reportedly
     bonded with a substantial return-service obligation. A bonded award is a materially different
     product from an unbonded one and the student must be told which they are accepting.
     `PROMPT-government-outbound-launch.md` Part B covers it.
   - **Recognition rules for AZ and TR become a hard gate rather than a disclosure.** §6 already
     says a degree the student's own government will not recognise is worthless to a returning
     graduate. For two launch markets that stops being a caveat and becomes an admission test, with
     Türkiye's YÖK equivalence regime the specific thing to model.
   - **The nationality-keyed axis is now the primary discovery axis, not a secondary one.** Both
     launch markets sit outside the EU and outside every registry we hold, so schemes keyed to their
     citizens are where the leverage is.
   - **The §7.4 Azerbaijan defect is now a launch-market defect.** It has been parked pending ten
     questions; it now blocks half of phase 1. `PROMPT-government-outbound-launch.md` Part A
     supersedes those questions and should be run before answering them by hand.
5. **Verification status, 2026-08-27.** Verified against primary sources: Germany's €992/€11,904
   (Auswärtiges Amt mission pages), Korea's D-10 three-year cap (Ministry of Justice press release,
   2025-10-27), Korea's ₩20m/₩16m held six months (Korean embassy pages), and Japan's absence of any
   statutory amount (`moj.go.jp/isa`). ~~Unresolved: Korea's commitment payment, item 3.~~ Item 3
   closed 2026-08-28.

   **Still to verify before these findings cite into a student pack** (from the round-2 synthesis §6):
   the MOE directive's own text — round 2's verbatim clauses are footnoted to `okep.moe.go.kr`
   files that are individual universities' 2027 admission notices *quoting* the rule, so the
   directive's existence is well attested but its wording is second-hand, and it should be pulled
   from `moe.go.kr` directly; refund-on-visa-denial at **SNU and KAIST**, confirmed so far only for
   Korea University, SKKU and Yonsei; and the MEXT 20倍 figure against its source PDF, which is a
   self-inspection document rather than a recruitment guideline.
6. Verify the robust-submodular citations (Orlin–Schulz–Udwani 2018; Staib et al. 2019) before
   citing them anywhere load-bearing; and run a forward-citation sweep of Chade & Smith (2006) and
   Kapur & Hong (2022) before treating "no robust version exists" and "no precedence result exists"
   as settled.
7. Kapur & Hong's `OptimalApplication.jl` implements the exact DP and an FPTAS — worth reading
   before re-deriving §7.3's recursion.
