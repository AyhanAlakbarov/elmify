"""The DOI evidence source, end to end, against the live APIs.

ingest_evidence reads a DOI into a publication fact. Nothing in it had ever
been run against a real artefact -- its tests all use recorded transports --
so this is the counterpart to test_live_tailoring.py for the other half of the
pipeline. The repository and document legs return through refresh_evidence.

Marked `live` (excluded by pyproject.toml's addopts). The leg skips unless its
input is named:

    POSTGRES_DB=elmify_ei uv run pytest tests/documents/test_live_evidence.py \
      -m live -s

    LIVE_DOI=10.1021/acscatal.5c00348        # publication leg, no model call
    LIVE_GITHUB_LOGIN=0rkhann                # refresh leg: GITHUB_TOKEN required,
                                             # OPENAI_API_KEY, OPENROUTER_API_KEY for Jev
    LIVE_EVIDENCE_PDF=/path/to/thesis.pdf    # thesis leg, 1 model call
"""

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from apps.concierge.documents import register
from apps.documents.evidence import facts
from apps.documents.evidence.intake import Outcome, ingest_evidence
from apps.documents.evidence.readings import usable_readings
from apps.documents.evidence.refresh import refresh_evidence
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


def test_a_real_doi(agency_a, django_user_model, capsys):
    """Crossref then OpenAlex. No model call: a publication fact is mechanical,
    which is why it is the only one written auto-confirmed."""
    doi = os.getenv("LIVE_DOI")
    if not doi:
        pytest.skip("set LIVE_DOI")
    with tenant_scope(agency_a.id):
        result = ingest_evidence(
            student=_student(agency_a, django_user_model), raw_source=doi
        )
    _report(f"DOI {doi}", result, capsys)
    assert result.outcome is not Outcome.FAILED, result.reason
    # The byline question is the point of the SUCCESS path: which author is he
    # is not decidable from a name, so it is always asked.
    if result.outcome is Outcome.SUCCESS:
        assert result.question, "a publication must ask which author the student is"


RUNS = Path.home() / "agent-workspace" / "elmify-runs" / "cv-evidence"


def _save_run(name, report, readings):
    run = RUNS / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{name}"
    run.mkdir(parents=True, exist_ok=True)
    (run / "report.json").write_text(json.dumps(asdict(report), indent=2))
    (run / "readings.json").write_text(
        json.dumps([asdict(r) for r in readings], indent=2, default=str)
    )
    return run


def test_a_real_refresh_of_a_github_account(agency_a, django_user_model, settings, capsys):
    """Spec §14: one refresh of the owner's account with the real model and real Jev."""
    login, token = os.getenv("LIVE_GITHUB_LOGIN"), os.getenv("GITHUB_TOKEN")
    if not login or not token:
        pytest.skip("set LIVE_GITHUB_LOGIN and GITHUB_TOKEN")
    settings.GITHUB_TOKEN = token
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model)
        facts.set_github_login(student, login)
        report = refresh_evidence(student, force=True)
        readings = usable_readings(student)
    run = _save_run("github", report, readings)
    with capsys.disabled():
        print(f"\n=== refresh of {login}: {asdict(report)}\n    run files: {run}")
    assert report.stopped in ("", "read_limit"), report.stopped
    assert readings, "an account with public repos yields at least one reading"
    for reading in readings:
        for bullet in reading.bullets:
            assert bullet.evidence, bullet.text
            assert bullet.verdict in {"supported", "rejected", "unchecked"}


def test_a_real_thesis(agency_a, django_user_model, fake_store, capsys):
    pdf_path = os.getenv("LIVE_EVIDENCE_PDF")
    if not pdf_path:
        pytest.skip("set LIVE_EVIDENCE_PDF")
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model)
        document = promoted_upload(
            register(agency_a.id, student.id, kind="THESIS_OR_REPORT"), fake_store,
            Path(pdf_path).read_bytes(),
        )
        report = refresh_evidence(student, store=fake_store)
        readings = usable_readings(student)
    run = _save_run("thesis", report, readings)
    with capsys.disabled():
        print(f"\n=== thesis {Path(pdf_path).name}: {asdict(report)}\n    run files: {run}")
    assert report.read == [f"upload:{document.id}"], report
