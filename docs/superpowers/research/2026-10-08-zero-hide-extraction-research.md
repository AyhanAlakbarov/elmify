# Slice 2 research: model prices, extraction accuracy evidence, techniques, latency

Retrieved 2026-10-08. "[raw]" = checked against the page's raw HTML text. "[summ]" = read through
a fetch summarizer, not checked against raw text; treat the numbers as likely but re-check before
relying on them. "UNVERIFIED" = no primary source found.

## 1. List prices and cost per page

Sources:
- Anthropic: https://platform.claude.com/docs/en/about-claude/pricing [full page text]
- OpenAI: https://developers.openai.com/api/docs/pricing (gpt-6 rows [raw]; gpt-5.x rows [summ])
- OpenAI current lineup: https://developers.openai.com/api/docs/models [summ]. It lists GPT-6 Astra
  (flagship), GPT-6.1 Sol and GPT-6 Luna as the recommended models. GPT-5.x is no longer the
  current family.
- Google: https://ai.google.dev/gemini-api/docs/pricing [raw for 3.1 Pro, 3.8 Flash, 3.5 Flash-Lite]
  and https://ai.google.dev/gemini-api/docs/models. The only Pro model is
  `gemini-3.1-pro-preview`, which is still a preview. There is no 3.5 Pro.
- DeepSeek: https://api-docs.deepseek.com/quick_start/pricing [raw]. `deepseek-flash` is
  DeepSeek-V4.1-Flash. The only V4.1 model is Flash; Pro is still `DeepSeek-V4-Pro-0813`. The
  page lists peak prices; off-peak is half (peak = 01-04 and 06-10 UTC, Mon-Fri).
- Kimi: https://platform.kimi.ai/docs/pricing/chat [summ; the table is rendered by JS].

Assumed workload: 12k input + 2k output tokens. Because thinking tokens are billed as output (the
Gemini page says "Output price (including thinking tokens)"), a second column assumes 12k input +
6k output (2k answer + 4k thinking).

| Model | $/M in / out | $/page 12k+2k | reads in $0.25 | $/page 12k+6k | reads |
|---|---|---|---|---|---|
| Claude Opus 5.5 | 4 / 20 | 0.088 | 2 | 0.168 | 1 |
| Claude Sonnet 5.5 | 2 / 10 | 0.044 | 5 | 0.084 | 2 |
| Claude Haiku 4.5 | 1 / 5 | 0.022 | 11 | 0.042 | 5 |
| Claude Haiku 5.5 (prompt <=100k) | 0.10 / 0.50 | 0.0022 | 113 | 0.0042 | 59 |
| gpt-6-astra (<=272k) | 10 / 50 | 0.220 | 1 | 0.420 | 0 |
| gpt-6.1-sol | 2 / 10 | 0.044 | 5 | 0.084 | 2 |
| gpt-6-luna | 0.10 / 0.50 | 0.0022 | 113 | 0.0042 | 59 |
| gpt-5.5 [summ] | 5 / 30 | 0.120 | 2 | 0.240 | 1 |
| gpt-5.4-mini [summ] | 0.75 / 4.50 | 0.018 | 13 | 0.036 | 6 |
| Gemini 3.1 Pro Preview (<=200k) | 2 / 12 | 0.048 | 5 | 0.096 | 2 |
| Gemini 3.8 Flash (to 2026-12-31) | 0.75 / 3.75 | 0.0165 | 15 | 0.0315 | 7 |
| Gemini 3.8 Flash (from 2027-01-01) | 1.50 / 7.50 | 0.033 | 7 | 0.063 | 3 |
| Gemini 3.5 Flash-Lite | 0.30 / 2.50 | 0.0086 | 29 | 0.0186 | 13 |
| DeepSeek V4.1 Flash, peak | 0.30 / 1.20 | 0.0060 | 41 | 0.0108 | 23 |
| DeepSeek V4.1 Flash, off-peak | 0.15 / 0.60 | 0.0030 | 83 | 0.0054 | 46 |
| DeepSeek V4 Pro, peak | 1.32 / 3.96 | 0.0238 | 10 | 0.0396 | 6 |
| Kimi K3 [summ] | 3 / 15 (cached in 0.30) | 0.066 | 3 | 0.126 | 1 |

