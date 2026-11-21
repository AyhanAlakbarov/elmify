"""The request package for one professor (lanes spec §11.3). The student sends it.

The platform never emails a third party: this module builds a page and one message the
student copies, and nothing here sends anything. It lists portal NAMES and the senders
the professor should expect, never how to apply (rule 11).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.concierge.models import DocumentVersion
from apps.dashboard.dates import both_zones, counting_deadline, funding_mandatory
from apps.portals.models import Application
from apps.portals.route_snapshot import read_snapshot
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .audit import record_event
from .evidence.readings import usable_readings
from .models import DocumentDraft, Referee, RefereeRequest, VerifiedFact
from .referee_evidence import SharedWorkItem, referee_angle, shared_work_for_referee
from .referee_views import _limited, _lock
from .verification import generatable_facts

#: What the student may mark; PROPOSED is the plan's, never a mark.
MARKS = ("ASKED", "AGREED", "DECLINED", "SUBMITTED")
_REF_REQ_WORDS = re.compile(r"recommendation|reference|referee", re.IGNORECASE)
#: What the professor does, per mode, in the message. Never a portal step.
_MODE_WORDS = {
    "PORTAL_INVITE": "the portal will email you an invitation to upload your letter",
    "REFEREE_SENDS": "the programme asks you to send the letter yourself",
    "UPLOAD_GENERIC": "a general letter that I upload is enough",
    "UPLOAD_ADDRESSED": "a letter addressed to the programme, which I upload",
}


@dataclass(frozen=True)
class CvLink:
    label: str
    #: "" when nothing serves the file back to the student (an upload: see Notes).
    url: str = ""


@dataclass(frozen=True)
class PackageLine:
    request: RefereeRequest
    title: str
    deadline: str
    portals: tuple[str, ...]
    senders: tuple[str, ...]
    looks_for: tuple[str, ...]
    co_referees: tuple[str, ...] = ()


def package_cv(student: Membership) -> CvLink | None:
    """The newest approved, rendered general CV, else the newest usable CV upload."""
    draft = (
        DocumentDraft.objects.filter(
            student=student, kind=DocumentDraft.Kind.CV, status=DocumentDraft.Status.APPROVED
        )
        .exclude(rendered_filename="")
        .order_by(F("programme_id").asc(nulls_first=True), "-version")
        .first()
    )
    if draft is not None:
        return CvLink(
            f"Your CV (version {draft.version})",
            reverse("documents-download", args=[draft.id, draft.rendered_filename]),
        )
    upload = (
        DocumentVersion.objects.filter(
            student=student, kind="CV", state="AVAILABLE", retired_at__isnull=True
        )
        .order_by("-created_at")
        .first()
    )
    if upload is not None:
        when = upload.created_at
        return CvLink(f"The CV you uploaded on {when.day} {when:%b %Y}")
    return None


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").casefold()
    except ValueError:
        return ""


def _portals(application: Application) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(portal names, sender hosts) from the card's own copies, never the catalogue."""
    names: list[str] = []
    hosts: list[str] = []
    if application.portal_form_id is not None:
        assert application.portal_form is not None
        hosts.append(application.portal_form.portal_host)
    snapshot = read_snapshot(application)
    for step in snapshot.steps if snapshot is not None else []:
        if step.portal_system and step.portal_system not in names:
            names.append(step.portal_system)
        host = _host(step.portal_url)
        if host and host not in hosts:
            hosts.append(host)
    return tuple(names or hosts), tuple(hosts)


def _fact_line(fact: VerifiedFact) -> str:
    p = fact.payload if isinstance(fact.payload, dict) else {}
    if fact.category == VerifiedFact.Category.EDUCATION:
        parts = [
            p.get("degree_english") or p.get("degree_as_awarded"),
            p.get("institution_english") or p.get("institution_original"),
            "–".join(str(d) for d in (p.get("start_date"), p.get("end_date")) if d),
            f"grade {p['grade_native']}" if p.get("grade_native") else "",
        ]
    elif fact.category == VerifiedFact.Category.EXPERIENCE:
        parts = [
            p.get("title"),
            p.get("employer"),
            "–".join(str(d) for d in (p.get("start_date"), p.get("end_date")) if d),
        ]
    else:
        parts = [
            p.get("thesis_title") or p.get("project_title"),
            f"supervised by {p['supervisor']}" if p.get("supervisor") else "",
            p.get("institution"),
        ]
    return ", ".join(str(part) for part in parts if part)


def _co_referee_label(other: Referee) -> str:
    kind_label = other.get_kind_display().lower()
    detail = f"{kind_label}, {other.institution}" if other.institution else kind_label
    return f"{other.label} ({detail})"


