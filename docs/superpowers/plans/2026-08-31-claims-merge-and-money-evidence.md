# Claims Merge and Money Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pool a programme's pages so a host that states its five gate facts across several pages writes a catalog row, and stop a money claim from inventing a currency it never read.

**Architecture:** `resolve_program` needs five facts from one `ExtractedClaims` and returns `None` otherwise, discarding everything else the page said. Pages of one programme now pool those five facts — and only those five — after the queue drains; every `OfficialEvidenceClaim` stays attached to its own snapshot, so provenance is untouched. Separately, a currency is validated against the ISO 4217 set the database already enforces, and a money claim must quote the sentence it came from. Every rejection happens in the catalog writer, never in the Pydantic schema.

**Tech Stack:** Python 3.12, Django, Pydantic v2, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-30-claims-merge-and-money-evidence-design.md`

## Global Constraints

- **PREREQUISITE: PR #35 must be merged before Task 1.** Task 1 edits the hop at `apps/research/pipeline.py:234`, which reads `replace(lead, canonical_url=url, identity=None)` only after commit `eb7f450`. On `master` that line still reads `identity=lead.identity`. Verify with `grep -c 'identity=None' apps/research/pipeline.py` — expect `1`, not `0`.
- **Repo gate before any commit is claimed done:** `uv run pytest -q`, `uv run ruff check .`, `uv run mypy apps config`.
- **NEVER run `black` or `ruff format`.** This repo is lint-only; `ruff format` rewrites 26 unrelated files.
- **Checks live in the catalog writer, never in the Pydantic schema.** A schema validator rejects the whole response over one field — the date defect discarded 13 pages' worth of institutions and funding claims to punish one date. Specifically: **do not "tighten" the four `^[A-Z]{3}$` currency patterns** at `apps/research/extraction.py:41,162,213,294` into ISO membership. They stay as cheap shape gates.
- **`MoneyClaim.currency` stays required in the schema.** The spec notes that
  `EligibilityCriterionClaim` already models "a number that might be a duration" with an
  optional currency plus a validator. That pattern is borrowed as *rationale*, not copied as a
  field change: making `currency` optional would move the decision back into the schema, and
  the rule above puts every rejection in the writer. A duration wearing money is dropped by
  Tasks 4 and 5, which is the outcome the spec asks for under "Not building: a duration claim
  type".
- **Claims never pool.** Only `resolve_program`'s five inputs pool. Every `OfficialEvidenceClaim` stays attached to the snapshot it was extracted from.
- `Institution` and `Program` are shared-catalog tables read by every tenant (`tests/tenancy/test_database_isolation.py::_SHARED_TABLES`).
- No new LLM-calling surface is introduced; the existing `rate_limited("discovery-extraction", ...)` at `pipeline.py:308` already covers the only model call.
- **Corpus and harness, preserved outside the repo** (they are third-party page content and stay out of git):
  - `~/.local/share/tehsil_agent/2026-08-30-eacea-claims.jsonl` — 595 cached extractions
  - `~/.local/share/tehsil_agent/eacea-cache/` — the fetched page bodies (161 MB)
  - `~/.local/share/tehsil_agent/eacea_run.py` — the two-pass shadow-run harness; `pass2` replays with no network
- **Do not re-run the full extraction.** It is 595 calls / 2.19 M in / 445 k output tokens, made 2026-08-30.

### Correction to the spec's expected outcome — read before Task 3

The spec's summary line says "8 → 23 rows". **The correct figure under the spec's own mechanics is 24 hosts.** The 23 came from `25 completable − 2 conflicts`, which double-counts NTNU: NTNU has a page that completes on its own, so it already writes today and keeps its row; only its held pages are refused. Re-measured over the corpus:

| | hosts |
|---|---|
| write today (≥1 page complete alone) | 8 |
| newly completed by pooling held pages | **+16** |
| union-complete but refused on a conflict | 1 (`life.univ-cotedazur.eu`, durations `[6, 36]`) |
| **expected after the change** | **24** |

The spec's *mechanics* are unchanged and were approved as written; only this arithmetic is corrected. Task 3's acceptance criterion uses 24.

---

### Task 1: A lead carries its source's one-programme-per-link promise

**Files:**
- Modify: `apps/research/discovery.py:78-116` (`ResearchLead`, `from_url`), `:129-141` (`LeadSource`), `:361-374` (`_tagged`)
- Modify: `apps/research/seeds.py:28-52` (`HtmlCatalogue`), `:105-113` (`EACEA_ERASMUS_MUNDUS`)
- Modify: `apps/research/search.py:75` (`SearchSource`), `:234` (`EntityExpansionSource`)
- Modify: `apps/research/pipeline.py:192-198` (the rebuild), `:233-236` (the hop)
- Modify: `tests/research/test_lead_sources.py:15-27` (the `FixedSource` double)
- Test: `tests/research/test_lead_sources.py`, `tests/research/test_discovery_pipeline.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `ResearchLead.one_programme_per_site: bool` (default `False`)
  - `ResearchLead.from_url(..., one_programme_per_site: bool = False)`
  - `LeadSource.one_programme_per_link` — read-only `@property` on the Protocol
  - `HtmlCatalogue.one_programme_per_link: bool = False`

