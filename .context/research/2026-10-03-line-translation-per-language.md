# Translating funding-page lines into English: which tool, per language

Date: 2026-10-03. For: the one-decision-engine reader (`docs/superpowers/specs/2026-10-03-one-decision-engine-design.md`). The reader translates selected funding lines line by line, keeping line ids, and Jev answers closed questions on the English. Amounts, dates and names are copied by code. Bar: at most 1 wrong shown value in 100.

## Answer first

1. **No published benchmark measures what we need.** That is meaning flips (negation, scope, who pays, conditions) at a 1% error rate, translating *into* English. WMT24 and WMT25 rank systems mostly on English→X. FLORES-style chrF scores show the top systems within 1–2 points of each other into English for Turkish, Russian, Azerbaijani, Vietnamese, Japanese and Korean (table in section 4). A 1–2 chrF gap does not tell you which system flips fewer negations. The choice has to be made by a small live test (last section).
2. **Coverage settles the low-resource languages.** Google Cloud NMT, DeepL, Azure and Amazon all cover Azerbaijani, Kazakh, Georgian and Armenian. Google's *Translation LLM* does not list Kazakh, and it marks Armenian and Serbian as experimental. So for kk/ka/hy/az the safe first choice is a dedicated NMT API (Google NMT, or Azure at half the price). A cheap LLM is the thing to test against it, not the default.
3. **For high-resource languages (TR, RU, EU set, PT, AR, CJK, VI), frontier LLMs are now the top-ranked translators.** WMT24++ found LLMs best in all 55 languages, on automatic metrics, English→X. Whether a *cheap* LLM (DeepSeek-flash class) matches Google NMT on meaning fidelity into English is **unmeasured**. It costs about 1/40 of NMT per character, so it is worth testing first.
4. **The cheapest thing that actually buys fidelity is two independent readings, not a better single engine.** Translate each line with one NMT API and one LLM, run Jev on both English versions, and show a value only when the two answers agree. This is the same pattern the repo already uses (three readings plus unanimity in `derive.py` and `funding_judge.py`). At these prices the second reading costs about $0.20 or less per 10k characters.
5. **Most open MT models are not usable commercially.** NLLB-200, SeamlessM4T, TowerInstruct, Tower+, Aya Expanse, COMET-Kiwi and xCOMET are all CC-BY-NC(-SA). The usable ones are MADLAD-400 (Apache-2.0), OPUS-MT `tr-en` (Apache-2.0) and MetricX-24 (Apache-2.0, works without a reference, so it can flag bad lines).

## Scope (sub-questions answered)

1. Commercial APIs: coverage of our 23 languages, price, free tier, data terms.
2. WMT24/WMT25 and related papers: LLMs vs dedicated MT, and known failure modes (omission, hallucination, negation).
3. Open models: licence (commercial yes/no), size, CPU throughput.
4. Per-language X→English scores with numbers.
5. Cost and fidelity techniques for line-level translation, plus reference-free quality estimation.

**How the candidate list was built.** The four commercial APIs and the open models came from the question itself. Exa searches ("Findings of the WMT25 General MT task"; "LLM MT omissions hallucinations negation low-resource into English FLORES"; "FLORES-200 into-English per-language tables GPT-4/NLLB/Google"; "Kazakh Georgian Armenian into English FLORES+ COMET 2025") added four more: Hunyuan-MT (WMT25 constrained winner), MetricX-24 (an Apache-licensed quality-estimation model), WMT24++ and the Enis & Hopkins tables. Brave was used for DeepL pricing and support pages. Tools: Exa, Brave and scrapling were all used. scrapling cannot read ACL Anthology PDFs: it errors on the PDF bytes. So WMT findings details that exist only in PDFs are marked **Unverified** below. Tavily and Context7 were not needed.

## 1. Commercial MT APIs

### Coverage of our languages

| Language | Google NMT | Google Translation LLM | DeepL | Azure | Amazon |
|---|---|---|---|---|---|
| Turkish, Russian, German, French, Hungarian, Polish, Czech, Italian, Spanish, Dutch, Swedish, Finnish, Portuguese, Arabic, Chinese, Japanese, Korean, Vietnamese | yes | yes | yes | yes | yes |
| Azerbaijani | yes | yes | yes | yes | yes |
| Kazakh | yes | **not listed** | yes | yes | yes |
| Georgian | yes | yes | yes | yes | yes |
| Armenian | yes | **experimental** | yes | yes | yes |
| Serbian | yes | **experimental** | yes | yes (Cyrl + Latn) | yes |

