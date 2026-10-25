"""The new front ends (2026-10-25): one application's documents side by side,
recommendation requests, plan and payment, and the counsellor's letters to review.

What is real is asserted as real; what is waiting for its backend is asserted to
be visibly disabled and to post nowhere."""

from unittest.mock import patch

import pytest

from apps.documents.workspace import requirements_for
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import reads_no_catalogue, verify_mfa_session
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card
from tests.documents.test_writing_page import ENQUEUE, _identity, _letter

pytestmark = pytest.mark.django_db
pack = dashboard_conftest.pack


def _url(application: Application, doc: str = "") -> str:
    return f"/student/writing/letters/{application.id}/" + (f"?doc={doc}" if doc else "")


def test_requirements_put_the_letters_own_rules_first() -> None:
    application = Application(
        kit_requirements=[
            "A motivation letter of no more than two pages.",
            "Two recommendation letters from academic referees.",
            "A copy of your passport.",
        ],
        kit_your_actions=[{"text": "Name a supervisor you contacted."}],
    )
    req = requirements_for(application)
    assert req.letter == ("A motivation letter of no more than two pages.",)
    assert req.references == ("Two recommendation letters from academic referees.",)
    assert req.other == ("A copy of your passport.",)
    assert req.your_actions == ("Name a supervisor you contacted.",)


def test_the_workspace_shows_the_rules_beside_the_letter(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme,
            kit_requirements=["A motivation letter of one page."],
        )
        _identity(agency_a, membership_a)
        _letter(agency_a, membership_a, programme.program_id)
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get(_url(application), HTTP_HOST=domain_a.host).content.decode()
    assert "A motivation letter of one page." in body
    assert "I am applying because chemistry is my field." in body
    assert f'action="/student/writing/letters/{application.id}/write/"' in body
    assert "Approve this letter" in body


def test_the_answers_form_is_disabled_and_posts_nowhere(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    body = client.get(_url(application), HTTP_HOST=domain_a.host).content.decode()
    assert "Coming soon" in body
    assert '<form class="ws-q-form" aria-describedby="questions-heading">' in body
    assert "<fieldset disabled>" in body


@pytest.mark.parametrize("doc", ["references", "essay"])
def test_the_other_tabs_say_they_are_coming(
    client, agency_a, domain_a, user_a, membership_a, pack, doc
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    body = client.get(_url(application, doc), HTTP_HOST=domain_a.host).content.decode()
    assert "Coming soon" in body
    assert "<fieldset disabled>" in body or "disabled>Write my essay" in body


def test_a_scholarship_opens_on_its_essay_tab(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    _programme, award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, award)
    client.force_login(user_a)
    body = client.get(_url(application), HTTP_HOST=domain_a.host).content.decode()
    assert '<a href="?doc=essay" aria-current="page">' in body


def test_another_students_application_is_not_found(
    client, agency_a, domain_a, user_a, membership_a, pack, counselor_membership
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, counselor_membership, programme)
    client.force_login(user_a)
    assert client.get(_url(application), HTTP_HOST=domain_a.host).status_code == 404


def test_writing_from_the_workspace_returns_to_it(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        _identity(agency_a, membership_a)
    client.force_login(user_a)
    with patch(ENQUEUE):
        response = client.post(
            f"/student/writing/letters/{application.id}/write/",
            {"next": _url(application, "letter")},
            HTTP_HOST=domain_a.host,
        )
    assert response["Location"] == _url(application, "letter")


def test_a_foreign_next_is_ignored(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        _identity(agency_a, membership_a)
    client.force_login(user_a)
    with patch(ENQUEUE):
        response = client.post(
            f"/student/writing/letters/{application.id}/write/",
            {"next": "https://evil.example/"},
            HTTP_HOST=domain_a.host,
        )
    assert response["Location"] == "/student/writing/"


def test_the_references_page_is_disabled_and_lists_who_asks(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(
            agency_a, membership_a, programme,
            kit_requirements=["Two recommendation letters from academic referees."],
        )
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get(
            "/student/writing/references/", HTTP_HOST=domain_a.host
        ).content.decode()
    assert "Two recommendation letters from academic referees." in body
    assert "<fieldset disabled>" in body
    assert "nothing on this page is saved or emailed" in body


def test_the_plan_page_shows_whether_the_year_is_paid(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    client.force_login(user_a)
    body = client.get("/student/settings/plan/", HTTP_HOST=domain_a.host).content.decode()
    assert "is not paid yet" in body
    assert "<button type=\"button\" disabled>Pay by card</button>" in body


def test_the_counsellor_sees_flagged_letters_of_their_own_students(
    client, agency_a, domain_a, membership_a, pack, counselor_user, counselor_membership
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        add_card(agency_a, membership_a, programme, letter_note="flagged")
        _letter(agency_a, membership_a, programme.program_id)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    with reads_no_catalogue():
        body = client.get("/counselor/letters/", HTTP_HOST=domain_a.host).content.decode()
    assert "I am applying because chemistry is my field." in body
    assert "<button type=\"button\" disabled>Approve</button>" in body


def test_an_unassigned_counsellor_sees_nothing(
    client, agency_a, domain_a, membership_a, pack, counselor_user, counselor_membership
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme, letter_note="flagged")
        _letter(agency_a, membership_a, programme.program_id)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    body = client.get("/counselor/letters/", HTTP_HOST=domain_a.host).content.decode()
    assert "Nothing to review" in body


def test_a_student_cannot_open_the_review_list(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    client.force_login(user_a)
    assert client.get("/counselor/letters/", HTTP_HOST=domain_a.host).status_code == 403


