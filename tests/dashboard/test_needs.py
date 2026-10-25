from dataclasses import replace
from datetime import UTC, timedelta
from datetime import timezone as tz
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.dashboard.board import Board, Button, Card, Column, Offer, board_for
from apps.dashboard.needs import NeedItem, items_for, items_from_cards, sort_items
from apps.tenancy.context import tenant_scope

from .conftest import add_card

NOW = timezone.now()


def _card(**overrides) -> Card:
    fields = dict(
        application_id=uuid4(), title="TUM M.Sc.", institution="TUM", country="DE",
        column=Column.TO_START, created_at=NOW, deadline=None, deadline_local=None,
        days_left=None, documents=(0, 0), answers=(0, 0), funding=(),
        funding_outcome_line="", funds=(), needs=(), gap="", fee=None, fee_currency="",
        badges=(), missing=(), outcome_line="", offer=None,
        button=Button("Start application", "/start", "post"), has_portal=True,
        portal_url="https://campus.tum.de/apply", kit_url="/kit",
        documents_url="/student/documents/#application-x", outcome_url="", remove_url="",
        portal_record_url="", outcome="", conditions=(),
    )
    fields.update(overrides)
    return Card(**fields)


def _need(text, deadline=None, created_at=NOW) -> NeedItem:
    return NeedItem(text, "", "", "get", deadline, created_at)


def test_dated_items_by_deadline_then_undated_newest_first() -> None:
    items = [
        _need("old undated", created_at=NOW - timedelta(days=2)),
        _need("late", deadline=NOW + timedelta(days=9)),
        _need("new undated", created_at=NOW),
        _need("soon", deadline=NOW + timedelta(days=1)),
    ]
    assert [i.text for i in sort_items(items)] == ["soon", "late", "new undated", "old undated"]


def test_each_card_gives_its_items_with_one_button() -> None:
    card = _card(
        deadline=NOW + timedelta(days=5), missing=("Transcript",), answers=(10, 12),
        fee=75, fee_currency="EUR",
    )
    items = items_from_cards([card], now=NOW, answer_url="/answer")
    by_button = {item.button: item for item in items}
    assert by_button["Submit document"].text == "Transcript — needed for TUM M.Sc."
    assert by_button["Answer"].text == "2 answers missing for TUM M.Sc."
    assert by_button["Start application"].method == "post"
    assert by_button["Open portal"].url == "https://campus.tum.de/apply"


def test_a_far_deadline_does_not_ask_to_start_yet() -> None:
    card = _card(deadline=NOW + timedelta(days=30))
    items = items_from_cards([card], now=NOW, answer_url="")
    assert [i.button for i in items] == []


def test_an_offer_for_another_programme_asks_accept_or_ignore() -> None:
    offer = Offer(
        uuid4(), "Lund University", "MSc Statistics", "/accept", "/ignore", authenticated=True
    )
    items = items_from_cards(
        [replace(_card(), offer=offer, column=Column.DECISION, button=None)],
        now=NOW, answer_url="",
    )
    assert items[0].text == "Lund University offers you a place in MSc Statistics"
    assert (items[0].button, items[0].url, items[0].method) == ("Accept", "/accept", "post")
    assert items[0].ignore_url == "/ignore"


def test_a_tag_only_offer_is_read_to_the_student_not_stated() -> None:
    """Final review M1: the Messages page's wording, unless sender_authenticated."""
    offer = Offer(uuid4(), "Lund University", "MSc Statistics", "/accept", "/ignore")
    [item] = items_from_cards(
        [replace(_card(), offer=offer, column=Column.DECISION, button=None)],
        now=NOW, answer_url="",
    )
    assert item.text == (
        "Lund University — the email reads: offers a place in MSc Statistics (unverified)"
    )


@pytest.mark.parametrize("outcome", ["REJECTED", "WITHDRAWN", "ADMITTED", "WAITLISTED"])
def test_a_decided_card_asks_for_no_documents_or_answers(outcome) -> None:
    """Final review I2: nothing can clear these once the card is decided."""
    card = _card(
        column=Column.DECISION, outcome=outcome, missing=("Transcript",), answers=(1, 3),
        button=None,
    )
    assert items_from_cards([card], now=NOW, answer_url="/answer") == []


def test_a_conditional_offer_still_lists_its_conditions() -> None:
    card = _card(
        column=Column.DECISION, outcome="ADMITTED_CONDITIONAL", button=None, answers=(1, 3),
        missing=("Transcript", "Condition: final transcript"),
        conditions=("Condition: final transcript",),
    )
    items = items_from_cards([card], now=NOW, answer_url="/answer")
    assert [item.text for item in items] == ["Condition: final transcript — needed for TUM M.Sc."]


