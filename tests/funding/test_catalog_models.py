from decimal import Decimal
from hashlib import sha256

import pytest
from django.db import IntegrityError, models, transaction
from django.db.models.deletion import PROTECT
from django.utils import timezone

from apps.funding.models import (
    CatalogWriteBlocked,
    OfficialSource,
    OfficialSourceSnapshot,
    update_exactly,
)


def _catalog():
    from apps import funding
    from apps.funding import models as catalog

    assert funding is not None
    return catalog


def _choice_values(model: type[models.Model], field: str) -> set[str]:
    return {value for value, _label in model._meta.get_field(field).choices}


def test_catalog_choice_contracts_are_exact() -> None:
    catalog = _catalog()
    expected = {
        (catalog.FundingOpportunity, "family"): {
            "GOVERNMENT_SCHOLARSHIP",
            "MULTILATERAL",
            "INDUSTRIAL_SPONSORSHIP",
            "UNIVERSITY_WIDE",
            "DEPARTMENT_OR_PROGRAM",
            "TUITION_WAIVER",
            "STIPEND_OR_ASSISTANTSHIP",
            "RELOCATION_HOUSING_INSURANCE_TRAVEL",
            "RESEARCH_ECOSYSTEM_PATHWAY",
            "AFFINITY_OR_DIASPORA",
            "PRIVATE_FOUNDATION",
        },
        (catalog.FundingOpportunity, "scope_type"): {
            "GLOBAL",
            "COUNTRY",
            "INSTITUTION",
            "PROGRAM",
            # An award anchored to the organisation that holds the money,
            # by registrable domain (2026-09-18 holder axis).
            "HOLDER",
        },
        (catalog.OfficialEvidenceClaim, "evidence_strength"): {
            "DIRECT",
            "COMPETITIVE",
            "FORMAL_PIPELINE",
            "ECOSYSTEM_CLUE",
        },
        (catalog.OfficialEvidenceClaim, "visibility"): {
            "INTERNAL",
            "STUDENT_FACING",
        },
        (catalog.FundingBenefit, "kind"): {
            "TUITION",
            "STIPEND",
            "ASSISTANTSHIP",
            "HOUSING",
            "INSURANCE",
            "TRAVEL",
            "RELOCATION",
            "OTHER",
        },
        (catalog.CostComponent, "kind"): {
            "TUITION",
            "APPLICATION_FEE",
            "HOUSING",
            "FOOD",
            "TRANSPORT",
            "UTILITIES",
            "INSURANCE",
            "OTHER",
        },
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
            "LANGUAGE",
            "GUARANTOR",
        },
        (catalog.BenefitRule, "comparable_unit"): {
            "MONTHS",
            "HOURS",
        },
        (catalog.BenefitRule, "scope_type"): {
            "GLOBAL",
            "COUNTRY",
            "CITY",
            "PROGRAM",
        },
        (catalog.OfficialSource, "source_type"): {
            "UNIVERSITY",
            "PROGRAM",
            "SCHOLARSHIP",
            "GOVERNMENT",
            "IMMIGRATION",
            "REGULATOR",
            "FUNDER",
            "RESEARCH_ORGANIZATION",
            "MUNICIPAL",
            "STUDENT_SERVICE",
            "OFFICIAL_STATISTICS",
        },
    }
    periods = {"ONE_OFF", "MONTHLY", "ANNUAL", "FULL_PROGRAM"}
    expected[(catalog.FundingBenefit, "period")] = periods
    expected[(catalog.CostComponent, "period")] = periods
    for (model, field), values in expected.items():
        assert _choice_values(model, field) == values


def test_reference_data_is_frozen_pinned_and_self_verifying() -> None:
    from apps import reference_data

    assert isinstance(reference_data.ISO_3166_ALPHA2_CODES, frozenset)
    assert isinstance(reference_data.ISO_4217_CODES, frozenset)
    assert {"AZ", "DE", "FR"} <= reference_data.ISO_3166_ALPHA2_CODES
    assert {"EUR", "USD", "AZN", "XAD", "XCG"} <= reference_data.ISO_4217_CODES
    assert {"ANG", "BGN", "CUC", "HRK"}.isdisjoint(reference_data.ISO_4217_CODES)
    assert {"ZZ", "ZZZ"}.isdisjoint(
        reference_data.ISO_3166_ALPHA2_CODES | reference_data.ISO_4217_CODES
    )
    metadata = tuple(vars(reference_data).values())
    assert "2026-08-12" in metadata
    assert (
        sha256("\n".join(sorted(reference_data.ISO_3166_ALPHA2_CODES)).encode()).hexdigest()
        in metadata
    )
    assert sha256("\n".join(sorted(reference_data.ISO_4217_CODES)).encode()).hexdigest() in metadata
    assert "https://www.iso.org/standard/72482.html" in metadata
    assert "https://www.iso.org/obp/ui/#iso:std:iso:3166:-1:ed-4:v1:en" in metadata
    assert "ISO 3166-1:2020; OBP edition 4" in metadata
    assert (
        "https://www.six-group.com/dam/download/financial-information/data-center/"
        "iso-currrency/lists/list-one.xml"
    ) in metadata
    assert "List one through Amendment 180 effective 2026-01-01" in metadata
    assert reference_data.ISO_4217_STATUS_NOTES == (
        "Amendment 174: HRK historical effective 2023-01-01",
        "Amendment 178: CUC historical",
        "Amendment 179: XAD effective 2025-05-12",
        "Amendment 180: ANG and BGN historical effective 2026-01-01; XCG active",
    )


