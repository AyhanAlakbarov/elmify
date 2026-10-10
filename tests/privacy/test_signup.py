
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils.html import strip_tags

from apps.privacy import acceptance, documents
from apps.privacy.forms import CONSENT_TEXT
from apps.privacy.models import Acceptance
from apps.tenancy.models import Membership

CONSENT = "consent"


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def published(db):
    for kind in documents.KINDS:
        documents.publish(kind, "en", f"{kind} v1", material=True)


def _shown_ids(language="en"):
    """The ids the signup page renders as hidden fields for `language`."""
    from apps.tenancy.models import Agency

    tenant_id = Agency.objects.get(name="Agency A").id
    return [str(d.id) for d in acceptance.documents_to_accept(tenant_id, language)]


def _post(client, host, extra=None, **over):
    data = {
        "full_name": "Aysel Mammadova",
        "email": "Aysel@Example.com",
        "password": "correct-horse-battery-staple",
        "language": "en",
        CONSENT: "on",
    }
    data.update(over)
    data.setdefault("documents", _shown_ids(data["language"]))
    return client.post(reverse("privacy-signup"), data, HTTP_HOST=host, **(extra or {}))



@pytest.mark.django_db
def test_signup_creates_student_records_acceptance_and_logs_in(
    client, domain_a, published
):
    response = _post(client, domain_a.host)
    assert response.status_code == 302
    user = get_user_model().objects.get(username="aysel@example.com")
    membership = Membership._base_manager.get(user=user)
    assert membership.role == Membership.Role.STUDENT
    assert membership.tenant_id == domain_a.agency_id
    accepted = Acceptance._base_manager.filter(student=membership)
    kinds = set(accepted.values_list("document__kind", flat=True))
    assert kinds == {"terms", "privacy_notice_agency"}
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_signup_without_the_tick_creates_nothing(client, domain_a, published):
    response = _post(client, domain_a.host, **{CONSENT: ""})
    assert response.status_code == 400
    assert not get_user_model().objects.exists()



@pytest.mark.django_db
def test_signup_with_an_existing_email_in_any_case_is_refused(
    client, domain_a, published
):
    assert _post(client, domain_a.host).status_code == 302
    client.logout()
    response = _post(client, domain_a.host, email="AYSEL@example.COM")
    assert response.status_code == 400
    assert get_user_model().objects.count() == 1


@pytest.mark.django_db
def test_signup_refuses_when_no_documents_are_published(client, domain_a):
    response = _post(client, domain_a.host)
    assert response.status_code == 503
    assert not get_user_model().objects.exists()



@pytest.mark.django_db
def test_legal_page_shows_the_current_text(client, domain_a, published):
    url = reverse("privacy-legal", args=["terms"]) + "?lang=az"
    response = client.get(url, HTTP_HOST=domain_a.host)
    assert response.status_code == 200 and b"terms v1" in response.content
    unknown = client.get(reverse("privacy-legal", args=["cookies"]), HTTP_HOST=domain_a.host)
    assert unknown.status_code == 404


