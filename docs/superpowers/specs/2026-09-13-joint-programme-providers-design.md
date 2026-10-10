# A programme has providers, not a provider

## 0. Scope

How a jointly-awarded master's programme names the universities that award it, and how the
platform stops inventing an `Institution` for one.

**In scope:** `Program`'s relationship to `Institution`; how `write_catalog_entry` decides whether
a lead is jointly awarded; the curation path that resolves a joint programme to real universities;
the three spec sentences this falsifies.

**Out of scope:** `apps/research/screen.py`, which does not exist. This design gives that spec one
rule (§5) and builds none of it. Also out of scope: the `propose_institution_identifiers` command
(binding design §6), which remains unbuilt and is the natural follow-up to §4 here.

## 1. The problem, measured

`apps/research/catalog.py::write_catalog_entry` creates an `Institution` per lead:

```python
institution, _created = Institution.objects.get_or_create(
    canonical_key=catalog_key(program_facts.country_code, program_facts.institution_name),
    ...
)
```

`catalog_key` is `trim + casefold` and nothing else. The name comes from a model reading a
programme's own page. For a jointly-awarded programme that name is several universities in one
string, or a consortium label naming none of them.

**Measured 2026-09-13 against the dev database's 22 `Institution` rows**, all written by
`manage.py discover`:

| Shape | Count | Example |
| --- | --- | --- |
| Names its members | 4 | `University of Belgrade; Libera Università Maria SS. Assunta (LUMSA); Örebro University`; `Art Academy of Latvia / SDSI consortium` |
| Consortium label naming no member | 3 | `ECT+ Consortium`, `Erasmus Mundus Journalism Consortium`, `Copernicus Master in Digital Earth consortium universities` |
| A single coordinator's name | 15 | `University of Glasgow`, `Université de Lille` |

**All 22 are joint programmes, including every row in the third group.** `default_sources`
(`pipeline.py:138`) registers exactly one catalogue seed, `seed:eacea`, whose listing is the EACEA
Erasmus Mundus register — one row per EMJM consortium, by definition every programme on it is
jointly awarded. The fifteen "single" names are coordinators, not sole providers. A name rule
cannot see this and neither can a domain rule; only the source knows.

Two further consequences, both measured:

- **The recorded website is the programme's, not a university's.** Of the 22 rows, 19 carry a
  programme site (`eusmat.net`, `ccd-stede.eu`, `master-wocc.eu`) and only 3 a university's.
  Joining the 15 plainly-named rows against DEQAR's 8,531 institution websites matched those same 3
  and missed 12, with no ambiguous match. `Institution.official_website` is `_origin` of the lead
  URL, which for a joint programme is the consortium's own site, so the column is not a usable
  binding key today.
- **The same university appears twice under two names.** `University of Padua` and
  `Università degli Studi di Padova` are one institution, two rows, one programme each. No
  normalisation reaches this: the strings share no substring. §4 notes how binding detects it.

`pipeline.py:468` had already measured the underlying shape from the other direction: on the
2026-08-30 replay, 110 programmes never stated a required gate fact, and the comment names the
cause as "joint degrees where four universities in four countries each publish their own partial
page."

### 1.1 Two specs assert the opposite, and the assertion is load-bearing

- `2026-09-07-institution-identifier-binding-design.md` §5: "`Institution` has no writer —
  `canonical_key` is hand-curated — so the catalog is small and grows deliberately." This is the
  stated justification for having **no candidate table** and for the human cost being "paid once,
  at a moment a human is already curating that row."
- The same design §9: "How many institutions this actually touches. Unmeasurable until
  `Institution` has a writer."
- `2026-09-07-institution-identifier-matching.md` §7: "`Institution` has no writer — nothing
  outside tests and migrations creates a row."

`write_catalog_entry` is called at `pipeline.py:402` and `:434`, from `run_discovery`, from
`manage.py discover`. The premise was false when written. §6 records the corrections.

## 2. Data model

Four changes to `Program`. No new entity: a joint programme is already a `Program` row, and a
consortium is a property of a programme rather than a place. `Institution` is unchanged — there is
no `CONSORTIUM` kind and no consortium row, ever.

- **`institution` becomes nullable.** A single-provider programme keeps exactly today's meaning. A
  joint programme leaves it empty.
- **`awarding_institutions`** — `ManyToManyField` to `Institution` through an explicit table, the
  shape `FundingOpportunity.programs` already uses.
- **`provision_type`** — `SINGLE` or `JOINT`, with a `CheckConstraint` in the idiom
  `FundingOpportunity.scope_type` established: `SINGLE` requires `institution` set, `JOINT` requires
  it null. The constraint is in the database rather than a validator because `catalog_ingestion` is
  a SQL-writing role that never runs Django model code.
