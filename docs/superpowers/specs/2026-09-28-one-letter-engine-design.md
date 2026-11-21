# One letter engine: requirements, research, story, writing, checking

**Date:** 2026-09-28
**Status:** design, awaiting owner review
**Branch:** `claude/letter-gap-fixes` (docs only in this commit)
**Evidence:** `docs/research/2026-09-28-letter-engine/` — admissions readers, specificity by reader,
human voice, writer benchmarks, flagship writers and hosts, harness best practice, watermarks and
the EU AI Act, and the 2026-09-27 cheap-model spike. All fetched 2026-09-28 unless dated.

One entry point builds one motivation letter for one student and one target (a programme or a
funder). It reads what the target asks for, researches what makes this target specific for this
student, reuses the student's one story, plans the letter in code, has a flagship Chinese model
write it, checks every sentence in code and with Jev, repairs only what failed, and renders it.

## 0. What governs

This is the master design for motivation letters. Where it and an earlier document disagree, this
one governs; everything not named here stands.

| Earlier document | What this design does to it |
|---|---|
| PR #159, `2026-09-26-requirement-reader-addendum-design.md` | **Consumed, not redesigned.** S2 reads its `LetterShape`. |
| `2026-09-22-letter-research-fit-from-the-student-design.md` | Kept: D1 anchor ladder, D2 profile-free queries, D5 code splits / models classify, D7 per-tenant storage, D9 render re-check, D11 never blocks, D14 professor data. **Changed:** D6 judge becomes Jev (S3.6); its §9 "no OpenAlex" is reversed for institution-plus-topic lookup, never lookup by name (S3.4). |
| `2026-09-24-letter-scope-and-story-reuse-design.md` | Its Plan A (wire `storyline.py`, one story per student) is S4 here. Its "three readings must agree" for `letter_scope` is replaced by #159's single reader. |
| `2026-09-27-verified-catalog-one-reader-design.md` §6.2–6.5 | S7 is the full form of its letter check; §6.4 identifier stripping and §6.5 censorship routing are S1 and S6. |
| `docs/research/2026-09-14-letter-storytelling-evidence.md` | Kept as the evidence base (N-01 … N-19). N-08's "no rewrite pass" is narrowed: a rewrite of **flagged sentences only**, followed by every check again (S8). No detector gate, no detector-targeted pass. |
| `letters.py` `_INSTRUCTIONS` and the model-emitted claim spans | Replaced (S6, S7): the writer returns plain paragraphs; code and Jev attach claims afterwards. |

## 1. Owner decisions (2026-09-28, this design's session)

1. **One engine** — requirements, research (professors, labs, papers, modules, facts about the
   university), story, writing and checking behind one entry point.
2. **Flagship Chinese model writes.** Cost is not the constraint (every candidate is under 5¢ a
   letter); quality is.
3. **Jev answers every closed judgement.** One reader per decision; no multi-model vote in
   production. Middle-confidence answers become warnings.
4. **Names, contacts, date of birth and ID numbers never reach a writer.** Placeholders; the letter
   body carries no name at all.
5. **AI policy:** write anyway (decision 6, 2026-09-14, confirmed). The student is shown the
   destination's rule, told that detection can lead to rejection, and gets the disclosure line
   where the destination allows AI with disclosure.
6. **No live similarity store.** Overlap between students' letters is measured in evaluation.
7. **No student-voice features.** No interviews for wording, no copying the student's phrasing:
   writing and speaking skills differ.
8. **Style checks included:** sentence-length variation, noun-heavy phrasing, stock phrases per
   language, and the `blader/humanizer` patterns (v3.1.0) as detect-and-repair.
9. **Reference letters** for the style checks come from the internet, vetted (§8.1).
10. **Research plans** (MEXT, GKS study plan, CSC) are last in the build order, as a guided flow
    that asks the student what they want to research.
11. **Specificity device chosen by reader** (S3.1). Professors and their recent work where the
    evidence supports it; never where the target forbids it.
12. **The engine reads the papers itself.** The student is never asked to read one.

