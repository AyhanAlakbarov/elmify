import base64
import io
import json
import pathlib
import zipfile
from unittest.mock import MagicMock

import pytest

from apps.concierge.documents import register
from apps.documents.evidence.extraction import ProposedDescription
from apps.documents.evidence.intake import (
    EvidenceRateLimited,
    Outcome,
    _repo_evidence,
    ingest_evidence,
)
from apps.documents.evidence.repo import RepoSnapshot
from apps.documents.evidence.sources import RepoRef
from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.uploads import promoted_upload

pytestmark = pytest.mark.django_db
FIXTURES = pathlib.Path(__file__).parent / "fixtures"

#: A minimal real DOCX (not a fixture -- the ingestion path sniffs bytes, not
#: an extension, so the zip has to be real). Mirrors tests/documents/test_ingestion.py.
_DOCX_WITH_TEXT = (
    b'<?xml version="1.0"?>'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p><w:r><w:t>Built a Python pipeline.</w:t></w:r></w:p></w:body></w:document>"
)
_DOCX_NO_TEXT = (
    b'<?xml version="1.0"?>'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body></w:body></w:document>"
)


def _docx(xml):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def _load(name):
    return json.loads((FIXTURES / name).read_text())


class _FakeS3Store:
    """Stands in for apps.research.storage.S3ObjectStore -- ingest_evidence
    takes no store parameter of its own, so the fake replaces the class
    open_document falls back to rather than reaching real S3."""

    def __init__(self, content):
        self._content = content

    def get(self, key):
        return self._content


def _client_returning(parsed):
    """A stub OpenAI client whose .responses.parse(...) yields ``parsed``.

    Mirrors tests/documents/test_ingestion.py's _openai_client -- the same
    shape propose_description reads (response.output_parsed).
    """
    client = MagicMock()
    response = MagicMock()
    response.output_parsed = parsed
    client.responses.parse.return_value = response
    return client


