# CV engine quality pass: design

**Status:** Stage 1 and build step 4.1 are built on this branch; the 2026-10-20 amendment awaits the owner's review.
**§6 rewritten 2026-10-14** as the governing part (requirements first); see §0.
**Amended 2026-10-20** by the gap review held before build step 4.2. Three read-only reviews
(2026-10-16) traced steps 4.2–4.10 against the merged step 4.1 code (`322d7a2b`), walked real
student journeys, and sorted 313 researched rules for kinds the engine cannot express. The
owner had the findings re-judged by one test: does it take work off the student, or stop a
real failure? Decisions 22–29 (§1), §6.15, §6.16, §8.1 and the step list (§2) carry the result.
**Dates:** designed 2026-10-12 and 2026-10-13.
**Scope:** master's applicants, first students from Azerbaijan, English CVs.
**Reviewed 2026-10-13** against `render.py` (`_render_pdf`, `_pdf_artifact`,
`render_cv_with_warnings`, `render_draft`), `europass.py` (`render_europass_pdf`), the funder
templates and `tests/documents/test_render.py`. That review added:
- the per-path table (§3.0);
- the shared date filter;
- where the tight-layout retry sits;
- how the existing `font` rule is honoured and checked, and the font packages Debian actually has;
- fonts in CI and locally;
- applied fixes stored on the draft (warnings superseded by §6, 2026-10-14);
- volunteering reusing `ExperienceEntry.unpaid`;
- military service reusing the gap statement;
- the passport name as a check, not a stamp;
- the §8 application rules.

This design came out of comparing a CV our engine rendered with a one-page résumé another
service produced for the same person. Our structure suits admissions better. The comparison
also exposed real defects and open questions, listed stage by stage below.

**Evidence** (`docs/research/2026-10-12-cv-engine/`):

| File | What it holds |
|---|---|
| `cv-engine-audit.md` | Master `3f0d3b73` audited against the rule catalogs, with file:line |
| `section-2-refined.md` | Code facts, detection rules and edge cases for stage 2. Its accept/reject cards are superseded by §5 |
| `jev-relevance-questions.md` | The question Jev is asked, and what each answer does |
| `2026-10-12-cv-typography.md` | Typefaces, legibility, licences, glyph coverage |
| `2026-10-12-cv-future-and-expected-degree-dates.md` | Date wording |
| `2026-10-12-cv-wordlists-and-merit-items.md` | Soft-skill and thesis words in six languages; merit-item rules |
| `2026-10-12-faithful-rewriting-checks.md` | How to edit text without inventing anything |
| `2026-10-13-cv-gaps-research.md` | CV language, military service, names, CV vs form |

The rule catalogs (`docs/research/cv-rules.csv`, `cv-style-rules.csv`) stay the authority.

## 0. What governs (added 2026-10-14)

§6 (requirements first) is the governing part of this design. It decides how every CV and letter
requirement is gathered, merged, written to, checked and shown. Where an older design disagrees,
this log says which one wins.

