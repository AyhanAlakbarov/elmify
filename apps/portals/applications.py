"""A student's applications as the dashboard changes them (spec §7, §4a).

Every function takes the ``actor`` who pressed -- the student, or their assigned
counsellor -- and leaves an AuditEvent naming them. Nothing here names the
submitted state (tests/portals/test_boundary.py).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from functools import partial
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.dashboard.templatetags.dashboard import https_only
from apps.documents.document_queue import DocumentWorkMessage, enqueue_document_work
from apps.documents.table import sendable
from apps.funding.models import AuditEvent, RecommendationCandidate
from apps.funding.services import LastInPack, PackCommandError, reject_for_student
from apps.mailbox.filter import host_in
from apps.mailbox.models import MailSignal
from apps.ratelimit import pack_command_rate_limited, rate_limited
from apps.research.hosts import registrable_domain
from apps.tenancy.models import CounselorAssignment, Membership

from .actions import queue_action
from .award_links import link_awards
from .models import Application, DeviceAction, PortalForm
from .outcome import correct_outcome, is_funding_application, record_refusal_from_offer
from .pairing import active_pairings
from .route_snapshot import snapshot_from_portal

logger = logging.getLogger(__name__)

#: Shared by Start application and Submit document: both put a device action in
#: front of the student's browser, so one budget covers both.
DEVICE_ACTION_LIMIT = 20
DEVICE_ACTION_WINDOW_SECONDS = 3600
_PORTAL_TASK_SLA = timedelta(days=3)

REFUSALS = {
    "not_found": "That programme is not in your list.",
    "comes_with_admission": (
        "This funding comes with the admission itself, so it has no application of its "
        "own: apply to the programme."
    ),
    "no_portal": (
        "We don't know this programme's application portal yet. Open the programme page; "
        "your counsellor has been asked to find it."
    ),
    "automation_prohibited": (
        "This portal does not allow filling tools. Use your Application Kit to apply by hand."
    ),
    "not_paired": "Connect the browser extension first (Settings, Extension).",
    "rate_limited": "Too many requests. Try again shortly.",
    "bad_url": "Enter the portal's full https:// address.",
    "last_in_pack": (
        "This is the only option left in your list, so it can't be removed. "
        "Add another option first."
    ),
    "pack_changed": "Your list just changed \u2014 reload and try again.",
    "document_unusable": "That document cannot be sent to this application.",
}


class ApplicationRefused(Exception):
    """Refused, with a stable reason; REFUSALS holds the sentence for each."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _audit(actor: Membership, event: str, application: Application) -> None:
    AuditEvent.objects.create(actor=actor, event=event, object_id=application.id)


def _queue_capture(tenant_id: UUID, student_id: UUID, application_id: UUID) -> None:
    """After commit, so the worker finds the row. A queue failure must not turn
    a successful add into an error page; adding the same card again re-queues."""
    try:
        enqueue_document_work(
            DocumentWorkMessage(
                action="capture_requirements", kind="KIT", tenant_id=tenant_id,
                student_id=student_id, application_id=application_id,
            ),
            queue_url=settings.DOCUMENT_QUEUE_URL,
        )
    except Exception as error:
        logger.warning(
            "could not queue capture_requirements for application %s (%s)",
            application_id, type(error).__name__,
        )


def _known_portal(target: UUID) -> PortalForm | None:
    """A portal someone in this agency already recorded for the programme."""
    form_id = (
        Application.objects.filter(program_id=target, portal_form__isnull=False)
        .values_list("portal_form_id", flat=True)
        .first()
    )
    return PortalForm.objects.filter(id=form_id).first() if form_id else None


def _ask_for_portal(application: Application, programme_name: str) -> None:
    """The counsellor task of spec §7. A direct student has no counsellor: their
    card's "Open programme page" is the whole answer."""
    assignment = (
        CounselorAssignment.objects.filter(student=application.student, active=True)
        .select_related("counselor")
        .first()
    )
    if assignment is None:
        return
    note = Notification.raise_card(
        student=application.student,
        recipient=assignment.counselor,
        owner=assignment.counselor,
        stage=RoadmapItem.Stage.APPLICATION_PREP,
        deadline=timezone.now() + _PORTAL_TASK_SLA,
        application=application,
        message=f"Find the application portal for {programme_name}.",
    )
    application.exception_item = note.roadmap_item
    application.save(update_fields=["exception_item"])


