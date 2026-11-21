# ruff: noqa: F811 -- fixtures imported by name and requested as arguments
"""Elmify staff (PLATFORM_ADMIN) on the counsellor pages: every student of the agency,
read-only, View and Download on every file; assigned counsellors View only (owner
decision 2026-10-11)."""

from uuid import uuid4

import pytest
from django.urls import reverse

from apps.concierge.documents import register
from apps.concierge.models import ConversationMessage, DocumentVersion
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from tests.conftest import verify_mfa_session
from tests.dashboard.conftest import add_card, pack  # noqa: F401
from tests.dashboard.test_counselor_board import (  # noqa: F401 -- fixtures
    _EVERY_ROUTE,
    _notification,
    _offer,
    counselor_client,
    paused,
)
from tests.portals.test_prepared_serving import bucket  # noqa: F401
from tests.portals.test_staff_file_access import _login, _staff, files  # noqa: F401

pytestmark = pytest.mark.django_db


def _urls(files):
    p, d, u = files["prepared"], files["draft"], files["upload"]
    view = [
        reverse("portals-prepared-view", args=[p.id]),
        reverse("documents-draft-view", args=[d.id]),
        reverse("documents-upload-view", args=[u.id]),
    ]
    download = [
        reverse("portals-staff-download-prepared", args=[p.id]),
        reverse("documents-download", args=[d.id, d.rendered_filename]),
        reverse("documents-staff-download-upload", args=[u.id]),
    ]
    return view, download


@pytest.fixture
def staff_client(client, agency_a, domain_a):
    user, _membership = _staff(agency_a)
    _login(client, user)
    return client


def test_staff_list_every_student_of_the_agency_assigned_or_not(
    staff_client, domain_a, membership_a
) -> None:
    body = staff_client.get("/counselor/", HTTP_HOST=domain_a.host).content.decode()
    assert f"/counselor/students/{membership_a.id}/" in body


def test_a_counselor_still_lists_only_assigned_students(
    client, domain_a, counselor_user, counselor_membership, membership_a
) -> None:
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    body = client.get("/counselor/", HTTP_HOST=domain_a.host).content.decode()
    assert f"/counselor/students/{membership_a.id}/" not in body


