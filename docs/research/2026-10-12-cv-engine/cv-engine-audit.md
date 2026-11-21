# CV engine audit: origin/master 3f0d3b73 (2026-10-12)

This audit only read code. It used a `git archive` snapshot of origin/master in `scratchpad/master/`, so the working tree was never involved. The two PDFs compared are:

- **v17**: `elmify-out/generated-cv-v17-tailored.pdf`. 2 pages, A4, WeasyPrint, fonts DejaVu Sans plus Noto Serif.
- **Tsenta**: the owner's Tsenta résumé (PDF, not committed). 1 page, pdfTeX.

One render probe was run with no database and no model call: `scratchpad/render_probe.py` → `scratchpad/probe.pdf`. It used the master templates, WeasyPrint 70.0, and the venv's pypdf 6.17. Master pins pypdf >=6.19, but the difference does not matter here.

Paths below are relative to the repo. Citations are line numbers on origin/master.

## Verdict table

| # | Item | Master today | Smallest change |
|---|------|--------------|-----------------|
| 1 | Soft-skill lines in Skills (S-025) | **Not handled** | Advisory gap question or filter for non-technical SKILL facts |
| 2 | Bullets with no verb (S-026, S-043c) | **Not handled** (bullets are copied verbatim by design) | Deterministic lint, then a gap question asking the student to rewrite |
| 3 | Thesis under Education (S-037a, S-040, R-039) | **Partly handled**: Education prints thesis and supervisor, but ingestion still files "Master's Thesis" as an Experience entry and a test pins that | Stop printing a "thesis" Experience entry when the Education entry carries the thesis |
| 4 | Bullet glyphs in the text layer (R-043) | **Still broken** (verified on master templates) | One CSS line |
| 5 | Page caps and compact mode | Caps are **checked, never fitted**. No 1-page or compact mode exists | `max_pages=1` already works as a rule. A compact density class would be new |
| 6 | Entry header (S-034) | Handled: role and dates on line 1, group/employer/place/supervisor on line 2, project not printed | Nothing needed. Optionally restore the project line per programme (R-061) |
| 7 | Fact freshness | **Not handled**: re-uploading a CV duplicates facts, nothing supersedes. A future start renders "– present" | Supersede by identity on re-ingest, and add a "from <date>" render for a future start |
| 8 | Links | Labelled handle with a live link. Never the URL as text (deliberate, per the S-013 amendment) | If paper safety is wanted, make the visible text `linkedin.com/in/<slug>` |
| 9 | AI-use bans (R-087..R-090) | **Partly handled**: rules are seeded and reported by `render_cv_with_warnings`, but **the production path throws the warning away** | Persist or return non-binding violations from the worker render |
| 10 | Contact in body (S-031); name and page number (S-023) | Both handled | (Prints "Name · 1/1" even on one page. Harmless) |
| 11 | Reviewer-cull items (S-022) | Mostly not handled. The final-page check exists but is also discarded in production | See below |

---

## 1. Soft-skill filler in Skills (S-025)

**Where skills come from:**
- `ingestion.py:370-372` copies each skill into a SKILL fact, with its category heading copied verbatim ("Do not invent groupings").
- The evidence path writes "language"/"library"/"technique" skills (`evidence/facts.py:205`).
- `generation.py:332` gives the model only confirmed facts, and the model emits `CVContent.skills` (`schemas.py:598-622`).

**Can the model add a skill the student never stated?** It can add one, but not silently:
- `verification.py:125-133` verifies each skill **by name**. An invented name comes back UNSUPPORTED.
- `approval.py:16,51` treats UNSUPPORTED as blocking, and generation retries once (`generation.py:377-395`).
- **The category is never compared** (`verification.py:126-129, 302-308`), and the generation prompt (`generation.py:217-265`) never says to carry `category` through unchanged. So the model *can* invent or rename a heading such as "Research and communication" without any verdict noticing.

**What happened in v17.** "Scientific writing, data analysis, interdisciplinary collaboration…" passed name verification, so those names were SKILL facts. They were most likely lifted from the student's own uploaded CV of the time; the Tsenta résumé does not carry them.

**Nothing filters soft skills.**
- `grep S-025` finds no hits in `apps/`.
- Tailoring (`tailoring.py:383-396`) keeps every non-"technique" SKILL fact in the printed tail. A soft skill that matches a competency like "strong communication" is even **promoted to the top**.

**Pinned by:** nothing pins S-025. `test_render.py:1428` only pins grouping by category.

