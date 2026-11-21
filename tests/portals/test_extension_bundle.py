"""Static checks on the built extension.

These read the BUILT bundle, not the sources: what ships is what Chrome runs,
and a rule enforced only in TypeScript is a rule a later build step can drop.

Locally the bundle may be absent -- `npm --prefix extension ci && npm --prefix
extension run build` builds it. Under CI a missing bundle is a FAILURE and
never a skip: this repository has already shipped one job that went green
having measured nothing (the retired portal-sandbox job, which a CI=true
could turn into a skip), and a skipping security check is that failure again.
"""

import json
import os
import pathlib
import re

import pytest

DIST = pathlib.Path(__file__).resolve().parents[2] / "extension" / "dist"


def bundle_text(name: str) -> str:
    """The built bundle's source, or a skip/failure per the rule above."""
    path = DIST / name
    if not path.exists():
        message = (
            f"{path} is missing -- run: npm --prefix extension ci "
            "&& npm --prefix extension run build"
        )
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    return path.read_text(encoding="utf-8")


def test_the_three_bundles_are_built() -> None:
    for name in ("service_worker.js", "content.js", "panel.js"):
        assert bundle_text(name).strip(), f"{name} is empty"


def test_the_manifest_is_v3_and_declares_no_content_script() -> None:
    """A declared content script runs on every matching page forever.

    This extension injects into the portal tab on a user gesture instead, so
    the manifest must carry no `content_scripts` key at all and no non-optional
    host permission.
    """
    manifest = json.loads(bundle_text("manifest.json"))
    assert manifest["manifest_version"] == 3
    assert "content_scripts" not in manifest
    assert manifest.get("host_permissions", []) == []
    assert manifest["optional_host_permissions"] == ["https://*/*"]


def test_the_device_token_never_reaches_a_portal_page() -> None:
    """The token lives in the worker's storage and in its Authorization header.

    The content bundle is what runs inside a portal page's tab. If the string
    that reads the token appears there at all, the token is one message reply
    away from a page that can log it.
    """
    content = bundle_text("content.js")
    assert "device_token" not in content
    assert "Authorization" not in content


def test_the_token_is_stored_outside_session_storage() -> None:
    """Pairing survives a browser restart; a packet does not.

    storage.local for the token, storage.session for the packet. Getting these
    the wrong way round either re-pairs the student every morning or leaves
    verified facts on disk.
    """
    worker = bundle_text("service_worker.js")
    assert "storage.local" in worker
    assert "storage.session" in worker


def test_the_manifest_version_is_at_least_the_packet_floor() -> None:
    """A shipped build older than MIN_EXTENSION_VERSION refuses every packet.

    Both numbers are edited by hand in two files. Pinning them together is the
    only thing that stops a release that cannot fill anything.
    """
    from apps.portals.packets import MIN_EXTENSION_VERSION

    manifest = json.loads(bundle_text("manifest.json"))
    built = tuple(int(part) for part in manifest["version"].split("."))
    floor = tuple(int(part) for part in MIN_EXTENSION_VERSION.split("."))
    assert built >= floor, f"manifest {manifest['version']} < packet floor {MIN_EXTENSION_VERSION}"


def test_the_snapshot_keys_match_the_server_schema() -> None:
    """extra='forbid' means an invented key is a 400 nobody can debug from the
    portal side. Both lists are short; pin them to each other."""
    from apps.portals.snapshot import SnapshotControl

    content = bundle_text("content.js")
    for field in SnapshotControl.model_fields:
        assert f"{field}:" in content.replace(" ", ""), f"snapshot never sets {field}"


def test_the_content_script_refuses_before_it_types() -> None:
    """The whole point of the check is its ORDER.

    Verification that ran after the fill would be a report, not a guard. The
    built bundle must contain the refusal reasons, and the e2e fixtures in
    test_extension_e2e.py prove the ordering against a real page.
    """
    content = bundle_text("content.js")
    for reason in ("no_such_control", "not_unique", "hidden", "disabled", "name_mismatch"):
        assert reason in content, f"the verification check has no {reason} refusal"


def test_the_content_script_types_only_the_allowed_methods() -> None:
    """The spec's allowlist parity test.

    The content script's set of DOM-mutating operations must equal the
    server's FILL_METHODS plus setFiles (task 9's document attachment, which is
    never a stored field-map method -- see this plan's Global Constraints).
    """
    from apps.portals.session import FILL_METHODS

    content = bundle_text("content.js")
    for method in FILL_METHODS:
        assert f'"{method}"' in content, f"the content script does not know {method}"
    # The inverse: nothing beyond the allowlist plus setFiles. Stagehand's
    # takeDeterministicAction dispatched sixteen; these are the ones whose
    # presence here would mean the port grew them back.
    for banned in ("doubleClick", "dragAndDrop", "scrollTo", "press"):
        assert banned not in content, f"the content script can {banned}"


