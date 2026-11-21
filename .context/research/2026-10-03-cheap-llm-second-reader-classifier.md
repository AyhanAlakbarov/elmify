# A cheap chat LLM as a closed-set "second reader": logprobs, caching, bias, prompt, thinking

Date: 2026-10-03. Question: is §3.3 of `docs/superpowers/specs/2026-10-03-one-decision-engine-design.md` sound? It says: page text as a cached prefix, one question with options as a strict `json_schema` enum, the option's probability read from `top_logprobs`, `max_tokens` capped at the longest option, reasoning off. If it is not sound, what should change?

**Short answer.** The shape is sound: one closed question per call, the page as a shared prefix, a probability read from the label token, and a bar measured per question. Six details are wrong, missing or unbuildable as written:

1. Neither DeepSeek's own API nor Z.ai's offers a strict `json_schema`.
2. GLM-5.3-Flash cannot turn thinking off.
3. Thinking is **on by default** on DeepSeek V4.1 Flash.
4. "`max_tokens` = longest option" is too tight once the JSON wrapper is counted, and fails silently if reasoning is still on.
5. Putting the page and the question in one message defeats OpenRouter's sticky routing.
6. The probability must be read at the token where the labels diverge, renormalised over the allowed labels, with labels designed so that token is unique.

Details are below, then the rules and the §3.3 edits.

## How this was researched

- **Sources.** Vendor docs were fetched live with scrapling: DeepSeek (api-docs.deepseek.com), OpenRouter, OpenAI (developers.openai.com), Alibaba Model Studio (alibabacloud.com) plus QwenCloud's API reference (docs.qwencloud.com; I assume Alibaba owns it, **Unverified**), Z.ai (docs.z.ai, read through its `.md` endpoints because the HTML pages render client-side) and vLLM. Papers were read from their arXiv abstract pages.
- **Discovery.** One Exa search found the Alibaba pages. One Brave `site:docs.z.ai` search and one `site:docs.vllm.ai` search found those pages.
- **Where the paper list came from.** The question asked for named papers (FrugalGPT, AutoMix and so on), so the paper list is from memory, not from searches. Each paper was then opened on arXiv and is quoted only from that page.
- **Tools not used.** Context7 and Tavily were available but not needed. The `ide` MCP server failed to connect; it is irrelevant here.

## 1. Logprobs under JSON / json_schema

**Where each host stands:**

| Host (first party) | Strict `json_schema` | `logprobs` / `top_logprobs` | Thinking off possible |
|---|---|---|---|
| DeepSeek API | No: `response_format` "must be one of text or json_object"[^1] | Yes, up to 20[^2] | Yes, but **on by default**[^6] |
| Z.ai (GLM) | No: text or json_object only[^39] | No such parameter in its chat API (read from the OpenAPI spec[^39]) | **No** for GLM-5.3 / GLM-5.3-Flash[^38] |
| Alibaba (Qwen) | Yes, on a narrower model list[^33] | Yes, but `top_logprobs` is capped at 5[^34] | Yes for Qwen; GLM-5.3 there always thinks[^36] |
| OpenRouter (third-party hosts) | Per endpoint[^22]; "strict" is not guaranteed everywhere[^23] | Pass-through, 0–20[^25b] | Through `reasoning`; see §5 |

**Whether one host returns logprobs together with strict structured output is not documented anywhere, for any candidate.** OpenRouter's `require_parameters` restricts routing to hosts that support every parameter sent[^26]. Sending `response_format` + `logprobs` + `top_logprobs` with it filters on what each host *declares*. Whether a declared host actually returns logprobs under a schema is **Unverified** and must be probed per host.

**Which token carries the label.**

- With `{"answer": <enum>}`, the output is a few fixed JSON tokens followed by the label's tokens. OpenAI documents that keys come out in schema order[^30], so `answer` must be the first key (or the only key) for nothing the model writes to come before the label.
- The probability that matters is at the **first token where the enum values differ**. That is not output position 0, and not the `{"` or `answer` tokens, whose probability is near 1 under the constraint. Which token index that is depends on the tokenizer, so find it by matching token text against the enum. **Unverified** for each host.
- This also avoids the problem papers report with "first-token" probabilities. Wang et al. found first-token probabilities and the text answer "severely misaligned … reaching mismatch rates over 60%"[^45]. A follow-up found "the text answers are more robust to question perturbations than the first token probabilities"[^46]. Reading at the label's own position, inside a constrained answer, is reading the text answer's token, not a free first token.

