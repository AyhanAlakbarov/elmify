# Review of the generated CV, and what an academic CV should look like

Reviewed 2026-08-30 against `~/Desktop/tehsil-out/generated-cv-abdullayev.pdf`
(01:27) and `generated-cv-v2.pdf` (01:40), both produced by
`tests/documents/test_live_tailoring.py` from
`CV-2026-07-UMR7140-01-ABDULLAYEV-ORKHAN.pdf`. Compared against the applicant's
own original CV.

Both files predate `4d221ba`, so some of what follows is already closed. Each
item says which.

---

## Part 1 — Defects in the output

### 1. The contact header is a run-on line, and the links are dead text

Now:

```
Orkhan Abdullayev
live-b3238d97@apply.example.test · +994 50 753 85 58 · GitHub: 0rkhann · LinkedIn: Orkhan
Abdullayev
```

The original:

```
Orkhan Abdullayev                    Email: orkhan.abdullayev@etu.unistra.fr
LinkedIn: Orkhan Abdullayev
Github: 0rkhann                      Mobile: +994 50 753 85 58
```

Three separate problems wearing one coat.

**a. Layout.** *(Fixed — flex header, this branch.)* `cv_base.html`'s `{% block personal %}` is a single `<p>` of
`·`-separated fragments, so it wraps mid-name ("Orkhan / Abdullayev"). The
original is a two-column block: identity left, contact right. A CSS grid or a
two-cell table in that block fixes it, and the block already exists as an
override point.

**b. The links are not links.** *(Fixed — `extract_link_urls`, this branch.)* "GitHub: 0rkhann" renders as plain text
because it came through `github_username`, not `github_url`, and the template
correctly refuses to build an address from a handle — `https://github.com/<name>`
points at whoever holds that name today, which is the right call and must not
be relaxed.

The real cause is upstream: **the original PDF's links live in PDF link
annotations, not in the text layer, and `ingestion.extract_text` only calls
`page.extract_text()`.** The URLs are sitting in the file and we throw them
away, then correctly decline to guess them back.

Measured against the actual upload, not assumed — every link in that CV is
recoverable in four lines of pypdf:

```
page 0: mailto:orkhan.abdullayev@etu.unistra.fr
page 0: https://www.linkedin.com/in/orkhan-abdullayev-647918235/
page 0: https://github.com/0rkhann
page 0: https://dl.iafastro.directory/event/IAC-2023/paper/76798/
```

All four are discarded today. Note the fourth: that is the IAC paper's landing
page, which would have given the second publication a real link instead of a
bare citation.

The fix belongs in `extract_text`: read `page["/Annots"]` for `/Subtype /Link`
entries and their `/A /URI`, and pass them to the model as a labelled, separate
block ("URLs the document links to"). Then `github_url` and `linkedin_url` get
real, document-sourced addresses and the handle fields stay as the fallback
they were designed to be. The prompt's ban on *constructing* a URL from a name
stays exactly as it is — this supplies one the document actually printed.

Two things to get right when implementing it. DOCX has the same problem and a
different answer (hyperlink relationships in `word/_rels/document.xml.rels`),
so `extract_text`'s two branches diverge here. And these URLs are untrusted
input arriving through a new channel: they must go into the prompt inside the
DATA block, never near the instructions, and `_HTTPS_URL_PATTERN` on the
schema is what stops a `javascript:` annotation becoming an `<a href>` in a
rendered PDF.

**c. The email is a platform mailbox, not a mistake.** `live-b3238d97@apply.example.test`
comes from `generation._call_model`, which stamps
`personal_information.email` with `Membership.application_email` on purpose —
"the platform issues this address, so the model has no authority over it." In
the live test that field is `f"live-{uuid4().hex[:8]}@apply.example.test"`, so
this is test scaffolding showing through, not a hallucination. **But the
product question is real and unanswered:** should a CV the student sends to a
supervisor carry a platform-routed mailbox instead of their university address?
For a tracked application, maybe. For an academic CV emailed to a PI, an
`@etu.unistra.fr` address is itself a credential — it says the sender is
enrolled. Worth deciding before this ships.

### 2. "Bosnia and Herzegovina" for Strasbourg — already fixed

`generated-cv-abdullayev.pdf` reads `Strasbourg, Bosnia and Herzegovina` and
`Baku, AA`. `generated-cv-v2.pdf`, thirteen minutes later, reads
`Strasbourg, France` and `Baku, Azerbaijan`.

`4d221ba` closed both, by two separate checks that are not redundant:
`schemas.CountryCode` rejects `AA` (two capitals that name no country), and
`verification.py`'s city/country comparison catches `BA` (a real code, for the
wrong country). No further action; re-verify on the next live run.

### 3. `Grade: 16.45/20.0 (Highest Honors) (20.0)` — the scale is printed twice *(Fixed)*

`cv_base.html`:

```django
Grade: {{ entry.grade_native }}{% if entry.grade_scale %} ({{ entry.grade_scale }}){% endif %}
```

