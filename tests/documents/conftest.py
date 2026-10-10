from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.concierge.models import DocumentVersion
from apps.documents import document_worker
from apps.documents.models import VerifiedFact
from apps.funding.models import Institution, Program
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _uploads_pass_the_upload_check(monkeypatch):
    """Every worker test that is not about the upload check gets a passed check and a
    recorded promotion, so none reaches S3 or the OCR child. test_upload_promotion.py
    overrides this fixture by name to test the real one."""

    def _promoted(tenant_id, document):
        key = f"tenants/{tenant_id}/students/{document.student_id}/uploads/{document.id}/stub"
        # tenant_transaction, not tenant_scope alone: behind rls_enforced_orm an UPDATE with
        # the GUC unset matches nothing and raises nothing.
        with tenant_scope(tenant_id), tenant_transaction(tenant_id):
            DocumentVersion.objects.filter(id=document.id).update(
                state="AVAILABLE", promoted_key=key, content_type="application/pdf"
            )
        document.state, document.promoted_key = "AVAILABLE", key
        return True

    monkeypatch.setattr(document_worker, "_check_and_promote", _promoted)


def make_identity_fact(student, *, confirmed=True, full_name="Jane Doe"):
    """A confirmed name for a student, matching what the _content() helpers build.

    personal_information is a verified claim, so a draft for a student with no
    IDENTITY fact carries a blocking UNSUPPORTED verdict and never approves.
    Shared here because four test modules need the same rows.
    """
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.IDENTITY,
        payload={"full_name": full_name},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="upload:test",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        created_by=student,
    )


def make_program(
    *,
    country_code: str = "GB",
    academic_track: str = "",
    portfolio_led: bool = False,
) -> Program:
    """An Institution + Program pair, for tests exercising shape_from_prompt/
    defaults_for (apps.documents.letter_shape/letter_defaults).

    Institution/Program are shared-catalog models with no tenant scoping and
    no factory of their own, so three test modules
    (test_letters.py, test_letter_shape.py, test_letter_end_to_end.py) each
    built this by hand until Task 7 fix round 1 (finding 6) collapsed them
    into this one. Never asserted on by name/city, only by the three fields
    letter shape resolution actually reads.
    """
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}",
        name="Stub University",
        country_code=country_code,
        official_website="https://stub.example.test",
    )
    return Program.objects.create(
        institution=institution,
        canonical_key=f"program:{uuid4()}",
        name="Stub Programme",
        campus_name="Main Campus",
        city="Stub City",
        country_code=country_code,
        location_key=f"{country_code.lower()}:stub",
        degree_level="MASTER",
        academic_track=academic_track,
        portfolio_led=portfolio_led,
        teaching_languages=["English"],
        duration_months=12,
    )


def make_fact(student, category, payload, *, tier=VerifiedFact.SourceTier.STUDENT_STATEMENT):
    """An unconfirmed fact of any category, as ingest_uploaded_cv writes one.

    The gap-interview modules all need the same shape -- a row the detectors
    can find a hole in -- so the three test modules that exercise them share
    this rather than each carrying a copy.
    """
    return VerifiedFact.objects.create(
        student=student,
        category=category,
        payload=payload,
        source_tier=tier,
        source_ref="upload:cv",
        confirmed_by=None,
        created_by=student,
    )
