# Application systems seed: row-by-row verification (2026-10-09)

Input: `2026-10-08-application-systems-draft.csv` (42 rows). Output: `2026-10-09-application-systems-verified.csv` (38 rows, draft columns plus `verified`).

Result: 26 YES, 10 PARTIAL, 2 NO, 4 dropped. 15 kept rows changed.

## Method

- I loaded every `source_url` with curl, then retried blocked pages with Tavily extract or Scrapling stealth. Pages blocked to curl were monmaster (403), OUAC (403), CSC (412), Chevening (connection refused), the ApplyWeb support site (403) and Studyinfo (an SPA).
- I probed every listed host over `https://` and recorded the final URL after redirects. I also read the outbound links on each official page to find the host where the applicant actually logs in. That pass found five missing application hosts.
- For the wildcard rows I checked DNS on a made-up tenant name. `*.dreamapply.com`, `*.tchooz.app`, `*.osiris-student.nl` and `*.cas.myliaison.com` all have wildcard DNS. So a hostname that resolves does not prove a tenant exists. `*.esse3.cineca.it`, `*.elluciancrmrecruit.com` and `*.etrieve.cloud` do not have wildcard DNS.
- `verified` values:
  - YES: every host and every non-empty policy value was checked against an official page loaded in this session.
  - PARTIAL: some part could not be confirmed, or the host list cannot be complete or safe as a pattern.
  - NO: the row should not be used as host-level trust.

## Security findings that cut across rows

1. **A vendor wildcard tells you which vendor runs a page. It does not tell you which university owns it.** `*.dreamapply.com`, `*.tchooz.app` and similar patterns let you recognise the software. They never show that a tenant belongs to a particular university. Any customer of the vendor gets a subdomain, and four of these vendor domains answer DNS for any name. Accept a tenant host only when a link on the university's own official domain points to it, and bind the host to that one university.
2. **A wildcard under an open TLD is a look-alike hole.**
   - The draft's `ecandidat.*.fr` matches `ecandidat.<any-registered-name>.fr`. Anyone can register a `.fr` name, so this pattern trusts an attacker's domain. Replaced with five tenants I loaded.
   - `apply.*.edu` (Slate) is also wrong. Slate tenants use any subdomain on any TLD; for example `apply.iie.org` is the Fulbright tenant. Removed (see the slate row).
   - `evision.*.ac.uk` is lower risk because `.ac.uk` registration is restricted. It is still incomplete.
3. **A generic form builder is not an application system.** Anyone can publish a form on `form.jotform.com` or `formdesk.com` in minutes. A look-alike "University X application" on those hosts would match a host-level rule. Both rows are marked NO. Trust only an exact form URL linked from the university's own domain.
4. **A demo or test instance looks like the real one.** `fs-demo.uio.no/soknadsweb/...` serves the same Søknadsweb login page as `fsweb.no`. Exact-host matching handles this. Fuzzy matching on page title would not.
5. **Pastel (Etudes en France) sends an incomplete TLS chain.** `pastel.diplomatie.gouv.fr` serves only its leaf certificate (Gandi). Browsers fix this through AIA. curl and Python `requests` fail with "unable to verify the first certificate". A host checker using a strict client will report the real host as broken. Do not "fix" this by turning off verification.

## Rows to drop (removed from the verified CSV)

| slug | why | URL |
|---|---|---|
| pac-ie | Defunct. The live page says "PAC has ceased to trade from September 30th 2024". A dead host should not be seeded as a trusted portal. If the platform wants to warn about it, it belongs on a denylist, not this table. | https://www.pac.ie/ |
| ucas-postgraduate | Not an application route. The page says "You apply directly to the provider for postgraduate courses". It also duplicates `www.ucas.com`, which would make host-to-system lookup ambiguous. | https://www.ucas.com/postgraduate/what-to-study/choosing-a-course |
| kira-talent | A video-interview and assessment add-on, not an application system. Its login is on a second host (`app.kiratalent.com` redirects to `auth.kiratalent.com`), which the draft did not list. | https://www.kiratalent.com/ |
| etrieve | A document and workflow forms product. The only example tenant (`unlvcontent.etrieve.cloud`) is a content and forms login, not an admissions system. The vendor page could not be found. | https://unlvcontent.etrieve.cloud/Account/Login |

## Rows not safe to seed as-is

