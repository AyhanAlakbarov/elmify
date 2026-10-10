# Pooling a host's pages, and making money quote itself

Two changes to the Phase 5 discovery write path, decided together because they are the same defect
seen twice: **a required field with no way to say "not applicable" makes the model invent a value.**
`KeyDateClaim.on` invented a year (fixed 2026-08-30, PR #33). `MoneyClaim.currency` invents a
currency. And the reason 169 consortium sites produced 9 catalog rows is the mirror image — a
required field the page genuinely does not state discards everything else the page did state.

Evidence base: `docs/superpowers/research/2026-08-30-eacea-full-catalogue-run.md` §3 and §5b, plus
measurements taken over the cached extraction corpus during design (method and numbers below).
Nothing here was re-extracted; all 595 model calls were made on 2026-08-30 and replayed from cache.

## Part 1 — Pooling a host's pages

### The problem is a gate, not a claim

`resolve_program` (`apps/research/catalog.py:72`) needs five facts from **one** `ExtractedClaims`:
institution, programme name, country, a cited teaching language, and a duration of 1-60 months.
Missing any one returns `None`, and the page contributes nothing — not even the facts it did state.

§3 measured what is missing across the 429 pages that extracted: teaching language on 343, country
on 291, duration on 290, institution on 234. Almost every page names the programme; almost none
names all five.

**Each `OfficialEvidenceClaim` attaches to its own snapshot.** So pooling never has to flatten
provenance: pages pool only the five gating facts, and every claim *extracted from a page* still
cites that page. This is what makes the change small. Two rows are the exception, and were already:
`claim_rows` (`catalog.py`) builds an `IDENTITY` row and a `Programme duration:` row from the
*resolved* programme, not from the page's own claims, so they carry no quotation regardless of
pooling -- pooling widens who can produce a resolved programme, it does not create this property.
(Correction, whole-branch review: this section previously overstated the claim as universal.)

### Where the vouching lives: the source, not the lead

Merging is the inverse of a decision made deliberately last week. `pipeline.py:222-232` drops seed
identity when hopping one page inside a host, because *"the catalogue vouched for the front door,
not for every page behind it -- one university host serves many programmes."* Pooling re-joins what
that rule separated, so it must state what licenses the re-join.

Two candidates were rejected:

- **`lead.identity`** — nothing in `apps/research/` ever constructs a `LeadIdentity`.
  `HtmlCatalogue`'s docstring says so outright: identity is not read off the listing. Every EACEA
  lead has `identity=None`, so a rule resting on it pools nothing today.
- **`lead.source_type == "PROGRAM"`** — set per-lead by the caller and only ever *downgraded* to
  `AGGREGATOR` by `from_url`. It does not assert one-programme-per-site, so a search-discovered
  university front door could carry it.

The property belongs to the **source**: EACEA's listing is one row per EMJM programme, and that is a
fact about the listing, not about any lead off it. So `HtmlCatalogue` (a frozen config dataclass)
gains one declarative field:

```python
#: Whether each harvested link is one programme's own site. EACEA's listing is
#: one row per EMJM consortium; a search provider's results are not.
one_programme_per_link: bool = False
```

EACEA sets it `True`. Search and entity-expansion sources leave it `False` and never pool. The Korea
and Finland registries (increments 2-3) may set it `True`, because they enumerate programmes.

### How the flag reaches the write loop

`collect_leads` flattens every source into one queue, so by the time `run_discovery`'s write loop
runs the source object is gone — a lead carries only `discovered_by: str`. The seam already exists:
`_tagged` (`discovery.py:361`) stamps `discovered_by=source.name` onto each lead as it leaves its
source. It stamps the pooling flag the same way, and `ResearchLead` gains one field:

```python
#: Set by _tagged from the source that produced this lead, never by a caller.
one_programme_per_site: bool = False
```

A hop's `lead.replace(...)` carries it, which is correct — the hopped page is on the same host from
the same source. Nothing else may set it, for the same reason `from_url` only ever *downgrades*
`source_type`: a lead must not be able to promote itself.

**Protocol note.** `one_programme_per_link` must be declared on `LeadSource` as a read-only
`@property`, not a plain attribute. That protocol's own docstring records why: every implementation
is a frozen dataclass, and mypy refuses a frozen field against a settable protocol member
("expected settable variable, got read-only attribute").

### The pool group

`(source, host)`. A hopped page joins the group of the parent it was derived from — never a sibling.
Pages whose source does not vouch are never pooled, and behave exactly as today.

### What pools

The five gate fields only. Claims never pool.

### Conflict rules

Measured over the cached corpus, restricted to the 25 hosts that union completes:

| gate field | hosts disagreeing | rule |
|---|---|---|
| `country_code` | 0 of 25 | disagreement ⇒ refuse the host |
| `duration_months` | 2 of 25 | disagreement ⇒ refuse the host |
| `teaching_languages` | — | union |
| `institution_name` | 11 of 25 | front-door page wins |
| `program_name` | 21 of 25 | front-door page wins |

**The split is the design.** The name fields disagree cosmetically and constantly — `master wocc` vs
`master wocc: contemporary challenges in the worlds of work`, and one host differing only in a curly
versus straight apostrophe. The fact fields disagree rarely and meaningfully: `[6, 36]` on
`life.univ-cotedazur.eu`, `[24, 36]` on `www.ntnu.edu`.

Refusing on a name variant would discard 21 of 25 rows to punish punctuation. Picking a winner on a
duration contradiction would invent a fact — the same failure this whole increment exists to stop.
"Front door wins" is provenance-anchored: it is the page the catalogue vouched for, not a
longest-string heuristic.

### How it attaches to the loop

The pipeline streams fetch → extract → write per source, so it cannot gate on a group it has not
finished reading. Minimal change:

1. Pages that resolve on their own keep writing immediately. **No behaviour change for the current
   nine rows.**
2. Pages that fail the gate are buffered per group with their `(lead, claims, source, snapshot)`
   instead of immediately opening a `ConsultantResearchTask`.
3. At end of run each group's pooled facts are resolved once. Held pages write against them; groups
   that still do not resolve emit the blocked tasks they would have emitted anyway.

No re-fetch, no second pass, no extra model calls — the held claims are already in memory. A held
page's row upserts onto the same `Institution`/`Program` a streaming write may already have created,
because `catalog_key` dedupes on those names.

### Expected yield

**8 → 23 rows.** Union completes 25 hosts; two are refused on a duration contradiction.

### What this deliberately does not solve

- **Institution name variants across hosts.** `ccd-stede.eu` yielded both "University of Padua" and
  "Università degli Studi di Padova"; `catalog_key` (`discovery.py:162`) is `casefold` + trim, so no
  normalization rule joins them. That needs an external canonical handle, which is **increment 4's
  ROR frame** in `2026-08-28-funding-led-discovery-design.md`. Pooling must not make it worse; it
  does not attempt to fix it.
- **The 109 hosts still incomplete after union.** §3: dominated by joint degrees run by consortia in
  several countries, which have no single institution or country to state. That is a modelling
  problem in `Program`, not an extraction one.

### A limitation found in the final review: pooling is a whole-run operation

A byte-identical page short-circuits at the `unchanged` path in `pipeline.py` -- `touch_claims` and a
`continue` -- *above* the point in the write loop where a page's claims are appended to `pooled`. So
on an incremental re-run, an unchanged page contributes nothing to its group: it is neither refetched
nor re-extracted, and its gate facts simply are not there for its siblings to pool against.

Two consequences follow, and the second is the sharper one:

- A held page that resolved against its group on a previous run can fail and open a
  `ConsultantResearchTask` on a later run, if the run that supplied the fact it depended on is not
  the one being replayed.
- If a *partial* pool still completes -- some but not all of a group's pages present in this run's
  `pooled` -- a different page can become the de facto front door than the one that would have won
  had every page been present, and `catalog_key` can then fork a **second `Program` row** under a
  different name variant. This is the same name-variant forking §"What this deliberately does not
  solve" already names, produced by a different mechanism: not cross-host spelling, but cross-run
  front-door drift.

**This is why pooling should run over a full corpus, not an incremental delta.** The general answer to
name-variant forking either way is the ROR canonical-identity increment already planned above; this
limitation does not need its own fix, because it is a special case of a problem that increment already
solves.

**Do not attempt to fix this in code.** An unchanged page's claims are stored as `OfficialEvidenceClaim`
text rows, not as a reconstructable `ExtractedClaims` -- the structured object pooling needs is gone by
the time a later run sees the page as unchanged. Fixing this means re-extracting the unchanged page,
which is exactly the cost the `unchanged` short-circuit exists to avoid paying.

## Part 2 — Making money quote itself

### Measured: 618 money claims in the corpus

| currency emitted | count | what it actually is |
|---|---|---|
| EUR / GBP / USD | 595 | real |
| `PCT` | 4 | percent |
| `NOM` | 4 | nominal |
| `VAR` | 3 | variable |
| `DUR` / `SCH` / `UNP` | 2 each | duration, scholarship, unpaid |
| `INS` / `SEM` / `NOT` | 1 each | instalments, semester, "not specified" |

**20 claims whose currency is not a currency.** `MoneyClaim.currency` is `Field(pattern=r"^[A-Z]{3}$")`,
which accepts any three capitals, so a model with nothing to say says `NOT`. Six further claims carry
labels naming a duration outright ("Scholarship duration", "Standard duration", "Monthly allowance
maximum duration").

### Three fixes, all reusing machinery this repo already has

1. **A real currency check.** `apps/reference_data.py` exports `ISO_4217_CODES`, pinned to SIX's list
   one with revision, retrieval date and SHA256. `apps/funding/models.py` already enforces it as
   database CHECK constraints (`funding_benefit_currency_iso4217`,
   `cost_component_currency_iso4217`). **The database already refuses these values; only the
   extraction schema does not.** Four fields in `extraction.py` carry the loose pattern — lines 41,
   162, 213 and 294 — so this is fixed at all four, not on `MoneyClaim` alone.

2. **Money must quote itself.** `MoneyClaim` is the only claim type in the schema with no `evidence`
   field. `KeyDateClaim`, `TeachingLanguageClaim`, `CountClaim`, `AwardTermsClaim` and
   `EligibilityCriterionClaim` all have one. That absence is exactly why a fabricated `SEK` was
   invisible to every automated check, and why the date fix's remedy — keep the citation, withhold
   the parse — was unavailable here. `MoneyClaim` gains `evidence`.

3. **The shape for "a number that might not be money" already exists.** `EligibilityCriterionClaim`
   solved this: a `kind` discriminator, an optional `comparable_currency`, and a validator reading
   *"only a means test carries a currency; others are durations"* (`extraction.py:177`). Money is
   made to match its own sibling rather than inventing a new pattern.

### Where the checks live: the catalog writer, not the schema

This applies the decision made for the date defect on 2026-08-30, unchanged and for the same reason:
a Pydantic validator rejects the **whole response** over one field. On the date defect that discarded
13 pages' worth of institutions and funding claims to punish one date.

So `evidence` is added to the schema with a default of `""` — it is how the model returns the value —
and the **rejection happens in `catalog.py`**. A money claim that fails its checks is not emitted as
a money row.

This has a second benefit that the sequencing depends on: because `evidence` defaults, the 138 cached
pages carrying money claims still parse, so Part 1 keeps its five-second replay.

### Not building: a duration claim type

Six claims of 618, and nothing in the codebase consumes a grant's duration — `ExtractedClaims.duration_months`
is the *programme's*, not the award's. The duration-shaped money claims are dropped. A claim type gets
added when a consumer exists, not before.

### Honest limit

**The ISO check does not catch either case from §5b.** `SEK` and `EUR` are real currency codes and
pass the list. Only the evidence rule catches `6 SEK per MONTHS` on a page containing "SEK" zero
times — and the evidence rule cannot be verified from the cache, because today's `MoneyClaim` carries
no evidence to replay.

## Sequencing and verification

Three steps, cheapest first, each independently verifiable:

| step | verification | cost |
|---|---|---|
| 1. Pooling | replay the write pass from the cached corpus; expect 8 → 23 rows | ~5 s, no model calls |
| 2. ISO currency check (4 fields) | replay; expect the 20 non-currency claims gone | ~5 s, no model calls |
| 3. `MoneyClaim.evidence` + writer rule | fresh extraction over a ~50-page sample: the 20 fake-currency pages, the 6 duration-labelled ones, and a control set | ~50 model calls |

Step 3 is the only one costing model calls, and it is ~50 rather than another 595.

**Do not re-run the full extraction.** The corpus is 595 calls / 2.19 M in / 445 k out, made
2026-08-30.

## Constraints honoured

- **Shared-catalog writes.** `Institution` and `Program` are read by every tenant
  (`tests/tenancy/test_database_isolation.py::_SHARED_TABLES`). Pooling changes which rows appear
  there, so this plan takes an independent read-only review before execution.
- **Rate limiting.** Part 1 adds no model calls. Step 3's sample extraction goes through the existing
  `extract` path, which already carries `rate_limited("discovery-extraction", ...)`
  (`pipeline.py:308`). No new LLM-calling surface is introduced, so CLAUDE.md's
  rate-limit-in-the-same-change rule is satisfied by construction.
- **Provenance.** Claims never pool; each stays attached to the snapshot it was extracted from.
- **Catalogues route, they do not claim** (design §2.5). `one_programme_per_link` grants a listing no
  power to supply a fact — only to say that its links are one programme each. Every gate fact still
  comes from the programme's own page.

## Method, so the numbers can be re-derived

Both measurements are pure arithmetic over `claims.jsonl` (595 lines, one JSON record per fetched
URL, `claims` holding the serialized `ExtractedClaims`). Grouping is by `urlsplit(url).hostname`;
string fields normalized with whitespace collapse + `casefold` to match `catalog_key`. Conflict = more
than one distinct non-null value across a host's pages. Reproduces §3's 8 and 25 exactly, which is
what licenses trusting the rest.

## Open items

- **The corpus is preserved outside the repository, not in it.**
  `~/.local/share/tehsil_agent/2026-08-30-eacea-claims.jsonl` (1.3 MB, sha256
  `8da484632e56222c...`) is the artifact of 595 model calls, and every verification step above
  replays from it. It was copied there from an ephemeral job directory during design. It is third-party
  page content, so it stays out of git deliberately — but it is also not backed up, and losing it turns
  steps 1 and 2 back into re-extractions.
- **`duration_months` conflicts are measured on one corpus.** 2 of 25 makes "refuse" cheap here. If a
  registry states duration inconsistently at scale, this is the rule that will hurt, and it is a
  one-line change to revisit.
- **`MoneyClaim.period` is a free string** with at least 15 spellings in the corpus (`monthly`,
  `per month`, `month`, `per annum`, `per year`, `year`, `academic year`, …). Not fabrication, so out
  of scope here — but it is the next thing that will make a money row unreadable.
