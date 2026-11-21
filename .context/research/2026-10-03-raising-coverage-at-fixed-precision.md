# Raising coverage while holding ~99% precision: published methods and what they cost

Researched 2026-10-03, for the line-level funding reader (Jev + DeepSeek V4.1 Flash).
Baseline: `2026-10-03-settle-second-reader-language-translation.md` (same directory). Jev ≥ 0.95
alone keeps 34/116 true "yes" facts with 0 errors; Jev ≥ 0.8 + DeepSeek ≥ 0.95 keeps 52/116 with 1
error; in Jev's 0.5–0.7 band, where DeepSeek disagrees, DeepSeek is right 39 of 50 times.

**How the candidate list was built.** Exa searches (cascaded selective evaluation; conformal/FDR
selective prediction for LLMs; cheap-then-expensive cascades; checklist decomposition and
agreement; annotation guidelines/codebooks for LLM annotators; sentence classification with
context and distraction; knowledge fusion / truth discovery; cheap-model sampling vs one large
call; correlated LLM errors), then one Brave `site:arxiv.org` search (it returned the Mixture-of-
Thoughts cascade). Two papers were added from the citation trail of those results rather than a
search hit: Conformal Alignment (cited by Trust or Escalate as "Gui et al., 2024") and Ask Me
Anything (prompt-wording ensembles). Every quote below was copied from a scrapling `get` of the
live arXiv / ACL Anthology page. Tavily and Context7 were not needed; no tool was missing.

## Sub-questions

1. Selective prediction / cascades with a guarantee: what coverage at a fixed error rate, and how
   many labelled examples set the threshold?
2. Escalating only uncertain or disagreeing items to a stronger model: gains, share escalated,
   correlated-error caveats.
3. Does splitting a vague criterion into atomic yes/no questions with definitions raise agreement?
4. Line-level classification: heading/neighbours vs whole page.
5. Redundancy in the source (same fact stated several times): fusion methods and their calibration.
6. Many cheap calls / wordings vs one strong call.

## 1. Selective prediction with a precision guarantee

**Trust or Escalate (Cascaded Selective Evaluation, ICLR 2025).** Each judge abstains unless its
confidence clears a threshold calibrated on labelled data, and abstained items go to the next,
stronger judge. The guarantee is that agreement with humans holds at a level the user sets.[^1]
The headline result: "guarantees over 80% human agreement with almost 80% test coverage" using
Mistral-7B among others.[^1] On ChatArena at target agreement 0.85, "our method achieves 91%
guarantee success rate while only using GPT-4 for 17.5% of the evaluations".[^2] At a target of
0.8, cost savings against all-GPT-4 were "up to 78.5% with stronger cascades and 87.4% with weaker
cascades".[^2] The items it abstains on are the hard ones: "the instances abstained by LLM judges
tend to be more subjective even for humans".[^2]
- *Coverage at a fixed error rate:* about 55–80% coverage at 80–90% agreement (paper §3 tables).
  Nobody has shown this at 99% precision. The error rates in the paper are 10–20%, not 1%.
- *Labelled examples:* §3.1 fixes the calibration set at 500 items (TL;DR, ChatArena) and 392
  (Auto-J), with δ = 0.1. The numbers sit in MathML on the page, so they have no checkable quote
  here; read §3.1 directly.
- Its confidence signal, "Simulated Annotators", is several few-shot prompts voting. It "significantly
  improves judge calibration and thus enables high coverage".[^1]

**Conformal risk control / FDR-controlled selection.** Conformal risk control bounds the expected
value of any monotone loss, and it is "tight up to an $\mathcal{O}(1/n)$ factor".[^3] For "accept
or abstain" decisions the closer fit is FDR control over the accepted set:
- COIN "applies confidence interval methods such as Clopper-Pearson to establish a high-probability
  upper bound on the true error rate".[^4]
- LEC computes "a risk-constrained, retention-maximizing threshold". It extends to "two-model routing
  systems", where an item over the first model's threshold goes to the second while the whole
  system keeps its error control.[^5] That is our Jev → second-reader shape.
- Conformal Alignment certifies which outputs to trust "via lightweight training over a moderate
  amount of reference data".[^6]

None of these abstracts reports coverage at a 1% error target. **Unverified** for our setting.

**What it costs in labels (arithmetic, not a citation).** These methods certify an error bound on
the accepted "yes" answers, so labelled *positives* set the cost. One-sided 95% Clopper-Pearson
bounds for an error rate ≤ 1%:

| errors seen among accepted yes | accepted yes facts needed |
|---|---|
| 0 | ≈ 300 |
| 1 | ≈ 473 |
| 2 | ≈ 628 |

