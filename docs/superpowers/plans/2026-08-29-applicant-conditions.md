# Applicant Conditions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Model the non-nationality applicant conditions that gate real scholarships — work experience, age cap, means test, values or affiliation, return service — so the engine stops offering students routes they cannot enter, and discloses bonded awards instead of hiding them.

**Architecture:** Three layers, in dependency order. The **catalog** gains two `BenefitRule.Kind`
values and a structured comparable beside the existing verbatim quote. The **extraction** schema
gains the condition kinds and the same comparable, and `claim_rows` emits them so they are not
extracted and thrown away. The **evaluation** layer gains condition facts on `CandidateFacts` and
honours them inside `benefit_applies()` — the shared function through which both the mandatory-funding
hard gate and the affordability buckets already run. A condition closes a *funding route*, not a
programme, which is why nothing here is written as a new top-level hard gate.

**Tech Stack:** Django 5.2 + PostgreSQL check constraints, Pydantic v2 (`extra="forbid"`, frozen),
pytest + pytest-django, `uv` for every command.

**Spec:** `docs/superpowers/specs/2026-08-27-risk-aware-portfolio-design.md` §4 ("The route to yes"),
specifically the **Applicant conditions** row of the attribute table and the two paragraphs beginning
"**Applicant conditions is a 2026-08-29 addition, and it is not an edge case.**" and "**Return
service belongs here too.**"

---

## Global Constraints

- **Test database must be isolated to this task:** every pytest invocation in this plan is prefixed
  `POSTGRES_DB=tehsil_conditions`. The shared `test_tehsil` database wedges across parallel sessions.
- **Commit through uv:** `uv run git commit`, never bare `git commit`. The Bandit pre-commit hook
  lives in the uv venv and is not on PATH; a bare commit fails with "`pre-commit` not found".
- **Never run `ruff format`** in this repo. The gate is lint-only; `ruff format` churns 26 unrelated
  files. Formatting checks are `uv run ruff check apps tests`.
- **Line length is 100** (`[tool.ruff]` in `pyproject.toml`), target version `py312`.
- **Pre-existing test failures: 25**, all `TemplateDoesNotExist` in badge/evidence/money tests. The
  `templates/` directory was deleted in commit `451791e` and never restored. These are **not yours**.
  Compare failures **by test name**, never by count — this plan adds tests, so counts move.
  Baseline on `4cebe85` was `400 passed, 25 failed`.
- **Every new model field is nullable**, and every new Pydantic field defaults to empty. Zero rows
  exist in the catalog today; a non-null column would be a migration that cannot be applied later
  once rows do exist.
- **Do not weaken the LLM security pattern** in `apps/research/extraction.py`: untrusted page content
  stays labelled as data, the schema stays `extra="forbid"`, `max_output_tokens` stays capped.

### Scope boundary you must not cross

Nothing in `apps/` constructs a `CandidateFacts` from Django models — verified by
`grep -rn "CandidateFacts(" apps/`, which returns only the class definition. The evaluation layer and
the catalog layer are **not connected yet**, and connecting them is a separate piece of work.

This plan therefore builds the **contract and the pure logic**. It does not make applicant conditions
live end-to-end, and no task here should attempt a DB→`CandidateFacts` resolver. Task 5 is the last
task; if you find yourself writing a query in `apps/funding/`, stop — you have left the plan.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `apps/funding/models.py` | Modify `BenefitRule` (~line 534) | Two new `Kind` values, `ConditionType`, three comparable fields, four check constraints |
| `apps/funding/migrations/0016_benefit_rule_applicant_conditions.py` | Create | Generated migration for the above |
| `apps/research/extraction.py` | Modify `EligibilityCriterionClaim` (~line 96) | Three new criterion kinds, optional structured comparable |
| `apps/research/catalog.py` | Modify `claim_rows` (~line 122) | Emit the comparable so it is not extracted and discarded |
| `apps/funding/evaluation.py` | Modify | `ApplicantConditionFact`, `ReturnServiceFact`, `benefit_applies`, `evaluate` |
| `apps/funding/pack.py` | Modify `rank_candidates` (~line 83) | Return-service disclosure |
| `tests/funding/conftest.py` | Modify | `make_applicant_condition`, `make_return_service` |
| `tests/funding/test_catalog_models.py` | Modify | Choices contract + constraint tests |
| `tests/research/test_extraction.py` | Modify | Criterion kinds and comparable round-trip |
| `tests/research/test_catalog_writer.py` | Modify | `claim_rows` emits the comparable |
| `tests/funding/test_hard_gates.py` | Modify | Route-closing behaviour, review routing |
| `tests/funding/test_ranking.py` | Modify | Return-service disclosure |

---

## Task 1: BenefitRule carries the condition, structured beside the quote

`rule_text` stays the verbatim published quote — it is the student-facing evidence and nothing here
replaces it. The comparable is a **second, machine-usable** representation of the same sentence.

The unit is a function of the condition, so there is no `comparable_unit` column:
`WORK_EXPERIENCE` → months, `AGE_CAP` → years, `MEANS_TEST` → money (needs `comparable_currency`),
`AFFILIATION` → no comparable at all, `RETURN_SERVICE` (a `Kind`, not a `ConditionType`)
→ months.

Return service is a separate `Kind` rather than a fifth `ConditionType` because it is **not a filter**.
It is a post-award obligation and a disclosure duty — the spec's "a bonded award is a materially
different product from an unbonded one and the student must be told which they are accepting."

**Files:**
- Modify: `apps/funding/models.py:534-620` (`BenefitRule`)
- Create: `apps/funding/migrations/0016_benefit_rule_applicant_conditions.py` (generated)
- Test: `tests/funding/test_catalog_models.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `BenefitRule.Kind.APPLICANT_CONDITION`, `BenefitRule.Kind.RETURN_SERVICE`,
  `BenefitRule.ConditionType` with members `WORK_EXPERIENCE`, `AGE_CAP`, `MEANS_TEST`,
  `AFFILIATION`; fields `condition_type: str | None`, `comparable_value: Decimal | None`,
  `comparable_currency: str | None`.

- [ ] **Step 1: Extend the choices contract test**

In `tests/funding/test_catalog_models.py`, inside `test_catalog_choice_contracts_are_exact`, replace
the `(catalog.BenefitRule, "kind")` entry and add a `condition_type` entry:

```python
        (catalog.BenefitRule, "kind"): {
            "ELIGIBILITY",
            "AMOUNT",
            "CAPACITY",
            "GEOGRAPHIC_SCOPE",
            "DEADLINE",
            "APPLICANT_CONDITION",
            "RETURN_SERVICE",
            "OTHER",
        },
        (catalog.BenefitRule, "condition_type"): {
            "WORK_EXPERIENCE",
            "AGE_CAP",
            "MEANS_TEST",
            "AFFILIATION",
        },
