"""My applications by country, and one option's page."""

import pytest

from apps.funding.models import RecommendationCandidate
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import reads_no_catalogue
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db
pack = dashboard_conftest.pack
LIST = "/student/applications/"


def test_the_list_groups_options_under_their_country_with_its_flag(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
        add_card(agency_a, membership_a, award)
    client.force_login(user_a)
    body = client.get(LIST, HTTP_HOST=domain_a.host).content.decode()
    assert "Germany" in body
    assert "elmify/flags/de" in body
    assert "M.Sc. Informatics" in body and "DAAD Study Scholarship" in body
    assert "Scholarship</p>" in body and "Programme</p>" in body


def test_by_stage_still_shows_the_board(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    body = client.get(LIST + "?view=stage", HTTP_HOST=domain_a.host).content.decode()
    assert 'class="board"' in body


def test_a_missing_motivation_letter_links_to_its_letter(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme,
            kit_requirements=["Upload a motivation letter of one page."],
        )
    client.force_login(user_a)
    body = client.get(LIST, HTTP_HOST=domain_a.host).content.decode()
    assert "Still missing" in body
    assert f'href="/student/writing/letters/{application.id}/">Motivation letter' in body


def test_the_option_page_shows_its_facts_and_why_the_student_fits(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    _programme, award = pack
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            details={
                "holder": "DAAD", "timing": "PRE_ARRIVAL", "cycle": "UNSTATED",
                "covers": [{"kind": "STIPEND", "amount": "934 EUR", "period": "MONTHLY"}],
                "bonds": [{"months": 24, "quote": "Return home for two years."}],
            },
            fit={
                "conditions": [
                    {
                        "key": "GRADE", "outcome": "SATISFIED",
                        "quote": "A GPA of at least 3.0.",
                        "reason": "GRADE: 3.8 on 4.0 GPA against 3.0",
                    },
                    {
                        "key": "LANGUAGE", "outcome": "UNDECIDABLE", "quote": "IELTS 6.5.",
                        "reason": "LANGUAGE: the profile does not carry language evidence",
                    },
                ],
                "budget": {"amount": "10000", "currency": "EUR"},
            },
        )
        application = add_card(agency_a, membership_a, award)
    client.force_login(user_a)
    with reads_no_catalogue():
        response = client.get(f"{LIST}{application.id}/", HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert response.status_code == 200
    assert "Your grade of 3.8 on a 4.0 GPA scale meets the 3 required" in body
    assert "We can’t tell yet" in body
    assert "934 EUR a month" in body
    assert "Return home for two years." in body
    assert "10000 EUR a year" in body
    assert "Before you arrive" in body
    assert "UNSTATED" not in body


def test_an_option_without_copies_says_its_details_are_coming(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    body = client.get(f"{LIST}{application.id}/", HTTP_HOST=domain_a.host).content.decode()
    assert "Detailed requirements appear the next time your list is refreshed." in body


def test_another_students_option_is_not_found(
    client, agency_a, domain_a, user_a, user_b, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        application = add_card(agency_a, other, programme)
    client.force_login(user_a)
    response = client.get(f"{LIST}{application.id}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_a_missing_recommendation_letter_links_to_its_references_tab(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme,
            kit_requirements=["Upload two recommendation letters."],
        )
    client.force_login(user_a)
    body = client.get(LIST, HTTP_HOST=domain_a.host).content.decode()
    expected_link = (
        f'href="/student/writing/letters/{application.id}/?doc=references">'
        "Recommendation letters"
    )
    assert expected_link in body


def test_plain_reason_renders_failed_conditions_accurately() -> None:
    from apps.dashboard.mylist import plain_reason

    assert (
        plain_reason("GRADE", "GRADE: 75 on 100 against 80", outcome="FAILED")
        == "Your grade of 75 on a 100 scale is below the 80 required"
    )
    assert (
        plain_reason("LANGUAGE", "LANGUAGE: English at B1 against B2", outcome="FAILED")
        == "Your English at B1 is below the B2 level required"
    )
    assert (
        plain_reason("FIELD", "FIELD: mathematics against computer science", outcome="FAILED")
        == "A degree in computer science is required (yours is in mathematics)"
    )
    assert (
        plain_reason(
            "WORK_EXPERIENCE", "WORK_EXPERIENCE: 6 months against 12.0", outcome="FAILED"
        )
        == "Your 6 months of work experience is below the 12 months required"
    )
    assert (
        plain_reason("AGE", "AGE: 32 against LTE 30.0", outcome="FAILED")
        == "Your age (32) exceeds the maximum age of 30"
    )
    assert (
        plain_reason("CITIZENSHIP", "nationality AZ against DE", outcome="FAILED")
        == "Open to DE citizens (your citizenship is Azerbaijan)"
    )


def test_programme_in_university_preserves_canonical_degree_prefixes() -> None:
    from apps.dashboard.templatetags.dashboard import programme_in_university

    assert (
        programme_in_university("MA in International Relations", "Freie Universität Berlin")
        == "MA in International Relations in Freie Universität Berlin"
    )
    assert (
        programme_in_university("LL.M. in European Law", "Leiden University")
        == "LLM in European Law in Leiden University"
    )
    assert (
        programme_in_university("BSc in Computer Science", "TU Munich")
        == "BSc in Computer Science in TU Munich"
    )
    assert (
        programme_in_university("Master of Engineering in Robotics", "ETH Zurich")
        == "MEng in Robotics in ETH Zurich"
    )
    assert (
        programme_in_university("Data Science", "TU Munich")
        == "MSc in Data Science in TU Munich"
    )
