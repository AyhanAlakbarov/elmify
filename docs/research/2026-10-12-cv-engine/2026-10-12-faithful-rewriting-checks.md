# Faithful rewriting checks for an automatic CV-bullet rewrite

Date: 2026-10-12. Scope: a literature review, papers first, to choose the guard for a
model that lightly rewrites a student's own CV bullets with no human approval step.

## Short answer

- **No published checker is accurate enough to be the only guard.** The best
  source-grounded checkers score about 75–77% balanced accuracy on a benchmark of
  11 expert-labelled datasets, frontier models included.[^15][^16] On summaries where
  detectors disagree, the best ones are near chance.[^28]
- **A strict prompt alone leaves fabrication in half of rewritten résumés** in the one
  controlled study that measured it (down from 96.7% with no guardrail).[^39][^40]
- **The errors a model judge misses are the ones this task cares about**: numbers,
  dropped qualifiers, and role/scope upgrades. Entailment models do not reason about
  quantities[^31], and the résumé study's own LLM judge disagreed with humans only on
  "embellishment-boundary" cases.[^44]
- So the published evidence supports the shape already proposed: **deterministic
  preservation checks first, then a closed two-direction entailment question, and fall
  back to the student's wording on any failure.** Two published systems do exactly this
  "reject and keep the previous text" step.[^48][^79]
- **Not published:** a per-bullet failure rate for a *light* rewrite (verb, grammar,
  tightening); a résumé-verb strength taxonomy; any sentence-level faithfulness
  benchmark in German, French, Turkish or Russian for rewrites. These must be measured
  on our own bullets.

## Sub-questions answered

1. Which published sentence-level faithfulness checkers exist, how do they work, how
   accurate are they, where are they blind, and do they work beyond English?
2. How often do language models add or inflate content when "improving" résumé text or
   paraphrasing, and which prompt or decoding constraints reduce it?
3. Is there a published taxonomy or study showing that changing the verb changes the
   claim (role, credit, strength)?
4. Is "rewrite, verify, fall back to the original" published as a production pattern
   with measurements?

## How the candidate list was built

The method names in the question (SummaC, AlignScore, TRUE, FactCC, MiniCheck, QAGS,
QuestEval) were given. Everything else came from searches, not memory:

- Exa (`web_search_advanced_exa`, limited to arxiv.org, aclanthology.org and
  openreview.net): 14 queries covering blind spots of factuality metrics, résumé
  rewriting fabrication, over-correction in grammatical error correction, multilingual
  hallucination detection, bidirectional entailment for paraphrase, verb agency and
  claim strength, text-editing models, entity and number checks, intensifiers in
  entailment, negation and numbers in entailment, LLM-as-judge faithfulness, résumé
  fraud taxonomies, post-generation verification pipelines, and scientific
  over-generalisation.
- Brave (`brave_web_search`): one query to find the DoorDash guardrail post on its own
  domain.
- Every cited page was fetched with scrapling `get` / `bulk_get`; quotes are copied
  from that output.

Tools not used or missing: Tavily and Context7 were available and not needed. The `ide`
server failed to connect (irrelevant here). No sec.gov sources.

Several sources are 2026 preprints with one or two authors and no peer review
(marked "preprint" below). Treat their numbers as one study each.

## 1. Sentence-level faithfulness checkers

### 1.1 Method table

