# apps/documents/transcript_pages.py
"""A transcript is a set of pages (spec 2026-10-03 §3.1). Each upload is read once into
TranscriptPage rows -- the cache that keeps a redelivery, a retake of another page or a new
reading from re-reading or re-billing a page -- and charged to its cycle's allowance once.

Every slow step (the file download, the parser, Azure) runs outside a transaction; each write is
a short one under the tenant's RLS scope, with the cycle row locked where slots or the allowance
change, so two uploads finishing together cannot take the same slot or overspend the allowance.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.concierge.cycles import paid_cycle
from apps.concierge.documents import (
    DocumentUnavailable,
    ReadableObjectStore,
    open_document,
    register,
)
from apps.concierge.models import DocumentVersion, StudentCycle
from apps.research.decisions import Client, DecisionsUnavailable
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.middleware import deletion_lock_target
from apps.tenancy.models import Membership

from .azure_layout import AzureLayout, analyze_layout
from .models import TranscriptPage, TranscriptReading, TranscriptUpload
from .ocr import InventoryPage, OcrPage, PageRead, inventory, read_inventory
from .ocr_errors import OcrUnavailable, PageRefused
from .transcript import (
    TranscriptReadingDisabled,
    academic_record,
    check_gates,
    personal_names,
    read_from_pages,
)
from .transcript_checks import highlights, key_numbers

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10_000_000
#: Delays before an upload is FAILED: 5 min doubling to a 6-hour cap -- about a day and a half
#: in all.
MAX_ATTEMPTS = 12
_FIRST_DELAY = timedelta(minutes=5)
_LONGEST_DELAY = timedelta(hours=6)
_LEASE = timedelta(minutes=10)
#: The ISO-BMFF brands an iPhone photo carries at bytes 4-12 (HEIC/HEIF).
_HEIC_BRANDS = frozenset(
    {b"ftypheic", b"ftypheix", b"ftypheim", b"ftypheis", b"ftyphevc", b"ftypmif1", b"ftypmsf1"}
)
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_WORD = re.compile(r"[^\W\d_]+")
#: Words of a Turkish or Azerbaijani transcript. "not" and "akts" are left out on purpose: the
#: first is English, the second is often left untranslated in an English transcript.
#: Words that are often part of a proper name an English translation keeps ("Orta Doğu Teknik
#: Üniversitesi", "Fen Edebiyat Fakültesi", "Kimya Bölümü") are left out too.
_ORIGINAL_WORDS_RAW = (
    "ders dersin kredi kredisi notu dönem dönemi yarıyıl yariyil toplam ortalama ve ile için "
    "öğrenci ogrenci adı soyadı fənn fənnin fənlər kredit qiymət "
    "semestr və üzrə cəmi tələbə ixtisas balı"
)


def _fold(word: str) -> str:
    """One key for a word in either case: Python folds İ to i + U+0307 and I to i, never to ı."""
    return word.casefold().replace("\u0307", "").replace("ı", "i")


_ORIGINAL_WORDS = frozenset(_fold(word) for word in _ORIGINAL_WORDS_RAW.split())
_LETTER = re.compile(r"[^\W\d_]")

State = TranscriptUpload.State


class _Refused(Exception):
    def __init__(self, reason: str, page: int | None = None) -> None:
        super().__init__(reason)
        self.reason, self.page = reason, page


class _OverCeiling(Exception):
    pass


class _ErasureRequested(Exception):
    pass


#: Refusals that come after the charge but before any page is placed: the charge is given back.
_REFUNDED_REFUSALS = frozenset({"replaced", "newer_upload"})


#: The presigned form lives 900 s, plus scan time; a PENDING upload older than this is stalled.
_PENDING_WINDOW = timedelta(minutes=20)


def replace_pending(cycle: StudentCycle) -> bool:
    """A REPLACE is visibly progressing, so a new upload would only be refused behind it.

    Correctness does not depend on this gate: `_reserve` and `_write` make a REPLACE refuse
    itself ("newer_upload") when any upload of the cycle was created after it. The gate only
    spares the student that refused REPLACE, so it stops blocking once a REPLACE has stalled:
    a READING one whose lease lapsed (worker died) or a PENDING one older than the window.
    """
    State = TranscriptUpload.State
    now = timezone.now()
    return TranscriptUpload.objects.filter(cycle=cycle, mode=TranscriptUpload.Mode.REPLACE).filter(
        Q(state=State.DELAYED)
        | Q(state=State.READING, next_attempt_at__gt=now)
        | Q(state=State.PENDING, created_at__gt=now - _PENDING_WINDOW)
    ).exists()


_ROLES = frozenset({"ORIGINAL", "TRANSLATION"})
_MODES = frozenset({"ADD", "RETAKE", "REPLACE"})
_LANGUAGES = frozenset({"az", "tr", "ru"})


class TranscriptRegistrationRefused(Exception):
    """A transcript upload refused before any row is written: an HTTP status and a stable code."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def register_transcript(student: Membership, body: dict[str, object]) -> DocumentVersion:
    """Register a transcript upload for the student's paid cycle -- the one way in, whichever door.

    Spec R13: nothing is read for an unpaid profile (402 cycle_unpaid). The cycle row is locked so
    two uploads cannot both slip past a REPLACE the other registers (409 replace_pending), and the
    DocumentVersion and its TranscriptUpload are written in the same transaction.
    """
    cycle = paid_cycle(student.id)
    if cycle is None:
        raise TranscriptRegistrationRefused(402, "cycle_unpaid")
    with transaction.atomic():
        StudentCycle.objects.select_for_update().get(id=cycle.id)
        if replace_pending(cycle):
            raise TranscriptRegistrationRefused(409, "replace_pending")
        fields = _transcript_upload(body, cycle)
        document = register(student.tenant_id, student.id, kind="TRANSCRIPT")
        TranscriptUpload.objects.create(student=student, document=document, cycle=cycle, **fields)
    return document


