# Binding a register row to an institution

**2026-09-07.** How a `RegisterListing` finds its `Institution` when `ror_id` is blank — which is
most of the world outside DEQAR.

Evidence: `../research/2026-09-07-institution-identifier-matching.md`. Every number below is measured
there, with the command that produced it.

## 0. Scope

**In scope:** the `InstitutionIdentifier` table, and the two commands that populate it.

**Two phases, and phase 1 ships alone.** Phase 1 is the model, its migration, the `0022` amendment,
`load_institution_identifiers` and the tests -- everything that makes a binding possible and safe.
Phase 2 is `propose_institution_identifiers`, which only makes binding *fast*: the loader works
against a hand-filled CSV without it. They are also different kinds of work, a data-layer change
versus a network client with ranking heuristics, and phase 2's outbound dependency should not hold
phase 1 hostage.

**Out of scope, deliberately: the per-country adapters.** Eleven registers with eleven different
fetch rules, transport requirements and licence terms is a separate deliverable with its own
lifecycle. It gets its own spec. This one gives that spec something to join against.

**Relationship to `2026-08-31-institution-safety-screen-design.md` §10.** This work sits between
item 2 and item 3, and it **amends item 1**: `Institution.ror_id` is removed rather than shipped
(§3 below). Item 3's claim that the DEQAR adapter "delivers the ROR crosswalk that item 1 wants"
still holds — the crosswalk now lands in this table instead of that column.

## 1. The problem, measured

The parent spec lists name matching as untested and calls it the known-hard part. It is worse than
untested; it is **actively unsafe**, and the UK sponsor register demonstrates why.

That register publishes no identifier column at all — `Sponsor Name, Town/City, Additional
Locations, Sponsor Type, Status, Route, Immigration Compliance`. Matching 943 distinct sponsor names
against Wikidata's 27,430 UKPRN-bearing items, on exact normalized equality:

```
unique match : 477  (50.6%)
ambiguous    :  27  ( 2.9%)   St Joseph's College -> four distinct UKPRNs
no match     : 439  (46.6%)
```

**28 of the unmatched are foreign institutions or pathway colleges operating in the UK** —
`Boston University London Programme`, `University of Brighton International College`,
`Georgetown University (USA) UK Initiatives Organisation`. A matcher loosened enough to recover
recall binds those to Boston University and the University of Brighton, asserting a UK
sponsor-licensing fact **against a legal entity that does not hold that licence**, into a table
every tenant reads.

The two error classes are reached from opposite directions — the ambiguous 27 come from *exact*
matching, the branch-campus errors from *loose* matching. **No single threshold avoids both.** That
is the finding this design is built on: nothing auto-binds on a name, ever.

*(The parent spec cites 1,308 UK rows; the 2026-09-07 file has 1,306. Registers move. Treat every
figure here as a dated snapshot.)*

## 2. `InstitutionIdentifier`

In `apps/funding/models.py`, beside `Institution`.

```python
_IDENTIFIER_SCHEMES = ("ROR", "UKPRN", "CRICOS", "DLI", "NZQA", "IPEDS", "DEQARINST", "ETER")


class InstitutionIdentifier(models.Model):
    """A durable code some register knows this institution by.

    The table exists so that a name is never matched twice. A human (or a
    crosswalk) resolves an institution to a code once; every register refresh
    afterwards is a code join with no matching in it at all.
    """

    class Scheme(models.TextChoices):
        ROR = "ROR"
        UKPRN = "UKPRN"
        CRICOS = "CRICOS"
        DLI = "DLI"
        NZQA = "NZQA"
        IPEDS = "IPEDS"
        DEQARINST = "DEQARINST"
        ETER = "ETER"

    class Source(models.TextChoices):
        #: The register printed this code in its own file.
        REGISTER = "REGISTER"
        #: Derived from a third-party mapping (Wikidata, DEQAR, IPEDS->ROR).
        CROSSWALK = "CROSSWALK"
        #: A person decided.
        HUMAN = "HUMAN"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="identifiers"
    )
    scheme = models.CharField(max_length=20, choices=Scheme.choices)
    value = models.CharField(max_length=128)
    source = models.CharField(max_length=20, choices=Source.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("scheme", "value"),
                name="institution_identifier_scheme_value_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(scheme__in=_IDENTIFIER_SCHEMES),
                name="institution_identifier_scheme_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(source__in=("REGISTER", "CROSSWALK", "HUMAN")),
                name="institution_identifier_source_valid",
            ),
        ]
```

