# An institution-safety screen that actually verifies — synthesis across two runs

**Adjudicated 2026-08-31.** Runs: `2026-08-31-open-admission-review-1.md` (A, Claude deep research)
and `-review-2.md` (B, Gemini deep research), both against
`PROMPT-open-admission-safe-institutions.md`. No pre-run recon existed for this brief, so the
adjudication rests on re-verification rather than on a control — every contested fact below was
re-checked against a primary or regulator source on 2026-08-31, and two were re-checked *because the
first reading of them was wrong*.

**The runs are not of comparable quality, and it is not a clean split.** Run A obeys the sourcing
rules, honours the capacity rule, and declines to pad Part B. Run B is largely built on agent and
aggregator sites, fabricates a verbatim quote, and estimates an acceptance rate the brief forbids —
and yet it holds two findings run A missed entirely, one of which invalidates run B's own
recommendation. Preferring A wholesale would have discarded the most consequential fact either run
produced.

---

## 1. The headline answer is a negative, and both runs reach it

**Neither launch market publishes a positive list of recognised foreign institutions.** The brief
named this as the finding that would change plans. It has not changed them.

- **Azerbaijan.** Recognition (*nostrification*) runs through the Agency for Quality Assurance in
  Education (TKTA) under Cabinet of Ministers Decision No. 64 of 13.05.2003, via the
  `nostrifikasiya.edu.az` e-service. It is **case by case, per application, and resolved only after
  graduation.** No list exists to pre-clear an institution against.
- **Türkiye.** YÖK operates an e-Devlet *query* (`turkiye.gov.tr/yok-okul-tanima-belgesi-sorgulama`),
  a published **blacklist** of non-recognised institutions, and a **ranking-based** equivalence rule.
  A query is not a list: it answers one institution at a time and cannot be enumerated or cached.

The operational consequence is the same for both: **recognition cannot be pre-computed for our
primary population.** For an Azerbaijani student it cannot be computed at all before enrolment. Any
product surface that implies otherwise is asserting something no public source supports.

Run A states this plainly. Run B reaches the same place for Türkiye but muddies Azerbaijan by
routing it through a Georgian-citizen bilateral scenario (its §3.3) rather than answering the
question asked.

## 2. The list-publishing set: the derivation returned a negative, and that is the result

The brief demanded the set be *derived* from the ENIC-NARIC directory, with Germany, China, Ireland
and Poland treated as a floor rather than the scope. Run A performed the derivation and found
**nothing beyond them**. ENIC-NARIC's own guidance explains why: the network's standard method is to
check the *awarding* country's register and then assess comparability case by case, so most centres
have no reason to publish a foreign-institution list at all.

**Germany's anabin remains the only true accreditation-plus-recognition gate found.** It rates the
foreign *institution* (H+ / H− / H+/−) and the *degree* separately, and recognition requires the
combination — which is exactly the two-part structure a computable gate needs. Its own caveat matters
and must be carried into any implementation: anabin "does not claim to be complete," so **absence is
not non-recognition**, and ZAB then issues an individual Statement of Comparability.

China's MOE list (`jsj.moe.gov.cn`, ~10,000 institutions across 44 countries) is a genuine second,
with the same asymmetry: MOE calls it "a reference list for the public," so presence is not a
guarantee and absence is not a refusal.

**Neither run found a fifth.** That is a real finding, not a gap: build for anabin, and treat every
other market as case-by-case until one of them starts publishing.

## 3. Where the runs contradict, and which is usable

### 3a. UK Basic Compliance Assessment thresholds — **both runs are partly right, and run A is stale**

This is the correction that most changes the adjudication.

| | refusal | enrolment | completion |
|---|---|---|---|
| Run A (quoting GOV.UK via the Bloomsbury case) | <10% | ≥90% | ≥85% |
| Run B (via `academicjobs.com`) | <5% | ≥95% | 90% |

