# Which universities count as "top" per country: a rule we can build and defend

Date: 2026-10-03. Scope: Vietnam, all of Africa (measured for ZA, NG, KE, EG, MA, GH, ET), South America (measured for BR, AR, CL, CO, PE) and Mexico.

## Answer

Don't use any single commercial ranking. Recommended rule, **TOP-U v1**:

1. **National floor.** The institution must be on the national authority's own register (VN: MOET quality-accreditation list; NG: NUC list; BR: e-MEC/INEP; ZA: DHET public universities; and so on). This decides whether an institution is *legitimate*, not whether it is *top*.
2. **Research-activity gate, from open data.** The institution must be in the **CWTS Leiden Ranking Open Edition** (at least 1,500 OpenAlex publications in 2020–2023). The data is CC0 and the method and code are open.
3. **Independent corroboration.** The institution must also appear in at least one ranking built on a *different* bibliographic database: URAP (Web of Science/InCites), SCImago SIR (Scopus), U.S. News BGU (Web of Science) or CWUR Global 2000. Exclude any institution SCImago flags as an integrity risk. QS and THE are tie-break evidence only and never enough on their own.
4. **Per-country cutoff.** Rank the survivors by Leiden Open **P(top 10%)**, the number of a university's papers among the 10% most cited. Keep at most **25** per country.
5. **Thin-coverage fallback.** If fewer than 5 survive, fill up to 5 with registered domestic universities ranked by OpenAlex output for 2020–2023, provided each has at least 300 works. Label them "national top, not globally ranked". In our measurements this is needed only for **Kenya**. Ghana and Ethiopia pass gate 2 with 6 and 13 universities.

Estimated yield (section 3): about **257 institutions** across the 14 measured countries. Brazil, Mexico, Chile, Colombia, Nigeria and Egypt are capped at 25. VN 19, AR 17, PE 13, ZA 21, KE 5, MA 13, GH 6, ET 13.

**Why this rule, briefly.** The two most-used rankings mix reputation surveys with data the universities submit themselves:

- QS gives Academic Reputation 30% and Employer Reputation 15%.[^qs1] It admits only institutions "in the top 20%" on Academic Reputation.[^qs2]
- THE gives teaching reputation 15% and research reputation 18%,[^the1] and the universities sign off their own data.[^the3]
- Peer-reviewed evidence shows the QS business model distorting results.[^chirikov]

By contrast, CWTS states that Leiden Open applies one published threshold to OpenAlex data and releases everything under CC0.[^leiden-sel][^leiden-cc0]

**Assumptions that would change the answer:**

- **"Top" means research-active.** If it should mean teaching quality or graduate outcomes, gates 2–4 are the wrong instrument. CWTS itself advises "students not to use the Leiden Ranking to choose where to study".[^leiden-students]
- **The per-country counts are estimates.** They come from my own OpenAlex queries that approximate Leiden Open's criterion. I could not read Leiden's own per-country list, because its endpoints are POST-only. The real counts will differ, mainly where university systems are federated (VNU, UNAM, Al-Azhar).
- **The cap of 25 is a product choice, not a finding.**

---

## 1. Comparison table

How the candidate list was built: the caller supplied it. I ran no discovery searches to add sources. Tools used: scrapling `get` (all quotes), scrapling `fetch` (URAP only, which renders with JavaScript), Exa, Brave, Tavily (to find owner pages) and the OpenAlex API (measurements). Unreachable: **webometrics.info** (DNS failure on both `www.` and the bare host, so every Webometrics cell is **Unverified**). The SCImago ranking table needs browser extensions (country counts **Unverified**).

