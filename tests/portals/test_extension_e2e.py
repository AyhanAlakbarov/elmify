"""The extension, driven by a real Chromium against fixture portal pages.

Skipped locally when the bundle or the browser is absent; FAILS under CI for a
missing bundle, for the reason test_extension_bundle.py gives.

Synchronous Playwright API on purpose -- no pytest-asyncio dependency, and the
same shape tests/portals/test_engine_browser.py already uses.

Playwright, not patchright: patchright left the dependency tree with Scrapling
(see pyproject's `playwright` entry), so `from patchright...` skipped every test
here locally and `uv run patchright install` failed the `extension` CI job
outright. Nothing about the extension needed patchright's stealth patches -- the
browser here drives our own fixture pages.
"""

import json
import os
import pathlib
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
DIST = pathlib.Path(__file__).resolve().parents[2] / "extension" / "dist"


@pytest.fixture
def fixture_server():
    handler = partial(SimpleHTTPRequestHandler, directory=str(FIXTURES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def browser_context(tmp_path):
    if not (DIST / "manifest.json").exists():
        message = (
            "extension/dist is missing -- npm --prefix extension ci "
            "&& npm --prefix extension run build"
        )
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed")

    with sync_playwright() as playwright:
        # An ordinary headless browser, NOT --load-extension. Every test below
        # injects content.js itself, so loading the packed extension would buy
        # nothing and cost a headed browser (extensions do not load in old
        # headless) plus an X server on the CI runner. The limitation that
        # creates is stated at the end of task 13 and must stay stated.
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        yield context
        context.close()
        browser.close()


def _verify_in_page(page, entries):
    """Run the bundle's verification against this page and return its verdicts.

    The bundle is injected as a plain script and the check is called directly:
    the pairing and packet round-trips are covered by tests/portals/
    test_ext_api.py, and mixing them in here would make a failure ambiguous.
    """
    page.add_script_tag(path=str(DIST / "content.js"))
    # No `isolated_context` argument, and none is needed: that was patchright's
    # own extension to `evaluate()`, which defaults to a separate JS world for
    # stealth. Vanilla Playwright evaluates in the MAIN world already, which is
    # where content.js's hooks live -- see the docstring above. Passing the
    # keyword here is a TypeError, not a no-op.
    return page.evaluate(
        "(entries) => window.__tehsil_verify(entries)", entries
    )


@pytest.mark.extension
def test_a_plain_form_fills(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    verdicts = _verify_in_page(
        page,
        [
            {
                "selector": "#gn",
                "method": "fill",
                "value": "Leyla",
                "profile_field": "personal.given_name",
            },
            {
                "selector": "#fn",
                "method": "fill",
                "value": "Aliyeva",
                "profile_field": "personal.family_name",
            },
        ],
    )
    assert [item["ok"] for item in verdicts] == [True, True]

    # Verify alone is a read; prove the values actually land too.
    page.evaluate(
        "(entries) => window.__tehsil_fill(entries)",
        [
            {
                "selector": "#gn",
                "method": "fill",
                "value": "Leyla",
                "profile_field": "personal.given_name",
            },
            {
                "selector": "#fn",
                "method": "fill",
                "value": "Aliyeva",
                "profile_field": "personal.family_name",
            },
        ],
    )
    assert page.input_value("#gn") == "Leyla"
    assert page.input_value("#fn") == "Aliyeva"


@pytest.mark.extension
def test_a_mislabelled_control_is_refused_not_typed_into(browser_context, fixture_server) -> None:
    """The hostile-snapshot case, and the one no server-side check can catch.

    #gn exists, is visible and is enabled. It asks for a passport number. A map
    aiming the given name at it is exactly what a crafted snapshot produces,
    and read-back would verify it clean.
    """
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/mislabelled_form.html")
    verdicts = _verify_in_page(
        page,
        [
            {
                "selector": "#gn",
                "method": "fill",
                "value": "Leyla",
                "profile_field": "personal.given_name",
            }
        ],
    )
    assert verdicts[0]["ok"] is False
    assert verdicts[0]["reason"] == "name_mismatch"
    # The verdict alone proves nothing about behaviour: _verify_in_page never
    # writes to the DOM, so an empty #gn above is trivially true regardless of
    # what fillVerified would do. Actually attempt the fill through the same
    # __tehsil_fill path test_nothing_the_extension_does_submits_the_form
    # uses -- fillVerified(verifyEntries(entries), new Set()) -- so this
    # exercises the real refusal, not just the read that reports it.
    page.evaluate(
        "(entries) => window.__tehsil_fill(entries)",
        [
            {
                "selector": "#gn",
                "method": "fill",
                "value": "Leyla",
                "profile_field": "personal.given_name",
            }
        ],
    )
    assert page.input_value("#gn") == ""


@pytest.mark.extension
def test_a_hidden_or_disabled_control_is_refused(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/hidden_field_form.html")
    verdicts = _verify_in_page(
        page,
        [
            {
                "selector": "#gn",
                "method": "fill",
                "value": "Leyla",
                "profile_field": "personal.given_name",
            },
            {
                "selector": "#fn",
                "method": "fill",
                "value": "Aliyeva",
                "profile_field": "personal.family_name",
            },
        ],
    )
    assert [item["reason"] for item in verdicts] == ["hidden", "disabled"]


@pytest.mark.extension
def test_a_missing_selector_is_refused(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    verdicts = _verify_in_page(
        page,
        [
            {
                "selector": "#nope",
                "method": "fill",
                "value": "Leyla",
                "profile_field": "personal.given_name",
            }
        ],
    )
    assert verdicts[0]["reason"] == "no_such_control"


@pytest.mark.extension
def test_a_challenge_page_is_detected(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/challenge.html")
    page.add_script_tag(path=str(DIST / "content.js"))
    assert (
        page.evaluate("() => window.__tehsil_detect_challenge()")["kind"]
        == "recaptcha"
    )


@pytest.mark.extension
def test_a_snapshot_of_a_filled_form_carries_no_value(browser_context, fixture_server) -> None:
    """The definitive form of "the snapshot carries no value".

    The page is filled first, so every control HAS a value to leak. A key-level
    assertion on the built snapshot cannot be fooled by a rename, where a text
    scan of the bundle both misses renames and trips over the legitimate
    element.value reads in fill and read-back.
    """
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.fill("#gn", "Leyla")
    page.fill("#em", "leyla@example.org")
    page.add_script_tag(path=str(DIST / "content.js"))
    snapshot = page.evaluate("() => window.__tehsil_snapshot()")

    assert snapshot["controls"], "the snapshot found no controls"
    for control in snapshot["controls"]:
        assert "value" not in control, control
    assert "Leyla" not in json.dumps(snapshot)
    assert "leyla@example.org" not in json.dumps(snapshot)


@pytest.mark.extension
def test_nothing_the_extension_does_submits_the_form(browser_context, fixture_server) -> None:
    """The spec's hardest guarantee, measured rather than scanned.

    The page records any submit; a full verify-and-fill must leave it unset.
    """
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.evaluate(
        "() => { window.__submitted = false; "
        "document.forms[0].addEventListener('submit', () => { window.__submitted = true; }); }"
    )
    page.add_script_tag(path=str(DIST / "content.js"))
    # __tehsil_fill takes the raw entries and verifies them itself
    # (fillVerified(verifyEntries(entries), ...)) -- it is not fed
    # __tehsil_verify's output, which is the {profile_field, ok, reason}
    # projection and carries neither a selector nor a value to type.
    page.evaluate(
        "(entries) => window.__tehsil_fill(entries)",
        [
            {
                "selector": "#gn",
                "method": "fill",
                "value": "Leyla",
                "profile_field": "personal.given_name",
            }
        ],
    )
    assert page.input_value("#gn") == "Leyla"
    assert page.evaluate("() => window.__submitted") is False


@pytest.mark.extension
def test_each_document_finds_its_own_upload_slot(browser_context, fixture_server) -> None:
    """The matcher must look at WHICH document it is placing.

    It did not: the predicate tested every input for cv/resume/curriculum and
    ignored the document entirely, so whichever file the packet listed first
    took the CV slot -- a transcript included. Nothing misfires in production
    today, because packets.py::_kit_documents filters to Kind.CV and every
    packet document is therefore a CV. This pins the behaviour before the
    second kind that docstring promises arrives.

    The transcript is listed FIRST on purpose: under the old predicate it is
    the file that ended up in the CV input.
    """
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/two_upload_slots.html")
    page.add_script_tag(path=str(DIST / "content.js"))

    result = page.evaluate(
        """() => window.__tehsil_attach([
             {filename: "transcript-2026.pdf", bytes: new ArrayBuffer(8)},
             {filename: "cv-standard.pdf", bytes: new ArrayBuffer(8)},
           ])""",
    )
    assert result["manual"] == []

    landed = page.evaluate(
        """() => Array.from(document.querySelectorAll("input[type=file]"))
             .map((input) => [input.id, input.files.length ? input.files[0].name : ""])""",
    )
    assert dict(landed) == {"cv": "cv-standard.pdf", "transcript": "transcript-2026.pdf"}


@pytest.mark.extension
def test_a_document_with_no_matching_slot_is_left_to_the_student(
    browser_context, fixture_server
) -> None:
    """No match, no guess -- the dock tells the student where to put it rather
    than the extension choosing a slot for them."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/two_upload_slots.html")
    page.add_script_tag(path=str(DIST / "content.js"))

    result = page.evaluate(
        """() => window.__tehsil_attach([
             {filename: "passport-scan.pdf", bytes: new ArrayBuffer(8)},
           ])""",
    )

    assert result["attached"] == []
    assert result["manual"] == ["passport-scan.pdf"]


def _run_with_stubbed_messaging(page, replies):
    """Drive the real run() with chrome.runtime.sendMessage stubbed.

    Returns every message the run sent, in order. The bundle is injected as a
    plain script, so there is no `chrome` at all until this puts one there --
    which is what makes the messages assertable instead of mocked away inside
    the extension.
    """
    page.evaluate(
        """(replies) => {
            window.__sent = [];
            window.chrome = {
              runtime: {
                sendMessage: async (message) => {
                  window.__sent.push(message);
                  return replies[message.type] ?? { ok: true };
                },
              },
            };
        }""",
        replies,
    )
    page.add_script_tag(path=str(DIST / "content.js"))
    page.evaluate("() => window.__tehsil_run('app-1', 'form-1')")
    return page.evaluate("() => window.__sent")


@pytest.mark.extension
def test_a_first_encounter_snapshot_is_never_posted_from_the_wrong_page(
    browser_context, fixture_server
) -> None:
    """The origin check runs BEFORE the form is described to the server.

    On the no_field_map path there is no packet, so form_url has to come from
    the refusal itself. Until it did, a snapshot of whatever page the student
    was standing on was posted and learned from. A snapshot carries no value,
    so the loss is a FieldMap aimed at the wrong controls -- for every student
    in the tenant, since a learned map is shared within it.
    """
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")

    sent = _run_with_stubbed_messaging(
        page,
        {"packet": {"ok": False, "code": "no_field_map", "form_url": "https://elsewhere.example/apply"}},
    )

    kinds = [message["type"] for message in sent]
    assert "snapshot" not in kinds
    assert kinds[-1] == "dock"
    assert sent[-1]["patch"]["message"] == "wrong_page"


@pytest.mark.extension
def test_a_first_encounter_snapshot_is_posted_when_the_page_is_the_right_one(
    browser_context, fixture_server
) -> None:
    """The positive control. Without it the test above passes just as well
    against a run() that never snapshots anything at all."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")

    sent = _run_with_stubbed_messaging(
        page,
        {
            "packet": {"ok": False, "code": "no_field_map", "form_url": fixture_server},
            "snapshot": {"ok": False, "code": "unmapped_fields"},
        },
    )

    kinds = [message["type"] for message in sent]
    assert "snapshot" in kinds
    assert sent[kinds.index("snapshot")]["portalFormId"] == "form-1"


@pytest.mark.extension
def test_a_refusal_with_no_form_url_refuses_rather_than_guessing(
    browser_context, fixture_server
) -> None:
    """A server too old to name the page cannot tell us what we are looking
    at, and guessing is exactly the behaviour this check replaces."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")

    sent = _run_with_stubbed_messaging(
        page, {"packet": {"ok": False, "code": "no_field_map"}}
    )

    assert "snapshot" not in [message["type"] for message in sent]
    assert sent[-1]["patch"]["message"] == "wrong_page"


TAGGED = "leyla.apply+ab12cd@outlook.com"
PLAIN = "leyla.apply@outlook.com"


def _email_packet(form_url):
    """A packet whose one entry is the portal address (apps/portals/tags.py)."""
    return {
        "ok": True,
        "packet": {
            "application_id": "app-1",
            "portal_form_id": "form-1",
            "field_map_version": 1,
            "form_url": form_url,
            "entries": [
                {
                    "selector": "#em",
                    "method": "fill",
                    "value": TAGGED,
                    "profile_field": "contact.email",
                }
            ],
            "documents": [],
            "issued_at": "2026-09-27T10:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "min_extension_version": "0.1.0",
            "confirmation_markers": None,
            "plain_email": PLAIN,
        },
    }


def _of_type(sent, kind):
    return [message for message in sent if message["type"] == kind]


@pytest.mark.extension
def test_a_form_that_refuses_the_tag_gets_the_plain_address(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/tag_rejecting_form.html")

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == PLAIN
    [report] = _of_type(sent, "address")
    assert (report["event"], report["evidence"]) == ("rejected", "form")
    [read_back] = [m for m in _of_type(sent, "event") if m["kind"] == "READ_BACK"]
    assert read_back["detail"]["mismatches"] == []


@pytest.mark.extension
def test_a_form_that_keeps_the_tag_reports_the_registration(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == TAGGED
    [report] = _of_type(sent, "address")
    assert report["event"] == "given"


@pytest.mark.extension
def test_a_rejection_after_submit_swaps_the_address_and_never_submits(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/tag_rejected_after_submit.html")
    page.evaluate(
        "() => { window.__submitted = false; "
        "document.forms[0].addEventListener('submit', () => { window.__submitted = true; }); }"
    )

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == PLAIN
    [report] = _of_type(sent, "address")
    assert (report["event"], report["evidence"]) == ("rejected", "after_submit")
    assert "Submit the form again yourself" in sent[-1]["patch"]["message"]
    assert page.evaluate("() => window.__submitted") is False


@pytest.mark.extension
def test_an_error_the_plain_address_also_gets_is_not_blamed_on_the_tag(
    browser_context, fixture_server
) -> None:
    """Both addresses refused: the "+" is not the reason, so nothing is
    reported -- a report here would mark the portal REJECTS for everyone."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/email_only_one_address.html")

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == TAGGED
    assert _of_type(sent, "address") == []


@pytest.mark.extension
def test_the_plain_address_button_types_it_and_says_it_was_the_student(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    page.evaluate("() => window.__tehsil_use_plain()")
    sent = page.evaluate("() => window.__sent")

    assert page.input_value("#em") == PLAIN
    assert (sent[-2]["event"], sent[-2]["evidence"]) == ("rejected", "student")


@pytest.mark.extension
def test_a_stale_error_a_slow_validator_clears_is_not_blamed_on_the_tag(
    browser_context, fixture_server
) -> None:
    """Review I1: the tagged read caught an error left over from an earlier
    submit, the plain read caught the page's late re-validation. Retyping the
    tagged address shows the page accepts it, so nothing is reported and the
    tagged value stays."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/slow_validator_stale_error.html")

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == TAGGED
    assert [m for m in _of_type(sent, "address") if m["event"] == "rejected"] == []
    assert "tagged address" not in sent[-1]["patch"]["message"]


@pytest.mark.extension
@pytest.mark.parametrize(
    "fixture", ["unrelated_password_error.html", "bootstrap_hidden_feedback.html"]
)
def test_an_error_not_tied_to_the_email_control_is_not_a_tag_rejection(
    browser_context, fixture_server, fixture
) -> None:
    """Review I2: another field's alert in a flat form, and a feedback element
    hidden by CSS, are not the page refusing the tagged address."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/{fixture}")

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == TAGGED
    assert _of_type(sent, "address") == []
    assert "tagged address" not in sent[-1]["patch"]["message"]


@pytest.mark.extension
def test_a_refusal_only_the_page_s_script_makes_is_account_only_evidence(
    browser_context, fixture_server
) -> None:
    """Review I3: a duplicate-account check refuses this tagged string, not the
    "+". The plain address still goes in, but the report says `page` -- only
    the browser's own validity verdict may say `form`."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/duplicate_account_check.html")

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == PLAIN
    [report] = _of_type(sent, "address")
    assert (report["event"], report["evidence"]) == ("rejected", "page")


@pytest.mark.extension
@pytest.mark.parametrize("change", ["__rerender", "__lock"])
def test_the_plain_address_button_says_so_when_it_could_not_type(
    browser_context, fixture_server, change
) -> None:
    """Review M3: the control was replaced, or refused the write. The student is
    told we could not type it, and nothing is reported."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/email_rerendered.html")
    _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})
    page.evaluate(f"() => window.{change}()")

    page.evaluate("() => window.__tehsil_use_plain()")
    sent = page.evaluate("() => window.__sent")

    assert page.input_value("#em") != PLAIN
    assert [m for m in _of_type(sent, "address") if m["event"] == "rejected"] == []
    assert "could not type" in sent[-1]["patch"]["message"]


@pytest.mark.extension
def test_a_banner_outside_the_form_is_not_mistaken_for_the_control_s_error(
    browser_context, fixture_server
) -> None:
    """Fix round 2, finding 1: email is the only real control on the page, so
    nothing ever blocked the tied-error search from climbing past the form.
    Fresh page: the banner used to be counted, `looksRejected` came back true
    for both the tagged and the plain address, and the run gave up as
    `unclear` -- losing the `given` registration entirely."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/site_banner_outside_form.html")

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == TAGGED
    [report] = _of_type(sent, "address")
    assert report["event"] == "given"


@pytest.mark.extension
def test_a_banner_outside_the_form_does_not_swap_a_returned_page(
    browser_context, fixture_server
) -> None:
    """Fix round 2, finding 1, the returned-page half: the page already holds
    the tagged address (as a portal's own returned page would), and the same
    banner used to make `cameBackRejected` true before anything was typed,
    swapping in the plain address and reporting a false `after_submit`."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/site_banner_outside_form.html")
    page.fill("#em", TAGGED)

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == TAGGED
    assert [m for m in _of_type(sent, "address") if m["event"] == "rejected"] == []
    assert "Submit the form again" not in sent[-1]["patch"]["message"]


@pytest.mark.extension
def test_the_plain_address_button_does_not_report_a_write_a_late_revert_undid(
    browser_context, fixture_server
) -> None:
    """Fix round 2, finding 2: the page reverts the write one tick later
    (Vue's nextTick, a setTimeout(0)). A read-back that runs synchronously,
    right after the retype, passes before the revert fires and reports a swap
    that did not hold."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_address_reverts_later.html")
    _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})
    page.evaluate("() => window.__revert_writes_later()")

    page.evaluate("() => window.__tehsil_use_plain()")
    sent = page.evaluate("() => window.__sent")

    assert page.input_value("#em") == TAGGED
    assert [m for m in _of_type(sent, "address") if m["event"] == "rejected"] == []
    assert "could not type" in sent[-1]["patch"]["message"]


def _open_panel(browser_context):
    """The real dock bundle, with a stub `chrome` that records what it sends.

    The panel is an extension page, so it is loaded from dist/ as a file rather
    than served; the stub is installed before panel.js runs. Clicking here is
    the TEST pressing the student's button -- the no-click rule binds the
    extension's own bundles, which test_no_code_path_clicks scans.
    """
    page = browser_context.new_page()
    page.add_init_script(
        """
        window.__sent = [];
        window.__listeners = [];
        window.chrome = {
          runtime: {
            sendMessage: async (message) => { window.__sent.push(message); },
            onMessage: { addListener: (listener) => window.__listeners.push(listener) },
          },
          tabs: {
            query: async () => [{ id: 7 }],
            sendMessage: async (tabId, message) => { window.__sent.push({ tabId, ...message }); },
          },
        };
        """
    )
    page.goto((DIST / "panel.html").as_uri())
    return page


def _push_state(page, state):
    page.evaluate(
        "(state) => window.__listeners.forEach((listener) => "
        "listener({ type: 'dock:state', state }))",
        state,
    )


@pytest.mark.extension
def test_the_dock_asks_about_the_registration_email_only_when_told_to(browser_context) -> None:
    page = _open_panel(browser_context)
    assert page.is_hidden("#registration")

    _push_state(
        page,
        {
            "registration": {
                "applicationId": "app-1",
                "portalHost": "apply.example.edu",
                "address": TAGGED,
            }
        },
    )

    assert page.is_visible("#registration")
    assert "apply.example.edu" in page.inner_text("#registration-question")
    assert TAGGED in page.inner_text("#arrived-tagged")


@pytest.mark.extension
def test_the_student_s_answer_carries_the_sender_they_typed(browser_context) -> None:
    page = _open_panel(browser_context)
    _push_state(
        page,
        {"registration": {"applicationId": "app-1", "portalHost": "x.edu", "address": TAGGED}},
    )

    page.fill("#sender", " noreply@mail-eu.portalvendor.com ")
    page.click("#arrived-plain")

    answer = page.evaluate("() => window.__sent.at(-1)")
    assert answer == {
        "type": "registration:answer",
        "applicationId": "app-1",
        "arrived": "plain",
        "sender": "noreply@mail-eu.portalvendor.com",
    }


@pytest.mark.extension
def test_use_my_plain_address_goes_to_the_portal_tab(browser_context) -> None:
    page = _open_panel(browser_context)

    page.click("#use-plain")

    assert page.evaluate("() => window.__sent.at(-1)") == {
        "tabId": 7,
        "type": "use_plain_address",
    }


# --- Fix round 1: M4 ---------------------------------------------------------


@pytest.mark.extension
def test_the_registration_question_hides_after_the_student_answers(browser_context) -> None:
    """render() must react to the worker's own patch, not just to the click:
    the worker is what actually clears `registration` once the answer round-
    trips (service_worker.ts's patchDock({registration: null, ...}))."""
    page = _open_panel(browser_context)
    _push_state(
        page,
        {"registration": {"applicationId": "app-1", "portalHost": "x.edu", "address": TAGGED}},
    )
    assert page.is_visible("#registration")

    page.click("#arrived-none")
    _push_state(page, {"registration": None})

    assert page.is_hidden("#registration")


@pytest.mark.extension
def test_the_registration_question_hides_whenever_state_returns_to_none(browser_context) -> None:
    """Not only after an answer: a `no_registration` refresh (fix round 1,
    M2) clears the question the same way, with no click in between."""
    page = _open_panel(browser_context)
    _push_state(
        page,
        {"registration": {"applicationId": "app-1", "portalHost": "x.edu", "address": TAGGED}},
    )
    assert page.is_visible("#registration")

    _push_state(page, {"registration": None})

    assert page.is_hidden("#registration")


APP_A = "11111111-1111-4111-8111-111111111111"
APP_B = "22222222-2222-4222-8222-222222222222"


def _load_worker(browser_context, dock, responses):
    """The real service_worker.js, run in a page against a stub `chrome`.

    `dock` is the stored dock state; `responses` maps "METHOD /path" to
    [status, body] for the stubbed fetch. The worker is an IIFE bundle, so it
    runs as a plain script; the stub records every listener it registers so
    the test can fire an alarm or deliver a message exactly as Chrome would.
    """
    page = browser_context.new_page()
    page.evaluate(
        """([dock, responses]) => {
            const listeners = (name) => ({
              addListener: (fn) => { (window.__on[name] ??= []).push(fn); },
            });
            const area = (store) => ({
              get: async (key) => {
                const keys = key == null ? Object.keys(store) : [].concat(key);
                return Object.fromEntries(keys.filter((k) => k in store).map((k) => [k, store[k]]));
              },
              set: async (items) => { Object.assign(store, items); },
              remove: async (key) => { [].concat(key).forEach((k) => delete store[k]); },
              clear: async () => { Object.keys(store).forEach((k) => delete store[k]); },
            });
            window.__on = {};
            window.__session = { dock };
            window.fetch = async (url, init) => {
              const key = `${(init && init.method) || "GET"} ${new URL(url).pathname}`;
              const [status, body] = responses[key] ?? [404, { error: "not_found" }];
              return new Response(status === 204 ? null : JSON.stringify(body), { status });
            };
            window.chrome = {
              action: { onClicked: listeners("action") },
              alarms: { create: async () => {}, onAlarm: listeners("alarm") },
              runtime: {
                getURL: (path) => `chrome-extension://tehsil/${path}`,
                getManifest: () => ({ version: "0.1.0" }),
                sendMessage: async () => {},
                onMessage: listeners("message"),
              },
              storage: {
                local: area({ device_token: "t", origin: "https://dash.example" }),
                session: area(window.__session),
              },
              tabs: {
                onActivated: listeners("tab"), get: async () => ({}), create: async () => {},
              },
            };
        }""",
        [dock, responses],
    )
    page.add_script_tag(path=str(DIST / "service_worker.js"))
    return page


def _registration_shown(page):
    return page.evaluate("() => window.__session.dock.registration ?? null")


def _fire_alarm(page, application_id):
    page.evaluate(
        "(id) => Promise.all(window.__on.alarm.map((fn) => fn({ name: `registration:${id}` })))",
        application_id,
    )


def _answer_from_dock(page, application_id, arrived):
    return page.evaluate(
        """([id, arrived]) => new Promise((resolve) => window.__on.message[0](
            { type: "registration:answer", applicationId: id, arrived },
            { url: "chrome-extension://tehsil/panel.html" },
            resolve,
        ))""",
        [application_id, arrived],
    )


def _question(application_id):
    return {"applicationId": application_id, "portalHost": "x.edu", "address": TAGGED}


@pytest.mark.extension
@pytest.mark.parametrize("state", ["done", "none", "waiting"])
def test_the_alarm_clears_a_question_the_server_no_longer_asks(browser_context, state) -> None:
    """M1 (final review): GET /registration answers 200 with state none/done,
    never 409, so a question already on screen is cleared on any state but
    `ask` -- the old no_registration branch never ran."""
    page = _load_worker(
        browser_context,
        {"registration": _question(APP_A)},
        {
            "POST /ext/mailbox/check": [204, None],
            f"GET /ext/applications/{APP_A}/registration": [200, {"state": state}],
        },
    )

    _fire_alarm(page, APP_A)

    assert _registration_shown(page) is None


@pytest.mark.extension
def test_the_alarm_leaves_another_application_s_question_alone(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"registration": _question(APP_B)},
        {
            "POST /ext/mailbox/check": [204, None],
            f"GET /ext/applications/{APP_A}/registration": [200, {"state": "done"}],
        },
    )

    _fire_alarm(page, APP_A)

    assert _registration_shown(page) == _question(APP_B)


@pytest.mark.extension
def test_an_answer_the_server_no_longer_wants_clears_the_question(browser_context) -> None:
    """M1: the student pressed "use my plain address" after the question went
    up, so the account is untagged and the answer POST is 409 no_registration.
    The question goes; it used to stay on screen forever."""
    page = _load_worker(
        browser_context,
        {"registration": _question(APP_A)},
        {f"POST /ext/applications/{APP_A}/registration": [409, {"error": "no_registration"}]},
    )

    reply = _answer_from_dock(page, APP_A, "tagged")

    assert reply == {"ok": False, "code": "no_registration"}
    assert _registration_shown(page) is None


@pytest.mark.extension
def test_a_failed_answer_keeps_the_question(browser_context) -> None:
    """Negative control for the test above: any other failure keeps the
    question up so the student can answer again."""
    page = _load_worker(
        browser_context,
        {"registration": _question(APP_A)},
        {f"POST /ext/applications/{APP_A}/registration": [429, {"error": "rate_limited"}]},
    )

    _answer_from_dock(page, APP_A, "tagged")

    assert _registration_shown(page) == _question(APP_A)
