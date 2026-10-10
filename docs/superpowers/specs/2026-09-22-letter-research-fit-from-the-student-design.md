# Research fit from the student outward: a ladder of anchors, profile-free search, verification by construction

Status: **approved 2026-09-22; implementation plan `docs/superpowers/plans/2026-09-22-letter-research-fit.md`.**
Date: 2026-09-22.
Supersedes: `2026-09-15-letter-research-fit-design.md` (kept as the record of the crawl-first
design and why it lost). Amends: `2026-08-22-phase2-motivation-letter-engine-design.md` — the
`WHY_PROGRAMME` unit, the `SOURCED` claim kind, and that spec's own 2026-09-15 amendment header.
Reads: `docs/research/2026-09-14-letter-storytelling-evidence.md` (N-04, N-15, N-19, the §2.3
reader table and its immigration row), `docs/research/letter-rules.csv` (L-004, L-028, L-041/042,
L-045, L-048, L-050, L-058, L-059, L-062),
`docs/superpowers/specs/2026-09-17-role-routed-discovery-design.md` (§4.13 roster, §5 demand
cells, §8 provider terms), `docs/superpowers/specs/2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md` (§4 fetch path)
— **those two, and the two plans cited below, live on branch `claude/program-page-reader` and are
not yet on master**; "the roster" below means the first of them.

## Goal, in three beats

**What and why.** The one paragraph an admissions committee weighs — *why this programme* — is the
one the shipped letter engine cannot fill. Its `WHY_PROGRAMME` unit must carry a `SOURCED`
claim (N-15, 2026-09-14; `letter_gates._SOURCED_REQUIRED_ARCHETYPES`) and nothing supplies one: `ApplicationPrompt.programme_evidence`
is hard-coded empty and never reaches the model, so the gate is satisfiable today only by a
model-invented URL that `verify_letter_claims` waves through. This design fills the slot **from the
student outward**: the strongest specific thing the student has — a thesis, an internship, a
course, or only an interest — becomes the query, the institution's own site is searched for its
counterpart, and the sentence found there, verified verbatim, is what the letter cites. Every
student gets the paragraph; a student with nothing but an interest gets it honestly labelled as one.

**The catch.** A professor's name, a group's name and a paper's title are exactly what a committee
can check, and the Cambridge rule treats a hallucinated one as fraud that withdraws every
application. So no model ever *writes* a sentence that reaches the letter: sentences are split by
code from our own fetch of the institution's page and models only classify them; alignment is a
judged majority; the claim is checked at generation and again at render. And no student data ever
reaches a search provider — both Exa (ToS §1.2(c)) and Tavily (§9.2) take a perpetual licence over
query text, so the query is a topic phrase with the student stripped out, tested. What the design
cannot reach is the unpublished — whether a professor is taking students, a lab's culture, whether
funding follows from proximity to a group (`phased requirements.md` §2 forbids inferring that by
name) — and the slot stays empty rather than guessed (N-19).

**What it costs to reverse.** One provenance JSON field on `NarrativeInput`, one search adapter the
discovery design already plans, one stricter check in claim verification that should exist
regardless. Removing the feature leaves the stricter check and an unused field.

## 1. What exists — measured 2026-09-22 on master `47a5e22`

- **The letter engine is complete and inert.** All 18 tasks of the 2026-08-23 plan are merged (PR
  #91). Nothing outside `apps/documents/` imports it: `api.py`'s `_SUPPORTED_KINDS` is CV-only
  with a comment forbidding widening, and `document_worker.py` returns unless the kind is CV. Every
  gap below is unreachable until a caller is wired; a caller makes the first two live defects.
- `check_generic_paragraph` requires a `WHY_PROGRAMME` unit to carry a `SOURCED` claim
  (`letter_gates._SOURCED_REQUIRED_ARCHETYPES`, the N-15 amendment). `verify_letter_claims` marks a
  `SOURCED` claim supported whenever `source_url` is non-empty (`letter_verification.py:36-41`) and
  never refetches.
- `SOURCED` has a second meaning in the engine design (2026-08-22, the `LetterClaim` kinds): *a
  cited fact about the home-country context* — DAAD A10's "facts and figures about the problem at
  home". Any verification rule on `SOURCED` must leave that use a route.
- `LetterClaim` carries `fact_id`, `input_id` and `source_url`, and the design reserves `input_id`
  for `DECLARED` claims. Its span is sentence-level — hygiene widens spans to sentence bounds
  (Task 16) — so an entity check must read the claim's own text, never its span.
- The engine's one non-negotiable rule is immigration: claims under `ApplicationPrompt.immigration`
  must be confirmed (`letter_approval.py`), `IMMIGRATION_PROHIBITION` lives in
  `letter_ai_policy.py`, and the 2026-09-14 amendment writes *no story* for immigration prompts. The
  evidence table's row: any invented "why" is misrepresentation with legal consequences (L-004,
  L-058, L-059).
- `letter_approval.py`'s flag list is closed (engine design decision 9); a new residue needs a
  named flag.
- `letter_gates.sentence_spans` splits on terminal punctuation followed by whitespace. Right for
  letter prose; on page text it cuts "Prof. Dr. A. Schmidt" into four pieces and merges
  `readable_text`'s heading and bullet lines, which carry no terminal punctuation.
- The `CONSORTIUM_SPECIFIC` structure fails closed with no generation (engine design).
- `prompt_resolution.py` sets `programme_evidence = {}` on every resolution rung; `letters.py`
  never receives it.
- `NarrativeInput` (`documents/models.py`) carries `student`, `kind`, `text`, `proposed_by`,
  `confirmed_at`, `created_at` — no provenance. Its kinds include `PERSONAL_BACKGROUND` and
  `RESEARCH_PLAN`; `proposed_by` distinguishes engine from student.
