# Institution Identifier Binding — Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a register row bind to an `Institution` by a durable code, so that a name is never matched twice and an ambiguous binding is impossible at the database rather than unlikely at a threshold.

**Architecture:** One new shared-catalog table, `InstitutionIdentifier`, with `UniqueConstraint(scheme, value)` as the load-bearing guarantee. `Institution.ror_id` is removed — ROR becomes an ordinary scheme in that table. Bindings are curated in a checked-in CSV and applied by a management command that runs under an elevated database role, following `load_cv_format_requirements`.

**Tech Stack:** Django 5.2.17, PostgreSQL with row-level security, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-09-07-institution-identifier-binding-design.md`
**Evidence:** `docs/superpowers/research/2026-09-07-institution-identifier-matching.md`

## Global Constraints

- **Phase 1 only.** `propose_institution_identifiers` (spec §6, Wikidata/DEQAR) is **out of scope** and gets its own plan. The loader works against a hand-filled CSV without it.
- **Per-country adapters are out of scope** (spec §0). This plan gives them something to join against.
- Gates, all of which must pass before the final commit: `uv run ruff check .`, `uv run mypy apps config`, `uv run pytest`.
- **Never run `ruff format`** — it rewrites 26 unrelated files in this repo.
- Set `POSTGRES_DB` per worktree (e.g. `POSTGRES_DB=tehsil_identifier_binding`); the shared `test_tehsil` wedges across parallel sessions.
- `git -C <worktree>` for every git command. A bare `git commit` lands on the wrong branch because the shell's cwd resets to the main repo.
- Every new shared-catalog table must be added to `_SHARED_TABLES` in `tests/tenancy/test_database_isolation.py`, or its isolation is untested.
- TDD: every constraint gets a watched failure before the code that satisfies it.

---

## Pre-flight: which branch, and a divergence you must not try to fix

**The code this plan touches is on `claude/institution-screen-schema`, not on the branch holding the spec.**

`claude/institution-safety-screen-design` has the spec and research note but **no `Institution.kind`, no `RegisterListing`, and no migrations 0022–0024**. Its funding migration tail is `0020, 0021, 0022_merge_20260830_1714`.

`claude/institution-screen-schema` has `0020, 0021, 0022_register_listing_and_coverage, 0023_register_tables_rls, 0024_register_constraints`.

**Both branches add a different `0022` on top of master's `0021_program_competency_rls`.** When they eventually meet, the `funding` app will have two leaf nodes and need `makemigrations --merge`. **That is pre-existing and NOT this plan's job.** Do not attempt to reconcile it. Do not renumber anything.

Task 1 runs on `claude/institution-screen-schema` because it edits that branch's own file. Tasks 2–4 run on a new branch stacked on it, so PR #47 stays focused.

---

### Task 1: Remove `ror_id` before it ships

Amends PR #47, which is open, `CONFLICTING`, and has **zero reviews** (CodeRabbit posted a walkthrough comment, not a review). Nothing is deployed. Per spec §4, this edits `0022` rather than adding a removal migration — you cannot remove a column that never shipped.

**Files:**
- Modify: `apps/funding/models.py` (remove the `ror_id` field and its comment block from `Institution`)
- Modify: `apps/funding/migrations/0022_register_listing_and_coverage.py` (remove the `AddField` at lines 34–38)

**Interfaces:**
- Consumes: nothing.
- Produces: `Institution` with no `ror_id` attribute. Task 2 relies on this — `ROR` becomes a `Scheme` value instead.

- [ ] **Step 1: Confirm `ror_id` has no readers**

```bash
cd /home/orkhan/Desktop/tehsil_agent/.worktrees/institution-screen-schema
grep -rn "ror_id" apps/ tests/ | grep -v "error_identifies"
```

Expected: exactly two hits — the field in `apps/funding/models.py` and the `AddField` in `0022`. Any third hit means a reader appeared; stop and report it.

- [ ] **Step 2: Remove the field from the model**

Delete from `Institution` in `apps/funding/models.py` — the field and the five comment lines above it that begin `#: The canonical identity handle`:

