"""The pairing row: one installation, one membership, nothing recoverable.

The row carries two hashes and no secret. A database dump gives an attacker a
list of SHA-256 digests, not a working device token.
"""

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_a_pairing_belongs_to_one_membership_and_stores_no_secret(agency_a, membership_a) -> None:
    from apps.portals.models import ExtensionPairing

    with tenant_scope(agency_a.id):
        pairing = ExtensionPairing.objects.create(
            tenant=agency_a, membership=membership_a, code_hash="a" * 64
        )

    assert pairing.membership_id == membership_a.id
    assert pairing.token_hash == ""
    assert pairing.installation_id == ""
    assert pairing.redeemed_at is None
    assert pairing.revoked_at is None
    # No column can hold the code or the token itself.
    columns = {field.name for field in ExtensionPairing._meta.get_fields()}
    assert "code" not in columns
    assert "token" not in columns


def test_every_new_column_is_classified_for_erasure() -> None:
    """The plan's own constraint, asserted here rather than discovered as 23
    errors in files that pass on their own."""
    from apps.audit.redaction import KEEP, REDACT

    keep = set(KEEP["portals.ExtensionPairing"])
    redact = set(REDACT["portals.ExtensionPairing"].fields)
    assert keep | redact == {
        "code_hash",
        "code_expires_at",
        "token_hash",
        "installation_id",
        "created_at",
        "redeemed_at",
        "last_seen_at",
        "revoked_at",
    }


def test_a_code_is_redeemed_once(agency_a, membership_a) -> None:
    from apps.portals import pairing as pairing_module

    with tenant_scope(agency_a.id):
        code = pairing_module.issue_pairing_code(membership_a)
        pairing, token = pairing_module.redeem_pairing_code(code, "install-1")

        assert pairing.membership_id == membership_a.id
        assert token  # returned exactly once, never stored
        with pytest.raises(pairing_module.PairingRefused) as refused:
            pairing_module.redeem_pairing_code(code, "install-2")
    assert refused.value.reason == "invalid_code"


def test_an_expired_code_is_refused(agency_a, membership_a, monkeypatch) -> None:
    from datetime import timedelta

    from django.utils import timezone

    from apps.portals import pairing as pairing_module

    with tenant_scope(agency_a.id):
        code = pairing_module.issue_pairing_code(membership_a)
        monkeypatch.setattr(
            pairing_module,
            "_now",
            lambda: timezone.now() + pairing_module.PAIRING_CODE_TTL + timedelta(seconds=1),
        )
        with pytest.raises(pairing_module.PairingRefused) as refused:
            pairing_module.redeem_pairing_code(code, "install-1")
    assert refused.value.reason == "invalid_code"


def test_the_token_authenticates_until_it_is_revoked(agency_a, membership_a) -> None:
    from apps.portals import pairing as pairing_module

    with tenant_scope(agency_a.id):
        code = pairing_module.issue_pairing_code(membership_a)
        pairing, token = pairing_module.redeem_pairing_code(code, "install-1")

        assert pairing_module.authenticate_device(token) is not None
        pairing_module.revoke_pairing(pairing)
        assert pairing_module.authenticate_device(token) is None


def test_a_wrong_token_authenticates_nothing(agency_a, membership_a) -> None:
    from apps.portals import pairing as pairing_module

    with tenant_scope(agency_a.id):
        pairing_module.issue_pairing_code(membership_a)
        assert pairing_module.authenticate_device("not-a-token") is None
        assert pairing_module.authenticate_device("") is None


def test_issuing_a_second_code_leaves_the_first_pairing_unusable(agency_a, membership_a) -> None:
    """A student who reloads the dashboard twice before the extension answers
    must not accumulate redeemable codes."""
    from apps.portals import pairing as pairing_module

    with tenant_scope(agency_a.id):
        first = pairing_module.issue_pairing_code(membership_a)
        second = pairing_module.issue_pairing_code(membership_a)
        with pytest.raises(pairing_module.PairingRefused):
            pairing_module.redeem_pairing_code(first, "install-1")
        pairing, _token = pairing_module.redeem_pairing_code(second, "install-1")
    assert pairing.installation_id == "install-1"
