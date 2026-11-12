# Letter story without questions, and research fit that is actually used

**Date:** 2026-10-14 (revision 2, after the bird's-eye review)
**Status:** design, awaiting owner review
**Branch:** `claude/letter-story-spec`, cut from `master` 05b3ddb2 (docs only). The master letter
design it amends travels with it, cherry-picked from `claude/letter-gap-fixes`, which is three
weeks behind `master`.
**Amends:** `docs/superpowers/specs/2026-09-28-one-letter-engine-design.md` (the master letter design)
**Evidence:** `docs/research/2026-10-14-letter-story/`:
- `2026-10-12-human-admissions-writing-literature.md` — what makes a letter read as human
- `2026-10-14-letter-fit-length-openings.md` — why-this-programme fallback, thin profiles, openings
- `2026-10-14-professor-and-paper-discovery.md` — OpenAlex reliability, national indexes, module leaders
- `2026-10-14-turkish-grammar-and-stock-word-lists.md` — Turkish/Azerbaijani checks, stock words
- `2026-10-14-story-fingerprint-embeddings.md` — fingerprint model, thresholds, pgvector
- `2026-10-14-letter-languages-coverage.md` — 40 letter languages and their tooling
- `2026-10-14-names-and-module-handbooks.md` — cross-script names, ORCID, handbook size

The engine builds each student's motivation story by itself, never asking the student a question,
from a rotated catalogue of story shapes and openings, and compares stories by idea rather than by
word — inside the agency and across agencies for the same target. It also makes the research-fit
engine (professors, labs, modules, papers) part of letter generation for the first time.

## 0. What governs

| Master section | What this amendment does |
|---|---|
| §1 decision 7 "No student-voice features" | Kept and extended: the student is asked nothing at all. `TODO.md` approach A's three questions are dropped. |
| §2 S3.3–S3.4 professors and papers | Refined in §6. |
| §2 S3.7 research cases | "Nothing found" replaced by §5 (programme-feature fallback). |
| §2 S4 story | Replaced by §4. |
| §2 S7 checks | Extended by §3 (invention line), §8 (languages, style, grammar). |
| §2 S9 student edits | Extended by §9 (edit warning). |
| §6 privacy | Extended by §10. |
| `TODO.md` (2026-10-12, `~/agent-workspace/elmify-runs/motivation-letter/`) | Items 3–5 answered here; item 6 (permission records) dropped by the owner (§11); the detector study is not designed (§12). |

Rules that bind every section, from `master`'s `.claude/rules/`: `row-level-security.md` (the
`runtime_web` / `runtime_engine` split and the crossing-tenants rule), `llm-ai-security.md` (data
labelled as data, schema-constrained output, a `rate_limited()` call on every model-calling path),
`derived-data-and-erasure.md` (derived data follows erasure), `web-fetching.md` (every page fetch
goes through `apps/research/fetch.fetch_page`).

## 1. Owner decisions (2026-10-14)

1. No questions to the student. The story is the engine's; the student sees it in the letter and may
   edit.
2. Rotated story shapes and openings; ideas compared, not words — inside the agency and across
   agencies. The cross-agency check is built now.
3. The engine invents the motivation. It never contradicts a confirmed fact and never invents a job,
   project, internship, award or publication (§3).
4. Edits are never blocked; an edit that weakens the letter gets a warning (§9).
5. Why-this-programme fallback, thin profiles, openings by culture follow the research (§5, §4.6, §4.3).
6. Professors and papers refined for the best letter (§6). **ORCID may be used** (owner: Elmify does
   not earn from professor data; see §6.1 for the clause).
7. **Long PDFs** (module handbooks) are read whole through the OCR seam and then extracted, not
   parsed per page by the fetch vendor (§6.4).
8. **Story fingerprints use OpenAI `text-embedding-3-small`** at 512 dimensions; the OpenAI account
   has zero-data-retention approval.
