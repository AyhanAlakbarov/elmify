"""DOI -> bibliographic record, from Crossref then OpenAlex.

Everything here is mechanically derived: the registries are publisher-deposited
and re-checkable at any time, so no model reads anything on this path and the
resulting facts need no human confirmation.

Author ORDER is preserved exactly, because PublicationEntry.self_author_index
indexes into it. Which author is the applicant is never decided here -- name
matching cannot distinguish "Abdullayev O." from a co-author's similar surname,
which is why the schema stores an index the student picks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .sources import DoiRef
from .transport import Transport, Urllib3Transport

_CROSSREF = "https://api.crossref.org/works/"
_OPENALEX = "https://api.openalex.org/works/https://doi.org/"


class PublicationNotFound(LookupError):
    """Neither registry has a usable record for this DOI."""


@dataclass(frozen=True)
class PublicationRecord:
    doi: str
    title: str
    venue: str | None
    year: int | None
    #: The locator a citation needs. These reach PublicationEntry and the
    #: ledger, so a rendered citation can print "15 (6), 4739-4745" instead of
    #: a placeholder. `publisher` is deliberately still absent: a journal
    #: citation does not print it, so nothing would read it.
    volume: str | None
    issue: str | None
    pages: str | None
    authors: tuple[str, ...]
    work_type: str | None


def _from_crossref(doi: str, body: dict[str, Any]) -> PublicationRecord | None:
    message = body.get("message") or {}
    titles = message.get("title") or []
    authors = tuple(
        f"{entry.get('given', '')} {entry.get('family', '')}".strip()
        for entry in (message.get("author") or [])
    )
    if not titles or not any(authors):
        return None
    issued = (message.get("issued") or {}).get("date-parts") or [[None]]
    containers = message.get("container-title") or []
    return PublicationRecord(
        doi=doi,
        title=titles[0],
        venue=containers[0] if containers else None,
        year=issued[0][0],
        volume=message.get("volume"),
        issue=message.get("issue"),
        pages=message.get("page"),
        authors=authors,
        work_type=message.get("type"),
    )


def _from_openalex(doi: str, body: dict[str, Any]) -> PublicationRecord | None:
    authors = tuple(
        (entry.get("author") or {}).get("display_name", "").strip()
        for entry in (body.get("authorships") or [])
    )
    title = body.get("title")
    if not title or not any(authors):
        return None
    biblio = body.get("biblio") or {}
    first, last = biblio.get("first_page"), biblio.get("last_page")
    source = (body.get("primary_location") or {}).get("source") or {}
    return PublicationRecord(
        doi=doi,
        title=title,
        venue=source.get("display_name"),
        year=body.get("publication_year"),
        volume=biblio.get("volume"),
        issue=biblio.get("issue"),
        # OpenAlex splits the range Crossref deposits as one string.
        pages=f"{first}-{last}" if first and last else None,
        authors=authors,
        work_type=body.get("type"),
    )


def fetch_publication(
    ref: DoiRef, *, transport: Transport | None = None
) -> PublicationRecord:
    """Crossref first; OpenAlex covers conference papers Crossref lacks.

    A record without a title or a byline is not returned. A publication whose
    authors we cannot read cannot support an authorship claim, and an error
    must never become a partial fact.
    """
    client = transport if transport is not None else Urllib3Transport()
    status, body = client.get_json(f"{_CROSSREF}{ref.doi}")
    if status == 200:
        record = _from_crossref(ref.doi, body)
        if record is not None:
            return record
    status, body = client.get_json(f"{_OPENALEX}{ref.doi}")
    if status == 200:
        record = _from_openalex(ref.doi, body)
        if record is not None:
            return record
    raise PublicationNotFound(ref.doi)
