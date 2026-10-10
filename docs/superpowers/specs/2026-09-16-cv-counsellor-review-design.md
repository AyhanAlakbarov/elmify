# The gap interview becomes a counsellor's review

Design, 2026-09-16. Supersedes the three fixed null-checks in `apps/documents/gaps.py`
without removing them: they become the cheapest of three detectors rather than the whole
of it.

## What this is, and why the shape is what it is

Today `gap_questions()` runs three null-checks — missing contact field, missing grade,
incomplete entry — plus the merit-award check added on 2026-09-15. It asks what is
*absent from a field*. A counsellor asks what would *make the document better*, which is
a larger question and mostly not about nulls at all.

**The method is not novel and that is the point.** Cambridge tells students to keep a
"bucket CV… the totally unabridged document where you capture everything… you are never
going to send [it] to an employer"; Harvard GSAS tells them to keep an "archival CV (for
your eyes only!) that lists all the details of everything you've done — tailor from
there". Two careers services on two continents prescribing store-everything-once then
generate-many, which is structurally the `VerifiedFact` ledger (S-048). Nobody does it by
hand. Automating a prescribed method nobody follows is a better product position than
inventing a workflow, because there is no behaviour to teach and the method is endorsed by
the people who read the result.

**One interview, many documents.** Questions are derived from the student's uploaded
documents, asked once, and every answer raises the value of every CV generated from that
ledger afterwards. The student's attention is the scarce resource — `gaps.py` already says
so — and a per-application interview would spend it twenty times over for the same answers.

## Does it ask everything? — the coverage table is the answer

**Audited 2026-09-16 against the catalog, rule by rule, and the first draft of this design
covered about twelve of the thirty-odd rules that concern a fact the student could supply.**
So the design now carries its own coverage table, and "does the review ask everything" becomes
a checkable claim: a rule is either mapped to a detector, mapped to a later moment, or listed
as a gap with a reason. A rule that appears in `docs/research/` and nowhere in this table is a
defect in this document.

Three detectors, ordered by value per unit of risk. The first two need no model.

### 1. Missing fields — deterministic

Exists today for contact fields, grade, supervisor-on-a-post, end dates and the merit award.
**Missing today, and every one is a null-check on a field the schema already has:**

| Rule | Ask when | Question | Value |
|---|---|---|---|
| S-027, Cambridge | a degree with no `grade_native` is **in progress** (no `end_date`, or one in the future) | "What is your grade so far, or your expected classification?" — Cambridge's own sample prints "Second Year, 2.1 expected" | high — **and a live defect today**: `missing_grade` asks every degree "What grade did you *finish* with?", which is the wrong question for the real CV's in-progress MSc. Fixed alongside this design |
| R-041, S-014 | a non-native language has no `test_score` | "Do you have an IELTS, TOEFL or Cambridge score for English?" | **Highest single item.** Nearly every international programme wants a certificate; the real CV reads "English — Advanced (C1)" with no test, and every destination in its pack will ask |
| S-014 | a language has no `cefr_level` | "What is your level in *L*, on the CEFR scale?" | high |
| S-037, S-040 | the most recent degree has no `thesis_title` | "What was the title of your *degree* thesis?" | high — the real CV lists its thesis under Experience and the degree has none |
| S-040 | a degree with a thesis has no `supervisor` | "Who supervised it?" | high |
| S-027, UCC | a completed degree has a grade and no `class_rank` | "Where did you rank in your cohort, if the institution states it?" | high for a non-anglophone applicant: UCC says "interpret grades … indicate range of scores and size of class" |
| S-011 | a publication has neither `doi` nor `url` | "Does this paper have a DOI or a landing page?" | medium |
| S-011 | a publication has `self_author_index=None` | "Are you an author of this paper, and which position?" | medium — decides whether the name is bolded |
| S-011 | a publication has no `year` | "What year was it published?" | low |
| S-035 | an award has no `awarding_body` | "Who awarded *A*?" | medium — the one field every worked sample carries |

