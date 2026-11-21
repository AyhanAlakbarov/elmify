"""The staff file access records can be read: the owner console list and the
`staff_file_views` command (owner decision 2026-10-11)."""

from datetime import UTC, datetime
from io import StringIO
from unittest import mock

import pytest
from django.core.management import CommandError, call_command

from apps.audit.models import StaffFileAccess
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.audit.test_deletion_views import owner_client  # noqa: F401 -- a fixture

pytestmark = pytest.mark.django_db

LINE = "StaffFileView action=view tenant=T1 staff=S1 student=U1 document=DRAFT_CV:D1"


def _access(agency, staff, student, action="VIEW", kind="DRAFT_CV"):
    from uuid import uuid4

    with tenant_scope(agency.id):
        return StaffFileAccess.objects.create(
            staff=staff, student=student, action=action, document_kind=kind, document_id=uuid4()
        )


def test_the_owner_console_lists_staff_views_without_a_student_name(
    owner_client, agency_a, domain_a, membership_a, django_user_model  # noqa: F811
):
    user = django_user_model.objects.create_user(username="elmify-staff")
    with tenant_scope(agency_a.id):
        staff = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.PLATFORM_ADMIN
        )
    _access(agency_a, staff, membership_a, "DOWNLOAD", "UPLOAD_PASSPORT")

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    [row] = response.context["staff_views"]
    assert row["staff_name"] == "elmify-staff"
    assert row["action"] == "DOWNLOAD" and row["document_kind"] == "UPLOAD_PASSPORT"
    assert "accessed_at" in row
    assert "student" not in " ".join(row) and membership_a.id not in row.values()


def test_the_console_list_is_this_agencys_only(
    owner_client, agency_a, agency_b, domain_a, membership_a, user_b, django_user_model  # noqa: F811
):
    with tenant_scope(agency_b.id):
        student_b = Membership.objects.create(
            tenant=agency_b, user=user_b, role=Membership.Role.STUDENT
        )
        staff_b = Membership.objects.create(
            tenant=agency_b,
            user=django_user_model.objects.create_user(username="staff-b"),
            role=Membership.Role.PLATFORM_ADMIN,
        )
    _access(agency_b, staff_b, student_b)

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    assert list(response.context["staff_views"]) == []


def _run(*args):
    out = StringIO()
    call_command("staff_file_views", *args, stdout=out)
    return out.getvalue().splitlines()


def test_the_command_prints_one_line_per_access_from_a_file(tmp_path):
    f = tmp_path / "web.log"
    f.write_text(f"2026-10-11T10:00:00 INFO x {LINE}\nunrelated line\n{LINE}\n")

    # An explicit --since: the default 1d window would age the dated line out
    # a day after it was written.
    lines = _run("--file", str(f), "--since", "2026-10-01")

    assert len(lines) == 2
    assert all(
        "view" in line and "T1" in line and "S1" in line and "U1" in line and "DRAFT_CV:D1" in line
        for line in lines
    )
    assert lines[0].startswith("2026-10-11T10:00:00")


def test_the_command_reads_cloudwatch_since_a_window():
    client = mock.Mock()
    client.get_paginator.return_value.paginate.return_value = [
        {"events": [{"timestamp": 1_760_176_800_000, "message": LINE}]}
    ]
    with mock.patch("boto3.client", return_value=client), mock.patch.dict(
        "os.environ", {"WEB_LOG_GROUP": "/elmify/app/x/web"}
    ):
        lines = _run("--since", "7d")

    kwargs = client.get_paginator.return_value.paginate.call_args.kwargs
    assert kwargs["logGroupName"] == "/elmify/app/x/web"
    assert kwargs["filterPattern"] == '"StaffFileView"'
    assert lines == [
        f"{datetime.fromtimestamp(1_760_176_800, UTC).isoformat()} action=view tenant=T1 "
        "staff=S1 student=U1 document=DRAFT_CV:D1"
    ]


def test_an_unreadable_since_is_refused():
    with pytest.raises(CommandError):
        _run("--since", "yesterday", "--file", "/dev/null")


def test_since_keeps_an_explicit_offset():
    from apps.audit.management.commands.staff_file_views import _start

    assert _start("2026-10-11T10:00:00+04:00") == datetime(2026, 10, 11, 6, 0, tzinfo=UTC)
    assert _start("2026-10-11") == datetime(2026, 10, 11, tzinfo=UTC)


def test_file_lines_older_than_since_are_dropped(tmp_path):
    f = tmp_path / "web.log"
    f.write_text(f"2026-10-01T10:00:00 INFO {LINE}\n2026-10-11T10:00:00 INFO {LINE}\n")

    assert len(_run("--since", "2026-10-05", "--file", str(f))) == 1


def test_a_file_line_starting_like_a_window_is_not_a_timestamp(tmp_path):
    """A line's first token is read only as an ISO timestamp: "1d" or "12h" is no
    timestamp, so the line is kept, never read as "one day ago" and filtered."""
    f = tmp_path / "web.log"
    f.write_text(f"1d {LINE}\n12h INFO {LINE}\n2026-10-11T10:00:00 INFO {LINE}\n")

    lines = _run("--since", "2099-01-01", "--file", str(f))

    assert [line.split()[0] for line in lines] == ["1d", "12h"]


@pytest.fixture
def real_templates(settings):
    settings.TEMPLATES = [
        {**settings.TEMPLATES[0], "DIRS": [settings.BASE_DIR / "templates"]}
    ]


def test_the_real_console_renders_all_four_lists_and_no_student_name(
    real_templates, owner_client, agency_a, domain_a, membership_a, user_a, django_user_model  # noqa: F811
):
    from apps.audit.models import DeletionRequest

    user = django_user_model.objects.create_user(username="elmify-staff")
    with tenant_scope(agency_a.id):
        staff = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.PLATFORM_ADMIN
        )
        held = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="RETENTION_REVIEW",
            review_reason="APPLICATIONS_IN_FLIGHT",
        )
    _access(agency_a, staff, membership_a, "DOWNLOAD", "UPLOAD_PASSPORT")

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    html = response.content.decode()
    assert response.status_code == 200
    assert "UPLOAD_PASSPORT" in html and "DOWNLOAD" in html and "elmify-staff" in html
    assert f"/owner/deletions/{held.id}/release/" in html
    assert f"/owner/deletions/{held.id}/deny/" in html
    assert user_a.get_username() not in html
