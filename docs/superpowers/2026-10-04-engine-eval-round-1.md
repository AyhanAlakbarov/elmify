# Engine evaluation, round 1 — 2026-10-04

Plan 1, Task 14 (`docs/superpowers/plans/2026-10-03-engine-eval-harness.md`), run as
`manage.py engine_eval --run 2026-10-r1` against a database of its own (`tehsil_eval_r1`). Run files
live in `.superpowers/engine-eval/2026-10-r1/` (gitignored). The owner's gold check is **not done
yet**; everything below is scored against the model-built key, which tunes and never certifies.

## Spend

| | budget | spent |
|---|---|---|
| OpenRouter | $15 cap (owner) | **$15.32** (the harness counted $15.00; ~$0.32 went on calls billed and then failed, which the 3-unmetered-calls stop is there to bound) |
| Firecrawl | — | 755 credits (estimate was ~400) |
| Brave | — | 29 searches |

## Page set

83 pages fetched, 79 served, 3,893 lines. The budget could not key all of them, so the round was cut
twice, keeping page and scheme spread: every served page with lines capped per page (2,158 lines),
then the answer key stopped at its own cap at **1,400 lines over 53 pages**, interleaved by language
so every language got a share. `items-full.jsonl` and `items-2158.jsonl` keep the larger sets.

| language | lines | pages | schemes |
|---|---|---|---|
| az | 411 | 14 | 8 |
| tr | 344 | 13 | 11 |
| ru | 313 | 13 | 4 |
| en | 332 | 13 | 5 |

Below the plan's 450 lines and 15 pages per language. Not served: three Azerbaijani pages yielded no
lines (`htp.edu.az/az/content/20`, `dp.edu.az/az/news/4877`, `dp.edu.az/az/faq`) and DAAD PRIME was
scheduled for retry. Tune/score halves (by page): 456 / 944 lines.

## The key

GPT-5.6-sol and Claude Sonnet 5.5 label, Claude Opus 5.5 referees disputes blind and audits 10% of
agreements. 221 disputed answers; 229 lines audited, **4 overturned (1.7%)** — the rate at which both
labellers share an error.

Two cost findings changed the code (commits on `claude/engine-eval-round-1`):

- **One line a call cost ~$0.009 a line**, not the ~$0.002 estimated. Reasoning effort is not the
  driver (medium vs low: same cost); the definitions resent with every line and the answers
  themselves are. The key now labels 8 lines of one page per call and the referee pools lines across
  calls: ~$0.006 a line. On 25 lines keyed both ways, batched labels agreed on 199 of 200 answers.
- **Anthropic's strict schemas refuse 10 lines × 8 questions** ("The compiled grammar is too
  large"); 8 lines is accepted.

## Readers

| reader | lines read | note |
|---|---|---|
| Jev, wording A | 1,400 | $0.06 |
| Jev, wording B | 1,400 | $0.05 |
| Firecrawl quote reader | 1,400 | from the page fetch's JSON extract |
| DeepSeek V4.1 Flash (Fireworks) | **313** | stopped twice on 3 consecutive failed calls |
| Kimi K3 (Makora) | 1,248 | meant for unsettled lines only; read nearly all because Flash had not |
| Gemini 3.5 Flash | 950 | reasons, so returns no probabilities — scored on its vote; stopped at the cap |

DeepSeek V4 Pro was not used: on all four hosts probed (streamlake, parasail, cloudflare, reka) it
answered the control item wrong — a 43,000 HUF monthly stipend as `in_kind_value` — the same on every
host that answered, so the model, not a host. V4.1 Flash answered it right; Kimi K3 passed every check.

The chat readers also moved to 8 lines a call with the page as the cached prefix: one line a call
cost ~$0.003 a line on Flash and ~$0.013 on Kimi with no cache hit; batched and cached, $0.0014 and
$0.0085 per 8 lines, with every answer still carrying its own probability.

## Results — "yes" facts (what a card shows), against the key

All 1,400 lines; 435 true "yes" facts.

