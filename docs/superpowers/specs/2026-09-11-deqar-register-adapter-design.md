# The DEQAR and WHED register adapters — the reference the other registers copy

**2026-09-11. Status: design, no code written. Revised the same day to add WHED** after the owner
obtained IAU's consent (`../research/2026-09-11-whed-recon.md`), and on 2026-09-12 to read WHED's
search by ID rather than each institution's page (§2.2). Item 3 of
`2026-08-31-institution-safety-screen-design.md` §10, plus a sixth axis that design did not have.
It builds on two things now on master: `InstitutionIdentifier` with `UniqueConstraint(scheme, value)`
(`2026-09-07-institution-identifier-binding-design.md`), and `OffSiteRedirect` in
`apps/research/refresh.py`.

**Every number below was measured on 2026-09-11** against DEQAR's four files and WHED's live site as
served that day. They are dated snapshots. Where a DEQAR number differs from the 2026-08-31
measurement, §3.2 says why.

## 0. Scope

**In scope.** Two registers on one machinery. DEQAR: fetching and archiving its four daily files and
turning them into `QUALITY_ASSURED` rows. WHED: asking WHED's own search, once per institution the catalog
has bound to a WHED ID, whether that ID is listed, and turning the answer into `NATIONALLY_RECOGNISED`
rows. The shared
parts every later register reuses: the per-register config, the same-origin check, the replace-on-
refresh writer, the crosswalk writer and the management command. One migration for the sixth axis
and the `WHED` identifier scheme. The rule a read uses when two listings disagree (§5), which this
slice specifies and `screen.py` implements when it lands.

**Out of scope.** `screen.py` itself. The alert when a listing an active student depends on moves
off `CLEAR` (§8). The schedules (§7). A walk of WHED's per-country listings: the adapter reads only
institutions already bound, and the country walk belongs to the later `propose_institution_identifiers`
command (§8).

## 1. Why this exists

**What.** The platform recommends programmes, and the discovery pipeline already creates an
institution row from a name the model reads off a programme page (`apps/research/catalog.py`). So a
convincing website is enough to enter the catalogue, and nothing yet checks that the institution
behind it is real and reviewed. Two registers answer that, without a human reading anything:

- **WHED**, the IAU and UNESCO database of every nationally recognised, degree-granting institution:
  about 21,000 in 196 countries, each with a stable ID. An institution is listed only if the national
  competent body recognises it and is removed when recognition lapses. DEQAR's own rules accept a WHED
  ID as automatic proof of official status. This is the "is it real" gate, worldwide.
- **DEQAR**, Europe's register of quality-assurance outcomes: which accredited agency reviewed which
  institution or programme, with what decision, valid until when. Public domain, four CSV files,
  regenerated daily. This is the "has its quality been judged" gate, deep in Europe and blind in the
  anglophone destinations (403 of 496 open German institutions clear; 4 of 286 American ones do).

**The limit.** Neither register enters ranking, and neither produces a negative that may be shown as
one (§1.1). WHED lists fewer institutions than DEQAR in Europe by design, and absence from either
means several different things (`2026-09-11-whed-recon.md`, "What an absence means").

**What it costs to decide.** One migration, two adapters, and the machinery the next registers fill
in as configuration. The tables and the identifier binding are already on master.

### 1.1 The anti-skew guarantee

The owner's requirement, 2026-09-11: a recommendation pack must not be skewed by the register
ingested first, and no counselor reads register output to decide. Four rules make that structural.

- **The screen is a gate, never a score.** A verdict never enters ranking. A programme in New Zealand
  and one in Hungary are ordered by exactly what orders them today.
- **Absence is never a negative.** No row means the axis is unanswered. Neither register here
  produces `EXCLUDED`, so neither can produce a negative that may be shown as one.
- **`QUALIFIED` is not a fail.** It is carried with the publisher's own words; the product decides how
  to render it, and never as a refusal.
- **Coverage travels with every negative**, and below roughly half coverage no negative is shown at
  all (parent spec §4, §9 step 5). DEQAR's per-country rates are in §3.2.