def _transcript_upload(body: dict[str, object], cycle: StudentCycle) -> dict[str, object]:
    """The TranscriptUpload fields a request asks for, or the refusal it earns."""
    role = body.get("role")
    if not isinstance(role, str) or role not in _ROLES:
        raise TranscriptRegistrationRefused(400, "invalid_role")
    mode = body.get("mode", "ADD")
    if not isinstance(mode, str) or mode not in _MODES:
        raise TranscriptRegistrationRefused(400, "invalid_mode")
    language = body.get("language", "")
    if not isinstance(language, str) or (
        language and (language not in _LANGUAGES or role != "ORIGINAL")
    ):
        raise TranscriptRegistrationRefused(400, "invalid_language")
    slot = body.get("slot")
    if mode != "RETAKE":
        if slot is not None:
            raise TranscriptRegistrationRefused(400, "invalid_slot")
        return {"role": role, "mode": mode, "language": language, "retake_slot": None}
    if not isinstance(slot, int) or isinstance(slot, bool) or slot < 1:
        raise TranscriptRegistrationRefused(400, "invalid_slot")
    page = TranscriptPage.objects.filter(cycle=cycle, slot=slot, superseded_at__isnull=True).first()
    if page is None:
        raise TranscriptRegistrationRefused(404, "slot_not_found")
    if page.retakes >= settings.TRANSCRIPT_MAX_RETAKES:
        raise TranscriptRegistrationRefused(409, "retakes_used")
    return {"role": role, "mode": mode, "language": language, "retake_slot": slot}

