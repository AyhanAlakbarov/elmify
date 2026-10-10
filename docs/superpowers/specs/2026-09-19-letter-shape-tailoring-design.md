# The letter follows the page: shape rules derived, defaulted and enforced — with no reviewer

Status: **design, awaiting owner review** (2026-09-19). Authorizes planning only.
Date: 2026-09-19.
Amends: `2026-08-22-phase2-motivation-letter-engine-design.md` (the `ApplicationPrompt` resolution
ladder, `silent_funder.py`, `letter_render.py`) and `2026-09-13-cv-follows-the-page` (the CV deriver,
which this design extends rather than copies).
Reads: `docs/research/letter-shape-rules.csv` (119 `M-` rules, 2026-09-18),
`docs/research/letter-shape-country-map.csv`, `docs/research/2026-09-18-letter-shape-run-1.md`,
`docs/research/2026-09-14-letter-storytelling-evidence.md` (N-04, N-10, N-15).
Owner decisions folded in (2026-09-18/19): no human reviews a finished letter; on ambiguity the engine
takes the safer shape by rule; programmes are grouped by **mode** (track × portfolio × reader), not by
subject; letter and CV rules are derived from **one** read of the page; eligibility checking is its own
spec, next.

## Goal, in three beats

**What and why.** When a programme or scholarship page states how the motivation letter must look —
"no more than 500 words", "minimum 500 words", "1.5 pages", "hand-signed", "typed into the portal",
"name a prospective supervisor", "references to faculty should not be made" — the engine reads it,
stores it against the programme with the sentence it came from, and writes and renders the letter
inside it. Where the page says nothing, the letter takes a sourced default for its application system
and mode instead of the hand-written orders in `silent_funder.py`. The student sees every requirement
the page states, for the letter, the CV and themselves, with its quote.

**The catch.** Nobody reviews the finished letter (owner, 2026-09-18), so the CV path's answer to a
doubtful page — write an `undecided` rule for a counsellor — has no reader here. Every doubt must
resolve by rule to a shape that cannot break the page's requirement, and every rule that blocks must be
a sentence the page verifiably contains. That is why the shape is *derived from verified statements*
and never *extracted from raw text*, and why "safer" is defined per key in §4, not left to judgement.

**What it costs to reverse.** Fifteen typed columns on `ApplicationPrompt` (nine shape, six artifact), one
flag and one filled field on `Program`, one seeded defaults table, one country→system table, two
per-language data tables (terms, formalities), one template, one gate, a post-generation judge check for
untyped text requirements, Application Kit steps for student actions, and extra tokens (not calls) on
the CV deriver's three judge readings. Removing it leaves the columns empty and the template unused;
nothing in the CV path depends on it.

## What exists (measured on master 2026-09-18, not inferred)

- **The letter has a resolution ladder already.** `apps/documents/prompt_resolution.py` resolves an
  `ApplicationPrompt` per programme: VERIFIED row → EXTRACTED from a snapshot → INFERRED
  (`silent_funder.py`) → UNRESOLVED. The EXTRACTED rung reads *raw page text* into four fields
  (`letter_required`, `structure`, `funder_kind`, `document_language`) via `LetterPromptExtraction`.
  Nothing checks that a returned value is on the page.
- **`ApplicationPrompt` has no home for a continuous letter's length.** Caps live only inside
  `questions[]` (`max_words` / `max_chars_incl_spaces` per question, PF-4). `letter_render._check_letter_constraint`
  can enforce `max_words`, `min_words`, `max_chars_*` from `ConstraintRule`s, but no rung writes them.
- **`silent_funder.DEFAULT_ARCHETYPES_BY_FUNDER_KIND` is unsourced.** Five orders keyed by funder kind,
  written to make the plan work; `DEFAULT_WORD_TARGET = 550`, advisory.
- **The CV deriver is the pattern.** `apps/research/reader.py::extract_statements` reads a page three
  times, keeps only sentences verified verbatim against the archive (`verified_statements`), and stores
  them as `ProgramStatement` rows of kind COMPETENCY / DOCUMENT / FORMAT / LANGUAGE / OTHER with
  REQUIRED / DESIRED. `apps/documents/derive.py::candidates` picks sentences by code, `_judge` asks a
  closed question three times in three phrasings (one reading from a second model family), `decide`
  writes an action only on unanimity. `derive._THIRD_PARTY` voids a sentence about a referee's or
  supervisor's document. All of it runs inside the one transaction `program_rules.read_and_derive`
  holds per page.