def test_shared_catalog_has_no_tenant_and_only_named_relationships() -> None:
    catalog = _catalog()
    shared = (
        catalog.Institution,
        catalog.Program,
        catalog.FundingOpportunity,
        catalog.FundingBenefit,
        catalog.CostComponent,
        catalog.BenefitRule,
        catalog.OfficialSource,
        catalog.OfficialEvidenceClaim,
    )
    for model in shared:
        assert "tenant" not in {field.name for field in model._meta.get_fields()}
    assert "programs" in {field.name for field in catalog.FundingOpportunity._meta.get_fields()}
    for forbidden in ("Decision", "PackItem"):
        assert not hasattr(catalog, forbidden)


@pytest.mark.parametrize(
    ("through_name", "owner_name", "m2m_name", "fields", "table", "constraint"),
    [
        (
            "InstitutionEvidenceClaim",
            "Institution",
            "evidence_claims",
            ("institution", "evidence_claim"),
            "funding_institution_evidence_claims",
            "institution_evidence_pair_uniq",
        ),
        (
            "ProgramEvidenceClaim",
            "Program",
            "evidence_claims",
            ("program", "evidence_claim"),
            "funding_program_evidence_claims",
            "program_evidence_pair_uniq",
        ),
        (
            "FundingOpportunityProgram",
            "FundingOpportunity",
            "programs",
            ("opportunity", "program"),
            "funding_fundingopportunity_programs",
            "opportunity_program_pair_uniq",
        ),
        (
            "FundingOpportunityEvidenceClaim",
            "FundingOpportunity",
            "evidence_claims",
            ("opportunity", "evidence_claim"),
            "funding_fundingopportunity_evidence_claims",
            "opportunity_evidence_pair_uniq",
        ),
        (
            "FundingBenefitEvidenceClaim",
            "FundingBenefit",
            "evidence_claims",
            ("benefit", "evidence_claim"),
            "funding_fundingbenefit_evidence_claims",
            "benefit_evidence_pair_uniq",
        ),
        (
            "CostComponentEvidenceClaim",
            "CostComponent",
            "evidence_claims",
            ("cost_component", "evidence_claim"),
            "funding_costcomponent_evidence_claims",
            "cost_component_evidence_pair_uniq",
        ),
        (
            "BenefitRuleEvidenceClaim",
            "BenefitRule",
            "evidence_claims",
            ("benefit_rule", "evidence_claim"),
            "funding_benefitrule_evidence_claims",
            "benefit_rule_evidence_pair_uniq",
        ),
    ],
)
def test_explicit_through_contract(
    through_name, owner_name, m2m_name, fields, table, constraint
) -> None:
    catalog = _catalog()
    through = getattr(catalog, through_name)
    relation = getattr(catalog, owner_name)._meta.get_field(m2m_name)
    assert relation.remote_field.through is through
    assert relation.remote_field.through_fields == fields
    assert through._meta.db_table == table
    assert tuple(field.name for field in through._meta.fields if not field.primary_key) == fields
    assert all(through._meta.get_field(name).remote_field.on_delete is PROTECT for name in fields)
    assert any(
        isinstance(item, models.UniqueConstraint)
        and item.name == constraint
        and item.fields == fields
        for item in through._meta.constraints
    )


def test_every_catalog_foreign_key_is_protect() -> None:
    catalog = _catalog()
    for model_name in (
        "Program",
        "FundingOpportunity",
        "FundingBenefit",
        "CostComponent",
        "BenefitRule",
        "OfficialEvidenceClaim",
        "InstitutionEvidenceClaim",
        "ProgramEvidenceClaim",
        "FundingOpportunityProgram",
        "FundingOpportunityEvidenceClaim",
        "FundingBenefitEvidenceClaim",
        "CostComponentEvidenceClaim",
        "BenefitRuleEvidenceClaim",
    ):
        for field in getattr(catalog, model_name)._meta.fields:
            if isinstance(field, models.ForeignKey):
                assert field.remote_field.on_delete is PROTECT


