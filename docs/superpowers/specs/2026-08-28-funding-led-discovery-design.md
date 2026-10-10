# Funding-Led Discovery

## Goal

Discover funded master's programmes by following the money, not the course catalogue.

The engine shipped in the Phase 5 increment is correct and discovered nothing: 201 tests green,
every invariant verified, zero catalog rows
(`docs/superpowers/research/2026-08-28-discovery-shadow-run.md`). This design replaces the supplier
of leads, not the pipeline that consumes them.

**One of the three closed inputs turned out never to have been closed.** EACEA was recorded as
blocked on `robots.txt`, and it is -- but only on the detail pages the adapter was harvesting. The
same listing links straight to each consortium's own site, and against the live listing the corrected
adapter now yields **169 `PROGRAM` leads, every one claim-capable**. The blocker was an anchor
pattern in `seeds.py`, not a policy and not a defence. The other two remain closed: DAAD on
unverified terms, live search on a missing key whose provider forbids storage.

It also corrects a drift. The plan's §2.3 already settled that gems resolve by **entity expansion**
from a funded organisation, not by enumerating programmes — and `FUNDING_PATH_TERMS`
(`apps/research/search.py:118`) is already funding-led triage. A programme census finds
"Master of Chemistry, Strasbourg" and misses the EUR-funded Complex Systems Chemistry track on its
own subdomain. Grant databases find the track before the university publishes the page.

## Probe findings

Throwaway probes, 2026-08-28, against the live network from the dev host with an honest
`User-Agent`. Every number below is from execution, not documentation.

### Institution sitemaps are a weak spine

| Host | `/sitemap.xml` | Programme detail pages |
|---|---|---|
| `www.tum.de` | 1,755 URLs | **Yes** — ~180 at `/studium/studienangebot/detail/<slug>-master-of-science-msc` |
| `www.rwth-aachen.de` | 5,432 URLs | **No** — only the index page `Liste-Aktuelle-Studiengaenge` |
| `www.sorbonne-universite.fr` | 4,035 URLs | None under any path pattern tried |
| `www.unibo.it` | absent; robots declares `sitemap.xml.gz` | Blocked — gzip served as `application/octet-stream`, refused by `ALLOWED_CONTENT_TYPES` |
| `www.u-tokyo.ac.jp` | absent | — |

Two of five reachable. A widened multilingual path regex made it worse, not better: on Sorbonne it
matched **0** URLs where the existing `FUNDING_PATH_TERMS` matched 128, and on TUM it returned 451
URLs that were mostly student housing, mental-health support and parental-leave pages. Path shape is
a CMS artifact, not a semantic signal. No universal triage regex is written.

Sitemaps also cannot see a separate subdomain, which is where funded graduate schools live.

### National registries: one tier-1 source, and it is not the sitemap

`opintopolku.fi` publishes a 26,686-URL sitemap. Every URL is a React shell: **7,127 bytes of HTML
containing 11 characters of text** (`"Opintopolku"`). The sitemap is worthless directly.

The backend it is served from is a public JSON API, reachable by GET through the existing
`fetch_official_source` (`application/json` is already in `ALLOWED_CONTENT_TYPES`):

| Endpoint | Result |
|---|---|
| `/konfo-backend/search/koulutukset?lng=en&page=1&size=N&order=asc&sort=name` | `{"total": 7664}` |
| the same with `&koulutustyyppi=amk-ylempi,maisteri` | `{"total": 1285}` — master's level |
| `/konfo-backend/search/oppilaitokset?...` | `{"total": 592}` — institutions |
| `/konfo-backend/toteutus/{oid}` | 36,712 bytes of structured JSON per programme |

Hit fields: `oid`, `nimi`, `kuvaus` (English descriptions), `opintojenLaajuus`,
`opintojenLaajuusNumero`, `tutkintonimikkeet`, `toteutustenTarjoajat`, `koulutustyyppi`.

The generalisable rule is **not** "does the registry publish a sitemap". It is "is there a JSON API
behind the SPA". The sitemap's residual value is that it enumerates every `oid` to hydrate.

Every other registry probed:

| CC | Host | Result |
|---|---|---|
| NL | `www.studyinnl.org` | 1,947 URLs, marketing pages only. Not the registry — `studiekeuze123.nl` / DUO open data unprobed |
| HU | `studyinhungary.hu` | 296 URLs; 31 are *institution* pages, no programmes |
| KR | `www.studyinkorea.go.kr` | 78 URLs, site furniture only |
| FR | `www.campusfrance.org` | no `Sitemap:`, no `/sitemap.xml` |
| IT | `www.universitaly.it` | `robots.txt` 404 |
| JP | `www.studyinjapan.go.jp`, `www.jasso.go.jp` | `robots.txt` 404 |
| TR | `www.studyinturkiye.gov.tr` | `robots.txt` 404 |
| CN | `www.campuschina.org` | `robots.txt` 403 |

One of ten corridors solved outright, and Finland is not currently in `COUNTRY_NAMES`
(`apps/research/search.py`).

### Grant databases are largely open

| Source | `robots.txt` posture |
|---|---|
| `cordis.europa.eu` | Disallows only `.xml`/`.pdf`/`.rtf` export formats. Project pages open |
| `data.europa.eu` | Standard Drupal disallows (`/core/`, `/admin/`, …). Open |
| `anr.fr` | Disallows exactly `/en/funded-projects-and-impact/funded-projects/search-for-a-funded-project` — the **search results** path |
| `gepris.dfg.de` | **`Disallow: /`** — flat, whole-site refusal |

The ANR signature — search closed, detail open — is the third appearance of one pattern.
`www.hochschulkompass.de` disallows its eight search paths, including
`/en/degree-programmes/study-in-germany-search/advanced-degree-programme-search/*`, while leaving
detail pages open; EACEA disallows `/search/`. **The recurring obstacle in this domain is a closed
enumeration surface over open records, not bot defence.** The engine's answer is to bring its own
index: grant data for the EU, a permission ask for DE and for DFG.

### Certificate Transparency is unverified

`crt.sh` returned **HTTP 502** for the duration of the probe session, so subdomain enumeration was
never demonstrated end to end. It also resolves IPv6-first and this host has no IPv6 route, which
surfaced a real egress defect (below). The CT design below is therefore written but its source is
**unproven** — Increment 1 does not depend on it.

## Scope: worldwide, and country is an output

**Programme discovery is not scoped by country.** `DiscoveryQuery` carries `field`, `degree_level`
and `teaching_languages` and nothing geographic. This reverses
`2026-08-27-phase5-discovery-and-pack-optimizer-design.md:240`, whose
`manage.py discover --field <f> --country <CC>` made destination a required filter.

