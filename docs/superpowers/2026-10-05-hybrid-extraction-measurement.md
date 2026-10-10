# Hybrid value extraction: does an LLM quote proposer add recall? (measured 2026-10-05)

Question (owner): code finders alone (verified-catalog §5 step 4) versus a hybrid where an LLM also
proposes exact quotes that code keeps only when byte-exact on the line. Research behind it:
`.context/research/2026-10-05-typed-value-extraction-architecture.md` (recommends the hybrid, narrow;
evidence is English/clinical only, so this measurement decides).

**Set-up.** The 1,400 keyed round-1 lines (`~/agent-workspace/tehsil_agent-runs/engine-eval/2026-10-r1/`,
key built by GPT-5.6-sol + Claude Sonnet 5.5, Opus referee). Arm A: the slice-1 finders as verified in
the plan (`2026-10-05-card-reader-1-finders.md`). Arm B: DeepSeek V4.1 Flash on Fireworks (a family not
in the key), thinking off, strict JSON schema `{L<n>: [{type, quote}]}`, 8 lines of one page per call.
Cost **$0.080 for all 1,400 lines**; 765 of 769 quotes (99.5%) were byte-exact on their line.

**Key-true lines found** (a line counts when the arm yields a candidate of the matching kind):

| key question | n | A (code) | B (LLM quotes) | C = A ∪ B | A only | B only | neither |
|---|---|---|---|---|---|---|---|
| application_date | 53 | 35 | 36 | 36 | 0 | 1 | 17 |
| money_to_student | 42 | 21 | 22 | 22 | 0 | 1 | 20 |
| level_rule | 169 | 147 | 124 | 151 | 27 | 4 | 18 |
| nationality_rule | 64 | 51 | 53 | 60 | 7 | 9 | 4 |
| requirement_rule | 50 | 7 | 28 | 28 | 0 | 21 | 22 |

**Hand check of the B-only and "neither" lines.**
- Requirements: B-only finds are real and code misses them — "ən azı 550 bal", "4 üzerinden 2,5",
  "100 üzerinden 65", "до 39 лет", "возраст 16–23 года", "2,800 hours" of work experience.
- Nationality: B-only finds are mostly real — a misspelt "иностранное гржданство", a list of Turkish
  provinces, "development and newly industrialised countries", "refugee status"; some are groups code
  already counts as `unknown_group`.
- "Neither" on money and dates is not a finder miss: those lines state no figure ("tüm masrafları …
  karşılanmaktadır", "aylık burs sağlanmakta") or no date ("Applications are now open"). They are Jev's
  questions (`covers_X`, `tuition_level`, `window_closed`), not candidates.
- Code beats the LLM on levels (27 A-only), so B alone would lose recall.

**Reading.** For dates and money the LLM adds almost nothing (+1 line each). For requirements it is
the difference between 7/50 and 28/50, and for nationality it adds 9/64. Its extra flags on key-false
lines are candidates for Jev to judge, not served values. At $0.08 per 1,400 lines the cost is
negligible. Caveat: one run, one model, a model-built key, small n per kind.
