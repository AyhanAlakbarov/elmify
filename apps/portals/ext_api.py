"""The extension's own HTTP surface: JSON, bearer token, no cookies.

Modelled on apps/documents/api.py, which is this repository's precedent for a
JSON door with no presentation layer, and different from it in exactly one
respect: the caller is a browser extension holding a device token, not a
browser holding a session cookie.

That difference is the security model. Every route here is @csrf_exempt --
correct, because a cross-site request cannot forge an Authorization header, and
necessary, because an extension has no CSRF cookie. It is only correct while
authentication is the token ALONE. The moment a view here reads request.user,
csrf_exempt stops being safe and every route becomes drivable by any page on
the internet. tests/portals/test_ext_api.py pins that with
test_a_session_cookie_is_not_a_device_token.

The tenant comes from the host, exactly as it does for the dashboard
(HostTenantContextMiddleware resolves it and opens tenant_scope() +
set_local_tenant() around the request). The token only says WHICH MEMBERSHIP;
it never says which tenant. A pairing whose membership belongs to a different
tenant than the host therefore fails to authenticate, because the pairing row
itself is tenant-scoped and invisible under the host's scope.

Refusals on id-addressed routes are 404, never 403, matching
storage.download_document and documents/api.py: a 403 confirms the object
exists.
"""

from __future__ import annotations

import base64
import binascii
import email.utils
import json
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from apps.concierge.documents import DocumentUnavailable
from apps.concierge.models import DocumentVersion
from apps.documents import storage as document_storage
from apps.documents.models import DocumentDraft
from apps.documents.storage import read_upload, store_submission_image
from apps.funding.models import AuditEvent
from apps.ratelimit import rate_limited
from apps.tenancy.db import tenant_transaction
from apps.tenancy.middleware import deletion_lock_target
from apps.watch.rules import REGISTRATION_ASK_AFTER

from . import pairing as pairing_module
from . import tags
from .actions import complete_action, pending_actions
from .escalation import Trigger, escalate, request_first_portal_review
from .learn import RateLimited, UnmappedField, learn_from_snapshot
from .models import (
    Application,
    ApplicationStep,
    DeviceAction,
    ExtensionPairing,
    PortalAccount,
    PortalForm,
)
from .packets import NoFieldMap, PacketRefused, mint_packet
from .profile import verified_values
from .snapshot import FormSnapshot, SnapshotPIILeak

if TYPE_CHECKING:
    from apps.tenancy.models import Membership

#: Every limiter here counts per membership per hour.
_RATE_WINDOW_SECONDS = 3600

#: Pairing is once per installation. Ten in an hour is a student reinstalling;
#: more is something else.
_PAIR_RATE_LIMIT = 10

#: Minting is three database reads and a step write. Thirty an hour is a
#: student refilling a six-page form twice over; more is a loop.
_PACKET_RATE_LIMIT = 30

_View = Callable[..., HttpResponse]


class _ApiError(Exception):
    """A refusal with a status and a stable machine-readable code.

    The code is the contract with the extension: it is matched on, so it must
    not become a sentence anyone will later reword.
    """

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _json_errors(view: _View) -> _View:
    @wraps(view)
    def _wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        try:
            return view(request, *args, **kwargs)
        except _ApiError as error:
            return JsonResponse({"error": error.code}, status=error.status)

    return _wrapped


def _json_body(request: HttpRequest) -> dict[str, object]:
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        raise _ApiError(400, "invalid_json") from None
    if not isinstance(body, dict):
        raise _ApiError(400, "invalid_json")
    return body


def _limit(bucket: str, pairing: ExtensionPairing, limit: int) -> None:
    """Refuse once this membership has spent its budget in ``bucket``."""
    if rate_limited(
        bucket, pairing.membership_id, limit=limit, window_seconds=_RATE_WINDOW_SECONDS
    ):
        raise _ApiError(429, "rate_limited")


