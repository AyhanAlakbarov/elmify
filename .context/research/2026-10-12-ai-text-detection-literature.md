# AI-text detection: literature review for the admissions-detection study

Date: 2026-10-12. Scope: the **detection** half of the review. Companion to
`docs/research/2026-09-14-letter-storytelling-evidence.md` (N-07, N-08), which this file does not
repeat: N-08 already records Liang et al.'s 61.3% TOEFL false-positive figure, the Pangram humanizer
study's headline, and the repo decision of "no detector gate, no best-of-N against a detector".
This file adds mechanisms, numbers, robustness, fairness follow-ups and admissions evidence.

## Bottom line

1. **On a 300–1,000-word formal essay, the best current classifiers report false-positive rates
   at or under 1%, but those figures come mostly from the vendors.** Independent audits disagree
   by vendor. In the one large independent benchmark (Chicago Booth / NBER 2025), Pangram met a
   0.5% false-positive cap. GPTZero lost most of its recall once text went through a humanizer.
   The open-source RoBERTa detector flagged 30–78% of human text. Zero-shot statistical methods
   (perplexity, DetectGPT, Fast-DetectGPT, Binoculars) do well on clean benchmarks. They are the
   family most exposed to paraphrase and to low-perplexity human writing.
2. **Humanizers and paraphrasers still beat most detectors, but not all of them.** RAID, DIPPER,
   Sadasivan et al. and adversarial paraphrasing (NeurIPS 2025) all show large losses in detection.
   Three defences have published evidence of recovering it: training on humanizer output
   (Pangram), retrieval of the provider's own generations (DIPPER), and long watermarked passages
   (about 800 tokens after strong human paraphrase).
3. **Watermarking is now live, and it changes the study.** Since August 2026, under the EU AI Act
   Code of Practice, Anthropic watermarks Claude text worldwide (SynthID-Text variant), and OpenAI
   watermarks ChatGPT/Codex text in the EU. OpenAI's API watermark is opt-in and off by default.
   Both detectors are restricted-access, but educational organizations are named as eligible for
   Anthropic's. OpenAI's own numbers: about 80% detection at 200 tokens and about 95% at 400
   tokens, at a 1% false-positive rate. Replacing 25% of words with synonyms drops detection to 17%.
4. **Fairness: the non-native bias is real for perplexity-style and older detectors, but it
   belongs to particular detectors, not to detection in general.** Liang et al. found a 61%
   average false-positive rate on 91 TOEFL essays. Detectors trained on representative L2 data
   (ETS on GRE essays; Turnitin, GPTZero and Pangram by their own reports) show no significant gap
   at 300 words and above. **Machine translation of a student's own text raises false positives**
   (Weber-Wulff et al.: accuracy on machine-translated human text "dropped by 20%"). Both
   OpenAI and Anthropic say their watermarks survive or can survive translation by their models.
   This is the directly relevant risk for students from Azerbaijan, Türkiye and Central Asia.
