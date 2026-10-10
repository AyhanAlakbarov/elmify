"""A published pack with a programme and the award that funds it."""

from uuid import uuid4

import pytest

from apps.funding.models import FundingOpportunity, RecommendationCandidate
from apps.portals.models import Application, PortalForm
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run


@pytest.fixture
def pack(agency_a, membership_a, program_factory):
    programme_row = program_factory(name="M.Sc. Informatics")
    award_row = FundingOpportunity.objects.create(
        canonical_key=f"award:{uuid4()}", name="DAAD Study Scholarship",
        family="UNIVERSITY_WIDE", scope_type="GLOBAL",
    )
    run = make_run(agency_a, membership_a)
    programme = make_db_candidate(
        agency_a, run, program_name="M.Sc. Informatics", funding_gap="1200.00"
    )
    award = make_db_candidate(agency_a, run, program_name="DAAD Study Scholarship")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(
            program_id=programme_row.id, institution_name="TUM", country_code="DE",
            application_fee="75.00", application_fee_currency="EUR",
        )
        RecommendationCandidate.objects.filter(id=award.id).update(
            opportunity_id=award_row.id,
            funds_program_ids=[programme_row.id],
            funding_card={
                "scope": "HOLDER", "holder": "DAAD", "tuition": "NONE", "living": "FULL",
                "amounts": ["934 EUR a month"], "deadline": "2026-11-15",
            },
        )
        programme.refresh_from_db()
        award.refresh_from_db()
    make_published_pack(agency_a, run, (programme, award))
    return programme, award


def add_card(agency, student, candidate, *, portal=True, **fields) -> Application:
    form = (
        PortalForm.objects.create(
            portal_host="campus.tum.de", form_key=f"k-{uuid4()}",
            form_url="https://campus.tum.de/apply",
        )
        if portal
        else None
    )
    return Application.objects.create(
        tenant=agency,
        student=student,
        program_id=candidate.program_id or candidate.opportunity_id,
        candidate=candidate,
        portal_form=form,
        **fields,
    )