def _bearer(request: HttpRequest) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def _device_endpoint(view: _View) -> _View:
    """Authenticated by device token, resolved once, passed in.

    The pairing is handed to the view rather than looked up again inside it, so
    the row that passed the check and the row being acted for are the same
    object. There is no way to authenticate as one membership and write as
    another.
    """

    @wraps(view)
    def _wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        pairing = pairing_module.authenticate_device(_bearer(request))
        if pairing is None:
            return JsonResponse({"error": "pairing_required"}, status=401)
        # The same lock TenantMembershipMiddleware applies to the dashboard.
        # It lives there inside `if request.user.is_authenticated`, so a device
        # token runs past it: a student whose erasure is pending is locked out
        # of every screen while their extension would still be handed packets
        # of their own verified facts. revoke_all_for closes this at the source
        # when the request is created; this is the second line of defence, for
        # a pairing minted before that ran or a state the revoke does not cover.
        if deletion_lock_target(pairing.membership) is not None:
            return JsonResponse({"error": "account_locked"}, status=403)
        # Neither check lives anywhere a device token reaches: both are applied
        # by TenantMembershipMiddleware to a session. An objection or withdrawal
        # stops processing, and until a material change is re-accepted no new
        # processing runs (spec section 1), so the extension is refused too.
        from apps.privacy.acceptance import needs_acceptance
        from apps.privacy.requests import processing_stopped

        if processing_stopped(pairing.membership):
            return JsonResponse({"error": "processing_stopped"}, status=403)
        if needs_acceptance(pairing.membership):
            return JsonResponse({"error": "acceptance_required"}, status=403)
        pairing_module.touch(pairing)
        return view(request, pairing, *args, **kwargs)

    return csrf_exempt(_json_errors(_wrapped))


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
@_json_errors
def pair(request: HttpRequest) -> HttpResponse:
    """POST redeems a code; DELETE revokes this installation.

    One route, two methods, because they are the two ends of one object's life
    and a second path would be a second place to forget the rate limit.
    """
    if request.method == "DELETE":
        pairing = pairing_module.authenticate_device(_bearer(request))
        if pairing is None:
            raise _ApiError(401, "pairing_required")
        pairing_module.revoke_pairing(pairing)
        return HttpResponse(status=204)

    body = _json_body(request)
    code = str(body.get("code") or "")
    installation_id = str(body.get("installation_id") or "")
    try:
        pairing, token = pairing_module.redeem_pairing_code(code, installation_id)
    except pairing_module.PairingRefused as refused:
        raise _ApiError(400, refused.reason) from refused
    # After redemption, not before: the limiter keys on the membership and
    # there is no membership to key on until the code resolves to one. A caller
    # who trips it has burned their own code and gets nothing.
    if rate_limited(
        "ext-pair",
        pairing.membership_id,
        limit=_PAIR_RATE_LIMIT,
        window_seconds=_RATE_WINDOW_SECONDS,
    ):
        pairing_module.revoke_pairing(pairing)
        raise _ApiError(429, "rate_limited")
    return JsonResponse(
        {
            "token": token,
            "membership_id": str(pairing.membership_id),
            "student_name": pairing.membership.display_name,
        },
        status=201,
    )


def _application_for(pairing: ExtensionPairing, application_id: UUID) -> Application:
    application = (
        # A portal-less application (spec §7) is not the extension's: there is
        # no portal to fill, so it does not exist on this surface.
        Application.objects.filter(
            id=application_id, student=pairing.membership, portal_form__isnull=False
        )
        .select_related("portal_form")
        .first()
    )
    if application is None:
        raise _ApiError(404, "not_found")
    return application


@require_GET
@_device_endpoint
def packet(request: HttpRequest, pairing: ExtensionPairing, application_id: UUID) -> HttpResponse:
    """Mint this application's fill packet, or say why not.

    The three pre-checks live in mint_packet, not here: they are the same
    checks prepare_application ran before it opened a browser, and putting them
    in an HTTP view would be the second copy.

    request_first_portal_review runs AFTER a successful mint and only then.
    §5.2 asks a consultant to review the first application prepared on each new
    portal; a refused packet prepared nothing. It is here rather than in
    mint_packet because mint_packet has unit tests that would otherwise each
    create a roadmap item, and because this is the first caller -- the retiring
    services.py::prepare_application was the other one.
    """
    _limit("ext-packet", pairing, _PACKET_RATE_LIMIT)
    application = _application_for(pairing, application_id)
    try:
        minted = mint_packet(application)
    except NoFieldMap:
        # form_url travels with the refusal so the content script can check the
        # origin BEFORE it builds a first-encounter snapshot. Without it the
        # only source of form_url is the packet, and on this path there is no
        # packet -- so the snapshot was built and posted from a page nothing
        # had verified. That degrades to sabotage of a learned FieldMap rather
        # than exfiltration (a snapshot carries no value), but it is a real
        # hole and this closes it.
        assert application.portal_form is not None  # _application_for filters on it
        return JsonResponse(
            {
                "error": "no_field_map",
                "portal_form_id": str(application.portal_form_id),
                "form_url": application.portal_form.form_url,
            },
            status=424,
        )
    except PacketRefused as refused:
        # 409 for every reason mint_packet refuses with. no_field_map is the
        # one the extension can act on, and it is answered above as 424.
        raise _ApiError(409, refused.reason) from refused
    request_first_portal_review(application)
    # Pydantic's own JSON mode, not model_dump(): the packet holds UUIDs and
    # datetimes, and this is the one serialization the extension and the tests
    # agree on.
    return JsonResponse(json.loads(minted.model_dump_json()))


