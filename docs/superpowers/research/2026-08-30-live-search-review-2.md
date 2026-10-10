# **Comprehensive Evaluation of Web Search APIs for Autonomous URL Discovery and Retention**

The architectural viability of an autonomous system designed to discover URLs, fetch them independently, and persistently cite the fetched pages relies fundamentally on the underlying search provider’s terms of service regarding data retention. Commercial search providers operate under business models predicated on displaying proprietary results, complete with ranked lists, titles, text snippets, and advertising. Consequently, their legal frameworks are heavily optimized to prevent unauthorized caching, the reverse-engineering of ranking algorithms, and the construction of competing databases. The proposed architecture strips away the snippet, title, and ranking order, requiring the retention of only the bare URL. The critical legal evaluation therefore hinges on whether a bare URL, divorced from its original search engine results page context, is legally classified as restricted data under the provider’s operative clauses, and whether permanent retention of that URL is permitted.

## **Part 1: The Retention Bottleneck and Legal Viability (Question 0\)**

The most valuable finding in this analysis is that the open-source repository Common Crawl is explicitly permissive regarding permanent data retention, and the Google Custom Search JSON API remains entirely silent on the caching or permanent storage of search results, offering no explicit prohibition against storing URLs for non-competing database purposes. Conversely, providers such as Microsoft Bing and Brave Search explicitly classify URLs as restricted data and strictly prohibit their retention. The providers evaluated fall into three distinct legal categories: explicitly permissive, legally silent, and explicitly restrictive.

### **Providers Explicitly Permitting URL Retention**

**Common Crawl** Common Crawl operates as a non-profit organization providing its index entirely unrestricted, making it the most legally permissive option for database construction1. The terms do not restrict display, caching, derived data, or retention duration, meaning a bare URL extracted from the Common Crawl Index becomes the property of the user to store indefinitely.

* **Operative Clause:** "Common Crawl maintains a free, open repository of web crawl data that can be used by anyone... Free and open corpus since 2007."  
* **URL:** https://commoncrawl.org/  
* **Date Read:** August 30, 2026\.

**SerpApi (Reseller via Legal Shield)** SerpApi acts as a proxy scraper for upstream engines like Google and Bing. Rather than restricting retention, SerpApi explicitly assumes the legal liability for the collection of the data, provided the ultimate use case is not illegal2. Retention of a bare URL for a persistent citation database falls well within their permitted use cases. The provider actively litigates to defend the right to scrape public data, arguing that upstream providers cannot use copyright law to restrict access to publicly visible web content4.

* **Operative Clause:** "Under and subject to the terms of your agreement with us, our U.S. Legal Shield covers the scraping and parsing of search engine data, as long as your use of the data or service is not illegal... In short, we assume liability for the lawful collection of public search data (scraping, parsing, and related actions), but not for how that data is ultimately used."  
* **URL:** https://serpapi.com/us-legal-shield  
* **Date Read:** August 30, 2026\.

### **Providers Silent on URL Retention**

**Google Custom Search JSON API and Programmable Search Engine (CSE)** Google’s terms are highly complex and distributed across the Google APIs Terms of Service and the Custom Search JSON API Additional Terms6. The terms heavily restrict the display of results and mandate that API clients do not function substantially the same as Google Search, but they are entirely silent on the persistent caching or storage of bare URLs for internal database building. Google explicitly restricts transferring or storing sensitive user data and prohibits using the API to process data subject to international traffic regulations7, but no explicit prohibition prevents URL retention for non-competing citation systems. It is vital to note that permission cannot be inferred from this silence, but the silence itself means there is no explicit contractual blocker to URL retention.

* **Operative Clause (API Prohibitions):** "Sublicense an API for use by a third party. Consequently, you will not create an API Client that functions substantially the same as the APIs and offer it for use by third parties... You will not use the APIs to process or store any data that is subject to the International Traffic in Arms Regulations..."  
* **URL:** https://developers.google.com/terms  
* **Document Last Updated:** January 11, 2020 (Custom Search JSON API Additional Terms)6.  
* **Date Read:** August 30, 2026\.

**Exa (formerly Metaphor)** Exa is a neural search engine designed specifically for artificial intelligence agents and applications9. The public Terms of Service and Privacy Policy provide no operative clause restricting a customer's ability to cache or store the URLs returned by the API11. Exa heavily promotes a "Zero Data Retention" policy regarding how they process and log customer queries to protect enterprise privacy, but this restricts the provider, not the user13. The terms are silent on customer data retention.

* **Operative Clause:** The terms are completely silent regarding customer restrictions on caching, storing, or retaining search results or URLs.  
* **URL:** https://exa.ai/privacy-policy  
* **Date Read:** August 30, 2026\.

**You.com Search API** Similar to Exa, You.com positions itself as an enterprise-grade AI search tool with strict privacy controls15. The provider advertises "Zero Data Retention" for customer queries, but an exhaustive review of their documentation reveals total silence regarding any restrictions on the customer's ability to cache, store, or build databases from the discovered URLs17.

