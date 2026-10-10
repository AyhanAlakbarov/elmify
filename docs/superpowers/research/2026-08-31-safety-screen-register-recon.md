# Reconnaissance — the four registers the safety screen would be built on

**Date:** 2026-08-31. **Status: NOT a research run.** A control, in the manner of
`2026-08-30-live-search-prerun-recon.md`: it asks what each register *actually is* — access route,
format, authentication, cadence, terms, and what an absence from it means — before any of it is
designed against.

`2026-08-31-open-admission-synthesis.md` §7.1 says "build the screen against anabin and DEQAR", and
§9d adds Canada's DLI list and the UK sponsor register on the destination side. Four registers, two
legs. This file establishes whether they can be built on at all.

**Revision note.** §1 was rewritten on 2026-08-31 after a follow-up spike found the API this file's
first version said did not exist. Everything else stands as first measured.

Every claim below was fetched on **2026-08-31** and is quoted or measured, with the URL and the HTTP
status. Row counts are counts of the file actually downloaded, not figures taken from a page.

**All four are technically usable, three of them better than the synthesis credits, and one question
is left open on purpose.** anabin — the register §7.1 named first — turns out to serve a public,
unauthenticated JSON API (§1, corrected after this file's first version said the opposite), so the
only thing standing between it and the screen is what its Impressum says about storing content in a
database. That is a decision for the project owner; every other obstacle here is a field shape or a
licence to attribute.

---

## 1. anabin — a public JSON API behind a page that hides it

> **Corrected 2026-08-31, after the first version of this file said otherwise.** The original read
> *"There is no API, no export and no bulk file"* and concluded anabin had to be scraped from a
> rendered table. **That was wrong.** The error and its cause are kept below because the cause is
> reusable; the measurements are from the follow-up spike.

**Access route.** `https://anabin.kmk.org/anabin.html` → 200, redirecting to
`/cms/public/startseite`; the institution table is at `/db/institutionen` (200). That page ships an
empty `<tbody id="tableBody">` — the rows arrive by XHR — and its bundle `/public/dist/institutions.js`
(1.3 MB) names the endpoint:

```
GET https://anabin.kmk.org/api/public/institution
    ?filter={"$and":[{"country":{"$oid":"<id>"}}]}
    &sort={"nameShort":1}&limit=1000&offset=0&search=&reference=true
```

**No authentication, no cookie, no session.** `application/json`. The bundle exposes the whole
`/api/public/*` family the same way — `institution`, `institution-type`, `degree`, `qualification`,
`location`, `recognition-office`, and a dozen more.

`filter` is a MongoDB-style query object and **is evaluated server-side**: tested with Hong Kong's
country `$oid`, it returned 26 records, 63,983 bytes in 9.9 s, every row from that country. So a
per-market pull is one request, not a corpus walk.

**Measured cost of a refresh** (all figures from requests made 2026-08-31):

| | |
|---|---|
| corpus size | **32,000–33,000 records** — binary-searched on `offset`: 32,000 returns a row, 33,000 returns none |
| one page | `limit=1000` → **3,716,897 bytes in 8.1 s** |
| full walk | ~33 requests, **~4.5 minutes, ~120 MB** |
| stored, slimmed | name + country + H-status for 1,000 records is 76,764 bytes → **~2.5 MB for the corpus** |
| per record | 2,751 bytes, of which **14% is HTML prose** in `institutionType.comment` that no gate needs |

`institutionType.status.nameShort` carries the gate value directly — measured across one page:
`H+` 703, `H +/-` 250, `H -` 47. No HTML parsing anywhere in the path.

**Rate limiting is real and recoverable.** `limit=100000` returns **503 after 30 s**, and a burst of
requests then draws 503s served in ~0.34 s — a gate, not a slow query. It cleared on its own inside
~2 minutes. Pace a full walk at a few seconds per request.

**Methodology caveat — this is what produced the original error, and it will produce others.** anabin
returns **HTTP 200 for paths that do not exist**: `/robots.txt` returns a body reading *"Found.
Redirecting to /db/404-fehler"*, and an invented `/api/institutionen` also returns 200 `text/html`.
The first pass guessed the German path, got that soft-200, and read it as "no API" — when the real
route is the English `/api/public/institution`. **Against this host, a 200 proves nothing and a
guessed 404 proves less. Read the JS bundle; it names every endpoint.**

**The terms are the finding.** `https://anabin.kmk.org/impressum`, fetched 2026-08-31:

> Jede vom deutschen Urheber- und Leistungsschutzrecht nicht zugelassene Verwertung bedarf der
> vorherigen schriftlichen Zustimmung des Anbieters oder jeweiligen Rechteinhabers. **Dies gilt
> insbesondere für Vervielfältigung, Bearbeitung, Übersetzung, Einspeicherung, Verarbeitung bzw.
> Wiedergabe von Inhalten in Datenbanken oder anderen elektronischen Medien und Systemen.** […]
> Lediglich die Herstellung von Kopien und Downloads für den persönlichen, privaten und **nicht
> kommerziellen** Gebrauch ist erlaubt.

Any exploitation not permitted by German copyright law requires **prior written consent** — and the
clause names, specifically, *storing, processing or reproducing content in databases or other
electronic media and systems*. Only personal, private and **non-commercial** copies are permitted.

**This is the same shape as Brave's definitions clause in the live-search adjudication, and it lands
the same way.** Caching anabin's H+/H− ratings into our own tables is the exploitation the clause
names, and we are a commercial product. There is no ambiguity to resolve by reading further.

Its disclaimer independently refuses reliance: *"Eine Gewähr für die jederzeitige Aktualität,
Richtigkeit, Vollständigkeit und Verfügbarkeit der bereit gestellten Informationen können wir
allerdings nicht übernehmen."*

**Consequence for §7.1.** The obstacle is licensing only — **there is no engineering obstacle left.**
Ingesting anabin costs an HTTP client, a pagination loop and a field mapper; no browser, no
rendering, none of the machinery in `CLAUDE.md`'s Scrapling section, because there is nothing to
render. Whether to store it under those terms is a decision for the project owner, not something this
file settles.

**The maintenance cost that survives either decision.** `/api/public/*` is undocumented and exists to
serve KMK's own SPA, so it can change without notice or deprecation. That is materially safer than
parsing a rendered table — JSON field names break loudly and rarely — but it is the one place a real
recurring cost remains. Assert the four fields the gate reads (`nameShort`, `nameGerman`,
`country.nameShort`, `institutionType.status.nameShort`) on every run and fail hard, rather than
writing an empty or partial refresh.

---

## 2. DEQAR — the opposite in every respect

**Access route.** `data.deqar.eu` is dead (404 on the root). The live surfaces are the web interface
at `eqar.eu/qa-results/search/`, a **token-protected Web API** at `backend.deqar.eu` (403 without
credentials, as expected), and — the one that matters — **four daily CSVs served with no
authentication at all**:

| file | HTTP | bytes | rows |
|---|---|---|---|
| `backend.deqar.eu/static/daily-csv/deqar-institutions.csv` | 200 | 2,931,558 | **9,018** |
| `…/deqar-reports.csv` | 200 | 103,064,497 | **149,229** |
| `…/deqar-agencies.csv` | 200 | 159,776 | 107 |
| `…/deqar-countries.csv` | 200 | 86,961 | 341 |

**No API token is needed for the bulk data.** The token gates the query API, not the corpus. That
removes the registration step the synthesis assumed.

**Terms** — `eqar.eu/.../terms-and-conditions`, fetched 2026-08-31, quoted:

> The information is freely accessible for anybody free of charge. **The Metadata may be used freely
> under the Open Data Commons Public Domain Dedication and Licence (PDDL).** In doing so, Users
> should respect the Open Data Commons Community Norms.

Original review documents are the agency's property, defaulting to CC-BY-SA-4.0 where the agency
specifies nothing. So: **the metadata — which is the whole screen — is public domain; the PDFs are
not.** Store the metadata, link the documents, never mirror them.

On the API: *"EQAR may limit access to the Web API to registered Users. In that case, EQAR will grant
access to any individual or organisation on request… EQAR will publish a list of registered Users."*
Worth knowing before choosing the API over the CSVs: **API use is public by design.**

**The caveat EQAR states about its own data, which the screen must carry:**

> …this inevitably requires simplification and might lead to a loss of detail or precision in some
> cases. **The Original Documents represent the only formally valid representation of the QA Result.**

**An unadvertised bonus that lands directly on the code roadmap.** `deqar-institutions.csv` carries an
`identifiers_all` column, and **3,664 of 9,018 rows (41%) contain a ROR ID**, alongside ETER and WHED:

> `Erasmus:DURRES01, WHED:IAU-019897, ROR:https://ror.org/023p15505`

The handoff lists "increment 4's ROR canonical identity" as where name-variant forking gets solved
generally. **DEQAR is a free, public-domain, daily-refreshed ROR crosswalk for 3,664 EHEA
institutions.** That is a better starting point than name matching, and it costs one CSV.

### 2a. Georgia — §4 of the synthesis is directionally right and quantitatively wrong

§4 states DEQAR "does not currently cover Georgian institutions." Measured against the file:
**DEQAR lists 83 Georgian institutions, 60 of them carrying at least one report**, 1,274 report rows
in total. The historic corpus did not vanish when NCEQE left the register; `report_last` clusters in
2021–2023 with a thin tail (4 in 2024, 3 in 2025, 1 in 2026).

The real mechanism is sharper, and it is computable:

| agency | GE report rows |
|---|---|
| **NCEQE** | **1,247** |
| ACQUIN | 7 |
| FIBAA | 6 |
| MusiQuE | 6 |
| ASIIN | 4 |
| AQ Austria, A3ES, EUA-IEP | 4 combined |

**98% of Georgia's evidence in DEQAR rests on an agency no longer on EQAR.** The residual 2% comes
from EQAR-registered agencies working cross-border, and covers only a handful of institutions. So the
screen is not blind in Georgia — it is *narrow*: a Georgian institution can still be cleared, but only
one holding a report from an agency **currently** on the register. That is a filter, not a blanket
exclusion, and it is strictly better than the Part D entry §5 proposed. Update §4 accordingly.

---

## 3. Canada's DLI list — one flat JSON behind a JavaScript page

The `canada.ca` page is a shell; the data is a single file referenced in its markup:

**`https://www.canada.ca/content/dam/ircc/documents/json/dli/dli-full-list.json`** — HTTP 200,
430,535 bytes, `{"data": [...]}`, **1,442 rows** across 12 provinces/territories, **1,119 distinct
institutions**. No authentication, no pagination, no key. Guessed sibling files
(`dli-pgwp-list.json`, `dli-pal-tal-exempt-list.json`) return 404 — the one file carries the flags.

Per-row schema, verbatim from the first record:

```json
{"Province": "Alberta", "Institution": "ABM College of Business and Technology",
 "DLI #": "O242632228347", "City": "Calgary", "Campus": "Calgary",
 "Grad Program": "No", "PGWP": "No", "HTML": "No", "Public/Private": "Private institution"}
```

**The load-bearing caveat: `PGWP` is not a boolean.** Measured distribution across the 1,442 rows:

| PGWP value | rows |
|---|---|
| `No` | 589 |
| `Yes` | 495 |
| **`Details`** | **358** |

**A quarter of the register refuses to answer at row level** and defers to a per-institution page
listing which programmes qualify. By institution: 301 have at least one `Yes` row, **324 have at
least one `Details` row**. Any screen that reads this file as a two-valued flag will silently
misclassify roughly a third of institutions. The `HTML` column holds the anchor markup for those
detail links — usable to resolve them, and the only reason that column exists.

`Grad Program` is a clean boolean: 156 rows / **103 institutions** offer PAL/TAL-exempt graduate
programmes. Split is 832 private / 610 public campus rows.

canada.ca states the limit of the flag itself: *"Not all programs offered by a DLI are eligible for a
PGWP."* **The register clears a provider, never a qualification** — the same asymmetry anabin
declares about completeness.

**Terms** were not located as an explicit open licence on the DLI page; canada.ca's site-wide terms
apply. Recorded as *unverified*, not as permitted — resolve before ingesting.

---

## 4. The UK Register of Licensed Student Sponsors — the cleanest of the four

**Access route.** The publication page's `gov.uk` content API
(`gov.uk/api/content/government/publications/register-of-licensed-sponsors-students`, 200) names the
current attachment directly, so the CSV can be resolved without scraping the page:

- `assets.publishing.service.gov.uk/media/6a9156109a177a1decf97b22/SP_-_Student_and_Child_Student_Web_Register_-_2026-08-28.csv` — 200, 122,641 bytes, **1,308 rows**.
- The asset URL is **content-hashed and date-stamped per revision**; only the API's
  `details.attachments[]` is stable. Do not hard-code the CSV URL.

**Cadence, measured not estimated.** The content API returns **2,988 change-history entries**, first
published 2013-11-13, with notes reading *"Register updated."* / *"Updated register of licensed
sponsors."* The last ten entries are 2026-08-12 through 2026-08-28 — **every business day**.
`public_updated_at`: `2026-08-28T10:41:09+01:00`.

**Licence: Open Government Licence v3.0.** Ingestible with attribution.

**Schema and measured distributions** — seven columns:

| column | values (n = 1,308) |
|---|---|
| Sponsor Name, Town/City, Additional Locations | free text |
| **Sponsor Type** | Independent school 901 · **HEI 192** · Private provider 109 · Publicly funded college 70 · **Overseas HEI 28** · Embedded pathway college 8 |
| **Status** | Student Sponsor 939 · **Student Sponsor – Track Record 302** · **Probationary Sponsor 67** |
| Route | Student 762 · Child Student 546 |
| **Immigration Compliance** | blank 1,293 · **"Subject To Action Plan" 15** |

**Two signals here that the synthesis did not credit, both free.**

1. **`Status` is a three-level trust ladder**, not a licence boolean. *Probationary Sponsor* (67
   today) is a sponsor without a track record — a materially different bet from one holding it, and
   exactly the "safe-looking floor that is not" the brief asked to flag.
2. **`Immigration Compliance` = "Subject To Action Plan" is live regulatory action** — 15 sponsors
   today. That is **leg A5**, which run A said needed separate enforcement-notice sources. It is a
   column in a file we already have, updated daily, under OGL.

Note the row grain: a sponsor appears **once per route**, so Student and Child Student are separate
rows (Abbey College Cambridge appears twice). Deduplicate on name before counting institutions.

---

## 5. What this changes

1. **§7.1 is buildable; only its terms are open.** anabin serves a public, unauthenticated JSON API
   (§1) — a full refresh is ~33 requests and ~4.5 minutes, and a single market is one request. What
   remains is the licensing question its Impressum raises, which is the owner's call, not an
   engineering blocker. **On engineering cost anabin ranks second of the four, behind the UK CSV.**
2. **DEQAR is cheaper than assumed and richer than assumed.** Four daily CSVs, no token, metadata in
   the public domain, and a 3,664-row ROR crosswalk that lands on the code roadmap independently of
   this screen.
3. **Canada's `PGWP` field is tri-valued.** Design for `Yes` / `No` / `Details`, or misclassify ~⅓ of
   institutions. Resolve the licence before ingesting.
4. **The UK register already answers leg A5** via `Immigration Compliance`, and grades sponsors three
   ways via `Status`. OGL, daily, 1,308 rows — the cheapest real signal in the whole screen.
5. **Georgia is a filter, not a blackout.** Clear a Georgian institution only on a report from an
   agency currently registered with EQAR; 98% of its DEQAR evidence is NCEQE's and does not qualify.
6. **Every one of the four declares its own incompleteness** — anabin's *"keine Gewähr … für
   Vollständigkeit"*, EQAR's *"the Original Documents represent the only formally valid
   representation"*, canada.ca's *"Not all programs offered by a DLI are eligible"*. The screen
   clears **providers**, never qualifications, and the product language has to say so.

## 6. Not established here

- **The DLI list's licence.** Unverified; canada.ca site terms apply by default.
- **Whether the DLI JSON path is stable.** It is a `/content/dam/` asset behind a JS page, not a
  published API, and could move without notice. Fetch defensively.
- **DEQAR API rate limits and the registered-user list.** Not needed if the CSVs suffice, which they
  appear to.
- **anabin under written consent.** Whether KMK grants it, and on what terms, is unasked.
- **anabin's exact corpus size**, bracketed to 32,000–33,000 rather than counted: the API returns no
  total and `reference=true` adds no envelope. One `limit=1&offset=N` walk would pin it.
- **Whether `/api/public/institution` is rate-limited by IP over longer horizons.** A single burst
  recovered in ~2 minutes; a daily 33-request job was not tested.
- **CRICOS / ILEP / NZQA**, still Part D. Expect them to resemble the DLI list rather than anabin.