@require_POST
@_device_endpoint
def snapshot(request: HttpRequest, pairing: ExtensionPairing, portal_form_id: UUID) -> HttpResponse:
    """Learn this form's field map from a value-free snapshot.

    Authorized by the student having an application on this portal form, not
    by the form's id being known. A FieldMap is shared by every tenant, so an
    unauthorized caller here would be writing shared data on an object they
    have nothing to do with -- the reason this route is not simply "any paired
    extension may learn any form".

    The profile fields it asks for are this student's own verified keys: the
    map needs to know which questions we can answer, and the vocabulary is the
    same profile.py vocabulary the packet fills from. The VALUES never leave
    the server -- they are handed to the guard as forbidden strings, which is
    the opposite direction.
    """
    application = (
        Application.objects.filter(student=pairing.membership, portal_form_id=portal_form_id)
        .select_related("portal_form")
        .first()
    )
    if application is None:
        raise _ApiError(404, "not_found")
    assert application.portal_form is not None  # filtered on portal_form_id, never NULL
    try:
        parsed = FormSnapshot.model_validate(_json_body(request))
    except ValidationError as error:
        raise _ApiError(400, "invalid_snapshot") from error
    with tenant_transaction(application.tenant_id):
        values = verified_values(pairing.membership)
        # The portal address is the one field the map needs that is not a
        # verified fact (tags.py). Learned when the page asks for it -- always
        # offered, even when THIS student has no address (final review T5):
        # the map is the agency's, and the first snapshot must not decide for
        # everyone that it never carries the field. A student with no address
        # then gets missing_fact from the packet. The addresses themselves are
        # forbidden in the snapshot like any value.
        address, plain = tags.addresses_for(application)
    addresses = [address, plain] if address else []
    try:
        field_map = learn_from_snapshot(
            application.portal_form,
            parsed,
            profile_fields=sorted(values),
            optional_fields=("contact.email",),
            tenant_id=application.tenant_id,
            forbidden_values=[*values.values(), *addresses],
        )
    except SnapshotPIILeak as leak:
        raise _ApiError(400, "invalid_snapshot") from leak
    except RateLimited as limited:
        raise _ApiError(429, "rate_limited") from limited
    except UnmappedField as unmapped:
        raise _ApiError(422, "unmapped_fields") from unmapped
    # Who published this map. The row is attribution, not prevention: the
    # server has no page to check the selectors against, which is why the map
    # is scoped to this tenant and why the extension that CAN see the real page
    # verifies them (plan 3). Without it, a snapshot rewrites the map for a
    # whole agency and the trail cannot say whose browser described the form.
    with tenant_transaction(application.tenant_id):
        AuditEvent.objects.create(
            tenant_id=application.tenant_id,
            actor=pairing.membership,
            actor_kind=AuditEvent.ActorKind.HUMAN,
            event="portal.field_map_learned",
            object_id=field_map.id,
        )
    return JsonResponse(
        {"field_map_version": field_map.version, "entries": len(field_map.entries)}, status=201
    )


#: A fill of a six-page form posts a handful of events per page, and a student
#: may redo a page. Six hundred an hour is far above that and far below a loop.
_EVENTS_RATE_LIMIT = 600

#: 1.5 MB of PNG is a full-page screenshot at a normal viewport. The cap is on
#: the DECODED bytes, checked before the decode, because base64 of a gigabyte
#: is a gigabyte we would otherwise hold in memory to measure.
#:
#: The number is chosen so this check fires BEFORE Django's. base64 inflates by
#: 4/3, so 1.5 MB decoded is 2.0 MB on the wire, under the 2.5 MB
#: DATA_UPLOAD_MAX_MEMORY_SIZE default. A larger cap here is dead code: Django
#: rejects the body first, with an HTML 400 no JSON client can read. Pinned by
#: test_the_image_cap_fires_before_django_s.
_MAX_IMAGE_BYTES = 1_500_000