- **`provider_text`** — the provider string as scraped, kept only on `JOINT` rows. This is the
  curation queue's payload: a human sees "University of Belgrade; LUMSA; Örebro University" without
  opening an archived snapshot to find it.

### 2.1 The uniqueness constraint must declare `nulls_distinct=False`

`Program`'s existing constraint is `UniqueConstraint(fields=("institution", "canonical_key",
"location_key"))`. Postgres treats `NULL` as distinct from `NULL` by default, so two joint
programmes sharing a key would both be accepted and the constraint would silently stop protecting
the exact rows this design creates most of. Django 5.2 and Postgres 17 (both in use here) support
`nulls_distinct=False`; it is required, not optional, and a test pins it.

## 3. The writer decides from the source, not the name

### 3.1 Primary rule: the seed declares it

A new boolean on the `LeadSource` protocol, `awards_jointly`, `True` on `EACEA_ERASMUS_MUNDUS` and
`False` by default. It is carried onto `ResearchLead` by `_tagged`, the mechanism
`one_programme_per_site` already uses, whose docstring states the property this depends on: "Set by
`_tagged` from the source, never by a caller — a lead cannot promote itself."

**Do not bind this to the existing `one_programme_per_site` flag.** They are different claims.
`one_programme_per_site` means one link is one programme; `awards_jointly` means the programme has
several awarding universities. EACEA is both. The Korea and Finland registry sources anticipated at
`pipeline.py:422` will be the first and not the second, and reusing the flag would mark every
Korean programme joint on the day that seed lands.

### 3.2 Fallback rule: the name's shape

For leads from a source that declares nothing — entity expansion, future non-catalogue seeds — the
provider name is joint if it contains `;`, contains ` / `, contains `consortium`, or ends in
`universities`, compared casefolded.

**Measured 2026-09-13.** Against the 22 dev rows: 7 of 7 composites flagged, 15 of 15 plain names
left alone. Against DEQAR's 9,030 real institutions: 19 flagged, 0.2%, in exactly two families —

- **Bilingual names joined by a slash.** `Universidad del País Vasco / Euskal Herriko
  Unibertsitatea`; `Kirchliche Hochschule Wuppertal / Bethel (ev)`; a Georgian school printed in
  Latin and Georgian script. One institution, two languages.
- **Finnish "University Consortium".** Kajaani, Kokkola, Lahti, Mikkeli, Pori, Seinäjoki — legally
  single institutions carrying the word.

The semicolon never fired falsely. Both families are pinned as test fixtures so a later change
cannot "fix" them into fake institutions, and §4's one-provider rule resolves them without a
special case.

**The bias is deliberate and must not be tuned away.** A false *joint* costs one human glance at a
queue and creates nothing. A false *single* mints an `Institution` that can never bind to a
register, which is the defect this design exists to remove.

### 3.3 What the writer does

**Joint:** write the `Program` with `institution=None`, `provision_type=JOINT`, `provider_text` set
to the scraped string. **No `Institution` row is created, and the string is not split.** Splitting
"Belgrade; LUMSA; Örebro" would produce names, and the matching research §7 settled that nothing
may auto-bind on a name; a split list is a convenience for the curator, deferred deliberately (§8).

**Single:** unchanged.

**Reporting:** `DiscoveryReport.degraded` gains one line, `N joint programmes await provider
resolution`, so the queue is visible as it grows.

A joint programme writes no `Institution`, so nothing records `eusmat.net` as a university again.

## 4. Resolving the queue

`docs/research/program-providers.csv`, checked in, one row per programme-university pair:
`program_key, institution_key, name, country_code, official_website`. A command
`load_program_providers` reads it and fills `awarding_institutions`.

A file rather than a database write, for the reason the identifier binding design already gives:
this is a shared-catalog decision every tenant reads, and in a file it is a reviewed diff —
attributable and revertable.

Three properties fall out:

- **It is the hand-curation path the two specs assumed existed.** A row naming an institution not
  in the catalog creates it from the last three columns. A person wrote that row, so
  `canonical_key` is hand-curated — true for the first time.
- **A one-provider joint programme resolves itself.** When a programme's rows name exactly one
  institution, the loader sets `institution`, flips `provision_type` to `SINGLE` and clears
  `provider_text`. The 0.2% of §3.2 need no separate command.
- **The Padua duplicate detects itself.** Binding both rows to the same DEQAR code violates
  `institution_identifier_scheme_value_uniq`, and `load_institution_identifiers` already renders
  that as "a duplicate institution row or a wrong binding, both need a human".

Insert-only, run under `DATABASE_ROLE=migration` or `catalog_ingestion`. An INSERT refused by RLS
raises, so a wrong-role run fails loudly — the trap `load_institution_identifiers` documents for
UPDATE and DELETE does not apply, and no guard is needed.

The curator's next step is the identifier CSV, binding each new institution to its register codes.
Two files, two loaders, one pattern.

## 5. The rule handed to the screen spec

**A joint programme is screened per awarding institution, never as a whole.** Padua clears, Örebro
clears, Belgrade unknown — three statements, not one. A joint programme never collapses to a single
verdict: "cleared" on the strength of one partner vouches for institutions no register assessed.
This is the safety-screen design's own rule — the screen clears providers, never qualifications —
applied where there are several providers.

`screen.py` does not exist. Nothing here implements this; it is recorded so that spec inherits it.

## 6. Corrections to existing specs

Each gets a dated correction pointing here, and is not deleted — `CLAUDE.md` records what one stale
"this is not built yet" claim cost a later session, and a stale "this is hand-curated" claim is the
same defect.

1. `2026-09-07-institution-identifier-binding-design.md` §5 — `Institution` has a writer.
2. The same design §9 — the count is measurable; it is 22 today, all from one seed.
3. `2026-09-07-institution-identifier-matching.md` §7 — same correction as (1).

## 7. Testing

- **The source rule.** A lead from an `awards_jointly` source is joint whatever its name. A lead
  from a `one_programme_per_site` *registry* source is **not** joint. The second test is the one
  that catches conflating the two flags.
- **The name fallback.** The 22 real dev names as fixtures; the Basque bilingual and Finnish
  "University Consortium" names pinned as **not** joint once resolved by §4.
- **The writer.** A joint lead produces one `Program` and **zero** `Institution` rows. This is the
  assertion the design exists for.
- **The constraint.** `SINGLE` with a null institution is refused; `JOINT` with one set is refused;
  two joint programmes sharing `(canonical_key, location_key)` are refused, which fails without
  `nulls_distinct=False`.
- **The loader.** Creates a missing institution; flips a one-provider programme to `SINGLE`;
  refuses under the ordinary runtime role via the `rls_enforced_orm` fixture
  (`tests/portals/test_rls_spine.py`). That last case is the coverage gap the register adapters
  still carry and it is not repeated here.

## 8. What this does not decide

- **Splitting a composite provider string into names.** Deferred: a name is not a binding, and the
  curator gets the raw string either way.
- **`propose_institution_identifiers`.** Unbuilt (binding design §6). DEQAR carries a website for
  94% of its institutions and an ETER code for 6,046 of 9,030, both deterministic keys, so a
  proposal command could reduce the human step to a confirmation. Measured here, designed
  elsewhere.
- **Whether a listing bound at campus level propagates to its parent.** Still open, still the
  screen spec's decision (binding design §9).
- **The existing 22 rows.** Every one is an artifact of the old behaviour and none is a real
  university. Nothing is deployed, so this is a dev-database delete and re-run, not a data
  migration.
- **Whether `discover` should create institutions at all once §4 exists.** It still does, for
  single-provider leads from future non-EACEA seeds. Revisit when such a seed lands.
- **A dedupe split this branch introduces.** `institution` is part of `write_catalog_entry`'s
  `get_or_create` lookup key, and `default_sources` registers both the EACEA seed and entity
  expansion. A programme reachable from both routes with an identical extracted
  `institution_name`, `program_name` and `country_code` now writes two `Program` rows -- one
  `JOINT` with `institution=None`, one `SINGLE` -- where before this branch both collapsed onto
  one. The unique constraint cannot catch it, because `provision_type` is effectively part of row
  identity but is not in the constraint. Deferred rather than fixed because this section already
  commits to wiping the existing 22 rows and re-running, and that re-run is the cheapest place to
  measure the real rate rather than guess it (probability is low -- the names must match after
  casefold and trim). Must be checked on that re-run.
- **`city` and `campus_name` borrowing the composite provider string.** `write_catalog_entry` sets
  both from `program_facts.city or program_facts.institution_name`, which pre-dates this branch. A
  joint programme that states no city therefore gets `city = "University of Belgrade; LUMSA;
  Örebro University"`. This branch establishes that the entire current corpus is joint, and joint
  programmes are the least likely to name one city, so what was an edge case is now the normal
  case. The consumer is `apps/funding/evaluation.py`, which matches a student's LOCATION
  non-negotiable against `candidate.city` -- such a programme would silently fail every location
  constraint. Nothing is broken today only because `CandidateFacts` has no constructor from
  `Program` yet. The fix -- leave `city` empty on JOINT rows rather than borrowing the provider
  string -- belongs with the first real curation pass, and must happen before anything builds
  `CandidateFacts` from a `Program`.
