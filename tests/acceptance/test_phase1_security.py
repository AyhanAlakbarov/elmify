"""Phase 1 security-gate regression checks (Task 18, Step 1).

These re-run already-proven behavior directly against the fixtures used
throughout Tasks 1-16, as a regression check -- they do not re-derive new
security guarantees.
"""

import pytest

from apps.research.egress import UnsafeTarget, validate_public_url
from apps.tenancy.context import tenant_scope


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://user:password@example.org/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
    ],
)
def test_controlled_egress_rejects_private_and_credentialed_targets(url: str) -> None:
    with pytest.raises(UnsafeTarget):
        validate_public_url(url)


@pytest.mark.django_db
def test_unknown_host_is_rejected_before_any_data_access(client) -> None:
    response = client.get("/", HTTP_HOST="unknown.example.test")
    assert response.status_code == 400


@pytest.mark.django_db
def test_unverified_domain_is_rejected_before_any_data_access(client, unverified_domain) -> None:
    response = client.get("/", HTTP_HOST=unverified_domain.host)
    assert response.status_code == 400


@pytest.mark.django_db
def test_cross_tenant_audit_export_is_denied(agency_a, agency_b, membership_a) -> None:
    from apps.audit.exports import build_export

    with pytest.raises(ValueError):
        build_export(agency_b.id, membership_a.id)


@pytest.mark.django_db
def test_cross_tenant_host_membership_mismatch_is_forbidden(
    client, domain_b, user_a, membership_a
) -> None:
    client.force_login(user_a)
    response = client.get("/", HTTP_HOST=domain_b.host)
    assert response.status_code == 403


@pytest.mark.django_db
def test_cross_tenant_pack_reject_is_isolated(
    agency_a, agency_b, membership_a, membership_b
) -> None:
    from apps.funding.models import PackVersion
    from apps.funding.services import reject_candidate
    from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    pack = make_published_pack(agency_a, run, (candidate,))

    with tenant_scope(agency_b.id):
        with pytest.raises(PackVersion.DoesNotExist):
            reject_candidate(pack, candidate.id, membership_b)


def test_no_cross_tenant_failures_in_this_run(scorecard) -> None:
    assert scorecard.cross_tenant_failures == 0


@pytest.mark.django_db
def test_mandatory_mfa_for_staff_roles_is_enforced(
    client, domain_a, counselor_user, counselor_membership
):
    """P1-mfa gate, closed.

    `phased requirements.md` Section 3.4 and the Task 15 brief's
    `require_staff_mfa()` sketch require mandatory MFA for platform admins,
    agency owners, and counselors. `apps.tenancy.middleware.require_staff_mfa`,
    enforced by `TenantMembershipMiddleware` on every tenant-hosted request,
    now closes this gap -- see tests/tenancy/test_mfa.py for the full
    per-role matrix and docs/validation/phase1-scorecard.md /
    docs/runbooks/shadow-pilot.md for the updated gate status.
    """
    import apps.tenancy.middleware as middleware_module
    from tests.conftest import verify_mfa_session

    assert hasattr(middleware_module, "require_staff_mfa")

    client.force_login(counselor_user)
    denied = client.get("/counselor/", HTTP_HOST=domain_a.host)
    assert denied.status_code == 403

    verify_mfa_session(client, counselor_user)
    allowed = client.get("/counselor/", HTTP_HOST=domain_a.host)
    assert allowed.status_code == 200