A future feature in which an agent filters programmes on screen verdicts unaided would break the
first rule and run into the human-oversight clause in `CLAUDE.md`'s search providers section. Read
both before proposing one.

## 2. What the adapters may fetch

### 2.1 DEQAR: four URLs, and nothing a file points to

```
https://backend.deqar.eu/static/daily-csv/deqar-institutions.csv   2,933,761 bytes
https://backend.deqar.eu/static/daily-csv/deqar-reports.csv      103,118,707 bytes
https://backend.deqar.eu/static/daily-csv/deqar-agencies.csv         160,083 bytes
https://backend.deqar.eu/static/daily-csv/deqar-countries.csv         86,799 bytes
```

Constants in the DEQAR config. Each becomes one `OfficialSource` row with publisher `EQAR` and
`source_type=REGULATOR`, created on first run with `get_or_create` on `canonical_url`.

**No URL found inside a file is ever fetched.** The files carry `deqar_url`, `report_url`,
`website_link`, `report_files` (agency PDFs) and agency websites. They are links a product may show,
never sources this code retrieves. The PDFs belong to the agencies under CC-BY-SA-4.0 by default and
are never mirrored (parent spec §6.1).

### 2.2 WHED: one search by ID per bound institution, on the bare host

```
https://whed.net/results_institutions.php?Chp2=IAU-011713&Chp0=&Chp1=&Ope0=and&Chp4=&Chp5=&nbr_ref_pge=100&debut=0&afftri=yes&stat=Country
```

One GET per institution the catalog has bound under scheme `WHED`, asking WHED's own search for that
ID. It needs no session, no referer and no JavaScript, measured 2026-09-12. Each URL becomes its own
`OfficialSource` with publisher `IAU`, so a listing cites a query anyone can re-run.

**Why the search and not the institution's page.** WHED's promise is that a delisted institution
leaves the list. The search answers "is this ID in the list now", which is that promise directly. The
stable page at `whed.net/institutions/IAU-nnnnnn` answers only "does a page exist", and nobody has
observed whether a delisted institution's page is removed or kept with a note. Reading the search
takes that unobserved case out of the read. The cost is the "accrediting agency" field, which appears
only on the page.

**Only the bare host.** `www.whed.net` answers every path with a Cloudflare challenge; `whed.net`
serves everything. `robots.txt` disallows only `/pdf/` and `/workspace/`, which this code never
touches. The per-country listing is not walked by this adapter; it is the route for proposing
bindings later (§8).

**Pacing.** One request a second, with the sleep injectable for tests. A catalog of a few hundred
bound institutions is minutes. Longer horizons were not measured.

### 2.3 The egress path, and two per-call limits

Every fetch goes through `egress.py::fetch_official_source` with `require_https=True`, so
`validate_public_url` runs on every redirect hop. Neither register needs a browser.

**Two per-call parameters are added to `fetch_official_source`, with today's values as defaults.**

| parameter | default (unchanged) | DEQAR passes | WHED passes |
|---|---|---|---|
| `content_types` | `ALLOWED_CONTENT_TYPES` | `{"application/octet-stream"}` | the default |
| `max_bytes` | `MAX_RESPONSE_BYTES`, 10 MiB | 256 MiB | the default |

DEQAR serves its CSVs as `application/octet-stream` and `reports.csv` is 103 MB, both measured. A
register passes exactly the type it was measured to serve, so the override narrows as well as
widens. A caller that passes nothing gets today's behaviour, and a test pins that (§9).

### 2.4 `OffSiteRedirect` applies unchanged, and moves to `egress.py`

The rule in `CLAUDE.md` ("Decision B vouches for the SOURCE ROW, not the BYTES") applies verbatim:
the origin of `fetched.final_url` must equal the origin of the requested URL before
`persist_snapshot` runs. Origin means scheme plus host, never the whole URL.

**`OffSiteRedirect` and `_origin` move from `refresh.py` to `egress.py`**, as one function:

```python
def require_same_origin(requested: str, fetched: FetchResult) -> None
```