**Found only by searching for what the catalog itself lacked (S-050)** — none of these had a
rule, let alone a question, and the first two are binding at named destinations:

| Source | Ask when | Question | Value |
|---|---|---|---|
| Cornell, USC, BU, ASU; R-065 | always, for the highest completed degree | "Was your *degree* taught in English? Can your university certify the medium of instruction?" | **Highest of the nine, and the question promises nothing.** The waiver conditions differ by destination — USC also requires the *country's* only official language to be English, BU requires the transcript to say *sole* language of instruction — so the standard layer gathers the fact and the programme layer decides, per destination, whether it earns an exemption. Needs a schema field: `EducationEntry.medium_of_instruction` |
| ETH ("every university attended, including any mobility or exchange programmes and study programmes which were not completed") | always | "Did you spend a semester at another university — Erasmus or an exchange?" / "Did you start any programme you did not complete?" / "Was any degree a double degree?" | high — ETH treats the omission as the fault; an exchange is an `EducationEntry` the student never thinks to list |
| Toronto Mississauga checklist; Cambridge; HKS | no fact names a role in a society, committee or association | "Have you held a position in a student society, committee or association?" | medium — S-039 still rejects a memberships *section*; as a question it is one line and feeds the community/leadership content three destinations want |
| S-027 (thesis grade) | a **completed** degree has a `thesis_title` | "Was the thesis graded separately, and what did it receive?" | low–medium; DE/NL/Nordic systems. Never for an in-progress degree — a fourth-year applicant has no thesis grade yet |
| Toronto Mississauga | a publication `is_presentation` | "Was this a talk or a poster?" | low |
| Toronto main guide | never fires deterministically; NOTE only if a publication looks like a blog or media piece | — | low |

### 1b. Timeline gaps — deterministic, and the largest single omission of the first draft

Lay the education and experience entries on one timeline; every uncovered span longer than
a threshold is a question: *"What were you doing between Jun 2024 and Sep 2024?"*

