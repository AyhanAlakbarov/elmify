"""Signup, legal pages, re-acceptance and the processing-stopped notice.

Plain, unstyled HTML on purpose (requirements P1-9 amendment): the team designs
the presentation later; these pages exist so the behaviour can be tested end to end.
"""

import hashlib

from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.privacy import acceptance, documents
from apps.privacy.forms import CONSENT_TEXT, SignupForm
from apps.privacy.models import Acceptance, LegalDocument
from apps.ratelimit import rate_limited
from apps.tenancy.context import current_tenant_id
from apps.tenancy.models import Agency, Membership
from apps.tenancy.services import current_membership

STALE_MESSAGE = "These documents changed while the page was open. Read the current versions below."
TOO_MANY = "Too many sign-up attempts. Try again later."
_HOUR = 3600


def _key(value: str) -> int:
    """rate_limited takes UUID | int; SHA-256 so a crafted value cannot collide."""
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")


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
    context = {"form": form, "docs": docs}
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
        first, _, last = data["full_name"].strip().partition(" ")
        user = get_user_model().objects.create_user(
            username=data["email"],
            email=data["email"],
            password=data["password"],
            first_name=first,
            last_name=last,
        )
        student = Membership.objects.create(user=user, role=Membership.Role.STUDENT)
        acceptance.record(student, docs, surface="signup", language=data["language"])
        login(request, user)
        return redirect("/student/")
    return render(request, "privacy/signup.html", context)


def legal_document(request: HttpRequest, kind: str) -> HttpResponse:
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