* **Operative Clause:** The terms are completely silent regarding customer restrictions on caching, storing, or retaining search results or URLs.  
* **URL:** https://apps.apple.com/ru/app/you-com-enterprise-grade-ai/id1600782099?l=en-GB and https://you.com/docs/guides/research  
* **Date Read:** August 30, 2026\.

**Mojeek and Marginalia** Both Mojeek and Marginalia operate independent, non-commercial, or specialized search indices19. Their terms of service and API documentation are entirely silent on the retention, caching, or storage of search results19. Marginalia specifies that its API is intended for "non-commercial content search," but does not explicitly restrict database building or URL retention22.

* **Operative Clause:** The terms are completely silent regarding customer restrictions on caching, storing, or retaining search results or URLs.  
* **URL:** https://www.mojeek.com/support/api/search/xml\_response.html and https://github.com/metorial/metorial-index  
* **Date Read:** August 30, 2026\.

### **Providers Explicitly Restricting URL Retention**

**Microsoft Bing Web Search (Azure)** Bing offers the most aggressive and legally watertight restrictions against data retention, explicitly closing the loophole regarding bare URLs. The terms prohibit copying, storing, or caching any data from responses, strictly forbidding the use of URLs for machine learning, algorithmic activity, or the creation of competing databases. While Bing allows a brief 24-hour caching window strictly for "continuity of service," building a persistent database of URLs is heavily prohibited24.

* **Operative Clause (Caching Restriction):** "Do not: Copy, store, or cache any data from Responses... Use data received from the Search APIs as part of any machine learning or similar algorithmic activity. Do not use this data to train, evaluate, or improve new or existing services that you or third parties might offer."  
* **Operative Clause (Defining URLs as Restricted):** "While URL discovery is an exception to the general 'internet search experience' requirements, the following rules apply to using the URLs and search response data: You must not cache, copy, or store any data or content from, or derived from, the search response, other than the limited URL copying described... You must not use the data (including the URLs) received from the Search APIs as part of any search index or machine learning or similar algorithmic activity."  
* **URL:** https://www.microsoft.com/en-us/bing/apis/legal  
* **Date Read:** August 30, 2026\.

**Brave Search API** Brave explicitly restricts the storage of any API output and prohibits the creation of derivative works. The terms explicitly forbid creating a database of Search Results "in whole or in part"26. A bare URL is fundamentally considered a part of the Search Result26. Furthermore, Brave explicitly prohibits using the content for machine learning or algorithmic activity unless the customer is subscribed to a specific "Data for AI" plan, but even under that premium plan, persistent database building and result caching remain entirely blocked27.

* **Operative Clause:** "Customer shall not and shall not permit End Users or others to: (i) store, cache, or create a database of Search Results, in whole or in part, other than transient storage required for operation of Customer Applications or related software, service or systems; (ii) create derivative works of the API, Documentation or Search Results..."  
* **URL:** https://api-dashboard.search.brave.com/terms-of-service  
* **Document Last Updated:** February 11, 202626.  
* **Date Read:** August 30, 2026\.

**Tavily** Tavily focuses its legal framework on restricting the creation of competing databases or models. While Tavily does not explicitly forbid transient caching, the sweeping prohibition against developing "competing databases" creates an extreme legal hazard for any autonomous system maintaining a persistent repository of discovered URLs28.

* **Operative Clause:** "Customers are strictly prohibited from using Output generated by Tavily's AI Functionality to develop models (which would include competing databases or search systems) that compete with the Company and/or its AI Functionalities."  
* **URL:** https://tavily.com/terms  
* **Document Last Updated:** May 4, 202628.  
* **Date Read:** August 30, 2026\.

**Serper.dev** Serper operates as a third-party scraper for Google search results but implements highly restrictive terms on its own end users. The terms restrict copying, preparing derivative works, or falsifying the origin of the material29. Because Serper acts as a direct passthrough to Google, building a persistent database from its outputs without explicit permission violates their intellectual property and data license restrictions.

* **Operative Clause:** "This constitutes the grant of a license, not a transfer of title, and under this license, you may not: Modify, copy, prepare derivative works of, decompile, or reverse engineer any materials and software contained on the serper.dev website... Falsify or delete any author attributions, legal notices, or other labels of the origin or source of material."  
* **URL:** https://serper.dev/terms  
* **Document Last Updated:** May 29, 202429.  
* **Date Read:** August 30, 2026\.

## **Part 2: The Provider Matrix (Question 1\)**

The following matrix evaluates the commercial and technical parameters of the requested search providers. Note that providers functioning as resellers (such as Startpage and DuckDuckGo, which rely primarily on Google and Bing respectively) inherently pass along the upstream provider's terms of service unless they operate outside standard API agreements via scraping methods. Furthermore, neither Startpage nor DuckDuckGo offer official commercial search APIs for autonomous programmatic access, rendering their technical parameters inapplicable for this specific architectural requirement.

