from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.funding.models import (
    FundingOpportunity,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
)
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import reads_no_catalogue
from tests.funding.conftest import make_db_candidate, make_run

from .conftest import add_card

pytestmark = pytest.mark.django_db


def test_home_shows_needs_then_the_board(client, agency_a, domain_a, user_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, deadline=timezone.now() + timedelta(days=5),
            kit_requirements=["Transcript of records"],
        )
    client.force_login(user_a)
    with reads_no_catalogue():
        response = client.get("/student/", HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert response.status_code == 200
    assert body.index("Needs you now") < body.index("Your applications")
    assert "To start" in body and "TUM — M.Sc. Informatics" in body
    assert "M.Sc. Informatics" in body
    assert "Transcript — needed for M.Sc. Informatics" in body
    # No extension here: the start form is replaced by a sentence (lanes §5.1).
    assert f"/student/applications/{application.id}/start/" not in body
    assert "Application fee: 75.00 EUR — you pay this at submission" in body


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
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "M.Sc. Informatics" not in body


def test_a_decision_card_offers_not_right(client, agency_a, domain_a, user_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, state="SUBMITTED", outcome="ADMITTED",
            outcome_source="MAIL", outcome_recorded_at=timezone.now(),
        )
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Not right?" in body
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
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    for key, application in ids.items():
        start = body.index(f'<article id="card-{application.id}"')
        card = body[start : body.index("</article>", start)]
        assert (f'action="/student/applications/{application.id}/remove/"' in card) == (
            key == "to_start"
        ), key
        assert (f'action="/student/applications/{application.id}/outcome/"' in card) == (
            key != "to_start"
        ), key


def test_a_lane_asks_does_this_apply_to_you(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    run = programme.run
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
        opportunity = FundingOpportunity.objects.create(
            canonical_key=f"award:{uuid4()}", name="SI Scholarship",
            family="UNIVERSITY_WIDE", scope_type="GLOBAL",
        )
        ask = make_db_candidate(
            agency_a, run, program_name="SI Scholarship", evidence_confidence="LOW"
        )
        RecommendationCandidate.objects.filter(id=ask.id).update(
            opportunity_id=opportunity.id,
            funding_card={"scope": "GLOBAL", "route": "STUDENT_APPLIES_SEPARATELY"},
        )
        PackCandidate.objects.create(
            pack_version=PackVersion.objects.get(run=run), candidate=ask
        )
        ask.refresh_from_db()
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Does this apply to you?" in body
    assert ask.evidence.claim in body
    assert f"/student/applications/add/{ask.id}/" in body
    assert "Suggested" not in body


def test_a_non_https_official_page_renders_no_link(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
        opportunity = FundingOpportunity.objects.create(
            canonical_key=f"award:{uuid4()}", name="Mystery fund",
            family="UNIVERSITY_WIDE", scope_type="GLOBAL",
        )
        fund = make_db_candidate(agency_a, programme.run, program_name="Mystery fund")
        RecommendationCandidate.objects.filter(id=fund.id).update(
            opportunity_id=opportunity.id, funding_card={"scope": "GLOBAL", "route": "UNSTATED"},
        )
        fund.evidence.source_url = "http://official.example.test/fund"
        fund.evidence.save()
        PackCandidate.objects.create(
            pack_version=PackVersion.objects.get(run=programme.run), candidate=fund
        )
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Mystery fund: How to apply for this is not stated" in body
    assert "http://official.example.test/fund" not in body
    assert 'href=""' not in body


def test_apply_button_follows_browser_and_pairing(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    from apps.portals.models import ExtensionPairing

    from .test_device import CHROME

    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(
            agency_a, membership_a, programme, deadline=timezone.now() + timedelta(days=5)
        )
    client.force_login(user_a)
    apply_text = "Apply to M.Sc. Informatics"

    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Open this in Chrome or Edge to apply" in body and apply_text not in body
    needs = body[body.index("Needs you now"):body.index("Your applications")]
    assert "is not started yet" in needs and "Open this in Chrome or Edge to apply" in needs
    assert apply_text not in needs

    body = client.get("/student/", HTTP_HOST=domain_a.host, HTTP_USER_AGENT=CHROME).content.decode()
    assert "Install the extension to apply" in body and "/student/settings/extension/" in body
    assert apply_text not in body

    with tenant_scope(agency_a.id):
        ExtensionPairing.objects.create(
            tenant=agency_a, membership=membership_a, code_hash="a" * 64,
            redeemed_at=timezone.now(),
        )
    body = client.get("/student/", HTTP_HOST=domain_a.host, HTTP_USER_AGENT=CHROME).content.decode()
    assert apply_text in body


def test_a_closed_lane_offers_nothing_to_do(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    from apps.portals.models import ExtensionPairing

    from .test_device import CHROME

    programme, _award = pack
    opportunity = FundingOpportunity.objects.create(
        canonical_key=f"award:{uuid4()}", name="DAAD Study Scholarship",
        family="UNIVERSITY_WIDE", scope_type="GLOBAL",
    )
    with tenant_scope(agency_a.id):
        add_card(
            agency_a, membership_a, programme, deadline=timezone.now() - timedelta(days=2),
            deadline_timezone="Europe/Berlin",
        )
        ask = make_db_candidate(
            agency_a, programme.run, program_name="SI Scholarship", evidence_confidence="LOW"
        )
        RecommendationCandidate.objects.filter(id=ask.id).update(
            opportunity_id=opportunity.id,
            funding_card={"scope": "GLOBAL", "route": "STUDENT_APPLIES_SEPARATELY"},
        )
        PackCandidate.objects.create(
            pack_version=PackVersion.objects.get(run=programme.run), candidate=ask
        )
        ExtensionPairing.objects.create(
            tenant=agency_a, membership=membership_a, code_hash="b" * 64,
            redeemed_at=timezone.now(),
        )
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get(
            "/student/", HTTP_HOST=domain_a.host, HTTP_USER_AGENT=CHROME
        ).content.decode()
    assert body.count("Closed for this intake") == 1
    assert "Apply to" not in body
    assert "Yes, add" not in body and "/student/applications/add/" not in body
    assert "is not started yet" not in body


def test_the_rate_note_appears_once_however_many_amounts(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    from apps.funding.rates import store

    from .conftest import AZN_RATES, set_profile

    programme, award = pack
    store(AZN_RATES)
    set_profile(agency_a, membership_a, country_of_residence="AZ")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            application_fee="20.00", application_fee_currency="USD"
        )
        award.refresh_from_db()
        add_card(agency_a, membership_a, programme)
        add_card(agency_a, membership_a, award, portal=False)
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Application fee: 75.00 EUR ≈ 150 AZN — you pay this at submission" in body
    assert "20.00 USD ≈ 32 AZN" in body
    assert body.count("Converted at the CBAR rate") == 1