- [ ] **Step 1: Write the failing tests**

Add to `tests/research/test_lead_sources.py`:

```python
def test_a_vouching_source_stamps_its_leads() -> None:
    class Vouching(FixedSource):
        one_programme_per_link = True

    leads = collect_leads([Vouching("seed:eacea", ["https://a.example/one"])], QUERY)

    assert leads[0].one_programme_per_site is True


def test_a_source_that_does_not_vouch_leaves_its_leads_unpoolable() -> None:
    leads = collect_leads([FixedSource("search", ["https://a.example/one"])], QUERY)

    assert leads[0].one_programme_per_site is False


def test_a_lead_that_lands_on_a_catalogue_cannot_be_pooled() -> None:
    # A catalogue page is not one programme's site whatever the source promised,
    # and it cannot support a claim either -- the two must not disagree.
    lead = ResearchLead.from_url(
        "https://www.mastersportal.com/studies/1234",
        source_type="PROGRAM",
        funding_family="MULTILATERAL",
        one_programme_per_site=True,
    )

    assert lead.source_type == "AGGREGATOR"
    assert lead.can_support_claim is False
    assert lead.one_programme_per_site is False
```

Add to `tests/research/test_discovery_pipeline.py`:

```python
def test_a_hopped_page_inherits_the_pooling_promise() -> None:
    # The hop drops identity (one host serves many programmes) but keeps the
    # promise: same host, same source, so its pages describe one programme.
    lead = ResearchLead.from_url(
        "https://consortium.eu/",
        source_type="PROGRAM",
        funding_family="MULTILATERAL",
        one_programme_per_site=True,
    )

    hopped = replace(lead, canonical_url="https://consortium.eu/scholarships", identity=None)

    assert hopped.one_programme_per_site is True
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/research/test_lead_sources.py -k pool -v
uv run pytest tests/research/test_discovery_pipeline.py -k pooling_promise -v
```
Expected: FAIL — `TypeError: ResearchLead.from_url() got an unexpected keyword argument 'one_programme_per_site'` and `AttributeError: 'ResearchLead' object has no attribute 'one_programme_per_site'`.

- [ ] **Step 3: Add the field to `ResearchLead`**

In `apps/research/discovery.py`, after `identity: LeadIdentity | None = None`:

```python
    #: Whether the source that produced this lead promises one programme per
    #: link. Only such leads may pool their pages' gate facts: a university host
    #: serving forty programmes must never merge one page's institution with
    #: another page's duration. Set by _tagged from the source, never by a
    #: caller -- a lead cannot promote itself, the same way from_url only ever
    #: downgrades source_type.
    one_programme_per_site: bool = False
```

- [ ] **Step 4: Thread it through `from_url`**

Add the keyword parameter and pass it as the final positional argument to `cls(...)`:

```python
        identity: LeadIdentity | None = None,
        one_programme_per_site: bool = False,
    ) -> "ResearchLead":
```

and, as the last argument of the `return cls(...)` call, after `identity`:

```python
            # A catalogue page is not one programme's site whatever the source
            # promised, and it may not support a claim anyway (§2.5).
            one_programme_per_site and not aggregator,
```

- [ ] **Step 5: Declare it on the `LeadSource` Protocol**

In `apps/research/discovery.py`, inside `class LeadSource(Protocol)`, between `name` and `find`:

```python
    @property
    def one_programme_per_link(self) -> bool: ...
```

A read-only `@property`, not a plain attribute, for the reason that class's own docstring already records: every implementation is a frozen dataclass, and mypy refuses a frozen field against a settable protocol member.

- [ ] **Step 6: Stamp it in `_tagged`**

Replace the body of the `for` loop in `_tagged`:

```python
        for lead in source.find(query):
            tagged = lead if lead.discovered_by else replace(lead, discovered_by=source.name)
            yield (
                replace(tagged, one_programme_per_site=True)
                if source.one_programme_per_link and tagged.can_support_claim
                else tagged
            )
```

- [ ] **Step 7: Give the three concrete sources the field**

`apps/research/seeds.py`, in `HtmlCatalogue`'s field list:

```python
    #: Whether each harvested link is one programme's own site. EACEA's listing
    #: is one row per EMJM consortium, so the pages behind one of its links
    #: describe one programme and may pool their gate facts. A catalogue whose
    #: links are institution front doors must leave this False.
    one_programme_per_link: bool = False
```

`apps/research/seeds.py`, in `EACEA_ERASMUS_MUNDUS(...)`, add:

```python
    one_programme_per_link=True,
```

`apps/research/search.py`, in both `SearchSource` and `EntityExpansionSource`:

```python
    #: A search hit is one page, not one programme's site.
    one_programme_per_link: bool = False
```

`tests/research/test_lead_sources.py`, on `FixedSource` as a **class attribute** — not in
`__init__`. `FixedSource` assigns its attributes in `__init__`, and an instance attribute would
shadow the `one_programme_per_link = True` that this task's own `Vouching` subclass sets, making
the test fail for a reason that has nothing to do with the code:

```python
class FixedSource:
    """A LeadSource that yields recorded URLs and counts how far it was consumed."""

    one_programme_per_link = False

    def __init__(self, name: str, urls: Iterable[str]) -> None:
```