**`UniqueConstraint(scheme, value)` is the load-bearing line.** It makes the §1 failure structurally
impossible rather than merely unlikely: one CRICOS code cannot name two institutions, so the database
refuses the ambiguous binding that `St Joseph's College` → four UKPRNs would otherwise produce. This
is why the design is a constraint and not a threshold.

**`value` is stored in the scheme's canonical form, and the loader validates it.** The unique
constraint only catches a duplicate if two sources spell the same code identically:
`https://ror.org/02mhbdp94` and `02mhbdp94` are one identifier and two rows. **ROR stores the bare
ID, never the resolver URL.** Every other scheme stores exactly what its register prints, including
leading zeros and letter suffixes (`00003G`) — those are part of the code, not formatting.
`load_institution_identifiers` rejects a value that does not match its scheme's documented shape,
because a malformed value defeats the one constraint this design rests on.

**No `UniqueConstraint(institution, scheme)`.** Mergers and re-registrations legitimately leave an
institution holding two UKPRNs; forbidding that would reject true data.

**Both `scheme` and `source` get a `CheckConstraint`.** `choices=` is a form-layer convention and
`catalog_ingestion` writes SQL. This is the same fail-open migration `0024` closed in five places:
a junk value persists happily and then matches no join the ingest makes.

**No `db_index` on `scheme`.** The unique constraint already builds a btree on `(scheme, value)`, and
a filter on `scheme` alone uses it by leftmost prefix. A separate index would be a second structure
covering what the first already covers -- write cost and disk for nothing.

**Why `scheme` gets a module constant and `source` an inline literal.** Neither can be written as
`Scheme.values` inside `Meta`: a nested choices class is not in scope there. That forces a duplicate
either way, so the only question is where it lives. `source` has three short values, so a literal
matches `RegisterListing.verdict`. `scheme` has eight, and eight values hand-copied between a choices
class and a literal is where drift starts -- the constant gives the drift-pin test (§8.4) a name to
compare against. This is a narrower justification than `_AXES`, which earned its constant by being
read from two `Meta` blocks; `_IDENTIFIER_SCHEMES` is read from one.

**`CASCADE`, not `PROTECT`**, matching `RegisterListing.institution`. An identifier is a property of
an institution, not an independent entity; `PROTECT` would make a curated catalog row undeletable the
moment anyone bound a code to it.

**No timestamps.** No model in `apps/funding/models.py` carries one.

**`source` is not decoration.** Wikidata is an open wiki — anyone can change a `P4971` value. When a
crosswalk proves wrong, `source=CROSSWALK` is how you find every binding it produced without
re-auditing the `REGISTER` and `HUMAN` ones.

**Deliberate asymmetry with `RegisterListing`.** That model carries a `snapshot` FK under PROTECT,
because "a listing whose snapshot is gone is an unsourced assertion". `InstitutionIdentifier` gets an
enum instead: a `HUMAN` binding has no artifact to point at, and giving a `CROSSWALK` binding one
would mean archiving Wikidata query results — a subsystem, for a question the enum answers.

**RLS:** shared-catalog data. `shared_catalog_select` (SELECT, public) plus `catalog_ingestion_write`,
exactly as migration `0023` sets up for the register tables.

## 3. An identifier binds at the level its register keys at

**This rule is required for §2's unique constraint to be correct.** Without it an implementer creates
one identifier row per register row and hits the constraint immediately.

Measured against the live IRCC designated-learning-institution list (2026-09-07, 1,441 rows parsed):
**1,124 distinct DLI numbers, of which 135 appear on more than one row.** `O19441088976` covers
sixteen campuses of College of the North Atlantic; `O19604209351` covers twelve of Yukon University.

Canada issues **one DLI per institution** and lists campuses beneath it. The US certifies **per
campus** — SEVP school codes are campus-keyed. So:

| Register | Keys at | Binds to |
| --- | --- | --- |
| DLI (Canada) | institution | `kind=INSTITUTION` |
| SEVP (US) | campus | `kind=CAMPUS` |
| CRICOS (Australia) | provider | `kind=INSTITUTION` |
| UKPRN | provider | `kind=INSTITUTION` |
| DEQAR (Europe) | institution | `kind=INSTITUTION` |
| WHED (worldwide) | institution | `kind=INSTITUTION` |

A constraint violation is therefore **informative, not an obstacle**: it means either a duplicate
institution row in the catalog or a wrong binding. Both deserve a human. The loader must fail loudly
rather than skip (§6).

## 4. `Institution.ror_id` is removed

`ror_id` was added by migration `0022` on `claude/institution-screen-schema` (PR #47, open,
`CONFLICTING`). It has **never been merged to master** and has **zero readers** anywhere in the
codebase — the only greps that appear to hit it are the substring inside
`test_profile_duplicate_error_identifies_...`.

It also has **no uniqueness guarantee**: `CharField(blank=True, default="", db_index=True)`, no
`unique=True`, no `UniqueConstraint`, on any branch. Two institutions can carry the same ROR ID today
and nothing stops them.

**Keeping it alongside this table would duplicate with unequal guarantees** — one path enforcing
one-ROR-one-institution and one path enforcing nothing, for the same identifier. That is worse than
either alone, and the unenforced path is the one that already exists. Matching the table's guarantee
would mean adding a *partial* unique index (`condition=~Q(ror_id="")`, since blank is the normal
case) purely to replicate what `UniqueConstraint(scheme, value)` gives free.

`ROR` is therefore an ordinary scheme in `_IDENTIFIER_SCHEMES`, and
`institution.identifiers.filter(scheme="ROR")` replaces the column. The `db_index` it carried is
subsumed by the unique index, which serves the direction that matters: code → institution.

**Implementation note.** Remove the `AddField` from `0022` rather than adding a removal migration.
`0022` is unmerged and unreviewed (PR #47 has zero reviews; CodeRabbit posted a walkthrough comment,
not a review), nothing is deployed, and test databases are per-worktree and disposable. You cannot
"remove" a column that never shipped. `0023` and `0024` reference `ror_id` zero times, so the edit is
self-contained. **If PR #47 merges first this becomes a removal migration against master** — a
permanent scar in history for a column that never held a row.

## 5. There is no candidate table

Candidates are transient. The matcher runs **only when a human is enrolling an institution into the
catalog**. Register ingest never generates a candidate: it joins on `InstitutionIdentifier`, and a
register row that joins nothing is simply not ingested, with `RegisterCoverage` recording the gap
honestly — which is what that table was built for.

Nothing re-proposes, so nothing needs to remember a rejection. A pending/accepted/rejected state
machine would persist state that is never read twice.

This also bounds the human cost correctly. The backlog is **however many institutions we catalog**,
not 943 UK sponsors or fifteen registers, and each is paid once, at a moment a human is already
curating that row. `Institution` has no writer — `canonical_key` is hand-curated — so the catalog is
small and grows deliberately.

**Correction, 2026-09-13: `Institution` has a writer and did when this was
written.** `apps/research/catalog.py::write_catalog_entry`, reached from
`manage.py discover` via `pipeline.py:411` and `:445`, creates one per lead
keyed on a scraped provider name. The 22 rows in the dev database are all its
output. This paragraph's conclusion — that binding is paid once at a moment a
human is already curating — becomes true only with
`load_program_providers` (2026-09-13 providers design §4), which is the
hand-curation route this assumed already existed.

## 6. The human surface: two commands

Following the existing convention for shared-catalog seeding
(`load_cv_format_requirements`, `seed_cv_rules`).

**`propose_institution_identifiers <canonical_key>`** — read-only, writes nothing. Queries Wikidata
and — once a token exists (§9) — the DEQAR API, prints ranked candidates per scheme with their
evidence (QID, label, city, code) and the exact CSV line to paste. Being a pure reader, it needs no
elevated database role. **The DEQAR tier is optional in the first cut**: Wikidata alone covers the
schemes the four non-European destinations need, and DEQAR's 34 identifier resources are all
European.

**`docs/research/institution-identifiers.csv` + `load_institution_identifiers`** — the only writer.
Run as `DATABASE_ROLE=migration`, mirroring `load_cv_format_requirements` and its
`docs/research/cv-rules.csv`.

