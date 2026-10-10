from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import DataError, IntegrityError, connection, transaction
from django.utils import timezone
from psycopg.types.json import Jsonb


def _models():
    from apps.funding import models as catalog

    return catalog


def _assert_constraint(sql: str, params: list[object], name: str) -> None:
    with pytest.raises(IntegrityError) as caught, transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
    assert caught.value.__cause__.diag.constraint_name == name


def _clone_insert(table: str, source_id: object, overrides: dict[str, object]) -> None:
    clone_id = uuid4()
    values: dict[str, object] = {
        "id": str(clone_id),
        **{
            key: str(value) if isinstance(value, type(clone_id)) else value
            for key, value in overrides.items()
        },
    }
    if table == "public.funding_institution":
        values.setdefault("canonical_key", f"constraint:institution:{clone_id}")
    elif table == "public.funding_program":
        values.setdefault("canonical_key", f"constraint:program:{clone_id}")
    elif table == "public.funding_fundingopportunity":
        values.setdefault("canonical_key", f"constraint:opportunity:{clone_id}")
    elif table == "public.funding_officialsource":
        values.setdefault("canonical_url", f"https://{clone_id}.example.test")
    elif table == "public.accounts_studentprofileversion":
        values.setdefault("version", 2)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {table}
            SELECT (jsonb_populate_record(NULL::{table}, to_jsonb(source_row) || %s)).*
              FROM {table} AS source_row
             WHERE id = %s
            """,
            [Jsonb(values), source_id],
        )


def _assert_insert_constraint(
    table: str,
    source_id: object,
    overrides: dict[str, object],
    name: str,
) -> None:
    with pytest.raises(IntegrityError) as caught, transaction.atomic():
        _clone_insert(table, source_id, overrides)
    assert caught.value.__cause__.diag.constraint_name == name


@pytest.fixture
def constrained_rows(db, agency_a, membership_a):
    catalog = _models()
    institution = catalog.Institution.objects.create(
        canonical_key="constraint:institution",
        name="Constraint University",
        country_code="AZ",
        official_website="https://university.example.test",
    )
    program = catalog.Program.objects.create(
        institution=institution,
        canonical_key="constraint:program",
        name="MSc Chemistry",
        campus_name="Main",
        city="Baku",
        country_code="AZ",
        location_key="az:baku",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=12,
    )
    opportunity = catalog.FundingOpportunity.objects.create(
        canonical_key="constraint:opportunity",
        name="Scholarship",
        family="GOVERNMENT_SCHOLARSHIP",
        scope_type="COUNTRY",
        country_code="AZ",
    )
    benefit = catalog.FundingBenefit.objects.create(
        opportunity=opportunity,
        kind="TUITION",
        amount=Decimal("100.00"),
        currency="EUR",
        period="ONE_OFF",
        description="Tuition",
    )
    cost = catalog.CostComponent.objects.create(
        program=program,
        kind="TUITION",
        amount=Decimal("100.00"),
        currency="EUR",
        period="ONE_OFF",
    )
    rule = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="ELIGIBILITY",
        rule_text="Open",
        scope_type="GLOBAL",
    )
    source = catalog.OfficialSource.objects.create(
        canonical_url="https://official.example.test/source",
        publisher="Publisher",
        source_type="GOVERNMENT",
    )
    claim = catalog.OfficialEvidenceClaim.objects.create(
        source=source,
        claim="Claim",
        evidence_strength="DIRECT",
        visibility="STUDENT_FACING",
        last_checked_at=timezone.now(),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.accounts_studentprofileversion
                (id, tenant_id, student_id, version, schema_version, snapshot, created_at)
            VALUES (%s, %s, %s, 1, 1, '{}'::jsonb, now())
            RETURNING id
            """,
            [uuid4(), agency_a.id, membership_a.id],
        )
        profile_id = cursor.fetchone()[0]
    return {
        "institution": institution.id,
        "program": program.id,
        "opportunity": opportunity.id,
        "benefit": benefit.id,
        "cost": cost.id,
        "rule": rule.id,
        "source": source.id,
        "claim": claim.id,
        "profile": profile_id,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("key", "overrides", "constraint"),
    [
        ("institution", {"country_code": "ZZ"}, "institution_country_iso3166_alpha2"),
        (
            "institution",
            {"official_website": "http://example.test"},
            "institution_official_website_https",
        ),
        ("program", {"country_code": "ZZ"}, "program_country_iso3166_alpha2"),
        ("program", {"degree_level": "PHD"}, "program_degree_level_valid"),
        (
            "program",
            {"teaching_languages": []},
            "program_teaching_languages_nonempty",
        ),
        (
            "program",
            {"teaching_languages": [str(index) for index in range(11)]},
            "program_teaching_languages_limit",
        ),
        ("program", {"duration_months": 0}, "program_duration_months_range"),
        (
            "opportunity",
            {"family": "UNKNOWN"},
            "funding_opportunity_family_valid",
        ),
        (
            "opportunity",
            {"scope_type": "CITY"},
            "funding_opportunity_scope_type_valid",
        ),
        (
            "opportunity",
            {"country_code": None},
            "funding_opportunity_scope_shape_valid",
        ),
        (
            "opportunity",
            {"scope_type": "GLOBAL"},
            "funding_opportunity_scope_shape_valid",
        ),
        (
            "opportunity",
            {"country_code": "AZ", "institution_id": "__institution__"},
            "funding_opportunity_scope_shape_valid",
        ),
        (
            "opportunity",
            {"country_code": "ZZ"},
            "funding_opportunity_country_iso3166_alpha2",
        ),
        ("benefit", {"kind": "UNKNOWN"}, "funding_benefit_kind_valid"),
        ("benefit", {"period": "WEEKLY"}, "funding_benefit_period_valid"),
        (
            "benefit",
            {"currency": None},
            "funding_benefit_amount_currency_pair",
        ),
        (
            "benefit",
            {"amount": None},
            "funding_benefit_amount_currency_pair",
        ),
        (
            "benefit",
            {"amount": "-0.01"},
            "funding_benefit_amount_nonnegative",
        ),
        (
            "benefit",
            {"currency": "ZZZ"},
            "funding_benefit_currency_iso4217",
        ),
        (
            "benefit",
            {"currency": "CUC"},
            "funding_benefit_currency_iso4217",
        ),
        (
            "benefit",
            {"currency": "HRK"},
            "funding_benefit_currency_iso4217",
        ),
        (
            "benefit",
            {"currency": "BGN"},
            "funding_benefit_currency_iso4217",
        ),
        (
            "benefit",
            {"currency": "ANG"},
            "funding_benefit_currency_iso4217",
        ),
        ("cost", {"kind": "UNKNOWN"}, "cost_component_kind_valid"),
        (
            "cost",
            {"amount": "-0.01"},
            "cost_component_amount_nonnegative",
        ),
        (
            "cost",
            {"currency": "ZZZ"},
            "cost_component_currency_iso4217",
        ),
        (
            "cost",
            {"currency": "CUC"},
            "cost_component_currency_iso4217",
        ),
        (
            "cost",
            {"currency": "HRK"},
            "cost_component_currency_iso4217",
        ),
        (
            "cost",
            {"currency": "BGN"},
            "cost_component_currency_iso4217",
        ),
        (
            "cost",
            {"currency": "ANG"},
            "cost_component_currency_iso4217",
        ),
        ("cost", {"period": "WEEKLY"}, "cost_component_period_valid"),
        ("rule", {"kind": "UNKNOWN"}, "benefit_rule_kind_valid"),
        ("rule", {"scope_type": "REGION"}, "benefit_rule_scope_type_valid"),
        (
            "rule",
            {"scope_type": "COUNTRY"},
            "benefit_rule_scope_shape_valid",
        ),
        (
            "rule",
            {"country_code": "AZ"},
            "benefit_rule_scope_shape_valid",
        ),
        (
            "rule",
            {"scope_type": "GLOBAL", "program_id": "__program__"},
            "benefit_rule_scope_shape_valid",
        ),
        (
            "rule",
            {"scope_type": "COUNTRY", "country_code": "ZZ"},
            "benefit_rule_country_iso3166_alpha2",
        ),
        ("source", {"source_type": "BLOG"}, "official_source_type_valid"),
        (
            "source",
            {"canonical_url": "http://example.test"},
            "official_source_url_https",
        ),
        (
            "claim",
            {"evidence_strength": "WEAK"},
            "official_claim_strength_valid",
        ),
        (
            "claim",
            {"visibility": "PUBLIC"},
            "official_claim_visibility_valid",
        ),
        (
            "claim",
            {"evidence_strength": "ECOSYSTEM_CLUE"},
            "official_claim_clue_internal_only",
        ),
        ("profile", {"version": 0}, "profile_version_positive"),
        ("profile", {"schema_version": 4}, "profile_schema_version_valid"),
    ],
)
def test_every_named_catalog_and_profile_constraint(
    constrained_rows, key, overrides, constraint
) -> None:
    tables = {
        "institution": "public.funding_institution",
        "program": "public.funding_program",
        "opportunity": "public.funding_fundingopportunity",
        "benefit": "public.funding_fundingbenefit",
        "cost": "public.funding_costcomponent",
        "rule": "public.funding_benefitrule",
        "source": "public.funding_officialsource",
        "claim": "public.funding_officialevidenceclaim",
        "profile": "public.accounts_studentprofileversion",
    }
    resolved = {
        field: constrained_rows[value.removeprefix("__").removesuffix("__")]
        if isinstance(value, str) and value.startswith("__") and value.endswith("__")
        else value
        for field, value in overrides.items()
    }
    _assert_insert_constraint(
        tables[key],
        constrained_rows[key],
        resolved,
        constraint,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("key", ["benefit", "cost"])
def test_money_precision_accepts_maximum_and_rejects_overflow(constrained_rows, key) -> None:
    table = {
        "benefit": "public.funding_fundingbenefit",
        "cost": "public.funding_costcomponent",
    }[key]
    _clone_insert(table, constrained_rows[key], {"amount": "999999999999.99"})
    with pytest.raises(DataError), transaction.atomic():
        _clone_insert(table, constrained_rows[key], {"amount": "1000000000000.00"})


@pytest.mark.django_db
def test_opportunity_program_endpoint_pair_is_unique(constrained_rows) -> None:
    catalog = _models()
    catalog.FundingOpportunityProgram.objects.create(
        opportunity_id=constrained_rows["opportunity"],
        program_id=constrained_rows["program"],
    )
    with pytest.raises(IntegrityError) as caught, transaction.atomic():
        catalog.FundingOpportunityProgram.objects.create(
            opportunity_id=constrained_rows["opportunity"],
            program_id=constrained_rows["program"],
        )
    assert caught.value.__cause__.diag.constraint_name == "opportunity_program_pair_uniq"


@pytest.mark.django_db
@pytest.mark.parametrize("statement", ["UPDATE", "DELETE"])
def test_profile_history_is_append_only(constrained_rows, statement) -> None:
    sql = (
        "UPDATE public.accounts_studentprofileversion SET snapshot = '{}'::jsonb WHERE id = %s"
        if statement == "UPDATE"
        else "DELETE FROM public.accounts_studentprofileversion WHERE id = %s"
    )
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql, [constrained_rows["profile"]])