- Google NMT lists Kazakh among its NMT languages.[^gnmtkk] The Translation LLM list states that "Translations from any language to any language in this list are supported".[^gllm] Kazakh does not appear in that list (checked against the full list on the same page). Armenian is marked experimental,[^gllmhy] and so is Serbian.[^gllmsr]
- DeepL Translator lists Azerbaijani, Kazakh, Georgian and Armenian.[^dlaz][^dlkk][^dlka][^dlhy] DeepL also says not every language supports glossaries.[^dlgloss] The API language page renders only in a browser. When rendered, it shows AZ, KK, KA and HY with "Translation" and "Tag Handling" only, without glossaries. That detail is **Unverified** by a plain fetch.
- Azure lists Azerbaijani (Latin), Kazakh, Georgian and Armenian for cloud text translation.[^azkk]
- Amazon lists all four.[^awslangs]

### Price and free tier (text translation, USD)

| Service | Price per 1M chars | Per 10k chars | Free tier |
|---|---|---|---|
| Google Cloud NMT | $20 over the free allowance[^gnmt] | $0.20 | first 500,000 chars/month, as a $10 credit[^gfree] |
| Google Translation LLM | $10 per 1M input chars + $10 per 1M output chars[^gllmprice] | about $0.20 (more for CJK, where the English output has more characters than the source) | shares the $10 credit |
| Google Adaptive Translation (LLM) | $25 input + $25 output[^gadaptive] | about $0.50 | — |
| Azure Translator S1 | $10 list price[^azprice] | $0.10 | 2M chars/month (F0)[^azfree] |
| Amazon Translate | $15[^awsprice] | $0.15 | 2M chars/month for the first 12 months[^awsfree] |
| DeepL API Growth | **Unverified**: about $27.50 per 1M over the included allowance, plus a $26–32.50/month base. Only third-party pages state this; the official pricing page renders only in a browser. | about $0.28 + base | Developer plan: 1M chars total, never reset[^dldev] |
| DeepSeek-flash (cheap LLM, for scale) | $0.30 per 1M input tokens (cache miss) and $1.20 per 1M output tokens at peak; off-peak is half[^dsprice] | about $0.003–0.01. **Unverified** estimate: it assumes 3–10k tokens per 10k source chars (Georgian and Armenian tokenise worst) and turns thinking mode off. | — |

Billing details that matter for line ids:
- Google bills every character sent, including markup.[^gchars]
- DeepL does not bill tag characters when `tag_handling` is `xml` or `html`.[^dltags] So `<l id="17">…</l>` wrappers cost nothing on DeepL.
- DeepSeek's thinking mode is on by default,[^dsthink] which multiplies output tokens. Turn it off for translation.

### Data retention and training

- **Google:** "does not use the content you send to train and improve" its translation features.[^gdata]
- **Azure:** text translation "doesn't store customer data".[^azdata]
- **DeepL:** Growth and Pro delete texts immediately after translation.[^dlsec] Whether the free Developer plan's text is used for training is **Unverified**.
- **Amazon:** by default it "may store and use text inputs" to improve Amazon AI, and you must set an AWS Organizations opt-out policy to stop that.[^awsdata] Of the four, Amazon is the only one where the default terms work against us.
- **DeepSeek:** terms not checked here (**Unverified**). The owner allows Chinese hosts (memory `model-choice-chinese-models.md`), and funding lines are public page text, not student data.

## 2. LLMs vs dedicated MT (WMT24, WMT25 and related work)

