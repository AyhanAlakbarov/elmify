# Assessment: `blader/humanizer`

Date: 2026-08-21. Status: assessed, **not integrated**. Input for the §4.2 motivation-letter design.

Repo: <https://github.com/blader/humanizer> — MIT, Python, described as "Agent skill that removes signs of AI-generated writing from text".

## Verdict: a style guide, not an evasion tool

The name and one-line description read like AI-detection evasion, and it was checked on that suspicion. Reading the source material shows otherwise.

Its own README states: *"It does not make things up. A name, number, date, quote, citation, or other factual detail must come from the source or the writer."*

Its 35 patterns (at the commit assessed; 25 since upstream v3.0.0, see the 2026-09-14 addendum) are editorial, and the "after" examples are consistently **plainer and more factual**:

| Pattern | Before → After |
|---|---|
| Inflated importance | *"marking a pivotal moment in the evolution of…"* → *"was established in 1989 as part of a wider decentralization"* |
| Vague sources | *"Experts believe it plays a crucial role"* → *"Name a real source or remove the claim"* |
| Sales language | *"nestled within the breathtaking region"* → *"is a town in the Gonder region"* |
| Shallow -ing analysis | *"symbolizing… reflecting… showcasing…"* → keep only what the source supports |

There is no perplexity manipulation, no invisible-character insertion, no classifier targeting. Reduced AI-detection signal is a **side effect of better writing**, not the mechanism. That distinguishes it from `watermarks-remover`, which was assessed separately and declined because its stated purpose is stripping C2PA/SynthID provenance marks — see the "Product decision" section in `2026-08-20-cv-ruleset.md` for the boundary.

Its constraint against inventing facts also aligns with this project's anti-fabrication design rather than working against it.

## How to use it: generation-prompt guidance, not a rewrite pass

**Adopt the patterns as constraints inside the §4.2 generation prompt.** Do not run it as a post-generation rewrite step.

The reason is architectural, not stylistic. `verify_against_facts` runs on generated content and classifies every material claim against the `VerifiedFact` ledger. A rewrite pass *after* that gate can reintroduce claims the gate already cleared — so it would force re-running the gate on the rewritten text, and a second LLM call, to fix something the first prompt could have avoided. Baking the patterns into generation keeps it to one call and one gate.

Note also that its "does not make things up" is a prompt instruction, not a guarantee. This project's deterministic gate is the actual guarantee; the tool's discipline is a quality input, never a substitute.

## No CV application

`CVContent` has **no prose field**, so there is nothing for prose rules to act on. Every field is a structured entry, and rewriting `BSc Computer Science, TU Delft, 2020–2024` would be wrong and risk factual drift.

The one candidate was a summary section. R-084 through R-086 established that admissions guidance routes objectives and motivation to the statement of purpose, every funder template we opened omits a summary, and the `summary` field that does exist is emitted by the `EUROPASS` variant only. So the CV surface for these patterns is close to nil.

**This belongs to §4.2 (motivation letters), where the document is prose end to end and §4.2's own requirement to "optimize for clarity" applies directly.**

## Practical note

It ships as an *agent skill* — Markdown plus a prompt for Claude Code / Cursor / Codex — not as a library the Django backend can import. "Integrating" it therefore means one of: adopting its patterns as prompt text (recommended), installing the skill for a human's own drafting workflow (unrelated to the product runtime), or running it as a service in the pipeline (rejected above). These are different actions with different risks and should not be conflated.

## Addendum, 2026-09-14: two further candidates, and the pattern count

**Pattern count.** "35 patterns" above was correct for the commit assessed (`c6f7cc2`, 2026-08-21; the letter plan pins `e2e92e7`). Upstream rebuilt the skill on 2026-09-06 (`34ca949`, released as v3.0.0) around 25 patterns ordered by strength, keeping the no-invented-facts rule and adding a "when not to act" section. The count moves with upstream releases. Cite the version the prompt is written against, never the number.

