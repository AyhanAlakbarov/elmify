"""Find, read, check and keep a student's evidence (CV evidence spec §5-§8, §12).

refresh_evidence(student) is the document worker's `refresh_evidence` job and
`manage.py ingest_evidence --student`. Two halves:

- PDF. Every live THESIS_OR_REPORT upload without a current reading is read:
  document_text -> read_repo -> checks -> facts.save_reading. A retired upload's
  reading goes. Always runs; it costs nothing when every upload is read.
- GitHub. Skipped when a GitHub refresh finished in the last SKIP_SECONDS.
  discover -> select (code, no model) -> for each repo whose pushed_at moved or
  whose reading is by an older READER_VERSION: fetch_repo (RepoOverview + the
  tree, sent with the reading's stored etag) -> repo_evidence (RepoFiles) ->
  read_repo -> checks -> save. A tree that answers 304 means a push elsewhere:
  the reading stays and nothing is read. Readings of repos gone from a COMPLETE
  discovery are deleted; a failure deletes nothing.

No transaction spans an HTTP or model call: facts.py opens one per database
step. Limits stop quietly (spec §12.1) -- an exception the worker does not
catch is redelivered forever.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import cast
from uuid import UUID

import openai
import pydantic
from django.conf import settings
from django.core.cache import cache
from openai import OpenAI

from apps.concierge.documents import DocumentUnavailable, ReadableObjectStore
from apps.ratelimit import rate_limited
from apps.research.decisions import Client
from apps.research.extraction import ResponsesAPI
from apps.tenancy.models import Membership

from ..ingestion import UnsupportedUpload
from . import facts
from .checks import check, support
from .extraction import RepoReading, Source, read_repo
from .github import (
    _EPOCH,
    LOW_REMAINING,
    UNKNOWN_USER_MESSAGE,
    Candidate,
    GitHub,
    GitHubRateLimited,
    GitHubUnavailable,
    NoGitHubToken,
    UnknownGitHubUser,
    budget_low,
    discover,
)
from .intake import (
    INTAKE_RATE_LIMIT,
    INTAKE_RATE_WINDOW_SECONDS,
    MAX_DOCUMENT_CHARS,
    cv_links,
    document_text,
    repo_evidence,
)
from .repo import RepoNotAccessible, RepoUnchanged, fetch_repo
from .sources import RepoRef
from .transport import Transport

logger = logging.getLogger(__name__)

#: Raise whenever the prompt, the schema or the checks change: every reading by an older
#: version is read again on the next refresh (spec §6).
READER_VERSION = 1
MAX_REPOS = 10
MAX_OWN = 5
MIN_LAB_COMMITS = 3
#: Characters of evidence after the description below which a repo is not read (§7.2).
EVIDENCE_FLOOR = 500
SKIP_SECONDS = 600
_DONE_KEY = "evidence:refresh-done:{}"
_UNKNOWN_KEY = "evidence:github-unknown:{}"
_UNKNOWN_SECONDS = 7 * 24 * 3600


class _ReadLimit(Exception):
    """evidence_intake is spent: keep what exists, read no more."""


@dataclass
class RefreshReport:
    github_requests: int = 0
    model_calls: int = 0
    tokens: int = 0
    read: list[str] = field(default_factory=list)
    deleted: int = 0
    #: Bullets the quote or number check removed (checks.Checked.dropped), summed.
    dropped: int = 0
    #: Why the refresh stopped early, or "": recent, read_limit, no_token, github_budget,
    #: github_rate_limited, github_unavailable, unknown_user.
    stopped: str = ""
    #: The one student-facing message (spec §12.3), for the screen that shows it.
    message: str = ""


def reset(student_id: UUID) -> None:
    """A login was set or changed: forget the 10-minute skip and the unknown-login state."""
    cache.delete_many([_DONE_KEY.format(student_id), _UNKNOWN_KEY.format(student_id)])


def unknown_login(student_id: UUID) -> str:
    """The login the last refresh could not find, or ""."""
    value = cache.get(_UNKNOWN_KEY.format(student_id))
    return value if isinstance(value, str) else ""


def _skipped(candidate: Candidate, login: str) -> bool:
    mine = candidate.ref.owner.casefold() == login.casefold()
    name = candidate.ref.name.casefold()
    return (
        candidate.size == 0
        or candidate.untouched_fork
        or (mine and name in (login.casefold(), f"{login.casefold()}.github.io"))
    )


def select(candidates: Iterable[Candidate], login: str) -> tuple[Candidate, ...]:
    """Up to MAX_REPOS, chosen by code (spec §6): CV links; lab repos with at least
    MIN_LAB_COMMITS commits, most first; own repos and changed forks, newest first,
    in at most MAX_OWN of the slots."""
    usable = [c for c in candidates if not _skipped(c, login)]
    chosen = [c for c in usable if c.group == "cv"]
    chosen += sorted(
        (c for c in usable if c.group == "lab" and c.commits >= MIN_LAB_COMMITS),
        key=lambda c: -c.commits,
    )
    chosen = chosen[:MAX_REPOS]
    own = sorted(
        (c for c in usable if c.group in ("own", "fork")),
        key=lambda c: c.pushed_at or _EPOCH,
        reverse=True,
    )
    return tuple(chosen + own[: min(MAX_OWN, MAX_REPOS - len(chosen))])


def _parser(client: object | None) -> ResponsesAPI:
    if client is not None:
        return cast(ResponsesAPI, getattr(client, "responses", client))
    return cast(ResponsesAPI, OpenAI().responses)


def _read(
    student: Membership, report: RefreshReport, client: object | None, evidence: str,
    source: Source,
) -> RepoReading | None:
    """One model read with one retry; every call counts against evidence_intake."""
    for _attempt in range(2):
        if rate_limited(
            "evidence_intake",
            student.id,
            limit=INTAKE_RATE_LIMIT,
            window_seconds=INTAKE_RATE_WINDOW_SECONDS,
        ):
            raise _ReadLimit
        report.model_calls += 1
        try:
            reading, tokens = read_repo(
                _parser(client), student_id=str(student.id), evidence=evidence, source=source
            )
        except (openai.OpenAIError, pydantic.ValidationError) as error:
            # The SDK's parse() raises ValidationError itself on an off-schema answer;
            # uncaught, the worker would redeliver the job forever (spec §12.1).
            logger.warning("EvidenceReadFailed error=%s", type(error).__name__)
            continue
        report.tokens += tokens
        if reading is not None:
            return reading
    return None


def _day(moment: datetime | None) -> str | None:
    return moment.date().isoformat() if moment is not None else None


def _read_reports(
    student: Membership, report: RefreshReport, client: object | None,
    support_client: Client | None, store: ReadableObjectStore | None,
) -> None:
    report.deleted += facts.delete_retired_report_readings(student)
    for document in facts.reports_to_read(student, reader_version=READER_VERSION):
        try:
            text = document_text(document, store=store)
        # KeyError: the store holds no object under the promoted key (storage.get).
        except (UnsupportedUpload, DocumentUnavailable, KeyError) as error:
            logger.warning("EvidenceReportUnreadable document=%s error=%s", document.id,
                           type(error).__name__)
            continue
        if len(text.strip()) < EVIDENCE_FLOOR:
            # A scan with no text layer, or next to nothing: never sent to the model.
            report.deleted += facts.delete_report_reading(student, document.id)
            continue
        reading = _read(student, report, client, text, "document")
        if reading is None:
            continue
        checked = support(check(reading, text), student_id=student.id, client=support_client)
        report.dropped += checked.dropped
        facts.save_reading(
            student,
            source_kind="pdf",
            document=document,
            changed_at=document.created_at,
            reader_version=READER_VERSION,
            reading={**checked.to_json(), "truncated": len(text) >= MAX_DOCUMENT_CHARS},
            skills=facts.suggestions(source_ref=f"upload:{document.id}", languages={},
                                     libraries=(), techniques=checked.techniques),
        )
        report.read.append(f"upload:{document.id}")


def _read_one(
    student: Membership, login: str, candidate: Candidate, changed_at: datetime,
    github: GitHub, report: RefreshReport, client: object | None,
    support_client: Client | None, *, author_id: str | None, etag: str,
) -> None:
    try:
        snapshot = fetch_repo(candidate.ref, github=github, author_id=author_id, etag=etag)
        evidence = repo_evidence(snapshot, github=github, login=login)
    except RepoUnchanged:
        # A push to another branch: the default branch is as it was read. Nothing is
        # written, so the next refresh asks again -- one RepoOverview and a free 304.
        logger.info("EvidenceRepoUnchanged: the tree did not move; reading kept")
        return
    except RepoNotAccessible:
        logger.info("EvidenceRepoUnavailable: its old reading is kept")
        return
    if evidence.body_chars < EVIDENCE_FLOOR:
        report.deleted += facts.delete_github_reading(student, candidate.full_name)
        return
    reading = _read(student, report, client, evidence.text, "repository")
    if reading is None:
        return
    checked = support(check(reading, evidence.text), student_id=student.id, client=support_client)
    report.dropped += checked.dropped
    facts.save_reading(
        student,
        source_kind="github",
        repo=candidate.full_name,
        changed_at=changed_at,
        reader_version=READER_VERSION,
        reading={
            **checked.to_json(),
            "url": f"https://github.com/{candidate.full_name}",
            "first_commit": _day(snapshot.first_commit),
            "last_commit": _day(snapshot.last_commit),
            # Sent as If-None-Match on the next fetch (spec §7.1).
            "tree_etag": snapshot.tree_etag,
            # What Part B's entry match needs (spec §10.2).
            "origin": {
                "group": candidate.group,
                "owner_type": candidate.owner_type,
                "owner_name": candidate.owner_name,
                "commits": candidate.commits,
            },
        },
        skills=facts.suggestions(
            source_ref=f"repo:github:{candidate.full_name}",
            languages=snapshot.languages,
            libraries=evidence.libraries,
            techniques=checked.techniques,
        ),
    )
    report.read.append(candidate.full_name)


def _github(
    student: Membership, login: str, github: GitHub, report: RefreshReport,
    client: object | None, support_client: Client | None,
    store: ReadableObjectStore | None,
) -> None:
    cv = facts.latest_cv(student)
    links: tuple[RepoRef, ...] = ()
    # A CV that exists but cannot be read leaves discovery incomplete: the repos only it
    # links are unanswered, not gone, so their readings stay (spec §6).
    cv_read = True
    if cv is not None:
        try:
            links = cv_links(cv, store=store)
        except (UnsupportedUpload, DocumentUnavailable, KeyError) as error:
            logger.warning("EvidenceCvUnreadable document=%s error=%s", cv.id,
                           type(error).__name__)
            cv_read = False
    found = discover(github, login, cv_links=links)
    cache.delete_many([_UNKNOWN_KEY.format(student.id)])
    stored = facts.github_readings(student)
    for candidate in select(found.candidates, login):
        if candidate.pushed_at is None:
            continue
        known = stored.get(candidate.key)
        if known is not None and known[:2] == (candidate.pushed_at, READER_VERSION):
            continue
        # The stored etag vouches only for a reading by this reader: an older one is read
        # again whatever the tree says.
        etag = known[2] if known is not None and known[1] == READER_VERSION else ""
        # A fork the student owns still carries its parent's commits, which are other
        # people's work: it is read by the student's own commits, like a repo they do not own.
        whole = (candidate.group != "fork"
                 and candidate.ref.owner.casefold() == login.casefold())
        _read_one(student, login, candidate, candidate.pushed_at, github, report, client,
                  support_client, author_id=None if whole else found.user_id, etag=etag)
    if found.complete and cv_read:
        report.deleted += facts.delete_github_readings_not_in(student, found.seen)


def _read_github(
    student: Membership, report: RefreshReport, client: object | None,
    support_client: Client | None, transport: Transport | None,
    store: ReadableObjectStore | None, *, force: bool,
) -> None:
    login = facts.github_login(student)
    if not login:
        # No login means no github reading (spec §5.1), whatever a refresh already running
        # when it was cleared wrote after the clear. Before the 10-minute skip: that
        # refresh set it.
        report.deleted += facts.delete_github_readings_not_in(student, frozenset())
        return
    if not force and cache.get(_DONE_KEY.format(student.id)):
        report.stopped = "recent"
        return
    try:
        github = GitHub(settings.GITHUB_TOKEN, transport=transport)
    except NoGitHubToken:
        logger.error("EvidenceGitHubNoToken: GITHUB_TOKEN is not set; no discovery, "
                     "nothing deleted")
        report.stopped = "no_token"
        return
    if budget_low():
        logger.warning("EvidenceGitHubBudgetLow: fewer than %d requests left; not starting",
                       LOW_REMAINING)
        report.stopped = "github_budget"
        return
    try:
        _github(student, login, github, report, client, support_client, store)
    except UnknownGitHubUser:
        cache.set(_UNKNOWN_KEY.format(student.id), login, _UNKNOWN_SECONDS)
        report.message = UNKNOWN_USER_MESSAGE.format(login=login)
        report.stopped = "unknown_user"
    except GitHubRateLimited:
        logger.warning("EvidenceGitHubRateLimited: refresh stopped; readings kept, "
                       "nothing deleted")
        report.stopped = "github_rate_limited"
    except GitHubUnavailable as error:
        logger.error("EvidenceGitHubUnavailable error=%s", type(error).__name__)
        report.stopped = "github_unavailable"
    finally:
        report.github_requests += github.requests
        # A clear that landed mid-refresh can have a reading written after it; the login is
        # re-read here, outside any transaction, so nothing of it survives to the next refresh.
        if not facts.github_login(student):
            report.deleted += facts.delete_github_readings_not_in(student, frozenset())
    if not report.stopped:
        cache.set(_DONE_KEY.format(student.id), True, SKIP_SECONDS)


def refresh_evidence(
    student: Membership,
    *,
    force: bool = False,
    transport: Transport | None = None,
    client: object | None = None,
    support_client: Client | None = None,
    store: ReadableObjectStore | None = None,
) -> RefreshReport:
    """Bring the student's readings up to date. Call inside tenant_scope(student.tenant_id)
    and outside any transaction. Never raises for a limit, a GitHub failure or an
    unreadable upload: each is in the report and the log instead."""
    report = RefreshReport()
    try:
        _read_reports(student, report, client, support_client, store)
        _read_github(student, report, client, support_client, transport, store, force=force)
    except _ReadLimit:
        report.stopped = "read_limit"
    logger.info(
        "EvidenceRefresh student=%s github_requests=%d model_calls=%d tokens=%d read=%d "
        "deleted=%d dropped=%d stopped=%s",
        student.id, report.github_requests, report.model_calls, report.tokens,
        len(report.read), report.deleted, report.dropped, report.stopped or "-",
    )
    return report