Three reasons, in ascending order of force.

1. **§7.2 constrains discovery by language, not geography** -- "Constrain automated discovery to
   English and the student's explicitly selected additional teaching languages." No country
   constraint appears anywhere in the discovery requirements.
2. **§7.1 already treats country as a reporting dimension** -- "Record catalog coverage and
   cache-hit rate per discipline and country so gaps are visible rather than inferred." A dimension
   you report coverage *over* cannot also be the filter that decides what gets covered.
3. **Destination is the dominant correlation axis in the portfolio model, so filtering on it makes
   the optimal portfolio unconstructible.** `2026-08-27-risk-aware-portfolio-design.md:157` lists
   destination country as a correlation grouping; the portfolio synthesis's decision 1 gives the
   mechanism -- one visa authority spans a destination. Ali & Shorrer's Theorem 1 (decision 2) is
   that under correlation the optimal portfolio contains **both a reach and a safety**, and the
   corridor synthesis shows those are usually in different countries: Türkiye Bursları is the most
   accessible funding in the eight-destination sample (75% bar, no language certificate, full
   package) against a destination with no post-study work route at all, while Germany and the UK
   are the reaches. A run filtered to one country never discovers the safety, and the resulting
   portfolio is maximally exposed to the single correlation the design exists to hedge.

Country is therefore an **output**: `extraction.py` returns `country_code`, catalog rows are keyed
on it, and §7.1's coverage report reads it. The student's location preference applies at ranking,
under §154's existing rule -- a non-negotiable constraint excludes, a weighted preference ranks.

**What the instrument sweep keeps.** `...pack-optimizer-design.md:288` sweeps *instruments* per
destination on a schedule, and that stays: a funding instrument is a country-level object, which is
why `DestinationPolicy` exists per country. The error corrected here was applying instrument scoping
to programme discovery. Two sweeps, two scopes.

**`--country` survives as an optional results filter** on `manage.py discover`, for a counselor
chasing one corridor or a targeted re-sweep after a `DestinationPolicy` change. It is applied to
rows after extraction and **is never passed to a `LeadSource`**, so it cannot narrow what is
discovered. A test asserts that no lead source receives it.

**What bounds a run instead.** Country was doing double duty as a scope limiter. `RunBudget`
(searches, fetches, extractions) is the real bound, and tier 0 is bounded by the size of the grant
dataset being read. Nothing further is needed.

## Design

Four tiers. Only the last writes catalog rows.

1. **Tier 0 — funding-led organisation discovery.** Grant databases yield organisations that hold
   money for graduate training, with the award year and amount. Every lead enters as
   `ECOSYSTEM_CLUE`, which `ResearchLead.from_url` already maps to `INTERNAL` /
   `can_support_claim=False`, and therefore writes nothing (§2.3).
2. **Tier 1 — registry JSON adapters.** Where a national registry exposes a JSON API, read it
   directly. Two qualify: **Korea** (KOGL, unblocked) and **Finland** (blocked on terms). A registry
   record is an `AGGREGATOR` lead:
   it routes research and seeds identity, and never supports a claim (§2.5).
3. **Tier 2 — entity expansion.** For each organisation from tier 0: enumerate its subdomains, read
   each host's sitemap, triage on `FUNDING_PATH_TERMS`, fetch the origin page. This is the existing
   `EntityExpansionSource` with its supplier replaced.
4. **Tier 3 — consultant task.** Anything blocked, unresolvable or out of budget becomes a
   `ConsultantResearchTask` (§2.6). A refusal is never a silence.

**Suppliers outside the EU -- resolved 2026-08-28, and better than feared.** This was recorded as
the design's largest open item: three of seven declared corridors with no supplier of any kind. The
research settles all three, differently:

| | Verdict | Consequence |
|---|---|---|
| **South Korea** | **Refuted** | A real programme register exists on data.go.kr under KOGL, with a degree-level field. A build target, not a gap |
| **Japan** | **Partly refuted** | **No programme register exists** -- confirmed, not filled with a weak source. MEXT publishes Japanese-only institution/faculty Excel; e-Stat is aggregate statistics behind a registered id. **KAKEN** covers the grant side under CC BY. Japan is tier-0-only, and the spec does not manufacture a registry it does not have |
| **China** | **Refuted** | MOE's programme catalogues and per-institution approval lists are enumerable as bulk PDF/Excel. No reuse licence is published either way; building against it was decided 2026-08-28 (see Access terms). The real costs are technical: the material is Chinese-only, adding an extraction burden, and some endpoints are WAF-blocked (`campuschina.org` returns HTTP 412, matching our own probe) |

**A cheaper route to China exists and is worth measuring first.** What the MOE catalogues supply is
*enumeration* -- which institutions offer which programmes. **ROR covers Chinese universities and is
CC0**: a probe on 2026-08-28 of `api.ror.org/organizations?filter=country.country_code:CN` returned
**5,708 Chinese organisations**, so the institution frame is available at no cost and with no terms
question, and tier 2's entity expansion reaches programme detail from each institution's own pages. That path also produces
the citable origin-page evidence the MOE catalogue would not. Build the MOE adapter if ROR plus
entity expansion proves thin for China; measure before paying the Chinese-language extraction cost.

**And the EU side is thinner than assumed**, for the reason recorded under `GrantDatabaseSource`:
CORDIS reaches forty countries but funds doctoral and postdoctoral research, not master's training,
so its breadth bought coverage of the wrong thing. `ROR` supplies the organisation frame for those
countries and everywhere else, free and with the website field CORDIS lacks.

The census frame (ETER/ROR → institution sitemaps) is **not built**. It reconstructs at roughly 40%
what tier 0 obtains by construction, and it structurally cannot reach a funded programme on its own
subdomain.

## Components

Each is a `LeadSource` (`apps/research/discovery.py:112`) unless stated, and plugs into
`default_sources` in `apps/research/pipeline.py` with no pipeline change.

**`GrantDatabaseSource`** — `apps/research/grants.py` (new). Reads funded-project records and yields
one `ECOSYSTEM_CLUE` lead per beneficiary organisation, carrying the organisation in
`LeadIdentity.institution_name` and the award year in `discovered_by`.

**Scope corrected 2026-08-28, and it is much narrower than this spec first claimed.** The correction
came from a single product observation: *we are looking for funded master's degrees, not PhDs or
postdocs.* Measured against that, most research-funding databases are off-mission:

