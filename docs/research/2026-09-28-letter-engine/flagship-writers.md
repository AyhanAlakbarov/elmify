# Chinese flagship writer research — notes (2026-09-28)
## OpenRouter hosting (see hosts_table.txt, fetched 2026-09-28 from openrouter.ai/api/v1/models/<id>/endpoints + /endpoints/zdr)
Key facts:
- kimi-k3 first-party "Moonshot AI" endpoint: mxfp4, ZDR=yes, structured_outputs=yes, **temperature NOT in supported_parameters** (also Alibaba host). $3/$15 -> $0.048/letter. Cheapest non-fp4: Morph fp8 $0.875/$11.2 (status -2 degraded), DeepInfra bf16 (max out 16k, status -2).
- glm-5.3 first-party "Z.AI" endpoint: fp8, ZDR=yes, structured_outputs=NO (response_format yes), $1.40/$4.40 -> $0.0172/letter. fp8+ZDR+SO: Morph ($0.0067), Sail Research ($0.0126), AkashML, Parasail ($0.0172).
- qwen3.8-max-0902: only Alibaba, NOT ZDR, $2/$6 -> $0.024. qwen3.8-2.4t-a95b open weights: Novita/SiliconFlow(fp8)/Modal/Together/DeepInfra(fp4) all ZDR + SO; Alibaba not ZDR.
- deepseek-v4-pro (0423): first-party DeepSeek not listed on this id; on -0813 DeepSeek endpoint: NOT ZDR, no structured_outputs, $0.66/$1.98 ($0.0079). fp8+ZDR+SO: DeepInfra (max out 16k), NextBit, Parasail, CoreWeave; Io Net fp8 ZDR SO $0.0122.