**Multi-token labels.**

- A sequence's probability is the sum of its tokens' logprobs[^29]. But `top_logprobs` only lists alternatives at positions on the path the model actually sampled.
- So when two labels share a first token (for example `not_stated` and `not_required` both starting with `not`), the unsampled label's later tokens are never scored, and its full probability cannot be computed from one response.
- **Design rule:** every label's first token must be unique within its enum.

**Does constrained decoding distort the probabilities?**

- In general, yes. Grammar-constrained decoding "can distort the LLM's distribution, leading to outputs that are grammatical but appear with likelihoods that are not proportional to the ones given by the LLM"[^41].
- For a single enum field decided at one token, the practical effect is narrower: the reported numbers may be the model's **raw** distribution, taken before the grammar mask. vLLM, a common serving engine, returns logprobs computed before logits post-processing by default, so "the returned logprobs do not reflect the final adjusted probabilities used during sampling"[^40].
- The top-k at the label position may therefore include tokens the enum forbids, and the enum tokens' probabilities may not sum to 1. **Renormalise over the enum's first tokens, and record the mass outside the enum as a diagnostic.** A large outside mass means the model wanted to say something the options do not allow.
- Which engine and which mode each OpenRouter host runs is **Unverified**.

**Letters (A/B/C) or words?** Models "prefer to select specific option IDs as answers"[^43], and this "primarily stems from LLMs' token bias"[^44]. Prefer short semantic labels (`yes`, `no`, `not_stated`; `tuition`, `stipend`) with distinct first tokens. Letters are worse because their bias is a property of the letter itself.

**Other API facts that matter:**
- DeepSeek reports `-9999.0` for any token outside its top 20: "the value -9999.0 is used to signify that the token is very unlikely"[^3]. Treat it as zero.
- DeepSeek's JSON mode "may occasionally return empty content"[^9].
- DeepSeek's beta **Chat Prefix Completion** can "force the model to start its answer by the content of the supplied prefix"[^7]. On DeepSeek's own API you can therefore send `{"answer": "` as the assistant prefix and read the very next token. That gives JSON-like control with no schema. Whether OpenRouter hosts honour `prefix` is **Unverified**.
- Alibaba says "Do not set max_tokens when structured output is enabled"[^32], because a cap can cut the JSON short. For a one-field answer a small cap is fine if it covers the wrapper; see §5 and the §3.3 edits.

## 2. Prompt caching and batching questions over one page

**DeepSeek's own cache (applies only when DeepSeek itself serves the call):**
- Matching is all-or-nothing per stored unit: "A subsequent request can only hit the cache if it fully matches a cache prefix unit."[^10]
- Units are stored at request boundaries: "Each request will produce two cache prefix units at the end position of the user input and the end position of the model output"[^11]. A shared prefix *inside* a request is stored only after the system detects it across requests. In DeepSeek's own page-plus-question example, "the first two requests will not hit the cache"[^12].
- Entries are cleared after disuse, "usually within a few hours to a few days"[^13]. The cache "does not guarantee a 100% cache hit rate"[^14].
- DeepSeek documents no minimum token count. The "minimum units" asked about do not exist as a number on its page.
- *Inference from the rules above, not documented:* one warm-up request whose input ends exactly at the page would store the page as its own unit. Every question after it would then hit, rather than the third onwards.
- Off-peak rates "are half of the peak rates"[^15].

**What OpenRouter adds:**
- For the DeepSeek provider, caching is automatic[^21].
- **Sticky routing**, which keeps calls on one host so its cache stays warm, has three conditions:
  - It is off whenever `provider.order` is set[^17]. §4.1's `only` list does not disable it.
  - It keys on "the first system (or developer) message and the first non-system message"[^18]. So **the page must be the first user message on its own, with the question in a later message**. If the page and the question share one message, every question gets a new key, can land on a different host, and misses that host's cache.
  - It times out after 10 minutes of inactivity[^20]. Passing `session_id` (for example a hash of the page) makes it stick from the first request[^19].
