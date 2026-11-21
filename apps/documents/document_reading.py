"""Reading a student's own document into facts, on the document worker (spec
2026-10-12 §5, §6). Every slow step -- the file download, Azure -- runs outside a
transaction; each write is a short one under the tenant's RLS scope, the pattern
transcript_pages set. A reading is one row per (document, reader version): a
redelivered scan event, the resume sweep and the co-pilot's hook all land on the
same row, and the lease in _claim keeps two of them from reading it at once."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from django.conf import settings
from django.db import IntegrityError
from django.db.models import F, Sum
from django.utils import timezone

from apps.concierge.documents import DocumentUnavailable, ReadableObjectStore, open_document
from apps.concierge.models import DocumentVersion
from apps.ratelimit import rate_limited
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.middleware import deletion_lock_target

from . import fact_readers, text_reading
from .azure_layout import AzureIdResult, analyze_id_document
from .fact_readers import ReadersUnavailable
from .fact_writer import ONE_TAP, write_facts
from .id_reading import (
    OWNER_UNCHECKED,
    NotRead,
    ReadValue,
    known_owner_names,
    owner_birth_date,
    read_id,
)
from .models import DocumentReading, TranscriptPage
from .ocr_errors import OcrUnavailable, PageRefused
from .verification import unsuperseded_facts

logger = logging.getLogger(__name__)

State = DocumentReading.State
READER_VERSION = {"PASSPORT": "id-1", "DIPLOMA": "doc-1", "LANGUAGE_CERTIFICATE": "doc-1"}
READ_KINDS = frozenset(READER_VERSION)
MAX_UPLOAD_BYTES = 10_000_000
MAX_ATTEMPTS = 12
_FIRST_DELAY = timedelta(minutes=5)
_LONGEST_DELAY = timedelta(hours=6)
_LEASE = timedelta(minutes=10)
#: A wait for the shared ceiling or the student's hourly limit: not a failure,
#: so it never counts toward MAX_ATTEMPTS.
_WAIT = timedelta(hours=1)
#: How long after its upload a reading may keep waiting before it fails
#: "reader_unavailable" and the dashboard asks for a new upload.
_LONGEST_WAIT = timedelta(days=3)


class _Failed(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Wait(Exception):
    """Not now: the ceiling, the student's hourly limit. Retried by the sweep."""

    def __init__(self, reason: str = "rate_or_ceiling") -> None:
        super().__init__(reason)
        self.reason = reason


def _delay_reason(error: Exception) -> str:
    if isinstance(error, _Wait):
        return f"_Wait:{error.reason}"
    if isinstance(error, (OcrUnavailable, ReadersUnavailable)) and str(error):
        return f"{type(error).__name__}:{error}"
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", "unknown")
        return f"ClientError:{code}"
    return type(error).__name__


def enabled() -> bool:
    return settings.FACT_READING_ENABLED and settings.TRANSCRIPT_AZURE_ENABLED


def kind_enabled(kind: str) -> bool:
    """A passport needs Azure; a diploma or certificate also needs the reader pair."""
    if not enabled() or kind not in READ_KINDS:
        return False
    return kind == "PASSPORT" or fact_readers.readers_configured()


def azure_pages_today() -> int:
    """Azure pages this tenant was billed today, by either reader. Inside a tenant
    transaction: both tables are FORCE RLS."""
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    transcripts = TranscriptPage.objects.filter(source="azure", created_at__gte=midnight).count()
    documents = DocumentReading.objects.filter(azure_billed_at__gte=midnight).aggregate(
        pages=Sum("azure_pages")
    )["pages"] or 0
    return transcripts + documents


def queue_reading(tenant_id: UUID, document_id: UUID) -> bool:
    """The QUEUED row for an AVAILABLE upload of a kind we read. True when this
    call created it. Idempotent: the unique (document, reader_version) is the lock."""
    if not enabled():
        return False
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        document = DocumentVersion.objects.filter(
            id=document_id, state="AVAILABLE", kind__in=READ_KINDS
        ).first()
        if document is None or not kind_enabled(document.kind):
            return False
        _, created = DocumentReading.objects.get_or_create(
            document=document,
            reader_version=READER_VERSION[document.kind],
            defaults={"student_id": document.student_id, "kind": document.kind},
        )
        return created


