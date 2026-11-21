# One decision engine: Jev first, a cheap second reader where Jev is unsure

Status: design, awaiting owner review. Written 2026-10-03 on `claude/verified-catalog-design`.
Inputs: the 2026-09-28 call-site inventory of `master` at 02926ac2 (every model call in `apps/`),
the 2026-09-28 vendor research (Jev docs, OpenRouter endpoint data, Chinese-model prices, papers),
the requirement-reader session's cost findings (2026-09-28), and a live probe the same day.

**In one paragraph.** Every place this system asks a model to *judge* something — is this line about
money, who pays this amount, is this sentence invented, what kind of organisation is this — goes
through one function, `decisions.ask`, and is answered by Jev. Where Jev's answer falls in the band
its measurement says is unreliable, the same closed question goes to one cheap second reader (a
Chinese model on a measured host), and the answer stands only if the two agree. Every place a model
*writes* — a letter, a CV, a project description, search terms — goes through one writer client with
the student's identifiers masked by code. The four multi-model votes in production today are deleted,
each when its replacement passes its gate. One harness, built by models, measures all of it.

## 0. What governs

This is the master document for **which model answers what, how, at what bar, and on which host**.
Where it and another spec disagree on those questions, this one governs; on everything else the other
spec governs its own subject.

| Document | Relationship |
|---|---|
| `2026-09-27-verified-catalog-one-reader-design.md` | Governs the funding reader's questions (§5.2), its finders (§5), fetch filters (§5.4), registers and proof (§3–4). **Superseded here:** §6.1 "one reader per decision" gains the second-reader stage (§3 below); §6.3 "which model" moves to §5 below; §7's harness becomes the shared harness of §6 below; §5.1's question rules are extended by §3.7, and §5.2's catalogue is amended by §3.8. |
| `2026-09-28-one-letter-engine-design.md` (branch `claude/letter-gap-fixes`) | Governs letters end to end: research, story, plan, writing, checks, repair. **Aligned:** its S1 masking seam, S6 host rules and S7 Jev checks are this design's §4, §5 and §3 applied to letters. Its S7.3 "uncertain band → warning" is kept for letters (a warning costs nothing); §3's second reader is an option its bake-off may switch on per question. |
| `2026-09-22-typed-decisions-and-multilingual-sources-design.md` + its 2026-09-26 addendum | Governs `decisions.py`'s contract (closed questions, `DecisionRecord`, budgets, refusal kinds). **Changed:** its "never switches provider" rule stands for failover and is narrowed for the second reader, which is a measured stage, not a failover (§3.3). |
| `2026-09-14-funding-reader-precision-design.md`, `2026-09-13-format-decision-guarantee-design.md` | Their three-reading unanimity rules are retired by §7, each when its replacement passes. Their measurements stay the record of why the votes existed. |
| Requirement-reader cost findings (other session, 2026-09-28, not a spec) | Become §8.2, credited there. That session writes no separate spec (owner, 2026-09-28). |

## 1. Owner decisions this rests on

- Jev answers closed judgements; no multi-model vote in production (2026-09-27, 2026-09-28).
- Chinese model families are tested and used wherever they match quality, on the cheapest host in
  any country, student data included, with direct identifiers stripped in code first (2026-09-27).
  The GDPR point (pseudonymised data stays personal data, Recital 26) was put to the owner and the
  decision stands; this design makes the stripping true in code, which it is not today (§4).
- No human in the loop; measurement is built by models for a few dollars (2026-09-27).
- One combined design for every reader, not one per reader (2026-09-28).
- Option chosen 2026-10-03: **Jev first, a cheap second reader only where Jev is unsure** — over
  Jev-only (cheapest, loses facts in weak languages) and best-model-per-decision (most providers and
  calibrations to keep).
