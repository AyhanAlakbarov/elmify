# Enumerators (build item 7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enumerate the closed part of the funding space for two launch countries (Türkiye and Azerbaijan) and for the country-less intergovernmental and regional-fund list. Every body a list names ends bound to an `Organisation` and carries a recorded read state. Wikidata, ROR and the EACEA project API feed the same register, and each is scoped to what it can answer alone. The gate is **100% enumerated, with a read state recorded for every entry**, printed by one command and exiting non-zero when it fails.

**Architecture:** One data-driven closed-list engine. `ClosedList` holds one sourced row per list: URL, maintainer, terms, verified-on date, read policy and printed size. It is loaded from `docs/research/closed-lists.csv`, and each hand-read list's rows come from `docs/research/closed-lists/<slug>.csv`. List rows land in the existing `RegisterEntry` table, which gains cell tags, a scheme page, a funded period and a read state, and they reach the register only through `record_organisation`. `read_state.py` works out each entry's read state from records other code already writes (snapshots, the classifier's columns, the fetch trail), stores it on the entry, and runs the gate as arithmetic over that table. Three adapters (`wikidata.py`, `ror.py`, `eacea.py`) write `CANDIDATE` bodies through the same door. EACEA also writes `RegisterEntryPartner` rows: the EMJM partner binding, PIC first and domain second. A `ClosedListSource` `LeadSource` hands a list's scheme pages to the existing `run_discovery` funding reader, so nothing reads a page by a second route.

**Tech Stack:** Django 5.2 / Python 3.14 / Postgres 17; `uv run` for everything; pytest with `pytestmark = pytest.mark.django_db`; `csv` from the standard library; `egress.fetch_json_api` for the three JSON sources; the vendor fetch seam (`apps.research.fetch.fetch_page`) for pages; the existing funding reader (`pipeline.run_discovery` with both model families) and classifier (`manage.py classify_organisations`).

**Spec:** `docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md`: §3 (principles 2, 4, 7 and "country is data"), §5 (the universe table), §6.1, §6.2 (closed-list engine, register table, register ladder), §6.3 (the government-outbound, professional-body/bank and multilateral rows), §6.4a (the per-family table), §11 (what reaches a person), §12, §14, §15, §16 item 7, §19 (the multilateral gap, the register survey, professional bodies and banks), decisions 31, 34 and 35. Also read `docs/superpowers/specs/2026-09-14-emjm-partner-source-design.md` §2–§4 and §8 (the EACEA request, its traps, the two-key binding) and `CLAUDE.md` §"Web fetching" (the EACEA bullet) and §"Row-level security". This plan argues nothing those documents already argue.

---

## Scope: what each source answers alone, and what it does not

Each source writes only the facts it can establish by itself. What it cannot establish is left to a named later step and never guessed.

| source | answers alone | does not answer: who does | writes |
|---|---|---|---|
| **Intergovernmental and regional-fund list** (hand-compiled, global, cell-tagged) | which intergovernmental and regional bodies run a master's-level award open to individuals; the scheme page on the body's own site; the home × host cells the scheme page states | the award's facts (the funding reader, §8); whether this cycle is open (item 11) | `REGISTERED` bodies, one entry per scheme |
| **Curated national lists**, TR and AZ (read by hand from a published list, or compiled where none is published) | the finite set of bodies of one kind in one country, with each body's own website; the list's printed size | whether a body funds students (the classifier, §6.6); award facts (the reader) | `REGISTERED` bodies. **The only route that promotes a body to `REGISTERED`** (§6.1, §6.2) |
| **Register survey** (`docs/research/register-survey.csv`) | which rung (§6.2 ladder) each (country, family) reaches: URL, maintainer, purpose filter, website/e-mail per row, access, reuse terms | anything about any body | nothing in the database; it decides which curated lists exist |
| **Wikidata** SPARQL, class × country × P856 | bodies of a class in a country that have an official website and no dissolution date; every label in every language | whether a body exists today, whether it is what its class says, whether it funds anyone. Crowd-sourced, so it never vouches | `CANDIDATE` bodies with a `WIKIDATA` identifier and all their labels. Entries sit on a **non-denominator** list, so a Wikidata count is never a coverage claim (§6.2: "a count from one is not a denominator for another") |
| **ROR** v2, country × type, and an exact `domains:` lookup | research, education and funding organisations with a stable id, domains, website and active/inactive status | anything reached by fuzzy name: the top hit "is sometimes a different organisation" (§6.2), so name lookup is measured for item 8 and never used here | `CANDIDATE` bodies with a `ROR` identifier. **Only after the ROR gate (Task 10) passes** |
| **EACEA project API**, `projectLevel3` × two action codes | every EMJM project (the complete list: every EMJM is an EU-funded project); each project's coordinator and partners with name, country, city, EU-PIC and website; the funded period where the response carries it | which `Program` row a project is (09-14 §8: a human, deferred); whether a partner awards degrees (CNR, CEPS and NGOs are partners too); an open intake after the funded period (only the page decides) | project entries on an `ENUMERATE_ONLY` list; partner bodies as `CANDIDATE` with an `EACEA_PIC` identifier; one `RegisterEntryPartner` row per participation, with its disposition |

**The two launch countries are Türkiye and Azerbaijan.** §6.7 names them first ("Azerbaijan and Türkiye home-side"). Türkiye already has rung 1 for foundations (item 6a, VGM). Azerbaijan is the thin-index country: 10–17% search precision, where §6.3 rule 4 switches the route to national registers, hub pages and hand curation, which is exactly this item. Choosing different countries means changing only rows in `register-survey.csv` and `closed-lists.csv`. No code changes.

**Not in this plan, and where each one lives:**

- **Build item 7 in §16 also lists** the BZSt rung-2 adapter (the second proof of the ladder), the Exa per-HEI first pass, and crt.sh plus `/map` inventory. The brief for this plan leaves them out. BZSt is recorded as a survey row (Task 6) and is a follow-up plan. The per-HEI pass and inventory belong with §6.4a and item 9.
- **DEQAR**, together with the succession walk the 09-14 design ran through it (`closure_date`, `historic_relationships`). Consequence: an EMJM partner that has since merged binds to whichever body holds its PIC or old domain. The final report (Task 13) names this limit. The repair is ROR's `relationships[type=successor]` or a DEQAR adapter, and it is a follow-up.
- **The resolver (item 8).** An unresolved row stays `UNRESOLVED`, counts in the denominator and reads `UNBOUND` in the gate. That is the correct failure.
- **`ResolutionItem` (item 12).** `CONFLICT` entries and partner rows are that queue's future writers' input. Here they are only counted and printed.
- **ANDISU** (Italy's DSU agencies, §19). It is a curated list with zero new code: one registry row and one rows file. It is outside the two launch countries, so it is recorded in the survey and not loaded.
- **The `Program` ↔ EACEA project join and `I5_FUNDED_DUAL_DEGREE` attachment.** This plan stores the funded period those need and nothing that consumes it.

## Global Constraints

- **Branch `claude/build-enumerators` from current `master`.** Do not hard-code a migration number. Before Task 1, run `ls apps/research/migrations/ | sort | tail -3`. As of 2026-09-25 the leaf is `0009_site_job_record_rls`. The new migration takes the next number and depends on whatever the leaf is. If another branch lands a research migration before this one merges, `makemigrations --check` in CI will report two leaves. Then add a merge migration with `uv run python manage.py makemigrations research --merge`, never a renumber (CLAUDE.md, "Migrations").
- **Test database:** every `pytest` and `manage.py` call carries `POSTGRES_DB=tehsil_enumerators`. Read `${PIPESTATUS[0]}`, never a piped exit code.
- **Do not edit** `apps/research/register.py`, `apps/research/pipeline.py`, `apps/research/funding_reader.py`, `apps/research/funding_judge.py`, `apps/research/vgm.py` or anything under `apps/funding/`. Other items (10, 11, 13) edit the reader and pipeline. This plan **calls** `record_organisation`, `run_discovery` and `_FAMILY_BY_HOLDER`, and changes none of them. The one shared module it touches is `apps/research/egress.py` (Task 7, one additive keyword argument).
- **Shared-catalog rule.** `ClosedList`, `RegisterEntry` and `RegisterEntryPartner` are read by every tenant, written only by `catalog_ingestion`, and never carry a person. RLS travels in the same migration as the tables. Verification goes through `runtime_connection`, because the test role bypasses RLS (CLAUDE.md §"Row-level security"). Catalog writes run under `DATABASE_ROLE=migration`, or `SET ROLE catalog_ingestion`, as `discover` already says.
- **No e-mail address and no person in any committed file.** The list loader refuses any cell containing `@`. A captured API fixture is trimmed to the keys the adapter reads. Grep every fixture for `@`, `contact`, `person`, `phone` and `email` before committing it.
- **Nothing names a scheme, funder or country in code** (§3 principle 7). Lists, classes, types, action codes and bounds are CSV rows under `docs/research/`. Code reads them.
- **Provider discipline.** Wikidata, ROR and EACEA are data sources under open terms (CC0, CC0, and the Europa reuse notice). Persisting what they return is permitted (CLAUDE.md: "do not carry either rule onto the other"). The page a list names is still fetched from the origin before any fact is read from it.
- **Validation before every commit:** `uv run ruff check apps config tests`, `uv run mypy apps config`, the focused tests, and `POSTGRES_DB=tehsil_enumerators uv run python manage.py makemigrations --check --dry-run`.
- **Commit convention:** `feat(research): …` / `test(research): …` / `docs(research): …`. One task per commit. End every commit message with the attribution lines your session's system prompt supplies.

---

## File structure

| file | responsibility |
|---|---|
| `apps/research/models.py` (modify) | `ClosedList`; nine fields and a `CONFLICT` resolution on `RegisterEntry`; `RegisterEntryPartner` |
| `apps/research/migrations/<next>_closed_lists.py` (create) | the fields, both tables, and RLS for both |
| `apps/research/closed_lists.py` (create) | read and validate the registry and list files; `record_list`; `ClosedListSource` |
| `apps/research/read_state.py` (create) | `ReadState`, `entry_read_state`, `record_read_states`, `list_gate` |
| `apps/research/wikidata.py` (create) | SPARQL enumeration and its writer |
| `apps/research/ror.py` (create) | the gate measurement, enumeration, and its writer |
| `apps/research/eacea.py` (create) | the project API, the partner binding, and its writer |
| `apps/research/egress.py` (modify) | `fetch_json_api(accept=...)` |
| `apps/research/management/commands/load_closed_lists.py` (create) | registry plus every rows file into the register |
| `apps/research/management/commands/closed_list_coverage.py` (create) | record read states, print the coverage line, `--gate` |
| `apps/research/management/commands/read_closed_list.py` (create) | a list's scheme pages through the funding reader |
| `apps/research/management/commands/enumerate_wikidata.py`, `ror_gate.py`, `enumerate_ror.py`, `enumerate_eacea.py` (create) | operator entries |
| `config/settings/base.py` (modify) | `CLOSED_LIST_RECHECK_DAYS`, `WIKIDATA_USER_AGENT`, `ROR_CLIENT_ID` |
| `docs/research/closed-lists.csv` (create) | one sourced row per list |
| `docs/research/closed-lists/*.csv` (create) | the hand-read lists |
| `docs/research/register-survey.csv` (create) | the survey per corridor country × family |
| `docs/research/wikidata-enumerations.csv`, `ror-enumerations.csv`, `eacea-actions.csv`, `ror-gate-names.csv` (create) | adapter configuration as data |
| `tests/research/test_closed_lists.py`, `test_closed_list_rls.py`, `test_read_state.py`, `test_closed_list_commands.py`, `test_register_survey.py`, `test_closed_list_data.py`, `test_wikidata.py`, `test_ror.py`, `test_eacea.py` (create); `test_egress.py` (modify) | the tests |
| `tests/research/fixtures/wikidata_tr_university.json`, `ror_domain_metu.json`, `ror_country_tr_education.json`, `eacea_emjm_page.json` (create, captured live, trimmed) | recorded responses |
| `tests/tenancy/test_database_isolation.py` (modify) | `_SHARED_TABLES` gains the two tables |
| `CLAUDE.md`, `docs/legal/2026-09-provider-terms.md` (modify) | the outbound paths and terms rows |
| `docs/superpowers/2026-09-2X-enumerators-gate.md` (create) | the gate run, numbers and limits |

---

### Task 0: Branch, leaf, green baseline

**Files:** none yet.

- [ ] **Step 1: Branch from master**

```bash
git fetch origin master && git checkout -b claude/build-enumerators origin/master
ls apps/research/migrations/ | sort | tail -3   # note the leaf; expect 0009_site_job_record_rls or later
```

- [ ] **Step 2: Prove the suite is green before touching anything**

```bash
POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_vgm.py tests/research/test_organisation_register.py tests/research/test_classify.py tests/tenancy/test_database_isolation.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
```

Expected: `… passed`, `EXIT=0`.

---

### Task 1: `ClosedList`, the `RegisterEntry` fields, `RegisterEntryPartner`, and their RLS

**Files:**
- Modify: `apps/research/models.py`
- Create: `apps/research/migrations/<next>_closed_lists.py`
- Modify: `tests/tenancy/test_database_isolation.py` (`_SHARED_TABLES`)
- Create: `tests/research/test_closed_list_rls.py`, `tests/research/test_closed_lists.py` (model tests first)

**Interfaces:**
- Produces: `ClosedList` (primary key `slug`), with `ClosedList.ReadPolicy.{FUNDING_READ, CLASSIFY, SIGNAL_ONLY, ENUMERATE_ONLY}` and `ClosedList.Terms.{OPEN, UNREAD, OWN_COMPILATION}`.
- Produces: `RegisterEntry.{country_code, kind, page_url, home_cells, host_cells, listed_from, listed_until, read_state, read_state_detail, read_state_at}` and `RegisterEntry.Resolution.CONFLICT`.
- Produces: `RegisterEntryPartner(entry, organisation, role, listed_name, listed_identifier, listed_domain, country_code, disposition)` and `RegisterEntryPartner.Disposition.{BOUND_BOTH, BOUND_PIC, BOUND_DOMAIN, NEW, CONFLICT, NO_KEY}`.

- [ ] **Step 1: Write the failing model tests**

```python
# tests/research/test_closed_lists.py
"""The closed-list engine: registry, rows, register writes, lead source.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
sections 6.1, 6.2, 16 item 7.
"""

from datetime import date

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.research.models import ClosedList, RegisterEntry, RegisterEntryPartner

pytestmark = pytest.mark.django_db


def _list(**overrides: object) -> ClosedList:
    fields: dict[str, object] = dict(
        slug="igo_regional_global", title="Intergovernmental and regional funds",
        country_code="", holder_kinds=["INTERGOVERNMENTAL", "REGIONAL_FUND"], rung=1,
        source_url="https://github.com/0rkhann/tehsil_agent/blob/master/docs/research/closed-lists/igo_regional_global.csv",
        maintainer="own compilation", carries_purpose=True, carries_website=True,
        reuse_terms=ClosedList.Terms.OWN_COMPILATION, is_denominator=True,
        read_policy=ClosedList.ReadPolicy.FUNDING_READ, verified_on=date(2026, 9, 25),
    )
    fields.update(overrides)
    return ClosedList.objects.create(**fields)


def test_a_list_rung_is_zero_to_four() -> None:
    """0 = an enumerator that is not a ladder rung (Wikidata, ROR); 1-4 = §6.2's rungs."""
    _list(slug="ok", rung=0)
    with pytest.raises(IntegrityError), transaction.atomic():
        _list(slug="bad", rung=5)


def test_a_list_covers_only_holder_kinds() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _list(slug="bad", holder_kinds=["UNIVERSITY"])


def test_an_entry_kind_is_a_holder_kind_or_blank() -> None:
    now = timezone.now()
    RegisterEntry.objects.create(
        register="x", external_key="a", name="A", resolution="UNRESOLVED", last_seen=now,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        RegisterEntry.objects.create(
            register="x", external_key="b", name="B", kind="UNIVERSITY",
            resolution="UNRESOLVED", last_seen=now,
        )


def test_a_partner_row_is_bound_exactly_when_its_disposition_says_so() -> None:
    entry = RegisterEntry.objects.create(
        register="eacea_emjm", external_key="p1", name="EMJM X",
        resolution="UNRESOLVED", last_seen=timezone.now(),
    )
    RegisterEntryPartner.objects.create(
        entry=entry, role="PARTNER", listed_name="NGO", listed_identifier="999",
        disposition=RegisterEntryPartner.Disposition.NO_KEY,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        RegisterEntryPartner.objects.create(
            entry=entry, role="PARTNER", listed_name="Bound?", listed_identifier="998",
            disposition=RegisterEntryPartner.Disposition.BOUND_PIC,
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_closed_lists.py -q 2>&1 | tail -3`
Expected: FAIL with `ImportError: cannot import name 'ClosedList'`.

- [ ] **Step 3: Add the models**

In `apps/research/models.py`, inside `class RegisterEntry`, extend `Resolution`:

```python
        #: Two keys named two different bodies (an EU-PIC held by one
        #: organisation, a website held by another; a Wikidata id already on a
        #: different body). Bound to neither: a person decides (spec 11, the
        #: resolution queue of build item 12), and guessing either way silently
        #: joins or splits a body.
        CONFLICT = "CONFLICT"
```

Then add these fields after `last_seen`:

```python
    #: What the list asserts about the row. `kind` is "" when the list asserts
    #: no kind (Wikidata's class is a claim and does go here; an EACEA project
    #: is not a body and has none).
    country_code = models.CharField(max_length=2, blank=True, default="")
    kind = models.CharField(max_length=24, blank=True, default="")
    #: The scheme page on the body's own site, for a FUNDING_READ list. The
    #: reader reads this; the list itself is never provenance (spec 3.2).
    page_url = models.URLField(max_length=2048, blank=True, default="")
    #: Cell tags (spec 5): ISO 3166-1 alpha-2, an `apps.funding.regions.REGIONS`
    #: key, or ANY. A tag selects a pool and never decides eligibility -- the
    #: reader's conditions do -- so a tag may be wider than the truth, never
    #: narrower. Expanded at read time, never copied, so a region's membership
    #: is one edit.
    home_cells = ArrayField(models.CharField(max_length=24), default=list, blank=True)
    host_cells = ArrayField(models.CharField(max_length=24), default=list, blank=True)
    #: The period the list says this row is live -- an EMJM project's funded
    #: period. Null when the list states none.
    listed_from = models.DateField(null=True, blank=True)
    listed_until = models.DateField(null=True, blank=True)
    #: `read_state.ReadState`, derived and stored by `record_read_states`; ""
    #: until the first coverage run. Never typed by a person.
    read_state = models.CharField(max_length=20, blank=True, default="")
    read_state_detail = models.CharField(max_length=120, blank=True, default="")
    read_state_at = models.DateTimeField(null=True, blank=True)
```

Then add this to its `Meta.constraints`:

```python
            models.CheckConstraint(
                condition=Q(kind="") | Q(kind__in=_HOLDER_VALUES),
                name="register_entry_kind_valid",
            ),
```

Add before `class RegisterEntry`:

```python
class ClosedList(models.Model):
    """One closed list, as a sourced row (spec 6.2's closed-list engine).

    A list is data, never code (spec 3, principle 7 and "country is data"):
    where it is published, who keeps it, what it covers, its reuse terms, and
    when a person last checked it. Loaded from docs/research/closed-lists.csv
    by `manage.py load_closed_lists`, never inserted by a migration. The rows
    it names are `RegisterEntry` rows with `register = slug`. That is a plain
    slug rather than a foreign key because `vgm_tr` rows predate this table,
    and a constraint added over them would need a registry row written in
    code.
    """

    class ReadPolicy(models.TextChoices):
        #: Each entry's `page_url` goes through the funding reader.
        FUNDING_READ = "FUNDING_READ"
        #: The body's homepage goes through the classifier (spec 6.6):
        #: institutions, whose awards are read by the per-HEI pass (6.4a).
        CLASSIFY = "CLASSIFY"
        #: The owner's read gate for professional bodies and banks (spec 6.3,
        #: 2026-09-23): the list is the denominator, never the reading queue.
        SIGNAL_ONLY = "SIGNAL_ONLY"
        #: The list routes other work and nothing here reads it (EACEA's
        #: projects; Wikidata's and ROR's enumerations).
        ENUMERATE_ONLY = "ENUMERATE_ONLY"

    class Terms(models.TextChoices):
        #: CC0, PDDL, Licence Ouverte, KOGL, the Europa reuse notice.
        OPEN = "OPEN"
        #: Published, but nobody has read the terms (VGM, spec 19). Read by
        #: hand into a file, never by an adapter (spec 14).
        UNREAD = "UNREAD"
        #: We compiled the list from each body's own page.
        OWN_COMPILATION = "OWN_COMPILATION"

    slug = models.CharField(max_length=40, primary_key=True)
    title = models.CharField(max_length=200)
    #: "" for a list that belongs to no country -- the intergovernmental list.
    country_code = models.CharField(max_length=2, blank=True, default="")
    holder_kinds = ArrayField(models.CharField(max_length=24), default=list, blank=True)
    #: 1-4 = spec 6.2's register ladder; 0 = an enumerator that is no rung.
    rung = models.PositiveSmallIntegerField()
    source_url = models.URLField(max_length=2048)
    maintainer = models.CharField(max_length=200)
    carries_purpose = models.BooleanField()
    carries_website = models.BooleanField()
    reuse_terms = models.CharField(max_length=16, choices=Terms.choices)
    reuse_terms_url = models.URLField(max_length=2048, blank=True, default="")
    #: Whether `listed` is a completeness claim. False for Wikidata and ROR:
    #: a count from one register is not a denominator for another (spec 6.2).
    is_denominator = models.BooleanField()
    read_policy = models.CharField(max_length=16, choices=ReadPolicy.choices)
    #: The count the publisher prints, when it prints one. "100% enumerated"
    #: means entries == this number, where it exists.
    printed_size = models.PositiveIntegerField(null=True, blank=True)
    verified_on = models.DateField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(rung__lte=4), name="closed_list_rung_range"),
            models.CheckConstraint(
                condition=Q(holder_kinds__contained_by=list(_HOLDER_VALUES)),
                name="closed_list_holder_kinds_valid",
            ),
        ]
```

Add after `class RegisterEntry`. The unbound tuple is module-level on purpose: a nested `Meta` body cannot see its enclosing class's attributes, because class scopes do not nest.

```python
#: The two dispositions that bind no organisation.
_UNBOUND_DISPOSITIONS = ("CONFLICT", "NO_KEY")


class RegisterEntryPartner(models.Model):
    """A body a list names as a partner of one of its rows -- an EMJM
    consortium member (spec 6.2's EACEA row, the 2026-09-14 partner design).

    Stores what the list printed (name, identifier, domain) beside what we
    bound it to, so every one of the 09-14 design's dispositions is a count
    over this table rather than a log line. Shared catalog; an organisation's
    PIC and website are not a person.
    """

    class Disposition(models.TextChoices):
        #: EU-PIC and website both reached the same body we already held.
        BOUND_BOTH = "BOUND_BOTH"
        #: The PIC reached a body; the website was absent or new to us, and is
        #: now attached to that body.
        BOUND_PIC = "BOUND_PIC"
        #: The website reached a body; the PIC is now attached to it.
        BOUND_DOMAIN = "BOUND_DOMAIN"
        #: Neither key was held; a new CANDIDATE was keyed on the website.
        NEW = "NEW"
        #: The PIC reached one body and the website another (EDEX, 09-14 4.3).
        CONFLICT = "CONFLICT"
        #: No website and a PIC no body carries. Silence, counted.
        NO_KEY = "NO_KEY"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    entry = models.ForeignKey(RegisterEntry, on_delete=models.PROTECT, related_name="partners")
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, null=True, blank=True,
        related_name="listed_partnerships",
    )
    #: As the list prints it -- EACEA: COORDINATOR or PARTNER.
    role = models.CharField(max_length=12)
    listed_name = models.CharField(max_length=300)
    #: EACEA: the EU-PIC.
    listed_identifier = models.CharField(max_length=120)
    listed_domain = models.CharField(max_length=253, blank=True, default="")
    country_code = models.CharField(max_length=2, blank=True, default="")
    disposition = models.CharField(max_length=14, choices=Disposition.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("entry", "listed_identifier"), name="register_partner_uniq"
            ),
            models.CheckConstraint(
                condition=(
                    Q(disposition__in=_UNBOUND_DISPOSITIONS, organisation__isnull=True)
                    | (
                        ~Q(disposition__in=_UNBOUND_DISPOSITIONS)
                        & Q(organisation__isnull=False)
                    )
                ),
                name="register_partner_bound_shape",
            ),
        ]
```

- [ ] **Step 4: Generate the migration, then add the RLS by hand**

```bash
POSTGRES_DB=tehsil_enumerators uv run python manage.py makemigrations research --name closed_lists
```

Open the generated file. Add this at the top, below the imports:

```python
# The RLS block is the shape research/0007 uses for RegisterEntry: every tenant
# reads, only catalog_ingestion writes. A shared-catalog table without it is
# readable by nobody under the runtime role, which no test using the default
# role can see (CLAUDE.md, "Row-level security").
_TABLES = ("research_closedlist", "research_registerentrypartner")

RLS_SQL = "".join(
    f"""
ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{table}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{table}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""
    for table in _TABLES
)

REVERSE_RLS_SQL = "".join(
    f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{table};
DROP POLICY IF EXISTS shared_catalog_select ON public.{table};
ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;
"""
    for table in _TABLES
)
```

Then append `migrations.RunSQL(RLS_SQL, reverse_sql=REVERSE_RLS_SQL),` as the last operation. Its dependencies must name **only** `research` migrations. A research→funding edge raises `InvalidMigrationPlan` (`tests/migrations/test_task7_migrations.py` reproduces it), and `_HOLDER_VALUES` is imported into the model and not needed by the migration. If the generated file imports `apps.funding` for the check constraints, inline the tuple values instead, as `research/0003` does.

Run: `POSTGRES_DB=tehsil_enumerators uv run python manage.py makemigrations --check --dry-run 2>&1 | tail -2`
Expected: `No changes detected`.

- [ ] **Step 5: Add both tables to the shared-catalog list**

In `tests/tenancy/test_database_isolation.py`, `_SHARED_TABLES`, after `"research_sitejobrecord",`:

```python
    # The closed-list registry and EMJM partner bindings (research/<next>).
    # A list's URL and terms, an organisation's PIC and website -- never a
    # person.
    "research_closedlist",
    "research_registerentrypartner",
```

That puts both tables under `test_task7_rls_policy_shapes_and_runtime_acl`, which checks the exact policy set through `runtime_connection`.

- [ ] **Step 6: Write the RLS behaviour tests**

```python
# tests/research/test_closed_list_rls.py
"""RLS on ClosedList and RegisterEntryPartner, through a role that cannot bypass it.

CLAUDE.md: the test role bypasses RLS, so everything here goes through
`runtime_connection`. The write test grants INSERT first, so the refusal is
the POLICY's -- an ungranted role raises the identical InsufficientPrivilege
(tests/research/test_site_job_record_rls.py carries the same control).
"""

from datetime import date

import psycopg
import pytest
from django.db import connection
from django.utils import timezone
from psycopg import sql

from apps.research.models import ClosedList, RegisterEntry, RegisterEntryPartner

pytestmark = pytest.mark.django_db


def _rows() -> None:
    ClosedList.objects.create(
        slug="igo_regional_global", title="IGO", holder_kinds=["INTERGOVERNMENTAL"], rung=1,
        source_url="https://example.org/list", maintainer="own", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="FUNDING_READ", verified_on=date(2026, 9, 25),
    )
    entry = RegisterEntry.objects.create(
        register="eacea_emjm", external_key="p1", name="EMJM", resolution="UNRESOLVED",
        last_seen=timezone.now(),
    )
    RegisterEntryPartner.objects.create(
        entry=entry, role="PARTNER", listed_name="NGO", listed_identifier="1",
        disposition="NO_KEY",
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("table", ["research_closedlist", "research_registerentrypartner"])
def test_every_tenant_reads_the_rows(runtime_connection, table: str) -> None:
    _rows()
    with runtime_connection.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
        assert cursor.fetchone()[0] == 1


@pytest.mark.django_db(transaction=True)
def test_the_runtime_role_cannot_write_a_list(runtime_connection) -> None:
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT INSERT ON TABLE {} TO {}").format(
                sql.Identifier("public", "research_closedlist"), role
            )
        )
    with runtime_connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(
                "INSERT INTO research_closedlist (slug, title, country_code, holder_kinds, "
                "rung, source_url, maintainer, carries_purpose, carries_website, "
                "reuse_terms, reuse_terms_url, is_denominator, read_policy, verified_on) "
                "VALUES ('x', 'x', '', '{}', 1, 'https://x.example/', 'x', true, true, "
                "'OPEN', '', true, 'CLASSIFY', '2026-09-25')"
            )
        assert "row-level security policy" in str(refused.value)


@pytest.mark.django_db(transaction=True)
def test_the_runtime_role_cannot_write_a_partner(runtime_connection) -> None:
    _rows()
    entry_id = RegisterEntry.objects.get(external_key="p1").id
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT INSERT ON TABLE {} TO {}").format(
                sql.Identifier("public", "research_registerentrypartner"), role
            )
        )
    with runtime_connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(
                "INSERT INTO research_registerentrypartner (id, entry_id, role, listed_name, "
                "listed_identifier, listed_domain, country_code, disposition) "
                "VALUES (gen_random_uuid(), %s, 'PARTNER', 'x', '2', '', '', 'NO_KEY')",
                [entry_id],
            )
        assert "row-level security policy" in str(refused.value)
```

- [ ] **Step 7: Run everything touched**

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_closed_lists.py tests/research/test_closed_list_rls.py tests/tenancy/test_database_isolation.py tests/research/test_vgm.py tests/migrations -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"`
Expected: all pass, `EXIT=0`.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check apps config tests && uv run mypy apps config | tail -1
git add apps/research/models.py apps/research/migrations/ tests/research/test_closed_lists.py tests/research/test_closed_list_rls.py tests/tenancy/test_database_isolation.py
git commit -m "feat(research): ClosedList, cell-tagged register entries, EMJM partner rows -- shared catalog, RLS in the migration"
```

---

### Task 2: The closed-list engine — files, `record_list`, `ClosedListSource`

**Files:**
- Create: `apps/research/closed_lists.py`
- Modify: `tests/research/test_closed_lists.py` (append)

**Interfaces:**
- Consumes: `record_organisation`, `registrable_domain`, `canonicalize_url`, `ResearchLead.from_url`, `REGIONS`, `_HOLDER_VALUES`, `_FAMILY_BY_HOLDER`.
- Produces: `DATA_DIR`, `REGISTRY`, `LISTS_DIR`; `ListFileError`; `valid_cell(token) -> bool`; `read_registry(path=REGISTRY) -> tuple[dict[str, object], ...]`; `load_registry(path=REGISTRY) -> int`; `ListRow`; `read_list_file(spec: ClosedList, path: Path | None = None) -> tuple[ListRow, ...]`; `ListReport`; `record_list(spec, rows, *, now) -> ListReport`; `has_signal(org) -> bool`; `ClosedListSource(slug)`.

- [ ] **Step 1: Write the failing tests.** Append them to `tests/research/test_closed_lists.py`. Add `from pathlib import Path` and `Organisation` (to the existing `apps.research.models` import) to the file's import block at the top, not mid-file, or ruff reports E402.

```python
_REGISTRY_HEADER = (
    "slug,title,country_code,holder_kinds,rung,source_url,maintainer,carries_purpose,"
    "carries_website,reuse_terms,reuse_terms_url,is_denominator,read_policy,printed_size,"
    "verified_on\n"
)
_LIST_HEADER = (
    "external_key,name,kind,website,page_url,country_code,home_cells,host_cells,"
    "rejected_reason,source_url,verified_on,notes\n"
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_the_registry_loads_one_row_per_list(tmp_path: Path) -> None:
    from apps.research.closed_lists import load_registry

    path = _write(tmp_path, "closed-lists.csv", _REGISTRY_HEADER + (
        "igo_regional_global,IGO,,INTERGOVERNMENTAL|REGIONAL_FUND,1,"
        "https://example.org/list,own,yes,yes,OWN_COMPILATION,,yes,FUNDING_READ,,2026-09-25\n"
    ))
    assert load_registry(path) == 1
    spec = ClosedList.objects.get(slug="igo_regional_global")
    assert spec.holder_kinds == ["INTERGOVERNMENTAL", "REGIONAL_FUND"]
    assert spec.printed_size is None and spec.is_denominator


def test_the_registry_refuses_a_wrong_header(tmp_path: Path) -> None:
    from apps.research.closed_lists import ListFileError, read_registry

    path = _write(tmp_path, "closed-lists.csv", "slug,title\nx,y\n")
    with pytest.raises(ListFileError, match="columns"):
        read_registry(path)


@pytest.mark.parametrize(
    ("token", "valid"),
    [("ANY", True), ("TR", True), ("EU", True), ("AFRICAN_UNION", True),
     ("tr", False), ("TUR", False), ("Europe", False), ("", False)],
)
def test_a_cell_tag_is_iso2_a_region_or_any(token: str, valid: bool) -> None:
    from apps.research.closed_lists import valid_cell

    assert valid_cell(token) is valid


def _spec(**overrides: object) -> ClosedList:
    return _list(**overrides)


def test_a_list_file_refuses_an_email_address(tmp_path: Path) -> None:
    """A mailbox is not what this file is for, and a committed file is storage."""
    from apps.research.closed_lists import ListFileError, read_list_file

    spec = _spec()
    path = _write(tmp_path, "igo.csv", _LIST_HEADER + (
        "wb,World Bank JJ/WBGSP,INTERGOVERNMENTAL,https://www.worldbank.org,"
        "https://www.worldbank.org/en/programs/scholarships,,ANY,ANY,,"
        "https://www.worldbank.org/en/programs/scholarships,2026-09-25,write to x@worldbank.org\n"
    ))
    with pytest.raises(ListFileError, match="e-mail"):
        read_list_file(spec, path)


def test_a_scheme_page_must_sit_on_the_bodys_own_site(tmp_path: Path) -> None:
    """The origin is the only evidence (spec 3.2): a page on someone else's
    host would be read as that someone's money."""
    from apps.research.closed_lists import ListFileError, read_list_file

    spec = _spec()
    path = _write(tmp_path, "igo.csv", _LIST_HEADER + (
        "adb,ADB-Japan Scholarship,INTERGOVERNMENTAL,https://www.adb.org,"
        "https://www.someuniversity.edu/adb-jsp,,ANY,ANY,,https://www.adb.org,2026-09-25,\n"
    ))
    with pytest.raises(ListFileError, match="own site"):
        read_list_file(spec, path)


def test_a_funding_read_list_row_needs_a_page(tmp_path: Path) -> None:
    from apps.research.closed_lists import ListFileError, read_list_file

    spec = _spec()
    path = _write(tmp_path, "igo.csv", _LIST_HEADER + (
        "wb,World Bank,INTERGOVERNMENTAL,https://www.worldbank.org,,,ANY,ANY,,"
        "https://www.worldbank.org,2026-09-25,\n"
    ))
    with pytest.raises(ListFileError, match="page_url"):
        read_list_file(spec, path)


def test_a_row_kind_must_be_one_the_list_covers(tmp_path: Path) -> None:
    from apps.research.closed_lists import ListFileError, read_list_file

    spec = _spec()
    path = _write(tmp_path, "igo.csv", _LIST_HEADER + (
        "x,X Bank,BANK_OR_LENDER,https://x.example.org,https://x.example.org/s,,ANY,ANY,,"
        "https://x.example.org,2026-09-25,\n"
    ))
    with pytest.raises(ListFileError, match="covers"):
        read_list_file(spec, path)


def _rows(tmp_path: Path, spec: ClosedList, body: str):
    from apps.research.closed_lists import read_list_file

    return read_list_file(spec, _write(tmp_path, f"{spec.slug}.csv", _LIST_HEADER + body))


def test_a_curated_list_registers_what_it_names(tmp_path: Path) -> None:
    from apps.research.closed_lists import record_list

    spec = _spec()
    rows = _rows(tmp_path, spec, (
        "wb-jjwbgsp,Joint Japan/World Bank Graduate Scholarship Program,INTERGOVERNMENTAL,"
        "https://www.worldbank.org,https://www.worldbank.org/en/programs/scholarships,,"
        "ANY,ANY,,https://www.worldbank.org/en/programs/scholarships,2026-09-25,\n"
    ))
    report = record_list(spec, rows, now=timezone.now())
    assert (report.listed, report.bound, report.organisations_new) == (1, 1, 1)
    entry = RegisterEntry.objects.get(register=spec.slug)
    org = entry.organisation
    assert org is not None and org.primary_domain == "worldbank.org"
    assert org.status == Organisation.Status.REGISTERED
    assert org.found_via == ["R1_LIST:igo_regional_global"]
    assert entry.home_cells == ["ANY"] and entry.kind == "INTERGOVERNMENTAL"


def test_a_curated_list_promotes_a_candidate_another_route_found(tmp_path: Path) -> None:
    """record_organisation never overwrites status -- rightly, for routes that
    vouch for nothing. A curated list vouches, so it upgrades, and only upward."""
    from apps.research.closed_lists import record_list
    from apps.research.register import record_organisation

    record_organisation(
        domain="isdb.org", name="isdb.org", kind="UNSTATED", country_code="",
        found_via="R4_SEARCH:exa",
    )
    spec = _spec()
    rows = _rows(tmp_path, spec, (
        "isdb-scholarship,IsDB Scholarship Programme,INTERGOVERNMENTAL,https://www.isdb.org,"
        "https://www.isdb.org/scholarships,SA,ANY,ANY,,https://www.isdb.org/scholarships,"
        "2026-09-25,\n"
    ))
    report = record_list(spec, rows, now=timezone.now())
    org = Organisation.objects.get(primary_domain="isdb.org")
    assert report.promoted == 1
    assert (org.status, org.kind, org.country_code) == ("REGISTERED", "INTERGOVERNMENTAL", "SA")
    assert org.found_via == ["R4_SEARCH:exa", "R1_LIST:igo_regional_global"]


def test_a_named_body_that_funds_no_masters_student_is_recorded_rejected(tmp_path: Path) -> None:
    """A body the owner named whose own page shows no master's award is kept,
    REJECTED with a reason and its page as source -- never silently dropped."""
    from apps.research.closed_lists import record_list

    spec = _spec()
    rows = _rows(tmp_path, spec, (
        "eea-grants,EEA Grants,REGIONAL_FUND,https://eeagrants.org,,,ANY,ANY,NOT_A_FUNDER,"
        "https://eeagrants.org/topics-programmes,2026-09-25,funds national programmes only\n"
    ))
    record_list(spec, rows, now=timezone.now())
    org = RegisterEntry.objects.get(external_key="eea-grants").organisation
    assert org is not None and org.status == "REJECTED" and org.rejected_reason == "NOT_A_FUNDER"


def test_reloading_a_list_is_idempotent(tmp_path: Path) -> None:
    from apps.research.closed_lists import record_list

    spec = _spec()
    body = (
        "wb-jjwbgsp,JJ/WBGSP,INTERGOVERNMENTAL,https://www.worldbank.org,"
        "https://www.worldbank.org/en/programs/scholarships,,ANY,ANY,,"
        "https://www.worldbank.org/en/programs/scholarships,2026-09-25,\n"
    )
    record_list(spec, _rows(tmp_path, spec, body), now=timezone.now())
    second = record_list(spec, _rows(tmp_path, spec, body), now=timezone.now())
    assert (second.organisations_new, RegisterEntry.objects.count()) == (0, 1)
    assert Organisation.objects.get().found_via == ["R1_LIST:igo_regional_global"]


def test_the_source_yields_funder_leads_for_scheme_pages_only(tmp_path: Path) -> None:
    from apps.research.closed_lists import ClosedListSource, record_list
    from apps.research.discovery import DiscoveryQuery

    spec = _spec()
    rows = _rows(tmp_path, spec, (
        "wb,JJ/WBGSP,INTERGOVERNMENTAL,https://www.worldbank.org,"
        "https://www.worldbank.org/en/programs/scholarships,,ANY,ANY,,"
        "https://www.worldbank.org,2026-09-25,\n"
        "eea,EEA Grants,REGIONAL_FUND,https://eeagrants.org,,,ANY,ANY,NOT_A_FUNDER,"
        "https://eeagrants.org,2026-09-25,\n"
    ))
    record_list(spec, rows, now=timezone.now())
    leads = list(ClosedListSource(spec.slug).find(DiscoveryQuery(field="x", country_code="AZ")))
    assert [lead.canonical_url for lead in leads] == [
        "https://www.worldbank.org/en/programs/scholarships"
    ]
    assert leads[0].source_type == "FUNDER" and leads[0].funding_family == "MULTILATERAL"


def test_a_signal_only_list_yields_nothing_without_a_signal(tmp_path: Path) -> None:
    """Owner, 2026-09-23: a licensed-lender list is the denominator, never the
    reading queue. Nothing tags an Organisation with POINTER: today, so every
    bank reads GATED -- which is the rule, not a gap."""
    from apps.research.closed_lists import ClosedListSource, record_list
    from apps.research.discovery import DiscoveryQuery

    spec = _spec(
        slug="tr_banks", country_code="TR", holder_kinds=["BANK_OR_LENDER"], rung=2,
        read_policy=ClosedList.ReadPolicy.SIGNAL_ONLY,
    )
    rows = _rows(tmp_path, spec, (
        "b1,Örnek Bankası,BANK_OR_LENDER,https://www.ornekbank.com.tr,"
        "https://www.ornekbank.com.tr/burs,TR,TR,ANY,,https://www.bddk.org.tr,2026-09-25,\n"
    ))
    record_list(spec, rows, now=timezone.now())
    source = ClosedListSource(spec.slug)
    assert list(source.find(DiscoveryQuery(field="x", country_code="TR"))) == []
    org = Organisation.objects.get(primary_domain="ornekbank.com.tr")
    org.found_via = [*org.found_via, "POINTER:tev.org.tr"]
    org.save(update_fields=["found_via"])
    assert len(list(source.find(DiscoveryQuery(field="x", country_code="TR")))) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_closed_lists.py -q 2>&1 | tail -3`
Expected: the new tests FAIL with `ModuleNotFoundError: No module named 'apps.research.closed_lists'`.

- [ ] **Step 3: Implement `apps/research/closed_lists.py`**

```python
"""Closed lists as data (spec 6.2's closed-list engine).

A closed list is a finite set of bodies that a publisher -- a regulator, a
ministry, or we ourselves compiling from each body's own page -- names in
full. Its size is the denominator the coverage line divides by, so the list
lives in files a person reviews as a diff, never in code:

- ``docs/research/closed-lists.csv`` -- one sourced row per list;
- ``docs/research/closed-lists/<slug>.csv`` -- the rows of a list read by
  hand: a register with no API or with terms nobody has read (spec 14), or a
  list we compiled because nobody publishes one (the intergovernmental
  bodies, spec 19). Azerbaijan's institutions come from the ministry's list;
  TKTA publishes two NEGATIVE lists as JSON (not recognised; high refusal)
  and still no list of recognised institutions (provenance gate spec §9.6).
  An adapter-read list (VGM, EACEA,
  Wikidata, ROR) has a registry row and no rows file.

A curated list promotes what it names to REGISTERED -- spec 6.1: "a national
register, DEQAR or a curated national file vouched for the domain" -- and
`record_list` is the only code that does, which is why no Wikidata, ROR or
EACEA row passes through it.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
sections 6.1, 6.2, 16 item 7.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from django.db import transaction

from apps.funding.models import _HOLDER_VALUES
from apps.funding.regions import REGIONS

from .discovery import DiscoveryQuery, ResearchLead, canonicalize_url
from .funding_reader import _FAMILY_BY_HOLDER
from .hosts import registrable_domain
from .models import ClosedList, Organisation, OrganisationDomain, RegisterEntry
from .register import record_organisation

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "docs" / "research"
REGISTRY = DATA_DIR / "closed-lists.csv"
LISTS_DIR = DATA_DIR / "closed-lists"

_REGISTRY_COLUMNS = (
    "slug", "title", "country_code", "holder_kinds", "rung", "source_url", "maintainer",
    "carries_purpose", "carries_website", "reuse_terms", "reuse_terms_url",
    "is_denominator", "read_policy", "printed_size", "verified_on",
)
_LIST_COLUMNS = (
    "external_key", "name", "kind", "website", "page_url", "country_code",
    "home_cells", "host_cells", "rejected_reason", "source_url", "verified_on", "notes",
)
_YES_NO = {"yes": True, "no": False}


class ListFileError(ValueError):
    """A list file that does not say what the loader needs, named by line."""


def valid_cell(token: str) -> bool:
    """ANY, a `REGIONS` key, or an ISO 3166-1 alpha-2 code (upper case)."""
    return (
        token == "ANY"
        or token in REGIONS
        or (len(token) == 2 and token.isascii() and token.isalpha() and token.isupper())
    )


def _cells(raw: str, where: str) -> list[str]:
    tokens = [token.strip() for token in raw.split("|") if token.strip()]
    if not tokens:
        raise ListFileError(f"{where}: no cell tags (write ANY for any country)")
    unknown = [token for token in tokens if not valid_cell(token)]
    if unknown:
        raise ListFileError(f"{where}: unknown cell tags {unknown}")
    if "ANY" in tokens and len(tokens) > 1:
        raise ListFileError(f"{where}: ANY beside other tags means ANY; write ANY alone")
    return tokens


def _url(raw: str, where: str, *, required: bool) -> str:
    raw = raw.strip()
    if not raw:
        if required:
            raise ListFileError(f"{where}: required")
        return ""
    try:
        return canonicalize_url(raw)
    except ValueError as error:
        raise ListFileError(f"{where}: {error}: {raw!r}") from error


def _day(raw: str, where: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as error:
        raise ListFileError(f"{where}: not an ISO date: {raw!r}") from error


def _flag(raw: str, where: str) -> bool:
    try:
        return _YES_NO[raw.strip().lower()]
    except KeyError as error:
        raise ListFileError(f"{where}: yes or no, not {raw!r}") from error


def _rows_of(path: Path, columns: tuple[str, ...]) -> Iterator[tuple[str, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise ListFileError(f"{path.name}: columns {reader.fieldnames} are not {columns}")
        for line, row in enumerate(reader, start=2):
            yield f"{path.name}:{line}", {key: (value or "") for key, value in row.items()}


def read_registry(path: Path = REGISTRY) -> tuple[dict[str, object], ...]:
    """Every registry row as `ClosedList` field values, validated."""
    specs: list[dict[str, object]] = []
    seen: set[str] = set()
    for where, row in _rows_of(path, _REGISTRY_COLUMNS):
        slug = row["slug"].strip()
        if not slug or slug in seen or len(slug) > 40:
            raise ListFileError(f"{where}: slug missing, repeated or over 40 characters: {slug!r}")
        seen.add(slug)
        kinds = [kind for kind in row["holder_kinds"].split("|") if kind]
        if any(kind not in _HOLDER_VALUES for kind in kinds):
            raise ListFileError(f"{where}: holder_kinds {kinds} outside the holder vocabulary")
        rung = int(row["rung"])
        if not 0 <= rung <= 4:
            raise ListFileError(f"{where}: rung {rung} is not 0-4")
        if row["reuse_terms"] not in ClosedList.Terms.values:
            raise ListFileError(f"{where}: reuse_terms {row['reuse_terms']!r}")
        if row["read_policy"] not in ClosedList.ReadPolicy.values:
            raise ListFileError(f"{where}: read_policy {row['read_policy']!r}")
        country = row["country_code"].strip().upper()
        if country and (country == "ANY" or country in REGIONS or not valid_cell(country)):
            raise ListFileError(f"{where}: country_code {country!r} is not ISO alpha-2")
        specs.append({
            "slug": slug,
            "title": row["title"].strip(),
            "country_code": country,
            "holder_kinds": kinds,
            "rung": rung,
            "source_url": _url(row["source_url"], f"{where} source_url", required=True),
            "maintainer": row["maintainer"].strip(),
            "carries_purpose": _flag(row["carries_purpose"], f"{where} carries_purpose"),
            "carries_website": _flag(row["carries_website"], f"{where} carries_website"),
            "reuse_terms": row["reuse_terms"],
            "reuse_terms_url": _url(row["reuse_terms_url"], f"{where} reuse_terms_url",
                                    required=False),
            "is_denominator": _flag(row["is_denominator"], f"{where} is_denominator"),
            "read_policy": row["read_policy"],
            "printed_size": int(row["printed_size"]) if row["printed_size"].strip() else None,
            "verified_on": _day(row["verified_on"], f"{where} verified_on"),
        })
    return tuple(specs)


def load_registry(path: Path = REGISTRY) -> int:
    """Write every registry row. A row an adapter maintains keeps the
    `printed_size` its adapter measured (EACEA sets it from the API's own
    totals); a blank in the file never erases a measured count."""
    specs = read_registry(path)
    for spec in specs:
        slug = str(spec.pop("slug"))
        if spec["printed_size"] is None:
            spec.pop("printed_size")
        ClosedList.objects.update_or_create(slug=slug, defaults=spec)
    return len(specs)


@dataclass(frozen=True)
class ListRow:
    external_key: str
    name: str
    kind: str
    website: str
    page_url: str
    country_code: str
    home_cells: tuple[str, ...]
    host_cells: tuple[str, ...]
    rejected_reason: str
    source_url: str
    verified_on: date


def read_list_file(spec: ClosedList, path: Path | None = None) -> tuple[ListRow, ...]:
    """Every row of one hand-read list, validated against its registry row."""
    path = path or LISTS_DIR / f"{spec.slug}.csv"
    rows: list[ListRow] = []
    keys: set[str] = set()
    for where, raw in _rows_of(path, _LIST_COLUMNS):
        if any("@" in value for value in raw.values()):
            # A mailbox is a person's or an office's, and a committed file is
            # storage (the 6a plan's rule). Rung 0 reads e-mails from registers
            # at run time and keeps only the domain; a file keeps the website.
            raise ListFileError(f"{where}: an e-mail address; store the website instead")
        key = raw["external_key"].strip()
        if not key or key in keys or len(key) > 120:
            raise ListFileError(f"{where}: external_key missing, repeated or too long: {key!r}")
        keys.add(key)
        name = raw["name"].strip()
        if not name:
            raise ListFileError(f"{where}: name missing")
        kind = raw["kind"].strip()
        if kind not in _HOLDER_VALUES:
            raise ListFileError(f"{where}: kind {kind!r} outside the holder vocabulary")
        if spec.holder_kinds and kind not in spec.holder_kinds:
            raise ListFileError(f"{where}: kind {kind} is not one {spec.slug} covers")
        rejected = raw["rejected_reason"].strip()
        if rejected and rejected not in Organisation.RejectedReason.values:
            raise ListFileError(f"{where}: rejected_reason {rejected!r}")
        website = _url(raw["website"], f"{where} website", required=not rejected)
        page_url = _url(
            raw["page_url"], f"{where} page_url",
            required=spec.read_policy == ClosedList.ReadPolicy.FUNDING_READ and not rejected,
        )
        if page_url and website and registrable_domain(page_url) != registrable_domain(website):
            # The origin is the only evidence (spec 3.2): a scheme page on
            # another host is that host's page, and reading it for this body
            # would write the wrong holder.
            raise ListFileError(f"{where}: page_url is not on the body's own site ({website})")
        country = raw["country_code"].strip().upper()
        if country and (country == "ANY" or country in REGIONS or not valid_cell(country)):
            raise ListFileError(f"{where}: country_code {country!r} is not ISO alpha-2")
        rows.append(ListRow(
            external_key=key, name=name, kind=kind, website=website, page_url=page_url,
            country_code=country,
            home_cells=tuple(_cells(raw["home_cells"], f"{where} home_cells")),
            host_cells=tuple(_cells(raw["host_cells"], f"{where} host_cells")),
            rejected_reason=rejected,
            source_url=_url(raw["source_url"], f"{where} source_url", required=True),
            verified_on=_day(raw["verified_on"], f"{where} verified_on"),
        ))
    return tuple(rows)


@dataclass(frozen=True)
class ListReport:
    listed: int = 0
    bound: int = 0
    unresolved: int = 0
    organisations_new: int = 0
    promoted: int = 0
    rejected: int = 0


def record_list(spec: ClosedList, rows: Iterable[ListRow], *, now: datetime) -> ListReport:
    """Write a hand-read list's rows and bind each to its body by website."""
    listed = bound = unresolved = new = promoted = rejected = 0
    tag = f"R{spec.rung}_LIST:{spec.slug}"
    vouched = (
        Organisation.Status.REGISTERED if spec.is_denominator
        else Organisation.Status.CANDIDATE
    )
    for row in rows:
        listed += 1
        domain = registrable_domain(row.website) if row.website else ""
        with transaction.atomic():
            entry, _ = RegisterEntry.objects.update_or_create(
                register=spec.slug,
                external_key=row.external_key,
                defaults={
                    "name": row.name, "kind": row.kind, "country_code": row.country_code,
                    "page_url": row.page_url, "home_cells": list(row.home_cells),
                    "host_cells": list(row.host_cells),
                    "resolution": (
                        RegisterEntry.Resolution.RESOLVED if domain
                        else RegisterEntry.Resolution.UNRESOLVED
                    ),
                    "last_seen": now,
                },
            )
            if not domain:
                unresolved += 1
                continue
            existed = OrganisationDomain.objects.filter(registrable_domain=domain).exists()
            org = record_organisation(
                domain=domain, name=row.name, names=(row.name,), kind=row.kind,
                country_code=row.country_code, found_via=tag,
                status=Organisation.Status.REJECTED if row.rejected_reason else vouched,
                rejected_reason=row.rejected_reason,
            )
            if _promote(org, row, vouches=spec.is_denominator):
                promoted += 1
            if entry.organisation_id != org.pk:
                entry.organisation = org
                entry.save(update_fields=["organisation"])
        bound += 1
        new += not existed
        rejected += org.status == Organisation.Status.REJECTED
    return ListReport(listed, bound, unresolved, new, promoted, rejected)


def _promote(org: Organisation, row: ListRow, *, vouches: bool) -> bool:
    """A body another route found first, now named by a list that vouches.

    Only upward: CANDIDATE -> REGISTERED, UNSTATED -> the list's kind, a blank
    country -> the list's. A REJECTED body stays rejected and is logged -- a
    list naming it does not undo whatever found it dead or infrastructure.
    Returns whether the status moved.
    """
    if not vouches or row.rejected_reason:
        return False
    if org.status == Organisation.Status.REJECTED:
        logger.warning(
            "closed list names %s, which is REJECTED (%s); left as it is",
            org.primary_domain, org.rejected_reason,
        )
        return False
    changed: list[str] = []
    if org.status == Organisation.Status.CANDIDATE:
        org.status = Organisation.Status.REGISTERED
        changed.append("status")
    if org.kind == "UNSTATED" and row.kind != "UNSTATED":
        org.kind = row.kind
        changed.append("kind")
    if not org.country_code and row.country_code:
        org.country_code = row.country_code
        changed.append("country_code")
    if changed:
        org.save(update_fields=changed)
    return "status" in changed


def has_signal(org: Organisation) -> bool:
    """The cheap positive signal a SIGNAL_ONLY body needs before it is read
    (spec 6.3): another funder's page named it. The domain-restricted Exa call
    is the other signal and belongs to spec 6.4a, not to this module."""
    return any(tag.startswith("POINTER:") for tag in org.found_via)


@dataclass(frozen=True)
class ClosedListSource:
    """A list's scheme pages as FUNDER leads -- a `LeadSource`.

    Ignores `query.country_code` on purpose: a list is already scoped by its
    registry row, the intergovernmental list belongs to no country (spec 19),
    and filtering it by the run's country is the corridor-sizing that list
    exists to avoid.
    """

    slug: str
    one_programme_per_link: bool = False
    awards_jointly: bool = False

    @property
    def name(self) -> str:
        return f"closed-list:{self.slug}"

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        policy = ClosedList.objects.values_list("read_policy", flat=True).get(slug=self.slug)
        if policy not in (ClosedList.ReadPolicy.FUNDING_READ, ClosedList.ReadPolicy.SIGNAL_ONLY):
            return
        entries = (
            RegisterEntry.objects.filter(register=self.slug, organisation__isnull=False)
            .exclude(page_url="")
            .exclude(organisation__status=Organisation.Status.REJECTED)
            .select_related("organisation")
            .order_by("external_key")
        )
        for entry in entries:
            assert entry.organisation is not None  # filtered above; for mypy
            if policy == ClosedList.ReadPolicy.SIGNAL_ONLY and not has_signal(entry.organisation):
                continue
            yield ResearchLead.from_url(
                entry.page_url,
                source_type="FUNDER",
                funding_family=_FAMILY_BY_HOLDER.get(entry.kind or entry.organisation.kind, ""),
                discovered_by=self.name,
            )
```

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_closed_lists.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"`
Expected: all pass, `EXIT=0`.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check apps tests && uv run mypy apps config | tail -1
git add apps/research/closed_lists.py tests/research/test_closed_lists.py
git commit -m "feat(research): closed lists as data -- registry, rows, the one route that promotes to REGISTERED"
```

---

### Task 3: Read states and the gate

**Files:**
- Create: `apps/research/read_state.py`, `tests/research/test_read_state.py`
- Modify: `config/settings/base.py`

**Interfaces:**
- Consumes: `ClosedList`, `RegisterEntry`, `Organisation`, `FetchAttempt`, `OfficialSource`, `OfficialSourceSnapshot`, `Outcome`, `has_signal`.
- Produces: `ReadState` (StrEnum); `EntryState(state, detail)`; `entry_read_state(entry, policy) -> EntryState`; `record_read_states(slug, *, now) -> Counter[str]`; `ListGate(slug, listed, printed_size, bodies_known, states, stale)` with `.enumerated` and `.passed`; `list_gate(slug, *, now) -> ListGate`; `settings.CLOSED_LIST_RECHECK_DAYS`.

- [ ] **Step 1: Add the setting**

In `config/settings/base.py`, next to `ORG_CLASSIFY_RUN_LIMIT`:

```python
# A hand-read closed list past this many days since `verified_on` prints STALE
# on the coverage line (spec 6.2: "a list past its verified-on date raises
# re-check priority"). One admissions season; it flags, it never fails the gate.
CLOSED_LIST_RECHECK_DAYS = int(os.getenv("CLOSED_LIST_RECHECK_DAYS", "90"))
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/research/test_read_state.py
"""Read states: what reading each listed body came to, derived, never typed.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
sections 6.1 (read state), 15, 16 item 7 (the gate).
"""

import hashlib
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.funding.models import OfficialSource, OfficialSourceSnapshot
from apps.research.models import ClosedList, FetchAttempt, Organisation, RegisterEntry
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db
NOW = timezone.now()


def _list(slug: str = "l", policy: str = "FUNDING_READ", **extra: object) -> ClosedList:
    fields: dict[str, object] = dict(
        slug=slug, title=slug, holder_kinds=[], rung=1, source_url="https://example.org/l",
        maintainer="m", carries_purpose=True, carries_website=True, reuse_terms="OPEN",
        is_denominator=True, read_policy=policy, verified_on=date.today(),
    )
    fields.update(extra)
    return ClosedList.objects.create(**fields)


def _entry(slug: str = "l", key: str = "a", domain: str | None = "body.example.org",
           page: str = "https://www.body.example.org/scholarship") -> RegisterEntry:
    org = None
    if domain:
        org = record_organisation(domain=domain, name=key, kind="INTERGOVERNMENTAL",
                                  country_code="", found_via="R1_LIST:l")
    return RegisterEntry.objects.create(
        register=slug, external_key=key, name=key, page_url=page, organisation=org,
        resolution="RESOLVED" if org else "UNRESOLVED", last_seen=NOW,
    )


def _snapshot(url: str, **extra: object) -> OfficialSourceSnapshot:
    source, _ = OfficialSource.objects.get_or_create(
        canonical_url=url, defaults={"publisher": url.split("/")[2], "source_type": "FUNDER"},
    )
    fields: dict[str, object] = dict(
        source=source, s3_key="k", s3_version_id="v",
        sha256=hashlib.sha256(f"{url}{sorted(extra.items())}".encode()).hexdigest(),
        final_url=url, retrieved_at=NOW, admissions_cycle="2027", content_type="text/html",
        byte_size=1,
    )
    fields.update(extra)
    return OfficialSourceSnapshot.objects.create(**fields)


def _attempt(url: str, outcome: str) -> None:
    FetchAttempt.objects.create(url=url, host=url.split("/")[2], rung=1, vendor="FIRECRAWL",
                                outcome=outcome)


def test_an_unbound_entry_is_unbound_and_fails_the_gate() -> None:
    from apps.research.read_state import ReadState, entry_read_state, list_gate

    _list()
    entry = _entry(domain=None)
    assert entry_read_state(entry, "FUNDING_READ").state == ReadState.UNBOUND
    assert not list_gate("l", now=NOW).passed


def test_a_funding_read_snapshot_on_any_of_the_bodys_hosts_is_a_read() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    # A hop inside the body's own site counts: the reader followed a funding
    # link from the scheme page (pipeline.funding_links).
    _snapshot("https://apply.body.example.org/call-2027", funding_read_at=NOW)
    found = entry_read_state(entry, "FUNDING_READ")
    assert (found.state, found.detail) == (ReadState.FUNDING_READ, "1 pages")


def test_a_page_fetched_but_never_funding_read_is_unread() -> None:
    """A run without --funding catalogues the page and reads no money from it."""
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    _snapshot("https://www.body.example.org/scholarship")
    assert entry_read_state(entry, "FUNDING_READ").state == ReadState.UNREAD


def test_a_shell_is_unreadable_never_no_funding() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    _snapshot("https://www.body.example.org/scholarship", readability="SHELL")
    found = entry_read_state(entry, "FUNDING_READ")
    assert (found.state, found.detail) == (ReadState.UNREADABLE, "SHELL")


def test_a_refused_fetch_is_could_not_look_with_the_outcome() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    _attempt(entry.page_url, "BLOCKED")
    found = entry_read_state(entry, "FUNDING_READ")
    assert (found.state, found.detail) == (ReadState.COULD_NOT_LOOK, "BLOCKED")


def test_our_budget_running_out_is_unread_not_the_host_refusing() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    _attempt(entry.page_url, "BUDGET")
    assert entry_read_state(entry, "FUNDING_READ").state == ReadState.UNREAD


def test_classify_policy_reads_the_classifier_columns() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list(policy="CLASSIFY")
    entry = _entry(page="")
    org = entry.organisation
    assert org is not None
    assert entry_read_state(entry, "CLASSIFY").state == ReadState.UNREAD
    org.classifier_confidence = 0.55
    org.save(update_fields=["classifier_confidence"])
    assert entry_read_state(entry, "CLASSIFY").state == ReadState.ABSTAINED
    org.classified_at, org.classified_by = NOW, "FRONTIER"
    org.save(update_fields=["classified_at", "classified_by"])
    found = entry_read_state(entry, "CLASSIFY")
    assert (found.state, found.detail) == (ReadState.CLASSIFIED, "FRONTIER")


def test_a_signal_only_body_without_a_signal_is_gated_and_passes() -> None:
    from apps.research.read_state import ReadState, entry_read_state, list_gate

    _list(policy="SIGNAL_ONLY")
    entry = _entry(page="")
    assert entry_read_state(entry, "SIGNAL_ONLY").state == ReadState.GATED
    assert list_gate("l", now=NOW).passed


def test_a_rejected_body_is_recorded_rejected_with_its_reason() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    Organisation.objects.filter(pk=entry.organisation_id).update(
        status="REJECTED", rejected_reason="NOT_A_FUNDER"
    )
    entry.refresh_from_db()
    found = entry_read_state(entry, "FUNDING_READ")
    assert (found.state, found.detail) == (ReadState.REJECTED, "NOT_A_FUNDER")


def test_fewer_entries_than_the_list_prints_is_not_enumerated() -> None:
    from apps.research.read_state import list_gate

    _list(policy="SIGNAL_ONLY", printed_size=2)
    _entry(page="")
    gate = list_gate("l", now=NOW)
    assert not gate.enumerated and not gate.passed


def test_recording_writes_the_state_and_the_bodys_read_fields() -> None:
    from apps.research.read_state import record_read_states

    _list()
    entry = _entry()
    _snapshot("https://www.body.example.org/scholarship", funding_read_at=NOW)
    tally = record_read_states("l", now=NOW)
    entry.refresh_from_db()
    assert tally == {"FUNDING_READ": 1}
    assert (entry.read_state, entry.read_state_at) == ("FUNDING_READ", NOW)
    org = Organisation.objects.get(pk=entry.organisation_id)
    assert (org.last_read_at, org.pages_read) == (NOW, 1)


def test_a_list_past_its_recheck_date_is_stale_but_not_failed(settings) -> None:
    from apps.research.read_state import list_gate

    settings.CLOSED_LIST_RECHECK_DAYS = 90
    _list(policy="SIGNAL_ONLY", verified_on=date.today() - timedelta(days=91))
    _entry(page="")
    gate = list_gate("l", now=NOW)
    assert gate.stale and gate.passed
```

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_read_state.py -q 2>&1 | tail -3`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.read_state'`.

- [ ] **Step 4: Implement `apps/research/read_state.py`**

```python
"""What reading each body a closed list names came to.

"100% enumerated with read states recorded" (spec 16 item 7) is two claims,
and this module is the arithmetic behind both:

- enumerated: every row is bound to an Organisation, and the row count equals
  the count the publisher prints, where it prints one;
- read state recorded: every row carries one word from a closed set saying
  what reading it came to -- including "could not look" and "not read, by
  rule" -- never a blank.

The word is DERIVED from records other code already writes (snapshots and
their `funding_read_at` / `readability`, the classifier's columns, the fetch
trail) and then stored on the entry. So the coverage line is a query, and no
number a person typed can satisfy the gate.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from django.conf import settings
from django.db.models import Max, Q, QuerySet

from apps.funding.models import OfficialSource, OfficialSourceSnapshot

from .closed_lists import has_signal
from .fetch.types import Outcome
from .models import ClosedList, FetchAttempt, Organisation, RegisterEntry


class ReadState(StrEnum):
    #: The list names a body no row holds -- the enumeration half of the gate.
    UNBOUND = "UNBOUND"
    #: Two keys named two bodies; a person decides (spec 11, build item 12).
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"
    FUNDING_READ = "FUNDING_READ"
    CLASSIFIED = "CLASSIFIED"
    #: The classifier read the homepage and would not commit. Read, undecided.
    ABSTAINED = "ABSTAINED"
    #: Fetched, and nothing could be read: a shell, a soft 404, a scan.
    UNREADABLE = "UNREADABLE"
    #: The host stopped us (blocked, unreachable, dead, off-site, retry due).
    COULD_NOT_LOOK = "COULD_NOT_LOOK"
    #: SIGNAL_ONLY and no signal: known, deliberately not read (owner 2026-09-23).
    GATED = "GATED"
    #: ENUMERATE_ONLY: the row routes other work; nothing here reads it.
    ENUMERATED = "ENUMERATED"
    #: Nothing attempted, or our own budget stopped it -- the read half of the gate.
    UNREAD = "UNREAD"


_FAILING = frozenset({ReadState.UNBOUND, ReadState.UNREAD})
_HOST_REFUSED = frozenset({
    Outcome.BLOCKED, Outcome.UNREACHABLE, Outcome.DEAD, Outcome.OFF_SITE,
    Outcome.INVALID, Outcome.RETRY_SCHEDULED,
})


@dataclass(frozen=True)
class EntryState:
    state: ReadState
    detail: str = ""


def _domains(org: Organisation) -> list[str]:
    return list(org.domains.values_list("registrable_domain", flat=True))


def _snapshots_on(org: Organisation) -> QuerySet[OfficialSourceSnapshot]:
    """Every snapshot of a page on any of the body's registrable domains --
    a hop inside its own site is still its page."""
    match = Q()
    for domain in _domains(org):
        match |= Q(publisher=domain) | Q(publisher__endswith=f".{domain}")
    if not match:
        return OfficialSourceSnapshot.objects.none()
    return OfficialSourceSnapshot.objects.filter(source__in=OfficialSource.objects.filter(match))


def _from_attempt(urls: list[str]) -> EntryState | None:
    attempt = FetchAttempt.objects.filter(url__in=urls).order_by("-created_at").first()
    if attempt is None:
        return None
    if attempt.outcome == Outcome.BUDGET:
        return EntryState(ReadState.UNREAD, "budget")
    if attempt.outcome == Outcome.UNREADABLE:
        return EntryState(ReadState.UNREADABLE, "fetch")
    if attempt.outcome in _HOST_REFUSED:
        return EntryState(ReadState.COULD_NOT_LOOK, attempt.outcome)
    return None


def _funding_state(entry: RegisterEntry, org: Organisation) -> EntryState:
    snapshots = _snapshots_on(org)
    read = snapshots.filter(funding_read_at__isnull=False)
    if read.exists():
        return EntryState(ReadState.FUNDING_READ, f"{read.values('source').distinct().count()} pages")
    unreadable = (
        snapshots.exclude(readability=OfficialSourceSnapshot.Readability.OK)
        .values_list("readability", flat=True).first()
    )
    if unreadable:
        return EntryState(ReadState.UNREADABLE, unreadable)
    return _from_attempt([entry.page_url]) or EntryState(ReadState.UNREAD)


def _classify_state(org: Organisation) -> EntryState:
    if org.classified_at is not None:
        return EntryState(ReadState.CLASSIFIED, org.classified_by)
    if org.classifier_confidence is not None:
        return EntryState(ReadState.ABSTAINED, f"{org.classifier_confidence:.2f}")
    if org.pages_unreadable:
        return EntryState(ReadState.UNREADABLE, "homepage")
    home = [f"https://{org.primary_domain}/", f"https://{org.primary_domain}"]
    return _from_attempt(home) or EntryState(ReadState.UNREAD)


def entry_read_state(entry: RegisterEntry, policy: str) -> EntryState:
    if entry.resolution == RegisterEntry.Resolution.CONFLICT:
        return EntryState(ReadState.CONFLICT)
    if policy == ClosedList.ReadPolicy.ENUMERATE_ONLY:
        return EntryState(ReadState.ENUMERATED)
    org = entry.organisation
    if org is None:
        return EntryState(ReadState.UNBOUND, entry.resolution)
    if org.status == Organisation.Status.REJECTED:
        return EntryState(ReadState.REJECTED, org.rejected_reason)
    if policy == ClosedList.ReadPolicy.SIGNAL_ONLY and not has_signal(org):
        return EntryState(ReadState.GATED)
    if policy == ClosedList.ReadPolicy.CLASSIFY:
        return _classify_state(org)
    return _funding_state(entry, org)


def _record_body_read(org: Organisation) -> None:
    """Spec 6.1's latest-state read fields, from the same snapshots."""
    read = _snapshots_on(org).filter(funding_read_at__isnull=False)
    last = read.aggregate(last=Max("funding_read_at"))["last"]
    pages = read.values("source").distinct().count()
    if (org.last_read_at, org.pages_read) != (last, pages):
        org.last_read_at, org.pages_read = last, pages
        org.save(update_fields=["last_read_at", "pages_read"])


def record_read_states(slug: str, *, now: datetime) -> Counter[str]:
    policy = ClosedList.objects.values_list("read_policy", flat=True).get(slug=slug)
    tally: Counter[str] = Counter()
    for entry in RegisterEntry.objects.filter(register=slug).select_related("organisation"):
        found = entry_read_state(entry, policy)
        tally[found.state] += 1
        detail = found.detail[:120]
        if (entry.read_state, entry.read_state_detail) != (found.state, detail):
            entry.read_state, entry.read_state_detail, entry.read_state_at = (
                found.state, detail, now,
            )
            entry.save(update_fields=["read_state", "read_state_detail", "read_state_at"])
        if found.state == ReadState.FUNDING_READ and entry.organisation is not None:
            _record_body_read(entry.organisation)
    return tally


@dataclass(frozen=True)
class ListGate:
    slug: str
    listed: int
    printed_size: int | None
    bodies_known: int
    states: dict[str, int]
    stale: bool

    @property
    def enumerated(self) -> bool:
        return self.listed > 0 and (self.printed_size is None or self.listed == self.printed_size)

    @property
    def passed(self) -> bool:
        return self.enumerated and not any(self.states.get(state, 0) for state in _FAILING)


def list_gate(slug: str, *, now: datetime) -> ListGate:
    spec = ClosedList.objects.get(slug=slug)
    states = record_read_states(slug, now=now)
    entries = RegisterEntry.objects.filter(register=slug)
    return ListGate(
        slug=slug,
        listed=entries.count(),
        printed_size=spec.printed_size,
        bodies_known=entries.filter(organisation__isnull=False)
        .values("organisation").distinct().count(),
        states=dict(states),
        stale=now.date() - spec.verified_on > timedelta(days=settings.CLOSED_LIST_RECHECK_DAYS),
    )
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_read_state.py tests/research/test_closed_lists.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"`
Expected: all pass.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check apps config tests && uv run mypy apps config | tail -1
git add apps/research/read_state.py tests/research/test_read_state.py config/settings/base.py
git commit -m "feat(research): read states -- derived from the reader and classifier trails, stored, gated"
```

---

### Task 4: The operator commands — load, coverage, read

**Files:**
- Create: `apps/research/management/commands/load_closed_lists.py`, `closed_list_coverage.py`, `read_closed_list.py`
- Create: `tests/research/test_closed_list_commands.py`

**Interfaces:**
- `manage.py load_closed_lists [--registry PATH] [--lists-dir DIR] [--list SLUG ...]` loads the registry, then every `<slug>.csv` present (or only the named slugs), and prints one `ListReport` line per list.
- `manage.py closed_list_coverage [--list SLUG ...] [--gate]` records read states and prints one line per list plus a verdict. With `--gate`, it raises `CommandError` when any printed list failed.
- `manage.py read_closed_list --list SLUG --tenant UUID [--max-leads N] [--cycle YYYY]` runs `run_discovery([ClosedListSource(slug)])` with both model families.

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/test_closed_list_commands.py
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.research.models import ClosedList, RegisterEntry

pytestmark = pytest.mark.django_db

_REGISTRY = (
    "slug,title,country_code,holder_kinds,rung,source_url,maintainer,carries_purpose,"
    "carries_website,reuse_terms,reuse_terms_url,is_denominator,read_policy,printed_size,"
    "verified_on\n"
    "tr_banks,Licensed banks,TR,BANK_OR_LENDER,2,https://www.bddk.org.tr/,BDDK,no,yes,"
    "UNREAD,,yes,SIGNAL_ONLY,2,2026-09-25\n"
)
_ROWS = (
    "external_key,name,kind,website,page_url,country_code,home_cells,host_cells,"
    "rejected_reason,source_url,verified_on,notes\n"
    "b1,Birinci Bankası,BANK_OR_LENDER,https://www.birinci.com.tr,,TR,TR,ANY,,"
    "https://www.bddk.org.tr/,2026-09-25,\n"
)


def _files(tmp_path: Path) -> tuple[Path, Path]:
    registry = tmp_path / "closed-lists.csv"
    registry.write_text(_REGISTRY, encoding="utf-8")
    lists = tmp_path / "closed-lists"
    lists.mkdir()
    (lists / "tr_banks.csv").write_text(_ROWS, encoding="utf-8")
    return registry, lists


def test_load_then_coverage_fails_the_gate_on_a_short_list(tmp_path: Path) -> None:
    registry, lists = _files(tmp_path)
    out = StringIO()
    call_command("load_closed_lists", registry=str(registry), lists_dir=str(lists), stdout=out)
    assert "tr_banks: listed 1, bound 1" in out.getvalue()
    assert RegisterEntry.objects.filter(register="tr_banks").count() == 1

    out = StringIO()
    with pytest.raises(CommandError, match="tr_banks"):
        call_command("closed_list_coverage", list=["tr_banks"], gate=True, stdout=out)
    line = out.getvalue()
    assert "tr_banks  listed 1/2" in line and "GATED=1" in line and "FAIL" in line


def test_coverage_passes_when_every_row_is_bound_and_recorded(tmp_path: Path) -> None:
    registry, lists = _files(tmp_path)
    registry.write_text(_REGISTRY.replace(",2,2026-09-25", ",1,2026-09-25"), encoding="utf-8")
    call_command("load_closed_lists", registry=str(registry), lists_dir=str(lists),
                 stdout=StringIO())
    out = StringIO()
    call_command("closed_list_coverage", list=["tr_banks"], gate=True, stdout=out)
    assert "PASS" in out.getvalue()


def test_read_closed_list_refuses_a_list_nothing_reads(tmp_path: Path) -> None:
    registry, lists = _files(tmp_path)
    registry.write_text(_REGISTRY.replace("SIGNAL_ONLY", "CLASSIFY"), encoding="utf-8")
    call_command("load_closed_lists", registry=str(registry), lists_dir=str(lists),
                 stdout=StringIO())
    with pytest.raises(CommandError, match="classify_organisations --found-via R2_LIST:tr_banks"):
        call_command("read_closed_list", list="tr_banks",
                     tenant="00000000-0000-0000-0000-000000000001")
    assert ClosedList.objects.get().read_policy == "CLASSIFY"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_closed_list_commands.py -q 2>&1 | tail -3`
Expected: FAIL with `CommandError: Unknown command: 'load_closed_lists'`.

- [ ] **Step 3: Implement the three commands**

```python
# apps/research/management/commands/load_closed_lists.py
"""Load the closed-list registry and every hand-read list into the register.

Operator-run, idempotent, and nothing here fetches: the files were read by a
person from the publisher's page (spec 6.2, "read by hand into a versioned
file per country"). Adding a list is adding a registry row and a file, never
a command.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import closed_lists
from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.models import ClosedList


class Command(BaseCommand):
    help = "Load docs/research/closed-lists.csv and its rows files into the register." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--registry", default=str(closed_lists.REGISTRY))
        parser.add_argument("--lists-dir", default=str(closed_lists.LISTS_DIR))
        parser.add_argument("--list", action="append", default=[], dest="slugs")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            count = closed_lists.load_registry(Path(options["registry"]))
        except closed_lists.ListFileError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f"registry: {count} lists")
        now = timezone.now()
        lists_dir = Path(options["lists_dir"])
        specs = ClosedList.objects.order_by("slug")
        if options["slugs"]:
            specs = specs.filter(slug__in=options["slugs"])
        for spec in specs:
            path = lists_dir / f"{spec.slug}.csv"
            if not path.exists():
                continue  # an adapter-read list: VGM, EACEA, Wikidata, ROR
            try:
                report = closed_lists.record_list(
                    spec, closed_lists.read_list_file(spec, path), now=now
                )
            except closed_lists.ListFileError as error:
                raise CommandError(str(error)) from error
            fields = asdict(report)
            self.stdout.write(
                f"{spec.slug}: listed {fields['listed']}, bound {fields['bound']}, "
                f"unresolved {fields['unresolved']}, new {fields['organisations_new']}, "
                f"promoted {fields['promoted']}, rejected {fields['rejected']}"
            )
```

```python
# apps/research/management/commands/closed_list_coverage.py
"""The coverage line per closed list, and the build-item-7 gate (spec 16).

Records every entry's read state first (read_state.record_read_states), then
prints: listed / printed, bodies known, the state histogram, STALE, PASS|FAIL.
`--gate` turns a FAIL into a non-zero exit, so the gate is a command's exit
code and not a paragraph someone reads.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.models import ClosedList
from apps.research.read_state import list_gate


class Command(BaseCommand):
    help = "Record read states and print each closed list's coverage line."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--list", action="append", default=[], dest="slugs")
        parser.add_argument("--gate", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        slugs = options["slugs"] or list(
            ClosedList.objects.order_by("slug").values_list("slug", flat=True)
        )
        failed: list[str] = []
        for slug in slugs:
            gate = list_gate(slug, now=now)
            printed = "?" if gate.printed_size is None else str(gate.printed_size)
            states = " ".join(f"{key}={value}" for key, value in sorted(gate.states.items()))
            verdict = "PASS" if gate.passed else "FAIL"
            stale = " STALE" if gate.stale else ""
            self.stdout.write(
                f"{slug}  listed {gate.listed}/{printed}  known {gate.bodies_known}  "
                f"{states}{stale}  {verdict}"
            )
            if not gate.passed:
                failed.append(slug)
        if options["gate"] and failed:
            raise CommandError(f"gate failed: {', '.join(failed)}")
```

```python
# apps/research/management/commands/read_closed_list.py
"""Read one closed list's scheme pages for funding (spec 6.2, 16 item 7).

The same reader every other route uses -- `run_discovery` with both model
families -- fed by `ClosedListSource`, so a list's pages are read, snapshotted,
chunked, budgeted and rate-limited exactly as a catalogue's are. Only
FUNDING_READ and SIGNAL_ONLY lists are read here; an institution list is read
by the classifier, and saying which command is the whole error message.
"""

from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID

import anthropic
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from openai import OpenAI

from apps.research.closed_lists import ClosedListSource
from apps.research.discovery import DiscoveryQuery, RunBudget
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import CATALOG_ROLE_NOTE, SweepBudget
from apps.research.funding_judge import FUNDING_READS, MAX_CHUNKS
from apps.research.models import ClosedList
from apps.research.pipeline import PacedFetch, run_discovery
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope

_READ = (ClosedList.ReadPolicy.FUNDING_READ, ClosedList.ReadPolicy.SIGNAL_ONLY)


class Command(BaseCommand):
    help = "Read a closed list's scheme pages through the funding reader." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--list", required=True, dest="slug")
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--max-leads", type=int, default=60)
        parser.add_argument("--cycle", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        slug = options["slug"]
        spec = ClosedList.objects.filter(slug=slug).first()
        if spec is None:
            raise CommandError(f"no closed list {slug!r}; run load_closed_lists first")
        if spec.read_policy not in _READ:
            raise CommandError(
                f"{slug} is {spec.read_policy}: nothing here reads it. An institution list "
                f"is read by the classifier: classify_organisations --found-via "
                f"R{spec.rung}_LIST:{slug}"
            )
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            if not os.environ.get(key):
                raise CommandError(f"{key} is unset: a row is served only when two families agree")
        tenant_id = UUID(options["tenant"])
        max_leads = int(options["max_leads"])
        budget = RunBudget(
            searches=0, fetches=max_leads * 3,
            extractions=max_leads * FUNDING_READS * MAX_CHUNKS,
        )
        fetch = PacedFetch(
            actor_id=tenant_id, budget=budget, credits=SweepBudget(settings.FETCH_SWEEP_CREDITS)
        )
        with tenant_scope(tenant_id):
            report = run_discovery(
                DiscoveryQuery(field=slug, country_code=spec.country_code, max_leads=max_leads),
                [ClosedListSource(slug)],
                tenant_id=tenant_id,
                store=S3ObjectStore(),
                admissions_cycle=options["cycle"] or str(timezone.now().year + 1),
                fetch=fetch,
                budget=budget,
                funding_parser=cast(ResponsesAPI, OpenAI().responses),
                funding_claude=cast(MessagesAPI, anthropic.Anthropic().messages),
            )
        self.stdout.write(
            f"leads={report.leads} written={report.written} unchanged={report.unchanged} "
            f"blocked={report.blocked} degraded={','.join(report.degraded) or 'none'} "
            f"funding: {report.funding}"
        )
        self.stdout.write(f"then: manage.py closed_list_coverage --list {slug}")
```

If `run_discovery` raises `ProgrammingError`, copy `discover.py`'s `except ProgrammingError` block verbatim. The two failure causes look identical, and that message is what tells them apart.

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_closed_list_commands.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"`
Expected: all pass.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check apps tests && uv run mypy apps config | tail -1
git add apps/research/management/commands/load_closed_lists.py apps/research/management/commands/closed_list_coverage.py apps/research/management/commands/read_closed_list.py tests/research/test_closed_list_commands.py
git commit -m "feat(research): load_closed_lists, closed_list_coverage --gate, read_closed_list"
```

---

### Task 5: The intergovernmental and regional-fund list — global, cell-tagged

**Files:**
- Create: `docs/research/closed-lists.csv` (registry; first rows)
- Create: `docs/research/closed-lists/igo_regional_global.csv`
- Create: `tests/research/test_closed_list_data.py`

This is a content task. The list is compiled from each body's own page and never from an aggregator (§3.2). It must hold for any student in any country (§3, "country is data"): a Nigerian applicant's AfDB and Mastercard Foundation schemes belong on it exactly as much as an Azerbaijani applicant's IsDB scheme.

- [ ] **Step 1: Write the registry with its first three rows**

```csv
slug,title,country_code,holder_kinds,rung,source_url,maintainer,carries_purpose,carries_website,reuse_terms,reuse_terms_url,is_denominator,read_policy,printed_size,verified_on
eacea_emjm,Erasmus Mundus Joint Masters (EACEA project records),,,1,https://erasmus-plus.ec.europa.eu/projects/search,European Education and Culture Executive Agency,yes,yes,OPEN,https://commission.europa.eu/legal-notice_en,yes,ENUMERATE_ONLY,,2026-09-25
igo_regional_global,Intergovernmental bodies and regional funds with a master's award open to individuals,,INTERGOVERNMENTAL|REGIONAL_FUND|NATIONAL_GOVERNMENT|PRIVATE_FOUNDATION,1,https://github.com/0rkhann/tehsil_agent/blob/master/docs/research/closed-lists/igo_regional_global.csv,tehsil_agent (compiled from each body's own page),yes,yes,OWN_COMPILATION,,yes,FUNDING_READ,,2026-09-25
vgm_tr,Vakıflar Genel Müdürlüğü -- scholarship-giving foundations (IsGrant=true),TR,PRIVATE_FOUNDATION,1,https://www.vgm.gov.tr/vakif-sorgulama/vakif-sorgulama?IsGrant=true,Vakıflar Genel Müdürlüğü,yes,no,UNREAD,,yes,CLASSIFY,4076,2026-09-24
```

`NATIONAL_GOVERNMENT` and `PRIVATE_FOUNDATION` are in the IGO list's kinds because the owner's named set includes the Commonwealth Scholarships (UK government-funded) and the Mastercard and Aga Khan Foundations. A body's kind is what the body is. The list's scope is what it funds: master's students across borders under a regional or intergovernmental remit.

- [ ] **Step 2: Compile `igo_regional_global.csv` — method, in this order**

1. **The named set, every one:** World Bank (Joint Japan/World Bank Graduate Scholarship Program), Islamic Development Bank, Asian Development Bank (ADB–Japan Scholarship Program), African Development Bank, Inter-American Development Bank, Commonwealth Scholarships, Mastercard Foundation, International Visegrad Fund, Nordic Council of Ministers, EEA Grants, OPEC Fund for International Development, UNESCO, Aga Khan Foundation (International Scholarship Programme), and the Black Sea Trust (§6.3).
2. **One hop out from each named body's own pages** (§6.4's hub rule). Look for a "partners", "other scholarships" or "fellowships" page on the body's site. Every intergovernmental or regional body it names is a candidate.
3. **The multilateral families as a checklist:** the other multilateral development banks (EBRD, EIB, AIIB, CAF, Caribbean Development Bank), the OIC's bodies, the Council of Europe, the Organization of Turkic States, and the UN system's scholarship-granting bodies. For each, check the body's own site for a master's-level award open to individuals.
4. **Entry rule:** a row enters only if the body's own page states a master's-level award open to individuals. The row uses the page URL of that award, and `page_url` must share `website`'s registrable domain. Where the award lives on a dedicated domain the body owns (for example a scholarship programme site), set `website` to that domain and say so in `notes`.
5. **A named body that funds no master's student** is still a row: `rejected_reason=NOT_A_FUNDER`, `page_url` empty, `source_url` the page that shows it, and one line in `notes` saying why. It is never dropped silently. A body whose award is doctoral-only or non-degree is `NOT_A_FUNDER` for this list (§5, "out by owner decision").
6. **Cells:** `home_cells` and `host_cells` are copied from the award page's own eligibility statement, as ISO codes, as `REGIONS` keys (for example `AFRICAN_UNION` or `EASTERN_PARTNERSHIP`), or as `ANY`. When the page names a group `REGIONS` does not hold (for example "IsDB member countries"), write `ANY` and name the group in `notes`. Never write the corridor's two countries in place of a group. A tag may be wider than the truth and never narrower, because the reader's conditions decide eligibility (§8.5) and the tag only selects a pool.
7. `external_key` is a stable lowercase slug per scheme, such as `worldbank-jjwbgsp`. `verified_on` is the day the page was read. `country_code` is the body's seat, or blank for a body with no single seat.

- [ ] **Step 3: Write the data tests**

```python
# tests/research/test_closed_list_data.py
"""The committed list files, parsed and checked without a database write.

These are data tests: they pin that the files load, that the owner-named
intergovernmental set is present, and that the global list is not sized to one
corridor (spec 19, build item 7).
"""

from datetime import date

import pytest

from apps.funding.regions import REGIONS
from apps.research.closed_lists import LISTS_DIR, REGISTRY, read_list_file, read_registry
from apps.research.models import ClosedList

pytestmark = pytest.mark.django_db

#: The owner's named set (brief and spec 16 item 7), matched on the body name
#: the file carries, case-folded. A name, not a domain: a body that moves its
#: site must not fail this test, and a body missing from the file must.
_NAMED = (
    "world bank", "islamic development bank", "asian development bank",
    "african development bank", "inter-american development bank", "commonwealth",
    "mastercard foundation", "visegrad", "nordic council", "eea grants", "opec fund",
    "unesco", "aga khan",
)


def _spec(slug: str) -> ClosedList:
    row = next(spec for spec in read_registry() if spec["slug"] == slug)
    return ClosedList(**row)


def test_every_registry_row_parses_and_every_rows_file_has_a_registry_row() -> None:
    slugs = {str(spec["slug"]) for spec in read_registry(REGISTRY)}
    files = {path.stem for path in LISTS_DIR.glob("*.csv")}
    assert files <= slugs, f"rows files with no registry row: {files - slugs}"
    for slug in files:
        assert read_list_file(_spec(slug))


def test_the_intergovernmental_list_carries_the_owner_named_set() -> None:
    names = " | ".join(row.name.casefold() for row in read_list_file(_spec("igo_regional_global")))
    missing = [body for body in _NAMED if body not in names]
    assert not missing, f"named bodies absent from the list: {missing}"


def test_the_intergovernmental_list_is_not_sized_to_one_corridor() -> None:
    """At least one scheme funds students from neither launch country -- the
    list serves a Nigerian applicant as well as an Azerbaijani one."""
    def reaches(cells: tuple[str, ...], country: str) -> bool:
        return "ANY" in cells or country in cells or any(
            country in REGIONS[cell].countries for cell in cells if cell in REGIONS
        )

    rows = read_list_file(_spec("igo_regional_global"))
    assert any(
        not reaches(row.home_cells, "AZ") and not reaches(row.home_cells, "TR")
        for row in rows if not row.rejected_reason
    )


def test_no_list_row_is_verified_in_the_future() -> None:
    for path in LISTS_DIR.glob("*.csv"):
        for row in read_list_file(_spec(path.stem)):
            assert row.verified_on <= date.today(), (path.name, row.external_key)
```

- [ ] **Step 4: Run, fix the data until green, commit**

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_closed_list_data.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"`
Expected: all pass. Fix a failure in the file, never in the test.

```bash
grep -c "@" docs/research/closed-lists/*.csv   # expect 0 on every file
git add docs/research/closed-lists.csv docs/research/closed-lists/igo_regional_global.csv tests/research/test_closed_list_data.py
git commit -m "docs(research): the global intergovernmental and regional-fund list, cell-tagged"
```

---

### Task 6: The register survey — per corridor country, per family

**Files:**
- Create: `docs/research/register-survey.csv`
- Create: `tests/research/test_register_survey.py`

The survey decides which curated lists Task 8 builds. It is owed for every corridor country (§19): **AZ, TR, KZ, GE, UZ, DE, NL, SE, FR, HU, IT, ID, VN, IN, PK**. It covers every family that a list can serve: `NATIONAL_GOVERNMENT`, `SUBNATIONAL_GOVERNMENT`, `EMBASSY_BILATERAL`, `POLITICAL_FOUNDATION`, `RELIGIOUS`, `PRIVATE_FOUNDATION`, `EMPLOYER`, `PROFESSIONAL_BODY`, `BANK_OR_LENDER` and `INSTITUTION`. That is 150 rows. Three families are deliberately excluded. `INTERGOVERNMENTAL` and `REGIONAL_FUND` are the global list (Task 5). `ALUMNI` derives from institutions (§5). `DIASPORA_AFFINITY` is keyed by (host, home language) and never by country (decision 37).

- [ ] **Step 1: Columns and vocabulary**

```csv
country_code,kind,rung,list_url,maintainer,purpose_filter,row_carries,access,reuse_terms,reuse_terms_url,closed_list_slug,surveyed_on,searched_for,notes
```

- `rung`: 1 = a register that carries the purpose; 2 = a register without the purpose; 3 = umbrella bodies or hubs (partial, every name real); 4 = no list found, search only (§6.2).
- `purpose_filter`: `yes`/`no`. `row_carries`: `website`/`email`/`both`/`neither`. `access`: `API`/`FILE`/`WEB_PAGE`/`FORM`/`NONE`.
- `reuse_terms`: `OPEN`/`UNREAD`/`OWN_COMPILATION`/`RESTRICTIVE`/`NONE`. `RESTRICTIVE` means the terms forbid automated reuse. No adapter is written for such a list, and whether a person may read it into a file is the owner's decision, recorded in `notes`.
- Rungs 1–3 need `list_url` (https) and `maintainer`. Rung 4 needs `searched_for`: what was looked for and where, in one line.
- `closed_list_slug` names the registry row the list became, or is blank.

- [ ] **Step 2: Seed the rows the spec already measured**

These rows are carried over verbatim from §6.2 and §19, then re-checked on the day:

- TR `PRIVATE_FOUNDATION`: rung 1, `https://www.vgm.gov.tr/vakif-sorgulama/vakif-sorgulama?IsGrant=true`, Vakıflar Genel Müdürlüğü, purpose yes, email, `WEB_PAGE`, `UNREAD`, slug `vgm_tr`, 2026-09-24.
- DE `PRIVATE_FOUNDATION`: rung 2, the BZSt Zuwendungsempfängerregister on `bzst.de`, purpose no ("searchable by tax-privileged purpose" is a filter on purpose categories, not a scholarship flag; the survey records which), `neither`, `WEB_PAGE`, `UNREAD`. `notes`: the federal Stiftungsregister opens 2028-01-01 (future rung 1); `foerdermittelkompass.reflecta.org` is a candidate directory with its licence unread.
- KZ `PRIVATE_FOUNDATION`: rung 3, `publicreg.myafsa.com`. `notes`: AIFC-registered foundations only, not a national register.
- IT `SUBNATIONAL_GOVERNMENT`: rung 3, ANDISU's list of regional DSU agencies (`andisu.it`). `notes`: incoming internationals eligible (§6.3's ten-country table).

- [ ] **Step 3: Survey TR and AZ completely first (20 rows)**

For each (country, kind), in this order, and stop at the first rung that holds:

1. **The regulator's or registrar's own list.** Institutions: the ministry or higher-education authority's register of licensed HEIs (for TR, YÖK's university list, which printed 208 when §6.2 measured it; for AZ, the Ministry of Science and Education and TKTA — §6.2 recorded that TKTA publishes no list; corrected 2026-09-26: TKTA publishes two negative lists as JSON (not recognised; high refusal) and no list of recognised institutions -- provenance gate spec §9.6). Banks: the central bank's or banking regulator's list of licensed institutions (TR's banking regulator; AZ's central bank). Foundations: the foundations or charities register. Employers: the stock exchange's listed-company list and the chamber of industry's ranking (decision 36; ISO 500 for TR).
2. **Umbrella bodies:** professional chambers' member lists, foundation associations, Philea's member list, ECFI's atlas, and the Centre Français des Fondations' list of national networks (§6.2).
3. **The ministry's hub page:** for home-side government schemes, the education ministry's page listing its outbound programmes (TR: YLSY and the other MEB schemes; AZ: the State Program for education abroad). For bilateral schemes, the ministry's page listing host governments' quota scholarships. AZ has the Intergovernmental Scholarship Programme, published per cycle on `htp.edu.az` (`docs/superpowers/research/2026-08-29-origin-side-synthesis.md` §2).
4. **None found:** rung 4, and `searched_for` says where you looked.