- **Two templates.** `letter_continuous.html` is a bold header line and a stack of paragraphs;
  `letter_two_section.html` is the MEXT-style two-box form. There is no date, addressee, salutation,
  sign-off or signature anywhere.
- **`Program.academic_track`** (taught / research) exists and nothing populates it. `Program` has
  `country_code`; `Institution` has `country_code`. Neither carries a discipline.
- **The research (119 rules, 59 country rows) found:** order is published almost nowhere and content
  checklists almost everywhere (M-002, M-037, M-052); letter formalities exist in France, Latin America,
  Ireland's visa letter and two pre-printed forms (M-025, M-034, M-084, M-016, M-101); the form is eating
  the letter (M-012, M-014, M-080, M-082, M-077); a **floor** exists (M-091, M-113); naming splits by
  mode — required at ETH Mathematics, Tokyo, NUS, Western Sydney (M-011, M-068, M-049, M-112), discouraged
  in professional programmes (M-062, M-040), forbidden by Fulbright (M-075); "no document required" is a
  real outcome (M-093, M-094, M-095); the heaviest published weight is Hamburg's 40% with rejection for
  quality and for generic or AI letters (M-108).

## Decisions

### 1. The shape is nine typed fields on `ApplicationPrompt`, each with its sentence

New columns, all nullable, written only by the rungs below:

| field | values | safer direction (§4) |
|---|---|---|
| `document_required` | REQUIRED / NOT_REQUIRED / UNSTATED | REQUIRED |
| `min_words` | int | keep the floor |
| `max_words` | int | the smaller |
| `max_chars` | int (incl. spaces) | the smaller |
| `max_pages` | decimal (1.5 is real: M-108) | the smaller |
| `form` | ESSAY / FORMAL_LETTER / PORTAL_FORM | FORMAL_LETTER over ESSAY; PORTAL_FORM only when stated |
| `signed_declaration` | bool | true |
| `naming` | REQUIRED / INVITED / FORBIDDEN / UNSTATED | FORBIDDEN over INVITED; REQUIRED only unanimous |
| `font_family` | text (e.g. "Times New Roman") | the stated one |
| `font_min_pt` | int | the larger minimum |
| `line_spacing` | decimal (1.0 / 1.5 / 2.0) | the stated one; if two, the larger |
| `margins_cm` | decimal | the larger |
| `file_bundle` | SEPARATE / WITH_CV / SINGLE_PDF_ALL | the stated one |
| `handwritten` | bool | true |
| `shape_sources` | JSON: field → `ProgramStatement` id | — |

