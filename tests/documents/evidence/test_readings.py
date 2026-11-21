"""usable_readings: what the letter engine may cite (spec §11)."""

import pytest
from django.utils import timezone

from apps.concierge.models import DocumentVersion
from apps.documents.evidence import facts
from apps.documents.evidence.readings import UsableBullet, usable_readings
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def test_each_reading_comes_back_with_its_checked_bullets_and_verdicts(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="letters")
        student = Membership.objects.create(tenant=agency_a, user=user,
                                            role=Membership.Role.STUDENT, active=True)
        thesis = DocumentVersion.objects.create(tenant=agency_a, student=student,
                                                object_key="quarantine/t",
                                                kind="THESIS_OR_REPORT", state="AVAILABLE")
        bullet = {"text": "Built a solver.", "evidence": ["solver"], "verdict": "rejected"}
        facts.save_reading(
            student, source_kind="github", repo="0rkhann/MicroKatc", changed_at=timezone.now(),
            reader_version=1, skills=(),
            reading={"summary": "A solver.", "kind": "project", "bullets": [bullet],
                     "names": ["MicroKatc"], "url": "https://github.com/0rkhann/MicroKatc",
                     "first_commit": "2024-08-28", "last_commit": "2025-02-22"},
        )
        facts.save_reading(student, source_kind="pdf", document=thesis, reader_version=1,
                           changed_at=timezone.now(), skills=(),
                           reading={"summary": "A thesis.", "kind": "project", "bullets": []})
        github, pdf = sorted(usable_readings(student), key=lambda r: r.source)

    assert (github.source, github.url, github.document_id) == (
        "github", "https://github.com/0rkhann/MicroKatc", None)
    assert (github.summary, github.kind, github.names) == ("A solver.", "project", ("MicroKatc",))
    assert (github.first_commit, github.last_commit) == ("2024-08-28", "2025-02-22")
    assert github.bullets == (UsableBullet("Built a solver.", ("solver",), "rejected"),)
    assert (pdf.source, pdf.url, pdf.document_id, pdf.bullets) == ("pdf", None, thesis.id, ())
