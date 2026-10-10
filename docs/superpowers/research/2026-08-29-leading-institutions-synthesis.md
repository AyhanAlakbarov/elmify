# Funded master's places outside the high-income core — synthesis across two runs

**Date:** 2026-08-29. **Inputs:** two independent runs of
`PROMPT-leading-institutions-outside-high-income.md`, filed as
`2026-08-29-leading-institutions-review-1.md` (run A) and `-review-2.md` (run B), adjudicated against
`2026-08-29-dual-degree-prerun-recon.md`.

**What it answers:** whether a student from Azerbaijan or Türkiye has any funded master's route they
can enter unaided — the floor question the outbound round left open.

---

## 1. The answer is yes, and it has a name

**`AUTOMATIC_ON_ADMISSION` is real and both runs found it.** An admitted international applicant is
considered for funding with no separate competition at **Sabancı** and **Bilkent** (Türkiye),
**Nazarbayev** (Kazakhstan), **Khazar** and **ADA** (Azerbaijan) — all English-taught.

**Corrected 2026-08-30: "open to our priority nationalities" is wrong for the host country's own
citizens, and that includes a launch market.** The route differs by nationality at the same
institution:

| Institution | Foreign applicant | Host-country citizen |
|---|---|---|
| Khazar (AZ) | `DIRECT`, no exam, no interview, English test **optional**, automatic merit consideration | **State Examination Centre master's test, then central placement into speciality and university** |
| ADA (AZ) | `DIRECT`, online interview at UG level | **SEC test required**, plus interview |
| Bilkent (TR) | GRE, sat worldwide | **ALES**, sat in Türkiye |

**For an Azerbaijani applying to Khazar or ADA, this is not an automatic route they can simply
enter** — they sit a national exam in the Baku area, and at Khazar they are *placed* rather than
choosing. Evidence and the national mechanism:
`2026-08-30-admission-exam-location-gate.md` §9.

The general rule, reached independently here and in the origin-side round: **route belongs to the
(instrument, nationality) pair, not to the instrument.** Any row asserting a route without naming the
nationality it holds for is unencodable.

That is the first instrument class this programme has found that **produces a place and can be
entered unaided**. The outbound round established that neither launch market's state scheme can be a
floor: Azerbaijan's funds only an admission you already hold, Türkiye's binds you for twice the funded
period behind guarantors. The origin-side round established that most foreign schemes reaching these
students are `NOMINATED`. This is the gap closing.

Run A's operative quotes, which are the encodable part:

> Sabancı: "All international applicants who meet the application requirements are **automatically
> considered** for a scholarship."
> Khazar: "You do **not need to make separate applications** for this, each applicant is
> automatically considered."
> ADA: "Graduate Assistantship is awarded to the top applicants at the time of admissions… **does not
> require a separate application**."
> Nazarbayev: "**No separate scholarship application is required**: all qualified international
> applicants are considered by default during NU admissions."

**Run A's best contribution is turning that into a detection rule.** The phrases "automatically
considered", "no separate application" and "considered by default" reliably mark the highest-value
awards **regardless of URL path**. That is directly implementable and worth more than any single row.

## 2. The recon's five checks, scored

| # | Check | Run A | Run B |
|---|---|---|---|
| 1 | Establishes the 2-bachelor's / 4-master's split | **No** — does not treat the dual degrees as a category at all | **Yes, exactly right**, with a full table |
| 2 | Finds the BP sentence rather than assuming state funding | No | **Found BP — and then inverted what it means.** See §3.1 |
| 3 | Notices the stale 01.04.2023 intake date | No | No |
| 4 | Keeps the competitiveness programme separate from the outbound one | Not engaged | **Partly** — names the right programme, then attributes its funding to SOFAZ, which funds the *outbound* one |
| 5 | Finds an equivalent outside Azerbaijan | No | **No — but expands the Azerbaijani set materially.** See §3.2 |

**Run B owns Part A0 entirely; run A did not attempt it.** Run A's only mention of the dual degrees is
as a *standing* signal for ADA in Part D.

## 3. The two findings that matter most from Part A0

### 3.1 Run B found BP and then over-claimed the funding

Run B: "The Azerbaijani government, occasionally augmented by corporate sponsors such as BP, **assumes
the comprehensive financial burden** of both the domestic and international partner tuition fees,
**rendering the programmes free** for successful candidates", and in its table, ADNSU–Warwick is
"**Completely free of charge**".

**The page does not say that.** `dp.edu.az/az/content/55` says only:

> "Proqram iştirakçılarının **bəzi xərcləri** BP və onun tərəfdaşları tərəfindən maliyyələşdiriləcəkdir."
> — "**Some** of the participants' costs will be financed by BP and its partners."

