# Joint Programme Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A programme names the several real universities that award it, and the discovery writer stops inventing an `Institution` when it cannot tell who the provider is.

**Architecture:** `Program` gains a nullable `institution`, a `awarding_institutions` many-to-many, a `provision_type` of `SINGLE`/`JOINT` enforced by a database check constraint, and a `provider_text` holding the scraped provider string. `write_catalog_entry` decides joint-ness from the lead's source first and the name's shape second, and writes no `Institution` for a joint programme. A checked-in CSV plus `load_program_providers` resolves the queue and is also the hand-curation route for new institutions.

**Tech Stack:** Django 5.2, Postgres 17, pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-13-joint-programme-providers-design.md`

## Global Constraints

- **Run everything with an isolated database:** prefix every `pytest` and `manage.py` call with `POSTGRES_DB=tehsil_joint`. The shared `tehsil` database is the owner's and must not be migrated.
- **Work in the worktree** `/home/orkhan/Desktop/tehsil_agent/.worktrees/deqar-adapter` on branch `claude/joint-programme-providers`. Use `git -C <worktree>` for every git call — a bare `git commit` lands on the wrong branch.
- **`nulls_distinct=False` on `program_institution_key_location_uniq` is required, not optional.** Postgres treats `NULL` as distinct from `NULL`, so without it two joint programmes sharing a key both insert and the constraint stops protecting the rows this change creates most of.
- **The `SINGLE`/`JOINT` rule is a database `CheckConstraint`, never a model validator.** `catalog_ingestion` is a SQL-writing role that never runs Django model code.
- **`Institution` does not change.** No `CONSORTIUM` kind, no consortium row, ever.
- **Never bind joint-ness to `one_programme_per_site`.** It means "one link is one programme"; the planned Korea and Finland registry sources set it while listing single-provider programmes (`pipeline.py:422`).
- **Never split a composite provider string into names.** A name is not a binding; the raw string goes to `provider_text` for a human.
- **The detection bias stays toward false-`JOINT`.** A false `JOINT` costs one human glance; a false `SINGLE` mints an `Institution` that can never bind.
- **No `ruff format`** — this repo is lint-only; `ruff format` churns unrelated files.
- Gate before each commit: `POSTGRES_DB=tehsil_joint uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`, `POSTGRES_DB=tehsil_joint uv run python manage.py makemigrations --check --dry-run`.

---

### Task 1: `Program` gains provision type, awarding institutions and the constraints

**Files:**
- Modify: `apps/funding/models.py:492` (the `institution` field), `apps/funding/models.py:529-535` (Program `Meta.constraints`), and the end of the module beside `FundingOpportunityProgram:1413`
- Create: `apps/funding/migrations/0029_program_providers.py`
- Create: `apps/funding/migrations/0030_program_awarding_institutions_rls.py`
- Modify: `tests/tenancy/test_database_isolation.py:15-36` (`_SHARED_TABLES`)
- Test: `tests/funding/test_program_providers.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Program.ProvisionType.SINGLE` / `.JOINT` (string values `"SINGLE"` / `"JOINT"`); `Program.institution` now nullable; `Program.awarding_institutions` (M2M manager); `Program.provision_type: str`; `Program.provider_text: str`; model `ProgramAwardingInstitution` with fields `program`, `institution`, table `funding_program_awarding_institutions`.

- [ ] **Step 1: Write the failing tests**

Create `tests/funding/test_program_providers.py`:

```python
import pytest
from django.db import IntegrityError, transaction

from apps.funding.models import Institution, Program

pytestmark = pytest.mark.django_db


def _institution(key: str = "de:aalen") -> Institution:
    return Institution._base_manager.create(
        canonical_key=key,
        name="Aalen University",
        country_code="DE",
        official_website="https://www.hs-aalen.de/",
    )


def _program(**overrides: object) -> Program:
    fields: dict[str, object] = {
        "canonical_key": "master:imlex",
        "name": "IMLEX",
        "campus_name": "Joensuu",
        "city": "Joensuu",
        "country_code": "FI",
        "location_key": "fi:joensuu",
        "degree_level": "MASTER",
        "teaching_languages": ["English"],
        "duration_months": 24,
    }
    fields.update(overrides)
    return Program._base_manager.create(**fields)


def test_a_joint_programme_needs_no_institution() -> None:
    program = _program(
        institution=None,
        provision_type=Program.ProvisionType.JOINT,
        provider_text="University of Eastern Finland; Toyohashi University of Technology",
    )

    assert program.institution_id is None
    assert program.awarding_institutions.count() == 0


def test_a_joint_programme_may_not_carry_an_institution() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _program(institution=_institution(), provision_type=Program.ProvisionType.JOINT)


def test_a_single_programme_must_carry_an_institution() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _program(institution=None, provision_type=Program.ProvisionType.SINGLE)


def test_a_single_programme_may_not_carry_provider_text() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _program(
            institution=_institution(),
            provision_type=Program.ProvisionType.SINGLE,
            provider_text="University of Eastern Finland; Toyohashi",
        )


