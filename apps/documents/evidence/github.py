"""Find a student's repositories on GitHub, with the platform's one key (CV evidence spec §5).

Four sources: the student's own repos, lab and organisation repos they
committed to (one GraphQL request carrying ten years), their changed forks,
and the repos their CV links. Trust the student (owner, 2026-10-14): nothing
here checks who wrote what.

THE HOST IS A CONSTANT. Every request goes through GitHub, which joins a path
this package built onto API. A segment that came out of GitHub's own answers
passes sources._is_safe_segment first, the login passes LOGIN, and a branch is
quote()d. This is not egress.fetch_json_api because that returns no headers
(the limits and etags below need them) and no raw bytes (repo.py downloads a
notebook or README that GraphQL cut); .claude/rules/web-fetching.md records the
exception.

GITHUB_TOKEN is the only credential, sent only to API and never logged. No
token, no request: the unauthenticated path through the shared NAT address is
gone.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote, urlsplit

from django.core.cache import cache

from .sources import RepoRef, _is_safe_segment
from .transport import Headers, Transport, Urllib3Transport

API = "https://api.github.com"
#: A GitHub login (spec §5.1). Always used with fullmatch: `$` alone admits a trailing newline.
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
UNKNOWN_USER_MESSAGE = "We couldn't find GitHub user {login}."
#: Below this many requests left, a refresh does not start (spec §5.4).
LOW_REMAINING = 200
REMAINING_KEY = "evidence:github-remaining"
_PAGE = 100
#: A ceiling on the listing loop, not an expected size: 5,000 repositories.
_MAX_PAGES = 50
_YEARS = 10
_REPOS_PER_YEAR = 25
_MAX_FORK_CHECKS = 10
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_REPO_FIELDS = (
    f"commitContributionsByRepository(maxRepositories: {_REPOS_PER_YEAR}) {{ "
    "contributions { totalCount } "
    "repository { name pushedAt owner { login __typename ... on Organization { name } } } }"
)

Group = Literal["cv", "lab", "own", "fork"]


class GitHubUnavailable(RuntimeError):
    """GitHub cannot be asked right now. A refresh that meets this deletes nothing."""


class NoGitHubToken(GitHubUnavailable):
    pass


class GitHubTokenRejected(GitHubUnavailable):
    pass


class GitHubRateLimited(GitHubUnavailable):
    """Primary (remaining 0) or secondary (retry-after) limit. Never "not found"."""


class UnknownGitHubUser(LookupError):
    """GraphQL answered data.user: null -- the login names nobody."""


class GitHub:
    """The one client: fixed host, the platform token, every response's limits read."""

    def __init__(self, token: str, *, transport: Transport | None = None) -> None:
        if not token:
            raise NoGitHubToken("GITHUB_TOKEN is not set; no request is made without it")
        self._token = token
        self._transport = transport if transport is not None else Urllib3Transport()
        #: Counted for the refresh log (spec §12.1).
        self.requests = 0

    @staticmethod
    def _url(path: str) -> str:
        # "@evil.example/x" appended to API would make api.github.com the userinfo.
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("a GitHub path starts with a single /")
        return API + path

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": accept}

    def get_json(self, path: str) -> tuple[int, Any]:
        status, body, _ = self.get_with_etag(path)
        return status, body

    def get_with_etag(self, path: str, etag: str = "") -> tuple[int, Any, str]:
        """A GET sending a stored etag as If-None-Match. A 304 answers {} and costs
        nothing against the limit (spec §7.1). Returns the response's own etag too."""
        headers = self._headers()
        if etag:
            headers["If-None-Match"] = etag
        status, body, found = self._transport.get_json(self._url(path), headers=headers)
        self._read_limits(status, found)
        return status, body, found.get("etag", "")

    def post_json(self, path: str, body: object) -> tuple[int, Any]:
        status, answer, headers = self._transport.post_json(
            self._url(path), body, headers=self._headers()
        )
        self._read_limits(status, headers)
        # GraphQL's own limit answers 200 with an error of type RATE_LIMITED.
        errors = answer.get("errors") if isinstance(answer, dict) else None
        if isinstance(errors, list) and any(
            isinstance(error, dict) and error.get("type") == "RATE_LIMITED" for error in errors
        ):
            raise GitHubRateLimited("GitHub GraphQL rate limit")
        return status, answer

    def get_bytes(self, path: str, *, max_bytes: int, accept: str) -> tuple[int, bytes]:
        status, data, headers = self._transport.get_bytes(
            self._url(path), headers=self._headers(accept), max_bytes=max_bytes
        )
        self._read_limits(status, headers)
        return status, data

    def _read_limits(self, status: int, headers: Headers) -> None:
        self.requests += 1
        remaining = headers.get("x-ratelimit-remaining", "")
        reset = headers.get("x-ratelimit-reset", "")
        if remaining.isdigit():
            ttl = int(reset) - int(time.time()) if reset.isdigit() else 3600
            cache.set(REMAINING_KEY, int(remaining), timeout=max(ttl, 1))
        if status == 401:
            raise GitHubTokenRejected("GitHub rejected GITHUB_TOKEN")
        if (status in (403, 429) and remaining == "0") or "retry-after" in headers:
            raise GitHubRateLimited(f"GitHub rate limit (status {status})")