def process_document(
    tenant_id: UUID,
    document_id: UUID,
    *,
    reading_id: UUID | None = None,
    store: ReadableObjectStore | None = None,
    analyze: Callable[..., AzureIdResult] = analyze_id_document,
    read_text: Callable[..., tuple[list[ReadValue], int]] = text_reading.read_text_document,
) -> None:
    if not enabled():
        return
    queue_reading(tenant_id, document_id)
    claimed = _claim(tenant_id, document_id, reading_id)
    if claimed is None:
        return
    reading, document = claimed
    billed = {"pages": 0}  # set once Azure has answered: every answer counts, read or not
    try:
        values, digest, pages = _read(
            tenant_id, reading, document, store=store, analyze=analyze, read_text=read_text,
            billed=billed,
        )
        with tenant_scope(tenant_id), tenant_transaction(tenant_id):
            locked = DocumentReading.objects.select_for_update().select_related("student").get(
                id=reading.id
            )
            _bill(locked, pages)
            if locked.state != State.READING:  # READ or FAILED meanwhile: never overwrite
                locked.save(update_fields=["azure_pages", "azure_billed_at", "updated_at"])
                return
            student = locked.student
            if not student.active or deletion_lock_target(student) is not None:
                locked.state, locked.failure = State.FAILED, "erasure_requested"
                locked.next_attempt_at = None
                locked.save(update_fields=["azure_pages", "azure_billed_at", "state", "failure",
                                           "next_attempt_at", "updated_at"])
                return
            locked.values = [v.as_dict() for v in values]
            locked.file_sha256 = digest
            locked.state, locked.failure, locked.next_attempt_at = State.READ, "", None
            locked.save(update_fields=["values", "file_sha256", "azure_pages", "azure_billed_at",
                                       "state", "failure", "next_attempt_at", "updated_at"])
            write_facts(locked)
    except _Failed as failed:
        _fail(tenant_id, reading.id, failed.code, pages=billed["pages"])
    except DocumentUnavailable:
        _fail(tenant_id, reading.id, "document_unavailable", pages=billed["pages"])
    except DocumentReading.DoesNotExist:
        return
    except IntegrityError:
        # A proof raced the student's correction (one-superseder constraint): the whole
        # write rolled back, so the reading is still READING; try again later.
        delay(tenant_id, reading.id, reason="IntegrityError", pages=billed["pages"])
    except Exception as error:  # noqa: BLE001 -- nothing may escape into the scan handler
        # Includes _Wait, OcrUnavailable, ReadersUnavailable and storage errors; the
        # type or sanitized code only, as raw messages can quote document text.
        if not isinstance(
            error, (_Wait, OcrUnavailable, ReadersUnavailable, ClientError, BotoCoreError)
        ):
            logger.warning("DocumentReadingError reading=%s error=%s", reading.id,
                           type(error).__name__)
        delay(tenant_id, reading.id, reason=_delay_reason(error), pages=billed["pages"],
              waiting=isinstance(error, _Wait))


def _claim(
    tenant_id: UUID, document_id: UUID, reading_id: UUID | None = None
) -> tuple[DocumentReading, DocumentVersion] | None:
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        rows = (
            DocumentReading.objects.select_for_update(of=("self",))
            .select_related("student", "document")
            .filter(document_id=document_id)
        )
        if reading_id is not None:
            # The row the sweep found. Without this an older reader version's DELAYED
            # row was swept every run and the newest row claimed instead.
            rows = rows.filter(id=reading_id)
        reading = rows.order_by("-created_at").first()
        if reading is None or reading.state in (State.READ, State.FAILED):
            return None
        student = reading.student
        if not student.active or deletion_lock_target(student) is not None:
            reading.state, reading.failure = State.FAILED, "erasure_requested"
            reading.save(update_fields=["state", "failure", "updated_at"])
            return None
        now = timezone.now()
        if reading.next_attempt_at is not None and reading.next_attempt_at > now:
            return None
        reading.state, reading.next_attempt_at = State.READING, now + _LEASE
        reading.save(update_fields=["state", "next_attempt_at", "updated_at"])
        return reading, reading.document