```

- [ ] **Step 2: Write the constraint tests**

Append to `tests/funding/test_catalog_models.py`:

```python
@pytest.mark.django_db
def test_applicant_condition_rules_accept_every_published_shape(catalog_rows) -> None:
    """ADB-JSP alone carries four of these: two years' post-degree experience, an age
    cap under 35, a means test in USD, and a two-year return commitment. Each stores
    the funder's own sentence in rule_text and a machine-comparable beside it."""
    catalog, _institution, _program, _other, _opportunity, benefit, _claim = catalog_rows

    experience = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="WORK_EXPERIENCE",
        comparable_value=Decimal("24.00"),
        rule_text="at least two years of full-time professional work experience after "
        "earning a bachelor's degree",
        scope_type="GLOBAL",
    )
    age = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="AGE_CAP",
        comparable_value=Decimal("35.00"),
        rule_text="not more than 35 years old at the time of application",
        scope_type="GLOBAL",
    )
    means = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="MEANS_TEST",
        comparable_value=Decimal("50000.00"),
        comparable_currency="USD",
        rule_text="gross family income not exceeding USD 50,000 per annum, verified by "
        "certified tax returns",
        scope_type="GLOBAL",
    )
    values = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="AFFILIATION",
        rule_text="applicants are expected to endorse the values of Christian Democracy",
        scope_type="GLOBAL",
    )
    bond = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="RETURN_SERVICE",
        comparable_value=Decimal("24.00"),
        rule_text="scholars commit to return to their home country for at least two "
        "years after completing the programme",
        scope_type="GLOBAL",
    )

    assert experience.comparable_value == Decimal("24.00")
    assert age.condition_type == "AGE_CAP"
    assert means.comparable_currency == "USD"
    assert values.comparable_value is None
    assert bond.condition_type is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        # APPLICANT_CONDITION without a condition_type is an uninterpretable row.
        (
            {"kind": "APPLICANT_CONDITION", "condition_type": None},
            "benefit_rule_condition_type_shape_valid",
        ),
        # A condition_type on any other kind claims a structure the kind does not have.
        # comparable_value is deliberately valid here: with it null this row would
        # violate BOTH constraints, and which name Postgres reports first is undefined.
        (
            {
                "kind": "ELIGIBILITY",
                "condition_type": "AGE_CAP",
                "comparable_value": Decimal("35.00"),
            },
            "benefit_rule_condition_type_shape_valid",
        ),
        # A means test without a currency is an amount that means nothing.
        (
            {
                "kind": "APPLICANT_CONDITION",
                "condition_type": "MEANS_TEST",
                "comparable_value": Decimal("50000.00"),
                "comparable_currency": None,
            },
            "benefit_rule_comparable_shape_valid",
        ),
        # Months are not money; a currency on a duration is a category error.
        (
            {
                "kind": "RETURN_SERVICE",
                "comparable_value": Decimal("24.00"),
                "comparable_currency": "USD",
            },
            "benefit_rule_comparable_shape_valid",
        ),
        # A work-experience bar with no number cannot be compared to anything.
        (
            {
                "kind": "APPLICANT_CONDITION",
                "condition_type": "WORK_EXPERIENCE",
                "comparable_value": None,
            },
            "benefit_rule_comparable_shape_valid",
        ),
        # Return service with no duration is an obligation of unknown length.
        (
            {"kind": "RETURN_SERVICE", "comparable_value": None},
            "benefit_rule_comparable_shape_valid",
        ),
    ],
)
def test_condition_rows_without_their_required_shape_are_rejected(
    catalog_rows, fields, constraint
) -> None:
    catalog, _institution, _program, _other, _opportunity, benefit, _claim = catalog_rows
    payload = {
        "benefit": benefit,
        "rule_text": "Published condition",
        "scope_type": "GLOBAL",
        **fields,
    }
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        catalog.BenefitRule.objects.create(**payload)
    assert constraint in str(error.value)
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/funding/test_catalog_models.py -q
```

Expected: FAIL. `test_catalog_choice_contracts_are_exact` fails on the kind set; the two new tests
fail with `FieldError`/`TypeError` on the unknown `condition_type` keyword.

- [ ] **Step 4: Add the enum members and fields**

In `apps/funding/models.py`, in `class BenefitRule`, replace the `Kind` class and add `ConditionType`
immediately after it:

```python
class BenefitRule(models.Model):
    class Kind(models.TextChoices):
        ELIGIBILITY = "ELIGIBILITY"
        AMOUNT = "AMOUNT"
        CAPACITY = "CAPACITY"
        GEOGRAPHIC_SCOPE = "GEOGRAPHIC_SCOPE"
        DEADLINE = "DEADLINE"
        # Added 2026-08-29 (spec §4). APPLICANT_CONDITION holds the non-nationality
        # gates that close a route to a student who satisfies every published academic
        # bar: ADB-JSP's two years of post-degree experience, its age cap and means
        # test, Konrad-Adenauer's values endorsement. A model that filters only on
        # nationality names routes the student then discovers are shut, which the spec
        # calls worse than omitting them.
        # RETURN_SERVICE is deliberately NOT a fifth condition type: it filters nobody.
        # It is a post-award obligation -- ADB-JSP, Bolashak and YLSY all bind the
        # graduate to return home -- and therefore a disclosure duty, because a bonded
        # award is a materially different product from an unbonded one.
        APPLICANT_CONDITION = "APPLICANT_CONDITION"
        RETURN_SERVICE = "RETURN_SERVICE"
        OTHER = "OTHER"

    class ConditionType(models.TextChoices):
        WORK_EXPERIENCE = "WORK_EXPERIENCE"
        AGE_CAP = "AGE_CAP"
        MEANS_TEST = "MEANS_TEST"
        AFFILIATION = "AFFILIATION"
```

Then, after the existing `rule_text` field, add:

```python
    condition_type = models.CharField(max_length=30, choices=ConditionType.choices, null=True)
    # The unit is a function of the condition, so there is no unit column:
    # WORK_EXPERIENCE and RETURN_SERVICE are months, AGE_CAP is years, MEANS_TEST is
    # money and is the only one that carries a currency. AFFILIATION has no
    # comparable -- "endorses Christian Democratic values" is not a number, and
    # pretending otherwise is how a subjective condition becomes a silent filter.
    # rule_text keeps the funder's own sentence regardless; this is a second reading
    # of it, never a replacement.
    comparable_value = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    comparable_currency = models.CharField(max_length=3, null=True)
