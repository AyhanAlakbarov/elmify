"""The search box (`/student/search/`): read-only, the student's own rows only."""

import pytest

from apps.concierge.models import ConversationMessage
from apps.dashboard.search import matches, terms
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment, Membership
from tests.conftest import reads_no_catalogue

from .conftest import add_card


def test_terms_need_two_characters_and_ignore_case():
    assert terms("") == ()
    assert terms(" a ") == ()
    assert terms("  TUM   Informatics ") == ("tum", "informatics")


def test_every_word_must_match():
    assert matches(("tum", "informatics"), "M.Sc. Informatics", "TUM")
    assert not matches(("tum", "physics"), "M.Sc. Informatics", "TUM")
    assert not matches((), "anything")


@pytest.mark.django_db
def test_search_finds_programme_award_application_and_page(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    with reads_no_catalogue():
        response = client.get("/student/search/", {"q": "informatics"}, HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    kinds = {group.kind: group for group in response.context["groups"]}
    assert set(kinds) == {"Applications", "Programmes"}
    assert (
        kinds["Programmes"].results[0].url == f"/student/recommendation/#candidate-{programme.id}"
    )

    award = client.get("/student/search/", {"q": "daad"}, HTTP_HOST=domain_a.host)
    assert [g.kind for g in award.context["groups"]] == ["Funding"]

    page = client.get("/student/search/", {"q": "mailbox"}, HTTP_HOST=domain_a.host)
    assert "/student/settings/mailbox/" in page.content.decode()


@pytest.mark.django_db
def test_search_reads_the_counsellor_thread(
    client, agency_a, domain_a, user_a, membership_a, counselor_user
):
    with tenant_scope(agency_a.id):
        counselor = Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR
        )
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor, student=membership_a
        )
        ConversationMessage.objects.create(
            tenant=agency_a,
            student=membership_a,
            counselor=counselor,
            sender=counselor,
            body="Book the IELTS for late November.",
        )
    client.force_login(user_a)
    body = client.get("/student/search/", {"q": "ielts"}, HTTP_HOST=domain_a.host).content.decode()
    assert "Book the IELTS for late November." in body
    assert "Counsellor," in body


@pytest.mark.django_db
def test_search_never_shows_another_students_rows(
    client, agency_a, domain_a, user_a, membership_a, user_b, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        add_card(agency_a, other, programme)
    client.force_login(user_a)
    response = client.get("/student/search/", {"q": "informatics"}, HTTP_HOST=domain_a.host)
    # The programme is in this student's pack, but the application is the other student's.
    assert [g.kind for g in response.context["groups"]] == ["Programmes"]


@pytest.mark.django_db
def test_a_short_or_empty_query_searches_nothing(client, domain_a, user_a, membership_a):
    client.force_login(user_a)
    response = client.get("/student/search/", {"q": "x"}, HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    assert response.context["groups"] == ()
    assert "Type at least 2 characters" in response.content.decode()


@pytest.mark.django_db
def test_search_is_students_only(client, agency_a, domain_a, counselor_user):
    with tenant_scope(agency_a.id):
        Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR
        )
    client.force_login(counselor_user)
    response = client.get("/student/search/", {"q": "informatics"}, HTTP_HOST=domain_a.host)
    assert response.status_code in {302, 403}


@pytest.mark.django_db(transaction=True)
def test_search_runs_under_the_web_role(
    client, agency_a, domain_a, user_a, membership_a, pack, web_role_orm
):
    """Through Django's connection logged in as runtime_web: a catalogue read
    would be a real `permission denied`, which no superuser test can show."""
    client.force_login(user_a)
    response = client.get("/student/search/", {"q": "informatics"}, HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    assert response.context["total"] >= 1
