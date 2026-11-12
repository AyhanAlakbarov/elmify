"""The onboarding answers a student types into plain fields, never a JSON box
(onboarding friction design 2026-10-15, variant 1). Each field compresses to the
exact JSON the profile schema already stores."""

from apps.accounts.forms import (
    AcademicRecordField,
    ConsultationQuestionForm,
    LanguageEvidenceField,
    MoneyField,
    _canonical_value,
    question_field,
)


def _post(key, **values):
    form = ConsultationQuestionForm(key=key, field=question_field(key), data=values)
    assert form.is_valid(), form.errors
    return form.cleaned_data["value"]


def test_budget_questions_are_money_fields_not_json_boxes():
    for key in ("application_budget", "self_funding_capacity", "budget_stretch"):
        assert isinstance(question_field(key), MoneyField)


def test_a_money_answer_compresses_to_the_stored_shape():
    # The profile's own canonical form, exactly what the JSON box stored.
    assert _post("application_budget", value_0="300", value_1="EUR") == _canonical_value(
        "application_budget", {"amount": "300", "currency": "EUR"}
    )


def test_a_blank_stretch_is_none_and_zero_is_none():
    assert _post("budget_stretch", value_0="", value_1="EUR") is None
    assert _post("budget_stretch", value_0="0", value_1="EUR") is None


def test_a_required_budget_refuses_a_blank_amount():
    form = ConsultationQuestionForm(
        key="application_budget", field=question_field("application_budget"),
        data={"value_0": "", "value_1": "EUR"},
    )
    assert not form.is_valid()


def test_an_unknown_currency_is_refused():
    form = ConsultationQuestionForm(
        key="application_budget", field=question_field("application_budget"),
        data={"value_0": "10", "value_1": "ZZZ"},
    )
    assert not form.is_valid()


def test_a_stored_money_answer_shows_back_in_both_inputs():
    field = question_field("application_budget")
    assert field.widget.decompress({"amount": "300.00", "currency": "EUR"}) == ["300.00", "EUR"]


_DEGREE = {
    "value_0": "Baku State University", "value_1": "az", "value_2": "BSc",
    "value_3": "Chemistry", "value_4": "85", "value_5": "0-100",
    "value_6": "2025-06-30", "value_7": "",
}


def test_the_degree_is_a_short_form_and_compresses_to_one_record():
    assert isinstance(question_field("academic_history"), AcademicRecordField)
    assert _post("academic_history", **_DEGREE) == [{
        "institution": "Baku State University", "country_code": "AZ", "qualification": "BSc",
        "field": "Chemistry", "grade": "85", "grading_scale": "0-100",
        "completed_on": "2025-06-30", "expected_completion": None, "courses": [],
    }]


def test_a_degree_missing_its_university_is_refused():
    form = ConsultationQuestionForm(
        key="academic_history", field=question_field("academic_history"),
        data={**_DEGREE, "value_0": ""},
    )
    assert not form.is_valid()


def test_a_stored_degree_shows_back_in_its_inputs():
    field = question_field("academic_history")
    widget = field.widget
    stored = [{"institution": "BSU", "country_code": "AZ", "qualification": "BSc",
               "field": "Chemistry", "grade": "85", "grading_scale": "0-100",
               "completed_on": "2025-06-30", "expected_completion": None, "courses": []}]
    assert widget.decompress(stored)[:3] == ["BSU", "AZ", "BSc"]
    form = ConsultationQuestionForm(key="academic_history", field=field, initial_value=stored)
    rendered = str(form["value"])
    assert 'value="BSU"' in rendered
    assert "&#x27;institution&#x27;" not in rendered
    assert "Graduation date (if completed)" in rendered
    assert "Expected graduation date" in rendered


def test_language_evidence_skips_blank_rows():
    assert isinstance(question_field("language_evidence"), LanguageEvidenceField)
    blank = {f"value_{i}": "" for i in range(4, 12)}
    value = _post(
        "language_evidence",
        value_0="English", value_1="C1", value_2="TEST", value_3="2026-01-15", **blank,
    )
    assert value == [{"language": "English", "level": "C1", "evidence_type": "TEST",
                      "available_by": "2026-01-15"}]
    assert _post("language_evidence", **{f"value_{i}": "" for i in range(12)}) == []