**Smallest change** (deterministic, no rewording):
- Add a gap question in `gaps.py` for SKILL facts whose category or name matches a short soft-skill list (writing, communication, collaboration, teamwork, presentation, analysis, leadership…): "S-025: move this into the bullet that shows it, or drop it?"
- Or drop them at render in `_cv_skills.html`, which is a deletion and not a claim.
- Separately, add "carry each skill's category through from DATA unchanged" to the generation prompt.

## 2. Bullets with no verb (S-026, S-043c)

**Not enforced anywhere on the CV path.**
- `generation.py:234-237` requires bullets carried "one for one … do not merge, split, reword". That is by design (S-010), and the comment at 234-235 explains it.
- Ingestion (`ingestion.py:332-334`) keeps one bullet per line verbatim.
- The only S-026 prompt is in `evidence/extraction.py:147-181`, which covers GitHub project descriptions, not CV bullets. It is pinned by `tests/documents/evidence/test_extraction.py:72-79`.

So "A map-agnostic framework that…" passes through untouched. The Tsenta version of the same bullet reads "Built a map-agnostic framework…".

**Smallest change:**
- A deterministic lint in `gaps.py`: flag an experience bullet whose first word is a determiner or pronoun ("A", "An", "The", "This", "I", "My") or a banned opener ("Responsible for", "Worked on").
- Raise it as a gap question: "Rewrite this line to start with what you did."
- The student's answer supersedes the fact. The engine never rewrites the bullet.

**Also unmet:** S-043(c) note form (no full sentences, no closing full stops). v17 mixes bullets that end in "." with bullets that do not.

## 3. Thesis placement (S-037a, S-040, R-039)

**What renders correctly.**
- Education prints `Thesis: …` and `Supervisor: …` under the degree (`cv_base.html:101-104`).
- Fields: `schemas.py:310` (thesis_title) and `schemas.py:315-321` (supervisor).
- Pinned by `test_render.py:1954` (`test_a_degrees_thesis_and_rank_reach_the_page`) and `:2297` (`…supervisor_funding_and_coursework_under_the_thesis`).
- `gaps.py:800-850` asks for the most recent degree's thesis title, then its supervisor.

**What still violates S-037(a).**
- The ingestion prompt **names "Master's Thesis" as a model experience title** (`ingestion.py:355-361`) and sends the thesis name into `ExperienceEntry.project`.
- `_cv_experience.html:35-66` no longer prints `project` (owner decision 2026-09-15).

The result is a "Master's Thesis" Experience entry, which is exactly v17's layout. Its title ("AZIMUTH…") is dropped from that entry, and the comment at `_cv_experience.html:49` measures "3 of 7" content words lost.

**This is pinned as correct by a test.** `test_render.py:313-335` (`test_a_research_position_in_experience_names_its_supervisor`) asserts that "Master's Thesis" renders as an experience role. `tests/documents/test_academic_track.py:57` uses the same shape.

Nothing removes the duplication either. `render.without_duplicated_posts` (`render.py:288`) only reconciles research entries against experience entries, never experience against an education thesis.

**Smallest change.** In `render.py`'s funnel, drop or skip an experience entry whose title matches `/\bthesis\b/i` and whose employer equals the institution of an education entry that carries `thesis_title`. Keep its bullets by moving them? No: a move is a re-filing the student must confirm. So the minimal safe version is:
1. Change the ingestion example so a thesis lands in `EducationEntry.thesis_title`.
2. Turn the "Master's Thesis" experience row into a gap question ("print this under your MSc?").
3. Update the test at `test_render.py:313`.

## 4. Bullet glyphs in the PDF text layer (R-043)

**Engine.**
- WeasyPrint `HTML(...).write_pdf()` at `render.py:13, 379-387`.
- Bullets are a native `<ul>` with `::marker` (`_cv_bullets.html`, `cv_base.html:64-65`), and awards and languages use `<ul>` too.

**Measured.** The same effect appears on v17 and on a fresh render with the master templates (`scratchpad/probe.pdf`):
- **pypdf** (content-stream order, which is the reader `ingestion.py:209` / `apps.research.pdf` and `render._check_final_page_fill` use) puts every "•" as an orphan line at the bottom of each page: 6 on page 1 of v17, 11 on page 2.
- **poppler `pdftotext`** (geometric order) places them inline. So the defect depends on the extractor, and it is real for any content-order reader.
- v17 under poppler also pushes the award **dates** to the end of page 2 (flex `<span>` inside `<li>`, `_cv_awards.html`).