- **jotform (NO) and formdesk (NO):** generic form builders (finding 3 above).
- **slate (PARTIAL):** hosts left empty on purpose. A tenant is recognised in three ways:
  - Its DNS is a CNAME to `cluster.technolutions.net` or a regional cluster (`cluster.ca-central-1`, `cluster.eu-west-1` or `cluster.ap-northeast-1.technolutions.net`). Technolutions requires a CNAME, never an A record (source below). Verified: `apply.iie.org` has a CNAME to `cluster.technolutions.net`.
  - Slate URL shapes such as `/apply/?sr=<guid>`, `/register/`, `/portal/` and `/account/login`.
  - Most importantly, the host's registrable domain equals the university's official domain.

  The first two only prove the page is Slate. Only the third ties it to the institution. Source: https://knowledge.technolutions.net/docs/changing-your-slate-subdomain
- **ecandidat (PARTIAL):** list hosts per tenant only, never the wildcard (finding 2).
- **mobility-online, osiris (PARTIAL):** these are mobility and student-records tools. Treat them as "known university software" and do not send students to them as degree-application portals.

## Per-row results

### NATIONAL rows

**universityadmissions-se** (YES, no change)
- Loaded: "You can select up to four master's programmes" (rises to five after results).
- Rank page: you cannot change the ranking order after the deadline.
- Fee page: "One application fee per semester … you pay 900 kronor just one time".
- `www.antagning.se` is the Swedish-language twin and resolves to `/se/start`. http redirects to https.
- URLs: the source_url, https://www.universityadmissions.se/en/apply-to-masters/rank-your-selections-masters/ and https://www.universityadmissions.se/en/apply-to-masters/pay-your-application-fee-non-eueea-masters/

**studyinfo-fi** (YES, no change)
- Loaded (Tavily): "apply to up to six (6) study programmes with one application form".
- Ranking varies by round: the English-taught spring round is unranked, the autumn round is ranked. Empty `ranked` is correct.
- Fee page: "one application fee covers all applications for programmes starting in the same academic term", EUR 100.
- `studyinfo.fi` redirects to `opintopolku.fi`.
- URLs: source_url and https://opintopolku.fi/konfo/en/sivu/application-fee

**studielink-nl** (YES, no change)
- PDF loaded: "You may submit up to four enrolment applications per academic year, of which only one or two may be for … numerus fixus".
- Host `www.studielink.nl` confirmed. http redirects to https.

**uni-assist-de** (YES, changed `prep_lead_days` from 42 to 56)
- The page states the lead time directly: "Apply as early as possible, at least 8 weeks before the deadline expires" (56 days).
- 42 came from the evaluation time ("usually 4 to 6 weeks"). That is a processing time, not a lead time. Current times by region are 3 to 5 weeks.
- `one_fee_per_round=false` is confirmed by the handling-fees page: "first chosen course of study: EUR 75.00, each additional: EUR 30.00".
- URLs: source_url and https://www.uni-assist.de/en/how-to-apply/pay-all-fees/handling-fees/

**hochschulstart-de** (YES, added host `dosv.hochschulstart.de`)
- The official page sends "DoSV-Bewerbungsportal" links to `https://dosv.hochschulstart.de/bewerber`. That is where applicants log in, and the draft missed it. At probe time it redirected to `wartung-bw.hochschulstart.de`, a maintenance page.
- 12 is confirmed: "Sie können sich auf bis zu 12 verschiedene „Studienangebote" bewerben". `ranked=true` is confirmed: "Priorisieren … Wunsch-Reihenfolge"; lower-priority offers are replaced by higher ones.
- Covers mainly bachelor's and locally restricted programmes.
- URLs: https://www.hochschulstart.de/bewerben-beobachten/bewerbung and https://www.hochschulstart.de/bewerben-beobachten/priorisierung

**monmaster-fr** (YES, no change; this row had been snippet-only)
- Loaded through Tavily extract (curl gets 403): "jusqu'à 15 vœux dans des formations hors alternance et 15 vœux dans des formations en alternance", counted per mention per institution.
- `monmaster.gouv.fr` loaded (the candidate platform).
- Note: Azerbaijan is on the Etudes en France country list, so most Azerbaijani applicants still resident in Azerbaijan use Etudes en France, not Mon Master.

**etudes-en-france** (PARTIAL, filled `one_fee_per_round=true`)
- Campus France Azerbaijan (official) charges one 250 AZN registration fee per dossier, after online submission: "250 AZN olan qeydiyyat ödənişi". The amount varies by country office.
  - https://www.azerbaidjan.campusfrance.org/az/etudes-en-france-s-n-d-q-bulu-proseduru