def test_two_joint_programmes_may_not_share_a_key() -> None:
    """Without nulls_distinct=False Postgres treats NULL as distinct from NULL
    and admits both rows, silently retiring the constraint for exactly the rows
    this change creates most of."""
    _program(institution=None, provision_type=Program.ProvisionType.JOINT)

    with pytest.raises(IntegrityError), transaction.atomic():
        _program(institution=None, provision_type=Program.ProvisionType.JOINT)


def test_a_joint_programme_holds_several_awarding_institutions() -> None:
    program = _program(institution=None, provision_type=Program.ProvisionType.JOINT)
    program.awarding_institutions.add(_institution("fi:uef"), _institution("jp:toyohashi"))

    assert program.awarding_institutions.count() == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/funding/test_program_providers.py -q`
Expected: FAIL — `AttributeError: type object 'Program' has no attribute 'ProvisionType'`

- [ ] **Step 3: Change the model**

In `apps/funding/models.py`, inside `class Program`, add the choices class beside the existing `DegreeLevel` / `AcademicTrack`:

```python
    class ProvisionType(models.TextChoices):
        SINGLE = "SINGLE"
        JOINT = "JOINT"
```

Replace line 492:

```python
    institution = models.ForeignKey(Institution, null=True, on_delete=models.PROTECT)
```

Add after it:

```python
    #: The universities that award a jointly-provided programme. EACEA's
    #: Erasmus Mundus listing is one row per consortium, so this is the common
    #: case rather than the exception -- see the 2026-09-13 providers design.
    awarding_institutions: models.ManyToManyField[
        Institution, "ProgramAwardingInstitution"
    ] = models.ManyToManyField(
        Institution,
        through="ProgramAwardingInstitution",
        through_fields=("program", "institution"),
        related_name="awarded_programs",
    )
    #: db_default as well as default: catalog_ingestion writes SQL, and a plain
    #: INSERT omitting these columns must still produce a row the constraint
    #: below accepts.
    provision_type = models.CharField(
        max_length=10,
        choices=ProvisionType.choices,
        default=ProvisionType.SINGLE,
        db_default=ProvisionType.SINGLE,
    )
    #: The provider string exactly as scraped, on JOINT rows only. This is the
    #: curation queue's payload: a human reads it without opening a snapshot.
    provider_text = models.CharField(max_length=500, blank=True, default="", db_default="")
```

In `Program.Meta.constraints`, replace the existing unique constraint and add the check:

```python
            models.UniqueConstraint(
                fields=("institution", "canonical_key", "location_key"),
                name="program_institution_key_location_uniq",
                nulls_distinct=False,
            ),
            #: SINGLE carries an institution and no provider text; JOINT carries
            #: provider text and no institution. In the database, not a
            #: validator: catalog_ingestion never runs model code.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        provision_type="SINGLE", institution__isnull=False, provider_text=""
                    )
                    | models.Q(provision_type="JOINT", institution__isnull=True)
                ),
                name="program_provision_type_valid",
            ),
```

At the end of the module, beside `FundingOpportunityProgram`:

```python
class ProgramAwardingInstitution(models.Model):
    program = models.ForeignKey(Program, on_delete=models.PROTECT)
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT)

    class Meta:
        db_table = "funding_program_awarding_institutions"
        constraints = [
            models.UniqueConstraint(
                fields=("program", "institution"),
                name="program_awarding_institution_pair_uniq",
            )
        ]
```

- [ ] **Step 4: Generate the schema migration**

Run: `POSTGRES_DB=tehsil_joint uv run python manage.py makemigrations funding --name program_providers`
Expected: creates `apps/funding/migrations/0029_program_providers.py`.

Open it and confirm it contains `AlterField` on `institution`, `AddField` for `provision_type` and `provider_text`, `CreateModel` for `ProgramAwardingInstitution`, `AddField` for `awarding_institutions`, plus the two constraint operations. Add nothing by hand.

- [ ] **Step 5: Write the RLS migration**

`funding_program_awarding_institutions` is shared-catalog data and needs the same two policies every other shared table has. Create `apps/funding/migrations/0030_program_awarding_institutions_rls.py`:

```python
# funding_program_awarding_institutions joins _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalog data: which
# universities award a programme is the same fact for every tenant.
# Same shape as 0026_institution_identifier_rls -- both the
# shared_catalog_select read policy and the catalog_ingestion_write policy,
# from the start.
from django.db import migrations

TABLE = "funding_program_awarding_institutions"

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
        ('funding', '0029_program_providers'),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
```

- [ ] **Step 6: Register the table as shared**

In `tests/tenancy/test_database_isolation.py`, add to `_SHARED_TABLES` after `"funding_program_evidence_claims"`:

```python
    "funding_program_awarding_institutions",
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/funding/test_program_providers.py tests/tenancy/test_database_isolation.py -q`
Expected: PASS

- [ ] **Step 8: Run the full gate and commit**

```bash
W=/home/orkhan/Desktop/tehsil_agent/.worktrees/deqar-adapter
POSTGRES_DB=tehsil_joint uv run pytest -q && uv run ruff check . && uv run mypy . \
  && POSTGRES_DB=tehsil_joint uv run python manage.py makemigrations --check --dry-run
