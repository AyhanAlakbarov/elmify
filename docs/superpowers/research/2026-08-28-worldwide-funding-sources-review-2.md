# **Architectural Blueprint and Legal Discovery Framework for Global Master's Programme Funding**

The engineering of an automated discovery engine to map the global ecosystem of funded master's programmes necessitates a highly orchestrated data ingestion strategy. This architecture must seamlessly bridge the ontological gap between Tier 0 systems, which operate as the primary ledgers for research capital and grant disbursements, and Tier 1 systems, which function as the official national registries for accredited educational degrees. Operating this federated query network requires rigorous adherence to international data reuse directives, the precise mapping of application programming interface (API) typologies, and the resolution of deeply fragmented persistent identifier (PID) schemas. The following analysis exhaustively deconstructs the technical reachability, semantic interoperability, and legal parameters governing the acquisition of this global dataset.

## **Part A: Legal Frameworks and Access Terms Resolution**

The ingestion of metadata from governmental and supranational portals is dictated by a complex matrix of copyright directives, open data mandates, and portal-specific terms of use. The explicit resolution of these terms determines the legal viability of automated retrieval and the persistent storage of retrieved payloads within a centralized discovery engine.

### **European Union Platforms: CORDIS and data.europa.eu**

The European Commission operates under a unified reuse policy implemented by Commission Decision 2011/833/EU of 12 December 2011 on the reuse of Commission documents1. The Community Research and Development Information Service (CORDIS) and the data.europa.eu portal both mandate this specific directive for the downstream reuse of European Union data1.  
The terms of access are formally published at https://cordis.europa.eu/about/legal and https://data.europa.eu/en/legal-notice1. Both platforms release their editorial content and high-value datasets under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence1. The explicit governing clause states: "Unless otherwise noted (e.g. in individual copyright notices), the reuse of the editorial content on this website owned by the EU is authorized under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence. This means that reuse is allowed, provided appropriate credit is given and any changes are indicated"1.  
Regarding automated retrieval and storage, explicit clauses permitting or prohibiting machine-driven scraping or API polling are not published in either legal notice1. However, the CC BY 4.0 licence implicitly allows for bulk retrieval, caching, and persistent storage in an automated discovery engine, provided that downstream users are presented with appropriate attribution to the European Union and the specific portal1. Both portals explicitly note third-party exceptions, stating that "To use or reproduce content that is not owned by the EU, you may need to seek permission directly from the respective rightholders," which places the burden of copyright clearance on the discovery engine for embedded external intellectual property1.

### **France: Agence Nationale de la Recherche (ANR)**

The French national research agency (ANR) has executed a strategic shift towards open data publishing, making its funded project data available through the data.gouv.fr platform5. The terms of access are formally hosted at https://www.data.gouv.fr/organizations/agence-nationale-de-la-recherche7.  
ANR datasets are published under the "Licence Ouverte v2.0 (Etalab)"8. Explicit clauses governing automated retrieval and permanent storage are not published in the ANR legal notices8. The Etalab Open Licence 2.0 is a highly permissive framework designed for sovereign data interoperability, functionally mirroring CC-BY. Because there are no clauses published that throttle or prohibit automated scraping, the discovery engine may continuously poll these datasets without violating established terms8.

### **Finland: Opintopolku (Konfo-Backend)**

Opintopolku (Studyinfo) is the official Finnish national registry for educational programmes, maintained by the Finnish National Agency for Education (Opetushallitus). The system relies on a Single Page Application (SPA) architecture supported by the konfo-backend10.  
The primary terms of use are published at https://www.oph.fi/fi/tietosuoja and https://opintopolku.fi/konfo/fi/sivu/tietosuojaselosteet-ja-evasteet12. The public-facing terms focus heavily on cookie consent and privacy, featuring the clause: "Opetushallitus edellyttää, että hyväksyt evästeiden käytön evästebannerissa, voidaksesi käyttää Opintopolku \-verkkopalveluamme" (The National Agency for Education requires that you accept the use of cookies in the cookie banner to use our Studyinfo online service)13. While explicit clauses regarding automated retrieval via scripts are not published in the consumer-facing terms, the internal architectural documentation explicitly dictates the provision of open data, stating: "Palvelukokonaisuuden avoin tieto tarjotaan (open data)"15. Furthermore, the konfo-backend source code and architecture are governed by the European Union Public Licence (EUPL)10. Because the external endpoints are explicitly documented as "Ulkoiset (eivät vaadi autentikaatiota)" (External: do not require authentication), automated retrieval and storage are fully permitted under the agency's overarching open data mandate10.

## **Part B: Global Searchable Grant Databases (Tier 0\)**

Tier 0 grant databases function as the origin nodes for research capital flows. Identifying and querying these systems globally allows an automated engine to isolate funded research trajectories that eventually support master's level research assistants, tuition waivers, or programmatic scholarships.

### **United States: NIH RePORTER**