Re-checked 2026-08-31: **the thresholds were tightened on 1 June 2026.** Times Higher Education and
The PIE both report the new BCA requiring enrolment "at least 95 per cent (up from 90 per cent)", and
`migrantimes` states the refusal rate moved "below 5%, down from below 10%." So **run B has the
current standard and run A has the superseded one** — run A's figures remain correct for the
Bloomsbury assessment itself, which predates the change, but are wrong as today's rule.

**Run B got the right answer from a source the brief forbids; run A got a stale answer from a source
it permits.** Neither is straightforwardly usable, which is the point: sourcing discipline is
necessary but not sufficient, and a well-sourced fact still needs a date.

The completion threshold **is now resolved against GOV.UK directly — see §9a. It is 85% today and
90% from 1 June 2027**, so the secondary sources were not in conflict; they were quoting two
different eras of the same rule, and neither dated it. Run A's completion figure is the one in force.

### 3b. RWTH Aachen's admission bar — run B quotes an agent site's invention

Run B presents *"MINIMUM 70% OR ABOVE required"* and *"TOEFL iBT with at least 90 points" / "IELTS
6.5"* as **verbatim** admission bars, cited to `studyabroadupdates.com`. Run A independently records
that RWTH's official programme page **states no numeric cutoff**, deferring to a central language
page, and flags the absence rather than filling it.

Sourcing rule 2 asks for the published bar quoted. Run B satisfied the *form* of the rule while
violating its purpose: a quotation whose provenance is an agent site is worse than no quotation,
because it will be trusted. **Treat run B's Part B admission bars as unsourced.**

### 3c. Pakistan and India — run B's "list-based" framing is wrong in the way that matters

Run B classes Pakistan's HEC as a "rigid list-based" system. HEC does publish a list of recognised
**Pakistani** universities, and a list of foreign universities for its own **scholarship** scheme —
neither is a recognition list for foreign degrees. HEC issues **equivalence letters case by case**
via `eservices.hec.gov.pk`, which is what run A says.

The distinction is the entire subject of the brief. A domestic accreditation register and a foreign
recognition list are different objects, and conflating them is the failure mode the run existed to
prevent.

Run B's India material is better and is corroborated: the **UGC (Recognition and Grant of Equivalence
to Qualifications obtained from Foreign Educational Institutions) Regulations, 2025** moved
equivalence from AIU to UGC, via `equivalence.ugc.ac.in`, decided case by case by a standing
committee. Both runs agree.

## 4. What run B found that run A missed — and one of them is decisive

**Georgia's national QA body is not currently on EQAR.** Run B reports the suspension; re-checked on
2026-08-31 it is **more serious than run B stated**:

- EQAR's own agency record reads: *"NCEQE is currently not registered on EQAR, but was registered
  from 01/04/2019 until 30/04/2024."*
- DEQAR hosts the decision document `A146_NCEQE_Rejection_decision_v1.pdf` — a renewal application
  **rejected**, not merely lapsed.
- The ground was **independence**, per ENQA's finding of non-compliance with that ESG standard, over
  gaps dating to 2023. Georgia subsequently passed a law increasing NCEQE's independence and
  governing appointment and dismissal.
- A restoration decision was still pending as of July 2026. NCEQE remains a full ENQA member; ENQA
  allows two years to remedy.
- NCEQE's own position (Acting Director Margishvili, December 2024) is that the suspension "is not
  related to the recognition of qualifications for diplomas issued in Georgia."

**This is the most consequential fact either run produced, and run A does not contain it.** It means
the European QA screen — DEQAR, the one machine-readable mechanism in Part A — **does not currently
cover Georgian institutions**, because the agency that would upload their reports is off the
register. Georgia is a screen blind spot right now, not merely a case-by-case recognition market.

Run B's three further contributions, all requiring primary re-sourcing before use:

- **Canada excludes public-private-partnership / curriculum-licensing programmes from the PGWP.**
  If confirmed on canada.ca, this is a whole provider *category* that passes accreditation and fails
  post-study work — precisely the "safe-looking floor that is not" the brief asked to be flagged.
- **UGC 2025 explicitly bans franchise-arrangement degrees**, which would make UK validation-only
  delivery providers unusable for Indian students.
