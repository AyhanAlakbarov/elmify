from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.dashboard.board import Column, board_for, column_for, outcome_line
from apps.funding.models import EvidenceClaim
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from tests.conftest import reads_no_catalogue

from .conftest import add_card

NOW = timezone.now()


def _app(**fields) -> Application:
    return Application(program_id=uuid4(), **fields)


@pytest.mark.parametrize(
    ("fields", "column"),
    [
        ({}, Column.TO_START),
        ({"started_at": NOW}, Column.IN_PROGRESS),
        ({"state": "READY_TO_SUBMIT"}, Column.IN_PROGRESS),
        ({"state": "BLOCKED_MISSING_FACT"}, Column.IN_PROGRESS),
        ({"state": "SUBMITTED"}, Column.SUBMITTED),
        ({"state": "CONFIRMED"}, Column.CONFIRMED),
        ({"state": "CONFIRMED", "decision_available_at": NOW}, Column.DECISION),
        ({"state": "SUBMITTED", "outcome": "REJECTED"}, Column.DECISION),
    ],
)
def test_column_for_follows_the_spec_table(fields, column) -> None:
    assert column_for(_app(**fields)) is column


def test_outcome_line_names_the_source_and_the_day() -> None:
    when = NOW.replace(month=10, day=3)
    application = _app(outcome="ADMITTED", outcome_source="MAIL", outcome_recorded_at=when)
    assert outcome_line(application, "tum.de") == "Admitted — from tum.de's email, 3 Oct"


def test_a_decision_without_an_outcome_says_where_to_read_it() -> None:
    assert outcome_line(_app(decision_available_at=NOW), "") == (
        "Decision available — open the email or your portal to read it"
    )


def test_an_unrecorded_reading_and_an_abstention_both_ask_the_person() -> None:
    assert outcome_line(_app(decision_available_at=NOW), "", read="ADMITTED") == (
        "Decision available — the email reads: Admitted. Confirm it below."
    )
    assert outcome_line(_app(), "", unconfirmed=True).startswith("Decision available — confirm")


@pytest.mark.django_db
def test_a_card_reads_its_copies_and_links_the_funding_both_ways(
    agency_a, membership_a, pack
) -> None:
    programme, award = pack
    with tenant_scope(agency_a.id):
        add_card(
            agency_a, membership_a, programme,
            deadline=NOW + timedelta(days=10), deadline_timezone="Europe/Berlin",
            kit_requirements=["Transcript of records", "A CV in English"],
        )
        add_card(agency_a, membership_a, award, portal=False)
        with reads_no_catalogue():
            board = board_for(membership_a)

    cards = {card.title: card for card in board.cards}
    card = cards["M.Sc. Informatics"]
    assert card.column is Column.TO_START
    assert (card.institution, card.country) == ("TUM", "DE")
    assert (card.fee, card.fee_currency) == (Decimal("75.00"), "EUR")
    assert card.gap == "1200.00 EUR"
    assert card.documents == (0, 2)
    assert card.missing == ("CV", "Transcript")
    assert card.needs == ("DAAD Study Scholarship",)
    assert cards["DAAD Study Scholarship"].funds == ("M.Sc. Informatics",)
    assert [(line.name, line.covers) for line in card.funding] == [
        ("DAAD Study Scholarship", "living: full")
    ]
    assert (card.button.label, card.button.method) == ("Start application", "post")
    assert card.deadline_local.tzinfo.key == "Europe/Berlin"


@pytest.mark.django_db
def test_a_card_without_a_portal_offers_the_programme_page(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme, portal=False)
        card = board_for(membership_a).cards[0]
    assert card.has_portal is False
    assert card.button.label == "Open programme page"
    assert card.button.url == programme.evidence.source_url


