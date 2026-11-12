import json
from collections.abc import Mapping
from datetime import date
from functools import cache
from typing import Annotated, Any, cast

from babel import Locale
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from pydantic import TypeAdapter, ValidationError

from apps.reference_data import ISO_3166_ALPHA2_CODES, ISO_4217_CODES

from .question_widgets import (
    CHOICE_LABELS,
    country_choices,
    money_widget,
)
from .schemas import StudentProfileSnapshot

_COMMA_SEPARATED = {
    "acceptable_teaching_languages",
    "allowed_countries",
    "excluded_countries",
    "research_interests",
}
#: Answers that are records (lists or objects), typed through structured fields since the
#: onboarding friction design (2026-10-15, variant 1): a JSON box here was a dead end no
#: student could fill in.
_JSON_VALUES = {
    "academic_history",
    "language_evidence",
}
_MONEY_VALUES = {"application_budget", "self_funding_capacity", "budget_stretch"}
_CURRENCIES = [(code, code) for code in sorted(ISO_4217_CODES)]
_OPTION_CHOICES: dict[str, tuple[tuple[str, str], ...]] = {
    "career_intent": (
        ("WORK_ABROAD", "Work in that country after graduating"),
        ("RETURN_HOME", "Return to my home country"),
        ("PHD", "Go into academic research after graduating"),
        ("UNDECIDED", "Not decided yet"),
    ),
    "funding_dependency": (
        ("MANDATORY", CHOICE_LABELS["funding_dependency"]["MANDATORY"]),
        ("IMPORTANT", "Prefer a scholarship, but I can cover part of the cost"),
        ("OPTIONAL", "Yes — I can fund my studies myself"),
    ),
}
_COUNTRY_NAME_ALIASES: dict[str, str] = {
    "UK": "GB",
    "GREAT BRITAIN": "GB",
    "ENGLAND": "GB",
    "SCOTLAND": "GB",
    "WALES": "GB",
    "USA": "US",
    "U.S.A.": "US",
    "U.S.": "US",
    "UNITED STATES OF AMERICA": "US",
    "UAE": "AE",
    "TURKEY": "TR",
    "TURKIYE": "TR",
    "TÜRKIYE": "TR",
    "TÜRKIYE CUMHURIYETI": "TR",
    "TURKIYE CUMHURIYETI": "TR",
    "REPUBLIC OF TURKEY": "TR",
    "REPUBLIC OF TÜRKIYE": "TR",
    "REPUBLIC OF TURKIYE": "TR",
    "AZERBAIJAN REPUBLIC": "AZ",
    "REPUBLIC OF AZERBAIJAN": "AZ",
    "AZƏRBAYCAN": "AZ",
    "AZERBAYCAN": "AZ",
    "AZƏRBAYCAN RESPUBLIKASI": "AZ",
    "AZƏRBAYCAN RESPUBLİKASI": "AZ",
    "AZERBAYCAN RESPUBLIKASI": "AZ",
    "DEUTSCHLAND": "DE",
    "BUNDESREPUBLIK DEUTSCHLAND": "DE",
    "FEDERAL REPUBLIC OF GERMANY": "DE",
    "SOUTH KOREA": "KR",
    "REPUBLIC OF KOREA": "KR",
    "KOREA": "KR",
    "HOLLAND": "NL",
    "THE NETHERLANDS": "NL",
    "CZECH REPUBLIC": "CZ",
    "RUSSIA": "RU",
    "RUSSIAN FEDERATION": "RU",
    "РОССИЯ": "RU",
    "РОССИЙСКАЯ ФЕДЕРАЦИЯ": "RU",
    "PEOPLE'S REPUBLIC OF CHINA": "CN",
    "PEOPLES REPUBLIC OF CHINA": "CN",
    "PRC": "CN",
}


@cache
def _country_name_lookup() -> dict[str, str]:
    table = dict(_COUNTRY_NAME_ALIASES)
    locale = Locale.parse("en")
    for code, name in locale.territories.items():
        if (
            isinstance(code, str)
            and len(code) == 2
            and code.upper() in ISO_3166_ALPHA2_CODES
            and isinstance(name, str)
        ):
            table[name.strip().upper()] = code.upper()
    return table


