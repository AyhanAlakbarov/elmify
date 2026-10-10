# Pre-run reconnaissance — a search provider whose terms permit storage

**Date:** 2026-08-30. **Status: NOT a research run, and not an input to one.**

A control, like `2026-08-29-outbound-launch-prerun-recon.md` and
`2026-08-29-dual-degree-prerun-recon.md`. `PROMPT-live-search-provider.md` asks, first, whether
storing only a discovered URL falls inside each provider's retention restriction. **Do not hand this
file to either run** — it exists so the adjudication can see what each run reaches without it.

Every claim here was fetched from the provider's own legal page and is quoted, with the URL and the
date read. Where a provider's terms are silent, that is recorded as silence.

**Prior state.** `2026-08-28-search-provider-storage-terms.md` left Exa and Brave at HOLD, Perplexity
unverified behind a 403, and Serper and Google CSE unverified. This control closes three of those and
finds one provider the earlier probe never reached.

---

## 1. Question 0 is already answered for Brave, and the answer is no

The 2026-08-28 probe quoted Brave's storage clause but never quoted the **definitions** section — which
is where Question 0 is actually decided.

`api-dashboard.search.brave.com/documentation/resources/terms-of-service`, HTTP 200, fetched
2026-08-30. The document's own header: **"Last Updated: 11 February 2026"**.

> **"Search Results" means any outputs from calls made to the API**, which may consist of (i) internet
> search results; (ii) Generated Results; or (iii) Third-Party Content.

And the restriction it feeds:

> Customer shall not and shall not permit End Users or others to: (i) **store, cache, or create a
> database of Search Results, in whole or in part**, other than transient storage required for
> operation of Customer Applications or related software, service or systems

**A bare URL is an output from a call to the API.** The definition is output-scoped, not
snippet-scoped, and "in whole or in part" closes the remaining gap: a URL is part of a Search Result
even on the narrowest reading. The hope behind Question 0 — that "results" means the ranked list,
titles and snippets, and that a URL sits outside it — **does not survive Brave's own definitions
section.**

This does not settle Question 0 generally. It settles it for the provider the earlier probe made the
front-runner, and it settles it against.

## 2. Perplexity is reachable, and it carries the sharpest trap in this run

The 2026-08-28 probe got HTTP 403 twice, including with a browser user-agent, and recorded Perplexity
as unverified with a note that bot protection on a legal page is not a verdict. **A real browser
reaches it.** Both documents below were fetched 2026-08-30 via a headless browser; plain `curl` still
returns 403.

**The headline document looks permissive.** `perplexity.ai/hub/legal/perplexity-api-terms-of-service`,
last updated **23 January 2026**, §2.3.1:

> As between Perplexity and Customer, and to the extent permitted by applicable law, Customer (i)
> retains all ownership rights in Input and (ii) **owns all Output**. Perplexity asserts no ownership
> rights in any Output and, to the extent it obtains any such rights by operation of law or otherwise,
> hereby assigns such rights to Customer.

There is no storage, caching or database clause anywhere in that agreement.

**A second document overrides it for the endpoint we would actually use.**
`perplexity.ai/hub/legal/perplexity-api-terms-of-service-search`, last updated **22 September 2025**,
is a Search Addendum that "overrides the agreement… solely with respect to the particular Perplexity
Search services", and §1.2.2 states that on conflict "this Addendum shall take priority". Its
Schedule 1, for the `/search` endpoint:

> **Customer does not own, and Perplexity shall not grant it ownership of, the Search API's Output.**

And §2.2:

> Perplexity may **retain, copy, distribute and otherwise use Search Data** for its lawful business
> purposes, including the improvement and development of products and services. Search Data is **not
> Customer's Confidential Information**…

where §1.1.1 defines Search Data as Input *and* Output.

**Two things follow, and they point in opposite directions.** The ownership grant that makes the
general ToS look like a clear "yes" is withdrawn precisely for search. But **non-ownership is not a
prohibition on retention** — neither document forbids the Customer from storing Output. Perplexity is
therefore *silent* on our question, after appearing to answer it in the affirmative.

Also noted, because it bears on a product handling student data: §2.3 — "Customer shall not submit
Personal Data… to the Search Services unless explicitly authorized by Perplexity in writing."

## 3. Mojeek is the only affirmative storage right found — and its contract was not

`mojeek.com/services/search/web-search-api/`, HTTP 200, fetched 2026-08-30. In the FAQ:

> **Can I store data obtained through the API?**
> You can **store results on Business plan** and optionally on the Enterprise plan. For other plans,
> you may store the results for 1 hour to enable caching.

"Storage Rights" is also a listed row in the plan comparison table across Startup (£2 CPM), Business
(£3 CPM) and Enterprise (custom). Rate limits are 5/sec and 100k/day on Startup, 10/sec and 400k/day
on Business. The page describes "Mojeek's full index of billions of web pages" — **an independent
crawler, not a resold index**, which matters because a reseller inherits its upstream's terms. It
advertises "multiple site search inclusion/exclusion", which is the `site:` capability Question 2 asks
about.

**But the binding instrument was not found.** `mojeek.com/about/terms.html` (HTTP 200, fetched
2026-08-30) is website terms; it contains no clause about API output at all — its only relevant
language is a conduct restriction about saturating attacks and unlawful access. There is no separately
published API contract on the site; the plan rows all end in "Contact".

**This is the Brave trap in reverse, and the 2026-08-28 probe already paid for the lesson once.** There,
a marketing FAQ promised storage and the binding ToS forbade it. Here a marketing FAQ grants storage
and no binding ToS was located. The correct verdict is therefore **the most promising lead in this
run, and not yet a cleared provider** — the same standard that demoted Brave.

## 4. Google's blocker is the database clause, not the caching clause

`developers.google.com/terms`, HTTP 200, fetched 2026-08-30, "Last modified: November 9, 2021".
Section e, "Prohibitions on Content":

> Unless expressly permitted by the content owner or by applicable law, you will not… do the following
> with content returned from the APIs: **Scrape, build databases, or otherwise create permanent copies
> of such content**, or keep cached copies longer than permitted by the cache header;

The prompt's own sourcing rule 6 anticipates this: the database clause, not the caching clause, is the
real blocker. Note the clause is conjunctive in effect — "create permanent copies" is prohibited
independently of the cache-header limb, so a short cache TTL does not rescue it.

## 5. SerpApi is silent on retention, and indemnifies the half we did not ask about

`serpapi.com/legal` (the `/legal/terms-of-service` path guessed by the earlier probe is HTTP 404),
fetched 2026-08-30, "Last updated: April 8, 2026". **No clause restricting storage, caching, retention
or database-building of API output was found.** Silence, not permission.

What the terms do say is more interesting:

> For all recurring plans except the Free, Starter, and Developer plans, SerpApi will assume the
> liabilities of **scraping and parsing search engine results** for both U.S. and international
> companies and individuals, with up to $2 million in coverage ("U.S. Legal Shield")… SerpApi assumes
> liability for the **lawful collection** of public search data (scraping, parsing, and related
> actions), **but not for how that data is ultimately used.**

SerpApi resells SERPs it obtains by scraping, so per sourcing rule 3 the upstream terms govern — and
§4 above is that upstream. SerpApi's answer to the upstream problem is **an indemnity for acquisition,
explicitly excluding use.** Retention is use. The shield does not cover the question this run is
asking.

## 6. Tavily restricts the Services, not the Output — and takes a licence over ours

`tavily.com/terms`, HTTP 200, fetched 2026-08-30, "Last updated: May 4, 2026". §3.2 General Use
Restrictions runs to twelve limbs, every one of which binds what may be done to **the Services** —
copy, sublicense, reverse engineer, frame or mirror, build a competitive product, data-mine *through*
the Services. **None restricts retention of Output.** Silence again, and a somewhat louder silence
than SerpApi's, since the clause that would carry such a restriction exists and does not carry it.

The countervailing clause runs the other way:

> You hereby grant Tavily and its affiliates a worldwide, royalty-free, fully paid, transferable,
> assignable, sublicensable (through multiple tiers), perpetual, and irrevocable license to collect,
> host, use, access, view, store, copy, display, create deriva[tive]…

together with a clause permitting Tavily and its AI subprocessors to "use, process, analyze, and retain
Customer Input… and Outputs… for purposes of training, improving, developing". Our queries are
institution and scheme names, so the exposure is low — but this is a different risk class from the
retention question, and it is the one Tavily's terms actually address.

## 7. One of the prompt's named providers no longer exists

**Bing Search APIs were retired on 11 August 2025.** `learn.microsoft.com/.../bing/search-apis/
bing-web-search/overview` now 301s to a `/previous-versions/` path (observed 2026-08-30), and
Microsoft's lifecycle announcement states the APIs were decommissioned with no new customer signup,
directing customers to Grounding with Bing Search inside Azure AI Agents.

