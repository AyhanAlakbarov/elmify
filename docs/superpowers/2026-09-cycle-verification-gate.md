# Cycle-verification gate (spec §9.3), result

**Verdict: NOT RUN**

Plan: `docs/superpowers/plans/2026-09-26-verification-ladder.md`, Task 13. Spec:
`docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md` §9.3 and the §15
readiness row "cycle verification ≥ 95% precision on `OPEN`/`UPCOMING`".

The instrument is built and tested: `manage.py cycle_verify` (pure `score`, `GateRow`,
`GateReport`, `--truth`, `--dry-run`, `--out`) in
`apps/research/management/commands/cycle_verify.py`, sharing
`cycle_verification.build_seams` with the scheduled worker so the gate measures what the
schedule runs. **No number in this note is a measurement.** Nothing here is PASS or FAIL,
and nothing here licenses Task 14.

## Why it did not run (2026-09-26)

1. **No vendor or model keys in the build environment.** Firecrawl, scrape.do, Exa, Brave,
   OpenAI and Anthropic keys were absent, and the egress proxy blocks `openai.com` and
   `query.wikidata.org`. Every ladder step past a stored read needs at least one of them.
2. **The truth set is unlabelled.** `docs/research/2026-09-cycle-truth-set.csv` is committed
   with its header row and zero data rows. Plan Task 12 requires a person to label it, blind,
   from the organisations' own sites and Wayback, before any command in the plan runs against
   them. No agent may fill it, and none did. `cycle_verify` refuses a real run on a file with
   no data rows and says the truth set is unlabelled.
3. **The Wikidata country labels were not generated.** `docs/research/country-labels.csv`
   ships header-only because `query.wikidata.org` was unreachable. So every country phrase in
   a `deadline_for` normalises to `OTHER:<text>`, and no `NATIONALITY:`/`RESIDENCE:`
   conditional deadline can match a student. Run as it stands, the gate's conditional-deadline
   rows would measure the missing file, not the ladder.
4. **`gpt-5.6-luna` is unpriced.** `MODEL_PRICES_USD_PER_MTOK` has no row for
   `OPENAI_EXTRACTION_MODEL` (its pricing page was unreachable). Every OpenAI reading counts as
   `unpriced`, so `cost_complete` is False and every cost below would be a floor.

## Commands owed, in order

1. **Country labels.** Run from a network that reaches Wikidata, then commit the CSV:

   ```bash
   uv run python manage.py refresh_country_labels
   ```

2. **Label the truth set by hand**, blind, in `docs/research/2026-09-cycle-truth-set.csv`, to
   Task 12's coverage: ≥ 40 distinct `organisation_domain`s with ≥ 3 in each of AZ, TR, DE, NL,
   SE, FR, HU, IT; ≥ 1 row per state; the three known-answer rows (ChEMoinformatics+
   `SUSPENDED` for 2026 from its 15/10/2025 statement, a March–May scheme `UPCOMING` in
   September with two past calls, a first-year scheme `UNVERIFIED`); ≥ 8 `UPCOMING` rows over
   ≥ 4 countries and ≥ 3 families, each with both `*_call_opened` dates; ≥ 10
   conditional-deadline rows, each labelled for two profiles. `labelled_by` is a person's
   name. Commit with the counts in the message.
3. **Add the `gpt-5.6-luna` price row** to `MODEL_PRICES_USD_PER_MTOK` from OpenAI's published
   price, and update `MODEL_PRICES_VERIFIED_ON`. Without it the run still works but every cost
   is a floor.
4. **Estimate, spending nothing:**

   ```bash
   uv run python manage.py cycle_verify --truth docs/research/2026-09-cycle-truth-set.csv --dry-run
   ```

5. **The owner's Firecrawl-quota decision.** Stop and ask if the estimate is more than what
   remains of the month's Firecrawl quota. On the free tier (1,000 credits a month) one crawl's
   worst case is 15 × (1 + 60) = 915 credits. The options are the paid plan, two months of free
   quota, or a temporary `FETCH_PDF_MAX_PAGES` override for this run. If an override is taken,
   record it here.
6. **The live run**, with `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `FIRECRAWL_API_KEY`,
   `SCRAPEDO_API_KEY`, `EXA_API_KEY` and `BRAVE_API_KEY` set:

   ```bash
   DATABASE_ROLE=runtime_engine uv run python manage.py cycle_verify \
     --truth docs/research/2026-09-cycle-truth-set.csv \
     --out docs/superpowers/2026-09-cycle-verification-gate.md
   ```

   The role is `runtime_engine`, not `migration` as the plan wrote. The gate writes no catalog
   row, but every `fetch_page` call writes a `FetchAttempt`/`HostProfile` row, and at runtime
   only `runtime_engine` may write those (`runtime_engine_write`, `CATALOG_ROLE_NOTE`).
   `migration` would also succeed, and that is the reason not to use it. It owns the shared
   catalogue tables, and those are `ENABLE` without `FORCE ROW LEVEL SECURITY`
   (`research/0005_fetch_engine_rls.py`), so as owner it bypasses every policy. A run as
   `migration` never exercises the policies the scheduled worker runs under. `runtime_engine`
   is the role `WorkerTaskDefinition` uses, so the gate measures the production path. The
   migration credential is kept for schema changes.

7. Replace the verdict line with PASS or FAIL, and fill in every "owed" item below. Commit as
   `docs: cycle-verification gate result, <PASS|FAIL>`.

**If the gate fails, the design changes, not the threshold** (§8.8's rule, repeated for this
gate). Task 14 does not run. Open a follow-up with the disagreements `cycle_verify` prints.

## What the recorded result must include (plan Task 13 Step 7)

| item | status |
|---|---|
| the full report (`cycle_verify --out` appends it below) | owed |
| the run date and the vendor plans in force (Firecrawl, scrape.do, Exa, Brave) | owed |
| `MODEL_PRICES_VERIFIED_ON` at run time (2026-09-26 when this note was written, with `gpt-5.6-luna` unpriced) | owed |
| cost per verified scholarship against §9.3's $0.15–0.40, and whether it is a floor (`cost_complete`) | owed |
| the share of rows settled at step 0 | owed |
| `cycles_without_opening` (plan decision 3) | owed |
| the count of `hop_withheld` links, and how many truth rows had no evidence except behind one (plan decision 1) | owed; `cycle_verify` reports both (`hop_withheld links`, `truth rows with no evidence but a withheld hop`: no joined evidence and at least one `hop_withheld` trail entry) |
| per-country recall of `OPEN`+`UPCOMING` (plan decisions 9–10) | owed |
| conditional-deadline accuracy per condition kind (the decision-side finding on `APPLICANT_CLASS`) | owed |
| the `FETCH_PDF_MAX_PAGES` override, if one was taken | owed |

## Task 14

Task 14 (retiring the interim rule) did not run: it is conditional on a recorded PASS.
`evaluate_award` still hides only what is known shut, and `UNVERIFIED` still passes
(`tests/funding/test_award_gates.py::test_an_unverified_award_is_still_eligible_and_that_is_deliberate`).
