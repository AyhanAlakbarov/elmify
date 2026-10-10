# The admission exam is a location gate, and it binds our own students hardest

**Date:** 2026-08-30. **Origin:** a user question — ADA University requires an exam; can such exams be
taken online? **Method:** four institutions checked at source. **Status:** a finding, not a run.

**Answer: mostly no, and the gate is keyed to nationality in a way that disadvantages the applicant
at home.** Nothing in the catalog or in any prompt records this today.

---

## 1. The gate has three independent parts

"An entrance exam is required" is not one fact. It is three, and each can close a route on its own:

1. **Which exam — keyed to citizenship or residence**, not to the programme.
2. **Where it can be sat** — some are held only inside one country.
3. **Whether an at-home variant is accepted** — several institutions accept a test but refuse its
   remote edition.

## 2. What each institution actually requires

### ADA University (Azerbaijan) — the exam falls on Azerbaijanis, not on internationals

> "Master admission test by State Examination Center (**required for citizens of Azerbaijan and
> holders of Permanent Living Permit in Azerbaijan**)"

International applicants without Azerbaijani permanent residence do **not** sit it. Minimum 45 for
most programmes, 40 for MA Teaching and Learning, 50 for the LL.M.; 2025 or 2026 results accepted for
Fall 2026; registration is separate, at the State Examination Centre.

**And an explicit at-home prohibition, with an exception that matters:**

> "**PTE and iBT tests taken at home are not accepted.** PTE and iBT test results are accepted only if
> they are taken at a registered testing centre."

Yet the accepted list includes the **Duolingo English Test at 120** — which *is* an at-home test. So
the rule is per-test, not a blanket ban on remote examination, and a student told "no at-home tests"
would be misadvised into paying for a test centre they did not need.

Admission ends in an **evaluative interview** — "final decisions are made based on the applicant's
interview results". Whether that interview may be held remotely is **not published**.

### The State Examination Centre's master's exam — Baku area only

Registration is online (`eservices.dim.gov.az`), but the exam itself is sat in person: announcements
state it is held **in Baku, Absheron and Sumgait**. Original documents must be delivered to a regional
DİM centre before the exam. Two sittings per cycle (first attempt February, second May–June). DİM does
run "electronic exams", but that is an electronic format at a centre, not remote invigilation from
abroad.

**No overseas centre was found.** On this evidence an Azerbaijani citizen outside the country cannot
sit it without travelling home.

### Bilkent (Türkiye) — nationality-scoped, and home editions refused

> "**ALES is required from resident Turkish citizens** who are applying for the graduate programs.
> Those applicants who are **not Turkish citizens** … may provide **GRE General Test (obligatory for
> foreign students)** scores instead of ALES."
> "**Home edition test results will not be accepted.**"

ALES is administered in Türkiye; GRE is available at test centres worldwide. So the foreign applicant
has the more portable exam and the Turkish resident has the fixed one.

### Sabancı (Türkiye) — the widest set, including a national alternative

Accepts **ALES, e-ALES, GRE, or GAT (Pakistan NTS)**, valid five years (GAT two). Accepting Pakistan's
national test materially lowers the barrier for one of our phase-2 markets, and **e-ALES** shows the
electronic variant is recognised where the awarding body offers one.

## 3. The finding: the home applicant faces the harder gate

| Applicant | Institution | Exam | Where it can be sat |
|---|---|---|---|
| Azerbaijani citizen | ADA | State Examination Centre master's test | **Baku, Absheron, Sumgait only** |
| Foreign national | ADA | none | — |
| Turkish resident citizen | Bilkent | ALES | **Türkiye** |
| Foreign national | Bilkent | GRE | worldwide test centres |

**This inverts the assumption that studying at home is the low-friction option.** For an Azerbaijani
or Turkish student, their own country's institutions impose a national exam sat in one place, while a
foreigner applying to the same programme takes a portable test or none at all.

Two concrete consequences:

- **The `AUTOMATIC_ON_ADMISSION` floor is not frictionless for the students who most need it.** The
  synthesis called Sabancı, Bilkent, Nazarbayev, Khazar and ADA the first routes that produce a place
  and can be entered unaided. For a Turkish applicant to Bilkent and an Azerbaijani applicant to ADA,
  "unaided" still means a national exam in a fixed location on a fixed date.