```

- [ ] **Step 5: Replace the kind constraint and add the three new ones**

In `BenefitRule.Meta.constraints`, replace the existing `benefit_rule_kind_valid` constraint and
append three more. The final constraint list starts:

```python
    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=(
                        "ELIGIBILITY",
                        "AMOUNT",
                        "CAPACITY",
                        "GEOGRAPHIC_SCOPE",
                        "DEADLINE",
                        "APPLICANT_CONDITION",
                        "RETURN_SERVICE",
                        "OTHER",
                    )
                ),
                name="benefit_rule_kind_valid",
            ),
            models.CheckConstraint(
                # A biconditional, not a disjunction: APPLICANT_CONDITION requires a
                # condition_type AND every other kind forbids one. Written as a plain
                # OR, the second branch would silently admit an APPLICANT_CONDITION
                # row with no condition_type -- an uninterpretable rule.
                condition=models.Q(kind="APPLICANT_CONDITION", condition_type__isnull=False)
                | (
                    ~models.Q(kind="APPLICANT_CONDITION")
                    & models.Q(condition_type__isnull=True)
                ),
                name="benefit_rule_condition_type_shape_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    condition_type__in=(
                        "WORK_EXPERIENCE",
                        "AGE_CAP",
                        "MEANS_TEST",
                        "AFFILIATION",
                    )
                )
                | models.Q(condition_type__isnull=True),
                name="benefit_rule_condition_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        condition_type="MEANS_TEST",
                        comparable_value__isnull=False,
                        comparable_currency__isnull=False,
                    )
                    | models.Q(
                        condition_type__in=("WORK_EXPERIENCE", "AGE_CAP"),
                        comparable_value__isnull=False,
                        comparable_currency__isnull=True,
                    )
                    | models.Q(
                        condition_type="AFFILIATION",
                        comparable_value__isnull=True,
                        comparable_currency__isnull=True,
                    )
                    | models.Q(
                        kind="RETURN_SERVICE",
                        condition_type__isnull=True,
                        comparable_value__isnull=False,
                        comparable_currency__isnull=True,
                    )
                    | (
                        # RETURN_SERVICE is excluded from this catch-all deliberately:
                        # its condition_type is null too, so a plain "everything else is
                        # empty" branch would admit a bond of unknown length.
                        ~models.Q(kind="RETURN_SERVICE")
                        & models.Q(
                            condition_type__isnull=True,
                            comparable_value__isnull=True,
                            comparable_currency__isnull=True,
                        )
                    )
                ),
                name="benefit_rule_comparable_shape_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(comparable_value__isnull=True)
                | models.Q(comparable_value__gte=0),
                name="benefit_rule_comparable_value_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(comparable_currency__isnull=True)
                | models.Q(comparable_currency__in=_CURRENCIES),
                name="benefit_rule_comparable_currency_iso4217",
            ),
            # ... the existing scope_type, scope_shape and country constraints follow unchanged
        ]
```

Leave the existing `benefit_rule_scope_type_valid`, `benefit_rule_scope_shape_valid` and
`benefit_rule_country_iso3166_alpha2` constraints exactly as they are, after these.

Note the last `models.Q(condition_type__isnull=True, comparable_value__isnull=True, ...)` branch:
it is what lets every pre-existing kind (`ELIGIBILITY`, `AMOUNT`, `CAPACITY`, `GEOGRAPHIC_SCOPE`,
`DEADLINE`, `OTHER`) keep working untouched. The `kind="RETURN_SERVICE"` branch is listed before it
and is the only branch that pairs a null `condition_type` with a non-null comparable.

- [ ] **Step 6: Generate the migration**

```bash
POSTGRES_DB=tehsil_conditions uv run python manage.py makemigrations funding \
  -n benefit_rule_applicant_conditions
```

Expected: creates `apps/funding/migrations/0016_benefit_rule_applicant_conditions.py` with
`RemoveConstraint` + `AlterField` + `AddField` × 3 + `AddConstraint` × 5. Read the generated file
and confirm it depends on `0015_funding_family_affinity_and_private_foundation`. Do not hand-edit it.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/funding/test_catalog_models.py -q
POSTGRES_DB=tehsil_conditions uv run python manage.py makemigrations --check --dry-run
```

Expected: all `test_catalog_models.py` tests PASS; `makemigrations --check` prints
"No changes detected".

- [ ] **Step 8: Commit**

```bash
uv run git add apps/funding/models.py apps/funding/migrations/0016_benefit_rule_applicant_conditions.py tests/funding/test_catalog_models.py
uv run git commit -m "feat(funding): BenefitRule carries applicant conditions and return service

Two new kinds and a structured comparable beside the published quote. The
unit is a function of the condition, so there is no unit column. Return
service is its own kind because it filters nobody -- it is a post-award
obligation and therefore a disclosure duty."
```

---

## Task 2: Extraction states the condition and its comparable

Rather than a parallel claim type, extend the existing `EligibilityCriterionClaim` — it is already
"one published requirement, quoted" and already carries `EXPERIENCE` and `AGE` kinds. What it lacks
is the three missing kinds and the structured comparable, which is exactly the spec's addition.

**Files:**
- Modify: `apps/research/extraction.py:96-111` (`EligibilityCriterionClaim`)
- Modify: `apps/research/catalog.py:122-128` (`claim_rows`)
- Test: `tests/research/test_extraction.py`, `tests/research/test_catalog_writer.py`

**Interfaces:**
- Consumes: the `ConditionType` vocabulary from Task 1 (same string values, independently declared —
  `extraction.py` must not import from `apps.funding.models`; it is deliberately DB-free).
- Produces: `EligibilityCriterionClaim.kind` extended with `MEANS_TEST`, `AFFILIATION`,
  `RETURN_SERVICE`; fields `comparable_value: Decimal | None`, `comparable_currency: str | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/research/test_extraction.py`:

```python
def test_eligibility_criterion_carries_a_comparable_beside_the_quote() -> None:
    from apps.research.extraction import EligibilityCriterionClaim

    claim = EligibilityCriterionClaim(
        kind="EXPERIENCE",
        requirement="at least two years of full-time professional work experience",
        comparable_value=Decimal("24"),
        evidence="Applicants must have at least two years of full-time professional "
        "work experience after earning a bachelor's degree.",
    )

    assert claim.comparable_value == Decimal("24")
    assert claim.comparable_currency is None


def test_means_test_criterion_requires_a_currency_with_its_amount() -> None:
    from apps.research.extraction import EligibilityCriterionClaim

    with pytest.raises(ValidationError):
        EligibilityCriterionClaim(
            kind="MEANS_TEST",
            requirement="gross family income not exceeding USD 50,000",
            comparable_value=Decimal("50000"),
            evidence="Gross family income must not exceed USD 50,000 per annum.",
        )


def test_a_currency_without_an_amount_is_rejected() -> None:
    from apps.research.extraction import EligibilityCriterionClaim

    with pytest.raises(ValidationError):
        EligibilityCriterionClaim(
            kind="MEANS_TEST",
            requirement="a means test applies",
            comparable_currency="USD",
            evidence="A means test applies to all applicants.",
        )


def test_return_service_is_not_an_eligibility_criterion_kind() -> None:
    """It excludes nobody. A post-award obligation in the eligibility vocabulary is
    the conflation design §4 warns against."""
    from apps.research.extraction import EligibilityCriterionClaim

    with pytest.raises(ValidationError):
        EligibilityCriterionClaim(
            kind="RETURN_SERVICE",
            requirement="return home for two years",
            evidence="Scholars commit to return home for two years.",
        )


def test_return_service_is_its_own_claim_with_a_duration() -> None:
    from apps.research.extraction import ReturnServiceClaim

    claim = ReturnServiceClaim(
        months=24,
        evidence="Scholars commit to return to their home country for at least two "
        "years after completing the programme.",
    )

    assert claim.months == 24


def test_return_service_reaches_extracted_claims_as_its_own_field() -> None:
    from apps.research.extraction import ExtractedClaims, ReturnServiceClaim

    claims = ExtractedClaims(
        confidence=0.9,
        return_service=ReturnServiceClaim(
            months=60, evidence="Graduates must work in Kazakhstan for five years."
        ),
    )

    assert claims.return_service is not None
    assert claims.return_service.months == 60
```

