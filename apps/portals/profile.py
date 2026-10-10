"""Verified facts, in the vocabulary a FieldMap entry uses.

A FieldMap entry names "personal.given_name". A VerifiedFact holds a category
and a payload dict. Nothing else in the codebase needs that translation, so it
lives here rather than in apps/documents, and it is deliberately one-way:
nothing writes facts from a portal page.
"""

from apps.documents.models import VerifiedFact
from apps.tenancy.models import Membership


def verified_values(student: Membership) -> dict[str, str]:
    """Confirmed, current facts flattened to ``"category.key" -> value``.

    # ponytail: last row wins for a repeated category. A form that needs the
    # second degree rather than the most recent one needs indexed keys
    # ("education.1.institution"), which no field map asks for yet.
    """
    superseded = set(
        VerifiedFact.objects.filter(student=student, supersedes__isnull=False).values_list(
            "supersedes_id", flat=True
        )
    )
    values: dict[str, str] = {}
    # Every confirmed category, TIMELINE included (owner decision 2026-10-06:
    # one ledger, every consumer). Like every multi-row category here, the
    # last row of a key wins, so a student with two gaps offers the later one.
    for fact in (
        VerifiedFact.objects.filter(student=student, confirmed_at__isnull=False)
        .exclude(id__in=superseded)
        .order_by("created_at")
    ):
        for key, value in fact.payload.items():
            # Text only. A list or a number here belongs to document
            # generation; typing its repr into a portal field is worse than
            # escalating the field as missing.
            if isinstance(value, str) and value.strip():
                values[f"{fact.category.lower()}.{key}"] = value
    return values