| Document | What it still governs | What §6 replaces in it |
|---|---|---|
| This design, §6 (old Stage 4a, "warnings reach a person") | nothing | Replaced whole by §6. A soft finding is an item state, never a warnings list |
| `docs/superpowers/plans/2026-10-13-cv-stage-4-programme-rules-warnings-relevance.md` | nothing | Superseded; rewritten from §6 after review |
| One letter engine (`2026-09-28-one-letter-engine-design.md`, branch `claude/letter-gap-fixes`) | Letters: research, story, plan, write, check, repair | Its letter requirements come from the shared list (§6.11). "Middle-confidence answers become warnings" becomes a list state |
| One decision engine (`2026-10-03-one-decision-engine-design.md`) | Which model answers what | Its row "`undecided` rule shown to the counsellor" is replaced by §6.4 |
| Requirement reader (PR #159) | The only reader of page rules | Extended: unclear rules keep each reading's value (§6.4), and scholarship pages are read too (§6.10) |
| Letter-shape design §4 | — | Adopted for CVs: ambiguity resolves by rule to the safer shape, never to a warning |
| Format-decision guarantee (2026-09-13) | The CV format decision, unanimity for Europass | Unchanged. The format never goes through "stricter wins" (§6.4) |
| Tailored programmes §4.3–§4.4 and the unwritten eligibility "spec 3" | Eligibility: "at least 20 ECTS in theoretical CS", grades, test scores, checked against the transcript | Out of this design (owner, 2026-10-14) |
| `.claude/rules/llm-ai-security.md`, "A programme rule may not lower a key's enforcement" | The Europass privacy gate | Kept by §6.4 step 7: a merged rule carries the strongest enforcement of the rules it came from |

## 1. Owner decisions

1. **Master's applicants only.** No PhD track.
2. **English CVs only for the MVP.** CVs written in other languages are later (§11). Translating
   the student's own non-English facts into an English CV is in (§6.9, decision 20).
3. **Fixes are automatic.** The engine applies them. The student and counsellor see a
   "what we changed" list, and the student can edit. Nothing the student did not provide
   may appear on the CV.
4. **A newer CV replaces matching older facts.** The student confirms one
   "changed since your last CV" list.
5. **Typeface:** follow the programme when it names a font; otherwise Charis SIL.
6. **Relevance:** Jev judges optional items one at a time, per programme.
7. **How much a CV must contain is read per programme from its page** (§8), not fixed by us.
8. **Counsellors see everything.**
9. **The owner labels the Jev test set** (about 240 items).
10. **No LaTeX.** HTML templates and WeasyPrint stay.
11. **Requirements first** (2026-10-14). Every requirement is gathered and merged before writing;
    the CV is written to it, checked against it and shown with it (§6).
12. **Eligibility is not the CV's job.** "20 ECTS in theoretical CS" is checked against the
    transcript in its own design; the CV uses a requirement only where showing it helps.
13. **One shared list** per application, read by the CV writer and the letter writer.
14. **Theirs beat ours; between programme and scholarship the stricter wins;** two versions when
    they cannot both be met.
15. **Soft wording is followed like a rule** while writing. Still unmet at the end: soft is
    delivered with the reason shown; strict, the student picks what to drop.
16. **Missing information is asked first;** that programme's CV waits, others do not. With no
    deadline known it waits at most seven days (amended 2026-10-20, §6.5).
17. **An unclear sentence takes the stricter reading,** within the limits of §6.4.
18. **A programme's CV is made when it is added to "my applications".**
19. **Scholarship pages are read for CV rules too;** scholarship cards get their own CV. A
    scholarship applied for in the same application merges into its programme's list instead
    (amended 2026-10-20, §6.2).
20. **Fixed formats follow their template** and say so; **non-English facts are translated**.
21. **The student's uploaded CV is the anchor;** questions cover only what it lacks.

Added 2026-10-20. The owner's test for each: the product exists to take work off students, so it
cuts their friction as far as possible.

22. **The student never types a deadline.** Our own reading supplies it (§6.5). When we have none,
    the counsellor sees "deadline unknown"; the student is not asked.
23. **Each question is asked once across all the student's applications,** in plain words, and only
    after their uploaded documents have been checked for the answer (§6.5).
24. **A correction to a fact fixes every CV.** A free-text edit to one CV makes that CV the student's
    own: it is never remade automatically (§6.15).
25. **A signature is given once.** The student draws or uploads it, and it is placed on every CV that
    needs one. Only a notarised CV stays a to-do for the student (§6.15).
26. **"Use my own CV" is allowed per application,** labelled "not checked against this programme's
    rules" (§6.15).
27. **A rule we can never meet still gets a CV.** The English CV is delivered with the rule flagged and
    a to-do for the student, as decision 15 does for soft rules (§6.7).
28. **A programme that asks for no CV gets none,** and nothing is asked for it (§6.2).
29. **Nothing the student sees fails on a limit.** Every limit queues and resumes; cost is held by one
    hidden budget per student (§6.13, §6.14).

## 2. Build order

| # | Stage | Why this order |
|---|---|---|
| 1 | Layout and typography (§3) | Independent, small, visible |
| 2 | Newer CV replaces older facts (§4) | Stage 3 assumes one current fact per real thing; today a re-upload duplicates every fact |
| 3 | Automatic quality fixes (§5) | Needs §4 |
| 4 | Requirements first (§6), page rules (§8), new section and relevance engine (§7) | Needs the new grammar keys. Built in steps, each its own PR (step contents below) |

Each stage is its own pull request and ships on its own.

**Stage 4 steps** (amended 2026-10-20; every part of §6–§9 now has a step):

| Step | What it builds |
|---|---|
| 4.1 | List and who-wins (§6.3–§6.4). **Built, merged as `322d7a2b`** |
| 4.2 | Per-application trigger and its plumbing (§6.2): each CV linked to its application; kit serves only that application's CV; render from the saved list; lasting item ids, states stored apart; the digest; track from facts; same-application scholarships merged; failures as states; the CV queued by the kit-capture job; no CV for a "use our form" format; scholarship on the draft; counsellor quick edit keeps the new fields; award deadlines copied onto the application; rate limits (§6.13); backfill of open applications if any exist |
| 4.2b | The page read (§6.2): a task with both the fetcher and the model keys, the gated read queue (vouched sources, linked PDFs, per-tenant rate limit, `run_budget`), the read status on `Program`, the short wait. Its own plan |
| 4.3 | Questions first (§6.5): the answers table, one question per fact across applications, documents checked first, reminders off the scraped deadline |
| 4.4 | Writing to the list (§6.6), the new requirement kinds (§8.1), certifications and volunteering (§7.1), the rest of `_CONTENT_ONLY_KEYS` on every format, the student's signature placed (§6.15) |
| 4.5 | Fitting and checking (§6.7), the relevance engine (§7.2, which "least relevant first" depends on), CV and form agree (§7.3), the name checks (§9), the Europass items carried from 4.1, the DAAD EPOS case (§8.1) |
| 4.6 | The page (§6.8): destination in filenames and kit labels, one "Your CV" line per destination, autoescaped sentences, "use my own CV" per application (§6.15) |
| 4.7 | Scholarship pages and templates (§6.10) |
| 4.8 | Translation (§6.9) |
| 4.9 | Letter reads the list (§6.11): letter fields go through the same merge |
| 4.10 | Staying current (§6.12), student edits (§6.15) |

## 3. Stage 1: layout and typography

### 3.0 Which renders this stage reaches
Five CV paths exist in `render_cv_with_warnings` (`render.py`). This stage changes them as follows:

| Path | Template / producer | §3.1 text layer | §3.2 dates | §3.4 tight layout | §3.5 typeface |
|---|---|---|---|---|---|
| STANDARD, GERMAN_TABULAR | `cv_base.html` children, via `_render_pdf` | yes | yes | yes | yes |
| EUROPASS (local look-alike, the preview when no network) | `cv_europass.html`, a `cv_base.html` child | yes | yes | yes | yes |
| FUNDER_TEMPLATE (SISGP, Rhodes) | `cv_funder_*.html`, own CSS, via `funder_templates/` | yes (same marker CSS added there) | yes | no: fixed funder layout | no: the funder's layout is kept |
| EUROPASS_API | `render_europass_pdf` (`europass.py`): the EU's service returns the PDF | no | partly: §3.2's content filter applies to the payload; wording is the EU's | no: a BINDING cap still blocks until Stage 4; from then page limits do not apply to it (§6.7 step 5) | no |
| FIELD_MAPPED | `_render_field_mapped`, no PDF | n/a | the content filter applies | n/a | n/a |

The date filter (§3.2) therefore lives on the shared content funnel (`europass_content`, which
every path calls first), not only in templates.

### 3.1 Clean text layer (R-043)
- **Problem.** pypdf (our own upload reader and page-fill check use it) puts every list
  marker at the bottom of the page, and kerning splits "PyTorch" into "PyT orch".
- **Fix.** Draw the marker with `li::before` and `list-style: none`; set `font-kerning: none`.
  Apply it in `cv_base.html` and in both `cv_funder_*.html`.
- **Hyphenation stays.** `cv_base.html` justifies with `hyphens: auto` (owner decision
  2026-09-15). A line-end hyphen is a legitimate break, not a split word, so the test allows
  "opti-" at a line end and forbids a split inside a line.
- **Test.** Render, extract with pypdf, assert each marker is on its bullet's line and no word
  is split inside a line. Re-check page counts on the existing render tests.

### 3.2 Dates
- **Degree in progress.** It prints "Sep 2024 – Jun 2026 (expected)". Five university guides agree.
- **Place accepted, not started.**
  - It is left off by default.
  - If the student opts in, it prints "Admitted; starts Oct 2026", never "– present".
  - No guide covers it, and naming an offer from elsewhere can hurt an application.
- **Post with no end date.** It prints "Present", capitalised consistently. Three existing tests
  pin the lowercase word (`test_render.py`: `test_open_ended_entry_still_renders_present` and
  two near lines 1395 and 2574); they are updated, not deleted.
- **"Today" is a parameter.** Whether a date is past or future is decided against a `today`
  passed into the render (default `date.today()`), so tests can fix it.
- **Where.**
  - The filter that leaves out a not-yet-started place is on `europass_content`, so every
    path, the EU payload included, is covered.
  - The "(expected)" and "Admitted; starts" wording is in `cv_dates.py` (`month_year`) and
    the templates.
  - Each form is pinned in `test_render.py`.
- **The opt-in has no storage yet.** It arrives with the "put back" decisions of §5.5. Until
  Stage 3 ships, a not-yet-started place is never printed.

### 3.3 Tidy-ups that change no fact
- **Bullet endings.** A trailing full stop is stripped at render, so endings are consistent.
- **Entry header.** The layout stays as it is (S-034 sample 1).

### 3.4 Tight layout only when needed
- **When it applies.** A BINDING `max_pages` would otherwise fail (from Stage 4: any page limit on the
  requirement list, §6.7).
- **What it does.** Render once more with a `compact` class:
  - 10pt body and 19mm margins (the S-002 and S-003 lower bounds);
  - tighter entry and heading spacing.
- **If it still fails,** block as today, until Stage 4; from then §6.7 decides what happens.
- **Never remove content to fit** in this stage. There is no one-page default (R-054). From Stage 4,
  a page limit on the requirement list may leave out optional items first (§6.7), each listed and
  restorable.
- **Where.** In `render_cv_with_warnings`, after the checks run:
  1. **Trigger.** It fires only when a BINDING `max_pages` violation exists and the path is one
     of the three `cv_base.html` paths (§3.0).
  2. **Re-render.** `_render_pdf` takes a `compact` flag that adds the class to `<body>`.
  3. **Re-check.** Every check runs again on the compact artifact. The compact one is kept
     only when it clears the BINDING `max_pages`. The final-page-fill check may then report
     a near-empty last page, which is advisory and reported as usual.
- **Existing tests.** `test_binding_max_pages_violation_blocks` (20 entries, one-page cap)
  still blocks, because 20 entries cannot fit one page at any density. A new test pins a CV
  that blocks at normal density and passes compact.

### 3.5 Typeface
- **When the programme names no font,** the CV uses Charis SIL. It is under SIL OFL, covers
  Ə ə and Cyrillic, and has four styles.
- **When the programme or portal names a font,** the CV uses the metric-compatible look-alike,
  as `letter_render.py` (`SHIPPED_FONTS`) already does:

  | Named font | Look-alike |
  |---|---|
  | Times New Roman | Liberation Serif |
  | Arial, Helvetica | Liberation Sans |
  | Calibri | Carlito |
  | Cambria | Caladea |
  | Garamond | EB Garamond |
  | Georgia | none packaged: the default, with a note |
  | Verdana | DejaVu Sans |

- **Where the programme's font comes from.** A CV `font` rule already exists. The in-repo
  grammar projects a page's font sentence onto the `font` constraint key (`rule_sinks.py`;
  `grammar.py` maps both `font_family` and `font_size_minimum` to it). Its value is the
  sentence's printed detail, for example "Times New Roman, 12 pt".
  - **Today nothing honours it, and nothing checks it.** `render_cv_with_warnings` has no
    `font` checker, so the rule is reported as "no pre-flight check for 'font'" on every such
    programme.
  - **This stage:**
    1. A parser reads the family and point size from the rule's value.
    2. `_render_pdf` takes `font_family` and `font_pt`. The family is resolved through the
       table above, and the size is honoured even above S-002's 11pt target, because the
       programme wins.
    3. A `font` checker passes when the artifact's embedded fonts include the resolved family,
       read with pypdf from the PDF's font resources.
    4. A family the table does not know keeps the default and leaves an advisory note naming
       the requested font.
  - **Not the letter's path.** `derive.py`'s `font_family` is the letter reader's; it is not used.
- **Caladea has no Cyrillic.** For a CV containing Cyrillic, use Liberation
  Serif instead and add a counsellor note naming the substitution.
- **Installing the fonts.**
  - **Production.** Fonts are system fonts, because `_RefusingFetcher` refuses every load,
    file URLs included. The `Dockerfile` installs each one as a Debian package in the stage
    that renders: `fonts-sil-charis`, `fonts-crosextra-carlito`, `fonts-crosextra-caladea`,
    `fonts-ebgaramond`. Checked 2026-10-13 against Debian trixie (`qa.debian.org/madison`):
    all four exist (Charis is 6.200 there, not the 7.000 used for the samples). Gelasio has no
    package, so Georgia falls back to the default with a note.
  - **Check each package exists** in the base image's Debian release before relying on it. A
    face with no package is dropped from the table, so it falls back to the default with a note.
  - **CI.** CI runs the tests on the host runner, not in the image, so `ci.yml` installs the
    same packages before `pytest`. That PR then gets no automatic Claude review (CLAUDE.md).
  - **Local.** A developer without the fonts gets a silent fallback and different page counts.
    So a test asserts the default face is installed and embedded (font name read from the PDF),
    and fails with an install hint rather than passing on the wrong font.
- **Page counts move.** Charis has different letter widths from DejaVu Sans. Every test that
  asserts a page count or a near-empty last page is re-run, and a changed count is
  investigated, not just updated.
- **Template facts found while rendering the samples:**
  - The page footer gets an explicit `font-family`; the margin box sets none today.
  - The change goes in `cv_base.html` itself, because an injected stylesheet loses to the
    template's own `<style>`.
  - The comment above `body { font-family: ... }` explains why the installed face must come
    first. The new order keeps that rule: Charis, then DejaVu Sans as the installed fallback.
