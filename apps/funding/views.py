from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import QuerySet
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseNotAllowed,
)
from django.shortcuts import get_object_or_404, redirect, render

from apps.dashboard.locks import paused_reason
from apps.dashboard.pack import applied_candidate_ids
from apps.ratelimit import pack_command_rate_limited, rate_limited
from apps.research.provenance import (
    BLOCKED_REASONS,
    RECOGNISED_REASONS,
    WAITING_REASONS,
    blocked_note,
    candidate_note,
)
from apps.tenancy.models import CounselorAssignment, Membership
from apps.tenancy.services import current_membership

from .grouping import group_under_funding
from .models import PackCandidate, PackVersion, RecommendationCandidate, RecommendationRun
from .services import (
    PackCommandError,
    consider_named_program,
    current_pack,
    pool_funding_gap_totals,
    reject_candidate,
    replace_candidate,
    resolve_named_program,
)

#: Leaves headroom under RecommendationCandidate.program_name (varchar 300) and
#: ConsultantResearchTask.reason (varchar 200, minus the f-string prefix in
#: consider_named_program) so neither insert can ever DataError.
_PROGRAM_NAME_MAX_LENGTH = 150

_validate_https_url = URLValidator(schemes=["https"])


#: Per counsellor: every resolve queues a worker check that spends vendor fetches.
_NAMED_RESOLVE_RATE_LIMIT = 30
_NAMED_RESOLVE_RATE_WINDOW_SECONDS = 3600


def _is_htmx(request: HttpRequest) -> bool:
    # hx-boost sends HX-Request too, but a boosted form expects a full page
    # back (htmx swaps the response into <body>); only true fragment requests
    # may receive the bare partial.
    return (
        request.headers.get("HX-Request", "").lower() == "true"
        and request.headers.get("HX-Boosted", "").lower() != "true"
    )


def _clean_source_url(raw: str) -> str | None:
    """Return a validated https:// source URL, or None if invalid.

    Mirrors the intent of the ``official_source_url_https`` constraint on
    ``OfficialSource`` — evidence links must be a real, https-only URL, never a
    bare string that reaches an ``<a href>`` unvalidated.
    """
    url = raw.strip()
    if not url or len(url) > 2048:
        return None
    try:
        _validate_https_url(url)
    except ValidationError:
        return None
    return url


def _current_student(request: HttpRequest) -> Membership:
    return current_membership(request, Membership.Role.STUDENT)


def _pack_context(student: Membership) -> dict[str, object]:
    pack = current_pack(student)
    pool: list[PackCandidate] = []
    considered: QuerySet[RecommendationCandidate] = RecommendationCandidate.objects.none()
    totals: dict[str, Decimal] = {}
    #: Institutions (not programmes) whose check was still running when this
    #: pack was built -- the run's tenant copy, never the catalogue (spec §7.1).
    pending_count = 0
    if pack is not None:
        pending_count = len(pack.run.pending_bodies)
        pool = list(
            PackCandidate.objects.filter(pack_version=pack)
            .select_related("candidate__evidence")
            .order_by("candidate__program_name")
        )
        considered = (
            RecommendationCandidate.objects.filter(run_id=pack.run_id)
            .exclude(id__in=[member.candidate_id for member in pool])
            .exclude(state=RecommendationCandidate.State.REJECTED)
            .select_related("evidence")
            .order_by("program_name")
        )
        if settings.PROVENANCE_GATE_ENFORCED:
            # Verified-only: the student sees recognised bodies, a BLOCKED one
            # ("Cannot be added: ..."), and their own request still being
            # checked -- never another UNCONFIRMED code.
            considered = considered.filter(
                provenance_reason_code__in=[
                    "", *RECOGNISED_REASONS, *BLOCKED_REASONS, *WAITING_REASONS
                ]
            )
        totals = dict(pool_funding_gap_totals(pack))
    # Spec §5: "while research is still running" -- the first run, or a newer
    # one queued after this pack's (a changed profile).
    queued = RecommendationRun.objects.filter(
        profile_version__student=student, state=RecommendationRun.State.QUEUED
    )
    if pack is not None:
        queued = queued.exclude(id=pack.run_id).filter(created_at__gt=pack.run.created_at)
    research_pending = queued.exists()
    # "Cannot be added: ..." beside a BLOCKED one before the student tries --
    # rendered from the tenant copy the worker wrote, never the catalogue. A
    # student never reads "Recognition not confirmed" (verified-catalog §0.18).
    notes = {
        candidate.id: note
        for candidate in (*(member.candidate for member in pool), *considered)
        if (note := blocked_note(candidate.provenance_reason_code))
    }
    return {
        "pack": pack,
        "pool": pool,
        "considered": considered,
        # Only what replace accepts: a CHECKING candidate is refused (400).
        "replacements": [
            c for c in considered if c.state == RecommendationCandidate.State.VISIBLE
        ],
        "totals": totals,
        "pending_count": pending_count,
        "recognition_notes": notes,
        # Open awards head eligible programmes from both lists (owner,
        # 2026-10-04): the pack's awards also list the pool's programmes, and
        # the other way round, each marked with the list it lives in.
        "groups": group_under_funding(
            [member.candidate for member in pool],
            extra=list(considered),
            extra_label="in Other options",
        ),
        "other_groups": group_under_funding(
            list(considered),
            extra=[member.candidate for member in pool],
            extra_label="in your pack",
        ),
        "applied": applied_candidate_ids(student),
        "research_pending": research_pending,
        "pending_line": (
            ""
            if not pending_count
            else "1 institution is still being checked."
            if pending_count == 1
            else f"{pending_count} institutions are still being checked."
        ),
    }


