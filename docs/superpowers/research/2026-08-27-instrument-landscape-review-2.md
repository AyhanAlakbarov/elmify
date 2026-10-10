> **Provenance (added when filing, content below unmodified):** external deep-research output,
> 2026-08-27, second independent run of the same prompt. Weaker sourcing in places, but found
> three things run 1 missed: Georgia's bilateral reciprocal schemes, the Erasmus Mundus 10%
> per-nationality cap, and the CSC agency-code structure.

# **Data Model Validation Report: Landscape of National and State Scholarship Schemes for International Master's Students**

The following architectural report provides an exhaustive analysis of national, state, and supranational scholarship frameworks targeting international master's students. The primary objective is to validate the structural parameters, edge cases, and relational mapping required for an automated scholarship recommendation data model. State-funded educational mobility architectures reflect complex geopolitical, economic, and soft-power strategies, resulting in highly heterogeneous data shapes. A robust relational data model must accommodate multi-stage institutional nominations, dynamic nationality quotas, decentralized discovery paths, and non-standard initiation pipelines.  
This report systematically evaluates thirteen distinct funding architectures against seven critical data dimensions to identify structural mismatches and inform the design of targeted web crawler seed adapters. In adherence to the data validation protocol, all factual assertions are strictly accompanied by the official URL from which they were sourced. Where official data is absent, it is explicitly marked as "not published," and any reliance on third-party aggregator metadata is explicitly flagged.

## **1\. Germany (DAAD)**

The German Academic Exchange Service (DAAD) operates a massive, highly decentralized funding network. In 2024, the organization funded 140,925 individuals globally, including 67,531 international scholars, as documented at https://www.daad.de/en/press-releases/annual-report-2024/1. The data model must account for numerous sub-programs with divergent rules under the unified DAAD umbrella.

### **1\. WHO CAN APPLY**

Eligibility rules for DAAD master's scholarships are determined dynamically by the sub-program. The "Study Scholarships \- Master Studies for All Academic Disciplines" is broadly available, whereas specialized programs like the "Development-related Postgraduate Courses" (EPOS) and "STEM" programs explicitly target graduates from developing and emerging countries, according to https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=577421302. There is no single published global list of eligible countries; rather, eligibility is conditionally rendered via a search filter in the database at https://www.daad.de/stipdb-redirect/4. Per-country allocations or hard quotas are not published.

### **2\. WHAT IT FUNDS**

The DAAD standard master's scholarship provides a monthly stipend of 992 EUR, alongside payments toward health, accident, and personal liability insurance, as stated at https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=500262003. It also includes an annual study allowance of 460 EUR and a travel allowance upon application5. **Mismatch Statement:** The standard DAAD scholarship is strictly non-portable; it does not fund study outside of Germany. It explicitly mandates full-time, on-campus study at a state or state-recognized German university, and programs with integrated mandatory stays outside Germany are generally excluded, as noted at https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=577421302.

### **3\. THE ACADEMIC BAR**

The DAAD enforces a mixture of absolute and comparative requirements. An absolute requirement is that the applicant's most recent university degree must not date back more than six years at the time of the application deadline, published at https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=577421302. Another absolute constraint prohibits applicants who have been resident in Germany for longer than 15 months at the time of application6. Language requirements are strict: applicants must possess at least a B1 level in the language of instruction (German or English)2. The EPOS sub-program adds an absolute bar of at least two years of relevant professional work experience post-bachelor's, according to https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=500767777. Beyond these absolute thresholds, selection is comparative based on academic achievement and motivation.

### **4\. HOW IT IS INITIATED**

**Mismatch Statement:** The initiation architecture branches based on the sub-program. For general Master's studies, the student applies directly via the central DAAD portal at https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=500262005. However, for the EPOS program, the process is highly decentralized: students are strictly prohibited from applying directly to the DAAD. Instead, they must apply directly to up to three participating postgraduate courses at the respective universities; these institutions subsequently act as selection committees and nominate candidates to the DAAD7. An existing university admission offer is not strictly required at the time of the initial application but must be submitted before the funding period begins5.

### **5\. TIMELINE**

Timelines are highly variable and tied to specific study programs. For standard cycles, the DAAD portal closes strictly at 24:00 CET/CEST on the final application day, as noted at https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=577421302. For certain upcoming cycles, the most recent published dates indicate an application deadline of October 30, 2026, with a selection date in Spring 2027 and funding commencing in October 2027, according to https://www.daad.org/en/find-funding/scholarship-database/8.

### **6\. SELECTIVITY**

While global organizational funding numbers are provided (140,925 individuals funded in 2024), the specific number of applications received for master's scholarships, the exact number of awards granted, and the distinct selection rate are not published1.

### **7\. DISCOVERY PATH**

The schemes were enumerated via the official DAAD Scholarship Database. For an automated crawler, the primary index page to map these schemes is https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/5. The data model should also index the DAAD International Programmes database at https://www2.daad.de/deutschland/studienangebote/international-programmes/en/ to map university course offerings to funding9.

## **2\. France (France Excellence Eiffel and Campus France Schemes)**

Managed by Campus France under the French Ministry for Europe and Foreign Affairs, the French funding landscape requires a data model capable of parsing highly institutionalized nomination frameworks and aggregating disparate localized grants.

### **1\. WHO CAN APPLY**

The Eiffel program is universally open to foreign nationals up to 29 years old for master's programs, as stated at https://www.campusfrance.org/en/france-excellence-eiffel-scholarship-program10. The documentation notes that it aims to encourage applications from emerging countries for the master's level, but there is no published exhaustive list of eligible countries or per-country allocations13.

### **2\. WHAT IT FUNDS**

For master's students, the Eiffel scheme provides a monthly allowance of 1,181 EUR, which is officially scheduled to increase to 1,200 EUR from January 2026, according to https://www.campusfrance.org/en/the-france-excellence-eiffel-scholarship-program13. The funding covers international and national transport, health insurance, and cultural activities12. **Mismatch Statement:** The Eiffel Scholarship explicitly does not cover university tuition fees. While it grants exemption from standard enrollment fees at public institutions, educational institutions are expected to provide additional financial support, as detailed at https://www.ghana.campusfrance.org/scholarship-programs14. The scholarship is generally not portable; it funds 12 to 36 months of study in France, and funding is suspended if the academic program includes an international academic exchange12.

### **3\. THE ACADEMIC BAR**

The program is designed to attract "the best foreign students" in priority areas including Science and Technology and Humanities and Social Sciences10. The academic bar is purely comparative against other nominated applicants, assessed by a jury of independent experts using non-public evaluation grids, as noted at https://www.campusfrance.org/fr/le-programme-de-bourses-france-excellence-eiffel10. Absolute requirements include the age limit (maximum 29 years), while language proficiency requirements are not published centrally by Campus France, as they are determined by the nominating institution.

