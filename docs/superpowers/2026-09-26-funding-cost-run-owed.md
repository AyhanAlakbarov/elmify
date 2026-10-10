# Item 15 cost run — prepared, NOT run (owed)

Plan: `docs/superpowers/plans/2026-09-25-cost-batch-flex-and-cheap-first-read.md`, Task 12.
Everything Task 12 measures needs live vendor and model keys, and none existed in the session
that built this (2026-09-26). **No number below is a measurement, and no cost figure is
estimated here.** The plan's §Task 12 Step 2 spend table is the plan's own estimate. It is
repeated nowhere in this note, because a saving nobody measured is not a saving (item 15's
brief).

When the owner approves the spend, this note becomes the checklist. The results go into a new
`docs/superpowers/<run-date>-funding-cost-run.md`, as Task 12 Step 9 describes, and this
file is deleted in the same commit.

## What is owed

| # | Measurement | Instrument (built) | Status |
|---|---|---|---|
| 1 | The Claude system prefix is ≥ 1,024 tokens, Sonnet 5's minimum cacheable length | `test_funding_cost_live.py::test_the_claude_system_prefix_is_long_enough_to_be_cached` | owed |
| 2 | `OPENAI_EXTRACTION_MODEL` accepts `service_tier="flex"` and bills it | `…::test_the_extraction_model_accepts_flex_and_reports_the_tier_it_billed` | owed |
| 3 | Both batch APIs accept the request shapes, including structured output | `…::test_one_page_reads_through_both_batch_apis` | owed. The request shapes were checked offline only: the real SDKs were run through a mock HTTP transport and the batch bodies equal the synchronous ones |
| 4 | Firecrawl answers the first-read `json` schema; `checkPromptInjection` is accepted inside the format entry | `…::test_a_real_page_answers_the_first_read_schema` | owed |
| 5 | Per changed page: standard vs standard (noise floor) vs flex vs batch, in tokens, dollars, verdicts and wall-clock | `funding_yield --save-pages/--load-pages --cost-csv --reading-tier`, then `funding_cost_compare` | owed |
| 6 | Prompt-cache hit shares (OpenAI cached / input; Claude cache-read / input) | the cost CSVs' token columns | owed |
| 7 | Our meters against the vendors' consoles (gap ≤ 5%) | by hand, with dedicated keys | owed |
| 8 | §8.9 first read vs judge: ≥ 30 human labels per reader; outcome (a), (b) or (c) | `first_read_gate --out`, then a person labels the sheet, then `--score` | owed; labels are a person's |

## Before the run

- **OpenAI price row.** `MODEL_PRICES_USD_PER_MTOK` has no row for `gpt-5.6-luna`, because
  OpenAI's pricing pages were unreachable from the build environment. Until someone reads the
  published price and adds the row, every OpenAI reading is reported *unpriced*, in tokens only,
  and the dollar totals are a floor. On the same page, confirm that flex and batch are 50% of list
  for that model. `MODEL_TIER_MULTIPLIER`'s comment marks the OpenAI rates as unverified.
- Dedicated OpenAI and Anthropic keys for the run, so that step 7's console figures contain nothing
  else.
- A Firecrawl credit balance that covers the fetch run and `first_read_gate --credits`.

## Commands (corrected against master as of 2026-09-26)

The plan wrote `DATABASE_ROLE=migration` for the fetching runs. Since `funding/0049_catalog_grants`,
the catalogue's writer is **`runtime_engine`** (see `CATALOG_ROLE_NOTE`), so use that role.
`--save-pages` now refuses a directory that already holds pages, so use a fresh one per run.

```bash
uv run pytest tests/research/test_funding_cost_live.py -m live -v -s     # 1-4

export RUN="$HOME/item15-run"          # outside the repository: saved pages are page bytes
HOSTS=docs/research/2026-09-18-yield-hosts.txt
time DATABASE_ROLE=runtime_engine FETCH_SWEEP_CREDITS_FIRECRAWL=300 uv run python manage.py \
  funding_yield --hosts "$HOSTS" --pages 4 --save-pages "$RUN/pages" \
  --cost-csv "$RUN/standard-1.csv" | tee "$RUN/standard-1.log"
for tier in standard flex batch; do
  out=$([ "$tier" = standard ] && echo standard-2 || echo "$tier")
  time uv run python manage.py funding_yield --hosts "$HOSTS" --load-pages "$RUN/pages" \
    --reading-tier "$tier" --cost-csv "$RUN/$out.csv" | tee "$RUN/$out.log"
done
uv run python manage.py funding_cost_compare "$RUN/standard-1.csv" "$RUN/flex.csv" \
  --repeat "$RUN/standard-2.csv" | tee "$RUN/flex-vs-standard.txt"
uv run python manage.py funding_cost_compare "$RUN/standard-1.csv" "$RUN/batch.csv" \
  --repeat "$RUN/standard-2.csv" | tee "$RUN/batch-vs-standard.txt"

time DATABASE_ROLE=runtime_engine uv run python manage.py first_read_gate --hosts "$HOSTS" \
  --pages 2 --credits 600 --out "$RUN/first-read.csv" | tee "$RUN/first-read.log"
# a person labels judge_correct / first_correct, y or n, against the live page; then:
uv run python manage.py first_read_gate --score "$RUN/first-read.csv"
```

Gate criteria, the cache-share script and the reconciliation rule are in the plan's Task 12,
Steps 5, 6 and 8. They are not restated here.

## Known limits of the instrument, read before trusting a number

- **A page a batch did not finish is not read again** by the next `discover` run unless its text
  changed. This is the plan's recorded out-of-scope gap. `funding_yield` is unaffected because it
  writes no rows.
- **Requests a cancelled batch had already completed** (a batch that outlived `max_wait_seconds`)
  are billed but never read or metered, so the meters under-count that case. Step 7's
  reconciliation is what would show it.
- **The synchronous path cannot price an off-schema reply.** It is billed, but the SDK's `parse()`
  discards the usage, so it is counted `unmetered`. A non-zero `unmetered` count is spend that the
  dollar total leaves out.
