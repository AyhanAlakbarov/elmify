"""Signup, legal pages, re-acceptance and the processing-stopped notice.

Plain, unstyled HTML on purpose (requirements P1-9 amendment): the team designs
the presentation later; these pages exist so the behaviour can be tested end to end.
"""

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.concierge.cycles import grant_early_access_cycle
from apps.privacy import acceptance, documents, email_code
from apps.privacy.forms import CONSENT_TEXT, SignupCodeForm, SignupForm
from apps.privacy.models import Acceptance, LegalDocument
from apps.ratelimit import actor_key as _key
from apps.ratelimit import rate_limited
from apps.tenancy.context import current_tenant_id
from apps.tenancy.models import Agency, Membership
from apps.tenancy.services import current_membership

#: How each language names itself, for the sign-up page's language links.
LANGUAGE_NAMES = (("en", "English"), ("az", "Azərbaycanca"), ("ru", "Русский"))
STALE_MESSAGE = "These documents changed while the page was open. Read the current versions below."
TOO_MANY = "Too many sign-up attempts. Try again later."
_HOUR = 3600
SEND_FAILED = "We could not send the email just now. Try again in a few minutes."


def _client_ip(request: HttpRequest) -> str:
    """The address the ALB saw: it APPENDS that as the last X-Forwarded-For entry
    (default append mode), so everything to its left is client-supplied.
    REMOTE_ADDR behind the ALB is the ALB node itself -- one bucket for everyone."""
    forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", ""))
    return forwarded.rsplit(",", 1)[-1].strip() or str(request.META.get("REMOTE_ADDR", ""))


def _shown_is_current(request: HttpRequest, docs: list[LegalDocument]) -> bool:
    """The ids the page showed (hidden fields) are the versions current now.

    A version published between GET and POST would otherwise be recorded as
    accepted by someone who never saw it (spec section 11).
    """
    return set(request.POST.getlist("documents")) == {str(doc.id) for doc in docs}


@require_http_methods(["GET", "POST"])
def signup(request: HttpRequest) -> HttpResponse:
    tenant_id = current_tenant_id()
    asked = request.POST.get("language") or request.GET.get("lang")
    language = asked if asked in documents.LANGUAGES else "en"
    docs = acceptance.documents_to_accept(tenant_id, language)
    if len(docs) < 2:
        # Never create an account that accepted nothing: the documents are published
        # by `manage.py publish_legal_documents` at deploy (docs/runbooks/privacy.md).
        return HttpResponse("Signup is not available yet.", status=503)
    form = SignupForm(request.POST or None, initial={"language": language})
    context = {"form": form, "docs": docs, "language_names": LANGUAGE_NAMES}
    if request.method == "POST":
        if rate_limited("signup", _key(_client_ip(request)), limit=10, window_seconds=_HOUR):
            return HttpResponse(TOO_MANY, status=429)
        if not form.is_valid():
            # "Already exists" says the address has an account somewhere on the
            # platform, so it gets its own, tighter bucket per address.
            email = str(request.POST.get("email", "")).strip().lower()
            if form.has_error("email", "taken") and rate_limited(
                "signup-email-taken", _key(email), limit=5, window_seconds=_HOUR
            ):
                return HttpResponse(TOO_MANY, status=429)
            return render(request, "privacy/signup.html", context, status=400)
        if not _shown_is_current(request, docs):
            form.add_error(None, STALE_MESSAGE)
            context["stale"] = True
            return render(request, "privacy/signup.html", context, status=400)
        data = form.cleaned_data
        details = {
            "full_name": data["full_name"],
            "email": data["email"],
            "password_hash": make_password(data["password"]),
            "language": data["language"],
            "documents": sorted(str(doc.id) for doc in docs),
        }
        if not settings.SIGNUP_EMAIL_CODE:
            return _create_account(request, details, docs)
        code = email_code.start(request.session, details)
        try:
            email_code.mail_code(details["email"], code)
        except OSError:
            email_code.clear(request.session)
            form.add_error(None, SEND_FAILED)
            return render(request, "privacy/signup.html", context, status=503)
        return redirect("privacy-signup-verify")
    return render(request, "privacy/signup.html", context)


def _create_account(
    request: HttpRequest, details: dict[str, Any], docs: list[LegalDocument]
) -> HttpResponse:
    first, _, last = details["full_name"].strip().partition(" ")
    user = get_user_model()(
        username=details["email"],
        email=details["email"],
        first_name=first,
        last_name=last,
        password=details["password_hash"],
    )
    user.save()
    student = Membership.objects.create(user=user, role=Membership.Role.STUDENT)
    acceptance.record(student, docs, surface="signup", language=details["language"])
    if settings.EARLY_ACCESS_FREE_CYCLE:
        grant_early_access_cycle(student)
    login(request, user)
    return redirect("/student/")