def _newer_upload_exists(upload: TranscriptUpload) -> bool:
    """An upload created after this one that can still place pages (or already has).

    Not counted: a byte-identical one (it never places pages of its own), a refused or failed
    one with no pages, and a PENDING one that was abandoned (old, and its file never arrived).
    """
    State = TranscriptUpload.State
    now = timezone.now()
    newer = TranscriptUpload.objects.filter(
        cycle_id=upload.cycle_id, created_at__gt=upload.created_at
    ).exclude(id=upload.id)
    if upload.file_sha256:
        newer = newer.exclude(file_sha256=upload.file_sha256)
    return newer.filter(
        Q(pages__isnull=False)
        | Q(state__in=(State.READING, State.DELAYED, State.READ))
        | Q(state=State.PENDING)
        & (Q(created_at__gt=now - _PENDING_WINDOW) | Q(document__state="AVAILABLE"))
    ).exists()


def _erasing(student: Membership) -> bool:
    """The student asked to be erased, or their membership ended: nothing more of theirs is read
    or sent to Azure or Jev (the same lock the dashboard and the extension apply)."""
    return not student.active or deletion_lock_target(student) is not None


def is_english(page: OcrPage) -> bool:
    """A translation office's PDF often binds the English translation with a copy of the
    original (R5), whose pages are skipped -- on evidence only, since a translation upload is
    expected to be English. The evidence is Cyrillic over 20% of the letters, or three distinct
    words of the Turkish/Azerbaijani transcript vocabulary -- distinct, so one name repeated down
    the page cannot reach three. A share of non-ASCII letters cannot do this:
    a Turkish page with ASCII course names ("Genel Kimya") has few, and an English page naming
    Azerbaijani people and universities has many (measured by the reviewer)."""
    cells = (cell for table in page.tables for row in table for cell in row)
    text = unicodedata.normalize("NFC", " ".join([*page.lines, *cells]))
    letters = len(_LETTER.findall(text))
    if len(_CYRILLIC.findall(text)) > 0.2 * letters:
        return False
    words = {_fold(word) for word in _WORD.findall(text)}
    return len(words & _ORIGINAL_WORDS) < 3


def _reopen_assembly(upload: TranscriptUpload) -> None:
    """An upload that ends REFUSED or FAILED may have been the one an earlier upload was waiting
    for: that earlier upload marked itself assembled without a reading and nothing would ever
    build one. Any READ upload that finished after the cycle's newest reading, with no reading of
    its own, is such a waiter; reopen the one that finished last so the resume sweep rebuilds the
    reading from every live page. Called inside the cycle lock, from the one place each of those
    states is written."""
    readings = TranscriptReading.objects.filter(cycle_id=upload.cycle_id)
    newest = readings.aggregate(newest=Max("created_at"))["newest"]
    waiters = (
        TranscriptUpload.objects.filter(cycle_id=upload.cycle_id, state=State.READ, assembled=True)
        .exclude(id=upload.id)
        .exclude(document_id__in=readings.values("document_id"))
    )
    if newest is not None:
        waiters = waiters.filter(updated_at__gt=newest)
    last = waiters.order_by("-updated_at").first()
    if last:
        TranscriptUpload.objects.filter(id=last.id).update(
            assembled=False, next_attempt_at=None, updated_at=timezone.now()
        )


def _refund(cycle: StudentCycle, upload: TranscriptUpload) -> None:
    """Spec §7.1 counts pages read: an upload whose pages were never written gives its charge
    back; a READ upload's pages stay live and stay charged. Under the cycle lock."""
    if upload.state != State.READ and upload.pages_counted:
        cycle.pages_used = max(0, cycle.pages_used - upload.pages_counted)
        cycle.save(update_fields=["pages_used"])
        upload.pages_counted = None