def test_staff_board_has_view_and_download_for_every_file_and_no_forms(
    staff_client, domain_a, membership_a, files
) -> None:
    response = staff_client.get(f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    body = response.content.decode()
    view, download = _urls(files)
    for url in view + download:
        assert f'href="{url}"' in body, url
    # The only form left is base.html's logout: nothing to write with.
    assert body.count("<form") == 1
    assert "Read-only" in body
    assert "/answers/" not in body and "gap-interview" not in body


def test_staff_see_files_only_nothing_from_the_rest_of_the_board(
    client, agency_a, domain_a, membership_a, counselor_membership, counselor_user, files, pack,
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme, state="SUBMITTED", outcome="ADMITTED")
        _notification(agency_a, membership_a)
        _offer(agency_a, membership_a, card)
        ConversationMessage.objects.create(
            tenant=agency_a, student=membership_a, counselor=counselor_membership,
            sender=membership_a, body="SECRET-MESSAGE-BODY",
        )
    url = f"/counselor/students/{membership_a.id}/"
    # The assigned counsellor's board is unchanged: it carries all of it.
    from django.test import Client

    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    other = Client()
    other.force_login(counselor_user)
    verify_mfa_session(other, counselor_user)
    board = other.get(url, HTTP_HOST=domain_a.host).content.decode()
    for text in ("SECRET-MESSAGE-BODY", "tum.de", "Needs you now", "Mail from universities"):
        assert text in board, text
    # The same rows, staff: files and nothing else.
    staff, _m = _staff(agency_a)
    _login(client, staff)
    body = client.get(url, HTTP_HOST=domain_a.host).content.decode()
    for text in (
        "SECRET-MESSAGE-BODY", "tum.de", "Data Engineering", "Needs you now",
        "Mail from universities", "Admitted", "ADMITTED", "Write to the student", "conversation",
    ):
        assert text not in body, text
    view, download = _urls(files)
    assert all(f'href="{u}"' in body for u in view + download)


def test_the_staff_list_hides_a_paused_student(
    staff_client, paused, domain_a, membership_a, user_a
) -> None:
    body = staff_client.get("/counselor/", HTTP_HOST=domain_a.host).content.decode()
    assert f"/counselor/students/{membership_a.id}/" not in body
    assert user_a.get_username() not in body


def test_an_assigned_counselor_gets_view_links_and_no_download(
    counselor_client, domain_a, membership_a, files
) -> None:
    body = counselor_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    view, download = _urls(files)
    for url in view:
        assert f'href="{url}"' in body, url
    for url in download:
        assert url not in body, url
    assert "Download" not in body
    assert "<form" in body  # still writes


def test_a_student_still_downloads_their_own_cv(client, user_a, domain_a, membership_a, files):
    client.force_login(user_a)
    draft = files["draft"]
    body = client.get("/student/documents/", HTTP_HOST=domain_a.host).content.decode()
    assert reverse("documents-download", args=[draft.id, draft.rendered_filename]) in body


@pytest.mark.parametrize(("method", "suffix"), [r for r in _EVERY_ROUTE if r != ("get", "")])
def test_every_write_and_page_but_the_board_is_a_404_for_staff(
    staff_client, agency_a, domain_a, membership_a, method, suffix
) -> None:
    response = getattr(staff_client, method)(
        f"/counselor/students/{membership_a.id}/{suffix}", {"body": "hi"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 404
    with tenant_scope(agency_a.id):
        assert not ConversationMessage.objects.filter(student=membership_a).exists()
        assert not AuditEvent.objects.exists()


def test_the_answers_page_stays_assigned_counselor_only(
    staff_client, domain_a, membership_a
) -> None:
    url = f"/counselor/students/{membership_a.id}/applications/{uuid4()}/answers/"
    assert staff_client.get(url, HTTP_HOST=domain_a.host).status_code == 404


def test_staff_get_a_404_for_a_paused_student(
    staff_client, paused, domain_a, membership_a  # noqa: F811
) -> None:
    response = staff_client.get(f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_staff_of_another_agency_get_a_404_for_the_student(
    client, agency_a, agency_b, domain_a, domain_b, membership_a
) -> None:
    user_b, _ = _staff(agency_b, "staff-b")
    _login(client, user_b)
    url = f"/counselor/students/{membership_a.id}/"
    assert client.get(url, HTTP_HOST=domain_b.host).status_code == 404
    assert client.get(url, HTTP_HOST=domain_a.host).status_code in (403, 404)


def test_staff_cannot_open_a_counselor_as_a_student(
    staff_client, domain_a, counselor_membership
) -> None:
    url = f"/counselor/students/{counselor_membership.id}/"
    assert staff_client.get(url, HTTP_HOST=domain_a.host).status_code == 404


def test_the_staff_page_is_titled_by_display_name_and_has_no_cv_facts_section(
    staff_client, agency_a, domain_a, membership_a, user_a
) -> None:
    user_a.first_name, user_a.last_name = "Aysel", "Mammadova"
    user_a.save()
    body = staff_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    assert "<title>Aysel Mammadova</title>" in body
    assert "<h1>Aysel Mammadova</h1>" in body
    # Staff never see CV facts, so "Nothing to confirm." would claim there are none.
    assert "Facts read from your CV" not in body and "Nothing to confirm." not in body


def test_a_vouched_mail_document_request_shows_its_state_and_no_mail_text(
    staff_client, agency_a, domain_a, membership_a, pack
) -> None:
    from tests.documents.test_documents_page import _signal

    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        _signal(
            agency_a, membership_a, application, tier="CONTENT", trusted=True,
            label="DOCUMENT_REQUEST", document_name="Certified copy of transcript MAILTEXT",
        )
    body = staff_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    assert "Transcript" in body  # the row the request added, by its kind
    for text in ("MAILTEXT", "Certified copy of transcript", "tum.de"):
        assert text not in body, text


def test_a_documents_table_cell_links_the_held_file(
    staff_client, agency_a, domain_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme, kit_requirements=["Passport copy"])
        upload = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=upload.id).update(
            state="AVAILABLE", scan_result="NO_THREATS_FOUND", content_type="application/pdf",
            promoted_key=f"tenants/{agency_a.id}/students/{membership_a.id}/uploads/{upload.id}/a",
        )
    body = staff_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    cells = "".join(part.split("</td>")[0] for part in body.split("<td>")[1:])
    assert reverse("documents-upload-view", args=[upload.id]) in cells
    assert reverse("documents-staff-download-upload", args=[upload.id]) in cells