def _render(request: HttpRequest, student: Membership) -> HttpResponse:
    context = _pack_context(student)
    if _is_htmx(request):
        return render(request, "student/_pack.html", context)
    return redirect("student-recommendation")


def _render_error(
    request: HttpRequest,
    student: Membership,
    message: str,
    *,
    status: int,
    error_form: str,
    error_field: str | None = None,
    form_values: dict[str, str] | None = None,
) -> HttpResponse:
    """Re-render the recommendation surface with an inline form error.

    Same contract as the counselor review error path (design-lint-baseline
    defect 5, extended to the student side): the caller's HTTP status is kept,
    ``error_form`` names the failing form ("named-program" or a candidate id),
    ``error_field`` the input it belongs under (None = form-level), and
    submitted values ride along so the student doesn't retype them.
    """
    context = _pack_context(student)
    context.update(
        {
            "error": message,
            "error_form": error_form,
            "error_field": error_field,
            "form_values": form_values or {},
        }
    )
    template = "student/_pack.html" if _is_htmx(request) else "student/recommendation_pool.html"
    return render(request, template, context, status=status)


@login_required
def recommendation(request: HttpRequest) -> HttpResponse:
    student = _current_student(request)
    return render(request, "student/recommendation_pool.html", _pack_context(student))


@login_required
def reject_candidate_view(request: HttpRequest, candidate_id: UUID) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    student = _current_student(request)
    if pack_command_rate_limited(student.id):
        return _render_error(
            request,
            student,
            "Too many requests. Try again shortly.",
            status=429,
            error_form=str(candidate_id),
        )
    pack = current_pack(student)
    if pack is None:
        raise Http404
    try:
        reject_candidate(pack, candidate_id, student)
    except PackCommandError as error:
        return _render_error(
            request, student, str(error), status=400, error_form=str(candidate_id)
        )
    return _render(request, student)


@login_required
def replace_candidate_view(request: HttpRequest, candidate_id: UUID) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    student = _current_student(request)
    if pack_command_rate_limited(student.id):
        return _render_error(
            request,
            student,
            "Too many requests. Try again shortly.",
            status=429,
            error_form=str(candidate_id),
        )
    pack = current_pack(student)
    if pack is None:
        raise Http404

    def _replace_error(message: str, *, field: str | None = None) -> HttpResponse:
        return _render_error(
            request, student, message, status=400, error_form=str(candidate_id), error_field=field
        )

    raw_replacement_id = request.POST.get("replacement_candidate_id")
    if not raw_replacement_id:
        return _replace_error(
            "A replacement program is required.", field="replacement_candidate_id"
        )
    try:
        replacement_id = UUID(raw_replacement_id)
    except ValueError:
        return _replace_error(
            "The replacement program was not recognized.", field="replacement_candidate_id"
        )
    try:
        replace_candidate(pack, candidate_id, replacement_id, student)
    except (PackCommandError, ValueError, ValidationError) as error:
        return _replace_error(str(error))
    return _render(request, student)