@pytest.mark.django_db
def test_a_javascript_programme_url_gives_no_button(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        EvidenceClaim.objects.filter(id=programme.evidence_id).update(
            source_url="javascript:alert(1)"
        )
        add_card(agency_a, membership_a, programme, portal=False)
        card = board_for(membership_a).cards[0]
    assert card.button is None


@pytest.mark.django_db
def test_a_decision_card_reads_the_outcome_and_badges_recent_mail(
    agency_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT",
            address="amina@outlook.test",
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="tum.de", received_at=NOW, application=application,
            label="DECISION", outcome="ADMITTED", trusted=True, sender_authenticated=True,
            funding_outcome="REJECTED",
        )
        Application.objects.filter(id=application.id).update(
            outcome="ADMITTED", outcome_source="MAIL", outcome_recorded_at=NOW,
            outcome_evidence=signal,
        )
        card = board_for(membership_a).cards[0]
    assert card.column is Column.DECISION
    assert card.outcome_line.startswith("Admitted — from tum.de's email")
    assert card.badges == ("A decision",)
    assert card.funding_outcome_line == "Scholarship: not awarded — from tum.de's email"
    assert (card.button.label, card.button.url) == ("Open portal", "https://campus.tum.de/apply")


@pytest.mark.django_db
def test_offer_conditions_are_missing_items(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT", address="a@o.test"
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-2",
            sender_domain="ed.ac.uk", received_at=NOW, application=application,
            label="DECISION", outcome="ADMITTED_CONDITIONAL",
            outcome_conditions=["final transcript"],
        )
        Application.objects.filter(id=application.id).update(
            outcome="ADMITTED_CONDITIONAL", outcome_source="MAIL", outcome_recorded_at=NOW,
            outcome_evidence=signal,
        )
        card = board_for(membership_a).cards[0]
    assert "Condition: final transcript" in card.missing


@pytest.mark.django_db
def test_an_offer_for_another_programme_waits_on_its_card(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT", address="a@o.test"
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-3",
            sender_domain="tum.de", received_at=NOW, application=application,
            label="DECISION", offered_programme="M.Sc. Data Engineering", trusted=True,
        )
        card = board_for(membership_a).cards[0]
        MailSignal.objects.filter(id=signal.id).update(offer_handled_at=NOW)
        handled = board_for(membership_a).cards[0]
    assert (card.offer.institution, card.offer.programme) == ("TUM", "M.Sc. Data Engineering")
    assert card.offer.accept_url == f"/student/offers/{signal.id}/accept/"
    assert card.offer.ignore_url == f"/student/offers/{signal.id}/ignore/"
    assert handled.offer is None


def test_column_keys_are_stable_and_not_the_headings() -> None:
    assert [c.key for c in Column] == [
        "to_start", "in_progress", "submitted", "confirmed", "decision"
    ]


def test_a_refused_scholarship_is_not_awarded_never_not_admitted() -> None:
    from apps.funding.models import RecommendationCandidate

    award = RecommendationCandidate(opportunity_id=uuid4())
    application = _app(outcome="REJECTED", outcome_source="PERSON")
    application.candidate = award
    assert outcome_line(application, "") == "Scholarship: not awarded — recorded by hand"


def _signal(agency, membership, application, n, **fields):
    connection = MailboxConnection.objects.get_or_create(
        tenant=agency, membership=membership, provider="MICROSOFT",
        defaults={"address": "a@o.test"},
    )[0]
    return MailSignal.objects.create(
        tenant=agency, connection=connection, provider_message_id=f"x-{n}",
        sender_domain="tum.de", received_at=NOW + timedelta(seconds=n),
        application=application, **fields,
    )


def _submitted_card(agency, membership, pack, **signal_fields):
    programme, _award = pack
    with tenant_scope(agency.id):
        application = add_card(agency, membership, programme, state="SUBMITTED")
        _signal(agency, membership, application, 1, label="DECISION", **signal_fields)
        return board_for(membership).cards[0]


_LOUD = {
    "outcome": "ADMITTED", "funding_outcome": "REJECTED",
    "offered_programme": "M.Sc. Other", "decision_reading": {},
}


@pytest.mark.django_db
def test_untrusted_mail_only_badges_and_says_unverified(agency_a, membership_a, pack) -> None:
    card = _submitted_card(agency_a, membership_a, pack, trusted=False, **_LOUD)
    assert card.badges == ("A decision (unverified)",)
    assert card.outcome_line == ""
    assert card.funding_outcome_line == ""
    assert card.offer is None


@pytest.mark.django_db
def test_the_same_mail_trusted_shows_its_lines(agency_a, membership_a, pack) -> None:
    card = _submitted_card(
        agency_a, membership_a, pack, trusted=True, sender_authenticated=True, **_LOUD
    )
    assert card.badges == ("A decision",)
    assert card.funding_outcome_line.startswith("Scholarship: not awarded")
    assert card.offer is not None


@pytest.mark.django_db
def test_a_newer_untrusted_signal_does_not_override_the_trusted_read(
    agency_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, state="SUBMITTED", decision_available_at=NOW
        )
        _signal(agency_a, membership_a, application, 1, label="DECISION", trusted=True,
                outcome="WAITLISTED", decision_reading={"is_decision": True})
        _signal(agency_a, membership_a, application, 2, label="DECISION", trusted=False,
                outcome="ADMITTED")
        card = board_for(membership_a).cards[0]
    assert "reads: Waitlisted" in card.outcome_line


@pytest.mark.django_db
def test_a_scholarship_card_reads_the_funding_outcome(agency_a, membership_a, pack) -> None:
    _programme, award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, award, portal=False, state="SUBMITTED",
            decision_available_at=NOW,
        )
        _signal(agency_a, membership_a, application, 1, label="DECISION", trusted=True,
                outcome="ADMITTED", funding_outcome="REJECTED",
                decision_reading={"is_decision": True})
        card = board_for(membership_a).cards[0]
    assert card.outcome_line == (
        "Decision available — the email reads: Scholarship: not awarded. Confirm it below."
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("reading", "asks"),
    [
        ({"is_decision": None}, True),
        ({}, True),
        ({"is_decision": None, "unavailable": True}, True),
        ({"is_decision": False}, False),
    ],
)
def test_confirm_only_when_jev_abstained(agency_a, membership_a, pack, reading, asks) -> None:
    card = _submitted_card(
        agency_a, membership_a, pack, trusted=True, decision_reading=reading
    )
    assert card.outcome_line.startswith("Decision available") is asks


