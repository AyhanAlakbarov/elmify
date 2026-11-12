# Application systems seed: owner review (2026-10-09, second pass)

Input: `2026-10-09-application-systems-verified.csv` (38 rows) and `2026-10-09-application-systems-verification.md`.
Output: `2026-10-09-application-systems-final.csv`, 38 rows in the spec §3.4 schema (`verified` column removed).

Count: 38 input rows, minus 3 dropped (jotform, formdesk, mobility-online), plus 3 new (az-state-programme, education-in-russia, study-in-italy-maeci). 6 kept rows changed: uac-au, vtac-au, chevening, tribal-sits-evision, campusonline, ecandidat.

Rules checked against: verified-catalogue spec §3.4 (commit d924fa0a, `docs/superpowers/specs/2026-09-27-verified-catalog-one-reader-design.md`).

## Method

- I fetched every `source_url` again (curl; Scrapling stealth or Tavily extract where curl was blocked). For each listed host I checked that it is linked from that page, is the page's own host, or is reached by a redirect from an official page.
- I ran `openssl s_client` against every exact host, with normal certificate verification. Results are in "TLS" below.
- I followed the login and sign-in links on each applicant host to find login hosts the first pass missed. This found three: `login.vtac.edu.au`, `asams.chevening.org` and `id.dreamapply.com`.
- I re-read every non-empty policy value against the text of the source page, quoted below where I re-confirmed it.
- Limits:
  - RDAP and whois did not answer from this sandbox. Vendor ownership of the wildcard domains therefore rests on the tenant pages naming the vendor, not on registrant records.
  - `www.campuschina.org` failed DNS once during the sweep. A stealth fetch loaded it, and `www.csc.edu.cn/laihua` redirected to it in that same session.

## Cross-cutting findings

1. **Wildcard rule.**
   - `evision.*.ac.uk` puts the wildcard on the label that sits directly under a public suffix (`ac.uk`). §3.4 forbids that, so it is removed.
   - The remaining wildcards each stand for the leftmost label under a vendor's registrable domain, which the rule allows: `*.dreamapply.com`, `*.cas.myliaison.com`, `*.tchooz.app`, `*.elluciancrmrecruit.com`, `*.esse3.cineca.it` and `*.osiris-student.nl`.
   - Vendor evidence:
     - the Tchooz tenant page references eMundus, and tchooz.io says Tchooz "s'appuie sur … notre agence eMundus";
     - the Osiris tenant page links `caci-nl.atlassian.net`, and CACI's site describes OSIRIS;
     - the Ellucian tenant page loads `Ellucian.Recruit` resources.
2. **The Slate rule applies to more than Slate.** §3.4 says a system "whose tenants live on the university's own domain … has empty `hosts`" and is recognised through the proven-site branch.
   - Three more rows fit that rule: CAMPUSonline (`online.tugraz.at`, `campus.tum.de` …), eCandidat (`ecandidat.unistra.fr` …) and e:Vision (`evision.city.ac.uk`).
   - Their hosts are now empty. The tenants loaded so far are listed per row below, as recognition examples only.
