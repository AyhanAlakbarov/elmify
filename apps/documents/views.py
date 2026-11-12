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
import re
import unicodedata
from collections.abc import Callable
from datetime import date
from uuid import UUID

from babel import Locale
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import StudentProfileVersion
from apps.concierge.documents import ADD_BY_DEFAULT
from apps.concierge.models import UPLOAD_KINDS, DocumentVersion
from apps.mailbox.models import MailSignal
from apps.portals.applications import REFUSALS, ApplicationRefused, queue_upload
from apps.portals.models import Application, PreparedDocument
from apps.portals.packets import document_notes
from apps.portals.prepare import current_prepared
from apps.portals.profile import verified_values
from apps.ratelimit import rate_limited
from apps.reference_data import ISO_3166_ALPHA2_CODES
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .audit import record_event
from .confirmation import FactNotFound
from .cv_checks import counsellor_notes
from .cv_fixes import VERB_OPENER, forget_revert, keep_wording, remember_revert
from .degree_match import different_degree, held_duplicates
from .doc_list import document_list
from .fact_labels import FIELD_LABELS, KIND_LABELS, PROBLEM_TEXT, WHY_TEXT
from .fact_writer import (
    PER_ROW,
    AlreadySettled,
    adopt_document_value,
    correct_fact,
    dismiss_document_value,
    held_whole_rows,
    merge_targets,
    merge_whole_document,
    needs_typing,
    placed_whole_rows,
    tip_of,
)
from .file_rules import UPLOAD_DOCUMENTS, rule_for
from .form_filler import fill_student_form_template
from .gap_intake import field_name, submit_answers
from .gaps import UnanswerableQuestion, gap_notes, gap_questions
from .generation import contact_email
from .id_reading import OWNER_UNCHECKED
from .models import DocumentDraft, DocumentReading, TranscriptReading, VerifiedFact
from .reupload import pending_changes, settle_changes
from .storage import download_document  # re-exported for urls.py
from .table import (
    EXPIRING,
    ROWS,
    SENDABLE,
    ApplicationNeeds,
    Cell,
    kinds_named,
    table_for,
    vouched,
)
from .transcript_check import (
    accept,
    accepted_reading,
    answer,
    cards,
    check_items,
    checked_numbers,
    degree_line,
    describe,
    effective_rows,
    fixed_cells,
    label,
    last_answered,
    notes,
    reopen,
    request_review,
    review_requested,
    transcript_to_check,
)
from .verification import (
    TRANSCRIPT_ONLY_EDUCATION_KEYS,
    confirm_candidates,
    disowned_refs,
    generatable_facts,
    id_document_groups,
    live_retired_refs,
    retired_hides,
    retired_refs,
    unsuperseded_facts,
)

__all__ = ["download_document", "gap_interview", "render_gap_page"]



def _same_text(a: object, b: object) -> bool:
    return str(a).strip().casefold() == str(b or "").strip().casefold()


def warning_lines(draft: object) -> list[str]:
    """The stored render warnings as lines to show. A redacted draft holds {}
    (redaction._empty_value), and a malformed entry is skipped, never a 500."""
    records = getattr(draft, "render_warnings", None)
    if not isinstance(records, list):
        return []
    return [
        str(record["detail"])
        for record in records
        if isinstance(record, dict) and record.get("detail")
    ]


def left_out_entries(draft: object) -> list[dict[str, str]]:
    """The draft's left-out items (selection.LeftOut.record()). A redacted
    draft holds {}, and anything malformed is skipped."""
    fixes = getattr(draft, "applied_fixes", None)
    if not isinstance(fixes, list):
        return []
    keys = ("section", "item", "item_digest", "reason")
    return [
        fix for fix in fixes
        if isinstance(fix, dict) and fix.get("kind") == "left_out"
        and all(isinstance(fix.get(k), str) and fix.get(k) for k in keys)
        # 64 hex by construction (coverage.item_digest); checked because the
        # value is written into a JSON attribute on the page.
        and bool(re.fullmatch(r"[0-9a-f]{64}", fix["item_digest"]))
    ]


def _row_name(fact: VerifiedFact) -> str:
    """"Bachelor, ADA University" or "IELTS, 2023-01-10": which degree or sitting."""
    groups = ((("test_name",), ("test_date",)) if fact.category == VerifiedFact.Category.LANGUAGE
              else (("degree_english", "degree_as_awarded"),
                    ("institution_english", "institution_original")))
    parts = [next((value.strip() for key in keys
                   if isinstance(value := fact.payload.get(key), str) and value.strip()), "")
             for keys in groups]
    return ", ".join(p for p in parts if p) or "entry"


#: Shown when answer_questions refuses the batch: the fact moved between the
#: render and the submit, so the questions below are re-derived and answerable.
_REFUSED = (
    "Your answers were not saved -- the questions below are current. "
    "Please answer them again."
)


