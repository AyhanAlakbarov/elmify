from __future__ import annotations

from collections.abc import Callable

from django.db import transaction

from apps.accounts.models import StudentProfileVersion
from apps.tenancy.models import Membership

from .models import VerifiedFact

_SOURCE_PREFIX = "profile-bridge"


def _latest_profile(student: Membership) -> StudentProfileVersion | None:
    return StudentProfileVersion.objects.filter(student=student).order_by("-version").first()


def _education_payload(record: dict[str, object]) -> dict[str, object]:
    """Canonical EDUCATION keys -- the ones verification.py reads.

    city and start_date are absent from AcademicRecord, so they stay None:
    a fact that does not state a detail never conflicts with a CV that does.
    """
    return {
        "institution_original": record["institution"],
        "degree_as_awarded": record["qualification"],
        "city": None,
        "country": record["country_code"],
        "start_date": None,
        "end_date": record.get("completed_on"),
        "field": record.get("field"),
        "grade_native": record.get("grade"),
        "grade_scale": record.get("grading_scale"),
    }


def _language_payload(record: dict[str, object]) -> dict[str, object]:
    return {
        "language": record["language"],
        "cefr_level": record["level"],
        "test_name": None,
        "test_score": None,
        "evidence_type": record.get("evidence_type"),
    }


_SECTIONS: tuple[tuple[str, str, Callable[[dict[str, object]], dict[str, object]]], ...] = (
    ("academic_history", VerifiedFact.Category.EDUCATION, _education_payload),
    ("language_evidence", VerifiedFact.Category.LANGUAGE, _language_payload),
)


def _current_fact_for_slot(
    student: Membership, *, category: str, index: int
) -> VerifiedFact | None:
    """The live fact for one profile slot.

    Keyed on the slot index, not the profile version: source_ref carries the
    version for provenance, so it changes every time the student saves, and
    matching on it would make every run look like a brand-new fact.

    # ponytail: slot index is the record identity. Reordering academic_history
    # makes two slots supersede each other's facts; the fix is a stable id on
    # AcademicRecord, which is an apps.accounts schema change, not this module's.
    """
    return (
        VerifiedFact.objects.filter(
            student=student,
            category=category,
            source_ref__startswith=f"{_SOURCE_PREFIX}:",
            source_ref__endswith=f":{index}",
            superseded_by__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )


@transaction.atomic
def bridge_profile_to_facts(student: Membership) -> tuple[VerifiedFact, ...]:
    """Seed the ledger from the student's latest profile snapshot.

    Idempotent: an unchanged slot writes nothing, a changed slot writes exactly
    one superseding row, and slots that did not change are untouched. Everything
    written is a candidate (confirmed_by=None) -- the bridge never produces
    something the generator may use.
    """
    profile = _latest_profile(student)
    if profile is None:
        return ()
    created: list[VerifiedFact] = []
    for section, category, build_payload in _SECTIONS:
        for index, record in enumerate(profile.snapshot.get(section, [])):
            payload = build_payload(record)
            existing = _current_fact_for_slot(student, category=category, index=index)
            if existing is not None and existing.payload == payload:
                continue
            created.append(
                VerifiedFact.objects.create(
                    student=student,
                    category=category,
                    payload=payload,
                    source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                    source_ref=f"{_SOURCE_PREFIX}:{profile.id}:{index}",
                    confirmed_by=None,
                    supersedes=existing,
                    created_by=student,
                )
            )
    return tuple(created)
