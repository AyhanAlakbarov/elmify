# Funded-Master's Discovery: Source Landscape, Access Terms and Build Priorities

## TL;DR
- **The highest-leverage build targets are supranational, openly-licensed grant graphs**: CORDIS (CC BY 4.0, bulk XML/CSV/JSON on data.europa.eu; more than 56,000 unique participating organisations across all Framework Programmes, EU PIC identifiers), the OpenAIRE Graph (CC BY 4.0 Zenodo dumps aggregating 368 funders and ~4 million grants worldwide) and UKRI Gateway to Research (Open Government Licence, documented JSON/XML API over ~170,000 funded projects). Build these before any national source.
- **The "no supplier" gap for Japan, Korea and China is now partly closed**: Korea has a genuine, KOGL-licensed, enumerable programme register on data.go.kr (55,228-row department/major list with a degree-level field) plus an Open API; China publishes official MOE programme catalogues and per-institution approval lists (enumerable PDF/Excel, no reuse licence published, Chinese-only, some WAF blocking); Japan has NO normalized programme register — only Japanese-only MEXT Excel institution directories — but its KAKEN grant database is fully usable (CC BY, OpenSearch API).
- **Part A resolved**: CORDIS, data.europa.eu, ANR and KAKEN are all effectively CC BY / open and permit automated retrieval AND storage; Finland's konfo-backend has no dataset-specific licence published, but the service is open and unauthenticated and Finnish public-sector data defaults to CC BY 4.0 (JHS 189). The families with NO index remain home-origin and bilateral government scholarships, and most corporate/foundation master's schemes.

## Key Findings

### Part A — the four blocking access-terms questions

