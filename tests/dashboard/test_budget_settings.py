import html
from decimal import Decimal
from unittest import mock

import pytest
from django.core.cache import cache

from apps.accounts.models import StudentProfileVersion
from apps.accounts.profile_versions import create_profile_version
from apps.accounts.schemas import Money
from apps.funding.models import AuditEvent, ExchangeRate, RecommendationCandidate
from apps.funding.rates import store
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import reads_no_catalogue, verify_mfa_session
from tests.funding.conftest import make_db_candidate, make_profile

from .conftest import AZN_RATES, add_card, set_profile

pytestmark = pytest.mark.django_db
PAGE = "/student/settings/budget/"


def _req(method, *args, **kwargs):
    """Every web request runs where the catalogue is unreadable (global constraint)."""
    with reads_no_catalogue():
        return method(*args, **kwargs)


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


def _profile(agency, student, amount="500.00"):
    with tenant_scope(agency.id):
        return create_profile_version(
            student=student,
            snapshot=make_profile(
                country_of_residence="AZ",
                application_budget=Money(amount=Decimal(amount), currency="AZN"),
            ),
        )


def _latest(agency, student) -> dict:
    with tenant_scope(agency.id):
        return (
            StudentProfileVersion.objects.filter(student=student)
            .order_by("-version")
            .first()
        ).snapshot


@pytest.fixture
def two_cards(agency_a, membership_a, pack, program_factory):
    """75 EUR (150 AZN) and 100 EUR (200 AZN), both unpaid: 350 AZN committed."""
    programme, _award = pack
    store(AZN_RATES)
    _profile(agency_a, membership_a)
    physics = make_db_candidate(agency_a, programme.run, program_name="M.Sc. Physics")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=physics.id).update(
            program_id=program_factory(name="M.Sc. Physics").id,
            application_fee="100.00", application_fee_currency="EUR",
        )
        physics.refresh_from_db()
        informatics = add_card(agency_a, membership_a, programme)
        return informatics, add_card(agency_a, membership_a, physics)