`refresh.py` calls it and re-exports `OffSiteRedirect`, so `tests/research/test_refresh.py` keeps its
import. The move is required, not tidying: `tests/research/test_registers.py` pins that the register
path reaches no model client, and `refresh.py` imports `extraction.py`.

### 2.5 Archiving

Every fetched page or file is archived through `snapshot.py::persist_snapshot` under its own source,
**after the read succeeds** (§4.4) and never after an off-site redirect. `admissions_cycle` is the
empty string: a register is not cycle-bound.

**Unchanged bytes reuse their snapshot.** `(source, sha256)` is unique, so a second `persist_snapshot`
of identical bytes raises. The refresh looks the digest up first, as `pipeline.py` does. Verdicts are
recomputed anyway: a DEQAR report can expire overnight in a file that did not change.

**Storage.** If `reports.csv` changes daily, a year of snapshots is about 39 GB, a little under a
dollar a month by year end. WHED searches are about 28 KB each, monthly. A lifecycle rule for old
reports snapshots is the fix when it matters; not built here.

## 3. The reads

Each register's read is a pure function in `apps/research/registers.py`: bytes in, verdicts out, no
database, no network:

```python
def read_deqar(pages: Mapping[str, bytes], today: date) -> RegisterRead
def read_whed(pages: Mapping[str, bytes], today: date) -> RegisterRead
```

`pages` is keyed by page name: for DEQAR the four file names; for WHED the IAU ID of each fetched
page. A `RegisterRead` holds one proposed listing per identifier value, each naming the page whose
snapshot it cites, plus (DEQAR only) coverage rows and a crosswalk.

### 3.1 DEQAR: the verdict rule

Every CSV is parsed with the `csv` module over a decoded `utf-8-sig` stream: that handles the BOM
DEQAR ships and the quoted `"Korea, South"` that split on its own comma in the 2026-08-31 measurement.
The longest field in `reports.csv` is 29,909 characters, inside the module's default limit.

**Per open institution, on axis `QUALITY_ASSURED`, audience everyone.** A report *counts* when:

1. its `report_agency` reads `Registered` in `agencies.csv::is_registered` (60 of 78 agencies);
2. it is in force today: `report_valid_to` is on or after today, or, when blank, `report_valid_from`
   plus six years is on or after today;
3. its `report_decision` is not `negative`. `positive`, `positive with conditions or restrictions`
   and `not applicable` all count.

A report whose dates do not parse does not count: the cautious direction.

| DEQAR says | verdict |
|---|---|
| at least one report counts | `CLEAR` |
| registered-agency reports exist, none counts (all expired, or all negative) | `QUALIFIED` |
| reports exist, all from agencies no longer registered | no row |
| no reports | no row |
| `closure_date` is set | no row, and not counted in coverage |

**The six-year rule is DEQAR's own.** `docs.deqar.eu/stable/report_data/`, read 2026-09-11: *"In
case the end date is left open, the report will be treated as valid for six years from the start of
its validity."* 33,551 reports have a blank end date; 20,394 of those are past six years.

**Why a lapsed agency produces no row.** Georgia and Russia: NCEQE and AKKORK left the EQAR register
(parent spec §4, case 3). No registered agency has spoken; coverage carries it, and Georgia reads 6
of 83.

**Why `EXCLUDED` never appears.** DEQAR never names an institution as excluded. A negative decision
is about one review, often one programme.

**Programme-only reviews count. Decided 2026-09-11.** 2,272 of the 4,041 institutions the rule clears
hold programme reviews only, and the share varies with how a country runs quality assurance, not
with the quality of its universities: Poland 98%, Netherlands 98%, Spain 81%, Germany 64%, France 29%,
Hungary 22%, Austria 6%, Türkiye 4%. Counting only institutional reviews would turn a country's
review style into a quality difference, which is the skew §1.1 forbids. The review type is carried in
`raw_value` so it stays visible.