| Provider | Storage / Retention Terms (Verbatim Quote, URL, Date Read) | URL-Only Retention Permitted? | Retention Duration Cap | Attribution Required | Index Source | Non-English Coverage | site: / Domain Restriction | Freshness / Recency Filter | Rate Limits | Cost | Result Cap Per Query & Deep Pagination |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| **Common Crawl** | "Common Crawl maintains a free, open repository of web crawl data that can be used by anyone." https://commoncrawl.org/ (Aug 30, 2026\)1. | Yes | None | None explicitly mandated; academic citation expected. | Own crawler (CCBot)1. | Excellent (global web crawl spanning millions of domains)30. | Yes, via CDX API (matchType=domain)32. | No native recency filter; data released in periodic monthly snapshots1. | Free tier CDX API is heavily rate-limited natively; unlimited if self-hosted via AWS31. | Free (AWS Athena compute costs apply if self-hosted)1. | Unlimited deep pagination capability32. |
| **Google Custom Search JSON API** | "You will not create an API Client that functions substantially the same as the APIs and offer it for use by third parties... You will not use the APIs to process or store any data..." https://developers.google.com/terms (Aug 30, 2026\)7. | Silent | None stated | Yes, Google branding required on display (irrelevant if purely backend). | Own crawler. | Exceptional (native handling of German, Korean, Turkish, Chinese, French, Hungarian)35. | Yes, native site: and Programmable Search domain whitelists36. | Yes, dateRestrict parameter available (e.g., d\[number\])35. | 10k queries/day limit for general search; no limit for Site Restricted API36. | $5 per 1,000 queries36. | Max 100 results total per query (start limit is 91; max 10 per page). Deep pagination strictly prohibited35. |
| **SerpApi** | "In short, we assume liability for the lawful collection of public search data... but not for how that data is ultimately used." https://serpapi.com/us-legal-shield (Aug 30, 2026\)3. | Silent (Assumes liability via Legal Shield). | None stated | None. | Reseller (Scrapes Google, Bing, Baidu, DuckDuckGo, etc.)41. | Exceptional (Inherited from Google/Bing). | Yes, fully supports upstream site: operators. | Yes, inherited from upstream search engine. | Up to 100,000 \+ 1% of plan volume per hour for enterprise42. | $25/mo (1k queries) to $275/mo (30k queries)42. | 100 organic results per single request via Google Light Fast API44. Inherits upstream deep pagination limits. |
| **Brave Search API** | "Customer shall not... store, cache, or create a database of Search Results, in whole or in part, other than transient storage..." https://api-dashboard.search.brave.com/terms-of-service (Aug 30, 2026\)26. | No26. | Transient execution only | Yes, mandatory attribution25. | Own crawler (35B pages)45. | Good, but shallower than Google in non-Western localized markets. | Yes, natively supported. | Yes, natively supported. | Variable by enterprise plan. | Custom enterprise pricing. | Inherently limited by pagination tokens. |
| **Bing Web Search (Azure)** | "Do not: Copy, store, or cache any data from Responses... You must not use the data (including the URLs)... as part of any search index..." https://www.microsoft.com/en-us/bing/apis/legal (Aug 30, 2026\)24. | No25. | 24 hours max for "continuity of service"25. | Yes, functional hyperlink to Microsoft Privacy Statement required24. | Own crawler. | Exceptional. | Yes, native support. | Yes, freshness filter (Day, Week, Month, Custom)46. | 150 transactions per second47. | $14 per 1,000 transactions47. | Supports deep pagination, but explicit caching restriction renders this capability legally moot. |
| **Exa** | Terms silent on URL caching. Privacy policy guarantees "Zero Data Retention" for logging user queries. https://exa.ai/privacy-policy (Aug 30, 2026\)12. | Silent | None stated | None. | Own index (Neural / Embedding-based). | Moderate. Relies on embeddings, handles translation well, but index footprint is smaller than Google. | Yes, native includeDomains parameter. | Yes, maxAgeHours parameter9. | Enterprise SLAs available48. | Enterprise pricing48. | Returns specific result arrays, deep pagination limited by embedding context window constraints. |
| **Tavily** | "Customers are strictly prohibited from using Output... to develop models (which would include competing databases or search systems)..." https://tavily.com/terms (Aug 30, 2026\)28. | No | None stated | None. | Reseller / Meta-search. | Strong (relies on upstream search APIs). | Yes, native domain filtering22. | Yes. | Variable based on plan. | Custom pricing. | Limited to standard API response payload depth. |
| **Serper.dev** | "...under this license, you may not: Modify, copy, prepare derivative works of, decompile, or reverse engineer any materials..." https://serper.dev/terms (Aug 30, 2026\)29. | No | None stated | None. | Reseller (Google scraper). | Exceptional (Inherits Google algorithms). | Yes. | Yes (Inherits Google parameters). | Variable. | Custom pricing. | Inherits Google's strict 100-result architectural cap. |
| **You.com Search API** | Silent on customer retention limits. Promotes "Zero Data Retention" purely for their own logging. https://you.com/docs/guides/research (Aug 30, 2026\)15. | Silent | None stated | None. | Own crawler \+ Reseller mix. | Strong. | Yes. | Yes. | Variable. | Custom pricing. | Standard API payload limitations. |
| **Mojeek** | Terms completely silent on retention. https://www.mojeek.com/support/api/search/xml\_response.html (Aug 30, 2026\)19. | Silent | None stated | None. | Own crawler (independent index)19. | Poor to Moderate (highly Western-centric index topology). | Yes. | Yes. | Variable. | Custom pricing. | Unknown deep pagination limits. |
| **Marginalia Search** | Silent on retention; explicitly built for "non-commercial content search." https://github.com/metorial/metorial-index (Aug 30, 2026\)22. | Silent | None stated | None. | Own crawler (small web focus)21. | Poor (Focuses predominantly on English, text-heavy small web). | Yes. | No native recency filtering documented. | Heavily rate-limited for public API20. | Free. | Shallow pagination. |
| **DuckDuckGo** | No official commercial search API is offered for autonomous programmatic querying. | N/A | N/A | N/A | Reseller (Bing primary). | N/A | N/A | N/A | N/A | N/A | N/A |
| **Startpage** | No official commercial search API is offered for autonomous programmatic querying. | N/A | N/A | N/A | Reseller (Google primary). | N/A | N/A | N/A | N/A | N/A | N/A |

