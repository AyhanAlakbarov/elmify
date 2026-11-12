# U1: state-recognition evidence and website binding for universities abroad

Date: 2026-10-03. Serves the decision: a no-human catalogue shows a foreign university only when it is (a) recognised by its own state and (b) bound to its own website.

## Bottom line

1. **A protected academic domain proves different things in different countries.** Only a few registries require state recognition of a *higher-education* institution: KR `ac.kr`, TR `edu.tr`, US `.edu` (new registrations since 2001), ZA `ac.za` (its higher-education branch), KE `ac.ke`, plus JP `ac.jp` and CN `edu.cn` (both: a legally established school or research body). Several others require only that the holder be "an educational institution": SG, SA, VN, KW, BH. NZ `ac.nz` is **unmoderated** and proves nothing. UK `ac.uk` and ZA `ac.za` also admit research bodies and learned societies, so the domain alone does not prove degree-awarding status.
2. **Every one of these restricted domains has a carve-out for registrations made before the current rule** (US before 2001-10-29, ZA before 2001-07-23, VN before Circular 48/2025). So "holds a protected domain" is a strong website-binding signal but only a moderate recognition signal, and it should never be the only evidence of recognition.
3. **WHED is the only worldwide source whose entry rule is "recognised by the national competent body"[^22], and it gives each institution's website[^21].** It removes institutions that lose recognition[^23], and it covers about 21,500 institutions in 190 countries[^20]. Use it as the default recognition-plus-URL source for any country, and add national lists where a country publishes a better one.
4. **DEQAR's institution list is not a recognition list.** It is "intended to give comprehensive coverage of tertiary education in the EHEA" and includes institutions with no quality-assurance report[^25][^26]. Only a DEQAR *report* from an EQAR-registered agency counts as QA evidence.
5. **The US bulk accreditation file on ope.ed.gov stops at 04/2017[^30].** The live DAPIP app renders in JavaScript. Plan on CHEA, the `.edu` registry, or a scraped DAPIP rather than the stale CSV.

## Scope (sub-questions)

1. For each priority ccTLD, does a restricted academic second-level domain exist, and what does the registry's own rule require?
2. For each destination, what is the official list of recognised higher-education institutions: owner, format, whether it lists websites, and size?
3. What do EQAR/DEQAR, USDE/CHEA and the regional bodies in Africa and Latin America publish, and in what format?

## Method and tools

- **Discovery searches:**
  - Exa `agent_run` (two runs: registry policies; national lists).
  - Exa `web_search_advanced_exa` with `includeDomains` limited to each owner's site: jisc.ac.uk, sgnic.sg, internetnz.nz/dnc.org.nz, cernet.edu.cn, nic.tr/trabis.gov.tr, registro.br, ac.za/zadna.org.za, nic.ar, tdra.gov.ae, nic.sa, vnnic.vn, kenic.or.ke, nira.org.ng, whed.net, eqar.eu, ed.gov/chea.org, officeforstudents.org.uk, enic-naric.net, cicic.ca, yok.gov.tr, gov.br, nuc.edu.ng, hrk.de, swissuniversities.ch/sbfi.admin.ch.
  - Brave, as the second engine for the regional QA bodies.
- **Citations:** every quote comes from a scrapling `get`, `fetch` or `stealthy_fetch` of the live page.
- **Agent leads were unreliable.** The Exa agent's national-list URLs were mostly wrong: hkdir.no, akkreditierungsrat.ch, anqa.am, sunedu.gob.pe and the yok.gov.tr path it gave all returned 404. Every row below that is not footnoted is marked **Unverified**.
- **Not used:** Tavily and Context7 were available but not needed. Firecrawl is not available in this session.

## 1. Protected academic second-level domains

Classes: **R** = proves state recognition (higher education or a legally established school); **E** = proves only that the holder is an educational body; **N** = no restriction; **?** = Unverified.

