"""What the platform does about a classified message.

The first production caller of apps/portals/actions.py::queue_action, whose own
docstring has been waiting for this module.

Everything here is written from the standpoint that the message is hostile. It
came from a domain in the student's pack, which means either the institution
wrote it or somebody took the institution's account -- and the second case is
not rare enough to design around. So a link must land on a host the pack or
an application names in full (never merely the domain the message was read
under), a code has to look like a code, and
nothing the model returns is ever stored as text on the signal.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.mailbox.classify import MailVerdict
from apps.mailbox.filter import host_in
from apps.mailbox.models import MailSignal
from apps.portals.actions import queue_action
from apps.portals.models import Application, ApplicationStep, DeviceAction, zone_named
from apps.portals.outcome import record_from_mail

if TYPE_CHECKING:
    from apps.mailbox.decision_reader import DecisionReading

logger = logging.getLogger(__name__)

#: An hour between sweeps (docs/runbooks/deploy.md, sync_mailboxes's own
#: docstring: rate(1 hour)) plus a buffer, not the foreground-appropriate
#: 15-minute ACTION_TTL default. A mailbox-sourced action is queued by an
#: unattended sweep, not by a student already at the dashboard, so it must
#: still be live at their next visit rather than expiring, unseen, before it.
_MAILBOX_ACTION_TTL = timedelta(hours=1, minutes=30)

#: A verification code a human is expected to type. Anything longer is not a
#: code, and the extension types what it is given.
_MAX_CODE_LENGTH = 12

#: Labels that mean the student has something to do or read now. The message
#: never carries the email's own words -- only who wrote and what kind of thing.
_ALERTS = {
    "DECISION": (
        RoadmapItem.Stage.MONITORING,
        "{domain} sent a decision. Open your portal to read it.",
    ),
    "INTERVIEW": (
        RoadmapItem.Stage.INTERVIEW,
        "{domain} invited you to an interview. Check the time and reply.",
    ),
    "DOCUMENT_REQUEST": (
        RoadmapItem.Stage.DOCUMENTS,
        "{domain} is asking for a document. Check what they need.",
    ),
    "FEE": (
        RoadmapItem.Stage.FEE_EXECUTION,
        "{domain} says a fee is due. Check the amount and the deadline.",
    ),
    # Never urgent (_alert_student): a student who registered a moment ago is
    # usually looking at the portal already, and on a trusted message the
    # extension opens the link itself. The card is for the mail nothing may
    # act on, so the student is told what it asks, never handed its link.
    "VERIFICATION": (
        RoadmapItem.Stage.MONITORING,
        "{domain} asked you to confirm your email address. "
        "Open the message in your inbox and use its link.",
    ),
}
_ALERT_HORIZON = timedelta(days=7)

#: The label card when a tag names a portal the student has several
#: applications on (final review I6b): the platform never guesses which, so
#: the card says where to look instead.
_SHARED_PORTAL = (
    "{domain} wrote about one of your {count} applications on {portal_host}. "
    "Open your portal to see which."
)


def _due_date(value: str) -> date | None:
    """The model's YYYY-MM-DD, or nothing: a date written any other way is not guessed at."""
    try:
        return date.fromisoformat(value.strip()) if value.strip() else None
    except ValueError:
        return None


def _interview_time(value: str, zone: str) -> datetime | None:
    """The model's ISO 8601 time, or nothing (controller amendment, 2026-10-04).

    A stated offset is kept. A time without one is read in the portal's own zone
    (Application.deadline_timezone), never UTC; with no usable zone it is not
    guessed at, and the item says to read the email for the time.
    """
    try:
        parsed = datetime.fromisoformat(value.strip()) if value.strip() else None
    except ValueError:
        return None
    if parsed is None or parsed.tzinfo is not None:
        return parsed
    where = zone_named(zone)
    return parsed.replace(tzinfo=where) if where is not None else None


def _local(moment: datetime, zone: str) -> datetime:
    """The moment in the portal's zone, or in UTC when it has none."""
    return moment.astimezone(zone_named(zone) or UTC)


def _zone_label(zone: str) -> str:
    return zone if zone_named(zone) is not None else "UTC"