## **Part 3: Architectural Fitness for Academic and Funding Discovery (Question 2\)**

The queries required for this specific product architecture are not general consumer web queries designed to seek broad information. They are highly specific, **funding-shaped and site-scoped** operations, specifically targeting scholarship, tuition-waiver, assistantship, and fee-discount pages on known university domains and government bodies. This architectural constraint narrows the functional utility of the search providers significantly, as the ability to execute reliable domain restrictions and cross-lingual conceptual matching becomes paramount.

### **The Reliability of site: Restrictions**

Because the queries name specific hosts (e.g., site:tum.de or site:ox.ac.uk), the search API must reliably enforce strict domain scoping without hallucinating results from external domains.  
Google Custom Search JSON API remains the industry standard for strict site: operator implementation. Furthermore, the Google Custom Search "Site Restricted API" allows for an explicit programmatic configuration where the search engine is locked to 10 or fewer specific domains. This strict whitelisting completely eliminates hallucinated or out-of-scope results, returning only URLs originating from the targeted institution36. Providers like SerpApi perfectly mirror this functionality by passing the operators directly to the upstream engine. Bing similarly provides a highly reliable site: operator implementation47.  
Conversely, neural search engines such as Exa and Tavily support domain inclusion filters (e.g., includeDomains), but their underlying architecture presents a challenge9. Neural engines map queries to high-dimensional vector spaces, and they occasionally struggle with rigid lexical boundaries if the embedding model prioritizes semantic similarity over absolute domain constraints.  
Common Crawl offers exceptional reliability in this regard. The CDX index utilizes exact URL string matching (matchType=domain or matchType=host). Querying the index with these parameters guarantees zero false positives, returning exclusively the URLs that cryptographically match the requested domain32.

### **Coverage of University Subdomains**

Funded graduate schools, specific grant programs, and departmental fee-waivers frequently reside on isolated, decentralized subdomains (e.g., gradschool.engineering.university.edu). This decentralized topology is notoriously difficult to map.  
A standard robots.txt or root sitemap.xml almost never encompasses deeply nested, independently administered departmental subdomains33. Sitemaps represent the owner's *intended* indexable pages, not the physical reality of the server's contents. Consequently, they fail entirely to surface "orphan pages"—URLs that are no longer linked in the main navigation menus but remain active, valid, and highly relevant to funding discovery33.  
Commercial search indexes like Google and Bing utilize immense crawling budgets that reliably map disjointed university subdomains via external backlinks and historical indexing data. This makes them ideal for discovering orphan pages or isolated academic portals that the university webmaster may have omitted from the primary sitemap.  
Common Crawl, however, is arguably the most powerful tool for this specific subdomain mapping task. The CDX API is natively designed to surface all known subdomains associated with a root domain. By querying matchType=domain on university.edu, the CDX index returns every single URL across every subdomain observed during the crawler's operational history33. Because the archive retains records of pages long after they have been unlinked from the main site architecture, the CDX server is frequently the single best method for mapping the complete physical perimeter of a university’s digital presence, completely bypassing the limitations of sitemaps33. Independent indices like Marginalia or Mojeek lack the crawl budget to comprehensively index deep university subdomains, heavily favoring top-level domains and text-heavy consumer blogs50.