- **YÖK's 2025 rules reject fully online degrees and cap blended delivery at 30% online**, with YKS
  rank floors for regulated professions.

## 5. Run B's recommendation is refuted by run B's own finding

Run B lists **Caucasus International University** (Tbilisi, private, medical-focused) as "Passed with
Caveats," sourced to `pactors.io` and the institution's own membership page — an agent site plus a
self-assertion, which sourcing rule 1 forbids twice over.

It does this **in the same document** in which it reports that Georgia's NCEQE is suspended from
EQAR. If the national QA body's registration has been rejected on independence grounds, an
institution accredited by that body cannot be cleared *by that accreditation*. Run B found the fact
and did not apply it to its own table.

**Nothing in Georgia should be surfaced as screened until NCEQE's EQAR position is restored.** That
is a Part D entry, not a Part B row.

## 6. Sourcing scorecard

| | Run A | Run B |
|---|---|---|
| Regulator/primary sources for safety claims | mostly; names its secondary sources and says to upgrade them | **largely agent, aggregator and consultancy sites** |
| Verbatim admission bars | quoted where published; **absence flagged as absence** | **one fabricated via an agent site** |
| Acceptance rates | not published → not stated | **estimated (10–15%), which the brief forbids** |
| Dating | statuses dated, staleness called out | thin; the BCA change is undated |
| Capacity rule | honoured explicitly; Part B kept short and said why | Part B padded relative to screen depth |
| Costs | tuition separated from visa minimum, with year and currency | mixed; INR conversions from an agent site |

Run A's Part B is three institutions and says the search budget ran out before Poland, Kazakhstan and
the Caucasus could be sourced to primary depth — *"not listed rather than listed on weak sourcing."*
That sentence is the difference between the two runs.

## 7. What this changes

1. **Build the screen against anabin and DEQAR; treat every other market as a consultant check.**
   The derivation found no fifth list-publisher. This is settled until a regulator changes it.
   **Refined by `2026-08-31-safety-screen-register-recon.md` §1: both are computable. anabin serves a
   public unauthenticated JSON API — one request per market, ~33 for the whole corpus — so the only
   open question is its Impressum's bar on storing content in a database, which is an ownership
   decision rather than an engineering one.**
2. **Azerbaijan cannot be gated.** State in-product that recognition resolves only on post-graduation
   application to TKTA. Never imply a list-clear where none exists.
3. **Türkiye can be gated *partially*, by ranking band**, using the YÖK query at the year of
   enrolment — top-400 and top-1000 bands behave as rules; below that is individual assessment.
4. **Georgia is a blind spot, not a market.** NCEQE off EQAR removes the machine-readable QA leg for
   Georgian institutions entirely. **Corrected by the register recon §2a: DEQAR still lists 83
   Georgian institutions, 60 of them with reports, but 1,247 of 1,274 report rows are NCEQE's. It is
   a filter — clear only on a report from an agency currently on EQAR — not a blackout.**
5. **Germany's tuition-free public sector is the floor**, and it is the only sector both runs
   independently reach: €0 tuition, ~€300–340 semester contribution, and a blocked-account visa
   minimum of **€11,904/year (€992/month) for 2026** per Make it in Germany. Both runs cite the same
   figure, which is the strongest agreement in the pair.
6. **Screen post-study-work separately from accreditation.** The UK Graduate Route's track-record
   requirement and Canada's PGWP category exclusions both disqualify institutions that pass every
   academic gate.

## 8. Still open

- ~~The BCA completion threshold~~, ~~RWTH's published admission bar~~ and ~~Canada's PGWP PPP
  exclusion~~ — **all three read against their primary sources on 2026-08-31; see §9.**
- ~~**Norway after 1 August 2026**~~ — **closed negatively in
  `2026-08-31-three-remaining-gaps.md` §3: studyinnorway.no states non-EEA degree students "must
  normally pay tuition fees". Norway is not a second free floor; Germany stands alone.**
