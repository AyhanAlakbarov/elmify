"""Tests for the 3-Tier Sufficiency-Gated Hybrid Retrieval & Discovery Engine."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from django.utils import timezone

from apps.funding.fx import RateTable
from apps.funding.models import (
    CostComponent,
    CycleState,
    FundingBenefit,
    FundingCycleVerification,
    FundingOpportunity,
    FundingOpportunityEvidenceClaim,
    FundingOpportunityProgram,
    Institution,
    Period,
    Program,
)
from apps.funding.rates import store
from apps.research.hybrid_strategy import (
    DiscoveryTier,
    apply_hybrid_plan_to_tap_inputs,
    execute_hybrid_discovery,
    plan_hybrid_retrieval,
)
from apps.research.models import SearchTap
from apps.research.services import rebuild_pack
from apps.research.tap import request_tap, run_tap
from apps.research.tap_query import inputs_from
from apps.research.tap_seams import AngleRow, NullSeams, PassState
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_profile
from tests.research.coverage_factories import make_published_student
from tests.research.provenance_helpers import attach_evidence, make_body, recognise

pytestmark = pytest.mark.django_db(transaction=True)


class _ScriptedPasses(NullSeams):
    def __init__(self, *, past_stop_countries: set[str] | None = None) -> None:
        self._past = past_stop_countries or set()

    def programme_angles(self, *, level: str, language: str) -> tuple[AngleRow, ...]:
        return (
            AngleRow(
                f"{language}-c",
                language,
                "Our M.Sc. in {field} in {destination}",
            ),
        )

    def state(self, country: str, family: str) -> PassState:
        return PassState(
            swept=country in self._past,
            past_economic_stop=country in self._past,
            batches_without_new=2 if country in self._past else 0,
            stop_reason="PLATEAU" if country in self._past else "",
        )


class _RecordingProvider:
    def __init__(self, name: str = "exa") -> None:
        self.name = name
        self.requests: list[object] = []

    def search(self, request: object, meter: object = None):
        self.requests.append(request)
        if False:
            yield ""


def _seed_rates() -> None:
    store(
        RateTable(
            base="AZN",
            rates={
                "AZN": Decimal("1"),
                "EUR": Decimal("0.54"),
                "USD": Decimal("0.59"),
            },
            source="CBAR",
            retrieved_on=timezone.now().date(),
        )
    )


def _create_verified_program(
    *,
    country_code: str,
    name: str,
    domain: str,
    funded: bool = False,
    intake_year: int = 2027,
    cycle_due: bool = False,
) -> tuple[Program, FundingOpportunity | None]:
    suffix = uuid4().hex[:6]
    inst = Institution.objects.create(
        canonical_key=f"institution:{country_code}:{suffix}",
        name=f"University {domain} {suffix}",
        country_code=country_code,
        official_website=f"https://www.{domain}/",
    )
    prog = Program.objects.create(
        institution=inst,
        canonical_key=f"prog:{country_code}:{suffix}",
        name=name,
        campus_name="Main",
        city="Capital",
        country_code=country_code,
        location_key=f"{country_code}-CAP-{suffix}",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    claims = attach_evidence(prog, f"https://www.{domain}/programs/{suffix}")
    org = make_body(domain, kind="INSTITUTION", country_code=country_code)
    recognise(org, domain)

    CostComponent.objects.create(
        program=prog,
        kind=CostComponent.Kind.TUITION,
        amount=Decimal("0") if funded else Decimal("12000"),
        currency="EUR",
        period=Period.FULL_PROGRAM,
    )
    CostComponent.objects.create(
        program=prog,
        kind=CostComponent.Kind.APPLICATION_FEE,
        amount=Decimal("0"),
        currency="EUR",
        period=Period.ONE_OFF,
    )

    opp: FundingOpportunity | None = None
    if funded:
        opp = FundingOpportunity.objects.create(
            canonical_key=f"opp:{country_code}:{suffix}",
            name=f"{name} Full Scholarship",
            family="UNIVERSITY_WIDE",
            scope_type="PROGRAM",
            program=prog,
            institution=None,
            organisation=org,
            holder="INSTITUTION",
            holder_domain=domain,
            holder_name=inst.name,
            country_code=None,
            agreement="AGREED",
            served=True,
            money_form="GRANT",
        )
        FundingOpportunityEvidenceClaim.objects.create(
            opportunity=opp,
            evidence_claim=claims[0],
        )
        FundingOpportunityProgram.objects.create(opportunity=opp, program=prog)
        FundingBenefit.objects.create(
            opportunity=opp,
            kind=FundingBenefit.Kind.TUITION,
            amount=Decimal("12000"),
            currency="EUR",
            period=Period.FULL_PROGRAM,
            description="100% tuition waiver",
        )
        now = timezone.now()
        FundingCycleVerification.objects.create(
            opportunity=opp,
            intake_start_year=intake_year,
            state=CycleState.UNVERIFIED if cycle_due else CycleState.OPEN,
            next_check_at=now - timedelta(hours=2) if cycle_due else now + timedelta(days=14),
            evidence=[
                {
                    "step": "0",
                    "url": claims[0].source.canonical_url,
                    "sha256": "a" * 64,
                    "at": now.date().isoformat(),
                    "archived": False,
                    "captured_at": "",
                    "offered": "YES",
                    "applies_to": f"{intake_year}/{intake_year + 1}",
                    "intake_year": intake_year,
                    "stated_on": now.date().isoformat(),
                    "deadlines": [[f"{intake_year}-03-15", "all applicants", ""]],
                    "quote": "Applications open.",
                    "agreement": "AGREED",
                }
            ],
        )
    return prog, opp


def test_tier_1_db_complete_short_circuits_live_search(
    agency_a, django_user_model, monkeypatch
) -> None:
    import apps.research.tap as tap_module

    monkeypatch.setattr(tap_module, "enqueue_research", lambda *_a, **_k: None)
    _seed_rates()

    programs = []
    for i in range(5):
        prog, _ = _create_verified_program(
            country_code="DE",
            name=f"M.Sc. in Computer Science Track {i + 1}",
            domain=f"uni-de-{i + 1}.de",
            funded=(i < 3),
        )
        programs.append(prog)

    student = make_published_student(
        agency_a,
        django_user_model,
        allowed=("DE",),
        target_field="Computer Science",
        research_interests=(),
        strategy="FUNDING_FIRST",
        programs=programs,
    )

    with tenant_scope(agency_a.id):
        from apps.funding.models import RecommendationRun
        from apps.funding.rates import latest_table

        run = RecommendationRun.objects.get(profile_version__student=student)
        pack = rebuild_pack(run, rates=latest_table())
        profile = make_profile(
            nationality="AZ",
            country_of_residence="AZ",
            allowed_countries=("DE",),
            target_field="Computer Science",
            research_interests=(),
            strategy="FUNDING_FIRST",
        )
        plan = plan_hybrid_retrieval(profile, pack=pack)
        assert plan.overall_tier == DiscoveryTier.TIER_1_DB_COMPLETE
        assert plan.hot_countries == ("DE",)
        assert plan.active_search_destinations == ()

        provider = _RecordingProvider()
        tap = request_tap(student, kind=SearchTap.Kind.FIRST)
        run_tap(tap.id, seams=_ScriptedPasses(), providers=[provider])
        tap.refresh_from_db()
        assert tap.state == SearchTap.State.DONE
        assert tap.ending == SearchTap.Ending.COMPLETE
        assert provider.requests == []


def test_tier_2_interdisciplinary_subfield_miss_and_university_funding_queries(
    agency_a, django_user_model
) -> None:
    _seed_rates()

    # Populate 5 generic Chemistry programmes in Italy (parent field matches,
    # but 0 exact "Cheminformatics" / "Digital Chemistry" programmes and 0 funded).
    for i in range(5):
        _create_verified_program(
            country_code="IT",
            name=f"Master of Science in Chemistry {i + 1}",
            domain=f"unipd-{i + 1}.it",
            funded=False,
        )

    profile = make_profile(
        nationality="AZ",
        country_of_residence="AZ",
        allowed_countries=("IT",),
        target_field="AI with chemistry",
        research_interests=(),
    )
    plan = plan_hybrid_retrieval(profile)
    assert plan.overall_tier == DiscoveryTier.TIER_2_TARGETED_DELTA
    assert plan.is_interdisciplinary is True
    assert plan.delta_countries == ("IT",)
    assert plan.assessments[0].program_count == 5
    assert plan.assessments[0].exact_subfield_count == 0
    assert len(plan.assessments[0].unfunded_university_domains) == 5
    assert any("site:unipd-1.it" in r.query for r in plan.targeted_queries)
    assert "IT" in plan.portal_seed_urls and len(plan.portal_seed_urls["IT"]) > 0

    raw_inputs = inputs_from(profile)
    narrowed = apply_hybrid_plan_to_tap_inputs(raw_inputs, plan)
    assert narrowed.destinations == ("IT",)
    assert any(
        "cheminformatics" in w or "digital chemistry" in w for w in narrowed.interest_words
    )


def test_tier_2_due_cycle_verifications_reverified_without_full_sweep(
    agency_a, django_user_model
) -> None:
    _seed_rates()

    programs = []
    for i in range(5):
        prog, _ = _create_verified_program(
            country_code="DE",
            name=f"M.Sc. in Computer Science {i + 1}",
            domain=f"tu-de-{i + 1}.de",
            funded=(i < 3),
            cycle_due=(i == 0),
        )
        programs.append(prog)

    student = make_published_student(
        agency_a,
        django_user_model,
        allowed=("DE",),
        target_field="Computer Science",
        research_interests=(),
        strategy="FUNDING_FIRST",
        programs=programs,
    )
    with tenant_scope(agency_a.id):
        from apps.funding.models import RecommendationRun
        from apps.funding.rates import latest_table

        run = RecommendationRun.objects.get(profile_version__student=student)
        profile = make_profile(
            nationality="AZ",
            country_of_residence="AZ",
            allowed_countries=("DE",),
            target_field="Computer Science",
            research_interests=(),
            strategy="FUNDING_FIRST",
        )
        initial_plan = plan_hybrid_retrieval(profile)
        assert initial_plan.cycle_refresh_only_countries == ("DE",)
        reverified_ids: list[UUID] = []

        def fake_verify(ids):
            reverified_ids.extend(ids)
            FundingCycleVerification.objects.filter(id__in=ids).update(
                state=CycleState.OPEN,
                next_check_at=timezone.now() + timedelta(days=14),
            )
            return len(ids)

        discovered: list[str] = []
        report = execute_hybrid_discovery(
            profile,
            tenant_id=agency_a.id,
            run=run,
            rates=latest_table(),
            verify_due_fn=fake_verify,
            discover_country_fn=lambda cc, _t, _p: discovered.append(cc) or 1,
        )
        assert len(reverified_ids) == 1
        assert report.cycles_reverified == 1
        assert report.plan.due_verification_ids == tuple(reverified_ids)
        assert report.plan.overall_tier == DiscoveryTier.TIER_1_DB_COMPLETE
        assert report.countries_discovered == ()
        assert discovered == []


def test_multi_country_plan_prunes_hot_countries_and_searches_only_cold_countries(
    agency_a, django_user_model, monkeypatch
) -> None:
    import apps.research.tap as tap_module

    monkeypatch.setattr(tap_module, "enqueue_research", lambda *_a, **_k: None)
    _seed_rates()

    de_programs = []
    for i in range(5):
        prog, _ = _create_verified_program(
            country_code="DE",
            name=f"M.Sc. in Computer Science {i + 1}",
            domain=f"rwth-{i + 1}.de",
            funded=(i < 3),
        )
        de_programs.append(prog)

    student = make_published_student(
        agency_a,
        django_user_model,
        allowed=("DE", "SA"),
        target_field="Computer Science",
        research_interests=(),
        strategy="FUNDING_FIRST",
        programs=de_programs,
    )
    with tenant_scope(agency_a.id):
        provider = _RecordingProvider()
        tap = request_tap(student, kind=SearchTap.Kind.FIRST)
        run_tap(tap.id, seams=_ScriptedPasses(), providers=[provider])
        asked_queries = [r.query for r in provider.requests]
        assert len(asked_queries) > 0
        assert any("Saudi Arabia" in q for q in asked_queries)
        assert not any("Germany" in q for q in asked_queries)


def test_warm_cell_past_economic_stop_is_classified_tier_1() -> None:
    for i in range(2):
        _create_verified_program(
            country_code="FI",
            name=f"M.Sc. in Computer Science {i + 1}",
            domain=f"aalto-{i + 1}.fi",
            funded=True,
        )

    profile = make_profile(
        nationality="AZ",
        country_of_residence="AZ",
        allowed_countries=("FI",),
        target_field="Computer Science",
        research_interests=(),
    )
    plan = plan_hybrid_retrieval(
        profile,
        passes=_ScriptedPasses(past_stop_countries={"FI"}),
    )
    assert plan.overall_tier == DiscoveryTier.TIER_1_DB_COMPLETE
    assert plan.hot_countries == ("FI",)


def test_research_interests_never_suppressed_by_generic_field_programs() -> None:
    """5 generic Computer Science programmes must NOT suppress discovery when the
    student specifies a research interest ('quantum cryptography') with 0 DB matches."""
    for i in range(5):
        _create_verified_program(
            country_code="DE",
            name=f"M.Sc. in Computer Science {i + 1}",
            domain=f"generic-cs-{i + 1}.de",
            funded=True,
        )

    profile = make_profile(
        nationality="AZ",
        country_of_residence="AZ",
        allowed_countries=("DE",),
        target_field="Computer Science",
        research_interests=("quantum cryptography",),
    )
    plan = plan_hybrid_retrieval(profile)
    assert plan.overall_tier == DiscoveryTier.TIER_2_TARGETED_DELTA
    assert plan.delta_countries == ("DE",)
    assert plan.hot_countries == ()
    assert plan.assessments[0].interest_match_count == 0


def test_anywhere_profile_does_not_misclassify_unpopulated_countries_as_tier_1() -> None:
    """An 'anywhere' profile (`allowed_countries=()`) with 5 programmes in DE must
    mark DE as hot (`hot_countries=('DE',)`), while keeping unpopulated countries
    in `cold_countries` (`overall_tier == TIER_3_COLD_CELL_SWEEP`)."""
    for i in range(5):
        _create_verified_program(
            country_code="DE",
            name=f"M.Sc. in Computer Science {i + 1}",
            domain=f"anywhere-de-{i + 1}.de",
            funded=True,
        )

    profile = make_profile(
        nationality="AZ",
        country_of_residence="AZ",
        allowed_countries=(),
        target_field="Computer Science",
        research_interests=(),
    )
    plan = plan_hybrid_retrieval(profile)
    assert plan.overall_tier == DiscoveryTier.TIER_3_COLD_CELL_SWEEP
    assert "DE" in plan.hot_countries
    assert len(plan.cold_countries) > 10


def test_past_economic_stop_does_not_suppress_missing_interdisciplinary_subfield() -> None:
    """Even when a country's general UNIVERSITY_WIDE sweep hit economic stop,
    0 exact matches for an interdisciplinary field ('Cheminformatics') must keep
    the cell in Tier 2 rather than suppressing sub-field discovery."""
    for i in range(3):
        _create_verified_program(
            country_code="IT",
            name=f"M.Sc. in Chemistry {i + 1}",
            domain=f"uni-it-chem-{i + 1}.it",
            funded=True,
        )

    profile = make_profile(
        nationality="AZ",
        country_of_residence="AZ",
        allowed_countries=("IT",),
        target_field="Cheminformatics",
        research_interests=("molecular modeling",),
    )
    plan = plan_hybrid_retrieval(
        profile,
        passes=_ScriptedPasses(past_stop_countries={"IT"}),
    )
    assert plan.overall_tier == DiscoveryTier.TIER_2_TARGETED_DELTA
    assert plan.delta_countries == ("IT",)
    assert plan.hot_countries == ()


def test_time_decayed_exploration_steps_down_stale_cell_below_deep_saturation() -> None:
    """A cell with 5..14 programmes whose evidence is older than 30 days and
    has not hit economic stop steps down to Tier 2 (`needs_exploration=True`)
    so one student tap every 30 days deepens the catalog toward 15 programmes."""
    from apps.funding.models import OfficialEvidenceClaim

    progs = []
    for i in range(5):
        p, _ = _create_verified_program(
            country_code="NL",
            name=f"M.Sc. in Computer Science {i + 1}",
            domain=f"tudelft-{i + 1}.nl",
            funded=True,
        )
        progs.append(p)

    # Backdate evidence claims to 45 days ago (> 30-day exploration cooldown).
    OfficialEvidenceClaim.objects.filter(
        programevidenceclaim__program_id__in=[p.id for p in progs]
    ).update(last_checked_at=timezone.now() - timedelta(days=45))

    profile = make_profile(
        nationality="AZ",
        country_of_residence="AZ",
        allowed_countries=("NL",),
        target_field="Computer Science",
        research_interests=(),
    )
    stale_plan = plan_hybrid_retrieval(profile, deep_saturation_count=15)
    assert stale_plan.overall_tier == DiscoveryTier.TIER_2_TARGETED_DELTA
    assert stale_plan.assessments[0].needs_exploration is True

    # Once the cell reaches deep_saturation_count (e.g. 5 when configured to 5),
    # it remains TIER_1_DB_COMPLETE even after 45 days.
    saturated_plan = plan_hybrid_retrieval(profile, deep_saturation_count=5)
    assert saturated_plan.overall_tier == DiscoveryTier.TIER_1_DB_COMPLETE
    assert saturated_plan.assessments[0].needs_exploration is False


def test_programme_and_institution_attached_awards_count_in_hybrid_sufficiency() -> None:
    """Attached PROGRAM (including direct `program_id`) and INSTITUTION awards
    must be counted in `matched_awards` and `affordable_programs` by `plan_hybrid_retrieval`."""
    from apps.funding.models import FundingCycleVerification, FundingOpportunity

    progs = []
    for i in range(5):
        p, _ = _create_verified_program(
            country_code="FR",
            name=f"M.Sc. in Computer Science {i + 1}",
            domain=f"univ-fr-{i + 1}.fr",
            funded=False,
        )
        progs.append(p)

    # Attach 1 direct PROGRAM-scoped opportunity to progs[0] (without a join row)
    # and 1 INSTITUTION-scoped opportunity to progs[1].institution.
    prog_opp = FundingOpportunity.objects.create(
        canonical_key=f"opp:direct-prog:{uuid4()}",
        name="LabEx Graduate School Fellowship",
        family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM",
        program=progs[0],
        agreement="AGREED",
        served=True,
        money_form="GRANT",
        route="CONSIDERED_WITH_ADMISSION",
        tuition="FULL",
        living="FULL",
    )
    inst_opp = FundingOpportunity.objects.create(
        canonical_key=f"opp:inst:{uuid4()}",
        name="University Excellence Scholarship",
        family="UNIVERSITY_WIDE",
        scope_type="INSTITUTION",
        institution=progs[1].institution,
        agreement="AGREED",
        served=True,
        money_form="GRANT",
        route="STUDENT_APPLIES_SEPARATELY",
        tuition="FULL",
        living="FULL",
    )
    for opp in (prog_opp, inst_opp):
        FundingCycleVerification.objects.create(
            opportunity=opp,
            intake_start_year=2027,
            state="OPEN",
            next_check_at=timezone.now() + timedelta(days=14),
        )

    profile = make_profile(
        nationality="AZ",
        country_of_residence="AZ",
        allowed_countries=("FR",),
        target_field="Computer Science",
        research_interests=(),
    )
    plan = plan_hybrid_retrieval(profile)
    assert plan.overall_tier == DiscoveryTier.TIER_1_DB_COMPLETE
    assert plan.assessments[0].affordable_count == 2
    assert plan.assessments[0].served_award_count == 2


def test_unfunded_joint_programme_domain_is_queued_in_unfunded_university_domains() -> None:
    """An unfunded JOINT / Erasmus Mundus programme (`institution_id is None`)
    must include its `origin_domain` in `unfunded_university_domains` so Tier 2
    triggers `CardHostReader` on the consortium website."""
    _create_verified_program(
        country_code="BE",
        name="M.Sc. in Computer Science",
        domain="kuleuven.be",
        funded=True,
    )
    joint_prog = Program.objects.create(
        canonical_key=f"prog:joint-unfunded:{uuid4()}",
        institution=None,
        provision_type=Program.ProvisionType.JOINT,
        origin_domain="emjm-unfunded.eu",
        evidence_domain="emjm-unfunded.eu",
        name="M.Sc. in Computer Science — Erasmus Mundus Joint Master",
        campus_name="Consortium",
        city="Brussels",
        country_code="BE",
        location_key="BE-BRUSSELS",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    attach_evidence(joint_prog, "https://emjm-unfunded.eu/programme")
    org = make_body("emjm-unfunded.eu", kind="INSTITUTION", country_code="BE")
    recognise(org, "emjm-unfunded.eu")

    profile = make_profile(
        nationality="AZ",
        country_of_residence="AZ",
        allowed_countries=("BE",),
        target_field="Computer Science",
        research_interests=(),
    )
    plan = plan_hybrid_retrieval(profile)
    assert plan.overall_tier == DiscoveryTier.TIER_2_TARGETED_DELTA
    assert "emjm-unfunded.eu" in plan.assessments[0].unfunded_university_domains
    assert "kuleuven.be" not in plan.assessments[0].unfunded_university_domains




