# Government inbound sweep — verification of the two runs, and what they missed

**Date:** 2026-09-13. **Inputs:** run A (`compass_artifact_wf-945afc4a…`, Claude-format export) and run B
("Updated Strict Parameters", Gemini-format export) of `PROMPT-government-inbound-sweep.md`.

**Method.** `gptr-mcp` `quick_search` located pages; every claim marked **FETCHED** was then read from
the official page itself (curl + text extraction, or `pdftotext` for PDFs) on 2026-09-13. Grades:

- **FETCHED** — read on the official page today; the quote is from that page.
- **OFFICIAL SNIPPET** — a search snippet from the official domain, page not opened. Good, not verified.
- **LEAD** — aggregator, social media or a third-party government page only. Not a finding.

---

## 1. Conflicts between the runs — adjudicated

| Question | Run A | Run B | Verdict |
|---|---|---|---|
| Russia: compatriot track? | One quota pool | Separate DESCENT track | **Both partly right; neither complete.** See 1.1 |
| Japan: descent master's route? | None in MEXT | Yes, MEXT Nikkei | **Exists, but it is JICA, not MEXT; run B's evidence is unrelated.** See 1.2 |
| Türkiye Bursları kin track | Yes | No, one track | **No separate track evidenced.** See 1.3 |
| DAAD EPOS for AZ/GE/AM/KZ | Not eligible | not covered | **Run A wrong; Türkiye alone is excluded.** See 1.4 |
| Germany/Canada regional tier | Exists (A) / not checked | "National only" | **Run B wrong for both.** See 1.5 |
| Stipendium Hungaricum numbers | Published | "Unpublished" | **Run A right.** FETCHED |
| Heydar Aliyev grant route | not covered | DIRECT | **NOMINATED.** See 2.1 |

### 1.1 Russia — three routes, not one or two

FETCHED, Federal Law 99-FZ art. 17 (consultant.ru, as amended 23.03.2026):

> "…соотечественникам, не являющимся гражданами Российской Федерации, предоставляется наравне с
> гражданами Российской Федерации право на доступ к образованию при условии представления ими
> документов…"

> "В случае установления квоты на прием иностранных граждан … за счет средств федерального бюджета в
> обязательном порядке учитываются интересы соотечественников независимо от их гражданства."

FETCHED, HSE St Petersburg master's admissions page, which lists the categories that compete for
budget places **"наравне с российскими абитуриентами"**:

1. **Citizens of Belarus, Kazakhstan, Kyrgyzstan, Tajikistan** — budget places "на общих основаниях"
   under the 29 March 1996 equal-rights agreement. **Not the quota.** A Kazakh citizen has a
   state-funded master's route that needs no Rossotrudnichestvo nomination. Neither run found this.
2. **Citizens of Azerbaijan, Armenia, Belarus, Kazakhstan, Kyrgyzstan, Moldova, Tajikistan,
   Turkmenistan, Uzbekistan, Ukraine with a Russian permanent residence permit (вид на жительство)** —
   same terms, 1992 Tashkent agreement. RESIDENCE-keyed.