@pytest.mark.django_db
def test_an_unknown_stored_value_skips_the_line(agency_a, membership_a, pack) -> None:
    card = _submitted_card(
        agency_a, membership_a, pack, trusted=True, funding_outcome="SURPRISE"
    )
    assert card.funding_outcome_line == ""
    application = _app(outcome="SURPRISE", outcome_source="MAIL")
    assert outcome_line(application, "tum.de") == ""
    assert outcome_line(_app(decision_available_at=NOW), "", read="SURPRISE").startswith(
        "Decision available — open"
    )


@pytest.mark.django_db
def test_other_mail_gets_a_badge(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        _signal(agency_a, membership_a, application, 1, label="OTHER", trusted=True)
        card = board_for(membership_a).cards[0]
    assert card.badges == ("Something else",)


@pytest.mark.django_db
def test_an_in_progress_card_without_a_portal_cannot_continue(
    agency_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme, portal=False, started_at=NOW)
        card = board_for(membership_a).cards[0]
    assert card.column is Column.IN_PROGRESS
    assert card.button.label == "Open programme page"


@pytest.mark.django_db
def test_a_tag_only_funding_reading_is_a_reading_not_a_fact(
    agency_a, membership_a, pack
) -> None:
    card = _submitted_card(
        agency_a, membership_a, pack, trusted=True, sender_authenticated=False,
        funding_outcome="REJECTED",
    )
    assert card.funding_outcome_line == (
        "Scholarship: the email reads not awarded — confirm it below."
    )
