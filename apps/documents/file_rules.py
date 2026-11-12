"""A programme's file rules, folded to one rule per document (spec §7, D4).

Input: `Application.kit_file_rules`, the tenant copy of `Program.file_rules`
(rule_sinks.to_file_rules). Conflicts resolve to the safer reading or to
nothing: the smaller cap; for formats the intersection, or no format when two
sentences contradict; for names, none when two differ. A conditional record
binds no student until their own facts are compared (addendum §6.6).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

#: The draft and upload kinds a file rule can name. A kind IS its FILE_FIELDS document:
#: one name each, so nothing translates between them.
DRAFT_DOCUMENTS = frozenset({"CV", "MOTIVATION_LETTER"})
UPLOAD_DOCUMENTS = frozenset(
    {"CV", "TRANSCRIPT", "PASSPORT", "DIPLOMA", "LANGUAGE_CERTIFICATE", "REFERENCE_LETTER"}
)
_ALLOWS = {"PDF": {"PDF"}, "JPG": {"JPG"}, "PDF_OR_JPG": {"PDF", "JPG"}}


@dataclass(frozen=True)
class FileRule:
    max_bytes: int | None = None
    format: str | None = None  # "PDF" | "JPG" | "PDF_OR_JPG"
    one_file: bool = False
    name_pattern: str | None = None

    @property
    def empty(self) -> bool:
        return self == FileRule()


def _applies(
    records: Iterable[Mapping[str, object]], documents: set[str]
) -> list[Mapping[str, object]]:
    # A JSONField list can hold anything: non-dict rows are skipped.
    return [
        r
        for r in records
        if isinstance(r, Mapping) and r.get("document") in documents and not r.get("conditional")
    ]


def _cap(value: object) -> int | None:
    """A positive whole number of bytes, or None for anything else (junk is skipped)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return value if isinstance(value, int) and value > 0 else None


def _fold(records: list[Mapping[str, object]], *, one_file_from: set[str]) -> FileRule:
    # A malformed record (missing field/value, unreadable cap) is skipped, never raised:
    # one bad stored row must not crash a kit. A format outside _ALLOWS (e.g. "DOCX")
    # is skipped the same way.
    caps = [c for r in records if r.get("field") == "max_bytes" and (c := _cap(r.get("value")))]
    formats = {
        str(r.get("value"))
        for r in records
        if r.get("field") == "format" and r.get("value") in _ALLOWS
    }
    allowed = set.intersection(*(_ALLOWS[f] for f in formats)) if formats else set()
    fmt = None if not allowed else ("PDF_OR_JPG" if allowed == {"PDF", "JPG"} else allowed.pop())
    combines = {
        str(r.get("value"))
        for r in records
        if r.get("field") == "combine"
        and r.get("document") in one_file_from
        and r.get("value") in ("ONE_FILE", "SEPARATE_FILES")  # NOT_STATED / junk: skipped
    }
    names = {
        str(r.get("value")) for r in records if r.get("field") == "name_pattern" and r.get("value")
    }
    return FileRule(
        max_bytes=min(caps) if caps else None,
        format=fmt,
        one_file=combines == {"ONE_FILE"},
        name_pattern=names.pop() if len(names) == 1 else None,
    )


def rule_for(records: Iterable[Mapping[str, object]], document: str) -> FileRule:
    """This document's rule. EVERY_DOCUMENT's size and format apply to each file;
    its ONE_FILE is the bundle (bundle_rule), never a per-document merge."""
    return _fold(_applies(records, {document, "EVERY_DOCUMENT"}), one_file_from={document})


def bundle_rule(records: Iterable[Mapping[str, object]]) -> FileRule | None:
    """The whole application as one PDF (R-008), or None when no page asked for it."""
    rule = _fold(_applies(records, {"EVERY_DOCUMENT"}), one_file_from={"EVERY_DOCUMENT"})
    if not rule.one_file:
        return None
    return FileRule(
        max_bytes=rule.max_bytes, format="PDF", one_file=True, name_pattern=rule.name_pattern
    )