```python
    ror_id = models.CharField(max_length=64, blank=True, default="", db_default="", db_index=True)
```

- [ ] **Step 3: Remove the `AddField` from migration 0022**

Delete this operation from `apps/funding/migrations/0022_register_listing_and_coverage.py`:

```python
        migrations.AddField(
            model_name='institution',
            name='ror_id',
            field=models.CharField(blank=True, db_default='', db_index=True, default='', max_length=64),
        ),
```

- [ ] **Step 4: Verify Django sees no pending model changes**

```bash
POSTGRES_DB=tehsil_identifier_binding uv run python manage.py makemigrations --check --dry-run funding
```

Expected: `No changes detected`. If it wants a migration, the model and `0022` disagree — recheck Steps 2 and 3.

- [ ] **Step 5: Run the funding tests**

```bash
POSTGRES_DB=tehsil_identifier_binding uv run pytest tests/funding/ -q
```

Expected: PASS. If a test references `ror_id`, Step 1 missed it.

- [ ] **Step 6: Commit and force-push the amended PR**

```bash
cd /home/orkhan/Desktop/tehsil_agent
git -C .worktrees/institution-screen-schema add apps/funding/models.py apps/funding/migrations/0022_register_listing_and_coverage.py
git -C .worktrees/institution-screen-schema commit -m "fix(screen): drop ror_id before it ships

A second home for ROR beside InstitutionIdentifier would duplicate with
unequal guarantees -- the table enforces one ROR per institution, the column
enforced nothing. Never merged, zero readers, so this edits 0022 rather than
adding a removal migration.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git -C .worktrees/institution-screen-schema push --force-with-lease
```

---

### Task 2: The `InstitutionIdentifier` table and its three constraints

**Files:**
- Modify: `apps/funding/models.py` (add `_IDENTIFIER_SCHEMES` beside `_AXES`; add the model after `Institution`)
- Create: `apps/funding/migrations/0025_institution_identifier.py`
- Create: `tests/funding/test_institution_identifier.py`

**Interfaces:**
- Consumes: `Institution` from Task 1 (no `ror_id`).
- Produces: `InstitutionIdentifier` with `Scheme` and `Source` nested `TextChoices`, `_IDENTIFIER_SCHEMES` module constant, and `institution.identifiers` reverse accessor. Task 4's loader writes through this model.

- [ ] **Step 1: Create the branch**

```bash
cd /home/orkhan/Desktop/tehsil_agent
git worktree add .worktrees/identifier-binding -b claude/institution-identifier-binding claude/institution-screen-schema
git -C .worktrees/identifier-binding cherry-pick 4770382 aaeb9a9 094f98a
```

Those three commits are the research note, the spec, and its review fixes — all documentation, no code, so they cherry-pick cleanly onto the schema branch.

- [ ] **Step 2: Write the failing tests**

Create `tests/funding/test_institution_identifier.py`. The fixture mirrors `register_rows` in `tests/funding/test_register_models.py`.

