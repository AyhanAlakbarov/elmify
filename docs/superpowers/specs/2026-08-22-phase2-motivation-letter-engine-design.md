# Phase 2 design: Motivation-letter engine (§4.2)

> **Amended 2026-09-15** by `2026-09-15-letter-research-fit-design.md`: `programme_evidence` is
> populated from `ProgramStatement(kind=RESEARCH)` rows; a `SOURCED` claim is verified against the
> archived snapshot and its origin, not accepted on a non-empty URL; and a named group, person or
> paper enters a letter only after the student confirms the cross-reference in the overlay.

Status: **design, ready for an implementation plan.** Date: 2026-08-22; revised 2026-08-22 against
Track A research and 2026-08-23 after product review (decisions 7–11 below).

Extends `2026-08-21-phase2-cv-engine-design.md` (fact ledger, `DocumentDraft`, `RevisionRequest`,
audit, storage, hygiene). Scope is `phased requirements.md` §4.2 only — §4.2.1 counselor review UI
and §4.2.2 storefront stay deferred, as in the CV doc.

## Research basis

`docs/research/2026-08-22-letter-ruleset.md` (Track A, 71 rows in `docs/research/letter-rules.csv`,
`L-` prefixed). Every structural decision below cites the row it rests on. Rows still marked
unverified in the CSV's open-questions table (Chevening per-answer word limit, Türkiye character
limit, SISGP 2026/27 questions, Commonwealth 2027/28 limits, Fulbright per-country page limits) load
with `verified_for_cycle = null`, exactly as the CV loader treats "unconfirmed" rows.

Three findings reshaped the draft (the rest confirmed it):

- **Structure is a property of the prompt, not the country or the document** (L-065). The same
  engine has to produce five 150-word form fields for an immigration authority (Australia GS,
  L-001), four capped short answers (Chevening, Gates, Commonwealth), a continuous letter (DAAD,
  most European programmes), two statements that must not repeat each other (US SOP + PHS, Fulbright,
  Rhodes, GKS) and a prescribed two-section research form (MEXT).
- **Narrative weight is a property of the prompt, not the country** (priority question 2). The US
  SOP is academic; the story goes in the PHS. The amount of personal background is governed by
  whether the prompt carries a `PERSONAL_BACKGROUND` archetype, and the through-line must be
  evidence-anchored everywhere.
- **Reuse is not penalised anywhere; generic content and breached caps are** (priority question 3).
  Core narrative + regenerated programme paragraphs is consistent with every rule found.

## Settled decisions (product calls, not research-dependent)

1. **Scope: §4.2 only.**
2. **The engine authors the narrative — the student does not write it.** The student supplies facts
   and the system writes. The bar is authored prose with a through-line, not verified facts
   arranged into paragraphs.
3. **Claims are generated with the prose**, not extracted by a second LLM pass.
4. **Reuse-vs-regenerate is a deterministic rule** over stored attributes, never a model judgement.
5. **Two style rounds on the core narrative; per-programme letters uncapped.** §4.2 places the cap
   on the narrative. The rate limiter, not a round cap, is the cost circuit-breaker. Counselor
   quick-edit stays uncapped, as in §4.1.
6. **AI-use policy is reference data surfaced to the counselor, not a generation gate** (2026-08-22
   decision in `docs/research/2026-08-20-cv-ruleset.md`). It never delays a letter.
7. **No up-front questionnaire (2026-08-23).** The engine drafts everything a prompt asks for —
   motivation, research plan, return plan, impact, language plan — as a proposal. The student
   corrects it in revision if they want to. Nothing is asked of the student before a draft exists.
8. **Student attestation is verification (2026-08-23).** Past facts — degrees, jobs, grades,
   awards, projects — come only from the ledger, but a fact the student states (at intake or in
   revision) enters the ledger and is used immediately. Counselors do not fact-check. The student
   is told once, at intake and in the terms, that they are responsible for the truth of what they
   assert and that funders treat false claims as fraud (L-041, L-013, L-059). The fabrication gate
   exists to stop the *model* inventing, never to second-guess the student.
9. **Clean drafts auto-approve (2026-08-23).** A draft with no flag is usable without counselor
   review; the counselor queue holds flagged drafts only. `phased requirements.md` §4.2.1 amended
   the same day.
10. **Agent first, counselor last (2026-08-23).** Whether a letter is wanted, what shape it takes
    and what the funder rewards are resolved by the research agent; a counselor sees a task only
    when the agent finds nothing or finds contradictions.
11. **Advise once, then comply (2026-08-23).** A student-requested change that weakens the letter
    against a published rubric gets one concrete explanation and an alternative; if the student
    still wants it, it is applied and the advice is recorded. Hard rules (caps, wrong institution,
    model-invented facts) stay unbreakable for everyone. This is the CV doc's `ADVISORY_HIGH_RISK`
    tier applied to prose.

