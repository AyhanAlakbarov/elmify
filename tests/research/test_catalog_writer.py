from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.funding.models import (
    FundingOpportunity,
    Institution,
    InstitutionEvidenceClaim,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)
from apps.research.catalog import (
    ResolvedProgram,
    _money,
    claim_rows,
    date_is_readable,
    pool_claims,
    write_catalog_entry,
)
from apps.research.discovery import LeadIdentity, ResearchLead
from apps.research.extraction import (
    ExtractedClaims,
    FundingFamilyClaim,
    KeyDateClaim,
    MoneyClaim,
    TeachingLanguageClaim,
)

pytestmark = pytest.mark.django_db

SEED_IDENTITY = LeadIdentity(
    institution_name="University of Technology Nuremberg",
    country_code="DE",
    city="Nürnberg",
    program_name="AI & Robotics (MSc)",
)
CLAIMS = ExtractedClaims(
    duration_months=24,
    key_dates=(
        KeyDateClaim(
            kind="APPLICATION_DEADLINE",
            on=date(2027, 5, 31),
            evidence="The application deadline is May 31, 2027.",
        ),
    ),
    teaching_languages=(
        TeachingLanguageClaim(language="English", evidence="Taught entirely in English."),
    ),
    costs=(
        MoneyClaim(
            label="tuition", amount=Decimal("0.00"), currency="EUR", period="annual",
            evidence="Tuition fees are 0.00 EUR per year for this programme.",
        ),
    ),
    benefits=(
        MoneyClaim(
            label="stipend", amount=Decimal("934.00"), currency="EUR", period="monthly",
            evidence="A monthly stipend of 934.00 EUR is paid to scholars.",
        ),
    ),
    confidence=0.9,
)


@pytest.fixture
def source() -> OfficialSource:
    return OfficialSource.objects.create(
        canonical_url="https://www.utn.de/en/study/ai-robotics-en",
        publisher="www.utn.de",
        source_type=OfficialSource.Type.PROGRAM,
    )


@pytest.fixture
def snapshot(source: OfficialSource) -> OfficialSourceSnapshot:
    return OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key="official-sources/x",
        s3_version_id="1",
        sha256="b" * 64,
        final_url=source.canonical_url,
        redirect_chain=[],
        retrieved_at=timezone.now(),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=10,
        discovery_technique="seed:daad-ip",
    )


def _official_lead(**overrides: object) -> ResearchLead:
    return ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family=str(overrides.get("funding_family", "")),
        discovered_by="seed:daad-ip",
        identity=SEED_IDENTITY,
    )


def test_an_official_page_writes_identity_and_classified_claims(source, snapshot) -> None:
    result = write_catalog_entry(
        lead=_official_lead(), claims=CLAIMS, source=source, snapshot=snapshot
    )

    assert result is not None
    assert result.institution.name == "University of Technology Nuremberg"
    assert result.institution.official_website == "https://www.utn.de/"
    assert result.program.city == "Nürnberg"
    assert result.program.teaching_languages == ["English"]
    assert result.program.duration_months == 24
    assert {claim.claim_class for claim in result.claims} == {
        "IDENTITY",
        "STRUCTURE",
        "DEADLINE",
        "TUITION",
        "FUNDING",
    }
    assert all(claim.snapshot_id == snapshot.id for claim in result.claims)
    assert set(result.program.evidence_claims.all()) == set(result.claims)