| policy | says yes | wrong | yes-precision | yes-recall |
|---|---|---|---|---|
| Jev A ≥ 0.8 | 293 | 8 | 0.973 | 0.66 |
| Jev A ≥ 0.95 | 178 | 2 | 0.989 | 0.40 |
| Jev B ≥ 0.95 | 151 | 1 | 0.993 | 0.34 |
| Kimi ≥ 0.95 (1,248 lines) | 235 | 7 | 0.970 | 0.55 |
| **Jev A ≥ 0.8 and Kimi ≥ 0.8** | 238 | 3 | **0.987** | 0.56 |
| Jev A ≥ 0.5 and Kimi ≥ 0.5 and Gemini yes (950 lines) | 254 | 7 | 0.972 | 0.72 |
| Gemini vote alone (950 lines) | 390 | 93 | 0.762 | 0.87 |
| Jev A ≥ 0.8 and Flash ≥ 0.8 (313 lines, 62 true yes) | 39 | 0 | 1.000 | 0.63 |

Jev A ≥ 0.8 and Kimi ≥ 0.8, by kind: deadline 32/1 wrong (0.969), eligibility 150/0 (1.000),
money 56/2 (0.964). By language: az 43/0, tr 100/1, ru 52/2, en 43/0. By question, the misses sit
in `costs_covered` (2 of 24 wrong) and `application_date` (1 of 32); every other question was clean.

Learn-then-Test set no bar for any stratum, as expected: zero errors at 1/1000 needs 2,995 tuning
rows and this round had 456. The report (`report.md`) shows precision and upper error at every bar.

## What it shows

1. **Wording A beats B on recall at the same precision** (0.66 vs 0.64 at 0.8; 0.40 vs 0.34 at 0.95).
2. **A second reader buys precision, not recall.** Jev and Kimi together cut errors from 8 to 3 at
   0.8 for 10 points of recall. Russian is where it matters most (Jev alone: 4 wrong of 61).
3. **Gemini is a liberal third vote, not a reader** (0.76 alone), as in the 2026-10-03 spike.
4. **Flash looks as good as Kimi on its 313 lines and is ~6× cheaper**, but 313 lines (62 true yes)
   cannot rank them, and its host failed twice. Round 2 should give Flash the whole set.
5. Still not shown: 1 wrong in 100 with confidence. 238 accepted with 3 wrong is consistent with
   ~97–99.7%.

## Decision for round 2 (proposed, pending the owner's gold check)

- Jev wording A for every question.
- Second reader: re-run Flash on all lines (≈ $0.5) before choosing between Flash and Kimi; probe a
  second Flash host so one host's outage does not stop the run.
- Third reader: keep Gemini only as a confirming vote; drop it if the gold check shows its extra
  recall is wrong more often than the key says.
- Fix before round 2: Kimi's `--only-unsettled` treated lines the second reader never read as
  unsettled, which is what spent the budget — such lines should wait for the second reader.

## Owner's gold check — done 2026-10-05

The owner checked all 114 queued facts (Jev A and Kimi K3 both "yes" at the 0.9 joint bar, score half)
on a private check page; verdicts imported into `GoldItem` with one `AuditEvent` each.

| kind | right | precision | 95% upper error |
|---|---|---|---|
| deadline | 14/14 | 1.000 | 0.193 |
| eligibility | 66/70 | 0.943 | 0.126 |
| money | 29/30 | 0.967 | 0.149 |
| all | 109/114 | **0.956** | 0.090 |

The model key agreed with the owner on 107 of 114. All five errors are question definitions, not
reading:
- **Postdoctoral is not a study level** (two TÜBİTAK/EMBO postdoc lines read as `level_rule`).
- **A current-study condition is not the level offered**: "Учитесь в магистратуре или на 3–4 курсе
  бакалавриата" is who may apply, not what the award is for.
- **"Xarici universitetə təhsil haqqı ödənilmir"** — "no tuition fee is paid to the foreign university" —
  says the programme does not pay tuition; both readers read it as a fee waiver.
- **A pointer is not a condition**: "citizenship requirements as defined by the binational agreement"
  states that a rule exists elsewhere. The owner's notes on two lines marked right say the same of
  "if your country is not listed in the dropdown": the engine should follow the pointer and read the
  list, not stop at the sentence.

## Owner's gold check — the earlier "pending" note

114 facts queued for improvement round 1 (`GoldItem`, run `2026-10-r1`): deadline 14, eligibility 70,
money 30. Few deadline facts because Jev and Kimi agree on few deadline lines at the 0.9 bar in the
score half. **Not checkable on `/platform/gold/` locally yet**: the operator gate requires staff MFA and
`/mfa/setup/` has no template (`TemplateDoesNotExist: tenancy/mfa_setup.html`) until the presentation
layer exists.

