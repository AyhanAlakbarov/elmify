"""Every database read and write of the evidence package (CV evidence spec §7.5, §9, §11).

The only module here that touches the database (tests/documents/evidence/
test_invariants.py pins it). Each function opens its own short
tenant_transaction: the document worker runs as runtime_engine behind FORCE
ROW LEVEL SECURITY, and refresh.py must never hold a transaction across an
HTTP or model call, so it calls these one at a time between them.

WHAT IS CONFIRMED. A publication from Crossref or OpenAlex is parsed with no
model in the path, so the student naming the DOI confirms it. Everything a
repo or thesis suggests -- languages included (decision 9) -- is an
unconfirmed SKILL fact the student accepts or drops. A reading is not a fact
at all: it lives in EvidenceReading, which nothing but this module reads, so
it never reaches the confirm list, tailoring, the portal profile or
generation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils import timezone

from apps.concierge.models import DocumentVersion
from apps.tenancy.db import tenant_transaction
from apps.tenancy.middleware import deletion_lock_target
from apps.tenancy.models import Membership

from ..models import EvidenceReading, VerifiedFact
from ..schemas import PublicationEntry, PublicationStatus, SkillEntry
from ..verification import fact_payload, unsuperseded_facts
from .extraction import Technique
from .github import login_from_identity
from .publication import PublicationRecord

#: Crossref and OpenAlex types recorded as published; anything else needs the student.
_PUBLISHED_TYPES = frozenset(
    {"journal-article", "proceedings-article", "book-chapter", "article"}
)
#: The source_ref of every IDENTITY row written for a typed or cleared login.
GITHUB_LOGIN_REF = "github-login"
#: Below this a language is a stray file (371 bytes of R must go, 828 of Shell stay).
_LANGUAGE_FLOOR_BYTES = 500
#: Ranked by per-file import count -- an alphabetical cut kept `ase` and dropped `torch`.
_MAX_LIBRARY_SKILLS = 15
_MAX_TECHNIQUE_SKILLS = 12
#: SkillEntry.name's ceiling.
_MAX_SKILL_NAME = 100
_HEADINGS = {
    "language": "Languages and tools",
    "library": "Libraries and frameworks",
    "technique": "Core competencies",
}
#: Namespaces the source_ref so a library and a language of one name stay two rows.
_PREFIXES = {"language": "", "library": "lib:", "technique": "method:"}


class UnusablePublication(ValueError):
    """The record cannot be recorded as a publication without a human."""


def publication_entry(record: PublicationRecord) -> PublicationEntry:
    """A registry record as a schema entry. self_author_index stays None: the student picks."""
    if record.work_type not in _PUBLISHED_TYPES:
        raise UnusablePublication(f"unrecognised work type: {record.work_type!r}")
    return PublicationEntry(
        authors=record.authors,
        self_author_index=None,
        title=record.title,
        venue=record.venue,
        year=record.year,
        volume=record.volume,
        issue=record.issue,
        pages=record.pages,
        doi=record.doi,
        status=PublicationStatus.PUBLISHED,
    )


def refreshable_student(tenant_id: UUID, student_id: UUID) -> Membership | None:
    """The active student, unless they asked to be erased (then nothing of theirs is read
    or sent to a model: the lock transcript_pages._erasing applies). Call inside
    tenant_scope."""
    with tenant_transaction(tenant_id):
        student = Membership.objects.filter(id=student_id, active=True).first()
        if student is None or deletion_lock_target(student) is not None:
            return None
        return student


def _previous(student: Membership, source_ref: str, category: str) -> VerifiedFact | None:
    return (
        VerifiedFact.objects.filter(
            student=student,
            source_ref=source_ref,
            category=category,
            superseded_by__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )


def write_publication_fact(*, student: Membership, record: PublicationRecord) -> VerifiedFact:
    entry = publication_entry(record)
    source_ref = f"doi:{record.doi}"
    with tenant_transaction(student.tenant_id):
        return VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.PUBLICATION,
            payload=fact_payload(entry, category=VerifiedFact.Category.PUBLICATION),
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref=source_ref,
            confirmed_by=student,
            confirmed_at=timezone.now(),
            supersedes=_previous(student, source_ref, VerifiedFact.Category.PUBLICATION),
            created_by=student,
        )


# --- skill suggestions ---------------------------------------------------------------


@dataclass(frozen=True)
class SkillSuggestion:
    name: str
    #: "language", "library" or "technique" -- what tailoring reads (SkillEntry.kind).
    kind: str
    #: What backs it, in words a student can check: "60731 bytes", "imported by 9
    #: files", or the verified excerpt that named a technique.
    evidence: str
    source_ref: str


def _import_evidence(count: int) -> str:
    if not count:
        return "declared in the project's manifest"
    return f"imported by {count} file{'s' if count != 1 else ''}"


def suggestions(
    *,
    source_ref: str,
    languages: Mapping[str, int],
    libraries: Iterable[tuple[str, int]],
    techniques: Iterable[Technique],
) -> tuple[SkillSuggestion, ...]:
    """What one reading proposes as skills. Pure: save_reading writes them."""

    def made(name: str, kind: str, evidence: str) -> SkillSuggestion:
        return SkillSuggestion(name, kind, evidence, f"{source_ref}#{_PREFIXES[kind]}{name}")

    found = [
        made(name, "language", f"{size} bytes")
        for name, size in sorted(languages.items())
        if size >= _LANGUAGE_FLOOR_BYTES
    ]
    ranked = sorted(libraries, key=lambda item: (-item[1], item[0]))[:_MAX_LIBRARY_SKILLS]
    found += [made(name, "library", _import_evidence(count)) for name, count in ranked]
    first: dict[str, Technique] = {}
    for technique in techniques:
        first.setdefault(technique.name, technique)
    found += [
        made(t.name, "technique", t.excerpt)
        for t in list(first.values())[:_MAX_TECHNIQUE_SKILLS]
    ]
    return tuple(s for s in found if len(s.name) <= _MAX_SKILL_NAME)


def _write_suggestions(student: Membership, skills: tuple[SkillSuggestion, ...]) -> None:
    """Unconfirmed SKILL facts, never superseding one (spec §7.5): a name already held
    unsuperseded -- same kind, or typed with no kind -- is skipped, confirmed or not."""
    held: set[tuple[str, str]] = set()
    for payload in unsuperseded_facts(student).filter(
        category=VerifiedFact.Category.SKILL
    ).values_list("payload", flat=True):
        if isinstance(payload, dict):
            held.add((str(payload.get("kind") or ""), str(payload.get("name") or "").casefold()))
    for skill in skills:
        name = skill.name.casefold()
        if (skill.kind, name) in held or ("", name) in held:
            continue
        held.add((skill.kind, name))
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.SKILL,
            payload=fact_payload(
                SkillEntry(name=skill.name, category=_HEADINGS[skill.kind], kind=skill.kind,
                           evidence=skill.evidence),
                category=VerifiedFact.Category.SKILL,
            ),
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref=skill.source_ref,
            confirmed_by=None,
            confirmed_at=None,
            created_by=student,
        )


# --- readings ------------------------------------------------------------------------


def save_reading(
    student: Membership,
    *,
    source_kind: str,
    changed_at: datetime,
    reader_version: int,
    reading: dict[str, Any],
    skills: tuple[SkillSuggestion, ...],
    repo: str = "",
    document: DocumentVersion | None = None,
) -> None:
    """A reading and its suggestions, together or not at all (one short transaction,
    after the model call has returned). A re-read updates the one row, matched
    case-insensitively on the repo."""
    fields = {
        "repo": repo,
        "changed_at": changed_at,
        "reader_version": reader_version,
        "read_at": timezone.now(),
        "reading": reading,
    }
    with tenant_transaction(student.tenant_id):
        existing = EvidenceReading.objects.filter(
            student=student, source_kind=source_kind, repo__iexact=repo, document=document
        ).first()
        if existing is None:
            EvidenceReading.objects.create(
                student=student, source_kind=source_kind, document=document, **fields
            )
        else:
            for name, value in fields.items():
                setattr(existing, name, value)
            existing.save(update_fields=list(fields))
        _write_suggestions(student, skills)


def github_readings(student: Membership) -> dict[str, tuple[datetime, int, str]]:
    """(changed_at, reader_version, tree_etag) of every github reading, by casefolded
    repo. The etag is what refresh.py sends as If-None-Match (spec §7.1)."""
    with tenant_transaction(student.tenant_id):
        rows = EvidenceReading.objects.filter(
            student=student, source_kind=EvidenceReading.SourceKind.GITHUB
        ).values_list("repo", "changed_at", "reader_version", "reading")
        return {
            repo.casefold(): (changed, version, str(reading.get("tree_etag") or ""))
            for repo, changed, version, reading in rows
        }


def delete_github_reading(student: Membership, repo: str) -> int:
    with tenant_transaction(student.tenant_id):
        deleted, _ = EvidenceReading.objects.filter(
            student=student, source_kind=EvidenceReading.SourceKind.GITHUB, repo__iexact=repo
        ).delete()
    return deleted


def delete_github_readings_not_in(student: Membership, seen: frozenset[str]) -> int:
    """After a COMPLETE discovery only (refresh.py): readings of repos no source named.
    `seen` may be in GitHub's own spelling; both sides are casefolded."""
    seen = frozenset(name.casefold() for name in seen)
    with tenant_transaction(student.tenant_id):
        rows = EvidenceReading.objects.filter(
            student=student, source_kind=EvidenceReading.SourceKind.GITHUB
        ).values_list("id", "repo")
        gone = [row_id for row_id, repo in rows if repo.casefold() not in seen]
        deleted, _ = EvidenceReading.objects.filter(id__in=gone).delete()
    return deleted