| Source | Verdict |
|---|---|
| **ANR** (French EUR / IdEx graduate schools) | **On-mission and the only confirmed one.** An École Universitaire de Recherche bundles master's and doctoral tracks, which is precisely how Strasbourg's Master in Complex Systems Chemistry -- the example that motivated this entire design -- is funded. Open data on data.gouv.fr under Licence Ouverte |
| **German Exzellenzstrategie** graduate schools | On-mission in principle; DFG/GEPRIS is search-only with no API or bulk route |
| **CORDIS** | **Dropped.** Horizon has no master's-level instrument. Probed 2026-08-28: of 59,002 projects, "doctoral network" returns 853 and "graduate school" 111 -- and the first "graduate school" hit is a *doctoral* programme under HORIZON.1.2, which is Marie Skłodowska-Curie doctoral and postdoctoral training. The EU's actual master's instrument, Erasmus Mundus Joint Masters, is Erasmus+ and is not in CORDIS at all |
| **KAKEN** (Japan) | **Dropped.** Grants-in-Aid for Scientific Research funds researchers, not master's training |

CORDIS and KAKEN were promoted earlier today on *leverage* -- 56,000 organisations across forty
countries -- without checking whether those organisations were funded for master's training. They
are not. Their only residual value was as a "this university has research money" signal, and that is
redundant: `ROR` supplies the organisation frame for free, more widely, and with the website field
those sources lack.

**`OrganisationFrame`** — `apps/research/frame.py` (new), not a funding source. **ROR**, CC0, no
registration, probed 2026-08-28: **1,543** Japanese, **1,231** Chinese and **374** Korean education
organisations, each record carrying `links.website`, `domains` and `external_ids`. That website field
is what tier 2 needs and is exactly what the CORDIS search record lacks. It supplies *enumeration*
with no funding signal, which is the correct division: tier 0 says which organisations hold
master's-training money, the frame says which organisations exist. Where tier 0 is silent -- which
is now most of the world -- the frame is the supplier.

**`OrganisationResolver`** — `apps/research/identity.py` (new). Smaller than first specified, because
dropping CORDIS removed the PIC problem with it. What remains is real: ANR identifies French
participants by **SIREN or RNSR** and foreign ones by **GRID**, while registries speak ROR or a local
code (Dutch BRIN). ROR's `external_ids` carries GRID, so that join is available; SIREN and RNSR are
national codes ROR does not admit.

The resolver maps an organisation identifier from any tier-0 source onto a canonical handle, using
the **OpenAIRE Graph as the crosswalk hub** — it is CC BY, versioned on Zenodo, carries ROR and GRID
where mapped, and is a source we ingest anyway. The alternative surfaced by the research —
community-maintained CORDIS-to-ROR tables on GitHub — is explicitly **not** adopted: an unversioned
third-party mapping cannot sit inside an evidence chain that has to be cited and freshness-windowed.
Where the resolver cannot produce a handle, the lead becomes a `ConsultantResearchTask` rather than a
guess from a name string.

**`RegistrySource`** — `apps/research/registries.py` (new), one adapter shape, several
configurations. Finland's `konfo-backend` is the first (blocked on terms, above). Korea's
data.go.kr Open API is the second and closes a priority gap: dataset **#15139338** carries
school → college → department/major → **degree program** across 55,228 rows, with companion API
**#15107736** exposing bilingual institution names, under KOGL. Each yields `AGGREGATOR` leads
pointing at the institution's own page, never at the registry's own URL.

**Both Korean datasets were opened on 2026-08-28 without an account, and the portal is not where
either file lives.** This satisfies the "open one record first" rule in Verification, and it moves
the registration off the critical path — see the Prerequisites table.

- **#15139338 is a catalogue card, not a host.** Its 제공형태 is *기관자체에서 다운로드*: data.go.kr
  stores metadata and points at 대학알리미's own board, which serves
  `학교별 교육편제단위 정보_20241007기준.xlsx` to an anonymous GET. Confirmed fields: 조사년도,
  학교명, 학교코드, 대학구분, 본분교, (대학)지역, 단과대학명, 단과대학코드, 학교별학과코드,
  **학부과(전공)명**, 주야간구분, 학과특성, **학과상태**, **대계열분류 / 중계열분류 / 소계열분류**,
  수업연한, **학위과정**, (학과)소재지. Licence reads 이용허락범위 제한 없음, 무료. `학위과정` is
  the degree-level field this spec claimed on the research's word; it is now verified.
- **#15107736 is institution-level only and better than described.** Not "bilingual institution
  names" but 전국대학및전문대학정보표준데이터, seventeen fields — 학교명, 학교 영문명, 본분교구분명,
  대학구분명, 학교구분명, 설립형태구분명, 시도코드, 시도명, 소재지도로명주소, 소재지지번주소,
  도로명우편번호, 소재지우편번호, **홈페이지주소**, 대표전화번호, 대표팩스번호, 설립일자, 기준연도.
  Published by 한국대학교육협의회 under 교육기관의 정보공개에 관한 특례법, refreshed 2026-03-19.
  **`홈페이지주소` is the institution website field**, which is what tier 2 needs and what
  `OrganisationFrame` exists to get from ROR — so Korea's frame is available directly, current, with
  no ROR join. Its file download 404s anonymously; the Open API
  (`api.data.go.kr/openapi/tn_pubr_public_univ_info_api`) is live and returns
  `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` (code 30) without a key, so the key is the only gate.

**The Korean programme list carries closed departments, and this is a liveness constraint on the
adapter, not a footnote.** The dataset's own 기타 유의사항 states the rows are 교육편제단위 held for
statistical disclosure, **include 폐과 (abolished departments)**, and therefore "may differ from the
학부/과(전공) the university is actually recruiting for and operating"
(현재 대학에서 실제 모집‧운영하고 있는 학부/과(전공) 현황과 다를 수 있음). The file is also dated
20241007 against a stated 수시/자동갱신 cycle, so it lags. The same warning is repeated inside the
workbook, on sheet row 2, ahead of the header.

**The file was parsed on 2026-08-28 and the caveat is not a minor one — 49.1% of the rows are
dead.** 55,228 data rows over 1,880 institutions; `학과상태` carries twelve values which partition
cleanly into a live family (기존, 신설, 변경[신설], 분리[신설], 통합[신설], 변경[기존], 통합[기존],
분리[기존]) totalling 28,104, and a 폐지 family (폐지, 변경[폐지], 통합[폐지], 분리[폐지])
totalling **27,124**. An adapter that ignored the field would emit a catalog that is roughly half
abolished departments, each looking exactly as claim-capable as a live one.