def add_application(*, student: Membership, candidate_id: UUID, actor: Membership) -> Application:
    """"Add to my applications" on a pack or pool item (spec §5, §7)."""
    if pack_command_rate_limited(student.id):
        raise ApplicationRefused("rate_limited")
    candidate = RecommendationCandidate.objects.filter(
        id=candidate_id,
        run__profile_version__student=student,
        state=RecommendationCandidate.State.VISIBLE,
    ).first()
    if candidate is None:
        raise ApplicationRefused("not_found")
    if (candidate.funding_card or {}).get("route") == "AUTOMATIC_ON_ADMISSION":
        raise ApplicationRefused("comes_with_admission")
    existing = _existing_card(student, candidate)
    if existing is not None:
        if not existing.kit_requirements and not existing.kit_letter_cycle:
            transaction.on_commit(
                partial(_queue_capture, existing.tenant_id, student.id, existing.id)
            )
        link_awards(existing, actor=actor)
        return existing
    # A named programme nobody resolved to a catalogue row has neither id; its
    # own id keeps program_id unique, and the kit then reads nothing for it.
    target = candidate.program_id or candidate.opportunity_id or candidate.id
    try:
        # A savepoint: a concurrent Add that inserted first makes this insert
        # fail on portal_app_one_per_candidate, and the request's transaction
        # must survive it to re-read that card.
        with transaction.atomic():
            card = _create(
                student, program_id=target, candidate=candidate, name="",
                portal=_known_portal(target), actor=actor, event="application.added",
                capture=True,
            )
    except IntegrityError:
        made = Application.objects.filter(student=student, candidate=candidate).first()
        if made is None:
            raise
        card = made
    link_awards(card, actor=actor)
    return card


def _existing_card(student: Membership, candidate: RecommendationCandidate) -> Application | None:
    return Application.objects.filter(student=student, candidate=candidate).first()


def _create(
    student: Membership,
    *,
    program_id: UUID,
    candidate: RecommendationCandidate | None,
    name: str,
    portal: PortalForm | None,
    actor: Membership,
    event: str,
    capture: bool,
) -> Application:
    """The one way a card is made: from a pack item, or from an accepted offer."""
    application = Application.objects.create(
        tenant_id=student.tenant_id,
        student=student,
        program_id=program_id,
        candidate=candidate,
        name=name,
        portal_form=portal,
        route_snapshot=snapshot_from_portal(portal),
    )
    if portal is None:
        _ask_for_portal(application, application.title)
    _audit(actor, event, application)
    if capture:
        transaction.on_commit(
            partial(_queue_capture, application.tenant_id, student.id, application.id)
        )
    return application


def offer_for(student: Membership, signal_id: UUID) -> MailSignal | None:
    """A trusted offer still waiting for Accept or Ignore, on one of this
    student's cards. Trusted, like the board that shows it (security review L5)."""
    return (
        MailSignal.objects.select_related("application__portal_form", "application__candidate")
        .filter(
            id=signal_id,
            connection__membership=student,
            application__student=student,
            trusted=True,
            offer_handled_at__isnull=True,
        )
        .exclude(offered_programme="")
        .first()
    )


def accept_offer(signal: MailSignal, *, actor: Membership) -> Application:
    """Accept on "<University> offers you a place in <programme>" (owner, 2026-10-04).

    A new card for the offered programme, through the same path as Add to my
    applications. It has no candidate -- the programme is in no pack -- so it
    carries the letter's name for it, and the signal's id as its program_id: a
    stable id no catalogue row has, so nothing is captured for its kit. It takes
    the original card's portal when the offer came from that portal's
    institution, otherwise it starts without one and the counsellor is asked.
    The original card's outcome becomes REJECTED only when an authenticated
    letter said so and no person recorded one (outcome.record_refusal_from_offer):
    the student's choice of card is harmless, a forged refusal is not.

    The signal is locked and re-read, so a double click makes one card: the
    second request finds the offer handled and is refused not_found.
    """
    signal = _lock_unhandled(signal)
    original = signal.application
    assert original is not None
    student = original.student
    form = original.portal_form
    # The offer was mailed from the institution the original portal belongs to.
    same = (
        form is not None
        and bool(signal.sender_domain)
        and bool(host_in(form.portal_host.casefold(), (signal.sender_domain.casefold(),)))
    )
    application = Application.objects.filter(student=student, program_id=signal.id).first()
    if application is None:
        application = _create(
            student,
            program_id=signal.id,
            candidate=None,
            name=signal.offered_programme,
            portal=form if same else None,
            actor=actor,
            event="application.offer_accepted",
            capture=False,
        )
    # signal.outcome is Jev's reading about the original card's own programme.
    record_refusal_from_offer(original, signal, actor=actor)
    signal.offer_handled_at = timezone.now()
    signal.save(update_fields=["offer_handled_at"])
    return application