def normalize_country_code(raw: object) -> str:
    """Resolve a 2-letter ISO code, common alias ('UK', 'USA'), or English country name."""
    if not isinstance(raw, str):
        return ""
    cleaned = " ".join(raw.strip().split())
    if not cleaned:
        return ""
    upper = cleaned.upper()
    if len(upper) == 2 and upper in ISO_3166_ALPHA2_CODES:
        return upper
    return _country_name_lookup().get(upper, upper)
_OPTIONAL_VALUES = {
    "language_evidence",
    "allowed_countries",
    "excluded_countries",
    "additional_notes",
    "budget_stretch",
    "self_funding_capacity",
    "research_interests",
}
_DATES = {"intended_intake", "date_of_birth", "expected_completion"}

POPULAR_DESTINATIONS: tuple[tuple[str, str], ...] = (
    ("DE", "Germany"),
    ("GB", "United Kingdom"),
    ("NL", "Netherlands"),
    ("SE", "Sweden"),
    ("FR", "France"),
    ("IT", "Italy"),
    ("CH", "Switzerland"),
    ("AT", "Austria"),
    ("BE", "Belgium"),
    ("FI", "Finland"),
    ("IE", "Ireland"),
    ("ES", "Spain"),
    ("DK", "Denmark"),
    ("NO", "Norway"),
    ("CZ", "Czechia"),
    ("EE", "Estonia"),
    ("LT", "Lithuania"),
    ("HU", "Hungary"),
    ("PL", "Poland"),
    ("US", "United States"),
    ("CA", "Canada"),
    ("AU", "Australia"),
    ("NZ", "New Zealand"),
    ("KR", "South Korea"),
    ("JP", "Japan"),
    ("SG", "Singapore"),
    ("CN", "China"),
    ("TR", "Türkiye"),
    ("AE", "United Arab Emirates"),
    ("SA", "Saudi Arabia"),
    ("QA", "Qatar"),
)
POPULAR_TEACHING_LANGUAGES: tuple[str, ...] = (
    "English",
    "German",
    "French",
    "Turkish",
    "Italian",
    "Spanish",
    "Russian",
    "Dutch",
)
POPULAR_FIELDS: tuple[str, ...] = (
    "Computer Science",
    "Data Science and Artificial Intelligence",
    "Cybersecurity",
    "Software Engineering",
    "Electrical and Computer Engineering",
    "Mechanical Engineering",
    "Chemical Engineering",
    "Chemistry",
    "Biotechnology and Bioinformatics",
    "Finance and Economics",
    "Business Administration and Management",
    "Public Policy and International Relations",
    "Law (LL.M.)",
    "Environmental Science and Sustainability",
    "Mathematics and Statistics",
    "Physics",
)
DURATION_TICK_OPTIONS: tuple[tuple[str, str], ...] = (
    ("", "Any duration (1 or 2 years)"),
    (
        "Strictly 1-year master's only.",
        "1-year master's only (strict 12-month duration)",
    ),
    (
        "Prefer a 1-year master's unless there is funding, research, or internship.",
        "Prefer 1-year master's, but open to 2-year for funding or research",
    ),
    (
        "Prefer a 2-year master's program.",
        "Prefer 2-year master's (120 ECTS)",
    ),
)
PRIORITY_TICK_OPTIONS: tuple[tuple[str, str], ...] = (
    (
        "Only top universities and prestigious scholarships.",
        (
            "Only selective flagship universities, specialized research institutes, "
            "or Erasmus Mundus programs"
        ),
    ),
    (
        "Applying for a post-admission government scholarship (admission required first).",
        (
            "Applying for a post-admission government or external scholarship "
            "(get university admission first, then scholarship)"
        ),
    ),
    (
        "I don't care about any funding options (fully self-funded).",
        "I don't care about scholarships or funding options (self-funded only)",
    ),
    (
        "No return-service bond.",
        "Avoid scholarships with a mandatory return-home bond",
    ),
    (
        "Fresh graduate, no work experience yet.",
        "Fresh graduate / no full-time work experience yet",
    ),
)
MONEY_PRESETS: dict[str, tuple[tuple[str, str], ...]] = {
    "self_funding_capacity": (
        ("NONE", "Full cost / No annual limit"),
        ("5000", "5,000 / yr"),
        ("10000", "10,000 / yr"),
        ("20000", "20,000 / yr"),
        ("30000", "30,000 / yr"),
    ),
    "application_budget": (
        ("0", "0 (Free applications only)"),
        ("100", "100"),
        ("250", "250"),
        ("500", "500"),
    ),
    "budget_stretch": (
        ("NONE", "0 (No extra stretch)"),
        ("50", "+50"),
        ("100", "+100"),
        ("250", "+250"),
    ),
}