def test_a_half_filled_language_row_is_refused():
    form = ConsultationQuestionForm(
        key="language_evidence", field=question_field("language_evidence"),
        data={"value_0": "English", **{f"value_{i}": "" for i in range(1, 12)}},
    )
    assert not form.is_valid()


# --- Final review: refusals say what to do, in plain words ---


def _errors(key, **values):
    form = ConsultationQuestionForm(key=key, field=question_field(key), data=values)
    assert not form.is_valid()
    return " ".join(form.errors["value"])


def test_a_blank_required_amount_asks_for_an_amount():
    assert _errors("application_budget", value_0="", value_1="EUR") == "Enter an amount."


def test_a_half_filled_language_row_says_what_is_missing():
    message = _errors(
        "language_evidence", value_0="English", **{f"value_{i}": "" for i in range(1, 12)}
    )
    assert message == (
        "For each language, fill in the level, how you can prove it and the date you will "
        "have that proof, or leave the whole row empty."
    )


def test_a_language_row_without_its_date_says_the_date_is_needed():
    message = _errors(
        "language_evidence", value_0="English", value_1="C1", value_2="TEST",
        **{f"value_{i}": "" for i in range(3, 12)},
    )
    assert "date" in message and "Input should be" not in message


def test_degree_and_attested_language_evidence_default_date_and_level():
    from datetime import date

    blank = {f"value_{i}": "" for i in range(4, 12)}
    value = _post(
        "language_evidence",
        value_0="English",
        value_1="",
        value_2="DEGREE",
        value_3="",
        **blank,
    )
    assert value == [
        {
            "language": "English",
            "level": "C1",
            "evidence_type": "DEGREE",
            "available_by": date.today().isoformat(),
        }
    ]


def test_country_names_and_common_aliases_resolve_to_iso_alpha2():
    assert _post("nationality", value="Azerbaijan") == "AZ"
    assert _post("country_of_residence", value="UK") == "GB"
    assert _post("allowed_countries", value="Germany, UK, Netherlands") == ["DE", "GB", "NL"]
    assert _post("academic_history", **{**_DEGREE, "value_1": "Turkey"})[0]["country_code"] == "TR"


