# Reliable extraction engine: making "at most 1 wrong in 100 shown" a sound claim

Date: 2026-10-03. Serves: the no-human scholarship-fact pipeline (code finds spans, Jev picks roles,
code copies values, a second model must agree on high-stakes facts, escalation to a strong model,
abstain below the bar), measured on a model-built answer key of about 80 pages, with 1 in 20
production decisions re-audited.

## Scope (the sub-questions actually answered)

1. How do you pick an accept threshold so that precision on shown facts is at least 0.99 with a
   stated confidence, from a finite calibration set, and how many calibration items does it take?
2. When does "two models must agree" raise precision, and how do you measure error correlation?
3. What does a model-built answer key let you claim, given its own error rate and LLM-judge biases?
4. Which sequential test detects precision falling below 0.99 in production, and how many audits per
   week does it need?
5. Per-language / per-site thresholds: pooled or stratified, and what to do with too few samples?
6. What do industrial knowledge-base builders (Knowledge Vault, DeepDive, Snorkel) do?

## Recipe (the answer)

1. **Threshold: Learn-then-Test with an exact binomial bound and fixed-sequence testing**, one
   threshold per (fact type, stratum). For each candidate threshold, from strictest to loosest,
   compute the exact (Clopper-Pearson) one-sided upper bound on the error rate *among accepted
   calibration items*; stop at the last threshold whose bound is still at or below the target. This
   is exactly the procedure in Trust or Escalate and in MAPIE's `BinaryClassificationController`.
2. **Sample size (derived arithmetic, see table below):** to claim error at most 1% with 95%
   confidence you need at least **299 accepted** calibration items with **0 errors**, 473 with one
   error, 628 with two. "Never wrong" cannot be certified; the honest form is a stricter target:
   0.2% needs 1,497 clean accepted items, 0.1% needs 2,995. An 80-page key does not reach 299
   accepted items per (language x fact type) for most strata, so most strata must abstain or pool.
3. **Agreement rule:** accept a high-stakes fact only when both readers pick the same role and the
   same verbatim value, and calibrate the **joint rule end to end** as one selective classifier
   (score = the lower of the two calibrated confidences, gated on agreement). Never compute its
   precision by multiplying the two error rates: LLM errors are strongly correlated.
4. **Monitoring:** a one-sided Bernoulli SPRT/CUSUM on audited decisions (H0: error 1%, H1: 3%), or an
   anytime-valid confidence sequence (MAPIE `RiskMonitoring`). Detecting 1% -> 3% takes about 180
   audits on average; 1% -> 2% about 600. At 1 audit in 20, that is about 3,600 or 12,000 shown
   decisions per stratum being monitored; below that volume, raise the audit rate for high-stakes types.
5. **Too few samples in a language:** do not borrow the pooled threshold silently. In order: cluster
   strata whose score distributions look alike and certify the cluster; use a multi-group guarantee;
   otherwise hide high-stakes facts in that language until it has 299 accepted calibration items.
6. **The key's error is the floor on what you can claim.** If the key is wrong on k% of items, a
   measured 1% error rate means the true rate is anywhere from about 0 to about 1% + k%, and
   correlated key/pipeline errors are invisible. The guarantee is "agrees with the key at 99%", not
   "true at 99%", unless the key itself is shown to be wrong well under 1% of the time.

## 1. Selective prediction with a guaranteed risk

### Methods

- **Conformal risk control (CRC):** "We extend conformal prediction to control the expected value of
  any monotone loss function."[^1] It also offers "extensions of the idea to distribution shift,
  quantile risk control, multiple and adversarial risk control".[^2] CRC bounds the *expected* risk
  over calibration draws, which is weaker than the high-probability bound below.
- **Learn-then-Test (LTT):** the aim is "so that their predictions satisfy explicit, finite-sample
  statistical guarantees"[^3], and "Our main insight is to reframe the risk-control problem as
  multiple hypothesis testing".[^4] LTT does not need the risk to be monotone, which matters because
  precision is not monotone in the threshold.