**What survives the filter is still the largest single supplier in the build.** `학위과정` values
containing 석사: **19,118 rows, of which 12,169 are live, across 1,185 institutions.** For scale,
the shipped EACEA adapter yields 169 leads.

Two parsing constraints, both from the data rather than the documentation:

- **`학위과정` is a comma-separated multi-value string, not an enum** — eleven distinct raw values
  including `석사`, `석사, 박사`, `석사,박사, 석박사통합`, `학석사통합`, `전문기술석사` and
  `석박사통합`. Spacing after the comma is inconsistent between values. Split and match on
  substring; an equality test against `'석사'` silently drops the 8,117 rows where master's is
  bundled with a doctoral track.
- **`대학구분` separates 대학원 (19,497) and 대학원대학 (365) from 대학 and 전문대학**, so
  graduate-school rows are identifiable without relying on the degree field alone.

A registry row is consequently **evidence that a department once existed, not that it admits
students now** — which is exactly the failure this pipeline is built to avoid, since a lead that
looks claim-capable and is actually dead produces a catalog row no consultant can catch by reading
it. Two consequences, both binding on the Korea configuration:

1. Filter on `학과상태` (department status) and treat any non-active value as excluded, not as
   unknown. If the field's value set does not cleanly separate live from abolished, the whole
   dataset drops to `ECOSYSTEM_CLUE` and supports no claim.
2. Liveness is confirmed at the **origin page**, never from the registry row. This is what the
   existing `AGGREGATOR` hop already does; the caveat is why it may not be short-circuited for
   Korea on the grounds that the source is official. Official and current are different properties.

The Finnish configuration pages `/konfo-backend/search/koulutukset` with
`koulutustyyppi=amk-ylempi,maisteri` and reads the institution from `toteutustenTarjoajat`. It needs
`fetch_official_source` plus `json.loads` — **no new egress path and no new dependency** — and never
fetches the 11-character HTML shells.

**Enumeration ceilings are an adapter-design constraint, not an incidental.** They differ per source
and each forces slicing by date or key range rather than naive pagination: NSF caps a search at
**3,000 results, 25 per page**; NIH RePORTER caps the offset at **9,999**; Korea's grid download caps
at **50,000 rows**, with the Open API as the full-extract route. An adapter written against naive
`offset` will silently truncate.

**`CertificateTransparencySource`** — `apps/research/certlog.py` (new).
Given a registrable domain, queries the CT log JSON endpoint for `%.<domain>` and yields distinct
hostnames as `ECOSYSTEM_CLUE` leads. Its own `LeadSource`, per decision, not a step inside entity
expansion: it has a separate upstream, a separate failure mode and a separate access-terms question,
and entity expansion must keep working when CT is unavailable. A refusal, a timeout or a malformed
body is a dead end, not an error.

**`EntityExpansionSource`** — `apps/research/search.py:175` (modify). Today it constructs its
organisations from a `SearchSource`. Change it to accept any `LeadSource` as its organisation
supplier, defaulting to none. `SearchSource` remains one possible supplier; `GrantDatabaseSource`
becomes the default. No behaviour change to the sitemap or triage logic.

### Programme-scoped funding is invisible to path triage

**A defect, raised by the product owner 2026-08-29 and confirmed in the code.** Expanding an
institution finds funding that lives at a funding-shaped *URL*. It does not find funding that lives
in a *paragraph on a programme page* — and an award attached to one programme only, or restricted to
international applicants to that programme, is usually written exactly there.

`apps/research/search.py:205` triages by path substring against `FUNDING_PATH_TERMS`
(`scholarship`, `fellowship`, `funding`, `stipend`, `admission`, `graduate`, `doctoral`, `phd`) and
`continue`s on anything else. So a page at `/en/study/master-chemistry` whose body reads *"all
admitted international students receive a 50% tuition waiver"* is **never fetched at all** — not
fetched and rejected, never seen. This is not a tuning problem: the Probe findings above already
established that path shape is a CMS artifact rather than a semantic signal, and that widening the
regex made results worse, not better (0 matches against 128 on Sorbonne, and mostly housing and
parental-leave pages on TUM).

**The fix costs no extra fetch.** A programme origin page is already retrieved — that is how a
catalog row gets written and cited at all. Funding claims should be extracted from *that same
response*, alongside the programme claims, rather than depending on a separate funding-shaped URL
being discovered independently. Path triage keeps doing its job for the central scholarships pages;
it simply stops being the only route to a funding claim.

**The data model needs no change, and is stricter than the extraction currently is.**
`OpportunityScope` is GLOBAL / COUNTRY / INSTITUTION / PROGRAM, and
`funding_opportunity_scope_shape_valid` (`apps/funding/models.py`) is a database check constraint
admitting exactly one anchor per scope: GLOBAL carries no anchor, COUNTRY only `country_code`,
INSTITUTION only `institution`, PROGRAM only `program`. A programme-only award therefore *cannot* be
stored against the institution, and a university-wide award cannot be stored against one programme —
the database refuses both. `FundingOpportunity.programs` (M2M) carries an award scoped to a named
subset of programmes, and `BenefitRule.program` carries a benefit whose value varies by programme.

So the two failure modes this guards against are already unrepresentable in storage:

| Mis-attachment | Consequence if it were possible |
|---|---|
| Programme award stored as institution-wide | Every programme at that university advertises money the student cannot get |
| Institution-wide award stored against one programme | The student misses it on every other programme at the same university |

What remains an *extraction* obligation is deciding which one a page describes, and capturing the
`nationality rule` that separates an award open to internationals from one restricted to nationals.
Both are already in the extracted-claims set; neither is exercised by a source that never fetches
the page.

## Defects fixed

Three, all found by probe, all independently useful.

1. **Content-region hashing** — `apps/research/pipeline.py:221` digests `page.body`, the whole raw
   response. A CSRF token, a rotating news sidebar or a "last reviewed" footer flips the digest, so
   an unchanged programme page misses the `unchanged` short-circuit and pays the extraction cost
   every cycle. Replace with a digest over a normalised token stream from the content region,
   computed by a **stdlib heuristic** — an `html.parser` subclass modelled on `harvest.py`'s
   `_TextParser` that drops `script`, `style`, `nav`, `header`, `footer`, `aside` and `form`
   subtrees. No HTML-parsing dependency is added; the Phase 5 plan's "no new dependency" constraint
   holds. `persist_snapshot` keeps hashing the raw bytes: the evidence chain must digest what was
   actually retrieved.
