# Enumerators (build item 7) — gate run, 2026-09-26

Plan: `docs/superpowers/plans/2026-09-25-enumerators.md`, Task 13.

**Verdict: FAIL.** `closed_list_coverage --gate` exits **1**. 10 of the 11 in-scope lists fail,
and only `az_banks` passes. This is the result the gate was built to give for the state these
lists are in. It is not a code defect.

**Why, in one line:** the environment that built this had **no outbound access** to any origin,
to Wikidata, to ROR or to EACEA (egress proxy: `CONNECT tunnel failed, response 403`), and **no
API keys**. So nothing could be read, classified or enumerated live, and every list was compiled
from search-engine results instead of from the publisher's page.

## The run, verbatim

Run against the local database `tehsil_enum` after `migrate` and `load_closed_lists` (a second
`load_closed_lists` reported `new 0` on every list, so the load is idempotent):

```
$ manage.py closed_list_coverage --gate --list igo_regional_global --list eacea_emjm \
    --list tr_outbound_gov --list tr_bilateral --list tr_heis --list tr_banks \
    --list tr_professional_bodies --list az_outbound_gov --list az_bilateral --list az_heis \
    --list az_banks
igo_regional_global  listed 22/?  known 19  REJECTED=3 UNREAD=19  FAIL
eacea_emjm  listed 0/?  known 0    FAIL
tr_outbound_gov  listed 1/?  known 1  UNREAD=1  FAIL
tr_bilateral  listed 8/?  known 8  UNREAD=8  FAIL
tr_heis  listed 74/208  known 4  UNBOUND=70 UNREAD=4  FAIL
tr_banks  listed 64/?  known 0  UNBOUND=64  FAIL
tr_professional_bodies  listed 24/24  known 15  GATED=15 UNBOUND=9  FAIL
az_outbound_gov  listed 1/?  known 1  UNREAD=1  FAIL
az_bilateral  listed 8/?  known 8  UNREAD=8  FAIL
az_heis  listed 36/?  known 35  UNBOUND=1 UNREAD=35  FAIL
az_banks  listed 21/?  known 21  GATED=21  PASS
CommandError: gate failed: igo_regional_global, eacea_emjm, tr_outbound_gov, tr_bilateral, tr_heis, tr_banks, tr_professional_bodies, az_outbound_gov, az_bilateral, az_heis
EXIT=1
```

`az_professional_bodies` is not run because the survey records it at rung 4, so no list file
exists. `vgm_tr` is out of this run's scope: it is loaded by item 6a's adapter, not by a list file.

Across all 259 register entries: **UNBOUND 144, UNREAD 76, GATED 36, REJECTED 3**. There are no
`COULD_NOT_LOOK` or `CONFLICT` rows, because nothing was fetched and nothing was enumerated.
Item 12's queue therefore has no input from this run.

## Per list

**Cost of this run: 0 Firecrawl credits, $0 in model calls.** Nothing was fetched and no model
was called. Every figure in the table comes from the register.

| list | rung | policy | printed | entries | bodies known | states | what fails it |
|---|---|---|---|---|---|---|---|
| igo_regional_global | 1 | FUNDING_READ | — | 22 | 19 | REJECTED 3, UNREAD 19 | nothing read (no keys) |
| eacea_emjm | 1 | ENUMERATE_ONLY | — | 0 | 0 | — | `enumerate_eacea` not run (no egress) |
| tr_outbound_gov | 3 | FUNDING_READ | — | 1 | 1 | UNREAD 1 | nothing read |
| tr_bilateral | 3 | FUNDING_READ | — | 8 | 8 | UNREAD 8 | nothing read |
| tr_heis | 2 | CLASSIFY | 208 | 74 | 4 | UNBOUND 70, UNREAD 4 | 74 of 208 listed; 70 without an established site; not classified |
| tr_banks | 2 | SIGNAL_ONLY | — | 64 | 0 | UNBOUND 64 | no bank's own site established |
| tr_professional_bodies | 3 | SIGNAL_ONLY | 24 | 24 | 15 | GATED 15, UNBOUND 9 | 9 chambers without an established site |
| az_outbound_gov | 3 | FUNDING_READ | — | 1 | 1 | UNREAD 1 | nothing read |
| az_bilateral | 3 | FUNDING_READ | — | 8 | 8 | UNREAD 8 | nothing read |
| az_heis | 2 | CLASSIFY | — | 36 | 35 | UNBOUND 1, UNREAD 35 | not classified; about 50 expected, 36 found |
| az_banks | 2 | SIGNAL_ONLY | — | 21 | 21 | GATED 21 | **passes**. GATED is the owner's rule, and no pointer-tag writer exists |

`tr_bilateral` created only 3 new bodies for its 8 rows, because five host agencies are the same
bodies `az_bilateral` names. A register keyed on the domain is meant to behave that way.