**`raw_value`** is built only from DEQAR's field values, capped at 200 characters, and describes one
representative report: for `CLEAR` the counting report, preferring `institutional` or
`institutional/programme` over a programme report, then the latest end date; for `QUALIFIED` the
registered-agency report with the latest end date.

```
EVALAG programme report, positive with conditions or restrictions, valid to 2028-09-30
ANECA institutional report, positive, valid to 2027-03-01 (six years from start)
A3ES programme report, positive, expired 2024-02-28
```

**`as_of`** is the date of the run; the file is regenerated daily and carries no date inside it.

**Duplicate IDs.** 39 open DEQAR IDs appear on more than one row, one per country. The verdict is per
ID. Coverage counts the ID once in each country that lists it, and an ID printed twice for one country
counts once.

**The crosswalk.** `identifiers_all` carries `WHED:IAU-nnnnnn` on 2,755 open rows. The read returns,
per DEQAR ID, the WHED IDs it prints; §4.3 says what the writer does with them.

### 3.2 What the DEQAR rule produces today

| | open institutions |
|---|---|
| `CLEAR` | 4,065 |
| `QUALIFIED` | 634 |
| no row: only lapsed-agency reports | 92 |
| no row: no reports | 3,271 |
| total open | 8,062 |

Coverage as `cleared / listed` over open institutions: Hungary 61/65 (94%), Germany 403/496 (81%),
Spain 945/1,341 (70%), Kazakhstan 117/170 (69%), Poland 323/494 (65%), Türkiye 130/211 (62%),
France 296/593 (50%), Italy 117/254 (46%), UK England 53/252 (21%), Georgia 6/83 (7%),
Ukraine 35/707 (5%), United States 5/287 (2%).

**Why lower than the 2026-08-31 figures.** That measurement counted any report from a registered
agency, expired or not, over all rows including closed institutions, and cleared 5,027. Every coverage
figure in the parent spec is the older rule's.

### 3.3 WHED: the search's own answer is the verdict

**Per fetched search, on axis `NATIONALLY_RECOGNISED`, audience everyone.** The read keys on the
page's result line, `<p class="infos">`, which echoes the searched ID:

| the result line reads | and | verdict |
|---|---|---|
| `1 results found for (Global WHED ID=IAU-011713)` | exactly one result row, carrying that ID | `CLEAR` |
| `No matching records for (Global WHED ID=IAU-011713)` | | no row |
| anything else: another ID, a count other than 1, no result line | | the read refuses (§4.5) |

**The ID's presence proves nothing.** A no-match page still prints the searched ID, in the result
line and in the search box. The read matches the whole result line, never the bare ID.

Never `QUALIFIED`, never `EXCLUDED`: WHED is a list of the recognised, and leaving it is silence.

**`raw_value`** is `Listed as <English name>, <country>` from the result row, capped at 200
characters, or `Listed` when the row's name does not parse. **`as_of`** is the run date; the
database is updated monthly.

**A whole-run guard.** If the catalog has bound IDs and the run finds none of them, the read refuses:
a changed search would otherwise read as every institution delisted at once.

## 4. The write

One writer in `apps/research/registers.py`, shared by every register:

```python
@transaction.atomic
def record_register_read(*, publisher: str, read: RegisterRead,
                         snapshots: Mapping[str, OfficialSourceSnapshot]) -> RecordSummary
```

`snapshots` maps page name to the archived snapshot, so each listing cites the page it was read from.

### 4.1 The join

Each proposed listing's identifier is looked up in `InstitutionIdentifier` under the read's scheme:
`DEQARINST` for DEQAR, `WHED` for WHED. **An unbound value is dropped, never matched on a name.**
That is the whole finding of the identifier-binding design. Dropped counts are reported.

Both registers key at institution level, so both bind to `kind=INSTITUTION`, and the identifier
spec's §3 table gains both rows. DEQAR's `parent_institution` column is not read; `Institution.parent`
is ours.

An institution can hold two IDs in one scheme after a merger. It gets one listing, and the more
cautious verdict stands, by the same order §5 uses.

### 4.2 The sixth axis