For every rung 1–3 row: open the host's terms or legal page and record `reuse_terms`, and inspect one page of rows to record `row_carries`. Do not paste a single row of the list into `notes`.

- [ ] **Step 4: Write the survey test (TR and AZ enforced)**

```python
# tests/research/test_register_survey.py
"""The register survey (spec 6.2's ladder, 19): one row per corridor country x
family, each stating which rung exists and on what evidence."""

import csv
from datetime import date
from pathlib import Path

import pytest

from apps.research.closed_lists import DATA_DIR, read_registry

SURVEY = DATA_DIR / "register-survey.csv"
_COLUMNS = (
    "country_code", "kind", "rung", "list_url", "maintainer", "purpose_filter",
    "row_carries", "access", "reuse_terms", "reuse_terms_url", "closed_list_slug",
    "surveyed_on", "searched_for", "notes",
)
#: Enforced now. Task 6 Step 6 widens this to every corridor country.
SURVEYED = ("TR", "AZ")
KINDS = (
    "NATIONAL_GOVERNMENT", "SUBNATIONAL_GOVERNMENT", "EMBASSY_BILATERAL",
    "POLITICAL_FOUNDATION", "RELIGIOUS", "PRIVATE_FOUNDATION", "EMPLOYER",
    "PROFESSIONAL_BODY", "BANK_OR_LENDER", "INSTITUTION",
)


def _rows() -> list[dict[str, str]]:
    with SURVEY.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == _COLUMNS
        return list(reader)


def test_every_surveyed_country_has_one_row_per_family() -> None:
    seen = [(row["country_code"], row["kind"]) for row in _rows()]
    assert len(seen) == len(set(seen)), "a (country, kind) surveyed twice"
    missing = [(c, k) for c in SURVEYED for k in KINDS if (c, k) not in set(seen)]
    assert not missing, f"unsurveyed: {missing}"


@pytest.mark.parametrize("row", _rows(), ids=lambda r: f"{r['country_code']}-{r['kind']}")
def test_a_row_states_its_evidence(row: dict[str, str]) -> None:
    assert row["kind"] in KINDS
    assert row["rung"] in {"1", "2", "3", "4"}
    assert row["purpose_filter"] in {"yes", "no", ""}
    assert row["row_carries"] in {"website", "email", "both", "neither", ""}
    assert row["access"] in {"API", "FILE", "WEB_PAGE", "FORM", "NONE"}
    assert row["reuse_terms"] in {"OPEN", "UNREAD", "OWN_COMPILATION", "RESTRICTIVE", "NONE"}
    assert date.fromisoformat(row["surveyed_on"]) <= date.today()
    if row["rung"] == "4":
        assert row["searched_for"].strip(), "rung 4 must say what was searched for"
    else:
        assert row["list_url"].startswith("https://") and row["maintainer"].strip()
        assert row["purpose_filter"] and row["row_carries"]
    assert "@" not in "".join(row.values())


def test_a_named_slug_is_a_registry_row() -> None:
    slugs = {str(spec["slug"]) for spec in read_registry()}
    for row in _rows():
        if row["closed_list_slug"]:
            assert row["closed_list_slug"] in slugs, row
```

