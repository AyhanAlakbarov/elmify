# CV Rule Catalog — Design

**Status:** approved in brainstorming 2026-08-26, not yet implemented
**Scope:** turn the researched CV rules into data the render path actually enforces

## Problem

`docs/research/cv-rules.csv` (93 rules) and `cv-style-rules.csv` (24 rules) are
merged, evidence-backed and cited. None of them reach a rendered CV.

Three things are true today, each verified by reading the code:

- `Program.cv_constraints` is `JSONField(default=list)`. Nothing writes it.
- `constraints.py::rules_from_program` has no callers.
- `render.py::select_render_variant` has no callers, and
  `europass_render.py:153` calls `render_draft(draft=draft)` with no
  constraints at all.

So the enforcement machinery is built and tested, and has never been handed a
single rule. This design connects the two.

## Dependency: PR #19 must land first

`_check_prohibited_content` serves R-017 by detecting hyperlinks, and the things
it detects — `PersonalInformation.links` and `PublicationEntry.doi` — arrive in
PR #19 (`claude/cv-schema-completion`), which is open against master and not
merged. On master today there is nothing for that checker to find.

Implement this design on a branch taken **after** PR #19 merges. If PR #19 is
abandoned, drop `_check_prohibited_content` and R-017 from the seed; nothing
else in this design depends on it.

## The rules are not one kind of thing

Classifying all 93 funder rules by where they would have to live:

| Destination | Count | Exists? |
| --- | --- | --- |
| A "which format" setting | ~25 | `Program.cv_format_requirement` exists |
| A checkable constraint | ~30 | `ConstraintRule` exists; table to hold them does not |
| AI-use policy | 8 | Nothing. **Deferred — out of scope, see below** |
| Guidance shaping prompts and templates | ~30 | Stays in `docs/research/` |

The single most important consequence: **"seed the catalog" is not one
destination.** A design that put all 93 rules in one table would misrepresent
two thirds of them.

### Deferred: AI-use policy

