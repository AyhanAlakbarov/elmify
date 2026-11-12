"""Discovery: the four sources, GitHub's limits, and what a failure deletes (nothing)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from django.core.cache import cache

from apps.documents.evidence.github import (
    LOGIN,
    REMAINING_KEY,
    GitHub,
    GitHubRateLimited,
    GitHubTokenRejected,
    NoGitHubToken,
    UnknownGitHubUser,
    budget_low,
    discover,
    login_from_identity,
    profile_login,
)
from apps.documents.evidence.sources import RepoRef

from .fakes import LOGIN as STUDENT
from .fakes import USER_ID, FakeTransport, contribution, graphql, listing, row

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def _github(routes, **kwargs):
    transport = FakeTransport(routes, **kwargs)
    return GitHub("test-token", transport=transport), transport


def _discover(routes, cv_links=()):
    github, transport = _github(routes)
    return discover(github, STUDENT, cv_links=cv_links, now=NOW), transport


def test_no_token_means_no_request():
    transport = FakeTransport({})
    with pytest.raises(NoGitHubToken):
        GitHub("", transport=transport)
    assert transport.calls == []


def test_every_request_goes_to_api_github_com_with_the_token():
    found, transport = _discover({**graphql(), **listing(row("0rkhann/MicroKatc"))})
    assert transport.urls
    for method, url, headers, _ in transport.calls:
        assert url.startswith("https://api.github.com/")
        assert headers["Authorization"] == "Bearer test-token"
    assert found.complete


def test_every_listing_page_is_read():
    first = [row(f"0rkhann/r{i}") for i in range(100)]
    routes = {
        **graphql(),
        "repos?type=owner&per_page=100&page=1": (200, first),
        "repos?type=owner&per_page=100&page=2": (200, [row("0rkhann/last")]),
    }
    found, transport = _discover(routes)
    assert sum("/users/0rkhann/repos" in url for url in transport.urls) == 2
    assert len([c for c in found.candidates if c.group == "own"]) == 101
    assert found.complete


def test_a_failed_listing_page_makes_discovery_incomplete():
    found, _ = _discover({**graphql(), "/users/0rkhann/repos": (500, {})})
    assert found.complete is False


def test_the_contributions_query_asks_ten_years_in_one_request():
    found, transport = _discover({**graphql(), **listing()})
    posts = [call for call in transport.calls if call[0] == "POST"]
    assert len(posts) == 1
    body = posts[0][3]
    assert body["query"].startswith("query Contributions(")
    # The student's node id rides along: fetch_repo filters a lab repo's history by it.
    assert "user(login: $login) { id " in body["query"]
    assert found.user_id == USER_ID
    assert body["query"].count("contributionsCollection") == 10
    assert body["query"].count("maxRepositories: 25") == 10
    assert '"2017-01-01T00:00:00Z"' in body["query"]
    # The login travels as a variable, never interpolated into the query text.
    assert body["variables"] == {"login": STUDENT}
    assert STUDENT not in body["query"]


def test_graphql_errors_make_discovery_incomplete():
    routes = {**listing(), "/graphql": (200, {"data": {"user": {}}, "errors": [{"m": "x"}]})}
    found, _ = _discover(routes)
    assert found.complete is False


def test_review_focus_3_an_unknown_login_is_unknown_not_incomplete():
    """Measured 2026-10-15: GraphQL answers data.user null AND an errors list together."""
    routes = {
        "/graphql": (200, {"data": {"user": None},
                           "errors": [{"type": "NOT_FOUND", "path": ["user"]}]}),
        **listing(),
    }
    github, transport = _github(routes)
    with pytest.raises(UnknownGitHubUser):
        discover(github, STUDENT, now=NOW)
    # Nothing after the GraphQL answer is asked about a login that names nobody.
    assert not any("/users/" in url for url in transport.urls)


def test_lab_repos_sum_commits_across_years_and_keep_the_organisation_name():
    routes = {
        **graphql(
            contribution("chem-lab", "solver", 4, typename="Organization", org_name="Chem Lab"),
            y2024=[contribution("chem-lab", "solver", 3, typename="Organization",
                                org_name="Chem Lab")],
        ),
        **listing(),
    }
    found, _ = _discover(routes)
    [lab] = found.candidates
    assert (lab.group, lab.commits, lab.owner_type, lab.owner_name) == (
        "lab", 7, "Organization", "Chem Lab"
    )
    assert lab.pushed_at == datetime(2026, 9, 1, tzinfo=UTC)


def test_only_changed_forks_are_compared_and_kept_when_ahead():
    untouched = row("0rkhann/copy", fork=True, pushed="2025-01-01T00:00:00Z",
                    created="2025-01-01T00:00:00Z")
    ahead = row("0rkhann/ahead", fork=True, pushed="2026-05-01T00:00:00Z")
    level = row("0rkhann/level", fork=True, pushed="2026-04-01T00:00:00Z")
    routes = {
        **graphql(),
        **listing(untouched, ahead, level),
        "/repos/0rkhann/ahead": (200, {"parent": {"full_name": "up/x"}, "default_branch": "main"}),
        "/repos/0rkhann/level": (200, {"parent": {"full_name": "up/y"}, "default_branch": "main"}),
        "/repos/up/x/compare/main...0rkhann:main": (200, {"ahead_by": 2}),
        "/repos/up/y/compare/main...0rkhann:main": (200, {"ahead_by": 0}),
    }
    found, transport = _discover(routes)
    assert [c.full_name for c in found.candidates] == ["0rkhann/ahead"]
    assert found.candidates[0].group == "fork"
    assert not any("/repos/0rkhann/copy" in url for url in transport.urls)
    # The untouched fork is in a source, so an old reading of it is kept.
    assert "0rkhann/copy" in found.seen


def test_at_most_ten_forks_are_checked():
    forks = [row(f"0rkhann/f{i:02d}", fork=True, pushed=f"2026-0{1 + i % 9}-0{1 + i % 9}T00:00:00Z")
             for i in range(14)]
    found, transport = _discover({**graphql(), **listing(*forks)})
    assert sum(url.count("/repos/0rkhann/f") for url in transport.urls) == 10


def test_cv_links_join_as_group_one_and_a_dead_link_is_gone():
    routes = {
        **graphql(),
        **listing(row("0rkhann/MicroKatc")),
        "/repos/someone/linked": (200, {**row("someone/linked"), "owner": {"type": "User"}}),
        "/repos/someone/dead": (404, {}),
        "/repos/someone/flaky": (502, {}),
    }
    links = (
        RepoRef("github", "0rkhann", "MicroKatc"),
        RepoRef("github", "someone", "linked"),
        RepoRef("github", "someone", "dead"),
        RepoRef("github", "someone", "flaky"),
    )
    found, _ = _discover(routes, cv_links=links)
    groups = {c.full_name: c.group for c in found.candidates}
    assert groups == {"0rkhann/MicroKatc": "cv", "someone/linked": "cv"}
    assert "someone/dead" not in found.seen
    # Unanswered, not gone: its old reading must survive this discovery.
    assert "someone/flaky" in found.seen
    assert found.complete


def test_review_focus_1_case_never_splits_one_repo_in_two():
    routes = {
        **graphql(contribution("0RKHANN", "MicroKatc", 9)),
        # GitHub answers the listing for any spelling of the login.
        "/users/0RKHANN/repos": (200, [row("0rkhann/MicroKatc")]),
    }
    github, _ = _github(routes)
    found = discover(github, "0RKHANN", cv_links=(RepoRef("github", "0rkhann", "microkatc"),),
                     now=NOW)
    # The GraphQL row is the student's own repo (case-insensitively), so it is not "lab";
    # the CV link matches the listing row case-insensitively and keeps GitHub's spelling.
    assert [(c.full_name, c.group) for c in found.candidates] == [("0rkhann/MicroKatc", "cv")]


@pytest.mark.parametrize("full_name", ["../x/y", "a/b c", "a/..", "a/b/c"])
def test_an_unsafe_owner_or_name_from_github_is_refused(full_name):
    found, transport = _discover({**graphql(), **listing(row(full_name))})
    assert found.candidates == ()
    assert not any(".." in url or " " in url for url in transport.urls)


@pytest.mark.parametrize(
    "headers,status",
    [({"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"}, 403),
     ({"x-ratelimit-remaining": "0"}, 429),
     ({"retry-after": "60"}, 403)],
)
def test_both_limit_kinds_raise_rate_limited(headers, status):
    github, _ = _github({"/graphql": (status, {}, headers)})
    with pytest.raises(GitHubRateLimited):
        discover(github, STUDENT, now=NOW)


def test_graphql_s_own_limit_answers_200_and_still_raises_rate_limited():
    limited = {"data": None, "errors": [{"type": "RATE_LIMITED", "message": "API rate limit"}]}
    github, _ = _github({"/graphql": (200, limited)})
    with pytest.raises(GitHubRateLimited):
        discover(github, STUDENT, now=NOW)


def test_a_stored_etag_is_sent_and_the_answer_s_etag_comes_back():
    github, transport = _github({"/repos/a/b/git/trees/main": (200, {"tree": []},
                                                               {"etag": 'W/"t2"'})})
    assert github.get_with_etag("/repos/a/b/git/trees/main", 'W/"t1"') == (
        200, {"tree": []}, 'W/"t2"'
    )
    assert transport.calls[0][2]["If-None-Match"] == 'W/"t1"'
    github.get_json("/repos/a/b/git/trees/main")
    assert "If-None-Match" not in transport.calls[1][2]


def test_a_403_without_limit_headers_is_not_a_rate_limit():
    found, _ = _discover({"/graphql": (403, {}), **listing()})
    assert found.complete is False


def test_a_rejected_token_raises():
    github, _ = _github({"/graphql": (401, {})})
    with pytest.raises(GitHubTokenRejected):
        discover(github, STUDENT, now=NOW)


def test_the_last_remaining_count_is_remembered():
    cache.delete(REMAINING_KEY)
    assert budget_low() is False
    github, _ = _github({"/graphql": (200, {}, {"x-ratelimit-remaining": "150",
                                                  "x-ratelimit-reset": "9999999999"})})
    github.post_json("/graphql", {})
    assert budget_low() is True
    assert github.requests == 1


def test_the_token_never_appears_in_an_error():
    github, _ = _github({"/graphql": (401, {})})
    with pytest.raises(GitHubTokenRejected) as raised:
        github.post_json("/graphql", {})
    assert "test-token" not in str(raised.value)
    assert "test-token" not in json.dumps(list(raised.value.args))


@pytest.mark.parametrize(
    "value,ok",
    [("0rkhann", True), ("a", True), ("a" * 39, True), ("a" * 40, False), ("-abc", False),
     ("abc\n", False), ("ab/c", False), ("", False)],
)
def test_the_login_pattern(value, ok):
    assert bool(LOGIN.fullmatch(value)) is ok


@pytest.mark.parametrize(
    "url",
    ["https://evil.example/?r=github.com/torvalds", "https://github.com.evil.example/torvalds",
     "https://not-github.com/torvalds", "https://github.com/tensorflow/models"],
)
def test_a_login_is_only_taken_from_a_github_profile(url):
    assert profile_login(url) == ""


def test_a_login_comes_from_the_handle_or_the_profile_address():
    assert profile_login("https://github.com/0rkhann") == "0rkhann"
    assert login_from_identity({"github_username": " 0rkhann "}) == "0rkhann"
    assert login_from_identity({"github_url": "https://www.github.com/0rkhann/"}) == "0rkhann"
    assert login_from_identity({"github_username": "not a login", "github_url": None}) == ""


@pytest.mark.parametrize("path", ["@evil.example/x", "evil.example/x", "//evil.example/x", ""])
def test_a_path_that_could_move_the_host_is_refused_before_any_request(path):
    github, transport = _github({})
    for call in (lambda: github.get_json(path), lambda: github.post_json(path, {}),
                 lambda: github.get_bytes(path, max_bytes=1, accept="x")):
        with pytest.raises(ValueError):
            call()
    assert transport.calls == []
