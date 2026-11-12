"""Award-card deadline lookup from stored cycle verification (CV build step 4.2).

Worker-only: reads `FundingCycleVerification` and `FundingOpportunity` from the
shared catalogue. Midnight UTC sits at or before the end of the selected day in
every timezone, so every reminder rung fires early, never late.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import ValidationError

from apps.accounts.models import StudentProfileVersion
from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.cycle_evidence import deadline_student, to_evidence
from apps.funding.models import FundingCycleVerification, RecommendationCandidate
from apps.funding.validity import select_deadline
from apps.portals.models import Application
from apps.research.cycle_verification import cadence_of
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

logger = logging.getLogger(__name__)


def award_deadline(application: Application) -> datetime | None:
    """The student's own deadline for an award card, at 00:00 UTC, or None."""
    if application.candidate_id is None:
        return None
    with tenant_scope(application.tenant_id), tenant_transaction(application.tenant_id):
        candidate = (
            RecommendationCandidate.objects.select_related(
                "opportunity__organisation", "run"
            )
            .filter(id=application.candidate_id)
            .first()
        )
        if candidate is None or candidate.opportunity is None:
            return None
        version = StudentProfileVersion.objects.filter(
            id=candidate.run.profile_version_id
        ).first()
    if version is None:
        return None
    try:
        profile = StudentProfileSnapshot.model_validate(version.snapshot)
    except ValidationError:
        logger.warning(
            "stored StudentProfileSnapshot unreadable for version %s (application %s)",
            version.id,
            application.id,
        )
        return None
    year = profile.intended_intake.year
    row = FundingCycleVerification.objects.filter(
        opportunity_id=candidate.opportunity_id, intake_start_year=year
    ).first()
    if row is None:
        return None
    evidence = to_evidence(
        row.evidence,
        target_year=year,
        cadence=cadence_of(candidate.opportunity),
        page_removed=row.page_removed,
        lapsed=row.projection_lapsed,
    )
    selected = select_deadline(
        evidence,
        deadline_student(profile.nationality, profile.country_of_residence),
    )
    if selected is None:
        return None
    return datetime(
        selected.date.year, selected.date.month, selected.date.day, tzinfo=UTC
    )