- `VerifiedFact.Category` has `EDUCATION | EXPERIENCE | RESEARCH | PUBLICATION | AWARD | LANGUAGE |
  SKILL | PERSONAL | REFERENCE | IDENTITY`. A `RESEARCH` payload (`evidence/facts.py::ResearchEntry`)
  carries `thesis_title`, `institution`, dates, `methods`, `outcomes`; GitHub project descriptions
  are written as `RESEARCH` facts with `STUDENT_STATEMENT` tier.
- Every letter has a storyline theme (`storyline.py`, Task 11b): three candidates, a deterministic
  choice, theme kind by `funder_kind`. This is the anchor of last resort and it always exists.
- `apps/research/search.py::SearchSource` posts to Tavily with a `RunBudget` and `rate_limited`,
  and leaves domain restriction out — its comment: *"Add it back with the caller that needs it, not
  before."* No Exa adapter exists on any branch; the organisation-register plan
  (`2026-09-18-organisation-register-and-provider-protocol.md`, branch `claude/program-page-reader`)
  names it as Task 6, `apps/research/providers/exa.py`.
- The research fetch path on master is `apps/research/egress.py::fetch_official_source` (own
  egress, `validate_public_url` on every hop, `require_same_origin`). The vendor path — Firecrawl
  first, scrape.do on the residue — is designed and planned (`2026-09-19-vendor-fetch-path-and-deletion.md`, branch
  `claude/program-page-reader`) and not yet merged. This design calls *the research fetch path*, whichever is live.
- The CV-format judge (`derive.py::_judge`) asks one closed question three times — two
  `OPENAI_EXTRACTION_MODEL` readings and one Claude reading — and acts only on agreement. That is
  the judge shape reused here.
- The discovery design's §5 rule: **the student never prompts a provider; a profile-free cell
  does.** A test asserts no profile field reaches any query the planner emits. This design extends
  that rule to one more path.

## 2. Owner decisions, 2026-09-22

1. **No question before the draft.** The letter is written with the name in it; the student edits
   afterwards. This retracts the 2026-09-15 spec's overlay confirmation and restores the
   2026-09-14 line (decision (c), struck): "nothing asked before a draft".
2. **Search from the student, never crawl to a depth.** The depth question is dissolved, not
   answered.
3. **Decision 6 — the `SOURCED` verification fix — ships first**, independent of the rest.
4. **Providers at full paid capability, cost-optimised**: Exa and Tavily on their paid tiers,
   configured for the fewest results that serve the job, every billed cost recorded.