- `choice_limit=7` is kept, but it is confirmed only on the Campus France **Mali** page ("7 choix pour les formations au-delà de la première année (L2, L3, Master)"), not for Azerbaijan. That is why the row is PARTIAL.
- `pastel.diplomatie.gouv.fr` is the platform, linked from the Azerbaijan Campus France site. See finding 5 on its TLS chain.
- Azerbaijan is an Etudes en France country: https://www.campusfrance.org/fr/faq/quels-sont-les-pays-relevant-de-la-procedure-etudes-en-france

**universitaly-it** (YES, filled `choice_limit=1`, added host `universitaly-private.cineca.it`, new source_url)
- The MUR circular for 2026-27/2027-28 says the pre-enrolment application must "indicare uno solo dei corsi di studio" (a single programme). The visa refers to a single course.
  - Source: https://universitaly-private.cineca.it/uploads/universitaly-pubblico/Circolare_2026-2027_studenti_internazionali.pdf (linked from universitaly.it)
- Login and pre-enrolment run on `universitaly-private.cineca.it/index.php/login`, linked 15 times from www.universitaly.it. A host check on `www.universitaly.it` alone would flag the real login page as foreign.
- The portal is "gratuito", so `one_fee_per_round` stays empty.

**optagelse-dk** (YES, no change)
- Loaded: "You can apply for up to 8 programmes", added to "your list of priorities".
- For bachelor's programmes. Master's applicants apply direct to the universities.

**samordna-opptak-no** (YES, no change)
- Loaded: "En person/søker kan søke ti studier i prioritert rekkefølge".
- `sok.samordnaopptak.no` is the "Søkerportalen" applicant portal.

**ucas-undergraduate** (YES, added host `accounts.ucas.com`)
- Loaded: "add up to five choices"; "For 2027 entry, the application fee is £34.50 for up to five choices".
- Sign-in goes to `accounts.ucas.com`. That host returns 403 to curl but is linked from the official page.
- Undergraduate only, so not relevant to master's applicants.

**cao-ie** (YES, no change)
- Loaded: "10 course choices on the Level 8 course list and 10 on the Level 7/6 course list"; "genuine order of preference".
- Applications run on `www.cao.ie/apply.php`, the same host.

**ouac-ca** (YES, no change; this row had been snippet-only)
- Loaded with Scrapling (Cloudflare): "Base Application Fee: $159 … Additional Choice Fees: $51 per choice", so `one_fee_per_round=false` is confirmed.
- The "My Account" and "Apply" links go to `www.ouac.on.ca/apply/dashboard/...`, the same host.
- Undergraduate application only.

**uac-au** (PARTIAL, added host `apply.uac.edu.au`)
- The official page links "apply" to `apply.uac.edu.au/welcome`. The draft lacked it.
- `www.uac.edu.au` redirects to `uac.edu.au`. Kept as an official alias.
- `choice_limit=5` is right for undergraduate applicants. The same page says postgraduate and international Year 12 applicants get **six**. Split the row if UAC postgraduate is used.
- One fee covering all preferences is confirmed: preference changes are free.
- URLs: source_url and https://uac.edu.au/current-applicants/undergraduate-applications-and-offers

**vtac-au** (YES, added host `vtacapplicantsportal.vtac.edu.au`)
- The applicant sign-in is `vtacapplicantsportal.vtac.edu.au/signin`, linked from the official page.
- "up to eight courses, which must be ranked in the order of your preference".
- One course application processing fee per application (dates page: a single "Fee" per course application).
- URLs: source_url and https://vtac.edu.au/dates

### SCHOLARSHIP rows

**gks-korea** (YES, no change)
- Loaded: "Embassy Track applicant may choose up to THREE different universities from Type A and B and MUST apply to at least one … Type B". This is the graduate section (Research, KDI, R&D tracks).
- "Embassy Track: Online application through the Study in Korea website (www.studyinkorea.go.kr)".
- University Track applicants apply to one university directly.

**csc-china** (YES, changed hosts and source_url)
- `www.csc.edu.cn/laihua` now redirects to `www.campuschina.org`, the CSC "Study in China" site.
- That site's "Scholarship Application for Students" link goes to `https://studyinchina.csc.edu.cn/#/login`.
- `www.csc.edu.cn` is the CSC homepage and mostly serves outbound Chinese students, so it was replaced by `www.campuschina.org`.
- No official page states a choice limit, so the policy fields stay empty.