@pytest.mark.django_db
@pytest.mark.parametrize("outcome", ["WITHDRAWN", "REJECTED"])
def test_a_withdrawn_or_refused_card_leaves_needs_you_now(
    agency_a, membership_a, pack, outcome
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(
            agency_a, membership_a, programme, state="SUBMITTED", outcome=outcome,
            outcome_recorded_at=NOW, kit_requirements=["Transcript of records"],
        )
        board = board_for(membership_a)
        items = items_for(membership_a, board=board)
        [card] = board.cards
    assert not [item for item in items if "needed for" in item.text]
    if outcome == "WITHDRAWN":
        # Built from the Documents page's own set: a withdrawn card has no column there.
        assert (card.documents, card.missing) == ((0, 0), ())


@pytest.mark.django_db
def test_an_interview_item_shows_its_time_and_sorts_by_it(agency_a, membership_a) -> None:
    from apps.mailbox.actions import apply_verdict
    from apps.mailbox.classify import MailVerdict
    from apps.mailbox.models import MailboxConnection, MailSignal
    from apps.tenancy.db import tenant_transaction

    cet = tz(timedelta(hours=1))
    interview = (NOW + timedelta(days=30)).astimezone(cet).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    as_utc = interview.astimezone(UTC)
    with tenant_scope(agency_a.id):
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT", address="a@o.test"
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="ethz.ch", received_at=NOW, trusted=True,
        )
        with tenant_transaction(agency_a.id):
            apply_verdict(
                signal, MailVerdict(label="INTERVIEW", interview_at=interview.isoformat()),
                link_hosts=frozenset(), authenticated=True,
            )
        later = RoadmapItem.objects.create(
            tenant=agency_a, student=membership_a, stage=RoadmapItem.Stage.DOCUMENTS,
            owner=membership_a, deadline=NOW + timedelta(days=90),
        )
        Notification.objects.create(
            tenant=agency_a, recipient=membership_a, roadmap_item=later, message="Later item"
        )
        items = items_for(membership_a, board=Board(columns=()))
    assert items[0].text == (
        f"ethz.ch invited you to an interview on {as_utc:%d %b %Y}, 09:00 UTC. "
        "Check the time and reply."
    )
    assert items[0].deadline == as_utc
    assert items[1].text == "Later item"


@pytest.mark.django_db
def test_notifications_carry_their_button_and_acknowledge(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a, student=membership_a, stage=RoadmapItem.Stage.PERSONAL_ACTION,
            owner=membership_a, deadline=NOW + timedelta(days=1),
        )
        note = Notification.objects.create(
            tenant=agency_a, recipient=membership_a, roadmap_item=item,
            message="Your Microsoft mailbox connection stopped working.",
            action=Notification.Action.RECONNECT,
        )
        items = items_for(membership_a, board=Board(columns=()))
    assert (items[0].button, items[0].url) == ("Reconnect", "/student/settings/mailbox/")
    assert items[0].acknowledge_url == f"/student/notifications/{note.id}/acknowledge/"


@pytest.mark.django_db
def test_an_unpaired_extension_asks_to_pair(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
        items = items_for(membership_a, board=board_for(membership_a))
    assert ("Pair", "/student/settings/extension/") in [(i.button, i.url) for i in items]


@pytest.mark.parametrize("days, words", [(1, "1 day left"), (2, "2 days left"), (0, "Today")])
def test_the_card_counts_days_in_english(days, words) -> None:
    from django.template.loader import render_to_string

    body = render_to_string(
        "student/_card.html", {"card": _card(deadline_local=NOW, days_left=days)}
    )
    assert words in body


def test_missing_letters_are_one_row_that_opens_the_writer() -> None:
    """Found on the 2026-10-25 showcase: thirteen "Motivation letter — needed for"
    rows, each with a Submit document button for a letter not yet written."""
    first = _card(missing=("Motivation letter",), deadline=NOW + timedelta(days=9))
    second = _card(missing=("Motivation letter", "Transcript"), deadline=NOW + timedelta(days=3))
    items = items_from_cards([first, second], now=NOW, answer_url="/a", group_letters=True)
    letters = [item for item in items if item.button == "Write letters"]
    assert len(letters) == 1
    assert letters[0].text == "Motivation letters still needed for 2 applications"
    assert letters[0].url == "/student/writing/#letters"
    assert letters[0].deadline == NOW + timedelta(days=3)
    assert [item.button for item in items if "Transcript" in item.text] == ["Submit document"]


def test_one_missing_letter_links_to_its_own_workspace() -> None:
    card = _card(missing=("Motivation letter",))
    [item] = items_from_cards([card], now=NOW, answer_url="/a", group_letters=True)
    assert item.button == "Write letter"
    assert item.url == f"/student/writing/letters/{card.application_id}/"


def test_a_counsellor_keeps_one_row_per_application() -> None:
    cards = [_card(missing=("Motivation letter",)), _card(missing=("Motivation letter",))]
    items = items_from_cards(cards, now=NOW, answer_url="/a")
    assert [item.button for item in items] == ["Submit document", "Submit document"]