| Method | Mechanism | Reported accuracy | Notes for short texts |
|---|---|---|---|
| **FactCC** (2020) | A BERT classifier trained on source sentences altered by rules: paraphrase, entity and number swap, pronoun swap, negation, noise.[^10] It checks a summary sentence against the whole document. | Class-balanced accuracy and F1 on a 503-example hand-labelled test set; the abstract gives no single figure. | Built around the error types that matter here: its authors found errors "most often related to the use of incorrect entity names, numbers, and pronouns".[^11] Its own misses were mostly commonsense errors.[^12] |
| **SummaC** (2022) | Splits both texts into sentences, runs an entailment model on every sentence pair, and aggregates the scores.[^1] | 74.4% balanced accuracy on its six-dataset benchmark.[^2] | Sentence-pair granularity is the native case for a one-bullet rewrite. |
| **TRUE** (2022, a benchmark, not a method) | Re-scores 12 metrics on 11 datasets with one binary label per example. | Large entailment and question-answering methods "achieve strong and complementary results"[^5]; averaging the best three added 4.5 ROC AUC over the best single metric.[^9] | All metrics degrade on inputs over 200 tokens[^6], which a bullet is not. The best ones "fail to detect subtle inconsistencies".[^7] English only.[^8] |
| **AlignScore** (2023) | One alignment model trained on 4.7M examples from seven tasks, including entailment and paraphrase.[^3] | "matches or even outperforms metrics based on ChatGPT and GPT-4" at 355M parameters.[^4] | Sentence and document inputs both supported by design. |
| **MiniCheck** (2024) | A small model trained on synthetic hard cases so that it checks "each fact in the claim".[^13] | The 770M model "reaches GPT-4 accuracy" on LLM-AggreFact.[^14] Leaderboard read 2026-10-12: Bespoke-MiniCheck-7B 77.4, Claude 3.5 Sonnet 77.2, GPT-4o 75.9, MiniCheck-Flan-T5-L 75.0 average balanced accuracy.[^16] | Thresholds can be tuned per dataset; the maintainers recommend exploring it.[^17] |
| **QAGS** (2020) | Generates questions from the output, answers them on both texts, compares answers.[^18] | Reported as correlation with human judgement, not accuracy. | Needs a question generator and a reader; heavy for one line. |
| **QuestEval** (2021) | Same idea in both directions, without a reference.[^19] | Correlation only. | The reverse direction approximates "nothing was lost". |
| **Entity and number checks** | Flag entities in the output that are absent from the source[^20]; verify "quantity entities (dates, numbers, sums of money, etc.)" against the source.[^21] | No accuracy figure for a rewrite task. | Deterministic, cheap, language-light for digits. |
| **Bidirectional entailment** | Treat two texts as paraphrases only if each entails the other. The Mutual Implication Score does this and "outperforms all other measures on the paraphrase detection task" across 57 measures and 19 datasets.[^22] The same idea was used earlier for translation evaluation.[^23] | Reported as rank against other measures, not as an error rate. | This is the published form of the two-direction question. |

A refinement worth copying: use the contradiction probability as well as the entailment
probability, which improved a plain entailment model on TRUE.[^85]

### 1.2 What accuracy to expect

- About three in four on hard, expert-labelled grounding benchmarks, for specialised
  models and frontier models alike.[^16]
- Near 50% on cases where current detectors disagree with each other.[^28]
- These benchmarks check a claim against a long document. A bullet checked against its
  own one-line source is an easier setting, and **no benchmark for that setting was
  found**, so the figures above are a floor on difficulty, not a prediction.

### 1.3 Known blind spots

- **Numbers.** Across nine entailment models, "state-of-the-art methods do not achieve
  an absolute improvement over a majority-class baseline" on quantitative reasoning.[^31]
- **Negation.** "state-of-the-art transformers struggle" on a benchmark where negation
  decides the label.[^30]
- **Gradable wording.** Entailment models "perform considerably worse on examples with
  scalar implicatures" involving gradable adjectives.[^32] No study was found that tests
  whether a checker separates "improved" from "significantly improved"; this is the
  nearest evidence. **Unverified** for intensifiers specifically.
- **Hedging and certainty.** Covered from the generation side in section 2; no checker
  paper reporting hedge-sensitivity was found.