**Fix, verified in a scratch render.** Either of these puts each glyph inline under pypdf:
- `ul{list-style-position:inside}` gives "• Built a model…".
- `ul{list-style:none} li::before{content:"\2022\00a0"; margin-left:-10pt}`. This one keeps the hanging indent and is the better choice.

It is one rule in `cv_base.html`, but it changes metrics slightly, so re-check page counts (see the S-004 note in the catalog).

**Second text-layer defect found, same cause class: DejaVu kerning.** pypdf reads "PyTorch" as "PyT orch", "BoTorch" as "BoT orch", and "Test" as "T est". This is visible in v17's Skills line. Adding `body{font-kerning:none}` removes it (verified). Also a one-line CSS change.

**Pinned by:** nothing. `test_render.py:1332` (`test_bullets_reach_the_pdf_in_order`) checks bullet *text* order only. A guard against regression: assert `"•\n" not in pypdf_text` and `"PyT orch" not in text`.

## 5. Page caps and compact variant

**Caps that exist** (`catalog_seed.py:84-210`):

| Rule | Programme | Cap | Enforcement |
|---|---|---|---|
| R-007 | EMJM Imaging | 2 | BINDING |
| R-008 | Mundus Journalism | 2 | BINDING |
| R-012 | DAAD Study | 3 | BINDING |
| R-057 | i-MESC | 2 | BINDING |
| R-072 | Eiffel | 2 | BINDING |
| R-080 | Rhodes | 2 | BINDING |
| R-023 | taught track | 2 | ADVISORY_STYLE |
| R-024 | research track | 3 | ADVISORY_STYLE |

- SISGP has a per-section entry cap (R-078) through `max_entries_per_section` and `funder_templates/sisgp.py:29-40` (`select_best_entries` keeps 3 paid posts, which is the only truncation in the engine).
- R-070's "2-page cap mode" for Europass is the same `max_pages` rule. There is no separate mode.

**How a cap is enforced.** The engine renders first, then checks (`render.py:571-576`, `_check_max_pages`).
- If the rule is BINDING, `render_cv` raises `PreflightBlocked` (`render.py:1049-1070`). Pinned by `test_render.py:223` and `test_catalog_rules.py:390-396`.
- Nothing fits, shrinks or truncates the document. "Refuse" is the only behaviour.

**One-page cap.** A rule with `value=1` works mechanically: `test_render.py:731` (`…still_fits_a_one_page_cap`) and the R-080 test use 1.

**Compact mode.** No compact density exists. The only style is `cv_base.html:4-19`: A4, 20 mm margins, 11 pt, line-height 1.3.

**Recommendation from the catalog.**
- R-054 says *do not* apply the one-page job-résumé cap to admissions CVs.
- S-009 and R-023 say 1-2 full pages. S-017 gives France a soft 1-page default.
- So a 1-page default would contradict the catalog. A density class within the catalog's bounds is legitimate: 10 pt (S-002 lower bound), 19 mm margins (S-003 lower bound), tighter `.entry`/`h2` spacing.
- **Smallest version:** a `compact` context flag in `_render_pdf` that adds a class to `<body>`, chosen automatically only when a BINDING `max_pages` would otherwise fail. That means one retry render, never content removal.

## 6. Entry header (S-034)

**Current layout** (`_cv_experience.html:66-68`):
- Line 1: **Role** bold left, `Mon YYYY – Mon YYYY` right (nowrap).
- Line 2: `group, employer, city, country — Supervisor: X`.
- The supervisor is suppressed when the group already names them (`schemas.py:403-427`, `distinct_supervisor`).
- The project is **not printed** (owner decision 2026-09-15). The tabular (DE) variant is dates-left (`:2-13`).

This matches S-034 sample 1 and S-007. The S-034 text itself says "needs no change".

**Pinned by:** `test_render.py:2271` (role alone, project not printed), `:2323` (group before employer), `:313` (supervisor).

**Gap.** R-061 (Europubhealth+, BINDING) asks for full project names per experience. The comment at `_cv_experience.html:55-60` admits there is no per-programme switch. Tsenta's "Employer | Role: Project" one-liner is the S-034 third layout, and it is a house choice, not a rule.

## 7. Fact freshness

**Re-upload merges and duplicates. Nothing supersedes.**
- `ingest_uploaded_cv` (`ingestion.py:494-554`) writes every extracted entry as a new **unconfirmed** fact with `source_ref=f"upload:{document.id}"`.
- It never sets `supersedes`. A new document id means even the evidence path's `_previous()` supersession pattern (`evidence/facts.py:81-97`) would not match.
- After the student confirms the new rows, `generatable_facts` (`verification.py:533-544`) returns old and new side by side.

