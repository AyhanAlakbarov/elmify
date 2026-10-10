import pathlib

import pytest

BANNED = (
    "playwright_stealth",
    "undetected_chromedriver",
    "selenium_stealth",
    "advancedStealth",
    "advanced_stealth",
    "fingerprint",
    "rotating_proxy",
    "residential",
)


def test_portals_app_contains_no_evasion_capability():
    """Section 3.4 prohibits fingerprint evasion and anti-bot bypass. This is a
    capability boundary, so it is enforced here rather than by convention."""
    source_root = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals"
    offenders = []
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for banned in BANNED:
            if banned in text:
                offenders.append(f"{path.name}: {banned}")
    assert offenders == []


def test_self_heal_is_never_enabled():
    """Stagehand's self_heal re-infers selectors silently and leaves no
    artifact. The spec requires a recorded re-learn instead."""
    engine = (
        pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals" / "engine.py"
    ).read_text(encoding="utf-8")
    assert "self_heal=False" in engine
    assert "self_heal=True" not in engine


def test_replay_methods_are_an_allowlist_not_a_denylist():
    """takeDeterministicAction dispatches sixteen methods and rejects only two.
    Mirroring its check would let a stored click fire on a submit control for
    every student of every tenant, so this side allowlists instead."""
    from apps.portals.session import FILL_METHODS, FieldAction, is_fillable

    assert FILL_METHODS == {"fill", "type", "selectOption", "selectOptionFromDropdown"}

    for dangerous in ("click", "doubleClick", "press", "dragAndDrop", "hover", "scrollTo"):
        action = FieldAction(selector="#x", method=dangerous, arguments=["%value%"])
        assert not is_fillable(action), f"{dangerous} must never be replayable"


def test_the_engine_itself_refuses_an_action_that_is_not_a_fill():
    """The allowlist is enforced at the chokepoint, not by caller convention.

    fill.py pre-checks a stored map and learn.py checks what it stores, but
    resolve.py calls session.act() directly and the next caller will too. A
    grep-based boundary test cannot see session.act(FieldAction(method="click"))
    at all, so the refusal has to live in act() itself.

    No browser: the check runs before _assert_on_portal, so neither the loop
    nor the Stagehand client is touched.
    """
    from apps.portals.engine import StagehandPortalSession
    from apps.portals.session import VALUE_PLACEHOLDER, FieldAction, UnsafeAction

    session = StagehandPortalSession(stagehand=None, loop=None, allowed_host=None)  # type: ignore[arg-type]
    for dangerous in ("click", "press", "dragAndDrop"):
        action = FieldAction(selector="#submit", method=dangerous, arguments=[VALUE_PLACEHOLDER])
        with pytest.raises(UnsafeAction):
            session.act(action, {"value": "x"})


def test_domain_pinning_has_no_default():
    """An opt-in domain policy that no caller opted into is no policy at all."""
    import inspect

    from apps.portals.engine import portal_session

    parameter = inspect.signature(portal_session.__wrapped__).parameters["allowed_host"]
    assert parameter.default is inspect.Parameter.empty


def test_the_chromium_sandbox_is_not_disabled():
    """The renderer sandbox is the only boundary between a hostile portal page
    and the worker process -- which holds the LLM credential, the database
    credentials, and a profile of live student session cookies. Verified by
    probe to cost nothing: the bundled extension loads and CDP works with it on.

    stagehand adds --no-sandbox regardless whenever CI is set
    (browser.py:589,682); test_a_portal_session_refuses_to_open_under_ci
    covers that half.
    """
    engine = (
        pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals" / "engine.py"
    ).read_text(encoding="utf-8")
    assert "chromium_sandbox=True" in engine
    assert "chromium_sandbox=False" not in engine


def test_a_portal_session_refuses_to_open_under_ci(monkeypatch, tmp_path):
    """chromium_sandbox=True is a lie under CI: stagehand appends --no-sandbox
    (browser.py:589,682). Fail loudly instead of quietly running a hostile
    portal page in an unsandboxed renderer."""
    from apps.portals.engine import portal_session

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used-the-guard-fires-first")
    monkeypatch.setenv("CI", "true")
    with pytest.raises(RuntimeError, match="strip the renderer sandbox"):
        with portal_session(user_data_dir=tmp_path, allowed_host="example.test"):
            pass  # pragma: no cover -- never reached


