import json
from datetime import date
from typing import Annotated, Any

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from pydantic import TypeAdapter, ValidationError

from .question_widgets import (
    CHOICE_LABELS,
    academic_history_widget,
    country_choices,
    country_code,
    language_evidence_widget,
    money_widget,
)
from .schemas import StudentProfileSnapshot

_COMMA_SEPARATED = {
    "acceptable_teaching_languages",
    "allowed_countries",
    "excluded_countries",
}
_JSON_VALUES = {
    "academic_history",
    "language_evidence",
    "application_budget",
    "self_funding_capacity",
}
_OPTION_VALUES: dict[str, tuple[str, ...]] = {
    "career_intent": ("WORK_ABROAD", "RETURN_HOME", "PHD", "UNDECIDED"),
    "funding_dependency": ("MANDATORY", "IMPORTANT", "OPTIONAL"),
}
_OPTIONAL_VALUES = {
    "language_evidence",
    "allowed_countries",
    "excluded_countries",
    "additional_notes",
}
_DATES = {"intended_intake", "date_of_birth", "expected_completion"}


_WIDGETS = {
    "application_budget": money_widget,
    "self_funding_capacity": money_widget,
    "language_evidence": language_evidence_widget,
    "academic_history": academic_history_widget,
}
_COUNTRY_LISTS = {"allowed_countries", "excluded_countries"}
_HINTS = {
    "allowed_countries": (
        "Names or codes, separated by commas. For example: Germany, France, Italy."
    ),
    "excluded_countries": "Names or codes, separated by commas. Leave empty if none.",
    "acceptable_teaching_languages": "Separated by commas. For example: English, German.",
    "target_field": "For example: Data Science, or Chemistry with a focus on materials.",
}
#: The parts of a structured answer, as a person names them in an error.
_PART_LABELS = {
    "amount": "Amount",
    "currency": "Currency",
    "language": "Language",
    "level": "Score or level",
    "evidence_type": "What it is",
    "available_by": "Date",
    "institution": "University",
    "country_code": "Country",
    "qualification": "Degree",
    "field": "Subject",
    "grade": "Grade",
    "grading_scale": "Out of",
    "completed_on": "Graduation date",
}


def question_field(key: str) -> forms.Field:
    field = _question_field(key)
    if key in _HINTS:
        field.help_text = _HINTS[key]
    return field


def _question_field(key: str) -> forms.Field:
    if key in _COMMA_SEPARATED:
        return forms.CharField(required=key not in _OPTIONAL_VALUES)
    if key in _JSON_VALUES:
        return forms.JSONField(
            required=key not in _OPTIONAL_VALUES,
            widget=_WIDGETS[key](),
            error_messages={"required": "Fill in this answer to continue."},
        )
    if key in _DATES:
        return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    if key == "additional_notes":
        return forms.CharField(required=False, max_length=1000)
    if key in {"nationality", "country_of_residence"}:
        return forms.ChoiceField(
            choices=country_choices(), error_messages={"required": "Choose a country."}
        )
    if key in _OPTION_VALUES:
        labels = CHOICE_LABELS.get(key, {})
        return forms.ChoiceField(
            choices=[(value, labels.get(value, value)) for value in _OPTION_VALUES[key]],
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


def _canonical_value(key: str, value: object) -> object:
    if key in _COMMA_SEPARATED:
        value = [part.strip() for part in str(value or "").split(",") if part.strip()]
        if key in _COUNTRY_LISTS:
            unknown = [part for part in value if country_code(part) is None]
            if unknown:
                raise forms.ValidationError(
                    f"We do not recognise {', '.join(unknown)}. Use a country name or "
                    "its two-letter code."
                )
            value = list(dict.fromkeys(country_code(part) for part in value))
    elif key in _JSON_VALUES and value in (None, ""):
        value = [] if key not in {"application_budget", "self_funding_capacity"} else value
    if key == "expected_completion":
        # Not a profile field: consultation folds it into the latest academic record.
        return date.fromisoformat(str(value)).isoformat()
    adapter = answer_adapter(key)
    try:
        validated = adapter.validate_python(value)
    except ValidationError as error:
        raise forms.ValidationError(_readable(error)) from error
    return json.loads(adapter.dump_json(validated))


def _readable(error: ValidationError) -> str:
    """The first problem, named the way the form names it ("University: ...")."""
    first = error.errors()[0]
    names = [str(part) for part in first.get("loc", ()) if isinstance(part, str)]
    label = _PART_LABELS.get(names[-1]) if names else None
    message = str(first["msg"])
    if first.get("type") == "missing":
        message = "fill this in"
    return f"{label}: {message}" if label else message


class ConsultationQuestionForm(forms.Form):
    def __init__(self, *, key: str, field: forms.Field, data: dict[str, Any] | None = None) -> None:
        super().__init__(data=data)
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
