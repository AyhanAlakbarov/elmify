"""The Firecrawl webhook receiver, and the platform's resolution console.

The webhook is off until a public HTTPS endpoint exists.

Shape decided by two of the vendor's own numbers: 2xx within 10 seconds, and
three retries at 1 / 5 / 15 minutes. So the handler verifies, writes one
column and returns. Anything that fetched a page inline would hold the
request open for a vendor round trip and be retried while still working on
the first delivery.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from uuid import UUID

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.funding.models import AuditEvent, OfficialSourceSnapshot
from apps.research.models import GoldItem, PlatformAgency, ResolutionItem
from apps.research.resolution.kinds import KINDS
from apps.research.resolution.operator import (
    DecisionRefused,
    decide,
    listing,
    open_item,
    park,
    waiting_for_the_applier,
)
from apps.tenancy.middleware import require_staff_mfa
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

logger = logging.getLogger(__name__)

_STATUS = {
    "changed": OfficialSourceSnapshot.RetrievalStatus.STALE,
    "removed": OfficialSourceSnapshot.RetrievalStatus.FAILED,
}


@csrf_exempt
@require_POST
def firecrawl_webhook(request: HttpRequest) -> HttpResponse:
    if not settings.FETCH_WEBHOOKS_ENABLED:
        # A route that exists and is unreachable makes Firecrawl report our
        # own unreachability as a delivery failure on every check.
        raise Http404
    secret = settings.FIRECRAWL_WEBHOOK_SECRET
    signature = request.headers.get("X-Firecrawl-Signature", "")
    # request.body, never a re-serialised parse: json.dumps(json.loads(body))
    # differs from body in key order and separators, and verifying the
    # round-trip is the classic way an HMAC check passes for a body nobody
    # sent. An absent secret refuses everything -- "no secret means accept" is
    # how a deployment that forgot it accepts anything that posts.
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest() if secret else ""
    if not secret or not hmac.compare_digest(expected, signature):
        logger.warning("firecrawl webhook signature rejected")
        return JsonResponse({"detail": "signature"}, status=401)
    try:
        payload = json.loads(request.body)
    except ValueError:
        return JsonResponse({"detail": "body"}, status=400)
    data = payload.get("data") or {}
    url = str(data.get("url") or "")
    status = _STATUS.get(str(data.get("status") or ""))
    if url and status is not None:
        # FAILS in production: the web tier runs as `runtime_web`, which holds
        # no grant on this catalogue table, so this raises `permission denied`
        # (pinned by test_under_the_web_role_the_write_is_refused_not_silent).
        # Moving it to the worker alone is not enough either: the snapshot
        # table has no UPDATE policy, so under `runtime_engine` it matches zero
        # rows, silently (`poll_monitor_checks._mark`). Enabling the flag needs
        # both: the write queued to `runtime_engine`, and that policy.
        OfficialSourceSnapshot.objects.filter(final_url=url).update(retrieval_status=status)
    return JsonResponse({"ok": True})


# --- /platform/resolution/: the platform's resolution console ---------------
#
# Spec 2026-09-22 section 11, plan Task 6. Mounted under /platform/, never
# /owner/: /owner/ is every agency's own owner console, and decision 26 is that
# no agency ever sees this queue. Runs as `runtime_web`, which holds no grant on
# any catalogue table (brief D3), so nothing reachable from here may read one --
# tests/research/resolution/test_views.py runs all four routes under that role.


def _operator(request: HttpRequest) -> Membership:
    """The only way into the resolution queue.

    Three checks, and each closes a different door:
    - the host must be the platform agency's (research.PlatformAgency): an
      agency's owner is an OWNER on /owner/, and PLATFORM_ADMIN is a role any
      agency can hold. The database agrees -- on any other host app.tenant_id
      is that agency's and the queue's policy shows zero rows -- but a 403
      here says so before a query does;
    - the membership must be an active PLATFORM_ADMIN of this agency;
    - MFA is checked HERE too. TenantMembershipMiddleware already checks it
      against the user's active membership in this tenant -- and
      membership_tenant_user_uniq makes that the one this function finds -- so
      today this is a second lock on the same door, kept so the queue's gate
      does not rest on a middleware's choice of membership.
    """
    tenant = request.tenant  # type: ignore[attr-defined]
    if not PlatformAgency.objects.filter(agency_id=tenant.id).exists():
        raise PermissionDenied("the resolution queue is the platform's")
    operator = current_membership(request, Membership.Role.PLATFORM_ADMIN)
    require_staff_mfa(request.user, Membership.Role.PLATFORM_ADMIN)  # type: ignore[arg-type]
    return operator


@login_required
@require_GET
def resolution_queue(request: HttpRequest) -> HttpResponse:
    operator = _operator(request)
    return render(
        request,
        "research/resolution_queue.html",
        {
            "rows": listing(operator, now=timezone.now()),
            "waiting_for_the_applier": waiting_for_the_applier(),
        },
    )


@login_required
@require_GET
def resolution_item(request: HttpRequest, item_id: UUID) -> HttpResponse:
    operator = _operator(request)
    try:
        item = open_item(item_id, operator, now=timezone.now())
    except ResolutionItem.DoesNotExist as error:
        raise Http404("no such item") from error
    return render(
        request,
        "research/resolution_item.html",
        {
            "item": item,
            "ask": item.ask,
            "evidence": item.evidence,
            "options": list(KINDS[item.kind].options),
            "apply_error": item.apply_error,
        },
    )


@login_required
@require_POST
def resolution_decide(request: HttpRequest, item_id: UUID) -> HttpResponse:
    operator = _operator(request)
    kind = ResolutionItem.objects.filter(id=item_id).values_list("kind", flat=True).first()
    if kind is None:
        raise Http404("no such item")
    form = {key: request.POST.get(key, "") for key in request.POST}
    try:
        decide(item_id, operator, KINDS[kind].from_form(form), now=timezone.now())
    except ResolutionItem.DoesNotExist as error:
        raise Http404("no live item") from error
    except DecisionRefused as refused:
        return HttpResponseBadRequest(str(refused))
    return redirect("resolution-queue")


@login_required
@require_POST
def resolution_park(request: HttpRequest, item_id: UUID) -> HttpResponse:
    operator = _operator(request)
    try:
        park(item_id, operator, now=timezone.now())
    except ResolutionItem.DoesNotExist as error:
        raise Http404("no live item") from error
    except DecisionRefused as refused:
        return HttpResponseBadRequest(str(refused))
    return redirect("resolution-queue")


_VERDICTS = {"correct", "wrong", "not_on_page"}
_FIX_MAX = 2000


@login_required
@require_GET
def gold_queue(request: HttpRequest) -> HttpResponse:
    """The owner's checking page: the next 20 unchecked facts, oldest first."""
    _operator(request)
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for kind, purpose, verdict in GoldItem.objects.values_list("kind", "purpose", "verdict"):
        c = counts.setdefault((kind, purpose), {"checked": 0, "unchecked": 0})
        c["checked" if verdict else "unchecked"] += 1
    items = GoldItem.objects.filter(verdict="").order_by("created_at")[:20]
    return render(
        request,
        "research/gold_queue.html",
        {"items": items, "counts": sorted(counts.items())},
    )


@login_required
@require_POST
def gold_label(request: HttpRequest, item_id: UUID) -> HttpResponse:
    """Label one item once. The filter on verdict="" is the whole relabel guard."""
    operator = _operator(request)
    verdict = request.POST.get("verdict", "")
    fix = request.POST.get("fix", "").strip()
    if verdict not in _VERDICTS or (verdict == "wrong" and not fix) or len(fix) > _FIX_MAX:
        return HttpResponseBadRequest("verdict must be correct, wrong (with a fix) or not_on_page")
    # Who labelled lives in AuditEvent, not on the row (GoldItem's docstring).
    with transaction.atomic():
        updated = GoldItem.objects.filter(id=item_id, verdict="").update(
            verdict=verdict, fix=fix, labelled_at=timezone.now()
        )
        if updated:
            AuditEvent.objects.create(actor=operator, event="gold.labelled", object_id=item_id)
    if not updated:
        return HttpResponse("already labelled", status=409)
    return redirect("gold-queue")