**stipendium-hungaricum** (YES, no change)
- Loaded: "Applications are processed in an online application system (apply.stipendiumhungaricum.hu) … only 2 choices are allowed". The FAQ says you cannot "edit the order of the priorities".
- The portal is a DreamApply instance on a custom domain.

**turkiye-burslari** (YES, no change)
- Loaded: applications run "via the Türkiye Scholarships Application System (TBBS)" from 10 January to 20 February, with university placement included.
- `tbbs.turkiyeburslari.gov.tr` is the login page.
- No official page gives the number of preferences, so `choice_limit` stays empty.

**daad-portal** (YES, no change)
- Loaded: "The DAAD portal can be accessed via www.meindaad.de/en/".

**si-scholarships** (YES, no change; this row had been snippet-only)
- The official si.se page states: "Your scholarship application can include up to four eligible master's programmes". The text sits in collapsed sections, read via Tavily's index of that URL. The curl copy confirmed the page and the 9–25 February 2026 portal window.
- `apply-scholarships.si.se` is a DreamApply instance.

**chevening** (PARTIAL, no change)
- Loaded with Scrapling: "three UK master's degree choices in order of preference".
- The application-portal host could not be verified. The window is closed. The portal is reached only through "apply today" links and emailed per-applicant links (sent from `chevening.awards@notifications.service.gov.uk`). `apply.`, `applications.` and `portal.chevening.org` do not exist.
- `www.chevening.org` is the information site, not the portal. Re-check the portal host when the next window opens (August 2027).

**fulbright-iie** (YES, new source_url; this row had been snippet-only)
- The US Embassy page (2027-28) says "please list in priority order up to four schools of your choice". Listing preferences is optional, and IIE applies on the candidate's behalf.
- The US Embassy Baku pages give the link `https://apply.iie.org/ffsp2027`.
- `apply.iie.org` is IIE's Slate tenant (CNAME to `cluster.technolutions.net`). The bare host redirects to www.iie.org. Only the `/ffsp2027` path is the application.
- URLs: https://hr.usembassy.gov/apply-now-for-the-fulbright-foreign-student-program-for-the-2027-2028-academic-year and https://az.usembassy.gov/fulbright-foreign-student-program

### VENDOR rows

**dreamapply** (YES, no change)
- `utwente.dreamapply.com` loaded (its links show it serves the GEM Erasmus Mundus programme).
- Custom-domain tenants exist: `apply.stipendiumhungaricum.hu`, `apply-scholarships.si.se`. They are recognised by the DreamApply marker on the page plus a link from the owner's domain.
- Wildcard DNS (see finding 1).

**slate** (PARTIAL, emptied `hosts`)
- See "Rows not safe to seed".

**collegenet-applyweb** (PARTIAL, added host `applyweb.collegenet.com`)
- `www.applyweb.com/public/account` and `/system/ustat` bounce to `applyweb.collegenet.com/account/...`, where credentials are typed.
- The cited support article returns 403 to every client tried, so its contents are unread.

**liaison-gradcas** (YES, changed hosts)
- `gradcas.liaisoncas.org` is the information site. The application is `gradcas2027.cas.myliaison.com/applicant/login`, linked from the official page. `gradcas2026` also answers.
- Hosts are now `gradcas.liaisoncas.org *.cas.myliaison.com`. The cycle year is in the hostname, so a fixed host would go stale every year.
- Wildcard DNS (see finding 1).

**jotform** (NO, no change)
- A generic form builder. The bare host `form.jotform.com` redirects to `www.jotform.com`. Forms also live on other JotForm hosts (EU, custom subdomains).

**tchooz** (YES, no change)
- `tfmasa.tchooz.app/tfmasa-2026-1` loaded. It references emundus.fr, so Tchooz is the eMundus SaaS.
- Wildcard DNS.

**formdesk** (NO, changed hosts)
- `www.formdesk.com` redirects to `formdesk.com`, so `formdesk.com` was added. `formdesk.nl` also redirects to `formdesk.com/nl/`.
- The vendor offers a free 90-day trial, so anyone can publish a form.

**tribal-sits-evision** (PARTIAL, no change)
- City's page says e:Vision is the SITS web front end "used by staff, students and applicants".
- I sampled 12 UK universities: `evision.<x>.ac.uk` exists for City, York, LSE and UCL, and is absent for KCL, Nottingham, QMUL, Bath, Southampton, Leeds, Sheffield and Bristol. The pattern covers a minority of tenants. Mostly it is a student-records tool.