### **4\. HOW IT IS INITIATED**

**Mismatch Statement:** Students are structurally barred from applying directly to this scheme. The data model must classify this as an "Institutional Nomination" scheme. The student must contact a French higher education institution; if the institution agrees to support the candidate, that institution submits the application online via the dedicated Campus France portal on the student's behalf, as stated at https://www.nigeria.campusfrance.org/the-eiffel-excellence-scholarship-program10. Applications sent directly by students or foreign entities are immediately declared ineligible14. Therefore, the student must essentially hold or be in the process of securing an admission offer for the nomination to occur.

### **5\. TIMELINE**

For the 2026 campaign cycle, the call for applications opens on October 1, 2025\. The strict deadline for French institutions to submit applications to Campus France is January 8, 2026, with results announced starting March 30, 2026, published at https://www.campusfrance.org/en/france-excellence-eiffel-scholarship-program10.

### **6\. SELECTIVITY**

In the 2022 cycle, the Ministry allocated a total of 393 scholarships globally (344 for master's courses and 49 for doctoral courses), according to https://www.pakistan.campusfrance.org/results-of-the-eiffel-excellence-scholarship-program-for-202218. However, the total number of applications received by Campus France and the overarching selection rate are not published.

### **7\. DISCOVERY PATH**

The schemes were discovered via the official Campus France "Campus Bourses" grant search engine. For automated web crawlers, the primary index URL is https://campusbourses.campusfrance.org/\#/catalog19. This centralized portal is highly critical for the data model as it also enumerates supplementary schemes like Make Our Planet Great Again (MOPGA) and localized university grants (e.g., Emile-Boutmy, Ampere Scholarships)20. Note: Certain structural interpretations of the Campus Bourses platform were found on non-official blogs like wherescholarsbegin.com; these are flagged as unverified metadata23.

## **3\. Japan: Japanese Government (MEXT) Scholarship**

The MEXT scholarship represents a traditional, bilateral soft-power initiative reliant on geopolitical networks. Data modeling for MEXT requires handling highly decentralized, embassy-level application workflows.

### **1\. WHO CAN APPLY**

The scholarship targets international students from countries possessing diplomatic relations with Japan, according to https://www.mext.go.jp/en/policy/education/highered/title02/detail02/sdetail02/1373897.htm24. Specific lists of eligible countries and per-country quotas exist internally at the embassy level, but a consolidated global allocation list is not published in the central documentation.

### **2\. WHAT IT FUNDS**

MEXT supports foreign students with tuition exemption, international travel support, and a monthly allowance24. The exact monetary amounts for the master's (Research Student) stipend are not published in the official snippets provided. The scheme is non-portable, funding study exclusively in Japan.

### **3\. THE ACADEMIC BAR**

The official documentation does not publish the academic bar in absolute terms (such as specific GPA thresholds or language scores). Selection relies on comparative academic merit assessed through examinations and interviews24.

### **4\. HOW IT IS INITIATED**

**Mismatch Statement:** The scheme utilizes a bifurcated initiation model requiring a relational branch in the database. Students are selected via either "Embassy Recommendation" (direct application to the Japanese Embassy/Consulate General in their home country) or "University Recommendation" (the host university in Japan nominates the student)24. The student does not require an admission offer prior to the Embassy Recommendation route, but it is intrinsically tied to the University Recommendation route.

### **5\. TIMELINE**

Exact opening dates, closing dates, and decision announcements for the most recent global cycle are not published in the provided documentation, as they are heavily localized by individual embassies25.

### **6\. SELECTIVITY**

The total number of applications, total global awards for master's students, and the selection rate are not published25. As contextual data, the Japan Student Services Organization (JASSO) notes that 65% of privately financed international students in Japan engage in part-time work, but explicit MEXT selection numbers remain opaque27.

### **7\. DISCOVERY PATH**

The scheme was identified via the official Ministry of Education, Culture, Sports, Science and Technology (MEXT) index page at https://www.mext.go.jp/en/policy/education/highered/title02/detail02/sdetail02/1373897.htm24. Procedural nuances were cross-referenced against a non-official blog (gogetscholarship.com), which must be flagged by the crawler as an external, non-authoritative source28.

## **4\. South Korea: Global Korea Scholarship (GKS)**

Administered by the National Institute for International Education (NIIED), the GKS program shares architectural similarities with MEXT, utilizing dual application tracks but offering far greater centralization and data transparency.

### **1\. WHO CAN APPLY**

Applicants and both of their parents must hold non-Korean citizenship, and dual citizens must renounce their foreign citizenship before commencing the program, according to https://www.studyinkorea.go.kr/in/plan/scholarship.do29. A published list of eligible countries is distributed dynamically via the "University Information File" accompanying the annual GKS announcements29.

### **2\. WHAT IT FUNDS**

The GKS is fully funded, covering airfare, Korean language training costs, full tuition, and monthly study allowances, as stated at https://www.studyinkorea.go.kr/in/plan/scholarship.do29. Exact monetary amounts are not published in the official snippets. The scholarship is strictly non-portable and mandates study at GKS-designated universities in South Korea29.

### **3\. THE ACADEMIC BAR**

The program enforces strict, absolute minimum requirements. For a master's degree, applicants must hold a bachelor's degree and must be under 40 years of age29. Academically, candidates must possess a cumulative GPA of 80% or higher from their most recent academic program, or an equivalent grade format (e.g., 2.64/4.0, 2.80/4.3, 2.91/4.5, 3.23/5.0), as published in the GKS guidelines at https://www.studyinkorea.go.kr/public/v3/download/gks\_graduate\_user\_guide.pdf29. Selection beyond this baseline is comparative.

### **4\. HOW IT IS INITIATED**

**Mismatch Statement:** Initiation occurs through one of two mutually exclusive tracks, requiring discrete crawler pipelines. Under the Embassy Track, students apply online via the Study in Korea website; under the University Track, students submit applications directly to a GKS-designated university29. Final selection is a joint process where NIIED reviews and approves candidates recommended by the universities or embassies29.

### **5\. TIMELINE**

The application period generally opens in February of the applicable year, according to https://www.studyinkorea.go.kr/in/plan/scholarship.do29. Precise closing dates and result announcement dates for the most recent cycle are not published in the provided texts.

### **6\. SELECTIVITY**

The program transparently advertises a global selection quota of approximately 1,900 graduate students, as published at https://www.studyinkorea.go.kr/in/plan/scholarship.do29. However, the total number of applications received and the subsequent selection rate are not published.

### **7\. DISCOVERY PATH**

The GKS program was enumerated on the official Study in Korea portal under the comprehensive scholarship index: https://www.studyinkorea.go.kr/in/plan/scholarship.do29.

## **5\. China: Chinese Government Scholarship (CSC)**

The CSC scholarship represents a highly scalable state-funded enterprise. Its data model is uniquely characterized by "Agency Codes," requiring automated systems to map a relational database of four-digit identifiers to specific application tracks and host institutions.

### **1\. WHO CAN APPLY**

The scholarship is open to international students. Quotas and per-country allocations exist but are highly decentralized via bilateral agreements32. An exhaustive published list of globally eligible countries is not provided in the snippets.

### **2\. WHAT IT FUNDS**

The Type A and Type B scholarships provide full coverage, which explicitly includes full tuition and on-campus accommodation33. While stipends are included, the exact monetary amounts are not published in the snippets. The scholarship is strictly non-portable, funding study exclusively at designated Chinese institutions.

### **3\. THE ACADEMIC BAR**

Absolute minimum academic requirements, maximum age limits, and language prerequisites are not published in the provided official documentation34.

### **4\. HOW IT IS INITIATED**

**Mismatch Statement:** The initiation process is complex and dual-layered, highly reliant on "Agency Codes." Students must navigate distinct tracks: Type A (Embassy/bilateral route) and Type B (High-Level Postgraduate Program / direct university route), according to https://isa.ustc.edu.cn/xs/disp.asp?menu1=99\&menu2=02\&degree=2\&ucode=3534. Applicants log onto the central CSC online system and input a specific 4-digit code (e.g., 10358 for USTC, 10520 for ZUEL)35. Simultaneously, a parallel online application to the specific university's admission portal is required, meaning dual submission is mandatory35.

### **5\. TIMELINE**

Timelines vary significantly by university and track. For example, Shanghai Ocean University lists a deadline of February 1, 2026, for individual applications, published at https://ieo.shou.edu.cn/2025/1126/c18223a348600/page.htm34. Conversely, historical data for USTC lists a deadline of March 15 with physical documents due by April 1035. Decision dates are not published.

### **6\. SELECTIVITY**

Data regarding the total number of applications, overall awards, and selection rates are not published in the official documentation35.

### **7\. DISCOVERY PATH**

The scheme's central index portal for applications is hosted at http://www.csc.edu.cn/Laihua/noticeen.html35. Note: Data regarding specific Type A/B definitions and Agency Codes was partially aggregated from non-official blogs like scholarshipsforafricans.com and crosslineedu.com, which must be flagged by the data model as unverified external metadata32.

## **6\. United Kingdom: Chevening Scholarship**

Chevening is the UK Government’s global scholarship program. Its data structure is highly centralized, unified, and strictly meritocratic, prioritizing post-study geopolitical influence via mandatory repatriation constraints.

### **1\. WHO CAN APPLY**

Applicants must be citizens of a Chevening-eligible country or territory, as published at https://www.chevening.org/resource-hub/guidance/eligibility/37. A published list exists on the official website. The applicant cannot hold British or dual British citizenship (with minor exceptions for British Overseas Territories) and cannot hold refugee status in a non-eligible country37. Furthermore, scholars must commit to returning to their home country for at least two years after the scholarship ends37.

### **2\. WHAT IT FUNDS**

The scholarship is fully funded, though exact monetary amounts for the living stipend are not published in the documentation38. **Mismatch Statement:** The award is strictly non-portable; courses must be based entirely in the UK and cannot be taught with more than one month of study outside the UK, according to https://www.chevening.org/resource-hub/guidance/courses/39. Distance learning and part-time courses are explicitly banned39.

### **3\. THE ACADEMIC BAR**

The academic bar consists of hard absolute minimums: an undergraduate degree that qualifies the applicant for a UK master's program, and a minimum of two years (strictly quantified as 2,800 hours) of work experience, as published at https://www.chevening.org/resource-hub/guidance/eligibility/37. Beyond these minimums, selection is highly comparative.

### **4\. HOW IT IS INITIATED**

Students apply directly to the Chevening online application system37. **Mismatch Statement:** An admission offer is not required at the time of the initial scholarship application. However, the student must apply independently to three different eligible UK master's courses and must secure an unconditional offer from at least one of these courses by a strict deadline late in the cycle37.

### **5\. TIMELINE**

For the 2026/2027 cycle, applications open on August 4, 2026 (11:00 UTC) and close on October 6, 2026 (11:00 UTC), as published at https://www.chevening.org/scholarships/application-timeline/41. Independent reading committees assess applications until January 2027, interviews occur in March-April 2027, and results are announced from mid-June 2027 onwards41. The hard deadline for the student to submit the unconditional university admission offer is July 8, 2027 (17:00 BST)41.

### **6\. SELECTIVITY**

The total number of applications, the number of awards, and the global selection rate are not published in the official snippets provided42.

### **7\. DISCOVERY PATH**

The scheme is indexed centrally on the official portal at https://www.chevening.org/scholarships/, featuring a highly robust course discovery tool located at https://www.chevening.org/scholarships/find-a-course/43.

## **7\. United Kingdom: Commonwealth Master’s Scholarships**

Funded primarily by the UK Foreign, Commonwealth & Development Office (FCDO), this scheme is an instrument of Official Development Assistance (ODA). A data model must flag this as a hybrid merit-and-need-based scheme, heavily reliant on intermediary nominating agencies.

### **1\. WHO CAN APPLY**

Applicants must be citizens, hold refugee status, or be British Protected Persons permanently resident in an eligible low or middle-income Commonwealth country, according to https://cscuk.fcdo.gov.uk/scholarships/commonwealth-masters-scholarships/45. A published list of eligible countries is actively maintained by the Commission (including nations like Bangladesh, Belize, Botswana, Cameroon, and Ghana)45.

### **2\. WHAT IT FUNDS**

The scholarship is fully funded, covering tuition fees, airfare to and from the UK, and a living allowance47. Exceptionally, it provides a child allowance for widowed, divorced, or single parents of £529 per month for the first child and £131 per month for the second and third child under 16, according to non-official data at https://www2.fundsforngos.org/fellowships/commonwealth-masters-scholarships-now-open/46. It is not portable; studies must be undertaken at a UK university with which the Commonwealth Scholarship Commission (CSC) has a Memorandum of Understanding48.

### **3\. THE ACADEMIC BAR**

The absolute minimum academic bar is a first degree of at least upper second-class (2:1) honors standard, or a lower second-class degree (2:2) combined with a relevant postgraduate qualification45. **Mismatch Statement:** Uniquely among the reviewed schemes, this program implements a strict financial bar: applicants must sign a declaration stating they are unable to afford to study in the UK without the scholarship, as stated at https://www.govt.lc/scholarships/2026-commonwealth-scholarships-in-the-united-kingdom--one-1-year-master-s-degree45. Selection is comparative, heavily weighing the potential development impact on the applicant's home country45.

### **4\. HOW IT IS INITIATED**

**Mismatch Statement:** Direct applications to the CSC are strictly prohibited45. Students must be nominated. The primary route is via National Nominating Agencies, or alternatively through selected non-governmental organizations45. The candidate completes an Electronic Application System (EAS) form, which is submitted to the nominator49.

### **5\. TIMELINE**

For the published cycle, the EAS application portal opens on September 2, 2025, and closes on October 14, 2025 (16:00), published at https://study-uk.britishcouncil.org/scholarships-funding/commonwealth-scholarships47. Nominating bodies must submit their selected candidates to the CSC by December 2026, and applicants receive outcomes by July 202745.

### **6\. SELECTIVITY**

Each year, approximately 700 students are awarded Commonwealth Scholarships across all postgraduate levels47. The number of applications and the overall selection rate are not published.

### **7\. DISCOVERY PATH**

The scheme is enumerated via the official Commonwealth Scholarship Commission portal at https://cscuk.fcdo.gov.uk/scholarships/50. Procedural constraints regarding application routing were partially verified against non-official blogs like learnfastguide.com, which must be classified as unverified external metadata by crawlers46.

## **8\. Turkey: Türkiye Bursları (Türkiye Scholarships)**

Operated by the Presidency for Turks Abroad and Related Communities (YTB), Türkiye Bursları utilizes a highly centralized, integrated data model. It combines university admission and scholarship provision into a single pipeline, making it an optimal target for automated web crawling due to its standardized schema.

### **1\. WHO CAN APPLY**

Citizens of all countries are eligible to apply. Turkish citizens, or individuals who have lost Turkish citizenship, are explicitly excluded, according to https://ytb.gov.tr/daireler/uluslararasi-ogrenciler/turkiye-burslari52. No per-country quotas or published lists are indicated, suggesting a global open pool.

### **2\. WHAT IT FUNDS**

The program funds university and department placement, full tuition fees, a one-year Turkish language course, accommodation, health insurance, and a one-time round-trip flight ticket52. For master's degree students, it provides a monthly stipend of 5,000 TL, as published at https://ytb.gov.tr/daireler/uluslararasi-ogrenciler/turkiye-burslari52. It is not portable and strictly requires study in Turkey52.

### **3\. THE ACADEMIC BAR**

The scheme imposes absolute minimum academic and demographic thresholds. For master's programs, candidates must have a minimum academic achievement (GPA) of 75%, which rises to an absolute bar of 90% for Health Sciences (Medicine, Dentistry, Pharmacy)52. Applicants must be under 30 years of age for master's programs52.

### **4\. HOW IT IS INITIATED**

The student applies directly via the centralized Türkiye Bursları online platform52. **Mismatch Statement:** Because the scholarship inherently includes university placement within the same application framework, an existing independent university admission offer is explicitly not required52.

### **5\. TIMELINE**

Applications are typically received in one consolidated period annually. For the 2024 cycle, applications opened on January 10 and closed on February 20, published at https://www.turkiyeburslari.gov.tr/announcements/turkiye-scholarships-2024-applications-5552. Decision announcement dates are not published in the snippets.

### **6\. SELECTIVITY**

The program is highly selective and exceptionally transparent with its data. In 2024, it received 121,830 applications from 170 countries. With approximately 5,000 scholarships awarded annually across all levels, the overall global selection rate sits at roughly 4.1%, published at https://ytb.gov.tr/daireler/uluslararasi-ogrenciler/turkiye-burslari52.

### **7\. DISCOVERY PATH**

The official portal hosting the scholarship application and programmatic details is https://www.turkiyeburslari.gov.tr/52.

## **9\. Hungary: Stipendium Hungaricum**

The Stipendium Hungaricum operates on a bilateral intergovernmental model. Data architecture for this scheme is highly relational, requiring crawlers to connect the central Hungarian funding database with localized "Sending Partner" databases in foreign countries.

### **1\. WHO CAN APPLY**

Eligibility is strictly dictated by bilateral education agreements between Hungary and specific Sending Partners (e.g., Georgia). Citizens of these partner countries are eligible, according to https://iec.gov.ge/en-us/Programs/2025-2026-ACADEMIC-YEAR/Hungaricum\_2025-202654. A published list of eligible partner countries is managed centrally via the study finder portal55.

### **2\. WHAT IT FUNDS**

The scholarship covers tuition-free education, a monthly stipend, an accommodation contribution, and medical insurance54. Exact monetary amounts are not detailed in the provided snippets. The scholarship is non-portable; it is designed strictly for study at Hungarian higher education institutions54.

### **3\. THE ACADEMIC BAR**

Specific minimum absolute requirements regarding grades, language, age, and work experience are not published in the provided documentation, as they are determined in conjunction with the local Sending Partner's criteria54.

### **4\. HOW IT IS INITIATED**

**Mismatch Statement:** The initiation process is joint and dual-platform. Students cannot apply directly to Hungary in isolation; they must be nominated by their home country's Sending Partner (e.g., Georgia's IEC). The applicant must submit applications simultaneously in the Hungarian Tempus Public Foundation (TPF) "Dream Apply" system and the Sending Partner's electronic system, as outlined at https://iec.gov.ge/en-us/Programs/2025-2026-ACADEMIC-YEAR/Hungaricum\_2025-202654. The Sending Partner creates a shortlist, and the final decision is made by the Hungarian side54.

