# The Elmify search engine: how it works, what we measured, and why it is built this way

Written 2026-10-24 for the external reviewer. It describes the code on `master` at `e5258ea2` (2026-10-20), not the plans. Every number is copied from a measurement note or the code in the repository; the file it comes from is named next to it. Anything we worked out by reading code, rather than found written down, is marked *(read from code)*.

Companion documents: the audit answer and its follow-up (`docs/superpowers/2026-10-24-external-audit-answer.md`) and the hidden-gem pressure-test protocol (`docs/superpowers/2026-10-24-hidden-gem-pressure-test.md`).

Contents: 0 Summary · 1 Pipeline · 1A What we search for · 1B Sources and tools · 1C Programmes · 2 Discovery · 3 Fetching · 4 Reading · 5 Provenance · 6 Freshness · 7 Pack · 8 Per-student search · 9 Gates owed · 10 Weaknesses · 11 Corrections to the audit · 12 Owner decisions.

---

## 0. Summary

Elmify finds master's programmes and the money to pay for them for applicants from Azerbaijan (then Turkey). The engine has two halves:

- **Offline, shared by every student:** find funders, universities and programmes (discovery) → fetch their own pages (fetch ladder) → read facts off those pages with quotes (readers) → admit only institutions an official register vouches for (provenance gate) → store the facts in one shared catalogue → keep them current (cycle verification).
- **Per student:** a questionnaire → hard gates, deterministic money math and ranking over the catalogue → a published recommendation pack. A per-student web search ("the tap") can add hosts the catalogue lacks.

Where it stands on 2026-10-20:

Nothing is deployed to production yet, so "switched on" below means what the code and the deployment template would run.

| Part | Built | Switched on |
|---|---|---|
| Register spine, closed lists, sweep harness, resolver, classifier | Yes | No: the gates that would let them write at scale failed or were not run (section 2.4) |
| Fetch ladder, rungs 1–4 and 6 | Yes | Yes when called; the rung-5 retry schedule is off |
| Gen-1 funding reader (three readings, unanimity) | Yes | Yes, but serves very little (2 of 69 rows written on the EACEA run) |
| Gen-2 card engine (code finds values, two cheap readers, Opus decides) | Engine yes | No: storage, serving and wiring ("slice 3") are not built; only tests call it |
| Provenance gate | Yes | Yes, enforced by default in the deployment template; registers for 4 countries only |
| Cycle verification | Yes | No: schedule disabled, accuracy gate not run |
| Decision layer, money math, pack, publish | Yes | Yes; balanced-strategy students get no programmes because fit is a placeholder 50 |
| The tap (per-student search) | Stage 1 yes | No: switched off; stage 2 reads nothing |

---

## 1. The pipeline at a glance

```
OFFLINE (platform-paid, shared)
  closed lists / registers / enumerators ─┐
  sweep harness (Exa + Brave, page-voiced, local languages) ─┤→ Organisation register (keyed by domain)
  name→site resolver, host classifier ────┘        │
                                                    ▼
                         fetch ladder (Firecrawl → scrape.do → retry → Internet Archive → person)
                                                    │
                                                    ▼
                         readers: Gen-1 funding judge  |  Gen-2 card engine (not wired yet)
                                                    │
                                                    ▼
                         provenance gate (register-backed verdict per domain)
                                                    │
                                                    ▼
                         shared catalogue (Program, awards, quotes, source URLs)
                                                    │
                         cycle verification (is this year's call open?)  [schedule off]

PER STUDENT
  questionnaire → profile snapshot → candidate pool (catalogue) → hard gates → money math
  → ranking → pack → published (no counsellor gate) → pack page with official source links
  └→ the tap: student's own search → new hosts → stage 2 read  [switched off; stage 2 unbuilt]
```

---

## 1A. What we search for: the categories

Everything the engine finds is sorted into closed vocabularies. A value nothing fits is `UNSTATED`, with its quote kept; nothing is forced into the nearest box.

### Who holds the money (holder kinds, 14 + unstated)

From `apps/research/funding_judge.py` (`_Holder`) and its copy in `apps/funding/models.py`:

| Holder kind | Examples from our own research | How we reach it |
|---|---|---|
| `NATIONAL_GOVERNMENT` | Azerbaijan's State Programme, Türkiye Bursları, Commonwealth Scholarships (UK) | Closed list first; search sweep as a novelty check |
| `SUBNATIONAL_GOVERNMENT` | Italian regional DSU grants, Turkish municipalities | Register survey (ANDISU, Türkiye's union of municipalities) |
| `INTERGOVERNMENTAL` | World Bank JJ/WBGSP, IsDB, ADB-Japan, ICESCO, Organization of Turkic States (Heydar Aliyev scholarship), Nordic Master | Closed list `igo_regional_global` (22 schemes) |
| `REGIONAL_FUND` | Visegrad Fund, EEA and Norway Grants, Black Sea Trust | Same closed list |
| `EMBASSY_BILATERAL` | Azerbaijan's intergovernmental programmes (HTP), Turkish MEB's foreign-government list | Closed lists `az_bilateral`, `tr_bilateral` |
| `PRIVATE_FOUNDATION` | German Stiftungen, Turkish vakıflar | Registers (VGM) + search sweep |
| `POLITICAL_FOUNDATION` | Konrad-Adenauer and other party foundations | Search sweep (no register found in TR or AZ) |
| `RELIGIOUS` | Community and religious foundations | Registers (VGM community foundations, Azerbaijan's religious-affairs committee) + sweep |
| `EMPLOYER` | Companies paying students directly | Largest-employer lists (ISO 500, Baku Stock Exchange issuers) + sweep |
| `DIASPORA_AFFINITY` | Associations of one nationality abroad | Sweep in the host country's web, in the home language |
| `PROFESSIONAL_BODY` | Engineering chambers (TMMOB) | Register only, read on a signal; never by open-web search |
| `BANK_OR_LENDER` | Licensed banks (BDDK, Central Bank of Azerbaijan lists) | Register only, read on a signal |
| `ALUMNI` | Alumni associations | Register only |
| `INSTITUTION` | Universities' own scholarships and waivers | Institution registers + the programme pages themselves |

Search sweeps cover four of these as **families** (`apps/research/angles.py`, `PASS_SHAPES`): private foundation (private, political and religious foundations), industrial sponsorship (employers), affinity or diaspora, and government scholarship. The others are reached through registers and lists, because open-web search for them returns mostly noise.

### What kind of award it is (instrument kinds, `_Kind`)

| Kind | Meaning |
|---|---|
| `I0_HOLDER_AWARD` | A funder's own scholarship, not tied to one institution (a foundation's or ministry's scheme) |
| `I1_UNIVERSITY_WIDE` | A university's scholarship open across its programmes |
| `I2_PROGRAMME_ATTACHED` | Money attached to one programme |
| `I3_STIPEND_OR_ASSISTANTSHIP` | Stipend, teaching or research assistantship |
| `I4_RESEARCH_PATHWAY` | Funding tied to a research track or PhD pathway |
| `I5_FUNDED_DUAL_DEGREE` | A funded joint or double degree (Erasmus Mundus and similar) |
| `I6_RELOCATION_HOUSING_TRAVEL` | Help with moving, housing or travel only |
| `I7_PAID_PLACEMENT` | A paid internship or placement within the degree |

### What we record about each award

| Field | Values |
|---|---|
| Scope | `PROGRAM`, `PROGRAMS`, `INSTITUTION`, `HOLDER_OWN` (the page's own organisation pays), `POINTER` (a third party's money mentioned on the page, kept as a lead) |
| Route to the money | `AUTOMATIC_ON_ADMISSION`, `CONSIDERED_WITH_ADMISSION`, `STUDENT_APPLIES_SEPARATELY`, `INSTITUTION_NOMINATES`, `HOME_GOVERNMENT_NOMINATES`, `JOINT_SELECTION` |
| Money form | `GRANT`, `FEE_WAIVER`, `SUBSIDY`, `LOAN`, `FORGIVABLE_LOAN`, `MIXED` |
| What it covers | `TUITION`, `LIVING` (stipend), `TRAVEL`, `HOUSING`, `INSURANCE`, `RELOCATION`, `TOTAL` (one unsplit sum), `OTHER` |
| Coverage level | Tuition and living each `NONE`, `PARTIAL` or `FULL` |
| Amount | Value, currency, period (`MONTHLY`, `ANNUAL`, `ONE_OFF`, `FULL_PROGRAM`), and bound: `EXACT`, `UP_TO` (shown, never counted), `AT_LEAST` |
| Who may apply | Nationality: `OPEN`, `COUNTRY_LIST`, `BLOC`, `BILATERAL_PAIR`; target level; requirements; whether internationals are included |
| Extras | `TRAVEL`, `INSURANCE`, `HOUSING`, `LANGUAGE_YEAR`, `VISA` |
| Obligations | `RETURN_HOME`, `WORK_IN_HOST`, `SERVE_FUNDER`, `REPAY_ON_BREACH` (shown as disclosures, never as filters) |
| Dates | Application opening, application deadline, fee deadline, scholarship decision date, intake |
| State flags (Gen-2) | Renewal condition, discontinued, application window closed, apply here vs elsewhere, institution-wide |

The Gen-2 card asks 22 fields (`apps/research/card_funding/card.py`, `FIELDS`): benefits, fees, dates, target level, nationality, requirements, funding duration and period, money form, holder kind, route, route order, tuition and living level, extras, obligations, apply here, apply elsewhere, institution-wide, renewal condition, discontinued, window closed.

Programme costs use their own categories: tuition, application fee, housing, food, transport, utilities, insurance, other (`CostComponent`). Award rules are typed as eligibility, amount, capacity, geographic scope, deadline and applicant condition (age caps, work experience, means tests, values endorsements), with return-service bonds kept apart as a disclosure (`BenefitRule`).

### Where and in which fields

- **Destinations:** 53 countries (`apps/research/destinations.py`): the 27 EU states, Norway, Switzerland, Iceland, the UK, Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Australia, New Zealand, Singapore, Brunei, Serbia, Türkiye, China, Japan, South Korea, Russia, Vietnam, Armenia, Azerbaijan, Georgia, Kazakhstan, the USA and Canada. A student who picks no country is searched across all 53.
- **Fields of study:** the 26 ISCED-F 2013 narrow fields plus "unclassifiable" (`docs/research/discipline-buckets.csv`: education, arts, humanities, languages, social sciences, journalism, business, law, biology, environment, physical sciences, mathematics, ICT, engineering, manufacturing, architecture, agriculture, forestry, fisheries, veterinary, health, welfare, personal services, occupational health, security, transport). They are used today to count coverage per demand cell, not to match programmes; matching is still a name match (section 1C).
- **Level:** master's only (`Program.DegreeLevel` = `MASTER`), taught or research track, single or joint degree. The questionnaire's PhD intent adds research-pathway words to the per-student search.

---

## 1B. Sources and tools

### Lists and registers we start from (`docs/research/closed-lists.csv`, 21 lists)

| List | Country | What it is | How it is used |
|---|---|---|---|
| `eacea_emjm` | EU | Erasmus Mundus Joint Masters (EACEA project records) | Enumerate |
| `igo_regional_global` | — | Intergovernmental bodies and regional funds (hand list, 22 rows) | Read for funding |
| `national_scholarship_agencies` | — | National scholarship agencies with no open register | Enumerate |
| `vgm_tr` | TR | VGM foundations register, grant-making only (4,076 printed) | Classify |
| `tr_outbound_gov` | TR | Ministry of Education outbound government scholarships | Read for funding |
| `tr_bilateral` | TR | Foreign-government scholarships announced by MEB | Read for funding |
| `tr_heis` | TR | YÖK licensed institutions (208 printed) | Classify |
| `tr_banks` | TR | BDDK licensed banks | Signal only |
| `tr_professional_bodies` | TR | TMMOB engineering chambers (24) | Signal only |
| `tr_yok_state`, `tr_yok_foundation` | TR | YÖK state and foundation universities | Enumerate (provenance register) |
| `az_outbound_gov` | AZ | Ministry of Science and Education: State Programme | Read for funding |
| `az_bilateral` | AZ | Intergovernmental scholarship programmes (HTP) | Read for funding |
| `az_heis` | AZ | Higher-education institutions | Classify |
| `az_banks` | AZ | Central Bank licensed banks | Signal only |
| `wd_tr_university`, `wd_az_university` | TR, AZ | Wikidata universities with an official website | Enumerate |
| `gb_ofs_register` | GB | Office for Students register (England) | Enumerate (provenance register) |
| `gb_sfc_universities` | GB | Scottish Funding Council universities (19) | Enumerate (provenance register) |
| `kr_univ_info` | KR | Ministry of Education university information | Enumerate (provenance register) |
| `de_hochschulkompass` | DE | HRK Hochschulkompass, state-recognised institutions | Enumerate (provenance register) |

The **register survey** (`docs/research/register-survey.csv`, 23 rows) records, per country and holder kind, which official list exists and at which rung: for Türkiye and Azerbaijan every holder kind, plus German foundations (BZSt donation-recipient register), Kazakh foundations (AIFC) and Italian regional bodies (ANDISU). Where no list exists (for example political foundations in both countries, Azerbaijani private foundations and professional bodies) the row says so, with the search that was tried.

**National study databases:** `find_national_databases` found 1,089 candidate official catalogues in 53 countries: 454 of institutions, 334 of programmes, 301 of scholarships (`docs/research/national-study-databases.csv`). All are still candidates; none is read yet.

### What we deliberately do not use as a source

- **Aggregators and commercial portals** are excluded from every search result (`apps/research/domains.py`, `AGGREGATOR_DOMAINS`, 216 domains): for example scholars4dev, scholarshipdb, findamasters, masterstudies, educations.com, idp.com, edvoy, yocket, StudyQA, cucas.cn, and the national "study in …" portals. Their pages are second-hand and often stale.
- **Six official catalogues may be followed to the real institution but are never evidence themselves** (`HOPPABLE_CATALOGUES`): daad.de, eacea.ec.europa.eu, erasmus-plus.ec.europa.eu, studyinkorea.go.kr, campusfrance.org, and the national catalogues.
- **No DAAD programme-database adapter:** the 2026-08-27 access-terms review could not establish that DAAD's terms allow automated retrieval, and the rule is not to write such an adapter (`apps/research/pipeline.py`).

### External tools and data

| Job | Tool | Status |
|---|---|---|
| Open-web discovery | **Exa** (neural search, 15 results; 100 in deep mode; domain-restricted mode) | In use |
| Open-web discovery | **Brave Search** (up to 10 result pages; Goggles to cut aggregators) | In use |
| Name → website, site maps, site-search fallback | **Tavily** | In use; removed from discovery (09-24) and never used for per-student search |
| Name → entity enrichment | **Diffbot** Enhance | Resolver's last step; needs terms re-read every 31 days |
| Regional engines | Baidu, Naver | Measured (+7, +5 new funders), not built |
| Measured and rejected | Yandex, Google via SerpApi, Exa Websets / `deep` / `findSimilar`, crt.sh | Comparators only |
| Fetching | **Firecrawl** (scrape, map, crawl, agent, change tracking, monitors) | In use, rungs 1–2 |
| Fetching | **scrape.do** (plain and rendered with premium proxies) | In use, rungs 3–4 |
| Fetching | **Internet Archive** (Wayback) | In use, rung 6 |
| Identity | **Wikidata** (universities, websites P856, kind words), **ROR** (identity and country only) | In use |
| Erasmus Mundus | **EACEA** project records | Adapter built; keys unverified |
| Which register is official | **ENIC-NARIC** country pages | In use |
| Domain age | **IANA RDAP** | In use (no dates for .az, .de, .tr, ac.uk) |
| Domain keys | **Public Suffix List** (tldextract) | In use |
| Languages per country | **Unicode CLDR** via Babel (≥ 5% speakers) | In use |
| Exchange rates | **Central Bank of Azerbaijan** daily table | In use; an ECB parser exists, unused |
| Models | OpenAI (`gpt-5.6-luna`, GPT-6-luna), Anthropic (Sonnet 5, Opus 5.5), DeepSeek V4.1 Flash and Jev via OpenRouter | See section 4.5 |
| Student documents | Azure Document Intelligence | Transcripts only, not web pages |

---

## 1C. Programmes: how a programme gets into the catalogue and into a pack

### What a programme record holds

`apps/funding/models.py`, `Program`: institution, name, campus, city, country, degree level (master's), track (taught or research), provision (single or joint), the provider as printed, evidence domain and whether it is the institution's own host, origin domain (part of the row's identity), duration in months, and the application requirements read off its pages: CV format (Europass required or preferred, funder template, structured fields only, any), CV constraints, referee requirements, file rules, whether a letter is required. Costs hang off it as cost components; funding attaches through programme-scope awards. Requirement sentences from its pages are stored as statements typed competency, document, format or language.

### Where programmes come from today

1. **Erasmus Mundus.** The EACEA adapter is the one built-in programme source (`pipeline.default_sources`); the full-catalogue run on 08-30 turned 169 sites into 9 catalogue rows.
2. **Entity expansion.** Search finds *organisations*, never programmes directly; the pipeline then reads each organisation's own sitemap for programme pages, so every programme lead comes from the institution's host. Search results were not allowed to become programme leads after a live run on 2026-08-30 returned eight content farms out of ten.
3. **`discover --field --country`.** The operator command that runs the two sources above for one field and country (up to 25 leads) and writes catalogue rows.
4. **A programme the student names.** The student types a programme; a counsellor verifies its URL; that domain is checked by the provenance gate before it can enter the pack.
5. **The per-student search (switched off).** Programme queries are filled from templates per language (`ProgrammeAngle`, kinds `PROGRAMME`, `MONEY`, `RECENCY`) with slots for field, research interest, teaching language, money, intake, duration, research pathway and destination, one destination per query. Only these profile answers ever enter a query (`tap_query.QUERY_WORDS`); budget, grades and experience only filter results; nationality, country of residence and free-text notes never leave the platform. Found hosts would go to stage 2, which reads nothing yet.
6. **Official national programme catalogues** (334 found) are candidates, not yet read.

Not used: sitemaps as a general spine (2 of 5 universities had usable ones, 08-28), DAAD's database (terms), commercial programme portals (excluded).

### From catalogue to the student's list

The candidate pool takes up to 50 programmes whose **name contains the student's target field** (for example "Chemical Engineering"), minus excluded countries and unrecognised institutions (`apps/funding/pool.py`). The code calls this "interim": selection by demand cell (field bucket × destination × home country) is meant to replace it. Each programme then goes through the ten hard gates, the money math and the application budget (section 7). The ISCED field buckets already exist, so field matching by code rather than by name is a data change, not a new vocabulary.

---

## 2. Discovery: finding who funds and who teaches

### 2.1 How it works

1. **One door into the register.** `apps/research/register.py::record_organisation` is the only way a body enters. It looks the body up by registrable domain (Public Suffix List, `apps/research/hosts.py`), then by any identifier (ROR, Wikidata, EACEA PIC, UKPRN …), and only then creates a row. Statuses: REGISTERED, CANDIDATE, REJECTED.
2. **Closed lists and registers first.** `docs/research/closed-lists.csv` (21 lists) gives each list a rung 0–4 and a read policy (`FUNDING_READ`, `CLASSIFY`, `SIGNAL_ONLY`, `ENUMERATE_ONLY`). `load_closed_lists` loads them; only a list that is a true denominator promotes a body to REGISTERED. `read_register --register vgm` reads Türkiye's foundation register (VGM, grant-making foundations only). `register-survey.csv` (23 rows) records which register exists for which country and holder kind.
3. **Enumerators.** Wikidata (`enumerate_wikidata`: Turkish and Azerbaijani universities), EACEA for Erasmus Mundus (`enumerate_eacea`; its project keys are still unverified placeholders), national study databases (`find_national_databases`, 1,089 candidate catalogues in 53 countries, none confirmed yet).
4. **Name → website resolver** (`apps/research/resolver.py`) for register rows with no URL: own-domain e-mail, then Wikidata P856, then Tavily search scored by a lexical rule, then a title check, then Diffbot. A name it cannot resolve stays unresolved with a reason (`ONE_TOKEN_NAME`, `DIRECTORY`, `TITLE_MISMATCH` …). Writes are switched off (`RESOLVER_WRITES_ENABLED`) until it passes a blind hold-out.
5. **Host classifier** (`apps/research/classify.py`): an official suffix (`.edu.tr`, `.gov.tr`) gives the kind for free; otherwise the homepage is fetched and a frontier model answers kind, country and "funds students?", abstaining below 0.8.
6. **Sweep harness** (`sweep_organisations --country DE --family PRIVATE_FOUNDATION`). For one (country, funder family): pick the lowest register rung that covers it; write queries in the voice of the page we want ("Bewerbung für das Stipendium …"), in every language with at least 5% speakers plus English; run them in shuffled batches on Exa and Brave at 15 results; key every hit by domain, drop aggregators, dedupe against the register, classify new hosts in-pass. A host counts only if the classifier says it funds students *and* is the family being swept. Stop on whichever comes first: plateau (3 batches with no new verified host), cost per award, exhaustion, budget ($5 a pass) or classifier limit.
7. **Angles** (the sentence templates): one DeepSeek V4.1 Flash call per language writes six kinds (application, eligibility, season, about, FAQ, PDF call). Words like "foundation" come from Wikidata, never from a model translation. Families: private foundation, industrial sponsorship, affinity/diaspora, government scholarship.
8. **Tally and retirement** (`sweep_tally`): finds are credited per (classified family, provider, angle, language); an angle with zero verified finds after 4 uses is retired.
9. **Demand cells and coverage.** A cell is holder × host country × home country × level. A thin area queues a bounded area sweep ($5). `closed_list_coverage` prints, per list, how much of the printed register we know and in what read state.

### 2.2 Strategies and why

- **Never merge two bodies on a name.** Neighbours share names (Carl-Zeiss-Stiftung and ZEISS; İnönü Vakfı and İnönü Üniversitesi), and a wrong merge is never undone.
- **The origin is the only evidence.** A search provider gives us a URL, never a fact; snippets are second-hand and stale.
- **Registers before search; know the denominator.** In Türkiye, search reached under 1% of the VGM register. "94% of a register" and "stopped after three empty batches" are different claims, and the coverage line says which one it is making.
- **A list is a denominator, not a reading queue.** Reading all 4,076 VGM hosts would cost about $1,400; classifying them costs about $4. Only hosts that pass the classifier get read.
- **Page-voiced queries, breadth over depth, in local languages, no provider language or country filter.** Topic queries return round-up blogs (20 of 72 Turkish hosts were noise); provider filters measurably hurt (section 2.3).
- **No study level in sweep sentences** (owner, 2026-10-14). Naming "master's" hid real master's funders.
- **No country is a code branch; no human types tips into the engine.** Tips have no denominator.

### 2.3 What we measured

| Date | What | Result | Source |
|---|---|---|---|
| 08-28 | Shadow run `discover robotics DE` | 5 leads → 0 written (5 blocked) | `docs/superpowers/research/2026-08-28-discovery-shadow-run.md` |
| 08-28 | Sitemaps as a programme spine | 2 of 5 universities usable; Finland's JSON API listed 1,285 master's | `docs/superpowers/2026-08-28-discovery-state-of-play.md` |
| 08-30 | Search recall, 16 known targets, 128 queries, 4 providers × English/local | Tavily 16/16 English, 8/16 local; Brave 14/14; Exa 13/10; run-to-run ±2 | `…/research/2026-08-30-search-recall-measurement.md` |
| 08-30 | Full EACEA catalogue | 169 sites → 494 leads → **9 catalogue rows**; 595 model calls | `…/research/2026-08-30-eacea-full-catalogue-run.md` |
| 09-16/17 | Provider probe, 160 calls, 862 hosts | Share of results on the funder's own site: Exa 79%, Brave 76% (a Goggle cut aggregators 33%→14%), Tavily 50%. Exa found 132 hosts no one else did | `…/research/2026-09-17-search-tool-probe.md` |
| 09-17 | Saturation: Germany × private foundation, 99 queries, 396 calls | 1,067 domains; **353 German/DACH funders**. New funders per batch: 146, 49, 32, 18, 24, 25, 27, 15, 17 (plateau, not saturation). First finders: Exa 147, Brave 100, Tavily 84, Firecrawl 22. About $2–6 | `…/research/2026-09-17-cell-saturation-measurement.md` |
| 09-17 | Settings ablation against a 377-funder key | **No configuration exceeds 18%** (Brave 10 result pages 18.0%; Exa 100 results 14.9%; Tavily 5.0%). Exa's `company` category −2.7 pts; provider `country` filter −8 in Indonesia; `search_lang` changed nothing | `…/research/2026-09-17-search-capability-ablation.md` |
| 09-17 | Regional engines | Baidu +7 new at 76%; Naver +5; Yandex 0 (Azerbaijan); Google +1 | same |
| 09-17 | Diffbot non-profit query | 137 entities, 28 fund students; +24 on the 353 (+7%); ~$0.14 per new funder vs ~$0.006 by sweep | `…/research/2026-09-17-diffbot-perplexity-recon.md` |
| 09-18 | Resolver, development set | Germany 20 correct / 0 wrong / 5 unresolved; Türkiye 12/1/12 | `docs/superpowers/specs/2026-09-17-role-routed-discovery-design.md` §4.13a |
| 09-18 | Resolver, blind hold-out | Georgia 5/3/17; Kazakhstan 1/11/13 → **FAIL**, six new rules | same §4.13b |
| 09-19 | ROR name lookup, 10 names | 8 right; Anadolu → TEV and EMBL → EMBL Australia wrong | `docs/research/2026-09-19-dual-seed-review.md` |
| 09-23/24 | First live Türkiye sweep | Tavily 0 first finds vs Exa 112, Brave 102 → Tavily removed from discovery | commit e1884cfa |
| 09-24 | Türkiye sweep 2 | 447 URLs, 214 new domains, 72 `.tr`, ~30 foundations → page-voiced redesign | `…/research/2026-09-24-query-design-and-enumeration.md` |
| 09-24 | VGM register | 6,857 foundations, 4,076 grant-making | same |
| 09-24 | Classifier gate, run 1 (81 labelled hosts) | Kind 58/61; funds-students 47/61; 10 abstained; Latin script only | commit 37ae5da8 |
| 09-24/25 | VGM read + classify | **1,417 of 4,028 register rows bound to a website for free (38%)**; 49 classified as funding students | master design §16 item 6a |
| 09-24 | Exa Websets / `deep` / `findSimilar` | Websets $0.045 per match (comparator only); `deep` 1 real find for $0.029 (not adopted); `findSimilar` 2 peer foundations for $0.007 | master design §6.3–6.4a |
| 09-26 | Enumerators gate | **FAIL**: 10 of 11 lists fail (259 entries: 144 unbound, 76 unread, 36 gated, 3 rejected); no network egress or keys at the time | `docs/superpowers/2026-09-26-enumerators-gate.md` |
| 09-27 | Exa `category:company` re-measure | Default found 32 new domains / 12 foundations vs 17 / 5 → not adopted | `…/research/2026-09-27-exa-category-company-remeasure.md` |
| 10-13 | Who writes sweep sentences | Funders per set: templates 32.7, DeepSeek 28.0, bare words 26.7; DeepSeek chosen | `…/research/2026-10-13-sweep-sentence-writing-comparison.md` |
| 10-13/14 | Angle writer across 42 languages | After fixes 42/42 return 18 sentences; ~$0.10 | `…/research/2026-10-13-angle-writer-language-check.md` |
| 10-14 | Naming the study level, Türkiye; Japan/Korea/Russia | Of 19 foundations found only without the level, 5 fund master's. Without/with level: 189/104, 105/74, 169/105 sites → level removed | comparison note above |

Not run: the ROR gate (API returned 403), the resolver's fresh Vietnam hold-out, saturation gates A and B.

### 2.4 Status

- **Built:** everything in 2.1.
- **Switched off:** `FUNDER_SWEEP_LEVEL_CHECK_LIVE` (funder sweeps refuse to run until a reader can check the master's level), `RESOLVER_WRITES_ENABLED`, Tavily in discovery.
- **Not built:** a cheap Jev host classifier (only the frontier one exists), ROR and DEQAR enumerators, a per-university domain-restricted search *as a discovery pass* (`exa_site_search` exists but only research-fit and cycle verification call it), Baidu/Naver legs, `findSimilar`, social-media reading (Browser Use), capture–recapture "estimated unseen" figure, the pointer → register writer.

---

## 3. Fetching: getting the page itself

### 3.1 How it works

Every research page goes through `fetch_page(url, purpose, tag, require_origin, budget, timeout_s)` (`apps/research/fetch/__init__.py`):

| Rung | Method | Cost | When |
|---|---|---|---|
| 1 | Firecrawl scrape (HTML, links, change tracking) | 1 credit (a PDF: 1 per page) | Always first |
| 2 | Firecrawl with wait/scroll actions | 1 credit | Rung 1 returned an empty shell |
| 3 | scrape.do, no render | 1 credit | Firecrawl failed |
| 4 | scrape.do with JS render and premium proxies | 25 credits | Only when the host beat us (blocked/unreadable); never on 429, 5xx, 402 |
| 5 | Scheduled retry (24/48/96 h unreachable; 6/24/48 h blocked; 3 tries) | — | Rungs 1–4 failed; skipped if the caller has a deadline |
| 6 | Internet Archive capture ≤ 365 days old, fetched through scrape.do | 1 credit | After rung 5 |
| 7 | A person (a `HOST_UNREACHABLE` item in the operator queue) | — | Last |

Every attempt writes a `FetchAttempt`; every outcome updates the host's memory (`HostProfile`): a host that needed rung 3–4 starts there next time, is re-probed from rung 1 after 30 days, and a blocked host cools off (6 h doubling, cap 7 days). Twelve outcomes; refusals are returned as values, never raised. `SweepBudget` caps credits per vendor; `reconcile_fetch_credits` checks our ledger against the vendor's bill (alarm at 5%). Site jobs (`fetch/site.py`): `/map`, `/crawl` (reads robots-blocked errors), `/agent`; all return URLs only, and every URL is re-fetched and origin-checked.

### 3.2 Strategies and why

- **Refusals are values.** Before this, a blocked fetch and a page that says nothing reached the reader looking the same, twice.
- **Buy, don't build** anti-bot, rendering and challenge solving (owner, 2026-09-19).
- **Firecrawl first although it costs 7× more per credit:** its free change tracking skips a ~$0.35 reader run when a page has not changed, which pays for 420 fetches.
- **Two failures, two answers:** "this host beat us" buys rung 4; "not now" (429, 5xx) does not. Otherwise every 429 spends 25 credits on a page that would have cost 1 a minute later.
- **HTML body, full page.** A markdown body once silently produced zero leads.
- **The final URL comes from the vendor's report, and must be on the same origin before any byte is kept.**
- **Robots.txt and text-and-data-mining opt-outs are left to the vendor** (owner, 2026-09-18); Firecrawl's crawl always honours robots.txt.

### 3.3 What we measured

| Date | What | Result | Source |
|---|---|---|---|
| 09-15 | Archive recovery | Two pages recovered (DAAD PRIME FAQ, Sciences Po); Sciences Po could not be reproduced on 09-22 | `docs/superpowers/specs/2026-09-22-fetch-engine-design.md` §16 |
| 09-18 | Firecrawl raw HTML stability | Same FAU page 189,682 vs 422,515 bytes between fetches | same §3 |
| 09-19 | Ladder over 58 funder hosts | Own client 49/58; Firecrawl +5; scrape.do +1 (25 credits); 2 dead. Whole sweep 4.8 cents | `docs/superpowers/specs/2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md` §4.0a–4.1b |
| 09-19 | Live fetch gate | 5/5 (PR #103) | master design §15 |
| 09-22 | Firecrawl image text | Turkish exact, Russian 75%, Azerbaijani 86%, Georgian unreadable | fetch-engine design §12, §15 |

### 3.4 Status

Built: rungs 1–4 and 6, host memory, budgets, ledger, site jobs. Switched off: the rung-5 retry schedule (a successful retry stores no snapshot and hands the page to no reader, so it would spend credits for nothing), fetch webhooks. Not built: a funnel orchestrator that runs the site-job stages end to end (`sitejob.py` holds only types), screenshots.

---

## 4. Reading: turning a page into facts

Two generations exist. Gen-1 is live and serves very little; Gen-2 was built to replace it and is not wired in yet.

### 4.1 Gen-1: the funding judge (live)

1. The page is cut into lines of ≤ 300 characters, in chunks of 80 lines, at most 3 chunks per page (`apps/research/funding_judge.py`).
2. **Three readings per chunk:** two differently phrased prompts on `gpt-5.6-luna` and one on `claude-sonnet-5`. Each answers closed questions about each line (is an award offered here? to whom? how much? …). The quote is the line itself, by index, so no quote can be invented.
3. A 2–1 split on "offered" buys a fourth reading and decides 3 of 4.
4. **Tiered agreement:** a split on whether the award exists (offered, holder, scope) makes it UNAGREED; a split on any other field keeps the award AGREED with that field blanked and flagged.
5. **Served** only if AGREED, offered = yes, a benefit or money form is stated, and the lead is vouched. Everything else goes to the operator queue (`AWARD_DISPUTED`), where a human decision is bound to the exact page version.

Separately, the **programme page reader** (`apps/research/reader.py`) runs `gpt-5.6-luna` three times on a programme page and keeps only quotes found on the page; it has no production caller yet.

### 4.2 Gen-2: the card engine (built, not wired)

1. `card_funding/entry.py::read_page` fetches the page (pinned to its origin) under a **30-second, $0.25 limit** for the whole read.
2. **Screen (D8):** two Jev questions check for a hostile page. Score ≥ 0.70 quarantines it; unscreened pages are never read (fails closed).
3. **Awards:** readers only answer "is this heading an award name?"; code groups lines under headings.
4. **Candidates:** deterministic code finders pull amounts, dates, relative dates, durations, intakes, places, levels and requirements.
5. **Questions:** about 20 per batch, asked of **two cheap readers in parallel** (DeepSeek V4.1 Flash pinned to one host, and GPT-6-luna, both via OpenRouter). Same answer from both = agreed; anything else goes to the **decider, Claude Opus 5.5**. Quotes must match the page byte for byte.
6. **Card:** code parses every value. Each field ends `shown`, `held` (with a reason: unresolved split, conflicting values, unparseable value, needs hunt, page budget …) or `not_stated` (both readers agree the page does not say). A held field hides its award until an operator fixes it.
7. **Site hunt** (`hunt.py`, a separate worker step): for held or missing fields, search the funder's own site (documents → map → guided map → `/agent`), at most 6 pages per award, only on provenance-recognised domains; a value attaches only by an exact award-name match.

Nothing in `apps/` calls `read_page` or `hunt_card` yet. Storing and serving cards is **slice 3**, planned to delete Gen-1's vote.

### 4.3 Strategies and why

- **Two model families, closed questions per line, unanimity (Gen-1).** "Unanimity of one model filters noise, not bias"; open extraction gave a different quote set on every read. Serving on 2 of 3 was rejected because the target is 95–100% precision.
- **Tiered agreement.** Losing a real scholarship because two models argued over "grant vs subsidy" is the wrong failure direction.
- **Code finds and parses; models only point (Gen-2).** No model is asked to calculate, compare dates, count or write text. A dropped quote costs a decider call, never a wrong value.
- **Byte-exact quotes, no normalisation.**
- **Why Gen-2 exists:** Gen-1 served 2 of 69 written rows, and its errors were dominated by question definitions and two-model disagreement. The owner's slice-2 decisions moved the unit to an award read with its section, values to code, and readers to DeepSeek + Luna with Opus deciding, against a target of ≤ 1% wrong per shown field at ≤ $0.25 a page (`docs/superpowers/research/2026-10-12-slice2-owner-decisions.md`).

### 4.4 What we measured

| Date | What | Result | Source |
|---|---|---|---|
| 09-16 | Gen-1 on 497 EACEA leads (15 h 12 min) | 69 written, 424 blocked; **served 2**, unagreed 53, abstained 8, pointers 88. Top disputed fields: money form 26, route 25, nationality shape 22. A throughput figure, not precision | `docs/superpowers/2026-09-16-funding-reader-precision-run.md` |
| 09-22 | Hand read of the 32 unagreed rows | About two-thirds were reading errors on clear pages, one-third genuinely ambiguous | same |
| 09-23 | Bound on tiered agreement | At least 33 of 53 (≈62%) would become AGREED with a caveat (arithmetic, not a run) | same |
| 09-18 | Gen-1 over 58 funder hosts | 88 pages, 399 calls, 102 min: **2 served, neither from a funder**; ~$0.35 a host | master design §8.8 |
| 09-19 | Holder-axis positive control, 5 hosts | 10 pages, **0 served**, 10 unagreed | `docs/research/2026-09-19-holder-axis-gate.md` |
| 09-25/26 | Requirement reader | English: 51 of 58 typeable rules, no wrong cap; 13 of 30 pages measured (credit ran out) | `docs/superpowers/specs/2026-09-26-requirement-reader-addendum-design.md` §1 |
| 10-04/05 | Engine eval round 1 | 83 pages, 79 served; key 1,400 lines / 53 pages; $15.32. Jev ≥ 0.8: precision 0.973 / recall 0.66; Gemini alone 0.762 / 0.87; Flash 1.000 / 0.63 | `docs/superpowers/2026-10-04-engine-eval-round-1.md` |
| 10-05 | **Owner gold check, 114 facts** | **109/114 = 0.956** (deadlines 14/14, eligibility 66/70, money 29/30); 95% upper bound on error 0.090; all 5 errors were question definitions | same |
| 10-05 | Owner hand check, 40 hard facts | The model answer key itself was wrong far more than its audit suggested (Sonnet right 14, wrong 25) → every precision above is a ceiling | same |
| 10-05 | Hybrid extraction, 1,400 lines | DeepSeek V4.1 Flash cost **$0.080 for all 1,400 lines**; 765 of 769 quotes byte-exact. Requirements: code alone 7/50, with the model 28/50 | `docs/superpowers/2026-10-05-hybrid-extraction-measurement.md` |
| 10-05 | Code finders | 208/211 key dates; 14/14 deadline lines; 20 of 29 money lines carry no amount; slowest line 9 ms | `docs/superpowers/plans/2026-10-05-card-reader-1-finders.md` |
| ~10-12 | **Gen-2 spike, 211 owner-judged hard cards** | Pair → Opus precision **0.980**, recall **0.925**; Opus alone 0.980 / 0.932; about 8% of answers split; $0.01–0.02 a page. Site hunt on 15 pages found 6 of 29 missing fields; 19 of 23 misses sat on another official domain | `docs/superpowers/research/2026-10-12-slice2-owner-decisions.md` |
| 10-12 | DeepSeek host choice | Fireworks returned 429 on every call; inference-net/fp8 chosen | `config/settings/base.py` |

Owed: the 58-host re-run after tiered agreement, the first-read gate, the full cost run ("NOT run (owed)", `docs/superpowers/2026-09-26-funding-cost-run-owed.md`), the 30-card hand check, `funding_recall` (its known-answers file has only a header), owner round 2 (~250 values on ~35 pages), which must prove Gen-2's ≤ 1% target.

### 4.5 Models in use

| Job | Model | Why |
|---|---|---|
| Gen-1 readings | `gpt-5.6-luna` ×2 + `claude-sonnet-5` | A second family, because three readings of one model share its bias |
| Gen-2 readers | DeepSeek V4.1 Flash + GPT-6-luna (OpenRouter), decider Claude Opus 5.5 | Measured on the 211-card spike; "No Sonnet" |
| Page screen (D8), classification decisions | Jev (`typesafe/jev-1.13` via OpenRouter) | Cheap guardrail and classifier questions |
| Host classifier | `gpt-5.6-luna` | Frontier classifier; the Jev version is not built |
| Sweep sentences | DeepSeek V4.1 Flash | Won the 10-13 comparison on cost and noise |
| Transcripts, student documents | Azure Document Intelligence | Not used on web pages |

---

## 5. Trust: the provenance gate

### 5.1 How it works

1. Each catalogue programme carries the registrable domain of its evidence pages (`Program.evidence_domain`) and whether that is the institution's own host. A fake page naming TUM gets its own row, because the origin domain is part of the row's identity.
2. `provenance_check` (worker only) judges each (body, domain) pair: ROR (identity only), the country's official register, curated and funder lists, 16 government zones (gov.az, europa.eu, go.kr …), the mill list, one hop of structural links from a recognised parent ("vouch"), two content vetoes (a fee to release an award; a degree for payment) and the domain's registration date (RDAP).
3. **Decision, in order:** on the mill list → BLOCKED. A recognition whose bound domain equals this domain → RECOGNISED (register > curated list > funder list > government zone > vouched link), unless a veto hits (`veto_conflict`) or the domain was registered after we first bound it. Recognitions that don't bind → `no_domain_binding`. A veto with no recognition → BLOCKED. Otherwise UNCONFIRMED with the most specific reason.
4. When the gate is enforced (`PROVENANCE_GATE_ENFORCED`: off when unset in code, on by default in the deployment template), the candidate pool only takes programmes and awards whose domain is RECOGNISED; bodies still being checked are counted in the pack ("N still being checked").
5. Daily `provenance_recheck` (scheduled, enabled) re-checks due pairs, screens recognised ones yearly (RDAP + mill list, ≤ 500 a run), then sweeps published packs: BLOCKED items are removed, and a changed pack gets a new version with a note.

### 5.2 Strategies and why

- **Admit only on evidence an attacker cannot write.** A fake controls its own pages, so no model call sits on the admit path.
- **Content checks can only veto, and a veto on a recognised body never blocks**; vendor wording must not condemn a real university.
- **Absence is never BLOCKED.** A good scholarship at an unknown school must not be condemned by a data gap.
- **ROR proves identity, never legitimacy:** 7 of 13 Wikipedia-listed diploma mills are active ROR records.
- **A verdict is per (body, domain)** (esmt.org vs esmt.berlin). **No name match ever binds a body** ("The University of Law" was once paired with National Law University, Delhi).
- **ENIC-NARIC decides which register is official** for a country.

### 5.3 Registers loaded (correction to the audit)

The registers on `master` (`docs/research/provenance-sources.csv`):

- **United Kingdom:** OfS (England) and the Scottish Funding Council list (Wales and Northern Ireland have no source).
- **Germany:** Hochschulkompass (HRK).
- **South Korea:** the national university information service.
- **Türkiye:** YÖK state and foundation universities.

**Azerbaijan has no register.** It has a curated list (`az_heis`: 36 rows, built from search results; they count only after their origin is verified). Türkiye also has a curated list (`tr_heis`, 74 rows). Other curated sources: intergovernmental bodies, Azerbaijan's outbound government and bilateral schemes, Türkiye's bilateral schemes, national scholarship agencies; EACEA as a funder list. Every other country's institutions get UNCONFIRMED `no_register`.

**Not built:** DEQAR and WHED (the earlier safety-screen version was deleted; the code rule says not to revive it), ROR enumeration, TKTA / Azerbaijani degree recognition checks, the State Programme list. The mill list holds 6 reviewed domains.

### 5.4 What we measured

| Date | What | Result | Source |
|---|---|---|---|
| 09-26 | Mills in ROR | 7 of 13 are active ROR education records | `docs/superpowers/specs/2026-09-26-institution-provenance-gate-design.md` §2 |
| 09-26 | ENIC-NARIC "recognised institutions" section | Present on 53 of 56 country pages | same §5.1 |
| 09-26 | ROR domain vs website fields | Disagree on 344 records; 205 active records point at hosting platforms (wordpress.com 59 …) | same §5.2, §5.6 |
| 09-26 | RDAP registration dates | Returned for .com, .gov, .kr, .uk, .fr; none for .az, .de, .tr, ac.uk | same §5.5 |
| 09-26 | Korea open data | 1,995 rows, 1,715 with a homepage | `docs/superpowers/plans/2026-09-26-provenance-gate.md` |
| 09-27 | YÖK | 128 state + 74 foundation universities | spec §5.1 |
| 09-13 | Joint-programme name markers | 7/7 joint names caught, 15/15 plain names not; 19 of DEQAR's 9,030 institutions flagged (0.2%) | `apps/research/catalog.py` |
| 2022–26 (Wayback) | How often requirement pages change | 29 pages over 107.7 page-years: 0.85 changes a year; 66% around the cycle opening | spec §10 |

No recorded run of `provenance_check --all` over real data exists yet.

---

## 6. Freshness: is this year's call open?

`verify_due_cycles` checks each agreed award for the next two intakes, cheapest step first: our stored pages → crawl (≤ 15 pages) → Wayback → the register's cadence → one own-domain hop → Exa/Brave restricted to the funder's domain. Budget $0.40 an award, $10 a run. Check frequency: daily within 14 days of a deadline, weekly in season, otherwise monthly. The pass bar (`cycle_verify --truth`) is ≥ 0.95 precision on OPEN and UPCOMING with no contradicted row.

**Status:** the schedule is **disabled** (the worker has no Anthropic key, the gate was never run because its truth set has no rows, and the worker role cannot write cycle evidence to storage). Firecrawl page monitors exist as commands but have no schedule. Awards whose cycle is unverified are still eligible, deliberately, with a test that says so.

Schedules on: provenance recheck (daily), exchange rates (daily), reminders, application watch, mailbox sync, Europass canary, transcript resume. Off: fetch retries, cycle verification. Absent: erasure execution, monitors, area sweeps.

---

## 7. From catalogue to a student's pack

### 7.1 How it works

1. **Questionnaire submitted** (`apps/accounts/consultation.py`): a versioned profile snapshot and a recommendation run, sent to the worker. Inputs that drive search: target field, intake, nationality, teaching languages and evidence, allowed/excluded countries, duration, non-negotiables, application budget, funding dependency (mandatory / important / optional), weights. The strategy is not asked: mandatory funding → `FUNDING_FIRST`, otherwise `BALANCED`.
2. **Exchange rates:** the newest Central Bank of Azerbaijan table (AZN base), fetched daily.
3. **Candidate pool** (`apps/funding/pool.py`, 50 rows): programmes whose name contains the target field, minus excluded countries; served awards; only provenance-recognised bodies. The code calls this pool "interim"; selection by demand cell is meant to replace it.
4. **Facts** (`apps/funding/facts.py`): catalogue rows become pure facts. What the catalogue does not say, the facts do not say. Every fit dimension is a neutral 50 until fit scoring exists.
5. **Ten hard gates** (`apps/funding/evaluation.py`): teaching language; language evidence by the deadline; confirmed eligibility failure; deadline still viable; evidence confidence not LOW; non-negotiables; countries; nationality; duration; for mandatory funding, a current, verified route that applies. Award conditions use a small rule grammar (citizenship, grade, age … with IN / NOT_IN / ≥ / ≤ → satisfied, failed or undecidable; undecidable goes to review).
6. **Scoring:** academic, programme, career and affordability always, plus duration, research and mobility when set; weights renormalised. Affordability = (1 − gap / cost) × 100. **Balanced students need overall ≥ 80 and every dimension ≥ 60. Funding-first students have no fit bar; the gap orders them.**
7. **Money** (`apps/funding/affordability.py`, `fx.py`): costs normalised to the whole programme; only guaranteed money (`AUTOMATIC_ON_ADMISSION`) counts as coverage; selective awards are shown as *conditional savings*, never subtracted; repayable shares never count. Gap = max(cost − covered, 0). Conversions go through the base currency, rounded half-up to the cent; a programme in a currency we can't convert drops out alone.
8. **Pack** (`apps/funding/pack.py`): free-to-apply programmes, then paid ones while the application budget lasts (fee × 1.03 bank margin must fit; the budget is charged the fee). Programmes over budget stay in the pool and can appear later as "New for you". Awards are a separate list that never touches the budget. Each programme says whether to apply for the scholarship first or in parallel, based on the two deadlines. Trade-offs shown: closed routes (with the scheme's rule quoted), service bonds, "weaker fit than another recommended candidate".
9. **Publish** (`apps/research/services.py`): a pack version with one candidate per item, each carrying its evidence source URL; an item with no origin is skipped and a counsellor task opened. **No counsellor approval** before the student sees it. An empty pack becomes a counsellor task.
10. **What the student sees:** the pack page shows, per item, fit label, fee, funding gap ("not yet costed" when unknown), the claim, an **"Official source" link with its domain and last-checked date** (`templates/student/_candidate.html`), and add / reject / replace. The application board card uses the source URL only as the "Open programme page" button; the Consultation Report shows the claim and last-checked date but no link.

### 7.2 Strategies and why

- **Money math is deterministic Decimal code, never a model.**
- **An award is an application, not a discount** (owner, 2026-09-19): counting it would understate the gap by exactly the amount at risk.
- **Conditional savings are never coverage:** that would show every applicant the gap only winners will have.
- **An unknown fee is "not known", never 0.**
- **The neutral 50 is deliberate:** inventing a spread would manufacture a ranking; raising it to clear the bar would manufacture a pass. The fix is real fit scoring.
- **Never a silently short pack:** an empty or thin result says why.

### 7.3 What we measured, and what the code shows

| Date | What | Result | Source |
|---|---|---|---|
| 09-23 | Balanced student against the neutral 50 | Overall 64 against an 80/60 bar → every programme "eligible, below fit bar"; left standing deliberately | `tests/funding/test_spine.py`; `apps/funding/facts.py` |
| 08-20 | Phase-1 scorecard | Precision 1.0000, recall 0.8235 — on **synthetic data, not acceptance evidence** | `docs/validation/phase1-scorecard.md` |

Owed: the 5-student live gate for programme search (~$2) and the 3-student demand-cells gate (~$3).

Found by reading the code *(read from code; not yet confirmed by a run)*:
- Nothing outside tests writes programme cost rows (`CostComponent`), so catalogue programmes would show an unknown fee and land as free to apply.
- A mandatory-funding student passes the funding gate only for programmes with an automatic-on-admission route.
- `self_funding_capacity` is collected but not read by the evaluator.
- The empty-pack reason and the coverage sentence are never rendered to the student.
- The tap rebuilds the pack without exchange rates, which would take the "no exchange-rate table" path on a not-yet-published run.

---

## 8. Per-student search ("the tap")

### 8.1 How it works

On a finished questionnaire (only if `TAP_AUTOMATIC` is on; it is off) or by hand (`run_first_search --student <id>`):

1. **Wallet** per (student, intake): `SEARCH_WALLET_USD` = $100, $10 kept back for follow-ups, 2 wallets a year, at most 2 taps a day, a $200 daily ceiling per tenant.
2. **Catalogue first:** rebuild the pack from what is already known.
3. **Stage 1 search** (Exa and Brave only, 8 calls in parallel): queries are filled from fixed templates in three bins (programme, money, recency), one destination per query, in English and each destination's languages; no model writes per-student query text. A FIRST search runs coverage → local languages → deep (top 20% of queries re-run at 100 Exa results), stopping on a plateau (a batch of 10 that finds fewer than 2 new hosts) or when the wallet reaches its reserve; time limit 840 s per job, with up to 6 continuations. A FOLLOW_UP searches only what changed in the profile (≤ 30 queries, ≤ 60 provider calls, ≤ 180 s, ≤ half the wallet).
4. **Dedupe:** every hit is keyed by domain and checked against the register; only new hosts go on.
5. **Stage 2 read:** `bound_host_reader()` returns `NullSeams`, so **no new host is read**; the tap ends `STAGE2_UNAVAILABLE`. Queries are reused (programme queries for the whole cycle, money and recency for 30 days) only once their hosts have been read.
6. **Thin areas** queue a platform-paid area sweep ($5, 30-day cooldown), run by hand with `run_area_sweeps`.

### 8.2 Strategies and why

- **Catalogue first; dedupe is the convergence.** Each student's search adds to the shared catalogue, so later students pay less.
- **The budget is a wallet, not a rate.** Each charge commits on its own, so money spent is never unrecorded.
- **No model writes per-student query text; Tavily is never a tap provider** (it takes a perpetual licence over query text).

### 8.3 What we measured

| Date | What | Result | Source |
|---|---|---|---|
| 10-12 | One query naming 3 countries vs one query per country | 5 universities, all German vs 16 across the three → one destination per query | `apps/research/tap_query.py` |
| 10-14 | Round-robin over countries | 15 angles × 3 countries gave Sweden no query → rotation fixed | same |
| 10-15 | Follow-up cap | A save adding a country and an interest rendered 61 queries, 21 new, 7 fit → reused queries dropped before the cap | `apps/research/tap.py` |
| design | Priced estimate per tap | ≈ $0.59 search, ≈ $0.05 fetch, ≈ $0.06 reading; search ≈ 85% of a tap | master design §10.5 |

The design admits the open question the auditor raised: "the first student in a cell pays for everyone after them", and whose budget fills the catalogue is not decided.

---

## 9. Gates owed or failed

| Gate | State | Blocks |
|---|---|---|
| Enumerators gate | **FAILED** (09-26) | Register lists as denominators |
| Resolver blind hold-out | **FAILED** (09-18); fresh hold-out not run | Resolver writes |
| Classifier gate, second script | Not run; funds-students 47/61 on Latin script | Classifier at scale |
| ROR gate | Not run (API 403) | ROR enumeration |
| Cycle-verification gate | Not run (truth set empty) | Cycle schedule |
| Saturation gates A, B | Not run | Sweep stop rules at scale |
| 58-host re-run, first-read gate, cost run | Not run | Gen-1 economics |
| Owner round 2 (~250 values) | Not run | Gen-2 ≤ 1% target, slice 3 |
| 30-card hand check | Not run | First real pack |
| Programme-search and demand-cell live gates | Not run (~$2, ~$3) | The tap |

---

## 10. What we know is weak

- **Search recall is low by construction:** no search configuration exceeds 18% against a known key; coverage comes from query volume and registers. In Azerbaijan precision is 10–17% because the web is thin.
- **The reader has been the binding constraint:** discovering a funder has so far rarely produced a served card (2 of 58 hosts on Gen-1).
- **Shared model bias:** two model families can be wrong together, and the answer keys themselves were unreliable, so measured precisions are ceilings.
- **Curated lists are unverified** (built from search results); 144 rows are unbound.
- **Provenance covers four countries' registers;** everything else is UNCONFIRMED and, with the gate enforced, out of the pack.
- **A spam page on a hacked real university host passes the gate** (accepted risk).
- **RDAP gives no registration dates for .az, .de, .tr or ac.uk.**
- **Sweep sentences no longer name the study level,** so many found funders may not fund master's students until a level reader exists (which is why funder sweeps are switched off).
- **The Gen-2 hunt stays on the start page's own site** (`apps/research/card_funding/seek.py:211`), although the spike found 19 of 23 missing fields on another official domain. (An earlier version of this document said the hunt does not transliterate; that came from a stale plan. The award-name match folds names through `anyascii`, and "Bolashak" and "Болашак" both fold to "bolashak", checked on 2026-10-24.)
- **Docs and settings drift:** several spec numbers ($50 wallet, ≤ 40 calls, 1,800 s) no longer match the settings; the Gen-2 design spec itself lives on a branch, not on `master`.

---

## 11. Corrections to the audit's facts

From reading `master`:

- **Source URLs are shown** on the student's pack page (domain, link and last-checked date). They are missing only from the board card (used as a button) and the Consultation Report.
- **The registers are Germany, the United Kingdom (England and Scotland), South Korea and Türkiye.** Azerbaijan has only an unverified curated list, not a register.
- **The erasure job exists and is tested;** only its schedule is missing.
- **Fit fixed at 50, Gen-2 not serving, the tap's stage 2 reading nothing, and portal passwords in Secrets Manager** are all confirmed.

## 12. Owner decisions that stand

These stay as they are, whatever the audit recommended: social-media reading through a remote browser (designed, not built), the register whose terms allow personal use only, Baidu and Naver sweeps (measured, not built), employer-sponsorship sweeps, and paid proxies that get past a site's blocks (fetch rung 4, built).
