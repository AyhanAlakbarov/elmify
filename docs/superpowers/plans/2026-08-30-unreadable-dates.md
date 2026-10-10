# Unreadable Dates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the catalog storing dates whose year the model fabricated, without losing the rest of the page.

**Architecture:** The check is deterministic and lives in the catalog writer, *not* in the extraction schema. A Pydantic validator would reject the whole response over one bad field — which is already costing whole pages (13 of the 20 hard extraction failures on the 2026-08-30 run were `key_dates` validators). Putting the check downstream of parsing means a bad date drops out while the institution, programme, teaching languages and funding claims on that page still become a row, and extraction's all-or-nothing contract is untouched.

Two changes carry it: a year window around the run date, and the removal of the one date path that carries no citation.

**Tech Stack:** Python 3.12, Django 5.2, Pydantic 2.11, pytest. **No new dependency** — the fix is integer year comparison. `python-dateutil` was considered for re-parsing dates out of the evidence text and rejected: it fails on real strings from this corpus (`"5 January 2026, 23.59 hrs Dutch time"`), so it would lose currently-correct dates to buy nothing the window does not already give.

**Spec:** `docs/superpowers/research/2026-08-30-eacea-full-catalogue-run.md` §5 — the measurement this plan argues from. There is no separate design doc; brainstorming classified this bounded.

## Global Constraints

