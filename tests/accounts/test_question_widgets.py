"""The profile questions a person fills in: structured inputs, not JSON."""

import json

import pytest
from django import forms

from apps.accounts.forms import ConsultationQuestionForm, question_field
from apps.accounts.question_widgets import country_code


def _clean(key, data):
    form = ConsultationQuestionForm(key=key, field=question_field(key), data=data)
    assert form.is_valid(), form.errors
    return form.cleaned_data["value"]


def test_money_is_two_inputs():
    assert _clean("application_budget", {"value_amount": "150", "value_currency": "EUR"}) == {
        "amount": "150",
        "currency": "EUR",
    }


def test_a_posted_json_value_still_works():
    assert (
        _clean("application_budget", {"value": json.dumps({"amount": "9", "currency": "USD"})})[
            "currency"
        ]
        == "USD"
    )


def test_a_degree_is_one_record_in_a_list():
    record = _clean(
        "academic_history",
        {
            "value_institution": "Baku State University",
            "value_country_code": "AZ",
            "value_qualification": "BSc",
            "value_field": "Chemistry",
            "value_grade": "90",
            "value_grading_scale": "100",
            "value_completed_on": "",
        },
    )
    assert record[0]["institution"] == "Baku State University"
    assert record[0]["completed_on"] is None


def test_a_missing_degree_part_is_named():
    form = ConsultationQuestionForm(
        key="academic_history",
        field=question_field("academic_history"),
        data={"value_institution": "BSU", "value_country_code": "AZ"},
    )
    assert not form.is_valid()
    assert form.errors["value"][0].startswith("Degree:")


def test_language_certificates_are_optional_and_blank_rows_are_skipped():
    assert _clean("language_evidence", {}) == []
    rows = _clean(
        "language_evidence",
        {
            "value_0_language": "English",
            "value_0_level": "IELTS 7.0",
            "value_0_evidence_type": "TEST",
            "value_0_available_by": "2026-12-01",
            "value_1_evidence_type": "",
        },
    )
    assert len(rows) == 1 and rows[0]["evidence_type"] == "TEST"


def test_countries_may_be_typed_by_name():
    assert _clean("allowed_countries", {"value": "germany, FR, uk"}) == ["DE", "FR", "GB"]
    form = ConsultationQuestionForm(
        key="allowed_countries", field=question_field("allowed_countries"), data={"value": "Narnia"}
    )
    assert not form.is_valid()
    assert "Narnia" in form.errors["value"][0]


def test_nationality_is_a_country_picker_and_choices_read_as_words():
    field = question_field("nationality")
    assert isinstance(field, forms.ChoiceField)
    assert ("AZ", "Azerbaijan") in field.choices
    labels = dict(question_field("funding_dependency").choices)
    assert labels["MANDATORY"] == "No, I can only go with a scholarship"


@pytest.mark.parametrize(("typed", "code"), [("de", "DE"), ("Germany", "DE"), ("USA", "US")])
def test_country_code(typed, code):
    assert country_code(typed) == code


def test_the_widget_renders_labelled_inputs():
    html = str(question_field("application_budget").widget.render("value", None))
    assert '<label for="id_value_amount">' in html
    assert '<select id="id_value_currency" name="value_currency">' in html


def test_global_country_to_currency_and_money_widget_full_iso4217():
    from uuid import uuid4

    from apps.accounts.consultation import ConsultationDraft, default_currency_for_draft
    from apps.reference_data import COUNTRY_TO_CURRENCY, ISO_4217_CODES

    expected = {
        "DE": "EUR",
        "US": "USD",
        "GB": "GBP",
        "IN": "INR",
        "NG": "NGN",
        "BR": "BRL",
        "JP": "JPY",
        "PK": "PKR",
        "CN": "CNY",
        "CA": "CAD",
        "AU": "AUD",
        "CH": "CHF",
        "PL": "PLN",
        "SE": "SEK",
        "NO": "NOK",
        "AZ": "AZN",
        "KZ": "KZT",
        "UZ": "UZS",
        "KG": "KGS",
        "TJ": "TJS",
        "GE": "GEL",
        "TR": "TRY",
        "BG": "EUR",
    }
    for country, curr in expected.items():
        assert COUNTRY_TO_CURRENCY[country] == curr
        draft = ConsultationDraft(uuid4(), uuid4(), {"country_of_residence": country})
        assert default_currency_for_draft(draft) == curr

    html = str(
        question_field("application_budget").widget.render(
            "value", {"amount": 1200, "currency": "CAD"}
        )
    )
    assert '<option value="CAD" selected>' in html
    for code in ("CHF", "PLN", "SEK", "NOK", "JPY", "BRL", "NGN", "AUD", "GEL"):
        assert code in ISO_4217_CODES
        assert f'<option value="{code}"' in html


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("İtalya", "IT"),
        ("İspaniya", "ES"),
        ("Türkiye", "TR"),
        ("Turkiye", "TR"),
        ("Azərbaycan", "AZ"),
        ("Azərbaycan Respublikası", "AZ"),
        ("Allemagne", "DE"),
        ("Alemania", "DE"),
        ("Almanya", "DE"),
        ("Almaniya", "DE"),
        ("Германия", "DE"),
        ("Österreich", "AT"),
        ("Osterreich", "AT"),
        ("Schweiz", "CH"),
        ("Suisse", "CH"),
        ("Svizzera", "CH"),
        ("Polska", "PL"),
        ("Nederland", "NL"),
        ("España", "ES"),
        ("Espana", "ES"),
    ],
)
def test_multilingual_and_turkish_dotted_i_country_resolution(typed, expected):
    from apps.accounts.forms import normalize_country_code

    assert normalize_country_code(typed) == expected
    assert country_code(typed) == expected


def test_language_evidence_supports_more_than_three_languages():
    four_langs = [
        {
            "language": "English",
            "level": "C1",
            "evidence_type": "TEST",
            "available_by": "2026-03-01",
        },
        {
            "language": "German",
            "level": "B2",
            "evidence_type": "TEST",
            "available_by": "2026-04-01",
        },
        {
            "language": "French",
            "level": "B2",
            "evidence_type": "ATTESTED",
            "available_by": "2026-05-01",
        },
        {
            "language": "Turkish",
            "level": "C1",
            "evidence_type": "DEGREE",
            "available_by": "2026-06-01",
        },
    ]
    cleaned_json = _clean("language_evidence", {"value": json.dumps(four_langs)})
    assert len(cleaned_json) == 4
    assert [row["language"] for row in cleaned_json] == [
        "English",
        "German",
        "French",
        "Turkish",
    ]

    flat_post = {}
    for idx, row in enumerate(four_langs):
        for part, val in row.items():
            flat_post[f"value_{idx}_{part}"] = val
    cleaned_parts = _clean("language_evidence", flat_post)
    assert len(cleaned_parts) == 4
    assert cleaned_parts[3]["language"] == "Turkish"

    rendered_form = ConsultationQuestionForm(
        key="language_evidence",
        field=question_field("language_evidence"),
        initial_value=four_langs,
    )
    html = str(rendered_form["value"])
    assert "Turkish" in html

