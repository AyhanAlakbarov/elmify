"""One over-budget confirmation for every way a programme reaches the plan
(owner 2026-10-14): Add, Replace and New for you. A counsellor is refused."""

import html
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.dashboard.money import BudgetLine, over_budget
from apps.funding.models import AuditEvent, PackCandidate, PackVersion, RecommendationCandidate
from apps.funding.rates import store
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import reads_no_catalogue, verify_mfa_session
from tests.funding.conftest import make_db_candidate

from .conftest import AZN_RATES, add_card, set_profile

pytestmark = pytest.mark.django_db

TITLE = "This is over your application budget"


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


# --- the pure rule -----------------------------------------------------------


def _line(free: str, extra: str | None = None) -> BudgetLine:
    return BudgetLine(
        currency="AZN", plan=Decimal(free), extra=Decimal(extra) if extra else None,
        paid=Decimal("0"), committed=Decimal("0"), not_known=0, no_rate=0, converted=False,
    )


def _check(fee, *, line, budget_set=True, currency="AZN"):
    return over_budget(
        fee=None if fee is None else Decimal(fee), currency=currency, line=line,
        budget_set=budget_set, table=AZN_RATES, home="AZN",
    )


def test_an_exact_fit_is_not_over() -> None:
    assert _check("100.00", line=_line("103")) is None  # 100 x 1.03 == 103


def test_a_stated_zero_fee_always_fits() -> None:
    assert _check("0.00", line=_line("0")) is None


def test_one_cent_over_is_over_by_a_whole_unit_rounded_up() -> None:
    overrun = _check("100.01", line=_line("103"))
    assert (overrun.kind, overrun.free, overrun.over) == ("OVER", "103 AZN", "1 AZN")


@pytest.mark.parametrize(
    ("fee", "kind", "over"), [("109.70", "STRETCH", "10 AZN"), ("109.71", "OVER", "11 AZN")]
)
def test_the_extra_reaches_exactly_as_far_as_its_amount(fee, kind, over) -> None:
    # 109.70 x 1.03 = 112.991, 9.991 over 103; 109.71 x 1.03 = 113.0013, 10.0013 over.
    overrun = _check(fee, line=_line("103", extra="10"))
    assert (overrun.kind, overrun.over) == (kind, over)


def test_no_budget_has_nothing_to_exceed_but_one_we_cannot_convert_asks() -> None:
    assert _check("50.00", line=None, budget_set=False) is None
    overrun = _check("50.00", line=None)
    assert overrun.kind == "BUDGET_NO_RATE"
    assert overrun.body == (
        "The application fee is 50.00 AZN. We can't convert your budget's currency yet, "
        "so we can't tell whether it fits your budget."
    )
    assert overrun.tick == "Add it anyway"


# --- the student's Add -------------------------------------------------------


def _budget(agency, student, amount, stretch=None):
    snapshot = {
        "country_of_residence": "AZ",
        "application_budget": {"amount": amount, "currency": "AZN"},
    }
    if stretch:
        snapshot["budget_stretch"] = {"amount": stretch, "currency": "AZN"}
    set_profile(agency, student, **snapshot)


