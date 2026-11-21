"""Book a demo (the website's form) and the owner's view of the requests."""

import pytest
from django.core.cache import cache

from apps.funding.models import AuditEvent
from apps.leads.models import DemoRequest
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment, Membership
from tests.conftest import verify_mfa_session

FORM = {
    "full_name": "Nigar Karimova",
    "email": "Nigar@AgencyOne.az",
    "role": "AGENCY",
    "organisation": "AgencyOne",
    "country": "Azerbaijan",
    "message": "We place 200 students a year.",
}


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_anyone_can_book_a_demo_and_it_lands_in_the_hosts_agency(client, domain_a, domain_b):
    assert client.get("/demo/", HTTP_HOST=domain_a.host).status_code == 200
    response = client.post("/demo/", FORM, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/demo/thanks/"
    row = DemoRequest._base_manager.get()
    assert row.tenant_id == domain_a.agency_id
    assert row.email == "nigar@agencyone.az"
    assert row.state == DemoRequest.State.NEW
    with tenant_scope(domain_b.agency_id):
        assert not DemoRequest.objects.exists()


@pytest.mark.django_db
def test_a_demo_request_needs_a_name_an_email_and_a_role(client, domain_a):
    response = client.post("/demo/", {"full_name": ""}, HTTP_HOST=domain_a.host)
    assert response.status_code == 400
    body = response.content.decode()
    assert body.count("This field is required.") == 3
    assert not DemoRequest._base_manager.exists()


@pytest.mark.django_db
def test_demo_requests_are_rate_limited_per_address(client, domain_a):
    for _ in range(5):
        assert client.post("/demo/", FORM, HTTP_HOST=domain_a.host).status_code == 302
    assert client.post("/demo/", FORM, HTTP_HOST=domain_a.host).status_code == 429
    assert DemoRequest._base_manager.count() == 5


@pytest.fixture
def owner_client(client, agency_a, domain_a, django_user_model):
    user = django_user_model.objects.create_user(username="owner-a")
    with tenant_scope(agency_a.id):
        owner = Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.OWNER)
    client.force_login(user)
    verify_mfa_session(client, user)
    return client, owner


@pytest.mark.django_db
def test_the_owner_sees_and_closes_a_demo_request(owner_client, agency_a, domain_a):
    client, _owner = owner_client
    with tenant_scope(agency_a.id):
        demo = DemoRequest.objects.create(**{**FORM, "email": "nigar@agencyone.az"})
    page = client.get("/owner/", HTTP_HOST=domain_a.host).content.decode()
    assert "Nigar Karimova" in page and "nigar@agencyone.az" in page
    response = client.post(f"/owner/demo-requests/{demo.id}/contacted/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    demo.refresh_from_db()
    assert demo.state == DemoRequest.State.CONTACTED


@pytest.mark.django_db
def test_a_student_cannot_close_a_demo_request(client, agency_a, domain_a, user_a, membership_a):
    with tenant_scope(agency_a.id):
        demo = DemoRequest.objects.create(**FORM)
    client.force_login(user_a)
    response = client.post(f"/owner/demo-requests/{demo.id}/contacted/", HTTP_HOST=domain_a.host)
    assert response.status_code == 403
    demo.refresh_from_db()
    assert demo.state == DemoRequest.State.NEW


@pytest.mark.django_db
def test_the_owner_assigns_and_removes_a_counsellor(
    owner_client, agency_a, domain_a, membership_a, counselor_membership
):
    client, owner = owner_client
    url = f"/owner/students/{membership_a.id}/counselor/"
    client.post(url, {"counselor": str(counselor_membership.id)}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        active = CounselorAssignment.objects.get(student=membership_a, active=True)
        assert active.counselor_id == counselor_membership.id
        assert AuditEvent.objects.filter(
            actor=owner, event="counselor_assignment.changed", object_id=membership_a.id
        ).exists()
    client.post(url, {"counselor": ""}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert not CounselorAssignment.objects.filter(student=membership_a, active=True).exists()


@pytest.mark.django_db
def test_assigning_refuses_someone_who_is_not_a_counsellor(
    owner_client, agency_a, domain_a, membership_a
):
    client, owner = owner_client
    client.post(
        f"/owner/students/{membership_a.id}/counselor/",
        {"counselor": str(owner.id)},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(agency_a.id):
        assert not CounselorAssignment.objects.exists()


@pytest.mark.django_db
def test_student_and_agency_demo_audiences_and_owner_separation(owner_client, agency_a, domain_a):
    client, _owner = owner_client
    student_page = client.get("/demo/?audience=student", HTTP_HOST=domain_a.host).content.decode()
    assert "Book a student &amp; parent walkthrough" in student_page
    assert 'value="STUDENT" selected' in student_page
    assert "Current university (optional)" in student_page

    agency_page = client.get("/demo/agency/", HTTP_HOST=domain_a.host).content.decode()
    assert "30-day white-label agency pilot" in agency_page
    assert 'value="AGENCY" selected' in agency_page

    with tenant_scope(agency_a.id):
        DemoRequest.objects.create(**{**FORM, "email": "nigar@agencyone.az"})
        DemoRequest.objects.create(
            full_name="Tural Mammadov",
            email="tural@student.az",
            role=DemoRequest.Role.STUDENT,
            organisation="ADA University",
            country="Azerbaijan",
            message="Looking at MSc Data Science in Italy and Germany.",
        )

    owner_page = client.get("/owner/", HTTP_HOST=domain_a.host).content.decode()
    assert "Agency &amp; university demo requests (1)" in owner_page
    assert "Student &amp; parent walkthrough requests (1)" in owner_page
    assert "Nigar Karimova" in owner_page
    assert "Tural Mammadov" in owner_page

