import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Protocol

from django.utils import timezone

from apps.funding.models import OfficialEvidenceClaim, OfficialSource, OfficialSourceSnapshot

from .egress import FetchResult
from .harvest import change_digest


class ObjectStore(Protocol):
    def put(self, key: str, body: bytes) -> str: ...


def archive_marker(fetch: FetchResult) -> SimpleNamespace | None:
    """`render_metadata` for a page that came from a capture, else None.

    Spec §6: an `Outcome.ARCHIVED` page must land as `ARCHIVE:<capture date>`.
    `retrieve_official_source` returns ARCHIVED as SERVED and the page's
    `final_url` is the ORIGINAL url, so a capture up to a year old
    (`FETCH_ARCHIVE_MAX_AGE_DAYS`) arrives at every consumer looking exactly
    like a live fetch -- and `retrieved_at` says when WE read it, never when
    the page was. This is the one marker; two consumers writing their own
    would be two formats to read.

    `archive.py` is the sole producer of `captured_at` and emits a `%Y-%m-%d`
    date (10 chars), never a 14-digit Wayback timestamp, so `ARCHIVE:` + that
    date is 18 characters and fits `render_status`'s 20-character column with
    room to spare.
    """
    captured_at = getattr(fetch, "captured_at", "") or ""
    return SimpleNamespace(status=f"ARCHIVE:{captured_at}") if captured_at else None


@dataclass(frozen=True)
class SnapshotResult:
    snapshot: OfficialSourceSnapshot
    s3_key: str
    s3_version_id: str
    sha256: str
    content_sha256: str
    final_url: str
    redirect_chain: tuple[str, ...]
    byte_size: int
    admissions_cycle: str


def persist_snapshot(
    *,
    source: OfficialSource,
    fetch: FetchResult,
    store: ObjectStore,
    admissions_cycle: str,
    retrieved_at: datetime | None = None,
    render_metadata: object | None = None,
    discovery_technique: str | None = None,
) -> SnapshotResult:
    digest = hashlib.sha256(fetch.body).hexdigest()
    content = change_digest(fetch.content_type, fetch.body)
    key = f"official-sources/{source.id}/{digest}"
    version_id = store.put(key, fetch.body)
    previous = (
        OfficialSourceSnapshot.objects.filter(source=source, reviewed_at__isnull=False)
        .order_by("-retrieved_at")
        .first()
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key=key,
        s3_version_id=version_id,
        sha256=digest,
        content_sha256=content,
        final_url=fetch.final_url,
        redirect_chain=list(fetch.redirects),
        retrieved_at=retrieved_at or timezone.now(),
        admissions_cycle=admissions_cycle,
        content_type=fetch.content_type,
        byte_size=len(fetch.body),
        dom_object_key=getattr(render_metadata, "dom_key", None),
        screenshot_object_key=getattr(render_metadata, "screenshot_key", None),
        render_status=getattr(render_metadata, "status", None),
        supersedes=previous,
        discovery_technique=discovery_technique,
        fetched_via=fetch.fetched_via,
    )
    return SnapshotResult(
        snapshot=snapshot,
        s3_key=key,
        s3_version_id=version_id,
        sha256=digest,
        content_sha256=content,
        final_url=fetch.final_url,
        redirect_chain=tuple(fetch.redirects),
        byte_size=len(fetch.body),
        admissions_cycle=admissions_cycle,
    )


def is_stale(
    checked_at: datetime,
    *,
    now: datetime | None = None,
    max_age: timedelta = timedelta(days=30),
) -> bool:
    return (now or timezone.now()) - checked_at > max_age


#: Design §2.5's per-claim-class freshness windows (§7.1).
CLAIM_MAX_AGE = {
    "IDENTITY": timedelta(days=365),
    "STRUCTURE": timedelta(days=180),
    #: Entry requirements are restated per admissions cycle, not per year.
    "ELIGIBILITY": timedelta(days=180),
    "TUITION": timedelta(days=90),
    "FUNDING": timedelta(days=30),
    "DEADLINE": timedelta(days=30),
}
#: An unclassified claim gets the tightest window, never the loosest.
_DEFAULT_MAX_AGE = min(CLAIM_MAX_AGE.values())


def claim_is_stale(claim: OfficialEvidenceClaim, *, now: datetime | None = None) -> bool:
    max_age = CLAIM_MAX_AGE.get(claim.claim_class or "", _DEFAULT_MAX_AGE)
    return is_stale(claim.last_checked_at, now=now, max_age=max_age)


def fresh_claims(
    claims: Iterable[OfficialEvidenceClaim], *, now: datetime | None = None
) -> list[OfficialEvidenceClaim]:
    """The claims that may still be shown; a stale one never enters a pack (§7.1)."""
    return [claim for claim in claims if not claim_is_stale(claim, now=now)]


def touch_claims(snapshot: OfficialSourceSnapshot, *, now: datetime | None = None) -> int:
    """Revalidate a snapshot's claims in place when the page is byte-identical.

    This is the other half of §7.1: a claim past its window is *revalidated* or
    dropped. Re-fetching an unchanged page is a revalidation, not new evidence,
    so last_checked_at moves and no duplicate row is written.
    """
    return OfficialEvidenceClaim.objects.filter(snapshot=snapshot).update(
        last_checked_at=now or timezone.now()
    )


