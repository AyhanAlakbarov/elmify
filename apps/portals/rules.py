"""Per-portal rules the bench taught (spec §9): every amber fixed here, never
left for the student. Applied server-side before a value leaves in a packet."""

from __future__ import annotations

import re
from datetime import date
from typing import Protocol

from .profile import field_class

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_FORMATS = {
    "DD.MM.YYYY": "%d.%m.%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/YYYY": "%m/%Y",
    "MM.YYYY": "%m.%Y",
    "YYYY-MM": "%Y-%m",
}
_MONTH_FORMATS = {"MM/YYYY", "MM.YYYY", "YYYY-MM"}


class RulesForm(Protocol):
    """What the rules read off a PortalForm; the bench runner passes the same."""

    value_formats: dict[str, str]
    option_synonyms: dict[str, dict[str, str]]
    readback_equivalences: dict[str, str]


def format_value(value: str, fmt: str) -> str:
    pattern = _FORMATS.get(fmt)
    if pattern is None:
        return value
    if _ISO.match(value):
        try:
            return date.fromisoformat(value).strftime(pattern)
        except ValueError:
            return value
    month_match = _ISO_MONTH.match(value)
    if month_match and fmt in _MONTH_FORMATS:
        try:
            return date(int(month_match.group(1)), int(month_match.group(2)), 1).strftime(pattern)
        except ValueError:
            return value
    return value


def apply_rules(portal_form: RulesForm, profile_field: str, value: str) -> str:
    key = field_class(profile_field)
    value = format_value(value, (portal_form.value_formats or {}).get(key, ""))
    return (portal_form.option_synonyms or {}).get(key, {}).get(value, value)
