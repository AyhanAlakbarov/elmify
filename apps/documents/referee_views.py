"""The student's referees (lanes spec §11.2): add a professor once, edit, mark them
declined or not answering.

Student only. The counsellor sees `referee_context(..., counselor_view=True)` read-only
on the board (apps/dashboard/views.py::_board_page); Elmify staff never see any of it,
because the staff page is files only (owner, 2026-10-11) and never builds this context.
Every write is rate-limited and audited, and the audit row carries ids, never the
professor's name.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.dashboard.dates import counting_deadline, funding_mandatory
from apps.portals.models import Application, ApplicationLink
from apps.portals.route_snapshot import read_snapshot
from apps.ratelimit import rate_limited
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .audit import record_event
from .models import Referee, RefereeRequest, VerifiedFact
from .referee_evidence import extract_supervisor_name_and_title, person_matches
from .referee_needs import NOT_STATED, RefereeNeed, Stated, needs_for
from .referee_plan import ApplicationNeed, Assignment, Proposal, RefereeFacts, propose
from .verification import unsuperseded_facts

#: Thirty edits an hour: a student adding their professors does a handful.
_LIMIT = 30
_WINDOW_SECONDS = 3600
_TOO_MANY = "Too many changes at once. Try again in a while."
#: Requests a professor has already been asked for: kept when the plan is proposed again.
_KEPT = ("ASKED", "AGREED", "SUBMITTED")
#: Out of the plan: their open requests are declined and the plan proposed again.
_OUT = ("DECLINED", "SILENT")
_FIELD_LABELS = (
    ("count", "Letters"),
    ("kind", "From"),
    ("mode", "How"),
    ("institutional_email_required", "University address required"),
    ("due", "When"),
)


class RefereeForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = Referee
        fields = (
            "title", "name", "institution", "email", "institutional_email", "kind",
            "relationship", "agreed_requests", "gives_generic_letter",
        )
        labels = {
            "title": "Title (Prof., Dr.)",
            "email": "Email address",
            "institutional_email": "This is their university address",
            "kind": "Academic or professional",
            "relationship": "How they know you (courses, grades, projects)",
            "agreed_requests": "How many portal requests they agreed to",
            "gives_generic_letter": "They will give me one general letter I can upload",
        }


def cv_referees(student: Membership, referees: list[Referee]) -> list[VerifiedFact]:
    """References and thesis/research supervisors read from the student's CV that are not
    referees yet: offered as a starting list, never added on their own. A reference the CV
    says not to contact is never offered."""
    from .verification import disowned_refs

    disowned = disowned_refs(student)
    base_facts = unsuperseded_facts(student).exclude(source_ref__in=disowned)
    known_emails = {r.email.casefold() for r in referees if r.email}
    known_names = [r.name for r in referees if r.name]
    offered: list[VerifiedFact] = []
    for fact in base_facts.filter(category=VerifiedFact.Category.REFERENCE):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        name = str(payload.get("name") or "").strip()
        email = str(payload.get("email") or "").strip()
        if not name or payload.get("do_not_contact"):
            continue
        if (email and email.casefold() in known_emails) or any(
            existing.casefold() == name.casefold() or person_matches(existing, name)
            for existing in known_names
        ):
            continue
        known_names.append(name)
        if email:
            known_emails.add(email.casefold())
        offered.append(fact)

    for fact in base_facts.filter(
        category__in=(
            VerifiedFact.Category.RESEARCH,
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.EXPERIENCE,
        )
    ):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        raw_supervisor = str(payload.get("supervisor") or "").strip()
        if not raw_supervisor:
            continue
        _title, clean_name = extract_supervisor_name_and_title(raw_supervisor)
        if not clean_name:
            continue
        if any(
            existing.casefold() == clean_name.casefold() or person_matches(existing, clean_name)
            for existing in known_names
        ):
            continue
        known_names.append(clean_name)
        inst = str(
            payload.get("institution")
            or payload.get("employer")
            or payload.get("institution_english")
            or payload.get("institution_original")
            or ""
        ).strip()
        fact.payload = {**payload, "name": raw_supervisor, "institution": inst}
        offered.append(fact)
    return offered


def referee_context(student: Membership, *, counselor_view: bool) -> dict[str, Any]:
    referees = list(Referee.objects.filter(student=student).order_by("created_at"))
    return {
        "referees": referees,
        # One edit form per professor, the student's only; auto_id keeps the ids apart.
        "rows": [
            (r, None if counselor_view else RefereeForm(instance=r, auto_id=f"id_{r.id}_%s"))
            for r in referees
        ],
        "counselor_view": counselor_view,
        "from_cv": [] if counselor_view else cv_referees(student, referees),
        "statuses": Referee.Status.choices,
    }


def _page(
    request: HttpRequest,
    student: Membership,
    form: RefereeForm,
    *,
    status: int = 200,
    editing: UUID | None = None,
) -> HttpResponse:
    """`form` is the add form, or, when `editing` names a referee, that referee's failed
    edit form (shown with its errors on their row) beside a fresh blank add form."""
    context = referee_context(student, counselor_view=False)
    if editing is not None:
        context["rows"] = [(r, form if r.id == editing else e) for r, e in context["rows"]]
        form = RefereeForm()
    context["form"] = form
    return render(request, "student/referees.html", context, status=status)


def _limited(request: HttpRequest, student: Membership) -> bool:
    if rate_limited(
        "referee-edit", student.id, limit=_LIMIT, window_seconds=_WINDOW_SECONDS
    ):
        messages.error(request, _TOO_MANY)
        return True
    return False


def _lock(student: Membership) -> None:
    """One student's referee writes run one after another: a double click or a second
    tab waits here instead of racing (apps/research/wallet.py::open_wallet). Call
    inside transaction.atomic."""
    Membership.objects.select_for_update().get(id=student.id)


@login_required
def referees_page(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    return _page(request, student, RefereeForm())


@login_required
@require_POST
def referee_add(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    if _limited(request, student):
        return redirect("student-referees")
    form = RefereeForm(request.POST)
    if not form.is_valid():
        return _page(request, student, form, status=400)
    with transaction.atomic():
        _lock(student)
        name, email = form.cleaned_data["name"], form.cleaned_data["email"]
        if Referee.objects.filter(
            student=student, name__iexact=name, email__iexact=email
        ).exists():
            # A double click, or the same professor typed twice.
            messages.info(request, f"{name} is already on your list.")
            return redirect("student-referees")
        referee = form.save(commit=False)
        referee.student = student
        referee.save()
        record_event(actor=student, event="referee.added", object_id=referee.id)
    return redirect("student-referees")


@login_required
@require_POST
def referee_from_cv(request: HttpRequest, fact_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    fact = get_object_or_404(
        VerifiedFact,
        id=fact_id,
        student=student,
        category__in=(
            VerifiedFact.Category.REFERENCE,
            VerifiedFact.Category.RESEARCH,
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.EXPERIENCE,
        ),
        superseded_by__isnull=True,
    )
    payload = fact.payload if isinstance(fact.payload, dict) else {}
    if fact.category == VerifiedFact.Category.REFERENCE:
        if not payload.get("name") or payload.get("do_not_contact"):
            raise Http404  # never offered (cv_referees), so never added
        name = str(payload["name"])[:200]
        title = str(payload.get("position") or "")[:60]
        institution = str(payload.get("institution") or "")[:300]
        email = str(payload.get("email") or "")[:320]
        relationship = ""
    else:
        raw_sup = str(payload.get("supervisor") or "").strip()
        title, name = extract_supervisor_name_and_title(raw_sup)
        if not name:
            raise Http404
        institution = str(
            payload.get("institution")
            or payload.get("employer")
            or payload.get("institution_english")
            or payload.get("institution_original")
            or ""
        )[:300]
        email = ""
        thesis = str(
            payload.get("thesis_title")
            or payload.get("project_title")
            or payload.get("title")
            or ""
        ).strip()
        relationship = (f"Supervised: {thesis}" if thesis else "")[:1000]
    ref_kind = (
        Referee.Kind.PROFESSIONAL
        if (fact.category == VerifiedFact.Category.EXPERIENCE and not title)
        else Referee.Kind.ACADEMIC
    )
    if _limited(request, student):
        return redirect("student-referees")
    with transaction.atomic():
        _lock(student)
        # Re-checked under the lock: a second click finds them added and changes nothing.
        if fact not in cv_referees(student, list(Referee.objects.filter(student=student))):
            return redirect("student-referees")
        referee = Referee.objects.create(
            student=student,
            name=name,
            title=title,
            institution=institution,
            email=email,
            kind=ref_kind,
            relationship=relationship,
        )
        record_event(actor=student, event="referee.added", object_id=referee.id)
    messages.success(request, "Added. Now say how many portal requests they agreed to.")
    return redirect("student-referees")


@login_required
@require_POST
def referee_edit(request: HttpRequest, referee_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    referee = get_object_or_404(Referee, id=referee_id, student=student)
    if _limited(request, student):
        return redirect("student-referees")
    form = RefereeForm(request.POST, instance=referee)
    if not form.is_valid():
        return _page(request, student, form, status=400, editing=referee.id)
    with transaction.atomic():
        _lock(student)
        name, email = form.cleaned_data["name"], form.cleaned_data["email"]
        if (
            Referee.objects.filter(student=student, name__iexact=name, email__iexact=email)
            .exclude(id=referee.id)
            .exists()
        ):
            messages.info(request, f"{name} is already on your list.")
            return redirect("student-referees")
        form.save()
        record_event(actor=student, event="referee.updated", object_id=referee.id)
        messages.success(request, f"Saved changes to {referee.label}.")
    return redirect("student-referees")


@login_required
@require_POST
def referee_status(request: HttpRequest, referee_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    referee = get_object_or_404(Referee, id=referee_id, student=student)
    status = request.POST.get("status", "")
    if status not in Referee.Status.values:
        messages.error(request, "Choose a status from the list.")
        return redirect("student-referees")
    if _limited(request, student):
        return redirect("student-referees")
    with transaction.atomic():
        referee.status = status
        referee.save(update_fields=["status", "updated_at"])
        record_event(actor=student, event="referee.status", object_id=referee.id)
        if status in _OUT:
            # Swap referee (spec §11.2): their open requests are declined and the plan
            # is proposed again without them. A submitted letter stays submitted.
            referee.requests.filter(state=RefereeRequest.State.PROPOSED).delete()
            referee.requests.filter(state__in=("ASKED", "AGREED")).update(
                state=RefereeRequest.State.DECLINED
            )
            # Fills the gaps only: the student's own edits to the proposal stay.
            repropose(student, reset=False)
            messages.success(request, f"We planned your letters again without {referee.label}.")
        else:
            messages.success(
                request, f"Saved status for {referee.label}: {referee.get_status_display()}."
            )
    return redirect("student-referees")


def _open_applications(student: Membership) -> list[Application]:
    """Cards still waiting for a decision: a withdrawn or decided card needs no letter."""
    return list(
        Application.objects.filter(student=student, outcome="")
        .select_related("candidate", "portal_form")
        .order_by("created_at")
    )


def application_needs(
    student: Membership, applications: list[Application]
) -> list[tuple[Application, RefereeNeed, ApplicationNeed]]:
    """Each card's referee need, read from its candidate's copy (never Program)."""
    mandatory = funding_mandatory(student)
    # Spec §11.2's funding-deciding applications: a programme an award card on the
    # board pays for. Links run award -> programme only (portals/award_links._link),
    # so an award's own card, which states no letters, is never marked.
    funded = set(
        ApplicationLink.objects.filter(
            to_app__in=applications, from_app__student=student,
            from_app__candidate__opportunity__isnull=False,
        ).values_list("to_app_id", flat=True)
    )
    rows = []
    for application in applications:
        candidate = application.candidate
        records = candidate.referee_requirements if candidate is not None else []
        award = candidate is not None and candidate.opportunity_id is not None
        snapshot = read_snapshot(application)
        need = needs_for(
            records if isinstance(records, list) else [],
            route_kind=snapshot.kind if snapshot is not None else "",
            award=award,
        )
        counted = counting_deadline(application, mandatory=mandatory)
        rows.append((application, need, ApplicationNeed(
            application_id=application.id,
            title=application.title,
            letters=need.letters,
            kind=need.kind.value if need.kind is not None else "",
            mode=need.mode.value if need.mode is not None else "",
            institutional_email=need.institutional_email,
            deadline=counted.at if counted is not None else None,
            funding_deciding=application.id in funded,
        )))
    return rows


def _facts(referees: list[Referee]) -> list[RefereeFacts]:
    return [
        RefereeFacts(
            r.id, r.label, r.kind, r.agreed_requests, r.gives_generic_letter,
            r.institutional_email,
        )
        for r in referees
        if r.status == Referee.Status.ACTIVE
    ]


def _plan_inputs(
    student: Membership, *, keep: tuple[str, ...]
) -> tuple[list[tuple[Application, RefereeNeed, ApplicationNeed]], list[RefereeFacts],
           list[Assignment], list[tuple[UUID, UUID]]]:
    rows = application_needs(student, _open_applications(student))
    referees = list(Referee.objects.filter(student=student).order_by("created_at"))
    requests = RefereeRequest.objects.filter(referee__student=student)
    kept = [
        Assignment(q.application_id, q.referee_id, q.mode)
        # A submitted letter fills its slot whatever its professor's status became.
        for q in requests.filter(state__in=keep).filter(
            Q(state=RefereeRequest.State.SUBMITTED) | Q(referee__status=Referee.Status.ACTIVE)
        )
        # A proposal on a card since decided is a request nobody will make (review M2).
        .exclude(Q(state=RefereeRequest.State.PROPOSED) & ~Q(application__outcome=""))
    ]
    declined = [
        (q.application_id, q.referee_id)
        for q in requests.filter(state=RefereeRequest.State.DECLINED)
    ]
    return rows, _facts(referees), kept, declined


@transaction.atomic
def repropose(student: Membership, *, reset: bool = True) -> Proposal:
    """Propose who writes for what; asked ones are kept. `reset` (the student's own
    "Propose a plan") replaces every PROPOSED request with a fresh proposal; without it
    (after a swap) the PROPOSED ones stay -- the student may have edited them, spec
    §11.2 -- and only the gaps are filled."""
    _lock(student)  # a second tab waits here, then sees this one's rows
    if reset:
        RefereeRequest.objects.filter(
            referee__student=student, state=RefereeRequest.State.PROPOSED
        ).delete()
    rows, facts, kept, declined = _plan_inputs(
        student, keep=_KEPT if reset else (*_KEPT, "PROPOSED")
    )
    proposal = propose([n for _a, _n, n in rows], facts, kept=kept, declined=declined)
    for made in proposal.assignments:
        RefereeRequest.objects.create(
            referee_id=made.referee_id, application_id=made.application_id,
            mode=made.mode or RefereeRequest.Mode.NOT_STATED,
        )
    return proposal


def _stated(need: RefereeNeed, field: str) -> Stated | None:
    value = getattr(need, field)
    return value if isinstance(value, Stated) else None


@login_required
def referee_plan_page(request: HttpRequest) -> HttpResponse:
    """The plan: what each application needs, who is proposed or asked, and what is short."""
    student = current_membership(request, Membership.Role.STUDENT)
    rows, facts, current, declined = _plan_inputs(student, keep=(*_KEPT, "PROPOSED"))
    # Measured against the plan as it stands, so "too few" says what is still missing.
    shortfall = propose([n for _a, _n, n in rows], facts, kept=current, declined=declined)
    requests = list(
        RefereeRequest.objects.filter(referee__student=student)
        .exclude(state=RefereeRequest.State.DECLINED)
        .select_related("referee")
    )
    lines = [
        {
            "application": application,
            "fields": [(label, _stated(need, field)) for field, label in _FIELD_LABELS],
            "has_stated": any(_stated(need, field) is not None for field, _label in _FIELD_LABELS),
            "other_conditions": need.other_conditions,
            # Flagged where a university address is required and theirs is not one.
            "requests": [
                (q, need.institutional_email and not q.referee.institutional_email)
                for q in requests if q.application_id == application.id
            ],
        }
        for application, need, _n in rows
    ]
    return render(request, "student/referee_plan.html", {
        "lines": lines,
        "short": shortfall.short,
        "not_stated": NOT_STATED,
        "active": list(Referee.objects.filter(student=student, status=Referee.Status.ACTIVE)),
        "marks": [
            (value, RefereeRequest.State(value).label)
            for value in ("ASKED", "AGREED", "SUBMITTED", "DECLINED")
        ],
    })


@login_required
@require_POST
def referee_propose(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    if not _limited(request, student):
        proposal = repropose(student)
        record_event(actor=student, event="referee.plan_proposed", object_id=student.id)
        if proposal.assignments:
            count = len(proposal.assignments)
            messages.success(
                request,
                f"Updated referee plan: proposed {count} assignment{'s' if count != 1 else ''}. "
                "Referees you already asked or who agreed were kept.",
            )
        elif RefereeRequest.objects.filter(referee__student=student, state__in=_KEPT).exists():
            messages.info(
                request,
                "All open applications with stated letter requirements are already covered by "
                "referees you asked or who agreed. Remove or change a referee's status below "
                "to re-plan.",
            )
        else:
            messages.info(
                request,
                "No automatic referee assignments could be proposed yet — add an active referee "
                "or assign one directly to each application below.",
            )
    return redirect("student-referee-plan")


@login_required
@require_POST
def referee_request_remove(request: HttpRequest, request_id: UUID) -> HttpResponse:
    """Edit the proposal: take one proposed request off. Marked DECLINED, not deleted, so
    no later proposal puts it back until the student adds it again (Add flips it back).
    An asked one is marked through its own states, never removed here."""
    student = current_membership(request, Membership.Role.STUDENT)
    proposed = get_object_or_404(
        RefereeRequest, id=request_id, referee__student=student,
        state=RefereeRequest.State.PROPOSED,
    )
    if not _limited(request, student):
        with transaction.atomic():
            _lock(student)
            RefereeRequest.objects.filter(
                id=proposed.id, state=RefereeRequest.State.PROPOSED
            ).update(state=RefereeRequest.State.DECLINED, updated_at=timezone.now())
        record_event(actor=student, event="referee.request_removed", object_id=request_id)
    return redirect("student-referee-plan")


@login_required
@require_POST
def referee_request_add(request: HttpRequest) -> HttpResponse:
    """Edit the proposal: put one active professor on one application."""
    student = current_membership(request, Membership.Role.STUDENT)
    try:
        referee_id = UUID(request.POST.get("referee_id", ""))
        application_id = UUID(request.POST.get("application_id", ""))
    except ValueError:
        raise Http404 from None
    referee = get_object_or_404(
        Referee, id=referee_id, student=student, status=Referee.Status.ACTIVE
    )
    # Only a card still waiting for a decision, as _open_applications.
    application = get_object_or_404(Application, id=application_id, student=student, outcome="")
    if _limited(request, student):
        return redirect("student-referee-plan")
    need = application_needs(student, [application])[0][1]
    mode = need.mode.value if need.mode is not None else RefereeRequest.Mode.NOT_STATED
    with transaction.atomic():
        _lock(student)
        made, created = RefereeRequest.objects.get_or_create(
            referee=referee, application=application, defaults={"mode": mode}
        )
        if not created and made.state != RefereeRequest.State.DECLINED:
            messages.error(request, f"{referee.label} is already on {application.title}.")
            return redirect("student-referee-plan")
        if not created:
            # They declined or went silent, and the student puts them back (spec §11.2).
            made.state, made.mode = RefereeRequest.State.PROPOSED, mode
            made.save(update_fields=["state", "mode", "updated_at"])
        record_event(actor=student, event="referee.request_added", object_id=made.id)
    return redirect("student-referee-plan")
