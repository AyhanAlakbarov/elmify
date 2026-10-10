"""Publishing and choosing legal document versions."""

import hashlib
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.privacy.models import LegalDocument

LANGUAGES = ("az", "en", "ru")
KINDS = tuple(LegalDocument.Kind.values)
LEGAL_DIR = Path(__file__).resolve().parent / "legal"


def _check(kind: str, language: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown legal document kind {kind!r}")
    if language not in LANGUAGES:
        raise ValueError(f"unsupported language {language!r}")


def publish(kind: str, language: str, body: str, *, material: bool) -> tuple[LegalDocument, bool]:
    """Add a version when the text changed; the same text returns the latest row."""
    _check(kind, language)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with transaction.atomic():
        latest = (
            LegalDocument.objects.select_for_update()
            .filter(kind=kind, language=language)
            .order_by("-version")
            .first()
        )
        if latest is not None and latest.sha256 == digest:
            return latest, False
        row = LegalDocument.objects.create(
            kind=kind,
            language=language,
            version=(latest.version + 1) if latest else 1,
            body=body,
            sha256=digest,
            material=material,
            effective_at=timezone.now(),
        )
        return row, True


def current(kind: str, language: str) -> LegalDocument | None:
    """The latest version in `language`, else in English, else None."""
    for lang in dict.fromkeys((language, "en")):
        row = LegalDocument.objects.filter(kind=kind, language=lang).order_by("-version").first()
        if row is not None:
            return row
    return None


def shipped_files() -> list[tuple[str, str, Path]]:
    """(kind, language, path) for every `legal/<kind>.<lang>.md` file."""
    out = []
    for path in sorted(LEGAL_DIR.glob("*.md")):
        kind, _, language = path.stem.rpartition(".")
        _check(kind, language)
        out.append((kind, language, path))
    return out