| Source | Method (core) | Documented weakness | Size / latest edition | Update cycle | Machine-readable? Reuse terms |
|---|---|---|---|---|---|
| **QS WUR** | 50% research lens: Academic Reputation 30%, Citations per Faculty 20%; Employer Reputation 15%[^qs1] | Inclusion requires the top 20% on reputation[^qs2]; universities with frequent QS contracts gained about 140 places (peer-reviewed)[^chirikov] | **Unverified** count | Research from September, published in June[^qs3] | No open download found. Terms **Unverified** |
| **THE WUR** | Teaching reputation 15% + research reputation 18% among 18 indicators[^the1]; data self-submitted and signed off[^the3] | Needs ≥1,000 publications 2020–24[^the2]; had to correct reputation-vote attribution after publication[^the4]; University of Zurich stopped providing data[^uzh] | 2026 edition (2027 also listed on site); count **Unverified** | Annual | No open download found. Terms **Unverified** |
| **ARWU (ShanghaiRanking)** | Nobel/Fields alumni 10%, staff 20%, Highly Cited Researchers 20%, Nature & Science 20%, Web of Science papers 20%, per-capita 10%[^arwu1] | Falls back to a world-average staff count where national data is missing[^arwu2]; peer review judged its criteria "not relevant"[^billaut] | 2025: >2,500 ranked, top 1,000 published[^arwu3] | Annual | A JSON endpoint (`/api/pub/v1/arwu/rank?version=2025`) returned the full 2025 list in this run (measured, about 453k characters). Terms **Unverified** |
| **CWUR** | Education 25%, Employability 25%, Faculty 10%, Research 40%; no surveys or self-submitted data[^cwur1] | Describes itself as a consulting organisation selling services to the universities it ranks[^cwur3] (the same conflict-of-interest structure Chirikov measured for QS; no CWUR-specific study found) | 2026: top 2,000 of 21,291 ranked[^cwur2]; BR has 52 in the Global 2000 (secondary source, g1)[^g1] | Annual (1 June 2026) | HTML table only. Terms **Unverified** |
| **U.S. News BGU** | 13 indicators; global and regional reputation 12.5% each; Web of Science bibliometrics[^usn2] | Reputation 25% in total; includes the pool of institutions with ≥1,250 papers 2020–24[^usn3] | 2026–2027: top 2,250 of 2,438, 105 countries[^usn1]; country pages only for countries with ≥5 schools[^usn4] | Annual | Pages paginate 10 rows per view. No download. Terms **Unverified** |
| **Webometrics** | **Unverified** (site unreachable) | **Unverified** | **Unverified** | **Unverified** | **Unverified** |
| **URAP** | 6 Web of Science/InCites indicators: article, citation, total documents, AIT, CIT, international collaboration (JavaScript page)[^urap1] | Cannot release raw data because of its InCites contract[^urap2] | 3,000 HEIs processed (the page says both "top 2,500 … scored" and "3000 … ranked")[^urap1] | Annual (2025–2026 edition) | Excel score tables per year[^urap3]. Terms **Unverified** |
| **SCImago SIR** | Research 50% / Innovation 30% / Societal 20%; Scopus, PATSTAT, Google/Semrush web metrics[^scimago3] | Uses web-visibility and SEO metrics; 61 universities flagged in 2026 for self-citation and self-referencing[^scimago2] | Inclusion threshold: ≥100 Scopus works in the last year[^scimago1]; country counts **Unverified** | Annual (2026 edition) | Ranking table needs a browser. Terms **Unverified** |
| **Nature Index** | Counts articles in 178 selected journals[^ni1] | Not size-normalised; its own FAQ says "metrics alone should not be used to assess institutions"[^ni3] | Any institution with ≥1 article in those journals appears[^ni4] | Monthly rolling 12 months[^ni2] | Web tables. Terms **Unverified** |
| **Leiden Ranking (Traditional)** | Web of Science bibliometric indicators, no composite score[^leiden-trad] | Calls THE, QS and ARWU "questionable"; not for students[^leiden-others][^leiden-students] | 2025: >1,500 universities[^leiden-trad] | Annual | Licensed Web of Science data; terms **Unverified** |
| **Leiden Ranking Open Edition** | Same indicators on OpenAlex (August 2025 snapshot)[^leiden-snap]; inclusion ≥1,500 publications 2020–2023[^leiden-sel] | More false negatives than false positives in affiliation linking[^leiden-dq]; OpenAlex coverage of local literature "varies substantially"[^leiden-local] | 2025: 2,831 universities, 120 countries[^leiden-n]; all 14 target countries appear in its country filter[^leiden-ctry] | Annual (2023, 2024, 2025 editions)[^leiden-eds] | **Yes: results, data, BigQuery and MIT-licensed code; CC0**[^leiden-cc0] |
| **OpenAlex output counts** | Raw counts from the API (works, h-index) | Institution IDs are "best answer to a fuzzy question … can be wrong"[^oa-wrong]; mapping artefacts measured below | 2,677 `type:education` institutions across the 14 countries (measured) | Continuous | **Yes: API, CC0, $1/day free**[^oa-cc0][^oa-free] |

