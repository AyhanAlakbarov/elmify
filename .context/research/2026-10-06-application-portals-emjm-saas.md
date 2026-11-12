# Application portals: EMJM, shared admissions SaaS, scholarship portals

Researched 2026-10-06 by direct fetch (WebFetch summaries of each page, curl against the Wayback CDX/`id_` endpoints). Hosts are written as the page showed them. "UNVERIFIED" = not confirmed on a primary page in this pass. Fetch tool returns model-summarised text, so exact URL strings were copied from those summaries; re-open before relying on a path.

## 0. EMJM catalogue facts (official)

- EU: students "apply directly to the institution running their chosen programme", not centrally; "in most cases" submit October-January for the next academic year; each programme's own site holds scholarship and non-scholarship steps. Source: https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-individuals/students/erasmus-mundus-joint-masters
- Catalogue (EACEA): https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en (lists name + consortium website only; no apply link).
- 2027 new-selection list with websites (third-party, erasmuscatalogue.com): https://erasmuscatalogue.com/erasmus-mundus-catalogue-update-2027/

## 1. EMJM sample (22 programmes)

Columns: programme | consortium site host | application host and system | one application incl. EM scholarship? | apply link lives on | cycle in URL? | source

| # | Programme | Consortium site | Application host / system | One application with EM scholarship? | Link lives on | Cycle in URL | Source |
|---|---|---|---|---|---|---|---|
| 1 | GEM (MSc Geospatial Technologies... "MScGEM") | gem-msc.eu | utwente.dreamapply.com (DreamApply, vendor-subdomain, coordinator University of Twente) | Single DreamApply portal for four tracks; scholarship combined: UNVERIFIED | consortium site links out; portal is coordinator's | No (path `/courses/course/19-...`); intake stated in page text, "September 2027 intake open 1 October 2026" | https://utwente.dreamapply.com/ |
| 2 | IHE Delft EMJMs (GroundwatCH, FRM, COASTHazar, IMETE) | apply.un-ihe.org (partner's own page) | apply.un-ihe.org `/blue-connect-integratie/create-application?application_process_code=EP` (university's own system) | Yes: "apply for admission to and a scholarship for" in one application | Partner university site | No (code `EP`); cycle in page text 2027/2029 | https://apply.un-ihe.org/application-process/master-of-science-erasmus |
| 3 | MultiDiverse | www.multidiverse.eu | zeus.uni-konstanz.de `/hioserver/pages/cs/sys/portal/hisinoneStartPage.faces?page=Master BewerberIn...` (coordinator's HISinOne portal) | UNVERIFIED (site has separate "Application & Admission" and "Scholarships & Fees" sections) | Consortium page `/applications` links to coordinator | No; "next intake 2027/28, Nov 2026 - 15 Jan 2027" in text | https://www.multidiverse.eu/applications |
| 4 | ILSPSD | master-international-law-erasmusmundus.eu | awards.leuphana.de `/datenabfrage/ilspsd2027-scholarship` and `/datenabfrage/ilspsd2027-self-funded` (coordinator's award system) | NO: two portals by funding track, different deadlines (4 Jan 2027 vs 31 Mar 2027) | Consortium site; stable guide page `/step-by-step-application-guide/` | YES: `ilspsd2027` in path | https://master-international-law-erasmusmundus.eu/ (fetched; Wayback: guide link identical in 2025-10 and 2026-06 snapshots) |
| 5 | CYBERSURE | www.cybersure-master.eu | fsweb.no `/soknadsweb/login.jsf?inst=ntnu` (NTNU's FS portal; shared Norwegian FS host, per-institution `inst=`) | Yes: one application, scholarship choice inside | Consortium `/admission/how-to-apply` | No; cycle in text (2027 intake, 16 Nov 2026 - 4 Jan 2027) | https://www.cybersure-master.eu/admission/how-to-apply |
| 6 | SuCat | www.master-sucat.eu | survey.appli.univ-poitiers.fr `/818799?lang=en` (coordinator's survey tool; numeric id) | Yes: one file, degree + scholarship | Consortium `/how-to-apply/` | Numeric form id only (818799); "2026-2028" in text | https://www.master-sucat.eu/how-to-apply/ |
| 7 | TFMASA | tfmasa.com | tfmasa.tchooz.app `/tfmasa-2026-1` (Tchooz, a vendor host with per-programme subdomain) | One application; scholarship wording not explicit | Consortium `/application/`; Wayback 2025-12 snapshot already linked `tfmasa.tchooz.app` | YES: `tfmasa-2026-1` | https://tfmasa.com/application/ |
| 8 | EGEI | www.master-egei.eu | form.jotform.com `/242865034099362` (JotForm, shared vendor host, numeric id per form) | Combined (scholarships awarded off the same form): per site | Consortium `/how-to-apply/` | Form id changes per cycle: 203333678135354 (2021), 212842086007350 (2022), 242865034099362 (now) | https://www.master-egei.eu/how-to-apply/ ; Wayback `20210513031205`, `20220929143818` |
| 9 | CNE | master-cne.eu | application.master-cne.eu `/index.php?lang=en` (own bespoke subdomain) | Scholarships integrated: per site | Consortium | No | https://master-cne.eu/ |
| 10 | RADMEP+ | master-radmep.org | international-sciencemasters.univ-st-etienne.fr `/login` (coordinator's portal shared by several Saint-Etienne science masters) | UNVERIFIED | Consortium links out | No; "15 Oct 2025 - 9 Feb 2026, 2026-2028" in text | https://master-radmep.org/ |
| 11 | RESCO | resco-master.eu | e-admission.bme.hu `/login/signup.php?lang=en` (BME, a partner's own system) | UNVERIFIED | Consortium | No | http://resco-master.eu/ |
| 12 | Euroculture | www.euroculturemaster.eu | formdesk.nl `/rug/euroculture` (Formdesk tenant of Groningen, in the 2024-06 snapshot); current host not captured | Site says full application needed for scholarship consideration: one application implied, UNVERIFIED | Consortium `/online-application-tool` (stable path, 2024-2025 snapshots) | No | Wayback `20240606063851`; https://www.euroculturemaster.eu/erasmus-mundus-scholarship |
| 13 | STEPS | www.emjmdsteps.eu / emjmdsteps.em.uniovi.es | emjmdsteps.em.uniovi.es `/emjmd_steps_rock_02.html` (bespoke login at coordinator Oviedo) | Yes: scholarship ticked inside the online form; plus hard copies by post | Consortium site | No; "open until 8 Jan 2027" | https://www.emjmdsteps.eu/students/admission |
| 14 | TERRA | msc-terra.org | UNVERIFIED (apply form not exposed in the fetched text; page `/applications/`) | Yes: one application automatically considered for EM + consortium scholarship | Consortium | UNVERIFIED | https://msc-terra.org/applications/ |
| 15 | Mundus Journalism (EMMA) | mundusjournalism.com | Online Registration Form on consortium site (bespoke; coordinator Aarhus); host of form UNVERIFIED | Yes: "admission and an EM scholarship through the same online application" | Consortium `/admissions/application-process` | No; 2027-2029 opens 1 Nov 2026 | https://mundusjournalism.com/admissions/application-process |
| 16 | CLIDE | clide.umk.pl | irk.umk.pl `/en-gb/offer/U2026/programme/11550305-KRK/` (coordinator's IRK system) | Not stated | Consortium PDF guide + link | YES: `U2026` | https://clide.umk.pl/ |
| 17 | REM Plus Plus | master-remplus2.eu | `master-remplus2.eu/online-application-form/` (bespoke, consortium host); procedure "under review" | Fetch: grants handled separately; page says procedure under review: UNVERIFIED | Consortium | No | https://master-remplus2.eu/application-procedure/ |
| 18 | BIOPHAM | www.master-biopham.eu | Path `/how-to-apply/application-procedure/2/...` on consortium site; external host not exposed: UNVERIFIED | Single call covers scholarship and non-scholarship | Consortium (Lille coordinator) | No; "1 Nov 2026 - 1 Feb 2027" | https://www.master-biopham.eu/ |
| 19 | LAWGID | lawgid.ius.bg.ac.rs | Not disclosed (`/application/` page; links by email) | Likely one form (step 4 for scholarship): UNVERIFIED | Consortium | No | https://lawgid.ius.bg.ac.rs/application/ |
| 20 | EPS (Vaclav Havel) | epsmaster.eu | is.cuni.cz `/studium/eng/prijimacky/` (Charles University admissions IS); separate windows for scholarship and self-payers | Scholarship and self-payer tracks distinct | Consortium | No | https://epsmaster.eu/ |
| 21 | EMMIR | www.emmir.org | Not captured (`/applications`) | UNVERIFIED | Consortium | "Edition 14 (2027-2029)" in text | https://www.emmir.org/ |
| 22 | MAIA / FIPDes / GLODEP / ISSF | maiamaster.udg.edu / www.fipdes.eu / glodep.eu / issf-master.eu | Not exposed in fetched text (MAIA "open soon", ISSF "2027 intake will soon open") | UNVERIFIED | Consortium | UNVERIFIED | respective homepages |

Not reachable in this pass (fetch errors): emle.eu, maiamaster.eu, master-ediss.eu, maisi-project.eu, mastergeotech.info.

### Share (of the 14 rows where the host was captured: 1-11, 13, 16, 20)

- DreamApply: 1 of 14 (GEM, `utwente.dreamapply.com`). Stipendium Hungaricum (scholarship, section 3) is also DreamApply. A search-engine claim that DreamApply is common for EMJM was not supported by consortium pages beyond GEM; treat as 1 sample.
- Coordinator/partner university's own system: 8 (IHE, MultiDiverse/HISinOne, ILSPSD/Leuphana awards, CYBERSURE/fsweb NTNU, SuCat/Poitiers survey, RADMEP/Saint-Etienne, RESCO/BME, CLIDE/IRK, EPS/Charles University IS, STEPS/Oviedo bespoke counted below).
- Generic form SaaS (vendor host): 3 (JotForm EGEI, Tchooz TFMASA, Formdesk Euroculture historical).
- Bespoke form on consortium domain: CNE, STEPS, Mundus Journalism, REM++ (4).
(Categories overlap marginally; counts are from a small, non-random sample.)
- Combined degree + EM scholarship in one application: stated for IHE, CYBERSURE, SuCat, STEPS, TERRA, Mundus Journalism, BIOPHAM, TFMASA(implied), EGEI. Separate by funding track: ILSPSD (two portals), EPS (distinct windows), REM++ (per fetch).
- Link location: always discoverable from the consortium site; the actual form is on the coordinator's or a partner's host in most cases (a consortium site is NOT the portal host).

### Stability of apply link across cycles (Wayback CDX, curl, 2026-10-06)

- EGEI: consortium page `www.master-egei.eu/how-to-apply/` stable 2021-2026 (snapshots 2021-01 to 2022-09 all 200). The JotForm URL changes every cycle (new numeric id each year), host constant.
- ILSPSD: consortium page stable; the guide link unchanged 2025-10 to 2026-06; the portal path embeds the cycle (`ilspsd2027-*`) so it changes yearly.
- TFMASA: `/application/` snapshots 2025-12, 2026-01, 2026-10; Tchooz host linked already in 2025-12; per-cycle path `tfmasa-2026-1`.
- Euroculture: `/online-application-tool` stable path 2024-06 to 2025-08; external tool host differed over time (Formdesk in 2024, current UNVERIFIED).
- GEM: `utwente.dreamapply.com/` only one snapshot (2025-10); DreamApply course path uses programme id not year.
- CYBERSURE: how-to-apply page two snapshots (2025-11, 2026-03); portal host fsweb.no constant, cycle in text only.
Conclusion: the consortium's "how to apply" page URL is the stable anchor; the form URL is stable only when the vendor gives an id-free path (DreamApply, fsweb) and is per-cycle when the tool is a form builder (JotForm, Tchooz, Leuphana awards, IRK `U2026`).

## 2. Shared admissions SaaS: hosting and whether host identifies the university

| System | Hosting pattern | Host per university? | Source |
|---|---|---|---|
| DreamApply | Vendor subdomain e.g. `utwente.dreamapply.com`; also a custom host `apply.stipendiumhungaricum.hu` (reported as DreamApply). Custom-domain/CNAME policy: UNVERIFIED (help page does not state) | Per tenant (subdomain), `dreamapply.com` itself is shared and not a portal | https://utwente.dreamapply.com/ ; https://stipendiumhungaricum.hu/apply/ ; https://help.dreamapply.com/kb/get-started/basics/ |
| Slate (Technolutions) | Customer-chosen host such as `apply.university.edu` as CNAME to `cluster.technolutions.net` (US); exclusive to that customer | Per university; target `technolutions.net` is shared infrastructure, never a portal | https://knowledge.technolutions.net/docs/changing-your-slate-subdomain ; https://knowledge.technolutions.net/docs/domain-verification |
| Liaison GradCAS (and other CAS) | Shared central host `gradcas.liaisoncas.org/apply/` (also `gradcas2025.cas.myliaison.com`); one application, many programs/universities | SHARED: one host serves many universities | https://www.liaisonedu.com/centralized-application-service/gradcas/ ; https://help.liaisonedu.com/GradCAS_Applicant_Help_Center |
| CollegeNET ApplyWeb | Vendor-hosted `www.applyweb.com/...` (applicant status page `www.applyweb.com/system/ustat`); institution selected by path | SHARED host; university in path | https://www.applyweb.com/instructions ; https://collegenet.com/admissions |
| SoftDocs Etrieve | Per customer `*.etrieve.cloud` (e.g. `unlvcontent.etrieve.cloud`, `chathamcentral.etrieve.cloud`) or on-prem `etcentral.ad.cfcc.edu`. A forms/workflow tool, not an application system per se | Per university subdomain | search results at https://help.unlv.edu/TDClient/33/IT-Support-Portal/KB/Article/2297/Softdocs-Etrieve-Quick-Start-Guide |
| Kira Talent | Interview add-on, `app.kiratalent.com` (shared); applicants arrive via the university's system | SHARED host, not an application portal | https://www.kiratalent.com/ ; https://knowledge.technolutions.net/docs/kira-talent-integration |
| Tribal SITS e:Vision | University host `evision.<univ>.ac.uk` (e.g. `evision.city.ac.uk`); hosted by university or by Tribal | Per university | https://blogs.city.ac.uk/accessibility/evision-sits/ |
| Studielink | One national host `www.studielink.nl` for all Dutch universities; then each university's own admissions portal does the evaluation | SHARED national host | https://www.tudelft.nl/en/education/admission-and-application/bsc-dutch-diploma/apply-via-studielink ; https://www.eur.nl/en/ese/education/master/admission-requirements/how-apply-studielink |
| Salesforce Experience Cloud | Salesforce default host (`*.my.site.com`, UNVERIFIED in sources) or customer custom domain (documented) | Per university when custom domain; shared vendor domain otherwise | https://help.salesforce.com/s/articleView?language=en_US&id=experience.networks_custom_domain.htm&type=5 |
| Ellucian CRM Recruit | `<institution>.elluciancrmrecruit.com` e.g. `aacc.elluciancrmrecruit.com/Apply/Account/Login` | Per university subdomain under shared vendor domain | search snippet; https://www.ellucian.com/assets/emea-ap/solution-sheet/emea-ellucian-crm-recruit.pdf |
| Others seen in EMJM sample | Tchooz (`<programme>.tchooz.app`), JotForm (`form.jotform.com/<id>`), Formdesk (`formdesk.nl/<org>/<form>`), fsweb.no (`?inst=ntnu`), Leuphana awards (`awards.leuphana.de/datenabfrage/<key>`) | Identity is in the subdomain or path or query, never the host alone | section 1 |

Rule for the product: key a portal on host only when the host is exclusive to one customer (`utwente.dreamapply.com`, `apply.*.edu`, `evision.*.ac.uk`). For shared hosts (`gradcas.liaisoncas.org`, `www.applyweb.com`, `www.studielink.nl`, `form.jotform.com`, `fsweb.no`, `awards.leuphana.de`, `app.kiratalent.com`) the identity needs host plus a tenant discriminator (path prefix, `inst=`, form id), or must be treated as a "platform" not a portal.

## 3. Scholarship portals separate from the degree application

| Scheme | Host | Combined or separate | Order | Source |
|---|---|---|---|---|
| DAAD (most study scholarships) | `www.meindaad.de` (DAAD portal; email portal@daad.de) | Scholarship applied in DAAD portal; degree admission is separate for most programmes. For some (EPOS) the application goes to the course/university and is not forwarded. Exact order per programme: UNVERIFIED | Programme-specific | search result https://www.meindaad.de/en/help/how-do-i-register-for-an-application/ ; https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50076777 (DAAD homepage fetch refused) |
| Swedish Institute SISGP | Admission at `universityadmissions.se`; scholarship portal linked from `si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/` | Separate, two steps; the 8-digit admissions application number is needed in the SI portal | Degree first (15 Jan), then SI documents (9-25 Feb 2026) | search summary; official si.se page returned 403 so UNVERIFIED on primary |
| Stipendium Hungaricum | `apply.stipendiumhungaricum.hu` (DreamApply) | Scholarship application is the application; picks 2 programmes among 30 institutions; cannot apply to universities directly; entrance exams afterward at universities | Scholarship application first (15 Jan 2026), then exams (Mar-May), award June | https://stipendiumhungaricum.hu/apply/ |
| Turkiye Burslari | `tbbs.turkiyeburslari.gov.tr` | Scholarship application includes university placement ("ensures university placement"); choices inside UNVERIFIED | Scholarship first, placement after | https://turkiyeburslari.gov.tr/en |
| GKS / KGSP (NIIED) | `studyinkorea.go.kr` (embassy track); university track applies at the university | Embassy track: scholarship application lists up to 3 universities; University track: one university and department directly | Parallel/embedded; track decides | search summary https://www.topikguide.com/global-korea-scholarship-niied-kgsp-undergraduate-scholarship/ (primary page 404 on the URL tried, UNVERIFIED) |
| MEXT (Japan) | Via Japanese embassy/consulate or via a Japanese university | Two routes; relation to degree admission not stated on page | UNVERIFIED | http://www.studyinjapan.go.jp/en/planning/scholarships/about-scholarships/ |
| CSC (China) | `studyinchina.csc.edu.cn` plus the university's own application system | Type A (embassy) vs Type B (university): Type B needs both the university and CSC portal applications | Parallel | search summary (university pages cup.edu.cn, zju.edu.cn); campuschina.org not reachable, UNVERIFIED primary |
| Chevening | Chevening site, per-country page (portal host UNVERIFIED) | Separate: scholarship first, then university applications | Scholarship first (Aug-Oct 2026), then unconditional UK offer by 8 Jul 2027 | https://www.chevening.org/scholarships/application-timeline/ |
| Fulbright Foreign Student | `apply.iie.org/ffsp2027` (IIE placed track) | One application; IIE places the grantee at US universities and applies on their behalf | Scholarship first, placement after | search summary https://cr.usembassy.gov/wp-content/uploads/sites/129/2026/01/Instructions-Foreign-Student-Program-Online-Application-IIE-Placed-27-28.pdf (country-specific variations exist) |
| Erasmus Mundus scholarship | Consortium's own portal (section 1) | Mostly one combined application; some run separate tracks (ILSPSD, EPS) | Combined | https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-individuals/students/erasmus-mundus-joint-masters |

## Patterns

1. Consortium site, coordinator's portal: the stable item is the consortium's "how to apply" page; the form sits on a coordinator or partner host (zeus.uni-konstanz.de, irk.umk.pl, fsweb.no, awards.leuphana.de, apply.un-ihe.org). Store the programme's apply-page URL plus the discovered portal host. The portal host belongs to the coordinator, so it is shared across all that university's programmes.
2. Vendor tenant host, exclusive (DreamApply `utwente.dreamapply.com`, Slate `apply.x.edu`, e:Vision): host identifies the tenant; many programmes can sit under one portal (GEM has 4 tracks in one portal).
3. Shared vendor host (JotForm, Tchooz, Formdesk, GradCAS, ApplyWeb, Studielink, Kira, fsweb.no): host does NOT identify a portal; require a discriminator (path/query/id) or treat as a platform class.
4. Per-cycle URL: the form URL changes each intake (EGEI JotForm id changes yearly; ILSPSD `ilspsd2027-*`; TFMASA `tfmasa-2026-1`; CLIDE `U2026`). Store per programme per cycle, and treat the consortium page as the durable key from which to re-discover the link each cycle.
5. Route split inside one programme: scholarship vs self-funded can be separate portals with different deadlines (ILSPSD, EPS, Stipendium Hungaricum/University Track vs Embassy Track, CSC Type A/B). Store per (programme, cycle, route).
6. Scholarship as its own application with the degree application elsewhere (SISGP -> universityadmissions.se, DAAD, Chevening, CSC Type B, MEXT, SH exams): two linked portals with an ordering and a shared identifier (SISGP needs the admissions number). Model as two portal records linked by order (degree-first or scholarship-first or parallel).
7. Scholarship that embeds placement (Fulbright IIE, Turkiye Burslari, SH): one scholarship portal; the degree "application" is done by the scheme, so no university portal exists for the student.
8. Gateway portal (Studielink): a national host that forwards to each university's own admissions portal; the first record is the gateway, the second is the evaluating portal.

Implications for storage: one link per programme is not enough. Minimum record: programme (or consortium) -> routes (scholarship, self-funded, embassy/university track) -> per cycle -> portal(s) with order and tenant discriminator, plus the durable "how to apply" page URL for re-discovery. Intake in URL is a hint for staleness, not a reliable signal (absent in most samples).
