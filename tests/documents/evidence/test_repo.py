import json
import pathlib

import pytest

from apps.documents.evidence.repo import (
    Authorship,
    RepoNotAccessible,
    authorship,
    fetch_file,
    fetch_repo,
)
from apps.documents.evidence.sources import RepoRef

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


class FakeTransport:
    def __init__(self, responses):
        self._responses = responses
        self.seen: list[str] = []
        self.headers_seen: list[dict] = []

    def get_json(self, url, *, headers=None):
        self.seen.append(url)
        self.headers_seen.append(headers or {})
        for fragment, response in self._responses.items():
            if fragment in url:
                return response
        return 404, {}


def _owned_transport():
    return FakeTransport(
        {
            "/repos/0rkhann/MicroKatc/languages": (200, _load("gh_microkatc_languages.json")),
            "/repos/0rkhann/MicroKatc/contributors": (200, _load("gh_microkatc_contributors.json")),
            "/repos/0rkhann/MicroKatc/commits": (200, {}),
            "/repos/0rkhann/MicroKatc/contents": (200, {}),
            "/repos/0rkhann/MicroKatc": (200, _load("gh_microkatc_repo.json")),
        }
    )


def _fork_transport():
    return FakeTransport(
        {
            "/repos/0rkhann/cdr_bench/contributors": (200, _load("gh_cdrbench_contributors.json")),
            "/repos/0rkhann/cdr_bench": (200, _load("gh_cdrbench_repo.json")),
            "/compare/": (200, {"ahead_by": 0, "behind_by": 31}),
        }
    )


def test_a_repo_the_student_wrote_is_owned():
    snapshot = fetch_repo(
        RepoRef("github", "0rkhann", "MicroKatc"),
        owner_login="0rkhann",
        transport=_owned_transport(),
    )
    assert snapshot.is_fork is False
    assert snapshot.contributors["0rkhann"] == 21
    assert authorship(snapshot, owner_login="0rkhann") is Authorship.OWNED


def test_a_fork_with_no_commits_by_the_student_is_unproven():
    """The case this gate exists for. cdr_bench reads 'Benchmarking
    Dimensionality Reduction Techniques on Chemical Datasets' -- an ideal CV
    bullet for a project he never committed to."""
    snapshot = fetch_repo(
        RepoRef("github", "0rkhann", "cdr_bench"),
        owner_login="0rkhann",
        transport=_fork_transport(),
    )
    assert snapshot.is_fork is True
    assert snapshot.parent == "AxelRolov/cdr_bench"
    assert snapshot.ahead_by == 0
    assert "0rkhann" not in snapshot.contributors
    assert authorship(snapshot, owner_login="0rkhann") is Authorship.UNPROVEN


@pytest.mark.parametrize(
    "is_fork,ahead_by,contributions,expected",
    [
        (False, None, 21, Authorship.OWNED),
        (False, None, 0, Authorship.UNPROVEN),
        (True, 0, 0, Authorship.UNPROVEN),
        (True, 0, 5, Authorship.OWNED),
        (True, 12, 0, Authorship.UNPROVEN),
        (True, 12, 3, Authorship.OWNED),
    ],
)
def test_the_authorship_gate_over_every_combination(
    is_fork, ahead_by, contributions, expected
):
    """Commits by the student are what prove authorship. A fork he added
    commits to is his work; a fork he did not touch is not, however far ahead
    it is of upstream."""
    from apps.documents.evidence.repo import RepoSnapshot

    snapshot = RepoSnapshot(
        ref=RepoRef("github", "0rkhann", "x"),
        description=None,
        is_fork=is_fork,
        parent="someone/x" if is_fork else None,
        languages={},
        contributors={"0rkhann": contributions} if contributions else {"other": 4},
        commit_count=contributions,
        first_commit=None,
        last_commit=None,
        ahead_by=ahead_by,
        file_names=(),
    )
    assert authorship(snapshot, owner_login="0rkhann") is expected


def test_a_missing_or_private_repo_raises_without_leaking_which():
    transport = FakeTransport({})
    with pytest.raises(RepoNotAccessible) as excinfo:
        fetch_repo(
            RepoRef("github", "0rkhann", "secret"),
            owner_login="0rkhann",
            transport=transport,
        )
    assert "not found, or private" in str(excinfo.value)


def test_a_token_is_sent_as_a_header_and_never_appears_in_an_error():
    transport = FakeTransport({})
    token = "github_pat_ThisMustNeverBeLogged"
    with pytest.raises(RepoNotAccessible) as excinfo:
        fetch_repo(
            RepoRef("github", "0rkhann", "secret"),
            owner_login="0rkhann",
            token=token,
            transport=transport,
        )
    assert token not in str(excinfo.value)
    assert any("Authorization" in headers for headers in transport.headers_seen)


def test_we_only_ever_build_urls_against_the_host_we_chose():
    transport = _owned_transport()
    fetch_repo(
        RepoRef("github", "0rkhann", "MicroKatc"),
        owner_login="0rkhann",
        transport=transport,
    )
    for url in transport.seen:
        assert url.startswith("https://api.github.com/")


