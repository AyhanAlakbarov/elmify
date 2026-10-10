# Organisation Register and Search Provider Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared-catalog `Organisation` register keyed by registrable domain, and put Exa, Brave and Tavily behind one `SearchProvider` protocol that returns URLs only — so a second index costs its set-difference rather than its sum.

**Architecture:** Every discovery route (registries, inventory, hub harvesting, search) converges on one table keyed by registrable domain. Adapters read `url` and nothing else from a provider response; the register answers "is this host new?" before anything is fetched. The register is shared catalog — every tenant reads it, only `catalog_ingestion` writes it.

**Tech Stack:** Django 5.2, Postgres with row-level security, `tldextract` (new, offline mode), `httpx`-free — outbound calls go through the repo's existing `apps/research/egress.py`.

**Spec:** `docs/superpowers/specs/2026-09-17-role-routed-discovery-design.md` (§4.1, §4.6, §4.13, §8, §9). Evidence for every configuration constant: `docs/superpowers/research/2026-09-17-search-capability-ablation.md`.

## Global Constraints

- **Only `url` is read from any provider response.** No snippet, title, ranking, score or result object is persisted, ever. Transient in-memory triage is allowed; a column is not. (§4.6, `CLAUDE.md` "Search providers")
- **Configuration that is measured OFF and must not be set:** Tavily `language`, Tavily `filter_by_language`, Exa `category`, Exa `includeText`, Brave `country`, Brave `search_lang`. Each is a measured loss, not an oversight. (§4.4 ablation table)
- **Configuration that is measured ON:** Exa `numResults: 100`; Brave `offset` paging; Firecrawl `categories: ["pdf"]`; query written in the local language with English as a second pass.
- **Brave pagination stops on the first empty `results` array.** `more_results_available` is **not present in the response** (measured 2026-09-18 on the paid plan). Do not gate the loop on it.
- **Every query is profile-free.** No student field may reach a provider. A test asserts this. (§8)
- `Organisation` is shared catalog: no tenant column, `shared_catalog_select` for read, `catalog_ingestion_write` for write, listed in `_SHARED_TABLES`. (§9)
- `funding.Institution` is unchanged. An `Organisation` of kind `HEI` gets a **nullable** link to it; `write_catalog_entry` stays the only writer of `Institution`. (§4.1)
- Python version is declared in five places and must agree (`CLAUDE.md`). This plan changes none of them.
- Never run `ruff format` in this repo (memory: it produces invalid Python here). `uv run ruff check` and `uv run mypy` only.

---

## File Structure

| file | responsibility |
|---|---|
| `apps/research/hosts.py` (new) | `registrable_domain()` — one function, Public Suffix List, offline |
| `apps/funding/models.py` (modify) | `Organisation`, `OrganisationIdentifier` |
| `apps/funding/migrations/00NN_organisation.py` (new) | schema |
| `apps/funding/migrations/00NN_organisation_rls.py` (new) | RLS policies |
| `apps/research/organisations.py` (new) | `record_organisation()`, `known_domains()` — the dedupe seam |
| `apps/research/domains.py` (modify) | `AGGREGATOR_DOMAINS` expansion, `STEERING` table |
| `apps/research/providers/__init__.py` (new) | `SearchRequest`, `SearchProvider` protocol |
| `apps/research/providers/exa.py` (new) | Exa adapter |
| `apps/research/providers/brave.py` (new) | Brave adapter + offset loop |
| `apps/research/providers/tavily.py` (new) | Tavily adapter |
| `apps/research/goggles/tehsil-funders.goggle` (new) | the hosted Goggle, committed |
| `config/settings/base.py` (modify) | per-provider keys |
| `infra/template.yaml` (modify) | the keys as Secrets Manager entries |

**Migration numbering:** the highest on this branch is `0030_cv_directives_undecided_unreadable`. Use the next free number **at the time you run `makemigrations`** — another session commits to this checkout, so verify with `ls apps/funding/migrations/` first. `makemigrations --check` in CI catches a collision; a textually clean merge does not.

---

### Task 1: Registrable domain, on the Public Suffix List

The probe's two-label rule got `edu.tr` wrong, which silently merges every Turkish university into one row. This is the key the whole register is built on, so it goes first and alone.

**Files:**
- Create: `apps/research/hosts.py`
- Modify: `pyproject.toml` (add `tldextract`)
- Test: `tests/research/test_hosts.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `registrable_domain(value: str) -> str` — accepts a bare host or a full URL, returns the registrable domain in lowercase, or `""` when there is none (an IP address, an unknown suffix, an empty string).

- [ ] **Step 1: Add the dependency**

`tldextract` 5.3.2 verified working offline on this repo's real edge cases, 2026-09-18. In `pyproject.toml`, in the `dependencies` list, keeping alphabetical order (after `stagehand`, before `pypdf` is wrong — the list is not strictly sorted; insert after `pydantic`):

```toml
  "tldextract>=5.3.2,<6",
```

Then:

```bash
uv sync
```

- [ ] **Step 2: Write the failing test**

Create `tests/research/test_hosts.py`:

```python
"""The register's key. A wrong answer here merges two universities into one row."""

import pytest

from apps.research.hosts import registrable_domain


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # The case the probe's two-label rule got wrong: edu.tr is a public
        # suffix, so metu.edu.tr is the registrable domain and edu.tr is not.
        ("www.metu.edu.tr", "metu.edu.tr"),
        ("https://www.metu.edu.tr/en/admissions", "metu.edu.tr"),
        ("ox.ac.uk", "ox.ac.uk"),
        # gov.az is a public suffix; edu.gov.az is a real organisation.
        ("edu.gov.az", "edu.gov.az"),
        ("zeit-stiftung.de", "zeit-stiftung.de"),
        # Deep subdomains collapse to the organisation that owns them.
        ("ai.study.fau.eu", "fau.eu"),
        ("sub.dept.uni-hamburg.de", "uni-hamburg.de"),
        ("HTTPS://WWW.Uni-Hamburg.DE/", "uni-hamburg.de"),
    ],
)
def test_registrable_domain_uses_the_public_suffix_list(value: str, expected: str) -> None:
    assert registrable_domain(value) == expected


@pytest.mark.parametrize("value", ["", "localhost", "192.0.2.1", "https://192.0.2.1/x", "   "])
def test_no_registrable_domain_is_an_empty_string_not_a_guess(value: str) -> None:
    """A caller must be able to skip a host rather than store a wrong key."""
    assert registrable_domain(value) == ""


