import os
import pathlib
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest

from apps.portals.engine import chrome_binary, portal_session
from apps.portals.session import VALUE_PLACEHOLDER, FieldAction

FIXTURE_FORM = """
<!doctype html><html><body><form>
  <label for="fn">Given name</label><input id="fn" name="given_name">
  <label for="ln">Family name</label><input id="ln" name="family_name">
</form></body></html>
"""


@pytest.mark.portal_browser
@pytest.mark.django_db
def test_learn_then_replay_against_real_chrome(tmp_path):
    """End-to-end proof of the cost thesis: the replay pass makes no LLM call.

    Skipped unless a browser and credential are present -- see the
    portal_browser marker. Synchronous on purpose: the engine owns the event
    loop, so no pytest-asyncio dependency is needed.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not configured")
    try:
        chrome_binary()
    except RuntimeError as exc:
        pytest.skip(str(exc))

    from apps.portals.engine import portal_session
    from apps.portals.fill import fill_form, read_back
    from apps.portals.learn import learn_form
    from apps.portals.models import PortalForm

    page_path = tmp_path / "form.html"
    page_path.write_text(FIXTURE_FORM, encoding="utf-8")
    form = PortalForm.objects.create(portal_host="localhost", form_key="fixture")
    values = {"personal.given_name": "Leyla", "personal.family_name": "Aliyeva"}

    with portal_session(
        user_data_dir=tmp_path / "profile",
        # A file:// fixture has no host; None pins the session to that, so a
        # navigation to any real host raises OffDomain.
        allowed_host=None,
    ) as session:
        session.goto(page_path.as_uri())

        # Learn pass: LLM runs here, once.
        field_map = learn_form(
            session,
            form,
            profile_fields=list(values),
            tenant_id=uuid4(),
            forbidden_values=list(values.values()),
        )
        assert len(field_map.entries) == 2

        # Replay pass: no LLM call at all.
        session.goto(page_path.as_uri())
        fill_form(session, field_map, values)
        read_back(session, field_map, values)

        metrics = session.metrics()
        print(
            f"learn pass tokens: prompt={metrics.total_prompt_tokens} "
            f"completion={metrics.total_completion_tokens}"
        )


@pytest.mark.portal_browser
def test_the_query_primitives_answer_against_real_chrome(tmp_path):
    """exists/query_attribute/press_enter are the only three methods whose
    implementation is a guess about the SDK rather than a call plan 1 already
    made. One run against a file:// fixture settles all three."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not configured")
    try:
        chrome_binary()
    except RuntimeError as exc:
        pytest.skip(str(exc))

    fixture = pathlib.Path(__file__).parent / "fixtures" / "login.html"
    with portal_session(user_data_dir=tmp_path, allowed_host=None) as session:
        session.goto(fixture.as_uri())

        assert session.exists("#password") is True
        assert session.exists("#not-here") is False
        assert session.query_attribute("#password", "type") == "password"
        assert session.query_attribute("#password", "data-absent") is None
        # press_enter's only real caller (auth.reauthenticate) has just
        # filled the password field, so focus is already there -- fill it
        # here too rather than calling press_enter cold.
        session.act(
            FieldAction(selector="#password", method="fill", arguments=[VALUE_PLACEHOLDER]),
            {"value": "hunter2"},
        )
        session.press_enter()  # must not raise


@contextmanager
def _served(directory):
    """Serve `directory` over http://127.0.0.1:<port>/.

    Cookies need a real origin. Chrome does not persist them for file:// URIs,
    so the profile-persistence test below has to be served, not opened off disk.
    Loopback is not proxied: Chrome bypasses the proxy for localhost unless
    <-loopback> is in the bypass list, so this never reaches LocalEgressProxy --
    which is CONNECT-only and would refuse a private address anyway.
    """
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(directory))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.portal_browser
def test_a_profile_survives_the_session_that_created_it(tmp_path):
    """The pause/resume premise, minimally. A cookie set in the first session
    must be readable in the second: that is what lets a consultant solve a
    challenge in a preserved session and the worker pick it back up.

    On EC2 capacity with one task the directory outlives the message, which is
    the deployment shape Task 14 chooses. It does NOT survive the instance --
    and that is what apps/portals/auth.py::reauthenticate is for.

    Served over http rather than file://, unlike its two siblings: Chrome does
    not persist cookies for a file:// origin at all, so the file:// version of
    this test could only ever fail, and would read as a profile regression
    rather than a fixture bug.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not configured")
    try:
        chrome_binary()
    except RuntimeError as exc:
        pytest.skip(str(exc))

    page = tmp_path / "pages"
    page.mkdir()
    (page / "login.html").write_bytes(
        (pathlib.Path(__file__).parent / "fixtures" / "login.html").read_bytes()
    )
    profile = tmp_path / "profile"

    with _served(page) as origin:
        url = f"{origin}login.html"
        with portal_session(user_data_dir=profile, allowed_host="127.0.0.1") as session:
            session.goto(url)
            # max-age is load-bearing: a cookie with no expiry is a session
            # cookie, and Chromium drops those on restart unless session restore
            # is on. Without it this asserts nothing about the profile.
            session._loop.run(
                session.page.evaluate("document.cookie = 'resumed=yes; path=/; max-age=3600'")
            )

        with portal_session(user_data_dir=profile, allowed_host="127.0.0.1") as session:
            session.goto(url)
            cookies = str(session._loop.run(session.page.evaluate("document.cookie")))

    assert "resumed=yes" in cookies
