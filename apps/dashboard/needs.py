"""Needs you now: one list across everything, sorted by deadline (spec §3).

Items come from the board's cards (pure: `items_from_cards`) and from three
queries -- unacknowledged notifications, drafts awaiting approval, the
extension's pairing. Paths to pages built in later tasks are literal.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import StudentProfileVersion
from apps.concierge.models import Notification
from apps.documents.models import DocumentDraft
from apps.documents.transcript_check import transcript_to_check
from apps.portals.pairing import active_pairings
from apps.tenancy.models import Membership

from .board import Board, Card, Column
from .routes import action_url
from .templatetags.dashboard import https_only

#: "Application not started, deadline near" (spec §3).
START_SOON = timedelta(days=14)
MAILBOX_URL = "/student/settings/mailbox/"
EXTENSION_URL = "/student/settings/extension/"


@dataclass(frozen=True)
class NeedItem:
    text: str
    button: str
    #: "" means no main button (Acknowledge may still be offered).
    url: str
    method: str
    deadline: datetime | None
    created_at: datetime
    acknowledge_url: str = ""
    #: A second, dismissing button ("Ignore") -- only an offer has one.
    ignore_url: str = ""
    #: The "Apply to ..." button: the dashboard swaps it for a sentence when
    #: this browser cannot apply.
    apply: bool = False
    #: The card's own §9.2 text, so Needs and the card name the same day.
    deadline_text: str = ""


def sort_items(items: Iterable[NeedItem]) -> list[NeedItem]:
    """Dated items by deadline, then undated ones newest first (spec §3)."""
    listed = list(items)
    dated = sorted(
        (i for i in listed if i.deadline is not None),
        key=lambda i: i.deadline,  # type: ignore[arg-type,return-value]
    )
    undated = sorted(
        (i for i in listed if i.deadline is None), key=lambda i: i.created_at, reverse=True
    )
    return [*dated, *undated]


#: The documents table's label for a motivation letter (documents.table.ROWS).
LETTER_LABEL = "Motivation letter"
LETTERS_URL = "/student/writing/#letters"
REFS_LABEL = "Recommendation letters"
REFS_PLAN_URL = "/student/referees/plan/"


def _grouped_doc_item(
    cards: list[Card],
    *,
    label: str,
    plural_noun: str,
    single_button: str,
    single_url: str,
    multi_button: str,
    multi_url: str,
) -> NeedItem:
    earliest = min(
        (card for card in cards if card.deadline is not None),
        key=lambda card: card.deadline,  # type: ignore[arg-type,return-value]
        default=None,
    )
    first = earliest.deadline if earliest else None
    first_text = earliest.deadline_text if earliest else cards[0].deadline_text
    if len(cards) == 1:
        card = cards[0]
        return NeedItem(
            f"{label} — needed for {card.title}",
            single_button,
            single_url,
            "get",
            card.deadline,
            card.created_at,
            deadline_text=card.deadline_text,
        )
    return NeedItem(
        f"{plural_noun} still needed for {len(cards)} applications",
        multi_button,
        multi_url,
        "get",
        first,
        min(card.created_at for card in cards),
        deadline_text=first_text,
    )


def _letters_item(cards: list[Card]) -> NeedItem:
    """Every missing motivation letter as one row: a letter is written, not
    submitted, and thirteen near-identical rows buried everything else on Home."""
    return _grouped_doc_item(
        cards,
        label=LETTER_LABEL,
        plural_noun="Motivation letters",
        single_button="Write letter",
        single_url=f"/student/writing/letters/{cards[0].application_id}/",
        multi_button="Write letters",
        multi_url=LETTERS_URL,
    )


def _refs_item(cards: list[Card]) -> NeedItem:
    """Group multiple missing recommendation letter rows on the student's Home."""
    return _grouped_doc_item(
        cards,
        label=REFS_LABEL,
        plural_noun="Recommendation letters",
        single_button="Submit document",
        single_url=cards[0].documents_url,
        multi_button="Plan referees",
        multi_url=REFS_PLAN_URL,
    )


