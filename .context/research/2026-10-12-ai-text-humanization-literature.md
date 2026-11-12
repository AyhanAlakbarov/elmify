# How AI text is made to look human, and what it costs: literature review for the detector study

Date: 2026-10-12. Scope: the attack side a detector study has to model. Papers first, then
official/benchmark pages, then code. Not repeated here (already in the repo): N-08/N-09 and §2.5 of
`docs/research/2026-09-14-letter-storytelling-evidence.md`, and
`docs/research/2026-08-21-humanizer-assessment.md` (blader/humanizer, no-ai-slop, StoryScope,
TinyStyler meaning floors, Lynote T5, `desklib`).

## Sub-questions

1. For each technique family: how it works, measured effect on named detectors, measured meaning or
   quality loss.
2. Which families still work against three defences: retrieval, detectors trained on humanizer
   output, watermark detection.
3. Open-source tools: licence, maintenance, does the code match the README, anything malicious.
4. Published norms for labelling and sharing red-team samples with the defenders.

## How the candidate list was built

- Exa `web_search_advanced_exa`, `includeDomains` arxiv.org + aclanthology.org: "attacks that make
  AI-generated text evade detectors ... measuring meaning preservation". This produced TH-Bench, DAMAGE,
  DIPPER, soft prompts, CoPA, Stumbling Blocks, Adversarial Paraphrasing, SilverSpeak, TempParaphraser,
  HMGC, proxy attack, StealthRL and MASH.
- Exa, `includeDomains` github.com: "open-source repository that humanizes AI text or attacks
  detectors". This produced the tool list in Q3.
- Brave `site:arxiv.org` "back-translation" OR "round-trip translation": ESPERANTO, SynGuard, the
  ELOQUENT 2026 Voight-Kampff paper.
- Exa, arxiv/aclanthology: "ethics or responsible disclosure for attacks on AI text detectors". This
  produced Safe Harbor, NLP Security and Ethics, and RAID.
- Exa `web_search_exa`: ELOQUENT/PAN Voight-Kampff task pages.
- GitHub MCP (`search_repositories`, `get_file_contents`): repo metadata and code reads.

Tools: Exa, Brave, scrapling and the GitHub MCP were used. Tavily and Context7 were available but not
needed. Every quote below was copied from a scrapling `get` of the cited page. Repo licence, push date
and star fields come from the GitHub REST API (via the GitHub MCP, read 2026-10-12). They are marked
**[API]** and have no footnote, because the quote check cannot read JSON.

## Answer in brief

- **Every attack family costs meaning or fluency. The ones that keep both are detector-guided.**
  Recursive paraphrasing evades the most but degrades the text most. Prompt-only rewriting keeps
  quality and mostly fails. Detector-guided or RL-trained paraphrasers (Adversarial Paraphrasing,
  StealthRL, MASH) report both high evasion and small quality loss. They are research code, and they
  need a detector to optimise against.
- **Commercial humanizers mostly damage text.** Pangram's audit of 19 tools found the low tier
  distorting meaning and hallucinating citations. GPT-4o preferred even the best tier's output to the
  original only 26% of the time.
- **The defences:**
  - Retrieval catches paraphrase, but only for the API provider that keeps the generation log.
  - A detector trained on humanizer output recovers most humanized text, at least in its vendor's own
    evaluation.
  - Watermarks fall to a paraphrase on short text and survive on long text.
  - In 2026 the evasion that still works pushes text *out* of the detector's training distribution
    (old registers, stream of consciousness), not toward "human-like".