## Round 2 plan — agreed 2026-10-05 with session tehsil-agent-75 (awaiting the owner's approval and cap)

That session measured second readers on 100 card facts Jev was unsure of, against a key of DeepSeek
V4.1 Flash + GPT-5.6 Luna with Sol on disputes (no Anthropic model; it flatters the DeepSeek family):
Claude Sonnet 5.5 87/100, Opus 5.5 80, DeepSeek V4 Pro 67, GLM 5.3 Flash 58, Jev alone 48, Kimi K3 36
(36 non-answers under reasoning=low — configuration, not the model; thinking-off on makora answered
every line here). Findings: `~/agent-workspace/second-reader-findings.md`; items: `compare_second_readers.py`,
seed 20261004.

Round 1 on Jev's unsure band (0.2 ≤ Jev < 0.8; 427 facts, 121 true yes), re-scored at $0: Jev 330/427,
Kimi 355/427 but 68/121 on true yes (56%), Flash 79/86 (16/20 true yes, small n), Gemini vote 281/345.
Kimi is a modest gate and a weak resolver.

**Conclusion.** A cheap second reader adds precision as a gate but resolves Jev's unsure band poorly.
Round 2 tests Claude Sonnet 5.5 both as gate and as resolver of that band, and DeepSeek Flash on every
line with a backup host, against a key built with neither an Anthropic nor a DeepSeek model (GPT-5.6-sol
plus one other family; Sol at high effort referees), with non-answers counted apart from wrong answers
and the owner's gold sampled from the unsure band. Fixes first: `--only-unsettled` must not treat lines
the second reader never read as unsettled; check OpenRouter account credit before a paid step.

### Superseded the same day by the owner's hand check

The owner checked 40 card facts Jev was unsure of (az 14, ru 12, ko 8, fr/en/tr 6) with Sonnet's
answers: Sonnet right 14, wrong 25, can't tell 1. Where Sonnet agreed with tehsil-agent-75's model key
(12 facts), the owner marked 5 wrong. **On the hard band a model key is wrong far more often than its
audit suggests** (that key's Sol audit: 2.5%; this round's Opus audit: 1.7%), so every precision above
is a ceiling relative to a key that is itself unreliable near Jev's bar, not a measured error rate.
The 87/100 for Sonnet did not hold.

The owner's notes put most errors in the question definitions, not model strength:
- a "scholarship X per month" is not "for living costs" unless the page says living costs
  (round 1's `costs_covered` already excludes money paid to the student);
- a period answer is often a duration ("during the first year", "first semester only"), so frequency
  and duration need separate options (round 1 asked neither);
- a bound needs "approximately" ("approximately 100 AZN");
- a place inside an institution's name ("Azərbaycan Dövlət Aqrar Universiteti") means that
  institution's students may apply; "Française / EU" means French or EU applicants (round 1 has no
  institution rule, so `nationality_rule` judgements on such lines are suspect).

**Revised conclusion (agreed with tehsil-agent-75, owner has no API budget now):** fix those question
definitions first, since they bind Jev and every reader; then certify on owner gold sampled from the
unsure band before choosing any second reader. No paid step until then. The 114 facts queued from this
round are agreements, so they measure the precision of what a card would show, not which reader
resolves the hard band. Owner data: `~/agent-workspace/tehsil-jev-harness/check2_items.json`,
`verdicts2/`, `verdicts/`.

**Question definitions v2** (tehsil-agent-75, validated on 36 owner-gold facts at ~$0: Jev 13/36 →
27/36): `~/agent-workspace/tehsil-jev-harness/question-definitions-v2.md`. They are card-fact
questions asked per amount or per place — `covers_<item>`, `period` split into frequency and duration,
`bound` with `range` and `approximately`, `eligible` per place including institution names — not this
harness's eight line questions, which score none of them (`amount_role` is read, never keyed). Porting
them is an item-model change for the harness (amount and place items, as in plan 3's card reader),
plus code-side range detection ("A~B", "A–B", "between A and B", "entre A et B", "от A до B",
"A ilə B arası" → `range` without asking), which `evidence.py` does not do yet. Do both with plan 3,
not as edits to the line questions.
