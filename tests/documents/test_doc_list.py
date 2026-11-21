# ruff: noqa: F811 -- fixtures imported by name and requested as arguments
"""One document list per student (lanes spec §10): the pure merge, then the page."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.concierge.models import DocumentVersion
from apps.documents.doc_list import CardNeeds, merge
from apps.documents.table import Cell, Held
from apps.funding.models import RecommendationCandidate
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.tenancy.context import tenant_scope
from tests.conftest import reads_no_catalogue
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card
from tests.dashboard.test_counselor_board import counselor_client  # noqa: F401
from tests.portals.test_staff_file_access import _login, _staff

pack = dashboard_conftest.pack  # the fixture, shared with the dashboard tests
PAGE = "/student/documents/"

TUM_DEADLINE = datetime(2027, 1, 2, 22, 59, tzinfo=UTC)  # 2 Jan 23:59 Berlin
LUND_DEADLINE = datetime(2027, 4, 1, 21, 59, tzinfo=UTC)


def _card(title, *sentences, deadline=None, zone="", letters=None):
    return CardNeeds(uuid4(), title, tuple(sentences), letters, deadline, zone)


def test_one_entry_per_document_with_every_application_that_needs_it() -> None:
    cards = [
        _card("TUM", "IELTS 6.5 or TOEFL 90", deadline=TUM_DEADLINE, zone="Europe/Berlin"),
        _card("Lund", "Proof of English proficiency", deadline=LUND_DEADLINE,
              zone="Europe/Stockholm"),
        _card("KTH", "Passport copy"),
    ]
    entries = {e.kind: e for e in merge(cards, [])}
    language = entries["LANGUAGE_CERTIFICATE"]
    assert language.headline == "Language certificate — needed by 2 applications"
    assert language.titles == ("TUM", "Lund")
    assert language.needed_by == "needed by 2 Jan for TUM (your first deadline)"
    assert entries["PASSPORT"].needed_by == ""
    assert list(entries) == ["PASSPORT", "LANGUAGE_CERTIFICATE"]


def test_needed_by_names_the_card_without_first_when_it_is_not_the_first() -> None:
    cards = [
        _card("TUM", "Motivation letter", deadline=TUM_DEADLINE, zone="Europe/Berlin"),
        _card("Lund", "Passport", deadline=LUND_DEADLINE, zone="Europe/Stockholm"),
    ]
    entries = {e.kind: e for e in merge(cards, [])}
    assert entries["PASSPORT"].needed_by == "needed by 1 Apr for Lund"


def test_a_certified_copy_stays_a_sub_flag_of_the_one_entry() -> None:
    cards = [_card("TUM", "Certified copy of your diploma"), _card("Lund", "Diploma")]
    entry = merge(cards, [])[0]
    assert (entry.kind, entry.titles, entry.certified) == ("DIPLOMA", ("TUM", "Lund"), ("TUM",))


def test_referee_facts_add_reference_letters_with_the_largest_count() -> None:
    cards = [_card("TUM", letters=2), _card("Lund", letters=1), _card("KTH", letters=0)]
    entry = merge(cards, [])[0]
    assert (entry.kind, entry.titles, entry.letters) == ("REFERENCE_LETTER", ("TUM", "Lund"), 2)


def test_a_passport_that_expires_before_a_card_needs_it_is_flagged() -> None:
    cards = [
        _card("TUM", "Passport", deadline=TUM_DEADLINE, zone="Europe/Berlin"),
        _card("Lund", "Passport", deadline=LUND_DEADLINE, zone="Europe/Stockholm"),
    ]
    passport = Held("PASSPORT", Cell.UPLOADED, expires_on=date(2027, 3, 3))
    entry = merge(cards, [passport])[0]
    assert entry.held is True
    assert entry.validity == "Your passport expires 3 Mar; Lund needs it valid on 1 Apr"


def test_a_passport_with_no_expiry_date_is_never_flagged() -> None:
    cards = [_card("Lund", "Passport", deadline=LUND_DEADLINE, zone="Europe/Stockholm")]
    entry = merge(cards, [Held("PASSPORT", Cell.UPLOADED)])[0]
    assert entry.held is True and entry.validity == ""


def test_a_document_still_being_checked_is_not_held() -> None:
    entry = merge([_card("TUM", "Passport")], [Held("PASSPORT", Cell.CHECKING)])[0]
    assert entry.held is False


def test_nothing_needed_is_an_empty_list() -> None:
    assert merge([], []) == ()
    assert merge([_card("TUM", "Bring enthusiasm")], []) == ()


def _snapshot(day, zone):
    return {"source": "CATALOGUE", "steps": [{
        "position": 1, "purpose": "APPLY", "channel": "PORTAL",
        "dates": [{"role": "FINAL", "date": day, "timezone": zone}],
    }]}


@pytest.fixture
def two_cards(agency_a, membership_a, pack):
    programme, award = pack
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(referee_requirements=[{
            "field": "count", "value": "TWO", "date": "", "conditional": False,
            "condition": "", "rule_text": "Two letters.", "source_url": "https://tum.de/a",
        }])
        programme.refresh_from_db()
        tum = add_card(
            agency_a, membership_a, programme,
            kit_requirements=["IELTS 6.5", "Passport copy"],
            route_snapshot=_snapshot("2027-01-02", "Europe/Berlin"),
        )
        daad = add_card(
            agency_a, membership_a, award, portal=False,
            kit_requirements=["Proof of English proficiency", "Passport"],
            route_snapshot=_snapshot("2027-04-01", "Europe/Berlin"),
        )
        DocumentVersion.objects.create(
            student=membership_a, object_key="k", kind="PASSPORT", state="AVAILABLE",
            expires_on=date(2027, 3, 3),
        )
    return tum, daad


@pytest.mark.django_db
def test_the_documents_page_lists_each_document_once_with_its_applications(
    client, domain_a, user_a, two_cards
) -> None:
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Language certificate — needed by 2 applications" in body
    assert "needed by 2 Jan for M.Sc. Informatics (your first deadline)" in body
    assert "Passport — needed by 2 applications" in body
    assert "Your passport expires 3 Mar; DAAD Study Scholarship needs it valid on 1 Apr" in body
    assert "Recommendation letters — needed by 1 application" in body
    assert "Up to 2 letters for one application" in body
    # The by-application table is still there.
    assert "What each application needs" in body


@pytest.mark.django_db
def test_a_conditional_offer_s_condition_is_a_document_need(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme)
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="GOOGLE", address="s@g.test"
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="tum.de", received_at=timezone.now(), application=card,
            outcome_conditions=["final transcript"],
        )
        card.outcome = "ADMITTED_CONDITIONAL"
        card.outcome_evidence = signal
        card.save(update_fields=["outcome", "outcome_evidence"])
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Transcript — needed by 1 application" in body


@pytest.mark.django_db
def test_the_counselor_sees_the_list_and_staff_do_not(
    counselor_client, client, agency_a, domain_a, membership_a, two_cards
) -> None:
    url = f"/counselor/students/{membership_a.id}/"
    board = counselor_client.get(url, HTTP_HOST=domain_a.host).content.decode()
    assert "Language certificate — needed by 2 applications" in board
    assert "Plan your referees" not in board
    staff, _membership = _staff(agency_a)
    from django.test import Client

    other = Client()
    _login(other, staff)
    response = other.get(url, HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert "By document" not in body and "needed by 2 applications" not in body
    # Not only unrendered: the staff page's context carries no list at all (final review D2).
    assert response.context["by_document"] == ()


def _letters(value):
    return [{
        "field": "count", "value": value, "date": "", "conditional": False,
        "condition": "", "rule_text": f"{value} letters.", "source_url": "https://x.de/a",
    }]


@pytest.mark.django_db
def test_a_decided_card_needs_nothing_and_a_conditional_offer_only_its_conditions(
    client, agency_a, domain_a, user_a, membership_a, pack, program_factory
) -> None:
    """Final review I2: a rejected card is not "your first deadline" and its letters
    are not counted; a conditional offer adds its conditions and nothing else."""
    from tests.funding.conftest import make_db_candidate

    programme, _award = pack

    def card(name, letters, day, *kit, outcome=""):
        candidate = make_db_candidate(agency_a, programme.run, program_name=name)
        with tenant_scope(agency_a.id):
            RecommendationCandidate.objects.filter(id=candidate.id).update(
                program_id=program_factory(name=name).id,
                referee_requirements=_letters(letters),
            )
            candidate.refresh_from_db()
            return add_card(
                agency_a, membership_a, candidate, kit_requirements=list(kit),
                route_snapshot=_snapshot(day, "Europe/Berlin"), outcome=outcome,
            )

    card("Open Programme", "TWO", "2027-01-02", "Passport copy")
    card("Rejected Programme", "THREE_OR_MORE", "2026-09-01", "Passport", "IELTS 6.5",
         outcome="REJECTED")
    card("Admitted Programme", "THREE_OR_MORE", "2026-08-01", "Passport", outcome="ADMITTED")
    offer = card("Offer Programme", "THREE_OR_MORE", "2026-07-01", "Passport", "IELTS 6.5")
    with tenant_scope(agency_a.id):
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="GOOGLE", address="s@g.test"
        )
        offer.outcome = "ADMITTED_CONDITIONAL"
        offer.outcome_evidence = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-2",
            sender_domain="tum.de", received_at=timezone.now(), application=offer,
            outcome_conditions=["final transcript"],
        )
        offer.save(update_fields=["outcome", "outcome_evidence"])
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    listing = body[body.index("By document"):body.index("What each application needs")]
    assert "Passport — needed by 1 application" in listing
    assert "needed by 2 Jan for Open Programme (your first deadline)" in listing
    assert "Up to 2 letters for one application" in listing
    assert "Recommendation letters — needed by 1 application" in listing
    assert "Transcript — needed by 1 application" in listing
    assert "Language certificate" not in listing
    assert "Rejected Programme" not in listing and "Admitted Programme" not in listing
    assert "for Offer Programme" not in listing
