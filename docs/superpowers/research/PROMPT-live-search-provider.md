# Deep research prompt — a search provider whose terms permit storage

**Status:** ready to run. Written 2026-08-29. Run twice, independently, so the results can be
adjudicated.

**Why this exists.** A live-search `LeadSource` was specified and then blocked — not on cost, and not
on capability, but because the provider we looked at **forbids storing results**. This product
stores what it retrieves: an evidence chain records `final_url`, timestamps, a snapshot and a
content digest, and a citation is shown to a counselor months later. A provider whose terms permit
querying but not retention is unusable for that, however good its index.

So the question is narrower than "which search API is best". It is **which providers' terms permit
the specific retention this product performs** — and, first, whether the retention we actually need
triggers the restriction at all.

---

## Prompt

You are evaluating **web search APIs** for a product that uses search to *discover URLs*, then
fetches those URLs itself and cites the fetched page.

### Question 0 — the one that may dissolve the problem

Search-API terms typically restrict caching, storing or displaying **results** — meaning the
provider's ranked list, titles and snippets. This product does not want those. It wants the **URLs**,
which it then fetches independently from the origin server, snapshots, and cites.

**For each provider examined, establish whether storing only the discovered URL — no snippet, no
title, no ranking, no result set — falls inside or outside its retention restriction.** Quote the
operative clause. Distinguish clearly between:

- clauses restricting **display** of results,
- clauses restricting **caching or storage** of results,
- clauses restricting **derived data** or database-building,
- clauses restricting **retention duration** (e.g. "no longer than 30 days"),
- and whether a bare URL is treated as "results" at all under the definitions section.

If any provider's terms clearly permit URL-only retention, that is the single most valuable finding
in this run and should lead the deliverable. This question comes first because a "no" everywhere
changes the architecture, and a "yes" anywhere makes most of the rest of this prompt moot.

### Question 1 — the provider table

Cover at least: **Brave Search API, Bing Web Search / Azure, Google Programmable Search (CSE), Google
Custom Search JSON API, Exa, Tavily, Serper, SerpAPI, You.com, Mojeek, Marginalia, Startpage,
DuckDuckGo (and whether any API is actually offered), Common Crawl** (as the non-search alternative),
and any provider you find that is explicitly retention-permissive.

| Column | Notes |
|---|---|
| Provider | |
| **Storage/retention terms** | **Verbatim quote of the operative clause**, with the URL and the date you read it |
| URL-only retention permitted? | Yes / No / Unclear — per Question 0 |
| Retention duration cap | If any is stated |
| Attribution required | And in what form |
| Index source | Own crawler, or reselling another index — say which, because a reseller inherits the upstream's terms |
| Non-English coverage | These queries run against German, Korean, Turkish, Chinese, French and Hungarian pages |
| `site:` / domain restriction | Whether queries can be confined to one host |
| Freshness / recency filter | Whether results can be limited to recently published or updated pages |
| Rate limits | Requests per second, per day, per month |
| Cost | Per 1,000 queries, and any free tier |
| Result cap per query | And whether deep pagination is offered |

### Question 2 — fitness for the actual job

The queries are **funding-shaped and site-scoped**: finding scholarship, tuition-waiver,
assistantship and fee-discount pages on a known university's own domain, and finding
government/bloc scholarship scheme pages. They are not general web queries.

For each provider, assess:
- Whether a `site:`-style restriction is supported and reliable, since most queries name the host.
- How well the index covers **university subdomains** — funded graduate schools frequently sit on a
  separate subdomain, which is exactly what a sitemap cannot see and why search is wanted.
- Whether non-English pages are retrievable with English query terms, or whether queries must be
  issued in the local language.

### Question 3 — the alternatives to a commercial search API

Assess as genuine options, not footnotes:
- **Common Crawl** — terms, coverage, index freshness, and whether the URL index (CDX) can be queried
  for a domain cheaply enough to substitute for `site:` search.
- **Self-hosted search** over pages we already fetch — what this would and would not replace.
- **Provider-published sitemaps and site search endpoints** on the target hosts themselves.
- Whether any national or academic body publishes a crawlable index of university web content.

State plainly where each fails, rather than presenting them as equivalent.

### Deliverable shape

1. **Question 0 answered first**, with quotes. Lead with it.
2. The provider table.
3. **A ranked recommendation** with the reasoning, where rank is decided by terms first and
   capability second — a better index we may not retain from is worse than a weaker one we may.
4. **What would change the recommendation** — a terms change, a new entrant, a price change.

### Sourcing rules

1. **Quote the operative clause verbatim, with its URL and the date read.** A summary of terms is
   not usable; the whole point of this run is the exact wording.
2. Terms of service change. **Date every quote**, and note the document's own "last updated" date
   where it has one.
3. Where a provider resells another index, say so and follow the terms upstream.
4. **Where terms are silent, say they are silent** — do not infer permission from silence, and do
   not infer prohibition from it either. Report the silence as the finding.
5. Do not rely on third-party comparison articles or blog roundups for any terms claim. Use them to
   find providers; read the provider's own legal pages for the facts.
6. Flag any provider whose terms forbid use for building a competing index or a persistent database,
   since that clause — not the caching clause — is often the real blocker.
