# Spike re-score (from raw jsonl)

Key: expected sets as recorded per row by spike.py (sheet copy with `strength` column, requirement-reader worktree). Content-rule rows accept any_format or not_a_format_rule. dangerous = europass_required where expected is not.

| run | answered/48 | first-try breaks | correct/48 | wrong rows (got) | dangerous | missed Europass (safe dir.) | $ total | median latency s (all attempts) | hosts (attempt counts) |
|---|---|---|---|---|---|---|---|---|---|
| luna / default reasoning, temperature omitted | 48 | 1 | 45 | emship(europass_required), emhrpp-a(any_format), d3(europass_required) | 2 ['emship', 'd3'] | - | 0.0048 | 1.2 | {'OpenAI': 49} |
| luna / reasoning.effort=none | 48 | 0 | 45 | emship(europass_required), emhrpp-a(any_format), d3(other_template) | 1 ['emship'] | - | 0.0041 | 1.1 | {'OpenAI': 48} |
| deepseek-v4.1-flash / default reasoning, temp 0 | 44 | 5 | 43 | emhrpp-a(any_format) | 0  | - | 0.0115 | 1.8 | {'AtlasCloud': 21, 'Modal': 16, 'Parasail': 11, 'Sail Research': 2, 'NextBit': 1, 'OpenInference': 1, 'Fireworks': 1} |
| deepseek-v4.1-flash / reasoning off | 48 | 0 | 45 | emship(not_a_format_rule), emhrpp-a(any_format), d3(europass_required) | 1 ['d3'] | ['emship'] | 0.0045 | 0.8 | {'Parasail': 23, 'Together': 13, 'Modal': 6, 'OpenInference': 2, 'InferenceNet': 1, 'AtlasCloud': 1, 'Wafer': 1, 'DeepInfra': 1} |
| glm-5.3-flash / default reasoning, temp 0 | 45 | 3 | 43 | emship(europass_required), emhrpp-a(any_format) | 1 ['emship'] | - | 0.0034 | 1.7 | {'DigitalOcean': 20, 'Together': 16, 'Parasail': 5, 'Fireworks': 4, 'Decart': 1, 'DeepInfra': 1, 'Sail Research': 1, 'Inceptron': 1, 'OpenInference': 1, 'Io Net': 1} |
| glm-5.3-flash / reasoning off (400 mandatory) | 0 | 48 | 0 | - | 0  | - | 0.0000 | 0.3 | none |
| glm-5.3-flash / reasoning.effort=low | 48 | 0 | 45 | emship(europass_required), emhrpp-a(any_format), d3(other_template) | 1 ['emship'] | - | 0.0019 | 3.5 | {'Decart': 24, 'Together': 7, 'Reka': 5, 'DigitalOcean': 4, 'Morph': 2, 'Sail Research': 2, 'Wafer': 1, 'DeepInfra': 1, 'InferenceNet': 1, 'BaseTen': 1} |
| qwen3.8-flash / default reasoning, temp 0 | 17 | 37 | 16 | emhrpp-a(any_format) | 0  | - | 0.0037 | 5.5 | {'Alibaba': 32} |
| qwen3.8-flash / reasoning off, 3 s sleep | 28 | 31 | 26 | emship(not_a_format_rule), emhrpp-a(any_format) | 0  | ['emship'] | 0.0014 | 5.5 | {'Alibaba': 28} |
| qwen3.7-flash / require_parameters (404, no host) | 0 | 48 | 0 | - | 0  | - | 0.0000 | 0.2 | none |
| qwen3.7-flash / NO require_parameters (schema unenforced) | 48 | 1 | 44 | emship(any_format), emhrpp-a(any_format), d3(europass_required), d4(other_template) | 1 ['d3'] | ['emship'] | 0.0005 | 1.1 | {'Alibaba': 48} |

## Unanswered rows per run (final attempt failed after one retry)

