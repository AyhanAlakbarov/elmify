import pytest

pytestmark = pytest.mark.django_db


def test_a_student_with_no_report_sees_how_to_get_one(
    client, domain_a, user_a, membership_a
) -> None:
    client.force_login(user_a)
    response = client.get("/student/reports/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    assert "No report yet" in response.content.decode()