def date_presets_for_question(
    key: str, *, today: date | None = None
) -> tuple[tuple[str, str], ...]:
    ref = today or date.today()
    y = ref.year
    if key == "intended_intake":
        candidates = [
            (date(yr, month, 1), f"{season} {yr}")
            for yr in range(y, y + 4)
            for month, season in ((2, "Spring"), (9, "Autumn / Fall"))
        ]
        upcoming = [(dt.isoformat(), label) for dt, label in candidates if dt >= ref]
        return tuple(upcoming[:4])
    if key == "expected_completion":
        candidates = [
            (date(yr, month, day), f"{label} {yr}")
            for yr in range(y, y + 4)
            for month, day, label in ((1, 31, "January"), (6, 30, "June"))
        ]
        upcoming = [(dt.isoformat(), label) for dt, label in candidates if dt >= ref]
        return tuple(upcoming[:4])
    return ()


class MoneyWidget(forms.MultiWidget):
    is_composite = True

    def __init__(self) -> None:
        super().__init__(
            (
                forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
                forms.Select(choices=_CURRENCIES),
            )
        )

    def decompress(self, value: object) -> list[object]:
        if isinstance(value, dict):
            return [value.get("amount"), value.get("currency") or "EUR"]
        return [None, "EUR"]

    def render(
        self, name: str, value: Any, attrs: dict[str, Any] | None = None, renderer: Any = None
    ) -> Any:
        return money_widget().render(name, value, attrs=attrs, renderer=renderer)


class MoneyField(forms.MultiValueField):
    """An amount and its currency, compressed to the profile's `Money` shape, so
    the stored answer is exactly what the JSON box used to accept.
    SHOULD BE DONE BY AYKHAN: the currency select's default and the layout."""

    widget = MoneyWidget

    def __init__(self, *, required: bool) -> None:
        super().__init__(
            fields=(
                forms.DecimalField(min_value=0, max_digits=14, decimal_places=2, required=False),
                forms.ChoiceField(choices=_CURRENCIES, required=False),
            ),
            require_all_fields=False,
            required=required,
        )

    def compress(self, data_list: list[object]) -> dict[str, str] | None:
        if not data_list or data_list[0] in (None, ""):
            # The currency select always sends a value, so Django's own "required"
            # check never fires on a blank amount; say it here, in plain words.
            if self.required:
                raise forms.ValidationError("Enter an amount.")
            return None
        return {"amount": str(data_list[0]), "currency": str(data_list[1])}


_DEGREE_PARTS = (
    "institution", "country_code", "qualification", "field", "grade", "grading_scale",
    "completed_on", "expected_completion",
)
_DEGREE_PLACEHOLDERS = (
    "University or institution",
    "Country (e.g. AZ or Azerbaijan)",
    "Qualification (e.g. BSc, BA)",
    "Field of study",
    "Overall grade / GPA",
    "Grading scale (e.g. 0-100 or 4.0)",
    "Graduation date (if completed)",
    "Expected graduation date",
)
_EVIDENCE_TYPES = [
    ("", ""),
    ("ATTESTED", "Official certificate / attestation"),
    ("TEST", "Language test (IELTS, TOEFL, etc.)"),
    (
        "DEGREE",
        "Completed degree with recognized Medium of Instruction (MOI) waiver (upon graduation)",
    ),
    ("OTHER", "Other proof"),
]
#: ponytail: three rows; a student with evidence for more than three languages is rare, so add a
#: row when one appears rather than build an "add another" flow now.
_LANGUAGE_ROWS = 3
_LANGUAGE_PARTS = ("language", "level", "evidence_type", "available_by")
_LANGUAGE_ROW_INCOMPLETE = (
    "For each language, fill in the level, how you can prove it and the date you will "
    "have that proof, or leave the whole row empty."
)