def _alert_student(
    signal: MailSignal,
    label: str,
    *,
    urgent: bool = True,
    shared_portal: tuple[str, int] | None = None,
    trusted: bool = True,
) -> None:
    """``trusted=False`` (Task 11 minor): the sender is marked unverified, and
    nothing the mail states -- an interview's time -- is repeated or becomes
    the item's deadline (Task 10's trusted-only rule)."""
    if label not in _ALERTS:
        return
    urgent = urgent and label != "VERIFICATION"
    stage, text = _ALERTS[label]
    domain = signal.sender_domain if trusted else f"{signal.sender_domain} (unverified)"
    if shared_portal is not None:
        portal_host, count = shared_portal
        message = _SHARED_PORTAL.format(domain=domain, portal_host=portal_host, count=count)
    else:
        message = text.format(domain=domain)
    application = signal.application
    now = timezone.now()
    # Only a deadline still ahead: a past one would put every alert straight
    # onto the counsellor ladder (final review M1).
    deadline = application.deadline if application is not None else None
    # An interview's own time is the date its item is about (spec §8): it is what
    # Needs you now shows and sorts by. Shown in the portal's zone, labelled.
    if label == "INTERVIEW" and shared_portal is None and trusted:
        zone = application.deadline_timezone if application is not None else ""
        interview = signal.interview_at
        if interview is None:
            message = (
                f"{signal.sender_domain} invited you to an interview. "
                "See the email for the time, and reply."
            )
        elif interview > now:
            deadline = interview
            local = _local(interview, zone)
            # ponytail: an exact local midnight is read as "date only" (the
            # prompt's YYYY-MM-DD); a real midnight interview loses its time here.
            at = "" if (local.hour, local.minute) == (0, 0) else f", {local:%H:%M}"
            message = (
                f"{signal.sender_domain} invited you to an interview on "
                f"{local:%d %b %Y}{at} {_zone_label(zone)}. Check the time and reply."
            )
    student = signal.connection.membership
    Notification.raise_card(
        student=student,
        recipient=student,
        owner=student,
        stage=stage,
        deadline=deadline if deadline is not None and deadline > now else now + _ALERT_HORIZON,
        urgent=urgent,
        message=message,
        application=application,
        action=Notification.Action.OPEN_MESSAGE,
    )


def _verification_url(value: str, link_hosts: Iterable[str]) -> str:
    """The link, if it is one we are willing to hand to the student's browser.

    https only, no userinfo, no backslash, and a host on this student's
    `filter.link_hosts`: the FULL hosts the pack and the applications name,
    never the registrable keys mail is read under (security finding
    2026-09-26, vuln 1 -- kth.smapply.io's key smapply.io made every smapply
    customer's page a target). A mail from tum.de linking to evil.example is
    the case this exists for, and it reads exactly like a real verification
    mail.

    **The backslash is not decoration.** Python's urlsplit and a browser's
    WHATWG parser disagree about it: for `https://evil.example\\@tum.de/`,
    urlsplit reports `hostname="tum.de"` while Chrome reads the host as
    `evil.example`. Here that URL is already refused, because urlsplit also
    reports `username="evil.example\\"` and userinfo is refused -- measured,
    2026-09-18, not assumed. The explicit check closes the class rather than
    relying on a second guard to keep catching it, and returning
    `urlunsplit(parsed)` means what was validated is what gets opened.

    The extension re-parses with `new URL()` and checks only the scheme; it
    cannot re-derive this student's allowlist. So this function is the only
    host check on either side.

    **Deliberately checked against every link host, never narrowed to the
    message's own sender domain.** A portal vendor legitimately mails from one
    domain and links to another, e.g. mail.uni-bonn.de sending a link to the
    application's portal.uni-bonn.de -- narrowing to sender-only would break that
    real, ordinary flow. Known, accepted residual risk: an open redirect on
    any allowlisted host is not closed by this check either way, narrowed or
    not, so this stays a known tradeoff rather than an oversight.
    """
    if "\\" in value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        # urlsplit raises on some malformed input rather than reporting it as
        # unparseable (NFKC-normalized characters that collide with a
        # separator, a truncated IPv6 literal). This value is text the model
        # copied out of a hostile email, so a crash here is a crash a hostile
        # sender controls -- treated the same as any other unacceptable URL.
        return ""
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
        return ""
    if not host_in(parsed.hostname.casefold(), link_hosts):
        return ""
    return urlunsplit(parsed)