def test_the_portfolio_contract_reaches_the_claim_table(source, snapshot) -> None:
    """Spec §12's page-level facts become evidence, each in its own class.

    A nomination-initiated track has to be visible as a claim, because it is
    the reason that route can never be the portfolio's floor.
    """
    from apps.research.extraction import (
        AdmissionRegimeClaim,
        CommitmentPaymentClaim,
        EligibilityCriterionClaim,
        FundingTrackClaim,
        KeyDateClaim,
    )

    claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
        admission_regime=AdmissionRegimeClaim(
            regime="RULE_BASED", evidence="Applicants meeting the stated bar receive an offer."
        ),
        eligibility_criteria=(
            EligibilityCriterionClaim(
                kind="GRADE",
                requirement="An upper second-class honours degree",
                evidence="Applicants need a 2:1 or equivalent.",
            ),
        ),
        commitment_payment=CommitmentPaymentClaim(
            kind="TUITION_DEPOSIT",
            amount=Decimal("2000.00"),
            currency="GBP",
            window_days=28,
            refundable=False,
            evidence="A deposit of £2,000 is payable within 28 days of the offer.",
        ),
        key_dates=(
            KeyDateClaim(
                kind="DECISION_DATE",
                decentralised=True,
                evidence="Each embassy announces results on its own schedule.",
            ),
        ),
        funding_tracks=(
            FundingTrackClaim(
                name="University nomination",
                initiation="INSTITUTION_NOMINATES",
                evidence="The university nominates candidates; students cannot apply.",
            ),
        ),
        confidence=0.9,
    )

    result = write_catalog_entry(
        lead=_official_lead(), claims=claims, source=source, snapshot=snapshot
    )

    assert result is not None
    by_class: dict[str, list[str]] = {}
    for claim in result.claims:
        by_class.setdefault(claim.claim_class, []).append(claim.claim)
    assert "ELIGIBILITY" in by_class
    assert "2:1" in by_class["ELIGIBILITY"][0]
    assert any("RULE_BASED" in text for text in by_class["STRUCTURE"])
    assert any("TUITION_DEPOSIT" in text for text in by_class["TUITION"])
    assert any("no central date" in text for text in by_class["DEADLINE"])
    assert any("INSTITUTION_NOMINATES" in text for text in by_class["FUNDING"])


def test_the_stipend_is_recorded_rather_than_dropped(source, snapshot) -> None:
    """A funding engine that records tuition but not funding is not one."""
    result = write_catalog_entry(
        lead=_official_lead(), claims=CLAIMS, source=source, snapshot=snapshot
    )

    assert result is not None
    funding = [claim for claim in result.claims if claim.claim_class == "FUNDING"]
    assert len(funding) == 1
    assert "934.00 EUR" in funding[0].claim
    assert "stipend" in funding[0].claim


def test_a_tracks_coverage_survives_into_the_claim_table(source, snapshot) -> None:
    """A field claim_rows does not emit is extracted and then discarded.

    'Unstated' must stay distinguishable from an explicit 'NO': the first is a
    gap to disclose, the second is a fact about the scheme.
    """
    from apps.research.extraction import FundingTrackClaim

    claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
        funding_tracks=(
            FundingTrackClaim(
                name="Embassy track",
                initiation="STUDENT_APPLIES_SEPARATELY",
                satisfies_financial_proof="YES",
                covers_commitment_payment="YES",
                evidence="The ministry pays the enrolment fee.",
            ),
            FundingTrackClaim(
                name="University track",
                initiation="INSTITUTION_NOMINATES",
                evidence="The university nominates candidates.",
            ),
        ),
        confidence=0.9,
    )

    result = write_catalog_entry(
        lead=_official_lead(), claims=claims, source=source, snapshot=snapshot
    )

    assert result is not None
    funding = [claim.claim for claim in result.claims if claim.claim_class == "FUNDING"]
    assert any("commitment payment YES" in text for text in funding)
    assert any("commitment payment UNSTATED" in text for text in funding)


def test_a_catalogue_lead_writes_nothing_at_all(source, snapshot) -> None:
    """Design §2.5's hard rule, at its strictest reading.

    DAAD says 'No tuition fees'; DAAD does not get to. And since a Program row
    is student-facing by construction, a lead that cannot support a claim does
    not get to create one either -- its names are useful only once the
    institution's own page has been read.
    """
    catalogue_lead = ResearchLead.from_url(
        "https://www2.daad.de/deutschland/studienangebote/international-programmes/en/detail/9894",
        source_type="AGGREGATOR",
        funding_family="",
        discovered_by="seed:daad-ip",
        identity=SEED_IDENTITY,
    )
    fee_claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
        costs=(
            MoneyClaim(
                label="No tuition fees", amount=Decimal("0.00"), currency="EUR", period="annual"
            ),
        ),
        confidence=0.9,
    )

    assert (
        write_catalog_entry(
            lead=catalogue_lead, claims=fee_claims, source=source, snapshot=snapshot
        )
        is None
    )
    assert OfficialEvidenceClaim.objects.count() == 0
    assert Program.objects.count() == 0
    assert Institution.objects.count() == 0


