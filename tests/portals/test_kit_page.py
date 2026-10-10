from uuid import uuid4

import pytest

from apps.audit.models import DeletionRequest
from apps.portals.models import Application, FieldMap, PortalForm
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _application(agency, student, **fields):
    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"k-{uuid4()}",
        form_url="https://apply.example.edu/personal",
    )
    FieldMap.objects.create(
        portal_form=form, version=1,
        entries=[{"profile_field": "identity.full_name", "action": {
            "selector": "#name", "description": "Full name",
            "method": "fill", "arguments": ["%value%"]}}],
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form, **fields
    )


def test_the_kit_marks_missing_answers_and_offers_start(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a, membership_a, kit_requirements=["A CV in English."]
        )
    client.force_login(user_a)
    url = f"/applications/{application.id}/kit"
    body = client.get(url, HTTP_HOST=domain_a.host).content.decode()
    assert "Full name" in body
    assert "missing" in body
    assert "A CV in English." in body
    assert f'action="/student/applications/{application.id}/start/"' in body


def test_a_kit_action_with_an_http_url_is_text_not_a_link(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    actions = [
        {"text": "Sign the declaration by hand.", "source_url": "http://evil.example/x",
         "requirement": "REQUIRED", "status": "YOUR_ACTION", "statement_id": ""},
        {"text": "Upload the signed form.", "source_url": "https://apply.example.edu/rules",
         "requirement": "REQUIRED", "status": "YOUR_ACTION", "statement_id": ""},
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, kit_your_actions=actions)
    client.force_login(user_a)
    url = f"/applications/{application.id}/kit"
    body = client.get(url, HTTP_HOST=domain_a.host).content.decode()
    assert "Sign the declaration by hand." in body
    assert 'href="http://evil.example/x"' not in body
    assert 'href="https://apply.example.edu/rules"' in body


def test_a_portal_less_kit_says_why_and_offers_no_start(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4()
        )
    client.force_login(user_a)
    url = f"/applications/{application.id}/kit"
    body = client.get(url, HTTP_HOST=domain_a.host).content.decode()
    assert "application portal is not known yet" in body
    assert "/start/" not in body


def test_the_kit_is_behind_the_deletion_lock(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED", reason="OTHER"
        )
    client.force_login(user_a)
    url = f"/applications/{application.id}/kit"
    response = client.get(url, HTTP_HOST=domain_a.host)
    assert response["Location"] == "/student/account/deletion/"