`RegisterListing.Axis` gains `NATIONALLY_RECOGNISED`: *is this a real institution the national
competent body recognises.* The parent design's five axes assume that premise and none states it;
WHED states it for 196 countries. It is not folded into `QUALITY_ASSURED` because §5's most-cautious
rule would then let a DEQAR `QUALIFIED` (reports lapsed) pull a recognised institution down on the
axis that says it exists. One migration widens `_AXES`, both axis `CheckConstraint`s, and adds
`WHED` to `_IDENTIFIER_SCHEMES` and its constraint. `load_institution_identifiers` gains the shape
`IAU-\d{6}`, the only form seen on every page read.

### 4.3 What lands

- **`RegisterListing`**: one row per bound institution with a verdict. `audience_country=""`,
  `applies_from` and `applies_until` null, `snapshot` = the snapshot of the page named by the listing:
  `reports` for DEQAR, the institution's own search for WHED.
- **`RegisterCoverage`, DEQAR only**: one row per country with at least one open institution,
  computed over all of DEQAR, citing the reports snapshot. WHED gets no coverage rows: every listed
  institution is `CLEAR`, so the ratio is always 100% and says nothing.
- **`InstitutionIdentifier`, from DEQAR's crosswalk**: for each institution bound by `DEQARINST`, the
  WHED IDs its DEQAR row prints are bound with `source=CROSSWALK`, unless already bound. A WHED ID
  already bound to a *different* institution is not touched and is reported: per the identifier
  design's §3 that is a duplicate institution row or a wrong binding, and a daily job must report it,
  not die on it. This is the one exception to "the adapter writes no identifiers", and it is narrow: a
  code printed by a public-domain register on a row a human already bound.

**Both DEQAR rows cite the reports snapshot; the verdict also depended on the agencies file.** An
agency's registration status at the time of a verdict is recoverable as the newest agencies snapshot
retrieved on or before the listing's `as_of`. A second snapshot foreign key is not added.

### 4.4 Country codes, DEQAR

`RegisterCoverage.country_code` is ISO 3166 alpha-2 and DEQAR prints names.

- **53 names resolve through `countries.csv::iso_3166_alpha2`**, taking the first two characters:
  `GB-ENG`, `GB-SCT`, `GB-WLS`, `GB-NIR` become `GB`; `BE-fl`, `BE-fr` become `BE`.
- **82 other names, on 905 rows, are not in `countries.csv`.** 81 resolve through a checked-in mapping
  in `registers.py`. **Kosovo does not**, on 35 rows: ISO 3166 assigns it no code, `XK` is not in
  `ISO_3166_ALPHA2_CODES`, and the table's constraint would reject it.
- **A name in neither is skipped from coverage and reported**, never fatal.
- **Every mapped code is checked against `ISO_3166_ALPHA2_CODES` before the transaction opens.**
- **1,200 rows have a blank country**, 586 open. They get their listing, if bound, and no coverage.

**The GB rate is a blend** of four nations; carry that into the rendering policy.

### 4.5 Replace, and refuse before replacing

Inside one transaction, delete every `RegisterListing` and `RegisterCoverage` row whose snapshot's
source has this register's publisher, then insert the new read. The parent spec's "projection, not a
ledger", and the same replace rule `profile.py` uses. Deleting by publisher rather than by source is
what lets WHED, with one source per institution search, share the writer.

**A read refuses before anything is archived or deleted**, raising and leaving previous rows
standing, when: a DEQAR file lacks a column the read uses; `reports.csv` or `institutions.csv` parses
to zero rows; `agencies.csv` has no agency reading `Registered`; a WHED search shows neither the one-result
line for its ID nor the no-match line; or WHED finds none of a non-empty set of bound IDs. A fetch
failure never reaches this point, because `fetch_official_source` raises first.

## 5. Two verdicts for one institution and axis — the read rule

`register_listing_subject_axis_audience_uniq` includes `snapshot`, so two rows for one institution,
axis and audience can coexist. `screen.py` implements this when it lands.