5. **Jev (TypeSafe's System One model) is evaluated** for the closed-question slots, adopted only on
   a measurement.
6. **Scope is the letter.** Using research fit to choose which programmes enter the pack belongs to
   the pack optimizer and gets its own design after this one.

## 3. Decisions

### D1. The anchor ladder — every student has one

The query is **the strongest specific, checkable thing the student has**, and the target is its
counterpart at that level on the programme's site. One pipeline, run at most twice per letter:
first with the strongest verified fact, then — on a miss, or when no fact exists — with the
storyline theme.

| Rung | Student has (ledger category) | Search the programme's site for | Claim kinds in the letter |
|---|---|---|---|
| 1 | thesis, publication, project (`RESEARCH`, `PUBLICATION`) | the group, chair, lab or named faculty doing that work | `FACTUAL` + `SOURCED` |
| 2 | internship, job, technique (`EXPERIENCE`, `SKILL`) | the applied track, lab, industry partnership | `FACTUAL` + `SOURCED` |
| 3 | degree field, courses (`EDUCATION`) | the module, specialisation or track that builds on it | `FACTUAL` + `SOURCED` |
| 4 | **only an interest** — the storyline theme, or a student-typed `NarrativeInput` | any group, module or track doing that | `DECLARED` + `SOURCED` |

Rung 4 is what makes the engine robust for the student who has "just studied": the interest is
the student's own statement, honestly marked; the group's sentence is verified on the university's
page. The paragraph reads *"I want to work on grid integration of renewables; your Energy Systems
chair's work on exactly that is why I chose this track"* — and it is true in every part a committee
can check.

**The floor under the ladder is already built, and it is thinner than its name.** Nothing found →
`WHY_PROGRAMME` uses the programme's own catalogued module/track/consortium facts (N-15) — but the
statement reader reads *admission obligations*, so a module or track sentence is in the catalog only
when the admissions page happened to state one. Rung 3's search is what actually supplies module and
track facts; the floor is mostly the gate. Nothing there either → the existing gate blocks the letter
and the counselor sees why (`check_generic_paragraph`). Fail-closed and visible; never a silent
generic paragraph.

**Immigration prompts run no research fit at all.** When `ApplicationPrompt.immigration` is true the
ladder does not run and no `NarrativeInput` is proposed: the engine's existing immigration path
governs — confirmed claims only, no story, the AI-use prohibition — because an engine-chosen "why"
there is misrepresentation with legal consequences (§2.3 immigration row; L-004, L-058, L-059).
Owner decision 1 (write, don't ask) does not reach this class of letter.

### D2. No student data reaches a search provider — the query is a topic phrase, and a test says so

Read on the cited hosts, 2026-09-22:

- **Exa Terms of Service §1.2(c)**: *"You grant us a nonexclusive, royalty-free, transferable,
  sub-licensable, worldwide, perpetual and irrevocable license to access, use, host, cache, store,
  reproduce, transmit, display, publish, distribute, and modify any User Input and Output as needed
  to provide, develop, and improve upon our products and services."* Exa's privacy policy: query
  data is used *"to improve Exa's products and technology, including by training and fine-tuning
  models"* and *"query fields are not intended for the submission of personal information."*
- **Tavily §9.2** takes the same perpetual licence over query text — already the reason the
  discovery design keeps every query profile-free (§5).

So the thesis title never leaves the building. The query is a **topic phrase** derived from the
anchor — *"gait control for legged robots"*, never *"Design of a gait controller for the BSU
quadruped"*:

- Derivation: one small model call with a closed output (≤ 8 words, lowercase, no digits, no proper
  nouns), or — cheaper and preferred where present — the `methods`/`outcomes` keywords the evidence
  pipeline already stores in English. For rung 4 the storyline theme is already generic.
- A code guard then strips any token sequence found in the student's `IDENTITY` name, any
  institution named in their `EDUCATION`/`EXPERIENCE` payloads, any capitalised multi-word phrase,
  and any four-digit year.
- **A test asserts** that for a fixture student no emitted query contains the name, an institution,
  or the thesis title verbatim — the §8 pattern from the discovery design, applied here.

Exa offers zero-data-retention on request; with profile-free queries it is not needed, and the
design does not depend on it.

### D3. Providers — paid tier, fewest results that serve the job, billed cost recorded

| Provider | Role | Configuration | Cost |
|---|---|---|---|
| **Exa** | primary search: semantic, so *"gait control for quadrupeds"* finds a page that says *"legged locomotion"* | `POST /search`, `type: "auto"`, `numResults: 5`, `includeDomains: ["<domain>", "*.<domain>"]` (the API accepts wildcards), **no `contents`**, `excludeDomains` = the aggregator denylist | $7 / 1k requests up to 10 results (`exa.ai/pricing`, read 2026-09-22) → **$0.007 per search**, ≤ 2 per letter. `costDollars` from every response is recorded per run, never estimated (roster §4.13). |
| **Tavily** | keyword fallback when Exa returns nothing for a domain | `search_depth: basic`, `include_domains`, `max_results: 5`; never `language`/`filter_by_language` (measured harmful, §4.4) | 1 credit; rare |
| **Firecrawl / the research fetch path** | fetch the 2–3 pages found | whatever the live path's scrape configuration is; `require_same_origin` against the programme's `canonical_url` origin | ≈ $0.0008 per page on the vendor path; $0 on own egress |
| **Frontier model** (`OPENAI_EXTRACTION_MODEL` + the Claude reading) | classifier and judge — the incumbent | the existing `_judge` shape | cents per letter |
| **Jev** (TypeSafe) | *candidate* for the classifier and judge slots, behind the gate in D6 | `POST /v1/systemone`, `model: "jev-latest"`, one sentence per call, Noul + Choice questions | $0.042 per million input tokens, output free → ≈ $0.001 per letter |

**Not used, on purpose.** Exa `contents.highlights`, the `deep*` search types, `category` filters
and `includeText`: three cheap fetches make highlights unnecessary, deep modes cost 2× for a
question `auto` answers, and the roster measured `category` and `includeText` as harmful. Keeping
`contents` off also keeps the **"a provider yields a URL and nothing else"** discipline (roster
§4.6) intact for this path — the owner's permission to relax it is on record; on the numbers there
is nothing to gain by using it.

**Exa's use rests on the owner's written permission of 2026-09-17** (condition: no competing-search
training), recorded in the roster's §8 and in the "Search providers" section of `CLAUDE.md` on branch
`claude/program-page-reader`. Master's `CLAUDE.md` still carries the earlier text ruling Exa and
Brave out on their definitions; that text is superseded by the grant and is corrected when the branch
merges. Read the roster before re-deriving either position.

**A second query in the site's language** (D12) is the only planned widening.

### D4. Fetch through the research fetch path; cache the page per tenant

- The top 3 hits are fetched through `fetch_official_source` (or its vendor successor), which
  validates every hop. `require_same_origin(programme.canonical_url, fetched)` applies: an off-origin
  redirect is dropped, not read. The programme page itself is excluded from the hit list — the
  catalog already read it.
- A page whose readable text falls under the reader's unreadable threshold (< 1,500 characters at
  ≥ 20,000 bytes) yields nothing and is recorded as `unreadable` — the honest outcome for a
  client-rendered shell, not a page that says nothing.
- Fetched page text is cached **per tenant** in the existing cache, keyed by URL and content digest,
  with a TTL of 7 days. It is public page text keyed by nothing about a student; two students at one
  agency hitting the same chair page pay one fetch.

### D5. Sentences are split by code; models only classify — verification by construction

The shipped reader has a model *quote* sentences and then verifies each against the page, which is
why `dropped_quotes` exists. Here the page is split into sentences by code —
`readable_text`'s lines first, then a **page-aware splitter** that knows abbreviations and honours
line boundaries; **not** `letter_gates.sentence_spans`, which cuts "Prof. Dr. A. Schmidt" into four
pieces and merges bullet lines (§1). A test pins "Prof. Dr. A. Schmidt leads the chair." as one
sentence and two bullet lines as two. A model then answers two closed questions per sentence:

- *relevance* — "does this sentence describe research or teaching work related to `<topic>`?" →
  a probability;
- *kind* — one of `research_group | named_person | module_or_track | industry_partner | none`.

No model ever authors a sentence that reaches the letter, so the "is it really on the page" check
holds by construction, with no quote to drop. Each kept sentence also gets an `entity` — the
verbatim substring naming the group, person, module, track or partner — returned by the frontier
classifier and checked as a substring of the sentence, or chosen by code from the sentence's
title-pattern spans ("Prof.", "Chair of", "Lab", "Institute") when Jev classifies; a sentence with
no entity is kept as `kind = none` and never becomes a `SOURCED` claim. Each candidate is scored on one sentence with a short
window of context, never a whole page: the classifier sees the least text that carries the
decision. The top-k sentences by relevance (k = 3) go to the judge.

### D6. Alignment is judged, not asserted; Jev is a candidate, not an adoption

> **2026-09-27: this section is history, not the current design.** The gate below
> (`research_fit/jev.py`, its live test and its labelled EN/DE/TR eval set) was an unwired
> duplicate of the typed-decision client audit finding 2 identified — the "no real student
> text before the DPA" condition was written only against this dead copy, while the live
> Jev client (`apps/research/decisions.py`) reads a *different* class of student text with no
> such check. `research_fit/jev.py` and its tests are deleted; research-fit classifies
> through `FrontierClassifier` only. Any future Jev use in this path goes through
> `apps/research/decisions.py`, gated the way `apps/documents/transcript.py` now gates
> transcripts (`TRANSCRIPT_JEV_ENABLED`) — a launch-gate decision, not a code path
> `research_fit/service.py` reaches on its own.

For the single best (anchor, sentence) pair — not every combination — the closed question *"does
this sentence describe work the student's anchor is directly about?"* is asked in the existing
`_judge` shape: three readings, majority `strong` required. One pair keeps this at three calls.

**Jev.** Read on `docs.typesafe.ai` and `typesafe.ai/legal/*`, 2026-09-22. A classifier, not a
generator: text in, typed decisions with probabilities out (Noul = yes/no probability; Choice =
one-of-N with a distribution and a `confidence`; Score = a scaled level). 64k context, 32k for
`state`; 250,000 tokens/s and 1,200 requests/min; 70–500 ms. Legal posture is clean for our use:
privacy policy *"We will not train or fine tune any artificial intelligence or machine learning
models on your prompts or other Input"*; MCA §4.1 grants a processing licence for the term only and
excludes training without consent; a DPA with EU SCCs Modules 2/3, the UK addendum and a published
sub-processor list; US-hosted; zero-data-retention for enterprise.

Why it is worth a slot: the three-readings majority exists because frontier models do not give
calibrated confidence; Jev's whole design is that the probability *is* the confidence, so one
thresholded call could replace three, at two orders of magnitude less cost and in milliseconds.
Why it is not simply adopted: it is weeks old; its own docs say non-English is *"handled but not
equally well"* and our pages are German, Dutch, Turkish; it *"answers the question you wrote, not
the one you meant"* and degrades as unrelated text enters the state (hence D5's one-sentence
windows); and calibration is claimed across populations, *"not … that an individual answer is
correct."*

