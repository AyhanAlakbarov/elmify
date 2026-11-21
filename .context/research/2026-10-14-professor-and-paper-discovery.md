# Professor and paper discovery for the letter engine: what decides the design

Date: 2026-10-14. Design under review: `docs/superpowers/specs/2026-09-28-one-letter-engine-design.md`
§3.3–3.4 (branch `claude/letter-gap-fixes`, read from the `letter-shape` worktree).

## Scope (the questions actually answered)

1. **Q1a** What share of recent works in OpenAlex has an abstract, which publishers are missing, and is
   there a better fallback (Crossref, Semantic Scholar, OpenAlex's own full text)?
2. **Q1b** How `last_known_institutions` / `affiliations` are derived, how wrong they are, and how much
   ORCID helps.
3. **Q1c** Which filters exist now for works by institution + title/abstract search + date, and for
   authors by institution; what they cost.
4. **Q2** OpenAlex volume and abstract share for the eight named countries, and whether each named
   national index has a usable API.
5. **Q3** Whether taught-master's module pages name a responsible teacher, and whether official
   admissions guidance for taught master's recommends naming staff.
6. **Q4** (brief) Evidence on picking the matching paper and on byline position as "group lead".

Tools: Exa, Brave, scrapling (`get`/`bulk_get`) were used; every quote below was copied from a scrapling
fetch. Tavily and Context7 were available but not needed. The Q2 candidate list was given by the
requester; each named index was then looked up with Exa restricted to the index owner's domain
(`support.nii.ac.jp`, `researchmap.jp`, `kci.go.kr`, `data.go.kr`, `dergipark.org.tr`, `trdizin.gov.tr`,
`api.archives-ouvertes.fr`, `elibrary.ru`). No search was run for German, Kazakh or Azerbaijani national
indexes (see Open questions).

## The answer, in short

The two-direction design (site + OpenAlex, confirmed on the site) is sound. Six facts change its details:

1. **The planned OpenAlex filter is deprecated.** `filter=...title_and_abstract.search:` still works, but
   the documented form is the `search.title_and_abstract=` parameter. Both are billed as searches:
   $1 per 1,000 calls, so the spec's "$0.001 each" is right.[^3][^4][^5]
2. **About one recent Elsevier article in three has an abstract in OpenAlex (measured: 33%), and about one
   Springer Nature article in two (50%).** Overall, 80% of 2023–2025 articles have one (measured). Crossref
   is no fallback for Elsevier (0.07% of 2023–2025 Elsevier articles carry an abstract there; measured).
   So "Jev reads title + abstract" silently skips the newest Elsevier/Springer papers. Either the
   selection step accepts title-only papers (with a lower bar), or it reads OpenAlex's own cached
   full text.[^8][^9][^10]
3. **OpenAlex already holds parsed full text (GROBID TEI XML) for about 43M open-access works**, so the
   OA conclusion can come from `content.openalex.org` at $10 per 1,000 downloads (1¢ each), with sections
   already split. That avoids a vendor fetch of `best_oa_location`. GROBID output contains errors,
   so the code must check what it parsed.[^11][^12][^13]
4. **`last_known_institutions` is simply the affiliation on the author's most recent indexed work.** A
   move shows only after the first paper with the new affiliation is indexed. An audit found
   institution-level affiliation timelines in OpenAlex about 62% accurate, and only about 29% of the
   moves it reported had both ends correct. The spec's rule that the university site must confirm each
   candidate is necessary.[^14][^23][^24]
5. **The admitting unit cannot be checked through ROR in most cases.** A department with no ROR record
   matches only its parent university. Department text is still searchable in `raw_affiliation_strings`.
   This is a cheap pre-filter before the site check.[^26][^27]
6. **"Last or corresponding author = group lead" is a heuristic, not a fact.** `author_position` follows
   the order of names on the paper, not seniority. Mathematics, economics and high-energy physics often
   list authors alphabetically. Prefer `is_corresponding`, and in those fields turn off the
   last-author rule.[^21][^22][^53]

For taught master's, the evidence supports the spec's secondary device: UK module pages name a module
leader, and official taught-master's guidance (Sussex, Imperial) recommends naming a professor or a
research group.[^44][^48][^50]

## Q1a — Abstract coverage and fallbacks

- OpenAlex stores abstracts only as an inverted index "for legal reasons"[^6]. Its own docs say newer
  works are more likely to have one ("over 60% of 2022 works")[^7].
- Takedowns: OpenAlex removed abstracts of Springer Nature's non-OA content in November 2022, and Elsevier
  had closed-article abstracts removed in November 2024[^8][^9]. Before that takedown, OpenAlex had abstracts
  for publishers that deposit none in Crossref (Elsevier, IEEE, ACS, Taylor & Francis), obtained partly
  by web scraping[^10].
- **Measured 2026-10-14** (OpenAlex API, `type:article`, `publication_year:2023-2025`):

  | Set | with abstract / all | share |
  |---|---|---|
  | All articles | 15,819,377 / 19,798,562 | 79.9% |
  | Elsevier BV (P4310320990) | 879,597 / 2,629,432 | 33.5% |
  | Springer Nature (P4310319965) | 745,624 / 1,502,477 | 49.6% |

  Crossref, same years, `type:journal-article`: Elsevier (member 78) 1,977 / 2,850,858 = 0.07%;
  Springer Nature (member 297) 469,863 / 1,581,851 = 29.7%. Kramer's 2024 figures agree in direction
  ("48% vs 34%" for Springer Nature, OpenAlex vs Crossref).[^8b]
  Note: `group_by=has_abstract` returned `false: 0` for this set, which contradicts the
  `has_abstract:false` filter (3,979,185). Count with filters, not that group_by.
- **Fallbacks, in order of evidence:**
  1. OpenAlex cached full text: more than 50M OA works as PDF, about 43M as TEI XML; downloads need a key
     (a free key works) and are metered at $10 per 1,000[^11][^12]. GROBID cannot parse every PDF and makes
     errors[^13].
  2. Crossref: useless for Elsevier, worse than OpenAlex for Springer Nature (measured above).
  3. Semantic Scholar API: needs a key for useful rates ("1 RPS on all endpoints" with an introductory
     key)[^55]. Its abstract coverage for Elsevier/Springer after the takedowns is **Unverified**: the API's
     schema page returned HTTP 429 to this run.
  4. Publisher landing pages: **Unverified** (not tested; ScienceDirect commonly blocks automated fetches).
- Retractions: `is_retracted` comes from Retraction Watch, so the spec's exclusion has a source[^59].

## Q1b — Affiliation freshness and ORCID

- An author profile is a set of works, and its other fields are computed from those works[^16].
  `last_known_institutions` comes "from the author's most recent work"[^14]. So the lag is the time until
  the first paper with the new affiliation is published and indexed. **No source found gives that lag
  in months (Unverified).**
- Disambiguation fails by splitting and by merging ("works from different people collapsed into one
  profile")[^20].
- Independent audit (NeurIPS 2020 cohort, Scientometrics 2026): institution-level affiliation accuracy
  about 0.62 in OpenAlex vs 0.70 in Scopus[^23]. Only about 29% of the institution moves it reported had
  both endpoints right[^24].
- The affiliation matcher (v3.0, 28 Sep 2026) names exactly the right institutions for 89% of sampled
  strings[^25]. A department without a ROR record can only match its parent[^26].
- ORCID: OpenAlex gets an ORCID only when a publisher deposits it with a work[^18]. 47% of works from 2023
  on have at least one ORCID author[^17]. OpenAlex itself says to treat a shared ORCID "as a strong hint
  rather than proof"[^19]. So ORCID can confirm a match when present, but cannot be required.

## Q1c — Filters and price now

- Works by institution: `authorships.institutions.id` / `.ror` / `.lineage` ("works affiliated with an
  institution (or its lineage, country, or type)")[^28]; corresponding status: `authorships.is_corresponding`[^22].
- Title/abstract search: the scoped parameters `search.title_and_abstract` and
  `search.title_abstract_keywords`[^5]. The keyword variant also finds "papers in other languages, and
  papers with no abstract"[^5b], which matters for Q2. The old `filter=...search:` form is deprecated[^4].
- Department text: `raw_affiliation_strings.search` "returns works whose authors printed that
  affiliation text"[^27].
- Semantic search exists (`search.semantic`). It embeds title and abstract, so a work with no abstract is
  matched on title alone (inference), and it returns at most 50 results per query[^29][^30].
- Price: list+filter $0.10 per 1,000; search $1 per 1,000[^3]. Every account gets $1 a day free[^2]. Keyless
  use gets $0.10 a day[^1]. A free key "raises your daily budget 10×"[^57]. Cached full text costs $10 per
  1,000 downloads[^12].

## Q2 — Non-English-language countries

**Measured 2026-10-14** (OpenAlex, articles 2023–2025 with at least one author from the country):

| Country | articles | with abstract | share |
|---|---|---|---|
| Turkey | 389,351 | 332,686 | 85.4% |
| Russia | 453,559 | 408,953 | 90.2% |
| Azerbaijan | 22,224 | 19,238 | 86.6% |
| Kazakhstan | 46,267 | 43,757 | 94.6% |
| South Korea | 298,563 | 225,486 | 75.5% |
| Japan | 438,501 | 342,953 | 78.2% |
| Germany | 516,196 | 442,203 | 85.7% |
| France | 388,175 | 298,980 | 77.0% |

These counts show what OpenAlex holds. They do not show what it misses relative to a national index.
OpenAlex's language coverage is "far more balanced" than WoS, but its language field overstates English
and understates other languages[^33][^32]. So filtering by `language` would drop national-language papers.

National indexes (one line each):

- **Japan — CiNii Research / KAKEN:** API yes, with an application ID from free registration; the same ID
  unlocks the KAKEN API, which includes a researcher search[^35][^34]. Terms: commercial use requires mailing
  NII before applying[^36].
- **Japan — researchmap:** the application form (PDF) indicates institutional applicants only, with
  IP-locked keys. **Unverified:** the only source is a PDF.
- **South Korea — KCI:** Open API yes, with an issued key[^37][^38]. Search parameters include author
  affiliation and abstract[^39]. Terms: **Unverified**.
- **Turkey — TR Dizin:** every search page is also available as raw JSON (`search.trdizin.gov.tr/api/...`)
  with no key mentioned[^40]. Terms: **Unverified**. **DergiPark:** journal pages say they publish over
  OAI-PMH through DergiPark (Exa snippet only; **Unverified**).
- **France — HAL:** public Solr search API (`api.archives-ouvertes.fr/search/`)[^41]; no key on the docs
  page. Terms: **Unverified**.
- **Russia — eLibrary.ru:** no public API found. The SCIENCE INDEX organisation service exports an
  organisation's publication list as XML for subscribed organisations (PDF manual; **Unverified**).
- **Germany, Kazakhstan, Azerbaijan:** no national index searched in this run. **Unverified.** German
  universities publish module and staff data per institution (Q3).

## Q3 — Taught master's: teaching staff, not researchers

- UK: UCL's catalogue defines "A Module Leader is responsible for the overall organisation, management and
  assessment of a module"[^44] and names one on each module page (e.g. MATH0086, taken by MSc students)[^45].
- Germany: module descriptions carry a responsible person (Oldenburg: "Zuständige Personen
  Modulverantwortung: Mareike Witkowski")[^46]. The same page shows why handbooks go stale: "Das Modul wird
  bis einschließlich Sommersemester 2026 angeboten"[^47]. In the search for German examples, 6 of 7 results
  were PDF handbooks (KIT, Freiburg, HKA, UniBw, Mannheim, Kempten). TUM's handbooks list both
  "Modulverantwortliche(r)" and "Dozent(in)" (search snippet; **Unverified**). So the module leader and the
  lecturer can be different people.
- Admissions guidance for taught master's:
  - Sussex (Masters personal statement) tells applicants to avoid "I was inspired by the University's
    world-renowned researchers and world-leading facilities"[^49]. Its model sentence names a professor and his
    work[^48].
  - Imperial (postgraduate taught): "Are there particular facilities or research groups you're interested
    in?"[^50].
  - Essex, Manchester careers and Reading careers say similar things (Exa snippets only; **Unverified**).
  - No official guidance found that tells taught-master's applicants **not** to name staff, outside the
    Fulbright rule already in the spec.
  - No German-language admissions guidance was searched.

## Q4 — Picking the paper; byline position (brief)

- OpenAlex `author_position` "tracks the printed sequence rather than any notion of credit or
  seniority"[^21].
- In 119 Annals of Internal Medicine papers, the last author was most involved in funding, revision,
  design and support[^51]. The same study says role profiles "do not strictly correspond to byline
  position"[^52].
- Alphabetical author order is most common in mathematics, economics and high-energy physics[^53]. There the
  last-author rule picks by surname.
- Relevance: SPECTER (citation-trained document embeddings) is the published baseline for
  paper-to-paper relatedness[^54]. OpenAlex's semantic search embeds title and abstract the same way for all
  works[^29].
- No published method was found for "which of a professor's papers best matches an applicant". The spec's
  rule (the most recent paper above a relevance bar, ties broken by topic overlap) is a design choice,
  not evidence-based. **Unverified.**

## What this changes in §3.3–3.4 (for the reader to decide)

1. Use `search.title_and_abstract` (or `search.title_abstract_keywords`, to reach non-English and
   abstract-less papers), not the deprecated filter.
2. In paper selection, treat "no abstract" as its own state. Then either read title + GROBID TEI
   (`has_content.grobid_xml:true`, 1¢ each) or judge on the title alone with a stricter bar. Do not let a
   missing abstract read as "not about the topic".
3. Get the conclusion from OpenAlex TEI XML before fetching `best_oa_location` through a vendor.
4. Add `raw_affiliation_strings.search:"<department name>"` as a pre-filter for the admitting unit. Keep
   site confirmation mandatory.
5. Group lead: prefer `is_corresponding`; in maths/economics/HEP, drop the last-author rule.
6. Production needs an API key: keyless use gets $0.10 a day.

## Measurement URLs (run 2026-10-14, keyless, $0.0001 each)

- `https://api.openalex.org/works?filter=publication_year:2023-2025,type:article,has_abstract:true&per_page=1&select=id`
  (and `has_abstract:false`)
- `https://api.openalex.org/works?filter=publication_year:2023-2025,type:article,primary_location.source.publisher_lineage:P4310320990[,has_abstract:true]&per_page=1&select=id`
  (Elsevier; `P4310319965` for Springer Nature)
- `https://api.openalex.org/works?filter=publication_year:2023-2025,type:article[,has_abstract:true],authorships.countries:TR|RU|AZ|KZ|KR|JP|DE|FR|US|GB&group_by=authorships.countries`
- `https://api.crossref.org/members/78/works?filter=from-pub-date:2023-01-01,until-pub-date:2025-12-31,type:journal-article[,has-abstract:true]&rows=0`
  (member 297 for Springer Nature)

## Sources

[^1]: https://help.openalex.org/access/example-costs/ "Without a key you get $0.10/day — a tenth of the above, enough to try the API."
[^2]: https://help.openalex.org/access/example-costs/ "Every account gets $1 of usage per day for free"
[^3]: https://help.openalex.org/api/searching.md "These filter-based searches cost the same $1 per 1,000 requests."
[^4]: https://help.openalex.org/api/searching.md "syntax still works but is no longer recommended"
[^5]: https://help.openalex.org/api/searching.md "Works also take scoped search parameters"
[^5b]: https://help.openalex.org/api/searching.md "papers in other languages, and papers with no abstract"
[^6]: https://help.openalex.org/data/works/attributes.md "OpenAlex does not ship plaintext abstracts for legal reasons; reconstruct the abstract from the index."
[^7]: https://help.openalex.org/data/works/attributes.md "Newer works are more likely to have one (over 60% of 2022 works vs. ~45% of pre-2000 works)."
[^8]: https://bmkramer.github.io/SesameOpenScience_site/thought/202411_open_abstracts/ "In November 2022, OpenAlex took the step to remove abstracts for Springer Nature’s non-open access content"
[^8b]: https://bmkramer.github.io/SesameOpenScience_site/thought/202411_open_abstracts/ "OpenAlex still has more abstracts for Springer Nature than Crossref (48% vs 34%)."
[^9]: https://bmkramer.github.io/SesameOpenScience_site/thought/202411_open_abstracts/ "Elsevier seems to have taken similar steps to have abstracts from closed articles removed from OpenAlex"
[^10]: https://bmkramer.github.io/SesameOpenScience_site/thought/202411_open_abstracts/ "This includes many of the larger publishers that do not (yet) deposit abstracts to Crossref at all, like Elsevier, IEEE, ACS and Taylor & Francis."
[^11]: https://help.openalex.org/access/fulltext.md "OpenAlex keeps its own cached copy of the full text for more than 50 million open-access works"
[^12]: https://help.openalex.org/access/example-costs/ "Cached PDF via the content API $10"
[^13]: https://help.openalex.org/access/fulltext.md "GROBID also can't parse every PDF."
[^14]: https://help.openalex.org/data/authors.md "from the author's most recent work"
[^16]: https://help.openalex.org/data/authors.md "a profile is a set of works, and almost everything else on it is computed from those works"
[^17]: https://help.openalex.org/data/authors/orcid.md "2023 onward | about 4 in 10 | 47%"
[^18]: https://help.openalex.org/data/authors/orcid.md "A researcher who has an ORCID but never gave it to a publisher is invisible on this axis"
[^19]: https://help.openalex.org/data/authors/orcid.md "treat a shared ORCID as a strong hint rather than proof"
[^20]: https://help.openalex.org/data/authors/disambiguation.md "works from different people collapsed into one profile"
[^21]: https://help.openalex.org/data/authorships.md "Derived from byline order, so it tracks the printed sequence rather than any notion of credit or seniority."
[^22]: https://help.openalex.org/data/authorships.md "True if this author is marked as a corresponding author on the work."
[^23]: https://link.springer.com/article/10.1007/s11192-026-05689-9 "average author-weighted affiliation accuracy is about 0.62 versus 0.75 in OpenAlex"
[^24]: https://link.springer.com/article/10.1007/s11192-026-05689-9 "positive predictive value is about 0.29 in OpenAlex and 0.45 in Scopus at institutions"
[^25]: https://help.openalex.org/data/raw-affiliation-strings.md "It names exactly the right institutions for 89% of a random sample of OpenAlex strings"
[^26]: https://help.openalex.org/data/raw-affiliation-strings.md "where a sub-unit has no ROR record, a string can only match its parent"
[^27]: https://help.openalex.org/data/raw-affiliation-strings.md "returns works whose authors printed that affiliation text"
[^28]: https://help.openalex.org/data/authorships.md "works affiliated with an institution (or its lineage, country, or type)"
[^29]: https://help.openalex.org/api/semantic-search.md "embeds the title and abstract of every work"
[^30]: https://help.openalex.org/api/semantic-search.md "Max results | 50 per query"
[^32]: https://arxiv.org/abs/2409.10633 "language metadata is not always accurate, which leads OpenAlex to overestimate the place of English while underestimating that of other languages"
[^33]: https://arxiv.org/abs/2409.10633 "OpenAlex exhibits a far more balanced linguistic coverage than WoS"
[^34]: https://support.nii.ac.jp/en/cinii/api/developer "the obtained Application ID will be required for using KAKEN API as well"
[^35]: https://support.nii.ac.jp/en/cinii/api/developer "If you want to use APIs like OpenSearch or RDF, please register through the following form and obtain the application ID."
[^36]: https://support.nii.ac.jp/en/cinii/api/developer "If you want to use CiNii at a commercial site or for other purposes, please mail to"
[^37]: https://www.kci.go.kr/kciportal/po/openapi/openDataView.kci?datasetBean.dtstSeqNo=1 "OPEN API를 이용한 논문 기본정보 제공"
[^38]: https://www.kci.go.kr/kciportal/po/openapi/openDataView.kci?datasetBean.dtstSeqNo=1 "입력한 인증키 값이 유효하지 않음"
[^39]: https://www.kci.go.kr/kciportal/po/openapi/openDataView.kci?datasetBean.dtstSeqNo=1 "논문의 초록 (UTF-8 인코딩)"
[^40]: https://development.trdizin.gov.tr/ "TR Dizin, arayüzden ulaşılan tüm verilere api gibi raw data olarakta erişilme imkanını sağlamaktadır."
[^41]: https://api.archives-ouvertes.fr/docs/search "Point d'entrée de l'API de recherche HAL"
[^44]: https://www.ucl.ac.uk/module-catalogue/glossary-terminology "A Module Leader is responsible for the overall organisation, management and assessment of a module"
[^45]: https://www.ucl.ac.uk/module-catalogue/modules/computational-and-simulation-methods-MATH0086 "students on the MSc in Mathematics or Mathematical Modelling or Scientific Computing"
[^46]: https://elearning.uni-oldenburg.de/dispatch.php/shared/modul/description/8cf2dc00e2f7e9123798305b7ac575bc "Zuständige Personen Modulverantwortung: Mareike Witkowski"
[^47]: https://elearning.uni-oldenburg.de/dispatch.php/shared/modul/description/8cf2dc00e2f7e9123798305b7ac575bc "Das Modul wird bis einschließlich Sommersemester 2026 angeboten"
[^48]: https://www.sussex.ac.uk/study/masters/apply/tips-for-masters/personal-statement "I was inspired to study Animal Biology because of the groundbreaking work into the behaviour of bees that is being led by Sussex Professor Francis Ratnieks."
[^49]: https://www.sussex.ac.uk/study/masters/apply/tips-for-masters/personal-statement "I was inspired by the University's world-renowned researchers and world-leading facilities"
[^50]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/personal-statement/ "Are there particular facilities or research groups you're interested in?"
[^51]: https://bmjopen.bmj.com/content/7/6/e013898 "The last author was most involved in obtaining the funding, critically revising the article, designing the study and providing support."
[^52]: https://bmjopen.bmj.com/content/7/6/e013898 "These profiles do not strictly correspond to byline position."
[^53]: https://arxiv.org/abs/1206.4863 "The use of alphabetical authorship is most common in mathematics, economics (including finance), and high energy physics."
[^54]: https://arxiv.org/abs/2004.07180 "We propose SPECTER, a new method to generate document-level embedding of scientific documents"
[^55]: https://www.semanticscholar.org/product/api "The introductory rate limit for an API key is 1 RPS on all endpoints."
[^57]: https://help.openalex.org/api/authentication/ "it raises your daily budget 10× and lets you track your usage"
[^59]: https://help.openalex.org/data/works/attributes.md "True if the work is known to be retracted"

## Open questions

- How long after a move `last_known_institutions` changes, in months: no source measures it.
- Semantic Scholar's abstract coverage for Elsevier/Springer after the 2022/2024 takedowns: its schema
  page returned HTTP 429 to this run.
- Terms of use for KCI, TR Dizin, DergiPark and HAL data in a commercial product: not read.
- National indexes for Germany, Kazakhstan and Azerbaijan, and researchmap's read-only access terms: not
  searched or not verifiable from HTML.
- What share of the professors a letter would name have papers that OpenAlex lacks but a national index
  holds: not measured. It needs a per-country sample against TR Dizin, KCI and CiNii.
- German- and Russian-language admissions guidance on naming staff in a Motivationsschreiben or
  мотивационное письмо: not searched.
