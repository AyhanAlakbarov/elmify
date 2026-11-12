# Funding-source breadth for Azerbaijani students going abroad

Date: 2026-10-03. Question: which official, machine-readable or bulk funding sources add awards for
an Azerbaijani citizen at low cost that the four current channels (HE registers, government
directories, foundation/charity registers, national scholarship databases used as leads) miss?

## Scope (sub-questions)

1. Is there an official list of scholarships open to Azerbaijani citizens specifically? (Yes: two.)
2. For each candidate named by the caller: does it list awards an Azerbaijani can take, roughly how
   many, in what format, how often updated?
3. Which candidates are dead ends (wrong eligibility, exchange-only, employer-only, blocked)?
4. Rank what is left by expected awards for an Azerbaijani student per unit of integration cost.

**How the list was built.** Candidates came from the caller's list plus these searches:
Exa "official government or embassy page listing scholarships available to citizens of
Azerbaijan" (surfaced the SOFAZ State Programme page and edu.gov.az); Brave
`site:edu.gov.az hökumətlərarası təqaüd proqramları xaricdə təhsil` (surfaced **htp.edu.az** and
the State Programme programme list, neither of which was on the caller's list); Brave
`site:htp.edu.az` (MEXT material hosted there); Exa searches for IsDB and Organization of Turkic
States programmes; Brave searches for Fulbright Azerbaijan, Bolashak and SOCAR. Tools: Exa, Brave,
scrapling all available; Tavily and Context7 not used. Every quote below was copied from a
scrapling `get` of the cited page unless marked otherwise.

## Answer: the ranked list

Ranked by expected awards an Azerbaijani student would be shown, divided by integration cost
(one HTML site with a stable news feed = cheap; a JS app, PDF or per-programme page = dear).

| # | Source | Owner | What it lists | Approx. count | Format | Update cycle | Open to AZ citizens? |
|---|---|---|---|---|---|---|---|
| 1 | **htp.edu.az** | AZ Ministry of Science and Education | Intergovernmental Scholarship Programmes (HTP) for AZ citizens, by destination; also reposts GKS and MEXT calls | ~10 destination programmes (HU, MA, CN, KZ, RO, LV, TJ, KG, TR-YTB doctoral, UZ, RU-MGIMO) | HTML + PDF calls | Per call, yearly per country | **Yes, by construction** |
| 2 | State Programme programme list (edu.gov.az news + linked list) | AZ Ministry of Science and Education; funded by SOFAZ | Foreign programmes the state will fund | 4,405 programmes, 221 institutions, 32 countries (2025-26); quota 500 people/year | HTML announcement + linked list (format **Unverified**) | Yearly | **Yes, AZ-only** |
| 3 | Stipendium Hungaricum partner list + Study Finder | Tempus Public Foundation (HU) | Degree scholarships by sending partner | >100 sending partners; AZ is one | HTML | Yearly call | **Yes** (AZ listed) |
| 4 | SI Scholarship for Global Professionals | Swedish Institute | Master's scholarships, eligible-programme list | 1 programme, 34 eligible countries | HTML + published programme list | Yearly | **Yes** |
| 5 | Chevening Azerbaijan page | UK FCDO | Chevening + partner awards | 1 programme + partner awards | HTML | Yearly | **Yes** |
| 6 | Fulbright Foreign Student Program (US Embassy Baku) | US Embassy Baku / IIE | US master's grants | 1 programme | HTML | Yearly | **Yes** (AZ residents) |
| 7 | DAAD scholarship database | DAAD | DAAD + other German funders, filterable by origin | Count **Unverified** (JS-rendered filter) | HTML, JS filter | Continuous | Per programme; e.g. FES names post-Soviet states |
| 8 | Study in Kazakhstan state scholarship | KZ Ministry of Science and Higher Education / Center for International Programs | Degree scholarships for foreigners in KZ | 550 recipients 2026-27 | HTML news + PDF lists | Yearly | **Unverified** whether AZ citizens are eligible |
| 9 | EURAXESS funding search | European Commission | Research funding offers | 124 funding offers (2026-10-03) | HTML | Continuous | Not citizenship-filtered; mostly PhD/postdoc |
| 10 | IsDB scholarships (+ YTB-IsDB joint) | Islamic Development Bank | MSc/PhD/post-doc programmes for member countries | 3-4 programmes | HTML + PDFs | Yearly | **Unverified** (AZ membership not fetched; eligibility only in PDFs) |

Notes that change the ranking:

- **#1 and #2 are the official aggregated lists the question asked for.** htp.edu.az is the only
  official source that lists, for Azerbaijani citizens specifically, the government-to-government
  scholarships (#1); the State Programme list (#2) is a home-side funder, but its *programme list*
  is a bulk dataset of eligible foreign institutions. Your closed home-side list probably names the
  programme already. The list is what the four channels do not cover.
- **#3-#6 are single-programme pages.** Each is one fetch for one high-value award confirmed open to
  AZ citizens. Cheap enough to add by hand to the closed list rather than as a channel.
- **#7 overlaps channel 4.** DAAD is the German equivalent of CampusBourses. Add it only if channel 4
  does not already include it.
- **#8-#10 are low yield for this student.** KZ eligibility for AZ citizens is not confirmed, EURAXESS
  is research-only, and IsDB's master's award is part-refundable (see below).

## Evidence per source

### 1. htp.edu.az: Intergovernmental Scholarship Programmes (official AZ-specific list)

- The Ministry launched the site to keep the public informed about HTP scholarships, by country and
  by level.[^1]
- The site's country menu lists Hungary, Morocco, China, Kazakhstan, Romania and Latvia, among
  others.[^2] Its home page also links a "Rusiya-MGIMO HTP" programme.[^3]
- It reposts other governments' calls aimed at AZ citizens. For example, the Global Korea
  Scholarship (GKS) on 17.09.2026.[^4] The site also hosts MEXT (Japan) call PDFs (seen in Brave
  results only, **Unverified** by fetch).
- Recent outcomes: "10 Azərbaycan vətəndaşı HTP çərçivəsində Latviyada təhsil alacaq".[^5]
- Context from the State Programme decree PDF (Exa snippet, not fetched, **Unverified**): about 700
  AZ citizens were studying under intergovernmental programmes in China, Latvia, Hungary,
  Kazakhstan, Romania and elsewhere.
- Format: plain HTML with a news list and per-country pages. Update cycle: one call per country per
  year. Cost: one site, scraped through the existing vendors.

### 2. State Programme 2022-2028 (home-side; its programme list is the bulk part)

- For 2025-26 the list holds 4,405 programmes at 221 institutions in 32 countries.[^6] The intake
  quota is 500 people.[^7]
- The State Oil Fund (SOFAZ) pays for it.[^8]
- The list is republished every year by ministerial order.[^9] Its file format behind the "keçid"
  link was not opened (**Unverified**).

### 3. Stipendium Hungaricum

- "Currently over 100 Sending Partners are engaged in the programme on 5 different continents".[^10]
- Azerbaijan appears in the sending-partner selector.[^11]
- HTML. The per-country page (`/country/azerbaijan/`) redirected to the generic home page when
  fetched, so the quota for AZ is **Unverified**.

### 4. Swedish Institute Scholarship for Global Professionals

- Azerbaijan is among the 34 eligible countries.[^12]
- The award covers tuition plus "A monthly allowance of SEK 12,000".[^13]
- The page also points ineligible applicants to the Study in Sweden scholarship database, which is
  a channel-4-type source.

### 5. Chevening (Azerbaijan)

- Chevening runs an Azerbaijan country page, open until 6 October 2026 for the 2027-28 intake.[^14]
- Partner awards are listed and "some go unfilled".[^15]

### 6. Fulbright Foreign Student Program (US Embassy Baku)

- Applicants must be citizens of the Republic of Azerbaijan.[^16]
- The 2027-28 deadline is 28 July 2026.[^17]
- The embassy site was the only US source checked. EducationUSA was not checked separately.

### 7. DAAD scholarship database

- The database covers DAAD programmes "as well as offers from other selected funding
  organisations".[^18]
- Example: the Friedrich Ebert Foundation scholarship targets "post-Soviet states" and offers "up to
  40 scholarships per year".[^19]
- The origin-country filter is filled by JavaScript. Neither scrapling `get` nor `fetch` returned
  its options, so the Azerbaijan filter code and the count are **Unverified**.

### 8. Study in Kazakhstan (KZ as destination)

- 550 international recipients were approved for 2026-27.[^20]
- Whether AZ citizens are eligible was not shown on a fetched page (**Unverified**).
- Bolashak itself: no fetched page states its citizenship rule. That it is for Kazakh citizens only
  is **Unverified**. The Bolashak site does run the inbound programme above, and it lists
  intergovernmental grants for Kazakhstani citizens (Brave snippet only).

### 9. EURAXESS funding

- The funding filter returns "Search results (124)", and the results include student-level items
  such as a Friedrich Naumann master's scholarship.[^21]
- HTML only. Whether there is an API or feed is **Unverified**.

### 10. IsDB

- The scholarship page describes the programmes (SPMC since 1983, Merit/PhD since 1992, MSc since
  1998).[^22]
- Unverified details, all from PDFs that scrapling returned as raw binary:
  - The member-country master's programme is "an interest-free loan (Qard Hasan)", with 50%
    refundable after graduation.
  - Study is limited to the student's own country or to Malaysia, Morocco, Tunisia and Turkey.
  - Treat it as partly a loan, which conflicts with the no-loans rule. Low priority.
- YTB runs a joint YTB-IsDB programme. Türkiye Bursları' home page announces the 2026 application
  period.[^23]
- **Azerbaijan's IsDB membership** was taken from the caller and not fetched (**Unverified**).

## Dead ends and exclusions

- **EduCanada / Study in Canada Scholarships**: the eligible-country list (Bangladesh, Nepal,
  Taiwan, Türkiye, Ukraine, MENA and Sub-Saharan countries) has no Azerbaijan. Only institutions
  can apply.[^24]
- **OAS Academic Scholarships (OEA)**: for "students from other OAS member states", so
  Azerbaijan does not qualify.[^25]
- **Organization of Turkic States: Orhun Exchange**: a semester exchange between member
  universities, published as an HTML quota table of seats per university.[^26] It funds no degrees
  and is mostly accommodation in kind (ADU's page, not fetchable as text). Not a catalogue source.
- **Heydar Aliyev International Education Grant**: inbound only. It funds *foreigners* to study in
  Azerbaijan, with 100 grants a year.[^27] Not for AZ students going abroad.
- **SOCAR Xarici Təqaüd Proqramı**: per a Brave snippet, it funds master's study only for employees
  of SOCAR Group companies. The fetch was refused (connection reset), so **Unverified**. The Heydar
  Aliyev Foundation was not found to run a study-abroad scholarship (**Unverified**).
- **Russian Federation quota (education-in-russia.com)**: the page renders only in a browser. A
  browser fetch showed a 2026 selection-test notice that names Azerbaijan, but a plain `get` returns
  an empty shell, so it cannot be cited (**Unverified**). Rossotrudnichestvo pages sit behind a
  browser check, and aze.rs.gov.ru did not resolve. The MGIMO intergovernmental route is covered
  through htp.edu.az.[^3]
- **Campus China / CSC**: HTTP 412 to automated reads. The China route for AZ citizens is the
  bilateral programme on htp.edu.az.[^2]
- **MEXT**: the call goes through each country's embassy.[^28] The Azerbaijani route appears on
  htp.edu.az (PDFs, **Unverified**). The Japanese embassy's Baku page URL that was tried returned
  404.
- **Commonwealth Scholarships, Australia Awards**: not fetched. Azerbaijan is not a Commonwealth or
  Australia Awards partner country (**Unverified**).
- **Erasmus+ project results API / EMJM**: already in use, so not re-examined.

## Sources

[^1]: https://edu.gov.az/az/news-and-updates/18596 "Məqsəd ictimaiyyətin HTP çərçivəsində müxtəlif ölkələr üzrə təhsilin müxtəlif səviyyələrində təqaüd proqramları ilə bağlı düzgün və mütəmadi məlumatlandırılmasını təmin etməkdir."
[^2]: https://htp.edu.az/az/index "Macarıstan HTP Mərakeş HTP Çin HTP Qazaxıstan HTP Rumıniya HTP Latviya HTP"
[^3]: https://htp.edu.az/az/index "RUMINİYA HTP TƏQAÜD PROQRAMI Rusiya-MGIMO HTP"
[^4]: https://htp.edu.az/az/index "təqaüd proqramı ilə Koreyada təhsil imkanı"
[^5]: https://htp.edu.az/az/index "10 Azərbaycan vətəndaşı HTP çərçivəsində Latviyada təhsil alacaq"
[^6]: https://edu.gov.az/az/news-and-updates/21834-1 "15 prioritet ixtisas sahəsi üzrə dünyanın 32 ölkəsinə aid 221 nüfuzlu ali təhsil müəssisəsində tədris olunan 4405 proqram yer alır"
[^7]: https://edu.gov.az/az/news-and-updates/21834-1 "Dövlət Proqramına qəbul üzrə kvota sayı 500 nəfər müəyyən olunub"
[^8]: https://oilfund.az/en/fund/about/educational-program2 "shall be carried out at the expense of the State Oil Fund of the Republic of Azerbaijan (SOFAZ)"
[^9]: https://oilfund.az/en/fund/about/educational-program2 "Annually, a list of educational programs in priority specialization areas, along with prestigious foreign higher education institutions"
[^10]: https://stipendiumhungaricum.hu/partners/ "Currently over 100 Sending Partners are engaged in the programme on 5 different continents"
[^11]: https://stipendiumhungaricum.hu/partners/ "Argentina Armenia Azerbaijan Bahrain Bangladesh"
[^12]: https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/ "Armenia, Azerbaijan, Bangladesh, Belarus, Bolivia, Brazil"
[^13]: https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/ "A monthly allowance of SEK 12,000"
[^14]: https://www.chevening.org/scholarship/azerbaijan/ "Open for applications until 6 October 2026, at 11:00 (UTC)"
[^15]: https://www.chevening.org/scholarship/azerbaijan/ "Chevening partners offer additional scholarships and every year, some go unfilled."
[^16]: https://az.usembassy.gov/fulbright-foreign-student-program/ "Applicants must be citizens of the Republic of Azerbaijan"
[^17]: https://az.usembassy.gov/fulbright-foreign-student-program/ "Application Deadline: July 28, 2026 (11:59 p.m.)"
[^18]: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=10000153 "as well as offers from other selected funding organisations"
[^19]: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=10000153 "post-Soviet states as well as eastern and south-eastern European (EU) countries"
[^20]: https://bolashak.gov.kz/en/allnews/550-international-students-awarded-scholarships-study-kazakhstan "the main list of 550 scholarship recipients for the 2026–2027 academic year has been approved"
[^21]: https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=offer_type%3Afunding "Friedrich Naumann Foundation for Freedom Scholarship for non-EU students (master's degree | Germany)"
[^22]: https://www.isdb.org/scholarships "IsDB launched its undergraduate scholarship program (SP) in 1983 under the title Scholarship Program for Muslim Communities (SPMC)."
[^23]: https://www.turkiyeburslari.gov.tr/ "YTB – Islamic Development Bank (ISDB) Joint Scholarship Program 2026 Applicaiton Period"
[^24]: https://www.educanada.ca/scholarships-bourses/can/institutions/study-in-canada-sep-etudes-au-canada-pct.aspx?lang=eng "Only Canadian post-secondary institutions are eligible to apply on this call"
[^25]: https://www.educanada.ca/scholarships-bourses/non_can/index.aspx?lang=eng "Scholarships available to students from other OAS member states to pursue graduate studies or research in Canada."
[^26]: https://turkunib.org/en/orhun "Student and teacher exchange quotas announced by the member universities for the current round."
[^27]: https://edu.gov.az/en/programmes/study-in-azerbaijan-layihesi "with 100 educational grants awarded annually"
[^28]: https://www.studyinjapan.go.jp/en/smap-stopj-applications-research.html "As the application process and specific schedule differ according to the country of your nationality, please inquire the Japanese Embassy or Consulate General in your country for details."

## Open questions

- **State Programme list format**: is the 4,405-programme list a spreadsheet, a PDF or HTML? Open
  the "keçid" link on edu.gov.az news 21834. This decides whether #2 is a one-shot import or a
  scrape.
- **DAAD origin filter for Azerbaijan**: the origin code and the count of programmes open to AZ
  citizens. The filter is JS-rendered, so it needs a vendor render.
- **Study in Kazakhstan**: are AZ citizens eligible, or only the Kazakh diaspora and listed
  countries?
- **IsDB**: is Azerbaijan a member? Confirm the master's-programme terms on an HTML page; the loan
  share may disqualify it.
- **Russian quota for Azerbaijan**: the yearly seat count. The official pages render only in a
  browser.
- **National open-data portals listing grants** (data.gov.az, data.go.kr GKS, EU Funding & Tenders
  API): not investigated in this pass.
- **Embassies in Baku**: beyond the US, UK and Japanese routes, no destination-country embassy list
  of scholarships open to AZ citizens was checked (France, Germany, China, Korea, Türkiye).