- **It compounds with the dual degrees.** Entry to all six A0 programmes runs through the same DİM
  exam, so the location gate applies to that whole floor shape too.

## 4. What the model lacks

`ApplicantCondition` gained `LANGUAGE` and `GUARANTOR` on 2026-08-29. This is a third shape and it is
not either of them:

- **`ENTRANCE_EXAM`** — required, keyed to citizenship or residence rather than to the programme, with
  a named accepted-test set and a minimum score. Partly quantifiable, so unlike `AFFILIATION` it is
  not simply unquantifiable — but the score is meaningless without the test identity beside it.
- **A location attribute the catalog has nowhere to put.** Whether a required test can be sat outside
  the destination country, and whether a remote or at-home edition is accepted, are facts about the
  *test*, not about the scheme or the student. They repeat across every institution accepting that
  test, which argues for a small test registry rather than a per-benefit field — the same shape as
  `DestinationPolicy` for visa classes.

Both are **exclusion conditions on a route the student is otherwise eligible for**, which is exactly
the class the portfolio spec says must not be discovered at application time.

## 5. Open

1. ~~Whether ADA's evaluative interview can be held remotely~~ — **closed by decision, not by
   evidence: treated as in person at master's level. See §6.**
2. **Whether the State Examination Centre offers any overseas sitting** for citizens abroad. Nothing
   found; a confirmed absence needs the Centre's own statement.
3. **Nazarbayev and Khazar** were not checked for exam requirements.
4. **Whether at-home English test acceptance varies inside one institution** — ADA refuses at-home PTE
   and TOEFL while accepting Duolingo, so "accepted tests" and "accepted delivery modes" must be
   recorded separately or the pair will be wrong.

---

## 6. The interview, and the same question asked of all five floor institutions

Checked 2026-08-30, after the note above was filed.

### ADA — online at undergraduate level, unstated at graduate

The undergraduate page states the international route as three steps, and the second is explicit:

> "International applicants must follow three-step application process:
> Step 1: submit ADA University online application and its attachments
> **Step 2: attend an online interview** (only shortlisted candidates are interviewed)
> Step 3: submit Study in Azerbaijan CAS online application"

**The graduate page says only "shortlisted applicants are invited for an evaluative interview"** and
never names the modality — confirmed online for international undergraduates, unstated at master's.

**Working assumption, set by the user on 2026-08-30 and not verified: the master's interview is in
person.** This is a decision, not a source. It is recorded as an assumption so nobody later cites it
as published, and it should be revisited if ADA states otherwise. It is also the safe direction to be
wrong in: assuming in-person and finding it remote costs a student nothing, while the reverse loses
the place at the final step.

Step 3 is worth recording separately: an international applicant to ADA files **two** applications —
ADA's own, and the state's Study in Azerbaijan centralised application at `portal.edu.az`. The second
is easy to miss and is not a scholarship application.

### Khazar — the clearest remote-friendly statement of the five

> "Nationals of other countries can **directly apply to the University from their home countries**."

**Confirmed against the master's requirements list itself, 2026-08-30**
(`international.khazar.org/en/page/master`). The complete set is: bachelor's diploma, transcripts,
statement of purpose, CV, medical examination certificate, passport copy, two reference letters, a
$25 application fee receipt — and:

> "**Optional: Standardized English Language Test Scores (TOEFL/IELTS)**"

**No entrance exam, no interview, and the English test is optional.** That is the most permissive
requirement set of the five by a wide margin, and it is the only one where a language certificate is
not a gate at all.

**On the published evidence Khazar is the only one of the five with no in-person step before an
offer.** Its cycles are dated to the minute in Baku time — Early Bird
09.01.2026 to 01.06.2026, second cycle 02.06 to 31.08.2026 — and **the unfunded price depends on when
you apply**: **$4,500 a year in the Early Bird cycle, $5,000 in the second** (Veterinary Medicine
$5,400 and $6,000). A tuition that moves with the application round is not something a single
`amount` field expresses.

**Two things that are gates even though they are not exams.** A **medical examination certificate** is
required at application — obtainable anywhere, but it needs a doctor and lead time. And after the
offer:

> "…by law, you must get registered as a student via portal.edu.az… The deadline for registering is
> early September 2026, and **those students who miss this deadline will not be able to commence
> their studies**."

That is a way to lose a place *after winning it*, on a state deadline the university does not control.
`ADA` carries the same state registration step. It belongs with the post-award obligations, not with
admission conditions.

**The limit on this finding, now closed — see §9.** The page is the International Affairs Office's and
its requirement set is for international applicants. Azerbaijani citizens go through the State
Examination Centre.

### Nazarbayev — video interviews are published policy

**Answered from the source, 2026-08-30.** The international admission page sets out the process in
four steps, and the third settles it:

> "**Interviews. Shortlisted candidates are invited to a video call or face-to-face interviews** with
> admission committees."

A video call is a named, standard option rather than a concession, so **Nazarbayev is reachable end to
end from home including the interview.** It is the only one of the five where that is published
rather than inferred.

NU also refuses at-home English tests — "IELTS (except Online test) / TOEFL (except Home Edition)" —
making it the **third** institution of the five with that rule, after ADA and Bilkent. The pattern is
now strong enough to assume as a default and check for exceptions, rather than the reverse.

### Nazarbayev — every required test is portable, and there is a waiver path

Master's regular admission asks for a bachelor's degree, CGPA ≥ 2.5/4.0, IELTS or TOEFL, and — school
dependent — ALEKS, GRE or GMAT, with GRE explicitly **optional** for several programmes. All of those
are international tests sat at centres worldwide or online-proctored; **none is a Kazakhstan-only
exam.** There is also an exemption:

> "Applicants with a CGPA of 3.0 or higher from STEM programs of Nazarbayev University, Economics of
> Nazarbayev University, or from **top-200 THE-ranked universities** can apply without taking the
> ALEKS/GRE/GMAT tests."

**And a finding the catalog has no field for: NU keys its deadlines to visa status.** Applicants "from
countries requiring a visa prior to arrival" face an earlier deadline than everyone else — 17 July
against 24 July 2026 for the fee-paying category, 1 June against 15 July for the late round. A
deadline that moves with the applicant's nationality is not something `KeyDateClaim` can express.

### Sabancı — an exam and/or interview, with the modality decided per cycle

> "The prospects meeting the minimum application criteria are called for a **written exam and/or an
> interview**."

And, from a departmental announcement:

> "Candidates invited for interviews will be **notified of the modalities (online/face-to-face)** for
> these interviews."

**Re-checked 2026-08-30 across the graduate announcement pages, and Sabancı is inconsistent with
itself.** The Engineering and Natural Sciences announcement schedules interviews "**at Sabancı
University** during 17th-24th August, 2026 (Interview schedule is subject to change)" — a location,
stated. Its earlier rounds say only that "interviews will be scheduled for potential candidates
during 13 – 27th April, 2026" with no location at all. Psychology says the modality is notified after
shortlisting.

So within one university: one school names the campus, one says nothing, one says it depends and you
will be told. **This cannot be resolved from published sources.**

**Working assumption, set by the user on 2026-08-30 and not verified: treat Sabancı's graduate
interview as in person.** A decision, not a source — recorded as an assumption for the same reason as
ADA's in §6, and defensible on the same grounds: the one school that does state a location states a
campus, and being wrong in this direction costs a student nothing while the reverse loses the place
after the fees and tests are paid for.

**Sabancı is the least predictable of the five for a student who cannot travel**, and that sits
awkwardly beside its being the strongest funding offer.

### Bilkent — interviews are dated and departmental; modality is stated nowhere

Checked across three departments. Every one publishes interview *dates* and none publishes the
*mode*:

- **International Relations** — application deadline 15 May 2026, "Date of Interview: **10 – 11 June
  2026**".
- **Engineering and Science** — "Date of Interview (if invited by the Department/ Program): Regular
  Application **01-03 July 2026**; Late Application **20-21 July 2026**".
- **Electrical and Electronics Engineering** — the same July window.

With an aggravating sentence from the IR department:

> "Invitations for interviews will be sent by June 6 **with short notice, so we ask that you plan
> your schedule accordingly to ensure your availability.**"