And the financing rule (Cabinet decision 450) funds design, steering-committee and local-faculty
costs — the *programme*, not the student. **"Fully funded" is not established for any of the six**,
and run B asserts it for all of them without a coverage quote for any.

**This is the most consequential error in either run**, because it is the difference between a floor
and a discount. A student told a dual degree is free, who then meets partner tuition, has been
misadvised on the single fact that decides whether the option is takeable.

Run B's structural detail is nonetheless good and appears nowhere else: the spatial split and visa
consequence per programme — ADPU–GWU entirely in Azerbaijan (no visa needed at all), ADA–GWU three
semesters home and two in the US, BDU–HUJI one semester in Israel, ADNSU–Warwick four semesters home
plus a six-week UK summer session. **A degree with two semesters abroad and no visa risk for the rest
is a genuinely different product**, and worth carrying — with the funding claim struck.

Both runs corroborate the recon on the route: **DİM national entrance examination, then joint
selection by the two institutions.** Entry is by open exam, not nomination.

### 3.2 Run B expanded the set — but not outside Azerbaijan

New and useful:
- **A presidential order to expand from six to eight** dual-degree programmes.
- **UNEC × Kyrgyz National University** — a dual master's in Finance and Management, formalised late
  2025, active for the 2026 cycle, one year at the partner. A South Caucasus–Central Asia route.
- **Azerbaijan University × University of Tuscia (Italy)** — private, two years, three semesters home
  and one in Italy, taught in English and Italian.
- Azerbaijan University × Kharkiv National University of Radio Electronics, which run B itself flags
  as operationally contingent.

**But every one of these has an Azerbaijani home institution.** Check 5 asked whether Türkiye,
Georgia, Kazakhstan, Uzbekistan, India or Pakistan fund equivalents, and **neither run answered it.**
The prompt states a route found outside Azerbaijan is worth more than all six; that remains unclaimed.

## 4. Where the runs contradict each other

### 4.1 The URL ratio is inverted between them, and run A's is the usable one

Run A: **~45% funding-shaped / 55% embedded.** Run B: **55% dedicated / 45% embedded.** They also
place the same institutions in opposite buckets — run B files Sabancı and Nazarbayev as "Embedded
Program Page"; run A files both as funding-shaped.

**Take run A**, for two reasons. First, it separates *where the page lives* from *where the operative
sentence lives*, which is the distinction our triage actually turns on — ADA has a funding-shaped
`/admission/financial-aid` page while the "no separate application" sentence sits in
`/admission/graduate`. Second, run B counts whole state portals (`turkiyeburslari.gov.tr`,
`studyinindia.gov.in`) as "dedicated domains", which inflates the dedicated share by answering a
different question: a scholarship programme's own domain is trivially funding-shaped, and our problem
is finding a *university's* award.

**The qualitative finding survives either number and is what matters:** several of the best
`AUTOMATIC_ON_ADMISSION` awards have their operative sentence off a funding path — ADA's in
`/admission/graduate`, IIT Delhi's IMSP in a PG brochure **PDF**, and Türkiye Scholarships' entire
participating-university list reachable only through a **dynamic search tool populated during the
application window**. Path-substring triage alone will miss a material share of the best awards.

### 4.2 Run B substituted METU Northern Cyprus for METU

Run A covers **METU** in Ankara: public, English-medium, ABET-accredited engineering, EUA member,
international master's fees of a few hundred USD a year. Run B covers **METU Northern Cyprus Campus** —
a different institution in a different jurisdiction, with a 2,200 TL/month assistantship.

That substitution matters precisely where Part D does: degrees awarded in Northern Cyprus carry
recognition problems in many countries, which is the question the run was asked to answer. **Run A's
METU is the one meant.**

### 4.3 Khazar — two different schemes, and run A found the useful one

