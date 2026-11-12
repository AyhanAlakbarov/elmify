"""The kit page: the assigned counsellor's read-only view of the answers we'll submit.

A student is shown no such page (owner, 2026-10-10). Asserts server behaviour
only -- authorization, tenant isolation and that the page offers no action.
"""

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import CounselorAssignment
from tests.conftest import verify_mfa_session

pytestmark = pytest.mark.django_db


def _application(agency, student, **fields):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"view-{uuid4()}",
        form_url="https://apply.example.edu/personal",
    )
    FieldMap.objects.create(
        portal_form=form,
        version=1,
        entries=[
            {
                "profile_field": "identity.full_name",
                "action": {
                    "selector": "#name",
                    "description": "Full name",
                    "method": "fill",
                    "arguments": ["%value%"],
                },
            }
        ],
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form, **fields
    )


def _url(student, application) -> str:
    return f"/counselor/students/{student.id}/applications/{application.id}/answers/"


@pytest.fixture
def counselor_client(client, agency_a, counselor_user, counselor_membership, membership_a):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    return client


def test_a_student_gets_404_on_the_old_kit_url(client, agency_a, domain_a, membership_a, user_a):
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    client.force_login(user_a)
    response = client.get(f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_the_assigned_counselor_sees_the_answers_and_no_action(
    counselor_client, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a, membership_a, kit_requirements=["A CV in English."]
        )
    response = counselor_client.get(_url(membership_a, application), HTTP_HOST=domain_a.host)
    body = response.content.decode()

    assert response.status_code == 200
    assert response.context["kit"].application_id == application.id
    assert [q.label for q in response.context["kit"].questions] == ["Full name"]
    assert "Answers we'll submit" in body.replace("&#x27;", "'").replace("&#39;", "'")
    assert "Full name" in body and "missing" in body
    assert "A CV in English." in body
    # Read-only: nothing to press, no portal link, no by-hand wording.
    assert "Start application" not in body and "/start/" not in body
    assert "Open the portal" not in body and "https://apply.example.edu/personal" not in body
    assert "by hand" not in body and "copy each answer" not in body


def test_an_action_with_an_http_url_is_text_not_a_link(
    counselor_client, agency_a, domain_a, membership_a
) -> None:
    actions = [
        {"text": "Sign the declaration.", "source_url": "http://evil.example/x",
         "requirement": "REQUIRED", "status": "YOUR_ACTION", "statement_id": ""},
        {"text": "Upload the signed form.", "source_url": "https://apply.example.edu/rules",
         "requirement": "REQUIRED", "status": "YOUR_ACTION", "statement_id": ""},
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, kit_your_actions=actions)
    body = counselor_client.get(
        _url(membership_a, application), HTTP_HOST=domain_a.host
    ).content.decode()
    assert "Sign the declaration." in body
    assert 'href="http://evil.example/x"' not in body
    assert 'href="https://apply.example.edu/rules"' in body


def test_a_portal_less_application_says_plainly_why_it_cannot_be_filled(
    counselor_client, agency_a, domain_a, membership_a
) -> None:
    from apps.portals.models import Application

    with tenant_scope(agency_a.id):
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4()
        )
    body = counselor_client.get(
        _url(membership_a, application), HTTP_HOST=domain_a.host
    ).content.decode()
    assert "The extension can&#x27;t fill" in body or "The extension can't fill" in body
    assert "by hand" not in body