### **5\. TIMELINE**

Specific open and close dates for the most recent cycle are not published in the provided snippets. The documentation references ongoing institutional evaluations for the 2025/2026 academic year phase spanning March-May 2025, published at https://stipendiumhungaricum.hu/wp-content/uploads/2025/10/BA\_MA\_OTM\_Call\_for\_Applications\_2026\_27.pdf55.

### **6\. SELECTIVITY**

The program exhibits massive global demand, with a published figure of 80,000 applications submitted in 2025 (a 20% increase from the previous year), as reported at https://stipendiumhungaricum.hu/news/stipendium-hungaricum-setting-new-application-record-in-2025/57. The distinct number of awards and the overall selection rate are not published.

### **7\. DISCOVERY PATH**

The primary enumeration portal and study finder for crawlers is https://stipendiumhungaricum.hu/study-finder/, paired with the central application engine at https://apply.stipendiumhungaricum.hu/54.

## **10\. Azerbaijan: Heydar Aliyev International Education Grant**

A newly established soft-power initiative, the Heydar Aliyev Grant demonstrates a state transitioning to a proactive internationalization strategy. The data model is straightforward but currently reflects operational bottlenecks typical of newly launched state frameworks.

### **1\. WHO CAN APPLY**

Eligibility is strictly geographical and geopolitical. Eligible applicants include citizens of member states of the Organization of Islamic Cooperation (OIC), the Non-Aligned Movement (NAM), Small Island Developing States, and countries with ethnic, historical, and cultural ties to Azerbaijan, according to https://oldver.studyinazerbaijan.edu.az/web/news/international-education-grant-named-after-heydar-aliyev-program-is-launched58. An exhaustive, distinct country list is not published in the snippets.

