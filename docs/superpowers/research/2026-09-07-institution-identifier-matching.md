# Binding a register row to an institution — what the identifier landscape actually offers

**Measured 2026-09-07.** Answers the "untested" item in
`../specs/2026-08-31-institution-safety-screen-design.md`: *how a listing is matched to an
`Institution` when `ror_id` is blank.*

**Every number here is a snapshot of a moving target.** The UK register republishes (the file read
below is dated `2026-09-07` in its own filename) and Wikidata changes continuously. Re-run the
commands rather than trusting the figures if more than a few weeks have passed.

## Provenance — read this before quoting anything below

Two tiers, and they are not equally strong:

- **MEASURED.** Run in this session against the live source, command recorded. Reproducible.
  Sections 1, 2, 3, 4 and the endpoint shapes in section 5.
- **RESEARCHED.** Reached through `gptr-mcp` web research, i.e. an LLM reading pages. The claim is
  attributed to a URL but *the page was not read directly* unless marked otherwise. Section 6.
  Treat as a lead, not a fact, and re-read the primary document before it becomes a design constraint.

---

## 1. MEASURED — the UK sponsor register publishes no identifier at all

Source: <https://www.gov.uk/government/publications/register-of-licensed-sponsors-students>
Asset fetched: `https://assets.publishing.service.gov.uk/media/6a9ea00901bbff0bf8f97ed7/SP_-_Student_and_Child_Student_Web_Register_-_2026-09-07.csv`
(122,473 bytes, 1,307 lines including header.)

The complete column list:

```
Sponsor Name,Town/City,Additional Locations,Sponsor Type,Status,Route,Immigration Compliance
```

**There is no identifier column of any kind** — no UKPRN, no licence number, nothing. This is a
known and publicly complained-about defect in the publication, not an oversight on our reading.

**1,306 data rows collapse to 943 distinct sponsor names.** The spec's note ("one row *per route* —
dedupe on name") is confirmed: an institution licensed for both Student and Child Student routes
appears twice. `Town/City` is present and does real disambiguation work — *Abbey College Cambridge*
and *Abbey College Manchester* are separable only by name plus city.

## 2. MEASURED — Wikidata carries the national codes ROR refuses to

Queried against `https://query.wikidata.org/sparql`:

| Property | What it is | Items | Also carry a ROR ID (P6782) |
| --- | --- | --- | --- |
| `P4971` | UKPRN / UKRLP ID | **27,430** | **347** (1.3%) |
| `P2651` | CRICOS Provider Code | **284** | 62 (22%) |
| `P1771` | IPEDS UNITID | **3,856** | **3,222 (84%)** |

Two conclusions follow, and they point opposite ways:

- **ROR is not the hub.** Only 347 of 27,430 UKPRN-bearing items have a ROR ID, because ROR covers
  research organizations and the UK sponsor register is mostly independent schools and private
  colleges. Routing UK matching through ROR discards 99% of the available index.
- **For the US it very nearly is.** 84% ROR coverage on IPEDS makes the US the one destination where
  a public crosswalk does most of the work unaided.

`P2651`'s 284 items are thin against CRICOS's provider population. **This costs convenience, not
correctness** — CRICOS prints its provider code in the register itself, so a human types a durable
code once; Wikidata would only have saved the typing.

## 3. MEASURED — no Wikidata property exists for DLI, NZQA, or SEVIS

`wbsearchentities` with `type=property` against `https://www.wikidata.org/w/api.php`, for
*designated learning institution*, *DLI number*, *NZQA provider*, *New Zealand education provider
code*, and *SEVIS school code*: **zero results each**. The same search for *IPEDS* returns `P1771`,
which confirms the method finds properties when they exist.

Canada and New Zealand therefore have **stable register codes and no public crosswalk**. Their
binding is a one-time human act, after which the register's own code is the permanent key.

## 4. MEASURED — the match probe, and the trap it exposed

Normalized the 943 UK sponsor names and the 24,664 distinct normalized labels among the 27,430
`P4971` items (lowercase; `&`→`and`; strip punctuation, `the`, and `ltd|limited|llp|plc|inc|uk|t/a`),
then joined on exact normalized equality:

```
unique UKPRN match :  477  (50.6%)
ambiguous (>1)     :   27  ( 2.9%)
no match           :  439  (46.6%)
```

**50.6% is a floor, not a ceiling** — a ten-line normalizer with no Wikidata alias lookup. Spot
checks confirm the matches are genuinely correct, including the hard pair (*Abbey College Cambridge*
→ UKPRN 10029725, *Abbey College Manchester* → 10008891, correctly separated).

**The 2.9% ambiguous class is an exact-match failure, not a fuzzy one.** `St Joseph's College`
resolves to four distinct UKPRNs: 10006207, 10008514, 10032965, 10037493. No threshold prevents this,
because no threshold was involved.

**The 46.6% unmatched class contains the design's central hazard.** 28 sponsor rows are foreign
institutions or pathway colleges operating in the UK. Verbatim, name and town, from today's file:

```
American Institute for Foreign Study                                  London
American University of the Caribbean School of Medicine               Preston
Amity University (in) London (a trading name of Amity Global Education Ltd).  London
Anglo American Educational Services                                   London
Boston University London Programme                                    London
Bournemouth University International College                          Bournemouth
CAPA The Global Education Network Ltd.                                London
ETC International College                                             Bournemouth
Felixstowe International College                                      Felixstowe
Gemological Institute of America London (GIA England t/a GIA London)  London
Georgetown University (USA) UK Initiatives Organisation               London
Glasgow International College                                         Glasgow
Global Education Oregon in London                                     London
Luther College Study Centre                                           Nottingham
Nottingham Trent International College                                Nottingham
Oxford International College Brighton                                 Brighton
Paris Dauphine International                                          London
Pepperdine University (USA)                                           London
Richmond The American International University in London              566 Chiswick High Road
Samford University London Study Centre                                London
St. Lawrence University (USA) London Programme                        London
TASIS The American School in England                                  Egham
The American School in London                                         London
University of Brighton International College                          Brighton
University of Essex International College                             Colchester
University of Liverpool International College                         Liverpool
University of Nottingham International College                        Nottingham
University of the West of England Bristol's International College     Bristol
```

**This is the fail-open the screen cannot afford, demonstrated rather than argued.** Any matcher
loosened enough to recover recall binds `Boston University London Programme` to Boston University,
and `University of Brighton International College` to the University of Brighton. The resulting row
asserts a UK sponsor-licensing fact **against a legal entity that does not hold that licence** — into
`RegisterListing`, which every tenant reads, with nothing downstream able to distinguish it from a
sound binding.

Tightening does not escape this either: exact matching already produces the ambiguous 27. **The two
error classes are reached from opposite directions, so no single threshold avoids both.**

## 5. MEASURED (primary docs read directly) — DEQAR resolves Europe and only Europe

Fetched `https://docs.deqar.eu/stable/web_api_examples/` directly. Example #3 documents a real
identifier-lookup path, Bearer-authenticated:

```
GET https://backend.deqar.eu/webapi/v2/browse/institutions/resources/
GET https://backend.deqar.eu/webapi/v2/browse/institutions/by-identifier/{resource}/{value}/
```

The 34 identifier resources it returns, verbatim:

```
AD-national, BA-national, BG-ETER.BAS.NATID, BY-national, CZ-ETER.BAS.NATID,
DE-ETER.BAS.NATID, DE-HRK, DID-EBSI, DK-ETER.BAS.NATID, ELIAS.HS_ID, Erasmus,
Erasmus-Charter, EU-PIC, EU-VAT, FI-ETER.BAS.NATID, FR-ETER.BAS.NATID,
GB-ETER.BAS.NATID, GE-national, HR-Mozvag, HU-ETER.BAS.NATID, IE-ETER.BAS.NATID,
IT-ETER.BAS.NATID, KZ-national, local identifier, LT-ETER.BAS.NATID,
LV-ETER.BAS.NATID, MD-national, PL-ETER.BAS.NATID, PT-ETER.BAS.NATID,
RO-ETER.BAS.NATID, SCHAC, SE-ETER.BAS.NATID, SI-ETER.BAS.NATID, UA-national
```