def test_an_unassigned_counselor_gets_404(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.get(_url(membership_a, application), HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_a_counselor_from_another_tenant_gets_404(
    client, agency_a, agency_b, domain_b, counselor_user, counselor_membership,
    membership_a, membership_b
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.get(_url(membership_a, application), HTTP_HOST=domain_b.host)
    assert response.status_code in (403, 404)


def test_another_students_application_is_404_for_the_assigned_counselor(
    counselor_client, agency_a, domain_a, membership_a, user_b
) -> None:
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        application = _application(agency_a, other)
    response = counselor_client.get(_url(membership_a, application), HTTP_HOST=domain_a.host)
    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_the_page_reads_facts_behind_the_row_level_security_policy(
    client, agency_a, domain_a, membership_a, counselor_user, counselor_membership,
    rls_enforced_orm
) -> None:
    """Real facts under a real NOBYPASSRLS role, end to end."""
    from apps.documents.models import VerifiedFact

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        application = _application(agency_a, membership_a)
        VerifiedFact.objects.create(
            tenant=agency_a,
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Ada Byron"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="passport.pdf",
            confirmed_by=membership_a,
            confirmed_at=timezone.now(),
            created_by=membership_a,
        )
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)

    response = client.get(_url(membership_a, application), HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert [q.answer for q in response.context["kit"].questions] == ["Ada Byron"]


def _same_response(a, b) -> None:
    import re

    def body(response) -> bytes:  # the per-response CSRF token is the only variance
        return re.sub(rb'csrfmiddlewaretoken" value="[^"]*"', b"", response.content)

    assert (a.status_code, body(a)) == (b.status_code, body(b))


def test_an_unassigned_counselor_gets_the_random_id_404_byte_for_byte(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    real = client.get(_url(membership_a, application), HTTP_HOST=domain_a.host)
    invented = client.get(
        f"/counselor/students/{membership_a.id}/applications/{uuid4()}/answers/",
        HTTP_HOST=domain_a.host,
    )
    assert real.status_code == 404
    _same_response(real, invented)


def test_the_student_gets_the_random_id_404_byte_for_byte(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    client.force_login(user_a)
    real = client.get(_url(membership_a, application), HTTP_HOST=domain_a.host)
    invented = client.get(
        f"/counselor/students/{membership_a.id}/applications/{uuid4()}/answers/",
        HTTP_HOST=domain_a.host,
    )
    assert real.status_code == 404
    _same_response(real, invented)


def test_a_user_with_no_membership_here_cannot_tell_a_real_id_from_an_invented_one(
    client, agency_a, domain_a, membership_a, user_b
) -> None:
    """user_b belongs to no tenant, so the tenant middleware answers before
    any view runs -- and answers the same for a real id and an invented one."""
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    client.force_login(user_b)
    real = client.get(_url(membership_a, application), HTTP_HOST=domain_a.host)
    invented = client.get(
        f"/counselor/students/{membership_a.id}/applications/{uuid4()}/answers/",
        HTTP_HOST=domain_a.host,
    )
    _same_response(real, invented)


def test_an_anonymous_visitor_gets_the_usual_login_redirect(
    client, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    real = client.get(_url(membership_a, application), HTTP_HOST=domain_a.host)
    invented = client.get(
        f"/counselor/students/{membership_a.id}/applications/{uuid4()}/answers/",
        HTTP_HOST=domain_a.host,
    )
    assert real.status_code == 302
    assert real["Location"].split("?")[0] == invented["Location"].split("?")[0]


def test_the_page_writes_nothing_and_refuses_every_other_method(
    counselor_client, agency_a, domain_a, membership_a
) -> None:
    from apps.funding.models import AuditEvent
    from apps.portals.models import ApplicationStep, PortalAccount

    with tenant_scope(agency_a.id):
        # An application e-mail is what would make a read create a PortalAccount.
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        application = _application(agency_a, membership_a)

    def counts():
        with tenant_scope(agency_a.id):
            return (
                AuditEvent.objects.count(),
                ApplicationStep.objects.count(),
                PortalAccount.objects.count(),
            )

    before = counts()
    url = _url(membership_a, application)
    assert counselor_client.get(url, HTTP_HOST=domain_a.host).status_code == 200
    assert counselor_client.head(url, HTTP_HOST=domain_a.host).status_code == 200
    for method in ("post", "put", "patch", "delete"):
        response = getattr(counselor_client, method)(url, HTTP_HOST=domain_a.host)
        assert response.status_code == 405, method
    assert counts() == before


def test_a_student_is_minted_a_packet_though_no_counselor_ever_opened_the_page(
    client, agency_a, domain_a, membership_a, monkeypatch
) -> None:
    """Applying depends on no counsellor action: no approval, no review flag."""
    import json

    from apps.portals import packets
    from apps.portals import pairing as pairing_module

    monkeypatch.setattr(packets, "verified_values", lambda student: {"identity.full_name": "Ada"})
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        code = pairing_module.issue_pairing_code(membership_a)
    token = client.post(
        "/ext/pair",
        data=json.dumps({"code": code, "installation_id": "install-1"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
    ).json()["token"]

    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 200
    assert response.json()["entries"][0]["value"] == "Ada"


@pytest.mark.parametrize("reason", ["deletion", "objection"])
def test_a_paused_student_gives_the_assigned_counselor_the_random_id_404(
    counselor_client, agency_a, domain_a, membership_a, reason
) -> None:
    from datetime import timedelta

    from apps.audit.models import DeletionRequest
    from apps.privacy.models import PrivacyRequest

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        now = timezone.now()
        if reason == "deletion":
            DeletionRequest.objects.create(
                tenant=agency_a, student=membership_a, state="REQUESTED", reason="OTHER"
            )
        else:
            PrivacyRequest.objects.create(
                tenant_id=agency_a.id, student=membership_a, kind="objection", channel="email",
                received_at=now, due_at=now + timedelta(days=9),
            )
    real = counselor_client.get(_url(membership_a, application), HTTP_HOST=domain_a.host)
    invented = counselor_client.get(
        f"/counselor/students/{membership_a.id}/applications/{uuid4()}/answers/",
        HTTP_HOST=domain_a.host,
    )
    assert real.status_code == 404
    _same_response(real, invented)


def test_the_counselor_sees_the_tagged_portal_address(
    counselor_client, agency_a, domain_a, membership_a
) -> None:
    from apps.portals.models import PortalAccount

    email = [{"profile_field": "contact.email", "action": {
        "selector": "#e", "description": "Email", "method": "fill", "arguments": ["%value%"]}}]
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        application = _application(agency_a, membership_a)
        from apps.portals.models import FieldMap

        FieldMap.objects.filter(portal_form=application.portal_form).update(entries=email)
        account = PortalAccount.objects.create(
            tenant=agency_a, student=membership_a, portal_host="apply.example.edu",
            tag="ab12cd", address="leyla.apply+ab12cd@outlook.com",
        )
    body = counselor_client.get(
        _url(membership_a, application), HTTP_HOST=domain_a.host
    ).content.decode()
    # Owner, 2026-10-13: the counsellor sees everything.
    assert account.address in body
    assert "(hidden)" not in body


def test_the_counselor_sees_the_plain_address_under_another_fact_key(
    counselor_client, agency_a, domain_a, membership_a
) -> None:
    from apps.documents.models import VerifiedFact
    from apps.portals.models import FieldMap

    entries = [{"profile_field": "identity.email", "action": {
        "selector": "#m", "description": "Email", "method": "fill", "arguments": ["%value%"]}}]
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        application = _application(agency_a, membership_a)
        FieldMap.objects.filter(portal_form=application.portal_form).update(entries=entries)
        VerifiedFact.objects.create(
            tenant=agency_a, student=membership_a, category=VerifiedFact.Category.IDENTITY,
            payload={"email": "Leyla.Apply@outlook.com"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT, source_ref="cv.pdf",
            confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a,
        )
    body = counselor_client.get(
        _url(membership_a, application), HTTP_HOST=domain_a.host
    ).content.decode()
    assert "leyla.apply@outlook.com" in body.casefold()
    assert "(hidden)" not in body