**The gate.** A labelled set — English, German and Turkish page sentences, synthetic student
anchors, no real student text — judged by the frontier majority and by Jev. Same pattern and same
bar as the CV-format eval (`docs/research/cv-format-eval.csv`): Jev takes a slot only where it
agrees with the frontier's unanimous verdicts at ≥ 95% and never disagrees in the direction that
would name a wrong person. Passes → Jev classifies (D5) and, if it also passes the judge subset,
judges; the frontier majority stays as the fallback reader on low confidence. Fails → nothing
changes. **No real student text reaches Jev before its DPA is on file** (§11).

### D7. Store with the student, not in the shared catalog; record the outcome either way

The result is an engine-proposed `NarrativeInput` for that student, `proposed_by = ENGINE`,
**pre-accepted** (owner decision 1), carrying a `provenance` JSON: `{sentence, source_url,
page_digest, kind, rung, anchor_fact_id, judgement}`. Tenant data: erased with the student, no
cross-tenant exposure, and **no new privileged writer** — the 2026-09-15 design's shared
`ProgramStatement(kind=RESEARCH)` rows would have needed the `catalog_ingestion` role on a path a
student's request triggers. Reuse across students is lost and is worth pennies (D4 caches the fetch,
which is the slow part); promotion to the shared catalog is a follow-up with a trigger (§9).

**Every run records an outcome** on the same row or its absence: `matched | no_match | unreadable |
provider_unavailable`, with the rung reached and the billed cost. This is deliberate: it is the data
the pack optimizer will need when owner decision 6's "later" comes, and it costs nothing to keep now.

### D8. What the letter says, and what kind each part is

- The group/person/track sentence is a `SOURCED` claim; the student's choice and reason is a
  `DECLARED` claim citing the `NarrativeInput`; the "so what" is `INTERPRETIVE`. No new claim kind.
- `letters._call_model` gets a third labelled DATA block, *programme research facts*, listing the
  accepted (anchor, sentence, URL) triples — untrusted page text labelled as data, per the reference
  pattern. One line is added to the prompt: *connect the group's work to the applicant's; do not
  describe the group.* At most one short quotation of the page's own words (§2.3: Chevening
  penalises pasted site copy; Göttingen: "we wrote it, we know it"; L-028). The DAAD no-flattery rule
  (L-028) is already there. Rung 3 connects **one** module or track to what the student did and never
  lists related courses (TUM, §2.3; L-050) — the coursework-only case is the mass case, and a module
  list is its failure mode.
- *"Over standard coursework"* is written only when the programme states the alternative
  (`Program.academic_track == RESEARCH`, or a catalogued statement establishing a thesis-in-group
  or research-track option). Otherwise the sentence invents a structure and the prompt forbids it.

### D9. Decision 6, stated precisely — what `verify_letter_claims` checks for a `SOURCED` claim

The 2026-09-15 text said the anchor must be *"a normalised substring of the archived snapshot"*.
Taken literally that forces the letter to quote the page, which the readers penalise (§2.3; L-028).
The check is **entity-level**, it applies to an **engine-written** `SOURCED` claim that names an
entity — a person, group, lab, chair, module, track or partner — and it is three conditions:

1. the claim carries `input_id` = the `NarrativeInput` whose `provenance` backs it, attached to
   *this* letter's inputs, with a matching `page_digest`. `input_id` is therefore no longer reserved
   for `DECLARED`: the field rule changes, the schema does not;
2. the provenance record's `entity` appears, normalised and case-insensitive, in the **claim's own
   text** (`claim.text`, never its sentence-level span — hygiene widens spans to the sentence, and an
   institution name sharing that sentence is not the claim), and every capitalised multi-word phrase
   in that text appears in the provenance sentence. The first half closes the lowercase ceiling the
   09-15 spec recorded — "the robotics group" passing `check_claim_coverage` untriggered — and the
   prompt writes names as the page writes them. The letter may paraphrase the work, never the name;
3. the `source_url`'s origin matches the programme's institution (`require_same_origin`).

   **Ships differently from this wording.** `letter_verification.py::sourced_claim_matches`
   condition 3 is `claim.source_url == provenance.get("source_url")` — an exact match against the
   provenance record's own stored URL, never a fresh `require_same_origin` call against the
   programme. That is stronger in practice, not weaker: the domain was already enforced once, at
   fetch time, by `fetch_page` (D4, `on_domain`) before the sentence was ever stored, so re-deriving
   and re-checking the origin here would only repeat a guarantee the provenance record already
   carries. Read this bullet as describing the guarantee, not the call the code makes.

The capitalised-phrase check inherited `CAPITALISED_PHRASE_PATTERN`, which matched only
directly-adjacent capitalised words, so a fabricated name containing a lowercase joiner —
"Institute of Advanced Study" — was not caught by this condition on its own; the entity check
(condition 2) was what bound there. **Closed, merged from master 2026-09-23:** the regex was
replaced by `letter_gates.capitalised_phrases`, a tokenizer-based walk that treats connectors such
as "of", "for" and "von" as continuing a proper-noun run rather than breaking it, so "Institute of
Advanced Study" and "Technical University of Munich" are each one phrase, not two truncated ones.
`sourced_claim_matches` now calls `capitalised_phrases(claim.text)` in place of the old regex's
`finditer`, so a fabricated name carrying a lowercase joiner is caught by condition 2 the same way
a directly-adjacent one always was.

**Two things this does not touch.** A `SOURCED` claim citing a *home-country context* fact (DAAD
A10, the claim kind's second meaning) names no entity from a programme page and has no research-fit
producer: it keeps its `source_url` and raises a `source_unverified` approval flag the counselor
clicks through — a flag, not a block — until a home-context producer exists (§9). And a name the
**student** types in after the draft is the student's own assertion: recorded as `DECLARED` with
`input_id` pointing at their edit, shown as unverified in the overlay, never `UNSUPPORTED` — the
fabrication gate exists to stop the model inventing, never to second-guess the student (engine design
decision 8; owner decision 1). `SOURCED` is reserved for what the engine verified.

An engine-written entity claim that fails any condition is `UNSUPPORTED` and the letter does not
pass; a plausible URL is no longer enough. **This ships first and alone** (owner decision 3); it
closes a live hole whether or not the rest is ever built.

**Re-check at render.** `mark_letter_ready` / the render path re-fetches the `source_url` (one
cached fetch), compares digests, and on change re-runs condition 2 against the fresh text. A dropped
sentence raises a new approval flag, `source_stale`, with the quote beside it — added to
`letter_approval.py`'s closed flag list, the same residue shape the CV format decision uses. A letter
never ships a name the page no longer carries.

### D10. Wrong institution

The provenance record's origin joins the letter's expected-institution set in
`check_wrong_institution`, so a professor cited with another affiliation — a visiting scholar's page
on the same host, a joint-appointment — trips the existing gate.

**Not implemented.** Nothing joins the provenance record's origin to `check_wrong_institution`'s
expected-institution set: `letter_gates.py::run_letter_gates` calls it with `allowed_names=frozenset()`
always, and the function's own docstring notes the parameter is unused inside it (Task 6 shape, kept
as-is). The residual, stated plainly: a visiting scholar named on the institution's own page whose
home affiliation is elsewhere would pass, uncaught by this gate. Deferred rather than fixed here
because `fetch_page` (D4) already guarantees the cited sentence came off the programme's own
institution's domain — the origin check this section describes would be a second, narrower filter on
top of that guarantee, not the only thing standing between a citation and the wrong institution.
Revisit when either arrives first: the feature gets its first production caller, or a mis-affiliation
like the one above is actually observed.

### D11. Research fit never blocks a letter by failing

Exa down → Tavily; both down → outcome `provider_unavailable`, floor. A fetch fails → next hit. The
classifier or judge errors → outcome `no_match` with the reason. In every case generation proceeds on
the floor (D1). The **only** blocking outcome is the existing gate finding nothing at all, and that
one is visible. Latency target for the whole step: under 30 seconds; it runs as its own unit of
work *before* generation, with its own transaction, so generation's transaction shape is unchanged
and the reader's idle-in-transaction cost (`CLAUDE.md`) is not extended.

### D12. A second query in the site's language — derived from the programme, never the student

The topic phrase is English. Where the programme's site language is not — read from the
programme's country and teaching-language facts already in the catalog, never from the student —
one more Exa search runs with the phrase in that language (one small model call to translate a
generic phrase; no personal data is involved because D2 already removed it). The roster measured
local-language queries beating English on local content in all four countries tested (§4.4); the
same is expected on a German chair's page. Cost: one more $0.007.

### D13. Consortia and funder letters