Recorded disagreement: the owner asked for a stage that passes letters through another model to
remove any statistical watermark. It is not designed here. It is also moot for the chosen writers:
no watermark is documented for GLM, Kimi, DeepSeek or Qwen served by third-party hosts, nor for
OpenAI text (research 2026-09-28; Anthropic does watermark Claude text since 2026-08-14, and Claude
is not a writer here). Admissions detectors (Turnitin, GPTZero, Pangram) classify style; they do
not read watermarks.

## 2. The pipeline

```
target + student
  │
  S0 entry: target kind, letter required?, structure, language, budget
  S1 inputs: confirmed facts → masked; aliases; roles
  S2 requirements: LetterShape from #159 (cached per programme)
  S3 research: choose device → find evidence → verify → compress
  S4 story: one storyline per student, reader-specific angle
  S5 plan (code): paragraphs, facts, evidence, questions, word budgets
  S6 write (GLM-5.3): plain paragraphs
  S7 check: code, then Jev
  S8 repair: flagged sentences only, once; re-run S7
  S9 render + deliver: formalities, AI-policy notice, status, warnings
```

Every stage writes what it decided and why onto the draft, so a warning shown to the student can
name its cause.

### S0 Entry

- **Target kinds:** `PROGRAMME`, `FUNDER` (DAAD, Chevening, Fulbright, Türkiye Bursları…),
  `CONSORTIUM` (Erasmus Mundus). Today `ApplicationPrompt.programme` is a non-null FK, so funder
  letters cannot exist; the prompt gains a nullable programme and a funder reference.
- **Letter required?** From #159's `PageFacts.letter_required`. `NOT_REQUIRED` → no letter; the
  student is told why (Helsinki/Oxford discard unrequested documents, L-054). `UNSTATED` → write it.
- **Immigration letters** keep the existing path: confirmed facts only, no story, no research.
- **Structure:** essay, formal letter, `SHORT_ANSWER_SET` (one answer per portal question, each with
  its own cap), prescribed government form (out of scope until the research-plan flow, §9 item 8).
- **Language:** #159's `document_language`; if unstated, the programme's language of instruction;
  if that is unknown, English. A language without calibrated Jev bars (S7.4) is still written, and
  every Jev outcome in it is a warning, never a hold.
- **Budget:** per-student rate limit (existing `letter_generation`, 20/hour) and a per-letter cost
  ceiling covering search, fetch, OpenAlex, Jev and writer calls. A spent ceiling stops research
  first; writing still runs on what was found.

### S1 Inputs and privacy

- Only **confirmed** facts (`generatable_facts`). Grades are passed exactly as awarded, with scale.
- **Masking.** One seam, `mask_for_model`, replaces the student's name (all transliterations:
  Orkhan / Orxan / Орхан), e-mail, phone, address, date of birth, ID numbers and referees' names in
  every text that goes to any model, including inside fact text (a thesis co-author list, a company
  named after a family). A test asserts no identifier reaches any prompt, the same shape as
  `test_no_query_ever_carries_the_student`.
- **The letter body never contains a placeholder.** Turkish and German inflect names
  ("Orkhan'ın"), so a substituted placeholder breaks grammar. The body is first person throughout;
  the header, salutation and sign-off are filled by code at render. A placeholder in the body is a
  hold.
- **Aliases.** A fact about an institution, degree or company carries its confirmed names in each
  letter language (ADNSU / Azərbaycan Dövlət Neft və Sənaye Universiteti / Azerbaijan State Oil and
  Industry University). The entity check (S7.1) matches against aliases, not one spelling.
- **Roles.** Each experience fact carries a role on a closed scale — `observed < assisted <
  contributed < co_led < led` — classified by Jev once when the fact is confirmed, stored with the
  fact. Role inflation is detected by comparison (S7.2), never by asking "is this inflated?".
- **Hosts.** Every call carrying student data goes to a zero-data-retention endpoint:
  OpenRouter `provider: {zdr: true, only: [...], allow_fallbacks: false}`. Jev
  (`typesafe/jev-1.13`) is on OpenRouter's ZDR list.

### S2 Requirements

