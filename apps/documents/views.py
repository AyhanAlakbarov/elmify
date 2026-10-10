"""The gap interview and the documents page (dashboard spec §6), and the
trust boundary underneath them.

``gap_intake.submit_answers`` takes ``student`` on trust and documents that it
does. ``current_membership(request, STUDENT)`` is where that trust is earned:
it is simultaneously the authorisation check and the ``student`` argument, so
there is no way to pass the check and then write to a different ledger.

Deliberately not a Django ``Form``. Every value a form would clean is already
cleaned by ``answer_questions`` -- against the ledger, which is the only place
that knows whether a key is askable and whether a tier may be overwritten --
and a ``Form`` would arrive with ``required=True`` on every field, which is
the one thing this surface must never be (see ``render_gap_page``).

The gap interview's template is an app template; the documents page lives
with the other student pages in ``templates/student/``. Both render unstyled
semantic HTML.
"""

import json
from datetime import date
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.concierge.models import UPLOAD_KINDS, DocumentVersion
from apps.mailbox.models import MailSignal
from apps.portals.applications import REFUSALS, ApplicationRefused, queue_upload
from apps.portals.models import Application
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .gap_intake import field_name, submit_answers
from .gaps import UnanswerableQuestion, gap_notes, gap_questions
from .models import DocumentDraft
from .storage import download_document  # re-exported for urls.py
from .table import EXPIRING, ROWS, SENDABLE, kinds_named, table_for, vouched
from .verification import unsuperseded_facts

__all__ = ["download_document", "gap_interview", "render_gap_page"]

#: Shown when answer_questions refuses the batch: the fact moved between the
#: render and the submit, so the questions below are re-derived and answerable.
_REFUSED = (
    "Your answers were not saved -- the questions below are current. "
    "Please answer them again."
)


def render_gap_page(
    request: HttpRequest, student: Membership, *, error: str | None = None
) -> HttpResponse:
    """Render the open questions, re-derived on every request.

    Re-deriving rather than carrying state is what makes an answered question
    disappear on its own: the answer supersedes the fact that lacked a value,
    so the detector that asked stops asking. Nothing records "answered".

    Field names come from ``field_name`` and are never built here -- the
    submit side looks answers up by exactly that string, so a page that names
    an input anything else posts a form whose answers are silently dropped.

    The template extends `base.html`; base.html carries no text input, which
    keeps tests/documents/test_gap_interview_view.py's count of `<input
    type="text"` honest.
    """
    return render(
        request,
        "documents/gap_interview.html",
        {
            "fields": [(field_name(q), q) for q in gap_questions(student)],
            "notes": gap_notes(student),
            "error": error,
        },
        status=400 if error else 200,
    )


@login_required
def gap_interview(request: HttpRequest) -> HttpResponse:
    """Ask what the ledger is missing; write what comes back.

    Post/Redirect/Get on success, so a reload cannot re-post a set of answers
    whose questions no longer exist.

    ``UnanswerableQuestion`` is a 400, not a 500: it means the submission
    disagreed with the ledger, which is a thing the student can see and act
    on, and ``answer_questions`` is atomic so nothing landed.
    """
    student = current_membership(request, Membership.Role.STUDENT)
    if request.method == "POST":
        try:
            submit_answers(request.POST, student=student)
        except UnanswerableQuestion:
            return render_gap_page(request, student, error=_REFUSED)
        return redirect("student-gap-interview")
    return render_gap_page(request, student)


