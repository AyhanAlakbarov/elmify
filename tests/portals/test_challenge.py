"""Detection is a DOM query, never a judgement. Both directions matter: a
missed challenge stalls an application, and a false positive sends an ordinary
form to a consultant."""

from tests.portals.fakes import FakePortalSession

PAGE = "https://apply.example.edu/personal"


def test_each_known_challenge_is_matched_with_its_site_key():
    from apps.portals.challenge import detect_challenge

    for selector, kind in (
        (".g-recaptcha", "recaptcha"),
        (".h-captcha", "hcaptcha"),
        (".cf-turnstile", "turnstile"),
    ):
        session = FakePortalSession(elements={selector: {"data-sitekey": "site-key-1"}})

        challenge = detect_challenge(session, page_url=PAGE)

        assert challenge is not None
        assert challenge.kind == kind
        assert challenge.site_key == "site-key-1"
        assert challenge.page_url == PAGE


def test_an_ordinary_form_is_not_a_challenge():
    from apps.portals.challenge import detect_challenge

    session = FakePortalSession(elements={"#name": {}, "form": {}, ".g-recaptcha-help": {}})

    assert detect_challenge(session, page_url=PAGE) is None


def test_a_marker_without_a_site_key_is_still_a_challenge():
    """An invisible reCAPTCHA renders its site key elsewhere. Reporting no
    challenge because we could not read the key would strand the application
    at the one moment a resolver is needed."""
    from apps.portals.challenge import detect_challenge

    session = FakePortalSession(elements={".g-recaptcha": {}})

    challenge = detect_challenge(session, page_url=PAGE)
    assert challenge is not None
    assert challenge.site_key == ""


def test_repeated_failures_with_no_marker_are_an_unknown_challenge():
    """The stall heuristic. It has no site key by construction, so it can only
    ever reach a consultant -- a resolution service has nothing to be given."""
    from apps.portals.challenge import STALL_THRESHOLD, UNKNOWN_KIND, detect_challenge

    session = FakePortalSession()

    assert detect_challenge(session, page_url=PAGE, act_failures=STALL_THRESHOLD - 1) is None
    stalled = detect_challenge(session, page_url=PAGE, act_failures=STALL_THRESHOLD)
    assert stalled is not None
    assert stalled.kind == UNKNOWN_KIND
    assert stalled.site_key == ""
