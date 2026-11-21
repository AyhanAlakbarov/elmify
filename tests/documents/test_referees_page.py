# ruff: noqa: F811 -- fixtures imported by name and requested as arguments
"""The referees page (lanes spec §11.2): the student adds, edits and marks professors;
the counsellor reads them; Elmify staff never see them."""

from unittest import mock

import pytest
from django.utils import timezone

from apps.documents.models import Referee, VerifiedFact
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from tests.dashboard.test_counselor_board import counselor_client  # noqa: F401
from tests.portals.test_staff_file_access import _login, _staff

pytestmark = pytest.mark.django_db
PAGE = "/student/referees/"
ADD = "/student/referees/add/"
_FORM = {
    "title": "Prof.", "name": "Rauf Aliyev", "institution": "ADA University",
    "email": "raliyev@ada.edu.az", "institutional_email": "on", "kind": "ACADEMIC",
    "relationship": "Supervised my thesis.", "agreed_requests": "3",
}


def _referee(agency, student, **extra):
    with tenant_scope(agency.id):
        return Referee.objects.create(
            tenant=agency, student=student, name="Rauf Aliyev", title="Prof.", **extra
        )


def _cv_reference(agency, student, **payload):
    with tenant_scope(agency.id):
        return VerifiedFact.objects.create(
            student=student, category=VerifiedFact.Category.REFERENCE,
            payload={"name": "Leyla Karimova", "position": "Dr.", "institution": "BHOS",
                     "email": "leyla@bhos.edu.az", **payload},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT, source_ref="cv",
            confirmed_by=student, confirmed_at=timezone.now(), created_by=student,
        )


def _events(agency, event):
    with tenant_scope(agency.id):
        return AuditEvent.objects.filter(event=event).count()