5. **Admissions-specific evidence is thin.** I found five published studies on admissions-type
   essays: Fordham (master's statements of intent), Mayo Clinic (personal statements), Lee et al.
   (undergraduate essays at a selective US university), a talent programme case study (PDF only,
   unverified), and Ghent (master's theses, not admissions). None tests non-native applicants writing master's motivation
   letters with current models and humanizers. That gap is what the planned study could fill.
   Admissions offices mostly say that humans decide, and that AI generation counts as fraud. TUM
   is the one master's-level office found saying it checks documents for AI use and rejects on
   detection.

## 1. Scope (sub-questions)

- Q1. For each detector family: mechanism, published accuracy and false-positive rate,
  behaviour at 300–1,000 words, and source.
- Q2. Which attacks (paraphrase, translation, editing, humanizers) defeat detectors, and which
  defences recover detection.
- Q3. False positives on non-native and translated English: Liang et al. and later replications.
- Q4. Published studies of detection on admissions essays or statements of purpose, and what
  admissions offices say they use detectors for.

**How the candidate list was built.** The Q1 detector list came from the brief. The Q2–Q4
follow-ups came from these searches: Exa ("research paper evaluating AI-generated text detectors
on college admissions essays or graduate statements of purpose"; "2025 paper replicating Liang et
al…"; "university admissions office official page…"; "European university master's admission
page…"; "Anthropic official statement on watermarking…"; "OpenAI 2026 announcement text
watermarking…"; "GPTZero technical report…"; "Chicago Booth 2025 Artificial Writing and Automated
Detection"). Brave was used for exact phrases (the ETS paper title, `site:tum.de`,
`site:turnitin.com`, the Natarajan and Goodman titles). Every quote below was copied from a
scrapling `get` of the cited page.

**Tools.** Scrapling, Exa and Brave were used. Tavily and Context7 were available but not needed:
no library documentation was involved. Two sources could not be fetched as plain HTML and are
marked **Unverified** below.

## 2. Q1: What detectors use, and how reliable each is

| Family | Mechanism (two sentences) | Published accuracy / FPR | At 300–1,000 words |
|---|---|---|---|
| **Perplexity / burstiness** (GLTR, early GPTZero) | Score how predictable each token is under a language model; low perplexity reads as "AI". Burstiness is how much that predictability varies across the document.[^8] | GLTR lifted human detection from 54% to 72%.[^6] GPTZero dropped perplexity/burstiness for a deep classifier in autumn 2023.[^9] | The single most bias-prone signal: low perplexity is also typical of L2 writing (Q3). |
| **Log-rank / entropy** (DetectLLM-LRR/NPR) | Use the rank of each observed token in the model's predicted distribution instead of its raw probability.[^7] | +3.9 and +1.75 AUROC points over the previous state of the art.[^7] | Not reported separately for essay lengths. |
| **DetectGPT** | Machine text sits in regions of negative curvature of the model's log-probability.[^1] Perturb the passage with T5 and compare log-probabilities. | Fake-news AUROC rose from 0.81 to 0.95.[^2] | Paraphrase collapses it (Q2: 70.3% to 4.6%).[^29] |
| **Fast-DetectGPT** | Replaces perturbation with *conditional probability curvature*, computed by sampling. | About 75% relative gain over DetectGPT, 340× faster.[^3] | Adversarial paraphrase cut its TPR at 1% FPR by 98.96%.[^73] |
| **Binoculars** | Contrasts two closely related LLMs (perplexity against cross-perplexity); needs no training data.[^4] | Over 90% of ChatGPT samples detected at 0.01% FPR.[^5] | Clean-benchmark figure; no humanizer test in the abstract. |
| **Fine-tuned RoBERTa/DeBERTa** (OpenAI's 2023 classifier, GPT-2 output detector, domain detectors) | A pretrained encoder fine-tuned on paired human and AI text.[^70] | OpenAI's own classifier: 26% TPR at 9% FPR, withdrawn in July 2023 for low accuracy.[^13][^14] Off-the-shelf RoBERTa: 30–78% FPR in an independent audit.[^18] | OpenAI: "very unreliable on short texts (below 1,000 characters)".[^15] Domain-trained BERT on Fordham statements of intent: high accuracy, but on GPT-3.5 text only (Q4).[^44][^63] |
| **Pangram** (commercial) | A transformer classifier trained with "hard negative mining with synthetic mirrors" (AI text generated to match each human text's features).[^10] | Vendor: over 38× lower error rates than competitors.[^10] Independent: the only tool meeting FPR ≤ 0.005.[^16] | Vendor and independent results agree it holds on short text and humanizers.[^16] Ghent 2026: best of four tools on humanised academic text.[^36] |
| **GPTZero** (commercial) | Since autumn 2023, a supervised deep classifier with Human / AI / Mixed classes and sentence-level heads.[^11] | Vendor: FPR "no more than 1%"; 1.1% on TOEFL.[^72] Independent: FNR around 50% or higher under StealthGPT.[^17] | Vendor says it "performs best of longer texts and English prose".[^12] |
| **Turnitin** (commercial) | Proprietary classifier, document-level and sentence-level. Method not published beyond the blog posts. | Document FPR under 1% when 20% or more of the text is AI; sentence FPR about 4%.[^19][^20] | **Refuses documents under 300 words** because of false positives below that length.[^67][^21] |
| **Originality.ai** (commercial) | **Method not published** (no primary technical report found). | Independent: second tier with GPTZero; strong AUROC, weaker on short and humanized text.[^16][^17] | Vendor numbers not verified here. |
| **Watermarks** (Kirchenbauer; SynthID-Text; Claude; OpenAI textGrain) | At generation time the sampler is biased towards a keyed pseudo-random subset of tokens ("green list", or a g-function), and the detector runs a statistical test for that bias.[^22][^24] Only the key holder can test for it. | Kirchenbauer: interpretable p-values.[^71] SynthID-Text: no quality change over nearly 20 million Gemini responses.[^25] OpenAI textGrain: about 80% at 200 tokens and about 95% at 400 tokens, at 1% FPR.[^39] | Length-bound. Anthropic: it does not work well on small samples.[^61] |

Notes on Q1.

- **Vendor figures are the vendors' own.** GPTZero's 2026 benchmark puts GPTZero first. The
  independent NBER/BFI audit puts Pangram first and finds GPTZero weak under humanizers. The
  independent audit owns that comparison. GPTZero's paper reports results on GPT-5.2, Gemini 3
  Pro, Claude Sonnet 4.5 and Grok 4 text, which the 2025 audit predates.
- **Pangram's ESL page contradicts itself.** Its table gives an overall ESL false-positive rate of
  0.012% across 25,021 texts, while its prose says 0.078%.[^35] Either way the figure is the
  vendor's.
- **Watermarks only answer "did *this provider's* model produce these words"**, and only for the
  key holder. Anthropic says its key cannot tell whether the text was written by a different
  AI.[^62] Claude's watermark is a SynthID-Text variant.[^41]

## 3. Q2: Robustness under paraphrase, translation, editing and humanizers

**Attacks that work**

- **RAID** (Dugan et al. 2024): over 6 million generations across 11 attacks. Detectors "are easily
  fooled by adversarial attacks, variations in sampling strategies, repetition penalties, and
  unseen generative models".[^27][^28]
- **DIPPER** (Krishna et al. 2023): an 11B paraphraser cut DetectGPT from 70.3% to 4.6% at 1% FPR,
  and also evaded watermarking, GPTZero and OpenAI's classifier.[^29]
- **Sadasivan et al. 2023**: recursive paraphrasing on passages of about 300 tokens. They give a
  theoretical bound linking the best possible AUROC to the total-variation distance between human
  and AI text.[^74] They also show *spoofing*: inferring watermark signatures so that human text
  gets flagged.[^32][^33]
- **Adversarial paraphrasing** (2025, arXiv 2506.07001): a detector-guided LLM paraphraser cut the
  true-positive rate at 1% FPR by 87.88% on average, across neural, watermark and zero-shot
  detectors. Simple paraphrasing *raised* detection on RADAR and Fast-DetectGPT.[^31][^73]
- **Prompted self-editing**: "Elevate the provided text by employing literary language" cut
  detection of GPT-3.5 Common App essays from 100% to 13%. The detectors were mostly GPT-2-based
  2023 tools.[^46][^47]
- **Editing in the classroom setting** (Weber-Wulff et al. 2023, 14 tools): human-edited AI text
  scored 42% accuracy against 74% unedited; Quillbot-paraphrased text scored 26%.[^66][^65]
- **Synonym edits on watermarks** (OpenAI 2026): on 400-token passages, replacing 10% of words
  dropped detection from about 92% to 66%, and replacing 25% dropped it to 17%.[^40]
- **Translation and global rewrites against watermarks**: OpenAI's 2024 watermark was "less robust
  against globalized tampering" such as translation or rewording with another model.[^76] Google:
  confidence "can be greatly reduced" after thorough rewriting or translation.[^23] Anthropic: a
  complete rewrite removes its watermark.[^42]

**Defences that recover detection**

- **Retrieval by the provider** (DIPPER paper): search a database of the API's own past outputs.
  It caught 80–97% of paraphrased generations at a 1% human false-positive rate, but it "must be
  maintained by a language model API provider".[^30]
- **Training on humanizer output** (Pangram, arXiv 2501.03437): 19 humanizers studied. "Many
  existing AI detectors fail to detect humanized text", but a detector trained with data
  augmentation stays robust, even against a model fine-tuned to beat it.[^75][^34] Independent support
  comes from the NBER/BFI audit (StealthGPT)[^16] and Ghent 2026 (prompt-humanised academic
  text).[^36] Neither independent study tested the full set of 19 humanizers.
- **Long watermarked passages**: after strong human paraphrase, a Kirchenbauer-style watermark
  was still detectable after about 800 tokens at a 1e-5 false-positive rate.[^38] A 500-word
  letter is roughly 650 tokens, so it sits at the edge of that range.
- **Model-level watermarks surviving translation**: Anthropic says a Claude *translation* carries
  the watermark, because Claude chose every word.[^43] This holds only when the provider's model
  does the translating. Translation by a different tool falls under the "globalized tampering"
  failure above.

**Unverified (403, not fetched):** Sun, Liao and Ma (2026, *Computers & Education* 105616) report
that hybrid editing let up to 88% of AI content evade 13 detectors on 280,000 student samples, and
that detectors fail on short coursework. Read from a search summary only.

## 4. Q3: Fairness to non-native writers and translated text

- **Liang et al. 2023** (91 Chinese-forum TOEFL essays, 7 detectors): average false-positive rate
  61.22%[^45]; 18 of 91 essays flagged by all seven detectors.[^48] Simplifying native 8th-grade
  essays raised false positives from 5.19% to 56.65%.[^49] Their own limitation: most of the
  detectors used GPT-2 as the backbone.[^47]
- **Disputes and replications**:
  - **ETS / GRE** (Jiang et al. 2024): detectors built on e-rater and perplexity features, with
    representative training data, "showed no evidence of bias disadvantaging non-native English
    speakers".[^50] A follow-up on 85,567 essays compared three debiasing strategies: balanced
    data, feature removal and threshold adjustment.[^51]
  - **Turnitin** (2023, vendor; ASAP, PELIC and ICNALE corpora): no significant L1/L2 gap at 300
    words and above[^68], but a significantly larger gap below 300 words.[^21] Turnitin had no
    full-length university L2 documents to test.[^52]
  - **GPTZero** (vendor): 1.1% false positives on Liang's TOEFL set.[^72]
  - **Pangram** (vendor): about 0% on four held-out ESL corpora.[^35]
  - **Natarajan et al., GenAICHI/CHI 2024 workshop** (real scholarship-programme essays,
    GPTZero): **Unverified.** It is a PDF only and could not be extracted. The search summary says
    scores varied by region and gender, and that essays from the "Five Eyes" countries scored
    *higher*, not lower. Link: <https://generativeaiandhci.github.io/papers/2024/genaichi2024_9.pdf>
- **Translated text**: human text written in Bosnian, Czech, German, Latvian, Slovak, Spanish or
  Swedish and machine-translated to English lost 20% accuracy against original English
  (96%).[^37] The authors warn that L2 students who translate their own texts risk false
  accusation.[^53] None of the cited studies covers Azerbaijani, Turkish, Kazakh, Uzbek or Russian
  source text.
- **Watermarks and fairness**: OpenAI held back its 2024 watermark partly because it "could
  stigmatize use of AI as a useful writing tool for non-native English speakers".[^26] Claude marks
  also attach to proofreading and translation.[^54] A student who has Claude translate their own
  Azerbaijani draft therefore produces watermarked text even though the ideas are theirs.

## 5. Q4: Admissions-specific evidence

**Published studies**

- **Fordham, *Scientific Reports* 2024**: 3,755 recommendation letters and 1,973 statements of
  intent from master's programmes in CS and Data Science, paired with GPT-3.5 counterparts.
  Domain-trained classifiers did very well.[^44][^63] The authors themselves say a "general and
  universally effective detection model … appears to be beyond the reach of current
  technology".[^55] Limits: GPT-3.5 only; no paraphrase or humanizer; non-native writers not
  analysed separately.
- **Mayo Clinic DPT personal statements, *J. Physical Therapy Education* 2025**: 50 real
  statements against 50 Gemini-generated ones. Two human raters reached 97% and 99%
  accuracy[^81]; GPTZero's sub-scores reached AUROC > 0.875.[^56]
- **Lee, Alvero, Joachims & Kizilcec 2025** (about 30,000 undergraduate applicants at a selective
  university): LLM essays are "linguistically distinct" from human ones, and prompting the model
  with an applicant's demographics did not close the gap.[^82][^57] This is evidence that a detectable
  signal exists, not a detector evaluation.
- **Ghent 2026**: Pangram applied to 1,163 master's *theses* (not admissions documents) flagged
  45.5%, mostly at low to moderate levels. With no ground truth, accuracy cannot be computed.[^64]
- **Natarajan et al. 2024**: **Unverified** (see Q3). The summary says GPTZero reached AUC 0.91
  but missed more than a third of AI essays at a 2% FPR. With only 2% of applicants selected, the
  authors concluded it should not be used to disqualify applicants.
- **No published study found** of detector accuracy on non-native master's motivation letters
  written with current (2025–2026) models and humanizers.

**What admissions offices say detectors are for**

- **TUM**: application documents "are thoroughly checked for the use of AI", and detection leads
  to exclusion for deception.[^58][^83] This is the only master's-level office found that states
  detection plus a sanction. It does not name a tool or a threshold.
- **Penn**: AI is used only for administrative steps, and staff make the decisions. "Artificial
  Intelligence does not do that for us."[^84][^59]
- **Yale** (admissions podcast): officers do not "spend a huge amount of energy trying to
  reverse-engineer how an essay was crafted". The essay is read against the whole file.[^60]
- **DAAD** permits AI with a declaration (already recorded in the companion note, §2.3). The
  pattern across offices is to **certify and read holistically**, not to gate on a detector score.

## 6. What this means for the study design (inference, not a finding)

- Report detector results **at a fixed low FPR** (1% or 0.5%), as RAID, DIPPER, GPTZero, NBER and
  OpenAI do. Stratify by **length band** (under 300, 300–600, 600–1,000 words) and by **writer L1**.
  Include a **machine-translated-from-L1** arm, which is where the 20% accuracy drop above was
  measured.
- **Watermarks**: Claude output carries one worldwide[^77], and the platform uses Anthropic models
  in parts of its pipeline (`ANTHROPIC_JUDGE_MODEL` in `config/settings/base.py`). Educational
  organizations are named as eligible for Anthropic's detector.[^80] OpenAI watermarks ChatGPT in
  the EU but leaves the API off by default.[^79][^78]
  Any study arm with Claude-drafted text therefore has a ground-truth signal that style
  classifiers lack. Each arm should record which provider and model wrote each draft, and whether
  OpenAI API watermarking was switched on.
- The companion note's rule stands: no detector gate and no optimisation against detectors. This
  review gives no reason to change it.

## Sources

[^1]: https://arxiv.org/abs/2301.11305 "text sampled from an LLM tends to occupy negative curvature regions of the model's log probability function"
[^2]: https://arxiv.org/abs/2301.11305 "from 0.81 AUROC for the strongest zero-shot baseline to 0.95 AUROC for DetectGPT"
[^3]: https://arxiv.org/abs/2310.05130 "not only surpasses DetectGPT by a relative around 75% in both the white-box and black-box settings but also accelerates the detection process by a factor of 340"
[^4]: https://arxiv.org/abs/2401.12070 "a score based on contrasting two closely related language models is highly accurate at separating human-generated and machine-generated text"
[^5]: https://arxiv.org/abs/2401.12070 "Binoculars detects over 90% of generated samples from ChatGPT (and other LLMs) at a false positive rate of 0.01%"
[^6]: https://arxiv.org/abs/1906.04043 "improves the human detection-rate of fake text from 54% to 72% without any prior training"
[^7]: https://arxiv.org/abs/2306.05540 "improve over the state of the art by 3.9 and 1.75 AUROC points absolute"
[^8]: https://gptzero.me/news/perplexity-and-burstiness-what-is-it/ "Burstiness, on the other hand, is a measure of how much writing patterns and text perplexities vary over the entire document."
[^9]: https://gptzero.me/news/perplexity-and-burstiness-what-is-it/ "As of autumn 2023, GPTZero no longer uses perplexity and burstiness for its AI detection because we migrated to a deep-learning based architecture."
[^10]: https://arxiv.org/abs/2402.14873 "with over 38 times lower error rates on a comprehensive benchmark comprised of 10 text domains"
[^11]: https://arxiv.org/abs/2602.13042 "introducing a hierarchical, multi-task architecture enabling a flexible taxonomy of human and AI texts"
[^12]: https://gptzero.me/technology "GPTZero performs best of longer texts and English prose"
[^13]: https://openai.com/index/new-ai-classifier-for-indicating-ai-written-text/ "As of July 20, 2023, the AI classifier is no longer available due to its low rate of accuracy."
[^14]: https://openai.com/index/new-ai-classifier-for-indicating-ai-written-text/ "while incorrectly labeling human-written text as AI-written 9% of the time (false positives)"
[^15]: https://openai.com/index/new-ai-classifier-for-indicating-ai-written-text/ "The classifier is very unreliable on short texts (below 1,000 characters)."
[^16]: https://www.nber.org/papers/w34223 "We show that Pangram is the only tool to satisfy a strict cap (FPR ≤ 0.005) without sacrificing accuracy."
[^17]: https://bfi.uchicago.edu/insights/artificial-writing-and-automated-detection/ "with GPTZero largely losing its capacity to detect AI-generated text, showing false negative rate scores around 50% and above across most genres and LLM models"
[^18]: https://bfi.uchicago.edu/insights/artificial-writing-and-automated-detection/ "misclassifying most human text with false positive rates of approximately 30-78% across scenarios"
[^19]: https://www.turnitin.com/blog/new-research-turnitin-s-ai-detector-shows-no-statistically-significant-bias-against-english-language-learners "false positive rate is less than 1% for documents with 20% or more AI writing"
[^20]: https://www.turnitin.com/blog/ai-writing-detection-update-from-turnitins-chief-product-officer "Our sentence-level false positive rate is ~4%."
[^21]: https://www.turnitin.com/blog/new-research-turnitin-s-ai-detector-shows-no-statistically-significant-bias-against-english-language-learners "This again corroborates our earlier finding that AI writing detectors require longer samples to correctly identify AI-generated content"
[^22]: https://arxiv.org/abs/2301.10226 "softly promoting use of green tokens during sampling"
[^23]: https://ai.google.dev/responsible/docs/safeguards/synthid "Detector confidence scores can be greatly reduced when an AI-generated text is thoroughly rewritten, or translated to another language."
[^24]: https://www.nature.com/articles/s41586-024-08025-4 "SynthID-Text does not affect LLM training and modifies only the sampling procedure"
[^25]: https://www.nature.com/articles/s41586-024-08025-4 "we conducted a live experiment that assessed feedback from nearly 20 million Gemini"
[^26]: https://openai.com/index/understanding-the-source-of-what-we-see-and-hear-online/ "it could stigmatize use of AI as a useful writing tool for non-native English speakers"
[^27]: https://arxiv.org/abs/2405.07940 "RAID includes over 6 million generations spanning 11 models, 8 domains, 11 adversarial attacks and 4 decoding strategies"
[^28]: https://arxiv.org/abs/2405.07940 "current detectors are easily fooled by adversarial attacks, variations in sampling strategies, repetition penalties, and unseen generative models"
[^29]: https://arxiv.org/abs/2303.13408 "DIPPER drops detection accuracy of DetectGPT from 70.3% to 4.6% (at a constant false positive rate of 1%)"
[^30]: https://arxiv.org/abs/2303.13408 "it can detect 80% to 97% of paraphrased generations across different settings while only classifying 1% of human-written sequences as AI-generated"
[^31]: https://arxiv.org/abs/2506.07001 "our attack achieves an average T@1%F reduction of 87.88% under the guidance of OpenAI-RoBERTa-Large"
[^32]: https://arxiv.org/abs/2303.11156 "Our experiments conducted on passages, each approximately 300 tokens long"
[^33]: https://arxiv.org/abs/2303.11156 "an attacker can infer hidden AI text signatures without white-box access to the detection method"
[^34]: https://arxiv.org/abs/2501.03437 "We show that many existing AI detectors fail to detect humanized text."
[^35]: https://www.pangram.com/blog/how-accurate-is-pangram-ai-detection-on-esl "Pangram's overall false positive rate is 0.078%, which is not significantly higher than our general false positive rate of 0.01%."
[^36]: https://link.springer.com/article/10.1007/s40979-026-00226-w "Results show that Pangram consistently performed better than the other tools, achieving high accuracy in detecting fully AI-generated, hybrid, and humanised texts."
[^37]: https://link.springer.com/article/10.1007/s40979-023-00146-z "that were machine-translated to English (case 02-MT), the accuracy dropped by 20%"
[^38]: https://arxiv.org/abs/2306.04634 "after strong human paraphrasing the watermark is detectable after observing 800 tokens on average, when setting a 1e-5 false positive rate"
[^39]: https://openai.com/index/eu-text-provenance/ "At a target false positive rate of 1%, our detector identified watermarks in about 80% of 200-token passages, compared with about 95% of 400-token passages"
[^40]: https://openai.com/index/eu-text-provenance/ "replacing 10% of words with synonyms reduced detection from about 92% to 66%. Replacing 25% of words reduced it to 17%."
[^41]: https://www.anthropic.com/news/claude-text-watermark "is a version of the SynthID-Text approach published by Google DeepMind"
[^42]: https://www.anthropic.com/news/claude-text-watermark "a complete rewrite where every word is replaced will"
[^43]: https://www.anthropic.com/news/claude-text-watermark "A translation produced by Claude carries a watermark, because in this case every word is chosen by Claude."
[^44]: https://www.nature.com/articles/s41598-024-77847-z "shows that specialized detection models can attain high accuracy"
[^45]: https://arxiv.org/html/2304.02819v3 "average false positive rate: 61.22%"
[^46]: https://arxiv.org/html/2304.02819v3 "significantly reduced detection rates from 100% to 13%"
[^47]: https://arxiv.org/html/2304.02819v3 "most of the detectors assessed in this study utilize GPT-2 as their underlying backbone model"
[^48]: https://arxiv.org/html/2304.02819v3 "All seven detectors unanimously identified 18 of the 91 TOEFL essays (19.78%) as AI-authored"
[^49]: https://arxiv.org/html/2304.02819v3 "from an average of 5.19% across detectors to 56.65%"
[^50]: https://www.sciencedirect.com/science/article/abs/pii/S0360131524000848 "showed no evidence of bias disadvantaging non-native English speakers"
[^51]: https://link.springer.com/chapter/10.1007/978-3-031-64312-5_38 "Leveraging a dataset comprised of 85,567 essays"
[^52]: https://www.turnitin.com/blog/new-research-turnitin-s-ai-detector-shows-no-statistically-significant-bias-against-english-language-learners "A comparable collection of publicly available full-length university level documents from L2 and L1 writers was not available for this evaluation."
[^53]: https://link.springer.com/article/10.1007/s40979-023-00146-z "using machine translation such as Google translate or DeepL can lead to a higher number of false positives"
[^54]: https://support.claude.com/en/articles/16266773-how-claude-marks-ai-generated-content "People often use Claude to proofread, translate, summarize, or convert files."
[^55]: https://www.nature.com/articles/s41598-024-77847-z "appears to be beyond the reach of current technology and detection methods"
[^56]: https://www.ovid.com/jnls/jopte/abstract/10.1097/jte.0000000000000396~human-or-machine-a-comparative-analysis-of-artificial?redirectionsource=fulltextview "GPTZero parameters including simplicity, perplexity, and readability also differentiated human- from AI-generated statements"
[^57]: https://arxiv.org/abs/2503.20062 "both types of LLM-generated essays are linguistically distinct from human-authored essays"
[^58]: https://www.tum.de/en/studies/application/application-info-portal/document-requirements/tum-style-guide "Self-created application documents are thoroughly checked for the use of AI"
[^59]: https://admissions.upenn.edu/how-to-apply/preparing-your-application/integrity-AI-in-admissions-process "Artificial Intelligence does not do that for us."
[^60]: https://admissions.yale.edu/posts/episode-34 "spend a huge amount of energy trying to reverse-engineer how an essay was crafted"
[^61]: https://www.anthropic.com/news/claude-text-watermark "work well on small samples, where there are fewer word choices and thus less information to go on"
[^62]: https://www.anthropic.com/news/claude-text-watermark "whether the text was written by a different AI"
[^63]: https://www.nature.com/articles/s41598-024-77847-z "we generated AI counterparts for each LOR and SOI using the GPT-3.5 Turbo API"
[^64]: https://link.springer.com/article/10.1007/s40979-026-00226-w "with flagged cases (45.5%) typically indicating low to moderate levels of AI-associated text"
[^65]: https://link.springer.com/article/10.1007/s40979-023-00146-z "The overall accuracy for this case was 26%, which means that most AI-generated texts remain undetected when machine-paraphrased."
[^66]: https://link.springer.com/article/10.1007/s40979-023-00146-z "generally received slightly over half the score (42%)"
[^67]: https://www.turnitin.com/blog/ai-writing-detection-update-from-turnitins-chief-product-officer "increasing the minimum word requirement from 150 to 300 words in order for a document to be evaluated by our AI writing detector"
[^68]: https://www.turnitin.com/blog/new-research-turnitin-s-ai-detector-shows-no-statistically-significant-bias-against-english-language-learners "the Turnitin AI writing detector does not appear to show a significant bias against writers for whom English is not their first language"
[^69]: https://www.turnitin.com/blog/new-research-turnitin-s-ai-detector-shows-no-statistically-significant-bias-against-english-language-learners "all of which are less than 150 words long"
[^70]: https://openai.com/index/new-ai-classifier-for-indicating-ai-written-text/ "Our classifier is a language model fine-tuned on a dataset of pairs of human-written text and AI-written text on the same topic."
[^71]: https://arxiv.org/abs/2301.10226 "We propose a statistical test for detecting the watermark with interpretable p-values"
[^72]: https://gptzero.me/technology "false positive rate on TOEFL texts to 1.1%"
[^73]: https://arxiv.org/abs/2506.07001 "reduces T@1%F by 64.49% on RADAR and a striking 98.96% on Fast-DetectGPT"
[^74]: https://arxiv.org/abs/2303.11156 "a theoretical framework connecting the AUROC of the best possible detector to the Total Variation distance between human and AI text distributions"
[^75]: https://arxiv.org/abs/2501.03437 "We study 19 AI humanizer and paraphrasing tools"
[^76]: https://openai.com/index/understanding-the-source-of-what-we-see-and-hear-online/ "it is less robust against globalized tampering; like using translation systems, rewording with another generative model"
[^77]: https://support.claude.com/en/articles/16266773-how-claude-marks-ai-generated-content "Marking will apply to output from supported models wherever Claude is offered, worldwide."
[^78]: https://openai.com/index/eu-text-provenance/ "Text watermarking will remain off by default in the API."
[^79]: https://openai.com/index/eu-text-provenance/ "Over the coming weeks, we will add an invisible watermark to eligible ChatGPT and Codex text output in the European Union."
[^80]: https://www.anthropic.com/news/claude-text-watermark "such as regulators, law enforcement, media, fact-checkers, independent researchers, educational organizations"
[^81]: https://www.ovid.com/jnls/jopte/abstract/10.1097/jte.0000000000000396~human-or-machine-a-comparative-analysis-of-artificial?redirectionsource=fulltextview "and accuracy (97% and 99%)"
[^82]: https://arxiv.org/abs/2503.20062 "essays written by 30,000 applicants to two types of LLM-generated essays"
[^83]: https://www.tum.de/en/studies/application/application-info-portal/document-requirements/tum-style-guide "your application will be rejected for deception"
[^84]: https://admissions.upenn.edu/how-to-apply/preparing-your-application/integrity-AI-in-admissions-process "We do use technology, including AI tools, to support parts of our process that are administrative rather than evaluative"

## Open questions

- **Natarajan et al. 2024** (real scholarship essays, GPTZero, regional and gender score
  differences): PDF only, could not be extracted. A human should read the PDF before citing it.
- **Sun, Liao and Ma 2026** (*Computers & Education*, 13 detectors, 280,000 student samples,
  88% evasion): the ACM page returned 403. Get the ScienceDirect copy.
- **Originality.ai's method and its own accuracy claims** were not found in a primary technical
  source.
- **Turnitin's current (2025–2026) model**: the figures here are from 2023 blog posts. No newer
  primary report was found.
- **Translation from Azerbaijani, Turkish, Kazakh, Uzbek or Russian into English**: no study
  found. The only translated-text evidence covers seven European source languages and 2023 tools.
- **Watermark detector access for universities**: Anthropic names educational organizations as
  eligible; OpenAI names approved researchers. Whether a partner university in the study qualifies,
  and at what false-positive rate the detectors operate on 300–1,000-word letters, is unpublished.
  OpenAI's figures are on ELI5 answers, not motivation letters.
- **Liang et al.'s essay length**: Turnitin says all 91 TOEFL essays were under 150 words.[^69]
  That is a claim by an interested party and was not checked against the dataset.