- Python `>=3.12,<3.13`; all commands run under `uv run`.
- **No new dependencies.** `pyproject.toml` is not modified by this plan.
- `uv run ruff check apps config tests` must pass. **Never run `ruff format`** — it rewrites 26 unrelated files (project convention: lint-only).
- `uv run mypy apps config` must pass with no issues.
- Bandit runs on every commit and pip-audit on every push via pre-commit; both must pass.
- Commit with `uv run git commit` (the repo's hooks require the project environment).
- Every commit message ends with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- Conventional commit prefixes: `fix:`, `feat:`, `docs:`, `chore:`.
- `apps/research/catalog.py` currently imports `from datetime import datetime`. Tasks below need `date` as well.

## The measurement this plan exists for

From one run over all 169 EACEA consortium sites, 429 pages extracted:

| date path | dates produced | impossible year | share |
|---|---|---|---|
| `ExtractedClaims.key_dates[].on` (cited) | 407 | 132 | **32%** |
| `ExtractedClaims.deadline` (uncited, schema v1) | 100 | 52 | **52%** |

Observed years include 101, 301, 1155, 1515, 1558, 3131, 4444, 8188. Every plausible value fell in 2025–2027 against a 2027 admissions cycle (`{2025: 49, 2026: 182, 2027: 44}`).

**The day and month were correct in every corrupted sample inspected; only the year was fabricated**, assembled from the day and month digits when the quoted sentence did not bind a year:

| quoted evidence | stored |
|---|---|
| `"31st of March"` | `3131-03-31` |
| `"15th Feb 2026"` | `1515-02-15` |
| `"September 25"` | `2509-01-01` |
| `"the deadline set for 1 December 2026 at 23:59 CET"` | `1558-12-01` |

That is why the check compares **years only**. A day-level window would turn a legitimate "1 December" that has just passed into a rejection.

Dropping the uncited `deadline` field costs at most **4 plausible dates across 429 pages** (7 pages had an uncited date and no cited one; 3 of those 7 were impossible anyway). Those 4 cite nothing, so under this module's own first rule — *no evidence, no row* — they should not be claims.

---

### Task 1: The readability window

A pure function, no I/O, no Django ORM. Its own test file section so it can be rejected on its own.

**Files:**
- Modify: `apps/research/catalog.py` (the `datetime` import at line 21; new constants and function above `claim_rows`, which starts at line 97)
- Test: `tests/research/test_catalog_writer.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `date_is_readable(value: date, now: datetime) -> bool`. Task 2 imports it from the same module.

- [ ] **Step 1: Write the failing tests**

Append to `tests/research/test_catalog_writer.py`:

```python
def test_a_year_assembled_from_the_day_and_month_is_not_readable() -> None:
    """Real values from the 2026-08-30 full-catalogue run.

    The model fabricates a year out of the day and month digits when the
    sentence it quotes does not bind one: "31st of March" became 3131-03-31 and
    "15th Feb 2026" became 1515-02-15. The day and month are right in each; only
    the year is invented.
    """
    run_date = datetime(2026, 8, 30)

    for corrupt in (
        date(1515, 2, 15),
        date(1558, 12, 1),
        date(3131, 3, 31),
        date(2509, 1, 1),
        date(101, 1, 1),
        date(8188, 6, 1),
    ):
        assert date_is_readable(corrupt, run_date) is False, corrupt


def test_dates_from_the_admissions_cycle_are_readable() -> None:
    """Every plausible value in the run fell in 2025-2027 for a 2027 cycle."""
    run_date = datetime(2026, 8, 30)

    for good in (date(2025, 11, 15), date(2026, 2, 15), date(2027, 9, 1)):
        assert date_is_readable(good, run_date) is True, good


def test_a_deadline_that_has_just_passed_is_still_readable() -> None:
    """The window compares years, never days.

    A day-level window would reject a legitimate "1 December" the moment it
    passed, which is a different question from whether the date was read
    correctly.
    """
    assert date_is_readable(date(2026, 1, 5), datetime(2026, 8, 30)) is True
```

Two import lines in that file need editing. It currently has, at lines 1 and 15:

```python
from datetime import date
...
from apps.research.catalog import write_catalog_entry
```

Change them to:

```python
from datetime import date, datetime
...
from apps.research.catalog import (
    ResolvedProgram,
    claim_rows,
    date_is_readable,
    write_catalog_entry,
)
```

`ResolvedProgram` and `claim_rows` are unused until Task 2; import them now so Task 2 touches no imports. Ruff will flag them as unused in the meantime — add them in Task 2 instead if you are running the linter between tasks.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/research/test_catalog_writer.py -k readable -v
```

Expected: `ImportError` / `cannot import name 'date_is_readable'`.

- [ ] **Step 3: Write the implementation**

In `apps/research/catalog.py`, change the datetime import:

```python
from datetime import date, datetime
```

and add above `def claim_rows(` (line 97):

```python
#: How far from the run date a stated date may fall and still be readable.
#:
#: What this bounds is not a *wrong* deadline but an *unreadable* one. On the
#: 2026-08-30 run over all 169 EACEA consortium sites, 132 of 407 cited dates
#: (32%) and 52 of 100 uncited ones (52%) carried an impossible year -- 101,
#: 1515, 4444, 8188. The day and month were correct in every sample inspected;
#: only the year was fabricated, assembled from the day and month digits when
#: the quoted sentence did not bind a year ("31st of March" -> 3131-03-31,
#: "15th Feb 2026" -> 1515-02-15, "September 25" -> 2509-01-01). Every
#: plausible value observed fell in 2025-2027 against a 2027 cycle.
#:
#: Years, never days: a day-level window would reject a legitimate "1 December"
#: the moment it passed, which is a different question from whether it was read
#: correctly. Evidence:
#: docs/superpowers/research/2026-08-30-eacea-full-catalogue-run.md §5.
_YEARS_BEHIND = 2
_YEARS_AHEAD = 4


def date_is_readable(value: date, now: datetime) -> bool:
    """Whether a stated date could belong to an admissions cycle near ``now``."""
    return now.year - _YEARS_BEHIND <= value.year <= now.year + _YEARS_AHEAD
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/research/test_catalog_writer.py -k readable -v
```

Expected: 3 passed.

- [ ] **Step 5: Prove the tests are load-bearing**

Temporarily change `_YEARS_AHEAD = 4` to `_YEARS_AHEAD = 10_000`, re-run the command from Step 4, and confirm `test_a_year_assembled_from_the_day_and_month_is_not_readable` FAILS. Restore `4` and confirm it passes again. A guard whose test passes either way is not a guard.

- [ ] **Step 6: Commit**

```bash
uv run git add apps/research/catalog.py tests/research/test_catalog_writer.py
uv run git commit -m "feat(catalog): a year outside the admissions cycle is not a date

Measured over all 169 EACEA sites: 32% of cited dates and 52% of uncited
ones carried an impossible year. The day and month were right in every
corrupted sample; the year was assembled from the day and month digits
when the quoted sentence bound no year -- \"31st of March\" became
3131-03-31. The window compares years only, so a deadline that has just
passed stays readable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Drop the unreadable date, keep the page

**Files:**
- Modify: `apps/research/catalog.py` — `claim_rows` signature (line 97), the `claims.deadline` block (lines 139-142), the `key_dates` loop (lines 143-152), and the `claim_rows` call site in `write_catalog_entry` (line 235)
- Test: `tests/research/test_catalog_writer.py` (append)

**Interfaces:**
- Consumes: `date_is_readable(value, now)` from Task 1.
- Produces: `claim_rows(program, claims, *, now: datetime | None = None)` — the `now` parameter is new and keyword-only with a `None` default, so no existing caller breaks. Task 3 relies on `write_catalog_entry` having computed `checked_at` before calling it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/research/test_catalog_writer.py`. Follow the existing fixtures in that file for building a `ResolvedProgram` and `ExtractedClaims`; the shape below names the fields explicitly so it does not depend on a helper you may not have read.

```python
def test_an_unreadable_date_is_dropped_and_the_rest_of_the_page_survives() -> None:
    """The whole point of checking here rather than in the schema.

    A Pydantic validator rejects the entire response over one bad field. This
    page states a real English teaching language and a real ECTS bar alongside
    a date whose year the model invented; all of it but the date is worth
    keeping.
    """
    program = ResolvedProgram(
        institution_name="Western Norway University of Applied Sciences",
        country_code="NO",
        city="Bergen",
        program_name="Theatre SPACEs",
        degree_level="MASTER",
        teaching_languages=("English",),
        duration_months=24,
    )
    claims = ExtractedClaims(
        confidence=0.9,  # required field, no default
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
        key_dates=(
            KeyDateClaim(
                kind="APPLICATION_DEADLINE",
                on=date(1558, 12, 1),
                evidence="the deadline set for 1 December 2026 at 23:59 CET",
            ),
            KeyDateClaim(
                kind="INTAKE_START",
                on=date(2026, 9, 1),
                evidence="The programme starts 1 September 2026.",
            ),
        ),
    )

    rows = claim_rows(program, claims, now=datetime(2026, 8, 30))
    text = [row[1] for row in rows]

    assert not any("1558" in row for row in text)
    assert any("2026-09-01" in row for row in text)
    assert any("Teaching language: English" in row for row in text)
    assert any("Theatre SPACEs" in row for row in text)


def test_the_uncited_deadline_field_never_becomes_a_claim() -> None:
    """It cites nothing, and this module's first rule is no evidence, no row.

    It is also the worse of the two date paths -- 52% of its values had an
    impossible year against 32% for the cited key_dates -- and key_dates covers
    the same ground with a quotation attached.
    """
    program = ResolvedProgram(
        institution_name="NTNU",
        country_code="NO",
        city="Trondheim",
        program_name="Coastal and Marine Engineering and Management",
        degree_level="MASTER",
        teaching_languages=("English",),
        duration_months=24,
    )
    claims = ExtractedClaims(
        confidence=0.9,  # required field, no default
        deadline=date(2026, 1, 5),
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Language / English"),
        ),
    )

    text = [row[1] for row in claim_rows(program, claims, now=datetime(2026, 8, 30))]

    assert not any(row.startswith("Application deadline:") for row in text)
```

`KeyDateClaim` is not yet imported in this file. Add it to the existing block:

```python
from apps.research.extraction import (
    ExtractedClaims,
    FundingFamilyClaim,
    KeyDateClaim,
    MoneyClaim,
    TeachingLanguageClaim,
)
```

`datetime` and `ResolvedProgram`/`claim_rows` were added in Task 1.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/research/test_catalog_writer.py -k "unreadable_date or uncited_deadline" -v
```

Expected: both FAIL — the first because the 1558 row is still emitted, the second because `Application deadline: 2026-01-05` is still emitted. (If the first errors on an unexpected `now` keyword instead, that is also a failure; proceed.)

- [ ] **Step 3: Write the implementation**

Change the signature at line 97:

```python
def claim_rows(
    program: ResolvedProgram, claims: ExtractedClaims, *, now: datetime | None = None
) -> tuple[tuple[str, str], ...]:
    """(claim_class, claim text) per extracted fact, for Task 10's windows."""
    classes = OfficialEvidenceClaim.ClaimClass
    checked_at = now or timezone.now()
```

Delete the `claims.deadline` block (lines 139-142) and put this in its place:

```python
    # claims.deadline is deliberately not emitted. It is the schema-v1 field and
    # carries no evidence, so a claim built from it cites nothing -- against this
    # module's first rule. It is also the worse of the two date paths: on the
    # 2026-08-30 run 52% of its values had an impossible year against 32% for
    # the cited key_dates, NTNU's was the page's own render timestamp read as a
    # deadline, and only 4 pages of 429 had a plausible uncited date and no
    # cited one. key_dates covers the same ground with a quotation attached.
```

Guard the `key_dates` loop:

```python
    for key_date in claims.key_dates:
        if key_date.on is not None and not date_is_readable(key_date.on, checked_at):
            # The year is a transcription artifact, so the claim would misstate
            # the date while citing a sentence that gives it correctly. Drop the
            # date; every other claim on this page still stands.
            continue
        rows.append(
```

Move `checked_at` above the `claim_rows` call in `write_catalog_entry` and pass it. Replace lines 235 and 238 so the order reads:

```python
    checked_at = now or timezone.now()
    rows = claim_rows(program_facts, claims, now=checked_at)
    if not rows:
        return None  # no evidence, no student-facing row
```

and delete the later `checked_at = now or timezone.now()` line so it is assigned exactly once.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/research/test_catalog_writer.py -v
```

Expected: all pass, including the two new ones. Existing tests in this file assert on emitted rows — if one asserted on an `Application deadline:` row, update that assertion to read the corresponding `APPLICATION_DEADLINE:` `key_dates` row instead, and say so in the commit message.

- [ ] **Step 5: Run the full suite**

```bash
uv run pytest -q
uv run ruff check apps config tests
uv run mypy apps config
```

Expected: 1367+ passed, ruff clean, mypy clean on 203 files.

- [ ] **Step 6: Commit**

```bash
uv run git add apps/research/catalog.py tests/research/test_catalog_writer.py
uv run git commit -m "fix(catalog): a fabricated year drops the date, not the page

The check runs in the writer rather than as a schema validator on purpose.
A validator rejects the whole response over one bad field, which is already
costing whole pages -- 13 of the 20 hard extraction failures on the
2026-08-30 run were key_dates validators throwing away an institution, a
programme name and every funding claim to punish one date.

The uncited schema-v1 deadline field stops becoming a claim entirely. It
cites nothing, against this module's first rule; 52% of its values carried
an impossible year; NTNU's was the page's own render timestamp; and only
4 pages of 429 had a plausible uncited date and no cited one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Report the drops instead of swallowing them

A third of dates disappearing silently is a worse bug than the one being fixed. `DiscoveryReport.degraded` already exists to carry exactly this kind of notice.

**Files:**
- Modify: `apps/research/catalog.py` — `CatalogWriteResult` (line 62), and the `return CatalogWriteResult(...)` at the end of `write_catalog_entry`
- Modify: `apps/research/pipeline.py` — `run_discovery`'s counters and its `degraded` list
- Test: `tests/research/test_discovery_pipeline.py` (append)

**Interfaces:**
- Consumes: `date_is_readable` (Task 1) and the `checked_at` computed before `claim_rows` (Task 2).
- Produces: `CatalogWriteResult.unreadable_dates: int`, defaulting to `0`.

- [ ] **Step 1: Write the failing test**

Append to `tests/research/test_discovery_pipeline.py`:

```python
def test_dropped_dates_are_reported_not_swallowed(agency_a, fake_store) -> None:
    """A third of dates vanishing quietly is worse than the bug being fixed."""
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught entirely in English."),
        ),
        key_dates=(
            KeyDateClaim(
                kind="APPLICATION_DEADLINE",
                on=date(1515, 2, 15),
                evidence="Deadline for Application with Scholarship 15th Feb 2026",
            ),
        ),
        confidence=0.9,
    )

    def extract(_snapshot, _client=None):
        return ExtractionResult(
            claims=claims,
            metadata=ModelMetadata(
                model_id="test", schema_version=2, response_id=None, usage={}
            ),
        )

    pages = {"https://www.utn.de/": ("https://www.utn.de/en/study/ai-robotics-en", OFFICIAL_PAGE)}
    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(lead)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(pages)),
            extract=extract,
        )

    assert report.written == 1  # the row still lands
    assert any("unreadable" in note for note in report.degraded)