- deepseek-v4.1-flash / default reasoning, temp 0: daad-prime: not JSON (finish=length): '{"confidence": 0.95, "verdict": "euro'; emship: not JSON (finish=length): ''; goettingen-de: not JSON (finish=length): ''; d3: not JSON (finish=length): ''
- glm-5.3-flash / default reasoning, temp 0: g12: not JSON (finish=length): ''; d3: not JSON (finish=length): ''; d4: not JSON (finish=length): ''
- glm-5.3-flash / reasoning off (400 mandatory): all 48 -- HTTP 400: {"error":{"message":"Reasoning is mandatory for this endpoin
- qwen3.8-flash / default reasoning, temp 0: daad-prime: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; amir: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; membiomed: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; i-mesc: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; we-team: not JSON (finish=length): ''; emship: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; emhrpp-q: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; imaging-a: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; daad-epos: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; swiss-3rd: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; goettingen-de: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; s1: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; s2: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; s3: not JSON (finish=length): ''; s5: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; s6: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; s8: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; s10: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; s11: not JSON (finish=length): ''; s13: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g3: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g4: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g5: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g8: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g9: not JSON (finish=length): '{"verdict":'; g11: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g12: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; d1: not JSON (finish=length): ''; d3: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; d4: not JSON (finish=length): ''; d5: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me
- qwen3.8-flash / reasoning off, 3 s sleep: i-mesc: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; we-team: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; europubhealth: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; imaging-a: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; swiss-3rd: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; goettingen-de: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; s6: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; s12: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; s13: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g2: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g4: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g5: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g7: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g9: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; g11: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; d1: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; d2: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; d3: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; d4: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me; d7: HTTP 429: {"error":{"message":"Provider returned error","code":429,"me
- qwen3.7-flash / require_parameters (404, no host): all 48 -- HTTP 404: {"error":{"message":"No endpoints found that can handle the 

## Per-row wrongness across runs that answered >=44 rows

Runs: luna / default reasoning, temperature omitted; luna / reasoning.effort=none; deepseek-v4.1-flash / default reasoning, temp 0; deepseek-v4.1-flash / reasoning off; glm-5.3-flash / default reasoning, temp 0; glm-5.3-flash / reasoning.effort=low; qwen3.7-flash / NO require_parameters (schema unenforced)

| id | sentence | truth (outcome/strength) | expected | wrong in N runs | answers (run: verdict) |
|---|---|---|---|---|---|
| emship | (Europass) CV | europass/preferred | ['europass_preferred'] | 6/7 | luna[A]: europass_required (0.78); luna[B]: europass_required (0.86); deepseek-v4.1-flash[A]: None (None); deepseek-v4.1-flash[B]: not_a_format_rule (0.6); glm-5.3-flash[A]: europass_required (0.5); glm-5.3-flash[D]: europass_required (0.6); qwen3.7-flash[C]: any_format (0.95) |
| emhrpp-a | Yes, any CV format is accepted. | none/- | ['not_a_format_rule'] | 7/7 | luna[A]: any_format (1.0); luna[B]: any_format (1.0); deepseek-v4.1-flash[A]: any_format (0.99); deepseek-v4.1-flash[B]: any_format (1.0); glm-5.3-flash[A]: any_format (0.95); glm-5.3-flash[D]: any_format (0.98); qwen3.7-flash[C]: any_format (1.0) |
| d3 | The curriculum vitae should be prepared in a tabular form in accordance with EU standards. | unapplied/- | ['any_format', 'not_a_format_rule'] | 5/7 | luna[A]: europass_required (0.93); luna[B]: other_template (0.97); deepseek-v4.1-flash[A]: None (None); deepseek-v4.1-flash[B]: europass_required (0.6); glm-5.3-flash[A]: None (None); glm-5.3-flash[D]: other_template (0.6); qwen3.7-flash[C]: europass_required (0.9) |
| d4 | A curriculum vitae in reverse chronological order. | order/- | ['any_format', 'not_a_format_rule'] | 1/7 | luna[A]: any_format (0.99); luna[B]: any_format (0.99); deepseek-v4.1-flash[A]: not_a_format_rule (0.96); deepseek-v4.1-flash[B]: not_a_format_rule (0.9); glm-5.3-flash[A]: None (None); glm-5.3-flash[D]: not_a_format_rule (0.55); qwen3.7-flash[C]: other_template (0.9) |

## Panel simulation (unanimity; disagreement -> abstain/undecided)

| panel | missing reading | correct | abstain | wrong (non-danger) | DANGEROUS | non-abstain detail |
|---|---|---|---|---|---|---|
| luna[B]+deepseek[B]+glm[D] (best settings) | abstain | 43 | 4 | 1 | 0 | emhrpp-a:wrong ; abstained on: emship, goettingen-de, d3, d4 |
| luna[B]+deepseek[B]+glm[D] (best settings) | dropped (survivors decide) | 43 | 4 | 1 | 0 | emhrpp-a:wrong ; abstained on: emship, goettingen-de, d3, d4 |
| luna[A]+deepseek[A]+glm[A] (default reasoning) | abstain | 41 | 6 | 1 | 0 | emhrpp-a:wrong ; abstained on: daad-prime, emship, goettingen-de, g12, d3, d4 |
| luna[A]+deepseek[A]+glm[A] (default reasoning) | dropped (survivors decide) | 44 | 1 | 1 | 2 | emship:DANGEROUS; emhrpp-a:wrong; d3:DANGEROUS ; abstained on: d4 |
| luna[B]+deepseek[B] | abstain | 43 | 4 | 1 | 0 | emhrpp-a:wrong ; abstained on: emship, goettingen-de, d3, d4 |
| luna[B]+deepseek[B] | dropped (survivors decide) | 43 | 4 | 1 | 0 | emhrpp-a:wrong ; abstained on: emship, goettingen-de, d3, d4 |
| luna[B]+glm[D] | abstain | 43 | 2 | 2 | 1 | emship:DANGEROUS; emhrpp-a:wrong; d3:wrong ; abstained on: goettingen-de, d4 |
| luna[B]+glm[D] | dropped (survivors decide) | 43 | 2 | 2 | 1 | emship:DANGEROUS; emhrpp-a:wrong; d3:wrong ; abstained on: goettingen-de, d4 |
| deepseek[B]+glm[D] | abstain | 45 | 2 | 1 | 0 | emhrpp-a:wrong ; abstained on: emship, d3 |
| deepseek[B]+glm[D] | dropped (survivors decide) | 45 | 2 | 1 | 0 | emhrpp-a:wrong ; abstained on: emship, d3 |
| luna[A]+deepseek[A] | abstain | 42 | 5 | 1 | 0 | emhrpp-a:wrong ; abstained on: daad-prime, emship, goettingen-de, d3, d4 |
| luna[A]+deepseek[A] | dropped (survivors decide) | 44 | 1 | 1 | 2 | emship:DANGEROUS; emhrpp-a:wrong; d3:DANGEROUS ; abstained on: d4 |
| luna[A]+glm[A] | abstain | 43 | 3 | 1 | 1 | emship:DANGEROUS; emhrpp-a:wrong ; abstained on: g12, d3, d4 |
| luna[A]+glm[A] | dropped (survivors decide) | 45 | 0 | 1 | 2 | emship:DANGEROUS; emhrpp-a:wrong; d3:DANGEROUS ; abstained on:  |
| deepseek[A]+glm[A] | abstain | 41 | 6 | 1 | 0 | emhrpp-a:wrong ; abstained on: daad-prime, emship, goettingen-de, g12, d3, d4 |
| deepseek[A]+glm[A] | dropped (survivors decide) | 45 | 1 | 1 | 1 | emship:DANGEROUS; emhrpp-a:wrong ; abstained on: d3 |
| luna[A]+luna[B] (same model, 2 settings) | abstain | 44 | 2 | 1 | 1 | emship:DANGEROUS; emhrpp-a:wrong ; abstained on: goettingen-de, d3 |
| luna[A]+luna[B] (same model, 2 settings) | dropped (survivors decide) | 44 | 2 | 1 | 1 | emship:DANGEROUS; emhrpp-a:wrong ; abstained on: goettingen-de, d3 |
| all 6 luna/deepseek/glm runs | abstain | 41 | 6 | 1 | 0 | emhrpp-a:wrong ; abstained on: daad-prime, emship, goettingen-de, g12, d3, d4 |
| all 6 luna/deepseek/glm runs | dropped (survivors decide) | 43 | 4 | 1 | 0 | emhrpp-a:wrong ; abstained on: emship, goettingen-de, d3, d4 |

## Pairwise error overlap (wrong-row sets, answered rows only)

- luna / reasoning.effort=none vs deepseek-v4.1-flash / reasoning off: both wrong ['d3', 'emhrpp-a', 'emship']; same wrong answer ['emhrpp-a']
- luna / reasoning.effort=none vs glm-5.3-flash / reasoning.effort=low: both wrong ['d3', 'emhrpp-a', 'emship']; same wrong answer ['d3', 'emhrpp-a', 'emship']
- luna / reasoning.effort=none vs luna / default reasoning, temperature omitted: both wrong ['d3', 'emhrpp-a', 'emship']; same wrong answer ['emhrpp-a', 'emship']
- luna / reasoning.effort=none vs deepseek-v4.1-flash / default reasoning, temp 0: both wrong ['emhrpp-a']; same wrong answer ['emhrpp-a']
- luna / reasoning.effort=none vs glm-5.3-flash / default reasoning, temp 0: both wrong ['emhrpp-a', 'emship']; same wrong answer ['emhrpp-a', 'emship']
- luna / reasoning.effort=none vs qwen3.7-flash / NO require_parameters (schema unenforced): both wrong ['d3', 'emhrpp-a', 'emship']; same wrong answer ['emhrpp-a']
- deepseek-v4.1-flash / reasoning off vs glm-5.3-flash / reasoning.effort=low: both wrong ['d3', 'emhrpp-a', 'emship']; same wrong answer ['emhrpp-a']
- deepseek-v4.1-flash / reasoning off vs luna / default reasoning, temperature omitted: both wrong ['d3', 'emhrpp-a', 'emship']; same wrong answer ['d3', 'emhrpp-a']
- deepseek-v4.1-flash / reasoning off vs deepseek-v4.1-flash / default reasoning, temp 0: both wrong ['emhrpp-a']; same wrong answer ['emhrpp-a']
- deepseek-v4.1-flash / reasoning off vs glm-5.3-flash / default reasoning, temp 0: both wrong ['emhrpp-a', 'emship']; same wrong answer ['emhrpp-a']
- deepseek-v4.1-flash / reasoning off vs qwen3.7-flash / NO require_parameters (schema unenforced): both wrong ['d3', 'emhrpp-a', 'emship']; same wrong answer ['d3', 'emhrpp-a']
- glm-5.3-flash / reasoning.effort=low vs luna / default reasoning, temperature omitted: both wrong ['d3', 'emhrpp-a', 'emship']; same wrong answer ['emhrpp-a', 'emship']
- glm-5.3-flash / reasoning.effort=low vs deepseek-v4.1-flash / default reasoning, temp 0: both wrong ['emhrpp-a']; same wrong answer ['emhrpp-a']
- glm-5.3-flash / reasoning.effort=low vs glm-5.3-flash / default reasoning, temp 0: both wrong ['emhrpp-a', 'emship']; same wrong answer ['emhrpp-a', 'emship']
- glm-5.3-flash / reasoning.effort=low vs qwen3.7-flash / NO require_parameters (schema unenforced): both wrong ['d3', 'emhrpp-a', 'emship']; same wrong answer ['emhrpp-a']
- luna / default reasoning, temperature omitted vs deepseek-v4.1-flash / default reasoning, temp 0: both wrong ['emhrpp-a']; same wrong answer ['emhrpp-a']
- luna / default reasoning, temperature omitted vs glm-5.3-flash / default reasoning, temp 0: both wrong ['emhrpp-a', 'emship']; same wrong answer ['emhrpp-a', 'emship']
- luna / default reasoning, temperature omitted vs qwen3.7-flash / NO require_parameters (schema unenforced): both wrong ['d3', 'emhrpp-a', 'emship']; same wrong answer ['d3', 'emhrpp-a']
- deepseek-v4.1-flash / default reasoning, temp 0 vs glm-5.3-flash / default reasoning, temp 0: both wrong ['emhrpp-a']; same wrong answer ['emhrpp-a']
- deepseek-v4.1-flash / default reasoning, temp 0 vs qwen3.7-flash / NO require_parameters (schema unenforced): both wrong ['emhrpp-a']; same wrong answer ['emhrpp-a']
- glm-5.3-flash / default reasoning, temp 0 vs qwen3.7-flash / NO require_parameters (schema unenforced): both wrong ['emhrpp-a', 'emship']; same wrong answer ['emhrpp-a']

## Panel at ACTION level (any_format and not_a_format_rule both = format 'any'; other_template = undecided, safe)

| panel | missing reading | correct action | abstain | wrong-safe | DANGEROUS (REQ not expected) | detail |
|---|---|---|---|---|---|---|
| luna[B]+deepseek[B]+glm[D] (best settings) | abstain | 46 | 2 | 0 | 0 | emship:abstain, d3:abstain |
| luna[B]+deepseek[B]+glm[D] (best settings) | dropped | 46 | 2 | 0 | 0 | emship:abstain, d3:abstain |
| luna[A]+deepseek[A]+glm[A] (default reasoning) | abstain | 42 | 6 | 0 | 0 | daad-prime:abstain, emship:abstain, goettingen-de:abstain, g12:abstain, d3:abstain, d4:abstain |
| luna[A]+deepseek[A]+glm[A] (default reasoning) | dropped | 46 | 0 | 0 | 2 | emship:DANGEROUS, d3:DANGEROUS |
| luna[B]+deepseek[B] | abstain | 46 | 2 | 0 | 0 | emship:abstain, d3:abstain |
| luna[B]+deepseek[B] | dropped | 46 | 2 | 0 | 0 | emship:abstain, d3:abstain |
| luna[B]+glm[D] | abstain | 46 | 0 | 1 | 1 | emship:DANGEROUS, d3:wrong-safe(OTHER(undecided)) |
| luna[B]+glm[D] | dropped | 46 | 0 | 1 | 1 | emship:DANGEROUS, d3:wrong-safe(OTHER(undecided)) |
| deepseek[B]+glm[D] | abstain | 46 | 2 | 0 | 0 | emship:abstain, d3:abstain |
| deepseek[B]+glm[D] | dropped | 46 | 2 | 0 | 0 | emship:abstain, d3:abstain |
| luna[A]+deepseek[A] | abstain | 44 | 4 | 0 | 0 | daad-prime:abstain, emship:abstain, goettingen-de:abstain, d3:abstain |
| luna[A]+deepseek[A] | dropped | 46 | 0 | 0 | 2 | emship:DANGEROUS, d3:DANGEROUS |
| luna[A]+glm[A] | abstain | 44 | 3 | 0 | 1 | emship:DANGEROUS, g12:abstain, d3:abstain, d4:abstain |
| luna[A]+glm[A] | dropped | 46 | 0 | 0 | 2 | emship:DANGEROUS, d3:DANGEROUS |
| deepseek[A]+glm[A] | abstain | 42 | 6 | 0 | 0 | daad-prime:abstain, emship:abstain, goettingen-de:abstain, g12:abstain, d3:abstain, d4:abstain |
| deepseek[A]+glm[A] | dropped | 46 | 1 | 0 | 1 | emship:DANGEROUS, d3:abstain |
| luna[A]+luna[B] (same model, 2 settings) | abstain | 46 | 1 | 0 | 1 | emship:DANGEROUS, d3:abstain |
| luna[A]+luna[B] (same model, 2 settings) | dropped | 46 | 1 | 0 | 1 | emship:DANGEROUS, d3:abstain |
| all 6 luna/deepseek/glm runs | abstain | 42 | 6 | 0 | 0 | daad-prime:abstain, emship:abstain, goettingen-de:abstain, g12:abstain, d3:abstain, d4:abstain |
| all 6 luna/deepseek/glm runs | dropped | 46 | 2 | 0 | 0 | emship:abstain, d3:abstain |

## Confidence: dangerous answers vs the weakest correct europass_required answer

- luna / default reasoning, temperature omitted: dangerous [('emship', 0.78), ('d3', 0.93)]; correct europass_required n=16 min conf 0.84
- luna / reasoning.effort=none: dangerous [('emship', 0.86)]; correct europass_required n=16 min conf 0.98
- deepseek-v4.1-flash / default reasoning, temp 0: dangerous -; correct europass_required n=16 min conf 0.82
- deepseek-v4.1-flash / reasoning off: dangerous [('d3', 0.6)]; correct europass_required n=16 min conf 0.6
- glm-5.3-flash / default reasoning, temp 0: dangerous [('emship', 0.5)]; correct europass_required n=16 min conf 0.8
- glm-5.3-flash / reasoning.effort=low: dangerous [('emship', 0.6)]; correct europass_required n=16 min conf 0.9
- qwen3.8-flash / default reasoning, temp 0: dangerous -; correct europass_required n=5 min conf 0.97
- qwen3.8-flash / reasoning off, 3 s sleep: dangerous -; correct europass_required n=8 min conf 0.95
- qwen3.7-flash / NO require_parameters (schema unenforced): dangerous [('d3', 0.9)]; correct europass_required n=16 min conf 0.95

## Notes added by recon

- Answer key: origin/master's `cv-format-eval.csv` has the same 48 ids, sentences, outcomes and details as the requirement-reader copy the spike scored, but no `strength` column; the required/preferred split comes from the requirement-reader copy only.
- Setting map (from spike.py env flags + run logs): A = temperature 0, default reasoning (luna A = temperature omitted re-run; the 48x404 "exact spec" luna file was overwritten); B = reasoning off (luna: effort none; qwen3.8: +3 s sleep); C = qwen3.7 without require_parameters; D = glm effort low. max_tokens 200, one retry, strict json_schema, provider.require_parameters true except C.
- Zero-dangerous single runs (deepseek A, qwen3.8 A/B) are zero because those runs broke on the hard rows (finish=length / 429), not because they answered them right.
- Jev grammar gates (jev-gate.log): CV gate 9/48, all 26 Europass rows missed (safe direction), 13 undecided; letter gate 0 asserted in every language, missed forbidden E-049 ("In the study objectives essay, references to proposed universities or faculty should not be made." -> naming=forbidden); negated-limit test got [] for "no more than 500 words". Cause (jev-diag.log): conditional scope answered False@0.81 and True@0.54 on two unconditional sentences; SLOT_BAR 0.85 fail-safe marks both conditional.
- Jev funding-reader spike (session ed04505b, spike_run3.log): 1,005 facts over 15 pages; 116 referee-judged disputes: Jev right 65, DeepSeek V4 Pro right 44, neither 7; agreement spot checks 64, of which 5 wrong (available 2, elig 1, holder 2; amount facts 0). Cost Jev $0.017, DeepSeek V4 Pro $0.187, gpt-5.6-sol $0.118.