The National Institutes of Health (NIH) operates the RePORTER system to track biomedical research funding allocations. The exact endpoint URL for programmatic access is https://api.reporter.nih.gov/v2/projects/search, which requires a POST request16. Access terms dictate that the data is in the public domain, and automated retrieval permissions are implicitly granted without authentication requirements17.  
Enumeration methods are highly constrained by the API's architecture. The maximum number of records returned per query batch is 10,00019. Furthermore, the absolute maximum record index (offset) allowable by the API is 9,99919. Rate limits are not published. To bypass the index limitation, automated retrieval systems cannot rely on simple offset pagination; instead, they must iteratively chunk queries using sort parameters (e.g., varying by sort\_field and sort\_order) or slice the requests by narrow date ranges, such as individual fiscal years19.  
Specific record contents include project abstracts, principal investigators, award amounts, administering institutes, and funding mechanisms (e.g., R01 equivalents)17. Resolvable beneficiary IDs (such as UEI or DUNS numbers) are occasionally embedded in the organization objects, but beneficiary websites are not published21. The record language is exclusively English17. The coverage cadence is updated continuously, though finalized institutional fiscal year data is consolidated annually17. Degree levels and funding direction metrics are not published directly within the payload, requiring natural language processing (NLP) to infer master's level involvement from the abstracts.

### **United States: NSF Award Search**

The National Science Foundation (NSF) serves as the primary funding apparatus for non-medical scientific and engineering research. The exact endpoint URL is api.nsf.gov/services/v1/awards.{format}, accepting XML, JSON, and JSONP formats22. Access terms place the data in the public domain, with no restrictive clauses published regarding automated access18.  
Enumeration methods are severely restricted. The API enforces a strict pagination limit of 25 results per page (managed via the rpp parameter) and enforces an absolute maximum retrieval ceiling of 3,000 results per overall search22. Rate limits are not published. A discovery engine must deeply parameterize sequential searches by specific date ranges to extract the entire database without hitting the 3,000-record threshold22.  
Specific record contents feature award abstracts, funding directorates, and awardee organizations22. Resolvable beneficiary IDs and explicit beneficiary websites are not published natively in the responses22. The record language is English. The coverage extends historically back to 198922. Degree levels and funding direction tags are not published as standardized enumerations.

### **United Kingdom: Gateway to Research (GtR)**

UK Research and Innovation (UKRI) publishes all funded projects across seven research councils and Innovate UK via the Gateway to Research portal23. The exact endpoint URLs were updated in June 2024 following a system migration. The core projects endpoint is https://gtr.ukri.org/api/projects, with relational endpoints located at /api/organisation, /api/person, and /api/publication24.  
Access terms stipulate that data is released under the Open Government Licence (OGL 3.0)25. Explicit automated retrieval is permitted, but the legal notice includes a specific clause: "We expect users of this API to follow web etiquette and not to flood the service with requests and make it inoperable for other users. We would like users of the API to respect this freedom in a similar way that search engines respect the sites they index and moderate the requests they make in any particular time window"27. Hard rate limits are not published.  
Enumeration methods rely on hypermedia link headers conforming to RFC 5988\. Pagination data is returned dynamically in the Link-Records, Link-Pages, and Link HTTP response headers. Page sizes can be dynamically set between 25 and 100 via the fetchSize parameter27.  
Specific record contents include project titles, abstracts, project durations, awarded amounts, collaborating organisations, and linked publications23. Beneficiary websites are not published. Resolvable beneficiary IDs do not feature native ROR identifiers, but ORCID iDs are provided for named researchers23. The record language is English. The coverage cadence operates on a strict quarterly cycle, scheduled for release in the second week of January, April, July, and October23. Degree levels are not published explicitly, and funding directions are assumed domestic unless classified under the GCRF and Newton bilateral programmes24.

### **Sweden: Swecris**

Swecris, administered by the Swedish Research Council, aggregates funding datasets from both governmental and private Swedish research funding bodies into a unified national architecture29. The exact endpoint URL for Swagger documentation is https://swecris-api.vr.se/index.html, utilizing OAS3 standards at base routes like /v{version}/projects and /v{version}/fundings30.  
Access terms are fully open. The explicit quoted clause states: "You may use the information in Swecris internally and publicly, but we appreciate it if you in connection with the data tell that it comes from Swecris"31. Automated retrieval requires a bearer token; a rolling public token (e.g., VRSwecrisAPI2026-1, valid from 9 April 2026\) is provided for immediate headless access, though production engines must register for a unique persistent key29. Rate limits are not published.  
Enumeration methods follow standard OAS3 REST parameters30. Specific record contents display funding periods, coordinating organizations, project leaders, award amounts, and Subject Classifications adhering to the SSIF2025 standards31. Resolvable beneficiary IDs are limited; ORCID is included if provided by the funder, but organization websites and ROR IDs are not published31. The record language varies between Swedish and English31. Coverage extends from 2008 onwards, with data updated on an ongoing cadence31. Degree levels are not published.

### **Japan: KAKEN (Grants-in-Aid for Scientific Research)**

