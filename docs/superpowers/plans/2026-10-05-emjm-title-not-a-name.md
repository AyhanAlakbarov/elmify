# EMJM Title Is Not a University Name — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An EACEA project title ("EMJM Smart Cities") stops counting as a name of the coordinating university, so a consortium site titled with the project can no longer verify as that university's own site.

**Architecture:** `recognition.body_names` keeps the organisation's own name and adds only names from `RegisterEntry` rows whose list is a REGISTER or CURATED_LIST source in `docs/research/provenance-sources.csv`. One function, one test, no migration.

**Tech Stack:** Django 5, Postgres, pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-verified-catalog-one-reader-design.md` §3.2 (the `body_names` defect paragraph), §11 item 9. The typed-programme flow (§3.3) is built after the card reader (plan 3), per the owner's 2026-10-05 decisions, and is not in this plan.

## Global Constraints

- Branch `claude/emjm-title-not-a-name` from `origin/master` (`2042618c` or later), in worktree `/home/orkhan/Desktop/elmify/.worktrees/emjm-title`. Never push to `master`.
- Tests: `POSTGRES_DB=elmify_emjm_title uv run pytest -q <paths>`. Lint: `uv run ruff check .` only, never `ruff format`. Types: `uv run mypy apps config`.
- No network in tests. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A body whose only extra name comes from a list missing from `provenance-sources.csv` (for example a slug from `closed-lists.csv` alone). Its name no longer counts. Expected, and pinned by the test's `az_heis` versus `eacea_emjm` pair.
2. A funder-list partner whose homepage names it still passes. `identity_ok` takes `RegisterEntryPartner.listed_name`, not `body_names`; the existing `test_a_funder_list_partner_whose_homepage_names_it_is_recognised` pins it.

---

### Task 1: `body_names` reads only REGISTER and CURATED_LIST rows

**Files:**
- Modify: `apps/research/recognition.py:507-511` (`body_names`)
- Test: `tests/research/test_provenance_identity.py`

**Interfaces:**
- Consumes: `read_sources() -> tuple[ProvenanceSource, ...]` (same module, line ~102). Each `ProvenanceSource` has `.slug` and `.role`. `Reason.REGISTER` and `Reason.CURATED_LIST` are already imported there.
- Produces: `body_names(organisation: Organisation) -> tuple[str, ...]`. Same signature; it now ignores rows whose `RegisterEntry.register` is not a REGISTER or CURATED_LIST source in `docs/research/provenance-sources.csv`.

- [ ] **Step 1: Write the failing test.** Append to `tests/research/test_provenance_identity.py`:

```python
def test_a_project_title_on_a_funder_list_is_never_the_coordinators_name() -> None:
    """EACEA writes each EMJM as a RegisterEntry named after the project and
    bound to its coordinator; a consortium site titled with that project must
    not verify as the coordinator's own site (verified-catalog §3.2)."""
    uni = _body("uni-x.example.edu", "Universidade X", kind="INSTITUTION")
    RegisterEntry.objects.create(
        register="eacea_emjm", external_key="101234", name="EMJM Smart Cities",
        organisation=uni, resolution="RESOLVED", resolved_via="LISTED", last_seen=NOW,
    )
    RegisterEntry.objects.create(
        register="az_heis", external_key="x1", name="X Universiteti",
        organisation=uni, resolution="RESOLVED", resolved_via="LISTED", last_seen=NOW,
    )
    assert body_names(uni) == ("Universidade X", "X Universiteti")
    home = "<html><head><title>EMJM Smart Cities</title></head></html>"
    assert site_identity(uni, "uni-x.example.edu", fetch=_home("uni-x.example.edu", home)) == (
        "the homepage does not name the body"
    )
```

Add `body_names` to the `from apps.research.recognition import (...)` block at the top of the file.

- [ ] **Step 2: Run it and see it fail.**

Run: `POSTGRES_DB=elmify_emjm_title uv run pytest -q tests/research/test_provenance_identity.py::test_a_project_title_on_a_funder_list_is_never_the_coordinators_name`
Expected: FAIL. `body_names(uni)` still includes `"EMJM Smart Cities"`.

- [ ] **Step 3: Implement.** Replace `body_names` in `apps/research/recognition.py`:

```python
def body_names(organisation: Organisation) -> tuple[str, ...]:
    """Every name the platform holds for a body: its own label and the name on
    each register or curated-list row bound to it (local-language names arrive
    this way). A funder list's row names a project, not its coordinator, so it
    never counts (verified-catalog §3.2)."""
    naming = [s.slug for s in read_sources() if s.role in (Reason.REGISTER, Reason.CURATED_LIST)]
    listed = RegisterEntry.objects.filter(
        organisation=organisation, register__in=naming
    ).values_list("name", flat=True)
    return tuple(dict.fromkeys((organisation.name, *listed)))
```

- [ ] **Step 4: Fix the one existing test whose register is not a provenance source.** In `test_a_local_language_register_name_counts_as_the_bodys_name` (same file, line ~96), change `register="az_gov"` to `register="az_outbound_gov"`. That slug is a `curated_list` row in `provenance-sources.csv`; `az_gov` is in neither CSV.

- [ ] **Step 5: Run the identity and check suites.**

Run: `POSTGRES_DB=elmify_emjm_title uv run pytest -q tests/research/test_provenance_identity.py tests/research/test_provenance_check.py tests/research/test_recognition_lists.py tests/research/test_vouch.py`
Expected: all pass. A failure here means an existing test names a body through a row of another role. Point it at a REGISTER or CURATED_LIST slug from `provenance-sources.csv`; never widen the filter.

- [ ] **Step 6: Commit.**

```bash
git -C /home/orkhan/Desktop/elmify/.worktrees/emjm-title add apps/research/recognition.py tests/research/test_provenance_identity.py
git -C /home/orkhan/Desktop/elmify/.worktrees/emjm-title commit -m "fix(provenance): a funder-list project title is never its coordinator's name

body_names reads only REGISTER and CURATED_LIST rows (verified-catalog §3.2).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---


### Task 2: Gates and PR

- [ ] **Step 1: Run every CI gate.**

```bash
cd /home/orkhan/Desktop/elmify/.worktrees/emjm-title
uv run ruff check .
uv run mypy apps config
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=elmify_emjm_title uv run pytest -q
```

Expected: all clean. The full suite passes, apart from failures already present on `origin/master`; record any.

- [ ] **Step 2: Push and open the PR** (`gh pr create --base master --head claude/emjm-title-not-a-name`), titled "An EACEA project title is never its coordinator's name". The body cites spec §3.2 and ends with the Claude Code attribution line.