def test_resolution_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """The snapshot ships with the package. A discovery sweep must not fetch
    the suffix list mid-run, and an air-gapped test run must not hang."""
    import socket

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("registrable_domain attempted a network call")

    monkeypatch.setattr(socket, "socket", refuse)
    assert registrable_domain("www.metu.edu.tr") == "metu.edu.tr"
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/test_hosts.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'apps.research.hosts'`.

- [ ] **Step 4: Write the implementation**

Create `apps/research/hosts.py`:

```python
"""The registrable domain of a host -- the key every discovery route dedupes on.

One function, because getting it wrong is expensive in a specific way: a crude
"last two labels" rule reads `metu.edu.tr` as `edu.tr` and merges every Turkish
university into a single register row. `edu.tr`, `ac.uk` and `gov.az` are public
suffixes, and only the Public Suffix List knows that.

The suffix list is the snapshot bundled with tldextract, never fetched:
`suffix_list_urls=()` disables the live download, and a discovery sweep that
paused to refresh a suffix list would be making an unbudgeted outbound call
from inside a loop that is already rate-limited on other grounds.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import tldextract

#: `suffix_list_urls=()` is the documented offline mode; `fallback_to_snapshot`
#: keeps the bundled list in play. Built once at import: the constructor reads
#: the snapshot, and building it per call would parse it per call.
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)


def registrable_domain(value: str) -> str:
    """The registrable domain of a host or URL, lowercased, or "" if there is none.

    "" is returned for an IP address, an unknown suffix and an empty input --
    never a guess. A caller that cannot key a host must skip it, because a
    wrong key is a silently merged organisation rather than a visible failure.
    """
    text = value.strip()
    if not text:
        return ""
    host = urlsplit(text).hostname if "//" in text else text
    if not host:
        return ""
    # `registered_domain` is deprecated in tldextract 5.3; this is the same
    # value under the accurate name.
    return _EXTRACT(host.casefold()).top_domain_under_public_suffix
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/test_hosts.py -q
```

Expected: PASS, 14 tests.

- [ ] **Step 6: Lint and type-check**

```bash
uv run ruff check apps/research/hosts.py tests/research/test_hosts.py
uv run mypy apps/research/hosts.py
```

Expected: `All checks passed!` and `Success: no issues found`. If mypy reports a missing stub for `tldextract`, add to `pyproject.toml` under `[[tool.mypy.overrides]]`:

```toml
[[tool.mypy.overrides]]
module = ["tldextract.*"]
ignore_missing_imports = true
```

- [ ] **Step 7: Commit**

```bash
git add apps/research/hosts.py tests/research/test_hosts.py pyproject.toml uv.lock
git commit -m "feat(research): registrable domain on the Public Suffix List

The register's dedupe key. A last-two-labels rule reads metu.edu.tr as
edu.tr and merges every Turkish university into one row; edu.tr, ac.uk and
gov.az are public suffixes and only the PSL knows it.

Offline by construction: suffix_list_urls=() uses the snapshot bundled with
the package, so no sweep pauses to fetch a suffix list. Pinned by a test
that fails if a socket is opened."
```

---

### Task 2: The Organisation register

> **Amended 2026-09-19 before execution — read
> `docs/superpowers/specs/2026-09-19-eligibility-vocabulary-and-register-amendment-design.md` §3
> first.** Five changes supersede the model below: domains are plural (`OrganisationDomain`,
> merge via a shared `OrganisationIdentifier`, never by name); `kind` takes the holder vocabulary
> (fifteen values plus `RESEARCH_INSTITUTE`) instead of the seven here; `FundingOpportunity`
> gains a real FK to `Organisation`; three read-state fields; five cadence fields. Task 1 stands
> as built (`apps/research/hosts.py`, already on the consolidated worktree).

**Files:**
- Modify: `apps/funding/models.py` (append after `InstitutionIdentifier`, around line 466)
- Create: `apps/funding/migrations/00NN_organisation.py` (generated)
- Create: `apps/funding/migrations/00NN_organisation_rls.py` (hand-written)
- Modify: `tests/tenancy/test_database_isolation.py:15-36` (`_SHARED_TABLES`)
- Test: `tests/funding/test_organisation.py`

**Interfaces:**
- Consumes: `registrable_domain` (Task 1).
- Produces: `Organisation` with `Kind` (`HEI`, `HEI_UNIT`, `FUNDER_GOVERNMENT`, `FUNDER_FOUNDATION`, `FUNDER_EMPLOYER`, `MULTILATERAL`, `INFRASTRUCTURE`) and `Status` (`REGISTERED`, `CANDIDATE`, `REJECTED`); `OrganisationIdentifier` with `Scheme` = `InstitutionIdentifier.Scheme` plus `WIKIDATA`, `EACEA_PIC`.

- [ ] **Step 1: Write the failing test**

Create `tests/funding/test_organisation.py`:

```python
"""The register: one row per registrable domain, shared by every tenant."""

import pytest
from django.db import IntegrityError, transaction

from apps.funding.models import Institution, Organisation, OrganisationIdentifier

pytestmark = pytest.mark.django_db


def _org(**kwargs: object) -> Organisation:
    defaults: dict[str, object] = {
        "registrable_domain": "metu.edu.tr",
        "name": "Middle East Technical University",
        "kind": Organisation.Kind.HEI,
        "country_code": "TR",
        "official_website": "https://www.metu.edu.tr/",
        "status": Organisation.Status.REGISTERED,
        "found_via": ["R1:deqar"],
    }
    defaults.update(kwargs)
    return Organisation.objects.create(**defaults)


def test_one_row_per_registrable_domain() -> None:
    """The dedupe guarantee is a database constraint, not a convention: two
    routes finding the same host must not be able to create two rows."""
    _org()
    with pytest.raises(IntegrityError), transaction.atomic():
        _org(name="METU (from Wikidata)", found_via=["R1:wikidata"])


def test_a_candidate_is_an_ordinary_row() -> None:
    """Status affects spend and dedupe, never student visibility (spec 4.1)."""
    org = _org(
        registrable_domain="zeit-stiftung.de",
        name="ZEIT-Stiftung",
        kind=Organisation.Kind.FUNDER_FOUNDATION,
        country_code="DE",
        official_website="https://www.zeit-stiftung.de/",
        status=Organisation.Status.CANDIDATE,
        found_via=["R4_SEARCH:exa"],
    )
    assert Organisation.objects.get(pk=org.pk).status == "CANDIDATE"


def test_a_unit_points_at_its_parent() -> None:
    parent = _org()
    unit = _org(
        registrable_domain="ii.metu.edu.tr",
        name="METU Informatics Institute",
        kind=Organisation.Kind.HEI_UNIT,
        official_website="https://ii.metu.edu.tr/",
        parent=parent,
    )
    assert unit.parent == parent
    assert list(parent.units.all()) == [unit]


def test_the_institution_link_is_optional_and_does_not_create_one() -> None:
    """funding.Institution stays write_catalog_entry's alone. The register
    links to one when the catalog has written it, and stands without it."""
    org = _org()
    assert org.institution is None
    institution = Institution.objects.create(
        canonical_key="tr:metu",
        name="Middle East Technical University",
        country_code="TR",
        official_website="https://www.metu.edu.tr/",
        kind=Institution.Kind.INSTITUTION,
    )
    org.institution = institution
    org.save(update_fields=["institution"])
    assert Organisation.objects.get(pk=org.pk).institution == institution


def test_an_identifier_cannot_name_two_organisations() -> None:
    first = _org()
    second = _org(registrable_domain="boun.edu.tr", name="Bogazici University")
    OrganisationIdentifier.objects.create(
        organisation=first, scheme=OrganisationIdentifier.Scheme.ROR, value="014weej12"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        OrganisationIdentifier.objects.create(
            organisation=second, scheme=OrganisationIdentifier.Scheme.ROR, value="014weej12"
        )


def test_wikidata_and_eacea_pic_are_schemes_here_and_not_on_institution() -> None:
    """The register keys funders too, and a foundation has no ROR id."""
    assert OrganisationIdentifier.Scheme.WIKIDATA == "WIKIDATA"
    assert OrganisationIdentifier.Scheme.EACEA_PIC == "EACEA_PIC"


def test_an_invalid_kind_is_refused_by_the_database() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        Organisation.objects.create(
            registrable_domain="example.org",
            name="Example",
            kind="UNIVERSITY",  # not a Kind
            country_code="DE",
            official_website="https://example.org/",
            status=Organisation.Status.CANDIDATE,
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/funding/test_organisation.py -q
```

Expected: `ImportError: cannot import name 'Organisation'`.

- [ ] **Step 3: Add the models**

In `apps/funding/models.py`, after `InstitutionIdentifier` (before `class CVFormatConfidence`), add. Note `_ORGANISATION_KINDS` and `_ORGANISATION_STATUSES` go beside `_IDENTIFIER_SCHEMES` near the top of the module, for the same reason the comment there gives — a nested choices class is not in scope inside its own `Meta`:

```python
_ORGANISATION_KINDS = (
    "HEI",
    "HEI_UNIT",
    "FUNDER_GOVERNMENT",
    "FUNDER_FOUNDATION",
    "FUNDER_EMPLOYER",
    "MULTILATERAL",
    "INFRASTRUCTURE",
)
_ORGANISATION_STATUSES = ("REGISTERED", "CANDIDATE", "REJECTED")
_ORGANISATION_IDENTIFIER_SCHEMES = (*_IDENTIFIER_SCHEMES, "WIKIDATA", "EACEA_PIC")
```

```python
class Organisation(models.Model):
    """One row per registrable domain: the denominator, and the dedupe key.

    Every discovery route converges here -- registries, host inventory, hub
    harvesting and search -- and the reason the table exists is that the
    denominator and the dedupe key are the same object. Without it a second
    index costs its whole result set rather than its set-difference, and
    every provider result costs a fetch to find out we already had it.

    Keyed on the registrable domain (apps/research/hosts.py) because that is
    the one identifier every route produces. A name is not: the same
    foundation is spelled four ways across four registers.

    Shared catalog. No tenant column, readable by every tenant, writable only
    by catalog_ingestion -- the ProgramStatement shape, for the same reason,
    and it joins _SHARED_TABLES in tests/tenancy/test_database_isolation.py.

    ``status`` affects spend and dedupe and never student visibility: a
    CANDIDATE funder's awards reach a student on the reader's evidence rules
    exactly as a REGISTERED one's do. What REGISTERED buys is that a register
    vouched for the domain, which is what a gold set can be scored against.
    """

    class Kind(models.TextChoices):
        HEI = "HEI"
        #: A faculty, institute or graduate school on its own host. Carries a
        #: parent; the inventory pass (spec 4.3) is what creates these.
        HEI_UNIT = "HEI_UNIT"
        FUNDER_GOVERNMENT = "FUNDER_GOVERNMENT"
        FUNDER_FOUNDATION = "FUNDER_FOUNDATION"
        FUNDER_EMPLOYER = "FUNDER_EMPLOYER"
        MULTILATERAL = "MULTILATERAL"
        #: Not an organisation at all: mail., vpn., a CDN. Stored so it is
        #: never fetched twice, and never read.
        INFRASTRUCTURE = "INFRASTRUCTURE"

    class Status(models.TextChoices):
        #: A register vouched for this domain.
        REGISTERED = "REGISTERED"
        #: Search, inventory or a hub page found it; fetched and classified;
        #: no register vouches for it.
        CANDIDATE = "CANDIDATE"
        REJECTED = "REJECTED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: 253 is the DNS maximum. Unique: this is the whole point of the table.
    registrable_domain = models.CharField(max_length=253, unique=True)
    name = models.CharField(max_length=300)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="units"
    )
    country_code = models.CharField(max_length=2)
    official_website = models.URLField(max_length=2048)
    status = models.CharField(max_length=12, choices=Status.choices)
    #: Route tags, spec 4.6: "R4_SEARCH:exa", "R1:deqar", "R2:crtsh",
    #: "HUB:firecrawl". A list rather than a column because a domain found by
    #: three routes is one row with three tags, and the per-route tallies in
    #: spec 7 are counted off this field.
    found_via = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_verified = models.DateTimeField(null=True, blank=True)
    #: Every name a register, Wikidata or a page has given this organisation -- native
    #: script, English, Russian. Spec 4.13b rule 4: domains are very often acronyms of
    #: the ENGLISH name whatever script the organisation writes in (gyla.ge, idfi.ge),
    #: so resolution and classification need every variant, not the one the route saw.
    names = ArrayField(models.CharField(max_length=300), default=list, blank=True)
    #: Nullable on purpose and in one direction only. funding.Institution is
    #: still created exclusively by write_catalog_entry; the register links to
    #: one once the catalog has written it, and a register row is complete
    #: without it. Never the reverse -- an Organisation must not be able to
    #: bring an Institution into existence.
    institution = models.ForeignKey(
        Institution, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=_ORGANISATION_KINDS),
                name="organisation_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=_ORGANISATION_STATUSES),
                name="organisation_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(country_code__in=_COUNTRIES),
                name="organisation_country_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} <{self.registrable_domain}>"


class OrganisationIdentifier(models.Model):
    """External ids for a register row. InstitutionIdentifier's vocabulary plus
    the two a funder needs: WIKIDATA (the only id many foundations have) and
    EACEA_PIC (how the EMJM project API names a consortium partner).

    Separate from InstitutionIdentifier rather than reusing it: that table
    binds to funding.Institution, which exists only for HEIs the catalog has
    written, and most rows here are foundations and ministries that will never
    have one.
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
        WHED = "WHED"
        #: A Q-id. The only durable id a private foundation usually carries.
        WIKIDATA = "WIKIDATA"
        #: Participant Identification Code, from the EACEA project API.
        EACEA_PIC = "EACEA_PIC"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="identifiers"
    )
    scheme = models.CharField(max_length=20, choices=Scheme.choices)
    value = models.CharField(max_length=128)
    source = models.CharField(max_length=20, choices=InstitutionIdentifier.Source.choices)

    class Meta:
        constraints = [
            #: One code cannot name two organisations -- the same guarantee
            #: InstitutionIdentifier makes, for the same reason: it turns an
            #: ambiguous binding into a refused write rather than a threshold.
            models.UniqueConstraint(
                fields=("scheme", "value"), name="organisation_identifier_scheme_value_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(scheme__in=_ORGANISATION_IDENTIFIER_SCHEMES),
                name="organisation_identifier_scheme_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(source__in=("REGISTER", "CROSSWALK", "HUMAN")),
                name="organisation_identifier_source_valid",
            ),
        ]
```

- [ ] **Step 4: Generate the schema migration**

```bash
ls apps/funding/migrations/ | tail -3
uv run python manage.py makemigrations funding --name organisation
```

Expected: a new `apps/funding/migrations/00NN_organisation.py` creating both models. Read it before continuing — it must contain `CreateModel` for `Organisation` and `OrganisationIdentifier` and nothing else. If it contains an unrelated `AlterField`, another session changed a model; stop and ask.

- [ ] **Step 5: Write the RLS migration**

Create `apps/funding/migrations/00NN_organisation_rls.py` (next number after the one just generated), modelled exactly on `0026_institution_identifier_rls.py`:

```python
# funding_organisation and funding_organisationidentifier join _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py): which organisations exist on the
# open web is the same fact for every tenant, and the register is what makes a
# second search index cost its set-difference instead of its sum.
#
# Same shape as 0026_institution_identifier_rls: both the shared_catalog_select
# read policy and the catalog_ingestion_write policy, from the start. Writing
# under the runtime role raises on INSERT; UPDATE and DELETE match zero rows
# silently, which is why apps/research/organisations.py carries its own guard.
from django.db import migrations

TABLES = ("funding_organisation", "funding_organisationidentifier")

RLS_SQL = "".join(
    f"""
ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{table}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{table}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""
    for table in TABLES
)

REVERSE_RLS_SQL = "".join(
    f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{table};
DROP POLICY IF EXISTS shared_catalog_select ON public.{table};
ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;
"""
    for table in TABLES
)


