# CV style research prompt — visual and typographic conventions

Paste the block below into Gemini Deep Research, Claude, or any research agent. It is
self-contained: it assumes no access to this repository. Run it in more than one tool and
diff the outputs — disagreement between them is itself a signal about which claims are solid.

Output merges into `docs/research/cv-style-rules.csv` (same column layout as `cv-rules.csv`,
IDs `S-001` upward) and a companion design note the default-template redesign will consume.

Scope note for this repository: these findings can only ever shape the STANDARD and
GERMAN_TABULAR render variants. EUROPASS, FUNDER_TEMPLATE and FIELD_MAPPED have externally
fixed forms, and 94 compliance rules (`cv-rules.csv`) already govern format families, page
caps, photo/date-of-birth conventions and portal mechanics. This research is about how the
default template should LOOK when no funder dictates a form.

---

## THE PROMPT

You are doing source-grounded research for a product that generates **master's-degree
application CVs** for international applicants worldwide, reviewed by a human counselor
before anything is sent. The compliance layer (which format a funder mandates, page caps,
photo rules) is already researched and is **out of scope here**. This research covers one
question: **what visual and typographic style serves a master's applicant best when the
university or funder does not dictate a format?**

### Ground rules (apply to everything below)

- **Cite a primary source for every claim.** A university's or funder's own page, official
  guidance from a graduate admissions office, or an official template file. University
  career-centre and writing-centre pages are acceptable but must be labelled as guidance,
  not requirement.
- **Separate binding from advisory.** Almost everything about style will be advisory; say
  so plainly. If you find a style rule a funder actually states in writing, flag it
  prominently — those are rare and valuable.
- **Distinguish admissions CVs from employment resumes.** Most CV style advice online is
  job-market advice — ATS optimization, one-page US resume dogma, recruiter six-second
  scans. Admissions committees are not ATS parsers or recruiters. When a source is
  employment-focused, say so, and do not silently import its advice as an admissions rule.
- **Distinguish master's-level from undergraduate.** US undergraduate admissions advice
  does not transfer. Label it when you meet it.
- **Never present taste as rule.** "Serif fonts look more academic" needs a source who
  actually reads applications, or it is a designer's opinion — label which it is.
- **Report gaps honestly.** "No published guidance found on X" is a valuable finding. Do
  not fill gaps with plausible-sounding general advice.
- Note the date and application cycle each source refers to.

### Already ruled — do NOT re-research

Format families (Europass mandates, funder templates), page and file-size caps,
photo and date-of-birth inclusion by destination, signature/date-line customs,
ATS parsing, whether to include a summary/objective. These are settled elsewhere;
citing them again wastes the run.

### TRACK A — Destination conventions

For each destination, report what a *normal, well-formed* master's-application CV looks
like visually — not what it contains. Cover at minimum: Germany/Austria/Switzerland
(what does "tabellarischer Lebenslauf" mean **visually** — column structure, label
placement, ordering direction), France (grande-école and university master's
expectations), the Netherlands, the Nordics, the UK and Ireland, the US and Canada
(the academic-CV-vs-resume distinction at graduate level), and at least two major
non-Western destinations (e.g. Japan's rirekisho conventions, China, Türkiye). For
each: typical length when uncapped, chronological direction, date format conventions,
and anything a local reader would find *odd* about a generically "international" CV.

### TRACK B — The reader's side

- **B1.** Published statements by graduate admissions offices or scholarship committees
  about CV appearance, length, density, or readability — what do the people who read
  these documents say they want? Quote them.
- **B2.** Any research or credible professional literature on how evaluators actually
  read application documents (skim patterns, time spent, print vs screen). Label
  research as research, not rule.
- **B3.** What makes a CV read as "template-generated" or careless to an academic
  reader — widowed pages, cramped leading, decorative fonts, icon clutter. Sources who
  review applications preferred; label opinion as opinion.

### TRACK C — Element-level conventions for the template itself

For each, report the dominant convention(s) for academic/admissions CVs, with sources:

- **C1.** Section headers: alignment, capitalization, rules/underlines.
- **C2.** Entry layout: date placement (right-aligned column vs inline), location
  placement, bullet points vs prose descriptions — and whether that answer differs for
  research positions vs employment.
- **C3.** Name/contact block: how LinkedIn, GitHub, ORCID and personal sites are
  presented on an academic CV; hyperlink text conventions in a PDF.
- **C4.** Publication entries on a master's CV: citation style, numbering, bolding the
  applicant's own name, DOI/URL presentation.
- **C5.** Language skills: CEFR levels, test scores, self-assessment grids — how are
  they typically laid out outside the Europass grid?
- **C6.** Typography itself: font families actually used in academic documents (and any
  admissions-side comment on them), font sizes, margins, line spacing for a document
  read by committee members in bulk.

### Output format

Two deliverables:

1. **Rule rows** — CSV, columns exactly: `"ID","Rule","Applies to","Scope","Binding or
   advisory","Source (tier)","Source URL [provenance]","Verified for cycle","Confidence"`.
   IDs `S-001` upward. `Applies to` is one of: layout / typography / element /
   reader-evidence. Scope names a destination or `universal`.
2. **A companion design note** — prose, for the template designer: the coherent picture
   the rules add up to, the genuine disagreements between sources, and the gaps where no
   guidance exists and taste will have to decide, so the designer knows which decisions
   are evidence-backed and which are theirs.