9. Agencies never see another agency's students. Elmify staff access is a separate design (§10.3).
10. Review findings 1–27 accepted; AI-use permission records dropped (§11).

## 2. What exists today (measured on `master`, 2026-10-14)

- **The story code is unused.** `storyline.propose_storylines`, `choose_storyline` and
  `recent_theme_texts` have no caller on any branch; `manage.py draft_letter` passes no storyline.
- **Research fit is unused.** `research_fit.service.propose_research_fit` has no caller on any
  branch; `recheck_research_fit` is the default of `letter_approval.mark_letter_ready`, which has no
  caller either.
- **Story comparison is English-only and only breaks ties** (`storyline._TOKEN = [a-z]{3,}`; Russian
  yields no tokens, "Türkiye" yields "rkiye"); the pool is the agency's 20 newest `CORE_NARRATIVE`
  drafts including the student's own, with no programme filter.
- **The why-this-programme gate accepts an unverified link**: a `SOURCED` claim with a URL and no
  input id is `UNCERTAIN`, not blocked, and satisfies `check_generic_paragraph`.
- **Research rows are not filtered by programme** (`draft_letter` passes every `NarrativeInput`;
  `research_fit_inputs` is unused).
- **`letter_gates._SENTENCE_SPLIT` is `(?<=[.!?])\s+`** (line 44): Chinese and Japanese letters are
  never split (`。` takes no space), and Armenian `։`, Arabic `؟` and Greek `;` are missed.
  **`script_of` knows only Korean, Japanese and Chinese** (line 304): Russian, Greek, Arabic,
  Armenian and Georgian letters are treated as Latin, so a Russian letter that came back in English
  passes the script check.
- **Confirmed facts carry part of what story shapes need** (codebase research R7): employment
  dates, thesis titles, publications (first author, status), `EXPERIENCE.unpaid`, CEFR levels and
  repository-derived skills are code-decidable; job progression, gap reasons outside the eight
  canned answers, teaching work and CV-ingested exchanges need a model; **transcript courses and
  grades never reach `VerifiedFact`** (`profile_bridge._education_payload` drops them); "missing
  prerequisite" exists nowhere; the home country lives in the profile, not the ledger.
- **`DocumentDraft` has no admissions cycle**; the cycle is passed at generation and not stored.
- **All direct-to-student customers share one tenant** (`PlatformAgency`).
- **`runtime_web` holds no grant on the catalogue or on fetch telemetry** (`row-level-security.md`):
  any web path that reads `Program`, `ProgramStatement`, `ApplicationPrompt` or fetches a page fails
  with `permission denied` in production and passes every test.

## 3. The invention line

**May invent (motivation):** a reason, an interest, what drew the student to a field, how two real
facts connect, a lesson drawn from a real fact, a feeling about a real fact, a plan, a goal, what the
student hopes to contribute.

**May not:**
- contradict a confirmed fact: date, duration, grade, degree, institution, employer, job title, role
  (member vs lead), kind of work (coursework vs research);
- invent a credential or activity: job, project, internship, award, scholarship, publication,
  certificate, research position;
- invent a personal life event or a person (§12).

**Enforcement, in two tiers:**
- **Provable by code → hold, in every language.** An entity, number, date or institution that
  matches no fact; an institution or employer absent from the ledger; a credential noun attached to
  an unledgered entity; a duration contradicting the fact's dates (duration words come from a
  per-language list, §8.1).
- **Judged by a model → hold where that question is calibrated for the letter's language, warning
  elsewhere** (master S7.3–7.4). The master's S7.2 question "Does this sentence state something
  about the applicant's past that none of the listed facts states?" also runs on interpretive and
  aspirational sentences; role and kind-of-work stretch use the S7.2 role question.
- Story anchors stay fact ids, never text.

## 4. The story, without questions

### 4.1 Shapes