git -C $W add apps/funding/models.py apps/funding/migrations/0029_program_providers.py \
  apps/funding/migrations/0030_program_awarding_institutions_rls.py \
  tests/tenancy/test_database_isolation.py tests/funding/test_program_providers.py
git -C $W commit -m "feat(funding): a programme may be awarded by several institutions"
```

---

### Task 2: The source declares whether its programmes are jointly awarded

**Files:**
- Modify: `apps/research/discovery.py:144-161` (the `LeadSource` protocol), `apps/research/discovery.py:78-92` (`ResearchLead`), `apps/research/discovery.py:379-391` (`_tagged`)
- Modify: `apps/research/seeds.py:28` (`HtmlCatalogue`), `apps/research/seeds.py:110` (`EACEA_ERASMUS_MUNDUS`)
- Modify: `apps/research/search.py:85` (`SearchSource`), `apps/research/search.py:244` (`EntityExpansionSource`)
- Test: `tests/research/test_joint_source.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `LeadSource.awards_jointly -> bool` (protocol property); `ResearchLead.awards_jointly: bool` defaulting `False`; `HtmlCatalogue(awards_jointly=...)` keyword.

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_joint_source.py`:

```python
from dataclasses import dataclass
from collections.abc import Iterator

from apps.research.discovery import DiscoveryQuery, ResearchLead, _tagged
from apps.research.seeds import EACEA_ERASMUS_MUNDUS

QUERY = DiscoveryQuery(field="robotics", country_code="DE", degree_level="MASTER")


@dataclass(frozen=True)
class _FakeSource:
    name: str
    one_programme_per_link: bool
    awards_jointly: bool

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        yield ResearchLead.from_url(
            "https://example.org/programme",
            source_type="PROGRAM",
            funding_family="MULTILATERAL",
        )


def test_a_lead_from_a_joint_awarding_source_is_marked_joint() -> None:
    source = _FakeSource("seed:fake", one_programme_per_link=True, awards_jointly=True)

    (lead,) = _tagged(source, QUERY, None)

    assert lead.awards_jointly is True


def test_a_registry_source_is_one_programme_per_link_but_not_joint() -> None:
    """The distinction Korea and Finland will need (pipeline.py:422): a registry
    promises one programme per link while listing single-provider programmes.
    Conflating the two flags marks every Korean programme joint."""
    source = _FakeSource("seed:registry", one_programme_per_link=True, awards_jointly=False)

    (lead,) = _tagged(source, QUERY, None)

    assert lead.one_programme_per_site is True
    assert lead.awards_jointly is False


def test_a_lead_cannot_promote_itself() -> None:
    source = _FakeSource("seed:fake", one_programme_per_link=False, awards_jointly=False)

    (lead,) = _tagged(source, QUERY, None)

    assert lead.awards_jointly is False


def test_the_eacea_seed_awards_jointly() -> None:
    """EACEA's listing is one row per Erasmus Mundus consortium, so every
    programme on it is jointly awarded."""
    assert EACEA_ERASMUS_MUNDUS.awards_jointly is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/research/test_joint_source.py -q`
Expected: FAIL — `AttributeError: 'ResearchLead' object has no attribute 'awards_jointly'`

- [ ] **Step 3: Add the flag to the protocol, the lead, and every source**

In `apps/research/discovery.py`, add to the `LeadSource` protocol after `one_programme_per_link`:

```python
    @property
    def awards_jointly(self) -> bool: ...
```

Add to `ResearchLead`, after `one_programme_per_site`:

```python
    #: Whether the source promises that its programmes are awarded by several
    #: universities together. NOT the same claim as one_programme_per_site,
    #: which says one link is one programme: the Korea and Finland registry
    #: sources (pipeline.py) will set that while listing single-provider
    #: programmes. Set by _tagged from the source, never by a caller.
    awards_jointly: bool = False
```

Replace the body of `_tagged`'s loop:

```python
        for lead in source.find(query):
            tagged = lead if lead.discovered_by else replace(lead, discovered_by=source.name)
            if source.one_programme_per_link and tagged.can_support_claim:
                tagged = replace(tagged, one_programme_per_site=True)
            if source.awards_jointly:
                tagged = replace(tagged, awards_jointly=True)
            yield tagged
```

In `apps/research/seeds.py`, add to `HtmlCatalogue` beside `one_programme_per_link`:

```python
    #: Whether every programme this catalogue lists is awarded by several
    #: universities together. True for EACEA: its listing is one row per
    #: Erasmus Mundus consortium.
    awards_jointly: bool = False