Required, not stylistic: ETH ("leave no time gaps: also list periods when you did not attend
school, study or work"), TUM ("must not contain any gaps longer than 3 months"), DAAD PRIME
(R-011), uni-assist (R-020), Harvard GSD ("including information about any gaps"). Germany's
C-002 is already seeded and already *resolves* for a German programme — and reaches a render
with nothing to act on, because the schema cannot hold the answer.

**Prerequisite: a gap-entry shape.** S-045 measured that every gap Cambridge prints has no
employer ("Full-time carer for family member", "3 months' full-time job-hunting"), so it is
not an `ExperienceEntry` — that model requires an employer and a bullet. A small
`TimelineEntry` (start, end, one-line statement) is needed before the answer can be stored.
`TimelineEntry` shipped on 2026-10-05 as the `TIMELINE` fact category (migration `documents/0027`),
so the detector now fires as a QUESTION. A gap row renders in date order among the experience
entries, following ETH's "also list periods when you did not attend school, study or work" (S-047)
and S-041's gap-filler-among-the-roles shape, not in a section at the foot. The render order
follows the page's `order` directive, passed explicitly (`_oldest_first_sections`), rather than
read back off the posts. Two limits: the funder templates print no gap row, and no timeline entry
is mapped to Europass (a test pins the absence), so the `EUROPASS_API` preview is rendered without
gap rows too and the student approves what ships. C-002 now has something to act on: the render's
`no_unexplained_gaps` check counts a gap statement as coverage on the variants that print it
(`STANDARD`, `GERMAN_TABULAR` and the local Europass look-alike), and on `EUROPASS_API`'s real
document and the funder templates, which print none, still reports the gap.

A gap statement is part of the ledger every model reads (owner decision 2026-10-06): the
letter, storyline and tailoring prompts see it, so an illness or a caring period can be part of
the student's story. The letter instruction lets the model tell it and forbids extending it --
no diagnosis, cause, severity, person or detail beyond the statement's own words. Portal autofill
offers it as `timeline.statement`, and europa.eu prints it as a work experience with the
statement as the occupation and no employer (verified live by `europass_canary`, 2026-10-06).
CLAUDE.md, "One ledger, every consumer", is the rule.
Threshold: 3 months, TUM's figure, the strictest one stated.

Two amendments to the above. The span from the last entry to today is asked as well, on ETH's
"right up to the time of application"; its answer carries no end date, so it closes permanently.
Once a later entry has started, that open span ends at the start of the next one (education,
experience, or research where dated), else today (`schemas.open_span_end`): the detector then asks
the gaps after it again, the render's check sees them, and the printed row shows the closing month
instead of "present". The stored fact is never rewritten. Answers are stored as `TimelineEntry`
writes them (statement tidied, dates in ISO), so the CV line verifies against its own fact. And a gap question cannot be dismissed, since it stops
firing only when a fact covers the span, so the interview form offers a list of neutral statements
(`<datalist>`) because answering is its only exit; an answer over 300 characters is refused.

### 2. Absent sections — deterministic

Nothing in a document reveals what it does not mention, but "this ledger holds no facts of
category X" is a fact, and the catalog says which categories a master's CV should have:

- **Voluntary / community activity** — Oxford makes it one of three headings, Utrecht lists
  it, Campus France names it, SISGP mandates it (S-039, S-042). Asked **unconditionally**.
- **Certificates / training** — Queensland, Toronto, Berkeley, German guidance (S-036). The
  real CV filed a summer school under Awards because there was nowhere else for it.
- **Referees** — R-051, for research-track applicants.

One question each, fired when the category is empty, phrased so "no" costs one click.

### 3. Model checks — closed questions from the catalog, not an open review

**The model does not enumerate.** This is the correction of a failure this repo measured
twice: `reader.py`'s open read of one page returned 29–40 statements with no two of eighteen
reads identical (union narrowed it to 47/42/48, did not close it); `derive.py` then replaced
an open judgement with one closed question asked three ways and measured 100% unanimity
against the keyword rule's 61%. An open "what is wrong with this CV" call returns a
different subset every run. So the enumeration is the catalog's and the model answers one
closed question per item:

| Rule | Closed question, per item | Output |
|---|---|---|
| S-049 | "This post ran *N* months and names a supervisor. Does the title *T* fit?" | PROPOSED VALUE (title) |
| S-026 | "Does this bullet state a result, or only what was done?" | NOTE |
| S-026 | "Does this bullet contain a number?" — Cambridge: "numbers have the most impact… capture them while the experience is fresh" | QUESTION: "Is there a figure for this — a percentage, a count, a size?" |
| S-026 | "Does this bullet open with an action verb?" — the real CV has one that opens "A map-agnostic framework…" | NOTE |
| S-028 | "Does this entry name a group or laboratory, or only the institution?" | QUESTION (group) |
| S-037 | "Does this title contain a project name as well as a role?" | PROPOSED VALUE (title) + QUESTION (project) |
| S-025 | "Is this skill technical, or transferable ('teamwork', 'communication')?" — transferable belongs in the bullets that evidence it | NOTE |
| S-025 | "Is this skill evidenced anywhere in the bullets?" | NOTE |

Each is the shape `derive.py` measured as stable. Batched across items, one call per check
family — around eight per ledger version, cached on a digest of the facts read.

**Deterministic where it can be, and this is where:** S-026's "5–6 bullets per role at
most" is a count, and fires as a NOTE without a model.

**What this buys:** coverage is a property of the catalog, not of a prompt — readable,
sourced, and extended by adding a rule. **What it still misses:** anything unresearched. A
check family that does not exist catches nothing; the residue shrinks only as
`docs/research/` grows.

### Searched and deliberately not asked

Recorded so the next session does not re-derive them (S-050): **GRE/GMAT** — no university
source puts it on the CV; it travels on the application form, and the only advice to list it
is commercial. **Driving licence** — a Europass employment field, irrelevant to admission.
**Patents, professional registration** — Harvard GSD asks for the latter; both rare at
master's level, so they live in the *wording* of the certificates and publications questions
("certificates, licences or professional registration") rather than as questions of their own.

### What the review is not for

The review supplies **facts the ledger lacks**. Which facts lead, what is emphasised, how
long the document runs and what it is called at a given destination are the generation and
render layers' job — `cv_directives`, `resolve_rules`, `_section_order` — and are driven by
the programme, not asked of the student. A review that started asking "should Research go
first?" would be doing generation's work badly.

## Scope: this is the STANDARD layer, and it gathers, it does not judge

Owner's framing, 2026-09-16: this design is the *gathering* half of Harvard's archival-CV
method — collect every fact once, from the student's own documents and answers. It never
reads a programme page and never decides what a destination accepts. Programme-specific
rules are fetched separately and applied **on top** of the standard result at generation,
which is already how `resolve_rules` layers a programme's own rules over the catalog's.

Three places this boundary bites, so they are stated:

- **Medium of instruction.** The review asks the fact; whether it earns an IELTS waiver is a
  per-destination rule (USC, Cornell and BU each set different conditions) and belongs to the
  programme layer. The question must not imply otherwise.
- **The pack-gated questions** (German level, ECTS, public repositories) read the pack's
  countries and fields — a property of the *student's own* recommendation set — not a
  programme's page. They are still the standard layer.
- **In-progress degrees.** A fourth-year applicant has no final grade and no thesis grade.
  Every grade question checks completion first; the in-progress form asks for a grade so far
  or an expected classification, which is what Cambridge's own sample prints.

## Two moments, not one

| Moment | What fires | Why not earlier or later |
|---|---|---|
| **Ingestion completes** | Detectors 1, 2, 3 — everything country-independent | The questions are grounded in the document the student just gave us, which is what makes them answerable. A blank form asked before upload gets abandoned |
| **A recommendation pack is published** | The country-gated questions, **and the field-gated ones** | The countries and the target disciplines both come from the pack. Asking the student to name either at intake is a question we can answer ourselves later |

**Three more pack-gated questions (S-050):** *"Your pack includes German programmes — what is
your German level?"* (DAAD asks German-capable applicants for a language evaluation form;
R-041 wants CEFR in Europe) — gated on the pack's **countries**. *"How many ECTS credits was
your degree?"* (R-038 has required it for European programmes since the first research pass
and nothing ever asked) — gated on **region**. *"Do you have personal or open-source projects
with a public repository?"* (Cambridge's own CS sample gives Project Experience its own
heading; for a STEM applicant the repository is the evidence) — gated on **field**.