- **False alarms on harmless rewording.** Entailment models change their answer on
  8–16% of paraphrased inputs[^24], and lose 12.92% accuracy in-domain under small
  meaning-preserving changes.[^25] Factuality metrics are "more sensitive to benign,
  fact-preserving edits than to factual corrections"[^26] and show "biases against
  highly paraphrased outputs".[^27] For this design a false alarm only costs a fallback
  to the student's wording.
- **Uneven coverage by error type.** An adversarial study built 24 diagnostic sets to
  show that six top metrics each have different weak error types.[^29]

### 1.4 Beyond English

- The specialised checkers were built and evaluated on English. TRUE says so
  directly.[^8] Multilingual support for SummaC, AlignScore and MiniCheck: **Unverified**
  (not stated on the pages fetched).
- Multilingual work exists but is thin: prior detectors "focus exclusively on
  English"[^34]; on generated biographies, entailment metrics "do not detect single-fact
  hallucinations well and fail for lower-resource languages".[^33] A single-fact error is
  exactly what a bad bullet rewrite is.
- Plain multilingual entailment models are weaker than English ones. One widely used
  model's card reports XNLI accuracy of 0.871 for English, 0.824 German, 0.823 French,
  0.803 Russian and 0.792 Turkish (values read from its results table), and warns that
  no model exceeds "a few points above 80%" on average.[^35] Its training data is
  machine-translated, "which reduces the quality of the data".[^36]
- Language-specific resources found: a Turkish fine-grained hallucination dataset[^37]
  and a German token-level one.[^38] Nothing found for Russian or French at sentence
  level for rewrites.

## 2. How often models add or inflate, and what reduces it

### 2.1 Measured rates

- **Résumé improvement (preprint, synthetic résumés, tailoring to a job description).**
  With an ordinary prompt, 96.7% of outputs contained at least one unsupported
  claim.[^39] A strict-rules prompt cut findings by 86% but "50.0% of outputs still
  contained a fabrication".[^40] The rules were close to ours: "no unsupported additions,
  no qualifier upgrades".[^41] That prompt removed dropped-qualifier and invented-identity
  findings entirely[^42]; what remained was mostly new unsupported claims. The run used
  temperature 0.7.[^45] The task is more aggressive than a light rewrite, so read these as
  an upper bound.
- **Résumé optimisation (preprint, 25 synthetic résumés).** Undefended baselines produced
  2.48–5.36 detected hallucinations per résumé.[^46] Prompt grounding alone reached zero
  detected at temperature 0 with a capable model[^47], and compliance weakened as
  temperature rose.[^86] Its detectors see presence, not magnitude, so an inflated number
  can pass.[^49]
- **Certainty inflation in rewriting (preprint).** Models were "1.5-2x more likely to
  increase the expressed certainty than to decrease it"[^50], and prompt interventions
  "reduce overall certainty distortion but do not eliminate it".[^51]
- **Over-generalisation in summaries (peer-reviewed).** Leading models over-generalised
  scientific findings "in 26 to 73% of cases", even when prompted for accuracy.[^52]
- **Simplification.** Rewriting for readability risks "inserting statements unsupported
  by the corresponding original text, or by omitting key information".[^62]
- **Grammar correction.** ChatGPT shows "over-correction tendencies and not adhering to
  the principle of minimal edits".[^53] Large models as a class make "excessive
  overcorrection, leading to low precision".[^54]
- **Repeated rewriting.** Distortion "accumulates over time" across iterations[^63], so a
  rewrite should always start from the student's original, never from a previous rewrite.

No study was found that reports a per-bullet rate for a light rewrite, or that counts
verb upgrades ("led" for "helped") separately. **No published evidence** on that exact
question; the closest category is "altered" claims, defined as "scope/role/metric
inflation".[^43]

### 2.2 Constraints shown to help

- **A minimal-edit instruction.** It "mitigates over-editing and typically boosts
  precision", while a fluency instruction "encourages broader paraphrastic rewriting"
  (seven models, three benchmarks).[^55]