def _settle_twins(
    upload: TranscriptUpload, state: str, refusal: str, page: int | None = None
) -> None:
    """A byte-identical double tap marked READ with no pages was waiting on this upload, which
    will now never write them: the twin ends the same way. It was never charged, so no refund.
    Before _reopen_assembly, so its state=READ filter skips the twin and finds the real waiter."""
    if upload.state != State.READ and upload.file_sha256:
        TranscriptUpload.objects.filter(
            cycle_id=upload.cycle_id, file_sha256=upload.file_sha256, state=State.READ,
            pages_counted__isnull=True, pages__isnull=True,
        ).exclude(id=upload.id).update(
            state=state, refusal=refusal, refusal_page=page, updated_at=timezone.now()
        )


def _fail(cycle: StudentCycle, upload: TranscriptUpload, refusal: str) -> None:
    """The one way into FAILED, under the cycle lock (cycle before upload)."""
    _refund(cycle, upload)
    _settle_twins(upload, State.FAILED, refusal)
    upload.state, upload.refusal, upload.next_attempt_at = State.FAILED, refusal, None
    _reopen_assembly(upload)


def delay(tenant_id: UUID, upload_id: UUID, *, reason: str) -> None:
    """Azure or Jev did not answer, or the tenant's daily ceiling is reached (spec §4, §7.1): the
    upload waits and the resume sweep retries it -- after MAX_ATTEMPTS, it has FAILED. An upload
    whose pages are already written keeps READ and only waits for its reading to be assembled."""
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        cycle_id = (
            TranscriptUpload.objects.filter(id=upload_id).values_list("cycle_id", flat=True).first()
        )
        if cycle_id is None:
            return
        cycle = StudentCycle.objects.select_for_update().get(id=cycle_id)  # cycle before upload
        upload = TranscriptUpload.objects.select_for_update().filter(id=upload_id).first()
        if upload is None or upload.state in (State.REFUSED, State.FAILED):
            return
        if upload.state == State.READ and upload.assembled:
            return
        upload.attempts += 1
        if upload.attempts >= MAX_ATTEMPTS:
            _fail(cycle, upload, "reader_unavailable")
        else:
            if upload.state != State.READ:
                upload.state = State.DELAYED
            upload.next_attempt_at = timezone.now() + min(
                _FIRST_DELAY * 2 ** (upload.attempts - 1), _LONGEST_DELAY
            )
        upload.save(update_fields=[
            "state", "refusal", "attempts", "next_attempt_at", "pages_counted", "updated_at",
        ])
    logger.warning(
        "TranscriptDelayed upload=%s attempts=%s reason=%s", upload_id, upload.attempts, reason
    )


def read_upload(
    tenant_id: UUID,
    upload_id: UUID,
    *,
    store: ReadableObjectStore | None = None,
    analyze: Callable[..., AzureLayout] = analyze_layout,
) -> bool:
    """Read one upload into pages. True once its pages are written (now or before)."""
    try:
        upload = _claim(tenant_id, upload_id)
    except _ErasureRequested:
        _finish(tenant_id, upload_id, State.FAILED, "erasure_requested")
        return False
    if upload is None:
        return False
    if upload.state == State.READ:
        return True
    try:
        check_gates()
    except TranscriptReadingDisabled:
        _finish(tenant_id, upload.id, State.FAILED, "reading_off")
        return False
    try:
        _read(tenant_id, upload, store=store, analyze=analyze)
    except (_Refused, PageRefused) as refused:
        _finish(tenant_id, upload.id, State.REFUSED, refused.reason, refused.page)
        return False
    except DocumentUnavailable:
        _finish(tenant_id, upload.id, State.FAILED, "document_unavailable")
        return False
    except _ErasureRequested:
        _finish(tenant_id, upload.id, State.FAILED, "erasure_requested")
        return False
    except (OcrUnavailable, _OverCeiling, ClientError, BotoCoreError) as error:
        delay(tenant_id, upload.id, reason=type(error).__name__)
        return False
    return True


