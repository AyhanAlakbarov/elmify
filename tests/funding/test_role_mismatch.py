"""A wrong-role membership must get a clean 403, never an unhandled 500."""

import pytest
from django.test import Client

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import verify_mfa_session


@pytest.mark.django_db(transaction=True)
def test_counselor_on_student_view_is_forbidden(agency_a, domain_a, django_user_model) -> None:
    user = django_user_model.objects.create_user(username="c1", password="pw")  # nosec B106
    with tenant_scope(agency_a.id):
        Membership.objects.create(
            tenant_id=agency_a.id, user=user, role=Membership.Role.COUNSELOR, active=True
        )
    client = Client(SERVER_NAME="a.example.test")
    client.force_login(user)
    verify_mfa_session(client, user)

    assert client.get("/student/recommendation/").status_code == 403


@pytest.mark.django_db(transaction=True)
def test_student_on_counselor_review_is_forbidden(agency_a, domain_a, django_user_model) -> None:
    from uuid import uuid4

    user = django_user_model.objects.create_user(username="s1", password="pw")  # nosec B106
    with tenant_scope(agency_a.id):
        Membership.objects.create(
            tenant_id=agency_a.id, user=user, role=Membership.Role.STUDENT, active=True
        )
    client = Client(SERVER_NAME="a.example.test")
    client.force_login(user)

    assert client.get(f"/counselor/runs/{uuid4()}/approve/").status_code == 403
