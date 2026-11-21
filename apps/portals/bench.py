"""The portal test bench (spec §9): the owner's recorded walk, the offline
replay and the verified gate. Platform-only: no agency role reaches any of it."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4

import lxml.html
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from lxml import etree

from apps.funding.models import AuditEvent
from apps.research.models import PlatformAgency
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

from .bench_runner import BenchReport
from .learn import _page_origin, _store_map
from .models import FieldMap, PageRecord, PortalForm
from .profile import narrative_values, verified_values
from .snapshot import (
    FormSnapshot,
    SnapshotPIILeak,
    assert_no_student_values,
    redact_student_values,
    student_value_pattern,
)

#: 1.5 MB of HTML. The copy arrives inside a JSON body under Django's 2.5 MB
#: DATA_UPLOAD_MAX_MEMORY_SIZE. JSON escaping inflates HTML (every quote and
#: newline gains a backslash), so a quote-heavy page near this cap can still
#: exceed Django's limit; that refusal is an HTML 400 the extension reads as
#: `request_failed`. This cap is the one a client can read as `invalid_recording`.
MAX_HTML_BYTES = 1_500_000

_REDACTED = "■"


class RecordingRefused(Exception):
    """A bench recording the server will not keep. The message never carries a value."""


def _store() -> S3ObjectStore:
    return S3ObjectStore()


def is_bench_operator(membership: Membership) -> bool:
    """An active PLATFORM_ADMIN of the platform agency, with MFA enrolled.

    research/views.py::_operator's door on a device token. require_staff_mfa
    reads a VERIFIED SESSION, which a device token never has, so two things
    stand in for it: the pairing code was minted from a dashboard session that
    passed require_staff_mfa (TenantMembershipMiddleware, and again in
    views.pairing_code), and the user must still hold a confirmed TOTP device
    now -- removing the device ends bench access. The host check is the
    pairing's own: a pairing is tenant-scoped, so it authenticates only on its
    own agency's host, and that agency must be the platform.
    """
    return bool(
        membership.active
        and membership.role == Membership.Role.PLATFORM_ADMIN
        and PlatformAgency.objects.filter(agency_id=membership.tenant_id).exists()
        and TOTPDevice.objects.filter(user_id=membership.user_id, confirmed=True).exists()
    )


def operator_forbidden_values(operator: Membership) -> list[str]:
    """What a recording must not carry: the operator's own facts in the platform
    tenant, their names and their login email. First and last name separately,
    so a "Welcome, Orkhan" greeting is redacted too. The platform tenant only --
    the owner's student membership in another agency is a person's data in
    another tenant (CLAUDE.md). Caller holds tenant_transaction(operator.tenant_id)."""
    user = operator.user
    # ponytail: the bare names go to snapshot.assert_no_student_values, an
    # any-substring refusal, so a short name ("Ali" in "quality", "Australia")
    # would refuse whole pages. Fine for the one operator today; when a second
    # exists, redact the names and refuse whole-word via student_value_pattern.
    found = [
        *verified_values(operator).values(),
        *narrative_values(operator).values(),
        user.first_name,
        user.last_name,
        user.get_full_name(),
        user.email,
    ]
    return [value for value in found if value.strip()]


_ACTIVE_TAGS = ("script", "iframe", "object", "embed", "base")


def _strip_active_content(tree: lxml.html.HtmlElement) -> None:
    """The saved copy is replayed in a browser: nothing in it may run or load.
    The client strips these too; the server does not rely on that. Chosen
    state (`selected`/`checked`) goes as well, so a replay starts blank."""
    for element in list(tree.iter(*_ACTIVE_TAGS, "meta")):
        if element.tag != "meta" or element.get("http-equiv") is not None:
            element.drop_tree()
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        for name in list(element.attrib):
            if name.lower().startswith("on") or name.lower() in ("selected", "checked"):
                del element.attrib[name]


def _redacted_html(html: str, pattern: re.Pattern[str] | None) -> str:
    """The saved copy with every operator value in its text and attributes redacted.

    ANY non-empty input `value` attribute or textarea text is refused, whether or
    not it is the operator's: savedCopy strips every one, so a survivor means
    the in-browser blanking failed and nothing else in the copy can be trusted
    to have been blanked either. Everything else -- a greeting ("Welcome, Orkhan"),
    an option listing the operator's own institution -- is the page's wording
    or vocabulary, and is redacted the way a snapshot's free text is.
    """
    try:
        tree = lxml.html.document_fromstring(html)
    except (etree.LxmlError, ValueError) as error:
        raise RecordingRefused("the saved copy is not an HTML page") from error
    _strip_active_content(tree)
    for control in tree.iter("input"):
        if control.get("value"):
            raise RecordingRefused("an input in the saved copy holds a value")
    for control in tree.iter("textarea"):
        if control.text_content().strip():
            raise RecordingRefused("a textarea in the saved copy holds text")
    if pattern is not None:
        for element in tree.iter():
            if element.text:
                element.text = pattern.sub(_REDACTED, element.text)
            if element.tail:
                element.tail = pattern.sub(_REDACTED, element.tail)
            if isinstance(element.tag, str):  # comments carry no attributes
                for name, value in list(element.attrib.items()):
                    element.set(name, pattern.sub(_REDACTED, value))
    out: str = lxml.html.tostring(tree, encoding="unicode", doctype="<!doctype html>")
    return out


def store_bench_page(
    portal_form: PortalForm,
    *,
    page_kind: str,
    password_rules: str,
    snapshot: FormSnapshot,
    html: str,
    forbidden_values: list[str],
    step: int,
    actor: Membership,
) -> PageRecord:
    """Keep one page of the operator's walk, redacted, or raise RecordingRefused.

    The HTML is put before the row exists, and outside any transaction, so a
    failed upload leaves no row without its copy -- one that would still count
    toward `step` and promotion. With `actor` (the operator) the row and
    its `portal.bench_page_recorded` AuditEvent commit in one tenant
    transaction, so a failed audit insert rolls the row back too: the
    request's own atomic block would not, because Django turns the view's
    exception into a 500 response before that block exits.
    """
    if len(html.encode()) > MAX_HTML_BYTES:
        raise RecordingRefused("the saved copy is larger than a form page")
    try:
        redacted = redact_student_values(_page_origin(snapshot), forbidden_values)
        assert_no_student_values(redacted, forbidden_values)
    except SnapshotPIILeak as leak:
        raise RecordingRefused(str(leak)) from leak
    body = _redacted_html(html, student_value_pattern(forbidden_values)).encode()
    record_id = uuid4()
    html_key = f"bench/{portal_form.id}/{record_id}.html"
    _store().put(html_key, body)
    fields = {
        "id": record_id,
        "portal_form": portal_form,
        "source": PageRecord.Source.BENCH_WALK,
        "page_kind": page_kind,
        "step": step,
        "snapshot": json.loads(redacted.model_dump_json()),
        "html_key": html_key,
        "password_rules": password_rules,
    }
    with tenant_transaction(actor.tenant_id):
        record = PageRecord.objects.create(**fields)
        AuditEvent.objects.create(
            tenant_id=actor.tenant_id,
            actor=actor,
            actor_kind=AuditEvent.ActorKind.HUMAN,
            event="portal.bench_page_recorded",
            object_id=record.id,
        )
    return record


class PromotionRefused(Exception):
    """The verified gate said no. Nothing was written."""


def mapping_digest(field_map: FieldMap) -> str:
    """Names the exact rows the operator checked. Read-back cannot see a
    wrong-but-consistent map (a box typed and read through the same wrong
    selector verifies clean), so the gate's human look is at the mapping
    itself, and promotion carries this digest as proof of which one."""
    rows = json.dumps([field_map.entries, field_map.slots or []], sort_keys=True)
    return hashlib.sha256(rows.encode()).hexdigest()[:12]


def promote(
    portal_form: PortalForm,
    source_map: FieldMap,
    report: BenchReport,
    *,
    operator: Membership,
    confirmed: str,
) -> FieldMap:
    """Spec §9's verified gate. Copies the bench-clean map to a platform-shared,
    verified row. Refuses, writing nothing, unless the bench is clean and the
    current walk recorded the portal's login and sign-up pages as having worked
    (spec §6, checked by the owner's own walk), the sign-up with its password
    rules, and the operator confirmed this exact mapping by its digest. A
    superseded walk describes a page that changed, so it never counts.
    """
    if not is_bench_operator(operator):
        raise PromotionRefused("only a bench operator promotes a map")
    if not source_map.entries and not source_map.slots:
        raise PromotionRefused("the map is empty: it proves nothing")
    if confirmed != mapping_digest(source_map):
        raise PromotionRefused(
            "the operator has not confirmed this exact mapping (portal_bench prints its digest)"
        )
    if not report.clean:
        raise PromotionRefused(
            "the bench run is not clean: an amber, a refusal, a manual document "
            "or an untested box remains"
        )
    walked = PageRecord.objects.filter(
        portal_form=portal_form,
        source=PageRecord.Source.BENCH_WALK,
        superseded_at__isnull=True,
        walk_ok=True,
    )
    if not walked.filter(page_kind=PageRecord.Kind.LOGIN).exists():
        raise PromotionRefused(
            "no recorded LOGIN page marked as worked (portal_bench --walk-ok LOGIN)"
        )
    signup_rules = (
        walked.filter(page_kind=PageRecord.Kind.SIGNUP)
        .exclude(password_rules="")  # nosec B106 -- the portal's rule text, not a credential
        .order_by("-created_at")
        .values_list("password_rules", flat=True)
        .first()
    )
    if signup_rules is None:
        raise PromotionRefused(
            "no recorded SIGNUP page with its password rules marked as worked "
            "(portal_bench --walk-ok SIGNUP)"
        )
    # AuditEvent is a TenantScopedModel: the scope for its save, the GUC for its
    # FORCE RLS policy. One transaction, so the verified row, the form's rules
    # and the audit event commit together or not at all.
    with tenant_scope(operator.tenant_id), tenant_transaction(operator.tenant_id):
        # Under the form lock, before any write: a relearn that landed between
        # the replay and here must not have its "portal changed" cleared by a
        # copy of the map the replay saw.
        locked = PortalForm.objects.select_for_update().get(pk=portal_form.pk)
        newer_relearn = FieldMap.objects.filter(
            portal_form=portal_form,
            learned_by_tenant__isnull=False,
            superseded_at__isnull=True,
            version__gt=source_map.version,
        )
        if (
            source_map.portal_form_id != portal_form.id
            or not FieldMap.objects.filter(pk=source_map.pk, superseded_at__isnull=True).exists()
            or (locked.needs_bench and (not portal_form.needs_bench or newer_relearn.exists()))
        ):
            raise PromotionRefused(
                "the benched map is not this form's current map any more: re-run portal_bench"
            )
        verified = _store_map(
            portal_form,
            list(source_map.entries),
            slots=list(source_map.slots or []),
            learned_by_tenant_id=None,
        )
        verified.verified_at = timezone.now()
        verified.save(update_fields=["verified_at"])
        portal_form.password_rules = signup_rules
        portal_form.needs_bench = False
        portal_form.save(update_fields=["password_rules", "needs_bench"])
        AuditEvent.objects.create(
            tenant_id=operator.tenant_id,
            actor=operator,
            actor_kind=AuditEvent.ActorKind.HUMAN,
            event="portal.field_map_verified",
            object_id=verified.id,
        )
    return verified