```

and add `awards_jointly=True,` to `EACEA_ERASMUS_MUNDUS`.

In `apps/research/search.py`, add to both `SearchSource` and `EntityExpansionSource`, beside their existing `one_programme_per_link`:

```python
    #: A search hit says nothing about who awards the programme.
    awards_jointly: bool = False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/research/test_joint_source.py -q`
Expected: PASS

- [ ] **Step 5: Run the full gate and commit**

```bash
W=/home/orkhan/Desktop/tehsil_agent/.worktrees/deqar-adapter
POSTGRES_DB=tehsil_joint uv run pytest -q && uv run ruff check . && uv run mypy .
git -C $W add apps/research/discovery.py apps/research/seeds.py apps/research/search.py \
  tests/research/test_joint_source.py
git -C $W commit -m "feat(research): a seed declares whether its programmes are jointly awarded"
```

---

### Task 3: The name fallback rule

**Files:**
- Modify: `apps/research/catalog.py` (add beside `_origin:390`)
- Test: `tests/research/test_joint_names.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `apps.research.catalog.names_several_providers(name: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_joint_names.py`:

```python
import pytest

from apps.research.catalog import names_several_providers

# Every composite name manage.py discover has actually written, 2026-09-13.
COMPOSITE = (
    "University of Belgrade; Libera Università Maria SS. Assunta (LUMSA); Örebro University",
    "University of Murcia; Lund University; Friedrich-Alexander-Universität Erlangen-Nürnberg",
    "IMLEX consortium: University of Eastern Finland; Toyohashi University of Technology",
    "Art Academy of Latvia / SDSI consortium",
    "ECT+ Consortium",
    "Erasmus Mundus Journalism Consortium",
    "Copernicus Master in Digital Earth consortium universities",
)

# Plain university names from the same run, and the two false-positive families
# measured against DEQAR's 9,030 institutions. Both families are real single
# institutions and must stay single: bilingual names joined by a slash, and the
# Finnish "University Consortium", which is one legal institution.
SINGLE = (
    "University of Glasgow",
    "Université de Lille",
    "Norwegian University of Science and Technology (NTNU)",
    "Università degli Studi di Padova",
    "Western Norway University of Applied Sciences (HVL)",
)


@pytest.mark.parametrize("name", COMPOSITE)
def test_a_composite_provider_name_is_joint(name: str) -> None:
    assert names_several_providers(name) is True


@pytest.mark.parametrize("name", SINGLE)
def test_a_plain_university_name_is_not_joint(name: str) -> None:
    assert names_several_providers(name) is False


@pytest.mark.parametrize(
    "name",
    (
        "Universidad del País Vasco / Euskal Herriko Unibertsitatea",
        "Kirchliche Hochschule Wuppertal / Bethel (ev)",
        "Kajaani University Consortium",
        "Lahti University Consortium",
    ),
)
def test_the_measured_false_positives_are_accepted_deliberately(name: str) -> None:
    """19 of DEQAR's 9,030 institutions trip this rule -- bilingual names joined
    by a slash, and Finnish university consortia. They are flagged on purpose:
    a false JOINT costs one human glance and creates nothing, while a false
    SINGLE mints an Institution that can never bind to a register. Task 5's
    loader resolves them to SINGLE with no special case. Do not tune the rule
    to pass these."""
    assert names_several_providers(name) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/research/test_joint_names.py -q`
Expected: FAIL — `ImportError: cannot import name 'names_several_providers'`

- [ ] **Step 3: Write the rule**

In `apps/research/catalog.py`, beside `_origin`:

```python
#: Measured 2026-09-13: 7 of 7 composite names written by discover are caught,
#: 15 of 15 plain names are not, and 19 of DEQAR's 9,030 real institutions are
#: flagged (0.2%) -- bilingual names joined by a slash, and Finnish university
#: consortia. The bias is deliberate; see the 2026-09-13 providers design §3.2.
_JOINT_NAME_MARKERS = (";", " / ", "consortium")


def names_several_providers(name: str) -> bool:
    """Whether a provider name looks like several universities rather than one.

    The FALLBACK only. The source's own ``awards_jointly`` is the primary rule
    and is the one that catches a coordinator's plain name -- which no name
    rule can see.
    """
    lowered = name.casefold().rstrip()
    return any(marker in lowered for marker in _JOINT_NAME_MARKERS) or lowered.endswith(
        "universities"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/research/test_joint_names.py -q`
Expected: PASS

- [ ] **Step 5: Run the full gate and commit**

```bash
W=/home/orkhan/Desktop/tehsil_agent/.worktrees/deqar-adapter
POSTGRES_DB=tehsil_joint uv run pytest -q && uv run ruff check . && uv run mypy .
git -C $W add apps/research/catalog.py tests/research/test_joint_names.py
git -C $W commit -m "feat(research): recognise a provider name that names several universities"
```

---

### Task 4: The writer stops inventing institutions, and the queue is visible

**Files:**
- Modify: `apps/research/catalog.py:64-69` (`CatalogWriteResult`), `apps/research/catalog.py:422-449` (the `get_or_create` pair), `apps/research/catalog.py:459-464` (the `InstitutionEvidenceClaim` branch)
- Modify: `apps/research/pipeline.py:92-97` (`DiscoveryReport`), `apps/research/pipeline.py:400-412` and `:440-460` (the write loop and the degraded summary)
- Test: `tests/research/test_catalog_writer.py`

