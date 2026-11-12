"""Repository facts from GitHub in about two GraphQL queries and one REST request
(CV evidence spec §7.1; owner, 2026-10-15).

1. RepoOverview (GraphQL, about 1 point, measured on 0rkhann/MicroKatc):
   description, isFork and parent, languages, the 100 most recent commits on
   the default branch, and the root README-type blobs. For a repository the
   student does not own, or a fork (its parent's commits are other people's),
   history(author: {id}) gives only their own commits.
2. The tree (REST git/trees/{branch}?recursive=1): every path with its size,
   which GraphQL cannot give -- a query goes down a fixed number of levels. It
   is sent with the reading's stored etag; a 304 (free) means the default
   branch did not move, and RepoUnchanged tells refresh.py to keep the reading.
3. RepoFiles (GraphQL, about 1 point, fetch_files): the chosen files as aliased
   object(expression:) fields f0..fN. Each path travels as a variable, never in
   the query text, so a path holding a quote or a backslash cannot change it.

A blob GraphQL cut (isTruncated) or could not give as text (binary) is
downloaded raw, capped at 5 MB, only when it is a notebook or a README; any
other is absent, and so is a Git LFS pointer. A fork's ahead_by is discovery's
REST compare (github.ahead_by) and is not asked again here.

Cloning would mean connecting to a host the student named, and every packer in
the repomix family clones (evidence-engine review §7). Nothing here decides who
wrote what (owner, 2026-10-14: trust the student). Only GitHub is fetched:
sources.py parses gitlab.com too, and both functions refuse it before any
request.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import quote

from .github import GitHub
from .signals import README_FILES
from .sources import RepoRef

logger = logging.getLogger(__name__)

#: Cut AFTER the depth sort, so a deep data directory cannot crowd out the root.
_MAX_TREE_PATHS = 2_000
_MAX_COMMIT_MESSAGES = 40
#: history(first:); a full page means the sample is truncated.
_COMMITS = 100
#: The raw download's cap (spec §5.3). Above it a file is data, not prose.
MAX_RAW_BYTES = 5_000_000
_LFS_POINTER = "version https://git-lfs"
_BLOB = "... on Blob { byteSize isTruncated text }"
#: Co-authored-by:, Signed-off-by:, Reviewed-by: and the like, and Change-Id:.
#: Trailers carry other people's names and e-mail addresses.
_TRAILER = re.compile(r"^(?:[A-Za-z]+(?:-[A-Za-z]+)*-by|Change-Id)\s*:", re.IGNORECASE)


class RepoNotAccessible(LookupError):
    """Absent, private, or GitHub's answer about it was unusable. refresh.py keeps the
    old reading either way: only a complete discovery deletes one (spec §6)."""


class RepoUnchanged(Exception):
    """The tree answered 304 to the stored etag: the default branch did not move."""


@dataclass(frozen=True)
class RepoSnapshot:
    ref: RepoRef
    description: str | None
    is_fork: bool
    parent: str | None
    languages: dict[str, int]
    #: None when the sample hit _COMMITS: a capped sample's oldest is not the first.
    first_commit: datetime | None
    last_commit: datetime | None
    #: Root blob names, from the tree.
    file_names: tuple[str, ...]
    #: Blob paths, shallowest first.
    tree_paths: tuple[str, ...] = ()
    #: Blob sizes by path: what fetch_files and interesting_paths decide on.
    sizes: dict[str, int] = field(default_factory=dict)
    #: Whole messages minus trailers, newest first, merges skipped.
    commit_messages: tuple[str, ...] = ()
    commit_sample_capped: bool = False
    #: Root README-type files by name, from RepoOverview (raw download included).
    readmes: dict[str, str] = field(default_factory=dict)
    #: The tree's etag: stored with the reading and sent next time (spec §7.1).
    tree_etag: str = ""


def _overview_query(authored: bool) -> str:
    """RepoOverview. `authored` adds history(author: {id: $author})."""
    declared = ", $author: ID!" if authored else ""
    author = ", author: {id: $author}" if authored else ""
    readmes = " ".join(
        f'r{index}: object(expression: "HEAD:{name}") {{ {_BLOB} }}'
        for index, name in enumerate(README_FILES)
    )
    return (
        f"query RepoOverview($owner: String!, $name: String!{declared}) "
        "{ repository(owner: $owner, name: $name) { "
        "description isFork parent { nameWithOwner } "
        "languages(first: 50) { edges { size node { name } } } "
        "defaultBranchRef { name target { ... on Commit { "
        f"history(first: {_COMMITS}{author}) {{ nodes {{ message authoredDate "
        "parents(first: 2) { totalCount } } } } } } "
        f"{readmes} }} }}"
    )


def _files_query(count: int) -> str:
    """RepoFiles: alias f<i> reads the path in variable $p<i>."""
    declared = "".join(f", $p{index}: String!" for index in range(count))
    fields = " ".join(
        f"f{index}: object(expression: $p{index}) {{ {_BLOB} }}" for index in range(count)
    )
    return (
        f"query RepoFiles($owner: String!, $name: String!{declared}) "
        f"{{ repository(owner: $owner, name: $name) {{ {fields} }} }}"
    )


def _repository(github: GitHub, query: str, variables: dict[str, str]) -> dict[str, Any]:
    status, body = github.post_json("/graphql", {"query": query, "variables": variables})
    data = body.get("data") if status == 200 and isinstance(body, dict) else None
    repository = data.get("repository") if isinstance(data, dict) else None
    # GraphQL answers 200 when it failed: `errors`, or data.repository null (gone,
    # renamed or private), is a failed fetch, never an empty repository.
    if not isinstance(repository, dict) or body.get("errors"):
        raise RepoNotAccessible(f"{variables['owner']}/{variables['name']} not found, or private")
    return repository


def _dig(value: Any, *keys: str) -> Any:
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _raw(ref: RepoRef, path: str, github: GitHub) -> str:
    status, data = github.get_bytes(
        f"/repos/{ref.owner}/{ref.name}/contents/{quote(path)}",
        max_bytes=MAX_RAW_BYTES,
        accept="application/vnd.github.raw",
    )
    return data.decode("utf-8", "replace") if status == 200 else ""


def _blob_text(ref: RepoRef, path: str, blob: Any, github: GitHub) -> str:
    """A blob's text, or "" when it is absent, binary, cut, or a Git LFS pointer.

    Cut or binary, only a notebook or a README is worth the raw download: the
    whole notebook is the point (spec §7.2), and a README is the project's own
    account of itself.
    """
    if not isinstance(blob, dict):
        return ""
    text = blob.get("text")
    if blob.get("isTruncated") or not isinstance(text, str):
        worth_it = path.endswith(".ipynb") or path.rsplit("/", 1)[-1] in README_FILES
        text = _raw(ref, path, github) if worth_it else ""
    return "" if text.startswith(_LFS_POINTER) else text


def _message(row: dict[str, Any]) -> str:
    message = row.get("message")
    if not isinstance(message, str):
        return ""
    kept = [line for line in message.strip().splitlines() if not _TRAILER.match(line.strip())]
    return "\n".join(kept).strip()


def _blobs(tree: Any) -> list[tuple[str, int]]:
    rows = tree.get("tree") if isinstance(tree, dict) else None
    rows = rows if isinstance(rows, list) else []
    if isinstance(tree, dict) and tree.get("truncated"):
        logger.info("RepoTreeTruncated blobs=%d", len(rows))
    blobs = [
        (row["path"], row["size"] if isinstance(row.get("size"), int) else 0)
        for row in rows
        if isinstance(row, dict)
        and row.get("type") == "blob"
        and isinstance(row.get("path"), str)
        # A "", "." or ".." segment would walk the fetch URL out of the repo.
        and all(part not in ("", ".", "..") for part in row["path"].split("/"))
    ]
    blobs.sort(key=lambda blob: (blob[0].count("/"), blob[0]))
    return blobs[:_MAX_TREE_PATHS]


def fetch_repo(
    ref: RepoRef, *, github: GitHub, author_id: str | None = None, etag: str = ""
) -> RepoSnapshot:
    """Read a repository: RepoOverview, then the tree.

    `author_id` is the student's GitHub node id (github.Discovery.user_id) for a
    repository they do not own or a fork; None reads every commit. `etag` is the stored
    reading's tree etag: a 304 raises RepoUnchanged. GitHubRateLimited
    propagates -- a rate limit is never "not found".
    """
    if ref.host != "github":
        raise RepoNotAccessible(f"{ref.host} repositories are not supported yet")
    if author_id == "":
        raise RepoNotAccessible("no GitHub user id to read the student's own commits by")
    variables = {"owner": ref.owner, "name": ref.name}
    if author_id is not None:
        variables["author"] = author_id
    repository = _repository(github, _overview_query(author_id is not None), variables)

    branch = _dig(repository, "defaultBranchRef", "name")
    blobs: list[tuple[str, int]] = []
    tree_etag = ""
    if isinstance(branch, str) and branch:  # an empty repository has no branch
        status, tree, tree_etag = github.get_with_etag(
            f"/repos/{ref.owner}/{ref.name}/git/trees/{quote(branch, safe='')}?recursive=1",
            etag,
        )
        if status == 304:
            raise RepoUnchanged(f"{ref.owner}/{ref.name}")
        if status != 200:
            raise RepoNotAccessible(f"{ref.owner}/{ref.name}: the tree did not answer")
        blobs = _blobs(tree)

    nodes = _dig(repository, "defaultBranchRef", "target", "history", "nodes")
    rows = [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []
    capped = len(rows) >= _COMMITS
    dates = sorted(date for row in rows if isinstance(date := row.get("authoredDate"), str))
    messages = [
        text
        for row in rows
        if (_dig(row, "parents", "totalCount") or 0) < 2 and (text := _message(row))
    ]
    edges = _dig(repository, "languages", "edges")
    languages = {
        name: size
        for edge in (edges if isinstance(edges, list) else [])
        if isinstance(name := _dig(edge, "node", "name"), str)
        and isinstance(size := _dig(edge, "size"), int)
    }
    readmes = {
        name: text
        for index, name in enumerate(README_FILES)
        if (text := _blob_text(ref, name, repository.get(f"r{index}"), github))
    }
    parent = _dig(repository, "parent", "nameWithOwner")
    description = repository.get("description")
    return RepoSnapshot(
        ref=ref,
        description=description if isinstance(description, str) else None,
        is_fork=bool(repository.get("isFork")),
        parent=parent if isinstance(parent, str) else None,
        languages=languages,
        first_commit=datetime.fromisoformat(dates[0]) if dates and not capped else None,
        last_commit=datetime.fromisoformat(dates[-1]) if dates and not capped else None,
        file_names=tuple(path for path, _ in blobs if "/" not in path),
        tree_paths=tuple(path for path, _ in blobs),
        sizes=dict(blobs),
        commit_messages=tuple(messages[:_MAX_COMMIT_MESSAGES]),
        commit_sample_capped=capped,
        readmes=readmes,
        tree_etag=tree_etag,
    )


def fetch_files(
    ref: RepoRef, paths: Iterable[str], *, github: GitHub, sizes: Mapping[str, int]
) -> dict[str, str]:
    """The chosen files' text by path, in one RepoFiles query.

    Absent from the answer: a file over 5 MB by its tree size (never asked), a
    Git LFS pointer, and a binary or cut blob that is not a notebook or a
    README. RepoNotAccessible when the query itself failed, so a failed fetch
    keeps the old reading instead of thinning the evidence under the floor.
    """
    if ref.host != "github":
        return {}
    wanted = [path for path in dict.fromkeys(paths) if sizes.get(path, 0) <= MAX_RAW_BYTES]
    if not wanted:
        return {}
    variables = {"owner": ref.owner, "name": ref.name}
    variables.update({f"p{index}": f"HEAD:{path}" for index, path in enumerate(wanted)})
    repository = _repository(github, _files_query(len(wanted)), variables)
    found = {
        path: _blob_text(ref, path, repository.get(f"f{index}"), github)
        for index, path in enumerate(wanted)
    }
    return {path: text for path, text in found.items() if text}
