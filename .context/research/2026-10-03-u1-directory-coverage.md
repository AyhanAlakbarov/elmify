# U1: university directory coverage and evidence tiers for binding a university to its website

Researched 2026-10-03. Every count below was measured on that date from a live query URL given in the table notes.

**Decision this serves.** We bind a recognised university to its own website, in any country, using evidence tiers:
- **Moderate signals:** ROR, Wikidata, uniRank, Webometrics, a ccTLD that matches the country, and RDAP-proven continuous domain ownership.
- **Strong signals:** WHED's URL, or the URL on the state's own list.
- **Rule:** one strong signal or two moderate ones, on top of a floor. The floor is: the site's own name matches, RDAP shows no re-registration after the domain was recorded, the site is not on a hosting platform, and the country matches.

## Bottom line

1. **The RDAP floor cannot be applied in most destination countries as written.** IANA lists an RDAP server for only 18 of the 66 destination ccTLDs. The other 48 have none, and neither do `.edu` or `.eu`. Three more gaps sit inside ccTLDs that do have RDAP:
   - `ac.uk` names are not in Nominet's RDAP.
   - auDA (`.au`) removes the registration date from its RDAP answers.
   - `.edu` has no RDAP server at all, and it is where US universities live.

   The floor needs a fallback: port-43 WHOIS, or "unknown, so the rule leans on strong signals only". Without one, most countries fail the floor by default.
2. **WHED should be ingested first.** It is the only directory whose inclusion depends on national recognition and whose delisting follows a loss of recognition. Per-country counts are one GET each, and IAU's consent is already on file. Its coverage of degree-granting institutions is high where an official count exists to compare against:
   - Germany: 360 of 421 (86%).
   - US: 2,552 against 2,691 four-year Title IV institutions (95%).
3. **Next, ingest ROR (CC0 dump) and Wikidata (CC0) as the moderate layer.** Neither is a recognition list:
   - ROR's `education` type includes schools and research institutes.
   - Wikidata's official-website property (P856) keeps former URLs by policy.

   Use both only to corroborate a candidate that WHED or a state list already put forward. **OpenAlex is not an independent signal**: every OpenAlex institution maps to a ROR record.
