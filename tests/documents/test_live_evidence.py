"""The three evidence sources, end to end, against the live APIs.

ingest_evidence is the enrichment path: a DOI, a GitHub repository or an
uploaded document goes in, and facts plus a drafted description come back for
the student to accept, edit or reject. Nothing in it had ever been run against
a real artefact -- its tests all use recorded transports -- so this is the
counterpart to test_live_tailoring.py for the other half of the pipeline.

Marked `live` (excluded by pyproject.toml's addopts). Each leg skips unless
its own input is named, so they can be run one at a time:

    POSTGRES_DB=tehsil_ei uv run pytest tests/documents/test_live_evidence.py \
      -m live -s

    LIVE_DOI=10.1021/acscatal.5c00348          # publication leg, no model call
    LIVE_GITHUB_REPO=https://github.com/you/project   # repo leg, 1 model call
    LIVE_GITHUB_LOGIN=you                      # REQUIRED with the repo, see below
    LIVE_EVIDENCE_PDF=/path/to/thesis.pdf      # document leg, 1 model call
    GITHUB_TOKEN=...                           # optional, raises the rate limit

LIVE_GITHUB_LOGIN is the authorship gate. ingest_evidence's docstring is
explicit that it must come from a verified account link and never from the
pasted URL -- passing the wrong one writes another person's languages as this
student's skills. Here it is supplied by hand, which is the whole reason this
is a manual test and not a fixture.
"""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from apps.concierge.documents import register
from apps.documents.evidence.intake import Outcome, ingest_evidence
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.uploads import promoted_upload

pytestmark = [pytest.mark.django_db, pytest.mark.live]


def _student(agency, django_user_model):
    user = django_user_model.objects.create(username=f"ev-{uuid4().hex[:8]}")
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _report(label, result, capsys):
    with capsys.disabled():
        print(f"\n=== {label}: {result.outcome.value} ===")
        if result.reason:
            print(f"  reason:   {result.reason}")
        if result.question:
            print(f"  question: {result.question}")
        for fact in result.facts:
            print(f"  fact:     [{fact.category}] {fact.payload}")
        if (proposal := result.proposal) is not None:
            print(f"  title:    {proposal.thesis_title}")
            print(f"  methods:  {proposal.methods}")
            print(f"  outcomes: {proposal.outcomes}")
            for technique in proposal.techniques:
                print(f"  technique: {technique.name}\n      <- {technique.excerpt}")


def test_a_real_doi(agency_a, django_user_model, capsys):
    """Crossref then OpenAlex. No model call: a publication fact is mechanical,
    which is why it is the only one written auto-confirmed."""
    doi = os.getenv("LIVE_DOI")
    if not doi:
        pytest.skip("set LIVE_DOI")
    with tenant_scope(agency_a.id):
        result = ingest_evidence(
            student=_student(agency_a, django_user_model), raw_source=doi, owner_login=""
        )
    _report(f"DOI {doi}", result, capsys)
    assert result.outcome is not Outcome.FAILED, result.reason
    # The byline question is the point of the SUCCESS path: which author is he
    # is not decidable from a name, so it is always asked.
    if result.outcome is Outcome.SUCCESS:
        assert result.question, "a publication must ask which author the student is"


def test_a_real_github_repository(agency_a, django_user_model, capsys):
    """Languages and libraries as skill facts, plus a drafted description."""
    repo, login = os.getenv("LIVE_GITHUB_REPO"), os.getenv("LIVE_GITHUB_LOGIN")
    if not repo or not login:
        pytest.skip("set LIVE_GITHUB_REPO and LIVE_GITHUB_LOGIN")
    with tenant_scope(agency_a.id):
        result = ingest_evidence(
            student=_student(agency_a, django_user_model),
            raw_source=repo,
            owner_login=login,
            token=os.getenv("GITHUB_TOKEN"),
        )
    _report(f"repo {repo}", result, capsys)
    assert result.outcome is not Outcome.FAILED, result.reason
    # The check worth having on a real repository: every technique the model
    # names has to quote the text that named it, or the name was recalled
    # rather than read.
    for technique in (result.proposal.techniques if result.proposal else ()):
        assert technique.excerpt.strip(), technique.name


def test_a_real_uploaded_document(agency_a, django_user_model, fake_store, capsys):
    """A thesis or project report. Always NEEDS_INPUT: nothing a model read out
    of a document becomes a fact until a human accepts it."""
    pdf_path = os.getenv("LIVE_EVIDENCE_PDF")
    if not pdf_path:
        pytest.skip("set LIVE_EVIDENCE_PDF")
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model)
        document = promoted_upload(
            register(agency_a.id, student.id), fake_store, Path(pdf_path).read_bytes()
        )
        result = ingest_evidence(
            student=student, document=document, owner_login="", store=fake_store
        )
    _report(f"document {Path(pdf_path).name}", result, capsys)
    assert result.outcome is Outcome.NEEDS_INPUT, result.reason
    assert not result.facts, "a document must write nothing until a human accepts it"