Run: `uv run pytest tests/research/test_register_survey.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"`. This test file needs no database. Expected: pass once the 20 TR/AZ rows exist.

- [ ] **Step 5: Commit the TR/AZ half**

```bash
git add docs/research/register-survey.csv tests/research/test_register_survey.py
git commit -m "docs(research): register survey for Türkiye and Azerbaijan, every family"
```

- [ ] **Step 6: Survey the other thirteen countries, then widen the test**

Use the same method for KZ, GE, UZ, DE, NL, SE, FR, HU, IT, ID, VN, IN and PK. Rows 1–3 are what future curated lists come from. Rung-4 rows are what the coverage line will report as "search only". When all 150 rows exist, change `SURVEYED` in the test to all fifteen codes, run it, and commit:

```bash
git commit -am "docs(research): register survey for every corridor country"
```

This step does not block Tasks 7–13. It is part of this item's deliverable, and the final gate report (Task 13) states whether it is complete.

---

### Task 7: `fetch_json_api(accept=...)`, then Wikidata

**Files:**
- Modify: `apps/research/egress.py` (`fetch_json_api` gains `accept`)
- Modify: `tests/research/test_egress.py` (append)
- Create: `apps/research/wikidata.py`, `apps/research/management/commands/enumerate_wikidata.py`, `docs/research/wikidata-enumerations.csv`, `tests/research/test_wikidata.py`, `tests/research/fixtures/wikidata_tr_university.json`
- Modify: `config/settings/base.py` (`WIKIDATA_USER_AGENT`), `docs/research/closed-lists.csv` (one row per enumeration)