- Sending a sampling parameter explicitly instead of omitting it "can affect provider-side cache keys"[^25]. Send the same parameters on every call.
- **The spec's first-choice host is not DeepSeek.** DeepSeek's cache rules describe DeepSeek's servers. A third-party host such as Ionstream has its own cache, or none. **Unverified**: read `usage.prompt_tokens_details.cached_tokens` on the first probe.

**One question per call, or several questions in one JSON object?**

- *For several in one call:* batch prompting cuts tokens and keeps accuracy, but "the number of samples in each batch and the complexity of tasks affect its performance"[^59].
- *Against, for this design:*
  - Keys are generated in order[^30], so a later answer is conditioned on the model's own earlier answers. Each field's logprob is then a conditional probability, and a per-question calibration set on one-question calls no longer applies to it.
  - With a cached page, the only cost one-per-call saves is the uncached question tail plus a few output tokens.
- *Recommendation:* keep one question per call, as §3.3 says, provided caching is measured to work on the chosen host. If it does not cache, re-decide using the measured costs.

## 3. Bias, calibration and cascades

**Biases to expect:**
- **Recency and majority-label bias.** Models lean towards answers "placed near the end of the prompt or are common in the pre-training data"[^47].
- **Option-ID bias.** See [^43].
- **Label-name ("verbalizer") bias.** Brittleness comes from "the formatting, the choice verbalizers, and the ICL examples"[^49].

**Fixes from the literature:**
- *Contextual calibration.* Ask the same prompt with a content-free input such as "N/A", then rescale so that input scores uniformly. This improved accuracy "up to 30.0% absolute"[^48].
- *Batch calibration.* Estimate the bias from a batch of real inputs; "BC is zero-shot, inference-only, and incurs negligible additional costs"[^50].
- The spec's per-question, per-wording, per-language threshold (§3.4) already absorbs much of this, because a threshold is set on measured precision rather than on raw probability. Contextual or batch calibration helps on top of it only if the harness shows the raw probabilities rank items badly (**Unverified**, to be measured).

**Logprob or verbalized confidence?**
- For RLHF-tuned models, Tian et al. found "verbalized confidences emitted as output tokens are typically better-calibrated than the model's conditional probabilities"[^51].
- OpenAI's own logprob guide warns that "confidence measures certainty in the classification, not whether the classification is correct"[^28].
- Neither finding is a reason to drop logprobs. The design does not need raw probabilities to be calibrated, only to *rank* items well enough that the harness can set a bar on them.
- If the harness finds logprobs rank poorly on a question, a verbalized-confidence field is the documented alternative. It costs a few output tokens and must come *after* the answer key.

**Cascades:**
- FrugalGPT learns which model to call next and matched the best single model "with up to 98% cost reduction"[^52].
- AutoMix has the small model check its own answer, and because "self-verification can be noisy, it employs a POMDP based router"[^53].
- A mixture-of-thoughts cascade escalates when a weak model's sampled answers disagree, and needs "only 40% of its cost"[^54].
- Agreement-Based Cascading "uses agreement between ensembles of models at each level of the cascade as a basis for data-dependent routing"[^55].
- Cascaded Selective Evaluation is the closest to §3.3. It holds a target agreement with humans by having the judge "assess the confidence of judge models and selectively decide when to trust its judgement", and escalates only when unsure[^56].

**Does two families agreeing on a low-confidence item raise precision?** The literature gives no general yes for this exact setup (**Unverified**), and gives one strong reason for caution. Across 350+ models, "models agree 60% of the time when both models err"[^57]. And "larger and more accurate models have highly correlated errors, even with distinct architectures and providers"[^58]. A different provider is therefore weaker evidence of independent judgement than §3.3's rationale assumes. The spec already makes the band measured, not assumed (§3.4, §11 first bullet). Keep that, and have the harness report precision *on agreement inside the band* separately from precision overall.

## 4. Prompt structure

**Where things go (for caching).**
- **System message:** a fixed instruction that never changes across pages.
- **First user message:** the page alone, between delimiters and labelled as data.
- **Last user message:** the question, the options and their definitions.
- This follows from the caching rules in §2[^11][^18]. Which wording sits in the system message and which in the user message has no primary source for these models (**Unverified**). Keep it fixed, because the bar is per wording.

**Untrusted page text.** Without help, an LLM "is unable to distinguish which sections of prompt belong to various input sources". Spotlighting (delimiting, datamarking or encoding the untrusted text) is "a robust defense that has minimal detrimental impact to underlying NLP tasks"[^60]. This matches the repo's `extraction.py` pattern.

