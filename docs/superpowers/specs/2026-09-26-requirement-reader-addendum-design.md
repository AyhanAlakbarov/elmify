# Requirement reader — addendum to the typed-decisions design, from the first live measurement

Design, 2026-09-26. Amends `2026-09-22-typed-decisions-and-multilingual-sources-design.md` ("the
design") and its plans `2026-09-23-decision-layer-and-rule-grammar.md` ("plan 1") and
`2026-09-23-reader-and-multilingual-layer.md` ("plan 2"). Plan 3 (site jobs and the funnel) is
already on master (PR #133) and is amended only where §4 says so.

**Owner decisions, 2026-09-25/26.**
- This session takes over plans 1 and 2 from the session that claimed them on 2026-09-22 and
  committed nothing. Refine the design wherever the measurement shows a gap.
- **Jev is reached through OpenRouter** while TypeSafe's own sign-ups are paused.
- **Rules are stored per page and merged in code** (§3).
- The engine must be **general, never rules for a particular university**. The measurement corpus
  measures the engine and never becomes an input to it (§8).
- Cost is optimised for the best result, and CV and letter requirements come from **one run** over
  a page.

Everything the design says stands unless a section below changes it.

## 1. What was measured, 2026-09-25/26

The design was written before any letter rule had been read from a real page. These are the first
measurements, all on real pages. They exist only on branches `claude/letter-gap-fixes` and
`claude/judge-schema-fix`, not on master.

**The 77-sentence letter eval** (`docs/research/letter-shape-eval.csv`, the judge handed each
sentence, three readings) had never completed. It crashed on every "states no rule" row, and
Claude's reading was cut off at 21,000 output tokens when a whole language went in one call. Run
in page-sized batches, with scoring that counts only real contradictions:
- **English: 51 of 58 typeable rules asserted, and no wrong cap.**
- German, Spanish and Portuguese: all asserted.
- **What was missed was structural, not a misreading:**
  - every floor and range lost its floor, because a verdict holds one length;
  - three French sentences never became candidates, because the vocabulary does not know
    "projet professionnel";
  - one label disagreement: a form that pre-prints a salutation.

**The 30-page answer key** (`docs/research/letter-page-corpus.csv`, on `claude/letter-gap-fixes`)
covers 30 real programme pages in five languages and four PDFs. Each rule was quoted verbatim from
the live page, and a held-out third was assigned before any result was seen. Only 13 pages were
actually measured, because Anthropic credit ran out mid-run. Of those 13, 6 were fully right and
none got a wrong value.

**Defects found by that run**, all general:
- **Anthropic refused the judge's answer format** ("Schema is too complex", HTTP 400). Every page
  read crashed once a key existed. *Fixed* on `claude/judge-schema-fix`.
- **Every PDF read as empty.** Firecrawl returns its HTML rendering under the label
  `application/pdf`, and the reader handed that to pypdf. *Fixed.*
- **Limits written as words or as "1 000" were dropped as unverified**: "approximately one A4 page",
  "maximal zwei DIN-A4-Seiten", "une ou deux pages", "1 000 mots". *Fixed* by
  `letter_terms.numbers_on_line`.
- One model error, including a credit-exhausted 400, aborts the whole page read.
- A NUL byte in page text crashes the database write (Universidad de Chile).
- **Real short pages are rejected as shells.** HKU's page has 597 readable characters and ASBU's
  709, which falls under the 1,500-character floor at 20 KB or more.
- **Link rot:** 3 of 12 catalogue URLs verified a week earlier now return 404, and UPF returns 404
  to the engine.
- **The rule was two links away** (EPFL), and the programme page states nothing.
- **A page's `<html lang>` overrides its text.** UvA's English page declares `nl`.
- **Cost:** each Claude reading writes about 20 letter fields for every candidate line, including
  CV-only lines. That is up to 3 minutes and 21,000 tokens per reading, and about 10 minutes of
  wall time per page.

The review of plans 1 and 2 against today's code (2026-09-26) found the gaps §2–§7 close, and the
stale references §9 lists.

## 2. The classifier: Jev through OpenRouter

**Why.**
- TypeSafe paused new sign-ups. Existing accounts keep working.
- OpenRouter serves `typesafe/jev-1.13` with TypeSafe as the provider, at $0.042 per million input
  tokens with free output and a 32k context. Its Jev guide says an OpenRouter key authenticates
  both the Decisions API and the TypeSafe SDK pointed at `https://openrouter.ai/api`, with no
  TypeSafe account.
- The adapter (`system-one-adapter`) needs no TypeSafe account either. But its probabilities are
  numbers the model writes into its answer, not logprobs, so they are not calibrated. It stays a
  measured fallback, never the default. Both facts were read from the packages' source at 0.2.1 /
  0.7.1 and from OpenRouter's API on 2026-09-26.

**What changes.**
- A setting `DECISIONS_BASE_URL` (default `https://openrouter.ai/api`) and a key setting
  `OPENROUTER_API_KEY`. The SDK client is built with that base URL.
- `TYPESAFE_API_KEY` is used only when `DECISIONS_BASE_URL` is TypeSafe's own endpoint.
- The design's §3.3 contract terms are re-read for OpenRouter: its terms and data policy, with the
  provider's retention on top. What is sent is unchanged: public page sentences only, never
  student data. That is why this path needs no data processing agreement, as the design's §3.3
  already argued for Jev.
- Plan 1's `DecisionsUnavailable` path stays. With no key the reader falls back to the current
  frontier judge rather than stopping (§5.1).

**Pinned** `typesafe/jev-1.13` through `TYPESAFE_MODEL`, never an alias. The model version is
written on every `DecisionRecord`, as plan 1 already does.

**The owner's action:** create an OpenRouter account and key, and save it as
`~/.config/tehsil_agent/openrouter.env` (`OPENROUTER_API_KEY=`, mode 600). Nothing in the build
waits on it except the live gates.

## 3. Rules are stored per page and merged in code

**The defect this closes.** Plan 1 Task 10 rewrites a programme's `cv_constraints`, `cv_directives`
and letter fields from one page, and plan 2 Task 9 deletes all of a programme's statements on every
read. With the funnel reading several pages per programme, the page read last wins:
- a later empty page wipes rules another page gave;
- a monitor re-reading one page wipes the others' rules;
- a university-wide page lands at programme rank, contradicting
  `2026-09-17-cv-rule-discovery-design.md` §1, which puts it at the institution tier.

**The store.** A new model, `research.PageRequirement`, is written by the grammar's projection:
- one row per rule, per `(OfficialSource, admissions_cycle)`;
- fields: document, operation, value, scope, the verbatim sentence, the decision probabilities,
  the snapshot it was read from, and a **tier**.

It is catalogue data, built by CLAUDE.md's recipe for a new catalogue table (2026-09-25):
- `shared_catalog_select` for reads;
- `runtime_engine_write` for the worker, its only writer;
- `REVOKE ALL ... FROM runtime_web` in the same migration, so the web tier holds no grant;
- `tests/tenancy/test_catalog_grants.py` fails until the revoke lands.

The merge (below) runs in the worker for the same reason.

**Re-reading one page replaces that page's rows and nothing else.**
- A fetch that did not serve (`BLOCKED`, `UNREACHABLE`, `UNREADABLE`, `OFF_SITE`, quarantined)
  keeps them.
- A page that served and states nothing removes its own rows, which is the design's §5.3 rule,
  now per page.

**The tier** comes from a D3 question already on the page: which scope does it cover? The options
are `this_programme`, `faculty_or_school`, `whole_university` and `several_named_programmes`, and
code adds `programme_document` when the page is a file linked from the programme's own page. A
`whole_university` page is attached to the `Institution`, read once, and inherited by every
programme of it. This closes the per-programme re-reading of shared pages.

**The merge**, `requirements.effective_rules(program, cycle)`, is pure code, runs after every read
of any contributing page, and writes the existing sinks: `Program.cv_constraints`, `cv_directives`,
`ApplicationPrompt.letter_*`.
- Each rule key has a source row, and `letter_shape_sources` keeps per-field provenance.
- **The most specific tier wins per key.** The order is `this_programme` >
  `programme_document` > `several_named_programmes` (only when the programme is among them) >
  `faculty_or_school` > `whole_university`.
- **At the same tier the safer side wins:** the smaller cap, the larger floor, `required` over
  `unstated`. Every same-tier conflict writes a note on the document, as the design's §6.4
  requires.
- The existing enforcement guard stays: a derived rule never lowers a `BINDING` one.

**Precedence is by specificity, not by recency.** A general page read yesterday never overrides a
programme page read last month.

## 4. Where the rules are: pages, links and PDFs

The funnel (plan 3, on master) already finds and ranks a programme's pages. The additions:
- **Wire the reader to the funnel's pages.** `read_program_page` accepts only `PROGRAM` source
  rows today, and the funnel's "wire `read` to the real reader" step has no design. The reader
  accepts any source the funnel attached to the programme, with its tier (§3).
- **Stop on sufficiency, not on the first hit.** A programme is read until both documents have an
  answer (a rule, or a page-level `not_required`) at `this_programme` or `programme_document`
  tier, or until the funnel's budget is spent. EPFL's rule, two links from the programme page, is
  reached this way.
- **PDFs, and files linked from the programme page** (guideline PDFs, checklists, templates) are
  `programme_document` tier. The CV-rule discovery design's §4 measured that rules live in them.
  A ZIP stays unread and noted, as it is today.
- **A dead URL is not a silent ledger row.** A source that returns `DEAD` on two consecutive rounds
  is re-discovered from the programme's landing page and the site map. Its rows are retired with a
  note, never kept as current.

## 5. Robustness, independent of which classifier runs

1. **One failed request is not a failed page.**
   - A decision request that fails (transport error, 5xx, 429, billing 400) marks that page's read
     `decision_failed`. The page's previous rows stand, and the page joins the existing retry
     queue (`FetchAttempt` with `retry_after`). The retry must hand what it re-reads to the
     reader and the merge (§3). `retry_due_fetches` does not do that today: a successful retry
     persists no snapshot and re-runs no reader, which is why its schedule stays `DISABLED`
     (CLAUDE.md, "Erasure"). This design supplies the missing hand-off for pages it owns. Until
     the schedule is enabled, a `decision_failed` page is re-read on the next operator run, and the
     page's previous rows keep serving.
   - A model that is refusing, as opposed to failing, is recorded as a refusal. It is not retried.
   - With no decision provider configured at all, the current frontier judge runs, so a missing
     key degrades cost, not correctness.
2. **Control characters are stripped** at `readable_text`, NUL included, before anything is stored
   or sent.
3. **The shell floor gives way to a question.** A page the vendor already rendered (Firecrawl
   renders JavaScript) and that has any sentence is read. D1's question "is the main content
   missing?" decides a shell, and D1 may now *rescue* a page the byte-count rule would have refused,
   not only refuse one. This reverses the design's §4 "never rescues" for this one question,
   because the byte-count rule was measured wrong on real pages.
4. **Language comes from the text.** Each sentence's language is detected from its own text (the
   design's §8.2 already puts language on every statement). `<html lang>` breaks ties only. A
   bilingual page is read in both languages.

## 6. The grammar, amended

1. **Every figure is its own decision.**
   - Code finds each figure in a requirement sentence with its unit: `numbers_on_line`, extended to
     return the unit beside each number, reused rather than plan 1's separate `numbers_in`.
   - Per figure, a Choice asks for its bound: `maximum`, `minimum`, `approximate`, `not_a_limit`.
   - For a character figure, a Noul asks *does the count include spaces?*
   - So "300–500 words" is a floor and a cap, never the floor as the cap, and "3,500 characters
     (approximately 500 words)" is two caps.
   - Plan 1 Task 7's `min()` resolution of a range is removed.
2. **Floors keep a sink.** `min_words` stays, and `min_chars` is added to `ApplicationPrompt` and
   `LetterShape`. Kassel rejects a letter under 2,800 characters, and a stated floor below which
   the application is rejected is a binding fact.
3. **Nothing typed is lost** (restoring the design's §6 promise, which plan 1 broke).
   - Plan 1 Task 10 may not delete `_form_decision`, `_naming_decision` or
     `_document_required_decision`, or the track and portfolio decisions, until the grammar has an
     operation that writes each of `form`, `naming`, `document_required`, `track` and
     `portfolio_led`.
   - The operation list gains `form` and `naming`. `document_required` comes from the page-level
     Noul the design's D4 already asks for the CV, extended to the letter.
4. **The letter's language** (`language` operation) writes `ApplicationPrompt.document_language`.
   Plan 1 Task 9 passes it into `LetterShape`, which has no such field and would raise.
5. **Recorded as notes, not yet enforced:**
   - **tolerances** ("an exceedance of more than 10 percent");
   - **per-section caps** (three parts of 400 words each);
   - **a second statement in the same application** (a 250-word statement beside a 500-word one).

   Each goes into `letter_written_requirements` as a topic with its sentence, so the letter writer
   reads it and the document carries it. Enforcing them needs sinks the renderer does not have. See
   §10.
6. **Scope, two additions.**
   - On a page whose D3 scope is `several_named_programmes`, a Choice over the programme and degree
     names code found on the page asks *which programme does this sentence apply to?* A rule for
     another programme is dropped. AUC's doctoral floor then never binds its master's.
   - A condition's value is kept beside its kind (citizens only, EU only). A conditional rule binds
     no student until the student's own facts are compared to it, and until then it is a note.

## 7. Cost

Per programme page, through Jev on OpenRouter:

| item | today (frontier judge) | this design |
|---|---|---|
| statement read | 3 generative reads | D4 + D5 classification |
| rule judgement | 3 readings (2 OpenAI + Claude), about 20 fields per line, retries | D6 per requirement sentence, a few Choices per figure |
| a shared university page | read once per programme | read once per university (§3) |
| an unchanged page | cache hit | cache hit (`DecisionRecord`, and the `content_sha256` check) |

The design's figure of about $0.001 per page assumed Jev's price, which OpenRouter lists unchanged.
**It is measured, not assumed.** The live gates record the input tokens and requests per page, and
a page costing more than 3× the estimate fails the gate.

## 8. Measurement

- **The two corpora become one instrument.** `letter-page-corpus.csv` (30 pages, a held-out split
  assigned before any result, a guard test that fails if any module on the read path names a corpus
  university) joins the labelled corpus of `2026-09-23-labelled-corpus-design.md` as its first
  page-layer rows.
- **The corpus gains a programme layer:** the *merged* rules each programme should end up with
  across its pages. Without it the merge (§3) cannot be scored.
- **Ship gates, in addition to the design's §11:**
  - on the page corpus, every length exact on ≥ 90% of dev pages and ≥ 85% of held-out pages;
  - no wrong value set on any page, since a wrong cap ships a rejected letter;
  - the required-or-not answer right on every page;
  - each gate reported per language and per stratum.
- **The held-out split is scored only when a part is declared finished**, as the CV corpus does. A
  fix that moves the dev score and not the held-out one is a fix for the pages we looked at.
- **Every live runner prints each row as it finishes** and runs sharded, one test database per
  shard. The first full run lost its table to a timeout.

## 9. Corrections to plans 1 and 2, before Task 1

Measured against `origin/master` at `134b176`, 2026-09-26:

- **Base branch:** `origin/master` at execution time, not `claude/fetch-spec-refresh`. The stale
  base check runs again at the start of each task.
- **Migrations:** research is at `0009`, so the decision layer's migration is `0010`. Funding is at
  `0049`, so plan 2's `0047` becomes `0050` or later. Re-read the tip before writing each one.
- **Plan 2 Task 9's pasted code uses `snapshot.unreadable` and `content_digest`.** Master uses
  `readability` (`SHELL`, `SOFT_404`, `UNPARSEABLE`), `change_digest` and `archive_marker`. Pasted
  as written, it would lose soft-404 and PDF detection. It is rewritten against the current
  functions.
- **Plan 1 Task 6's `numbers_in` is replaced** by `letter_terms.numbers_on_line` (§6.1).
- **Plan 2 Task 1's size handling** keeps trimming to sections matching `_ADMISSION_TERMS` above
  24k, and that list has no letter words. Enumeration and D4 run over the whole page in chunks;
  trimming, if any, happens only after D4 has picked.
- **Line references move.** Every `file:line` in both plans is re-resolved at the task that uses
  it, never trusted.
- **The fixes from `claude/judge-schema-fix` land first**: the Anthropic schema, PDF bodies and
  numbers written as words. The frontier judge is the fallback (§5.1), so its fixes still matter.
- **Interfaces other plans consume do not change.** The award-card plan (build item 13, Part B)
  consumes `decisions.ask` and D4/D5 unchanged. This addendum adds questions and a store; it
  renames nothing either plan exports.

## 10. Deliberately not built, with the trigger

| not built | trigger |
|---|---|
| enforcing tolerances and per-section caps | a programme in a student's pack states one, and the renderer grows a per-section check |
| several statements per application as separate documents | the letter engine writes more than one document per programme |
| matching a conditional rule to the student's own facts | the pack reaches a programme whose only letter rule is conditional |
| detecting a stale intake-year page | the corpus measures how often a page names a past intake (design §14) |
| rules visible only inside an applicant portal | recorded as "unknown", never "none"; the glass-box extension reading the portal is the path |
| Jev directly from TypeSafe | sign-ups reopen; `DECISIONS_BASE_URL` changes, and nothing else does |

## 11. Execution order

1. Land `claude/judge-schema-fix` on master (the three fixes).
2. Plan 1 as amended: §2, §6, §9. Its ship gate is the design's §11.1 plus §8 here.
3. Plan 2 as amended: §5, §9.
4. Plan 3's unbuilt remainder: `triage.py` with D1, D2, D3 and D8. The funnel merged in PR #133
   without it, and §3's tier and §5.3's shell rescue are D3 and D1 questions.
5. §3's store and merge, then §4's wiring to the funnel. Both are new tasks, written into a short
   plan 4 once plans 1–3 are in, because they build on all three.
6. The full corpus run, dev split first, then the held-out split.
