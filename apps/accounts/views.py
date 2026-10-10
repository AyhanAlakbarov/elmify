from typing import Any

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from pydantic import ValidationError

from apps.concierge.cycles import paid_cycle
from apps.ratelimit import LOGIN_WINDOW_SECONDS, login_rate_limited
from apps.research.dispatch import dispatch_recommendation_run
from apps.tenancy.models import Membership

from .consultation import (
    QUESTION_LABELS,
    ConsultationDraft,
    clear_draft,
    consultation_progress,
    correction_key,
    finalize_consultation,
    next_profile_question,
    prefill_from_latest_reading,
    read_draft,
    validate_draft,
    write_draft,
)
from .forms import ConsultationQuestionForm, PlainAuthenticationForm
from .profile_versions import ProfileVersionRejected


def _is_htmx(request: HttpRequest) -> bool:
    # Same rule as apps/funding/views.py: a boosted form (base.html boosts
    # <main>) expects a whole page back, only a true fragment request gets one.
    return (
        request.headers.get("HX-Request", "").lower() == "true"
        and request.headers.get("HX-Boosted", "").lower() != "true"
    )


def _render_question(
    request: HttpRequest,
    draft: ConsultationDraft,
    *,
    form: ConsultationQuestionForm | None = None,
    error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    question = next_profile_question(draft)
    # next_profile_question() always resolves here (caller-guarded or
    # correction_key set) -- type-narrowing assert.
    assert question is not None
    answered, total = consultation_progress(draft)
    context = {
        "draft": draft,
        "question": question,
        "form": form or ConsultationQuestionForm(key=question.key, field=question.field_factory()),
        "progress_answered": answered,
        "progress_total": total,
        "error": error,
    }
    template = (
        "student/_consultation_step.html" if _is_htmx(request) else "student/consultation.html"
    )
    return render(request, template, context, status=status)


def _render_review(
    request: HttpRequest,
    draft: ConsultationDraft,
    *,
    error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    context = {
        "draft": draft,
        "error": error,
        "review": validate_draft(draft),
        "labels": QUESTION_LABELS,
    }
    template = (
        "student/_consultation_step.html" if _is_htmx(request) else "student/consultation.html"
    )
    return render(request, template, context, status=status)


def _render_current_state(
    request: HttpRequest,
    draft: ConsultationDraft,
    *,
    error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    """Render whichever wizard state the draft is in -- shared by the happy
    path and the two sequencing errors so neither loses the student's place.
    """
    if next_profile_question(draft) is not None:
        return _render_question(request, draft, error=error, status=status)
    try:
        return _render_review(request, draft, error=error, status=status)
    except ValidationError as validation_error:
        return _render_validation_error(request, draft, validation_error)


#: Why the answers, taken together, do not make a profile -- said to the
#: student on the question they are sent back to. Without a sentence the
#: wizard re-asks a question they already answered, silently, and they loop.
_CORRECTION_MESSAGES = {
    "profile_country_overlap": (
        "A country is both on your list and ruled out. Remove it from one of the two."
    ),
    "profile_language_evidence_mismatch": (
        "This certificate is for a language you did not list as one you could study in. "
        "Change its language, or leave this question empty."
    ),
    "profile_self_funding_missing": "Say how much you can cover yourself each year.",
    "profile_birth_date_future": "Your date of birth must be in the past.",
}


def _render_validation_error(
    request: HttpRequest, draft: ConsultationDraft, error: ValidationError
) -> HttpResponse:
    corrected = draft.with_correction(correction_key(error))
    write_draft(request.session, corrected)
    detail = error.errors()[0]
    reason = detail.get("msg", "it does not fit with your other answers")
    message = _CORRECTION_MESSAGES.get(
        str(detail.get("type", "")), f"Please check this answer: {reason}."
    )
    return _render_question(request, corrected, error=message, status=400)


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    assert request.user.pk is not None
    try:
        membership = Membership.objects.get(
            user_id=request.user.pk, role=Membership.Role.STUDENT, active=True
        )
    except Membership.DoesNotExist:
        # See templates/403.html: a bare-text 403 body would swap in as the
        # page under hx-boost, and this denial has no wizard state to re-render.
        raise PermissionDenied("tenant membership required") from None
    draft = read_draft(
        request.session,
        tenant_id=request.tenant.id,  # type: ignore[attr-defined]
        membership_id=membership.id,
    )
    prefilled = prefill_from_latest_reading(draft, membership=membership)
    if prefilled is not draft:
        write_draft(request.session, prefilled)
        draft = prefilled
    if request.method == "GET":
        return _render_current_state(request, draft)

    if request.POST.get("action") == "confirm":
        if next_profile_question(draft) is not None:
            return _render_current_state(
                request, draft, error="consultation is incomplete", status=400
            )
        if paid_cycle(membership.id) is None:
            # Spec R13: the programme search starts only for a paid academic-year cycle.
            return _render_current_state(
                request,
                draft,
                error="Your application cycle is not paid yet. The search starts once it is.",
                status=402,
            )
        try:
            _snapshot, run = finalize_consultation(membership=membership, draft=draft)
        except ValidationError as error:
            return _render_validation_error(request, draft, error)
        except (DatabaseError, ProfileVersionRejected):
            return _render_review(
                request,
                draft,
                error="Unable to start research. Please try again.",
                status=400,
            )
        clear_draft(request.session, draft)
        tenant_id = run.tenant_id
        run_id = run.id
        transaction.on_commit(
            lambda: dispatch_recommendation_run(tenant_id=tenant_id, run_id=run_id)
        )
        if _is_htmx(request):
            response = HttpResponse(status=204)
            response.headers["HX-Redirect"] = redirect("student-recommendation").url
            return response
        response = redirect("student-recommendation")
        response.headers["X-Run-ID"] = str(run.id)
        return response

    question = next_profile_question(draft)
    if question is None or request.POST.get("key") != question.key:
        return _render_current_state(
            request, draft, error="unexpected consultation question", status=400
        )
    form = ConsultationQuestionForm(
        key=question.key, field=question.field_factory(), data=request.POST
    )
    if not form.is_valid():
        return _render_question(request, draft, form=form, status=400)
    draft = draft.with_answer(question.key, form.cleaned_data["value"])
    write_draft(request.session, draft)
    return _render_current_state(request, draft)


class RateLimitedLoginView(LoginView):
    """Django's LoginView behind the JSON login's limiter (spec §1)."""

    form_class = PlainAuthenticationForm

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if login_rate_limited(request.POST.get("username", "")):
            context = self.get_context_data(form=self.form_class(request), rate_limited=True)
            response = self.render_to_response(context, status=429)
            response["Retry-After"] = str(LOGIN_WINDOW_SECONDS)
            return response
        return super().post(request, *args, **kwargs)