3. **Compatriots living abroad** — general competition on equal terms with citizens, proving status by
   documents (parents' birth in USSR/RSFSR territory, etc.). DESCENT-keyed, **outside** the quota.

Plus the government quota itself (Decree 2150), where compatriots' interests must be "taken into
account" but no separate allocation is published. So run A is right that the *quota* is one pool, run B
is right that a distinct compatriot route exists, and both missed that the compatriot and CIS routes
sit **outside** the quota — which is why no quota document shows them.

### 1.2 Japan — JICA Nikkei Leaders, not MEXT

FETCHED, JICA (`jica.go.jp/english/activities/schemes/nikkei/leader.html`):

> "the program gives an opportunity of studying abroad in Japan to Japanese emigrants and their
> descendants living in Central, South America and the Caribbean. This program is open to those Nikkei
> who have been admitted to study at a graduate school in Japan… This program provides support from
> the time of application to the completion of the degree program…"

Eligibility "Be a Japanese emigrant and descendant (In principle, up to third generation Nikkei)";
allowance "2 more years to those entering a master's course". 11 participating countries, all in
Latin America/Caribbean. **A real DESCENT-keyed master's route, administered by JICA, irrelevant to
our nine markets.**

Run B's evidence does not support its own claim. FETCHED, its cited MEXT PDF
(`20250508-mxt-kotokoku01-000039329_02.pdf`) is a **MEXT Teacher Training Student** programme at
Hokkaido University of Education — non-degree, no mention of Nikkei. Its "21 students" figure is
that programme's intake. Run A's "none found in MEXT" stands for MEXT.

### 1.3 Türkiye Bursları — no separate kin track evidenced

OFFICIAL SNIPPET, `turkiyeburslari.gov.tr` criteria page: "Eligible Groups: Citizens of all countries…
Ineligible Groups: Turkish citizens and individuals who have lost Turkish citizenship". YTB's own
page lists no kin sub-programme. The only source asserting a "soydaş/akraba topluluklar kontenjanı" is
a blog (`rehberpanda.com`) — not evidence. Run A inferred the track from YTB's agency name; run B's
cited page (FETCHED) is a marketing article that says nothing either way. **Record as one general
track; an unpublished internal preference for Turkic states cannot be excluded.**

Also: OFFICIAL SNIPPET, `ytb.gov.tr`: master's stipend **5,000 TL/month** (bachelor 3,500, doctorate
6,500). Run B's "6,500 TL master's stipend" is the doctoral figure.

### 1.4 DAAD EPOS — the key is RESIDENCE, and Türkiye is out

FETCHED, DAAD database entry 50076777 (2027/2028 course list). Selectable countries include
**Armenia, Azerbaijan, Georgia, Kazakhstan, India, Indonesia, Pakistan, Vietnam, Uzbekistan**.
**Türkiye is not listed.** And:

> "„Country" is the country in which you are living and from which you are applying."

So EPOS is keyed to **residence**, not citizenship. Run A's claim that AZ/GE/AM/KZ are excluded is
wrong; its Türkiye exclusion is right.

### 1.5 Regional tier — run B's "national scheme only" is wrong twice

- **Canada:** Québec runs PBEEE. OFFICIAL SNIPPET, `frq.gouv.qc.ca`: "Bourses d'excellence pour
  étudiantes étrangères et étudiants étrangers (PBEEE) 2027-2028" page exists; the 2026-27 rules PDF
  sets a 2 Dec 2025 deadline with university pre-selection (→ NOMINATED). Research-master's value
  $20,000/yr per a Laval-linked LEAD.
- **Germany:** run A's BAYHOST and Baden-Württemberg findings, and the prompt's own BAYHOST citation,
  contradict run B.
- **Belgium:** FETCHED, `studyinflanders.be`: "The Flemish Ministry of Education and Training awards
  scholarships for master's programmes… grant of €10.225 and a tuition fee waiver per academic year";
  reserved places Japan (3), Mexico (3), Palestine (2), USA (5); "Each Flemish higher education
  institution can submit a maximum of 20 applications." Regional tier confirmed. (VLIR-UOS ICP
  Connect: FETCHED, nationality **and** residence in one of 29 countries; covers tuition, travel,
  insurance, living; 2027–28 call opens mid-November 2026. Its funder is not stated on the page —
  run B's "Flemish regional" label is unverified.)

---

## 2. Other claims checked

### 2.1 Launch-market-relevant