```python
"""InstitutionIdentifier: the constraints that make a wrong binding impossible.

A false binding writes a register verdict onto an institution that does not
hold it, into a table every tenant reads, with nothing downstream able to tell
it from a sound one. These are the lines that stop it.
"""

import pytest
from django.db import IntegrityError

from tests.funding.test_catalog_models import _catalog


@pytest.fixture
def two_institutions(db):
    catalog = _catalog()
    first = catalog.Institution.objects.create(
        canonical_key="institution:houston",
        name="University of Houston",
        country_code="US",
        official_website="https://uh.example.test",
    )
    second = catalog.Institution.objects.create(
        canonical_key="institution:brighton-international",
        name="University of Brighton International College",
        country_code="GB",
        official_website="https://bic.example.test",
    )
    return catalog, first, second


@pytest.mark.django_db
def test_one_code_cannot_name_two_institutions(two_institutions) -> None:
    """The measured failure: St Joseph's College resolves to four UKPRNs.

    A pathway college and the university it is named after are different legal
    entities. Binding one register code to both is the silent, cross-tenant
    error this whole design exists to prevent.
    """
    catalog, first, second = two_institutions
    catalog.InstitutionIdentifier.objects.create(
        institution=first, scheme="UKPRN", value="10007163", source="REGISTER"
    )
    with pytest.raises(IntegrityError):
        catalog.InstitutionIdentifier.objects.create(
            institution=second, scheme="UKPRN", value="10007163", source="REGISTER"
        )


@pytest.mark.django_db
def test_an_institution_may_hold_two_codes_in_one_scheme(two_institutions) -> None:
    """Mergers and re-registrations leave two UKPRNs. Rejecting that rejects truth."""
    catalog, first, _second = two_institutions
    catalog.InstitutionIdentifier.objects.create(
        institution=first, scheme="UKPRN", value="10007163", source="REGISTER"
    )
    catalog.InstitutionIdentifier.objects.create(
        institution=first, scheme="UKPRN", value="10029725", source="REGISTER"
    )
    assert first.identifiers.filter(scheme="UKPRN").count() == 2


@pytest.mark.django_db
def test_a_scheme_must_be_one_the_design_names(two_institutions) -> None:
    """choices= is a form-layer convention and catalog_ingestion writes SQL."""
    catalog, first, _second = two_institutions
    with pytest.raises(IntegrityError):
        catalog.InstitutionIdentifier.objects.create(
            institution=first, scheme="NONSENSE", value="1", source="REGISTER"
        )


@pytest.mark.django_db
def test_a_source_must_be_one_the_design_names(two_institutions) -> None:
    """source is how a bad crosswalk's bindings are found later. Junk defeats that."""
    catalog, first, _second = two_institutions
    with pytest.raises(IntegrityError):
        catalog.InstitutionIdentifier.objects.create(
            institution=first, scheme="ROR", value="02mhbdp94", source="GUESSED"
        )


@pytest.mark.django_db
def test_deleting_an_institution_deletes_its_identifiers(two_institutions) -> None:
    """CASCADE, not PROTECT: an identifier is a property, not an entity.

    PROTECT would make a curated catalog row undeletable the moment anyone
    bound a code to it.
    """
    catalog, first, _second = two_institutions
    catalog.InstitutionIdentifier.objects.create(
        institution=first, scheme="IPEDS", value="225511", source="CROSSWALK"
    )
    first.delete()
    assert catalog.InstitutionIdentifier.objects.count() == 0


def test_the_scheme_constant_matches_the_choices_class() -> None:
    """_IDENTIFIER_SCHEMES is a hand-kept copy.

    A nested choices class is not in scope inside its own Meta, so the CHECK
    constraint cannot say Scheme.values. This is the line that stops the two
    drifting.
    """
    catalog = _catalog()
    assert catalog._IDENTIFIER_SCHEMES == tuple(
        catalog.InstitutionIdentifier.Scheme.values
    )
```

- [ ] **Step 3: Run them to watch every one fail**

```bash
POSTGRES_DB=tehsil_identifier_binding uv run pytest tests/funding/test_institution_identifier.py -v
```

Expected: all six FAIL with `AttributeError: module 'apps.funding.models' has no attribute 'InstitutionIdentifier'`. **Do not proceed until you have seen them fail.** A test that passes before the code exists is testing nothing.

- [ ] **Step 4: Add the module constant**

In `apps/funding/models.py`, beside `_AXES`:

```python
#: Kept beside _AXES for the same reason: a nested choices class is not in
#: scope inside its own Meta, so the CHECK constraint cannot say
#: Scheme.values. Eight values hand-copied between a choices class and an
#: inline literal is where drift starts, so this gets a name and a test.
_IDENTIFIER_SCHEMES = ("ROR", "UKPRN", "CRICOS", "DLI", "NZQA", "IPEDS", "DEQARINST", "ETER")
```

- [ ] **Step 5: Add the model**

After `Institution` in `apps/funding/models.py`:

```python
class InstitutionIdentifier(models.Model):
    """A durable code some register knows this institution by.

    The table exists so that a name is never matched twice. A human or a
    crosswalk resolves an institution to a code once; every register refresh
    afterwards is a code join with no matching in it at all.

    An identifier binds at the level its issuing register keys at. Canada
    issues one DLI per institution and lists campuses beneath it -- 135 of its
    1,124 DLI numbers cover more than one campus row -- so DLI binds to
    kind=INSTITUTION. The US certifies per campus, so SEVP binds to
    kind=CAMPUS. Get this wrong and the unique constraint below reads as a bug
    rather than the guarantee it is.
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
        #: Wikidata is an open wiki -- this is how a bad crosswalk's bindings
        #: are found later without re-auditing the other two kinds.
        CROSSWALK = "CROSSWALK"
        #: A person decided.
        HUMAN = "HUMAN"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="identifiers"
    )
    #: No db_index: the unique constraint below already builds a btree on
    #: (scheme, value), which a scheme-only filter uses by leftmost prefix.
    scheme = models.CharField(max_length=20, choices=Scheme.choices)
    #: Stored in the scheme's canonical form. "https://ror.org/02mhbdp94" and
    #: "02mhbdp94" would otherwise be one identifier and two rows, defeating
    #: the constraint. The loader validates the shape.
    value = models.CharField(max_length=128)
    source = models.CharField(max_length=20, choices=Source.choices)

    class Meta:
        constraints = [
            #: The load-bearing line. One CRICOS code cannot name two
            #: institutions, so the database refuses the ambiguous binding a
            #: name matcher would produce. This is why the design is a
            #: constraint and not a threshold.
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

- [ ] **Step 6: Generate the migration**

```bash
POSTGRES_DB=tehsil_identifier_binding uv run python manage.py makemigrations funding --name institution_identifier
```

Expected: creates `apps/funding/migrations/0025_institution_identifier.py` depending on `0024_register_constraints`. Open it and add a header comment above the imports:

```python
# The table that makes a wrong binding impossible rather than unlikely.
#
# UniqueConstraint(scheme, value) is the guarantee: one register code names one
# institution. Safe on an empty funding_institutionidentifier -- the table is
# new and has no writer until load_institution_identifiers lands.
```

- [ ] **Step 7: Run the tests until green**

```bash
POSTGRES_DB=tehsil_identifier_binding uv run pytest tests/funding/test_institution_identifier.py -v
```

Expected: 6 passed.

- [ ] **Step 8: Commit**

```bash
cd /home/orkhan/Desktop/tehsil_agent
git -C .worktrees/identifier-binding add apps/funding/models.py apps/funding/migrations/0025_institution_identifier.py tests/funding/test_institution_identifier.py
git -C .worktrees/identifier-binding commit -m "feat(screen): bind a register row by code, never by name

UniqueConstraint(scheme, value) makes the measured failure impossible at the
database: St Joseph's College resolves to four UKPRNs on an exact name match,
and 28 UK sponsor rows are foreign institutions a looser matcher would bind to
the wrong legal entity.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Row-level security and the shared-table registry

Mirrors `0023_register_tables_rls` exactly. A reviewer could accept Task 2's table and still reject this policy shape, which is why it is its own task.

**Files:**
- Create: `apps/funding/migrations/0026_institution_identifier_rls.py`
- Modify: `tests/tenancy/test_database_isolation.py:15-35` (add to `_SHARED_TABLES`)

**Interfaces:**
- Consumes: `funding_institutionidentifier` table from Task 2.
- Produces: the table is SELECT-only for the runtime role. Task 4's loader depends on this being true — its guard exists because of it.

- [ ] **Step 1: Add the table to `_SHARED_TABLES`**

In `tests/tenancy/test_database_isolation.py`, add after `"funding_registercoverage",`:

```python
    "funding_institutionidentifier",
```

- [ ] **Step 2: Run the isolation test to watch it fail**

```bash
POSTGRES_DB=tehsil_identifier_binding uv run pytest tests/tenancy/test_database_isolation.py -v
```

Expected: FAIL — the table is listed as shared catalog but has no RLS policy yet. **Watch this fail before writing the migration.**