@pytest.mark.django_db
def test_agency_notice_shows_the_agency_name_not_the_placeholder(client, domain_a, agency_a):
    body = "Your agency, {{ agency }}, controls it."
    documents.publish("privacy_notice_agency", "en", body, material=True)
    url = reverse("privacy-legal", args=["privacy_notice_agency"])
    response = client.get(url, HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    assert b"Your agency, Agency A, controls it." in response.content
    assert b"{{ agency }}" not in response.content


@pytest.mark.django_db
def test_a_document_published_between_get_and_post_is_refused(client, domain_a, published):
    for kind in documents.KINDS:
        documents.publish(kind, "ru", f"{kind} ru v1", material=True)
    page = client.get(reverse("privacy-signup") + "?lang=ru", HTTP_HOST=domain_a.host)
    shown = [str(doc.id) for doc in page.context["docs"]]
    new_terms, _ = documents.publish("terms", "ru", "terms ru v2", material=True)

    response = _post(client, domain_a.host, language="ru", documents=shown)

    assert response.status_code == 400
    assert not get_user_model().objects.exists()
    assert not Acceptance._base_manager.exists()
    assert new_terms in response.context["docs"]
    assert str(new_terms.id) in response.content.decode()


@pytest.mark.django_db
def test_an_unknown_language_shows_english_with_english_selected(client, domain_a, published):
    response = client.get(reverse("privacy-signup") + "?lang=xx", HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    assert {doc.language for doc in response.context["docs"]} == {"en"}
    body = response.content.decode()
    assert '<input type="hidden" name="language" value="en">' in body
    assert '<strong aria-current="true">English</strong>' in body


@pytest.mark.django_db
def test_choosing_a_language_reloads_the_page_so_its_documents_are_the_ones_posted(
    client, domain_a, published
):
    """The language is a link, not a select: picking Azerbaijani after the page
    loaded used to post English document ids with language=az, and the student
    was told the documents had changed while the page was open."""
    for kind in ("terms", "privacy_notice_agency", "privacy_notice_direct"):
        documents.publish(kind, "az", f"{kind} az v1", material=True)
    page = client.get(reverse("privacy-signup") + "?lang=az", HTTP_HOST=domain_a.host)
    shown = [str(doc.id) for doc in page.context["docs"]]
    assert {doc.language for doc in page.context["docs"]} == {"az"}
    response = _post(client, domain_a.host, language="az", documents=shown)
    assert response.status_code == 302


def test_the_consent_sentence_is_pinned():
    assert CONSENT_TEXT == (
        "I agree to the Terms of Service and consent to the processing of my personal data as "
        "described in the Privacy Notice, including its transfer to the countries it lists."
    )


@pytest.mark.django_db
def test_the_signup_page_shows_the_sentence_with_the_box_unticked(client, domain_a, published):
    html = client.get(reverse("privacy-signup"), HTTP_HOST=domain_a.host).content.decode()
    assert CONSENT_TEXT in " ".join(strip_tags(html).split())
    box = html[html.index('name="consent"') :].split(">", 1)[0]
    assert "checked" not in box


@pytest.mark.django_db
def test_an_overlong_email_is_a_form_error_not_a_crash(client, domain_a, published):
    email = "a" * 178 + "@example.com"  # 190 characters; auth_user.username holds 150
    response = _post(client, domain_a.host, email=email)
    assert response.status_code == 400
    assert not get_user_model().objects.exists()



@pytest.mark.django_db
def test_an_email_already_used_as_another_users_email_is_refused(client, domain_a, published):
    get_user_model().objects.create_user(username="staff-aysel", email="AYSEL@example.com")
    response = _post(client, domain_a.host)
    assert response.status_code == 400
    assert get_user_model().objects.count() == 1


@pytest.mark.django_db
def test_signup_posts_are_limited_per_client_address(client, domain_a, published):
    """Keyed on the address the ALB appends -- the LAST X-Forwarded-For entry.
    Anything to its left is whatever the client sent, so rotating it buys nothing."""
    for n in range(10):
        spoofed = {"HTTP_X_FORWARDED_FOR": f"10.0.0.{n}, 203.0.113.7"}
        assert _post(client, domain_a.host, spoofed, **{CONSENT: ""}).status_code == 400

    response = _post(client, domain_a.host, {"HTTP_X_FORWARDED_FOR": "203.0.113.7"})

    assert response.status_code == 429
    assert not get_user_model().objects.exists()
    other = _post(client, domain_a.host, {"HTTP_X_FORWARDED_FOR": "198.51.100.9"})
    assert other.status_code == 302


@pytest.mark.django_db
def test_repeated_signups_for_a_taken_email_are_limited(client, domain_a, published):
    """The "already exists" answer is an existence oracle across tenants; five
    asks an hour per address is enough for a student who forgot they signed up."""
    assert _post(client, domain_a.host).status_code == 302
    client.logout()
    for _ in range(5):
        assert _post(client, domain_a.host, email="AYSEL@example.com").status_code == 400

    response = _post(client, domain_a.host, email="aysel@EXAMPLE.com")

    assert response.status_code == 429
    assert get_user_model().objects.count() == 1
