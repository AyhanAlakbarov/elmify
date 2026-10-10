# The gap interview: what to ask before generating a CV

A student has paid, and uploaded a transcript and a CV. Between ingestion and
generation there is a step that does not exist yet: **read the ledger against
the target programme, find what is missing or weak, and ask the student for
exactly that — once, before any generation call.**

Asking after generating is the expensive order. It burns a generation, shows a
document built on a gap, and then asks. Asking first costs one analysis call
and produces a better first draft.

Nothing here is built. This is the design.

## Why it is one call, not a conversation

The gap analysis reads the whole ledger and the whole programme profile at
once, because the interesting gaps are *relational* — "you list PyTorch under
skills but no entry says where you used it" is invisible to any check that
looks at one section. One call, one structured list of questions, one form.
A chat loop would cost a call per turn and produce the same questions in a
worse order.

Rate limiting is not optional here and the pattern exists: `apps/ratelimit.py`
`rate_limited()`, as `generate_cv` and `ingest_uploaded_cv` already use it.

## The question types

Each is a schema-constrained output with a `kind`, the evidence that triggered
it, and what a good answer unlocks. The student sees a form, not a chat.

### 1. MISSING_MATERIAL — the CV does not mention something that would help

The hardest and most valuable. Requires comparing the ledger against
`ProgramCompetency` for the target programme and asking about the difference —
not listing every gap, which would be a wall of noise.

The filter that makes this useful: **ask only where the student plausibly has
something and simply did not write it down.** A programme asking for a
competency the student has never touched is not a question, it is a mismatch
the recommendation layer should have caught. Signals that a gap is worth
asking about:

- a competency the programme names that appears in *no* fact, but a neighbouring
  one does (they have PyTorch, the programme wants JAX — ask, do not assume);
- a transcript course whose title matches a programme competency but which
  appears in no CV entry;
- a tool named in a bullet that has no matching skill fact, or the reverse.

Never ask "do you have any other experience?" — an open question returns
nothing usable and wastes the student's attention, which is the scarce
resource in this whole flow.

### 2. WEAK_DESCRIPTION — it is there, but it does not say anything

Rule **S-026** is the yardstick, and it is now in `docs/research/cv-style-rules.csv`:
every bullet answers *what was done*, *how* (method or tool), and *with what
result*, in one or two lines, quantified where a number exists. Oxford Careers
teaches this as CAR (Challenge, Action, Result); the outcome-first XYZ form
("accomplished X as measured by Y by doing Z") is the same content reordered.

So the check is mechanical enough to be reliable: a bullet missing the *result*
clause, or opening with "Responsible for" / "Worked on", or listing a duty
rather than an outcome, triggers one question naming that bullet and asking for
the missing piece — **the number, if there is one**. "You benchmarked
generative frameworks — how many, and what did the comparison establish?"

The question must ask for a fact, never invite embellishment. This is where a
CV generator most easily becomes a CV fabricator, and the whole ledger design
exists to prevent it.

### 3. MISSING_CONTACT — the header is incomplete

Cheapest to detect and cheapest to answer, so it should never be the reason a
CV is weak. `PersonalInformation` has the fields; a null one with no
corresponding link annotation in the upload is a question.

Ask for: LinkedIn, GitHub, ORCID, a personal site, phone. **Ask only for what
is genuinely absent** — since `extract_link_urls` now recovers addresses from
the PDF's link annotations, a CV that hyperlinks a handle no longer looks
empty here, and asking for something already on file is the fastest way to
make a student distrust the tool.

ORCID deserves its own prompt for a research applicant: S-013 puts it in the
contact header, and an applicant with a publication and no ORCID has a
five-minute fix.

### 4. MISSING_GRADE — the grade, its scale, and what it means

**S-027**, researched for this document: the grade goes on the institution's
own scale, mark and denominator together (`16.45/20.0`, `3.82/4.0`), with the
honours classification alongside where one was awarded. For a graduate
application the grade is expected, not optional.

Two questions, both narrow: the mark and scale if the ledger has neither; the
classification if the mark is there but unlabelled. A transcript usually
answers both, so **read it before asking** — an avoidable question is worse
than none.

Two findings worth writing down, because both are things a reasonable person
would otherwise implement:

- **Do not ask how many semesters the grade covers.** Searched; no source
  states it. The degree's own date range already carries the period. S-027
  records this as a negative result so nobody re-derives it.
- **Do not convert the grade.** `16.45/20.0` is the claim; a conversion to a
  4.0 scale is a new claim nobody made, and conversion tables differ between
  the institution, the destination country and the credential evaluator.

### 5. INCOMPLETE_ENTRY — a section is missing a field the reader needs

