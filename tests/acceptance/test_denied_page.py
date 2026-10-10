"""Denied (403/400) responses render a real page, not a bare text body.

`base.html`'s htmx-config makes 400/403 swap (tests/acceptance/test_htmx_config.py),
so under hx-boost a bare-text body replaces the page with the raw string. The
form endpoints re-render their own page with an inline error; the entry
points below have no page context to re-render -- middleware runs before any
view, and the two views fail before loading the data their template needs --
so they raise Django's PermissionDenied/SuspiciousOperation and share
templates/403.html or templates/400.html.

Django's permission_denied view passes {"exception": str(exception)} to
403.html, so those assertions check the raise-site message verbatim. Its
bad_request view passes NO context to 400.html ("to not disclose any
sensitive information"), so 400.html carries static authored copy instead --
that test checks the authored string, not an internal message.
"""

import pytest

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import verify_mfa_session


def assert_denied_page(response, message: str, *, status: int = 403) -> None:
    body = response.content.decode()
    assert response.status_code == status
    # A real page, not a bare string: base.html's skip link is the cheapest
    # proof the template chain rendered.
    assert "Skip to content" in body
    assert 'role="alert"' in body
    assert message in body


@pytest.mark.frontend
@pytest.mark.django_db
def test_membership_gate_renders_denied_page(client, domain_b, user_a, membership_a) -> None:
    """TenantMembershipMiddleware: no active membership for the resolved host."""
    client.force_login(user_a)
    assert_denied_page(
        client.get("/", HTTP_HOST=domain_b.host), "tenant membership required"
    )


@pytest.mark.frontend
@pytest.mark.django_db
def test_staff_mfa_gate_renders_denied_page(
    client, domain_a, counselor_user, counselor_membership
) -> None:
    """TenantMembershipMiddleware: staff session without a verified device."""
    client.force_login(counselor_user)
    assert_denied_page(
        client.get("/counselor/", HTTP_HOST=domain_a.host),
        "multi-factor verification required",
    )


@pytest.mark.frontend
@pytest.mark.django_db
def test_profile_without_student_membership_renders_denied_page(
    client, domain_a, counselor_user, counselor_membership
) -> None:
    """accounts.views.profile: authenticated, but not as a student.

    Verified via MFA first so the middleware gate above passes and the view's
    own membership check is what denies.
    """
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    assert_denied_page(
        client.get("/student/profile/", HTTP_HOST=domain_a.host), "tenant membership required"
    )


@pytest.mark.frontend
@pytest.mark.django_db
def test_support_grant_gate_renders_denied_page(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    """concierge.views.admin_support_grant: no active grant.

    The page needs an active grant to render at all, so the denial cannot
    re-render it -- this is why it shares the standalone denied page.
    """
    with tenant_scope(agency_a.id):
        membership_a.role = Membership.Role.PLATFORM_ADMIN
        membership_a.save(update_fields=["role"])
    client.force_login(user_a)
    verify_mfa_session(client, user_a)
    assert_denied_page(
        client.get("/admin/support-grant/", HTTP_HOST=domain_a.host),
        "an active support grant is required",
    )


@pytest.mark.frontend
@pytest.mark.django_db
def test_unknown_host_renders_denied_page(client) -> None:
    """HostTenantContextMiddleware: no verified domain for this host.

    Runs before tenant_scope() even opens -- there is no tenant yet.
    """
    response = client.get("/", HTTP_HOST="unknown.example.test")
    assert_denied_page(
        response,
        "This address isn't recognized. Check the link, or contact your counselor "
        "if you were sent here.",
        status=400,
    )