class FakeTransport:
    def __init__(self, responses):
        self._responses = responses

    def get_json(self, url, *, headers=None):
        for fragment, response in self._responses.items():
            if fragment in url:
                return response
        return 404, {}


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def test_a_doi_succeeds_and_writes_a_confirmed_fact(agency_a, django_user_model):
    transport = FakeTransport(
        {"api.crossref.org": (200, _load("crossref_acscatal.json"))}
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-1")
        result = ingest_evidence(
            student=student,
            raw_source="https://doi.org/10.1021/acscatal.5c00348",
            owner_login="0rkhann",
            transport=transport,
        )
        assert result.outcome is Outcome.SUCCESS
        assert len(result.facts) == 1
        assert result.facts[0].category == VerifiedFact.Category.PUBLICATION
        assert result.question is not None  # which author is he


def test_an_unproven_fork_needs_input_and_writes_no_project_fact(
    agency_a, django_user_model
):
    """The case that matters. cdr_bench looks like an ideal bullet and is a
    fork he never committed to."""
    transport = FakeTransport(
        {
            "/contributors": (200, _load("gh_cdrbench_contributors.json")),
            "/compare/": (200, {"ahead_by": 0}),
            "/languages": (200, {"Jupyter Notebook": 2855876}),
            "/commits": (200, []),
            "/contents": (200, []),
            "api.github.com": (200, _load("gh_cdrbench_repo.json")),
        }
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-2")
        result = ingest_evidence(
            student=student,
            raw_source="https://github.com/0rkhann/cdr_bench",
            owner_login="0rkhann",
            transport=transport,
            client=_client_returning(None),
        )
        assert result.outcome is Outcome.NEEDS_INPUT
        assert "AxelRolov/cdr_bench" in (result.question or "")
        # Unproven means we cannot claim it mechanically, never that we refuse
        # to look: no auto-confirmed fact of any category is written.
        assert not VerifiedFact.objects.filter(
            category=VerifiedFact.Category.RESEARCH
        ).exists()
        assert not VerifiedFact.objects.filter(
            category=VerifiedFact.Category.SKILL
        ).exists()


def test_an_unproven_fork_is_still_read_and_still_drafted(
    agency_a, django_user_model
):
    """The ungating. A fork with no commits from him on the default branch may
    still be work he really did -- on an unmerged branch, or under a lab's
    account. Refusing to read it produced an empty question and lost the
    material; the product decision keeps provenance, not silence. So it gets
    drafted, the draft reaches him as his claim to make, and nothing is written
    to the ledger until he accepts it."""
    proposal = ProposedDescription(
        thesis_title="Benchmarking dimensionality reduction on chemical datasets",
        methods="Compares embedding methods over molecular fingerprints.",
        outcomes=None,
    )
    transport = FakeTransport(
        {
            "/contributors": (200, _load("gh_cdrbench_contributors.json")),
            "/compare/": (200, {"ahead_by": 0}),
            "/languages": (200, {"Jupyter Notebook": 2855876}),
            "/commits": (200, []),
            "/contents": (200, []),
            "api.github.com": (200, _load("gh_cdrbench_repo.json")),
        }
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-ungated")
        result = ingest_evidence(
            student=student,
            raw_source="https://github.com/0rkhann/cdr_bench",
            owner_login="0rkhann",
            transport=transport,
            client=_client_returning(proposal),
        )
        assert result.outcome is Outcome.NEEDS_INPUT
        assert result.proposal is proposal
        assert result.facts == ()
        assert "AxelRolov/cdr_bench" in (result.question or "")
        assert "what was your role" in (result.question or "").lower()
        assert not VerifiedFact.objects.filter(student=student).exists()


def test_an_unsupported_source_fails_without_touching_the_network(
    agency_a, django_user_model
):
    class ExplodingTransport:
        def get_json(self, url, *, headers=None):
            raise AssertionError(f"must not fetch {url}")

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-3")
        result = ingest_evidence(
            student=student,
            raw_source="https://evil.example.test/a/b",
            owner_login="0rkhann",
            transport=ExplodingTransport(),
        )
        assert result.outcome is Outcome.FAILED
        assert result.facts == ()


def test_the_token_never_appears_in_the_result(agency_a, django_user_model):
    transport = FakeTransport({})
    token = "github_pat_MustNeverLeak"
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-4")
        result = ingest_evidence(
            student=student,
            raw_source="https://github.com/0rkhann/private",
            owner_login="0rkhann",
            token=token,
            transport=transport,
        )
        assert result.outcome is Outcome.FAILED
        assert token not in json.dumps(
            {"reason": result.reason, "question": result.question}
        )


def test_intake_is_rate_limited_per_student(agency_a, django_user_model):
    """CLAUDE.md requires a limiter in the same change as the path it guards."""
    from apps.documents.evidence.intake import _INTAKE_RATE_LIMIT

    transport = FakeTransport(
        {"api.crossref.org": (200, _load("crossref_acscatal.json"))}
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-5")
        for _ in range(_INTAKE_RATE_LIMIT):
            ingest_evidence(
                student=student,
                raw_source="10.1021/acscatal.5c00348",
                owner_login="0rkhann",
                transport=transport,
            )
        with pytest.raises(EvidenceRateLimited):
            ingest_evidence(
                student=student,
                raw_source="10.1021/acscatal.5c00348",
                owner_login="0rkhann",
                transport=transport,
            )


def test_a_capped_commit_sample_does_not_attribute_a_date_span_to_the_student(
    agency_a, django_user_model
):
    """/commits is the newest 100 commits of the whole repository, not the
    student's own -- write_project_fact's docstring says so, and the question
    shown to the student must not claim a date span it cannot support once
    the sample is truncated."""
    commits = [
        {"commit": {"author": {"date": f"2025-01-{(i % 28) + 1:02d}T00:00:00Z"}}}
        for i in range(100)
    ]
    transport = FakeTransport(
        {
            "/contributors": (200, _load("gh_microkatc_contributors.json")),
            "/languages": (200, _load("gh_microkatc_languages.json")),
            "/commits": (200, commits),
            "/contents": (200, []),
            "api.github.com": (200, _load("gh_microkatc_repo.json")),
        }
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-12")
        result = ingest_evidence(
            student=student,
            raw_source="https://github.com/0rkhann/MicroKatc",
            owner_login="0rkhann",
            transport=transport,
            client=_client_returning(None),
        )
        assert result.outcome is Outcome.NEEDS_INPUT
        assert "2025" not in (result.question or "")
        assert "span" not in (result.question or "")


def _microkatc_transport():
    return FakeTransport(
        {
            "/contributors": (200, _load("gh_microkatc_contributors.json")),
            "/languages": (200, _load("gh_microkatc_languages.json")),
            "/commits": (200, []),
            "/contents": (200, []),
            "api.github.com": (200, _load("gh_microkatc_repo.json")),
        }
    )


def test_a_proven_repo_reaches_needs_input_with_a_proposal_and_no_research_fact(
    agency_a, django_user_model
):
    """Authorship.OWNED: the branch that writes skill facts, calls the model,
    and assembles the confirm-my-draft question. A proposal is never a fact --
    the RESEARCH assertion is the one that protects that design property."""
    proposal = ProposedDescription(
        thesis_title="MicroKatc", methods="Simulated catalytic cycles.", outcomes=None
    )
    token = "github_pat_MustNeverLeakEither"
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-6")
        result = ingest_evidence(
            student=student,
            raw_source="https://github.com/0rkhann/MicroKatc",
            owner_login="0rkhann",
            token=token,
            transport=_microkatc_transport(),
            client=_client_returning(proposal),
        )
        assert result.outcome is Outcome.NEEDS_INPUT
        assert result.proposal == proposal
        assert "21 commits in MicroKatc" in (result.question or "")
        skill_facts = VerifiedFact.objects.filter(
            student=student, category=VerifiedFact.Category.SKILL
        )
        assert {f.payload["name"] for f in skill_facts} == {"Python", "Shell"}
        assert not VerifiedFact.objects.filter(
            category=VerifiedFact.Category.RESEARCH
        ).exists()
        leaked = json.dumps(
            {
                "reason": result.reason,
                "question": result.question,
                "proposal": result.proposal.model_dump() if result.proposal else None,
            }
        )
        assert token not in leaked


def test_a_fork_barely_touched_writes_no_skill_facts_but_still_asks(
    agency_a, django_user_model
):
    """One commit anywhere in a fork clears authorship() outright (contributors
    is truthy), but ahead_by = 0 means the student's branch adds nothing over
    upstream. A README typo fix on cdr_bench must not donate its whole
    Jupyter-Notebook-shaped skill profile -- the cdr_bench failure class one
    rung down from an unproven fork. The project question is still asked."""
    transport = FakeTransport(
        {
            "/contributors": (200, [{"login": "0rkhann", "contributions": 1}]),
            "/compare/": (200, {"ahead_by": 0}),
            "/languages": (200, {"Jupyter Notebook": 2855876}),
            "/commits": (200, []),
            "/contents": (200, []),
            "api.github.com": (200, _load("gh_cdrbench_repo.json")),
        }
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-10")
        result = ingest_evidence(
            student=student,
            raw_source="https://github.com/0rkhann/cdr_bench",
            owner_login="0rkhann",
            transport=transport,
            client=_client_returning(None),
        )
        assert result.outcome is Outcome.NEEDS_INPUT
        assert result.question is not None
        assert not VerifiedFact.objects.filter(
            student=student, category=VerifiedFact.Category.SKILL
        ).exists()


def test_a_fork_meaningfully_advanced_still_writes_skill_facts(
    agency_a, django_user_model
):
    """ahead_by > 0 means the student's branch carries commits beyond
    upstream, so the mechanical skill facts are written same as any other
    owned repository."""
    transport = FakeTransport(
        {
            "/contributors": (200, [{"login": "0rkhann", "contributions": 5}]),
            "/compare/": (200, {"ahead_by": 3}),
            "/languages": (200, {"Jupyter Notebook": 2855876}),
            "/commits": (200, []),
            "/contents": (200, []),
            "api.github.com": (200, _load("gh_cdrbench_repo.json")),
        }
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-11")
        result = ingest_evidence(
            student=student,
            raw_source="https://github.com/0rkhann/cdr_bench",
            owner_login="0rkhann",
            transport=transport,
            client=_client_returning(None),
        )
        assert result.outcome is Outcome.NEEDS_INPUT
        assert VerifiedFact.objects.filter(
            student=student, category=VerifiedFact.Category.SKILL
        ).exists()


def test_a_proven_repo_with_no_draft_falls_back_to_the_blank_box_question(
    agency_a, django_user_model
):
    """propose_description returning None (refusal, nothing to parse, or a
    schema failure) still writes the mechanical skill facts and degrades to
    asking the student directly -- the same outcome as the accepted-draft
    case, just without a proposal to show."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-7")
        result = ingest_evidence(
            student=student,
            raw_source="https://github.com/0rkhann/MicroKatc",
            owner_login="0rkhann",
            transport=_microkatc_transport(),
            client=_client_returning(None),
        )
        assert result.outcome is Outcome.NEEDS_INPUT
        assert result.proposal is None
        assert "What were you building" in (result.question or "")
        assert (
            VerifiedFact.objects.filter(
                student=student, category=VerifiedFact.Category.SKILL
            ).count()
            == 2
        )


def test_a_readable_document_reaches_needs_input_with_a_proposal(
    agency_a, django_user_model, monkeypatch
):
    proposal = ProposedDescription(thesis_title="Thesis project", methods=None, outcomes=None)
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-8")
        document = promoted_upload(register(agency_a.id, student.id), None, b"")
        content = _docx(_DOCX_WITH_TEXT)
        monkeypatch.setattr(
            "apps.concierge.documents.S3ObjectStore", lambda: _FakeS3Store(content)
        )
        result = ingest_evidence(
            student=student,
            owner_login="0rkhann",
            document=document,
            client=_client_returning(proposal),
        )
        assert result.outcome is Outcome.NEEDS_INPUT
        assert result.proposal == proposal
        assert "look right" in (result.question or "")


def test_a_document_longer_than_the_limit_says_so(agency_a, django_user_model, monkeypatch):
    """Measured on a real M2 report: it was cut at exactly 40,000 characters and
    nothing anywhere said so, so the student was asked to accept a description
    of a document the model had only partly read. The cut still happens -- some
    ceiling has to exist -- but it now arrives as a sentence the person
    accepting the description can see.
    """
    proposal = ProposedDescription(thesis_title="Thesis project", methods=None, outcomes=None)
    long_text = ("word " * 60_000).encode()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-long")
        document = promoted_upload(register(agency_a.id, student.id), None, b"")
        content = _docx(
            b'<?xml version="1.0"?>'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b"<w:body><w:p><w:r><w:t>" + long_text + b"</w:t></w:r></w:p></w:body></w:document>"
        )
        monkeypatch.setattr(
            "apps.concierge.documents.S3ObjectStore", lambda: _FakeS3Store(content)
        )
        result = ingest_evidence(
            student=student,
            owner_login="0rkhann",
            document=document,
            client=_client_returning(proposal),
        )
        assert result.outcome is Outcome.NEEDS_INPUT
        assert result.reason is not None
        assert "200,000" in result.reason


def test_a_document_within_the_limit_reports_no_truncation(
    agency_a, django_user_model, monkeypatch
):
    proposal = ProposedDescription(thesis_title="Thesis project", methods=None, outcomes=None)
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-short")
        document = promoted_upload(register(agency_a.id, student.id), None, b"")
        monkeypatch.setattr(
            "apps.concierge.documents.S3ObjectStore",
            lambda: _FakeS3Store(_docx(_DOCX_WITH_TEXT)),
        )
        result = ingest_evidence(
            student=student,
            owner_login="0rkhann",
            document=document,
            client=_client_returning(proposal),
        )
        assert result.reason is None


def test_a_document_with_no_text_layer_fails(agency_a, django_user_model, monkeypatch):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "in-9")
        document = promoted_upload(register(agency_a.id, student.id), None, b"")
        content = _docx(_DOCX_NO_TEXT)
        monkeypatch.setattr(
            "apps.concierge.documents.S3ObjectStore", lambda: _FakeS3Store(content)
        )
        result = ingest_evidence(
            student=student,
            owner_login="0rkhann",
            document=document,
            client=_client_returning(None),
        )
        assert result.outcome is Outcome.FAILED
        assert result.reason == "no text layer in the document; OCR is out of scope"
        assert result.facts == ()


def _contents(files):
    """FakeTransport responses shaped like the GitHub contents API."""
    return {
        f"/contents/{path}": (
            200,
            {"encoding": "base64", "content": base64.b64encode(body.encode()).decode()},
        )
        for path, body in files.items()
    }


def _repo_snapshot(**overrides):
    base = dict(
        ref=RepoRef("github", "0rkhann", "MicroKatc"),
        description="",
        is_fork=False,
        parent=None,
        languages={"Python": 60731},
        contributors={"0rkhann": 21},
        commit_count=21,
        first_commit=None,
        last_commit=None,
        ahead_by=None,
        file_names=("package.json",),
    )
    base.update(overrides)
    return RepoSnapshot(**base)


def test_libraries_carry_import_counts_and_include_manifest_names():
    """Counts come from parsed files; a manifest name appears even at zero.

    The count is the ranking evidence the alphabetical cut never had, and a
    declared-but-unimported name is still worth proposing -- just weaker.
    """
    snapshot = _repo_snapshot(tree_paths=("a.py", "b.py", "package.json"))
    transport = FakeTransport(
        _contents(
            {
                "a.py": "import numpy\nimport torch\n",
                "b.py": "import torch\n",
                "package.json": '{"dependencies": {"d3": "^7"}}',
            }
        )
    )

    evidence = _repo_evidence(snapshot.ref, snapshot, token=None, transport=transport)

    assert evidence.libraries == (("torch", 2), ("numpy", 1), ("d3", 0))


def test_a_repo_with_no_manifest_reports_only_what_it_imports():
    """The designed degradation: nothing is guessed for a language we cannot read."""
    snapshot = _repo_snapshot(file_names=(), tree_paths=("a.rs", "main.py"))
    transport = FakeTransport(
        _contents({"a.rs": "use serde::Serialize;\n", "main.py": "import numpy\n"})
    )

    evidence = _repo_evidence(snapshot.ref, snapshot, token=None, transport=transport)

    assert evidence.libraries == (("numpy", 1),)