Operated by the National Institute of Informatics (NII), KAKEN is the primary ledger for Japanese government-funded academic research. The exact endpoint URLs rely on an OpenSearch API framework, available at https://kaken.nii.ac.jp/opensearch/ for project data and https://nrid.nii.ac.jp/opensearch/ for researcher data32. Access requires an Application ID appended as a URL parameter in the format appid=xxxxxxxx32.  
Access terms (Restrictions on Published Information) permit reuse and automated retrieval, provided explicit source attribution is injected into the engine's interface. The quoted clause requires the format: "Source: KAKEN: Grants-in-Aid for Scientific Research Database (The National Institute of Informatics)(https://kaken.nii.ac.jp/)"33. Rate limits are not published.  
Enumeration methods for the API are standard OpenSearch parameter queries; however, NII provides a critical architectural alternative by hosting master data XML files for direct download, bypassing iterative API pagination entirely for bulk ingestion32. Specific record contents feature project titles, budget allocations, research abstracts, researcher numbers, and DOIs33. Beneficiary websites and organization IDs are not published. The record language is bilingual, supporting Japanese and English34. Coverage cadence and degree levels are not published.

### **South Korea: NTIS (National Science & Technology Information Service)**

The NTIS platform tracks national research and development projects and capital allocation in South Korea. The primary interfaces are exposed via www.ntis.go.kr and the national data portal data.go.kr35. Access terms stipulate that Open API access requires a registered API key obtained through data.go.kr36.  
Because navigating the bureaucratic registration for foreign data engines can introduce latency, third-party developers have successfully constructed a *Hypothesis*: Model Context Protocol (MCP) servers (e.g., vertical-mcp-ntis-mcp) can be deployed to wrap the NTIS search portal directly, allowing automated engines to bypass strict API key requirements for retrieval by interacting with the portal as a virtualized client37. Rate limits, pagination methods, and specific record metadata fields are not published in the provided documentation.

### **China: NSFC (National Natural Science Foundation of China)**

The NSFC operates as China's principal state funding agency for basic and applied research. The primary web portal is located at kd.nsfc.gov.cn38. Explicit access terms, open API schemas, and automated retrieval guidelines are not published39.  
Because official APIs are absent, the engine must rely on a *Hypothesis*: An internal, undocumented API endpoint, https://kd.nsfc.gov.cn/baseQuery/supportQuery, has been utilized by external bibliometric researchers to extract yearly funding topologies and may accept programmatic POST requests39. Rate limits and specific enumeration methods are not published. Record contents support broad categorization like the Young Scientists Fund and General Program, but granular beneficiary IDs, websites, and specific degree levels are not published40.

### **Germany: GEPRIS (German Research Foundation \- DFG)**

GEPRIS contains details of research projects funded by the DFG, hosted at gepris.dfg.de41. An official REST or GraphQL API endpoint is not published. Furthermore, the DFG does not publish terms permitting or restricting automated scraping. Developers currently bypass the lack of an API by relying on headless browser scraping architectures (e.g., Python Scrapy frameworks targeting HTML DOM elements)42. Due to the engine's strict operational constraint prohibiting the writing of adapters without established terms, GEPRIS must be categorized as technically blocked for automated API ingestion.

## **Part C: Official National Degree Registries (Tier 1\)**

Tier 1 sources represent the ultimate destination of prospective master's students: the official national ledgers of accredited degree programmes. Reconciling Tier 0 grant data with Tier 1 degree data requires parsing highly localized educational schemas.

### **The Netherlands: Open Onderwijsdata (DUO)**

Dienst Uitvoering Onderwijs (DUO) publishes the underlying, authoritative register of all accredited higher education in the Netherlands. The engine must bypass consumer-facing marketing portals and directly query the "Centraal Register Opleidingen Hoger Onderwijs" (CROHO) and "Registratie Instellingen en Opleidingen" (RIO) structures, exposed through the onderwijsdata.duo.nl portal43.  
The exact endpoint URLs rely on the CKAN DataStore search API architecture. An example hypothesis endpoint for querying institutions is https://onderwijsdata.duo.nl/api/3/action/datastore\_search?resource\_id=bf1da9c6-c688-4873-91b1-b12c9ac2c13245. Access terms indicate the data is released under Dutch Open Data principles (functionally equivalent to a CC0 public domain dedication), and automated retrieval permissions are explicitly implied by the provision of the API43.  
Enumeration methods for the CKAN endpoints utilize the limit and q (query) parameters for pagination (e.g., limit=5)43. Rate limits are not published. Specific record contents include detailed institutional addresses, enrollment metrics segmented by geographic and demographic features (e.g., gender, academic year), and specific degree classifications isolating higher professional education (HBO) from academic university education (WO)44. Resolvable institution codes (BRIN codes) are embedded natively in the payloads, facilitating cross-referencing46. Teaching languages, master's specific tags, and direct university web links are not published in these specific API responses.

### **France: RNCP and Mon Master**