- A consortium programme (Erasmus Mundus and kin) searches the programme's `canonical_url` domain
  first and each partner domain the catalog records, one search each, stopping at the first
  `strong` match. This applies to structures that generate; `CONSORTIUM_SPECIFIC` fails closed with
  no generation (engine design) and gets no search.
- A **funder-only letter** with no programme attached (a scholarship statement written before the
  programme is chosen) skips research fit; its `WHY_PROGRAMME`-class unit uses the funder's own
  catalogued facts, as today.
- PhD and research-track applications where a funder *requires* a named supervisor (MEXT, CSC, GKS)
  are out of scope; the ladder finds a person where the page names one and **never makes one
  mandatory** (2026-09-15 "deliberately not built", kept).

### D14. Third-party personal data — a professor's name in tenant rows

A name reaches a model and a tenant table. It is published by the employer on its own site about
the person's professional role, archived with provenance, holds no special-category data, and is
stored only as the verbatim sentence (2026-09-15 D10, kept). Two things change with per-tenant
storage:

- **Takedown or correction** can no longer be a single catalog fix. It is an **audited admin
  command** that searches `NarrativeInput.provenance` across tenants for the name — a cross-tenant
  read of data that is *not about a student*, reason-bound and leaving an `AuditEvent`, through the
  `SECURITY DEFINER` route `CLAUDE.md` sanctions for exactly that class. It never reads a student
  field.
- The render re-check (D9) purges stale names on its own: a professor who has left stops appearing
  in new renders the day the page changes.

### D15. Cost controls and idempotency

- Per-student limiter `research-fit`, 20/hour, via `rate_limited` — on top of generation's own.
- **Per-tenant daily ceiling on billed VENDOR SEARCH cost only** (`RESEARCH_FIT_DAILY_CEILING_USD`,
  `service.py::spend_within_ceiling`), summed from Exa's recorded `costDollars` and Tavily's
  credits × rate, in the `cost_usd` shape the funder design records — a ceiling on what the search
  vendors *charged*, never on an estimate. **Correction, post-implementation:** this section
  originally said the ceiling meters search, fetch *and* model tokens at list price. It doesn't —
  fetch had no per-call vendor charge to sum at the time, and no per-model-call price is recorded
  anywhere in this codebase to meter tokens against, so inventing one to match the old wording would
  be a fabricated number standing in for a real limit. Model-call *volume* (not cost) is bounded
  separately, by the same per-student `research-fit` rate limit above (20/hour) — that is the
  circuit-breaker on runaway token spend for this feature, not the daily ceiling.
