"""Which documents a student must have accepted, and the lock that enforces it."""

from uuid import UUID

from django.utils import timezone

from apps.privacy import documents
from apps.privacy.models import Acceptance, LegalDocument
from apps.tenancy.models import Membership


def required_kinds(tenant_id: UUID) -> tuple[str, str]:
    from apps.research.models import PlatformAgency

    direct = PlatformAgency.objects.filter(agency_id=tenant_id).exists()
    return ("terms", "privacy_notice_direct" if direct else "privacy_notice_agency")


def documents_to_accept(tenant_id: UUID, language: str) -> list[LegalDocument]:
    docs = [documents.current(kind, language) for kind in required_kinds(tenant_id)]
    return [d for d in docs if d is not None]


def record(
    student: Membership, docs: list[LegalDocument], *, surface: str, language: str
) -> None:
    now = timezone.now()
    for doc in docs:
        Acceptance.objects.get_or_create(
            student=student,
            document=doc,
            defaults={"accepted_at": now, "surface": surface, "language": language},
        )


def needs_acceptance(student: Membership) -> bool:
    """True when some required kind has a material version newer than any the student accepted.

    Each kind is compared in the language of the document the student actually
    accepted for it, so a translation published later never re-locks someone who
    accepted the English fallback; material changes are published in every
    language together. A kind never accepted is judged in the language of the
    student's last acceptance (English before any). A kind with no published
    document asks for nothing.
    """
    if student.role != Membership.Role.STUDENT:
        return False
    accepted_rows = Acceptance.objects.filter(student=student)
    last = accepted_rows.order_by("-accepted_at").first()
    fallback_language = last.language if last else "en"
    for kind in required_kinds(student.tenant_id):
        last_for_kind = (
            accepted_rows.filter(document__kind=kind)
            .select_related("document")
            .order_by("-accepted_at", "-document__version")
            .first()
        )
        if last_for_kind is not None:
            language = last_for_kind.document.language
        else:
            doc = documents.current(kind, fallback_language)
            if doc is None:
                continue
            language = doc.language
        newest_material = (
            LegalDocument.objects.filter(kind=kind, language=language, material=True)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        ) or 0
        accepted = (
            accepted_rows.filter(document__kind=kind, document__language=language)
            .order_by("-document__version")
            .values_list("document__version", flat=True)
            .first()
        ) or 0
        if accepted < newest_material:
            return True
    return False
