from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import reads_no_catalogue
from tests.funding.conftest import make_db_candidate, make_run

from .conftest import add_card

pytestmark = pytest.mark.django_db


def test_home_shows_milestones_then_next_actions(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(
            agency_a, membership_a, programme, deadline=timezone.now() + timedelta(days=5),
            kit_requirements=["Transcript of records"],
        )
    client.force_login(user_a)
    with reads_no_catalogue():
        response = client.get("/student/", HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert response.status_code == 200
    assert body.index('aria-label="Your progress"') < body.index("Next actions")
    assert "Transcript — needed for M.Sc. Informatics" in body
    assert "M.Sc. Informatics" in body  # the upcoming deadline
    # The board lives on My applications now, not on the home page.
    assert "To start" not in body


def test_my_applications_shows_the_board(client, agency_a, domain_a, user_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, deadline=timezone.now() + timedelta(days=5),
            kit_requirements=["Transcript of records"],
        )
    client.force_login(user_a)
    with reads_no_catalogue():
        response = client.get("/student/applications/", HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert response.status_code == 200
    for heading in ("To start", "In progress", "Submitted", "Confirmed", "Decision"):
        assert heading in body
    assert "M.Sc. Informatics" in body
    assert f'action="/student/applications/{application.id}/start/"' in body
    assert "Application fee: 75.00 EUR, paid at submission" in body


def test_home_never_shows_another_students_card(
    client, agency_a, domain_a, user_a, membership_a, user_b, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        add_card(agency_a, other, programme)
    client.force_login(user_a)
    for page in ("/student/", "/student/applications/"):
        body = client.get(page, HTTP_HOST=domain_a.host).content.decode()
        assert "M.Sc. Informatics" not in body


def test_a_decision_card_offers_a_change(client, agency_a, domain_a, user_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, state="SUBMITTED", outcome="ADMITTED",
            outcome_source="MAIL", outcome_recorded_at=timezone.now(),
        )
    client.force_login(user_a)
    body = client.get("/student/applications/", HTTP_HOST=domain_a.host).content.decode()
    assert "Change the decision" in body
    assert f'action="/student/applications/{application.id}/outcome/"' in body
    assert '<label for="outcome-' in body


@pytest.mark.parametrize("authenticated", [True, False])
def test_an_offer_asks_accept_or_ignore(
    client, agency_a, domain_a, user_a, membership_a, pack, authenticated
):
    """Tag-only, the offer is read to the student, as on Messages (final review M1)."""
    from apps.mailbox.models import MailboxConnection, MailSignal

    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT", address="a@o.test"
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="tum.de", received_at=timezone.now(), application=application,
            label="DECISION", offered_programme="M.Sc. Data Engineering", trusted=True,
            sender_authenticated=authenticated,
        )
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    stated = "TUM offers you a place in M.Sc. Data Engineering"
    read = "TUM — the email reads: offers a place in M.Sc. Data Engineering (unverified)"
    assert (stated in body, read in body) == (authenticated, not authenticated)
    assert f'action="/student/offers/{signal.id}/accept/"' in body
    assert f'action="/student/offers/{signal.id}/ignore/"' in body


def test_each_column_renders_its_own_key_dependent_markup(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    """The card compares the column key, never the heading (controller ruling F25)."""
    now = timezone.now()
    run = make_run(agency_a, membership_a)
    cases = {
        "to_start": {},
        "in_progress": {"started_at": now},
        "submitted": {"state": "SUBMITTED"},
        "confirmed": {"state": "CONFIRMED"},
        "decision": {"state": "SUBMITTED", "outcome": "ADMITTED", "outcome_recorded_at": now},
    }
    ids = {}
    with tenant_scope(agency_a.id):
        for key, fields in cases.items():
            candidate = make_db_candidate(agency_a, run, program_name=f"Programme {key}")
            candidate.program_id = uuid4()
            ids[key] = add_card(agency_a, membership_a, candidate, **fields)
    client.force_login(user_a)
    body = client.get("/student/applications/", HTTP_HOST=domain_a.host).content.decode()
    for key, application in ids.items():
        start = body.index(f'<article id="card-{application.id}"')
        card = body[start : body.index("</article>", start)]
        assert (f'action="/student/applications/{application.id}/remove/"' in card) == (
            key == "to_start"
        ), key
        assert (f'action="/student/applications/{application.id}/outcome/"' in card) == (
            key != "to_start"
        ), key