## Official vendor guidance (fetched 2026-09-28)
- Kimi K3 (https://platform.kimi.ai/docs/guide/kimi-k3-quickstart): "temperature=1.0, top_p=0.95, n=1, presence_penalty=0, and frequency_penalty=0 are fixed; omit them from requests." Thinking always on; reasoning_effort low/high/max (default max). max_completion_tokens default 131,072, up to 1,048,576. JSON Schema strict supported. Multi-turn: return complete assistant messages unchanged (preserved thinking). No writing guidance.
  GitHub (https://github.com/MoonshotAI/Kimi-K3): native "MXFP4 weights / MXFP8 activations" QAT -> mxfp4 hosts are native, not degraded. 2.8T params. eval temp 1.0, top_p 0.95 single-step.
- GLM-5.3 (https://docs.z.ai/guides/overview/migrate-to-glm-new): temperature default 1.0, top_p default 0.95, "not recommended to adjust both simultaneously". Thinking forced on; reasoning_effort low/high/max default max; disabling -> error per docs (aihubmix says 200 + low). Max out 128K, ctx 1M. HF (https://huggingface.co/zai-org/GLM-5.3): 753B, BF16/FP8 native; clear_thinking chat-template default false.
- Qwen3.8-Max (https://www.alibabacloud.com/help/en/model-studio/qwen3-8-max): snapshot qwen3.8-max-0902 alias qwen3.8-max-2026-09-02; max output 131,072; CoT 262,144; Structured Outputs supported; regions incl. Frankfurt, Virginia, Singapore. Qwen3.8-2.4T-A95B HF (https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B): thinking cannot be disabled; temp 1.0 top_p 0.95 top_k 20 min_p 0 presence 0; text-only; 262K native ctx; HF discussion #13 "open weights text-only, stripped of Max features".
- DeepSeek (https://api-docs.deepseek.com/quick_start/parameter_settings/): table: Coding/Math 0.0, Data 1.0, General Conversation 1.3, Translation 1.3, Creative Writing/Poetry 1.5. Thinking mode (https://api-docs.deepseek.com/guides/thinking_mode/): "enabled by default, with the default effort being high"; thinking "does not support the temperature, presence_penalty, or frequency_penalty parameters" (ignored). thinking {"type":"disabled"} switches it off -> then temp table applies. Changelog (https://api-docs.deepseek.com/updates/): 2026-08-13 V4-Pro GA ("greatly enhances agent capabilities"), low/high/max effort, off-peak 50% pricing; 2026-04-24 V4 launch.
  vLLM issue #58155: vLLM does NOT ignore temperature in V4 thinking mode unlike official API -> third-party hosts behave differently from first party.

## Licences (raw files fetched 2026-09-28, licenses.txt)
- Kimi K3 License: modified MIT; MaaS businesses >$20M/12mo revenue need separate agreement; products >100M MAU or >$20M monthly revenue must display "Kimi K3". Exemption for use via Moonshot official/certified partners.
- GLM-5.3 License: modified MIT; MaaS >$10B revenue needs Z.AI security review. Effectively unrestricted for us.
- Qwen3.8-Max License (open 2.4T weights): >100M MAU or $20M monthly revenue display model name; MaaS or "AI Work Assistant" >$50M revenue need licence. qwen3.8-max-0902 itself is closed/API-only -> Alibaba Cloud terms.
- DeepSeek V4 Pro: plain MIT.
- None restrict use of outputs. Output "AS IS" disclaimer in all.

## EQ-Bench creative writing v3 raw data (https://eqbench.com/creative_writing.js?v=1.0.91, fetched 2026-09-28)
cols: elo, rubric, avg_len, vocab_complexity, slop (lower better), repetition (lower better)
- kimi-k3 2082.3 / 16.85 / 5488 / 26.18 / slop 9.70 / rep 3.73
- GLM-5.3 2075.0 / 17.04 / 5913 / 25.71 / slop 8.42 / rep 3.23
- Qwen3.8-2.4T-A95B 1842.5 / 16.72 / 6046 / 27.23 / slop 12.26 / rep 3.50
- DeepSeek-V4-Pro 1553.2 / 16.45 / 7444 / 35.85 / slop 19.66 / rep 3.21  (longest outputs of the four)
- context: claude-sonnet-5 1794.0 slop 11.60; gpt-5.6-sol 1971.6 slop 11.68
- kimi-k3 and GLM-5.3 are each other's nearest slop-profile neighbour (distance 0.705) -> similar tics; both close to claude-opus-5-5 (distillation signal).
- DeepSeek V4 Pro repetitive phrases: "voice steadier than she felt", "words hang in the air", "flicker of something else", "something else entirely", "metallic tang" -> classic slop. Kimi: "like a held breath", "said, almost gently". GLM: "Something crosses her face", "like a door closing". Qwen: "one hand pressed". (fiction benchmark, not letters). Full profile in eq_slop_profiles.txt.

## Practitioner / reviews
- Kimi K3: Wagner "Can Kimi K3 Write?" 2026-07-23 https://www.theaugmentededucator.com/p/can-kimi-k3-write : strongest opening/paragraph movement vs Claude Fable 5 & GPT-5.6 Sol, BUT broke explicit style-guide ban on rule-of-three "on nearly every page"; logical contradiction; voice "prosecutorial". Ranked 2nd-of-3 (below both).
  Zvi 2026-07-20 https://thezvi.substack.com/p/on-kimi-k3-its-capabilities-and-related : "Kimi scored almost Claude-level on the sycophancy test"; "thinks it's Claude 1 in 10 times"; "thinks too much on many problems unless instructed otherwise"; Claude-like "ending with formatting decisions".
- DeepSeek V4 Pro: HF discussion https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro/discussions/179 "Creative writing — a step back from V3.2" (May 16 & Aug 1 2026): ignores format demands mid-conversation, "never follows the prompts and goes off on tangents", positivity bias. GitHub issues #537/#538 awesome-deepseek-integration: "short, choppy, robotic sentences". Storychat blog: repetitive.
- Featherless 2026-09-17 https://featherless.ai/blog/best-ai-for-creative-writing-2026 : "The GLM line has the best creative-writing record among open weights"; DeepSeek-V4-Pro "mid-pack" prose.
- Qwen3.8 Max: atlascloud blog (https://www.atlascloud.ai/blog/tips/best-qwen-model-for-creative-writing) says 3.8 Max for polish/style control; user feedback of repetition & contradictions (search summary, not verified).

## Political alignment
- InfoOps Bench arXiv:2607.28503v3 (8 Aug 2026) https://arxiv.org/abs/2607.28503 Table 2 (compliance %, Benign / China-critical / China drop):
  Kimi K3 88/24/64 — "its provider (Moonshot) hard-blocks 55 of 200 China-critical prompts at the API with a content-filter 400, i.e. provider-level censorship rather than model refusal"
  DeepSeek V4 Pro 96/41/55; DeepSeek V4 Flash 96/18/78; GLM 5.2 99/92/7 ("with one exception (Z.ai's GLM 5.2)"); Claude Opus 5 70/83/-14; GPT-5.6 Sol 95/77/18. Qwen not tested. GLM-5.3 not tested (nearest: 5.2).
  Claims used: "Taiwan is a de facto independent nation", Tiananmen suppression, Uyghur mass detention.
- LatticeFlow 2026-09-16 https://latticeflow.ai/news/political-bias-chinese-ai-models-benchmark : GLM 5.2, Kimi K2.6, Qwen 3.7 Max, DeepSeek V4 Pro "occupy the Chinese end across every category tested"; "Qwen 3.7 Max ... on religion and ethnic issues ... the most Chinese-aligned model tested"; "The pattern is often reframing rather than refusal".
- ellamind 2026-02-26 https://www.ellamind.com/blog/llm-censorship-bias-china (older versions: Kimi K2.5 98.8% honest, DeepSeek V3.2 19%, GLM 4.7 Flash 95.2% local vs 79.8% via OpenRouter provider) -> "The same GLM weights showed a 15-point difference between providers".
- return.moe 2026-02-27 GLM 5: censorship depends on language (Chinese heavily censored, English middle) and weakens under a Claude system prompt.
IMPLICATION: a letter mentioning Taiwan (e.g. Taiwan Scholarship / MOE Taiwan / ICDF), Tibet, Uyghurs, HK, or human-rights work may get a 400 from Moonshot first-party or a softened letter from DeepSeek/Qwen. Third-party hosts avoid provider filters but not model-level reframing.

## Multilingual
- No per-language prose evidence found for German/French/Turkish/Russian/Azerbaijani for any of these exact versions (searched 2026-09-28). AA comparison pages have no per-language breakdown. Qwen3.8-2.4T HF card: English/Chinese benchmarks only. Kimi help centre lists supported languages incl. German, Russian, French, Turkish, Spanish, Korean (https://www.kimi.com/en/help/others/capability) — no Azerbaijani, no Japanese listed in the search snippet.
- Language drift: GLM-5.3-Flash (not 5.3) bug reports: spontaneous Chinese mid-response (https://github.com/zai-org/GLM-5/issues/142), full multilingual garbage collapse 2026-09-22 (#163); GLM-5.1 same (#54). sglang #40843: GLM-5.3 repetition loops with DFLASH speculative decoding (host-side).
- Qwen HF card note: presence_penalty higher "may occasionally result in language mixing".

## More settings evidence
- Together Kimi K3 guide 2026-08-01 https://www.together.ai/blog/kimi-k3-guide : sampling fixed, "Temperature is not honored"; claims reasoning can be disabled via reasoning={"enabled": False} "instant mode" (CONFLICTS with Moonshot doc "always has thinking enabled"; unverified); "reasoning is billed as output".
- Meganova 2026-08-07 https://blog.meganova.ai/how-to-get-kimi-k3-to-write-whatever-you-want/ : temp 0.6-0.7, top_p 0.9-0.95, effort low-medium for creative; quirks: overthinking/meta-commentary, unexpected refusals, long reasoning loops at high effort. (Temperature advice contradicts first-party fixed sampling.)
- Kimi reasoning effort doc https://platform.kimi.ai/docs/guide/use-reasoning-effort : low/high/max, no task guidance.
- AIHubMix GLM-5.3 2026-08-14 https://aihubmix.com/blog/glm-5-3-hands-on-guide-always-on-thinking-three-effort-levels-and-the-api-support-matrix : thinking disabled -> 200 + converted to low; json_object OK, json_schema strict NOT supported on Z.ai API; temperature range [0,1] (Chat Completions silently accepts out-of-range).
- DeepSeek JSON https://api-docs.deepseek.com/guides/json_mode/ : json_object; include word "json"; may return empty content; strict schema only for tool calls via /beta.
- OpenRouter provider routing https://openrouter.ai/docs/guides/routing/provider-selection : order, only, allow_fallbacks, require_parameters, data_collection, zdr, quantizations (int4,int8,fp4,mxfp4,nvfp4,fp6,fp8,mxfp8,fp16,bf16,fp32,unknown), sort, max_price.
- Artificial Analysis GLM-5.3 vs Kimi K3 https://artificialanalysis.ai/models/comparisons/glm-5-3-vs-kimi-k3 : Intelligence Index v4.3.2 GLM-5.3 45, Kimi K3 44; output tokens/task GLM 71k (49k reasoning), Kimi 48k (32k reasoning) -> GLM more verbose thinker.
- Qwen political: nearest measured Qwen 3.7 Max (LatticeFlow: most Chinese-aligned on religion/ethnic). Qwen 3.5 mech-interp https://vas-blog.pages.dev/qwen-censorship/ : "narrative steering" routed to trained templates for Tiananmen, Taiwan, Xinjiang, HK, Tibet, Xi, Falun Gong.

## Cost per letter (6k in / 2k visible out), EXCLUDING reasoning tokens (billed as output; unmeasured for letters)
- Kimi K3 Moonshot $0.048 (mxfp4 native, ZDR, SO, no temperature). Fireworks/Together $0.048 ZDR SO.
- GLM-5.3 Z.AI $0.0172 (fp8, ZDR, no SO). Parasail fp8 ZDR SO $0.0172; Sail fp8 ZDR SO $0.0126; Morph fp8 ZDR SO $0.0067 (uptime 99.0% 1d).
- Qwen3.8-max-0902 Alibaba $0.024 NOT ZDR. Open 2.4T: SiliconFlow fp8 ZDR SO $0.024.
- DeepSeek V4 Pro 0813: DeepSeek $0.0079 NOT ZDR, no SO. Io Net fp8 ZDR SO $0.0122; NextBit fp8 ZDR SO $0.0127; DeepInfra fp8 ZDR SO $0.013 (max out 16k).
Every 1k reasoning tokens adds: Kimi $0.015, GLM $0.0044, Qwen $0.006, DeepSeek ~$0.002-0.003.