2. **Shell detection floor** — `apps/research/egress.py:139` sets `_SHELL_MIN_BYTES = 20_000`, so
   `looks_unrendered` returns `False` for Opintopolku's 7,127-byte, 11-character shell. A page with
   nothing in it passes as rendered. Lower `_SHELL_MIN_BYTES` to 2,000, so the text test governs
   above a floor that excludes only redirect stubs and error pages.

   **Superseded in part, 2026-08-30.** The floor was right; the *text-ratio* test above it was not.
   Measured against seven live consortium pages, a 5% ratio called every one of them a JavaScript
   shell while all seven served 2,900–7,300 characters of ordinary prose — three of them at
   4.8–4.9%, decided by the threshold rather than by the page. The ratio is replaced by an absolute
   floor, `_MIN_VISIBLE_WORDS = 40`. See
   `docs/superpowers/research/2026-08-30-discovery-shadow-run-3.md` §1.
3. **No address-family fallback** — `apps/research/egress.py` takes `target.addresses[0]`
   unconditionally. An IPv6-first host is unreachable from a v4-only network even when an A record
   exists. Try the resolved addresses in order rather than only the first.

## Access terms

No adapter is written for a host whose terms are unverified. That rule stopped the DAAD adapter and
it holds here. Resolved 2026-08-28 by two research runs plus a direct fetch, filed as
`docs/superpowers/research/2026-08-28-worldwide-funding-sources-synthesis.md`:

| Source | Blocks | Status |
|---|---|---|
| CORDIS | `GrantDatabaseSource` (EU) | **RESOLVED — CC BY 4.0.** Commission Decision 2011/833/EU. Verified by fetching `cordis.europa.eu/about/legal` directly, not taken from the runs. Beneficiary-supplied *attachments* carry separate terms; project and organisation metadata does not |
| `data.europa.eu` | `GrantDatabaseSource` (EU) | **RESOLVED — CC BY 4.0** for editorial content, but **licensing varies per dataset** and must be read from each dataset page. For CORDIS bulk it matches CORDIS |
| ANR | `GrantDatabaseSource` (FR) | **RESOLVED — Licence Ouverte v2.0 (Etalab)**, published as open data on data.gouv.fr in XLSX, CSV and JSON. The site's own search path is never needed |
| OpenAIRE Graph | `GrantDatabaseSource`, join layer | **RESOLVED — CC BY 4.0**, Zenodo dumps |
| Opintopolku / `konfo-backend` | `RegistrySource` (FI) | **STILL BLOCKED.** No service-specific licence statement exists. One run inferred permission from the **EUPL on konfo-backend's source code**; that licenses the software, not the data it serves. CC BY 4.0 is the Finnish public-sector default under JHS 189, which is a basis for expecting a yes, not a statement of one |
| Korea data.go.kr | Korean registry adapter | **RESOLVED — KOGL**, attribution, free, "use permission range limitless" |
| KAKEN (Japan) | Japanese grant adapter | **RESOLVED** — terms stated as compatible with CC BY 4.0; requires a free CiNii application id |
| China MOE catalogues | Chinese registry adapter | **NO LICENCE PUBLISHED — build anyway, decided by the product owner 2026-08-28.** Two runs established that nothing is published either permitting or forbidding reuse. Silence is not refusal, and this is public government data, so the terms rule above does not apply: there are no terms to establish. Recorded as a decision rather than a finding |
| CT log endpoint service terms | `CertificateTransparencySource` | unverified; source also unreachable |

Three permission requests are outside engineering and block nothing here: **DAAD**
(International Programmes API), **HRK/Hochschulkompass** (~23,000 German programmes, search path
disallowed), and **DFG/GEPRIS** (`Disallow: /`).

**Blocked by technique — recorded, and retrieval for these is out of scope for this spec.** After
the `robots.txt` decision the only remaining obstacle at these sources is technical: a closed
enumeration surface, or an edge that refuses on its own. The product owner is handling retrieval
against them separately; this spec neither designs nor depends on it, and each entry below stays
listed so its *status* is not mistaken for a terms problem it is not.

| Source | Obstacle | What it holds |
|---|---|---|
| HRK/Hochschulkompass | No sitemap; search is the only index | ~23,000 German master's programmes |
| DFG/GEPRIS | Search-only, no API, no bulk route | German Exzellenzstrategie graduate schools |
| `erasmus-plus.ec.europa.eu` detail pages | Edge returns HTTP 403 server-side | Nothing needed — the listing already links to each consortium's own site, which is the better source |
| `campuschina.org` | WAF, HTTP 412 | CSC scheme pages |
| China MOE service endpoints | WAF on some paths; static PDF/Excel reachable | Programme catalogues, Chinese-only |

Germany is the corridor most constrained by enumeration and least by terms.

## Data model

One migration, for the content-region digest. `GrantDatabaseSource` and
`CertificateTransparencySource` emit `ECOSYSTEM_CLUE` leads, which write nothing;
`RegistrySource` emits `AGGREGATOR` leads, which the pipeline already hops to an origin page
before any row is written. Those need no schema change.

`OfficialSourceSnapshot.content_sha256` does (migration `funding/0014`). This spec first claimed the
digest could be a local variable in `run_discovery`; that was wrong. Comparing against a previous
fetch means the previous fetch's content digest has to be readable, and the only alternatives were an
S3 GET per candidate row per run or recomputing from stored bytes -- both pay object-store reads to
avoid an LLM call. A blank-defaulted column is cheaper than either.

`sha256` continues to hold the raw-body digest that the evidence chain cites, and the two are used
for different questions: `sha256` answers "are these the same bytes", `content_sha256` answers "is
this the same page". A content match is only ever a revalidation shortcut, never a snapshot to
reuse -- attaching new claims to a row whose stored bytes differ from what was extracted would cite
evidence that does not match the extraction.

## Coverage is measured by the optimizer, not counted

The phase gate (`risk-aware-portfolio-design.md`) stops an *unsupervised* catalog from reaching
students: a consultant reviews every pack. But a consultant can catch a wrong row and cannot conjure
a missing one, so a systematically thin corridor is not caught by review. Coverage needs its own
measure.

**That measure is not a count of programmes.** An earlier draft of this section proposed per-corridor
thresholds over three classes of option, flipped by a human. That was wrong on the decisive point:
**the student's fee budget is a parameter of the optimization**, so how much catalog a corridor needs
is not a property of the corridor. A student with a EUR 600 fee budget and one with EUR 100 need
different depth from the same catalog. `risk-aware-portfolio-design.md` §2.1 makes this explicit --
in the recursion the budget appears as `b - g_i` -- so any corridor-level constant answers a question
the optimizer already answers per student, with the parameter included and the answer better.

