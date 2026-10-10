"""Which agency is the platform.

`research.PlatformAgency` holds at most one row, written only by
`manage.py set_platform_agency` as the migration role (neither runtime role
holds INSERT, UPDATE or DELETE on it -- research/0013).
"""

from __future__ import annotations

from apps.research.models import PlatformAgency
from apps.tenancy.models import Agency


def platform_agency() -> Agency:
    """The platform's own agency. Raises Agency.DoesNotExist when none is set.

    Deliberately no fallback: a queue that silently resolved "the platform" to
    some agency would show every catalog question to that agency's staff.
    """
    marker = PlatformAgency.objects.select_related("agency").first()
    if marker is None:
        raise Agency.DoesNotExist("no platform agency is set: run manage.py set_platform_agency")
    return marker.agency
