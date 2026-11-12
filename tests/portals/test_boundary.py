import pathlib

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


def test_replay_methods_are_an_allowlist_not_a_denylist():
    """takeDeterministicAction dispatches sixteen methods and rejects only two.
    Mirroring its check would let a stored click fire on a submit control for
    every student of every tenant, so this side allowlists instead."""
    from apps.portals.session import FILL_METHODS, FieldAction, is_fillable

    assert FILL_METHODS == {"fill", "type", "selectOption", "selectOptionFromDropdown"}

    for dangerous in ("click", "doubleClick", "press", "dragAndDrop", "hover", "scrollTo"):
        action = FieldAction(selector="#x", method=dangerous, arguments=["%value%"])
        assert not is_fillable(action), f"{dangerous} must never be replayable"


def test_press_enter_is_named_nowhere():
    """press_enter existed for one caller, the server tier's login form. That
    tier is retired (glass-box spec, open decision 3), so no module of the app
    may name it: a new one would be a control-activation primitive, which is
    a design change this test should make someone argue for."""
    import pathlib

    portals = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals"
    for path in portals.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert "press_enter" not in source, path.name


def test_no_module_reaches_a_browser_page_to_click():
    """The retired engine held a Stagehand Page, which has click(), type() and
    key_press() on it. Nothing in the app drives a browser now; the extension
    types in the student's own tab, and the student clicks."""
    import pathlib

    portals = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portals"
    for path in portals.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for reach in (".page.", "page.click(", "page.key_press("):
            assert reach not in source, f"{path.name}: {reach}"


def test_nothing_in_the_app_can_submit():
    """The platform never submits. Superseded in FORM, not in substance, by the
    2026-09-15 glass-box decision 10: the student presses Submit in their own
    session and the server RECORDS that they did, so the guard is on the ACT
    and no longer on the word.

    The act itself is banned by the tests above: FILL_METHODS is an allowlist,
    press_enter is named nowhere, and no module reaches a browser page to
    click. Those are what stop an application being submitted by us; this test
    never could, because a string ban cannot see a FieldAction(method="click")
    either.

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

