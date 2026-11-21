"""Elmify staff (PLATFORM_ADMIN) view and download any student's files in their agency,
every view and download audited before a byte is read (owner decision 2026-10-11).

Review Focus of docs/superpowers/plans/2026-10-11-staff-file-access.md, one block each:
1 cross-agency under a real NOBYPASSRLS role, 2 a failed audit write, 3 the record itself,
4 counsellors gain nothing, 5 paused students.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.audit import staff_access
from apps.audit.models import StaffFileAccess
from apps.concierge.models import DocumentVersion
from apps.portals import views as portal_views
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import CounselorAssignment, Membership
from tests.conftest import verify_mfa_session
from tests.dashboard.test_counselor_board import paused  # noqa: F401 -- a fixture
from tests.portals.test_ext_document import PDF, _promoted
from tests.portals.test_kit import _application, _approved_cv
from tests.portals.test_prepare import _r
from tests.portals.test_prepared_serving import PREPARED, _prepared, bucket  # noqa: F401

pytestmark = pytest.mark.django_db
DRAFT = b"%PDF-cv"  # what the `bucket` fixture's read_draft returns
ACCESS = StaffFileAccess._base_manager  # the test role bypasses RLS; no scope needed to look
INLINE_CSP = "default-src 'none'; img-src 'self'; object-src 'self'; frame-ancestors 'none'"


def _staff(agency, username="elmify-staff"):
    user = get_user_model().objects.create_user(username=username)
    with tenant_scope(agency.id):
        membership = Membership.objects.create(
            tenant=agency, user=user, role=Membership.Role.PLATFORM_ADMIN
        )
    return user, membership


@pytest.fixture
def files(agency_a, membership_a, bucket):  # noqa: F811
    """One prepared file, one approved draft and one available upload of student A. Not
    `prepared_cv_application`, which holds A's scope open through the test."""
    with tenant_scope(agency_a.id):
        draft = _approved_cv(agency_a, membership_a)
        application = _application(agency_a, membership_a)
        [prepared] = _prepared(application, bucket, _r("CV", "max_bytes", 2_000_000))
        upload = _promoted(agency_a, membership_a, bucket)
    return {"prepared": prepared, "draft": draft, "upload": upload}


def _routes(files):
    """(name, url, action, kind, document id, expected bytes) for every staff-reachable route."""
    p, d, u = files["prepared"], files["draft"], files["upload"]
    return [
        ("prepared-view", reverse("portals-prepared-view", args=[p.id]), "view",
         f"PREPARED_{p.document}", p.id, PREPARED),
        ("prepared-download", reverse("portals-staff-download-prepared", args=[p.id]),
         "download", f"PREPARED_{p.document}", p.id, PREPARED),
        ("draft-view", reverse("documents-draft-view", args=[d.id]), "view", f"DRAFT_{d.kind}",
         d.id, DRAFT),
        ("draft-download", reverse("documents-download", args=[d.id, d.rendered_filename]),
         "download", f"DRAFT_{d.kind}", d.id, DRAFT),
        ("upload-view", reverse("documents-upload-view", args=[u.id]), "view",
         f"UPLOAD_{u.kind}", u.id, PDF),
        ("upload-download", reverse("documents-staff-download-upload", args=[u.id]), "download",
         f"UPLOAD_{u.kind}", u.id, PDF),
    ]


def _login(client, user):
    client.force_login(user)
    verify_mfa_session(client, user)


# --- the rule: staff see and download, unassigned, and each access is recorded first ---


def test_staff_view_and_download_every_file_unassigned_and_each_is_recorded(
    client, agency_a, domain_a, membership_a, files, caplog
):
    """Review Focus 3: the StaffFileAccess row and the StaffFileView line, per access."""
    user, staff = _staff(agency_a)
    _login(client, user)
    for name, url, action, kind, document_id, body in _routes(files):
        with caplog.at_level("INFO"):
            response = client.get(url, HTTP_HOST=domain_a.host)
        assert response.status_code == 200, name
        assert response.content == body, name
        assert response["X-Content-Type-Options"] == "nosniff", name
        if action == "view":
            assert response["Content-Disposition"] == "inline", name
            assert response["Cache-Control"] == "no-store", name
            assert response["Content-Security-Policy"] == INLINE_CSP, name
        else:  # inert_response, the staff draft download included
            assert response["Content-Disposition"].startswith("attachment"), name
            assert response["Content-Security-Policy"] == "sandbox; default-src 'none'", name
            assert response["Cache-Control"] == "no-store", name
        row = ACCESS.get(document_id=document_id, action=action.upper())  # exactly one
        assert (row.tenant_id, row.staff_id, row.student_id, row.document_kind) == (
            agency_a.id, staff.id, membership_a.id, kind
        ), name
        line = (
            f"StaffFileView action={action} tenant={agency_a.id} staff={staff.id} "
            f"student={membership_a.id} document={kind}:{document_id}"
        )
        assert line in caplog.text, name
        caplog.clear()