- **No published framework covers labelling and sharing red-team samples with detector builders.**
  The working models are shared tasks (PAN/ELOQUENT builder-breaker, RAID's hidden-label leaderboard)
  and general AI flaw-disclosure proposals.

## Q1. Technique families

### 1a. Paraphrase models (DIPPER, recursive paraphrasing)

- **How it works.** DIPPER is an 11B-parameter paraphraser. It rewrites whole paragraphs, can
  condition on surrounding context, and has knobs for lexical diversity and reordering. Recursive
  paraphrasing feeds the output back through a paraphraser several times; TH-Bench used depth 5 on
  DIPPER.
- **Effect on detectors.** DIPPER cut DetectGPT from 70.3% to 4.6% detection at 1% FPR, with
  semantics reportedly not "appreciably" changed.[^1] It also evaded watermarking, GPTZero and
  OpenAI's classifier.[^1] Sadasivan et al. report that recursive paraphrasing cuts detection
  "significantly" across watermark, neural, zero-shot and retrieval detectors.[^2]
- **Meaning and quality loss.** The independent benchmark disagrees with the authors' "slight
  degradation" claim.[^2] TH-Bench measured recursion at cosine similarity below 0.65 and ROUGE-L below
  0.3, "a notable loss in semantic consistency".[^3] On STEM text perplexity nearly quadrupled (31 to
  126). Plain DIPPER keeps similarity high (CS about 0.73–0.88 across six datasets) but "performs
  poorly in attack effectiveness".[^4] TH-Bench measured on 2025-era detectors; the source papers used
  their own settings.
- **Detector-guided paraphrase (2025–2026).** Adversarial Paraphrasing uses an off-the-shelf
  instruction LLM, steered token by token by a detector. It cut Fast-DetectGPT's TPR@1%FPR by 98.96%
  and RADAR's by 64.49%, "with mostly a slight degradation in text quality". The same paper found that
  simple paraphrasing *raised* detection on both detectors.[^5] StealthRL trains a Qwen3-4B paraphrase
  policy (GRPO) against a detector ensemble. It reports a 97.6% attack success rate, mean AUROC down
  from 0.79 to 0.43, and transfer to two held-out detectors.[^6] Quality was judged by an LLM on a
  Likert scale, not by humans.[^6]

### 1b. Prompt-level methods (style prompts, persona, "write like a human")

- **How it works.** The generating model is told how to write: a hand prompt, or one optimised
  automatically. SICO builds the prompt from about 40 human examples, using substituted in-context
  examples.[^7]
- **Effect on detectors.**
  - SICO lowered six detectors' AUC by 0.5 on average with GPT-3.5.[^7]
  - In TH-Bench, a hand-written rewrite prompt on GPT-4o-mini "generally fails to evade detection";
    on WP text it raised Log-Likelihood AUC from 0.907 to 0.928.[^8]
  - ELOQUENT 2026 found that adversarial fine-tuning "trivially closes the 2025 winning evasion
    recipes".[^9] Prompts that push text into unusual forms (cross-decade register, modernist stream
    of consciousness) still got up to about 50x higher fool rates.[^9] Prompts that imitate human
    training data "fail completely".[^9]
  - PAN 2026's own test set already includes LLMs told to "mimic a specific human author", so style
    prompting is now in-distribution for that benchmark.[^10]
- **Meaning and quality loss.**
  - Prompt rewriting keeps fluency closest to the original in TH-Bench (perplexity within about ±2
    points) and has the best semantic similarity after RAFT/HMGC-Mis.[^8]
  - SICO reports "human-level readability and task completion rates".[^7]
  - ELOQUENT 2026 claims "preserving naturalness".[^9] This is a self-report; for a motivation letter,
    a stream-of-consciousness register is itself a quality loss.

### 1c. Token-level and sampling methods (temperature, repetition penalty, decoding-time steering)

- **How it works.** These change how tokens are chosen, not the prompt:
  - higher temperature, or a repetition penalty;
  - TempParaphraser, which imitates high-temperature output by combining several normal-temperature
    generations;[^11]
  - the proxy attack, which steers a large model at decode time with an RL-tuned "humanized" small
    model.[^12]
- **Effect on detectors.**
  - RAID found detectors "easily fooled by ... variations in sampling strategies, repetition
    penalties".[^13]
  - TempParaphraser reports an 82.5% average accuracy drop.[^11]
  - The proxy attack reports a 70.4% mean AUROC drop, with a maximum of 90.3%.[^12]
  - In TH-Bench, TOBLEND (token-level mixing of several LLMs) took ChatGPT-Detector's AUC on WP from
    0.727 to 0, but it fails against RADAR.[^4]
- **Meaning and quality loss.**
  - TempParaphraser claims "high text quality".[^11]
  - The proxy attack says quality is "preserved, even within a modest utility budget".[^12]
  - In TH-Bench, TOBLEND fell to CS 0.57–0.73 and its perplexity rose 13–24 points.[^4] TH-Bench
    lists TOBLEND and Recursion as the two methods that "perform poorly across all three aspects".[^4]

### 1d. Character and homoglyph tricks

- **How it works.** Latin letters are swapped for look-alike Cyrillic and other letters, or zero-width
  and whitespace characters are inserted. A human reader sees the same text; the tokenizer sees
  different tokens. RAID ships homoglyph, zero-width-space, whitespace, upper-lower swap, misspelling,
  article-deletion and number-swap attacks.[^14]