- ~~**Indonesia's *penyetaraan ijazah*, and the CRICOS / DLI / ILEP / NZQA registers**~~ — **all
  closed except Ireland. DLI in §9d; CRICOS and NZQA in `2026-08-31-destination-registers-recon.md`;
  Indonesia's QA leg in `2026-08-31-screen-coverage-measurement.md` §5 (78 screenable institutions,
  96% coverage), its recognition leg still open. Ireland's ILEP is being retired for TrustEd Ireland
  at the end of 2026 and must not be built against.**
- ~~**No pre-run recon existed for this brief.**~~ **Closed by
  `2026-08-31-screen-coverage-measurement.md`: the screen returns 5,027 institutions across 131
  countries and Germany is 9% of them, so the convergence was the brief's affordability framing, not
  the mechanism. That measurement also found Russia is a second Georgia, that per-country coverage
  runs from 98% to 6% so a negative result is not comparable across countries, and that DEQAR cannot
  see the US, Canada, Australia or New Zealand at all.**

---

## 9. Verified against primary sources after filing — 2026-08-31

Three of §8's open items were read directly. Two of the three change what §3 concluded about *which
run was right*; none changes what §7 says to build.

### 9a. The BCA thresholds, from GOV.UK itself

`gov.uk/government/publications/student-sponsor-guidance/student-sponsor-compliance-accessible`,
Student Sponsor Guidance Document 3, ¶2.14 — three dated tiers, not two:

| assessment made | refusal | enrolment | completion |
|---|---|---|---|
| before 1 June 2026 | <10% | ≥90% | ≥85% |
| on/after 1 June 2026 | **<5%** | **≥95%** | **≥85%** |
| on/after 1 June 2027 | <5% | ≥95% | **≥90%** |

¶2.88, verbatim: *"The new course completion rate of 90% will come into effect for Basic Compliance
Assessments made on or after 1 June 2027. As such, course completion rate will not form part of the
sponsor's first RAG rating under this guidance. During the period from 1 June 2026 to 31 May 2027,
sponsors must meet the course completion rate of at least 85% and failure to meet this threshold will
result in the appropriate compliance action."*

**The adjudication in §3a was half wrong.** Run A is stale on refusal and enrolment, as §3a said —
but its 85% completion is the rule in force, and run B's 90% is a rule that does not yet apply. The
two secondary sources never disagreed; each quoted a different tier and neither dated it. **Encode
85% with an expiry of 2027-05-31, not a single number.**

### 9b. RWTH publishes numeric *language* bars centrally, and no academic bar at all

Run B's *"MINIMUM 70% OR ABOVE"* has no counterpart in any RWTH source. The official international
master page states the opposite of a threshold: ranking is by average grade converted to the NRW
1.0–4.0 scale, competitively, with no minimum. Run A was right to record an absence.

Run B's *"IELTS 6.5"* matches nothing RWTH publishes. The real bars live in the ÜPO, tabulated in
`rwth-aachen.de/global/show_document.asp?id=aaaaaaaaabpixuo` per programme, in two tiers:

- **§3 Abs. 9 ÜPO** — *"TOEFL … (IBT) with a result of at least 90 points"*, *"IELTS test with a
  score of at least 6.0"*, PTE ≥60, Cambridge B2 First grade B, UNIcert II, CEFR B2.
- **§3 Abs. 10 ÜPO** — *"at least 100 points"*, *"IELTS … at least 7.0"*, PTE ≥70, C1 Advanced,
  UNIcert III.

So run B's TOEFL 90 is coincidentally the §3(9) figure and its IELTS 6.5 is invented — which is the
worse outcome than being wrong twice, because half-right numbers survive review.

**The screen's lesson is structural, not about RWTH.** A German programme page can state no bar and
still be governed by one; the bar is in the examination regulation and is keyed per programme by
paragraph reference. A screen that reads programme pages alone will record "no published bar" for
institutions that publish a strict one.

### 9c. Canada's PGWP curriculum-licensing exclusion — confirmed, but grandfathered by start date