**S-028**: an academic post names the group or laboratory and its principal
investigator; an industry post names the company; both carry a month-year
range. The supervisor is the strongest single signal on an academic CV and is
the field most often lost, because a CV prints "EPFL | Prof. Schwaller's
group" on one line and the extractor folds it into the employer.

Detectable without a model: an experience entry with `supervisor` null and an
academic-looking employer; any entry with no `end_date` and no "present"; a
research entry with no institution.

### 6. DISCIPLINE_SWITCH — the degree is in one field, the programme in another

**S-029**, and the case that motivated it: a petroleum engineering bachelor's
with substantial ML work applying to a master's in AI.

The degree title is stated honestly and never reworded. Everything else moves:
relevant coursework listed under the degree, projects and methods promoted
above unrelated employment, technical skills placed early. So the questions are
specific to this case and are not asked otherwise:

- *which courses* in the transcript are relevant to the target field (the
  transcript has them; nothing has decided which matter);
- whether unlisted personal or open-source projects exist in the target field;
- for each unrelated role, whether any part of it used the target field's
  methods.

Detecting the case is a comparison the system can already make: the
`Program.name` / `ProgramCompetency` set against the education entries'
`degree_as_awarded`. Confidence should be low-threshold — asking a non-switcher
one irrelevant question is cheap; missing a switcher produces a CV that reads
as a mismatch.

**Note the honest limit of S-029**: the sources for it are commercial CV
guides, not a university careers service. It is the weakest-sourced rule added
in this pass, and it is marked so in the table.

### 7. Sections that do not exist yet

Two questions cannot be asked because `CVContent` has nowhere to put the
answer, and both matter for a research applicant:

- **Conference presentations** (**S-030**) — their own section, separate from
  publications. Merging them either inflates the publication record or hides
  the presentation, and the applicant who motivated this has an IAC paper.
- **Referees** — European academic applications routinely expect named
  referees.

Schema work precedes the question, in that order.

## What must be true of every question

- **It names its evidence.** A question the student cannot trace to something
  in their own material reads as a machine guessing, and they stop answering.
  Same principle as `Technique.excerpt` in `evidence/extraction.py`: requiring
  the quote makes a fabrication cost something.
- **It is answerable in one line or one number.** The student is not writing a
  second CV.
- **Its answer becomes a candidate fact, never a confirmed one.** An answer is
  a student statement — `source_tier=STUDENT_STATEMENT`, `confirmed_by=None`,
  exactly as `ingest_uploaded_cv` writes. The counsellor confirms.
- **It is skippable.** A required answer to an inferred gap is a wall in front
  of a paying student.

## Order of implementation

1. **The deterministic checks first** — types 3, 4 and 5 are field-null tests
   against the ledger and need no model call at all. They are most of the
   value and none of the cost, and building them first establishes the
   question/answer plumbing (`IntakeResult.question` already has the shape).
2. **Types 1, 2 and 6** need a model and the programme profile. One call,
   schema-constrained, following `extraction.py`'s pattern: untrusted content
   labelled as data, output Pydantic-constrained with `extra="forbid"`,
   `max_output_tokens` capped, rate limited per student.
3. **Type 7 after the schema gains the sections.**

## The one thing to settle before building — settled

`tailor_skills` computed its gap list against `category=SKILL` while
`ProgramCompetency` holds what a page asks an applicant to *have*, most of
which a degree or a post answers rather than a skill. A student's own master's
degree was reported as a gap against a programme asking for one.

`skill_pool` is now `fact_pool`: every unsuperseded fact, named by
`verification.fact_label` — the same text `verify_against_facts` puts in
`ClaimVerdict.claim_text`, so both directions share one vocabulary. Exact
matching and `judge_remainder` both run over that pool, and the judge's rows
carry a `category` column so a degree is not read as a skill someone listed.

What *prints* did not widen with it. `printed` is the CV's skills section and
is filtered back to `category=SKILL` on both halves — the ranked matches and
the unmatched tail. Widening the comparison while leaving printing alone is
the same category error in the other direction, and two tests pin each half.

So the gap analysis here inherits a comparison of like with like. Two things
it does **not** inherit, both still open:

- **A CV-uploaded skill still carries no evidence.** `SkillEntry.evidence` is
  None for anything ingestion parses out of an uploaded CV, and the judge is
  told to pair only where the record shows the competency. Those rows now sit
  in a pool alongside the degrees and posts that *do* carry text, so a gap is
  no longer produced by their silence — but they still match nothing on their
  own. Type 1 questions are the natural place to fix that, not this function.
- **`tailor_skills` still has no caller.** When it gains one it must take a
  `RecommendationCandidate`, not a bare `Program`.