def package_lines(student: Membership, referee: Referee) -> list[PackageLine]:
    mandatory = funding_mandatory(student)
    open_requests = list(
        # Cards still waiting for a decision only: a withdrawn or decided card is not
        # something to ask a professor for (as referee_views._open_applications).
        referee.requests.exclude(state=RefereeRequest.State.DECLINED)
        .filter(application__outcome="")
        .select_related("application__candidate", "application__portal_form")
        .order_by("application__created_at")
    )
    app_ids = [r.application_id for r in open_requests]
    co_by_app: dict[UUID, list[str]] = {}
    if app_ids:
        for sibling in (
            RefereeRequest.objects.filter(application_id__in=app_ids, referee__student=student)
            .exclude(referee=referee)
            .exclude(state=RefereeRequest.State.DECLINED)
            .select_related("referee")
            .order_by("created_at")
        ):
            co_by_app.setdefault(sibling.application_id, []).append(
                _co_referee_label(sibling.referee)
            )
    lines = []
    for request in open_requests:
        application = request.application
        counted = counting_deadline(application, mandatory=mandatory)
        if counted is None:
            deadline = ""
        elif counted.at is None:
            deadline = counted.wording
        else:
            deadline = both_zones(counted.at, counted.zone, student.timezone)
        portals, senders = _portals(application)
        all_reqs = tuple(
            text for text in application.kit_requirements if isinstance(text, str)
        )
        ref_reqs = tuple(text for text in all_reqs if _REF_REQ_WORDS.search(text))
        lines.append(PackageLine(
            request=request,
            title=application.title,
            deadline=deadline,
            portals=portals,
            senders=senders,
            looks_for=ref_reqs or all_reqs,
            co_referees=tuple(co_by_app.get(application.id, ())),
        ))
    return lines


def package_message(
    student: Membership,
    referee: Referee,
    lines: list[PackageLine],
    cv: CvLink | None,
    shared_work: Sequence[SharedWorkItem] = (),
    angle: str = "",
) -> str:
    """One ready-to-send message, in the student's voice. The student sends it."""
    body = [f"Dear {referee.label},", "",
            "Thank you for supporting my applications. Here is where each letter goes:"]
    for line in lines:
        detail = [line.deadline and f"due {line.deadline}",
                  _MODE_WORDS.get(line.request.mode, "")]
        text = "; ".join(part for part in detail if part)
        body.append(f"- {line.title}" + (f": {text}" if text else ""))
    senders = sorted({host for line in lines for host in line.senders})
    if senders:
        body += ["", f"You may get emails from: {', '.join(senders)}."]
    if any(line.co_referees for line in lines) and angle:
        body += ["", f"Recommended focus for your letter: {angle}."]
    if shared_work:
        body += ["", "What we worked on together:"]
        for item in shared_work:
            body.append(f"- {item.summary}")
            for bullet in item.bullets:
                body.append(f"  * {bullet}")
    body += ["", ("I attach my CV" if cv is not None else "I will send you my CV")
             + " and a short sheet of what we worked on together.", "",
             "With thanks,", student.display_name]
    return "\n".join(body)


@login_required
def referee_package(request: HttpRequest, referee_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    referee = get_object_or_404(Referee, id=referee_id, student=student)
    lines = package_lines(student, referee)
    cv = package_cv(student)
    all_facts = list(generatable_facts(student))
    shared_work = shared_work_for_referee(
        referee,
        facts=all_facts,
        readings=usable_readings(student),
    )
    angle = referee_angle(referee, shared_work)
    facts = [
        _fact_line(fact)
        for fact in all_facts
        if fact.category
        in (
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.RESEARCH,
            VerifiedFact.Category.EXPERIENCE,
        )
    ]
    saved_request_id = str(request.session.pop("last_saved_referee_req", "") or "")
    return render(request, "student/referee_package.html", {
        "referee": referee,
        "lines": lines,
        "cv": cv,
        "shared_work": shared_work,
        "angle": angle,
        "facts": [line for line in facts if line],
        "message": package_message(student, referee, lines, cv, shared_work, angle),
        "marks": [(value, RefereeRequest.State(value).label) for value in MARKS],
        "saved_request_id": saved_request_id,
    })


@login_required
@require_POST
def referee_request_state(request: HttpRequest, request_id: UUID) -> HttpResponse:
    """The student marks one request asked, agreed, declined or submitted."""
    student = current_membership(request, Membership.Role.STUDENT)
    asked = get_object_or_404(
        RefereeRequest.objects.select_related("application", "referee"),
        id=request_id,
        referee__student=student,
    )
    state = request.POST.get("state", "")
    if state not in MARKS:
        messages.error(request, "Choose a status from the list.")
    elif not _limited(request, student):
        with transaction.atomic():
            _lock(student)
            # By id, under the lock: a swap in another tab may have deleted the row
            # first, and then this changes nothing (final review M1).
            changed = RefereeRequest.objects.filter(id=asked.id).update(
                state=state, updated_at=timezone.now()
            )
            if changed:
                record_event(actor=student, event="referee.request_state", object_id=asked.id)
                if state == RefereeRequest.State.DECLINED:
                    from .referee_views import repropose

                    repropose(student, reset=False)
                request.session["last_saved_referee_req"] = str(asked.id)
                label = RefereeRequest.State(state).label
                messages.success(
                    request,
                    f"Saved status for {asked.application.title}: {label}.",
                )
    if request.POST.get("next") == "/student/referees/plan/":
        return redirect("student-referee-plan")
    return redirect("student-referee-package", referee_id=asked.referee_id)
