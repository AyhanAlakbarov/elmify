"""Fixtures cannot catch API drift; only a real call can.

Skipped by default. Run deliberately with:
    uv run pytest tests/documents/evidence/test_live_contracts.py -m live

These assert ONLY that the fields this package depends on still exist. They do
not assert values, which change.
"""

import pytest

from apps.documents.evidence.publication import fetch_publication
from apps.documents.evidence.repo import fetch_repo
from apps.documents.evidence.sources import DoiRef, RepoRef

pytestmark = pytest.mark.live


def test_crossref_still_returns_the_fields_we_read():
    record = fetch_publication(DoiRef("10.1021/acscatal.5c00348"))
    assert record.title
    assert record.authors
    assert record.issue is not None
    assert record.work_type


def test_the_github_api_still_returns_fork_parent_and_contributors():
    snapshot = fetch_repo(
        RepoRef("github", "0rkhann", "cdr_bench"), owner_login="0rkhann"
    )
    # is_fork and ahead_by together are the closest observable proxy for "the
    # fork and ahead_by fields still exist": ahead_by is only computed at all
    # when the compare endpoint has both fork and parent, so this also proves
    # that endpoint still answers.
    assert snapshot.is_fork is True
    assert snapshot.ahead_by is not None
    # parent.full_name still exists -- assert presence, not who upstream is
    # today (that is this repo's current fact, not the API's contract).
    assert snapshot.parent
    # contributors[].login still exists and is still read -- assert the map
    # is populated and keyed by login strings. Whether a specific login is or
    # isn't a contributor is authorship-gate behaviour, already pinned by the
    # fixture-based table in test_repo.py; a live test can't tell "GitHub
    # changed" apart from "someone pushed a commit", so it doesn't belong here.
    assert snapshot.contributors
    assert all(isinstance(login, str) for login in snapshot.contributors)