Eight rules (R-050, R-087 to R-093) govern whether an applicant may use AI at
all. Cambridge prohibits it for CVs outright ("AI must not be used when writing
personal statements and CVs"), Oxford permits research but not generation,
Chevening takes a negative attestation on the form, and DAAD and Rhodes require
disclosure. R-093 names the field the research expects — `ai_use_policy` with
values prohibit / requires_disclosure / silent — and states that for funders
with no located policy, silence must **not** be read as permission.

This is a gate on generation, not a check on output: by the time a CV exists,
the prohibited act has happened. It is a different axis from every key in
`_CONSTRAINT_KEYS`, it is the sharpest risk in the catalog for a white-label
product, and the user has explicitly deferred it. It is **not** part of this
design and must not be quietly folded in during implementation.

## Architecture

```
docs/research/*.csv          research record, prose, human-authored
        │
        │  (one-time human curation, reviewed in the PR)
        ▼
apps/documents/catalog_seed.py   explicit rows: rule_id, scope, key, value,
        │                        enforcement, source_url, cycle
        │  seed_cv_rules (management command, idempotent)
        ▼
CatalogRule table  ────────►  resolve_rules(program, opportunity)
                                        │
                                        ├─► tuple[ConstraintRule, ...] ─► render_cv(constraints=…)
                                        └─► cv_format_requirement ─────► select_render_variant()
```

### Why a curated seed module, not a CSV parser

The CSVs cannot be parsed into rules mechanically, and pretending otherwise
would produce silent wrong data:

- The `Binding or advisory` column is prose in 18 of 93 rows — "binding
  (Scholar) / advisory (Student)", "binding (size) / preferred (format)",
  "binding where the destination requires it" — against a three-value enum.
- The `Scope` column is prose too, and inconsistent: `funder (SI SISGP)`,
  `country (US/CA/UK/AU)`, `track (research)`, bare `funder`, bare `country`,
  `discipline (Europe)`.
- Two thirds of the rules have no representable key at all.

Each of those is a human judgement. The seed module records the judgement once,
in reviewed code, with the `rule_id` and `source_url` copied from the CSV so
provenance survives. The CSV stays the research record; the seed module is the
enforceable subset.

**A rule absent from the seed module is not enforced, and that is visible** —
which is the property a silently-partial import would destroy.

### Why a shared table rather than rules in code

`Program` rows are already runtime data — `format_resolution.py` creates and
updates them from funder pages. Rules in code would mean programmes existing in
the database that cannot have rules until someone ships a release. For a
white-label B2B product that is also a sales problem: an agency taking a
student to a programme we never researched would wait on our release cycle.

### The tenancy boundary

`CatalogRule` is **shared across all tenants and never tenant-editable**. A
funder's requirement is the same fact for every agency; one agency editing a
shared rule would silently change another agency's output. Per-tenant judgement
already has a home in `ConstraintOverride`, which is a `TenantScopedModel`.

This mirrors `Program`, whose own comment records the same decision: a shared
catalog model, deliberately not tenant-scoped.

## Data model

### `CatalogRule` (new, shared, not tenant-scoped)

| Column | Type | Notes |
| --- | --- | --- |
| `rule_id` | `CharField(max_length=20)`, unique | `R-079`, `S-011` — the CSV's own ID |
| `scope_kind` | `CharField(choices)` | `UNIVERSAL`, `TRACK`, `COUNTRY`, `FUNDER` — four, not six; see below |
| `scope_values` | `ArrayField(CharField)` | Empty for `UNIVERSAL`. **A list, not a scalar** — R-032's scope is `US/CA/UK/AU`, four countries in one rule. Country values are ISO 3166-1 alpha-2, so the CSV's `UK` is stored as `GB` to match `Program.country_code` |
| `key` | `CharField(choices)` | Must be one of `constraints.py::_CONSTRAINT_KEYS` |
| `value` | `JSONField` | `2`, `false`, `{"experience": 3}`, `["fr", "en"]` |
| `enforcement` | `CharField(choices)` | `BINDING` / `ADVISORY_HIGH_RISK` / `ADVISORY_STYLE` |
| `rule_text` | `TextField` | Copied from the CSV, ≤1000 chars to match `ConstraintRule` |
| `source_url` | `URLField(max_length=2048, blank=True)` | |
| `verified_for_cycle` | `CharField(max_length=200, blank=True)` | **Prose, verbatim** — see below. 200, not 80: the longest value in the CSV is 82 characters (R-008) |
| `confidence` | `CharField(choices)` | `high` / `medium` / `low` |

`ArrayField` is already used in this codebase (`Program.teaching_languages`),
so it introduces nothing new.

### `verified_for_cycle` is prose, and is never parsed

The CSV's values are `evergreen`, `current`, `reverify`, `2026/2027`, `cycle
label unconfirmed`, `Class 22, 2026-28`, and `2027-2029 programme;
applications open 1 Nov 2026, deadline 10 Jan 2026 as printed`.

`Program.cv_format_verified_for_cycle` already made this call, with the comment:
*"Free text as printed on the funder's page, not a parsed cycle — the CSV's own
values are prose."* This design follows it rather than inventing a second
convention.

**Expiry never blocks a render.** A funder's page not having been re-read is
not evidence that the rule changed, and a rule that switched itself off on a
date would leave a student with no CV at their deadline. The cycle travels into
the violation text instead, so a human sees "per Rhodes, current template" and
can judge.

### `FundingOpportunity.cv_format_requirement` (new column)

`cv_format_requirement` currently lives only on `Program`, but ~19 of the format
rules belong to funders (Rhodes and SISGP mandate their own templates; AMIR,
GLOBED, MathMods, WE-TEAM require Europass; Stipendium Hungaricum and NAWA take
no CV at all). A Rhodes applicant's format requirement cannot be expressed
today.

Add the same column, with the same choices, to `FundingOpportunity`. The funder
value wins when set — see precedence.

Deliberately **not** modelled as a `CatalogRule` row: `_CONSTRAINT_KEYS` is a
closed set of *checkable* keys, and a `BINDING` rule whose key has no checker
fails closed and blocks the render. Format requirement is a setting, not a
check.

### `DocumentDraft.funding_opportunity` (new column)

```python
funding_opportunity = models.ForeignKey(
    "funding.FundingOpportunity", null=True, blank=True,
    on_delete=models.PROTECT, related_name="+",
)
```

Nullable, and the null case is meaningful: **empty means self-funded / direct
application**, and the resolver simply has one fewer layer. A self-funded
student still gets universal, country, track and programme rules — R-032 (no
photo or date of birth for US/CA/UK/AU) and Germany's tabular layout, signature
and gap rules all apply with no funder present.

Resolving funder rules from the programme alone was rejected: a programme linked
to five scholarships would inherit all five funders' rules at once,
over-constraining the CV and creating same-specificity contradictions the
resolver cannot settle.

Follows the `programme` FK immediately above it, including its comment about
`Program` being a shared catalog model with no tenant column to pair with.

## Resolution

`resolve_rules(program, opportunity)` returns `tuple[ConstraintRule, ...]`.

**Rules accumulate across scopes. When two rules set the same `key`, the more
specific scope wins:**

```
Program.cv_constraints  >  FUNDER  >  COUNTRY  >  TRACK  >  UNIVERSAL
```

There is no `PROGRAMME` scope kind, because programme specificity already has a
home: `Program.cv_constraints`, appended last. Adding a second way to express
the same thing would give two places to look and a rule that could contradict
itself. There is no `PORTAL` scope kind either — `Program` has no portal field
to match against, so portal rules are not seeded and a choice for them would be
dead. Both are one-line migrations if they are ever needed.

The research settles the decisive case itself. R-079 (SISGP mandates Sex, Date
of birth, Citizenship) explicitly overrides R-032 (US/CA/UK/AU: no photo, DOB,
marital status or gender), and says why: *"Personal-data inclusion is therefore
a per-destination render decision, never a global content decision."*

**This is specificity, not strictness.** DAAD allows 3 pages where the taught
default is 1–2; DAAD wins, because a funder's own published rule is the
operative one, not the tightest one available.

**Two rules at the same specificity setting the same key is a data error**, and
the seed command fails on it rather than picking one silently.

Scope matching:

| `scope_kind` | Matches when |
| --- | --- |
| `UNIVERSAL` | always |
| `TRACK` | the track derived from content (research when `CVContent.research` is non-empty, else taught — the same heuristic `render.py::_section_order` already uses) |
| `COUNTRY` | `program.country_code` is in `scope_values` |
| `FUNDER` | `opportunity.canonical_key` is in `scope_values` |

`FundingOpportunity.canonical_key` is unique, so a funder scope value identifies
exactly one row. `Program.canonical_key` is **not** unique on its own — it is
unique only with `institution` and `location_key` — which is a second reason
programme-scoped rules go in `Program.cv_constraints` rather than in a scope
value that could match several programmes at once.

`Program.cv_constraints` keeps its current meaning: programme-specific rules
that `format_resolution.py` may write at runtime. The resolver appends them
last, so they win over every catalog scope.

## The two missing checkers

`_CONSTRAINT_KEYS` lists ten keys; `_CHECKERS` implements seven.
`required_fields` and `prohibited_content` have no checker, and a `BINDING` rule
whose key has no checker becomes a violation ("no pre-flight check for …") that
`render_cv` turns into `PreflightBlocked`.

That fail-closed behaviour is correct and must not be weakened. It does mean
seeding SISGP's binding R-079 today would make every SISGP CV unrenderable — so
both checkers are part of this work.

### `_check_required_fields`

`value` is a list of `PersonalInformation` field names. The rule is satisfied
when every named field is present and non-empty on the content.

Serves R-079 (SISGP: `sex`, `date_of_birth`, `citizenship` — all three already
exist on `PersonalInformation`, and `cv_funder_sisgp.html` already renders
them).

**Known gap, deliberately not seeded:** R-004 (MemBioMed) requires age, cGPA and
institution recognition. `CVContent` has no field for any of them, so a binding
`required_fields` rule naming them would permanently block that programme. It is
recorded here and left out of the seed until the schema can carry them.

### `_check_prohibited_content`

`value` is a list of content-class tokens. Only one token is needed now:
`"hyperlinks"`, satisfied when `personal_information.links` is empty and no
publication carries a DOI.

Serves R-017 (Fulbright: no hyperlinks or off-site references). Graded
`ADVISORY_HIGH_RISK`, not `BINDING`: the CSV records it as *"binding (Scholar) /
advisory (Student)"*, and this platform's applicants are on the student track.

This one interacts with shipped behaviour — the contact header gained live
ORCID/GitHub/LinkedIn links, and publications gained resolvable DOIs. A
Fulbright applicant will therefore see a warning, which is the system working as
designed, not a regression.

### One checker widened

`_check_language` compares `document_language` against a single value. R-072
(Eiffel: "CV in French or English") is a set. The checker accepts a string or a
list of strings; a string keeps its current meaning exactly.

## Wiring

`render_draft` resolves its own draft rather than relying on each caller:

- when `constraints` is not supplied, call `resolve_rules(draft.programme, draft.funding_opportunity)`
- when `draft.render_variant` is blank, call `select_render_variant(program, opportunity)`

Both parameters stay, as test overrides. `select_render_variant` gains the
opportunity argument and prefers its `cv_format_requirement` when set, falling
back to the programme's, then to `STANDARD`.

A draft with no programme resolves to no rules and `STANDARD` — today's exact
behaviour, so nothing already working changes.

## Seed contents

The first seed carries the rules whose key, value, scope and enforcement are all
unambiguous in the research. Rule IDs, enforcement and cycle strings are copied
from `cv-rules.csv` verbatim.

| Key | Rules |
| --- | --- |
| `max_pages` | R-007 EMJM Imaging 2 (binding) · R-008 Mundus Journalism 2 (binding) · R-012 DAAD 3 (binding) · R-057 i-MESC 2 (binding) · R-072 Eiffel 2 (binding) · R-080 Rhodes 2 (binding) · R-023 taught 2 (advisory_style) · R-024 research 3 (advisory_style) |
| `max_bytes` | R-048 Mundus Journalism 10 MB (binding) · R-060 Europubhealth+ 2 MB (binding) |
| `max_entries_per_section` | R-015 Chevening education/experience 15 each (binding) · R-078 SISGP experience 3 (binding) |
| `photo_allowed` | R-032 US/CA/GB/AU false (advisory_high_risk) · R-030 DE true (advisory_style) · R-033 Europass true (advisory_style) |
| `date_of_birth_allowed` | R-032 US/CA/GB/AU false (advisory_high_risk) · R-033 Europass true (advisory_style) |
| `date_of_issue_required` | R-010 DAAD EPOS true (binding) |
| `signature_required` | R-031 DE true (advisory_high_risk — German custom, no funder-binding instance found) |
| `language` | R-072 Eiffel `["fr", "en"]` (binding) |
| `required_fields` | R-079 SISGP sex, date_of_birth, citizenship (binding) |
| `prohibited_content` | R-017 Fulbright hyperlinks (advisory_high_risk) |

R-032 is graded `ADVISORY_HIGH_RISK` rather than `BINDING` because the CSV grades
it advisory; it survives to the student as a warning they must accept, via the
existing `ConstraintOverride` flow.

Two curation judgements in the table above, recorded because they are
judgements and not transcriptions:

- **R-048's own scope is the bare word `funder`** — the rule states "respect
  per-package size limits" and cites Mundus Journalism's 10 MB as its example.
  It is seeded scoped to Mundus Journalism, because that is the only instance
  the rule evidences. A general "respect the limit" with no limit attached is
  not a checkable rule.
- **R-067's 2 MB default is derived, not published** — the CSV describes it as a
  target extrapolated from Europubhealth+'s ceiling. It is **not** seeded as a
  universal rule; inventing a size cap for every funder from one funder's page
  is the same error as inventing a French page limit.

`FundingOpportunity.cv_format_requirement` values seeded alongside: AMIR,
MemBioMed, STEPS, GLOBED, i-MESC, MathMods, WE-TEAM, DAAD EPOS →
`europass_required`; DAAD PRIME, Europubhealth+, EMSHIP → `europass_preferred`;
EMHRPP, CoMEM, CLMCE, Turkiye Burslari → `any`; SISGP, Australia Awards, Rhodes
→ `funder_template`; Stipendium Hungaricum, NAWA → `structured_fields_only`.

**Amended during planning (2026-08-26): seeding does NOT create
`FundingOpportunity` rows.** It sets `cv_format_requirement` on funders that
already exist, and refuses to run — naming the missing keys — when a
funder-scoped rule points at a funder the catalog does not hold.

The original wording had the seed create them. Writing the task showed why that
is wrong: `FundingOpportunity` requires `family` and `scope_type`, and this
research establishes neither. The taxonomy does not even fit — Rhodes is a
private trust, so both `GOVERNMENT_SCHOLARSHIP` and `MULTILATERAL` would be
false claims about it. Inventing a classification to satisfy a NOT NULL column
is precisely the failure mode this system exists to prevent, and it would be
invented in the shared catalog every tenant reads.

Funder rows come from the discovery pipeline. This seed only annotates them.

**No `Program` rows are seeded.** The earlier plan named IP Paris as the first
real programme; it was a test fixture, not a real target, and is dropped. The
catalog's value is in the funder rules, which need no programme to be correct.
S-017 remains binding on any future French programme: France has no documented
style norm, so nothing may be inherited from a French default, and the
commercial one-page claim the research rejected must not reappear.

## Error handling

- **Malformed stored rule** — `rules_from_program` already raises rather than
  skipping, on the grounds that a constraint we cannot parse is one we cannot
  enforce. `resolve_rules` keeps that behaviour.
- **Unknown `key` in the database** — rejected by `ConstraintRule` validation at
  resolve time, and by a `CheckConstraint` at write time.
- **Same-specificity duplicate** — the seed command raises and writes nothing.
- **Unevaluatable BINDING rule** — unchanged: a violation, which `render_cv`
  turns into `PreflightBlocked`. Pinned by a test so a future change cannot
  loosen it accidentally.
- **Seed re-run** — idempotent: rows are matched on `rule_id`, updated in place,
  and rules no longer in the module are deleted, so the module is the whole
  truth.

## Testing

- `_check_required_fields` and `_check_prohibited_content`: red-first, each with
  a passing case, a failing case, and a rule whose `value` is malformed (which
  must be reported, not raised).
- `_check_language` with a string (unchanged behaviour) and with a list.
- Resolver: one test per precedence pair that actually occurs — SISGP over
  US/CA/UK/AU for `date_of_birth_allowed`, DAAD's 3 pages over the taught
  default of 2, funder over country.
- Resolver with `opportunity=None`: universal, country and track rules still
  resolve; no funder rule does.
- Scope matching on a multi-value scope: a `GB` programme matches R-032's
  `US/CA/GB/AU`, a `DE` programme does not.
- Seed idempotency: run twice, second run changes nothing; a removed rule is
  deleted; a duplicate raises.
- Wiring: a draft with a programme and an opportunity renders with that pair's
  rules; a draft with neither renders exactly as today.
- The fail-closed guarantee: a BINDING rule with a key that has no checker still
  blocks.

## Out of scope

- The AI-use policy gate (see above) — deferred by the user, tracked separately.
- An admin screen for editing rules. The seed command covers the "new programme
  tonight" case until an agency asks for more.
- Portal-scoped rules — no portal field exists on `Program` to match against.
- The ~30 guidance rules. They shape prompts and templates; storing unenforceable
  prose in a database would make it look enforced when nothing enforces it.
- Re-verification tooling for expired cycles. The data is there to query when
  someone wants it.