def ignore_offer(signal: MailSignal, *, actor: Membership) -> None:
    """Ignore: the item goes away; the reading stays on the signal."""
    signal = _lock_unhandled(signal)
    signal.offer_handled_at = timezone.now()
    signal.save(update_fields=["offer_handled_at"])
    assert signal.application is not None
    _audit(actor, "application.offer_ignored", signal.application)


def _lock_unhandled(signal: MailSignal) -> MailSignal:
    """The signal, row-locked until the request's transaction ends, if still unhandled."""
    with transaction.atomic():
        locked = (
            MailSignal.objects.select_for_update()
            .filter(id=signal.id, offer_handled_at__isnull=True)
            .first()
        )
    if locked is None:
        raise ApplicationRefused("not_found")
    return locked


def _close_portal_task(application: Application) -> None:
    if application.exception_item_id is not None:
        RoadmapItem.objects.filter(id=application.exception_item_id).update(
            state=RoadmapItem.State.DONE
        )
        application.exception_item = None
        application.save(update_fields=["exception_item"])


def remove_application(application: Application, *, actor: Membership) -> None:
    """An untouched card is deleted; anything the portal may have seen is
    withdrawn instead, so the §5.5 trail survives."""
    if pack_command_rate_limited(application.student_id):
        raise ApplicationRefused("rate_limited")
    untouched = (
        application.state == Application.State.PREPARING
        and application.started_at is None
        and not application.steps.exists()
    )
    if not untouched:
        correct_outcome(application, Application.Outcome.WITHDRAWN, actor=actor)
        return
    try:
        with transaction.atomic():  # a refusal below keeps the card
            _close_portal_task(application)
            _audit(actor, "application.removed", application)
            application.delete()
            candidate = application.candidate
            if candidate is not None and is_funding_application(application):
                # Removing an award the student did not want keeps it off the board.
                reject_for_student(candidate, student=application.student, actor=actor)
    except LastInPack as error:
        raise ApplicationRefused("last_in_pack") from error
    except PackCommandError as error:
        raise ApplicationRefused("pack_changed") from error


def _require_device_ready(application: Application) -> None:
    form = application.portal_form
    if form is None:
        raise ApplicationRefused("no_portal")
    if form.terms_posture == PortalForm.TermsPosture.PROHIBITS_AUTOMATION:
        raise ApplicationRefused("automation_prohibited")
    if not active_pairings(application.student).exists():
        raise ApplicationRefused("not_paired")
    if rate_limited(
        "device-action",
        application.student_id,
        limit=DEVICE_ACTION_LIMIT,
        window_seconds=DEVICE_ACTION_WINDOW_SECONDS,
    ):
        raise ApplicationRefused("rate_limited")


def is_startable(application: Application) -> bool:
    """No outcome, and not past READY_TO_SUBMIT. The kit page asks the same."""
    # Named by what may start, not by the submitted states: nothing outside
    # ext_api.py and models.py names them (tests/portals/test_boundary.py).
    startable = application.state in (
        Application.State.PREPARING,
        Application.State.READY_TO_SUBMIT,
    ) or application.state.startswith("BLOCKED_")
    return startable and not application.outcome


