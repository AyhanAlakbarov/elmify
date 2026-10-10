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

EVIDENCE_TYPES = (
    ("", "Choose…"),
    ("TEST", "Test score (IELTS, TOEFL, TestDaF…)"),
    ("DEGREE", "A degree taught in this language"),
    ("ATTESTED", "Letter from my university"),
    ("OTHER", "Other"),
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
        "PHD": "Continue to a PhD",
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


_OPTIONAL = mark_safe(' <span class="muted">(optional)</span>')  # nosec B703 B308 - constant


@dataclass(frozen=True)
class Part:
    name: str
    label: str
    kind: str = "text"  # text | number | date | select
    choices: Sequence[tuple[str, str]] = ()
    hint: str = ""
    optional: bool = False


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
    """Renders `rows` copies of `parts`; returns their values as one JSON string.

    `shape` turns the list of filled-in rows into the answer: a single object,
    or a list of objects. A row with every part blank is not an answer.
    """

    is_composite = True

    def __init__(self, parts: Sequence[Part], *, rows: int = 1, many: bool = False) -> None:
        super().__init__()
        self.parts = tuple(parts)
        self.rows = rows
        self.many = many

    def _field_name(self, name: str, row: int, part: Part) -> str:
        return f"{name}_{row}_{part.name}" if self.rows > 1 else f"{name}_{part.name}"

    def value_from_datadict(self, data: Any, files: Any, name: str) -> Any:
        if name in data:  # a JSON value posted directly
            return data.get(name)
        rows = []
        for row in range(self.rows):
            values = {
                part.name: str(data.get(self._field_name(name, row, part), "")).strip()
                for part in self.parts
            }
            if any(values.values()):
                rows.append({key: value for key, value in values.items() if value})
        if not rows:
            return ""
        return json.dumps(rows if self.many else rows[0])

    def _rows_from(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, str):
            try:
                value = json.loads(value) if value else None
            except ValueError:
                return []
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def render(
        self, name: str, value: Any, attrs: dict[str, Any] | None = None, renderer: Any = None
    ) -> SafeString:
        filled = self._rows_from(value)
        groups = []
        for row in range(self.rows):
            current = filled[row] if row < len(filled) else {}
            cells = []
            for part in self.parts:
                input_name = self._field_name(name, row, part)
                input_id = f"id_{input_name}"
                raw = current.get(part.name, "")
                hint = (
                    format_html('<small class="muted">{}</small>', part.hint) if part.hint else ""
                )
                cells.append(
                    format_html(
                        '<p class="q-part"><label for="{}">{}{}</label>{}{}</p>',
                        input_id,
                        part.label,
                        _OPTIONAL if part.optional else "",
                        _input(part, input_id, input_name, "" if raw is None else str(raw)),
                        hint,
                    )
                )
            heading = (
                format_html('<p class="q-row-head">{} {}</p>', "Certificate", row + 1)
                if self.rows > 1
                else ""
            )
            groups.append(
                format_html('<div class="q-row">{}{}</div>', heading, mark_safe("".join(cells)))  # nosec B703 B308 - built from format_html
            )
        return format_html('<div class="q-structured">{}</div>', mark_safe("".join(groups)))  # nosec B703 B308 - built from format_html


def money_widget() -> StructuredWidget:
    return StructuredWidget(
        (
            Part("amount", "Amount", "number"),
            Part("currency", "Currency", "select", choices=COMMON_CURRENCIES),
        )
    )


def language_evidence_widget() -> StructuredWidget:
    return StructuredWidget(
        (
            Part("language", "Language", hint="For example English or German."),
            Part("level", "Score or level", hint="For example IELTS 7.0 or C1."),
            Part("evidence_type", "What it is", "select", choices=EVIDENCE_TYPES),
            Part("available_by", "Date you have it (or will)", "date"),
        ),
        rows=2,
        many=True,
    )


def academic_history_widget() -> StructuredWidget:
    return StructuredWidget(
        (
            Part("institution", "University"),
            Part("country_code", "Country", "select", choices=country_choices()),
            Part("qualification", "Degree", hint="For example BSc or Bachelor of Arts."),
            Part("field", "Subject"),
            Part(
                "grade", "Your grade or GPA", hint="As written on your transcript, e.g. 3.6 or 85."
            ),
            Part("grading_scale", "Out of", hint="The top of the scale, e.g. 4.0 or 100."),
            Part(
                "completed_on",
                "Graduation date",
                "date",
                hint="Leave empty if you are still studying.",
                optional=True,
            ),
        ),
        many=True,
    )