def test_no_code_path_clicks() -> None:
    """The student presses every button. This is the spec's hardest line.

    A static scan of the built bundle, not of the sources: what ships is what
    Chrome runs. `.click(` catches element.click(); MouseEvent and
    requestSubmit catch the two ways to fake one.
    """
    for name in ("content.js", "service_worker.js"):
        text = bundle_text(name).replace(" ", "")
        for banned in (".click(", "MouseEvent", "PointerEvent", "requestSubmit", ".submit("):
            assert banned not in text, f"{name} contains {banned}"


def test_the_extension_reports_only_kinds_the_server_accepts() -> None:
    """ext_api rejects an unknown kind with 400 and no explanation the student
    can act on. Both lists are short; pin them."""
    from apps.portals.ext_api import _EVENT_KINDS

    content = bundle_text("content.js") + bundle_text("service_worker.js")
    reported = {kind for kind in _EVENT_KINDS if f'"{kind}"' in content}
    assert "FILL" in reported and "READ_BACK" in reported
    # Nothing outside the server's set.
    for forbidden in ("PACKET", "ESCALATION", "RECOVERY"):
        assert f'"{forbidden}"' not in content, f"the extension writes {forbidden} rows"


def test_the_worker_branches_only_on_action_kinds_the_server_can_send() -> None:
    """A kind the server never emits is a branch nothing reaches.

    Measured 2026-09-18: the worker tested `action.kind === "OPEN_LINK"`, which
    is not one of DeviceAction.Kind's four values, so the auto-open branch was
    dead -- every verification link fell through to a dock message instead of
    opening, which is the owner's decision 5 silently not happening. Nothing
    failed, nothing logged, and no test could see it. This is that test.
    """
    from apps.portals.models import DeviceAction

    worker = bundle_text("service_worker.js")
    kinds = {kind.value for kind in DeviceAction.Kind}
    assert f'"{DeviceAction.Kind.OPEN_VERIFICATION_URL.value}"' in worker, (
        "the worker does not recognise the one kind it is supposed to act on"
    )
    # The inverse. These are the plausible inventions: a quoted ALL-CAPS string
    # the worker compares a kind against, that the server can never produce.
    for invented in ("OPEN_LINK", "OPEN_URL", "NAVIGATE", "VERIFY_URL"):
        assert invented not in kinds
        assert f'"{invented}"' not in worker, f"the worker branches on {invented}"


def test_a_queued_link_is_scheme_checked_before_it_becomes_a_tab() -> None:
    """The payload is text a third party wrote.

    Plan 4 fills this table from email bodies, so an unchecked `javascript:`
    payload would become a tab in the student's own browser. A static check is
    weak -- it proves the string is present, not that it guards the call -- but
    a service worker cannot be driven from pytest, and the alternative was
    nothing.
    """
    worker = bundle_text("service_worker.js")
    assert "tabs.create" in worker
    assert '"https:"' in worker, "no scheme check before opening a queued link"


def test_the_challenge_markers_match_the_server_s() -> None:
    """Ported, not reinvented. A marker the extension does not know is a
    challenge the student is not told about."""
    from apps.portals.challenge import MARKERS

    content = bundle_text("content.js")
    for _kind, container, _attribute, _response in MARKERS:
        assert container in content, f"the content script does not know {container}"


def test_setfiles_is_the_content_script_s_own_vocabulary() -> None:
    """The spec's allowlist parity: FILL_METHODS | {"setFiles"}.

    setFiles must NOT be in the server's FILL_METHODS -- a file-writing method
    in a stored, tenant-shared field map is a method a hostile snapshot can
    aim. The content script finds file inputs itself.
    """
    from apps.portals.session import FILL_METHODS

    assert "setFiles" not in FILL_METHODS
    assert "setFiles" in bundle_text("content.js")


def test_the_extension_polls_actions_on_a_bounded_schedule() -> None:
    """ext_api caps this at 120/hour per membership. A poller without its own
    interval discovers that cap at a student's deadline."""
    worker = bundle_text("service_worker.js")
    assert "/ext/actions" in worker
    assert "setInterval" not in worker, (
        "a service worker is unloaded; setInterval does not survive it"
    )


