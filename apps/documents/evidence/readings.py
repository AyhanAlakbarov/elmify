"""The letter hand-off (CV evidence spec §11): checked readings, nothing else.

Every bullet here passed the quote and number checks; its support verdict
says whether Jev agreed (supported, rejected, unchecked). How a letter uses a
reading -- including whether it requires `supported` -- is the letter engine's
choice. Part B adds the undo filter and the matched CV entry here (§10.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from apps.tenancy.models import Membership

from . import facts


@dataclass(frozen=True)
class UsableBullet:
    text: str
    evidence: tuple[str, ...]
    verdict: str


@dataclass(frozen=True)
class UsableReading:
    source: str
    #: https://github.com/<owner>/<name> for a repo; None for an upload.
    url: str | None
    document_id: UUID | None
    summary: str
    kind: str
    names: tuple[str, ...]
    first_commit: str | None
    last_commit: str | None
    bullets: tuple[UsableBullet, ...]
    repo: str = ""
    methods: str | None = None
    outcomes: str | None = None
    owner_type: str = ""
    owner_name: str = ""
    commits: int = 0
    matched_target: str | None = None


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


def _usable(stored: facts.StoredReading) -> UsableReading:
    reading = stored.reading
    raw = reading.get("bullets")
    bullets = tuple(
        UsableBullet(str(b.get("text") or ""), _strings(b.get("evidence")),
                     str(b.get("verdict") or "unchecked"))
        for b in (raw if isinstance(raw, list) else [])
        if isinstance(b, dict) and b.get("text")
    )
    url = reading.get("url")
    first, last = reading.get("first_commit"), reading.get("last_commit")
    methods = reading.get("methods")
    outcomes = reading.get("outcomes")
    raw_origin = reading.get("origin")
    origin: dict[str, object] = raw_origin if isinstance(raw_origin, dict) else {}
    return UsableReading(
        source=stored.source_kind,
        url=url if isinstance(url, str) else None,
        document_id=stored.document_id,
        summary=str(reading.get("summary") or ""),
        kind=str(reading.get("kind") or ""),
        names=_strings(reading.get("names")),
        first_commit=first if isinstance(first, str) else None,
        last_commit=last if isinstance(last, str) else None,
        bullets=bullets,
        repo=stored.repo,
        methods=methods if isinstance(methods, str) and methods else None,
        outcomes=outcomes if isinstance(outcomes, str) and outcomes else None,
        owner_type=str(origin.get("owner_type") or ""),
        owner_name=str(origin.get("owner_name") or ""),
        commits=raw_commits if isinstance((raw_commits := origin.get("commits")), int) else 0,
    )


def reading_key(reading: UsableReading) -> str:
    if reading.source == "github":
        return f"github:{reading.repo.casefold()}"
    return f"pdf:{reading.document_id}"


def usable_readings(
    student: Membership,
    *,
    undone: frozenset[str] = frozenset(),
) -> tuple[UsableReading, ...]:
    """Every reading of this student, for a letter or CV placement. Call inside tenant_scope."""
    items = tuple(_usable(stored) for stored in facts.stored_readings(student))
    if not undone:
        return items
    return tuple(item for item in items if reading_key(item) not in undone)
