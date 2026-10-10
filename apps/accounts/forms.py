import json
from datetime import date
from typing import Annotated, Any

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from pydantic import TypeAdapter, ValidationError

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


def question_field(key: str) -> forms.Field:
    if key in _COMMA_SEPARATED:
        return forms.CharField(required=key not in _OPTIONAL_VALUES)
    if key in _JSON_VALUES:
        return forms.JSONField(required=key not in _OPTIONAL_VALUES)
    if key in _DATES:
        return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    if key == "additional_notes":
        return forms.CharField(required=False, max_length=1000)
    if key in {"nationality", "country_of_residence"}:
        return forms.CharField(required=True, min_length=2, max_length=2)
    if key in _OPTION_VALUES:
        return forms.ChoiceField(choices=[(value, value) for value in _OPTION_VALUES[key]])
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
    elif key in _JSON_VALUES and value in (None, ""):
        value = [] if key not in {"application_budget", "self_funding_capacity"} else value
    if key == "expected_completion":
        # Not a profile field: consultation folds it into the latest academic record.
        return date.fromisoformat(str(value)).isoformat()
    adapter = answer_adapter(key)
    try:
        validated = adapter.validate_python(value)
    except ValidationError as error:
        raise forms.ValidationError(error.errors()[0]["msg"]) from error
    return json.loads(adapter.dump_json(validated))


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