- **WMT24's title is the summary:** "The LLM Era Is Here but MT Is Not Solved Yet".[^wmt24] That year's evaluation covered 8 LLMs and 4 online providers.[^wmt24abs]
- **WMT25** evaluated 60 systems, 24 of them LLMs and online providers, on deliberately hard test sets.[^wmt25] The PDF findings say Gemini 2.5 Pro was the best system overall, in the top cluster for 14 language pairs. They also say automatic metrics over-rated Shy-hunyuan-MT, and that systems "still struggle with robustness". These points come from https://aclanthology.org/2025.wmt-1.22.pdf and are **Unverified** here, because the PDF could not be fetched as text.
- **Direction caveat (it matters for us):** most WMT24/25 pairs are English→X. WMT25's human-evaluated list is English→X apart from cs→uk, cs→de and ja→zh (same PDF, **Unverified**). These results tell us how strong a system is overall, not how well it translates *into* English.
- **WMT24++** extended WMT24 to 55 languages and found "LLMs are the best-performing MT systems in all 55 languages", on automatic metrics only, English→X.[^wmt24pp]
- **Low-resource caveat (older models):** across FLORES-200, GPT-3.5/4 were "under-performing traditional MT for 84.1% of languages".[^robinson] This is 2023-era evidence. It is why kk/ka/hy default to NMT in the table below until a test says otherwise.
- **Failure modes that hit our fidelity bar:**
  - Massively multilingual models "may generate hallucinated translations".[^guerreiro]
  - Omissions are "translations that do not include some of the input information".[^halomi]
  - Negation is a measured source of MT error, "in some cases resulting in quality reductions of more than 60%".[^negation]
  - None of these papers gives a negation-flip *rate* for current LLMs into English. That is an open question.

## 3. Open-source MT: licence, size, CPU