def apply_verdict(
    signal: MailSignal,
    verdict: MailVerdict,
    *,
    link_hosts: Iterable[str],
    authenticated: bool,
    vouched: bool = False,
    shared_portal: tuple[str, int] | None = None,
    reading: DecisionReading | None = None,
) -> DeviceAction | None:
    """Record the label, act on at most one thing, and return the action if any.

    Must be called inside a tenant transaction: it writes two tenant-scoped
    tables.

    **`authenticated` gates every ACTION, and nothing else.** The caller passes
    the message's *trust* (spec §3), not raw provider authentication: `From:`
    is a header anyone can write, and a message earns trust either by the
    provider authenticating its DMARC domain or by arriving at a tagged
    address we issued (and not from Junk) -- see sync.py. The allowlist says
    which domains this student's pack justifies READING; it says nothing on
    its own about who actually sent a message, so without a trust gate anyone
    who knows the student's address (or a leaked tag) could queue a link into
    their browser or mark their application confirmed, by typing a
    university's address into a From line.

    So an unauthenticated message still becomes a signal and still tells the
    student that someone claiming to be that institution wrote -- which is true,
    and useful -- but it moves no state and queues no device action. A Microsoft
    connection on the METADATA tier is unauthenticated by construction
    (`Mail.ReadBasic` exposes no verdict), so there only tagged mail acts. On
    the CONTENT tier sync.py reads Microsoft's own verdict for each kept
    message (providers.MicrosoftMailbox.delivery_verified), so pack mail can act
    there as it does on Gmail. That is the honest cost of the cheaper scope.

    ``vouched`` (final review I6a): the sender's domain is one the pack or an
    application vouches for -- not merely learned. An untrusted message from
    one still raises its label card, NOT urgent and never with a link, so a
    Microsoft student hears about a decision at all.

    ``shared_portal`` (final review I6b): (portal host, application count)
    when a trusted tag names a portal the student has several applications
    on; the label card then says so instead of naming the wrong one.

    ``reading`` (spec §4): Jev's one reading of the mail, or None when the
    mail is tied to no card. Stored on the signal trusted or not -- an untrusted
    one is shown as a claim -- and recorded on the application only behind the
    trust gate (portals/outcome.py::record_from_mail).
    """
    signal.label = verdict.label
    fields = ["label"]
    if verdict.label == "DOCUMENT_REQUEST":
        signal.document_name = verdict.document_name.strip()[:120]
        signal.document_due = _due_date(verdict.document_due)
        fields += ["document_name", "document_due"]
    if verdict.label == "INTERVIEW":
        zone = signal.application.deadline_timezone if signal.application is not None else ""
        signal.interview_at = _interview_time(verdict.interview_at, zone)
        fields.append("interview_at")
    if reading is not None:
        signal.decision_reading = reading.as_json()
        signal.outcome = reading.outcome
        signal.funding_outcome = reading.funding_outcome
        signal.outcome_conditions = (
            [c.strip() for c in verdict.outcome_conditions if c.strip()]
            if reading.outcome == "ADMITTED_CONDITIONAL"
            else []
        )
        # Jev says an offer is there; the classifier's verified quote names it.
        signal.offered_programme = (
            verdict.offered_programme.strip()[:120] if reading.other_programme_offered else ""
        )
        fields += [
            "decision_reading", "outcome", "funding_outcome", "outcome_conditions",
            "offered_programme",
        ]
    signal.save(update_fields=fields)

    if not authenticated:
        if vouched:
            _alert_student(signal, verdict.label, urgent=False, trusted=False)
        logger.info("signal %s carries no delivery authentication; not acting", signal.id)
        return None

    _alert_student(signal, verdict.label, shared_portal=shared_portal)

    application = signal.application
    if application is not None:
        if verdict.label == "RECEIVED" and application.state == Application.State.SUBMITTED:
            application.state = Application.State.CONFIRMED
            application.save(update_fields=["state"])
            ApplicationStep.objects.create(
                tenant_id=application.tenant_id,
                application=application,
                sequence=application.next_step_sequence(),
                kind=ApplicationStep.Kind.STATUS,
                detail={
                    "source": "mailbox",
                    "signal": str(signal.id),
                    "sender_domain": signal.sender_domain,
                    # The number, if the portal quoted one. Not the mail.
                    "application_number": verdict.application_number[:100],
                },
            )
        if reading is not None:
            record_from_mail(application, signal, reading)

    if verdict.action_kind == "OPEN_VERIFICATION_URL":
        url = _verification_url(verdict.action_value, link_hosts)
        if not url:
            # Logged without the value, which is the whole point.
            logger.warning("refused a verification link on signal %s", signal.id)
            return None
        return queue_action(
            signal.connection.membership,
            DeviceAction.Kind.OPEN_VERIFICATION_URL,
            {"url": url},
            application=application,
            ttl=_MAILBOX_ACTION_TTL,
        )

    if verdict.action_kind == "TYPE_CODE":
        code = verdict.action_value.strip()
        if not code or len(code) > _MAX_CODE_LENGTH or not code.isalnum():
            logger.warning("refused a verification code on signal %s", signal.id)
            return None
        return queue_action(
            signal.connection.membership,
            DeviceAction.Kind.TYPE_CODE,
            {"code": code},
            application=application,
            ttl=_MAILBOX_ACTION_TTL,
        )

    return None