**Every one is European.** No CRICOS, no DLI, no NZQA, no SEVIS. DEQAR is the right hub for the
~42 European countries and is *irrelevant to the four destinations the screen most needs* — Australia,
the US, Canada, New Zealand.

**Untested:** the endpoint requires a Bearer token nobody has requested. Documented, not exercised.

## 6. RESEARCHED — leads that still need primary reading

Reached via `gptr-mcp`, attributed but not directly re-read. Verify before relying on any of these.

- **ROR excludes national identifiers by policy.** `ror.readme.io/docs/mapping` reportedly states
  that `external_ids` supports exactly GRID, ISNI, Wikidata and Crossref Funder Registry, and that
  ROR's policy is to include "only globally unique persistent identifiers … which means that national
  and regional identifiers such as UEI and PIC are not included." *Consistent with the measured 1.3%
  UKPRN/ROR overlap in section 2, which is why it is credible — but it is still second-hand.*
- **DEQAR stores national identifiers per provider.** `docs.deqar.eu/stable/institution_data` shows
  an `IDENTIFIER` entity with examples `FR-SIREN`, `UK-PIN` (UK Register of Learning Providers,
  i.e. UKPRN) and `KZ-BIN`. Partially corroborated by the measured `GB-ETER.BAS.NATID` resource above.
- **CRICOS publishes a provider code as its linking key**, per the data.gov.au provider export
  documentation. Not verified against the actual CSV — **do that before designing the AU adapter.**
- **NZQA publishes a provider number** ("also referred to as the Ministry of Education number or
  provider code"), per `nzqa.govt.nz/providers`.
- **Canada's IRCC DLI list publishes DLI numbers** in the form `O19376023352`, per the canada.ca
  designated-learning-institutions page.
- **The OpenSyllabus `institution-identifiers` repo** maps ROR ↔ GRID ↔ Wikidata ↔ IPEDS UNITID.
  An existence proof of the crosswalk pattern, US-only. Licence and freshness unchecked.

## 7. What this settles, and what it does not

**Settled: nothing may auto-bind on a name.** Section 4 is the evidence — both error classes are
real, both are silent, and they are unreachable by one threshold. A confirmed binding must be
recorded as a durable identifier so no name is ever resolved twice.

**Settled: the automation available is per-country, not per-tier.** US ≈ free via IPEDS/ROR. UK ≈ half
proposable via Wikidata/UKPRN — the best external index sits over the register with the worst
identifiers. AU/CA/NZ print durable codes and need no index. Europe is DEQAR's already.

**Not settled, and not fabricable here: how many institutions this actually touches.** `Institution`
has no writer — nothing outside tests and migrations creates a row, and `canonical_key` is
hand-curated. The catalog is small and grows deliberately, so the human cost is bounded by *our*
catalog, not by 943 UK sponsors or fifteen registers. The real number is measurable only after the
first ingest.

**Correction, 2026-09-13:** "`Institution` has no writer — nothing outside
tests and migrations creates a row" is false and was false when written.
`write_catalog_entry` creates one per discovered lead. The count is 22 today.
See the 2026-09-13 providers design §1.1.

**Open, in descending order of how much they would change a design:**

1. Whether a Wikidata alias lookup lifts the 50.6% materially (one more SPARQL query).
2. Whether the CRICOS export's provider-code column is what section 6 claims (one download).
3. Whether DEQAR's `by-identifier` behaves as documented (needs a token request).

## Reproducing this

```sh
# UK register
curl -sL https://www.gov.uk/government/publications/register-of-licensed-sponsors-students \
  | grep -oE 'https://assets[^"]*\.csv' | head -1

# Wikidata coverage
curl -s -G https://query.wikidata.org/sparql -H 'Accept: text/csv' \
  --data-urlencode 'query=SELECT (COUNT(DISTINCT ?i) AS ?n) WHERE { ?i wdt:P4971 ?v }'

# DEQAR identifier resources (needs a Bearer token)
curl -s -H 'Authorization: Bearer ***' \
  https://backend.deqar.eu/webapi/v2/browse/institutions/resources/
```