### National sources (floor, not ranking)

| Country | Source | Status in this run |
|---|---|---|
| VN | MOET Cục Quản lý chất lượng: list of accredited institutions and programmes, updated monthly (latest to 30/8/2026)[^vqa] | Verified that it exists and is updated monthly. Count **Unverified** (file attachment not parsed) |
| NG | NUC: Federal 77, State 69, Private 182[^nuc1][^nuc2]; NUC also publishes a list of illegal universities (**Unverified**, seen only via Tavily snippet) | Verified |
| BR | INEP IGC: annual institution quality index[^inep]; e-MEC register and RUF Folha ranking | IGC verified. e-MEC and RUF **Unverified** |
| ZA | DHET: 26 public universities | **Unverified** (search snippet of a DHET PDF only) |
| MX (SEP RVOE / SECIHTI-SNP), KE (CUE), AR (CONEAU), CL (CNA), CO (MEN/CNA), PE (SUNEDU), EG (SCU), MA, GH (GTEC), ET (ETA) | Registers expected to exist | **Unverified**: not researched within the step budget |

---

## 2. The rule and its failure modes

**Why each gate exists**

- **Gate 1 (Leiden Open).** It is the only candidate that is open on every axis: data, code, threshold and licence.[^leiden-sel][^leiden-cc0] It sits on OpenAlex, which our pipeline can query directly.
- **Gate 2 (a second, independent database).** It catches OpenAlex attribution artefacts. This run hit two of them:
  - **Mexico:** "Tecnológico de Estudios Superiores de San Felipe del Progreso" is credited with **8,529** works for 2020–23, more than Tec de Monterrey (8,603 is next). A mapping error is very likely; that it is one is **Unverified**.
  - **Argentina:** "Argentine-German Geodetic Observatory" has **52,804** works against CONICET's 52,802. This is a lineage artefact.

  A university that is real and large also appears in Scopus-based SCImago (threshold of 100 works per year)[^scimago1] or WoS-based URAP. So the gate costs little for genuine institutions and removes artefacts that exist in only one database.
- **Gate 4 (sort on P(top 10%), not on volume).** Volume rewards size and paper output. Measured example: Universidad César Vallejo is **#2 in Peru by OpenAlex volume** (6,307 works), ahead of PUCP (4,212). A volume cut cannot tell whether that reflects quality. A citation-percentile cut is the standard size-dependent excellence measure; U.S. News uses the same construct at 12.5%.[^usn2]
- **Excluding QS and THE as deciders.** Both lean on reputation surveys and self-submitted data.[^qs1][^the1][^the3] QS has measured conflict-of-interest distortion.[^chirikov] THE has lost data providers.[^uzh]

**Failure modes**