`tests/research/test_discovery_pipeline.py`, in `StaticSource`, beside its `name` class attribute:

```python
    one_programme_per_link = False
```

Both doubles are read by `_tagged` at runtime; without the attribute every existing pipeline test raises `AttributeError`.

- [ ] **Step 8: Carry it across the pipeline's rebuild**

`apps/research/pipeline.py`, in the `ResearchLead.from_url(...)` rebuild, after `identity=lead.identity,`:

```python
                one_programme_per_site=lead.one_programme_per_site,
```

The hop below needs no change — `replace()` already carries the flag, which is correct: same host, same source. Add one line to its existing comment so nobody "fixes" it:

```python
                # identity is dropped but one_programme_per_site is kept: the
                # catalogue vouched for the site being one programme, and a page
                # inside it is still that programme's page.
```

- [ ] **Step 9: Run the tests to verify they pass**

```bash
uv run pytest tests/research/test_lead_sources.py tests/research/test_discovery_pipeline.py -q
```
Expected: PASS.

- [ ] **Step 10: Run the full gate**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy apps config
```
Expected: all pass; test count is the previous total plus 4.

- [ ] **Step 11: Commit**

```bash
git add apps/research/discovery.py apps/research/seeds.py apps/research/search.py \
        apps/research/pipeline.py tests/research/test_lead_sources.py \
        tests/research/test_discovery_pipeline.py
git commit -m "feat(research): a lead carries whether its source promises one programme per link"
```

---

### Task 2: Pool a group's gate facts, without touching its claims

**Files:**
- Modify: `apps/research/catalog.py` (add `pool_claims` and `_front_door` after `resolve_program`, ~line 98; add the `program_facts` parameter to `write_catalog_entry`, ~line 278)
- Test: `tests/research/test_catalog_writer.py`

**Interfaces:**
- Consumes: nothing from Task 1 (this task is pure logic plus one optional parameter).
- Produces:
  - `pool_claims(pages: Sequence[ExtractedClaims]) -> ExtractedClaims | None` — `pages[0]` is the front door, in queue order. `None` means a factual conflict refuses the group.
  - `write_catalog_entry(..., program_facts: ResolvedProgram | None = None)` — when supplied, the pooled facts drive the row and `claims` still supplies the claim text.

- [ ] **Step 1: Write the failing tests**

Add to `tests/research/test_catalog_writer.py`:

```python
def _page(**fields: object) -> ExtractedClaims:
    return ExtractedClaims(confidence=0.9, **fields)  # type: ignore[arg-type]


def test_a_name_takes_the_front_doors_version() -> None:
    # 21 of 25 completable hosts disagree on programme name and 11 on
    # institution -- always as variants, never as contradictions.
    front = _page(institution_name="University of Padua", program_name="CCD-STeDe")
    other = _page(
        institution_name="Università degli Studi di Padova",
        program_name="CCD-STeDe: Sustainable Territorial Development",
    )

    pooled = pool_claims((front, other))

    assert pooled is not None
    assert pooled.institution_name == "University of Padua"
    assert pooled.program_name == "CCD-STeDe"


def test_a_field_the_front_door_omits_is_taken_from_a_later_page() -> None:
    front = _page(institution_name="NTNU")
    other = _page(program_name="Coastal Engineering", duration_months=24, country_code="NO")

    pooled = pool_claims((front, other))

    assert pooled is not None
    assert pooled.institution_name == "NTNU"
    assert pooled.program_name == "Coastal Engineering"
    assert pooled.duration_months == 24
    assert pooled.country_code == "NO"


def test_a_contradicted_duration_refuses_the_whole_group() -> None:
    # life.univ-cotedazur.eu states 6 on one page and 36 on another. Picking a
    # winner invents the fact this increment exists to stop.
    assert pool_claims((_page(duration_months=6), _page(duration_months=36))) is None


def test_a_contradicted_country_refuses_the_whole_group() -> None:
    assert pool_claims((_page(country_code="FR"), _page(country_code="IT"))) is None


def test_languages_from_every_page_survive_the_pool() -> None:
    front = _page(
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        )
    )
    other = _page(
        teaching_languages=(
            TeachingLanguageClaim(language="French", evidence="Enseigné en français."),
        )
    )

    pooled = pool_claims((front, other))

    assert pooled is not None
    assert [claim.language for claim in pooled.teaching_languages] == ["English", "French"]


def test_pooled_facts_drive_the_row_while_the_page_still_supplies_its_own_claims(
    source: OfficialSource, snapshot: OfficialSourceSnapshot
) -> None:
    # The whole point of pooling only the gate: a held page's claims must cite
    # the page they came from, never the front door's.
    lead = ResearchLead.from_url(
        "https://consortium.eu/scholarships",
        source_type="PROGRAM",
        funding_family="MULTILATERAL",
    )
    facts = ResolvedProgram(
        institution_name="Consortium University",
        country_code="NO",
        city="",
        program_name="Coastal Engineering",
        degree_level="MASTER",
        teaching_languages=("English",),
        duration_months=24,
    )
    page_claims = ExtractedClaims(
        confidence=0.9,
        benefits=(
            MoneyClaim(
                label="stipend", amount=Decimal("1400.00"), currency="EUR", period="monthly"
            ),
        ),
    )

    result = write_catalog_entry(
        lead=lead,
        claims=page_claims,
        source=source,
        snapshot=snapshot,
        program_facts=facts,
    )

    assert result is not None
    assert result.program.name == "Coastal Engineering"
    assert any("stipend" in claim.claim for claim in result.claims)
    assert all(claim.snapshot_id == snapshot.id for claim in result.claims)