### **Cross-Lingual Information Retrieval**

The autonomous system must retrieve German, Korean, Turkish, Chinese, French, and Hungarian pages using English query terms. This requires the search provider to understand the semantic intent of the query rather than relying purely on exact lexical string matching.  
Google and its resellers (like SerpApi) excel at this task. Google’s internal query-expansion and sophisticated synonym algorithms automatically bridge lexical gaps across language barriers52. Searching for the English term "scholarship" on a German .de domain will natively surface pages utilizing the term "Stipendium" or "Förderung," mapping the conceptual intent seamlessly.  
Exa is uniquely positioned for cross-lingual discovery. As an embedding-based neural engine, Exa inherently maps concepts rather than keywords into vector spaces. An English query for "tuition waiver" will map to the same mathematical vector space as the French or Hungarian equivalent, making it highly effective for cross-lingual discovery without requiring explicit dictionary translations9.  
Common Crawl fails entirely at this requirement. The CDX index is purely a metadata registry of URLs32. It does not support semantic or text-based searching without first downloading and processing the raw WARC (Web Archive) files for the underlying HTML content30. If the English word "scholarship" is not explicitly visible in the URL slug of the Turkish webpage, the CDX metadata lookup will not find it33.

## **Part 4: Alternatives to Commercial Search APIs (Question 3\)**

Relying exclusively on commercial search APIs introduces strict rate limits, severe legal liabilities regarding data retention, and aggressive pagination caps—such as Google's hard limit preventing the retrieval of more than 100 results per query35. Exploring alternatives is practically mandatory for a product aiming to snapshot and cite URLs at a global scale.

### **Common Crawl (The Non-Commercial Heavyweight)**

Common Crawl is a multi-petabyte repository of the open web, adding between 3 and 5 billion new pages every month1.

* **Terms:** The terms are fully permissive. Wholesale extraction, transformation, and retention of the data are actively encouraged by the non-profit1.  
* **Coverage:** The coverage is massive, encompassing hundreds of millions of domains and serving as the foundational dataset for major large language models30.  
* **Index Querying & Cost:** The CDX Index API allows developers to look up any domain and receive every URL, timestamp, HTTP status, and MIME type associated with it32. While third-party services like Apify offer managed scrapers for this data at $8.25 per 1,000 items32, querying the CDX directly via AWS Athena or the public API is free31. However, the public API is heavily rate-limited for anonymous users, meaning self-hosting the index processing infrastructure on AWS is necessary for high-throughput discovery34.  
* **Where it Fails:** Common Crawl fails significantly regarding index freshness and semantic searchability. The data is released in periodic quarterly or monthly snapshots, meaning newly published scholarship pages will not appear in the index for weeks or months30. More critically, the CDX index cannot be queried for page *content*—only for URLs33. To substitute for a site: search looking for specific keywords across a university, the system would have to download the raw Web Extracted Text (WET) files or Web Archive (WARC) files for the entire university domain and index them locally53. This incurs massive computational, storage, and bandwidth overhead, shifting the processing burden entirely onto the local architecture.

### **Provider-Published Sitemaps and Site Search Endpoints**

Universities manage their own web infrastructure, theoretically allowing direct querying without relying on global search engines.

* **Sitemaps:** Sitemaps provide a polite, free, and direct method to map a site’s intended indexable pages via robots.txt or sitemap.xml33.  
* **Where it Fails:** University sitemaps are notoriously fragmented and unreliable. A sitemap hosted on www.university.edu will almost never contain the routing links for independent departments like physics.university.edu. Furthermore, they fail to surface historical or orphan pages that are no longer actively maintained in the main navigation but still host valid scholarship application forms33.  
* **Site Search Endpoints:** Utilizing a university's internal search bar (e.g., via automated POST requests) theoretically bypasses commercial APIs entirely.  
* **Where it Fails:** Internal university search engines are historically poorly maintained, rarely offer clean API endpoints, rely heavily on client-side JavaScript rendering that breaks automated scrapers, and enforce strict IP-based rate limiting to prevent denial-of-service attacks. They are impossible to query reliably at a global scale.

### **Self-Hosted Search Over Fetched Pages**

This alternative involves maintaining a local Elasticsearch or vector database over pages the system has already fetched and archived.

* **Where it Fails:** While a self-hosted architecture solves the legal retention problem perfectly, it suffers inherently from the "cold start" paradox. Self-hosted search only works on data already ingested into the local system. It cannot *discover* new URLs on the open web, which is the primary architectural requirement of the product33. It replaces the need to re-query external APIs for known pages, but it fundamentally does not replace the discovery engine itself.

### **National or Academic Body Indices**