**Consequences:**
- **A newer value conflicts with the old one.** For example, an MSc end date that moved. `_classify` returns CONFLICTING on any matching fact whose compared detail differs (`verification.py:475-477`), and that **blocks** the draft. Education compares dates only (`verification.py:84-90`).
- **A new grade or thesis on the same degree:** grade is not compared. Both facts reach the prompt and the model picks one.
- **A new PhD:** gets added (a new identity). That part is fine.
- Old facts never disappear unless corrected one by one through `gap_intake`/`revisions`.

**Ongoing positions.** `end_date=None` renders as "present" (`cv_dates.py:22-27`; pinned by `test_render.py:889`, `:1399`). `gaps.incomplete_entry` (`gaps.py:1008-1050`) asks "Are you still working as…?". For an in-progress degree, `gaps.py:1050+` asks for the expected graduation date (R-040).

**Future-dated entries are wrong today.** Verified in the probe: an education entry with start Oct 2026 and no end renders **"Oct 2026 – present"**, which reads as already enrolled. Nothing checks `start_date > today`. A future end date prints bare ("Sep 2024 – Jun 2026") with no "expected" label (R-040).

**Smallest changes:**
1. In `ingest_uploaded_cv`, look up an unsuperseded fact with the same category and identity (`verification._identity`), and write the new row with `supersedes=` that fact.
2. In `month_year` or the templates, render a future start as "from Oct 2026" or "starting Oct 2026", and a future end as "expected Jun 2026".

**Data drift worth flagging to the owner.** v17 says "10B+ compounds" while Tsenta says "3.88M compounds" for the same thesis bullet. The two CVs also carry different LinkedIn addresses. One of each pair is stale.

## 8. Links

Master prints a **labelled handle with a live annotation**: the visible text is "LinkedIn: <student name>" and the href is the profile.
- Code: `schemas.py:120-134` (`_anchor_text`), `:174-185` (`handles`, unlinked when no URL is on file), `:188-229` (`links`), `cv_base.html:82`.
- Pinned by `test_render.py:1192` (`…labelled_and_the_address_still_resolves`), which explicitly asserts that `github.com/jane` is **not** in the text, and `:1185`.
- ORCID is the exception: its identifier prints as text.

This is deliberate. S-013 was amended on 2026-08-30 to prefer labelled handles for accessibility. So a paper or link-stripped copy loses the address, which is what happened in v17. Publications print `doi.org/…` and full landing URLs as text (v17 shows this).

**Smallest change if paper-safe is wanted:** make `_anchor_text` return the host and path (`linkedin.com/in/<slug>`) as the visible text, as Tsenta does. That means flipping the test at `:1192`.

## 9. AI-use prohibitions (R-087..R-090)

**What exists.**
- Seeded as `ai_use_policy` rules, all ADVISORY_HIGH_RISK, value PROHIBITS or REQUIRES_DISCLOSURE (`catalog_seed.py:493-600`):
  - L-041 Cambridge (INSTITUTION `gb:university of cambridge`)
  - L-040 Oxford
  - L-039 Edinburgh
  - L-021 Chevening
  - L-024 Rhodes, L-025 DAAD (disclosure)
- Gates Cambridge (R-089) has no own row. It inherits only when the programme's institution canonical key is Cambridge.
- The checker always reports and never blocks (`render.py:786-798`). Pinned by `test_catalog_rules.py:425-446` (institution scoping) and `:451` (`test_an_ai_use_policy_is_always_reported_and_never_blocks`).

**The gap: the warning is discarded.**
- `generate_cv` never consults it (`generation.py:301-395`).
- The production worker calls `render_draft` (`document_worker.py:432, 476`; `europass_render.py:169`). That calls `render_cv`, which **drops every non-BINDING violation** (`render.py:1063-1070`).
- `grep` shows no other consumer of `ConstraintViolation` or `render_cv_with_warnings` in `apps/` or `templates/`.

So nothing in production stops, warns about, or records generating a CV for a Cambridge or Oxford programme. The same applies to S-022's widowed-page warning and to every `undecided`/`unapplied` quote.

**Smallest change.** Have the generate step call `resolve_rules(programme, …)` and refuse, or mark the draft, when an `ai_use_policy=PROHIBITS` rule resolves. At minimum, store `render_cv_with_warnings`'s violations on the draft so the review overlay can show them.

**Owner decision needed.** The comment says "never a gate", following the letter engine. Cambridge's text calls an AI-written CV fraud, so a refusal or a strong pre-generation notice is a product call.

## 10. Contact block (S-031) and name + page number (S-023)

