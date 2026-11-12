"""The cycle wallet (spec 10.5, decision 28). Money, so every rule is durable.

- One wallet per (student, intended_intake); SEARCH_WALLETS_PER_YEAR caps how
  many an edited intake can mint.
- A tap's allowance is TAP_WALLET_SHARE of what remains, fixed when the tap starts.
- Every charge commits in its OWN short transaction with the wallet row locked:
  a charge that rolled back with a failed tap would be money spent and
  unrecorded. So `charge` must never be called inside a caller's atomic block
  -- run_tap is deliberately outside one.
- `preflight` checks a call's WORST-CASE price against the tap allowance, the
  wallet and the tenant's runaway ceiling BEFORE the call is made, and refuses
  without writing anything.
- `charge` records what a call ACTUALLY billed. By default the call has already
  happened (`already_billed=True`), so even a charge that crosses a ceiling --
  the real price beat the preflight -- is written down first: the row carries
  the provider's own figure, `spent_usd` grows (capped at the budget, the
  overshoot logged at WARNING), the transaction commits, and only then
  WalletExhausted is raised. With `already_billed=False` a charge over a
  ceiling refuses and records nothing, like preflight.

Every function runs inside the caller's `tenant_scope`; each database touch is
its own `tenant_transaction`, so the RLS GUC is set wherever a row is read.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

from .models import PlatformAgency, SearchTap, SearchWallet, WalletCharge

logger = logging.getLogger(__name__)

_WALLET_PLACES = Decimal("0.0001")  # SearchWallet's 4 decimal places
_CHARGE_PLACES = Decimal("0.00001")  # WalletCharge's 5 decimal places
#: A provider with no PROVIDER_CALL_PREFLIGHT_USD row is priced high, never at
#: zero: an unpriced call must not slip past every ceiling.
_UNKNOWN_PROVIDER_USD = Decimal("0.1")


class WalletExhausted(Exception):
    """A ceiling was reached; `ending` is the SearchTap.Ending that names it."""

    def __init__(self, ending: str) -> None:
        super().__init__(ending)
        self.ending = ending


class TapRefused(Exception):
    """A tap may not start. The message is shown to the student."""


def open_wallet(student: Membership, intake: date) -> SearchWallet:
    """The student's wallet for `intake`, opened on first use.

    A third distinct intake inside 365 days reuses the newest wallet rather
    than minting money (plan decision 4). Direct retail B2C students on
    `PlatformAgency` use `STUDENT_B2C_SEARCH_WALLET_USD` ($35) and
    `STUDENT_B2C_SEARCH_WALLETS_PER_YEAR` (1) so a 299 AZN / 499 AZN cycle pass
    stays unit-economics positive even under cold sweeps. The membership row is
    locked so two concurrent opens cannot both pass the count.
    """
    with tenant_transaction(student.tenant_id):
        Membership.objects.select_for_update().get(id=student.id)
        existing = SearchWallet.objects.filter(student=student, intended_intake=intake).first()
        if existing is not None:
            return existing
        is_direct_b2c = PlatformAgency.objects.filter(agency_id=student.tenant_id).exists()
        max_wallets = (
            settings.STUDENT_B2C_SEARCH_WALLETS_PER_YEAR
            if is_direct_b2c
            else settings.SEARCH_WALLETS_PER_YEAR
        )
        budget_usd = (
            settings.STUDENT_B2C_SEARCH_WALLET_USD
            if is_direct_b2c
            else settings.SEARCH_WALLET_USD
        )
        recent = SearchWallet.objects.filter(
            student=student, created_at__gte=timezone.now() - timedelta(days=365)
        ).order_by("-created_at")
        newest = recent.first()
        if newest is not None and recent.count() >= max_wallets:
            return newest
        return SearchWallet.objects.create(
            student=student, intended_intake=intake, budget_usd=budget_usd
        )


def remaining(wallet: SearchWallet) -> Decimal:
    return max(Decimal("0"), wallet.budget_usd - wallet.spent_usd)


def tap_allowance(wallet: SearchWallet) -> Decimal:
    """What one tap may spend: a share of what remains, rounded DOWN."""
    return (remaining(wallet) * settings.TAP_WALLET_SHARE).quantize(
        _WALLET_PLACES, rounding=ROUND_DOWN
    )


def page_backstop(remaining_usd: Decimal) -> int:
    """Runaway page cap, ABOVE what the money buys, so it never becomes the ceiling."""
    return math.ceil(remaining_usd / settings.CHEAPEST_PAGE_READ_USD)


def taps_in_last_day(student: Membership, *, now: datetime) -> int:
    with tenant_transaction(student.tenant_id):
        return SearchTap.objects.filter(
            student=student, requested_at__gte=now - timedelta(days=1)
        ).count()


def tenant_spend_today(*, now: datetime) -> Decimal:
    """The ambient tenant's billed spend since midnight UTC."""
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = WalletCharge.objects.filter(created_at__gte=start).aggregate(total=Sum("usd"))[
        "total"
    ]
    return total or Decimal("0")