- **Heydar Aliyev International Education Grant (Azerbaijan, inbound).** FETCHED,
  `studyinazerbaijan.edu.az/financial-support`: MFA + Ministry of Science and Education; "100
  educational grants will be provided annually"; "offered annually for a period of 5 years, starting
  from the 2026–2027 academic year"; eligible: OIC members, NAM members, SIDS, "Countries sharing
  common cultural, ethnic and historical ties with Azerbaijan"; levels include Master's; covers
  tuition, international flights, monthly allowance, medical insurance, visa & registration.
  **Türkiye qualifies as an OIC member.**
  - **Route is NOMINATED, not DIRECT (run B wrong).** LEAD + third-government pages: two stages,
    "nomination by the applicant's national authorities, followed by registration on the SIACAS
    platform"; Pakistan's HEC ran its own portal to 20 Mar 2026 and publishes **3 slots for Pakistan**
    (`hec.gov.pk/site/AZS`, OFFICIAL SNIPPET) — a sending-side quota, as the origin-side synthesis
    predicts.
  - **Start-year conflict:** the official page says 5 years from 2026–27; SESRIC (an OIC body)
    announced a 2025–26 round (deadline 15 May 2025); run B cites an MFA page saying 2024–25. Give
    both; the programme has run since at least 2025–26.
- **Czech Government Scholarships – Developing Countries.** OFFICIAL SNIPPET, `msmt.gov.cz` (the
  direct fetch was blocked): 2027/2028 offered "only to the citizens of" Bosnia and Herzegovina,
  **Georgia**, Ukraine, Belarus (democratic forces), Ethiopia, Gabon, Mauritania, Zambia, Bangladesh,
  Cambodia, Palestine, Guatemala, Honduras. **Azerbaijan and Armenia are not eligible.** Application
  window **21 August – 30 September 2026** — open now for Georgians. Basis: Government Resolution
  No. 870 of 27 Nov 2024. The Czech-taught follow-up master's track is for BiH, Georgia, Ukraine and
  Belarus; the English-taught one is for all eligible countries (2026/27 wording).
- **Kazakhstan "Study in Kazakhstan".** FETCHED, `bolashak.gov.kz` (31/07/2024): "for foreign citizens
  and individuals of Kazakh nationality who are not citizens of Kazakhstan… 550 scholarship places…
  in 2024… 11,293 applications were received from 83 countries… 490 bachelor's, **50 master's**, 10
  doctoral." Both halves published (2024) — but for the whole scheme, not per level. The descent
  group is an eligibility class; no separate quota for it is published. Run B's "Post-secondary
  grants" understated the master's confirmation that was on its own source.
- **SISGP (Sweden).** FETCHED, `si.se`: 34 countries incl. Armenia, Azerbaijan, Georgia, Indonesia,
  Uzbekistan, Vietnam — **not** Türkiye, Kazakhstan, India or Pakistan. "you do not need to reside in
  the country at the time of the application." "we do not have any quotas for specific countries."
  Travel grant SEK 10,000 for Armenia/Azerbaijan/Georgia. Key is CITIZENSHIP (run B said REGION).
- **Stipendium Hungaricum.** FETCHED, 2026/27 Call PDF: "In 2025, 80,000 applications were received,
  and more than 4,500 scholarships were awarded." Deadline 15 Jan 2026; 2027/28 round opens November
  2026 (LEAD, university page). Run A right; run B's "Unpublished" wrong. The route for our markets is
  NOMINATED via the sending partner (origin-side synthesis).
- **Canada — Study in Canada Scholarships.** OFFICIAL SNIPPET, `educanada.ca`: "short-term study or
  research exchanges", "up to eight months"; eligible includes **Türkiye**. **Not a master's degree
  scholarship — run B's row should be struck.**
- **Italy MAECI 2026/27.** OFFICIAL SNIPPET, `esteri.it`: for foreign students "e Italiani Residenti
  all'Estero (IRE)"; deadline 26 March 2026. LEAD (info-cooperazione, UniPi): **9 months** (1 Nov
  2026 – 31 Jul 2027), age ≤ 28, **€10,800** plus tuition exemption. IRE is Italian **citizens**
  resident abroad — CITIZENSHIP + RESIDENCE, not DESCENT (run A mislabelled). Neither run's
  "full-cost" reading holds: it is a 9-month grant.

### 2.2 Not launch-market-relevant, confirmed

- **Ireland GOI-IES.** FETCHED, `hea.ie`: 60/yr; €10,000 stipend + full fee waiver for one year at NFQ
  9/10; "domiciliary of origin outside the EU/EEA, Switzerland and the United Kingdom" (RESIDENCE, not
  REGION); "Russian and Belarusian nationals are not eligible"; 2026 deadline 12 March 2026.
