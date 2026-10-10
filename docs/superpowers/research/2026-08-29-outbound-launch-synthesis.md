# Outbound state provision, Azerbaijan and Türkiye — synthesis across two runs

**Date:** 2026-08-29. **Inputs:** two independent runs of `PROMPT-government-outbound-launch.md`,
filed as `2026-08-29-outbound-launch-review-1.md` (run A, the structured one) and `-review-2.md`
(run B, the essay), adjudicated against `2026-08-29-outbound-launch-prerun-recon.md`.

**What it answers:** what Azerbaijan and Türkiye pay for their own citizens to study abroad, on what
terms, and whether either instrument can serve as a portfolio floor.

---

## 1. Both programmes are live, and both are bonded. That is the product.

Neither is suspended. Azerbaijan's State Programme ran a 2025/2026 intake (10 April – 15 June 2025,
1,147 applicants) and **its 2026/2027 university and programme list was approved on 12 January
2026** — verified directly at `dp.edu.az/az/news/4963`, which upgrades the recon's lead to a fact.
Türkiye's YLSY is open, branded "1416 Bursları", with 811 places for 2025 against 668 for 2024, and
an application window that opened 19 December 2025.

**The decisive fact for a student is the bond, not the money.**

| | Azerbaijan State Programme | Türkiye YLSY |
|---|---|---|
| Service | **5 years** working in Azerbaijan | **Twice the funded period**, to a named institution |
| Secured by | Employment contract; all costs repayable on breach | Notarised undertaking **plus two joint-and-several guarantors** |
| On default | Repayment of all costs incurred | Repayment **with interest**, pursued against the guarantors |

Run A's framing is the right one: these are bonded public-service contracts, not grants. A two-year
funded master's under YLSY implies roughly **four years** of compulsory service to a named employer.

**This produces the first real `GUARANTOR` instance in the catalog** — the condition type added to
`BenefitRule` earlier today. YLSY requires *müteselsil kefil*, two persons acceptable to the ministry,
at the point of acceptance. It is not a number and no profile field decides it, which is exactly why
it routes to review.

## 2. The recon's six checks, scored

Written before the runs, so these test coverage rather than hindsight.

| # | Check | Run A | Run B |
|---|---|---|---|
| 1 | Finds the "no admission is carried out" clause | **Yes, quoted** | Partial — states the offer requirement, never quotes the clause |
| 2 | Reaches and quotes the return-service provision | **Yes**, Cabinet decision, financing condition | Yes, but quotes a *selection-criterion* fragment, not the financing condition |
| 3 | Names SOFAZ as funder | Yes | Yes |
| 4 | Labels the 500 as a ceiling | Muddled — treats 500 as quota *and* as a realised cohort | **Yes** — separates "hüququ qazanıb" (awarded) from "məzunu olub" (graduated) explicitly |
| 5 | Keeps HTP / DP / Heydar Aliyev apart | Yes | **Yes, explicitly** ("operates entirely distinctly from the HTP framework") |
| 6 | Notices the competitiveness-programme name discrepancy | **Yes, and explains it** — DPİQ was created under the separate 2019–2023 higher-education-competitiveness programme | No |

**Neither run drew the consequence of check 1**, which is the recon's surviving contribution: an
instrument that funds only an admission the student already holds **cannot be a portfolio floor or a
safety**, because it produces no place. Run A has the fact and files it as an application detail. The
prompt was written believing the inbound/outbound conflation was what barred Azerbaijan from being a
floor; the conflation is real, and correcting it still does not make this a floor.

**Neither run reports SOFAZ's financial series** — AZN 92.729m allocated for 2026 at 13.2% execution
by H1, with a cumulative disbursement history. Both name SOFAZ and stop. That series is the likeliest
public source of per-cycle award counts.

## 3. Where the runs contradict each other

### 3.1 YLSY's route — run A says `NOMINATED`, run B says `DIRECT`. Run B is right.

This is the load-bearing column and they disagree flatly. Run A reasons that ÖSYM/ALES exam plus oral
exam plus placement to a named institution makes it state-selected. Run B reasons that any citizen
clearing ALES 75 can enter REBUS unaided.

**`NOMINATED` in our taxonomy means the student cannot initiate — a university, ministry, club or
partner must put them forward.** A competitive open exam is not that. YLSY is `DIRECT` with a hard
selection, the same shape as GKS's University Track. Run A has conflated "the state chooses among
applicants" with "the state must nominate you", which would wrongly bar YLSY from ever being a floor.

The nuance worth encoding: entry is `DIRECT`, but **placement binds the destination** — the student is
assigned a sponsoring institution before securing foreign admission, and cannot change it afterwards.
That is a constraint on the award, not on the route.

