"""An executed erasure leaves no CellCoverage row counting the erased student.

CellCoverage has no student relation, so the redaction walk and the Pseudonym
cascade never reach it; advance_deletion's EXECUTED path rebuilds it instead.
Stubs as in test_execute_due_erasures.py (no ambient AWS region in CI).
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.research.coverage import refresh_cell_coverage
from apps.research.models import CellCoverage
from apps.tenancy.context import tenant_scope
from tests.research.coverage_factories import make_published_student

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch):
    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_mailbox_tokens", lambda **kw: 0)
    # Stubbed for a reason found here, not for convenience: on master,
    # redact_student's UPDATE of StudentProfileVersion.snapshot is refused by
    # the accounts_profile_version_immutable trigger (accounts/0003), so ANY
    # erasure of a student holding a profile version raises IntegrityError
    # before EXECUTED. No master test erases such a student. This test needs
    # one (coverage is computed from the profile), so the walk is stubbed and
    # the rebuild -- the thing under test -- still runs after the student is
    # made inactive, exactly where it sits on the real path.
    monkeypatch.setattr("apps.audit.deletion.redact_student", lambda **kw: None)


def _due(agency, student):
    with tenant_scope(agency.id):
        RetentionPolicy.objects.get_or_create(
            tenant=agency, version=1, defaults={"effective_at": timezone.now()}
        )
        request = DeletionRequest.objects.create(tenant=agency, student=student, state="REQUESTED")
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        DeletionRequest.objects.filter(id=request.id).update(
            execute_after=timezone.now() - timedelta(days=1)
        )
        request.refresh_from_db()
        return request


def _counted(agency) -> int:
    with tenant_scope(agency.id):
        row = CellCoverage.objects.filter(
            holder="PRIVATE_FOUNDATION", host_country="ANY", home_country="GE"
        ).first()
        return row.active_students if row else 0


def test_an_executed_erasure_leaves_no_cell_counting_that_student(
    agency_a, django_user_model
):
    kept = make_published_student(agency_a, django_user_model, nationality="AZ")
    erased = make_published_student(agency_a, django_user_model, nationality="GE")
    refresh_cell_coverage(agency_a.id)
    assert _counted(agency_a) == 1  # the GE home cells count exactly the erased student

    _due(agency_a, erased)
    call_command("execute_due_erasures")

    assert _counted(agency_a) == 0
    with tenant_scope(agency_a.id):
        assert not CellCoverage.objects.filter(home_country="GE").exists()
        # The other student is still counted: a rebuild, not a wipe.
        assert CellCoverage.objects.filter(home_country="AZ", active_students=1).exists()
    assert kept.active