#: What the extension may report. A subset of ApplicationStep.Kind: PACKET is
#: the server's own row and the extension may not write one, and ESCALATION and
#: RECOVERY are written by the modules that own those decisions.
_EVENT_KINDS = frozenset(
    {
        ApplicationStep.Kind.FILL,
        ApplicationStep.Kind.READ_BACK,
        ApplicationStep.Kind.CHALLENGE,
        ApplicationStep.Kind.SUBMITTED,
        ApplicationStep.Kind.SIGNUP,
    }
)


def _decoded_image(raw: object) -> bytes | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise _ApiError(400, "invalid_image")
    # Exactly the encoded length of a _MAX_IMAGE_BYTES payload: base64 is
    # 4 characters per 3 bytes, rounded up. Slack here is a hole -- the first
    # version added 4 characters of it and let a payload one byte over the cap
    # through to the object store.
    if len(raw) > 4 * ((_MAX_IMAGE_BYTES + 2) // 3):
        raise _ApiError(413, "image_too_large")
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as error:
        raise _ApiError(400, "invalid_image") from error


@require_POST
@_device_endpoint
def events(request: HttpRequest, pairing: ExtensionPairing, application_id: UUID) -> HttpResponse:
    """Record what the student's browser reports, as the browser's attestation.

    This is not the authoritative record of what was prepared -- the PACKET row
    mint_packet wrote is (decision 2). The server cannot see the page, so
    everything here is a report from a device, and the two rows sit side by side
    in the §5.5 trail precisely so a reader can tell them apart.

    A READ_BACK carrying mismatches escalates PORTAL_ERROR and is not retried
    (decision 7); escalate() owns the move into every BLOCKED_* state, so this
    view never sets one itself. A CHALLENGE escalates nothing: the student is
    standing in front of the page, and the triggers that used to summon a
    consultant became dock prompts for the person who is already there
    (decision 8).
    """
    _limit("ext-events", pairing, _EVENTS_RATE_LIMIT)
    application = _application_for(pairing, application_id)
    body = _json_body(request)
    kind = str(body.get("kind") or "")
    if kind not in _EVENT_KINDS:
        raise _ApiError(400, "unknown_kind")
    detail = body.get("detail")
    if not isinstance(detail, dict):
        raise _ApiError(400, "invalid_detail")
    image = _decoded_image(body.get("image"))

    with tenant_transaction(application.tenant_id):
        step = ApplicationStep.objects.create(
            tenant=application.tenant,
            application=application,
            sequence=application.next_step_sequence(),
            kind=kind,
            detail=detail,
        )
    if image is not None:
        key = store_submission_image(
            tenant_id=application.tenant_id,
            student_id=application.student_id,
            step_id=step.id,
            image=image,
        )
        with tenant_transaction(application.tenant_id):
            ApplicationStep.objects.filter(pk=step.pk).update(detail={**detail, "image_key": key})

    if kind == ApplicationStep.Kind.SUBMITTED:
        with tenant_transaction(application.tenant_id):
            Application.objects.filter(pk=application.pk).update(
                state=Application.State.SUBMITTED
            )
    elif kind == ApplicationStep.Kind.READ_BACK and detail.get("mismatches"):
        escalate(application, Trigger.PORTAL_ERROR, detail=json.dumps(detail["mismatches"])[:500])
    return JsonResponse({"step_id": str(step.id)}, status=201)


#: The extension polls this on every dashboard load and while a fill is open.
#: Two a minute is comfortable for that and closes the door on a spin loop.
_ACTIONS_RATE_LIMIT = 120


@require_GET
@_device_endpoint
def actions(request: HttpRequest, pairing: ExtensionPairing) -> HttpResponse:
    """What this student's extension should do next.

    Scoped to the pairing's own membership, never to a student id in the
    request: there is no parameter here to get wrong.
    """
    _limit("ext-actions", pairing, _ACTIONS_RATE_LIMIT)
    with tenant_transaction(pairing.tenant_id):
        queued = pending_actions(pairing.membership)
    return JsonResponse(
        {
            "actions": [
                {
                    "id": str(action.id),
                    "kind": action.kind,
                    "application_id": (
                        str(action.application_id) if action.application_id else None
                    ),
                    "payload": action.payload,
                    "expires_at": action.expires_at.isoformat(),
                }
                for action in queued
            ]
        }
    )


@require_POST
@_device_endpoint
def action_result(request: HttpRequest, pairing: ExtensionPairing, action_id: UUID) -> HttpResponse:
    """Close one action, and record its outcome in the trail where it belongs.

    The outcome goes on the ApplicationStep, not on the action: the action is
    an instruction that expires, the step is the §5.5 record that does not.
    """
    body = _json_body(request)
    detail = body.get("detail")
    if not isinstance(detail, dict):
        raise _ApiError(400, "invalid_detail")
    with tenant_transaction(pairing.tenant_id):
        action = (
            DeviceAction.objects.filter(id=action_id, membership=pairing.membership)
            .select_related("application")
            .first()
        )
        if action is None:
            raise _ApiError(404, "not_found")
        application = action.application
        if application is not None:
            ApplicationStep.objects.create(
                tenant=application.tenant,
                application=application,
                sequence=application.next_step_sequence(),
                kind=ApplicationStep.Kind.VERIFY,
                detail={"action_kind": action.kind, "ok": bool(body.get("ok")), **detail},
            )
        complete_action(action)
    return JsonResponse({"completed": True})


class _PortalStatus(BaseModel):
    """What a portal's own account page said, as the extension read it.

    Typed and capped because it is third-party page text arriving as JSON, and
    it lands in a tenant's audit trail. The caps are what stop a hostile portal
    writing a novel into the §5.5 record.
    """

    model_config = ConfigDict(extra="forbid")

    portal_state: str = Field(default="", max_length=200)
    application_number: str = Field(default="", max_length=100)
    document_requests: tuple[str, ...] = Field(default=(), max_length=50)


@require_POST
@_device_endpoint
def application_status(
    request: HttpRequest, pairing: ExtensionPairing, application_id: UUID
) -> HttpResponse:
    """Record the portal's own account page, and change nothing else.

    Application.State deliberately does not move here. The portal's wording is
    the portal's; CONFIRMED in this codebase means a confirmation we recognised
    (decision 10), and letting a scraped string set it would hand a third-party
    page control of our own state machine.
    """
    application = _application_for(pairing, application_id)
    try:
        status = _PortalStatus.model_validate(_json_body(request))
    except ValidationError as error:
        raise _ApiError(400, "invalid_status") from error
    with tenant_transaction(application.tenant_id):
        step = ApplicationStep.objects.create(
            tenant=application.tenant,
            application=application,
            sequence=application.next_step_sequence(),
            kind=ApplicationStep.Kind.STATUS,
            detail=status.model_dump(mode="json"),
        )
    return JsonResponse({"step_id": str(step.id)}, status=201)


@require_POST
@_device_endpoint
def mailbox_check(request: HttpRequest, pairing: ExtensionPairing) -> HttpResponse:
    """Ask the mailbox worker to check this student's mailboxes now.

    The hourly sweep is too slow for a code the student is waiting for at the
    portal (spec §3). Queued, never synced here (security review M1): a sync
    reads the stored grant, WebTaskRole has no GetSecretValue on
    tehsil/mailbox/* and must not get it, and the AccessDenied would read as a
    lost grant and disconnect the student. The worker also runs outside this
    request's transaction. Same per-student brake the in-request sync had.
    Imported here, not at module load: apps.mailbox imports apps.portals.
    """
    from apps.mailbox import push
    from apps.mailbox.models import MailboxConnection
    from apps.mailbox.sync import SYNC_LIMIT, SYNC_WINDOW_SECONDS

    with tenant_transaction(pairing.tenant_id):
        connections = list(MailboxConnection.objects.filter(membership=pairing.membership))
    active = [c for c in connections if c.status == MailboxConnection.Status.ACTIVE]
    # "Wait" and "reconnect" are different answers for the dock.
    if not active and any(c.status == MailboxConnection.Status.ERROR for c in connections):
        raise _ApiError(409, "mailbox_disconnected")
    if active and rate_limited(
        "mailbox-sync",
        pairing.membership_id,
        limit=SYNC_LIMIT,
        window_seconds=SYNC_WINDOW_SECONDS,
    ):
        raise _ApiError(429, "rate_limited")
    for connection in active:
        push.enqueue_work("sync", connection)
    return JsonResponse({"queued": len(active)}, status=202)


#: A fill reports its address once per page. Thirty an hour is a student
#: redoing a registration a few times; more is a loop.
_ADDRESS_RATE_LIMIT = 30

#: How the extension knows a portal refused the tagged address. "form" is the
#: browser's own validity verdict -- the tagged value fails the control's
#: pattern or type while the plain one passes; "page" is the page's script
#: saying no (aria-invalid, an error message); "after_submit" is an unverified
#: page error seen only after the student pressed submit; "student" is the
#: dock's "use my plain address" button. All four are evidence about this
#: account only, never about the portal (tags.py, security review M2).
#: extension/src/types.ts::RejectionEvidence mirrors these; a test pins it.
_REJECTION_EVIDENCE = frozenset({"form", "page", "after_submit", "student"})


class _AddressReport(BaseModel):
    """What the extension saw happen to the address it typed (spec §2a).

    `event` and `evidence` are a closed vocabulary matched on by code, never
    displayed, like `_PortalStatus` above -- so nothing here should carry more
    than the few characters `address_report`'s own dict already checks.
    """

    model_config = ConfigDict(extra="forbid")

    event: Literal["given", "rejected"]
    evidence: str = Field(default="", max_length=20)

    @model_validator(mode="after")
    def _evidence_matches_event(self) -> _AddressReport:
        # A rejection names one of _REJECTION_EVIDENCE's values; a `given`
        # names none. The dict is the one definition of the vocabulary.
        if self.event == "rejected":
            known = self.evidence in _REJECTION_EVIDENCE
        else:
            known = not self.evidence
        if not known:
            raise ValueError("evidence does not match event")
        return self


@require_POST
@_device_endpoint
def address_report(
    request: HttpRequest, pairing: ExtensionPairing, application_id: UUID
) -> HttpResponse:
    """What happened when the extension typed this portal's address (spec §2a).

    `given`: the page held the address the packet carried. The first report
    for an account is its registration and, when the address is tagged, opens
    the registration-mail window; the answer says so and says when the dock
    should ask the student if no mail has come.
    `rejected`: the page refused the tagged address. The account falls back to
    the plain address for good, and the next packet and kit hand that out.
    Refused 409 `not_tagged` when the account never carried a tag of ours AND
    was never measured (F1): there is nothing for this evidence to be
    evidence of, and nothing is written. `plain_of` alone is not enough for
    that check (round 2): the first REJECTS already rewrites
    `account.address` to the plain address, so a repeat report on an
    already-measured account must not read that as "never tagged" and refuse
    a harmless no-op.

    Always answers with the account's current address, so the extension never
    has to guess which one the server now holds.
    """
    _limit("ext-address", pairing, _ADDRESS_RATE_LIMIT)
    application = _application_for(pairing, application_id)
    try:
        report = _AddressReport.model_validate(_json_body(request))
    except ValidationError as error:
        raise _ApiError(400, "invalid_report") from error
    now = timezone.now()
    awaiting = False
    with tenant_transaction(application.tenant_id):
        account = tags.account_for(application)
        if account is None:
            raise _ApiError(409, "no_portal_address")
        if report.event == "given":
            if tags.mark_registered(account, now):
                awaiting = tags.awaits_registration_mail(account, now)
                ApplicationStep.objects.create(
                    tenant=application.tenant,
                    application=application,
                    sequence=application.next_step_sequence(),
                    kind=ApplicationStep.Kind.SIGNUP,
                    detail={"tagged": bool(tags.plain_of(account))},
                )
        else:
            if not tags.plain_of(account) and account.tag_outcome == PortalForm.TagStatus.UNKNOWN:
                raise _ApiError(409, "not_tagged")
            tags.record_tag_outcome(
                account, PortalForm.TagStatus.REJECTS, force=report.evidence == "student"
            )
    return JsonResponse(
        {
            "address": account.address,
            "awaiting_mail": awaiting,
            "ask_after_seconds": int(REGISTRATION_ASK_AFTER.total_seconds()),
        }
    )


#: The dock asks once per registration; a student answering twice is fine, a
#: page answering in a loop is not.
_REGISTRATION_RATE_LIMIT = 30

_ARRIVED = {"tagged": PortalForm.TagStatus.KEEPS, "plain": PortalForm.TagStatus.STRIPS}


class _RegistrationAnswer(BaseModel):
    """What the student said about the portal's first email. Typed, capped:
    `sender` is text the student typed, and it only ever becomes a domain."""

    model_config = ConfigDict(extra="forbid")

    arrived: str = Field(pattern="^(tagged|plain|none)$")
    sender: str = Field(default="", max_length=320)


def _single_address(text: str) -> str:
    """The one address ``text`` names, or "" when it is not exactly one.

    A typed sender is not a trusted header, and `apps.mailbox.filter
    .sender_domain`'s bare ``rpartition("@")`` keeps the LAST "@" in whatever
    text it is handed -- so `"x@evil.com\\r\\nBcc: y@z.com"` resolved to
    z.com, an attacker-smuggled line, instead of being refused (fix round 1,
    finding 3). `email.utils.getaddresses` parses the same input as one
    malformed pair with an empty address; two genuine addresses parse as two
    pairs. Either way `len(parsed) != 1` or the address holds other than
    exactly one "@" refuses it, never picks one.
    """
    parsed = email.utils.getaddresses([text])
    if len(parsed) != 1:
        return ""
    _name, address = parsed[0]
    return address if address.count("@") == 1 else ""


def _registration_state(account: PortalAccount | None, now: datetime) -> dict[str, object]:
    """`none`: no tagged registration to watch (no account, never registered,
    or an untagged address -- an account handed the plain address from the
    start has nothing for the dock to ask about). `done`: the account's own
    measurement, or the student's own answer, already settled it. `waiting`:
    too early to ask -- the portal's mail may still be on its way. `ask`: the
    window has passed with no mail; ask the student while they are still at
    the portal.
    """
    if account is None or account.registered_at is None or not tags.plain_of(account):
        return {"state": "none"}
    if account.tag_outcome != PortalForm.TagStatus.UNKNOWN:
        state = "done"
    elif now - account.registered_at < REGISTRATION_ASK_AFTER:
        state = "waiting"
    else:
        state = "ask"
    return {"state": state, "portal_host": account.portal_host, "address": account.address}


@require_http_methods(["GET", "POST"])
@_device_endpoint
def registration(
    request: HttpRequest, pairing: ExtensionPairing, application_id: UUID
) -> HttpResponse:
    """The registration-mail expectation (spec §2a), asked and answered in the dock.

    GET says where it stands -- see `_registration_state`.

    POST is the student's answer. `tagged` measures KEEPS; `plain` measures
    STRIPS and learns the sender they named, unconfirmed, because a typed
    address is not verified evidence on its own (apps.mailbox.filter
    .learn_answered_sender, ruling F8); `none` records nothing -- the tag
    status stays unmeasured, which is the safe default. Either measurement is
    this account's only, like every report (tags.py, security review M2).

    A sender is learned only on THIS account's first measurement (fix round 1,
    finding 2): `record_tag_outcome`'s return value says whether this call
    was the one that moved `tag_outcome` out of UNKNOWN, and only that call
    may add a `LearnedSender`. A repeat answer -- `plain` after an earlier
    `tagged`, or a second `plain` naming a different sender -- moves nothing,
    so it must not add a second, contradicting row either; it was previously
    bounded only by the rate limit.

    `state` is computed once, up front, and used for both the GET answer and
    the POST refusal (ruling F4): an untagged account -- `none` -- is refused
    `409 no_registration` on POST exactly as a missing one is, because there
    is nothing here for the student's answer to be about and nothing may be
    written for it.
    """
    _limit("ext-registration", pairing, _REGISTRATION_RATE_LIMIT)
    application = _application_for(pairing, application_id)
    now = timezone.now()
    with tenant_transaction(application.tenant_id):
        account = tags.account_for(application)
    state = _registration_state(account, now)

    if request.method == "GET":
        return JsonResponse(state)

    if state["state"] == "none":
        raise _ApiError(409, "no_registration")
    try:
        answer = _RegistrationAnswer.model_validate(_json_body(request))
    except ValidationError as error:
        raise _ApiError(400, "invalid_answer") from error
    # Imported here, not at module load: apps.mailbox imports apps.portals.
    from apps.mailbox.filter import learn_answered_sender, sender_key
    from apps.mailbox.models import MailboxConnection

    address = ""
    if answer.arrived == "plain":
        address = _single_address(answer.sender)
        if not address or not sender_key(address):
            raise _ApiError(400, "invalid_sender")
    learned = False
    with tenant_transaction(application.tenant_id):
        assert account is not None  # state != "none" guarantees this
        moved = False
        if answer.arrived in _ARRIVED:
            moved = tags.record_tag_outcome(account, _ARRIVED[answer.arrived])
        if answer.arrived == "plain" and moved:
            own = [
                application.student.application_email,
                account.address,
                *MailboxConnection.objects.filter(membership=pairing.membership).values_list(
                    "address", flat=True
                ),
            ]
            learned = learn_answered_sender(
                pairing.membership, address, account.portal_host, own_addresses=own
            )
    return JsonResponse({"learned": learned})


#: An attachment is a whole file. Thirty an hour is a student attaching every
#: document of several applications, and stops a loop pulling the bucket.
_DOCUMENT_RATE_LIMIT = 30
_EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}
#: A rendered draft's type, from its stored filename's extension.
_TYPES = {extension: content_type for content_type, extension in _EXTENSIONS.items()}


