"""A student's applications as the dashboard changes them (spec §7, §4a).

Every function takes the ``actor`` who pressed -- the student, or their assigned
counsellor -- and leaves an AuditEvent naming them. Nothing here names the
submitted state (tests/portals/test_boundary.py).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
from collections import defaultdict
from datetime import timedelta
from functools import partial
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.db.models.signals import post_delete, post_save
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.dashboard.templatetags.dashboard import https_only
from apps.documents.document_queue import DocumentWorkMessage, enqueue_document_work
from apps.documents.table import sendable
from apps.funding.models import AuditEvent, RecommendationCandidate
from apps.funding.services import (
    LastInPack,
    PackCommandError,
    clear_overflow_pack_notes,
    reject_for_student,
)
from apps.mailbox.filter import host_in
from apps.mailbox.models import MailSignal
from apps.ratelimit import pack_command_rate_limited, rate_limited
from apps.research.hosts import registrable_domain
from apps.research.provenance import BLOCKED_REASONS, RECOGNISED_REASONS, WAITING_REASONS
from apps.tenancy.models import CounselorAssignment, Membership

from .actions import queue_action
from .award_links import link_awards
from .fees import fee_state_for
from .models import Application, DeviceAction, PortalForm
from .outcome import correct_outcome, is_funding_application, record_refusal_from_offer
from .pairing import active_pairings
from .prepare import queue_for_student
from .route_snapshot import snapshot_from_portal

logger = logging.getLogger(__name__)

#: Shared by Start application and Submit document: both put a device action in
#: front of the student's browser, so one budget covers both.
DEVICE_ACTION_LIMIT = 20
DEVICE_ACTION_WINDOW_SECONDS = 3600
_PORTAL_TASK_SLA = timedelta(days=3)

_SHARED_PROGRAM_PORTALS: dict[UUID, UUID] = {}
_KNOWN_PORTAL_PLATFORMS = (
    "uni-assist.de",
    "studielink.nl",
    "dreamapply.com",
    "moveon4.de",
    "smapply.io",
    "smapply.org",
    "smapply.ca",
    "embark.com",
    "applyweb.com",
    "commonapp.org",
    "ucas.com",
    "parcoursup.fr",
    "osiris-student.nl",
    "mobility-online.com",
    "fullfabric.com",
    "submittable.com",
)

_SHARED_PORTAL_HOSTS_CACHE_KEY = "portals:shared_platform_hosts:v1"
_SHARED_PORTAL_HOSTS_CACHE_TTL = 300


def _registrable_host(raw: str) -> str:
    """Extract the registrable domain (`eTLD+1`) from a URL or hostname."""
    text = (raw or "").strip()
    if not text:
        return ""
    host = (
        (urlsplit(text).hostname or "")
        if "://" in text
        else text.split("/")[0].split(":")[0]
    ).strip().casefold().rstrip(".")
    if not host or host.endswith(
        (".test", ".internal", ".example", ".invalid", ".localhost", ".arpa")
    ):
        return ""
    return registrable_domain(host)


def _host_matches_institution_names(host: str, inst_names: set[str]) -> bool:
    """Whether ``host``'s primary domain label matches a word or acronym of any associated
    institution name (so two name variants of the same institution, e.g. ``"TU Munich"``
    and ``"Technical University of Munich"``, never promote ``tum.de`` as a shared platform
    when ``Institution`` could not be queried)."""
    if not host or not inst_names:
        return False
    primary = host.split(".")[0].casefold()
    primary_compact = re.sub(r"[^a-z0-9]+", "", primary)
    primary_tokens = {tok for tok in re.split(r"[^a-z0-9]+", primary) if len(tok) >= 3}
    if len(primary_compact) >= 2:
        primary_tokens.add(primary_compact)
    if not primary_tokens:
        return False

    for raw_name in inst_names:
        folded = "".join(
            ch
            for ch in unicodedata.normalize("NFKD", raw_name)
            if not unicodedata.combining(ch)
        ).casefold()
        words = [w for w in re.split(r"[^a-z0-9]+", folded) if w]
        if not words:
            continue
        stopwords = {
            "the", "and", "for", "und", "der", "die", "das", "von", "van", "les", "des", "del",
        }
        content_words = [w for w in words if len(w) > 2 and w not in stopwords]
        name_tokens = {w for w in words if len(w) >= 2}
        if len(words) >= 2:
            name_tokens.add("".join(w[0] for w in words))
            name_tokens.add("".join(words))
        if len(content_words) >= 2:
            name_tokens.add("".join(w[0] for w in content_words))
            name_tokens.add("".join(content_words))
        if len(words) >= 2 and len(words[0]) <= 4:
            name_tokens.add(words[0] + "".join(w[0] for w in words[1:]))
            rest_content = [w for w in content_words if w != words[0]]
            if rest_content:
                name_tokens.add(words[0] + "".join(w[0] for w in rest_content))
        if primary_tokens & name_tokens:
            return True
    return False


def catalogue_shared_portal_hosts() -> frozenset[str]:
    """Discover registrable portal hosts shared by >= 2 distinct Institutions
    where the host is not the institution's own `official_website` domain.

    Cached in Django `cache` under `"portals:shared_platform_hosts:v1"` for 300s,
    and returns `frozenset()` gracefully when database tables are not ready or
    accessible under the active connection role.
    """
    cached = cache.get(_SHARED_PORTAL_HOSTS_CACHE_KEY)
    if isinstance(cached, frozenset):
        return cached
    if getattr(connection.ensure_connection, "__name__", "") == "_blocking_wrapper":
        return frozenset()

    try:
        own_domains_by_inst: dict[Any, set[str]] = defaultdict(set)
        all_own_domains: set[str] = set()
        inst_by_slug: dict[str, Any] = {}
        prog_to_inst: dict[Any, Any] = {}
        institutions_by_host: dict[str, set[Any]] = defaultdict(set)
        inst_names_by_host: dict[str, set[str]] = defaultdict(set)

        def _record(inst_key: Any, raw_url: str, inst_name: str | None = None) -> None:
            if not inst_key:
                return
            host = _registrable_host(raw_url)
            if not host:
                return
            if host in own_domains_by_inst.get(inst_key, set()) or host in all_own_domains:
                return
            institutions_by_host[host].add(inst_key)
            if isinstance(inst_name, str) and inst_name.strip():
                inst_names_by_host[host].add(inst_name.strip().casefold())
            elif isinstance(inst_key, str) and inst_key.strip():
                inst_names_by_host[host].add(inst_key.strip().casefold())

        skip_catalogue = bool(
            getattr(connection, "force_debug_cursor", False)
            or os.environ.get("DATABASE_ROLE") == "runtime_web"
            or "runtime_web" in str(connection.settings_dict.get("USER") or "")
        )
        catalogue_read = False
        if not skip_catalogue:
            from apps.funding.models import Institution, Program, ProgramEvidenceClaim

            inst_ok = False
            prog_ok = False
            try:
                with transaction.atomic():
                    for inst in Institution.objects.all():
                        inst_id = inst.id
                        own = _registrable_host(getattr(inst, "official_website", "") or "")
                        if own:
                            own_domains_by_inst[inst_id].add(own)
                            all_own_domains.add(own)
                            stem = own.split(".")[0]
                            if len(stem) >= 2:
                                inst_by_slug.setdefault(stem, inst_id)
                        ckey = (getattr(inst, "canonical_key", "") or "").strip().casefold()
                        if ckey:
                            inst_by_slug.setdefault(ckey, inst_id)
                            for tok in re.split(r"[^a-z0-9]+", ckey):
                                if len(tok) >= 3:
                                    inst_by_slug.setdefault(tok, inst_id)
                inst_ok = True
            except Exception as exc:
                logger.debug("shared portal institution scan degraded: %s", exc)

            try:
                with transaction.atomic():
                    for prog in Program.objects.all():
                        prog_inst_id = getattr(prog, "institution_id", None)
                        if not prog_inst_id:
                            continue
                        prog_to_inst[prog.id] = prog_inst_id
                        for attr in (
                            "application_url",
                            "source_url",
                            "cv_format_source_url",
                            "origin_domain",
                            "evidence_domain",
                        ):
                            val = getattr(prog, attr, "") or ""
                            if isinstance(val, str) and val.strip():
                                _record(prog_inst_id, val)
                    for claim_inst_id, canonical_url in ProgramEvidenceClaim.objects.values_list(
                        "program__institution_id", "evidence_claim__source__canonical_url"
                    ):
                        if claim_inst_id and canonical_url:
                            _record(claim_inst_id, canonical_url)
                prog_ok = True
            except Exception as exc:
                logger.debug("shared portal programme scan degraded: %s", exc)
            catalogue_read = inst_ok and prog_ok

        try:
            with transaction.atomic():
                for form in PortalForm.objects.all():
                    raw_url = (
                        getattr(form, "base_url", "")
                        or getattr(form, "form_url", "")
                        or getattr(form, "portal_host", "")
                    )
                    if not raw_url:
                        continue
                    explicit_inst = getattr(form, "institution_id", None)
                    if explicit_inst:
                        _record(explicit_inst, raw_url)
                    haystack = " ".join(
                        filter(
                            None,
                            [
                                getattr(form, "portal_host", ""),
                                getattr(form, "form_key", ""),
                                getattr(form, "form_url", ""),
                                getattr(form, "base_url", ""),
                            ],
                        )
                    ).casefold()
                    tokens = {t for t in re.split(r"[^a-z0-9]+", haystack) if len(t) >= 2}
                    for slug, inst_id in inst_by_slug.items():
                        if slug in tokens:
                            _record(inst_id, raw_url)
        except Exception as exc:
            logger.debug("shared portal form scan degraded: %s", exc)

        try:
            with transaction.atomic():
                for (
                    prog_id,
                    portal_host,
                    form_url,
                    cand_inst_id,
                    cand_inst_name,
                ) in Application.objects.filter(portal_form__isnull=False).values_list(
                    "program_id",
                    "portal_form__portal_host",
                    "portal_form__form_url",
                    "candidate__institution_id",
                    "candidate__institution_name",
                ):
                    inst_key = (
                        prog_to_inst.get(prog_id)
                        or cand_inst_id
                        or (cand_inst_name.strip().casefold() if cand_inst_name else None)
                    )
                    if inst_key:
                        _record(inst_key, form_url or portal_host, cand_inst_name)
        except Exception as exc:
            logger.debug("shared portal application scan degraded: %s", exc)

        try:
            with transaction.atomic():
                for (
                    cand_inst_name,
                    prog_id,
                    details,
                    funding_card,
                    evidence,
                ) in RecommendationCandidate.objects.values_list(
                    "institution_name",
                    "program_id",
                    "details",
                    "funding_card",
                    "evidence",
                ):
                    inst_key = (
                        prog_to_inst.get(prog_id)
                        or (cand_inst_name.strip().casefold() if cand_inst_name else None)
                    )
                    if not inst_key:
                        continue
                    for mapping in (details, funding_card, evidence):
                        if isinstance(mapping, dict):
                            for key in ("portal_url", "apply_url", "source_url"):
                                raw = mapping.get(key)
                                if isinstance(raw, str) and raw.strip():
                                    _record(inst_key, raw, cand_inst_name)
        except Exception as exc:
            logger.debug("shared portal candidate scan degraded: %s", exc)

        discovered = frozenset(
            host
            for host, insts in institutions_by_host.items()
            if len(insts) >= 2
            and (
                all_own_domains
                or not _host_matches_institution_names(host, inst_names_by_host.get(host, set()))
            )
        )
        if catalogue_read:
            cache.set(
                _SHARED_PORTAL_HOSTS_CACHE_KEY, discovered, timeout=_SHARED_PORTAL_HOSTS_CACHE_TTL
            )
        return discovered
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        logger.debug("catalogue_shared_portal_hosts degraded: %s", exc)
        return frozenset()


_CATALOGUE_PORTAL_SENDERS = frozenset({
    "Institution",
    "Program",
    "ProgramEvidenceClaim",
    "PortalForm",
    "Application",
    "RecommendationCandidate",
})


def _invalidate_shared_portal_hosts_cache(sender: object = None, **_kwargs: object) -> None:
    sender_name = getattr(sender, "__name__", "")
    if sender_name and sender_name not in _CATALOGUE_PORTAL_SENDERS:
        return
    try:
        cache.delete(_SHARED_PORTAL_HOSTS_CACHE_KEY)
    except Exception as exc:
        logger.debug("shared portal cache delete degraded: %s", exc)


for _sig in (post_save, post_delete):
    _sig.connect(
        _invalidate_shared_portal_hosts_cache,
        dispatch_uid=f"portals_shared_platform_hosts_{id(_sig)}",
    )


def known_portal_platforms() -> frozenset[str]:
    """Union of baseline `_KNOWN_PORTAL_PLATFORMS` and catalogue-discovered shared portal hosts."""
    return frozenset(_KNOWN_PORTAL_PLATFORMS) | catalogue_shared_portal_hosts()


def _is_shared_portal_platform(url: str) -> bool:
    """Whether ``url`` (or hostname) sits on a baseline or catalogue-discovered shared platform."""
    text = (url or "").strip()
    if not text:
        return False
    host = (
        (urlsplit(text).hostname or "")
        if "://" in text
        else text.split("/")[0].split(":")[0]
    ).strip().casefold().rstrip(".")
    if not host:
        return False
    return bool(host_in(host, known_portal_platforms()))

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
        "This portal does not allow filling tools, so the extension cannot apply here."
    ),
    "not_paired": "Connect the browser extension first (Settings, Extension).",
    "rate_limited": "Too many requests. Try again shortly.",
    "bad_url": "Enter the portal's full https:// address.",
    "last_in_pack": (
        "This is the only option left in your list, so it can't be removed. "
        "Add another option first."
    ),
    "pack_changed": "Your list just changed \u2014 reload and try again.",
    "provenance_blocked": "This programme can't be added: its institution did not pass our checks.",
    "provenance_checking": "This programme is still being checked. Try again shortly.",
    "provenance_unconfirmed": "This programme's recognition isn't confirmed, so it can't be added.",
    "not_eligible": "Your updated profile no longer meets this programme's requirements.",
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


def _parse_portal_url(form_url: str) -> tuple[str, str, str] | None:
    url = https_only(form_url)
    if not url or len(url) > 500:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    try:
        form_key = _form_key(parts.port, parts.path, parts.query, parts.fragment)
    except ValueError:
        return None
    if not registrable_domain(host) or host.rstrip(".").endswith(".arpa"):
        return None
    return host, form_key, url


def _portal_from_candidate(candidate: RecommendationCandidate | None) -> PortalForm | None:
    """Resolve or create a PortalForm from candidate metadata or a portal evidence URL."""
    if candidate is None:
        return None
    details = candidate.details if isinstance(candidate.details, dict) else {}
    funding_card = candidate.funding_card if isinstance(candidate.funding_card, dict) else {}
    for raw in (
        details.get("portal_url"),
        details.get("apply_url"),
        funding_card.get("portal_url"),
        funding_card.get("apply_url"),
    ):
        if isinstance(raw, str) and raw.strip():
            parsed = _parse_portal_url(raw.strip())
            if parsed is not None:
                host, form_key, url = parsed
                form, _ = PortalForm.objects.get_or_create(
                    portal_host=host, form_key=form_key, defaults={"form_url": url}
                )
                return form
    if candidate.evidence_id is not None:
        source_url = (candidate.evidence.source_url or "").strip()
        parsed = _parse_portal_url(source_url)
        if parsed is not None:
            host, form_key, url = parsed
            if not host.endswith(
                (".test", ".internal", ".example", ".invalid", ".localhost")
            ) and not host_in(host, ("example.edu", "example.com", "example.org", "example.net")):
                path = (urlsplit(url).path or "/").casefold()
                if _is_shared_portal_platform(url) or path.startswith(
                    ("/apply", "/portal", "/bewerbung")
                ):
                    form, _ = PortalForm.objects.get_or_create(
                        portal_host=host, form_key=form_key, defaults={"form_url": url}
                    )
                    return form
    return None


def _known_portal(
    target: UUID, candidate: RecommendationCandidate | None = None
) -> PortalForm | None:
    """A portal someone in this agency already recorded, cached cross-tenant, or on candidate."""
    form_id = (
        Application.objects.filter(program_id=target, portal_form__isnull=False)
        .values_list("portal_form_id", flat=True)
        .first()
    )
    if form_id is not None:
        portal = PortalForm.objects.filter(id=form_id).first()
        if portal is not None:
            _SHARED_PROGRAM_PORTALS[target] = portal.id
            return portal
    shared_id = _SHARED_PROGRAM_PORTALS.get(target)
    if shared_id is not None:
        portal = PortalForm.objects.filter(id=shared_id).first()
        if portal is not None:
            return portal
        _SHARED_PROGRAM_PORTALS.pop(target, None)
    portal = _portal_from_candidate(candidate)
    if portal is not None:
        _SHARED_PROGRAM_PORTALS[target] = portal.id
        return portal
    return None


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


def own_candidate(student: Membership, candidate_id: UUID) -> RecommendationCandidate | None:
    """A reviewed candidate from one of this student's own runs, or None."""
    return (
        RecommendationCandidate.objects.select_related("evidence")
        .filter(
            id=candidate_id,
            run__profile_version__student=student,
            state=RecommendationCandidate.State.VISIBLE,
        )
        .first()
    )