Run A: the **Excellence Scholarship** (full tuition, master's and PhD) and automatic 25/50/75% merit
waivers, with the "no separate application" quote — and the honest limitation that it is **tuition
only**, "does not cover living, travel and other expenses", against Baku living costs of roughly
$400–1,000 a month. Run B instead reports the **Nailekhanim Scholarship**, a foundation award for
gifted female students, on a `DIRECT` route.

Both may exist. Run A's is the one that bears on the floor question.

### 4.4 Pakistan — run B is right and run A is wrong

Run A concludes Pakistan is a source country with no confirmed inbound funded master's scheme. Run B
found **HEC's Allama Muhammad Iqbal Scholarships**, open to citizens of Central Asian and other
friendly countries — 100% tuition, monthly stipend, accommodation allowance, return airfare, applied
through `eportal.hec.gov.pk`. **That is an inbound, fully funded, directly-applicable route for our
Central Asian population**, and run A's confirmed-absence is wrong.

### 4.5 Sabancı's terms differ, and run B's stronger quote is department-scoped

Run A: 32,500 TL/month, "almost all students admitted… are either totally or partially exempted".
Run B: 43,500 TL/month, free two-person dormitory, health insurance, laptop, unfunded tuition
USD 36,500, and the much stronger "**Except for rare cases, we only accept graduate students with
full scholarships.**"

If that sentence holds university-wide, Sabancı is close to a guaranteed floor. But run B sources it
to `iegrad.sabanciuniv.edu` — the **Industrial Engineering** graduate guide, one department. **Verify
before relying on it**; it is the single highest-value unverified claim across both runs.

## 5. Run B mixes direction in the Caucasus section

Run B's Georgian entries are largely **outbound**: Ilia State University relaying *Latvian* Government
Scholarships and a Korea Foundation fellowship, TSU relaying a Chinese Government Scholarship. Those
are Georgian institutions publicising foreign money for Georgians going abroad — the origin-side
channel — not funded places for internationals coming in, which is what this prompt asks for.

The inbound/outbound conflation is now the single most repeated failure across all six runs
adjudicated today. Run B's Koç entry is the exception and is correctly inbound: Koç bills tuition
directly to Azerbaijan's state scholarship programme for Azerbaijani state-sponsored students.

## 6. Run A alone: the ROR work, and an honest refusal

Run A supplies verified ROR IDs (Sabancı, Bilkent, METU, Nazarbayev, Khazar, IIT Delhi, IIT Madras)
and, for ADA, states that **no ROR record could be confirmed and warns against substituting the
unrelated "Ada Kent University" (Northern Cyprus) record.** That is exactly the behaviour the sourcing
rules ask for.

Run B declares instead that "ROR IDs remain unpublished across all examined official marketing and
program pages". **That misunderstands ROR** — it is a registry to be looked up, not an identifier
institutions publish. Run B returned no ROR IDs at all as a result.

Run A also flags that **Study in India publishes internally inconsistent figures** — ~9,500 waivers
across 108 institutes at 100/50/20% on one page, larger counts and 100/50/25% on another — and says to
cite the page used and treat the numbers as provisional.

## 7. Part C — both agree, and the answer is the expected one

**No body enumerates institutions offering funded international master's places across these
regions.** The lone structured exception is **India's Study in India portal**, which publishes a
browsable table of named institutions with per-institute fee-waiver counts. Everything else is a
dynamic search tool (Türkiye Scholarships), a single-grant programme list (Azerbaijan's SIACAS, 435
eligible programmes under one grant), or an exchange-oriented member list (TURKUNIB's ~170 member
universities, feeding Orhun — which funds one- or two-semester exchange, **not** a full master's).

Both runs reached this independently. It confirms the prompt's stated expectation rather than
overturning it.

## 8. What this changes for the model

1. **`AUTOMATIC_ON_ADMISSION` needs to be a first-class route value.** It is not `DIRECT` with a
   detail — it is a funded place with no second competition, which is what makes it a floor. Our
   `Application route` vocabulary has no such value today.
2. **Tuition-only cover is not a floor unless living costs are low, and that is now a testable pair.**
   Khazar (tuition-only, Baku $400–1,000/month) and METU (near-free public tuition) can be floors;
   the same waiver in a high-cost city is not. Affordability already models cost and coverage
   separately, so this is expressible — but only if coverage records **whether living costs are
   included**, which is the field both runs treat as optional.
3. **Discovery must not rely on path triage alone.** Crawl `/admissions/` and `/international/`,
   index PDF brochures, parse programme-page bodies, and handle dynamic search endpoints — and key on
   the three operative phrases. This is a concrete change to `apps/research` path handling.
4. **Ingest Study in India's fee-waiver table as a structured source.** It is the only enumerable
   list in scope.
5. **Teaching language is a hard filter, not metadata.** Türkiye Scholarships places students into
   Turkish-taught programmes with a mandatory Turkish year even for English-track placees; KNB and
   VIED are frequently national-language. A funded place in a language the student does not have is
   not an option.

## 9. Still open

1. **Whether the six Azerbaijani dual degrees fund the student at all**, and if so what "some costs"
   covers. Run B asserts full funding without a coverage quote; the recon shows the page does not
   support it. **This is the item to close first** — it decides whether Part A0 describes a floor.
2. **Whether Sabancı's "we only accept graduate students with full scholarships" holds university-wide
   or only in Industrial Engineering.**
3. **Whether any dual-degree equivalent exists outside Azerbaijan.** Unanswered by both runs, and the
   prompt rates it above everything they did find.
4. **ADA University's ROR ID** — unconfirmed, with an active trap adjacent to it.
5. **Heydar Aliyev eligibility for Armenia and Georgia** — run A flags OIC/NAM/ties status as needing
   verification against the current call.
6. **Whether the URL ratio is stable**, given the two runs inverted it. Run A's method is sounder;
   the number should be re-derived over a fixed institution list before anything is built on it.
