# The funder already knows who the partners are

## 0. Scope

Where the list of universities awarding a joint programme comes from, and how each one is bound to
a register code without a person typing it.

**In scope:** the EACEA project API as the partner source; the website join against DEQAR; what is
persisted; what reaches a human.

**Out of scope:** `apps/research/screen.py`, still unbuilt. The
`propose_institution_identifiers` command (2026-09-07 binding design §6), still unbuilt — this
design overlaps its purpose and §8 records what that means. Non-EMJM programmes: `seed:eacea` is
the only catalogue seed, so every programme in the catalogue today is an EMJM.

## 1. The problem this replaces

The 2026-09-13 providers design leaves a joint programme with `institution=None` and the scraped
provider string in `provider_text`, awaiting a curator. It assumed the curator would read the
consortium's own page. Two measurements say there is a better source.

**Measured 2026-09-13 — scraping a consortium's page works but under-recovers.** 16 real EMJM
consortium sites, every outbound link resolved against DEQAR's published websites: 36 partners
matched, **zero wrong**, but 3 of 16 pages yielded nothing at all (JavaScript-rendered, no links in
the HTML) and several consortia simply do not link every partner. Precision was never the problem;
recall was.

**Measured 2026-09-14 — the funder publishes the partner list.** Every EMJM is an EU-funded project,
and the Erasmus+ Project Results Platform records each project's participating organisations with
name, country, city, PIC and **website**. That is the same join key, from the body that funded the
consortium rather than from whatever the consortium chose to hyperlink.

## 2. Reaching it — measured, because three earlier attempts were wrong

`CLAUDE.md` records EACEA detail pages returning HTTP 403 and concludes the platform refuses us.
That conclusion is wrong, and the correction is worth stating precisely so it is not re-derived:

- `erasmus-plus.ec.europa.eu/projects/search` returns **200**. `robots.txt` disallows `/search/`
  and `/search?` at the root, which do not prefix-match `/projects/search`; no rule mentions
  `/projects`. Crawling it is permitted.
- The page is a JavaScript shell. Its HTML carries a header, a disclaimer and a footer — no
  projects. Reading the HTML and concluding "blocked" is the first trap.
- `webgate.ec.europa.eu/eyp/valor/api` — the base string in the page's bundle — returns **403** on
  every path. This is the second trap: it is a base concatenated with a path at runtime, not the
  host actually called.
- The endpoint actually called is **`POST https://ec.europa.eu/programmes/service/search/project/search`**,
  and it answers **200 to plain `curl`** with no browser, no session and no token.

### 2.1 The request

```json
{"from":0,"index":"eplus2021","keyword":"","matchAllCountries":false,
 "project":{"projectLevel3":"43690363"},"coordinator":{},"partner":{},
 "organisation":{"organisationRole":"COORDINATOR_OR_PARTNER"},
 "size":400,"sort":"","withAggregations":false}
```

`Content-Type: application/json`, plus `Origin`/`Referer` of `erasmus-plus.ec.europa.eu`.

**The filter field is `projectLevel3`, not `level3`.** `level3` and `actionType` are accepted and
silently ignored — they return all 341,601 projects, which looks like a successful query. Any change
to the filter must assert the total, or a silent full-corpus fetch passes for a filtered one.

Two action codes, both required:

| Code | Label | Programme |
| --- | --- | --- |
| `43690363` | Erasmus Mundus Joint Master | 2021-2027 |
| `31046261` | Erasmus Mundus Joint Master Degrees | 2014-2020 |

### 2.2 Terms

The platform's Terms of Use govern **uploading**: every obligation attaches to submitting content.
Nothing restricts retrieval, and the platform's own stated purpose includes being a *"Source of
information for the Commission Open Data Portal"*. Downloading is referred to the Europa Legal
Notice, the Commission's standard reuse regime.

**This is why the DAAD rule does not bite here.** That adapter was never written because DAAD's
terms were *silent* on automated retrieval (2026-08-27 access-terms review). EACEA's are explicit
and point toward reuse. The rule is unchanged; the facts differ.

**And this is not the Tavily case either.** `CLAUDE.md`'s "never persist a provider result object"
governs *search providers*, whose licences forbid retaining results. EACEA is the funder publishing
its own grant records under an open-reuse notice. Persisting them is permitted. Do not generalise
the search-provider rule onto it, and do not generalise this onto a search provider.

## 3. What the API returns

Per organisation, verbatim field names:

```
organisationName      UNIVERSITE DE LIEGE
organisationPIC       E10209384
organisationCountry   BE
organisationCity      LIEGE
organisationWebsite   www.uliege.be
organisationRole      coordinator | partner
organisationIsConsortium  false
```

**Measured 2026-09-14 across both action codes:** 415 projects, 2,026 participation rows,
**576 distinct organisations**, 78% carrying a website.

## 4. The join: two identifiers that check each other

**Measured 2026-09-14 across 576 distinct organisations.**