**Interfaces:**
- `fetch_json_api(..., accept: tuple[str, ...] = ("application/json",))` sends `Accept: ", ".join(accept)` and accepts a response content type in `accept`. The default behaviour is unchanged.
- `wikidata.EnumerationRow`, `read_enumerations(path) -> tuple[EnumerationRow, ...]`, `query_text(row) -> str`, `parse_bindings(body) -> tuple[Item, ...]`, `fetch_items(row, *, call=fetch_json_api) -> tuple[Item, ...]`, `record_items(row, items, *, now) -> EnumerationReport`, `EnumerationShape`.

- [ ] **Step 1: The egress test, then the change**

```python
# tests/research/test_egress.py -- append


class _JsonBody:
    def __init__(self, content_type: str) -> None:
        self.status, self.headers = 200, {"Content-Type": content_type}
        self._chunks = [b'{"results": {"bindings": []}}']

    def read(self, amount: int, decode_content: bool = True) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def release_conn(self) -> None:
        pass


def test_fetch_json_api_accepts_a_declared_json_dialect(public_dns) -> None:
    """SPARQL answers application/sparql-results+json. The default stays strict;
    a caller widens it by name, and the Accept header says the same thing."""
    sent: dict[str, str] = {}

    def transport(_target, _path, **kwargs):
        sent.update(kwargs["extra_headers"])
        return _JsonBody("application/sparql-results+json; charset=utf-8")

    body = fetch_json_api(
        "https://query.wikidata.org/sparql", params={"query": "ASK {}"}, headers={},
        transport=transport, accept=("application/sparql-results+json",),
    )
    assert body == {"results": {"bindings": []}}
    assert sent["Accept"] == "application/sparql-results+json"
    with pytest.raises(SourceBlocked, match="content type"):
        fetch_json_api(
            "https://query.wikidata.org/sparql", params={"query": "ASK {}"}, headers={},
            transport=lambda *_a, **_k: _JsonBody("application/sparql-results+json"),
        )
```