def _date_input(label: str = "") -> forms.DateInput:
    attrs: dict[str, str] = {"type": "date"}
    if label:
        attrs["aria-label"] = label
    return forms.DateInput(attrs=attrs)


class _RecordWidget(forms.MultiWidget):
    """Shows a stored list of records back in its inputs, `parts` per record."""

    def __init__(
        self,
        widgets: list[forms.Widget],
        parts: tuple[str, ...],
        labels: tuple[str, ...] = (),
    ) -> None:
        self.parts = parts
        self.labels = labels
        super().__init__(widgets)

    def decompress(self, value: object) -> list[object]:
        records = value if isinstance(value, list) else []
        flat = [
            record.get(part) if isinstance(record, dict) else None
            for record in records
            for part in self.parts
        ]
        return (flat + [None] * len(self.widgets))[: len(self.widgets)]

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        if isinstance(value, list) and (
            not value or any(isinstance(item, dict) for item in value)
        ):
            value = self.decompress(value)
        return super().get_context(name, value, attrs)

    def render(
        self,
        name: str,
        value: Any,
        attrs: dict[str, Any] | None = None,
        renderer: Any = None,
    ) -> Any:
        if not self.labels:
            return super().render(name, value, attrs=attrs, renderer=renderer)
        ctx = self.get_context(name, value, attrs)
        subwidgets = ctx.get("widget", {}).get("subwidgets", [])
        active_renderer = renderer or forms.renderers.get_default_renderer()
        cells = []
        for idx, sub in enumerate(subwidgets):
            sub_html = mark_safe(  # nosec B703 B308 - rendered by Django widget template
                active_renderer.render(sub["template_name"], {"widget": sub})
            )
            label = self.labels[idx] if idx < len(self.labels) else ""
            sub_id = sub.get("attrs", {}).get("id", "")
            if label:
                cells.append(
                    format_html(
                        '<div class="q-part"><label class="q-part-label"'
                        ' for="{}">{}</label>{}</div>',
                        sub_id,
                        label,
                        sub_html,
                    )
                )
            else:
                cells.append(format_html('<div class="q-part">{}</div>', sub_html))
        return format_html(
            '<div class="q-structured q-grid">{}</div>',
            mark_safe("".join(cells)),  # nosec B703 B308 - built from format_html
        )


_DEGREE_REQUIRED_LABELS = (
    ("institution", "University"),
    ("country_code", "Country"),
    ("qualification", "Degree"),
    ("field", "Subject"),
    ("grade", "Grade"),
    ("grading_scale", "Out of"),
)


