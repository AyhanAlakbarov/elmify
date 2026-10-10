# Evidence note: storytelling in engine-authored motivation letters

Date: 2026-09-14. Status: **evidence note, feeds the 2026-09-14 amendment of the letter plan**
(`docs/superpowers/plans/2026-08-23-phase2-motivation-letter-engine-plan.md`, Tasks 3, 4, 6, 7,
11b, 12, 13, 14). Companion to `2026-08-22-letter-ruleset.md` (the 71 destination rules in
`letter-rules.csv`), which this note does not repeat: it answers the one question the ruleset
left open — **how the engine chooses and tells the story** once the reader, shape and limits are
known.

Findings carry `N-` ids so the plan can cite them the way it cites `L-` and `S-` rules. Tiers:
T1 = the reader's own published wording; T2 = a university writing centre or a peer-reviewed
study; T3 = a commercial guide quoting T1 (used only where it quotes, never for its own advice).

## 1. Question and method

Decision 2 of the letter design says the engine authors the narrative and the student edits it
(decision 7: nothing is asked of the student before a draft exists). Task 12's prompt says only
"hold one unifying theme", so the model picks the theme, the order and the turning point in the
same call as the prose. The question was what a chosen story should look like per reader, and how
far the engine may invent.

Read directly, 2026-09-14: Ding (2007) *English for Specific Purposes* 26, the only controlled
move analysis (20 successful vs 10 unedited statements); MIT EECS's Communication Lab guide and
its page of fourteen faculty statements; UC Berkeley Graduate Division; Cornell Graduate School;
Iowa State's open textbook with ten accepted statements and a faculty-advice chapter; Purdue OWL's
two samples; DAAD's advice sheet (Section ST 32) and its AI-use FAQ; Göttingen's programme page
built on that sheet; KTH's Computer Science entry-requirements page; TU Delft CoSEM; Leiden
Clinical Psychology; Chevening's application-criteria page, common-errors page and the 2023
reading-committee feedback post. Secondary (T3): GradPilot's destination guides and
ScholarshipUnion's Erasmus Mundus guide, used for quoted T1 wording only.

Six `gptr-mcp` runs backed the first pass (AI-vs-human text, detectors, humanizers, narrative
structure, genre analysis, exemplar corpora). Two broad multi-destination runs hung and were
killed at the 30-minute idle limit; nothing below rests on them.

## 2. Findings

### 2.1 The story is invented; the circumstances are not

- **N-01 (T2, Ding 2007).** Successful statements told 0.8 stories per essay; unedited ones 2.4.
  Personal or family experience as the *reason* for applying was 7.5% of sentences in the
  successful corpus and 20.5% in the unedited one. Successful statements spent twice as much on
  academic or intellectual interest (0.9 vs 0.5 moves; 2.7 vs 0.4 sentences per essay) and 5:2
  more on professional experience. Ding's worked example of an irrelevant story is an applicant's
  father's farm: 224 of 730 words, "only remotely relevant". Personality in successful essays is
  shown "through facts", not stated.
- **N-02 (T1/T2, readers in their own words).** MIT CommKit: "Avoid cliché openings like 'ever
  since my childhood, I've been fascinated by…'. The statement of purpose should tell your
  unique research story, not your life story." Karger (MIT EECS): "Not why you've loved computer
  science since you got your first PC at age 4, but why you consider certain specific problems
  important and interesting." TUM style guide: the statement "is not just a letter of
  motivation… explain why you are suitable". LSE's "what does not work" list opens with "I have
  always been passionate about economics". Berkeley: "don't spend a great deal of time on
  autobiography." Cornell: "an academically focused essay, not necessarily a personal essay."
