"""Whether a counsellor may change a student's data right now.

The tenancy middleware locks the REQUESTER only, so every counsellor write on a
student's behalf checks the TARGET student here: the counsellor board
(apps/dashboard/views.py), the named-programme resolve (apps/funding/views.py)
and marking a roadmap step done (apps/concierge/views.py).
"""

from apps.privacy.requests import processing_stopped
from apps.tenancy.middleware import deletion_lock_target
from apps.tenancy.models import Membership


def paused_reason(student: Membership) -> str | None:
    """Why the student's data is read-only, or None.

    The student asked to delete their account (owner, 2026-10-04), or objected
    to / withdrew consent for processing (F14): either stops every write until
    it is lifted.
    """
    if deletion_lock_target(student) is not None:
        return "This student has asked to delete their account; changes are paused."
    if processing_stopped(student):
        return "This student has stopped the processing of their data; changes are paused."
    return None
