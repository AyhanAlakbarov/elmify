"""Repository facts from a fixed host, without cloning.

Six REST endpoints give what a CV bullet needs. Cloning would mean connecting
to a host the student named, which is the expensive problem sources.py exists
to remove; every packer in the repomix family clones, so none of them helps
here (see docs/research/2026-08-27-evidence-intake-landscape.md).

AUTHORSHIP IS NEVER INFERRED. Of the four project repositories this was
validated against, three were forks with zero commits by the account owner --
one of them described as "Benchmarking Dimensionality Reduction Techniques on
Chemical Datasets", an ideal-looking CV bullet for work he did not do. Two
fields catch all three at no model cost. UNPROVEN does not mean he did nothing:
work can live on an unmerged branch or under another account. It means we
cannot claim it, so it goes to the student with a sharper question.

Only GitHub is fetched. sources.py parses gitlab.com URLs too, but GitLab's
v4 API uses a different path shape (/projects/{url-encoded-path}) and this
module implements none of it -- see fetch_repo's host check below.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .sources import RepoRef
from .transport import Transport, Urllib3Transport

#: The only host this module fetches. fetch_repo and fetch_file both refuse a
#: non-github ref before reading it, so there is nothing else to map.
_GITHUB_API = "https://api.github.com"
#: Enough to characterise a project; far short of a page of results.
_MAX_FILES = 200
#: The recursive tree of a large repository runs to thousands of blobs. This
#: many is plenty to pick the interesting files and name the directories.
_MAX_TREE_PATHS = 2_000
#: Rung 6 is the weakest prose rung; a handful of subjects is the signal, and
#: the rest is "fix typo".
_MAX_COMMIT_MESSAGES = 40
#: GitHub's own page-size cap for /commits. Also the signal for whether the
#: fetched list is truncated -- see RepoSnapshot.commit_sample_capped.
_COMMITS_PER_PAGE = 100


class RepoNotAccessible(LookupError):
    """The repository is absent, or private and no usable key was supplied."""


class Authorship(Enum):
    OWNED = "OWNED"
    UNPROVEN = "UNPROVEN"


@dataclass(frozen=True)
class RepoSnapshot:
    ref: RepoRef
    description: str | None
    is_fork: bool
    parent: str | None
    languages: dict[str, int]
    contributors: dict[str, int]
    commit_count: int
    first_commit: datetime | None
    last_commit: datetime | None
    ahead_by: int | None
    file_names: tuple[str, ...]
    #: Every blob path in the default branch, not just the root listing, from
    #: one recursive git-trees call. This is what makes the signal ladder
    #: reachable: a repository whose code lives under src/ or whose
    #: documentation is in notebooks is invisible to a root listing.
    tree_paths: tuple[str, ...] = ()
    #: Rung 6. Already fetched for the commit dates and previously discarded.
    commit_messages: tuple[str, ...] = ()
    #: True when /commits returned a full page (_COMMITS_PER_PAGE rows): the
    #: fetched range is truncated and first_commit is not necessarily the
    #: repository's actual first commit. Defaults False so existing literal
    #: constructions of this dataclass (e.g. in tests) do not need updating.
    commit_sample_capped: bool = False


def _headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _commit_date(row: dict[str, Any]) -> str | None:
    """The row's commit date, or None for anything that is not a plain string.

    GitHub emits `{"commit": {"author": null}}` for commits it cannot
    attribute -- real traffic, not a hypothetical -- and a naive
    row["commit"]["author"]["date"] raises TypeError on it. This must not
    raise on that, nor on a `date` that parsed as something other than a
    string.
    """
    commit = row.get("commit")
    author = commit.get("author") if isinstance(commit, dict) else None
    date = author.get("date") if isinstance(author, dict) else None
    return date if isinstance(date, str) else None


def fetch_repo(
    ref: RepoRef,
    *,
    owner_login: str,
    token: str | None = None,
    transport: Transport | None = None,
) -> RepoSnapshot:
    """Read a repository through its host's API.

    The token is used here and never returned, stored or logged. GitHub answers
    404 rather than 403 for a private repository so that existence does not
    leak, and this function preserves that: the caller is told "not found, or
    private", never which.

    Only "github" is implemented. GitLab is parsed by sources.py but this
    function refuses it up front, before any request -- GitLab's API has a
    different shape entirely, and fetching it against GitHub-shaped paths
    would 404 and be reported as "not found, or private", which would be a
    lie about a host we never actually tried.
    """
    if ref.host != "github":
        raise RepoNotAccessible(f"{ref.host} repositories are not supported yet")

    client = transport if transport is not None else Urllib3Transport()
    base = f"{_GITHUB_API}/repos/{ref.owner}/{ref.name}"
    headers = _headers(token)

    status, meta = client.get_json(base, headers=headers)
    if status != 200:
        raise RepoNotAccessible(
            f"{ref.owner}/{ref.name} not found, or private and no key was supplied"
        )
    # Both endpoints return objects on real traffic, so this is unreachable
    # today -- but it matches the isinstance guard every other .get() below
    # gets, and the transport bug this branch fixed existed precisely
    # because an unguarded body shape surprised us.
    if not isinstance(meta, dict):
        meta = {}

    _, languages = client.get_json(f"{base}/languages", headers=headers)
    _, contributor_rows = client.get_json(f"{base}/contributors", headers=headers)
    _, commit_rows = client.get_json(
        f"{base}/commits?per_page={_COMMITS_PER_PAGE}", headers=headers
    )
    _, tree_rows = client.get_json(f"{base}/contents", headers=headers)

    contributors = {
        row["login"]: row.get("contributions", 0)
        for row in (contributor_rows if isinstance(contributor_rows, list) else [])
        if row.get("login")
    }
    commit_row_list = commit_rows if isinstance(commit_rows, list) else []
    dates = sorted(
        date for row in commit_row_list if (date := _commit_date(row)) is not None
    )
    files = tuple(
        row["name"]
        for row in (tree_rows if isinstance(tree_rows, list) else [])
        if row.get("name")
    )[:_MAX_FILES]

    default = meta.get("default_branch") or "main"
    _, tree = client.get_json(
        f"{base}/git/trees/{default}?recursive=1", headers=headers
    )
    tree_rows_recursive = (tree or {}).get("tree") if isinstance(tree, dict) else None
    tree_paths = tuple(
        row["path"]
        for row in (tree_rows_recursive if isinstance(tree_rows_recursive, list) else [])
        if isinstance(row, dict) and row.get("type") == "blob" and row.get("path")
    )[:_MAX_TREE_PATHS]

    commit_messages = tuple(
        message.strip().splitlines()[0]
        for row in commit_row_list
        if isinstance(row, dict)
        and isinstance(commit := row.get("commit"), dict)
        and isinstance(message := commit.get("message"), str)
        and message.strip()
    )[:_MAX_COMMIT_MESSAGES]

    parent = (meta.get("parent") or {}).get("full_name")
    ahead_by = None
    if meta.get("fork") and parent:
        _, comparison = client.get_json(
            f"{_GITHUB_API}/repos/{parent}/compare/{default}...{ref.owner}:{default}",
            headers=headers,
        )
        ahead_by = comparison.get("ahead_by") if isinstance(comparison, dict) else None

    return RepoSnapshot(
        ref=ref,
        description=meta.get("description"),
        is_fork=bool(meta.get("fork")),
        parent=parent,
        languages=languages if isinstance(languages, dict) else {},
        contributors=contributors,
        # The student's own contribution count on this repository, not the
        # repository's total commit count -- /commits above measures
        # something different (see _commit_date and commit_sample_capped).
        commit_count=contributors.get(owner_login, 0),
        first_commit=datetime.fromisoformat(dates[0]) if dates else None,
        last_commit=datetime.fromisoformat(dates[-1]) if dates else None,
        ahead_by=ahead_by,
        file_names=files,
        tree_paths=tree_paths,
        commit_messages=commit_messages,
        commit_sample_capped=len(commit_row_list) >= _COMMITS_PER_PAGE,
    )


def fetch_file(
    ref: RepoRef,
    path: str,
    *,
    token: str | None = None,
    transport: Transport | None = None,
) -> str:
    """One file's text, or "" when it is absent or not decodable.

    Never raises: a missing README is the common case, not an error, and the
    caller falls back to whatever other signal the repository has. Refuses a
    non-GitHub host before building any request or sending the token -- the
    token is used inside the request and discarded, and must never be sent to
    a host we did not choose to support (see fetch_repo's identical guard).
    """
    if ref.host != "github":
        return ""
    client = transport if transport is not None else Urllib3Transport()
    status, body = client.get_json(
        f"{_GITHUB_API}/repos/{ref.owner}/{ref.name}/contents/{path}",
        headers=_headers(token),
    )
    if status != 200 or not isinstance(body, dict) or body.get("encoding") != "base64":
        return ""
    try:
        # base64.b64decode raises binascii.Error on malformed content, which
        # is a ValueError subclass -- already covered here, nothing to add.
        return base64.b64decode(body.get("content", "")).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return ""


def authorship(snapshot: RepoSnapshot, *, owner_login: str) -> Authorship:
    """Commits by the student are the only thing that proves authorship.

    Not the repository living under his account, and not how far a fork is
    ahead of upstream -- those commits may be someone else's.
    """
    return (
        Authorship.OWNED
        if snapshot.contributors.get(owner_login, 0) > 0
        else Authorship.UNPROVEN
    )