**Bindings live in a checked-in file, not a bare database write.** A binding is the consequential
cross-tenant decision this whole design exists to protect. In a file it is a reviewed diff —
attributable, revertable, visible in `git log`. As a database side effect it is invisible to
everyone, including the person who made it.

### The RLS silent-no-op trap

Shared-catalog tables carry a SELECT-only policy for the runtime role. `load_institution_identifiers`
is insert-only, and an INSERT blocked by RLS raises (`InsufficientPrivilege`, "new row violates
row-level security policy") — so this loader already fails loudly under the wrong role, with no guard
needed.

The silent case is UPDATE and DELETE, which match no rows and raise nothing under RLS — that is what
`seed_cv_rules` guards against, because it updates rather than inserts. The first change that gives
`load_institution_identifiers` upsert semantics inherits that same silence and must add its own check
against whatever that call actually returns; do not assume the insert-only precedent still holds once
the loader can update.

### On conflict

A `(scheme, value)` already bound to a different institution raises `IntegrityError`. The loader
reports the offending row and stops. Per §3 that collision means a duplicate institution row or a
wrong binding — both need a human, neither is safe to skip.

### Outbound path

`propose` adds a fourth network path (Wikidata SPARQL, DEQAR API) alongside the three in `CLAUDE.md`.
It is operator-run, read-only, outside any request path, and **persists no provider artifact** — only
a code a human then confirms into a file. That keeps it inside the "provenance comes from the origin"
rule rather than around it.

## 7. Two things ruled out, with reasons

**Not `ConsultantResearchTask`.** It is a `TenantScopedModel` with `UniqueConstraint(tenant, url)`.
Routing a shared-catalog decision through per-tenant data would have every tenant re-confirm the same
binding, and one tenant's decision writing into rows every other tenant reads — precisely the
cross-tenant hazard the `ProgramCompetency` rule in `CLAUDE.md` exists to prevent. It also models
"go research this URL", not "is this the same institution".

**Not Django admin.** There are zero admin registrations in this codebase. Adding one means a new
surface with its own authorization story, for work the command convention already covers.

## 8. Testing

Red check per constraint, as `0024` established:

1. A second institution taking an already-bound `(scheme, value)` raises `IntegrityError`.
2. A junk `scheme` raises `IntegrityError`.
3. A junk `source` raises `IntegrityError`.
4. `_IDENTIFIER_SCHEMES == tuple(InstitutionIdentifier.Scheme.values)` — the drift pin. A nested
   choices class is not in scope inside its own `Meta`, which is why the module constant exists at
   all; this is the line that stops the two diverging. Mirrors
   `test_an_axis_must_be_one_the_design_names`.
5. Deleting an institution deletes its identifiers (CASCADE, not PROTECT).
6. `load_institution_identifiers` under the runtime role raises rather than silently writing nothing.
7. `propose_institution_identifiers` writes no rows.

`propose`'s network calls are stubbed; nothing in the default suite reaches Wikidata or DEQAR.

## 9. What this does not decide

- **The per-country adapters.** Out of scope; their own spec (§0).
- **Whether a Wikidata alias lookup lifts 50.6% materially.** One more SPARQL query, unmeasured.
  The `propose` command's usefulness rides on Wikidata coverage, which is a snapshot and not a
  property.
- **Whether DEQAR's `by-identifier` endpoint behaves as documented.** It needs a Bearer token nobody
  has requested. Documented, not exercised.
- **Whether a listing bound at campus level propagates to the parent institution, or the reverse.**
  §3 establishes that SEVP binds to `kind=CAMPUS` while DLI binds to `kind=INSTITUTION`, which makes
  the question unavoidable: a campus excluded by SEVP under a parent the registers call clean has no
  defined reading yet. The parent spec has the screen walking parents; how a walk combines listings
  found at different levels is that spec's decision, not this one's. **This spec makes the situation
  representable and deliberately does not resolve it.**
- **How many institutions this actually touches.** Unmeasurable until `Institution` has a writer.
  Any number stated before then would be invented.
  **Measured 2026-09-13: 22, all from the one seed `seed:eacea`, and all
  jointly awarded.** See the 2026-09-13 providers design §1.