def add_application(*, student: Membership, candidate_id: UUID, actor: Membership) -> Application:
    """"Add to my applications" on a pack or pool item (spec §5, §7)."""
    if pack_command_rate_limited(student.id):
        raise ApplicationRefused("rate_limited")
    candidate = own_candidate(student, candidate_id)
    if candidate is None:
        raise ApplicationRefused("not_found")
    if not candidate.eligible:
        raise ApplicationRefused("not_eligible")
    if (candidate.funding_card or {}).get("route") == "AUTOMATIC_ON_ADMISSION":
        raise ApplicationRefused("comes_with_admission")
    # Provenance spec §7.5: the same check replace_candidate makes, from the
    # tenant copy the worker wrote. A body BLOCKED after the pack was shown
    # stays VISIBLE (with a "Cannot be added" note), so VISIBLE is not enough.
    code = candidate.provenance_reason_code
    if code in BLOCKED_REASONS:
        raise ApplicationRefused("provenance_blocked")
    if settings.PROVENANCE_GATE_ENFORCED and code not in RECOGNISED_REASONS:
        if not code or code in WAITING_REASONS:
            raise ApplicationRefused("provenance_checking")
        raise ApplicationRefused("provenance_unconfirmed")
    clear_overflow_pack_notes(candidate)
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
                portal=_known_portal(target, candidate=candidate), actor=actor,
                event="application.added",
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
        fee_state=fee_state_for(candidate),
    )
    if portal is None:
        _ask_for_portal(application, application.title)
    elif program_id:
        _SHARED_PROGRAM_PORTALS[program_id] = portal.id
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
    # A paid fee is touched too: deleting the card would erase the only record
    # of the payment the budget line counts (lanes final review I3).
    untouched = (
        application.state == Application.State.PREPARING
        and application.started_at is None
        and application.fee_state != Application.FeeState.PAID
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
    """No outcome, and not past READY_TO_SUBMIT."""
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
    # A cheap no-op in the worker when the prepared files are current.
    queue_for_student(application.tenant_id, application.student_id)
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
    parsed = _parse_portal_url(form_url)
    if parsed is None:
        raise ApplicationRefused("bad_url")
    host, form_key, url = parsed
    form, _created = PortalForm.objects.get_or_create(
        portal_host=host, form_key=form_key, defaults={"form_url": url}
    )
    if application.program_id:
        _SHARED_PROGRAM_PORTALS[application.program_id] = form.id
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
