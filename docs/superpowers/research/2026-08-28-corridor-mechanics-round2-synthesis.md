# Corridor mechanics round 2 — East Asian admission data and Korea's prepayment

**Date:** 2026-08-28. **Inputs:** two independent deep-research runs, filed as
`2026-08-28-corridor-mechanics-round2-review-1.md` (better sourced on Korean university practice;
found the post-payment scholarship mechanism) and `-review-2.md` (found the national MOE directive
run 1 missed; found MEXT's own stated selection rates; more current CSC series).

**What it answers:** the two items round 1 left open —
`2026-08-27-corridor-mechanics-synthesis.md` §4 marked Korea's commitment payment **Unresolved**
("must be verified before the money model encodes Korea"), and
`2026-08-27-risk-aware-portfolio-design.md` §14 item 1 asked whether Japan, Korea and China publish
admission or award statistics at all. Both now close. One closes as a rule the runs jointly
establish; the other closes as a confirmed negative.

---

## 1. The finding that changes an encoding decision

**Korea's tuition prepayment is a national rule, not an emergent university practice.** Round 1
could not decide between "입학금 is being phased out" and "full first semester's tuition is prepaid
before the Certificate of Admission" — an order-of-magnitude difference in money at risk. Both are
true, of different things, and run 2 supplies the instrument that settles it:

The MOE directive 「외국인 유학생 및 어학연수생 표준업무처리요령」 (Standard Work Processing
Guidelines for International Students and Language Trainees) states that the 표준입학허가서 —
the Certificate of Admission required for the D-2 visa — *"is issued only to those who have paid the
tuition fee in full after acceptance"* (유학비자 발급신청에 필요한 표준입학허가서는 합격 후
등록금을 완납한 자에게만 발급되며).

Run 1 concluded there was **no** national rule and that the requirement emerged from Ministry of
Justice document requirements plus each university's registration calendar. That was the right
reading of the evidence run 1 had — it observed the sequence at five universities and inferred a
convention. Run 2 found the directive the convention implements. The five-university observation is
not overturned; it is explained.

**What is national and what is not:**

| | Status |
|---|---|
| The *sequence* — full tuition paid, then COA issued, then visa | **National.** MOE directive, uniform across SNU, Yonsei, Korea, KAIST, SKKU in both runs |
| The *amount* | **Per university and per college.** No national figure exists. Both runs agree |
| Refund on visa denial | **Published, per university.** Confirmed at Korea University and SKKU (run 1, verbatim); Yonsei 100% before first course registration, SKKU prorated after commencement per Article 28 (run 2) |

**Round 1's encoding decision survives unchanged, with its confidence raised.** The portfolio spec
§14 item 3 already says *"No national figure is encoded"* and requires per-university verification
before any Korean row claims a commitment amount. That is still correct — but the reason changes.
It was "we do not know which run is right." It is now "the rule is known and it is per-university by
construction."

**The product consequence is in §8.2, not §5.1.** A self-funded student admitted to a Korean
university commits a full semester's tuition — typically ₩6–9m against a former entrance fee
averaging ₩637,000 (run 1) — before the visa document exists. So the
`SCHOLARSHIP_RESOLVES_FIRST` branch is **unavailable in Korea whenever the scholarship decision
lands after the university's registration deadline**. Waiting is not free there. Run 1 states the
decision rule directly: scholarship known before billing is deducted at source (감면고지) and the
student never fronts the money; scholarship confirmed after payment goes through the university's
cash-disbursement process. That is a **cash-flow risk, not a loss** — which is a materially
different pack disclosure from the deposit-forfeiture risk the UK carries.

GKS itself is the benign case: NIIED pays tuition directly to the university and selection is
normally confirmed before enrolment, so GKS scholars register against an already-covered bill.

---

## 2. The negative that is the real result

**No university in Japan, South Korea or China publishes a matched international applicant/admitted
count for master's programmes.** Both runs searched independently and both returned the same
answer, run 1 naming SNU, Yonsei, Korea, KAIST and SKKU explicitly. Korea University's own Spring
2026 international guide sets 모집인원 to 제한없음 — there is not even a published admit
denominator.

This is now a **confirmed negative rather than an unsearched gap**, which is what portfolio §14 item
1 was waiting for. The spec's existing position — *"Admission-difficulty data for international
applicants is unpublished essentially everywhere"* — is corroborated by a second independent run
and needs no change.

The three national statistical systems (e-Stat 学校基本調査, KEDI/대학알리미 and data.go.kr,
moe.gov.cn 来华留学统计) are **enrolment stock series, not admissions-competition series**. Both
runs make this distinction unprompted. They are the wrong *kind* of data, not missing data — which
matters, because it means no amount of further access work produces a rate.

---

## 3. Where the runs conflict

