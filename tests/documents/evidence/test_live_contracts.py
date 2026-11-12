"""Fixtures cannot catch API drift; only a real call can.

Skipped by default. Run deliberately with:
    uv run pytest tests/documents/evidence/test_live_contracts.py -m live

These assert ONLY that the fields this package depends on still exist. They do
not assert values, which change.
"""

import os

import pytest

from apps.documents.evidence.github import GitHub, ahead_by, discover
from apps.documents.evidence.publication import fetch_publication
from apps.documents.evidence.repo import fetch_files, fetch_repo
from apps.documents.evidence.sources import DoiRef, RepoRef

pytestmark = pytest.mark.live


def test_crossref_still_returns_the_fields_we_read():
    record = fetch_publication(DoiRef("10.1021/acscatal.5c00348"))
    assert record.title
    assert record.authors
    assert record.issue is not None
    assert record.work_type


def test_the_github_queries_still_return_the_fields_we_read():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        pytest.skip("set GITHUB_TOKEN: no token, no request")
    github = GitHub(token)
    fork = RepoRef("github", "0rkhann", "cdr_bench")
    snapshot = fetch_repo(fork, github=github)
    assert snapshot.is_fork is True and snapshot.parent
    assert snapshot.languages and snapshot.tree_paths and snapshot.tree_etag
    assert isinstance(
        fetch_files(fork, snapshot.tree_paths[:5], github=github, sizes=snapshot.sizes), dict
    )
    # Discovery's REST compare still answers ahead_by for a fork.
    status, meta = github.get_json(f"/repos/{fork.owner}/{fork.name}")
    assert status == 200 and ahead_by(github, fork, meta) is not None
    # The authored RepoOverview (a repo the student does not own) still parses.
    _, body = github.post_json("/graphql", {
        "query": "query($login: String!) { user(login: $login) { id } }",
        "variables": {"login": "0rkhann"},
    })
    lab = RepoRef("github", "AxelRolov", "cdr_bench")
    assert fetch_repo(lab, github=github, author_id=body["data"]["user"]["id"]).tree_paths


def test_one_graphql_request_still_carries_ten_years():
    """Spec §15: confirmed during Part A. If this fails with errors, fall back to one
    request per year in github._contributed."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        pytest.skip("set GITHUB_TOKEN: no token, no request")
    found = discover(GitHub(token), "0rkhann")
    assert found.complete, "the ten-year GraphQL query or a listing page failed"
    assert found.user_id, "the Contributions query no longer answers the user's node id"
    assert any(c.group == "lab" and c.commits >= 3 for c in found.candidates)
