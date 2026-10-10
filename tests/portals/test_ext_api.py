"""The extension API's door.

Bearer token only. A signed-in browser session is not an extension, and the one
thing this decorator must never do is accept one -- a cookie-authenticated
route with @csrf_exempt is a CSRF hole, and every route here is csrf_exempt
because none of them is reached by a cookie.
"""

import json
from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

PAIR = "/ext/pair"


def _pair(client, agency, membership, domain, installation="install-1"):
    from apps.portals import pairing as pairing_module

    with tenant_scope(agency.id):
        code = pairing_module.issue_pairing_code(membership)
    response = client.post(
        PAIR,
        data=json.dumps({"code": code, "installation_id": installation}),
        content_type="application/json",
        HTTP_HOST=domain.host,
    )
    assert response.status_code == 201, response.content
    return response.json()["token"]


def test_the_dashboard_mints_a_code_for_its_own_session(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    client.force_login(user_a)

    response = client.post("/api/extension/pairing-code", HTTP_HOST=domain_a.host)

    assert response.status_code == 201
    assert response.json()["code"]


def test_minting_a_code_needs_a_signed_in_student(client, domain_a) -> None:
    response = client.post("/api/extension/pairing-code", HTTP_HOST=domain_a.host)
    assert response.status_code == 401


def test_a_code_becomes_a_token(client, agency_a, domain_a, membership_a, user_a) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    assert token


def test_a_bad_code_is_refused(client, domain_a) -> None:
    response = client.post(
        PAIR,
        data=json.dumps({"code": "nope", "installation_id": "install-1"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_code"}


def test_a_session_cookie_is_not_a_device_token(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    """The load-bearing negative. These routes are csrf_exempt, so if the
    decorator ever fell back to request.user every one of them would become a
    CSRF hole that any page on the internet could drive."""
    client.force_login(user_a)

    response = client.delete(PAIR, HTTP_HOST=domain_a.host)

    assert response.status_code == 401
    assert response.json() == {"error": "pairing_required"}


def test_a_revoked_token_stops_working(client, agency_a, domain_a, membership_a, user_a) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)

    revoked = client.delete(PAIR, HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}")
    again = client.delete(PAIR, HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}")

    assert revoked.status_code == 204
    assert again.status_code == 401


def test_a_token_from_another_tenant_s_host_is_refused(
    client, agency_a, domain_a, domain_b, membership_a, user_a
) -> None:
    """The token identifies the membership; the host identifies the tenant.
    Presenting one tenant's token on another tenant's host must not
    authenticate -- otherwise the device token, not the host, would be deciding
    which tenant's rows are in scope."""
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.delete(PAIR, HTTP_HOST=domain_b.host, HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code == 401


def _application(agency, student, *, entries=None, posture=None):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"ext-{uuid4()}",
        form_url="https://apply.example.edu/personal",
        **({"terms_posture": posture} if posture else {}),
    )
    if entries is not None:
        FieldMap.objects.create(portal_form=form, version=1, entries=entries)
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


ENTRIES = [
    {
        "profile_field": "identity.full_name",
        "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]},
    }
]


def test_the_packet_route_returns_what_the_extension_types(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == [
        {
            "selector": "#name",
            "method": "fill",
            "value": "Ada Byron",
            "profile_field": "identity.full_name",
        }
    ]
    assert body["form_url"] == "https://apply.example.edu/personal"


def test_the_packet_route_reads_no_catalogue_table(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch, program_factory
) -> None:
    """ext_api.packet is a web request, and the web role holds no grant on the
    catalogue. A rendered CV attached to the application's programme is the
    case that used to join funding_program through resolve_variant."""
    from apps.documents.models import DocumentDraft
    from apps.portals import packets
    from tests.conftest import reads_no_catalogue

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    program = program_factory()
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
        application.program_id = program.id
        application.save(update_fields=["program_id"])
        draft = DocumentDraft.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=DocumentDraft.Kind.CV,
            version=1,
            content={},
            status=DocumentDraft.Status.APPROVED,
            programme=program,
            rendered_filename="cv-german-tabular.pdf",
        )
    token = _pair(client, agency_a, membership_a, domain_a)

    with reads_no_catalogue():
        response = client.get(
            f"/ext/applications/{application.id}/packet",
            HTTP_HOST=domain_a.host,
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    assert response.status_code == 200
    assert [d["draft_id"] for d in response.json()["documents"]] == [str(draft.id)]


def test_a_refusal_carries_its_reason_and_the_right_status(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    from apps.portals import packets
    from apps.portals.models import PortalForm

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a,
            membership_a,
            entries=ENTRIES,
            posture=PortalForm.TermsPosture.PROHIBITS_AUTOMATION,
        )
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 409
    assert response.json() == {"error": "automation_prohibited"}


def test_a_portal_with_no_map_asks_for_a_snapshot(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    """424, not 404: the application is fine and the extension's next move is
    to send a snapshot, which is a different instruction from 'no such thing'."""
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 424
    assert response.json() == {
        "error": "no_field_map",
        "portal_form_id": str(application.portal_form_id),
        # The page the map is FOR. Without it the content script cannot check
        # the origin before it builds a first-encounter snapshot -- it learns
        # form_url from the packet, and on this path there is no packet. So a
        # snapshot of whatever page the student happened to be on was posted
        # to the server, and the origin check ran one step too late.
        "form_url": application.portal_form.form_url,
    }


def test_another_student_s_application_is_404(
    client, agency_a, domain_a, membership_a, user_a, user_b
) -> None:
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        application = _application(agency_a, other, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 404


def test_the_first_packet_on_a_portal_asks_a_consultant_to_look(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    """§5.2's first-application review. The retiring server tier ran this at the
    end of prepare_application; nothing else does, and no other test goes red
    when it disappears."""
    from apps.concierge.models import RoadmapItem
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
        assert application.portal_form.review_required is True
    token = _pair(client, agency_a, membership_a, domain_a)

    client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    with tenant_scope(agency_a.id):
        assert RoadmapItem.objects.filter(student=membership_a).exists()


SNAPSHOT_BODY = {
    "page_url": "https://apply.example.edu/personal",
    "controls": [
        {
            "selector": "#name",
            "tag": "input",
            "type": "text",
            "name": "applicant_name",
            "id": "name",
            "label": "Full name",
            "placeholder": "",
            "options": [],
            "required": True,
        }
    ],
}


def test_a_snapshot_becomes_a_field_map(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    from apps.portals import ext_api
    from apps.portals.models import FieldMap

    monkeypatch.setattr(
        ext_api, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    monkeypatch.setattr(
        ext_api,
        "learn_from_snapshot",
        lambda form, snapshot, **kwargs: FieldMap.objects.create(
            portal_form=form,
            version=1,
            entries=[
                {
                    "profile_field": "identity.full_name",
                    "action": {
                        "selector": "#name",
                        "method": "fill",
                        "arguments": ["%value%"],
                    },
                }
            ],
        ),
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        f"/ext/portal-forms/{application.portal_form_id}/snapshot",
        data=json.dumps(SNAPSHOT_BODY),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 201
    assert response.json()["field_map_version"] == 1


def test_a_snapshot_with_a_value_key_is_refused_before_anything_is_learned(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    from apps.portals import ext_api

    monkeypatch.setattr(ext_api, "verified_values", lambda student: {})

    def _never(*args, **kwargs):
        raise AssertionError("the learn pass must not be reached")

    monkeypatch.setattr(ext_api, "learn_from_snapshot", _never)
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    body = {
        "page_url": "https://apply.example.edu/personal",
        "controls": [dict(SNAPSHOT_BODY["controls"][0], value="Ada Byron")],
    }

    response = client.post(
        f"/ext/portal-forms/{application.portal_form_id}/snapshot",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_snapshot"}


def test_a_malformed_page_url_is_refused_by_the_view_not_a_500(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    """The real (unstubbed) learn_from_snapshot must turn a page_url that
    urlsplit cannot parse into the view's ordinary 400, not an unhandled
    ValueError."""
    from apps.portals import ext_api

    monkeypatch.setattr(
        ext_api, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    body = {**SNAPSHOT_BODY, "page_url": "https://[bad-ipv6/path"}

    response = client.post(
        f"/ext/portal-forms/{application.portal_form_id}/snapshot",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_snapshot"}


def test_a_portal_form_this_student_has_no_application_for_is_404(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    """A shared table addressed by id is still not a public one: without this
    check any paired student could learn a map for any portal in the platform,
    which is a write to shared data on an unowned object."""
    from apps.portals.models import PortalForm

    with tenant_scope(agency_a.id):
        other_form = PortalForm.objects.create(
            portal_host="elsewhere.example.edu", form_key=f"other-{uuid4()}"
        )
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        f"/ext/portal-forms/{other_form.id}/snapshot",
        data=json.dumps(SNAPSHOT_BODY),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 404


def _post_event(client, application, token, host, body):
    return client.post(
        f"/ext/applications/{application.id}/events",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_a_fill_event_lands_in_the_trail(client, agency_a, domain_a, membership_a, user_a) -> None:
    from apps.portals.models import ApplicationStep

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _post_event(
        client,
        application,
        token,
        domain_a.host,
        {"kind": "FILL", "detail": {"filled": ["#name"], "page": 1}},
    )

    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        step = ApplicationStep.objects.get(application=application, kind="FILL")
    assert step.detail["filled"] == ["#name"]


def test_a_read_back_mismatch_escalates_a_portal_error(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    """Decision 7: a mismatch is reported, not trusted, and it still escalates
    PORTAL_ERROR and is still not retried."""
    from apps.concierge.models import RoadmapItem

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    _post_event(
        client,
        application,
        token,
        domain_a.host,
        {"kind": "READ_BACK", "detail": {"mismatches": ["#name"]}},
    )

    with tenant_scope(agency_a.id):
        application.refresh_from_db()
        assert application.state == "BLOCKED_PORTAL_ERROR"
        assert RoadmapItem.objects.filter(student=membership_a).exists()


def test_a_clean_read_back_escalates_nothing(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    from apps.concierge.models import RoadmapItem

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    _post_event(
        client,
        application,
        token,
        domain_a.host,
        {"kind": "READ_BACK", "detail": {"mismatches": []}},
    )

    with tenant_scope(agency_a.id):
        application.refresh_from_db()
        assert application.state == "PREPARING"
        assert not RoadmapItem.objects.filter(student=membership_a).exists()


def test_a_challenge_is_recorded_and_blocks_nothing(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    """Decision 8: a challenge is the student's own act. They are already there;
    a counselor task would be a message to someone who cannot help."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.models import ApplicationStep

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    _post_event(
        client,
        application,
        token,
        domain_a.host,
        {"kind": "CHALLENGE", "detail": {"marker": "captcha"}},
    )

    with tenant_scope(agency_a.id):
        application.refresh_from_db()
        assert application.state == "PREPARING"
        assert ApplicationStep.objects.filter(application=application, kind="CHALLENGE").exists()
        assert not RoadmapItem.objects.filter(student=membership_a).exists()


def test_submitted_moves_the_state_and_stores_the_evidence(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    import base64

    from apps.portals import ext_api

    stored = {}
    monkeypatch.setattr(
        ext_api, "store_submission_image", lambda **kwargs: stored.update(kwargs) or "a-key"
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)
    image = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()

    response = _post_event(
        client,
        application,
        token,
        domain_a.host,
        {"kind": "SUBMITTED", "detail": {"confirmation_text": "Thank you"}, "image": image},
    )

    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
    assert application.state == "SUBMITTED"
    assert stored["student_id"] == membership_a.id


def test_an_unknown_kind_is_refused(client, agency_a, domain_a, membership_a, user_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _post_event(
        client, application, token, domain_a.host, {"kind": "DELETE_EVERYTHING", "detail": {}}
    )

    assert response.status_code == 400
    assert response.json() == {"error": "unknown_kind"}


def test_an_oversized_image_is_refused(client, agency_a, domain_a, membership_a, user_a) -> None:
    import base64

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _post_event(
        client,
        application,
        token,
        domain_a.host,
        {
            "kind": "SUBMITTED",
            "detail": {},
            "image": base64.b64encode(b"0" * (1_500_001)).decode(),
        },
    )

    assert response.status_code == 413


def test_the_image_cap_fires_before_django_s() -> None:
    """A cap above DATA_UPLOAD_MAX_MEMORY_SIZE is dead code: Django rejects the
    body first, with an HTML 400 no JSON client can read. Measured -- the first
    cap written here was 2 MB and produced exactly that."""
    from django.conf import settings

    from apps.portals.ext_api import _MAX_IMAGE_BYTES

    on_the_wire = 4 * ((_MAX_IMAGE_BYTES + 2) // 3)
    assert on_the_wire < settings.DATA_UPLOAD_MAX_MEMORY_SIZE


def test_the_actions_route_delivers_this_student_s_actions_once(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    from apps.portals.actions import queue_action
    from apps.portals.models import DeviceAction

    with tenant_scope(agency_a.id):
        queue_action(membership_a, DeviceAction.Kind.TYPE_CODE, {"code": "123456"})
    token = _pair(client, agency_a, membership_a, domain_a)

    first = client.get(
        "/ext/actions", HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    second = client.get(
        "/ext/actions", HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}"
    )

    assert [a["payload"] for a in first.json()["actions"]] == [{"code": "123456"}]
    assert second.json()["actions"] == []


def test_reporting_a_result_closes_the_action(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    from apps.portals.actions import queue_action
    from apps.portals.models import DeviceAction

    with tenant_scope(agency_a.id):
        action = queue_action(membership_a, DeviceAction.Kind.TYPE_CODE, {"code": "123456"})
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        f"/ext/actions/{action.id}/result",
        data=json.dumps({"ok": True, "detail": {"typed": True}}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 200
    with tenant_scope(agency_a.id):
        action.refresh_from_db()
    assert action.completed_at is not None
    assert action.payload == {}


def test_another_student_s_action_is_404(
    client, agency_a, domain_a, membership_a, user_a, user_b
) -> None:
    from apps.portals.actions import queue_action
    from apps.portals.models import DeviceAction
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        action = queue_action(other, DeviceAction.Kind.TYPE_CODE, {"code": "123456"})
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        f"/ext/actions/{action.id}/result",
        data=json.dumps({"ok": True, "detail": {}}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 404


def test_a_status_read_records_what_the_portal_showed(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    from apps.portals.models import ApplicationStep

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        f"/ext/applications/{application.id}/status",
        data=json.dumps(
            {
                "portal_state": "Under review",
                "application_number": "TUM-2027-1184",
                "document_requests": ["Certified transcript"],
            }
        ),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        step = ApplicationStep.objects.get(application=application, kind="STATUS")
    assert step.detail["application_number"] == "TUM-2027-1184"


def test_a_status_read_never_moves_the_state_by_itself(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    """The page says what the portal thinks. Application.State is ours, and a
    string scraped off a third-party page is not allowed to set it -- CONFIRMED
    means something specific in this codebase and a portal's wording does not
    map onto it."""
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    client.post(
        f"/ext/applications/{application.id}/status",
        data=json.dumps({"portal_state": "CONFIRMED", "document_requests": []}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    with tenant_scope(agency_a.id):
        application.refresh_from_db()
    assert application.state == "PREPARING"


def test_an_oversized_status_payload_is_refused(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        f"/ext/applications/{application.id}/status",
        data=json.dumps({"portal_state": "x" * 5000, "document_requests": []}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_status"}


def test_a_deactivated_membership_s_token_stops_working(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    """advance_deletion sets active=False as THE mechanism that cuts an erased
    student off. The session path enforces it in current_membership and in
    TenantMembershipMiddleware, both inside `if request.user.is_authenticated`
    -- so a device token runs past both unless authenticate_device checks it."""
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    with tenant_scope(agency_a.id):
        membership_a.active = False
        membership_a.save(update_fields=["active"])

    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 401
    assert response.json() == {"error": "pairing_required"}


def test_a_pending_erasure_locks_the_extension_out_too(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    """The student is locked out of every dashboard screen the moment they ask.
    Before this, their extension kept being handed packets carrying their own
    verified facts in plaintext for the whole thirty-day statutory window."""
    from apps.audit.models import DeletionRequest

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)

    # The row alone, without going through request_deletion: this asserts the
    # decorator's own guard, not the revoke that now also fires.
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="APPROVED", reason="PRIVACY"
        )

    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 403
    assert response.json() == {"error": "account_locked"}


def test_a_stopped_student_is_refused_by_the_extension_api(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    from datetime import UTC, datetime

    from apps.privacy import requests as privacy_requests

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        privacy_requests.record(
            membership_a,
            kind="withdrawal",
            channel="email",
            received_at=datetime(2026, 10, 2, tzinfo=UTC),
        )

    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 403
    assert response.json() == {"error": "processing_stopped"}


def test_a_student_who_must_reaccept_is_refused_by_the_extension_api(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    from apps.privacy import documents

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=ENTRIES)
    token = _pair(client, agency_a, membership_a, domain_a)
    for kind in documents.KINDS:
        documents.publish(kind, "en", f"{kind} v1", material=True)

    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 403
    assert response.json() == {"error": "acceptance_required"}


def test_requesting_erasure_revokes_every_paired_installation(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    """Revoked at request time, not at EXECUTED. DELETE /ext/pair authenticates
    with the very token you would be revoking, so a device the student no
    longer holds could not otherwise be revoked at all."""
    from apps.audit.console import request_deletion
    from apps.portals.models import ExtensionPairing

    token = _pair(client, agency_a, membership_a, domain_a)

    with tenant_scope(agency_a.id):
        request_deletion(student=membership_a, reason="PRIVACY")
        pairing = ExtensionPairing.objects.get(membership=membership_a)

    assert pairing.revoked_at is not None
    assert pairing.token_hash == ""

    response = client.get(
        "/ext/actions", HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 401


def test_a_snapshot_records_who_sent_it(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    """A snapshot rewrites the field map for a whole agency, and until this row
    existed it left no trace of which membership sent it.

    Attribution, not prevention: the server has no page to check the selectors
    against, so a map that misdirects a value is caught by the extension that
    can see the real page (plan 3). What this row buys is the ability to answer
    'who published this map' afterwards, which the trail could not.
    """
    from apps.funding.models import AuditEvent
    from apps.portals import ext_api
    from apps.portals.models import FieldMap

    monkeypatch.setattr(
        ext_api, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    monkeypatch.setattr(
        ext_api,
        "learn_from_snapshot",
        lambda form, snapshot, **kwargs: FieldMap.objects.create(
            portal_form=form,
            version=1,
            learned_by_tenant_id=kwargs["tenant_id"],
            entries=[
                {
                    "profile_field": "identity.full_name",
                    "action": {
                        "selector": "#name",
                        "method": "fill",
                        "arguments": ["%value%"],
                    },
                }
            ],
        ),
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        f"/ext/portal-forms/{application.portal_form_id}/snapshot",
        data=json.dumps(SNAPSHOT_BODY),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        event = AuditEvent.objects.get(event="portal.field_map_learned")
        learned = FieldMap.objects.get(portal_form_id=application.portal_form_id)
    assert event.actor_id == membership_a.id
    assert event.actor_kind == AuditEvent.ActorKind.HUMAN
    assert event.object_id == learned.id


def test_a_snapshot_offers_the_portal_address_and_forbids_it(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    from apps.portals import ext_api
    from apps.portals.models import FieldMap

    seen = {}

    def _learn(form, snapshot, **kwargs):
        seen.update(kwargs)
        return FieldMap.objects.create(portal_form=form, version=1, entries=[])

    monkeypatch.setattr(ext_api, "verified_values", lambda student: {})
    monkeypatch.setattr(ext_api, "learn_from_snapshot", _learn)
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        f"/ext/portal-forms/{application.portal_form_id}/snapshot",
        data=json.dumps(SNAPSHOT_BODY),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 201
    assert seen["optional_fields"] == ("contact.email",)
    assert "leyla.apply@outlook.com" in seen["forbidden_values"]
    assert any(value.startswith("leyla.apply+") for value in seen["forbidden_values"])


def test_a_snapshot_offers_the_email_field_even_when_this_student_has_no_address(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    """T5 (final review): the learned map is the agency's. If the first
    student to send a snapshot had no address, the map would never carry the
    email field for anyone, so it is always offered (as optional). This
    student then gets missing_fact from the packet -- test_tags pins that."""
    from apps.portals import ext_api
    from apps.portals.models import FieldMap

    seen = {}

    def _learn(form, snapshot, **kwargs):
        seen.update(kwargs)
        return FieldMap.objects.create(portal_form=form, version=1, entries=[])

    monkeypatch.setattr(ext_api, "verified_values", lambda student: {})
    monkeypatch.setattr(ext_api, "learn_from_snapshot", _learn)
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        f"/ext/portal-forms/{application.portal_form_id}/snapshot",
        data=json.dumps(SNAPSHOT_BODY),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 201
    assert seen["optional_fields"] == ("contact.email",)
    assert seen["forbidden_values"] == []