- [ ] **Step 3: Write the RLS migration**

Create `apps/funding/migrations/0026_institution_identifier_rls.py`:

```python
# funding_institutionidentifier joins _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalog data: which
# code a register knows an institution by is the same fact for every tenant.
# Same shape as 0023_register_tables_rls -- both the shared_catalog_select
# read policy and the catalog_ingestion_write policy, from the start.
#
# This is also what makes load_institution_identifiers need an elevated role.
# An INSERT under the runtime role raises rather than passing silently; the
# silent case is UPDATE and DELETE, which is why that command carries a guard
# it does not strictly need yet.
from django.db import migrations

TABLE = "funding_institutionidentifier"

RLS_SQL = f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{TABLE}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('funding', '0025_institution_identifier'),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
```

- [ ] **Step 4: Run the isolation test until green**

```bash
POSTGRES_DB=tehsil_identifier_binding uv run pytest tests/tenancy/test_database_isolation.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/orkhan/Desktop/tehsil_agent
git -C .worktrees/identifier-binding add apps/funding/migrations/0026_institution_identifier_rls.py tests/tenancy/test_database_isolation.py
git -C .worktrees/identifier-binding commit -m "feat(screen): RLS on the identifier table

Third-party codes every tenant reads; only catalog ingestion writes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The curated CSV and its loader

**Files:**
- Create: `docs/research/institution-identifiers.csv`
- Create: `apps/funding/management/commands/load_institution_identifiers.py`
- Create: `tests/funding/test_load_institution_identifiers.py`

**Interfaces:**
- Consumes: `InstitutionIdentifier` (Task 2), RLS (Task 3).
- Produces: `load_institution_identifiers <csv_path>`, the only writer of the table in phase 1.

- [ ] **Step 1: Create the CSV with real observed values**

Create `docs/research/institution-identifiers.csv`. Every value below was observed in the research note, not invented:

```csv
canonical_key,scheme,value,source
institution:houston,IPEDS,225511,CROSSWALK
```

Keep it to that single row for now. The catalog has no other institutions to bind, and inventing rows would put unverified bindings into shared-catalog data.

- [ ] **Step 2: Write the failing tests**

Create `tests/funding/test_load_institution_identifiers.py`:

```python
"""The loader, and the silence it must refuse to be.

Today's insert-only path fails loudly under RLS. The guard exists for the
first change that adds upsert semantics, where an UPDATE matching no rows
writes nothing and raises nothing -- and a curator binds fifty identifiers,
sees no error, and gets an empty table.
"""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.funding.test_catalog_models import _catalog


@pytest.fixture
def houston(db):
    catalog = _catalog()
    return catalog, catalog.Institution.objects.create(
        canonical_key="institution:houston",
        name="University of Houston",
        country_code="US",
        official_website="https://uh.example.test",
    )


def _write(tmp_path, body):
    path = tmp_path / "identifiers.csv"
    path.write_text("canonical_key,scheme,value,source\n" + body)
    return str(path)


@pytest.mark.django_db
def test_it_loads_a_binding(houston, tmp_path) -> None:
    catalog, institution = houston
    call_command(
        "load_institution_identifiers",
        _write(tmp_path, "institution:houston,IPEDS,225511,CROSSWALK\n"),
    )
    assert institution.identifiers.get(scheme="IPEDS").value == "225511"


@pytest.mark.django_db
def test_a_malformed_value_is_refused(houston, tmp_path) -> None:
    """A malformed value defeats the one constraint this design rests on.

    "https://ror.org/02mhbdp94" and "02mhbdp94" are one identifier and two
    rows, and the unique constraint cannot tell.
    """
    _catalog()
    with pytest.raises(CommandError, match="ROR"):
        call_command(
            "load_institution_identifiers",
            _write(
                tmp_path,
                "institution:houston,ROR,https://ror.org/02mhbdp94,CROSSWALK\n",
            ),
        )


@pytest.mark.django_db
def test_an_unknown_institution_is_refused(houston, tmp_path) -> None:
    _catalog()
    with pytest.raises(CommandError, match="institution:nowhere"):
        call_command(
            "load_institution_identifiers",
            _write(tmp_path, "institution:nowhere,IPEDS,225511,CROSSWALK\n"),
        )


