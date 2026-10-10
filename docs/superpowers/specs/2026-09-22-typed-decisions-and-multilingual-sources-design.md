# Typed decisions and multilingual sources — one classifier, every language, no word lists

Design, 2026-09-22. Owner decisions the same day: **Jev (TypeSafe AI's System One model) does all
classification** — page triage, sentence selection, statement labelling and the CV-format judge —
and the frontier models keep only the work that must produce words (translation, image
transcription, `/agent` navigation); **all fourteen target languages at once**, with helper
vocabularies drafted by a model, frozen, and reviewed as native speakers become available; **social
platforms are the opportunity-discovery session's**, not this design's; and **a person sees an
English translation with the original sentence and its link beside it** for verification.

Builds on `2026-09-22-fetch-engine-design.md` (the engine that produces the pages this design
reads) and supersedes the *mechanism* of `2026-09-13-format-decision-guarantee-design.md` — three
phrasings, three samples, a second model family, unanimity, one retry — while keeping every
guarantee that spec measured for. Every statement about Jev below was read from
`docs.typesafe.ai` (the API reference, the three primitives, the patterns, the `jev-1.13`
failure-mode page, the SDK, fourteen cookbooks), the launch post of 2026-09-15, the Master Customer
Agreement and the Data Processing Addendum, on 2026-09-22. Re-read them before executing any plan
built on this document: the product is a week old.

> **Amended 2026-09-23** after the owner's review. Decisions taken that day: **no person in the
> pipeline** — nothing waits on a human; every unsure, conflicting, conditional, unapplied or
> quarantined reading becomes a note on the document it would have shaped, seen by the counsellor
> at the document review that already exists (§5.4, §6.4); **the motivation letter's requirements
> are in scope** beside the CV's (§2, §6.1); **a mistaken Europass render is acceptable** to the
> owner, so the format action takes the ordinary bar (§6.2, §14); **every rule is typed through one
> grammar seeded from the catalogs**, and a rule of a kind the grammar cannot hold is recorded and
> counted, never improvised (§6.1, §6.5); **ambiguity is detected and typed** (§6.3); **the
> classifier for any decision is chosen by measurement** through the adapter, Jev being the
> default (§3.2, §11). Package-source and availability facts were verified the same day (§3.2, §14).

## 1. Why this exists

Three things were measured on 2026-09-22 and one had been measured for a fortnight.

- **Three English word lists decide what the pipeline sees.** `_ADMISSION_TERMS`
  (`apps/research/reader.py:128`) decides which sections of a page reach the model;
  `FUNDING_PATH_TERMS` (`apps/research/search.py:140`) decides which links a crawl follows;
  `_CV_TERMS` (`apps/documents/derive.py:65`) decides which sentences reach the judge. Together they
  know one German word. A Kazakh ministry's page matches none of them: the reader falls back to
  the whole page (safe, expensive), but the crawl never follows `/stipendii/` at all, silently.
  No list in fourteen languages closes that — addresses are numbers, slugs and transliterations —
  which is why the answer is to stop deciding with words.
- **The reader's selection has never been stable.** Three generative reads unioned, and still 47 /
  42 / 48 statements from the same page; three designs failed set equality (CLAUDE.md). The cause
  is structural: a model asked to *quote* chooses a different subset of true sentences every time.
  A model asked to *classify each sentence* cannot.
- **The judge costs three frontier calls per candidate page** and stands in for a confidence it
  cannot get: "nine readings agree" is a workaround for models that do not give an honest
  probability when asked.
- **The quote check drops true quotes in some scripts.** `reader.normalize` collapses whitespace
  and case and nothing else; Uzbek's five interchangeable apostrophes, and any page in NFD, fail
  it and are recorded as fabricated.
- **The scripts themselves are fine.** Measured 2026-09-22: Claude Sonnet 5 read Azerbaijani,
  Kazakh in both alphabets, Kyrgyz, Turkmen, Mongolian, Chinese, Korean, Russian, Georgian and
  Armenian at 98–100% of characters; OpenAI matched except on the new Kazakh Latin; Firecrawl's
  OCR Russifies Kazakh Cyrillic and cannot read Georgian. Reading is not the problem. Deciding is.

## 2. Scope and non-scope

**In:** the typed-decision layer and every decision it takes (§4); the reader rebuilt around
selection instead of generation (§5); the judge rebuilt as classification, and the rule grammar for the CV and the motivation letter (§6); the crawl gate
rebuilt without words (§7); the multilingual layer — vocabularies as additive data, language on
every statement, script-safe quote verification, English translation for people, images (§8).

**Out, and whose it is:** social platforms and search-engine query strategy (the opportunity-
discovery session); deadlines and amounts (the discovery design's §4.10 card — Jev's own docs say
dates are extracted as parts and compared in code, and that is a separate pattern); Arabic-script
and right-to-left languages and vertical CJK (untested; §14); the student chatbot's language; the
letter engine's *writing* — its requirements are In since 2026-09-23 (§6.1); how it writes is unchanged.

## 3. The typed-decision layer

### 3.1 What Jev is, from its documentation

`POST https://api.typesafe.ai/v1/systemone` takes a `state` — a string or JSON — and a map of typed
`questions`, evaluates every question **independently and in parallel** against the same state, and
returns one typed answer per question. Three question types:

| type | asks | returns |
|---|---|---|
| **Noul** | is this true? | `noul`: P(yes), 0–1 |
| **Choice** | which of these ≤ 255 options? | `choice`, `probabilities` over the options, `confidence` |
| **Score** | which of these 2–10 ordered levels? | `score`, `probabilities`, `confidence` |

It does not generate text. Its extraction cookbooks work the way this repo's own rule works: code
finds the candidate spans (a regex, a sentence splitter, a list of IDs), Jev picks the one the
question asks for, code copies it verbatim — "it cannot invent a value or transpose a digit."
Limits: 64k tokens for `state` plus all questions, 32k for `state` plus the longest question.
Price: $0.042 per million input tokens, output free. Latency 70–500 ms. Rate limits are "adjusting
dynamically"; 429/529 back off with `retry-after`. Aliases (`jev-latest`) move between versions;
the response's `model` field names the version that answered, and **a tuned threshold is pinned
to a versioned ID** (`jev-1.13.0` today) and moved on our schedule.

Their `jev-1.13` failure-mode page binds every question written here:

1. **Literal reading.** It answers the question written, not the one meant. Every question below
   states its exact condition; boundary cases go in `criteria`, with `what`, `not_for` and
   `examples` fields.
2. **No arithmetic, counting or date comparison.** Code does those. A page limit is *picked* from
   the numbers a regex found in the sentence, never computed.
3. **Indirection costs accuracy.** One judgment per question; questions point at a named part of a
   structured state.
4. **Irrelevant state costs accuracy.** Sentences and short contexts are sent, never whole pages;
   §5 chunks at 200 sentences.
5. **Adversarial content can steer it.** Page text is untrusted (CLAUDE.md, LLM/AI security). §9
   says what that means without a second model.
6. **Contradictory instructions and criteria confuse it.** `true` means yes; no negated questions.
7. **Structural invariants are not guaranteed.** A Noul and a yes/no Choice on the same question
   differ; thresholds are tuned per question and never carried across.
8. **English is the primary training language; others "are handled but not equally well; test on
   your own content."** §11 measures per language before any non-English decision is trusted.

### 3.1a How a question is written — the vendor's rules, kept in code (2026-09-23)

Jev has no prompt; it has a state and typed questions, so "prompt engineering" is question
engineering and the levers are the vendor's, read from their pages on 2026-09-23 and recorded with
their sources in `docs/superpowers/research/2026-09-23-jev-question-engineering.md`. The rules the
code follows:

- **One judgment per question.** No `and` inside a Noul; split and combine in code.
- **Point at the state by name.** `instructions` is an object — `{"question", "inspect", "focus",
  "note"}` — and `inspect` carries a backtick path into the state (`` `sentences[3]` ``). Prose
  indirection ("for the sentence with id 3") is a documented failure mode.
- **The state is an object with named parts; instructions stay out of it.** Irrelevant state is a
  distractor, so a request carries the sentences a decision is about and nothing else.
- **A Choice's options are its criteria keys**, each described so it separates from its
  neighbours, with `{what, not_for, examples}` where two are confusable, and an `other` / `none`
  option whenever the list may not cover the input.
- **A Noul is phrased so that a high value means yes**, has one condition, and gets `{true, false}`
  criteria only when a real sentence showed it needed them.
- **Choice is relative, Noul is absolute.** A Choice's probabilities sum to 1 across its options,
  so "which sentence states…?" answers *which one* and cannot select *all that do* — that needs one
  Noul per sentence. Thresholds never transfer between the two.
- **Code counts, computes and finds candidates; Jev picks; code copies verbatim.** `none` is
  always offered; a value assembled from parts routes on the lowest confidence among them.
- **Ask everything in one request.** Questions run in parallel; speculative questions cost tokens
  and no call.
- **Thresholds follow the cost of the error.** Recall-critical selection sits low (0.3–0.5);
  actions that cost sit at 0.85 or above; the vendor's own routing pattern and classification
  cookbook use 0.85 and 0.9.
- **Repeats are stable (σ ≈ 0.01 over fifteen); wording is the variance.** Redundancy is three
  *wordings*, never three repeats, and §11 gate 6 measures rewording stability.
- **A quote is verified by code before any question is asked** — the vendor's citation cookbook
  does exactly what `verified_statements` did.

### 3.2 The contract with the codebase

- **Questions live in named question modules, never at a call site.** Their own guidance is "put
  the constants in a single place so they're easy to review", and the reviewable unit is the
  module, not the repository: `apps/research/decisions.py` owns the primitives, the client, the
  provider routing and the thresholds it can express; each decision's questions live in one module
  named for it (`apps/documents/grammar_questions.py`, `grammar_values.py`, `apps/research/triage.py`).
  **Amended 2026-09-23:** a single file is not reachable, and the reason is structural rather than a
  preference — `apps.documents` imports `apps.research` and never the reverse
  (`apps/documents/program_rules.py` states the rule), so a question whose options are
  `constraints._INCLUDE_TARGETS` cannot be built inside `apps.research`. What the rule protects is
  that no question is assembled inline where it is asked, and that every threshold sits beside the
  question it gates; both hold per module.
- **One client:** `typesafe-sdk`'s `system_one(state, questions)` when `TYPESAFE_API_KEY` is set;
  otherwise TypeSafe's own `system-one-adapter`, a client-side drop-in for the same call that answers
  the *same* questions through Anthropic, OpenAI or Gemini (each call names `provider=` and
  `model=`; `llm_answer_mode="probabilities"`). The adapter is the fallback if TypeSafe is unavailable
  and the instrument for every like-for-like measurement in §11. No question is ever written
  against a provider.
- **Settings:** `TYPESAFE_API_KEY` (env only), `TYPESAFE_MODEL` (default the pinned versioned ID —
  `jev-1.13.0` as of 2026-09-23; `jev-latest` is an alias that moves, and their docs say to pin the
  version once thresholds are tuned), `TYPESAFE_BASE_URL` (default `https://api.typesafe.ai`;
  `https://openrouter.ai/api` reaches the same model as `typesafe/jev-1.13` at the same price
  through OpenRouter's native decisions route — the SDK appends `/v1/systemone`; chat-completions
  clients cannot call it), `DECISIONS_PROVIDER` ∈ `typesafe | adapter:anthropic | adapter:openai`.
- **Provider per decision, by measurement (amended 2026-09-23).** `DECISIONS_PROVIDER` is a
  mapping from decision ID, optionally per language, to `typesafe | adapter:anthropic |
  adapter:openai`, with one default. Jev is the default for every classification — cheapest, a
  probability on every answer, cannot generate — and §11 gate 9 is the referee: where the adapter
  scores higher on a decision in a language, it takes that decision there, as a measured exception
  the owner sees. Adding an LLM to a decision is therefore a setting, never a redesign; the
  owner's rule that no frontier model classifies is the default, not a ban on the measurement.
- **Every decision is logged** with its probabilities, confidence, the versioned model, the
  question ID and the sentence or page it judged, so a threshold can be re-tuned from history and
  a calibration curve drawn from production.
- **Package source — verified 2026-09-23, superseding the 2026-09-22 custom-index claim.** Both
  packages are on public PyPI under the author "TypeSafe AI", published from the vendor's `typesafe-ai`
  GitHub org: `typesafe-sdk` 0.7.1 (2026-09-21; deps `httpx2`, `pydantic`, `tenacity`) and
  `system-one-adapter` 0.2.1 (2026-09-22; MIT; extras `[anthropic]`, `[openai]`, `[gemini]`;
  depends on `typesafe-sdk>=0.7.0`). `pypi.typesafe.ai` answers 404 and no vendor page names it. Under
  `engineering.md`'s source gate these are *confirmed* sources: ordinary pinning and vulnerability
  checks, no approval round. Two namesakes to avoid: `typesafe` (2010, unrelated) and `typesafe-ai`
  (a third-party shim).

### 3.3 Contract terms, read 2026-09-22

Master Customer Agreement: no training on Customer Data without consent; we may not distil,
imitate or build a competing model from Output; we are responsible for Input (public page text,
the same standing it has when sent to OpenAI or Anthropic today); Output may be inaccurate and we
evaluate it — which §9 does. Data Processing Addendum: controller/processor, EU Standard
Contractual Clauses Module 2, subprocessors listed at `trust.typesafe.ai`. No clause naming
education or admissions as high-risk, unlike Anthropic's usage policy and Tavily §3.2(xvi). One
courtesy: §16.4 lets them name us as a customer unless asked not to.

**The clauses are on file, and so is the standing.** `docs/legal/2026-09-provider-terms.md` carries
the TypeSafe entry quoted from the MCA, the privacy policy and the DPA — that file is the record,
this section is the summary, and where they differ the file wins. Its **status line binds this
design**: *candidate only; no real student text reaches Jev until the DPA is countersigned or
accepted through the account and the sub-processor list has been read once; the live gate uses
synthetic anchors.*

Every decision in §4 sends **public page text** — a programme page's own sentences, a site map's
URLs — which is the standing that text already has when it goes to OpenAI or Anthropic today, so
the status line does not block D1 through D6 or D8. It blocks exactly one thing: the research-fit
classifier on master (`apps/documents/research_fit/jev.py`), whose state is a page fetched for one
student's topic. That one stays behind `DECISIONS_PROVIDER` and the gate until the DPA is accepted,
and no key exists on any machine here yet, so nothing has been sent.

## 4. Where decisions are made

Every row is one request. Thresholds are the starting values; §11's calibration measurement sets
the shipped ones. "Below" always means: the decision is not taken, the item is recorded with its
probabilities, and it goes where the last column says.

| # | decision | state | questions | act at | below |
|---|---|---|---|---|---|
| D1 | **fetch outcome** — is this page really a page? | first 4,000 characters of markdown + URL | Nouls: *is this a "not found" or error page?*; *is this an anti-bot challenge or interstitial?*; *is this a region or language selector rather than content?*; *is the main content missing (a shell)?* Choice: *language of the text* over the fourteen + `other` | any Noul ≥ 0.8 → the engine's `DEAD` / `BLOCKED` / `UNREADABLE` outcome with reason `judged:<question>` | the engine's own byte-count and marker rules stand; Jev only *adds* a refusal, never rescues a page |
| D2 | **site-map ranking** — which addresses to fetch | the first 255 `{id, path, title}` of `/map`'s result after the additive URL-term rank, and the programme's landing URL | Choice over the IDs: *which page most likely states the documents an applicant must submit?* (top-25 by probability); Noul: *does the list contain such a page at all?* | the top 25 by probability are crawled first | Noul < 0.3 → proximity crawl alone (§7) |
| D3 | **crawl triage** — which fetched pages deserve reading | one page's sentences (§5.1), URL, title | Nouls: *states application-document requirements?*; *mentions a CV, résumé or curriculum vitae requirement?*; *is a news, event or staff page?*; Choice: page kind ∈ programme / how-to-apply / documents-list / funder-award / faq / other | documents ≥ 0.7 or CV ≥ 0.7 → D4 | 0.3–0.7 → D4 anyway (recall is the job; a false positive costs a D4 call, not $0.35); < 0.3 → skip, recorded |
| D4 | **sentence selection** — which sentences state requirements | the page's sentences as `{id, heading, text}` (≤ 200 per request; chunked) | **One Noul per sentence per kind, each pointed with `inspect`** (amended 2026-09-23 — a Choice over IDs is a *ranking*, its probabilities sum to 1 across the sentences, and a checklist with thirty requirement sentences gives each ~0.03; §3.1a): *does this sentence state a requirement about the applicant's CV or résumé?*; *…state which documents the applicant must submit?*; *…state a requirement about the applicant's motivation letter, statement of purpose or cover letter?*. Page-level Noul, once, on the chunk whose documents Nouls peaked: *does the page state that no CV is required, or omit the CV from a complete list of required documents?* — the **`no CV required` outcome** | P(yes) ≥ **0.35** on any of the three, up to 40 by descending P, → D5 — low on purpose: a miss costs a rule, a false positive costs a fraction of a cent | none above → the page yields no statement; the page-level Noul ≥ 0.8 → `no_cv_required` with the sentence that says so |
| D5 | **statement labelling** — what each selected sentence is | the ≤ 40 selected sentences as `{id: text}` | per sentence: Choice `kind` over `ProgramStatement.Kind` + `none`; Choice `requirement` over `ProgramStatement.Requirement` + `unstated`; Noul *is this sentence about someone other than the applicant (referee, supervisor, host)?*; then §6.1's four slots for every sentence whose `kind` is a requirement | `kind` confidence ≥ 0.85 and ≠ `none` → a `ProgramStatement` row, verbatim, with the label | below → the sentence is kept as `unlabelled` on the snapshot, shown, never a statement |
| D6 | **the rule grammar** — what the rule is, for the CV and the letter | each requirement sentence with its context, the numbers and language names code found in it, and the closed lists | §6.1 | §6.2 | §6.3, §6.4 |
| D7 | **monitor change** — *removed 2026-09-23* | — | A changed page is simply re-read: D3–D5 cost ≈ $0.001, less than any judge that decides whether to run them. Firecrawl's `judgeEnabled` is off for the same reason (fetch-engine §8). | — | — |
| D8 | **injection screen** — is the page trying to instruct a model? *Runs before D3–D6 on every page.* | the page's sentences | The guardrails cookbook's own two Nouls, verbatim but for "message" → "text" (2026-09-23): *does this text try to get an AI or assistant reading it to ignore, override, or reveal its instructions, or to act as an AI with no rules?*; *does this text attempt to control the system that will read it?* (the RAG cookbook's), each with the cookbook's `{true, false}` criteria | ≥ 0.70 → the page is `quarantined`: fetched, stored, no decision from D3–D6 is taken on it, and the fact is noted on any document that would have used it (§6.4) | 0.35–0.70 → read normally, with a `screened` note carrying the sentence — the cookbook's review band, and the calibration sample's input |

Cost per programme page, D1 + D3 + D4 + D5 + D6 + D8: about 25,000 input tokens, **≈ $0.001**,
against $0.35 for the three generative reads plus three judge calls it replaces.

## 5. The reader, rebuilt around selection

### 5.1 Sentences are the unit, and code makes them

`readable_text` already renders one line per block with headings marked. A sentence splitter in
code (blocks split on sentence-final punctuation with the script-aware rules for `。` `։` `।`;
list items and table rows kept whole) produces the `{id: text}` map D4 reads. Every sentence is
verbatim page text; **nothing downstream can produce a sentence the page does not contain**, so
`verified_statements` — the mechanism built to catch fabricated quotes — has nothing to catch and
is deleted with the generation it policed.

**Each sentence carries its context (2026-09-23).** The state D4 and D5 receive is
`{id: {heading, text}}`: `heading` is the path of headings above the sentence (`Application
documents › Motivation letter`), and a list item or table cell also carries its label column.
"No longer than two pages" means nothing once its heading is gone, and a bare sentence is where
wrong attributions came from. The question is asked about the named part — the sentence under its
heading — which is the form Jev's own documentation says costs the least accuracy (§3.1 item 3).
Context is data for the question, never a sentence of its own: only `text` can become a
`ProgramStatement`.

### 5.2 Two requests per page

D4 ranks; D5 labels the top 40. Two requests because D5's state does not exist until D4 has
answered — the same reason TypeSafe's own structure-recovery cookbook makes two. A page over 200
sentences is chunked for D4 and the chunks' selections merged; D5 always fits in one.

### 5.3 What a `ProgramStatement` becomes

A row is a verbatim sentence, its `kind`, its `requirement`, the D5 probabilities, the model
version, and (§8) its `language` and English translation. The `content_sha256` cache stays: a page
whose text has not changed is not re-read. `_READS = 3`, the union, `dropped_quotes`, the
last-occurrence-wins dedup and their tests go. The re-read of an unchanged page is now
byte-for-byte reproducible, which is what three designs tried to reach with generation.

**A read that finds no requirement sentence is a result, not a failure (2026-09-23).** With
selection, a `FETCHED` page on which D4 selects nothing yields an empty set and *replaces* the
programme's rows; only a fetch that did not serve — `BLOCKED`, `UNREACHABLE`, `UNREADABLE`,
`OFF_SITE`, `quarantined` — keeps the previous rows standing. This reverses the generative
reader's rule of keeping rows when a read verified no quotes: that rule existed because a
generative read could fail to quote, and a selection over enumerated sentences cannot, so its
silence is the page's. A rule that vanished from a page vanishes from the catalog on the next read.

### 5.4 Nothing waits for a person (owner decision 2026-09-23)

A page D3 admits but D4 finds nothing in, a sentence D5 cannot label at the bar, a `no CV
required` Noul between 0.3 and 0.8 — each is recorded with its probabilities and becomes a note
(§6.4) on whatever document the programme's rules would have shaped. The pipeline never creates
a task for a person and never waits on one; the document is produced with the safe default and
carries the note, and the counsellor's existing document review is where it is seen. No frontier
read is triggered by uncertainty either: classification is Jev's (§3.2), and a second classifier
would be the thing this design removes.

## 6. The judge, rebuilt as classification

The judge's job is a small set of closed questions about one sentence; §6.1's slots are those
questions. On master the judge already exists twice — `derive.py`'s CV questions and its
`LetterVerdict` (subject, length measure / bound / number, form, naming, signed declaration,
document required, track, font, spacing, margins, bundle, handwritten, and the three-way
`requirement_path` render / writer / student) — both answered by frontier readings and vote
counting. The grammar keeps every one of those fields as a value and replaces the readings with
Jev; nothing typed is lost (2026-09-23).

### 6.1 The rule grammar — four slots, closed lists, one free topic (amended 2026-09-23)

A requirement sentence is never read as a sentence. It is taken apart into four slots, each a
closed question with a probability, and a rule exists only when every slot fills at its bar. The
questions are the same for the CV and the letter; the lists differ per document.

| slot | question | answers |
|---|---|---|
| **document** | which document is this about? | Choice: `cv`, `motivation_letter`, `reference_letter`, `other` |
| **operation** | what does it ask for? | Choice: `limit`, `language`, `format`, `include`, `order`, `emphasise`, `style`, `topic`, `student_action`, `other` |
| **value** | which value? | typed per operation, below |
| **scope** | whom does it bind? | Noul *is the document this sentence describes someone else's — a referee's, supervisor's, host's or employer's — rather than the applicant's?*; Noul *does it apply only under a condition or to a subset of applicants?* |

**The grammar is a projection onto sinks that already exist.** For the CV every `(operation,
value)` resolves to a key of `constraints._CONSTRAINT_KEYS` — `max_pages`, `max_words`,
`max_chars_incl_spaces`, `max_chars_excl_spaces`, `max_bytes`, `language`, `photo_allowed`,
`date_of_birth_allowed`, `date_of_issue_required`, `signature_required`, `font` — or to a
`cv_directives` entry (`include`, `order`, `emphasise`). For the letter it resolves to a
`LetterShape` / `ApplicationPrompt.letter_*` field — `document_required`, `min_words`, `max_words`,
`max_chars`, `max_pages`, `form`, `naming`, `signed_declaration`, `font_family`, `font_min_pt`,
`line_spacing`, `margins_cm`, `file_bundle`, `handwritten`, `track` — to
`letter_written_requirements` (the `topic`), or to `letter_student_actions`. §11 gate 7's table
names the sink per catalog row, so "applied" always means a checker or renderer that exists ran;
an operation with no sink does not enter the grammar until its handler does. D4's
`no_cv_required` outcome resolves to a programme flag the plan adds, which document generation
reads to skip the CV and say why.

Values are typed, and the type decides who fills them:

- **`limit`** — Choice over the numbers code found in the sentence (digits and number words in
  every §8.1 language) plus `none`: *which of these is the maximum?*; Choice over `pages`,
  `words`, `characters` for the unit. The pick is copied verbatim; nothing is computed (§3.1
  item 2). `none` at ≥ 0.6 → no limit.
- **`language`** — set-valued: code finds every language name in the sentence (the §8.1 vocabulary,
  every script) and one Noul per name asks *does the sentence allow this language?*; "in English or
  German" is two values, not a conflict. The sink takes both — `render._check_language` has accepted
  a list since Eiffel's R-072, "CV in French or English" — so a single-valued question here would
  silently forbid the other language, and a CV in it is a rejected application. The letter's own
  sink holds one code, so a multi-language rule picks English where it is allowed and records the
  set beside it.
- **`format`** — the CV-format verdict as before: Choice over `europass_required`,
  `europass_preferred`, `any`, `other_template`, `not_a_format_rule`, with the 48 real sentences
  of `docs/research/cv-format-eval.csv` as criteria examples (`what`, `not_for`, `examples`).
  Negation ("no need to use the Europass format"), softening ("we suggest", "Wir empfehlen") and
  a stated choice each have an example on the side they belong to, because the keyword rule was
  wrong on exactly those (61%, spec of 2026-09-13). `other_template` carries the template's name,
  picked verbatim from the sentence, and §6.6 follows it.
- **`include`** — Choice over `derive._INCLUDE_TARGETS` plus `none`: *which field does the
  sentence say must be included?*
- **`order`** — Choices over `derive._SECTIONS` plus `none`, and over `chronological`,
  `reverse_chronological`, `none`. **`emphasise`** — Choice over `derive._SECTIONS`.
- **`style`** — Choice over a closed list seeded from `docs/research/cv-style-rules.csv` and
  `letter-rules.csv`: photo required or forbidden, a font size picked from the sentence's numbers,
  signed, dated, addressed, no colour, single column, and the rest the seeding pass of §11 gate 7
  produces.
- **`topic`** — the letter's one open slot: the verbatim sentence, kept as *something the letter
  must address* — a question the programme asks, a theme it names. It reaches the letter engine
  labelled as data with its source, exactly as a `ProgramStatement` does today, and the engine's
  claim hygiene still allows nothing a document could check unless the ledger holds it. **It is
  the only free text the grammar lets through, and it is a subject, never an instruction.**
- **`student_action`** — a requirement only the applicant can perform: sign by hand, notarise,
  upload as a named PDF, paste into a portal field. `LetterVerdict.requirement_path = student`
  already carries this for letters; it becomes an operation for both documents, its value the
  verbatim sentence, and it lands in `letter_student_actions` or the CV's equivalent list the plan
  adds, read by the student's Application Kit. It is applied by the student, never by the engine,
  and it is never `unapplied`. A rule whose document is `reference_letter` binds the referee's
  document; for the applicant it is a `student_action` — obtain the letters — and nothing else.
- **`other`** — a requirement no operation can carry. §6.5.

The first scope Noul at ≥ 0.5 marks the rule `third_party` and it binds no document (the
`_THIRD_PARTY` guard as a question, never dropped). The second at ≥ 0.5 sends the sentence to one
more Choice over the condition kinds the student ledger can answer — `nationality`,
`degree_level`, `work_experience`, `track`, `other` — and a typed condition is applied only to the
students it fits; `other` is a note (§6.3, §6.4). A typed condition is checked against the
**programme** before any student: a rule under a "PhD applicants" heading on a Master's
programme's page yields no rule for that programme at all, `track` and `degree_level` being read
from the programme's own record first.

The state is every sentence D5 labelled a requirement, **plus every `europass` line and every
CV-term or letter-term line `derive.candidates` finds by code — the code path stays, additive**
(`letter_terms.TERMS` covers nine European languages today and *gates* letter candidates; it becomes
§8.1 rows in the fourteen languages, and gating is what §8.1 ends). The slots are asked in **two
requests per sentence set**: document, operation and scope for every sentence first, then the
value questions each sentence's operation calls for — so the 48 format examples ride on the few
sentences that are format rules, not on every sentence, and state plus questions stays under Jev's
64k tokens (§3.1); a set larger than that is chunked. **Seeded, not invented:** every operation and every closed value comes from the
rules already catalogued in `docs/research/` — `cv-rules.csv` (93), `cv-style-rules.csv` (50),
`letter-rules.csv` (73), counted 2026-09-23 — and the grammar ships only when every one of those
rows can be written in it (§11 gate 7). New *instances* of these kinds — a limit of three pages, a
letter in Portuguese, a section order we have not met — need nothing new: they are what the slots
are for, on any site, in any of the fourteen languages, with no one involved.

**No separate "mandatory" slot.** Whether the sentence *requires* or *recommends* is D5's
`requirement` label (`REQUIRED` / `DESIRED`), already on the statement; it is what separates
`europass_required` from `europass_preferred`, exactly as the verdict's values do. **Enforcement is
unchanged by any of this:** every derived rule stays `ADVISORY_HIGH_RISK`, as the 2026-09-13 spec
and CLAUDE.md require, and the guard that a programme rule may never lower a key's enforcement
stays in code untouched. A Jev answer can make a rule *say* "required"; it can never make one
*bind*.

### 6.2 Acting — every rule at the same bar, nothing irreversible (amended 2026-09-23)

- A rule is applied when its `operation` and `value` confidences are **≥ 0.85**; §11 sets the
  shipped figure per question. Below, it is a note (§6.4) and the document is produced without it.
- **`europass_required`** was the one action with a higher bar — three phrasings agreeing at 0.95,
  because it renders the student's name, date of birth, education and employment history through
  europa.eu. **Owner judgement 2026-09-23: a mistaken Europass render is acceptable**, recorded in
  §14 for the privacy review. So it takes the ordinary bar. The three phrasings stay because they
  cost tokens in one request and no call: a Choice, a Noul *"does this sentence require the
  Europass CV format?"*, and a Choice whose criteria are written from the applicant's side. The
  action is taken when **two of three** agree at the bar; disagreement is the `phrasing` note of
  §6.3. Below the bar the CV renders `any` with the sentence noted — the outcome the format spec
  already defined.
- **`other_template`** at the bar → `any` plus a note carrying the template's name and link, and
  §6.6 reads the template.
- **Nothing here is irreversible.** Every applied rule is visible on the document with its
  sentence, its link and its confidence beside the choice it produced; the counsellor's existing
  document review can flip it in one click **as a `ConstraintOverride` row** — tenant-scoped, per
  student and programme, the decider recorded — never as a write to the shared catalog rule every
  other agency reads; and a flip is recorded as a labelled error for §11's calibration. That review is not a gate in the pipeline: the document is produced first, in full,
  and the review is where it was always going.

### 6.3 Ambiguity, detected and typed (2026-09-23)

Because every answer carries a probability and every rule is typed, four kinds of doubt fall out
of the numbers and out of code, each with its reason:

| kind | detected by | route |
|---|---|---|
| **unsure** | no answer clears the bar; the distribution is flat | note; the sentence and its probabilities join §11's calibration sample — a weakness of the system, not of the page |
| **conflict** | two rules on the same `(document, operation)` for one programme — two sentences, or the page and its PDF — both at the bar with different values | note carrying both sentences; the safer value applies: the tighter limit, `any` for format |
| **conditional** | the condition Noul at ≥ 0.5 | a typed condition is applied to the students it fits; an untyped one is a note |
| **phrasing** | the format verdict's three phrasings disagree | note; the sentence's wording is doing something the closed question does not capture |

None of these waits for anyone. What no design detects is a confident wrong answer; only the
corpus and the corrections made at document review find those, and both feed §11.

### 6.4 Notes on the document, not tasks for a person (owner decision 2026-09-23)

The pipeline never waits on a person and never creates a task for one. A reading that is
`unsure`, `conflict`, `conditional`, `phrasing`, `third_party`, `unapplied` (§6.5) or
`quarantined` (D8) becomes a **note** on the rule set the programme's documents are generated
from: the verbatim sentence, its English translation (§8.4), the page link, the kind, and the
probabilities. The document is produced with the safe default — the standard CV, the rule not
applied — and carries its notes. The only person who sees them is the counsellor at the document
review `phased requirements.md` §38 already places downstream, and that review is not a gate: the
document exists before it. `ConsultantResearchTask` is untouched by this reader; the fetch
engine's rung 7 keeps writing one for a page that could not be fetched, as a ledger row nothing
waits on.

### 6.5 A rule of a kind the grammar cannot hold (2026-09-23)

`operation = other` at the bar means the page states a requirement and no handler in the writing
engine exists for it — "publications in APA style", the first time it appears. No system can act
on a behaviour it does not have, and the alternative, handing the sentence to the writing model as
an instruction, is the one door this design keeps shut (§9 item 5). So the sentence is kept
verbatim as a `ProgramStatement`, noted on the document as **unapplied**, and **counted**. When
the count says a kind is real, it enters the grammar as an operation or a value — code, with its
handler in the engine — and `manage.py rederive_rules` re-asks the slot questions over every stored
sentence, so every programme that ever stated the rule gets it without a page being refetched
(the sweep CLAUDE.md already promises; it calls the decision layer directly and carries its own
limiter). The unapplied rate on the corpus is §11 gate 8; the target is a few sentences per
hundred programmes, falling. A requirement the engine cannot perform but the applicant can is
not `other`: it is `student_action` (§6.1), and the student applies it.

### 6.6 A template the engine does not know (2026-09-23)

A `format` rule naming a template, or any rule whose sentence links a file, has the fetch engine
follow the link as part of the same job (fetch-engine spec §7.0). A template file — DOCX, PDF, ODT
— is read **once per template digest** by a frontier model through the existing extraction clients
(the reference pattern of `apps/research/extraction.py`, with the per-programme `rate_limited` call
every LLM caller carries), which is extraction, not classification: it returns `{sections: [{name, order, fields}]}` under a schema with
`extra="forbid"` and a capped output. Every section name must be found verbatim (§8.3
`normalize`) in the template's own text or the reading is discarded; a discarded or partial
reading is a note with the template's link. A verified structure becomes `order` and `include`
rules for that programme, applied like any other. No person confirms it.

### 6.7 What is deleted, and what the deletion keeps

Deleted from `apps/documents/derive.py`: `_judge`'s three samples and three phrasings against
OpenAI, `_claude_reading` and `ANTHROPIC_JUDGE_MODEL`, `_with_one_retry`, `_agreed_by_all`, the
`_SAMPLES` constant; and the letter readings — `LetterVerdict` as a model answer, `_judge` on letter
candidates, `apply_derived_shape`'s per-field vote counting — whose fields survive as §6.1 values
and whose sink, `LetterShape`, is untouched; `letter_terms.TERMS` stops gating letter candidates
and becomes §8.1 rows. Kept, verbatim: `candidates` (code finds the sentences), `_THIRD_PARTY`'s
*intent* (now D6's Noul), `decide`'s outcome vocabulary (`UNDECIDED`, `unapplied`, `undecided`
rules), `constraints._MULTI_KEYS`, the enforcement-level guard, and every test that asserts an
*outcome* — those tests now stub the decision layer instead of two model clients. The 48-row gate
in `tests/documents/test_derive.py` is rewritten to run the D6 questions and becomes the ship gate
(§11). The 2026-09-13 spec gets a pointer to this section; its guarantees are restated there as
kept, its mechanism as replaced.

## 7. The crawl gate, without words

Fetch-engine plan 2's crawl follows **distance, not vocabulary**: from the programme page, two
hops, siblings allowed (`crawlEntireDomain: true`), 25 pages, an *exclude* list of obvious noise
(news, events, staff, login, press — a list of what to skip is easy to complete). D2 ranks the
site map first so the 25 are the likeliest, D3 triages every fetched page, and only D3's admits
reach D4. `FUNDING_PATH_TERMS` survives only as an additive signal on `/map`'s `search`
parameter, in every language §8.1 drafts: it can add a candidate, never remove one. The stages around this crawl — the programme page's own
document links, the guided map, the navigator — and the stop rule are the fetch-engine spec's §7.0
funnel (2026-09-23).

## 8. The multilingual layer

### 8.1 Vocabularies as additive data

`docs/research/vocabulary.csv`: one row per (`vocabulary`, `language`, `script`, `term`, `kind`,
`review_status`, `reviewer`, `date`), with `vocabulary` ∈ `funding_path_terms`,
`admission_terms`, `cv_terms`, `letter_terms`, `number_words`, `language_names` — the last two feed
§6.1's `limit` and `language` slots — and `kind` ∈ `word | path_slug`. Fourteen languages plus English,
German and French: Azerbaijani, Turkish, Kazakh (Cyrillic and Latin), Uzbek (Latin), Kyrgyz,
Turkmen, Russian, Georgian, Armenian, Mongolian, Chinese, Japanese, Korean. Cyrillic-language
sites also get transliterated path slugs (`/stipendii/`, `/granty/`), because that is how their
addresses are written. Drafted by a model in one pass, frozen, `review_status = drafted` until a
native speaker marks a row `reviewed` or `rejected`. **Every use is additive:** `admission_terms`
trims a page over the reader's cap to matching sections and reads the whole page otherwise;
`cv_terms` adds candidates beside D5's; `funding_path_terms` adds map candidates. A wrong or
missing term costs tokens, never a rule. A test pins ≥ 12 terms per language per vocabulary and
that every path slug is a valid URL fragment.

### 8.2 Language on every statement

`ProgramStatement.language` (BCP-47 with script: `kk-Cyrl`, `kk-Latn`, `uz-Latn`, `zh-Hans`), set
from D1's language Choice and the sentence's Unicode script, the script winning on disagreement.
`OfficialSourceSnapshot` gains `language` the same way. The corpus scores per language on these.

### 8.3 Quote verification that survives every script

Where a sentence is still compared to a page — the `unmapped` rules of the corpus, the `undecided`
rules a person edits, the image path — `normalize` gains, applied to both sides: Unicode NFC;
folding of `ʻ ʼ ’ ‘ ´ \` ʹ` to `'` and of `– — ‐ −` to `-`; non-breaking, thin and zero-width
spaces to a space; the bidirectional control characters stripped; then the existing whitespace
collapse and casefold, with Turkish `İ`/`ı` folded through casefold as Python already does when
both sides pass through it. Pinned by tests with an Uzbek sentence written with two different
apostrophes, a Kazakh Cyrillic sentence against its Russified OCR (must **not** match), Turkish
`İngilizce` against `ingilizce`, and a Cyrillic URL path through `canonicalize_url`.

### 8.4 The human surface

A statement or rule reaches a person as **the English translation, with the original sentence
and the page link beside it, labelled as the evidence**. The translation is one frontier call per
statement, cached on the row with the model and date, labelled machine-made, and used for
nothing else: never for verification, never for a decision, never in the CV. English-language
sentences carry no translation.

### 8.5 Images in every script

The fetch-engine spec's §15 design, now with the reading layer settled: the image is the
snapshot; Claude Sonnet 5 and OpenAI transcribe it verbatim (both measured exact on Turkish,
Azerbaijani, Kazakh in both scripts, Kyrgyz, Turkmen, Mongolian, Chinese, Korean, Russian;
Georgian and Armenian 98–100% of characters), Firecrawl's OCR is the free third; a line is kept
where at least two agree after §8.3's normalisation, and Firecrawl's OCR is never one of only two
because it Russifies Kazakh Cyrillic. The agreed lines then enter **D4–D6 exactly as a page's
sentences do** — Jev labels them, Jev judges them. `source_kind = image` and the object key ride
on every row. A Chinese-trained third transcriber is the tie-breaker candidate to measure when
Kazakh Latin or Uzbek ties appear. Trigger unchanged: the corpus finds a rule that lives only in
an image.

## 9. Security — what changes when one classifier decides

Page text is untrusted and Jev's own documentation says adversarial text can steer it. Without a
second model, four things hold the line:

1. **A rule is verbatim page text with a label.** Jev never writes a sentence; a steered answer
   can mislabel a real sentence, never invent one. What a person sees is always the page's words.
2. **D8 runs first.** A page carrying instructions addressed to a model is quarantined before any
   decision is taken on it: fetched, stored, no rule derived, the fact noted on any document that
   would have used it (§6.4). Nothing waits on anyone.
3. **Nothing is irreversible, and every applied rule is visible.** The bar is the same for every
   decision (§6.2). What protects the one action that moves student data is the owner's recorded
   judgement that its mistake is cheap (§14), plus the fact that every applied rule shows its
   sentence, link and confidence at document review, where a flip is a labelled error.
4. **Every decision is logged with its probabilities**, and §11's calibration audit re-runs a
   sample of acted decisions monthly against the corpus's labels and the review's corrections.
   Drift or steering shows up as a calibration break, which is measurable, rather than as a wrong
   CV, which is not.
5. **The grammar is the injection boundary.** The writing models never receive a page sentence as
   an instruction. What reaches them is a typed rule — an operation, a closed value — or, for the
   letter only, a `topic` labelled as data (§6.1). A page that wants the model to "ignore the
   ledger" has no slot to say it in.

Nothing here weakens the reader's existing "content is data, not instructions" labelling for the
frontier calls that remain (translation, transcription), nor `checkPromptInjection` on the
Firecrawl JSON read where it is still used.

## 9a. Operations — what runs it, what it writes, what bounds it (2026-09-23)

- **Trigger.** A programme is read when it enters the catalog — the ingestion path that creates a
  `Program` and its `OfficialSource` — and again when its monitor reports a change (fetch-engine
  §8). Never at document-generation time: a student's CV is built from rules already stored, and a
  programme not yet read renders with the standard defaults and a note saying so. The production
  caller is the five-part build's part 4; it carries the per-programme limiter `read_program_page`
  already has and a per-run cap on programmes.
- **Transaction boundary.** `read_and_derive` today holds one transaction across the fetch and the
  model calls (CLAUDE.md). The funnel makes that untenable: fetching and deciding run outside any
  transaction, and one short transaction writes a snapshot's statements, rules and notes together,
  keyed on the snapshot. Two readers on one programme serialise on the `Program` row.
- **Every decision is a row.** `research.DecisionRecord` — shared catalog under `HostProfile`'s RLS
  pattern: the decision (D1–D8 or a §6.1 slot), the question set's version, the state's digest,
  the answer, its probabilities, the model version, the provider, `created_at`. It is the
  calibration audit's input, `rederive_rules`'s input, and a **cache**: the same state digest and
  question set under the same model version is answered from the row, so a faculty-wide
  requirements page linked by thirty programmes is decided once. No student data is ever in a
  state.
- **The statement keeps its context.** `ProgramStatement` gains `heading_path`, `position`,
  `language`, `probabilities`, `model_version` and the translation; without the heading, §6.5's
  re-derivation would re-ask the slot questions about a bare sentence, which §5.1 says is where
  attribution errors come from.
- **A budget for decisions.** Jev is cheap and unbounded; a runaway sweep is still a bill.
  `DECISIONS_MONTHLY_TOKENS`, env-overridable, with a counter beside `FetchAttempt`'s credit ledger,
  checked before each request as the fetch budget is; exhausted → the read is rescheduled through
  the fetch engine's retry queue, never skipped silently.
- **Outage policy.** A 429 or 529 backs off with `retry-after`; an outage longer than the back-off
  reschedules the read through the same retry queue. **The provider is never switched on an
  outage:** thresholds are tuned per provider (§3.1 item 7), so a silent failover to the adapter
  would run every decision at an uncalibrated bar. The adapter answers only where
  `DECISIONS_PROVIDER` names it (§3.2).
- **Keys.** `TYPESAFE_API_KEY` reaches the worker as a Secrets Manager secret with an empty
  container, exactly as `FIRECRAWL_API_KEY` does, and `tests/infra/test_template.py` pins it the
  same way.
- **Observability.** Counters per outcome — applied, and each note kind of §6.4 — per language and
  per provider, plus Jev latency and 429s, on the existing `apps` logging path and CloudWatch
  filters. A rise in `quarantined` is the attack signal; a rise in `unsure` is drift; a rise in
  `unapplied` is the grammar falling behind.
- **Template files are untrusted files.** A template is read under the fetch engine's 10 MiB cap:
  DOCX and ODT as XML members through `zipfile` with member-size limits, PDF through `pypdf` as
  today; nothing is executed, nothing rendered.

## 10. Cost

| item | before | after |
|---|---|---|
| reading one programme page | 3 generative reads ≈ $0.30 | D3 + D4 + D5 ≈ $0.0008 |
| judging a page's candidates | 3–9 frontier calls ≈ $0.05–0.15 | D6 ≈ $0.0002 |
| triage of a crawled page that yields nothing | $0.35 if read | ≈ $0.0003 |
| translation for a person | — | ≈ $0.002 per non-English statement, once |
| a page the monitor reports changed | 1 vendor judge credit, then $0.35 if "meaningful" | ≈ $0.001, re-read unconditionally (D7 removed) |
| a 2,000-programme corridor pass, 25 pages each | ≈ $700 reader spend | ≈ $60 in decisions + ≈ $40 in fetches + translations |

The fetch-engine spec's economics said the reader was the dominant term and the fetch a rounding
error; this design removes most of the dominant term. What remains dear per programme is the
`/agent` navigator on the residue and the frontier calls for images.

## 11. Measurement — every gate has a number before it ships

Each measurement runs through the adapter as well, so Jev's number sits beside Claude's and
OpenAI's on identical questions.

1. **The 48-row CV-format gate** (`docs/research/cv-format-eval.csv`, `tests/documents/test_derive.py`):
   D6's `verdict` on every row; **ship gate for §6 is 48/48 on the Europass action and ≥ 46/48 on
   the rest**, the bar the frontier judge met.
2. **Statement selection** on the six pages with stored statements (FAU, TUM, SISGP, Rhodes,
   DAAD PRIME, JASSO): D4 + D5 against the stored rows; recall of REQUIRED statements ≥ 0.95, and
   three runs byte-identical.
3. **Per language** on the labelled corpus (`docs/superpowers/specs/2026-09-23-labelled-corpus-design.md`): D4 recall and D5 label accuracy per
   `language`; a language below 0.9 on either has every decision in it written as a note (§6.4)
   until its threshold is re-tuned or the adapter takes that language (§3.2) — the design degrades
   to notes, never to silence.
4. **Calibration:** confidence bins against accuracy on 1–3; a bin whose accuracy is below its
   confidence moves that question's threshold up. Repeated monthly on a sample of acted production
   decisions.
5. **Triage recall** on the corpus: every rule-bearing page must clear D3 at its threshold.
6. **Consistency:** 15 repeats of D5 on one page — label agreement ≥ 0.99 at the shipped
   threshold, the figure TypeSafe's own consistency cookbook reports — **and** the same page under
   each wording of gate 12: the vendor measured repeat variance at σ ≈ 0.01, so repeats prove
   little and rewording is where the variance lives (§3.1a).
7. **Grammar expressibility (2026-09-23):** every row of `cv-rules.csv`, `cv-style-rules.csv` and
   `letter-rules.csv` (216 on 2026-09-23) written in §6.1's slots by a person once, and a test that
   pins the mapping; a row no slot can carry is a missing operation found before the grammar ships,
   not after.
8. **Unapplied rate** on the corpus: `operation = other` on ≤ 2% of requirement sentences, per
   language; above it, the grammar grows before the decision layer ships.
9. **Provider per decision:** gates 1–3, 5 and 10 run through Jev and through the adapter on Claude
   and OpenAI with identical questions; per decision and per language the better one is written
   into `DECISIONS_PROVIDER`, Jev where they tie. Re-measured on every model version change.
10. **Letter selection** on the corpus's letter rules: D4's letter Choice recall ≥ 0.95 and D5
    label accuracy ≥ 0.9 per language.
12. **Wording ablation (2026-09-23):** every decision's question ships with at least two wordings
    (question form and statement form — the vendor says to test both); on the corpus, per
    language, the wording with the best accuracy at the shipped bar is written into the question
    module and the losers stay in the file with their score. No wording changes without this.
13. **State ablation:** chunk size (25 / 50 / 100 / 200 sentences per request) and state shape
    (flat `sentences` against `sections[k].sentences[j]`), on the corpus. The vendor's rules
    predict smaller related chunks win and the cost is negligible either way; the corpus decides.
    Two riders in the same run: a `note` naming the page's language on non-English pages, and
    per-option `examples` beyond the 48 format sentences.
11. **Negatives in the corpus** (counts fixed by the corpus spec §5.2)**:** pages that state no CV or letter rule, third-party sentences,
    negated and conditional sentences, and pages that are not the programme's, in every language —
    so gates 1–3, 5 and 10 measure false positives and the stop rule's false stops (fetch-engine
    §7.0), not recall alone. The corpus spec fixes the counts.

All live measurements carry the `live` marker and run deliberately.

## 12. What this replaces, and what is deleted

- The generative reads: `reader.extract_statements`, `_READS`, `verified_statements`,
  `dropped_quotes`, the union, and their tests. `read_program_page`'s transaction, cache and
  `require_same_origin` stay.
- The judge's mechanism: `_judge`'s samples and phrasings, `_claude_reading`,
  `ANTHROPIC_JUDGE_MODEL`, `_with_one_retry`, `_agreed_by_all` — and the pending "judge format
  fixes" (the answer-format change and the retry removal in the 2026-09-22 handoff) become moot,
  because there is no answer format to fix.
- The three word lists as gates, and `letter_terms.TERMS` as a fourth; they survive as §8.1's additive data.
- `2026-09-13-format-decision-guarantee-design.md` is superseded in mechanism and pointed here.

## 13. Deliberately not built, with the trigger

| not built | trigger |
|---|---|
| a second model family reading beside Jev on a decision | §11's calibration audit shows acted decisions on that question wrong more than 5% two months running, and gate 9's adapter measurement has not already taken the decision |
| a human confirmation before a rule is applied | the owner reverses the 2026-09-23 no-person decision, or the privacy review of §14 requires one for the Europass action |
| a student-facing consent step before a Europass render | the same privacy review |
| a frontier model as a second reader anywhere in classification | the owner reverses the 2026-09-22 decision, or §11.4's calibration audit finds a steered or drifted question the three-phrasing rule did not catch |
| Score questions (ordered levels) anywhere | a decision that is genuinely a spectrum appears; every decision here is a set or a yes/no |
| a fine-tuned or per-tenant classifier | TypeSafe does not offer one, and nothing here needs one |
| Jev for deadlines, amounts, dates | the discovery session's card work; their date-extraction pattern is the design when it comes |
| hierarchical classification of funders and holders (their beam-search cookbook) | the register work in the discovery session |
| a review UI for `vocabulary.csv` | a native speaker asks for one; until then the CSV and a pull request |

## 14. Open questions

- **Non-English accuracy** — TypeSafe's own caveat; §11.3 is the answer and nothing ships a
  non-English decision before it runs.
- **Availability** — *closed 2026-09-23:* sign-ups reopened on 2026-09-20 ("available to everyone,
  no waitlist", `console.typesafe.ai`), and OpenRouter serves `typesafe/jev-1.13` in beta. Rate limits
  still change "while upcoming large GPU deals land"; the adapter fallback stays for that. No key
  exists on the development machine yet — the owner signs up.
- **Package source** — *closed 2026-09-23:* public PyPI, confirmed source (§3.2).
- **A mistaken Europass render.** Owner judgement 2026-09-23: acceptable — the data goes to the
  EU's own Europass service to produce the student's own CV, and the wrong format is visible and
  reversible at document review. Recorded here for `phased requirements.md` §10's privacy items,
  which is where the lawful-basis question belongs; nothing in this design depends on the answer
  except §6.2's bar.
- **Arabic script, Persian, right-to-left, vertical CJK** — readable by the transcribers,
  untested by Jev, not in the fourteen.
- **Intake-year validity of an unchanged page.** A page that has not changed is presumed to state
  the current cycle's rules; the monitor catches change, not staleness. A page that names a past
  intake year and never changes is the case nothing here detects; the corpus records how often it
  occurs before anything is built for it.
- **The price** — they "expect it to go down, not up"; the design's economics survive a 10×
  increase.

## 15. Implementation plans

1. **The decision layer and the judge** — `decisions.py`, the client and adapter, settings, the
   rule grammar (§6.1) with the 48-row examples and the expressibility gate, the notes surface (§6.4), the ambiguity kinds (§6.3), the unapplied counter and `rederive_rules` (§6.5), the rewrite of `derive.py`, the ship gate, the deletion
   of the old judge mechanism, the pointer in the 2026-09-13 spec and CLAUDE.md.
2. **The reader and the multilingual layer** — the sentence splitter with its context (§5.1), D4–D5 with the letter Choice, template reading (§6.6), `ProgramStatement`
   changes and migration, `normalize`, `language`, translation, `vocabulary.csv` and its test,
   the deletion of the generative reads, gates 2–6.
3. **Triage and outcomes inside the fetch engine** — D1, D2, D3, D8 (D7 removed 2026-09-23), wired into fetch-engine
   plan 2's crawl and monitor; the crawl's exclude list.

The labelled-corpus spec (unwritten) is the instrument for gates 3–5 and proceeds in parallel.