### 3.2 Co-holding with a destination scholarship — run A is honest, run B over-reaches

Run A: not clearly published for either scheme, confirm with the administering body. Run B: asserts
Türkiye "ruthlessly enforces" exclusivity and Azerbaijan permits "synergy".

**Run B's evidence for the Turkish claim is a TÜBİTAK *domestic* guideline** — from a programme run B
itself ruled out of scope two sections earlier. Inferring YLSY's rule from a different programme's
document is precisely the error the ADB-JSP round was called out for. Its Azerbaijani claim ("the
state simply does not process the tuition invoice and continues the stipend") is an inference, not a
quotation.

**Take run A.** Unpublished, and it stays unpublished until someone asks.

### 3.3 Which Cabinet decision — 217 or 218

Run A cites decision **No. 218 of 1 June 2022** for both the coverage rules and the return obligation.
Run B cites **217** (`e-qanun.az/framework/49751`). Most likely two acts adopted the same day — a
selection *Qayda* and a financing rule — in which case both runs are right about different documents
and each has attributed a quote to the wrong one. **Both say five years, so the finding is safe and
the citation is not.** Resolve before quoting either number in a student-facing document.

### 3.4 2022–2026 or 2022–2028

Run A dates the extension to decree No. 248 of 12 August 2024 and quotes the FAQ as "2022-2026". Run B
uses 2022–2028 throughout while citing pages titled "2019-2023/2022-2026". **Directly retrieved today,
`dp.edu.az` navigation and the 12 January 2026 announcement both read "2022–2028".** The site is
mid-rename and stale strings survive in places; run A's quotation is one of them.

## 4. Run B's approved-university list is wrong, and it is the dangerous kind of wrong

Run B presents a table headed "the precise, exhaustive list of approved foreign universities and their
corresponding eligible master's programs for the 2026/2027 cycle" — twenty institutions, almost
entirely **architecture, urban design and landscape**, plus a handful of natural-science entries.

Run A reports the 2025/2026 list as **221 institutions in 32 countries and 4,405 programmes**.

These are not two accounts of the same object. Run B has almost certainly captured **one field's
table** — architecture and design, one of the fifteen priority fields it lists elsewhere in its own
report — and presented it as the entire list. Its own priority-field table contradicts its university
table.

**Encoded as published, this tells an economics or IT applicant they are ineligible for a programme
that funds them.** It is the single most damaging error across all four runs filed today, precisely
because the table looks authoritative and complete. **Do not use run B's university table.** Take run
A's shape (221 / 32 / 4,405) and fetch the real list from the 12 January 2026 announcement.

## 5. What each run found alone, and is worth keeping

**Run A only:**
- **A fourth confusable instrument.** Beyond outbound DP, inbound Heydar Aliyev grant and HTP, there
  is a *domestic* "Heydər Əliyev adına təqaüd" (decree of 24 June 2023) — a one-off 3,000 AZN award to
  100 Azerbaijani bachelor students. Same name, same year, unrelated. Four instruments, one name.
- The quota composition rule: from 2025, no more than 25% bachelor's and no more than 20% doctoral,
  leaving 55%+ master's. That makes the 500 ceiling **majority master's**, which matters for us.
- **YÖK** sends research assistants abroad for master's and doctoral study under Law 2547 arts. 33/35,
  each on behalf of a named university — a real outbound route, restricted to university staff.
- Türkiye's interest-on-default provision: Law 1416 art. 21 as amended by Law 7326 (9 June 2021).

**Run B only:**
- **TCMB — the Central Bank of Türkiye funds its own employees' master's abroad** (9 scholarship
  holders and 2 on unpaid leave in 2025). This is the enumeration payoff the prompt asked for: a body
  neither the prompt, the recon, nor run A named. It is `EMPLOYER_ONLY`, not a public route, but it is
  a real instrument and it suggests other state institutions run staff schemes.
- **AYK** (Atatürk Yüksek Kurumu) — domestic master's, outbound post-doctoral only. A clean confirmed
  absence.
- The per-country monthly stipend norms across ~49 jurisdictions. **Corroborated by run A on the two
  figures it independently reports** — USD 1,800 general USA, GBP 1,500 London — which is the only
  cross-run check available on that table, and it passes.
- Türkiye's post-return machinery: a three-month duty to report, a half-stipend holding allowance
  while unplaced, and transfer of the obligation to any state department that takes the graduate.

**Both, corroborated:** TÜBİTAK funds **no** outbound master's — its 2210 suite is domestic and 2213
is doctoral-only. A useful negative result, independently reached twice, and worth recording because
the opposite is widely assumed.

## 6. What this changes for the model

1. **A new instrument shape: coverage conditional on an admission obtained outside the scheme.** The
   Azerbaijani programme is not a route to a place and cannot be a floor. Nothing in the catalog
   expresses "funds a place you already hold".
2. **`GUARANTOR` has its first real instance** (YLSY's *müteselsil kefil*), and so does severe
   `RETURN_SERVICE`: 5 years for Azerbaijan, 2× funded period for Türkiye. Both are repayment-enforced,
   and Türkiye's compounds interest from the date of breach.
3. **Return service now has three distinct sources**, all confirmed this week: the funder (ADB-JSP,
   Bolashak, YLSY), the destination's visa class (J-1 / INA §212(e)), and the origin state binding a
   graduate on another state's money (Kazakhstan's intergovernmental grants). The Azerbaijani and
   Turkish cases are the first source, at the most severe end.
4. **`DIRECT` with a binding placement is a shape we do not model.** YLSY entry is open; the sponsoring
   institution is assigned before the student holds any foreign offer, and cannot be changed. Route and
   destination constraint are separate facts.
5. **An approved-university list is a hard constraint on what we may recommend**, republished per
   cycle. Azerbaijan's exists and is large; ours must be able to say "funded only at these
   institutions this cycle" or it will recommend unfundable places.

## 7. Still open

1. ~~Cabinet decision 217 vs 218~~ — **closed, §8.3.**
2. ~~The real 2026/2027 approved-university list~~ — **closed, §8.1.**
3. ~~The UCL claim~~ — **closed, §8.1. Run B was right.**
4. ~~Co-holding with a destination scholarship~~ — **closed for both countries, §8.2.**
   is behind JS or in a PDF. **Unverified, not disproven.**
4. **Whether either award may be held alongside a destination scholarship.** Both runs agree it is
   unpublished; run B's contrary assertion rests on the wrong document. This needs a phone call, and
   it is the kind of question a counsellor will be asked immediately.
5. **YLSY's master's-versus-doctoral split per cycle.** The headline figures (811 for 2025, 668 for
   2024) combine both levels, and the kılavuz publishes institution-level quotas rather than a level
   total.
6. **How funded language months count toward YLSY's service obligation.** Run A says one-for-one for
   domestic language time; run B implies they fall inside the 2× multiplier. The difference is months
   of a person's life.

---

## 8. The two chased items, closed 2026-08-29

### 8.1 The approved list — run B was out by an order of magnitude, and right about UCL

From the Ministry's own announcement (`dp.edu.az/az/news/4963`, 12 January 2026):

> "Təsdiq olunmuş yeni siyahıya əsasən, namizədlərə **15 prioritet ixtisas istiqaməti** üzrə dünyanın
> **33 ölkəsini** təmsil edən **231 nüfuzlu ali təhsil ocağında** tədris olunan ümumilikdə **4121
> proqram** üzrə təhsil almaq imkanı yaradılıb."

**231 institutions, 33 countries, 4,121 programmes** for 2026/2027 — against run A's 221/32/4,405 for
the prior cycle, which is the right shape, and run B's twenty.

The list PDF itself (50 pages) carries **2,928 master's rows**, 1,235 bachelor's and 3 doctoral,
spanning data science, statistics, ecology, molecular sciences, biotechnology, materials and
mechanical engineering. **Run B captured the architecture-and-design section, which sorts first, and
labelled it the whole list.** Diagnosis confirmed; do not use that table.

Two rules from the same PDF that a counsellor needs:

- **Qeyd 2 — the top-10 exception, and run B's UCL claim, verbatim and correct:**
  > "…yalnız 'universitetlər üzrə top 10'da yer almış ali təhsil müəssisələri tərəfindən təqdim
  > olunan, siyahıda yer almayan istənilən ixtisas sahəsi üzrə … proqramlara qəbul almış şəxslər
  > Dövlət Proqramına müraciət edə bilərlər. **Ötən illərdə University College London (UCL) üzrə
  > göndərilən namizədlərin sayını nəzərə alaraq bu yanaşma 2026/2027-ci tədris ilində UCL üçün
  > tətbiq olunmayacaq** və yalnız siyahıda olan proqramlar üzrə müraciətlər…"
  > — "…only those admitted to programmes in any field not on the list, offered by institutions in the
  > 'top 10 by university', may apply. **Taking into account the number of candidates sent to
  > University College London in past years, this approach will not be applied to UCL for 2026/2027**,
  > and only applications for programmes on the list…"

  The synthesis filed this as unverified. It is now verified, and **run B found something run A did
  not.** A run that is wrong about a table can still be right about a note.

- **Qeyd 4** excludes executive, distance and non-degree formats, and joint degrees whose partner is
  not on the list.

The announcement also re-confirms the annual quota at **500**, and adds that per-field passing scores
may be applied depending on application volume.

### 8.2 Co-holding a destination scholarship — permitted in both, and Türkiye has a name for it

**Türkiye settles it outright.** The 1416 scholarship-holder handbook defines a status for exactly
this case:

> "**Kısmi Resmî Burslu Öğrenci:** Resmî burslu statüde öğrenim görmekte iken, **karşılıksız burs ya
> da asistanlık ücreti alan**; ancak aldığı burs veya ücret, yaşam … ve öğrenim giderlerini … tamamen
> karşılamadığı için Bakanlık ya da öğrenim görülen kurum/kuruluş tarafından **kısmen desteklenen**
> öğrencidir."
> — "**Partially State-Funded Student:** a student who, while holding official scholarship status,
> **receives a non-repayable scholarship or an assistantship salary**, but whose scholarship or salary
> does not fully cover living and study costs, and who is therefore **partly supported** by the
> Ministry or the sponsoring institution."

**Holding another award is not merely allowed — it is a defined status, and the state becomes a
top-up funder.** This refutes run B's claim that Türkiye "ruthlessly enforces" exclusivity, which it
inferred from a TÜBİTAK *domestic* guideline it had itself ruled out of scope. Run A's "not clearly
published, confirm directly" was the honest answer; the answer turned out to be published, in the
handbook rather than the kılavuz.

**Azerbaijan carries no exclusivity clause.** The binding instrument — the two-party contract form
approved by minister's order F-436 of 07.07.2022, linked from `dp.edu.az/az/content/76` — contains no
prohibition on other scholarships, grants or fee waivers, and the ministry pays tuition only against
an invoice presented to the foreign institution (§3.1.2). A waiver therefore reduces state outlay
rather than disqualifying the student. Note the disclosure duties that do apply: §3.3.19 requires
notifying the Ministry within 10 days of anything affecting the obligations, and §3.3.16 requires
answering ministry queries within 10 days.

**The contract also yields the return obligation in its operative form** (§3.3.18):

> "tədris müddəti bitdikdən sonra ən geci **2 (iki) ay** ərzində Azərbaycan Respublikasına qayıtmaq,
> qayıtdıqdan sonra 10 (on) təqvim günü müddətində Nazirliyə bu barədə məlumat vermək və Azərbaycan
> Respublikasında **5 (beş) il (öhdəlik müddəti)** əmək fəaliyyəti göstərmək"
> — "return to the Republic of Azerbaijan no later than **2 (two) months** after the study period
> ends, notify the Ministry within 10 calendar days of returning, and carry out employment activity
> in the Republic of Azerbaijan for **5 (five) years** (the obligation period)."

And the repayment triggers, §6.2.1–6.2.7, each requiring **repayment of all costs within two months**
of the triggering event. **§6.2.1 is the one to tell a student about:**

> "təhsilini **səbəbindən asılı olmayaraq** xaricdə davam etdirə bilmədikdə"
> — "where they are unable to continue their studies abroad, **irrespective of the reason**."

**That produces a sharp asymmetry between the two bonds, and it runs opposite to their apparent
severity.** Türkiye's handbook forgives medical withdrawal outright — where the Ministry finds a
student cannot continue on health grounds, "Tahsil masrafları geri talep edilmez, Mecburi hizmet
yükümlülüğü doğmaz" (costs are not reclaimed, no compulsory service arises). Azerbaijan's §6.2.1 has
no such carve-out and is drafted to exclude one. Türkiye's bond is longer and guarantor-backed;
Azerbaijan's is less forgiving of misfortune.

### 8.3 Cabinet decision 217 vs 218 — both runs were half right

The contract cites both, which settles it. **Decision 218 of 1 June 2022** approves the *financing*
Qayda (contract §2, and §1.4 of that Qayda is the contract's legal basis). **Decision 217 of the same
date** approves the *selection criteria and procedures* (contract §3.2.3). Run A attributed the
return obligation to 218 and run B to 217; the obligation sits in the contract made under 218, so run
A's citation is the usable one.

### 8.4 Two corrections and an operational note

- **Run B's YLSY application window is wrong.** It gives 19 December 2025 – 9 January 2026. The
  ministry's own announcement says applications ran **19–30 December 2025**, closing 17:00 on the
  30th. Run A's "opened 19 December 2025" is right.
- **`yyegm.meb.gov.tr` is fetchable** — flat HTML with linked PDFs — despite `abdigm.meb.gov.tr` at
  the same ministry being robots-blocked. The pre-run warning was worth issuing and turned out not to
  bind.
- `mevzuat.gov.tr` failed on an SSL chain error from this machine; the ministry's own PDFs made it
  unnecessary.