Confirm `Decimal`, `pytest` and `ValidationError` are imported at the top of that test file; add
`from decimal import Decimal` and `from pydantic import ValidationError` if either is missing.

Append to `tests/research/test_catalog_writer.py` (the module already has
`pytestmark = pytest.mark.django_db`, the `source` and `snapshot` fixtures, `_official_lead()`,
`Decimal` and `TeachingLanguageClaim`; add nothing to the imports but
`EligibilityCriterionClaim`, imported inside the test the way the neighbouring tests import their
claim types):

```python
def test_an_applicant_conditions_comparable_survives_into_the_claim_table(
    source, snapshot
) -> None:
    """A field claim_rows does not emit is extracted and then discarded.

    ExtractedClaims is transient. Dropping the comparable means paying for the fetch
    and keeping a sentence the gate cannot read.
    """
    from apps.research.extraction import EligibilityCriterionClaim

    claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
        eligibility_criteria=(
            EligibilityCriterionClaim(
                kind="EXPERIENCE",
                requirement="at least two years of professional work experience",
                comparable_value=Decimal("24"),
                evidence="Applicants must have at least two years of professional "
                "work experience.",
            ),
            EligibilityCriterionClaim(
                kind="MEANS_TEST",
                requirement="gross family income not exceeding USD 50,000",
                comparable_value=Decimal("50000"),
                comparable_currency="USD",
                evidence="Gross family income must not exceed USD 50,000 per annum.",
            ),
            EligibilityCriterionClaim(
                kind="AFFILIATION",
                requirement="endorsement of the values of Christian Democracy",
                evidence="Applicants are expected to endorse our values.",
            ),
        ),
        confidence=0.9,
    )

    result = write_catalog_entry(
        lead=_official_lead(), claims=claims, source=source, snapshot=snapshot
    )

    assert result is not None
    eligibility = [
        claim.claim for claim in result.claims if claim.claim_class == "ELIGIBILITY"
    ]
    assert any("EXPERIENCE" in text and "[24]" in text for text in eligibility)
    assert any("MEANS_TEST" in text and "[50000 USD]" in text for text in eligibility)
    # No number to compare, and none invented: the quote travels alone.
    assert any(
        "AFFILIATION" in text and "[" not in text for text in eligibility
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/research/test_extraction.py tests/research/test_catalog_writer.py -q
```

Expected: FAIL — `extra="forbid"` rejects the unknown `comparable_value` keyword, and
`"MEANS_TEST"` is not a member of the `kind` Literal.

- [ ] **Step 3: Extend the claim schema**

Replace `EligibilityCriterionClaim` in `apps/research/extraction.py`:

```python
class EligibilityCriterionClaim(BaseModel):
    """One published requirement, quoted. The band ladder's leading rung.

    The corridor sweep found admission-difficulty statistics for international
    applicants are essentially unpublished everywhere, so distance from the
    published bar is the strongest evidence available -- which makes this the
    most load-bearing field in the schema.

    MEANS_TEST and AFFILIATION were added 2026-08-29 (design §4). The
    nationality-keyed research found them in scheme after scheme -- ADB-JSP's
    certified-tax-return income test, Konrad-Adenauer's values endorsement --
    and a criterion vocabulary without them silently records those pages as
    having no condition at all.

    Return service is deliberately NOT a kind here. It excludes nobody, so it
    is not an eligibility criterion; putting a post-award obligation in the
    eligibility vocabulary is the conflation design §4 warns against. It has
    its own claim, below.

    ``comparable_value`` is a machine-usable reading of the same sentence
    ``requirement`` and ``evidence`` already quote; it never replaces them. Its
    unit follows the kind: EXPERIENCE is months, AGE is years, MEANS_TEST is
    money and is the only kind that carries a currency.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[
        "GRADE",
        "LANGUAGE",
        "EXPERIENCE",
        "DEGREE",
        "AGE",
        "NATIONALITY",
        "MEANS_TEST",
        "AFFILIATION",
        "OTHER",
    ]
    requirement: str = Field(min_length=1, max_length=1_000)
    comparable_value: Decimal | None = Field(default=None, ge=0)
    comparable_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    evidence: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def money_conditions_carry_their_currency(self) -> EligibilityCriterionClaim:
        if self.kind == "MEANS_TEST" and (self.comparable_value is None) != (
            self.comparable_currency is None
        ):
            raise ValueError("a means test states both an amount and its currency, or neither")
        if self.kind != "MEANS_TEST" and self.comparable_currency is not None:
            raise ValueError("only a means test carries a currency; others are durations")
        return self


class ReturnServiceClaim(BaseModel):
    """A bond on the graduate, quoted. Not an eligibility criterion (design §4).

    ADB-JSP, Bolashak and YLSY all bind the graduate to return home for a stated
    period. It excludes nobody at application time, so it filters nothing and lives
    outside the eligibility vocabulary; what it creates is a disclosure duty, because
    a bonded award is a materially different product from an unbonded one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    months: int = Field(ge=1, le=600)
    evidence: str = Field(min_length=1, max_length=1_000)
```

Then add the field to `ExtractedClaims`, beside the other design-§4 additions:

```python
    return_service: ReturnServiceClaim | None = None
```

`Decimal`, `model_validator` and `Field` are already imported in this module — confirm with
`grep -n "^from decimal\|model_validator" apps/research/extraction.py` before assuming it.

- [ ] **Step 4: Emit the comparable from claim_rows**

In `apps/research/catalog.py`, replace the `eligibility_criteria` loop inside `claim_rows`:

```python
    for criterion in claims.eligibility_criteria:
        # The comparable travels with the quote or it is discarded: ExtractedClaims is
        # transient, so a field claim_rows does not emit was paid for at fetch time and
        # then thrown away. An applicant condition without its number cannot close a
        # route, which is the whole point of extracting it.
        if criterion.comparable_value is None:
            comparable = ""
        elif criterion.comparable_currency is None:
            comparable = f" [{criterion.comparable_value}]"
        else:
            comparable = f" [{criterion.comparable_value} {criterion.comparable_currency}]"
        rows.append(
            (
                classes.ELIGIBILITY,
                f"{criterion.kind}: {criterion.requirement}{comparable} — {criterion.evidence}",
            )
        )
```

