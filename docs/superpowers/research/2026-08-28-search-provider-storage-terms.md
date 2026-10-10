# Search providers: may we store what they return?

Probed 2026-08-28, after the access-terms review found Exa's ToS §4.2(a) forbids
reproducing "any information obtained from or through the Services" outside
temporary browser caching. Same method as
`2026-08-27-seed-source-access-terms.md`: a verdict with no quoted clause is not
a finding.

| Provider | Terms reached | Quoted clause | Verdict |
|---|---|---|---|
| Brave Search API — **binding ToS** | `api-dashboard.search.brave.com/documentation/resources/terms-of-service`, HTTP 200, fetched 2026-08-28 | "Customer shall not and shall not permit End Users or others to: (i) store, cache, or create a database of Search Results, in whole or in part, **other than transient storage required for operation of Customer Applications** or related software, service or systems"; also "(xii) redistribute, resell, or sublicense the Search Results"; and on termination, may not "retain ... Search Results in Customer's possession and control". | **HOLD by default** |
| Brave Search API — paid add-on | `brave.com/search/api/` FAQ, HTTP 200 | "If you would like to store the API results in part or whole ... you will need to subscribe to a plan that explicitly grants storage rights." and "Plans with storage rights grant special permissions which are not covered in our general Terms of Service." | **SHIP only on a storage-rights plan** |
| Serper | `serper.dev/terms`, HTTP 200 | "Serper provides web-scraped data collected from public domain sources." Its licence restriction covers "materials and software contained on the serper.dev website" — no clause addressing retention of API output was found. | **UNDER-EVIDENCED** — absence of a prohibition is not a grant |
| Perplexity | `perplexity.ai/hub/legal/perplexity-api-terms-of-service` → HTTP 403; `docs.perplexity.ai/guides/search-api` → HTTP 404 | none reachable | **UNVERIFIED** |
| Google CSE | `developers.google.com/custom-search/v1/site_restricted_api` → HTTP 200 but is documentation, not terms | no storage language on the page | **UNVERIFIED** |
| Exa | (carried over) ToS §4.2(a) | "You may not... download, modify, copy, ... reproduce, duplicate ... any information contained on, or obtained from or through, the Services, except for temporary files that are automatically cached by your web browser" | **HOLD** |

## What the probe actually established

**Correction, made after the first version of this document.** That version
quoted Brave's marketing FAQ and recorded Brave as SHIP. That was wrong on the
evidence: the FAQ is not the contract, and the binding ToS — linked from the
same page and not fetched on the first pass — prohibits storing or caching
Search Results in language close to Exa's own. The verdict is now HOLD by
default, SHIP only on a storage-rights plan.

What survives the correction is narrower but still real: **Brave publishes a
route to buy the right, and Exa does not.** Both default to prohibition. One
sells the exemption openly and says so; the other's terms mention no such path.
That is a genuine difference, and it is a smaller one than the first version of
this document implied.

The other thing that survives is the **transient-storage carve-out**, which is
the most consequential clause found in this probe: Brave permits "transient
storage required for operation of Customer Applications". Whether holding a URL
long enough to fetch the page behind it is "transient" — and whether persisting
that URL as a citation in `OfficialSource.canonical_url` crosses the line — is
the question that decides whether the base plan suffices. It is a question for
Brave, not one to answer ourselves.

## The question that decides the cost

**The engine may not need storage rights at all.**

What it persists from a search provider is a *URL* — nothing else. That URL flows
into `ResearchLead.canonical_url` and then `OfficialSource.canonical_url`. The
content that is stored as evidence — the snapshot in S3, every
`OfficialEvidenceClaim` — is fetched **by us, directly from the institution's own
server**, and never comes from the provider.

So the engine is not building a competing index and is not retaining provider
output in any substantive sense. It uses search the way a person uses it: to
find out where to look, then goes and looks.

Whether a bare URL counts as "API results" under a storage-rights clause is the
open question, and it is worth asking each provider directly rather than
assuming the expensive answer. Note Exa's clause is broad enough to cover a URL
on a literal reading, which is why it stays HOLD until someone asks them.

## Recommendation

1. **No provider is cleared yet. Do not sign up for one on this probe.**
2. **Ask Brave the transient-storage question** — does retaining only the URL,
   with all page content fetched independently from the origin, require a
   storage-rights plan? That single answer decides both the provider and the
   cost, and it is cheap to ask.
3. **Perplexity is still unverified and should not have been dropped.** It was
   the design's own named fallback; its terms page returned 403 on two attempts,
   including with a browser user-agent. Bot protection on a legal page is not a
   verdict. Reach it another way before ruling on it.
4. **Do not choose Serper on the strength of this probe.** No prohibition found,
   but no permission granted either, and "web-scraped data collected from public
   domain sources" raises a separate question about the sources behind it.
5. Google CSE stays unverified.

**On how Brave came to be the front-runner, recorded so the next reader
discounts it appropriately:** it was the only provider whose relevant page could
be fetched. That is selection by reachability, not by merit. Exa is the only
provider whose binding terms have been read end to end, and Brave the second —
both prohibit storage by default. The others remain unknown, and unknown is not
worse than HOLD.

## Why this matters more than it looks

Four seed catalogues have now failed for four unrelated reasons — DAAD on
access terms, EACEA on client-side rendering, Study in Korea on a session-gated
listing, Campus France classed tier-3 at design time. The catalogue path is also
the most fragile by construction: two fetches plus an anchor-matching heuristic
verified against a single site, which broke on the first different one.

Search returns institution URLs directly: one fetch, no hop, no heuristic, no
per-catalogue permission question, no browser. The `PROGRAM` lead path that
consumes it is already built and tested. If search is licensed, the discovery
engine works; if it is not, every remaining route needs either a negotiation or
a rendering subsystem.