def test_an_ecosystem_clue_never_becomes_a_catalog_row(source, snapshot) -> None:
    """§2.3: clues stay internal until primary evidence upgrades them.

    An institute homepage describing itself is not a programme record, and a
    Program row has no way to say 'internal'.
    """
    clue = ResearchLead.from_url(
        "https://cbs.riken.jp/en/",
        source_type="RESEARCH_ORGANIZATION",
        funding_family="",
        evidence_strength="ECOSYSTEM_CLUE",
        discovered_by="entity-expansion",
    )
    claims = ExtractedClaims(
        institution_name="RIKEN Center for Brain Science",
        program_name="Graduate Program",
        city="Wako",
        country_code="JP",
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Programmes are in English."),
        ),
        confidence=0.9,
    )

    assert write_catalog_entry(lead=clue, claims=claims, source=source, snapshot=snapshot) is None
    assert Program.objects.count() == 0


def test_identity_can_come_from_the_page_when_no_catalogue_covers_the_corridor(
    source, snapshot
) -> None:
    lead = ResearchLead.from_url(
        "https://i.kyoto-u.ac.jp/en/admissions",
        source_type="PROGRAM",
        funding_family="",
        discovered_by="search",
    )
    claims = ExtractedClaims(
        institution_name="Kyoto University",
        program_name="Graduate School of Informatics",
        city="Kyoto",
        country_code="jp",  # lower case: normalized, not discarded
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Instruction is in English."),
        ),
        confidence=0.9,
    )

    result = write_catalog_entry(lead=lead, claims=claims, source=source, snapshot=snapshot)

    assert result is not None
    assert result.institution.country_code == "JP"
    assert result.program.name == "Graduate School of Informatics"


def test_the_cited_claim_wins_over_the_catalogue_for_anything_a_gate_reads(
    source, snapshot
) -> None:
    """§2.2 puts teaching-language enforcement on the cited claim.

    The catalogue's own language and duration fields are not carried at all
    (Task 3), so the only possible source for these columns is the page.
    """
    claims = ExtractedClaims(
        duration_months=18,
        teaching_languages=(
            TeachingLanguageClaim(
                language="German", evidence="Der Studiengang ist deutschsprachig."
            ),
        ),
        confidence=0.9,
    )

    result = write_catalog_entry(
        lead=_official_lead(), claims=claims, source=source, snapshot=snapshot
    )

    assert result is not None
    assert result.program.teaching_languages == ["German"]
    assert result.program.duration_months == 18


@pytest.mark.parametrize(
    "overrides",
    [
        {"institution_name": None},
        {"program_name": None},
        {"country_code": None},
        {"duration_months": None},
        {"teaching_languages": ()},
    ],
)
def test_incomplete_identity_writes_nothing(source, snapshot, overrides: dict) -> None:
    base = {
        "institution_name": "Kyoto University",
        "program_name": "Graduate School of Informatics",
        "city": "Kyoto",
        "country_code": "JP",
        "duration_months": 24,
        "teaching_languages": (
            TeachingLanguageClaim(language="English", evidence="In English."),
        ),
        "confidence": 0.9,
    }
    lead = ResearchLead.from_url(
        "https://i.kyoto-u.ac.jp/en/admissions", source_type="PROGRAM", funding_family=""
    )

    assert (
        write_catalog_entry(
            lead=lead,
            claims=ExtractedClaims(**(base | overrides)),
            source=source,
            snapshot=snapshot,
        )
        is None
    )
    assert Institution.objects.count() == 0


def test_the_same_programme_spelled_two_ways_is_one_row(source, snapshot) -> None:
    """The seed says Nürnberg; the university's own page says Nuremberg.

    Design §2.5 keys on (institution, programme name, degree level), so the
    city must not be part of the key.
    """
    first = write_catalog_entry(
        lead=_official_lead(), claims=CLAIMS, source=source, snapshot=snapshot
    )
    from_the_page = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en", source_type="PROGRAM", funding_family=""
    )
    page_claims = ExtractedClaims(
        institution_name="University of Technology Nuremberg",
        program_name="AI & Robotics (MSc)",
        city="Nuremberg",
        country_code="DE",
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught entirely in English."),
        ),
        confidence=0.9,
    )

    second = write_catalog_entry(
        lead=from_the_page, claims=page_claims, source=source, snapshot=snapshot
    )

    assert first is not None and second is not None
    assert first.program.id == second.program.id
    assert Institution.objects.count() == 1
    assert Program.objects.count() == 1