def _read(
    tenant_id: UUID,
    reading: DocumentReading,
    document: DocumentVersion,
    *,
    store: ReadableObjectStore | None,
    analyze: Callable[..., AzureIdResult],
    read_text: Callable[..., tuple[list[ReadValue], int]],
    billed: dict[str, int],
) -> tuple[list[ReadValue], str, int]:
    content = open_document(document, store=store)
    if len(content) > MAX_UPLOAD_BYTES:
        raise _Failed("unsupported_file")
    digest = hashlib.sha256(content).hexdigest()
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        # A twin read before the student had a name, or under a name it did not
        # match, proved nothing about whose passport it is: fixing the name and
        # uploading again must read again.
        twin = next(
            (
                t for t in DocumentReading.objects.filter(
                    student_id=reading.student_id, file_sha256=digest, state=State.READ,
                    reader_version=reading.reader_version, kind=reading.kind,
                ).exclude(id=reading.id)
                if not any(v.get("why") in OWNER_UNCHECKED for v in t.values or [])
            ),
            None,
        )
        if twin is not None:  # the same bytes again: nothing read, nothing billed
            return [ReadValue.from_dict(v) for v in twin.values], digest, 0
        cap = settings.FACT_READING_PAGE_CAPS[reading.kind]
        if cap > settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES:
            raise _Failed("reader_unavailable")  # it could never fit: waiting is for ever
        if azure_pages_today() + cap > settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES:
            raise _Wait("azure_daily_ceiling")
        known_names = _known_names(reading)
        known_dob = (
            owner_birth_date(
                reading.student, exclude_ref=f"document:{reading.document_id}"
            )
            if reading.kind == "PASSPORT"
            else None
        )
        identifiers = _identifiers(reading, known_names) if reading.kind != "PASSPORT" else []
    if reading.kind != "PASSPORT" and not fact_readers.readers_configured():
        # Queued before the pair was unset: wait, and fail after _LONGEST_WAIT; never
        # read with no readers. Before the student's hourly count, which a wait never spends.
        raise _Wait("readers_unconfigured")
    if rate_limited("fact-reading", reading.student_id, limit=settings.FACT_READING_HOURLY,
                    window_seconds=3600):
        raise _Wait("student_hourly_limit")
    if reading.kind != "PASSPORT":
        return _read_text(tenant_id, reading, document, content, digest, cap=cap,
                          identifiers=identifiers, read_text=read_text, billed=billed)
    try:
        result = analyze(content, pages=f"1-{cap}")
    except OcrUnavailable:
        if settings.AZURE_DI_ENDPOINT and settings.AZURE_DI_KEY:
            # The call may have reached Azure and been billed with no answer to
            # count from. ponytail: charge the cap, the safe over-count, until
            # Azure's own usage figure is read back.
            billed["pages"] = cap
        raise
    billed["pages"] = len(result.pages)
    try:
        values = read_id(
            result,
            known_names=known_names,
            known_birth_date=known_dob,
            threshold=settings.FACT_READING_CONFIDENCE,
            today=timezone.localdate(),
        )
    except NotRead as not_read:
        raise _Failed(not_read.code) from None
    return values, digest, len(result.pages)


def _read_text(
    tenant_id: UUID,
    reading: DocumentReading,
    document: DocumentVersion,
    content: bytes,
    digest: str,
    *,
    cap: int,
    identifiers: list[str],
    read_text: Callable[..., tuple[list[ReadValue], int]],
    billed: dict[str, int],
) -> tuple[list[ReadValue], str, int]:
    """A diploma or certificate (spec §5.3). read_text sets billed["pages"] the moment
    Azure answers, so a NotRead or ReadersUnavailable after it still bills (plan 1)."""
    # The per-tenant cost breaker CLAUDE.md requires of every LLM-calling path: one
    # count per document (at most four model calls: two readers, one retry each).
    # ponytail: a ReadersUnavailable retry analyses the pages again (billed again);
    # keep the layout on the reading if retries are ever measured to cost.
    if rate_limited("fact-reading-readers", tenant_id,
                    limit=settings.FACT_READING_TENANT_DAILY_CALLS, window_seconds=86400):
        raise _Wait("tenant_daily_reader_limit")
    try:
        values, pages = read_text(
            kind=reading.kind, document=document, content=content, identifiers=identifiers,
            threshold=settings.FACT_READING_CONFIDENCE, cap=cap, billed=billed,
        )
    except NotRead as not_read:
        raise _Failed(not_read.code) from None
    except ReadersUnavailable as unavailable:
        if str(unavailable) == "off_schema":
            # The model answered, twice, outside the schema (fact_readers retried once):
            # retrying would bill Azure again for an answer that will not come. Only a
            # transport failure (timeout, connection, 5xx, rate limit) waits and retries.
            raise _Failed("reader_unavailable") from None
        raise
    except PageRefused as refused:
        raise _Failed(
            "unsupported_file" if refused.reason == "page_too_large" else "unreadable"
        ) from None
    return values, digest, pages


