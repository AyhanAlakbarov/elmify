"""The cycle wallet (spec 10.5, decision 28): money, so every rule is durable."""

import logging
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.research.models import SearchTap, SearchWallet, WalletCharge
from apps.research.wallet import (
    TapRefused,
    WalletExhausted,
    charge,
    check_tap_permitted,
    open_wallet,
    page_backstop,
    preflight,
    tap_allowance,
    tap_spent,
    tenant_spend_today,
)
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

_INTAKE = date(2027, 9, 1)


def test_one_wallet_per_student_and_intake(student) -> None:
    a = open_wallet(student, _INTAKE)
    b = open_wallet(student, _INTAKE)
    assert a.id == b.id and a.budget_usd == Decimal("50")
    assert SearchWallet.objects.count() == 1


def test_a_third_intake_inside_a_year_reuses_the_newest_wallet(student) -> None:
    open_wallet(student, _INTAKE)
    second = open_wallet(student, date(2028, 2, 1))
    third = open_wallet(student, date(2028, 9, 1))
    assert third.id == second.id
    assert SearchWallet.objects.count() == 2


def test_a_wallet_older_than_a_year_does_not_count_against_the_cap(student) -> None:
    first = open_wallet(student, _INTAKE)
    second = open_wallet(student, date(2028, 2, 1))
    SearchWallet.objects.filter(id__in=(first.id, second.id)).update(
        created_at=timezone.now() - timedelta(days=366)
    )
    third = open_wallet(student, date(2028, 9, 1))
    assert third.id not in {first.id, second.id}


def test_a_tap_may_spend_at_most_half_of_what_remains(student) -> None:
    wallet = open_wallet(student, _INTAKE)
    assert tap_allowance(wallet) == Decimal("25")
    wallet.spent_usd = Decimal("40")
    assert tap_allowance(wallet) == Decimal("5")


def test_a_september_tap_leaves_money_for_february(student) -> None:
    wallet = open_wallet(student, _INTAKE)
    for _ in range(6):  # six taps, each spending its whole allowance
        wallet.spent_usd += tap_allowance(wallet)
    assert wallet.budget_usd - wallet.spent_usd > Decimal("0.5")


def test_preflight_refuses_a_call_past_the_tap_allowance_and_records_nothing(
    student, tap_for
) -> None:
    wallet = open_wallet(student, _INTAKE)
    tap = tap_for(wallet, allowance=Decimal("0.01"))
    charge(tap, kind="SEARCH", provider="brave", usd=Decimal("0.005"))
    with pytest.raises(WalletExhausted) as refused:
        preflight(tap, "exa")  # worst case $0.012 would cross $0.01
    assert refused.value.ending == SearchTap.Ending.TAP_SHARE_SPENT
    assert WalletCharge.objects.filter(tap=tap).count() == 1


def test_an_unbilled_charge_past_the_allowance_is_refused_and_not_recorded(
    student, tap_for
) -> None:
    wallet = open_wallet(student, _INTAKE)
    tap = tap_for(wallet, allowance=Decimal("0.01"))
    charge(tap, kind="SEARCH", provider="exa", usd=Decimal("0.008"))
    with pytest.raises(WalletExhausted):
        charge(tap, kind="SEARCH", provider="exa", usd=Decimal("0.008"), already_billed=False)
    assert WalletCharge.objects.filter(tap=tap).count() == 1
    wallet.refresh_from_db()
    assert wallet.spent_usd == Decimal("0.008")


def test_a_billed_charge_past_the_allowance_is_recorded_and_then_raises(
    student, tap_for
) -> None:
    # The call already happened: the money is spent, so it is written down
    # before anyone is told the allowance is gone.
    wallet = open_wallet(student, _INTAKE)
    tap = tap_for(wallet, allowance=Decimal("0.01"))
    charge(tap, kind="SEARCH", provider="exa", usd=Decimal("0.008"))
    with pytest.raises(WalletExhausted) as over:
        charge(tap, kind="SEARCH", provider="exa", usd=Decimal("0.008"))
    assert over.value.ending == SearchTap.Ending.TAP_SHARE_SPENT
    assert WalletCharge.objects.filter(tap=tap).count() == 2
    assert tap_spent(tap) == Decimal("0.016")
    wallet.refresh_from_db()
    assert wallet.spent_usd == Decimal("0.016")


