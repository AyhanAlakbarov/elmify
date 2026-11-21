"""Form inputs a student can actually fill in, for the profile questions whose
answer is a structured value (money, a degree, language certificates).

Each widget still produces ONE value under the question's `value` name, as a
JSON string, so the consultation's validation (`forms._canonical_value`) and
everything after it is unchanged. A client that posts `value` directly (the
tests, an API caller) keeps working: the widget prefers it when present.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from django import forms
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString, mark_safe

from apps.documents.templatetags.cv_countries import _NAMES as COUNTRY_NAMES

#: Shown first in currency pickers: the markets Elmify serves and where students go.
COMMON_CURRENCIES = (
    ("EUR", "EUR — Euro"),
    ("USD", "USD — US dollar"),
    ("GBP", "GBP — British pound"),
    ("AZN", "AZN — Azerbaijani manat"),
    ("KZT", "KZT — Kazakhstani tenge"),
    ("UZS", "UZS — Uzbekistani som"),
    ("KGS", "KGS — Kyrgyzstani som"),
    ("TJS", "TJS — Tajikistani somoni"),
    ("TMT", "TMT — Turkmenistani manat"),
    ("INR", "INR — Indian rupee"),
    ("PKR", "PKR — Pakistani rupee"),
    ("CNY", "CNY — Chinese yuan"),
    ("TRY", "TRY — Turkish lira"),
    ("RUB", "RUB — Russian rouble"),
    ("KRW", "KRW — South Korean won"),
)

#: Readable names for the closed answers, shared with the review screen.
CHOICE_LABELS: Mapping[str, Mapping[str, str]] = {
    "funding_dependency": {
        "MANDATORY": "No, I can only go with a scholarship",
        "IMPORTANT": "A scholarship matters a lot, but I can pay part",
        "OPTIONAL": "Yes, I can pay my own way",
    },
    "career_intent": {
        "WORK_ABROAD": "Work in that country",
        "RETURN_HOME": "Return home",
        "PHD": "Go into academic research",
        "UNDECIDED": "Not sure yet",
    },
}


def country_choices(blank: str = "Choose a country") -> list[tuple[str, str]]:
    ordered = sorted(COUNTRY_NAMES.items(), key=lambda pair: pair[1])
    return [("", blank), *((code, name) for code, name in ordered)]


_BY_NAME = {name.casefold(): code for code, name in COUNTRY_NAMES.items()}
_BY_NAME.update(
    {
        "uk": "GB",
        "britain": "GB",
        "great britain": "GB",
        "england": "GB",
        "usa": "US",
        "united states of america": "US",
        "america": "US",
        "holland": "NL",
        "korea": "KR",
        "türkiye": "TR",
        "turkiye": "TR",
        "czech republic": "CZ",
        "russian federation": "RU",
    }
)


def country_code(text: str) -> str | None:
    """A typed country -- a code ("de") or a name ("Germany") -- as its code."""
    cleaned = text.strip()
    if len(cleaned) == 2 and cleaned.upper() in COUNTRY_NAMES:
        return cleaned.upper()
    return _BY_NAME.get(cleaned.casefold())


@dataclass(frozen=True)
class Part:
    name: str
    label: str
    kind: str = "text"  # text | number | date | select
    choices: Sequence[tuple[str, str]] = ()


def _input(part: Part, input_id: str, input_name: str, value: str) -> SafeString:
    if part.kind == "select":
        options = format_html_join(
            "",
            '<option value="{}"{}>{}</option>',
            (
                (code, mark_safe(" selected") if code == value else "", label)  # nosec B703 B308 - constant
                for code, label in part.choices
            ),
        )
        return format_html('<select id="{}" name="{}">{}</select>', input_id, input_name, options)
    extra = mark_safe(' step="0.01" min="0" inputmode="decimal"') if part.kind == "number" else ""  # nosec B703 B308 - constant
    return format_html(
        '<input type="{}" id="{}" name="{}" value="{}"{}>',
        part.kind,
        input_id,
        input_name,
        value,
        extra,
    )


class StructuredWidget(forms.Widget):
    """Renders structured sub-inputs for a single composite question."""

    is_composite = True

    def __init__(self, parts: Sequence[Part]) -> None:
        super().__init__()
        self.parts = tuple(parts)

    def _row_from(self, value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            try:
                value = json.loads(value) if value else None
            except ValueError:
                return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
        return {}

    def render(
        self, name: str, value: Any, attrs: dict[str, Any] | None = None, renderer: Any = None
    ) -> SafeString:
        current = self._row_from(value)
        cells = []
        for part in self.parts:
            input_name = f"{name}_{part.name}"
            input_id = f"id_{input_name}"
            raw = current.get(part.name, "")
            cells.append(
                format_html(
                    '<p class="q-part"><label for="{}">{}</label>{}</p>',
                    input_id,
                    part.label,
                    _input(part, input_id, input_name, "" if raw is None else str(raw)),
                )
            )
        return format_html(
            '<div class="q-structured"><div class="q-row">{}</div></div>',
            mark_safe("".join(cells)),  # nosec B703 B308 - built from format_html
        )


def money_widget() -> StructuredWidget:
    return StructuredWidget(
        (
            Part("amount", "Amount", "number"),
            Part("currency", "Currency", "select", choices=COMMON_CURRENCIES),
        )
    )