- **Edit-level voting.** Generating several candidates and keeping only the edits most of
  them agree on reduces over-correction without retraining, in seven languages including
  German.[^56]
- **Edit-based models instead of free generation.** A tagger that can only keep, delete
  or insert from a small phrase list[^57] is contrasted with free generation, which is
  "more likely to produce subtly misleading hallucinations".[^58] Its authors add the
  caveat that deletion alone can "completely alter the meaning of the sentence".[^59] A
  later tutorial presents the family as a way "to mitigate hallucination".[^60]
- **Copy mechanisms.** Pointing at source words "aids accurate reproduction of
  information".[^61] This is an architecture choice for a trained model, not something a
  hosted model exposes.
- **Low temperature**, per the résumé-optimisation ablation.[^86]
- **Quote-and-verify.** Anthropic's guidance is to make the model find a supporting quote
  for each claim and "If it can't find a quote, it must retract the claim."[^64] The same
  page says these techniques "don't eliminate them entirely"[^65] and reports no
  measurement.

Context, not a fabrication result: a field experiment on nearly half a million
jobseekers found that algorithmic writing assistance on résumés raised hiring by 8%, so
the light rewrite is worth doing.[^84]

## 3. Verb strength and claim inflation

- **Verbs carry an implied level of agency.** Connotation frames model "how different
  levels of power and agency are implicitly projected on actors through their
  actions"[^66], and a follow-up system rewrites text by swapping verbs to change that
  level, using frames that "encode pragmatic knowledge of implied power dynamics with
  respect to verb predicates".[^67] This is the closest published lexicon to a
  verb-strength scale.
- **A word list is not enough.** Work on language agency in model output notes that
  string matching for agentic words falls "short of accurately classifying language
  agency" and trains a classifier instead.[^68]
- **Statement strength is a studied property of revisions.** A corpus of sentence
  revisions from academic writing exists because "papers can be rejected because they
  overstate or understate their findings".[^69]
- **Exaggeration is a known rewriting failure.** Findings "may be distorted with altered
  claim strength when reported to the public"[^70], and news tends "to misrepresent
  scientific papers by exaggerating their findings".[^71]
- **Contribution is typed in research publishing.** CRediT is "a community-owned
  taxonomy of 14 contributor roles"[^72] (Conceptualization, Software, Supervision and so
  on). It types *what kind* of contribution, not how large.
- **Résumé misrepresentation has a validated three-part model**: "fabrication,
  embellishment, omission".[^73] A verb upgrade is embellishment; a dropped qualifier is
  omission.
- **Observed in model rewrites.** The résumé study logged role and scope rewrites such as
  "legal-practice experience rewritten into localization program leadership".[^74]

**No published evidence** was found for a taxonomy that ranks résumé verbs by claim
strength ("assisted" < "contributed to" < "developed" < "led"), or for a measured rate
of verb upgrades by models. A tiering for our guard would be our own artefact.

## 4. "Rewrite, verify, fall back" in practice

- **DoorDash (vendor engineering blog, with measurements).** Two layers: a cheap
  semantic-similarity check, then a model evaluator only when the first fails.[^75] The
  system "reduced overall hallucinations by 90%".[^76] When a response fails, it defaults
  to a human agent[^77], which is the support-chat equivalent of falling back to the
  original.
- **Résumé optimisation framework (preprint).** "Failures at any post-generation layer
  trigger retry with augmented constraints or fallback to original content."[^48] Its
  evaluator model "defaults to rejection" when it times out or returns malformed
  output.[^82]
- **Manuscript editing (preprint).** Every numeric token must be attested by a
  registry[^78]; candidates that fail "are rejected and the previous HEAD is
  retained".[^79] With a model proposing the edits, 75% of candidates were accepted.[^80]