The French higher education data infrastructure splits its ontological focus across the Répertoire National des Certifications Professionnelles (RNCP) and the centralized application platform "Mon Master".  
The exact endpoint URL for Mon Master data is exposed as a bulk JSON download on data.gouv.fr (e.g., the file fr-esr-mon\_master.json)48. The RNCP data is exposed via REST APIs, such as the https://entreprise.api.gouv.fr/catalogue/carif\_oref/certifications\_qualiopi\_france\_competences endpoint49. Access terms for Mon Master are standard French open data provisions, while the RNCP data is explicitly licensed under the Licence Ouverte / Open Licence version 2.050. Automated retrieval is permitted for both. Rate limits are not published.  
Specific record contents for Mon Master include candidacies, admission proposals, and establishment responses, providing a statistical overview of programme demand48. The RNCP payload is highly granular, containing certification objectives, specific prerequisites (e.g., requiring an existing Level 6 RNCP diploma for entry into Level 7 master's equivalent programmes), ROME codes, and specific sector identifiers51. Teaching languages and direct university links are not published.  
Crucially, to resolve an abstract RNCP code to a physical master's programme, the discovery engine cannot rely on a single endpoint. It must ingest and process the "Table de passage codes certifications et formations," a mapping dataset that crosswalks RNCP codes to the Idéo (ONISEP) database and Certif Info (CI) codes, thereby bridging the gap between certification standards and physical institutions52.

### **Finland: Opintopolku (Konfo)**

Opintopolku operates as a Single Page Application (SPA), meaning traditional REST API routes are obscured behind front-end rendering. However, the exact endpoint URL for the backend is OpenAPI-compliant and reachable at https://opintopolku.fi/konfo-backend/swagger/index.html\#/External10. Access terms dictate an EUPL open data licence10. Rate limits are not published.  
Enumeration methods are standard Swagger/OpenAPI patterns. Specific record contents return JSON payloads describing institutional offerings, target groups (Hakukohderyhmä), and localized study paths managed through the Kouta subsystem10. Explicit degree levels, teaching languages, and institution links are not published in the provided documentation snippets.

### **Italy: MIUR (Legacy System)**

Historically, Italian university degree programme data was aggregated via the Ministry of University and Research (MIUR) OFFF database. The exact endpoint URL was historically located at http://offf.miur.it53. However, this represents a legacy dataset structure lacking a modern JSON or XML REST API architecture53. Data retrieval from this legacy system requires significant web scraping architectures or reliance on undocumented regional API portals. Access terms, rate limits, and record contents are not published. Because custom scraping adapters violate the engine's constraints, Italy is classified as technically blocked pending modernization to national open data standards.

## **Part D: Typologies of Funding Families**

An automated discovery engine must index master's funding schemes by separating them structurally. Conflating a foreign-aid scholarship with an internal domestic grant poisons the data ontology and misleadingly presents opportunities to prospective students. Government schemes must be strictly labeled.

### **(a) Destination-Origin (Inbound Funding)**

Destination-origin schemes represent government-backed capital allocations where the host country provides funding to attract foreign master's students to their domestic institutions, or funds domestic institutions to hire researchers globally.

* **United Kingdom:** UK Research and Innovation (UKRI) grants frequently support project-specific master's stipends or research assistantships at UK universities23. These are highly discoverable via the GtR Tier 0 database27.  
* **Sweden:** The Swedish Research Council funds projects that attract international talent to Swedish universities, discoverable via the Swecris API31.

### **(b) Home-Origin (Outbound Funding)**

Home-origin schemes represent sovereign wealth or government programs aimed at sending domestic students abroad to acquire master's degrees, often bound by mandatory return-of-service clauses.

* **Georgia:** The International Education Center (IEC) manages the nation's outbound funding strategy. The IEC acts as a centralized node for Georgian state scholarships, coordinating 9 specific scholarship programs54. While data is highly localized, CSV extracts exist on third-party migration research portals54. The primary endpoint is the web portal iec.gov.ge55.  
* **Azerbaijan:** The "State Program on Increasing the International Competitiveness of the Higher Education System in the Republic of Azerbaijan" provides full funding for Azerbaijani students studying at top-tier international institutions56.  
* **Discoverability Constraints:** Home-origin outbound programs are only moderately discoverable. They rarely feature structured REST APIs and usually require scraping HTML news announcements or PDF government decrees (e.g., scanning edu.gov.az for scholarship intake announcements)56.

### **(c) Third-Country / Bilateral Funding**

Bilateral schemes are joint funding ventures between two sovereign nations, designed to promote specific geopolitical or scientific collaborations, allowing student mobility between the two states.

* **Ireland and China:** The SFI-NSFC Partnership Programme (Science Foundation Ireland and the National Natural Science Foundation of China) exemplifies this category. Ireland funds the domestic activities and team based in Ireland, while the NSFC funds the research activities in China58.  
* **Discoverability Constraints:** These schemes are architecturally complex to track. They require the discovery engine to cross-reference two distinct Tier 0 databases simultaneously (e.g., verifying a grant identifier in the NSFC kd.nsfc.gov.cn ledger against an SFI Irish ledger to confirm the dual-funding status)39. Bilateral scholarship programs, such as the Serbia-Azerbaijan Intergovernmental Scholarship Program, are also published via news bulletins rather than APIs59.

### **Centrally Published Institution-Local Awards**

In most jurisdictions, university-specific local awards (e.g., a specific endowment at a single college) are not exposed to central government APIs. However, certain jurisdictions mandate that independent universities report institution-local awards to a central registry.

* **Sweden:** Swecris provides a unique architectural advantage. While primarily handling state research funders, it successfully indexes grants from specific local and private Swedish funding bodies into a single, centralized national API architecture, allowing the discovery engine to capture institution-local awards without writing hundreds of custom university adapters29.

### **Private Foundation Master's Schemes (Regional Targeting)**

Private foundation funding operates outside state architectures and relies on two primary application vectors: *direct application* (the student applies directly to the foundation) and *nominated application* (the university nominates an already-enrolled student).

* **Islamic Development Bank (IsDB):** The IsDB Scholarship Programme features regional targeting, specifically designed for Muslim communities situated in non-member countries60.  
* **Discoverability Constraints:** Private foundations routinely lack machine-readable databases or open APIs, rendering their master's schemes largely undiscoverable to automated engines without manual data entry or bespoke web scraping.

## **Entity Resolution and Identifier Crosswalks: The PIC Disagreement**

A fundamental architectural challenge in federating Tier 0 (grants) and Tier 1 (degrees) is entity resolution. An engine cannot reliably link a multi-million euro grant to a specific master's degree without a persistent identifier (PID).  
The Research Organization Registry (ROR) serves as the global gold standard for mapping institutions. The ROR schema (JSON) embeds an external\_ids object that maps equivalent organization IDs, including GRID, ISNI, Wikidata, and Crossref Funder IDs, to a single unified ROR ID21.  
However, a severe ontological disagreement exists regarding the European Union's Participant Identifier Code (PIC), which is the primary identifier used in systems like CORDIS to denote grant beneficiaries. ROR's strict schema policy mandates the inclusion of only globally unique persistent identifiers. Consequently, ROR explicitly refuses to host national or regional identifiers natively, meaning PIC codes are purposefully excluded from the ROR external\_ids payload21.  
To resolve this conflict and successfully link a CORDIS grant (using a PIC) to an institution's master's programme (using a ROR or a national ID like the Dutch BRIN46), the discovery engine must ingest third-party identifier crosswalks. Specifically, the engine must rely on community-maintained CORDIS-to-ROR mapping tables hosted externally on platforms like GitHub to bridge the gap21.

## **Comprehensive Synthesis and Ranking Matrices**

### **Table 1: Usable Sources Ranked by API Leverage**

| Rank | Source Name | Country | Exact Endpoint / Interface | Rate Limits / Enumeration | Access Terms & Licence |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **1** | **DUO Open Onderwijsdata** | Netherlands | api/3/action/datastore\_search \[cite: 44\] | CKAN limit params. Rate Limit: Not published43. | Open Data (Implied CC0). Auto-retrieval permitted43. |
| **2** | **Swecris** | Sweden | swecris-api.vr.se/index.html (OAS3)30 | Token: VRSwecrisAPI2026-1. Rate Limit: Not published29. | Open access. Auto-retrieval permitted31. |
| **3** | **UKRI Gateway to Research** | United Kingdom | /api/projects \[cite: 24\] | Link headers, fetchSize 25-100. Limit: "web etiquette"27. | Open Government Licence (OGL 3.0)25. |
| **4** | **NIH RePORTER** | United States | /v2/projects/search \[cite: 16\] | Max offset 9,999. Max batch 10,00019. Rate: Not published. | Public Domain18. Auto-retrieval permitted. |
| **5** | **NSF Award Search** | United States | api.nsf.gov/services/v1/awards \[cite: 22\] | Max 25/page, total 3,000 limit22. Rate: Not published. | Public Domain18. Auto-retrieval permitted. |
| **6** | **Opintopolku (Konfo)** | Finland | /konfo-backend/swagger/index.html\#/External \[cite: 10\] | SPA API. Limits: Not published. | EUPL / Open Data mandate10. |
| **7** | **KAKEN** | Japan | kaken.nii.ac.jp/opensearch/ \[cite: 32\] | XML OpenSearch. Limits: Not published. | Requires specific citation for UI33. |
| **8** | **France Compétences (RNCP)** | France | data.gouv.fr API & XML dumps50 | Standard REST. Limits: Not published. | Licence Ouverte v2.0 (Etalab)50. |

### **Table 2: Blocked, Rate-Throttled, and Undiscoverable Sources**

| Source Name | Country / Entity | Blocking Mechanism / Reason | Resolution / Hypothesis |
| :---- | :---- | :---- | :---- |
| **DFG GEPRIS** | Germany | No REST API. Relies entirely on HTML scraping42. | Blocked due to constraints prohibiting custom HTML adapters. |
| **MIUR OFFF** | Italy | Legacy architecture (http://offf.miur.it) lacking modern JSON payloads53. | Blocked. Await modernization to national open data standards. |
| **NSFC** | China | Strict reliance on web portals (kd.nsfc.gov.cn). APIs are not publicly documented38. | *Hypothesis*: Monitor baseQuery/supportQuery endpoint for JSON structures39. |
| **NTIS** | South Korea | Open API requires authorized API key generation via a data portal36. | *Hypothesis*: Requires MCP wrapping techniques for headless bypass37. |

### **Table 3: Undiscoverable Funding Families**

| Funding Family | Structure Typology | Architectural Barrier to Automated Discovery |
| :---- | :---- | :---- |
| **IsDB Scholarship** | Private Foundation | Direct student applications processed through unindexed, closed-system portals60. |
| **Azerbaijan State Program** | (b) Home-Origin | Program intakes and student allocations are published via static HTML news bulletins56. |
| **Georgia IEC Scholarships** | (b) Home-Origin | Centralized state portal relies on CSV downloads rather than a machine-readable REST interface54. |

#### **Works cited**

> 1. Legal notice | CORDIS | European Commission \- Europa.eu, [https://cordis.europa.eu/about/legal](https://cordis.europa.eu/about/legal)  
> 2. ETIP SNET \- European Commission, [https://ec.europa.eu/newsroom/etipsnet\_bridge/redirection/link/916120/en/mainURL](https://ec.europa.eu/newsroom/etipsnet_bridge/redirection/link/916120/en/mainURL)  
> 3. Legal notice | data.europa.eu, [https://data.europa.eu/en/legal-notice](https://data.europa.eu/en/legal-notice)  
> 4. Legal notices: Copyright \- About Us \- Publications Office of the EU, [https://op.europa.eu/en/web/about-us/legal-notices/publications-office-of-the-european-union-copyright](https://op.europa.eu/en/web/about-us/legal-notices/publications-office-of-the-european-union-copyright)  
> 5. L'Agence nationale de la recherche lance data anr, une plateforme, [https://www.cap-recherche.fr/lagence-nationale-de-la-recherche-lance-data-anr-une-plateforme-interactive-dediee-au-partage-de-ses-donnees-ouvertes/](https://www.cap-recherche.fr/lagence-nationale-de-la-recherche-lance-data-anr-une-plateforme-interactive-dediee-au-partage-de-ses-donnees-ouvertes/)  
> 6. Données et visualisations \- ANR, [https://anr.fr/fr/projets-finances-et-impact/donnees-et-visualisations/](https://anr.fr/fr/projets-finances-et-impact/donnees-et-visualisations/)  
> 7. Agence nationale de la recherche ANR \- Data Gouv, [https://www.data.gouv.fr/organizations/agence-nationale-de-la-recherche](https://www.data.gouv.fr/organizations/agence-nationale-de-la-recherche)  
> 8. Répertoire national des structures de recherche \- RNSR, [https://data.enseignementsup-recherche.gouv.fr/explore/dataset/fr-esr-repertoire-national-structures-recherche/?refine.numero\_national\_de\_structure=196217769J%3B\&flg=fr-fr\&start=0](https://data.enseignementsup-recherche.gouv.fr/explore/dataset/fr-esr-repertoire-national-structures-recherche/?refine.numero_national_de_structure=196217769J;&flg=fr-fr&start=0)  
> 9. Appels à projets ANR \- Projets retenus et participants identifiés, [https://data.enseignementsup-recherche.gouv.fr/explore/dataset/fr-esr-aap-anr-projets-retenus-participants-identifies/table/?flg=fr-fr](https://data.enseignementsup-recherche.gouv.fr/explore/dataset/fr-esr-aap-anr-projets-retenus-participants-identifies/table/?flg=fr-fr)  
> 10. Uusi opintopolku.fi koulutusinformaatio (konfo) \- Eduuni-wiki, [https://wiki.eduuni.fi/pages/viewpage.action?pageId=256889616](https://wiki.eduuni.fi/pages/viewpage.action?pageId=256889616)  
> 11. Konfo-backend: API Documentation \- Opintopolku, [https://opintopolku.fi/konfo-backend/redoc/index.html](https://opintopolku.fi/konfo-backend/redoc/index.html)  
> 12. Tietosuojakäytäntö | Opetushallitus, [https://www.oph.fi/fi/tietosuoja](https://www.oph.fi/fi/tietosuoja)  
> 13. Tietosuojaselosteet ja evästeet \- Opintopolku, [https://opintopolku.fi/konfo/fi/sivu/tietosuojaselosteet-ja-evasteet](https://opintopolku.fi/konfo/fi/sivu/tietosuojaselosteet-ja-evasteet)  
> 14. Oma Opintopolku, [https://opintopolku.fi/oma-opintopolku/](https://opintopolku.fi/oma-opintopolku/)  
> 15. Opetushallituksen palvelu- ja prosessikokonaisuus \- Eduuni-wiki, [https://wiki.eduuni.fi/spaces/ophPPK/pages/450075519/Opetushallituksen+palvelu-+ja+prosessikokonaisuus](https://wiki.eduuni.fi/spaces/ophPPK/pages/450075519/Opetushallituksen+palvelu-+ja+prosessikokonaisuus)  
> 16. NIH RePORTER Grant Funding & Procurement Signals \- Apify, [https://apify.com/nintendo424/nih-grant-procurement-signal-monitor](https://apify.com/nintendo424/nih-grant-procurement-signal-monitor)  
> 17. NIH RePORTER vs. Grants.gov: What's the Difference? \- CASRAI, [https://casrai.org/guides/nih-award-search-nih-reporter](https://casrai.org/guides/nih-award-search-nih-reporter)  
> 18. 5 Free US Health Data Sources Every Developer Should Know, [https://www.myfitbyte.com/blog/us-health-data-sources-for-developers](https://www.myfitbyte.com/blog/us-health-data-sources-for-developers)  
> 19. Help for package repoRter.nih \- CRAN, [https://cran.r-project.org/web/packages/repoRter.nih/refman/repoRter.nih.html](https://cran.r-project.org/web/packages/repoRter.nih/refman/repoRter.nih.html)  
> 20. The NIH Research Centers in Minority Institutions (RCMI) \- PMC, [https://pmc.ncbi.nlm.nih.gov/articles/PMC12652206/](https://pmc.ncbi.nlm.nih.gov/articles/PMC12652206/)  
> 21. Map other organization IDs to ROR IDs \- ReadMe, [https://ror.readme.io/docs/mapping](https://ror.readme.io/docs/mapping)  
> 22. How to Use NSF Award Search: Step-by-Step \- CASRAI, [https://casrai.org/guides/nsf-award-search](https://casrai.org/guides/nsf-award-search)  
> 23. Gateway to Research (GtR): UKRI Portal \- CASRAI, [https://casrai.org/dictionary/term/gateway-to-research](https://casrai.org/dictionary/term/gateway-to-research)  
> 24. Gateway to Research Additions and Modifications \- GtR, [https://gtr.ukri.org/resources/releasehistory.html](https://gtr.ukri.org/resources/releasehistory.html)  
> 25. Introducing the Gateway to Research (GtR) website, [https://gtr.ukri.org/resources/about.html](https://gtr.ukri.org/resources/about.html)  
> 26. Grant \- ALB \- UKRI \- InGAME: Innovation for ... \- 360Giving GrantNav, [https://grantnav.threesixtygiving.org/grant/360G-cabinetoffice-GA-214378](https://grantnav.threesixtygiving.org/grant/360G-cabinetoffice-GA-214378)  
> 27. GTRAPI documentation \- UKRI Gateway to Research, [https://gtr.ukri.org/resources/gtrapi.html](https://gtr.ukri.org/resources/gtrapi.html)  
> 28. GtR Data Explained \- UKRI Gateway to Research, [https://gtr.ukri.org/resources/data.html](https://gtr.ukri.org/resources/data.html)  
> 29. Swecris API \- Swedish Research Council \- Vetenskapsrådet, [https://www.vr.se/english/swecris/swecris-api.html](https://www.vr.se/english/swecris/swecris-api.html)  
> 30. Swagger UI, [https://swecris-api.vr.se/index.html](https://swecris-api.vr.se/index.html)  
> 31. Swecris \- Base platform for data processing and analysis, [https://www.vr.se/english/swecris.html?project=2021-03638\_Vinnova](https://www.vr.se/english/swecris.html?project=2021-03638_Vinnova)  
> 32. KAKEN \- Metadata and API | Support Academic Information Services, [https://support.nii.ac.jp/en/kaken/api/api\_outline](https://support.nii.ac.jp/en/kaken/api/api_outline)  
> 33. KAKEN – Service Information: Terms of Use, [https://support.nii.ac.jp/en/kaken/about/terms](https://support.nii.ac.jp/en/kaken/about/terms)  
> 34. Development of an open data environment and system infrastructure, [https://cir.nii.ac.jp/crid/1040282256982417920?lang=en](https://cir.nii.ac.jp/crid/1040282256982417920?lang=en)  
> 35. Service Diagnosis and Improvement Measures Based on National, [http://apjcriweb.org/content/vol11no12/7.pdf](http://apjcriweb.org/content/vol11no12/7.pdf)  
> 36. DMZ 포털 전면 개통, 오픈행사(7.27.\~28.) 개최 \> 보도자료 \> 통일부, [https://www.unikorea.go.kr/web/unikorea/bbs/bbs\_0000000000000004/59704](https://www.unikorea.go.kr/web/unikorea/bbs/bbs_0000000000000004/59704)  
> 37. @vertical-mcp/ntis-mcp | MCP Servers · LobeHub, [https://lobehub.com/mcp/vertical-mcp-ntis-mcp](https://lobehub.com/mcp/vertical-mcp-ntis-mcp)  
> 38. A Review of Open Research Data Policies and Practices in China, [https://digitalcommons.unl.edu/cgi/viewcontent.cgi?article=1331\&context=scholcom](https://digitalcommons.unl.edu/cgi/viewcontent.cgi?article=1331&context=scholcom)  
> 39. A Review of Open Research Data Policies and Practices in China, [https://www.researchgate.net/publication/348882713\_A\_Review\_of\_Open\_Research\_Data\_Policies\_and\_Practices\_in\_China](https://www.researchgate.net/publication/348882713_A_Review_of_Open_Research_Data_Policies_and_Practices_in_China)  
> 40. NSFC: China Funding Overview for Researchers \- CASRAI, [https://casrai.org/guides/nsfc-china-funding-overview](https://casrai.org/guides/nsfc-china-funding-overview)  
> 41. Research Information Systems \- DFG, [https://www.dfg.de/en/funded-projects/information-systems](https://www.dfg.de/en/funded-projects/information-systems)  
> 42. primeapple/dfg-gepris-crawler: A project to continuously crawl the, [https://github.com/primeapple/dfg-gepris-crawler](https://github.com/primeapple/dfg-gepris-crawler)  
> 43. Adressen bevoegde gezagen mbo \- Open Onderwijsdata \- DUO, [https://onderwijsdata.duo.nl/datasets/adressen\_mbo/resources/9aedc028-b38b-48d7-a158-7fd360d5fc30](https://onderwijsdata.duo.nl/datasets/adressen_mbo/resources/9aedc028-b38b-48d7-a158-7fd360d5fc30)  
> 44. Ingeschrevenen hoger beroepsonderwijs niveau opleiding in het, [https://onderwijsdata.duo.nl/datasets/p01hoinges/resources/7761bd6a-b87b-4389-a943-829872116f92](https://onderwijsdata.duo.nl/datasets/p01hoinges/resources/7761bd6a-b87b-4389-a943-829872116f92)  
> 45. Adressen van instellingen in het hoger onderwijs, [https://onderwijsdata.duo.nl/datasets/adressen\_ho/resources/bf1da9c6-c688-4873-91b1-b12c9ac2c132](https://onderwijsdata.duo.nl/datasets/adressen_ho/resources/bf1da9c6-c688-4873-91b1-b12c9ac2c132)  
> 46. Ingeschrevenen hoger onderwijs in het domein hoger onderwijs, [https://onderwijsdata.duo.nl/datasets/p01hoinges](https://onderwijsdata.duo.nl/datasets/p01hoinges)  
> 47. Het toegestane voortgezet onderwijs per schoolvestiging en leerjaar., [https://onderwijsdata.duo.nl/datasets/06\_vomtgo](https://onderwijsdata.duo.nl/datasets/06_vomtgo)  
> 48. MonMaster 2024 & 2025 \- vœux de poursuite d'études ... \- Data Gouv, [https://www.data.gouv.fr/datasets/monmaster-2024-2025-voeux-de-poursuite-detudes-et-de-reorientation-en-master-et-reponses-des-etablissements](https://www.data.gouv.fr/datasets/monmaster-2024-2025-voeux-de-poursuite-detudes-et-de-reorientation-en-master-et-reponses-des-etablissements)  
> 49. Qualiopi & habilitations France compétences \- API Entreprise, [https://entreprise.api.gouv.fr/catalogue/carif\_oref/certifications\_qualiopi\_france\_competences](https://entreprise.api.gouv.fr/catalogue/carif_oref/certifications_qualiopi_france_competences)  
> 50. Répertoire national des certifications professionnelles ... \- Data Gouv, [https://www.data.gouv.fr/datasets/repertoire-national-des-certifications-professionnelles-et-repertoire-specifique](https://www.data.gouv.fr/datasets/repertoire-national-des-certifications-professionnelles-et-repertoire-specifique)  
> 51. Consultant en assistance à maîtrise d'ouvrage informatique, [https://www.francecompetences.fr/recherche/rncp/41879/](https://www.francecompetences.fr/recherche/rncp/41879/)  
> 52. Table de passage codes certifications et formations | data.gouv.fr, [https://www.data.gouv.fr/datasets/table-de-passage-codes-certifications-et-formations](https://www.data.gouv.fr/datasets/table-de-passage-codes-certifications-et-formations)  
> 53. students' skills and competencies in higher education system, [https://msdjournal.org/wp-content/uploads/unesco2011-7.pdf](https://msdjournal.org/wp-content/uploads/unesco2011-7.pdf)  
> 54. Tamar Todria Expert Profile \- Migration Research Hub, [https://migrationresearch.com/experts/tamar-todria/1215](https://migrationresearch.com/experts/tamar-todria/1215)  
> 55. Financial Aid for International Students | NYFA, [https://www.nyfa.edu/international-financial-aid/](https://www.nyfa.edu/international-financial-aid/)  
> 56. Ministry of Science and Education Republic of Azerbaijan, [https://edu.gov.az/en/news-and-updates/page/72?](https://edu.gov.az/en/news-and-updates/page/72)  
> 57. haydar aliyev, [https://edu.gov.az/uploads/Hesabat/TN-hesabat-2020-eng.pdf](https://edu.gov.az/uploads/Hesabat/TN-hesabat-2020-eng.pdf)  
> 58. SFI International Partnership Programme \- Science Foundation Ireland, [https://www.sfi.ie/funding/funding-calls/sfi-nsf-china-partnership/](https://www.sfi.ie/funding/funding-calls/sfi-nsf-china-partnership/)  
> 59. Ministry of Science and Education Republic of Azerbaijan, [https://edu.gov.az/en/news-and-updates/page/250?](https://edu.gov.az/en/news-and-updates/page/250)  
> 60. 37Years In the Service of Development \- Islamic Development Bank, [https://www.isdb.org/sites/default/files/media/documents/2018-12/37-Years%20in%20the%20Service%20of%20Development%201432H.pdf](https://www.isdb.org/sites/default/files/media/documents/2018-12/37-Years%20in%20the%20Service%20of%20Development%201432H.pdf)  
> 61. API RNCP et RS | data.gouv.fr, [https://www.data.gouv.fr/reuses/api-rncp-et-rs](https://www.data.gouv.fr/reuses/api-rncp-et-rs)