def test_the_log_line_carries_no_filename(client, agency_a, domain_a, files, caplog):
    user, _staff_m = _staff(agency_a)
    _login(client, user)
    draft = files["draft"]
    with caplog.at_level("INFO"):
        url = reverse("documents-download", args=[draft.id, draft.rendered_filename])
        assert client.get(url, HTTP_HOST=domain_a.host).status_code == 200
    assert "StaffFileView" in caplog.text and draft.rendered_filename not in caplog.text


def test_the_record_is_written_before_the_bytes_are_read(
    client, agency_a, domain_a, files, monkeypatch
):
    user, staff = _staff(agency_a)
    seen = []

    def read(key):
        seen.append(StaffFileAccess.objects.filter(staff=staff).exists())
        return PREPARED

    monkeypatch.setattr(portal_views, "read_prepared", read)
    _login(client, user)
    url = reverse("portals-prepared-view", args=[files["prepared"].id])
    assert client.get(url, HTTP_HOST=domain_a.host).status_code == 200
    assert seen == [True]


# --- Review Focus 2: a failed audit write serves nothing ---


def test_a_failed_audit_write_is_a_404_with_no_bytes(
    client, agency_a, domain_a, files, monkeypatch
):
    """A real database error: an action longer than its column, refused by Postgres."""
    user, _staff_m = _staff(agency_a)
    monkeypatch.setattr(staff_access.StaffFileAccess, "Action", lambda _value: "x" * 11)
    _login(client, user)
    for name, url, _action, _kind, _id, body in _routes(files):
        response = client.get(url, HTTP_HOST=domain_a.host)
        assert response.status_code == 404, name
        assert body not in response.content, name
    assert not ACCESS.exists()


# --- Review Focus 4: counsellors gain nothing; downloads are staff only ---


def test_an_unassigned_counsellor_or_owner_gets_a_404_everywhere(
    client, agency_a, domain_a, counselor_user, counselor_membership, files
):
    owner = get_user_model().objects.create_user(username="owner-a")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=owner, role=Membership.Role.OWNER)
    for who in (counselor_user, owner):
        _login(client, who)
        for name, url, *_rest in _routes(files):
            assert client.get(url, HTTP_HOST=domain_a.host).status_code == 404, name
    assert not ACCESS.exists()


def test_an_assigned_counsellor_views_and_never_downloads(
    client, agency_a, domain_a, membership_a, counselor_user, counselor_membership, files
):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    _login(client, counselor_user)
    for name, url, action, *_rest in _routes(files):
        status = client.get(url, HTTP_HOST=domain_a.host).status_code
        # Owner 2026-10-10: counsellors read files, they do not download them --
        # documents-download included.
        assert status == (200 if action == "view" else 404), name
    # A counsellor's view is their job, not a Elmify-staff access.
    assert not ACCESS.exists()


def test_the_student_downloads_their_draft_and_gets_no_view_or_staff_route(
    client, domain_a, user_a, files
):
    client.force_login(user_a)
    for name, url, *_rest in _routes(files):
        status = client.get(url, HTTP_HOST=domain_a.host).status_code
        assert status == (200 if name == "draft-download" else 404), name
    assert not ACCESS.exists()