def page_context(student: Membership, *, counselor_view: bool) -> dict[str, object]:
    """The documents table and everything around it, from tenant rows only.

    ``counselor_view`` hides every student-only action (Submit, expiry, fact
    confirmation, CV writing and approval, naming a message); Task 20 reuses it.
    """
    applications = list(
        Application.objects.filter(student=student)
        .exclude(outcome=Application.Outcome.WITHDRAWN)
        .select_related("portal_form", "candidate")
        .order_by("created_at")
    )
    signals = list(
        MailSignal.objects.filter(application__in=applications).select_related(
            "connection", "application__candidate", "application__portal_form"
        )
    )
    table = table_for(student, applications, signals)
    grid = [
        {
            "row": row,
            "cells": [
                {
                    "column": column,
                    "state": cell,
                    # Only a filled cell offers Submit: never CHECKING, MISSING or
                    # CERTIFIED (nothing records a certified copy, F13).
                    "held": (
                        table.held_for(row.kind, column.application_id)
                        if cell in SENDABLE
                        else None
                    ),
                }
                for column, cell in zip(table.columns, row.cells, strict=True)
            ],
        }
        for row in table.rows
    ]
    facts = list(unsuperseded_facts(student).filter(confirmed_by__isnull=True))
    return {
        "table": table,
        "grid": grid,
        "uploads": DocumentVersion.objects.filter(student=student).order_by("-created_at"),
        "drafts": DocumentDraft.objects.filter(
            student=student, kind=DocumentDraft.Kind.CV
        ).order_by("-version"),
        "facts": facts,
        "confirm_body": json.dumps({"fact_ids": [str(fact.id) for fact in facts]}),
        "upload_kinds": UPLOAD_KINDS,
        "expiring": EXPIRING,
        "row_kinds": ROWS,
        # F23: only mail nothing will read -- the metadata tier, or a message whose
        # classification gave up. Other unlabelled mail is waiting for it.
        "unnamed": [s for s in signals if s.label == "" and s.nobody_reads],
        # A request from mail we cannot vouch for adds no cell; it is shown,
        # marked, as the kinds we recognised in it -- never the sender's own
        # wording, which is a stranger's text on our page (Task 15 minor).
        "unverified": [
            (
                s.application.title,
                ", ".join(label for kind, label in ROWS if kind in kinds_named(s.document_name))
                or "a document",
            )
            for s in signals
            if s.label == MailSignal.Label.DOCUMENT_REQUEST and s.document_name
            and not vouched(s) and s.application is not None
        ],
        "counselor_view": counselor_view,
        "upload_endpoint": (
            f"/counselor/students/{student.id}/uploads/" if counselor_view
            else "/api/documents/uploads"
        ),
    }


@login_required
def documents_page(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    return render(request, "student/documents.html", page_context(student, counselor_view=False))


def _uuid(raw: str | None) -> UUID:
    try:
        return UUID(str(raw))
    except ValueError:
        raise Http404 from None


@login_required
@require_POST
def submit_document(request: HttpRequest) -> HttpResponse:
    """Spec §6 step 1-3: the document goes to the application the cell names.

    queue_upload refuses anything but the document that application's own cell
    holds, usable (``table.sendable``); that refusal is a 404 like any other
    id this student cannot address.
    """
    student = current_membership(request, Membership.Role.STUDENT)
    application = get_object_or_404(
        Application.objects.select_related("portal_form", "candidate"),
        id=_uuid(request.POST.get("application_id")),
        student=student,
    )
    try:
        queue_upload(
            application,
            document_id=_uuid(request.POST.get("document_id")),
            source=request.POST.get("source", ""),
            actor=student,
        )
    except ApplicationRefused as refused:
        if refused.reason == "document_unusable":
            raise Http404 from None
        messages.error(request, REFUSALS[refused.reason])
    else:
        messages.success(
            request, f"Your browser extension is opening {application.where} to attach it."
        )
    return redirect("student-documents")


@login_required
@require_POST
def document_expiry(request: HttpRequest, document_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    document = get_object_or_404(
        DocumentVersion, id=document_id, student=student, kind__in=EXPIRING
    )
    try:
        document.expires_on = date.fromisoformat(request.POST.get("expires_on", ""))
    except ValueError:
        messages.error(request, "Enter the date as shown on the document.")
    else:
        document.save(update_fields=["expires_on"])
        messages.success(request, "Saved.")
    return redirect("student-documents")


@login_required
@require_POST
def document_request(request: HttpRequest, signal_id: UUID) -> HttpResponse:
    """Spec §6: on the metadata tier nothing is read, so the student says which
    document a message asked for."""
    student = current_membership(request, Membership.Role.STUDENT)
    signal = get_object_or_404(
        MailSignal.objects.filter(MailSignal.NOBODY_READS),
        id=signal_id,
        connection__membership=student,
        label="",
    )
    label = dict(ROWS).get(request.POST.get("kind", ""))
    if label is None:
        messages.error(request, "Choose a document from the list.")
    else:
        signal.label = MailSignal.Label.DOCUMENT_REQUEST
        signal.document_name = label
        signal.save(update_fields=["label", "document_name"])
    return redirect("student-documents")
