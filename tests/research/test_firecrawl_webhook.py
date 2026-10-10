import hashlib
import hmac
import json

import pytest
from django.db import ProgrammingError

pytestmark = pytest.mark.django_db

_SECRET = "s" * 32
_BODY = json.dumps(
    {"type": "monitor.page", "data": {"url": "https://uni.example.org/apply/", "status": "changed"}}
).encode()


def _signature(body: bytes, secret: str = _SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_the_route_does_not_exist_while_the_flag_is_off(client, settings):
    """Nothing is deployed. A route that exists and is unreachable makes
    Firecrawl report OUR unreachability as a delivery failure on every check,
    three retries at a time; a 404 is a smaller surface than that."""
    settings.FETCH_WEBHOOKS_ENABLED = False

    response = client.post(
        "/webhooks/firecrawl/", data=_BODY, content_type="application/json",
        HTTP_X_FIRECRAWL_SIGNATURE=_signature(_BODY),
    )

    assert response.status_code == 404


def test_a_valid_signature_is_accepted(client, settings):
    settings.FETCH_WEBHOOKS_ENABLED = True
    settings.FIRECRAWL_WEBHOOK_SECRET = _SECRET

    response = client.post(
        "/webhooks/firecrawl/", data=_BODY, content_type="application/json",
        HTTP_X_FIRECRAWL_SIGNATURE=_signature(_BODY),
    )

    assert response.status_code == 200


def test_a_wrong_signature_is_401(client, settings):
    settings.FETCH_WEBHOOKS_ENABLED = True
    settings.FIRECRAWL_WEBHOOK_SECRET = _SECRET

    response = client.post(
        "/webhooks/firecrawl/", data=_BODY, content_type="application/json",
        HTTP_X_FIRECRAWL_SIGNATURE=_signature(_BODY, "wrong"),
    )

    assert response.status_code == 401


def test_the_signature_is_over_the_RAW_body_not_the_parsed_one(client, settings):
    """`json.dumps(json.loads(body))` is not `body`: key order and separators
    differ, and re-serialising before verifying is the classic way an HMAC
    check passes for a body nobody sent."""
    settings.FETCH_WEBHOOKS_ENABLED = True
    settings.FIRECRAWL_WEBHOOK_SECRET = _SECRET
    spaced = b'{"type": "monitor.page",  "data": {"url": "https://uni.example.org/apply/"}}'

    response = client.post(
        "/webhooks/firecrawl/", data=spaced, content_type="application/json",
        HTTP_X_FIRECRAWL_SIGNATURE=_signature(spaced),
    )

    assert response.status_code == 200


def test_an_absent_secret_refuses_every_delivery(client, settings):
    """Never a settings default, and never 'no secret means accept'. A
    deployment that forgot the secret must fail loudly, not accept anything
    that posts."""
    settings.FETCH_WEBHOOKS_ENABLED = True
    settings.FIRECRAWL_WEBHOOK_SECRET = ""

    response = client.post(
        "/webhooks/firecrawl/", data=_BODY, content_type="application/json",
        HTTP_X_FIRECRAWL_SIGNATURE=_signature(_BODY),
    )

    assert response.status_code == 401


def test_a_changed_page_is_marked_stale_and_nothing_is_fetched_inline(
    client, settings, snapshot_factory
):
    """2xx within 10 seconds. A receiver that fetched the page inline would
    hold the request open for a vendor round trip and be retried three times
    while it was still working on the first delivery."""
    settings.FETCH_WEBHOOKS_ENABLED = True
    settings.FIRECRAWL_WEBHOOK_SECRET = _SECRET
    snapshot = snapshot_factory(final_url="https://uni.example.org/apply/")

    client.post(
        "/webhooks/firecrawl/", data=_BODY, content_type="application/json",
        HTTP_X_FIRECRAWL_SIGNATURE=_signature(_BODY),
    )

    snapshot.refresh_from_db()
    assert snapshot.retrieval_status == "STALE"


def test_a_get_is_not_allowed(client, settings):
    settings.FETCH_WEBHOOKS_ENABLED = True
    settings.FIRECRAWL_WEBHOOK_SECRET = _SECRET

    assert client.get("/webhooks/firecrawl/").status_code == 405


@pytest.mark.django_db(transaction=True)
def test_under_the_web_role_the_write_is_refused_not_silent(client, settings, web_role_orm):
    """The receiver is routed to the WEB tier (`WebTaskDefinition` carries its
    secret), and the web tier runs as `runtime_web`, which holds no grant on
    `funding_officialsourcesnapshot` -- a catalogue table. So with the flag on,
    a correctly signed delivery reaches the UPDATE and fails with `permission
    denied`, a 500 Firecrawl retries three times.

    This pins that state so enabling `FETCH_WEBHOOKS_ENABLED` cannot look like
    it works: every other test here runs as the superuser test role, which
    bypasses grants, and passes. Enabling the receiver means routing the write
    to `runtime_engine` (queue it to the worker) AND adding an UPDATE policy on
    the snapshot table -- the engine has no UPDATE policy there either, so the
    same statement on the worker matches zero rows (`poll_monitor_checks._mark`).
    When that lands, this test changes with it, on purpose.
    """
    settings.FETCH_WEBHOOKS_ENABLED = True
    settings.FIRECRAWL_WEBHOOK_SECRET = _SECRET

    refused = "permission denied for table funding_officialsourcesnapshot"
    with pytest.raises(ProgrammingError, match=refused):
        client.post(
            "/webhooks/firecrawl/", data=_BODY, content_type="application/json",
            HTTP_X_FIRECRAWL_SIGNATURE=_signature(_BODY),
        )