### **2\. WHAT IT FUNDS**

The grant is highly comprehensive, covering tuition fees, visa fees, registration, dormitory or apartment rent, daily sustenance, educational literature, medical assistance, transportation (excluding taxis), utilities, and one round-trip international flight per year, published at https://oldver.studyinazerbaijan.edu.az/web/news/international-education-grant-named-after-heydar-aliyev-program-is-launched58. Exact monetary amounts for stipends are not published in the specific grant documentation (though external intergovernmental announcements on the site mention 500 Euros for separate programs in Latvia, this does not apply here)58. The grant is not portable; it mandates study in Azerbaijan58.

### **3\. THE ACADEMIC BAR**

Published minimum absolute requirements regarding grades, language, age, and work experience are not present in the provided snippets58.

### **4\. HOW IT IS INITIATED**

The program intends for a direct application via the unified "SIACAS E-Application" portal58.

### **5\. TIMELINE**

**Mismatch Statement:** While the program was legislated to launch for the 2024-2025 academic year, an official announcement dated February 6, 2024, stated that due to an "extreme amount of applications," the official application process had not yet been launched by the ministry, as noted at https://oldver.studyinazerbaijan.edu.az/web/news/attention-information-related-to-the-international-education-grant-named-after-h61. Thus, exact open/close dates are not published.