- **Human checkpoint comparison (preprint).** Neither the prompt guardrail nor the human
  review cost content: "claim retention exceeded 99% under both".[^81] The reviewer missed
  subtle qualifier drops about half the time, and the paper asks for exactly the tooling
  proposed here: "automated diff highlighting against source claims and
  qualifier-preservation checks".[^83]

No measurement-reporting post from a writing-assistant or résumé vendor was found in
these searches. **No published evidence** on fallback rates for a deployed bullet
rewriter.

## What this means for the guard (synthesis, not a finding)

The items below are my reading of the evidence above. None is a published result.

**Deterministic checks, both directions (nothing added, nothing lost):**

1. Numbers, percentages, dates, currency and units: the multiset in the rewrite equals
   the multiset in the original. Reason: entailment models cannot be trusted on
   quantities[^31], and numbers and entities are the commonest real errors.[^11]
2. Named entities, acronyms and capitalised tokens: same set in both.[^20]
3. No new content word outside a small allow-list of neutral action verbs and function
   words. Reason: restricting insertions is what makes edit-based models safer.[^58]
4. Qualifier preservation: a per-language list ("basic", "prototype", "assisted",
   "contributed to", "part of a team", "one of") whose members may not be dropped.
   Reason: dropped qualifiers are the error humans miss.[^83]
5. No inserted intensifiers or outcome adverbs ("significantly", "successfully").
   Reason: checker sensitivity to these is unproven (section 1.3).
6. One bullet in, one bullet out, with a length-ratio bound.

**Model judgement:** two closed yes/no questions per bullet (does the original support
everything in the rewrite; does the rewrite keep everything in the original), asked of a
model from a different family than the writer, with any "no", refusal, timeout or
malformed answer treated as a fail.[^82] A third closed question is justified by
section 3: "does the rewrite give the student a larger role than the original?"

**Generation settings that reduce how often the guard has to fire:** minimal-edit
wording[^55], low temperature[^86], always rewrite from the original.[^63]

**What failure rate to expect:**

- Rewrites that try to add something: the only résumé figures are document-level (half
  of documents with at least one finding under a strict prompt[^40]). A per-bullet rate
  for a light rewrite is **Unverified**; it has to be measured on our own data.
- Bad rewrites that slip past a model judge alone: the one résumé-specific judge
  validation gives recall of 15/16 on 20 items[^44], a wide interval. General benchmarks
  suggest far worse on hard cases.[^16][^28] This is why checks 1–5 must not depend on
  the judge.
- Good rewrites wrongly rejected: expect this to be common, given 8–16% answer flips on
  paraphrases[^24], plus strict lexical rules. It is the cheap direction.

## Sources