Things that change these numbers:
- **Caching makes repeat reads of the same page cheap.** On Opus 5.5 and Sonnet 5.5 a cache hit
  costs 0.05x the input price. A 5-minute cache write costs 1.25x (Anthropic pricing page).
  Example for Sonnet 5.5: the first read costs about $0.05 (cache write plus output), and each
  later read about $0.021 (12k x $0.10/M plus 2k output). That gives about 10 reads per $0.25
  instead of 5. Output becomes the cost. Other caches: OpenAI cached input on gpt-6.1-sol is
  0.05x; Gemini context caching is 0.1x; DeepSeek cache hits are about 0.02x; Kimi K3 is 0.1x. The
  cache only pays off if every read starts with the identical page prefix, so the varying question
  wording has to come after the page.
- **Claude may count more tokens.** Anthropic says Claude 4.7+ models use a tokenizer that
  "produces approximately 30% more tokens for the same text". Each vendor counts tokens
  differently, and az/kk/ko/ru text likely costs more tokens per line than English
  (UNVERIFIED by language). Measure with each vendor's token-count endpoint on 20 real pages
  before fixing the budget.
- **Batch and Flex are 50% off** (Anthropic and OpenAI pages), but they are asynchronous, so they
  do not fit the <30 s per page target.

## 2. Published accuracy for document extraction: what exists, and where 99% is missing

- **No published result shows ≥99% field accuracy at ~100% coverage for zero-shot, open-schema
  extraction from heterogeneous web pages.** I found none, in any language. The 95-97% results
  below come either from fine-tuned in-domain models on fixed schemas, from narrow single-field
  tasks, or from agentic vendor pipelines.
- ExtractBench (Feb 2026), https://arxiv.org/html/2602.12247v2 [summ]: 35 PDFs, 12,867 fields, six
  frontier models (Gemini 3 Pro/Flash, GPT-5.2, GPT-5, Sonnet 4.5, Opus 4.5). Only 51% of outputs
  were valid JSON, and the aggregate field pass rate was 4.6%. On valid outputs only, field
  accuracy was 65-80%. "Output volume, not input length, is the binding constraint." For us:
  keep each call's output small (per-field or per-group calls, not one large JSON).
- ExtractBench enterprise (Jul 2026), https://arxiv.org/html/2607.29677v1 [summ]: 370 documents,
  4,869 pages. Best result was LlamaExtract Agentic Plus at 95.6% value F1 (8.1 c/page). Codex
  GPT-5.5 reached 93.6% (27.8 c/page) and Claude Code Opus 4.8 87.1%. Gemini 3.5 Flash fell from
  87.9% on short documents to 27.9% on long ones. **Word-level grounding F1 was below 50% even for
  the best system (46.4%)**, and plain VLMs return no grounding at all. For us: the verbatim quote
  check our code does is ahead of the field, not behind it.
- CONSTRUCT / trust scoring (Mar 2026), https://arxiv.org/html/2603.18014 [summ]: field accuracy of
  GPT-5, GPT-4.1-mini and Gemini 3 Pro/2.5 was 88.7-94.9% on financial entities, 96.6-97.9% on
  PII, 75-77.5% on insurance claims and 82.9-96.4% on table metadata. Document-level accuracy was
  only 26-77%. Even the best fields stay below 98% without filtering.
- Fine-tuned in-domain document AI: LayoutLMv3 reaches CORD F1 96.56 (base) and FUNSD 92.08
  (large), https://arxiv.org/pdf/2204.08387. These are fixed schemas, in-domain training, receipts
  and forms. They are not comparable to our setting. I found no frontier zero-shot DocILE, SROIE
  or Kleister numbers from a primary source (UNVERIFIED).