class AcademicRecordField(forms.MultiValueField):
    """The latest degree, typed when no transcript reading is ready (onboarding friction
    design 2026-10-15, variant 1). Courses are never typed: they come only from a reading.
    SHOULD BE DONE BY AYKHAN: a label per input, and the layout."""

    def __init__(self) -> None:
        fields = (
            forms.CharField(max_length=200, required=False),
            forms.CharField(max_length=100, required=False),
            forms.CharField(max_length=100, required=False),
            forms.CharField(max_length=200, required=False),
            forms.CharField(max_length=50, required=False),
            forms.CharField(max_length=100, required=False),
            forms.DateField(required=False),
            forms.DateField(required=False),
        )
        widgets: list[forms.Widget] = [
            forms.TextInput(attrs={"placeholder": text, "aria-label": text})
            for text in _DEGREE_PLACEHOLDERS[:6]
        ]
        widgets[1].attrs["list"] = "country-datalist"
        widgets[2].attrs["list"] = "qualification-datalist"
        widgets[3].attrs["list"] = "field-datalist"
        widgets[5].attrs["list"] = "grading-scale-datalist"
        widgets += [
            _date_input(_DEGREE_PLACEHOLDERS[6]),
            _date_input(_DEGREE_PLACEHOLDERS[7]),
        ]
        super().__init__(
            fields=fields,
            widget=_RecordWidget(widgets, _DEGREE_PARTS, labels=_DEGREE_PLACEHOLDERS),
            require_all_fields=False,
        )

    def compress(self, data_list: list[object]) -> list[dict[str, object]] | None:
        if not data_list:
            return None
        record = dict(zip(_DEGREE_PARTS, data_list, strict=True))
        for part_key, part_label in _DEGREE_REQUIRED_LABELS:
            if not str(record.get(part_key) or "").strip():
                raise forms.ValidationError(f"{part_label}: fill this in.")
        record["country_code"] = normalize_country_code(record["country_code"])
        for key in ("completed_on", "expected_completion"):
            when = record[key]
            record[key] = when.isoformat() if isinstance(when, date) else None
        return [{**record, "courses": []}]