At our base rate (116 yes in 2,215 items, 5.2%), 300 accepted positives means roughly 6,000–12,000
labelled items, depending on coverage. Calibration also has to be done per question, or the
questions must be shown to share a threshold.

## 2. Escalating only uncertain or disagreeing items

- **FrugalGPT** learns which LLMs to chain per query and can "match the performance of the best
  individual LLM (e.g. GPT-4) with up to 98% cost reduction".[^7]
- **AutoMix** routes on a self-verification estimate and reports "reducing computational cost by
  over 50% for comparable performance".[^8]
- **Mixture-of-Thoughts cascade (ICLR 2024)** is closest to "escalate on disagreement". It uses the
  weaker model's "answer consistency" across sampled answers and prompt styles as the escalation
  signal, and reaches "performance comparable to using solely the stronger LLM but require only 40%
  of its cost".[^9]
- **Trust or Escalate**: GPT-4 handled 17.5% of items at the 0.85 target (above).[^2]

**Correlated-error caveats. This is the main precision risk for "two cheap readers agree":**
- "models agree 60% of the time when both models err", and "larger and more accurate models have
  highly correlated errors, even with distinct architectures and providers".[^10]
- A panel of 9 frontier judges gives "only about 2 independent votes' worth of information", and
  "the best single judge matches or outperforms the full panel across all conditions".[^11]
- Ten judges with mean pairwise error correlation 0.21 "only provide roughly as much statistical
  information as 3.5 independent judges".[^12]
- Self-consistency fails on confident models: "agreement >=0.8 on 77% of GPQA case-result entries,
  48% of those wrong".[^13]
- The cascade literature exploits the same correlation: "the error patterns of small and large
  models are correlated", so early abstention cut cost by 13.0%.[^14]

For us: precision measured on "Jev and DeepSeek agree" is the only valid number. Multiplying their
separate error rates would overstate it.

## 3. Question and label design

- CheckEval turns vague criteria into "decomposed binary questions". It "improves the average
  agreement across evaluator models by 0.45".[^15]
