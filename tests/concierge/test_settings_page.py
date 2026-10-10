import pytest

pytestmark = pytest.mark.django_db


def test_settings_links_every_settings_page(client, domain_a, user_a, membership_a) -> None:
    client.force_login(user_a)
    body = client.get("/student/settings/", HTTP_HOST=domain_a.host).content.decode()
    for href in (
        "/student/profile/", "/student/settings/mailbox/", "/student/settings/extension/",
        "/student/settings/account/",
    ):
        assert f'href="{href}"' in body
    assert "Not started" in body
