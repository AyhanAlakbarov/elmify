"""manage.py ingest_evidence: a DOI through --source; repositories never one at a time."""

import uuid
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.documents.evidence import facts
from apps.documents.evidence.refresh import RefreshReport
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model):
    user = django_user_model.objects.create(username=f"u{uuid.uuid4().hex[:12]}")
    with tenant_scope(agency.id):
        return Membership.objects.create(
            tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
        )


def test_the_command_refuses_a_source_it_cannot_classify(agency_a, django_user_model):
    student = _student(agency_a, django_user_model)
    with pytest.raises(CommandError, match="unusable source"):
        call_command("ingest_evidence", tenant=str(agency_a.id), student=str(student.id),
                     source="https://example.com/whatever")


def test_the_command_refuses_a_repository_source(agency_a, django_user_model):
    student = _student(agency_a, django_user_model)
    with pytest.raises(CommandError, match="--source takes a DOI"):
        call_command("ingest_evidence", tenant=str(agency_a.id), student=str(student.id),
                     source="https://github.com/torvalds/linux")


def test_without_a_source_the_command_refreshes_and_prints_the_readings(
    agency_a, django_user_model, monkeypatch
):
    student = _student(agency_a, django_user_model)
    with tenant_scope(agency_a.id):
        facts.save_reading(
            student, source_kind="github", repo="0rkhann/MicroKatc", changed_at=timezone.now(),
            reader_version=1, skills=(),
            reading={"summary": "A solver.", "kind": "project",
                     "url": "https://github.com/0rkhann/MicroKatc",
                     "bullets": [{"text": "Built a solver.", "evidence": ["solver"],
                                  "verdict": "supported"}]},
        )
    seen = []

    def _refresh(member, **kwargs):
        seen.append(kwargs)
        return RefreshReport(read=["0rkhann/MicroKatc"], model_calls=1, tokens=900,
                             message="We couldn't find GitHub user x.")

    monkeypatch.setattr(
        "apps.documents.management.commands.ingest_evidence.refresh_evidence", _refresh
    )
    out = StringIO()
    call_command("ingest_evidence", tenant=str(agency_a.id), student=str(student.id), stdout=out)
    printed = out.getvalue()
    assert seen == [{"force": True}]
    assert "read=1" in printed and "tokens=900" in printed
    assert "We couldn't find GitHub user x." in printed
    assert "[github] https://github.com/0rkhann/MicroKatc project: A solver." in printed
    assert "  - (supported) Built a solver." in printed


def _never_refresh(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("refresh_evidence must not run")

    monkeypatch.setattr(
        "apps.documents.management.commands.ingest_evidence.refresh_evidence", _boom
    )


def test_bad_student_input_is_a_command_error_and_never_refreshes(
    agency_a, agency_b, django_user_model, monkeypatch
):
    _never_refresh(monkeypatch)
    mine = _student(agency_a, django_user_model)
    inactive = _student(agency_a, django_user_model)
    with tenant_scope(agency_a.id):
        Membership.objects.filter(id=inactive.id).update(active=False)
    other = _student(agency_b, django_user_model)
    for tenant, student in (
        (str(agency_a.id), str(uuid.uuid4())),
        (str(agency_a.id), str(other.id)),
        (str(agency_a.id), str(inactive.id)),
        (str(agency_a.id), "not-a-uuid"),
        ("not-a-uuid", str(mine.id)),
    ):
        with pytest.raises(CommandError):
            call_command("ingest_evidence", tenant=tenant, student=student)


def test_final_3_a_student_being_erased_is_a_command_error_and_never_refreshes(
    agency_a, django_user_model, monkeypatch
):
    from apps.audit.models import DeletionRequest

    _never_refresh(monkeypatch)
    student = _student(agency_a, django_user_model)
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(tenant=agency_a, student=student, state="APPROVED")
    for source in ("", "10.1000/xyz123"):
        with pytest.raises(CommandError, match="being erased"):
            call_command("ingest_evidence", tenant=str(agency_a.id), student=str(student.id),
                         source=source)