**Field-gating is the second draft's addition.** S-029 and R-028 want relevant coursework
listed when direct experience in the target field is thin — the discipline switcher's main
lever — and "thin" is judged against the *target* field, which only the pack knows. So
`relevant_coursework` is asked at pack time, for the most recent degree, phrased against the
pack's disciplines: *"Your pack targets AI programmes. Which modules from your BSc in Chemical
Engineering are most relevant?"* Same prerequisite as the country gate: the pack must carry a
structured discipline, and today it carries a free-text `program_name`.

A third moment — programme-specific requirements read off a programme's own page — already
exists as `gaps.programme_required` and is being built out separately. It is **out of scope
here** and this design must not duplicate it.

## Output kinds, and the write contract

Three kinds. The contract with `answer_questions` is what keeps the ledger honest.

| Kind | Writes | Shown to |
|---|---|---|
| **QUESTION** | A superseding fact, or a new one via the create path added 2026-09-15 | Student answers; counsellor sees |
| **NOTE** | Nothing | Both. Prose about the document, e.g. "the ICIQ bullet states a method but no result" |
| **PROPOSED VALUE** | Same as QUESTION, but arrives with a suggested answer | Student |

**A proposal is for typed fields only — never prose.** A title, a date, a grade. The model
may not draft a bullet, because an accepted rewrite would make a model the author of the
student's claim on a submitted document, and refusing that is the ledger's entire premise.
Recorded as a limit, not a phase-two feature.

**Notes are the preferred output wherever the student cannot act.** A note costs a second
to read and skip; a question costs a decision. Tier 1 plus tier 2 already produces more
questions at intake than today, and a long form is where students abandon.