def test_a_billed_charge_past_the_wallet_caps_the_column_and_logs_the_overshoot(
    student, tap_for, caplog
) -> None:
    wallet = open_wallet(student, _INTAKE)
    SearchWallet.objects.filter(id=wallet.id).update(spent_usd=Decimal("49.99"))
    tap = tap_for(wallet, allowance=Decimal("5"))
    with caplog.at_level(logging.WARNING), pytest.raises(WalletExhausted) as over:
        charge(tap, kind="READ", provider="reader", usd=Decimal("0.35"))
    assert over.value.ending == SearchTap.Ending.WALLET_SPENT
    wallet.refresh_from_db()
    assert wallet.spent_usd == wallet.budget_usd  # capped, never beyond
    assert WalletCharge.objects.get(tap=tap).usd == Decimal("0.35")  # the real figure
    assert "overshoot" in caplog.text


@pytest.mark.django_db(transaction=True)
def test_a_charge_commits_even_when_the_caller_fails_afterwards(agency_a, membership_a) -> None:
    # transaction=True: under the default wrapping transaction a rolled-back
    # charge and a committed one look the same, and this would prove nothing
    # (CLAUDE.md's erasure-atomicity trap). The caller is not inside an atomic
    # block, as run_tap is not: charge's own short transaction is the boundary.
    from django.db import connection

    from tests.funding.conftest import make_run

    run = make_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        wallet = open_wallet(membership_a, _INTAKE)
        tap = SearchTap.objects.create(
            student=membership_a, wallet=wallet, run_id=run.id, allowance_usd=Decimal("5")
        )

        def the_tap() -> None:
            charge(tap, kind="SEARCH", provider="brave", usd=Decimal("0.005"))
            raise RuntimeError("the tap died after paying")

        with pytest.raises(RuntimeError):
            the_tap()
        assert not connection.in_atomic_block
        wallet.refresh_from_db()
        assert wallet.spent_usd == Decimal("0.005")
        assert WalletCharge.objects.filter(tap=tap).count() == 1


def test_the_page_backstop_is_derived_and_sits_above_the_money(settings) -> None:
    settings.CHEAPEST_PAGE_READ_USD = Decimal("0.167")
    assert page_backstop(Decimal("50")) == 300
    settings.CHEAPEST_PAGE_READ_USD = Decimal("0.35")
    assert page_backstop(Decimal("50")) == 143


def test_a_third_tap_in_a_day_is_refused(student, tap_for) -> None:
    wallet = open_wallet(student, _INTAKE)
    tap_for(wallet)
    check_tap_permitted(student, wallet, now=timezone.now())  # one so far: fine
    tap_for(wallet)
    with pytest.raises(TapRefused, match="per day"):
        check_tap_permitted(student, wallet, now=timezone.now())


def test_a_tap_from_yesterday_does_not_count(student, tap_for) -> None:
    wallet = open_wallet(student, _INTAKE)
    tap_for(wallet)
    tap_for(wallet)
    SearchTap.objects.update(requested_at=timezone.now() - timedelta(days=1, minutes=1))
    check_tap_permitted(student, wallet, now=timezone.now())


def test_a_spent_wallet_refuses_a_tap(student) -> None:
    wallet = open_wallet(student, _INTAKE)
    SearchWallet.objects.filter(id=wallet.id).update(spent_usd=wallet.budget_usd)
    wallet.refresh_from_db()
    with pytest.raises(TapRefused, match="budget"):
        check_tap_permitted(student, wallet, now=timezone.now())


def test_the_tenant_ceiling_counts_every_student_in_the_tenant(
    student, tap_for, settings, agency_a
) -> None:
    from django.contrib.auth import get_user_model

    other = Membership.objects.create(
        tenant=agency_a,
        user=get_user_model().objects.create_user(username="student-a2"),
        role=Membership.Role.STUDENT,
    )
    settings.SEARCH_TENANT_DAILY_CEILING_USD = Decimal("0.01")
    theirs = tap_for(open_wallet(other, _INTAKE))
    charge(theirs, kind="SEARCH", provider="brave", usd=Decimal("0.005"))
    mine = tap_for(open_wallet(student, _INTAKE))
    assert tenant_spend_today(now=timezone.now()) == Decimal("0.005")
    with pytest.raises(WalletExhausted) as refused:
        preflight(mine, "brave")
        preflight(mine, "exa")
    assert refused.value.ending == SearchTap.Ending.TENANT_CEILING


def test_an_unknown_provider_is_preflighted_at_a_conservative_price(student, tap_for) -> None:
    tap = tap_for(open_wallet(student, _INTAKE), allowance=Decimal("0.05"))
    with pytest.raises(WalletExhausted):
        preflight(tap, "some-new-vendor")
