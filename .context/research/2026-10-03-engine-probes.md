# Engine probes, 2026-10-03 — measured, not read

Throwaway scripts (scratchpad, not committed): one synthetic Stipendium-Hungaricum-style page
(43 numbered lines, ~2,150 prompt tokens), two closed questions per host, OpenRouter, total spend
under $0.02. Each finding is one or two items, so it says what *can* happen, never a rate.

## Jev (`typesafe/jev-1.13` via `/api/v1/systemone`)

- **Billing.** 1 question → 386 input tokens; 5 → 466; 20 short → 766; 20 long → 1,286; one-word
  state + 1 question → 286. So ≈ 270 tokens fixed per request, the state billed once, ≈ 20 tokens per
  short question and ≈ 46 per long one. 24 Choices over a 7-line state: 3,417 tokens.
- **Context limit.** Through OpenRouter, a request of 31,507 input tokens (850 lines + 1 question)
  passed; ≈ 33,400 (900 lines) failed with `{"detail":{"error_type":"max_tokens_exceeded"}}`. The
  limit is ≈ 32k for the whole request, not TypeSafe's "32k for state plus the longest question".
- **Distractors.** The same stipend line scored P(yes) 0.98 in a 5-line state and 0.90–0.91 in
  300–850-line states padded with unrelated lines.
- **Option order.** Six amounts, each asked as "What is the amount in `amounts.mN`…" and as "Who pays
  the amount…", options forward and reversed, all in one request. Forward and reversed agreed on 11
  of 12 answers; the one change was the hardest item (supplementary insurance "up to 65,000 HUF",
  0.42 → `not_stated` 0.33). Confidence moved with order on agreeing answers too: 0.63 vs 0.81,
  0.99 vs 0.85, 0.97 vs 0.87. The old wording ("Who pays…") did slightly better on this set: 6/6
  forward and 5/6 reversed, against the new wording's 5/6 and 5/6 (both missed only the insurance
  item). Six items decide nothing; both wordings go to the harness as A and B.
- Jev answered the monthly stipend `paid_to_student` at 0.99–1.00 in both orders.

## Second-reader candidates (chat completions, strict `json_schema` enum, `logprobs`, reasoning off)

| Model / host | Answer on "What is the amount in L7 (43,000 HUF monthly stipend)?" | Logprobs with strict schema | Prefix cache on 2nd call | Notes |
|---|---|---|---|---|
| DeepSeek V4.1 Flash / Fireworks | `paid_to_student` (P 0.9997) | yes, `top_logprobs` ≤ 5 (10 → HTTP 400) | yes once warm (2,110 of 2,240) | ≈ $0.00006 per cached question |
| DeepSeek V4.1 Flash / Sail Research (fp4) | `paid_to_student` | on one call of two | yes (2,145) | logprobs unreliable → vote mode only |
| DeepSeek V4.1 Flash / CoreWeave (fp8) | `paid_to_student` | **no** (declared) | **no** | |
| DeepSeek V4.1 Flash / Ionstream | **`not_stated` (P 0.93)** | yes | yes (2,048) | wrong; correct with reasoning `low` at 720 reasoning tokens (≈ 5× cost) |
| DeepSeek V4.1 Flash / DigitalOcean | **`not_stated` (P 0.89)** | yes | yes (2,112) | wrong |
| DeepSeek V4.1 Flash / Together | **`not_stated`** | **no** (declared) | yes (2,048) | wrong |
| GLM-5.3-Flash / Fireworks, Together, Sail, Parasail | — | — | — | HTTP 400 "Reasoning is mandatory for this endpoint and cannot be disabled." |
| Qwen3.8-Flash / Alibaba (only host, not ZDR) | — | — | — | HTTP 429 "temporarily rate-limited upstream", twice |

**The same model gives a different answer on a different host.** The three wrong hosts bill ≈ 2,146
prompt tokens for the same messages; the three right ones ≈ 2,240–2,268. A ~100-token difference in
identical input is a different chat template, and with thinking off it changed a 0.99 answer into a
confident wrong one. A "second reader" is therefore a (model, host, quantisation) triple, measured and
pinned as one.

A rephrased question ("Line L7 states the sum 43,000 HUF. What kind of sum is it?") did not fix the
wrong hosts (still `not_stated`, P 0.68–0.69), so this is not a wording artefact of the first question.

Declared `supported_parameters` were wrong twice (Together and CoreWeave declare logprobs and returned
none), so a host is accepted only on a probe, never on its declaration.
