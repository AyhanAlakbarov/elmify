# Gap-fill §9 open items — primary-source verification pass

**Date:** 2026-08-29. **Method:** direct fetch of the funder's own page or PDF. No search snippet is
load-bearing here; where a search was used it only located a URL, per the 2026-08-21 observation that
the summary layer conflates sources.

Closes three of the six items left open by `2026-08-29-nationality-keyed-synthesis.md` §9. Three
remain, listed at the end with why they resisted this method.

---

## 1. IsDB M.Sc. / LDMC status — CLOSED. None of the nine qualify.

**Source:** `isdb.org/sites/default/files/media/documents/2025-02/Sch-Bklets_EN_ISDB-ISFD_WEB_Revised.pdf`,
page 11, "LIST OF ELIGIBLE LDMCs". Retrieved and parsed 2026-08-29.

> Afghanistan, Bangladesh, Benin, Burkina Faso, Chad, Comoros, Djibouti, Gambia, Guinea,
> Guinea Bissau, Mali, Mauritania, Mozambique, Niger, Senegal, Sierra Leone, Somalia, Sudan,
> Togo, Uganda, Yemen

**Twenty-one countries. Not one of our nine appears** — not Azerbaijan, Türkiye, Kazakhstan,
Kyrgyzstan, Tajikistan, Turkmenistan or Uzbekistan, all of which are IsDB *member* countries, and not
Armenia or Georgia, which are not.

This is the membership-versus-eligibility error the ADB-JSP case already taught, appearing again in a
different scheme: **IsDB membership does not imply LDMC status, and the M.Sc. track keys on the
latter.** Run 1's presentation of IsDB as "a parallel full-cost route" for Turkish citizens does not
survive it.

**Discrepancy worth noting:** `isdb.org/scholarships` says the M.Sc. programme was launched "realizing
that **20** of the Least Developed Member Countries could not benefit" from the Merit programme. The
booklet lists **21**. Neither number is load-bearing for our answer — our countries are absent either
way — but do not encode "20" as a count.

**Also established:** the IsDB-ISFD LDMC scheme carries an age cap of 24 ("Maximum age of 24 years at
the closing date of applications"), and studies are normally in the student's own country, with
placement abroad only "for students who are unable to secure admission in their own countries", and
then only in Malaysia, Morocco or Türkiye.

## 2. Aga Khan Foundation ISP — CLOSED, and it is half a loan

**Source:** `the.akdn/en/what-we-do/developing-human-capacity/education/international-scholarships`.
Note the path: every URL ending `international-scholarship-programme` serves a page titled "OLD
International Scholarship Programme" containing unrelated Afghanistan cultural content. That is a
broken CMS entry, not a retired programme, and it is why a prior run could not characterise this.

**Two of our nine are eligible: the Kyrgyz Republic and Tajikistan.**

> "the AKF ISP is available in Afghanistan, Australia, Bangladesh, Egypt, India, Kenya, the Kyrgyz
> Republic, Madagascar, Mozambique, New Zealand, Pakistan, Syria, Tajikistan, Tanzania and Uganda."

**The award conditions are the finding, not the eligibility.** Verbatim:

> "AKF ISP awards are structured as **half grant and half loan** – where you need to repay 50 percent
> of the award amount. […] A **guarantor is required to co-sign** the award agreement. Repayment of
> the loan component, which **includes a service charge**, begins six months after the first of the
> following events: a) graduation, b) termination of studies or c) the withdrawal of support."

Further conditions: priority to master's; **must be entering the first year** (already-enrolled
students are ineligible); an explicit "resource of last resort" framing requiring a demonstrated
multi-source funding plan; **preference — not a cap — for under-30s**; and a destination exclusion:
**not available for study in the United Kingdom or Russia**.

**This is a spec defect, in the same class as the work-during-study finding.** `FundingBenefit` has no
concept of repayable funding. An AKF ISP award recorded as coverage would tell a student a place is
funded when half of it is debt carrying a service charge and requiring a guarantor — a person who may
not exist for the student we serve. A half-loan and a grant are not the same product, and the
affordability test cannot treat them alike. See §4.

**Bonus, and only a tip-off:** the same page publishes a curated list of ~48 other funders (Chevening,
DAAD, Eiffel, Fulbright, Rhodes, MMEG, Mastercard Foundation Scholars, JADS, ADB, World Bank,
Commonwealth, and Prodigy and Mpower as loan programmes). Aggregator rules apply — a discovery seed,
never evidence.

## 3. Chevening per-country allocation — CLOSED as "not published", with two conditions found

**Source:** `chevening.org/resource-hub/guidance/eligibility/` and
`chevening.org/scholarships/who-can-apply/`.

**No per-country allocation or quota is published on either page.** The application form's country
selector does carry **"South Caucasus"** as an entry alongside Armenia, Azerbaijan and Georgia
individually, which is evidence of *award-scheme* structure at regional level — consistent with run
1's Chevening-TEV finding for Türkiye — but a scheme grouping is not a quota. Recorded as a confirmed
non-publication rather than an absence of structure.

**What the page does establish, and it is load-bearing for `APPLICANT_CONDITION`:**

> "**Commit to returning to your home country (country of award) for at least two years** after your
> scholarship ends."

> "Have **at least two years' work experience**, acquired after completing your undergraduate degree,
> **equivalent to 2,800 hours**."

Chevening is therefore a **bonded award with a 24-month return-service obligation** and a
**post-undergraduate work-experience bar**. Both are exactly what the 2026-08-29 model additions hold,
and Chevening is among the most-recommended schemes in the corridor set — so this is not an edge case.

Note the unit: the bar is stated in **hours (2,800)** as well as years. A duration-only comparable
loses that, and 2,800 hours is not 24 months of any particular working pattern.

Further conditions on the same page, unmodelled: no prior UK-government-funded study; not resident in
the UK at application; an unconditional offer from one of three eligible UK courses by the deadline;
and an employment-relationship exclusion covering immediate relatives of staff.

---

## 4. What this changes

1. **A repayable award is not coverage.** `FundingBenefit` needs to distinguish grant from loan, and
   an affordability test that nets a half-loan against cost overstates what the student has. The
   guarantor requirement is a second, harder gate: it is not a number, and for our population it may
   be the binding constraint. Related to the `u_unfunded` defect recorded in the 2026-08-29
   cross-check.
2. **`comparable_value` may need an hours unit**, or Chevening's 2,800 hours must be converted at
   encode time with the conversion recorded. Converting silently is the grade-conversion mistake in a
   different costume.
3. **Confirmed absences, stop re-checking:** IsDB M.Sc./LDMC for all nine; AKF ISP for all but the
   Kyrgyz Republic and Tajikistan; AKF ISP for the UK and Russia as destinations.

## 5. Still open after this pass

- **GKS per-country quota** — needs the NIIED annual guideline PDF itself. The prior probe found
  `studyinkorea.go.kr` browser-required and partly 404, so this needs the browser path or a direct
  PDF URL, not a plain GET. **Do not encode the compiled figures until it is read.**
- **The 1a membership enumeration's per-claim sourcing** — irreducibly ~9 countries × dozens of
  bodies. A verification pass, not a fetch; budget it as its own run.
- **Fulbright per-country terms** — nine national commissions, each with its own site and cycle. Same
  shape: a run, not a lookup.