4. **uniRank's inclusion rule is close to WHED's** (official recognition, at least a three-year bachelor's), but its terms bar scraping without written permission. Webometrics' site did not resolve today. Its July 2026 edition is a 1.4 MB PDF on figshare, and whether that PDF carries URLs is **Unverified**.

## 1. Inclusion criteria and curation

### WHED (IAU, with UNESCO)

- **Recognition:** required. An institution must "Be recognized and referenced by the national competent body"[^1], and institutions that lose recognition "are not listed in the WHED"[^2]. It must also be degree-conferring with at least a four-year degree and three cohorts[^1].
- **Size:** about 21,500 HEIs in 190 countries and territories[^5].
- **Curation:**
  - Data comes from national competent bodies and the ENIC-NARIC networks.
  - Each institution is sent a questionnaire "inviting them to check and update their institutional data"[^3].
  - The database is updated on a regional rotation, "focusing each year on one specific region or geographic area"[^4]. So an entry's freshness depends on its region's turn, and each entry shows its own last-update date.
- **Website field:**
  - Address and website are core fields, and an institution with no website gets no entry ("Where there is insufficient information on an institution (no website, no contact details"[^6]).
  - **Unverified:** how often the website field is stale. Nothing measured it, and the regional rotation suggests it can be several years old.
- **Absence:** means unknown, never a negative. Not recognised, not four-year, too new, delisted and not yet entered all look the same (repo note `docs/superpowers/research/2026-09-11-whed-recon.md`).

### ROR

- **Recognition:** not required. ROR includes "any organization that produces, funds, facilitates, manages, publishes, or is otherwise involved in scholarly research"[^10]. ROR says "Inclusion in ROR does not imply anything about the quality or legitimacy of this research"[^13], and its metadata "should not be interpreted as serving as the canonical authority on a given organization"[^16].
- **Curation:** central and community-fed, with "New releases are available at least once every month"[^11].
- **Website field:**
  - When a record changes, curators "verify the information against reliable public sources like the organization’s website, authority files, and national-level registries"[^14].
  - Each record carries `links[type=website]` and `domains` (measured in the API responses).
  - **Unverified:** how stale the website field is. Many records were seeded from GRID in 2018 and have not changed since, for example Iceland's `admin.created 2018-11-14`.
- **`education` is not "university".** The `types:education` query for Kuwait returned 16 records, including "American School of Kuwait"[^45], a K-12 school, and the Dasman Diabetes Institute. ROR counts are therefore upper bounds on HEIs.

### Wikidata (P856 official website; Q3918 university)

- **Recognition:** not required. Q3918 is described as "an institution of tertiary education and research which awards academic degrees in several academic disciplines"[^19]. Classification is open editing.
- **Website field:** P856's own usage note says "If a listed URL no longer points to the official website, do not remove it"[^18]. A raw P856 read can therefore return a dead or hijacked domain. Filter on preferred rank and the end-time qualifier.
- **Licence:** CC0 for all structured data[^17].

### uniRank

- **Recognition:** required. Institutions "must be officialy chartered, licensed or accredited by national or regional government bodies"[^20], authorised to grant "bachelor's degrees of at least three years' duration"[^21], and teaching mainly face-to-face.
- **Size:** "over 14,000 officially accredited and recognized universities and colleges in 200 countries"[^24].
- **Updates:** "Data and information are added or updated on a monthly basis."[^22]
- **Website field:** this is uniRank's core field, because its ranking is built from web metrics of the official domain. It does not rank sites "hosted on free global platforms such as wordpress.com, blogspot.com"[^25], which matches our hosting-platform floor.

### Webometrics (Cybermetrics Lab, CSIC)

- **Size:** "The July 2026 edition includes more than 32,000 higher education institutions (HEIs) from around the world."[^28]
- **Recognition:** whether it is required is **Unverified**. `webometrics.info` and `www.webometrics.info` both failed DNS resolution on 2026-10-03, so the methodology page could not be read.
- **Format:** the July 2026 edition is a 1.4 MB PDF on figshare. The figshare API record lists the licence as CC BY 4.0. That was measured from a JSON record with no quotable sentence, so it carries no footnote.

### OpenAlex institutions

- **Source:** "every OpenAlex institution maps to a record in the Research Organization Registry (ROR)"[^30]. Metadata "is also drawn from Crossref, PubMed, MAG, and publisher websites"[^31].
- **Website field:** `homepage_url` is "The institution’s official homepage"[^33].
- **Licence:** CC0[^32].
- **Consequence:** OpenAlex is ROR plus enrichment, so it must not count as a second moderate signal next to ROR. Its `type:education` group-by is used below as a one-call proxy for ROR's per-country counts. Spot checks against ROR: Iceland 10 vs 10, Kuwait 13 vs 16.

## 2. Coverage per country

### How each column was measured

- **WHED:** `GET https://whed.net/results_institutions.php?Chp1=<Country>&Chp0=&Chp2=&Ope0=and&Chp4=&Chp5=&nbr_ref_pge=100&debut=0&afftri=yes&stat=Country`, reading the `p.infos` line. Example: "360 results found for (Country=Germany)"[^8].
- **uniRank:** `https://www.unirank.org/<cc>/`, reading the ranking link's text. Example: "League Table and University Ranking of 353 Universities in Germany"[^26].
- **OpenAlex (≈ROR):** one call, `https://api.openalex.org/institutions?filter=type:education&group_by=country_code&per_page=200`.
- **Wikidata:** one SPARQL GET: items whose `P31` is a subclass of Q3918, grouped by `P17`'s ISO code (`P297`), with the count of those carrying `P856` in brackets. There is no dissolved-item filter, so the counts include defunct institutions.
  - **Netherlands = 1 is a query artifact, not a coverage figure.** The likely cause is a country-item mismatch (`P17` pointing to Q55 while the ISO code sits elsewhere). That cause is **Unverified**, and other countries may be affected less visibly.
- **RDAP:** whether IANA's root-zone page for the ccTLD lists an "RDAP Server", cross-checked against IANA's bootstrap file published 2026-09-30[^34].
- **Webometrics per-country counts:** not measured, because the site was unreachable.

### Table

| Country | Official national count | WHED | uniRank | OpenAlex edu (≈ROR) | Wikidata Q3918 (with P856) | ccTLD RDAP |
|---|---|---|---|---|---|---|
| Austria | | 71 | 73 | 103 | 65 (49) | no |
| Belgium | | 65 | 63 | 86 | 74 (35) | no |
| Bulgaria | | 50 | 47 | 57 | 45 (38) | no |
| Croatia | | 37 | 41 | 66 | 30 (25) | no |
| Cyprus | | 36 | 50 | 40 | 27 (24) | no |
| Czechia | | 46 | 55 | 108 | 63 (38) | yes |
| Denmark | | 34 | 26 | 61 | 40 (28) | no |
| Estonia | | 9 | 15 | 25 | 16 (11) | no |
| Finland | | 35 | 35 | 53 | 58 (42) | yes |
| France | | 551 | 230 | 513 | 376 (212) | yes[^35] |
| Germany | 421 Hochschulen, WS 2025/26[^41] | 360 (86%) | 353 (84%) | 589 | 669 (528) | no[^36] |
| Greece | | 26 | 26 | 65 | 45 (38) | no |
| Hungary | | 38 | 41 | 71 | 66 (51) | no |
| Ireland | | 47 | 23 | 48 | 68 (56) | no |
| Italy | | 107 | 86 | 245 | 332 (241) | no |
| Latvia | | 22 | 21 | 44 | 25 (18) | no |
| Lithuania | | 17 | 32 | 44 | 28 (24) | no |
| Luxembourg | | 1 | 1 | 10 | 5 (2) | no |
| Malta | | 9 | 5 | 9 | 10 (6) | no |
| Netherlands | | 69 | 55 | 132 | 1 (1) (artifact) | yes |
| Poland | | 409 | 129 | 320 | 207 (176) | yes |
| Portugal | | 90 | 82 | 332 | 64 (49) | no |
| Romania | | 76 | 72 | 109 | 95 (84) | no |
| Slovakia | | 32 | 31 | 48 | 32 (25) | no |
| Slovenia | | 42 | 29 | 64 | 12 (10) | yes |
| Spain | | 113 | 76 | 211 | 304 (186) | no |
| Sweden | | 43 | 39 | 65 | 41 (23) | no |
| Norway | | 32 | 29 | 78 | 34 (30) | yes |
| Switzerland | | 37 | 23 | 160 | 73 (56) | no |
| Iceland | | 7 | 7 | 10 (ROR 10) | 9 (9) | yes |
| United Kingdom | | 245 | 164 | 584 | 343 (250) | yes, but `ac.uk` is not in Nominet RDAP[^38] |
| Saudi Arabia | | 71 | 63 | 62 | 69 (49) | no |
| UAE | | 54 | 54 | 64 | 60 (49) | no |
| Qatar | | 4 | 13 | 31 | 11 (10) | no |
| Kuwait | | 12 | 5 | 13 (ROR 16) | 10 (10) | no |
| Bahrain | | 13 | 11 | 13 | 16 (15) | yes |
| Australia | 220 TEQSA providers, 44 universities[^42] | 90[^44] | 39[^43] | 139 | 83 (67) | yes, but registration date redacted[^39] |
| New Zealand | | 35 | 8 | 38 | 28 (23) | no |
| Singapore | | 9 | 8 | 115 | 39 (30) | yes |
| Brunei | | 4 | 4 | 14 | 7 (7) | no |
| Serbia | | 16 | 22 | 36 | 45 (41) | no |
| Türkiye | | 178 | 174 | 219 | 253 (229) | no |
| China | | 1,065 | 939 | 3,175 | 859 (725) | no |
| Japan | | 753 | 781 | 1,574 | 1,647 (1,170) | no |
| South Korea | | 249 | 186 | 369 | 399 (332) | yes |
| Russia | | 603 | 366 | 834 | 467 (430) | no |
| Vietnam | | 176 | 78 | 243 | 189 (136) | no |
| Armenia | | 58 | 39 | 20 | 39 (31) | no |
| Azerbaijan | | 45 | 39 | 50 | 70 (48) | no |
| Georgia | | 48 | 47 | 58 | 52 (40) | no |
| Kazakhstan | | 111 | 102 | 89 | 93 (75) | no |
| United States | 2,691 four-year Title IV, 2023–24[^40] | 2,552 (95%)[^9] | 1,704 (63%)[^27] | 4,429 | 2,597 (2,185) | no for `.us`, and none for `.edu`[^37] |
| Canada | | 151 | 101 | 386 | 274 (231) | yes |
| Mexico | | 1,386 | 540 | 564 | 388 (313) | no |
| Brazil | | 1,448 | 203 | 518 | 395 (353) | yes |
| Argentina | | 132 | 126 | 156 | 178 (140) | yes |
| Chile | | 62 | 55 | 96 | 101 (69) | no |
| Colombia | | 283 | 207 | 218 | 170 (146) | no |
| Peru | | 98 | 118 | 108 | 137 (127) | no |
| South Africa | | 71 | 25 | 71 | 75 (50) | no |
| Nigeria | | 175 | 165 | 273 | 544 (436) | yes |
| Kenya | | 76 | 69 | 82 | 96 (83) | yes |
| Egypt | | 221 | 60 | 117 | 142 (107) | no |
| Morocco | | 124 | 37 | 102 | 56 (48) | no |
| Ghana | | 134 | 68 | 74 | 87 (73) | no |
| Ethiopia | | 74 | 51 | 55 | 62 (51) | no |

### How to read the table

- **Coverage share is computable only where an official count was fetched:** Germany, the US and Australia.
  - In Germany and the US, WHED and uniRank sit at or below the official count.
  - OpenAlex/ROR and Wikidata exceed it, because they include non-HEIs (schools, research institutes) and, in Wikidata's case, defunct ones.
  - A larger ROR or Wikidata count does not mean better coverage of recognised universities.
- **Australia shows that "recognised" depends on the list's own threshold.** TEQSA registers 44 universities among 220 providers[^42]. WHED lists 90 and uniRank 39.
- **Official counts for the other 63 countries were not fetched** (step budget), so their coverage share is **Unverified**.

## 3. Access and terms

| Source | Access | Terms |
|---|---|---|
| WHED | Per-country GET (above). Each institution has a stable `whed.net/institutions/IAU-xxxxxx` page carrying the website. No bulk export without MyWHED. | "The copying of all or substantial parts of the Portal is not allowed without prior consent of IAU."[^7] IAU gave consent by e-mail on 2026-09-11: "You can scrape and access without any problem". It does not name storage or commercial use (repo `docs/superpowers/research/2026-09-11-whed-recon.md`). |
| ROR | Monthly CC0 dump on Zenodo, plus the REST API. The dump includes inactive and withdrawn records[^15]. | "All ROR IDs and metadata are provided under the Creative Commons CC0 1.0 Universal Public Domain Dedication."[^12] |
| Wikidata | SPARQL GET endpoint (measured working with a grouped query), plus dumps. | CC0[^17] |
| OpenAlex | Free API with a key, plus snapshot. | CC0[^32] |
| uniRank | Country pages as plain HTML (measured). | "you may not scrape or republish data or information about universities on the Site without our prior written permission"[^23]. The owner decided on 2026-09-27 that a source site's terms do not gate a fetch (memory `scraping-terms-not-a-blocker.md`), so this is recorded, not a blocker. |
| Webometrics | July 2026 edition as a figshare PDF. The site was unreachable on 2026-10-03. | CC BY 4.0 per the figshare API record (measured, not quotable). |

## 4. RDAP per ccTLD

These were read from IANA's root-zone pages, each of which shows an "RDAP Server" line when one exists (for example, France: "WHOIS Server: whois.nic.fr RDAP Server: https://rdap.nic.fr/"[^35]). They were cross-checked against the bootstrap file published 2026-09-30[^34].

### ccTLDs with RDAP (18)

`cz fi fr nl pl si no is uk bh au sg kr ca br ar ng ke`

### ccTLDs without RDAP (48, plus `eu`)

`at be bg hr cy dk ee de gr hu ie it lv lt lu mt pt ro sk es se ch sa ae qa kw nz bn rs tr cn jp ru vn am az ge kz us mx cl co pe za eg ma gh et`, and `eu`.

`.edu`, where US universities live, has no RDAP server on its IANA page[^37].

### Whether registration dates come back (measured 2026-10-03, one domain per registry)

| Registry | Domain queried | Result |
|---|---|---|
| `rdap.nic.fr` | `unistra.fr` | Returns a `registration` event (2007-07-24). |
| `rdap.sidn.nl` | `uva.nl` | Returns `registration` (1988-10-12). |
| `rdap.registro.br` | `usp.br` | Returns `registration` (1996-01-01), plus the registrant's CNPJ tax ID. |
| `rdap.cctld.au` | `unimelb.edu.au` | Redacts the "Registry Domain Registration Date"[^39]. It does return `eligibility type: Higher Education Institution` and `eligibility id: TEQSA PRV12150`, which makes the `edu.au` registry record itself close to a state-list signal. |
| `rdap.nominet.uk` | `ox.ac.uk` | "Domain ox.ac.uk not found"[^38]. `ac.uk` is run outside Nominet, so the `.uk` RDAP server does not cover UK universities. |

The other 13 RDAP ccTLDs were not sampled. Whether they return registration dates is **Unverified**.

## Ranked ingestion order

1. **WHED.** It is the strong signal and the recognition filter, and it covers the widest set of countries among the recognition-gated lists. It is also the only list that removes institutions when recognition ends[^2].
2. **State lists where they carry URLs or registry-level proof.** TEQSA for Australia is already reachable through the `edu.au` RDAP eligibility ID[^39]. The planned Korean data.go.kr and EACEA sources follow the same pattern. Which other national lists carry website URLs is **Unverified**.
3. **ROR dump.** It is CC0, monthly, carries `links.website` and `domains`, and has a Wikidata crosswalk. Use it as a moderate corroborator only, because `education` is not recognition[^45].
4. **Wikidata.** Use P856 with preferred rank and without an end time, because stale URLs are kept by policy[^18]. Treat it as partly correlated with ROR (ROR records carry Wikidata IDs). Whether the two websites are independently sourced is **Unverified**.
5. **uniRank.** Its criteria are close to WHED's[^20][^21] and it already excludes hosting-platform sites[^25]. Terms are noted above.
6. **Webometrics, last.** It was unreachable today, and its PDF's URL content is unverified.

**OpenAlex should not be ingested as a separate signal.** It derives from ROR[^30].

## Countries where fewer than two moderate signals will typically exist

### Why the RDAP signal is missing in most of these countries

- **RDAP is unavailable for 48 of the 66 ccTLDs.** There, the moderate set shrinks to ROR, Wikidata, uniRank, Webometrics and the ccTLD match.
- **The floor's "no re-registration" check cannot run at all** in those countries, for `.edu`, for `ac.uk`, or for `.au` (where the registration date is redacted).

### Where to lean on strong signals only

This list is inferred from the directory gaps in the table: many WHED institutions there are likely to have at most one of uniRank, ROR or Wikidata. It is not a measured per-institution join.

- **Mexico, Brazil, Poland, Egypt, Morocco, Ghana, Vietnam, Armenia, and the long tail of France.** WHED lists far more institutions than uniRank, OpenAlex or Wikidata:
  - Mexico: 1,386 vs 540 / 564 / 388.
  - Brazil: 1,448 vs 203 / 518 / 395.
  - Poland: 409 vs 129 / 320 / 207.
  - Egypt: 221 vs 60 / 117 / 142.
  - Morocco: 124 vs 37 / 102 / 56.
  - Ghana: 134 vs 68 / 74 / 87.
  - Vietnam: 176 vs 78 / 243 / 189.
  - Armenia: 58 vs 39 / 20 / 39.
  - France: 551 vs 230 / 513 / 376.

  Of these, only Brazil and Poland have RDAP. Expect many institutions with at most one directory signal.
- **United States.** Universities use `.edu`, so there is no ccTLD match and no RDAP. Only the four directory signals remain. WHED covers 95% of four-year institutions, so lean on WHED (or IPEDS, which is **Unverified** as a URL source).
- **Gulf states (Qatar, Kuwait, Bahrain, Saudi Arabia, UAE) and Brunei.** Counts are small and uniRank is thin (Kuwait 5 vs WHED 12), and none has RDAP except Bahrain.
- **The ccTLD match will nearly always be present elsewhere,** so "ccTLD + one directory" will pass the two-moderate bar by default. Whether ccTLD match should count as a full moderate signal is a design question this research raises but does not settle.

## Sources and tools

- **Source of the directory list:** the caller named the six directories. No discovery search was needed.
- **Searches used:**
  - Exa: ROR scope; OpenAlex licence; Webometrics 2026 edition on figshare; NCES, Destatis, TEQSA and YÖK counts.
  - Brave: Webometrics methodology.
- **Pages:** fetched with scrapling. WebFetch was used once, to scan the 52 KB RDAP bootstrap JSON; its output was then re-verified page by page on iana.org.
- **Missing or unused:**
  - Tavily was not used.
  - Context7 does not apply.
  - `webometrics.info` failed DNS resolution.
  - YÖK's university count was not found on a quotable page.
- **Measured but not footnoted:** ROR, OpenAlex, Wikidata and RDAP JSON values come from query URLs that return JSON with no quotable sentence. The URLs are given inline.

## Sources

[^1]: https://whed.net/About.html "Be recognized and referenced by the national competent body"
[^2]: https://whed.net/About.html "but are no longer recognized, are not listed in the WHED"
[^3]: https://whed.net/About.html "inviting them to check and update their institutional data"
[^4]: https://whed.net/About.html "on an ongoing basis focusing each year on one specific region or geographic area"
[^5]: https://whed.net/About.html "higher education institutions (HEIs) in 190 countries and territories"
[^6]: https://whed.net/About.html "Where there is insufficient information on an institution (no website, no contact details"
[^7]: https://whed.net/Terms_of_use.html "The copying of all or substantial parts of the Portal is not allowed without prior consent of IAU."
[^8]: https://whed.net/results_institutions.php?Chp1=Germany&Chp0=&Chp2=&Ope0=and&Chp4=&Chp5=&nbr_ref_pge=100&debut=0&afftri=yes&stat=Country "360 results found for (Country=Germany)"
[^9]: https://whed.net/results_institutions.php?Chp1=United%20States%20of%20America&Chp0=&Chp2=&Ope0=and&Chp4=&Chp5=&nbr_ref_pge=100&debut=0&afftri=yes&stat=Country "2552 results found for (Country=United States of America)"
[^10]: https://ror.org/registry/ "any organization that produces, funds, facilitates, manages, publishes, or is otherwise involved in scholarly research."
[^11]: https://ror.org/registry/ "New releases are available at least once every month"
[^12]: https://ror.org/registry/ "All ROR IDs and metadata are provided under the Creative Commons CC0 1.0 Universal Public Domain Dedication."
[^13]: https://ror.org/blog/2022-08-31-name-metadata-in-ror/ "Inclusion in ROR does not imply anything about the quality or legitimacy of this research."
[^14]: https://ror.org/blog/2025-10-08-journey-of-a-curation-request/ "we verify the information against reliable public sources like the organization’s website, authority files, and national-level registries"
[^15]: https://ror.readme.io/docs/data-dump "the data dump contains all records with all statuses (active, inactive, withdrawn)"
[^16]: https://ror.org/blog/2022-08-31-name-metadata-in-ror/ "ROR metadata should not be interpreted as serving as the canonical authority on a given organization."
[^17]: https://www.wikidata.org/wiki/Wikidata:Licensing "is released into the public domain under Creative Commons Zero"
[^18]: https://www.wikidata.org/wiki/Property:P856 "If a listed URL no longer points to the official website, do not remove it"
[^19]: https://www.wikidata.org/wiki/Q3918 "an institution of tertiary education and research which awards academic degrees in several academic disciplines"
[^20]: https://www.unirank.org/about/ "institutions must be officialy chartered, licensed or accredited by national or regional government bodies"
[^21]: https://www.unirank.org/about/ "they must be authorised to grant bachelor's degrees of at least three years' duration"
[^22]: https://www.unirank.org/about/ "Data and information are added or updated on a monthly basis."
[^23]: https://www.unirank.org/terms/ "you may not scrape or republish data or information about universities on the Site without our prior written permission"
[^24]: https://www.unirank.org/about/ "reviews and rankings of over 14,000 officially accredited and recognized universities and colleges in 200 countries"
[^25]: https://www.unirank.org/about/ "official website is hosted on free global platforms such as wordpress.com, blogspot.com"
[^26]: https://www.unirank.org/de/ "League Table and University Ranking of 353 Universities in Germany"
[^27]: https://www.unirank.org/us/ "League Table and University Ranking of 1704 Universities in the United States"
[^28]: https://api.figshare.com/v2/articles/33062150 "The July 2026 edition includes more than 32,000 higher education institutions (HEIs) from around the world."
[^30]: https://help.openalex.org/data/institutions/ "every OpenAlex institution maps to a record in the Research Organization Registry (ROR)"
[^31]: https://help.openalex.org/data/institutions/ "Institution metadata is also drawn from Crossref, PubMed, MAG, and publisher websites."
[^32]: https://help.openalex.org/access/pricing/ "released under a CC0 public-domain license"
[^33]: https://help.openalex.org/data/institutions/ "The institution’s official homepage."
[^34]: https://data.iana.org/rdap/dns.json "RDAP bootstrap file for Domain Name System registrations"
[^35]: https://www.iana.org/domains/root/db/fr.html "WHOIS Server: whois.nic.fr RDAP Server: https://rdap.nic.fr/"
[^36]: https://www.iana.org/domains/root/db/de.html "URL for registration services: http://www.denic.de/ WHOIS Server: whois.denic.de"
[^37]: https://www.iana.org/domains/root/db/edu.html "URL for registration services: http://www.educause.edu/edudomain WHOIS Server: whois.educause.edu"
[^38]: https://rdap.nominet.uk/uk/domain/ox.ac.uk "Domain ox.ac.uk not found"
[^39]: https://rdap.cctld.au/rdap/domain/unimelb.edu.au "Registry Domain Registration Date"
[^40]: https://nces.ed.gov/learn/press-release/total-number-higher-education-institutions-decreases-2-percent "2,691 were classified as 4-year institutions"
[^41]: https://www.destatis.de/DE/Themen/Gesellschaft-Umwelt/Bildung-Forschung-Kultur/Hochschulen/Tabellen/hochschulen-hochschularten.html "Hochschulen insgesamt 428 422 421"
[^42]: https://www.teqsa.gov.au/national-register "Total providers 75 145 220"
[^43]: https://www.unirank.org/au/ "League Table and University Ranking of 39 Universities in Australia"
[^44]: https://whed.net/results_institutions.php?Chp1=Australia&Chp0=&Chp2=&Ope0=and&Chp4=&Chp5=&nbr_ref_pge=100&debut=0&afftri=yes&stat=Country "90 results found for (Country=Australia)"
[^45]: https://api.ror.org/v2/organizations?filter=types:education,locations.geonames_details.country_code:KW "American School of Kuwait"

## Open questions

- **Website staleness, per directory:** unmeasured. Measure it by sampling about 50 institutions per directory and checking that the URL resolves to a site naming the institution.
- **Webometrics:**
  - its inclusion criteria;
  - whether the July 2026 PDF carries URLs;
  - whether `webometrics.info` is down temporarily or for good.
- **Official national HE counts** for the 63 countries other than Germany, the US and Australia.
- **Registration dates on the other RDAP servers:** whether the 13 unsampled ccTLD registries return them, and whether `.com`/`.org` university domains need the gTLD RDAP path.
- **The Wikidata Netherlands = 1 artifact:** its cause, and whether other countries' counts are depressed the same way.
- **How independent ROR's and Wikidata's website fields are.** If they are correlated, "two moderate" can be one source counted twice.
- **WHED scope:** whether IAU's consent covers storage and commercial use. This is carried over from the 2026-09-11 recon.
