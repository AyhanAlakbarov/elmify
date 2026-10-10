# Funding engine, slice 1: one student receives one real award — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Join the two halves of the engine that have never been joined. The reader writes
`FundingOpportunity` rows nothing reads; the evaluator and `build_pack` are reached from tests only;
the one live path that makes a pack fetches `https://official.example.test/program.json` and
hard-codes `eligible=True`. After this plan, a real student's pack is built from real catalog rows,
awards appear as their own applications, and **an award the readings disagreed about on a detail is
shown with that detail marked unconfirmed instead of being hidden entirely** — which is why ten
awards decided on five known funders currently reach nobody.

**Architecture:** Four movements, in dependency order. (1) One lineage — three branches carrying this
work merge to `master`. (2) The `Organisation` register, so an award has a holder row to point at and
a domain key that survives a funder owning two domains. (3) Tiered agreement and award identity in
the judge, so existence gates the award and details do not. (4) The spine — `pool.py` → `facts.py` →
gates → `build_pack`, replacing the fixture path in `handle_research_message`.

**Tech Stack:** Django 5.2, Postgres 17 with RLS, Pydantic v2 schemas for model output, pytest with
the repo's test DB. No new dependency, with one exception in Task 4 (Public Suffix List — already
vendored as `apps/research/hosts.py` on `claude/reader-holder-axis`; this plan only merges it).

**Spec:** `docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md` — build-order
items **0, 2, 3, 4** (item 1 is optional and deliberately excluded, §12). Sections this plan
implements: §6.1 (the register), §8.6 (tiered agreement), §8.7 (award identity), §10.1–10.3 (the
spine), §11's privacy rule for a platform table. Everything from item 5 on is out of scope and must
not be started here.

**Base branch:** `master`. Work in a fresh worktree (`git worktree add ../funding-slice-1 master`).
Test database: `POSTGRES_DB=tehsil_funding_slice1` — never share a test DB between sessions.

---

## Global Constraints

- **RLS is verified against a `NOBYPASSRLS` role or it is not verified.** The test role bypasses RLS,
  so a test asserting a shared table is readable by every tenant passes whether or not the policy
  exists. Every new table's isolation test goes through the `runtime_connection` fixture
  (`tests/tenancy/test_database_isolation.py`) or the `rls_enforced_orm` fixture
  (`tests/portals/test_rls_spine.py`). Dumping Django's SQL proves nothing — Postgres adds the
  predicate.
- **`catalog_ingestion` already exists** (`apps/funding/migrations/0006_official_snapshots.py`,
  `CREATE ROLE catalog_ingestion NOLOGIN`). New shared tables carry the same two policies as
  `0030_program_awarding_institutions_rls.py` and nothing more. Do not create the role, do not add a
  `DATABASE_ROLE` option — that is the spec's optional item 1 and is out of scope.
- **Migration numbering collides on merge, by design.** Three branches carry `funding` migrations on
  the same chain. After every merge in Task 1, run `makemigrations --check --dry-run` and renumber
  the *local* branch's migrations, fixing each `dependencies` entry that names a node that was itself
  renumbered upstream. CLAUDE.md's "Migrations" section explains why this exact shape is expected and
  is not a bug.
- **Never widen the serve rule on existence.** "Never show money the page does not offer" survives
  this plan unchanged. Task 8 relaxes *details* only, and a test pins that an award whose readings
  split on `offered`, `holder` or `scope` is still not served.
- **A platform table carries nothing about a person.** Applies to Task 12's priority computation:
  the count is a query, never a column. (`ResolutionItem` itself is spec item 12 and out of scope.)
- **Every model-calling path keeps its limiter.** Nothing in this plan adds a model call; nothing in
  it may remove a `rate_limited()` call either.
- Never run `ruff format` here. After every task: `uv run ruff check apps config tests scripts`,
  `uv run mypy apps config`, `POSTGRES_DB=tehsil_funding_slice1 uv run pytest`,
  `uv run python manage.py makemigrations --check --dry-run`.

---

## File Structure

| file | responsibility |
|---|---|
| `apps/research/hosts.py` (merged, Task 1) | `registrable_domain()` on the Public Suffix List |
| `apps/research/models.py` (modify, Task 4) | `Organisation`, `OrganisationDomain`, `OrganisationIdentifier` |
| `apps/research/register.py` (new, Task 5) | `record_organisation()` — the dedupe seam |
| `apps/research/funding_judge.py` (modify, Tasks 7–8) | award identity; tiered agreement |
| `apps/research/funding_reader.py` (modify, Task 9) | the serve rule reads existence only; `organisation` FK |
| `apps/funding/models.py` (modify, Task 6) | `FundingOpportunity.organisation` FK + scope-shape constraint |
| `apps/funding/pool.py` (new, Task 10) | the interim pool query |
| `apps/funding/facts.py` (new, Task 11) | `program_facts()`, `award_facts()` |
| `apps/funding/conditions.py` (new, Task 11) | the shared condition engine, moved from `evaluation.py` |
| `apps/funding/evaluation.py` (modify, Task 11) | `AwardCandidateFacts`, award gates; imports the shared engine |
| `apps/funding/pack.py` (modify, Task 12) | `build_pack` gains the award-application list |
| `apps/research/services.py` (modify, Task 13) | `handle_research_message` = pool → facts → evaluate → pack |
| tests | `tests/research/test_organisation_register.py`, `test_award_identity.py`, `test_tiered_agreement.py` (new); `tests/funding/test_pool.py`, `test_facts.py`, `test_award_gates.py`, `test_spine.py` (new); `tests/tenancy/test_database_isolation.py`, `tests/funding/test_pack.py`, `tests/research/test_services.py` (modify) |