**Interfaces:**
- Consumes: `Program.ProvisionType` and `Program.provider_text` (Task 1); `ResearchLead.awards_jointly` (Task 2); `names_several_providers` (Task 3).
- Produces: `CatalogWriteResult.institution: Institution | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/research/test_catalog_writer.py`:

```python
def _joint_lead() -> ResearchLead:
    """What _tagged produces for a lead harvested from seed:eacea."""
    return replace(_official_lead(), awards_jointly=True, discovered_by="seed:eacea")


def test_a_joint_lead_writes_no_institution_at_all(source, snapshot) -> None:
    """The assertion this whole change exists for: a jointly-awarded programme
    must never mint an Institution keyed on a scraped provider name, because
    such a row can never bind to a register code."""
    before = Institution._base_manager.count()

    result = write_catalog_entry(
        lead=_joint_lead(), claims=CLAIMS, source=source, snapshot=snapshot
    )

    assert result is not None
    assert result.institution is None
    assert Institution._base_manager.count() == before
    assert result.program.institution_id is None
    assert result.program.provision_type == "JOINT"
    assert result.program.provider_text == "University of Technology Nuremberg"


def test_a_joint_lead_writes_no_institution_evidence_claim(source, snapshot) -> None:
    result = write_catalog_entry(
        lead=_joint_lead(), claims=CLAIMS, source=source, snapshot=snapshot
    )

    assert result is not None
    assert InstitutionEvidenceClaim._base_manager.count() == 0
    assert any(claim.claim_class == "IDENTITY" for claim in result.claims)


def test_a_composite_provider_name_is_joint_without_a_source_promise(source, snapshot) -> None:
    """The fallback path: a source that promises nothing still must not mint an
    Institution from 'A; B; C'."""
    lead = ResearchLead.from_url(
        "https://example.org/programme",
        source_type="PROGRAM",
        funding_family="MULTILATERAL",
        discovered_by="entity-expansion",
        identity=LeadIdentity(
            institution_name="University of Belgrade; LUMSA; Örebro University",
            country_code="RS",
            city="Belgrade",
            program_name="Joint Master",
        ),
    )
    before = Institution._base_manager.count()

    result = write_catalog_entry(lead=lead, claims=CLAIMS, source=source, snapshot=snapshot)

    assert result is not None
    assert result.institution is None
    assert Institution._base_manager.count() == before


def test_a_single_lead_still_writes_its_institution(source, snapshot) -> None:
    result = write_catalog_entry(
        lead=_official_lead(), claims=CLAIMS, source=source, snapshot=snapshot
    )

    assert result is not None
    assert result.institution is not None
    assert result.institution.name == "University of Technology Nuremberg"
    assert result.program.provision_type == "SINGLE"
    assert result.program.provider_text == ""
```

Add `InstitutionEvidenceClaim` and `LeadIdentity` to the file's existing imports if absent.

Add `from dataclasses import replace`, plus `InstitutionEvidenceClaim` and `LeadIdentity`, to the file's existing imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/research/test_catalog_writer.py -q`
Expected: FAIL — the joint lead still creates an `Institution`, so `result.institution is None` fails.

- [ ] **Step 3: Change the writer**

In `apps/research/catalog.py`, widen the result type:

```python
@dataclass(frozen=True)
class CatalogWriteResult:
    #: None for a jointly-awarded programme: no Institution is invented for it.
    institution: Institution | None
    program: Program
    claims: tuple[OfficialEvidenceClaim, ...]
    opportunity: FundingOpportunity | None
    #: Dates whose year the model fabricated, dropped rather than stored. Not a
    #: silence: run_discovery reports the run's total in DiscoveryReport.degraded.
    unreadable_dates: int = 0
```

Only the `institution` annotation changes; the remaining fields are unchanged and
are repeated here so the whole dataclass is in front of you.

Replace the `Institution.objects.get_or_create(...)` / `Program.objects.get_or_create(...)` pair:

```python
    # The source's promise first, the name's shape second. A coordinator's
    # plain name ("University of Glasgow") is invisible to any name rule --
    # only the seed knows EACEA lists one consortium per row.
    jointly_awarded = lead.awards_jointly or names_several_providers(
        program_facts.institution_name
    )
    institution = None
    if not jointly_awarded:
        institution, _created = Institution.objects.get_or_create(
            canonical_key=catalog_key(
                program_facts.country_code, program_facts.institution_name
            ),
            defaults={
                "name": program_facts.institution_name,
                "country_code": program_facts.country_code,
                "official_website": _origin(source.canonical_url),
            },
        )
    program, _created = Program.objects.get_or_create(
        institution=institution,
        canonical_key=catalog_key(program_facts.degree_level, program_facts.program_name),
        # Constant per institution, not per city: §2.5's dedupe key is
        # (institution, programme name, degree level), and a catalogue's
        # "Nürnberg" against a university's "Nuremberg" must not fork the row.
        # ponytail: revisit when a genuinely multi-campus programme appears.
        location_key=location_key(
            country_code=program_facts.country_code, city=program_facts.institution_name
        ),
        defaults={
            "name": program_facts.program_name,
            "campus_name": program_facts.city or program_facts.institution_name,
            "city": program_facts.city or program_facts.institution_name,
            "country_code": program_facts.country_code,
            "degree_level": program_facts.degree_level,
            "teaching_languages": list(program_facts.teaching_languages),
            "duration_months": program_facts.duration_months,
            "provision_type": (
                Program.ProvisionType.JOINT
                if jointly_awarded
                else Program.ProvisionType.SINGLE
            ),
            # The scraped string, unsplit: a name is not a binding, so the
            # curator gets what the page said and decides (design §3.3).
            "provider_text": program_facts.institution_name if jointly_awarded else "",
        },
    )
```

Guard the identity-claim branch — there is no institution to attach it to:

```python
        if claim_class == OfficialEvidenceClaim.ClaimClass.IDENTITY and institution is not None:
            InstitutionEvidenceClaim.objects.get_or_create(
                institution=institution, evidence_claim=claim
            )
```

- [ ] **Step 4: Make the queue visible in the discovery report**

In `apps/research/pipeline.py`, add to `DiscoveryReport`:

```python
    joint_pending: int = 0
```

In `run_discovery`, beside the other counters, add `joint_programs: set[UUID] = set()`. After each successful `write_catalog_entry` call — both the main loop and the held-page loop — record:

```python
        if result is not None and result.program.provision_type == Program.ProvisionType.JOINT:
            joint_programs.add(result.program.id)
```

A set, not a counter: one programme routinely arrives on several pages and must be queued once.

Before building the report, add the summary line:

```python
    if joint_programs:
        degraded.append(
            f"{len(joint_programs)} joint programmes await provider resolution"
        )
```

and pass `joint_pending=len(joint_programs)` to `DiscoveryReport`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/research/test_catalog_writer.py tests/research/test_discovery_pipeline.py -q`
Expected: PASS

- [ ] **Step 6: Run the full gate and commit**

```bash
W=/home/orkhan/Desktop/tehsil_agent/.worktrees/deqar-adapter
POSTGRES_DB=tehsil_joint uv run pytest -q && uv run ruff check . && uv run mypy .
git -C $W add apps/research/catalog.py apps/research/pipeline.py tests/research/test_catalog_writer.py
git -C $W commit -m "feat(research): a joint programme writes no invented institution"
```

---

### Task 5: `load_program_providers`, and the spec corrections

**Files:**
- Create: `apps/funding/management/commands/load_program_providers.py`
- Create: `docs/research/program-providers.csv`
- Modify: `docs/superpowers/specs/2026-09-07-institution-identifier-binding-design.md` (§5 and §9)
- Modify: `docs/superpowers/research/2026-09-07-institution-identifier-matching.md` (§7)
- Test: `tests/funding/test_load_program_providers.py`

**Interfaces:**
- Consumes: `Program.ProvisionType`, `Program.provider_text`, `Program.awarding_institutions` (Task 1).
- Produces: `manage.py load_program_providers <csv_path>`, printing `loaded=<pairs> resolved=<programmes flipped to SINGLE>`.

- [ ] **Step 1: Write the failing tests**

Create `tests/funding/test_load_program_providers.py`:

```python
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.funding.models import Institution, Program

pytestmark = pytest.mark.django_db

HEADER = "program_key,institution_key,name,country_code,official_website\n"


def _csv(tmp_path, body: str):
    path = tmp_path / "providers.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return str(path)


def _joint(
    canonical_key: str = "master:imlex",
    provider_text: str = "A; B",
    location_key: str = "fi:joensuu",
) -> Program:
    return Program._base_manager.create(
        institution=None,
        provision_type=Program.ProvisionType.JOINT,
        provider_text=provider_text,
        canonical_key=canonical_key,
        name="IMLEX",
        campus_name="Joensuu",
        city="Joensuu",
        country_code="FI",
        location_key=location_key,
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )


def test_it_binds_several_institutions_to_one_joint_programme(tmp_path) -> None:
    program = _joint()
    path = _csv(
        tmp_path,
        "master:imlex,fi:uef,University of Eastern Finland,FI,https://www.uef.fi/\n"
        "master:imlex,jp:toyohashi,Toyohashi University of Technology,JP,https://www.tut.ac.jp/\n",
    )

    call_command("load_program_providers", path)

    program.refresh_from_db()
    assert program.awarding_institutions.count() == 2
    assert program.provision_type == "JOINT"