[^1]: https://arxiv.org/abs/2111.09525 "segmenting documents into sentence units and aggregating scores between pairs of sentences"
[^2]: https://arxiv.org/abs/2111.09525 "state-of-the-art results with a balanced accuracy of 74.4%, a 5% point improvement compared to prior work"
[^3]: https://arxiv.org/abs/2305.16739 "4.7M training examples from 7 well-established tasks (NLI, QA, paraphrasing, fact verification, information retrieval, semantic similarity, and summarization)"
[^4]: https://arxiv.org/abs/2305.16739 "AlignScore (355M parameters) matches or even outperforms metrics based on ChatGPT and GPT-4"
[^5]: https://arxiv.org/abs/2204.04991 "large-scale NLI and question generation-and-answering-based approaches achieve strong and complementary results"
[^6]: https://ar5iv.labs.arxiv.org/html/2204.04991 "We find that there is a consistent degradation for texts longer than 200 tokens for all metrics"
[^7]: https://ar5iv.labs.arxiv.org/html/2204.04991 "the best-performing metrics fail to detect subtle inconsistencies"
[^8]: https://ar5iv.labs.arxiv.org/html/2204.04991 "We focus on English text-to-text tasks"
[^9]: https://ar5iv.labs.arxiv.org/html/2204.04991 "with an increase of 4.5 in ROC AUC from the best single-metric result"
[^10]: https://arxiv.org/abs/1910.12840 "Training data is generated by applying a series of rule-based transformations to the sentences of source documents."
[^11]: https://ar5iv.labs.arxiv.org/html/1910.12840 "errors made by summarization models are most often related to the use of incorrect entity names, numbers, and pronouns"
[^12]: https://ar5iv.labs.arxiv.org/html/1910.12840 "The majority of error made by our fact checking model were related to commonsense mistakes made by summarization models."
[^13]: https://arxiv.org/abs/2404.10774 "Training on this data teaches models to check each fact in the claim and recognize synthesis of information across sentences."
[^14]: https://arxiv.org/abs/2404.10774 "Our best system MiniCheck-FT5 (770M parameters) outperforms all systems of comparable size and reaches GPT-4 accuracy."
[^15]: https://llm-aggrefact.github.io/blog "LLM-AggreFact draws together performance across 11 datasets"
[^16]: https://llm-aggrefact.github.io/ "Bespoke-Minicheck-7B 7B 77.4 65.5 77.8"
[^17]: https://llm-aggrefact.github.io/blog "As this is a binary classification task, it is possible to tune the threshold for each dataset."
[^18]: https://arxiv.org/abs/2004.04228 "if we ask questions about a summary and its source, we will receive similar answers if the summary is factually consistent with the source"
[^19]: https://arxiv.org/abs/2103.12693 "QuestEval does not require any ground-truth reference"
[^20]: https://arxiv.org/abs/2102.09130 "generating names of entities that are not present in the source document"
[^21]: https://arxiv.org/abs/2009.13312 "The system learns to recognize and verify quantity entities (dates, numbers, sums of money, etc.)"
[^22]: https://aclanthology.org/2022.acl-srw.23/ "a measure that uses the idea of paraphrasing as a bidirectional entailment and outperforms all other measures on the paraphrase detection task"
[^23]: https://arxiv.org/abs/1911.00681 "paraphrasing can be detected by evaluating entailment relationship in the forward and backward direction"
[^24]: https://arxiv.org/abs/2306.16722 "contemporary models change their predictions on 8-16"
[^25]: https://aclanthology.org/2024.eacl-long.27/ "semantic sensitivity causes performance degradations of 12.92% and 23.71% average over"
[^26]: https://arxiv.org/abs/2411.16638 "some metrics are more sensitive to benign, fact-preserving edits than to factual corrections"
[^27]: https://arxiv.org/abs/2501.14883 "these metrics exhibit biases against highly paraphrased outputs"
[^28]: https://arxiv.org/abs/2410.13210 "even the best hallucination detection models have near 50"
[^29]: https://aclanthology.org/2021.findings-emnlp.179/ "diagnose the fine-grained strengths and weaknesses of 6 existing top-performing metrics over 24 diagnostic test datasets"
[^30]: https://aclanthology.org/2020.emnlp-main.732/ "state-of-the-art transformers struggle making inference judgments with the new pairs"
[^31]: https://aclanthology.org/K19-1033/ "state-of-the-art methods do not achieve an absolute improvement over a majority-class baseline"
[^32]: https://aclanthology.org/2024.lrec-main.1288/ "the investigated models still perform considerably worse on examples with scalar implicatures than on other types of NLI examples"
[^33]: https://arxiv.org/abs/2402.10496 "they do not detect single-fact hallucinations well and fail for lower-resource languages"
[^34]: https://arxiv.org/abs/2212.10622 "they focus exclusively on English, a language with abundant resources"
[^35]: https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 "shows a multilingual average performance of more than a few points above 80% on XNLI"
[^36]: https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 "dataset was created using machine translation, which reduces the quality of the data for a complex task like NLI"
[^37]: https://arxiv.org/abs/2503.07833 "fine-grained hallucinations in English, Arabic, and Turkish"
[^38]: https://arxiv.org/abs/2407.13702 "a new evaluation dataset that extends the English hallucination detection dataset to German"
[^39]: https://arxiv.org/abs/2608.26171 "the baseline (C1) produced at least one unsupported claim in 96.7% of outputs"
[^40]: https://arxiv.org/abs/2608.26171 "50.0% of outputs still contained a fabrication, showing prompt-level mitigation alone is insufficient"
[^41]: https://arxiv.org/html/2608.26171 "strict factual rules (no unsupported additions, no qualifier upgrades, no domain reinterpretation, no papering over gaps)"
[^42]: https://arxiv.org/html/2608.26171 "eliminated two categories entirely (identity: 0, qualifier_drop: 0)"
[^43]: https://arxiv.org/html/2608.26171 "modification of existing claims (scope/role/metric inflation)"
[^44]: https://arxiv.org/html/2608.26171 "judge accuracy is 18/20 (90%), with precision 15/16 (93.8%) and recall 15/16 (93.8%) at the item level"
[^45]: https://arxiv.org/html/2608.26171 "temperature 0.7 (variance source across repetitions)"
[^46]: https://arxiv.org/abs/2607.01457 "undefended baselines produce 2.48-5.36 detected hallucinations per resume"
[^47]: https://arxiv.org/abs/2607.01457 "Prompt-level grounding alone achieves zero detected hallucinations at low temperature with a capable instruction-following model"
[^48]: https://arxiv.org/html/2607.01457v1 "Failures at any post-generation layer trigger retry with augmented constraints or fallback to original content."
[^49]: https://arxiv.org/html/2607.01457v1 "the framework detects presence but not magnitude hallucinations"
[^50]: https://arxiv.org/abs/2606.07951 "most LMs being 1.5-2x more likely to increase the expressed certainty than to decrease it"
[^51]: https://arxiv.org/abs/2606.07951 "Prompt-based interventions reduce overall certainty distortion but do not eliminate it."
[^52]: https://arxiv.org/abs/2504.00025 "overgeneralizing in 26 to 73% of cases"
[^53]: https://arxiv.org/abs/2304.01746 "possibly due to its over-correction tendencies and not adhering to the principle of minimal edits"
[^54]: https://aclanthology.org/2025.emnlp-main.1431/ "making excessive overcorrection, leading to low precision"
[^55]: https://aclanthology.org/2026.bea-1.17/ "The Minimal-Edit instruction mitigates over-editing and typically boosts precision"
[^56]: https://arxiv.org/abs/2605.13624 "edit-level majority voting over multiple candidates generated by a single model"
[^57]: https://arxiv.org/abs/1909.01187 "three main edit operations: keeping a token, deleting it, and adding a phrase before the token"
[^58]: https://ar5iv.labs.arxiv.org/html/1909.01187 "A seq2seq model is more likely to produce subtly misleading hallucinations that misrepresent the input text, while looking fluent and credible."
[^59]: https://ar5iv.labs.arxiv.org/html/1909.01187 "We have seen examples where deletion of word spans was sufficient to completely alter the meaning of the sentence."
[^60]: https://arxiv.org/abs/2206.07043 "how these models can be used to mitigate hallucination and bias"
[^61]: https://arxiv.org/abs/1704.04368 "copy words from the source text via pointing, which aids accurate reproduction of information"
[^62]: https://arxiv.org/abs/2204.07562 "inserting statements unsupported by the corresponding original text, or by omitting key information"
[^63]: https://arxiv.org/abs/2502.20258 "distortion accumulates over time, influenced by language choice and chain complexity"
[^64]: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations "If it can't find a quote, it must retract the claim."
[^65]: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations "while these techniques significantly reduce hallucinations, they don't eliminate them entirely"
[^66]: https://aclanthology.org/D17-1247/ "to model how different levels of power and agency are implicitly projected on actors through their actions"
[^67]: https://aclanthology.org/2020.emnlp-main.602/ "which encode pragmatic knowledge of implied power dynamics with respect to verb predicates"
[^68]: https://arxiv.org/abs/2404.10508 "falling short of accurately classifying language agency"
[^69]: https://arxiv.org/abs/1405.1439 "papers can be rejected because they overstate or understate their findings"
[^70]: https://aclanthology.org/W17-4219/ "Original findings from science publications may be distorted with altered claim strength when reported to the public"
[^71]: https://arxiv.org/abs/2108.13493 "a tendency of news media to misrepresent scientific papers by exaggerating their findings"
[^72]: https://credit.niso.org/ "CRediT is a community-owned taxonomy of 14 contributor roles"
[^73]: https://link.springer.com/article/10.1007/s10869-017-9527-4 "three theorized resume fraud dimensions (fabrication, embellishment, omission)"
[^74]: https://arxiv.org/html/2608.26171 "legal-practice experience rewritten into localization program leadership"
[^75]: https://careersatdoordash.com/blog/large-language-modules-based-dasher-support-automation/ "The first quality check layer is a semantic similarity comparison between the response and KB article segments."
[^76]: https://careersatdoordash.com/blog/large-language-modules-based-dasher-support-automation/ "This guardrail system has successfully reduced overall hallucinations by 90% and cut down potentially severe compliance issues by 99%."
[^77]: https://careersatdoordash.com/blog/large-language-modules-based-dasher-support-automation/ "strategically defaulting to human agents can be an effective way to ensure a quality user experience"
[^78]: https://arxiv.org/abs/2608.23001 "require every cited key and experimental numeric token to be attested by a reference registry or experimental log"
[^79]: https://arxiv.org/abs/2608.23001 "Candidates that fail either check are rejected and the previous HEAD is retained."
[^80]: https://arxiv.org/abs/2608.23001 "candidates were accepted in 75% of cases"
[^81]: https://arxiv.org/abs/2608.26171 "claim retention exceeded 99% under both"
[^82]: https://arxiv.org/html/2607.01457v1 "it defaults to rejection rather than silently accepting the candidate output"
[^83]: https://arxiv.org/html/2608.26171 "automated diff highlighting against source claims and qualifier-preservation checks"
[^84]: https://arxiv.org/abs/2301.08083 "Treated jobseekers experienced an 8% increase in the probability of getting hired."
[^85]: https://arxiv.org/abs/2305.16819 "Making use of both entailment and contradiction probabilities in NLI"
[^86]: https://arxiv.org/html/2607.01457v1 "suggests prompt compliance weakens with temperature, motivating deterministic layers as a complement rather than a replacement for prompt-based grounding"

## Open questions

- **Per-bullet failure rate of a light rewrite.** Not published. Needs our own labelled
  set of original/rewrite pairs, split by error type (number, entity, verb upgrade,
  dropped qualifier, added intensifier).
- **Intensifiers and verb upgrades in checkers.** No paper found that measures whether
  SummaC, AlignScore, MiniCheck or a prompted model catches "helped" becoming "led" or an
  added "significantly". The gradable-adjective result is the nearest evidence.
- **A résumé-verb strength scale.** None found. The connotation-frame agency lexicon is
  the nearest published resource; whether it covers CV verbs well enough is untested.
- **German, French, Turkish, Russian.** No sentence-level rewrite-faithfulness benchmark
  found in any of the four. Whether the English-trained checkers accept these languages
  at all was not established from the pages fetched.
- **Sentence-to-sentence accuracy.** Every benchmark figure here is claim-against-document.
  The easier bullet-against-bullet case has no published number.
- **Science-news exaggeration baseline (Sumner et al., BMJ 2014).** Could not be fetched,
  so the human base rate of exaggeration in rewriting is not cited here.
- **The 2026 preprints** on résumé fabrication, certainty distortion and gated editing are
  unreviewed and mostly single-team; their figures need replication before being used as
  targets.