def _fee(agency, candidate, fee, currency="EUR"):
    with tenant_scope(agency.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(
            application_fee=fee, application_fee_currency=currency
        )


def _cards(agency, candidate) -> int:
    with tenant_scope(agency.id):
        return Application.objects.filter(candidate=candidate).count()


def _page(client, url, host, data=None) -> tuple[int, str]:
    """A POST that is expected to render the page: no write, no catalogue read."""
    with reads_no_catalogue():
        response = client.post(url, data or {}, HTTP_HOST=host)
    return response.status_code, html.unescape(response.content.decode())


def _add(candidate) -> str:
    return f"/student/applications/add/{candidate.id}/"


@pytest.fixture
def signed_in(client, user_a, pack):
    """The pack's programme: 75.00 EUR, 150 AZN, 154.50 with the bank margin."""
    store(AZN_RATES)
    client.force_login(user_a)
    return client


def test_an_over_budget_add_asks_first_and_adds_once_confirmed(
    signed_in, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    _budget(agency_a, membership_a, "100.00")

    status, body = _page(signed_in, _add(programme), domain_a.host)
    assert status == 200
    assert TITLE in body
    assert (
        "The application fee is 75.00 EUR ≈ 150 AZN. You have 100 AZN left in your budget, "
        "so adding it puts you about 55 AZN over."
    ) in body
    assert "I understand this takes me about 55 AZN over my budget" in body
    assert "Change my budget" in body
    assert _cards(agency_a, programme) == 0

    # Submitted without the tick (the browser's `required` bypassed): refused.
    status, body = _page(signed_in, _add(programme), domain_a.host, {"seen": "1"})
    assert status == 200 and "Tick the box to add it." in body
    assert _cards(agency_a, programme) == 0

    added = signed_in.post(_add(programme), {"confirm": "1"}, HTTP_HOST=domain_a.host)
    assert added.status_code == 302
    assert _cards(agency_a, programme) == 1

    again = signed_in.post(
        _add(programme), {"confirm": "1"}, HTTP_HOST=domain_a.host, follow=True
    )
    assert again.status_code == 200
    assert "This is already in your applications." in again.content.decode()
    assert _cards(agency_a, programme) == 1
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(
            actor=membership_a, event="application.added_over_budget"
        ).count() == 1


def test_a_programme_that_fits_is_added_at_once(signed_in, agency_a, domain_a, membership_a, pack):
    programme, _award = pack
    _budget(agency_a, membership_a, "200.00")
    response = signed_in.post(_add(programme), HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert _cards(agency_a, programme) == 1


@pytest.mark.parametrize(
    ("stretch", "fee", "currency", "sentence", "tick"),
    [
        (
            "100.00", "75.00", "EUR",
            "The application fee is 75.00 EUR ≈ 150 AZN. It doesn't fit your plan, but it fits "
            "the extra you allowed: it uses about 55 AZN of your 100 AZN extra.",
            "Use about 55 AZN from my extra",
        ),
        (
            None, "1200.00", "ISK",
            "The application fee is 1200.00 ISK. We can't convert this currency yet, so we "
            "can't tell whether it fits your budget.",
            "Add it anyway",
        ),
        (
            None, None, "",
            "We don't know this programme's application fee yet, so we can't tell whether it "
            "fits your budget.",
            "Add it anyway",
        ),
    ],
    ids=["stretch", "no-rate", "unknown"],
)
def test_the_page_says_why_it_asks(
    signed_in, agency_a, domain_a, membership_a, pack, stretch, fee, currency, sentence, tick
):
    programme, _award = pack
    _budget(agency_a, membership_a, "100.00", stretch=stretch)
    _fee(agency_a, programme, fee, currency)
    status, body = _page(signed_in, _add(programme), domain_a.host)
    assert status == 200
    assert sentence in body
    assert tick in body
    assert _cards(agency_a, programme) == 0


def test_a_scholarship_copies_no_fee_and_is_added_without_the_page(
    signed_in, agency_a, domain_a, membership_a, pack
):
    _programme, award = pack
    _budget(agency_a, membership_a, "100.00")
    assert signed_in.post(_add(award), HTTP_HOST=domain_a.host).status_code == 302
    assert _cards(agency_a, award) == 1


def test_a_short_form_budget_has_nothing_to_exceed(
    signed_in, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    set_profile(agency_a, membership_a, country_of_residence="AZ", application_budget="50")
    _fee(agency_a, programme, None, "")
    assert signed_in.post(_add(programme), HTTP_HOST=domain_a.host).status_code == 302
    assert _cards(agency_a, programme) == 1


# --- Replace -------------------------------------------------------------------


@pytest.fixture
def swap_in(agency_a, pack):
    """A pool item outside the pack: 120.00 EUR, 240 AZN, 247.20 with the margin."""
    programme, _award = pack
    item = make_db_candidate(agency_a, programme.run, program_name="MSc Pool")
    _fee(agency_a, item, "120.00")
    return item


def _replace(candidate) -> str:
    return f"/student/recommendation/candidates/{candidate.id}/replace/"


def _in_pack(agency, candidate) -> bool:
    with tenant_scope(agency.id):
        latest = PackVersion.objects.filter(run_id=candidate.run_id).order_by("-version").first()
        return PackCandidate.objects.filter(pack_version=latest, candidate=candidate).exists()


def test_an_over_budget_swap_in_asks_first_and_swaps_once_confirmed(
    signed_in, agency_a, domain_a, membership_a, pack, swap_in
):
    programme, _award = pack
    _budget(agency_a, membership_a, "200.00")
    choice = {"replacement_candidate_id": str(swap_in.id)}

    status, body = _page(signed_in, _replace(programme), domain_a.host, choice)
    assert status == 200
    assert (
        "The application fee is 120.00 EUR ≈ 240 AZN. You have 200 AZN left in your budget, "
        "so adding it puts you about 48 AZN over."
    ) in body
    assert f'value="{swap_in.id}"' in body  # the page carries the choice to the confirm
    assert not _in_pack(agency_a, swap_in)

    done = signed_in.post(_replace(programme), {**choice, "confirm": "1"}, HTTP_HOST=domain_a.host)
    assert done.status_code == 302
    assert _in_pack(agency_a, swap_in)
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(
            actor=membership_a, event="candidate.replaced_over_budget", object_id=swap_in.id
        ).exists()


def test_a_swap_in_that_fits_is_made_at_once(
    signed_in, agency_a, domain_a, membership_a, pack, swap_in
):
    programme, _award = pack
    _budget(agency_a, membership_a, "300.00")
    done = signed_in.post(
        _replace(programme), {"replacement_candidate_id": str(swap_in.id)},
        HTTP_HOST=domain_a.host,
    )
    assert done.status_code == 302
    assert _in_pack(agency_a, swap_in)


# --- the counsellor ------------------------------------------------------------


@pytest.fixture
def counselor_client(client, agency_a, counselor_user, counselor_membership, membership_a, pack):
    store(AZN_RATES)
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    return client


def _counselor_add(client, student, candidate, host):
    return client.post(
        f"/counselor/students/{student.id}/applications/add/{candidate.id}/",
        HTTP_HOST=host, follow=True,
    )


def _counselor_page(client, student, candidate, host, data=None):
    response = client.post(
        f"/counselor/students/{student.id}/applications/add/{candidate.id}/",
        data or {}, HTTP_HOST=host,
    )
    return response, html.unescape(response.content.decode())


def _audits(agency, actor) -> int:
    with tenant_scope(agency.id):
        return AuditEvent.objects.filter(
            actor=actor, event="application.added_over_budget"
        ).count()


def test_a_counsellors_over_budget_add_asks_in_their_words_and_adds_once_ticked(
    counselor_client, agency_a, domain_a, membership_a, counselor_membership, pack
):
    programme, _award = pack
    _budget(agency_a, membership_a, "100.00")
    name = membership_a.display_name
    with reads_no_catalogue():
        response, body = _counselor_page(counselor_client, membership_a, programme, domain_a.host)
    assert response.status_code == 200
    assert f"This is over {name}'s application budget" in body
    assert (
        f"The application fee is 75.00 EUR ≈ 150 AZN. {name} has 100 AZN left in their "
        "budget, so adding it puts them about 55 AZN over."
    ) in body
    assert f"I understand this takes {name} about 55 AZN over their budget" in body
    assert "Change my budget" not in body
    assert f"/counselor/students/{membership_a.id}/applications/add/{programme.id}/" in body
    assert _cards(agency_a, programme) == 0

    with reads_no_catalogue():
        _response, body = _counselor_page(
            counselor_client, membership_a, programme, domain_a.host, {"seen": "1"}
        )
    assert "Tick the box to add it." in body
    assert _cards(agency_a, programme) == 0

    done, _ = _counselor_page(
        counselor_client, membership_a, programme, domain_a.host, {"confirm": "1"}
    )
    assert done.status_code == 302
    assert _cards(agency_a, programme) == 1
    assert _audits(agency_a, counselor_membership) == 1


def test_a_counsellors_stretch_add_names_the_extra_the_student_allowed(
    counselor_client, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    _budget(agency_a, membership_a, "100.00", stretch="100.00")
    name = membership_a.display_name
    with reads_no_catalogue():
        _response, body = _counselor_page(counselor_client, membership_a, programme, domain_a.host)
    assert (
        f"It doesn't fit {name}'s plan, but it fits the extra {name} allowed: it uses about "
        "55 AZN of their 100 AZN extra."
    ) in body
    assert f"Use about 55 AZN from {name}'s extra" in body
    assert "Change my budget" not in body
    assert _cards(agency_a, programme) == 0


def test_a_counsellor_still_adds_a_programme_that_fits(
    counselor_client, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    _budget(agency_a, membership_a, "200.00")
    _counselor_add(counselor_client, membership_a, programme, domain_a.host)
    assert _cards(agency_a, programme) == 1


def test_a_budget_we_cannot_convert_asks_before_adding(
    client, user_a, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack  # no rate table is stored in this test
    client.force_login(user_a)
    set_profile(
        agency_a, membership_a, country_of_residence="AZ",
        application_budget={"amount": "500.00", "currency": "EUR"},
    )
    status, body = _page(client, _add(programme), domain_a.host)
    assert status == 200
    assert (
        "We can't convert your budget's currency yet, so we can't tell whether it fits "
        "your budget."
    ) in body
    assert _cards(agency_a, programme) == 0


def test_the_extra_already_used_is_not_available_again(
    signed_in, agency_a, domain_a, membership_a, pack, program_factory
):
    programme, _award = pack
    # Plan 50, extra 100. A 100 AZN card already uses 50 of the extra, so only 50 is
    # left; 58 AZN x 1.03 = 59.74 is over by 60 and does not fit it.
    _budget(agency_a, membership_a, "50.00", stretch="100.00")
    used = make_db_candidate(agency_a, programme.run, program_name="MSc Used")
    _fee(agency_a, used, "100.00", "AZN")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=used.id).update(
            program_id=program_factory(name="MSc Used").id
        )
        used.refresh_from_db()
        add_card(agency_a, membership_a, used)
    _fee(agency_a, programme, "58.00", "AZN")
    status, body = _page(signed_in, _add(programme), domain_a.host)
    assert status == 200
    assert "puts you about 60 AZN over." in body
    assert "fits the extra you allowed" not in body


def test_a_programme_already_a_card_is_not_asked_about_again(
    signed_in, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    _budget(agency_a, membership_a, "100.00")
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
    response = signed_in.post(_add(programme), HTTP_HOST=domain_a.host, follow=True)
    assert response.status_code == 200
    body = html.unescape(response.content.decode())
    assert "This is already in your applications." in body
    assert TITLE not in body
    assert _cards(agency_a, programme) == 1


def test_unconfirmed_adds_are_rate_limited_before_the_page(
    signed_in, agency_a, domain_a, membership_a, pack
):
    programme, _award = pack
    _budget(agency_a, membership_a, "100.00")
    for _ in range(20):
        assert _page(signed_in, _add(programme), domain_a.host)[0] == 200
    response = signed_in.post(_add(programme), HTTP_HOST=domain_a.host, follow=True)
    body = html.unescape(response.content.decode())
    assert "Too many requests" in body
    assert TITLE not in body


CANNOT = "We can't check this against your budget"


@pytest.mark.parametrize(
    "kind,title",
    [("OVER", TITLE), ("STRETCH", TITLE), ("UNKNOWN", CANNOT), ("NO_RATE", CANNOT),
     ("BUDGET_NO_RATE", CANNOT)],
)
def test_only_a_fee_known_to_be_over_is_called_over(kind, title) -> None:
    """Final review I2: nothing is known to be over when the fee, its rate or
    the budget's rate is missing, so the headline does not say so."""
    from apps.dashboard.money import Overrun

    assert Overrun(kind).title == title
    counsellor = Overrun(kind, who="Aysel").title
    assert counsellor == (
        "This is over Aysel's application budget" if title == TITLE
        else "We can't check this against Aysel's budget"
    )


def test_an_unknown_fee_page_does_not_say_over(
    signed_in, agency_a, domain_a, membership_a, pack
):
    """I2 through the page (the reviewer's P3 shape): a budget of 5000 AZN and a
    fee nobody states."""
    programme, _award = pack
    store(AZN_RATES)
    _budget(agency_a, membership_a, "5000.00")
    _fee(agency_a, programme, None, "")
    status, body = _page(signed_in, _add(programme), domain_a.host)
    assert status == 200
    assert f"<h1>{CANNOT}</h1>" in body
    assert TITLE not in body
    assert _cards(agency_a, programme) == 0


def test_the_over_budget_swap_and_its_audit_row_commit_together(
    signed_in, agency_a, domain_a, membership_a, pack, swap_in, monkeypatch
):
    """Final review M3: the audit row is written in the swap's own transaction,
    so a swap never lands without the record of who confirmed it."""
    programme, _award = pack
    _budget(agency_a, membership_a, "200.00")
    real = AuditEvent.objects.create

    def failing(**kwargs):
        if kwargs.get("event") == "candidate.replaced_over_budget":
            raise RuntimeError("audit write failed")
        return real(**kwargs)

    monkeypatch.setattr(AuditEvent.objects, "create", failing)
    with pytest.raises(RuntimeError):
        signed_in.post(
            _replace(programme),
            {"replacement_candidate_id": str(swap_in.id), "confirm": "1"},
            HTTP_HOST=domain_a.host,
        )
    assert not _in_pack(agency_a, swap_in)