@pytest.mark.django_db
def test_a_code_already_bound_elsewhere_stops_the_load(houston, tmp_path) -> None:
    """Per spec section 3 this means a duplicate institution row or a wrong
    binding. Both need a human; neither is safe to skip."""
    catalog, _institution = houston
    catalog.Institution.objects.create(
        canonical_key="institution:other",
        name="Somewhere Else",
        country_code="US",
        official_website="https://other.example.test",
    )
    body = (
        "institution:houston,IPEDS,225511,CROSSWALK\n"
        "institution:other,IPEDS,225511,CROSSWALK\n"
    )
    with pytest.raises(CommandError, match="225511"):
        call_command("load_institution_identifiers", _write(tmp_path, body))


@pytest.mark.django_db
def test_it_refuses_to_write_nothing_in_silence(houston, tmp_path, monkeypatch) -> None:
    """The RLS trap seed_cv_rules already guards against.

    Simulated rather than provoked: an INSERT under the wrong role raises
    before reaching this branch. The branch protects the upsert path that does
    not exist yet, which is precisely when nobody would think to add it.
    """
    catalog, _institution = houston
    monkeypatch.setattr(
        catalog.InstitutionIdentifier.objects, "bulk_create", lambda *a, **k: []
    )
    with pytest.raises(CommandError, match="DATABASE_ROLE=migration"):
        call_command(
            "load_institution_identifiers",
            _write(tmp_path, "institution:houston,IPEDS,225511,CROSSWALK\n"),
        )
```

- [ ] **Step 3: Run them to watch every one fail**

```bash
POSTGRES_DB=tehsil_identifier_binding uv run pytest tests/funding/test_load_institution_identifiers.py -v
```

Expected: all five FAIL with `CommandError: Unknown command: 'load_institution_identifiers'`. **Do not proceed until you have seen them fail.**

- [ ] **Step 4: Write the command**

Create `apps/funding/management/commands/load_institution_identifiers.py`:

```python
"""Load curated institution identifier bindings from a CSV.

    DATABASE_ROLE=migration uv run python manage.py load_institution_identifiers \\
        docs/research/institution-identifiers.csv

funding_institutionidentifier carries a SELECT-only shared_catalog_select RLS
policy, so run this as the migration or catalog_ingestion role.

The guard at the end is deliberate belt-and-braces, and it is worth being
precise about why. An INSERT blocked by RLS raises ("new row violates
row-level security policy"), so today's pure-insert path already fails loudly.
It is UPDATE and DELETE that match no rows and say nothing -- which is how
seed_cv_rules came to need its own guard. The first change that gives this
loader upsert semantics inherits that silence, and the guard is already here.

Bindings live in a checked-in CSV rather than a bare database write because a
binding is a consequential cross-tenant decision: in a file it is a reviewed
diff, attributable and revertable; as a database side effect it is invisible.
"""

from __future__ import annotations

import csv
import re

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError, transaction

from apps.funding.models import Institution, InstitutionIdentifier

