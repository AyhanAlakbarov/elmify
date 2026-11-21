# Settling three engine questions — measured 2026-10-03

Throwaway spike (`scratchpad/settle/settle.py`, not committed). 16 real funding pages fetched with
Firecrawl (`onlyMainContent`), split into 443 lines: Azerbaijani 107 (edu.gov.az, htp.edu.az, ADAU),
Turkish 124 (TÜBİTAK 2215, MEB, YÖK, Türkiye Bursları), Russian 90 (two Russian-quota university
pages, Bolashak), English 122 (Stipendium Hungaricum). Five yes/no questions per line
(receives_money, fee_waived, application_date, who_may_apply, no_funding) → 2,215 items, 116 of
them true "yes". Total spend ≈ $1.10 (key $0.82).

**Key.** GPT-5.6-sol and Claude Sonnet 5.5 labelled every item, each line read alone; 97 of 2,215
answers (4.4%) disagreed and Claude Opus 5.5 settled them. Neither family is under test.

**Readers.** Jev 1.13 on the original lines (30-line chunks, `inspect` per line); Jev on a DeepSeek
V4.1 Flash line-by-line English translation; DeepSeek V4.1 Flash on Fireworks (thinking off, strict
enum, logprobs, the page as cached first message, one call per line) as the second reader.
Cost: Jev ≈ $0.006 per arm for all 443 lines; translation $0.023; second reader $0.06.

## Results

"Yes" facts are what a card shows (a deadline exists, who may apply), so they are scored apart:
yes-precision = share of "yes" answers that are right; yes-recall = share of true "yes" facts kept.

| Policy (all languages) | says yes | wrong | yes-precision | yes-recall |
|---|---|---|---|---|
| Jev ≥ 0.95 alone | 34 | 0 | 1.000 | 34/116 |
| Jev ≥ 0.80 alone | 68 | 9 | 0.868 | 59/116 |
| DeepSeek ≥ 0.95 alone | 63 | 3 | 0.952 | 60/116 |
| DeepSeek ≥ 0.99 alone | 55 | 2 | 0.964 | 53/116 |
| Both agree: Jev ≥ 0.5 and DeepSeek ≥ 0.95 | 59 | 2 | 0.966 | 57/116 |
| Both agree: Jev ≥ 0.8 and DeepSeek ≥ 0.95 | 53 | 1 | 0.981 | 52/116 |
| Both agree, Jev on English translation | 60 | 2 | 0.967 | 58/116 |

By language, "both agree: Jev ≥ 0.5, DeepSeek ≥ 0.95": az 8/8 right (recall 8/20), tr 41/41
(41/79), ru 5/6 (5/12), en 3/4 (3/5). By question: application_date 20/20 right and 20/20 kept;
who_may_apply 28/30 right, 28/66 kept; receives_money 6/6, 6/18 kept.

All items, "no" included: Jev ≥ 0.95 covers 1,808 of 2,215 with 2 errors (99.9%); in Jev's
0.5–0.7 band Jev is 58% right, and where DeepSeek disagrees there DeepSeek is right 39 of 50 times.

## What it settles, and what it does not

1. **The second reader adds accuracy — mainly by keeping facts Jev is unsure of.** Jev is almost
   never wrong when confident, but it is confident on only 29% of true "yes" facts; lowering its bar
   alone costs precision (0.868 at 0.80). A second reader agreeing keeps 45–49% of "yes" facts at
   0.966–0.981 precision. DeepSeek alone is nearly as good as the pair here, so the pair's value over
   DeepSeek alone is a small precision gain (one fewer error in ~55), not a large one.
2. **Jev on non-English text:** no language failed outright at high bars — Azerbaijani and Turkish made
   no "yes" errors under the agreement policy; Russian made one in six. The weakness is recall in every
   language (English included), not a language collapse. Russian and English yes-counts (12, 5) are too
   small to rank languages.
3. **Translating first (DeepSeek translation) changed almost nothing:** 58 vs 57 facts kept, same
   precision; at the loose 0.5 bar it halved Turkish false "yes" answers (32 → 15) but those are
   removed by the bars anyway. Google/Azure translation was not tested (no key).
4. **No policy is shown to reach 1 wrong in 100 on "yes" facts.** The best, 52 right of 53, has a 95%
   lower bound near 0.90. Proving 0.99 needs ~300 "yes" facts with no error — about 3× this run.
5. **Recall, not precision, is the binding constraint under verified-only.** At the safe policies about
   half the true deadline/eligibility/funding facts are not confirmed, so an award would be hidden
   unless the verification ladder (verified-catalog) confirms them another way.

## Caveats

- The key labelled each line alone; DeepSeek saw the whole page; Jev saw 30-line chunks without
  headings. Context differences favour DeepSeek and depress Jev's recall on lines whose meaning needs
  the heading ("who may apply" lines especially).
- 116 "yes" facts; per-language yes-counts are small (az 20, ru 12, en 5).
- The key's own error rate is unknown; 4.4% of answers needed the referee.
- One wording per question; no order-swap or A/B wording arms.
