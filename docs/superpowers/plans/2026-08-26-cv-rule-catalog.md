# CV Rule Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the researched CV rules reach a rendered CV — a shared rule table, a resolver, the two missing checkers, and the wiring that has never existed.

**Architecture:** A curated seed module (reviewed code, not a CSV parser) populates a shared `CatalogRule` table. `resolve_rules(program, opportunity)` merges rules across four scopes by specificity into the existing `ConstraintRule` tuple, which the existing `render_cv` pre-flight already knows how to enforce. A nullable `DocumentDraft.funding_opportunity` lets a CV say which scholarship it is for; empty means self-funded.

**Tech Stack:** Django 5.2, PostgreSQL (ArrayField, row-level security), Pydantic v2, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-26-cv-rule-catalog-design.md`

## Global Constraints

- **Precondition: PR #19 (`claude/cv-schema-completion`) must be merged before Task 3.** `_check_prohibited_content` detects `PersonalInformation.links` and `PublicationEntry.doi`, which exist only on that branch. Branch this work from a master that includes it.
- **Never run `ruff format`.** CI runs `uv run ruff check .` only; the repo is not ruff-format-clean and a format run rewrites ~26 unrelated files. For import-order complaints use `uv run ruff check --fix <one file>`.
- **Commit through `uv run git commit`** — the pre-commit Bandit hook lives in the uv venv and a bare `git commit` fails with "pre-commit not found".
- **Use `git -C <absolute-path>` for every git command.** The shell cwd silently resets to the main repo.
- Full gate before any PR: `uv run pytest`, `uv run ruff check .`, `uv run mypy apps config`, `uv run bandit -c pyproject.toml -r apps config`, `uv run pip-audit`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`.
- **`CatalogRule` is shared and never tenant-scoped.** A funder's requirement is the same fact for every agency. Per-tenant judgement lives in the existing `ConstraintOverride`.
- **Do not implement the AI-use policy gate.** It is deferred by explicit decision; see the spec's "Deferred" section.
- Baseline before starting: `uv run pytest` is green. Record the count; every task must leave it green.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `apps/funding/models.py` | **Modify** — add `CatalogRule` (shared catalog, beside `Program`) and `FundingOpportunity.cv_format_requirement`. Lives here, not in documents, because `apps/documents/render.py` already imports `apps.funding.models`; the reverse would be an import cycle. |
| `apps/funding/migrations/0016_catalog_rule.py` | **Create** — table, RLS policy, and the `FundingOpportunity` column. |
| `apps/documents/migrations/0013_draft_funding_opportunity.py` | **Create** — nullable FK on `DocumentDraft`. |
| `apps/documents/constraints.py` | **Modify** — `resolve_rules()` lives here, beside `rules_from_program()` which it reuses. |
| `apps/documents/render.py` | **Modify** — two new checkers, one widened checker, `select_render_variant` gains the opportunity, `render_draft` resolves its own draft. |
| `apps/documents/catalog_seed.py` | **Create** — the curated rows. Data only, no logic, so a reviewer can read it against the CSV. |
| `apps/documents/management/commands/seed_cv_rules.py` | **Create** — idempotent loader. |
| `tests/documents/test_catalog_rules.py` | **Create** — model, resolver, precedence, seed. |
| `tests/documents/test_render.py` | **Modify** — the new and widened checkers, wiring, fail-closed guard. |

---

### Task 1: `CatalogRule` model and migration

**Files:**
- Modify: `apps/funding/models.py`
- Create: `apps/funding/migrations/0016_catalog_rule.py`
- Test: `tests/documents/test_catalog_rules.py`

**Interfaces:**
- Consumes: nothing
- Produces: `apps.funding.models.CatalogRule` with fields `rule_id: str`, `scope_kind: str`, `scope_values: list[str]`, `key: str`, `value: Any`, `enforcement: str`, `rule_text: str`, `source_url: str`, `verified_for_cycle: str`, `confidence: str`; and `CatalogRule.ScopeKind` with members `UNIVERSAL`, `TRACK`, `COUNTRY`, `FUNDER`.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_catalog_rules.py
import pytest
from django.db import IntegrityError

from apps.funding.models import CatalogRule

pytestmark = pytest.mark.django_db


def _rule(**overrides):
    base = dict(
        rule_id="R-080",
        scope_kind=CatalogRule.ScopeKind.FUNDER,
        scope_values=["rhodes"],
        key="max_pages",
        value=2,
        enforcement="BINDING",
        rule_text="Rhodes: CV should not exceed 2 pages.",
        source_url="https://www.rhodeshouse.ox.ac.uk/",
        verified_for_cycle="current template",
        confidence="high",
    )
    base.update(overrides)
    return CatalogRule.objects.create(**base)


def test_a_catalog_rule_round_trips_its_scope_and_value():
    rule = _rule()
    stored = CatalogRule.objects.get(rule_id="R-080")
    assert stored.scope_values == ["rhodes"]
    assert stored.value == 2
    assert stored.id == rule.id


def test_the_same_rule_id_may_set_two_different_keys():
    """R-032 is one researched rule and two constraints: no photo AND no date
    of birth. Uniqueness is on (rule_id, key), not rule_id alone."""
    _rule(rule_id="R-032", key="photo_allowed", value=False)
    _rule(rule_id="R-032", key="date_of_birth_allowed", value=False)
    assert CatalogRule.objects.filter(rule_id="R-032").count() == 2


def test_the_same_rule_id_may_not_set_the_same_key_twice():
    _rule(rule_id="R-032", key="photo_allowed", value=False)
    with pytest.raises(IntegrityError):
        _rule(rule_id="R-032", key="photo_allowed", value=True)