| Disposition | Count | Share | Action |
| --- | --- | --- | --- |
| Both keys agree on a live institution | 277 | 48.1% | bind — confirmed twice |
| EU-PIC only | 137 | 23.8% | bind |
| Website only | 47 | 8.2% | bind |
| **Bound** | **461** | **80.0%** | every one a *live* institution |
| Keys disagree after succession | 1 | 0.2% | **human** |
| Website ambiguous, no EU-PIC | 5 | 0.9% | **human** |
| Closed, no successor recorded | 4 | 0.7% | silence |
| Neither key reaches | 105 | 18.2% | silence |

**A human sees 6 organisations out of 576 — 1.0%.**

### 4.1 EU-PIC is the primary key, because it is an identifier

Every EMJM organisation carries a numeric `organisationPIC` (576 of 576). DEQAR publishes `EU-PIC:`
in `identifiers_all`. The join is exact equality: 416 of 576 match outright.

**Do not judge this key by its global coverage.** DEQAR carries EU-PIC for 2,141 of 9,030
institutions — 23% — and that figure is what made an earlier draft of this spec dismiss it. On the
population actually joined against it is **72%**, because EMJM partners are EU grant participants and
therefore exactly the institutions that hold a PIC. Coverage measured over the wrong denominator
nearly discarded the best key available.

### 4.2 The website is the corroborating key, not the primary one

The registrable domain, walked suffix-wise so `cs.ulb.ac.be` resolves to `ulb.ac.be`. DEQAR
publishes a website for 8,527 of 9,030 institutions across 7,052 distinct hosts.

It is second because **a website is a contact detail, not an identifier**. Institutions change it:
Liège moved to `uliege.be`, and "City St George's University of London" is a 2024 merger. DEQAR
records whatever was current when the entry was last touched and nothing re-verifies it, so a
website join degrades silently over time — and degrades worst for merged and rebranded
institutions, which are the ones most worth getting right. An earlier draft made this the only key
and recorded the resulting 43 misses as an unexplained limit; EU-PIC recovers 33 of them exactly.

It still earns its place: 50 organisations resolve by website that EU-PIC cannot reach.

### 4.3 Never bind a closed institution — follow the succession

**A binding must land on an institution that exists now.** DEQAR keeps dissolved institutions as
rows, marked with `closure_date`, and publishes the succession in `historic_relationships`:

```
DEQARINST0948 University of Rennes 1   closed 2023-01-01
    "2023-01-01: was absorbed by DEQARINST9002 University of Rennes (EPE)"
```

**This is not a refinement, it is a correctness fix.** An earlier draft of this design bound **seven**
organisations to institutions DEQAR marks closed — Rennes 1, Lille, Montpellier, Nantes, Galway-Mayo,
Lusófona — and **two of those passed the both-keys-agree check**. A quality verdict attached to a
dissolved legal person is the wrong-entity failure the 2026-09-07 research is about, arriving
silently through the front door.

So each key resolves, then walks `succeeded by` / `was absorbed by` until it reaches a row with no
`closure_date`, bounded at four hops. 603 of DEQAR's 915 closed rows (65%) carry the relationship.

**This is also what makes the keys agree.** Two of the three apparent disagreements were never
disagreements: EU-PIC pointed at the predecessor, the website at the successor, and DEQAR states the
link between them.

| Organisation | EU-PIC resolved to | Website resolved to | After succession |
| --- | --- | --- | --- |
| Rheinland-Pfälzische TU | Kaiserslautern (closed 2023) | Kaiserslautern-Landau | agree |
| LAB-ammattikorkeakoulu | Lahti UAS (closed 2020) | LAB UAS | agree |
| EDEX Educational Excellence | European University Cyprus | University of Nicosia | **still disagree** |

EDEX is the genuine case and the reason a human stays in the loop: a Cypriot corporate group
operating two live universities, where the PIC is registered against one and the website belongs to
the other. No rule settles which institution awards the degree. That is a person's call, and it is
the only one left.

**Where a closed row records no successor** (4 organisations; Lille, Montpellier and Nantes are the
pattern) the design binds nothing and reports it. Guessing a successor from a name is the failure
this whole spec exists to avoid.

### 4.4 The Erasmus Charter code is not a third key

`Erasmus-Charter:` appears in 2,105 DEQAR rows and demonstrably joins — `E10209384` resolves to
`DEQARINST0073 University of Liège`. **Across all 576 EMJM organisations it matched zero**, because
`organisationPIC` holds a numeric PIC on EMJM projects and an `E`-prefixed Charter code only on the
mobility project where it was first tested. One match in a different project type is not coverage.

## 5. What is persisted, and what is not

**Nothing new is stored for EACEA.** The command writes exactly what the 2026-09-13 design already
defined: `ProgramAwardingInstitution` rows, and `Institution` rows for universities the catalogue
lacks. No project table, no organisation table, no PIC column, no cached API response.

The reason is the same one that governs the register adapters: provenance comes from the origin. An
`Institution` row's `official_website` is the university's own address; its register verdict comes
from DEQAR's own file. EACEA told us *which* universities to look at. That is a pointer, and a
pointer is not retained as an artifact.