- **Effect on detectors.** SilverSpeak tested seven detectors (ArguGPT, Binoculars, DetectGPT,
  Fast-DetectGPT, Ghostbuster, OpenAI's detector and watermarking). The detectors collapsed into
  calling everything one class, and average MCC fell from 0.64 to −0.01.[^15]
- **Meaning and quality loss.** Nothing is lost visually. The cost is that the text is no longer
  clean Unicode. The SilverSpeak library advertises that it can "neutralize" these attacks as well as
  perform them **[API, repo description]**. No measured defence rate was found in a primary source:
  **Unverified**.

### 1e. Translation round-trips

- **How it works.** The text goes English → one or more pivot languages → English, and the
  machine-translation output replaces the model's word choice. ESPERANTO uses ten pivot languages and
  a combiner that picks among the back-translations.[^16]
- **Effect on detectors.**
  - ESPERANTO lowered TPR on nine detectors (six open, three proprietary) while it says semantics were
    retained.[^16]
  - Back-translation also significantly degrades SynthID-Text watermark detection.[^17]
  - Translation hurts the other side too. In Weber-Wulff et al., *human* texts machine-translated into
    English dropped detector accuracy by 20%, which means more false accusations.[^18] This matters
    for a non-native applicant population.
- **Meaning and quality loss.** ESPERANTO's claim of preserved meaning is the authors' own. No
  independent semantic-similarity measurement of round-trip evasion was found: **Unverified**. The
  Lynote tool (Q3) chains two LLM rewrites through Chinese and Japanese and two MT hops through
  Finnish, which compounds the drift.

### 1f. Authorship obfuscation and style transfer (STRAP, TinyStyler, MASH, style-aware paraphrase)

- **How it works.** These rewrite text to match a target style or author while trying to keep the
  content:
  - STRAP recasts style transfer as paraphrase generation;[^19]
  - TinyStyler uses an 800M model plus authorship embeddings for few-shot transfer;[^20]
  - MASH chains style-injection SFT, DPO and inference-time refinement against black-box detectors.[^21]
- **Effect on detectors.**
  - MASH: 92% average attack success over 5 detectors, 24 points above the strongest of 11
    baselines.[^21]
  - Rivera Soto et al. found that ordinary attacks (prompting through detector-guided optimisation)
    leave a stylistic fingerprint. Few-shot style-feature detectors catch them.[^22]
  - Their own style-targeted paraphraser evades every detector, including the style-based ones, but
    machine and human text "become distinguishable again" when several documents per author are
    available.[^22]
- **Meaning and quality loss.**
  - STRAP's own finding is that many style-transfer systems "warp the input's meaning".[^19]
  - MASH claims "superior linguistic quality" (self-reported).[^21]
  - TinyStyler's meaning floors are already in the repo note and are not repeated here.

### 1g. Commercial humanizers

- **How it works.** Pangram audited 19 tools, among them Undetectable AI, StealthGPT, WriteHuman,
  BypassGPT, HIX Bypass, Humbot, Quillbot and Grammarly.[^23] Some are LLMs with a "write more like a
  human" system prompt or fine-tunes. Others are rule-based synonym swappers.[^23] Two of the four most
  popular Writing GPTs in the OpenAI GPT Store were humanizers at the time.[^23]
- **Meaning and quality loss.**
  - Low-tier tools "often distorted the meaning of the text", with nonsensical phrases and
    hallucinated citations.[^23]
  - LLM-based humanizers are "more weakly grounded in the original text" than synonym swappers.[^23]
  - GPT-4o preferred the humanized text over the original 26.0% of the time for the best tier (L1),
    14.67% for L2 and 2.67% for L3.[^23] All tiers degraded quality.[^23]
  - Undetectable AI and WriteHuman are rated L3: elementary-school level, with typos or incomplete
    sentences.[^23]
- **Effect on detectors.** All results below are TPR@5%FPR on academic essays (Table 3, values copied
  from the page).[^24] Pangram's employees evaluate Pangram's own detector, so this is vendor
  evidence:

  | Detector | Plain AI text | Humanized AI text |
  |---|---|---|
  | GPTZero | 99.73% | 60.04% |
  | Binoculars | 94.15% | 28.23% |
  | Pangram's DAMAGE | 100% | 98.26% |

  Independent and older evidence: Quillbot paraphrase left detection accuracy at 26% over 14 tools,
  including Turnitin.[^18]

### 1h. Cross-family trade-off (independent benchmark)

TH-Bench ran 6 attacks against 13 detectors, 6 datasets and 11 LLMs. No attack "excels across all
three dimensions" (evasion, quality, compute).[^25] Recursion is "effective against most metric-based
detectors but fails against all model-based detectors".[^4] Its detectors are open-source. No
commercial detector was in TH-Bench.

## Q2. Which survive current defences

| Family | Retrieval defence | Detector trained on humanizer output | Watermark detection |
|---|---|---|---|
| DIPPER / paraphrase | Caught: retrieval finds 80–97% of paraphrases at 1% FPR, but only the API provider that logged the generations can run it.[^26] | Mostly caught: DAMAGE keeps 93.0% TPR@5%FPR on RAID's paraphrase split (vendor result).[^24] | Short text: survives. One DIPPER pass took SynthID TPR@1%FPR from 66.5% to 1.5% on 200-token outputs.[^24] Long text: caught. After strong *human* paraphrase, the Kirchenbauer watermark is detectable after about 800 tokens at 1e-5 FPR.[^27] |
| Recursive paraphrase | The authors say it also degrades retrieval detectors[^2] (no figure in the abstract). | Fails against all model-based detectors in TH-Bench.[^4] | Not separately measured in the sources read. |
| Detector-guided / RL paraphrase (Adversarial Paraphrasing, StealthRL, MASH) | Not evaluated in the sources read. | Mostly caught. Pangram's own detector-specific GPT-4o fine-tune humanizer was still caught on 93.2% of samples.[^24] Style detectors catch generic attacks, but not a style-targeted paraphraser on a single document.[^22] | Adversarial Paraphrasing reports reductions on watermark-based detectors too.[^5] |
| Prompt-level | n/a (new generation) | 2025 recipes are closed by adversarial fine-tuning; out-of-distribution register prompts still pass in 2026.[^9] | n/a |
| Sampling / temperature | n/a | Training on TempParaphraser-augmented data "improves detector robustness".[^11] | n/a |
| Homoglyph / zero-width | n/a | Not measured against a humanizer-trained detector in the sources read: **Unverified**. Unicode normalisation is the obvious defence, with no published rate found. | SilverSpeak also defeated a watermarking detector.[^15] |
| Round-trip translation | n/a | ESPERANTO's countermeasure detector loses only 1.85% TPR after back-translation.[^16] | SynGuard recovers 11.1% F1 over SynthID-Text.[^17] |
| Commercial humanizers | n/a | DAMAGE: 98.26% TPR@5%FPR (vendor). GPTZero: 60.04%. Binoculars: 28.23%.[^24] | Humanizers remove watermarks, per Pangram.[^24] |

Two facts for designing the study:

1. Pangram had to augment training with only the high-quality (L1) humanizers. Adding all of them
   "significantly compromised" precision; humanized text was about 0.68% of the training set.[^24]
2. PAN 2026's top detectors still show a precision/recall split. The winner had FPR 0.053 / FNR
   0.029; others had FPR 0.000 with FNR 0.067–0.170.[^10]

## Q3. Open-source tools

The descriptions, licences, push dates and stars below are **[API]**, read 2026-10-12. Nothing was
run.

| Repo | What it is | Licence | Last push | Code vs README |
|---|---|---|---|---|
| `martiansideofthemoon/ai-detection-paraphrases` | DIPPER + retrieval defence (NeurIPS 2023) | Apache-2.0 | 2023-11-09 (dormant) | Not read; official paper code[^28] |
| `vinusankars/Reliability-of-AI-text-detectors` | Recursive paraphrasing (Sadasivan) | none declared | 2023-11-16 (dormant) | Not read |
| `martiansideofthemoon/style-transfer-paraphrase` | STRAP (EMNLP 2020) | MIT | 2022-06-13 (dormant) | Not read |
| `zacharyhorvitz/TinyStyler` | TinyStyler (EMNLP 2024 Findings) | none declared | 2024-11-18 | Not read |
| `ACMCMC/silverspeak` | Homoglyph attack *and* neutraliser library | GPL-3.0 | 2026-07-07 (active) | Not read |
| `chengez/Adversarial-Paraphrasing` | Detector-guided paraphrase (NeurIPS 2025) | Apache-2.0 | 2025-06-10 | Not read |
| `suraj-ranganath/StealthRL` | RL paraphrase attack | MIT | 2026-06-01 | Not read |
| `HJJWorks/TempParaphraser` | Temperature-simulating paraphraser (EMNLP 2025) | none declared | 2025-10-28 | Not read |
| `liamdugan/raid` | RAID benchmark + 11 attack implementations | MIT | 2026-10-06 (active) | README documents `get_attack("homoglyph")` etc.[^14] |
| `lynote-ai/humanize-text` | Commercial vendor's "open-source humanizer" | MIT | 2026-10-08 (active) | **Matches; see below** |
| `rudra496/StealthHumanizer` | Next.js "bypass GPTZero, Turnitin" app, 35 LLM providers | MIT | 2026-10-09 (active) | `package.json` read only |
| `ssamba1/untell` | Now described as a "detector auditing toolkit" | MIT | 2026-09-13 | Not read; see note |
| `ADEMOLA200/Humanize-AI` | Go "undetectable AI bypass" | none declared | 2025-03-06 | Not read |
| `fromleda/text-humanizer` | Previously found not to match its README | n/a | **404 on 2026-10-12**: deleted or renamed | n/a |

Repos with no declared licence are all-rights-reserved by default, so they cannot be reused without
permission.

### Code read: `lynote-ai/humanize-text` (commit `768d304`, via the GitHub API)

- **Does what it says.** `src/standard/pipeline.py` is a four-step chain, exactly as the README says:
  1. English → Chinese, LLM rewrite;
  2. Chinese → Japanese, LLM rewrite;
  3. Japanese → Finnish, Google Translate;
  4. Finnish → English, Niutrans.[^29]
- **Defaults.** `llm_client.py` defaults to DeepSeek at temperature 1.3 [code-read], so it combines the
  sampling family (1c) with the translation family (1e). The input text is sent to three third parties:
  DeepSeek or another LLM host, Google and Niutrans.
- **Nothing hidden found.** No obfuscated code, no install hooks, and only plain `httpx` calls to the
  declared endpoints in the files read (`setup.py`, `requirements.txt`, `pipeline.py`,
  `llm_client.py`).
- **One supply-chain note.** The optional `litellm` extra allows `>=1.80.0,<1.87.0` [code-read]. That
  range spans 1.82.7 and 1.82.8, the versions compromised on 2026-03-24, which "have already been
  removed from PyPI".[^30] So it is not exploitable today. Pinning to an exact audited version is still
  the safe practice.
- **Star count.** 3,356 stars and 381 forks in under five months [API]. Exa's cached copy earlier in
  this run showed 1,596. The growth is fast, but nothing here proves inauthentic stars: **Unverified**.

### `rudra496/StealthHumanizer`

`package.json` has no `preinstall` or `postinstall` hooks. The dependencies are mainstream (next,
react, mammoth, pdfjs-dist, jspdf) [code-read]. The rest of the code was not read.

### `ssamba1/untell`

An Exa result earlier in this run described this repo as a humanizer "live-proven 100%→0% on
ZeroGPT". The current API description is an "AI-detector auditing toolkit". That is a repositioning,
not evidence of anything malicious. It is recorded because the README may not match the original
intent.

### Malicious code

None found in the files read. The only prior finding stands (`fromleda`, now gone). Coverage is
partial: only the Lynote and StealthHumanizer files listed above were read.

## Q4. Published frameworks for red-teaming detectors and sharing with defenders

| Source | What it sets up | How samples reach defenders |
|---|---|---|
| PAN × ELOQUENT Voight-Kampff (2024–2026) | Builder-breaker shared task. "PAN participants will build systems to tell human and machine apart, while ELOQUENT participants will investigate novel text generation and obfuscation methods".[^10] Breaker submissions are scored on how often they fool the detectors; detectors run sandboxed on Tira. | Research-only dataset on Zenodo: "may be used only for research purposes", with no redistribution.[^10] |
| RAID (ACL 2024) | Public benchmark: 11 attacks and 4 decoding strategies, with the data released alongside a leaderboard.[^13] Test labels are withheld. A GitHub bot scores submitted predictions, so defenders are evaluated without seeing the answers.[^14] | Public data; hidden test labels. |
| Krishna et al. (DIPPER) | Paired the attack with a defence and released both: "We open-source our models, code and data."[^26] | Attack-plus-defence release, no embargo. |
| ESPERANTO | Same attack-plus-countermeasure pattern.[^16] | 720k-text dataset "publicly shared for the benefit of the research community".[^16] |
| Lent et al., *NLP Security and Ethics, in the Wild* (TACL 2025) | Surveyed NLP-security papers against cybersecurity ethics norms and found "alarming gaps on topics like harm minimization and responsible disclosure". Proposes "white hat NLP" practices.[^31] | Not detector-specific. |
| Longpre et al., flaw disclosure for general-purpose AI (2025) | "standardized AI flaw reports and rules of engagement for researchers", plus provider disclosure programmes with legal safe harbours.[^32] | Coordinated disclosure through a standard flaw report. |
| Longpre et al., *A Safe Harbor for AI Evaluation and Red Teaming* (2024) | Asks AI developers for a legal and technical safe harbour for good-faith evaluation.[^33] | Concerns permission to test, not sample sharing. |

**Gap.** No published framework was found that is specific to *labelling and sharing evasion samples
with AI-text-detector vendors*: no embargo period, sample schema or vendor-notification norm. Shared
tasks come closest. A study can borrow three things from them:

1. a research-only licence with no redistribution (PAN);
2. hidden test labels with a scoring service (RAID);
3. a standard flaw report for each vendor (Longpre et al.).

This combination is an inference from the sources above, not a published standard.

## What this means for the study design

These points are inference and are labelled as such.

- **Label every attacked sample** with: attack family (1a–1g); tool and version or commit; parameters
  (pivot languages, temperature, recursion depth, guiding detector); the source text ID; and a meaning
  check against the source (cosine similarity plus a names-and-numbers diff). TH-Bench and DAMAGE show
  that evasion figures mean nothing without the matching quality figure.
- **Include out-of-distribution register attacks and detector-guided paraphrase.** Those are the two
  families that 2026 evidence says survive adversarially trained detectors.[^9][^5] The 2023-era
  attacks alone (DIPPER, homoglyphs) would flatter the detectors.
- **Measure false positives on translated human text as well as evasion.** Translation raises false
  accusations on human writing,[^18] and the applicants are mostly non-native writers.
- **Never send real applicant letters through third-party humanizers.** The Lynote chain alone ships
  the text to three external services. Use synthetic or consented, de-identified letters.

## Open questions

- **RAID leaderboard standings for current commercial detectors** (Pangram, GPTZero, Originality,
  Turnitin) on the homoglyph, paraphrase and zero-width splits. The leaderboard was not fetched.
- **The PAN 2026 overview paper's finding that obfuscation is "surprisingly hard".** It was seen only
  in an Exa highlight of the CEUR PDF (`ceur-ws.org/Vol-4283/paper386.pdf`), which scrapling could not
  parse: **Unverified**.
- **Which 2025 recipes were closed.** The ELOQUENT 2026 paper body names them (a Brave snippet
  mentioned Hindi back-translation plus a be-imperfect instruction). Only the abstract was quoted:
  **Unverified** beyond "2025 winning evasion recipes".
- **A measured defence rate for Unicode normalisation against homoglyph and zero-width attacks.** None
  found.
- **Independent (non-vendor) measurement of humanizer-trained detectors.** DAMAGE is Pangram grading
  Pangram.
- **Detector performance at letter length.** No paper here measured meaning loss or detection on
  motivation letters (about 500–1,000 words). Watermark results depend on length (about 800 tokens in
  Kirchenbauer et al.).
- **Code vs README for the research repos.** Not read; only the Lynote code and StealthHumanizer's
  `package.json` were inspected.

## Sources

[^1]: https://arxiv.org/abs/2303.13408 "DIPPER drops detection accuracy of DetectGPT from 70.3% to 4.6% (at a constant false positive rate of 1%), without appreciably modifying the input semantics"
[^2]: https://arxiv.org/abs/2303.11156 "while our recursive paraphrasing method can significantly reduce detection rates, it only slightly degrades text quality in many cases"
[^3]: https://arxiv.org/html/2503.08708 "with Cosine Similarity falling below 0.65 and ROUGE-L scores consistently below 0.3, indicating a notable loss in semantic consistency"
[^4]: https://arxiv.org/html/2503.08708 "Recursion proves effective against most metric-based detectors but fails against all model-based detectors"
[^5]: https://arxiv.org/abs/2506.07001 "reduces T@1%F by 64.49% on RADAR and a striking 98.96% on Fast-DetectGPT"
[^6]: https://arxiv.org/abs/2602.08934 "reducing mean AUROC from 0.79 to 0.43 and attaining a 97.6% attack success rate"
[^7]: https://arxiv.org/abs/2305.10847 "enables GPT-3.5 to successfully evade six detectors, decreasing their AUC by 0.5 on average"
[^8]: https://arxiv.org/html/2503.08708 "preserves good text quality but generally fails to evade detection across different datasets and detectors"
[^9]: https://arxiv.org/abs/2607.13565 "While adversarial fine-tuning trivially closes the 2025 winning evasion recipes"
[^10]: https://pan.webis.de/clef26/pan26-web/generated-content-analysis.html "The dataset contains copyrighted material and may be used only for research purposes."
[^11]: https://aclanthology.org/2025.emnlp-main.1607/ "TempParaphraser reduces detector accuracy by an average of 82.5% while preserving high text quality"
[^12]: https://arxiv.org/abs/2410.19230 "resulting in an average AUROC drop of 70.4% across multiple datasets, with a maximum drop of 90.3% on a single dataset"
[^13]: https://arxiv.org/abs/2405.07940 "current detectors are easily fooled by adversarial attacks, variations in sampling strategies, repetition penalties, and unseen generative models"
[^14]: https://github.com/liamdugan/raid "Our GitHub bot will automatically run evaluations on the submitted predictions"
[^15]: https://arxiv.org/abs/2406.11239 "decreasing the average Matthews Correlation Coefficient from 0.64 to -0.01"
[^16]: https://arxiv.org/abs/2409.14285 "Our results indicate that the TPR of the proposed method declines by only 1.85% after back-translation manipulation"
[^17]: https://arxiv.org/abs/2508.20228 "SynthID-Text is vulnerable to meaning-preserving attacks, such as paraphrasing, copy-paste modifications, and back-translation"
[^18]: https://link.springer.com/article/10.1007/s40979-023-00146-z "The overall accuracy for this case was 26%, which means that most AI-generated texts remain undetected when machine-paraphrased."
[^19]: https://arxiv.org/abs/2010.05700 "we reformulate unsupervised style transfer as a paraphrase generation problem"
[^20]: https://arxiv.org/abs/2406.15586 "leverages a small language model (800M params) and pre-trained authorship embeddings to perform efficient, few-shot text style transfer"
[^21]: https://aclanthology.org/2026.findings-acl.1487/ "MASH achieves an average Attack Success Rate (ASR) of 92%, surpassing the strongest baselines by an average of 24%"
[^22]: https://arxiv.org/abs/2505.14608 "as the number of documents available for analysis grows, the human and machine distributions become distinguishable again"
[^23]: https://arxiv.org/html/2501.03437 "L1 humanizers had an average Win Rate of 26.0%, L2 humanizers had an average Win Rate of 14.67%, and L3 humanizers had an average Win Rate of 2.67%."
[^24]: https://arxiv.org/html/2501.03437 "the detector is still able to detect 93.2% of the humanized AI samples"
[^25]: https://arxiv.org/abs/2503.08708 "Our findings reveal that no single evading attack excels across all three dimensions."
[^26]: https://arxiv.org/abs/2303.13408 "it can detect 80% to 97% of paraphrased generations across different settings while only classifying 1% of human-written sequences as AI-generated"
[^27]: https://arxiv.org/abs/2306.04634 "after strong human paraphrasing the watermark is detectable after observing 800 tokens on average, when setting a 1e-5 false positive rate"
[^28]: https://arxiv.org/abs/2303.13408 "We open-source our models, code and data."
[^29]: https://raw.githubusercontent.com/lynote-ai/humanize-text/main/src/standard/pipeline.py "Standard Pipeline v1.5.1 — Multi-language translation chain with LLM humanization."
[^30]: https://docs.litellm.ai/blog/security-update-march-2026 "The compromised PyPI packages were litellm==1.82.7 and litellm==1.82.8."
[^31]: https://aclanthology.org/2025.tacl-1.33/ "ultimately finding alarming gaps on topics like harm minimization and responsible disclosure"
[^32]: https://arxiv.org/abs/2503.16861 "we propose using standardized AI flaw reports and rules of engagement for researchers"
[^33]: https://arxiv.org/abs/2403.04893 "We propose that major AI developers commit to providing a legal and technical safe harbor"