## Design

### Document kinds

`DocumentDraft.kind` gains `CORE_NARRATIVE` (no programme, never rendered, never sent) beside
`MOTIVATION_LETTER` (always has a programme and an `ApplicationPrompt`, plus `derived_from` FK to
the narrative draft it descends from). `derived_from` makes reuse auditable and stops a new
narrative version retroactively altering already-approved letters.

The 2-round cap then needs no new mechanism: the CV design's counter already filters
`document__kind=kind`, so making the narrative its own kind places the cap correctly.

**There are no further kinds.** The draft's open question — a form-answer kind and a study-plan
kind — is closed by L-065: shape belongs on the **prompt record**, not the document. A Chevening
answer set, a MEXT research form and a DAAD letter are all `MOTIVATION_LETTER` drafts generated
against an `ApplicationPrompt` whose `structure` differs. Australia GS is a `SHORT_ANSWER_SET`
with `immigration=True`, nothing more. A single `STUDY_PLAN` kind would have been wrong three ways
at once (MEXT, GKS and CSC ask for three different things — priority question 1).

### `ApplicationPrompt` (funding app)

A fact about the programme, not the document, so it lives beside `cv_format_requirement`:

- `programme`, `cycle`, `source_url`, `confidence`, `verified_for_cycle`
- `source` ∈ `{VERIFIED, EXTRACTED, INFERRED, UNRESOLVED}` — hand-checked row; agent read it from
  the funder's pages; agent found no letter guidance and applied the silent-funder playbook
  (below); agent found nothing or contradictions. Only `UNRESOLVED` creates a counselor task.
- `funder_kind` — see the silent-funder playbook; set for every prompt, inferred where not stated.
- `structure` ∈ `{SHORT_ANSWER_SET, CONTINUOUS_LETTER, TWO_STATEMENTS, PRESCRIBED_RESEARCH_FORM,
  CONSORTIUM_SPECIFIC, VIDEO}` (L-065). The last two are recorded so the resolver can fail closed
  on them; the engine does not generate them.
- `archetypes: set[...]` from L-064: `WHY_PROGRAMME`, `WHY_COUNTRY`, `CAREER_PLAN_RETURN`,
  `HOME_COUNTRY_CONTRIBUTION`, `LEADERSHIP_EXAMPLE`, `RELATIONSHIP_COMMUNITY`, `RESEARCH_PLAN`,
  `ACADEMIC_PREPARATION`, `LANGUAGE_PLAN`, `PERSONAL_BACKGROUND`, `CONSTRAINTS_MEASUREMENT`.
- `questions` (JSON): `{id, text, archetypes, max_words, max_chars_incl_spaces}` — per-question caps
  are the norm for short-answer sets (Gates 1,400/1,400/2,100/2,100; Commonwealth 200/100/250/100;
  Australia GS 150 × 5).
- `constraints` (JSON, same closed vocabulary as the CV doc) — see below.
- `programme_evidence` (JSON): modules, labs, research groups, faculty, stated mission, pulled from
  the programme's pages by the agent — the raw material for `SOURCED` claims, collected for every
  prompt whether or not the funder published letter guidance.
- `document_language` (L-063: set per funder/programme, never per country; GKS's cap itself depends
  on it — 6,000 KR vs 17,000 EN chars, L-016).
- `immigration: bool` — Australia GS (L-004), Canada study-permit letter of explanation (L-058).
- `paired_with` (self-FK, nullable) — the other half of a `TWO_STATEMENTS` pair, each half keeping
  its own `archetypes` (Berkeley SOP vs PHS, L-045; Fulbright objective vs personal, L-030).
- `header_block_required: bool` — uni-assist (L-057), KTH (L-053).
- `ai_use_policy` resolved per `(programme, structure)`: Cambridge prohibits AI for statements and
  permits it with acknowledgement for research proposals (L-041), so resolution per `DocumentDraft.kind`
  alone (R-088) is too coarse for letters.

Fulbright limits are set per national commission, not by IIE (L-030): for Fulbright the prompt
record is keyed by country, one row per commission, not one row for the programme.

`EXTRACTED` and `INFERRED` rows persist. The second student applying to a programme starts from
the first student's resolved prompt; a counselor who has placed someone there can correct it. This
is how the table grows beyond the 25 researched funders without anyone maintaining it by hand.

### `letter_required` on the programme record