`canada.ca/…/study-canada/work/after-graduation/eligibility.html` (page updated 2026-06-24) states
it in both directions. Under who's not eligible: programmes *"delivered on behalf of a PGWP-eligible
DLI through a curriculum licensing agreement (also known as public private partnerships, or P3s)"*.
Under special cases: *"These programs are not PGWP-eligible in most cases"*, with two dated
exceptions — same-province agreements begun **on or before 15 May 2024**, and cross-province
agreements begun **on or before 31 January 2023**. Anything begun after those dates: *"not
eligible"*.

Run B's category is real. Its framing as categorical is not: the exclusion is by programme start
date, so the screen needs the cohort's start date, not just the provider. For our population — all
starting in the future — it is categorical in effect.

**One correction to §7.6 while the page was open:** bachelor's, master's and doctoral graduates have
**no field-of-study requirement**; that requirement binds college, polytechnic and non-university
programmes and other university programmes. What does bind degree graduates is language — CLB/NCLC 7
in all four skills for applications from 1 November 2024. That is a gate on the *student*, not the
institution, and the screen cannot clear it.

### 9d. The destination-side registers — Canada's DLI list and the UK sponsor register

Raised as a question about Canada and the UK after filing: do they publish recognition lists? **No,
and that is not the interesting answer.** They publish the two best-instrumented registers in the
whole screen, on the leg neither run treated as machine-readable.

**Both are negatives on leg A3.** CICIC, Canada's ENIC-NARIC centre, maintains no list of recognised
foreign institutions; it routes to six assessment services and then to provincial regulators or the
employer, warning that assessments *"do not guarantee recognition of your qualifications for:
admission at an educational institution; certification, licensing, or registration in an occupation;
and/or general employment."* UK ENIC is **Ecctis**, a commercial per-assessment service operating a
Band Framework, with no public institution list. So the §2 derivation stands: still no fifth
publisher.

**But on legs A1/A2/A4 they are the strongest sources found.**

- **Canada's DLI list** (`canada.ca/…/designated-learning-institutions-list.html`, page updated
  2026-08-28) is browsable per province and carries a per-institution **"Offers PGWP-eligible
  programs"** column, plus a separate list of **public DLIs offering PAL/TAL-exempt graduate
  programmes** at master's and doctoral level for applications after 1 January 2026. It fuses two
  facts accreditation cannot answer — may this provider host international students, and will its
  graduates qualify for post-study work — in one government table. Given §9c, **this is the register
  that resolves the P3 exclusion at provider level**, which is what §7.6 asked for and did not have.
- **The UK's Register of Licensed Student Sponsors** is published as a **CSV, updated nearly every
  business day**, carrying each sponsor's licensed student category *and its sponsorship rating*.
  That is leg A4 — the risk that a properly accredited institution loses its licence mid-degree — in
  the most consumable form any authority publishes. Degree-awarding powers (leg A2) sit separately
  in the OfS register and the Recognised/Listed Bodies split, and the Listed Bodies half remains
  unpublished per run A's Part D.

**The screen therefore has four machine-readable registers, on two different legs**: anabin and
China's MoE gate the *home* side (does the student's country recognise this degree), the DLI list
and the sponsor register gate the *destination* side (may this provider enrol them, and will the
qualification carry work rights). Neither pair substitutes for the other, and the earlier framing —
"anabin is the only computable gate" — was true only of the home side. Part D item 6 is closed for
DLI; CRICOS, ILEP and NZQA are not, and should be expected to resemble the DLI list rather than
anabin.

**A caution the DLI list shares with anabin.** Presence answers a narrower question than it appears
to. A DLI flagged as offering PGWP-eligible programmes is not a promise that *the student's*
programme is one — canada.ca states it plainly: *"Not all programs offered by a DLI are eligible for
a PGWP."* Same asymmetry as anabin's incompleteness: the register clears a provider, never a
qualification.

### Still open after this pass

Norway's post-August-2026 fee position, Indonesia's *penyetaraan ijazah*, the CRICOS/ILEP/NZQA
registers, and the missing pre-run recon — all as §8 states.