1. **"Top" collapses to "research-intensive".** Teaching-led, arts, law and business institutions with low output drop out. Leiden says so itself.[^leiden-students] Mitigation: let a counsellor override with a recorded reason.
2. **Gaming by volume and affiliation.** OpenAlex affiliation data affects both gates. SCImago's integrity flag[^scimago2] and the P(top 10%) sort reduce this but do not remove it. Egypt's co-authorship list is full of Saudi universities (for example King Saud University with 6,728 works in the Egyptian query), which shows how dual affiliations move counts.
3. **Federated systems and members counted twice.** OpenAlex lineage counts a VNU member university both under VNU and on its own (VN: HCMUT, HCMUS and VNU-University of Science appear separately). Leiden's own registry handles this better. My VN count removes 3 such member universities by hand.
4. **Research institutes outrank universities.** KE: CGIAR (3,910), KEMRI (3,011) and ILRI (1,577) sit among the universities. ET: the Ethiopian Institute of Agricultural Research (2,320). Filter on institution type plus the national register (gate 0).
5. **The national register means "licensed", not "good".** NUC lists 328 universities.[^nuc1][^nuc2] Vietnam's list certifies accreditation status.[^vqa] Neither ranks anything, which is why the floor is never the cutoff.
6. **Thin-coverage countries.** Kenya has only 4 universities at or above the threshold (Nairobi, JKUAT, Kenyatta, Moi), so the fallback adds Egerton (1,407). Ghana stops at 6 (University of Ghana, KNUST, Cape Coast, UDS, UEW, UHAS). A Ghanaian "top 6" includes UHAS at 1,517 works, just over the line, so the threshold edge decides membership. Prefer a stable rule plus annual review to hand-tuning.
7. **Cadence and cost.** Leiden Open is annual and uses an OpenAlex snapshot about a year old.[^leiden-snap] OpenAlex API use beyond $1/day is paid.[^oa-free]

---

## 3. Per-country yield

Gate 1 is approximated by my own OpenAlex query (measured 2026-10-03). For each country: `works?filter=publication_year:2020-2023,type:article|review|book-chapter,authorships.institutions.country_code:XX&group_by=authorships.institutions.lineage`. I then counted by hand the **domestic universities** with ≥1,500 works, excluding hospitals, government bodies, research institutes, foreign co-authors and member units already counted under a parent. These are **measured approximations of Leiden Open's criterion, not Leiden's list.** Gate 2 is not applied in these numbers; I expect it to remove few institutions apart from artefacts like San Felipe del Progreso.

The JSON responses cannot be quoted in the footnote format, so these counts carry no footnotes. Each one can be reproduced with the URL pattern above.

| Country | ≥1,500 works 2020–23 (gate 1 approximation) | After cap 25 / floor 5 | OpenAlex `type:education` institutions | …with lifetime works >10,000 |
|---|---|---|---|---|
| VN | 19 (22 raw minus 3 VNU members) | **19** | 243 | 12 |
| MX | ~36 (37 minus the San Felipe artefact) | **25** | 564 | 23 |
| BR | ≥105 (130th group still at 2,345 works) | **25** | 518 | 102 |
| AR | 17 | **17** | 156 | 12 |
| CL | 27 | **25** | 96 | 18 |
| CO | ~25 (one "University of Córdoba" entry ambiguous) | **25** | 218 | 17 |
| PE | 13 | **13** | 108 | 4 |
| ZA | 21 | **21** | 71 | 17 |
| NG | 41 | **25** | 273 | 23 |
| KE | 4 | **5** (fallback: Egerton) | 82 | 3 |
| EG | 28 | **25** | 117 | 24 |
| MA | 13 | **13** | 102 | 12 |
| GH | 6 | **6** | 74 | 4 |
| ET | 13 | **13** | 55 | 6 |
| **Total** | | **≈257** | 2,677 | |

Global-ranking coverage by country: I verified only that **Leiden Open lists all 14 countries**[^leiden-ctry] and that **CWUR 2026 has 52 Brazilian universities** (secondary source, g1).[^g1] The other per-country counts (QS, THE, ARWU, U.S. News, URAP, SCImago, Nature Index, Webometrics for the 14 countries) are **Unverified**. Their lists are either JavaScript-rendered or too large to count without running code, which this agent cannot do. See Open questions.

---

## Sources

