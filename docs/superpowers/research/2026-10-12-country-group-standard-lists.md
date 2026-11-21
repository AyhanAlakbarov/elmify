# Country-group phrases in scholarship eligibility: who owns each list

Researched 2026-10-12. Every claim cites the list owner's own page. **[UNVERIFIED]** marks
claims taken from a search snippet or news, or not read on a primary page. Read-only; no repo edits.

Rule applied (owner): the funder's own list first; the standard list only when the funder gives none.
Example of a funder list: DAAD EPOS names "development and newly industrialised countries" and
publishes its own PDF, headed "List of developing countries 2023 according to the DAC of the OECD …
validity 2024 - 2025". That validity window has ended, which is worth flagging on its own:
https://static.daad.de/media/daad_de/pdfs_nicht_barrierefrei/in-deutschland-studieren-forschen-lehren/dac_laenderliste_epos.pdf
(linked from https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50076777)

## 1. What the repo already holds (origin/master)

`apps/funding/regions.py` (last touched f881eb54, 2026-09-19) defines `REGIONS` with 7 keys. Each key has one source URL:

| Key | Count | Source in file | Finding |
|---|---|---|---|
| EU | 27 | european-union.europa.eu/…/eu-countries_en | OK |
| EEA | 30 | efta.int/eea | OK |
| WESTERN_BALKANS | 6 incl. XK | neighbourhood-enlargement.ec.europa.eu/…/western-balkans_en | not re-checked |
| EASTERN_PARTNERSHIP | AM AZ GE MD UA | eeas.europa.eu/eeas/eastern-partnership_en | matches EEAS: the five, with Belarus suspended (§9) |
| ASEAN | 10 | asean.org/member-states/ | **STALE: missing TL** (Timor-Leste joined 26 Oct 2025, §10) |
| AFRICAN_UNION | 55 incl. EH | au.int/…/countryprofiles2 | not re-checked |
| COMMONWEALTH | 56 | thecommonwealth.org/our-member-countries | **WRONG: has SS (South Sudan, not a member), lacks TG (Togo)** (§7) |

`docs/research/region-names.csv` holds 28 alias rows (en/az/tr/ru/fr/de) for those keys only.
REGIONS is used by `eligibility.py:114`, `deadline_conditions.py:90,132`, `cycle_evidence.py:213` and
`research/candidates/__init__.py:102`. Any group phrase not in REGIONS resolves to UNDECIDABLE
(see regions.py docstring). None of LDC, DAC, World Bank income, M49, CIS, OIC, OTS or Erasmus+ regions exist yet.

## 2. Least developed countries (LDCs)

- Owner: UN Committee for Development Policy (CDP) / UN DESA. https://policy.desa.un.org/least-developed-countries
  states "There are currently 44 countries on the list of LDCs which is reviewed every three years by the CDP".
- List page: https://policy.desa.un.org/themes/least-developed-countries-category/list-of-ldcs-and-country-fact-sheets
  has a "List of all LDCs in PDF format (updated December 2024)". Graduated: Bhutan, Botswana, Cabo Verde,
  Equatorial Guinea, Maldives, Samoa, Sao Tome and Principe, Vanuatu.
- Machine-readable: the UN M49 table carries an LDC column (§5). I counted 44 flagged rows on 2026-10-12, matching the 44 above:
  https://unstats.un.org/unsd/methodology/m49/overview/ . Criteria datasets (Excel) are at
  https://policy.desa.un.org/themes/least-developed-countries-category/ldc-data