| Shape | Needs (confirmed) | Decided by | Readers |
|---|---|---|---|
| problem met at work | EXPERIENCE | code | faculty, funder |
| setback turned | TIMELINE gap with a statement, or `gap-interview:unfinished-programme` | code; reason by model unless canned | all |
| question a course left open | transcript course with a grade (§4.1.1) | code | faculty, taught |
| something built | RESEARCH with `source_ref` `repo:` or project outcome | code | faculty, taught |
| thesis or final project continued | `thesis_title` | code | faculty, taught |
| two fields meet | two EDUCATION/EXPERIENCE facts in different fields | model | all |
| need at home | profile `nationality`/`country_of_residence` + an EXPERIENCE or project in that country | code | funder, taught |
| a result that surprised | RESEARCH `outcomes` or PUBLICATION | code | faculty |
| a method carried across | SKILL used in one domain, programme in another | model | faculty, taught |
| teaching or volunteering | EXPERIENCE `unpaid`, or teaching by model | code / model | all |
| language and mobility | LANGUAGE + exchange (`gap-interview:exchange-programme`, else model) | code / model | funder, taught |
| career step | two EXPERIENCE facts with progression | dates by code, seniority by model | MBA, funder |

"A skill gap found" is dropped: nothing records a missing prerequisite. Fit is decided in two steps:
code first, then **one cheap classification per fact** (the master's Jev checker) for the "model"
column, cached on the fact so it runs once per fact, not per letter.

**4.1.1 Transcript courses become facts.** Accepted transcript courses (`TranscriptReading.record`,
`{title, ects, grade, in_progress}`) are bridged into the ledger as confirmed EDUCATION course
entries, graded in their own scale, never converted (`derived-data-and-erasure.md`). "Best-graded
relevant course" is ranked within one transcript's own scale only. By `cv-and-letters.md` ("One
ledger, every consumer") the course entries reach every ledger consumer in the same change — CV
generation and rendering, skill tailoring, portal autofill, `europass.europass_payload` — each
deciding how it uses them; none is excluded without an owner decision. That makes this bridge its
own plan, ahead of the story plan.

### 4.2 Choosing

1. Code computes the fitting shapes for this student.
2. Usage is counted per shape over the pools of **every target the student has** — programmes and
   funders (§4.4).
3. The least-used fitting shape across those pools wins; ties break by a random draw seeded on the
   student id. ≥ 3 anchors from ≥ 2 categories is a floor, not the first sort key.
4. `propose_storylines` proposes up to three stories within that shape.
5. Each candidate's fingerprint (§4.4) is compared with each target's pool and the cross-agency
   function (§10.2). Too close for any target → the next fitting shape. If only one shape fits, it
   is kept and opening and anchor order vary; the outcome records "single shape".
6. **A target added later is checked against the existing story**; too close there → that letter
   varies its opening and angle and records it; the story itself is not re-chosen while any letter
   built on it is submitted (§4.5).

One story per student, reused by every letter. The core (shape, anchors, turn, gap, future) is
reader-neutral; each letter applies its reader's angle (`theme_kind_for`) and its own opening.

### 4.3 Openings

Chosen per letter, tagged by culture, rotated like shapes:

| Opening | Cultures |
|---|---|
| plain status line: who I am now, what I apply for, the main reason | all |
| the question the student wants to answer | all |
| a result or number from a fact | all |
| the plan | all |
| the programme feature first | all |
| a real moment from a fact (scene) | **English letters to UK readers only** (Sussex, Loughborough); US until a US source confirms it |

German, French, Russian and Turkish letters rotate among plain openings only (HSE, Campus France,
Lyon 3, Özyeğin, TU Dresden). Every other language uses the plain set by default.

### 4.4 Pools and fingerprints

- **Pool key: the target** (programme or funder) **and the admissions cycle.** `DocumentDraft` gains
  a `cycle` field storing `ApplicationPrompt.cycle` verbatim: pools compare drafts with drafts, and
  "2027" cannot be mapped to `YYYY-YYYY` without guessing.
- **Inside the agency:** this agency's drafts for the same target and cycle, plus its stories from
  the last 90 days counted by shape; the student's own and superseded drafts excluded. Direct
  students share one tenant, so they form one pool.
- **Fingerprint:** `text-embedding-3-small`, `dimensions=512`, over an English summary (shape +
  theme + gap + future) written with no names or institutions. Stored unit-length inside the
  draft's `content` with `{model, dimensions}`; fingerprints of different `{model, dimensions}` are
  never compared. Compared with `pgvector` (available on RDS for PostgreSQL 17). Erasure removes it
  with the draft; no new table, so no `Pseudonym` link is needed.
- **Threshold:** provisional (0.85) until recalibrated on the golden set (master §8.2); no published
  threshold exists for this model.
- **Lock:** the model calls and embeddings run with no lock held; only the final step — re-read the
  pool, compare, reserve the shape on the draft — runs under a transaction-scoped advisory lock on
  (tenant, target, cycle). Two agencies reserving at the same moment can both pass the cross-agency
  check; that race is accepted and recorded, not designed away.
- **Outage:** if the embeddings call fails, the shape still rotates by usage counts, the idea
  comparison is skipped, and the outcome logs the vendor and its message.

### 4.5 Regeneration, edits and submitted letters

- Regenerate keeps the story and rewrites the text; "different story" excludes the previous shape.
- **Either one asks before discarding the student's own edits** and keeps the edited version as a
  superseded draft.
- A changed or withdrawn fact re-chooses the story and marks unsubmitted letters built on it stale.
  **A letter whose `Application` is submitted is never marked stale or regenerated.**
- A student's edit that changes the story becomes their story; `check_storyline_drift` is a warning
  on student-edited text.

### 4.6 Thin profiles and no facts

- **Fewer than three anchors:** the fitting set is usually "question a course left open" (§4.1.1),
  "thesis or final project continued", "something built", "teaching or volunteering". Length: the
  lower end of the target's expected range, dense, never under a published minimum (programme
  minimums come from #159's `LetterShape`).
- **No confirmed facts at all:** no story. The letter is short: the programme feature (§5) and the
  student's plan, marked "built without your facts — add your CV to strengthen it".
  `check_generic_paragraph` treats this state as a warning, as it does when research returned
  nothing.

## 5. Why this programme

Device order (master S3.1): professors/labs where the reader wants them, then a module, track or
thesis theme, then **one verifiable programme feature plus the student's own reason** — a course,
specialisation, internship or placement, thesis option, or where graduates go — connected to the
student's past and plan. Never rankings, prestige, the city, or the page's self-description
restated (Göttingen, LSE, Imperial, Sussex, Utrecht, HSE, Özyeğin); this also settles MIT vs
Göttingen.

**Where features come from.** `ProgramStatement` holds admission kinds only (`COMPETENCY`,
`DOCUMENT`, `FORMAT`, `LANGUAGE`, `OTHER`) and the reader keeps admission sections only, so features
need their own read: the research-fit worker reads the programme page and its curriculum/module
pages for sentences naming a course, track, placement, thesis option or outcome, keeps each as a
verbatim substring (`classify.entity_in_sentence`), and writes it as a `NarrativeInput` of kind
`RESEARCH_FIT` with `provenance.kind = programme_feature`. The verifier's existing `SOURCED` path
then covers it with no new claim kind.

**Gate change:** only a `SOURCED` claim citing a verified input satisfies `check_generic_paragraph`
for `WHY_PROGRAMME`; a URL without an input no longer counts. When nothing was found (page
unreadable, no page), the paragraph is written from the student's stated need, flagged "not
specific to this programme", and the gate is a warning (master D11).

## 6. Professors, labs and papers (refines master S3.3–S3.4)

### 6.1 Finding and confirming people

Sources, which must meet on the university's own site:
1. the department's staff pages;
2. OpenAlex: works by the institution's ROR, last three years, `search.title_and_abstract=` (the
   `title_and_abstract.search` filter is deprecated), narrowed with `raw_affiliation_strings.search`
   where the department has no ROR;