**The optimizer already emits the coverage signal, per student.** Two of its outputs are exactly
"this catalog could not serve this student", and both are required behaviour today:

| Signal | Required by | Meaning |
|---|---|---|
| No floor after every §7.5 widening | portfolio §7.4, §7.5 | Nothing in the catalog is a safety this student can secure |
| Unspent budget because the remainder buys only zeros | portfolio §2.1 | The catalog held nothing more worth this student's money |

Both are deterministic, both name the widening that would change the answer, and §2.1 forbids the
silent version of the second outright: *"Silent underspend is forbidden -- a student who sees EUR 150
unspent and no explanation cannot tell a careful decision from a broken one."*

**So coverage is the rate of those two outcomes, aggregated.** Per destination x discipline, over a
profile population: what fraction of students end with no floor, and what fraction with material
unspent budget. That is a computed number with the budget already inside it, not a judgment over
counts.

**Consequently there is no serve flag and no closed corridor.** The per-student path is already
honest -- a thin corridor produces a pack that states no floor was found and which widening would
produce one, which is *actionable* by the consultant in a way a silently short pack is not. Gating
service on top of that would suppress a correct, informative answer in favour of no answer.

**What the aggregate is for is aiming discovery.** A destination x discipline cell with a high
no-floor rate is where the catalog is thin, and therefore where the next discovery run should be
pointed. It is an operational instrument, not an admission gate. The phase gate already mandates the
place to run it before any student is exposed: *"Build and shadow-validate meanwhile"* -- the
shadow-validation population is where these rates are first measured.

**The three option classes survive as diagnosis, not criterion.** When a cell shows a high no-floor
rate, the useful decomposition is which kind of option is missing -- rule-based admission (rescues the
weak profile), tuition-funded or low-fee (rescues the student who cannot pay), or a funded route the
student can initiate (rescues the poor strong profile). That tells discovery what to go find. It
never decides whether a student is served.

**What is built:** an aggregation over outcomes the optimizer already produces -- no-floor rate and
underspend rate per destination x discipline -- plus the discipline taxonomy needed to group them.
No threshold logic, no flag, no gate. Discipline is a small fixed bucket set because the student's
field is deduced by the LLM from chat rather than chosen from an enum; both the student's field and
each source's subject facet map onto it.

**A candidate for that bucket set already exists in a source we are building anyway.** Korea's
#15139338 carries a three-level national classification — **대계열 / 중계열 / 소계열분류**
(broad / middle / narrow) — on every one of its 55,228 rows, and it arrives already mapped to real
programme rows, which is the part that is otherwise hand-built.

**Use the middle tier, not the top one.** The file was counted on 2026-08-28 and the top tier is too
coarse to group coverage rates: `대계열분류` has only **five** values (인문사회계열, 공학계열,
자연과학계열, 예체능계열, 의학계열) and they are badly unbalanced — 인문사회계열 alone takes 45% of
the live master's rows, lumping humanities with all of social science, while 의학계열 takes 1.3%.
Rates computed over five buckets that lopsided would hide exactly the thin cells this section exists
to find. `중계열분류` has **28** values (경영・경제, 사회과학, 전기・전자・컴퓨터, 교육, 건설,
기계, 언어・문학, 인문학, 보건, 화학・생명과학・환경, …) and is the right granularity for a small
fixed set.

Adopt it as the **starting point, not the definition**, and check two things first. Whether it is
destination-neutral enough to group a German or Brazilian programme without distortion — a national
classification reflects national provision, so the risk is a bucket set that silently fits Korea
better than anywhere else, biasing the coverage rates in the direction hardest to notice. And how to
handle **`N.C.E`** ("not classified elsewhere"), which is not a rare escape hatch: 2,793 rows
overall and 386 live master's rows land in it, so the taxonomy needs a real answer for unclassified
rather than a bucket that quietly absorbs them. Note also that the token is spelled `N.C.E` in the
middle tier and `N.C.E.` in the narrow one — normalise before joining.

If it does not survive those checks it still saves the work of inventing buckets from nothing.

**Deferred:** an ETER/ROR denominator. The two rates are already normalised by construction -- they
are fractions of students, not of institutions -- so a denominator of institutions answers a different
question. Add it only if the rates prove insufficient to aim discovery. Recorded, not built.

## Prerequisites — accounts and infrastructure to set up

None of these is engineering work, and each blocks something. Recorded here so they are not lost.

| # | Task | Blocks | Notes |
|---|---|---|---|
| 1 | **Role mailbox `data@tehsil.app`** (or similar) | tasks 2 and 3 | The domain is owned. Registering from a personal address ties production credentials to one individual's inbox and login |
| 2 | **`data.go.kr` account, then apply for dataset #15107736** | ~~Korea `RegistrySource`~~ — **improves it, does not block it** | Free under KOGL. Applications are **per-API and account-bound**, so migrating accounts later means re-applying per dataset — do this from the role mailbox first time. **Record the daily call cap granted**, which these portals commonly set low for development and raise on production approval; it changes how the increment is scheduled. **Downgraded from blocker 2026-08-28:** probing without an account showed the programme list is served anonymously by 대학알리미 and the institution metadata is readable from the portal, so the Korea configuration can be built and tested now. Registration buys the Open API — paged, refreshed 2026-03-19, and free of the 50,000-row grid ceiling — which is the right production route but not the entry ticket. Sign up on the Korean site; `/en` is a catalogue front and does not carry the 활용신청 flow |
| 3 | **CiNii Application ID** at `https://api.ci.nii.ac.jp/en/` | KAKEN adapter | Free. One id covers **both CiNii and KAKEN**. Trivial to redo, so address choice matters less here. Their rule: send `appid` on API calls only, never when linking a user's browser to a CiNii page |
| 4 | **Email Opetushallitus** re the `konfo-backend` licence | Finland `RegistrySource` | The only remaining terms block. Smaller ask since 2026-08-28, when P1-7.1 made source URLs internal-only: the request is about internal use, not redistribution |
| 5 | **DNS for `tehsil.app`, and a page at `/bot`** | nothing yet; rising risk | Probed 2026-08-28: the domain **does not resolve**. `apps/research/render.py:28` sends every source `+https://tehsil.app/bot` as the crawler's contact URL. With `robots.txt` no longer consulted, that URL is the only channel a source has to reach us before deciding to block — and a block lands on the one static IP every legitimate fetch also uses. The page needs: who the crawler is, what it collects, a contact address, and how to ask it to stop |
| 6 | **Swecris bearer token** | Swecris adapter, if built | `/v1/projects` returns HTTP 401, so the route is real and gated. Only needed if Sweden enters the build order |