In `fetch_json_api`, add the parameter `accept: tuple[str, ...] = ("application/json",)`. Replace `"Accept": "application/json",` with `"Accept": ", ".join(accept),`, and replace `if content_type != "application/json":` with `if content_type not in accept:`. Add one docstring line: "`accept` widens the content types a caller will parse (SPARQL's `application/sparql-results+json`); the default is unchanged."

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_egress.py -q 2>&1 | tail -3`. Expected: all pass. Commit:

```bash
git add apps/research/egress.py tests/research/test_egress.py
git commit -m "feat(research): fetch_json_api names the JSON dialects a caller parses"
```

- [ ] **Step 2: Setting and enumeration rows**

`config/settings/base.py`:

```python
# Wikimedia's User-Agent policy requires a contact; a generic client string is
# throttled or refused. Operator-run enumeration only (apps/research/wikidata.py).
WIKIDATA_USER_AGENT = os.getenv(
    "WIKIDATA_USER_AGENT",
    "tehsil-agent-enumerator/1.0 (https://github.com/0rkhann/tehsil_agent)",
)
```

`docs/research/wikidata-enumerations.csv`:

```csv
slug,country_code,class_qid,class_label,kind,widen,min_count,max_count,home_cells,host_cells
wd_tr_university,TR,Q3918,university,INSTITUTION,no,150,400,ANY,TR
wd_az_university,AZ,Q3918,university,INSTITUTION,no,10,200,ANY,AZ
```

The TR bounds rest on the 229 that §6.2 measured. The AZ bounds are wide because nothing has been measured there. They are tightened to ×0.5–×2 of the first live count in Step 6. Add one registry row per enumeration to `closed-lists.csv`, for example `wd_tr_university,Wikidata -- universities with an official website (P31 Q3918 × P17 × P856),TR,INSTITUTION,0,https://query.wikidata.org/,Wikidata community,no,yes,OPEN,https://www.wikidata.org/wiki/Wikidata:Licensing,no,ENUMERATE_ONLY,,2026-09-25`.