3. for taught master's, the **module leader** (§6.4);
4. **ORCID** public API for other names and current employment, as a second witness. Owner decision:
   allowed. The clause reads "you may not make use of the public APIs in connection with any
   revenue-generating product or service"; ORCID sells a Member API for that case. Recorded, not
   re-litigated. Coverage is thin (2.9% of records carry other names; 4.7–11.5% at Tokyo, MSU, SNU).

**Confirmation** (master S3.3 rules stand: on-site, admitting unit, no emeritus/retired/leave marker,
fetched within 30 days):
- Prefer the department's **English staff page** with romanised names (Tokyo, SNU, HSE have one;
  MSU's computing faculty does not).
- Where only native script exists: match OpenAlex `display_name_alternatives` (native forms present
  for 7/10 Russian and Kazakh authors, 3/10 Japanese and Greek, 1/10 Chinese, 0/10 Korean in 10-author
  samples), then ORCID other names.
- **Transliteration only proposes**, never confirms (`iuliia`, `pypinyin`, `cutlet`, `koroman`,
  `anyascii` — permissive licences; `pykakasi`, `Unidecode` are GPL and not used). Korean names are
  spelled personally ("Yi", "Hur").
- **Group lead:** prefer `authorships.is_corresponding`; no last-author rule in mathematics,
  economics and high-energy physics.