_GAP_SECTION_META: dict[str, tuple[str, str]] = {
    "MISSING_CONTACT": (
        "Contact & profile links",
        "Optional links and handles for your CV header. Leave blank any profile you do not use.",
    ),
    "NAME_PARTS": (
        "Contact & profile links",
        "Optional links and handles for your CV header. Leave blank any profile you do not use.",
    ),
    "MISSING_LANGUAGE": (
        "Language certificates & levels",
        "Scores and CEFR levels for the languages on your CV.",
    ),
    "TIMELINE_GAP": (
        "Timeline",
        "Short explanations for any gap of 3+ months between studies or jobs.",
    ),
    "MEDIUM_OF_INSTRUCTION": (
        "Education & degrees",
        "Grades, thesis details, and full official names for your degrees.",
    ),
    "MISSING_GRADE": (
        "Education & degrees",
        "Grades, thesis details, and full official names for your degrees.",
    ),
    "MISSING_DEGREE_DETAIL": (
        "Education & degrees",
        "Grades, thesis details, and full official names for your degrees.",
    ),
    "ABBREVIATED_NAME": (
        "Education & degrees",
        "Grades, thesis details, and full official names for your degrees.",
    ),
    "INCOMPLETE_ENTRY": (
        "Experience, publications & awards",
        "Dates, supervisors, and awarding bodies for entries already on your CV.",
    ),
    "MISSING_PUBLICATION_DETAIL": (
        "Experience, publications & awards",
        "Dates, supervisors, and awarding bodies for entries already on your CV.",
    ),
    "MISSING_AWARD": (
        "Experience, publications & awards",
        "Dates, supervisors, and awarding bodies for entries already on your CV.",
    ),
    "ABSENT_SECTION": (
        "Additional background (if applicable)",
        (
            "Extra sections universities ask about — voluntary work, exchange semesters, or "
            "society roles."
        ),
    ),
    "EDUCATION_COMPLETENESS": (
        "Additional background (if applicable)",
        (
            "Extra sections universities ask about — voluntary work, exchange semesters, or "
            "society roles."
        ),
    ),
    "PROGRAMME_REQUIRED": (
        "Programme-specific details",
        "Details asked for by a programme on your list.",
    ),
}


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
    questions = gap_questions(student)
    fields = [(field_name(q), q) for q in questions]
    question_rows = []
    last_section = ""
    for idx, (fname, q) in enumerate(fields, start=1):
        sec_title, sec_sub = _GAP_SECTION_META.get(
            str(q.kind), ("Other details", "Additional details for your CV and applications.")
        )
        show_section = sec_title != last_section
        last_section = sec_title
        has_multi_group = bool(q.slug and len(q.group_keys) > 1)
        is_parent = has_multi_group and q.payload_key == q.group_keys[0]
        is_followup = has_multi_group and q.payload_key != q.group_keys[0]
        question_rows.append(
            {
                "index": idx,
                "name": fname,
                "question": q,
                "section_title": sec_title if show_section else "",
                "section_subtitle": sec_sub if show_section else "",
                "is_group_parent": is_parent,
                "is_group_followup": is_followup,
                "group_slug": q.slug or "",
            }
        )
    return render(
        request,
        "documents/gap_interview.html",
        {
            "fields": fields,
            "question_rows": question_rows,
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
        messages.success(request, "Saved your answers.")
        return redirect("student-gap-interview")
    return render_gap_page(request, student)


#: Upload kinds that offer "Add another" next to "Replace", with the example shown.
_ADD_ANOTHER = {
    "DIPLOMA": "a second degree",
    "LANGUAGE_CERTIFICATE": "a second test",
    "REFERENCE_LETTER": "a letter from another referee",
    "THESIS_OR_REPORT": "a project report",
    # A dual national holds two (owner 2026-10-13). Wording and styling:
    # SHOULD BE DONE BY AYKHAN.
    "PASSPORT": "a second passport",
}


def _merged(application: Application, kind: str) -> bool:
    """Whether this application sends several of `kind` as one READY merged file: then the
    cell is one attachment and one Submit (fix M4). A merge that could not be made, or is not
    made yet, is no attachment -- the extension serves only a READY one -- so each document
    keeps its own Submit."""
    if kind not in UPLOAD_DOCUMENTS:
        return False
    if not rule_for(application.kit_file_rules or [], kind).one_file:
        return False
    row = current_prepared(application).get(kind)
    return row is not None and row.state == PreparedDocument.State.READY


def _reading_problems(readings: list[DocumentReading]) -> list[dict[str, object]]:
    read_at = {
        r.document_id: r.created_at for r in readings if r.state == DocumentReading.State.READ
    }
    failed = [
        {"document": r.document, "text": PROBLEM_TEXT.get(r.failure, PROBLEM_TEXT["unreadable"])}
        for r in readings
        if r.state == DocumentReading.State.FAILED
        and r.failure != "erasure_requested"
        and not (r.document_id in read_at and read_at[r.document_id] > r.created_at)
    ]
    owner_issues = [
        {
            "document": r.document,
            "text": PROBLEM_TEXT[why].replace(
                "passport",
                KIND_LABELS.get(r.kind, "document").lower().removeprefix("your "),
            ),
        }
        for r in readings
        for why in ("owner_mismatch", "owner_unknown")
        if any(v.get("why") == why for v in (r.values or []))
        # Settled only by a later read of the same file free of it (the name was
        # fixed), never by another passport: a mother's passport read before the
        # name existed is not settled by the name arriving.
        and not any(
            later.state == DocumentReading.State.READ
            and later.created_at > r.created_at
            and later.file_sha256 == r.file_sha256
            and not any(v.get("why") == why for v in (later.values or []))
            for later in readings
        )
    ]
    return failed + owner_issues


def _pending_document_choices(
    student: Membership,
    readings: list[DocumentReading],
    *,
    excluded_refs: set[str],
) -> list[dict[str, object]]:
    latest = {r.document_id: r for r in readings if r.state == DocumentReading.State.READ}
    choices: list[dict[str, object]] = []
    for reading in latest.values():
        if f"document:{reading.document_id}" in excluded_refs:
            continue
        for entry in reading.values or []:
            if (
                entry.get("proven")
                or not entry.get("target")
                or entry.get("why") in ("adopted", "kept", *OWNER_UNCHECKED)
            ):
                continue
            key = str(entry.get("key", ""))
            target = VerifiedFact.objects.filter(id=entry["target"], student=student).first()
            # ponytail: one query per waiting value; a student has a handful.
            tip = tip_of(target) if target else None
            if tip is None or tip.confirmed_at is None:
                continue  # adopt refuses it: nothing a tap could do
            held = tip.payload.get(key.partition(".")[2])
            if isinstance(held, str) and held.strip() and _same_text(held, entry.get("value")):
                continue  # the row already holds it: nothing to choose
            choices.append(
                {
                    "label": FIELD_LABELS.get(key, key),
                    "value": entry.get("value", ""),
                    "held": held if isinstance(held, str) else "",
                    "snippet": entry.get("snippet", ""),
                    "why": WHY_TEXT.get(str(entry.get("why", "")), ""),
                    "source": KIND_LABELS.get(reading.kind, "your document"),
                    "reading_id": reading.id,
                    "key": key,
                    "typed": needs_typing(key, entry.get("value", "")),
                    "date": key.endswith("date"),
                }
            )
    return choices


def page_context(student: Membership, *, counselor_view: bool) -> dict[str, object]:
    """The documents table and everything around it, from tenant rows only.

    ``counselor_view`` hides every student-only action (Submit, expiry, fact
    confirmation, CV writing and approval, naming a message); Task 20 reuses it.
    """
    applications = list(
        Application.objects.filter(student=student)
        .exclude(outcome=Application.Outcome.WITHDRAWN)
        .select_related("portal_form", "candidate", "outcome_evidence")
        .order_by("created_at")
    )
    signals = list(
        MailSignal.objects.filter(application__in=applications).select_related(
            "connection", "application__candidate", "application__portal_form"
        )
    )
    table = table_for(student, applications, signals)
    by_id = {application.id: application for application in applications}
    # Why a prepared file was left as it is, per cell; read-only text (final review I1).
    notes, bundles = document_notes(applications)

    def cell_for(kind: str, column: ApplicationNeeds, cell: Cell) -> dict[str, object]:
        # Only a filled cell offers Submit: never CHECKING, MISSING or CERTIFIED
        # (nothing records a certified copy, F13).
        held = [h for h in table.held_all_for(kind, column.application_id)
                if h.state in SENDABLE] if cell in SENDABLE else []
        merged = len(held) > 1 and _merged(by_id[column.application_id], kind)
        return {"column": column, "state": cell, "count": len(held), "merged": merged,
                # A merged cell is one attachment: the extension serves the merged PDF
                # for any of its sources (ext_api._prepared_upload).
                "held": held[:1] if merged else held,
                "notes": notes.get((kind, column.application_id), [])}

    grid = [
        {
            "row": row,
            "cells": [
                cell_for(row.kind, column, cell)
                for column, cell in zip(table.columns, row.cells, strict=True)
            ],
        }
        for row in table.rows
    ]
    cv_changes = pending_changes(student)
    pending_ids = {change.fact.id for change in cv_changes}
    # A pending change is settled in its own list, old beside new; confirming
    # it from the plain list would accept it without the student seeing the
    # value it replaces.
    facts = [
        fact
        for fact in confirm_candidates(student)
        if not fact.source_ref.startswith("document:") and fact.id not in pending_ids
    ]
    # A CV degree that may be one already held waits for the student's "Different degree"
    # (transcript plan 3b Task 7): shown with the degree it may be, never confirmed in the batch.
    unconfirmed = list(unsuperseded_facts(student).filter(
        category=VerifiedFact.Category.EDUCATION, confirmed_at__isnull=True))
    held_ids = held_duplicates(unconfirmed)
    checked = accepted_reading(student)
    held_degrees = []
    for claim in (f for f in unconfirmed if f.id in held_ids):
        target = VerifiedFact.objects.filter(
            id=claim.payload["possible_duplicate_of"], student=student).first()
        held_degrees.append({"fact": claim, "name": _row_name(claim),
                             "may_be": _row_name(target) if target else ""})
    # Oldest first: a document's latest reading is the one its snippets and choices come from.
    readings = list(DocumentReading.objects.filter(student=student)
                    .select_related("document").order_by("created_at"))
    snippets = {
        (f"document:{r.document_id}", v.get("key")): v for r in readings for v in (r.values or [])
    }
    disowned = disowned_refs(student)
    retired, live = retired_refs(student), live_retired_refs(student)
    read_facts = [
        f
        for f in unsuperseded_facts(student)
        .filter(source_ref__startswith="document:")
        .exclude(source_ref__in=disowned)
        if not retired_hides(f, retired, live)
    ]
    # A whole row whose document a confirmed degree or sitting carries is no longer a
    # question; the append-only ledger keeps it (fact_writer.placed_whole_rows).
    placed = placed_whole_rows(student, read_facts)
    # And one an unconfirmed CV row may be is not shown until that row is confirmed
    # (final review I2, concern ruling 1).
    waits_on_cv = held_whole_rows(student, read_facts)
    kinds = {f"document:{r.document_id}": r.kind for r in readings}
    details: list[dict[str, object]] = []
    to_check: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, bool]] = set()
    groups = id_document_groups(read_facts)
    documents = {ref: document for ref, (document, _) in groups.items()}
    # The same passport uploaded again is one document, shown once under its
    # merged values, as id_document_groups counts it -- a correction made on the
    # earlier upload included.
    merged_into = {r: ref for ref, (_, refs) in groups.items() for r in refs}
    for fact in read_facts:
        group = (
            merged_into.get(fact.source_ref)
            if fact.category == VerifiedFact.Category.ID_DOCUMENT and fact.confirmed_at
            else None
        )
        if fact.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT:
            source = "your entry"
        else:
            source = KIND_LABELS.get(kinds.get(fact.source_ref, ""), "your document")
        if fact.category in PER_ROW and fact.confirmed_at is None:
            # Plan 2 (spec §6.2): a diploma or certificate read with no proven anchor is
            # one row; Use confirms all of it, so it is shown, and confirmed, whole. Or the
            # student says which degree or sitting it is (build ruling 1).
            if fact.id in placed or fact.id in waits_on_cv:
                continue  # held: waits until the CV degree it may be is confirmed
            prefix = f"{fact.category.lower()}."
            targets = [{"id": row.id, "name": _row_name(row)}
                       for row in merge_targets(student, fact)]
            question = ("new_degree" if fact.category == VerifiedFact.Category.EDUCATION
                        else "new_result")
            to_check.append({
                "label": "Details", "key": "", "fact_id": fact.id, "source": source,
                # In FIELD_LABELS' order: jsonb keeps no key order.
                "value": "; ".join(
                    f"{label}: {value}" for full, label in FIELD_LABELS.items()
                    if full.startswith(prefix)
                    and isinstance(value := fact.payload.get(full.removeprefix(prefix)), str)
                    and value.strip()
                ),
                "snippet": "", "why": WHY_TEXT[question] if targets else "",
                "use_body": json.dumps({"fact_ids": [str(fact.id)]}),
                "merge_into": targets,
                # What "Yes, add it" would confirm unproven, and why (final review M5).
                "doubts": [
                    f"{label}: {WHY_TEXT.get(str(read.get('why', '')), '')}"
                    for full, label in FIELD_LABELS.items()
                    if full.startswith(prefix)
                    and isinstance(value := fact.payload.get(full.removeprefix(prefix)), str)
                    and value.strip()
                    and (read := snippets.get((fact.source_ref, full)))
                    and not read.get("proven") and read.get("why") != question
                    and _same_text(value, read.get("value"))
                ],
            })
            continue
        for key, value in fact.payload.items():
            full = f"{fact.category.lower()}.{key}"
            if full not in FIELD_LABELS or not isinstance(value, str):
                continue
            if group is not None and documents[group].get(key) != value:
                continue  # not the value the merged document holds
            mark = (FIELD_LABELS[full], value, group or fact.source_ref, bool(fact.confirmed_at))
            read = snippets.get((fact.source_ref, full), {})
            if not fact.confirmed_at and read.get("why") in OWNER_UNCHECKED:
                continue  # build ruling 2: the problem line says what to do instead
            if mark in seen:
                continue
            seen.add(mark)
            row = {
                "label": FIELD_LABELS[full], "value": value, "key": key, "fact_id": fact.id,
                "source": source, "snippet": read.get("snippet", ""),
                "why": WHY_TEXT.get(str(read.get("why", "")), ""),
                "use_body": json.dumps({"fact_ids": [str(fact.id)]}),
                # An unread date is typed, never tapped (final review I3).
                "typed": needs_typing(full, value),
            }
            (details if fact.confirmed_at else to_check).append(row)
    problems = _reading_problems(readings)
    document_choices = _pending_document_choices(
        student, readings, excluded_refs=disowned | retired
    )
    today = timezone.localdate().isoformat()
    passports = [
        {"document_id": ref.removeprefix("document:"), **doc}
        for ref, doc in documents.items()
        if doc.get("document_type") == "passport" and doc.get("expiry_date", "") >= today
    ]
    # What a new upload can replace; a transcript has its own modes (transcript_pages).
    replaceable = (
        DocumentVersion.objects.filter(student=student, state="AVAILABLE", retired_at__isnull=True)
        .exclude(kind="TRANSCRIPT")
        .order_by("-created_at")
    )
    drafts = list(
        DocumentDraft.objects.filter(
            student=student, kind=DocumentDraft.Kind.CV
        ).order_by("-version")
    )
    for draft in drafts:
        draft.warning_lines = warning_lines(draft)  # type: ignore[attr-defined]
        draft.left_out = left_out_entries(draft)  # type: ignore[attr-defined]
    notes_by_draft = counsellor_notes(student, drafts) if counselor_view else {}
    for draft in drafts:
        draft.counsellor_notes = notes_by_draft.get(draft.id, [])  # type: ignore[attr-defined]
    latest_cv = drafts[0] if drafts else None
    uploads_qs = list(DocumentVersion.objects.filter(student=student).order_by("-created_at"))
    has_passport_upload = any(u.kind == "PASSPORT" and not u.retired_at for u in uploads_qs)
    return {
        "details": details,
        "to_check": to_check,
        "document_choices": document_choices,
        # Here, not in the template: `a|length|add:b|length` takes the length of the sum.
        "to_check_total": len(to_check) + len(document_choices),
        "problems": problems,
        "passport_choices": passports if len(passports) >= 2 else [],
        "has_passport_upload": has_passport_upload,
        "table": table,
        # Spec §10: one entry per document; the table below is the by-application view.
        "by_document": document_list(student, applications, signals, table.held),
        "grid": grid,
        # One refused-bundle line per application column, or None when there is none.
        "bundle_row": [bundles.get(c.application_id, "") for c in table.columns]
        if bundles else None,
        "uploads": uploads_qs,
        "drafts": drafts,
        "applied_fixes": [
            f for f in (
                latest_cv.applied_fixes
                if latest_cv and isinstance(latest_cv.applied_fixes, list)
                else []
            )
            if isinstance(f, dict) and "fix" in f
        ],
        "cv_changes": cv_changes,
        "facts": facts,
        # What each fact says, read by a person: a transcript's courses as a count, never
        # a list dump, and the matcher's bookkeeping not at all.
        "facts_shown": [
            (
                fact,
                [
                    (
                        key.replace("_", " "),
                        ", ".join(str(item) for item in value if item)
                        if isinstance(value, (list, tuple))
                        else ("yes" if value is True else value),
                    )
                    for key, value in fact.payload.items()
                    if key not in TRANSCRIPT_ONLY_EDUCATION_KEYS
                    and key.lower() != "is_quantified"
                    and value not in (None, "", [], (), {}, False)
                ],
                len(fact.payload.get("courses") or ()),
            )
            for fact in facts
        ],
        "held_degrees": held_degrees,
        # The transcript the student checked, kept in view with "Something's wrong" (a
        # checked transcript must not vanish), or the one waiting to be checked.
        "transcript_checked": checked,
        "transcript_checked_line": degree_line(checked) if checked else "",
        "transcript_to_check": transcript_to_check(student),
        "confirm_body": json.dumps({"fact_ids": [str(fact.id) for fact in facts]}),
        "upload_kinds": UPLOAD_KINDS,
        "replaceable": replaceable,
        # Kinds a student may rarely hold several of (owner, 2026-10-10), held now.
        "add_another": [
            (kind, example, kind in ADD_BY_DEFAULT) for kind, example in _ADD_ANOTHER.items()
            if any(upload.kind == kind for upload in replaceable)
        ],
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
        # "Something's wrong" on the transcript check reaches whoever looks after the student
        # (plan 3b Task 6); the student's own page does not repeat it back.
        "transcript_review": review_requested(student) if counselor_view else None,
        "upload_endpoint": (
            f"/counselor/students/{student.id}/uploads/" if counselor_view
            else "/api/documents/uploads"
        ),
    }