def test_a_student_with_no_referees_sees_the_form_and_nothing_else(
    client, domain_a, user_a, membership_a
) -> None:
    client.force_login(user_a)
    response = client.get(PAGE, HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert response.status_code == 200
    assert "No referees yet." in body
    assert 'name="agreed_requests"' in body
    assert "From your CV" not in body


def test_adding_a_professor_saves_them_and_audits_it(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    client.force_login(user_a)
    response = client.post(ADD, _FORM, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        referee = Referee.objects.get(student=membership_a)
    assert (referee.label, referee.agreed_requests, referee.institutional_email) == (
        "Prof. Rauf Aliyev", 3, True
    )
    assert _events(agency_a, "referee.added") == 1
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Prof. Rauf Aliyev" in body and "agreed to 3 portal requests" in body


def test_a_double_click_adds_the_professor_once(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    client.force_login(user_a)
    client.post(ADD, _FORM, HTTP_HOST=domain_a.host)
    client.post(ADD, {**_FORM, "name": "rauf aliyev"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert Referee.objects.filter(student=membership_a).count() == 1
    assert _events(agency_a, "referee.added") == 1


def test_a_bad_email_is_refused_and_nothing_is_saved(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    client.force_login(user_a)
    response = client.post(ADD, {**_FORM, "email": "not an address"}, HTTP_HOST=domain_a.host)
    assert response.status_code == 400
    with tenant_scope(agency_a.id):
        assert not Referee.objects.exists()


def test_the_rate_limit_stops_a_write(client, agency_a, domain_a, user_a, membership_a) -> None:
    client.force_login(user_a)
    with mock.patch("apps.documents.referee_views.rate_limited", return_value=True):
        client.post(ADD, _FORM, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert not Referee.objects.exists()


def test_editing_and_marking_a_professor_declined(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    referee = _referee(agency_a, membership_a)
    client.force_login(user_a)
    client.post(
        f"/student/referees/{referee.id}/edit/", {**_FORM, "agreed_requests": "1"},
        HTTP_HOST=domain_a.host,
    )
    client.post(
        f"/student/referees/{referee.id}/status/", {"status": "DECLINED"},
        HTTP_HOST=domain_a.host,
    )
    client.post(
        f"/student/referees/{referee.id}/status/", {"status": "GHOSTED"},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(agency_a.id):
        referee.refresh_from_db()
    assert (referee.agreed_requests, referee.status) == (1, "DECLINED")
    assert _events(agency_a, "referee.updated") == _events(agency_a, "referee.status") == 1


def test_another_students_professor_is_404(
    client, agency_a, domain_a, user_a, user_b, membership_a
) -> None:
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
    theirs = _referee(agency_a, other)
    client.force_login(user_a)
    for suffix, data in (("edit/", _FORM), ("status/", {"status": "SILENT"})):
        response = client.post(
            f"/student/referees/{theirs.id}/{suffix}", data, HTTP_HOST=domain_a.host
        )
        assert response.status_code == 404


def test_cv_references_are_offered_never_added_and_do_not_contact_is_skipped(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    offered = _cv_reference(agency_a, membership_a)
    hidden = _cv_reference(agency_a, membership_a, name="Elvin Mammadov", do_not_contact=True)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Leyla Karimova" in body and "Elvin Mammadov" not in body
    with tenant_scope(agency_a.id):
        assert not Referee.objects.exists()
    refused = client.post(f"/student/referees/from-cv/{hidden.id}/", HTTP_HOST=domain_a.host)
    assert refused.status_code == 404
    client.post(f"/student/referees/from-cv/{offered.id}/", HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        added = Referee.objects.get(student=membership_a)
    assert (added.name, added.title, added.email) == ("Leyla Karimova", "Dr.", "leyla@bhos.edu.az")
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Add as a referee" not in body
    # A second click on the same reference adds nothing and is not an error page.
    again = client.post(f"/student/referees/from-cv/{offered.id}/", HTTP_HOST=domain_a.host)
    assert again.status_code == 302
    with tenant_scope(agency_a.id):
        assert Referee.objects.filter(student=membership_a).count() == 1


def test_the_counselor_reads_the_referees_and_cannot_change_them(
    counselor_client, agency_a, domain_a, membership_a
) -> None:
    referee = _referee(agency_a, membership_a, relationship="Taught me algorithms.")
    body = counselor_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    assert "Prof. Rauf Aliyev" in body and "Taught me algorithms." in body
    assert f"/student/referees/{referee.id}/" not in body


def test_a_counselor_whose_assignment_ended_sees_no_referee(
    counselor_client, agency_a, domain_a, membership_a
) -> None:
    from apps.tenancy.models import CounselorAssignment

    _referee(agency_a, membership_a, relationship="Taught me algorithms.")
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.filter(student=membership_a).update(active=False)
    response = counselor_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 404
    assert "Rauf Aliyev" not in response.content.decode()


def test_elmify_staff_never_see_a_referee(client, agency_a, domain_a, membership_a) -> None:
    _referee(agency_a, membership_a, relationship="Taught me algorithms.")
    staff, _membership = _staff(agency_a)
    _login(client, staff)
    response = client.get(f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert response.status_code == 200
    assert "Rauf Aliyev" not in body and "Taught me algorithms." not in body
    assert client.get(PAGE, HTTP_HOST=domain_a.host).status_code == 403


def test_a_relationship_over_the_limit_is_refused_and_nothing_is_saved(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    client.force_login(user_a)
    response = client.post(
        ADD, {**_FORM, "relationship": "x" * 1001}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 400
    with tenant_scope(agency_a.id):
        assert not Referee.objects.exists()
    ok = client.post(ADD, {**_FORM, "relationship": "x" * 1000}, HTTP_HOST=domain_a.host)
    assert ok.status_code == 302


def test_an_invalid_edit_shows_on_that_professors_row_not_the_add_form(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    referee = _referee(agency_a, membership_a)
    client.force_login(user_a)
    url = f"/student/referees/{referee.id}/edit/"
    response = client.post(url, {**_FORM, "agreed_requests": "-1"}, HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert response.status_code == 400
    add_part = body.split('action="/student/referees/add/"')[1]
    edit_part = body.split(f'action="{url}"')[1].split("</form>")[0]
    assert "errorlist" in edit_part and 'value="-1"' in edit_part
    assert 'value="Rauf Aliyev"' not in add_part.split("</form>")[0]
    with tenant_scope(agency_a.id):
        assert Referee.objects.count() == 1
    client.post(url, {**_FORM, "agreed_requests": "2"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert Referee.objects.count() == 1
        assert Referee.objects.get().agreed_requests == 2


def test_an_edit_cannot_duplicate_another_professor(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    _referee(agency_a, membership_a, email="raliyev@ada.edu.az")
    with tenant_scope(agency_a.id):
        other = Referee.objects.create(
            tenant=agency_a, student=membership_a, name="Someone Else", email="s@ada.edu.az"
        )
    client.force_login(user_a)
    client.post(f"/student/referees/{other.id}/edit/", _FORM, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        other.refresh_from_db()
    assert other.name == "Someone Else"
    assert _events(agency_a, "referee.updated") == 0


def test_the_heading_differs_for_student_and_counselor(
    client, counselor_client, agency_a, domain_a, user_a, membership_a
) -> None:
    board = counselor_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    assert "Your referees" not in board and 'id="referees-heading">Referees<' in board
    counselor_client.logout()
    client.force_login(user_a)
    assert "Your referees" in client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()


def test_a_counselor_cannot_write_referees(
    counselor_client, agency_a, domain_a, membership_a
) -> None:
    referee = _referee(agency_a, membership_a)
    fact = _cv_reference(agency_a, membership_a)
    for url, data in (
        (ADD, _FORM),
        (f"/student/referees/{referee.id}/edit/", {**_FORM, "name": "Changed"}),
        (f"/student/referees/{referee.id}/status/", {"status": "DECLINED"}),
        (f"/student/referees/from-cv/{fact.id}/", {}),
    ):
        assert counselor_client.post(url, data, HTTP_HOST=domain_a.host).status_code == 403
    with tenant_scope(agency_a.id):
        referee.refresh_from_db()
        assert Referee.objects.count() == 1
    assert (referee.name, referee.status) == ("Rauf Aliyev", "ACTIVE")


def test_elmify_staff_cannot_write_referees(client, agency_a, domain_a, membership_a) -> None:
    staff, _membership = _staff(agency_a)
    _login(client, staff)
    assert client.post(ADD, _FORM, HTTP_HOST=domain_a.host).status_code == 403
    with tenant_scope(agency_a.id):
        assert not Referee.objects.exists()


def test_supervisors_from_research_facts_offered_and_deduplicated_for_transliterated_referees(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    now = timezone.now()
    with tenant_scope(agency_a.id):
        sup_fact = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.RESEARCH,
            payload={
                "thesis_title": "Transformer Reaction Yields",
                "supervisor": "Prof. Philippe Schwaller",
                "institution": "EPFL",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="cv",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        # Already added under Azerbaijani spelling: must not be re-offered under English spelling
        Referee.objects.create(
            tenant=agency_a,
            student=membership_a,
            name="Rauf Əliyev",
            title="Prof.",
            institution="ADA University",
        )
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.RESEARCH,
            payload={
                "thesis_title": "Graph Search",
                "supervisor": "Prof. Rauf Aliyev",
                "institution": "ADA University",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="cv",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )

    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Prof. Philippe Schwaller, EPFL" in body
    assert "Prof. Rauf Aliyev, ADA University" not in body

    resp = client.post(f"/student/referees/from-cv/{sup_fact.id}/", HTTP_HOST=domain_a.host)
    assert resp.status_code == 302
    with tenant_scope(agency_a.id):
        added = Referee.objects.get(student=membership_a, name="Philippe Schwaller")
    assert added.title == "Prof."
    assert added.institution == "EPFL"
    assert added.relationship == "Supervised: Transformer Reaction Yields"

    with tenant_scope(agency_a.id):
        exp_fact = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={
                "title": "Research Intern",
                "employer": "ETH Zürich",
                "supervisor": "Dr. Andreas Krause",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="cv",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
    body2 = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Dr. Andreas Krause, ETH Zürich" in body2
    resp2 = client.post(f"/student/referees/from-cv/{exp_fact.id}/", HTTP_HOST=domain_a.host)
    assert resp2.status_code == 302
    with tenant_scope(agency_a.id):
        added_exp = Referee.objects.get(student=membership_a, name="Andreas Krause")
    assert added_exp.title == "Dr."
    assert added_exp.institution == "ETH Zürich"
    assert added_exp.relationship == "Supervised: Research Intern"