- TICK splits an instruction "into a series of YES/NO questions", which "leads to a significant
  increase (46.4%" in exact LLM–human agreement (to 52.2%).[^16]
- In checklist appraisal, "ambiguous and conditional criteria producing the greatest disagreement",
  and "Revising these items improves both raw and chance-corrected agreement".[^17]
- Checklist decomposition does not always help: benefits "are less consistent in direct scoring".[^18]
- A cheap codebook-repair loop uses cross-LLM disagreement to target expert time: rationale labels
  on disagreement cases reached "the highest LLM-labeling accuracy (64.9%)", against 57.8% for the
  expert-revised codebook.[^19]

Our `who_may_apply` (28/66 kept) is the "conditional criterion" case. It probably bundles
nationality, degree level, age and field into one question. Splitting it into atomic questions and
writing boundary definitions from our 97 disagreement items is the direct application. The size of
the gain for our task is **Unverified**.

## 4. Context for line-level classification

- Adjacent sentences "can provide important information for classification", and adding them
  "consistently improves over previous methods" (pre-LLM).[^20]
- BERT given all the sentences jointly achieves "state-of-the-art results on four datasets" for
  sequential sentence classification.[^21]
- Targeted context beats the whole document. Retrieving only nearby or similar sentences gave "an
  average increase of ∼5.5 weighted-F1 points", and "Sequential heuristics outperform hierarchical
  models" on two of three datasets.[^22]
- Irrelevant context costs accuracy: "the model performance is dramatically decreased when
  irrelevant information is included".[^23] Long contexts also lose material placed in the middle:
  performance "significantly degrades when models must access relevant information in the middle of
  long contexts".[^24]

For us: Jev saw 30-line chunks without headings. The measurement file already flags this as
depressing recall on `who_may_apply`. Prepending the section heading path plus ±2 lines is the
evidence-backed middle ground. No source measured headings specifically: **Unverified**.

## 5. Redundancy in the source: fusion

- Knowledge fusion assigns "true subject-predicate-object triples extracted by multiple information
  extractors from multiple information sources", tested on 1.6B triples.[^25]
- Its best calibration: "when we predict a probability above 0.9, the real accuracy of the triples
  is indeed high (0.94)".[^26] That is 94%, not 99%. Fusion alone does not reach our bar.
- Knowledge-Based Trust separates "errors made in the extraction process from factual errors in the
  web source", which is the distinction we need between a misread line and a wrong page.[^27]

For us: two mentions on one site (call page and FAQ) are not independent. They share an author and
often a template. Two extractions of one sentence are not independent either. Treat a repeat
mention as a corroborating signal that feeds the calibrated threshold, not as an automatic pass.
No source quantifies the gain for scholarship pages: **Unverified**.

## 6. Many cheap calls / wordings vs one strong call

- Ask Me Anything aggregates several imperfect prompt wordings with weak supervision. It let
  "GPT-J-6B model to match and exceed the performance of few-shot GPT3-175B on 15 of 20 popular
  benchmarks".[^28]
- Majority voting across semantically equivalent prompts "significantly improves reproducibility and
  reduces variance".[^29]
- More calls can hurt: Vote performance "can first increase but then decrease as a function of the
  number of LM calls".[^30]
- Self-consistency "often provide statistically insignificant gains while becoming
  cost-prohibitive" on strong models.[^31]
- Correlated self-agreement (§2) caps what repeated calls of one model add to *precision*.

## Options ranked for our case

| # | Option | Expected coverage gain (yes facts) | Precision risk | Cost per page* | Evidence strength |
|---|---|---|---|---|---|
| 1 | **Escalate only the uncertain band / disagreements to a strong model** (Jev 0.5–0.95 or Jev ≠ DeepSeek). The strong model decides, or a third agreeing reader is required. | Large. Most of the ~60 unkept facts sit in this band; DeepSeek was right 39/50 there. Plausibly 49% → 65–80% of yes facts (**Unverified** estimate). | Moderate: strong models share errors (§2). Requires item-level calibration of the strong model's yes. | Escalate ~5–15% of ~140 items/page. At the key-run rate (~$0.82 for 2,215 items × 2 strong models, ≈ $0.0002 per item per model) that is ≈ $0.002–0.005/page on top of ~$0.005 now. | Strong for the pattern (Trust or Escalate, MoT cascade, FrugalGPT, AutoMix). None shown at 99%. |
| 2 | **Certify thresholds with Clopper-Pearson / LTT (COIN, LEC)** instead of hand-picked bars. | Indirect: picks the lowest bar the data allows, so it can only add coverage. It is also the only way to *claim* ≤1/100. | Low by construction, if calibration items are exchangeable with production lines (same languages and site mix). | ~$0 at run time. Cost is ~300–630 labelled positives per question family (≈ 6–12k labelled items at 5% base rate), ≈ $2–5 of key spend at the measured rate plus referee review. | Strong theory; LLM experiments at 10–20% risk, not 1%. |
| 3 | **Redesign the questions**: split `who_may_apply` and `receives_money` into atomic yes/no questions with definitions and boundary examples taken from the 97 disagreement items. | Medium on the weak questions (`who_may_apply` 28/66, `receives_money` 6/18). Size **Unverified**. | Low, and it may lower risk, since agreement rises when ambiguity falls. More questions means more chances for a false yes, so re-measure. | ~1–2× tokens per added question. Jev is ≈ $0.006 for 443 lines, so negligible. | Medium: CheckEval, TICK, GRoLTS checklist study. Not on extraction from web pages. |
| 4 | **Give Jev the heading path ± 2 neighbouring lines**, not bare 30-line chunks or the whole page. | Medium, concentrated on lines whose meaning needs the heading. **Unverified**. | Low to moderate: whole-page context distracts (§4). | Small token increase. | Medium for local context (sequential sentence classification). Indirect for LLMs. |
| 5 | **Fuse repeated mentions** (same fact on call page, FAQ, PDF) into a per-fact score. | Small to medium: helps exactly the deadlines and amounts that are restated. | Moderate: mentions on one site are not independent, and fusion calibrated only to 0.94 at p > 0.9. | Only aggregation code. Needs entity/fact matching across lines. | Medium (knowledge fusion at web scale). Nothing at 99%. |
| 6 | **Several wordings of the same question to the cheap reader, then vote.** | Small to medium on recall. | Moderate to high for precision: one model's agreement with itself is the most correlated signal there is. | k× the cheap reader (×3 ≈ +$0.012 for 443 lines with Jev). | Mixed: AMA positive; non-monotone and insignificant-gain findings against. |

\* Per-page figures are extrapolated from the measurement file (443 lines ≈ 16 pages; five
questions per line). They are not quoted from any source.

**The recommendation this supports.** Do 2 + 1 together: a calibrated cascade (Jev → DeepSeek →
strong model on the residual band), certified per question by a Clopper-Pearson bound. Then
3 and 4, which are cheap prompt changes, to shrink the band that needs escalating. Treat 5 as a
later signal fed into the same calibration. Rank 6 last.

## Open questions

- No published result shows any method above at a 1% error target. Every guarantee paper here
  reports 10–20% risk levels. Whether coverage holds at α = 0.01 with a few hundred positives is
  unmeasured.
- Whether one calibration can serve all five questions and four languages, or must be done per
  question and language. Per-cell counts in our run (ru 12, en 5 yes facts) are far too small.
- How correlated the strong escalation model's errors are with DeepSeek's on our lines. The 97-item
  key/referee split could estimate this.
- The key's own error rate (4.4% needed the referee) bounds how precisely any 99% claim can be
  certified. Measuring it is a prerequisite, not an option.
- Trust or Escalate's calibration size (500 / 392 items) comes from its §3.1 MathML. It could not be
  quote-checked, though the page was read.

## Sources

[^1]: https://arxiv.org/abs/2407.18370 "guarantees over 80% human agreement with almost 80% test coverage"
[^2]: https://arxiv.org/html/2407.18370 "our method achieves 91% guarantee success rate while only using GPT-4 for 17.5% of the evaluations"
[^3]: https://arxiv.org/abs/2208.02814 "We extend conformal prediction to control the expected value of any monotone loss function"
[^4]: https://arxiv.org/abs/2506.20178 "applies confidence interval methods such as Clopper-Pearson to establish a high-probability upper bound on the true error rate"
[^5]: https://arxiv.org/abs/2512.01556 "enabling the computation of a risk-constrained, retention-maximizing threshold"
[^6]: https://arxiv.org/abs/2405.10301 "via lightweight training over a moderate amount of reference data"
[^7]: https://arxiv.org/abs/2305.05176 "FrugalGPT can match the performance of the best individual LLM (e.g. GPT-4) with up to 98% cost reduction"
[^8]: https://arxiv.org/abs/2310.12963 "reducing computational cost by over 50% for comparable performance"
[^9]: https://arxiv.org/abs/2310.03094 "can achieve performance comparable to using solely the stronger LLM but require only 40% of its cost"
[^10]: https://arxiv.org/abs/2506.07962 "models agree 60% of the time when both models err"
[^11]: https://arxiv.org/abs/2605.29800 "the 9 judges effectively provide only about 2 independent votes' worth of information"
[^12]: https://arxiv.org/abs/2609.22512 "the ten judges only provide roughly as much statistical information as 3.5 independent judges"
[^13]: https://arxiv.org/abs/2607.08065 "agreement >=0.8 on 77% of GPQA case-result entries, 48% of those wrong"
[^14]: https://arxiv.org/abs/2502.09054 "Since the error patterns of small and large models are correlated"
[^15]: https://aclanthology.org/2025.emnlp-main.796/ "CheckEval dramatically improves the average agreement across evaluator models by 0.45"
[^16]: https://arxiv.org/abs/2410.03608 "decompose the instruction into a series of YES/NO questions"
[^17]: https://arxiv.org/abs/2608.20385 "Revising these items improves both raw and chance-corrected agreement"
[^18]: https://aclanthology.org/2025.emnlp-main.538/ "while its benefits are less consistent in direct scoring"
[^19]: https://arxiv.org/abs/2609.26926 "Rationale Labeling yielded the highest LLM-labeling accuracy (64.9%) against expert labels"
[^20]: https://aclanthology.org/D18-1107/ "context formed from sentences adjacent to the sentence being classified can provide important information for classification"
[^21]: https://aclanthology.org/D19-1383/ "Our approach achieves state-of-the-art results on four datasets"
[^22]: https://aclanthology.org/2025.argmining-1.15/ "Sequential heuristics outperform hierarchical models on two out of three datasets"
[^23]: https://arxiv.org/abs/2302.00093 "the model performance is dramatically decreased when irrelevant information is included"
[^24]: https://aclanthology.org/2024.tacl-1.9/ "significantly degrades when models must access relevant information in the middle of long contexts"
[^25]: https://arxiv.org/abs/1503.00302 "Knowledge fusion identifies true subject-predicate-object triples extracted by multiple information extractors from multiple information sources"
[^26]: https://ar5iv.labs.arxiv.org/html/1503.00302 "when we predict a probability above 0.9, the real accuracy of the triples is indeed high (0.94)"
[^27]: https://arxiv.org/abs/1502.03519 "We propose a way to distinguish errors made in the extraction process from factual errors in the web source per se"
[^28]: https://arxiv.org/abs/2210.02441 "This simple strategy enables the open-source GPT-J-6B model to match and exceed the performance of few-shot GPT3-175B on 15 of 20 popular benchmarks"
[^29]: https://arxiv.org/abs/2604.16413 "majority voting across prompts significantly improves reproducibility and reduces variance"
[^30]: https://arxiv.org/abs/2403.02419 "can first increase but then decrease as a function of the number of LM calls"
[^31]: https://arxiv.org/abs/2412.01690 "approaches such as Self-Consistency often provide statistically insignificant gains while becoming cost-prohibitive"