| ccTLD | SLD | Registry rule (quoted) | Class | Caveat |
|---|---|---|---|---|
| US | `.edu` | Must hold institutional accreditation from a USDE-recognised accreditor[^1] | R | Pre-2001-10-29 registrants keep their names regardless[^2] |
| KR | `ac.kr` | Universities and graduate schools under the Higher Education Act[^3] | R | — |
| TR | `edu.tr` | Allocated to higher-education institutions recognised by YÖK[^10] | R | — |
| JP | `ac.jp` | Schools and university bodies established under the School Education Act and other laws, and school corporations (学校法人)[^4] | R (legal school) | JPNIC's copy dates from 2018; JPRS owns the rule |
| CN | `edu.cn` | Education and research units legally established in China, at any level[^5] | R (legal entity, not higher education specifically) | Includes primary and secondary schools |
| ZA | `ac.za` | Public HEIs, or private HEIs registered under the Higher Education Act[^11] | R for the HEI branch | Also admits research bodies and learned societies[^12]; registrations before 2001 may be exempt[^13] |
| KE | `ac.ke` | Ministry registration certificate, charter or Act; the document must classify the holder as tertiary[^15] | R (tertiary, including polytechnics) | — |
| UK | `ac.uk` | Jisc approves via a naming committee; alternative providers must be on the OfS register[^9] | R/E mix | The eligibility policy itself (degree-awarding powers, FE colleges, research bodies, "exceptionally" others) is **Unverified**: the policy page returns 403 to scrapling |
| SG | `edu.sg` | Registered with MOE or under the Private Education Act[^6], **or** funded or endorsed by a government authority[^7] | E | Any education level |
| SA | `edu.sa` | Licensed education and training providers, including schools and training institutes[^14] | E | Not specific to higher education |
| VN | `edu.vn` | Any organisation or business working in education or training[^16] | E | — |
| KW | `edu.kw` | "Educational" institute[^17] | E | No documented check |
| BH | `edu.bh` | Educational institutes operating in Bahrain[^18] | E | — |
| NZ | `ac.nz` | Unmoderated: "no restriction as to who applies"[^8] | **N** | Do not use as evidence |
| AU | `edu.au` | Agent lead: "must be a recognised education or training entity" | ? | **Unverified**: domainname.edu.au blocks all fetchers (Cloudflare 403) |
| AE | `ac.ae` | Policy PDF (tdra.gov.ae, AEDA-POL-007 §14.1.3) reportedly requires a licence from the Ministry of Higher Education | ? | **Unverified**: PDF not fetched by scrapling |
| BR | `edu.br` | Category listed as "Instituições de ensino superior" (Exa snippet) | ? | **Unverified**: registro.br renders in JavaScript |
| AR | `edu.ar` | Managed by ARIU, not NIC Argentina (Exa snippet of nic.ar Res. 58/2023) | ? | **Unverified** |
| NG | `edu.ng` | NiRA's 2008 policy defines "Educational institution" as one recognised under an Act | ? | **Unverified** (PDF snippet only) |
| RS, KZ, AZ, GE, AM, QA, BN, EG, MA, GH, ET, MX, CO, PE, RU | various | not researched to the registry page | ? | **Unverified** |
| CA, CL, IS, NO, CH, most EU | none known | — | ? | **Unverified** that no academic SLD exists; not checked per registry |

## 2. Official recognition lists

