# Six proposed Jev pipeline improvements: what TypeSafe's docs and the literature say

Date: 2026-10-03. Input to the measurement-harness plan (spec `docs/superpowers/specs/2026-10-03-one-decision-engine-design.md` §3).
Builds on `.context/research/2026-10-03-jev-question-design.md` (the "notes") and `2026-10-03-settle-v2-sharper-questions-and-ladder.md` (the "v2 run"), and does not repeat what they establish.

## Scope and method

Sub-questions:
1. Does TypeSafe document code-side evidence checks gating a model "yes", and what does the weak-supervision literature say?
2. Do TypeSafe's docs back per-question thresholds, and how many labelled examples does a 1% error target need?
3. Do the docs back adding a line's section heading to the state?
4. Is a fact stated twice stronger evidence (TypeSafe; truth discovery)?
5. What exactly does TypeSafe recommend against first-option bias, and what does permutation debiasing cost?
6. Is tune-on-one-half, score-on-the-other standard, and what sample size does it need?
7. Anything else in the docs (Score, `focus`, multi-question, self-consistency, criteria-always) that changes how we ask.

Sources:
- **TypeSafe docs**, fetched live as `.md` with scrapling `get`. New this round: Patterns, Speculative fan-out, Confidence-gated routing, Composite scoring, System One, Score, State, Noul, jev-1.13 jaggedness (re-read), and the cookbooks on citation check, entity alignment, structure recovery, re-ranking, hierarchical classification and autoresearch. Also TypeSafe's agent `SKILL.md`.
- **Papers**, found with Exa (four searches: PriDe, Snorkel, selective classification, truth discovery and distractibility) and one Brave search (rule of three). Abstracts were then fetched from arxiv.org, jmlr.org and Wikipedia with scrapling.
- **Not used:** Context7 (no library question), Tavily (not needed).
- **Blocked:** PubMed and PMC returned empty pages (bot check). The rule-of-three citation therefore comes from Wikipedia, a secondary source; the arithmetic is standard.

---

## 1. Code "evidence gates" (a yes counts only if code finds a date, degree word or country word)

**TypeSafe docs: strongly supported in principle, but the docs never show a gate being used to lower the model's bar.**
- The docs' standard workflow combines model answers with deterministic checks in code.[^1] Known rules, calculations and exact lookups stay in code.[^2] "Asking the model something code can compute exactly" is listed as an anti-pattern.[^8]
- The citation-check cookbook is the closest pattern:
  - A plain string match runs first, and a quote it cannot find is marked fabricated with no model call.[^3]
  - The model then reads the quote's section to judge support.[^21]
  - Note the direction: there, code *vetoes*. It never *licenses* a model yes at a lower bar.
- The structure-recovery cookbook is the strongest precedent for what we want:
  - Code reads direct evidence (blank lines, markers). The model gets only the questions code cannot answer.[^4]
  - **The model's threshold depends on a fact code reads.** The join bar is 0.2 after a line with no closing punctuation and 0.5 after one with closing punctuation: "No single threshold works for both cases; once code checks the punctuation first, the two bands separate."[^5]
- Entity alignment keeps the numeric field out of the model entirely.[^7]

**Literature.**
- Snorkel-style weak supervision treats heuristics as noisy labellers "which can have unknown accuracies and correlations".[^9] The modelling lesson that transfers: a regex is a fallible signal with its own error rate and its own correlation with the model, not ground truth.
- **Unverified:** no paper fetched here measures "regex gate plus lowered LLM bar" on our kind of task.

**What this means for us** (my reasoning):
- A gate stops only one kind of false yes: the line that states no such thing at all. It does not stop a line that has a date which is not the deadline ("results announced 1 March"). The gate's errors and the model's errors are therefore correlated on exactly the hard lines.
- In weak languages a gate can also cut recall: Azerbaijani or Russian date formats, or a country written as an adjective.

**Verdict: adopt with change.**
- Use the structure-recovery shape: **two thresholds per question, chosen by whether code found evidence**, rather than a hard AND gate.
- Measure gate recall per language on the dev half before relying on it.
- Lower the evidence-present bar only where precision on the held-out half still holds.

## 2. Per-question thresholds instead of one bar

