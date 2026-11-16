"""Repeating rows for the profile's list questions: jobs, volunteering,
publications, projects (2026-11-16).

Each question is one Django field that posts `value_0 … value_N` like every
other structured answer here, so `ConsultationQuestionForm` and the stored-draft
check stay unchanged. A blank row is skipped; a half-filled row is refused with
the row and the missing part named. `app.js` shows one empty row at a time and an
"Add another" button; without JavaScript every row is visible.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from django import forms
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString, mark_safe


@dataclass(frozen=True)
class RowPart:
    name: str
    label: str
    #: text | textarea | month | year | select | hidden
    kind: str = "text"
    choices: Sequence[tuple[str, str]] = ()
    required: bool = True
    placeholder: str = ""
    #: A hidden part's fixed value.
    fixed: str = ""


_OPTIONAL_TAG = mark_safe(' <small class="muted">optional</small>')  # nosec B703 B308 - constant
_MONTH = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?$")


def _shown(part: RowPart, raw: object) -> str:
    text = "" if raw is None else str(raw)
    if part.kind == "month" and (match := _MONTH.match(text)):
        return f"{match.group(1)}-{match.group(2)}"
    return text


def _input(part: RowPart, input_id: str, name: str, value: str) -> SafeString:
    if part.kind == "hidden":
        return format_html('<input type="hidden" name="{}" value="{}">', name, part.fixed)
    if part.kind == "select":
        options = format_html_join(
            "",
            '<option value="{}"{}>{}</option>',
            (
                (code, mark_safe(" selected") if code == value else "", label)  # nosec B703 B308 - constant
                for code, label in (("", "Choose…"), *part.choices)
            ),
        )
        return format_html('<select id="{}" name="{}">{}</select>', input_id, name, options)
    if part.kind == "textarea":
        return format_html(
            '<textarea id="{}" name="{}" rows="2" maxlength="500" placeholder="{}">{}</textarea>',
            input_id, name, part.placeholder, value,
        )
    kind, extra = {
        "month": ("month", ""),
        "year": ("number", ' min="1950" max="2100" inputmode="numeric"'),
    }.get(part.kind, ("text", ""))
    return format_html(
        '<input type="{}" id="{}" name="{}" value="{}" placeholder="{}"{}>',
        kind, input_id, name, value, part.placeholder, mark_safe(extra),  # nosec B703 B308 - constant
    )


class RowsWidget(forms.Widget):
    is_composite = True

    def __init__(self, parts: Sequence[RowPart], rows: int, noun: str) -> None:
        super().__init__()
        self.parts = tuple(parts)
        self.rows = rows
        self.noun = noun

    def value_from_datadict(self, data: Any, files: Any, name: str) -> list[str]:
        width = len(self.parts)
        return [str(data.get(f"{name}_{i}", "") or "") for i in range(self.rows * width)]

    def _flat(self, value: Any) -> list[str]:
        width = len(self.parts)
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            cells = list(value)
        else:
            records = value if isinstance(value, list) else []
            cells = [
                _shown(part, record.get(part.name)) if isinstance(record, dict) else ""
                for record in records
                for part in self.parts
            ]
        return (cells + [""] * (self.rows * width))[: self.rows * width]

    def render(
        self, name: str, value: Any, attrs: dict[str, Any] | None = None, renderer: Any = None
    ) -> SafeString:
        width = len(self.parts)
        cells = self._flat(value)
        rows = []
        for row in range(self.rows):
            parts = []
            for col, part in enumerate(self.parts):
                index = row * width + col
                input_name = f"{name}_{index}"
                input_id = f"id_{input_name}"
                control = _input(part, input_id, input_name, cells[index])
                if part.kind == "hidden":
                    parts.append(control)
                    continue
                wide = " q-part-wide" if part.kind == "textarea" or part.name == "title" else ""
                parts.append(
                    format_html(
                        '<div class="q-part{}"><label for="{}">{}{}</label>{}</div>',
                        wide, input_id, part.label,
                        "" if part.required else _OPTIONAL_TAG,
                        control,
                    )
                )
            rows.append(
                format_html(
                    '<fieldset class="q-row-card" data-repeat-row><legend>{} {}</legend>'
                    '<div class="q-grid">{}</div></fieldset>',
                    self.noun, row + 1, mark_safe("".join(parts)),  # nosec B703 B308 - built from format_html
                )
            )
        return format_html(
            '<div class="q-rows" data-repeat data-noun="{}">{}</div>',
            self.noun, mark_safe("".join(rows)),  # nosec B703 B308 - built from format_html
        )


class RowsField(forms.Field):
    """A list of records, one per filled row. `build` turns a row's text into the
    stored record or raises ValueError with a sentence for the student."""

    widget = RowsWidget

    def __init__(
        self,
        parts: Sequence[RowPart],
        *,
        rows: int,
        noun: str,
        build: Callable[[dict[str, str]], dict[str, object]],
    ) -> None:
        self.parts = tuple(parts)
        self.rows = rows
        self.noun = noun
        self.build = build
        super().__init__(required=False, widget=RowsWidget(parts, rows, noun))

    def to_python(self, value: Any) -> list[dict[str, object]]:
        if isinstance(value, list) and all(isinstance(v, dict) for v in value):
            return value  # an already-stored answer, re-validated by the profile schema
        width = len(self.parts)
        cells = list(value or []) + [""] * (self.rows * width)
        out: list[dict[str, object]] = []
        for row in range(self.rows):
            raw = {
                part.name: (
                    part.fixed if part.kind == "hidden" else str(cells[row * width + i]).strip()
                )
                for i, part in enumerate(self.parts)
            }
            typed = [raw[p.name] for p in self.parts if p.kind != "hidden"]
            if not any(typed):
                continue
            for part in self.parts:
                if part.required and part.kind != "hidden" and not raw[part.name]:
                    raise forms.ValidationError(
                        f"{self.noun} {row + 1}: add the {part.label.lower()}, or clear the row."
                    )
            try:
                out.append(self.build(raw))
            except ValueError as error:
                raise forms.ValidationError(f"{self.noun} {row + 1}: {error}") from error
        return out


def month_to_date(text: str) -> str | None:
    """'2024-05' (a month input) as '2024-05-01'; '' as None."""
    if not text:
        return None
    match = _MONTH.match(text)
    if not match:
        raise ValueError("use the month picker for dates.")
    return f"{match.group(1)}-{match.group(2)}-01"


def year_or_none(text: str) -> int | None:
    if not text:
        return None
    if not text.isdigit():
        raise ValueError("the year should be four digits.")
    return int(text)
