"""Early access: a self-signup gets this year's cycle so the search can start."""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from apps.concierge.cycles import current_academic_year
from apps.concierge.models import StudentCycle
from apps.privacy import acceptance, documents
from apps.tenancy.models import Membership


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def published(db):
    for kind in documents.KINDS:
        documents.publish(kind, "en", f"{kind} v1", material=True)


def _signup(client, domain):
    docs = acceptance.documents_to_accept(domain.agency_id, "en")
    return client.post(
        reverse("privacy-signup"),
        {
            "full_name": "Leyla Mammadova",
            "email": "leyla@example.com",
            "password": "correct-horse-battery-staple",
            "language": "en",
            "consent": "on",
            "documents": [str(doc.id) for doc in docs],
        },
        HTTP_HOST=domain.host,
    )


@pytest.mark.django_db
def test_early_access_gives_a_new_student_a_paid_cycle(client, domain_a, published, settings):
    settings.EARLY_ACCESS_FREE_CYCLE = True
    assert _signup(client, domain_a)["Location"] == "/student/"
    student = Membership._base_manager.get(user__username="leyla@example.com")
    cycle = StudentCycle._base_manager.get(student=student)
    assert cycle.paid_at is not None
    assert cycle.academic_year == current_academic_year()


@pytest.mark.django_db
def test_without_early_access_signup_creates_no_cycle(client, domain_a, published, settings):
    settings.EARLY_ACCESS_FREE_CYCLE = False
    _signup(client, domain_a)
    assert get_user_model().objects.filter(username="leyla@example.com").exists()
    assert not StudentCycle._base_manager.exists()


def test_the_academic_year_turns_over_in_july():
    from datetime import date

    assert current_academic_year(date(2026, 10, 10)) == "2026-2027"
    assert current_academic_year(date(2027, 3, 1)) == "2026-2027"
    assert current_academic_year(date(2027, 7, 1)) == "2027-2028"
