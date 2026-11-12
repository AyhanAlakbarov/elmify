import logging
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from pydantic import ValidationError

from apps.concierge.cycles import paid_cycle
from apps.dashboard.board import Board, Card, board_for
from apps.dashboard.money import budget_line, in_home, whole
from apps.dashboard.money import counts_toward_budget as _counts
from apps.funding.models import AuditEvent
from apps.funding.views import _is_htmx
from apps.portals.applications import REFUSALS, ApplicationRefused, remove_application
from apps.portals.models import Application
from apps.portals.pairing import revoke_all_for
from apps.ratelimit import LOGIN_WINDOW_SECONDS, login_rate_limited, rate_limited
from apps.research.dispatch import dispatch_recommendation_run
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .consultation import (
    QUESTION_LABELS,
    ConsultationDraft,
    clear_draft,
    consultation_progress,
    correction_key,
    default_currency_for_draft,
    finalize_consultation,
    late_reading,
    next_profile_question,
    prefill_from_latest_reading,
    previous_question_key,
    read_draft,
    seed_from_latest_profile,
    use_reading,
    validate_draft,
    write_draft,
)
from .field_taxonomy import resolve_field_taxonomy
from .forms import (
    DURATION_TICK_OPTIONS,
    MONEY_PRESETS,
    POPULAR_DESTINATIONS,
    POPULAR_FIELDS,
    POPULAR_TEACHING_LANGUAGES,
    PRIORITY_TICK_OPTIONS,
    ConsultationQuestionForm,
    PlainAuthenticationForm,
    date_presets_for_question,
)
from .models import StudentProfileVersion
from .profile_versions import ProfileVersionRejected, create_profile_version
from .schemas import Money, StudentProfileSnapshot

logger = logging.getLogger(__name__)


_ANGLOPHONE_CODES = frozenset({"GB", "UK", "US", "CA", "AU", "IE", "NZ"})


def _default_question_seed(draft: ConsultationDraft, key: str) -> object:
    if key in {"self_funding_capacity", "application_budget", "budget_stretch"}:
        return {"amount": None, "currency": default_currency_for_draft(draft)}
    if key == "country_of_residence" and isinstance(draft.answer("nationality"), str):
        return draft.answer("nationality")
    if key == "acceptable_teaching_languages":
        return ["English"]
    if key == "intended_intake":
        presets = date_presets_for_question("intended_intake")
        if len(presets) >= 3:
            return presets[2][0]
    return None


def _interest_suggestions_for(
    draft: ConsultationDraft, key: str
) -> tuple[tuple[str, str], ...]:
    if key != "research_interests":
        return ()
    raw_field = str(draft.answer("target_field") or "").strip()
    if not raw_field:
        return ()
    res = resolve_field_taxonomy(raw_field)
    if res.orientations:
        return tuple(
            (ori.degree_titles[0] if ori.degree_titles else ori.label, ori.label)
            for ori in res.orientations
        )
    return tuple((title, title) for title in res.canonical_degree_titles[:8])


def _selected_ticks_for(key: str, seed: object) -> set[str]:
    if key in {"allowed_countries", "excluded_countries"} and isinstance(seed, (list, tuple)):
        return {str(x).strip().upper() for x in seed if str(x).strip()}
    if key in {"acceptable_teaching_languages", "research_interests"} and isinstance(
        seed, (list, tuple)
    ):
        return {str(x).strip() for x in seed if str(x).strip()}
    if key in {"intended_intake", "expected_completion"} and isinstance(seed, str):
        return {seed.strip()}
    if key == "additional_notes":
        selected: set[str] = set()
        note_str = seed.casefold() if isinstance(seed, str) else ""
        for phrase, _ in (*PRIORITY_TICK_OPTIONS, *DURATION_TICK_OPTIONS):
            if phrase and phrase.casefold() in note_str:
                selected.add(phrase)
        if not any(phrase and phrase in selected for phrase, _ in DURATION_TICK_OPTIONS):
            selected.add("")
        return selected
    return set()


def _language_context_note_for(draft: ConsultationDraft, key: str) -> str:
    if key != "language_evidence":
        return ""
    acad = draft.answer("academic_history")
    if not isinstance(acad, list):
        return ""
    for rec in acad:
        if not isinstance(rec, dict):
            continue
        cc = str(rec.get("country_code") or "").strip().upper()
        if not cc or cc in _ANGLOPHONE_CODES:
            continue
        inst = str(rec.get("institution") or "").strip()
        inst_label = inst or f"your institution ({cc})"
        if rec.get("completed_on"):
            return (
                f"Note for {inst_label}: studying in English outside an official "
                "English-speaking country does not automatically replace IELTS/TOEFL "
                "unless the target programme explicitly accepts a Medium of "
                "Instruction (MOI) waiver. Enter your official test score below, "
                "or skip if none."
            )
        return (
            f"Note for {inst_label}: a prior degree only qualifies for Medium of "
            "Instruction (MOI) language waivers upon graduation, and only at "
            "programmes that explicitly accept MOI instead of an official test. "
            "Enter your IELTS/TOEFL score (or planned test date) below, or skip."
        )
    return ""