Separately, and independent of the retirement, the archived overview carried a use restriction that
would have excluded this product anyway:

> Bing Web Search API **may only be used as a result of a direct user query or search**, or as a result
> of an action within an app or experience that logically can be interpreted as a user's search
> request.

A scheduled discovery crawl is not a user query. Bing was never a candidate on its terms, and is now
not a candidate at all.

## 8. Common Crawl carries no retention restriction

`commoncrawl.org/terms-of-use`, HTTP 200, fetched 2026-08-30, "LAST UPDATED: March 7, 2024". §2's
prohibited-use list, limbs (a) through (m), is entirely conduct-based — attacks, harassment,
impersonation, header forgery, unlawful purposes — and contains **no storage, caching, database or
retention clause**. The one limb touching data handling is (l): "collecting or harvesting any
personally identifiable information or personal information for use separately from the Crawled
Content", which our use does not engage.

§2 does warn that Crawled Content "may be subject to separate terms of use or terms of service from
the owners of such Crawled Content" — i.e. Common Crawl licenses its own service, not the pages in it.
For a system that only wants **URLs** and then fetches the page itself from the origin, that caveat is
mostly inert.

---

## 9. The checks this control scores

Each run is scored against these. A run that reaches one unaided beats this control on that point; a
run that contradicts one is either better-sourced or wrong, and the adjudication must say which.

1. **Does the run quote Brave's *definition* of "Search Results", not just its storage clause?**
   Question 0 is decided in the definitions section, and the previous probe missed it. A run that
   answers Question 0 for Brave without quoting "any outputs from calls made to the API" has not
   actually answered it.
2. **Does the run find the Perplexity Search Addendum, or stop at the general API ToS?** Stopping at
   §2.3.1 yields "Customer owns all Output" — a clean, quotable, *wrong* answer for the `/search`
   endpoint. This is the single most likely error in the run.
3. **Does the run reach Perplexity at all?** It 403s to ordinary fetching. A run that reports
   Perplexity as unreachable has been beaten by a browser.
4. **Does the run distinguish silence from permission** for SerpApi and Tavily, per sourcing rule 4 —
   or does it read an absent prohibition as a grant?
5. **Does the run find Mojeek's storage right, and does it then ask what document grants it?** Finding
   the FAQ is the easy half. Noticing that no API contract is published, after the Brave FAQ-versus-ToS
   correction, is the half that matters.
6. **Does the run know Bing Search APIs are retired?** Naming Bing as a live option with pricing is a
   dated-training-data failure, and the prompt lists Bing explicitly, so both runs are invited to make
   it.
7. **Does the run flag Google's "build databases" limb rather than only the cache-header limb?** The
   prompt asks for this by name in sourcing rule 6.
8. **Does the run follow SerpApi upstream to Google's terms**, and does it notice the Legal Shield
   covers collection but excludes use?
9. **Does the run date every quote and note each document's own "last updated" date?** Four of the
   documents here carry dates spanning 2021 to 2026; Google's is nearly five years old, which is itself
   a fact about how much weight it bears.
10. **Does either run reach a provider not in this control?** The prompt names You.com, Startpage,
    Marginalia, Serper and DuckDuckGo, none of which this control resolved. Genuinely new coverage —
    especially any provider with an *affirmative* storage grant to sit beside Mojeek's — is the
    clearest way a run earns its keep here.
11. **Does the run answer Question 2's subdomain question with evidence?** Whether an index covers
    university *subdomains* is testable by query, not by reading terms, and no run so far in this
    programme has tested a provider rather than described one.

## 10. What this control does not establish

- **Nothing about capability.** Every finding above is a terms finding. Index coverage, subdomain
  reach, non-English retrieval and `site:` reliability are untested here, and Question 2 is wide open.
- **Nothing about Serper, You.com, Startpage, Marginalia, Exa's current wording, or DuckDuckGo.**
  Exa's HOLD is carried from 2026-08-28 and was not re-read today.
- **No provider was contacted.** The 2026-08-28 recommendation to ask Brave whether URL-only retention
  needs a storage plan is still unexecuted — and §1 above materially lowers the expected value of
  asking, since Brave's own definitions bring a URL inside "Search Results" before the transient-storage
  carve-out is reached.
- **Whether we need a search provider at all** is out of scope here and belongs to
  `PROMPT-new-opportunity-surfaces.md`, which asks how anything reaches us that no index contains.