- [ ] **Step 5: Emit return service from claim_rows**

Still in `claim_rows`, after the `funding_tracks` loop, add:

```python
    if claims.return_service is not None:
        # FUNDING, not ELIGIBILITY: a bond is a property of the award, not a bar the
        # applicant clears. Emitted here or discarded -- ExtractedClaims is transient.
        rows.append(
            (
                classes.FUNDING,
                f"Return service: {claims.return_service.months} months — "
                f"{claims.return_service.evidence}",
            )
        )
```

- [ ] **Step 6: Record the schema growth against the existing token-cap note**

`apps/research/extraction.py` carries a comment on `max_output_tokens=8_000` reading "revisit this
number again the next time the schema grows." This task grows the schema, so answer it rather than
walking past it. Append to that comment block, immediately before `max_output_tokens=8_000`:

```python
            # 2026-08-29: revisited. This addition is two optional scalars on an
            # existing nested model plus one optional two-field model, not a new
            # tuple-of-models, so the worst-case output grows by well under 200
            # tokens. Cap unchanged.
```

Leave the number at `8_000`. Raising it without evidence of truncation is speculation.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/research/ -q
```

Expected: PASS, with no new failures against the baseline.

- [ ] **Step 8: Commit**

```bash
uv run git add apps/research/extraction.py apps/research/catalog.py tests/research/test_extraction.py tests/research/test_catalog_writer.py
uv run git commit -m "feat(research): extract applicant conditions with a structured comparable

Three new criterion kinds and an optional comparable beside the quote,
emitted through claim_rows so it survives the transient ExtractedClaims."
```

---

## Task 3: A failed condition closes the route, not the programme

**This is the load-bearing task and the one most likely to be got wrong.** An applicant condition
disqualifies a *funding route*, not the programme. `benefit_applies()` is the shared function that
both `_mandatory_funding_route_gate` (`apps/funding/evaluation.py`) and affordability's `_bucket_for`
(`apps/funding/affordability.py`) already call — one guard there closes the route in both places at
once. Do **not** add an entry to `HARD_GATES`: that would kill a candidate over one closed route
while three open ones remain.

Only `WORK_EXPERIENCE` is decided here. `StudentProfileSnapshot` carries `experience`
(`ExperienceRecord.months`) but has **no date of birth and no income**, so `AGE_CAP` and
`MEANS_TEST` are not computable from a v2 profile, and `AFFILIATION` is not computable from
any profile. Those route to review in Task 4 — they must not be silently treated as passing or as
failing.

**Files:**
- Modify: `apps/funding/evaluation.py` (add facts near `BenefitFact`, ~line 51; modify
  `benefit_applies`, ~line 155)
- Modify: `tests/funding/conftest.py`
- Test: `tests/funding/test_hard_gates.py`

**Interfaces:**
- Consumes: the `ConditionType` string values from Task 1 (independently declared as a `Literal`;
  `evaluation.py` is deliberately DB-free and imports nothing from `apps.funding.models`).
- Produces:
  - `ApplicantConditionType = Literal["WORK_EXPERIENCE", "AGE_CAP", "MEANS_TEST", "AFFILIATION"]`
  - `ApplicantConditionFact(benefit_id: str, condition_type: ApplicantConditionType, comparable_value: Decimal | None, comparable_currency: str | None, rule_text: str)`
  - `ReturnServiceFact(benefit_id: str, months: int, rule_text: str)`
  - `CandidateFacts.applicant_conditions: tuple[ApplicantConditionFact, ...]` (default `()`)
  - `CandidateFacts.return_service: tuple[ReturnServiceFact, ...]` (default `()`)
  - `benefit_applies(benefit, candidate, profile) -> bool` — unchanged signature, new behaviour
  - `closed_route_reasons(profile, candidate) -> tuple[str, ...]` — one string per route shut by
    an unmet condition, naming the route and quoting the condition
  - `make_applicant_condition(...) -> ApplicantConditionFact` and
    `make_return_service(...) -> ReturnServiceFact` in `tests/funding/conftest.py`

- [ ] **Step 1: Add the conftest helpers**

Append to `tests/funding/conftest.py`, and add `ApplicantConditionFact` and `ReturnServiceFact` to
the existing `from apps.funding.evaluation import ...` line:

```python
def make_applicant_condition(
    condition_type: str = "WORK_EXPERIENCE",
    *,
    benefit_id: str = "benefit-1",
    comparable_value: str | None = "24",
    comparable_currency: str | None = None,
    rule_text: str = "at least two years of professional work experience",
) -> ApplicantConditionFact:
    return ApplicantConditionFact(
        benefit_id=benefit_id,
        condition_type=condition_type,
        comparable_value=Decimal(comparable_value) if comparable_value is not None else None,
        comparable_currency=comparable_currency,
        rule_text=rule_text,
    )