| Model | Licence | Commercial use? | Notes |
|---|---|---|---|
| NLLB-200 (600M distilled and larger) | CC-BY-NC-4.0[^nllb] | **No** | "a research model and is not released for production deployment"[^nllbprod] |
| SeamlessM4T v2 | CC-BY-NC-4.0[^seamless] | **No** | 2.3B parameters |
| TowerInstruct-7B v0.2 | CC-BY-NC-4.0[^tower] | **No** | 10 languages only |
| Tower+ 9B | cc-by-nc-sa-4.0 (in the card's metadata)[^towerplus] | **No** | covers none of az/kk/ka/hy/tr |
| Aya Expanse 8B | cc-by-nc-4.0[^aya] | **No** | |
| MADLAD-400-3B-MT | Apache 2.0[^madlad] | Yes | 400+ languages including az, kk, ka, hy. The card says it has "not been assessed for production usecases".[^madladprod] Quantized file is 1.65 GB.[^madladq] CTranslate2 runs it.[^ct2] |
| OPUS-MT `tr-en` | apache-2.0[^opustr] | Yes | Marian transformer. Licences of other OPUS-MT/Tatoeba pairs (az/kk/ka/hy→en) were not checked (**Unverified**). |
| Hunyuan-MT-7B | not shown on the model page (**Unverified**) | check the licence first | WMT25 constrained-track winner (PDF, **Unverified**) |

**CPU throughput.** CTranslate2 int8 runs an OPUS-MT base transformer at 696.1 target tokens/s on 4 threads of a c5.2xlarge.[^ct2bench] That is enough for a whole page's funding lines in under a second on CPU. MADLAD-3B will be roughly an order of magnitude slower (**Unverified**, not measured).

**Bottom line for open MT.** The only commercially licensed models covering all our languages are MADLAD-400 (research-grade per its own card) and a patchwork of OPUS-MT pairs. Neither has published into-English numbers that would beat Google NMT on our low-resource languages. They are a cost floor, not a quality option.

## 4. Per-language evidence (into English)

Source: Enis & Hopkins 2024, FLORES-200 devtest and a fresh BBC set. Score is chrF++ for X→English, comparing Google Translate, Claude 3 Opus and NLLB-54B. They warn of Claude contamination on FLORES,[^enis] which is why the uncontaminated BBC column is included.

| Language | FLORES Google / Claude / NLLB | BBC Google / Claude / NLLB |
|---|---|---|
| Turkish | 66.62 / 68.06 / 64.40[^trf] | 50.80 / 51.41 / 51.84[^trb] |
| Azerbaijani | 55.55 / 57.76 / 54.82[^azf] | 56.72 / 56.56 / 55.77[^azb] |
| Russian | 64.13 / 65.41 / 63.13[^ruf] | 55.69 / 57.45 / 55.83[^rub] |
| Vietnamese | 61.65 / 61.82 / 60.54[^vif] | — |
| Japanese | 58.32 / 58.04 / 56.26[^jaf] | — |
| Korean | 59.46 / 59.20 / 56.65[^kof] | — |
| Arabic (MSA) | 67.38 / 68.34 / 68.34[^arf] | — |

What this shows:
- The top two systems are within about 2 chrF++ for every language here, and BBC reverses the order for Turkish. So these scores cannot pick the winner on meaning fidelity.
- The same paper rates Azerbaijani a "Very Low" resource language.[^azlow] Even so, a frontier LLM matched Google on it.
- **No primary X→English numbers were found for Kazakh, Georgian, Armenian or Chinese.** See Open questions.

## 5. Techniques for our shape

- **Translate only the selected lines, numbered, in one call per page.** Enis & Hopkins used a "sentence-aligned document-level translation prompt": numbered source lines in, numbered English lines out.[^enisdoc] On their Yoruba BBC test, the document-level Claude run scored chrF++ 47.06 against 43.78 sentence by sentence.[^enisyo] That is one language, but it supports sending a page's lines together with their ids rather than as isolated strings. Line context helps with pronouns and with conditions split across lines. Check every returned id against the ids sent.
- **Cache by line hash.** Key the cache on `sha256(normalised line) + source lang + engine + engine version`. Re-reads of unchanged pages then cost nothing. This matters most on Google, which bills every character sent, whitespace included.[^gchars] The repo's page-level `content_sha256` short-circuit already covers whole unchanged pages; a line cache also covers pages where only a date changed.
- **Ids that cost nothing:** on DeepL, wrap each line in an XML tag with `tag_handling=xml`. Tags are not billed.[^dltags]
- **A literal-translation prompt for the LLM path.** No primary source measured a prompt for negation preservation, so this is design advice, **Unverified**:
  - translate literally;
  - keep every negation, "only", "not", "except", "unless" and conditional;
  - do not merge or drop lines;
  - copy numbers and names unchanged (code re-copies them anyway);
  - output JSON `{id: text}`;
  - temperature 0, thinking off.
- **Reference-free quality estimation as a flag, not a gate:**
  - MetricX-24 hybrid models "can do both reference-based and QE inference".[^metricx] The licence is apache-2.0.[^metricxlic] The README shows its training included synthetic undertranslation examples,[^metricxsyn] which matches our omission risk.
  - COMET-Kiwi and xCOMET are cc-by-nc-sa-4.0,[^kiwi][^xcomet] so they are not usable commercially.
  - QE score thresholds for a 1% error target on kk/ka/hy are unknown.
- **Two-reading agreement (recommended).** Translate with engines A and B, run Jev on both English versions, and show a value only when the answers match. Send disagreements to the existing undecided or consultant path. Back-translation is a weaker version of the same idea: one engine checking itself.

## Per-language recommendation

Costs are per 10k source characters, list price, after free tiers. The cheap-LLM cost is an estimate (see section 1). "Fallback" also means "second reader" under the two-reading design.

| Language | First choice | Fallback / second reader | Why | Cost per 10k chars (first / fallback) |
|---|---|---|---|---|
| Turkish | Google NMT | DeepSeek-flash (literal prompt) | Tie on FLORES and BBC; NMT cannot mis-follow an instruction | $0.20 / ~$0.005 |
| Azerbaijani | Google NMT | Azure | "Very Low" resource; LLMs lag on low-resource languages in general | $0.20 / $0.10 |
| Russian | DeepSeek-flash (literal prompt) | Google NMT | High-resource; LLMs at or above Google on FLORES and BBC | ~$0.005 / $0.20 |
| German, French, Italian, Spanish, Portuguese, Dutch, Polish, Czech, Hungarian, Swedish, Finnish | DeepSeek-flash | Google NMT (or DeepL, untested here) | High-resource; LLMs top WMT24++ | ~$0.005 / $0.20 |
| Kazakh | Google NMT | Azure | Not in Google's Translation LLM list; no X→en numbers found | $0.20 / $0.10 |
| Georgian | Google NMT | Azure | Low-resource; no X→en numbers found | $0.20 / $0.10 |
| Armenian | Google NMT | Azure | Experimental in Google's Translation LLM; no X→en numbers found | $0.20 / $0.10 |
| Arabic (Gulf pages are mostly MSA) | DeepSeek-flash | Google NMT | Claude ≥ Google on FLORES; dialect lines untested | ~$0.005 / $0.20 |
| Chinese | DeepSeek-flash or Qwen (**Unverified** quality) | Google NMT | Chinese-native LLMs; no X→en numbers fetched. Count output characters, not input. | ~$0.005 / $0.20 |
| Japanese, Korean | DeepSeek-flash | Google NMT | Google ≈ Claude on FLORES | ~$0.005 / $0.20 |
| Vietnamese | DeepSeek-flash | Google NMT | Google ≈ Claude on FLORES | ~$0.005 / $0.20 |
| Serbian | Google NMT | Azure (send `sr-Cyrl` or `sr-Latn` explicitly) | Experimental in Google's Translation LLM | $0.20 / $0.10 |

Amazon (data-use default) and DeepL (price, plus no per-language evidence fetched) are kept as alternates, not defaults.

## What to test live

The smallest experiment that picks between Google NMT and the cheap LLM for Turkish, Azerbaijani and Russian:

1. **Set.** Take 100 real funding lines per language (300 total) from pages already archived by the funding reader. Enrich the sample so at least 40 lines per language carry a negation, an exclusion ("except", "only"), a payer clause or a condition.
2. **Gold labels.** Write gold answers to the Jev closed questions for each line. Either a native speaker answers directly, or Jev answers on a human translation and a native speaker spot-checks 20%.
3. **Run both.** Translate each line with A = Google NMT and B = DeepSeek-flash (non-thinking, temperature 0, the literal prompt, numbered page batch). Run Jev on both.
4. **Measure, per language:**
   - wrong answers for A and for B, compared with McNemar's test on the lines where they disagree;
   - the error rate on lines where A and B agree, which is the two-reading design;
   - how often A and B disagree, which is the review load.
5. **Decide.** Zero errors in 300 lines gives a 95% upper bound of about 1% (rule of three). So 100 per language can only separate the engines; claiming the 1-in-100 bar for one engine needs about 300 lines in that language. If agreed-answer errors are 0/300 overall, adopt two-reading for all three languages and stop optimising the engine.
6. **Cost.** Under $1 in API fees. The real cost is the native-speaker labelling.

## Sources

[^gnmtkk]: https://docs.cloud.google.com/translate/docs/languages "Kazakh kk Khmer km"
[^gllm]: https://docs.cloud.google.com/translate/docs/languages "Translations from any language to any language in this list are supported"
[^gllmhy]: https://docs.cloud.google.com/translate/docs/languages "Armenian hy ⚠️ Experimental support"
[^gllmsr]: https://docs.cloud.google.com/translate/docs/languages "Serbian sr ⚠️ Experimental support"
[^dlaz]: https://support.deepl.com/hc/en-us/articles/360019925219-DeepL-Translator-languages "Azerbaijani English Irish Malagasy"
[^dlkk]: https://support.deepl.com/hc/en-us/articles/360019925219-DeepL-Translator-languages "Bhojpuri Galician Kazakh Marathi"
[^dlka]: https://support.deepl.com/hc/en-us/articles/360019925219-DeepL-Translator-languages "Bosnian Georgian Konkani Mongolian"
[^dlhy]: https://support.deepl.com/hc/en-us/articles/360019925219-DeepL-Translator-languages "Armenian Danish Icelandic Luxembourgish"
[^dlgloss]: https://support.deepl.com/hc/en-us/articles/360019925219-DeepL-Translator-languages "Not all languages mentioned in the table above are supported for the glossary"
[^azkk]: https://learn.microsoft.com/en-us/azure/ai-services/translator/language-support "Kazakh kk ✔ ✔ ✔ Khmer km"
[^awslangs]: https://docs.aws.amazon.com/translate/latest/dg/what-is-languages.html "Georgian ka German de"
[^gnmt]: https://cloud.google.com/products/translate/pricing "Over 500,000 characters per month $20.00"
[^gfree]: https://cloud.google.com/products/translate/pricing "First 500,000 characters per month Free (applied as $10 credit every month)"
[^gllmprice]: https://cloud.google.com/products/translate/pricing "If you use Translation LLM (LLM), then it is charged $10 per million characters input and $10 per million characters output, making it cost equivalent with NMT."
[^gadaptive]: https://cloud.google.com/products/translate/pricing "Adaptive translation The number of input characters per month $25.00"
[^gchars]: https://cloud.google.com/products/translate/pricing "You are charged for all characters that you include in a Cloud Translation request, even untranslated characters."
[^azprice]: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-translation "The translation list price is $10 per million characters."
[^azfree]: https://azure.microsoft.com/en-us/pricing/details/translator/ "2 million characters of any combination of standard translation and custom translation training free per month"
[^awsprice]: https://aws.amazon.com/translate/pricing/ "Standard Text Translation $15.00 per million characters"
[^awsfree]: https://aws.amazon.com/translate/pricing/ "translate up to 2M characters monthly - free for up 12 months"
[^dldev]: https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans "total translation limit of 1,000,000 characters"
[^dsprice]: https://api-docs.deepseek.com/quick_start/pricing/ "1M OUTPUT TOKENS OFF-PEAK $0.6 $1.98 PEAK $1.2 $3.96"
[^dsthink]: https://api-docs.deepseek.com/quick_start/pricing/ "Supports both non-thinking and thinking (default) modes"
[^dltags]: https://support.deepl.com/hc/en-us/articles/360020685720-Usage-count-and-billing-in-DeepL-API "the characters of the HTML or XML tags (including all their attributes and values) are not counted towards billing."
[^gdata]: https://docs.cloud.google.com/translate/data-usage "Google does not use the content you send to train and improve our Google Translation features."
[^azdata]: https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/translator/data-privacy-security "processes customer data at REST and doesn’t store customer data"
[^dlsec]: https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans "your texts are deleted immediately after the translation or improvement"
[^awsdata]: https://aws.amazon.com/translate/faqs/ "Amazon Translate may store and use text inputs processed by the service solely to provide and maintain the service and to improve and develop the quality of Amazon Translate and other Amazon machine-learning/artificial-intelligence technologies."
[^wmt24]: https://aclanthology.org/2024.wmt-1.1/ "The LLM Era Is Here but MT Is Not Solved Yet"
[^wmt24abs]: https://aclanthology.org/2024.wmt-1.1/ "we collected translations from 8 different large language models (LLMs) and 4 online translation providers"
[^wmt25]: https://aclanthology.org/2025.wmt-1.22/ "We evaluated 60 systems in total: 36 submitted by participants and 24 for which we collected translations from large language models (LLMs) and popular online translation providers."
[^wmt24pp]: https://arxiv.org/abs/2502.12404 "find that LLMs are the best-performing MT systems in all 55 languages"
[^robinson]: https://arxiv.org/abs/2309.07423 "under-performing traditional MT for 84.1% of languages we covered"
[^guerreiro]: https://arxiv.org/abs/2303.16104 "these models may generate hallucinated translations which have the potential to severely undermine user trust"
[^halomi]: https://arxiv.org/abs/2305.11746 "Omissions are translations that do not include some of the input information."
[^negation]: https://aclanthology.org/2020.findings-emnlp.345/ "in some cases resulting in quality reductions of more than 60%"
[^nllb]: https://huggingface.co/facebook/nllb-200-distilled-600M/raw/main/README.md "License: CC-BY-NC - Where to send questions or comments about the model"
[^nllbprod]: https://huggingface.co/facebook/nllb-200-distilled-600M/raw/main/README.md "NLLB-200 is a research model and is not released for production deployment."
[^seamless]: https://huggingface.co/facebook/seamless-m4t-v2-large/raw/main/README.md "license: cc-by-nc-4.0 language: - af - am"
[^tower]: https://huggingface.co/Unbabel/TowerInstruct-7B-v0.2/raw/main/README.md "**License:** CC-BY-NC-4.0, Llama 2 is licensed under"
[^towerplus]: https://huggingface.co/Unbabel/Tower-Plus-9B/raw/main/README.md "base_model: google/gemma-2-9b license: cc-by-nc-sa-4.0"
[^aya]: https://huggingface.co/CohereLabs/aya-expanse-8b "5 papers License: cc-by-nc-4.0"
[^madlad]: https://huggingface.co/google/madlad400-3b-mt/raw/main/README.md "Multilingual (400+ languages) - **License:** Apache 2.0"
[^madladprod]: https://huggingface.co/google/madlad400-3b-mt/raw/main/README.md "these research models have not been assessed"
[^madladq]: https://huggingface.co/google/madlad400-3b-mt/raw/main/README.md "We also provide a quantized model (1.65 GB vs the original 11.8 GB file)"
[^ct2]: https://raw.githubusercontent.com/OpenNMT/CTranslate2/master/README.md "Encoder-decoder models: Transformer base/big, M2M-100, NLLB, BART, mBART, Pegasus, T5, Whisper, T5Gemma, T5Gemma2, MADLAD-400"
[^opustr]: https://huggingface.co/Helsinki-NLP/opus-mt-tr-en/raw/main/README.md "license: apache-2.0 --- ### opus-mt-tr-en"
[^ct2bench]: https://raw.githubusercontent.com/OpenNMT/CTranslate2/master/README.md "- int8 | 696.1 | 516MB | 27.65"
[^enis]: https://arxiv.org/abs/2404.13813 "Though we find evidence of data contamination with Claude on FLORES-200"
[^trf]: https://arxiv.org/html/2404.13813v1 "Turkish tur_Latn 66.62 68.06 64.40"
[^trb]: https://arxiv.org/html/2404.13813v1 "Turkish tur_Latn 50.80 51.41 51.84"
[^azf]: https://arxiv.org/html/2404.13813v1 "Azerbaijani azj_Latn 55.55 57.76 54.82"
[^azb]: https://arxiv.org/html/2404.13813v1 "Azerbaijani azj_Latn 56.72 56.56 55.77"
[^ruf]: https://arxiv.org/html/2404.13813v1 "Russian rus_Cyrl 64.13 65.41 63.13"
[^rub]: https://arxiv.org/html/2404.13813v1 "Russian rus_Cyrl 55.69 57.45 55.83"
[^vif]: https://arxiv.org/html/2404.13813v1 "Vietnamese vie_Latn 61.65 61.82 60.54"
[^jaf]: https://arxiv.org/html/2404.13813v1 "Japanese jpn_Jpan 58.32 58.04 56.26"
[^kof]: https://arxiv.org/html/2404.13813v1 "Korean kor_Hang 59.46 59.20 56.65"
[^arf]: https://arxiv.org/html/2404.13813v1 "Modern Standard Arabic arb_Arab 67.38 68.34 68.34"
[^azlow]: https://arxiv.org/html/2404.13813v1 "Azerbaijani azj_Latn Latin az Turkic Common Turkic Very Low"
[^enisdoc]: https://arxiv.org/html/2404.13813v1 "An example of a sentence-aligned document-level translation prompt"
[^enisyo]: https://arxiv.org/html/2404.13813v1 "chrF++ 41.99 43.26 43.78 47.06"
[^metricx]: https://raw.githubusercontent.com/google-research/metricx/main/README.md "the MetricX-24 models are all hybrid models that can do both reference-based and QE inference"
[^metricxlic]: https://huggingface.co/google/metricx-24-hybrid-xl-v2p6 "PyTorch mt5 License: apache-2.0"
[^metricxsyn]: https://raw.githubusercontent.com/google-research/metricx/main/README.md "Candidate translation with an arbitrary sentence removed"
[^kiwi]: https://huggingface.co/Unbabel/wmt22-cometkiwi-da "COMET 94 languages License: cc-by-nc-sa-4.0"
[^xcomet]: https://huggingface.co/Unbabel/XCOMET-XL "arxiv: 2310.10482 License: cc-by-nc-sa-4.0"

## Open questions

- **X→English scores for Kazakh, Georgian, Armenian and Chinese.** No primary per-language table was found. The NLLB paper's metrics files and FLORES+ leaderboards are the next places to look.
- **Negation-flip and omission rates for current cheap LLMs (DeepSeek, Qwen, GLM) into English.** Unpublished as far as these searches went. Only the live test answers it.
- **WMT25 human-evaluation details** (Gemini 2.5 Pro best overall, robustness findings, the exact language-pair list) are in a PDF scrapling could not read. They are cited above as **Unverified**.
- **The DeepL API Growth per-character rate** ($27.50/M) is from third-party pages only. The official pricing page needs a browser.
- **Hunyuan-MT-7B licence** (it may restrict territories) was not shown on its model page.
- **OPUS-MT/Tatoeba licences and quality for `az-en`, `kk-en`, `ka-en` and `hy-en`.**
- **Whether the "1 wrong in 100" bar can be certified for kk/ka/hy at all** without about 300 labelled lines per language. Native-speaker labelling is the real cost.
