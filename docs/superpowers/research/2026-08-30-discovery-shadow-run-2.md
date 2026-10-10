# Discovery shadow run 2 — the first run against an open route

Run 2026-08-30 from the dev host: local Postgres (`tehsil`), the real evidence bucket
`tehsil-evidence-367842306577` in eu-central-1, real OpenAI key, **`SEARCH_API_KEY` deliberately
unset** so only the seed catalogue ran and nothing touched the live-search path.

```
manage.py discover --field any --country DE --tenant <agency> --max-leads 5
→ leads=5 written=0 unchanged=0 blocked=5 degraded=none
```

Zero catalog rows again — but for three understood reasons instead of one blocked door, and with
the pipeline demonstrably working end to end. `2026-08-28-discovery-shadow-run.md` is the first run;
this supersedes its "standing position" table.

## 1. The EACEA route is open, and has been since 28 August

The earlier run failed because the adapter harvested
`erasmus-plus.ec.europa.eu/projects/search/details/<id>`, which is refused server-side with HTTP 403.
**That was fixed the same day** — `EACEA_ERASMUS_MUNDUS` now points at the EACEA catalogue on a
different host — and nobody re-ran discovery afterwards. The empty catalog since then has not been a
blocked route. It has been an unrun one.

Verified 2026-08-30 with the honest bot User-Agent:

| Check | Result |
|---|---|
| `eacea.ec.europa.eu/robots.txt` | Disallows Drupal internals and `/search/` only. **`/scholarships/` is permitted** |
| `…/scholarships/erasmus-mundus-catalogue_en` | HTTP 200, 186 KB |
| Pagination | `?page=0…10`, 20 programmes each; page 1 shares **zero** hosts with page 0 |
| Consortium websites | On the catalogue page itself — `master-radmep.org`, `mundusjournalism.com`, `msc-terra.org`, … |
| Shipped adapter, run live | **169 leads, all `PROGRAM`, all `can_support_claim=True`** |

It is also a better adapter than the blocked one: 11 fetches instead of 1 + 169, more programmes,
and no catalogue hop, because the consortium's own site is on the listing. The detail pages were only
ever a pointer to it.

**These leads are claim-capable by construction**, which is the trust rule this programme settled on
the same day: EACEA vouches for the consortium, and the consortium's own site is the origin. No
classifier decides whether a host "looks official".

## 2. Five live leads, three failure modes

| Lead | Outcome |
|---|---|
| `www.multidiverse.eu` | `browser required: page is a JavaScript shell` |
| `lawgid.ius.bg.ac.rs` | `browser required: page is a JavaScript shell` |
| `www.emjmdstepsrock.eu` | `browser required: page is a JavaScript shell` |
| `www.master-wocc.eu` | `extraction failed` — funding is one hop inside the site |
| `clide.umk.pl/pages/home` | `extraction failed` — **undiagnosed** |

Every one became a `ConsultantResearchTask`. Nothing crashed, nothing was silently dropped, the
budget held. Invariant 4 holds against five real servers, as it did against the first run's five.

### 2.1 Three of five consortium sites are SPAs

Small EU-project consortium sites are built as JavaScript applications far more often than the
institution pages this pipeline was tuned against. The browser tier exists
(`apps/research/browser_server.py`) and was not used: `--render` was off, and `BrowserDesiredCount`
is 0. Whether patchright's Chromium is even installed on the dev host is untested — the Dockerfile's
`browser` stage installs it, not the local environment.

### 2.2 The catalogue gives a front door; the funding is a room inside

`www.master-wocc.eu` fetched cleanly — HTTP 200, 5,000 characters of visible text — and contains
**not one** of scholarship, fee, tuition, funding, grant or stipend. The extractor was handed a
homepage with no funding facts on it and correctly found none. That is a **targeting** gap, not an
extraction defect.

The funding pages are one hop away, on the same host:

```
/candidature-et-admission/bourses-detudes        (scholarships)
/candidature-et-admission/cout-de-la-formation   (cost of the programme)
/candidature-et-admission/admission-et-selection
```

`FUNDING_PATH_TERMS` in `apps/research/search.py` would match these — English `admission` appears in
the French path — and `EntityExpansionSource` already walks a host's sitemap and triages on exactly
that list. Seed-catalogue leads simply do not do it.

**And the hop is legitimate here for the reason it was not legitimate for open-web search.** The host
is a consortium EACEA vouched for, so hopping *within* it and granting `DIRECT` is provenance by
construction. The same mechanism that admitted content farms when the "organisation" came from an
open-web query is safe when the organisation came from a catalogue that stands behind it.

### 2.3 One failure is not explained

`clide.umk.pl/pages/home` returned 9.7 KB and 4,534 characters of text **containing both
"scholarship" and "fee"**, and extraction still failed. That is a different shape from 2.2 and is
recorded as open rather than guessed at. It wants one look at the extractor's input and output before
anything is concluded.

## 3. Two defects found on the way

**Six migrations were unapplied on the dev database**, including
`funding.0014_officialsourcesnapshot_content_sha256`. The run died on
`column funding_officialsourcesnapshot.content_sha256 does not exist`. Applied 2026-08-30;
`showmigrations` is now clean. The dev database had drifted behind the branch since the
condition-model work.

**The `discover` command's error handler blamed the wrong thing.** It catches `ProgrammingError` and
reports that "a database write was refused", naming the `catalog_ingestion` role and row-level
security as the two causes. The actual cause was schema drift, and the real message survives only
inside the parenthetical. Two minutes were spent looking at Postgres roles for a missing column.
Worth narrowing the handler, or leading with the underlying error rather than the interpretation.

## 4. What this changes

The 28 August document's standing position — *"every route to a catalog row is currently
closed"* — is now wrong on its first row:

| Route | Status |
|---|---|
| **EACEA via the catalogue** | **Open. Permitted, unblocked, 169 claim-capable leads** |
| DAAD International Programmes | Terms question unresolved. The host is additionally throttling us after this session's fetches: both `daad.de` and `www2.daad.de` timed out at 35 s |
| Open-web search → institution pages | Key and terms now fine; trust is not. Needs the ROR organisation frame |
| Institution sitemaps as a spine | Unchanged: 2 of 5 reachable, path shape is a CMS artifact |

**Nearest work, in order:**

1. **Intra-site hop for seed-catalogue leads**, reusing `FUNDING_PATH_TERMS` and the existing sitemap
   walk. Addresses 2.2 and reuses tested machinery.
2. **Diagnose 2.3** — one extractor input/output inspection.
3. **Browser tier for the SPA cases**, which is the larger lift and unblocks three of five here.
4. **ROR organisation frame** (own table; `Institution` stays evidence-backed) for everything outside
   Erasmus Mundus.

## 5. Honest limits

- **n = 5, of 169.** The 3:2 split between browser-required and extraction-failed is not a population
  rate and should not be quoted as one. Running the full catalogue is cheap and would replace it.
- **No row has ever been written.** The write path from extraction to `write_catalog_entry` remains
  unexercised against real data — every run so far has failed upstream of it. Nothing here shows that
  it works, only that everything before it does.
- The browser tier's local viability is untested, so item 3 above may hit an install problem before it
  hits a design one.
