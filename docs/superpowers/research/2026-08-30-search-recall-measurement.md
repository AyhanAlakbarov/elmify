# The provider question, measured

**Run 2026-08-30** with `scripts/search_recall.py` — 16 verified targets across German, Turkish,
French, Hungarian, Korean and Chinese, against **Tavily, Brave, Exa and SerpApi**, under both an
English and a local-language query, prefix matching. 128 queries, one provider error.

Every previous statement in this programme about provider coverage was an assertion. Two deep-research
runs ranked six languages and four indexes between them without either issuing a query.

## The result

| Provider | English | Local-language | Adds over Tavily-English |
|---|---|---|---|
| **Tavily** | **16/16** | 8/16 | — |
| Brave | 14/16 | 14/16 | **+0** |
| SerpApi (Google-derived) | 14/16 | 8/16 | **+0** |
| Exa | 13/16 | 10/16 | **+0** |
| **Union of all four providers × both languages** | **16/16** | | **+0** |

**Nothing adds anything.** Eight provider/language combinations, 128 queries, and the union is exactly
what Tavily's English queries alone returned.

## What this decides

**1. One provider. Tavily. English queries.** The threshold was set before any run: under ~10%
marginal recall the ensemble is complexity for nothing. Measured marginal across three runs: **+1, +0,
+0**. A second provider is not worth a client, a key, a rate limit and a failure mode.

**2. The Google-derived index came fourth, not first.** Both runs claimed Google leads on non-English
coverage and university subdomains — run B ranked Google/SerpApi **Rank 1** partly on that basis.
Measured, SerpApi scores **14/16 against Tavily's 16/16**, and adds nothing Tavily missed. The premise
of run B's top recommendation is now contradicted by measurement as well as by the fact that Google
Custom Search is closed to new customers.

**3. Local-language querying is refuted again, and the effect is provider-specific.** Tavily drops
16 → 8 and SerpApi 14 → 8 on local queries, while Brave (14 → 14) and Exa (13 → 10) barely move. So
the honest form of run A's advice is not "issue local queries" but "some indexes handle cross-lingual
matching and some do not" — and the one we chose handles it well enough that English queries alone
reach every target. Issue English; halve the query bill.

**4. University subdomains are covered.** A direct `site:metu.edu.tr` probe returns 20 results on both
providers tested for it, led by `oidb.metu.edu.tr` and `international.ncc.metu.edu.tr` — separately
administered subdomains, which is the gap a sitemap cannot fill and the stated reason for wanting
search. The worry that shaped both runs' recommendations does not survive contact with the API.

## Threats to these numbers

1. **The fixture set is now saturated, and a ceiling cannot discriminate.** Tavily scores 16/16, so no
   provider *can* add to it on this set — the +0 columns are partly an artefact of the test being too
   easy. This is the single biggest limitation: the measurement proves nothing is missing from these
   16 targets, not that nothing is missing. Harder and more numerous targets would be needed to
   separate providers at the top, and that is the work to do if anyone wants finer discrimination.
2. **Run-to-run variance is ±2 fixtures.** Tavily-English read 14/16, 15/16 and 16/16 across three
   runs an hour apart with no relevant change. Read "16/16" as "at ceiling, within noise", not as
   perfect. The *conclusion* is robust — the marginal was ≤1 in all three — but the headline number is
   not stable.
3. **n=16.** Per-language cells hold 2–3 fixtures and are noise; they are not reported.
4. **The local-language queries are mine.** I composed them; a native speaker would phrase them
   differently. Note this cuts against conclusion 3 less than it appears — local queries found a
   strict subset of the English results for every provider.
5. **One fixture was replaced after seeing results** (`tr-metu-root` → `tr-metu-fees-subdomain`), and
   **a harness bug was fixed mid-measurement** that had made root-URL targets unmatchable under prefix
   search. Both are recorded in the fixture file and the git history because either could flatter a
   result.
6. **One SerpApi query failed** (HTTP 500, `zh-tsinghua-is-subdomain`, local mode), so its
   local-language score rests on 31 of 32 queries.

## Cost

This run consumed roughly 32 of SerpApi's 100 free monthly searches, which are shared with `gptr-mcp`.
Neither SerpApi nor Exa nor Brave is a candidate — SerpApi's terms hand use-side liability back to us,
Exa's bar retention, Brave's bar storage without a paid tier. They were tested to find out whether
Tavily was leaving recall on the table. It is not.

## What did not need a research run

The provider decision consumed two deep-research runs, a pre-run control, an adjudication and this
harness. The runs settled the **terms** question, which only reading could settle, and that is what
chose Tavily. They could not settle the **capability** question, and both attempted it anyway —
ranking four indexes and six languages by assertion. 128 queries answered it in about six minutes and
contradicted them on every count that mattered.