def budget_low() -> bool:
    """True when the last response GitHub sent showed fewer than LOW_REMAINING left."""
    remaining = cache.get(REMAINING_KEY)
    return isinstance(remaining, int) and remaining < LOW_REMAINING


def profile_login(url: str) -> str:
    """The login a github.com profile address names, or "".

    Parsed, never searched: https://evil.example/?r=github.com/x is not GitHub,
    and a repository address (two segments) is a project the CV used, not the
    applicant (moved from manage.py ingest_evidence's confirmed_github_login).
    """
    parts = urlsplit(url)
    if (parts.hostname or "").lower() not in {"github.com", "www.github.com"}:
        return ""
    segments = [segment for segment in parts.path.split("/") if segment]
    login = segments[0] if len(segments) == 1 else ""
    return login if LOGIN.fullmatch(login) else ""


def login_from_identity(payload: Mapping[str, object]) -> str:
    """The login one IDENTITY payload carries: the handle, else the profile address."""
    handle = str(payload.get("github_username") or "").strip()
    if LOGIN.fullmatch(handle):
        return handle
    return profile_login(str(payload.get("github_url") or ""))


@dataclass(frozen=True)
class Candidate:
    ref: RepoRef
    group: Group
    pushed_at: datetime | None
    size: int | None = None
    #: The student's commits (lab group, from GraphQL); 0 elsewhere.
    commits: int = 0
    #: "User" or "Organization", and an organisation's display name -- Part B matches on them.
    owner_type: str = ""
    owner_name: str = ""
    untouched_fork: bool = False

    @property
    def full_name(self) -> str:
        return f"{self.ref.owner}/{self.ref.name}"

    @property
    def key(self) -> str:
        return self.full_name.casefold()


@dataclass(frozen=True)
class Discovery:
    candidates: tuple[Candidate, ...]
    #: Every repo some source named (casefolded owner/name): readings outside it may go.
    seen: frozenset[str]
    #: Every listing page answered 200 and GraphQL carried no errors (spec §6).
    complete: bool
    #: The student's GitHub node id: repo.fetch_repo reads a repository they do not own
    #: through history(author: {id}), so its commits are their own (spec §7.1).
    user_id: str = ""


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _changed(row: Mapping[str, Any]) -> bool:
    pushed, created = _when(row.get("pushed_at")), _when(row.get("created_at"))
    return pushed is not None and created is not None and pushed > created


def _from_row(row: Mapping[str, Any], group: Group) -> Candidate | None:
    owner, _, name = str(row.get("full_name") or "").partition("/")
    if not (_is_safe_segment(owner) and _is_safe_segment(name)):
        return None
    owner_info = row.get("owner")
    size = row.get("size")
    return Candidate(
        ref=RepoRef("github", owner, name),
        group=group,
        pushed_at=_when(row.get("pushed_at")),
        size=size if isinstance(size, int) else None,
        owner_type=str(owner_info.get("type") or "") if isinstance(owner_info, dict) else "",
        untouched_fork=bool(row.get("fork")) and not _changed(row),
    )


def _listing(github: GitHub, login: str) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    for page in range(1, _MAX_PAGES + 1):
        status, body = github.get_json(
            f"/users/{login}/repos?type=owner&per_page={_PAGE}&page={page}"
        )
        if status != 200 or not isinstance(body, list):
            return rows, False
        rows.extend(item for item in body if isinstance(item, dict))
        if len(body) < _PAGE:
            return rows, True
    return rows, False


def _contributions_query(now: datetime) -> str:
    blocks = []
    for year in range(now.year - _YEARS + 1, now.year + 1):
        end = now if year == now.year else datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC)
        blocks.append(
            f'y{year}: contributionsCollection(from: "{year}-01-01T00:00:00Z", '
            f'to: "{end:%Y-%m-%dT%H:%M:%SZ}") {{ {_REPO_FIELDS} }}'
        )
    return (
        "query Contributions($login: String!) { user(login: $login) { id "
        + " ".join(blocks)
        + " } }"
    )