def test_quick_ticks_and_presets_reduce_friction_across_questions():
    from django import forms

    # 1. Single-select choices render as RadioSelect (1-click visible options, not hidden dropdowns)
    for key in ("funding_dependency", "career_intent"):
        assert isinstance(question_field(key).widget, forms.RadioSelect)

    # 2. Country checkboxes merge with typed countries and normalize to ISO alpha-2
    assert _post(
        "allowed_countries",
        country_ticks=["DE", "NL"],
        value="United Kingdom",
    ) == ["DE", "NL", "GB"]

    # 3. Teaching-language checkboxes merge without duplicates
    assert _post(
        "acceptable_teaching_languages",
        language_ticks=["English", "German"],
        value="English",
    ) == ["English", "German"]

    # 4. Research-interest checkboxes merge with typed interests
    assert _post(
        "research_interests",
        interest_ticks=["Machine Learning", "Computer Vision"],
        value="Robotics",
    ) == ["Machine Learning", "Computer Vision", "Robotics"]

    # 5. Intake date preset fills intended_intake in 1 click without calendar typing
    assert _post("intended_intake", intake_preset="2027-09-01", value="") == "2027-09-01"

    # 6. Money presets fill amount or clear self_funding_capacity ("NONE" -> unlimited)
    assert _post(
        "self_funding_capacity", amount_preset="NONE", value_0="", value_1="EUR"
    ) is None
    assert _post(
        "application_budget", amount_preset="250", value_0="", value_1="EUR"
    ) == _canonical_value("application_budget", {"amount": "250", "currency": "EUR"})

    # 7. Priority tick checkboxes + duration radio on additional_notes combine with textarea
    notes = _post(
        "additional_notes",
        priority_ticks=[
            "Only top universities and prestigious scholarships.",
        ],
        duration_tick="Strictly 1-year master's only.",
        value="I have 2 years of work experience.",
    )
    assert "I have 2 years of work experience." in notes
    assert "Only top universities and prestigious scholarships." in notes
    assert "Strictly 1-year master's only." in notes

    # 8. OB13: Unchecking a pre-seeded tick removes it from the submitted answer
    assert _post(
        "allowed_countries",
        initial_ticks=["DE", "NL"],
        country_ticks=["DE"],
        value="DE, NL",
    ) == ["DE"]
    assert _post(
        "acceptable_teaching_languages",
        initial_ticks=["English"],
        language_ticks=["German"],
        value="English",
    ) == ["German"]

    # 9. UX1: Language evidence 1-click preset ("NONE" clears rows; no false "DEGREE_EN" preset)
    assert _post(
        "language_evidence",
        language_quick_preset="NONE",
        value_0="English",
        value_1="C1",
        value_2="DEGREE",
        value_3="2026-06-01",
    ) == []

    # 10. OB12 & UX3: dashboard.answer renders None/"" as "none", and single inputs autofocus
    from apps.dashboard.templatetags.dashboard import answer

    assert answer(None) == "none"
    assert answer("") == "none"
    assert question_field("target_field").widget.attrs.get("autofocus") == "autofocus"

    # 11. P3-B4 & P3-UX2: career_intent="WORK_ABROAD" + post-study work notes sets
    # mobility_priorities, and 1-click language test presets populate language/score/type
    from apps.accounts.consultation import _priorities_from_notes

    payload_psw: dict[str, object] = {"career_intent": "WORK_ABROAD"}
    _priorities_from_notes(
        "I want a strong post-study work visa and job market.", payload_psw
    )
    assert payload_psw["mobility_priorities"] == ["POST_STUDY_WORK"]

    assert _post(
        "language_evidence",
        language_quick_preset="IELTS",
        value_0="",
        value_1="",
        value_2="",
        value_3="2026-06-01",
    ) == [
        {
            "language": "English",
            "level": "IELTS 7.0",
            "evidence_type": "TEST",
            "available_by": "2026-06-01",
        }
    ]

    # 12. Post-admission government scholarship tick & note extraction
    gov_notes = _post(
        "additional_notes",
        priority_ticks=[
            "Applying for a post-admission government scholarship (admission required first).",
        ],
        value="",
    )
    payload_dp: dict[str, object] = {}
    _priorities_from_notes(gov_notes, payload_dp)
    assert payload_dp["negotiable_preferences"] == [
        {"kind": "OTHER", "value": "GOV_SCHOLARSHIP_AFTER_ADMISSION"}
    ]
    assert payload_dp["strategy"] == "BALANCED"

    # 13. Date presets roll forward so past dates in the current year are never offered
    from datetime import date as dt_date
    from uuid import uuid4

    from apps.accounts.consultation import ConsultationDraft, default_currency_for_draft
    from apps.accounts.forms import date_presets_for_question

    oct_today = dt_date(2026, 10, 30)
    intake_presets = date_presets_for_question("intended_intake", today=oct_today)
    assert all(dt_date.fromisoformat(iso) >= oct_today for iso, _ in intake_presets)
    assert intake_presets[0] == ("2027-02-01", "Spring 2027")

    comp_presets = date_presets_for_question("expected_completion", today=oct_today)
    assert all(dt_date.fromisoformat(iso) >= oct_today for iso, _ in comp_presets)
    assert comp_presets[0] == ("2027-01-31", "January 2027")

    # 14. Eurozone and expanded country currency hints resolve country_of_residence first
    de_draft = ConsultationDraft(
        uuid4(), uuid4(), {"country_of_residence": "DE", "nationality": "US"}
    )
    assert default_currency_for_draft(de_draft) == "EUR"