`letter_required ∈ {required, optional, not_requested, unknown}`, resolved by the research agent
from the programme's required-documents list (`ExtractedClaims.required_documents` already
exists), failing closed to `unknown` → a counselor task only when the agent cannot tell. **The
engine never defaults to producing a letter**: NTNU does not want one, Helsinki and Oxford remove
unrequested documents, DTU wants the SOP inside its mandatory template (L-054, L-040). Generating
a letter for a programme at `not_requested` is blocked; at `unknown` the draft is produced and
flagged, so the student is not kept waiting on a lookup.

### Prompt resolution — agent first

Same three-layer ladder as `cv_format_requirement`, with the agent doing the work before a human
is involved:

1. **Verified** — a hand-checked row for the ~25 researched funders.
2. **Extracted** — `apps/research/extraction.py`'s `ExtractedClaims` extended to emit `structure`,
   `archetypes`, `questions`, `constraints`, `document_language`, `programme_evidence`. Before
   concluding a funder is silent, the agent widens the search to where the rules actually live:
   FAQ pages, application-guide PDFs, the previous cycle's call, the university's general
   admissions page, the national portal (uni-assist, universityadmissions.se, Campus France). Half
   the rules in `letter-rules.csv` came from such pages, not the programme page (L-054, L-057,
   L-068).
3. **Inferred** — no letter guidance found anywhere: the silent-funder playbook below. This is a
   normal path producing a usable, auto-approvable draft, not a degraded one.
4. **Unresolved** — contradictory findings, or a page that could not be read: a default
   `CONTINUOUS_LETTER` is still generated so the student has something, stamped with a flag that
   routes it to the counselor queue.

`structure ∈ {CONSORTIUM_SPECIFIC, VIDEO}` fails closed to the counselor with no generation:
Erasmus Mundus consortia and Invest Your Talent (one-minute video, L-036) are outside the engine.

**The scraped prompt is the most injection-prone input in the system** — third-party text that
literally instructs a model what to write. It gets `extraction.py`'s data-labelling treatment
explicitly, and that is not optional here.

### Silent-funder playbook

"No letter guidance on the page" almost never means "no information". Every rubric found — German,
Nordic, Dutch, US, East Asian — scores the same things: a concrete connection between the student's
background and *this programme's content*; a credible forward plan; evidence rather than adjectives
(L-050, L-052, L-028, L-045). Every office that lists failure modes lists the same ones: generic
text, platitudes, repeating the CV, wrong institution name (A7). A silent funder does not change
that standard; it only fails to restate it. The playbook writes to the standard:

1. **Programme evidence is always collected** (`programme_evidence` above). Curriculum, labs,
   groups, faculty, mission exist for every real programme and are what make a paragraph
   non-generic ("your module on X matches the project I did on Y").
2. **Infer `funder_kind` from who pays and who reads**, and borrow that kind's prompt set. The
   table below is derived from the funders in `letter-rules.csv`; every researched funder fits one
   row, and a silent one is written to its row's default archetypes.
3. **Defaults for the unstated:** `CONTINUOUS_LETTER`; one page, 500–600 words (the median of
   every published cap — KTH <500, Mundus 500, LMU 600, Berkeley 500–1,000); the programme's
   teaching language; header block naming institution and programme; past → present → future.
   These sit inside every limit ever observed, so a silent funder cannot be offended by them.
4. **Where the page hints otherwise, the page wins** — a government scholarship whose page asks
   for a research proposal gets `RESEARCH_PLAN` added.
5. **Every gate runs as for a catalogued funder**, plus `GENERIC_PARAGRAPH` (below): each unit
   must carry at least one `SOURCED` or `FACTUAL` claim specific to this programme or this
   student — the "could anyone have written this?" test that Purdue and DAAD both name (L-062,
   L-028).