@login_required
def consider_named_program_view(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    student = _current_student(request)
    program_name = request.POST.get("program_name", "").strip()

    def _named_program_error(message: str, *, status: int) -> HttpResponse:
        return _render_error(
            request,
            student,
            message,
            status=status,
            error_form="named-program",
            error_field="program_name",
            form_values={"program_name": program_name},
        )

    if pack_command_rate_limited(student.id):
        return _named_program_error("Too many requests. Try again shortly.", status=429)
    pack = current_pack(student)
    if pack is None:
        raise Http404
    if not program_name:
        return _named_program_error("A program name is required.", status=400)
    if len(program_name) > _PROGRAM_NAME_MAX_LENGTH:
        return _named_program_error(
            f"Program names must be {_PROGRAM_NAME_MAX_LENGTH} characters or fewer.",
            status=400,
        )
    consider_named_program(pack, program_name, student)
    return _render(request, student)


def _current_counselor(request: HttpRequest) -> Membership:
    return current_membership(request, Membership.Role.COUNSELOR)


def _run_and_latest_pack(run_id: str | UUID) -> tuple[RecommendationRun, PackVersion]:
    """The latest pack version for a run, published or not.

    Used by the counselor review page and by resolve_named_program_view's
    error re-render — both need the latest version regardless of publish
    state, since packs publish automatically and there is no unpublished
    "awaiting review" version to prefer.
    """
    try:
        run = RecommendationRun.objects.get(id=run_id)
    except RecommendationRun.DoesNotExist as error:
        raise Http404 from error
    pack = PackVersion.objects.filter(run=run).order_by("-version").first()
    if pack is None:
        raise Http404
    return run, pack


def _review_page(
    request: HttpRequest,
    run: RecommendationRun,
    pack: PackVersion,
    *,
    status: int = 200,
    error: str | None = None,
    error_form: str | None = None,
    error_field: str | None = None,
    form_values: dict[str, str] | None = None,
) -> HttpResponse:
    """Render the counselor's read-only recommendation context and the
    named-program-resolution tool.

    Recommendation packs auto-publish (phased requirements.md §2.1); this page
    no longer has an approval action, only P1-13's read-only context for
    document tailoring plus P1-8's named-program resolution.
    """
    pool = PackCandidate.objects.filter(pack_version=pack).select_related("candidate__evidence")
    checking = (
        RecommendationCandidate.objects.filter(
            run=run, state=RecommendationCandidate.State.CHECKING
        )
        .select_related("evidence")
        .order_by("program_name")
    )
    # Spec §7.4: the counsellor sees each resolved named programme's verdict,
    # from the tenant code the worker wrote -- never the catalogue.
    named = [
        (candidate, _named_note(candidate.provenance_reason_code))
        for candidate in RecommendationCandidate.objects.filter(
            run=run, state=RecommendationCandidate.State.VISIBLE,
            program__isnull=True, opportunity__isnull=True,
        )
        .select_related("evidence")
        .order_by("program_name")
    ]
    return render(
        request,
        "counselor/review.html",
        {
            "pack": pack,
            "pool": pool,
            "checking": checking,
            "named": named,
            "error": error,
            "error_form": error_form,
            "error_field": error_field,
            "form_values": form_values or {},
        },
        status=status,
    )


def _named_note(code: str) -> str:
    if not code or code in WAITING_REASONS:
        return "Still being checked."
    return candidate_note(code)


@login_required
def review(request: HttpRequest, run_id: str) -> HttpResponse:
    counselor = _current_counselor(request)
    run, pack = _run_and_latest_pack(run_id)
    get_object_or_404(
        CounselorAssignment,
        counselor=counselor,
        student_id=run.profile_version.student_id,
        active=True,
    )
    return _review_page(request, run, pack)


@login_required
def resolve_named_program_view(
    request: HttpRequest, run_id: UUID, candidate_id: UUID
) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    counselor = _current_counselor(request)
    try:
        candidate = RecommendationCandidate.objects.get(id=candidate_id, run_id=run_id)
    except RecommendationCandidate.DoesNotExist as error:
        raise Http404 from error
    # Only the run's student's active counsellor: the error path below renders
    # that student's whole review page. Checked before the rate limit.
    student_id = (
        RecommendationRun.objects.filter(id=candidate.run_id)
        .values_list("profile_version__student_id", flat=True)
        .first()
    )
    assignment = get_object_or_404(
        CounselorAssignment.objects.select_related("student"),
        counselor=counselor,
        student_id=student_id,
        active=True,
    )
    paused = paused_reason(assignment.student)
    reason = request.POST.get("reason", "").strip()
    raw_source_url = request.POST.get("source_url", "")

    def _resolve_error(
        message: str, *, field: str | None = None, status: int = 400
    ) -> HttpResponse:
        run, pack = _run_and_latest_pack(run_id)
        return _review_page(
            request,
            run,
            pack,
            status=status,
            error=message,
            error_form=str(candidate.id),
            error_field=field,
            form_values={"reason": reason, "source_url": raw_source_url},
        )

    if paused is not None:
        return _resolve_error(paused, status=409)
    if rate_limited(
        "named-program-resolve",
        counselor.id,
        limit=_NAMED_RESOLVE_RATE_LIMIT,
        window_seconds=_NAMED_RESOLVE_RATE_WINDOW_SECONDS,
    ):
        return _resolve_error("Too many requests. Try again shortly.", status=429)
    if not reason:
        return _resolve_error("A rationale is required.", field="reason")
    source_url = _clean_source_url(raw_source_url)
    if source_url is None:
        return _resolve_error(
            "The official source must be a valid https:// URL.", field="source_url"
        )
    try:
        resolve_named_program(
            candidate,
            eligible=request.POST.get("eligible") == "true",
            reason=reason,
            source_url=source_url,
            actor=counselor,
        )
    except PackCommandError as error:
        return _resolve_error(str(error))
    return redirect("counselor-review", run_id=run_id)