```

Add `pool_claims` and `ResolvedProgram` to the `apps.research.catalog` import block, and `Decimal` is already imported.

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/research/test_catalog_writer.py -k "pool or front_door or contradicted or languages_from" -v
```
Expected: FAIL — `ImportError: cannot import name 'pool_claims'`.

- [ ] **Step 3: Implement `pool_claims`**

In `apps/research/catalog.py`, immediately after `resolve_program`:

```python
def _front_door(values: Iterable[str | None]) -> str | None:
    """The first page that states the field wins -- pages arrive in queue order."""
    return next((value for value in values if value), None)


def pool_claims(pages: Sequence[ExtractedClaims]) -> ExtractedClaims | None:
    """Pool one programme's pages into the five facts resolve_program gates on.

    Only the gate fields pool. Claims never do -- every OfficialEvidenceClaim
    stays attached to the snapshot it was extracted from, so this result is used
    for nothing but the gate, and a held page still writes its own claim text.

    Names and facts are treated differently on purpose. Across the 25 hosts a
    union completes, the two name fields disagreed on 11 and 21 -- always as
    variants ("master wocc" against "master wocc: contemporary challenges in the
    worlds of work"; one host differing only in a curly apostrophe) -- while
    country never disagreed and duration disagreed twice, meaningfully ([6, 36]
    on life.univ-cotedazur.eu, [24, 36] on ntnu.edu). So a name takes the front
    door's version, and a contradicted fact refuses the whole group: choosing
    between 6 and 36 months invents the fact this increment exists to stop.

    ``pages[0]`` is the front door. Returns None when a fact is contradicted.
    """
    if not pages:
        return None
    countries = {page.country_code.upper() for page in pages if page.country_code}
    durations = {page.duration_months for page in pages if page.duration_months is not None}
    if len(countries) > 1 or len(durations) > 1:
        return None
    return pages[0].model_copy(
        update={
            "institution_name": _front_door(page.institution_name for page in pages),
            "program_name": _front_door(page.program_name for page in pages),
            "country_code": next(iter(countries), None),
            "duration_months": next(iter(durations), None),
            # resolve_program dedupes by language name, so concatenation is enough.
            "teaching_languages": tuple(
                claim for page in pages for claim in page.teaching_languages
            ),
        }
    )
```

Add to the imports at the top of `catalog.py`:

```python
from collections.abc import Iterable, Sequence
```

- [ ] **Step 4: Let a caller supply already-resolved facts**

In `write_catalog_entry`, add the parameter and use it:

```python
    now: datetime | None = None,
    program_facts: ResolvedProgram | None = None,
) -> CatalogWriteResult | None:
```

and replace the resolution line:

```python
    # Supplied by the pooled path, which resolved the group once. `claims` is
    # still this page's own, so the rows it writes cite this page.
    program_facts = program_facts or resolve_program(lead, claims)
    if program_facts is None:
        return None
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/research/test_catalog_writer.py -q
```
Expected: PASS.

- [ ] **Step 6: Mutation-check the conflict rule**

Temporarily change `if len(countries) > 1 or len(durations) > 1:` to `if len(countries) > 1:` and re-run:

```bash
uv run pytest tests/research/test_catalog_writer.py -k contradicted_duration -v
```
Expected: FAIL. **Restore the line.** A guard no test can kill is not a guard.

- [ ] **Step 7: Run the full gate**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy apps config
```

- [ ] **Step 8: Commit**

```bash
git add apps/research/catalog.py tests/research/test_catalog_writer.py
git commit -m "feat(research): pool a group's gate facts, and let pooled facts drive a write"
```

---

### Task 3: The pipeline holds unresolved pages and resolves each group when the queue drains

**Files:**
- Modify: `apps/research/pipeline.py` (imports; `run_discovery` locals ~line 157; the write section ~line 326-335; a new block after the `while queue:` loop)
- Test: `tests/research/test_discovery_pipeline.py`

**Interfaces:**
- Consumes: `ResearchLead.one_programme_per_site` (Task 1); `pool_claims`, `write_catalog_entry(program_facts=...)` (Task 2).
- Produces: `DiscoveryReport.degraded` may now carry `"<n> programmes' pages disagreed on a gate fact"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/research/test_discovery_pipeline.py`, reusing the module's existing
`StaticSource` / `_pages` / `_paced` helpers. Two leads on one host rather than a hop, so the
test does not depend on `funding_links`' heuristics:

```python
FRONT_DOOR = b"<html><body><h1>Coastal Engineering</h1></body></html>"
ADMISSIONS = b"<html><body><p>Two years, taught in English.</p></body></html>"

# More specific prefix first: _pages matches with startswith.
CONSORTIUM = {
    "https://consortium.eu/admissions": ("https://consortium.eu/admissions", ADMISSIONS),
    "https://consortium.eu/": ("https://consortium.eu/", FRONT_DOOR),
}


