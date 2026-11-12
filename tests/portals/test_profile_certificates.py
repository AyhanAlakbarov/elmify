import pytest
from django.utils import timezone

from apps.documents.models import VerifiedFact
from apps.portals.profile import verified_values
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _row(student, payload, ref):
    VerifiedFact.objects.create(
        student=student, category="LANGUAGE", payload=payload,
        source_tier=("AUTHORITATIVE_DOCUMENT" if ref.startswith("document:")
                     else "STUDENT_STATEMENT"),
        source_ref=ref, confirmed_by=student, confirmed_at=timezone.now(), created_by=student)


def test_the_latest_sitting_wins_and_never_mixes_with_the_cv(agency_a, membership_a):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _row(membership_a, {"language": "English", "cefr_level": "C1", "test_score": "100"},
             "upload:cv")
        _row(membership_a, {"language": "English", "test_name": "IELTS", "test_score": "7.5",
                            "test_date": "2026-03-01"}, "document:new")
        _row(membership_a, {"language": "English", "test_name": "IELTS", "test_score": "6.5",
                            "test_date": "2025-11-08"}, "document:old")
        values = verified_values(membership_a)
    assert values["language.test_score"] == "7.5"
    assert "language.cefr_level" not in values  # the CV's level never rides on a certificate