def _named_for(membership: Membership, document_id: UUID, source: str) -> bool:
    """Named for one of this student's applications, under this source: by a live
    OPEN_UPLOAD_PAGE action (Submit document) or by the latest PACKET step (spec B),
    whose ``uploads`` name uploads and whose ``documents`` name drafts."""
    if DeviceAction.objects.filter(
        membership=membership,
        kind=DeviceAction.Kind.OPEN_UPLOAD_PAGE,
        completed_at__isnull=True,
        expires_at__gt=timezone.now(),
        payload__document_id=str(document_id),
        payload__source=source,
    ).exists():
        return True
    group, field = ("uploads", "upload_id") if source == "upload" else ("documents", "draft_id")
    for application in Application.objects.filter(student=membership):
        packet = (
            ApplicationStep.objects.filter(
                application=application, kind=ApplicationStep.Kind.PACKET
            )
            .order_by("-sequence")
            .first()
        )
        items = (packet.detail or {}).get(group, []) if packet is not None else []
        if any(isinstance(i, dict) and i.get(field) == str(document_id) for i in items):
            return True
    return False


def _inert(body: bytes, content_type: str, filename: str) -> HttpResponse:
    response = HttpResponse(body, content_type=content_type)
    # Every route that serves an upload sends all three (spec §6, "Upload safety"): a file
    # is saved, never rendered; its type is never guessed; and if anything renders it
    # anyway, it runs no script and loads nothing.
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