def test_the_panel_is_the_only_dom_owner_and_is_marked_for_handover() -> None:
    """One module owns the dock's DOM, so replacing the design replaces one
    file. The marker is what tells the next session not to design it.

    content/ is excluded on purpose: it writes to the PORTAL's DOM, which is
    its whole job. This asserts nothing else builds the DOCK's.
    """
    panel = pathlib.Path(__file__).resolve().parents[2] / "extension" / "src" / "panel" / "panel.ts"
    assert "SHOULD BE DONE BY AYKHAN" in panel.read_text(encoding="utf-8")
    # No other source file builds the dock's DOM.
    src = pathlib.Path(__file__).resolve().parents[2] / "extension" / "src"
    for path in src.rglob("*.ts"):
        if path.parent.name == "panel" or path.parent.name == "content":
            continue
        assert "createElement" not in path.read_text(encoding="utf-8"), path


def test_the_registration_check_survives_the_worker_being_unloaded() -> None:
    """The dock asks about the registration email minutes later. A service
    worker is unloaded when idle, so the wait must be a chrome.alarms alarm --
    declared in the manifest -- and never a timer that dies with the worker."""
    manifest = json.loads(bundle_text("manifest.json"))
    worker = bundle_text("service_worker.js")
    assert "alarms" in manifest["permissions"]
    assert "alarms.create" in worker and "onAlarm" in worker
    assert "/registration" in worker and "/ext/mailbox/check" in worker


def test_the_address_report_uses_only_the_server_s_evidence_words() -> None:
    """ext_api refuses an evidence word it does not know with a 400 the student
    never sees. Pin the extension's words to the server's."""
    from apps.portals.ext_api import _REJECTION_EVIDENCE

    content = bundle_text("content.js")
    for evidence in _REJECTION_EVIDENCE:
        assert f'"{evidence}"' in content, f"the content script never reports {evidence}"


# --- Fix round 1 ------------------------------------------------------------
#
# The worker cannot be driven from pytest (test_extension_e2e.py's
# browser_context never loads it with --load-extension, by design -- see that
# file's own docstring). So, as for every other worker-only rule this suite
# pins (setInterval, the scheme check on a queued link), these are static
# checks on the built text: the most direct test this harness allows for
# service-worker-only logic.


def test_registration_answer_is_refused_from_anywhere_but_the_dock() -> None:
    """I1: a compromised portal renderer runs as a content script too, and
    could otherwise post a KEEPS verdict or teach the server a sender for an
    account it does not own. Only the side panel -- which carries no
    sender.tab and whose sender.url is our own panel.html -- may answer."""
    worker = bundle_text("service_worker.js")
    assert 'getURL("panel.html")' in worker
    assert "sender.tab" in worker and "sender.url" in worker


def test_address_reports_are_refused_from_anywhere_but_a_content_script() -> None:
    """I1's mirror: only a content script witnessed anything on a page, so
    only one may report it -- never the dock, which holds no tab."""
    worker = bundle_text("service_worker.js")
    assert '"untrusted_sender"' in worker


def test_applicationid_is_checked_as_a_uuid_before_it_reaches_a_url_path() -> None:
    """M1: applicationId is interpolated, unescaped, into every id-addressed
    route's path (api.ts). A crafted string such as "../actions/<id>/result"
    would otherwise widen an id-addressed call into an unrelated route,
    carried on the device's own token. One check, at the message boundary."""
    worker = bundle_text("service_worker.js")
    assert '"invalid_message"' in worker
    assert "0-9a-f" in worker, "no UUID pattern guards applicationId"


def test_the_worker_checks_a_closed_vocabulary_for_event_evidence_and_arrived() -> None:
    """M1: event, evidence and arrived are each a closed set on the server
    (ext_api.py's _AddressReport / _RegistrationAnswer); the worker must
    refuse a value outside it before any handler trusts it."""
    from apps.portals.ext_api import _REJECTION_EVIDENCE

    worker = bundle_text("service_worker.js")
    assert '"given"' in worker and '"rejected"' in worker
    for evidence in _REJECTION_EVIDENCE:
        assert f'"{evidence}"' in worker, f"the worker never checks evidence {evidence}"
    for arrived in ("tagged", "plain", "none"):
        assert f'"{arrived}"' in worker, f"the worker never checks arrived {arrived}"


def test_the_alarm_tells_the_dock_when_pairing_is_missing() -> None:
    """M2: pairing_required used to return before any dock message, leaving
    the student staring at nothing. Show the same code every other case in
    this file already surfaces as a dock message."""
    worker = bundle_text("service_worker.js")
    assert 'message: "pairing_required"' not in worker
    assert "Connect this browser to your dashboard first." in worker


def test_the_marks_layer_is_closed_unclickable_and_unmarked_in_production():
    content = bundle_text("content.js")
    assert 'mode: "closed"' in content or 'mode:"closed"' in content
    assert "pointer-events" in content and "none" in content
    assert "data-elmify-marks" not in content  # test-build only