3. **Open publishing hosts.** JotForm and Formdesk let anyone publish a form. The schema has no column marking a host as open publishing. If they stay in the table, the only thing keeping them from host-level trust is the generic SHARED rule (exact tenant path linked from the proven page), and nothing in the row records why these two need it more than others. Dropped. See "Owner decisions" 1.
4. **No remaining row trusts a host where anyone can publish.** Every remaining host is one of three kinds:
   - government-run;
   - run by an admissions body;
   - a vendor host whose tenants are sold to institutions. DreamApply is sold by sales contact: "Pricing is determined by the number of applications", "A dedicated Configuration Manager will guide your team" (https://dreamapply.com/, Tavily). Tchooz, Liaison, Ellucian, Cineca and CACI are institutional products.
5. **Login hosts the first pass missed.**
   - `vtacapplicantsportal.vtac.edu.au/signin` redirects to `login.vtac.edu.au/…/b2c_1a_signup_signin/…`. Added.
   - Chevening's "Apply today" goes to `asams.chevening.org/apply`. Added.
   - The "Sign in / register" link on the DreamApply custom-domain tenants (`apply.stipendiumhungaricum.hu`, `apply-scholarships.si.se`) redirects to `https://id.dreamapply.com/login?client=634` and `?client=1298`. Not added. See "Owner decisions" 3.
6. **TLS (never relaxed).** Two hosts serve only their leaf certificate, so strict clients fail with `Verify return code: 21 (unable to verify the first certificate)`:
   - `pastel.diplomatie.gouv.fr`, already known;
   - **new:** `auth.education-in-russia.com`, a GlobalSign GCC R46 DV leaf with no intermediate. The apex `education-in-russia.com` serves the full chain and verifies.

   Every other exact host verified (code 0).

## The three new rows

### az-state-programme: Azerbaijan State Programme for study abroad 2022-2028

`NATIONAL, SCHOLARSHIP, SHARED, hosts=portal.edu.az dp.edu.az, AZ`. Policy fields are empty.

**What it is**
- The State Programme pays study costs abroad only for applicants already admitted to a programme on the Ministry's list. It does not admit anyone.
  - FAQ: "Yalnız xarici ali təhsil müəssisələrinə qəbul olunmuş və yaxud artıq orada təhsil alan tələbələr təhsil xərclərinin qarşılanması məqsədilə … müraciət edə bilərlər" (https://dp.edu.az/az/faq).
  - So `SCHOLARSHIP` is right. In a route it follows the degree admission.
- dp.edu.az belongs to the State Programme Management Group (DPİQ), set up under the Ministry: "İdarəetmə Qrupu … Azərbaycan Respublikası Təhsil Nazirliyinin nəzdində yaradılır" (https://dp.edu.az/az/content/79).

**Hosts**
- The 2026-27 call says applications go through the Ministry of Science and Education's personal-cabinet portal:
  - "Müraciət Azərbaycan Respublikası Elm və Təhsil Nazirliyi Şəxsi Kabinet Portalı vasitəsi ilə həyata keçirilir";
  - "sənədlərin skan edilmiş surətlərini portal.edu.az veb-səhifə üzərindən əlavə edib, ərizəni təsdiq etməlidir".
  - Deadline "05.06.2026, saat 18:00". Source: https://dp.edu.az/uploads/fileuploads/2026/04/0428d7b03166464f9078f404643eeeb9.pdf, linked from the dp.edu.az menu.
- dp.edu.az's menu item "ELEKTRON XİDMƏTLƏR → Proqrama müraciət" links `https://portal.edu.az/services`.
- https://dp.edu.az/az/content/48 says: "sənəd qəbulu portal.edu.az üzərindən həyata keçirilir".
- Login runs on portal.edu.az itself: its page title is "Azərbaycan Respublikası Elm və Təhsil Nazirliyi Şəxsi Kabinet Portalı", and the bundle calls the relative paths `/api/auth` and `/api/sso/checkToken`. No other login host was found.

**Official, not a look-alike**
- The Ministry's own page links both hosts: https://edu.gov.az/az/2022-2026-ci-iller-uzre-dovlet-proqrami/2022-2026-ci-iller-uzre-dovlet-proqrami2483 links `https://dp.edu.az/` and `https://portal.edu.az/`.
- The edu.gov.az homepage links `https://portal.edu.az/services`.
- Both certificates verify (Let's Encrypt `*.dp.edu.az` and `*.portal.edu.az`).

**Policy fields left empty**
- No official page states a choice limit, ranking or fee. The applicant already holds one admission.
- The call states two stages, documents then an interview ("Namizədlərin seçimi iki mərhələdən ibarətdir"). There is no column for that.

### education-in-russia: Russian Government quota (Education in Russia)

`NATIONAL, SCHOLARSHIP, SHARED, hosts=education-in-russia.com auth.education-in-russia.com, RU, choice_limit=6, ranked=true`.

**Official, not a look-alike**
- Rossotrudnichestvo's own page names it as the first step: "register in the information system [education-in-russia.com](https://education-in-russia.com/)". The same page gives the quota hotline (https://rs.gov.ru/en/service/obrazovanie-v-rossii, Scrapling stealth; the page is rendered by JavaScript).
- The site's title is "Official website for the selection of foreign citizens to study in Russia". It loads the gosuslugi.ru government widget.
- Because the domain is a `.com`, the rs.gov.ru link is the proof, not the name.

**Hosts**
- The operator's own instruction PDF says registration and login are on `https://education-in-russia.com/`.
- The site's JavaScript sends profile and login to `avanpost:"https://auth.education-in-russia.com"`, including `https://auth.education-in-russia.com/lk/`, so the applicant sees that host. That host's certificate chain is incomplete (TLS finding above). Record it as such; do not relax verification.

**Rules**
- From https://education-in-russia.com/settings/static/media/Instruction(en).pdf:
  - "select 1 to 6 universities";
  - "Select 1 to 6 universities in which you'd like to study";
  - "only the preferential order of universities can be changed" once submitted, so the list is ranked;
  - "you will only be allowed to submit one application for tuition-free study".
- The PDF metadata says it was created on 2021-10-29. The live site still serves it. Re-check the values when the 2027 campaign page is published.

**Purpose**
- The application selects candidates for the quota and also asks whether the candidate will "accept a tuition-paying placement" if no quota place is given. Its main job is the quota, so `SCHOLARSHIP`.

**Owner note:** the first pass flagged a sanctions and policy check before seeding. You approved the row. The check is still not recorded anywhere in the repo.

### study-in-italy-maeci: Study in Italy (MAECI Italian Government scholarships)

`NATIONAL, SCHOLARSHIP, SHARED, hosts=studyinitaly.esteri.it iam.esteri.it, IT, choice_limit=3`.

**Official, not a look-alike**
- `studyinitaly.esteri.it` is under the Foreign Ministry's own domain. Its certificate subject is `O = Ministero degli Affari Esteri e Cooperazione Internazionale, CN = esteri.it`.
- `https://www.esteri.it/it/` links `https://studyinitaly.esteri.it/`.
- The portal's contact block reads: "Ministry of Foreign Affairs and International Cooperation, Directorate General for Growth and Export Promotion – Office VII".

**Hosts**
- `/Auth/Login` shows only an "Accedi" button to `/signin-oidc/login`, which redirects with a 302 to `https://iam.esteri.it/login/oauth2/authorize?client_id=study-in-italy-fo&…`. The applicant types credentials on `iam.esteri.it`. Both hosts verify.

**Rules** (https://studyinitaly.esteri.it/Static/FAQ)
- "You can indicate a maximum of three Course options, even in different Institutions or Universities … the three Course options must all be of the same type". So `choice_limit=3`.
- No ranking is stated, so `ranked` is empty.
- "No, there are no costs associated with submitting the Application. Participation is free." `one_fee_per_round` is left empty, following the Universitaly precedent for a free portal.
- "You can submit your application exclusively through the Study in Italy website."
- Applying for the grant and enrolling at the university are "two separate and different procedures". So this is a scholarship step alongside Universitaly and the university's own application.
- At review time the call was closed: "The call for applications for MAECI grants for the 2025-2026 academic year is now closed" (https://studyinitaly.esteri.it/ListaBandi). The FAQ already cites the 2026-2027 call.

## Per-row review of the 38 input rows

Status key: **keep** = unchanged and seeded; **changed** = seeded with the change shown; **dropped** = not in the final CSV.

### NATIONAL, DEGREE

| slug | status | evidence and notes |
|---|---|---|
| universityadmissions-se | keep | Source: "You can select up to four master's programmes … increases from four to five". Both hosts are linked from it. |
| studyinfo-fi | keep | Source (stealth-rendered): "apply to up to six (6) study programmes with one application form". Spring English round: "you do not have to place the study programmes in order of preference". Autumn: "you must place … in order of preference". Empty `ranked` is right. `studyinfo.fi` returns 302 to `opintopolku.fi`. |
| studielink-nl | keep | PDF: "You may submit up to four enrolment applications per academic year". `www.studielink.nl` loads; its JS calls no separate login host. DigiD is used for Dutch residents only and is not listed. |
| uni-assist-de | keep | Source: "Apply as early as possible, at least 8 weeks before the deadline" (56). Both hosts are linked. |
| hochschulstart-de | keep | Source: "bis zu 12 verschiedene „Studienangebote"". `dosv.hochschulstart.de/bewerber` currently redirects with a 302 to `wartung-bw.hochschulstart.de`: a planned maintenance window, "04.10.2026, 12:00 Uhr - 19.10.2026, 09:00 Uhr". The maintenance host is not added. |
| monmaster-fr | keep | Source (Tavily; curl gets 403): "jusqu'à 15 vœux dans des formations hors alternance et 15 vœux dans des formations en alternance". `monmaster.gouv.fr` loads. It is a single-page app, so its login host was not confirmed. |
| etudes-en-france | keep (was PARTIAL) | 7 is now confirmed by a second Campus France office. Morocco: "Vous avez la possibilité d'effectuer 7 choix maximum sur la plateforme Études en France" (https://www.maroc.campusfrance.org/3le-panier-de-formations-et-les-motivations). Mali: "7 choix pour les formations au-delà de la première année (L2, L3, Master, DUT)". Fee: Azerbaijan office, "250 AZN olan qeydiyyat ödənişi" per dossier; the amount varies by country. Pastel's TLS chain is still incomplete (code 21). Safe to seed. |
| universitaly-it | keep | Circular: "indicare uno solo dei corsi di studio". Both hosts are linked or self. |
| optagelse-dk | keep | Source: "You can apply for up to 8 programmes … list of priorities". Bachelor's only. |
| samordna-opptak-no | keep | Source: "En person/søker kan søke ti studier i prioritert rekkefølge". |
| ucas-undergraduate | keep | Source: "add up to five choices"; "£34.50 for up to five choices". `accounts.ucas.com` redirects to `/Account/Login`. Undergraduate only. |
| cao-ie | keep | Source: "10 course choices on the Level 8 course list and 10 on the Level 7/6 course list"; "genuine order of preference". `www2.cao.ie` appears on apply.php only for the privacy statement, so it is not added. |
| ouac-ca | keep | Source (stealth, behind Cloudflare): "Base Application Fee: $159 … Additional Choice Fees: $51 per choice", which confirms `one_fee_per_round=false`. Undergraduate only. |
| uac-au | **changed**: `choice_limit` 5 → empty | Source: "In your undergraduate application, you can select up to five course preferences. If you're an international Year 12 applicant or you're applying for postgraduate courses, you can select up to six." The field holds one number and the page gives two. For a master's applicant 5 is wrong, so the field is left empty, as `ranked` is for Studyinfo. Kept: `ranked=true` ("consider your course preferences according to the order in which you list them") and `one_fee_per_round=true` ("There is no charge to change your preferences"). Hosts are all linked. Login is Cognito, run from `apply.uac.edu.au` itself. |
| vtac-au | **changed**: added `login.vtac.edu.au` | `https://vtacapplicantsportal.vtac.edu.au/signin` follows a redirect to `https://login.vtac.edu.au/b16ff7c8-…/b2c_1a_signup_signin/oauth2/v2.0/authorize?…`, where the applicant types credentials. The certificate verifies (`CN = login.vtac.edu.au`). Rules: "select up to eight courses, which must be ranked". https://vtac.edu.au/dates lists one fee per course application ("Current year 12 students*: $83 All others: $104"). |

### NATIONAL, SCHOLARSHIP

| slug | status | evidence and notes |
|---|---|---|
| gks-korea | keep | Source: "Embassy Track applicant may choose up to THREE different universities". The same page says R-GKS (undergraduate) allows 2, and University Track applicants apply direct. 3 is right for the Embassy Track, which is the track that uses this portal. |
| csc-china | keep | `www.csc.edu.cn/laihua` → `www.campuschina.org` (stealth). That page links "Scholarship Application for Students" → `https://studyinchina.csc.edu.cn/#/login`. Curl gets 412 from the bot wall. |
| stipendium-hungaricum | keep | Source: "only 2 choices are allowed"; FAQ: "it is not possible to edit your priorities". Login is `id.dreamapply.com` (Owner decisions 3). |
| turkiye-burslari | keep | Source: applications "via the Türkiye Scholarships Application System (TBBS) between 10 January and 20 February". `tbbs.` is linked. |
| daad-portal | keep | Source: "The DAAD portal can be accessed via www.meindaad.de/en/". Login is `/?mydaad_login` on the same host. |
| si-scholarships | keep | Source (Tavily; the curl copy hides the collapsed text): "Your scholarship application can include up to four eligible master's programmes". Login is `id.dreamapply.com` (Owner decisions 3). |
| chevening | **changed**: added `asams.chevening.org` (was PARTIAL) | Each open country page's "Apply today" button links `https://asams.chevening.org/apply`. Example: https://www.chevening.org/scholarship/austria/ ("Open for applications until 20 October 2026", per https://www.chevening.org/apply/). That page loads ("Choose an award … select a country or territory where you hold citizenship") and its certificate verifies. Rules re-confirmed on the source: "three UK master's degree choices in order of preference". Safe to seed. |
| fulbright-iie | keep | Source: "please list in priority order up to four schools of your choice". Listing is optional. Only the `/ffsp2027` path on `apply.iie.org` is the application; the bare host redirects to www.iie.org. |

### VENDOR

| slug | status | evidence and notes |
|---|---|---|
| dreamapply | keep | Wildcard is under the vendor domain, so the rule allows it. Wildcard DNS: a host resolving proves nothing. Sales-led product (finding 4). `id.dreamapply.com` (DreamID login) falls under this row's wildcard. |
| slate | keep (empty hosts) | Matches §3.4 exactly. Seed with empty hosts. |
| collegenet-applyweb | keep (was PARTIAL) | The support article now loaded through Tavily: "sign up for an account with ApplyWeb, the application hosting service affiliated with the school … access an application directly by going to the school's own website and following the link". `www.applyweb.com/public/account` redirects to `applyweb.collegenet.com/account/bounce?…`. The bare `www.applyweb.com/` now redirects to the help site `applyweb.collegenet.support`, which is not added. Tenants are paths, and only institutions are tenants. Safe to seed. |
| liaison-gradcas | keep | Source links `gradcas2026.` and `gradcas2027.cas.myliaison.com`. Wildcard under the vendor domain is allowed; DNS wildcard noted. |
| tchooz | keep | `tfmasa.tchooz.app` loads (an EMJM tenant). Vendor link to eMundus (finding 1). Connections to `tchooz.app` and `www.tchooz.app` were reset during this pass, so the apex was not loaded. |
| ellucian-crm-recruit | keep | Tenant login page loads. No wildcard DNS. |
| esse3-cineca | keep | univr.it links `univr.esse3.cineca.it`. Universities that host Esse3 on their own domain are recognised by the proven-site branch. |
| osiris | keep (PARTIAL stays) | `purpose=DEGREE` is supported by an official university page. Radboud: the application "consists of two steps: first, submitting an enrolment application in Studielink, then uploading documents in OSIRIS Application" (https://www.ru.nl/en/education/application-and-admission/application-procedure-masters/masters-international-previous-education). Known OSIRIS Application tenants are on university domains (`osiris.tue.nl/osiris_aanmeld_tueprd/…`, loaded), so the proven-site branch covers them. The vendor-hosted `*.osiris-student.nl` (`uvt.` = "Osiris Student Mobile") is mostly student records; any page behind its login is `login_wall` anyway. Seeded unchanged. |
| tribal-sits-evision | **changed**: hosts `evision.*.ac.uk` → empty | The wildcard stands for the label under the public suffix `ac.uk`, which §3.4 forbids. e:Vision tenants live on each university's own domain (`evision.city.ac.uk`; the first pass sampled York, LSE and UCL), so the Slate rule applies. Purpose: City's page says it is "used by staff, students and applicants". Seed with empty hosts. |
| campusonline | **changed**: four tenant hosts → empty | All four loaded tenants are on the university's own registrable domain (`online.tugraz.at`, `online.uni-graz.at`, `online.uni-salzburg.at`, `campus.tum.de`), so §3.4's own-domain rule applies. A sample of four can never be complete. Recognition hint for later: path `/<inst>_online/ee/ui/ca2/` or `/tumonline/ee/ui/ca2/`. Seed with empty hosts. |
| ecandidat | **changed**: five tenant hosts → empty | eCandidat is self-hosted by each university on its own domain (`ecandidat.unistra.fr` and others; all five load and verify), so the same rule applies. Seed with empty hosts. |
| fsweb-soknadsweb | keep | `fsweb.no/soknadsweb/login.jsf?inst=ntnu` loads. Tenants are institutions in Norway's FS student-records system (Sikt); nobody else can publish there. The tenant is the `inst=` query parameter, so the exact URL linked from the proven page must be matched with its query string. Beware `fs-demo.uio.no`. |
| jotform | **dropped** | Anyone can publish a form; finding 3. |
| formdesk | **dropped** | Same reason. The vendor offers a free 90-day trial. |
| mobility-online | **dropped** | Every page loaded (`www.service4mobility.com/europe/LoginServlet`, `mo.service4mobility.com/LoginServlet` "MOBILITY-ONLINE login", `mobility.univie.ac.at` "Studierendenmobilität") is about exchange mobility. No official page shows it used for degree admission, and the purpose values are only DEGREE or SCHOLARSHIP. Seeding it would let an exchange deadline page be read as a degree-route `APPLICATION` source. That is a wrong-date risk, not only a labelling problem. Many installs are also self-hosted on university domains. Re-add only when a proven programme page shows it as the degree application. |

Country codes: every NATIONAL row's code matches the country whose body runs the system. VENDOR rows correctly have none.

Purpose: every DEGREE and SCHOLARSHIP value matches what the operating body says the system does. mobility-online was dropped as the one exception.

## Owner decisions still open

1. **JotForm and Formdesk.** Spec §3.4 mentions them ("never served unless the proven page links that exact form"), which suggests you expected them in the table. I dropped them because no column marks them as open publishing. If you want them seeded, add an `open_publishing` boolean, or a `host_scope` value such as `OPEN`, so code enforces the exact-form rule for those rows, with a test pinning it. Until then, a JotForm link on a proven page still becomes a `portal_url` with `portal_system` NULL, and nothing is lost except the label.
2. **Empty-hosts rows.** Slate, e:Vision, CAMPUSonline and eCandidat are now label-only rows. Code cannot attribute a `portal_url` to them from the host. Decide whether these rows should carry a path pattern, for example CAMPUSonline's `/ee/ui/ca2/`, or stay label-only.
3. **Shared identity-provider hosts.** `id.dreamapply.com` is the login for the SH and SI tenants. `iam.esteri.it` and `portal.edu.az` are ministry-wide login portals that serve other services too.
   - I listed `iam.esteri.it` and `portal.edu.az`, which each appear in one row only.
   - I left `id.dreamapply.com` under the DreamApply wildcard and did not list it on SH and SI, which would have put one host in three rows.
   - National eID providers (ID-porten, MitID, DigiD, suomi.fi, e-Devlet) are not listed anywhere. They serve residents, not this platform's applicants.
   - If host→system lookup must be one-to-one, this is the rule to confirm.
4. **`country_code` meaning for outbound programmes.** For every other row the country is also the study destination. For `az-state-programme` it is the funder's country (AZ), while study is abroad. Any code that reads `country_code` as "destination" will mis-route this row. Confirm the column means "country of the operating body".
5. **UAC's two limits.** Undergraduate 5, postgraduate 6. Left empty. Split into two rows only if UAC postgraduate matters to the product.
6. **Russia.** The sanctions and policy check flagged by the first pass is still unrecorded. The instruction PDF is dated 2021; re-check 6 and ranked when the 2027 campaign opens.
7. **Chevening.** Only Austria's page was checked for the ASAMS link. The host is the same for every country, but this is one sample.

## Assumptions that would change this result

- **`one_fee_per_round` on free portals.** Left empty for a free portal (Universitaly, Study in Italy). If empty is meant to mean "unknown" only, a free portal could instead be stated as `true`.
- **The own-domain rule.** I applied it to every system whose tenants sit on the university's registrable domain, not only to Slate. If you meant it to cover Slate only, put back the CAMPUSonline and eCandidat tenant lists from the input CSV. e:Vision cannot go back as a wildcard in any case.
- **Ranking on Education in Russia.** `ranked=true` rests on "the preferential order of universities". If you read that as a display order rather than a priority, set it empty.
