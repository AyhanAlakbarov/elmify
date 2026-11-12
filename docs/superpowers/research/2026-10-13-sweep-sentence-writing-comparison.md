# How the sweep's search sentences are written — compared, decided, closed (2026-10-13)

**Status: CLOSED.** Owner's instruction, 2026-10-13: do the recommendations and mark the study done
so it is not reopened. Reopen only on one of the triggers at the end. **The second trigger fired on
2026-10-14 and the level was taken back out** (last section); everything else stands.

**Question.** `apps/research/angles.py` turns the kind-word list into page-voiced search sentences
with one model call per (country, family, language). Is a model the right way to write them, and
which model? Nothing in `docs/` had compared alternatives before this run; the page-voiced *shape*
was researched (2026-09-24 query-design note, master spec §6.3), the *writer* was not.

**Decision.**
- **Keep a model as the writer, and make it DeepSeek V4.1 Flash** (`SWEEP_ANGLE_MODEL`, through
  OpenRouter, `angles.OpenRouterParser`), as the 2026-10-03 engine design already named it.
- **Three prompt faults fixed:** the study level (Wikidata's label for master's degree, `MASTER` in
  `resolver_data/holder_kinds.json`) is now in every sentence, written as the students a funder
  funds; the cycle's years are digits; Brave keyword versions with more than three operators are
  stored empty, so Brave gets the sentence instead.
- Hand templates scored highest but are not adopted: the margin is within luck, and they need a
  person who writes each language — about 50 of them.

## Method

Turkish private foundations only. Each option wrote sets of six sentences, one per page type
(application, eligibility, this year's call, about, FAQ, PDF call). Every sentence went to Exa
(`type: auto`, 15 results, aggregators excluded). A **funder found** is a domain on the official
foundation register (VGM, 4,028 entries, local copy `elmify_ladder_tr`) or a new foundation-like
site labelled by hand; **noise** is news, blogs, listings and unrelated companies.

**Luck, measured rather than assumed.** Exa returns identical results for an identical query (six
sets rerun: 0 differences), so rerunning shows nothing. The variation is in the wording: different
sentences of the same kind find different sites. So each option got 10–12 differently worded sets,
and gaps were tested with a permutation test (how often a random split of the sets gives a gap as
large as the observed one).

## Results

**Round 1 (3–4 sets per option, before any fix):**

| Option | Funders per set | Noise |
|---|---|---|
| Model, DeepSeek | 42, 53, 45, 47 | 8% |
| Model, gpt-5.6-luna | 40, 47, 49, 18 | 13% |
| English, then translated | 50, 13, 44 | 24% |
| Bare words | 27, 44, 31 | 15% |
| Hand templates | 29, 42, 20 | 27% |
| Copied lines from real funder pages | 18, 6, 21 | 54% |

Copied page lines were dropped here: every set scored below every DeepSeek set. Round 1 also found
the prompt faults: 0 of 66 model sentences named the study level; luna wrote years as words
("iki bin yirmi altı"); luna's six Brave keyword versions returned **zero** results (stacked
`inbody:` operators); the translate path put a real foundation's name ("Koç Vakfı") in every sentence
of one set, steering the set to that one funder (13 found).