def _identifiers(reading: DocumentReading, known_names: list[str]) -> list[str]:
    """What names the student, stripped from the readers' copy (spec §8): the whole
    names _known_names holds (the account holder's included), every name, date of birth,
    phone and ID document number in the ledger, confirmed or waiting, and the account's
    application e-mail. Place of birth, sex and citizenship stay out: they name places
    and categories, not the student, and stripping "Ganja" would break "Ganja State
    University" in the very quote the readers must find. Called inside a tenant
    transaction."""
    out = list(known_names)
    if reading.student.application_email:
        out.append(reading.student.application_email)
    for fact in unsuperseded_facts(reading.student).filter(category__in=ONE_TAP):
        for key in ("full_name", "given_names", "surname", "date_of_birth", "phone", "number"):
            value = fact.payload.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value)
    return out


def _known_names(reading: DocumentReading) -> list[str]:
    """Whole names we already hold for the student, to catch someone else's passport
    (spec §5.2.4): the account holder's own name, the CV's full name, and each earlier
    document's given names and surname joined. Never a bare surname -- the ownership
    check reads a one-word value as a given name, so ["ŞAHIN"] would vouch for any
    ŞAHIN. Never this document's own. Called inside a tenant transaction."""
    return known_owner_names(
        reading.student, exclude_ref=f"document:{reading.document_id}"
    )


def delay(tenant_id: UUID, reading_id: UUID, *, reason: str, pages: int = 0,
          waiting: bool = False) -> None:
    """Try again later. `waiting` is the ceiling or the hourly limit: an hour on,
    and not an attempt, or a busy day would fail a passport nothing was wrong with."""
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        reading = DocumentReading.objects.select_for_update().filter(id=reading_id).first()
        if reading is None or reading.state in (State.READ, State.FAILED):
            return
        _bill(reading, pages)
        reading.attempts += 0 if waiting else 1
        if waiting and timezone.now() + _WAIT > reading.created_at + _LONGEST_WAIT:
            reading.state, reading.failure, reading.next_attempt_at = (
                State.FAILED, "reader_unavailable", None)
        elif waiting:
            reading.state, reading.next_attempt_at = State.DELAYED, timezone.now() + _WAIT
        elif reading.attempts >= MAX_ATTEMPTS:
            reading.state, reading.failure, reading.next_attempt_at = (
                State.FAILED, "reader_unavailable", None)
        else:
            reading.state = State.DELAYED
            reading.next_attempt_at = timezone.now() + min(
                _FIRST_DELAY * 2 ** (reading.attempts - 1), _LONGEST_DELAY
            )
        reading.save(update_fields=["state", "failure", "attempts", "azure_pages",
                                    "azure_billed_at", "next_attempt_at", "updated_at"])
    logger.warning("DocumentReadingDelayed reading=%s attempts=%s reason=%s",
                   reading_id, reading.attempts, reason)


def _bill(reading: DocumentReading, pages: int) -> None:
    if pages:
        reading.azure_pages += pages
        reading.azure_billed_at = timezone.now()


def _fail(tenant_id: UUID, reading_id: UUID, code: str, *, pages: int = 0) -> None:
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        # Never over a READ or FAILED row: the lease may have expired and another worker
        # finished this reading while ours was failing.
        DocumentReading.objects.filter(id=reading_id).exclude(
            state__in=(State.READ, State.FAILED)
        ).update(
            state=State.FAILED, failure=code, next_attempt_at=None, updated_at=timezone.now(),
            azure_pages=F("azure_pages") + pages,
            azure_billed_at=timezone.now() if pages else F("azure_billed_at"),
        )
    logger.warning("DocumentReadingFailed reading=%s failure=%s", reading_id, code)