```

`date` is already imported in this file (`from datetime import date, timedelta`). `KeyDateClaim` is not — add it to the existing block:

```python
from apps.research.extraction import (
    ExtractedClaims,
    ExtractionError,
    ExtractionResult,
    KeyDateClaim,
    ModelMetadata,
    TeachingLanguageClaim,
)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/research/test_discovery_pipeline.py -k dropped_dates -v
```

Expected: FAIL on the `report.degraded` assertion — the row is written and nothing mentions the dropped date.

- [ ] **Step 3: Write the implementation**

In `apps/research/catalog.py`, add the field to `CatalogWriteResult`:

```python
@dataclass(frozen=True)
class CatalogWriteResult:
    institution: Institution
    program: Program
    claims: tuple[OfficialEvidenceClaim, ...]
    opportunity: FundingOpportunity | None
    #: Dates whose year the model fabricated, dropped rather than stored. Not a
    #: silence: run_discovery reports the run's total in DiscoveryReport.degraded.
    unreadable_dates: int = 0
```

In `write_catalog_entry`, just after `checked_at` is assigned:

```python
    unreadable_dates = sum(
        1
        for key_date in claims.key_dates
        if key_date.on is not None and not date_is_readable(key_date.on, checked_at)
    )
```

and pass it on the return:

```python
    return CatalogWriteResult(
        institution, program, tuple(written), opportunity, unreadable_dates
    )