- Cadence: triennial review (last 2024, next 2027). Graduation takes effect on a date the General Assembly sets.
- Moving parts: Solomon Islands' graduation was deferred to 13 Dec 2027 (A/RES/77/323), as quoted on the OECD DAC page (§3).
  Bangladesh, Lao PDR and Nepal are scheduled for 24 Nov 2026. ECOSOC backed a 3-year extension for Bangladesh and Nepal,
  and the GA vote is pending **[UNVERIFIED: news only, e.g. https://www.bssnews.net/news-flash/407860]**.
  So re-check this list after 24 Nov 2026.

## 3. "DAC list countries" / "ODA recipients" / "developing countries" per OECD

- Owner: OECD Development Assistance Committee.
  https://www.oecd.org/en/topics/sub-issues/oda-eligibility-and-conditions/dac-list-of-oda-recipients.html
- Current: the list for reporting 2025 flows (PDF):
  https://www.oecd.org/content/dam/oecd/en/topics/policy-sub-issues/oda-eligibility-and-conditions/DAC-List-of-ODA-Recipients-for-reporting-2025-flows.pdf
  It has 4 columns: LDCs, other LICs, LMICs and UMICs, using thresholds based on 2022 GNI.
- Cadence: "The DAC revises the list every three years… The last review took place in 2023… the 2026 Triennial Review…
  has been postponed to 2027" (same page). Nauru graduates with effect from 1 Jan 2027. Guyana and Panama are up for graduation in the 2027 review.
- Machine-readable: PDF and historical HTML/PDF only (https://webfs.oecd.org/oda/DAClists/). No CSV of the list itself.
  The CRS recipient code lists may cover it **[UNVERIFIED]**.
- Use when: the funder says "DAC list", "ODA-eligible", or is a development-aid funder (DAAD EPOS, BMZ- or FCDO-funded schemes).

## 4. World Bank income groups ("low-income", "LMIC", "low- and middle-income")

- Owner: World Bank. https://datahelpdesk.worldbank.org/knowledgebase/articles/906519-world-bank-country-and-lending-groups
  The current classification is FY2027, from 2025 GNI: L ≤ $1,175; LM $1,176–4,635; UM $4,636–14,375; H > $14,375.
  Counts: 25 L, 47 LM, 59 UM, 87 H. Updated every 1 July.
- Machine-readable: CLASS.xlsx (HTTP 200, checked) https://datacatalogfiles.worldbank.org/ddh-published/0037712/DR0090755/CLASS.xlsx
  The JSON API returns `incomeLevel` and `region` per country: https://api.worldbank.org/v2/country?format=json&per_page=400
  Aggregate codes (from https://api.worldbank.org/v2/incomelevel?format=json): LIC, LMC, UMC, HIC, and **LMY = "Low & middle income"**, MIC.
- **Ambiguity: "LMIC" is used for both LMY (L+LM+UM) and LMC (lower-middle only).** Expand the spelled-out phrase
  "low- and middle-income countries" to LMY. A bare "LMIC" goes to a human unless the funder defines it.
- Know which year applies: the funder may freeze the list at its call date, while the World Bank reclassifies every 1 July.

## 5. UN M49 regions ("Sub-Saharan Africa", "Western Asia", …)

- Owner: UN Statistics Division. https://unstats.un.org/unsd/methodology/m49/ ; table at /overview/
  (columns: region, sub-region and intermediate-region codes, ISO-2/3, LDC, LLDC, SIDS flags). The table is an HTML DataTable
  with a client-side CSV/Excel export button; no static CSV URL was found **[UNVERIFIED]**.
- Sub-Saharan Africa = region 202 (sub-regions 011, 014, 017, 018). It contains 53 rows, territories included.
  M49 puts **Sudan in Northern Africa (015)**, so Sudan is not in SSA under M49.

## 6. "Sub-Saharan Africa": three competing official lists

| List | Sudan | Djibouti | Size |
|---|---|---|---|
| UN M49 202 | no (Northern Africa) | yes | 53 rows incl. territories |
| World Bank SSA region (API) | **yes** | **no** (MENA-AfPak) | 48 economies |
| Erasmus+ Region 9 | yes | yes | 49 countries |

Use the list of the funder's own system, e.g. Region 9 for an Erasmus+ action. With no system named, use M49 and
send the two edge countries (Sudan, Djibouti) to a human.

## 7. Commonwealth

- Owner: Commonwealth Secretariat. https://thecommonwealth.org/our-member-countries lists 56 members,
  with Togo and Gabon among them. HTML only.
- Gabon was partially suspended in Sept 2023, and CMAG lifted the suspension on 15 Jul 2025:
  https://thecommonwealth.org/news/gabon-restored-full-membership-within-commonwealth (title read; body via search snippet).
- Repo REGIONS["COMMONWEALTH"] has SS instead of TG. Diffed against the official page on 2026-10-12.

## 8. EU / EEA

Already sourced in the repo (§1). EU source: https://european-union.europa.eu/principles-countries-history/eu-countries_en ; EEA: https://www.efta.int/eea .
No contested membership. HTML only.

## 9. Eastern Partnership

- Owner: EEAS. https://www.eeas.europa.eu/eeas/eastern-partnership_en (updated 08.05.2025): "Armenia, Azerbaijan, Georgia,
  the Republic of Moldova and Ukraine". "Belarus suspended its participation in 2021".
- The repo excludes BY. Correct by the owner's text. A funder that says "EaP incl. Belarus" overrides this.

## 10. ASEAN

- Owner: ASEAN Secretariat. https://asean.org/member-states/ lists 11 members: Brunei, Cambodia, Indonesia, Lao PDR, Malaysia,
  Myanmar, Philippines, Singapore, Thailand, **Timor-Leste**, Viet Nam. The same page says
  "Timor-Leste on 26 October 2025 making up what is today the eleven Member States". HTML only.
- Watch out: a funder page written before Oct 2025 meant 10 members. Bind the list to the page's date.

## 11. CIS

- Owner: CIS Executive Committee. https://cis.minsk.by/topic/2 (redirects to eccis.org) lists 11 "участники"
  (participants): AZ, AM, BY, KZ, KG, MD, RU, TJ, TM, UZ, **UA**. HTML only.
- Contested, from https://cis.minsk.by/page/174:
  - Ukraine and Turkmenistan never signed the 1993 Charter, so they are "de-jure not member states", only founders/participants.
  - Turkmenistan declared itself an "associated member" (Kazan summit, 26 Aug 2005).
  - Georgia left on 18 Aug 2009.
  - The Council of Defence Ministers excludes Moldova, Turkmenistan and Ukraine.
  - Ukraine's 2018 exit from CIS bodies is Ukraine's own position and does not appear on the ExCom page **[UNVERIFIED]**.
  - Moldova's withdrawal from CIS agreements, 2023–25 **[UNVERIFIED]**.
- **A careful reader treats "CIS" as human-review** when the applicant is from UA, TM, MD or GE. For the other 7 it is unambiguous.

## 12. OIC

- Owner: OIC. https://www.oic-oci.org/en/members (Cloudflare; fetched with a browser) lists 57 member states with join years,
  Syria included, without a note. HTML only.
- Observer states: Bosnia and Herzegovina, Central African Republic, Thailand, Russia, "Turkish Cypriot State"
  **[UNVERIFIED: search snippet; /en/observers returned 404]**. Syria's 2012 suspension and whether it was lifted: **[UNVERIFIED]**.
- Observers are not members. "OIC member states" expands to the 57 only.

## 13. Organization of Turkic States

- Owner: OTS Secretariat. Members: AZ, KZ, KG, TR, UZ. Observers: Hungary (2018), Turkmenistan (Nov 2021),
  "Turkish Republic of Northern Cyprus" (Nov 2022), ECO (2023, an organisation). Source: https://turkicstates.org/en/observers
  (menu and observer text read). HTML only.
- **Turkmenistan is the edge case**: an observer, not a member. A funder writing "Turkic states" or "Turkic world" may mean it, so send it to a human.
  TRNC has no ISO 3166 code, so it cannot be expanded to a country code.

## 14. "Erasmus+ partner countries"

- Owner: European Commission, Erasmus+ Programme Guide Part A.
  https://erasmus-plus.ec.europa.eu/programme-guide/part-a/eligible-countries
- Since 2021 the guide says "EU Member States and third countries associated to the Programme" (associated: MK, RS, IS, LI, NO, TR)
  and "third countries not associated" in Regions 1–14. "Programme/Partner countries" is the 2014–2020 vocabulary.
  So "partner countries" today means not-associated third countries, and **eligibility varies per action (Part B)**.
- Region 2 (Neighbourhood East) includes Belarus, with a footnote: no engagement with Belarus public bodies.
  Region 4 is Russia alone (restrictive measures).
- The Guide is republished every year with the call. The web page prints no version year **[UNVERIFIED which year is live]**.
  HTML/PDF only.

## 15. Phrases with no standard list, or several competing ones

| Phrase | Status | What a careful reader does |
|---|---|---|
| "developing countries" | **No UN definition.** UNSD says: "There is no definition of developing and developed countries (or areas) within the UN system". M49 dropped its Developed/Developing regions in Dec 2021, and keeps a frozen xlsx (historical, updated May 2022): https://unstats.un.org/unsd/methodology/m49/historical-classification-of-developed-and-developing-regions.xlsx | Funder list first. If the funder is an aid donor, use the DAC list (§3), as DAAD does. Otherwise send to a human. Never use the M49 xlsx silently: it is frozen, and UNSD itself says to use income groups or custodian lists. |
| "development and newly industrialised countries" (DAAD) | DAAD's own published DAC-based list | Use the funder PDF (top of this file), and flag its stated validity. |
| "newly industrialised countries" / "emerging economies" | No owner. IMF WEO "emerging market and developing economies" exists (imf.org returned 403, **[UNVERIFIED]**), and UNCTAD has its own classification (https://unctadstat.unctad.org/EN/Classifications.html, HTTP 200, not read) | Human. The lists disagree on, e.g., Korea, Singapore and Gulf states. |
| "Global South" | No list. G77 membership is the nearest operative list (https://www.g77.org/doc/members.html, read, count not taken) | Human. Note in the review that G77 is the closest proxy. |
| "low- and middle-income" | World Bank LMY (§4) | Expand to LMY. A bare "LMIC" goes to a human. |
| "Sub-Saharan Africa" | 3 lists (§6) | Use the funder's system list; otherwise M49 with the Sudan/Djibouti edge cases to a human. |

## 16. Suggested order of work (for the caller, not done)

1. Fix the COMMONWEALTH list (SS → TG) and ASEAN (+TL) in `regions.py`. Both are wrong today against their own source URLs.
2. Add data-backed groups that have machine-readable sources and are cheap to refresh:
   LDC from the M49 LDC column, World Bank LIC/LMC/UMC/LMY from the API, and M49 sub-regions.
3. Add the HTML-only lists by hand, each with its source URL and an `as_of` date: DAC (PDF), CIS, OIC, OTS, Erasmus+ regions.
4. For CIS (UA/TM/MD), OTS (TM) and every phrase in §15 except LMY, return UNDECIDABLE and send to a human. The existing regions.py contract already does this.