def _claim(tenant_id: UUID, upload_id: UUID) -> TranscriptUpload | None:
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        upload = (
            TranscriptUpload.objects.select_for_update(of=("self",))
            .select_related("document", "student")
            .filter(id=upload_id)
            .first()
        )
        if upload is None or upload.state in (State.REFUSED, State.FAILED):
            return None
        if _erasing(upload.student):
            raise _ErasureRequested()
        if upload.state == State.READ:
            return upload  # assembly backoff is the sweep's business, not this reading's
        now = timezone.now()
        if upload.next_attempt_at is not None and upload.next_attempt_at > now:
            return None
        # A lease: a concurrent redelivery or sweep finds the upload not due; a crashed run
        # is picked up again once it lapses. _write, _finish and delay replace it.
        upload.state, upload.next_attempt_at = State.READING, now + _LEASE
        upload.save(update_fields=["state", "next_attempt_at", "updated_at"])
        return upload


def _finish(
    tenant_id: UUID, upload_id: UUID, state: str, refusal: str, page: int | None = None
) -> None:
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        cycle_id = (
            TranscriptUpload.objects.filter(id=upload_id).values_list("cycle_id", flat=True).first()
        )
        if cycle_id is None:
            return
        cycle = StudentCycle.objects.select_for_update().get(id=cycle_id)  # cycle before upload
        upload = TranscriptUpload.objects.select_for_update().filter(id=upload_id).first()
        if upload is None:
            return
        if state == State.FAILED:
            _fail(cycle, upload, refusal)
        else:
            if refusal in _REFUNDED_REFUSALS:
                _refund(cycle, upload)
            _settle_twins(upload, state, refusal, page)
            upload.state, upload.refusal, upload.next_attempt_at = state, refusal, None
            _reopen_assembly(upload)
        upload.refusal_page = page
        upload.save(update_fields=[
            "state", "refusal", "refusal_page", "next_attempt_at", "pages_counted", "updated_at",
        ])
    logger.warning("TranscriptUpload%s upload=%s reason=%s", state.title(), upload_id, refusal)


def _read(
    tenant_id: UUID,
    upload: TranscriptUpload,
    *,
    store: ReadableObjectStore | None,
    analyze: Callable[..., AzureLayout],
) -> None:
    content = open_document(upload.document, store=store)
    if len(content) > MAX_UPLOAD_BYTES:
        raise _Refused("unsupported_file")
    if content[4:12] in _HEIC_BRANDS:
        raise _Refused("heic")
    if not content.startswith((b"%PDF", b"\x89PNG", b"\xff\xd8\xff")):
        raise _Refused("unsupported_file")
    digest = hashlib.sha256(content).hexdigest()
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        TranscriptUpload.objects.filter(id=upload.id).update(file_sha256=digest)
        duplicate = TranscriptPage.objects.filter(
            cycle_id=upload.cycle_id, upload__file_sha256=digest, superseded_at__isnull=True
        ).exists()
    if duplicate:
        if upload.mode == TranscriptUpload.Mode.RETAKE:
            raise _Refused("same_file")
        _write(tenant_id, upload, ())  # the same file again: nothing read, nothing charged
        return
    pages = inventory(upload.document, content)
    if upload.mode == TranscriptUpload.Mode.RETAKE:
        if len(pages) != 1:
            raise _Refused("retake_one_page")
        _check_retake(tenant_id, upload)
    if _reserve(tenant_id, upload.id, len(pages)):
        _write(tenant_id, upload, ())  # a double tap of an upload still in flight
        return
    _check_ceiling(tenant_id, pages)
    reads = read_inventory(content, pages, locale=upload.language or None, analyze=analyze)
    _write(tenant_id, upload, reads)


def _check_retake(tenant_id: UUID, upload: TranscriptUpload) -> None:
    """Refuse a retake that cannot succeed before it is charged; _write re-checks under the lock."""
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        old = TranscriptPage.objects.filter(
            cycle_id=upload.cycle_id, superseded_at__isnull=True, slot=upload.retake_slot or 0
        ).first()
    if old is None:
        raise _Refused("slot_not_found")
    if old.retakes >= settings.TRANSCRIPT_MAX_RETAKES:
        raise _Refused("retakes_used")