A two-day fixed window announced at short notice is a travel problem for anyone outside Ankara **if**
it is in person, and Bilkent never says. So Bilkent is `UNSTATED` like ADA's graduate page, but with a
tighter window and less warning.

**Bilkent also has the strictest test-delivery rules found anywhere in this set**, and they are worth
quoting because they are the model for what "accepted test" has to mean:

> "TOEFL IBT '**Online test taken at home (Home Edition)**' and 'my best score' test results **will
> not be accepted**."
> "IELTS Academic '**OSR (One Skill Retake)**' exam **will not be accepted**."

**ADA accepts the IELTS One Skill Retake. Bilkent refuses it.** Two institutions, the same test, the
same variant, opposite answers — which settles the question of whether accepted-test variants can be
modelled once globally. They cannot; this is a per-institution fact.

And a constraint imposed by the *national regulator* rather than the university:

> "…take the TOEFL IBT exam at one of the test centers in **public universities (YÖK requirement)**."

That is a test-location rule set by Türkiye's higher-education council, binding on the institution.
It belongs with the visa-class rules on a country-level object, not on a benefit.

**One genuinely helpful rule, and the only one of its kind found:**

> "Don't have your exam scores yet? You can still apply… You may be offered **conditional admission**
> based on your existing application materials. All official scores must be submitted by the time of
> registration."

Applying is decoupled from having sat the test. For a student whose test date falls after the
deadline, that is the difference between applying and not.

## 7. What this adds to §4

The modality of an interview or exam is **not a stable institution attribute**, and three observations
say so:

1. **It differs by level inside one institution** — ADA publishes "online interview" for
   international undergraduates and says nothing for master's applicants.
2. **It is sometimes decided per cycle, not as policy** — Sabancı notifies candidates of the modality
   after shortlisting, so no correct value can be stored ahead of a cycle.
3. **Silence is the common case.** Four of the five publish nothing about modality at master's level.

So the recording rule should be `ONLINE` / `IN_PERSON` / `PER_CYCLE` / `UNSTATED`, with **`UNSTATED`
the default and never collapsed into `ONLINE`** — and where an operator resolves an `UNSTATED` by
judgement rather than evidence, as with ADA above, that has to remain visibly an assumption rather
than becoming a published fact by attrition. A student told an interview is remote, who then
cannot attend in Baku or Istanbul, loses the place at the final step — after paying application fees
and sitting the tests.

**Ranked by how far a student can get without travelling, on published evidence only:**

| Institution | In-person step before an offer? |
|---|---|
| Khazar | **None** — no exam, no interview, English test *optional*; apply from your home country. Azerbaijani citizens unverified |
| Nazarbayev | **None — "video call or face-to-face" is published policy**; all tests portable, waiver path for top-200 graduates |
| ADA | **Yes at master's, by assumption** (§6) — online interview published at undergraduate level only |
| Bilkent | **Unstated** — dated two-day interview windows per department, invitations at short notice |
| Sabancı | **Yes, by assumption** — written exam and/or interview; one school states "at Sabancı University", the rest are silent or per-cycle |

## 8. Consequence of the ADA assumption

Taking ADA's master's interview as in person changes the picture for the students this whole line of
work is about.

**An Azerbaijani applying to ADA now faces two in-person steps**: the State Examination Centre
master's test, sat in Baku, Absheron or Sumgait, and the admission interview. A foreign national
applying to the same programme faces one, and no exam.

**And it halves the remote-reachable floor.** Of the five `AUTOMATIC_ON_ADMISSION` institutions, **ADA
and Sabancı are both taken as requiring presence before an offer** (by assumption, §6 and §7),
Bilkent runs dated interview windows without stating the mode, and only **Khazar and Nazarbayev** are
reachable end to end from home — Nazarbayev on an explicit published statement rather than on the
absence of a contrary one.

**Two of the five resolved by decision rather than evidence is worth stating plainly.** Both
assumptions point the same way, both were chosen because that is the safe direction to be wrong in,
and both would be overturned by a single reply from an admissions office. They are recorded so that a
later reader can see the floor narrowed by judgement, not by discovery. Khazar's
award is tuition-only; Nazarbayev's is tuition plus stipend plus insurance.