@require_http_methods(["GET", "POST"])
def signup_verify(request: HttpRequest) -> HttpResponse:
    """Step two of sign-up: the code mailed by `signup`. The account exists only
    after the right code, so a mistyped address never becomes a login."""
    pending = email_code.pending(request.session)
    if pending is None:
        return redirect("privacy-signup")
    form = SignupCodeForm(request.POST or None)
    context: dict[str, object] = {"form": form, "email": pending["email"]}
    if request.method == "POST" and request.POST.get("action") == "resend":
        code = email_code.resend(request.session)
        if code is None:
            context["notice"] = "Wait a minute before asking for another code."
        else:
            try:
                email_code.mail_code(pending["email"], code)
            except OSError:
                context["notice"] = SEND_FAILED
            else:
                context["notice"] = "We sent a new code."
        return render(request, "privacy/signup_verify.html", context)
    if request.method == "POST" and form.is_valid():
        if rate_limited("signup-code", _key(_client_ip(request)), limit=30, window_seconds=_HOUR):
            return HttpResponse(TOO_MANY, status=429)
        outcome = email_code.check(request.session, form.cleaned_data["code"])
        if outcome == "ok":
            tenant_id = current_tenant_id()
            docs = acceptance.documents_to_accept(tenant_id, pending["language"])
            taken = get_user_model().objects.filter(username__iexact=pending["email"]).exists()
            if taken or sorted(str(doc.id) for doc in docs) != pending["documents"]:
                # The address was taken, or the documents changed, while the code
                # was in the mail: start again rather than accept what was not shown.
                email_code.clear(request.session)
                messages.error(
                    request, "Something changed while you were away. Please sign up again."
                )
                return redirect("privacy-signup")
            email_code.clear(request.session)
            return _create_account(request, pending, docs)
        if outcome in {"expired", "locked"}:
            email_code.clear(request.session)
            messages.error(
                request,
                "That code has expired. Sign up again to get a new one."
                if outcome == "expired"
                else "Too many wrong codes. Sign up again to get a new one.",
            )
            return redirect("privacy-signup")
        form.add_error("code", "That code is not right. Check the email and try again.")
        return render(request, "privacy/signup_verify.html", context, status=400)
    return render(request, "privacy/signup_verify.html", context)


def legal_document(request: HttpRequest, kind: str) -> HttpResponse:
    if kind == "terms_of_service":
        kind = "terms"
    elif kind in {"privacy_notice", "privacy"}:
        tenant_id = current_tenant_id()
        _, kind = (
            acceptance.required_kinds(tenant_id)
            if tenant_id is not None
            else ("terms", "privacy_notice_direct")
        )
    if kind not in documents.KINDS:
        raise Http404
    doc = documents.current(kind, request.GET.get("lang") or "en")
    if doc is None:
        raise Http404
    # The body is data, not a template: substitute the one token by hand. The stored
    # text (and so the accepted sha256) keeps the placeholder.
    agency = Agency.objects.filter(id=current_tenant_id()).values_list("name", flat=True).first()
    body = doc.body.replace("{{ agency }}", agency or "your agency")
    return render(request, "privacy/legal_document.html", {"doc": doc, "body": body})


@login_required
@require_http_methods(["GET", "POST"])
def accept(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    last = Acceptance.objects.filter(student=student).order_by("-accepted_at").first()
    language = last.language if last else "en"
    docs = acceptance.documents_to_accept(student.tenant_id, language)
    context = {"docs": docs, "consent_text": CONSENT_TEXT}
    if request.method == "POST":
        if request.POST.get("consent") != "on":
            return render(request, "privacy/accept.html", {**context, "error": True}, status=400)
        if not _shown_is_current(request, docs):
            return render(request, "privacy/accept.html", {**context, "stale": True}, status=400)
        # Each row carries its own document's language, which may be the English
        # fallback rather than the language asked for.
        for doc_language in {doc.language for doc in docs}:
            group = [doc for doc in docs if doc.language == doc_language]
            acceptance.record(student, group, surface="reacceptance", language=doc_language)
        return redirect("/student/")
    return render(request, "privacy/accept.html", context)


@login_required
def stopped(request: HttpRequest) -> HttpResponse:
    notice = acceptance.required_kinds(current_tenant_id())[1]
    return render(request, "privacy/stopped.html", {"notice_kind": notice})