- **N-03 (T2, Iowa State corpus).** Nine of ten accepted statements open with a personal
  circumstance (a Mexican vocational school, a sister's illness, a refugee childhood, a Brazilian
  town's herbal remedies). Each is true, one paragraph, and followed by credentials that carry the
  rest. Faculty in the same book: "Application readers can easily detect when someone is writing
  what they believe that the readers want to hear." Oppenheim (MIT): "If the personal statement is
  genuine and honest, it shows. And if it isn't, it also shows."
- **N-04 (rule derived from N-01–N-03 and the design's claim kinds).** The engine may invent the
  **theme, the causal links, the ordering, the interpretation of a grade dip or failed project,
  the gap it names, and the plan** — all `INTERPRETIVE`, `ASPIRATIONAL` or `DECLARED`. It may
  never invent a **person, an event, a number, a name, a date or an institution**; those are
  `FACTUAL`/`SOURCED` and the existing gate blocks an uncited one (`UNSUPPORTED`,
  `UNDECLARED_ASSERTION`). Where a reader wants an origin (US statements, GKS Form 2, Fulbright,
  DAAD scholarship letters), the engine fills it from real ledger facts — home country plus a
  sourced fact about the field there — or proposes a background sentence as an engine-proposed
  `NarrativeInput` the student sees in the overlay and edits; accepting the draft confirms it
  (decision (c), struck). **Owner's line, 2026-09-14:** the boundary is whether a submitted
  document could check the claim. A course, grade, degree, date, employer, institution,
  publication or number comes only from the ledger; the motivation, reasoning, framing and plan
  around it the engine writes freely, and the student edits the letter afterwards. "My father is
  a financier and I was passionate about finance from childhood" is not checkable, so its
  exclusion rests on the evidence alone: it is the losing pattern (N-01, N-02).
- **N-05 (T2, MIT CommKit; T1, Cornell).** Setbacks are wanted, not tolerated: "If there were
  challenges, don't be afraid to mention what you learned from them… persistence and resilience
  — these are also things they are looking for" (Cornell); Kaelbling (MIT): "I don't worry about
  a few poor grades, if they have an explanation." A redemption sequence built on a real negative
  fact (grade dip, failed project, missing prerequisite) is the strongest turn available; the
  ledger must therefore surface negative facts, not only achievements. It does not today
  (measured 2026-09-14: an `EDUCATION` fact is one row per degree,
  `apps/documents/schemas.py::EducationEntry`, keyed on institution and degree in
  `apps/documents/verification.py`, and the ledger records no negative facts at all — absence is
  just absence). Decision (b): no ingestion task; the turn uses a real negative fact only where
  the ledger holds one, and the storyline falls back to the other shapes otherwise.
- **N-06 (T3 quoting T1 limits; T2 pattern).** A master's reader "is buying preparation, and
  wants the subject of the essay inside the first three sentences" (GradPilot, master's guide);
  the strongest UK exemplar found is built on a named **gap** — what the applicant can do, what
  they cannot yet do, and the module that closes it — and the annotation's justification is that
  "the reasoning is the part nothing else carries". Berkeley's prompt wording "academic plans
  **or** research interests" makes a plan a complete answer for a taught master's.

### 2.2 Text that reads as a person's, and what does not help

- **N-07 (T2, peer-reviewed).** Stylometric uniformity — same sentence lengths, same paragraph
  sizes, one tone, tidy intro and conclusion — separates model text from human text at 93–99% in
  classifier studies; "excess vocabulary" (Kobak et al., PubMed abstracts: *delve, crucial,
  testament, underscore, pivotal, showcase, leverage*) traces to instruction tuning (Juzek & Ward).
  Frequent LLM users detect model text accurately without training (Russell et al., ACL 2025);
  experts know humans write the run-on sentences and models the grammatical ones.
- **N-08 (T2).** Paraphrasers and "humanizers" either fail or damage: Turnitin classifies
  paraphrased model text as model text; Pangram's study of 19 humanizers (arXiv 2501.03437) found
  a detector trained on their output catches them; a T5 humanizer tried in this repo on 2026-09-14
  corrupted URLs and dropped numbers. Detectors mis-flag non-native English writers — 61.3% of
  TOEFL essays in Liang et al. (2023) — which is this platform's whole population. Consequences,
  unchanged from the design: no rewrite pass (the assessment's architectural reason stands), no
  detector gate, no best-of-N against a detector (§4.2.3 forbids aiming at detectors).
- **N-09 (T3, `harshaneel/humanize`, MIT).** Of its nine levers, five duplicate the pinned
  `blader/humanizer` patterns already in Task 12's prompt. Three are new and cheap: no semicolons
  and at most one em dash per 300 words; colons only after a complete sentence; strip the
  assistant register (unprompted balanced trade-offs, enumeration where one answer will do,
  hedged closers). Its own README says few-shot style cloning is a documented dead end (arXiv
  2509.14543), which is why the engine reuses a student's *facts*, not their idiolect.

### 2.3 What each reader rewards — primary wording

| Reader | Rewards | Penalises | Source |
|---|---|---|---|
| **DAAD scholarship** (`GOVERNMENT_SCHOLARSHIP`) | Professional goal *and sector*; contribution to home-country development — "some facts and figures are highly welcome"; "which of the courses offered… are particularly beneficial"; knowledge, professional experience, organisational membership *with proof*; personality "emphasize your strong points, but be realistic". "Not all of the above questions have to be addressed." | Repeating the CV; "platitudes, flowery phrases and flattery"; campaigning for beliefs. | T1 advice sheet (`advice-for-motivation-letter.pdf`); AI permitted with "Produced with the aid of (tool used)" and a Declaration of Authenticity; "applicants' unique qualities and characteristics should remain evident" (T1 FAQ B.3) |
| **German admission** (Göttingen, TUM) | "Analytical skills, academic writing"; "a short outline of an example of a research project you could be conducting" and "which of your skills equip you"; TUM: suitability and commitment, "do not simply list related courses". | "Do not retell the information about the programme from our web page — we wrote it, we know it." | T1 Göttingen 648936; T1 TUM via L-050 and GradPilot quoting the style guide |
| **KTH** | Selection: "study results, motivation for the studies (**awards, prizes and publications**) and previous education", merit-rated 1–75. Letter under 500 words, includes an autobiography, names the programme at the top. | Prose that points at nothing tangible. | T1 entry-requirements page |
| **TU Delft CoSEM** | 200 words motivation, 100 on the track, 200 on **two hypothetical thesis projects**, plus a passed-course list with learning objectives. | A continuous letter. | T1 programme page |
| **Leiden** (Clinical Psychology) | "Quality and structure of the reasoning"; "connection of personal interests and motivation with the content of the programme"; language. | Over the limit by more than 10%: no Excellent. | T1 via L-055 |
| **UK taught master's** (LSE, Edinburgh, UCL, Sussex) | Academic engagement beyond the curriculum: a dissertation, a method, a question, and the module that continues it; LSE's 80/20 academic rule. | "I have always been passionate about…"; rankings as reasons; Sussex: "should not contain any autobiographical information about your personal life". | T1 via L-038/L-039/L-044; T3 quoting LSE and Sussex |
| **Chevening** (`SHORT_ANSWER_SET`) | STAR for every example; "use 'I' instead of 'we'"; recent professional examples; a position is not leadership — "explain how you successfully gained and maintained influence and what the outcome was"; name the networks and what they achieved; modules and assessment; "specific, measurable goals"; full sentences. | School-era examples; listing responsibilities; "local attractions and football clubs"; cut-and-paste from university sites. | T1 reading-committee feedback (2023) and application-criteria page (2026) |
| **Commonwealth** | Four development-impact fields as one chain: need → capability → outcome → evidence; outputs are not outcomes; three career horizons that differ. | "Impact will be monitored"; the same destination at three dates. | T1 via L-029; T3 field map |
| **US faculty SOP** (MIT, Berkeley, Cornell) | A problem the applicant found; "concrete and quantitative experiences"; "make a narrative out of your CV. It is *not* a diary entry"; meaning wrapped around each experience; named faculty and programme features; discipline terminology. | Autobiography; "over the top" essays (Berggren); vague experience sentences. | T1/T2 MIT CommKit and faculty page; T1 Berkeley; T1 Cornell |
| **MEXT / CSC / ESKAS** (`PRESCRIBED_RESEARCH_FORM`) | Past field → research theme → plan, "in a detailed and concrete manner"; feasibility. | Drama; a plan that cannot be carried out. | T1 via L-011, L-014, L-008 |
| **GKS** | Form 2: motivations, background, significant experiences, persons or events of influence; Form 3: direction and tangible plans during and after. | Confusing the two forms. | T1 via L-015, L-017 |
| **Immigration** (Australia GS, IRCC) | Ties, circumstances, evidence-backed statements. | Any invented "why": misrepresentation carries legal consequences. | T1 via L-004–L-006, L-058, L-059 |

### 2.4 Craft rules with evidence

- **N-10** One unifying theme (Purdue OWL via L-062; thematic coherence in McAdams' narrative
  identity framework). Three theme kinds fit the readers above: a **problem** for faculty readers,
  a **plan** (goal → contribution → programme) for scholarship readers, a **match** for readers who
  fill in a score (KTH, Leiden, TUM).
- **N-11** Evidence before interpretation; every fact gets one sentence of "so what", and that
  sentence is the transition (MIT CommKit's "wrap meaning around your experiences").
- **N-12** Quantify: "top student among my cohort of 20", "a 10,000-line Fortran library" (MIT's
  vague-to-concrete table). Describe a project by what went wrong, then what was done.
- **N-13** Agency over communion: "I sought out… then proposed…", never "I was fortunate to"
  (McAdams via GradPilot; Chevening's "I" not "we").
- **N-14** Under a cap, cut commentary first and keep method, consequence and gap (the UCL
  re-cut of the Edinburgh exemplar).
- **N-15** Fit must survive a find-and-replace: swap the university's name for another and reread;
  if the paragraph still makes sense it says nothing. Fit is a named module, track, lab, thesis
  structure or consortium mobility path; Fulbright asks "why does the project have to be conducted
  in the country of application" in those words.
- **N-16** The origin slot, where the reader wants one, is one paragraph of real circumstance
  followed by credentials (N-03) — never the arc.
- **N-17** Intrinsic beats impact except where an archetype asks for impact: a master's-admission
  essay study found "master specific" and "interest to learn" moves predicted later grades, while
  "societal impact" and "city and university" moves predicted the opposite.
- **N-18** Kaelbling remembers essays "with a strong or novel view or that articulate a clear
  vision": one committed opinion about the field beats a balanced survey.
- **N-19** "Do not manufacture contact to fill the box" (Commonwealth, T3 quoting the form): an
  empty field beats an invented one; the same holds for every optional archetype.

### 2.5 Open-source tools assessed — none adopted as a component

DIPPER, TinyStyler (meaning floor 0.70/0.85), Lynote's T5 humanizer and StealthHumanizer are
evasion or paraphrase models and lose meaning; `fromleda/text-humanizer` was found on 2026-09-14
to contain code that does not match its README. `desklib/ai-text-detector-v1.01` (MIT, DeBERTa,
Feb 2025) predates GPT-5-era output and would fire on exactly our writers (N-08); it is not wired
anywhere. `harshaneel/humanize` contributes three prompt lines (N-09). `blader/humanizer` stays
pinned at v3.0.0 as before.

## 3. Consequences for the plan (amendment of 2026-09-14)

| Finding | Plan change |
|---|---|
| N-04, N-10 | New Task 11b: a storyline step proposes three candidate stories per core narrative and a deterministic scorer picks one; theme kind by `funder_kind`; the storyline is stored on the `CORE_NARRATIVE` draft's `LetterContent.storyline` and handed to Task 12 as data |
| N-04, N-16 | `NarrativeInput.Kind.PERSONAL_BACKGROUND` (Task 3); an engine-proposed background is a `DECLARED` input like any other — accepting the draft confirms it (owner decision (c), struck 2026-09-14) |
| N-05 | Task 11b's proposal prompt is told to prefer a real negative fact as the turn; deterministic gap derivation from `ProgramStatement` is a follow-up |
| N-09, N-13, Chevening feedback | Task 12 prompt: story block as data; STAR and first-person rules for `SHORT_ANSWER_SET`; punctuation and assistant-register lines |
| N-15 | Task 7: a `WHY_PROGRAMME` unit needs a `SOURCED` claim, not merely a `FACTUAL` one (`GENERIC_PARAGRAPH` detail) |
| Commonwealth, Chevening | Task 7: `DUPLICATES_SIBLING_ANSWER` across answers of one set; `FIRST_PERSON_PLURAL` in leadership and relationship units |
| N-04 | Task 7: `STORYLINE_DRIFT` when the letter's factual claims skip the storyline's anchors |
| Chevening feedback | Task 14: `example_not_recent` counselor flag (not a gate — a student with only old examples must not be blocked) |

## 4. Owner decisions (resolved 2026-09-14)

- **(a) `PROHIBITS` destinations — keep decision 6.** Chevening now states detection,
  disqualification and "you do not need to pay anyone"; Cambridge, Oxford and Edinburgh prohibit;
  Rhodes says "mentors must not write or edit". The engine still drafts for these readers; the
  policy is surfaced, never gated, and no reader is excluded.
- **(b) Ledger granularity — no ingestion task.** Measured: `EDUCATION` facts are degree-level
  only and the ledger holds no negative facts (N-05). The owner's line is checkability, not
  granularity: anything a submitted document could check comes only from the ledger; everything
  else — the why, the framing, the plan — the engine may invent, and the student edits. The
  setback turn fires only where a real negative fact exists; deterministic gap derivation stays
  a follow-up.
- **(c) Per-item confirmation — struck.** An engine-proposed `PERSONAL_BACKGROUND` input is
  `DECLARED` like any other: never blocking, confirmed by the student's acceptance of the draft.
  One click was judged not worth the friction; the student edits the letter afterwards anyway.

## 5. Limits

Ding's corpus is medical and dental, 2007, US; the Iowa State corpus is PhD-heavy; Purdue's
samples are decades old. The master's-specific evidence is thinner and partly T3. MEXT and GKS
rest on the catalogued guideline PDFs, not a fresh read. Chevening's wording moved between the
2023 feedback (detail all three courses) and the 2026 criteria page (focus on the first choice):
the live form governs, which is the design's `ApplicationPrompt` rule. Nothing here was measured
on an engine-generated letter; the storyline step is a design inference from reader evidence, to
be checked against counselor judgement once letters exist.

## 6. Sources (all fetched 2026-09-14)

- Ding, H. (2007). Genre analysis of personal statements. *English for Specific Purposes* 26,
  368–392. <https://faculty.washington.edu/farkas/HCDE510-Fall2012/Ding-GenreAnalysisPersonalStatements.pdf> (T2)
- MIT EECS Communication Lab, Graduate School Statement of Purpose.
  <https://mitcommlab.mit.edu/eecs/commkit/graduate-school-statement-of-purpose/> (T2)
- MIT EECS, What faculty members are looking for in a grad school statement of objectives.
  <https://www.eecs.mit.edu/academics/graduate-programs/admission-process/what-faculty-members-are-looking-for-in-a-grad-school-application-essay/> (T1)
- UC Berkeley Graduate Division, Writing Your Statements.
  <https://grad.berkeley.edu/admissions/application-process/writing-your-statements/> (T1)
- Cornell Graduate School, Writing Your Academic Statement of Purpose.
  <https://gradschool.cornell.edu/inclusion/recruitment/prospective-students/writing-your-statement-of-purpose/> (T1)
- Todey, E. (2025). *A Guide to Writing the Statement of Purpose*, Iowa State University Digital
  Press, CC BY-NC-SA 4.0 — Section 6 (ten annotated accepted statements) and Section 8 (faculty
  advice). <https://iastate.pressbooks.pub/statementofpurpose/> (T2)
- Purdue OWL, Examples of Successful Statements.
  <https://owl.purdue.edu/owl/job_search_writing/preparing_an_application/writing_the_personal_statement/examples.html> (T2)
- DAAD, How to Write a Letter of Motivation (Section ST 32).
  <https://www2.daad.de/medien/deutschland/stipendien/formulare/advice-for-motivation-letter.pdf> (T1)
- DAAD, Important information for scholarship applicants, B.3 on AI use.
  <https://www.daad.de/en/studying-in-germany/scholarships/information-for-scholarship-applicants/> (T1)
- Georg-August-Universität Göttingen, How to Write the Letter of Motivation.
  <https://www.uni-goettingen.de/en/648936.html> (T1)
- KTH, MSc Computer Science entry requirements and selection criteria.
  <https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975> (T1)
- TU Delft, MSc CoSEM application with a non-Dutch BSc.
  <https://www.tudelft.nl/en/education/programmes/masters/cosem/msc-complex-systems-engineering-and-management/application-and-admission/with-a-non-dutch-bsc-degree> (T1)
- Chevening, Application criteria; Common application errors; Where did I go wrong (2023).
  <https://www.chevening.org/resource-hub/guidance/application-criteria/>,
  <https://www.chevening.org/resource-hub/guidance/common-errors/>,
  <https://www.chevening.org/news/where-did-i-go-wrong-on-my-chevening-application-feedback-from-this-years-reading-committees/> (T1)
- Russell, Karpinska, Iyyer (2025). People who frequently use ChatGPT for writing tasks are
  accurate and robust detectors of AI-generated text. ACL 2025.
  <https://aclanthology.org/2025.acl-long.267> (T2)
- Liang et al. (2023). GPT detectors are biased against non-native English writers. Via
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC12453642> and the Pangram humanizer study
  <https://arxiv.org/pdf/2501.03437> (T2)
- Kobak et al. (2024). Delving into ChatGPT usage in academic writing through excess vocabulary.
  arXiv:2406.07016 (T2)
- `harshaneel/humanize` README, nine levers and limits. <https://github.com/harshaneel/humanize> (T3, MIT)
- GradPilot destination guides (T3, quoted T1 wording only): Chevening, DAAD, TUM, LSE/Imperial/
  Oxford/Cambridge, Nordic, UK examples, Commonwealth, Netherlands, Fulbright, master's SOP,
  narrative identity — <https://gradpilot.com/news/graduate-school-essays>
- ScholarshipUnion, Erasmus Mundus motivation letter (T3).
  <https://guides.scholarshipunion.com/erasmus-mundus/motivation-letter.html>
