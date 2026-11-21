"""Intake: the DOI path, the evidence text of spec §7.2, and the upload helpers."""

from __future__ import annotations

import base64
import io
import json
import pathlib
import zipfile

import pytest

from apps.concierge.documents import register
from apps.documents.evidence.github import GitHub
from apps.documents.evidence.intake import (
    INTAKE_RATE_LIMIT,
    MAX_AGENT_NOTES_CHARS,
    MAX_DOCUMENT_CHARS,
    MAX_README_CHARS,
    EvidenceRateLimited,
    Outcome,
    cv_links,
    document_text,
    ingest_evidence,
    repo_evidence,
)
from apps.documents.evidence.repo import fetch_repo
from apps.documents.evidence.sources import RepoRef
from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.uploads import promoted_upload

from .fakes import (
    SYNTH_NOTEBOOK,
    FakeTransport,
    asked,
    blob,
    files_key,
    overview,
    overview_key,
    repo_routes,
    synthetic_routes,
)

pytestmark = pytest.mark.django_db
FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


class _DoiTransport:
    def __init__(self, status=200, body=None):
        self.answer = (status, body if body is not None else _load("crossref_acscatal.json"), {})

    def get_json(self, url, *, headers=None):
        return self.answer


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def test_a_doi_succeeds_and_writes_a_confirmed_fact(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-1")
        result = ingest_evidence(
            student=student, raw_source="https://doi.org/10.1021/acscatal.5c00348",
            transport=_DoiTransport(),
        )
        assert result.outcome is Outcome.SUCCESS
        assert [fact.category for fact in result.facts] == [VerifiedFact.Category.PUBLICATION]
        assert result.question  # which author is he


def test_a_repository_is_not_ingested_one_at_a_time(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-2")
        result = ingest_evidence(
            student=student, raw_source="https://github.com/0rkhann/MicroKatc",
            transport=_DoiTransport(),
        )
        assert result.outcome is Outcome.FAILED
        assert "refresh_evidence" in (result.reason or "")


def test_an_unsupported_source_fails_without_touching_the_network(agency_a, django_user_model):
    class Exploding:
        def get_json(self, url, *, headers=None):
            raise AssertionError(f"must not fetch {url}")

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-3")
        result = ingest_evidence(student=student, raw_source="https://evil.example.test/a/b",
                                 transport=Exploding())
        assert (result.outcome, result.facts) == (Outcome.FAILED, ())


def test_intake_is_rate_limited_per_student(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-5")
        for _ in range(INTAKE_RATE_LIMIT):
            ingest_evidence(student=student, raw_source="10.1021/acscatal.5c00348",
                            transport=_DoiTransport())
        with pytest.raises(EvidenceRateLimited):
            ingest_evidence(student=student, raw_source="10.1021/acscatal.5c00348",
                            transport=_DoiTransport())


def _synthetic_evidence():
    transport = FakeTransport(synthetic_routes())
    github = GitHub("test-token", transport=transport)
    snapshot = fetch_repo(RepoRef("github", "0rkhann", "synth-bench"), github=github)
    return repo_evidence(snapshot, github=github, login="0rkhann"), transport


def test_the_evidence_follows_the_spec_order_with_the_readme_capped_after_the_code():
    evidence, _ = _synthetic_evidence()
    text = evidence.text
    order = [
        "Description: Synthetic benchmark",
        "--- latest_model.py ---",
        f"--- {SYNTH_NOTEBOOK} ---",
        "Imported libraries: numpy",
        "Directories:",
        "Commit messages, newest first:",
        "--- README.md ---",
        "--- CLAUDE.md ---",
    ]
    positions = [text.index(marker) for marker in order]
    assert positions == sorted(positions)
    readme = text.split("--- README.md ---\n", 1)[1].split("\n\n--- ", 1)[0]
    assert len(readme) <= MAX_README_CHARS
    assert "Synth bench" in readme and "shields" not in readme and "<" not in readme
    notes = text.split("--- CLAUDE.md ---\n", 1)[1]
    assert len(notes) <= MAX_AGENT_NOTES_CHARS


def test_the_selection_rules_reach_the_right_files_in_one_query():
    evidence, transport = _synthetic_evidence()
    paths = asked(transport)
    files_queries = [c for c in transport.calls if c[0] == "POST" and "RepoFiles" in c[3]["query"]]
    assert len(files_queries) == 1
    assert "Contest solver for the benchmark leaderboard." in evidence.text
    assert "docs/my notes.md" in paths and "Design notes kept at a path" in evidence.text
    assert "Notes on the acquisition function." in evidence.text
    for never in ("requirements.txt", "data/readings.txt", "tests/test_model.py",
                  "src/model_test.py", "LICENSE.md", "README.md"):
        assert never not in paths, never  # the README came with RepoOverview
    # The LFS pointer was fetched and treated as absent.
    assert "git-lfs" not in evidence.text
    # GraphQL cut a module: absent, never downloaded. It cut the notebook: downloaded raw.
    assert paths.count("generated_tables.py") == 1
    assert "too big for GraphQL" not in evidence.text
    assert paths.count(SYNTH_NOTEBOOK) == 2


def test_a_241_kb_notebook_is_read_whole_and_its_image_output_skipped():
    evidence, _ = _synthetic_evidence()
    assert "RMSE 0.42" in evidence.text
    assert "Surrogate benchmark" in evidence.text
    assert "iVBOR" not in evidence.text


def test_commit_trailers_and_merges_never_reach_the_evidence():
    evidence, _ = _synthetic_evidence()
    for gone in ("jane@example.com", "Signed-off-by", "Co-authored-by", "Merge pull request"):
        assert gone not in evidence.text
    assert "Fit the surrogate" in evidence.text


def test_review_focus_2_the_login_never_reaches_the_prompt():
    """Not only the dropped 'Repository: owner/name' line: a commit thanking @0rkhann and
    naming 0RKHANN/synth-bench carries it too."""
    evidence, _ = _synthetic_evidence()
    assert "0rkhann" not in evidence.text.casefold()
    assert "Repository:" not in evidence.text
    assert "Thanks @the author for the review of the author/synth-bench" in evidence.text


def test_a_short_login_is_left_alone():
    """A two-letter login is a common word; scrubbing it would mangle the evidence."""
    transport = FakeTransport(repo_routes("ab/tool", description="Built by ab in a lab"))
    github = GitHub("test-token", transport=transport)
    snapshot = fetch_repo(RepoRef("github", "ab", "tool"), github=github)
    assert "Built by ab in a lab" in repo_evidence(snapshot, github=github, login="ab").text


def test_the_floor_measures_what_follows_the_description():
    transport = FakeTransport(repo_routes("0rkhann/empty", description="x" * 900, files={}))
    github = GitHub("test-token", transport=transport)
    snapshot = fetch_repo(RepoRef("github", "0rkhann", "empty"), github=github)
    evidence = repo_evidence(snapshot, github=github, login="0rkhann")
    assert len(evidence.text) > 900
    assert evidence.body_chars < 500


def test_nhc_bo_benchmark_keeps_its_27k_readme_to_6000_and_skips_its_data_dumps():
    """Recorded REST answers (Step 1), served in the shapes the queries ask for."""
    name = "0rkhann/nhc-bo-benchmark"
    readme = base64.b64decode(_load("gh_nhc_readme.json")["content"]).decode()
    routes = {
        overview_key(name): overview(description=_load("gh_nhc_repo.json")["description"],
                                     languages=_load("gh_nhc_languages.json"),
                                     readmes={"README.md": blob(readme)}),
        f"/repos/{name}/git/trees/main": (200, _load("gh_nhc_tree.json")),
        files_key(name): (200, {"data": {"repository": {}}}),
    }
    transport = FakeTransport(routes)
    github = GitHub("test-token", transport=transport)
    snapshot = fetch_repo(RepoRef("github", "0rkhann", "nhc-bo-benchmark"), github=github)
    evidence = repo_evidence(snapshot, github=github, login="0rkhann")
    readme = evidence.text.split("--- README.md ---\n", 1)[1].split("\n\n--- ", 1)[0]
    assert 0 < len(readme) <= MAX_README_CHARS
    assert not any(path.endswith(("pruned_columns.txt", "requirements.txt"))
                   for path in asked(transport))
    assert len(evidence.text) <= 24_000


_DOCX_TEXT = (
    b'<?xml version="1.0"?>'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:body></w:document>"
)


def _docx(text: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", _DOCX_TEXT % text)
    return buffer.getvalue()


def test_document_text_reads_an_upload_to_the_200000_character_ceiling(
    agency_a, django_user_model, fake_store
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-doc")
        document = promoted_upload(register(agency_a.id, student.id), fake_store,
                                   _docx(b"word " * 60_000))
        text = document_text(document, store=fake_store)
    assert len(text) == MAX_DOCUMENT_CHARS


def test_cv_links_keeps_github_repositories_only(agency_a, django_user_model, fake_store):
    from weasyprint import HTML

    anchors = "".join(
        f'<a href="{href}">link</a> '
        for href in ("https://github.com/0rkhann/MicroKatc", "https://github.com/0rkhann",
                     "https://gitlab.com/a/b", "https://example.org/x")
    )
    pdf = HTML(string=f"<p>Jane Doe {anchors}</p>").write_pdf()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-links")
        document = promoted_upload(register(agency_a.id, student.id), fake_store, pdf)
        assert cv_links(document, store=fake_store) == (RepoRef("github", "0rkhann", "MicroKatc"),)