| Country | List, owner, format | Lists websites? | Size |
|---|---|---|---|
| **Global** | WHED (IAU, with UNESCO), HTML portal[^20] | Yes: "contact details: address, website"[^21] | ~21,500 HEIs in 190 countries[^20] |
| UK (England) | OfS Register, HTML search plus spreadsheet download[^31] | Unverified | 428 registered providers[^31] |
| AU | TEQSA National Register, HTML search[^32] | Unverified | Unverified |
| US | DAPIP (USDE; reported by recognised accreditors)[^28]; not audited[^29]; bulk CSV/XLSX last 04/2017[^30] | Unverified | — |
| CA | CICIC Directory of Educational Institutions (all levels)[^34] | Unverified | — |
| CN | MOE 全国高等学校名单, XLSX attachments[^33] | No (attachment columns unverified) | 3,167 (2025-06-20)[^33] |
| JP | MEXT 令和6年度全国大学一覧, mext.go.jp/a_menu/koutou/ichiran/mext_00038.html | Unverified | Fetched; the Japanese text has too few spaces for the 4-word quote check, so no footnote |
| KR | data.go.kr dataset #15107736 (keyed API) | Yes (`홈페이지주소`) | From this repo's CLAUDE.md (measured 2026-08-28); not re-fetched |
| BR | e-MEC, the official database of institutions and courses[^38]; public[^38] | Unverified | — |
| NG | NUC: 77 federal / 69 state / 182 private[^39]; federal list has a WEBSITE ADDRESS column[^44] | Yes (federal page) | 328 |
| CH | Swiss Accreditation Council list; accreditation is mandatory to use "university"[^40] | Unverified | — |
| RU | Rosobrnadzor accredited-HEI registry, linked from the ENIC-NARIC page[^37] | Unverified | — |
| NZ | NZQA "Find Education Organisations", HTML search[^41] | Unverified | — |
| TR | YÖK university pages list "Web Sitesi" per university (Exa snippet of yok.gov.tr/tr/university?type=2) | Yes (Unverified) | 207 (Exa snippet of akademik.yok.gov.tr; scrapling timed out) |
| ZA, KE, GH, ET, EG, MA, SA, AE, QA, KW, BH, BN, SG, KZ, AZ, GE, AM, RS, VN, NO, IS, MX, AR, CL, CO, PE | agent leads only | — | **Unverified**: lead URLs that were tested 404'd |
| DE (EU example) | HRK Hochschulkompass covers "all state and state-recognised" HEIs (Exa snippet of hrk.de flyer) | — | Unverified |

**Global pattern for every other country:**

- **ENIC-NARIC country pages.** Each centre maintains a country page with a "Recognised Higher Education Institutions" section linking to the competent authority's list[^35]. The Recognition Conventions section covers competent authorities in Europe, Asia-Pacific, Africa, Latin America and the Arab States[^36]. Russia's page is an example of the section linking to the official registry[^37].
- **WHED** as the fallback, which is itself fed by those national bodies.

## 3. QA and accreditation agency lists

- **EQAR / DEQAR.** Nightly CSV downloads of the HEI list, QA reports and registered agencies (including de-registered agencies, flagged)[^27]. The HEI list comes from ETER/OrgReg and includes HEIs without reports[^25][^26].
  - A REST API is free on request (Exa snippet of eqar.eu/qa-results/connect-to-api; Unverified).
  - Coverage is the EHEA only. Agencies take part voluntarily (Unverified, from Exa snippet).
- **USDE / DAPIP.** Data comes straight from recognised accreditors and state approval agencies[^28]. The bulk files are stale (last 04/2017)[^30].
- **CHEA.** Its institution database ("over 8,200" institutions) returned 403 to scrapling, so it is **Unverified**.
- **Latin America.**
  - SIACES publishes a register of accredited *programmes* by member agencies[^42]. In Peru, SUNEDU licensing is mandatory and SINEACE accreditation is voluntary[^43], so programme accreditation is not the recognition signal there.
  - RIACES and ARCU-SUR (MERCOSUR programme accreditation) were found by Exa and Brave, but their lists were not fetched: **Unverified**.
- **Africa.**
  - AfriQAN (Association of African Universities) is a network, not a register. Its site rendered empty in scrapling: **Unverified**.
  - Brave results (CHEA news pages) say a Pan-African Quality Assurance and Accreditation Agency is being *established* under HAQAA3. It is not a list today: **Unverified**.
- **Warning.** Brave's top hit for this query was QAHE, a self-described "international accreditation" body. The catalogue should accept only agencies designated by the state, EQAR or USDE/CHEA, never an accreditor's own claim.

## Countries with no verified machine-readable recognition evidence in this pass (WHED aside)

None of the destinations lacks *all* evidence: WHED covers 190 countries. But this pass verified **neither** a national list **nor** a restrictive domain for:

- Kazakhstan, Azerbaijan, Georgia, Armenia, Serbia
- Qatar, Brunei, Egypt, Morocco, Ghana, Ethiopia
- Mexico, Argentina, Chile, Colombia, Peru
- Iceland, Norway, UAE

For these, WHED is currently the only verified source.

## Sources