Consumed from #159: caps (words, characters, pages, per question), floors, approximate caps, form,
naming rule (`must / may / must_not` name a supervisor), language, `letter_required`, `track`
(`research / taught`), portfolio-led, topics and questions the letter must address, include items,
student actions (sign, upload name). Cached per programme; re-read when the page changes.

Cases:
- **An abstained value** (below #159's bar) → the country × reader default row applies and the
  student sees the page sentence we could not settle.
- **Conflicting pages** → #159's safer value, with every side noted.
- **Page says nothing** → the default row alone. This closes today's defect where page-read and
  extracted prompts store `archetypes=[]` and produce an empty, blocked letter.
- **Conditional rules** ("applicants from non-EU countries…") → notes, never applied (#159 C3).

### S3 Research

#### 3.1 Choose the device first (code)

Inputs: target kind, `track`, naming rule, funder rules, structure, discipline family (from the
programme's field), and whether a `CONFIRMED_SUPERVISOR` fact exists.

| Reader / programme | Primary device | Secondary (only on a strong match) | Never |
|---|---|---|---|
| Research-track, faculty readers (US research MS/PhD, UK MRes/DPhil, doctoral training) | 2–3 professors in the admitting unit, each with one recent-work phrase | — | a single name unless a confirmed supervisor exists |
| Taught master's, STEM / economics / social science / policy | 1–2 modules, a specialisation or a thesis theme | one professor or lab whose work matches the student's thesis or project | course lists |
| Taught master's with envisioned thesis projects asked (TU Delft MoT) | thesis-project themes tied to named groups | the group's professor | — |
| MBA / management | career goal → 1–3 programme resources → contribution | — | professors |
| Arts, design, architecture | programme approach vs the student's own methods; studio | — | staff names |
| Funder (Chevening, DAAD, Türkiye Bursları, Stipendium Hungaricum) | funder's stated goals + first-choice course modules + home-country benefit | — | flattery; for **Fulbright, any university or faculty name** |
| MEXT / GKS / CSC | research theme (the plan is a later document type) | — | supervisor names in the letter |
| Page says `must_not` name staff | modules / groups without persons | — | persons |
| Law, public health, medicine | taught-master rule (modules, clinics, practicum) | — | — (unverified rows; defaults) |

Sources for the table: `docs/research/2026-09-28-letter-engine/specificity.md`.

The fit part is one paragraph, about a fifth of the letter; two sentences at most per professor.

#### 3.2 Modules, tracks, thesis themes, facilities, partners

The existing `research_fit` ladder (D1) searches the institution's own domain (Exa, profile-free
query), fetches through `fetch_page`, splits sentences in code (`split.page_sentences`). Change:
curriculum and module-handbook pages are added as targets (they are often PDFs; the fetch ladder
already parses PDFs). Jev classifies each sentence (S3.6). A module sentence is used only when the
programme page or its handbook states it; a module absent from the current curriculum is never
named.

#### 3.3 Professors and labs

Candidates come from two directions and must meet on the university's own site:

1. **Site first:** the ladder's `named_person` / `research_group` sentences on the institution's
   domain.
2. **Literature first:** OpenAlex works filtered by the institution's ROR and the student's
   profile-free topic phrase, last three years (`/works?filter=authorships.institutions.ror:…,
   from_publication_date:…,title_and_abstract.search:…`). Authors affiliated with the institution
   are candidates; the last or corresponding author is preferred as the group lead.

A candidate is **confirmed** only when all of these hold:
- a page on the institution's domain names the person (name matched after Unicode folding,
  diacritics, initials and transliteration; Jev Noul "Is the person on this page the author
  `<name>`?" when the match is not exact);
- the page places them in the **admitting unit** of the programme (Jev Noul over the page's
  affiliation sentence);
- no status marker says emeritus, retired, deceased, on leave, or not taking students (a
  multilingual code list, then a Jev Noul on the page);
- the page was fetched within 30 days (re-checked at render, D9).

Unconfirmed → the group or theme is named instead of the person. Research-track letters name 2–3
confirmed people from **one** subfield (OpenAlex topic ids must share a subfield); two names far
apart read as unfocused.

#### 3.4 Papers — the engine reads them

- **Which:** works by the confirmed person in the last 3 years, type article / conference paper /
  preprint with a year; excluded: retracted (`is_retracted`), editorials, errata, theses, datasets.
- **What is read:** title and abstract (OpenAlex's inverted index, rebuilt by code); for
  open-access works, the conclusion section from `best_oa_location` through `fetch_page`. Never
  the whole paper into a model.
- **Selection:** Jev Noul per paper, "Is this paper about `<topic phrase>`?", over title + abstract.
  The most recent paper above the bar wins; ties go to the one whose abstract shares the most
  OpenAlex topics with the student's anchor.
- **Compression:** code splits the abstract into sentences and proposes result spans — clauses after
  *we show / we propose / we find / we demonstrate / results indicate* and the noun phrases of the
  title. Jev picks one (Choice, with `none`). The phrase is at most 15 words and is a verbatim
  substring of the title or abstract.
- **Bundle handed to the writer** (per professor): `name` as the site spells it, `unit`,
  `work_phrase` (verbatim), `paper_year`, `paper_title_short` (≤ 8 words, verbatim prefix),
  `source_url`, `connects_to` (one student fact id or storyline anchor), `sentence_budget: 2`.
- **Attribution wording:** "work by Professor X's group on …" unless the person is first or last
  author; never "her paper" for a middle author.
- **Citation:** where #159 records a citation rule (TUM: sources must be cited as quotations or the
  letter risks a plagiarism finding), the render appends a short reference line.
- **Non-English letters:** names stay verbatim; the writer translates `work_phrase`; Jev checks the
  translation carries the phrase (Noul), below the bar → warning.

#### 3.5 Funder alignment and home-country benefit

Funder goals come from the funder's own published criteria pages, read like programme pages. The
home-country benefit comes only from the student's DECLARED plan; a producer of sourced
national-strategy facts stays unbuilt (research-fit §9), so the letter states the plan, not
statistics about the country.

#### 3.6 Jev in research (replaces D6's three-reading judge)

Per sentence (state = the sentence and its heading; never the whole page, which Jev does not treat
as hostile): kind Choice (`research_group, named_person, module_or_track, facility,
industry_partner, funder_goal, none`); relevance Noul "Is this sentence about `<topic phrase>`?".
Code keeps the entity only when it is a verbatim substring (`entity_in_sentence`, existing). This
replaces 28 frontier calls per letter with a few hundred Jev questions (well under 1¢).

#### 3.7 Research cases

- OpenAlex merges or splits authors; affiliations lag moves → the site confirmation is mandatory.
- Topic too broad (rung 4, interest only) → modules and groups, no papers.
- Nothing found → the fit paragraph is built from the student's stated need and flagged "not
  specific to this programme"; the letter is not held (D11). Today's `GENERIC_PARAGRAPH` gate
  becomes a warning when research returned nothing, closing the contradiction that blocks every
  letter.
- Research facts are filtered to **this** programme (`research_fit_inputs`, exists, unused), so a
  letter never cites another programme's lab.
- Consortia: the fit paragraph may name the mobility track and partner universities the consortium
  page lists; professors only at the admitting (coordinating) unit.
- Cost: ≤ 3 site searches, the fetch budget from `SweepBudget`, ≤ 5 OpenAlex list calls
  ($0.001 each, measured 2026-09-28; the free allowance is $0.10/day without a key, so production
  needs a key), Jev under 0.5¢.

### S4 Story

- One storyline per student (`propose_storylines` → deterministic `choose_storyline`), stored on the
  `CORE_NARRATIVE` draft and reused by every letter, so eight letters tell one story.
- Reader-specific **angle** via `theme_kind_for` (funder → plan/impact; committee → fit and
  readiness); the anchors and the plan stay the same across letters.
- `recent_theme_texts` excludes the student's own earlier themes (today it pushes one student's
  stories apart).
- Setback turn only when a real negative fact exists (N-05).
- A fact changed or withdrawn → the storyline is re-chosen and every letter built on it is marked
  stale.
- Fewer than three confirmed anchors → the letter is written, and the student is told it will be
  generic until more facts are added.

### S5 Plan (code only)

- Archetypes from the country × reader default row, overlaid with #159's questions and topics.
- Per paragraph: archetype, purpose, fact ids, evidence ids, questions answered, word budget.
- Budgets sum to the target inside every cap and above every floor; characters are counted with
  spaces where the portal counts them; the strictest cap wins; a page cap converts to words with the
  render's font metrics.
- A cap too small for the archetypes → drop by N-14's priority (commentary first; method,
  consequence and gap stay).