def items_from_cards(
    cards: Iterable[Card], *, now: datetime, answer_url: str, group_letters: bool = False
) -> list[NeedItem]:
    """`group_letters` is the student's Home: missing letters become one row that
    opens the writer. A counsellor keeps one row per application."""
    items: list[NeedItem] = []
    letters: list[Card] = []
    refs: list[Card] = []
    for card in cards:
        if card.closed:  # closed for this intake: nothing left to do
            continue
        # Decided (withdrawn and refused included): nothing sent now changes
        # it, so only a conditional offer's conditions are still asked for.
        for label in card.conditions if card.outcome else card.missing:
            if group_letters and label == LETTER_LABEL and not card.outcome:
                letters.append(card)
                continue
            if group_letters and label == REFS_LABEL and not card.outcome:
                refs.append(card)
                continue
            items.append(NeedItem(
                f"{label} — needed for {card.title}", "Submit document", card.documents_url,
                "get", card.deadline, card.created_at,
                deadline_text=card.deadline_text,
            ))
        given, total = card.answers
        if total > given and not card.outcome:
            missing_answers = total - given
            word = "answer" if missing_answers == 1 else "answers"
            items.append(NeedItem(
                f"{missing_answers} {word} missing for {card.title}", "Answer", answer_url,
                "get", card.deadline, card.created_at,
                deadline_text=card.deadline_text,
            ))
        if (
            card.column is Column.TO_START
            and card.deadline is not None
            and card.deadline - now <= START_SOON
            and card.button is not None
        ):
            items.append(NeedItem(
                f"{card.title} is not started yet", card.button.label, card.button.url,
                card.button.method, card.deadline, card.created_at,
                apply=card.button.apply, deadline_text=card.deadline_text,
            ))
        if (
            card.fee
            and card.fee_state != "PAID"
            and card.portal_url
            and card.column in (Column.TO_START, Column.IN_PROGRESS)
        ):
            items.append(NeedItem(
                f"Application fee for {card.title}: {card.fee_text} — "
                "you pay this at submission",
                "Open portal", card.portal_url, "get", card.deadline,
                card.created_at, deadline_text=card.deadline_text,
            ))
        if card.offer is not None:
            # Owner, 2026-10-04: Accept makes the offered programme a card.
            items.append(NeedItem(
                card.offer.line,
                "Accept", card.offer.accept_url, "post", None, card.created_at,
                ignore_url=card.offer.ignore_url,
            ))
    if letters:
        items.append(_letters_item(letters))
    if refs:
        items.append(_refs_item(refs))
    return items


def _notification_button(
    note: Notification, *, counselor_view: bool, messages_url: str
) -> tuple[str, str]:
    if note.action == Notification.Action.OPEN_MESSAGE:
        return "Open message", messages_url
    if note.action == Notification.Action.OPEN_PORTAL:
        application = note.application
        form = application.portal_form if application is not None else None
        return "Open portal", https_only(form.form_url) if form is not None else ""
    if note.action == Notification.Action.RECONNECT and not counselor_view:
        return "Reconnect", MAILBOX_URL
    return "", ""


def items_for(
    student: Membership,
    *,
    board: Board,
    counselor_view: bool = False,
    now: datetime | None = None,
) -> list[NeedItem]:
    now = now or timezone.now()
    base = f"/counselor/students/{student.id}/"
    messages_url = f"{base}#messages" if counselor_view else "/student/messages/"
    answer_url = f"{base}gap-interview/" if counselor_view else "/student/gap-interview/"
    review_url = f"{base}#documents" if counselor_view else "/student/writing/#drafts"
    items = items_from_cards(
        board.open_cards, now=now, answer_url=answer_url, group_letters=not counselor_view
    )
    for note in (
        Notification.objects.filter(recipient=student, acknowledged_at__isnull=True)
        .select_related("roadmap_item", "application__portal_form")
        .order_by("-created_at")
    ):
        label, url = _notification_button(
            note, counselor_view=counselor_view, messages_url=messages_url
        )
        items.append(NeedItem(
            note.message, label, url, "get", note.roadmap_item.deadline, note.created_at,
            action_url(counselor_view, "acknowledge", student.id, note.id),
        ))
    for draft in DocumentDraft.objects.filter(
        student=student, kind=DocumentDraft.Kind.CV, status=DocumentDraft.Status.DRAFT
    ).order_by("-created_at"):
        items.append(NeedItem(
            f"Your CV (version {draft.version}) is waiting for approval", "Review",
            review_url, "get", None, draft.created_at,
        ))
    if not counselor_view and (reading := transcript_to_check(student)) is not None:
        # Plan 3b: a read transcript waits for the student's check.
        items.append(NeedItem(
            "We read your transcript — check it", "Check your transcript",
            reverse("student-transcript-check"), "get", None, reading.created_at,
        ))
    if (
        not counselor_view
        and not board.cards
        and not StudentProfileVersion.objects.filter(student=student).exists()
    ):
        items.append(NeedItem(
            "Complete your profile so we can find programmes and scholarships for you",
            "Complete your profile",
            reverse("student-profile"),
            "get",
            None,
            now - timedelta(seconds=1),
        ))
    if (
        not counselor_view
        and any(card.has_portal for card in board.cards)
        and not active_pairings(student).exists()
    ):
        items.append(NeedItem(
            "Connect the browser extension so it can fill your applications", "Pair",
            EXTENSION_URL, "get", None, now,
        ))
    return sort_items(items)