def reports_to_read(
    student: Membership, *, reader_version: int
) -> tuple[DocumentVersion, ...]:
    """Live THESIS_OR_REPORT uploads with no reading by this reader version, oldest first."""
    with tenant_transaction(student.tenant_id):
        current = EvidenceReading.objects.filter(
            student=student,
            source_kind=EvidenceReading.SourceKind.PDF,
            reader_version=reader_version,
        ).values_list("document_id", flat=True)
        return tuple(
            DocumentVersion.objects.filter(
                student=student,
                kind="THESIS_OR_REPORT",
                state="AVAILABLE",
                retired_at__isnull=True,
            )
            .exclude(id__in=current)
            .order_by("created_at", "id")
        )


def delete_report_reading(student: Membership, document_id: UUID) -> int:
    with tenant_transaction(student.tenant_id):
        deleted, _ = EvidenceReading.objects.filter(
            student=student, document_id=document_id
        ).delete()
    return deleted


def delete_retired_report_readings(student: Membership) -> int:
    """A retired upload's reading goes. retire_replaced retires exactly the upload a new
    one `replaces`, so this is also "replaces replaces"; "Add another" retires nothing."""
    with tenant_transaction(student.tenant_id):
        deleted, _ = EvidenceReading.objects.filter(
            student=student,
            source_kind=EvidenceReading.SourceKind.PDF,
            document__retired_at__isnull=False,
        ).delete()
    return deleted