def test_current_personalized_relationships_are_exact() -> None:
    from apps.accounts.models import StudentProfileVersion
    from apps.funding.models import (
        Approval,
        AuditEvent,
        PackCandidate,
        PackVersion,
        RecommendationCandidate,
        RecommendationRun,
        StudentDecision,
    )
    from apps.tenancy.models import Membership

    expected = (
        (StudentProfileVersion, "student", Membership),
        (RecommendationRun, "profile_version", StudentProfileVersion),
        (RecommendationCandidate, "run", RecommendationRun),
        (PackVersion, "run", RecommendationRun),
        (PackCandidate, "pack_version", PackVersion),
        (PackCandidate, "candidate", RecommendationCandidate),
        (StudentDecision, "candidate", RecommendationCandidate),
        (StudentDecision, "actor", Membership),
        (Approval, "object_version", PackVersion),
        (Approval, "actor", Membership),
        (AuditEvent, "actor", Membership),
    )
    for model, field_name, related_model in expected:
        field = model._meta.get_field(field_name)
        assert isinstance(field, models.ForeignKey)
        assert field.remote_field.model is related_model


def test_money_and_language_columns_have_exact_database_shapes() -> None:
    catalog = _catalog()
    for model in (catalog.FundingBenefit, catalog.CostComponent):
        amount = model._meta.get_field("amount")
        assert isinstance(amount, models.DecimalField)
        assert (amount.max_digits, amount.decimal_places) == (14, 2)
    languages = catalog.Program._meta.get_field("teaching_languages")
    assert languages.base_field.max_length == 100


@pytest.fixture
def statement_rows(db):
    catalog = _catalog()
    institution = catalog.Institution.objects.create(
        canonical_key="institution:competency",
        name="Example University",
        country_code="DE",
        official_website="https://university.example.test",
    )
    program = catalog.Program.objects.create(
        institution=institution,
        canonical_key="program:chemistry-competency",
        name="MSc Chemistry",
        campus_name="Main Campus",
        city="Berlin",
        country_code="DE",
        location_key="de:berlin",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    source = catalog.OfficialSource.objects.create(
        canonical_url="https://official.example/programme-competency",
        publisher="Official University",
        source_type=catalog.OfficialSource.Type.PROGRAM,
    )
    snapshot = catalog.OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key="official-sources/programme-competency",
        s3_version_id="1",
        sha256="a" * 64,
        final_url=source.canonical_url,
        redirect_chain=[],
        retrieved_at=timezone.now(),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=1,
    )
    return catalog, program, snapshot


@pytest.mark.django_db
def test_two_statements_may_share_a_label(statement_rows) -> None:
    """Identity is the sentence. "Mathematics" from the degree requirement and
    "Mathematics" from the screening test are two statements with one label."""
    catalog, program, snapshot = statement_rows
    for text in ("A degree in Mathematics.", "The test covers mathematics."):
        catalog.ProgramStatement.objects.create(
            program=program,
            snapshot=snapshot,
            kind=catalog.ProgramStatement.Kind.COMPETENCY,
            requirement=catalog.ProgramStatement.Requirement.REQUIRED,
            text=text,
            label="Mathematics",
        )
    assert catalog.ProgramStatement.objects.filter(program=program).count() == 2


@pytest.mark.django_db
def test_a_statement_requirement_must_be_a_known_level(statement_rows) -> None:
    catalog, program, snapshot = statement_rows
    with pytest.raises(IntegrityError):
        catalog.ProgramStatement.objects.create(
            program=program, snapshot=snapshot, kind="COMPETENCY",
            requirement="MANDATORY", text="y", label="x",
        )


@pytest.mark.django_db
def test_a_statement_kind_must_be_a_known_kind(statement_rows) -> None:
    catalog, program, snapshot = statement_rows
    with pytest.raises(IntegrityError):
        catalog.ProgramStatement.objects.create(
            program=program, snapshot=snapshot, kind="RUMOUR",
            requirement="REQUIRED", text="y", label="x",
        )