def make_return_service(
    *,
    benefit_id: str = "benefit-1",
    months: int = 24,
    rule_text: str = "return home for at least two years after the programme",
) -> ReturnServiceFact:
    return ReturnServiceFact(benefit_id=benefit_id, months=months, rule_text=rule_text)
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/funding/test_hard_gates.py`, adding `ExperienceRecord` to the
`apps.accounts.schemas` imports and `make_applicant_condition` to the conftest imports:

```python
def test_unmet_work_experience_condition_closes_that_route_only() -> None:
    """ADB-JSP's two-year bar excludes fresh graduates, who are most of our
    population. It shuts that scheme, not the programme: a student with another
    verified route is still fundable."""
    profile = make_profile(funding_dependency="MANDATORY", experience=())
    candidate = make_candidate(
        benefits=(
            make_benefit(id="bonded-scheme"),
            make_benefit(id="open-scheme"),
        ),
        applicant_conditions=(make_applicant_condition(benefit_id="bonded-scheme"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"


def test_unmet_work_experience_on_the_only_route_fails_the_mandatory_funding_gate() -> None:
    profile = make_profile(funding_dependency="MANDATORY", experience=())
    candidate = make_candidate(
        benefits=(make_benefit(id="bonded-scheme"),),
        applicant_conditions=(make_applicant_condition(benefit_id="bonded-scheme"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert any("no viable verified funding route" in reason for reason in result.reasons)


def test_met_work_experience_leaves_the_route_open() -> None:
    profile = make_profile(
        funding_dependency="MANDATORY",
        experience=(
            ExperienceRecord(kind="WORK", summary="Backend engineer", months=30),
        ),
    )
    candidate = make_candidate(
        benefits=(make_benefit(id="bonded-scheme"),),
        applicant_conditions=(make_applicant_condition(benefit_id="bonded-scheme"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"


def test_internships_do_not_count_toward_a_professional_experience_bar() -> None:
    """The published bars say "professional work experience". Counting an internship
    toward one over-qualifies the student and produces exactly the false offer the
    spec calls worse than an omission."""
    profile = make_profile(
        funding_dependency="MANDATORY",
        experience=(
            ExperienceRecord(kind="INTERNSHIP", summary="Summer internship", months=36),
        ),
    )
    candidate = make_candidate(
        benefits=(make_benefit(id="bonded-scheme"),),
        applicant_conditions=(make_applicant_condition(benefit_id="bonded-scheme"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"


def test_an_excluded_scheme_names_the_condition_that_excluded_it() -> None:
    """A pack that says "no viable funding route" and stops has told the student
    nothing they can act on. The reason has to name the scheme and the bar."""
    profile = make_profile(funding_dependency="MANDATORY", experience=())
    candidate = make_candidate(
        benefits=(make_benefit(id="adb-jsp"),),
        applicant_conditions=(
            make_applicant_condition(
                benefit_id="adb-jsp",
                rule_text="at least two years of full-time professional work experience",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    named = " ".join(result.reasons)
    assert "adb-jsp" in named
    assert "WORK_EXPERIENCE" in named
    assert "two years of full-time professional work experience" in named


def test_a_closed_route_does_not_count_toward_affordability_coverage() -> None:
    """benefit_applies is the single point both the funding gate and the affordability
    buckets route through, so one guard closes the route in both."""
    from apps.funding.affordability import calculate_affordability

    profile = make_profile(experience=())
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "10000.00"),),
        benefits=(make_benefit(id="bonded-scheme", kind="TUITION", amount="8000.00"),),
        applicant_conditions=(make_applicant_condition(benefit_id="bonded-scheme"),),
    )

    affordability = calculate_affordability(profile, candidate, EUR_RATES)

    assert affordability.covered == Decimal("0.00")
    assert affordability.gap == Decimal("10000.00")
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/funding/test_hard_gates.py -q
```

Expected: FAIL — `extra="forbid"` on `CandidateFacts` rejects the unknown `applicant_conditions`
keyword.

- [ ] **Step 4: Add the facts and the guard**

In `apps/funding/evaluation.py`, after the `BenefitFact` class, add:

```python
ApplicantConditionType = Literal[
    "WORK_EXPERIENCE", "AGE_CAP", "MEANS_TEST", "AFFILIATION"
]

#: A v2 StudentProfileSnapshot has no date of birth and no income, and no profile can
#: answer "does this student endorse Christian Democratic values". These are not
#: treated as passing (that offers a route the student may not be able to enter) nor
#: as failing (that hides a route they may well be able to enter). They route the
#: candidate to POSSIBLY_ELIGIBLE_REVIEW, which is a consultant's task.
UNEVALUABLE_CONDITIONS: frozenset[ApplicantConditionType] = frozenset(
    {"AGE_CAP", "MEANS_TEST", "AFFILIATION"}
)


class ApplicantConditionFact(BaseModel):
    """One non-nationality condition attached to one funding route (design §4).

    Attached to a benefit, never to the programme: a condition closes the route it
    is published on. A student who fails ADB-JSP's experience bar has lost ADB-JSP,
    not the degree.
    """

    model_config = _CANDIDATE_CONFIG

    benefit_id: str
    condition_type: ApplicantConditionType
    #: Months for WORK_EXPERIENCE, years for AGE_CAP, money for MEANS_TEST, and None
    #: for AFFILIATION, which has no number to compare.
    comparable_value: Decimal | None = Field(default=None, ge=0)
    comparable_currency: str | None = None
    #: The funder's own sentence, carried so a closed route can be explained.
    rule_text: str


class ReturnServiceFact(BaseModel):
    """A post-award obligation, not a filter (design §4).

    ADB-JSP, Bolashak and YLSY all bind the graduate to return home. Nothing here
    excludes a candidate; a bonded award is a materially different product from an
    unbonded one and the duty this creates is disclosure, discharged in pack.py.
    """

    model_config = _CANDIDATE_CONFIG

    benefit_id: str
    months: int = Field(ge=1)
    rule_text: str
```

Add to `CandidateFacts`, after the `benefits` field:

```python
    applicant_conditions: tuple[ApplicantConditionFact, ...] = ()
    return_service: tuple[ReturnServiceFact, ...] = ()
```

Replace `benefit_applies` and add the two helpers above it:

```python
def _professional_experience_months(profile: StudentProfileSnapshot) -> int:
    # WORK only. The published bars say "professional work experience" -- ADB-JSP's is
    # explicitly post-degree -- and counting an internship or a research assistantship
    # toward one over-qualifies the student into a route that will reject them, which
    # the spec calls worse than omitting the route.
    return sum(record.months for record in profile.experience if record.kind == "WORK")


def _conditions_are_met(
    benefit: BenefitFact, candidate: CandidateFacts, profile: StudentProfileSnapshot
) -> bool:
    """Only the conditions a profile can actually answer are decided here.

    UNEVALUABLE_CONDITIONS deliberately fall through as met; evaluate() picks them up
    and routes the candidate to review rather than letting them pass silently.
    """
    months = _professional_experience_months(profile)
    for condition in candidate.applicant_conditions:
        if condition.benefit_id != benefit.id:
            continue
        if condition.condition_type != "WORK_EXPERIENCE":
            continue
        if condition.comparable_value is not None and months < condition.comparable_value:
            return False
    return True


def benefit_applies(
    benefit: BenefitFact, candidate: CandidateFacts, profile: StudentProfileSnapshot
) -> bool:
    # Conditions are checked before scope: a route the student cannot enter does not
    # apply to them no matter where it is published. Both the mandatory-funding hard
    # gate and affordability's buckets call this, so the guard lands once.
    if not _conditions_are_met(benefit, candidate, profile):
        return False
    if benefit.scope_type == "GLOBAL":
        return True
    if benefit.scope_type == "NATIONALITY":
        return benefit.nationality_code == profile.nationality
    if benefit.scope_type == "COUNTRY":
        return benefit.country_code == candidate.program_country_code
    if benefit.scope_type == "CITY":
        return benefit.location_key == candidate.location_key
    return benefit.program_id == candidate.program_id


def closed_route_reasons(
    profile: StudentProfileSnapshot, candidate: CandidateFacts
) -> tuple[str, ...]:
    """Every route shut by a condition the student demonstrably does not meet.

    "No viable verified funding route exists" is true but useless: it tells a student
    nothing they can act on, and hides that the bar was two years of experience rather
    than their grades. Each string names the scheme and quotes the published condition.
    """
    months = _professional_experience_months(profile)
    return tuple(
        f"funding route {condition.benefit_id} is closed by its "
        f"{condition.condition_type} condition: {condition.rule_text}"
        for condition in candidate.applicant_conditions
        if condition.condition_type == "WORK_EXPERIENCE"
        and condition.comparable_value is not None
        and months < condition.comparable_value
    )
```

- [ ] **Step 5: Name the closed route in the outcome**

In `evaluate`, replace the two lines that build and return the hard-gate failures:

```python
    failures = tuple(gate.reason for gate in HARD_GATES if not gate.passes(profile, candidate))
    if failures:
        # A gate's reason is static text; the condition that shut a route is not. Append
        # it so an excluded candidate says which scheme closed and on what bar.
        return RecommendationOutcome(
            "NOT_ELIGIBLE", failures + closed_route_reasons(profile, candidate), None
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/funding/test_hard_gates.py tests/funding/test_affordability.py tests/funding/test_ranking.py -q
```

Expected: PASS. If `test_affordability.py` or `test_ranking.py` regress, the guard is placed wrong —
it must be a no-op for any candidate with an empty `applicant_conditions`, which is every existing
fixture.

- [ ] **Step 7: Commit**

```bash
uv run git add apps/funding/evaluation.py tests/funding/conftest.py tests/funding/test_hard_gates.py
uv run git commit -m "feat(funding): an unmet applicant condition closes that funding route

Guard lands in benefit_applies, the one function both the mandatory-funding
gate and the affordability buckets already route through. A condition shuts
the scheme it is published on, never the programme."
```

---

## Task 4: A condition the profile cannot answer goes to review, never silently through

`POSSIBLY_ELIGIBLE_REVIEW` already exists in `EligibilityOutcome` and is currently reachable only
through the `BALANCED` score threshold. Reuse it. `RecommendationOutcome.reasons` is currently `()`
on every non-failing path and must now carry the review reasons.

**Files:**
- Modify: `apps/funding/evaluation.py` (`evaluate`, at the end of the module)
- Test: `tests/funding/test_hard_gates.py`

**Interfaces:**
- Consumes: `ApplicantConditionFact`, `UNEVALUABLE_CONDITIONS`, `benefit_applies` from Task 3.
- Produces: `unevaluable_condition_reasons(profile, candidate) -> tuple[str, ...]`;
  `evaluate` returns `outcome="POSSIBLY_ELIGIBLE_REVIEW"` with non-empty `reasons` and a non-None
  `scores` when any applicable route carries an unevaluable condition.

- [ ] **Step 1: Write the failing tests**

Append to `tests/funding/test_hard_gates.py`:

```python
def test_an_age_cap_cannot_be_checked_and_routes_to_review() -> None:
    """A v2 profile has no date of birth. Passing the candidate silently would offer a
    route that may be shut; failing it silently would hide one that may be open."""
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="capped-scheme"),),
        applicant_conditions=(
            make_applicant_condition(
                "AGE_CAP",
                benefit_id="capped-scheme",
                comparable_value="35",
                rule_text="not more than 35 years old at the time of application",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("AGE_CAP" in reason for reason in result.reasons)
    assert any("35 years old" in reason for reason in result.reasons)
    assert result.scores is not None


def test_a_means_test_routes_to_review_and_names_the_route() -> None:
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="adb-jsp"),),
        applicant_conditions=(
            make_applicant_condition(
                "MEANS_TEST",
                benefit_id="adb-jsp",
                comparable_value="50000",
                comparable_currency="USD",
                rule_text="gross family income not exceeding USD 50,000 per annum",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("adb-jsp" in reason for reason in result.reasons)


def test_an_unevaluable_condition_on_an_inapplicable_route_does_not_force_review() -> None:
    """The route is scoped to a country this programme is not in, so its condition is
    moot. Sending a consultant a task about a scheme that never applied is noise."""
    profile = make_profile()
    candidate = make_candidate(
        program_country_code="DE",
        benefits=(
            make_benefit(id="fr-only", scope_type="COUNTRY", country_code="FR"),
        ),
        applicant_conditions=(
            make_applicant_condition("AGE_CAP", benefit_id="fr-only", comparable_value="35"),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"
    assert result.reasons == ()


def test_a_route_already_closed_on_experience_does_not_also_force_review() -> None:
    """WORK_EXPERIENCE already shut this route in benefit_applies, so its unevaluable
    sibling condition is moot -- no consultant task for a scheme the student is out of."""
    profile = make_profile(experience=())
    candidate = make_candidate(
        benefits=(make_benefit(id="adb-jsp"), make_benefit(id="open-scheme")),
        applicant_conditions=(
            make_applicant_condition(benefit_id="adb-jsp"),
            make_applicant_condition("AGE_CAP", benefit_id="adb-jsp", comparable_value="35"),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/funding/test_hard_gates.py -q -k "review or moot or inapplicable or already_closed"
```

Expected: FAIL — outcome is `ELIGIBLE` where the test expects `POSSIBLY_ELIGIBLE_REVIEW`.

- [ ] **Step 3: Add the reason collector and wire it into evaluate**

In `apps/funding/evaluation.py`, add above `evaluate`:

```python
def unevaluable_condition_reasons(
    profile: StudentProfileSnapshot, candidate: CandidateFacts
) -> tuple[str, ...]:
    """Conditions on still-open routes that no profile field can decide.

    Restricted to routes that actually apply: a condition on a route already closed
    by benefit_applies -- wrong country, or a failed experience bar -- is moot, and
    raising a consultant task about a scheme the student was never in is noise.
    """
    open_routes = {
        benefit.id
        for benefit in candidate.benefits
        if benefit.is_current and benefit_applies(benefit, candidate, profile)
    }
    return tuple(
        f"{condition.condition_type} on funding route {condition.benefit_id} cannot be "
        f"checked against the student profile: {condition.rule_text}"
        for condition in candidate.applicant_conditions
        if condition.condition_type in UNEVALUABLE_CONDITIONS
        and condition.benefit_id in open_routes
    )
```

Replace the last three lines of `evaluate`:

```python
    review_reasons = unevaluable_condition_reasons(profile, candidate)
    if review_reasons or not qualifies:
        return RecommendationOutcome("POSSIBLY_ELIGIBLE_REVIEW", review_reasons, scores)
    return RecommendationOutcome("ELIGIBLE", (), scores)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/funding/ -q
```

Expected: PASS, apart from the 25 pre-existing `TemplateDoesNotExist` failures. If a
`test_pack_service.py` or `test_ranking.py` test now fails, check whether it asserted
`reasons == ()` on a review outcome — that assertion was only ever true because nothing populated
review reasons, and updating it is correct.

- [ ] **Step 5: Commit**

```bash
uv run git add apps/funding/evaluation.py tests/funding/test_hard_gates.py
uv run git commit -m "feat(funding): conditions no profile can answer route to review

A v2 profile has no date of birth and no income. Passing an age cap or a
means test silently offers a route that may be shut; failing it silently
hides one that may be open. Both are wrong, so it becomes a review task."
```

---

## Task 5: The pack tells the student the award is bonded

Return service never excludes anything. The duty it creates is disclosure, and `RankedCandidate`
already has the channel: `tradeoffs`. Broadening it from "weaker fit" to "things the student must be
told before accepting" is the smallest change that discharges the duty.

**Files:**
- Modify: `apps/funding/pack.py:60-99` (`rank_candidates`)
- Test: `tests/funding/test_ranking.py`

**Interfaces:**
- Consumes: `ReturnServiceFact`, `benefit_applies` and `closed_route_reasons` from Task 3.
- Produces: `RankedCandidate.tradeoffs` may contain a return-service disclosure string; no signature
  changes anywhere.

- [ ] **Step 1: Write the failing tests**

Append to `tests/funding/test_ranking.py`, adding `make_return_service` to its conftest imports:

```python
def test_a_bonded_award_is_disclosed_to_the_student() -> None:
    """ADB-JSP, Bolashak and YLSY all bind the graduate to return home. A bonded award
    is a materially different product from an unbonded one and the student must be
    told which they are accepting."""
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="bolashak"),),
        return_service=(
            make_return_service(
                benefit_id="bolashak",
                months=60,
                rule_text="graduates must work in Kazakhstan for five years",
            ),
        ),
    )

    ranked = rank_candidates(profile, (candidate,), EUR_RATES)

    assert len(ranked) == 1
    disclosure = " ".join(ranked[0].tradeoffs)
    assert "bolashak" in disclosure
    assert "60 months" in disclosure
    assert "work in Kazakhstan for five years" in disclosure


def test_return_service_never_excludes_a_candidate() -> None:
    profile = make_profile(funding_dependency="MANDATORY")
    candidate = make_candidate(
        benefits=(make_benefit(id="bolashak"),),
        return_service=(make_return_service(benefit_id="bolashak"),),
    )

    ranked = rank_candidates(profile, (candidate,), EUR_RATES)

    assert len(ranked) == 1


def test_a_route_closed_by_a_condition_is_named_even_when_the_candidate_survives() -> None:
    """The candidate stays in the pack on another route, but the student should still
    learn that the scheme they had heard of is shut, and on what bar."""
    profile = make_profile(experience=())
    candidate = make_candidate(
        benefits=(make_benefit(id="adb-jsp"), make_benefit(id="open-scheme")),
        applicant_conditions=(
            make_applicant_condition(
                benefit_id="adb-jsp",
                rule_text="at least two years of full-time professional work experience",
            ),
        ),
    )

    ranked = rank_candidates(profile, (candidate,), EUR_RATES)

    disclosure = " ".join(ranked[0].tradeoffs)
    assert "adb-jsp" in disclosure
    assert "two years of full-time professional work experience" in disclosure


def test_return_service_on_an_inapplicable_route_is_not_disclosed() -> None:
    """Disclosing a bond attached to a scheme the student cannot use is a false
    warning, and it would push them off a candidate that carries no bond at all."""
    profile = make_profile()
    candidate = make_candidate(
        program_country_code="DE",
        benefits=(make_benefit(id="fr-only", scope_type="COUNTRY", country_code="FR"),),
        return_service=(make_return_service(benefit_id="fr-only"),),
    )

    ranked = rank_candidates(profile, (candidate,), EUR_RATES)

    assert not any("fr-only" in tradeoff for tradeoff in ranked[0].tradeoffs)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/funding/test_ranking.py -q -k "bonded or return_service"
```

Expected: FAIL — `tradeoffs` is empty; no disclosure string is produced.

- [ ] **Step 3: Add the disclosure**

In `apps/funding/pack.py`, add to the imports:

```python
from apps.funding.evaluation import (
    CandidateFacts,
    EvaluationScores,
    benefit_applies,
    closed_route_reasons,
    evaluate,
)
```

Add above `rank_candidates`:

```python
def _return_service_disclosures(
    profile: StudentProfileSnapshot, candidate: CandidateFacts
) -> tuple[str, ...]:
    """A bonded award is a different product, and the student must be told before
    accepting it. Only for routes that actually apply -- warning about a bond on a
    scheme the student cannot use would push them off an unbonded candidate.
    """
    open_routes = {
        benefit.id
        for benefit in candidate.benefits
        if benefit.is_current and benefit_applies(benefit, candidate, profile)
    }
    return tuple(
        f"funding route {obligation.benefit_id} is bonded: it commits you to "
        f"{obligation.months} months of return service after graduation — "
        f"{obligation.rule_text}"
        for obligation in candidate.return_service
        if obligation.benefit_id in open_routes
    )
```

In `rank_candidates`, replace the `tradeoffs` assignment inside the final loop:

```python
    ranked = []
    for candidate, scores, affordability in ordered:
        tradeoffs = (
            *closed_route_reasons(profile, candidate),
            *_return_service_disclosures(profile, candidate),
        )
        if soft_fit(scores) < best_soft_fit:
            tradeoffs = ("weaker fit than another recommended candidate", *tradeoffs)
        ranked.append(
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/funding/test_ranking.py tests/funding/test_pack_service.py -q
```

Expected: PASS. `test_ranking.py:65`'s existing `assert "weaker fit" in " ".join(ranked[0].tradeoffs)`
must still pass — the weaker-fit string is prepended, not replaced.

- [ ] **Step 5: Run every gate**

```bash
POSTGRES_DB=tehsil_conditions uv run pytest tests/funding/ tests/research/ -q
POSTGRES_DB=tehsil_conditions uv run python manage.py makemigrations --check --dry-run
uv run ruff check apps tests
uv run mypy apps
uv run bandit -c pyproject.toml -r apps config
```

Expected: pytest shows only the 25 pre-existing `TemplateDoesNotExist` failures — **check by test
name against the baseline, not by count**. `makemigrations --check` prints "No changes detected".
`ruff` and `bandit` clean. `mypy` reports no issues across 134 source files.

If any check cannot run, report the command, the reason and the uncertainty. Do not claim success
without the command output.

- [ ] **Step 6: Commit**

```bash
uv run git add apps/funding/pack.py tests/funding/test_ranking.py
uv run git commit -m "feat(funding): disclose a bonded award in the pack

Return service excludes nobody; it creates a disclosure duty. RankedCandidate
already had the channel, so tradeoffs widens from weaker-fit to everything
the student must be told before accepting."
```

---

## What this plan deliberately does not do

State these plainly when reporting completion; do not let them read as oversights.

1. **Nothing resolves catalog rows into `CandidateFacts`.** No such resolver exists anywhere in
   `apps/`, before or after this plan. Applicant conditions are contract and logic, exercised by
   tests, not yet by data.
2. **The catalog has zero rows.** These filters will filter nothing until a discovery run populates
   it. That was a known and accepted condition of starting this work, not a discovery made during it.
3. **`AGE_CAP` and `MEANS_TEST` are never decided, only escalated.** Deciding them needs date of
   birth and household income on the profile, which is a `schema_version` 3 migration
   (`apps/accounts/schemas.py:115`, and the `profile_schema_version_valid` constraint in
   `apps/accounts/models.py:27`) plus consent and data-minimisation review for two new categories of
   personal data. Out of scope here by design.
4. **`AFFILIATION` is not automatable at all** and should stay a human judgement.
   Konrad-Adenauer's expectation of endorsement is not a field.
5. **Return service is disclosed, not modelled as a cost.** Its effect on lifetime earnings and on
   post-study mobility is a §2 utility question, untouched here.