def _reserve(tenant_id: UUID, upload_id: UUID, count: int) -> bool:
    """Charge the pages to the cycle once (spec §7.1): a redelivery finds pages_counted set.
    True when a byte-identical upload of the cycle is already charged: this one is free."""
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        cycle_id = TranscriptUpload.objects.values_list("cycle_id", flat=True).get(id=upload_id)
        cycle = StudentCycle.objects.select_for_update().get(id=cycle_id)  # same order as _write
        upload = TranscriptUpload.objects.select_for_update().get(id=upload_id)
        if upload.mode == TranscriptUpload.Mode.REPLACE and _newer_upload_exists(upload):
            # Before the charge, or before a revived charged REPLACE is re-read: no Azure call.
            raise _Refused("newer_upload")
        if upload.pages_counted is not None:
            return False
        twin = (
            TranscriptUpload.objects.filter(
                cycle_id=cycle_id, file_sha256=upload.file_sha256, pages_counted__isnull=False
            )
            .exclude(id=upload_id)
            .filter(state__in=(State.PENDING, State.READING, State.DELAYED))
            .exists()
            # The file may have been read since the check in _read, which ran before this lock.
            or TranscriptPage.objects.filter(
                cycle_id=cycle_id,
                upload__file_sha256=upload.file_sha256,
                superseded_at__isnull=True,
            ).exists()
        )
        if twin:
            if upload.mode == TranscriptUpload.Mode.RETAKE:
                raise _Refused("same_file")
            return True
        left = settings.TRANSCRIPT_PAGES_PER_CYCLE - cycle.pages_used
        if count > left:
            raise _Refused("allowance_exceeded", max(left, 0))
        cycle.pages_used += count
        cycle.save(update_fields=["pages_used"])
        upload.pages_counted = count
        upload.save(update_fields=["pages_counted", "updated_at"])
        return False


def _check_ceiling(tenant_id: UUID, pages: tuple[InventoryPage, ...]) -> None:
    # ponytail: soft cap -- concurrent uploads can overshoot it by the pages in flight;
    # reserve pages under a lock if the ceiling must be exact.
    wanted = sum(1 for page in pages if page.source == "image")
    if not wanted:
        return
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        used = TranscriptPage.objects.filter(source="azure", created_at__gte=midnight).count()
    if used + wanted > settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES:
        raise _OverCeiling()


def _fields(read: PageRead, role: str) -> dict[str, object]:
    azure = {"source": "azure", "api_version": settings.AZURE_DI_API_VERSION}
    if read.blank:
        return {"state": TranscriptPage.State.SKIPPED, "skipped_because": "blank", **azure}
    if read.page is None:
        return {"state": TranscriptPage.State.REFUSED, "refusal": read.refusal or "", **azure}
    origin = {"source": read.page.source, "api_version": read.page.api_version}
    if role == TranscriptUpload.Role.TRANSLATION and not is_english(read.page):
        return {
            "state": TranscriptPage.State.SKIPPED,
            "skipped_because": "original_language",
            **origin,
        }
    return {"state": TranscriptPage.State.READ, "page": read.page.model_dump(mode="json"), **origin}