**A1. Opintopolku / konfo-backend (Opetushallitus / Finnish National Agency for Education).** The API is open and unauthenticated: the OpenAPI/Swagger is published at `https://opintopolku.fi/konfo-backend/swagger` (ReDoc at `/konfo-backend/redoc/index.html`), and the search endpoint `/konfo-backend/search/koulutukset` returns clean JSON with a level filter (the requester verified 7,664 → 1,285 master's records). **No dataset-specific licence or terms-of-service statement for konfo-backend itself could be found on opintopolku.fi.** The Finnish public-sector default is CC BY 4.0: the JHS 189 recommendation and the avoindata.fi guidance both state CC BY 4.0 / CC0 as the standard licence for public open data ("Julkisen hallinnon avoimille tietoaineistoille on annettu suositus JHS-189… joka myös suosittelee käytettäväksi CC BY 4.0 -lisenssiä"). **Verdict: technically open; automated retrieval clearly permitted; storage almost certainly permitted under CC BY 4.0 but NOT confirmed by a service-specific statement — a residual terms gap to close with a one-line email to Opetushallitus, not an adapter blocker.**

**A2. CORDIS.** Legal notice at `https://cordis.europa.eu/about/legal`: "the reuse of the **editorial content** on this website owned by the EU is authorized under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence… reuse is allowed, provided appropriate credit is given and any changes are indicated." Reuse is implemented by Commission Decision 2011/833/EU. **Caveat, quoted verbatim:** "Materials provided by beneficiaries receiving EU funding may only be used according to the terms and conditions applicable to the respective grant." Project/organisation metadata (titles, participants, PICs, funding) is EU-owned editorial content = CC BY 4.0. **Verdict: automated retrieval AND storage permitted (CC BY 4.0); only beneficiary-supplied attachments carry separate terms.**

**A3. data.europa.eu.** Legal notice: editorial content CC BY 4.0; **dataset licensing varies per dataset** ("A link to these conditions can be found on every dataset page"). The CORDIS bulk datasets hosted there are published by the Publications Office under the same Commission reuse regime as CORDIS itself — i.e. the CORDIS bulk downloads on data.europa.eu do NOT carry a more restrictive licence than CORDIS; both are CC BY 4.0 under Decision 2011/833/EU. **Verdict: automated retrieval AND storage permitted; always read the per-dataset licence field, but for CORDIS it matches.**

**A4. ANR (Agence nationale de la recherche).** The underlying data IS separately published as open data on data.gouv.fr (not only through anr.fr's search). Datasets: "ANR_01 Projets ANR DOS et DGDS", "ANR_02 Projets ANR DGPIE", and "Appels à projets ANR – Projets retenus et participants identifiés", each in **XLSX, CSV and JSON** ("Chaque jeu de données est présenté sous 3 formats : XLSX, CSV et JSON. Les données des 3 fichiers sont exactement les mêmes"). Also mirrored with an API on `data.enseignementsup-recherche.gouv.fr`. Identifiers, quoted: "Les participants français sont identifiés par leur numéro SIREN ou leur numéro RNSR… et les participants étrangers sont identifiés par leur numéro GRID." data.gouv.fr default licence is the Licence Ouverte/Etalab (open, attribution). Coverage: 28,000+ Plan d'action projects and 1,450+ France 2030/PIA projects, 2005–2024. **Verdict: automated retrieval AND storage permitted; French orgs carry SIREN/RNSR, foreign orgs carry GRID.**

### Part B — grant and research-funding databases

- **CORDIS (EU, supranational)** — bulk XML/CSV/XLS/JSON on data.europa.eu; RSS/XML/CSV live. Open, no auth. CC BY 4.0. Records carry beneficiary org name + **EU PIC** participant id + country. More than 56,000 unique organisations have participated as coordinators or partners across all Framework Programmes (FP1→Horizon Europe). Highest leverage: one adapter, roughly 40 countries. English.
- **OpenAIRE Graph (supranational aggregator)** — bulk dumps on Zenodo (`organization.tar`, `project.tar`, etc.), CC BY 4.0; also a live API. Per OpenAIRE's "Year in Review: 2025" and ERCIM News (en144, 2026), the Graph aggregates metadata from **over 2,100 direct metadata sources (155,000 counting indirect sources via aggregators)**, ~345 million research products, **368 funders, ~4 million grants and over 7 billion relationships**. Org records carry PIDs incl. ROR/GRID where mapped. Very high leverage; heavier to process; best used as the identifier crosswalk hub.
- **UKRI Gateway to Research (UK)** — documented GTR-2 API (JSON + XML) at `gtr.ukri.org/gtr/api/`, Open Government Licence v2.0, open/no key. Publishes ~170,000 funded projects with start dates on or after 1 January 2006. Records carry organisation, people, and **studentship/training-grant** links; quoted: "Information about UKRI-funded students, associated with UKRI training grants, is only available from 1 February 2015." Quarterly updates: "GtR publishes award data quarterly and is scheduled to update the second week of April, July, October and January." A further studentship-portal dataset "is expected to become available… during the first quarter of the 2026-27 financial year… visible in the July 2026 update to GtR." Pagination 10–100/page; "we expect users… not to flood the service" (no hard numeric limit published). English.
- **KAKEN (Japan, NII/MEXT/JSPS)** — OpenSearch API at `https://kaken.nii.ac.jp/opensearch/` (RSS/Atom/JSON-LD/HTML) requiring a free CiNii Application ID (`appid=`). **Terms:** content follows "MEXT's Website Terms of Use," which "is compatible with the Creative Commons License Attribution 4.0 International… therefore the content… can also be used by complying with CC BY" (some pre-2015 report attachments are separately copyrighted). Records carry institution, PI, funding category, amount; researcher numbers/DOIs as ids. Records available in English and Japanese. **Rate note, quoted:** "huge accesses in short time which affect other users may be blocked without notice." Usable now.
- **NIH RePORTER (US)** — documented v2 REST API (`api.reporter.nih.gov`) + ExPORTER bulk files; US-Gov public-domain works. Org + PI + amount + linked publications. English. Usable now.
- **NSF Awards (US)** — documented Award Search API (research.gov / NSF awards API). Public domain. Org, PI, program, amount, abstract. English. Usable now.
- **USASpending.gov (US)** — cross-agency API, no key; captures NIH/NSF/SBIR at recipient level. Public domain. The only US source that does not require knowing the funding agency in advance.
- **DFG GEPRIS (Germany)** — HTML only via `gepris.dfg.de/gepris/OCTOPUS?task=…` search; **no documented API, no bulk download** (third parties crawl it). Records carry applicant institution + project. A GEPRIS release stated for July 2026 will add project participants' research-institution data. German/English. BLOCKED BY TECHNIQUE for now (search-only enumeration; no published licence).
- **NRF Korea** — programme pages on eng.nrf.re.kr; **no open-data API or bulk grant download found**. Grant-level data not published as a machine-readable feed. HTML only.
- **SNSF (P3), NWO, Vetenskapsrådet (SweCRIS), TÜBİTAK, NKFIH** — not individually verified this pass (search budget exhausted); SNSF's P3 portal and Sweden's SweCRIS are known open datasets and should be probed next. Labelled UNVERIFIED.
- **Dimensions / Candid** — aggregators with commercial/closed terms (see Part D).

### Part C — official national programme registers

| Country | Register | Access route | Terms | Master's filter | Language |
|---|---|---|---|---|---|
| Finland | Opintopolku konfo-backend | JSON API `/search/koulutukset` (verified responding) | open; CC BY 4.0 assumed (not service-specific) | yes (1,285 MA) | FI/SV/EN |
| Germany | Hochschulkompass (HRK) | HTML search only, **no sitemap** | terms not established | via search | DE/EN |
| France | RNCP / France Compétences on data.gouv.fr; MESR fr-esr open data | bulk + API | Licence Ouverte | yes | FR |
| Italy | MUR "Offerta formativa" open data, `dati-ustat.mur.gov.it` | bulk datasets (2001–2024) | open data (CKAN) | yes (laurea magistrale) | IT |
| Netherlands | **RIO (successor to CROHO), DUO** | "Erkenningenoverzicht ho" bulk on `onderwijsdata.duo.nl`; **OOAPI** via SURFeduhub; RIO also as **linked open data** | DUO open onderwijsdata (open) | yes (master/bachelor/AD) | NL |
| Korea | **대학알리미/Academyinfo via data.go.kr** | file XLSX (#15139338, 55,228 rows) + Open API (standard data #15107736, key) | **KOGL** (attribution; "use permission range limitless"; free) | **yes (degree-program field)** | KO; institution names bilingual |
| Japan | **No programme register**; MEXT annual "全国大学一覧" Excel (institution/faculty) | bulk Excel; e-Stat = statistics only (auth API) | JP-gov general terms; no per-dataset licence | no | **Japanese only** |
| China | **MOE 专业目录 + per-institution 专业备案/审批结果 + 学位授权审核结果** | bulk PDF/Excel on moe.gov.cn; gov.cn query tool search-only | **not published** | undergrad catalogue; grad authorization lists | **Chinese only** |
| Turkey | YÖK Atlas / YÖKSİS | HTML; open-data status not established | not established | yes | TR |
| Hungary | Oktatási Hivatal FIR / felvi.hu | HTML | not established | yes | HU |

**Netherlands correction confirmed**: the register is **RIO (Registratie Instellingen en Opleidingen)**, which replaced CROHO/BRIN in 2021, exposed via DUO open onderwijsdata bulk files ("Erkenningenoverzicht ho"), the OOAPI standard (through the SURFeduhub gateway), and as linked open data — NOT studyinnl.org (marketing). studiekeuze123.nl is a downstream consumer, as is Studielink.

**Korea detail**: data.go.kr dataset #15139338 (교육부_대학알리미_학교별 학부_학과(전공) 리스트) is an XLSX of 55,228 rows carrying school → college → department/major → **degree program** and years of study; legal basis Higher Education Act art. 6. Grid downloads are capped — quoted: "그리드 형태의 데이터는 다운로드 건수가 5만 건으로 제한되며, 전체 데이터가 필요한 경우 API를 활용" (use the Open API for the full extract). Companion standard dataset #15107736 exposes an Open API (`api.data.go.kr/openapi/tn_pubr_public_univ_info_api`) with bilingual institution names.

**China detail**: the authoritative programme artifacts are the annual undergraduate 专业目录 (latest 《普通高等学校本科专业目录（2026年）》 published 2026-04-28), the annual per-institution 专业备案和审批结果 (2024 results notice, 2025-04-22, ~62,800 programme placements nationally), and the graduate 学位授权审核结果 (degree-authorization points by institution, issued by MOE / the State Council Academic Degrees Committee). CDGDC (cdgdc.edu.cn) provides technical support and degree verification but the authoritative published lists are MOE's.

**Japan detail**: e-Stat's School Basic Survey (学校基本調査, code 00400001) is aggregate statistics, not a programme list, and its DB API requires a registered application ID. MEXT's annual 全国大学一覧 Excel files list institutions and their faculties/graduate schools (bulk, enumerable) but are Japanese-only and not normalized to programme level. ReaD/researchmap is a researcher directory; JASSO's English-programme finder is marketing.

### Part D — funding families and where (if anywhere) they are indexed

**Government, DESTINATION-ORIGIN (INBOUND; a country funds foreigners to come to it):** DAAD (Germany), GKS/Study in Korea (Korea), CSC (China, via campuschina.org — HTTP 412 to plain requests, WAF-blocked), Türkiye Bursları, Stipendium Hungaricum. **Indexed on each destination's own promotional "study-in-X" portal.** Student applies directly (CSC Type A embassy / Type B university; some require university nomination). Direction = INBOUND. Already held by requester.

**Government, HOME-ORIGIN (OUTBOUND; a country funds its own citizens to go abroad):** e.g. Azerbaijan State Programme, Georgia's International Education Center. **No aggregate index exists** — each sits on the sending government's own site, discoverable only one at a time. Direction = OUTBOUND. This is a genuine index gap. (Prior sweeps mis-indexed the inbound portal — these must be kept strictly apart from destination-origin schemes.)

**Government, THIRD-COUNTRY / BILATERAL (fixed number of places negotiated between two governments):** **No index exists.** Found only in bilateral cultural/education agreements published ad hoc by foreign ministries. Undiscoverable by automated route.

**MULTILATERAL:** Erasmus Mundus Joint Masters — EACEA catalogue at `eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en`; **200 programmes for the 2026 intake** (EEAS, updated 26.11.2025: "This year, there are 200 different masters programmes in a wide variety of fields"); HTML, students apply directly to the consortium. Islamic Development Bank, ADB, OFID, Commonwealth and UN agencies each publish their own scheme pages; **no unified multilateral index** beyond EACEA. Direction mostly inbound-to-consortium / global.

**CORPORATE & FOUNDATION** (the biggest gap and the section's motivating problem):
1. **Authoritative directories that exist:** **360Giving** (UK) — HTTP/JSON API + Datastore + GrantNav; data under open licences with attribution ("360Giving publishers share an open licence for their data… users of the data need to attribute and link to the data source"); grants carry funder + recipient org. **Candid** (US; Foundation Directory + Form 990 data + a family of developer APIs) — authoritative but **paid/closed** (commercial developer APIs). **US IRS Form 990/990-PF** — authoritative and open, but grant-level detail is unstructured. **UK Charity Commission register** — open API, charity-level not scholarship-level. **awardFindR** aggregates individual US foundation grant search endpoints (MacArthur, Mellon, Open Society, Rockefeller, RWJF, Sloan, Templeton, SSRC) — proof that foundation grant databases are scrape-able, but not a single authoritative scholarship directory.
2. **Large private/foundation funders with master's schemes open to Caucasus/Central Asia/Turkey/OIC/NAM students:** Aga Khan Foundation (International Scholarship Programme — nomination/direct hybrid), Mastercard Foundation Scholars Program (**nominated via partner universities** — cannot be a safety option), Open Society Foundations, Rotary Foundation (Global Grants — **nominated via Rotary clubs/districts**), OFID scholarship, IsDB scholarship (inbound to member states).
3. Access route/terms/cadence for these are **published only on each funder's own site**; none exposes an open structured feed of its scholarship schemes. The application-vs-nomination distinction (which decides safety-option eligibility) must be read per scheme.

**Institution-local families** (UNIVERSITY_WIDE, DEPARTMENT_OR_PROGRAM, TUITION_WAIVER, STIPEND_OR_ASSISTANTSHIP, RELOCATION_HOUSING_INSURANCE_TRAVEL, RESEARCH_ECOSYSTEM_PATHWAY): no directory to hunt — the crawler already reaches institution pages. The only central-publication exceptions worth noting: some countries publish **statutory tuition-fee schedules** centrally (Italy's UniversItaly shows fees; Dutch statutory tuition, wettelijk collegegeld, is set nationally), but assistantship/waiver funding is not centrally mandated-disclosed anywhere identified.

**Bilateral country-pair agreements, diaspora/community funds, professional bodies/learned societies, employer study-leave sponsorship:** no systematic index found for any; discoverable only case by case.

## Details — usable / blocked / no-supplier classification

**USABLE NOW (open terms, machine-readable, records carry organisation identifiers):**
- CORDIS (CC BY 4.0; PIC ids) — supranational
- OpenAIRE Graph (CC BY 4.0; ROR/GRID where mapped) — supranational
- UKRI GtR (OGL v2.0; internal GUIDs) — UK
- KAKEN (CC BY; researcher/DOI ids, free appid) — Japan grant side
- ANR via data.gouv.fr (Licence Ouverte; SIREN/RNSR/GRID) — France
- NIH RePORTER, NSF, USASpending (US public domain) — US
- Korea data.go.kr #15139338 + API #15107736 (KOGL) — Korea registry
- Netherlands RIO/DUO (open; OOAPI + linked open data) — NL registry
- Italy MUR ustat "Offerta formativa" (open data) — IT registry
- Finland konfo-backend (open, unauthenticated; licence assumed CC BY 4.0) — FI registry
- 360Giving (open, attribution; funder + recipient) — UK foundation grants

**BLOCKED BY TERMS (permission request needed before an adapter is written):**
- Opintopolku/konfo-backend — no service-specific licence statement (CC BY 4.0 only assumed)
- China MOE catalogues — no reuse licence published ("not published")
- Germany Hochschulkompass, Turkey YÖK, Hungary FIR — access terms not established on the source's own pages

**BLOCKED BY TECHNIQUE (blocking, unobtainable auth, no enumeration, or no structured data):**
- DFG GEPRIS — search-only, no API/bulk, no sitemap enumeration
- NRF Korea — no machine-readable grant feed
- Candid, Dimensions — commercial/closed
- China MOE service endpoints — WAF/HTTP 412/403 on some paths (campuschina.org 412 confirmed); static PDFs reachable but Chinese-only, adding language-extraction cost
- Hochschulkompass — no sitemap; search is the only index (expensive even though reachable)

**NO USABLE SUPPLIER OF ANY KIND — confirm/refute:**
- **Japan: PARTLY REFUTED.** No programme register exists (confirmed, not filled with a weak source), but KAKEN gives a fully usable grant-side supplier (CC BY, English available). MEXT Excel directories are a Japanese-only institution/faculty fallback.
- **Korea: REFUTED.** A genuine KOGL-licensed, enumerable programme register with a degree-level field now exists on data.go.kr, plus NRF/BK21 on the grant side (grant feed itself not open).
- **China: REFUTED for registry.** Official MOE programme catalogues and per-institution approval lists are enumerable (PDF/Excel), but carry no published licence and some endpoints are WAF-blocked and Chinese-only — a terms decision and a heavier extraction pipeline are required.

## Recommendations

**Build first, ranked by LEVERAGE (records per adapter):**
1. **CORDIS bulk (data.europa.eu)** — one adapter, ~40 countries, 56,000+ PIC-identified beneficiaries; the single highest-leverage Tier-0 source.
2. **OpenAIRE Graph dumps** — worldwide funder/org/project graph (368 funders, ~4M grants), CC BY; adopt as the **identifier crosswalk hub** (PIC↔ROR↔GRID) that joins CORDIS grant records to registry institution records.
3. **UKRI GtR API** — clean OGL JSON, carries training-grant/studentship links (directly on-mission for funded graduate training).
4. **Korea data.go.kr programme register (#15139338 + API #15107736)** — closes a priority-1 gap with a degree-level, KOGL-licensed, enumerable register.
5. **Finland konfo-backend** — already proven; ship it, but send Opetushallitus a one-line licence-confirmation request to convert the CC BY assumption into a citable statement.
6. **KAKEN API** — closes Japan on the grant side (CC BY, English available); register a CiNii Application ID.
7. **NIH RePORTER + NSF + USASpending** — US public-domain, documented APIs.
8. **Netherlands RIO/DUO (bulk + OOAPI), Italy MUR ustat, ANR** — solid national registers/grant feeds with open licences.
9. **China MOE catalogues** — enumerable but Chinese-only, no licence, WAF; treat as HTML/PDF bulk with a language-extraction cost and a "terms not established" flag → resolve terms (constraint 1) before writing an adapter.
10. **360Giving** — the one authoritative open foundation-grant source; build it to seed the corporate/foundation family.

**Benchmarks that would change these steps:** if a probe of **SNSF P3**, **SweCRIS (Sweden)**, **NWO**, **TÜBİTAK** or **NKFIH** returns a documented open bulk/API with organisation ids, promote it above the Chinese HTML/PDF route. If Opetushallitus confirms a licence, drop Finland's residual terms flag. If GEPRIS ships a documented API with the July 2026 release, reclassify it from blocked-by-technique to usable. If EACEA ever exposes the Erasmus Mundus catalogue as structured data (currently HTML only), it becomes a high-value multilateral supplier.

## Caveats
- **konfo-backend, Turkey (YÖK), Hungary (FIR/felvi), Germany (Hochschulkompass)**: access terms **not established** per each source's own pages — under constraint 1, an adapter cannot be written until terms are resolved. Hochschulkompass additionally has **no sitemap** (search is the only index).
- **China MOE** publishes no reuse licence ("not published") and WAF-blocks some endpoints (campuschina.org confirmed HTTP 412); static PDF/Excel paths are reachable but Chinese-only.
- **Japan has no programme register** — confirmed, not filled with a weak source. KAKEN covers the grant side only.
- **NRF Korea, GEPRIS, Dimensions, Candid**: blocked by technique or terms (no open feed / commercial).
- **SNSF, NWO, Vetenskapsrådet, TÜBİTAK, NKFIH** were not verified this pass (search budget exhausted) — labelled UNVERIFIED hypotheses, not findings; probe next.
- **Identifier fragmentation is the central integration risk**: CORDIS uses EU PIC, ANR uses SIREN/RNSR/GRID, national registries use local codes or ROR; **no single published crosswalk covers all**. There is no published PIC↔ROR mapping; OpenAIRE and ROR are the practical bridges and should be adopted as the canonical join layer.
- The GEPRIS "July 2026", UKRI studentship-portal "Q1 2026-27 / July 2026 update", and China "2026 catalogue" items are dated statements from the sources; the first two are forward-looking commitments, not yet-delivered facts.

## Funding families with NO index (undiscoverable by any automated route)
1. **Government HOME-ORIGIN (outbound national scholarships)** — no aggregate index.
2. **Government THIRD-COUNTRY / BILATERAL** — no index at all.
3. **Corporate & foundation master's schemes** — no authoritative structured *scheme* directory (360Giving/Candid/990 give grant history, not a catalogue of scholarship schemes); each scheme lives on its funder's own site.
4. **Diaspora/community funds, professional bodies/learned societies, employer study-leave sponsorship** — no systematic index.
5. **Institution-local waivers/assistantships** — not centrally published anywhere except partial statutory fee schedules (Italy's UniversItaly, Dutch statutory tuition).