def _render_question(
    request: HttpRequest,
    draft: ConsultationDraft,
    *,
    form: ConsultationQuestionForm | None = None,
    initial_value: object = None,
    error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    question = next_profile_question(draft)
    # next_profile_question() always resolves here (caller-guarded or
    # correction_key set) -- type-narrowing assert.
    assert question is not None
    answered, total = consultation_progress(draft)
    seed = initial_value if initial_value is not None else draft.answer(question.key)
    if seed is None:
        seed = _default_question_seed(draft, question.key)

    priority_options: tuple[tuple[str, str], ...] = ()
    if question.key == "additional_notes":
        priority_options = (
            tuple(
                (
                    phrase,
                    "Switch to self-funded only (ignore scholarships and funding options)"
                    if "self-funded" in phrase
                    else label,
                )
                for phrase, label in PRIORITY_TICK_OPTIONS
            )
            if draft.answer("funding_dependency") == "MANDATORY"
            else PRIORITY_TICK_OPTIONS
        )

    context = {
        "draft": draft,
        "question": question,
        "form": form
        or ConsultationQuestionForm(
            key=question.key,
            field=question.field_factory(),
            initial_value=seed,
        ),
        "progress_answered": answered,
        "progress_total": total,
        "can_go_back": (
            draft.correction_key is not None or previous_question_key(draft) is not None
        ),
        "error": error,
        "popular_destinations": (
            POPULAR_DESTINATIONS
            if question.key in {"allowed_countries", "excluded_countries"}
            else ()
        ),
        "popular_languages": (
            POPULAR_TEACHING_LANGUAGES
            if question.key == "acceptable_teaching_languages"
            else ()
        ),
        "popular_fields": (
            POPULAR_FIELDS
            if question.key in {"target_field", "academic_history"}
            else ()
        ),
        "interest_suggestions": _interest_suggestions_for(draft, question.key),
        "date_presets": date_presets_for_question(question.key),
        "money_presets": MONEY_PRESETS.get(question.key, ()),
        "priority_tick_options": priority_options,
        "duration_tick_options": (
            DURATION_TICK_OPTIONS if question.key == "additional_notes" else ()
        ),
        "selected_ticks": _selected_ticks_for(question.key, seed),
        "language_context_note": _language_context_note_for(draft, question.key),
    }
    template = (
        "student/_consultation_step.html" if _is_htmx(request) else "student/consultation.html"
    )
    return render(request, template, context, status=status)


def _current_study_summary(draft: ConsultationDraft) -> str:
    raw = draft.answers.get("academic_history")
    if not isinstance(raw, list) or not raw:
        return ""
    first = raw[0]
    if not isinstance(first, dict):
        return ""
    inst = str(first.get("institution") or "").strip()
    qual = str(first.get("qualification") or "").strip()
    field = str(first.get("field") or "").strip()
    deg = f"{qual} in {field}" if (qual and field) else (qual or field)
    if inst and deg:
        return f"{inst} — {deg}"
    return inst or deg


def _render_review(
    request: HttpRequest,
    draft: ConsultationDraft,
    *,
    error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    membership = Membership.objects.get(id=draft.membership_id)
    user = request.user
    full_name = (
        (user.get_full_name() or getattr(user, "email", "") or "").strip()
        if user.is_authenticated
        else ""
    )
    context = {
        "draft": draft,
        "error": error,
        "review": validate_draft(draft),
        "labels": QUESTION_LABELS,
        "late_reading": late_reading(draft, membership=membership),
        "has_existing_profile": StudentProfileVersion.objects.filter(student=membership).exists(),
        "full_name": full_name,
        "current_study": _current_study_summary(draft),
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
    write_draft(corrected)
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
        tenant_id=request.tenant.id,  # type: ignore[attr-defined]
        membership_id=membership.id,
    )
    seeded = (
        seed_from_latest_profile(draft, membership=membership)
        if request.method == "GET" and not draft.answers
        else draft
    )
    prefilled = prefill_from_latest_reading(seeded, membership=membership)
    if prefilled is not draft:
        write_draft(prefilled)
        draft = prefilled
    if request.method == "GET":
        return _render_current_state(request, draft)

    if request.POST.get("action") == "use_reading":
        reading = late_reading(draft, membership=membership)
        if reading is not None:
            draft = use_reading(draft, reading)
            write_draft(draft)
        return _render_current_state(request, draft)

    if request.POST.get("action") == "correct":
        target_key = request.POST.get("key", "")
        if target_key in draft.answers:
            draft = draft.with_correction(target_key)
            write_draft(draft)
        return _render_current_state(request, draft)

    if request.POST.get("action") == "back":
        if draft.correction_key is not None:
            draft = replace(draft, correction_key=None)
            write_draft(draft)
            return _render_current_state(request, draft)
        prev_key = previous_question_key(draft)
        if prev_key is not None:
            prev_val = draft.answer(prev_key)
            remaining = {k: v for k, v in draft.answers.items() if k != prev_key}
            draft = replace(draft, answers=remaining, correction_key=None)
            write_draft(draft)
            return _render_question(request, draft, initial_value=prev_val)
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
        except ProfileVersionRejected as exc:
            msg = (
                "Your date of birth, nationality, or degree does not match your "
                "verified profile records."
                if str(exc) == "identity continuity violation"
                else "Unable to start research. Please try again."
            )
            return _render_review(request, draft, error=msg, status=400)
        except DatabaseError:
            logger.exception(
                "accounts.views.profile finalize_consultation database error for membership %s",
                membership.id,
            )
            return _render_review(
                request,
                draft,
                error="Unable to start research. Please try again.",
                status=400,
            )
        clear_draft(draft)
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
    write_draft(draft)
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


_BUDGET_PAGE = "student/settings_budget.html"


def _droppable(card: Card) -> bool:
    """An unpaid fee the budget counts as committed (§7.5). The page lists only
    these, and only these may be ticked: a forged tick on a decided card would
    count money that was never committed towards the shortfall."""
    return card.fee_state == "OPEN" and bool(card.fee) and not card.outcome and not card.closed


def _latest_full_profile(student: Membership) -> StudentProfileSnapshot | None:
    """The newest full profile, or None for the short form (its budget is a
    bare number with no currency, so there is nothing to change it from)."""
    version = StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
    if version is None or version.schema_version != 3:
        return None
    try:
        return StudentProfileSnapshot.model_validate(version.snapshot)
    except ValidationError as exc:
        logger.warning(
            "accounts.views._latest_full_profile invalid v3 snapshot "
            "for membership %s (version %s, %d errors)",
            student.id,
            version.version,
            exc.error_count(),
        )
        return None


def _budget_page(
    request: HttpRequest,
    *,
    profile: StudentProfileSnapshot | None,
    board: Board | None = None,
    values: dict[str, str] | None = None,
    error: str = "",
    status: int = 200,
) -> HttpResponse:
    unpaid = [card for card in board.cards if _droppable(card)] if board is not None else []
    return render(
        request,
        _BUDGET_PAGE,
        {"profile": profile, "board": board, "values": values or {}, "unpaid": unpaid,
         "error": error},
        status=status,
    )


def _floor_error(
    board: Board,
    *,
    budget: Money,
    saved: Money,
    picked: set[str],
) -> tuple[str, list[Card]]:
    """("", cards to drop) when ``budget`` may be saved, else (the refusal, [])."""
    if budget.currency == saved.currency and budget.amount >= saved.amount:
        return "", []  # a raise in the same currency can never break a floor
    if not any(_counts(card) for card in board.cards):
        return "", []  # nothing to protect
    line = budget_line(
        budget=budget, stretch=None, cards=board.cards, table=board.rates, home=board.home
    )
    if line is None or line.no_rate:
        return (
            "We can't check a lower budget against your application fees until today's "
            "exchange rates are loaded. You can still raise it, or try again later.",
            [],
        )
    if line.plan < line.paid:
        return (
            f"You've already paid {whole(line.paid, up=True)} {line.currency} in fees, so "
            "your budget can't go below that.",
            [],
        )
    shortfall = line.paid + line.committed - line.plan
    if shortfall <= 0:
        return "", []  # ticks are ignored when there is no shortfall
    chosen = [
        card for card in board.cards if str(card.application_id) in picked and _droppable(card)
    ]
    freed = sum(
        (in_home(c.fee, c.fee_currency, board.rates, board.home) or Decimal("0")
         for c in chosen if c.fee is not None),
        Decimal("0"),
    )
    if freed < shortfall:
        return (
            f"Your new budget is {whole(shortfall, up=True)} {line.currency} below the "
            "fees you've committed to. Choose which unpaid applications to drop.",
            [],
        )
    return "", chosen


@login_required
@require_http_methods(["GET", "POST"])
def budget_settings(request: HttpRequest) -> HttpResponse:
    """"Change my application budget" (lanes spec §7.8). Only the student: a
    counsellor gets the same refusal every student settings page gives."""
    student = current_membership(request, Membership.Role.STUDENT)
    profile = _latest_full_profile(student)
    if profile is None:
        return _budget_page(request, profile=None)
    board = board_for(student)
    if request.method == "GET":
        stretch = profile.budget_stretch
        return _budget_page(request, profile=profile, board=board, values={
            "amount": str(profile.application_budget.amount),
            "currency": profile.application_budget.currency,
            "stretch": str(stretch.amount) if stretch else "",
            "stretch_currency": (stretch or profile.application_budget).currency,
        })
    values = {
        key: request.POST.get(key, "").strip()
        for key in ("amount", "currency", "stretch", "stretch_currency")
    }

    def refuse(error: str, status: int = 400) -> HttpResponse:
        return _budget_page(
            request, profile=profile, board=board, values=values, error=error, status=status
        )

    if rate_limited("budget-change", student.id, limit=10, window_seconds=3600):
        return refuse("Too many changes. Try again in an hour.", 429)
    try:
        budget = Money(amount=Decimal(values["amount"]), currency=values["currency"].upper())
        extra = Decimal(values["stretch"] or "0")
        stretch = (
            Money(
                amount=extra,
                currency=(values["stretch_currency"] or budget.currency).upper(),
            )
            if extra
            else None
        )
    except (ValidationError, InvalidOperation):
        return refuse(
            "Enter the amounts as numbers and the currency as a 3-letter code, like 500 and AZN."
        )
    saved = profile.application_budget
    picked = set(request.POST.getlist("drop"))
    error, _ = _floor_error(board, budget=budget, saved=saved, picked=picked)
    if error:
        return refuse(error)
    try:
        with transaction.atomic():
            ticked = list(
                Application.objects.select_for_update().filter(
                    student=student, id__in=[i for i in picked if _is_uuid(i)]
                )
            )
            fresh = board_for(student)
            error, chosen = _floor_error(fresh, budget=budget, saved=saved, picked=picked)
            if error:
                return refuse(error)
            # Ticks only count in a shortfall; then each must still be a droppable card.
            if chosen and {str(card.application_id) for card in chosen} != picked:
                return refuse(
                    "One of the applications you ticked has changed since you opened this "
                    "page. Nothing was saved; check the page and try again."
                )
            locked = {a.id: a for a in ticked}
            for card in chosen:
                remove_application(locked[card.application_id], actor=student)
            create_profile_version(
                student=student,
                snapshot=profile.model_copy(
                    update={"application_budget": budget, "budget_stretch": stretch}
                ),
            )
            AuditEvent.objects.create(
                actor=student, event="profile.budget_changed", object_id=student.id
            )
    except ApplicationRefused as refused:
        return refuse(REFUSALS[refused.reason])
    messages.success(request, "Your application budget is saved.")
    if picked and not chosen:  # ticks only count in a shortfall, and there was none
        messages.success(request, "Nothing was dropped: your budget covers your applications.")
    return redirect("concierge-student-dashboard")


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


@login_required
@require_http_methods(["GET", "POST"])
def password_change(request: HttpRequest) -> HttpResponse:
    """Self-service password change with session rotation and device token revocation."""
    assert isinstance(request.user, User) and request.user.pk is not None
    if request.method == "GET":
        form = PasswordChangeForm(user=request.user)
        return render(request, "registration/password_change.html", {"form": form})

    if rate_limited("password-change", request.user.pk, limit=5, window_seconds=3600):
        form = PasswordChangeForm(user=request.user)
        return render(
            request,
            "registration/password_change.html",
            {"form": form, "rate_limited": True},
            status=429,
        )

    form = PasswordChangeForm(user=request.user, data=request.POST)
    if not form.is_valid():
        return render(request, "registration/password_change.html", {"form": form}, status=400)

    user = form.save()
    update_session_auth_hash(request, user)
    request.session["authenticated_at"] = timezone.now().timestamp()
    membership = getattr(request, "membership", None)
    if isinstance(membership, Membership):
        revoke_all_for(membership)
        AuditEvent.objects.create(
            actor=membership, event="account.password_changed", object_id=membership.id
        )
    messages.success(request, "Your password has been updated.")
    if isinstance(membership, Membership) and membership.role == Membership.Role.STUDENT:
        return redirect("student-settings-account")
    return redirect("/")