def test_a_retired_unavailable_or_unservable_type_upload_is_a_404_for_staff(
    client, agency_a, domain_a, files
):
    from django.utils import timezone

    user, _staff_m = _staff(agency_a)
    _login(client, user)
    upload = files["upload"]
    urls = [reverse(n, args=[upload.id]) for n in ("documents-upload-view",
                                                    "documents-staff-download-upload")]
    changes = ({"retired_at": timezone.now()}, {"state": "CHECKING"},
               {"content_type": "text/html"})  # only pdf, png and jpeg are ever served
    for change in changes:
        DocumentVersion._base_manager.filter(id=upload.id).update(**change)
        for url in urls:
            assert client.get(url, HTTP_HOST=domain_a.host).status_code == 404
        DocumentVersion._base_manager.filter(id=upload.id).update(
            retired_at=None, state="AVAILABLE", content_type="application/pdf"
        )


# --- Review Focus 5: a paused student is a 404 for staff too ---


def test_a_paused_students_files_are_a_404_for_staff(
    client, agency_a, domain_a, files, paused  # noqa: F811
):
    user, _staff_m = _staff(agency_a)
    _login(client, user)
    for name, url, *_rest in _routes(files):
        assert client.get(url, HTTP_HOST=domain_a.host).status_code == 404, name
    assert not ACCESS.exists()


def test_an_inactive_students_page_and_files_are_a_404_for_staff_and_nothing_is_recorded(
    client, agency_a, domain_a, membership_a, files
):
    """An erased student is inactive with no pause left (EXECUTED clears the lock), and a
    partial erasure keeps their real name: neither the page nor any file opens."""
    with tenant_scope(agency_a.id):
        Membership.objects.filter(id=membership_a.id).update(active=False)
    user, _staff_m = _staff(agency_a)
    _login(client, user)
    page = f"/counselor/students/{membership_a.id}/"
    assert client.get(page, HTTP_HOST=domain_a.host).status_code == 404
    for name, url, *_rest in _routes(files):
        assert client.get(url, HTTP_HOST=domain_a.host).status_code == 404, name
    assert not ACCESS.exists()


# --- Review Focus 1: another agency's ids under a real NOBYPASSRLS role ---


@pytest.fixture
def staff_pair(agency_a, agency_b):
    """Committed as the test superuser, before the ORM changes roles."""
    return _staff(agency_a, "elmify-staff-a"), _staff(agency_b, "elmify-staff-b")


@pytest.mark.django_db(transaction=True)
def test_staff_of_another_agency_get_a_404_behind_row_level_security(
    client, agency_a, agency_b, domain_a, domain_b, files, staff_pair, rls_enforced_orm
):
    """Staff of B change the URL to A's ids: the request runs under B's tenant, so A's rows
    do not exist there. Staff of A on A's host is the positive control: the same routes,
    the audit write included, work under the policy."""
    (user_a, staff_a), (user_b, staff_b) = staff_pair
    _login(client, user_b)
    for name, url, *_rest in _routes(files):
        assert client.get(url, HTTP_HOST=domain_b.host).status_code == 404, name
    _login(client, user_a)
    for name, url, *_rest in _routes(files):
        assert client.get(url, HTTP_HOST=domain_a.host).status_code == 200, name
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert StaffFileAccess.objects.filter(staff=staff_a).count() == len(_routes(files))
    # The new table's own policy: under B's GUC, _base_manager (no ORM tenant filter) sees
    # none of A's rows.
    with tenant_transaction(agency_b.id):
        assert not StaffFileAccess._base_manager.exists()


# --- refused before the rule: no active membership on this host ---


def test_a_deactivated_staff_member_is_refused_everywhere_and_nothing_is_recorded(
    client, agency_a, domain_a, files
):
    user, staff = _staff(agency_a)
    Membership._base_manager.filter(id=staff.id).update(active=False)
    client.force_login(user)
    for name, url, *_rest in _routes(files):
        assert client.get(url, HTTP_HOST=domain_a.host).status_code in (403, 404), name
    assert not ACCESS.exists()


def test_staff_of_agency_a_on_agency_bs_host_are_refused_and_nothing_is_recorded(
    client, agency_a, agency_b, domain_a, domain_b, files
):
    """A's staff hold no membership in B: the tenancy middleware refuses them on B's host,
    for B's own student's ids and for A's alike."""
    user, _staff_a = _staff(agency_a)
    _login(client, user)
    for name, url, *_rest in _routes(files):
        assert client.get(url, HTTP_HOST=domain_b.host).status_code in (403, 404), name
    assert not ACCESS.exists()