### **6\. SELECTIVITY**

The program is highly selective by design, legally capped at exactly 100 educational grants annually for a period of five years starting from the 2024-2025 academic year58. Application volumes are noted informally as "extreme," but exact selection rates are not published61.

### **7\. DISCOVERY PATH**

The scheme is indexed on the official portal https://studyinazerbaijan.edu.az/scholarships and managed directly by the Ministry of Science and Education58. Note: A crawler mapping this portal will also ingest secondary third-country scholarships (e.g., Latvian government grants) hosted on the Azerbaijani government's announcement boards, necessitating robust geographic filtering logic60.

## **11\. Georgia: International Education Center (IEC) Foreign Scholarships**

The Georgian IEC operates primarily to fund Georgian nationals studying abroad, but it also administers unique, reciprocal state-funded scholarships for foreign citizens to study in Georgia (specifically citizens of Armenia and Czechia).

### **1\. WHO CAN APPLY**

Only citizens of specific partner countries with which Georgia has signed memorandums of understanding (e.g., the Republic of Armenia, the Czech Republic) are eligible, as published at https://iec.gov.ge/en-us/Programs/2025-2026-ACADEMIC-YEAR/Somkheti\_\_2025-202663.

### **2\. WHAT IT FUNDS**

Funding parameters vary radically by bilateral agreement. For Armenian citizens, the program covers full tuition at Armenian higher education institutions (up to 1,000,000 AMD), free accommodation, and a monthly stipend of 50,000 AMD63. For Czech citizens, master's students receive a monthly stipend of 12,000 CZK64. **Mismatch Statement:** The funds are explicitly for international exchange (e.g., Georgians to Armenia/Czechia, and vice versa), meaning the data model must flag these as reciprocal, destination-specific funds rather than general inbound mobility grants63.

### **3\. THE ACADEMIC BAR**

Applicants must hold a bachelor's degree and possess an English language proficiency certificate. In the absence of a language certificate, candidates face an absolute requirement to pass an internal examination administered by the host university, published at https://iec.gov.ge/en-us/Programs/2025-2026-ACADEMIC-YEAR/Somkheti\_\_2025-202663.

### **4\. HOW IT IS INITIATED**

**Mismatch Statement:** The process is a joint, manual selection. Applicants do not use a standardized web portal; they submit documentation directly via email (info-iec@iec.gov.ge). The IEC nominates candidates, but the final selection is made by the receiving country's authorities (e.g., the Armenian side)63.

### **5\. TIMELINE**

Exact timelines (open, close, and decision dates) for the 2025-2026 academic year cycle are not published in the provided documentation63.

### **6\. SELECTIVITY**

For the Armenian partnership, exactly 10 scholarships are available annually63. Application numbers and selection rates are not published.

### **7\. DISCOVERY PATH**

The reciprocal foreign scholarship programs are enumerated at the IEC official portal: https://iec.gov.ge/en-us/Programs/63.

## **12\. Russia: Government Quota Scheme**

The Russian Government Quota represents a traditional, volume-heavy state funding mechanism for internationalization. However, the provided data surface area for this scheme is exceptionally sparse, posing a significant challenge for automated extraction models.

### **1\. WHO CAN APPLY**

The scheme is open generally to foreign students aiming to receive quality education in Russia, according to https://studyinrussia.ru/en/65. Details on country quotas or a published list of eligible countries are not present in the provided snippets.

### **2\. WHAT IT FUNDS**

The term "quota" implies tuition coverage, but specific details regarding stipends, travel, and insurance are not published in the snippets65. It is not portable.

### **3\. THE ACADEMIC BAR**

Minimum absolute academic requirements (grades, language, age, work experience) are not published in the provided snippets65.

### **4\. HOW IT IS INITIATED**

The initiation protocol (whether direct application, institutional nomination, or embassy nomination) is not explicitly published in the provided snippets65.

### **5\. TIMELINE**

Application open and close dates, as well as decision dates, are not published in the provided snippets65.

### **6\. SELECTIVITY**

Statistics regarding the number of applications, the number of awards, and selection rates are not published65. **Data Modeling Insight:** Crawler queries targeting Google Knowledge Panels for "Education in Russia" yielded severe hallucination errors, returning parsed sports data (Olympic wrestling and soccer match results) instead of scholarship statistics66. This underscores the necessity of constraining crawlers strictly to official .ru governmental domains.

### **7\. DISCOVERY PATH**

The official portals for discovering the Russian Government Quota are https://studyinrussia.ru/en/ and https://educationinrussia.com65.

## **13\. The European Union: Erasmus Mundus Joint Masters (EMJM)**

Funded by the European Education and Culture Executive Agency (EACEA), the EMJM represents the most structurally complex data architecture in this review. It shifts selection power entirely to autonomous university consortia, creating a highly decentralized, multi-node data environment.

### **1\. WHO CAN APPLY**

Students of all nationalities worldwide are eligible, according to https://www.eacea.ec.europa.eu/document/download/9b5521ee-2303-4e2c-825b-db7996634418\_en67. **Mismatch Statement:** While open to all, the scheme enforces a strict structural limitation known as the "10% rule." A maximum of 10% of scholarship holders in any given intake can share the same nationality (excluding specific targeted regions like the Western Balkans or Sub-Saharan Africa), as published at https://erasmus-networks.ec.europa.eu/system/files/2025-11/7.%20PPT%20MOBILITY%20TOOL%20EMJM%20NOVEMBER%202025.pdf67. This dictates that a student's probability of selection is dynamically linked to the applicant pool of their compatriots.

### **2\. WHAT IT FUNDS**