class Consortium(StaticSource):
    name = "seed:eacea"
    one_programme_per_link = True


def _consortium_leads() -> Consortium:
    return Consortium(
        ResearchLead.from_url(
            "https://consortium.eu/", source_type="PROGRAM", funding_family="MULTILATERAL"
        ),
        ResearchLead.from_url(
            "https://consortium.eu/admissions",
            source_type="PROGRAM",
            funding_family="MULTILATERAL",
        ),
    )


def _split_extract(front: ExtractedClaims, rest: ExtractedClaims):
    """The front door states one thing; the other page states the others."""

    def extract(snapshot: object, _client: object = None) -> ExtractionResult:
        url = snapshot.evidence_metadata["source_url"]  # type: ignore[attr-defined]
        return ExtractionResult(
            claims=front if url.endswith("consortium.eu") else rest,
            metadata=ModelMetadata(
                model_id="test", schema_version=2, response_id=None, usage={}
            ),
        )

    return extract


def test_two_pages_of_one_programme_write_a_row_neither_could_write_alone(
    agency_a, fake_store
) -> None:
    cache.clear()
    front = ExtractedClaims(confidence=0.9, institution_name="Consortium University")
    rest = ExtractedClaims(
        confidence=0.9,
        program_name="Coastal Engineering",
        country_code="NO",
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
    )

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [_consortium_leads()],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(CONSORTIUM)),
            extract=_split_extract(front, rest),
        )

    # Neither page resolves alone; pooled they do, and both write against one row.
    assert report.written == 2
    assert Program.objects.count() == 1
    assert Program.objects.get().name == "Coastal Engineering"
    assert Institution.objects.get().name == "Consortium University"


def test_pages_that_contradict_a_duration_are_reported_not_guessed(
    agency_a, fake_store
) -> None:
    cache.clear()
    front = ExtractedClaims(
        confidence=0.9, institution_name="Consortium University", duration_months=6
    )
    rest = ExtractedClaims(
        confidence=0.9,
        program_name="Coastal Engineering",
        country_code="NO",
        duration_months=36,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
    )

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [_consortium_leads()],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(CONSORTIUM)),
            extract=_split_extract(front, rest),
        )

    assert Program.objects.count() == 0
    assert any("disagreed" in note for note in report.degraded)
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/research/test_discovery_pipeline.py -k "neither_could_write_alone or contradict_a_duration" -v
```
Expected: FAIL — `Program.objects.count() == 0`, because each page fails the gate alone today.

- [ ] **Step 3: Add the holding structures**

At the top of `apps/research/pipeline.py`:

```python
from collections import defaultdict, deque
from typing import NamedTuple

from apps.research.catalog import pool_claims, resolve_program, write_catalog_entry
```

(extend the existing `catalog` import rather than adding a second one), and above `run_discovery`:

```python
class _HeldPage(NamedTuple):
    """A page that failed the gate alone, kept until its group is resolved."""

    lead: ResearchLead
    claims: ExtractedClaims
    source: OfficialSource
    snapshot: OfficialSourceSnapshot
```

In `run_discovery`, beside the existing counters:

```python
    # Pages of one programme in queue order (front door first), and the ones
    # that could not resolve alone. Only sources that vouch populate these.
    pooled: dict[tuple[str, str], list[ExtractedClaims]] = defaultdict(list)
    held: dict[tuple[str, str], list[_HeldPage]] = defaultdict(list)
    conflicted = 0
```

- [ ] **Step 4: Hold instead of blocking**

Replace the write section (currently `result = write_catalog_entry(...)` through `unreadable_dates += result.unreadable_dates`):

```python
        group = (lead.discovered_by, urlsplit(source.canonical_url).hostname or "")
        if lead.one_programme_per_site:
            pooled[group].append(claims)
        result = write_catalog_entry(
            lead=lead, claims=claims, source=source, snapshot=snapshot, now=now
        )
        if result is None:
            if lead.one_programme_per_site:
                # Not blocked yet: another page of this same programme may state
                # the field this one lacks. Resolved once, after the queue drains.
                held[group].append(_HeldPage(lead, claims, source, snapshot))
                continue
            _open_task(tenant_id, source.canonical_url, "no evidence for a catalog row")
            blocked += 1
            continue
        written += 1
        unreadable_dates += result.unreadable_dates
```

- [ ] **Step 5: Resolve the groups after the queue drains**

Immediately after the `while queue:` loop ends, before the `if unreadable_dates:` block:

```python
    for group, pages in held.items():
        merged = pool_claims(tuple(pooled[group]))
        facts = resolve_program(pages[0].lead, merged) if merged is not None else None
        if facts is None:
            conflicted += 1
        for page in pages:
            result = (
                write_catalog_entry(
                    lead=page.lead,
                    claims=page.claims,
                    source=page.source,
                    snapshot=page.snapshot,
                    now=now,
                    program_facts=facts,
                )
                if facts is not None
                else None
            )
            if result is None:
                _open_task(tenant_id, page.source.canonical_url, "no evidence for a catalog row")
                blocked += 1
                continue
            written += 1
            unreadable_dates += result.unreadable_dates
    if conflicted:
        # A refusal is never a silence (§2.6): these are hosts whose own pages
        # state different facts, which is a page problem for a human to read.
        degraded.append(f"{conflicted} programmes' pages disagreed on a gate fact")
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/research/test_discovery_pipeline.py -q
```
Expected: PASS.

- [ ] **Step 7: Run the full gate**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy apps config
```

