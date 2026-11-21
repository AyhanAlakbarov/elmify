"""The GitHub username door (CV evidence spec §5.1): validation, the limiter, set /
change / clear. JSON only; the screen that calls it is Aykhan's."""

import json

import pytest
from django.core.cache import cache
from django.db import IntegrityError
from django.test import Client
from django.utils import timezone

from apps.documents.evidence import facts
from apps.documents.models import EvidenceReading, VerifiedFact
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db
URL = "/api/documents/github-login"


@pytest.fixture
def signed_in(client, domain_a, user_a, membership_a):
    client.force_login(user_a)
    return client


@pytest.fixture
def queued(monkeypatch):
    sent = []
    monkeypatch.setattr("apps.documents.document_queue.enqueue_document_work",
                        lambda message, **kwargs: sent.append(message))
    return sent


def _post(client, host, body):
    return client.post(URL, json.dumps(body), content_type="application/json", HTTP_HOST=host)


def test_a_session_is_required(client, domain_a):
    assert _post(client, domain_a.host, {"login": "0rkhann"}).status_code == 401


@pytest.mark.parametrize("login", ["", "-abc", "a" * 40, "ab/c", "ab\nc", "ab c", None, 7])
def test_an_invalid_login_is_refused(signed_in, domain_a, login):
    response = _post(signed_in, domain_a.host, {"login": login})
    assert (response.status_code, response.json()) == (400, {"error": "invalid_login"})


def test_setting_and_changing_a_login_saves_it_and_queues_a_refresh(
    signed_in, domain_a, membership_a, queued, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        first = _post(signed_in, domain_a.host, {"login": " 0rkhann "})
        second = _post(signed_in, domain_a.host, {"login": "other-login"})
    assert (first.status_code, second.status_code) == (202, 202)
    assert [m.action for m in queued] == ["refresh_evidence", "refresh_evidence"]
    with tenant_scope(membership_a.tenant_id):
        assert facts.github_login(membership_a) == "other-login"
        rows = VerifiedFact.objects.filter(student=membership_a,
                                           category=VerifiedFact.Category.IDENTITY)
        assert rows.count() == 2  # the change superseded the first


def test_clearing_deletes_the_login_and_every_github_reading(signed_in, domain_a, membership_a):
    with tenant_scope(membership_a.tenant_id):
        facts.set_github_login(membership_a, "0rkhann")
        facts.save_reading(membership_a, source_kind="github", repo="0rkhann/MicroKatc",
                           changed_at=timezone.now(), reader_version=1, reading={}, skills=())
    response = signed_in.delete(URL, HTTP_HOST=domain_a.host)
    assert (response.status_code, response.json()) == (200, {"status": "cleared"})
    with tenant_scope(membership_a.tenant_id):
        assert facts.github_login(membership_a) == ""
        assert not EvidenceReading.objects.filter(student=membership_a).exists()


def test_final_4_the_limiter_counts_sets_and_never_refuses_a_clear(signed_in, domain_a, queued):
    for _ in range(10):
        assert _post(signed_in, domain_a.host, {"login": "0rkhann"}).status_code == 202
    response = _post(signed_in, domain_a.host, {"login": "0rkhann"})
    assert (response.status_code, response.json()) == (429, {"error": "rate_limited"})
    # Clearing is the erasure of a data source: a 429 on it would refuse a privacy request.
    for _ in range(11):
        assert signed_in.delete(URL, HTTP_HOST=domain_a.host).status_code == 200


def test_final_4_a_clear_racing_a_change_is_a_conflict(signed_in, domain_a, monkeypatch):
    def _race(student):
        raise IntegrityError("verifiedfact_one_superseder")

    monkeypatch.setattr(facts, "clear_github_login", _race)
    response = signed_in.delete(URL, HTTP_HOST=domain_a.host)
    assert (response.status_code, response.json()) == (409, {"error": "conflict"})


def test_get_shows_the_login_and_the_unknown_user_message(signed_in, domain_a, membership_a):
    with tenant_scope(membership_a.tenant_id):
        facts.set_github_login(membership_a, "0rkhann")
    assert signed_in.get(URL, HTTP_HOST=domain_a.host).json() == {"login": "0rkhann",
                                                                   "message": None}
    cache.set(f"evidence:github-unknown:{membership_a.id}", "0rkhann")
    assert signed_in.get(URL, HTTP_HOST=domain_a.host).json() == {
        "login": "0rkhann", "message": "We couldn't find GitHub user 0rkhann."}


def test_csrf_applies(domain_a, user_a, membership_a):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user_a)
    assert _post(client, domain_a.host, {"login": "0rkhann"}).status_code == 403
