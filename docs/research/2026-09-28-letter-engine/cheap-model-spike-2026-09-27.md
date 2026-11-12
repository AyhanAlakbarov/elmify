# Model spike: OpenRouter structured output, cheap models and Jev gates (2026-09-27)

This was a throwaway measurement. Nothing in the repo was edited. The scripts are `spike.py`, `score.py`, `jev_diag*.py` and `keyusage.py`. Raw per-row output is in `*.jsonl`, and the logs are `run*.log`, `jev-gate.log` and `jev-diag.log`.

## 1. Documentation answers

**(a) Can a request be limited to hosts that support json_schema? Yes, with `provider.require_parameters: true`.**
- The provider-selection page says `require_parameters` means *"Only use providers that support all parameters in your request."* (default `false`). Source: https://openrouter.ai/docs/guides/routing/provider-selection
- The same page says that without it, `response_format` is only a soft preference: *"a small set of parameters is used as a soft preference when choosing between providers of the same model: `tools`, `response_format` (including structured outputs), and `verbosity`."*
- The structured-outputs page says: *"Set `require_parameters: true` in your provider preferences"*. It also says *"Set `strict: true` so that providers with a native strict mode enforce your schema exactly. Enforcement varies by provider."* Source: https://openrouter.ai/docs/guides/features/structured-outputs
- **Observed, not only documented:**
  - The filter is real. `qwen/qwen3.7-flash` has one host (Alibaba), which does not list `structured_outputs`, so every request returned 404 "No endpoints found that can handle the requested parameters".
  - The filter covers **every** parameter you send. No `gpt-5.6-luna` host lists `temperature`, so the exact spec request (temperature 0 with require_parameters) returned 404 on every call.
  - "Enforcement varies by provider" means strict json_schema is the host's promise, not OpenRouter's. A client-side schema check is still needed.

**(b) Is the Responses API supported, with structured output? Yes.**
- The endpoint is `https://openrouter.ai/api/v1/responses`. The docs describe it as *"designed to be a drop-in replacement for OpenAI's Responses API"* and say *"This API is **stateless**"*. `store: true` and `previous_response_id` are rejected with a 400.
- The API reference lists `text.format` as `FormatJsonSchemaConfig`, *"JSON schema constrained response format"*, with `name`, `schema` and `strict` fields. The request body also accepts `provider` (ProviderPreferences, including `require_parameters`).
- Sources: https://openrouter.ai/docs/api_reference/responses/overview and https://openrouter.ai/docs/api/api-reference/responses/create-a-response.md
- The guide pages do not mention structured output. Only the API reference does. **I did not test the Responses API live.** Every measurement here used chat completions.

**(c) Options for pinning or excluding hosts.** All quotes are from the provider-selection page:
- `order`: *"List of provider slugs to try in order (e.g. `["anthropic", "openai"]`)."*
- `only`: *"List of provider slugs to allow for this request."*
- `ignore`: *"List of provider slugs to skip for this request."*
- `allow_fallbacks` (default `true`): *"Whether to allow backup providers when the primary is unavailable."*

## 2. The 48-row CV-format sheet, one closed question per sentence

**Setup**
- Each sentence was asked one question: "What does this sentence require of the applicant's CV format?"
- The sentence was wrapped as `<untrusted_sentence>` and described as data, not instructions.
- The answer was forced into a strict json_schema: `verdict`, one of five enum values, and `confidence`, a number from 0 to 1.
- Requests went through chat completions with `provider.require_parameters: true`, `max_tokens` 200 and one retry. A first-try failure counts as a break.

**How the sheet's outcomes were mapped**
- `europass` with strength `required` maps to `europass_required`. With strength `preferred` it maps to `europass_preferred`.
- `standard` maps to `any_format`.
- `none` maps to `not_a_format_rule`.
- The content rules (`unapplied`, `constraint`, `include`, `order`, `emphasise`, 9 rows) state no template, so either `any_format` or `not_a_format_rule` counts as correct.

**How errors were scored**
- **Dangerous** means `europass_required` on a row whose expected answer is anything else.
- "Wrong Europass" uses the gate's definition: Europass given where the sheet has none, or no Europass where the sheet has Europass.

### 2a. The spec as written (temperature 0, default reasoning)