The EMJM provides a highly lucrative scholarship of 1,400 EUR per month for the duration of the master's program (12, 18, or 24 months), alongside institutional costs of 750 EUR per month, detailed at https://www.eacea.ec.europa.eu/document/download/9b5521ee-2303-4e2c-825b-db7996634418\_en67. **Mismatch Statement:** Unlike all national schemes reviewed, EMJM is inherently and mandatorily portable. It requires compulsory physical student mobility consisting of at least two study periods in two different countries (of which at least one must be an EU Member State or third country associated with the Programme)68. The approved list of destinations is defined by the specific consortium and published in the Erasmus Mundus Catalogue23. Data pipelines must also account for complex pro-rata payment deductions calculated daily in the event of student drop-outs67.

### **3\. THE ACADEMIC BAR**

The EACEA dictates a mandate of "Excellence\!"—requiring one selection list and one rank67. The selection is purely comparative against other applicants globally. Specific absolute minimum requirements (such as exact GPA or language test scores) are decentralized and set autonomously by the individual university consortia67.

### **4\. HOW IT IS INITIATED**

**Mismatch Statement:** Students do not apply to the EU or the EACEA directly. The student must apply directly to the specific university consortium offering the program, as noted on unverified indexing blogs like wherescholarsbegin.com23. There is no central EACEA application portal for students; the consortium controls the recruitment process, scholarship cut-offs, and reserve lists independently67.

### **5\. TIMELINE**

Because applications are handled by individual consortia, there is no single universal deadline. EACEA guidelines recommend that consortia keep their application calls open for approximately three months, as stated at https://www.eacea.ec.europa.eu/document/download/9b5521ee-2303-4e2c-825b-db7996634418\_en67. Non-official blog sources note that applications generally run from October to January for the following academic year23.

### **6\. SELECTIVITY**

Global macro-statistics on application volumes and selection rates are not published centrally in the provided snippets. Consortia manage their own distinct quotas (e.g., funding 2 to 20 international students per intake)23.

### **7\. DISCOVERY PATH**

Because application portals are fully decentralized, the critical discovery path for a web crawler is the central enumeration index: The Erasmus Mundus Catalogue located at https://ec.europa.eu/erasmus-mundus67. Structural context regarding application mechanisms was cross-referenced via the non-official site wherescholarsbegin.com, which should be categorized strictly as secondary metadata23.

## **Architectural Synthesis and Data Modeling Implications**

The validation of these thirteen scholarship frameworks reveals profound structural heterogeneity. The following table summarizes the overarching architectural paradigms that the database schema must accommodate:

| Scheme Architecture | Primary Example | Crawler Implications | Database Relational Requirement |
| :---- | :---- | :---- | :---- |
| **Highly Centralized** | Türkiye Bursları | Single-point crawling. | 1:1 mapping (Application \-\> University \+ Scholarship). |
| **Dual-Track Central/Nominated** | DAAD, GKS | Multi-point crawling required. | 1:N mapping (One central fund, multiple initiation points). |
| **Agency Code Relational** | CSC (China) | Must parse metadata for 4-digit codes. | N:N mapping linking universities, tracks (Type A/B), and central codes. |
| **Institutional Nomination** | Eiffel | No direct applicant portal to scrape. | Must map university deadline pages, not funder pages. |
| **Consortium Decentralized** | Erasmus Mundus | Must scrape central catalogue, then follow outbound links. | Highly dynamic mapping of mandatory mobility destinations. |

A rigid, one-size-fits-all database schema will inherently fail to capture this landscape. The automated recommendation engine must accommodate Many-to-Many Portability Matrices (like EMJM), Dual-Node Application Architectures (like CSC and Stipendium Hungaricum), and Dynamic Eligibility Rules (such as the EMJM "10% rule" or the Commonwealth financial necessity clause). By pointing the seed adapters directly at the index portals (e.g., Campus Bourses, the DAAD Database, and the EMJM Catalogue) and programming them to parse these distinct structural mismatches, the resulting system will successfully navigate the complexities of international educational funding.

#### **Works cited**