def start_application(application: Application, *, actor: Membership) -> DeviceAction:
    """Marks the card in progress and queues START_FILL; spec B makes the
    extension open the portal and fill. The student presses, never a counsellor
    (spec §4a) -- the counsellor views never call this.

    A card with an outcome, or past READY_TO_SUBMIT, has nothing left to start:
    it is refused like a card that is not on the list (the board shows no Start
    for it either, so only a stale page or a forged POST gets here)."""
    if not is_startable(application):
        raise ApplicationRefused("not_found")
    _require_device_ready(application)
    if application.started_at is None:
        application.started_at = timezone.now()
        application.save(update_fields=["started_at"])
    action = queue_action(
        application.student, DeviceAction.Kind.START_FILL, {}, application=application
    )
    _audit(actor, "application.start_requested", application)
    return action


def queue_upload(
    application: Application, *, document_id: UUID, source: str, actor: Membership
) -> DeviceAction:
    """Spec §6 step 3: the extension opens this application's upload page.

    §5.6's "verify the document's intended application" is this argument: the
    caller resolved it from the item the student pressed, which names one
    application, never from the document. The document must be the one that
    application's cell holds, checked and usable (``sendable``) -- before the
    portal is even looked at, so an unusable document reads the same everywhere.
    """
    if not sendable(application, document_id=document_id, source=source):
        raise ApplicationRefused("document_unusable")
    _require_device_ready(application)
    action = queue_action(
        application.student,
        DeviceAction.Kind.OPEN_UPLOAD_PAGE,
        {"application_id": str(application.id), "document_id": str(document_id), "source": source},
        application=application,
    )
    _audit(actor, "application.upload_requested", application)
    return action


def record_portal(application: Application, form_url: str, *, actor: Membership) -> PortalForm:
    """A person recorded where this programme is applied for (spec §7).

    PortalForm is platform-shared: an existing (host, key) row is reused and
    never modified, so one agency's entry cannot rewrite a row another relies on.
    The key is everything after the host (review ruling 2, Task 9): portals that
    differ only by ``?programme=`` or by an SPA ``#/route`` are different forms,
    and must not collapse into one row every tenant fills from.

    The host must have a public registrable domain: no localhost, IP literal,
    single label, reserved name or ``.arpa`` name (``home.arpa`` is on the public
    suffix list, so registrable_domain alone accepts ``router.home.arpa``).
    Checked offline, never by resolving it. The student's browser opens this
    URL. The dormant server-side portal tier (shipped stopped at
    PortalDesiredCount 0, deleted by PR #169) is guarded at connect time by
    LocalEgressProxy, which is the check that holds against a public-looking
    name resolving privately; a record-time DNS lookup would not stop
    rebinding, so none is made.

    Every distinct URL is a new shared row, so this shares add and remove's
    per-student bucket (security review L3).
    """
    if pack_command_rate_limited(application.student_id):
        raise ApplicationRefused("rate_limited")
    url = https_only(form_url)
    if not url or len(url) > 500:
        raise ApplicationRefused("bad_url")
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    try:
        form_key = _form_key(parts.port, parts.path, parts.query, parts.fragment)
    except ValueError as error:  # a port urlsplit cannot read
        raise ApplicationRefused("bad_url") from error
    if not registrable_domain(host) or host.rstrip(".").endswith(".arpa"):
        raise ApplicationRefused("bad_url")
    form, _created = PortalForm.objects.get_or_create(
        portal_host=host, form_key=form_key, defaults={"form_url": url}
    )
    application.portal_form = form
    application.route_snapshot = snapshot_from_portal(form)
    application.save(update_fields=["portal_form", "route_snapshot"])
    _close_portal_task(application)
    _audit(actor, "application.portal_recorded", application)
    return form


_FORM_KEY_LENGTH = PortalForm._meta.get_field("form_key").max_length or 200


def _form_key(port: int | None, path: str, query: str, fragment: str) -> str:
    """The URL after its host: a non-default port, the path, the query, the fragment.

    Over the column's length it is the tail's sha256 hex instead -- never a cut,
    which would merge two forms sharing a long prefix. A hashed key cannot meet
    a literal one: a literal starts with "/" or ":".
    """
    tail = (f":{port}" if port not in (None, 443) else "") + (path or "/")
    tail += (f"?{query}" if query else "") + (f"#{fragment}" if fragment else "")
    if len(tail) > _FORM_KEY_LENGTH:
        return hashlib.sha256(tail.encode()).hexdigest()
    return tail
