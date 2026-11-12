Orkhan -- Choosing a cheap letter writer (research as of 2026-09-28)

**Bottom line.** No public benchmark tests motivation letters, or writing in Turkish or Azerbaijani. On the English fiction benchmarks that exist, GLM-5.3 ($1.40/$4.40) scores level with Kimi K3 and GPT-6 Sol at a third to a tenth of the price. GLM-5.3-flash is the cheapest model with decent evidence. GPT-6 Luna has almost no writing evidence. Every candidate costs under $0.05 a letter, so choose on measured quality, not price.

**1. Writing benchmarks**
- **EQ-Bench Creative Writing v3** (Elo; judged by Claude Sonnet 4.6 since 2026-03-01; raw data read 2026-09-28):
  - gpt-6-sol 2125 (#4), kimi-k3 2082 (#5), GLM-5.3 2075 (#6, slop 8.4, lowest repetition of the three).
  - Qwen3.8-2.4T-A95B 1843 (#19; I assume this is 3.8-max), claude-sonnet-5 1794 (#27).
  - Kimi-K2.5 1579, DeepSeek-V4-Pro 1553, deepseek-v4.1-flash 1540 (slop 22.4 and repetition 5.2, the worst on our list).
  - Not tested: gpt-6-luna (only gpt-5.6-luna, 1829), glm-5.3-flash, qwen3.7-plus, minimax-m3.
  - https://eqbench.com/creative_writing.html
- **EQ-Bench Longform** (same judge): gpt-6-sol 82.8, GLM-5.3 81.8 (slop 7.1), kimi-k3 79.6, claude-sonnet-5 78.3, DeepSeek-V4-Pro 75.6, deepseek-v4.1-flash 74.0. https://eqbench.com/creative_writing_longform.html
- **Limits of EQ-Bench:** it tests fiction. Its author says judges favour longer outputs and that it doesn't control for judges preferring their own writing (https://eqbench.com/about.html). Surge found its grader agrees with expert writers as little as 43% of the time (https://surgehq.ai/blog/hemingway-bench-ai-writing-leaderboard).
- **Arena creative writing** (crowd votes, 2026-09-25): qwen3.8-max #18, kimi-k3-max #25, glm-5.3-max #27, gpt-6-sol-max #34, deepseek-v4-pro #45, claude-sonnet-5-high #61, glm-5.3-flash #65, minimax-m3 #94, gpt-6-luna-max #99 (939 votes). https://arena.ai/leaderboard/text/creative-writing
- **Older than every model on our list:** Hemingway-bench (Feb 2026) and WritingBench, whose leaderboard is all self-reported Qwen3 and Kimi K2 scores (https://llm-stats.com/benchmarks/writingbench).

**2. Writing in other languages**
- **Arena's per-language boards** are the only signal for current versions. They measure general chat, and error bars run ±15–45 points, so read ranks as rough bands.
  - glm-5.3-flash sits in the upper middle everywhere: French #21, Russian #38, Spanish #39, German #49.
  - minimax-m3 and deepseek-v4-flash sit near the bottom of all four (#87–101).
  - Boards: https://arena.ai/leaderboard/text/german (also /french, /russian, /spanish). There is no Turkish or Azerbaijani board.
- **Human translation ratings** (versions unstated): Anthropic leads German and Turkish; no Qwen, GLM, Kimi or MiniMax models were tested. https://alconost.com/en/blog/best-llm-for-translation-2026
- **M-GATE** (Aug 2026): translation quality tracks how much of the web is in a language (r=0.86), so Azerbaijani is likely the weakest language for every model. https://arxiv.org/abs/2608.03803
- **Azerbaijani:** I found no writing benchmark.
- **Known failure:** DeepSeek and Qwen drift into Chinese mid-reply. https://arxiv.org/abs/2507.14894

**3. Censorship**
- **It lives in the weights, mostly as softening.** CEIAS (Apr–May 2026) queried DeepSeek V3.2, Kimi K2.5, Qwen 3.5 and GLM-5 through OpenRouter. Findings:
  - Taiwan questions failed 42–86% of the time.
  - Communist Party talking points appeared in 24% of English answers and 59% of Mandarin ones on the most sensitive topics.
  - The same messaging leaks into questions about other countries.
  - https://ceias.eu/chinese-llms-and-the-spillover-effects-of-political-alignment/
- **Refusals also survive a US host.** DeepSeek R1 through OpenRouter refused 85% of 1,156 sensitive prompts (https://www.promptfoo.dev/blog/deepseek-censorship/). NIST found Kimi K2 Thinking gave Communist Party-aligned answers 26% of the time in Chinese against 7% in English (https://www.nist.gov/news-events/news/2025/12/caisi-evaluation-kimi-k2-thinking).
- **Some blocking is the vendor's own service.** GLM 5.2 blanked Tiananmen on Z.ai but answered through OpenRouter. That test used only 3 prompts. https://takshashila.org.in/content/blogs/20260704-open-weight-model-censorship.html
- **Current models:** DeepSeek V4 Flash denied evidence of Uyghur camps (https://www.semafor.com/article/07/29/2026/censorship-in-chinese-ai-models-can-be-undone-new-research-shows). I found no measurement of GLM-5.3, K3 or Qwen3.7.

**4. Long-form techniques**
- **Paragraph-by-paragraph writing** (LongWriter) exists to get past length limits at 10,000+ words. We don't need it at 1,000. https://arxiv.org/abs/2408.07055
- **Outlines** help structure: STORM's articles were judged organised 25 points more often than a baseline. https://arxiv.org/abs/2402.14207
- **Self-critique and rewrite** gained about 20%, but weak models rewrite poorly. https://arxiv.org/abs/2303.17651
- **Draft, edit, then rank** with a trained quality scorer won expert preference 66% of the time. Off-the-shelf models judging quality did barely better than chance. https://arxiv.org/abs/2504.07532
- **Stock AI phrases** run over 1,000 times more often than in human text. The Antislop fix needs sampling control that OpenRouter lacks, so we would use a detect-and-rewrite pass instead. https://arxiv.org/abs/2510.15061
- **Thinking modes** give "limited gains on open-ended writing" (https://arxiv.org/abs/2604.03004). On EQ-Bench, Kimi-K2-Thinking scored 1631 against 1666 for the plain version, and heavy-reasoning DeepSeek-V3.2-Speciale 1276 against 1515.
- **Models write alike**, so picking the best of several drafts from one model adds little variety (NeurIPS 2025). https://proceedings.neurips.cc/paper_files/paper/2025/hash/754d5a526a5ee5a47220664a0eb92751-Abstract-Datasets_and_Benchmarks_Track.html

**5. Checking letters against the facts**
- **Established methods:**
  - FActScore splits text into single facts; its automatic score lands within 2% of humans averaged over whole texts. https://arxiv.org/abs/2305.14251
  - SAFE agreed with crowd raters 72% of the time and cost a twentieth as much. https://arxiv.org/abs/2403.18802
  - VeriScore checks only claims that can be verified. https://arxiv.org/abs/2406.19276
- **Small checkers:** MiniCheck (770M parameters) matches GPT-4 at 400 times lower cost (https://arxiv.org/abs/2404.10774). The best leaderboard score is about 77% accuracy (https://llm-aggrefact.github.io/). So they flag problems rather than settle them, and they are trained on English.
- **Pitfalls:** splitting text into claims adds its own errors (https://arxiv.org/abs/2411.02400). Checkers are biased against paraphrase, which letters do constantly, so expect false alarms (https://arxiv.org/abs/2501.14883).

**6. Models judging writing**
- **Known biases:** judges favour the first answer shown, longer answers and their own writing (https://arxiv.org/abs/2306.05685, https://arxiv.org/abs/2404.13076). The bias extends to same-family models (https://arxiv.org/abs/2502.01534), and order bias peaks when drafts are close (https://arxiv.org/abs/2406.07791).
- **Rubrics:** the wording of the rubric alone predicts verdicts. https://arxiv.org/abs/2609.02942
- **Accuracy:** the best off-the-shelf judge agreed with humans on stories 73% of the time, against 78% for a trained scorer. https://aclanthology.org/2026.eacl-long.362/

**Recommendations for choosing and running a cheap writer**
- **Shortlist:** GLM-5.3, GLM-5.3-flash and gpt-6-luna, with Sonnet 5 as the control. Drop MiniMax M3 and DeepSeek V4 Flash.
- **Own blind test:** about 30 real fact lists across our languages, compared in pairs with order swapped. Use a judge from a third model family, plus native speakers for Turkish, Russian and Azerbaijani.
- **Pin the OpenRouter host:** turn fallbacks off and log the host. A serving change alone has shifted scores 16.6 points. https://www.lesswrong.com/posts/KsyoSAyBRXtwzSugg/not-pinning-your-openrouter-provider-might-invalidate-your
- **Pipeline:** outline, one-pass draft, then one fix pass driven by outside checks, not self-critique.
- **Thinking mode:** off or low for drafting.
- **Fact check:** check each sentence against the fact list with a model from a different family; failures get a rewrite, then a person.
- **Checks in code:** output language, stray Chinese characters, word count.
- **Sensitive stories:** send stories touching Uyghur, Tibetan, Hong Kong or Taiwan topics, or human-rights work, to a non-Chinese writer.
- **Judges:** let them catch defects, not pick the best prose, until checked against people.
- **Cost:** $0.001–0.045 a letter, and under $0.25 even for four drafts. Price doesn't separate the candidates.

Assumptions: Arena rows were read through a page summariser, so spot-check them. The Qwen "max" mapping is unconfirmed. Costs assume about 5k tokens in and 2k out; Turkish, Russian and Azerbaijani use more tokens. Full notes: /tmp/claude-1000/-home-orkhan-Desktop-elmify--worktrees-letter-shape/70e5adfd-8661-41b5-bc11-8d8362fb829f/scratchpad/research-models/notes.md