```

In `apps/research/pipeline.py`'s `run_discovery`, add a counter beside the existing ones:

```python
    leads = written = unchanged = blocked = unreadable_dates = 0
```

after the `result is None` check, replace `written += 1` with:

```python
        written += 1
        unreadable_dates += result.unreadable_dates
```

and before the `return DiscoveryReport(...)`:

```python
    if unreadable_dates:
        # A third of extracted dates carried a fabricated year on the
        # 2026-08-30 run. Dropping them quietly would hide that.
        degraded.append(f"{unreadable_dates} dates dropped as unreadable")
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/research/test_discovery_pipeline.py -k dropped_dates -v
```

Expected: PASS.

- [ ] **Step 5: Full verification**

```bash
uv run pytest -q
uv run ruff check apps config tests
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config -q
```

Expected: all green, bandit exit 0 with no findings.

- [ ] **Step 6: Commit**

```bash
uv run git add apps/research/catalog.py apps/research/pipeline.py tests/research/test_discovery_pipeline.py
uv run git commit -m "fix(research): a dropped date is reported, never swallowed

A third of extracted dates carry a fabricated year, so silently discarding
them would hide the extraction problem behind a clean-looking catalog.
DiscoveryReport.degraded already exists for exactly this notice.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verification against the real corpus