**Round 2 and 3 (10–12 sets per option; all include the master's level):**

| Option | Funders per set (sorted) | Mean | Noise |
|---|---|---|---|
| Hand templates | 26 28 29 29 30 34 35 35 40 41 | 32.7 | 19% |
| Model, DeepSeek, final prompt | 15 20 24 24 24 25 26 29 35 37 38 39 | 28.0 | 17% |
| Bare words | 21 22 22 26 27 27 27 29 30 36 | 26.7 | 22% |

| Gap | Size | Chance it is luck |
|---|---|---|
| Templates vs model | +4.7 | 12% — not shown |
| Templates vs bare words | +6.0 | 1.4% — real |
| Model vs bare words | +1.3 | 65% — none |

**A fix that backfired, kept here so it is not repeated.** The first level fix gave the model the
Wikidata label *and* its aliases. It wrote "yüksek lisans derecesi" (the master's *degree*) in 42 of
60 sentences and found programme pages. The final prompt gives the label only and asks for the
students the page funds ("yüksek lisans öğrencilerine burs").

**What naming the level costs.** Without the level, DeepSeek found 29.5 register foundations per
set; with it, about 15. Most register foundations fund undergraduates and their pages never say
"yüksek lisans". The narrower set is the target population, but this run cannot show it is *more
useful*: that needs the reader to say which found funders actually fund master's students.

**Brave keyword leg.** After the operator cap, Brave returned results again (51–52 domains per set)
but 41–63% of them were noise, against Exa's 17%.

## Cost

About **$5.15**: Exa about $4.90 (68 sets of 6 searches), Brave about $0.24, models about $0.06
(OpenRouter). The OpenAI account itself had **no credits** ("credit_balance_exhausted"), so luna
was reached through OpenRouter; every module still on `OPENAI_EXTRACTION_MODEL` fails until it is
topped up.

Query sets, raw results, labels and scripts: `~/agent-workspace/elmify-runs/sentence-writing-test-2026-10-13/`.

## Limits

One country, one family, one engine scored. Labels for new domains were assigned by hand from the
domain and general knowledge, without visiting each site. "Funder found" says the body exists and
looks like a foundation, not that it funds master's students.

## Reopen only if

- a sweep's per-angle tally (`sweep_tally`) shows the model's angles finding clearly fewer new
  funders than the earlier sets in some country — then compare templates there;
- the reader's yield shows the master's-level narrowing drops funders that do fund master's
  students;
- the writer model changes (re-run round 3's 12 sets against round 3's numbers, about $0.90).

## Reopened once, 2026-10-14: the level is out of the sentences

The second trigger fired. 24 register foundations were found only by the sets that do **not** name
the level. A reader of each of the 19 foundation sites among them (the 5 universities were not read)
found: **5 fund master's students** (fabev, semayazar outright; gev, tesyev and cebi narrowly: one
university's four departments, disabled students, one surname), 6 fund undergraduates only, 1 school
pupils, 7 unclear (no level stated, rules behind a login or in an unreadable file). So the level
hid about as many real master's funders as wrong ones, and the reader already reads a funder's level
off its page. Separately, Wikidata's word for the level was wrong or outdated in Italian, French,
Danish and Slovenian, and only a word the writer happened to ignore could be caught.

**Owner decision, 2026-10-14: remove it.** The prompt now says never name a study level; `MASTER` is
gone from `holder_kinds.json`, `kind_words.json` and the corrections; the language screen has no
level column.

**Not yet true, and owed before any sweep runs these sentences:** no reader records which level an
award funds (`apps/funding/grouping.py::_levels_agree` treats an award with no level as fitting every
level, and nothing fills `funding_card["degree_levels"]`). Owner rule, 2026-10-14: only master's
counts. A funder is shown when its page says it funds master's, dropped when the page says it does
not, and sent to a Elmify staff review (yes or no, recorded) when the page does not say. Per-site
verdicts and quotes: `~/agent-workspace/elmify-runs/sentence-writing-test-2026-10-13/masters_check_2026-10-14.md`.

## Japan, South Korea and Russia, 2026-10-14 (owner: "run them")

Same writer (DeepSeek V4.1 Flash), private-foundation pass, the local language only: 36 sentences per
country without the level (current code) and 36 naming it (`2d7e7ba1`, the commit before removal), all
through Exa, 15 results each, aggregators excluded. Exa cost **$2.59**. Raw sets, results and the per-site
reading: `~/agent-workspace/elmify-runs/funder-level-check-2026-10-14/`.

| | Japan | South Korea | Russia |
|---|---|---|---|
| sites found without the level / with it | 189 / 104 | 105 / 74 | 169 / 105 |
| found only without / only with | 122 / 37 | 62 / 31 | 108 / 44 |

A random 15 "only without" and 10 "only with" sites per country were read (75 sites, in-session tools):

| group | sites | real funders | university's own | pass-on or other | open to master's | not open | unstated | "students" in general |
|---|---|---|---|---|---|---|---|---|
| only without the level | 45 | 23 | 8 | 13 | 10 | 12 | 4 | 5 |
| only with the level | 30 | 4 | 11 | 13 | 5 | 2 | 4 | 4 |

Scaled to the "only" sets, the level-free sentences add about 65 award sites open to master's students
that the level sentences miss (JP ~41, KR ~4, RU ~29), against about 19 the other way (JP ~11, KR ~6, RU 0).
Small samples: South Korea is even within luck. **The removal stands**, and the cost is visible: about
half of the extra real funders are **not** open to master's (12 against 10), so the card reader's level
check (owned by `elmify-6a`, slice 3) is what makes the level-free sentences safe to serve.
Two more lessons: naming the level mostly finds university notice boards that pass on someone else's
award (Potanin, Samsung Dream, Iwatani) — name sources, not the funder's own page; and about a third
of the returned URLs were PDFs, which the in-session reader could not open, so those verdicts read the
page announcing the file. Read verdicts: `sample_verdicts.md` in the run folder.