def test_it_creates_an_institution_the_catalog_does_not_have(tmp_path) -> None:
    """This is the hand-curation path two specs assumed already existed: a
    person wrote the row, so canonical_key is hand-curated."""
    _joint()
    path = _csv(
        tmp_path,
        "master:imlex,se:orebro,Örebro University,SE,https://www.oru.se/\n"
        "master:imlex,rs:belgrade,University of Belgrade,RS,https://www.bg.ac.rs/\n",
    )

    call_command("load_program_providers", path)

    created = Institution._base_manager.get(canonical_key="se:orebro")
    assert created.name == "Örebro University"
    assert created.country_code == "SE"


def test_one_named_provider_resolves_the_programme_to_single(tmp_path) -> None:
    """The Basque and Finnish false positives of the name rule land here and
    need no special case."""
    program = _joint(provider_text="Universidad del País Vasco / Euskal Herriko Unibertsitatea")
    path = _csv(
        tmp_path,
        "master:imlex,es:ehu,Universidad del País Vasco,ES,https://www.ehu.eus/\n",
    )

    call_command("load_program_providers", path)

    program.refresh_from_db()
    assert program.provision_type == "SINGLE"
    assert program.institution.canonical_key == "es:ehu"
    assert program.provider_text == ""


def test_it_refuses_a_programme_key_that_names_nothing(tmp_path) -> None:
    path = _csv(tmp_path, "master:nope,fi:uef,University of Eastern Finland,FI,https://www.uef.fi/\n")

    with pytest.raises(CommandError, match="no joint programme"):
        call_command("load_program_providers", path)


def test_it_refuses_an_ambiguous_programme_key(tmp_path) -> None:
    _joint()
    _joint(canonical_key="master:imlex", location_key="be:ghent")
    path = _csv(tmp_path, "master:imlex,fi:uef,University of Eastern Finland,FI,https://www.uef.fi/\n")

    with pytest.raises(CommandError, match="matches 2 joint programmes"):
        call_command("load_program_providers", path)