@pytest.fixture
def catalog_rows(db):
    catalog = _catalog()
    institution = catalog.Institution.objects.create(
        canonical_key="institution:example",
        name="Example University",
        country_code="DE",
        official_website="https://university.example.test",
    )
    program = catalog.Program.objects.create(
        institution=institution,
        canonical_key="program:chemistry",
        name="MSc Chemistry",
        campus_name="Main Campus",
        city="Berlin",
        country_code="DE",
        location_key="de:berlin",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    other_program = catalog.Program.objects.create(
        institution=institution,
        canonical_key="program:physics",
        name="MSc Physics",
        campus_name="Main Campus",
        city="Berlin",
        country_code="DE",
        location_key="de:berlin",
        degree_level="MASTER",
        teaching_languages=["German"],
        duration_months=24,
    )
    opportunity = catalog.FundingOpportunity.objects.create(
        canonical_key="funding:example",
        name="Example Scholarship",
        family="GOVERNMENT_SCHOLARSHIP",
        scope_type="COUNTRY",
        country_code="DE",
    )
    benefit = catalog.FundingBenefit.objects.create(
        opportunity=opportunity,
        kind="TUITION",
        amount=Decimal("1000.00"),
        currency="EUR",
        period="ANNUAL",
        description="Tuition contribution",
    )
    source = catalog.OfficialSource.objects.create(
        canonical_url="https://official.example.test/funding",
        publisher="Example Ministry",
        source_type="GOVERNMENT",
    )
    claim = catalog.OfficialEvidenceClaim.objects.create(
        source=source,
        claim="Funding is competitive.",
        evidence_strength="COMPETITIVE",
        visibility="STUDENT_FACING",
        last_checked_at=timezone.now(),
    )
    return catalog, institution, program, other_program, opportunity, benefit, claim


@pytest.mark.django_db
def test_opportunity_allowlist_modes_store_only_explicit_relationships(catalog_rows) -> None:
    catalog, _institution, program, other, opportunity, _benefit, _claim = catalog_rows
    assert opportunity.programs.count() == 0
    catalog.FundingOpportunityProgram.objects.create(opportunity=opportunity, program=program)
    catalog.FundingOpportunityProgram.objects.create(opportunity=opportunity, program=other)
    assert set(opportunity.programs.values_list("id", flat=True)) == {
        program.id,
        other.id,
    }
    assert opportunity.scope_type == "COUNTRY"


@pytest.mark.django_db
@pytest.mark.parametrize("currency", ["XAD", "XCG"])
def test_active_currency_is_accepted(catalog_rows, currency) -> None:
    catalog, _institution, program, _other, opportunity, _benefit, _claim = catalog_rows
    catalog.FundingBenefit.objects.create(
        opportunity=opportunity,
        kind="STIPEND",
        amount=Decimal("100.00"),
        currency=currency,
        period="ONE_OFF",
        description="Development bank unit of account",
    )
    catalog.CostComponent.objects.create(
        program=program,
        kind="OTHER",
        amount=Decimal("100.00"),
        currency=currency,
        period="ONE_OFF",
    )
    assert opportunity.country_code == "DE"


@pytest.mark.django_db
def test_rule_accepts_intersecting_and_disjoint_stored_scopes(catalog_rows) -> None:
    catalog, _institution, program, other, _opportunity, benefit, _claim = catalog_rows
    catalog.FundingOpportunityProgram.objects.create(
        opportunity_id=benefit.opportunity_id, program=program
    )
    intersecting = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="ELIGIBILITY",
        rule_text="Program-specific",
        scope_type="PROGRAM",
        program=program,
    )
    disjoint = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="ELIGIBILITY",
        rule_text="Stored but not applicable",
        scope_type="PROGRAM",
        program=other,
    )
    assert intersecting.program_id == program.id
    assert disjoint.program_id == other.id
    assert not {
        "compatible",
        "derived_country_code",
        "derived_institution_id",
    } & {field.name for field in catalog.BenefitRule._meta.get_fields()}


@pytest.mark.django_db
def test_catalog_facts_are_mutable_but_canonical_key_is_stable(catalog_rows) -> None:
    catalog, _institution, program, _other, opportunity, _benefit, _claim = catalog_rows
    catalog.Program.objects.filter(id=program.id).update(location_key="de:hamburg")
    catalog.FundingOpportunity.objects.filter(id=opportunity.id).update(country_code="FR")
    program.refresh_from_db()
    opportunity.refresh_from_db()
    assert (program.canonical_key, program.location_key) == (
        "program:chemistry",
        "de:hamburg",
    )
    assert (opportunity.canonical_key, opportunity.country_code) == (
        "funding:example",
        "FR",
    )