Not a task — evidence to gather once the three tasks are done, using the cached responses from the 2026-08-30 run if they still exist in the job scratch directory.

Re-run the write pass and confirm:

1. No stored `DEADLINE` claim contains a year outside the run's window.
2. The three known-bad rows lose their dates and **keep their other claims**: `theatre-spaces.eu` (1558), `ccd-stede.eu/fees-and-fundings` (1515), `ntnu.edu` (the uncited render timestamp).
3. Row count does not fall. All nine rows should survive; the count may rise, since dropping a bad date never removes a row.

If the cache is gone, the three unit tests above already pin each of those cases with the real strings, and that is the durable check.

## What `claim_rows` emits today

Verified by running it on the Task 2 fixture before any change, so the assertions above match real
strings rather than remembered ones:

```
IDENTITY     | WNUAS offers Theatre SPACEs (MASTER)
STRUCTURE    | Teaching language: English — Taught in English.
STRUCTURE    | Programme duration: 24 months
DEADLINE     | Application deadline: 2026-01-05                  <- Task 2 removes this row
DEADLINE     | APPLICATION_DEADLINE: 1558-12-01 — the deadline set for 1 December 2026 at 23:59 CET
DEADLINE     | INTAKE_START: 2026-09-01 — The programme starts 1 September 2026.
```

Note the separator before the evidence is an em dash (`—`), not a hyphen.

## Known and deliberately out of scope

- **The 13 whole-page rejections from `KeyDateClaim.dated_or_decentralised`.** Same underlying complaint — one bad field costs a whole page — but fixing it means partial acceptance of a model response, which changes extraction's contract and is architectural, not bounded. Raise it separately.
- **Selection errors.** No window catches the model quoting the wrong sentence — NTNU's render timestamp was a *plausible* 2025 date. Dropping the uncited field removes that specific instance; the general case needs a human reading the citation.
- **Re-parsing dates from the evidence text.** Rejected above under Tech Stack; revisit only with a measurement showing the window lets real errors through.
