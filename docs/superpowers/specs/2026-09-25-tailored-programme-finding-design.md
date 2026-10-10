# Tailored programme finding — from a transcript to a risk-balanced pack

**Status:** design, approved section by section by the owner 2026-09-24/25. Not built.

**Builds on, does not replace:**
- `2026-08-27-risk-aware-portfolio-design.md` — the objective, the floor, the two bands, staging and
  deposits. This design keeps its principles and **defers its exact dynamic program** (§5.6).
- `2026-09-22-funding-search-engine-master-design.md` — especially §6.4a (programme enumeration) and
  §10.5 (demand cells). The owner's 2026-09-24 amendments to it (decisions 30–38: breadth-first,
  page-voiced search) live on `claude/funding-tap-rule` (PR #127) and bind this design too.
- `2026-09-19-recommendation-spine-design.md` — the pool → facts → gates → pack path that exists on
  master (`apps/research/spine.py`), whose pool query (`apps/funding/pool.py`) is interim by its own
  docstring. This design is what replaces it.
- `2026-09-15-student-owned-mailbox-design.md` — the source of scholarship results for re-planning.

**What exists today, measured on master 5b8c67a:** a 22-question wizard
(`apps/accounts/consultation.py`) whose field answer is one free-text box (`target_field`); a pool
that matches `Program.name__icontains=target_field`; a pack that walks a ranked list
(`apps/funding/pack.py`) with no risk levels and no stored reason; programmes with no entry
requirements beyond what the evaluator reads, and no topic description; a catalogue fed by the
EACEA Erasmus Mundus listing only.

---

## 1. Goal

Every student gets a pack of master's programmes and scholarships tailored to what they studied and
what they want, arranged as a portfolio of safe, target and reach applications, so that each student
ends up with at least an admission — and, when they said they can only go with a scholarship, a
funded admission — wherever such an option exists. Where it does not, the pack says so and says what
would change it.

## 2. Owner decisions recorded here

| # | Decision |
|---|---|
| T1 | Documents first. The student uploads transcript, CV and any language certificate; questions ask only what documents cannot say. |
| T2 | No fact-by-fact confirmation. One summary screen ("We read: …"); continuing is agreement; the four eligibility numbers are shown for one glance, and a row is highlighted only when a check fails (§3.1, amended 2026-09-26). |
| T3 | Seven fixed questions with skip rules (§3.2). Dynamic questions in exactly two places: narrowing after the search, and a missing-document upload. Never a free-form model chat. |
| T4 | Whether a course counts toward a subject requirement is **decided by us, never asked of the student.** Borderline counts keep the programme, one risk level up, with a note. |
| T5 | That decision is built on prior research into how admissions offices count credits (§4.4), and the Jev questions are written from that research. |
| T6 | Fine-grained field is **not** a fixed taxonomy. ISCED-F is too coarse (chemoinformatics has no code, and two chemoinformatics programmes differ). Programmes and students are described by weighted topic labels read from modules and courses (§4.2). |
| T7 | A label comes only from the programme's own pages — never from its name or general knowledge of a field. |
| T8 | Hidden gems are programmes with attached funding, recorded as a funding route on the programme, not a separate object. External awards stack unless the award's own rules forbid it. |
| T9 | Programme finding is the programme half of the funding search engine, and is **breadth-first** like it: many page-voiced angles, 10–15 results each, recall measured against a register. |
| T10 | Catalogue first; a thin slice triggers a targeted search whose results serve every later student in that slice. |
| T11 | Risk levels come from rules, not probabilities. No probability is shown to students until a model beats the rules on our own students' outcomes. |
| T12 | A student who needs a scholarship gets a funded safe option or none. With none: honest, "your best funded chance", and up to four widenings computed over our own data. |
| T13 | Every free-to-apply programme the student is eligible for enters the pack. |
| T14 | The plan re-plans when a scholarship result arrives; nothing changes until the student confirms. University applications wait for a scholarship result where §5.5 allows it. |
| T15 | Every candidate carries a plain reason for the student and a full decision record for us. |
| T16 | Outcome data from three sources: our students (consented, rejections included), funder-published winner lists (counts), LinkedIn winners (owner states legal sign-off; to be filed under `docs/legal/`). |
| T17 | Student data is stored as it is, in the tenant database, at full fidelity and reachable by erasure. Anonymisation and a training copy are deferred. |
| T19 | No generative model reads a transcript: OCR, then code and Jev (§3.1). Test transcripts are official samples and specimens, never a real person's transcript found online. |
| T20 | Transcript OCR is PaddleOCR PP-StructureV3, self-hosted, on straightened pages, behind an upload gate for resolution and blur; one engine, no second reader; code checks printed totals, scale ranges and mixed scripts, and shows a failed check without repairing it (§3.1, 2026-09-26). |
| T18 | The portfolio spec's phase gate (a recorded manual-consultant baseline over one admissions cycle before anything serves students) is lifted, for now (2026-09-25). |

---

## 3. Onboarding

### 3.1 Documents

1. Upload: transcript (required), CV, language certificate(s).
2. Read: institution, degree, grade and grading scale, each course with its credits and credit unit,
   languages, experience. Each course is then labelled (§4.2) and converted to ECTS (§4.4).
   **The student never watches a progress bar (owner, 2026-09-26).** Reading takes about two
   minutes for three pages, so the order is: upload → identity basics and the seven questions
   (§3.2) while the transcript is read → the summary screen **last**, when the reading has usually
   landed. A page the upload gate refuses asks for a rescan at once, at upload. If the reading is
   still running at the summary, the screen shows progress; if it failed, or about three minutes
   pass there, the student chooses between typing the details themselves and being emailed when
   the reading is ready.
3. One summary screen, the last step. Its top carries the four numbers that decide eligibility and are typed into
   portals — **overall grade, grading scale, total credits (with their unit) and graduation date** —
   for one "Is this right?" glance; a student knows these by heart. Below them, a course row is
   highlighted **only when a check fails** (§3.1, "What the reader checks"), never for spelling. A
   wrong scale or total silently wrongs the whole pack; a misspelled title costs almost nothing.
   Every correction a student makes is stored as a labelled example of where the reader failed.
4. A transcript without credits, or with titles too thin to label, produces one request: upload the
   course descriptions or a credit breakdown. That is an upload, never a judgement asked of the
   student.

The CV path's existing rule — a model-read fact is not a `VerifiedFact` until a person accepts it —
is met by the summary screen: continuing is the acceptance, recorded as such.

**Superseded for reading by `2026-10-03-transcript-reader-redesign-design.md` (2026-10-05): Azure Document Intelligence and the PDF's own text layer, the Lambda kept as a page inventory.**

**OCR first (owner, 2026-09-25).** Every transcript without a text layer — a scan or a photo, the
common case in the launch markets — goes through OCR before any model sees it. OCR returns the exact
characters and the table layout (rows and cells).

**The OCR is PaddleOCR's PP-StructureV3, self-hosted, on straightened pages (owner, 2026-09-26).**
Chosen by measurement, not reputation: five engines in nine configurations on 24 official-sample,
invented and real page images against hand-made answer keys (git-ignored at `.superpowers/ocr-eval/`, one `REPORT.md` per engine).

- **Why it:** exact course titles 91% Azerbaijani, 94% Russian, 84% Turkish (about 95% without one
  unreadable 129-ppi scan) — Russian excludes a specimen whose text is about 6 pixels tall, which
  every engine read 0% of; ə kept; free for commercial use (library and all twelve model weights
  Apache-2.0); runs in our own AWS account, so **no student document reaches an OCR vendor** (Jev's
  processors see trimmed table cells — below). Its layout step
  is what keeps a course on its own row: on real Turkish scans row pairing went 0% → 62% (NKU) and
  0% → 22% (BEUN) against PaddleOCR's own table pipeline.
- **Straightening first:** a 1° tilt put grades on the wrong course; straightening took that page
  from 57% to 96% of rows paired.
- **Rejected, with the reason:** Azure Document Intelligence read best on Turkish, Russian and tables,
  and its confidence was a real error signal, but it read Azerbaijani ə as e/a (46% of titles exact;
  57% with an Azerbaijani hint) and adds a processor. Surya read best overall but is a generative
  vision-language model (T19) under a licence free only below $5M revenue or funding. Tesseract read
  fewer titles and far fewer rows. docTR has no ə, ı or Cyrillic. Amazon Textract (below) lists none
  of the languages.
- **Known failure modes, which the checks below exist for:** silent letter swaps (ı→i, İ→I, ü→u);
  per-line confidence that says nothing (most wrong lines scored high); whole rows occasionally
  dropped, or two courses merged into one row carrying one set of grades; a word read in mixed Latin
  and Cyrillic letters ("Rуsсkий"). **The Azerbaijani result rests on invented pages** — no filled
  Azerbaijani-language sample is published anywhere (searched 2026-09-26) — so §7 gate 1 needs
  consented real transcripts before launch.

**Upload gate.** A page below a resolution floor, or too blurred to read, is refused at upload with
a request to rescan; nothing is guessed from it. Every engine read 0% of a 129-ppi scan and of a
specimen whose text was about 6 pixels tall. A tilted page is straightened, not refused.

**What the reader checks.** No second OCR engine: a second reader flags every disagreement, and
Tesseract alone disagreed on about a quarter of the Azerbaijani titles PaddleOCR read right —
friction for the student with no gain, and blind to errors both make. Instead, code checks what the
document itself lets it check, and highlights the row or semester only when a check fails:

- credits against every printed credit total (exact; catches dropped, doubled and merged rows and
  misread credits) — where a transcript prints no totals, the screen says "not checked", never
  shows it clean;
- the overall grade outside its stated scale (150 on a 100-point scale), and a course credit outside
  a sane range (a 60-credit course). Course grades are **not** range-checked: Turkish transcripts
  print letter grades per course beside a 4-point average, so every row would be flagged;
- a word mixing Latin and Cyrillic letters.

Averages are not checked: they are weighted, rounded and sometimes include failed attempts or
unprinted weights, so a misread single grade barely moves them. **A failed check is shown, never
repaired**: filling a missing value from a printed total writes a number the document did not show.

**No generative model reads a transcript (owner, 2026-09-25).** Code cuts, Jev picks, code copies —
the decision layer's rule. Code builds rows and columns from the OCR tables; Jev answers closed
questions about them — which column holds credits, grades or course titles; whether a row is a
course, a semester heading or a total; whether a course is completed, in progress or an earlier
failed attempt; which credit system the transcript uses; and the course-to-topic labels of §4.2.
Every value stored is copied from an OCR cell by code, never written by a model. A failed check
(above) or a low Jev probability becomes a highlighted item on the summary screen. This puts transcript
reading behind the decision layer (§9) and `TYPESAFE_API_KEY`.

**Every transcript goes through OCR, text-layer PDFs included (2026-09-26).** `pypdf` yields no
table structure, and one path is one path to test; PDF pages are rendered to images first. DOCX
transcripts are no longer accepted. `apps/documents/ingestion.py`'s `pypdf` path stays for CVs.

**Where it runs (owner, 2026-09-26).** PaddlePaddle ships no Python 3.14 wheel, so the OCR is its own
small program on Python 3.12, packaged as its own container image and run **on demand** as an AWS
Lambda function the document worker invokes per transcript — never an always-on worker (an
always-on task large enough for the models measured ~$85–150/month; on demand it costs cents per
transcript until volume reaches thousands a month). Its role reads cleared uploads and nothing else:
no database secret, no API key, so the process parsing untrusted files holds nothing to steal. The
web and worker images do not carry the models. A first transcript after idle waits for a cold start;
the summary screen shows that it is reading, never hangs. The function takes Lambda's full 10,240 MB
(6 vCPU, ~39 s a page; 8 GB saves under a cent a transcript and reads ~15% slower); new AWS accounts
start below that quota, so the increase is requested the week before the first deploy, with 8 GB as
the fallback if refused.

**Jev runs through OpenRouter** (owner, 2026-09-26; `TYPESAFE_BASE_URL=https://openrouter.ai/api`,
model `typesafe/jev-1.13`), so **OpenRouter and TypeSafe become processors of transcript content**.
Code sends only table cells and candidate lines, and drops every line carrying the student's name,
date of birth or an ID-like number before any call. **Launch gate:** real students' transcripts go to
Jev only after TypeSafe's DPA is accepted and OpenRouter's terms are reviewed (the typed-decisions
spec's own rule, §3.3); until then only official samples and the owner's own transcript are read.
Enforced in code, not by review discipline: `settings.TRANSCRIPT_JEV_ENABLED` (default off) gates
`apps/documents/transcript.py::read_transcript`, which raises `DecisionsUnavailable` before the
document is even opened while it is off (2026-09-27).

**Known limits, accepted for now:** only numeric dates are recognised (a date written in words leads
to the graduation question instead); when no total is printed, the total-credits number is our own
sum of completed courses and is shown as ours; a failed course never retaken stays marked completed.
**Amazon Textract is ruled out** despite running inside our AWS account: it reads English, Spanish,
German, Italian, French and Portuguese only (AWS, "Amazon Textract recognizes handwriting and adds
five new languages"), and the launch markets' transcripts are Azerbaijani, Turkish and Russian.
Mistral OCR was dropped before measurement as generative (T19); Google Document AI was not measured,
and would add a processor as Azure does. Revisit the choice only on evidence from real transcripts
(§7 gate 1): Surya on a GPU after legal review of its licence, or Azure for documents not in
Azerbaijani.

**A student still studying.** A final-year student's transcript is incomplete. Whether it lists
current courses varies: a US-style registrar transcript prints them as "in progress" with no grade,
while an interim transcript from many universities lists completed semesters only. So a course is
marked in progress **only when the transcript prints it so**, never inferred; and when the transcript
shows no completion date, one question is asked: "When do you expect to graduate?". A date the
transcript prints is copied; the date is **never estimated** from year of study (owner, 2026-09-25):
degree lengths vary (3, 4, 5–6 years; repeated years, transfers, part-time), a wrong estimate silently
excludes intakes, confirming an estimate costs the student as long as typing the date, and the student
knows it for certain. Revisit only if this question measurably causes onboarding drop-off. Credit requirements
are checked on completed credits, with in-progress courses able to lift a borderline count to
*conditional* but never to safe, and intake dates earlier than expected completion are excluded.

**Identity basics are not in any academic document.** Nationality, country of residence and date of
birth decide scholarship eligibility (citizenship, residence, age caps). They are read from a
passport or ID if uploaded, and otherwise asked as three short fields before the questions — they
are facts, not preferences, so they do not count against the seven.

**Languages.** Teaching languages and levels come from certificates and from the language of the
degree. With no certificate, one question: "Which languages could you study in, and do you plan to
take a test (which, by when)?" A planned test is recorded with its date (the profile already carries
`LanguageEvidence.available_by`).

### 3.2 Seven questions

1. What do you want to study, and anything specific within it? (free text)
2. Which countries would you consider, and which would you rule out? (default: anywhere)
3. When do you want to start?
4. Can you go without a scholarship? (only with one / prefer one / not needed)
5. How much can you cover yourself per year for tuition and living? — skipped when 4 = only with one
6. How much can you spend on application fees?
7. After the master's, do you want to work in that country, return home, or continue to a PhD?

Then an optional "Anything else we should know?".

Question 7 changes three things: post-study work rights weigh more for *work there*; return-bonded
scholarships become acceptable for *return home* and are flagged as a trap otherwise; research
tracks and funded research positions weigh more for *PhD*.

The dropped questions (weights, duration, mobility, negotiable and non-negotiable lists) take
defaults the student can change on the pack. `StudentProfileSnapshot` gains a new schema version:
self-funding capacity (the portfolio spec §13 already asks for it), the reworded question 7, and the
student's topic profile (§4.2).

### 3.3 Narrowing, after the search

When the slice's results split on the topic labels that differ most among them, the student gets one
or two questions built from those labels ("We found 40 programmes: some weighted to organic
synthesis, some to catalysis, some to polymers — which interest you?"). Asked only when the answer
changes the list. The mechanism is field-independent: nothing is configured per field.

---

## 4. Finding and describing programmes

### 4.1 Finding — the programme half of the funding engine

Slices are destination × broad field × level. Enumeration follows the master spec's §6.4a order:
national programme registers; one search restricted to each registered university's own domain;
funder-side seeds (the EACEA project API for every Erasmus Mundus programme); one page-voiced
open-web pass per slice, which is where hidden gems in countries the student did not name are found.

Breadth-first (T9): each angle is worded the way a programme page describes itself, in the page's
language, with 10–15 results per angle; never one topic query at 100. Recall is reported per slice
against the register's count. A hit on a host no register vouches for is not student-facing until a
person or a register confirms it — `CLAUDE.md`'s provenance guard, due before any production run
carries a search key.

Search wording is developed the way the scholarship angles were: per field and per language,
measured against `docs/research/programme-funding-known-answers.csv` (~50 verified funded
programmes), which each route must reach without a query naming the scheme or programme.

A thin slice (T10) triggers a targeted run for that slice only; the coverage line reads "12 found,
still researching 2 areas" rather than a short pack.

### 4.2 Describing — weighted topic labels

Read once per programme at ingestion, reused for every student:

- **Topic labels with weights.** Each module is labelled in the words programmes use ("machine
  learning", "molecular modelling", "heterogeneous catalysis"); a label's weight is its modules'
  share of the credits. A programme carries many labels. Every label cites the module or sentence it
  was read from (T7) — the reader's verbatim-quote rule applies.
- **Thin description.** A programme whose pages list no modules is flagged; it appears, but never
  ranks on topic alone.
- **Vocabulary.** Synonyms merge ("ML" = "machine learning"). Before building our own list, check
  OpenAlex Topics (open, CC0, ~4,500 topics) as the base vocabulary; build our own only where it
  does not fit, and record why.

The student's courses are labelled with the same vocabulary, weighted by their credits. One labelling
therefore answers both "does this student hold 20 ECTS of computing?" and "which programmes match what
this student studied and wants?". The student's question-1 answer and narrowing answer add interest
labels; a typed programme name ("chemoinformatics") is never expanded from general knowledge.

### 4.3 Requirements and attached funding

Per programme: subject-credit requirements (topic + minimum ECTS), grade bar and the programme's own
conversion rule, language, required documents, deadlines and admission rounds, whether admission is
rolling or first-come, application fee, and funding attached to the programme with its own deadline.
Attached funding is a funding route on the programme (T8), with its initiation type from the
portfolio spec §4.

Every external award carries a stacking field read from its rules: *forbids other funding* / *permits*
/ *silent*. Silent is shown as "check with the funder", never as forbidden.

### 4.4 Research before the credit decision (T5)

Before any credit count decides a student's pack, one research pass establishes:

- how admissions offices judge whether a course counts toward a subject (title, description,
  learning outcomes), with real examples — TUM's aptitude assessment, Dutch deficiency rules,
  uni-assist, UK and Nordic practice;
- credit conversion for non-ECTS systems, starting with the launch markets (Azerbaijan, Türkiye) and
  the US; a full-time year is 60 ECTS where no published rule exists;
- what happens near the bar: conditional admission, bridging courses, refusal;
- a labelled set of real transcripts against real requirements, which is the gate Jev must pass
  before it decides anything, written per `2026-09-23-jev-question-engineering.md`
  (on `claude/fetch-spec-refresh`).

The pack always says our count is our estimate, never the university's decision.

---

## 5. The pack

### 5.1 Gates first

Credit requirements, grade bar, language, nationality, legitimacy and reachable deadlines. A clear
miss excludes the programme, which stays visible in the pool with its reason. A borderline credit
count keeps it, one risk level up, with a note ("we counted 18–22 of the required 20").

### 5.2 Risk levels, by rule

- **Safe** — meets every published bar with margin, and admission is rule-based (not
  capacity-competitive). For a scholarship-only student the funding must also be near-certain: an
  automatic waiver, or funding considered with admission on a programme where the bar is met with
  margin, or a large non-competitive scheme the student meets.
- **Target** — bar met, selection competitive.
- **Reach** — competitive programme, or a lottery-like scholarship.

Missing data never counts as safe. Nomination-only routes are never safe (portfolio spec §7.4).

**A requirement the student can still meet** — a language test planned before the deadline, a GRE
not yet taken, a final-year course in progress — keeps the programme as an action item ("needs
IELTS 6.5 by 15 January"), never safe until the evidence exists. A test's fee is shown beside it,
since it is money the student spends to apply.

### 5.3 No safe option (T12)

Every candidate is still shown. Nothing is labelled safe; the strongest funded option is named
"your best funded chance". Up to four widenings are computed — one relaxed answer at a time
(country, field breadth, start date, a missing certificate) — over the catalogue already held, with
no new search and no model call. Each that produces a safe option becomes one sentence.

### 5.4 Money

- The safe option's fee first; the rest of the budget on target and reach. The budget is spent, but
  never on an application that adds nothing (a second application to a funder already in the pack).
- Every eligible free-to-apply programme is included (T13), grouped as "free to apply", best fit
  first, because each still costs the student documents and time.
- Scholarships are separate applications and are never subtracted from a programme's cost.
- Money at risk (a deposit due before a scholarship decision) is named with its amount.

### 5.5 Timing and re-planning (T14)

A university application waits for a scholarship result only when all hold: the result arrives
before the university's deadline; admission is not rolling or first-come; the programme's own funding
has no earlier round; and the visa still fits after the later deadline. Otherwise apply in parallel
and state the money at risk.

When a result arrives — reported by the student or read by the mailbox feature — the unspent budget
is re-planned over the remaining options and presented to the student; nothing changes until they
confirm.

### 5.6 Publishing in stages

A thin slice's targeted search can take hours. The pack is published with what the catalogue
already holds, carrying the coverage line ("12 found, still researching 2 areas"), and republished
as a new pack version when the research finishes — the student is told what changed. A pack is never
held back waiting, and never silently short (P1-7).

**Pack size and documents.** The pack can be long, because every free eligible programme enters it
(T13). Letters and CVs are generated only for the applications the student chooses to pursue, not
for every row — the letter engine's per-student hourly limit (20) would otherwise be hit by the pack
itself (`2026-09-24-letter-scope-and-story-reuse-design.md` §7, on `claude/letter-gap-fixes`).

### 5.7 Who sees the reasons

The student sees the plain reason on every row. An agency counsellor sees the same text plus the
decision record's sources. Nothing waits on the counsellor (owner decision 2026-09-23: no person in
the pipeline).

### 5.8 What is deferred

The portfolio spec's exact dynamic program over probabilities (§7.3 there) waits for a probability
model (§6.2). Until then allocation is the rule-based order above.

---

## 6. Reasons and outcome data

### 6.1 Reasons (T15)

Every candidate in the pool, excluded ones included, stores:
- a plain reason for the student ("Safe: 24 of the required 20 computing ECTS, and the tuition
  waiver is automatic");
- a decision record: every fact, gate, label, requirement, source URL and snapshot, rule version and
  code version behind it, enough to replay the decision.

### 6.2 Outcomes and the model

- **Our students:** where they applied and what happened, rejections included, stored as it is in the
  tenant database (T17) and reached by erasure. This is the only source a model is tested on.
- **Published winner lists:** counts, never a file on a person.
- **LinkedIn winners:** a separate collection project, specified on its own. Winners only, so it
  describes winners and cannot on its own estimate a chance.

No probability is shown until a model beats the rule-based levels on our own students' outcomes.

---

## 7. Measurement — gates before scale

1. Transcript reading: grade, scale, credit unit and per-course credits correct on a labelled set of
   real transcripts, per launch-market country. Azerbaijani-language transcripts come only from
   students who consent — none is published — and are needed before launch (§3.1).
2. Credit decision: Jev's course → topic call against §4.4's labelled set.
3. Topic labels: every label traceable to a quote; two same-named programmes with different modules
   receive different labels on a hand-checked sample.
4. Finding: recall per slice against the register, and the known-answer set reached with no
   scheme-naming query.
5. Pack cases: a scholarship-only student never gets an unfunded safe option; no-safe-option packs
   name widenings; a free eligible programme is never missing; a waiting plan is never produced for
   a rolling-admission programme or a programme whose funding round closes first.

## 8. Security, cost and freshness

- **Uploads are untrusted input to a model.** Transcript and CV text is labelled as data, never
  instructions, output is schema-constrained with `extra="forbid"`, and every call is capped — the
  `apps/research/extraction.py` pattern. Every model-calling step a student triggers carries a
  per-student `rate_limited()` limiter in the same change (`apps/ratelimit.py`); ingestion already
  carries one (15 uploads).
- **Programme descriptions are shared-catalogue data.** Topic labels and requirements are read by
  every tenant, so they are written only by the `runtime_engine` role (the web tier cannot even read them) and only from pages reachable
  from an `OfficialSource` the catalogue vouches for — never from a URL a tenant supplies
  (`CLAUDE.md`, `ProgramStatement`). A student's own labels are tenant data and never enter the
  catalogue.
- **Cost per student** is the onboarding reads (on-demand OCR, measured 94–214 CPU-seconds per page
  — cents per transcript, no per-page vendor fee; one structured read per document, one Jev call per course batch) plus pack assembly, which makes no
  model call. Catalogue reads and targeted searches are per slice and amortised across students; the
  first student in a thin slice triggers its search, bounded by the engine's per-vendor
  `SweepBudget`.
- **Freshness.** Modules, requirements, fees and deadlines change per admissions cycle. A programme's
  description carries the cycle it was read for and is re-read under the master spec's §9 cycle
  verification; a stale requirement never decides a gate, it makes the row *unverified for this
  cycle*.

## 9. Dependencies on work in flight

- **The decision layer** (`plans/2026-09-23-decision-layer-and-rule-grammar.md`, on
  `claude/fetch-spec-refresh`, not executed) builds `apps/research/decisions.py`, the one Jev client,
  and `DecisionRecord`. Every Jev call in this design goes through `decisions.ask()` — never a third
  Jev client beside it and `research_fit/jev.py`. It is blocked on `TYPESAFE_API_KEY`, which does not
  exist on this machine; until it lands, the steps that need Jev (course labelling, programme
  labelling, the credit decision) cannot start.
- **The fetch engine** (`claude/fetch-engine-core`, in progress) and **the page-finding funnel**
  (plan 4 of the same set) are how programme pages are fetched and found.
- **The funding engine's breadth-first amendments** (PR #127) and search adapters (PR #128).
- **The mailbox** (`claude/student-mailbox*`) for reading scholarship results.

## 10. Build order

Each step is its own implementation plan.

1. §4.4 research and the labelled transcript set — no code, no dependency.
2. **Onboarding from documents:** transcript reading (text and scans), ECTS conversion, identity
   basics, the summary screen, the seven questions and the new profile version (§3.1–3.2). Depends
   on the decision layer's client (its plan's Task 1), since Jev picks every column and row.
3. Topic labelling for courses and programmes, and the credit decision (§4.2, §4.4) — after the
   decision layer.
4. Programme requirements and attached funding at ingestion (§4.3) — after the fetch engine.
5. Finding: slices and angles over the engine (§4.1) — after PRs #127/#128 and the funnel.
6. **Destination facts and living cost** (added 2026-10-03, owner): nothing else builds them, and
   §5.4 and §5.5 cannot be computed without them. Both are already designed; this step builds them,
   for the destinations in the owner's country list, launch students applying from Azerbaijan:
   - `DestinationPolicy`, one cited, versioned record per country
     (`2026-08-27-risk-aware-portfolio-design.md` §5.1): the visa financial-proof amount,
     post-study work rights, the commitment-payment norm, and — added here — visa processing time
     and appointment wait for an applicant applying from Baku, which §5.5's "the visa still fits"
     needs. The deposit-deadline pivot is that spec's §8.3.
   - `CityCost`, one per-city range researched once and refreshed yearly
     (`2026-09-17-role-routed-discovery-design.md` §4.11), which §5.4's "money at risk" and the
     funding gap need.
7. Narrowing (§3.3), gates, risk levels, money, timing, reasons (§5, §6.1) — after step 6.
8. Outcome capture (§6.2), re-planning from the mailbox (§5.5).

## 11. Open

- TypeSafe's DPA and a review of OpenRouter's terms — the launch gate for reading real students'
  transcripts (§3.1).
- The legal note for LinkedIn collection, and the consent and data-use text for direct-to-student
  users (no consent model for them exists today — `CLAUDE.md`, derived data).
- Whether OpenAlex Topics fits as the base vocabulary.
- Where the students' outcome record lives relative to `portals.Application`, whose `CONFIRMED`
  state means the portal accepted a submission, not that the university admitted the student.