def _write(tenant_id: UUID, upload: TranscriptUpload, reads: tuple[PageRead, ...]) -> None:
    now = timezone.now()
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        cycle = StudentCycle.objects.select_for_update().get(id=upload.cycle_id)  # serialises slots
        fresh = TranscriptUpload.objects.select_for_update().get(id=upload.id)
        if fresh.state == State.READ:
            return
        if _erasing(fresh.student):  # the membership may have ended while Azure was reading
            raise _ErasureRequested()
        # A REPLACE already written covers every upload sent before it, including one that was
        # still delayed: appending that one's pages now would put superseded courses back.
        replaced = (
            TranscriptUpload.objects.filter(
                cycle_id=cycle.id, mode=TranscriptUpload.Mode.REPLACE, pages__isnull=False
            )
            .exclude(id=fresh.id)
            .aggregate(newest=Max("created_at"))["newest"]
        )
        if replaced is not None and fresh.created_at < replaced:
            raise _Refused("replaced")
        # A REPLACE renumbers slots later uploads may target: never over newer uploads.
        if fresh.mode == TranscriptUpload.Mode.REPLACE and _newer_upload_exists(fresh):
            raise _Refused("newer_upload")
        live = TranscriptPage.objects.filter(cycle=cycle, superseded_at__isnull=True)
        if not reads:  # the same file again: nothing to place, and REPLACE must not clear the slots
            fresh.state, fresh.refusal, fresh.next_attempt_at = State.READ, "", None
            fresh.save(update_fields=["state", "refusal", "next_attempt_at", "updated_at"])
            return
        # A page the quality gate refused may be the table page: it goes to its retake slot.
        if (
            not any(read.page is not None and read.page.tables for read in reads)
            and not any(read.refusal for read in reads)
            and (
                fresh.mode == TranscriptUpload.Mode.REPLACE
                or not any(
                    page.page and page.page.get("tables") for page in live.filter(state="READ")
                )
            )
        ):
            raise _Refused("not_a_transcript", 1)
        retakes = 0
        if fresh.mode == TranscriptUpload.Mode.REPLACE:
            # Only the old transcript is replaced: what was sent before this REPLACE (its charge
            # stays: it was read). Nothing newer with pages exists (refused above).
            live.filter(upload__created_at__lt=fresh.created_at).update(superseded_at=now)
            first = 1
        elif fresh.mode == TranscriptUpload.Mode.RETAKE:
            old = live.filter(slot=fresh.retake_slot or 0).first()
            if old is None:
                raise _Refused("slot_not_found")
            if old.retakes >= settings.TRANSCRIPT_MAX_RETAKES:
                raise _Refused("retakes_used")
            old.superseded_at = now
            old.save(update_fields=["superseded_at"])
            first, retakes = old.slot, old.retakes + 1
        else:
            first = (live.aggregate(last=Max("slot"))["last"] or 0) + 1
        for offset, read in enumerate(reads):
            TranscriptPage.objects.create(
                student_id=fresh.student_id, cycle=cycle, upload=fresh, number=read.number,
                slot=first + offset, retakes=retakes, **_fields(read, fresh.role),
            )
        fresh.state, fresh.refusal, fresh.next_attempt_at = State.READ, "", None
        fresh.save(update_fields=["state", "refusal", "next_attempt_at", "updated_at"])