`grade_native` already carried `16.45/20.0`, so appending `grade_scale` repeats
it. The template is not wrong in isolation — the split between the two fields is
what the model decides run to run, and it decides differently each time (see
`2026-08-30-extraction-non-determinism.md`: `grade_native="16.45/20.0 (Highest
Honors)"` + null in one run, `"16.45/20.0"` + `"Highest Honors"` in another).

Two candidate fixes, and they are not equivalent:

- **Template-side:** suppress the parenthetical when `grade_scale` already
  appears in `grade_native`. One condition, no schema change, tolerant of
  whatever the model does. Ugly but honest.
- **Prompt-side:** state that `grade_native` is the bare mark and the scale
  belongs only in `grade_scale`. Cleaner data; one more clause on a prompt
  already carrying twelve, and the evidence says clauses hold.

Recommend both — the prompt for the data, the template guard because the
extractor is not deterministic and a rendered CV should not depend on it being.

### 4. Experience comes only from the uploaded CV

Correct observation. Nothing else feeds it today: `ingest_uploaded_cv` reads the
PDF and writes `VerifiedFact`s with `confirmed_by=None`, and `generate_cv` reads
only confirmed facts. The uploaded CV is the sole source.

The pipeline for other sources exists and is unwired: `apps/documents/evidence/`
already talks to **Crossref, OpenAlex and GitHub** and is built on the principle
that authorship is never inferred — a model may draft a description, but nothing
becomes a `VerifiedFact` until a human accepts it. `ingest_evidence` has no
caller outside its own tests.

So "test how it writes from GitHub" is a real, scoped experiment: point
`evidence/intake.py` at the repos behind AZIMUTH/MicroKatc and compare the
bullets it drafts against the ones the CV states. Worth doing — a repo says
what was *built*, a CV says what was *claimed*, and the difference is exactly
what a supervisor probes in an interview.

### 5. Bullet text is ragged-right; it should be justified *(Fixed)*

Nothing in `cv_base.html` sets `text-align`. Add `text-align: justify` on `li`
and the research prose blocks. WeasyPrint supports it.

One caveat worth knowing before you like it: justification without hyphenation
opens rivers of whitespace in narrow columns, and these bullets are narrow.
WeasyPrint honours `hyphens: auto` when the element carries a `lang`, via
Pyphen — which is already installed (0.18.1, it arrives with WeasyPrint), and
the template already sets `<html lang="{{ content.document_language }}">`. So
`hyphens: auto` alongside `text-align: justify` is a two-line change with no
new dependency. Render both and compare before committing.

### 6. Awards need a date column, and the months abbreviated *(Fixed)*

Now: `2nd place at Pasha Insurance Hackathon — November 2023`, an inline bullet.
Wanted: title left, `Nov 2023` right, matching Education and Experience.

**This one needs a schema change, not a template change.** `CVContent.awards` is
`tuple[str, ...]` — the date is *inside the string*, so there is no field to
right-align and nothing to run through the `month_year` filter that already
abbreviates months everywhere else.

The change: `AwardEntry(title: str, date: CVDate | None, issuer: str | None)`,
mirroring the other entry models; the template then reuses the existing
`.entry-header` flex row and `|month_year`, and the awards list stops being the
one section that formats its own dates. Touches `schemas.py`, the extraction
prompt, `verification.py`'s `_SPEC_BY_CATEGORY` (awards currently use
`spec.scalar_key`, the bare-string path), all four templates, and the fixtures.
Not large, but not one line either.

Also: `Participation in summer school at the University of Strasbourg` is not an
award. Once `AwardEntry` exists this is the moment to say so in the prompt —
honours and awards are competitive distinctions; attendance goes under
education or is dropped.

### 7. Three things you did not flag, from the same two files

- **`Master's Thesis, Project Title: AZIMUTH: …` as the job title.** The
  original CV prints the employer and group on one line and the role and
  project on the next; the extractor folds them into `title` differently on
  every run (`Research Intern` / `…, Project Title: X` / `… — X`). Measured,
  documented in the non-determinism note.