| Fact | Run 1 | Run 2 | Position taken |
|---|---|---|---|
| **National prepayment rule** | None; emerges from MOJ document rules + university calendars | MOE directive 「외국인 유학생 및 어학연수생 표준업무처리요령」, quoted | **Run 2**, on the rule's existence. Run 1's five-university observation stands as its implementation. See §1 |
| **MEXT selection rates** | Not published — "no applicant count; no rate" | MEXT states rates in its own documents: **>20倍** embassy-mission track (2026 PDF), ~2–3倍 master's courses, 10倍 policy goal | **Run 2.** Run 1 looked for computable counts and correctly found none; run 2 found publisher-*stated* rates, which is a different thing and a lower ladder rung. Vintage is the catch — see below |
| **CSC figures** | 2014: 36,943 scholarship holders of 377,054 (9.80%) | 2018: **63,041** (12.81%), from 49,022 in 2016 | **Run 2**, on currency. No conflict of substance — both are enrolment stock with no applicant denominator. Run 1's warning still binds: third-party "30,000–60,000 awards per year" estimates are unofficial and are *not* the same quantity as run 2's enrolled stock |
| **입학금 in practice for graduates** | Legally chargeable, but many universities folded the residual cost into first-semester tuition — SKKU 2022 tuition-committee minutes cited | Legally chargeable, and internationals "will still routinely encounter a mandatory entrance fee alongside their tuition bill" | **Run 1.** Both agree on the law (graduate programmes are excluded from the Art. 11(2) ban). On practice run 1 has a dated primary document and run 2 asserts without one. Encode no separate entrance-fee figure |
| **Post-payment scholarship treatment** | Published at SKKU: 감면고지 if before billing, 현금지급/계좌입금 if after | "**Not published** in any provided source" | **Run 1.** A sourced positive beats an unsourced negative. Scope it to SKKU — it is not a national rule, and both runs agree the *late-GKS* reimbursement case is genuinely unpublished |

**On the MEXT rates, a caution that decides how they can be used.** The three figures are of mixed
vintage and mixed scope: the 20倍 embassy-track figure is from a MEXT self-inspection PDF dated
2026-08-25 and is current; the 2–3倍 master's figure comes from an FY2010 business-results report;
the 10倍 figure is an FY2006 policy target. Only the first is usable as a present-day statement, and
all three are the publisher describing its own competitiveness rather than a rate computed from
released counts.

That places them at **rung 2** of the portfolio spec's evidence ladder ("published selection rate,
where the funder states one directly") — the rung Chevening already occupies — and *not* rung 3
("published counts — awards ÷ applicants"), because no counts exist. It does not disturb the spec's
statement that "rungs 2 and 3 fire for **instruments**, not for admission": MEXT is a funder, so
this is a `FundingBand` input, and the `AdmissionBand` position is untouched.

---

## 4. What both runs agree on

- **GKS 2026: 2,000 graduate awards**, published with per-country quotas, no applicant count and no
  경쟁률. The guideline states reasons for pass/fail are not disclosed. Run 1 has the fuller track
  split (Embassy 800 / University 1,200, with sub-splits); run 2 adds that final selection lists are
  published by candidate number and nationality, so per-nationality award counts are verifiable
  after the fact.
- GKS is the only one of the three funders yielding a **nationality-resolved scarcity signal** — and
  it is still a numerator with no denominator. It must be labelled as such and never presented as a
  rate.
- MEXT and CSC publish recipient/enrolment aggregates only.
- Full first-semester tuition, paid before the COA, refundable on visa refusal.
- 입학금 abolished for undergraduate entry from the 2023 academic year under 고등교육법 Art. 11(2);
  graduate degree and research programmes explicitly excluded from the ban.

---

## 5. Design consequences

1. **`2026-08-27-risk-aware-portfolio-design.md` §14 item 1 closes** — confirmed negative, second
   independent run. No spec change beyond marking it resolved.
2. **§14 item 3 closes**, and §5.1's `TUITION_PREPAYMENT` row moves from *"claimed by one research
   run, contradicted by the other; unresolved"* to *"national MOE directive; amount per university."*
   The no-national-figure encoding is unchanged.
3. **§5.1's line "Korea's practice is unresolved and per-university"** is now half wrong: the
   practice is resolved, only the amount is per-university.
4. **§8.2 gains a Korea exclusion.** `SCHOLARSHIP_RESOLVES_FIRST` cannot be selected for a Korean
   target when the scholarship decision falls after the registration deadline, because the full
   semester's tuition is committed to obtain the visa document. The pack states a cash-flow risk
   with a refund path, not a forfeiture.
5. **MEXT gains a rung-2 instrument rate** — embassy-mission track, >20倍, MEXT self-inspection
   document dated 2026-08-25 — with the year attached and labelled publisher-stated.
6. No change to the `AdmissionBand` ladder. Rung 1 still leads for these corridors.

---

## 6. Must be verified before encoding

- **The MOE directive itself.** Run 2's two verbatim clauses are footnoted to `okep.moe.go.kr`
  downloads that are individual universities' 2027 admission notices quoting the rule, not the
  directive text. The directive's existence is well attested; the wording is second-hand. Pull the
  directive from `moe.go.kr` before citing it as primary evidence in a pack.
- **Refund on visa denial at SNU and KAIST.** Confirmed from their own pages only for Korea
  University and SKKU (run 1) and Yonsei (run 2). Run 1 flags this gap itself.
- **Per-university tuition amounts**, from each institution's 등록금 일람표, before any Korean row
  claims a commitment figure.
- **The MEXT 2026 figure**, against the source PDF, before it enters a `FundingBand` computation —
  it is three days old at time of filing and comes from a self-inspection document rather than a
  recruitment guideline.