[^1]: https://net.educause.edu/eligibility.htm "They must have institutional accreditation from an institutional accrediting body recognized by the U.S. Department of Education."
[^2]: https://net.educause.edu/eligibility.htm "to retain those registrations regardless of whether the registrants meet the current .edu eligibility requirements"
[^3]: https://krnic.or.kr/jsp/eng/domain/kr/qualification.jsp "Universities or graduate schools according to the Framework Act on Education, the Higher Education Act and other special acts"
[^4]: https://www.nic.ad.jp/ja/question/domain5.html "・学校(ED.JPドメイン名の登録資格の(a)に該当するものを除く) ・大学共同利用機関 ・大学校、短期大学校"
[^5]: https://www.cernet.edu.cn/xxh/zt/cernet/200806/t20080627_305382.shtml "注册域名单位必须符合以下所有条件: 1、 用户是我国依法设立的各级教育和科研单位。"
[^6]: https://www.sgnic.sg/domain-registration/sg-categories-rules "Applicants must be registered with (i) the Ministry of Education (MOE) in Singapore"
[^7]: https://www.sgnic.sg/domain-registration/sg-categories-rules "receive support in the form of funding, endorsement and so on from a relevant government authority in Singapore"
[^8]: https://dnc.org.nz/for-consumers/domain-name-dispute-resolution-scheme/case-summaries/victoria-university-of-wellington-v-fortune-sources-group-limited-2018-nzdc-1327/ "Thus, there is no restriction as to who applies for it."
[^9]: https://www.jisc.ac.uk/domain-registry "they are on the register of designated higher education providers held by the Office for Students (OfS)"
[^10]: https://www.trabis.gov.tr/content/Belgeli "Yükseköğretim Kurulu tarafından tanınan yükseköğretim kurumlarına tahsis edilir."
[^11]: https://www.ac.za/ "Is registered as a private higher education institution in terms of the Higher Education Act (no. 101 of 1997), as amended"
[^12]: https://www.ac.za/ "Conducts scholarly research and places a reasonable proportion of the results in the public domain"
[^13]: https://www.ac.za/ "may not have been applied to domain registrations made before that date"
[^14]: https://nic.sa/en/help/regulation/ "Dedicated only for entities that provide educational and training services directly to students (including, but not limited to, schools, universities, training institutes)"
[^15]: https://kenic.or.ke/ke-domains/ke-products/ "The document should classify the Entity as a Tertiary Institution: Polytechnic, Technical Institute, College or University"
[^16]: https://vnnic.vn/vi/ten-mien-vn/danh-cho-chu-the/dang-ky-ten-mien/huong-dan-dang-ky-ten-mien "EDU.VN: chỉ dành cho cơ quan, tổ chức, doanh nghiệp hoạt động trong lĩnh vực giáo dục, đào tạo;"
[^17]: https://www.kw/en/support/faqs/ "(4) .edu.kw - Which represents an"
[^18]: https://register.bh/faqs/ "Educational institutes operating in Bahrain"
[^20]: https://whed.net/article.php?page=About "the WHED provides information on around 21,500 higher education institutions (HEIs) in 190 countries and territories"
[^21]: https://whed.net/article.php?page=About "contact details: address, website;"
[^22]: https://whed.net/article.php?page=About "Be recognized and referenced by the national competent body"
[^23]: https://whed.net/article.php?page=About "Institutions that may have been recognized by their national competent body in the past, but are no longer recognized, are not listed in the WHED."
[^25]: https://www.eqar.eu/qa-results/download-data-sets/ "The list is intended to give comprehensive coverage of tertiary education in the EHEA."
[^26]: https://www.eqar.eu/qa-results/download-data-sets/ "Download the complete DEQAR HEI list, including those that do not yet have reports in DEQAR."
[^27]: https://www.eqar.eu/qa-results/download-data-sets/ "Download the complete list of EQAR registered agencies, including those that are no longer on the register."
[^28]: https://data.ed.gov/data_explorer/database-post-secondary-institutions "contains information reported to the U.S. Department of Education directly by recognized accrediting agencies and state approval agencies"
[^29]: https://data.ed.gov/data_explorer/database-post-secondary-institutions "This reported information is not audited."
[^30]: https://ope.ed.gov/accreditation/GetDownLoadFile.aspx/ "Accreditation data files created on 04/03/2017 are stored in a CSV and an Excel file."
[^31]: https://www.officeforstudents.org.uk/for-providers/registering-with-the-ofs/guide-to-the-ofs-register/ "The Register lists all the English higher education providers registered by the OfS."
[^32]: https://www.teqsa.gov.au/national-register "The National Register is the authoritative source of information on the status of registered higher education providers in Australia."
[^33]: http://www.moe.gov.cn/jyb_xxgk/s5743/s5744/202506/t20250627_1195683.html "截至2025年6月20日，全国高等学校共计3167所，其中：普通高等学校2919所，含本科学校1365所、高职（专科）学校1554所；成人高等学校248所。本名单未包含港澳台地区高等学校。"
[^34]: https://www.cicic.ca/868/search_the_directory_of_educational_institutions_in_canada.canada "The directory contains the list of educational institutions currently recognized, authorized, registered and/or licensed by the competent authorities in the provinces and territories of Canada."
[^35]: https://enic-naric.net/documents/page-educational-systems-country-profiles-and-tools "ENIC-NARIC centres created and maintain their respective country page up-to-date with official information on:"
[^36]: https://enic-naric.net/documents/page-educational-systems-country-profiles-and-tools "provides information on national competent authorities in charge of higher education issues for most countries"
[^37]: https://enic-naric.net/page-Russian-Federation "Database maintained by the Federal Service of Supervision in Education and Science"
[^38]: https://www.gov.br/mec/pt-br/politica-regulacao-supervisao-educacao-superior/cadastro-nacional-de-cursos-e-ies "é a base de dados oficial dos cursos e"
[^39]: https://enuc.nuc.edu.ng/nus "77 Federal Universities 69"
[^44]: https://www.nuc.edu.ng/nigerian-univerisities/federal-univeristies/ "FEDERAL UNIVERSITIES VICE CHANCELLOR WEBSITE ADDRESS"
[^40]: https://www.sbfi.admin.ch/en/higher-education-accreditation "The list of currently recognised or accredited Swiss higher education institutions under the terms of HEdA can be found on the CSA website."
[^41]: https://www.nzqa.govt.nz/providers/index.do "Search Education organisations by region:"
[^42]: https://siaces.org/registro-de-programas-acreditados/ "Acceda a las titulaciones acreditadas por las distintas agencias que componen el SIACES."
[^43]: https://siaces.org/registro-de-programas-acreditados/ "En Perú la acreditación de programas es un proceso voluntario (realizado por SINEACE), mientras que el licenciamiento es obligatorio (realizado por SUNEDU)."