- **Swiss Government Excellence Scholarships.** FETCHED, `sbfi.admin.ch`: master's funding only as
  **art scholarships** ("first Master's degree at a Swiss art school or conservatory", limited
  countries); research scholarships require a completed master's. CHF 2,450/month.

---

## 3. Schemes neither run found

| Country | Scheme | Grade | Key facts | Our markets |
|---|---|---|---|---|
| **Russia** | CIS equal-rights budget places | FETCHED | See 1.1; outside the quota | **Kazakhstan** (citizens); AZ/AM/UZ with RF residence permit |
| **Slovakia** | Scholarship scheme for international students (state budget + ESIF) | FETCHED, `scholarships.portalvs.sk` | €5,000/yr, 2 years for a master's; **55 master's places** (35 outside Bratislava, 20 in it); ranked by SAT/SCIO within 5 regional groups; Slovaks living abroad also eligible; 2026/27 deadline extended to 8 Sep 2026. Partial, not full-cost | All nationalities |
| **Slovakia** | Government scholarships (development cooperation) | OFFICIAL SNIPPET, `minedu.sk` | ODA-country list (xls); includes a **Slovaks Living Abroad** DESCENT track; 2026/27 deadline 25 May 2026 | Check the xls |
| **Lithuania** | State scholarships for full-time master's | OFFICIAL SNIPPET, `studyin.lt` | 2026: citizens of **Armenia, Azerbaijan, Georgia, Kazakhstan, Uzbekistan, Indonesia, Vietnam**, China, Israel, Japan, Moldova, NZ, Philippines, S. Korea, Ukraine, USA, **and foreign citizens of Lithuanian origin** (DESCENT); **70 grants** with per-country quotas; €592/month (FETCHED, VU page) + tuition grant; deadline 20 Apr 2026 | **AZ, GE, AM, KZ** |
| **Qatar** | Qatar Scholarships (Qatar Fund for Development) | FETCHED, `qatarscholarships.qa` | State development fund; "hundreds of scholarships annually"; developing-country students; master's at Doha Institute, HBKU. Per-nationality eligibility sits behind a questionnaire — not established | Unverified |
| **Pakistan** | Allama Muhammad Iqbal Scholarship for Central Asia & Friendly Countries (HEC) | FETCHED, `hec.gov.pk` | "350 fully funded scholarships for students from central Asian and friendly countries to pursue undergraduate and graduate studies". No master's split, cycle or country list on the page | **Central Asia** |
| **Brunei** | BDGS for foreign students | LEAD (+ HEC Pakistan page) | Diploma/UG/master's; master's age ≤ 35; all nationalities; 2026/27 closed 15 Feb 2026 | All |
| **Malaysia** | MIS (MOHE); MTCP (MFA) | FETCHED `biasiswa.mohe.gov.my` (MIS 2026/27 closed; interview shortlist July 2026; MTCP text dated 2023) | MIS master's/PhD; eligible list incl. **Azerbaijan, Georgia, Kazakhstan, Türkiye, Uzbekistan** per LEAD only | **All five, unverified** |
| **Indonesia** | KNB | OFFICIAL SNIPPET `knb.kemdiktisaintek.go.id` + LEAD | Developing countries; LEAD: 162 master's places, deadline 31 Mar | Unverified |
| **Romania** | MFA scholarships for non-EU citizens | OFFICIAL SNIPPET `mae.ro` (fetch blocked) + LEAD | UG/master's/PhD, Romanian-taught; excludes "citizens of Romanian origin" (separate descent route) | All non-EU |
| **Serbia** | "The World in Serbia" | OFFICIAL SNIPPET `mfa.gov.rs` | Since 2010, "100 scholarships for students from the Member States of the Non-Aligned Movement"; nominated by governments (St Kitts 2025: 2 candidates); latest evidence is the 2025 round | **Azerbaijan** (NAM member); not Türkiye |
| **Austria** | Scholarship Foundation of the Republic of Austria — master's in International Relations | FETCHED, `oead.at` | "intended for descendants of forced labourers under the NS regime and nationals of countries that suffered particularly from the NS regime"; 9 months; closes 1 April. DESCENT + historical key. Otherwise Austria has **no full-master's government scholarship** on OeAD's list (Ernst Mach = short stays or full PhD) | Unlikely |
| **Hungary** | Hungarian Diaspora Scholarship | OFFICIAL SNIPPET `diasporascholarship.hu` + LEAD | BA/MA for Hungarian diaspora outside the EU, Serbia and Transcarpathia; 2026/27 closed | Descent only |
| **Denmark** | Danish Government Scholarships (state tuition waivers via universities) | LEAD | Non-EU/EEA master's; university-selected; full or partial waiver + grant | All, unverified |
| **Georgia** | MES state study grant for foreign citizens | LEAD (AI-generated social post) | Partial tuition up to GEL 2,250; window 1 Sep – 2 Oct 2026 | Verify before use |
| **Croatia** | Bilateral scholarships | OFFICIAL SNIPPET `mzom.gov.hr` | Nominated by partner-country authorities; mostly mobility | Bilateral only |
| **Israel** | MFA scholarships | OFFICIAL SNIPPET `gov.il` | **8-month non-degree**; lists include Azerbaijan, Georgia, Türkiye, India | Not a master's |
| **New Zealand** | Manaaki | LEAD (Massey, ENZ) | Pacific + ASEAN only (Indonesia, Vietnam); 2027 intake 1 Mar – 10 Apr 2027 | Not AZ/TR |
| **Latvia** | Scholarships to foreigners (Cabinet Reg. 68) | OFFICIAL SNIPPET `studyinlatvia.lv` | €500/month up to 10 months — mobility, not a degree | — |