## Increments

Reordered 2026-08-28. The terms research inverted the first two: what was increment 1 is the only
one still blocked, and what was increment 2 is now clear.

**Reordered again 2026-08-28**, twice: after dropping CORDIS and KAKEN, and again after the EACEA
adapter was corrected. Order now follows what can actually run — a source needing nobody's permission
outranks one waiting on a form, which outranks one waiting on an email.

1. **EACEA Erasmus Mundus, already shipped.** The corrected seed adapter harvests **169 consortium
   programme sites** from the live listing, all `PROGRAM`, all claim-capable. It needs **no
   registration, no email and no key** -- the only source in the build that needs nothing from
   anyone -- and the adapter is written, tested and merged. It is therefore the only source that can
   produce catalog rows today, and the shadow run against it is the next thing worth doing.
2. **`RegistrySource`, Korea configuration.** KOGL, degree-level field (`학위과정`, verified by
   inspection 2026-08-28), enumerable via the Open API. **No longer blocked** — the programme list
   downloads anonymously from 대학알리미 and the institution frame is readable without a key, so
   this can be built now and switched to the Open API when the account exists. Must implement the
   `학과상태` liveness filter above; the source carries abolished departments.
3. **`RegistrySource`, Finland configuration.** 1,285 master's programmes, structure verified by
   direct inspection -- the one source whose records we have actually opened. Gated on one email to
   Opetushallitus.
4. **`OrganisationFrame` over ROR, plus the `EntityExpansionSource` supplier change.** CC0, no
   registration, carries the website field entity expansion needs. This is what makes tier 2 work
   anywhere outside the registries, and it needs no permission from anyone.
5. **`GrantDatabaseSource`, ANR configuration**, plus `OrganisationResolver`. EUR and IdEx graduate
   schools -- the only confirmed master's-funding grant source, and the one the design's founding
   example came from.
6. `CertificateTransparencySource`. Gated on its terms check and on the source being reachable at all.
7. Coverage measurement -- unchanged, still last.

Increment 7 in full: aggregate the optimizer's existing no-floor and underspend outcomes per
destination x discipline. Ordered last because the rates are meaningless over an empty catalog, and
gated on nothing else. It must ship before shadow validation, so the first cohort's rates are
captured rather than reconstructed.

## Verification

- A shadow run writes catalog rows. The current baseline is zero; Increment 1 fails if it stays zero.
- Every `RegistrySource` configuration yields leads pointing at institution hosts, asserted by test
  to contain no registry URL of its own -- no `opintopolku.fi`, no `data.go.kr`.
- The content-region digest is stable across a page whose only change is a rotating token, and
  changes when the content region changes. Both asserted on fixtures.
- `looks_unrendered` returns `True` for the captured 7,127-byte Opintopolku shell, and `False` for a
  50 KB CMS page carrying a few hundred words inside heavy markup.
- The JSON schema `ExtractedClaims` generates carries no regex the Responses API refuses. A bare
  `Decimal` renders a lookaround pattern and the API rejects the entire request, which failed every
  extraction call this project made until 2026-08-30 (shadow run 3 §2). Asserted against the
  generated schema, because no canned-response fixture can see it.
- Every blocked source in a run produces a `ConsultantResearchTask`.
- No `LeadSource` receives a country: a run with `--country DE` and one without produce the same
  lead set, and differ only in the rows returned. Asserted directly, because this is the constraint
  most likely to be quietly reintroduced.
- A single run yields catalog rows for more than one country, given sources that span several.
- A student for whom the catalog holds no floor gets a pack stating that, and naming the widening that would produce one -- never a silently short pack (portfolio §7.4, §7.5).
- Coverage rates aggregate per destination x discipline from real optimizer outcomes, not from catalog counts.
- `OrganisationResolver` maps an ANR GRID or a registry code to a canonical handle, or opens a
  `ConsultantResearchTask`. It never falls back to matching on an organisation name string, which is
  the failure mode that would silently attach a grant to the wrong institution.
- Every adapter is asserted against its source's enumeration ceiling: a fixture proving it slices
  rather than paginating past Korea's 50,000-row grid limit or any cap a later source imposes.
- No source enters the build order without at least one record having been opened and its fields
  recorded. CORDIS was promoted to increment 1 on a total count alone, and inspecting a record showed
  it carried neither an organisation nor a master's-level instrument.

## Retrieval policy: `robots.txt` and access terms are treated differently

**Decided by the product owner, 2026-08-28.** `robots.txt` is no longer treated as a constraint on
retrieval. A `Disallow` does not make a source unusable, and the engine does not consult robots files
to decide what to fetch.

**Published access terms remain binding.** The rule in the Access terms section is unchanged: no
adapter is written for a host whose terms we cannot establish. The distinction is deliberate --
`robots.txt` is a convention addressed to crawlers, while terms of service are an agreement about
use and re-publication, and this product re-publishes what it retrieves as cited evidence. Treating
the two differently is a position, not an oversight, and is recorded here so a later reader does not
read one of them as a mistake.

**What this changes.**

- Sources we were declining to fetch become fetchable. **This is narrower than it first appears, and
  EACEA is the counter-example.** Re-probed 2026-08-28 after this decision: `erasmus-plus.ec.europa.eu`
  detail pages still return **HTTP 403**, because *their edge* enforces robots server-side and returns
  the refusal itself. We were never the party enforcing it there. A policy of not consulting
  `robots.txt` only unblocks sources that relied on our compliance; it does nothing against a server
  that refuses on its own. Getting those detail pages would require browser impersonation, which
  remains in Not built.

  **And it turned out not to matter.** The detail pages were never needed: the catalogue *listing* is
  unaffected and links straight to each consortium's own website, which is the better source anyway
  because a catalogue detail page is an `AGGREGATOR` that may not support a claim while the
  programme's own site is the origin. The 403 was guarding a road we had no reason to take. Worth
  generalising: **before treating a refusal as a blocker, check whether the data is reachable by
  another route on the same host** -- three of the four sources examined this session published
  what we wanted somewhere other than the surface that refused us.
- The constraint that actually limits discovery becomes **technical**: whether a source blocks
  automated requests outright, whether its records can be enumerated at all, and whether rate limits
  permit useful volume. A closed enumeration surface (`hochschulkompass.de` has no sitemap and its
  search is its only index) is now the real obstacle where a `Disallow` used to be.
- **Attribution is a live operational risk.** Production egress is one static declared IP with an
  honest User-Agent, which is what makes snapshots reproducible and geo-stable. That same property
  makes retrieval against a stated `Disallow` trivially attributable, and a resulting block would
  land on the address every legitimate origin fetch also uses. This is a cost to weigh per source,
  not a reason the policy is wrong -- but it is why the policy does not imply crawling aggressively.