---

## Movement A — one lineage

### Task 1: Merge the three branches to `master` — **DONE 2026-09-23**

Master now carries, in one tree: `funding_judge.py` + `funding_reader.py` (#104), the vendor fetch
seam `apps/research/fetch/` (#103), and the holder axis with `hosts.py`, `eligibility.py` and
`validity.py` (#116). Gone: `vendors.py`, `browser_server.py`, the Scrapling tier. The `funding`
migration chain ends at `0042_condition_type_to_key`. **Task 2 is the next thing to run.**

**Files:** the whole tree; no new code is written in this task.

- [x] **Step 1: Establish what each branch carries, before merging anything** — *run 2026-09-22;
  the topology is not what this task assumed, and Steps 2–3 are rewritten below on what was found.*

```
gh pr list --state open --json number,headRefName,baseRefName,mergeStateStatus
for b in claude/programme-funding-reader claude/program-page-reader claude/vendor-fetch claude/reader-holder-axis; do
  echo "$b ahead=$(git rev-list --count master..$b) behind=$(git rev-list --count $b..master)"; done
git merge-base --is-ancestor claude/programme-funding-reader claude/reader-holder-axis
```

| branch | PR | base | position vs `master` | state |
|---|---|---|---|---|
| `claude/programme-funding-reader` — the reader | **#104** | `master` | 43 ahead, **0 behind** | `CLEAN`, 10/10 checks pass, **no human review** |
| `claude/vendor-fetch` — the fetch path | **#103** | **`claude/program-page-reader`, not `master`** | 103 ahead, 105 behind | `UNSTABLE` |
| `claude/program-page-reader` — #103's base | none | — | 82 ahead, 105 behind | stale intermediate |
| `claude/reader-holder-axis` — holder axis | **none** | — | 156 ahead, 86 behind | parallel lineage |

Three facts this task was written without, each of which changes it:

1. **#103 does not target `master`.** Merging it lands the fetch seam on a branch 105 commits behind
   master, not in the lineage. It must be **retargeted to `master`** (`gh pr edit 103 --base master`)
   and rebased or re-merged; `claude/program-page-reader` then has no purpose and is deleted.
2. **#103's eight failing checks are not code.** The job annotation reads *"The job was not started
   because recent account payments have failed or your spending limit needs to be increased"* —
   GitHub Actions refused to start every job on 2026-09-20, with zero steps recorded. #104's checks
   passed on 2026-09-22, so the account is working now. **Re-run the checks before reading anything
   into them**; do not debug a test failure that never ran.
3. **`reader-holder-axis` is a parallel lineage, not a descendant of #104.**
   `git merge-base --is-ancestor` is false in both directions: it carries an *older* copy of the
   reader plus the holder axis, and it is 86 behind master. So this is a real three-way merge with
   conflicts expected in `funding_judge.py`, `funding_reader.py` and the `funding` migration chain —
   not the fast-forward the original Step 3 implied.

- [x] **Step 2: Merge PR #104 (the reader) to `master`** — *done 2026-09-22, as `59ec92a`. Its
  green was stale: the checks had run against a master four merges old, and #103 had since
  rewritten `discover.py` and `pipeline.py`, which the reader also touches. Merging master in first
  produced four conflicts — `discover.py` (both PRs edited it: `--render` and
  `render_via_browser_service` dropped with the browser tier, `--funding` kept, and the reader's
  extraction ceiling now sits beside #103's `SweepBudget`, deliberately not merged into one
  budget), `pipeline.py` (import-block collision, both sides needed) and the two glass-box
  documents (master's, already reconciled). Gate: 2953 passed / 45 skipped — the reader's suite and
  the vendor path's together for the first time; ruff, mypy (333 files) and `makemigrations --check`
  clean. All 10 CI checks green on the merge commit, `claude-review` passed with no findings.*

It is the only one of the three that is ready: on `master` as its base, zero behind, every check
green. Everything downstream builds on it. **It has no human review — that is the owner's call, not
this plan's**, and the plan stops here until it is taken.

- [x] **Step 2a: Retarget and revive PR #103** — *done 2026-09-22. Retargeted to `master`; merged
  master twice (local master carried 39 unpushed glass-box commits and had to be reconciled with
  `origin/master` and pushed first, or the PR read as CONFLICTING against a master that existed
  nowhere as one tree). Seven conflicts across the two merges, each recorded in its merge commit.
  Gate: 2844 passed / 45 skipped, ruff + mypy clean, `makemigrations --check` clean. All 9 CI
  checks green once the billing block lifted. **Merged as `95a305c`**; `claude/program-page-reader`
  deleted (fully contained in master, no PR or worktree on it).*

`gh pr edit 103 --base master`, merge current `master` into `claude/vendor-fetch` (105 commits
behind, so expect conflicts in `egress.py`, `discovery.py`, `pipeline.py` and `CLAUDE.md` — take
master's version of anything the fetch work did not author), push, and let the checks run now that
the billing block is gone. Merge only on green. Then delete `claude/program-page-reader`.

- [x] **Step 3: Merge `claude/reader-holder-axis`, dropping two files** — *merged as **PR #116**
  (`30cb666`) on 2026-09-23, all 10 checks green, no findings. Three files dropped, not two
  (`fetch_ladder.py` joined the list, above). Nine conflicts: `discovery.py`, `fetch_ladder.py`,
  `config/settings/base.py` and `CLAUDE.md` took master's, each describing the fetch path that
  survives; `pipeline.py` and `pyproject.toml` kept both sides; `uv.lock` regenerated. Two breakages
  the merge created rather than inherited, both recorded below. Gate: 3303 passed / 45 skipped,
  ruff clean, mypy clean over 351 files, bandit 0/0/0, `makemigrations --check` clean.*

**The two breakages, because each generalises.** First, `funding_yield.py` — the gate harness this
plan's Task 8 depends on — still fetched through `egress.fetch_official_source`, which #103 renamed.
It now goes through `retrieve_official_source`, which the eligibility spec §5 had already required in
writing: fetching the old way makes the gate re-measure the JavaScript shells the vendor path closed,
so a stale import would have produced a *plausible wrong number* rather than an error.

Second, the migration collision, and it is worth more than its fix. `0035_holder_axis` depended on
`0034_funding_review` — a name #104 renumbered to `0036` — so the branch's five migrations moved to
**0038–0042** behind master's merge node. `makemigrations --check` caught the graph, as CLAUDE.md
says it does. What it could not catch: **three tests reach that migration through
`importlib.import_module("apps.funding.migrations.0039_condition_type_to_key")`**, a string no
renumbering tool and no import checker will find. They failed only under `pytest`, after the graph
was already consistent. A migration referenced by module name is a dependency that lives outside the
dependency graph — grep for the old number across `tests/` and `apps/` after any renumber.


Take everything **except**:

- `apps/research/vendors.py` and its tests — superseded by PR #103's `apps/research/fetch/` seam.
  Spec §17 row 1: the quota-mode ladder (`FETCH_VENDOR_MODE`, scrape.do first on free tiers) is
  retired in favour of Firecrawl-first, and two fetch paths in one tree is the bug this plan exists
  to avoid multiplying.
- `apps/research/models.py::HostFetchCost` and its migration — spec §17 row 18 folds per-host cost
  into `HostProfile`, which is spec item 5 and not built here. Dropping it now avoids a table nobody
  writes.
- `apps/research/management/commands/fetch_ladder.py` — **added 2026-09-22 after re-measuring the
  branch.** Both lineages wrote a `fetch_ladder` command independently: this branch's drives
  `vendors.py`, master's (from #103) drives `apps/research/fetch/`. Master's is the one that matches
  the seam that survives, so take master's and drop this branch's, exactly as with `vendors.py`. A
  file present on both sides with the same path and a different implementation is the case a merge
  resolves *silently* in whichever direction the conflict markers happen to fall — check this one by
  name rather than trusting the resolution.

**Re-measured against current master, 2026-09-22 (after #103 and #104 landed):** the branch is **75
ahead / 119 behind**, not the 156/86 recorded in Step 1, and it overlaps master on 20+ files under
`apps/` — `egress.py`, `discovery.py`, `pipeline.py`, `discover.py`, `extraction.py`, `reader.py`,
`search.py`, `seeds.py`, `catalog.py`, `models.py` and the `funding` migration chain. Expect a
merge closer to the two already done than to a clean take-everything-except.

Because it is a parallel lineage rather than a descendant (Step 1, fact 3), open it as a PR against
`master` rather than merging locally: it is 156 commits of somebody's work and the conflict
resolution in `funding_judge.py` deserves a diff someone can read. **Where the two copies of the
reader disagree, PR #104's is newer and wins**; the holder axis is what is being taken from this
branch, not a second reader.

Everything else merges: the holder axis on `LineVerdict`/`FundingDecision`, `pointer_leads`,
`tie_break_offered`, `apps/funding/validity.py`, `apps/funding/eligibility.py` with `decide` and
`ConditionTriple`, the widened `BenefitRule`, and `apps/research/hosts.py`.

- [ ] **Step 4: Renumber migrations and prove the chain**

```
uv run python manage.py makemigrations --check --dry-run    # must print "No changes detected"
POSTGRES_DB=tehsil_funding_slice1 DATABASE_ROLE=migration uv run python manage.py migrate
```

A `dependencies` entry naming a migration that was renumbered upstream is the expected failure; fix
the name, never the number of an already-merged migration.

- [ ] **Step 5: Verify and record**

Full suite green, ruff, mypy, `makemigrations --check`. Record the test count in the ledger — later
tasks compare against it.

**Verification:** one branch contains the reader, the fetch seam, the holder axis, `validity.py`,
`eligibility.py` and `hosts.py`; `git grep -l "FETCH_VENDOR_MODE\|HostFetchCost" apps/` returns
nothing.

---

### Task 2: Rename `TALENT` to `GRADE` in the eligibility vocabulary — **DONE 2026-09-23**

Owner decision 2026-09-22 (spec §17 row 25). Zero rows exist, so this is a rename on an empty table;
after the first real row it is a data migration.

**Files:**
- Modify: `apps/funding/eligibility.py`, `apps/funding/models.py` (`BenefitRule` key choices),
  `apps/research/funding_judge.py` (the prompt's key list)
- Test: `tests/funding/test_eligibility.py`

- [ ] **Step 1: Write the failing test**

```python
def test_grade_decides_on_an_identical_scale_and_talent_does_not_mean_a_number():
    """Two different conditions were sharing one key. GRADE is a numeric bar on a
    stated scale; TALENT is sports or arts, a label nothing in the profile decides."""
    grade = ConditionTriple(key="GRADE", operator="GTE", value="3.5",
                            unit="GPA_4", quote="A minimum GPA of 3.5 is required.")
    assert decide(grade, profile_with_grade("3.7", "GPA_4")).outcome == "SATISFIED"

    talent = ConditionTriple(key="TALENT", operator="PRESENT", value="music",
                             quote="Open to students with a record of musical achievement.")
    decision = decide(talent, profile_with_grade("3.7", "GPA_4"))
    assert decision.outcome == "UNDECIDABLE"
    assert "profile does not carry" in decision.reason
```

- [ ] **Step 2: Run it and watch it fail** — `KeyError: 'GRADE'`.

- [ ] **Step 3: Rename**

`GRADE` takes the existing `TALENT` decider unchanged (grades are never converted; identical scale
strings only). `TALENT` becomes a label-form key with operator `PRESENT` and no decider — always
`UNDECIDABLE` with the naming reason, exactly like `NEED` and `DISABILITY`.

- [ ] **Step 4: Migrate** — `makemigrations funding`, and assert in the migration's docstring that it
touches zero rows because `BenefitRule.objects.count() == 0` in every environment.

- [ ] **Step 5: Verify** — the whole `eligibility.py` table-driven suite passes; the judge's prompt
lists both keys with their distinct definitions.

---

## Movement B — the Organisation register

### Task 3: A test that fixes the shape before any model exists — **DONE 2026-09-23**

**Files:** Create `tests/research/test_organisation_register.py`

- [ ] **Step 1: Write the three tests that encode the measured lessons**

```python
def test_one_organisation_can_hold_several_domains():
    """ROR returns bwstiftung.de for the foundation whose scholarship lives on
    bw-stipendium.de (measured 2026-09-19). Under a one-domain key those never
    join, and the award's holder and the register's row are different objects."""

def test_a_new_domain_attaches_only_on_a_shared_identifier_never_on_a_name():
    """The resolver measurements' lesson: adjacent organisations share names
    (Carl-Zeiss-Stiftung vs ZEISS; Inönü Vakfi vs Inönü Üniversitesi). An
    identifier (ROR, Wikidata, EACEA PIC) is evidence; a matching name is not."""

def test_kind_is_the_holder_vocabulary_not_a_second_taxonomy():
    """A funder's kind IS its holder type (spec §6.1). Two taxonomies over one
    object is how a register and a reader come to disagree about what a body is."""
```

- [ ] **Step 2: Run and watch all three fail** — `ImportError: cannot import name 'Organisation'`.

---

### Task 4: The three models and their RLS — **DONE 2026-09-23**

**Files:**
- Modify: `apps/research/models.py`
- Create: `apps/research/migrations/00NN_organisation_register.py`
- Modify: `tests/tenancy/test_database_isolation.py` (`_SHARED_TABLES`)

**Interfaces:**
- Consumes: `apps.research.hosts.registrable_domain`, `apps.funding.models` holder value tuple
- Produces: `Organisation`, `OrganisationDomain`, `OrganisationIdentifier`

- [ ] **Step 1: Write the models**

`Organisation`: `primary_domain` (unique, the display key), `name`, `names` (ArrayField — every label
a register or Wikidata supplies; the resolver scores the union of them), `kind` (choices = the
sixteen holder values imported from `apps.funding.models`, one taxonomy), `country_code`,
`official_website`, `status` (`REGISTERED` / `CANDIDATE` / `REJECTED`), `rejected_reason`
(`INFRASTRUCTURE` / `NOT_A_FUNDER` / `DOES_NOT_EXIST` / `UNREACHABLE`, blank unless `REJECTED`),
`found_via` (ArrayField of route tags), `first_seen`, `last_verified`, `parent` (self-FK, for a
faculty under its institution), plus read state `last_read_at`, `pages_read`, `pages_unreadable` and
the five nullable cadence fields (`cadence`, `cadence_open_month`, `cadence_deadline_month`,
`cadence_source`, `cadence_verified_for_cycle`).

`OrganisationDomain`: `organisation` (FK, PROTECT), `registrable_domain` (unique), `found_via`,
`first_seen`.

`OrganisationIdentifier`: `organisation` (FK, PROTECT), `scheme`, `value`, unique together
`(scheme, value)`.

Two notes that belong in the code, not only here: read state is **latest-state fields, not a history
table** (`ponytail:` comment naming the upgrade path); and nothing about cells goes on the
organisation — its `country_code` is its home, and the countries it funds derive from its awards.

- [ ] **Step 2: The RLS migration**

Three `RunSQL` blocks in the shape of `0030_program_awarding_institutions_rls.py` — `ENABLE ROW LEVEL
SECURITY`, `shared_catalog_select` for SELECT, `catalog_ingestion_write` for ALL — with the reverse
SQL. No `CREATE ROLE`: it exists.

- [ ] **Step 3: Add all three tables to `_SHARED_TABLES`** in
`tests/tenancy/test_database_isolation.py`.

- [ ] **Step 4: Verify against a real `NOBYPASSRLS` role**

```
POSTGRES_DB=tehsil_funding_slice1 uv run pytest tests/tenancy/test_database_isolation.py -v
POSTGRES_DB=tehsil_funding_slice1 uv run pytest tests/research/test_organisation_register.py -v
```

The isolation test must run through `runtime_connection`. A green test on the default role proves
nothing (CLAUDE.md).

---

### Task 5: `record_organisation` — the dedupe seam — **DONE 2026-09-23**

**Files:** Create `apps/research/register.py`; test in `tests/research/test_organisation_register.py`

**Interfaces:** `record_organisation(*, domain, name, kind, country_code, found_via, identifiers=(), names=()) -> Organisation`

- [ ] **Step 1: Write the failing tests** (the three from Task 3, now against the real function, plus:)

```python
def test_a_domain_already_known_returns_its_organisation_and_adds_the_route_tag():
    """Discovery reaches the same body by four routes; found_via is a list so a
    per-route tally (§15) can say which route found what, and the second route
    must not create a second row."""

def test_an_infrastructure_host_is_stored_rejected_so_it_is_never_fetched_twice():
    """mail., vpn., cdn. hosts are a fifth of an inventory sweep. Storing the
    rejection is the whole saving; forgetting it pays the fetch every cycle."""
```

- [ ] **Step 2: Run and watch them fail.**

- [ ] **Step 3: Implement**

Lookup order, and it is the whole function: (1) `OrganisationDomain` by `registrable_domain(domain)`
— **any** domain, not the primary; (2) failing that, `OrganisationIdentifier` by any supplied
`(scheme, value)` — and if it hits, attach the new domain to that organisation; (3) failing both,
create. **Never match on `name`.** Every path appends the route tag to `found_via` and merges
`names`.

- [ ] **Step 4: Verify** — the register suite green; `mypy` clean.

---

### Task 6: `FundingOpportunity.organisation` — a real link — **DONE 2026-09-23**

**Files:**
- Modify: `apps/funding/models.py`, `apps/research/funding_reader.py`
- Create: migration (FK + backfill + constraint)
- Test: `tests/funding/test_funding_models.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_holder_scoped_award_requires_an_organisation():
    """holder_domain was a string 'because the register lives on another branch'
    (2026-09-18). It does not any more, and a string holder cannot carry the
    second domain, the cadence or the read state the verifier needs."""
    with pytest.raises(IntegrityError):
        FundingOpportunity.objects.create(scope="HOLDER", organisation=None, ...)
```

- [ ] **Step 2: Run and watch it fail** — the row is created.

- [ ] **Step 3: Add the FK, backfill, and move the constraint**

`organisation = models.ForeignKey(Organisation, on_delete=models.PROTECT, null=True)`. In the same
migration, a `RunPython` backfill from `holder_domain` through `OrganisationDomain` (creating a
`CANDIDATE` row for a domain the register has not seen — a funder we already read is a body we
already know). Then amend `funding_opportunity_scope_shape_valid` so `HOLDER` requires `organisation`
non-null instead of `holder_domain != ""`.

**`holder_domain` is not dropped in this plan.** It is dropped in a later migration once a test
asserts every `HOLDER` row carries the FK; dropping a column in the same change that backfills it
leaves no way to check the backfill was right.

- [ ] **Step 4: Verify** — backfill covers every existing `HOLDER` row (assert in the test, not only
in the migration); `makemigrations --check` clean.

---

## Movement C — the judge

### Task 7: Award identity — `(organisation, page, heading, kind)` — **DONE 2026-09-23**

The holder-axis plan keyed an award on `(holder domain, kind)`, so a ministry's dozens of schemes
collapse into one row. A "find all" engine that cannot count DAAD's programmes is not finding all.

**Files:**
- Modify: `apps/research/funding_judge.py` (the grouping in `awards`), `apps/research/funding_reader.py`
- Create: `tests/research/test_award_identity.py`

- [ ] **Step 1: Write the failing test**

```python
def test_two_awards_under_two_headings_on_one_page_are_two_decisions():
    """Measured shape: an agency page lists several schemes of one kind, each
    under its own heading. Grouped by (kind, scope) they become one row whose
    quotes come from two different awards -- and a student sees one."""
    chunk = lines_under_headings(
        ("## Masters Scholarship", "Covers full tuition for one year."),
        ("## Research Fellowship", "A monthly stipend of 1,200 EUR."),
    )
    result = awards(chunk, readings=three_agreeing_readings(chunk))
    assert len(result.decisions) == 2
    assert {d.heading for d in result.decisions} == {"Masters Scholarship", "Research Fellowship"}


def test_one_award_spanning_several_lines_under_one_heading_stays_one_decision():
    """The other half: the grouping must not shatter a multi-line award, which is
    what the verbosity finding (2026-09-22 hand-sample) is about."""
```

- [ ] **Step 2: Run and watch the first fail** (one decision, not two) and the second pass.

- [ ] **Step 3: Implement**

`Line` already carries `heading`. The group key becomes `(heading, kind)` inside one page, and the
stored identity is `(organisation, page, heading, kind)`. `FundingDecision` gains `heading`. The
judge's six-word `name` stays a label and is not part of identity — it is a model's choice and varies
between reads; a heading is the site's own structure.

- [ ] **Step 4: Verify** — the existing judge suite passes unchanged except where it asserted the old
key; every changed assertion is reviewed, not just updated.

---

### Task 8: Tiered agreement — **DONE 2026-09-23**

**Files:**
- Modify: `apps/research/funding_judge.py` (`awards`, `FundingDecision`)
- Create: `tests/research/test_tiered_agreement.py`

- [ ] **Step 1: Write the failing tests — the measured case first**

```python
def test_an_award_split_on_money_form_is_shown_with_that_field_unconfirmed():
    """Measured 2026-09-19: ten awards decided on five known funders, none shown,
    all split on route and money_form, none on holder. Hiding the award is the
    wrong failure direction for a recall-first goal -- the student loses a real
    scholarship because two models disagreed about grant vs subsidy."""
    decision = awards(chunk, readings=split_on("money_form")).decisions[0]
    assert decision.agreement == "AGREED"
    assert "money_form" in decision.unconfirmed
    assert decision.money_form == "UNSTATED"


def test_an_award_split_on_offered_is_still_not_agreed():
    """Existence is untouched. 'Never show money the page does not offer' is the
    one guarantee this task may not weaken."""
    for field in ("offered", "holder", "scope"):
        assert awards(chunk, readings=split_on(field)).decisions[0].agreement == "UNAGREED"


def test_an_unconfirmed_field_is_never_a_filterable_value():
    """The pool must not filter on a value no reading confirmed -- that is how a
    disagreement becomes a silent exclusion instead of a visible caveat."""
```

- [ ] **Step 2: Run and watch them fail** — the first returns `UNAGREED`.

- [ ] **Step 3: Implement**

`_EXISTENCE = ("offered", "holder", "scope")`. In `awards`: a split on an existence field keeps
today's `UNAGREED`; a split on any other decided field sets that field to `UNSTATED`, adds its name
to a new `unconfirmed: tuple[str, ...]`, and leaves `agreement == "AGREED"`. `disputed` keeps its
meaning for the operator queue and now records every unconfirmed field too, so nothing is lost from
the review path.

The existing per-condition rule is the same shape one level down and is already built: a condition
the readings split on goes to `disputed_conditions` and never to `conditions`. Do not re-implement
it; make the field rule match it.

- [ ] **Step 4: Verify, and quantify the change**

Run the judge suite. Then, on the recorded 58-host fixtures if they exist in-tree, print
`awards shown ÷ awards found` before and after. If the fixtures are not in-tree, record that the
number is owed to the §8.8 gate and do not invent it.

---

### Task 9: The serve rule reads existence only — **DONE 2026-09-23**

**Files:** Modify `apps/research/funding_reader.py::_served`, `write_funding_decision`,
`write_holder_decision`; test in `tests/research/test_funding_reader.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_row_with_an_unconfirmed_detail_is_served_and_carries_the_caveat():
    """The serve gate's four conditions are unchanged except that 'every decided
    field unanimous' becomes 'every EXISTENCE field unanimous'."""

def test_a_row_whose_readings_split_on_offered_is_not_served():
    """Pinned separately so a future change to the existence tuple fails loudly."""
```

- [ ] **Step 2: Run and watch the first fail.**

- [ ] **Step 3: Implement** — `_served` reads `agreement == "AGREED"` (which Task 8 has already
redefined) and the unchanged three: the award names a benefit or a stated money form; the lead is
vouched; no `REJECTED` review stands for this page version. The writer persists `unconfirmed` on the
row so the card can render it. `organisation` is set from Task 6's FK via `record_organisation`.

- [ ] **Step 4: Verify** — the reader suite green; `review_funding` still binds to `reviewed_sha256`.

---

## Movement D — the spine

### Task 10: The pool — **DONE 2026-09-23**

**Files:** Create `apps/funding/pool.py`, `tests/funding/test_pool.py`

**Interfaces:** `candidate_pool(profile, *, limit) -> PoolResult` (programmes and served awards, plus
the reason when it is empty)

- [ ] **Step 1: Write the failing tests**

```python
def test_the_pool_never_reads_an_unserved_row():
    """The serve gate is the catalog's promise; the pool does not second-guess it,
    and a pool that read unserved rows would put a disputed award in front of a
    student through the back door."""

def test_a_preference_filters_the_pool_and_a_non_negotiable_does_not():
    """allowed_countries is already a hard gate. Filtering the pool by a preferred
    country hides funding the student would have taken -- so only
    excluded_countries and the field narrow the pool."""

def test_an_empty_pool_reports_why():
    """P1-7: never a silently short pack. The run records field, countries and
    intake, and the pack publishes that sentence."""
```

- [ ] **Step 2: Run and watch them fail.**

- [ ] **Step 3: Implement the interim query**

`target_field` + `excluded_countries` + `intended_intake` over catalog programmes and served `HOLDER`
awards, bounded by an explicit limit, ordered deterministically. Document in the module docstring
that cell selection (spec §10.1) **replaces** this query rather than extending it, so nobody grows
this into the real thing.

- [ ] **Step 4: Verify.**

---

### Task 11: Two fact types, one condition engine — **DONE 2026-09-23**

**Files:**
- Create: `apps/funding/conditions.py`, `apps/funding/facts.py`, `tests/funding/test_facts.py`,
  `tests/funding/test_award_gates.py`
- Modify: `apps/funding/evaluation.py`

- [ ] **Step 1: Move the condition engine with no behaviour change**

`_unmet_conditions`, `unevaluable_condition_reasons`, `open_routes`, `closed_route_reasons`,
`_return_service_disclosures` move to `apps/funding/conditions.py`; `evaluation.py` imports them.
**The 41 existing evaluator tests must pass untouched** — if any needs editing, the move changed
behaviour and must be redone.

- [ ] **Step 2: Write the failing translator tests — one per "when absent" row**

```python
def test_a_country_list_shape_with_no_list_becomes_an_undecidable_condition():
    """The reader records nationality_shape but not WHICH countries (spine §3.2).
    A translator that guessed the list would be inventing eligibility; the honest
    output is undecidable, carrying the award's own sentence as the reason."""

def test_no_benefit_means_no_coverage_never_a_zero_cost_assumption():
def test_no_deadline_leaves_the_intake_gate_to_decide_never_a_fabricated_date():
def test_an_unagreed_row_translates_to_low_evidence_confidence():
def test_an_unconfirmed_field_does_not_become_a_condition():
```

- [ ] **Step 3: Implement `AwardCandidateFacts` and the two translators**

`award_facts(opportunity)` and `program_facts(program, profile_intake)`, both pure — no I/O inside
them; rows are fetched by the caller. `CandidateFacts` is **unchanged**, so today's `HARD_GATES` and
their tests are untouched (rejected: an optional `program_id`, which would need an `if` in every
programme gate, and a gate that silently skips is worse than a crash in this repo).

- [ ] **Step 4: The four award gates**

Conditions the student demonstrably fails; `cycle_validity` on the award's evidence; the selected
deadline still reachable against `intended_intake`; evidence confidence not `LOW`.

`cycle_validity` runs on **step-0 evidence only** — what the reader stored. Without the evidence
ladder there is no call history, so `UPCOMING` is unreachable and most awards return `UNVERIFIED`.
**Therefore the gate hides an award only when the evidence says it is shut** (`SUSPENDED`, `ENDED`,
a passed deadline); an `UNVERIFIED` award enters the pool flagged and never the recommended pack.
This is deliberately weaker than the spec's "only OPEN and UPCOMING are shown" and tightens
automatically when the ladder lands — same function, more evidence. Gating hard today empties the
pack for want of a crawler, which is the worse failure. Put that paragraph in the code.

- [ ] **Step 5: Verify** — new suites green; the 41 evaluator tests green and unedited.

---

### Task 12: The pack gains a second list — **DONE 2026-09-23**

**Files:** Modify `apps/funding/pack.py`, `tests/funding/test_pack.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_an_awards_money_is_not_counted_against_a_programmes_cost():
    """Owner decision 2026-09-19: an award is an application, not a discount.
    Counting money not yet won understates the gap by exactly the amount at risk."""

def test_an_award_application_carries_its_own_deadline_and_sentence():
def test_an_award_deciding_before_a_fee_deadline_orders_scholarship_first():
def test_every_excluded_candidate_is_published_with_its_reason():
    """P1-7: visible with the reason, never a silently short pack."""
```

- [ ] **Step 2: Run and watch them fail.**

- [ ] **Step 3: Implement** — `build_pack` returns programme applications (today's shape, ordering
and budget arithmetic unchanged) plus award applications as their own entries. `_ordering_for` is
untouched.

- [ ] **Step 4: Verify.**

---

### Task 13: The entry point — replace the fixture path — **DONE 2026-09-23**

**Files:** Modify `apps/research/services.py`, `apps/funding/models.py`
(`RecommendationCandidate` gains a FK to its catalog row); test `tests/funding/test_spine.py`

- [ ] **Step 1: Write the end-to-end failing test**

```python
def test_one_student_one_programme_one_award_becomes_a_pack():
    """The test that fails today for every reason in the spine spec §1: the
    evaluator has no production caller, the live path is a fixture skeleton, and
    nothing student-facing reads the reader's catalog."""
```

- [ ] **Step 2: Run and watch it fail.**

- [ ] **Step 3: Implement**

`handle_research_message` keeps its message-driven seam and its `select_for_update` on the run. Its
body becomes pool → facts → evaluate → `build_pack` → write `RecommendationCandidate` rows (now with
a FK to the catalog row they came from) → publish. The placeholder fetch of
`https://official.example.test/program.json`, `OfficialFixture` and the hard-coded `eligible=True` go.

A `POSSIBLY_ELIGIBLE_REVIEW` outcome opens a **tenant-scoped** `ConsultantResearchTask` — a question
about one student's own eligibility, which belongs to that student's agency. Catalog questions are
the platform's alone (spec §11) and are not created here. Publication stays un-gated by counsellor
review (§38): the task is work for a human, not a hold on the student's pack.

- [ ] **Step 4: The failure paths, each its own test**

Empty pool → an empty pack carrying the sentence; an untranslatable row → skipped, counted, named in
the run's degraded list, and one bad row never fails a pack; every candidate excluded → the excluded
list with reasons.

- [ ] **Step 5: Verify** — full suite, ruff, mypy, `makemigrations --check`.

---

## Self-Review — run 2026-09-23

Every task above is done. What the plan asked for and did not get, and what it
asked for that turned out to be wrong, is recorded under each item below rather
than dropped.

After Task 13, before any PR:

- [ ] **The slice is real.** One student, one programme row, one served holder award, a fake rate
  table → a pack with one programme application and one award application. This is the deliverable;
  if it does not run, nothing else in this plan matters.
- [ ] **Existence is not weakened.** A row split on `offered`, `holder` or `scope` is not served —
  asserted at both the judge and the writer.
- [ ] **RLS is verified through `runtime_connection`**, not the test role, for all three new tables.
- [ ] **Nothing personal is in a shared or platform table** — the register carries hosts and
  organisations only.
- [ ] **No fetch path was added or re-added.** `git grep -l "FETCH_VENDOR_MODE\|vendors.py"` is empty;
  `apps/research/fetch/` is the only seam.
- [ ] **The 41 evaluator tests are green and unedited.**
- [ ] **Counts recorded** in the ledger: tests before Task 1, after Task 1, after Task 13; and
  `awards shown ÷ awards found` if the fixtures allowed it, or an explicit "owed to the §8.8 gate".
- [ ] **Out of scope stayed out:** no `HostProfile`, no `FetchAttempt`, no providers, no registers,
  no classifier, no resolver changes, no `ResolutionItem`, no cells, no on-demand search.

## Where the plan was wrong, recorded 2026-09-23

Each of these was built against the code rather than the plan, and each is the
kind of thing the next slice will hit again:

- **The holder vocabulary is 15 values, not "the sixteen".**
- **Task 2's snippet passes `unit="GPA_4"`**, which `eligibility.Unit`
  (`MONTHS|HOURS|YEARS`) rejects — the scale travels inside `value`, which is
  what the existing decider reads.
- **`OrganisationIdentifier`'s scheme list** is specified as "the
  `InstitutionIdentifier` vocabulary plus three", and that model was DELETED on
  2026-09-14 with the institution-safety screen. The list survives only in
  `funding/migrations/0028`, which is where it was taken from.
- **The register's RLS cannot live in `research/0003`.** Depending on
  `funding/0006` for the `catalog_ingestion` role makes `research` downstream of
  `funding`, and every test that rolls funding back while other apps stay at
  their head then builds a plan holding both directions —
  `InvalidMigrationPlan`, six failures in `tests/migrations/test_task7_migrations.py`.
  It is in `funding/0044`, which already depends on `research/0003` for the FK.
- **Task 11's route-scoped engine does not answer for an award.** An award is
  one route, itself, and carries no `BenefitFact` until a page states an amount,
  so `open_routes` returned an empty set and dropped every one of its conditions
  silently. `conditions.failed_conditions` / `undecidable_conditions` are the
  same engine one level down.
- **Task 13's "untranslatable row" is unreachable from the pool.**
  `program_country_iso3166_alpha2` and `program_duration_months_range` refuse
  both candidate cases at the database. The guard stays as defence in depth and
  says so.

## What this plan deliberately does not prove

That the options are *good*. It makes the path exist. Whether a served card's amount, deadline and
eligibility are true is the 30-card hand check (spec §8.8), and whether the catalog is *complete* is
every gate from item 5 on. Both are the next plans' work, and both are measurable only once a pack
can be built at all.