- **Test.** A coverage render with "Ə ə Ğ ğ İ ı Ş ş Ç ç Ö ö Ü ü", Cyrillic, German and French
  letters, in regular, bold and italic. Assert from the PDF's font resources, read with pypdf,
  that no face other than the resolved one is embedded. Not `pdffonts`, which CI may not have.

### 3.6 EUROPASS_API is outside this stage
`render_europass_pdf` sends the content to the EU's service and returns its PDF. §3.1, §3.4
and §3.5 cannot reach it, and §3.2 reaches it only through the content filter. A BINDING page
cap the EU's PDF breaks still blocks until Stage 4. From Stage 4, a Europass CV takes whatever
number of pages the EU's format produces (owner, 2026-10-14; §6.7 step 5). The local EUROPASS look-alike is ours and is in
scope (§3.0).

## 4. Stage 2: a newer CV replaces older facts

- **Matching.** `ingest_uploaded_cv` (`ingestion.py`) writes each new entry with `supersedes=`
  the matching older fact, matched by category and identity (`verification._identity`).
  Matching runs against the whole supersession chain, not only the current tip. Otherwise a
  re-uploaded abbreviation stops matching its corrected form and becomes a second degree.
- **What is new and what stays.** Entries only in the new CV are added. Entries only in the old
  CV stay.
- **One confirmation.** The student sees "changed since your last CV": each changed value, old
  beside new. One press confirms. An unticked row keeps the old value.
- **Result.** Today's dead end goes away: a changed date no longer makes two facts conflict and
  block the draft.
- **Tests.** In `tests/documents/`:
  - re-upload with one changed date gives one current fact, superseding the old;
  - an unticked change keeps the old value;
  - a corrected degree title survives a re-upload of the old abbreviation.

## 5. Stage 3: automatic quality fixes

Every fix is a constrained edit, never a free rewrite. The one controlled study of model-
rewritten résumés found invented or inflated claims in half of outputs even under a strict
prompt. No checker is accurate enough to be the only guard
(`2026-10-12-faithful-rewriting-checks.md`). So no model writes a sentence here.

### 5.1 Bullets that do not start with what the student did (S-026)
- **Detection.** Plain code. An English bullet whose first word is not a verb in past or
  present form, and which is not a short research or thesis prose line (S-010 allows those).
- **Fix.**
  - Jev picks one opening from a short fixed list, or "leave unchanged".
  - Code attaches it to the front of the student's own words. Every other character stays
    the student's.
- **No inflation.**
  - The list runs from modest ("Worked on", "Contributed to") to stronger ("Built",
    "Designed", "Led").
  - A stronger verb is allowed only when the student's own text in the same entry already uses
    it, or one of equal strength. Otherwise the modest one is used.
- **Doubt keeps the line.** If Jev answers "leave unchanged" or is unsure, the line stays as written.
- **English only in the MVP.**

### 5.2 Soft-skill filler in Skills (S-025)
- **Detection.** A skill matching the verified English soft-skill list (about 31 terms,
  `2026-10-12-cv-wordlists-and-merit-items.md`).
- **Fix.**
  - Left out of the Skills section and listed under "left out". The ledger keeps it.
  - The student can put it back.
- **Skill headings.** Generation stops inventing them: code copies `category` from the
  matching confirmed SKILL fact after the model returns (`section-2-refined.md` §2.5).

### 5.3 Abbreviated degree or institution names (R-034, R-061, S-029)
- **Never guessed.** "Chem. Eng." could be several titles.
- **When the platform has read the diploma or transcript** (the document fact-reading work),
  the full title is taken from it.
- **Otherwise** the name prints as written, and the gap question for the full title stays
  in the student's question list.
- **Guard.** A title longer than the CV's line budget is refused before it is stored.

### 5.4 Thesis listed as a job (S-037a, S-040, R-039)
- **Placement.** The thesis title and supervisor print under the degree. The experience entry
  stays, because Education entries cannot hold bullets.
- **Reader instruction.** Change the CV reader's prompt at `ingestion.py:357` so it no longer
  gives "Master's Thesis" as a job title, and update `test_render.py:313`.
- **Detection.** English thesis words: Master's thesis, Bachelor's thesis, dissertation, capstone.
- **Print once.** When the thesis also has its own Research entry, the title prints once, under
  the degree, and the Research entry is headed "Thesis research".

### 5.5 What the student and counsellor see
- **"What we changed":** every automatic change, with the original beside it, and every item
  left out. The student can undo any of them.
- **The counsellor sees the same list.**
- **One-tap fixes from the student** are written as new facts superseding the old, confirmed
  by the student, with an audit event (`section-2-refined.md` §2.3).
- **Where the list lives.** Generation writes it to a new `applied_fixes` JSON field on the
  `DocumentDraft` (§10). It holds each change with its original text, so it carries student
  text and is redacted on erasure.

### 5.6 Two stamps in generation
After the model returns and before verification, code overwrites:
- each experience entry's bullets with the confirmed fact's bullets;
- each skill's `category` with the confirmed fact's.

Without these, generation can reword an applied fix and no check notices
(`section-2-refined.md` §2.5).

## 6. Stage 4: requirements first

Owner, 2026-10-14: before a CV is written, gather every requirement that applies, merge it with
our own writing rules, and write to the result. Today the writer sees only `include` field names
(`generation.py`). Every other rule is checked after the PDF exists, and `render_cv` keeps only the
BINDING findings, so every soft one is lost.

### 6.1 The anchor: the student's own CV

The student uploads their CV first, and its facts (plus their documents) are the starting point.
Every requirement is compared against what those facts already hold. Questions and document
requests cover only what is missing. Nothing the student did not provide may appear on the CV
(owner decision 3).

### 6.2 When it runs

- **A programme's own CV** is made when the student adds it to "my applications"
  (`portals.applications.add_application`). The worker gathers the list (§6.3), asks what is
  missing (§6.5) and writes the CV (§6.6).
- **A separately-applied scholarship** gets its own CV the same way. Today its card stores the
  award's id in `program_id`, and `document_worker._generate` drops the job in silence.
- **Which scholarship feeds which list** (amended 2026-10-20). `ApplicationLink` exists only for
  `SEPARATE_ROUTES` awards (`portals/award_links.py`); it pairs cards but merges nothing, because a
  separate card has its own upload and its own list. An award applied for **in the same
  application** as its programme (routes `CONSIDERED_WITH_ADMISSION` and `JOINT_SELECTION`, the
  Erasmus Mundus case: "Programme + scholarship, one application") never becomes a card, so today
  its rules never reach the CV. Its rules now merge into that programme's list. `build_requirements`
  takes every such opportunity, not one.
- **Each CV belongs to one application** (`DocumentDraft.application`, §10). Today the kit
  (`packets._kit_documents`) takes `programme_id = application.program_id OR programme IS NULL`. A
  scholarship CV has `programme = NULL`, so it counts as "general" and lands in every kit; an award
  card's `program_id` holds the opportunity id, so its own CV never matches it; and a re-applicant's
  new card picks up last year's approved CV. The kit now serves the latest approved CV made for that
  application, and a general CV is one marked as such, not one with no programme.
- **The general CV** stays only for applications whose list holds no outside CV rule. It is still
  written to a list, one holding only our own rules, and its "Requirements for CV" says the
  programme states no CV rules.
