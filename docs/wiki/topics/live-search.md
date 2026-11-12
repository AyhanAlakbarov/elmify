# Live search provider

Which search provider's terms permit keeping result URLs, from two runs adjudicated against a pre-run recon. [src: 2026-08-30-live-search-synthesis.md] Related: [worldwide funding sources](worldwide-funding-sources.md).

- Tavily's terms permit retaining a URL by structure: "Services" is defined to exclude "Output", and all seventeen restriction limbs of §3.2 attach to Services. [src: 2026-08-30-live-search-synthesis.md §1]
- Limits: Tavily may query third-party indexes (an undisclosed upstream), and §3.2(xvi) bars automated high-risk decisions without human oversight; education is not enumerated. [src: 2026-08-30-live-search-synthesis.md §1]
- Mojeek is a strong lead, not a cleared provider: its storage grant is a marketing FAQ and no API contract is published; both runs rate it weakest on non-English coverage. [src: 2026-08-30-live-search-synthesis.md §2]
- Google is out twice: its terms prohibit building databases from content, and the Custom Search JSON API is closed to new customers and ends on 1 January 2027. [src: 2026-08-30-live-search-synthesis.md §3]
- Run B fabricated an interpolation inside a verbatim Tavily quote and relied on non-primary sources; run A over-read a marketing FAQ. [src: 2026-08-30-live-search-synthesis.md §4]
- Common Crawl samples rather than deep-crawls, so run A's rejection of it for university subdomains is the usable one. [src: 2026-08-30-live-search-synthesis.md §6]
- The synthesis's decision was Tavily first, Mojeek second and conditional, Brave required a paid storage tier, its definitions bringing a bare URL inside "Search Results" regardless, and Exa, Serper and SerpApi restrictive, and Google, Bing, DuckDuckGo and Startpage not options. [src: 2026-08-30-live-search-synthesis.md §7]
- The rule it recommended for CLAUDE.md: the engine consumes a URL and discards the response, never persisting a result object, snippet column or SERP cache. [src: 2026-08-30-live-search-synthesis.md §7]
- Still open: Tavily's upstream, Mojeek's contract, non-English recall (untested), Run A's Google v. SerpApi claim and Exa's current wording. [src: 2026-08-30-live-search-synthesis.md §8]

Superseded: discovery now runs on Exa and Brave, each used for its measured best side, on written permission from both that the roster spec requires before any code reads their keys; Tavily was removed from discovery on 2026-09-24 and is kept for name-to-site resolution, `/map` host inventory and site-search fallback, and is never used for per-student search — see [How the search engine works](../../superpowers/2026-10-24-search-engine-how-it-works.md) and [Discovery by role](../../superpowers/specs/2026-09-17-role-routed-discovery-design.md).