**Descent/residence-keyed tracks now evidenced** (the catalog cannot represent any of them): Russia
compatriots (outside quota) and CIS residence-permit holders; JICA Nikkei; GKS Overseas Korean
(repo file); Kazakhstan ethnic Kazakhs; Lithuania Lithuanian origin; Slovakia Slovaks Living Abroad
(×2); Poland gen. Anders (run B); Hungary diaspora; Austria forced-labourer descendants; Italy IRE
(citizenship + residence); DAAD EPOS (residence, not citizenship); Ireland GOI-IES (domicile).

---

## 4. Still unresolved

- **Superseded:** the next line came from multi-country queries and was wrong for Singapore, Hong Kong,
  Luxembourg, Denmark, Cyprus and Portugal — see the synthesis §7 for one-search-per-country results.
- **No evidence found** (not confirmed absence): Hong Kong, Singapore, Iceland, Cyprus, Luxembourg,
  Malta, Finland, Portugal, Northern Ireland, UAE, Kuwait, Bahrain, Vietnam, Uzbekistan, Armenia;
  Bulgaria (Decree 228 descent scheme, LEAD only); Greece (IKY, LEAD only).
- **Not re-checked here:** Chevening 1,400 (FCDO CP 981, run A); GKS quotas (already verified in
  `2026-08-29-gks-quota-primary-verification.md`); Polish Banach group for Azerbaijan; Eiffel;
  Fulbright; Australia Awards list; China CSC 2026/27 (OFFICIAL SNIPPET only: embassy deadline
  8 Feb 2026, master's age < 35, Silk Road Type B deadlines ~15 May 2026 at universities).
- **Launch-market implications to carry into the synthesis:**
  - Azerbaijani citizens gain Lithuania (quota), EPOS (restored — keyed on residence), Serbia (NAM,
    nominated), and probably MIS; Czech is closed to them.
  - Turkish citizens gain Heydar Aliyev (nominated) and probable MIS; they are **out** of EPOS,
    SISGP, Lithuania, Czech, Australia Awards and Manaaki.
  - Kazakh citizens gain the Russian budget-place route with no nomination, and Pakistan's HEC
    Central Asia scheme.
