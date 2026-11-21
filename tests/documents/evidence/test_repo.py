"""fetch_repo and fetch_files: two GraphQL queries and one REST tree (spec §7.1)."""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from apps.documents.evidence.github import GitHub, GitHubRateLimited
from apps.documents.evidence.repo import (
    MAX_RAW_BYTES,
    RepoNotAccessible,
    RepoUnchanged,
    fetch_files,
    fetch_repo,
)
from apps.documents.evidence.sources import RepoRef

from .fakes import (
    SYNTH,
    USER_ID,
    FakeTransport,
    files_key,
    from_rest,
    overview_key,
    overviews,
    repo_routes,
    synthetic_routes,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SYNTH_REF = RepoRef("github", "0rkhann", "synth-bench")


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _github(routes):
    transport = FakeTransport(routes)
    return GitHub("test-token", transport=transport), transport


def test_microkatc_from_its_recorded_answers():
    names = [row["name"] for row in _load("gh_microkatc_contents.json") if row["type"] == "file"]
    github, transport = _github(repo_routes(
        "0rkhann/MicroKatc",
        files=dict.fromkeys(names, "x"),
        languages=_load("gh_microkatc_languages.json"),
        commits=from_rest(_load("gh_microkatc_commits.json")),
    ))
    snapshot = fetch_repo(RepoRef("github", "0rkhann", "MicroKatc"), github=github)
    assert snapshot.is_fork is False
    assert snapshot.languages == {"Python": 60731, "Shell": 828}
    assert snapshot.first_commit.isoformat() == "2025-02-14T22:00:59+00:00"
    assert snapshot.last_commit.isoformat() == "2025-02-22T23:49:43+00:00"
    assert "README.md" in snapshot.file_names and len(snapshot.file_names) == 14
    assert snapshot.readmes == {"README.md": "x"}
    assert not hasattr(snapshot, "contributors")
    # RepoOverview, then the tree: no contributors, no root listing, no compare.
    assert [method for method, *_ in transport.calls] == ["POST", "GET"]


def test_an_owned_repo_reads_every_commit_and_a_lab_repo_only_the_student_s():
    github, transport = _github({**repo_routes("0rkhann/own"), **repo_routes("chem-lab/solver")})
    fetch_repo(RepoRef("github", "0rkhann", "own"), github=github)
    fetch_repo(RepoRef("github", "chem-lab", "solver"), github=github, author_id=USER_ID)
    asked = overviews(transport)
    assert "author" not in asked["0rkhann/own"]
    assert asked["chem-lab/solver"]["author"] == USER_ID
    queries = [call[3]["query"] for call in transport.calls if call[0] == "POST"]
    assert "author:" not in queries[0]
    assert "history(first: 100, author: {id: $author})" in queries[1]


def test_a_missing_user_id_refuses_a_lab_repo_before_any_request():
    """Without the id, history() would read the whole lab's commits."""
    github, transport = _github(repo_routes("chem-lab/solver"))
    with pytest.raises(RepoNotAccessible):
        fetch_repo(RepoRef("github", "chem-lab", "solver"), github=github, author_id="")
    assert transport.calls == []


def test_a_fork_reports_its_parent_and_asks_no_compare():
    """ahead_by is discovery's REST compare (spec §7.1); a read does not ask again."""
    routes = repo_routes("0rkhann/cdr_bench", fork=True, parent="AxelRolov/cdr_bench")
    github, transport = _github(routes)
    snapshot = fetch_repo(RepoRef("github", "0rkhann", "cdr_bench"), github=github)
    assert (snapshot.is_fork, snapshot.parent) == (True, "AxelRolov/cdr_bench")
    assert not any("/compare/" in url for url in transport.urls)


def test_commit_messages_are_whole_newest_first_without_trailers_or_merges():
    github, _ = _github(synthetic_routes())
    snapshot = fetch_repo(SYNTH_REF, github=github)
    assert snapshot.commit_messages == (
        "Fit the surrogate",
        "Thanks @0rkhann for the review of 0RKHANN/synth-bench",
    )


def test_a_capped_commit_sample_keeps_no_dates():
    rows = [{"message": f"c{i}", "authoredDate": "2025-01-01T00:00:00Z",
             "parents": {"totalCount": 1}} for i in range(100)]
    github, _ = _github(repo_routes("0rkhann/busy", commits=rows))
    snapshot = fetch_repo(RepoRef("github", "0rkhann", "busy"), github=github)
    assert snapshot.commit_sample_capped is True
    assert (snapshot.first_commit, snapshot.last_commit) == (None, None)


def test_the_tree_is_depth_sorted_before_the_2000_path_cut():
    deep = [{"path": f"a/b/c/d{i}.py", "type": "blob", "size": 1} for i in range(2_500)]
    shallow = [{"path": f"top{i}.py", "type": "blob", "size": 7} for i in range(5)]
    routes = {**repo_routes("0rkhann/big"),
              "/repos/0rkhann/big/git/trees/main": (200, {"truncated": True,
                                                          "tree": deep + shallow})}
    github, _ = _github(routes)
    snapshot = fetch_repo(RepoRef("github", "0rkhann", "big"), github=github)
    assert len(snapshot.tree_paths) == 2_000
    assert snapshot.tree_paths[:5] == tuple(f"top{i}.py" for i in range(5))
    assert snapshot.sizes["top0.py"] == 7


def test_the_tree_carries_the_stored_etag_and_a_304_means_unchanged():
    github, _ = _github(repo_routes("0rkhann/x", etag='W/"t1"'))
    assert fetch_repo(RepoRef("github", "0rkhann", "x"), github=github).tree_etag == 'W/"t1"'
    routes = {**repo_routes("0rkhann/x"), "/repos/0rkhann/x/git/trees/main": (304, {})}
    github, transport = _github(routes)
    with pytest.raises(RepoUnchanged):
        fetch_repo(RepoRef("github", "0rkhann", "x"), github=github, etag='W/"t1"')
    [tree] = [call for call in transport.calls if "/git/trees/" in call[1]]
    assert tree[1].endswith("/git/trees/main?recursive=1")
    assert tree[2]["If-None-Match"] == 'W/"t1"'


@pytest.mark.parametrize("answer", [
    (200, {"data": {"repository": None}, "errors": [{"type": "NOT_FOUND"}]}),
    (200, {"data": {"repository": {"description": "x"}}, "errors": [{"message": "timeout"}]}),
    (502, {}),
])
def test_a_failed_overview_is_not_accessible(answer):
    """GraphQL answers 200 when it failed: errors, or data.repository null, is a failed
    fetch -- refresh.py keeps the old reading (spec §6)."""
    github, _ = _github({overview_key("0rkhann/x"): answer})
    with pytest.raises(RepoNotAccessible, match="not found, or private"):
        fetch_repo(RepoRef("github", "0rkhann", "x"), github=github)


def test_a_tree_that_does_not_answer_is_not_accessible():
    routes = {**repo_routes("0rkhann/x"), "/repos/0rkhann/x/git/trees/main": (500, {})}
    github, _ = _github(routes)
    with pytest.raises(RepoNotAccessible):
        fetch_repo(RepoRef("github", "0rkhann", "x"), github=github)


def test_a_rate_limit_is_never_reported_as_not_found():
    """repo.py:131-134 used to call this 'not found, or private'."""
    github, _ = _github({overview_key("0rkhann/x"): (403, {}, {"x-ratelimit-remaining": "0"})})
    with pytest.raises(GitHubRateLimited):
        fetch_repo(RepoRef("github", "0rkhann", "x"), github=github)


def test_a_gitlab_repo_is_refused_before_any_request():
    github, transport = _github({})
    with pytest.raises(RepoNotAccessible, match="not supported"):
        fetch_repo(RepoRef("gitlab", "someone", "project"), github=github)
    gitlab = RepoRef("gitlab", "someone", "project")
    assert fetch_files(gitlab, ["README.md"], github=github, sizes={}) == {}
    assert transport.calls == []


def test_files_come_in_one_query_and_no_path_enters_its_text():
    files = {"a.py": "A", 'we"ird\\name.py': "W", "docs/my notes.md": "Notes."}
    github, transport = _github(repo_routes(SYNTH, files=files))
    assert fetch_files(SYNTH_REF, list(files), github=github, sizes={}) == files
    [call] = transport.calls
    query, variables = call[3]["query"], call[3]["variables"]
    assert query.startswith("query RepoFiles(")
    for path in files:
        assert path not in query
    assert [variables[f"p{i}"] for i in range(3)] == [f"HEAD:{path}" for path in files]
    assert re.findall(r"\b(f\d+): object", query) == ["f0", "f1", "f2"]


def test_a_cut_notebook_or_readme_is_downloaded_raw_and_anything_else_is_absent():
    files = {"nb/my run.ipynb": '{"cells": []}', "docs/README.md": "Docs readme.",
             "big.py": "x = 1", "logo.md": "binary"}
    github, transport = _github(repo_routes(
        SYNTH, files=files, truncated=("nb/my run.ipynb", "docs/README.md", "big.py"),
        binary=("logo.md",),
    ))
    found = fetch_files(SYNTH_REF, list(files), github=github, sizes={})
    assert found == {"nb/my run.ipynb": '{"cells": []}', "docs/README.md": "Docs readme."}
    raw = [call for call in transport.calls if call[0] == "BYTES"]
    assert [call[1].rsplit("/contents/", 1)[1] for call in raw] == [
        "nb/my%20run.ipynb", "docs/README.md"
    ]
    assert {(call[2]["Accept"], call[3]) for call in raw} == {
        ("application/vnd.github.raw", MAX_RAW_BYTES)
    }


def test_a_git_lfs_pointer_is_absent():
    pointer = {"results/table.md": "version https://git-lfs.github.com/spec/v1\n"}
    github, _ = _github(repo_routes(SYNTH, files=pointer))
    assert fetch_files(SYNTH_REF, list(pointer), github=github, sizes={}) == {}


def test_a_file_over_5_mb_is_never_asked_for():
    github, transport = _github(repo_routes(SYNTH, files={"huge.ipynb": "{}", "a.py": "A"}))
    found = fetch_files(SYNTH_REF, ["huge.ipynb", "a.py"], github=github,
                        sizes={"huge.ipynb": MAX_RAW_BYTES + 1, "a.py": 1})
    assert found == {"a.py": "A"}
    assert "HEAD:huge.ipynb" not in transport.calls[0][3]["variables"].values()


def test_a_failed_files_query_raises_rather_than_reading_thin():
    """Absent files would thin the evidence under the floor and delete a good reading."""
    github, _ = _github({files_key(SYNTH): (200, {"errors": [{"message": "timeout"}]})})
    with pytest.raises(RepoNotAccessible):
        fetch_files(SYNTH_REF, ["a.py"], github=github, sizes={})


def test_a_tree_path_with_a_dot_or_empty_segment_is_dropped():
    from apps.documents.evidence.repo import _blobs

    paths = ["ok/a.py", "../x.py", "a/../b.py", "a/./b.py", "a//b.py", "/abs.py", "b.py/"]
    tree = {"tree": [{"type": "blob", "path": p, "size": 1} for p in paths]}
    assert [path for path, _ in _blobs(tree)] == ["ok/a.py"]