> 1. DAAD draws a positive balance for 2024, [https://www.daad.de/en/press-releases/annual-report-2024/](https://www.daad.de/en/press-releases/annual-report-2024/)  
> 2. Study scholarships for STEM disciplines \- DAAD, [https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=57742130](https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=57742130)  
> 3. DAAD Scholarships \- An Overview, [https://www.daad.de/en/studying-in-germany/scholarships/daad-scholarships/](https://www.daad.de/en/studying-in-germany/scholarships/daad-scholarships/)  
> 4. Scholarship Database \- Deutscher Akademischer Austauschdienst, [https://www.daad.de/stipdb-redirect/](https://www.daad.de/stipdb-redirect/)  
> 5. Study Scholarships \- Master Studies for All Academic Disciplines, [https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50026200](https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50026200)  
> 6. Study Scholarships \- Postgraduate Studies in the Fields of Fine Art, [https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=57135742](https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=57135742)  
> 7. Development-Related Postgraduate Courses (EPOS) \- DAAD, [https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50076777](https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50076777)  
> 8. Scholarship Database \- DAAD Office New York, [https://www.daad.org/en/find-funding/scholarship-database/](https://www.daad.org/en/find-funding/scholarship-database/)  
> 9. International Programmes \- Homepage \- DAAD, [https://www2.daad.de/deutschland/studienangebote/international-programmes/en/](https://www2.daad.de/deutschland/studienangebote/international-programmes/en/)  
> 10. Le programme de bourses France Excellence Eiffel, [https://www.campusfrance.org/fr/le-programme-de-bourses-france-excellence-eiffel](https://www.campusfrance.org/fr/le-programme-de-bourses-france-excellence-eiffel)  
> 11. France Excellence Eiffel scholarship program, [https://www.campusfrance.org/en/france-excellence-eiffel-scholarship-program](https://www.campusfrance.org/en/france-excellence-eiffel-scholarship-program)  
> 12. Eiffel Scholarship Program of Excellence \- Campus France Pakistan, [https://www.pakistan.campusfrance.org/eiffel-scholarship-program-of-excellence](https://www.pakistan.campusfrance.org/eiffel-scholarship-program-of-excellence)  
> 13. France Excellence Eiffel Scholarship, [https://www.inde.campusfrance.org/eiffel\_scholarship\_2024](https://www.inde.campusfrance.org/eiffel_scholarship_2024)  
> 14. The Eiffel Excellence Scholarship Program \- Campus France Nigeria, [https://www.nigeria.campusfrance.org/the-eiffel-excellence-scholarship-program](https://www.nigeria.campusfrance.org/the-eiffel-excellence-scholarship-program)  
> 15. The France Excellence Eiffel scholarship program, [https://www.campusfrance.org/en/the-france-excellence-eiffel-scholarship-program](https://www.campusfrance.org/en/the-france-excellence-eiffel-scholarship-program)  
> 16. France Excellence \- Eiffel Scholarship, [https://www.southafrica.campusfrance.org/france-excellence-eiffel-scholarship](https://www.southafrica.campusfrance.org/france-excellence-eiffel-scholarship)  
> 17. SCHOLARSHIP PROGRAMS \- Campus France Ghana, [https://www.ghana.campusfrance.org/scholarship-programs](https://www.ghana.campusfrance.org/scholarship-programs)  
> 18. Results of the Eiffel excellence scholarship program for 2022, [https://www.pakistan.campusfrance.org/results-of-the-eiffel-excellence-scholarship-program-for-2022](https://www.pakistan.campusfrance.org/results-of-the-eiffel-excellence-scholarship-program-for-2022)  
> 19. Funding opportunities | Erasmus \- QEM, [https://master-economics-qem.eu/application-and-practical/funding-opportunities](https://master-economics-qem.eu/application-and-practical/funding-opportunities)  
> 20. Finding financial aid \- Sorbonne University Welcome Desk, [https://international-welcome-desk.sorbonne-universite.fr/managing-your-finances/your-budget/finding-financial-aid/](https://international-welcome-desk.sorbonne-universite.fr/managing-your-finances/your-budget/finding-financial-aid/)  
> 21. Call for application : Eiffel scholarship program of excellence 2022, [https://www.inde.campusfrance.org/call-for-application-eiffel-scholarship-program-of-excellence-2022](https://www.inde.campusfrance.org/call-for-application-eiffel-scholarship-program-of-excellence-2022)  
> 22. Scholarships for Indian Students | Campus France India, [https://www.inde.campusfrance.org/scholarships-for-indian-students](https://www.inde.campusfrance.org/scholarships-for-indian-students)  
> 23. 10 Sites for Masters and MPhil Scholarships, [https://wherescholarsbegin.com/10-sites-for-masters-and-mphil-scholarships/](https://wherescholarsbegin.com/10-sites-for-masters-and-mphil-scholarships/)  
> 24. STUDY in JAPAN \- MEXT, [https://www.mext.go.jp/en/policy/education/highered/title02/detail02/sdetail02/1373897.htm](https://www.mext.go.jp/en/policy/education/highered/title02/detail02/sdetail02/1373897.htm)  
> 25. 国費外国人留学生制度について \- 文部科学省, [https://www.mext.go.jp/a\_menu/koutou/ryugaku/06032818.htm](https://www.mext.go.jp/a_menu/koutou/ryugaku/06032818.htm)  
> 26. 文部科学省, [https://www.mext.go.jp/](https://www.mext.go.jp/)  
> 27. Part-Time Work｜Study in Japan Official Website, [https://www.studyinjapan.go.jp/en/work-in-japan/part-time-jobs/](https://www.studyinjapan.go.jp/en/work-in-japan/part-time-jobs/)  
> 28. Fully Funded Scholarships for International Students: Complete Guide, [https://gogetscholarship.com/%F0%9F%8C%9F-fully-funded-scholarships-for-international-students-complete-guide/](https://gogetscholarship.com/%F0%9F%8C%9F-fully-funded-scholarships-for-international-students-complete-guide/)  
> 29. GKS Scholarships \- Study in Korea | Run by Korean Government, [https://www.studyinkorea.go.kr/in/plan/scholarship.do](https://www.studyinkorea.go.kr/in/plan/scholarship.do)  
> 30. 지원 신청 가이드 User Guide, [https://www.studyinkorea.go.kr/public/v3/download/gks\_graduate\_user\_guide.pdf](https://www.studyinkorea.go.kr/public/v3/download/gks_graduate_user_guide.pdf)  
> 31. 장학금 | Plan your studies | 한국유학종합시스템(스터디인코리아), [https://www.studyinkorea.go.kr/ko/plan/scholarship.do](https://www.studyinkorea.go.kr/ko/plan/scholarship.do)  
> 32. The 2026 China Scholarship Quota (CSC and 10+ Other Types), [https://www.crosslineedu.com/blog/china-scholarship-quota-international-students](https://www.crosslineedu.com/blog/china-scholarship-quota-international-students)  
> 33. Chinese Government Scholarship (CSC) 2026: Step-by-Step Guide, [https://scholarshipsforafricans.com/blog/chinese-government-scholarship-csc-guide](https://scholarshipsforafricans.com/blog/chinese-government-scholarship-csc-guide)  
> 34. 2026 CSC "High-level Postgraduate" Program Application Guide, [https://ieo.shou.edu.cn/2025/1126/c18223a348600/page.htm](https://ieo.shou.edu.cn/2025/1126/c18223a348600/page.htm)  
> 35. Step by Step Application Process Guidance \- USTC, [https://isa.ustc.edu.cn/xs/disp.asp?menu1=99\&menu2=02°ree=2\&ucode=35](https://isa.ustc.edu.cn/xs/disp.asp?menu1=99&menu2=02&degree=2&ucode=35)  
> 36. 2026 CSC High Level Postgraduate Program, ZUEL, [https://ies-en.zuel.edu.cn/2025/1114/c13676a411002/page.htm](https://ies-en.zuel.edu.cn/2025/1114/c13676a411002/page.htm)  
> 37. Chevening eligibility criteria, [https://www.chevening.org/resource-hub/guidance/eligibility/](https://www.chevening.org/resource-hub/guidance/eligibility/)  
> 38. Peru (Chevening Scholarship), [https://www.chevening.org/scholarship/peru/](https://www.chevening.org/scholarship/peru/)  
> 39. Choosing a UK university course \- Chevening, [https://www.chevening.org/resource-hub/guidance/courses/](https://www.chevening.org/resource-hub/guidance/courses/)  
> 40. Courses | Chevening, [https://www.chevening.org/scholarships/guidance/courses/](https://www.chevening.org/scholarships/guidance/courses/)  
> 41. Application timeline \- Chevening, [https://www.chevening.org/scholarships/application-timeline/](https://www.chevening.org/scholarships/application-timeline/)  
> 42. Chevening's 2023-2024 annual impact report, [https://www.chevening.org/impact/chevenings-2023-2024-annual-impact-report/](https://www.chevening.org/impact/chevenings-2023-2024-annual-impact-report/)  
> 43. Chevening, [https://www.chevening.org/](https://www.chevening.org/)  
> 44. Find a course | Chevening, [https://www.chevening.org/scholarships/find-a-course/](https://www.chevening.org/scholarships/find-a-course/)  
> 45. Commonwealth Master's Scholarships, [https://cscuk.fcdo.gov.uk/scholarships/commonwealth-masters-scholarships/](https://cscuk.fcdo.gov.uk/scholarships/commonwealth-masters-scholarships/)  
> 46. Commonwealth Master's Scholarships Now Open\! \- fundsforNGOs, [https://www2.fundsforngos.org/fellowships/commonwealth-masters-scholarships-now-open/](https://www2.fundsforngos.org/fellowships/commonwealth-masters-scholarships-now-open/)  
> 47. Commonwealth Scholarships | Study UK \- British Council, [https://study-uk.britishcouncil.org/scholarships-funding/commonwealth-scholarships](https://study-uk.britishcouncil.org/scholarships-funding/commonwealth-scholarships)  
> 48. UK universities \- Commonwealth Scholarship Commission in the UK, [https://cscuk.fcdo.gov.uk/uk-universities/](https://cscuk.fcdo.gov.uk/uk-universities/)  
> 49. 2026 commonwealth scholarships in the united kingdom, [https://www.govt.lc/scholarships/2026-commonwealth-scholarships-in-the-united-kingdom--one-1-year-master-s-degree](https://www.govt.lc/scholarships/2026-commonwealth-scholarships-in-the-united-kingdom--one-1-year-master-s-degree)  
> 50. Commonwealth Scholarship Commission in the UK, [https://cscuk.fcdo.gov.uk/scholarships/](https://cscuk.fcdo.gov.uk/scholarships/)  
> 51. Commonwealth Masters Scholarships full guide \- Learnfastguide, [https://learnfastguide.com/commonwealth-masters-scholarships/](https://learnfastguide.com/commonwealth-masters-scholarships/)  
> 52. Türkiye Bursları \- Yurtdışı Türkler ve Akraba Topluluklar Başkanlığı, [https://ytb.gov.tr/daireler/uluslararasi-ogrenciler/turkiye-burslari](https://ytb.gov.tr/daireler/uluslararasi-ogrenciler/turkiye-burslari)  
> 53. Fully funded scholarship program for international students, [https://www.turkiyeburslari.gov.tr/announcements/turkiye-scholarships-2024-applications-55](https://www.turkiyeburslari.gov.tr/announcements/turkiye-scholarships-2024-applications-55)  
> 54. Hungaricum\_2025-2026, [https://iec.gov.ge/en-us/Programs/2025-2026-ACADEMIC-YEAR/Hungaricum\_2025-2026](https://iec.gov.ge/en-us/Programs/2025-2026-ACADEMIC-YEAR/Hungaricum_2025-2026)  
> 55. Study finder \- Stipendium Hungaricum Scholarship, [https://stipendiumhungaricum.hu/study-finder/](https://stipendiumhungaricum.hu/study-finder/)  
> 56. Call for Applications 2026/2027 \- Stipendium Hungaricum Scholarship, [https://stipendiumhungaricum.hu/wp-content/uploads/2025/10/BA\_MA\_OTM\_Call\_for\_Applications\_2026\_27.pdf](https://stipendiumhungaricum.hu/wp-content/uploads/2025/10/BA_MA_OTM_Call_for_Applications_2026_27.pdf)  
> 57. Stunning statistics\! Stipendium Hungaricum setting new application, [https://stipendiumhungaricum.hu/news/stipendium-hungaricum-setting-new-application-record-in-2025/](https://stipendiumhungaricum.hu/news/stipendium-hungaricum-setting-new-application-record-in-2025/)  
> 58. Heydar Aliyev International Education Grant Program, [https://oldver.studyinazerbaijan.edu.az/web/heydar-aliyev-international-education-grant-program](https://oldver.studyinazerbaijan.edu.az/web/heydar-aliyev-international-education-grant-program)  
> 59. "International Education Grant named after Heydar Aliyev" program, [https://oldver.studyinazerbaijan.edu.az/web/news/international-education-grant-named-after-heydar-aliyev-program-is-launched](https://oldver.studyinazerbaijan.edu.az/web/news/international-education-grant-named-after-heydar-aliyev-program-is-launched)  
> 60. Ministry of Science and Education Republic of Azerbaijan, [https://edu.gov.az/en/announcements/page/2?](https://edu.gov.az/en/announcements/page/2)  
> 61. Information related to the “International Education Grant named after, [https://oldver.studyinazerbaijan.edu.az/web/news/attention-information-related-to-the-international-education-grant-named-after-h](https://oldver.studyinazerbaijan.edu.az/web/news/attention-information-related-to-the-international-education-grant-named-after-h)  
> 62. Khazar University International Scholarship Program (KUISP), [https://studyinazerbaijan.edu.az/scholarships](https://studyinazerbaijan.edu.az/scholarships)  
> 63. Somkheti\_\_2025-2026, [https://iec.gov.ge/en-us/Programs/2025-2026-ACADEMIC-YEAR/Somkheti\_\_2025-2026](https://iec.gov.ge/en-us/Programs/2025-2026-ACADEMIC-YEAR/Somkheti__2025-2026)  
> 64. Czechia\_2025-2026, [https://iec.gov.ge/en-us/Programs/2025-2026-ACADEMIC-YEAR/Czechia\_2025-2026](https://iec.gov.ge/en-us/Programs/2025-2026-ACADEMIC-YEAR/Czechia_2025-2026)  
> 65. Studying in Russia \- Get quality education in Russia\!, [https://studyinrussia.ru/en/](https://studyinrussia.ru/en/)  
> 66. Google Sports Data, [https://support.google.com/knowledgepanel/answer/9787176](https://support.google.com/knowledgepanel/answer/9787176)  
> 67. Erasmus+ Erasmus Mundus Joint Masters (EMJM) Student selection, [https://www.eacea.ec.europa.eu/document/download/9b5521ee-2303-4e2c-825b-db7996634418\_en?filename=E\_EMJM\_Events\_2022\_4Kick-off\_student%20selection%20and%20scholarship%20management\_EMJM%20CALL%202021.pdf](https://www.eacea.ec.europa.eu/document/download/9b5521ee-2303-4e2c-825b-db7996634418_en?filename=E_EMJM_Events_2022_4Kick-off_student+selection+and+scholarship+management_EMJM+CALL+2021.pdf)  
> 68. Erasmus+ \- Erasmus Networks Platform, [https://erasmus-networks.ec.europa.eu/system/files/2025-11/7.%20PPT%20MOBILITY%20TOOL%20EMJM%20NOVEMBER%202025.pdf](https://erasmus-networks.ec.europa.eu/system/files/2025-11/7.%20PPT%20MOBILITY%20TOOL%20EMJM%20NOVEMBER%202025.pdf)  
> 69. How to prepare your Erasmus Mundus Joint Masters (EMJM) Proposal, [https://www.eacea.ec.europa.eu/document/download/120475e5-3fe2-4d6d-b46c-dd37def7b03b\_en?filename=EMJM%20instructions%20for%20applicants\_2025%20-%20events%20page%20final.pdf](https://www.eacea.ec.europa.eu/document/download/120475e5-3fe2-4d6d-b46c-dd37def7b03b_en?filename=EMJM+instructions+for+applicants_2025+-+events+page+final.pdf)