**TypeSafe docs: explicitly recommended.**
- The confidence page says to set the threshold per question.[^11] The Noul page ties it to the cost of being wrong.[^12] Raise it when a false yes is expensive.[^50]
- The confidence-routing pattern gives each action its own threshold above a common floor.[^10] The fan-out example uses different Noul cut-offs per question in one code path.
- The skill says thresholds are evaluated on the user's data and consequences.[^13]
- **Alternative the docs offer:** a Score whose middle level *is* the review outcome. Entity alignment routes on the nearest level with "no threshold constant anywhere in this file".[^14] A Choice would lose the ordering of the three outcomes.[^41]

**Literature.**
- Selective classification picks a rejection threshold on a labelled validation set so that the error of accepted answers stays below a user-set level with high probability.[^15]
- **Sample size.** With zero errors in n trials, 3/n is the 95% upper bound. So 300 accepted "yes" with no error is needed to claim under 1 in 100.[^16]
  - My arithmetic (one-sided Clopper–Pearson): with 1 error, about 475 accepted; with 2 errors, about 630.
- Tuning many thresholds on a small sample over-fits the selection criterion, and the effect "can be surprisingly large".[^17]

**What this means for us** (my arithmetic):
- The v2 run has 203 "yes" facts across eight questions, about 25 per question.
- No single question's threshold can be certified at 1% on this set. Per-question thresholds fitted to about 25 positives each will over-fit.

**Verdict: adopt with change.**
- Use one threshold per **risk tier**, not per question:
  - deadline, eligibility and documents (the student-facing "never" errors);
  - everything else.
- Pick each tier's threshold with cross-validation on the dev half, and certify each tier pooled on the test half against the 300/475/630 counts.
- Allow a per-question override only once that question alone has about 300 accepted on the test half.
- For three-way "yes / unclear / no" questions, test a 3-level Score against Noul plus band.

## 3. Giving each line its section heading (or heading path)

**TypeSafe docs: supported, as named, relevant context.**
- The state should hold related information when the decision needs it.[^18] Each question needs enough relevant state: "source text, identities, relationships, policies, and current facts".[^19]
- The citation check judges a quote by its surrounding section, not the quote alone.[^21]
- The counter-pressure is documented too: unrelated detail is a distractor.[^20] So a heading path (a few tokens, directly relevant) is in-bounds. The full page is not.

**Literature.**
- Sentence classification "requires understanding sentences in context of the document"; contextual models beat isolated-sentence ones.[^22]
- Irrelevant context sharply lowers LLM accuracy.[^23]
- **Unverified (PDF not fetched):** Shi et al. report that on-topic distractors with high lexical overlap hurt most. A generic heading such as "Scholarship" or "Funding" is exactly that kind of on-topic text.

**Verdict: adopt with change.**
- Put the heading path in its own named key, for example `{"section": ["Funding", "Deadlines"], "line": "..."}`, and point the question at `line` with a backticked path, so the heading is context and not the thing judged.
- A/B it on the dev half per question. Watch for headings that pull every line under them to "yes", for example a line under "Deadlines" that states no date.
- Translate the heading with the line (spec §3.10).

## 4. A fact stated twice (two pages, or two places) counts as stronger evidence

**TypeSafe docs: nothing found.** No page fetched discusses combining agreeing evidence across states. **Unverified.**

**Literature: only if the sources are independent.**
- Truth discovery that assumes independence takes repeated values as more likely true. The survey warns that observations from positively correlated sources "should not increase the belief that they are true".[^25]
- Copy detection fails when sources copy a *good* source.[^26] So agreement cannot even be used to detect dependence reliably.
- Snorkel likewise models correlated heuristics rather than counting them twice.[^9]

**What this means for us:** scholarship pages copy each other. An aggregator restates the funder; a faculty page restates the university's central page; the same template repeats a deadline in a header and a table.

**Verdict: adopt with change.**
- Count a second statement as corroboration only when it is on a **different owning domain or organisation** and is **not a verbatim copy** (compare normalised text in code).
- Use it to raise a borderline fact over the bar, never to override a contradicting statement. A contradiction stays a review case.
- A fact repeated on the same page counts once.

## 5. Order-swapped Choice pairs against Jev's first-option bias

**TypeSafe docs.**
- The exact recommendation: Jev leans toward the first option, and the fix given is to "reorder the options to double check that the answer stays consistent".[^27] This is a consistency check, not a debiasing recipe.
- The hierarchical cookbook treats option order as part of the question: options are asked in the order they appear, and that order is "part of the question, not presentation".[^31]