class Migration(migrations.Migration):

    dependencies = [
        ("funding", "00NN_organisation"),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
```

Replace `00NN_organisation` in `dependencies` with the actual filename stem from Step 4.

- [ ] **Step 6: Add both tables to `_SHARED_TABLES`**

In `tests/tenancy/test_database_isolation.py`, append to the `_SHARED_TABLES` tuple (line 35, after `"funding_institutionidentifier"`):

```python
    "funding_organisation",
    "funding_organisationidentifier",
```

- [ ] **Step 7: Run the tests**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/funding/test_organisation.py tests/tenancy/test_database_isolation.py -q
```

Expected: PASS. The isolation suite is what verifies the RLS policies actually landed — it reads `pg_policies`, not the migration text.

- [ ] **Step 8: Lint, type-check, and check for missing migrations**

```bash
uv run ruff check apps/funding/models.py apps/funding/migrations/ tests/funding/test_organisation.py
uv run mypy apps/funding/models.py
uv run python manage.py makemigrations --check --dry-run
```

Expected: all clean; `makemigrations --check` reports no changes.

- [ ] **Step 9: Commit**

```bash
git add apps/funding/models.py apps/funding/migrations/ tests/funding/test_organisation.py tests/tenancy/test_database_isolation.py
git commit -m "feat(funding): the Organisation register, keyed on registrable domain

The denominator and the dedupe key are the same object, so they are one
table. Without it a second search index costs its whole result set rather
than its set-difference, and every provider URL costs a fetch to discover
we already held the host.

Shared catalog from the start -- shared_catalog_select, catalog_ingestion_write,
listed in _SHARED_TABLES -- because which organisations exist on the open web
is the same fact for every tenant.

funding.Institution is untouched and still write_catalog_entry's alone: the
link is nullable and points one way, so a register row can never bring an
Institution into existence."
```

---

### Task 3: Recording an organisation — the dedupe seam

**Files:**
- Create: `apps/research/organisations.py`
- Test: `tests/research/test_organisations.py`

**Interfaces:**
- Consumes: `registrable_domain` (Task 1), `Organisation` (Task 2).
- Produces:
  - `known_domains(domains: Iterable[str]) -> frozenset[str]` — which of these registrable domains the register already holds. The set-difference primitive.
  - `record_organisation(*, domain, name, kind, country_code, official_website, status, found_via) -> tuple[Organisation, bool]` — upsert by registrable domain, returning `(row, created)`. On an existing row it **adds** the route tag and never downgrades `status`.

- [ ] **Step 1: Write the failing test**

Create `tests/research/test_organisations.py`:

```python
"""The set-difference seam: what makes a second index cost only its novelty."""

import pytest

from apps.funding.models import Organisation
from apps.research.organisations import known_domains, record_organisation

pytestmark = pytest.mark.django_db


def _record(**kwargs: object) -> tuple[Organisation, bool]:
    defaults: dict[str, object] = {
        "domain": "zeit-stiftung.de",
        "name": "ZEIT-Stiftung",
        "kind": Organisation.Kind.FUNDER_FOUNDATION,
        "country_code": "DE",
        "official_website": "https://www.zeit-stiftung.de/",
        "status": Organisation.Status.CANDIDATE,
        "found_via": "R4_SEARCH:exa",
    }
    defaults.update(kwargs)
    return record_organisation(**defaults)  # type: ignore[arg-type]


def test_a_new_domain_is_created_once() -> None:
    org, created = _record()
    assert created is True
    again, created_again = _record(found_via="R4_SEARCH:brave")
    assert created_again is False
    assert again.pk == org.pk
    assert Organisation.objects.count() == 1


def test_a_second_route_adds_its_tag_and_does_not_duplicate_it() -> None:
    """Spec 7's tallies are counted off found_via, so a repeat must not
    inflate them and a genuine second discoverer must not be lost."""
    _record()
    _record(found_via="R4_SEARCH:brave")
    _record(found_via="R4_SEARCH:brave")
    org = Organisation.objects.get(registrable_domain="zeit-stiftung.de")
    assert sorted(org.found_via) == ["R4_SEARCH:brave", "R4_SEARCH:exa"]


def test_a_register_promotes_a_candidate_and_search_never_demotes_one() -> None:
    """REGISTERED means a register vouched for the domain. A later search hit
    on the same host is not evidence against that."""
    _record(status=Organisation.Status.CANDIDATE, found_via="R4_SEARCH:exa")
    _record(status=Organisation.Status.REGISTERED, found_via="R1:deqar")
    assert Organisation.objects.get(registrable_domain="zeit-stiftung.de").status == "REGISTERED"

    _record(status=Organisation.Status.CANDIDATE, found_via="R4_SEARCH:brave")
    assert Organisation.objects.get(registrable_domain="zeit-stiftung.de").status == "REGISTERED"


def test_a_url_is_accepted_where_a_domain_is_expected() -> None:
    org, _ = _record(domain="https://www.zeit-stiftung.de/stipendien/index.html")
    assert org.registrable_domain == "zeit-stiftung.de"


def test_a_host_with_no_registrable_domain_is_refused() -> None:
    """Better a raised error than a row keyed on "" that swallows every
    unkeyable host into one organisation."""
    with pytest.raises(ValueError, match="no registrable domain"):
        _record(domain="192.0.2.1")


def test_known_domains_answers_only_about_domains_it_was_asked() -> None:
    _record()
    assert known_domains(["zeit-stiftung.de", "example.org"]) == frozenset({"zeit-stiftung.de"})
    assert known_domains([]) == frozenset()


def test_known_domains_normalises_what_it_is_given() -> None:
    """Callers pass provider URLs. The set-difference must not miss a host
    because one route spelled it with a www and a scheme."""
    _record()
    assert known_domains(["https://WWW.Zeit-Stiftung.de/x"]) == frozenset({"zeit-stiftung.de"})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/test_organisations.py -q
```

Expected: `ModuleNotFoundError: No module named 'apps.research.organisations'`.

- [ ] **Step 3: Write the implementation**

Create `apps/research/organisations.py`:

```python
"""Writing to the Organisation register, and asking it what it already holds.

`known_domains` is the whole economic argument of the design in one function:
a second index is paid for by its novel hosts, so a sweep asks the register
which domains are new before it fetches anything. Without this, combining
providers costs their sum.

Two rules live here rather than in the model, because they are about how
routes interact rather than about what a row may contain:

  * a route tag is added, never replaced -- spec 7 counts first-discoverers
    off found_via, and a repeat visit must neither inflate that count nor
    erase the route that got there first;
  * REGISTERED is never downgraded. A register vouched for the domain; a
    later search hit on the same host is not evidence against it.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction
from django.db.models import F
from django.db.models.functions import Now

from apps.funding.models import Organisation

from .hosts import registrable_domain


def known_domains(values: Iterable[str]) -> frozenset[str]:
    """Which of these hosts or URLs the register already holds, as domains.

    Normalises its input, so a caller may pass provider URLs straight in: the
    set-difference must not miss a host because one route spelled it with a
    scheme and a www.
    """
    domains = {d for d in (registrable_domain(v) for v in values) if d}
    if not domains:
        return frozenset()
    return frozenset(
        Organisation.objects.filter(registrable_domain__in=domains).values_list(
            "registrable_domain", flat=True
        )
    )


@transaction.atomic
def record_organisation(
    *,
    domain: str,
    name: str,
    kind: str,
    country_code: str,
    official_website: str,
    status: str,
    found_via: str,
) -> tuple[Organisation, bool]:
    """Upsert one register row by registrable domain. Returns (row, created).

    Raises ValueError for a host with no registrable domain: a row keyed on ""
    would swallow every unkeyable host into a single organisation, which is
    the failure this table exists to prevent.
    """
    key = registrable_domain(domain)
    if not key:
        raise ValueError(f"no registrable domain in {domain!r}")

    organisation, created = Organisation.objects.get_or_create(
        registrable_domain=key,
        defaults={
            "name": name,
            "kind": kind,
            "country_code": country_code,
            "official_website": official_website,
            "status": status,
            "found_via": [found_via],
        },
    )
    if created:
        return organisation, True

    updates: list[str] = []
    if found_via not in organisation.found_via:
        organisation.found_via = [*organisation.found_via, found_via]
        updates.append("found_via")
    # REGISTERED is the only promotion. CANDIDATE never overwrites it, and
    # REJECTED is set by a human or the classifier, never by a route.
    if status == Organisation.Status.REGISTERED and organisation.status != status:
        organisation.status = status
        updates.append("status")
    if updates:
        organisation.last_verified = Now()  # type: ignore[assignment]
        organisation.save(update_fields=[*updates, "last_verified"])
        organisation.refresh_from_db(fields=["last_verified"])
    return organisation, False
```

Note: `F` is imported for symmetry with the repo's other services but is unused here — remove the import if ruff flags it.

- [ ] **Step 4: Run the test to verify it passes**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/test_organisations.py -q
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check apps/research/organisations.py tests/research/test_organisations.py
uv run mypy apps/research/organisations.py
```

- [ ] **Step 6: Commit**

```bash
git add apps/research/organisations.py tests/research/test_organisations.py
git commit -m "feat(research): known_domains, the set-difference seam

The design's economic claim in one function: a second index is paid for by
its novel hosts, so a sweep asks the register what is new before fetching
anything. Without it, combining providers costs their sum.

Two interaction rules live here rather than on the model: a route tag is
added and never replaced, because first-discoverer tallies are counted off
found_via; and REGISTERED is never downgraded, because a later search hit
on a vouched-for host is not evidence against the register."
```

---

### Task 4: The denylist and the steering table

**Files:**
- Modify: `apps/research/domains.py`
- Test: `tests/research/test_domains.py` (extend if present, create if not)

**Interfaces:**
- Consumes: nothing.
- Produces: `AGGREGATOR_DOMAINS: tuple[str, ...]` (the union of today's `CATALOGUE_DOMAINS` and the aggregators the probe needed); `STEERING: dict[str, Steering]` keyed by ISO-2 country code, each with `language` (ISO-639-1 for the local-language query) and `english_second_pass: bool`.

**Why `STEERING` carries no provider country codes:** the ablation measured Brave `country` at −8 local funders in Indonesia and `search_lang` as inert (Jaccard 1.000), and Tavily `language` at −1.0. The steering table therefore steers *our query text*, never a provider parameter. This is the whole content of the design's "set no filters except the aggregator denylist".

- [ ] **Step 1: Write the failing test**

Create or extend `tests/research/test_domains.py`:

```python
from apps.research.domains import AGGREGATOR_DOMAINS, STEERING, is_catalogue


def test_the_probe_aggregators_are_on_the_denylist() -> None:
    """Every one of these was a top-ranked non-answer in the 2026-09-17 probe."""
    for host in (
        "scholars4dev.com",
        "scholarshiproar.com",
        "findamasters.com",
        "educations.com",
        "topuniversities.com",
        "edumap.az",
        "xaricdetehsil.net",
    ):
        assert host in AGGREGATOR_DOMAINS, host
        assert is_catalogue(host), host


def test_the_old_list_is_still_wholly_included() -> None:
    """domains.py has three consumers and the failure mode it exists to
    prevent is a host excluded in one place and trusted in another."""
    from apps.research.domains import CATALOGUE_DOMAINS

    assert set(CATALOGUE_DOMAINS) <= set(AGGREGATOR_DOMAINS)


def test_a_subdomain_of_a_denied_host_is_denied() -> None:
    assert is_catalogue("www.scholars4dev.com")


def test_steering_gives_a_local_language_for_every_launch_corridor() -> None:
    """Spec 5: AZ and TR home-side, DE/NL/SE/FR/HU/IT destination-side."""
    for code in ("AZ", "TR", "DE", "NL", "SE", "FR", "HU", "IT"):
        assert STEERING[code].language, code


def test_steering_carries_no_provider_country_or_language_parameter() -> None:
    """Measured OFF: Brave country (-8 in Indonesia), Brave search_lang
    (inert, Jaccard 1.000), Tavily language (-1.0). The table steers the
    query text we write, never a parameter we send."""
    fields = set(vars(STEERING["TR"]))
    assert fields == {"language", "english_second_pass"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/test_domains.py -q
```

Expected: `ImportError: cannot import name 'AGGREGATOR_DOMAINS'`.

- [ ] **Step 3: Extend `apps/research/domains.py`**

Append to the module (keep `CATALOGUE_DOMAINS`, `is_catalogue` and `is_hoppable_catalogue` exactly as they are — `discovery.from_url` reads them):

```python
#: Aggregators the 2026-09-17 probe ranked above the origin, on top of the
#: 23 held above. Collected from 862 classified hosts across four providers:
#: each one is a page that describes funding it does not administer, so it can
#: route research and can never support a claim.
_PROBE_AGGREGATORS = (
    "scholars4dev.com",
    "scholarshiproar.com",
    "scholarshipdb.net",
    "findamasters.com",
    "findaphd.com",
    "educations.com",
    "topuniversities.com",
    "timeshighereducation.com",
    "studyabroad.com",
    "hotcoursesabroad.com",
    "scholarshipscorner.website",
    "opportunitydesk.org",
    "scholarshipregion.com",
    "youthop.com",
    "armacad.info",
    # Regional, from the Azerbaijani and Turkish legs.
    "edumap.az",
    "xaricdetehsil.net",
    "tehsilxeberleri.az",
    "kariyer.net",
    "burslar.net",
    # Forums and Q&A beyond the three already listed above.
    "stackexchange.com",
    "vk.com",
    "telegram.me",
    "t.me",
)

#: The single list every adapter sends as its exclusion parameter, and the
#: one `discovery.from_url` demotes against. One list, because the failure
#: mode is a host excluded in one place and trusted in another.
AGGREGATOR_DOMAINS = (*CATALOGUE_DOMAINS, *_PROBE_AGGREGATORS)


@dataclass(frozen=True)
class Steering:
    """How to phrase a query for a country -- not how to filter one.

    There is deliberately no provider `country` or `language` code here. The
    2026-09-17 ablation measured Brave `country` at -8 local funders in
    Indonesia and inert elsewhere, Brave `search_lang` as measurably inert
    (Jaccard 1.000, 0.985, 1.000, 1.000), and Tavily `language` at -1.0 on the
    German key (-2.3 with `filter_by_language`). Every one of them narrows the
    pool instead of re-ranking it.

    What did win, in all four countries, was writing the query in the local
    language and running English as a second pass (union 110/62, 80/54, 22/14,
    84/50). So this table steers the text we compose and sends no filter.
    """

    #: ISO-639-1, the language the query is written in.
    language: str
    #: English still adds a unique 5-35 hosts per country, so it is a second
    #: pass everywhere rather than a fallback for countries we think are small.
    english_second_pass: bool = True


#: Launch corridors, spec 5. A country absent from this table gets an English
#: query only -- correct, and visibly incomplete, which is the intended shape:
#: adding a corridor is adding a row, not writing code.
STEERING = {
    "AZ": Steering(language="az"),
    "TR": Steering(language="tr"),
    "KZ": Steering(language="kk"),
    "GE": Steering(language="ka"),
    "UZ": Steering(language="uz"),
    "DE": Steering(language="de"),
    "NL": Steering(language="nl"),
    "SE": Steering(language="sv"),
    "FR": Steering(language="fr"),
    "HU": Steering(language="hu"),
    "IT": Steering(language="it"),
    "ID": Steering(language="id"),
    "VN": Steering(language="vi"),
    "IN": Steering(language="hi"),
    "PK": Steering(language="ur"),
}
```

Add `from dataclasses import dataclass` to the module's imports.

- [ ] **Step 4: Run the test to verify it passes**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/test_domains.py -q
```

- [ ] **Step 5: Run the existing consumers' tests — this module has three**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research -q
```

Expected: PASS. If `test_discovery.py` fails on a newly-denied host, that is the change working; update the fixture's expectation rather than shrinking the denylist.

- [ ] **Step 6: Commit**

```bash
git add apps/research/domains.py tests/research/test_domains.py
git commit -m "feat(research): one denylist, and a steering table that sets no filters

AGGREGATOR_DOMAINS unions the 23 catalogue hosts already held with the
aggregators the 2026-09-17 probe ranked above the origin across 862
classified hosts.

Steering carries a language for writing the query and nothing else. Brave
country measured -8 local funders in Indonesia, Brave search_lang
measurably inert (Jaccard 1.000), Tavily language -1.0 and -2.3 with
filter_by_language. Writing the query in the local language won in all four
countries; asking a provider to filter for it lost. The table encodes that
asymmetry so an adapter cannot reintroduce the losing half."
```

---

### Task 5: The provider protocol

**Files:**
- Create: `apps/research/providers/__init__.py`
- Test: `tests/research/providers/test_protocol.py`

**Interfaces:**
- Consumes: `AGGREGATOR_DOMAINS`, `STEERING` (Task 4).
- Produces:
  - `SearchRequest` — frozen dataclass: `query: str`, `country_code: str`, `language: str`, `phrasing: str`, `max_results: int = 100`, `denylist: tuple[str, ...] = AGGREGATOR_DOMAINS`.
  - `SearchProvider` protocol — `name: str` (read-only property), `search(request: SearchRequest) -> Iterable[str]`.
  - `requests_for(query_template: str, country_code: str) -> tuple[SearchRequest, ...]` — the local-language request plus the English second pass.

- [ ] **Step 1: Write the failing test**

Create `tests/research/providers/__init__.py` (empty) and `tests/research/providers/test_protocol.py`:

```python
"""The contract every adapter meets: a request in, URLs out, nothing kept."""

from collections.abc import Iterable

import pytest

from apps.research.domains import AGGREGATOR_DOMAINS
from apps.research.providers import SearchProvider, SearchRequest, requests_for


class _Stub:
    name = "stub"

    def search(self, request: SearchRequest) -> Iterable[str]:
        return ["https://example.org/a"]


def test_a_stub_satisfies_the_protocol() -> None:
    provider: SearchProvider = _Stub()
    assert list(provider.search(SearchRequest(query="q", country_code="TR", language="tr"))) == [
        "https://example.org/a"
    ]


def test_a_request_carries_the_denylist_by_default() -> None:
    assert SearchRequest(query="q", country_code="TR", language="tr").denylist == AGGREGATOR_DOMAINS


def test_the_default_depth_is_the_measured_one() -> None:
    """Depth is the only capability that reliably wins, so it is the default
    rather than something a caller must remember to ask for."""
    assert SearchRequest(query="q", country_code="TR", language="tr").max_results == 100


def test_a_request_is_frozen() -> None:
    request = SearchRequest(query="q", country_code="TR", language="tr")
    with pytest.raises(AttributeError):
        request.query = "other"  # type: ignore[misc]


def test_requests_for_writes_the_local_language_pass_first() -> None:
    requests = requests_for("{language_name} scholarships for master's abroad", "TR")
    assert [r.language for r in requests] == ["tr", "en"]
    assert requests[0].phrasing == "local"
    assert requests[1].phrasing == "english"


def test_an_unsteered_country_gets_english_only_and_says_so() -> None:
    """Visibly incomplete beats silently English: adding a corridor is adding
    a row to STEERING, and a missing row must not look like a decision."""
    requests = requests_for("{language_name} scholarships", "BR")
    assert [r.language for r in requests] == ["en"]


def test_no_request_field_can_carry_a_student_fact() -> None:
    """Spec 8: queries are built from country and family vocabulary only.
    This asserts the shape -- there is no field a profile could travel in."""
    assert set(SearchRequest.__dataclass_fields__) == {
        "query",
        "country_code",
        "language",
        "phrasing",
        "max_results",
        "denylist",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/providers -q
```

Expected: `ModuleNotFoundError: No module named 'apps.research.providers'`.

- [ ] **Step 3: Write the implementation**

Create `apps/research/providers/__init__.py`:

```python
"""One protocol for every search index: a request in, URLs out.

`search` returns an iterable of URL strings and nothing else. That is not a
simplification of a richer return type -- it is the design's retention rule
expressed as a signature. A snippet, a title or a ranking cannot be persisted
by accident if the adapter never hands one back, and a provider whose terms
change tomorrow costs a deleted adapter rather than a data migration.

Adding a provider is writing one of these and appending it to a tally. It is
deliberately not a plugin system: there are four, they are named in the spec,
and a registry with one implementation is the abstraction this repo's rules
forbid.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from ..domains import AGGREGATOR_DOMAINS, STEERING

#: Written into the query in place of `{language_name}` so one template serves
#: both passes. English names, because the template is composed by us and read
#: by an index, not shown to anyone.
_LANGUAGE_NAMES = {
    "az": "Azerbaijani",
    "tr": "Turkish",
    "kk": "Kazakh",
    "ka": "Georgian",
    "uz": "Uzbek",
    "de": "German",
    "nl": "Dutch",
    "sv": "Swedish",
    "fr": "French",
    "hu": "Hungarian",
    "it": "Italian",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "hi": "Hindi",
    "ur": "Urdu",
    "en": "English",
}


@dataclass(frozen=True)
class SearchRequest:
    """One call's worth of intent, provider-independent.

    There is no field here a student fact could travel in, and the test suite
    asserts that by enumerating the fields: spec 8's profile-free rule is an
    ongoing obligation under Tavily 9.2's perpetual licence over query text,
    so it is enforced by the shape rather than by review.
    """

    query: str
    country_code: str
    language: str
    #: "local" or "english" -- carried so a tally can attribute a hit to the
    #: pass that found it, which is what decides whether the second pass earns
    #: its cost per country.
    phrasing: str = "local"
    #: Depth is the only capability that reliably wins (Exa 25->100 gave
    #: x3.4/x2.0/x1.7/x2.2), so the measured value is the default rather than
    #: something each caller must remember.
    max_results: int = 100
    denylist: tuple[str, ...] = field(default=AGGREGATOR_DOMAINS)


class SearchProvider(Protocol):
    """One index. `name` is a read-only property for the same reason
    `LeadSource.name` is: implementations are frozen dataclasses, and mypy
    refuses a frozen field against a settable protocol member.
    """

    @property
    def name(self) -> str: ...

    def search(self, request: SearchRequest) -> Iterable[str]: ...


def requests_for(query_template: str, country_code: str) -> tuple[SearchRequest, ...]:
    """The local-language pass, then English.

    Both, always, where a language is known: local-language queries beat
    English on local funders in all four countries measured, and English still
    contributed a unique 5-35 hosts on top. Neither subsumes the other.

    A country with no STEERING row gets English alone. That is visibly
    incomplete on purpose -- adding a corridor is adding a row, and a missing
    row must not be indistinguishable from a decision that English suffices.
    """
    steering = STEERING.get(country_code.upper())
    languages = ["en"] if steering is None else [steering.language]
    if steering is not None and steering.english_second_pass:
        languages.append("en")
    return tuple(
        SearchRequest(
            query=query_template.format(language_name=_LANGUAGE_NAMES.get(language, "English")),
            country_code=country_code.upper(),
            language=language,
            phrasing="english" if language == "en" else "local",
        )
        for language in languages
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/providers -q
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check apps/research/providers tests/research/providers
uv run mypy apps/research/providers
git add apps/research/providers tests/research/providers
git commit -m "feat(research): SearchProvider -- a request in, URLs out

search() returns URL strings and nothing else, which is the retention rule
expressed as a signature rather than as a review checklist: an adapter that
never hands back a snippet cannot have one persisted by accident, and a
provider whose terms change costs a deleted file rather than a migration.

SearchRequest has no field a student fact could travel in and a test
enumerates them, because Tavily 9.2 takes a perpetual licence over query
text and profile-free is therefore an ongoing obligation.

requests_for runs the local language and then English: local won on local
funders in all four countries measured and English still added a unique
5-35 on top, so neither subsumes the other."
```

---

### Task 6: The Exa adapter

**Files:**
- Create: `apps/research/providers/exa.py`
- Test: `tests/research/providers/test_exa.py`

**Interfaces:**
- Consumes: `SearchRequest`, `SearchProvider` (Task 5); `fetch_json_api` from `apps.research.egress`.
- Produces: `ExaProvider(api_key: str, post: Callable[..., dict] = fetch_json_api)` with `name = "exa"` and `search(request) -> Iterator[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/research/providers/test_exa.py`:

```python
"""Exa: the primary index for the families no register covers."""

from typing import Any

from apps.research.providers import SearchRequest
from apps.research.providers.exa import ExaProvider

_RESPONSE: dict[str, Any] = {
    "results": [
        {"url": "https://www.zeit-stiftung.de/", "title": "ZEIT-Stiftung", "score": 0.4},
        {"url": "https://www.daad.de/en/", "title": "DAAD"},
    ],
    "costDollars": {"total": 0.097},
}


class _Recorder:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = response if response is not None else _RESPONSE

    def __call__(self, url: str, *, payload: dict[str, Any], headers: dict[str, str]) -> dict:
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        return self.response


def _request(**kwargs: Any) -> SearchRequest:
    defaults: dict[str, Any] = {"query": "Stiftung Stipendium", "country_code": "DE", "language": "de"}
    defaults.update(kwargs)
    return SearchRequest(**defaults)


def test_only_urls_are_returned() -> None:
    """Title and score are in the response and must not survive the adapter."""
    post = _Recorder()
    urls = list(ExaProvider(api_key="k", post=post).search(_request()))
    assert urls == ["https://www.zeit-stiftung.de/", "https://www.daad.de/en/"]


def test_the_measured_depth_is_sent() -> None:
    post = _Recorder()
    list(ExaProvider(api_key="k", post=post).search(_request()))
    assert post.calls[0]["payload"]["numResults"] == 100


def test_no_category_and_no_include_text_are_sent() -> None:
    """Measured losses: category="company" -2.7 pts, includeText -0.8. The
    vendor's docs recommend the first; the measurement rejects it."""
    post = _Recorder()
    list(ExaProvider(api_key="k", post=post).search(_request()))
    payload = post.calls[0]["payload"]
    assert "category" not in payload
    assert "includeText" not in payload


def test_the_denylist_is_the_only_filter() -> None:
    post = _Recorder()
    list(ExaProvider(api_key="k", post=post).search(_request()))
    payload = post.calls[0]["payload"]
    assert "daad.de" in payload["excludeDomains"]
    assert payload["type"] == "auto"
    assert set(payload) == {"query", "type", "numResults", "excludeDomains"}


def test_the_api_key_travels_in_the_header_and_not_the_payload() -> None:
    post = _Recorder()
    list(ExaProvider(api_key="secret", post=post).search(_request()))
    assert post.calls[0]["headers"]["x-api-key"] == "secret"
    assert "secret" not in str(post.calls[0]["payload"])


def test_a_result_without_a_url_is_skipped_not_yielded_empty() -> None:
    post = _Recorder({"results": [{"title": "no url here"}, {"url": "https://ok.example/"}]})
    assert list(ExaProvider(api_key="k", post=post).search(_request())) == ["https://ok.example/"]


def test_an_empty_response_yields_nothing_and_does_not_raise() -> None:
    post = _Recorder({})
    assert list(ExaProvider(api_key="k", post=post).search(_request())) == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/providers/test_exa.py -q
```

Expected: `ModuleNotFoundError: No module named 'apps.research.providers.exa'`.

- [ ] **Step 3: Write the implementation**

Create `apps/research/providers/exa.py`:

```python
"""Exa: the primary index for the three families no register covers.

Best single performer in the 2026-09-17 probe (132 unique hosts, 79% origin,
strongest on the Azerbaijani and Turkish legs) and the only one that does not
decay: across 99 queries in one cell its per-batch contribution barely moved
(124, 63, 45, 43, 45, 38, 34, 42, 42) while Brave fell 81 -> 11 and Tavily
62 -> 5. So a sweep drops the decaying engines early and keeps Exa running.

Two parameters the vendor recommends are not set here, and both are
measurements rather than opinions: `category: "company"` scored -2.7 points on
the 377-funder German key because its entity pipeline is tuned to businesses
and misses foundations, and `includeText` -0.8 because it narrows the pool
like every other filter. Depth is the one capability that wins: 25 -> 100
results multiplied local funders by 3.4, 2.0, 1.7 and 2.2 across four
countries.

Permitted by written permission from Exa (owner correspondence 2026-09-17)
with one condition: Output may not train a competing search index. Nothing
here stores Output at all -- `search` yields URLs and the rest of the
response is discarded at the boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..egress import fetch_json_api
from . import SearchRequest

EXA_SEARCH_URL = "https://api.exa.ai/search"


@dataclass(frozen=True)
class ExaProvider:
    api_key: str = field(repr=False)
    name: str = "exa"
    post: Callable[..., dict[str, object]] = field(default=fetch_json_api)

    def search(self, request: SearchRequest) -> Iterator[str]:
        payload: dict[str, object] = {
            "query": request.query,
            # `auto` lets Exa pick neural or keyword per query. Pinning either
            # was not measured and the default was what the probe scored.
            "type": "auto",
            "numResults": request.max_results,
            "excludeDomains": list(request.denylist),
        }
        data: Mapping[str, Any] = self.post(
            EXA_SEARCH_URL,
            payload=payload,
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
        )
        for item in data.get("results") or []:
            url = str(item.get("url") or "")
            if url:
                yield url
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/providers/test_exa.py -q
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check apps/research/providers/exa.py tests/research/providers/test_exa.py
uv run mypy apps/research/providers/exa.py
git add apps/research/providers/exa.py tests/research/providers/test_exa.py
git commit -m "feat(research): Exa adapter at the measured configuration

numResults 100 -- depth multiplied local funders by 3.4/2.0/1.7/2.2 across
four countries and is the only capability that reliably wins.

Two parameters the vendor recommends are deliberately absent, each with a
number: category='company' at -2.7 points (its entity pipeline is tuned to
businesses and misses foundations) and includeText at -0.8. Tests assert
their absence, so a future reading of Exa's docs cannot quietly add them."
```

---

### Task 7: The Brave adapter and its Goggle

**Files:**
- Create: `apps/research/providers/brave.py`
- Create: `apps/research/goggles/tehsil-funders.goggle`
- Test: `tests/research/providers/test_brave.py`

**Interfaces:**
- Consumes: `SearchRequest`, `SearchProvider` (Task 5).
- Produces: `BraveProvider(api_key: str, get: Callable[..., dict] = fetch_json_api, goggle_url: str = "")` with `name = "brave"` and `search(request) -> Iterator[str]`.

**The pagination rule, measured 2026-09-18 on the paid plan:** `more_results_available` is **not in the response**. Stop on the first empty `results` array. A real German foundation query exhausted at offset 5 (110 results, 76 distinct hosts), so the ceiling of 10 is a ceiling, not an expectation.

- [ ] **Step 1: Write the failing test**

Create `tests/research/providers/test_brave.py`:

```python
"""Brave: the independent second index, and the deepest per query."""

from typing import Any

from apps.research.providers import SearchRequest
from apps.research.providers.brave import BraveProvider


class _Pages:
    """Returns `pages[offset]`, then empty -- the real shape of exhaustion."""

    def __init__(self, pages: list[list[str]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, *, params: dict[str, Any], headers: dict[str, str]) -> dict:
        self.calls.append({"url": url, "params": params, "headers": headers})
        offset = int(params.get("offset", 0))
        urls = self.pages[offset] if offset < len(self.pages) else []
        return {"web": {"results": [{"url": u, "title": "t", "description": "d"} for u in urls]}}


def _request(**kwargs: Any) -> SearchRequest:
    defaults: dict[str, Any] = {"query": "Stiftung Stipendium", "country_code": "DE", "language": "de"}
    defaults.update(kwargs)
    return SearchRequest(**defaults)


def test_it_pages_until_the_first_empty_results_array() -> None:
    """more_results_available is NOT in the response (measured 2026-09-18 on
    the paid plan), so an empty page is the only stop signal there is."""
    get = _Pages([["https://a.example/"], ["https://b.example/"], ["https://c.example/"]])
    urls = list(BraveProvider(api_key="k", get=get).search(_request()))
    assert urls == ["https://a.example/", "https://b.example/", "https://c.example/"]
    # Three pages plus the empty one that stopped it.
    assert [c["params"]["offset"] for c in get.calls] == [0, 1, 2, 3]


def test_it_stops_at_the_offset_ceiling_even_if_pages_keep_coming() -> None:
    """Brave's documented maximum offset is 9. A provider that kept answering
    must not turn one query into an unbounded spend."""
    get = _Pages([["https://x.example/%d" % i] for i in range(20)])
    list(BraveProvider(api_key="k", get=get).search(_request()))
    assert [c["params"]["offset"] for c in get.calls] == list(range(10))


def test_only_urls_are_returned() -> None:
    get = _Pages([["https://a.example/"]])
    assert list(BraveProvider(api_key="k", get=get).search(_request())) == ["https://a.example/"]


def test_no_country_and_no_search_lang_are_sent() -> None:
    """country measured -8 local funders in Indonesia; search_lang measurably
    inert (Jaccard 1.000, 0.985, 1.000, 1.000)."""
    get = _Pages([["https://a.example/"]])
    list(BraveProvider(api_key="k", get=get).search(_request()))
    params = get.calls[0]["params"]
    assert "country" not in params
    assert "search_lang" not in params


def test_the_count_is_the_maximum_page_size() -> None:
    get = _Pages([["https://a.example/"]])
    list(BraveProvider(api_key="k", get=get).search(_request()))
    assert get.calls[0]["params"]["count"] == 20
    assert get.calls[0]["params"]["result_filter"] == "web"


def test_the_goggle_is_sent_only_when_one_is_configured() -> None:
    get = _Pages([["https://a.example/"]])
    list(BraveProvider(api_key="k", get=get).search(_request()))
    assert "goggles" not in get.calls[0]["params"]

    get = _Pages([["https://a.example/"]])
    list(BraveProvider(api_key="k", get=get, goggle_url="https://x/g.goggle").search(_request()))
    assert get.calls[0]["params"]["goggles"] == "https://x/g.goggle"


def test_the_key_travels_in_the_subscription_header() -> None:
    get = _Pages([["https://a.example/"]])
    list(BraveProvider(api_key="secret", get=get).search(_request()))
    assert get.calls[0]["headers"]["X-Subscription-Token"] == "secret"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/providers/test_brave.py -q
```

Expected: `ModuleNotFoundError: No module named 'apps.research.providers.brave'`.

- [ ] **Step 3: Write the Goggle**

Create `apps/research/goggles/tehsil-funders.goggle`:

```
! name: Tehsil funders
! description: Discards commercial scholarship aggregators and boosts institutional and funder hosts. Committed to the repo because a Goggle hosted elsewhere is configuration nobody can review.
! public: true
! author: Tehsil

! Discard: aggregators describe funding they do not administer, so they can
! route research and can never support a claim.
$discard,site=mastersportal.com
$discard,site=bachelorsportal.com
$discard,site=scholarshipportal.com
$discard,site=studyportals.com
$discard,site=scholars4dev.com
$discard,site=scholarshiproar.com
$discard,site=scholarshipdb.net
$discard,site=findamasters.com
$discard,site=findaphd.com
$discard,site=educations.com
$discard,site=topuniversities.com
$discard,site=hotcoursesabroad.com
$discard,site=opportunitydesk.org
$discard,site=youthop.com
$discard,site=edumap.az
$discard,site=xaricdetehsil.net

! Boost: the hosts that administer money or teach.
/scholarship$boost=2
/stipendium$boost=2
/burs$boost=2
/təqaüd$boost=2
.edu.$boost=3
.ac.$boost=3
.gov.$boost=3
uni-$boost=2
universit$boost=2
stiftung$boost=3
vakf$boost=3
vakif$boost=3
```

**Hosting is a separate, non-blocking step.** Brave's `goggles` parameter takes a public URL, so the file has to be reachable over HTTPS before the parameter does anything. Until then `goggle_url` stays empty and the adapter simply omits the parameter — measured effect of the Goggle in the probe was aggregators 33% → 14%, which is a precision win, not a recall one, so the sweep is correct without it and merely noisier. Hosting it is tracked in the spec's §13 open items.

- [ ] **Step 4: Write the implementation**

Create `apps/research/providers/brave.py`:

```python
"""Brave: the independent second index, and the deepest per query.

It returned 84 hosts Exa did not, which is why both are in the roster rather
than the better one alone. Depth is what it is for: 3 -> 10 pages gave +47%,
+68%, +27% and +104% local funders across Germany, Turkiye, Azerbaijan and
Indonesia.

**Pagination stops on the first empty `results` array.** `more_results_available`
is documented but is not present in the response -- measured 2026-09-18 on the
paid Search plan, where a real German foundation query returned 110 results
across offsets 0-5 and empty arrays from 6 on. A loop gated on that field
would run to the ceiling on every query and pay for four empty calls.

`country` and `search_lang` are not sent. `country` measured -8 local funders
in Indonesia and inert in the other three; `search_lang` is measurably inert
(Jaccard of the result sets with and without: 1.000, 0.985, 1.000, 1.000). The
local-language steering happens in the query text instead (see domains.Steering).

Permitted by written permission from Brave (owner correspondence 2026-09-17),
condition: Output may not train a competing search index.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..egress import fetch_json_api
from . import SearchRequest

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

#: Brave's documented maximum. A ceiling, not an expectation: a real query
#: exhausts around offset 5, and the empty-page check is what usually stops
#: the loop. This exists so a provider that kept answering could not turn one
#: query into unbounded spend.
_MAX_OFFSET = 9

#: Brave's maximum page size.
_COUNT = 20


@dataclass(frozen=True)
class BraveProvider:
    api_key: str = field(repr=False)
    name: str = "brave"
    get: Callable[..., dict[str, object]] = field(default=fetch_json_api)
    #: A public HTTPS URL for tehsil-funders.goggle. Empty until the file is
    #: hosted, and the parameter is then omitted: the Goggle is a precision
    #: win (aggregators 33% -> 14% in the probe), never a recall one, so the
    #: sweep is correct without it and merely noisier.
    goggle_url: str = ""

    def search(self, request: SearchRequest) -> Iterator[str]:
        for offset in range(_MAX_OFFSET + 1):
            params: dict[str, object] = {
                "q": request.query,
                "count": _COUNT,
                "offset": offset,
                "result_filter": "web",
            }
            if self.goggle_url:
                params["goggles"] = self.goggle_url
            data: Mapping[str, Any] = self.get(
                BRAVE_SEARCH_URL,
                params=params,
                headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
            )
            results = (data.get("web") or {}).get("results") or []
            if not results:
                return
            for item in results:
                url = str(item.get("url") or "")
                if url:
                    yield url
```

- [ ] **Step 5: Confirm `fetch_json_api` supports a `params` keyword**

```bash
grep -n "def fetch_json_api" -A 20 apps/research/egress.py
```

If it takes only `payload` (a POST body), add a GET path to it in this task rather than bypassing the module — `egress.py` is where `validate_public_url` runs, and a provider call that skips it is an unvalidated outbound request. Extend the existing signature; do not add a second fetch function.

- [ ] **Step 6: Run the test to verify it passes**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/providers/test_brave.py -q
```

Expected: PASS, 7 tests.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check apps/research/providers/brave.py tests/research/providers/test_brave.py
uv run mypy apps/research/providers/brave.py
git add apps/research/providers/brave.py apps/research/goggles tests/research/providers/test_brave.py
git commit -m "feat(research): Brave adapter, paging on the only stop signal there is

more_results_available is documented and absent from the response -- measured
2026-09-18 on the paid plan, where a real German foundation query returned
110 results across offsets 0-5 and empty arrays after. So the loop stops on
the first empty results array, with offset 9 as a ceiling rather than an
expectation. A loop gated on the documented field pays for four empty calls
on every query.

country and search_lang are not sent: -8 local funders in Indonesia, and
measurably inert (Jaccard 1.000) respectively.

The Goggle is committed rather than hosted-and-forgotten; the parameter is
omitted until a public URL exists, which costs precision and never recall."
```

---

### Task 8: The Tavily adapter, and retyping what already exists

**Files:**
- Create: `apps/research/providers/tavily.py`
- Modify: `apps/research/search.py:236-244` (`EntityExpansionSource.search` retyped)
- Test: `tests/research/providers/test_tavily.py`

**Interfaces:**
- Consumes: `SearchRequest`, `SearchProvider` (Task 5).
- Produces: `TavilyProvider(api_key: str, post: Callable[..., dict] = fetch_json_api)` with `name = "tavily"`, `search(request) -> Iterator[str]`, and `candidates(name: str) -> list[str]` — the top-10 URLs for a quoted organisation name. **Selection is not the adapter's job**: the resolver (best lexical match over these, spec §4.13a) lands with the registries plan, beside the register writer.

**Measured 2026-09-18 (spec §4.13a):** taking the *first* result resolves 3 of 25 foundation names;
choosing the best lexical match among the *top 10 of the same responses* resolves 20, with 2 honest
abstentions. So the adapter returns candidates and never picks. Nothing in this plan writes
`REGISTERED` from a search result, and no URL-less register is ingested until the selector's
remaining gate in §13 is passed.

- [ ] **Step 1: Write the failing test**

Create `tests/research/providers/test_tavily.py`:

```python
"""Tavily: name-to-site resolution, and the local-language leg."""

from typing import Any

from apps.research.providers import SearchRequest
from apps.research.providers.tavily import TavilyProvider


class _Recorder:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, *, payload: dict[str, Any], headers: dict[str, str]) -> dict:
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        return self.response


def _request(**kwargs: Any) -> SearchRequest:
    defaults: dict[str, Any] = {"query": "burs veren vakıflar", "country_code": "TR", "language": "tr"}
    defaults.update(kwargs)
    return SearchRequest(**defaults)


def test_no_language_and_no_filter_by_language_are_sent() -> None:
    """-1.0 point on the German key, -2.3 with filter_by_language, harmful in
    three of four countries. The local language goes in the query text."""
    post = _Recorder({"results": [{"url": "https://vgm.gov.tr/"}]})
    list(TavilyProvider(api_key="k", post=post).search(_request()))
    payload = post.calls[0]["payload"]
    assert "language" not in payload
    assert "filter_by_language" not in payload
    assert "country" not in payload


def test_basic_depth_is_sent_not_advanced() -> None:
    """Advanced costs 2 credits against 1 and measured 5x WORSE at resolution
    (spec 4.13a: basic 10/30, advanced 2/30, advanced returning the Wikipedia
    article instead of the foundation's own site). Depth for the discovery leg
    is unmeasured, so basic is the default there too: the cost is certain and
    the benefit is not."""
    post = _Recorder({"results": []})
    list(TavilyProvider(api_key="k", post=post).search(_request()))
    assert post.calls[0]["payload"]["max_results"] == 20
    assert post.calls[0]["payload"]["search_depth"] == "basic"


def test_the_denylist_is_sent() -> None:
    post = _Recorder({"results": []})
    list(TavilyProvider(api_key="k", post=post).search(_request()))
    assert "mastersportal.com" in post.calls[0]["payload"]["exclude_domains"]


def test_only_urls_are_returned() -> None:
    post = _Recorder({"results": [{"url": "https://vgm.gov.tr/", "content": "snippet", "score": 1}]})
    assert list(TavilyProvider(api_key="k", post=post).search(_request())) == ["https://vgm.gov.tr/"]


def test_candidates_returns_the_top_ten_urls_and_chooses_none_of_them() -> None:
    """Spec 4.13a: the right site was in the top 10 for 22 of 25 names and at
    rank 1 for 3. Selection is a lexical match done beside the register writer;
    the adapter's only job is to hand back the ten, in rank order, as URLs."""
    post = _Recorder({"results": [{"url": f"https://r{i}.example/", "score": 1} for i in range(10)]})
    urls = TavilyProvider(api_key="k", post=post).candidates("Türk Eğitim Vakfı")
    assert urls == [f"https://r{i}.example/" for i in range(10)]
    payload = post.calls[0]["payload"]
    assert payload["query"] == '"Türk Eğitim Vakfı"'
    assert payload["max_results"] == 10
    assert payload["search_depth"] == "basic"
    assert "exact_match" not in payload  # measured neutral (6/25 either way); not worth a 400 risk
    assert "mastersportal.com" in payload["exclude_domains"]


def test_candidates_is_empty_when_nothing_matches() -> None:
    post = _Recorder({"results": []})
    assert TavilyProvider(api_key="k", post=post).candidates("No Such Foundation") == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/providers/test_tavily.py -q
```

- [ ] **Step 3: Write the implementation**

Create `apps/research/providers/tavily.py`:

```python
"""Tavily: name-to-site resolution, host inventory, and the local-language leg.

Its terms are the cleanest of any provider surveyed -- its restrictions attach
to "the Services", which it defines to exclude "Output" -- so its retention is
permitted by structure rather than by silence. That is why it keeps the jobs
where we hold a URL or a name already, and why it is no longer the provider:
provider choice is settled by measurement now (spec 4.13), and Tavily alone
reaches 165 funding-relevant hosts where four indexes reach 507.

`language` and `filter_by_language` are not sent. Measured -1.0 point on the
377-funder German key and -2.3 with the filter, harmful in three of four
countries: they narrow the pool rather than re-ranking it. The local language
belongs in the query text, which is what actually won.

Spec 9.2 takes a perpetual licence over every query string we send, so no
query may carry a student fact. SearchRequest has no field one could travel in.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..domains import AGGREGATOR_DOMAINS
from ..egress import fetch_json_api
from . import SearchRequest

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

#: Tavily's documented maximum for one call.
_MAX_RESULTS = 20

#: basic, not advanced. Advanced costs 2 credits against 1 -- halving a
#: 1,000-credit cycle to 500 calls -- and measured five times WORSE at the job
#: the roster actually gives Tavily: resolving 30 German foundations by name,
#: basic scored 10/30 and advanced 2/30, with advanced returning the Wikipedia
#: article instead of the foundation's own site on five of them. Spec 4.13a.
_DEPTH = "basic"


@dataclass(frozen=True)
class TavilyProvider:
    api_key: str = field(repr=False)
    name: str = "tavily"
    post: Callable[..., dict[str, object]] = field(default=fetch_json_api)

    def _post(self, payload: dict[str, object]) -> Mapping[str, Any]:
        return self.post(
            TAVILY_SEARCH_URL,
            payload=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )

    def search(self, request: SearchRequest) -> Iterator[str]:
        data = self._post(
            {
                "query": request.query,
                "search_depth": _DEPTH,
                "max_results": min(request.max_results, _MAX_RESULTS),
                "exclude_domains": list(request.denylist),
            }
        )
        for item in data.get("results") or []:
            url = str(item.get("url") or "")
            if url:
                yield url

    def candidates(self, organisation_name: str) -> list[str]:
        """The top ten URLs for an organisation named but not linked, in rank order.

        Registers list names without URLs -- the VGM foundation register is the
        motivating case. The adapter does not choose among these: measured on 25
        German foundations, the first result was right 3 times and the best
        lexical match among these ten was right 20 times, on the same responses
        (spec 4.13a). Choosing is the resolver's job, beside the register writer,
        where the name's tokens and the register's own hints are both in hand.
        """
        data = self._post(
            {
                "query": f'"{organisation_name}"',
                "search_depth": _DEPTH,
                "max_results": 10,
                "exclude_domains": list(AGGREGATOR_DOMAINS),
            }
        )
        return [str(item.get("url")) for item in (data.get("results") or []) if item.get("url")]
```

- [ ] **Step 4: Retype `EntityExpansionSource`**

In `apps/research/search.py`, change line 239 from:

```python
    search: SearchSource
```

to:

```python
    #: The protocol, not the concrete Tavily source: this was the 2026-08-28
    #: plan's intent and was never done, and it is what lets an expansion run
    #: on Exa where Exa is the better index for the family.
    search: SearchSource
```

**Leave the type as `SearchSource` for now** and add the comment only. The retype is genuinely blocked: `EntityExpansionSource.find` calls `replace(self.search, name=..., source_type=..., evidence_strength=...)`, which are `SearchSource` fields that `SearchProvider` does not have. Retyping it needs `find` restructured to build a `SearchRequest` instead, and that belongs with the sweep harness (increment 9) which is the only caller that will pass a provider. Record it rather than half-doing it:

Add to `docs/superpowers/specs/2026-09-17-role-routed-discovery-design.md` §13:

```markdown
- **`EntityExpansionSource.search` is still typed `SearchSource`.** §4.6 calls for the protocol,
  and the retype is blocked on `find` calling `dataclasses.replace` with three `SearchSource`
  fields the protocol does not carry (`name`, `source_type`, `evidence_strength`). Doing it needs
  `find` restructured to compose a `SearchRequest`, which belongs with the sweep harness that will
  be its first provider-passing caller. Left typed and commented rather than adapted around, because
  a shim that makes a protocol look like a concrete class is how the seam stops meaning anything.
```

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research -q
```

Expected: PASS, including the existing `test_search.py` which must be unaffected.

- [ ] **Step 6: Commit**

```bash
git add apps/research/providers/tavily.py apps/research/search.py tests/research/providers/test_tavily.py docs/superpowers/specs/2026-09-17-role-routed-discovery-design.md
git commit -m "feat(research): Tavily adapter -- resolution, inventory, local-language leg

language and filter_by_language are not sent: -1.0 and -2.3 points on the
German key and harmful in three of four countries. They narrow the pool
rather than re-ranking it, and the local language belongs in the query text.

resolve() is the name-to-site step the URL-less registers need: the quoted
name, one result, or None. A name resolved to the wrong site is worse than
one left unresolved, because the wrong site then gets fetched and believed.

EntityExpansionSource's retype is recorded as blocked rather than shimmed --
find() replaces three SearchSource fields the protocol does not carry, and a
shim that makes a protocol look like a concrete class empties the seam."
```

---

### Task 9: Per-provider keys, in settings and in the template

`SEARCH_API_KEY` is one generic name holding the Tavily key. Four providers need four keys, and none of them is in `infra/template.yaml` — so live search cannot run deployed at all.

**Files:**
- Modify: `config/settings/base.py:116`
- Modify: `infra/template.yaml`
- Test: `tests/test_bootstrap.py` (extend), `tests/infra/test_template.py` (extend)

**Interfaces:**
- Consumes: nothing.
- Produces: `settings.EXA_API_KEY`, `settings.BRAVE_API_KEY`, `settings.TAVILY_API_KEY`, `settings.FIRECRAWL_API_KEY`, each `""` when unset. `SEARCH_API_KEY` is **kept** as the Tavily fallback so `manage.py discover` and `pool_cv_corpus` keep working.

- [ ] **Step 1: Write the failing test**

Add to `tests/infra/test_template.py`:

```python
def test_the_worker_can_read_every_search_provider_key() -> None:
    """Without these the discovery sweep runs deployed as seed-catalogues-only
    and says so once, in a log line nobody reads. A key that is absent from
    the template is a feature that is silently off in production."""
    template = _template()  # the module's existing loader
    worker = template["Resources"]["WorkerTaskDefinition"]["Properties"]
    secrets = {
        s["Name"] for container in worker["ContainerDefinitions"] for s in container.get("Secrets", [])
    }
    for name in ("EXA_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY", "FIRECRAWL_API_KEY"):
        assert name in secrets, name


def test_the_browser_task_gets_no_search_key() -> None:
    """BrowserTaskDefinition's guarantee is that there is nothing to steal
    (CLAUDE.md). A provider key is something to steal."""
    template = _template()
    browser = template["Resources"]["BrowserTaskDefinition"]["Properties"]
    for container in browser["ContainerDefinitions"]:
        assert not container.get("Secrets")
        assert not container.get("Environment")
```

Add to `tests/test_bootstrap.py`:

```python
def test_every_provider_key_defaults_to_empty() -> None:
    """A missing key must degrade to "this provider is off", never to a crash
    at import time on a developer machine."""
    from django.conf import settings

    for name in ("EXA_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY", "FIRECRAWL_API_KEY"):
        assert isinstance(getattr(settings, name), str)
```

- [ ] **Step 2: Run to verify they fail**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/infra/test_template.py tests/test_bootstrap.py -q
```

Expected: failures naming the missing secrets and the missing settings.

- [ ] **Step 3: Add the settings**

In `config/settings/base.py`, replace line 116:

```python
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
```

with:

```python
#: Kept: `manage.py discover` and `pool_cv_corpus` read it, and it holds the
#: Tavily key today. The four below are the per-provider names the roster
#: needs (spec 4.13) -- one generic name cannot carry four keys with four
#: different auth headers.
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
EXA_API_KEY = os.getenv("EXA_API_KEY", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
#: Falls back to SEARCH_API_KEY, which is where the Tavily key lives today.
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "") or SEARCH_API_KEY
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
```

- [ ] **Step 4: Add them to the template**

In `infra/template.yaml`, find `WorkerTaskDefinition`'s `Secrets` list and add four entries in the same shape as the existing `OPENAI_API_KEY` entry (copy its `ValueFrom` pattern exactly — it references a Secrets Manager secret ARN built from a parameter). Add the corresponding secrets to whatever resource declares them, following the file's existing convention.

**Do not add them to `BrowserTaskDefinition`.** That task has no `TaskRoleArn` and empty `Environment`/`Secrets` by design, and four tests pin it.

- [ ] **Step 5: Validate the template and run the tests**

```bash
uv run cfn-lint infra/template.yaml
POSTGRES_DB=tehsil_progpage uv run pytest tests/infra/test_template.py tests/test_bootstrap.py -q
```

- [ ] **Step 6: Commit**

```bash
git add config/settings/base.py infra/template.yaml tests/infra/test_template.py tests/test_bootstrap.py
git commit -m "feat(config): four provider keys, and they reach the deployed worker

SEARCH_API_KEY is one generic name holding the Tavily key, and it is absent
from infra/template.yaml -- so deployed, discover() prints 'seed catalogues
only, no live search' and runs degraded without failing. A key missing from
the template is a feature silently off in production.

SEARCH_API_KEY is kept as TAVILY_API_KEY's fallback so the two management
commands that read it keep working. A test asserts the browser task still
receives none of them: its whole guarantee is that there is nothing to
steal, and a provider key is something to steal."
```

---

### Task 10: The set-difference sweep, end to end

The task that makes the previous nine into working software: one command that runs the providers for a country, keeps only hosts the register does not hold, and records them.

**Files:**
- Create: `apps/research/management/commands/sweep_organisations.py`
- Test: `tests/research/test_sweep.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `manage.py sweep_organisations --country TR --dry-run`, and `apps/research/sweep.py::sweep_country(providers, *, country_code, query_template, record) -> SweepReport` with `SweepReport(seen: int, novel: int, per_provider: dict[str, int], first_discoverer: dict[str, int])`.

- [ ] **Step 1: Write the failing test**

Create `tests/research/test_sweep.py`:

```python
"""The economic claim, tested: a second index costs its set-difference."""

from collections.abc import Iterable, Iterator

import pytest

from apps.funding.models import Organisation
from apps.research.organisations import record_organisation
from apps.research.providers import SearchRequest
from apps.research.sweep import sweep_country

pytestmark = pytest.mark.django_db


class _Fake:
    def __init__(self, name: str, urls: list[str]) -> None:
        self.name = name
        self._urls = urls
        self.requests: list[SearchRequest] = []

    def search(self, request: SearchRequest) -> Iterator[str]:
        self.requests.append(request)
        yield from self._urls


def _record(**kwargs: object) -> None:
    record_organisation(
        kind=Organisation.Kind.FUNDER_FOUNDATION,
        country_code="TR",
        status=Organisation.Status.CANDIDATE,
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_host_already_held_is_not_recorded_twice() -> None:
    _record(
        domain="tev.org.tr",
        name="tev.org.tr",
        official_website="https://tev.org.tr/",
        found_via="R1:wikidata",
    )
    exa = _Fake("exa", ["https://www.tev.org.tr/burslar", "https://vgm.gov.tr/"])
    report = sweep_country([exa], country_code="TR", query_template="{language_name} burs")

    assert report.seen == 2
    assert report.novel == 1
    assert Organisation.objects.count() == 2


def test_the_second_index_is_charged_only_its_novelty() -> None:
    """Exa and Brave both return tev.org.tr; the register makes that one row
    and attributes the discovery to whoever got there first."""
    exa = _Fake("exa", ["https://tev.org.tr/"])
    brave = _Fake("brave", ["https://tev.org.tr/", "https://vgm.gov.tr/"])
    report = sweep_country([exa, brave], country_code="TR", query_template="{language_name} burs")

    assert report.novel == 2
    assert report.first_discoverer == {"exa": 1, "brave": 1}
    tev = Organisation.objects.get(registrable_domain="tev.org.tr")
    assert sorted(tev.found_via) == ["R4_SEARCH:brave", "R4_SEARCH:exa"]


def test_both_language_passes_run() -> None:
    exa = _Fake("exa", [])
    sweep_country([exa], country_code="TR", query_template="{language_name} burs")
    assert [r.phrasing for r in exa.requests] == ["local", "english"]
    assert exa.requests[0].query == "Turkish burs"


def test_a_url_with_no_registrable_domain_is_counted_and_skipped() -> None:
    exa = _Fake("exa", ["https://192.0.2.1/x", "https://vgm.gov.tr/"])
    report = sweep_country([exa], country_code="TR", query_template="{language_name} burs")
    assert report.seen == 2
    assert report.novel == 1
    assert Organisation.objects.count() == 1


def test_no_query_carries_a_profile_field() -> None:
    """Spec 8, asserted at the one place a query is composed."""
    exa = _Fake("exa", [])
    sweep_country([exa], country_code="TR", query_template="{language_name} burs")
    for request in exa.requests:
        assert set(vars(request)) == {
            "query",
            "country_code",
            "language",
            "phrasing",
            "max_results",
            "denylist",
        }
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/test_sweep.py -q
```

- [ ] **Step 3: Write `apps/research/sweep.py`**

```python
"""One country, every provider, and only the hosts we did not already hold.

This is the design's economic claim made executable: providers are asked in
parallel routes but charged for their set-difference, because the register
answers "new?" before anything is fetched. The per-provider and
first-discoverer tallies are what decide, per cell, when a decaying engine is
dropped -- Brave fell 81 -> 11 first-discoverers across 99 queries while Exa
held steady, and a fixed rule would have dropped the wrong one.

Nothing here fetches an origin or classifies a host. A swept row is a
CANDIDATE with a name equal to its domain; the classifier (spec 4.7) and the
funding reader run afterwards on rows this produced. Keeping discovery and
classification in separate passes is what lets a sweep be re-run cheaply.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from apps.funding.models import Organisation

from .hosts import registrable_domain
from .organisations import record_organisation
from .providers import SearchProvider, requests_for


@dataclass
class SweepReport:
    #: Every URL every provider returned, before dedupe.
    seen: int = 0
    #: Registrable domains recorded that no route held before this sweep.
    novel: int = 0
    #: URLs returned, per provider.
    per_provider: dict[str, int] = field(default_factory=dict)
    #: Novel domains credited to the provider that returned one first.
    first_discoverer: dict[str, int] = field(default_factory=dict)


def sweep_country(
    providers: Sequence[SearchProvider],
    *,
    country_code: str,
    query_template: str,
) -> SweepReport:
    report = SweepReport()
    for request in requests_for(query_template, country_code):
        for provider in providers:
            for url in provider.search(request):
                report.seen += 1
                report.per_provider[provider.name] = report.per_provider.get(provider.name, 0) + 1
                domain = registrable_domain(url)
                if not domain:
                    # Counted in `seen` and skipped: an unkeyable host is a
                    # real provider answer we cannot dedupe, and hiding it
                    # would overstate precision.
                    continue
                _, created = record_organisation(
                    domain=domain,
                    name=domain,
                    kind=Organisation.Kind.FUNDER_FOUNDATION,
                    country_code=country_code.upper(),
                    official_website=url,
                    status=Organisation.Status.CANDIDATE,
                    found_via=f"R4_SEARCH:{provider.name}",
                )
                if created:
                    report.novel += 1
                    report.first_discoverer[provider.name] = (
                        report.first_discoverer.get(provider.name, 0) + 1
                    )
    return report
```

**Note on `kind`:** every swept row is written `FUNDER_FOUNDATION` as a placeholder because the sweep does not classify. That is wrong as a fact and right as a shape — the classifier (§4.7) overwrites it, and a row with no kind cannot satisfy the model's check constraint. If the classifier is not the very next increment, change this to a `CANDIDATE`-only kind instead. Flag it to the reviewer.

- [ ] **Step 4: Write the management command**

Create `apps/research/management/commands/sweep_organisations.py`:

```python
"""Run one country's search sweep and print its tallies.

Providers are constructed from whichever keys are set, so a missing key is a
provider that does not run rather than a crash -- the same degradation
`discover` already uses.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.research.providers import SearchProvider
from apps.research.providers.brave import BraveProvider
from apps.research.providers.exa import ExaProvider
from apps.research.providers.tavily import TavilyProvider
from apps.research.sweep import sweep_country

_TEMPLATE = (
    "An official page from a ministry, foundation or company describing "
    "scholarships for master's study, written in {language_name}"
)


class Command(BaseCommand):
    help = "Sweep one country for funder hosts the register does not hold."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--country", required=True, help="ISO-3166 alpha-2, e.g. TR")
        parser.add_argument("--dry-run", action="store_true", help="Print providers and exit")

    def handle(self, *args: Any, **options: Any) -> None:
        providers: list[SearchProvider] = []
        if settings.EXA_API_KEY:
            providers.append(ExaProvider(api_key=settings.EXA_API_KEY))
        if settings.BRAVE_API_KEY:
            providers.append(BraveProvider(api_key=settings.BRAVE_API_KEY))
        if settings.TAVILY_API_KEY:
            providers.append(TavilyProvider(api_key=settings.TAVILY_API_KEY))
        if not providers:
            raise CommandError("no provider key is set: EXA_API_KEY, BRAVE_API_KEY, TAVILY_API_KEY")

        names = ", ".join(p.name for p in providers)
        if options["dry_run"]:
            self.stdout.write(f"would sweep {options['country']} with: {names}")
            return

        report = sweep_country(
            providers, country_code=options["country"], query_template=_TEMPLATE
        )
        self.stdout.write(f"providers: {names}")
        self.stdout.write(f"urls seen: {report.seen}")
        self.stdout.write(f"novel domains: {report.novel}")
        self.stdout.write(f"per provider: {report.per_provider}")
        self.stdout.write(f"first discoverer: {report.first_discoverer}")
```

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research -q
```

Expected: PASS.

- [ ] **Step 6: Verify the command runs without keys and refuses cleanly**

```bash
EXA_API_KEY= BRAVE_API_KEY= TAVILY_API_KEY= SEARCH_API_KEY= uv run python manage.py sweep_organisations --country TR --dry-run; echo "exit=$?"
```

Expected: `CommandError: no provider key is set: ...` and `exit=1`.

- [ ] **Step 7: Verify it runs with keys, dry**

```bash
set -a; . ~/.config/tehsil_agent/search.env; set +a
uv run python manage.py sweep_organisations --country TR --dry-run
```

Expected: `would sweep TR with: exa, brave, tavily`.

- [ ] **Step 8: Full suite, lint, type-check**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest -q
uv run ruff check apps tests config
uv run mypy apps
uv run python manage.py makemigrations --check --dry-run
```

- [ ] **Step 9: Commit**

```bash
git add apps/research/sweep.py apps/research/management/commands/sweep_organisations.py tests/research/test_sweep.py
git commit -m "feat(research): sweep a country, pay for the set-difference

The design's economic claim made executable: providers are asked on parallel
routes and charged for their novelty, because the register answers 'new?'
before anything is fetched. Per-provider and first-discoverer tallies are
kept because they are what decides when a decaying engine is dropped -- Brave
fell 81 -> 11 first-discoverers across 99 queries while Exa held steady, so a
fixed rule would have dropped the wrong one.

A URL with no registrable domain is counted and skipped rather than dropped
silently: it is a real provider answer we cannot dedupe, and hiding it would
overstate precision."
```

---

## Self-Review

**Spec coverage (§4.1, §4.6, §4.13, §8, §9):**

| spec requirement | task |
|---|---|
| §4.1 Organisation, registrable-domain key, kinds, statuses, `found_via`, identifiers | 1, 2 |
| §4.1 shared catalog, `_SHARED_TABLES`, `catalog_ingestion` | 2 |
| §4.1 `Institution` unchanged, nullable one-way link | 2 |
| §4.6 `SearchProvider` protocol, `SearchRequest`, URL-only | 5 |
| §4.6 `AGGREGATOR_DOMAINS`, steering table, `found_via` route tags | 4, 3 |
| §4.6 Tavily wiring fixed (`max_results` 20, `search_depth`, denylist) | 8 |
| §4.6 `EntityExpansionSource` retype | 8 — **recorded as blocked**, with the reason |
| §4.13 Exa `numResults: 100`, no `category`, no `includeText` | 6 |
| §4.13 Brave offset paging, Goggle, no `country`/`search_lang` | 7 |
| §4.13 Tavily no `language`/`filter_by_language`, `exact_match` resolve | 8 |
| §8 profile-free queries, asserted | 5, 10 |
| Deployed keys (handoff blocker) | 9 |
| Set-difference / dedupe | 3, 10 |

**Not in this plan, by design:** registries (increment 3), host inventory (4), hub harvesting (5), the classifier (§4.7), Diffbot, Firecrawl, the Goggle's hosting, and the option card (6–7). Increments 3–5 are a second plan; they consume `record_organisation` and `known_domains` from Task 3 and need nothing else from here.

**Known gaps deliberately left, each flagged in its task:**
1. Task 10 writes `kind=FUNDER_FOUNDATION` as a placeholder because the sweep does not classify. Correct only if the classifier is the next increment.
2. Task 7's Goggle is committed but not hosted, so the parameter is omitted. Costs precision, never recall.
3. Task 8 does not retype `EntityExpansionSource`; the reason is recorded in the spec rather than worked around with a shim.
4. `fetch_json_api` may not support GET with `params` (Task 7, Step 5). If not, extend it — never bypass `egress.py`, which is where `validate_public_url` runs.
5. `candidates()` (Task 8) hands back ten URLs and picks none. The resolver — Wikidata P856 first,
   tiered lexical best-match over the ten, an origin title check requiring **org-type agreement**,
   unresolved on mismatch, fetch failure or a one-token name — reached German 20/0/5 and Turkish
   12/1/12 hand-tuned, and **its generalised form FAILED a blind Georgian/Kazakh acceptance test**
   (spec §4.13b: KZ 1/11/13). Six general rules are recorded there; the next version is measured
   on a fresh hold-out before it enters an adapter. It lands with the registries plan, not this
   one. Read spec §7a before starting increments 3–5.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-18-organisation-register-and-provider-protocol.md`. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — tasks executed in this session with checkpoints for review.

Which approach?

---

## Amendments, 2026-09-18 evening (tool audit and yield measurement)

Read with the tasks above; each is a small change to the task named.

- **Task 6 (Exa adapter):** `search()` also accepts `include_domains: tuple[str, ...] = ()` and
  `highlights: bool = False` on `SearchRequest` (or as adapter kwargs) — `includeDomains` per
  registered institution is the measured first pass for hidden gems (TUM, METU, $0.022 each), and
  `contents.highlights` is transient triage, never stored. `findSimilar` is live (not deprecated);
  add `similar(url) -> Iterator[str]` beside `search()`. Audit:
  `research/2026-09-18-tool-capability-oversights.md`.
- **Task 8 (Tavily adapter):** `search_depth: "basic"` (measured; `advanced` is 5× worse at resolution
  and costs double). `candidates()` returns the ten URLs and picks none.
- **Task 3 (`record_organisation`):** add `names: list[str]` — every label a register or Wikidata
  supplies — the `Organisation.names` column from Task 2's amendment.
- **New step in the resolution ladder, not in this plan:** Diffbot Enhance by name on the unresolved
  residue (7/10 measured), confidence-gated, title-checked, within the free 400/month.
- **Task 9 (keys):** add `DIFFBOT_TOKEN` and `FIRECRAWL_API_KEY` is already listed; the worker also
  needs them; the browser task still gets none.
- **Reader interface this plan will meet:** `FundingOpportunity.holder_domain` (registrable domain)
  is how holder awards join `Organisation` — `apps/research/hosts.py::registrable_domain` is
  duplicated verbatim on the reader branch by its plan (Task 5 there) so the merge is clean.

---

## Amendments, 2026-09-18 night (vendor-per-axis review; the owner's China/Korea catch)

Evidence: `research/2026-09-18-vendor-per-axis-proposal-review.md`. Owner's rule the same day: the
engine is **general** — any country, script, family; per-country numbers are development scores;
acceptance is a blind hold-out on a different script. Each amendment below was checked against it.

- **Task 6 (Exa adapter) — K1, one measured step before the per-institution pass ships.** Exa now
  documents `includeDomains` entries as a hostname, a hostname with a path prefix, or a wildcard
  subdomain (`*.example.com`). Run the D.5 query once with `["metu.edu.tr"]` and once with
  `["*.metu.edu.tr"]`, `numResults: 25`, and compare the *set of on-host result hosts* (transient;
  nothing stored; ≈ $0.05). If the bare hostname already matches subdomains the knob is moot and the
  adapter sends the bare registrable domain; if not, it sends both forms for every institution.
  General by construction: the input is `registrable_domain()` from Task 1, the same for
  `metu.edu.tr`, `ox.ac.uk` and `uni-heidelberg.de`.
- **Task 7 (Brave adapter) — K2, boolean phrasing, measured before adoption.** Brave documents
  `AND` / `OR` / `NOT`, `-`, `""`, `site:` — and **no wildcard `site:`**. One phrasing variant that
  ORs a language's terms of art (`"burs" OR "hibe" OR "vakıf"`) could cover a vocabulary in one
  request instead of several. Score it the ablation's way — first-discoverer count *per request* on
  the German 377-funder key (development, ≈ 30 requests) — then, before it enters `Steering`, one
  different-script query (Georgian or Chinese) confirming the operator tokens still act as operators
  amid non-Latin text. Adopt only if both hold. Also: Brave accepts the Goggle **inline** (`goggles`
  takes a definition string — audit §2), so `goggle_url` can carry the committed file's contents and
  the hosting question is closed; the spec §13 caveat about HTTP 422 on a long rule set is what the
  first live call checks.
- **Task 8 (Tavily adapter) — K3, considered and dropped.** Tavily's `include_domains` now has a
  `prefer` mode (boost, not filter, ≤ 300 domains). It needs a concrete per-country domain list —
  the enum knowledge Task 4's steering table deliberately carries none of — and it boosts hosts the
  register already holds while the sweep pays for hosts it does not. For known hosts Exa
  `includeDomains` is the measured tool. Not built; recorded so it is not re-proposed.
- **Task 10 (sweep) — H1, reshaped.** The probe's per-family origin share (Brave-with-Goggle 89% vs
  Exa 66% on Government) suggested "Brave first on government". As a fixed rule it is a one-run,
  20-query reading and fails the generality test; the design's per-cell tally is the general form.
  What Task 10 must carry for that to be measurable: `SweepReport.first_discoverer` is keyed by
  provider only — when the query set becomes per family (§4.12), key it by `(family, provider)`, or
  no family-level ordering can ever be read off the data.
- **Task 4 (steering)** gains `CN` (`zh`) and `KR` (`ko`) rows — the language of the query text
  only, as for every other country.
- **Task 9 (keys)** gains `SERPAPI_API_KEY` in the settings, both test loops and the template (it
  already exists under that name in this machine's environment). The browser task still gets none.
- **Self-review table** gains: §4.13 Baidu and Naver → Task 11.

### Task 11: The regional engines — Baidu and Naver through SerpApi (owner decision 2026-09-18)

The roster adopted both on 2026-09-17 (ablation §7: Baidu +7 Chinese institutions from three
searches at 76% precision; Naver +5 Korean funders including two foundations) and this plan never
built them — the owner caught it. **Decision 2026-09-18: build both through SerpApi on its free tier
(250 searches a month), now.** Stated plainly, because it is the position the roster ruled out for
Google: SerpApi resells indexes it has no rights to grant, and its U.S. Legal Shield applies only
from the Production plan ($150/month, verified on `serpapi.com/pricing` 2026-09-18) — on the free
tier there is none. The owner accepted that with the concern raised. Two remedies stay open in spec
§13: Naver's own developer API (a direct contract; `developers.naver.com` refused this session's
fetch, so its terms and limits are read on the cited host before it is preferred) and the Production
tier if volume or exposure grows.

**The rule that keeps this general.** A regional engine is added for a country only where the
measured rule holds — the national web is **large** *and* **partly outside the global indexes'
reach** (ablation §6–7) — never because a country has a popular engine. Measured in: China
(policy-separated), Korea (platform-concentrated). Measured out: Yandex for Azerbaijan (0), Seznam,
Coc Coc, Google via SerpApi (+2 / +1). Adding a country is one row in `REGIONAL_ENGINES` and, if the
engine's parameter names differ, one row in the adapter's engine table; no other code moves.

**Files:**
- Create: `apps/research/providers/serpapi.py`
- Modify: `apps/research/domains.py` (`REGIONAL_ENGINES`)
- Modify: `apps/research/management/commands/sweep_organisations.py` (Task 10's command adds the
  regional provider for the country)
- Test: `tests/research/providers/test_serpapi.py`; `tests/research/test_domains.py` (extend)

**Interfaces:**
- Consumes: `SearchRequest`, `SearchProvider` (Task 5); the GET path of `fetch_json_api` (Task 7,
  Step 5 — `fetch_json_api` is POST-only today); `settings.SERPAPI_API_KEY` (Task 9).
- Produces: `SerpApiProvider(api_key: str, engine: Literal["baidu", "naver"], get=fetch_json_api)`
  with `name = engine` — so `found_via` reads `R4_SEARCH:baidu` / `R4_SEARCH:naver`, the *index*,
  with the reseller recorded once in spec §8's terms row and never as a tag — and
  `search(request) -> Iterator[str]`; `REGIONAL_ENGINES: dict[str, str] = {"CN": "baidu", "KR": "naver"}`.

**The two engines' shapes** (`serpapi.com/baidu-search-api`, `serpapi.com/naver-search-api`, read
2026-09-18): both `GET https://serpapi.com/search.json`. Baidu: `engine=baidu`, query in `q`,
`rn` ≤ 50 results per page, `pn` offset; results at `organic_results[].link`. Naver: `engine=naver`,
query in `query`, `where=web`, `start` / `page`; results at `web_results[].link`. **The key travels
as the `api_key` query parameter** — the one provider here whose credential is in the URL — so the
adapter passes it through `params`, and a test asserts it appears in no `repr`, no log record and no
exception message; if `egress.py` logs the request URL, redact `api_key` there first.

**Depth on the free tier:** one page per query at the engine's maximum page size (Baidu `rn=50`;
Naver's web page as served). `# ponytail: single page on the free 250/month; add the pn/page loop
when a paid tier exists` — the ablation's +7 came from three single-page searches. SerpApi offers no
exclude-domains parameter for these engines; the sweep's existing denylist filter applies after the
adapter.

- [ ] **Step 1: Write the failing tests**

Create `tests/research/providers/test_serpapi.py`:

```python
"""Baidu and Naver through SerpApi: the regional route, for two countries."""

from typing import Any

import pytest

from apps.research.providers import SearchRequest
from apps.research.providers.serpapi import SerpApiProvider


class _Recorder:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, *, params: dict[str, Any], headers: dict[str, str]) -> dict:
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.response


def _request(**kwargs: Any) -> SearchRequest:
    defaults: dict[str, Any] = {"query": "留学生 奖学金 硕士", "country_code": "CN", "language": "zh"}
    defaults.update(kwargs)
    return SearchRequest(**defaults)


def test_baidu_reads_organic_results_and_returns_only_urls() -> None:
    get = _Recorder({"organic_results": [{"link": "https://xjtu.edu.cn/", "title": "t", "snippet": "s"}]})
    urls = list(SerpApiProvider(api_key="k", engine="baidu", get=get).search(_request()))
    assert urls == ["https://xjtu.edu.cn/"]
    params = get.calls[0]["params"]
    assert params["engine"] == "baidu" and params["q"] == "留学生 奖学金 硕士" and params["rn"] == 50


def test_naver_reads_web_results_with_where_web() -> None:
    get = _Recorder({"web_results": [{"link": "https://daesangfoundation.or.kr/", "title": "t"}]})
    req = _request(query="외국인 유학생 장학금 석사", country_code="KR", language="ko")
    urls = list(SerpApiProvider(api_key="k", engine="naver", get=get).search(req))
    assert urls == ["https://daesangfoundation.or.kr/"]
    params = get.calls[0]["params"]
    assert params["engine"] == "naver" and params["query"] == req.query and params["where"] == "web"


def test_the_provider_name_is_the_engine_not_the_reseller() -> None:
    """found_via must read R4_SEARCH:baidu -- the index that was searched, so
    the tally and the terms record name the same thing."""
    assert SerpApiProvider(api_key="k", engine="baidu").name == "baidu"
    assert SerpApiProvider(api_key="k", engine="naver").name == "naver"


def test_google_is_refused() -> None:
    """Google via SerpApi is the transient yardstick and may never write a
    catalog row (spec 4.13). A closed literal makes that a construction
    error, not a convention."""
    with pytest.raises((ValueError, TypeError)):
        SerpApiProvider(api_key="k", engine="google")  # type: ignore[arg-type]


def test_the_key_is_a_query_parameter_and_never_in_repr_or_str() -> None:
    get = _Recorder({"organic_results": []})
    provider = SerpApiProvider(api_key="secret", engine="baidu", get=get)
    list(provider.search(_request()))
    assert get.calls[0]["params"]["api_key"] == "secret"
    assert "secret" not in repr(provider) and "secret" not in str(provider)


def test_an_empty_or_error_response_yields_nothing() -> None:
    get = _Recorder({"error": "Baidu hasn't returned any results for this query."})
    assert list(SerpApiProvider(api_key="k", engine="baidu", get=get).search(_request())) == []
```

Add to `tests/research/test_domains.py`:

```python
def test_regional_engines_exist_only_where_the_rule_was_measured() -> None:
    """Large national web AND partly outside the global indexes' reach
    (ablation 6-7). Measured in: CN, KR. Measured out: AZ (Yandex 0), CZ, VN."""
    from apps.research.domains import REGIONAL_ENGINES

    assert REGIONAL_ENGINES == {"CN": "baidu", "KR": "naver"}
    for code in ("AZ", "CZ", "VN", "DE", "TR"):
        assert code not in REGIONAL_ENGINES
```

- [ ] **Step 2: Run them to verify they fail**

```bash
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/providers/test_serpapi.py tests/research/test_domains.py -q
```

Expected: `ModuleNotFoundError: No module named 'apps.research.providers.serpapi'`, then `ImportError` on `REGIONAL_ENGINES`.

- [ ] **Step 3: Write the adapter**

`apps/research/providers/serpapi.py`: a frozen dataclass like Task 6's, `api_key` a
`field(repr=False)`, `engine: Literal["baidu", "naver"]` checked in `__post_init__` (raise
`ValueError` for anything else), `name` a property returning the engine. One table carries the two
engines' differences — `_ENGINES = {"baidu": ("q", {"rn": 50}, "organic_results"), "naver":
("query", {"where": "web"}, "web_results")}` — and `search()` builds `params` from the row plus
`api_key`, calls `self.get("https://serpapi.com/search.json", params=params, headers={})`, and
yields `str(item.get("link") or "")` when non-empty from `data.get(results_key) or []`. The module
docstring carries the ablation numbers, the terms position and the generality rule from this task,
so the next reader does not re-derive any of the three.

- [ ] **Step 4: The route table and the sweep**

`apps/research/domains.py`: `REGIONAL_ENGINES` with the rule as its comment.
`sweep_organisations.py`: when `settings.SERPAPI_API_KEY` and `REGIONAL_ENGINES.get(country)` both
exist, append `SerpApiProvider(api_key=settings.SERPAPI_API_KEY, engine=...)` to the providers.

- [ ] **Step 5: Live check — at most 6 of the month's 250**

The three Chinese and three Korean queries of ablation §7, `--dry-run`. Expect Chinese and Korean
institutions at the top of each; record novel hosts against the register in the tally and confirm
`first_discoverer` carries `baidu` / `naver` entries. Nothing from a response is kept.

- [ ] **Step 6: Lint, type-check, test, commit**

```bash
uv run ruff check apps/research/providers/serpapi.py apps/research/domains.py tests/research/providers/test_serpapi.py tests/research/test_domains.py
uv run mypy apps/research/providers/serpapi.py apps/research/domains.py
POSTGRES_DB=tehsil_progpage uv run pytest tests/research/providers tests/research/test_domains.py -q
git add apps/research/providers/serpapi.py apps/research/domains.py apps/research/management/commands/sweep_organisations.py tests/research/providers/test_serpapi.py tests/research/test_domains.py
git commit -m "feat(research): Baidu and Naver through SerpApi, for the two countries the rule was measured on

A regional engine pays where the national web is large and partly outside
the global indexes' reach: Baidu added 7 Chinese institutions from three
searches at 76% precision, Naver 5 Korean funders including two foundations,
while Yandex added zero in Azerbaijan and Google via SerpApi +2/+1. So the
route is a per-country table populated only by that measurement, and adding
a country is one row.

Free tier by owner decision 2026-09-18, with the position stated: no Legal
Shield below SerpApi's Production plan, and a reseller cannot grant rights
to the indexes it resells. Google stays a construction error here -- it is
the yardstick, never a catalog source."
```