def test_the_pages_cited_family_beats_the_seeds_uncited_assertion(source, snapshot) -> None:
    """Whole-branch review Fix 4.

    The seed says MULTILATERAL (EACEA's own assertion, no citation attached).
    The institution's own page cites a different family with a verbatim
    quotation. The module's own rule -- 'claims beat seeds for anything a hard
    gate reads' -- must also hold for family, or the row is labelled on an
    aggregator's authority while every citation on it says something else.
    """
    claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught entirely in English."),
        ),
        funding_family=FundingFamilyClaim(
            family="GOVERNMENT_SCHOLARSHIP",
            evidence="The scholarship is funded by the federal ministry of education.",
        ),
        confidence=0.9,
    )

    result = write_catalog_entry(
        lead=_official_lead(funding_family="MULTILATERAL"),
        claims=claims,
        source=source,
        snapshot=snapshot,
    )

    assert result is not None
    assert result.opportunity is not None
    assert result.opportunity.family == "GOVERNMENT_SCHOLARSHIP"
    assert any(
        "federal ministry of education" in claim.claim
        for claim in result.opportunity.evidence_claims.all()
    )


def test_a_funding_opportunity_needs_a_stated_family(source, snapshot) -> None:
    result = write_catalog_entry(
        lead=_official_lead(), claims=CLAIMS, source=source, snapshot=snapshot
    )

    assert result is not None
    assert result.opportunity is None
    assert FundingOpportunity.objects.count() == 0


def test_a_family_stated_by_the_seed_or_cited_by_the_page_writes_the_opportunity(
    source, snapshot
) -> None:
    from_seed = write_catalog_entry(
        lead=_official_lead(funding_family="MULTILATERAL"),
        claims=CLAIMS,
        source=source,
        snapshot=snapshot,
    )

    assert from_seed is not None
    assert from_seed.opportunity is not None
    assert from_seed.opportunity.family == "MULTILATERAL"
    assert from_seed.opportunity.scope_type == "PROGRAM"
    assert from_seed.opportunity.program_id == from_seed.program.id

    cited = ExtractedClaims(
        institution_name="Kyoto University",
        program_name="Graduate School of Informatics",
        city="Kyoto",
        country_code="JP",
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="In English."),
        ),
        funding_family=FundingFamilyClaim(
            family="GOVERNMENT_SCHOLARSHIP",
            evidence="The scholarship is funded by the Ministry of Education.",
        ),
        confidence=0.9,
    )
    lead = ResearchLead.from_url(
        "https://i.kyoto-u.ac.jp/en/admissions", source_type="PROGRAM", funding_family=""
    )

    from_page = write_catalog_entry(
        lead=lead, claims=cited, source=source, snapshot=snapshot
    )

    assert from_page is not None
    assert from_page.opportunity is not None
    assert from_page.opportunity.family == "GOVERNMENT_SCHOLARSHIP"
    # The sentence that justified the family is itself evidence on the record.
    assert any(
        "Ministry of Education" in claim.claim
        for claim in from_page.opportunity.evidence_claims.all()
    )


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
    eligibility = [claim.claim for claim in result.claims if claim.claim_class == "ELIGIBILITY"]
    assert any("EXPERIENCE" in text and "[24]" in text for text in eligibility)
    assert any("MEANS_TEST" in text and "[50000 USD]" in text for text in eligibility)
    # No number to compare, and none invented: the quote travels alone.
    assert any("AFFILIATION" in text and "[" not in text for text in eligibility)


def test_a_bond_reaches_the_claim_table_as_funding_not_eligibility(source, snapshot) -> None:
    """A bond is a property of the award, not a bar the applicant clears."""
    from apps.research.extraction import ReturnServiceClaim

    claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
        return_service=ReturnServiceClaim(
            months=60, evidence="Graduates must work in Kazakhstan for five years."
        ),
        confidence=0.9,
    )

    result = write_catalog_entry(
        lead=_official_lead(), claims=claims, source=source, snapshot=snapshot
    )

    assert result is not None
    by_class: dict[str, list[str]] = {}
    for claim in result.claims:
        by_class.setdefault(claim.claim_class, []).append(claim.claim)
    assert any("Return service: 60 months" in text for text in by_class["FUNDING"])
    assert not any("Return service" in text for text in by_class.get("ELIGIBILITY", []))


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