def test_it_refuses_a_missing_column(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("program_key,institution_key\nmaster:imlex,fi:uef\n", encoding="utf-8")

    with pytest.raises(CommandError, match="missing expected column"):
        call_command("load_program_providers", str(path))


def test_it_refuses_a_plaintext_website(tmp_path) -> None:
    _joint()
    path = _csv(tmp_path, "master:imlex,fi:uef,University of Eastern Finland,FI,http://www.uef.fi/\n")

    with pytest.raises(CommandError, match="must be https"):
        call_command("load_program_providers", path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/funding/test_load_program_providers.py -q`
Expected: FAIL — `CommandError: Unknown command: 'load_program_providers'`

- [ ] **Step 3: Write the command**

Create `apps/funding/management/commands/load_program_providers.py`:

```python
"""Load curated programme-provider bindings from a CSV.

    DATABASE_ROLE=migration uv run python manage.py load_program_providers \\
        docs/research/program-providers.csv

Which universities award a programme is shared-catalog data every tenant
reads, so it lives in a checked-in file rather than a bare database write:
in a file it is a reviewed diff, attributable and revertable. Same reasoning
as load_institution_identifiers, and the curator's next step is that command.

funding_program_awarding_institutions carries a SELECT-only
shared_catalog_select policy, so run this as the migration or
catalog_ingestion role. This loader is insert-only for the pair table, and an
INSERT blocked by RLS raises, so a wrong-role run fails loudly.

It is also the hand-curation route for Institution itself: a row naming an
institution the catalog does not have creates it, which is what makes
"canonical_key is hand-curated" true rather than aspirational.
"""

from __future__ import annotations

import csv

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.funding.models import Institution, Program, ProgramAwardingInstitution

_REQUIRED_COLUMNS = ("program_key", "institution_key", "name", "country_code", "official_website")


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("csv_path")

    def handle(self, *args: object, **options: object) -> None:
        path = str(options["csv_path"])
        # utf-8-sig: an Excel re-export carries a BOM, which under plain utf-8
        # corrupts the first header and makes every row look unmapped.
        with open(path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = [c for c in _REQUIRED_COLUMNS if c not in (reader.fieldnames or ())]
            if missing:
                raise CommandError(f"CSV is missing expected column(s): {missing}")
            rows = list(reader)

        by_program: dict[str, list[dict[str, str]]] = {}
        for line, row in enumerate(rows, start=2):
            website = row["official_website"].strip()
            if not website.startswith("https://"):
                raise CommandError(f"line {line}: {website!r} must be https")
            if len(row["country_code"].strip()) != 2:
                raise CommandError(
                    f"line {line}: {row['country_code']!r} is not an ISO 3166 alpha-2 code"
                )
            by_program.setdefault(row["program_key"].strip(), []).append(row)

        loaded = 0
        resolved = 0
        with transaction.atomic():
            for program_key, program_rows in by_program.items():
                matches = list(
                    Program._base_manager.filter(
                        canonical_key=program_key,
                        provision_type=Program.ProvisionType.JOINT,
                    )
                )
                if not matches:
                    raise CommandError(f"no joint programme with key {program_key!r}")
                if len(matches) > 1:
                    raise CommandError(
                        f"{program_key!r} matches {len(matches)} joint programmes -- "
                        f"a human must say which"
                    )
                program = matches[0]
                institutions = []
                for row in program_rows:
                    institution, _created = Institution._base_manager.get_or_create(
                        canonical_key=row["institution_key"].strip(),
                        defaults={
                            "name": row["name"].strip(),
                            "country_code": row["country_code"].strip().upper(),
                            "official_website": row["official_website"].strip(),
                        },
                    )
                    institutions.append(institution)
                    ProgramAwardingInstitution._base_manager.create(
                        program=program, institution=institution
                    )
                    loaded += 1
                # Exactly one provider means it was never joint -- the name rule's
                # measured false positives (a bilingual name, a Finnish
                # "University Consortium") resolve here with no special case.
                if len(institutions) == 1:
                    program.institution = institutions[0]
                    program.provision_type = Program.ProvisionType.SINGLE
                    program.provider_text = ""
                    program.save(
                        update_fields=["institution", "provision_type", "provider_text"]
                    )
                    resolved += 1

        self.stdout.write(f"loaded={loaded} resolved={resolved}")
```

- [ ] **Step 4: Create the empty curated file**

Create `docs/research/program-providers.csv` with the header only — the rows are a human's work, not this task's:

```csv
program_key,institution_key,name,country_code,official_website
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/funding/test_load_program_providers.py -q`
Expected: PASS

- [ ] **Step 6: Add the wrong-role test**

Append to `tests/funding/test_load_program_providers.py`:

```python
def test_it_fails_under_the_ordinary_runtime_role(tmp_path, rls_enforced_orm) -> None:
    """The suite otherwise runs as a BYPASSRLS superuser, so without this
    fixture a wrong-role run passes here and fails in production. This is the
    coverage the register adapters still lack."""
    _joint()
    path = _csv(
        tmp_path,
        "master:imlex,fi:uef,University of Eastern Finland,FI,https://www.uef.fi/\n",
    )

    with pytest.raises(Exception, match="row-level security"):
        call_command("load_program_providers", path)

    assert ProgramAwardingInstitution._base_manager.count() == 0
```

Import `ProgramAwardingInstitution` at the top of the file. If `rls_enforced_orm` cannot create the joint programme fixture under the restricted role, create the programme before the fixture takes effect by requesting the fixture last in the signature, as `tests/portals/test_rls_spine.py` does.

Run: `POSTGRES_DB=tehsil_joint uv run pytest tests/funding/test_load_program_providers.py -q`
Expected: PASS

- [ ] **Step 7: Correct the three false spec sentences**

In `docs/superpowers/specs/2026-09-07-institution-identifier-binding-design.md`, append to §5 (after "…so the catalog is small and grows deliberately."):

```markdown
**Correction, 2026-09-13: `Institution` has a writer and did when this was
written.** `apps/research/catalog.py::write_catalog_entry`, reached from
`manage.py discover` via `pipeline.py:402` and `:434`, creates one per lead
keyed on a scraped provider name. The 22 rows in the dev database are all its
output. This paragraph's conclusion — that binding is paid once at a moment a
human is already curating — becomes true only with
`load_program_providers` (2026-09-13 providers design §4), which is the
hand-curation route this assumed already existed.
```

Append to §9's "How many institutions this actually touches" bullet:

```markdown
  **Measured 2026-09-13: 22, all from the one seed `seed:eacea`, and all
  jointly awarded.** See the 2026-09-13 providers design §1.
```

In `docs/superpowers/research/2026-09-07-institution-identifier-matching.md`, append to §7's "Not settled" paragraph:

```markdown
**Correction, 2026-09-13:** "`Institution` has no writer — nothing outside
tests and migrations creates a row" is false and was false when written.
`write_catalog_entry` creates one per discovered lead. The count is 22 today.
See the 2026-09-13 providers design §1.1.
```

- [ ] **Step 8: Run the full gate and commit**

```bash
W=/home/orkhan/Desktop/tehsil_agent/.worktrees/deqar-adapter
POSTGRES_DB=tehsil_joint uv run pytest -q && uv run ruff check . && uv run mypy . \
  && POSTGRES_DB=tehsil_joint uv run python manage.py makemigrations --check --dry-run \
  && uv run bandit -c pyproject.toml -r apps config
git -C $W add apps/funding/management/commands/load_program_providers.py \
  docs/research/program-providers.csv tests/funding/test_load_program_providers.py \
  docs/superpowers/specs/2026-09-07-institution-identifier-binding-design.md \
  docs/superpowers/research/2026-09-07-institution-identifier-matching.md
git -C $W commit -m "feat(funding): curate which universities award a joint programme"
```

---

## Done when

- `POSTGRES_DB=tehsil_joint uv run pytest -q` passes, with the register-adapter suite untouched.
- A lead from `seed:eacea` writes a `Program` and **zero** `Institution` rows.
- A lead from a `one_programme_per_link` registry source is **not** marked joint.
- `manage.py discover` reports how many joint programmes await provider resolution.
- The three corrected spec sentences no longer assert `Institution` is unwritten.