def test_a_universal_rule_carries_no_scope_values():
    rule = _rule(rule_id="S-009", scope_kind=CatalogRule.ScopeKind.UNIVERSAL, scope_values=[])
    assert rule.scope_values == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/documents/test_catalog_rules.py -v`
Expected: FAIL — `ImportError: cannot import name 'CatalogRule'`

- [ ] **Step 3: Add the model**

Add to `apps/funding/models.py`, immediately after the `Program` class (it is shared catalog data and belongs with its neighbours):

```python
class CatalogRule(models.Model):
    """One researched CV rule, as data the render path can enforce.

    Shared across every tenant and never tenant-editable: a funder's
    requirement is the same fact for every agency, and one agency editing it
    would silently change another agency's output. Per-tenant judgement lives
    in ConstraintOverride, which is a TenantScopedModel.

    `key` is deliberately a plain CharField rather than a choices field: the
    authoritative list is _CONSTRAINT_KEYS in apps/documents/constraints.py,
    and importing it here would invert the dependency direction
    (apps.documents.render already imports this module). It is validated where
    it is written (the seed command) and where it is read
    (ConstraintRule.model_validate in resolve_rules), so an unknown key cannot
    reach a render.
    """

    class ScopeKind(models.TextChoices):
        UNIVERSAL = "UNIVERSAL"
        TRACK = "TRACK"
        COUNTRY = "COUNTRY"
        FUNDER = "FUNDER"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: NOT unique on its own. One researched rule can produce more than one
    #: enforceable constraint: R-032 ("US/Canada/UK/Australia: no photo, DOB,
    #: marital status, or gender") is both photo_allowed=false and
    #: date_of_birth_allowed=false, and R-033 is both again. Uniqueness is on
    #: (rule_id, key). Note the consequence for ConstraintOverride, which is
    #: keyed on rule_id alone: accepting R-032 accepts both of its keys at
    #: once, which is the right behaviour for one rule a student was shown.
    rule_id = models.CharField(max_length=20)
    scope_kind = models.CharField(max_length=20, choices=ScopeKind.choices)
    #: A list, not a scalar: R-032's scope is US/CA/UK/AU -- four countries in
    #: one rule. Country values are ISO 3166-1 alpha-2, so the CSV's "UK" is
    #: stored as "GB" to match Program.country_code.
    scope_values = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    key = models.CharField(max_length=40)
    value = models.JSONField()
    enforcement = models.CharField(max_length=20)
    rule_text = models.TextField()
    source_url = models.URLField(max_length=2048, blank=True)
    #: Free text as printed on the funder's page, never a parsed date -- the
    #: CSV's own values are prose ("evergreen", "reverify", "2026/2027",
    #: "cycle label unconfirmed"). Same decision, and same reason, as
    #: Program.cv_format_verified_for_cycle. Expiry never blocks a render: a
    #: page not re-read is not evidence the rule changed, and a rule that
    #: switched itself off on a date would leave a student with no CV at their
    #: deadline.
    verified_for_cycle = models.CharField(max_length=200, blank=True)
    confidence = models.CharField(max_length=10)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("rule_id", "key"), name="catalog_rule_id_key_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(scope_kind__in=ScopeKind.values),
                name="catalog_rule_scope_kind_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope_kind="UNIVERSAL", scope_values__len=0)
                    | ~models.Q(scope_kind="UNIVERSAL") & ~models.Q(scope_values__len=0)
                ),
                name="catalog_rule_scope_values_match_kind",
            ),
        ]
```

`ArrayField` is already imported in this module for `Program.teaching_languages`; confirm the import exists before adding.

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations funding --name catalog_rule`
Expected: creates `apps/funding/migrations/0016_catalog_rule.py`

- [ ] **Step 5: Add the RLS policy to that migration**

Every shared catalog table carries a SELECT-only policy (see `apps/funding/migrations/0004_phase1_catalog.py`). Without this, `CatalogRule` would be the one catalog table the runtime role could write. Append to the generated migration's `operations`:

```python
        migrations.RunSQL(
            sql="""
            ALTER TABLE public.funding_catalogrule ENABLE ROW LEVEL SECURITY;
            CREATE POLICY shared_catalog_select ON public.funding_catalogrule
                FOR SELECT USING (true);
            """,
            reverse_sql="""
            DROP POLICY IF EXISTS shared_catalog_select ON public.funding_catalogrule;
            ALTER TABLE public.funding_catalogrule DISABLE ROW LEVEL SECURITY;
            """,
        ),
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/documents/test_catalog_rules.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Verify no migration drift**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected"

- [ ] **Step 8: Commit**

```bash
git add apps/funding/models.py apps/funding/migrations/0016_catalog_rule.py tests/documents/test_catalog_rules.py
uv run git -C "$(git rev-parse --show-toplevel)" commit -m "feat(funding): add the shared CatalogRule table

Shared catalog, SELECT-only RLS like every other catalog table: a funder's
requirement is the same fact for every tenant, and per-tenant judgement
already has a home in ConstraintOverride."
```

---

### Task 2: `_check_required_fields`

**Files:**
- Modify: `apps/documents/render.py`
- Test: `tests/documents/test_render.py`

**Interfaces:**
- Consumes: `ConstraintRule` from `apps/documents/constraints.py`
- Produces: `_check_required_fields(rule, content, artifact) -> str | None`, registered in `_CHECKERS` under `"required_fields"`

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/test_render.py`:

```python
def _required_fields_rule(fields, enforcement=Enforcement.BINDING):
    return ConstraintRule(
        rule_id="R-079",
        key="required_fields",
        value=list(fields),
        enforcement=enforcement,
        rule_text="SISGP mandates Sex, Date of birth and Citizenship.",
    )


def test_required_fields_pass_when_every_named_field_is_present():
    content = _content()
    personal = content.personal_information.model_copy(
        update={"sex": "F", "citizenship": "AZ", "date_of_birth": date(2000, 1, 1)}
    )
    content = content.model_copy(update={"personal_information": personal})
    artifact, violations = render_cv_with_warnings(
        content,
        variant="STANDARD",
        constraints=(_required_fields_rule(["sex", "citizenship", "date_of_birth"]),),
    )
    assert violations == ()


def test_required_fields_report_the_missing_ones_by_name():
    with pytest.raises(PreflightBlocked) as excinfo:
        render_cv(
            _content(),
            variant="STANDARD",
            constraints=(_required_fields_rule(["sex", "citizenship"]),),
        )
    assert "sex" in str(excinfo.value)
    assert "citizenship" in str(excinfo.value)


def test_required_fields_treats_a_blank_string_as_missing():
    content = _content()
    personal = content.personal_information.model_copy(update={"sex": "  "})
    content = content.model_copy(update={"personal_information": personal})
    _artifact, violations = render_cv_with_warnings(
        content,
        variant="STANDARD",
        constraints=(_required_fields_rule(["sex"], Enforcement.ADVISORY_STYLE),),
    )
    assert len(violations) == 1


def test_a_malformed_required_fields_value_is_reported_not_raised():
    rule = ConstraintRule(
        rule_id="R-999",
        key="required_fields",
        value=42,
        enforcement=Enforcement.ADVISORY_STYLE,
        rule_text="malformed",
    )
    _artifact, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(rule,)
    )
    assert len(violations) == 1
    assert "could not evaluate" in violations[0].detail
```

