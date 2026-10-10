"""The pairing handshake: a one-time code becomes a device token.

Nothing recoverable is stored. Both secrets are 32 random bytes rendered
url-safe and kept only as SHA-256 hex, so the row is a verifier and not a
credential -- the token is returned to the caller exactly once, at redemption,
and there is no second way to read it.

SHA-256 without a work factor is deliberate and is the right choice here. A
password is a low-entropy human secret and needs stretching; these are 256-bit
random values, so a brute force over the digest is not a shorter path than a
brute force over the token itself. A slow KDF would only make the per-request
lookup slow: this hash is computed on every single extension call.

Why a conditional UPDATE rather than read-then-write: two dashboard loads, or a
retried request, would otherwise both see a pending row and both redeem it.
``.filter(...).update(...)`` returns the number of rows the database actually
changed, which is 1 for exactly one caller.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from django.db.models import QuerySet
from django.utils import timezone

from apps.tenancy.models import Membership

from .models import ExtensionPairing

#: Two minutes. The dashboard page mints a code and the extension redeems it in
#: the same page load; anything longer is a bearer credential sitting in a
#: browser for no reason.
PAIRING_CODE_TTL = timedelta(minutes=2)


class PairingRefused(Exception):
    """No pairing, with a stable machine-readable reason for the HTTP layer."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _now() -> datetime:
    """Indirected so a test can move the clock without freezing the world."""
    return timezone.now()


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_pairing_code(membership: Membership) -> str:
    """Mint a code for this session, invalidating any code still pending.

    Invalidating is not tidiness: two live codes for one membership is two
    chances for a code that leaked into a log or a tab's history to be redeemed
    by something that is not the student's extension.
    """
    ExtensionPairing.objects.filter(
        membership=membership, redeemed_at__isnull=True, revoked_at__isnull=True
    ).update(revoked_at=_now(), code_hash="")
    code = secrets.token_urlsafe(32)
    ExtensionPairing.objects.create(
        tenant_id=membership.tenant_id,
        membership=membership,
        code_hash=_digest(code),
        code_expires_at=_now() + PAIRING_CODE_TTL,
    )
    return code


def redeem_pairing_code(raw_code: str, installation_id: str) -> tuple[ExtensionPairing, str]:
    """Exchange a live code for a device token. Once."""
    if not raw_code:
        raise PairingRefused("invalid_code")
    token = secrets.token_urlsafe(32)
    now = _now()
    updated = ExtensionPairing.objects.filter(
        code_hash=_digest(raw_code),
        redeemed_at__isnull=True,
        revoked_at__isnull=True,
        code_expires_at__gt=now,
    ).update(
        code_hash="",
        token_hash=_digest(token),
        installation_id=installation_id[:100],
        redeemed_at=now,
        last_seen_at=now,
    )
    if updated != 1:
        raise PairingRefused("invalid_code")
    pairing = ExtensionPairing.objects.get(token_hash=_digest(token))
    return pairing, token


def authenticate_device(raw_token: str) -> ExtensionPairing | None:
    """The pairing this token belongs to, or None. Never raises.

    ``select_related("membership")`` because every caller immediately needs the
    membership, and a lazy forward-FK traversal after the transaction closes is
    the exact mistake CLAUDE.md's row-level-security section records twice.
    """
    if not raw_token:
        return None
    # membership__active is not decoration. advance_deletion sets active=False
    # as THE mechanism that cuts an erased student off ("leaving this True lets
    # an erased person keep reaching the agency that erased them"), and the
    # session path enforces it in two places -- current_membership and
    # TenantMembershipMiddleware -- both of which sit inside
    # `if request.user.is_authenticated` and so never run for a device token.
    # Without this line the flag is simply not load-bearing on this surface.
    return (
        ExtensionPairing.objects.select_related("membership")
        .filter(
            token_hash=_digest(raw_token),
            revoked_at__isnull=True,
            membership__active=True,
        )
        .first()
    )


def active_pairings(membership: Membership) -> QuerySet[ExtensionPairing]:
    """The installations this student has paired and not revoked."""
    return ExtensionPairing.objects.filter(
        membership=membership, redeemed_at__isnull=False, revoked_at__isnull=True
    )


def revoke_pairing(pairing: ExtensionPairing) -> None:
    """Revoke, and clear the verifier rather than only marking the row.

    revoked_at alone would leave a live digest in the table for a token the
    student has withdrawn, and authenticate_device's filter would be the only
    thing standing between it and a working credential.
    """
    pairing.revoked_at = _now()
    # nosec B105 -- emptying a stored digest, not setting a password. The field
    # never holds a secret in the first place; it holds SHA-256 hex of one.
    pairing.token_hash = ""  # nosec B105
    pairing.save(update_fields=["revoked_at", "token_hash"])


def touch(pairing: ExtensionPairing) -> None:
    """Record that this installation was seen, so the dashboard can say
    'extension not seen since Tuesday' (owner decision 2)."""
    ExtensionPairing.objects.filter(pk=pairing.pk).update(last_seen_at=_now())


def revoke_all_for(membership: Membership) -> int:
    """Revoke every installation paired to this student. Returns how many.

    Called when a deletion request is created, not when it is executed. The
    student is locked out of the dashboard the moment they ask; until this
    existed, their device token kept minting fill packets -- their full
    verified facts in plaintext -- for the whole thirty-day statutory window,
    and DELETE /ext/pair authenticates with the very token you would be trying
    to revoke, so a device you no longer hold could not be revoked at all.
    """
    return ExtensionPairing.objects.filter(membership=membership, revoked_at__isnull=True).update(
        revoked_at=_now(),
        # nosec B106 -- emptying stored digests, not setting a password. These
        # fields never hold a secret; they hold SHA-256 hex of one, and leaving
        # a live digest behind for a revoked token is the bug this call fixes.
        token_hash="",  # nosec B106
        code_hash="",  # nosec B106
    )
