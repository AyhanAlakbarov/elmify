"""Give the LOCAL demo student a CV's worth of details to confirm.

    DJANGO_DEBUG=true uv run python scripts/seed_demo_cv.py

A developer machine cannot run the upload path (it needs S3 and the malware
scan), so the demo student never gets details read from a CV. This writes the
details that reading would have produced -- UNconfirmed, exactly as the reader
leaves them -- so "CV & letters" can be clicked through: confirm them, write the
CV and the letters (needs OPENAI_API_KEY and scripts/local_research.py --watch),
approve and download.

Safe to run twice: it adds nothing to a student who already has details. Never
run against a real database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
os.environ.setdefault("DJANGO_DEBUG", "true")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.db import transaction  # noqa: E402

if settings.DATABASES["default"]["HOST"] not in {"127.0.0.1", "localhost"}:
    sys.exit("Refusing: seed_demo_cv only runs against a local database.")


def main() -> None:
    from apps.documents.models import VerifiedFact
    from apps.documents.schemas import EducationEntry, ExperienceEntry, LanguageEntry, SkillEntry
    from apps.documents.verification import fact_payload
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.db import set_local_tenant
    from apps.tenancy.models import Membership, TenantDomain

    domain = TenantDomain.objects.filter(host="localhost").first()
    if domain is None:
        sys.exit("No demo agency. Run scripts/seed_demo.py first.")
    with tenant_scope(domain.agency_id):
        student = Membership.objects.filter(
            user__username="aysel", role=Membership.Role.STUDENT
        ).first()
    if student is None:
        sys.exit("No demo student. Run scripts/seed_demo.py first.")

    C = VerifiedFact.Category
    entries = [
        (C.IDENTITY, {"full_name": "Aysel Mammadova"}),
        (C.EDUCATION, fact_payload(EducationEntry(
            degree_as_awarded="Bakalavr, Kimya",
            degree_english="BSc Chemistry",
            institution_original="Bakı Dövlət Universiteti",
            institution_english="Baku State University",
            city="Baku", country="AZ",
            start_date="2021-09", end_date="2025-06",
            grade_native="88", grade_scale="0-100",
        ), category=C.EDUCATION)),
        (C.EXPERIENCE, fact_payload(ExperienceEntry(
            employer="Institute of Petrochemical Processes",
            title="Research intern",
            city="Baku", country="AZ",
            start_date="2024-06", end_date="2024-09",
            bullets=(
                "Prepared and characterised polymer samples with FTIR spectroscopy.",
                "Kept the lab's sample log for a team of six researchers.",
            ),
        ), category=C.EXPERIENCE)),
        (C.LANGUAGE, fact_payload(LanguageEntry(
            language="Azerbaijani", mother_tongue=True
        ), category=C.LANGUAGE)),
        (C.LANGUAGE, fact_payload(LanguageEntry(
            language="English", cefr_level="C1", test_name="IELTS Academic", test_score="7.0"
        ), category=C.LANGUAGE)),
        (C.SKILL, fact_payload(SkillEntry(name="FTIR spectroscopy"), category=C.SKILL)),
        (C.SKILL, fact_payload(SkillEntry(name="Python"), category=C.SKILL)),
    ]

    with tenant_scope(student.tenant_id), transaction.atomic():
        set_local_tenant(student.tenant_id)
        if VerifiedFact.objects.filter(student=student).exists():
            print("The demo student already has details; nothing added.")
            return
        for category, payload in entries:
            VerifiedFact.objects.create(
                tenant_id=student.tenant_id,
                student=student,
                category=category,
                payload=payload,
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="demo:seed_demo_cv",
                created_by=student,
            )
        if not student.application_email:
            student.application_email = "aysel.demo@example.com"
            student.save(update_fields=["application_email"])
    print(f"Added {len(entries)} details for aysel. Open http://localhost:8000/student/writing/")


if __name__ == "__main__":
    main()