| `funder_kind` | Researched examples | Default archetypes when silent |
|---|---|---|
| `GOVERNMENT_SCHOLARSHIP` — a state funds foreigners to come | DAAD, Chevening, Stipendium Hungaricum, Türkiye Bursları, ESKAS, Eiffel, MEXT, GKS, CSC, Fulbright, Australia Awards, Open Doors, SISGP | `WHY_COUNTRY`, `WHY_PROGRAMME`, `ACADEMIC_PREPARATION`, `CAREER_PLAN_RETURN`, `HOME_COUNTRY_CONTRIBUTION` |
| `UNIVERSITY_ADMISSION` — the department decides | TUM, LMU, Aalto, KTH, Helsinki, Leiden, TU Delft, UCL, Edinburgh, Oxford, Berkeley, Cornell, Toronto | `ACADEMIC_PREPARATION`, `WHY_PROGRAMME`, `CAREER_PLAN_RETURN`; `PERSONAL_BACKGROUND` only where separately asked |
| `UNIVERSITY_SCHOLARSHIP` — the university funds, academics judge | Gates Cambridge, Rhodes, Chalmers / Helmut-Schmidt-type awards | `ACADEMIC_PREPARATION`, `LEADERSHIP_EXAMPLE`, `RELATIONSHIP_COMMUNITY`; must not duplicate the admission statement |
| `CONSORTIUM` — multi-university programme | Erasmus Mundus (MAPP, IMSISS, Euroculture, Mundus Journalism), NL Scholarship | per-consortium forms; `CONSORTIUM_SPECIFIC` fails closed |
| `DEVELOPMENT_FOUNDATION` — a donor funds for impact | Commonwealth, Australia Awards | `HOME_COUNTRY_CONTRIBUTION`, `CONSTRAINTS_MEASUREMENT`, `LEADERSHIP_EXAMPLE`, `CAREER_PLAN_RETURN` |
| `IMMIGRATION_AUTHORITY` — not admission at all | Australia GS, Canada study-permit letter | `WHY_PROGRAMME`, `WHY_COUNTRY`, `PERSONAL_BACKGROUND` (home ties), `CAREER_PLAN_RETURN`; `immigration=True` |
| `RESEARCH_SUPERVISOR` — a professor is the reader | MEXT research students, CSC university overlays (PKU, Zhejiang), ESKAS research awards | `RESEARCH_PLAN`, `ACADEMIC_PREPARATION`, written in the discipline's register |

Two kinds exist in principle with no researched example yet and map to the nearest row:
corporate/industry scholarships → `DEVELOPMENT_FOUNDATION`; employer-sponsored study →
`GOVERNMENT_SCHOLARSHIP`. One application often involves two kinds at once (a DAAD letter *and* a
TUM statement; a Chevening essay set *and* a UK university statement): different documents to
different readers, each written to its own kind from the same core narrative.

The honest residual is unstated preference — a faculty culture that appears on no page. That is
invisible to a counselor who has never placed a student there, too. The playbook reaches what a
well-informed human would write; closing the last gap needs admission outcomes fed back per funder,
which is a later phase, not this one.

### `constraints`

Joins the CV doc's vocabulary at `BINDING`, with the letter-specific keys the research forced:

| key | why |
|---|---|
| `max_words`, `max_pages` | as the CV doc |
| `min_words` | CSC 800 words for postgraduates, PKU/ZJU 1,500, Stipendium Hungaricum minimum one page (L-008). **A floor cannot be satisfied by truncation — generation targets the floor**, and the pre-flight check fails a draft below it exactly as it fails one above a cap. |
| `max_chars_incl_spaces` / `max_chars_excl_spaces` | GKS and Australia Awards say "including spaces"; a word cap is the wrong unit for a character-counted form (L-016, A4) |
| per-question caps | carried on `questions[]`, checked per answer, not on the total |
| `font` | UCL 12pt, Hungary TNR 12, Heidelberg Arial 10 / 1.5, Aalto 11pt — render-time, validated like `max_pages` |
| `language` | paired with `document_language`, feeds `LANGUAGE_MISMATCH` |

Over-length is a hard failure, not a style issue: Oxford removes the statement and treats the
application as incomplete; Mundus MAPP and UvA do not read the excess; Leiden scores it down (A7).

### Source material the ledger does not hold

Several archetypes ask for things that are not facts about the applicant's past (item 2 of the
research consequences):

- `RESEARCH_PLAN` — theme, plan, end goals (MEXT, ESKAS, Fulbright objective, CSC). MEXT's form has
  **no supervisor field and no timeline heading** — do not make those mandatory (L-011–L-014).
- `LANGUAGE_PLAN` — GKS only (L-015–L-018).
- `HOME_COUNTRY_CIRCUMSTANCES` — ties to family, community, employment; economic circumstances
  (Australia GS question 1, L-006).
- `DEVELOPMENT_IMPACT` — outcomes, timeframe, beneficiaries, measurement (Commonwealth, Australia
  Awards, L-064 `CONSTRAINTS_MEASUREMENT`).

These are **engine-drafted, student-owned** (decision 7). New model `NarrativeInput` on the
documents app: `student`, `kind` (the four above), `text`, `proposed_by` (`ENGINE` / `STUDENT`),
`confirmed_at` (set when the student accepts the draft or edits the input in revision). The engine
writes the first version from the profile and the programme evidence — a plausible research theme
for a computer-vision graduate applying to a robotics lab, a return plan consistent with the
student's stated goals — and the student changes it in revision if it is not what they want.
Nothing is asked before the draft exists.

Where an input is a present-day fact with a document behind it (an employment contract for GS
question 1), it is a `VerifiedFact` in a new ledger category instead; `NarrativeInput` is for
plans and circumstances that have no document by nature.

### `LetterContent` schema

Pydantic, `extra="forbid"`, `frozen=True`, matching `CVContent`.