- Decided 2026-10-03 in a grilling round (each applied where its section says):
  - **At most 1 wrong value in 100** on anything a student sees (§6.3).
  - **A language passes on the pooled bar, then is checked on its own** (§3.4).
  - **Student text may go to any host once masked** — the 2026-09-27 rule stands; the zero-retention
    narrowing this design first proposed is withdrawn (§4.1).
  - **A leaked unknown spelling of a name is acceptable**; it is logged and added to the mask, the call
    is not rerouted or blocked (§4.2).
  - **Name entry adds no friction**: the name typed at sign-up, code-made variants, and near-matches
    found in the student's own uploads; a passport's machine-readable name is a cross-check (§4.2).
  - **Two readers on deadline, eligibility and documents, always** (§3.3), and **catalogue verification
    is charged to the platform's budget, never to a student's** (`funding/wallet.py`).
  - **Verified-only** (later the same day, recorded by the verified-catalog session, reversing an
    earlier "unverified notes" answer): a student sees an award only when every value they act on —
    deadline, eligibility, document list — meets the 1-in-100 target **and** the student is eligible on
    verified facts. Anything else, including every award from a language that has not passed, is not
    shown at all. Owner: "It shouldn't be shown as it will lower the reputation of a platform. Student
    should see only programs that he can apply to and verified." The owner's "never" errors at the
    application stage: a wrong or missed deadline, being wrongly told "eligible", a wrong document list;
    being wrongly told "not eligible" is not one of them (§3.5).
  - ~~Jev reads English~~ — **reversed the same day: no translation.** Two independent measurements
    (this session's 443 lines; session f7's 48 pages in 9 languages) found translating first adds
    nothing once the questions carry written criteria (all arms within 0.3%; funding lines slightly
    worse translated). Jev reads every page in its own language (§3.10).
  - TypeSafe's DPA and OpenRouter's terms were accepted by the owner (2026-10-03, recorded by the
    verified-catalog session).
  - **A portal's official rule counts as verified for a programme whose page names that portal**
    ("apply through uni-assist", the funder's own portal), cited with both links (§8.5).
  - **Transcripts** (handed to the transcript-reading session): when a notarised translation is
    uploaded, the reader reads **only the translation**, because a sworn or notarised translator has
    already checked it; the Azerbaijani original is read only when no translation is uploaded. 2026
    e-diploma verification (edu.gov.az/az/yoxla needs a document number, date of birth and a
    reCAPTCHA) is **ignored** — no automated check, no verification link.

## 2. What exists today (2026-09-28 inventory, master 02926ac2)

**Judgement calls (closed answers):**
- Jev already: `decisions.ask` (#159) for transcript reading and the CV/letter rule grammar;
  `apps/research/jev.py` (#158) for the provenance vetoes. **Two Jev clients**, two settings blocks.
- Frontier models doing closed work: `funding_judge.py` (2 OpenAI + 1 Claude per chunk, unanimity,
  a 4th tie-break reading; also through the Batch APIs in `batch_reading.py`); `derive.py`'s frontier
  judge (3 readings × one retry, unanimity; now only the fallback when no decision provider is
  configured); `research_fit/judge.py` (3 readings, majority) and `classify.py` (1 per page);
  `letter_verification.py` (2–3 readings, unanimous); `classify.py::FrontierClassifier` (org kind);
  `tailoring.py::judge_remainder`; `profile_cells.py::select_bucket`; `mailbox/classify.py`;
  `portals/learn.py::learn_from_snapshot`.

**Structured extraction by a writing model:** `extraction.py::extract_claims` (programme claims
JSON), `reader.py::extract_statements` (3 reads unioned), `ingestion.py` (raw CV → claims),
`prompt_resolution.py` (no caller).

**Prose writers:** `letters.py`, `generation.py` (CV JSON with prose fields),
`evidence/extraction.py`, `storyline.py` (no caller), `research_fit/anchors.py` (topic phrases),
`angles.py` (search terms), `funding/explanations.py` (no caller).

**Identifier handling:** only `transcript.py::_minimised`, the portal snapshot guard, research-fit's
query guard (on the model's *output*, not its input) and `tailoring.py` dropping IDENTITY facts.
**Nothing masks identifiers before** CV generation (identity facts and the contact e-mail are in the
prompt), CV ingestion (raw CV text), letters, storylines, evidence intake or the mailbox classifier.

## 3. The judgement path: `decisions.ask`, two stages

### 3.1 One client

`decisions.ask` is the only function that asks a closed question. `apps/research/jev.py` and its
`JEV_*` settings are folded into it: the provenance vetoes call `ask` with `record=True` (page text
only), and `blocking.py` keeps its veto logic unchanged. One base URL, one key setting, one pinned
model (`TYPESAFE_MODEL = typesafe/jev-1.13`, endpoint `/api/v1/systemone`; measured 2026-09-28:
served `typesafe/jev-1.13-20260917`; `typesafe/jev-router` on that endpoint returns "does not exist" —
it is a chat router over other models and its measurements never count as Jev's).

### 3.2 Stage one: Jev

Unchanged from #159: a state, a map of Nouls and Choices, all questions about one state in one
request (Jev has no prompt cache, so a second request pays for the state again), `inspect` paths
into a state keyed by name, never by position.

**What a request costs, measured 2026-10-03** (five calls, one fixed five-line state): 1 question →
386 billed input tokens, 5 → 466, 20 short → 766, 20 long → 1,286; a one-word state with 1 question →
286. So a request carries **≈ 270 tokens of fixed overhead**, the state is billed **once**, and each
question adds only its own text: **≈ 20 tokens for a short question, ≈ 46 for a long one**. At $0.042 per
million input tokens (output free), a 120-line chunk with 8 questions per line (≈ 960 questions,
≈ 24k question tokens plus the state) costs ≈ 0.12¢. Question length is therefore a real but small
cost lever; the state is the large one.

**The context limit is budgeted at 32,000 tokens for the whole request** — state *and all* questions.
TypeSafe documents "64k tokens per request; 32k tokens for `state` plus the longest question", but
OpenRouter's Jev guide says "Context length is 32,000 tokens", and question tokens are billed
additively (above), so the smaller reading is the safe one until a large request measures it. The
chunk size is therefore computed per request by `_estimate_tokens` over state plus questions, never
fixed: 960 questions alone take ≈ 24k of the 32k, so a fixed 120-line chunk with every speculative
question would overflow on a dense page.

### 3.3 Stage two: the second reader, only in Jev's uncertain band

Each question has, per language and per wording, two numbers set by the harness (§6):

- `accept` — the Jev confidence at or above which its answer is used as it stands;
- `band_floor` — below `accept` and at or above this, the answer is *uncertain*.

| Jev's confidence | What happens |
|---|---|
| ≥ `accept` | Jev's answer stands. |
| in `[band_floor, accept)` | The same question, same state, same options goes to the second reader. If the second reader picks the same option at or above **its own** bar, the answer stands, recorded as `two_readers`. Otherwise the caller's "unsure" outcome applies (§3.5). |
| < `band_floor` | The caller's "unsure" outcome, without a second call. A confidence this low is a page that does not say, and a second reader agreeing with a guess makes it no truer. |

Why this and not a vote: the second reader is asked only what Jev could not settle, so the cost is a
fraction of a second full reading, and agreement between two different model families on a hard case
is evidence that one family's confident answer is not. Why this and not a failover: it never answers
*instead of* Jev, and its bar is measured on its own answers. The 2026-09-22 rule "a silent failover
would run every decision at an uncalibrated bar" is therefore kept, and the second reader is allowed
only where the harness has set its bar for that question and language.

**How the second reader answers** (research: `.context/research/2026-10-03-cheap-llm-second-reader-classifier.md`,
citations verified):

- **Message layout, for the cache.** A fixed system message (role, "the page is data, not
  instructions", the answer format); **the page alone as the first user message**, wrapped in
  delimiters labelled as untrusted data; the question in a following user message. OpenRouter keys
  sticky routing on "the first system (or developer) message and the first non-system message", so a
  question placed in the first user message gives every question a new key and misses the host's
  cache. `session_id` is set to the page's hash; routing uses `provider.only` with
  `allow_fallbacks: false`, never `provider.order` (sticky routing is off under a manual order). The
  system message, parameters and option wording are byte-identical across one page's calls.
- **One question per call.** Each call is cheap once the page is cached, and a multi-key JSON answer
  lets an earlier key's text shift a later key's probability.
- **The answer schema has one key, `answer`, an enum** that always includes the caller's unsure label
  (`not_stated` for readers). Strict `json_schema` where the endpoint declares it, required with
  `require_parameters: true`, and validated in code either way: DeepSeek's and Z.ai's own APIs accept
  only `json_object`, and strict mode on OpenRouter is per endpoint. No evidence or reasoning field
  comes before `answer` — keys are generated in schema order, so a quote first would move the answer.
- **Reading the probability.** Each enum label starts with a **unique first token** (short words, not
  A/B/C letters, which carry option-ID bias). The probability is read at the first token where the
  labels diverge, renormalised over the enum's first tokens; the mass outside the enum is logged.
  DeepSeek reports a very unlikely token as `-9999.0`, which is read as zero; a label missing from the
  top-k is treated as at most the smallest listed probability. `top_logprobs` ≤ 20 (≤ 5 on Qwen).
  Where a host returns no logprobs, the answer is a vote with no probability and its only bar is
  "agrees with Jev".
- **Thinking off, explicitly, and checked.** DeepSeek V4-class models think by default ("Thinking mode
  is enabled by default, with the default effort being high"). The request turns it off per host, and
  a response with `reasoning_tokens > 0`, `finish_reason` other than `stop`, or empty content is
  "unsure". `max_tokens` is the JSON wrapper plus the longest label plus a small margin.
- **Instructions in English** on every page; the bar is per language (§3.4). **No few-shot examples**
  by default, and never a key row as an example.
- **Option order is fixed** per question and wording in production; the harness permutes it on the
  key to measure position bias (§6.2).
- A malformed, refused or skipped answer is "unsure", retried at most once.

**A second reader is a (model, host, quantisation) triple, accepted only on a probe.** Measured
2026-10-03 (`.context/research/2026-10-03-engine-probes.md`): DeepSeek V4.1 Flash with thinking off
answered a plain monthly stipend `paid_to_student` at P 0.9997 on Fireworks and **`not_stated` at
P 0.89–0.93 on Ionstream, DigitalOcean and Together**. The wrong hosts bill ~100 fewer prompt tokens
for identical messages — a different chat template — and a rephrased question did not fix them.
Declared features were wrong twice (Together and CoreWeave declare logprobs and returned none). So:
the triple is pinned (`provider.only` with one host, its quantisation recorded), the harness measures
each triple separately, a host change or a changed prompt-token count for an unchanged request stops
its bar from applying until re-measured, and no host is used on its declaration alone. Plan 1 repeats
the probe on more items for every candidate triple: answer, logprobs present on every call, and
`cached_tokens` on a page's second call.

**The owner's three "never" facts always take two readers** (owner, 2026-10-03, recorded by the
verified-catalog session): "verified" means Jev at its measured bar, plus code's checks, plus a second
independent reader agreeing — for every question that decides a **deadline, eligibility or a document
requirement**, whatever Jev's confidence. Their mode is fixed at `jev+second` with no `jev`-only
shortcut; a disagreement makes the fact unsure, and the verification engine (verified-catalog) climbs
its ladder before the fact is dropped. At ≈ 0.006¢ per cached second-reader question (§5) this adds
well under a cent per page. All other questions keep the band rule above.

**Which model is the second reader** is plan 1's first result: DeepSeek V4 Pro (frontier; on OpenRouter
≈ $0.21–0.45 in / $0.42–3.48 out per million depending on host, 2026-10-03) against V4.1 Flash. Its
thinking must be switchable off, its host probed like Flash's, and its errors measured against Jev's
for correlation. A **third reader** (Gemini 3.5 Flash measured; a stronger family to compare) is added
only if two readers fail the bar, asked only on items the two leave unsettled, and counted only as a
confirming vote (§11 has the 2026-10-03 numbers).

**Cost per student** (estimate, 2026-10-03): pages are shared — read once per page version for every
student — and the pre-built Azerbaijani core is a platform cost, so a student pays only for pages no one
has read: ≈ 100 pages for the first students in a new area (≈ 8¢ fetching + ≈ 30¢ reading with two
readers; a third reader adds ≈ 20¢ with DeepSeek V4 Pro or ≈ $1–4 with Gemini as measured), ≈ 10–30
pages later (≈ 5–15¢). Plan 1 logs real page counts per pack.

**For every other question and language, the harness picks one of three modes**, written to `DECISIONS_PROVIDER`
the way #159 already routes per decision and language:
- `jev` — no second stage (Jev alone already meets the bar, or the second reader adds nothing);
- `jev+second` — the cascade above;
- `second` — the second reader alone, only where it beats Jev outright on the key (expected for
  none; allowed so a measurement is never overruled by this document).

### 3.4 Calibration is per question, per wording, per language

Jev's documentation claims calibrated confidence but publishes no reliability figures, and says
probabilities do not carry across question types (a Noul and an equivalent yes/no Choice gave 0.22
and 0.01). So no bar is carried from one question to another, and none from Jev to the second reader.
The harness sets `accept` as the lowest confidence at which the answer's precision on the key meets
the question's target (§6.3), and `band_floor` as the lowest confidence at which the second reader's
agreement still lifts precision to the target. A question/language with no measurement runs in the
caller's "uncalibrated" mode: notes, not actions (verified-catalog §5.3; letter engine S7.3).

**A Choice's confidence depends on how many options it has** ("0.5 is a weak answer among two options
and a strong one among ten, so set its threshold per question" — `confidence.md`). That is harmless for
a fixed option list and wrong for a Choice whose options are candidates found on the page (headings,
places, amounts, durations), where the count changes from page to page. Such Choices are gated on the
top probability **stratified by option count** in the harness (bands 2–3, 4–8, 9+), or rewritten as
one Noul per candidate wherever more than one candidate can be true (§3.8).

**Pooling across languages** (owner, 2026-10-03). A bar measured per language needs enough rows: by the
rule of three, showing 0.99 precision with 95% confidence takes ≈ 300 checked values with no error,
far more than one language's slice of the key holds. So `accept` is first set on all languages pooled, and each
language is then checked against it with its own interval; a language whose interval falls below the
target gets its own, higher bar or stays at notes-not-actions. The verified-catalog spec's §7 carries
the interval arithmetic and the owner decision it raises.

### 3.5 What "unsure" means is the caller's, and fixed per caller

| Caller | Unsure means |
|---|---|
| Funding and programme readers | `not_stated` — never a guessed value. An award with any acted-on value (deadline, eligibility, documents) unsure, or from a language that has not passed (§3.4), is **not shown** (owner, verified-only, 2026-10-03). Turning unsure into verified is the verification engine's job (verified-catalog session) |
| Fetch filters (verified-catalog §5.4) | **keep** — fetch the page; a skip needs positive evidence |
| Letter checks (letter engine S7) | a warning beside the sentence |
| CV/letter rule grammar | `undecided` rule shown to the counsellor (unchanged from #159) |
| Organisation classifier | no kind written; the next rung asks |
| Provenance vetoes | no veto (a veto only ever lowers a verdict, and needs to be sure) |
| Transcript reader | the row is shown as unread |
| Mailbox classifier | `unclassified`, shown to the student |

### 3.6 Order-swapped pairs for values a student acts on

Jev "leans toward the option that comes first" (`model-jaggedness/jev-1.13`, which says to "reorder the
options to double check that the answer stays consistent"). For the Choices that put a value on a
card — `pays`, `date_role`, `bound`, `period` — the same question is asked twice **in the same
request**, once with the options reversed. It costs ≈ 25 tokens (§3.2), not a second state. The answer
stands only when both orders pick the same option, and its confidence is the lower of the two;
otherwise it is "unsure" and goes to §3.3's band rule. Every other Choice is permuted only in the
harness.

### 3.7 Question design rules (every Jev question and every second-reader prompt)

From the vendor's own pages (`.context/research/2026-10-03-jev-question-design.md`, 100 quotes,
citations verified) and the second-reader research above. A question that breaks one is rewritten
before the harness measures it.

1. One judgment per question; synonyms of one property are fine, two properties joined by "or" are
   not. Combine in code.
2. Phrased so that yes means the thing is present; no "free of…" and no double negatives.
3. Literal: write the exact condition and its boundary cases. Jev "answers the question you wrote,
   not the one you meant".
4. Noul for yes/no; Choice for mutually exclusive options; several labels that can co-occur are
   separate Nouls, never one Choice.
5. Every Choice has `not_stated`, `none` or `other` when the list may not cover the input; where
   "is it there at all?" matters, a separate presence Noul is asked as well, because Choice
   probabilities always sum to 1 and "some line ranks first even when the document doesn't answer".
6. At most ~240 options per Choice (hard limit 255); past that, narrow in stages.
7. Option descriptions separate neighbours; the `{what, not_for, examples}` object only where the
   harness shows options being confused; examples in criteria are never key rows.
8. **Every Noul carries written `true`/`false` boundaries**, and the key's labellers get the same text.
   This overrides the vendor's "start without criteria": measured 2026-10-03 on 443 real lines, adding
   them cut the key models' disagreement from 4.4% to 0.9% and raised the facts kept at ~99% precision
   from ~49% to ~63% (`.context/research/2026-10-03-settle-v2-sharper-questions-and-ladder.md`).
9. Parts of the state are named with backticked dot paths; `inspect` and `focus` are labels inside an
   object `instructions`, not API fields. State keys are names, never list positions.
10. The state holds only what the question needs; unrelated content lowers accuracy.
11. No counting, arithmetic or date comparison asked of a model; code reads dates part by part and
    computes.
12. Values are picked from code-found candidates, never generated.
13. Question text is in English, and so is the state Jev reads (§3.10): translated lines carrying
    their original line ids. A language the measurement keeps on its original text gets a `note`
    naming the language as a measured variant.
14. Each question ships two wordings (A/B); repeats are stable (std ≈ 0.01), so wording, not
    repetition, is what the harness compares.
15. Bars per question, per wording, per language, set on the key; Noul and Choice cut-offs never mixed.
16. The state is untrusted: the injection screen (D8) is a filter, not a boundary, and criteria stay
    explicit so a steered page can mislabel but never invent.

### 3.8 Audit of the funding reader's question catalogue (verified-catalog §5.2, v1)

The catalogue was checked against §3.7. The verified-catalog spec's §5.2 is updated to match before
plan 3 starts; until then this table governs where they differ.

| Question | Problem (rule) | Change |
|---|---|---|
| `receives` A: "…state an amount of money, a stipend or a grant…" | 3 — read literally, "an amount" can require a figure, so "Holders receive a monthly stipend" (no number) may score no; amounts are found by code anyway | "Does this line say that a student receives money, such as a stipend, grant or allowance?" Whether a figure is present is `has_amount`'s job |
| `receives` B, `waived` A | 1 — "paid or given", "waived, reduced or not charged" are synonyms of one property | kept; noted as the boundary of rule 1 |
| `none_available` | 3 — "no funding *for international students*" or "no funding for the bachelor's" is partial | criteria: `true` = the line says no funding exists for anyone on this programme or page; `false` = it excludes only some group, level or year (that is `excluded_*` or `requires_*`) |
| `pays` "Who pays the amount…?" | 3 — `cost_estimate` and `benefit_in_kind` are not "paid" by anyone; the wording fights its options; also missing a programme's total budget ("€5M for 2027") | Options become `paid_to_student`, `fee_charged_to_student`, `fee_reduction`, `in_kind_value`, `cost_estimate`, `total_budget_or_count`, `other`, `not_stated`; asked as an order-swapped pair (§3.6). Wording: "Who pays the amount in `amounts.mN`?" stays A and "What is the amount in `amounts.mN`, read on its line?" becomes B — the 2026-10-03 probe scored the old wording 11/12 and the new 10/12 on six amounts, too few to choose; the harness decides |
| `covers` "What does the amount pay for?" | 3 — a fee is charged for, not paid for | "What is the amount in `amounts.mN` for?" (same options) |
| `bound` | 5 — no `not_stated` | add `not_stated`; order-swapped pair |
| `date_role` | 5 — `other` but no `not_stated` | add `not_stated`; order-swapped pair |
| `route`, `money_form` | 5 — closed lists without an escape | add `not_stated` and `other` |
| `amount_for`, `date_for` (Choice over places + `everyone`) | 4 — an amount often applies to several places at once ("EU and EEA students"); a Choice forces one; option count varies (§3.4) | one Noul per place candidate on the amount's own line or header: "Does `amounts.mN` apply to applicants from `places.pK`?", plus one Noul "Does `amounts.mN` apply to all applicants alike?" |
| `duration` (Choice over candidates + none) | §3.4 — variable option count | kept as a Choice (one funding duration per award), gated stratified by option count, with a presence Noul "Do these lines state how long the funding lasts?" |
| `name` (Choice) | §3.4, 5 | kept; presence comes from `is_award_name`; stratified gating |
| `suspended` "suspended, closed, or not offered this year" | 1, 3 — "applications are closed" (this round's window) is a different fact from a discontinued award; one hides a real award for a year | split: `discontinued` ("Do these lines state that this award is discontinued or not offered in the coming round?", hides at 0.70) and `window_closed` ("Do these lines state that applications for this award are currently closed?", a note on the card with the next opening if a date is found; never hides) |
| `holder_kind`, `tuition_level`, `living_level` | — | kept; `tuition_level`/`living_level` stay Choices (distinct categories), not Score, whose "levels are weak in numerical calibration" |
| `eligible_pN`, `excluded_pN`, `requires_cN`, `apply_here`, `apply_elsewhere`, `extra_*`, `obligation_*`, `internationals` | — | kept; `inspect` paths by name |
| Call 1's eight questions per line | §3.2 — 32k budget | the five relevance questions on every line; the three speculative ones only on lines a code pass did not already settle (a line with a currency span needs no `has_amount`); chunk size from `_estimate_tokens` |

### 3.9 Failure

`decisions.ask` keeps #159's refusal kinds: `not_configured`, `failed` (retried next read), `refused`
(recorded, not asked again under that pin). A failure of the second reader never fails the decision:
it is "unsure". A Jev outage is not covered by the second reader (that would be a failover); the
caller's outage policy applies, unchanged.

### 3.10 Translation — dropped (owner, 2026-10-03)

**Jev reads every page in its own language; nothing is translated.** The owner first chose English-only,
then reversed it on the measurements: translating first changed almost nothing once the questions
carried written criteria (§11). The rest of this section is kept as the design to reuse **only if** a
language later fails its bar and a translation arm is shown to rescue it — a per-language owner
decision, measured first. Three rules would then keep translation from becoming a source of wrong
facts:

1. **Values never come from the translation.** Code finds amounts, dates, places and names on the
   **original** line and copies them from there; the translation only carries the meaning Jev judges
   (who pays, whether a group is excluded, whether something is required). Each translated line keeps
   its original line id, so every answer points back to an original line.
2. **Only what is read is translated.** Lines kept by the per-language funding-term filter (verified-
   catalog §5, `_FUNDING_TERMS`) and their headings, never the whole page; every translation is cached
   by (line hash, source language, translator, version), so an unchanged line is never paid for twice.
3. **The translator is a measured, pinned component per language**, like a second reader: a changed
   translator or version re-opens that language's bars.

**Starting choice per language** (research, citations verified:
`.context/research/2026-10-03-line-translation-per-language.md`):

| Languages | First choice | Fallback | Cost per 10k characters |
|---|---|---|---|
| Azerbaijani, Kazakh, Georgian, Armenian, Serbian | Google Cloud Translation (NMT) | Azure AI Translator | ≈ $0.20 / ≈ $0.10 |
| Turkish | Google NMT | DeepSeek V4.1 Flash, literal prompt | ≈ $0.20 / ≈ $0.005 |
| Russian, EU languages, Arabic, Chinese, Japanese, Korean, Vietnamese | DeepSeek V4.1 Flash (Fireworks, thinking off), literal line-by-line prompt that forbids adding or dropping words and keeps negations, numbers and names | Google NMT | ≈ $0.005 / ≈ $0.20 |

Open-source translators were checked and mostly fail the licence test: NLLB-200, SeamlessM4T,
TowerInstruct/Tower+, Aya Expanse, COMET-Kiwi and xCOMET are non-commercial. MADLAD-400 and OPUS-MT
(Apache-2.0) are usable but weaker and are not defaults; MetricX-24 (Apache-2.0) can score a
translation without a reference and is a candidate line-quality flag for plan 1.

**What decides it** (plan 1, before any language ships English-only): ~100 real funding lines each in
Turkish, Azerbaijani and Russian, enriched so at least 40 per language carry a negation, an exclusion,
a payer clause or a condition. Each line is translated by Google NMT and by DeepSeek; Jev answers on
both; errors are compared with McNemar's test on the lines where they differ. The same run scores the
original-language arm and a **two-translation agreement** arm (a fact counts only when Jev answers the
same on both translations) — the research's top recommendation for the 1-in-100 target, measured here
rather than assumed. A Google Cloud key is needed (none exists in this environment).

**Cost.** For a page's funding lines (≈ 2–5k characters), DeepSeek ≈ 0.1–0.25¢ and Google ≈ 4–10¢.
Google is therefore used only where the measurement shows it is needed, and the line cache matters most
for those languages.

### 3.11 Dates, month-year spans and "exact or up to" — fixes from the data (2026-10-03)

Re-scored for $0 on session f7's v5 run (`.context/research/2026-10-03-dates-and-bounds-fixes.md`):

- **Date role.** In az/tr/ru/en/fr Jev picked the right role on 18 of 19 dates but was sure on only 10;
  the "15% coverage" headline was mostly one Korean table whose key lacked an "application period"
  answer. Fixes: dates are decided by the two-reader joint score (§3.3); code finds **date ranges** and
  asks once per range; code passes a **table column header** to Jev through a per-language cue table
  (context, never the decision); the option list gains `application_period` (a window).
- **Date finding.** The code finder, improved and with years/academic years sent to the intake finder,
  finds 208 of 211 key dates across 8 languages; `dateparser` 1.2.2 was tested and rejected (lower
  recall, many false hits). Numeric dates require day ≤ 31 and month ≤ 12 (Russian specialty codes).
- **Exact or up to.** 7 of Jev's 9 wrong up_to/at_least answers were ranges or approximations. Code
  records **`range` (min, max)** and **`approximately`** itself, verbatim; Jev's `bound` is asked only of
  single amounts, with the `{what, not_for, examples}` criteria for up_to and at_least.

## 4. The writing path: one writer client, identifiers masked by code

### 4.1 One client

One OpenRouter chat client for every prose or structured-JSON writer (letters, CV generation, CV
ingestion, evidence descriptions, storylines, topic phrases, search angles, explanations when wired).
It is the letter engine's "model seam" (its plan 2), built once here for all writers. Every call sends:

- `provider: {only: [<pinned hosts>], allow_fallbacks: false, require_parameters: true}`. Hosts are
  chosen on price and measured quality, **in any country, whether or not they retain data**: the owner
  kept the 2026-09-27 rule (any host, student data included, once masked) on 2026-10-03, after this
  design had proposed zero-retention hosts only. The protection for student text is the mask (§4.2),
  not the host.
- A pinned model id per writer role, from §5.
- A capped `max_tokens`, untrusted content labelled as data (the `extraction.py` reference pattern).

Outages go to another pinned host of the same model, then to the next *measured* model; never to an
untested one. Host, model and reasoning tokens are logged per call.

### 4.2 Masking: one seam, enforced at both clients

`mask_for_model(text, student)` (letter engine S1) replaces the student's name in every confirmed
transliteration, e-mail, phone, postal address, date of birth, ID numbers and referees' names, in
every text sent to any model. **Both** clients take a required `carries_student: bool`; with `True`
the text must have passed through the seam, or the call raises before any network request. One test asserts, for every call site in §2 that carries student data, that no identifier of
a seeded student reaches the request body (the shape of
`test_no_query_ever_carries_the_student`), and a second asserts that `carries_student=True` without
masking raises.

**CV ingestion is the hard case, and needs no exception.** Today the model reads the raw CV partly to
learn the student's name and contacts. It does not need to: the account already holds the name and
e-mail, and code finds phone numbers, e-mails and dates of birth by pattern. So ingestion masks the
account's name variants and every pattern-found identifier, then sends the rest. The IDENTITY facts
come from the account and from code, never from the model.

**Where the spellings come from, without a new form field** (owner: no added friction, 2026-10-03):
1. The name the student typed at sign-up, as the account already asks.
2. Variants generated by code: Azerbaijani/Turkish/Russian transliterations (x↔kh, ə↔a/e, ş↔sh,
   ç↔ch, ğ↔gh, ı↔i, Cyrillic↔Latin), case, initials ("O. Abdullayev"), and the grammatical endings
   Turkish and Azerbaijani attach to names ("Orxan'ın", "Abdullayevin").
3. Near-matches found by code in the student's own uploads: a token within a small edit distance of a
   known variant, after folding accents and script, joins the mask for that student.
4. A passport, when uploaded: its machine-readable zone is parsed by code (no model) and that spelling
   joins the mask; if it differs from the typed name, the student confirms it once.
5. A former name is asked about only when a document carries a surname matching none of the above.

**A spelling none of these finds can reach a host. The owner accepts that** (2026-10-03): the call is
neither blocked nor rerouted. The seam logs every capitalised token adjacent to a masked one as a
suspected spelling; a suspected spelling confirmed by a later upload or the passport joins the mask.

### 4.3 Sensitive topics

Chinese-hosted models filter Taiwan, Tibet, Xinjiang, Hong Kong and human-rights topics. The letter
engine routes such letters to a non-Chinese model (its S6). The same rule applies to every writer and
to the second reader: a refusal, a content-filter error or an empty answer is redone on the
non-Chinese route for writers, and is "unsure" for the second reader.

## 5. Which model, where (starting candidates; the harness decides)

Prices are OpenRouter endpoint data read 2026-09-28, per million tokens in / out; they change without
notice and plan 1 re-reads them. S = strict schema, L = logprobs, ZDR = on OpenRouter's
zero-retention list.

| Role | First candidate | Others measured | Why |
|---|---|---|---|
| Every closed judgement, stage one | Jev 1.13 ($0.042 / free) | — | Cheapest per input token of any option; returns a distribution over options natively. |
| Second reader | DeepSeek V4.1 Flash **on Fireworks** (ZDR; strict schema with logprobs, `top_logprobs` ≤ 5; prefix cache once warm; $0.30 / $1.20, ≈ $0.00006 per cached question, measured 2026-10-03), thinking off per request. Backup: Sail Research fp4 (correct and cached, logprobs on one call of two → vote mode). Ionstream, DigitalOcean and Together excluded after a confident wrong answer with thinking off; CoreWeave returned neither logprobs nor a cache hit | Qwen3.8-Flash (Alibaba only, $0.15 / $0.47, not ZDR: page text only; rate-limited upstream on both probes 2026-10-03, so a harness candidate only, never a production reader while it has one host) | Cheap, logprobs declared on at least one ZDR host, a different family from Jev's. **GLM-5.3-Flash is not a second-reader candidate**: every host probed (Fireworks, Together, Sail, Parasail) answered HTTP 400 "Reasoning is mandatory for this endpoint and cannot be disabled", and Z.ai's API returns no logprobs. |
| Letter writer | per letter engine S6 (GLM-5.3, then Kimi K3, DeepSeek V4 Pro) | its §8.3 bake-off | Governed there. |
| CV writer and ingestion | the letter bake-off's winner | OpenAI `OPENAI_EXTRACTION_MODEL` as control | Same writer seam; no separate bake-off. |
| Translation into English (§3.10) | per language: Google NMT for az/kk/ka/hy/sr/tr, DeepSeek V4.1 Flash for the rest | Azure; DeepSeek ↔ Google | Coverage of low-resource languages; cost for high-resource ones. |
| Short phrases (topic phrases, search angles) | DeepSeek V4.1 Flash, thinking off | GLM-5.3-Flash (thinking cannot be turned off, so measured with its reasoning tokens counted in the cost) | No student identifiers in the output; cheapest capable writer. |

Facts that bound these choices (research, 2026-09-28): on input price Jev is cheaper than every
non-promotional Chinese endpoint; Chinese models win only with prompt caching (DeepSeek cache hit
$0.003/M) or near-zero output; DeepSeek's own API offers JSON mode but not strict schema, doubles its
price in Chinese business hours and is not ZDR, so it is reached through a third-party host; DeepInfra
declares strict schema but no logprobs on these models; Groq and Cerebras host none of them. **No
current benchmark covers Turkish or Azerbaijani for any candidate** (MMLU-ProX omits Turkish; the one
Azerbaijani benchmark, TUMLU 2025, had Qwen2.5-72B 12 points behind GPT-4o), so our own key is the only
evidence that will exist.

Versions are pinned. A changed `served_model` on a Jev answer, or a changed model id on a host, stops
that question's `accept` bar from applying until the harness re-measures it.

## 6. The harness: one, for every decision

The verified-catalog §7 harness, the letter engine's S7.4 calibration sets and §8.3 bake-off, the
fetch-filter recall test (verified-catalog §5.4) and the CV-format eval (`docs/research/cv-format-eval.csv`)
become one package with one record format.

### 6.1 The key, built by models

For each item (a line, a sentence, a page, an organisation): a reader that is not the one on trial
answers; code compares with the trial reader; agreements enter the key; disagreements go to a strong
model asked only the disputed question; a random 10% of agreements also go to it, to measure errors
both readers share. No model grades its own family: when a Chinese model is on trial, the key's reader
and referee come from other companies. Examples used inside a question's criteria are never key rows
(the 48-row CV lesson).

### 6.2 What it measures, per question × wording × language × reader

Precision and recall on the key, the confidence-to-precision curve (from which `accept` and
`band_floor` are read), the second reader's lift inside Jev's band, cost per item, malformed and
refused answers, and for writers the letter engine's §8.3 measures. Negatives are counted: an item
that states nothing is scored like one that states something. Three more, from the 2026-10-03
research:

- **Precision given agreement inside Jev's band**, reported apart from overall precision. Agreement is
  not independence: a 350-model study found "models agree 60% of the time when both models err", and
  that larger models from distinct providers have highly correlated errors. The second reader earns
  its place only by this number.
- **Position bias:** every Choice is scored with its options in the shipped order and reversed (and
  shuffled for long lists); a question whose answer moves with order is reworded or kept as an
  order-swapped pair (§3.6).
- **Option-count strata** for candidate Choices (§3.4).
- **Tune on one half, score on the other.** Wordings, bars, modes and language arms are chosen on a
  random half of the key and reported on the rest (verified-catalog §7 carries the same rule, with a
  per-language page set of ~80 pages approved by the owner on 2026-10-03, Wilson intervals, the
  funding-term recall check and a proof measurement of zero wrong websites).

### 6.3 Targets

| Decision kind | Target precision at `accept` | Unsure means |
|---|---|---|
| A value shown to a student (amount, date, deadline role, who pays) | 0.99 (owner, 2026-10-03: at most 1 wrong in 100) | `not_stated` |
| Excluding a student or hiding an award (`excluded_*`, `discontinued`) | 0.99 | not excluded, not hidden |
| Labels shown on a card (covers, period, kind of body) | 0.99 | `not_stated` |
| Labels not shown to a student (rule kinds, organisation kind, routing) | 0.95 | undecided / next rung |
| Fetch-filter skip | recall: **zero** awards on skipped items | keep |
| Letter checks | per letter engine S7.4 | warning |

### 6.4 Size and cost

Built once: about 50 funding pages (verified-catalog §7), ~200 sentences per letter-check question
per language (letter engine S7.4), the 48 CV-format rows plus the requirement-reader page corpus,
~20 sites for the fetch filters, and every language that has students before it is trusted. Estimated
$3–6 in model calls and about $1 of fetch credits, once. In production, 1 decision in 20 is re-asked of
the key's reader (about 1¢ per hundred pages); a fall in agreement re-opens that question's bars.

## 7. The four votes, and when each goes

| Vote | Replaced by | Deleted when |
|---|---|---|
| `funding_judge.py` 3 readings + tie-break, and its Batch-API twin in `batch_reading.py` | the Jev funding reader (verified-catalog §5) through `decisions.ask` | the reader meets §6.3 on the 50-page key in every language with students |
| `derive.py` frontier judge (fallback since #159) | #159's rule grammar, already on Jev | the grammar meets the CV-format eval in every round of its live gate; also port draft PR #156's rule that a confident "not required" vetoes a Europass action, which #159 lacks |
| `research_fit/judge.py` 3 readings | Jev per sentence (letter engine S3.6) | letter engine plan 5's gate |
| `letter_verification.py` 2–3 readings, unanimous | Jev checks (letter engine S7) | letter engine plan 4's gate |

Agreement between readers survives only in the harness.

## 8. Every other call site

### 8.1 Judgements moving to `decisions.ask`

| Site | Today | After |
|---|---|---|
| `classify.py::FrontierClassifier` (kind of organisation) | luna, 1 per host | Jev Choice through the existing `HostClassifier` seam; page text, `record=True` |
| `tailoring.py::judge_remainder` (skill ↔ statement pairs) | luna | Jev Choices over the closed id lists; IDENTITY already dropped; `record=False` |
| `profile_cells.py::select_bucket` | luna | Jev Choice; target field and interests are student-derived, so masked and `record=False` |
| `mailbox/classify.py` | luna, 1 per e-mail | Jev Choice; the body is masked first; `record=False` |
| `apps/research/jev.py` provenance vetoes | its own client | `decisions.ask` (§3.1) |
| `portals/learn.py::learn_from_snapshot` | luna, value-free snapshot | unchanged until the glass-box extension work touches it |

`record=False` for anything student-derived is #159's rule: `DecisionRecord` is a shared catalogue
table, and nothing about a student may land in it.

### 8.2 The CV/letter requirement reader (requirement-reader session's findings, adopted)

Measured cost today per changed programme page: `extract_statements` 3 × luna ≈ 2¢; #159's Jev
grammar ≈ 0.6¢ (100 candidates × ~1,500 tokens); the frontier fallback 35–50¢ when no Jev key is set.
The three reads exist because a writing model *selects* a different subset of true sentences each
time (29–40 statements per read on FAU, no two identical). Jev's repeats are stable (vendor: std 0.01),
so one pass is enough once Jev does the choosing and code does the listing:

- code lists every `readable_text` line with its heading path;
- one Jev request set tags each line: is it a requirement; which kind; required or desired;
- code copies the line verbatim, and the heading path replaces the model-written 6-word label;
- the Europass check becomes three wordings inside one Jev request, not three readers.

Expected ≈ 1¢ per page. The OpenAI statement read and the Claude judge are deleted only after the
page-corpus gates pass on Jev. The second reader (§3.3) replaces the earlier idea of DeepSeek as a
per-language fallback.

### 8.3 Programme claims (`extraction.py::extract_claims`)

A writing model fills a large claims schema (money, dates, grades, nationality, admission regime)
from a page. It becomes the funding reader's shape: the funding reader's finders (amounts, dates,
places, requirements) find candidates, Jev picks roles, code copies. Claims the finders cannot cover
(grade-equivalence rules, admission regime) stay on the writer client, with `carries_student=False`
because the input is page text only, until the harness shows a Jev question set that meets §6.3. Planned last of the readers because no
production path reads its output beyond the discovery pipeline.

### 8.4 Writers

All move to §4's client with masking: `generation.py`, `ingestion.py` (§4.2), `evidence/extraction.py`,
`storyline.py`, `research_fit/anchors.py`, `angles.py`, and `funding/explanations.py` when it gets a
caller. Model per §5, chosen by the letter engine's bake-off; until a writer role passes, it stays on
its current OpenAI model, behind the new client and the masking seam (so the privacy fix ships first,
independent of any model change).

### 8.5 Document requirements: language, translation and legalisation

Under verified-only (§1), an award is shown only when its **document list** is verified, and a wrong
document list is one of the owner's three "never" errors. For an Azerbaijani applicant the list is
mostly about *which language, which kind of translation, and which stamp*
(`.context/research/2026-10-03-transcript-translation-rules-azerbaijan.md`): Italy wants Italian
"not into English" with an apostilled translation; Poland a sworn translator and never a notary;
Russia and Kazakhstan a notarised Russian/Kazakh translation and no apostille (CIS Minsk Convention);
uni-assist German or English by a sworn translator, attested by an Azerbaijani notary; Hungary, Japan,
China and Korea English; WES an independent translation, never the university's own English version.

**Each required document becomes a typed record, not a sentence**, filled by the requirement reader's
code-finds / Jev-picks pattern (§8.2) from the programme page or the portal it names:

| Field | Values |
|---|---|
| `document` | transcript, diploma, diploma_supplement, cv, motivation_letter, recommendation, language_certificate, passport, other |
| `accepted_languages` | ISO codes, or `original_any` |
| `translation` | `none_needed`, `any`, `certified`, `notarised`, `sworn`, `issuing_university`, `not_stated` |
| `translator_location` | `any`, `destination_country`, `applicant_country`, `not_stated` (Kazakhstan: notarised inside Kazakhstan) |
| `legalisation` | `none`, `apostille`, `consular`, `not_stated` |
| `original_also` | yes / no / not_stated — must the original be uploaded beside the translation |
| `stage` | `application`, `admission`, `enrolment`, `visa`, `not_stated` (Türkiye Scholarships: Turkish translation only at contract and enrolment) |

Each field is one closed question per §3.7 (a Choice with `not_stated`, or a Noul per language), asked
over the sentences code found near the document's name. A field left `not_stated` on a required
document fails verification, and the award is not shown — exactly the verified-only rule.

**Delegated rules** (owner, 2026-10-03): when the programme page names a portal or funder ("via
uni-assist", "through the Stipendium Hungaricum portal"), that body's official rule page fills the
fields the programme page leaves `not_stated`, and the record cites both pages. A programme's own
statement always wins over the portal's.

**How to get it, in Azerbaijan** — a code table, not a model, shown beside each requirement:
- a notarised translation: an Azerbaijani notary; for uni-assist the notary must also attest the
  translator;
- an apostille on the diploma: the Ministry of Foreign Affairs; on a notarised translation: the
  Ministry of Justice;
- no apostille for Russia and Kazakhstan (Minsk Convention); Germany accepts apostilles from Azerbaijan
  since 16 March 2026;
- the diploma and supplement themselves: Azerbaijani by default, English on the graduate's application
  (Cabinet of Ministers decision No. 1, 7 January 2026, clause 2.5 — confirmed in the PDF's text).
Each row carries its source link and the date it was read; a row older than a year is re-read before it
is shown.

## 9. Cost (estimates; the harness replaces each with a measurement)

| Unit | Today | After |
|---|---|---|
| Translating one page's funding lines (§3.10) | none | ≈ 0.1–0.25¢ (DeepSeek languages) or ≈ 4–10¢ (Google languages), once per changed line thanks to the line cache |
| Reading one funding page | ≈ 35¢ (3 frontier readings) | ≈ 0.1–0.25¢ Jev (≈ 270 tokens per request + ≈ 20–46 per question, measured) + second reader on the uncertain ~10–20% of questions at ≈ 0.006¢ each once the page is cached (Fireworks, measured) |
| One programme page's CV/letter rules | ≈ 2.6¢ (36–50¢ on the fallback) | ≈ 1¢ |
| One letter | per letter engine §5 | ≈ 5–10¢, mostly research |
| One organisation classified | 1 luna call | < 0.01¢ |
| Building the harness | none | ≈ $4–7 once |

The second-reader figure assumes a 6k-token page cached once per page and 5-token answers; it is the
least certain number here and plan 1 measures it first.

## 10. Build order (each its own implementation plan)

1. **The harness (§6)** — owner, 2026-10-03: the main candidate is **two readers, Jev + DeepSeek V4 Pro**
   (the frontier DeepSeek; V4.1 Flash as the cheaper comparison), with a **third reader only as a
   fallback** if two readers miss the 1-in-100 bar or keep too few facts. It measures, per question and
   language: code evidence gates, per-question bars, the section heading given with each line, a fact
   stated twice, order-swapped pairs, and tune-on-half / score-on-half — on ≈ 1,500 funding lines
   (enough for ~300 confirmed "yes" facts per half). Also: the shared key format, the model-built key, the
   CV-format and requirement-reader corpora, the fetch-filter recall set, re-measured prices, a large
   Jev request to settle the 32k-vs-64k context question, and per-host probes of the second reader
   (logprobs together with strict schema; `cached_tokens` on a page's second call; thinking off). Everything after is scored by it.
2. **The two clients (§3.1, §3.3, §4)** — fold `jev.py` into `decisions.ask`; the second-reader stage
   and the per-question mode table; the writer client with host policy; `mask_for_model` and its two
   tests; every student-data call site in §2 moved behind the seam on its *current* model. This is
   the letter engine's plan 2, built once.
3. **The Jev funding reader** (verified-catalog §5) and the deletion of `funding_judge.py`'s vote. Also
   in this plan (agreed with the verified-catalog session, 2026-10-03): the per-language funding-word
   table replacing `_FUNDING_TERMS` (9 callers); `target_level` and the LOAN exclusion; pointer names as
   a reader output; eligibility place candidates from every line of a funding section; the writer of
   `FundingOpportunity.served` (`_served`) with a per-value record of which readers agreed; retiring
   `unconfirmed` (a blanked disputed value plus a caveat) on the student path; the serve gate accepting
   a social-media post URL only when it matches a `SocialAccount` of the holder; and porting
   `VerifyDueCyclesRule`'s two-model cycle verifier to Jev (it ships disabled today).
4. **The requirement reader, option A (§8.2)**, the Europass veto port from #156, and the deletion of
   the frontier fallback and the 3-read union.
5. **Small judgements to Jev (§8.1)**.
6. **Programme claims (§8.3)**.

Letters follow the letter engine's own build order, using plan 2's clients.

## 11. Open questions and risks

- **Measured 2026-10-03 on 443 real lines in az/tr/ru/en**
  (`.context/research/2026-10-03-settle-second-reader-language-translation.md`): Jev at ≥ 0.95 is almost
  never wrong but keeps only 29% of true "yes" facts; Jev ≥ 0.8 with DeepSeek ≥ 0.95 agreeing kept 45%
  at 52/53 right; DeepSeek alone was nearly as good as the pair; no language failed outright (the
  weakness is recall everywhere); translating first with DeepSeek changed almost nothing. No policy is
  yet *shown* to reach 1 in 100 — that needs ~300 "yes" facts with no error. Recall, not precision, is
  the binding constraint under verified-only.
- **Version 2, same lines, sharper questions** (`.context/research/2026-10-03-settle-v2-sharper-questions-and-ladder.md`):
  Jev ≥ 0.8 with DeepSeek ≥ 0.95 kept 59% of "yes" facts with no error; a **third reader** (Gemini 3.5
  Flash) asked only on the ~26% of items the two cheap readers left unsettled, and counted only as a
  confirming vote, raised that to 74% at 98.3%. Russian is where the cheap pair fails (23% kept); the
  third reader lifted it to 62% with no error. Plan 1 therefore measures a **three-step ladder**: Jev
  and DeepSeek on everything, a third reader (a stronger family, chosen by measurement) on the unsettled
  items, accepting a fact only when the third reader confirms a cheap reader's lean.
- **The second reader's value beyond these runs is still to be confirmed** at plan 1's scale. If the harness shows it adds no precision inside Jev's
  band for most questions, the mode table ends mostly `jev` and this design reduces to Jev-only with a
  measured exception list. That is an acceptable outcome, not a failure.
- **Jev outside English is unmeasured** by anyone on our languages; the vendor says it is weaker. The
  first numbers come from plan 1.
- **Corrected 2026-10-03:** the "≈ 300 tokens per question" figure was one call's fixed overhead.
  Measured over 1/5/20 questions it is ≈ 270 per request plus ≈ 20–46 per question (§3.2). The live
  limit is now the 32k context, not cost.
- **Second-reader premises, probed 2026-10-03 on one page:** logprobs with strict schema and a warm
  prefix cache both work on Fireworks; host choice changes answers (§3.3). One page is not a rate, so
  plan 1 repeats the probe across the key before any second-reader number is trusted.
- **Thinking off may cost accuracy on the hosts that remain.** Reasoning `low` fixed the wrong host at
  ≈ 5× the cost per question. The harness measures each triple with thinking off and at `low`, and the
  mode table may choose `low` for a question where the lift is worth it.
- **Cross-family agreement may add little**, because strong models' errors correlate (§6.2). The
  harness's precision-given-agreement number decides each question's mode.
- **A name spelling the mask does not know can reach a host.** Accepted by the owner (§4.2); plan 2
  still reports the suspected-spelling rate on the owner's own CV and synthetic profiles, so the
  variant rules improve.
- **TypeSafe's subprocessor update of 2026-10-03** (adds Nebius and CoreWeave) opens a 15-day objection
  window; nothing here depends on objecting.
- **Anthropic and Tavily high-risk clauses** (CLAUDE.md) are unaffected or eased: no Claude call
  remains on a student-facing decision path once §7 completes.