* **Where it Fails:** There is no centralized, globally crawlable academic index that maps the granular sub-page content of university funding mechanisms. Platforms like ResearchGate or government education portals map high-level institutional data, not the specific URL routing of departmental fee-waivers or localized assistantship applications. Attempting to scrape centralized databases yields high-level directory information rather than the target URLs.

## **Part 5: Strategic Recommendations**

The final ranking of search providers is determined primarily by legal retention safety, followed closely by the capability to execute cross-lingual, site-scoped queries effectively. A highly capable index that legally jeopardizes the product architecture by explicitly prohibiting URL retention is categorized as fundamentally unusable.

### **The Ranked Recommendation**

**Rank 1: Google Custom Search JSON API (and SerpApi as a Proxy)**

* **Reasoning:** Google is the only enterprise-grade index that is completely *silent* on the prohibition of URL caching in its JSON API terms. While it strictly regulates how results are *displayed* and heavily prohibits building a competing search engine, extracting and retaining a bare URL for a non-competing, internal citation database is not explicitly forbidden by the operative clauses7. If legal ambiguity regarding Google's terms is a concern, utilizing **SerpApi** provides access to the exact same index with an explicit U.S. Legal Shield that actively assumes liability for the scraping process, provided the end-use is lawful3.  
* **Capabilities:** Google flawlessly executes rigid site: scoping, penetrates deep university subdomains, and natively handles the required cross-lingual query mapping via its query-expansion algorithms36.  
* **The Caveat:** The Google Custom Search JSON API hard-caps queries at 100 results. Deep pagination is physically impossible beyond start=9135. This means if a university has 500 relevant scholarship pages, 400 are permanently inaccessible via the API. SerpApi bypasses this slightly via their Google Light Fast API to pull 100 results in one single call, but the hard depth ceiling inherently remains44.

**Rank 2: Exa (Neural Search)**

* **Reasoning:** Exa's terms are entirely silent on caching restrictions for end users, and they aggressively market a "Zero Data Retention" stance for their own logging systems, indicating a privacy-forward operating model12.  
* **Capabilities:** As a neural index designed specifically for AI workflows, it excels at cross-lingual discovery and semantic matching across academic domains. It handles includeDomains effectively9. It avoids the lexical limitations of older scrapers, making it highly suitable for identifying funding opportunities described in foreign languages.

**Rank 3: Common Crawl (Augmented with Local Indexing)**

* **Reasoning:** This is the absolute safest legal route. The data is entirely open, explicitly permitting unlimited retention and database construction without any risk of terms-of-service violations1.  
* **Capabilities:** It fails as a real-time keyword search engine due to the lack of content querying and severe freshness lag30. However, the system architecture could be modified to accommodate it: use the CDX API to pull *every single URL* from a target university domain using matchType=domain33, fetch those URLs independently, and execute the keyword search (e.g., "scholarship") locally on the fetched HTML. This shifts the massive compute cost from the API provider to the local architecture but completely dissolves any legal retention risk and bypasses Google's 100-result pagination limit.

**Rank 4 (Disqualified): Bing Web Search, Brave Search, and Tavily**

* **Reasoning:** Immediate disqualification based on restrictive terms. Bing explicitly prohibits the retention of URLs for algorithmic or database purposes25. Brave explicitly prohibits storing or creating a database of any part of their Search Results, even transiently26. Tavily strictly prohibits using outputs to build competing models or databases28. A superior index that introduces extreme legal jeopardy to the product architecture is ultimately unusable.

### **Variables That Would Alter the Recommendation**

> 1. **A Terms of Service Update:** If Google updates the Custom Search JSON API terms to explicitly include URLs in a "no-caching" or "no-database" clause—mirroring Bing's highly restrictive recent updates—Google would immediately drop to Rank 4\. The architecture would be forced to shift entirely to the Common Crawl local-indexing model to avoid legal liability.  
> 2. **Scaling Pricing Shifts:** SerpApi currently costs up to $275 per month for 30,000 queries42. If the required query volume scales to millions of requests per month across global university domains, the economic burden of SerpApi would become unsustainable. This would necessitate building an internal data pipeline utilizing the Common Crawl corpus, entirely bypassing commercial APIs to control costs.  
> 3. **New Entrants in Open Search:** If an open-source provider develops a real-time, semantically searchable index built strictly on top of the Common Crawl corpus—combining the freshness and searchability of commercial search with the absolute legal permissiveness of open data—it would immediately supersede Google and Exa to become the Rank 1 architectural choice.

#### **Works cited**