`date` is already imported in this module; `Enforcement` and `render_cv_with_warnings` are already imported. Confirm before running.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_render.py -k required_fields -v`
Expected: FAIL — with no checker registered, a BINDING rule fails closed with "no pre-flight check for 'required_fields'", and the ADVISORY cases report the wrong detail.

- [ ] **Step 3: Implement the checker**

Add to `apps/documents/render.py`, beside the other checkers:

```python
def _check_required_fields(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """Named PersonalInformation fields must be present and non-empty.

    Serves R-079 (SISGP mandates Sex, Date of birth and Citizenship as fixed
    template fields). Without this checker the rule could not be seeded at all:
    a BINDING rule whose key has no checker fails closed, which would make
    every SISGP CV unrenderable.
    """
    missing = [
        field
        for field in cast(list[str], rule.value)
        if not str(getattr(content.personal_information, field, "") or "").strip()
    ]
    return f"missing required fields: {', '.join(missing)}" if missing else None
```

Register it in `_CHECKERS`:

```python
    "required_fields": _check_required_fields,
```

A non-list `rule.value` raises `TypeError` inside the loop, which the existing violation loop already catches and reports as "could not evaluate rule" — which is why the malformed test asserts a violation rather than an exception.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_render.py -k required_fields -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Add to the content-only key set**

`required_fields` is decidable from content alone, so add it to `_CONTENT_ONLY_KEYS` in `apps/documents/render.py`. This stops a EUROPASS_API render sending a student's PII to europa.eu for a CV a BINDING rule already blocks.

- [ ] **Step 6: Run the full documents suite**

Run: `uv run pytest tests/documents/ -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add apps/documents/render.py tests/documents/test_render.py
uv run git -C "$(git rev-parse --show-toplevel)" commit -m "feat(documents): check required_fields

R-079 (SISGP) could not be seeded without it: a BINDING rule whose key has no
checker fails closed, so seeding it would have made every SISGP CV
unrenderable."
```

---

### Task 3: `_check_prohibited_content`

**Precondition: PR #19 must be merged.** Without it `PersonalInformation.links` and `PublicationEntry.doi` do not exist and this checker has nothing to detect.

**Files:**
- Modify: `apps/documents/render.py`
- Test: `tests/documents/test_render.py`

**Interfaces:**
- Consumes: `PersonalInformation.links` (PR #19), `PublicationEntry.doi` (PR #19)
- Produces: `_check_prohibited_content(rule, content, artifact) -> str | None`, registered in `_CHECKERS` under `"prohibited_content"`

- [ ] **Step 1: Write the failing test**

```python
def _prohibited_rule(tokens):
    return ConstraintRule(
        rule_id="R-017",
        key="prohibited_content",
        value=list(tokens),
        enforcement=Enforcement.ADVISORY_HIGH_RISK,
        rule_text="Fulbright: no hyperlinks or off-site references in the CV.",
    )


def test_prohibited_hyperlinks_pass_for_a_cv_with_none():
    _artifact, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(_prohibited_rule(["hyperlinks"]),)
    )
    assert violations == ()


def test_prohibited_hyperlinks_catch_a_contact_link():
    content = _content()
    personal = content.personal_information.model_copy(
        update={"github_url": "https://github.com/jane"}
    )
    content = content.model_copy(update={"personal_information": personal})
    _artifact, violations = render_cv_with_warnings(
        content, variant="STANDARD", constraints=(_prohibited_rule(["hyperlinks"]),)
    )
    assert len(violations) == 1
    assert "hyperlinks" in violations[0].detail


def test_prohibited_hyperlinks_catch_a_publication_doi():
    content = CVContent.model_validate(
        {
            **_content().model_dump(mode="json"),
            "publications": (
                {
                    "authors": ["Doe, J."],
                    "self_author_index": 0,
                    "title": "A Study",
                    "doi": "10.1000/study",
                },
            ),
        }
    )
    _artifact, violations = render_cv_with_warnings(
        content, variant="STANDARD", constraints=(_prohibited_rule(["hyperlinks"]),)
    )
    assert len(violations) == 1