@login_required
def documents_page(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    return render(request, "student/documents.html", page_context(student, counselor_view=False))


@login_required
@require_POST
def settle_cv_changes(request: HttpRequest) -> HttpResponse:
    """Spec §4: one press settles the "changed since your last CV" list.

    `shown` names every change the page displayed and `accept` the ticked ones;
    an unticked change keeps the old value. settle_changes ignores any id that
    is not one of this student's pending changes, so a stale page or a forged
    id changes nothing.
    """
    student = current_membership(request, Membership.Role.STUDENT)
    shown = [_uuid(value) for value in request.POST.getlist("shown")]
    accepted = [_uuid(value) for value in request.POST.getlist("accept")]
    try:
        settle_changes(student=student, shown=shown, accepted=accepted, actor=student)
    except IntegrityError:
        messages.error(request, "Your choices were not saved -- the list below is current.")
    else:
        messages.success(request, "Saved. Your next CV uses these facts.")
    return redirect("student-documents")


def _latest_fix(student: Membership, subject: str) -> tuple[DocumentDraft, dict[str, object]]:
    """The fix named by `subject` on the student's newest CV draft, or 404.
    The fix's kind and text come from the stored list, never from the form."""
    draft = (
        DocumentDraft.objects.filter(student=student, kind=DocumentDraft.Kind.CV)
        .order_by("-version")
        .first()
    )
    if draft is None:
        raise Http404
    for fix in draft.applied_fixes:
        if isinstance(fix, dict) and fix.get("subject") == subject:
            return draft, fix
    raise Http404


@login_required
@require_POST
def cv_fix_decision(request: HttpRequest) -> HttpResponse:
    """Spec §5.5: the student undoes an automatic fix, or applies it again.

    Takes effect on the next CV the student writes; an existing draft or PDF
    is never altered. Student-only: current_membership refuses a counsellor,
    who sees the same list without buttons."""
    student = current_membership(request, Membership.Role.STUDENT)
    subject = request.POST.get("subject", "")
    action = request.POST.get("action", "")
    draft, fix = _latest_fix(student, subject)
    if action == "undo":
        remember_revert(student, str(fix["fix"]), subject)
    elif action == "redo":
        forget_revert(student, subject)
    elif action == "keep" and fix.get("fix") == VERB_OPENER:
        try:
            kept = keep_wording(
                student=student,
                original=str(fix["original"]),
                changed=str(fix["changed"]),
            )
        except IntegrityError:
            kept = None
        if kept is None:
            messages.error(request, "That line has changed since this CV -- write it again.")
            return redirect("student-documents")
    else:
        raise Http404
    record_event(actor=student, event=f"document.cv_fix_{action}", object_id=draft.id)
    messages.success(request, "Saved. It shows on the next CV you write.")
    return redirect("student-documents")


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
def correct_fact_view(request: HttpRequest, fact_id: UUID) -> HttpResponse:
    """The student's own value for one read detail (spec 2026-10-12 §3, D5)."""
    student = current_membership(request, Membership.Role.STUDENT)
    if rate_limited("api-confirm", student.id, limit=60, window_seconds=3600):
        return HttpResponse(status=429)
    try:
        with transaction.atomic():
            correct_fact(
                student=student, fact_id=fact_id,
                key=str(request.POST.get("key", "")), value=str(request.POST.get("value", "")),
            )
    except FactNotFound:
        raise Http404 from None
    except ValueError:
        return HttpResponse("That value can't be saved.", status=400)
    except IntegrityError:
        return HttpResponse("That changed — refresh and try again.", status=409)
    return redirect(f"{reverse('student-documents')}#details")


def _answer(request: HttpRequest, act: Callable[[Membership], object]) -> HttpResponse:
    """One answer to a document's value, with correct_fact_view's guards: the student
    only (another's ids 404, a counsellor 403), rate limited, and a racing write 409."""
    student = current_membership(request, Membership.Role.STUDENT)
    if rate_limited("api-confirm", student.id, limit=60, window_seconds=3600):
        return HttpResponse(status=429)
    try:
        with transaction.atomic():
            act(student)
    except (IntegrityError, AlreadySettled):  # before FactNotFound: it is one
        # Plan 1: one superseder per row, so a racing write won; or this was answered
        # already (a repeated tap, a stale page).
        return HttpResponse("That changed — refresh and try again.", status=409)
    except FactNotFound:
        raise Http404 from None
    except ValueError:
        return HttpResponse("That value can't be saved.", status=400)
    return redirect(f"{reverse('student-documents')}#details")


@login_required
@require_POST
def adopt_value(request: HttpRequest, reading_id: UUID) -> HttpResponse:
    """Use the document's value (spec 2026-10-12 §3), or the one the student typed for a
    value no tap may write (final review I3)."""
    key = str(request.POST.get("key", ""))
    typed = request.POST.get("value")
    return _answer(request, lambda student: adopt_document_value(
        student=student, reading_id=reading_id, key=key,
        value=None if typed is None else str(typed)))


@login_required
@require_POST
def keep_value(request: HttpRequest, reading_id: UUID) -> HttpResponse:
    """Keep what the student already had (spec D5)."""
    key = str(request.POST.get("key", ""))
    return _answer(request, lambda student: dismiss_document_value(
        student=student, reading_id=reading_id, key=key))


@login_required
@require_POST
def merge_document(request: HttpRequest, fact_id: UUID) -> HttpResponse:
    """"No, it's my <degree>": a whole diploma or certificate row goes into a confirmed
    degree or sitting the student already holds (build ruling 1)."""
    into = request.POST.get("into", "")
    return _answer(request, lambda student: merge_whole_document(
        student=student, fact_id=fact_id, into_id=_uuid(into)))


@login_required
@require_POST
def choose_id_document(request: HttpRequest, document_id: UUID) -> HttpResponse:
    """Which valid passport portals get (spec §4.2): only ever the student's own."""
    student = current_membership(request, Membership.Role.STUDENT)
    if f"document:{document_id}" in (disowned_refs(student) | retired_refs(student)):
        raise Http404
    updated = DocumentReading.objects.filter(
        student=student, document_id=document_id, state=DocumentReading.State.READ
    ).update(primary_chosen_at=timezone.now())
    if not updated:
        raise Http404
    return redirect(f"{reverse('student-documents')}#details")


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


#: The country picker on a transcript's country card: an active ISO code, so a fix can
#: never be a value the academic record refuses (spec audit P3). English names, by name.
_COUNTRIES: tuple[tuple[str, str], ...] = tuple(sorted(
    ((code, name) for code, name in Locale("en").territories.items()
     if code in ISO_3166_ALPHA2_CODES),
    # "Åland" with the A's, "Côte d'Ivoire" with the C's.
    key=lambda pair: "".join(ch for ch in unicodedata.normalize("NFKD", pair[1])
                             if not unicodedata.combining(ch)).casefold(),
))


def _clean_card(reading: TranscriptReading, courses: int) -> str:
    """Variant 3's one sentence: what was read, in the transcript's own figures."""
    numbers = checked_numbers(reading)
    parts = [f"{courses} course{'s' * (courses != 1)}"]
    if numbers.get("total_credits"):
        parts.append(f"{numbers['total_credits']} credits")
    sentence = "We read " + ", ".join(parts)
    if numbers.get("overall_grade"):
        sentence += f", overall {numbers['overall_grade']}"
        if numbers.get("grading_scale"):
            sentence += f" on a {numbers['grading_scale']} scale"
    return sentence + "."


@login_required
def transcript_check_page(request: HttpRequest) -> HttpResponse:
    """The transcript check (plan 3b): one tap when nothing is doubtful, otherwise one card per
    doubtful cell, then a read-only summary. "Something's wrong" never blocks accepting."""
    student = current_membership(request, Membership.Role.STUDENT)
    if request.method == "POST":
        return _transcript_check_post(request, student)
    reading = transcript_to_check(student)
    if reading is None:
        return render(request, "student/transcript_check.html", {"reading": None})
    items = check_items(reading)
    all_cards = cards(items)
    open_cards = [[i for i in card if i.ref not in reading.answers] for card in all_cards]
    open_cards = [card for card in open_cards if card]
    fixed = fixed_cells(reading)
    unread = {ref.partition(":")[0] for ref, given in reading.answers.items()
              if given["choice"] == "cant_read" and ref[:1].isdigit()}
    rows = [row for row in effective_rows(reading) if row.kind == "course"]
    card_items = open_cards[0] if open_cards else []
    card = card_items[0] if card_items else None
    choice_text = {"matches": "matches", "fix": "you typed {value}", "cant_read": "can't read",
                   "same": "same degree", "different": "different degree"}
    return render(request, "student/transcript_check.html", {
        "reading": reading,
        "degree": degree_line(reading),
        "card": card,
        "card_items": [(item, label(item)) for item in card_items],
        "card_refs": [item.ref for item in card_items],
        "card_title": (card.row_title if card.cell != "field" else label(card)) if card else "",
        "card_label": label(card) if card else "",
        "countries": _COUNTRIES if card is not None and card.ref == "field:country" else (),
        "position": len(all_cards) - len(open_cards) + 1,
        "total": len(all_cards),
        "back": last_answered(reading),
        "clean": _clean_card(reading, len(rows)) if not items else "",
        "courses": [
            (row, bool({(row.index, "credits"), (row.index, "grade"), (row.index, "title")}
                       & fixed), str(row.index) in unread)
            for row in rows
        ],
        "answered": [
            (item.ref, describe(item), choice_text[reading.answers[item.ref]["choice"]].format(
                value=reading.answers[item.ref].get("value", "")))
            for item in items if item.ref in reading.answers
        ],
        "numbers": checked_numbers(reading),
        "notes": notes(reading),
    })


def _transcript_check_post(request: HttpRequest, student: Membership) -> HttpResponse:
    if rate_limited("transcript-check", student.id, limit=300, window_seconds=3600):
        return HttpResponse(status=429)
    reading = get_object_or_404(
        TranscriptReading, id=_uuid(request.POST.get("reading_id")), student=student
    )
    here = redirect("student-transcript-check")
    action = request.POST.get("action")
    if reading.accepted is not None:
        latest = accepted_reading(student)
        if action == "review" and latest is not None and latest.id == reading.id:
            # "Something's wrong" after accepting: the documents page keeps offering it.
            request_review(reading, str(request.POST.get("reason", "")))
            messages.success(request, "Thanks — someone will look at it.")
            return redirect(f"{reverse('student-documents')}#transcript")
        return here  # a repeated tap or a stale page
    current = transcript_to_check(student)
    if current is None or current.id != reading.id:
        # A stale tab: a newer reading replaced this one (final review, finding 3).
        messages.error(request, "A newer reading of your transcript is waiting — check that one.")
        return here
    try:
        with transaction.atomic():
            if action == "answer":
                asked = {item.ref: item for item in check_items(reading)}
                before = len(asked)
                choice = str(request.POST.get("choice", ""))
                # One card may answer a row's cells together; a cell left as read in "Fix"
                # is a match, not a fix.
                for ref in request.POST.getlist("ref"):
                    value = str(request.POST.get(f"value:{ref}", request.POST.get("value", "")))
                    unchanged = (choice == "fix" and ref in asked
                                 and value.strip() == asked[ref].reader_value.strip())
                    answer(reading, ref, "matches" if unchanged else choice, value)
                if len(check_items(reading)) > before:
                    messages.info(request, "Your change affects a total, so we added a "
                                           "question about it.")
            elif action == "reopen":
                reopen(reading, str(request.POST.get("ref", "")))
            elif action == "review":
                request_review(reading, str(request.POST.get("reason", "")))
            elif action == "accept":
                accept(reading, student=student)
            else:
                return HttpResponse(status=400)
    except ValueError as refused:
        if str(refused) == "unanswered":
            messages.error(request, "Answer every card first.")
        elif action == "accept":
            messages.error(request, "This transcript can't be saved yet. Use “Something's "
                                    "wrong” and someone will look at it.")
        else:
            messages.error(request, "That value can't be saved.")
        return here
    if action == "accept":
        if not StudentProfileVersion.objects.filter(student=student, schema_version=3).exists():
            # The questionnaire comes next, its degree already filled from this check.
            messages.success(request, "Thanks — your transcript is checked. Next, a few "
                                      "questions about you.")
            return redirect("student-profile")
        messages.success(request, "Thanks — your transcript is checked.")
        return redirect("concierge-student-dashboard")
    return here


@login_required
@require_POST
def different_degree_view(request: HttpRequest, fact_id: UUID) -> HttpResponse:
    """"Different degree -- add it": a CV degree held back as possibly one already held."""
    return _answer(request, lambda student: different_degree(student=student, fact_id=fact_id))


_MAX_FORM_TEMPLATE_BYTES = 10 * 1024 * 1024
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _student_passport_details(student: Membership) -> dict[str, str]:
    """Combine active picked-passport `id_document.*` and `identity.*` values from
    `verified_values(student)` with fallback values from the student's onboarding
    `StudentProfileVersion` snapshot when no passport/fact row exists yet."""
    vvals = verified_values(student)
    details: dict[str, str] = {}
    for k in (
        "given_names",
        "given_name",
        "surname",
        "date_of_birth",
        "place_of_birth",
        "sex",
        "citizenship",
        "phone",
    ):
        val = vvals.get(f"identity.{k}", "").strip()
        if val:
            details[k] = val
    for k in ("number", "issue_date", "expiry_date", "issuing_country", "issuing_authority"):
        val = vvals.get(f"id_document.{k}", "").strip()
        if val:
            details[k] = val

    latest_profile = (
        StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
    )
    snap = (
        latest_profile.snapshot
        if (latest_profile and isinstance(latest_profile.snapshot, dict))
        else {}
    )
    if not details.get("citizenship"):
        raw_nat = snap.get("nationality")
        if isinstance(raw_nat, list) and raw_nat:
            details["citizenship"] = str(raw_nat[0]).strip()
        elif isinstance(raw_nat, str) and raw_nat.strip():
            details["citizenship"] = raw_nat.strip()
    if not details.get("date_of_birth") and snap.get("date_of_birth"):
        details["date_of_birth"] = str(snap["date_of_birth"]).strip()
    if snap.get("country_of_residence"):
        details.setdefault("country_of_residence", str(snap["country_of_residence"]).strip())
    return details


@login_required
@require_POST
def fill_application_form(request: HttpRequest) -> HttpResponse:
    """Inspect an uploaded `.docx` or `.pdf` scholarship/university form template,
    populate its slots from the student's confirmed `VerifiedFact` records, and
    return either the filled `.docx`/`.pdf` download or a `FIELD_MAPPED` copy-paste
    sheet when the PDF uses XFA streams or is a flat/scanned document."""
    student = current_membership(request, Membership.Role.STUDENT)
    if rate_limited("fill-form", student.id, limit=30, window_seconds=3600):
        return HttpResponse(status=429)

    target_programme = ""
    target_institution = ""
    raw_app_id = (request.POST.get("application_id") or "").strip()
    if raw_app_id:
        app = get_object_or_404(
            Application.objects.select_related("candidate", "portal_form"),
            id=_uuid(raw_app_id),
            student=student,
        )
        target_programme = app.title
        target_institution = app.candidate.institution_name if app.candidate else ""

    uploaded = request.FILES.get("template_file")
    if uploaded is None or uploaded.size is None or uploaded.size <= 0:
        messages.error(request, "Choose a .docx or .pdf form to fill.")
        return redirect("student-documents")
    if uploaded.size > _MAX_FORM_TEMPLATE_BYTES:
        messages.error(request, "Upload a .docx or .pdf form under 10 MB.")
        return redirect("student-documents")

    raw_bytes = uploaded.read(_MAX_FORM_TEMPLATE_BYTES + 1)
    if len(raw_bytes) > _MAX_FORM_TEMPLATE_BYTES:
        messages.error(request, "Upload a .docx or .pdf form under 10 MB.")
        return redirect("student-documents")

    is_pdf = raw_bytes.lstrip().startswith(b"%PDF-")
    is_zip = raw_bytes.startswith(b"PK\x03\x04")
    if not (is_pdf or is_zip):
        messages.error(request, "Upload a valid .docx or .pdf form.")
        return redirect("student-documents")

    from .models import Referee

    facts = list(generatable_facts(student))
    seen_refs = {
        (
            str((f.payload or {}).get("name") or "").strip().casefold(),
            str((f.payload or {}).get("email") or "").strip().casefold(),
        )
        for f in facts
        if f.category == VerifiedFact.Category.REFERENCE and isinstance(f.payload, dict)
    }
    for ref in Referee.objects.filter(student=student, status=Referee.Status.ACTIVE).order_by(
        "created_at"
    ):
        ref_key = ((ref.name or "").strip().casefold(), (ref.email or "").strip().casefold())
        if ref_key in seen_refs:
            continue
        seen_refs.add(ref_key)
        facts.append(
            VerifiedFact(
                student=student,
                category=VerifiedFact.Category.REFERENCE,
                payload={
                    "name": ref.name,
                    "position": ref.title,
                    "institution": ref.institution,
                    "email": ref.email,
                },
            )
        )
    passport_details = _student_passport_details(student)
    email = contact_email(student) or student.user.email
    try:
        result = fill_student_form_template(
            raw_bytes,
            facts=facts,
            student_name=student.user.get_full_name(),
            student_email=email,
            target_programme=target_programme,
            target_institution=target_institution,
            passport_details=passport_details,
        )
    except ValueError:
        messages.error(request, "We couldn't read that form template.")
        return redirect("student-documents")

    record_event(actor=student, event="document.form_filled", object_id=student.id)

    orig_name = uploaded.name or ("form.pdf" if is_pdf else "form.docx")
    stem = orig_name.rsplit(".", 1)[0] if "." in orig_name else orig_name
    safe_stem = _SAFE_FILENAME_RE.sub("-", stem).strip("-")[:60] or "form"

    if result.mode == "docx_filled" and result.filled_bytes is not None:
        resp = HttpResponse(
            result.filled_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        resp["Content-Disposition"] = f'attachment; filename="filled-{safe_stem}.docx"'
        resp["X-Content-Type-Options"] = "nosniff"
        resp["X-Form-Fill-Mode"] = "docx_filled"
        return resp

    if result.mode == "pdf_filled" and result.filled_bytes is not None:
        resp = HttpResponse(result.filled_bytes, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="filled-{safe_stem}.pdf"'
        resp["X-Content-Type-Options"] = "nosniff"
        resp["X-Form-Fill-Mode"] = "pdf_filled"
        return resp

    lines = [
        f"# Copy-paste fields for {safe_stem}",
        *(f"{label}: {val}" for label, val in result.field_mapped.items()),
    ]
    resp = HttpResponse(
        "\n".join(lines).encode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )
    resp["Content-Disposition"] = f'attachment; filename="filled-{safe_stem}-fields.txt"'
    resp["X-Content-Type-Options"] = "nosniff"
    resp["X-Form-Fill-Mode"] = "field_mapped_fallback"
    return resp