## Open questions

- **AU `edu.au`:** the actual rule. domainname.edu.au blocks every scrapling mode; try Firecrawl or scrape.do.
- **UK `ac.uk`:** the full eligibility clauses (community.jisc.ac.uk returns 403; a PDF exists).
- **AE `ac.ae`:** AEDA-POL-007 §14.1.3 (PDF not fetched).
- **BR `edu.br`:** the rule (registro.br is JavaScript-rendered).
- **AR `edu.ar`:** ARIU's rule.
- **NG `edu.ng`:** the current rule.
- **Not researched:** SLD rules for RS, KZ, AZ, GE, AM, QA, BN, EG, MA, GH, ET, MX, CO, PE, RU and each EU state.
- **WHED:** whether it has a bulk export or API, and its terms. Per this repo's CLAUDE.md, WHED is one lookup per institution, and IAU consent was obtained in 2026-08/09.
- **Website fields:** whether OfS, TEQSA, CICIC, e-MEC, DAPIP and DEQAR's HEI CSV carry a website field.
- **CHEA database:** it returned 403. Size and format are Unverified.
- **National lists:** for the Unverified countries in §2, find the real list URLs. The agent's leads were wrong.
- **NUC count:** the NUC federal page's WEBSITE ADDRESS header was fetched, but the 77+69+182 figure comes from enuc.nuc.edu.ng. The two pages could diverge.