**ellucian-crm-recruit** (YES, no change)
- The `aacc.elluciancrmrecruit.com/Apply/Account/Login` page loaded. The vendor domain does not have wildcard DNS.

**mobility-online** (PARTIAL, no change)
- The login pages load (`www.service4mobility.com/europe/LoginServlet`, `mo.service4mobility.com/LoginServlet` "MOBILITY-ONLINE login").
- It is an exchange-mobility tool, so `purpose=DEGREE` is doubtful. One host serves many institutions, so bind by the institution parameter, not the host.

**campusonline** (PARTIAL, hosts expanded)
- A single host cannot stand for a per-university vendor. I loaded four tenants: `online.uni-graz.at`, `online.tugraz.at`, `campus.tum.de` and `online.uni-salzburg.at`.
- Recognise tenants by the path `/<inst>_online/ee/ui/ca2/` or `/tumonline/ee/ui/ca2/`, never by the hostname shape. Hostnames vary.

**esse3-cineca** (YES, no change; this row had been snippet-only)
- The univr.it page (body loaded) links to `https://univr.esse3.cineca.it/Home.do`.
- `unime.`, `uniroma1.` and `unimi.esse3.cineca.it` resolve. The domain does not have wildcard DNS.
- Some universities use their own domain (`www.esse3.unimore.it`). Add those per tenant.

**osiris** (PARTIAL, no change)
- `uvt.osiris-student.nl` is "Osiris Student Mobile", a student-records app. Dutch applications go through Studielink, so this is not an application system.
- Wildcard DNS on `*.osiris-student.nl`.

**ecandidat** (PARTIAL, replaced the wildcard with five loaded tenants; this row had been snippet-only)
- The ESUP wiki page loaded: eCandidat "accompagne le candidat depuis la création de son dossier".
- eCandidat is self-hosted by each university on its own domain. There is no vendor domain.
- Loaded tenants: `ecandidat.univ-lyon1.fr`, `ecandidat.parisnanterre.fr`, `ecandidat.univ-tours.fr`, `ecandidat.unistra.fr` and `ecandidat.univ-grenoble-alpes.fr`.

**fsweb-soknadsweb** (YES, no change)
- `fsweb.no/soknadsweb/login.jsf?inst=ntnu` loaded ("Søknadsweb, Norwegian University of Science and Technology").
- UiO links "Login - Søknadsweb (fsweb.no)".
- Beware `fs-demo.uio.no` (finding 4).

## Suggested missing systems (not added to the CSV)

1. **Azerbaijan State Program for study abroad, 2022–2028** (SCHOLARSHIP, NATIONAL, AZ).
   - Arguably the single most relevant funding route for Azerbaijani master's students: about 500 places a year, 375 of them master's in 2024-25.
   - Applicants file through the "Elektron Ərizə Sistemi" and a personal cabinet on the State Program Management Group site.
   - Funding comes only after admission abroad, so it follows the degree application rather than running in parallel.
   - Host to verify: `dp.edu.az` (loaded, 200). The e-application host itself was not identified.
   - Sources: https://dp.edu.az/az/faq and https://edu.gov.az/az/2022-2026-ci-iller-uzre-dovlet-proqrami/2022-2026-ci-iller-uzre-dovlet-proqrami2483
2. **Russian Government quota — Education in Russia** (SCHOLARSHIP, NATIONAL, RU).
   - `education-in-russia.com` (loaded, title "Official website for the selection of foreign citizens …").
   - A university page states "up to six universities" and a 15 December 2026 deadline for CIS countries. That is a university page, not the operator's, so the limit is unconfirmed.
   - A sanctions or policy review comes before seeding.
   - Sources: https://education-in-russia.com/settings/static/media/Instruction(en).pdf and https://en.misis.ru/applicants/scholarships/quota
3. **Italian Government (MAECI) scholarships — Study in Italy** (SCHOLARSHIP, NATIONAL, IT).
   - Host `studyinitaly.esteri.it` loaded. Rules not verified.

## Assumptions that would change this result

- **Dropping rows.** I removed the dropped rows from the CSV rather than keeping them as NO. If the catalogue wants dead or not-an-application-system hosts kept for warnings, restore pac-ie, kira-talent and etrieve from the draft with `verified=NO`.
- **Choice of meaning for two policy values.**
  - `prep_lead_days` is read as the lead time the official page tells applicants to leave, so uni-assist is 56, not the 42 processing time.
  - `choice_limit` for Universitaly is read as "programmes per application" (1).
- **Single value for UAC.** UAC keeps the undergraduate value of 5. Postgraduate is 6.