def check_tap_permitted(student: Membership, wallet: SearchWallet, *, now: datetime) -> None:
    if taps_in_last_day(student, now=now) >= settings.TAP_PER_DAY:
        raise TapRefused(f"at most {settings.TAP_PER_DAY} searches per day")
    if remaining(wallet) <= 0:
        raise TapRefused("this cycle's search budget is spent")


def tap_spent(tap: SearchTap) -> Decimal:
    total = WalletCharge.objects.filter(tap=tap).aggregate(total=Sum("usd"))["total"]
    return total or Decimal("0")


def _reserve(tap: SearchTap) -> Decimal:
    """What this tap may never spend of the wallet: a FIRST search leaves the
    follow-up reserve. Checked live against the wallet, not only through the
    allowance fixed at request time -- a follow-up that spends between a first
    search's request and its run would otherwise let it eat the reserve."""
    if tap.kind == SearchTap.Kind.FIRST:
        return Decimal(settings.SEARCH_FOLLOWUP_RESERVE_USD)
    return Decimal("0")


def spendable(tap: SearchTap, wallet: SearchWallet) -> Decimal:
    """What this tap may still spend: its allowance left, the wallet left, the reserve kept."""
    return max(
        Decimal("0"),
        min(tap.allowance_usd - tap_spent(tap), remaining(wallet) - _reserve(tap)),
    )


def _crossed(tap: SearchTap, wallet: SearchWallet, usd: Decimal) -> str | None:
    """The first ceiling `usd` more would cross, as a SearchTap.Ending, or None."""
    if tap_spent(tap) + usd > tap.allowance_usd:
        return SearchTap.Ending.TAP_SHARE_SPENT
    if wallet.spent_usd + usd > wallet.budget_usd - _reserve(tap):
        return SearchTap.Ending.WALLET_SPENT
    if tenant_spend_today(now=timezone.now()) + usd > settings.SEARCH_TENANT_DAILY_CEILING_USD:
        return SearchTap.Ending.TENANT_CEILING
    return None


def preflight(
    tap: SearchTap, provider: str, *, worst: Decimal | None = None,
    in_flight: Decimal = Decimal("0"),
) -> Decimal:
    """Refuse a call whose worst-case price would cross any ceiling. Writes nothing.
    Returns the worst-case price it checked.

    `worst` overrides the provider's table price for a call the table does not
    describe (the first search's 100-result Exa call is ~8x the 15-result one).
    `in_flight` is the worst-case price of calls already made and not yet
    charged (the tap's parallel calls): it counts as spent.
    """
    if worst is None:
        worst = settings.PROVIDER_CALL_PREFLIGHT_USD.get(provider, _UNKNOWN_PROVIDER_USD)
    with tenant_transaction(tap.tenant_id):
        wallet = SearchWallet.objects.get(id=tap.wallet_id)
        ending = _crossed(tap, wallet, worst + in_flight)
    if ending is not None:
        raise WalletExhausted(ending)
    return worst


def charge(
    tap: SearchTap, *, kind: str, provider: str, usd: Decimal, already_billed: bool = True
) -> None:
    """Record what a call billed. Own transaction; wallet row locked.

    Rounded UP to the ledger's precision: a ledger that under-records by a
    rounding step on every call drifts below what the providers invoice.
    """
    usd = usd.quantize(_CHARGE_PLACES, rounding=ROUND_UP)
    with tenant_transaction(tap.tenant_id):
        wallet = SearchWallet.objects.select_for_update().get(id=tap.wallet_id)
        ending = _crossed(tap, wallet, usd)
        if ending is not None and not already_billed:
            raise WalletExhausted(ending)
        WalletCharge.objects.create(
            wallet=wallet, tap=tap, kind=kind, provider=provider, usd=usd
        )
        spent = wallet.spent_usd + usd.quantize(_WALLET_PLACES, rounding=ROUND_UP)
        if spent > wallet.budget_usd:
            logger.warning(
                "wallet %s overshoot: tap %s billed %s %s past the %s budget; "
                "the column is capped, the charge row carries the real figure",
                wallet.id, tap.id, spent - wallet.budget_usd, provider, wallet.budget_usd,
            )
            spent = wallet.budget_usd
        wallet.spent_usd = spent
        wallet.save(update_fields=["spent_usd"])
    # Raised only after the block above committed: the money is recorded.
    if ending is not None:
        raise WalletExhausted(ending)
