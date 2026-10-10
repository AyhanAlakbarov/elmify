"""Origin pinning, exercised without a browser.

The control lives in StagehandPortalSession._assert_on_portal, and the only
test that drove it end to end needs a credential and a display, so it is
skipped in CI. These stub the loop and the page so the check itself runs.
"""

import pytest

from apps.portals.engine import OffDomain, StagehandPortalSession


class _StubLoop:
    """The real loop marshals a coroutine onto its thread; the stub just
    returns what the page handed back."""

    def run(self, value):
        return value


class _StubPage:
    def __init__(self, url: str) -> None:
        self._url = url

    def url(self) -> str:
        return self._url


def _session_on(url: str, allowed_host: str | None) -> StagehandPortalSession:
    session = StagehandPortalSession(
        stagehand=None,  # type: ignore[arg-type]
        loop=_StubLoop(),  # type: ignore[arg-type]
        allowed_host=allowed_host,
    )
    # goto() would need a live browser context; the page is what matters here.
    session._page = _StubPage(url)  # type: ignore[assignment]
    return session


def test_matching_host_is_accepted():
    _session_on("https://apply.example.edu/form", "apply.example.edu")._assert_on_portal()


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/form",
        # userinfo must not be mistaken for the host
        "https://apply.example.edu@evil.example/form",
        # a sibling subdomain is still a different origin
        "https://www.apply.example.edu/form",
        "file:///tmp/clone.html",
    ],
)
def test_any_other_origin_raises(url):
    with pytest.raises(OffDomain):
        _session_on(url, "apply.example.edu")._assert_on_portal()


def test_none_pins_to_a_host_less_scheme():
    """None is not an escape hatch: it accepts a file:// fixture and rejects
    every real host."""
    _session_on("file:///tmp/form.html", None)._assert_on_portal()

    with pytest.raises(OffDomain):
        _session_on("https://evil.example/form", None)._assert_on_portal()


def test_read_value_checks_the_origin_before_reading():
    """read_back must not verify values against a page that is no longer the
    portal -- it would read the attacker's own inputs back and pass."""
    session = _session_on("https://evil.example/form", "apply.example.edu")

    with pytest.raises(OffDomain):
        session.read_value("#fn")


def test_act_checks_the_origin_before_typing():
    """act() is the call that puts a student's value into the document. If its
    origin check were removed, every other test here would still pass."""
    from apps.portals.session import FieldAction

    session = _session_on("https://evil.example/form", "apply.example.edu")
    action = FieldAction(selector="#fn", method="fill", arguments=["%value%"])

    with pytest.raises(OffDomain):
        session.act(action, {"value": "Leyla"})


def test_observe_checks_the_origin_before_asking_the_model():
    """observe() reads the page into an LLM prompt; doing that on an attacker's
    document is how a poisoned field map gets written in the first place."""
    session = _session_on("https://evil.example/form", "apply.example.edu")

    with pytest.raises(OffDomain):
        session.observe("the form field for personal.given_name")
