"""When things are due and when an unanswered alert climbs. No database, no clock.

Platform-wide defaults (spec §1): a portal gets its own timing only when real
data shows it behaves differently.
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: How long a portal gets to confirm a submission before we ask the student to
#: look. Two days covers a weekend-free acknowledgement; tune from data.
CONFIRMATION_WINDOW = timedelta(hours=48)

#: Registering on a portal almost always triggers a verification email within
#: minutes (spec §2a). Mail from that portal inside this window says whether it
#: keeps the tag; after it, nothing more is inferred.
REGISTRATION_MAIL_WINDOW = timedelta(minutes=30)

#: When the dock asks the student about that email if the mailbox has not
#: answered yet -- short, because the point is to ask while they are still at
#: the portal's screen.
REGISTRATION_ASK_AFTER = timedelta(minutes=5)

#: Inside this distance of the deadline the ladder tightens.
NEAR_DEADLINE = timedelta(hours=48)

#: (email after, counsellor after) -- slow far from a deadline, fast near one.
_SLOW = (timedelta(hours=12), timedelta(hours=24))
_FAST = (timedelta(hours=2), timedelta(hours=4))


def confirmation_due(submitted_at: datetime) -> datetime:
    return submitted_at + CONFIRMATION_WINDOW


def escalation_target(created_at: datetime, now: datetime, deadline: datetime | None) -> int:
    """The escalation level an unanswered urgent alert should have reached.

    0 dashboard only, 1 email the student, 2 tell the counsellor. Levels are
    cumulative; the caller performs every level between the current one and this.
    """
    near = deadline is not None and deadline - now <= NEAR_DEADLINE
    email_after, counsellor_after = _FAST if near else _SLOW
    waited = now - created_at
    if waited >= counsellor_after:
        return 2
    if waited >= email_after:
        return 1
    return 0
