"""One Europass render, start to finish: cache, circuit, render, store.

Deliberately free of AWS concerns. The worker owns SQS; this owns the
decision of whether to call europa.eu at all and what to do with the bytes,
which is the part worth testing without a queue.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.research.storage import S3ObjectStore
from apps.tenancy.context import current_tenant_id
from apps.tenancy.db import set_local_tenant

from .constraints import directives_from_program
from .europass import (
    EuropassProvenanceMissing,
    EuropassThrottled,
    EuropassUnavailable,
    europass_payload,
)
from .models import DocumentDraft, EuropassCircuit, EuropassRenderCache
from .render import RenderRateLimited, europass_content, render_draft
from .schemas import CVContent
from .storage import document_key, store_document

#: Three in a row means it is europa.eu, not this request. Below that a single
#: transient failure should not park every other student's CV.
_FAILURE_THRESHOLD = 3
#: How long a run of plain failures parks the queue. Shorter than a throttle:
#: we were not asked to wait, we are guessing.
_FAILURE_PAUSE_SECONDS = 300
#: One filename, used both when computing the key a cache hit should have
#: landed under and when actually storing -- so the two can never drift.
_ARTEFACT_FILENAME = "cv-europass.pdf"


class CircuitOpen(EuropassUnavailable):
    """We are paused. The caller should return the message to the queue."""


@dataclass(frozen=True)
class RenderOutcome:
    object_key: str
    called_remote: bool


def payload_hash(content: CVContent, oldest_first: bool = False) -> str:
    """Hash what we would SEND, not the draft row.

    Two drafts differing only in a field Europass never receives produce the
    same payload and should share an artefact rather than cost two calls. Pass
    render.europass_content's pair, so the programme's order is part of the
    key: hashing the raw draft let two programmes asking different orders
    share one PDF.
    """
    canonical = json.dumps(
        europass_payload(content, oldest_first=oldest_first),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _open_circuit(seconds: int, reason: str) -> None:
    circuit = EuropassCircuit.load()
    circuit.paused_until = timezone.now() + timedelta(seconds=seconds)
    circuit.reason = reason[:200]
    circuit.save(update_fields=["paused_until", "reason"])


def render_and_store(
    *, draft: DocumentDraft, store: S3ObjectStore | None = None
) -> RenderOutcome:
    """Render one approved draft through europa.eu and store the artefact.

    Raises CircuitOpen when paused, EuropassThrottled when europa.eu asks us
    to slow down, and EuropassUnavailable for everything else. It never
    returns a non-Europass artefact -- there is no fallback.

    Tenant-scoped DB work (the cache lookup, a stale-row delete, the final
    store-plus-cache-row write) each gets its own short transaction with a
    freshly set tenant GUC. EuropassCircuit is deliberately NOT tenant-scoped
    and never sits inside one of those transactions: every write to it must
    survive on its own, regardless of whether the tenant-scoped work around
    it ever commits (ruling F-G).

    Nothing in this module enforces that against an enclosing transaction --
    a caller that wraps this whole function in its own atomic() would turn
    these three atomic() blocks into savepoints, and a rollback of that
    outer transaction would take the breaker writes with it. It is true
    today only because the sole caller, process_europass_message, closes its
    own atomic block before calling this function.
    """
    if draft.render_variant != "EUROPASS_API":
        # The choke point: every other variant (STANDARD, EUROPASS,
        # GERMAN_TABULAR, or the blank default) must never reach the
        # Europass hash, cache, or store below -- there is no fallback, and
        # a future trigger spec that does not exist yet cannot be relied on
        # to re-derive this guard.
        #
        # This reads the RAW field. render_draft (render.py) now resolves the
        # effective variant from programme/funder instead of trusting
        # render_variant as stored, so a blank-variant draft that WOULD
        # resolve to EUROPASS_API never reaches this function at all today.
        # The two must be reconciled once draft creation learns about
        # funders and starts persisting the resolved variant.
        raise EuropassUnavailable(
            f"draft render_variant is {draft.render_variant!r}, not EUROPASS_API"
        )
    content = CVContent.model_validate(draft.content)
    directives = directives_from_program(draft.programme) if draft.programme is not None else ()
    digest = payload_hash(*europass_content(content, directives))
    tenant_id = current_tenant_id()

    with transaction.atomic():
        set_local_tenant(tenant_id)
        cached = EuropassRenderCache.objects.filter(payload_hash=digest).first()

    if cached is not None:
        # Verified on EVERY hit, same-key included: delete_student_documents
        # erases a student's S3 objects but never touches this table, so a
        # cache row -- even one already keyed to this exact draft -- can
        # point at nothing. Checking only the cross-draft branch would leave
        # that case reporting success for an object that is gone.
        store_obj = store or S3ObjectStore()
        try:
            cached_pdf = store_obj.get(cached.object_key)
        except KeyError:
            # The row outlived its object. A miss, not a failure: drop it
            # and fall through to a real render. Anything other than a
            # missing object (AccessDenied, throttling) still propagates --
            # S3ObjectStore.get translates only NoSuchKey.
            with transaction.atomic():
                set_local_tenant(tenant_id)
                cached.delete()
        else:
            this_draft_key = document_key(
                tenant_id=tenant_id,
                student_id=draft.student_id,
                draft_id=draft.id,
                filename=_ARTEFACT_FILENAME,
            )
            if cached.object_key == this_draft_key:
                return RenderOutcome(object_key=cached.object_key, called_remote=False)
            # Cross-draft hit: same payload, different draft. download_document
            # re-derives its key from draft_id (apps/documents/storage.py), so
            # handing back the cached key verbatim would be a permanent 404
            # for this draft. Re-store the bytes we just fetched under THIS
            # draft's key -- the cache exists to protect europa.eu, not S3,
            # so an extra GET+PUT here is the right trade.
            new_key = store_document(
                draft=draft, filename=_ARTEFACT_FILENAME, content=cached_pdf, store=store_obj
            )
            return RenderOutcome(object_key=new_key, called_remote=False)

    circuit = EuropassCircuit.load()
    if circuit.is_open():
        raise CircuitOpen(f"Europass rendering paused: {circuit.reason}")

    try:
        artifact = render_draft(draft=draft)
    except EuropassThrottled as error:
        _open_circuit(error.retry_after_seconds, "throttled by europa.eu")
        raise
    except EuropassProvenanceMissing:
        # NOT an availability problem, so it must not count toward the
        # breaker: europa.eu is up, it just handed us something that is not
        # a Europass document. Re-raised so SQS redelivers it to the DLQ,
        # which is the alarm that means "go read the canary".
        raise
    except RenderRateLimited:
        # Also not an availability problem: this is OUR OWN per-student
        # limiter firing before we ever reached europa.eu. Counting it would
        # let one student's approval burst park every other tenant's queue.
        # Re-raised so SQS redelivers once the student's window rolls over.
        raise
    except EuropassUnavailable:
        circuit.consecutive_failures += 1
        # ponytail: unlocked read-modify-write on the shared counter. Safe
        # only because exactly one pinned worker ever calls this
        # (DesiredCount: 1, enforced by Tasks 5/6) -- add select_for_update()
        # on EuropassCircuit here if that ever stops being true.
        if circuit.consecutive_failures >= _FAILURE_THRESHOLD:
            circuit.paused_until = timezone.now() + timedelta(seconds=_FAILURE_PAUSE_SECONDS)
            circuit.reason = "consecutive failures"
            circuit.save(update_fields=["consecutive_failures", "paused_until", "reason"])
        else:
            circuit.save(update_fields=["consecutive_failures"])
        raise

    if circuit.consecutive_failures:
        circuit.consecutive_failures = 0
        circuit.save(update_fields=["consecutive_failures"])

    pdf = artifact.pdf_bytes
    if pdf is None:  # pragma: no cover - EUROPASS_API always yields bytes
        raise EuropassUnavailable("Europass render produced no PDF")
    with transaction.atomic():
        set_local_tenant(tenant_id)
        object_key = store_document(
            draft=draft, filename=_ARTEFACT_FILENAME, content=pdf, store=store
        )
        EuropassRenderCache.objects.create(payload_hash=digest, object_key=object_key)
    return RenderOutcome(object_key=object_key, called_remote=True)