**Definitions and a "none" option.** Under structured outputs "The model will always try to adhere to the provided schema, which can result in hallucinations if the input is completely unrelated to the schema"[^31]. A `not_stated` label gives that case a valid answer. Without one, a page that says nothing is forced onto a real label. One-line definitions per option are good practice, but no source here measures their effect for these models (**Unverified**).

**Few-shot examples.**
- Demonstrations mostly teach "the label space … the distribution of the input text … the overall format", and "randomly replacing labels in the demonstrations barely hurts performance"[^61].
- They also bring order and majority bias[^47].
- With strict enums and definitions the label space and format are already fixed, so examples add little and add bias. Leave them out by default, and add them only per question where the harness shows a gain.
- Any example used must never be a key row (spec §6.1 already says this).

**Instruction language.** The one study found covers Arabic and found "on average, the non-native prompt performs the best, followed by mixed and native prompts"[^62]. That supports English instructions over non-English text. No study found covers Turkish or Azerbaijani (**Unverified**), so the harness's per-language bar is the only evidence there will be.

**Quote evidence before the answer?** No, not when the probability is read from logprobs.
- Keys are generated in order[^30]. An `evidence` key before `answer` makes the answer token conditional on the model's own quote, which changes what the probability means and adds output tokens.
- Chain-of-thought helps "primarily on tasks involving math or logic, with much smaller gains on other types of tasks"[^63].
- Format restrictions already reduce reasoning[^42].
- If evidence is wanted for review, put it *after* `answer` in the schema. Its tokens then cannot affect the answer's probability.

## 5. Thinking modes

- **DeepSeek V4.1 Flash thinks unless told not to.** "Thinking mode is enabled by default, with the default effort being high"[^6]. The pricing page lists it as "Supports both non-thinking and thinking (default) modes"[^16].
  - Turn it off explicitly: `thinking: {"type": "disabled"}` or `reasoning_effort: "none"` on DeepSeek ("If set to disabled, then use non-thinking model."[^4]), or `reasoning` effort `none` through OpenRouter.
  - Then check `reasoning_tokens` is 0 on every response[^8].
  - The default output budget is "8K in non-thinking mode, 64K in thinking mode"[^5].
- **Cost.** Reasoning tokens "are considered output tokens and charged accordingly"[^27]. Through OpenRouter they also count against `max_tokens`: "A small max_tokens can be consumed entirely by reasoning"[^24]. With §3.3's tiny cap, a host that ignored "reasoning off" would return empty content and still bill for the reasoning.
- **GLM-5.3-Flash cannot be the second reader as specified.** On Z.ai, GLM-5.3 and GLM-5.3-Flash "use forced thinking and cannot be disabled"[^38]. On Alibaba, "The glm-5.3 series models always perform thinking."[^36] Z.ai's API has no logprobs parameter either[^39]. Whether Fireworks or Together let you turn GLM-5.3-Flash's thinking off is **Unverified**.
- **Qwen.** Thinking-phase content "does not include log probabilities"[^35], and Alibaba also turns thinking on by default for the DeepSeek-V4 series it hosts[^37]. Use Qwen with thinking off.
- **Does turning thinking off cost accuracy on this kind of task?** No vendor publishes thinking-vs-non-thinking accuracy for closed-set classification on these models (**Unverified**). The general evidence says the gain from reasoning is small outside math and logic[^63]. Measure both modes on the key for each question before deciding. The harness can test this cheaply.

## Rules for the second-reader prompt