- `SHORT_ANSWER_SET`: one plan per question, the question's own text and cap included (today the
  questions never reach the model).
- Formal letter vs essay from #159's form; salutation, closing, header and place-date line from
  `letter-formalities.csv` at render; a place-date line is written only when a declared city exists.

### S6 Write

- **Writer:** `z-ai/glm-5.3`, effort `low`, vendor-default sampling, fp8 hosts on the ZDR list
  (Parasail, Sail Research). Second: `moonshotai/kimi-k3` on Fireworks/Together (not Moonshot's
  own endpoint, whose content filter rejects China-critical text). Fallback: `deepseek/deepseek-
  v4-pro-0813`, thinking off, temperature ≈1.0. `qwen3.8-max` excluded: its only host is not ZDR.
  Final choice by the bake-off (§8.3); versions pinned.
- **Sensitive routing:** a multilingual code list plus a Jev Noul over the plan ("Does this letter
  concern Taiwan, Tibet, Xinjiang/Uyghurs, Hong Kong or human rights?") routes to a non-Chinese
  flagship (OpenAI, ZDR endpoint). A refusal, a content-filter 400, an empty answer, or a planned
  point missing after writing (S7.2) re-runs on that route.
- **Prompt, in this order:** a short system message (role; voice described positively — plain,
  specific, first person, evidence before interpretation; at most 10 banned phrases for the letter
  language; no markdown); the plan, facts and evidence as tagged data, labelled as data; the task
  last ("write N paragraphs in `<language>`, about W words each"). Plain paragraphs separated by
  blank lines — no JSON, no spans. Two or three short rotated excerpts of vetted human letters as
  style examples, never full letters; overlap with them is checked in code.
- **Output handling:** markdown stripped; Chinese characters in a non-CJK letter, the wrong
  language, a paragraph count off, or length outside ±20% → one retry with the measured numbers;
  still wrong → hold with the reason.
- **Outages:** another pinned host of the same model; then the next tested model; never an untested
  one. Host and model are logged per letter, with reasoning tokens.

### S7 Check

#### 7.1 Code (free, certain)

- Every capitalised entity, number, date and institution in the letter matches a fact, an alias or
  an evidence bundle; anything else is an unsupported entity.
- Wrong institution: names of the student's other targets appear nowhere; Fulbright letters carry no
  university or faculty name.
- Language per sentence, script, placeholders, caps and floors, paragraph count, first person
  (per-language pronoun lists).
- Style: stock phrases per language counted by word root (English: Kobak et al.'s excess-vocabulary
  list; de/fr/ru/tr: `tjuzek/ai-34-languages` as a starting list); humanizer patterns code can see
  (semicolons, dashes per 300 words, "not X but Y", triads, trailing -ing clauses, one-line
  closers); stylometry — sentence-length variation, nominalisation rate, participial-clause rate,
  lexical diversity (MTLD) — against the human reference corpus of that language (§8.1). A
  stylometry flag needs two features outside the human 10th–90th percentile; no absolute threshold
  is used because none is published.
- Tools: spaCy for en/de/fr/ru; TurkicNLP (Apache-2.0) for tr/az; lexical diversity on lemmas.
  Both are new dependencies and go through the artifact gate in the plan.

#### 7.2 Jev (closed questions, one condition each, high means yes)

State is filtered to what the question needs: the sentence, its paragraph, and only the facts or
evidence the plan attached to that paragraph.

| Question | Type | Applies to |
|---|---|---|
| What kind of statement is this? `applicant_fact, applicant_plan_or_interest, interpretation, programme_fact, other` | Choice | every sentence |
| Does this sentence state something about the applicant's past that none of the listed facts states? | Noul | `applicant_fact` |
| What role does this sentence give the applicant? (closed scale + `none`) | Choice | `applicant_fact` about experience; compared in code with the fact's stored role |
| Is this sentence's claim about the programme stated in the evidence excerpt? | Noul | `programme_fact` |
| Does the letter answer `<question / topic>`? | Noul | each #159 question and topic, over the paragraphs the plan assigned |
| Does paragraph k mention `<planned point>`? | Noul | each planned point (catches softening and omissions) |
| Could this paragraph be sent unchanged to another university's programme in the same field? | Noul | the fit paragraph (N-15) |
| Does this sentence praise the university, its ranking or its city? | Noul | every sentence |
| Humanizer patterns code cannot see (significance inflation, vague attribution, promotional register) | Noul, one per pattern | every sentence, the six strongest patterns only |

Interpretation and plans are never checked for truth (N-04); only the facts they presuppose are.

#### 7.3 Outcomes

| Finding | Outcome |
|---|---|
| unsupported entity, invented applicant fact, role inflation, wrong institution, placeholder in body, cap or language wrong | repair (S8); still failing → **hold** |
| unanswered question, planned point missing | repair; still missing → warning (softening → non-Chinese re-run first) |
| generic fit paragraph, flattery, style, stylometry, humanizer pattern | repair once; still present → warning |
| any Jev answer in the uncertain band | warning, no repair |
| any Jev answer in an uncalibrated language | warning |

#### 7.4 Calibration

Each Jev question has its own bar per wording and per language, set on ≥ 200 labelled sentences.
Labels are built by two strong models and a referee on disagreement (owner decision: measurement by
models, not people). Until a language has its set, its Jev outcomes are warnings. Examples used in
Jev criteria are never also test rows (the 48-row CV lesson).

### S8 Repair

- One round. Each flagged sentence is rewritten by the same writer with its neighbours as context,
  the failed check in plain words, and the facts it may use. Only that sentence changes.
- A rewrite may introduce no new entity (code check).
- Then **every** S7 check runs again on the whole letter, including length.
- Anything still in the hold row → the draft is stored with status `BLOCKED` and its reasons (today
  a blocked draft is saved as an ordinary `DRAFT`).

### S9 Render and deliver

- Formalities by code; the reference line where a citation rule applies; the DAAD-style disclosure
  line where the destination allows AI with disclosure.
- The AI-policy notice: the destination's rule in plain words, that detection can lead to rejection,
  and that the final text is the student's responsibility.
- Caps re-checked on the rendered PDF (pages).
- The student sees the draft, each programme fact with its source link, and every warning with its
  cause.
- **Student edits** re-run S7; every outcome on the student's own words is a warning.
- **Regeneration** supersedes the previous draft and is rate-limited.

## 3. Pack build

All letters of a student's pack share one storyline, are generated in parallel, and draw their plan
statements from the same storyline plan, so two letters cannot state different goals. Research runs
per target; its facts never cross targets.

## 4. Failure handling

| Failure | Behaviour |
|---|---|
| #159 read failed or abstained | default row + visible note |
| search, fetch or OpenAlex outage | research returns nothing; fit paragraph flagged, not held; logged with the failing party |
| Jev outage | letter written; every Jev check recorded "not checked" and shown; no hold from an unrun check |
| writer outage | same model on another pinned host → next tested model → the letter waits; never an untested model |
| Chinese-host refusal or softening | non-Chinese route |
| budget spent | research stops; writing continues on what exists |
| requirement check cannot run | "not checked" warning (today it silently passes) |
| SDK transport error in any check | caught, logged, "not checked" (today it crashes the command after the letter was paid for) |

## 5. Cost per letter (estimates, to be measured in the bake-off)

| Stage | Cost |
|---|---|
| Requirements (#159, cached per programme) | ≈ 0.1¢ amortised |
| Research: 3 searches, page fetches, ≤ 5 OpenAlex calls, Jev | ≈ 2–4¢ |
| Story (once per student) | ≈ 2¢, amortised over the pack |
| Writing, GLM-5.3 (6k in / 2k out, plus thinking) | ≈ 1.5–3¢ |
| Jev checks (≈ 250 questions) | < 0.5¢ |
| Repair | ≈ 0.5–1¢ |
| **Total** | **≈ 5–10¢** |

Research, not writing, is the largest line; Jev replacing the three-reading judge is the largest
saving.

## 6. Privacy, terms, law

- Student data only to ZDR endpoints; OpenRouter's DPA is an open item for the owner.
- Research queries carry a topic phrase only, never the student (Exa §1.2(c), Tavily §9.2).
- Professor names are third-party personal data in tenant rows (research-fit D14: verbatim, sourced,
  takedown command exists).
- **EU AI Act Article 50(2)** (applies from 2026-08-02; systems already on the market by
  2026-12-02): a company offering a letter generator under its own name whose output is used in the
  EU is likely a "provider" that must mark generated text in a machine-readable way; the
  "assistive standard editing" exception does not cover drafting whole letters (Commission
  Guidelines C(2026) 5054, paras 10, 74–75, 90–92). **A question for the owner's lawyer before EU
  launch.**

## 7. Deliberately not built

- A watermark-removal or detector-targeted pass (section 1).
- A live cross-student similarity store (owner decision 6).
- Student-voice features: interviews for wording, phrase reuse, style cloning (owner decision 7).
- Contacting professors, or claiming a professor is taking students (N-19).
- Sourced home-country statistics (S3.5).
- Research plans for MEXT/GKS/CSC until the guided flow (§9 item 8).

## 8. Measurement

### 8.1 Human reference corpus

Letters published by a university, funder or its official channel as a good example, or shown with
the writer's admission; written before 2023 or explicitly human-written; consultancy-written
samples excluded. Target 30–50 per language for en, de, fr, tr, ru; Azerbaijani will be thin, so
its stylometry outcomes stay warnings. Used only to compute feature percentiles; never shipped,
never shown to a writer beyond the rotated short excerpts.

### 8.2 Golden set

About 100 cases: ≥ 30 student profiles (the owner's own CV and thesis are approved test material;
the rest synthetic) × target types (research-track, taught STEM, taught social science, MBA, funder,
Fulbright, `SHORT_ANSWER_SET`, non-English). Every production failure joins the pinned regression
set.

### 8.3 Writer bake-off (gate before enabling)

GLM-5.3, Kimi K3, DeepSeek V4 Pro and an OpenAI flagship as control, on the golden set. Measured:
S7 pass rates, holds, stock-phrase rate, stylometry percentiles, length adherence, overlap between
different students' letters, cost and reasoning tokens, and a pairwise preference judged by a
different model family with order swapped, anchored to a small set of human-ranked pairs.

### 8.4 Production canary

Code and Jev checks on 100%; a cross-family pairwise judge on 2–5% of letters and on every repaired
letter.

## 9. Build order (each its own implementation plan)

Depends on #158 and #159 merging.

1. **Letter gap fixes** already on this branch (seven commits) → their own PR.
2. **Model seam:** one OpenRouter chat client for writers (ZDR routing, pinned hosts, logging,
   refusal handling), the masking seam and its test, Jev calls through #159's `decisions.ask`.
3. **Plan, write, code checks, repair** — `letters.py` restructured: plain-paragraph writer, the
   S5 planner, S7.1, S8, `BLOCKED` status, the empty-archetype and short-answer fixes, funder-level
   prompts.
4. **Jev checks and calibration sets** (S7.2–7.4), fact roles at confirmation.
5. **Research:** device selection, `research_fit` on Jev, module pages, OpenAlex professors and
   papers, confirmation on the site.
6. **Measurement:** reference corpus, golden set, bake-off; the writer is enabled only after it
   passes.
7. **Pack wiring:** one storyline per student, pack build, edit re-checks, AI-policy notice.
8. **Research plans** (MEXT, GKS study plan, CSC) as a guided flow.

## 10. Open questions for the owner

1. EU AI Act Article 50 marking (section 6) — lawyer.
2. OpenRouter DPA and the list of ZDR hosts carrying student data.
3. Which OpenAI flagship takes the sensitive-topic route (measured in the bake-off).