Top level: `language`, `header_block` (institution + programme, nullable), `units`. A unit is a
paragraph for `CONTINUOUS_LETTER` / `TWO_STATEMENTS`, an answer for `SHORT_ANSWER_SET`, a section
for `PRESCRIBED_RESEARCH_FORM`. Each unit carries:

- `archetype` — one of the L-064 set, plus `OPENING` and `CLOSING` for continuous letters. This
  replaces the draft's `ParagraphRole`: the §4.2 tailoring list maps onto it (curriculum fit and
  institution evidence → `WHY_PROGRAMME`; research fit → `RESEARCH_PLAN`; goals →
  `CAREER_PLAN_RETURN`; scholarship rationale → `HOME_COUNTRY_CONTRIBUTION`). A2 is explicit that
  no office prescribes a section order for a continuous letter — what they publish is a content
  checklist — so the archetype is a rendering and reuse convenience, and the binding unit is the
  next field.
- `answers_question` — the `questions[].id` this unit satisfies. Feeds `PROMPT_REQUIREMENT_UNMET`.
- `claims: tuple[LetterClaim, ...]`.

`OPENING` and `CLOSING` count as programme-specific **because they carry the institution name**.
Never copying the units that name the university is the cheapest defence against §4.2's
wrong-institution failure mode.

`LetterClaim`: `text`, `span` (offsets into the unit), `kind`, `fact_id` / `input_id` / `source_url`
as the kind requires.

| kind | Meaning | Verdict class |
|---|---|---|
| `FACTUAL` | Asserts something about the applicant's past or present. Must cite a `VerifiedFact` — authoritative document **or student statement**; both count as supported for use (decision 8). The overlay still colours the two tiers differently so the student can see which facts rest on their word alone. | `SUPPORTED`; `UNSUPPORTED` (cites nothing — model invention) is blocking, never overridable |
| `DECLARED` | Restates a plan or circumstance from a `NarrativeInput`. Must cite it. | Never blocking; the student's acceptance of the draft confirms the input |
| `INTERPRETIVE` | States meaning or causality over facts that are themselves supported — *"that failure is why I switched fields"*. Must name the facts it interprets; may not assert anything new about the world. | Never `SUPPORTED`, never blocking |
| `ASPIRATIONAL` | Forward-looking intent not demanded by any prompt question. Traces to no fact by nature. | Never blocking |
| `SOURCED` | Drawn from `programme_evidence`, or a cited fact about the home-country context (DAAD: facts and figures about the problem at home are "highly welcome", A10). Must cite `source_url`. | Checked against the cited source |

`INTERPRETIVE` exists because narrative requires causal connective tissue, and forcing that into
`FACTUAL` or `ASPIRATIONAL` would either block good writing or hide real claims. `DECLARED` exists
because a research theme or a return plan is neither a verifiable past fact nor optional
aspiration: the prompt demands it, the engine proposes it, and the student owns it by accepting the
letter.

**Immigration prompts** (`immigration=True`) use the same rule — the student attests, no counselor
— with a sharper attestation text, because the consequence is legal rather than a rejection:
Home Affairs names refusal, cancellation, future restrictions and prosecution (L-059); IRCC
five years' inadmissibility, including for a representative's misrepresentation "with or without
the applicant's knowledge" (L-058). Assessors give greater weight to statements backed by attached
evidence, so the draft prefers authoritative-document facts where both tiers exist (L-005). One
thing the gate must **not** do: flag a stated intention to seek permanent residence after study —
Home Affairs says in terms that this "does not count against an applicant under GS" (L-071).

### Revision

Two student-requested paths, both through `RevisionRequest` as in the CV doc:

- **Factual** (uncapped): "add that I led the robotics team" writes a `VerifiedFact` row at
  `source_tier=STUDENT_STATEMENT`, attested with timestamp, and the letter regenerates with it
  immediately. No counselor step. The attestation shown at intake ("you are responsible for the
  truth of facts you state; funders treat false claims as fraud") is the record (decision 8).
- **Style/structure** (two rounds on the narrative, uncapped per letter): applied as asked, except
  where the change weakens the letter against a rule in `letter-rules.csv` or the funder's
  published rubric — then decision 11: one concrete explanation naming the rule and its
  consequence ("TUM scores the letter on the connection between your interests and their
  curriculum; this cut removes the only paragraph that does that" — L-050), one alternative, and
  on re-request the change is applied with `advice_shown` stored on the request. Changes that
  break a `BINDING` constraint, name the wrong institution, or ask for a fact that traces to
  nothing are refused for everyone.

### The claim-coverage check

The gate consumes the claim list, so a model could assert something in `text` and omit it from
`claims`. Closing that deterministically:

**Any sentence containing a digit, a date, or a capitalised multi-word phrase must fall inside a
declared claim span, else `UNDECLARED_ASSERTION` — blocking.**

Catches every hard fabrication (names, numbers, dates, institutions) with no NLP and no second
model call. Narrative prose without those triggers passes untouched, which is deliberate: the gate
is strict about facts and permissive about story.

**Stated ceiling:** a soft lowercase claim — *"I supervised a research group"* — carries no trigger
and escapes. With counselor fact-checking removed (decision 8), the backstop is the student: the
overlay shows every claim and its source, and the student is the one who reads their own letter
before accepting it. Upgrade path if it proves insufficient: a POS-tagged first-person
past-tense-assertion rule. The capitalised-phrase trigger is Latin-script only; for Korean,
Japanese or Chinese output the digit and date triggers still fire — stated, not hidden.

### Further deterministic gates

All blocking; all fixed mechanically by regeneration, so all trigger the single retry.

- **`WRONG_INSTITUTION`** — scan the letter against the `Institution` / `Program` catalogue for any
  name that is not the target. §4.2 requires this explicitly; uni-assist cannot route an unlinked
  letter and Purdue names "the correct school's name" as the first thing to check (L-057, L-062).
  No override.
- **`PROMPT_REQUIREMENT_UNMET`** — every `questions[].id` must be claimed by some unit's
  `answers_question`, and every `NarrativeInput` the archetypes demand must exist (the engine
  drafts it if missing — this fires only if generation failed to). Aalto rejects without
  evaluation on a missing item; GKS disqualifies (L-052, L-018).
- **`DUPLICATES_PAIRED_DOCUMENT`** — for `TWO_STATEMENTS`, sentence-level overlap between the two
  halves above a threshold. Normalised-sentence set intersection (stdlib; no similarity model),
  threshold set by test fixture. Berkeley, UCLA and Rackham all state non-duplication as a rule
  (L-045–L-047); Fulbright's personal statement is "not a duplication of the study objective"
  (L-030). Also applied between a letter and the student's CV when the prompt is a continuous
  letter — DAAD: "do not start by repeating your CV" (L-028) — at advisory level only.
- **`HEADER_BLOCK_MISSING`** — when `header_block_required`, the rendered first lines must contain
  the institution and programme name (uni-assist: "in bold print at the top… otherwise we will not
  be able to link your letter", L-057).
- **`LANGUAGE_MISMATCH`** — `LetterContent.language` must equal `document_language`, cross-checked
  by Unicode-script ratio of the text (Hangul / kana / Han vs Latin). Cheap and sufficient to
  catch the GKS and MEXT cases where the cap depends on the language (L-016, L-063); it does not
  distinguish French from English, which the model-declared field covers.
- **`GENERIC_PARAGRAPH`** — every unit except `OPENING`/`CLOSING` must carry at least one
  `FACTUAL` or `SOURCED` claim. A paragraph with neither is the "could have been written by
  anyone" paragraph that TUM, DAAD and Purdue all reject (L-061, L-028, L-062). Runs for every
  prompt; it is what keeps the silent-funder path at the same bar as a catalogued one.
- **Eligibility pre-flight, not drafting rules** — Chevening voids the application for duplicate
  course choices or a non-English form (L-068). These live on the application checklist, not in
  the letter gate; recorded here so nobody adds them to the engine.

### Approval

A draft with **no blocking verdict and no flag** is approved automatically and usable for the
application the moment the student accepts it (decision 9). Flags that route a draft to the
counselor queue: `UNRESOLVED` prompt, `letter_required=unknown`, `CONFLICTING` between two facts
the student stated, a `BINDING` constraint the retry could not meet, `CONSORTIUM_SPECIFIC` /
`VIDEO`. The counselor's job is these mechanical residuals, not reading every letter. Approval
invalidates on any change, as §4.2.1 requires; the audit record stores who accepted (student or
counselor) and the verdicts at that moment.

### Clustering

`cluster_key = (discipline, structure, sorted(archetypes), limit_band, scholarship_present,
document_language)`. Deterministic tuple equality — no model, no embedding store. Reuse is
permitted only within a cluster; anything else fully regenerates from the same core narrative —
the story is identical either way, only the amount rewritten differs, and the cost of a full
rewrite is tokens, not consistency.

Two changes from the draft (item 5): the question signature is the **sorted archetype set**, not
raw question text, so Chevening's and Gates' differently worded leadership questions cluster; and
`limit_band` is **per structure kind**, since a 2,000-character short answer and a three-page
letter must never cluster however close their totals.

Reuse is not a separate code path: the same generation call with core units pinned as input and
only programme-specific units requested. Core-eligible archetypes: `PERSONAL_BACKGROUND`,
`ACADEMIC_PREPARATION`, `LEADERSHIP_EXAMPLE`, `RELATIONSHIP_COMMUNITY`, `CAREER_PLAN_RETURN`,
`HOME_COUNTRY_CONTRIBUTION`. Always regenerated: `OPENING`, `CLOSING`, `WHY_PROGRAMME`,
`WHY_COUNTRY`, `RESEARCH_PLAN`, `LANGUAGE_PLAN`, and any unit whose `answers_question` names a
question absent from the source letter's prompt. An engineering graduate applying to an
engineering programme and an AI programme gets two letters from one story: the first reuses most
units, the second is fully rewritten with the emphasis shifted.

**Prerequisite:** `apps/funding/models.py:288`'s `Program` has **no discipline field**. Recommend
adding one over **ISCED-F narrow field** (UNESCO), since Europass and Erasmus Mundus already use it
and free text would make cluster keys never match.

### Generation (`apps/documents/letters.py`)

Clones `apps/research/extraction.py` exactly: Responses API, `LetterContent` schema-constrained,
untrusted content labelled as data, `safety_identifier=privacy_safe_identifier(...)`,
`max_output_tokens` ~6000 (prose plus claim spans), `store=False`. Rate limiting added in the same
change per CLAUDE.md — `rate_limited("letter_generation", actor_id, ...)`.

The prompt carries, as constraints never as a rewrite pass:

- the humanizer's 25 patterns, pinned at v3.0.0 (commit `9862685`), plus three rules carried from
  the pre-3.0 version (synonym cycling, false "from X to Y" ranges, filler phrases) — see `docs/research/2026-08-21-humanizer-assessment.md` for why a
  rewrite after the gate can reintroduce cleared claims;
- the craft rules from A10 (one unifying theme; evidence then interpretation; no "I've always
  wanted to be a ___"; no opening with the CV; reflective and factual, no platitudes or flattery —
  DAAD L-028; cut any sentence that could have been written by anyone);
- the structural kind, `funder_kind`, per-question caps, and any `min_words` floor to target;
- `programme_evidence` and the fact ledger as the only sources for `SOURCED` and `FACTUAL` claims;
- the narrative-weight rule from priority question 2: personal background only where the prompt
  carries `PERSONAL_BACKGROUND`; a US SOP is written "technically, in the style of the discipline"
  (Berkeley L-045) and a Toronto statement is "what interests you analytically" (L-048).

Bounded retry: exactly one, on `UNSUPPORTED`, `UNDECLARED_ASSERTION`, `WRONG_INSTITUTION`,
`PROMPT_REQUIREMENT_UNMET`, `DUPLICATES_PAIRED_DOCUMENT`, `HEADER_BLOCK_MISSING`,
`LANGUAGE_MISMATCH`, `GENERIC_PARAGRAPH` or a `constraints` violation — all mechanically fixable.
Hard cap of one, both passes gated, both counted by the rate limiter.

### Render

Through the existing `render.py` / `hygiene.py`. No variant matrix — letters have no Europass
equivalent; `structure` selects the template (letter, numbered answers, MEXT's two headed
sections). `FIELD_MAPPED` matters more here than for CVs: `SHORT_ANSWER_SET` is the common case for
funders, most portals count the limit on pasted text, and Australia GS is a form outright (L-001).
The pre-flight check counts characters the way the form does (`max_chars_incl_spaces`) and pages
the way the PDF renders, per question where caps are per question.

### AI-use policy

Reference data, not a gate (settled decision 6); it never delays or blocks a letter. It carries
**four** classes (A9, L-067), resolved per `(programme, structure)`, shown as a note on the draft:

| class | who | note says |
|---|---|---|
| `PROHIBITS` | Cambridge (incl. help with English, L-041), Oxford (AI = plagiarism, may screen, L-040), Edinburgh (L-039), Chevening (detection, negative attestation, and no endorsed paid third parties — L-021, R-091/R-092) | the destination's wording covers English-language help and agency help, not only generation |
| `REQUIRES_DISCLOSURE` | Rhodes (mentors must not write or edit; disclose tool and prompts; no substantive generation, L-024); DAAD ("Produced with the aid of (tool used)" + Declaration of Authenticity, L-025) | the exact disclosure text — DAAD's phrase; Rhodes' checkbox list |
| `IMMIGRATION_PROHIBITION` | Australia Home Affairs: "Do not modify or create documents using… artificial intelligence (AI), or any other method" (L-059); IRCC misrepresentation by a representative "with or without the applicant's knowledge" → 5 years' inadmissibility (L-058) | quote Home Affairs / IRCC verbatim, and the legal consequence |
| `SILENT` | EACEA, Fulbright/IIE, SISGP, Gates, Australia Awards, Commonwealth, Hungary, Türkiye, CSC; MEXT and GKS carry a fraud clause only | nothing found is not permission |

`cv-rules.csv` R-093 ("no AI policy located" for DAAD and Rhodes) was corrected on 2026-08-22 to
point at L-024/L-025; the `ai_use_policy` reference data needs the `REQUIRES_DISCLOSURE` value
beside prohibit/silent before letters ship. §4.2.3's hygiene clause already binds the platform to
comply with disclosure requirements rather than conceal assistance.

## Amendment 2026-09-14 — how the story is chosen and told

Evidence: `docs/research/2026-09-14-letter-storytelling-evidence.md` (findings cited as `N-`). The
plan carries the mechanics (Tasks 3, 4, 6, 7, 11b, 12, 13, 14); this section records what changed
in the design and why.

1. **The story is chosen before the prose is written.** Generation as first designed asked the
   model to "hold one unifying theme" inside the same call as the letter, so the model chose the
   theme, order and turn by default — and the default is the childhood-passion opening every
   reader names as the cliché, repeated across a discipline. A storyline step (plan Task 11b) now
   proposes three candidate stories per core narrative and a deterministic scorer picks one: more
   anchoring facts, more fact categories, fewer assumptions, and the theme least like the tenant's
   recent ones. The storyline lives on the `CORE_NARRATIVE` draft (`LetterContent.storyline`) and
   is data in every derived letter's prompt.
2. **Three theme kinds, by reader.** A *problem* for faculty readers (`RESEARCH_SUPERVISOR`,
   thesis-track admission); a *plan* — goal, contribution, programme — for scholarship readers;
   a *match* between the applicant's record and the programme's content for readers who fill in a
   score (TUM, Leiden, KTH). No story for immigration prompts.
3. **What the engine invents, and what it never does (N-04).** The theme, the causal links, the
   order, the reading of a setback, the gap and the plan are invented and land as `INTERPRETIVE`,
   `ASPIRATIONAL` or `DECLARED`. A person, an event, a number, a name, a date or an institution is
   never invented; anchors are fact ids, never text. Ding (2007) measured family-as-reason at
   20.5% of sentences in unedited statements against 7.5% in successful ones, and readers say it
   in their own words (N-02), so the exclusion costs nothing a winning letter had. Owner's line
   (2026-09-14): the boundary is whether a submitted document could check the claim — checkable
   facts come only from the ledger; the reasoning around them is the engine's, and the student
   edits afterwards.
4. **The origin slot.** Nine of ten accepted statements in the Iowa State corpus open with a real
   circumstance, one paragraph, then credentials (N-03). Where a reader wants one, it comes from
   the ledger (home country plus a `SOURCED` fact about the field there) or from a new
   `NarrativeInput.Kind.PERSONAL_BACKGROUND` the engine proposes and the student sees in the
   overlay and edits. It is a `DECLARED` input like any other: accepting the draft confirms it.
   Per-item confirmation was proposed as owner decision (c) and struck on 2026-09-14 — decision
   8's "acceptance confirms" stands unchanged.
5. **Gates added, one flag added (plan Tasks 7, 14).** A `WHY_PROGRAMME` unit needs a `SOURCED`
   claim (a fit paragraph that survives a find-and-replace of the university's name says
   nothing — N-15); answers in one short-answer set may not repeat each other; leadership and
   relationship answers are first person singular (Chevening reading committees: "use 'I' instead
   of 'we'"); a letter that drops the storyline's anchors retries. A stale example (older than
   five years) is a counselor flag, never a gate — a student with only old examples must not be
   blocked.
6. **Unchanged, restated.** No rewrite pass, no detector, no best-of-N against a detector (N-08:
   detectors mis-flag non-native English writers at rates up to 61%, and §4.2.3 forbids aiming at
   them). Decision 6 stands: AI-use policy is surfaced, not gated — with the note that Chevening
   now publishes detection, disqualification and "you do not need to pay anyone". Owner decision
   (a), 2026-09-14: keep — the engine drafts for every reader, none excluded.

## Consequences for the CV engine design

Decisions 8 and 9 apply to CVs as well: `UNCERTAIN` (student-statement facts) no longer needs a
counselor override, and a CV draft with no blocking verdict auto-approves.
`2026-08-21-phase2-cv-engine-design.md` carries a dated amendment to that effect rather than a
rewrite.

## Next step

Write the implementation plan. Order of dependencies: `Program.discipline` and `letter_required`
(funding) → `ApplicationPrompt` + CSV loader for `letter-rules.csv` + `funder_kind` defaults
(funding) → `ExtractedClaims` extension and the widened search (research) → `NarrativeInput` and
`DocumentDraft.kind` additions (documents) → `LetterContent` + gates → `letters.py` generation
→ render templates per `structure`.