def latest_cv(student: Membership) -> DocumentVersion | None:
    with tenant_transaction(student.tenant_id):
        return (
            DocumentVersion.objects.filter(
                student=student, kind="CV", state="AVAILABLE", retired_at__isnull=True
            )
            .order_by("-created_at", "-id")
            .first()
        )


@dataclass(frozen=True)
class StoredReading:
    source_kind: str
    repo: str
    document_id: UUID | None
    changed_at: datetime
    reading: dict[str, Any]


def stored_readings(student: Membership) -> tuple[StoredReading, ...]:
    with tenant_transaction(student.tenant_id):
        rows = EvidenceReading.objects.filter(student=student).order_by(
            "source_kind", "repo", "changed_at"
        )
        return tuple(
            StoredReading(
                source_kind=row.source_kind,
                repo=row.repo,
                document_id=row.document_id,
                changed_at=row.changed_at,
                reading=row.reading if isinstance(row.reading, dict) else {},
            )
            for row in rows
        )


# --- the GitHub login ----------------------------------------------------------------


def _identity_tips(student: Membership) -> list[VerifiedFact]:
    return list(
        unsuperseded_facts(student)
        .filter(category=VerifiedFact.Category.IDENTITY)
        .order_by("-created_at", "-id")
    )


def github_login(student: Membership) -> str:
    """The newest login any IDENTITY tip carries, confirmed or not (decision 1)."""
    with tenant_transaction(student.tenant_id):
        tips = _identity_tips(student)
    for tip in tips:
        if isinstance(tip.payload, dict) and (login := login_from_identity(tip.payload)):
            return login
    return ""