@require_GET
@_device_endpoint
def document(request: HttpRequest, pairing: ExtensionPairing, document_id: UUID) -> HttpResponse:
    """A scanned-clean, checked upload or a rendered, approved draft, for the extension
    to attach (spec §6 step 3).

    404 for every refusal, never 403: the id of a document that is not yours,
    not clean, not promoted, not rendered or not asked for is not a fact you get
    to confirm.
    """
    _limit("ext-document", pairing, _DOCUMENT_RATE_LIMIT)
    with tenant_transaction(pairing.tenant_id):
        upload = (
            DocumentVersion.objects.filter(
                id=document_id, student=pairing.membership, state="AVAILABLE",
                scan_result="NO_THREATS_FOUND",
            )
            .exclude(promoted_key="")
            .first()
        )
        draft = (
            None
            if upload is not None
            else DocumentDraft.objects.filter(
                id=document_id, student=pairing.membership,
                status=DocumentDraft.Status.APPROVED,
            )
            .exclude(rendered_filename="")
            .first()
        )
        named = (upload is not None and _named_for(pairing.membership, document_id, "upload")) or (
            draft is not None and _named_for(pairing.membership, document_id, "draft")
        )
    if not named:
        raise _ApiError(404, "not_found")
    if upload is not None:
        if upload.content_type not in _EXTENSIONS:
            raise _ApiError(404, "not_found")
        try:
            body = read_upload(upload)
        except (DocumentUnavailable, KeyError):
            raise _ApiError(404, "not_found") from None
        filename = f"{upload.kind.lower()}-{upload.id}{_EXTENSIONS[upload.content_type]}"
        return _inert(body, upload.content_type, filename)
    assert draft is not None  # named implies one of the two
    suffix = PurePosixPath(draft.rendered_filename).suffix.lower()
    content_type = _TYPES.get(".jpg" if suffix == ".jpeg" else suffix)
    if content_type is None:
        raise _ApiError(404, "not_found")
    try:
        body = document_storage.read_draft(draft, draft.rendered_filename)
    except (document_storage.InvalidFilename, KeyError):
        raise _ApiError(404, "not_found") from None
    return _inert(body, content_type, f"{draft.kind.lower()}-{draft.id}{suffix}")
