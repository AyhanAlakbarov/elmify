"""Pack-page helpers shared with other dashboard pages."""

from uuid import UUID

from apps.portals.models import Application
from apps.tenancy.models import Membership


def applied_candidate_ids(student: Membership) -> set[UUID]:
    """Candidates the student has already added as applications."""
    return set(
        Application.objects.filter(student=student, candidate__isnull=False).values_list(
            "candidate_id", flat=True
        )
    )