[^qs1]: https://support.qs.com/hc/en-gb/articles/4405955370898-QS-World-University-Rankings "Research and Discovery 50% Academic Reputation 30% Citations per Faculty 20%"
[^qs2]: https://support.qs.com/hc/en-gb/articles/4405955370898-QS-World-University-Rankings "Be in the top 20% of institutions globally for Academic Reputation"
[^qs3]: https://support.qs.com/hc/en-gb/articles/4405955370898-QS-World-University-Rankings "Research for the World University Rankings begins in September and the Rankings are published in June."
[^chirikov]: https://link.springer.com/article/10.1007/s10734-022-00942-5 "the universities with frequent QS-related contracts had an increase of 0.75 standard deviations (~ 140 positions) in QS World University Rankings"
[^the1]: https://www.timeshighereducation.com/world-university-rankings/world-university-rankings-2026-methodology "Teaching (the learning environment): 29.5% Teaching reputation: 15%"
[^the2]: https://www.timeshighereducation.com/world-university-rankings/world-university-rankings-2026-methodology "fewer than 1,000 relevant publications between 2020 and 2024 (with a minimum of 100 a year)"
[^the3]: https://www.timeshighereducation.com/world-university-rankings/world-university-rankings-2026-methodology "Institutions provide and sign off their institutional data for use in the rankings."
[^the4]: https://www.timeshighereducation.com/world-university-rankings/world-university-rankings-2026-methodology "we identified an issue with institutional affiliations relating to the attribution of reputation votes affecting four universities"
[^uzh]: https://www.news.uzh.ch/en/articles/news/2024/rankings.html "UZH has decided it will no longer provide data for the THE ranking."
[^arwu1]: https://www.shanghairanking.com/methodology/arwu/2025 "Papers published in Nature and Science* N&S 20%"
[^arwu2]: https://www.shanghairanking.com/methodology/arwu/2025 "the average number of academic staff for world top 1000 universities will be used for all institutions in this country"
[^arwu3]: https://www.shanghairanking.com/methodology/arwu/2025 "In total, more than 2500 universities are actually ranked, and the best 1000 are published."
[^billaut]: https://link.springer.com/article/10.1007/s11192-009-0115-x "Our main conclusions are that the criteria that are used are not relevant"
[^cwur1]: https://cwur.org/methodology/world-university-rankings.php "without relying on surveys and university data submissions"
[^cwur2]: https://cwur.org/media.php "lists the top 2000 universities out of 21,291 ranked institutions"
[^cwur3]: https://cwur.org/media.php "is a leading consulting organization providing policy advice, strategic insights, and consulting services to governments and universities"
[^g1]: https://g1.globo.com/educacao/noticia/2026/06/01/ranking-lista-global-universidades-cwur-2026.ghtml "45 das 52 universidades brasileiras que integram a lista das melhores no mundo caíram de posição no ranking de 2026 do CWUR."
[^usn1]: https://www.usnews.com/education/best-global-universities/articles/methodology "the top 2,250 schools among them – representing 105 countries – were ranked"
[^usn2]: https://www.usnews.com/education/best-global-universities/articles/methodology "Global research reputation (12.5%):"
[^usn3]: https://www.usnews.com/education/best-global-universities/articles/methodology "Additional institutions that met a threshold of at least 1,250 papers published from 2020 to 2024 were also added."
[^usn4]: https://www.usnews.com/education/best-global-universities/articles/methodology "the top institutions in 58 countries, all of which have five or more schools in the overall ranking"
[^urap1]: https://urapcenter.org/Methodology "Data for 3,000 HEIs have been processed and top 2,500 of them are scored."
[^urap2]: https://urapcenter.org/Methodology "due to our university's agreement with InCites, we are unable to fulfill data requests for raw data"
[^urap3]: https://urapcenter.org/Methodology "you can retrieve score tables generated from ranking analyses in Excel format categorized by year"
[^scimago1]: https://www.scimagoir.com/methodology.php "The institutions had published at least 100 works included in the SCOPUS database during the last year of the selected time period."
[^scimago2]: https://www.scimagoir.com/methodology.php "A total of 61 universities in the SIR 2026 edition have been flagged for high rates of self-citation (over 25%) and self-referencing (over 15%)."
[^scimago3]: https://www.scimagoir.com/methodology.php "The sources of information used for the indicators for web visibility are Google and Semrush."
[^ni1]: https://www.nature.com/nature-index/faq "primary research articles published within 178 high-quality natural, health, applied and social science publications"
[^ni2]: https://www.nature.com/nature-index/faq "The Current Index is refreshed monthly"
[^ni3]: https://www.nature.com/nature-index/faq "Nature Index metrics alone should not be used to assess institutions or individuals."
[^ni4]: https://www.nature.com/nature-index/faq "Only institutions with at least one affiliated author on a primary research article published in one of the 178 publications tracked by the index will appear in the Nature Index."
[^leiden-trad]: https://www.leidenranking.com/ "The 2025 release includes over 1500 universities worldwide."
[^leiden-others]: https://open.leidenranking.com/information/general "which we believe to provide questionable information"
[^leiden-students]: https://open.leidenranking.com/information/general "we advise students not to use the Leiden Ranking to choose where to study"
[^leiden-sel]: https://open.leidenranking.com/information/universities "The Leiden Ranking Open Edition includes universities that have at least 1500 publications in the period 2020–2023 indexed in the OpenAlex database."
[^leiden-n]: https://open.leidenranking.com/information/universities "The Leiden Ranking Open Edition 2025 includes 2831 universities from 120 countries."
[^leiden-dq]: https://open.leidenranking.com/information/universities "in general there are substantially more false negatives than false positives"
[^leiden-local]: https://open.leidenranking.com/information/universities "coverage of local literature varies substantially across countries, disciplines, and regions"
[^leiden-snap]: https://open.leidenranking.com/information/data "The ranking uses the OpenAlex snapshot from August 2025."
[^leiden-cc0]: https://open.leidenranking.com/resources "The results are made available under a CC0 public domain dedication."
[^leiden-ctry]: https://open.leidenranking.com/ranking/2025/list "Estonia Ethiopia Finland France Georgia Germany Ghana"
[^leiden-eds]: https://open.leidenranking.com/ranking/2025/list "Map view Ranking 2024 Ranking 2023"
[^oa-wrong]: https://help.openalex.org/data/ "These IDs represent OpenAlex’s best answer to a fuzzy question, and they can be wrong"
[^oa-cc0]: https://help.openalex.org/access/pricing/ "the data is a public good, released under a CC0 public-domain license"
[^oa-free]: https://help.openalex.org/access/pricing/ "every account gets $1 of API usage per day for free"
[^vqa]: https://vqa.moet.gov.vn/vi/thong-bao-quan-ly-bao-dam/thong-bao/danh-sach-cac-co-so-giao-duc-chuong-trinh-dao-tao-giao-duc-dai-hoc-va-cao-dang-su-pham-duoc-cong-nhan-dat-tieu-chuan-chat-luong-giao-duc-cap-nhat-den-ngay-30-8-2026-94.html "được công nhận đạt tiêu chuẩn chất lượng giáo dục (cập nhật đến ngày 30/8/2026)"
[^nuc1]: https://www.nuc.edu.ng "Total Number of Universities Federal Universities (77)"
[^nuc2]: https://www.nuc.edu.ng "Private Universities (182) 55.5%"
[^inep]: https://www.gov.br/inep/pt-br/areas-de-atuacao/pesquisas-estatisticas-e-indicadores/indicadores-de-qualidade-da-educacao-superior/indice-geral-de-cursos-igc "O IGC é um indicador de qualidade que avalia as instituições de educação superior."

## Open questions

1. **Exact Leiden Open counts per country.** The site's list endpoint is POST-only. The answer is in the CC0 results file (Zenodo record 17473224) or BigQuery. Counting it needs code, so the build should run it.
2. **Per-country coverage of QS, THE, ARWU, U.S. News, URAP, SCImago, Nature Index and Webometrics.** Not counted (lists are rendered with JavaScript or too large to count without code). ARWU's JSON endpoint returned the full 2025 list and can be grouped by country in one script. Webometrics could not be reached at all.
3. **Reuse terms** of every commercial ranking (QS, THE, ARWU, CWUR, U.S. News, SCImago, Nature Index, URAP) were not read. Only Leiden Open and OpenAlex are confirmed CC0.
4. **National registers** for MX, KE, AR, CL, CO, PE, EG, MA, GH, ET and ZA: whether each exists, whether it can be downloaded, and how many institutions it lists. Not verified.
5. **Gate 2's real drop rate** per country, and whether "Tecnológico de Estudios Superiores de San Felipe del Progreso" (8,529 works) really is an OpenAlex mapping error.