- Citations may now include pages retrieved contrary to a publisher's stated preference. The evidence
  chain records `final_url`, timestamps and version ids unchanged; what changes is that a reader of a
  citation cannot infer the publisher consented to its retrieval.

**Everything else in Not built is unaffected**, because each of those lost on engineering merit
rather than on policy -- rotating exit IPs corrupt geo-varying data and break snapshot
reproducibility; evasion turns clear refusals into plausible 200s full of garbage; a CAPTCHA marks an
aggregator surface whose data may not support a claim regardless. Those arguments do not depend on
`robots.txt` and are unchanged by this decision.

## Opportunity aggregators as tip-offs — decisions, 2026-08-29

Brainstormed after the product owner found a Korea-to-Azerbaijan scholarship on `edumap.az` that no
source in this spec would have surfaced. **The technical design is deliberately deferred** to a
whole-system session; what follows is the decision record that session starts from.

**This is not the "aggregator scraping as a discovery spine" that Not built rejects.** That entry
turns on aggregator data being unable to support a claim, which is still true and is not contested
here. A tip-off is a different proposal: the aggregator supplies a *lead*, never evidence, and never
appears in the evidence chain.

**Origin-side aggregators index the two families nothing else does.** Every host in
`CATALOGUE_DOMAINS` today is destination-side — DAAD lists German programmes, `studyinkorea.go.kr`
lists Korean ones. `edumap.az` is the other kind: a feed of opportunities *available to
Azerbaijanis*, curated by someone whose job is watching for them. Nationality-keyed and home-origin
outbound schemes have no index anywhere, and an origin-side aggregator is the closest thing to one.

| Decision | |
|---|---|
| **Scope** | Both origin- and destination-side, **origin-side first**. The destination side largely duplicates registries and grant databases we already hold; the origin side is where we have nothing |
| **Social hosts** | **Tip-off only** — still true, and "not fetched automatically" is **superseded 2026-09-24**: they are fetched, through Browser Use, and still only ever hand over a name and a link. See the master design §6.4 |
| **Why** | ~~Meta's and X's terms explicitly forbid automated collection...~~ **The legal premise moved, not the reasoning** (owner's counsel, 2026-09-24). The terms still say what they said; the advice is that reading public pages through that vendor is available to this company. Tip-off-only survives on its own merits, which were never about the terms: a third party's paraphrase cannot support a claim |
| **An official body's own post is still legitimate** | If the posting page is an embassy's or ministry's own account, the opportunity is real and is **never discarded** for lack of a website. It routes to a `ConsultantResearchTask`, and a person confirms it. **A counselor reading a Facebook post is not automated collection** — the terms constraint binds the crawler, not human eyes |
| **Evidence chain** | The aggregator never enters it. We take an outbound URL, verify independently against the official source, and cite that |

**A host-keyed social rule cannot express the distinction, and that is a latent defect.**
`domains.py` excludes `facebook.com`, `instagram.com`, `x.com`, `linkedin.com`, `youtube.com` and
`bsky.app` wholesale, which is right for the case it was built for — the social row in a catalogue
page's footer, added after an EACEA harvest pulled in `bsky.app/profile/ec.europa.eu`. It is wrong
for an embassy's own announcement. Both live on the same host, so a host-keyed rule cannot separate
navigational chrome from primary publication.

If that distinction is ever needed in code, the shape is **attestation, not allow-listing**: an
official domain we already trust linking to its own social account is what makes that account
official, and an unattested account claiming to be an embassy stays noise. That solves impersonation,
which is the real hazard. It is recorded, not built — the tip-off decision above means it is not
needed yet.

**Approach ranking, for the design session:**

1. **The human channel.** Counselors browse these sites already; an inbound `ConsultantResearchTask`
   gives what they notice somewhere to go. Days of work, no terms exposure. **This is already
   happening un-instrumented** — the `edumap.az` find had nowhere to land except a chat message.
2. **A `TipOffSource`**, one config per aggregator, structurally identical to `HtmlCatalogue`: harvest
   a listing, follow outbound links, drop the ones that lead to another aggregator. EACEA proved the
   shape. Each new aggregator is config, not code.
3. **Aggregators as a search seed** rather than a fetch target — scheme names in, live search out.
   Parked behind the live-search dependency.

**One terms question generalises and should be resolved once.** Aggregators are commercial and
usually state no reuse terms, which would normally stop an adapter under this spec's own rule. But
retaining *only an outbound URL*, with none of their content, is a much lighter act than the
re-publication that rule exists to govern — and it is the same question
`PROMPT-live-search-provider.md` now leads with. One answer covers both.

**This is the same problem as new-opportunity detection, seen from the other end.** *"How do we spot
an opportunity nothing indexes?"* and *"should we harvest origin-side aggregators?"* are one
question: **how does something reach us that no index contains.** Every other supplier in this spec
walks an index and is structurally blind to what is not in one. The two should therefore be designed
together, not separately, and `PROMPT-new-opportunity-surfaces.md` researches them as one — which
aggregators exist per country, where a scheme is published *first*, and whether any of those
surfaces can be watched by machine.

**Two numbers from that run govern the design and are not yet known.** The
announcement-to-deadline window decides sweep cadence: if schemes typically run three weeks from
announcement to deadline, a monthly sweep misses most of them and cadence becomes the dominant
constraint; if the typical window is four months, the whole watch problem is smaller than assumed.
The announcement-to-indexing lag decides whether watching is needed at all, or whether waiting for a
scheme to reach a stable index is fast enough. **Do not settle the technical design before those two
numbers exist** — they determine whether this is a feed reader, a crawl schedule, or a staffed human
channel.

## Not built

Residential proxy pools, CAPTCHA-solving services, stealth browser fingerprinting, unrestricted
recursive spiders, search-engine result scraping, DNS brute-force subdomain enumeration, and
aggregator scraping as a discovery spine.

Each was evaluated on technical merit before any rule was considered, and lost on merit: rotating
exit IPs corrupt geo-varying tuition and eligibility data and make a snapshot unreproducible, which
is fatal for a product selling citable evidence; evasion converts clear refusals into plausible
200-with-garbage, and this project has already misdiagnosed one source that way; a CAPTCHA marks an
aggregator surface, whose data §2.5 bars from supporting a claim; and rendered pages over residential
bandwidth cost roughly $0.02–0.05 each against effectively zero for material that is mostly served to
a plain GET.
