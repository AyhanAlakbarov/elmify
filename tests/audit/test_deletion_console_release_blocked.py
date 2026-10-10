"""Release without an approved retention policy is refused on the console, not a 500."""

import pytest
from django.contrib.auth import get_user_model

from apps.audit.models import DeletionRequest
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import verify_mfa_session


@pytest.mark.django_db
def test_release_without_a_retention_policy_says_why(client, agency_a, domain_a, membership_a):
    owner_user = get_user_model().objects.create_user(username="owner-a")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=owner_user, role=Membership.Role.OWNER)
        held = DeletionRequest.objects.create(
            student=membership_a,
            state="RETENTION_REVIEW",
            review_reason=DeletionRequest.ReviewReason.NO_RETENTION_POLICY,
            reason=DeletionRequest.Reason.PRIVACY,
        )
    client.force_login(owner_user)
    verify_mfa_session(client, owner_user)
    response = client.post(
        f"/owner/deletions/{held.id}/release/", HTTP_HOST=domain_a.host, follow=True
    )
    assert response.status_code == 200
    assert "no approved data-retention policy" in response.content.decode()
    held.refresh_from_db()
    assert held.state == "RETENTION_REVIEW"