- **Second correction, 2026-09-23, and this one is not cosmetic.** The premise above — "fetch has no
  per-call vendor charge" — was true only because `pages.py::fetch_page` called our own local egress
  client. Master moved four PRs ahead while this branch was open and deleted that client as part of
  its vendor-only fetch redesign (see CLAUDE.md's "Web fetching"); the merge into this branch
  switched `fetch_page` to `apps.research.discovery.retrieve_official_source`, i.e. the
  Firecrawl-then-scrape.do vendor path. **Every research-fit page fetch is now a billable vendor
  credit** (~$0.0008/fetch, up to ~$0.003 when a fetch escalates to scrape.do's heavier tier), and
  `spend_within_ceiling` never sees it — `RESEARCH_FIT_DAILY_CEILING_USD` sums search cost only, as
  stated above, so fetch spend is currently unmetered by anything in this feature. The scale: one
  `propose_research_fit` call can make up to roughly `2 anchors × domains × 2 queries × 3 pages`
  fetches, bounded on the outside only by the per-student `research-fit` call limiter (20/hour) —
  which is a call count, not a dollar figure, and was never sized against a per-fetch vendor cost
  because none existed when it was set.

  **A fetch-side bound is therefore owed and not yet designed here**, because
  `retrieve_official_source`'s own docstring is explicit that wiring one in is not this function's
  call to make ("Wiring a budget in here means deciding whose it is"). Two shapes, not chosen
  between: (a) thread a `SweepBudget` through `retrieve_official_source` from `pages.py`, scoped to
  research-fit's own per-call or per-student ceiling, the same mechanism a discovery sweep already
  uses; or (b) fold the vendor's returned fetch cost into `spend_within_ceiling` itself, so the
  existing per-tenant daily ceiling meters search-plus-fetch together instead of search alone. Either
  is a real design decision (whose budget, what happens on exhaustion mid-`propose_research_fit`) and
  is recorded as owed in §11, not decided here.
- Idempotency key `(student, programme, topic-phrase hash, page_digest)`: the same letter regenerated
  against unchanged facts and an unchanged page reuses the stored `NarrativeInput` and pays nothing.

### D16. Visibility — counselor and student

- The counselor's approval view shows, beside each `SOURCED` claim: the verified sentence, its URL,
  the rung, and the judge's verdict. An `example_not_recent`-style flag is not needed; the source is
  its own explanation. The counselor can strike the claim, which removes the `NarrativeInput`.
- The student's letter overlay shows a source affordance beside the `SOURCED` span — the glass-box
  premise applied to the letter: nothing named in it is unexplained. Striking it there has the same
  effect.

### D17. Student edits are re-gated

A post-draft edit produces a revision (`letter_revisions.py`) and the gates re-run on it. An edit
that *adds* a name yields a `DECLARED` claim (D9), never a block; an edit that *changes* an
engine-verified name inside a `SOURCED` claim fails D9 condition 2 and the claim is downgraded to
`DECLARED` with the same unverified marker, not `UNSUPPORTED`. **Plan-level check, not assumed:** confirm the revision path re-runs
`verify_letter_claims`; if it does not, this design adds that call, because D9's guarantee is only
as good as the last text checked.

## 4. Data flow

```
student ledger ──► strongest anchor (rung 1–3) or storyline theme (rung 4)
                        │
                 topic phrase (closed output) ──► guard: no name / institution / proper noun / year
                        │                          test: no profile field in any query
        Exa /search, includeDomains=<programme domain>, numResults 5  [+ site-language query]
                        │  (Tavily basic on empty)
                 top 3 URLs ──► research fetch path ──► require_same_origin ──► tenant page cache
                        │
                 code splits sentences ──► classifier: relevance + kind  (frontier | Jev, gated)
                        │
                 best (anchor, sentence) ──► judge ×3, majority strong  (frontier | Jev, gated)
                        │ strong                         │ no
      NarrativeInput(ENGINE, pre-accepted, provenance)   outcome recorded; floor (N-15)
                        │
      letters._call_model: DATA block "programme research facts"  ──► WHY_PROGRAMME / RESEARCH_PLAN
                        │
      verify_letter_claims: provenance ∧ entities ⊂ sentence ∧ same origin  ──► render re-check
                        │
      counselor sees sentence + URL + verdict; student sees the source beside the span
```

## 5. Data model

- `NarrativeInput.provenance` — nullable JSON: `{sentence, entity, source_url, page_digest, kind,
  rung, anchor_fact_id, judgement, outcome, cost_usd}`. One migration. No new table.
- `LetterClaim`: no schema change; `input_id` is now set on `SOURCED` claims (the backing
  `NarrativeInput`) as well as `DECLARED` ones (D9).
- No change to `ProgramStatement`, `ApplicationPrompt` or `VerifiedFact`.
  `ApplicationPrompt.programme_evidence` stops being read for this purpose: the prompt block is
  built from the letter's `NarrativeInput` rows, so the orphan field is left as it is until a
  separate cleanup removes it.
- Page cache: the existing cache backend, key `research-fit:page:<tenant>:<sha256(url)>`, value
  `{digest, text}`, TTL 7 days. Not a table; not personal data.

## 6. Prompt and gates

- `letters._call_model`: third DATA block (D8); one added instruction line.
- `verify_letter_claims`: D9, conditions 1–3; ships first.
- `check_wrong_institution`: D10.
- `letter_approval.py`: two flags join the closed list — `source_stale` (the render re-check) and
  `source_unverified` (a home-context `SOURCED` claim with no producer).
- `check_claim_coverage`, `check_generic_paragraph`, hygiene: **no change**. Coverage is
  load-bearing for names and is recorded as such; generic-paragraph is what a `SOURCED` research
  claim satisfies; `normalize_text` never touches letters or diacritics, so "Ångström" survives.
- `mark_letter_ready` / render: the re-check (D9). This is also where the parked residual from the
  final letter-engine review — *content re-derived from the caller's argument rather than the row*
  — must close before any live caller: the re-check reads `document.content`, never a parameter.

## 7. Cost per letter

| Step | Calls | Cost |
|---|---|---|
| topic phrase | 0–1 small model call | < $0.001 |
| Exa search | 1–2 (+1 site-language) | $0.007–0.021 |
| fetch | ≤ 3 | ≤ $0.0025 vendor / $0 own egress |
| classify ~60 sentences | frontier: 1–2 calls · Jev: 60 × ~200 tokens | cents · ≈ $0.0005 |
| judge one pair | frontier: 3 readings · Jev: 1 | cents · ≈ $0.0001 |
| **total** | | **≈ 2–10 ¢ on the frontier path; under 1 ¢ if Jev takes both slots** |

Only letters actually generated pay; only students with an anchor beyond the theme run rung 1–3;
the idempotency key (D15) makes regeneration free.

## 8. Testing

- **Query hygiene.** A fixture student with a distinctive name, institution and thesis title: no
  emitted query — Exa, Tavily, the site-language variant — contains any of them (D2).
- **Ladder.** A student with a `RESEARCH` fact queries rung 1; with only `EDUCATION`, rung 3; with
  nothing, rung 4 from the storyline theme; each records its rung.
- **Verification by construction.** Every sentence in a provenance record is a code-split sentence
  of the cached page text; a classifier output naming text not on the page cannot occur (there is
  no path for it), and a test asserts the classifier interface accepts sentence ids, not strings.
- **Judge.** Same pair judged three times; 2-of-3 `strong` proposes, 1-of-3 does not; a `weak`
  majority proposes nothing.
- **Decision 6, negative controls.** A `SOURCED` claim with a plausible URL and no provenance →
  `UNSUPPORTED`; one whose span names a person absent from its provenance sentence →
  `UNSUPPORTED`; an off-origin URL → `UNSUPPORTED`. A positive control passes all three.
- **Render re-check.** Change the cached page so the sentence is gone → `source_stale` flag,
  counselor residue.
- **The two untouched cases.** A home-context `SOURCED` claim with a URL and no provenance →
  `source_unverified` flag, letter passes; a student-typed professor → `DECLARED`, letter passes,
  overlay marks it unverified.
- **Immigration.** `ApplicationPrompt.immigration = True` → the ladder does not run, no
  `NarrativeInput` is written, the existing immigration path is untouched.
- **Lowercase ceiling.** A claim reading "the robotics group" against a provenance entity "Chair of
  Robotics" → `UNSUPPORTED`; the same claim reading "the Chair of Robotics" → supported.
- **Splitter.** "Prof. Dr. A. Schmidt leads the chair." is one sentence; two bullet lines are two.
- **Failure paths.** Provider 5xx, fetch timeout, classifier error: generation proceeds on the
  floor, outcome recorded, nothing raised to the student.
- **Isolation.** `NarrativeInput` rows are tenant-scoped (`rls_enforced_orm`); no `IDENTITY` fact
  enters the classifier or judge prompt (`tailoring.fact_pool` precedent); the takedown command
  leaves an `AuditEvent` and never selects a student field.
- **Live gates, `-m live`:** (a) the ladder on ten real programme pages across five countries with
  a handful of synthetic anchors — the rung reached and whether a verified match landed; (b) the
  Jev gate (D6) on the labelled EN/DE/TR set against the frontier majority.

## 9. Deliberately not built, with the trigger that reopens each

- **DOI attachment and OpenAlex author lookup.** A DOI printed in a found sentence is not resolved
  yet; naming a professor to OpenAlex by name is never done (the wrong-person path). Trigger: the
  live ladder gate shows page-printed DOIs are common enough to be worth `publication.py`'s call.
- **Promotion of found sentences to the shared catalog.** Trigger: recorded outcomes show the same
  (programme, sentence) matched for many students at many tenants — then a catalog-side job, under
  the ingestion role, promotes them; the request path still never writes shared rows.
- **Cross-student duplication within a tenant.** Two students at one agency naming the same chair
  is true for both; identical *sentences* are a detectability risk. Trigger: an agency submits more
  than a handful of letters to one programme per cycle — then a per-tenant, per-programme variation
  check joins the gates.
- **Exa highlights, deep modes, `category`; zero-data-retention.** Not needed at three fetches and
  profile-free queries (D3).
- **Jev in the letter gates** (`check_generic_paragraph` as a Score). Trigger: Jev passes D6's gate.
- **A producer for home-country context facts** (DAAD A10's `SOURCED` use). Until it exists those
  claims carry `source_unverified` for the counselor. Trigger: the first DAAD-class letter generated
  for a real student.
- **Inferring funding, culture or openness from proximity to a group.** `phased requirements.md` §2
  forbids the first by name; the others are the honest residual the Goal states.
- **Contacting the professor.** Never (N-19).
- **Research fit as a discovery signal** (owner decision 6): its own design, fed by D7's outcomes.

## 10. Adjacent gaps this design does not close — named so they are not mistaken for closed

Found by the 2026-09-22 audit of the letter engine against its spec and plan; each is outside this
scope and each matters more to letter quality than this feature does:

1. **No funder prompt data.** `apps/funding/letter_prompt_fixtures.py` is one commented-out example;
   the ~25 researched funders were never loaded, so every letter resolves to inferred defaults.
2. **`letter_required = not_requested` is not enforced.** The spec blocks generating an unrequested
   letter; nothing does. Helsinki and Oxford discard unrequested documents.
3. **`resolve_ai_use_policy` keys on the funder alone**, against the spec's `(programme,
   structure)`; Cambridge prohibits AI for statements and permits it for research proposals.
4. **No production caller.** Wiring one is the gate to any of this reaching a student, and turns
   gaps 1–2 above into live defects on day one.
5. **`Program.discipline` (ISCED-F) is absent** — the engine design's named prerequisite — so
   `cluster_key` takes discipline from its caller and cluster identity depends on what a caller
   invents.
6. **The `font` constraint has no checker**, and `letter_render` fails closed on it: a `font`
   BINDING rule blocks a letter permanently rather than validating it.

## 11. Owed before the plan is written

- **The Exa adapter** — planned as Task 6 of `2026-09-18-organisation-register-and-provider-protocol.md`
  (branch `claude/program-page-reader`), built nowhere. Research fit is its first caller, or ships a minimal `providers/exa.py` behind the
  same protocol so discovery inherits it.
- **Legal filing.** `docs/legal/` does not exist; the roster already owes the Exa and Brave
  permission letters. Add Jev's MCA, privacy policy and DPA (read 2026-09-22), and the date, before
  any real student text goes through it.
- **The spike** (§8, live gates a and b): ~10 programme pages × a handful of synthetic anchors for
  the ladder; the EN/DE/TR labelled set for Jev. Both numbers size the plan — if rung 4 carries most
  matches, the ladder is mostly the theme; if Jev fails, the frontier path is the plan.
- **A fetch-side cost bound (D15, amended 2026-09-23).** Master's vendor-fetch redesign deleted the
  local egress client `pages.py::fetch_page` used to call and the merge into this branch switched it
  to `retrieve_official_source`, the Firecrawl/scrape.do vendor path. Every research-fit page fetch
  is now a billable vendor credit, and `RESEARCH_FIT_DAILY_CEILING_USD` meters vendor search spend
  only — fetch spend is currently unmetered, up to roughly `2 anchors × domains × 2 queries × 3
  pages` per `propose_research_fit` call, bounded only by the per-student 20/hour call limiter (a
  count, not a dollar figure). Whoever writes the plan must choose one of: threading a `SweepBudget`
  through `retrieve_official_source` from `pages.py`, or folding the vendor's returned fetch cost
  into `spend_within_ceiling`. Not chosen here — see D15.

## 12. Measuring the letter, not only this paragraph

Nothing measures whether the engine's letters are good, and no admission outcome exists anywhere
in the system to measure against. Two measurements, neither a research pass (the rules are
catalogued; a 2026-09-11 pass re-derived what was already in the catalog):

1. **A rubric judge as a live gate** — engine letters scored against each reader's own published
   criteria (Chevening's reading-committee feedback, DAAD, TUM, LSE's "what does not work"), the
   CV-format eval pattern. Research fit's contribution is one rubric line: *specificity of why this
   programme* before and after.
2. **A blind counselor panel** at the first agency tenant — engine letters and human ones, which is
   which and which is better. The only ground truth available before outcomes exist.