1. Send one question per call; the page is the first user message on its own, and the question comes in a later user message.[^18][^11]
2. Keep the system message, parameter set and option wording byte-identical across a page's calls; send no optional parameter on some calls and not others.[^10][^25]
3. Pass `session_id` = hash of the page, and route with `only` + `allow_fallbacks:false`, never `order`.[^19][^17]
4. Read `cached_tokens` on every response and alert when a page's second call shows 0.[^14]
5. Wrap the page in delimiters labelled as untrusted data, and never put instructions inside it.[^60]
6. Use a schema with one key, `answer`, as an enum. If a quote is wanted, it goes after `answer`, never before.[^30][^63]
7. Give every enum label a unique first token; use short words, not letters A/B/C.[^43][^29]
8. Include `not_stated` (or the caller's "unsure" label) in every enum.[^31]
9. Read the probability at the first token where the labels diverge, renormalise over the enum, and log the mass outside the enum.[^40][^41]
10. Treat `-9999.0` as zero, and treat a label missing from the top-k as at most the smallest listed probability.[^3]
11. Send `require_parameters:true` with `response_format`, `logprobs` and `top_logprobs` set, and still validate the JSON in code.[^26][^23]
12. Set `top_logprobs` to at most 5 on Qwen and at most 20 elsewhere.[^34][^2]
13. Turn thinking off explicitly, and treat `reasoning_tokens > 0`, `finish_reason != "stop"` or empty content as "unsure".[^6][^24][^9]
14. Cap `max_tokens` at the wrapper tokens + the longest label + a small margin, not the label alone.[^32][^24]
15. Write instructions in English, and set the bar per language from the key; no bar carries across languages.[^62]
16. Use no few-shot examples by default; never use key rows as examples.[^61][^47]
17. Fix option order per question and wording; the harness measures position bias by permuting options on the key.[^43][^47]
18. Report precision on agreement inside Jev's band separately from overall precision; agreement is not independence.[^57][^58]

## What in §3.3 should change

1. **"Strict json_schema enum" → "strict json_schema where the endpoint declares it, required via `require_parameters`; validated in code either way."** DeepSeek's and Z.ai's own APIs offer only `json_object`[^1][^39], and OpenRouter's strict mode is per endpoint and not guaranteed[^22][^23].
2. **Name the token.** "Read from the logprobs of the option token" → "read at the first token where the enum labels diverge, renormalised over the enum's first tokens; labels are designed with unique first tokens; mass outside the enum is logged". Raw-logprob engines do not apply the grammar mask to what they report[^40], and multi-token labels with a shared first token cannot be scored[^29].
3. **`max_tokens`.** "Capped at the longest option" → "capped at the JSON wrapper + the longest option + a small margin". Add: "a response with `reasoning_tokens > 0`, `finish_reason` ≠ `stop`, or empty content is unsure". A cap that tight returns nothing if reasoning is on[^24], and Alibaba warns that caps truncate JSON[^32].
4. **"Reasoning is off" → "reasoning is turned off explicitly per host (DeepSeek defaults to on), and checked on every response".**[^6][^8] **Drop GLM-5.3-Flash from §5's second-reader candidates**, or replace it with a GLM model whose thinking can be turned off. GLM-5.3 thinks always on Z.ai and Alibaba[^38][^36], and Z.ai's API has no logprobs[^39].
5. **Cache layout.** "The page first, byte-identical" → "a fixed system message; the page alone as the first user message; the question in a following message; `session_id` = page hash". Otherwise OpenRouter's sticky key changes with every question[^18][^19]. Also state that DeepSeek's cache rules apply only if DeepSeek serves the call, and that the chosen third-party host's caching is measured (`cached_tokens`) before §9's second-reader cost figure is trusted.
6. **State that options must include the caller's "unsure" label** (`not_stated` for the readers), so a page that says nothing has a legal answer[^31].
7. **No evidence or reasoning field before `answer`.** Generation order makes it shift the answer's probability[^30].
8. **Keep, with evidence:** one question per call (§2 above), the measured per-question bar (§3), and "no probability → vote that must agree with Jev". Text answers are the more robust signal when token probabilities are unavailable[^46]. Add one harness metric: precision *given agreement* inside the band, because cross-family errors correlate[^57][^58].

## Open questions

- Does any OpenRouter host for DeepSeek V4.1 Flash, GLM-5.3-Flash or Qwen3.8-Flash return `logprobs` *together with* strict `json_schema`? Are those logprobs pre-mask or post-mask? This needs a probe per host; no host documents it.
- Do the chosen third-party hosts (for example Ionstream) cache prefixes at all, and at what price? The cache-hit figures in spec §5/§9 assume DeepSeek-like behaviour that is undocumented for them.
- Does OpenRouter pass DeepSeek's beta `prefix: true` (Chat Prefix Completion) through to any host?
- Can GLM-5.3-Flash's thinking be turned off on Fireworks or Together? Z.ai and Alibaba say no.
- Accuracy and calibration of non-thinking vs thinking mode for closed-set classification on these exact models: no vendor figure was found.
- Alibaba's page is internally inconsistent about which models get strict JSON Schema (its table says "Only selected qwen-plus models"[^33], while a list on the same page names Flash series). Confirm Qwen3.8-Flash with one call.

## Sources

[^1]: https://api-docs.deepseek.com/api/create-chat-completion/ "Must be one of text or json_object"
[^2]: https://api-docs.deepseek.com/api/create-chat-completion/ "An integer between 0 and 20 specifying the number of most likely tokens to return at each token position"
[^3]: https://api-docs.deepseek.com/api/create-chat-completion/ "the value -9999.0 is used to signify that the token is very unlikely"
[^4]: https://api-docs.deepseek.com/api/create-chat-completion/ "then use non-thinking model."
[^5]: https://api-docs.deepseek.com/api/create-chat-completion/ "When not set, the default is 8K in non-thinking mode, 64K in thinking mode"
[^6]: https://api-docs.deepseek.com/guides/thinking_mode/ "Thinking mode is enabled by default, with the default effort being high"
[^7]: https://api-docs.deepseek.com/api/create-chat-completion/ "to force the model to start its answer by the content of the supplied prefix"
[^8]: https://api-docs.deepseek.com/api/create-chat-completion/ "Tokens generated by the model for reasoning."
[^9]: https://api-docs.deepseek.com/guides/json_mode/ "the API may occasionally return empty content"
[^10]: https://api-docs.deepseek.com/guides/kv_cache/ "A subsequent request can only hit the cache if it fully matches a cache prefix unit."
[^11]: https://api-docs.deepseek.com/guides/kv_cache/ "Each request will produce two cache prefix units at the end position of the user input and the end position of the model output"
[^12]: https://api-docs.deepseek.com/guides/kv_cache/ "the first two requests will not hit the cache"
[^13]: https://api-docs.deepseek.com/guides/kv_cache/ "it will be automatically cleared, usually within a few hours to a few days"
[^14]: https://api-docs.deepseek.com/guides/kv_cache/ "does not guarantee a 100% cache hit rate"
[^15]: https://api-docs.deepseek.com/quick_start/pricing/ "Off-peak rates are half of the peak rates."
[^16]: https://api-docs.deepseek.com/quick_start/pricing/ "Supports both non-thinking and thinking (default) modes"
[^17]: https://openrouter.ai/docs/guides/best-practices/prompt-caching "Sticky routing is not used when you specify a manual provider order via provider.order"
[^18]: https://openrouter.ai/docs/guides/best-practices/prompt-caching "OpenRouter identifies conversations by hashing the first system (or developer) message and the first non-system message in each request"
[^19]: https://openrouter.ai/docs/guides/best-practices/prompt-caching "When session_id is set, sticky routing activates on any successful request"
[^20]: https://openrouter.ai/docs/guides/best-practices/prompt-caching "Sticky sessions expire after 10 minutes of inactivity."
[^21]: https://openrouter.ai/docs/guides/best-practices/prompt-caching "Prompt caching with DeepSeek is automated and does not require any additional configuration."
[^22]: https://openrouter.ai/docs/guides/features/structured-outputs "Support is determined per endpoint, not just per model"
[^23]: https://openrouter.ai/docs/guides/features/structured-outputs "exact compliance is not guaranteed on every endpoint"
[^24]: https://openrouter.ai/docs/api_reference/parameters "A small max_tokens can be consumed entirely by reasoning"
[^25]: https://openrouter.ai/docs/api_reference/parameters "it can affect provider-side cache keys"
[^25b]: https://openrouter.ai/docs/api_reference/parameters "An integer between 0 and 20 specifying the number of most likely tokens to return at each token position"
[^26]: https://openrouter.ai/docs/guides/routing/provider-selection "You can restrict requests only to providers that support all parameters in your request using the require_parameters field."
[^27]: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens "Reasoning tokens are considered output tokens and charged accordingly."
[^28]: https://developers.openai.com/cookbook/examples/using_logprobs "This shows that confidence measures certainty in the classification, not whether the classification is correct."
[^29]: https://developers.openai.com/cookbook/examples/using_logprobs "Logprobs allow us to compute the joint log probability of a sequence by summing the logprobs of its tokens."
[^30]: https://developers.openai.com/api/docs/guides/structured-outputs "outputs will be produced in the same order as the ordering of keys in the schema"
[^31]: https://developers.openai.com/api/docs/guides/structured-outputs "which can result in hallucinations if the input is completely unrelated to the schema"
[^32]: https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output "Do not set max_tokens when structured output is enabled."
[^33]: https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output "Only selected qwen-plus models"
[^34]: https://docs.qwencloud.com/api-reference/chat/openai-chat "Valid values: 0 to 5. This parameter applies only if logprobs is set to true"
[^35]: https://docs.qwencloud.com/api-reference/chat/openai-chat "does not include log probabilities"
[^36]: https://docs.qwencloud.com/api-reference/chat/openai-chat "The glm-5.3 series models always perform thinking."
[^37]: https://docs.qwencloud.com/api-reference/chat/openai-chat "The DeepSeek-V4 series enables thinking by default."
[^38]: https://docs.z.ai/guides/capabilities/thinking-mode.md "use forced thinking and cannot be disabled"
[^39]: https://docs.z.ai/api-reference/llm/chat-completion.md "Output format type: text for plain text, json_object for JSON-formatted output."
[^40]: https://docs.vllm.ai/en/stable/usage/v1_guide/ "the returned logprobs do not reflect the final adjusted probabilities used during sampling"
[^41]: https://arxiv.org/abs/2405.21047 "can distort the LLM's distribution, leading to outputs that are grammatical but appear with likelihoods that are not proportional to the ones given by the LLM"
[^42]: https://arxiv.org/abs/2408.02442 "we observe a significant decline in LLMs reasoning abilities under format restrictions"
[^43]: https://arxiv.org/abs/2309.03882 "they prefer to select specific option IDs as answers"
[^44]: https://arxiv.org/abs/2309.03882 "this behavioral bias primarily stems from LLMs' token bias"
[^45]: https://arxiv.org/abs/2402.14499 "the two approaches are severely misaligned on all dimensions, reaching mismatch rates over 60%"
[^46]: https://arxiv.org/abs/2404.08382 "the text answers are more robust to question perturbations than the first token probabilities"
[^47]: https://arxiv.org/abs/2102.09690 "those that are placed near the end of the prompt or are common in the pre-training data"
[^48]: https://arxiv.org/abs/2102.09690 "substantially improves GPT-3 and GPT-2's average accuracy (up to 30.0% absolute)"
[^49]: https://arxiv.org/abs/2309.17249 "including but not limited to the formatting, the choice verbalizers, and the ICL examples"
[^50]: https://arxiv.org/abs/2309.17249 "BC is zero-shot, inference-only, and incurs negligible additional costs."
[^51]: https://arxiv.org/abs/2305.14975 "verbalized confidences emitted as output tokens are typically better-calibrated than the model's conditional probabilities"
[^52]: https://arxiv.org/abs/2305.05176 "FrugalGPT can match the performance of the best individual LLM (e.g. GPT-4) with up to 98% cost reduction"
[^53]: https://arxiv.org/abs/2310.12963 "given that self-verification can be noisy, it employs a POMDP based router"
[^54]: https://arxiv.org/abs/2310.03094 "achieve performance comparable to using solely the stronger LLM but require only 40% of its cost"
[^55]: https://arxiv.org/abs/2407.02348 "uses agreement between ensembles of models at each level of the cascade as a basis for data-dependent routing"
[^56]: https://arxiv.org/abs/2407.18370 "assess the confidence of judge models and selectively decide when to trust its judgement"
[^57]: https://arxiv.org/abs/2506.07962 "models agree 60% of the time when both models err"
[^58]: https://arxiv.org/abs/2506.07962 "larger and more accurate models have highly correlated errors, even with distinct architectures and providers"
[^59]: https://arxiv.org/abs/2301.08721 "the number of samples in each batch and the complexity of tasks affect its performance"
[^60]: https://arxiv.org/abs/2403.14720 "a robust defense that has minimal detrimental impact to underlying NLP tasks"
[^61]: https://arxiv.org/abs/2202.12837 "randomly replacing labels in the demonstrations barely hurts performance"
[^62]: https://arxiv.org/abs/2409.07054 "on average, the non-native prompt performs the best, followed by mixed and native prompts"
[^63]: https://arxiv.org/abs/2409.12183 "CoT gives strong performance benefits primarily on tasks involving math or logic, with much smaller gains on other types of tasks"