The last six are **artifact** rules — how the rendered file must look or be packaged — found by the
research on real pages (TSU's Times New Roman 12 / spacing 1.0 / 2 cm margins; Alberta's double-spaced
12 pt; Huddersfield's 12-point; Reading's minimum 11; UCT GSB's 1.5 spacing; Polimi's "combine them into one
pdf"; Otago's handwriting). They exist so that a formatting requirement is *applied at render* (§6) rather
than left as text.

`structure`, `questions`, `document_language`, `header_block_required` stay as they are. A page cap on a
continuous letter therefore has a home (`max_words`/`max_chars`/`max_pages`) and no longer needs a
question to hang on. `shape_sources` is what lets the requirements pane (§7) and any block message show
the page's own sentence; a shape value without a source id is a default, never a page rule.

### 2. The programme carries its mode, filled by the same read

- `Program.academic_track` is set from verified statements: a DOCUMENT/OTHER sentence requiring a thesis,
  research proposal or prospective supervisor → `research`; a sentence stating coursework-only or a
  taught/professional master's → `taught`; silence leaves it blank, and blank resolves as `taught`
  (the safer of the two: it never demands a named supervisor the student cannot supply).
- `Program.portfolio_led` (new bool, default false) is set when a DOCUMENT sentence requires a portfolio.
- Reader kind is `ApplicationPrompt.funder_kind`, unchanged.

A programme is therefore keyed for defaults by facts the page states, with no classifier. Subject is
**not** a key (owner decision 2026-09-19): the evidence splits on mode, and the only subject effect found
is register, which §6 treats as an optional tint, not built now.

### 3. One read, both documents

**The page's language is detected first; candidates are then found in that language.** (Owner, 2026-09-19.)
The reader already knows the page — `readable_text` has the `<html lang>` attribute and the text, and a
per-sentence language detector (the same `lingua`/`langdetect`-class library the CV path would use for
`check_language_mismatch`) settles mixed pages, where an English version and the native one sit on one
URL. With the language known, the candidate finder uses **that language's row** of
`docs/research/letter-shape-terms.csv` — unit words (words / Wörter / mots / palabras / palavras / слов /
kelime / 字 / 文字 / 자), document words (letter / Motivationsschreiben / lettre / carta / мотивационное
письмо / niyet mektubu / 志望理由書 / 학업계획서), signature and declaration words, supervisor and naming
words, portfolio words, thesis and coursework words — one row per language, seeded with the twelve the
catalog quotes (en, de, fr, nl, it, es, pt, ru, tr, zh, ja, ko) and extended per language from research,
never by guesswork. Numerals are normalised across scripts (Western, Arabic-Indic, CJK count words such as
五百字) before the number test.

Two safeguards keep this from becoming a new English bias in another alphabet: **the reader's labels
stay in the set regardless of language** — every DOCUMENT, FORMAT and LANGUAGE statement is a candidate
even if no keyword matched, so a language with a thin row loses nothing the reader already labelled — and
**a detected language with no row at all** falls back to labels only and logs the language, which is
the research backlog's first entry for that language (§10). The table is measured per language in the
eval gate (§8): a language whose recall is low is visible as a language.

The same three `_judge` readings that answer the CV questions answer the letter questions in the same
call — the page is read once, credits are spent per page, not per document. The judge reads the
sentence in its own language; the questions are closed and the answers are typed, so nothing about the
value depends on the page being in English. Each letter question is closed:

- *Does this sentence set a length limit on the applicant's letter or statement? If so: which measure
  (words / characters / pages), which bound (maximum / minimum / approximate), and what number?*
- *Does this sentence say the document is a letter with date, addressee, salutation or signature; an
  essay; or a field in an online form?*
- *Does this sentence require the applicant to sign a declaration about the document?*
- *Does this sentence require, invite, or forbid naming a specific professor, group, lab or module?*
- *Does this sentence say a letter, statement or essay is required, or that none is required?*
- *Does this sentence say the programme requires a thesis or supervisor, or is coursework-only?*
- *Does this sentence require a portfolio?*

`derive._THIRD_PARTY` applies unchanged: a sentence about a referee's, supervisor's or host's document
sets nothing. A sentence the judge reads as *approximate* ("about one page", "roughly 500 words") is
recorded as a cap, not a floor — approximate language never creates a minimum.

### 3b. Every requirement is applied — by the renderer, by the writer and checked, or by the student

"Verified" means *the sentence is on the page*, not *we have seen it before*: a sentence never met is
verified exactly like a familiar one. What the closed questions cannot do is *type* a requirement they
were not written for. The owner's rule (2026-09-19): **if it is a requirement, it is applied** — there is
no "shown but not applied" state. So every letter-candidate sentence the judge confirms as a requirement
on the applicant's document lands in exactly one of three application paths, decided by one further closed
question — *is this about the text, about the file, or about something only the applicant can do?*:

1. **Applied at render** — artifact rules: font, size, spacing, margins, page count, file bundling
   (§1's artifact fields, §6). Code applies them and the render checks them; a rule the renderer cannot
   satisfy (a font we do not ship) blocks with the sentence.
2. **Applied by the writer and checked by the judge** — text rules with no typed key yet ("in the third
   person", "do not repeat the CV", "address the three questions in order", "mention your language
   level"). The sentence is injected into the generation prompt as data — *"The programme states: '<sentence>'.
   Write so that this is satisfied."* — and after generation the same three-reading judge is asked, per
   such sentence, *does this letter satisfy the stated requirement?* A unanimous **no** triggers the one
   bounded regeneration `letters.py` already has; a second no blocks with the sentence. A model checks what
   code cannot, three ways, and the letter never ships on an unchecked requirement.
3. **Applied by the student** — things neither code nor model can do: hand-write, hand-sign, print and
   scan, attach a paper form, obtain a stamp. These become **Application Kit steps** (the glass-box design,
   2026-09-15) carrying the sentence and its URL, so the student performs them and ticks them; the letter's
   Kit entry is not complete until they are ticked.

Whatever the path, the sentence is **shown** in the letter pane (§7) with its status — *enforced at
render* / *written to and checked* / *your action* — and **counted**: a management command lists path-2
and path-3 sentences by frequency across the catalog, and any kind seen on three or more programmes
becomes the next closed question and, where the renderer can carry it, the next typed field. No
requirement ever **lowers** a typed rule: a path-2 sentence cannot relax a cap the page also states.

The CV path's `unapplied` rules are the precedent in machinery only (`constraints._MULTI_KEYS`); the word
`unapplied` is not used here, because nothing is.

### 4. Ambiguity resolves by rule to the safer shape — never to a warning

`decide` writes a shape value on **unanimity** of the surviving readings. Short of unanimity it applies,
per field, the safer-direction column of §1: the smaller cap; the floor kept if any reading found one;
FORMAL_LETTER if any reading says letter; PORTAL_FORM only if all say form (a wrongly assumed form drops
the letter's prose); `signed_declaration` true if any reading says so; `naming` FORBIDDEN if any reading
says forbidden, REQUIRED only if all say required, otherwise INVITED if any says invited, else UNSTATED;
`document_required` REQUIRED if any reading says required. Two caps in different units (500 words and
3,500 characters) are both kept and both enforced. The disagreement is **logged** with the readings for
the eval gate (§8) — not shown to anyone at run time, because no one is there.

The ladder's precedence holds: a VERIFIED row beats everything; the EXTRACTED shape above beats the
defaults; a page with no candidate sentences takes the defaults. A programme's shape is re-derived only
when its page text changes (`content_sha256` cache), as the CV rules are.

### 5. Defaults are one seeded table, sourced row by row

`LETTER_SHAPE_DEFAULTS[(system, track, portfolio_led, funder_kind)]` replaces
`DEFAULT_ARCHETYPES_BY_FUNDER_KIND`. Each row carries: archetype order; what the opening does and what the
closing does (positive moves, e.g. system B: name the programme and state the purpose in the first
sentences, close by returning to the reasons — M-040, M-044, M-045; system C: open with the problem or
present research position, close on career in two or three sentences — M-052, M-056); `form` default
(FORMAL_LETTER for system A in France and Latin America, ESSAY elsewhere); a default target length
(replacing the single 550) — and the `M-` ids it rests on. Every row cites a rule; a cell with no rule
stays empty and inherits the system-level row. The **system** comes from a seeded
`COUNTRY_SYSTEM[country_code] → A..F` built from `letter-shape-country-map.csv`, with `funder_kind`
overriding it (a DAAD letter is system D whatever the university's country; an immigration authority is F).
Countries the map leaves unassigned resolve to system B's plain essay — the shape that breaks no
formality rule anywhere — and the resolution is logged, so the first real applicant to such a country
surfaces the gap.

### 6. The letter is written and rendered inside the shape

- **Generation** (`letters.py`) receives the shape as data: target length inside the cap and above the
  floor (aim at 85% of the smaller cap; never below the floor), `form`, `naming`, and the default row's
  opening/closing moves and archetype order. A `naming = FORBIDDEN` shape adds one line to the prompt
  forbidding named people, groups and labs; `REQUIRED` requires a confirmed research-fit input (the
  2026-09-15 fit design's `NarrativeInput`) and **stops with a named reason** — `NotGeneratable("naming
  required, no confirmed fit")` — when none exists, rather than inventing a professor.
- **Render** (`letter_render.py`) enforces `min_words`, `max_words`, `max_chars`, `max_pages` as BINDING
  `ConstraintRule`s built from the shape, each carrying its sentence; `_check_letter_constraint` already
  knows the keys. A floor failure blocks like a cap failure — HBKU and Qatar University reject under the
  minimum (M-091, M-113). The artifact fields drive the template: `font_family`, `font_min_pt`,
  `line_spacing` and `margins_cm` become CSS on the rendered page (with a shipped-font allowlist — a
  requested family we do not ship blocks, never silently substitutes; **amended 2026-09-23,
  owner: never silently substitutes a font of DIFFERENT METRICS.** The image ships
  `fonts-liberation` beside DejaVu, so "Times New Roman", "Arial" and "Courier New" render at
  the metrics they publish — measured in the built image, 600 words at 12pt is 2 pages in
  Liberation Serif and 3 in DejaVu Serif, so the old rule refused a letter that fitted. What
  the substitution costs is the NAME the PDF records, never the page count; the Microsoft
  originals are Monotype's and cannot be embedded in a document we distribute); `file_bundle = WITH_CV` or
  `SINGLE_PDF_ALL` makes the download route hand back one combined PDF; `handwritten = true` is a path-3
  student action (§3b), and the renderer produces the text for the student to copy, not a typed letter
  presented as the submission.
- **Template.** A third template, `letter_formal.html`, selected when `form = FORMAL_LETTER`: place and
  date line (date formatted for `document_language` by the existing `cv_dates` tag); addressee block — the
  programme's committee or coordinator as named in `ApplicationPrompt` (or the programme's own name when
  none is named); a salutation and sign-off from **`docs/research/letter-formalities.csv`** — one row per
  language with the salutation formula, the closing formula, whether a place-and-date line is customary,
  and the source rule id — seeded from the research (fr: M-025; es: M-034; pt: M-101; en: M-016; de: the
  DAAD/uni-assist letters) and extended per language **only from a sourced row**. A letter whose
  `document_language` has no row falls back to ESSAY form and logs the missing language; it never carries
  a salutation borrowed from another language. Then the applicant's name and a signature line when
  `signed_declaration` is true or the system default says hand-signed (DAAD EPOS, L-027).
  `letter_continuous.html` stays for ESSAY; `PORTAL_FORM` uses the existing FIELD_MAPPED path.
- **One new gate**, `NAMING_FORBIDDEN` in `letter_gates.py`: when the shape forbids naming, no unit may
  contain a capitalised multi-word phrase that resolves to a person, group or lab of the target
  institution — reusing `check_claim_coverage`'s proper-noun detection against the programme's
  `ProgramStatement` RESEARCH rows and institution name. A hit blocks; there is no override, because there
  is no one to override.

### 7. The requirements are shown, with quotes, and the applicant pane says what we do not check

`apps/funding/requirements.py::program_requirements(programme)` returns three panes, read-only, from data
already in the catalog:

- **letter** — the shape fields with their sentences, plus every requirement sentence about the letter,
  statement or essay with its application status from §3b (*enforced at render* / *written to and
  checked* / *your action*); the student-action items are the same objects the Application Kit shows;
- **cv** — `cv_format_requirement`, `cv_constraints`, `cv_directives` and their sentences (the CV path's
  existing derivations);
- **applicant** — every COMPETENCY, LANGUAGE and OTHER statement with its REQUIRED/DESIRED mark, **as text
  with no verdict**, under a fixed label: *"Stated by the programme. Not yet checked against your record."*
  The check is spec 3; this pane is built so that spec replaces the label with a verdict per item without
  rebuilding the pane.

Every item carries `text`, `source_url`, `requirement`, and the statement id. The window that shows the
three panes is the presentation layer's; the module ends with a `SHOULD BE DONE BY AYKHAN` note at the
seam (owner rule, 2026-09-17), and the service is the one thing the window calls.

### 8. What proves it

- **Deterministic tests** for every §4 rule: two readings disagreeing on a cap → the smaller; one floor →
  kept; one "letter" → FORMAL_LETTER; one "forbidden" → FORBIDDEN; two "required" and one "invited" →
  INVITED; approximate wording → cap not floor; a referee's-document sentence → nothing set.
- **`docs/research/letter-shape-eval.csv`**: ≥60 real sentences drawn from the `M-` catalog **in their
  original languages** — English (Hamburg's "maximum length is 1.5 pages", HBKU's "below the minimum word
  count will not be accepted", Fulbright's "References to proposed universities or faculty should not be
  made"), German (TUM's "maximal zwei DIN-A4-Seiten"), French (Sciences Po's "en maximum 1 000 mots",
  Eiffel's "sur une ou deux pages"), Spanish (Chile's "extensión máxima de 500 palabras", UNAM's "máximo
  de 2 cuartillas"), Portuguese (USP's "de até 2 páginas"), Chinese (TMU's 讀書計畫 / 自傳), plus the
  Korean byte cap and the Japanese single-spacing rule as read from their pages — with the expected
  shape, pinned by a `live` gate in `tests/documents/test_letter_derive.py` modelled on
  `cv-format-eval.csv`. Every language in the sheet gets its own recall and precision line in the gate's
  output, so a language the judge reads badly is visible as a language, not averaged away. It is re-run
  before any change to the judge prompt; the bar is zero wrong caps and zero missed `naming = FORBIDDEN`
  in every language present.
- **A held-out acceptance country, drawn before any rule is edited** (owner rule, 2026-09-18: the engine is
  general, not a country fit). One country whose pages are in a script the eval sheet does not train on
  (candidates: Japan, Korea, Saudi Arabia, Russia) is chosen and sealed at plan start; its programmes are
  read once at the end, and the shapes derived are checked by a human against the pages. Per-country
  numbers on the eval sheet are development scores; this one is the acceptance score.
- **Render tests**: a France-mapped programme with no page shape renders `letter_formal.html`; a UK-mapped
  one never does; a `min_words` floor blocks a short letter with the page's sentence in the message; a
  FORBIDDEN shape blocks a letter naming a professor; a REQUIRED shape with no confirmed fit raises
  `NotGeneratable`; a `font_family` we do not ship blocks rather than substitutes; `line_spacing` and
  `margins_cm` reach the rendered CSS.
- **Application-path tests** (§3b): a text requirement with no typed key reaches the generation prompt
  verbatim as data and is judge-checked afterwards; a unanimous "not satisfied" regenerates once, then
  blocks with the sentence; a "handwritten" sentence produces an Application Kit step and marks the letter's
  Kit entry incomplete until ticked; no path-2 sentence can relax a typed cap.
- **Language tests**: a page detected as French selects the French term row; a mixed English/Japanese page
  is split per sentence; a language with no term row still yields every DOCUMENT/FORMAT candidate and logs
  the language.
- **Defaults tests**: every `LETTER_SHAPE_DEFAULTS` row cites at least one existing `M-` id (a test reads
  the CSV); every `COUNTRY_SYSTEM` entry is a row of the country map.
- **Isolation**: unchanged — `ApplicationPrompt`, `Program`, `ProgramStatement` are shared catalog tables;
  nothing here reads student data at derivation time. `tests/tenancy/test_database_isolation.py::_SHARED_TABLES`
  is the list to keep true.

### 9. Cost, stated

The letter questions ride on the CV deriver's existing three judge readings per changed page — more
tokens per call, no new calls — inside the transaction `read_and_derive` already holds, so the
idle-in-transaction cost the repo flags for that path is unchanged in count and slightly longer in
duration. Six model calls per changed page remains the ceiling. Nothing runs per student.

### 10. The research is a sample, and the design says so

119 rules over roughly seventy institutions, read in one day, English-first: that is a sample of how
letters are shaped, not the population. The country map's own coverage table shows where it is thin —
Central Asia, the Caucasus, Africa outside Egypt and Ghana, Latin America beyond four institutions, and
non-English pages generally, which the three runs reached mostly through English-language versions. Three
things follow, and each is part of this design rather than a hope:

- **The engine does not depend on the sample being complete.** Candidates come from the reader's labels
  (§3), unknown requirements are kept and obeyed rather than dropped (§3b), and defaults fall to the
  shape that breaks no rule anywhere (§5). A page the research never saw is read exactly like one it did.
- **The sample grows from production, in a loop with a counter.** Every path-2 and path-3 sentence (§3b)
  is a research finding logged with its URL; the counting command is the research backlog. The next
  research pass runs **after specs 2 and 3 are written** (owner, 2026-09-19), and its first target is
  already known: official pages read in their **own language** (de, fr, es, pt, ru, tr, zh, ja, ko, ar),
  because runs 1–3 read the English versions where both existed and the formalities live in the
  originals; its second target is every language the detector met with no term row.
- **Acceptance is measured on a country the sample did not touch** (§8), so "it works on the 119" can
  never be mistaken for "it works".

## Deliberately not built, and what would trigger it

- **Eligibility checking against the student's record** ("20 ECTS of theoretical computer science"): its own
  spec, next. Prerequisite: course-level facts from transcripts (course, credits, a disputable subject
  class); a typed requirement parser; a deterministic checker with an honest third verdict, *cannot verify*.
  §7's applicant pane is shaped to receive it.
- **Paragraph order read from the page.** Almost no page publishes one (research, 2026-09-18); defaults carry
  it. Trigger: a programme found stating an order.
- **Subject tint on register** ("write technically" vs an intellectual question). Trigger: mode-keyed
  defaults measured and a register complaint traced to subject.
- **Seeding the rest of the `M-` catalog as mechanical rules.** Only the defaults table, the caps and the gate
  are code; 119 rows stay prose, exactly as the `S-` catalog does, and this line exists so nobody assumes
  otherwise.
- **The second-engine reconciliation of the scholarship system** (run D died twice at the silence limit);
  system D rows stand on the direct read.
- **Re-examining L-001–L-073** — the owner's separate item.