- Clinical report extraction (Sci Rep 2025), https://pmc.ncbi.nlm.nih.gov/articles/PMC12749435
  [summ]: a fine-tuned Llama-3.1-8B reached **99.0%** on breast anatomic site and 99.3% on
  laterality. That is narrow, closed-vocabulary fields with in-domain fine-tuning. Average exact
  match was 90.0%, and zero-shot GPT-4 averaged 86.1%. **A second human annotator reached only
  75.5-85.8% exact match (kappa 0.54-0.88).** For us: this matches our own finding that the
  residual errors come from how the questions are defined. Above about 95%, the limit is whether
  the label is well defined, not how well the model reads.
- Multilingual: TUMLU (https://arxiv.org/abs/2502.11020) benchmarks az, kk, tr and other Turkic
  languages on Claude, Gemini, GPT and Llama and reports gaps across languages and alphabets.
  KazMMLU-type results show English prompts beating Kazakh prompts (secondary summary,
  UNVERIFIED number). I found no extraction-specific numbers for az or kk. Expect accuracy to
  differ by language, and report it per language.

## 3. Techniques: effect size, cost multiplier, latency

| Technique | Evidence and effect | Cost multiplier | Latency |
|---|---|---|---|
| Verbatim quotes checked by code | Removes fabricated values but not wrong choices among real ones (our 2026-09-13 measurements in CLAUDE.md say the same). Anthropic Citations: "guaranteed to contain valid pointers to the provided documents"; `cited_text` "does not count toward output tokens"; with custom-content documents each block is citable on its own, so one page line per block makes line-index citations possible. **Citations cannot be combined with structured outputs** (returns a 400). https://platform.claude.com/docs/en/build-with-claude/citations | about 1x (a little more input) | none |
| Self-consistency / several samples | +3.9 to +17.9 points on reasoning benchmarks (GSM8K +17.9%), https://arxiv.org/abs/2203.11171. Applied to extraction: voting raises precision, and the union of several readers raises recall. An ensemble of 3 models beat the best single model on evidence recall, https://arxiv.org/abs/2511.07055. Our own 2026-09-13 union-of-3 run: coverage up about 1/3, variance not removed. | Nx output (input mostly cached) | parallel, so wall time is about one call |
| Verify step / Chain-of-Verification | Wikidata list precision 0.17 to 0.36 and MultiSpanQA F1 0.39 to 0.48 (Llama-65B), https://arxiv.org/html/2309.11495. Old model; no frontier replication found. | +1 to k calls | sequential: +1 call |
| Verifier ensemble / trust score (CONSTRUCT) | Five parallel verifier calls. Field-level error detection AUROC beats LLM-as-judge and logprobs (the summarizer gave no exact AUROC numbers). Aimed at sending 1-5% of cases to human review. https://arxiv.org/html/2603.18014 | about +5 cheap calls | parallel |
| Selective prediction / abstention | Two thresholds with an "undetermined" band: on glioblastoma notes, PPV 0.89 to 0.98 and specificity 0.79 to 0.96, **at a cost of 43% left undetermined** (classical ML, not LLMs). https://academic.oup.com/jamia/article/31/1/188/7285661. Conformal factuality gives 80-90% correctness guarantees while keeping most of the output, https://arxiv.org/abs/2402.10978. **No method found gives ≤1% error without giving up coverage.** | cheap | none |
| Cascade to a stronger model | FrugalGPT: matches GPT-4 at up to 98% lower cost, or +4% accuracy at the same cost, https://arxiv.org/abs/2305.05176. Fits "cheap pair agrees, so show it; they disagree, so escalate to Sonnet/Opus/gpt-6.1-sol". | 1x plus the escalation rate times the strong model's price | +1 sequential call on escalated fields |
| LLM-as-judge with a rubric | Strong judges agree with humans at about human-human level (MT-Bench), https://arxiv.org/abs/2306.05685. That is a general chat benchmark, not field extraction (no extraction-specific evidence found). | +1 call | +1 call |
| Human fixes the instruction, not the value | EvalGen "criteria drift": people only settle their criteria by grading outputs, https://arxiv.org/abs/2404.12272. This supports fixing question definitions from the errors found. | human time | offline |
| Automatic prompt optimisation | MIPRO: up to +13 points, 5 of 7 tasks better (Llama-3-8B), https://arxiv.org/abs/2406.11695. GEPA: +10% over MIPROv2, +6% over GRPO on average, up to 35x fewer rollouts, https://arxiv.org/abs/2507.19457. TextGrad: GPQA 51% to 55% (GPT-4o), https://arxiv.org/abs/2406.07496. All need a labelled dev set (we have the 1,400 lines). Gains are a few points, not the step from 0.56 to ~1.0 recall. | one-off offline spend | offline |

Reading of the evidence (my inference, not a published claim):
1. **Precision ≥0.99 is reachable by agreement plus abstention, as we already measured. Recall is
   the open problem.** The literature's tools for recall are a union over several reads or models,
   then a precision filter on each candidate (a verifier or a stronger-model cascade).
2. **No study shows ≤1% error together with ~100% coverage on open-domain extraction.** The
   published ≥99% results are narrow fields with fine-tuning. Human-human agreement on comparable
   clinical fields is 75-86%, so an owner target of "≤1% wrong, ~all shown" requires the field
   definitions to be made strict enough that two humans agree at ≥99% first. That is a
   definitions task, which matches our error analysis.

## 4. Latency (does a page finish in <30 s)

Source: Artificial Analysis (AA), https://artificialanalysis.ai/leaderboards/models [summ]. AA's
default workload is "approximately 10,000 input tokens, at least 1,500 answer tokens", close to
ours. TTFT for reasoning models counts the first *reasoning* token; time to first answer token
comes after thinking ends (https://artificialanalysis.ai/methodology/performance-benchmarking
[summ]). Estimated page time = latency + 2000 / tokens per second.

| Model (AA setting) | tok/s | latency s | about 2k-token answer |
|---|---|---|---|
| Claude Opus 5.5 (max) | 95 | 731 | fails |
| Claude Sonnet 5.5 (xhigh) | 107 | 35.9 | fails (about 55 s) |
| Claude Haiku 5.5 (low) | 178 | 9.9 | about 21 s, passes |
| Claude Haiku 5.5 (high) | 160 | 28.0 | about 40 s, fails |
| GPT-5.6 Terra (low / medium) | 85 / 92 | 1.6 / 1.8 | about 25 s, borderline |
| GPT-5.5 Instant | 129 | 0.96 | about 17 s |
| Gemini 3.1 Pro | 122 | 23.2 | about 40 s, fails |
| Gemini 3.8 Flash (high) | 125 | 24.3 | about 40 s, fails |
| Gemini 3.5 Flash-Lite | 346 | 8.6 | about 14 s |
| DeepSeek V4.1 Flash (max) | 216 | 1.1* | about 10 s |
| DeepSeek V4 Pro (max) | 100 | 1.6* | about 22 s |
| Kimi K3 (max) | 42 | 3.5* | **about 51 s, fails** |

\*A low latency on a "max" reasoning setting probably reflects the first reasoning token, not the
first answer token, so the real time is longer. UNVERIFIED; measure it.

- Haiku 4.5, gpt-6 models and the non-reasoning Sonnet/Opus 5.5 were missing from the fetched
  leaderboard (UNVERIFIED).
- Anthropic's fast mode for Opus 5.5 costs $8/$40 and speeds output "significantly" (pricing
  page; no tok/s figure given).
- **What sets latency is the thinking setting, not the model tier.** Run every model at no or low
  thinking. Fire the reads in parallel, so wall time is the slowest call, not the sum. Keep each
  call's output under about 500 tokens (per field group): at 100 tok/s that is 5 s plus TTFT.
  A sequential escalation step adds one more call.
- Kimi K3 at 42 tok/s cannot produce 2k tokens in under 30 s. Run it only on short per-field
  outputs, or replace it.
