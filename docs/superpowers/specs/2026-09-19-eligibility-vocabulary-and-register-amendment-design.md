# One eligibility vocabulary, and the register amended to carry it

**Status:** approved by the owner 2026-09-19 ("if it is the best for our platform architectural
design" — the reasoning it rests on is §1). Refinements 1 and 2 of the build order in
`2026-09-19-coverage-driven-funding-engine-design.md`; both precede its build item 1.

Builds on: the engine design (this is its §6.1 made concrete), the recommendation-spine design
(§3.1–3.2 there name the two gaps this closes), the funder-reader design §3.1 (whose "eligibility
keys" row promised a vocabulary nothing implemented), and the organisation-register plan of
2026-09-18 (amended here before its Task 2).

## 1. Why this exists, and why now

**Four eligibility vocabularies coexist and none is the one the specs name.** Read from the code
on 2026-09-19:

| where | keys | role |
|---|---|---|
| `BenefitRule.ConditionType` (`apps/funding/models.py`, August) | WORK_EXPERIENCE, AGE_CAP, MEANS_TEST, AFFILIATION, LANGUAGE, GUARANTOR | what the catalog can store |
| `ApplicantConditionType` (`apps/funding/evaluation.py`) | the same six | what the evaluator can read |
| `validity.py::_CONDITION_FIELDS` | NATIONALITY, RESIDENCE, DESCENT, APPLICANT_CLASS, FUNDING, ROUTE, ROUND | whose deadline a date is |
| engine design §6.1 (prose) | eighteen keys from the funder spec §3.1 | what the reader should emit |

A writer for these — build item 2 — would write in one language and be read in another. The
evaluator today decides exactly **one** key mechanically (`WORK_EXPERIENCE` in months,
`_unmet_conditions`) and routes every other condition to review; so the shared engine the spine
design describes is real but tiny, and unifying it is a widening, not a rewrite.

**Why now:** there is no production database and **no code writes a `BenefitRule` row**
(`grep BenefitRule.objects.create` → nothing). Renaming the six stored values is a migration
that touches zero rows. The first real row ends that.

**The register plan is already outdated, by a measurement taken the day after it was written.**
Its `Organisation` has `registrable_domain … unique=True` — one domain per organisation. ROR
returned `bwstiftung.de` for the foundation whose scholarship lives on `bw-stipendium.de`
(`docs/research/2026-09-19-dual-seed-review.md`); under the plan those never join, and the award
rows built on 2026-09-18 key on `holder_domain`. Its `Kind` (HEI, HEI_UNIT, FUNDER_GOVERNMENT,
FUNDER_FOUNDATION, FUNDER_EMPLOYER, MULTILATERAL, INFRASTRUCTURE) is a second taxonomy beside
the fifteen holder types the reader writes on every award. It carries no read state and no
cadence, both of which the engine's Layers 1–2 read. And `FundingOpportunity.holder_domain` is a
string "because the register lives on another branch" — since the 2026-09-19 consolidation it
does not.

## 2. The vocabulary — `apps/funding/eligibility.py`

A pure module: the closed key list, the operators, the value forms, one decider per key. No
Django import. `apps/funding/models.py` imports the key tuple for its check constraint (same
app, no direction problem); `apps/research/funding_judge.py` imports the triple schema
(research → funding is the existing direction); `evaluation.py` and `validity.py` import the
deciders.

### 2.1 Keys

Closed. A condition a page states that fits no key is `OTHER` with the sentence kept — shown,
never dropped, always undecidable.

| key | value form | operators | decided from | today |
|---|---|---|---|---|
| `CITIZENSHIP` | country set | IN, NOT_IN | `profile.nationality` | decided |
| `RESIDENCE` | country set | IN, NOT_IN | `profile.country_of_residence` | decided |
| `DESCENT` | country set | IN | — (not collected) | review |
| `FIELD` | set of field names | IN | `profile.target_field`, `academic_history[].field` | match → satisfied; **no match → review, never failed** — "engineering" does not demonstrably exclude "robotics" |
| `PRIOR_DEGREE` | degree level held (`BACHELOR`, `MASTER`, `DOCTORATE`) | GTE, EQ | `academic_history[].qualification` | decided when the qualification maps to a level; else review |
| `PRIOR_INSTITUTION` | set of institutions, or of their countries | IN | `academic_history[].institution`, `.country_code` | country decided; institution name → review unless exact |
| `TALENT` | number on a named grading scale | GTE | `academic_history[].grade`, `.grading_scale` | decided only when the scales are the same string; grades are never converted (CLAUDE.md) |
| `WORK_EXPERIENCE` | months | GTE | `experience[].months` (WORK) | decided — the one key decided today, behaviour unchanged |
| `LANGUAGE` | language + level | PRESENT, GTE | `language_evidence[]` | presence decided; level decided only when both sides are CEFR |
| `AGE` | years at a reference date | LTE, GTE | `profile.date_of_birth` (**new**, §4) | review until collected |
| `GENDER` | enum | EQ | `profile.gender` (**new**, §4) | review until collected |
| `NEED` | amount + currency (a means test) | LTE | — | review |
| `REFUGEE_OR_DISPLACED` | bool | EQ | — | review |
| `DISABILITY` | bool | EQ | — | review |
| `EMPLOYMENT` | employer or sector label | EQ, IN | — | review |
| `AFFINITY` | membership label, optional organisation | PRESENT | — | review |
| `GUARANTOR` | bool | PRESENT | — | review |
| `OPEN` | — | — | — | satisfied — the page says "open to all" |
| `OTHER` | free text | — | — | review |

`UNSTATED` is not a key: a page that states nothing writes **no row**. Absence is the record of
absence.

**Two names differ from the funder spec's §3.1 list, on purpose.** `REGION` is a value form, not
a key: "citizens of Western Balkan countries" has to say whether it means citizenship or
residence, and a separate key cannot. `LEVEL` is `PRIOR_DEGREE`, so it is never confused with the
cell's `level` (the degree applied for). `AFFILIATION`, `AGE_CAP`, `MEANS_TEST` from the old
`ConditionType` are `AFFINITY`, `AGE`, `NEED`. `BLOC` and `BILATERAL_PAIR` from `nationality_shape`
map to `CITIZENSHIP IN <region>` and two `CITIZENSHIP IN` rows.

### 2.2 Value forms

- **country set** — a list of ISO 3166-1 alpha-2 codes, **or** a named region. Regions expand to
  country sets through one small data table (`REGIONS`: `EU`, `EEA`, `WESTERN_BALKANS`,
  `EASTERN_PARTNERSHIP`, `OECD`, `COMMONWEALTH`, `AFRICAN_UNION`, `ASEAN`, `GLOBAL_SOUTH`…),
  each row carrying its source URL. A region the table does not know is `OTHER` — undecidable,
  never guessed. The table is data; a new region is a row.
- **number** — `comparable_value` with `comparable_unit` (MONTHS, YEARS, HOURS) and, for `NEED`,
  `comparable_currency`. Exactly the columns `BenefitRule` already has.
- **enum / bool / label** — a short string.

### 2.3 The triple the reader emits

```python
class ConditionTriple(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: _Key                         # the closed list above
    operator: _Operator               # IN, NOT_IN, EQ, GTE, LTE, PRESENT
    value: str                        # as written by the page: "DE,AT,CH", "WESTERN_BALKANS", "35", "C1"
    unit: _Unit | None = None         # MONTHS, YEARS, HOURS, or a currency code
    quote: str                        # the sentence, verbatim -- quote verification covers it
```

`LineVerdict.conditions: tuple[ConditionTriple, ...] = ()` is the reader change (engine design
§6.1, build item 2), and `nationality_shape` stays as a coarse summary the pool can index on.
Three readings agree on a condition when they agree on `(key, operator, value)`; a split on any
of the three makes that condition undecidable — the tiered-agreement rule (§6.2 there) applied
per condition, never to the award.

### 2.4 The row — `BenefitRule`

`condition_type` is widened to the key list and renamed `key`; `operator` and `value` are added;
`comparable_value`, `comparable_unit`, `comparable_currency` and `rule_text` stay as they are;
the evidence join (`BenefitRuleEvidenceClaim`) is unchanged. The migration renames the six stored
values (`AGE_CAP→AGE`, `MEANS_TEST→NEED`, `AFFILIATION→AFFINITY`; the other three keep their
names) and touches no rows, because there are none.

### 2.5 The decision — one function

```python
@dataclass(frozen=True)
class Decision:
    outcome: Literal["SATISFIED", "FAILED", "UNDECIDABLE"]
    reason: str        # names the key, the bar and the profile fact -- or what the profile lacks

def decide(condition: ConditionTriple | ApplicantConditionFact, profile: StudentProfileSnapshot) -> Decision
```

One decider per key in a table; a key with no profile source returns `UNDECIDABLE` with the
reason *"the profile does not carry <field>"*, which is also the sentence the consultation-gap
report reads. `_unmet_conditions` becomes the `FAILED` filter over `decide`, and
`unevaluable_condition_reasons` the `UNDECIDABLE` filter — both are thin wrappers, so the 41
evaluator tests pass unchanged and every new key is one row in the table, not a new function.
`validity.py::_CONDITION_FIELDS` is replaced by importing the `CITIZENSHIP`/`RESIDENCE`/`DESCENT`
deciders; its four deadline-partition keys (`APPLICANT_CLASS`, `FUNDING`, `ROUTE`, `ROUND`) move
into the same module as a separate, clearly-labelled tuple — they say *whose deadline*, not
*who is eligible*.

**Programmes use the same rows.** `BenefitRule.benefit` becomes nullable and a check constraint
requires **exactly one** of `benefit` (a funding route's condition) or `program` (a programme's
admission condition — the `program` FK the table already carries). Same key, same decider, one
gate for both kinds of thing (spine design §4). Today every row has a benefit, so the constraint
is added satisfied.

**Correction (Task 5 review):** the paragraph above is wrong about `program` being free to
repurpose — `benefit_rule_scope_shape_valid` already requires `program` non-null whenever
`scope_type="PROGRAM"`, so that column already means *the scope a benefit's rule is narrowed to*,
and a benefit's rule may legitimately carry both `benefit` and `program` (an existing, tested
capability: `test_rule_accepts_intersecting_and_disjoint_stored_scopes`). The constraint actually
implemented is therefore **at least one** of `benefit`/`program`, not exactly one, named
`benefit_rule_target_present`. Four shapes, distinguished by which column is null: `benefit` set +
`program` null is a funding route's condition; `benefit` set + `program` set is that route's
condition narrowed to one programme (unchanged); `benefit` null + `program` set is the programme's
own admission condition (no route to confuse it with, since there is no benefit); both null is
rejected.

## 3. The register amendment — before the plan's Task 2

Five changes to `2026-09-18-organisation-register-and-provider-protocol.md`.

**3.1 Domains plural.** A new `OrganisationDomain(organisation FK PROTECT, registrable_domain
unique, found_via, first_seen)`. `Organisation.primary_domain` stays unique for display and as
the default key; every other domain is a row. `record_organisation` (Task 3) looks up **any**
domain first; a new domain attaches to an existing organisation when they share an
`OrganisationIdentifier` (ROR, Wikidata, EACEA PIC) — the plan's own table is the merge
mechanism — and never on a name match alone (the resolver measurements' lesson).

**3.2 One taxonomy.** `Organisation.kind` takes the holder vocabulary
(`funding_judge._HOLDERS` / `models._HOLDER_VALUES`) instead of the plan's seven values: a
funder's kind *is* its holder type; a university is `INSTITUTION`; a faculty is `INSTITUTION`
with `parent` set. **The holder vocabulary gains `RESEARCH_INSTITUTE`** (owner decision
2026-09-19, on this design's recommendation): Max Planck, CNRS, Fraunhofer, EMBL fund master's
theses and fit none of the fifteen. It maps to `FundingFamily.RESEARCH_ECOSYSTEM_PATHWAY` in
`_FAMILY_BY_HOLDER`, joins the judge's prompt text, `_HOLDER_VALUES`, and the check constraint —
one value, one migration.

**3.3 A real link.** `FundingOpportunity.organisation = ForeignKey(Organisation, PROTECT,
null=True)`, backfilled from `holder_domain` through `OrganisationDomain`; the scope-shape
constraint for `HOLDER` requires `organisation` non-null instead of `holder_domain != ""`; the
string column is dropped in a later migration once a test asserts every `HOLDER` row has the FK.
Award identity follows the engine design §6.3 — `(organisation, page, heading, kind)` — and
becomes buildable only with this FK.

**3.4 Read state.** Three fields on `Organisation`: `last_read_at`, `pages_read`,
`pages_unreadable`. Per-host, per-rung cost already lives in `HostFetchCost` (research app,
keyed by host); an organisation's cost is the sum over its domains.
`ponytail:` latest-state fields, not a history table — a table when someone needs to ask "what
did we read last month", not before.

**3.5 Cadence.** The five nullable fields the funder spec §3.5.1 names — `cadence`,
`cadence_open_month`, `cadence_deadline_month`, `cadence_source`, `cadence_verified_for_cycle` —
consumed unchanged by `validity.RegisterCadence`.

Nothing about cells goes on the organisation: its `country_code` is its home; the countries it
funds are derived from its awards' cells.

## 4. The profile — what the consultation starts asking

Owner decision 2026-09-19. Two fields unlock the two conditions funders use most:

- `date_of_birth` — national schemes cap at 30–35 constantly. Decides `AGE`.
- `gender` — women-in-STEM awards are common; enum with *prefer not to say*. Decides `GENDER`.

**Not asked, always review:** `DISABILITY`, `REFUGEE_OR_DISPLACED`, `NEED` (income) — special-
category or near it; the review path handles them honestly and a counsellor asks in person.
`DESCENT` also stays review until a diaspora corridor makes asking worth it. Both new fields are
optional in the consultation; a blank answer makes the condition `UNDECIDABLE`, never `FAILED`.

## 5. The gate harness

`funding_yield` fetches through the vendor ladder: one seam, `fetch_official_source` →
the path `retrieve_official_source` now takes (`fetch_via_vendors` on refusal or shell). Without
it, gate 3.4 re-measures the JavaScript shells already closed.

## 6. Testing

- `eligibility.py`: table-driven, one row per key × outcome, including every "review until
  collected" key returning `UNDECIDABLE` with the naming reason; a region the table lacks →
  `OTHER`; scales that differ → `UNDECIDABLE`; `FIELD` no-match → `UNDECIDABLE`, never `FAILED`.
- `evaluation.py`: the existing 41 pass unchanged (the wrappers are behaviour-preserving) plus
  one per newly decidable key.
- `validity.py`: the existing table passes unchanged after the import swap.
- register: two domains one organisation; a domain attaching via a shared ROR id; a name-only
  match **not** merging; the `HOLDER` scope refusing a row without `organisation`; backfill
  covers every `HOLDER` row.
- migration: `makemigrations --check` clean; the rename migration applies on an empty table.

## 7. What this changes in other documents

- Register plan: Tasks 2–3 amended per §3; Task numbering unchanged.
- Engine design §6.1 → points here instead of listing keys in prose.
- Funder spec §3.1's "eligibility keys" row → points here; its `REGION`/`LEVEL` names noted as
  superseded.
- Holder-axis plan Task 4's canonical key → superseded by engine design §6.3 (already recorded
  there).

## 8. Deliberately not built

A rules engine or DSL (plain conditionals per key, as everywhere in this repo). Grade-scale
conversion (one-way, never; `TALENT` decides only on identical scales). Fuzzy field matching in
the gate (discovery does field matching by embedding at query time — owner decision D.5; the gate
matches or reviews). A history table for read state (§3.4). Asking for the sensitive-category
fields (§4).