class LanguageEvidenceField(forms.MultiValueField):
    """Up to three languages with how each is evidenced. A blank row is skipped; a
    half-filled one is refused by the profile schema."""

    def __init__(self) -> None:
        fields: list[forms.Field] = []
        widgets: list[forms.Widget] = []
        for idx in range(1, _LANGUAGE_ROWS + 1):
            fields += [
                forms.CharField(max_length=100, required=False),
                forms.CharField(max_length=50, required=False),
                forms.ChoiceField(choices=_EVIDENCE_TYPES, required=False),
                forms.DateField(required=False),
            ]
            widgets += [
                forms.TextInput(
                    attrs={
                        "placeholder": "Language (e.g. English)",
                        "aria-label": f"Language {idx}",
                    }
                ),
                forms.TextInput(
                    attrs={
                        "placeholder": "Level or score (e.g. IELTS 6.5, C1)",
                        "aria-label": f"Level or score {idx}",
                    }
                ),
                forms.Select(
                    choices=_EVIDENCE_TYPES,
                    attrs={"aria-label": f"Proof type {idx}"},
                ),
                _date_input(f"Date available {idx}"),
            ]
        lang_labels = (
            "Language",
            "Level or score",
            "Proof type",
            "Date available (or planned)",
        ) * _LANGUAGE_ROWS
        super().__init__(
            fields=tuple(fields),
            widget=_RecordWidget(widgets, _LANGUAGE_PARTS, labels=lang_labels),
            require_all_fields=False,
            required=False,
        )

    def compress(self, data_list: list[object]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        parts = len(_LANGUAGE_PARTS)
        for start in range(0, len(data_list or []), parts):
            row = dict(zip(_LANGUAGE_PARTS, data_list[start : start + parts], strict=True))
            if not any(row.values()):
                continue
            if (
                row.get("language")
                and not row.get("level")
                and row.get("evidence_type") == "DEGREE"
            ):
                row["level"] = "C1"
            if (
                row.get("language")
                and row.get("level")
                and row.get("evidence_type") in ("DEGREE", "ATTESTED")
                and not row.get("available_by")
            ):
                row["available_by"] = date.today()
            if not all(row.values()):
                raise forms.ValidationError(_LANGUAGE_ROW_INCOMPLETE)
            row["available_by"] = cast(date, row["available_by"]).isoformat()
            rows.append(row)
        return rows


class CountryChoiceField(forms.ChoiceField):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("choices", country_choices())
        kwargs.setdefault("error_messages", {"required": "Choose a country."})
        kwargs.setdefault(
            "widget",
            forms.TextInput(
                attrs={
                    "list": "country-datalist",
                    "autofocus": "autofocus",
                    "placeholder": "e.g. Azerbaijan, Germany, UK, AZ",
                }
            ),
        )
        super().__init__(**kwargs)

    def to_python(self, value: Any) -> str:
        val = super().to_python(value)
        return normalize_country_code(val) if val else ""


def question_field(key: str) -> forms.Field:
    if key in _COMMA_SEPARATED:
        placeholders = {
            "allowed_countries": (
                "Tick destinations below, type more, or leave empty for anywhere"
            ),
            "excluded_countries": (
                "Leave empty for none, or tick/type countries to rule out"
            ),
            "acceptable_teaching_languages": "e.g. English, German",
            "research_interests": (
                "Tick sub-fields below, type comma-separated interests, or leave blank for all"
            ),
        }
        return forms.CharField(
            required=key not in _OPTIONAL_VALUES,
            widget=forms.TextInput(
                attrs={"placeholder": placeholders.get(key, ""), "autofocus": "autofocus"}
            ),
        )
    if key in _MONEY_VALUES:
        return MoneyField(required=key not in _OPTIONAL_VALUES)
    if key == "academic_history":
        return AcademicRecordField()
    if key == "language_evidence":
        return LanguageEvidenceField()
    if key in _DATES:
        return forms.DateField(
            widget=forms.DateInput(attrs={"type": "date", "autofocus": "autofocus"})
        )
    if key == "additional_notes":
        return forms.CharField(
            required=False,
            max_length=1000,
            widget=forms.Textarea(
                attrs={
                    "rows": 3,
                    "autofocus": "autofocus",
                    "placeholder": (
                        "Optional: tick any priorities below, or write anything else "
                        "(e.g. 2 years of work experience, specific universities)"
                    ),
                }
            ),
        )
    if key in {"nationality", "country_of_residence"}:
        return CountryChoiceField()
    if key == "target_field":
        return forms.CharField(
            widget=forms.TextInput(
                attrs={
                    "list": "field-datalist",
                    "autofocus": "autofocus",
                    "placeholder": "e.g. Computer Science, Data Science, Chemical Engineering",
                }
            )
        )
    if key in _OPTION_CHOICES:
        return forms.ChoiceField(
            choices=list(_OPTION_CHOICES[key]),
            widget=forms.RadioSelect,
        )
    return forms.CharField()


def answer_adapter(key: str) -> TypeAdapter[Any]:
    """The validator for one consultation answer: its snapshot field's type
    WITH the field's own constraints (the Annotated metadata -- a two-letter
    nationality, not any string). expected_completion is not a field; a date.
    Shared by this form and consultation's stored-draft check."""
    if key == "expected_completion":
        return TypeAdapter(date)
    model_field = StudentProfileSnapshot.model_fields[key]
    annotation = (
        Annotated[model_field.annotation, *model_field.metadata]
        if model_field.metadata
        else model_field.annotation
    )
    return TypeAdapter(annotation)


def _initial_form_value(key: str, value: object) -> object:
    if value is None:
        return None
    if key in _COMMA_SEPARATED and isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return value


def _canonical_value(key: str, value: object) -> object:
    if key in {"nationality", "country_of_residence"} and isinstance(value, str):
        value = normalize_country_code(value)
    elif key in _COMMA_SEPARATED:
        parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
        if key in {"allowed_countries", "excluded_countries"}:
            raw_parts = list(parts)
            parts = [normalize_country_code(part) for part in raw_parts]
            unknown = [
                raw
                for raw, code in zip(raw_parts, parts, strict=True)
                if code not in ISO_3166_ALPHA2_CODES
            ]
            if unknown:
                raise forms.ValidationError(
                    f"We do not recognise {', '.join(unknown)}. Use a country name or "
                    "its two-letter code."
                )
            parts = list(dict.fromkeys(parts))
        value = parts
    elif key in _JSON_VALUES | _MONEY_VALUES and value in (None, ""):
        if key in {"budget_stretch", "self_funding_capacity"}:
            return None  # blank: no stretch / no annual self-funding cap
        value = [] if key not in {"application_budget", "self_funding_capacity"} else value
    if key == "expected_completion":
        # Not a profile field: consultation folds it into the latest academic record.
        return date.fromisoformat(str(value)).isoformat()
    adapter = answer_adapter(key)
    try:
        validated = adapter.validate_python(value)
    except ValidationError as error:
        raise forms.ValidationError(error.errors()[0]["msg"]) from error
    if (
        key in {"budget_stretch", "self_funding_capacity"}
        and validated is not None
        and validated.amount == 0
    ):
        return None  # 0 means no stretch / no annual self-funding cap, as blank does
    return json.loads(adapter.dump_json(validated))


def _checked_list(data: Mapping[str, Any], name: str) -> list[str]:
    getlist = getattr(data, "getlist", None)
    if callable(getlist):
        return [str(v).strip() for v in cast(list[object], getlist(name)) if str(v).strip()]
    raw = data.get(name)
    if isinstance(raw, (list, tuple)):
        return [str(v).strip() for v in raw if str(v).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


_QUICK_TICK_FIELDS: dict[str, str] = {
    "allowed_countries": "country_ticks",
    "excluded_countries": "country_ticks",
    "acceptable_teaching_languages": "language_ticks",
    "research_interests": "interest_ticks",
}


def _merge_quick_inputs(key: str, data: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    merged: dict[str, Any] = {k: data[k] for k in data}
    initial_ticks = {x.casefold() for x in _checked_list(data, "initial_ticks")}
    if tick_field := _QUICK_TICK_FIELDS.get(key):
        norm = normalize_country_code if tick_field == "country_ticks" else lambda x: x
        ticks = _checked_list(data, tick_field)
        unchecked = initial_ticks - {norm(t).casefold() for t in ticks}
        if ticks or unchecked:
            typed = [p.strip() for p in str(merged.get("value") or "").split(",") if p.strip()]
            combined: list[str] = []
            seen: set[str] = set()
            for item in (*ticks, *typed):
                val = norm(item)
                if val and val.casefold() not in seen and val.casefold() not in unchecked:
                    seen.add(val.casefold())
                    combined.append(val)
            merged["value"] = ", ".join(combined)
    elif key in {"intended_intake", "expected_completion"}:
        preset = str(data.get("intake_preset") or "").strip()
        if preset and not str(merged.get("value") or "").strip():
            merged["value"] = preset
    elif key in _MONEY_VALUES:
        raw_val = data.get("value")
        if raw_val not in (None, "") and "value_0" not in data:
            parsed_money = raw_val
            if isinstance(raw_val, str) and raw_val.strip().startswith("{"):
                try:
                    parsed_money = json.loads(raw_val)
                except ValueError:
                    parsed_money = None
            if isinstance(parsed_money, dict):
                merged["value_0"] = str(parsed_money.get("amount", ""))
                merged["value_1"] = str(parsed_money.get("currency", ""))
        if "value_amount" in data or "value_currency" in data:
            if "value_0" not in data:
                merged["value_0"] = str(data.get("value_amount", ""))
            if "value_1" not in data:
                merged["value_1"] = str(data.get("value_currency", ""))
        preset = str(data.get("amount_preset") or "").strip()
        if preset and not str(merged.get("value_0") or "").strip():
            merged["value_0"] = "" if preset.upper() == "NONE" else preset
    elif key == "academic_history":
        raw_val = data.get("value")
        if raw_val not in (None, "") and "value_0" not in data:
            parsed_acad = raw_val
            if isinstance(raw_val, str) and raw_val.strip().startswith("["):
                try:
                    parsed_acad = json.loads(raw_val)
                except ValueError:
                    parsed_acad = None
            if isinstance(parsed_acad, list) and parsed_acad and isinstance(parsed_acad[0], dict):
                rec0 = parsed_acad[0]
                for idx, part in enumerate(_DEGREE_PARTS):
                    merged[f"value_{idx}"] = str(rec0.get(part) or "")
        if any(f"value_{part}" in data for part in _DEGREE_PARTS):
            for idx, part in enumerate(_DEGREE_PARTS):
                if f"value_{idx}" not in data:
                    merged[f"value_{idx}"] = str(data.get(f"value_{part}") or "")
    elif key == "language_evidence":
        raw_val = data.get("value")
        if raw_val not in (None, "") and "value_0" not in data:
            parsed_lang = raw_val
            if isinstance(raw_val, str) and raw_val.strip().startswith("["):
                try:
                    parsed_lang = json.loads(raw_val)
                except ValueError:
                    parsed_lang = None
            if isinstance(parsed_lang, list):
                for row_idx, row in enumerate(parsed_lang[:_LANGUAGE_ROWS]):
                    if isinstance(row, dict):
                        for j, part in enumerate(_LANGUAGE_PARTS):
                            merged[f"value_{row_idx * 4 + j}"] = str(row.get(part) or "")
        if any(
            f"value_{row_idx}_{part}" in data
            for row_idx in range(_LANGUAGE_ROWS)
            for part in _LANGUAGE_PARTS
        ):
            for row_idx in range(_LANGUAGE_ROWS):
                for j, part in enumerate(_LANGUAGE_PARTS):
                    cell_key = f"value_{row_idx * 4 + j}"
                    if cell_key not in data:
                        merged[cell_key] = str(data.get(f"value_{row_idx}_{part}") or "")
        preset = str(data.get("language_quick_preset") or "").strip().upper()
        if preset == "NONE":
            for idx in range(_LANGUAGE_ROWS * 4):
                merged[f"value_{idx}"] = ""
        elif preset in {"IELTS", "TOEFL", "DUOLINGO", "TESTDAF"}:
            defaults = {
                "IELTS": ("English", "IELTS 7.0", "TEST"),
                "TOEFL": ("English", "TOEFL 100", "TEST"),
                "DUOLINGO": ("English", "Duolingo 125", "TEST"),
                "TESTDAF": ("German", "TestDaF TDN 4", "TEST"),
            }[preset]
            if not str(merged.get("value_0") or "").strip():
                merged["value_0"] = defaults[0]
            if not str(merged.get("value_1") or "").strip():
                merged["value_1"] = defaults[1]
            if not str(merged.get("value_2") or "").strip():
                merged["value_2"] = defaults[2]
    elif key == "additional_notes":
        ticks = _checked_list(data, "priority_ticks")
        dur_tick = str(data.get("duration_tick") or "").strip()
        if dur_tick and dur_tick not in ticks:
            ticks.append(dur_tick)
        unchecked = initial_ticks - {t.casefold() for t in ticks}
        if ticks or unchecked:
            base = str(merged.get("value") or "").strip()
            for removed_phrase in unchecked:
                for orig_phrase, _ in (*PRIORITY_TICK_OPTIONS, *DURATION_TICK_OPTIONS):
                    if orig_phrase and orig_phrase.casefold() == removed_phrase:
                        base = " ".join(base.replace(orig_phrase, "").split())
            parts = [base] if base else []
            lower_base = base.casefold()
            for phrase in ticks:
                if phrase.casefold() not in lower_base:
                    parts.append(phrase)
            merged["value"] = " ".join(parts)[:1000]
    return merged


class ConsultationQuestionForm(forms.Form):
    def __init__(
        self,
        *,
        key: str,
        field: forms.Field,
        data: Mapping[str, Any] | None = None,
        initial_value: object = None,
    ) -> None:
        normalized_data = _merge_quick_inputs(key, data)
        initial = (
            {"value": _initial_form_value(key, initial_value)}
            if initial_value is not None and normalized_data is None
            else None
        )
        super().__init__(data=normalized_data, initial=initial)
        self.key = key
        self.fields["value"] = field

    def clean_value(self) -> object:
        return _canonical_value(self.key, self.cleaned_data["value"])


class PlainAuthenticationForm(AuthenticationForm):
    """One sentence for every refusal: a separate one for an inactive account
    would tell whoever is guessing that the username exists."""

    error_messages = {
        "invalid_login": "Wrong username or password.",
        "inactive": "Wrong username or password.",
    }

    def clean_username(self) -> str:
        raw = (self.cleaned_data.get("username") or "").strip()
        if "@" in raw:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            if not User.objects.filter(username=raw).exists():
                match = User.objects.filter(email__iexact=raw).order_by("id").first()
                if match is not None:
                    return str(match.get_username())
        return raw