def _contribution(item: object, login: str) -> tuple[Candidate | None, int]:
    if not isinstance(item, dict):
        return None, 0
    repo, contributions = item.get("repository"), item.get("contributions")
    owner = repo.get("owner") if isinstance(repo, dict) else None
    if not isinstance(repo, dict) or not isinstance(owner, dict):
        return None, 0
    handle, name = str(owner.get("login") or ""), str(repo.get("name") or "")
    if not (_is_safe_segment(handle) and _is_safe_segment(name)):
        return None, 0
    if handle.casefold() == login.casefold():
        return None, 0  # the student's own repos come from the listing
    kind = str(owner.get("__typename") or "")
    count = contributions.get("totalCount") if isinstance(contributions, dict) else None
    candidate = Candidate(
        ref=RepoRef("github", handle, name),
        group="lab",
        pushed_at=_when(repo.get("pushedAt")),
        owner_type=kind,
        owner_name=str(owner.get("name") or "") if kind == "Organization" else "",
    )
    return candidate, count if isinstance(count, int) else 0


def _contributed(
    github: GitHub, login: str, now: datetime
) -> tuple[list[Candidate], bool, str]:
    status, body = github.post_json(
        "/graphql", {"query": _contributions_query(now), "variables": {"login": login}}
    )
    data = body.get("data") if status == 200 and isinstance(body, dict) else None
    # Checked before `errors`: an unknown login carries both (measured 2026-10-15).
    if isinstance(data, dict) and "user" in data and data["user"] is None:
        raise UnknownGitHubUser(login)
    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict):
        return [], False, ""
    totals: dict[str, int] = {}
    found: dict[str, Candidate] = {}
    for block in user.values():
        items = block.get("commitContributionsByRepository") if isinstance(block, dict) else None
        for item in items if isinstance(items, list) else []:
            candidate, count = _contribution(item, login)
            if candidate is not None:
                totals[candidate.key] = totals.get(candidate.key, 0) + count
                found.setdefault(candidate.key, candidate)
    complete = not body.get("errors")
    user_id = user.get("id")
    return (
        [replace(c, commits=totals[key]) for key, c in found.items()],
        complete,
        user_id if isinstance(user_id, str) else "",
    )


def ahead_by(github: GitHub, ref: RepoRef, meta: Mapping[str, Any]) -> int | None:
    """How far a fork's default branch is ahead of its parent's, or None when unknown."""
    parent = meta.get("parent")
    full = parent.get("full_name") if isinstance(parent, dict) else None
    owner, _, name = str(full or "").partition("/")
    branch = str(meta.get("default_branch") or "")
    if not (_is_safe_segment(owner) and _is_safe_segment(name) and branch):
        return None
    head = quote(branch, safe="")
    status, comparison = github.get_json(
        f"/repos/{owner}/{name}/compare/{head}...{ref.owner}:{head}"
    )
    value = comparison.get("ahead_by") if status == 200 and isinstance(comparison, dict) else None
    return value if isinstance(value, int) else None


def _changed_forks(github: GitHub, rows: list[dict[str, Any]]) -> list[Candidate]:
    """Forks pushed after they were made, newest first, at most _MAX_FORK_CHECKS of them.

    Two requests each: the listing carries no parent, so metadata first, then compare.
    """
    changed = [item for item in rows if item.get("fork") and _changed(item)]
    changed.sort(key=lambda item: _when(item.get("pushed_at")) or _EPOCH, reverse=True)
    kept = []
    for item in changed[:_MAX_FORK_CHECKS]:
        candidate = _from_row(item, "fork")
        if candidate is None:
            continue
        status, meta = github.get_json(f"/repos/{candidate.full_name}")
        if status == 200 and isinstance(meta, dict) and (
            ahead_by(github, candidate.ref, meta) or 0
        ) > 0:
            kept.append(candidate)
    return kept


def discover(
    github: GitHub,
    login: str,
    *,
    cv_links: Iterable[RepoRef] = (),
    now: datetime | None = None,
) -> Discovery:
    """Every candidate from the four sources (spec §5.2). Raises UnknownGitHubUser and
    GitHubUnavailable; never deletes anything itself."""
    if not LOGIN.fullmatch(login):
        raise UnknownGitHubUser(login)
    lab, answered, user_id = _contributed(github, login, now or datetime.now(UTC))
    rows, listed = _listing(github, login)
    found: dict[str, Candidate] = {candidate.key: candidate for candidate in lab}
    seen = set(found)
    for item in rows:
        own = _from_row(item, "own")
        if own is None:
            continue
        seen.add(own.key)
        if not item.get("fork"):
            found.setdefault(own.key, own)
    for fork in _changed_forks(github, rows):
        found.setdefault(fork.key, fork)
    for ref in cv_links:
        key = f"{ref.owner}/{ref.name}".casefold()
        if key in found:
            found[key] = replace(found[key], group="cv")
            continue
        status, meta = github.get_json(f"/repos/{ref.owner}/{ref.name}")
        linked = _from_row(meta, "cv") if status == 200 and isinstance(meta, dict) else None
        if linked is not None:
            found[linked.key] = linked
            seen.add(linked.key)
        elif status != 404:
            seen.add(key)  # unanswered, not gone: its old reading stays
    return Discovery(
        candidates=tuple(found.values()),
        seen=frozenset(seen),
        complete=answered and listed,
        user_id=user_id,
    )