def test_an_unreadable_date_keeps_its_citation_instead_of_the_fabricated_year() -> None:
    """The quoted sentence usually carries the correct date; don't throw it away.

    Two of the three originally-discovered bad rows had a correct date in the
    evidence quote and only the parsed year wrong. Dropping the row entirely
    (the prior behaviour) destroys exactly what a human needs to resolve it,
    and the page is later marked unchanged so it is never re-extracted.
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
        key_dates=(
            KeyDateClaim(
                kind="APPLICATION_DEADLINE",
                on=date(1558, 12, 1),
                evidence="the deadline set for 1 December 2026 at 23:59 CET",
            ),
        ),
    )

    rows = claim_rows(program, claims, now=datetime(2026, 8, 30))
    text = [row[1] for row in rows]

    assert not any("1558" in row for row in text)
    assert any(
        "date stated but not read reliably" in row
        and "the deadline set for 1 December 2026 at 23:59 CET" in row
        for row in text
    )


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


def test_pooling_no_pages_refuses_rather_than_crashing() -> None:
    assert pool_claims(()) is None


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
                label="stipend", amount=Decimal("1400.00"), currency="EUR", period="monthly",
                evidence="A monthly stipend of 1,400 EUR is paid.",
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
                       currency="DUR", period="months",
                       evidence="The scholarship lasts 24 months."),
            MoneyClaim(label="stipend", amount=Decimal("1400.00"),
                       currency="EUR", period="monthly",
                       evidence="A monthly stipend of 1,400 EUR is paid."),
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
    assert _money(
        "stipend", Decimal("1400.00"), "EUR", "monthly", "A monthly allowance of 1,400 EUR."
    ) == "stipend: 1400.00 EUR per monthly"
    assert _money(
        "Scholarship duration", Decimal("24"), "DUR", "months",
        "The scholarship lasts 24 months.",
    ) is None


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


def test_eur_as_a_substring_of_an_unrelated_word_is_not_a_quotation() -> None:
    # EUR sits inside European/eurozone/chauffeur/entrepreneur. A plain
    # substring check let currency="EUR" pass on evidence with no amount and
    # no currency in it at all, which inverted the rule for 552 of the
    # corpus's 618 money claims (all EUR). \bEUR\b must not match here.
    assert _money(
        "stipend", Decimal("1400.00"), "EUR", "monthly",
        "The European Commission co-funds this programme.",
    ) is None


def test_a_spelled_out_currency_is_dropped_not_credited() -> None:
    # Documented ceiling, not an oversight: \bEUR\b does not match "euros"
    # because the word continues past the R. A page that spells the currency
    # out instead of using the code or symbol is withheld -- Task 6 measures
    # whether this actually costs a claim on real pages.
    assert _money(
        "stipend", Decimal("1400.00"), "EUR", "monthly",
        "A monthly allowance of 1,400 euros is paid.",
    ) is None


def test_a_commitment_payment_with_an_unreadable_currency_keeps_its_row() -> None:
    """Same precedent as the unreadable date: a mangled currency is one field,

    not proof the page said nothing. The row survives in TUITION with its
    due-window and evidence intact -- only the bogus currency code is gone.
    """
    from apps.research.extraction import CommitmentPaymentClaim

    program = ResolvedProgram(
        institution_name="Consortium University",
        country_code="NO",
        city="",
        program_name="Coastal Engineering",
        degree_level="MASTER",
        teaching_languages=("English",),
        duration_months=24,
    )
    claims = ExtractedClaims(
        confidence=0.9,
        commitment_payment=CommitmentPaymentClaim(
            kind="TUITION_DEPOSIT",
            amount=Decimal("2000.00"),
            currency="NOT",
            window_days=28,
            evidence="A deposit of 2,000 is payable within 28 days of the offer.",
        ),
    )

    rows = claim_rows(program, claims, now=datetime(2026, 8, 30))
    text = [row[1] for row in rows]

    assert any(
        row.startswith("TUITION_DEPOSIT: amount stated but currency not read reliably")
        and "due within 28 days of an offer" in row
        and "A deposit of 2,000 is payable within 28 days of the offer." in row
        for row in text
    )
    # Not just the text -- the row must be emitted under TUITION, not some
    # other class, or a claim_class regression here would pass unnoticed.
    assert all(
        claim_class == OfficialEvidenceClaim.ClaimClass.TUITION
        for claim_class, row_text in rows
        if row_text.startswith("TUITION_DEPOSIT:")
    )
    assert not any("NOT" in row for row in text)


def test_a_commitment_payment_with_a_real_currency_is_unchanged() -> None:
    from apps.research.extraction import CommitmentPaymentClaim

    program = ResolvedProgram(
        institution_name="Consortium University",
        country_code="NO",
        city="",
        program_name="Coastal Engineering",
        degree_level="MASTER",
        teaching_languages=("English",),
        duration_months=24,
    )
    claims = ExtractedClaims(
        confidence=0.9,
        commitment_payment=CommitmentPaymentClaim(
            kind="TUITION_DEPOSIT",
            amount=Decimal("2000.00"),
            currency="GBP",
            window_days=28,
            evidence="A deposit of £2,000 is payable within 28 days of the offer.",
        ),
    )

    rows = claim_rows(program, claims, now=datetime(2026, 8, 30))
    text = [row[1] for row in rows]

    assert any(
        "TUITION_DEPOSIT: 2000.00 GBP, due within 28 days of an offer"
        " — A deposit of £2,000 is payable within 28 days of the offer." == row
        for row in text
    )
    # Not just the text -- the row must be emitted under TUITION, not some
    # other class, or a claim_class regression here would pass unnoticed.
    assert all(
        claim_class == OfficialEvidenceClaim.ClaimClass.TUITION
        for claim_class, row_text in rows
        if row_text.startswith("TUITION_DEPOSIT:")
    )


def _joint_lead() -> ResearchLead:
    """What _tagged produces for a lead harvested from seed:eacea."""
    return replace(_official_lead(), awards_jointly=True, discovered_by="seed:eacea")


def test_a_joint_lead_writes_no_institution_at_all(source, snapshot) -> None:
    """The assertion this whole change exists for: a jointly-awarded programme
    must never mint an Institution keyed on a scraped provider name, because
    such a row can never bind to a register code."""
    before = Institution._base_manager.count()

    result = write_catalog_entry(
        lead=_joint_lead(), claims=CLAIMS, source=source, snapshot=snapshot
    )

    assert result is not None
    assert result.institution is None
    assert Institution._base_manager.count() == before
    assert result.program.institution_id is None
    assert result.program.provision_type == "JOINT"
    assert result.program.provider_text == "University of Technology Nuremberg"


def test_a_joint_lead_writes_no_institution_evidence_claim(source, snapshot) -> None:
    result = write_catalog_entry(
        lead=_joint_lead(), claims=CLAIMS, source=source, snapshot=snapshot
    )

    assert result is not None
    assert InstitutionEvidenceClaim._base_manager.count() == 0
    assert any(claim.claim_class == "IDENTITY" for claim in result.claims)


def test_a_composite_provider_name_is_joint_without_a_source_promise(source, snapshot) -> None:
    """The fallback path: a source that promises nothing still must not mint an
    Institution from 'A; B; C'."""
    lead = ResearchLead.from_url(
        "https://example.org/programme",
        source_type="PROGRAM",
        funding_family="MULTILATERAL",
        discovered_by="entity-expansion",
        identity=LeadIdentity(
            institution_name="University of Belgrade; LUMSA; Örebro University",
            country_code="RS",
            city="Belgrade",
            program_name="Joint Master",
        ),
    )
    before = Institution._base_manager.count()

    result = write_catalog_entry(lead=lead, claims=CLAIMS, source=source, snapshot=snapshot)

    assert result is not None
    assert result.institution is None
    assert Institution._base_manager.count() == before


def test_a_single_lead_still_writes_its_institution(source, snapshot) -> None:
    result = write_catalog_entry(
        lead=_official_lead(), claims=CLAIMS, source=source, snapshot=snapshot
    )

    assert result is not None
    assert result.institution is not None
    assert result.institution.name == "University of Technology Nuremberg"
    assert result.program.provision_type == "SINGLE"
    assert result.program.provider_text == ""


def test_a_provider_string_never_becomes_a_city(source, snapshot) -> None:
    """evaluation.py's LOCATION gate compares Program.city by equality. A joint
    row's institution_name is several universities in one string, so borrowing
    it as the city excluded the programme from every student who named a real
    city -- and matched none of them."""
    lead = replace(
        _joint_lead(),
        identity=replace(
            SEED_IDENTITY,
            institution_name="University of Belgrade; LUMSA; Örebro University",
            city="",
        ),
    )

    result = write_catalog_entry(lead=lead, claims=CLAIMS, source=source, snapshot=snapshot)

    assert result is not None
    assert result.program.city == ""
    assert result.program.campus_name == ""
    assert result.program.provider_text == "University of Belgrade; LUMSA; Örebro University"