def test_a_student_raises_the_budget_and_every_other_answer_is_kept(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    before = _latest(agency_a, membership_a)
    client.force_login(user_a)

    response = _req(client.post, 
        PAGE, {"amount": "800", "currency": "AZN", "stretch": "100"}, HTTP_HOST=domain_a.host
    )

    assert response.status_code == 302
    after = _latest(agency_a, membership_a)
    assert Decimal(after["application_budget"]["amount"]) == 800
    assert after["application_budget"]["currency"] == "AZN"
    assert Decimal(after["budget_stretch"]["amount"]) == 100
    assert after["budget_stretch"]["currency"] == "AZN"
    changed = ("application_budget", "budget_stretch")
    unchanged = {k: v for k, v in before.items() if k not in changed}
    assert {k: after[k] for k in unchanged} == unchanged
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(event="profile.budget_changed").count() == 1


def test_a_counsellor_cannot_reach_the_page(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a, two_cards
):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    other_settings = _req(client.get, "/student/settings/extension/", HTTP_HOST=domain_a.host)

    assert _req(client.get, PAGE, HTTP_HOST=domain_a.host).status_code == other_settings.status_code
    response = _req(client.post, PAGE, {"amount": "1", "currency": "AZN"}, HTTP_HOST=domain_a.host)
    assert response.status_code in (403, 404)
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 500


def test_below_what_is_paid_is_refused_with_the_paid_figure(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    """Review Focus 4."""
    informatics, _physics = two_cards
    with tenant_scope(agency_a.id):
        Application.objects.filter(id=informatics.id).update(
            fee_state="PAID", fee_paid_source="STUDENT"
        )
    client.force_login(user_a)

    response = _req(client.post, PAGE,
        {"amount": "100", "currency": "AZN"},
        HTTP_HOST=domain_a.host)

    assert response.status_code == 400
    assert "already paid 150 AZN" in response.content.decode()
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 500


def test_below_what_is_committed_needs_a_choice_and_drops_only_the_chosen(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    informatics, physics = two_cards
    client.force_login(user_a)

    refused = _req(client.post, PAGE, {"amount": "200", "currency": "AZN"}, HTTP_HOST=domain_a.host)
    assert refused.status_code == 400
    # The error itself: the fieldset's legend says "Choose which…" on every GET.
    assert "150 AZN below the fees you've committed to" in html.unescape(
        refused.content.decode()
    )
    with tenant_scope(agency_a.id):
        assert Application.objects.filter(student=membership_a).count() == 2

    saved = _req(client.post, 
        PAGE, {"amount": "200", "currency": "AZN", "drop": [str(physics.id)]},
        HTTP_HOST=domain_a.host,
    )

    assert saved.status_code == 302
    with tenant_scope(agency_a.id):
        assert list(
            Application.objects.filter(student=membership_a).values_list("id", flat=True)
        ) == [informatics.id]
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 200


def test_a_ticked_card_that_commits_nothing_frees_nothing(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    """A forged tick on a withdrawn card: its fee was never committed, so it
    cannot cover the shortfall and the budget is not saved."""
    informatics, physics = two_cards
    with tenant_scope(agency_a.id):
        Application.objects.filter(id=physics.id).update(outcome="WITHDRAWN")
    client.force_login(user_a)

    # Committed is now 150 (informatics); 100 is 50 short, and only physics is ticked.
    response = _req(client.post, 
        PAGE, {"amount": "100", "currency": "AZN", "drop": [str(physics.id)]},
        HTTP_HOST=domain_a.host,
    )

    assert response.status_code == 400
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 500


def test_a_short_form_profile_is_asked_to_finish_the_consultation(
    client, agency_a, domain_a, user_a, membership_a
):
    # The short form stores the budget as a bare number, with no currency.
    set_profile(agency_a, membership_a, funding_dependency="OPTIONAL", application_budget="150")
    client.force_login(user_a)
    body = _req(client.get, PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Finish your consultation first" in body


def test_the_board_links_the_student_and_not_the_counsellor(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    client.force_login(user_a)
    body = _req(client.get, "/student/", HTTP_HOST=domain_a.host).content.decode()
    assert f'href="{PAGE}"' in body
    assert "Change my application budget" in body


def test_a_stretch_in_another_currency_survives_an_unchanged_save(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    with tenant_scope(agency_a.id):
        create_profile_version(
            student=membership_a,
            snapshot=make_profile(
                country_of_residence="AZ",
                application_budget=Money(amount=Decimal("500"), currency="AZN"),
                budget_stretch=Money(amount=Decimal("100"), currency="USD"),
            ),
        )
    client.force_login(user_a)
    body = _req(client.get, PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert 'name="stretch_currency"' in body and 'value="USD"' in body

    response = _req(
        client.post, PAGE,
        {"amount": "500", "currency": "AZN", "stretch": "100", "stretch_currency": "USD"},
        HTTP_HOST=domain_a.host,
    )

    assert response.status_code == 302
    after = _latest(agency_a, membership_a)["budget_stretch"]
    assert (Decimal(after["amount"]), after["currency"]) == (100, "USD")


def _versions(agency, student) -> int:
    with tenant_scope(agency.id):
        return StudentProfileVersion.objects.filter(student=student).count()


def _no_rates(agency):
    with tenant_scope(agency.id):
        ExchangeRate.objects.all().delete()


def test_without_rates_a_lower_budget_is_refused_while_a_paid_fee_exists(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    informatics, _physics = two_cards
    with tenant_scope(agency_a.id):
        Application.objects.filter(id=informatics.id).update(fee_state="PAID")
    _no_rates(agency_a)
    client.force_login(user_a)

    response = _req(client.post, PAGE, {"amount": "1", "currency": "AZN"}, HTTP_HOST=domain_a.host)

    assert response.status_code == 400
    assert "until today's exchange rates are loaded" in html.unescape(response.content.decode())
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 500


def test_without_rates_a_raise_still_saves(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    _no_rates(agency_a)
    client.force_login(user_a)
    response = _req(client.post, PAGE,
        {"amount": "900", "currency": "AZN"},
        HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 900


def test_a_student_with_no_home_currency_and_no_fees_can_lower_the_budget(
    client, agency_a, domain_a, user_a, membership_a
):
    with tenant_scope(agency_a.id):
        create_profile_version(
            student=membership_a,
            snapshot=make_profile(
                country_of_residence="FR",
                application_budget=Money(amount=Decimal("500"), currency="EUR"),
            ),
        )
    client.force_login(user_a)
    response = _req(client.post, PAGE,
        {"amount": "100", "currency": "EUR"},
        HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 100


def test_ticks_are_ignored_when_there_is_no_shortfall(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    _informatics, physics = two_cards
    client.force_login(user_a)
    response = _req(
        client.post, PAGE, {"amount": "800", "currency": "AZN", "drop": [str(physics.id)]},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        assert Application.objects.filter(student=membership_a).count() == 2
    # Final review M4: the ignored ticks are said to be ignored.
    said = [str(m) for m in response.wsgi_request._messages]
    assert said == [
        "Your application budget is saved.",
        "Nothing was dropped: your budget covers your applications.",
    ]


def test_without_ticks_only_the_save_is_reported(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    client.force_login(user_a)
    response = _req(client.post, PAGE, {"amount": "800", "currency": "AZN"},
                    HTTP_HOST=domain_a.host)
    assert [str(m) for m in response.wsgi_request._messages] == [
        "Your application budget is saved."
    ]


def test_a_card_paid_in_another_tab_is_not_dropped(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    """The board is read, then the other tab marks the ticked card PAID."""
    _informatics, physics = two_cards
    versions = _versions(agency_a, membership_a)
    client.force_login(user_a)
    from apps.accounts import views

    real = views.board_for
    calls = []

    def racing(student):
        board = real(student)
        if not calls:
            calls.append(1)
            with tenant_scope(agency_a.id):
                Application.objects.filter(id=physics.id).update(fee_state="PAID")
        return board

    with mock.patch.object(views, "board_for", racing):
        response = _req(
            client.post, PAGE, {"amount": "200", "currency": "AZN", "drop": [str(physics.id)]},
            HTTP_HOST=domain_a.host,
        )

    assert response.status_code == 400
    with tenant_scope(agency_a.id):
        assert Application.objects.filter(student=membership_a).count() == 2
        assert StudentProfileVersion.objects.filter(student=membership_a).count() == versions


def test_a_failure_part_way_through_the_drops_removes_nothing(
    client, agency_a, domain_a, user_a, membership_a, two_cards
):
    from apps.accounts import views
    from apps.portals.applications import ApplicationRefused, remove_application

    versions = _versions(agency_a, membership_a)
    client.force_login(user_a)
    seen = []

    def flaky(application, *, actor):
        if seen:
            raise ApplicationRefused("rate_limited")
        seen.append(application.id)
        remove_application(application, actor=actor)

    with mock.patch.object(views, "remove_application", flaky):
        response = _req(
            client.post, PAGE,
            {"amount": "1", "currency": "AZN", "drop": [str(a.id) for a in two_cards]},
            HTTP_HOST=domain_a.host,
        )

    assert response.status_code == 400
    with tenant_scope(agency_a.id):
        assert Application.objects.filter(student=membership_a).count() == 2
        assert StudentProfileVersion.objects.filter(student=membership_a).count() == versions
        assert not AuditEvent.objects.filter(event="profile.budget_changed").exists()


def test_removing_a_paid_card_withdraws_it_and_keeps_the_payment(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    """Final review I3. A paid card was deleted by Remove: the only record of
    the payment went with it, and the budget could then be lowered below money
    already spent. Paid counts as touched, so the card is withdrawn instead."""
    from apps.dashboard.board import board_for

    programme, _award = pack  # 75 EUR = 150 AZN
    store(AZN_RATES)
    _profile(agency_a, membership_a, "300.00")
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme, fee_state="PAID")
    client.force_login(user_a)

    _req(client.post, f"/student/applications/{card.id}/remove/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        card.refresh_from_db()
        assert card.outcome == "WITHDRAWN"
        assert "Paid 150" in board_for(membership_a).budget.text
    response = _req(client.post, PAGE, {"amount": "10", "currency": "AZN"},
                    HTTP_HOST=domain_a.host)
    assert response.status_code == 400
    assert "already paid 150 AZN" in response.content.decode()
    assert Decimal(_latest(agency_a, membership_a)["application_budget"]["amount"]) == 300


def test_a_paid_card_offers_no_remove_button(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    """I3: Remove would only withdraw a paid card, so it is not offered."""
    programme, _award = pack
    _profile(agency_a, membership_a, "300.00")
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme, fee_state="PAID")
    client.force_login(user_a)
    body = _req(client.get, "/student/", HTTP_HOST=domain_a.host).content.decode()
    start = body.index(f'<article id="card-{card.id}"')
    article = body[start : body.index("</article>", start)]
    assert "Application fee paid" in article  # the card is rendered, in To start
    assert f'action="/student/applications/{card.id}/remove/"' not in article