def assemble(tenant_id: UUID, upload_id: UUID, *, client: Client | None = None) -> None:
    """Rebuild the cycle's reading from its live pages, unless the transcript is not ready.

    Not ready means another upload of the cycle is still being read or waiting on Azure, or a
    refused page still has a retake left. The upload that finishes last assembles: each writes
    READ before it looks, so two finishing together both see the other done, and the cost of
    that race is one extra reading -- the newest is the student's. An upload registered and never
    sent stays PENDING and holds nothing back. A byte-identical twin has no pages of its own and
    assembles from the cycle's.
    """
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        upload = TranscriptUpload.objects.select_related("student").get(id=upload_id)
        # The cycle lock makes "is anything busy" and "mark myself assembled" one step against
        # _fail/_finish, which reopen assembly under the same lock (cycle before upload).
        cycle = StudentCycle.objects.select_for_update().get(id=upload.cycle_id)
        if _erasing(upload.student):
            locked = TranscriptUpload.objects.select_for_update().get(id=upload.id)
            _fail(cycle, locked, "erasure_requested")
            locked.save(update_fields=[
                "state", "refusal", "next_attempt_at", "pages_counted", "updated_at",
            ])
            logger.warning("TranscriptUploadFailed upload=%s reason=erasure_requested", upload.id)
            return
        busy = (
            TranscriptUpload.objects.filter(
                cycle_id=upload.cycle_id, state__in=(State.READING, State.DELAYED)
            )
            .exclude(id=upload.id)
            .exists()
        )
        live = list(
            TranscriptPage.objects.filter(cycle_id=upload.cycle_id, superseded_at__isnull=True)
            .select_related("upload")
            .order_by("slot")
        )
        waiting = any(
            page.state == TranscriptPage.State.REFUSED
            and page.retakes < settings.TRANSCRIPT_MAX_RETAKES
            for page in live
        )
        readable = [page for page in live if page.state == TranscriptPage.State.READ]
        translated = [p for p in readable if p.upload.role == TranscriptUpload.Role.TRANSLATION]
        readable = translated or readable
        if busy or waiting or not readable:
            TranscriptUpload.objects.filter(id=upload.id).update(
                assembled=True, next_attempt_at=None, updated_at=timezone.now()
            )
            return
        names = personal_names(upload.student)
    try:
        # read_upload returns before its gates for an upload already READ, so the provider check
        # and the Jev launch gate (spec T19, §3.1) are made again here, before anything is sent.
        check_gates()
        reading = read_from_pages(
            tuple(OcrPage.model_validate(page.page) for page in readable), names, client=client
        )
    except TranscriptReadingDisabled:
        # Stays READ and unassembled; the sweep resumes it once the gate reopens. Not an attempt.
        with tenant_scope(tenant_id), tenant_transaction(tenant_id):
            TranscriptUpload.objects.filter(id=upload.id).update(
                next_attempt_at=timezone.now() + timedelta(hours=1), updated_at=timezone.now()
            )
        logger.warning("TranscriptAssemblyGateClosed upload=%s", upload.id)
        return
    except DecisionsUnavailable as error:
        if error.kind == "refused":
            # The provider declined these pages and is never asked again (decisions.py): a
            # retry gets the same answer, so the upload fails now rather than after 12 delays.
            _finish(tenant_id, upload.id, State.FAILED, "reader_refused")
        else:
            delay(tenant_id, upload.id, reason="DecisionsUnavailable")
        return
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        # ponytail: the Jev call above can still run twice for a concurrent redelivery and sweep;
        # the lock only keeps the second from writing a second reading. Lease the assembly if
        # the duplicate cost matters.
        if TranscriptUpload.objects.select_for_update().get(id=upload.id).assembled:
            return
        TranscriptReading.objects.get_or_create(
            document_id=upload.document_id,
            defaults={
                "student_id": upload.student_id,
                "cycle_id": upload.cycle_id,
                "record": academic_record(reading.content),
                "highlights": [highlight.model_dump() for highlight in highlights(reading)],
                "key_numbers": key_numbers(reading).model_dump(mode="json"),
                "rows": [asdict(row) for row in reading.rows],
            },
        )
        TranscriptUpload.objects.filter(id=upload.id).update(
            assembled=True, next_attempt_at=None, updated_at=timezone.now()
        )


def process_upload(
    tenant_id: UUID,
    upload_id: UUID,
    *,
    store: ReadableObjectStore | None = None,
    analyze: Callable[..., AzureLayout] = analyze_layout,
    client: Client | None = None,
) -> None:
    """Read one upload into pages, then rebuild the cycle's reading. Safe to run again: pages are
    never read twice, the allowance is never charged twice, and a reading is one per upload."""
    if read_upload(tenant_id, upload_id, store=store, analyze=analyze):
        with tenant_scope(tenant_id), tenant_transaction(tenant_id):
            done = TranscriptUpload.objects.filter(id=upload_id, assembled=True).exists()
        if not done:
            assemble(tenant_id, upload_id, client=client)
