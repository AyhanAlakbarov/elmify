# The CV follows the page: switch, check, apply, ask, or show — never drop

> **Superseded in mechanism, 2026-09-22:** the three phrasings, three samples, second model family,
> unanimity and one retry are replaced by typed classification in
> `2026-09-22-typed-decisions-and-multilingual-sources-design.md` §6, which restates every guarantee
> measured here as kept. This document remains the record of the measurements that set the bar.
>
> **Landed 2026-09-26** as `apps/documents/rule_sinks.py` and `derive._read_by_grammar` (plan
> `2026-09-26-decision-layer-and-rule-grammar-amended.md` Tasks 8–10). The mechanism this document
> describes remains the fallback when no decision provider is configured, until the page-corpus
> gates of `2026-09-26-requirement-reader-addendum-design.md` §8 pass on Jev.

Status: **implemented 2026-09-13** (plan: docs/superpowers/plans/2026-09-13-cv-follows-the-page.md).
Date: 2026-09-13 (rewritten the same day; the first draft carried a conformal-calibration layer
that bought a certified number and not a behaviour, and it is cut — see "Deliberately not built").
Amends `2026-09-12-program-page-reader-design.md` — the reader, the verbatim statements and the
shared transaction stand; what changes is how a page becomes a decision.

The goal: read a programme's or scholarship's page and make the student's generated CV follow
it — switch the template when it wants Europass or its own form, enforce the rules it states,
include and order what it asks for, ask the student for a fact it wants that they never gave, and
put in front of the counsellor the one kind of requirement no code can carry. **Every CV
requirement on a readable page lands in exactly one of those five outcomes; none is dropped.**

Robust in the sense that is available for reading natural language: **the system acts only when
three readings agree; anything less is abstained, visibly, to a default that ships no data; and
neither a sentence the model did not judge nor a page the reader could not read can be recorded as
"the page says nothing".** No human is in the flow. A counsellor sees a quote only on the residue;
the student is asked only for their own missing fact.

## Why

The shipped design makes the decision with a single detector, and every detector we have fails in
a bad direction. Measured 2026-09-13 on 41 sentences — 16 real, from 12 live funder pages; 13 from
the test suite; 12 written to hit phrasing the vocabulary does not know (suggest, advisable,
encouraged, German, French, Spanish):

| Classifier | Real | Synthetic | Phrasing gap | Total |
|---|---|---|---|---|
| Local NLI zero-shot (best of 2 models, 3 framings) | 10/16 | 5/13 | 7/12 | 54% |
| Shipped keyword rule (`derive.py`) | 11/16 | 8/13 | 6/12 | 61% |
| `OPENAI_EXTRACTION_MODEL`, closed question, majority of 3 | 15/16 | 13/13 | 12/12 | 98% |
| Same, scored on the **action** (renderer) rather than the label | 16/16 | 13/13 | 12/12 | **100%, unanimous across samples** |

Three findings drive the design:

1. **The keyword rule is not silent on unknown phrasing; it is wrong in the PII direction.** "We
   suggest the Europass template", "It is advisable", "strongly encouraged", "Wir empfehlen",
   "Ideally" all classified `europass_required`: the modality word is not in `_SOFTENERS` and the
   fallback is the strict reading. Each ships a student's name, date of birth, education and
   employment history to europa.eu off a page that merely suggests. Adding words moves the cliff.
2. **The model's selection step is a lottery in front of the rule.** DAAD PRIME's whole Europass
   basis is one sentence in 15,680 characters; a read that does not quote it derives `any`, which
   is also what a page stating no format derives. Union-of-three reads (built 2026-09-13) raised
   coverage and did not close this: 47/42/48 statements on one page, no two identical.