| model | breaks (of 48) | dangerous | wrong Europass | agreement | mean tokens in/out | $ | median latency | hosts |
|---|---|---|---|---|---|---|---|---|
| openai/gpt-5.6-luna, exact spec | **48** (404: no host takes `temperature`) | - | - | 0% | - | 0 | - | none |
| openai/gpt-5.6-luna, temperature omitted | 1 (reasoning used up the 200-token budget) | **2** (emship, d3) | 1 (d3) | 45/48 = 94% | 297/32 | 0.0048 | 1.2 s | OpenAI |
| deepseek/deepseek-v4.1-flash | 5 (budget used up) | 0 | 0 | 43/48 = 90% | 289/120 | 0.0115 | 1.8 s | 7 hosts, mostly AtlasCloud, Modal, Parasail |
| z-ai/glm-5.3-flash | 3 (budget used up) | 1 (emship) | 0 | 43/48 = 90% | 250/70 | 0.0034 | 1.7 s | 10 hosts, mostly DigitalOcean, Together |
| qwen/qwen3.8-flash | **37** (28 × 429 from the host's rate limit, 9 × budget used up) | 0 | 0 | 16/48 = 33% | 299/178 | 0.0037 | 5.5 s | Alibaba (only host) |
| qwen/qwen3.7-flash | **48** (404: its only host has no structured outputs) | - | - | 0% | - | 0 | - | none |

### 2b. With reasoning turned down, so the 200-token budget holds the answer

| model / config | breaks | dangerous | wrong Europass | agreement | tokens in/out | $ | latency | hosts |
|---|---|---|---|---|---|---|---|---|
| gpt-5.6-luna, `reasoning.effort: none` | **0** | 1 (emship) | 0 | 45/48 = 94% | 297/22 | 0.0041 | 1.1 s | OpenAI |
| deepseek-v4.1-flash, reasoning off | **0** | 1 (d3) | 2 (emship missed, d3) | 45/48 = 94% | 253/22 | 0.0045 | **0.8 s** | 8 hosts, mostly Parasail, Together |
| glm-5.3-flash, reasoning off | **48** (400: "Reasoning is mandatory for this endpoint and cannot be disabled.") | - | - | 0% | - | 0 | - | none |
| glm-5.3-flash, `reasoning.effort: low` | **0** | 1 (emship) | 0 | 45/48 = 94% | 253/24 | **0.0019** | 3.5 s | 10 hosts, mostly Decart |
| qwen3.8-flash, reasoning off, 3 s between calls | **31** (all 429) | 0 | 1 | 26/48 = 54% | 263/20 | 0.0014 | 5.5 s | Alibaba |
| qwen3.7-flash, **without** require_parameters (schema not enforced by the host) | 1 (429) | 1 (d3) | 2 | 44/48 = 92% | 263/20 | 0.0005 | 1.1 s | Alibaba |

### The rows every model struggled with
- **emhrpp-a**, "Yes, any CV format is accepted." Every model answered `any_format`. The sheet says `none` because the sentence answers a question, and that context is invisible when the sentence is read alone. This is arguably a limit of the sheet in a one-sentence setup.
- **emship**, "(Europass) CV", strength preferred. The meaning is genuinely ambiguous. Luna and GLM read it as a mandate, which is the dangerous direction.
- **d3**, "tabular form in accordance with EU standards". The sheet says `unapplied`. Luna (with reasoning), DeepSeek (reasoning off) and Qwen 3.7 read it as `europass_required`, which is dangerous.
- Every model that answered all 48 rows missed exactly these three, or two of them plus d4. **No single call is free of dangerous errors, including today's model.** The production design of several readings that must all agree is still needed whichever model is chosen.
- Every model got every clear-cut Europass-required and Europass-optional row right.

## 3. Jev's live gates

Command: `POSTGRES_DB=elmify_requirement_reader uv run pytest tests/documents/test_grammar_gate.py -m live -v -s`, run from the worktree. Result: **all 3 tests failed**, in 27 s.

- **test_the_forty_eight_row_cv_gate: FAIL.** `AssertionError: 26 of 48 wrong on Europass`.
  - Printed: `cv gate: 9/48 correct; europass wrong [all 26 europass rows: daad-prime, amir, membiomed, globed, i-mesc, mathmods, we-team, europubhealth, emship, daad-epos, s1, s2, s3, s9, s12, s13, g1-g8, g10, g11]`.
  - The rows that were not wrong came back "undecided": imaging-a, goettingen-de, s4, s5, s7, s8, s10, g9, d1, d2, d3, d4, d7.
  - Every Europass row was a *miss*, meaning no Europass rule was applied. None was a false mandate.
- **test_the_seventy_seven_sentence_letter_gate: FAIL.** `assert missed_forbidden == []`, with `['E-049']` left over.
  - Printed per language, as rows / asserted / missed / not a candidate / untypeable:
    - de: 2 / 0 / 2 / 0 / 0
    - en: 65 / 0 / 58 / 3 / 4
    - es: 2 / 0 / 2 / 0 / 0
    - fr: 4 / 0 / 1 / 3 / 0
    - pt: 3 / 0 / 2 / 0 / 1
    - zh: 1 / 0 / 0 / 0 / 1
  - The "untypeable" rows (E-002, E-052, E-055, E-068, E-064, E-060) all came back empty.
  - Warnings printed: "ignoring an implausible words cap of 2", "pages maximum of 1000", "pages maximum of 500".
  - The failure hit before the cost line, so **the tokens-per-sentence figure was never printed**.
- **test_negated_limits_read_the_right_way_round: FAIL.** `AssertionError: Your motivation letter must be no more than 500 words.` Expected `[('max_words', 500)]`, got `[]`.

**Cause, from a two-sentence diagnostic (`jev-diag.log`; the code was not changed):**
- Jev reads the *values* correctly:
  - "no more than 500 words" gave `limit 500 words, bound maximum, confidence 1.0`.
  - The globed Europass sentence gave `europass_required`, confidence 0.98.
- What blocks the gates is the "conditional" question, "Does this sentence state a condition that must hold for the requirement to apply?". On these two plainly unconditional sentences Jev answered:
  - `False` at probability 0.81, and
  - `True` at 0.54.
- `grammar_questions._scope` treats any answer below `SLOT_BAR = 0.85` as True, which is the fail-safe design. So `conditional=True` is set, and every rule gets the note `conditional`. A rule with a note is not applied (`Rule.applied` means no note), so nothing lands.
- The failure therefore comes from the conditional question and its 0.85 bar, not from the value reading.
- The two sentences above suggest this happens on almost every sentence. The gate result is consistent with that: 0 asserted anywhere, and every Europass row missed.

## Spend

| item | $ |
|---|---|
| Direct spike calls (summed from each response's `usage.cost`; pilot plus runs A, B, C and D) | 0.037 |
| Jev gate run plus 2 diagnostics (key usage rose by 0.214 over the session, minus the line above) | ~0.177 |
| **Total** | **~0.214**, against the $2.00 cap |

- The OpenRouter key itself has a **$1.00 limit**. It had $0.856 left before the spike and has $0.642 left now.
- The Jev figure is inferred from the key's usage counter. If another process was using the same key at the same time, part of that 0.177 belongs to it.

## Recommendation

- **Reading pages and extracting (closed-question classification):**
  - **deepseek/deepseek-v4.1-flash with reasoning off.** It matches luna's 94% agreement at about the same cost (~$0.0001 per call). It is the fastest at 0.8 s median, and has 8 or more hosts that enforce json_schema, so there is no single-host throttling.
  - **z-ai/glm-5.3-flash at `reasoning.effort: low`** is the second choice. It has the same 94% at half the cost, but runs at 3.5 s. Reasoning cannot be turned off on it: the request returns 400.
  - Neither is safer than luna. Each made 1 dangerous error on the two genuinely ambiguous rows. Use them as additional readings inside the existing all-must-agree rule. A mixed panel of luna, DeepSeek and GLM would have caught every dangerous error seen here, because the dangerous rows differ by model: luna on emship, DeepSeek on d3, GLM on emship. The one caveat: luna and GLM agree on emship. With all three required to agree, DeepSeek's `not_a_format_rule` breaks the tie, so the result is an abstention, not a mandate.
- **Qwen:**
  - qwen3.8-flash is **not usable via OpenRouter today**. It has one host, which throttles it (429 on 58-77% of calls).
  - qwen3.7-flash has **no host that enforces the schema**. With require_parameters on it can never run. Without it, the output happened to be well-formed on 48 of 48 rows, but nothing guarantees that.
- **Writing:** not measured by this spike. Suggested next test: DeepSeek v4.1-flash and GLM-5.3-flash with reasoning **on** and a larger `max_tokens`, against luna as the baseline, on the letter engine's existing live checks.
- **Required configuration for any of these:**
  - Keep `require_parameters: true` and never send `temperature` to OpenAI reasoning models.
  - Size `max_tokens` for reasoning, or turn reasoning down: at 200 tokens, 1 to 9 of 48 calls per model ended with `finish_reason=length` and an empty answer.
  - Keep the client-side schema check.
- **Jev: the gates do not pass (0 of 3).** The value readings look right. The blocker is the conditional scope question under the 0.85 fail-safe bar, which marks nearly every rule as conditional. Measuring Jev's actual accuracy needs a decision on that question first: reword it, move the bar, or keep the bar only for third_party. That is a design call for the owner, not something this spike changed.

**Caveats**
- Every model was run once, over 48 rows, so a 1-row difference is noise.
- The sheet's `none` label on emhrpp-a depends on context the one-sentence setup does not have.
- The Responses API was confirmed from the docs only, not tested live.
- The Jev diagnosis rests on two sentences.