- **Contact.** It sits in the body as a `div.contact-header` flex row (`cv_base.html:79-84`), not in a page header. DOM order is name → email → phone → links, pinned by `test_render.py:1662`. Compliant.
- **Name and page number.** `@page @bottom-center { string(doc-name) " · " counter(page)/counter(pages) }` (`cv_base.html:4-7`), with `h1 string-set` at `:17`. It appears on every page, and v17 shows it.
  - No test pins it. `grep doc-name` finds nothing in tests.
  - It also prints on a 1-page CV ("Test Person · 1/1"), which S-023 does not require. Harmless.
- **Email.** The CV prints `academic_email or application_email` (`generation.py:106-123`). v17 printed a test address, `live-…@apply.example.test`. Pinned by `test_generation.py:398`.

## 11. Things a reviewer would cull for (S-022)

**From v17, against current master:**
- **Degree titles** "MSc. of Complex Systems Chemistry (CSC)" and "BSc. of Chem. Eng." are copied verbatim as `degree_as_awarded`. That field is an identity key (`verification.py:87`), and the engine must not reword it (S-029, R-034).
  - Nothing asks for the full title on the diploma. R-061 (Europubhealth+) is BINDING on "no abbreviations".
  - Smallest change: a gap question when `degree_as_awarded` or `institution_original` matches an abbreviation pattern (`\b[A-Z][a-z]{0,4}\.`, or "(ACRONYM)"). The student's answer supersedes.
- **Mixed trailing full stops on bullets, and mixed group naming** ("Prof. Varnek's group" / "Dr. Robert Pollice group" / "Prof. Carles Bo group"). All verbatim, nothing normalises them. Stripping a trailing "." at render is formatting, not a claim, and is safe to automate.
- **Lower-case "present"** against Tsenta's "Present". A house choice.
- **Sections split across pages** (S-043h). Experience splits on v17. `.entry{break-inside:avoid}` exists but cannot prevent a section split. Unmet by design.
- **Widowed last page.** `_check_final_page_fill` exists (S-022, `render.py:579-621`, universal rule `:887-908`; pinned by `test_render.py:2080-2100`), but per item 9 its result never leaves `render_cv` in production.
- **"Machine Learning architectures"** casing, and the soft-skills heading (item 1).
- **Text layer** reads "PyT orch" and has orphan "•" lines (item 4).
- **Experience order.** The thesis appears as the top Experience entry *and* (once answered) under Education (item 3).
- **MSc grade missing** in v17 while Tsenta has 15.1/20. `gaps.missing_grade` (`gaps.py:703`) would ask, so this is a freshness issue.

## Catalog rules the engine visibly does not enforce today (top 10 by likely reviewer impact)

1. **S-026 / S-043(c) / R-052.** Action-verb, note-form, quantified bullets. Bullets are verbatim with no lint.
2. **S-037(a).** Thesis is never an experience title. Ingestion instructs the opposite, and a test pins it.
3. **S-025.** Skills limited to technical and research skills. There is no filter, and tailoring can promote soft skills.
4. **S-022 / S-009 widowed page, plus all ADVISORY violations** (AI policy R-087..R-090, `undecided`/`unapplied` quotes). Computed, then dropped by `render_cv` in the production worker.
5. **R-087 / R-090 / R-089** as a generation-time stop or notice. None exists; Gates has no own row.
6. **R-043.** A clean text layer. Orphan list markers and kerning splits appear under pypdf.
7. **R-040 + S-033 (future dates).** A future start renders "– present", and a future end has no "expected" label.
8. **R-034 / R-061 / S-029.** Unabbreviated, as-awarded degree and institution names. There is no question and no check.
9. **R-061 / S-038.** Project names per experience. The project line is globally off, with no per-programme switch.
10. **S-043(h) and S-043(f)/(e) consistency.** Sections split across pages; mixed bullet punctuation and group naming are never normalised.

Runner-up: **S-036 / S-042**, which is a certifications and volunteering section. `CVContent` has no field for either, and Tsenta prints "Certifications & Achievements".

## Assumptions and limits

- "Production path" means `document_worker._generate`/`_render` and `europass_render.py`. I found no other caller of `render_cv_with_warnings`.
- I did not establish the origin of v17's soft-skill line, because the student's uploaded CV for that run was not read. Name verification implies those skills existed as SKILL facts.
- The probe used the main checkout's `.venv`, which is from another branch: pypdf 6.17 against master's >=6.19 pin, and WeasyPrint 70.0, which matches the pin. Marker placement is a WeasyPrint content-stream property, so I expect the same result under 6.19.