- **`Supervisor:` never renders.** `_cv_experience.html` prints it when set;
  the original CV's `EPFL | Prof. Philippe Schwaller's group` is being read as
  part of the employer instead, so the field stays null. For an academic CV
  this is a real loss — the supervisor's name is one of the strongest signals
  on the page.
- **Azerbaijani renders as `C1`, not `native`.** The template handles
  `mother_tongue` correctly; the flag arrived false. Also drift.

---

## Part 2 — Section order, and who actually reads these

Sources: Princeton Graduate Career Development, UPenn Career Services, Oxford
Careers, UIC and Missouri career services, `academics.com` (German market),
Wordvice, and *The Professor Is In*. Flagging source quality honestly: the
university career-service pages are the load-bearing ones; several of the
top-ranking "academic CV guide" results are SEO content marketing that agree
with each other because they copy each other, and at least one is a Fiverr gig
promising "ATS-optimized academic CVs." Where the two classes disagree, I went
with the universities.

### Are these read by humans or by machines?

**For what this product does — students applying to master's/PhD programmes and
scholarships in Europe — a human reads it.** Not because parsers do not exist,
but for three converging reasons:

1. **Academic applications do not flow through an ATS.** They arrive via the
   university's own admissions portal, Interfolio, or a shared folder, and land
   in front of a faculty committee. That routing is the whole reason keyword
   optimisation is largely beside the point here.
2. **EU law pushes hard against the alternative.** GDPR Art. 22 gives a right
   not to be subject to a decision "based solely on automated processing" with
   legal or similarly significant effects — and Recital 71 names e-recruiting
   without human intervention as the textbook case. The EU AI Act puts
   recruitment/selection systems in Annex III as high-risk (obligations now
   deferred to 2 Dec 2027 under the Digital Omnibus agreement). The UK ICO's
   March 2026 report sets a high bar for what counts as "meaningful" human
   involvement: the reviewer must have the authority, discretion and competence
   to change the decision, not rubber-stamp it.
3. **Universities are writing this down.** UW's Graduate School guidance (rev.
   April 2026) explicitly prohibits AI from judging potential, likelihood of
   success or fit, and requires committees to document which parts of review
   are human-led.

**The caveat that matters.** "A human decides" does not mean "a human reads
every page." Where volume is high, the realistic pattern is machine-assisted
triage producing a ranked or summarised list that a human then works through —
which is exactly the arrangement the ICO warns can collapse into de-facto
automation. And a scholarship portal is closer to a hiring funnel than a
departmental PhD committee is.

**So design for both, and it costs nothing, because the two agree.** Plain
semantic structure, standard section headings, real text (never dates baked
into images or drawn in table gutters), no multi-column body, selectable text,
consistent reverse-chronological order. That is simultaneously what a parser
needs and what a faculty reader skimming for 30–60 seconds needs. The current
template is already close: single column, real headings, live links, text
layer intact.

One place the two genuinely diverge, and it bites here: **the header.** A
two-column contact block is what the eye wants and what naive parsers most
often scramble. If you rebuild it as two columns, use a CSS grid or a table
whose reading order still runs name → email → phone → links, and check the
extracted text order of the output PDF afterward. That is a one-command check
and worth making a test.

There is also a nice symmetry worth noticing: this repo's own
`CLAUDE.md` records that Tavily §3.2(xvi) forbids automated decisions without
human oversight in high-risk areas, and that every recommendation here is
counselor-reviewed. The same rule that keeps our search provider's terms
satisfied is the rule that keeps a human on the other end of the CV.

### The section order

There is a canonical order, and the sources converge on it. For a **PhD or
master's applicant** (not a postdoc, not faculty):

```
1.  Contact information
2.  Research interests / profile   — optional, 2-3 lines, only if specific
3.  Education                      — reverse chronological, with thesis titles
4.  Research experience            — positions, with supervisor named
5.  Publications                   — full citations, own name bolded, status honest
6.  Conference presentations       — separate from publications
7.  Awards, honours and fellowships
8.  Teaching / mentoring experience
9.  Other professional experience
10. Technical skills and methods
11. Languages
12. Referees
```

Two rules the sources are unanimous on: reverse-chronological *within* every
section, and length matched to career stage — 2–3 pages for a graduate-school
applicant. The current output is 2 pages. Good.

**Where the current implementation stands.** `render._section_order` already
does the important half: `_RESEARCH_SECTIONS` puts Research and Publications
above Experience when the CV has research, `_TAUGHT_SECTIONS` does not. That
matches the guidance and the reasoning in its docstring is sound — content
decides what leads, the programme decides what page limit is enforced.

Four gaps against the canonical order:

- **Awards is rendered outside `section_order`**, hardcoded between the
  section loop and Skills, so it cannot move. It should be a partial in the
  tuple like the others. Position is right for a research-track CV; it is
  frozen, which is the problem.
- **No Conference presentations section.** For a chemistry applicant with an
  IAC paper this is a real omission — presentations are their own currency and
  merging them into Publications either inflates or hides them.
- **No Referees section.** European academic applications routinely expect
  named referees; the schema has nowhere to put them.
- **Skills sits above Languages, both near the bottom.** Correct.

Recommend, in order of value per unit of work: fold Awards into
`section_order`; give awards a real `AwardEntry`; add Conference presentations;
then referees.

### On the style itself

The output is already doing the hard things right — one column, real headings
with rules, `reverse_chronological` applied at a single funnel, publications as
proper citations with the applicant's name bolded, `PublicationStatus` keeping
submitted work out of the published list. Those are the things that make an
academic CV read as competent, and they are the things templates usually get
wrong.

What separates it from the original is entirely in the details this review
lists: a header with hierarchy, a date column that lines up in every section,
supervisors named, prose justified. None of that is structural. Three of the
six items are one template change each; two need a schema field; one needs
`extract_text` to stop discarding link annotations.

The one thing I would add that nobody asked for: **the thesis title belongs
under Education, not only under Research.** Every source that discusses
graduate-applicant CVs puts the degree and its thesis together, because the
first landmark a reader's eye hits is the education block and the thesis is the
single most informative fact in it. `EducationEntry` has no thesis field today.