**Writes stay in the checked-in CSV.** `docs/research/program-providers.csv` and
`load_program_providers` are unchanged and remain the only writer. The command in §6 **generates
CSV rows on stdout and writes nothing to the database.** A binding is a shared-catalog decision
every tenant reads; in a file it is a reviewed diff, attributable and revertable. Automating the
typing does not change who is accountable for the diff — which is the whole point of the file, and
the reason automation does not dissolve it.

## 6. The command

`manage.py propose_program_providers` — read-only, writes no database rows.

1. `POST` both action codes, asserting `total` is far below 341,601.
2. Index DEQAR's institutions file by registrable domain.
3. For each project, resolve each participating organisation.
4. Emit CSV rows for clean matches; emit a commented block naming each ambiguous organisation with
   its candidate DEQAR rows; count and report the silences by class.

A curator reads the diff, resolves the commented block by hand, and runs `load_program_providers`.

**It does not match a project to a `Program`.** That join does not exist yet and is §8's. The
command emits the EACEA project title beside each block so a human makes that call.

**It calls no model.** The 2026-09-13 design's fallback name rule and the Luna-read plan are both
unnecessary on this path: an API response and a database join have nothing to be confidently wrong
about. `CLAUDE.md`'s LLM rate-limiting rule is not engaged because no LLM is engaged.

**Outbound path.** This is a distinct outbound path, now recorded in `CLAUDE.md`'s Web-fetching
list alongside Scrapling and europass. It is operator-run, read-only, outside any request path, and
not behind `LocalEgressProxy` — which is correct for a command run by hand and wrong the moment
anything schedules it. See §8.

## 7. Testing

- **The filter is real.** A query asserting `projectLevel3` returns hundreds, not 341,601. This is
  the test that catches the silent-ignore trap in §2.1, and it is the most valuable test here.
- **The domain walk.** `cs.ulb.ac.be` → `ulb.ac.be`; `emabg.boku.ac.at` → `boku.ac.at`. Recorded
  fixtures, no network.
- **EU-PIC is tried before the website**, and a recorded fixture where the two disagree emits a
  comment for a human rather than a binding. This is the test that protects against the wrong-legal-
  entity failure; a change that makes one key win silently must fail it.
- **Ambiguity is not resolved by guessing.** An organisation whose domain matches two DEQAR rows,
  with no EU-PIC to settle it, emits a comment, never a CSV row.
- **Silence has classes.** No website, outside the EHEA, and unmatched-in-Europe are counted
  separately and reported separately; a test pins that an unmatched organisation emits no binding.
- **No model, no database write.** The module imports no OpenAI client, and a run leaves
  `ProgramAwardingInstitution` untouched.
- **Live, marked `live`** and excluded from a default run by `pyproject.toml`'s
  `addopts = "-m 'not live'"`: the endpoint still answers 200 and still returns the documented
  organisation fields, mirroring the register adapters' canaries.

## 8. What this does not decide

- **Matching an EACEA project to a `Program` row.** The catalogue is keyed on a scraped programme
  name; EACEA has its own title. Today a human reads both. Deferred deliberately — it is the same
  name-matching hazard the 2026-09-07 research measured, and it deserves its own measurement.
- **The 105 organisations neither key reaches, which are mostly not a gap.** Inspected: the majority
  are **not degree-awarding institutions at all** — CNR and CEA (national research councils), CEPS (a
  think tank), ICFO (a research institute), ALDA (an NGO), Göttingen's *university hospital*. DEQAR is
  a register of institutions that award degrees; omitting them is correct, and so is binding nothing.
  Counting them as a shortfall overstates the problem.
  The genuine remainder is roughly ten real universities, concentrated in **French reorganisations**
  (Clermont Auvergne, Grenoble Alpes, Bourgogne Europe, Rennes) where EACEA records no website and
  DEQAR records no EU-PIC, so neither key has data on both sides. Country-scoped name matching is the
  candidate repair and is unmeasured; it is smaller and safer than the global name matching the
  2026-09-07 research ruled out, but it is still name matching and wants its own measurement.
- **Re-checking the EU-PIC crosswalk over time.** DEQAR's `identifiers_all` is as maintained as any
  other field in it. Nothing here detects a PIC that DEQAR later corrects.
- **Scheduling.** The command is run by hand. Anything that schedules it must first put the fetch
  behind `LocalEgressProxy` and decide a cadence against a public EU endpoint.
- **`propose_institution_identifiers`** (2026-09-07 §6) is now partly redundant: that command was to
  query Wikidata and DEQAR to propose identifier bindings, which this does for EMJM partners from a
  better source. Whether it is narrowed or dropped is that spec's decision, not this one's.
- **Non-EMJM sources.** The 2026-09-13 name-shape fallback stays exactly as built, for leads from
  seeds that declare nothing. Nothing here removes it, and the consortium-page link scraping probed
  on 2026-09-13 is **not** built — it was a measurement, and this design supersedes its purpose.
