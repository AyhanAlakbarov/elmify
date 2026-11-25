import datetime as dt
from uuid import uuid4

import pytest

from apps.funding.models import (
    BenefitRule,
    EvidenceStrength,
    EvidenceVisibility,
    Institution,
    OfficialEvidenceClaim,
    OfficialSource,
    Program,
    ProgramEvidenceClaim,
)
from apps.research.spine import _program_deadline_candidates, build_student_pack

pytestmark = pytest.mark.django_db


def test_program_deadline_candidates_matches_residence_ch_eea_regions_and_negations() -> None:
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}",
        name="Example University",
        country_code="DE",
        official_website="https://university.example.org",
    )
    program = Program.objects.create(
        institution=institution,
        canonical_key=f"program:{uuid4()}",
        name="MSc Data Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE-MUNICH",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    source = OfficialSource.objects.create(
        canonical_url="https://university.example.org/deadlines",
        publisher="university.example.org",
        source_type=OfficialSource.Type.UNIVERSITY,
    )
    for dl_iso, label in (
        ("2027-03-01", "Applicants from outside the EU/EEA"),
        ("2027-05-15", "EU/EEA and Swiss citizens"),
        ("2027-06-01", "Residents of Germany"),
    ):
        claim = OfficialEvidenceClaim.objects.create(
            source=source,
            claim=f"Application deadline: {dl_iso}: {label}",
            evidence_strength=EvidenceStrength.DIRECT,
            visibility=EvidenceVisibility.STUDENT_FACING,
            claim_class=OfficialEvidenceClaim.ClaimClass.DEADLINE,
            last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
        ProgramEvidenceClaim.objects.create(program=program, evidence_claim=claim)

    # 1. Azerbaijani student residing in Azerbaijan matches "outside the EU/EEA" (priority 0)
    az_dls = _program_deadline_candidates((program,), "AZ", "AZ")[program.id]
    assert (0, dt.date(2027, 3, 1)) in az_dls
    assert (2, dt.date(2027, 5, 15)) in az_dls
    assert (2, dt.date(2027, 6, 1)) in az_dls

    # 2. Swiss (CH) student matches "EU/EEA and Swiss citizens" (priority 0) and is excluded
    # from "outside the EU/EEA" (priority 2)
    ch_dls = _program_deadline_candidates((program,), "CH", "CH")[program.id]
    assert (0, dt.date(2027, 5, 15)) in ch_dls
    assert (2, dt.date(2027, 3, 1)) in ch_dls

    # 3. Azerbaijani student residing in Germany matches "Residents of Germany" (priority 0)
    az_in_de_dls = _program_deadline_candidates((program,), "AZ", "DE")[program.id]
    assert (0, dt.date(2027, 6, 1)) in az_in_de_dls


def test_program_deadline_candidates_parses_catalog_and_scraper_formats() -> None:
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}",
        name="Example University",
        country_code="DE",
        official_website="https://university.example.org",
    )
    program = Program.objects.create(
        institution=institution,
        canonical_key=f"program:{uuid4()}",
        name="MSc Computer Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE-MUNICH",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    source = OfficialSource.objects.create(
        canonical_url="https://university.example.org/cs-deadlines",
        publisher="university.example.org",
        source_type=OfficialSource.Type.UNIVERSITY,
    )
    for claim_str in (
        "application_deadline: 2027-04-01 — Applicants from outside the EU/EEA",
        "Application Deadline: 2027-04-15 - EU/EEA citizens",
        "Application Deadline: Applications close on 2027-01-15",
        (
            "application_deadline: date stated but not read reliably"
            " — Applications close on 10 February 2027"
        ),
    ):
        claim = OfficialEvidenceClaim.objects.create(
            source=source,
            claim=claim_str,
            evidence_strength=EvidenceStrength.DIRECT,
            visibility=EvidenceVisibility.STUDENT_FACING,
            claim_class=OfficialEvidenceClaim.ClaimClass.DEADLINE,
            last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
        ProgramEvidenceClaim.objects.create(program=program, evidence_claim=claim)

    az_dls = _program_deadline_candidates((program,), "AZ", "AZ")[program.id]
    assert (0, dt.date(2027, 4, 1)) in az_dls
    assert (2, dt.date(2027, 4, 15)) in az_dls
    assert (1, dt.date(2027, 1, 15)) in az_dls
    assert (1, dt.date(2027, 2, 10)) in az_dls


def test_build_student_pack_loads_programme_scoped_benefit_rules() -> None:
    from tests.funding.conftest import EUR_RATES, make_profile

    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}",
        name="Technical University",
        country_code="DE",
        official_website="https://tu.example.de",
    )
    program = Program.objects.create(
        institution=institution,
        canonical_key=f"program:{uuid4()}",
        name="MSc Computer Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE-MUNICH",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    source = OfficialSource.objects.create(
        canonical_url="https://tu.example.de/msc-cs",
        publisher="tu.example.de",
        source_type=OfficialSource.Type.UNIVERSITY,
    )
    claim = OfficialEvidenceClaim.objects.create(
        source=source,
        claim="Minimum GPA 3.5/4.0 required for admission",
        evidence_strength=EvidenceStrength.DIRECT,
        visibility=EvidenceVisibility.STUDENT_FACING,
        claim_class=OfficialEvidenceClaim.ClaimClass.ELIGIBILITY,
        last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    )
    ProgramEvidenceClaim.objects.create(program=program, evidence_claim=claim)
    BenefitRule.objects.create(
        program=program,
        benefit=None,
        scope_type=BenefitRule.Scope.PROGRAM,
        kind=BenefitRule.Kind.ELIGIBILITY,
        key="GRADE",
        operator="GTE",
        value="3.5/4.0",
        rule_text="Minimum GPA 3.5/4.0 required",
    )

    student_profile = make_profile()
    result = build_student_pack(
        student_profile, rates=EUR_RATES, today=dt.date(2026, 10, 1)
    )
    facts = result.program_facts.get(str(program.id))
    assert facts is not None
    assert any(
        c.key == "GRADE" and c.value == "3.5/4.0" for c in facts.applicant_conditions
    )