> 1. Common Crawl \- Open Repository of Web Crawl Data, [https://commoncrawl.org/](https://commoncrawl.org/)  
> 2. FAQ \- SerpApi, [https://serpapi.com/faq](https://serpapi.com/faq)  
> 3. Scraper Legal Protection \- SerpApi's U.S. Legal Shield, [https://serpapi.com/us-legal-shield](https://serpapi.com/us-legal-shield)  
> 4. Google v. SerpApi: Threatening Access to Public Data, [https://serpapi.com/blog/google-v-serpapi-threatening-access-to-public-data/](https://serpapi.com/blog/google-v-serpapi-threatening-access-to-public-data/)  
> 5. Google v. SerpApi: We're filing a Motion to Dismiss. Here's why we, [https://serpapi.com/blog/google-v-serpapi-motion-to-dismiss-why-were-in-the-right/](https://serpapi.com/blog/google-v-serpapi-motion-to-dismiss-why-were-in-the-right/)  
> 6. Custom Search JSON API Additional Terms of Service, [https://developers.google.com/custom-search/terms](https://developers.google.com/custom-search/terms)  
> 7. Google APIs Terms of Service, [https://developers.google.com/terms](https://developers.google.com/terms)  
> 8. Google Workspace user data and developer policy, [https://developers.google.com/workspace/workspace-api-user-data-developer-policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy)  
> 9. Exa | Sim Docs, [https://docs.sim.ai/integrations/exa](https://docs.sim.ai/integrations/exa)  
> 10. Terms of Use \- Metaphor, [https://withmetaphor.com/terms](https://withmetaphor.com/terms)  
> 11. Exa Labs Vulnerability Disclosure Policy, [https://exa.ai/security](https://exa.ai/security)  
> 12. Privacy Policy \- Exa, [https://exa.ai/privacy-policy](https://exa.ai/privacy-policy)  
> 13. GitHub \- api-evangelist/exa: Exa is a neural web search API, [https://github.com/api-evangelist/exa](https://github.com/api-evangelist/exa)  
> 14. Exa Login, [https://dashboard.exa.ai/](https://dashboard.exa.ai/)  
> 15. You.com \- Enterprise grade AI \- App Store, [https://apps.apple.com/ru/app/you-com-enterprise-grade-ai/id1600782099?l=en-GB](https://apps.apple.com/ru/app/you-com-enterprise-grade-ai/id1600782099?l=en-GB)  
> 16. AI Research Agents: Architecture and Capabilities \- You.com, [https://you.com/resources/ai-research-agent](https://you.com/resources/ai-research-agent)  
> 17. You.com (Su-Sea, Inc.) Security & Compliance (SOC 2, ISO 27001, [https://aifoxx.com/trust/you-com](https://aifoxx.com/trust/you-com)  
> 18. Research API Overview | You.com | You.com | Documentation, [https://you.com/docs/guides/research](https://you.com/docs/guides/research)  
> 19. API Documentation \- Search XML Response Format \- Mojeek, [https://www.mojeek.com/support/api/search/xml\_response.html](https://www.mojeek.com/support/api/search/xml_response.html)  
> 20. Metorial MCP Index \- An ever growing list of open source MCP servers, [https://github.com/metorial/metorial-index](https://github.com/metorial/metorial-index)  
> 21. Verticals \+ Search \- NLnet Foundation, [https://nlnet.nl/thema/Verticals+Search.html](https://nlnet.nl/thema/Verticals+Search.html)  
> 22. MCP Server Integrations for AI Apps \- Klavis AI, [https://www.klavis.ai/mcp-servers](https://www.klavis.ai/mcp-servers)  
> 23. awesome-mcp-servers/docs/knowledge-management--memory.md, [https://github.com/TensorBlock/awesome-mcp-servers/blob/main/docs/knowledge-management--memory.md](https://github.com/TensorBlock/awesome-mcp-servers/blob/main/docs/knowledge-management--memory.md)  
> 24. Legal Terms for Bing Search APIs, with your LLM \- Microsoft, [https://www.microsoft.com/en-us/bing/apis/llm-legal](https://www.microsoft.com/en-us/bing/apis/llm-legal)  
> 25. Bing Search APIs – Legal Information \- Microsoft, [https://www.microsoft.com/en-us/bing/apis/legal](https://www.microsoft.com/en-us/bing/apis/legal)  
> 26. search api terms of use, [https://api-dashboard.search.brave.com/terms-of-service](https://api-dashboard.search.brave.com/terms-of-service)  
> 27. Clarify possible Brave Search TOS violation · Issue \#522 \- GitHub, [https://github.com/modelcontextprotocol/servers/issues/522](https://github.com/modelcontextprotocol/servers/issues/522)  
> 28. Tavily – Platform Terms of Service, [https://tavily.com/terms](https://tavily.com/terms)  
> 29. Terms of Service \- Serper, [https://serper.dev/terms](https://serper.dev/terms)  
> 30. Data Sources | RankParse, [https://rankparse.com/data](https://rankparse.com/data)  
> 31. Improved methodology for longitudinal Web analytics using ... \- arXiv, [https://arxiv.org/html/2404.09770v1](https://arxiv.org/html/2404.09770v1)  
> 32. Common Crawl Scraper \- URL Index Lookup & Export API \- Apify, [https://apify.com/parseforge/common-crawl-index-scraper](https://apify.com/parseforge/common-crawl-index-scraper)  
> 33. Find All URLs on a Domain: 5 Methods to Map Every Page \- cloro, [https://cloro.dev/blog/find-all-urls-on-domain/](https://cloro.dev/blog/find-all-urls-on-domain/)  
> 34. Internet Archive vs Common Crawl vs web archive \- Bright Data, [https://brightdata.com/blog/web-data/internet-archive-vs-common-crawl-vs-web-archive](https://brightdata.com/blog/web-data/internet-archive-vs-common-crawl-vs-web-archive)  
> 35. Method: cse.list | Custom Search JSON API \- Google for Developers, [https://developers.google.com/custom-search/v1/reference/rest/v1/cse/list](https://developers.google.com/custom-search/v1/reference/rest/v1/cse/list)  
> 36. Custom Search Site Restricted JSON API \- Google for Developers, [https://developers.google.com/custom-search/v1/site\_restricted\_api](https://developers.google.com/custom-search/v1/site_restricted_api)  
> 37. Custom Ranking | Programmable Search Engine, [https://developers.google.com/custom-search/docs/ranking](https://developers.google.com/custom-search/docs/ranking)  
> 38. Overview | Programmable Search Engine \- Google for Developers, [https://developers.google.com/custom-search/docs/overview](https://developers.google.com/custom-search/docs/overview)  
> 39. How to get more than 100 results from Google Custom Search API, [https://stackoverflow.com/questions/34031557/how-to-get-more-than-100-results-from-google-custom-search-api](https://stackoverflow.com/questions/34031557/how-to-get-more-than-100-results-from-google-custom-search-api)  
> 40. Implementing Google Custom Search Engine's JSON API in the, [https://www.raymondcamden.com/2020/03/22/implementing-google-custom-search-engines-json-api-in-the-jamstack](https://www.raymondcamden.com/2020/03/22/implementing-google-custom-search-engines-json-api-in-the-jamstack)  
> 41. Academic & Legal Research APIs \- SerpApi, [https://serpapi.com/search-engine-apis/academic-legal-research](https://serpapi.com/search-engine-apis/academic-legal-research)  
> 42. SerpApi: Google Search API, [https://serpapi.com/](https://serpapi.com/)  
> 43. Breakdown of SerpApi's Subscriptions, [https://serpapi.com/blog/breakdown-of-serpapis-subscriptions/](https://serpapi.com/blog/breakdown-of-serpapis-subscriptions/)  
> 44. Scrape 100 Search Results on Google (solution to num ... \- SerpApi, [https://serpapi.com/blog/solution-to-scrape-100-search-results-on-google-google-fast-light-api/](https://serpapi.com/blog/solution-to-scrape-100-search-results-on-google-google-fast-light-api/)  
> 45. Brave is the only search API offering true Zero Data Retention, [https://brave.com/blog/search-api-zero-data-retention/](https://brave.com/blog/search-api-zero-data-retention/)  
> 46. Grounding with Bing Search (classic) \- Microsoft Learn, [https://learn.microsoft.com/en-us/azure/foundry-classic/agents/how-to/tools-classic/bing-grounding](https://learn.microsoft.com/en-us/azure/foundry-classic/agents/how-to/tools-classic/bing-grounding)  
> 47. Grounding with Bing \- Microsoft, [https://www.microsoft.com/en-us/bing/apis](https://www.microsoft.com/en-us/bing/apis)  
> 48. Enterprise Web Search API | Exa, [https://exa.ai/enterprise](https://exa.ai/enterprise)  
> 49. APIs \- API Evangelist, [https://apis.apievangelist.com/m/](https://apis.apievangelist.com/m/)  
> 50. Weird 10k Spike In Google Traffic For SEO, Content Writing, [https://www.eelkat.com/weird-spike-in-google-traffic-for-seo-content-writing-search-terms.html](https://www.eelkat.com/weird-spike-in-google-traffic-for-seo-content-writing-search-terms.html)  
> 51. News publishers limit Internet Archive access due to AI scraping, [https://news.ycombinator.com/item?id=47017138](https://news.ycombinator.com/item?id=47017138)  
> 52. Rewriting Queries | Programmable Search Engine, [https://developers.google.com/custom-search/docs/queries](https://developers.google.com/custom-search/docs/queries)  
> 53. Inside Common Crawl: The Dataset Behind AI Models (and Its Real, [https://dev.to/extractdata/inside-common-crawl-the-dataset-behind-ai-models-and-its-real-world-limits-2eo2](https://dev.to/extractdata/inside-common-crawl-the-dataset-behind-ai-models-and-its-real-world-limits-2eo2)  
> 54. Pitfalls of Common Crawl for E-Commerce \- CEUR-WS.org, [https://ceur-ws.org/Vol-1426/paper-04.pdf](https://ceur-ws.org/Vol-1426/paper-04.pdf)