- **Risk-controlling prediction sets (RCPS):** "Our approach provides explicit finite-sample
  guarantees for any dataset by using a holdout set to calibrate".[^5]
- **Selection with guaranteed risk (SGR):** "At test time, the classifier rejects instances as needed,
  to grant the desired risk (with high probability)."[^6] Its headline result: "an unprecedented 2%
  error in top-5 ImageNet classification can be guaranteed with probability 99.9%, and almost 60%
  test coverage".[^7]
- **Applied to LLM abstention:** conformal abstention gives "an abstention procedure that benefits
  from rigorous theoretical guarantees on the hallucination rate (error rate)".[^8]

### The concrete threshold procedure (Trust or Escalate, which is the closest analogue to this pipeline)

Trust or Escalate (Jung et al.) fixes the threshold on a model's confidence so that precision among
accepted items is guaranteed with probability 1 - delta over the calibration draw. The empirical risk
counts errors among accepted calibration items only, and "Since the empirical risk is a binomial
random variable with"[^9] n(lambda) trials, they take the exact binomial upper confidence bound.
Because risk roughly falls as the threshold rises, "This allows us to use fixed sequence testing"[^10]:
test from the strictest threshold downward and stop at the last one whose bound is within target.
They "adopt fixed-sequence testing instead of Bonferroni correction, which may be too conservative
for a large hypothesis space"[^11], and the guarantee holds "with high probability that the risk is
below" the target, conditional on the calibration data.[^12] The cascade matches this pipeline's
escalation step: "we use cheaper models as initial judges and escalate to stronger models only when
necessary -- again, while still providing a provable guarantee of human agreement".[^13]

Library: MAPIE implements this. In its precision example "the highest threshold values are considered
invalid due to the small number of observations used to compute the precision, following the Learn
Then Test procedure"[^14], and "the naive threshold results in a precision on the test set that is
lower than the target precision".[^15] Its LLM-as-judge example sets two thresholds (an abstain band)
because "we want to control the precision of the non-abstained predictions while minimizing the
abstention rate".[^16] That two-threshold, multi-risk setup fits closed-option roles directly.

Use the exact binomial bound, not a normal approximation: NIST notes that near-zero failure counts make
"symmetical confidence limits that are approximated using the normal distribution may not be accurate
enough for some applications".[^17]

### Calibration sample sizes (derived, not quoted)

Exact one-sided Clopper-Pearson, confidence 95% (delta = 0.05). n is the number of **accepted**
calibration items in the stratum (n(lambda) above), not the number of pages or candidates.

| Target error among shown | Errors observed in calibration | Minimum accepted items n |
|---|---|---|
| 1% | 0 | 299 (ln 0.05 / ln 0.99 = 298.07) |
| 1% | 1 | 473 |
| 1% | 2 | 628 |
| 1% | 3 | about 774 |
| 1%, at 99% confidence | 0 | 459 |
| 0.5% | 0 | 598 |
| 0.2% (stand-in for "never wrong") | 0 | 1,497 |
| 0.1% | 0 | 2,995 |

Consequences for this design:

- Every row is **per stratum** (fact type x language, and site family if thresholds differ). To make
  all K strata hold at once, run each at delta / K (Bonferroni across strata). That is standard
  practice, not something these sources state.
- **Unverified (my reasoning, no source fetched):** facts from one page share a template and an
  author, so they are not independent draws. Count a page once per fact type, or treat the page as
  the sampling unit, or n overstates the evidence.
- An 80-page key yields at most a few hundred deadlines across all languages. That can certify a
  pooled 1% at best, and certifies nothing per language. The "deadline / eligible / document list
  never wrong" target needs on the order of 1,500 to 3,000 clean accepted items per stratum.

## 2. Multi-reader agreement