**Counsellor visibility, no counsellor answers.** Notes and questions are both visible to
the counsellor; only the student may answer. That is the existing rule
(`test_a_counselor_is_refused`, and `gaps.py`'s own docstring on why), and a review that
produces notes is the first output genuinely useful to a counsellor without breaking it.

## The model call

- **Input:** the student's own unsuperseded facts, serialised, plus the resolved catalog
  rules. Labelled DATA, never instructions — the reference pattern is
  `apps/research/extraction.py` and `apps/funding/explanations.py`.
- **Output:** schema-constrained, `extra="forbid"`, a list of
  `{kind, fact_id | null, category, payload_key, prompt, evidence, proposed_value | null}`.
- **Server-side validation, not trust:** every emitted `(fact_id, payload_key)` is checked
  against `payload_keys(category)` and against facts belonging to *this* student, exactly
  as `answer_questions` already does. A question naming a key the category does not carry
  is dropped, not asked — `gaps.py`'s docstring already warns that a form must re-derive
  askable pairs rather than trust what it was posted.
- **Rate limit in the same change.** Per-student, via `apps/ratelimit.py::rate_limited`.
  CLAUDE.md requires it of any change that wires up an LLM call, and this is that change.
- **`max_output_tokens` capped.**
- **Cached on a digest of the facts read**, so re-opening the interview is free and a
  re-ingest is what re-runs it.
- **One call per check family, not one per interview.** See detector 3 on why a single
  open call is the wrong shape. A family whose closed question the model refuses or answers
  off-schema is dropped for that run; the other families still produce their questions,
  because a review that fails whole is worse than one that is short.

## The country gate, and its prerequisite

Country-conditional questions are the ones where asking the wrong student is actively
wrong:

- **photo** — customary in Germany (R-030), wrong for UK/US/Canada/Australia (R-032)
- **date of birth, nationality** — same split; TUM requires DOB, Oxford says omit
- **signature and place/date line** — German custom (R-031)
- **secondary school** — ETH wants upper-secondary onward, TUM *elementary* onward, UCC
  and Lancaster say omit (S-047)

**Volunteering is deliberately not on this list.** Searched 2026-09-15: no country was
found whose guidance excludes voluntary or community activity from an admissions CV, and it
is named positively in the UK, Netherlands, France, Germany, Ireland and the US (S-042). A
country gate on that field would return "ask" in every case we have evidence for, which is
a table that does nothing.

**Prerequisite, and it is in another app.** `RecommendationCandidate` carries
`program_name` as a free string and has no `country_code` and no FK to `Program`, so the
countries cannot be read off a pack today. The gate needs one of those added. It is in
`apps/funding`, which is being worked on separately, so this design states the dependency
rather than reaching into it.

**Degradation is safe and is the correct behaviour:** no country known means no
country-gated question fires. Asking a UK-bound student for a passport photo is the
mistake; asking nobody is merely a missed prompt.

## Testing

- Detectors 1 and 2 are pure functions over the ledger: ordinary unit tests, no model.
- Detector 3's *validation* is tested without a model — feed it a fabricated model response
  naming another student's fact, a key the category lacks, and a proposal on a prose field,
  and assert each is dropped.
- One `live`-marked test, excluded from a default run by `addopts`, asserting that a real
  call against the real CV returns questions that all survive validation.
- The rate limiter is tested by exhausting it, as `test_generate_cv_rate_limited` does.

## Read against the code, 2026-09-17 — five things the design got wrong

The design above was written against the catalog. Read against `gaps.py`, `gap_intake.py`
and `verification.py`, five of its claims do not hold. Each is a defect in this document,
corrected here rather than discovered during implementation.

### 1. Every create-path question collides on one form field

`gap_intake.field_name` is `f"{question.fact_id}:{question.payload_key}"`. It was written
when exactly one question had no fact (`missing_award`), so `"None:title"` was unique. This
design adds several: an exchange programme and an unfinished programme create EDUCATION
facts, a society role creates an EXPERIENCE fact, a referee creates a REFERENCE fact, and
the award question is still there. Two questions that both create a fact with `title` post
under one name, and `submit_answers` — which looks answers up *by that name* — writes one
student sentence into both.

**Correction:** `GapQuestion` gains a `slug` for the create path, and `field_name` becomes
`f"{fact_id or slug}:{payload_key}"`. The slug is the detector's own name for the question
("society-role", "exchange-programme"), stable between the render and the submit, which is
the property the whole field-name contract rests on. A question with no fact and no slug is
a programming error, raised at construction rather than silently shadowed.

### 2. NOTE cannot be a `GapQuestion`

The output-kinds table lists NOTE alongside QUESTION, but a note has no `payload_key`, no
`fact_id` to supersede and no answer. Putting it in the same tuple makes `payload_key`
nullable and forces a guard into `answer_questions`, `submit_answers` and `field_name` —
three places, all of them the write path, for a thing that never writes.

**Correction:** notes are their own type. `gap_notes(student) -> tuple[GapNote, ...]`,
carrying `text` and `evidence` and nothing else, rendered beside the questions and never
posted. The write path is untouched, which is the point: it is the only part of this module
with a trust boundary in it.

### 3. The detector-3 cache must not be a table

"Cached on a digest of the facts read" is right, and a Django model is the wrong place for
it. CLAUDE.md's derived-data rule requires any table holding data derived from a student to
point at `audit.Pseudonym` with `CASCADE`, and names `documents.EuropassRenderCache` — a
digest derived from a student's CV with no FK back to them — as the mistake that rule
exists to stop repeating. A questions cache is exactly that shape.

**Correction:** cache in Django's cache backend, keyed on
`sha256(student_id + fact digest)`, the way `apps/ratelimit.py` already uses it. No table, no
migration, no erasure hole, and an entry that outlives an erasure is a key nobody will ever
compute again rather than a row a deletion sweep has to find. It also makes the re-derive
cost honest: the interview page re-derives questions on every GET (`views.py::_page`), so
an uncached detector 3 is eight model calls per page view, not per ingest.

### 4. Certificates has nowhere to land

Detector 2 asks for certificates and training unconditionally (S-036). There is no
`VerifiedFact.Category` for one, no `CertificateEntry` on `CVContent`, and no section in any
template — which is precisely S-036's own complaint, and why the real CV filed a summer
school under Awards. The question is askable; the answer is not storable.

**Correction:** certificates fires as a NOTE, on the same terms as the timeline gaps in 1b
and for the same reason — the counsellor sees it, nobody is asked something the ledger
cannot hold. A `CERTIFICATE` category is a change of its own: model choice, a
`_CategorySpec`, a schema entry, `_PAYLOAD_KEYS`, an ingestion prompt line, a render
section and a Europass mapping. It is not part of this one.

### 5. Volume is not addressed, and is left unaddressed deliberately

Detector 1's ten new rules are per-entry. On the real CV — four experience entries, two
degrees, several publications — they produce something over thirty questions, on top of the
contact and grade questions that already fire. The design says a long form is where students
abandon and then adds one.

**No cap, and the reason is that a cap is a worse failure than a long form.** Dropping the
thirty-first question means the ledger never gets that fact and nothing ever asks again —
silent, and the failure mode this repo keeps recording. The order is what is spent instead:
questions come out in the value order of the tables above (highest first), so a student who
stops a third of the way down has answered the IELTS, medium-of-instruction and thesis
questions rather than a publication's year. Grouping and progressive disclosure are the
presentation layer's, and the presentation layer is not pinned (CLAUDE.md, "Frontend and
design").

## Deliberately not built

- **Prose rewriting.** See "Output kinds". A limit, not a backlog item.
- **A conversation.** These questions are independent of each other and a chat loop costs a
  call per turn to produce the same set in a worse order. `gaps.py` already records this.
- **Re-asking a skipped question differently.** A skip is an ordinary outcome; nagging is
  how a form gets abandoned.
- **Programme-specific requirements.** Out of scope, built separately.