def test_the_default_model_is_one_the_sdk_accepts():
    """stagehand validates model_name against a fixed allowlist and raises
    before launching a browser. The only test that would have caught a bad
    default is skipped without a credential, so pin it here instead."""
    from stagehand.client_models import _model_config

    from apps.portals.engine import DEFAULT_MODEL

    _model_config(DEFAULT_MODEL, api_key="not-a-real-key", headers=None)


def test_press_enter_is_unreachable_from_a_stored_field_map():
    """press_enter is the only control-activation primitive in the app, and it
    exists for one caller: the login form, where the password field already has
    focus. A replay path that could reach it could submit an application, which
    is plan 2b's decision and gated on portal terms."""
    import pathlib

    portals = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals"
    #: engine.py, session.py and auth.py are the three modules legitimately
    #: allowed to name press_enter -- the Protocol declaration, the real
    #: implementation, and the one caller. rglob rather than a hardcoded list:
    #: a new module calling press_enter must be caught even if this test is
    #: never revisited.
    allowed = {"engine.py", "session.py", "auth.py"}
    for path in portals.rglob("*.py"):
        if path.name in allowed or "migrations" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert "press_enter" not in source, path.name

    auth = (portals / "auth.py").read_text(encoding="utf-8")
    assert "press_enter" in auth


def test_no_module_reaches_past_the_session_protocol_to_click():
    """The engine exposes a Stagehand Page, which has click(), type() and
    key_press() on it. Only engine.py may touch that object; everything else
    goes through PortalSession, whose surface is the allowlist."""
    import pathlib

    portals = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals"
    for path in portals.rglob("*.py"):
        if path.name in {"engine.py"} or "migrations" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for reach in (".page.", "page.click(", "page.key_press("):
            assert reach not in source, f"{path.name}: {reach}"


def test_nothing_in_the_app_can_submit():
    """The platform never submits. Superseded in FORM, not in substance, by the
    2026-09-15 glass-box decision 10: the student presses Submit in their own
    session and the server RECORDS that they did, so the guard is on the ACT
    and no longer on the word.

    The act itself is banned by four tests above, none of which changed:
    FILL_METHODS is an allowlist, act() refuses anything outside it,
    press_enter is unreachable from a stored map, and no module reaches past
    the session Protocol to click. Those are what stop an application being
    submitted by us; this test never could, because a string ban cannot see
    session.act(FieldAction(method="click")) either.

    What remains banned here: any control-activation verb aimed at a submit
    control. ext_api.py may NAME the state -- it writes one student's own
    attestation into the §5.5 trail, which is the evidence §10 wants, not a
    capability it forbids.
    """
    import pathlib

    portals = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals"
    #: ext_api.py records a SUBMITTED the student performed; models.py declares
    #: the state; migrations replay the choices list. Everything else in the app
    #: has no business naming it, and a new module that does is a design change
    #: this test should make someone argue for.
    allowed = {"ext_api.py", "models.py"}
    for path in portals.rglob("*.py"):
        if path.name in allowed or "migrations" in path.parts:
            continue
        assert "SUBMITTED" not in path.read_text(encoding="utf-8"), path.name

    #: And the act stays impossible from the one module now allowed to name it:
    #: recording is not dispatching.
    ext_api = (portals / "ext_api.py").read_text(encoding="utf-8")
    for dispatch in ("click(", "press(", "press_enter", "key_press", "MouseEvent"):
        assert dispatch not in ext_api, dispatch


def test_chrome_is_resolved_from_the_playwright_cache_wherever_it_is(monkeypatch, tmp_path):
    """The container installs Chrome under PLAYWRIGHT_BROWSERS_PATH and runs as
    a non-root user, so a path under $HOME resolves to a directory that does not
    exist there. Same binary, different root."""
    from apps.portals.engine import chrome_binary

    for revision in ("chromium-1140", "chromium-1234"):
        binary = tmp_path / revision / "chrome-linux64" / "chrome"
        binary.parent.mkdir(parents=True)
        binary.touch()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))

    # Highest revision, numerically -- "chromium-999" sorts above
    # "chromium-1234" as a string, which would pin an older Chrome silently.
    assert chrome_binary().parts[-3] == "chromium-1234"


def test_a_missing_chrome_is_a_loud_failure(monkeypatch, tmp_path):
    """Not a fallback to system Chrome: that combination has no working
    configuration (Extensions.loadUnpacked is unavailable on it)."""
    import pytest

    from apps.portals.engine import chrome_binary

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="Chrome for Testing"):
        chrome_binary()
