# Resolver hold-out (build item 8) — the gate is OWED, 2026-09-26

Plan: `docs/superpowers/plans/2026-09-25-name-to-site-resolver.md`, Tasks 10–12.

**Verdict: none.** The gate was prepared and **not run**, so there is no PASS or FAIL. Nothing
here is a measurement. `RESOLVER_WRITES_ENABLED` stays off, so `resolve_register --write`
refuses and the resolver writes nothing to the catalog.

**Why:** the environment that built the resolver had no outbound access to Wikidata or to any
vendor (the egress proxy answers `CONNECT tunnel failed, response 403`), and no Tavily,
Firecrawl, scrape.do or Diffbot keys. The build of item 7 recorded the same condition in
`docs/superpowers/2026-09-26-enumerators-gate.md`.

## What exists, and what the next run needs, in order

The order matters. The hold-out CSV records `resolver_digest`, one sha256 over the frozen
resolver **for that country** (`holdout.frozen_digest(country)`), and the gate refuses to score a
resolver whose digest differs. The components are:

- the files `names.py`, `resolver.py`, `vocabulary.py`, `domains.py` (the aggregator list),
  `hosts.py` (the registrable-domain key), `providers/tavily.py` and `providers/diffbot.py`;
- the **value** of `classify._USABLE` (its sorted repr) -- not `classify.py`, which the resolver
  reads nothing else from;
- the installed `tldextract` version, whose bundled suffix snapshot decides every registrable
  domain and moves with a re-lock, not with a file here;
- `resolver_data/kinds.json` and `resolver_data/<CC>.json` for the drawn country **only**, so
  building another country's vocabulary later does not spend Vietnam.

A missing file hashes as the marker `absent`, the same way every time. Each component's own digest
is also written to the CSV's `resolver_digest_parts` column (JSON), so a refusal names what moved;
`resolver_digest` is still the one number compared. Anything that changes a component after the
draw turns Vietnam into development data.

1. **Build the vocabulary** (free, CC0):
   `manage.py build_resolver_vocabulary --countries TR,DE,AZ,GE,KZ,UZ,VN,ID`, then commit
   `apps/research/resolver_data/`. If `test_the_committed_kinds_name_every_kind_v5_lacked`
   fails, rebuild with `--kind-depth 3` and record the depth. If depth 3 still misses a word,
   stop: that is a finding about Wikidata's tree, and hand-adding the word is the typed list
   rule 1 forbids. The nine committed-data tests skip until this lands.
2. **Probe Firecrawl's `html` for `<head><title>`** (3 credits, plan Task 4 Step 3).
   `fetch/firecrawl.py` asks for `html`, not `rawHtml`, so it is unknown whether the title
   survives. If it does not, every `SEARCH_TITLE` answer becomes `TITLE_MISMATCH`. That is the
   safe direction, but it would sink the gate's correct count. The prepend the plan describes
   changes `fetch/firecrawl.py`, which is outside the digest, but do it **before** the draw
   anyway, so the draw's resolver is the one that runs.
3. **Capture the Diffbot fixture** (25 credits, Task 5 Step 4). Read the terms first and set
   `DIFFBOT_TERMS_READ_ON` (see `docs/legal/2026-09-provider-terms.md`). Replace
   `tests/research/fixtures/diffbot_enhance_shape.json`, which is hand-built from the documented
   shape. If the live shape differs, fix `homepage()` **before** the draw: `providers/diffbot.py`
   is in the digest, so fixing it after the draw spends Vietnam.
4. **Optionally, one dry run on VGM** (~25 Tavily credits, Task 9 Step 4), as
   `DATABASE_ROLE=runtime_engine`. This is development data. Change a rule only for a code
   defect (a crash, an accepted directory, a returned aggregator).
5. **Draw once:** `manage.py draw_resolver_holdout --country VN --language vi`. Commit
   `docs/research/resolver-holdout-vn.csv` without opening its `truth` column. If fewer than 50
   are drawn, the draw prints the scaled thresholds (correct ≥ 40% rounded up, confident-wrong ≤
   4% rounded down); copy them here **before** step 6. The gate applies them itself from the row
   count (`holdout.thresholds`), so the note records them rather than setting them.
6. **Run the gate once:** `manage.py resolver_gate --country VN --diffbot`, as
   `DATABASE_ROLE=runtime_engine`, with `TAVILY_API_KEY`, `FIRECRAWL_API_KEY`,
   `SCRAPEDO_API_KEY` and `DIFFBOT_TOKEN` set (it refuses before any spend without them).
   Ceilings: Tavily ≤ 160 credits, Firecrawl ≤ 500 (worst case 8 fetches a row × 50, plus
   re-renders), scrape.do ≤ 2,500, Diffbot ≤ 50 entities (1,250 credits; these are not metered on
   `RegisterEntry`, so subtract the printed count from the month's allowance by hand). It refuses
   to run if `resolver-holdout-vn-results.csv` exists. A spent cap, a Tavily failure, a fetch
   vendor failing (Firecrawl or scrape.do down, throttled past its back-off, out of credit) or a
   Diffbot failure stops it as **INCOMPLETE** and writes no results file -- never a partial or
   outage-shaped score. Firecrawl's own 408 (its renderer timing out on a page) is scored as the
   host's failure, as the fetch ladder treats it.
7. **Record the result here and act on it**, per Task 12:
   - Write the verbatim output, FULL vs NATIVE, unresolved results by reason and by stratum, and
     every confident-wrong with its adjudication.
   - On PASS, flip `RESOLVER_WRITES_ENABLED`'s default.
   - On FAIL, leave it off, and treat Vietnam as development data from then on. The next hold-out
     is Indonesian, with a new salt committed together with the rule change and before the draw.

## Pass rule, fixed before any draw (`holdout.passes`)

- confident-wrong ≤ 2 in 50 (a short draw of n: ≤ 4% of n, rounded down);
- correct ≥ 20 in 50 (a short draw of n: ≥ 40% of n, rounded up);
- no wrong answer that is a directory or an aggregator;
- no more than 1 wrong answer from Diffbot.

## Rules changed by review before any draw

These changes were made **before any hold-out existed**, so they do not spend a hold-out. Each
one fixes a defect, not a threshold.

- Rule 1's directory test reads kind words and their inflections, never compounds. Before this,
  `bosch-stiftung.de`, `hertie-stiftung.de` and `gatesfoundation.org` scored zero as
  directories.
- `page_titles` honours the page's own charset. A windows-1254 "Vakfı" had lost its kind.
- `find_item` reads every search hit, not the first 50. It also treats an undated P576 as
  dissolved.

## Questions the gate is expected to answer, not tuned in advance

These were found in review. They are left alone on purpose, because tuning them before a
measurement is the Georgia/Kazakhstan mistake.

- **Adjacent bodies can pass the title check.** It needs one distinctive token plus a shared
  kind, so an adjacent body of the same kind passes. "Kanserle Savaş Vakfı" agrees with a page
  titled "Türk Kanser Vakfı".
- **A three-letter initials label ships unchecked.** It is tier 3 and ships without a title
  fetch, so `ksv.com.tr` would be accepted for Kanserle Savaş Vakfı.
- **Some names spend credits they cannot use.** A multi-token name with no kind word can never
  pass the title check, yet it still spends Tavily credits and fetches.