@pytest.mark.django_db
def test_catalog_tables_have_no_user_defined_mutation_triggers() -> None:
    with transaction.get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT tgname
              FROM pg_trigger
             WHERE tgrelid = ANY(%s::regclass[])
               AND NOT tgisinternal
            """,
            [
                [
                    "public.funding_institution",
                    "public.funding_program",
                    "public.funding_fundingopportunity",
                    "public.funding_fundingbenefit",
                    "public.funding_costcomponent",
                    "public.funding_benefitrule",
                    "public.funding_officialsource",
                    "public.funding_officialevidenceclaim",
                    "public.funding_institution_evidence_claims",
                    "public.funding_program_evidence_claims",
                    "public.funding_fundingopportunity_programs",
                    "public.funding_fundingopportunity_evidence_claims",
                    "public.funding_fundingbenefit_evidence_claims",
                    "public.funding_costcomponent_evidence_claims",
                    "public.funding_benefitrule_evidence_claims",
                ]
            ],
        )
        assert cursor.fetchall() == []


@pytest.mark.django_db
def test_provenance_cannot_be_deleted_while_referenced(catalog_rows) -> None:
    catalog, institution, _program, _other, _opportunity, _benefit, claim = catalog_rows
    catalog.InstitutionEvidenceClaim.objects.create(institution=institution, evidence_claim=claim)
    with pytest.raises(IntegrityError), transaction.atomic():
        with transaction.get_connection().cursor() as cursor:
            cursor.execute(
                "DELETE FROM public.funding_officialevidenceclaim WHERE id = %s",
                [claim.id],
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.django_db
def test_family_check_constraint_accepts_the_two_2026_08_29_families() -> None:
    """AFFINITY_OR_DIASPORA keys eligibility to descent, not citizenship (AGBU funds
    students "of Armenian descent" worldwide); PRIVATE_FOUNDATION holds party
    Stiftungen and education foundations like TEV. The DB check constraint has to
    admit both, not only the model's choices list.
    """
    catalog = _catalog()
    for family in ("AFFINITY_OR_DIASPORA", "PRIVATE_FOUNDATION"):
        opportunity = catalog.FundingOpportunity.objects.create(
            canonical_key=f"funding:{family.lower()}",
            name=f"Example {family}",
            family=family,
            scope_type="GLOBAL",
        )
        assert opportunity.family == family


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
    affiliation = catalog.BenefitRule.objects.create(
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
    assert affiliation.comparable_value is None
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


@pytest.mark.django_db
def test_a_language_bar_and_a_guarantor_requirement_are_storable(catalog_rows) -> None:
    """Neither carries a number, so both behave like AFFILIATION: the funder's sentence
    is the whole record, and evaluation routes them to a consultant."""
    catalog, _institution, _program, _other, _opportunity, benefit, _claim = catalog_rows

    language = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="LANGUAGE",
        rule_text="German at C1 level is required, including for programmes taught in "
        "English",
        scope_type="GLOBAL",
    )
    guarantor = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="GUARANTOR",
        rule_text="two guarantors resident in the country of study are required",
        scope_type="GLOBAL",
    )

    assert language.comparable_value is None
    assert guarantor.comparable_value is None


@pytest.mark.django_db
def test_an_experience_bar_can_be_stored_in_the_unit_the_funder_published(
    catalog_rows,
) -> None:
    """Chevening publishes 2,800 hours, ADB-JSP two years. Converting either into the
    other needs a working-hours-per-month figure no funder publishes."""
    catalog, _institution, _program, _other, _opportunity, benefit, _claim = catalog_rows

    hours = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="WORK_EXPERIENCE",
        comparable_value=Decimal("2800.00"),
        comparable_unit="HOURS",
        rule_text="at least 2,800 hours of work experience",
        scope_type="GLOBAL",
    )
    months = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="WORK_EXPERIENCE",
        comparable_value=Decimal("24.00"),
        comparable_unit="MONTHS",
        rule_text="at least two years of professional work experience",
        scope_type="GLOBAL",
    )

    assert hours.comparable_unit == "HOURS"
    assert months.comparable_unit == "MONTHS"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        # A unit on a condition whose unit is fixed claims a choice that does not exist.
        (
            {
                "kind": "APPLICANT_CONDITION",
                "condition_type": "AGE_CAP",
                "comparable_value": Decimal("35.00"),
                "comparable_unit": "HOURS",
            },
            "benefit_rule_comparable_unit_valid",
        ),
        # A unit with nothing to qualify is uninterpretable.
        (
            {
                "kind": "APPLICANT_CONDITION",
                "condition_type": "AFFILIATION",
                "comparable_unit": "MONTHS",
            },
            "benefit_rule_comparable_unit_valid",
        ),
    ],
)
def test_a_unit_outside_work_experience_is_rejected(catalog_rows, fields, constraint) -> None:
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


@pytest.mark.django_db
def test_a_half_loan_award_records_its_repayable_share_and_charge(catalog_rows) -> None:
    """AKF's International Scholarship Programme is half grant, half interest-free loan
    with a service charge. Recorded as a grant it overstates coverage by half."""
    catalog, _institution, _program, _other, opportunity, _benefit, _claim = catalog_rows

    award = catalog.FundingBenefit.objects.create(
        opportunity=opportunity,
        kind="TUITION",
        amount=Decimal("10000.00"),
        currency="USD",
        period="ANNUAL",
        description="Half grant, half loan",
        repayable_share=Decimal("0.50"),
        service_charge_text="a service charge is levied on the loan portion",
    )

    assert award.repayable_share == Decimal("0.50")
    assert "service charge" in award.service_charge_text


@pytest.mark.django_db
def test_a_repayable_share_outside_zero_to_one_is_rejected(catalog_rows) -> None:
    catalog, _institution, _program, _other, opportunity, _benefit, _claim = catalog_rows

    with pytest.raises(IntegrityError) as error, transaction.atomic():
        catalog.FundingBenefit.objects.create(
            opportunity=opportunity,
            kind="TUITION",
            period="ANNUAL",
            description="Impossible award",
            repayable_share=Decimal("1.50"),
        )
    assert "funding_benefit_repayable_share_fraction" in str(error.value)


@pytest.mark.django_db
def test_a_programme_can_record_an_undecided_format_and_page_directives(program_factory):
    program = program_factory(
        cv_format_confidence="UNDECIDED",
        cv_directives=[{
            "action": "include", "target": "education.ects_credits", "value": None,
            "rule_text": "State your ECTS credits.", "source_url": "https://official.example/msc",
        }],
    )
    program.refresh_from_db()
    assert program.cv_format_confidence == "UNDECIDED"
    assert program.cv_directives[0]["target"] == "education.ects_credits"


@pytest.mark.django_db
def test_a_snapshot_records_why_it_could_not_be_read():
    source = OfficialSource.objects.create(
        canonical_url="https://official.example/shell",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, s3_key="k", s3_version_id="1", sha256="0" * 64,
        final_url=source.canonical_url, redirect_chain=[], retrieved_at=timezone.now(),
        admissions_cycle="2027", content_type="text/html", byte_size=458_728,
        readability=OfficialSourceSnapshot.Readability.SHELL,
    )
    snapshot.refresh_from_db()
    assert snapshot.readability == OfficialSourceSnapshot.Readability.SHELL


def test_a_funding_opportunity_refuses_an_unknown_agreement_or_kind(db):
    from django.db import IntegrityError, transaction

    from apps.funding.models import FundingOpportunity

    with pytest.raises(IntegrityError), transaction.atomic():
        FundingOpportunity.objects.create(
            canonical_key="x", name="x", family="UNIVERSITY_WIDE", scope_type="GLOBAL",
            agreement="MAYBE",
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        FundingOpportunity.objects.create(
            canonical_key="y", name="y", family="UNIVERSITY_WIDE", scope_type="GLOBAL",
            kind="I9_UNKNOWN",
        )


def test_a_funding_opportunity_refuses_an_unknown_review(db):
    from django.db import IntegrityError, transaction

    from apps.funding.models import FundingOpportunity

    with pytest.raises(IntegrityError), transaction.atomic():
        FundingOpportunity.objects.create(
            canonical_key="r", name="r", family="UNIVERSITY_WIDE", scope_type="GLOBAL",
            review="MAYBE",
        )


@pytest.mark.django_db
def test_a_rule_belongs_to_a_benefit_or_a_programme_never_both_nor_neither(catalog_rows) -> None:
    """Valid in every other respect -- no condition_type, no comparable_value, a
    GLOBAL scope -- so benefit_rule_target_present is the only constraint that can
    reject it."""
    catalog, _institution, _program, _other, _opportunity, _benefit, _claim = catalog_rows

    with pytest.raises(IntegrityError) as error, transaction.atomic():
        catalog.BenefitRule.objects.create(
            benefit=None, program=None, kind="ELIGIBILITY",
            rule_text="Two years of experience.", scope_type="GLOBAL",
        )
    assert "benefit_rule_target_present" in str(error.value)


@pytest.mark.django_db
def test_the_database_refuses_a_key_outside_the_vocabulary(catalog_rows) -> None:
    """Valid in every other respect -- a real benefit, no condition_type, a valid
    operator -- so benefit_rule_key_valid is the only constraint that can reject
    it."""
    catalog, _institution, _program, _other, _opportunity, benefit, _claim = catalog_rows

    with pytest.raises(IntegrityError) as error, transaction.atomic():
        catalog.BenefitRule.objects.create(
            benefit=benefit, program=None, kind="ELIGIBILITY",
            key="NATIONALITY", operator="IN", value="AZ",
            rule_text="x", scope_type="GLOBAL",
        )
    assert "benefit_rule_key_valid" in str(error.value)


@pytest.mark.django_db
def test_the_database_refuses_an_operator_outside_the_vocabulary(catalog_rows) -> None:
    """Valid in every other respect -- a real benefit, no condition_type, a valid
    key -- so benefit_rule_operator_valid is the only constraint that can reject
    it."""
    catalog, _institution, _program, _other, _opportunity, benefit, _claim = catalog_rows

    with pytest.raises(IntegrityError) as error, transaction.atomic():
        catalog.BenefitRule.objects.create(
            benefit=benefit, program=None, kind="ELIGIBILITY",
            key="CITIZENSHIP", operator="MAYBE", value="AZ",
            rule_text="x", scope_type="GLOBAL",
        )
    assert "benefit_rule_operator_valid" in str(error.value)


@pytest.mark.django_db
def test_a_rule_may_belong_to_a_benefit_alone(catalog_rows) -> None:
    """benefit set, program null: an ordinary funding route condition."""
    catalog, _institution, _program, _other, _opportunity, benefit, _claim = catalog_rows
    rule = catalog.BenefitRule.objects.create(
        benefit=benefit, program=None, kind="ELIGIBILITY",
        rule_text="Open to applicants worldwide.", scope_type="GLOBAL",
    )
    rule.refresh_from_db()
    assert rule.benefit_id == benefit.id
    assert rule.program_id is None


@pytest.mark.django_db
def test_a_rule_may_belong_to_a_programme_alone(catalog_rows) -> None:
    """benefit null, program set: the programme's own admission condition -- no
    route to confuse it with, since there is no benefit."""
    catalog, _institution, program, _other, _opportunity, _benefit, _claim = catalog_rows
    rule = catalog.BenefitRule.objects.create(
        benefit=None, program=program, kind="ELIGIBILITY",
        rule_text="A completed bachelor's degree in a related field.", scope_type="PROGRAM",
    )
    rule.refresh_from_db()
    assert rule.benefit_id is None
    assert rule.program_id == program.id


def test_every_stored_condition_type_has_a_vocabulary_key(db) -> None:
    """The rename is a data migration; this pins that nothing was left behind.

    condition_type is never cleared (0039 fills key/operator from it and leaves
    it standing -- two DB constraints still require it for
    kind="APPLICANT_CONDITION"), so the guarantee is not "no row carries a
    legacy condition_type" but "no row carrying one is left with an empty key".
    One assertion is the whole guarantee: benefit_rule_condition_type_shape_valid
    makes condition_type non-null exactly when kind="APPLICANT_CONDITION", and
    benefit_rule_comparable_shape_valid admits only the six legacy values there,
    so a condition_type-keyed filter selects the same row set as this one.
    """
    from apps.funding.models import BenefitRule

    assert not BenefitRule.objects.filter(kind="APPLICANT_CONDITION", key="").exists()


@pytest.mark.django_db
def test_fill_keys_backfills_the_legacy_condition_types(catalog_rows) -> None:
    """Exercises 0039's fill_keys function against real rows, not an empty table --
    otherwise both assertions above pass vacuously until a much later task writes
    the first row, which is exactly the defect the previous task's review caught.

    All six legacy condition types, each built to the exact shape
    benefit_rule_comparable_shape_valid demands for it. AGE_CAP -> AGE/LTE is the
    mapping where a wrong answer inverts a real condition (a cap silently read as
    a floor); MEANS_TEST -> NEED/LTE is the only other shape needing a currency.
    The rest (WORK_EXPERIENCE, AFFILIATION, LANGUAGE, GUARANTOR) are pinned too,
    now that this table has turned out to be the authoritative one (fix round 1:
    it disagreed with evaluation.py's _LEGACY_KEYS on four of six operators).
    """
    import importlib

    from django.apps import apps as django_apps

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
    age_cap = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="AGE_CAP",
        comparable_value=Decimal("35.00"),
        rule_text="not more than 35 years old at the time of application",
        scope_type="GLOBAL",
    )
    means_test = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="MEANS_TEST",
        comparable_value=Decimal("50000.00"),
        comparable_currency="USD",
        rule_text="gross family income not exceeding USD 50,000 per annum",
        scope_type="GLOBAL",
    )
    affiliation = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="AFFILIATION",
        rule_text="applicants are expected to endorse the values of Christian Democracy",
        scope_type="GLOBAL",
    )
    language = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="LANGUAGE",
        rule_text="German at C1 level is required, including for programmes taught in "
        "English",
        scope_type="GLOBAL",
    )
    guarantor = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="GUARANTOR",
        rule_text="two guarantors resident in the country of study are required",
        scope_type="GLOBAL",
    )
    rows = (experience, age_cap, means_test, affiliation, language, guarantor)
    assert all(row.key == "" for row in rows)

    # 0042_condition_type_to_key: not importable by a normal `import` statement --
    # its module name starts with a digit -- so it is loaded by path instead. The
    # real app registry's get_model has the same (app_label, model_name) shape
    # the migration's frozen `apps` argument has, so it is a faithful stand-in.
    migration = importlib.import_module("apps.funding.migrations.0042_condition_type_to_key")
    migration.fill_keys(django_apps, None)

    for row in rows:
        row.refresh_from_db()
    assert (experience.key, experience.operator) == ("WORK_EXPERIENCE", "GTE")
    assert (age_cap.key, age_cap.operator) == ("AGE", "LTE")
    assert (means_test.key, means_test.operator) == ("NEED", "LTE")
    assert (affiliation.key, affiliation.operator) == ("AFFINITY", "PRESENT")
    assert (language.key, language.operator) == ("LANGUAGE", "PRESENT")
    assert (guarantor.key, guarantor.operator) == ("GUARANTOR", "PRESENT")
    # condition_type is untouched -- the migration fills key from it, never clears it.
    assert tuple(row.condition_type for row in rows) == (
        "WORK_EXPERIENCE", "AGE_CAP", "MEANS_TEST", "AFFILIATION", "LANGUAGE", "GUARANTOR",
    )


@pytest.mark.django_db
def test_clear_keys_undoes_only_what_fill_keys_wrote(catalog_rows) -> None:
    """clear_keys mirrors fill_keys's SELECTION, not just its column list: a row is
    only cleared if it matches the exact (condition_type, key, operator) triple
    fill_keys would have written for that condition_type.

    This cannot distinguish a hand-seeded row that happens to carry that same
    triple from one the backfill actually wrote -- unknowable in principle -- but
    it narrows the blast radius from "every legacy-typed row" to "rows
    indistinguishable from ones this backfill wrote", instead of wiping a row the
    forward pass deliberately skipped because it already carried its own key --
    exactly the fixture/hand-seeded case the migration's own docstring names as
    its reason to exist.
    """
    import importlib

    from django.apps import apps as django_apps

    catalog, _institution, _program, _other, _opportunity, benefit, _claim = catalog_rows

    written_by_forward = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="AGE_CAP",
        comparable_value=Decimal("35.00"),
        rule_text="not more than 35 years old at the time of application",
        scope_type="GLOBAL",
    )
    # A row a future writer already gave its own key/operator to -- skipped by
    # fill_keys's own `key=""` filter, so it must survive clear_keys too, even
    # though its condition_type is one of the six and its key is the same "AGE"
    # fill_keys would have chosen. Only the operator (GTE, a floor, not LTE, a
    # cap) differs, which is exactly the distinction clear_keys must respect.
    hand_seeded = catalog.BenefitRule.objects.create(
        benefit=benefit,
        kind="APPLICANT_CONDITION",
        condition_type="AGE_CAP",
        comparable_value=Decimal("40.00"),
        key="AGE",
        operator="GTE",
        rule_text="at least 40 years old to qualify for the emeritus track",
        scope_type="GLOBAL",
    )

    migration = importlib.import_module("apps.funding.migrations.0042_condition_type_to_key")
    migration.fill_keys(django_apps, None)
    written_by_forward.refresh_from_db()
    assert (written_by_forward.key, written_by_forward.operator) == ("AGE", "LTE")

    migration.clear_keys(django_apps, None)
    written_by_forward.refresh_from_db()
    hand_seeded.refresh_from_db()
    assert (written_by_forward.key, written_by_forward.operator) == ("", "")
    assert (hand_seeded.key, hand_seeded.operator) == ("AGE", "GTE")


def test_the_legacy_operator_table_agrees_with_the_migrations_backfill() -> None:
    """Two independent tables translate the same six pre-vocabulary condition
    types: apps/funding/evaluation.py::_LEGACY_KEYS, read by a live
    ApplicantConditionFact with no explicit key, and this migration's own _KEYS,
    read once by the backfill. They must agree, or a legacy row is decided
    differently depending on whether it went through the evaluator or the
    one-time migration -- exactly the divergence fix round 1 found (four of six
    operators disagreed). The migration is not imported into evaluation.py or
    vice versa on purpose: a migration importing live application code lets a
    later edit rewrite applied history, so the duplication stays and this test
    is what keeps the two sides honest.
    """
    import importlib

    from apps.funding.evaluation import _LEGACY_KEYS

    migration = importlib.import_module("apps.funding.migrations.0042_condition_type_to_key")
    assert migration._KEYS == _LEGACY_KEYS


@pytest.mark.django_db
def test_update_exactly_raises_when_no_row_matches() -> None:
    with pytest.raises(CatalogWriteBlocked, match="no rows"):
        update_exactly(
            OfficialSource.objects.filter(canonical_url="https://nowhere.example/missing"),
            error="catalog write affected no rows",
            publisher="Nobody",
        )


@pytest.mark.django_db
def test_update_exactly_writes_when_one_row_matches() -> None:
    source = OfficialSource.objects.create(
        canonical_url="https://official.example.test/update-exactly",
        publisher="Old Name",
        source_type=OfficialSource.Type.PROGRAM,
    )

    update_exactly(
        OfficialSource.objects.filter(pk=source.pk),
        error="catalog write affected no rows",
        publisher="New Name",
    )

    source.refresh_from_db()
    assert source.publisher == "New Name"