**So for a student who cannot travel to apply, the floor is Nazarbayev**, with Khazar as the
low-cost-city fallback. That is a much narrower answer than "five institutions offer automatic
funding", and it is the kind of narrowing that only appears once the application mechanics are
modelled alongside the money.

---

## 9. Khazar and the DİM exam — the inversion at its widest

**Checked 2026-08-30. Azerbaijani citizens do go through the State Examination Centre to enter a
master's at Khazar, and the mechanism is national rather than institutional.**

Three pieces of evidence, in descending order of directness:

**1. The DİM master's system covers higher education institutions generally, and places students into
them.** Its e-service portal is headed "2026/2027-ci tədris ili üçün **Azərbaycan Respublikasının ali
təhsil müəssisələrinin magistraturalarına qəbul**" — admission to the master's programmes of *the
higher education institutions of the Republic of Azerbaijan*, not of state institutions only. The
cycle ends with "ixtisas seçimi və yerləşdirmə… müsabiqə nəticəsinə əsasən tələbələr **ixtisas və
universitetlərə yerləşdirilir**" — candidates are **placed into specialities and universities** on the
competition result.

**2. It is explicitly citizens-only, with a separate track for foreigners.** Among the eligibility
conditions: "Azərbaycan Respublikasının vətəndaşı olmaq (**xarici vətəndaşlar üçün ayrıca qaydalar
tətbiq olunur**)" — be a citizen of the Republic of Azerbaijan; *separate rules apply for foreign
citizens*. This is the ADA split stated at national level rather than by one university.

**3. Khazar states it admits on general terms**, and a second private-adjacent institution confirms
the master's case directly. Khazar's own Azerbaijani page: "Xəzər Universitetinə tələbə qəbulu **ümumi
əsaslarla** aparılır" — admission is carried out on general terms, i.e. inside the national system
rather than independently. And UFAZ, the French-Azerbaijani University, states the master's case in as
many words: "UFAZ-ın **magistratura** pilləsinə qəbul olunmaq üçün **Dövlət İmtahan Mərkəzi (DİM)
tərəfindən təşkil olunmuş imtahanlarda iştirak etmək lazımdır**."

**Honest limit:** the Khazar-specific quotation is about school-leavers, so Khazar's participation at
*master's* level rests on the national system's own scope plus "ümumi əsaslarla", not on a Khazar
master's page. Strong, not airtight.

### Why this is the sharpest version of §3

At Khazar the two applicants are no longer merely unequal — they are in different systems.

| | Foreign national | Azerbaijani citizen |
|---|---|---|
| Entrance exam | **None** | **DİM master's test**, Baku / Absheron / Sumgait |
| English certificate | **Optional** | per the national process |
| Interview | None | — |
| Who chooses the university | The applicant | **Central placement on competition result** |
| Route | `DIRECT`, from home | Centrally placed |

**The applicant who lives in Baku faces the harder path into a Baku university than someone applying
from abroad.** Every earlier instance of this pattern was a matter of degree; here the foreign
applicant needs no exam, no interview and no language certificate, while the citizen sits a national
exam and is *placed* rather than choosing.

### The modelling consequence, and it is not a new one

**The same institution has different route values by nationality.** For a foreign applicant Khazar is
`DIRECT` and, with automatic merit consideration, close to `AUTOMATIC_ON_ADMISSION`. For an
Azerbaijani it runs through a central competition that assigns the university — which is much nearer
`NOMINATED` in the only sense that matters to us: **the student cannot simply choose this route and
enter it.**

That is the same conclusion the origin-side synthesis reached about schemes — route belongs to the
*(instrument, nationality)* pair, not to the instrument. Reaching it independently from institutional
admissions, by a completely different mechanism, is worth more than either instance alone. It should
be treated as settled and built in, not rediscovered a third time.

**And a caution for the floor claim.** `2026-08-29-leading-institutions-synthesis.md` §1 lists Khazar
among five institutions offering `AUTOMATIC_ON_ADMISSION` funding "open to our priority nationalities".
For **Azerbaijani** applicants — a launch market — that is not the route they are on. The row needs
splitting by nationality before it is encoded.
