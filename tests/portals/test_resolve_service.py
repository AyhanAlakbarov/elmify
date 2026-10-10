"""The service tier: bounded, credential-optional, and unable to do anything
except write a token into the field the provider's own script writes to."""

from uuid import uuid4

import pytest

from apps.portals.challenge import UNKNOWN_KIND, Challenge
from apps.tenancy.context import tenant_scope
from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db

CHALLENGE = Challenge(
    kind="recaptcha",
    site_key="site-key-1",
    page_url="https://apply.example.edu/personal",
    response_selector="textarea[name='g-recaptcha-response']",
)


def _application(agency, student, *, approved=False):
    from apps.portals.models import Application, PortalForm

    # form_key varies: PortalForm has a unique (portal_host, form_key)
    # constraint and these helpers are called more than once per test.
    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"personal-details-{uuid4()}",
        resolution_approved=approved,
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_a_solved_challenge_returns_the_token(agency_a, membership_a):
    """Records what the adapter was called with and asserts outside solve(),
    like its two siblings: ServiceResolver._attempt catches any exception the
    adapter raises and treats it as a failed attempt, so an assertion inside
    solve() is swallowed -- the test would then pass three attempts and ~3s of
    real time.sleep later, having proved nothing about the arguments."""
    from apps.portals.resolve import ServiceResolver

    calls = []

    class Adapter:
        def solve(self, *, kind, site_key, page_url):
            calls.append((kind, site_key, page_url))
            return "token-1"

    with tenant_scope(agency_a.id):
        resolver = ServiceResolver(Adapter(), sleep=lambda _: None)
        application = _application(agency_a, membership_a, approved=True)
        assert resolver.solve(CHALLENGE, application=application) == "token-1"

    assert calls == [("recaptcha", "site-key-1", CHALLENGE.page_url)]


def test_attempts_are_bounded_and_backed_off(agency_a, membership_a):
    """A resolution service that is down must not become an unbounded spend."""
    from apps.portals.resolve import ServiceResolver

    calls = []
    slept = []

    class Failing:
        def solve(self, *, kind, site_key, page_url):
            calls.append(1)
            return None

    with tenant_scope(agency_a.id):
        resolver = ServiceResolver(Failing(), attempts=3, sleep=slept.append)
        application = _application(agency_a, membership_a, approved=True)
        assert resolver.solve(CHALLENGE, application=application) is None

    assert len(calls) == 3
    assert slept == [1.0, 2.0]  # no sleep after the last attempt


def test_an_unapproved_portal_never_reaches_the_service(agency_a, membership_a):
    """CLAUDE.md: a resolution service may be integrated only per-approved
    portal, after the portal-terms and legal gates. The default is False, so a
    portal nobody has cleared falls through to a consultant.

    Asserts on a call count, not a raised exception: ServiceResolver._attempt
    catches any exception the adapter raises and treats it as a failed
    attempt, so a fake that raises to signal "must not run" would still leave
    solve() returning None after exhausting retries -- passing for the wrong
    reason even if this gate were deleted."""
    from apps.portals.resolve import ServiceResolver

    calls = []

    class Adapter:
        def solve(self, *, kind, site_key, page_url):
            calls.append(1)
            return "token-should-not-be-used"

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        assert application.portal_form.resolution_approved is False

        assert ServiceResolver(Adapter()).solve(CHALLENGE, application=application) is None

    assert calls == []


def test_no_configured_provider_is_a_fallback_not_a_crash(agency_a, membership_a):
    """§ Challenge resolution: 'an absent or rejected credential is a
    ConsultantResolver fallback, not a crash'."""
    from apps.portals.resolve import ServiceResolver

    with tenant_scope(agency_a.id):
        assert ServiceResolver(None).solve(
            CHALLENGE, application=_application(agency_a, membership_a)
        ) is None


def test_an_unknown_challenge_is_never_sent_to_the_service(agency_a, membership_a):
    """The stall heuristic produces no kind and no site key. Sending that to a
    paid API is spend with no possible result.

    Approved=True so this isolates the unknown-kind check: without it, this
    test would pass even with the check deleted, because the unapproved-
    portal gate alone would already return None. Asserts on a call count,
    not a raised exception, for the same reason as the unapproved-portal
    test above -- ServiceResolver._attempt swallows whatever the adapter
    raises."""
    from apps.portals.resolve import ServiceResolver

    calls = []

    class Adapter:
        def solve(self, *, kind, site_key, page_url):
            calls.append(1)
            return "token-should-not-be-used"

    unknown = Challenge(kind=UNKNOWN_KIND, site_key="", page_url="p", response_selector="")
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, approved=True)
        assert ServiceResolver(Adapter()).solve(unknown, application=application) is None

    assert calls == []


def test_a_provider_that_raises_is_a_failed_attempt_not_a_crash():
    from apps.portals.resolve import ServiceResolver

    class Exploding:
        def solve(self, *, kind, site_key, page_url):
            raise RuntimeError("provider 503")

    resolver = ServiceResolver(Exploding(), attempts=2, sleep=lambda _: None)
    assert resolver._attempt(CHALLENGE) is None


def test_the_token_is_written_through_the_ordinary_fill_path():
    """apply_token builds a FieldAction that is_fillable accepts, so a token
    goes in exactly the way a student value does -- no new primitive, and
    nothing that could activate a control."""
    from apps.portals.resolve import apply_token

    session = FakePortalSession()
    apply_token(session, CHALLENGE, "token-1")

    assert session.values == {"textarea[name='g-recaptcha-response']": "token-1"}


def test_configured_adapter_is_none_without_a_credential(settings, monkeypatch):
    from apps.portals.resolve import configured_adapter

    settings.PORTAL_CAPTCHA_ENDPOINT = "https://provider.example/solve"
    monkeypatch.delenv("PORTAL_CAPTCHA_API_KEY", raising=False)

    assert configured_adapter() is None
