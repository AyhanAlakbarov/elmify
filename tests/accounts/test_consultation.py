from copy import deepcopy

import pytest
from django.db import IntegrityError
from pydantic import ValidationError

from apps.accounts.consultation import correction_key
from apps.accounts.models import StudentProfileVersion
from apps.funding.models import RecommendationRun
from apps.tenancy.context import tenant_scope
from tests.acceptance.helpers import complete_consultation, confirm_consultation


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_first_consultation_answer_is_stored_only_in_the_bound_session(
    client, domain_a, membership_a, user_a
) -> None:
    client.force_login(user_a)

    response = client.post(
        "/student/profile/",
        {"key": "nationality", "value": "AZ"},
        HTTP_HOST=domain_a.host,
    )

    assert response.status_code == 200
    assert client.session[f"consultation:{domain_a.agency_id}:{membership_a.id}"] == {
        "tenant_id": str(domain_a.agency_id),
        "membership_id": str(membership_a.id),
        "answers": {"nationality": "AZ"},
    }
    assert b'id="consultation"' in response.content


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
# "AZE": the field's own constraint (two letters) holds on a stored draft too
# (Task 18 minor) -- the Annotated metadata, not just the bare type.
@pytest.mark.parametrize("nationality", [" AZ ", "AZE"])
def test_noncanonical_session_draft_is_discarded(
    client, domain_a, membership_a, user_a, nationality
) -> None:
    client.force_login(user_a)
    key = f"consultation:{domain_a.agency_id}:{membership_a.id}"
    session = client.session
    session[key] = {
        "tenant_id": str(domain_a.agency_id),
        "membership_id": str(membership_a.id),
        "answers": {"nationality": nationality},
    }
    session.save()

    response = client.get("/student/profile/", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert b"nationality" in response.content
    assert key not in client.session


def test_profile_duplicate_error_identifies_its_correction_question() -> None:
    from apps.accounts.schemas import StudentProfileSnapshot

    payload = {
        "schema_version": 3,
        "academic_history": [
            {
                "institution": "Baku State University",
                "country_code": "AZ",
                "qualification": "BSc",
                "field": "Chemistry",
                "grade": "90",
                "grading_scale": "100",
                "completed_on": "2026-06-30",
            }
        ],
        "target_field": "Chemistry",
        "nationality": "AZ",
        "country_of_residence": "AZ",
        "intended_intake": "2027-09-01",
        "acceptable_teaching_languages": ["English", " english "],
        "language_evidence": [],
        "experience": [],
        "research_interests": ["Catalysis"],
        "career_intent": "PHD",
        "date_of_birth": "2000-01-01",
        "application_budget": {"amount": "150.00", "currency": "EUR"},
        "funding_dependency": "MANDATORY",
        "strategy": "FUNDING_FIRST",
        "duration_preference": "ONE_YEAR",
        "duration_flexibility": "NON_NEGOTIABLE",
        "longer_program_justifications": [],
        "allowed_countries": ["DE"],
        "excluded_countries": [],
        "mobility_priorities": ["Public transport"],
        "non_negotiables": [],
        "negotiable_preferences": [],
        "weights": {"ACADEMIC_FIT": "1"},
    }

    with pytest.raises(ValidationError) as raised:
        StudentProfileSnapshot.model_validate(deepcopy(payload))

    error = raised.value.errors()[0]
    assert error["type"] == "profile_duplicate_language"
    assert error["ctx"] == {"target": "acceptable_teaching_languages"}
    assert correction_key(raised.value) == "acceptable_teaching_languages"

    payload["acceptable_teaching_languages"] = ["English"]
    payload["target_field"] = "x" * 201
    with pytest.raises(ValidationError) as field_raised:
        StudentProfileSnapshot.model_validate(payload)
    assert correction_key(field_raised.value) == "target_field"


@pytest.mark.django_db(transaction=True)
def test_confirmed_consultation_creates_one_profile_and_run(
    client, domain_a, membership_a, user_a, paid_cycle_a
) -> None:
    client.force_login(user_a)
    complete_consultation(client, host=domain_a.host)

    response = confirm_consultation(client, host=domain_a.host)

    assert response.status_code == 302
    with tenant_scope(domain_a.agency_id):
        profile = StudentProfileVersion.objects.get()
        assert profile.schema_version == 3
        assert RecommendationRun.objects.get().profile_version_id == profile.id


@pytest.mark.django_db(transaction=True)
def test_confirm_without_a_paid_cycle_starts_no_search(
    client, domain_a, membership_a, user_a
) -> None:
    client.force_login(user_a)
    complete_consultation(client, host=domain_a.host)

    response = confirm_consultation(client, host=domain_a.host)

    assert response.status_code == 402
    with tenant_scope(domain_a.agency_id):
        assert not RecommendationRun.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_unpaid_confirm_with_a_schema_invalid_draft_is_402_not_500(
    client, domain_a, membership_a, user_a
) -> None:
    client.force_login(user_a)
    complete_consultation(client, host=domain_a.host)
    from apps.accounts.consultation import read_draft, write_draft

    session = client.session
    draft = read_draft(session, tenant_id=domain_a.agency_id, membership_id=membership_a.id)
    write_draft(session, draft.with_answer("target_field", "x" * 201))
    session.save()

    response = confirm_consultation(client, host=domain_a.host)

    assert response.status_code == 400  # re-asks the invalid question; never a 500
    with tenant_scope(domain_a.agency_id):
        assert not RecommendationRun.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_htmx_confirmation_redirects_after_creating_the_run(
    client, domain_a, membership_a, monkeypatch, user_a, paid_cycle_a
) -> None:
    monkeypatch.setattr("apps.accounts.views.dispatch_recommendation_run", lambda **_kwargs: False)
    client.force_login(user_a)
    complete_consultation(client, host=domain_a.host)

    response = client.post(
        "/student/profile/",
        {"action": "confirm"},
        HTTP_HOST=domain_a.host,
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == "/student/recommendation/"


@pytest.mark.django_db(transaction=True)
def test_failed_run_creation_keeps_the_draft_without_a_profile(
    client, domain_a, membership_a, monkeypatch, user_a, paid_cycle_a
) -> None:
    def fail_run_creation(**_kwargs: object) -> None:
        raise IntegrityError("run creation failed")

    monkeypatch.setattr(
        "apps.accounts.consultation.RecommendationRun.objects.create",
        fail_run_creation,
    )
    client.force_login(user_a)
    complete_consultation(client, host=domain_a.host)

    response = confirm_consultation(client, host=domain_a.host)

    assert response.status_code == 400
    with tenant_scope(domain_a.agency_id):
        assert StudentProfileVersion.objects.count() == 0
        assert RecommendationRun.objects.count() == 0
    assert any(key.startswith("consultation:") for key in client.session.keys())


def test_the_transcript_questions_come_after_every_other_question_but_the_notes():
    from apps.accounts.consultation import QUESTIONS

    keys = [question.key for question in QUESTIONS]
    assert keys[-3:] == ["academic_history", "expected_completion", "additional_notes"]
    assert keys[:3] == ["nationality", "country_of_residence", "date_of_birth"]


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_the_review_step_reads_structured_answers_as_text(
    client, domain_a, membership_a, user_a
) -> None:
    """Task 18 minor: lists and records were printed as Python reprs."""
    client.force_login(user_a)
    body = complete_consultation(client, host=domain_a.host).content.decode()
    assert "Check your answers" in body
    assert "DE; FR" in body
    assert "amount: 150.00, currency: EUR" in body
    assert "institution: Baku State University" in body
    assert "[" not in body.split("Check your answers", 1)[1].split("</dl>", 1)[0]
    assert "{" not in body.split("Check your answers", 1)[1].split("</dl>", 1)[0]


@pytest.mark.django_db
def test_a_question_sent_back_by_the_review_says_why(client, domain_a, user_a, membership_a):
    """Every answer passes alone, but together they do not (a certificate in a
    language the student did not list). The review sends the student back to
    that question; it must say why, or they answer the same thing and loop."""
    import json

    client.force_login(user_a)
    answers = (
        ("nationality", "AZ"),
        ("country_of_residence", "AZ"),
        ("date_of_birth", "2002-05-01"),
        ("target_field", "Chemistry"),
        ("allowed_countries", "DE"),
        ("excluded_countries", ""),
        ("intended_intake", "2027-09-01"),
        ("funding_dependency", "MANDATORY"),
        ("application_budget", {"amount": "150.00", "currency": "EUR"}),
        ("career_intent", "PHD"),
        ("acceptable_teaching_languages", "English"),
        (
            "language_evidence",
            [
                {
                    "language": "German",
                    "level": "B2",
                    "evidence_type": "TEST",
                    "available_by": "2026-12-01",
                }
            ],
        ),
        (
            "academic_history",
            [
                {
                    "institution": "BSU",
                    "country_code": "AZ",
                    "qualification": "BSc",
                    "field": "Chemistry",
                    "grade": "90",
                    "grading_scale": "100",
                    "completed_on": "2026-06-30",
                }
            ],
        ),
        ("additional_notes", ""),
    )
    for key, value in answers:
        response = client.post(
            "/student/profile/",
            {"key": key, "value": json.dumps(value) if isinstance(value, (dict, list)) else value},
            HTTP_HOST=domain_a.host,
        )
    assert response.status_code == 400
    body = response.content.decode()
    assert "did not list as one you could study in" in body