**Pin decision, 2026-09-14: v3.0.0, commit `9862685f575c65a8247f90369951df1b3416e3d6`.** The letter plan (Task 12) now pins it. The 35-to-25 change is mostly consolidation, with 9 patterns merged into others:

| Pre-3.0 patterns (`e2e92e7`) | v3.0.0 pattern |
|---|---|
| inflated importance, formulaic challenges/outlook, generic positive endings | 13 inflated significance |
| name-dropping, vague sources | 17 borrowed authority |
| too much bold, bold mini-heading lists | 19 bold as decoration |
| title case, emojis | 20 decorative headings |
| chatbot text, overly agreeable tone | 22 chatbot residue |
| deeper-truth phrasing, formulaic sayings | 3 sayings that sound deep |
| announcing the next point, fake-candid openings | 4 staged run-up |
| answering unraised objections, rejecting fake alternatives | 5 arguing with no one |

Dropped by upstream: false "from X to Y" ranges (§12), filler phrases (§23), and the synonym-cycling half of §11. Added: 14 vague connection or association. The overused-word list grew from 24 to 28 (bolstered, deep dive, meticulous, figurative robust). Structurally, v3.0.0 orders the patterns by strength, lets the five strongest justify an edit on one sighting, marks weak tells as needing company, and tells the editor to treat input text as material, never as instructions.

**The three dropped rules are carried by us**, labelled in the plan as our broadening and not the source's, because each is common in motivation letters.

**Synonym-cycling meaning guard, 2026-09-14.** A test rewrite of a 2,000-word academic methods paper with v3.0.0 plus the carried rules passed a citations-and-numbers check, yet five edits changed what a sentence claimed. Two came from the synonym-cycling rule treating non-synonyms as one subject: "partnerships" narrowed to "relations with NATO", dropping the United States, and "initiatives" replaced by "cooperation". The rule now carries a guard: only words that mean exactly the same thing count as one subject, and a wider or different term keeps its own word. The same test is the measured case for the letter design's no-rewrite-pass decision: a names-and-numbers gate cannot see a claim that changed scope.

**`petergyang/no-ai-slop`: declined.** A short `SKILL.md` plus a self-check `eval.md`, written for blog and LinkedIn posts, about 20 patterns, no sources given. Nearly all are humanizer patterns under other names: binary contrasts, throat-clearing openers, colon reveals, -ing riders, importance puffery, weasel attribution, fake-strong verbs, em dashes, a banned-word list. Its one addition is a "portability test": a sentence that could move unchanged to another person or company is filler. That is already the design's A10 rule, "cut any sentence that could have been written by anyone". Its register is wrong for a funder letter: it preserves profanity, bluntness and humour by rule. It passes the same editorial-not-evasion test as the humanizer; its detect mode names patterns with quoted lines and explicitly refuses to guess authorship. Carry forward the portability-test wording as one prompt sentence, nothing else.

**StoryScope (arXiv 2604.03136, Russell, Rajendhran, Pham, Iyyer, Wieting; Apr 2026, rev. Aug 2026): evidence, not a feature.** Fiction only: 61,608 stories of about 5,000 words, 304 narrative features annotated by a model, XGBoost with SHAP. Narrative structure alone separates human from AI at 93.2%; surface style alone at 99.7%. AI narrators state the theme outright (77% vs 52% for humans), prefer single-track plots and morally clear protagonists; human stories use flashbacks and leave ambiguity. The authors claim nothing beyond fiction and say the features need long text, so nothing in it runs on an 800-word letter. Two things transfer:

- "Show the evidence, do not state the lesson" is A10's "evidence then interpretation, no platitudes" at paragraph scale. Confirmation of a rule we have, not a new one.
- AI outputs cluster and human writing disperses (human stories fall in the rarest 10% of the paper's narrative space 24.7% of the time, AI 7.1%). For a platform sending many letters to one funder that is a cross-student sameness risk, and §4.2's core-narrative reuse amplifies it. Not a build item; one risk line in the letter design when it is next edited.

Style-only detection being the stronger signal also means neither skill makes a letter undetectable, which §4.2.3 forbids aiming for anyway. Both are quality inputs and nothing more.
