# Government inbound master's scholarships — synthesis across two runs and a verification pass

**Date:** 2026-09-13. **Inputs:**
`2026-09-13-government-inbound-review-1.md` (run A, Claude-format export),
`2026-09-13-government-inbound-review-2.md` (run B, Gemini-format export, run under a stricter plan),
`2026-09-13-government-inbound-verification.md` (gptr-mcp search + direct fetch of official pages).
Every claim below carries the grade the verification file gave it; where it says **run A only** or
**run B only**, nobody re-checked it.

**What it answers:** which foreign governments fund a master's degree that an Azerbaijani or Turkish
citizen can actually get into, how those schemes are keyed, and which countries still need a run.

---

## 1. The answer, per launch market

Coverage after both runs and verification: **about 36 of the 58** listed jurisdictions have at least
one row resting on an official source, and far fewer are complete (eligible-country lists, quotas,
sub-national tier). That is enough to answer for the launch markets on the schemes that matter most,
and not enough to call any country absent.

### Azerbaijani citizens

| Scheme | Route | Cost | Grade |
|---|---|---|---|
| Türkiye Bursları | `DIRECT` | Full (5,000 TL/month master's) | Official snippet |
| Chevening | `DIRECT` | Full; two-year return obligation | Run A only |
| DAAD EPOS | `DIRECT` to the course | Full; **keyed on residence**, 2 yrs' work experience | Fetched |
| SI Scholarship for Global Professionals | `HYBRID` (admission, then SI) | Full; work experience required | Fetched |
| Lithuanian state master's scholarship | `DIRECT` after admission | €592/month + tuition grant; 70 grants, per-country quotas | Official snippet |
| Stipendium Hungaricum | `NOMINATED` by the Azerbaijani ministry | Full minus airfare | Fetched + origin-side synthesis |
| GKS, MEXT, CSC, Fulbright, Eiffel, Russian quota | `NOMINATED` | Full | Runs A/B, partly verified |
| World in Serbia | `NOMINATED` (NAM members) | Full minus airfare | Official snippet, 2025 round |
| Polish Banach NAWA | `DIRECT` | Stipend + fee exemption | Run A only |
| Malaysia International Scholarship | `DIRECT` | Full | Eligible-country list is a lead |

Czech development scholarships are **closed** to Azerbaijan for 2027/28 (fetched list).

### Turkish citizens

| Scheme | Route | Cost | Grade |
|---|---|---|---|
| Chevening | `DIRECT` | Full; two-year return | Run A only |
| Heydar Aliyev International Education Grant (Azerbaijan) | `NOMINATED` by Turkish authorities | Full | Fetched (terms); route from third-government pages |
| Stipendium Hungaricum | `NOMINATED` via MEB | Full minus airfare | Fetched + origin-side synthesis |
| GKS, MEXT, CSC, Fulbright, Eiffel, Russian quota | `NOMINATED` | Full | Runs A/B, partly verified |
| Italian MAECI | `DIRECT` | **9 months**, €10,800 + fee exemption — not full-degree | Official snippet + lead |
| Malaysia International Scholarship | `DIRECT` | Full | Lead |
| Guillaume Dupaix International Scholarship (Luxembourg MFA) | Via University of Luxembourg admission | 2-year master's stipend | Official snippet (§7) |

Türkiye is **excluded** from: DAAD EPOS, SISGP, the Lithuanian scheme, Czech development scholarships,
Australia Awards and Manaaki (all fetched or official). Canada's Study in Canada Scholarships include
Türkiye but are an eight-month exchange, not a degree.

**The structural fact behind both tables:** almost everything full-cost is `NOMINATED`, and for our
two markets even schemes the funder describes as open become nominated through the home ministry
(origin-side synthesis). The `DIRECT` full-cost set is Türkiye Bursları, Chevening, EPOS (with work
experience) and, for Azerbaijan only, SISGP — plus MIS if its country list verifies.

## 2. Where the runs disagreed — resolved

Full evidence in the verification file §1.

| Question | Run A | Run B | Resolved |
|---|---|---|---|
| Russia: compatriot track | One quota pool | Separate descent track | Both partly right. Compatriots **and** CIS citizens compete for budget places on equal terms with Russians **outside** the quota; the quota itself has no compatriot allocation |
| Japan: descent master's route | None in MEXT | MEXT Nikkei | Exists — **JICA**, Latin America only. Run B's cited PDF is a non-degree teacher-training programme |
| Türkiye Bursları kin track | Exists | One track | No official evidence of a separate track |
| DAAD EPOS for AZ/GE/AM/KZ | Excluded | — | **Eligible**; only Türkiye excluded; keyed on residence |
| Germany, Canada regional tier | Exists (Germany) | "National scheme only" | Run B wrong: BAYHOST, Baden-Württemberg, Québec PBEEE |
| GKS, Hungaricum, Türkiye Bursları, Chevening numbers | Published | "Unpublished" | Run A right (Hungaricum fetched: 80,000 applications, 4,500+ awards in 2025) |
| Heydar Aliyev route | — | `DIRECT` | `NOMINATED` |
| Stipendium Hungaricum, SISGP key | `CITIZENSHIP` | `REGION` | `CITIZENSHIP` |

## 3. Sourcing scorecard

| | Run A | Run B |
|---|---|---|
| Jurisdictions with rows | 16 | 19 |
| Material factual errors found | 4 (EPOS exclusion, invented Türkiye Bursları track, MAECI "full-cost", Italy IRE as descent) | 9 (Russian quota route, Japan evidence, Canada exchange as master's, Heydar Aliyev route, German/Canadian regional tier, four "unpublished" numbers, Türkiye Bursları stipend, two false index flags, key labels) |
| Echoed prompt content as evidence | Yes (GKS 16 of 24) | No |
| Unique true finds | BAYHOST, BW-Stipendium, OKP closed, Chevening South Caucasus, Russia decree quote | Heydar Aliyev grant, Kazakhstan 550, Ireland GOI-IES, Czech, Flanders Master Mind, Swiss master's art-only, JICA-adjacent Nikkei lead |
| Stale sources | Few | Stipendium Hungaricum 2023/24 and 2024/25 calls |

Run A is more accurate; run B found more countries. **Neither is usable alone**, and the verification
pass found more launch-market routes (Russia's CIS track, Lithuania, Pakistan HEC, Slovakia, Qatar)
than either run.

Several verification finds were **already in the corpus** and simply unconnected to this sweep:
Heydar Aliyev (outbound-launch synthesis, as the "inbound grant" to keep apart from HTP); Lithuania
(nationality-keyed gap-fill review 2); Czech and MIS (nationality-keyed schemes reviews); HEC's Allama
Iqbal and KNB (leading-institutions synthesis). The sweep had no step that read the corpus first.

## 4. Things to strike or hold back

- **Not a master's degree:** Canada Study in Canada Scholarships (≤ 8-month exchange); Israel MFA
  scholarships (8-month non-degree); Latvia's scholarships to foreigners (≤ 10 months); Baden-Württemberg
  Stipendium (exchange semesters); Austria's Ernst Mach grants (short stays or full PhD); Swiss
  Excellence research scholarships (post-master's).
- **Closed:** Netherlands Orange Knowledge Programme (ended December 2024; run A, Nuffic quote).
- **Not a full-cost scheme:** Italian MAECI (9 months); Slovakia's international scheme (€5,000/yr);
  Holland Scholarship (€5,000 once); Georgia's state grant for foreigners (≤ GEL 2,250, lead).
- **Run B's two "change our plans" flags are rejected.** "Study in Europe" is an EU marketing PDF and
  the Basque 2023 catalogue lists all regional grants. **No cross-country index of government
  scholarships exists** — both runs and the verification agree.

## 5. Design consequences

1. **Eligibility is not a nationality list, and not one key.** Verified in this sweep alone:
   - `RESIDENCE`: DAAD EPOS ("the country in which you are living"), Ireland GOI-IES (domicile),
     VLIR-UOS ICP Connect (nationality **and** residence), Russian budget places for CIS citizens with
     a Russian residence permit;
   - `DESCENT`: Russian compatriots, JICA Nikkei, GKS Overseas Korean, Kazakhstan's ethnic Kazakhs,
     Lithuanian origin, Slovaks Living Abroad, Hungarian diaspora, Polish gen. Anders, Austria's
     forced-labourer descendants;
   - `CITIZENSHIP` + `RESIDENCE`: Italy IRE.

   A track needs a *set* of keys with a combinator, not a single enum.
2. **Some routes sit outside the quota that documents the scheme.** Russia's CIS and compatriot
   budget places never appear in a quota table, because they are not quota places. A model that
   discovers schemes by walking quota documents cannot see them.
3. **Who publishes the per-country number is still the sending side.** Heydar Aliyev gives Pakistan 3
   places — published by Pakistan's HEC, not by Azerbaijan. Same pattern as Hungaricum in the
   origin-side synthesis.
4. **Research needs a corpus-read step before searching.** Five of the verification's "new" schemes
   were already on disk. The next prompt should list what the corpus holds and ask for the rest.

## 6. Coverage map and the further deep research needed

### Settled enough for now (no further run)

France, Hungary, Türkiye, United Kingdom (national), United States (Fulbright), Japan, South Korea,
Russia (national), Sweden, Poland, Ireland, Czechia, Kazakhstan, Azerbaijan, Netherlands, Australia,
Lithuania, New Zealand. (Run-A-only rows — Chevening, Fulbright, Eiffel, Banach, Australia Awards —
still want a one-page verification each, not a deep-research run.)

### Needs further deep research — four runs, in priority order

Each run should be two independent models, as before.

**Run 1 — Asia and the Gulf, launch-market eligibility and quotas (highest value).**
China · Malaysia · Indonesia · Brunei · Pakistan · Qatar · United Arab Emirates · Kuwait · Bahrain ·
Singapore · Hong Kong · Vietnam · India.
Why: these are full-cost, mostly OIC/ODA-keyed schemes where our markets are *probably* eligible and
nothing is verified. China needs the CSC bilateral per-country quotas for Azerbaijan and Türkiye and
the provincial government scholarships; India needs the ICCR country schemes; Malaysia, Indonesia,
Qatar and Pakistan need their eligible-country lists from the official call. Singapore and Hong Kong
**do** run government schemes for international students (§7) — the first verification pass searched
them three-to-a-query and wrongly reported nothing; the run must establish whether any reaches a
master's degree. The UAE's only candidates are state-owned universities' own awards (Khalifa, MBZUAI),
which sit on the funder boundary.

**Run 2 — Central/Eastern Europe and the Balkans.**
Romania · Bulgaria · Serbia · Slovenia · Croatia · Greece · Cyprus · Estonia · Latvia · Slovakia
(development-cooperation list) · Portugal · Malta.
Why: several of these carry both a general non-EU scheme and a descent track (Romania's "românii de
pretutindeni", Bulgaria's Decree 228, Slovenia's Slovenians abroad, Greek diaspora), Serbia is open to
Azerbaijan through NAM, and the origin-side synthesis shows Azerbaijan's HTP already places students in
Romania and Slovakia. Only official snippets or leads exist today.

**Run 3 — the sub-national tier, which neither run did properly.**
Spain (autonomous communities) · Italy (regions) · Belgium (Wallonia-Brussels Federation) · Austria
(Länder) · Switzerland (cantons) · Canada (provinces other than Québec) · Germany (Länder beyond
Bavaria and Baden-Württemberg) · UK devolved nations (Scotland, Wales, Northern Ireland) · Australia
(states) · India (states).
Why: run B declared "national only" without looking and was wrong twice. **One hypothesis to test
here, unverified:** Italy's regional right-to-study (DSU) grants are government-funded, need-based and
open to non-EU degree students — if that holds, it is a full-degree route for our population that no
national-scheme sweep will ever list.

**Run 4 — the origin region as a destination.**
Georgia · Armenia · Uzbekistan · Kazakhstan (master's split and ethnic-Kazakh quota) · Azerbaijan
(HTP inbound quotas; Heydar Aliyev start year and per-country slots) · Türkiye (inbound schemes
beyond Türkiye Bursları) · Russia (which agreements give which citizenships budget-place access at
master's level).
Why: students move within the region, the Russian CIS route turned out to be the single largest
unlisted route for Kazakh students, and the Heydar Aliyev grant is only half-documented.

### Not worth a deep-research run — confirm by direct check instead

Finland · Iceland · Israel · Luxembourg · Denmark · Northern Ireland (inside Run 3). Settled by the
second pass (§7): Finland has none, Iceland and Israel fund only non-degree study, and Luxembourg and
Denmark each have one scheme that needs a single verification fetch, not a run.

## 7. Second pass, 2026-09-13 — one search per country

The first verification pass bundled several countries into one query and reported "no evidence" for
fifteen. Challenged on Singapore, each was searched on its own. Grades as in the verification file.

| Country | What exists | Grade | Master's? | Our markets |
|---|---|---|---|---|
| **Singapore** | MOE **Tuition Grant** — subsidy for international students with a **3-year bond to work in Singapore**; MOE-funded **ASEAN Undergraduate Scholarship**; MFA **Singapore Scholarship** (ASEAN, undergraduate); NUS **Service Obligation Scheme** for international students in government-subsidised graduate programmes | Official snippets (`moe.gov.sg`, `mfa.gov.sg`, `nusgs.nus.edu.sg`) | MOE page says diploma and undergraduate only; the NUS scheme is the only graduate-level route — partial, bonded | Tuition Grant and NUS scheme open to all nationalities |
| **Hong Kong** | **HKSAR Government Scholarship Fund**: Belt and Road Scholarship (full non-local tuition, HKU, undergraduate and **research** postgraduate); Scholarship for Outstanding Performance for non-local students at UGC-funded universities | Official snippets (`admissions.hku.hk`, `studyinhongkong.edu.hk`) | Research master's (MPhil) only; taught master's not covered | Belt and Road nationals — includes AZ, TR, KZ as BRI partners (unverified list) |
| **Luxembourg** | MFA-funded **Guillaume Dupaix International Scholarship** for a 2-year master's at the University of Luxembourg | Official snippet (`mae.gouvernement.lu`) | Yes | Eligible list names **Türkiye**, India, Vietnam, Western Balkans, Ibero-America, Thailand, Belarus, Egypt, Moldova, Russia, UK, Ukraine |
| **Denmark** | **Danish Government Scholarship** — state-funded tuition waivers and/or living grants, allocated by universities; automatic consideration | Official snippets (`studyindenmark.dk`, `ku.dk`, `sdu.dk`) | Yes | All non-EU/EEA |
| **Finland** | "there are no governmental scholarships available" | Official snippet (`studyinfinland.fi`) | — | **Confirmed absence** |
| **Iceland** | ~12–15 scholarships for the **BA** in Icelandic as a Second Language | Official snippets (`arnastofnun.is`, `hi.is`) | No | No master's route |
| **Cyprus** | MFA/CyprusAid scholarships (full tuition) for nationals of Africa, the Middle East and the Caribbean | Official MFA post + university page | Undergraduate and postgraduate | Not our markets as listed |
| **Portugal** | Camões I.P. master's scholarships for PALOP and Timor-Leste citizens, nominated via home ministries | Official snippet (Portuguese embassy, Praia) | Yes | Not our markets |
| **Uzbekistan** | ICESCO–Uzbekistan Scholarship Programme (ICESCO member states; tuition, housing, stipend; deadline 15 May 2026); "New Uzbekistan Scholarship" up to 500/yr from unused state-grant quotas | ICESCO official page; the second is a lead | Level unclear (post mentions four-year programmes) | AZ and TR are ICESCO members |
| **Armenia** | Armenian Government Scholarship (intergovernmental + diaspora Armenians) | Lead | Unclear | Diaspora track = DESCENT |
| **Vietnam** | Vietnamese Government Scholarship via VIED (MOET) | Lead | Claimed | Likely bilateral (Laos, Cambodia) |
| **Kuwait** | Kuwait government scholarship (Kuwait University) | Lead (video) | Mostly undergraduate | Unverified |
| **UAE** | No federal inbound scheme found; MoFA scholarship is for Emiratis (outbound); Khalifa University and MBZUAI fund international master's students | Official snippets (`mofa.gov.ae`, `ku.ac.ae`) | Yes, university-run | Funder-boundary case |
| **Bahrain** | Nothing inbound; the Crown Prince programme is outbound | Official-adjacent | — | No evidence |
| **Malta** | Nothing found | — | — | No evidence |

**Lesson recorded:** a multi-country query returns the loudest country's results and nothing for the
rest. "No evidence" is only a result when the country was searched on its own, in its own terms.

### What the follow-up prompt must add

- **Read the corpus first**, and name what it already holds, so runs stop rediscovering Heydar Aliyev
  and Lithuania.
- **Ask for routes outside the quota** explicitly (equal-rights budget places, residence-permit
  routes), since quota documents cannot show them.
- **Require the eligible-country list verbatim from the current call**, not from an aggregator — the
  single most common gap in both runs.
- **Keep per-country quotas for Azerbaijan and Türkiye as a required column**, and look for them on
  the sending side (ministry announcements), where they are actually published.