- OpenAlex alone first; national indexes (KAKEN/CiNii, KCI, TR Dizin, HAL) only after a measured
  miss.

### 6.2 Choosing the paper

- The confirmed person's articles, conference papers and preprints, last three years, not retracted.
- **Relevance first, recency second**, judged against several student anchors (thesis, best-graded
  relevant courses, projects, repositories, publications).
- **What is read:** the OpenAlex abstract; when missing (34% of Elsevier 2024 articles have one,
  measured 2026-10-14; about half of Springer Nature's), OpenAlex's cached GROBID full text for
  open-access works, else the publisher landing page through `fetch_page`, else the paper is
  skipped. Never a title alone; Crossref is not a fallback.
- Phrase extraction, the writer bundle, attribution wording and citation stay as in master S3.4.

### 6.3 Never

Claiming a meeting; saying a professor is taking students (N-19); naming a person marked emeritus,
retired, deceased or on leave; naming any person where the page forbids naming (`shape.naming` is
passed into research fit, so `named_person` candidates are not proposed there).

### 6.4 Module leaders and long PDFs

- Per-module web pages first where a university publishes them (TUM names "Responsible for the
  module" per module — to be confirmed by one test fetch in the plan; the citations for it did not
  re-verify because the pages are generated on request).
- **Long PDFs** (KIT Informatics master's handbook 1,172 pages, TUM Information Engineering 556,
  RWTH 123): fetched raw through `fetch_page` with no vendor parsing (one credit flat), then read
  whole through the existing OCR seam (`apps/documents/ocr.py`: the sandboxed inventory reads text
  layers; Azure Document Intelligence reads scanned pages), then one schema-constrained extraction
  pass pulls module title, responsible person and content, each kept only as a verbatim substring
  of the page text. The OCR seam today takes an uploaded `DocumentVersion`; it gains a fetched-file
  entry point, still running in the sandboxed parser, because a third-party PDF is untrusted bytes.
- The extracted handbook is cached per URL and digest; a changed digest re-reads it.

### 6.5 Third-party personal data

Professors' and module leaders' names, units and work phrases are third-party personal data in
tenant rows (master §6, research-fit D14). `manage.py research_fit_takedown` covers every row that
carries a person: research-fit rows, professor bundles and module-leader rows.

## 7. Research fit: wiring and fixes

1. **Wire it, in the worker:** story → research fit per target → `generate_letter` with
   `research_fit_inputs(student, programme)` → `mark_letter_ready`. One plan.
2. **Behind a switch, off by default,** until the master's S3.6 rebuild replaces the three-reading
   judge (up to 28 model calls per letter today). The §7.4–7.8 fixes and §6 land in that rebuild (the §7.3 programme filter is plan 1),
   not on the old judge.
3. **Filter by programme** wherever research rows reach a prompt or a verifier; a row for another
   programme is dropped and logged.
4. **Anchors:** rank within a category (thesis over coursework, graded relevant course over an
   unrelated one); `SKILL` below `EXPERIENCE`; transcript courses (§4.1.1) are anchors.
5. **Rank across pages** instead of stopping at the first strong pair, up to the device's count.
6. **Splitter:** sentence boundaries by Unicode rules (§8.1); the 120-sentence cap becomes
   per-section windows.
7. **Ages** — one table:

   | Age limit | Question it answers |
   |---|---|
   | 7 days | reuse a research-fit result for the same student, target and topic without searching again |
   | 30 days | a person may be named only if their page was fetched within 30 days (re-checked at render and approval) |
   | 90 days | an archived (Internet Archive) copy may be cited at all |
   | 1 year | the fetch engine's own ceiling on archive copies (`FETCH_ARCHIVE_MAX_AGE_DAYS`); research fit applies the stricter 90 |

8. **Measurement:** the live test gets a pass bar (match rate, zero off-programme rows) and runs before
   the switch is turned on.

## 8. Checks after writing

### 8.1 Languages

The letter languages needed: 15 named in `letter-shape-country-map.csv` (English, German, French,
Italian, Spanish, Portuguese, Dutch, Russian, Turkish, Azerbaijani, Arabic, Chinese, Japanese,
Korean, Afrikaans) and about 25 more possible (R3 table). **The default for any language without
dedicated tooling:**
- sentence splitting on the sentence terminals our letter languages use (Latin `.!?`, Arabic `؟`,
  Armenian `։`, CJK `。！？`), replacing `_SENTENCE_SPLIT` with no new dependency (built in plan 1);
  research-fit pages get the same in plan 7. Recorded limit: Greek writes its question mark as `;`,
  indistinguishable from a semicolon without the language, so Greek questions are not split;
- `script_of` extended to Cyrillic (`ru`, `uk`, `be`, `bg`, `mk`), Greek, Arabic, Armenian and
  Georgian (built in plan 1); Serbian and Kazakh are left out because both are written in two
  scripts. Character counting is a separate CJK-only set, so a new script never switches a
  language's word caps off;
- spelling by Hunspell where a dictionary exists;
- style checks marked "unchecked in this language" (warnings, never holds);
- fact and invention checks always run (§3), with duration words from a per-language list where one
  exists and the model check otherwise.

### 8.2 Style

- **Stock words:** English as in the master. Other languages start from `tjuzek/ai-34-languages`
  (CC0; news continuations, not letters), filtered to words the chosen writer over-uses against the
  human reference corpus (master §8.1). Languages without a list: no stock-word check.
- **Generic openers and closers:** "In conclusion", topic-restating first sentences.
- **Hedges are kept** ("I think", "I believe"); the evidence comes from studies of GPT-3.5/4-era
  models, so the bake-off re-measures it on the chosen writer.

### 8.3 Grammar on student edits only

LanguageTool (self-hosted, LGPL) where it covers the language (not Turkish, Korean, Czech,
Hungarian, Finnish in 6.6); spelling only elsewhere (Hunspell; Turkish from TDD's benchmark or
`zemberek-python`, chosen in the plan). Suggestions only, never applied; non-native phrasing never
flagged.

## 9. The edit warning

When the student saves an edit, checks run on the previous and the edited text; **only problems the
edit introduced** produce a warning.

| Edit introduced | Warning says |
|---|---|
| cap exceeded; required question unanswered; wrong language or script; another institution's name; a name where naming is forbidden | the portal or reader may reject it |
| verified programme-specific claim removed; quantified result removed; story anchors dropped | the letter became less specific |
| a date, grade, role or institution differing from a confirmed fact | it differs from your records — **with an offer to correct the record** (a corrected fact goes through the ordinary confirmation path and re-checks every letter that cites it) |
| a new name or number with no source | it is not in your records |
| stock phrases, clichés, flattery of ranking or city | it reads as generic (English until other lists exist) |

Never flagged: simpler words, hedges, contractions, non-native phrasing, meaning-preserving slips.

**Where it runs.** The web request saves the edit and runs only checks that need no catalogue: caps
and naming rules from the tenant-side copy the worker wrote with the draft, language and script,
facts, stock words. Checks that need the catalogue or a model are **queued to the worker** when the
student presses "done editing"; the warning appears when they finish. Each model-calling check
carries `rate_limited()` per student (`letter-edit-check`, 20/hour). Proceeding records an
`AuditEvent` `document.letter_edit.proceeded_with_warnings` with the reasons shown. The screen is
Aykhan's.

## 10. Tenant boundaries and where work runs

### 10.1 Web and worker

| Work | Runs in | Why |
|---|---|---|
| story choice, fingerprints, research fit, feature reads, handbook OCR, letter generation, re-checks at render/approval, cross-agency check | worker (`runtime_engine`) | reads the catalogue or fetches; `runtime_web` holds no grant on either |
| saving an edit and its catalogue-free checks; showing warnings | web (`runtime_web`) | reads only tenant rows, including the copies the worker wrote |

A student action that needs any worker step queues it (`row-level-security.md`: "A student-facing
action that needs a fetch queues it to the worker").

### 10.2 Inside an agency

The pool read refuses to run without `tenant_scope` and fails loudly: with the GUC unset row-level
security returns no rows, every story would look new, and variety would switch off in silence.
Pinned by a test through `rls_enforced_orm`.

### 10.3 Across agencies, same target

- A `NOLOGIN BYPASSRLS` role owning one function, created by a new admin script run by hand after
  migrations, never by a migration (`tests/infra/test_template.py::
  test_no_migration_creates_a_bypassrls_role`), following `scripts/create_erasure_guard.sql`'s
  measured ordering (revoke from `PUBLIC` before `ALTER FUNCTION ... OWNER TO`; the owner holds
  `CREATE` on the schema; every membership but the admin's revoked and asserted).
  `elmify_erasure_guard` is not reused.
- The function takes target, cycle, shape, opening, fingerprint and the caller's tenant and returns
  **one boolean**: too close to, or too common among, other agencies' letters to this target this
  cycle. No count, no text, no student.
- **Why it fits "a fact that is not about a person"** (crossing-tenants rule 1): the answer is one
  bit about a target's letter pool, never about which student or agency; it cannot name, count or
  quote anyone.
- **Probing:** a crafted fingerprint could test whether a similar story exists elsewhere, one bit
  per call. Calls are `rate_limited()` per agency (`story-cross-check`, 200/day) and each writes an
  `AuditEvent` in the caller's transaction.
- Verified against a `NOBYPASSRLS` role through `rls_enforced_orm`, with a cross-tenant fixture where
  the answer must be true.

### 10.4 Elmify staff

The owner wants staff to read, save and act in every agency without a `SupportGrant`;
`row-level-security.md` and `docs/runbooks/support-access.md` still require the grant. A separate
design with an owner-approved rules edit; it also decides whether staff edits trigger the edit
warning and count in pools.

## 11. AI-use permission records — dropped

Owner decision, 2026-10-14: no record of which institutions have given written permission for
AI-assisted letters. The master's S9 AI-policy notice stays as designed for every target, partners
included.

## 12. Not designed

- **Invented personal life events or people** (§3): requested by the owner, citing signed study
  agreements. Not designed: they are false biography in the student's name to readers making real
  admission decisions; nothing in the system can verify an agreement's scope; a study involving them
  belongs to the partner institution's research group under its ethics review.
- **Detector work:** no detector study, no detector-targeted pass.
- **Screens:** Aykhan's; the backend returns data and reasons.

## 13. Tests and checks

| Area | Tests |
|---|---|
| shapes, two-step fit, choosing across targets, openings, pools, fingerprints, lock, outage, regeneration, submitted letters | `tests/documents/test_storyline.py` |
| invention line (both tiers), why-programme gate, no-facts letter | `tests/documents/test_letter_verification.py`, `tests/documents/test_letter_gates.py` |
| sentence splitting and `script_of` across scripts | `tests/documents/test_letter_gates.py` |
| wiring, switch, programme filter, cycle field, edit warning (web vs worker) | `tests/documents/test_letters.py`, `test_draft_letter_command.py`, `test_letter_approval.py` |
| research-fit anchors, ranking, naming, features, handbook extraction | `tests/documents/research_fit/` |
| transcript courses bridged | `tests/documents/test_profile_bridge.py` |
| pool scope, cross-agency function, web role cannot read catalogue on any new web path | `tests/documents/test_letter_tenant_isolation.py` via `rls_enforced_orm`; `tests/infra/test_template.py` |

Command: `POSTGRES_DB=elmify_<branch> uv run pytest -q tests/documents`, plus ruff, mypy,
`manage.py check` and `makemigrations --check`.

## 14. Build order (each its own plan)

1. **Correctness on today's code** (built 2026-10-14, plan
   `docs/superpowers/plans/2026-10-14-letter-plan-1-correctness.md`): sentence splitting and
   `script_of`; the programme filter; non-blocking (warning) gate violations; the why-programme gate
   and the unsourced-programme-claim gate accept only a verified programme input; the no-facts
   letter is generatable. The ten unmerged fixes on `claude/letter-gap-fixes` were merged first.
2. **Transcript courses into the ledger** (§4.1.1), wired to every ledger consumer.
3. **Story:** `DocumentDraft.cycle`; the short no-facts and thin-profile length (§4.6); shapes with
   two-step fit, openings, choosing
   across targets, pools, fingerprints with `pgvector`, lock, outage, regeneration and submitted
   letters (§4, §10.2). Threshold provisional.
4. **Cross-agency function** and its admin script (§10.3).
5. **Invention line** (§3): the code tier now; the model tier inside master build item 4.
6. **Wiring** in the worker, research fit behind its switch, `mark_letter_ready` (§7.1–7.3, §10.1).
7. **Research rebuild** (master build item 5): §5 feature reads, §6, §7.4–7.8, handbook OCR.
8. **Edit warning** (§9) with English stock words and grammar on edits (§8.3).
9. **Stock-word lists per language** (§8.2), after the reference corpus; the edit warning picks them
   up without a change.
10. Measurement: the golden-set recalibration of the fingerprint threshold and the live research-fit
   bar (master build item 6).

## 15. Assumptions and open items

- The English story summary can be forced regardless of letter language (tested in plan 3 before
  the fingerprint is relied on).
- Threshold 0.85 is a placeholder.
- German and Korean master's-admission opening norms were not found; the plain set is the default.
- The 25 "possible" languages may never be required; several of those countries' rows say English.
- TUM per-module pages and Firecrawl's PDF billing are to be confirmed by one test fetch each.
- OpenAlex native-name rates come from 10-author samples.
- National index terms (KCI, TR Dizin, HAL) unread.
- Before launch, from the master: EU AI Act Article 50 marking and the OpenRouter DPA.