- **A programme that asks for no CV gets none** (decision 28). Nothing records a page's "no CV"
  today (corrected 2026-10-20 from the code): `research.SiteJobRecord`'s `no_cv_required` outcome has
  no production writer, and `Program.cv_format_confidence = NO_CV_FOUND` is a claim about our
  reading, never about the page. What exists is the format `structured_fields_only` ("use our
  form"), seeded on Stipendium Hungaricum and NAWA (`catalog_seed.py`). Step 4.2 honours it: no CV is
  made, nothing is asked, and the application records "no CV". The page reader learns to produce it
  in step 4.4 (§8.1).
- **The page read, without making the student wait** (amended 2026-10-20; replaces "every document
  waits for the page read"). Corrected from the code the same day: no programme page is read for CV
  rules in production today. `program_rules.read_and_derive` has no production caller; pages are
  read only by hand (`manage.py rederive_rules` over stored statements, and seeded runs). The
  document worker has no page fetcher, and the general worker has no OpenRouter or Anthropic key
  (`infra/template.yaml`). Wiring the read is therefore its own step, **4.2b**, with its own plan.
  Until it ships, the CV is written from the rules already stored, and a programme whose
  `cv_format_confidence` is still `UNVERIFIED` shows "this programme's page has not been read yet".
  Once 4.2b ships:
  - adding the application queues a read (shared by every agency) through the gated read queue: vouched `OfficialSource`
    pages only, the reading funnel that also follows linked PDFs (`DOCUMENT_SUFFIXES`), per-tenant
    rate limiting in the same change (`.claude/rules/llm-ai-security.md`). Today nothing in
    production starts a read (`program_rules.read_and_derive` has no production caller) and the
    worker task has no model key; step 4.2 wires both;
  - the CV waits at most a short limit (set in the step 4.2 plan, measured on real reads), then is
    written with what we have. When the read lands and changes the list, an unapproved CV is remade
    automatically (§6.12);
  - a read that fails (blocked, unreadable, not found, or past the limit) still finishes: the CV
    is made to our own rules, and the list says "the programme's rules could not be read";
  - `Program` gains a read status, so "never read" is told apart from "read, no CV rules"
    (`cv_format_confidence = UNVERIFIED` means both today);
  - scholarship pages have no reader until step 4.7, so scholarship cards skip the wait until then.
- **Built in the kit-capture job.** The list needs the application's letter cycle, which
  `packets.capture_requirements` writes in its own job queued on commit. The list is built in that
  same job, after the capture, so the two never race.
- **Failures are states, not crashes.** `generate_cv` raises `IdentityNotConfirmed`,
  `ApplicationEmailMissing` and `GenerationRateLimited`, and `_generate` assumes the endpoint
  checked them; `add_application` checks none, and `link_awards` can add several cards per Add.
  Each becomes a list state ("waiting for you", "queued, starts at 14:20") instead of a job that
  retries into the dead-letter queue.
- **Applications made before step 4.2** get their list and CV from a one-off `manage.py` command
  over open applications. Drafts made before it keep `requirements = NULL` and render as they do
  today. If no real student has an application yet, the command is not built.
- **Remade** when the student submits answers, confirms the Stage 2 "changed since your last CV"
  list (not on the upload itself, §6.12) or a page re-read changes the list.
- **Only typed data crosses into the web tier.** `runtime_web` holds no grant on catalogue tables,
  so the worker writes everything the page shows onto tenant rows (§10).

### 6.3 The requirement list

One list per application, built by the worker (`runtime_engine` can read the catalogue) and saved
on the draft. Each item has:

- a **typed key and value** from the closed lists (`constraints.CONSTRAINT_KEYS`, the directive
  actions, the letter-shape fields);
- the **document** it governs: CV or letter, so a 1-page letter limit never becomes the CV's;
- its **origin**: programme, scholarship, institution, or ours;
- its **force**: strict, soft, or for-information;
- the **page's own sentence** and URL, for display only (§6.6), stored once (today it is held twice,
  in `sentence` and in `rule.rule_text`, up to 1,000 characters each, on every draft version);
- a **lasting id** (added 2026-10-20), derived from its content: a hash of (document, key, origin,
  source URL, normalised value), plus a counter for true duplicates. Today `Requirement` has no id;
  directive, format, letter and competency items have no contributors, and duplicate keys arise
  from `alone`, from the two sides of a conflict and from repeated written requirements. Answers,
  "put back" choices and overrides key on this id, so they keep their place across remakes.

Its **state** (§6.8) is not part of the item. States can name the student's own entries, so they
live only in `DocumentDraft.requirement_states` as `{item id: {state, reason}}`, REDACTED on
erasure, while the list itself is programme data, KEEP (§10). Step 4.2 drops the `Requirement.state`
field that step 4.1 built.

**The academic track** (taught or research master's) is saved with the list. It comes from the
programme's `academic_track`; when that is unset, from the student's anchor facts. Today
`constraints.resolve_track` falls back to `content.research`, the written CV, which does not exist
yet when the list is built.

**Sources:**
- `Program.cv_constraints`, `cv_directives`, `cv_format_requirement`;
- the scholarship's equivalents (§6.10);
- catalogue rules: INSTITUTION and FUNDER scope count as theirs; UNIVERSAL, TRACK and COUNTRY
  count as ours. INSTITUTION rules are our research about one university, and they still beat our
  country norms, because they are about that university (owner, 2026-10-14);
- our style rules that the engine applies or shows, seeded as UNIVERSAL rows (today only S-022
  exists as a rule object);
- the application's letter shape and written requirements, for its own cycle
  (`Application.kit_letter_cycle`). With no prompt for that cycle the letter part is empty and the
  letter writer uses its defaults (`letter_defaults.defaults_for`);
- the programme's COMPETENCY statements, used only to rank relevance (§7.2), never as pass or fail.

### 6.4 Who wins

Applied in this order:

1. **Readings about someone else are discarded.** `third_party` and `unjudged` outcomes never
   become rules (`derive._THIRD_PARTY`).
2. **An unclear sentence takes the stricter reading**, computed from the readings, which the
   reader now saves on the `undecided` rule (today it keeps only the disputed key). This applies
   only to limits and bans. An unclear sentence about a personal item (photo, date of birth,
   signature) is asked of the student. An unclear format stays `any`. An `undecided` rule written
   before readings were saved is for-information until `manage.py rederive_rules` re-reads it.
3. **Theirs beat ours**, even when theirs is soft. Among our own rules, today's scope order stands:
   the more specific wins (COUNTRY over TRACK over UNIVERSAL).
4. **Among theirs, the stricter value wins**, per key, by the table below.
5. **Contradictions across keys are caught.** Example: the scholarship's `required_fields` includes
   the date of birth (SISGP's R-079) while the programme's page forbids it, or the page carries an
   `include(personal.date_of_birth)` directive against a ban. (A COUNTRY rule against the date of
   birth is ours, so step 3 already settles it.) The pairs are listed in code.
6. **What cannot be reconciled:** if the destinations are separate uploads, two CV versions are
   made, one per destination. If they share one upload, the student is shown the conflict and
   chooses. Two versions double that application's cost, rate-limit use and confirmations; that is
   accepted, since it should be rare (owner, 2026-10-14).
7. **A merged rule carries the strongest force of the rules it came from**, whichever one
   supplied the value.
8. **The privacy check before europa.eu.** Code applies every content-only item on the list (photo,
   date of birth, prohibited content and the rest of `_CONTENT_ONLY_KEYS`) to the content before the
   payload is built, soft ones included, so a soft rule cannot let personal data out. The check
   that runs before sending (`_blocked_by_content_only_rules`) then stops the send whenever a strict
   content-only item is still unmet, because that CV would end in "choose what to drop" (§6.7),
   not be delivered. A soft item never stops a send, since a soft item still unmet is delivered
   anyway (decision 15). Build step 4.1 applies this on the europa.eu path for the photo, the date
   of birth and links; step 4.4 applies the rest of `_CONTENT_ONLY_KEYS`, on every format.

| Key | Stricter means |
|---|---|
| `max_pages`, `max_bytes`, `no_unexplained_gaps` (months) | the lower value |
| `min_final_page_fill` | the higher value |
| `max_entries_per_section` (absorbs the planned `cv_item_cap`) | the lower value, per section |
| `required_fields`, `prohibited_content` | both lists combined |
| `photo_allowed` / new `photo_required` (§8) | forbidden beats allowed. Required against forbidden goes to step 6 |
| `date_of_birth_allowed` | forbidden beats allowed |
| `signature_required` (absorbs the planned `cv_signature`), `date_of_issue_required` | required beats not stated |
| `language` (absorbs the planned `cv_language`) | the languages both accept. None in common goes to step 6 |
| `cv_scope` (§8) | `complete` beats `relevant_only` |
| `cv_start` (§8) | the earliest start |
| `font` | the first stated by theirs; the rest are for-information |
| `include` directive | all kept (combined) |
| `emphasise` directive | all kept, in theirs-first order |
| `order` directive | no stricter direction: two different orders for one section go to step 6 |
| `ai_use_policy`, `undecided`, `unapplied` | for-information; these can never refuse a CV |
| CV format (`cv_format_requirement`) | not merged by strictness: today's order stands (funder, then programme, then country) |
| `max_words`, `max_chars_incl_spaces`, `max_chars_excl_spaces` (letter) | the lower value, document = letter |
| `min_words`, `min_chars_excl_spaces` (letter) | the higher value, document = letter. A minimum above a maximum goes to step 6 |
| letter written requirements and student actions | all kept, document = letter |

A test fails when a key or directive action exists without a row here. That is how every rule
the system can read is anticipated (owner, 2026-10-14).

### 6.5 Before writing

- **Missing facts become questions,** but only after the student's uploaded documents have been
  checked for the answer (the document fact-reading work, merged to `master` 2026-10-16 as PR #221,
  not yet in this branch: step 4.3 merges `master` first).
  The worker compares the list with the anchor and stores the questions on a tenant row the web
  page can read. That programme's CV waits; others do not.
- **One question per fact, across every application** (decision 23). Questions are keyed by
  (fact, key), not by application, so a student adding ten programmes answers "your GRE score" once,
  and one answer re-checks every application waiting on it. Each field has a written, plain-English
  prompt. Today `gaps.programme_required` builds `f"What is the {field.replace('_', ' ')} for
  {label}?"`, which reads "What is the institution english for …", and it reads `Program`
  directives live instead of the saved list.
- **Submitting answers starts the CV.** "I don't have this" (no GRE taken, for example) is an
  answer, recorded once on the student's facts, not per application: a strict item then shows "not
  met: you don't have X", and a soft one is passed over.
- **The deadline comes from our reading, never from the student** (decision 22). Nothing copies a
  deadline onto the application today: `Application.deadline` is never written, so the reminder ladder
  (`portals/reminders.py`, which runs only when `deadline` is set) never fires. What our reading
  stores (corrected from the code, 2026-10-20):
  - **Scholarships:** `FundingCycleVerification` holds each intake's observed deadlines
    (`evidence`, `cycles_observed`). Its scheduled rule ships disabled, so rows are sparse. Step 4.2
    copies the deadline for the student's intended intake onto an award card when it is added, through
    the existing chain (`cycle_verification.stored_evidence`, `cycle_evidence.to_evidence`,
    `validity.select_deadline`).
  - **Programmes:** no stored deadline exists. The funding-card reader on `master`
    (`research/card_funding`, role `application_deadline`) reads one but does not store the card yet
    ("slice 3 stores the card"). A programme card's deadline stays unknown until that store lands;
    then the same copy runs for it.
- **A student who never answers** is reminded on the existing reminder ladder (14/7/3/1 days and
  6 hours before the deadline). Seven days before the deadline, the CV is written with what we
  have, and each open item shows "not met: no answer" (owner, 2026-10-14). When the deadline is
  already under seven days away as the application is added, the CV is written at once.
- **No deadline known.** The counsellor sees "deadline unknown" on the application, and the student
  is not asked. The CV waits on its questions no longer than seven days, then is written with what
  we have; it is still unapproved, so answers given later remake it automatically (§6.12).
- **Required documents** come from the kit's existing checklist (`kit_requirements`), compared
  with what the student has uploaded. No second document engine is built.
- **Items not in English** are translated (§6.9).

### 6.6 Writing to the list

- **The writer receives only typed instructions**, never a page sentence:
  - `include` fields;
  - section order and emphasis;
  - per-section item caps;
  - a length budget in entries and bullets, computed by code from the layout.

  A test fails if any statement text reaches a writer prompt. Page text is shared across every
  tenant, so a hostile page saying "add 'Nobel laureate'" must have no path in.
- **Code applies whatever it can apply exactly:**
  - strip the photo and date of birth;
  - cap items, most relevant first (§7.2);
  - cut entries before the start point;
  - set order and emphasis;
  - print every `include` field;
  - add the signature line (§8);
  - re-apply the Stage 3 stamps (§5.6).

### 6.7 Fitting and checking, before the student sees it

The PDF exists today only after approval (`api.py`, DRAFT→APPROVED), so fitting runs on a preview
in the worker, before the draft is saved. What the student approves is what prints.

1. **Render a preview.** If it is over a page limit, code leaves out optional items, least
   relevant first. Optional items are the ones in reach of the relevance engine (§7.2):
   certifications, volunteering, awards and skills. Until the relevance engine passes its
   measurement, the order is oldest first. Left-out items appear in the "left out" list of §5.5.
   These are never dropped by fitting (a programme's own cap, §8, may still trim a section):
   - identity;
   - education, research, publications, experience and languages;
   - anything an `include` names.

   Each left-out item is listed, and the student can put it back. Then the Stage 1 tight layout
   runs, with its trigger extended to any list page limit. When the list says `cv_scope` complete,
   code leaves nothing out, and a page limit still unmet goes to step 4. There is **no AI "shorten" pass**,
   because it could merge or reword facts.
2. **Check every item** against the same saved list. `verify_against_facts` runs again after
   any change.
3. **One repair.** One more write, with the failed items given as typed targets, then the check
   again.
4. **What is left:**
   - **Soft and still unmet:** the CV is delivered, and the item says what was not met and why
     (owner, 2026-10-14).
   - **Strict and still unmet:** the student picks what to drop from a list of what would fit,
     and the CV is made at the right length. A student who drops nothing gets the CV anyway, with a
     clear flag naming the strict rule it breaks; it is their choice (owner, 2026-10-14).
   - **Never meetable by us** (a CV in German, notarised, handwritten; amended 2026-10-20,
     decision 27): the English CV is still delivered. The item shows the rule it breaks and why, and
     the student gets one to-do ("have it translated", "have it notarised"). Today such a CV is "not
     possible yet" and no CV is made, while the kit offers an uploaded CV that breaks the same rule.
     Step 4.5 replaces the `not_possible_yet` state built in step 4.1 (`requirement_list.py`).
   - **A template we do not have** (the institution's own form, with no renderer): shown as
     "handled by the official template", with the template's link, and the standard CV is never
     printed as if it met the rule (§8.1).
   - **A vendor or model failure:** "temporary error, retry". The saved list is unchanged.
5. **Fixed formats.** Europass (rendered on europa.eu after consent), funder templates and
   form-style CVs follow their own layout, so page-type items show "handled by the official
   template". There is no page loop on them. **A Europass CV takes whatever number of pages the
   EU's format produces:** Europass natively runs longer, and when a programme or scholarship asks
   for Europass, its page limit does not apply to it (owner, 2026-10-14). No page check, no extra
   EU call.
6. **A refused programme CV is never replaced by the general one.** The kit (`packets.py`) does
   not substitute the general CV for an application whose own CV was refused or is waiting. While
   the programme's CV is being prepared or waits on the student, the kit offers the student's own
   uploaded CV, labelled "not checked against this programme's rules" (owner, 2026-10-14). It serves only the latest
   approved version made for that application (§6.2), never every approved CV version as it does
   today: approving a draft never supersedes the older approved ones.

### 6.8 "Requirements for CV" on the CV page

For each application, the CV page lists every item: the page's own sentence, where it came from
and its state. The student and the counsellor both see it, as plain HTML on the existing CV page.
**SHOULD BE DONE BY AYKHAN:** the final look. This design ships the data and a one-module swap seam.

**States:**
- applied;
- translated;
- left out (put back);
- waiting for you;
- not fully met (why);
- choose what to drop;
- not met by us, to-do for you (why; §6.7, decision 27);
- handled by the official template;
- for your information;
- temporary error.

Each draft also records its destination (the programme or scholarship name), so two versions can
be told apart. Every "counsellor note" elsewhere in this design (font substitution §3.5, CV against
form §7.3, names §9) is a for-information item on this list, seen by the student and the counsellor.

Added 2026-10-20:
- **Two versions can be told apart when downloaded.** Today `storage.artefact_filename` names only
  the variant (`cv-standard.pdf` for every CV), the kit labels every entry "CV", and
  `portals/needs.py` shows one "Your CV (version N)" line per draft, with N counted across all of
  the student's programmes. The filename and kit label carry the destination (and "with photo" or
  "no photo" when two versions differ by that), and the needs list shows one line per destination.
  Where a page states a file name (TU Delft's "LastnameInitials-resume.pdf"), that name is used (§8.1).
- **Language of the list:** English for the MVP (the app has no locales). An INSTITUTION-origin
  item reads "our research about this university", so our research is never shown as the
  university's own words. A translated screen is its own piece of work.

### 6.9 Translating the student's own facts

The MVP writes English CVs. A fact the student gave in Azerbaijani, Russian or another language is
translated for that CV, so the student is not asked to retype it:
- names, numbers, dates, grades, units and titles stay exact;
- the translation passes the faithful-rewriting guard (`2026-10-12-faithful-rewriting-checks.md`);
- a degree title prints in the original plus the translation (R-034).

**When the guard fails** on an item, only that item is shown to the student, asking for an English
wording. The original text stays the fact of record, and the translation is stored as a rendering
of it. The list shows what was translated.

### 6.10 Scholarships

- **Scholarship pages are read** for CV rules the same way programme pages are: the same reader,
  the same grammar, the same projections. The results land in new `FundingOpportunity.cv_constraints`
  and `cv_directives` fields. Without this, "stricter of programme and scholarship" compares
  against nothing for every scholarship nobody entered by hand.
- **The draft records its scholarship.** Today `create_draft` never sets `funding_opportunity`,
  so scholarship rules never reach a real CV.
- **Funder templates reach the worker.** Today `render_draft` gets no template id, so
  SISGP and Rhodes renders would dead-letter.
- **A scholarship applied for with its programme** merges into that programme's list (§6.2); only a
  separately-applied scholarship has a card, a list and a CV of its own. For an Erasmus Mundus
  degree the consortium's published rules count; partner universities' own pages are not read for
  it (owner, 2026-10-20; it rests on the assumption in §13 that a consortium publishes one set
  of rules).
- **Australia Awards** is seeded as a funder template (`catalog_seed.py`), but no renderer exists,
  so its CVs fail with `UnsupportedRenderVariant`. The seed stops claiming a template we do not
  have: the item becomes "handled by the official template" with its link (§6.7), and no renderer
  is built.

### 6.11 The letter reads the same list

`generate_letter` takes the application's letter items (document = letter) from the same list
instead of gathering its own. Only typed fields cross; no sentence is copied between the CV and
the letter.

Amended 2026-10-20: letter fields go through the same merge as CV rules. Today step 4.1 builds them
directly with `force="strict"`, no rule and origin "programme", so the MERGE table's `first` row is
never used for letters, and a scholarship's letter shape has nowhere to live (`ApplicationPrompt` is
keyed by programme only). Step 4.9 routes them through contributions and gives a scholarship's
letter shape a home. A strict letter item no one can meet (handwritten, a file bundle) follows
§6.7's "never meetable by us", not "choose what to drop".

### 6.12 Staying current

- **A digest of the list** is saved with the draft. It covers only what changes the CV: a sorted
  list of (document, key, value, force, origin, conflict) per item (amended 2026-10-20). The step
  4.1 plan's digest of `model_dump_json()` would also cover rule ids (which carry a sentence's
  position on the page), sentences, contributors and states; three reads of one page union to 47,
  42 and 48 statements, so every re-read would remake every unapproved CV and show "rules changed"
  on every approved one.
- **What triggers an update:** a page re-read that changes the digest, the student confirming the
  Stage 2 "changed since your last CV" list (not the upload itself: until it is confirmed the old
  facts stand, so remaking on the upload writes them again and then remakes a second time), or
  answers submitted.
- **Each list records the intake it was read for,** as the letter does (`kit_letter_cycle`). A
  re-read for next year's intake never touches a current applicant's CV.
- **Remakes and "rules changed" notices stop** once an application is submitted or its deadline
  has passed.
- **A CV the student edited by hand is never remade automatically** (§6.15).
- **Drafts not yet approved** are remade automatically, queued under the rate limit (§6.13).
- **Approved drafts** keep the list they were made with and are never replaced without asking. The
  student and counsellor see "this programme changed its CV rules" or "your CV changed", with one
  tap to make a new version (owner, 2026-10-14).
- **Rendering** uses the saved list and the format pinned on the draft. It never re-resolves the
  rules live. This moves to step 4.2 (amended 2026-10-20), so the page and the checks never disagree
  between steps 4.2 and 4.10. Today `render_draft` resolves live whenever it gets no constraints, so a
  saved list that projects no rules would also fall back to live, and `europass_render` resolves
  live and takes directives from the programme. `DocumentDraft.requirements` is nullable: null
  means a draft from before step 4.2, which renders as today; an empty list means "no rules".

### 6.13 Plumbing fixed on the way

- **The CV rate limit is counted once per job.** Today `api.generate` and `generate_cv` both
  count, so 10 an hour is really 5. Hitting the limit becomes a visible state ("queued, starts at 14:20"), and the job resumes on
  its own when the window opens, never a dead letter.
- **Model calls run outside the long database transaction** in `document_worker._generate`.
- **Every limiter queues and resumes** (amended 2026-10-20), not only the CV one. §7.2 reuses the
  `skill-match` limiter (20 an hour), which `tailor_skills` already spends once per CV; twenty
  applications added at once trip it, and `SkillMatchRateLimited` goes to the dead-letter queue
  today. The student only ever sees "queued, starts at 14:20".
- **"Request changes" rounds count per destination.** `revisions._STYLE_STRUCTURE_ROUND_CAP` is 2
  per student per kind, so today two rounds are shared across all of a student's CVs.

### 6.14 Cost per programme CV

Owner budget: $100 per student (2026-10-03). Per programme CV, the model calls are:
- **the page read,** once per page, shared by every agency: three statement reads plus up to six
  judge calls (`.claude/rules/llm-ai-security.md`);
- **writing:** one call, plus one repair call at most (§6.7);
- **skill tailoring:** one call (`tailor_skills`);
- **relevance:** up to 40 small Jev questions, about $0.0008 for 20 (§7.2), cached;
- **translation:** one call per non-English fact, only when there are any;
- **two versions,** when needed, double the writing and repair.

The dollar figure per CV is measured in build step 4.4 on real pages and CVs, and recorded here
before step 4.5 ships. A measured cost that puts ten programmes over a student's budget stops the
rollout until it is cut.

**One budget per student, remakes included** (amended 2026-10-20, decision 29). Remakes from
answers, re-reads and confirmed newer CVs count against the same $100, with a cap on remakes per
application set from the step 4.4 measurement. The student never sees the budget; reaching it
queues work for the counsellor to release, it never fails a CV.

### 6.15 Student edits, their own CV and the signature (added 2026-10-20)

- **Edits today.** Students have no edit endpoint (`documents/api.py` has generate, drafts, detail
  and approve only), although decision 3 says the student can edit. `revisions.counselor_quick_edit`
  has no production caller; it copies only `programme` and `render_variant` onto the new draft.
- **A correction to a fact** (a wrong date, a misspelt employer) is made on the student's facts,
  not on one CV. Every CV that uses the fact is remade under §6.12's rules: unapproved ones
  automatically, approved ones with one tap (decision 24).
- **A free-text edit to one CV** makes that CV the student's own. It is never remade automatically.
  When its list changes, the student is offered "make a fresh version"; their edits are not carried
  into it, and the offer says so. No edit layer is replayed over a remake (cut, §6.16).
- **A counsellor's quick edit** follows the same rule, and carries the application, the scholarship,
  the saved list, its digest, the destination and the pinned format onto the new draft, pinned by a
  test.
- **"Use my own CV" for one application** (decision 26). The student picks their uploaded CV for
  that application; the kit serves it, labelled "not checked against this programme's rules", and
  no CV is made for it. Today `packets.py` removes every CV upload from the packet once an approved
  draft exists, so this choice cannot be expressed.
- **The signature is given once** (decision 25). The student draws or uploads a signature image
  once. Every CV whose list has `signature_required` prints it with the place and date, instead of
  an empty line (§8). The image is the student's personal data: stored in the tenant's private
  storage, REDACTED on erasure, never sent to europa.eu or any model. A notarised CV stays a
  to-do for the student (§6.7), as it cannot be done for them.

### 6.16 What the 2026-10-20 review cut

Recorded so they are not proposed again. The owner's test: it must take work off the student or stop
a real failure.

| Proposal | Decision | Why |
|---|---|---|
| Partner universities' own pages read for a joint degree | Cut | A consortium publishes one set of rules; the scholarship-merge half is kept (§6.2) |
| Hand edits kept as a layer replayed over every remake | Cut | Fragile, and rarely needed; §6.15's "your own CV" replaces it |
| An uploaded document contradicting an answer shown to the counsellor | Deferred | Rare, and adds a review step |
| "No abbreviations" as its own key and question | Cut | It would add a question to every CV. §5.3 already takes full degree and institution names from the read diploma or transcript, and asks only when neither holds one |
| Bans beyond links ("no annexes") | Cut | We never add annexes, so the rule is met by construction |
| A header or a declaration on every document; a name in a second script; publication formats and separate publication lists | Deferred (§11) | Niche for these students |
| An Australia Awards renderer | Cut | The seed stops claiming the template instead (§6.10) |
| Separate caps for remakes, budget and limits | Merged | One hidden per-student budget plus queue-and-resume (§6.13, §6.14) |
| Reminders at day 3 and day 7 when no deadline is known | Replaced | The deadline comes from our reading (§6.5) |
| A printed, signed and scanned CV uploaded per application | Replaced | The signature is given once (§6.15) |

## 7. Stage 4: the new section and the relevance engine

### 7.1 Certifications and volunteering (S-036, S-042)
- **Volunteering already exists.** It is `ExperienceEntry.unpaid` (`schemas.py`). Rhodes
  (section 2) and SISGP ("Network/Civil Society Engagement") already print unpaid entries under
  their own headings. The STANDARD, GERMAN_TABULAR and EUROPASS look-alike templates mix them into
  Experience. This stage gives those three a separate "Volunteering" section, printed only when an
  unpaid entry exists. No new field.
- **Certifications are new.**
  - `CVContent` gains a `certifications` list (title, issuer, date), with a matching fact category.
  - The EU payload already names a "certifications" section, which this list feeds.
  - The section prints only when non-empty.
  - Language certificates stay in Languages (R-041). They are not duplicated here.

### 7.2 Relevance engine
- **In reach:** certifications, volunteering, awards and skills, one item at a time.
- **Never dropped:** education, research, publications, experience and languages.
- **The question:** in `jev-relevance-questions.md`. Jev returns one of five answers: asked_for,
  same_field, general_merit, unrelated, cannot_tell. Only "unrelated" at or above the bar
  leaves an item out. The bar starts at 0.9 and is set by measurement.
- **Code decides without asking Jev:**
  - no published requirements: keep everything;
  - language certificates: always kept;
  - an item the programme names: kept;
  - an item the student put back: not asked again.
- **General-merit items.** For a scholarship, all are kept unless its own page limit forces some
  out; then they go oldest first, only as many as needed (owner, 2026-10-14). For a programme, they
  are kept while the CV fits its page target, and left out oldest first when it does not. No university
  publishes a number, so there is no fixed count.
- **Privacy.** Jev sees the programme's requirements and one CV line. It never sees the
  student's name, grades or any other line.
- **Repeatability.** Answers are cached on (requirements digest, item digest, question
  version), so a regenerated CV gives the same result for free.
- **Cost.** About $0.0008 per CV per programme for 20 items.
- **Limiter.** The existing `skill-match` limiter, plus a cap of 40 items per CV.
- **Safety.**
  - It only keeps or leaves out whole items. It never rewrites or adds one.
  - It never copies programme wording onto the CV, the rule `tailoring.py::tailor_skills`
    already follows.
  - Programme text is labelled as data.
- **Funder templates win.** SISGP and Rhodes keep their own sections and
  per-section limits (`funder_templates/`). The relevance engine runs inside them, never
  against them.
- **Measurement before it is switched on.**
  - **The set:** the owner labels about 240 items across 12 programmes and scholarships.
  - **Pass mark:** at least 98% of the items Jev would leave out are ones the owner also left
    out.
  - **Languages:** each is scored separately, and a language below the mark keeps everything.

### 7.3 CV and form agree
- **Selection is allowed.** Declarations cover the academic record and required information,
  and a CV is expected to be selective (`2026-10-13-cv-gaps-research.md` §4). So leaving an
  unrelated award off the CV is fine.
- **Contradiction is not.** A check compares the CV with the application's own data on dates,
  titles and grades. Any mismatch becomes a counsellor note.

## 8. Programme rules read from the page

These are added to the in-repo grammar (`grammar.py`, `grammar_values.py`, `rule_sinks.py`).
The owner of the catalogue reader agreed they belong there, not in the card engine. Each is a
rule in `Program.cv_constraints` carrying its verbatim sentence, and read through the requirement
list (§6). `cv_scope`, `cv_start` and `photo_required` are added to `CONSTRAINT_KEYS`; the other
three fold into existing keys, as the table says. "Not stated" is the absence of a rule.

| Key | Values | What the CV engine does |
|---|---|---|
| `cv_scope` | complete, relevant_only | complete: relevance engine off, keep everything. relevant_only: the engine may leave out unrelated items |
| `cv_start` | from_upper_secondary, from_first_degree, last_n_years + n | Bounds how far back entries go |
| `cv_item_cap` | section + n | Folded into the existing `max_entries_per_section` (one value per section, lowest wins, §6.4), not a `_MULTI_KEYS` key |
| `cv_language` | a language | Folded into the existing `language` key. MVP: a CV language other than English gets the English CV with the rule flagged and a "have it translated" to-do (§6.7, decision 27), never a silent English CV |
| `cv_signature` | required | Folded into the existing `signature_required` key. Adds a place, date and signature line |
| `photo_required` | true | New. Read apart from `photo_allowed`, which today stores "required" and "allowed" alike as `True`. A student without a photo is asked (§6.4 step 2) |

**Rules for applying them:**
- **How they are applied is §6.4.** Page rules are still stored `ADVISORY_HIGH_RISK`
  (`rule_sinks.py`); the requirement list follows them like rules while writing, and §6.7 decides
  what happens to one still unmet.
- **`relevant_only` cannot lower a BINDING rule.** It must never leave out anything a BINDING
  catalogue rule requires. This is the repo's rule that a programme rule may not lower
  enforcement.
- **A missing school-leaving entry is asked for, not invented.** `from_upper_secondary`
  (ETH: "Begin with your UPPER SECONDARY SCHOOL GRADUATION") needs an education fact for
  secondary school. When none exists, `gaps.py` asks for it, and the CV is not printed as if
  complete.
- **A stated cap beats "never dropped".** A programme's per-section cap (`max_entries_per_section`) is its own instruction, so
  it may trim even a never-dropped section, publications for example. It keeps the most recent
  n, lists the rest as left out, and never touches education.
- **A signature is a line, not a signature.** The engine cannot sign for the student.
  `signature_required` prints a place, a date and an empty signature line, and an item on the requirement list (§6.8) tells the
  student to sign it before uploading. The catalog's R-031 (German custom) stays advisory, as today.

### 8.1 Requirement kinds added 2026-10-20

A research pass (2026-10-16) sorted 313 researched rules (`cv-rules.csv`, `cv-style-rules.csv`,
`letter-rules.csv`, the CV-requirement corpus and the format evaluation) into those the engine can
express (135), partly (11), only as an `unapplied` note (15) and not CV page rules (152), then checked
official pages for kinds the corpora miss. Nine BINDING rules in the corpus are mishandled today.
The kinds below are the ones kept by the owner's test for where these students apply; the rest are
in §6.16 and §11. Each new key gets a §6.4 row (the test in §6.4 enforces it). Built in step 4.4;
the DAAD case in step 4.5.

| Kind | Evidence | Handling | Stricter means |
|---|---|---|---|
| "Tabular", "in table form" | R-012, S-008, DAAD PRIME, Göttingen; ETH (S-047) | New `layout = tabular`: the existing German tabular layout in any country. Today it is reached only by programme country (`render._TABULAR_COUNTRIES` = DE, AT), so ETH's "table form" ends `undecided`. Europass meets it | tabular beats any |
| Page size, margins, line spacing | S-003, R-045; TUM ("A4 … 2 centimeters … 1.5-fold") | New CV keys `page_size`, `margins_cm`, `line_spacing` (the letter grammar already has `margins` and `line_spacing`). Today the base CV is 11pt at 1.3 spacing | theirs wins on paper size; the larger value on margins and spacing |
| "In the programme's teaching language" | ETH, DSHS Köln | New `language` value `teaching_language`, resolved by code from the programme record. An English-taught programme is met by the English CV; otherwise decision 27 applies. Unknown teaching language: `undecided` | as `language` |
| "No CV: use our form" | R-015, R-016, R-019, R-022, R-071, R-073, R-076; GKS, MEXT, CSC, Commonwealth | The page reader can produce `structured_fields_only` (today only hand-seeded, e.g. Stipendium Hungaricum, NAWA). No CV is made (§6.2). Form limits ("up to 10 publications") go to the kit, never to the CV | — |
| The institution's own template, with no renderer | R-065, S-021; KUAS ("CVs submitted in other formats will not be accepted"), Perugia "Allegato B" | Shown, not applied: "handled by the official template" with its link (§6.7). The standard CV is never printed as if it met the rule | — |
| Named sections the CV must contain | R-014 (ESKAS, BINDING), S-036; URFU | New `required_sections`. A section with no entries is asked once (§6.5); a section the CV schema cannot hold is shown, not applied | both lists combined |
| Entry fields with no `include` target | R-004 (BINDING), R-065, R-078; Dalhousie | Add the fields the CV schema already holds to the include targets: medium of instruction, relevant coursework, education city and country, supervisor, funding. Institution recognition is shown, not applied | as `include` |
| The page's own gap tolerance | TUM "no gaps longer than 3 months" | `no_unexplained_gaps` reads the page's figure. Today every "no gaps" page is read at `GERMAN_GAP_TOLERANCE_MONTHS` = 3, so TUM is right by luck and a 1- or 6-month page is not | the lower value (existing row) |
| History from elementary school | TUM; uni-assist "from first school"; Australia Awards | `cv_start` gains `primary_school` and `lower_secondary`. A missing entry is asked, never invented (§8) | the earliest start (existing row) |
| "Short CV" or "extensive résumé" with no number | SBFI, TU Delft | Mapped to the existing `cv_scope`: short is `relevant_only`, extensive is `complete` | existing row |
| A stated file name | TU Delft "LastnameInitials-resume.pdf"; NUS, HKU | New file rule `file_name`, applied by code to the downloaded file (§6.8). Campus France's "300 KB" is read as a unit, not dropped | theirs wins |

**DAAD EPOS cannot get a CV today** (R-010, BINDING). It requires Europass and a date of issue.
`date_of_issue_required` is in `_CONTENT_ONLY_KEYS`, and Europass is rendered on europa.eu, which
cannot carry one, so the check blocks the send before any call (`catalog_seed.py` records this). A
date of issue is not personal data, so the block protects nothing. Step 4.5 lets a Europass CV meet it
by stamping the place and date (and the signature, §6.15) on the returned PDF's last page. Because a
step 4.1 test pins that a BINDING `date_of_issue_required` blocks Europass, the change goes through a
security review, which confirms the privacy gate for photo, date of birth and links is untouched.

## 9. Names and military service

- **Names.**
  - The CV prints the passport's English spelling. Azerbaijani passports carry both spellings,
    and in the English one Ə becomes A.
  - The engine never re-spells a name, and never stamps it. `generation.py` deliberately does
    not stamp `full_name`, because a wrong name must be caught by a person.
  - **What this design adds is a check, not a stamp.** When an IDENTITY fact from the passport
    exists (the document fact-reading work, branch `claude/fact-reading-design`, not merged), a
    `full_name` that differs from its English spelling becomes a counsellor note.
  - **Until that work merges,** the name comes from the confirmed facts as today. The given name
    and surname the dashboard collects are the reference the counsellor sees.
  - A diploma or transcript translation spelled differently also becomes a counsellor note.
- **Military service.**
  - Azerbaijani law sets 1 year for men with higher education and 1.5 years otherwise.
    Full-time students are deferred until they finish, including abroad.
  - When service happened, the CV prints one dated line with no detail: "Compulsory military
    service, Armed Forces of the Republic of Azerbaijan, Oct 2024 – Oct 2025".
  - **It reuses the gap statement that already exists.** That is the TIMELINE fact and
    `CVContent.timeline`, printed in date order with the posts by `_experience_rows`. No new
    entry type is needed.
  - **How it gets there:** the student's own CV, or the existing gap question for an
    unexplained period. The engine never asks about military service by gender or age.
  - The relevance engine never drops it; timeline entries are outside its reach.
  - No admissions guide covers this; the rule follows the catalog's gap entries (S-041, S-045).

## 10. Data, migrations, erasure

- **New tables.** One for the relevance cache and one for "put back" and "undo" decisions.
  Each is tenant-scoped, with RLS ENABLE and FORCE, composite tenant guards (pattern:
  `documents/migrations/0026_transcript_pages_tenant_guards.py`), and entries in
  `apps/audit/redaction.py`. No student text is stored, only digests and ids.
- **New fields on `DocumentDraft`.** `render_warnings` (superseded by `requirements` and `requirement_states`, below; not built) holds programme quotes and check
  details, with no student text; it is classified KEEP. `applied_fixes` (§5.5) holds the
  student's original text; it is REDACTED on erasure. Both default to empty, so existing drafts
  need no data migration.
- **`CVContent` field** for certifications, with a matching fact category (volunteering reuses
  `ExperienceEntry.unpaid`, §7.1):
  - **Verification.** They need identities in `verification._identity`, or generation marks
    every such entry UNSUPPORTED.
  - **Every renderer** must carry them:
    - the `cv_base.html` partials;
    - the Europass payload (`europass_payload`, whose printed sections include "certifications");
    - each funder template's nearest section.

    A field a renderer drops is a silent loss.
  - **Existing drafts.** The fields default to empty tuples, so drafts written before them
    still validate.
- **Grammar keys** in §8, and their projections.
- **Requirements first (§6):**
  - `DocumentDraft.requirements`: the saved list's typed items, page sentences and digest. Programme
    data only; KEEP on erasure.
  - `DocumentDraft.requirement_states`: the per-item states, which can name student entries (a
    question's label, a reason); REDACTED with `content`.
  - `DocumentDraft` destination label and pinned format; `funding_opportunity` actually set.
  - A tenant table for pending questions and answers (RLS ENABLE and FORCE, tenant guards,
    redaction entries), written by the worker, read by the web tier.
  - `FundingOpportunity.cv_constraints` and `cv_directives` (shared catalogue, written by
    `runtime_engine` only).
  - The `undecided` rule gains each reading's value (inside the existing JSON; `ConstraintRule`
    gains one optional field).
  - Translations stored as renderings of the original fact (§6.9), REDACTED on erasure.
- **Added 2026-10-20:**
  - `DocumentDraft.application`, a FK with `SET_NULL`. Removing an application calls
    `application.delete()` (`portals/applications.py`), while `DocumentDraftFact.document` and
    `RevisionRequest.document` are PROTECT, so a CASCADE FK would make removal raise. The step 4.2
    plan decides what re-adding a removed application does with its old drafts.
  - `DocumentDraft.requirements` nullable (§6.12): null for drafts before step 4.2, empty for "no
    rules". Each item carries its lasting id (§6.3); `requirement_states` is keyed by it.
  - A "general CV" marker on `DocumentDraft`, so "general" no longer means "no programme" (§6.2).
  - A "hand-edited" marker on `DocumentDraft`, which stops automatic remakes (§6.15).
  - `Program` read status: never read, read, failed (§6.2).
  - The no-CV outcome, the "use my own CV" choice and the read deadline copied onto `Application`
    (§6.2, §6.5, §6.15); `Application.deadline` exists and is simply never written today.
  - The list's intake year (§6.12).
  - The student's signature image (§6.15): personal data, the tenant's private storage, an entry in
    `apps/audit/redaction.py`, REDACTED on erasure.
  - The answers table (step 4.3) keyed by (student, fact, key), not by application (§6.5), with
    "I don't have this" as an answer state.
  - **The relevance cache** (§7.2) holds digests of single CV lines. Keyed only on digests, erasure
    could not reach it, which is the `EuropassRenderCache` pattern
    `.claude/rules/derived-data-and-erasure.md` forbids. It points at `audit.Pseudonym` with
    CASCADE, like every other derived table.
- **No data migration** for already-ingested facts. §4's supersession and §5's detectors handle
  them on the next upload or generation.

## 11. Later, not in this design

- **Translated CVs**, French and German first, for programmes requiring their teaching language.
  - The `language` key (§8) already carries the CV language.
  - Names, numbers, dates and titles are kept exactly.
  - The degree title prints in the original plus a translation (R-034).
  - The guard from `2026-10-12-faithful-rewriting-checks.md` applies.
- **Uploaded CVs in Azerbaijani or Russian:** moved into §6.9 (owner, 2026-10-14).
- **Non-English fixes.** Word lists and verb rules for German, French, Turkish, Russian and
  Azerbaijani; the lists exist in the research file.
- **Central Asian scripts and word lists,** when students from there arrive.
- **Sections splitting across pages** (S-043h): unmet today, not tackled here.
- **Deferred by the 2026-10-20 review** (§6.16): a name, date of birth or title on every document
  (TUM), a declaration with fixed wording (Perugia, DPR 445/2000), document numbers (MEXT), the
  bundle order of a combined file, publication format and separate publication lists (NUS, HKU),
  a name in a second script (Katakana), and showing the counsellor an uploaded document that
  contradicts an answer.
- **A translated "Requirements for CV" screen** in Azerbaijani or Russian (§6.8).

## 12. Testing

- **Fonts in every environment that renders.** The image, CI (`ci.yml` installs the font
  packages before `pytest`) and local development. A test fails with an install hint when the
  default face is not the one embedded (§3.5).
- **Fixed dates.** Date tests pass a fixed `today` (§3.2).

- **Each stage** extends the existing tests:
  - `tests/documents/test_render.py`
  - `test_generation*.py`
  - `test_verification.py`
  - `test_gaps*.py`
  - the grammar tests
- **Cross-agency checks** for any new table run under the `rls_enforced_orm` fixture.
- **Requirements first (§6)**, extending `tests/documents/test_catalog_rules.py` and
  `tests/funding/test_program_cv_format.py`:
  - theirs beat ours, also when theirs is soft; between programme and scholarship the stricter
    wins, one case per row of the §6.4 table;
  - `test_programme_constraints_win_over_every_catalog_scope` still passes;
    `test_a_binding_programme_rule_still_replaces_a_binding_catalog_one` is rewritten on purpose
    (stricter wins now decides it);
  - a merged rule carries the strongest force; `test_a_derived_rule_cannot_unlock_the_europass_pii_egress`
    still passes, plus a new one: a soft page rule cannot let data reach `EUROPASS_API`;
  - every key and directive action has a row in the §6.4 table;
  - no statement text reaches any writer prompt;
  - a `third_party` reading never becomes a rule; its sentence is kept as one for-information item
    (owner, 2026-10-14);
  - for-information items never refuse a CV;
  - a soft content-only item is applied before any europa.eu payload is built and never stops a send;
  - an `undecided` rule without saved readings is for-information;
  - `FundingOpportunity.cv_constraints` round-trips, malformed rows raise; an `undecided` rule's
    readings round-trip; the list round-trips on the draft.
- **Added 2026-10-20:**
  - a scholarship CV never appears in another application's kit; a re-applicant's new card never
    gets last year's CV; only the latest approved CV per application is served;
  - removing an application with a CV attached succeeds;
  - an item's id is the same across two builds of the same list, and across a re-read that changes
    only rule ids and sentence order; the digest is unchanged by the same re-read;
  - rendering a draft never resolves rules live, including a draft whose list projects no rules;
  - a `JOINT_SELECTION` award's rules reach its programme's list;
  - a missing identity, email or rate-limit window becomes a state, never a dead letter;
  - one question for a fact shared by two applications, and one answer re-checks both;
  - the scraped deadline reaches `Application.deadline`, and the reminder ladder fires from it;
  - a hand-edited draft is never remade automatically;
  - a counsellor quick edit keeps the application, scholarship, list, digest, destination and format;
  - each new §8.1 key has a §6.4 row and a projection test;
  - the relevance cache and the signature image are removed by erasure.
- **Gates:** `uv run ruff check .`, `uv run mypy apps config`,
  `uv run pytest -q tests/documents tests/funding` (each checkout has its own test database).
- **The Jev set** (§7.2) runs on the existing evaluation harness. The labelled set is
  committed; run files are kept outside any worktree.

## 13. Open items for the owner

- All eleven judgment calls from the 2026-10-14 review are decided and written into §6 and §7.2.
- The 2026-10-20 review is decided (decisions 22–29, §6.16). Assumptions it rests on, each to be
  checked in the step named:
  - **Programme deadlines** (checked 2026-10-20): none is stored yet (§6.5), so every programme
    card is "deadline unknown" until the funding-card store lands, and the seven-day wait (§6.5)
    carries them. Scholarship deadlines exist only where cycle verification has run.
  - **Erasmus Mundus partners** (step 4.2): a consortium publishes one set of CV rules, and partner
    universities rarely add their own. Judgement, not checked against pages.
  - **Signature image** (step 4.4): a drawn or uploaded signature is accepted where a "signed CV" is
    asked for in an online upload. Some German universities may want a handwritten signature on
    paper; for those the to-do stays.
  - **Documents checked first** (step 4.3): relies on the document fact-reading work on `master`;
    its coverage of the facts questions ask about is not yet measured.
  - **DAAD EPOS** (step 4.5): stamping the place and date on the Europass PDF that europa.eu
    returns is acceptable to DAAD. If not, the date of issue becomes a to-do for the student.

- Two facts on the owner's own CV, needed only when it is regenerated:
  - "10B+" or "3.88M" compounds in the thesis bullet;
  - which LinkedIn address is current.