3. **The distinction the model wobbles on is one the system throws away.**
   `render.py::_REQUIREMENT_TO_VARIANT` is the only consumer of `cv_format_requirement`, and it maps
   `europass_required` and `europass_preferred` to the same variant. Every sample disagreement, and
   the one miss (EMSHIP's checklist line "(Europass) CV", which our own catalog labels by judgment),
   was required-vs-preferred. On the decision the pipeline makes — Europass renderer or STANDARD —
   the model was 41/41 and unanimous.

A local classifier is ruled out by measurement: "A Europass CV is recommended." scored p=0.01
against the *recommended* hypothesis on the best model, and re-framing did not move it. The
frontier model does read this language, and the design uses it for judgement only — never for
recall, never unguarded.

## Decisions

- **Decide on actions, not labels.** The unit of agreement is the render variant: `EUROPASS`
  (required or preferred) or `STANDARD` (not required, or no statement). The four-way label is
  still asked and stored as provenance, and two samples that disagree on required-vs-preferred
  *agree*. Measured: this alone takes observed instability from 4/41 to 0/41.
- **Five outcomes, one closed vocabulary.** A CV requirement the page states becomes one of:
  1. **Switch** — the template: `EUROPASS` or `other_template` (below).
  2. **Check** — one of the renderer's enforceable keys (`max_pages`, `language`, `photo_allowed`,
     …), as `derive_cv_constraints` writes today.
  3. **Apply** — a *typed generation directive* over the CV's own vocabulary:
     `include(<field>)`, `order(<section> | cv, chronological | reverse_chronological)` or
     `emphasise(<section>)`. `order` alone also takes `cv`, the whole document: "A curriculum
     vitae in reverse chronological order." (DAAD EPOS, verbatim) names no section, and pinning
     it to one was arbitrary — `cv` orders every dated section at once. The field and section names are the closed lists `CVContent` already
     defines (`education.ects_credits`, `education.grade_native`, `education.thesis_title`,
     `education.class_rank`, `personal.date_of_birth`, the section names, …); the model picks from
     them, it never writes a target. "State your ECTS credits" → `include(education.ects_credits)`;
     "in reverse chronological order" → `order(education, reverse_chronological)`; "the CV should
     highlight your academic and professional experiences" (WE-TEAM, verbatim) →
     `emphasise(experience)`. One directive per sentence; a sentence naming two sections yields
     the model's single choice.
  4. **Ask** — an `include(<field>)` directive for a fact the student's ledger does not carry
     raises a `GapQuestion` (`gaps.py`, the `missing_grade` pattern) carrying the page's sentence,
     so the student supplies their own fact and it reaches the CV as a `VerifiedFact` like any
     other. This is the one place a person is involved, and it is the student, about themselves.
  5. **Show** — a sentence all three readings agree states a CV requirement that names no field,
     section or key the engine has (MemBioMed, verbatim: "include details on … quality/recognition
     of the institution having awarded the bachelor … degree"). It is written as an
     `ADVISORY_HIGH_RISK` rule on the key **`unapplied`** with the quote, and the counsellor sees it
     in the warnings panel next to the rendered CV. Distinct from `undecided` (the readings
     disagreed): `unapplied` means the engine understood and cannot act. The `unapplied` quotes,
     counted across real pages, are the queue for the next field or key to add.

  There is deliberately no `exclude` directive. Every real "leave X out" the corpus contains
  (photo, date of birth) is already an enforceable key, and a directive that can hide a field is
  the one a hostile page would want — a page must never be able to remove a student's name.
- **Candidates are found by code over the whole page, by two paths.** For the format question:
  **every** line of the archived page's readable text that contains `europass`, whether or not it
  names the CV — i-MESC's real mandate is "Please use the Europass model.", with no CV word in it,
  and a CV-term filter would have scanned past it into a silent `any`. The word is itself the
  signal. For the constraints question: every line matching `_CV_TERMS`, **unioned with** the
  statement read's DOCUMENT and FORMAT sentences — `_CV_TERMS` knows Lebenslauf and résumé and not
  özgeçmiş, życiorys or 履歴書, and this catalog reads Türkiye Bursları and JASSO; the model's own
  read is the second path for what the vocabulary does not cover. Each candidate is presented to
  the model with its nearest preceding heading line (`readable_text` keeps `#` markers for this),
  so a bullet under a "CV" heading carries its context. The model never decides what is on the
  page for the format question; for constraints it may add candidates and never remove one.
- **One closed question, asked three times in three phrasings.** `derive_cv_constraints` already
  lists numbered sentences and asks for per-index verdicts from a closed schema; it gains a second
  schema field for the format verdict, takes its candidates as above, and is called `K = 3` times,
  each with a differently worded developer prompt over the same schema. Three samples of one model
  on one prompt share every systematic bias that model has — unanimity over them filters sampling
  noise, not bias — and three phrasings is the cheap, partial decorrelation. It is not independence
  and the spec does not call it that; a reading from a second model family is the real version and
  is listed under "Deliberately not built". Same prompt discipline as today: DATA labelled as data,
  `extra="forbid"`, `max_output_tokens` capped, `store=False`, `safety_identifier`.
- **The action needs every reading; an advisory rule needs a majority of them.** (Amended
  2026-09-14; it was unanimity on both. **Reverted to unanimity on both the same day**, owner
  decision, once Claude became the third reading and the wrong-by-majority rows turned out to be
  stray OpenAI votes; the paragraph below records the majority design as it stood. See CLAUDE.md.) A format verdict for a candidate is accepted only if all
  three samples returned one for that index and all three agree on the action. A page's decision is
  written only if every accepted verdict points the same way (lines judged `none` are neutral).
  Otherwise the page **abstains**. A constraint value (`max_pages` etc.) is written if a majority of
  the surviving samples — `n // 2 + 1`, so 2 of 3 — returned the same value for that (index, key);
  otherwise it is dropped and the sentence is surfaced the same way. A directive is written on the
  same majority of the same (action, target); `unapplied` likewise. A reading that dissents with
  itself (two values for one key, two directives for one line) casts one vote that can never be the
  majority value. The two bars differ because the costs do: an advisory rule that is wrong costs a
  warning the counsellor reads beside the quote, while one that abstains costs the criterion never
  reaching the CV at all — measured live, "Your CV must be in English" abstained under unanimity
  because one reading of three wobbled — whereas a wrong *action* ships the student's name, date of
  birth, education and employment history to europa.eu.
- **A sentence naming a referee, supervisor, host or employer yields no rule and no directive**, and
  is surfaced as `undecided`/`third_party` instead. Code enforces it because the prompt alone did
  not: measured live 2026-09-14, two of three readings attributed "Short CV (max. 2 pages) from this
  academic supervisor." to the applicant. The guard is on the OUTCOME, not on the candidate list —
  the sentence is still judged and still shown, because a skipped sentence would be silent and
  silence is the failure this design ends.
- **The guard has two voices since 2026-09-18, and either one withholds.** `_THIRD_PARTY` is ten
  English words; a page may be in any language, and a regex that misses attributes a supervisor's
  page limit to the student — the one failure direction here that is dangerous rather than lossy.
  So `Directive` carries a required `about_whom: applicant | third_party | unclear` (no default: a
  reading that skipped the question must never read as "the applicant's"), and any vote that is not
  `applicant` withholds the line exactly as the regex does. `unclear` withholds too — a reading that
  cannot tell whose CV a sentence means has not said it is the applicant's. Measured live
  2026-09-18 on seven sentences, three readings each, 21 of 21 attributions right, including
  German, Turkish, Russian and Kazakh lines the regex and `_CV_TERMS` cannot read; the 48-row gate
  the same day was 46/48 correct, 0 wrong, 2/14 advisory undecided — the schema field cost no
  abstention. The regex stays as the second opinion, not as the only one.
- **A candidate the model did not judge is an abstention, not an absence.** Every `europass` line
  must receive a format verdict from every sample — `none` is a verdict. A missing index means the
  page abstains. This is what makes a silent miss structurally impossible rather than unlikely.
- **Abstention is safe, stored and visible; it is never `any`-by-omission.** An abstained page
  writes `cv_format_requirement=any` (the STANDARD renderer, no egress) with the new confidence
  `UNDECIDED`, and an `ADVISORY_HIGH_RISK` rule on the new key `undecided`, `value` naming the
  field in question (`cv_format`, `max_pages`, …) and `rule_text` carrying the sentence verbatim.
  The existing render path shows advisory rules with their quotes, so the counsellor sees "this
  page says something about the CV the platform could not decide: *<sentence>*" with no new
  surface. A hand-verified row (`cv_format_verified_for_cycle`) is never touched, as today.
  **The exit from `UNDECIDED` is the existing hand-verification path** — a row in
  `docs/research/cv-rules.csv` loaded by `load_cv_format_requirements`, which sets `VERIFIED` and
  the cycle. There is no UI for it, and the gate file grows the same way: by hand, from resolved
  cases. That is a manual loop today and the spec says so rather than implying otherwise.
- **A mandate for a template the engine cannot render is surfaced, not resolved to nothing.** The
  verdict `other_template` ("use SI's provided template", SISGP) writes `any` + `UNDECIDED` and an
  `undecided` rule with the quote, exactly like an abstention. `CLAUDE.md` records that the reader
  could see this requirement and nothing could act on it; this closes that gap inside the same
  mechanism, at the cost of one enum value.
  **The enum is complete for master's-level applicants, and the next family is known.** Two
  independent research runs (2026-08-26, `cv-style-rules.csv`) found binding CV formats only in
  funders and format families: Europass, the German tabular form (already a variant, chosen by
  country rule), a funder's own file, and portal fields. Japan's rirekisho is domestic employment,
  not international admissions (S-019). The one family that will arrive is the **narrative CV**
  (UKRI R4RI, SNSF, DFG, NWO — four prose modules, no bullets), which S-021 records as research
  *funding* practice, not master's admission. When the platform takes on research-funding
  applications it becomes a sixth value, `narrative_cv`, with its own render variant — a template
  class like Europass, not one funder's form. Until then a page mandating it lands in
  `other_template` and is shown, never misrendered.
- **The word must be on the page.** A format verdict can act only for a candidate line that
  contains `europass` — which is by construction, since those are the only lines the format
  question is asked about, and a verdict for any other index is discarded. A hostile page can make
  the platform believe Europass is required only by writing that Europass is required, which a page
  is entitled to say. The model decides modality; it cannot manufacture a value from a page that
  does not carry the word, and the prompt gives it nowhere to write a sentence of its own.
- **No `europass` anywhere on the page → `any`, confidence `EXTRACTED`.** The one case where "says
  nothing" is established by code over the whole page, not inferred from what a model quoted.
- **Unreadable is a state, not silence.** A page whose readable text is under **1,500 characters**
  on a body of **20,000 bytes or more** is recorded `unreadable` on the snapshot and derives
  nothing: previous rows stand, and it is listed for the browser tier. Measured 2026-09-12/13: the
  unreadable shapes are 289, 265 and ~1,000 characters (Sciences Po, JASSO, Türkiye Bursları); the
  smallest page that read fine is 3,095 (WE-TEAM). An absolute floor, not a ratio, because the
  ratio margin is thinner (1.1% vs 2.5%). Re-derive if a real page lands between 1,000 and 3,000.
  Two-sided, found at implementation: the floor alone flagged every small page, and a 300-byte page
  whose text is the page is not a shell.
- **The sentences become a gate, pinned to the model.** `docs/research/cv-format-eval.csv` (48
  rows: 41 from the spike plus 7 directive sentences; `d2` reworded to name the CV; `s4`, `s5`
  relabelled standard; `goettingen-de` unapplied; `emhrpp-a` none) carries sentence, source URL or
  `synthetic`, language, outcome and detail. A `live` test
  (`tests/documents/test_derive.py::test_the_eval_corpus_has_no_wrong_action_and_few_abstentions`)
  asks the closed question three times over the whole set and asserts **zero wrong actions**, with
  abstentions capped separately by row kind: format rows (europass/standard) undecided ≤ 1;
  advisory rows undecided ≤ `ceil(15%)`. It names `OPENAI_EXTRACTION_MODEL`; a model change is a
  red test until re-run. It carries the directive sentences too — MemBioMed's cGPA and
  institution-quality lines, DAAD PRIME's tabular-form and no-gaps lines, DAAD EPOS's
  reverse-chronological and PDF-only lines, WE-TEAM's highlight line — each labelled with its
  outcome. The file grows from abstained cases a human later resolves — that is the
  feedback loop, and it needs no statistics. Measured 2026-09-13 over three live runs of
  `gpt-5.6-luna` under the old unanimity rule: format rows 0/34 undecided and 0 wrong every run;
  advisory rows 4–5 of 14 undecided per run (29–36%), churning among the tabular-form / order /
  emphasise sentences. Re-measured 2026-09-14 under the majority rule: **48/48 correct, 0 wrong,
  0/34 format and 0/14 advisory undecided.** The same run without the third-party guard was 47/48
  with one wrong row — `swiss-3rd`, the supervisor's page limit written as the applicant's — which
  is the tradeoff made visible: relaxing to a majority converts abstentions into rules, and one of
  them was an attribution the prompt had been getting wrong all along and unanimity had been hiding. **Its blind spot is
  stated here so nobody reads the gate as covering it:** a *unanimous wrong* answer never
  abstains, so nobody sees it and it never becomes a gate row. Systematic error is invisible to
  this loop by construction. The mitigation — a small periodic sample of *acted* decisions
  re-judged by a second model family, disagreements surfaced — is listed under "Deliberately not
  built" with its trigger.
- **The keyword modality rule is deleted.** `_SOFTENERS`, `_NEGATIONS`, `_CLAUSE`,
  `_europass_clauses` and `_negated_europass` go. Negation, softening and a stated choice are all
  things the closed question answers (`none` / `not_required`, and the existing two-values-one-key
  drop), and the gate pins each of them with the real sentence that motivated the guard.
  `_THIRD_PARTY_CV` went too and **came back on 2026-09-14 as `_THIRD_PARTY`**, a flag on the
  candidate read by `outcomes()` rather than a filter that skipped the sentence: the closed question
  did not answer that one. See the third-party decision above for the measurement.
- **The union-of-three statement read stays, and the *format* decision no longer depends on it.**
  It feeds `ProgramStatement` for competencies (advisory reordering in `tailor_skills`) and
  citation — and it remains a recall path for constraints: a bullet under a CV heading that
  carries no CV word of its own reaches the judge only because the read quoted it. What changed is
  that the format decision is no longer a function of which sentences it selected.

What this does **not** claim: that every requirement is *enforced* — "include details on the
quality of the institution" is an instruction to a writer, and no code verifies it; it is shown,
and the vocabulary grows from what is shown most. Nor that the reading is right on every sentence,
or a certified error rate. It claims that every Europass action had three
readings, in three phrasings, agree on it, and every advisory rule had a majority of them; that the
residue is abstained rather than guessed; that a missed sentence or an unread page cannot be
recorded as an absence; and that the claim is re-checked against 48 real sentences on every run of
the gate. On the measured set the residue is empty; the design does not assume it stays empty.

## Data flow

```
archived page ──readable_text──▶ lines
                                   │
        ┌──────────────────────────┼───────────────────────────────┐
        ▼                          ▼                               ▼
 < 1,500 chars       format: every `europass` line        statement read ×3 (unchanged)
 → UNREADABLE        constraints: _CV_TERMS lines           → ProgramStatement rows
 (derive nothing)      ∪ DOCUMENT/FORMAT statements  ◀────── (competencies, citation,
                       each with its nearest heading           second recall path)
                                   │
                                   ▼
                   closed question, one listing, K=3 samples, 3 phrasings
                   (format verdict for europass lines; constraint verdicts for all)
                                   │
                    every candidate judged in every sample?
                    every accepted verdict unanimous?
                       no  ──▶ page abstains: any + UNDECIDED + `undecided` rule with the quote
                       yes ──▶ per sentence, one of:
                                switch ─▶ cv_format_requirement (template)
                                check  ─▶ cv_constraints (renderer enforces)
                                apply  ─▶ cv_directives ─▶ generate_cv (include / order / emphasise)
                                ask    ─▶ include() with no fact ─▶ GapQuestion to the student
                                show   ─▶ `unapplied` rule with the quote ─▶ counsellor
```

## Components

- `apps/documents/derive.py`: `derive_cv_format` and `derive_cv_constraints` collapse into
  `derive_page_rules(program, *, parser, page_text, snapshot) -> Derivation`, which makes the K
  calls once and writes `cv_format_requirement`, `cv_format_confidence` and `cv_constraints`
  together. `Derivations` gains `formats: tuple[FormatVerdict, ...]` with `statement_index` and
  `value: Literal["required", "preferred", "not_required", "other_template", "none"]`, and
  `directives: tuple[Directive, ...]` with `statement_index`, `action: Literal["include", "order",
  "emphasise", "unapplied", "none"]` (`none`: a CV-naming line that states no requirement — a
  heading, a question — so that "not judged" and "judged as nothing" stay distinguishable), `target: <Literal built from CVContent's field and section names>`
  and, for `order`, `value: Literal["chronological", "reverse_chronological"]`. Every `_CV_TERMS`
  candidate must receive a constraint verdict, a directive, or `unapplied` from every sample;
  a candidate missing from a sample abstains the page, as for Europass.
  Rule ids stay `PAGE-<index>-<key>`. The regexes above are deleted.
- `apps/documents/program_rules.py::read_and_derive`: passes `readable_text(fetched)` and the
  snapshot through; unchanged transaction shape.
- `apps/funding/models.py`: `Program.cv_directives` (JSONField, list of `{action, target, value,
  rule_text, source_url}`), written with `cv_constraints` in the same `_write_program` call.
- `apps/documents/generation.py`: `generate_cv(programme=...)` reads `cv_directives` beside the
  competency tailoring it already does. `include` renders the field when a `VerifiedFact` carries
  it; `order` sets the section's date ordering; `emphasise` moves the section ahead of its default
  position. The generator still writes only from verified facts: a directive can select, order
  and surface, never author.
- `apps/documents/gaps.py`: `programme_required(student, programme) -> tuple[GapQuestion, ...]` —
  one question per `include` directive whose target has no fact, `Kind` `PROGRAMME_REQUIRED`,
  the page's sentence as the question's evidence. Joins `gap_questions` like the others.
- `apps/documents/render.py`: `unapplied` and `undecided` are advisory-only keys with no checker;
  `render_cv_with_warnings` shows both with their quotes, as it shows every advisory rule.
- `apps/documents/templates/`: STANDARD, tabular and Europass variants honour section order and
  emphasis from the content object; no template change is needed for `include` (the field is
  rendered if present, as today).
- `apps/funding/models.py`: `CVFormatConfidence.UNDECIDED`; `OfficialSourceSnapshot.unreadable`
  (bool, default False). `constraints.py::_CONSTRAINT_KEYS` gains `undecided`; `render.py` has no
  checker for it — it exists to carry a quote.
- `apps/research/reader.py`: sets `unreadable` at `persist_snapshot` time and returns early on it
  as on a refusal.
- `docs/research/cv-format-eval.csv`; `tests/documents/test_derive.py` (unit, scripted parser);
  the `live` gate in the same module.

## Error handling

- All K samples refused or off-schema → `DerivationFailure`, raised; the shared transaction rolls
  the statement write back (unchanged rule).
- Some samples refused → if fewer than K−1 survive, abstain; otherwise unanimity is over the
  survivors.
- Any `europass` candidate missing from any surviving sample → abstain.
- Accepted verdicts pointing both ways on one page → abstain.
- A constraint (index, key) with differing values across samples → dropped, surfaced as
  `undecided`.
- No `_CV_TERMS` candidates at all → no model call; `any`, `EXTRACTED`, empty constraints.

## Security

Unchanged boundaries, restated because judgement moves to a model: DATA labelled as data; closed
schema; no free-text field; a format verdict acts only on a page line carrying the word;
abstention's default is the no-egress renderer; `ProgramStatement` writes stay with the
`catalog_ingestion` role. The new trust placed in the model is bounded to *which of five closed
values a sentence the page really contains means*; it must be given three times over three
phrasings; and it is re-measured on every gate run. The statement read may *add* a constraints
candidate and never remove one, and every candidate it adds was already verified verbatim against
the archived page by `verified_statements` — so the second recall path widens what is judged and
cannot put a sentence the page does not contain in front of the judge.

Directives are the one place this design turns page text into an instruction about a student's
document, and the bound is structural: the model chooses an action and a target from lists the CV
schema defines, never free text; the generator writes only from `VerifiedFact` rows a human
accepted, so a directive can select, order or surface a fact and cannot author one; there is no
`exclude`; a gap question puts the page's sentence in front of the student as *evidence*, labelled
as the programme's words, never as an instruction to them; and document approval still follows.
The worst a hostile page can do through this channel is ask that a real fact be shown or a section
moved, in a document a counsellor reviews.

## Testing

Unit, no network, a parser scripted per sample (script length derived from `K`, never a literal —
2026-09-13 observation):

- unanimous `required` on one europass line → `europass_required`, `EXTRACTED`, no `undecided`
- 2-of-3 on the action → `any`, `UNDECIDED`, one `undecided` rule carrying the sentence
- one europass line absent from one sample → abstain even when the others are unanimous
- two europass lines, unanimous each, pointing opposite ways → abstain
- a format verdict for a non-europass index → discarded, no effect
- a europass line with no CV word ("Please use the Europass model.") → a candidate, judged
- a `_CV_TERMS` miss covered by a DOCUMENT statement → still a constraints candidate
- `other_template` → `any`, `UNDECIDED`, `undecided` rule with the quote
- the three samples receive three distinct prompts (pinned, so a refactor cannot collapse them)
- "State your ECTS credits" unanimous → `include(education.ects_credits)`; with the fact present
  the CV renders it; absent, a `PROGRAMME_REQUIRED` gap question carries the sentence
- "reverse chronological order" → `order(education, reverse_chronological)` and the rendered
  entries follow it; WE-TEAM's sentence → `emphasise(experience)` — one directive per sentence, a
  sentence naming two sections yields the model's single choice
- the MemBioMed institution-quality sentence → `unapplied` rule with the quote, no directive
- a directive on a target outside the schema's list → schema rejection, sample counts as refused
- a `_CV_TERMS` candidate missing from one sample's constraint/directive/unapplied verdicts →
  abstain
- `cv_directives` written in the same `_write_program` call as `cv_constraints`; a
  `DerivationFailure` rolls both back with the statements
- no `europass` on the page → `any`, `EXTRACTED`; no `_CV_TERMS` at all → no model call
- constraint value differs across samples → dropped, `undecided` rule with the sentence
- readable text under 1,500 characters → `unreadable`, nothing derived, previous rows stand
- the phrasing-gap sentences, scripted as the live run answered them → the labelled action; pins
  that "we suggest" can never become `required` by fallback again
- the negation, referee and choice sentences → `STANDARD` / dropped, as the deleted guards did
- hand-verified row untouched; total refusal → `DerivationFailure` rolls statements back

Live (`live` marker): the 48-sentence gate. Then the three-reads test on FAU and DAAD PRIME
asserts the *action* agrees across reads — what its 2026-09-13 reframing already measures.

## Cost

Three model calls per changed page for format, constraints and directives together — one listing,
three schema fields — on top of the three statement-read calls: six per changed page, none for an
unchanged one. `_READ_LIMIT` unchanged. Generation reads `cv_directives` from the row; no extra
call there.

## Deliberately not built

- **Conformal calibration of the agreement threshold.** It would certify "acted-upon error ≤ α" and
  it is additive later — the agreement fraction is computed anyway and the rule today is "must be
  1.0". It costs a labelled set of a few hundred sentences sampled from what production reads, a
  hold-out split, α set from the set size, and re-calibration per model, and it changes no
  behaviour. Build it when someone needs the number, not before.
- ~~**A reading from a second model family**, as one of the three.~~ Built 2026-09-14 by owner
  decision: the third phrasing goes to `claude-sonnet-5` (`derive._claude_reading`). The live gate
  has not been re-run against it yet; see CLAUDE.md.
- **A periodic audit of acted decisions.** A small random sample of pages whose decision was
  written `EXTRACTED`, re-judged by a second model, disagreements surfaced as `undecided`. It is
  the only thing that can see the gate's blind spot. Trigger: the first real programme whose
  Europass decision a human reports as wrong — until then there is no evidence the blind spot has
  anything in it, and the audit needs the second model anyway.
- JS-only pages are recorded as unreadable, not rendered; the browser tier remains stopped.
- The production caller and per-tenant rate limiting (the 2026-09-12 spec's out-of-scope items).
- Finding the cheapest model that clears the gate — a one-line change once the gate exists.
- ~~**Lowering the advisory abstention rate.**~~ Done 2026-09-14 by the majority rule above: 4–5 of
  14 advisory rows undecided per run (29–36%) became 0/14, at the cost of one wrong attribution that
  the third-party guard then closed. What stays out of scope is lowering it on the *format*
  dimension, where unanimity is the point.