def test_commit_dates_and_file_names_are_parsed_from_real_list_shaped_responses():
    """_owned_transport() above stubs /commits and /contents as (200, {}),
    which only ever exercises the isinstance(..., list) 'not a list' branch
    -- first_commit, last_commit and file_names never see real GitHub array
    data. This uses fixtures captured from the live API (gh api
    repos/0rkhann/MicroKatc/commits?per_page=5 and .../contents) trimmed to
    the fields the parser reads, plus three malformed commit rows appended by
    hand: one with no 'commit' key at all, one GitHub emits for a commit it
    cannot attribute ({"commit": {"author": null}}), and one with a
    non-string date -- proving _commit_date filters all three rather than
    raising TypeError, rather than merely happening to pass on well-formed
    input."""
    transport = FakeTransport(
        {
            "/repos/0rkhann/MicroKatc/languages": (200, _load("gh_microkatc_languages.json")),
            "/repos/0rkhann/MicroKatc/contributors": (200, _load("gh_microkatc_contributors.json")),
            "/repos/0rkhann/MicroKatc/commits": (200, _load("gh_microkatc_commits.json")),
            "/repos/0rkhann/MicroKatc/contents": (200, _load("gh_microkatc_contents.json")),
            "/repos/0rkhann/MicroKatc": (200, _load("gh_microkatc_repo.json")),
        }
    )
    snapshot = fetch_repo(
        RepoRef("github", "0rkhann", "MicroKatc"),
        owner_login="0rkhann",
        transport=transport,
    )
    # Real dates from the fixture, oldest and newest of the 5 well-formed
    # rows; the 6th (malformed, no "commit" key) must not blow up the sort
    # and must not appear as either boundary.
    assert snapshot.first_commit.isoformat() == "2025-02-14T22:00:59+00:00"
    assert snapshot.last_commit.isoformat() == "2025-02-22T23:49:43+00:00"
    assert "README.md" in snapshot.file_names
    assert "requirements.txt" in snapshot.file_names
    assert len(snapshot.file_names) == 16


def test_fetch_file_returns_the_decoded_text_for_a_real_file():
    body = _load("gh_microkatc_file_requirements.json")
    transport = FakeTransport({"/contents/requirements.txt": (200, body)})
    text = fetch_file(
        RepoRef("github", "0rkhann", "MicroKatc"),
        "requirements.txt",
        transport=transport,
    )
    assert text.startswith("appdirs==1.4.4\n")


def test_fetch_file_returns_empty_string_for_a_404():
    transport = FakeTransport({})
    assert (
        fetch_file(RepoRef("github", "0rkhann", "MicroKatc"), "nope.txt", transport=transport)
        == ""
    )


def test_fetch_file_returns_empty_string_for_a_directory_shaped_body():
    """The bug this task's resolution 4 exists to fix: GitHub's /contents
    endpoint returns a JSON *list*, not a dict, when the path names a
    directory rather than a file. Calling .get() on that list without a
    type check raises AttributeError, breaking the "never raises" contract
    the docstring promises."""
    transport = FakeTransport(
        {"/contents/GaussOutputFiles": (200, [{"name": "a.log", "type": "file"}])}
    )
    assert (
        fetch_file(
            RepoRef("github", "0rkhann", "MicroKatc"),
            "GaussOutputFiles",
            transport=transport,
        )
        == ""
    )


def test_fetch_file_returns_empty_string_for_malformed_base64():
    transport = FakeTransport(
        {"/contents/broken.txt": (200, {"encoding": "base64", "content": "not-valid-base64!!"})}
    )
    assert (
        fetch_file(
            RepoRef("github", "0rkhann", "MicroKatc"),
            "broken.txt",
            transport=transport,
        )
        == ""
    )


def test_fetch_file_refuses_a_non_github_host_before_any_request():
    """Resolution 3: without this guard a GitLab RepoRef reaching fetch_file
    would build a GitHub-shaped path against gitlab.com/api/v4 and send the
    Authorization header to that unintended host before falling back to "".
    The token must never leave the process for a host we did not choose to
    support, not merely never appear in an exception."""
    transport = FakeTransport({})
    text = fetch_file(
        RepoRef("gitlab", "someone", "project"),
        "README.md",
        token="should-never-be-sent",
        transport=transport,
    )
    assert text == ""
    assert transport.seen == []


def test_a_gitlab_repo_is_refused_before_any_request():
    """GitLab is parsed by sources.py but this module only implements
    GitHub's endpoint shapes. Fetching a gitlab.com URL against GitHub-shaped
    paths would 404 and be reported as 'not found, or private' -- a lie, since
    it was never attempted. Refuse up front instead, before any request."""
    transport = FakeTransport({})
    with pytest.raises(RepoNotAccessible) as excinfo:
        fetch_repo(
            RepoRef("gitlab", "someone", "project"),
            owner_login="someone",
            transport=transport,
        )
    assert "gitlab" in str(excinfo.value).lower()
    assert "not supported" in str(excinfo.value).lower()
    assert transport.seen == []