# --- Task 6: start from the dashboard, follow each page ---------------------


def test_the_worker_injects_content_only_into_a_bound_tab_on_its_own_origin():
    """Bench mode (plan 6) is the one other injection: operator only, the
    active tab, the chosen form's origin."""
    worker = bundle_text("service_worker.js")
    assert 'files: ["content.js"]' in worker or 'files:["content.js"]' in worker
    assert "bindings" in worker and "onUpdated" in worker
    # the origin check sits with the re-injection
    assert re.search(r"onUpdated[\s\S]{0,800}origin", worker)


def test_start_and_stop_are_accepted_only_from_the_dock():
    worker = bundle_text("service_worker.js")
    for kind in ("start-fill", "stop-fill", "language"):
        assert re.search(rf'"{kind}"[\s\S]{{0,300}}fromDock', worker), kind


def test_only_the_panel_asks_for_the_portal_s_host_permission():
    """The user gesture lives in the panel's Start click. The worker's one
    permissions.request is the toolbar click on the dashboard (pairing)."""
    worker = bundle_text("service_worker.js")
    panel = bundle_text("panel.js")
    assert worker.count("permissions.request") == 1
    assert "permissions.request" in panel


def test_the_content_script_sends_codes_not_english_sentences():
    """Final review I2: the panel translates codes; a sentence reaches an
    az/tr/ru student in English."""
    content = bundle_text("content.js")
    for sentence in ("portal's own button", "prove you are human", "confirmed it received"):
        assert sentence not in content, sentence


# --- Security + ponytail fix wave ---------------------------------------------


def test_content_scripts_are_locked_out_of_storage_local():
    """S1: storage.local holds the device token, and a content script can read
    it unless the worker sets the access level, at load, before any injection."""
    worker = bundle_text("service_worker.js")
    assert "setAccessLevel" in worker and "TRUSTED_CONTEXTS" in worker
    content = bundle_text("content.js")
    assert "chrome.storage" not in content and "storage.local" not in content
    manifest = json.loads(bundle_text("manifest.json"))
    # sidePanel.open (and setAccessLevel, 102) need this; older Chrome ignores the lock.
    assert int(manifest["minimum_chrome_version"]) >= 116


def test_a_choice_is_answered_only_from_the_dock_and_attached_only_by_content() -> None:
    worker = bundle_text("service_worker.js")
    assert re.search(r'"choice:answer"[\s\S]{0,300}fromDock', worker)
    assert '"choice:attach"' in bundle_text("content.js")


def test_uploads_are_fetched_with_the_token_and_without_cookies() -> None:
    worker = bundle_text("service_worker.js").replace(" ", "")
    assert re.search(r'"/ext/"[\s\S]{0,400}fetchDocument', worker)
    assert re.search(r'fetchDocument[\s\S]{0,400}credentials:"omit"', worker)


def test_answers_leave_only_on_the_dock_s_review_press_and_only_from_a_bound_tab() -> None:
    """The answers channel's one trigger is "I have checked this page" in our
    panel: the worker takes review:open only from the dock, the content script
    sends answers only from that message, and an answers message is a content
    type, so contentRefusal binds it to its tab and its application."""
    worker = bundle_text("service_worker.js")
    assert re.search(r'"review:open"[\s\S]{0,300}fromDock', worker)
    assert re.search(r'CONTENT_TYPES = [^\]]*new Set\(\[[^\]]*"answers"', worker)
    content = bundle_text("content.js")
    assert re.search(r'"review:open"[^;]{0,40}sendAnswers\(\)', content)
    assert content.count('type: "answers"') == 1


def test_bench_messages_are_accepted_only_from_the_dock() -> None:
    worker = bundle_text("service_worker.js")
    for kind in ("bench:hello", "bench:record"):
        assert re.search(rf'"{kind}"[\s\S]{{0,300}}fromDock', worker), kind


def test_a_bench_recording_is_checked_against_the_page_s_own_origin() -> None:
    """The tab may navigate during the worker's awaits; the content script's
    own location.origin is compared before anything is posted."""
    assert re.search(r'"record"[\s\S]{0,400}location\.origin', bundle_text("content.js"))
    worker = bundle_text("service_worker.js")
    assert re.search(r'\.origin\)\)?\s*throw new ExtError\(409,\s*"wrong_page"\)', worker)


def test_unpair_hands_back_the_bench_grants() -> None:
    worker = bundle_text("service_worker.js")
    assert re.search(r'"unpair"[\s\S]{0,600}forgetBenchOrigins', worker)
    assert re.search(r"bench_origins[\s\S]{0,600}permissions\.remove", worker)