The three `REJECTED` rows on the intergovernmental list are all `NOT_A_FUNDER`:
`norden-nordic-master` and `eeagrants-scholarships` fund institutions only, and
`gmf-black-sea-trust` grants to NGOs. Each is a recorded row, not a dropped one.

## How the lists were compiled — read this before trusting any row

Direct fetches of every publisher and body page were blocked. The only evidence available was
**search-engine results, restricted where possible to the publisher's or body's own domain**.
That departs from the plan's method, which is to read each list from the publisher's page by
hand, and every row's `notes` says so ("search-indexed text only, origin not fetched (egress
blocked 2026-09-26)"). `verified_on` is the day the search evidence was read, not a day the page
was opened. Consequences:

- **No domain was guessed from a name.** A body whose own site did not appear in results has a
  blank `website` and reads `UNBOUND`, which is 144 rows. This is the correct failure.
- **`tr_heis` is incomplete:** 74 of YÖK's 208. The search budget ran out partway through the
  list.
- **`tr_banks`:** 64 names from TBB/TKBB report summaries, not from the BDDK page. The BDDK snippet
  says 54, so the 64 probably mixes categories. `printed_size` is left blank because the count
  could not be dated or reconciled.
- **`az_heis`:** 36 of an estimated ~50. The ministry's list pages are not indexed; the rows rest
  on an old PDF version and on edu.gov.az pages naming each body.
- **Bilateral lists:** only schemes whose page could be established on the host agency's own
  domain are listed. The rest are named in the compilers' logs, not in the files. For both Russia
  rows, `page_url` is a portal root rather than a scheme page.
- **Intergovernmental list, weak rows:** IDB's award page could not be confirmed as current; the
  OPEC Fund scholarship is being restructured; Commonwealth `home_cells` are wide
  (`COMMONWEALTH|MS|SH`); UNESCO/Great Wall home is `ANY` because the annex was not visible; the
  Organization of Turkic States page says "graduate", not "master's".

## ROR gate (Task 10) and ROR enumeration (Task 11)

**Not run.** `manage.py ror_gate` → `CommandError: ROR unreachable: api returned HTTP 403` (the
egress proxy). So there are no known share, no website-agreement share, no exact-name share and
no `name_website_match` for item 8. **Task 11 was not built**, because the plan gates it on a
live PASS.

`docs/research/ror-gate-names.csv` holds 63 (name, domain) pairs from the curated files that have
a website. No `vgm_tr` rows are included, because no database carried them. A review found that
`docs/research/2026-09-18-yield-hosts.txt` lists `chinesescholarshipcouncil.com` twice, so it has
57 distinct hosts, not 58.

## EACEA (Task 9)

**Not run live.** There are no totals per action code, no disposition histogram and no conflict
share. `printed_size` is unset, so `eacea_emjm` reads `listed 0/?` and fails.

The adapter's **project-level keys** (`projectIdentifier`, `title`, `startDate`, `endDate`) are
**unverified placeholders**. Its fixture is hand-built from the organisation keys the 09-14
design records. A wrong key yields zero projects, and the adapter now also asserts that the
number of distinct projects paged equals the API's total. Either failure is loud. Capture one live
page before the first real run.

## Wikidata (Task 7)

**Not run live.** The row bounds are the plan's first guesses, not half and double of a measured
count. The extra class rows (foundation, government agency, ministry, bank) were not added,
because each needs a live dry run to bound it. The fixture is hand-built and its QIDs are
illustrative.

## Set differences (spec §15 gold sets)

**Not computable.** Wikidata-TR/AZ and ROR hold no rows in the register, so
Wikidata-minus-`tr_heis`, `tr_heis`-minus-Wikidata, the AZ pair and ROR-minus-curated are all
undefined, not zero.

## Limits, as the plan asks

- **No succession walk.** An EMJM partner that has merged binds to whichever body holds its old
  PIC or domain.
- **No pointer-tag writer.** Every `SIGNAL_ONLY` body is `GATED`, which is the owner's rule and
  passes.
- **The thirteen-country survey (Task 6 Step 6) is not done.** `register-survey.csv` has the 20
  TR/AZ rows plus the three seed rows for DE, KZ and IT, and the test enforces TR and AZ only.
  Every rung 1–3 row records `reuse_terms=UNREAD`, because no terms page could be opened.

## What turns this green

1. From a network that reaches the origins: re-read each list from its `list_url`, finish
   `tr_heis` (134 missing) and `az_heis`, and establish sites for the 144 `UNBOUND` rows. Where a
   site cannot be established, the rows stay for item 8's resolver.
2. With `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` set: `read_closed_list` on the four FUNDING_READ
   lists and the intergovernmental list, and `classify_organisations --found-via
   R2_LIST:tr_heis` / `R2_LIST:az_heis`.
3. Capture EACEA and fix its project keys, then run `enumerate_eacea`. Run `ror_gate`, and Task
   11 only if it passes. Run `enumerate_wikidata --dry-run`, then tighten the bounds.
4. Re-run the command at the top of this file.