1. **Filter first.** Rows whose `audience_country` is `""` or the student's home country, and whose
   `applies_from` and `applies_until` contain the cohort start when one is given.
2. **One snapshot per source.** Among rows from the same `OfficialSource`, only the newest snapshot's
   rows count. Replace already guarantees this; the rule is the read's defence if the table ever holds
   two anyway.
3. **Across sources, the most cautious verdict wins:** `EXCLUDED` over `QUALIFIED` over `CLEAR`. An
   audience-specific row does not override an everyone row; both apply.
4. **Every contributing row is returned**, with `raw_value`, `as_of`, publisher, snapshot and that
   country's coverage rate, so the product can show each publisher's own word.
5. **Parents: inherit downward, never upward.** A `CAMPUS` or `UNIT` reads its own rows plus every
   ancestor's; an institution never reads a subunit's rows. The walk stops after three hops and raises
   past that, which is the cycle guard `Institution`'s own `ponytail:` comment defers to the walker.

**Rejected: ranking the publishers.** "The home regulator outranks a cross-border agency" needs a
measured ordering of authorities, and none exists. Caution needs no ordering and cannot skew a pack,
because a verdict never enters ranking.

## 6. Where the code goes

| file | change |
|---|---|
| `apps/funding/models.py` + migration `0028` | `Axis.NATIONALLY_RECOGNISED`, `Scheme.WHED`, the three widened constraints |
| `apps/funding/management/commands/load_institution_identifiers.py` | `_SHAPES["WHED"]` |
| `apps/research/egress.py` | `content_types` and `max_bytes`; `OffSiteRedirect` and `require_same_origin` move here |
| `apps/research/refresh.py` | calls `require_same_origin`; re-exports `OffSiteRedirect` |
| `apps/research/registers.py` | `Register`, `DEQAR`, `WHED`, both reads, the country mapping, `record_register_read`, `refresh_register` |
| `apps/research/management/commands/refresh_register.py` | `refresh_register <slug>`: builds the store, calls `refresh_register`, turns a refusal into `CommandError`, prints the summary |
| `docs/superpowers/specs/2026-09-07-institution-identifier-binding-design.md` | §3 table gains `DEQARINST` and `WHED` |

**The `Register` config** carries `slug`, `publisher`, `collect` and `read`, plus `content_types`
and `max_bytes`, which default to egress's own limits. Each register's licence is recorded in the
comment above its config, not in a field nothing reads. `collect` takes a fetch callable and returns the pages this register wants,
keyed by name: DEQAR's fetches four fixed URLs; WHED's reads the bound IDs from the database and
runs one search each, pacing itself. **The only URLs a register may fetch are the ones its `collect`
builds from constants and bound identifier values.** The parent spec's `axes`, `audience_country`,
`cadence` and `transport` join with the first register that needs them.

**The words "extraction", "llm", "openai" and "anthropic" must not appear in `registers.py` or the
command, even in a comment.** `test_registers_module_reaches_no_llm_client` scans the source text.

## 7. Running it

```
DATABASE_ROLE=migration uv run python manage.py refresh_register deqar
DATABASE_ROLE=migration uv run python manage.py refresh_register whed
```

**The role.** Register tables accept writes under the `catalog_ingestion` policy only, and
`config/settings/database.py` accepts `DATABASE_ROLE` values `runtime` and `migration`. A manual run
uses `migration`, as `load_institution_identifiers` does. Under the runtime role the INSERT raises and
the DELETE before it rolls back with it.

**Schedules are deferred, with a prerequisite.** Daily for DEQAR, monthly for WHED, as EventBridge
rules modelled on `EuropassCanaryRule`, deferred like the erasure schedule because nothing is
deployed. A scheduled job should not hold migration credentials, so the schedule's own change adds a
`catalog_ingestion` value to `DATABASE_ROLE` and a task definition that uses it.

**Memory.** `fetch_official_source` holds the 103 MB reports body in memory and the read streams rows
from it. The worker task has 1,024 MB. That fits, and would not fit a register ten times larger.