**Literature.**
- PriDe: the standard debiasing averages predictions over option permutations. Full permutation costs n!, so cyclic permutation (×n) is the practical baseline.[^30]
- PriDe itself estimates the bias prior by permuting on a small sample and applies it to the rest.[^29]
- PriDe attributes most LLM selection bias to option-ID tokens (A/B/C/D) and calls position bias "less regular" and model-dependent.[^49] Jev's options are named keys, so PriDe's token-prior correction does not transfer directly.

**What this means for us** (my reasoning from spec §3.2's cost measurement):
- Questions in one request are independent.[^32] Jev bills the state once, at about 20–46 tokens per extra question.
- So a swapped duplicate of a 2–3-option Choice in the **same request** costs a few tokens. Cyclic permutation is effectively free, and PriDe's sampling shortcut buys nothing.

**Verdict: adopt.**
- For every Choice with 2–4 options, ask the cyclic rotations in the same request.
- Average the probabilities per option, or require the top option to agree, and send disagreement to the second reader.
- First measure on the dev half whether the bias shows up on our questions at all ("in some cases" per the docs). Drop the rotations for questions where it never moves the answer.
- Keep `none` / `not_stated` last only if the measurement shows its position does not matter. Otherwise rotate it as well.

## 6. Tune on one half, score on the other (or cross-validate); labelled examples needed

**TypeSafe docs: this is the docs' own practice.**
- The autoresearch cookbook keeps 800 of 2,000 rows untouched, because "Scoring on the same rows would mostly measure how well the loop fitted itself to them".[^33] It recommends "a final test set untouched by both feature discovery and model selection"[^34] and "grouped splits when related rows must stay together".[^35] It also says to check stability across seeds and data slices.[^44]
- The Score page: test revised descriptions on separate inputs before keeping them.[^36]

**Literature.**
- Selecting prompts on the evaluation data overestimates real performance.[^37] Over-fitting the selection criterion is comparable in size to real differences between methods.[^17]

**Sample size for a 1% target.**
- At least 300 accepted "yes" with 0 errors in the **test** half, pooled over the tier being certified.[^16] About 475 with 1 error and 630 with 2 (my arithmetic).
- My arithmetic for the v2 run: policy C accepted 117 of 363 lines (about 0.32 accepted per line). Reaching 300 accepted in the test half therefore needs about 930 test lines, or about 1,900 labelled lines with the dev half. That is about 4× the current 443.

**Verdict: adopt with change.**
- **Split by page, not by line,** so lines from one page never sit on both sides.[^35]
- Stratify the split by language.
- Use k-fold on the dev half for choosing wordings and thresholds. Score the test half once.
- Size the labelled set from the 300/475/630 rule per certified tier, and per language if each language must pass on its own (spec §3.4).

---

## 7. Other doc guidance not in the notes

- **Criteria: always, or only when needed?**
  - The Noul page's default is instruction-only: "The instruction is enough for most Nouls". It says to test with and without criteria and keep the better one.[^38]
  - The jev-1.13 jaggedness page, which is version-specific and reviewed 2026-10-02, says for literal reading: "Put boundary cases in the criteria."[^39]
  - So the docs **do not contradict** our always-criteria result. Our measurement is the docs' own test-and-keep procedure, and jev-1.13's literalness is the documented reason it wins.
  - Caveat: the v2 run tuned wordings on the data it scored. Re-confirm on the held-out half.
  - Criteria examples steer only when they resemble real inputs, and higher confidence does not prove a wording is better.[^40]
- **Score primitive.**
  - Each level is judged on its own, without seeing its number or neighbours.[^42]
  - The middle-level-as-review design (§2) is the one Score use relevant to us. Do not interpolate score values (notes §6).
- **Multi-question requests.**
  - Put every question needed about one state in one request, including speculative ones.[^48]
  - Questions cannot see each other's answers. So a premise such as "if this line is about a deadline" must be written into each question.[^43]
- **Self-consistency.**
  - For LLMs, sampling plus majority vote reduces distractibility.[^47] Jev's repeat variance is tiny (mean SD 0.0102)[^46], so repeated identical calls add almost nothing.
  - The useful "self-consistency" for Jev is variation of *form*: option rotations (§5) and two independent wordings. **Unverified:** no TypeSafe page measures paraphrase ensembles.
- **`focus` / `note`.** Nothing new beyond the notes. They are non-reserved field names the model reads as labels.
- **Narrowest deciding fact.** The structure-recovery cookbook measured that the broad wording ("same paragraph") failed where the narrow one ("picks up mid-sentence") worked: "the question should name the narrowest fact that decides it".[^6] This backs the v2 run's sharper questions.

## Summary table

| # | Improvement | TypeSafe docs say | Literature says | Verdict | Change |
|---|---|---|---|---|---|
| 1 | Code evidence gates, lower model bar | Deterministic checks in code[^1][^2]. Code vetoes before the model[^3]. Threshold conditioned on a code-read fact[^5] | Heuristics are noisy, correlated signals[^9]. No direct measurement found | **Adopt with change** | Two thresholds per question (evidence found / not found) instead of a hard AND gate. Measure gate recall per language. Lower the bar only where held-out precision holds |
| 2 | Per-question thresholds | Explicitly per question, by cost of error[^10][^11][^12]. A Score middle level can replace a fitted band[^14] | Risk-controlled threshold from a labelled set[^15]. 300 accepted with 0 errors for <1%[^16]. Selection over-fits[^17] | **Adopt with change** | One threshold per risk tier (deadline/eligibility/documents vs rest), pooled certification. Per-question override only after about 300 test-half accepts |
| 3 | Section heading in state | Related context belongs in state[^18][^19]. Citation check reads the section[^21]. Distractors hurt[^20] | Context helps sentence classification[^22]. Irrelevant context hurts[^23] | **Adopt with change** | Heading path in its own key, question points at `line`. A/B per question. Watch for generic headings pulling lines to yes |
| 4 | Stated twice = stronger | Nothing found (**Unverified**) | Only independent sources add belief[^25]. Copying of good sources is hard to detect[^26] | **Adopt with change** | Count only across different owning domains and non-verbatim text. Raise borderline facts only, never override a contradiction. Same-page repeats count once |
| 5 | Order-swapped Choice pairs | Reorder to check consistency[^27]. Order is part of the question[^31] | Cyclic permutation ×n is the practical debias[^30]. PriDe estimates a prior[^29]. Its token-bias model does not fit named options[^49] | **Adopt** | All cyclic rotations in the same request (a few tokens each). Average or require agreement, disagreement to the second reader. Drop where the dev half shows no order effect |
| 6 | Tune on half, score on other | Untouched final test set; grouped splits[^33][^34][^35]. Test revisions on separate inputs[^36] | Selecting on eval data overestimates[^37][^17]. 3/n rule[^16] | **Adopt with change** | Split by page and stratify by language. k-fold on dev, test scored once. About 1,900 labelled lines (about 4× today) for one pooled tier at 1% |

## Open questions

- Whether Jev's first-option lean appears on our 2–4-option Choices at all. Measure on the dev half before paying for rotations everywhere.
- Gate recall for Azerbaijani, Turkish and Russian date, degree and country expressions. No source covers it.
- Whether a heading path helps or hurts per question. No TypeSafe page measures it.
- How to identify "independent" pages robustly (same owner on two domains, mirrored PDFs). The literature says agreement alone cannot detect copying of a good source.[^26]
- Whether each language must separately clear 300 accepts, which would multiply the labelling need about fourfold. That is an owner decision under spec §3.4.
- The exact Shi et al. finding on lexical-overlap distractors (PDF not fetched).

## Sources

[^1]: https://docs.typesafe.ai/concepts/system-one.md "Combine the answers with deterministic checks in code, then route the case for action or review."
[^2]: https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md "Keep known rules, calculations, exact lookups, and execution in code."
[^3]: https://docs.typesafe.ai/cookbooks/citation_check.md "A quote that is not in the source is fabricated, and no model is needed to find that out."
[^4]: https://docs.typesafe.ai/cookbooks/autoformat.md "The model gets only the questions code cannot answer from the text."
[^5]: https://docs.typesafe.ai/cookbooks/autoformat.md "No single threshold works for both cases; once code checks the punctuation first, the two bands separate."
[^6]: https://docs.typesafe.ai/cookbooks/autoformat.md "When a judgment call feeds a threshold, the question should name the narrowest fact that decides it."
[^7]: https://docs.typesafe.ai/cookbooks/entity_alignment.md "Alcohol content gets none, because comparing two numbers is arithmetic; compute it in code if you want it."
[^8]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "Asking the model something code can compute exactly."
[^9]: https://arxiv.org/abs/1711.10160 "users write labeling functions that express arbitrary heuristics, which can have unknown accuracies and correlations"
[^10]: https://docs.typesafe.ai/patterns/confidence-routing.md "Above that floor, each action type has its own threshold based on the consequences of acting on a wrong classification."
[^11]: https://docs.typesafe.ai/confidence.md "since 0.5 is a weak answer among two options and a strong one among ten, so set its threshold per question"
[^12]: https://docs.typesafe.ai/primitives/noul.md "Where to set the threshold depends on the cost of being wrong."
[^13]: https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md "Use probabilities and confidence to guide behavior, with thresholds evaluated on the user's data and consequences."
[^14]: https://docs.typesafe.ai/cookbooks/entity_alignment.md "There is no threshold constant anywhere in this file."
[^15]: https://arxiv.org/abs/1705.08500 "Our method allows a user to set a desired risk level."
[^16]: https://en.wikipedia.org/wiki/Rule_of_three_(statistics) "If 300 parachutes are randomly tested and all open successfully, then it is concluded with 95% confidence that fewer than 1 in 100 parachutes with the same characteristics (3/300) will fail."
[^17]: https://www.jmlr.org/papers/v11/cawley10a.html "the degradation in performance due to over-fitting the model selection criterion can be surprisingly large"
[^18]: https://docs.typesafe.ai/concepts/state.md "Put related information together when the decision requires comparing those parts."
[^19]: https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md "to answer: source text, identities, relationships, policies, and current facts"
[^20]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "Unrelated detail acts as a distractor, and a large state makes it harder to tell which part of the input produced a wrong answer."
[^21]: https://docs.typesafe.ai/cookbooks/citation_check.md "Deciding that takes the quote's context, the section step 1 found."
[^22]: https://arxiv.org/abs/1909.04054 "a task that requires understanding sentences in context of the document"
[^23]: https://arxiv.org/abs/2302.00093 "find that the model performance is dramatically decreased when irrelevant information is included"
[^25]: https://ar5iv.labs.arxiv.org/html/1505.02463 "the observations from positively correlated sources should not increase the belief that they are true"
[^26]: https://ar5iv.labs.arxiv.org/html/1505.02463 "However, this principle becomes ineffective when some sources copy information from a good source."
[^27]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "reorder the options to double check that the answer stays consistent"
[^29]: https://arxiv.org/abs/2309.03882 "PriDe first estimates the prior by permutating option contents on a small number of test samples"
[^30]: https://arxiv.org/html/2309.03882v4 "Since computing full permutations is prohibitively expensive"
[^31]: https://docs.typesafe.ai/cookbooks/hierarchical_classification.md "sibling options are asked in the order they appear here, so it is part of the question, not presentation"
[^32]: https://docs.typesafe.ai/primitives.md "One question's answer is not hidden context for another."
[^33]: https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery.md "Scoring on the same rows would mostly measure how well the loop fitted itself to them"
[^34]: https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery.md "keep a final test set untouched by both feature discovery and model selection"
[^35]: https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery.md "grouped splits when related rows must stay together"
[^36]: https://docs.typesafe.ai/primitives/score.md "Choose examples with known expected levels, then test the revised descriptions on separate inputs before keeping them."
[^37]: https://arxiv.org/abs/2105.11447 "prior work significantly overestimated the true few-shot ability of LMs given the difficulty of few-shot model selection"
[^38]: https://docs.typesafe.ai/primitives/noul.md "The instruction is enough for most Nouls"
[^39]: https://docs.typesafe.ai/model-jaggedness/jev-1.13.md "Put boundary cases in the criteria."
[^40]: https://docs.typesafe.ai/primitives/score.md "Higher confidence does not establish which answer is correct."
[^41]: https://docs.typesafe.ai/cookbooks/entity_alignment.md "a Choice question would lose the ordered relationship of the three outcomes"
[^42]: https://docs.typesafe.ai/primitives/score.md "Every level is evaluated separately."
[^43]: https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md "State each speculative premise explicitly; code consumes the applicable answers."
[^44]: https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery.md "Check stability. Repeat discovery across seeds or data slices"
[^46]: https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md "TypeSafe's mean per-question probability standard deviation is `0.0102`"
[^47]: https://arxiv.org/abs/2302.00093 "such as decoding with self-consistency and adding to the prompt an instruction that tells the language model to ignore the irrelevant information"
[^48]: https://docs.typesafe.ai/patterns/fan-out.md "we recommend putting all of the questions your system needs in a single request"
[^49]: https://arxiv.org/html/2309.03882v4 "position bias is less regular and depends on models and tasks"
[^50]: https://docs.typesafe.ai/primitives/noul.md "Raise it when acting on a false yes is expensive"