def test_an_unknown_prohibited_token_is_reported_not_silently_ignored():
    _artifact, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(_prohibited_rule(["photographs"]),)
    )
    assert len(violations) == 1
    assert "photographs" in violations[0].detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_render.py -k prohibited -v`
Expected: FAIL — no checker registered

- [ ] **Step 3: Implement the checker**

```python
def _check_prohibited_content(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """Content classes a funder forbids.

    One token today: "hyperlinks", for R-017 (Fulbright). An unrecognised
    token is reported rather than ignored -- a prohibition we do not
    understand is not a prohibition we have satisfied.
    """
    found: list[str] = []
    for token in cast(list[str], rule.value):
        if token != "hyperlinks":
            return f"unrecognised prohibited-content token {token!r}"
        if content.personal_information.links or any(
            entry.doi for entry in content.publications
        ):
            found.append(token)
    return f"content includes prohibited {', '.join(found)}" if found else None
```

Register in `_CHECKERS` as `"prohibited_content"`, and add it to `_CONTENT_ONLY_KEYS`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_render.py -k prohibited -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/documents/render.py tests/documents/test_render.py
uv run git -C "$(git rev-parse --show-toplevel)" commit -m "feat(documents): check prohibited_content

Serves R-017 (Fulbright: no hyperlinks). An unrecognised token is reported,
not ignored: a prohibition we do not understand is not one we have satisfied."
```

---

### Task 4: `_check_language` accepts a set of languages

**Files:**
- Modify: `apps/documents/render.py`
- Test: `tests/documents/test_render.py`

**Interfaces:**
- Produces: `_check_language` unchanged in signature; `rule.value` may now be `str` or `list[str]`

- [ ] **Step 1: Write the failing test**

```python
def _language_rule(value):
    return ConstraintRule(
        rule_id="R-072",
        key="language",
        value=value,
        enforcement=Enforcement.BINDING,
        rule_text="Eiffel: CV in French or English.",
    )


def test_a_single_language_rule_still_works_exactly_as_before():
    _artifact, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(_language_rule("en"),)
    )
    assert violations == ()


def test_a_language_set_accepts_any_member():
    _artifact, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(_language_rule(["fr", "en"]),)
    )
    assert violations == ()


def test_a_language_set_rejects_a_non_member():
    _artifact, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(_language_rule(["fr", "de"]),)
    )
    assert len(violations) == 1
```

`_content()` builds `document_language="en"`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_render.py -k language -v`
Expected: the set tests FAIL — `str(["fr", "en"])` never equals `"en"`

- [ ] **Step 3: Widen the checker**

Replace the body of `_check_language`:

```python
def _check_language(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """R-072 (Eiffel) allows French *or* English, so a rule may name a set.
    A bare string keeps its exact previous meaning."""
    allowed = rule.value if isinstance(rule.value, list) else [rule.value]
    if content.document_language in [str(item) for item in allowed]:
        return None
    return f"document language {content.document_language!r} is not {rule.value!r}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_render.py -k language -v`
Expected: PASS, including the pre-existing single-value language tests

- [ ] **Step 5: Commit**

```bash
git add apps/documents/render.py tests/documents/test_render.py
uv run git -C "$(git rev-parse --show-toplevel)" commit -m "feat(documents): let a language rule name a set

R-072 (Eiffel) allows French or English. A bare string is unchanged."
```

---

### Task 5: `FundingOpportunity.cv_format_requirement`

**Files:**
- Modify: `apps/funding/models.py`, `apps/documents/render.py`
- Create: migration (extend Task 1's if unmigrated, else a new one)
- Test: `tests/documents/test_render.py`

**Interfaces:**
- Produces: `FundingOpportunity.cv_format_requirement: str`; `select_render_variant(program, opportunity=None) -> str`

- [ ] **Step 1: Write the failing test**

```python
def test_a_funders_format_requirement_beats_the_programmes():
    class _Program:
        cv_format_requirement = "any"

    class _Opportunity:
        cv_format_requirement = "funder_template"

    assert select_render_variant(_Program(), _Opportunity()) == "FUNDER_TEMPLATE"


def test_the_programme_decides_when_the_funder_states_nothing():
    class _Program:
        cv_format_requirement = "europass_required"

    class _Opportunity:
        cv_format_requirement = ""

    assert select_render_variant(_Program(), _Opportunity()) == "EUROPASS_API"


def test_no_programme_and_no_funder_is_still_standard():
    assert select_render_variant(None, None) == "STANDARD"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_render.py -k format_requirement -v`
Expected: FAIL — `select_render_variant() takes 1 positional argument`

- [ ] **Step 3: Add the column**

In `apps/funding/models.py`, on `FundingOpportunity`:

```python
    #: ~19 of the researched format rules belong to funders, not programmes
    #: (Rhodes and SISGP mandate their own templates; AMIR, GLOBED, MathMods
    #: and WE-TEAM require Europass; Stipendium Hungaricum and NAWA take no CV
    #: at all). Blank means the funder states nothing and the programme decides.
    cv_format_requirement = models.CharField(
        max_length=30, choices=Program.CVFormatRequirement.choices, blank=True, default=""
    )
```

- [ ] **Step 4: Update `select_render_variant`**

```python
def select_render_variant(
    program: Program | None, opportunity: "FundingOpportunity | None" = None
) -> str:
    """Map a programme's format requirement onto a render variant.

    A funder's requirement wins over the programme's: a Rhodes applicant fills
    the Rhodes template whatever the university would otherwise accept. Blank
    means the funder states nothing, not that it permits anything.

    Falls back to STANDARD rather than raising: an unknown requirement value is
    a data problem, and a KeyError here would take rendering down for every
    student at that programme.
    """
    requirement = getattr(opportunity, "cv_format_requirement", "") or getattr(
        program, "cv_format_requirement", ""
    )
    return _REQUIREMENT_TO_VARIANT.get(requirement, "STANDARD")
```

Import `FundingOpportunity` alongside the existing `Program` import.

- [ ] **Step 5: Generate and apply the migration**

Run: `uv run python manage.py makemigrations funding --name funder_cv_format_requirement`

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/documents/test_render.py -q && uv run python manage.py makemigrations --check --dry-run`
Expected: PASS, "No changes detected"

- [ ] **Step 7: Commit**

```bash
git add apps/funding/models.py apps/funding/migrations/ apps/documents/render.py tests/documents/test_render.py
uv run git -C "$(git rev-parse --show-toplevel)" commit -m "feat(funding): give a funder its own CV format requirement

A Rhodes applicant fills the Rhodes template whatever the university accepts;
the column only existed on Program, so that could not be expressed."
```

---

### Task 6: `DocumentDraft.funding_opportunity`

**Files:**
- Modify: `apps/documents/models.py`
- Create: `apps/documents/migrations/0013_draft_funding_opportunity.py`
- Test: `tests/documents/test_document_draft.py`

**Interfaces:**
- Produces: `DocumentDraft.funding_opportunity: FundingOpportunity | None`

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/test_document_draft.py`:

```python
def test_a_draft_records_which_scholarship_it_is_for(agency_a, django_user_model):
    """Empty is meaningful: it means self-funded, and the resolver then has one
    fewer scope layer rather than no rules at all."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "d-funder")
        draft = DocumentDraft.objects.create(
            tenant=agency_a,
            student=student,
            kind=DocumentDraft.Kind.CV,
            version=1,
            content=_content().model_dump(mode="json"),
        )
        assert draft.funding_opportunity is None
```

Match the fixture and helper names already used in that file.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/documents/test_document_draft.py -k scholarship -v`
Expected: FAIL — `AttributeError: 'DocumentDraft' object has no attribute 'funding_opportunity'`

- [ ] **Step 3: Add the field**

In `apps/documents/models.py`, immediately after `programme`:

```python
    # Same shape and same reason as `programme` above: FundingOpportunity is a
    # shared catalog model, so this FK has no composite tenant partner.
    # Nullable, and null is meaningful -- it means self-funded, a direct
    # application, and the resolver simply drops the funder scope. Resolving a
    # funder from the programme instead was rejected: a programme linked to
    # five scholarships would inherit all five funders' rules at once.
    funding_opportunity = models.ForeignKey(
        "funding.FundingOpportunity",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations documents --name draft_funding_opportunity`

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/documents/ -q && uv run python manage.py makemigrations --check --dry-run`
Expected: PASS, "No changes detected"

- [ ] **Step 6: Commit**

```bash
git add apps/documents/models.py apps/documents/migrations/ tests/documents/test_document_draft.py
uv run git -C "$(git rev-parse --show-toplevel)" commit -m "feat(documents): let a draft say which scholarship it is for

Nullable, and null means self-funded: the resolver drops the funder scope and
still applies universal, country and track rules."
```

---

### Task 7: `resolve_rules`

**Files:**
- Modify: `apps/documents/constraints.py`
- Test: `tests/documents/test_catalog_rules.py`

**Interfaces:**
- Consumes: `CatalogRule` (Task 1), `rules_from_program` (existing)
- Produces: `resolve_rules(program, opportunity, *, content) -> tuple[ConstraintRule, ...]`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/documents/test_catalog_rules.py
from apps.documents.constraints import resolve_rules
from apps.funding.models import FundingOpportunity, Institution, Program


def _programme(country_code="GB", constraints=None):
    institution = Institution.objects.create(
        canonical_key=f"inst:{country_code}",
        name="Test University",
        country_code=country_code,
        official_website="https://university.example.test",
    )
    return Program.objects.create(
        institution=institution,
        canonical_key=f"prog:{country_code}",
        name="MSc Test",
        campus_name="Main",
        city="Town",
        country_code=country_code,
        location_key=f"{country_code.lower()}:town",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=12,
        cv_constraints=constraints or [],
    )


def _opportunity(key="sisgp"):
    return FundingOpportunity.objects.create(
        canonical_key=key, name=key.upper(), family="GOVERNMENT_SCHOLARSHIP",
        scope_type="COUNTRY", country_code="SE",
    )


def _taught_content():
    from tests.documents.test_render import _content
    return _content()


def test_a_universal_rule_applies_with_no_programme_and_no_funder():
    _rule(rule_id="S-009", scope_kind=CatalogRule.ScopeKind.UNIVERSAL,
          scope_values=[], key="max_pages", value=2)
    resolved = resolve_rules(None, None, content=_taught_content())
    assert [rule.rule_id for rule in resolved] == ["S-009"]


def test_a_country_rule_matches_by_membership_not_equality():
    _rule(rule_id="R-032", scope_kind=CatalogRule.ScopeKind.COUNTRY,
          scope_values=["US", "CA", "GB", "AU"], key="photo_allowed", value=False)
    assert [r.rule_id for r in resolve_rules(_programme("GB"), None, content=_taught_content())] == ["R-032"]
    assert resolve_rules(_programme("DE"), None, content=_taught_content()) == ()


def test_a_funder_rule_only_applies_when_that_funder_is_named():
    _rule(rule_id="R-078", scope_kind=CatalogRule.ScopeKind.FUNDER,
          scope_values=["sisgp"], key="max_entries_per_section", value={"experience": 3})
    programme = _programme("SE")
    assert resolve_rules(programme, None, content=_taught_content()) == ()
    resolved = resolve_rules(programme, _opportunity("sisgp"), content=_taught_content())
    assert [rule.rule_id for rule in resolved] == ["R-078"]


def test_the_funder_wins_over_the_country_on_the_same_key():
    """R-079 (SISGP mandates date of birth) over R-032 (US/CA/UK/AU forbid it).
    The research states this outcome directly: personal-data inclusion is a
    per-destination render decision, never a global content decision."""
    _rule(rule_id="R-032", scope_kind=CatalogRule.ScopeKind.COUNTRY,
          scope_values=["GB"], key="date_of_birth_allowed", value=False)
    _rule(rule_id="R-079", scope_kind=CatalogRule.ScopeKind.FUNDER,
          scope_values=["sisgp"], key="date_of_birth_allowed", value=True)
    resolved = resolve_rules(_programme("GB"), _opportunity("sisgp"), content=_taught_content())
    assert [rule.rule_id for rule in resolved] == ["R-079"]


def test_specificity_wins_even_when_it_is_looser():
    """DAAD allows 3 pages where the taught default is 2. The funder's own
    published rule is the operative one, not the tightest one available."""
    _rule(rule_id="R-023", scope_kind=CatalogRule.ScopeKind.TRACK,
          scope_values=["taught"], key="max_pages", value=2)
    _rule(rule_id="R-012", scope_kind=CatalogRule.ScopeKind.FUNDER,
          scope_values=["daad"], key="max_pages", value=3)
    resolved = resolve_rules(_programme("DE"), _opportunity("daad"), content=_taught_content())
    assert [(r.rule_id, r.value) for r in resolved] == [("R-012", 3)]


def test_programme_constraints_win_over_every_catalog_scope():
    _rule(rule_id="R-012", scope_kind=CatalogRule.ScopeKind.FUNDER,
          scope_values=["daad"], key="max_pages", value=3)
    programme = _programme("DE", constraints=[{
        "rule_id": "P-001", "key": "max_pages", "value": 1,
        "enforcement": "BINDING", "rule_text": "This programme caps at 1 page.",
    }])
    resolved = resolve_rules(programme, _opportunity("daad"), content=_taught_content())
    assert [(r.rule_id, r.value) for r in resolved] == [("P-001", 1)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_catalog_rules.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_rules'`

- [ ] **Step 3: Implement the resolver**

Add to `apps/documents/constraints.py`:

```python
#: Least specific first. A later scope's rule replaces an earlier one for the
#: same key. This is specificity, not strictness: DAAD's 3 pages beat the
#: taught default of 2, because a funder's own published rule is the operative
#: one, not the tightest one available.
_SCOPE_ORDER = ("UNIVERSAL", "TRACK", "COUNTRY", "FUNDER")


def _scope_matches(rule: Any, *, program: Any, opportunity: Any, track: str) -> bool:
    if rule.scope_kind == "UNIVERSAL":
        return True
    if rule.scope_kind == "TRACK":
        return track in rule.scope_values
    if rule.scope_kind == "COUNTRY":
        return program is not None and program.country_code in rule.scope_values
    if rule.scope_kind == "FUNDER":
        return opportunity is not None and opportunity.canonical_key in rule.scope_values
    return False


def resolve_rules(program: Any, opportunity: Any, *, content: Any) -> tuple[ConstraintRule, ...]:
    """The rules that apply to one programme-and-scholarship pair.

    Rules accumulate across scopes; when two set the same key, the more
    specific scope wins. `opportunity=None` means a self-funded, direct
    application -- the funder layer is simply absent, and universal, country
    and track rules still apply.

    Track is derived the way render.py::_section_order already derives it, so
    one CV cannot be research-track for ordering and taught-track for rules.
    """
    from apps.funding.models import CatalogRule

    track = "research" if content.research else "taught"
    chosen: dict[str, tuple[int, ConstraintRule]] = {}
    # order_by is load-bearing, not cosmetic: the merge below keeps the last
    # rule seen at a given rank, so two same-scope rules setting the same key
    # would otherwise resolve by Postgres row order -- a render difference
    # nothing in the code or the catalog would explain.
    for row in CatalogRule.objects.order_by("rule_id"):
        if not _scope_matches(row, program=program, opportunity=opportunity, track=track):
            continue
        rank = _SCOPE_ORDER.index(row.scope_kind)
        existing = chosen.get(row.key)
        if existing is None or rank >= existing[0]:
            chosen[row.key] = (rank, ConstraintRule.model_validate({
                "rule_id": row.rule_id,
                "key": row.key,
                "value": row.value,
                "enforcement": row.enforcement,
                "rule_text": row.rule_text,
                "source_url": row.source_url,
            }))
    for rule in rules_from_program(program) if program is not None else ():
        chosen[rule.key] = (len(_SCOPE_ORDER), rule)
    return tuple(rule for _rank, rule in chosen.values())
```

The `CatalogRule` import is function-local: `apps.funding.models` is a heavier import than `constraints.py` otherwise needs, and keeping it here matches the lazy-import pattern `render.py::_funder_dispatch` already uses.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_catalog_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/documents/constraints.py tests/documents/test_catalog_rules.py
uv run git -C "$(git rev-parse --show-toplevel)" commit -m "feat(documents): resolve catalog rules by scope specificity

Rules accumulate; the more specific scope wins on a shared key. Specificity,
not strictness -- DAAD's 3 pages beat the taught default of 2."
```

---

### Task 8: Curated seed module and command

**Files:**
- Create: `apps/documents/catalog_seed.py`, `apps/documents/management/commands/seed_cv_rules.py`
- Test: `tests/documents/test_catalog_rules.py`

**Interfaces:**
- Consumes: `CatalogRule` (Task 1), `_CONSTRAINT_KEYS` (existing)
- Produces: `SEED_RULES: tuple[dict[str, object], ...]`; `seed_cv_rules() -> tuple[int, int, int]` returning (created, updated, deleted)

- [ ] **Step 1: Write the failing test**

```python
def _every_seed_funder():
    """The seed refuses to run against funders that do not exist, so tests that
    exercise it must load them first -- the same precondition a deployment has."""
    from apps.documents.catalog_seed import SEED_FUNDERS
    for canonical_key, name, _requirement in SEED_FUNDERS:
        FundingOpportunity.objects.create(
            canonical_key=canonical_key, name=name,
            family="GOVERNMENT_SCHOLARSHIP", scope_type="GLOBAL",
        )


def test_seeding_twice_changes_nothing_the_second_time():
    from apps.documents.catalog_seed import seed_cv_rules
    _every_seed_funder()
    created, updated, deleted = seed_cv_rules()
    assert created > 0
    again = seed_cv_rules()
    assert again == (0, 0, 0)


def test_seeding_removes_a_rule_no_longer_in_the_module():
    from apps.documents.catalog_seed import seed_cv_rules
    seed_cv_rules()
    _rule(rule_id="R-999", key="max_pages", value=9)
    _created, _updated, deleted = seed_cv_rules()
    assert deleted == 1
    assert not CatalogRule.objects.filter(rule_id="R-999").exists()


def test_every_seeded_key_is_a_key_the_engine_can_check():
    from typing import get_args
    from apps.documents.catalog_seed import SEED_RULES
    from apps.documents.constraints import _CONSTRAINT_KEYS
    from apps.documents.render import _CHECKERS

    allowed = set(get_args(_CONSTRAINT_KEYS))
    for row in SEED_RULES:
        assert row["key"] in allowed, row["rule_id"]
        if row["enforcement"] == "BINDING":
            assert row["key"] in _CHECKERS, (
                f"{row['rule_id']} is BINDING with no checker -- it would block "
                "every render for that funder"
            )


def test_seeding_annotates_an_existing_funder_and_never_invents_one():
    """The seed sets cv_format_requirement on funders the discovery pipeline
    loaded. It does not create them: FundingOpportunity needs `family`, and
    this research establishes none -- Rhodes is a private trust, so every
    value in that taxonomy would be a false claim."""
    from apps.documents.catalog_seed import seed_cv_rules
    _opportunity("rhodes")
    seed_cv_rules()
    assert FundingOpportunity.objects.get(
        canonical_key="rhodes"
    ).cv_format_requirement == "funder_template"


def test_seeding_refuses_when_a_rule_names_a_funder_that_does_not_exist():
    from apps.documents.catalog_seed import seed_cv_rules
    with pytest.raises(ValueError, match="not in the catalog"):
        seed_cv_rules()


def test_two_rules_of_the_same_scope_and_key_are_a_data_error():
    from apps.documents.catalog_seed import _assert_no_same_scope_conflict
    rows = (
        {"rule_id": "A", "scope_kind": "COUNTRY", "scope_values": ["DE"], "key": "max_pages"},
        {"rule_id": "B", "scope_kind": "COUNTRY", "scope_values": ["DE"], "key": "max_pages"},
    )
    with pytest.raises(ValueError, match="max_pages"):
        _assert_no_same_scope_conflict(rows)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_catalog_rules.py -k seed -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Write the seed module**

Create `apps/documents/catalog_seed.py`.

**These are the exact rows to seed.** The judgement fields — scope, key, value, enforcement — are given here because they cannot be derived from the CSV; they are the curation. The four provenance fields (`rule_text`, `source_url`, `verified_for_cycle`, `confidence`) are copied verbatim from the `docs/research/cv-rules.csv` row with that `ID`, which is mechanical and unambiguous.

| rule_id | scope_kind | scope_values | key | value | enforcement |
| --- | --- | --- | --- | --- | --- |
| R-007 | FUNDER | `["emjm-imaging"]` | `max_pages` | `2` | BINDING |
| R-008 | FUNDER | `["mundus-journalism"]` | `max_pages` | `2` | BINDING |
| R-012 | FUNDER | `["daad-study-scholarships"]` | `max_pages` | `3` | BINDING |
| R-057 | FUNDER | `["i-mesc"]` | `max_pages` | `2` | BINDING |
| R-072 | FUNDER | `["eiffel-excellence"]` | `max_pages` | `2` | BINDING |
| R-080 | FUNDER | `["rhodes"]` | `max_pages` | `2` | BINDING |
| R-023 | TRACK | `["taught"]` | `max_pages` | `2` | ADVISORY_STYLE |
| R-024 | TRACK | `["research"]` | `max_pages` | `3` | ADVISORY_STYLE |
| R-048 | FUNDER | `["mundus-journalism"]` | `max_bytes` | `10485760` | BINDING |
| R-060 | FUNDER | `["europubhealth-plus"]` | `max_bytes` | `2097152` | BINDING |
| R-015 | FUNDER | `["chevening"]` | `max_entries_per_section` | `{"education": 15, "experience": 15}` | BINDING |
| R-078 | FUNDER | `["sisgp"]` | `max_entries_per_section` | `{"experience": 3}` | BINDING |
| R-032 | COUNTRY | `["US", "CA", "GB", "AU"]` | `photo_allowed` | `false` | ADVISORY_HIGH_RISK |
| R-032 | COUNTRY | `["US", "CA", "GB", "AU"]` | `date_of_birth_allowed` | `false` | ADVISORY_HIGH_RISK |
| R-030 | COUNTRY | `["DE"]` | `photo_allowed` | `true` | ADVISORY_STYLE |
| R-031 | COUNTRY | `["DE"]` | `signature_required` | `true` | ADVISORY_HIGH_RISK |
| R-010 | FUNDER | `["daad-epos"]` | `date_of_issue_required` | `true` | BINDING |
| R-072 | FUNDER | `["eiffel-excellence"]` | `language` | `["fr", "en"]` | BINDING |
| R-079 | FUNDER | `["sisgp"]` | `required_fields` | `["sex", "date_of_birth", "citizenship"]` | BINDING |
| R-017 | FUNDER | `["fulbright"]` | `prohibited_content` | `["hyperlinks"]` | ADVISORY_HIGH_RISK |

Four of these carry a judgement that is not a transcription, and each is recorded in the spec:

- **R-032 and R-072 appear twice** — one researched rule, two enforceable keys. This is why uniqueness is `(rule_id, key)`.
- **R-031 is `ADVISORY_HIGH_RISK`, not BINDING** — the CSV grades it "advisory (custom); no funder-binding instance found". `signature_required` has no checker by design (a wet signature is not visible from here), so a BINDING grade would block every German CV.
- **R-017 is `ADVISORY_HIGH_RISK`** — the CSV says "binding (Scholar) / advisory (Student)", and this platform's applicants are on the student track.
- **R-048 is scoped to Mundus Journalism** — its own scope is the bare word "funder"; 10 MB is the only limit it evidences.
- **R-033 and R-067 are deliberately absent.** R-033 states Europass photo/DOB are *optional*, which constrains nothing. R-067's 2 MB "default" is extrapolated from one funder's page, and seeding it universally would invent a limit nobody published.

```python
"""The enforceable subset of the researched CV rules.

Curated by hand, not parsed: the CSVs' enforcement column is prose in 18 of 93
rows ("binding (Scholar) / advisory (Student)"), their scope column is prose
too, and two thirds of the rules have no checkable key at all. Each row here
records one human judgement, reviewable against the CSV by rule_id.

A rule absent from this module is not enforced -- which is the property a
silently-partial CSV import would destroy.
"""

from __future__ import annotations

from typing import Any, get_args

from django.db import transaction

from .constraints import _CONSTRAINT_KEYS

#: Every funder a rule is scoped to, and the CV format that funder mandates.
#: canonical_key is FundingOpportunity's unique key, so these strings are the
#: same ones SEED_RULES scopes against. "" means the funder states no format.
SEED_FUNDERS: tuple[tuple[str, str, str], ...] = (
    ("rhodes", "Rhodes Scholarship", "funder_template"),
    ("sisgp", "Swedish Institute Scholarships for Global Professionals", "funder_template"),
    ("australia-awards", "Australia Awards", "funder_template"),
    ("daad-epos", "DAAD EPOS", "europass_required"),
    ("daad-study-scholarships", "DAAD Study Scholarships", ""),
    ("daad-prime", "DAAD PRIME", "europass_preferred"),
    ("amir", "AMIR EMJM", "europass_required"),
    ("membiomed", "MemBioMed EMJM", "europass_required"),
    ("steps", "STEPS EMJM", "europass_required"),
    ("globed", "GLOBED EMJM", "europass_required"),
    ("i-mesc", "i-MESC EMJM", "europass_required"),
    ("mathmods", "MathMods EMJM", "europass_required"),
    ("we-team", "WE-TEAM EMJM", "europass_required"),
    ("europubhealth-plus", "Europubhealth+", "europass_preferred"),
    ("emship", "EMSHIP EMJM", "europass_preferred"),
    ("emhrpp", "EMHRPP EMJM", "any"),
    ("comem", "CoMEM EMJM", "any"),
    ("turkiye-burslari", "Turkiye Burslari", "any"),
    ("stipendium-hungaricum", "Stipendium Hungaricum", "structured_fields_only"),
    ("nawa", "NAWA Banach", "structured_fields_only"),
    ("chevening", "Chevening", ""),
    ("fulbright", "Fulbright Foreign Student Program", ""),
    ("eiffel-excellence", "Eiffel Excellence", ""),
    ("emjm-imaging", "EMJM Imaging", "any"),
    ("mundus-journalism", "Mundus Journalism", ""),
)

SEED_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "R-080",
        "scope_kind": "FUNDER",
        "scope_values": ["rhodes"],
        "key": "max_pages",
        "value": 2,
        "enforcement": "BINDING",
        # rule_text / source_url / verified_for_cycle / confidence copied
        # verbatim from the cv-rules.csv row with ID R-080.
        "rule_text": (
            "Rhodes template constraints: 'your CV should not exceed 2 pages and no "
            "additional pages will be read by selection committees'"
        ),
        "source_url": "",
        "verified_for_cycle": "current template",
        "confidence": "high",
    },
    {
        "rule_id": "R-079",
        "scope_kind": "FUNDER",
        "scope_values": ["sisgp"],
        "key": "required_fields",
        "value": ["sex", "date_of_birth", "citizenship"],
        "enforcement": "BINDING",
        "rule_text": (
            "SISGP mandates Sex, Date of birth (YYYY-MM-DD) and Citizenship in PERSONAL "
            "INFORMATION, as fixed template fields."
        ),
        "source_url": "",
        "verified_for_cycle": "2026/2027",
        "confidence": "high",
    },
    # One entry per row of the table above, same shape. Copy the four
    # provenance fields from the CSV row of that ID -- do not paraphrase them.
)


def _assert_no_same_scope_conflict(rows: tuple[dict[str, Any], ...]) -> None:
    """Two rules of the same scope setting the same key is a data error.

    The resolver would have to pick one, and picking silently is how a
    funder's rule quietly stops applying.
    """
    seen: dict[tuple[str, str, str], str] = {}
    for row in rows:
        for value in row["scope_values"] or [""]:
            slot = (row["scope_kind"], value, row["key"])
            if slot in seen:
                raise ValueError(
                    f"{row['rule_id']} and {seen[slot]} both set {row['key']!r} "
                    f"for {row['scope_kind']} {value!r}"
                )
            seen[slot] = row["rule_id"]


@transaction.atomic
def seed_cv_rules() -> tuple[int, int, int]:
    """Load SEED_RULES into the catalog. Returns (created, updated, deleted)."""
    from apps.funding.models import CatalogRule, FundingOpportunity

    _assert_no_same_scope_conflict(SEED_RULES)
    # Set the format requirement on funders that already exist. This seed
    # deliberately does NOT create FundingOpportunity rows: that model requires
    # `family` and `scope_type`, and this research establishes neither. The
    # taxonomy does not even fit -- Rhodes is a private trust, so
    # GOVERNMENT_SCHOLARSHIP and MULTILATERAL are both false about it, and a
    # catalog row asserting one would be invented data in the one place this
    # system exists not to invent things. Funder rows come from the discovery
    # pipeline; this seed only annotates them.
    for canonical_key, _name, requirement in SEED_FUNDERS:
        if not requirement:
            continue
        FundingOpportunity.objects.filter(canonical_key=canonical_key).update(
            cv_format_requirement=requirement
        )
    named = {value for row in SEED_RULES for value in row["scope_values"]
             if row["scope_kind"] == "FUNDER"}
    missing = named - set(
        FundingOpportunity.objects.filter(canonical_key__in=named)
        .values_list("canonical_key", flat=True)
    )
    if missing:
        raise ValueError(
            f"rules scope to funders not in the catalog: {sorted(missing)} -- "
            "load them through the discovery pipeline before seeding rules"
        )
    allowed = set(get_args(_CONSTRAINT_KEYS))
    for row in SEED_RULES:
        if row["key"] not in allowed:
            raise ValueError(f"{row['rule_id']} uses unknown constraint key {row['key']!r}")

    created = updated = 0
    kept: list[Any] = []
    for row in SEED_RULES:
        # Keyed on (rule_id, key), NOT rule_id alone -- that is the table's
        # unique constraint, and the difference is not cosmetic. R-032 appears
        # twice in SEED_RULES (photo_allowed, date_of_birth_allowed) and R-072
        # twice (max_pages, language). Keyed on rule_id alone, each pair's
        # second row UPDATES the first instead of inserting: the catalog ends
        # with 18 rows where 20 are specified, photo_allowed and max_pages
        # silently gone, and the idempotency test still green.
        lookup = {"rule_id": row["rule_id"], "key": row["key"]}
        defaults = {k: v for k, v in row.items() if k not in lookup}
        existing = CatalogRule.objects.filter(**lookup).first()
        if existing is None:
            kept.append(CatalogRule.objects.create(**lookup, **defaults).pk)
            created += 1
            continue
        kept.append(existing.pk)
        if any(getattr(existing, field) != value for field, value in defaults.items()):
            # Check .update()'s row count, exactly as
            # format_resolution.py::_write_program does. Under the SELECT-only
            # shared_catalog_select policy an INSERT raises, but an UPDATE
            # simply matches no rows and returns 0 -- a write that looks fine
            # and silently did nothing. That is the one failure mode the
            # command's own zero-write guard cannot see, because a populated
            # table makes `_any_rules()` true.
            if CatalogRule.objects.filter(pk=existing.pk).update(**defaults) != 1:
                raise CatalogWriteBlocked(
                    "catalog write affected no rows -- run this under "
                    "DATABASE_ROLE=migration; the runtime role cannot update "
                    "funding_catalogrule"
                )
            updated += 1
    deleted, _ = CatalogRule.objects.exclude(pk__in=kept).delete()
    return created, updated, deleted
```

Counting only genuine changes is what makes a second run return `(0, 0, 0)`, which is
what the idempotency test asserts. The delete sweep is keyed on `(rule_id, key)` for the
same reason the upsert is: an `exclude(rule_id__in=...)` sweep would spare a stale row
whose `rule_id` is still seeded under a different `key`.

- [ ] **Step 4: Write the management command**

Create `apps/documents/management/commands/seed_cv_rules.py`:

```python
"""Load the curated CV rule catalog.

    DATABASE_ROLE=migration uv run python manage.py seed_cv_rules

funding_catalogrule carries a SELECT-only shared_catalog_select RLS policy, so
the ordinary runtime role matches no rows and writes nothing -- silently. Run
this as the migration or catalog_ingestion role, the same way
format_resolution.py::_write_program requires.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.documents.catalog_seed import seed_cv_rules


class Command(BaseCommand):
    help = "Load the curated CV rule catalog into funding_catalogrule."

    def handle(self, *args: object, **options: object) -> None:
        created, updated, deleted = seed_cv_rules()
        if created == updated == deleted == 0 and not _any_rules():
            raise CommandError(
                "seed wrote nothing and the catalog is empty -- the runtime role "
                "cannot write funding_catalogrule; re-run with DATABASE_ROLE=migration"
            )
        self.stdout.write(f"created={created} updated={updated} deleted={deleted}")
```

Add the `_any_rules()` helper (`CatalogRule.objects.exists()`) and import `CommandError`. The zero-write guard is the same failure `_write_program` exists to catch: an RLS-blocked write looks like success.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_catalog_rules.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/documents/catalog_seed.py apps/documents/management/commands/seed_cv_rules.py tests/documents/test_catalog_rules.py
uv run git -C "$(git rev-parse --show-toplevel)" commit -m "feat(documents): seed the curated CV rule catalog

Curated, not parsed: the CSVs' enforcement and scope columns are prose in a
fifth of the rows. A rule absent from the module is visibly unenforced, which
a partial import would have hidden."
```

---

### Task 9: Wire `render_draft`

**Files:**
- Modify: `apps/documents/render.py`
- Test: `tests/documents/test_catalog_rules.py` — **not** `test_render.py`: this test needs `_rule`, `_programme` and `_opportunity`, which are defined there, and importing test helpers across test modules is worse than putting the test beside them.

**Interfaces:**
- Consumes: `resolve_rules` (Task 7), `select_render_variant` (Task 5), `DocumentDraft.funding_opportunity` (Task 6)

- [ ] **Step 1: Write the failing test**

```python
def test_a_draft_renders_with_its_programmes_rules(agency_a, django_user_model):
    """render_draft resolved nothing before this: every caller had to pass
    constraints, and the one caller in the app passed none."""
    with tenant_scope(agency_a.id):
        programme = _programme("GB")
        _rule(rule_id="R-032", scope_kind=CatalogRule.ScopeKind.COUNTRY,
              scope_values=["GB"], key="max_pages", value=1,
              enforcement="BINDING")
        draft = _approved_draft(agency_a, django_user_model, programme=programme,
                                content=_long_content())
        with pytest.raises(PreflightBlocked):
            render_draft(draft=draft)


def test_a_draft_with_no_programme_renders_exactly_as_before(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, programme=None)
        assert render_draft(draft=draft).variant == "STANDARD"
```

Build `_approved_draft` and `_long_content` from the helpers already in `tests/documents/test_document_draft.py`; a draft must be APPROVED before `render_draft` accepts it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_catalog_rules.py -k draft_renders -v`
Expected: FAIL — no rules are resolved, so no violation and no `PreflightBlocked`

- [ ] **Step 3: Wire it**

In `render_draft`, resolve **above the Europass rate-limit guard**, not merely
before the `render_cv` call:

```python
    content = CVContent.model_validate(draft.content)
    if not constraints:
        constraints = resolve_rules(
            draft.programme, draft.funding_opportunity, content=content
        )
    variant = draft.render_variant or select_render_variant(
        draft.programme, draft.funding_opportunity
    )
```

Then change the guard's condition from `draft.render_variant == "EUROPASS_API"`
to `variant == "EUROPASS_API"`, and pass `content` and `variant` to `render_cv`.

**This ordering is the whole point of the step.** Before this task, a draft
reached the Europass API only via a stored `draft.render_variant`, so guarding
on the raw field was the same as guarding on the variant. After it, a blank
`render_variant` can resolve to `EUROPASS_API` from the programme or funder --
and a guard still reading the raw field would let every such draft through the
public EU service with no limit at all. See the `_EUROPASS_RENDER_LIMIT`
comment: "a release path that can be re-triggered is a way to hammer a public
EU service from our IP, which is how access gets withdrawn."

Keep the `constraints` and `funder_template_id` parameters: they remain the
test override, which is why the second test can still assert today's behaviour.

- [ ] **Step 3b: Pin the guard against the resolved variant**

```python
def test_a_resolved_europass_variant_is_still_rate_limited(agency_a, django_user_model):
    """The guard must read the resolved variant, not draft.render_variant.
    A draft that stores no variant but resolves to EUROPASS_API is exactly the
    case this task creates, and it is the case an unmoved guard misses."""
    with tenant_scope(agency_a.id):
        institution = Institution.objects.create(
            canonical_key="inst:europass", name="Test University", country_code="SE",
            official_website="https://university.example.test",
        )
        programme = Program.objects.create(
            institution=institution, canonical_key="prog:europass", name="MSc Test",
            campus_name="Main", city="Town", country_code="SE", location_key="se:town",
            degree_level="MASTER", teaching_languages=["English"], duration_months=12,
            cv_format_requirement=Program.CVFormatRequirement.EUROPASS_REQUIRED,
        )
        draft = _approved_draft(agency_a, django_user_model, programme=programme)
        assert draft.render_variant == ""
        for _ in range(_EUROPASS_RENDER_LIMIT):
            rate_limited(
                "europass-render", draft.student_id,
                limit=_EUROPASS_RENDER_LIMIT,
                window_seconds=_EUROPASS_RENDER_WINDOW_SECONDS,
            )
        with pytest.raises(RenderRateLimited):
            render_draft(draft=draft)
```

If `_approved_draft` leaves `render_variant` non-empty, pass `render_variant=""`
explicitly rather than weakening the assertion.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/documents/render.py tests/documents/test_catalog_rules.py
uv run git -C "$(git rev-parse --show-toplevel)" commit -m "feat(documents): resolve a draft's rules at render time

render_draft took constraints and the one caller in the app passed none, so no
researched rule had ever reached a rendered CV."
```

---

### Task 10: Pin the fail-closed guarantee

**Files:**
- Test: `tests/documents/test_render.py`

- [ ] **Step 1: Write the test**

```python
def test_a_binding_rule_with_no_checker_still_blocks():
    """The whole catalog leans on this. A rule we cannot verify must never
    pass as satisfied, and a future checker registry change must not loosen it
    quietly. signature_required is the deliberately-uncheckable key: a wet
    signature is not visible from here."""
    rule = ConstraintRule(
        rule_id="R-031",
        key="signature_required",
        value=True,
        enforcement=Enforcement.BINDING,
        rule_text="Germany: signature on the last page for formal CVs.",
    )
    with pytest.raises(PreflightBlocked) as excinfo:
        render_cv(_content(), variant="STANDARD", constraints=(rule,))
    assert "no pre-flight check" in str(excinfo.value)
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/documents/test_render.py -k no_checker -v`
Expected: PASS immediately — this pins existing behaviour rather than adding any.

- [ ] **Step 3: Run the full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
uv run pip-audit
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```
Expected: all green, test count above the recorded baseline.

- [ ] **Step 4: Commit**

```bash
git add tests/documents/test_render.py
uv run git -C "$(git rev-parse --show-toplevel)" commit -m "test(documents): pin the fail-closed guarantee

A BINDING rule whose key has no checker must keep blocking. The catalog leans
on this: it is what makes an unenforceable rule visibly unenforceable."
```

---

## After the plan

- `security-review` — a new shared table read on every render, a new FK, and two new checkers that read student content.
- `ponytail:ponytail-review` before the PR is merge-bound.
- The seed command needs `DATABASE_ROLE=migration` in whatever runs it in a deployed environment. Note it in the PR description; there is no deployment yet to wire it into.