- [ ] **Step 8: Commit**

```bash
git add apps/research/pipeline.py tests/research/test_discovery_pipeline.py
git commit -m "feat(research): hold a page whose programme may be described by its neighbours"
```

- [ ] **Step 9: Verify against the real corpus — this is the acceptance criterion**

Clear the catalog and replay. **No network, no model calls, about five seconds.**

```bash
python - <<'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base"); django.setup()
from apps.funding.models import (
    FundingOpportunity, Institution, OfficialEvidenceClaim, Program,
)
# Join tables first: the FKs are PROTECT.
from django.apps import apps as A
for m in ("FundingOpportunityEvidenceClaim", "FundingOpportunityProgram",
          "ProgramEvidenceClaim", "InstitutionEvidenceClaim"):
    A.get_model("funding", m).objects.all().delete()
for M in (FundingOpportunity, Program, Institution, OfficialEvidenceClaim):
    M.objects.all().delete()
print("catalog cleared; sources and snapshots kept")
PY

cp ~/.local/share/tehsil_agent/eacea_run.py /tmp/eacea_run.py
# point BASE at the preserved cache, then:
uv run python /tmp/eacea_run.py pass2
```

Then count:

```bash
uv run python -c "
import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.base'); django.setup()
from apps.funding.models import Program, Institution
from urllib.parse import urlsplit
print('programs   :', Program.objects.count())
print('institutions:', Institution.objects.count())
"
```

**Expected: 24 distinct hosts represented, and `Program.objects.count()` of 25** — the 9 rows written today (8 hosts, one of which forks into two programmes on a name variant) plus 16 newly pooled hosts. The run must also report `1 programmes' pages disagreed on a gate fact` for `life.univ-cotedazur.eu`.

If the count is higher than 25, check whether the extra row is the name-variant fork the spec assigns to increment 4's ROR frame — that is expected and out of scope. **If any of the 9 existing rows is missing, stop: pooling has regressed a row that used to write.**

- [ ] **Step 10: Record the measured result**

Append the observed counts to `docs/superpowers/research/2026-08-30-eacea-full-catalogue-run.md` as a short `§5c`, then commit.

---

### Task 4: A currency must be a real currency

**Files:**
- Modify: `apps/research/catalog.py` (imports; `claim_rows` at the eligibility comparable ~line 164-167, commitment payment ~line 210, charges ~line 242-248, benefits ~line 249-255)
- Test: `tests/research/test_catalog_writer.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_money(label: str, amount: Decimal, currency: str, period: str) -> str | None` — private to `catalog.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_currency_that_is_not_a_currency_is_not_written(
    source: OfficialSource, snapshot: OfficialSourceSnapshot
) -> None:
    # ^[A-Z]{3}$ accepted PCT, NOM, VAR, DUR, SCH, UNP, INS, SEM and NOT from a
    # model with no currency to state -- 20 of 618 claims on the 2026-08-30 run.
    claims = ExtractedClaims(
        confidence=0.9,
        institution_name="Consortium University",
        program_name="Coastal Engineering",
        country_code="NO",
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
        benefits=(
            MoneyClaim(label="Scholarship duration", amount=Decimal("24"),
                       currency="DUR", period="months"),
            MoneyClaim(label="stipend", amount=Decimal("1400.00"),
                       currency="EUR", period="monthly"),
        ),
    )
    lead = ResearchLead.from_url(
        "https://consortium.eu/", source_type="PROGRAM", funding_family="MULTILATERAL"
    )

    result = write_catalog_entry(
        lead=lead, claims=claims, source=source, snapshot=snapshot
    )

    assert result is not None
    written = [claim.claim for claim in result.claims]
    assert any("stipend" in text for text in written)
    assert not any("DUR" in text for text in written)


def test_a_real_currency_still_writes() -> None:
    assert _money("stipend", Decimal("1400.00"), "EUR", "monthly") == (
        "stipend: 1400.00 EUR per monthly"
    )
    assert _money("Scholarship duration", Decimal("24"), "DUR", "months") is None
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/research/test_catalog_writer.py -k "not_a_currency or real_currency" -v
```
Expected: FAIL — `ImportError: cannot import name '_money'`, and the `DUR` row is present.

- [ ] **Step 3: Implement the check**

Add to `apps/research/catalog.py` imports. Line 40 already reads
`from apps.reference_data import ISO_3166_ALPHA2_CODES` — extend that line rather than adding a
second import, and add `Decimal`, which this module does not import at all today:

```python
from decimal import Decimal
...
from apps.reference_data import ISO_3166_ALPHA2_CODES, ISO_4217_CODES
```

and above `claim_rows`:

```python
def _money(label: str, amount: Decimal, currency: str, period: str) -> str | None:
    """A money row, or None when what it calls a currency is not one.

    ISO_4217_CODES is the same pinned set the database already enforces on
    FundingBenefit and CostComponent (funding_benefit_currency_iso4217). Only the
    extraction schema was looser: its ^[A-Z]{3}$ accepts any three capitals, so a
    model with nothing to say said PCT, NOM, VAR, DUR, SCH, UNP, INS, SEM and NOT
    -- 20 of 618 money claims on the 2026-08-30 run.

    The check is here and not in the schema on purpose: a validator rejects the
    whole response over one field, and the date defect discarded 13 pages' worth
    of institutions and funding claims that way. Do not move it.
    """
    if currency not in ISO_4217_CODES:
        return None
    return f"{label}: {amount} {currency} per {period}"
```

- [ ] **Step 4: Use it at all four emission sites in `claim_rows`**

Charges:

```python
    for charge in charges:
        text = _money(charge.label, charge.amount, charge.currency, charge.period)
        if text is not None:
            rows.append((classes.TUITION, text))
```

Benefits:

```python
    for benefit in claims.benefits:
        text = _money(benefit.label, benefit.amount, benefit.currency, benefit.period)
        if text is not None:
            rows.append((classes.FUNDING, text))
```

Commitment payment — guard the currency, keeping the row's kind when the currency is unreadable:

```python
        if payment.currency in ISO_4217_CODES:
            rows.append((classes.FUNDING, f"{payment.kind}: {payment.amount} {payment.currency}"))
```

Eligibility comparable — drop only the bracket, never the cited criterion:

```python
        elif criterion.comparable_currency not in ISO_4217_CODES:
            comparable = ""
        else:
            comparable = f" [{criterion.comparable_value} {criterion.comparable_currency}]"
```

Read the surrounding lines before editing; keep the existing `comparable_currency is None` branch ahead of the new one.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/research/test_catalog_writer.py -q
```

- [ ] **Step 6: Run the full gate**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy apps config
```

- [ ] **Step 7: Commit**

```bash
git add apps/research/catalog.py tests/research/test_catalog_writer.py
git commit -m "fix(research): a currency the model invented is not written as money"
```

- [ ] **Step 8: Verify against the corpus**

Clear and replay exactly as in Task 3 Step 9, then:

```bash
uv run python -c "
import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.base'); django.setup()
from apps.funding.models import OfficialEvidenceClaim
bad = ('PCT','NOM','VAR','DUR','SCH','UNP','INS','SEM','NOT')
hits = [c.claim for c in OfficialEvidenceClaim.objects.all() if any(f' {b} ' in c.claim for b in bad)]
print('non-currency money rows still written:', len(hits)); [print(' ', h) for h in hits[:5]]
"
```

**Expected: 0.** The host and row counts from Task 3 must be unchanged — this task drops claim rows, never catalog rows.

---

### Task 5: A money claim must quote itself

**Files:**
- Modify: `apps/research/extraction.py:36-42` (`MoneyClaim`)
- Modify: `apps/research/catalog.py` (`_money` gains the evidence rule)
- Test: `tests/research/test_catalog_writer.py`, `tests/research/test_extraction.py`

**Interfaces:**
- Consumes: `_money` (Task 4).
- Produces: `MoneyClaim.evidence: str` (default `""`).

**Read before starting:** after this task, replaying the cached corpus writes **no money rows at all** — those 618 claims predate the field and carry no quotation. That is the intended behaviour (an uncited money figure is exactly what we decided not to publish), not a regression. Money rows return when pages are extracted afresh, which Task 6 demonstrates on a sample. **Do not verify this task by replay.**

- [ ] **Step 1: Write the failing tests**

```python
def test_a_money_claim_without_a_quotation_is_not_written() -> None:
    assert _money("stipend", Decimal("1400.00"), "EUR", "monthly", "") is None


def test_a_quotation_that_does_not_carry_the_currency_is_not_written() -> None:
    # ccd-stede's page contains "SEK" zero times. SEK is a real ISO code, so the
    # list check passes it -- this is the only check that catches it.
    assert _money(
        "Mobility subsistence allowance maximum duration",
        Decimal("6"), "SEK", "MONTHS",
        "The mobility period lasts a maximum of 6 months.",
    ) is None


def test_a_quoted_currency_is_written_by_code_or_by_symbol() -> None:
    assert _money("stipend", Decimal("1400.00"), "EUR", "monthly",
                  "A monthly allowance of 1,400 EUR is paid.") is not None
    assert _money("stipend", Decimal("1400.00"), "EUR", "monthly",
                  "A monthly allowance of €1,400 is paid.") is not None


def test_money_claims_keep_parsing_without_a_quotation() -> None:
    # The field defaults so the 138 cached pages carrying money still parse and
    # Tasks 1-4 keep their five-second replay.
    assert MoneyClaim(
        label="stipend", amount=Decimal("1400.00"), currency="EUR", period="monthly"
    ).evidence == ""
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/research/test_catalog_writer.py -k "quotation or quoted_currency" -v
```
Expected: FAIL — `_money() takes 4 positional arguments but 5 were given`.

- [ ] **Step 3: Add the field**

In `apps/research/extraction.py`, in `MoneyClaim`, after `period`:

```python
    #: The sentence the figure came from. Defaulted, not required: a validator
    #: rejects the whole response over one field, and the date defect discarded
    #: 13 pages' worth of institutions that way. The catalog writer requires it.
    #: Money was the only claim type here with no quotation, which is exactly why
    #: a fabricated SEK was invisible to every automated check.
    evidence: str = Field(default="", max_length=1_000)
```

- [ ] **Step 4: Extend `_money`**

```python
#: Symbols for the currencies that carry one in the corpus -- 595 of 618 claims
#: are EUR, GBP or USD. Anything else must state its code.
_CURRENCY_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$"}


def _money(
    label: str, amount: Decimal, currency: str, period: str, evidence: str
) -> str | None:
    if currency not in ISO_4217_CODES:
        return None
    # ponytail: a page writing "1 400 kr" for SEK is dropped rather than
    # published uncited. Add the symbol when a real source is measured losing a
    # claim to this, not before.
    symbol = _CURRENCY_SYMBOLS.get(currency)
    quoted = currency.casefold() in evidence.casefold() or (
        symbol is not None and symbol in evidence
    )
    if not evidence or not quoted:
        return None
    return f"{label}: {amount} {currency} per {period}"
```

Update the two `claim_rows` call sites to pass `charge.evidence` / `benefit.evidence`.

- [ ] **Step 5: Update Task 4's direct `_money` test for the new signature**

`test_a_real_currency_still_writes` from Task 4 calls `_money` with four arguments and now
raises `TypeError`. Give both calls an evidence string that carries the currency:

```python
def test_a_real_currency_still_writes() -> None:
    assert _money(
        "stipend", Decimal("1400.00"), "EUR", "monthly", "A monthly allowance of 1,400 EUR."
    ) == "stipend: 1400.00 EUR per monthly"
    assert _money(
        "Scholarship duration", Decimal("24"), "DUR", "months",
        "The scholarship lasts 24 months.",
    ) is None
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/research/test_catalog_writer.py tests/research/test_extraction.py -q
```

- [ ] **Step 7: Run the full gate**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy apps config
```

Existing tests asserting a money row is written now fail unless their fixtures gain an `evidence`
carrying the currency. Two are known:

- `CLAIMS` at `tests/research/test_catalog_writer.py:37`.
- **`test_pooled_facts_drive_the_row_while_the_page_still_supplies_its_own_claims`, added in Task 2.**
  It asserts `any("stipend" in claim.claim ...)` on a `MoneyClaim` with no evidence, which this task
  stops writing. Give that claim an evidence string carrying `EUR` — do not change what the test is
  about, which is that a held page's claims cite the held page.

Fix the fixtures; do not weaken the rule.

- [ ] **Step 8: Commit**

```bash
git add apps/research/extraction.py apps/research/catalog.py tests/research/
git commit -m "fix(research): money quotes the sentence it came from, or it is not money"
```

---

### Task 6: Verify the quotation rule on a real sample, and record it

**Files:**
- Modify: `docs/superpowers/research/2026-08-30-eacea-full-catalogue-run.md` (append §5d)

**Interfaces:**
- Consumes: everything above.

**This is the only task that spends model calls: about 50, not another 595.**

- [ ] **Step 1: Build the sample**

From `~/.local/share/tehsil_agent/2026-08-30-eacea-claims.jsonl`, take every URL whose extraction carried a money claim with a non-ISO currency (about 20 pages), the 6 whose label names a duration — including `ccd-stede.eu/fees-and-fundings/erasmus-mundus-scholarship` and `floodriskmaster.org/scholarships`, the two named in §5b — and about 25 pages carrying ordinary EUR claims as a control.

- [ ] **Step 2: Re-extract just those pages**

Use `~/.local/share/tehsil_agent/eacea_extract.py` against the preserved bodies in `~/.local/share/tehsil_agent/eacea-cache/`, restricted to the sample URLs. **No re-fetching: the bodies are already on disk.**

- [ ] **Step 3: Measure three things**

1. How many sampled money claims now carry an `evidence` string.
2. Whether `6 SEK per MONTHS` and `24 EUR per months` are gone.
3. **How many control claims the rule drops.** This is the number that matters — a rule that also silences legitimate EUR claims is too strict, and the symbol map is where to loosen it.

- [ ] **Step 4: Write it up and commit**

Append §5d with the three numbers, the sample definition, and the date. If the control loss is material, say so plainly and open the question rather than tuning the map to make the number look good.

```bash
git add docs/superpowers/research/2026-08-30-eacea-full-catalogue-run.md
git commit -m "docs(research): the quotation rule, measured on a fifty-page sample"
```

---

## Verification summary

| task | how it is verified | cost |
|---|---|---|
| 1, 2 | unit tests + full gate | free |
| 3 | replay: **24 hosts, 25 Program rows**, 1 conflict reported | ~5 s, no model calls |
| 4 | replay: **0** non-currency money rows, host count unchanged | ~5 s, no model calls |
| 5 | unit tests only — replay writes no money rows by design | free |
| 6 | ~50-page re-extraction over cached bodies | ~50 model calls |

## Rollback

Every task is one commit. Tasks 4 and 5 drop claim rows but write no schema migration, so reverting either restores the previous rows on the next discovery run. Tasks 1-3 add one field to `ResearchLead`, one to three source classes and one optional parameter to `write_catalog_entry`; none is persisted, so there is no migration to unwind.