**Output.** Per page: bytes and whether the snapshot was created or reused. Verdict counts, bound
versus dropped IDs, coverage rows, crosswalk bindings written and conflicts, unmapped country names,
and the count of bound institutions whose verdict changed since the previous read, which stands in
for the alert until §8's item lands.

## 8. Not established here, or deliberately deferred

- **IAU's consent in their own words for storage and commercial use.** Recorded and read as covered
  (`2026-09-11-whed-recon.md`); a one-line confirmation is a work item.
- **Whether WHED's search ever keeps a delisted institution.** The design assumes the search reflects the
  list as IAU maintains it, which is what IAU's listing rule says. The first observed delisting settles
  it; the read no longer depends on whether an institution's page is kept.
- **Proposing WHED bindings.** WHED's per-country listing and keyword search
  (`POST results_institutions.php`, `Chp0=<keyword>`) are the basis for the identifier design's
  `propose_institution_identifiers` worldwide. Not this slice.
- **The change alert** (parent spec §6.2). The command counts transitions and prints them.
- **ETER as a second DEQAR join key.** Add when a catalog institution is bound only by ETER.
- **`Last-Modified` as `as_of`.** Needs `FetchResult` to carry headers.
- **A lifecycle rule for old reports snapshots** (§2.5), and **the GB blend** (§4.4).
- **The negative-rendering threshold.** Still roughly 50%, still untested; France sits on it.

## 9. Testing

Fixture CSVs and fixture HTML built from real header lines and real page structure. No test reaches
DEQAR or WHED by default.

**DEQAR read, pure:** registered, in-force, positive clears; explicit past end date does not count;
blank end date counts within six years and not after, leap-day start ends on the 28th; only
`negative` stops a report counting; one counting report outweighs a negative one; lapsed-agency-only
makes no row; no reports makes no row but counts as listed; closed institution neither; unreadable
dates make `QUALIFIED`; institutional report preferred as representative; `raw_value` capped;
`"Korea, South"` is one country; UK nations and Belgian communities collapse; unmapped name reported
and skipped; blank country keeps its listing; one ID counted once per country; every mapped code is
in `ISO_3166_ALPHA2_CODES` and Kosovo is absent; a missing column, an empty file, no registered agency
or a missing file refuses; the crosswalk returns the WHED IDs a row prints.

**WHED read, pure:** a one-result line for the ID with a matching row clears, with name and country in
`raw_value`; a no-match line makes no row even though the page prints the ID; a result line for another
ID, a count other than 1, a row carrying another ID, or no result line refuses; all-miss over a
non-empty set refuses; `raw_value` capped.

**The write, database:** a bound institution gets its listing citing the right page; an unbound value
is dropped and never bound; coverage counts all of DEQAR; a second read replaces the first; a verdict
disappearing counts as a change and an unchanged one does not; another publisher's rows are untouched;
two IDs bound to one institution keep the more cautious verdict; a crosswalk WHED ID is bound as
`CROSSWALK`, an existing binding is left alone, and one bound elsewhere is reported not written.

**The refresh:** DEQAR archives four files and cites `reports`; WHED runs one search per bound ID,
on the bare host, paced, and cites each search; an off-site redirect archives nothing; identical bytes
reuse snapshots; a report expiring overnight changes the verdict without new bytes; an unreadable
page leaves previous rows standing; the command prints its summary and turns a refusal into
`CommandError`.

**The fetch:** off-site `final_url` raises before `store.put`; no overrides still rejects
`application/octet-stream` and still caps at 10 MiB; the no-model-client scan covers the command
and the `refresh.py` import.

**Constraints:** `_AXES` and `_IDENTIFIER_SCHEMES` still equal their choices; a `WHED` value in the
wrong shape is refused by the loader.

**Live, under `-m live`:** DEQAR still serves the columns the read uses (range request, first 8 KiB);
WHED's search still answers `1 results found for (Global WHED ID=IAU-011713)` and
`No matching records for (Global WHED ID=IAU-000000)`.

**The §5 read rule** is pinned by `screen.py`'s own tests when it lands.