- **Agreement helps only as much as errors are independent, and LLM errors are not.** In 350+ LLMs,
  "models agree 60% of the time when both models err".[^18] Diversity is no cure: "larger and more
  accurate models have highly correlated errors, even with distinct architectures and
  providers"[^19], and correlation is driven by "shared architectures and providers".[^20] Goel et al.
  find "model mistakes are becoming more similar with increasing capabilities, pointing to risks from
  correlated failures".[^21]
- **What agreement buys, as arithmetic (derived):** the agreed-and-wrong rate is P(both wrong) x
  P(same wrong answer | both wrong). Under independence with 5% error each and a 0.6 same-answer rate
  that is 0.05 x 0.05 x 0.6 = 0.15%. Under realistic correlation, P(both wrong) can approach the
  smaller of the two error rates, giving up to 3%. Only measurement on labelled data tells you where
  you are, which is why the joint rule must be calibrated as one unit (recipe step 3). Verbatim value
  copying narrows the answer space for dates and amounts, which pushes the same-answer rate *up*.
- **How to measure correlation on the key:**
  (a) the 2x2 table of (A wrong, B wrong) per fact type, reporting the lift P(B wrong | A wrong) /
  P(B wrong); (b) the error-agreement rate when both are wrong (Kim et al.'s metric above);
  (c) CAPA, "Chance Adjusted Probabilistic Agreement (CAPA): a metric for LM similarity based on
  overlap in model mistakes".[^22] Pick the second reader to minimise (b) and (c), not to maximise its
  own accuracy.
- Weak-supervision systems model this explicitly: Snorkel's labeling functions "can have unknown
  accuracies and correlations"[^23], and "The generative model's dependency structure directly
  affects the quality of the estimated labels".[^24]

## 3. A model-built answer key

- **Known judge biases:** Zheng et al. list "including position, verbosity, and self-enhancement
  biases, as well as limited reasoning ability".[^25] Self-preference means "an LLM evaluator scores its
  own outputs higher than others' while human annotators consider them of equal quality".[^26]
  Similarity generalises it: "LLM-as-a-judge scores favor models similar to the judge".[^27] A referee
  from the same family as either pipeline reader will tend to ratify that reader's errors.
- **Overconfidence of judges:** "while an LLM judge can be as accurate as a single human annotator, it
  tends to be over-confident in estimating its agreement with the majority of annotators".[^28]
- **Key errors are the norm, even in human-built benchmarks:** "we estimate an average of at least
  3.3% errors across the 10 datasets".[^29] A key wrong at that rate cannot resolve a 1% target.
- **How the key's error bounds the claim (derived):** with key error rate k, the observed error rate
  is roughly e + k - 2·(errors the key and pipeline share), so a measured 1% means the true rate lies
  between about 1% - k and 1% + k, and shared errors are not seen at all. The fixes:
  1. Build the key's two readers and referee from model families **different** from Jev and the
     second reader, measured by CAPA.
  2. Audit a random sample of agreements *and* disagreements against an independent check. The 10%
     audit of agreements estimates k only if the auditor is independent of the readers.
  3. If any human-verified subset exists, prediction-powered inference combines it with the model
     labels "without making any assumptions on the machine-learning algorithm that supplies the
     predictions".[^30] **Unverified:** whether a fully human-free key can be made sound. Nothing found
     establishes it, and the Trust or Escalate guarantee is explicitly relative to the labels in its
     calibration set.

## 4. Production monitoring

- **Tooling:** Podkopaev & Ramdas design sequential tests that "allow continuous monitoring of model
  performance without increasing the false alarm rate"[^31], built on confidence sequences, "a
  sequence of confidence intervals that is uniformly valid over an unbounded time horizon".[^32]
  Anytime-valid methods "remain valid at all stopping times, accommodating continuous monitoring and
  analysis of accumulating data".[^33] MAPIE ships it as `RiskMonitoring`, which will "flag a harmful
  shift once the lower confidence bound on the online risk exceeds the threshold".[^34]
- **Classical alternative:** CUSUM charts "have been shown to be more efficient in detecting small
  shifts in the mean of a process"[^35] than Shewhart charts. For 0/1 audit outcomes, use the
  log-likelihood-ratio form: S = max(0, S + z) with z = ln(3) = +1.099 on an error and
  ln(0.97/0.99) = -0.020 on a correct audit, and alarm at h of about 3 to 4. Set h by simulation for
  the in-control run length you can tolerate. The LLR increments are my derivation; NIST gives only
  the tabular form for means.
- **Audit volume (derived, Wald SPRT, alpha 0.05, beta 0.10):**

| Shift to detect | Mean audits to decide when the shift is real | Mean audits to clear when error stays at 1% | Shown decisions at 1-in-20 |
|---|---|---|---|
| 1% -> 3% | about 180 | about 216 | about 3,600 |
| 1% -> 2% | about 607 | about 639 | about 12,100 |

  So the audits needed per week are the table value divided by how many weeks of detection delay you
  accept. Run the test per high-stakes fact type, since a deadline regression must not be diluted by
  correct amounts. The auditor's own error adds to the measured rate (section 3), so the auditor must
  be independent of the readers too.

## 5. Shift across languages and sites

- Calibration does not transfer: "the multilingual QA models are poorly calibrated for languages other
  than English".[^36] An English-dominated pooled threshold therefore under-protects the other
  languages.
- Pooled thresholds give **marginal** guarantees only. Per-stratum (Mondrian) thresholds give per-group
  guarantees but starve: "existing conformal prediction methods do not work well when there is a
  limited amount of labeled data per class".[^37] Middle paths:
  - clustered calibration, which "performs conformal prediction at the cluster level"[^38];
  - multi-group conditional guarantees, where "given a collection of subgroups, our prediction sets
    guarantee coverage over each group".[^39]
- Known covariate shift (for example a new site family whose feature mix differs) can be reweighted:
  "a weighted version of conformal prediction can be used to compute distribution-free prediction
  intervals for problems in which the test and training covariate distributions differ".[^40]
  **Unverified:** that the likelihood ratio can be estimated well enough for language shift.
- **Rule for a language with too few samples (synthesised):**
  1. Certify the cluster it joins only if its own small sample does not reject the cluster bound
     (an exact binomial test at the cluster's target).
  2. Otherwise abstain on deadline, eligibility and document-list facts in that language.
  3. Collect pages until it reaches 299 accepted items per high-stakes fact type.
  4. Monitor it as its own stratum from day one.

## 6. Industrial practice

- **Google Knowledge Vault:** "We employ supervised machine learning methods for fusing these distinct
  information sources."[^41] The system "features a probabilistic inference system that computes
  calibrated probabilities of fact correctness".[^42] **Unverified:** the specific acceptance cutoffs
  (often cited as 0.7 / 0.9) and fact counts are in the PDF, which was not fetched.
- **DeepDive:** evaluates calibration on held-out labelled data, and "DeepDive uses the holdout variables
  to evaluate its accuracy, and no holdout is used by default."[^43] It reads its calibration plots for
  "Predictions in the range of 0.4 - 0.6 mean that the system is not sure"[^44], and treats a confidence
  cutoff as a precision/recall dial: "if one is interested only in company names that are > 90%
  confident are correct, then the company names in the buckets below 0.9 are recall errors".[^45]
- **Snorkel:** "Snorkel denoises their outputs without access to ground truth"[^46], by modelling
  source accuracies and correlations. It is a way to build better training labels, not a certified
  precision guarantee; every system above still evaluates on held-out ground truth.
- **None of the three** claims a finite-sample precision guarantee without labelled holdout data. That
  is the gap the LTT layer fills, and it inherits the same dependence on the holdout's correctness.

## Search log and tools

- Exa search (risk-controlled LLM abstention papers) surfaced conformal abstention (2405.01563);
  Brave `site:arxiv.org` surfaced Trust or Escalate (2407.18370). The other methods are the canonical
  papers for the names given in the task, located by their arXiv IDs. The MAPIE pages were found from
  the MAPIE docs navigation. So the candidate list is partly from searches and partly from the task's
  own named methods, which is a limitation.
- Not used: Tavily, Context7 (MAPIE docs were fetched directly). All cited pages were fetched with
  scrapling `get` / `bulk_get`.

## Open questions

- Can a key with no human-verified subset ever certify "true at 99%" rather than "agrees with the
  model referee at 99%"? No source establishes it (section 3).
- What are Jev's actual calibration and error correlation with the second reader, per language? This
  needs measuring on the key using the section 2 metrics.
- How big is the page-level clustering effect on the effective n? Unverified; a page-level bootstrap
  on the key would size it.
- What are Knowledge Vault's acceptance thresholds? Not verified (PDF not fetched).
- Is a Bernoulli-CUSUM primary reference needed? Not fetched; the LLR increments above are derived.

## Sources

[^1]: https://arxiv.org/abs/2208.02814 "We extend conformal prediction to control the expected value of any monotone loss function."
[^2]: https://arxiv.org/abs/2208.02814 "extensions of the idea to distribution shift, quantile risk control, multiple and adversarial risk control"
[^3]: https://arxiv.org/abs/2110.01052 "so that their predictions satisfy explicit, finite-sample statistical guarantees"
[^4]: https://arxiv.org/abs/2110.01052 "Our main insight is to reframe the risk-control problem as multiple hypothesis testing"
[^5]: https://arxiv.org/abs/2101.02703 "Our approach provides explicit finite-sample guarantees for any dataset by using a holdout set to calibrate"
[^6]: https://arxiv.org/abs/1705.08500 "At test time, the classifier rejects instances as needed, to grant the desired risk (with high probability)."
[^7]: https://arxiv.org/abs/1705.08500 "an unprecedented 2% error in top-5 ImageNet classification can be guaranteed with probability 99.9%, and almost 60% test coverage"
[^8]: https://arxiv.org/abs/2405.01563 "an abstention procedure that benefits from rigorous theoretical guarantees on the hallucination rate (error rate)"
[^9]: https://arxiv.org/html/2407.18370v1 "Since the empirical risk is a binomial random variable with"
[^10]: https://arxiv.org/html/2407.18370v1 "This allows us to use fixed sequence testing"
[^11]: https://arxiv.org/html/2407.18370v1 "we adopt fixed-sequence testing instead of Bonferroni correction, which may be too conservative for a large hypothesis space"
[^12]: https://arxiv.org/html/2407.18370v1 "guarantee with high probability that the risk is below"
[^13]: https://arxiv.org/abs/2407.18370 "we use cheaper models as initial judges and escalate to stronger models only when necessary -- again, while still providing a provable guarantee of human agreement"
[^14]: https://mapie.readthedocs.io/en/stable/generated/risk_control/1-quickstart/plot_risk_control_binary_classification/ "the highest threshold values are considered invalid due to the small number of observations used to compute the precision, following the Learn Then Test procedure"
[^15]: https://mapie.readthedocs.io/en/stable/generated/risk_control/1-quickstart/plot_risk_control_binary_classification/ "the naive threshold results in a precision on the test set that is lower than the target precision"
[^16]: https://mapie.readthedocs.io/en/stable/generated/risk_control/2-advanced-analysis/plot_risk_control_llm_as_a_judge/ "we want to control the precision of the non-abstained predictions while minimizing the abstention rate"
[^17]: https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm "symmetical confidence limits that are approximated using the normal distribution may not be accurate enough for some applications"
[^18]: https://arxiv.org/abs/2506.07962 "models agree 60% of the time when both models err"
[^19]: https://arxiv.org/abs/2506.07962 "larger and more accurate models have highly correlated errors, even with distinct architectures and providers"
[^20]: https://arxiv.org/abs/2506.07962 "We identify factors driving model correlation, including shared architectures and providers."
[^21]: https://arxiv.org/abs/2502.04313 "model mistakes are becoming more similar with increasing capabilities, pointing to risks from correlated failures"
[^22]: https://arxiv.org/abs/2502.04313 "Chance Adjusted Probabilistic Agreement (CAPA): a metric for LM similarity based on overlap in model mistakes"
[^23]: https://arxiv.org/abs/1711.10160 "users write labeling functions that express arbitrary heuristics, which can have unknown accuracies and correlations"
[^24]: https://arxiv.org/abs/1703.00854 "The generative model's dependency structure directly affects the quality of the estimated labels"
[^25]: https://arxiv.org/abs/2306.05685 "including position, verbosity, and self-enhancement biases, as well as limited reasoning ability"
[^26]: https://arxiv.org/abs/2404.13076 "an LLM evaluator scores its own outputs higher than others' while human annotators consider them of equal quality"
[^27]: https://arxiv.org/abs/2502.04313 "LLM-as-a-judge scores favor models similar to the judge"
[^28]: https://arxiv.org/html/2407.18370v1 "while an LLM judge can be as accurate as a single human annotator, it tends to be over-confident in estimating its agreement with the majority of annotators"
[^29]: https://arxiv.org/abs/2103.14749 "we estimate an average of at least 3.3% errors across the 10 datasets"
[^30]: https://arxiv.org/abs/2301.09633 "without making any assumptions on the machine-learning algorithm that supplies the predictions"
[^31]: https://arxiv.org/abs/2110.06177 "allow continuous monitoring of model performance without increasing the false alarm rate"
[^32]: https://arxiv.org/abs/1810.08240 "A confidence sequence is a sequence of confidence intervals that is uniformly valid over an unbounded time horizon."
[^33]: https://arxiv.org/abs/2210.01948 "remain valid at all stopping times, accommodating continuous monitoring and analysis of accumulating data"
[^34]: https://mapie.readthedocs.io/en/stable/generated/exchangeability_testing/1-quickstart/plot_risk_monitoring/ "once the lower confidence bound on the online risk exceeds the threshold"
[^35]: https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm "have been shown to be more efficient in detecting small shifts in the mean of a process"
[^36]: https://arxiv.org/abs/2311.08669 "the multilingual QA models are poorly calibrated for languages other than English"
[^37]: https://arxiv.org/abs/2306.09335 "existing conformal prediction methods do not work well when there is a limited amount of labeled data per class"
[^38]: https://arxiv.org/abs/2306.09335 "performs conformal prediction at the cluster level"
[^39]: https://arxiv.org/abs/2305.12616 "given a collection of subgroups, our prediction sets guarantee coverage over each group"
[^40]: https://arxiv.org/abs/1904.06019 "a weighted version of conformal prediction can be used to compute distribution-free prediction intervals for problems in which the test and training covariate distributions differ"
[^41]: https://research.google/pubs/knowledge-vault-a-web-scale-approach-to-probabilistic-knowledge-fusion/ "We employ supervised machine learning methods for fusing these distinct information sources."
[^42]: https://research.google/pubs/knowledge-vault-a-web-scale-approach-to-probabilistic-knowledge-fusion/ "features a probabilistic inference system that computes calibrated probabilities of fact correctness"
[^43]: http://deepdive.stanford.edu/calibration "DeepDive uses the holdout variables to evaluate its accuracy, and no holdout is used by default."
[^44]: http://deepdive.stanford.edu/calibration "Predictions in the range of 0.4 - 0.6 mean that the system is not sure"
[^45]: http://deepdive.stanford.edu/calibration "if one is interested only in company names that are > 90% confident are correct, then the company names in the buckets below 0.9 are recall errors"
[^46]: https://arxiv.org/abs/1711.10160 "Snorkel denoises their outputs without access to ground truth"