- [ ] **Step 3: Implement `apps/research/wikidata.py`**

```python
"""Wikidata as an enumerator: class x country x official website (spec 6.2).

CC0. Writes CANDIDATE only -- crowd-sourced, it names bodies and never vouches
for them; a curated list promotes (closed_lists.py). Also the resolver's first
stop (P856, spec 6.5), which is build item 8's to wire, not this module's.

Pinned, and quoted here because spec 6.2's Wikidata row requires it:
- class: `wdt:P31 wd:<class>` -- a direct instance -- unless the row says
  `widen`, which walks `wdt:P31/wdt:P279*`. Türkiye has 229 universities with
  a website under the direct class and 366 when widened (spec 6.2).
- dissolved filter: `FILTER NOT EXISTS { ?item wdt:P576 ?ended }` -- P576 is
  "dissolved, abolished or demolished date"; a body with one is not a body a
  student can apply to.
- website requirement: `wdt:P856` must exist -- the website is the key
  `record_organisation` binds on, and a row without one binds nothing.
- country: `?country wdt:P297 "<ISO2>"`, so no country QID is written anywhere.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction

from .closed_lists import DATA_DIR, valid_cell
from .domains import is_catalogue
from .egress import fetch_json_api
from .hosts import registrable_domain
from .models import Organisation, RegisterEntry
from .register import record_organisation

ENDPOINT = "https://query.wikidata.org/sparql"
ENUMERATIONS = DATA_DIR / "wikidata-enumerations.csv"
_ISO2 = re.compile(r"^[A-Z]{2}$")
_QID = re.compile(r"^Q[0-9]+$")
_ENTITY = "http://www.wikidata.org/entity/"
_SPARQL = """SELECT ?item ?website (SAMPLE(?en) AS ?name)
       (GROUP_CONCAT(DISTINCT ?label; separator="\\t") AS ?labels) WHERE {{
  ?country wdt:P297 "{country}" .
  ?item wdt:P31{widen} wd:{klass} ;
        wdt:P17 ?country ;
        wdt:P856 ?website .
  FILTER NOT EXISTS {{ ?item wdt:P576 ?ended }}
  OPTIONAL {{ ?item rdfs:label ?label }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
}} GROUP BY ?item ?website"""


class EnumerationShape(ValueError):
    """A count outside the row's bounds: a changed class, a dropped filter."""


@dataclass(frozen=True)
class EnumerationRow:
    slug: str
    country_code: str
    class_qid: str
    kind: str
    widen: bool
    min_count: int
    max_count: int
    home_cells: tuple[str, ...]
    host_cells: tuple[str, ...]


@dataclass(frozen=True)
class Item:
    qid: str
    name: str
    labels: tuple[str, ...]
    websites: tuple[str, ...]


@dataclass(frozen=True)
class EnumerationReport:
    listed: int = 0
    bound: int = 0
    conflicts: int = 0
    unkeyable: int = 0


def read_enumerations(path: Path = ENUMERATIONS) -> tuple[EnumerationRow, ...]:
    rows: list[EnumerationRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            home = tuple(raw["home_cells"].split("|"))
            host = tuple(raw["host_cells"].split("|"))
            if not all(valid_cell(cell) for cell in (*home, *host)):
                raise ValueError(f"{raw['slug']}: bad cell tags")
            rows.append(EnumerationRow(
                slug=raw["slug"], country_code=raw["country_code"], class_qid=raw["class_qid"],
                kind=raw["kind"], widen=raw["widen"] == "yes", min_count=int(raw["min_count"]),
                max_count=int(raw["max_count"]), home_cells=home, host_cells=host,
            ))
    return tuple(rows)


def query_text(row: EnumerationRow) -> str:
    # Our own data, but it is still interpolated into a query language: refuse
    # anything that is not exactly an ISO code and a QID.
    if not _ISO2.match(row.country_code) or not _QID.match(row.class_qid):
        raise ValueError(f"{row.slug}: country {row.country_code!r} / class {row.class_qid!r}")
    return _SPARQL.format(
        country=row.country_code, klass=row.class_qid, widen="/wdt:P279*" if row.widen else ""
    )


def _value(binding: dict[str, dict[str, str]], key: str) -> str:
    return str(binding.get(key, {}).get("value", ""))


def parse_bindings(body: dict[str, object]) -> tuple[Item, ...]:
    """One Item per QID. An item with two websites arrives as two bindings,
    and both websites are kept -- each becomes a domain of the same body."""
    results = body.get("results")
    bindings = results.get("bindings", []) if isinstance(results, dict) else []
    names: dict[str, str] = {}
    labels: dict[str, list[str]] = {}
    websites: dict[str, list[str]] = {}
    for binding in bindings:
        qid = _value(binding, "item").removeprefix(_ENTITY)
        seen_labels = labels.setdefault(qid, [])
        seen_sites = websites.setdefault(qid, [])
        site = _value(binding, "website")
        if site and site not in seen_sites:
            seen_sites.append(site)
        if not names.get(qid):
            names[qid] = _value(binding, "name")
        for label in _value(binding, "labels").split("\t"):
            if label and label not in seen_labels:
                seen_labels.append(label)
    return tuple(
        Item(
            qid=qid,
            name=names[qid] or (labels[qid] or [qid])[0],
            labels=tuple(labels[qid]),
            websites=tuple(websites[qid]),
        )
        for qid in labels
    )


def fetch_items(
    row: EnumerationRow, *, call: Callable[..., dict[str, object]] = fetch_json_api
) -> tuple[Item, ...]:
    body = call(
        ENDPOINT,
        params={"query": query_text(row), "format": "json"},
        headers={"User-Agent": settings.WIKIDATA_USER_AGENT},
        read_timeout=65.0,
        accept=("application/sparql-results+json", "application/json"),
    )
    items = parse_bindings(body)
    if not row.min_count <= len(items) <= row.max_count:
        raise EnumerationShape(
            f"{row.slug}: {len(items)} items outside {row.min_count}-{row.max_count}"
        )
    return items


def record_items(row: EnumerationRow, items: tuple[Item, ...], *, now: datetime) -> EnumerationReport:
    listed = bound = conflicts = unkeyable = 0
    for item in items:
        listed += 1
        domains = list(dict.fromkeys(
            domain for website in item.websites
            if not is_catalogue(urlsplit(website).hostname or "")
            and (domain := registrable_domain(website))
        ))
        entry, _ = RegisterEntry.objects.update_or_create(
            register=row.slug, external_key=item.qid,
            defaults={
                "name": item.name[:300], "kind": row.kind, "country_code": row.country_code,
                "home_cells": list(row.home_cells), "host_cells": list(row.host_cells),
                "resolution": RegisterEntry.Resolution.UNRESOLVED, "last_seen": now,
            },
        )
        if not domains:
            unkeyable += 1
            continue
        try:
            with transaction.atomic():
                for domain in domains:
                    org = record_organisation(
                        domain=domain, name=item.name[:300], names=item.labels, kind=row.kind,
                        country_code=row.country_code, found_via=f"WIKIDATA:{row.slug}",
                        identifiers=[("WIKIDATA", item.qid)],
                        status=Organisation.Status.CANDIDATE,
                    )
        except ValueError:
            # One QID already on another body: a question, not a merge.
            entry.resolution, entry.organisation = RegisterEntry.Resolution.CONFLICT, None
            entry.save(update_fields=["resolution", "organisation"])
            conflicts += 1
            continue
        entry.resolution, entry.organisation = RegisterEntry.Resolution.RESOLVED, org
        entry.save(update_fields=["resolution", "organisation"])
        bound += 1
    return EnumerationReport(listed, bound, conflicts, unkeyable)
```

Keep `is_catalogue` on the P856 host. Wikidata's P856 sometimes holds a Facebook page, and `is_catalogue` refuses social hosts as keys (§6.4).

```python
# apps/research/management/commands/enumerate_wikidata.py
"""Enumerate docs/research/wikidata-enumerations.csv into the register (CANDIDATE only)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import wikidata
from apps.research.egress import SourceBlocked
from apps.research.fetch import CATALOG_ROLE_NOTE


class Command(BaseCommand):
    help = "Enumerate Wikidata class x country x P856 into the register." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--slug", action="append", default=[], dest="slugs")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        now, failed = timezone.now(), []
        for row in wikidata.read_enumerations():
            if options["slugs"] and row.slug not in options["slugs"]:
                continue
            try:
                items = wikidata.fetch_items(row)
            except (wikidata.EnumerationShape, SourceBlocked) as error:
                self.stderr.write(f"{row.slug}: {error}")
                failed.append(row.slug)
                continue
            if options["dry_run"]:
                self.stdout.write(f"{row.slug}: items {len(items)} (dry run, nothing written)")
                continue
            report = wikidata.record_items(row, items, now=now)
            self.stdout.write(
                f"{row.slug}: items {report.listed}, bound {report.bound}, "
                f"conflicts {report.conflicts}, unkeyable {report.unkeyable}"
            )
        if failed:
            raise CommandError(f"failed: {', '.join(failed)}")
```

`enumerate_ror` (Task 11), `enumerate_eacea` (Task 9) and `ror_gate` (Task 10) follow this shape: a loop over the data rows, the adapter's shape error caught per row, `--dry-run` where it writes, and a `CommandError` naming every failed row at the end.

- [ ] **Step 4: Capture the fixture live**

```bash
QUERY=$(uv run python -c "from apps.research.wikidata import query_text, EnumerationRow; print(query_text(EnumerationRow('wd_tr_university','TR','Q3918','INSTITUTION',False,150,400,('ANY',),('TR',))))")
curl -sS -G https://query.wikidata.org/sparql --data-urlencode "query=$QUERY" --data-urlencode format=json \
  -H 'Accept: application/sparql-results+json' \
  -A 'tehsil-agent-enumerator/1.0 (https://github.com/0rkhann/tehsil_agent)' -o /tmp/wd_tr.json
uv run python -c "import json; b=json.load(open('/tmp/wd_tr.json')); print(len(b['results']['bindings'])); b['results']['bindings']=b['results']['bindings'][:3]; json.dump(b, open('tests/research/fixtures/wikidata_tr_university.json','w'), ensure_ascii=False, indent=1)"
```

Record the printed full count in the commit message. It is the first measurement of the pinned class, to set against §6.2's 229.

- [ ] **Step 5: Tests on the fixture**

```python
# tests/research/test_wikidata.py
import json
from pathlib import Path

import pytest
from django.utils import timezone

from apps.research.models import Organisation, RegisterEntry
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db
FIXTURE = Path(__file__).parent / "fixtures" / "wikidata_tr_university.json"


def _row(**overrides: object):
    from apps.research.wikidata import EnumerationRow

    fields: dict[str, object] = dict(
        slug="wd_tr_university", country_code="TR", class_qid="Q3918", kind="INSTITUTION",
        widen=False, min_count=1, max_count=10, home_cells=("ANY",), host_cells=("TR",),
    )
    fields.update(overrides)
    return EnumerationRow(**fields)  # type: ignore[arg-type]


def test_the_query_pins_class_dissolution_and_website() -> None:
    from apps.research.wikidata import query_text

    text = query_text(_row())
    assert "wdt:P31 wd:Q3918" in text and "P279" not in text
    assert "FILTER NOT EXISTS { ?item wdt:P576 ?ended }" in text
    assert "wdt:P856 ?website" in text and 'wdt:P297 "TR"' in text
    assert "wdt:P31/wdt:P279* wd:Q3918" in query_text(_row(widen=True))


def test_the_query_refuses_anything_but_an_iso_code_and_a_qid() -> None:
    from apps.research.wikidata import query_text

    with pytest.raises(ValueError):
        query_text(_row(country_code='TR" } #'))
    with pytest.raises(ValueError):
        query_text(_row(class_qid="Q1 ; DROP"))


def test_the_recorded_response_parses_and_binds_candidates() -> None:
    from apps.research.wikidata import parse_bindings, record_items

    items = parse_bindings(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert items and all(item.qid.startswith("Q") and item.websites for item in items)
    report = record_items(_row(), items, now=timezone.now())
    assert report.bound == len(items)
    org = RegisterEntry.objects.filter(register="wd_tr_university").first().organisation
    assert org is not None and org.status == Organisation.Status.CANDIDATE
    assert org.identifiers.filter(scheme="WIKIDATA").exists()
    assert len(org.names) >= 1


def test_a_count_outside_the_bounds_stops_the_row() -> None:
    from apps.research.wikidata import EnumerationShape, fetch_items

    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(EnumerationShape):
        fetch_items(_row(min_count=100, max_count=400), call=lambda *_a, **_k: body)


def test_a_qid_already_on_another_body_is_a_conflict_not_a_merge() -> None:
    from apps.research.wikidata import Item, record_items

    record_organisation(domain="a.edu.tr", name="A", kind="INSTITUTION", country_code="TR",
                        found_via="x", identifiers=[("WIKIDATA", "Q1")])
    record_organisation(domain="b.edu.tr", name="B", kind="INSTITUTION", country_code="TR",
                        found_via="x")
    report = record_items(
        _row(), (Item("Q1", "B University", ("B University",), ("https://b.edu.tr",)),),
        now=timezone.now(),
    )
    assert report.conflicts == 1
    assert RegisterEntry.objects.get(external_key="Q1").resolution == "CONFLICT"
```

The last test works because `record_organisation` finds `b.edu.tr` by domain and then raises on attaching `Q1`, which `a.edu.tr` already holds.

Run: `POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_wikidata.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"`. Expected: all pass.

- [ ] **Step 6: Live dry run, tighten bounds, add rows, commit**

```bash
POSTGRES_DB=tehsil_enumerators uv run python manage.py enumerate_wikidata --dry-run
```

Set each row's `min_count`/`max_count` to half and double the printed count. Then add rows for the classes the set-difference report needs, for both countries: `Q157031` foundation → `PRIVATE_FOUNDATION`; `Q327333` government agency and `Q192350` ministry → `NATIONAL_GOVERNMENT`; `Q22687` bank → `BANK_OR_LENDER`. Dry-run them and bound them the same way, and give each a registry row with `is_denominator=no`.

```bash
grep -c "@" tests/research/fixtures/wikidata_tr_university.json   # expect 0
git add apps/research/wikidata.py apps/research/management/commands/enumerate_wikidata.py docs/research/wikidata-enumerations.csv docs/research/closed-lists.csv tests/research/test_wikidata.py tests/research/fixtures/wikidata_tr_university.json config/settings/base.py
git commit -m "feat(research): Wikidata enumerator -- class x country x P856, CANDIDATE only, bounded"
```

---

### Task 8: The Türkiye and Azerbaijan curated lists, loaded and read

**Files:**
- Create: `docs/research/closed-lists/<slug>.csv` for each list the survey (Task 6) found at rungs 1–3
- Modify: `docs/research/closed-lists.csv`, `docs/research/register-survey.csv` (`closed_list_slug`)

- [ ] **Step 1: Which lists**

One curated list per (country, family) the survey found at rungs 1–3, using exactly these slugs and policies:

| slug | kind | read policy | cells (home → host) |
|---|---|---|---|
| `tr_outbound_gov`, `az_outbound_gov` | `NATIONAL_GOVERNMENT` (decision 35: one row per scheme; the ministry's page is the hub) | `FUNDING_READ` | the country → `ANY`, or the hosts the scheme names |
| `tr_bilateral`, `az_bilateral` | `EMBASSY_BILATERAL` (one row per host scheme open to that nationality; the body is the host's awarding agency) | `FUNDING_READ` | the country → the host |
| `tr_heis`, `az_heis` | `INSTITUTION` | `CLASSIFY` | `ANY` → the country |
| `tr_banks`, `az_banks` | `BANK_OR_LENDER` | `SIGNAL_ONLY` | the country → `ANY` |
| `tr_professional_bodies`, `az_professional_bodies` | `PROFESSIONAL_BODY` | `SIGNAL_ONLY` | the country → `ANY` |

Where the survey recorded rung 4 for a family, no file is written, and the survey row is the record. For every list the publisher prints a count on (the HEI authority's count, the regulator's count), `printed_size` is that number. For a compiled list, it is blank.

- [ ] **Step 2: Compile each file from its `list_url`, by hand**

Use the column rules from Task 5 Step 2. One row per body the list names. `website` is the body's own site, as the list prints it or as the body's own page states it. Never guess a domain from a name. A row whose site cannot be established is left with `website` empty, and it stays `UNRESOLVED` until the resolver (item 8) gets to it. `source_url` is the list page. No e-mail address, no named person.

- [ ] **Step 3: Load, then run the data tests**

```bash
DATABASE_ROLE=migration POSTGRES_DB=tehsil_enumerators uv run python manage.py load_closed_lists
POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_closed_list_data.py tests/research/test_register_survey.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
```

- [ ] **Step 4: Read what each policy says to read**

```bash
# FUNDING_READ lists: the scheme pages through the reader (≈ $0.35 a page; ~40 pages across the four lists)
DATABASE_ROLE=migration uv run python manage.py read_closed_list --list igo_regional_global --tenant <platform tenant uuid> --max-leads 60
DATABASE_ROLE=migration uv run python manage.py read_closed_list --list tr_outbound_gov --tenant <platform tenant uuid>
DATABASE_ROLE=migration uv run python manage.py read_closed_list --list az_outbound_gov --tenant <platform tenant uuid>
DATABASE_ROLE=migration uv run python manage.py read_closed_list --list tr_bilateral --tenant <platform tenant uuid>
DATABASE_ROLE=migration uv run python manage.py read_closed_list --list az_bilateral --tenant <platform tenant uuid>
# CLASSIFY lists: the homepage through the classifier (one Firecrawl credit and ~$0.002 a host)
DATABASE_ROLE=migration uv run python manage.py classify_organisations --found-via R1_LIST:tr_heis --limit 400 --firecrawl-credits 400
DATABASE_ROLE=migration uv run python manage.py classify_organisations --found-via R1_LIST:az_heis --limit 200 --firecrawl-credits 200
```

`<platform tenant uuid>` is the platform (master-agency) tenant's id, taken from the owner console's tenant, because consultant tasks for blocked pages are filed there. The `R1_` prefix is the list's `rung`. If the survey placed an HEI list at a different rung, the tag follows that rung. Check with `closed_list_coverage`, which prints the slug, and `SELECT found_via FROM research_organisation LIMIT 1`.

Free-tier budgets (§13) cap Firecrawl at 1,000 credits a month. If a run stops on `BUDGET`, the affected entries read `UNREAD (budget)` and the gate fails, which is correct. Re-run when credits return. Never raise a cap to force a pass.

- [ ] **Step 5: Commit the lists**

```bash
grep -c "@" docs/research/closed-lists/*.csv   # expect 0 everywhere
git add docs/research/closed-lists/ docs/research/closed-lists.csv docs/research/register-survey.csv
git commit -m "docs(research): Türkiye and Azerbaijan closed lists -- government, bilateral, institutions, banks, professional bodies"
```

---

### Task 9: EACEA — every EMJM, and the partner binding

**Files:**
- Create: `apps/research/eacea.py`, `apps/research/management/commands/enumerate_eacea.py`, `docs/research/eacea-actions.csv`, `tests/research/test_eacea.py`, `tests/research/fixtures/eacea_emjm_page.json`

**Interfaces:**
- `eacea.ActionRow(code, label, index, min_total, max_total)`; `read_actions(path)`; `payload(row, start, size) -> dict`; `organisations_in(node) -> Iterator[dict]`; `project_fields(project) -> ProjectFields`; `fetch_projects(row, *, call=fetch_json_api, size=100) -> tuple[int, list[dict]]`; `bind_partner(org_row) -> tuple[Organisation | None, str]`; `record_projects(projects, *, now) -> EaceaReport`; `TotalShape`.

- [ ] **Step 1: Action codes as data**

```csv
code,label,index,min_total,max_total
43690363,Erasmus Mundus Joint Master (2021-2027),eplus2021,100,1000
31046261,Erasmus Mundus Joint Master Degrees (2014-2020),eplus2021,100,1000
```

The bounds rest on the 166 and 249 measured on 2026-09-15. **A total in the hundreds of thousands means the filter was silently ignored** (`level3` and `actionType` are accepted and do nothing; the unfiltered corpus is 341,611). That must be a stop, never a load. The `index` for the 2014–2020 code is the value the 09-14 measurement used. If Step 2's capture shows it answering zero under `eplus2021`, change it to what the platform's own search sends for that programme period and record that in the commit.

- [ ] **Step 2: Capture one page live, and read its shape before writing code**

```bash
curl -sS -X POST https://ec.europa.eu/programmes/service/search/project/search \
  -H 'Content-Type: application/json' -H 'Origin: https://erasmus-plus.ec.europa.eu' \
  -H 'Referer: https://erasmus-plus.ec.europa.eu/' \
  -d '{"from":0,"index":"eplus2021","keyword":"","matchAllCountries":false,"project":{"projectLevel3":"43690363"},"coordinator":{},"partner":{},"organisation":{"organisationRole":"COORDINATOR_OR_PARTNER"},"size":2,"sort":"","withAggregations":false}' \
  -o /tmp/eacea.json
uv run python -c "
import json; b=json.load(open('/tmp/eacea.json'))
print('top keys:', sorted(b)); print('total:', b.get('total'))
def walk(n, p=''):
    if isinstance(n, dict):
        if 'organisationPIC' in n: print('org at', p, sorted(n)); return
        [walk(v, f'{p}.{k}') for k, v in n.items()]
    elif isinstance(n, list) and n: walk(n[0], p + '[0]')
walk(b)"
```

Write down three things from the output: where the project list sits, the project's identifier, title and date keys, and where the organisation dicts sit. Organisation keys are documented verbatim (09-14 §3): `organisationName`, `organisationPIC`, `organisationCountry`, `organisationCity`, `organisationWebsite`, `organisationRole`. Trim the capture to two projects. **Delete every key the adapter will not read**, and grep for `@`, `contact`, `person`, `phone` and `email`, all of which must be absent. Save it as `tests/research/fixtures/eacea_emjm_page.json`.

- [ ] **Step 3: Write the failing tests**

```python
# tests/research/test_eacea.py
"""Every EMJM from the funder's own records, and each partner bound PIC-first
(spec 6.2's EACEA row; docs/superpowers/specs/2026-09-14-emjm-partner-source-design.md)."""

import json
from pathlib import Path

import pytest
from django.utils import timezone

from apps.research.models import RegisterEntry, RegisterEntryPartner
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db
FIXTURE = Path(__file__).parent / "fixtures" / "eacea_emjm_page.json"


def _action(**overrides: object):
    from apps.research.eacea import ActionRow

    fields: dict[str, object] = dict(code="43690363", label="EMJM", index="eplus2021",
                                     min_total=1, max_total=1000)
    fields.update(overrides)
    return ActionRow(**fields)  # type: ignore[arg-type]


def test_the_payload_filters_on_projectLevel3_never_level3() -> None:
    """level3 and actionType are accepted and silently ignored -- the whole
    corpus comes back looking like a filtered answer (CLAUDE.md)."""
    from apps.research.eacea import payload

    body = payload(_action(), start=0, size=100)
    assert body["project"] == {"projectLevel3": "43690363"}
    assert "level3" not in json.dumps(body) and "actionType" not in json.dumps(body)


def test_a_total_in_the_hundreds_of_thousands_is_a_stop() -> None:
    from apps.research.eacea import TotalShape, fetch_projects

    with pytest.raises(TotalShape, match="341611"):
        fetch_projects(_action(), call=lambda *_a, **_k: {"total": 341611})


def test_the_recorded_page_yields_projects_with_partners() -> None:
    from apps.research.eacea import organisations_in, project_fields, projects_in

    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    projects = projects_in(body)
    assert len(projects) == 2
    fields = project_fields(projects[0])
    assert fields.identifier and fields.title
    orgs = list(organisations_in(projects[0]))
    assert orgs and all(org["organisationPIC"] for org in orgs)


def _org(pic: str, website: str = "", name: str = "UNIVERSITE X", role: str = "partner"):
    return {"organisationName": name, "organisationPIC": pic, "organisationCountry": "BE",
            "organisationCity": "LIEGE", "organisationWebsite": website,
            "organisationRole": role}


def test_pic_is_primary_and_the_website_attaches_to_its_body() -> None:
    from apps.research.eacea import bind_partner

    held = record_organisation(domain="uliege.be", name="ULiège", kind="INSTITUTION",
                               country_code="BE", found_via="x",
                               identifiers=[("EACEA_PIC", "999884732")])
    org, disposition = bind_partner(_org("999884732", "www.ulg.ac.be"))
    assert (org, disposition) == (held, "BOUND_PIC")
    assert held.domains.filter(registrable_domain="ulg.ac.be").exists()


def test_two_keys_naming_two_bodies_is_a_conflict_and_binds_neither() -> None:
    """EDEX (09-14 4.3): the PIC is registered against one university, the
    website belongs to another. No rule settles it; a person does."""
    from apps.research.eacea import bind_partner

    record_organisation(domain="euc.ac.cy", name="EUC", kind="INSTITUTION", country_code="CY",
                        found_via="x", identifiers=[("EACEA_PIC", "111")])
    record_organisation(domain="unic.ac.cy", name="UNIC", kind="INSTITUTION",
                        country_code="CY", found_via="x")
    assert bind_partner(_org("111", "https://www.unic.ac.cy")) == (None, "CONFLICT")


def test_no_website_and_an_unknown_pic_is_silence_counted() -> None:
    from apps.research.eacea import bind_partner

    assert bind_partner(_org("222")) == (None, "NO_KEY")


def test_a_new_partner_is_a_candidate_of_unstated_kind() -> None:
    """EACEA cannot say a partner awards degrees -- CNR, CEPS and NGOs are
    partners too (09-14 8) -- so the kind is left for the classifier."""
    from apps.research.eacea import bind_partner

    org, disposition = bind_partner(_org("333", "https://www.cnr.it", name="CNR"))
    assert disposition == "NEW" and org is not None
    assert (org.status, org.kind, org.country_code) == ("CANDIDATE", "UNSTATED", "BE")


def test_recording_writes_one_entry_per_project_and_one_row_per_partner() -> None:
    from apps.research.eacea import projects_in, record_projects

    projects = projects_in(json.loads(FIXTURE.read_text(encoding="utf-8")))
    report = record_projects(projects, now=timezone.now())
    assert RegisterEntry.objects.filter(register="eacea_emjm").count() == 2 == report.projects
    assert RegisterEntryPartner.objects.count() == report.partners > 0
    again = record_projects(projects, now=timezone.now())
    assert RegisterEntryPartner.objects.count() == again.partners
```

- [ ] **Step 4: Implement `apps/research/eacea.py`**

```python
"""Every Erasmus Mundus Joint Master, from the funder's own records (spec 6.2).

`POST ec.europa.eu/programmes/service/search/project/search`, filtered on
`projectLevel3` with both action codes (docs/research/eacea-actions.csv). The
complete EMJM list: every EMJM is an EU-funded project. Europa reuse notice,
so persisting what it returns is permitted -- and that does not generalise to
a search provider (CLAUDE.md).

What it answers alone: the projects, their funded period, and each project's
coordinator and partners (name, country, city, EU-PIC, website). What it does
not: which `Program` row a project is (a person, 09-14 section 8), and whether
a partner awards degrees (it records CNR and NGOs too) -- so every partner is
a CANDIDATE of kind UNSTATED for the classifier.

The partner binding is the 09-14 design's, against OUR register rather than
DEQAR's (CLAUDE.md, "two designs this supersedes in part"): EU-PIC first, the
website second, and two keys naming two bodies is a question for a person.
DEQAR's succession walk is not here, so a partner that merged binds to
whichever body holds its old PIC or domain -- the limit the gate report names.

Shape: the organisation keys below are the ones 09-14 section 3 records
verbatim. The project keys were read off the capture in
tests/research/fixtures/eacea_emjm_page.json on the day this was written.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from django.db import transaction

from .closed_lists import DATA_DIR
from .egress import fetch_json_api
from .hosts import registrable_domain
from .models import (
    ClosedList, Organisation, OrganisationDomain, OrganisationIdentifier, RegisterEntry,
    RegisterEntryPartner,
)
from .register import record_organisation

ENDPOINT = "https://ec.europa.eu/programmes/service/search/project/search"
ACTIONS = DATA_DIR / "eacea-actions.csv"
REGISTER = "eacea_emjm"
_HEADERS = {
    "Origin": "https://erasmus-plus.ec.europa.eu",
    "Referer": "https://erasmus-plus.ec.europa.eu/",
}
_ORG_MARK = "organisationPIC"
#: Set from the Step 2 capture -- one key each. A tuple of guesses left here is
#: a review finding: the capture is the authority, not this list.
_PROJECT_ID = "projectIdentifier"
_PROJECT_TITLE = "title"
_PROJECT_START = "startDate"
_PROJECT_END = "endDate"
Disposition = RegisterEntryPartner.Disposition


class TotalShape(ValueError):
    """A total outside the action's bounds -- the silent-filter trap."""


@dataclass(frozen=True)
class ActionRow:
    code: str
    label: str
    index: str
    min_total: int
    max_total: int


@dataclass(frozen=True)
class ProjectFields:
    identifier: str
    title: str
    start: date | None
    end: date | None


@dataclass(frozen=True)
class EaceaReport:
    projects: int = 0
    partners: int = 0
    by_disposition: tuple[tuple[str, int], ...] = ()


def read_actions(path: Path = ACTIONS) -> tuple[ActionRow, ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(
            ActionRow(row["code"], row["label"], row["index"], int(row["min_total"]),
                      int(row["max_total"]))
            for row in csv.DictReader(handle)
        )


def payload(row: ActionRow, *, start: int, size: int) -> dict[str, object]:
    return {
        "from": start, "index": row.index, "keyword": "", "matchAllCountries": False,
        "project": {"projectLevel3": row.code}, "coordinator": {}, "partner": {},
        "organisation": {"organisationRole": "COORDINATOR_OR_PARTNER"},
        "size": size, "sort": "", "withAggregations": False,
    }


def organisations_in(node: object) -> Iterator[dict[str, object]]:
    """Every organisation dict under `node`, found by its documented key, so
    the walk does not depend on where the response nests them."""
    if isinstance(node, dict):
        if _ORG_MARK in node:
            yield node
            return
        for value in node.values():
            yield from organisations_in(value)
    elif isinstance(node, list):
        for value in node:
            yield from organisations_in(value)


def projects_in(body: dict[str, object]) -> list[dict[str, object]]:
    """The response's project list: the top-level list whose items hold
    organisations."""
    for value in body.values():
        if isinstance(value, list) and value and any(organisations_in(value[0])):
            return [item for item in value if isinstance(item, dict)]
    return []


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def project_fields(project: dict[str, object]) -> ProjectFields:
    return ProjectFields(
        identifier=str(project.get(_PROJECT_ID, "")),
        title=str(project.get(_PROJECT_TITLE, ""))[:300],
        start=_day(project.get(_PROJECT_START)),
        end=_day(project.get(_PROJECT_END)),
    )


def fetch_projects(
    row: ActionRow, *, call: Callable[..., dict[str, object]] = fetch_json_api, size: int = 100
) -> tuple[int, list[dict[str, object]]]:
    """Every project under one action code, with the total asserted first."""
    projects: list[dict[str, object]] = []
    start, total = 0, None
    while total is None or start < total:
        body = call(ENDPOINT, payload=payload(row, start=start, size=size), headers=_HEADERS)
        if total is None:
            total = int(str(body.get("total", -1)))
            if not row.min_total <= total <= row.max_total:
                raise TotalShape(
                    f"{row.code}: total {total} outside {row.min_total}-{row.max_total}"
                )
        page = projects_in(body)
        if not page:
            break
        projects.extend(page)
        start += size
    return total or 0, projects


def _held_by_pic(pic: str) -> Organisation | None:
    row = OrganisationIdentifier.objects.select_related("organisation").filter(
        scheme="EACEA_PIC", value=pic
    ).first()
    return row.organisation if row else None


def _held_by_domain(domain: str) -> Organisation | None:
    row = OrganisationDomain.objects.select_related("organisation").filter(
        registrable_domain=domain
    ).first()
    return row.organisation if row else None


def bind_partner(org_row: dict[str, object]) -> tuple[Organisation | None, str]:
    """One participating organisation -> (body, disposition). PIC first."""
    pic = str(org_row.get("organisationPIC", "")).strip()
    website = str(org_row.get("organisationWebsite", "") or "").strip()
    domain = registrable_domain(website) if website else ""
    by_pic = _held_by_pic(pic) if pic else None
    by_domain = _held_by_domain(domain) if domain else None
    if by_pic and by_domain and by_pic.pk != by_domain.pk:
        return None, Disposition.CONFLICT
    if not domain:
        return (by_pic, Disposition.BOUND_PIC) if by_pic else (None, Disposition.NO_KEY)
    name = str(org_row.get("organisationName", "")).strip()[:300] or domain
    org = record_organisation(
        domain=domain, name=name, names=(name,), kind="UNSTATED",
        country_code=str(org_row.get("organisationCountry", "")).strip().upper()[:2],
        found_via="EACEA:emjm", identifiers=[("EACEA_PIC", pic)] if pic else (),
        status=Organisation.Status.CANDIDATE,
    )
    if by_pic and by_domain:
        return org, Disposition.BOUND_BOTH
    if by_pic:
        return org, Disposition.BOUND_PIC
    if by_domain:
        return org, Disposition.BOUND_DOMAIN
    return org, Disposition.NEW


def record_projects(projects: list[dict[str, object]], *, now: datetime) -> EaceaReport:
    tally: dict[str, int] = {}
    project_count = partner_count = 0
    for project in projects:
        fields = project_fields(project)
        if not fields.identifier:
            continue
        project_count += 1
        with transaction.atomic():
            entry, _ = RegisterEntry.objects.update_or_create(
                register=REGISTER, external_key=fields.identifier[:120],
                defaults={
                    "name": fields.title or fields.identifier, "listed_from": fields.start,
                    "listed_until": fields.end, "home_cells": ["ANY"], "host_cells": ["ANY"],
                    "resolution": RegisterEntry.Resolution.UNRESOLVED, "last_seen": now,
                },
            )
            for org_row in organisations_in(project):
                pic = str(org_row.get("organisationPIC", "")).strip()
                if not pic:
                    continue
                org, disposition = bind_partner(org_row)
                role = str(org_row.get("organisationRole", "")).upper()[:12]
                RegisterEntryPartner.objects.update_or_create(
                    entry=entry, listed_identifier=pic,
                    defaults={
                        "organisation": org, "role": role,
                        "listed_name": str(org_row.get("organisationName", ""))[:300],
                        "listed_domain": registrable_domain(
                            str(org_row.get("organisationWebsite", "") or "")
                        ),
                        "country_code": str(org_row.get("organisationCountry", ""))[:2],
                        "disposition": disposition,
                    },
                )
                partner_count += 1
                tally[disposition] = tally.get(disposition, 0) + 1
                if role == "COORDINATOR":
                    entry.organisation = org
                    entry.resolution = (
                        RegisterEntry.Resolution.CONFLICT if disposition == Disposition.CONFLICT
                        else RegisterEntry.Resolution.RESOLVED if org
                        else RegisterEntry.Resolution.UNRESOLVED
                    )
            entry.save(update_fields=["organisation", "resolution"])
    return EaceaReport(project_count, partner_count, tuple(sorted(tally.items())))


def set_printed_size(total: int) -> None:
    """The API's own total is the list's printed size -- 100% enumerated means
    entries == the sum across both action codes."""
    ClosedList.objects.filter(slug=REGISTER).update(printed_size=total)
```

If the capture shows `organisationRole` in another case, keep `.upper()`. The comparison is to `"COORDINATOR"` after upper-casing.

`enumerate_eacea` command: for each `read_actions()` row, `fetch_projects` (catch `TotalShape` and raise `CommandError`), `record_projects`, sum the totals, `set_printed_size(sum)`, and print `projects N / total T`, the disposition histogram, and `conflict share X%`. `--dry-run` fetches and prints without writing. Write runs under `DATABASE_ROLE=migration`.

- [ ] **Step 5: Run the tests, then live, then commit**

```bash
POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_eacea.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
DATABASE_ROLE=migration POSTGRES_DB=tehsil_enumerators uv run python manage.py enumerate_eacea
```

Expected live: two totals near 166 and 249, summed into `printed_size`, and one entry per project. The disposition histogram will **not** match the 09-14 table (277/137/47/…). That table joined against DEQAR, and this one joins against our own register, where most partners are `NEW` on a fresh database. The comparable number is the **conflict share**, which was measured at 1.0% (6 of 576). Above 2% on this population means the binding code is wrong, not the data: stop and read the conflicts.

```bash
grep -c -i -E "@|contact|person|phone|email" tests/research/fixtures/eacea_emjm_page.json   # expect 0
git add apps/research/eacea.py apps/research/management/commands/enumerate_eacea.py docs/research/eacea-actions.csv tests/research/test_eacea.py tests/research/fixtures/eacea_emjm_page.json
git commit -m "feat(research): every EMJM from EACEA's records; partners bound PIC-first, conflicts left to a person"
```

---

### Task 10: The ROR gate — measured before ROR writes anything

**Files:**
- Create: `apps/research/ror.py` (lookup and gate half), `apps/research/management/commands/ror_gate.py`, `docs/research/ror-gate-names.csv`, `tests/research/test_ror.py`, `tests/research/fixtures/ror_domain_metu.json`
- Modify: `config/settings/base.py` (`ROR_CLIENT_ID`)

§6.2: "**Gate before it enters a plan:** run against the 58 yield hosts and the pointer names; record the share known, exact-name share, website-matches-held-domain share." Pointer names are not persisted anywhere today (`DiscoveryReport.pointer_names` is returned and dropped). So the name set is assembled from pairs whose true domain we already know: every curated-list row from Tasks 5 and 8 (name, website domain), plus 50 `vgm_tr` rows resolved at rung 0 (name, e-mail domain).

**Pass rule, set here so it cannot be tuned afterwards:** for the 58 hosts, among the ROR records an exact `domains:` lookup returns, the share whose website resolves to the queried domain must be **≥ 95%**. Below that, ROR's website is not a key and Task 11 does not run. The known share and the exact-name share are **recorded, not gated**. They say how much of our register ROR covers, and whether ROR's name matching could serve item 8's resolver. This plan never looks ROR up by name.

- [ ] **Step 1: Setting, name file, capture**

`config/settings/base.py`: `ROR_CLIENT_ID = os.getenv("ROR_CLIENT_ID", "")`, with the comment "ROR v2 identifies heavy clients by a free client id sent as `Client-Id`; blank sends none."

Build the names file:

```bash
DATABASE_ROLE=migration POSTGRES_DB=tehsil_enumerators uv run python manage.py shell -c "
import csv, sys
from apps.research.models import RegisterEntry
w = csv.writer(sys.stdout); w.writerow(['name','domain','source'])
for e in RegisterEntry.objects.filter(register__in=['igo_regional_global','tr_heis','az_heis','tr_outbound_gov','az_outbound_gov'], organisation__isnull=False).select_related('organisation'):
    w.writerow([e.name, e.organisation.primary_domain, e.register])
for e in RegisterEntry.objects.filter(register='vgm_tr', resolution='RESOLVED').order_by('external_key')[:50]:
    w.writerow([e.name, e.contact_domain, 'vgm_tr'])
" > docs/research/ror-gate-names.csv
```

Capture `curl -sS 'https://api.ror.org/v2/organizations?query.advanced=domains:metu.edu.tr' -o tests/research/fixtures/ror_domain_metu.json` and check that it holds `items[0].id`, `names`, `domains`, `links` and `status`. If the response nests any of these differently, the code below follows the capture.

- [ ] **Step 2: Tests**

```python
# tests/research/test_ror.py
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db
FIX = Path(__file__).parent / "fixtures"


def test_website_domain_prefers_the_website_link() -> None:
    from apps.research.ror import website_domain

    record = {"links": [{"type": "wikipedia", "value": "https://en.wikipedia.org/x"},
                        {"type": "website", "value": "https://www.metu.edu.tr/"}],
              "domains": ["odtu.edu.tr"]}
    assert website_domain(record) == "metu.edu.tr"
    assert website_domain({"links": [], "domains": ["odtu.edu.tr"]}) == "odtu.edu.tr"


def test_the_recorded_domain_lookup_parses() -> None:
    from apps.research.ror import by_domain

    body = json.loads((FIX / "ror_domain_metu.json").read_text(encoding="utf-8"))
    records = by_domain("metu.edu.tr", call=lambda *_a, **_k: body)
    assert records and records[0]["id"].startswith("https://ror.org/")


def test_the_gate_passes_only_at_95_percent_website_agreement() -> None:
    from apps.research.ror import RorGate

    assert RorGate(hosts=58, known=20, website_match=19, names=0, name_known=0,
                   exact_name=0).passed
    assert not RorGate(hosts=58, known=20, website_match=18, names=0, name_known=0,
                       exact_name=0).passed
    assert not RorGate(hosts=58, known=0, website_match=0, names=0, name_known=0,
                       exact_name=0).passed
```

- [ ] **Step 3: Implement the lookup and gate half of `apps/research/ror.py`**

```python
"""ROR v2 as an enumerator -- gated (spec 6.2's ROR row).

CC0. Used two ways only: an exact `domains:` lookup, and a country x type
enumeration. Never a name lookup's top hit -- "the fuzzy top hit is sometimes
a different organisation" (spec 6.2) -- so the name half of the gate below
measures ROR's matching for item 8's resolver and nothing here uses it.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from .egress import fetch_json_api
from .hosts import registrable_domain

ENDPOINT = "https://api.ror.org/v2/organizations"
_PASS_SHARE = 0.95

Call = Callable[..., dict[str, object]]


def _headers() -> dict[str, str]:
    return {"Client-Id": settings.ROR_CLIENT_ID} if settings.ROR_CLIENT_ID else {}


def _items(body: dict[str, object]) -> list[dict[str, object]]:
    items = body.get("items", [])
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def by_domain(domain: str, *, call: Call = fetch_json_api) -> list[dict[str, object]]:
    return _items(call(ENDPOINT, params={"query.advanced": f"domains:{domain}"},
                       headers=_headers()))


def website_domain(record: dict[str, object]) -> str:
    for link in record.get("links", []) or []:  # type: ignore[union-attr]
        if isinstance(link, dict) and link.get("type") == "website" and link.get("value"):
            return registrable_domain(str(link["value"]))
    domains = record.get("domains", []) or []
    return registrable_domain(str(domains[0])) if domains else ""  # type: ignore[index]


def all_names(record: dict[str, object]) -> tuple[str, ...]:
    return tuple(
        str(name["value"]) for name in record.get("names", []) or []  # type: ignore[union-attr]
        if isinstance(name, dict) and name.get("value")
    )


@dataclass(frozen=True)
class RorGate:
    hosts: int
    known: int
    website_match: int
    names: int
    name_known: int
    exact_name: int
    #: Of the names ROR chose a record for, how many carry the website we
    #: know is the body's -- the number item 8's resolver needs. Not gated.
    name_website_match: int = 0

    @property
    def passed(self) -> bool:
        return self.known > 0 and self.website_match >= _PASS_SHARE * self.known


def ror_gate(hosts: list[str], names: list[tuple[str, str]], *, call: Call = fetch_json_api) -> RorGate:
    known = matched = 0
    for host in hosts:
        records = by_domain(host, call=call)
        if records:
            known += 1
            matched += website_domain(records[0]) == host
    name_known = exact = name_site = 0
    for name, domain in names:
        body = call(ENDPOINT, params={"affiliation": name}, headers=_headers())
        chosen = [
            item["organization"] for item in _items(body)
            if item.get("chosen") and isinstance(item.get("organization"), dict)
        ]
        if chosen:
            name_known += 1
            exact += name.casefold() in {label.casefold() for label in all_names(chosen[0])}
            name_site += website_domain(chosen[0]) == domain
    return RorGate(len(hosts), known, matched, len(names), name_known, exact, name_site)


def read_hosts(path: Path) -> list[str]:
    return [
        line.split("\t")[0].strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def read_names(path: Path) -> list[tuple[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [(row["name"], row["domain"]) for row in csv.DictReader(handle)]
```

Only ROR's own `chosen` flag counts as a name match. That is ROR's confident match rather than its top hit.

`ror_gate` command: it reads `docs/research/2026-09-18-yield-hosts.txt` and `docs/research/ror-gate-names.csv`, and prints each count and share, then `ROR GATE: PASS` or `ROR GATE: FAIL`. It never writes to the database.

- [ ] **Step 4: Run tests, run the gate live, commit**

```bash
POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_ror.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
uv run python manage.py ror_gate | tee /tmp/ror_gate.txt
git add apps/research/ror.py apps/research/management/commands/ror_gate.py docs/research/ror-gate-names.csv tests/research/test_ror.py tests/research/fixtures/ror_domain_metu.json config/settings/base.py
git commit -m "feat(research): the ROR gate -- website agreement on the 58 hosts, name matching measured for item 8"
```

Paste `/tmp/ror_gate.txt` into the commit body. **If the gate prints FAIL, skip Task 11** and record the numbers in Task 13's report.

---

### Task 11: ROR enumeration (only if Task 10 passed)

**Files:**
- Modify: `apps/research/ror.py` (enumeration half), `tests/research/test_ror.py`, `docs/research/closed-lists.csv`
- Create: `apps/research/management/commands/enumerate_ror.py`, `docs/research/ror-enumerations.csv`, `tests/research/fixtures/ror_country_tr_education.json`

- [ ] **Step 1: Rows and capture**

```csv
slug,country_code,type,kind,min_count,max_count,home_cells,host_cells
ror_tr_education,TR,education,INSTITUTION,120,480,ANY,TR
ror_az_education,AZ,education,INSTITUTION,25,110,ANY,AZ
ror_tr_funder,TR,funder,UNSTATED,1,500,TR,ANY
ror_az_funder,AZ,funder,UNSTATED,1,200,AZ,ANY
```

The education bounds are half and double of §6.2's measured 239 (TR) and 52 (AZ). The funder bounds are wide, and are tightened after the first `--dry-run` exactly as in Task 7 Step 6. Add one registry row per slug: `rung 0`, `is_denominator no`, `ENUMERATE_ONLY`, `OPEN`, source `https://ror.org/`, terms `https://ror.org/about/faqs/#what-is-the-license-for-ror-data`.

Capture `curl -sS 'https://api.ror.org/v2/organizations?filter=types:education,locations.geonames_details.country_code:TR&page=1'`, trim it to three items, and save it as `ror_country_tr_education.json`. Confirm that `number_of_results` sits at the top level.

- [ ] **Step 2: Test, then implement**

```python
# tests/research/test_ror.py -- append
def test_the_enumeration_binds_active_records_and_skips_inactive() -> None:
    from django.utils import timezone

    from apps.research.models import RegisterEntry
    from apps.research.ror import EnumerationRow, record_records

    body = json.loads((FIX / "ror_country_tr_education.json").read_text(encoding="utf-8"))
    records = body["items"]
    records[0] = {**records[0], "status": "inactive"}
    row = EnumerationRow("ror_tr_education", "TR", "education", "INSTITUTION", 1, 10,
                         ("ANY",), ("TR",))
    report = record_records(row, records, now=timezone.now())
    assert report.inactive == 1 and report.bound == len(records) - 1
    org = RegisterEntry.objects.filter(register="ror_tr_education", organisation__isnull=False
                                       ).first().organisation
    assert org.status == "CANDIDATE" and org.identifiers.filter(scheme="ROR").exists()
```

Append to `ror.py` the following. `EnumerationRow` has the same fields as Wikidata's, with `type` in place of `class_qid`/`widen`. `read_enumerations(path)` reads the rows. `enumerate_records(row, *, call)` loops `page=1..` with `params={"filter": f"types:{row.type},locations.geonames_details.country_code:{row.country_code}", "page": page}`, asserts `number_of_results` within bounds on page 1 (raising `EnumerationShape`), stops when a page returns no items, and returns every item. `record_records(row, records, *, now) -> RorReport(listed, bound, conflicts, unkeyable, inactive)` has the same shape as `wikidata.record_items`. Each record is keyed on `website_domain(record)`, with `identifiers=[("ROR", record["id"])]`, `names=all_names(record)`, `found_via=f"ROR:{row.slug}"` and status `CANDIDATE`. A `status` other than `active` counts as `inactive`, writes an entry with `UNRESOLVED`, and binds nothing: a closed institution is not a body a student can apply to. Its successor is the follow-up named at the top of this plan. `enumerate_ror` mirrors `enumerate_wikidata`, including `--dry-run`.

- [ ] **Step 3: Run tests, dry-run, run live, commit**

```bash
POSTGRES_DB=tehsil_enumerators uv run pytest tests/research/test_ror.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
POSTGRES_DB=tehsil_enumerators uv run python manage.py enumerate_ror --dry-run
DATABASE_ROLE=migration POSTGRES_DB=tehsil_enumerators uv run python manage.py enumerate_ror
git add apps/research/ror.py apps/research/management/commands/enumerate_ror.py docs/research/ror-enumerations.csv docs/research/closed-lists.csv tests/research/test_ror.py tests/research/fixtures/ror_country_tr_education.json
git commit -m "feat(research): ROR enumerator -- country x type, active only, CANDIDATE, behind its gate"
```

---

### Task 12: Record the new outbound paths and their terms

**Files:**
- Modify: `CLAUDE.md` (§"Web fetching", the list of outbound paths that are data sources rather than fetches)
- Modify: `docs/legal/2026-09-provider-terms.md`

- [ ] **Step 1: CLAUDE.md**

Under "Two more outbound paths are data sources rather than fetches", change "Two" to "Four". In the EACEA bullet, replace "**Designed, not built** (`propose_program_providers` …)" with one sentence: `manage.py enumerate_eacea` (build item 7) now writes every project and a PIC-first partner binding into the register, and matching a project to a `Program` row is still a person's job. Add two bullets:

- **Wikidata SPARQL** (`apps/research/wikidata.py`): CC0, operator-run, read through `egress.fetch_json_api` with the SPARQL JSON content type named explicitly. It writes `CANDIDATE` only and never vouches. Its query pins class, dissolution filter and website, and its docstring quotes them.
- **ROR v2** (`apps/research/ror.py`): CC0, exact `domains:` lookup and country × type enumeration only. It never uses a name lookup's top hit, and it is gated by `manage.py ror_gate` at ≥ 95% website agreement on the 58 yield hosts.

Both are operator-run and read-only toward the network. Anything that *schedules* them must first put the call behind `LocalEgressProxy`, the same rule the EACEA bullet already states.

- [ ] **Step 2: Terms record**

Append rows for Wikidata (CC0 data; the Wikimedia User-Agent policy, which is why `WIKIDATA_USER_AGENT` carries a contact), ROR (CC0; client id optional), and the EACEA project API (Europa reuse notice; the Terms of Use govern uploading, 09-14 §2.2). Each row gets a URL and today's date.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/legal/2026-09-provider-terms.md
git commit -m "docs: record the Wikidata, ROR and EACEA enumerators as outbound data paths, with their terms"
```

---

### Task 13: The gate run, and its report

**Files:**
- Create: `docs/superpowers/2026-09-2X-enumerators-gate.md` (the date of the run)

- [ ] **Step 1: Bring every in-scope list to a recorded state**

Re-run Task 8 Step 4 for any list that shows `UNREAD`, until the only non-passing entries are ones the budget cannot reach this month. Then run:

```bash
DATABASE_ROLE=migration POSTGRES_DB=tehsil_enumerators uv run python manage.py closed_list_coverage --gate \
  --list igo_regional_global --list eacea_emjm \
  --list tr_outbound_gov --list tr_bilateral --list tr_heis --list tr_banks --list tr_professional_bodies \
  --list az_outbound_gov --list az_bilateral --list az_heis --list az_banks --list az_professional_bodies \
  | tee /tmp/gate.txt; echo "EXIT=${PIPESTATUS[0]}"
```

Drop any slug the survey recorded at rung 4, because no file exists for it. The survey row is its record, and the report says so.

**The gate passes when the command exits 0.** For each in-scope list:

- enumerated: `listed == printed` wherever the publisher prints a count, and no `UNBOUND` row;
- no `UNREAD` row;
- every row carries one of `FUNDING_READ`, `CLASSIFIED`, `ABSTAINED`, `UNREADABLE`, `COULD_NOT_LOOK`, `GATED`, `REJECTED`, `CONFLICT` or `ENUMERATED`.

`eacea_emjm` passes on `listed == API total` plus a conflict share ≤ 2% (Task 9), and that share is printed in the report.

**What fails it, stated so it is not argued afterwards:**

- a `UNBOUND` row: a body with no website we could establish is item 8's to resolve, and the gate stays red until it is resolved;
- an `UNREAD` row: nothing tried, or our own budget stopped it;
- `listed ≠ printed` on any list that prints a count;
- an EACEA conflict share above 2%.

`COULD_NOT_LOOK` passes the gate, because it is recorded, and every one is listed in the report as future `HOST_UNREACHABLE` queue input (§11). `GATED` passes by the owner's rule.

- [ ] **Step 2: Write the report**

`docs/superpowers/2026-09-2X-enumerators-gate.md` contains:

- the verbatim `/tmp/gate.txt`;
- per list: printed size, entries, bodies known, the state histogram, and cost (Firecrawl credits and model dollars, from `FetchAttempt` and the run output);
- the ROR gate numbers, including `name_website_match` for item 8, and whether Task 11 ran;
- EACEA's totals per action code and its disposition histogram, beside the 09-14 table with the caveat that the join target changed;
- the set-differences §15 names as gold sets, computed over the register: Wikidata-TR-universities minus `tr_heis`, `tr_heis` minus Wikidata, and the same for AZ; ROR minus the curated lists where Task 11 ran. For each, a count and up to ten example domains;
- every `COULD_NOT_LOOK` and `CONFLICT` row, by list, as item 12's first queue input;
- the limits: no succession walk (merged EMJM partners), no pointer-tag writer (every `SIGNAL_ONLY` body is `GATED`), and whether the thirteen-country survey (Task 6 Step 6) is complete.

- [ ] **Step 3: Commit, push, PR**

```bash
git add docs/superpowers/2026-09-2X-enumerators-gate.md
git commit -m "docs(research): enumerators gate run -- coverage per list, ROR gate, EACEA, set-differences"
git push -u origin claude/build-enumerators
```

Open a PR against `master`. Its body lists the gate verdict, the list slugs and their states, and the limits above.

---

## Self-review against the brief

| brief requirement | where |
|---|---|
| the country-less intergovernmental and regional-fund list, global, cell-tagged, never sized to one corridor; World Bank, IsDB, ADB, AfDB, OPEC Fund, UNESCO, Aga Khan | Task 5 (named set pinned by test, including the §16 additions; "not sized to one corridor" pinned by test) |
| Wikidata and ROR as sources | Task 7; Tasks 10–11 (ROR gate first, per §6.2) |
| the EACEA project API with its EMJM partner binding | Task 9 |
| the register survey per corridor country | Task 6 (TR/AZ enforced first, all fifteen before the item closes) |
| curated national files | Tasks 2, 4, 8 |
| scope each source to what it can answer alone | the scope table at the top; each adapter's docstring repeats its own row |
| gate: 100% enumerated with read states recorded | Tasks 3–4 (arithmetic and `--gate` exit code); Task 13 (the run, pass and fail rules) |
| no hard-coded migration number; expect a merge migration | Global Constraints; Task 1 Step 4 |
| new tables state their RLS case, carry policies in the same migration, join `test_database_isolation.py`, verified through `runtime_connection` | Task 1 (both tables are shared catalog) |