#: The unique constraint only catches a duplicate if two sources spell a code
#: identically. Every pattern below is anchored on values observed in
#: docs/superpowers/research/2026-09-07-institution-identifier-matching.md.
#: NZQA is deliberately permissive: no real provider number was observed, and
#: a guessed pattern that rejects real data is worse than a loose one. Tighten
#: it when a value is in hand.
_SHAPES = {
    "ROR": re.compile(r"^0[0-9a-z]{6}[0-9]{2}$"),
    "UKPRN": re.compile(r"^\d{8}$"),
    "CRICOS": re.compile(r"^\d{5}[A-Z]$"),
    "DLI": re.compile(r"^[OL]\d{9,13}$"),
    "IPEDS": re.compile(r"^\d{6}$"),
    "DEQARINST": re.compile(r"^DEQARINST\d{4,}$"),
    "ETER": re.compile(r"^[A-Z]{2}\d{4}$"),
    "NZQA": re.compile(r"^\S{1,32}$"),
}


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("csv_path")

    def handle(self, *args: object, **options: object) -> None:
        path = str(options["csv_path"])
        with open(path, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        keys = {row["canonical_key"] for row in rows}
        known = dict(
            Institution.objects.filter(canonical_key__in=keys).values_list(
                "canonical_key", "id"
            )
        )

        pending = []
        for line, row in enumerate(rows, start=2):
            key, scheme = row["canonical_key"], row["scheme"]
            value, source = row["value"], row["source"]
            if scheme not in _SHAPES:
                raise CommandError(f"line {line}: unknown scheme {scheme!r}")
            if not _SHAPES[scheme].match(value):
                raise CommandError(
                    f"line {line}: {value!r} is not a canonical {scheme} value"
                )
            if key not in known:
                raise CommandError(f"line {line}: no institution {key!r}")
            pending.append(
                InstitutionIdentifier(
                    institution_id=known[key],
                    scheme=scheme,
                    value=value,
                    source=source,
                )
            )

        try:
            with transaction.atomic():
                written = InstitutionIdentifier.objects.bulk_create(
                    pending, ignore_conflicts=False
                )
        except IntegrityError as exc:
            raise CommandError(
                f"a binding collides with one already stored -- a duplicate "
                f"institution row or a wrong binding, both need a human: {exc}"
            ) from exc

        if pending and not written:
            raise CommandError(
                "loaded nothing from a non-empty file -- the runtime role cannot "
                "write funding_institutionidentifier; re-run with "
                "DATABASE_ROLE=migration"
            )
        self.stdout.write(f"loaded={len(written)}")
```

- [ ] **Step 5: Run the tests until green**

```bash
POSTGRES_DB=tehsil_identifier_binding uv run pytest tests/funding/test_load_institution_identifiers.py -v
```

Expected: 5 passed. If `test_a_code_already_bound_elsewhere_stops_the_load` fails on the match string, the `IntegrityError` message did not include the value — widen the `match=` to `"collides"`.

- [ ] **Step 6: Run the loader against the real CSV**

```bash
cd /home/orkhan/Desktop/tehsil_agent/.worktrees/identifier-binding
POSTGRES_DB=tehsil_identifier_binding DATABASE_ROLE=migration \
  uv run python manage.py load_institution_identifiers docs/research/institution-identifiers.csv
```

Expected: `CommandError: line 2: no institution 'institution:houston'` — the catalog is empty, which is correct and is the honest state of the system. Record that in the commit message rather than seeding a fake institution to make it pass.

- [ ] **Step 7: Run all gates**

```bash
cd /home/orkhan/Desktop/tehsil_agent/.worktrees/identifier-binding
uv run ruff check .
uv run mypy apps config
POSTGRES_DB=tehsil_identifier_binding uv run pytest
```

All three must pass. **Do not run `ruff format`.**

- [ ] **Step 8: Commit**

```bash
cd /home/orkhan/Desktop/tehsil_agent
git -C .worktrees/identifier-binding add docs/research/institution-identifiers.csv apps/funding/management/commands/load_institution_identifiers.py tests/funding/test_load_institution_identifiers.py
git -C .worktrees/identifier-binding commit -m "feat(screen): curated identifier bindings, loaded loudly

Bindings live in a reviewed CSV, not a database side effect. The loader
refuses a malformed value, an unknown institution, a colliding code, and --
the one that would otherwise pass unnoticed -- a run under the runtime role,
where RLS makes every write match no rows and raise nothing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## After this plan

- **`ponytail:ponytail-review`** on the whole diff before opening a PR.
- **`security-review`** — this adds the first writer of a shared-catalog table in this subsystem.
- **Phase 2** (`propose_institution_identifiers`) gets its own plan, written once phase 1 lands and the ranking requirements are concrete.
- **Still open and not this plan's work:** PR #47 misdescribes itself until `master` is pushed; the two `0022` migrations will need `makemigrations --merge` when the branches meet; `OffSiteRedirect` is still not on master.
