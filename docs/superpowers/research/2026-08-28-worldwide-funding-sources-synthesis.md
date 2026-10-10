# Worldwide funding sources — synthesis and design consequences

**Date:** 2026-08-28. **Inputs:** two independent deep-research runs of the same prompt, filed as
`2026-08-28-worldwide-funding-sources-review-1.md` (better sourced on licences: quotes operative
clauses, labels its own unverified items, found OpenAIRE and 360Giving) and `-review-2.md` (deeper on
API mechanics: pagination ceilings, endpoint paths; found Swecris and NTIS, which run 1 missed).

**What it answers:** the tier-0 supplier gap outside the EU, the four access-terms questions blocking
increments 1 and 2, and whether a grant record can be resolved to an institution at all.

---

## 1. The finding that changes the design most

**Tier 0's supply problem is solved by two supranational sources, and neither is national.**

- **CORDIS** — bulk XML/CSV/JSON on data.europa.eu, CC BY 4.0, no auth. Over **56,000 unique
  participating organisations** across all Framework Programmes, each carrying an **EU PIC**
  identifier and country. One adapter, roughly forty countries.
- **OpenAIRE Graph** — CC BY 4.0 Zenodo dumps aggregating **368 funders and ~4 million grants**
  worldwide, with organisation records carrying ROR/GRID where mapped.

Run 1 found both. **Run 2 does not mention OpenAIRE at all**, which is the single largest asymmetry
between the runs.

**But the prompt's decisive question — can a grant record be resolved to an institution? — has a
worse answer than expected.** Records *do* carry a resolvable identifier. It is the wrong one:

> ROR's schema policy mandates only globally unique persistent identifiers, so **PIC codes are
> purposefully excluded** from the ROR `external_ids` payload. (run 2, citing ROR's own mapping docs)

Run 1 reaches the same conclusion independently: *"There is no published PIC↔ROR mapping."* So
CORDIS hands tier 2 a PIC, national registries speak ROR or a local code (Dutch BRIN, French
SIREN/RNSR), and **nothing official joins them**. This is the central integration risk and it was
invisible before this research.

The two runs propose different bridges, and the choice matters:

| Bridge | Proposed by | Assessment |
|---|---|---|
| **OpenAIRE Graph as the join layer** | run 1 | **Adopt.** CC BY, versioned on Zenodo, carries ROR/GRID, and is a source we would ingest anyway |
| Community-maintained CORDIS→ROR tables on GitHub | run 2 | **Fallback only.** An unversioned third-party mapping sitting inside the evidence chain is a dependency we cannot cite or freshness-window |

---

## 2. Part A — three of four resolved, and the fourth still blocks increment 1

**CORDIS — resolved, and verified directly this session.** A live fetch of
`https://cordis.europa.eu/about/legal` returns the operative text both runs quote: the Commission's
reuse policy is implemented by **Commission Decision 2011/833/EU**, and *"the reuse of the editorial
content on this website owned by the EU is authorized under the Creative Commons Attribution 4.0
International (CC BY 4.0) licence."* Retrieval and storage permitted. One caveat, quoted by run 1:
*"Materials provided by beneficiaries receiving EU funding may only be used according to the terms
and conditions applicable to the respective grant"* — that governs beneficiary-supplied attachments,
not project and organisation metadata.

**data.europa.eu — resolved.** Editorial content CC BY 4.0; **licensing varies per dataset** and must
be read from each dataset page. For CORDIS bulk downloads it matches CORDIS itself. Both runs agree.

**ANR — resolved, and better than expected.** The data is separately published as open data on
data.gouv.fr under **Licence Ouverte v2.0 (Etalab)**, in XLSX, CSV *and* JSON, covering 28,000+ Plan
d'action projects and 1,450+ France 2030/PIA projects, 2005–2024. Run 1 quotes the identifier scheme:
*"Les participants français sont identifiés par leur numéro SIREN ou leur numéro RNSR… et les
participants étrangers sont identifiés par leur numéro GRID."* We never need the site's search path.

**Opintopolku — NOT resolved, and this still gates increment 1.** Both runs agree no
service-specific licence statement exists. They disagree on what follows, and run 2 is wrong:

- Run 1: no dataset-specific licence found; the Finnish public-sector default is CC BY 4.0 under
  JHS 189; verdict *"storage almost certainly permitted but NOT confirmed by a service-specific
  statement."*
- Run 2: the konfo-backend **source code** is under the EUPL and an architecture wiki says open data
  is provided, therefore *"automated retrieval and storage are fully permitted."*

**Position: run 1.** Run 2 makes a category error — the EUPL licenses the *software*, not the *data*
it serves, and an internal architecture wiki is not a licence grant. Under this project's rule that
no adapter is written for a source whose terms are unestablished, Opintopolku remains blocked. The
resolution is a one-line email to Opetushallitus, not an inference.

---

## 3. The three-country gap: one refuted, one partly, one confirmed

| Country | Verdict | Detail |
|---|---|---|
| **Korea** | **REFUTED** | A real programme register exists: data.go.kr dataset **#15139338**, an XLSX of **55,228 rows** carrying school → college → department/major → **degree program**, under **KOGL** (attribution, free, "use permission range limitless"), legal basis Higher Education Act art. 6. Companion Open API **#15107736** with bilingual institution names. Grid downloads are capped at 50,000 rows — the API is the full-extract route |
| **Japan** | **PARTLY REFUTED** | **No programme register exists** — confirmed, not papered over. MEXT publishes only Japanese-only institution/faculty Excel directories, and e-Stat is aggregate statistics behind a registered app id. But **KAKEN** is fully usable on the grant side: OpenSearch API, free CiNii app id, records in English and Japanese, and terms *"compatible with the Creative Commons License Attribution 4.0 International"* |
| **China** | **REFUTED for the registry, blocked on terms** | MOE publishes enumerable programme artifacts — the annual undergraduate 专业目录, the per-institution 专业备案和审批结果, and the graduate 学位授权审核结果 — as bulk PDF/Excel. But **no reuse licence is published**, the material is Chinese-only, and some endpoints are WAF-blocked (`campuschina.org` returns HTTP 412, which our own probe recorded independently) |

So the "no supplier of any kind" claim in the prompt is **refuted for Korea, half-refuted for Japan,
and refuted-with-conditions for China.** Only Japan's *registry* side remains genuinely empty.

---

## 4. Where the runs conflict

| # | Question | Run 1 | Run 2 | Position |
|---|---|---|---|---|
| 1 | Opintopolku licence | No service-specific licence; CC BY assumed via JHS 189; residual gap | EUPL + open-data mandate ⇒ fully permitted | **Run 1.** EUPL licenses code, not data (§2) |
| 2 | UKRI GtR endpoint and licence | `gtr.ukri.org/gtr/api/`, OGL **v2.0** | `gtr.ukri.org/api/projects`, migrated June 2024, OGL **3.0** | **Unresolved.** Both paths returned **HTTP 502** on probe — the service was down, so neither is disproved. Probe again before encoding |
| 3 | Italy | MUR "Offerta formativa" open data at `dati-ustat.mur.gov.it`, bulk 2001–2024 | Legacy `offf.miur.it`, no modern API, blocked | **Unresolved, and run 2 is not stale as first assumed.** Our probe: `offf.miur.it` **responds** and redirects to a live search form; `dati-ustat.mur.gov.it` **timed out**. Both need re-probing |
| 4 | Korea grant side | NRF has no machine-readable feed | NTIS via data.go.kr, needs a registered key; suggests an **MCP wrapper to bypass the key requirement** | **Run 1 on the finding; reject run 2's method.** Wrapping a portal to avoid API-key registration circumvents an access control — different in kind from ignoring a `robots.txt` convention — and is unnecessary, because data.go.kr keys are free. **Register the key** |
| 5 | China grant side | Not covered | Undocumented endpoint `kd.nsfc.gov.cn/baseQuery/supportQuery`, explicitly labelled a hypothesis | **Treat as a hypothesis**, as run 2 does. Probe before it enters any plan |
| 6 | PIC↔ROR | No published mapping; OpenAIRE and ROR are the practical bridges | ROR excludes PIC by policy; use community GitHub crosswalks | **Agree on substance; run 2 supplies the reason.** Adopt OpenAIRE, not GitHub tables (§1) |
| 7 | Coverage asymmetry | Found OpenAIRE, 360Giving; left SNSF/SweCRIS/NWO/TÜBİTAK/NKFIH explicitly **UNVERIFIED** ("search budget exhausted") | Found Swecris and NTIS in detail; **never mentions OpenAIRE** | **Complementary.** Run 1's self-labelled gap is exactly what run 2 filled. Run 1's disclosure of its own limit is the better research practice |

---

## 5. Verified directly this session, not taken on trust

- **CORDIS legal page fetched.** Decision 2011/833/EU and the CC BY 4.0 clause confirmed verbatim.
- **UKRI GtR — both disputed paths returned HTTP 502.** Conflict 2 stands open; the service, not the
  claim, was unavailable.
- **`offf.miur.it` is live** and redirects to a search form; **`dati-ustat.mur.gov.it` timed out.**
  Conflict 3 stands open, and an early lean toward run 1 was premature.
- **`swecris-api.vr.se` responds**, but the three plausible OpenAPI spec paths all returned 404 —
  run 2's OAS3 claim is host-confirmed and spec-unconfirmed.

---

## 6. Design consequences

| # | Consequence | Basis |
|---|---|---|
| 1 | **Build CORDIS bulk first.** One adapter, ~40 countries, 56,000+ PIC-identified organisations, CC BY 4.0, verified terms | §1, §2 |
| 2 | **Adopt the OpenAIRE Graph as the identifier join layer**, not merely as a source. Nothing else bridges PIC to ROR, and the alternative is an uncitable third-party table | §1 |
| 3 | **Increment 1 stays blocked on one email.** Opintopolku's terms are unresolved; the fix is a request to Opetushallitus, and it is the cheapest unblock in the project | §2 |
| 4 | **Korea moves from "no supplier" to a build target** — KOGL-licensed, degree-level, enumerable via Open API | §3 |
| 5 | **Japan is tier-0-only.** KAKEN on the grant side; no registry to adapt. Do not manufacture one from MEXT Excel | §3 |
| 6 | **China needs a terms decision before code.** The registry is enumerable; the licence is absent. This is a decision to take, not a fact to find | §3 |
| 7 | **Adapter design must account for enumeration ceilings**, which differ per source and are not incidental: NSF caps a search at **3,000 results, 25 per page**; NIH RePORTER caps the offset at **9,999** with 10,000-record batches; Korea's grid download caps at **50,000 rows**. Each forces slicing by date or key range rather than naive pagination | run 2 §Part B, run 1 §Korea |
| 8 | **Home-origin government schemes have no index anywhere on earth.** Both runs state it independently. This confirms, empirically, that origin-side scheme knowledge must come from the tenant at onboarding rather than from discovery | run 1 §Part D, run 2 §Part D(b) |
| 9 | **Corporate and foundation schemes have no scheme-level directory either.** 360Giving (open, attribution, funder + recipient) is the one authoritative open source, but it publishes **grant history, not a catalogue of schemes** — it seeds the family, it does not solve it | run 1 §Part D |
| 10 | **The Netherlands correction is confirmed.** The register is **RIO** (successor to CROHO), via DUO's `onderwijsdata.duo.nl` bulk files and the OOAPI standard — not `studyinnl.org`, and `studiekeuze123.nl` is a downstream consumer. Our own probe of studyinnl.org found only marketing pages | both runs, and the 2026-08-28 probe |
| 11 | **Nomination-gating is confirmed for the largest foundation schemes** — Mastercard Foundation Scholars (nominated via partner universities) and Rotary Global Grants (nominated via clubs) — so neither can ever be a floor under portfolio §7.4 | run 1 §Part D |

---

## 7. Probe results, 2026-08-28 — every conflict resolved

Run after the synthesis was written, through the project's own egress with an honest User-Agent.

**Build-order sources:**

| Target | Result |
|---|---|
| CORDIS search API | **Live JSON, and better than the bulk route the runs described.** `cordis.europa.eu/api/search/results?q=contenttype='project'&format=json` returns `{"total": 59002}`. A queryable API means incremental sync rather than whole-dump reprocessing |
| OpenAIRE Graph API | **Live JSON** at `api.openaire.eu/search/projects?format=json` |
| OpenAIRE Zenodo dumps | **Discoverable** via the Zenodo records API |
| Korea `data.go.kr` | **HTTP 403 with a placeholder key** — live and enforcing auth, not down. A free key registration is a prerequisite task |
| KAKEN | **HTTP 403** without a CiNii application id — same shape, same prerequisite |
| **ROR, filtered to China** | **5,708 Chinese organisations** returned from one call to `api.ror.org/organizations?filter=country.country_code:CN`. The CC0 alternative to the MOE catalogues is not theoretical |

**Conflicts, now settled:**

| # | Question | Resolution |
|---|---|---|
| 2 | UKRI GtR path | **Run 2 is right.** `gtr.ukri.org/api/projects` returns 387 KB of XML; run 1's `/gtr/api/` path returns **HTTP 400**. The default representation is XML, so the adapter must set an Accept header for JSON |
| 3 | Italy | **Run 2 is right on reachability.** `dati-ustat.mur.gov.it` timed out on two attempts at different times — treat as unreachable from our egress, possibly geo-restricted rather than dead. `offf.miur.it` responds with 45 KB of HTML. Italy is a search-form-only source either way |
| — | Swecris | **Path shape confirmed, auth required.** `/v1/projects` returns **HTTP 401**, not 404, so run 2's route is real and needs the bearer token. The OpenAPI spec paths all 404 |

**Unverified tail:**

| Source | Result |
|---|---|
| SNSF `data.snf.ch` | Live HTML; needs a deeper probe for its API |
| NWO | **HTTP 403** — actively blocking |
| TÜBİTAK, NKFIH | Live HTML; no API surface established |
| **China NSFC** `kd.nsfc.gov.cn` | **Refused at DNS/address validation** — not reachable from our egress at all. Run 2's undocumented-endpoint hypothesis cannot be tested from here and stays a hypothesis |

**Still open, and not a probe:** the Opintopolku licence, which needs an email to Opetushallitus.
Note this became a smaller ask on 2026-08-28, when P1-7.1 was amended to make source URLs
internal-only: the request is now about internal use rather than redistribution.