def _supersede(tip: VerifiedFact, update: Mapping[str, object]) -> VerifiedFact:
    """A copy of `tip` with `update` applied. It inherits the tip's confirmation and
    never grants one: the row also carries the name a model read off the CV."""
    payload = dict(tip.payload) if isinstance(tip.payload, dict) else {}
    return VerifiedFact.objects.create(
        student=tip.student,
        category=VerifiedFact.Category.IDENTITY,
        payload={**payload, **update},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref=GITHUB_LOGIN_REF,
        confirmed_by=tip.confirmed_by,
        confirmed_at=tip.confirmed_at,
        supersedes=tip,
        created_by=tip.student,
    )


def _login_tip(tips: list[VerifiedFact]) -> VerifiedFact | None:
    """The IDENTITY row a typed login may rewrite: the student's own named statement,
    else the standalone login row. Never a row read off a document (a passport writes
    one AUTHORITATIVE_DOCUMENT row per field): superseding it would downgrade its tier
    and rewrite its source_ref."""
    statements = [
        tip for tip in tips
        if tip.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT
        and isinstance(tip.payload, dict)
    ]
    named = [tip for tip in statements if tip.payload.get("full_name")]
    standalone = [tip for tip in statements if tip.source_ref == GITHUB_LOGIN_REF]
    found = named or standalone
    return found[0] if found else None


def set_github_login(student: Membership, login: str) -> VerifiedFact:
    """The login the student typed, kept on IDENTITY (spec §5.1). The caller validated it."""
    github = {"github_url": f"https://github.com/{login}", "github_username": login}
    with tenant_transaction(student.tenant_id):
        tip = _login_tip(_identity_tips(student))
        if tip is not None:
            return _supersede(tip, github)
        return VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.IDENTITY,
            payload=github,
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref=GITHUB_LOGIN_REF,
            confirmed_by=None,
            confirmed_at=None,
            created_by=student,
        )


def clear_github_login(student: Membership) -> int:
    """No login anywhere on IDENTITY, and every github reading deleted. Skill
    suggestions already written stay, as suggestions (spec §5.1)."""
    with tenant_transaction(student.tenant_id):
        for tip in _identity_tips(student):
            payload = tip.payload if isinstance(tip.payload, dict) else {}
            if tip.source_tier != VerifiedFact.SourceTier.STUDENT_STATEMENT:
                continue
            if payload.get("github_url") or payload.get("github_username"):
                _supersede(tip, {"github_url": None, "github_username": None})
        deleted, _ = EvidenceReading.objects.filter(
            student=student, source_kind=EvidenceReading.SourceKind.GITHUB
        ).delete()
    return deleted
