"""Tests for card probability display, Elmify staff catalogue access, and B2B isolation."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.dashboard.board import board_for
from apps.funding.models import (
    EvidenceClaim,
    FundingOpportunity,
    Institution,
    Program,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.portals.models import Application
from apps.research.models import PlatformAgency, WinnerCohortProfile
from apps.research.register import record_organisation
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency, CounselorAssignment, Membership, TenantDomain
from tests.conftest import verify_mfa_session
from tests.funding.conftest import make_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def platform(db) -> Agency:
    agency = Agency.objects.create(name="Platform")
    PlatformAgency.objects.create(agency=agency)
    return agency


@pytest.fixture
def operator(platform: Agency) -> Membership:
    user = get_user_model().objects.create_user(username="operator-catalogue")
    with tenant_scope(platform.id):
        return Membership.objects.create(
            tenant=platform, user=user, role=Membership.Role.PLATFORM_ADMIN
        )


@pytest.fixture
def operator_user(operator: Membership):
    return operator.user


@pytest.fixture
def platform_domain(platform: Agency) -> TenantDomain:
    return TenantDomain.objects.create(
        agency=platform, host="platform.example.test", verified_at=timezone.now()
    )


def _create_catalogue_program() -> tuple[Program, FundingOpportunity, WinnerCohortProfile]:
    inst = Institution.objects.create(
        canonical_key=f"inst:{uuid4()}",
        name="University of Strasbourg",
        country_code="FR",
        official_website="https://unistra.fr",
    )
    program = Program.objects.create(
        institution=inst,
        canonical_key=f"prog:{uuid4()}",
        name="MSc Chemoinformatics",
        campus_name="Main Campus",
        city="Strasbourg",
        country_code="FR",
        location_key="FR-STRASBOURG",
        degree_level="MASTER",
        provision_type="SINGLE",
        provider_text="",
        teaching_languages=["English"],
        duration_months=24,
    )
    org = record_organisation(
        domain="unistra.fr",
        name="Campus France",
        kind="NATIONAL_GOVERNMENT",
        country_code="FR",
        found_via="REGISTER",
    )
    opp = FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}",
        name="EMJM Scholarship",
        holder="NATIONAL_GOVERNMENT",
        holder_domain="unistra.fr",
        holder_name="Campus France",
        family="GOVERNMENT_SCHOLARSHIP",
        organisation=org,
        scope_type="HOLDER",
        route="SEPARATE_APPLICATION",
        money_form="GRANT",
        tuition="FULL",
        living="FULL",
        agreement="AGREED",
        served=True,
    )
    cohort = WinnerCohortProfile.objects.create(
        program_id=program.id,
        target_kind=WinnerCohortProfile.TargetKind.PROGRAM,
        target_name=program.name,
        holder_name="University of Strasbourg",
        country_code="FR",
        sample_size=24,
        origin_country_counts={"AZ": 3, "IN": 6},
        prior_degree_fields={"chemistry": 14, "computer_science": 10},
        prior_degree_levels={"BSC": 20, "MSC": 4},
        work_experience_months_p25=6,
        work_experience_months_median=12,
        work_experience_months_p75=24,
        research_signal_rate=Decimal("0.6500"),
        source_provider="proxycurl",
    )
    return program, opp, cohort


def test_candidate_and_application_card_render_estimated_chance_line(
    agency_a, django_user_model
) -> None:
    program, _, _ = _create_catalogue_program()
    user = django_user_model.objects.create_user(username="student-chance")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT
        )
        run: RecommendationRun = make_run(agency_a, student)
        ev = EvidenceClaim.objects.create(
            tenant=agency_a,
            source_url="https://unistra.fr/msc",
            claim="MSc Chemoinformatics",
            last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
        candidate = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            evidence=ev,
            program=program,
            program_name=program.name,
            country_code="FR",
            degree_level="MASTER",
            funding_gap=Decimal("0.00"),
            currency="EUR",
            eligible=True,
            estimated_chance_pct=68,
        )
        app = Application.objects.create(
            tenant=agency_a,
            student=student,
            program_id=program.id,
            candidate=candidate,
        )

        card_open = board_for(student).open_cards[0]
        assert card_open.chance_line == "We estimate that there is an ~68% chance"

        # Once a final outcome is recorded, the chance estimate line is hidden
        app.outcome = Application.Outcome.ADMITTED
        app.save(update_fields=["outcome"])
        card_decided = board_for(student).cards[0]
        assert card_decided.chance_line == ""

        # When estimated_chance_pct is None, chance_line is empty
        app.outcome = ""
        app.save(update_fields=["outcome"])
        candidate.estimated_chance_pct = None
        candidate.save(update_fields=["estimated_chance_pct"])
        card_none = board_for(student).open_cards[0]
        assert card_none.chance_line == ""

    # Verify the production templates include the exact sentence
    repo_root = Path(__file__).resolve().parents[2]
    cand_tpl = (repo_root / "templates" / "student" / "_candidate.html").read_text()
    card_tpl = (repo_root / "templates" / "student" / "_card.html").read_text()
    prog_tpl = (repo_root / "templates" / "student" / "programme.html").read_text()
    assert "We estimate that there is an ~{{ candidate.estimated_chance_pct }}% chance" in cand_tpl
    assert "{{ card.chance_line }}" in card_tpl
    assert "{{ lane.lead.chance_line }}" in prog_tpl


def test_elmify_staff_can_access_platform_catalogue_and_b2b_roles_are_refused(
    client,
    platform,
    platform_domain,
    operator_user,
    operator,
    agency_a,
    domain_a,
    django_user_model,
) -> None:
    _, _, cohort = _create_catalogue_program()

    # 1. Elmify staff (PlatformAgency + PLATFORM_ADMIN + MFA) gets 200 OK and sees global catalogue
    client.force_login(operator_user)
    verify_mfa_session(client, operator_user)
    resp_staff = client.get("/platform/catalogue/", HTTP_HOST=platform_domain.host)
    assert resp_staff.status_code == 200
    assert any(c.id == cohort.id for c in resp_staff.context["cohorts"])

    # 2. B2B agency OWNER is refused (403)
    owner_user = django_user_model.objects.create_user(username="b2b-owner")
    with tenant_scope(agency_a.id):
        Membership.objects.create(
            tenant=agency_a, user=owner_user, role=Membership.Role.OWNER
        )
    client.force_login(owner_user)
    verify_mfa_session(client, owner_user)
    assert client.get("/platform/catalogue/", HTTP_HOST=domain_a.host).status_code == 403

    # 3. B2B agency COUNSELOR is refused (403)
    counselor_user = django_user_model.objects.create_user(username="b2b-counselor")
    with tenant_scope(agency_a.id):
        Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    assert client.get("/platform/catalogue/", HTTP_HOST=domain_a.host).status_code == 403

    # 4. Ordinary agency PLATFORM_ADMIN (not PlatformAgency) is refused (403)
    b2b_padmin = django_user_model.objects.create_user(username="b2b-padmin")
    with tenant_scope(agency_a.id):
        Membership.objects.create(
            tenant=agency_a, user=b2b_padmin, role=Membership.Role.PLATFORM_ADMIN
        )
    client.force_login(b2b_padmin)
    verify_mfa_session(client, b2b_padmin)
    assert client.get("/platform/catalogue/", HTTP_HOST=domain_a.host).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_b2b_counselor_sees_only_assigned_students_and_has_zero_db_catalogue_access(
    client,
    role_connection,
    platform,
    agency_a,
    domain_a,
    django_user_model,
) -> None:
    program, _, _ = _create_catalogue_program()

    counselor_user = django_user_model.objects.create_user(username="counselor-iso")
    student1_user = django_user_model.objects.create_user(username="student-assigned")
    student2_user = django_user_model.objects.create_user(username="student-unassigned")

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        counselor = Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR
        )
        student_assigned = Membership.objects.create(
            tenant=agency_a, user=student1_user, role=Membership.Role.STUDENT
        )
        student_unassigned = Membership.objects.create(
            tenant=agency_a, user=student2_user, role=Membership.Role.STUDENT
        )
        CounselorAssignment.objects.create(
            tenant=agency_a,
            counselor=counselor,
            student=student_assigned,
            active=True,
        )
        run: RecommendationRun = make_run(agency_a, student_assigned)
        ev = EvidenceClaim.objects.create(
            tenant=agency_a,
            source_url="https://unistra.fr/msc",
            claim="MSc Chemoinformatics",
            last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
        cand = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            evidence=ev,
            program=program,
            program_name=program.name,
            country_code="FR",
            degree_level="MASTER",
            funding_gap=Decimal("0.00"),
            currency="EUR",
            eligible=True,
            estimated_chance_pct=68,
        )
        Application.objects.create(
            tenant=agency_a,
            student=student_assigned,
            program_id=program.id,
            candidate=cand,
        )

    # B2B counselor can access their assigned student's board and sees the card with chance_line
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    resp_assigned = client.get(
        f"/counselor/students/{student_assigned.id}/",
        HTTP_HOST=domain_a.host,
    )
    assert resp_assigned.status_code == 200
    cards = resp_assigned.context["board"].open_cards
    assert len(cards) == 1
    assert cards[0].chance_line == "We estimate that there is an ~68% chance"

    # B2B counselor cannot access an unassigned student in the same agency (404)
    resp_unassigned = client.get(
        f"/counselor/students/{student_unassigned.id}/",
        HTTP_HOST=domain_a.host,
    )
    assert resp_unassigned.status_code == 404

    # Database-level verification on runtime_web:
    # 1. Catalogue tables are completely revoked from runtime_web
    with role_connection("runtime_web") as conn:
        for table in (
            "public.funding_program",
            "public.funding_fundingopportunity",
            "public.funding_outcomecalibrationrecord",
        ):
            with conn.transaction(), conn.cursor() as cur, pytest.raises(
                psycopg.errors.InsufficientPrivilege
            ):
                cur.execute(f"SELECT count(*) FROM {table}")

        # 2. WinnerCohortProfile is invisible to agency_a under RLS and visible to PlatformAgency
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true)", [str(agency_a.id)])
            cur.execute("SELECT count(*) FROM public.research_winnercohortprofile")
            assert cur.fetchone() == (0,)

        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true)", [str(platform.id)])
            cur.execute("SELECT count(*) FROM public.research_winnercohortprofile")
            assert cur.fetchone() == (1,)
