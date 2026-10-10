"""Challenge resolution: the service first, a consultant second.

§2 makes CAPTCHA delegable application work and §5.1 requires both paths. The
provider is named in configuration rather than in code so that swapping one is
a deployment change; the adapter interface is three arguments wide on purpose,
because anything wider starts to encode one provider's API.

The service tier is off until a portal is approved for it:
PortalForm.resolution_approved defaults to False and is checked before the
provider is ever called, per the project's Phase 3 rules ("only
per-approved-portal, after the portal-terms and legal gates, with consultant
fallback"). An unapproved portal gets the consultant path, which is the MVP
behaviour the requirements already describe. The per-portal approval record is
retained as an audit artifact under §5.5, and §10's portal-terms blocker
still gates running any of this against a real portal.
"""

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Protocol

import urllib3
from django.conf import settings

from .challenge import UNKNOWN_KIND, Challenge
from .escalation import Trigger, escalate
from .models import Application
from .session import VALUE_PLACEHOLDER, FieldAction, PortalSession

logger = logging.getLogger(__name__)


class ProviderAdapter(Protocol):
    def solve(self, *, kind: str, site_key: str, page_url: str) -> str | None: ...


class CaptchaResolver(Protocol):
    def solve(self, challenge: Challenge, *, application: Application) -> str | None: ...


class HttpCaptchaProvider:
    """One concrete adapter, shaped like every hosted resolution API: post the
    challenge, get a token back. A provider whose API differs gets its own
    class implementing ProviderAdapter -- not a branch in this one."""

    def __init__(self, endpoint: str, api_key: str) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._http = urllib3.PoolManager()

    def solve(self, *, kind: str, site_key: str, page_url: str) -> str | None:
        response = self._http.request(
            "POST",
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            body=json.dumps({"type": kind, "site_key": site_key, "url": page_url}),
            timeout=urllib3.Timeout(total=settings.PORTAL_CAPTCHA_TIMEOUT_SECONDS),
            retries=False,
        )
        if response.status != 200:
            return None
        token = json.loads(response.data).get("token")
        return token if isinstance(token, str) and token else None


def configured_adapter() -> ProviderAdapter | None:
    """None whenever the deployment has no service tier. Both halves are
    required: an endpoint with no credential is a misconfiguration, and
    treating it as configured would spend every attempt on a 401."""
    endpoint = settings.PORTAL_CAPTCHA_ENDPOINT
    api_key = os.environ.get("PORTAL_CAPTCHA_API_KEY", "")
    if not endpoint or not api_key:
        return None
    return HttpCaptchaProvider(endpoint, api_key)


class ServiceResolver:
    """Bounded attempts against the configured provider. Never raises."""

    def __init__(
        self,
        adapter: ProviderAdapter | None = None,
        *,
        attempts: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._adapter = adapter
        self._attempts = attempts or settings.PORTAL_CAPTCHA_ATTEMPTS
        self._sleep = sleep

    def _attempt(self, challenge: Challenge) -> str | None:
        assert self._adapter is not None
        try:
            return self._adapter.solve(
                kind=challenge.kind, site_key=challenge.site_key, page_url=challenge.page_url
            )
        except Exception:
            # A provider outage is a failed attempt, not a failed application:
            # the consultant path is right there.
            logger.warning("captcha provider attempt failed", exc_info=True)
            return None

    def solve(self, challenge: Challenge, *, application: Application) -> str | None:
        # Three ways to not call the provider, and all three are ordinary
        # states rather than errors: no service tier configured, a portal
        # nobody has approved for automated resolution (CLAUDE.md's Phase 3
        # rule, default False), and a stall-heuristic challenge that carries
        # no site key to send.
        assert application.portal_form is not None  # never queued portal-less
        if (
            self._adapter is None
            or not application.portal_form.resolution_approved
            or challenge.kind == UNKNOWN_KIND
        ):
            return None
        for attempt in range(self._attempts):
            token = self._attempt(challenge)
            if token:
                return token
            if attempt < self._attempts - 1:
                self._sleep(2.0**attempt)
        logger.info(
            "PortalChallengeUnsolved portal=%s kind=%s",
            application.portal_form.portal_host,
            challenge.kind,
        )
        return None


def apply_token(session: PortalSession, challenge: Challenge, token: str) -> None:
    """Write the token into the provider's own response field.

    Through FieldAction and act(), not a new primitive: the response field is a
    textarea or hidden input, so filling it is exactly the operation the replay
    allowlist already permits.
    """
    session.act(
        FieldAction(
            selector=challenge.response_selector,
            method="fill",
            arguments=[VALUE_PLACEHOLDER],
        ),
        {"value": token},
    )


class ConsultantResolver:
    """Hands the preserved session to a human. Always returns None.

    It cannot return a token by construction, which is the point: the fallback
    is a person doing the challenge in the session we kept open, not a second
    automated guess. The session survives because the browser profile is
    per-application and outlives the worker's message
    (apps/portals/profiles.py).
    """

    def solve(self, challenge: Challenge, *, application: Application) -> str | None:
        escalate(
            application,
            Trigger.UNSOLVED_CHALLENGE,
            detail=f"{challenge.kind} on {challenge.page_url}",
        )
        return None


def resolve_challenge(
    session: PortalSession,
    challenge: Challenge,
    *,
    application: Application,
    service: CaptchaResolver | None = None,
    consultant: CaptchaResolver | None = None,
) -> bool:
    """True when the page is clear to continue.

    Order is fixed by §5.1: the service is tried first and only its exhaustion
    reaches a consultant. Nothing here clears the form -- the fields already
    filled stay filled, which is what "without losing completed form state"
    means in practice.
    """
    service = service or ServiceResolver(configured_adapter())
    token = service.solve(challenge, application=application)
    if token:
        apply_token(session, challenge, token)
        return True
    (consultant or ConsultantResolver()).solve(challenge, application=application)
    return False
