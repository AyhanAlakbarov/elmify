"""The bench's door: a platform operator with MFA, on a device token."""

import json

import pytest
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.tenancy.context import tenant_scope
from tests.conftest import verify_mfa_session
from tests.portals.test_ext_api import _pair

pytestmark = pytest.mark.django_db

HTML = (
    "<!doctype html><html><body><p>Welcome, Orkhan Abdullayev</p>"
    "<form><label for='gn'>First name</label><input id='gn'></form></body></html>"
)
SNAP = {"page_url": "https://apply.example.edu/p",
        "controls": [{"selector": "#gn", "tag": "input", "label": "First name"}]}


def _get(client, domain, token: str, path: str):
    return client.get(path, HTTP_HOST=domain.host, HTTP_AUTHORIZATION=f"Bearer {token}")


def _record(client, domain, token: str, form_id, body: dict[str, object]):
    return client.post(
        f"/ext/bench/portal-forms/{form_id}/pages", data=json.dumps(body),
        content_type="application/json", HTTP_HOST=domain.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_a_student_is_not_a_bench_operator(
    client, agency_a, domain_a, membership_a, portal_form
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _get(client, domain_a, token, "/ext/bench/whoami").json() == {"operator": False}
    assert _get(client, domain_a, token, "/ext/bench/portal-forms").status_code == 403
    response = _record(client, domain_a, token, portal_form.id,
                       {"page_kind": "FORM", "snapshot": SNAP, "html": HTML})
    assert response.status_code == 403


def test_an_operator_without_mfa_or_outside_the_platform_is_not_one(
    operator, platform, agency_a, django_user_model
) -> None:
    from apps.portals.bench import is_bench_operator
    from apps.tenancy.models import Membership

    assert is_bench_operator(operator)
    TOTPDevice.objects.filter(user=operator.user).delete()
    assert not is_bench_operator(operator)
    user = django_user_model.objects.create_user(username="padmin")
    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    with tenant_scope(agency_a.id):
        ordinary = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.PLATFORM_ADMIN
        )
    assert not is_bench_operator(ordinary)  # PLATFORM_ADMIN of an ordinary agency
    owner_user = django_user_model.objects.create_user(username="powner")
    TOTPDevice.objects.create(user=owner_user, name="default", confirmed=True)
    with tenant_scope(platform.id):
        owner = Membership.objects.create(
            tenant=platform, user=owner_user, role=Membership.Role.OWNER
        )
    assert not is_bench_operator(owner)  # an agency role, even on the platform
    TOTPDevice.objects.create(user=operator.user, name="default", confirmed=True)
    operator.active = False
    assert not is_bench_operator(operator)


def test_the_operator_pairs_from_the_platform_dashboard(client, platform_domain, operator) -> None:
    client.force_login(operator.user)
    verify_mfa_session(client, operator.user)
    response = client.post("/api/extension/pairing-code", HTTP_HOST=platform_domain.host)
    assert response.status_code == 201 and response.json()["code"]


def test_an_unverified_operator_session_cannot_pair(client, platform_domain, operator) -> None:
    client.force_login(operator.user)
    response = client.post("/api/extension/pairing-code", HTTP_HOST=platform_domain.host)
    assert response.status_code == 403


def test_the_operator_sees_the_portal_forms(
    client, platform_domain, operator_token, portal_form
) -> None:
    assert _get(client, platform_domain, operator_token, "/ext/bench/whoami").json() == {
        "operator": True,
    }
    forms = _get(client, platform_domain, operator_token, "/ext/bench/portal-forms").json()
    assert {"id": str(portal_form.id), "portal_host": "apply.example.edu",
            "form_url": "https://apply.example.edu/apply"} in forms["forms"]


def test_a_recording_is_stored_with_the_greeting_redacted(
    client, platform_domain, operator_token, portal_form, bench_store
) -> None:
    from apps.portals.models import PageRecord

    response = _record(client, platform_domain, operator_token, portal_form.id, {
        "page_kind": "SIGNUP", "password_rules": "At least 12 characters, one digit",
        "snapshot": SNAP, "html": HTML,
    })
    assert response.status_code == 201
    record = PageRecord.objects.get(id=response.json()["record_id"])
    assert (record.source, record.page_kind, record.learned_by_tenant_id, record.step) == (
        "BENCH_WALK", "SIGNUP", None, 1,
    )
    assert record.password_rules.startswith("At least 12")
    stored = bench_store.get(record.html_key).decode()
    assert "Orkhan" not in stored and "Welcome, ■" in stored and 'id="gn"' in stored
    assert record.snapshot["page_url"] == "https://apply.example.edu"


def test_a_first_name_greeting_and_an_option_are_redacted_not_refused(
    client, platform_domain, operator_token, portal_form, bench_store
) -> None:
    from apps.portals.models import PageRecord

    html = HTML.replace("Welcome, Orkhan Abdullayev", "Hi Orkhan!").replace(
        "</form>", "<select><option value='Orkhan'>Orkhan</option></select></form>"
    )
    response = _record(client, platform_domain, operator_token, portal_form.id,
                       {"page_kind": "FORM", "snapshot": SNAP, "html": html})
    assert response.status_code == 201
    record = PageRecord.objects.get(id=response.json()["record_id"])
    stored = bench_store.get(record.html_key).decode()
    assert "Orkhan" not in stored and "Hi ■!" in stored
    assert '<option value="■">■</option>' in stored


def test_the_step_counts_the_current_walk_only(
    client, platform_domain, operator_token, portal_form, bench_store
) -> None:
    from apps.portals.models import PageRecord

    body = {"page_kind": "FORM", "snapshot": SNAP, "html": HTML}
    first = _record(client, platform_domain, operator_token, portal_form.id, body).json()
    second = _record(client, platform_domain, operator_token, portal_form.id, body).json()
    assert PageRecord.objects.get(id=second["record_id"]).step == 2
    PageRecord.objects.filter(id__in=[first["record_id"], second["record_id"]]).update(
        superseded_at=timezone.now()
    )
    third = _record(client, platform_domain, operator_token, portal_form.id, body).json()
    assert PageRecord.objects.get(id=third["record_id"]).step == 1


@pytest.mark.parametrize("html", [
    HTML.replace("<input id='gn'>", "<input id='gn' value='Orkhan Abdullayev'>"),
    HTML.replace("<input id='gn'>", "<input id='gn' value='Orkhan'>"),
    HTML.replace("<input id='gn'>", "<textarea>owner@example.org</textarea>"),
    HTML.replace("<input id='gn'>", "<input id='gn' value='1999-01-01'>"),
    HTML.replace("<input id='gn'>", "<textarea>anything at all</textarea>"),
    "<html><body>" + "x" * 1_500_001 + "</body></html>",
    "",
    "   ",
], ids=["full-name-value", "first-name-value", "textarea-email", "any-value",
    "any-textarea", "too-large", "empty", "blank"])
def test_a_recording_with_a_value_in_a_control_or_too_large_is_refused(
    client, platform_domain, operator_token, portal_form, bench_store, html: str
) -> None:
    from apps.portals.models import PageRecord

    response = _record(client, platform_domain, operator_token, portal_form.id,
                       {"page_kind": "FORM", "snapshot": SNAP, "html": html})
    assert (response.status_code, response.json()["error"]) == (400, "invalid_recording")
    assert not PageRecord.objects.exists()


def test_a_failed_upload_leaves_no_row(operator, platform, portal_form, monkeypatch) -> None:
    from apps.portals import bench
    from apps.portals.models import PageRecord
    from apps.portals.snapshot import FormSnapshot

    class _Down:
        def put(self, key: str, body: bytes) -> str:
            raise OSError("store unavailable")

    monkeypatch.setattr(bench, "_store", lambda: _Down())
    with pytest.raises(OSError):
        bench.store_bench_page(
            portal_form, page_kind="FORM", password_rules="",
            snapshot=FormSnapshot.model_validate(SNAP), html=HTML,
            forbidden_values=["Orkhan"], step=1, actor=operator,
        )
    assert not PageRecord.objects.exists()


def test_the_forbidden_values_carry_the_operators_names(operator, platform) -> None:
    from apps.portals.bench import operator_forbidden_values
    from apps.tenancy.db import tenant_transaction

    with tenant_scope(platform.id), tenant_transaction(platform.id):
        values = operator_forbidden_values(operator)
    assert {"Orkhan", "Abdullayev", "Orkhan Abdullayev", "owner@example.org"} <= set(values)


def test_a_failed_audit_insert_rolls_the_row_back(
    client, platform_domain, operator_token, portal_form, bench_store, monkeypatch
) -> None:
    from apps.funding.models import AuditEvent
    from apps.portals.models import PageRecord

    def _fail(**kwargs: object) -> None:
        raise RuntimeError("audit insert failed")

    monkeypatch.setattr(AuditEvent.objects, "create", _fail)
    client.raise_request_exception = False
    response = _record(client, platform_domain, operator_token, portal_form.id,
                       {"page_kind": "FORM", "snapshot": SNAP, "html": HTML})
    assert response.status_code == 500
    assert not PageRecord.objects.exists()


def test_the_server_strips_scripts_and_handlers_whatever_the_client_did(
    operator, platform, portal_form, bench_store
) -> None:
    from apps.portals import bench
    from apps.portals.snapshot import FormSnapshot
    from apps.tenancy.db import tenant_transaction

    html = (
        "<!doctype html><html><head><meta http-equiv='refresh' content='0;url=//x'>"
        "<base href='//x/'><script>steal()</script></head><body>"
        "<img src='a.png' onerror='steal()'><iframe src='//x'></iframe>"
        "<select><option selected>A</option></select><input type='checkbox' checked>"
        "<label>First name</label></body></html>"
    )
    with tenant_scope(platform.id), tenant_transaction(platform.id):
        record = bench.store_bench_page(
            portal_form, page_kind="FORM", password_rules="",
            snapshot=FormSnapshot.model_validate(SNAP), html=html,
            forbidden_values=["Orkhan"], step=1, actor=operator,
        )
    stored = bench_store.get(record.html_key).decode().lower()
    for gone in ("script", "onerror", "iframe", "<base", "http-equiv", "selected", "checked"):
        assert gone not in stored
    assert "first name" in stored


def test_an_operator_device_reaches_no_students_file_or_packet(
    client, platform, platform_domain, operator_token, django_user_model, monkeypatch, fake_store
) -> None:
    """Every ext route is scoped to `pairing.membership`: an operator's device names its own
    membership, so a student of the same (platform) agency, whose upload is named for them
    by a live action and by a packet, is a 404 to it -- the file and the packet alike."""
    from apps.documents import storage
    from apps.portals.models import ApplicationStep
    from apps.tenancy.models import Membership
    from tests.portals.test_ext_document import _named, _promoted

    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    user = django_user_model.objects.create_user(username="platform-student")
    with tenant_scope(platform.id):
        student = Membership.objects.create(
            tenant=platform, user=user, role=Membership.Role.STUDENT
        )
        upload = _promoted(platform, student, fake_store)
        application = _named(platform, student, upload)
        ApplicationStep.objects.create(
            tenant=platform, application=application, sequence=1, kind="PACKET",
            detail={"uploads": [{"upload_id": str(upload.id)}]},
        )
    file = f"/ext/documents/{upload.id}"
    assert _get(client, platform_domain, operator_token, file).status_code == 404
    packet = f"/ext/applications/{application.id}/packet"
    assert _get(client, platform_domain, operator_token, packet).status_code == 404
    # The control: the student's own device is served the same file.
    own = _pair(client, platform, student, platform_domain, installation="install-2")
    assert _get(client, platform_domain, own, file).status_code == 200
