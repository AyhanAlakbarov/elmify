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
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
DIST = pathlib.Path(__file__).resolve().parents[2] / "extension" / "dist-test"


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
            "extension/dist-test is missing -- npm --prefix extension ci "
            "&& npm --prefix extension run build:test"
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
        "(entries) => window.__elmify_verify(entries)", entries
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
        "(entries) => window.__elmify_fill(entries)",
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
    # __elmify_fill path test_nothing_the_extension_does_submits_the_form
    # uses -- fillVerified(verifyEntries(entries), new Set()) -- so this
    # exercises the real refusal, not just the read that reports it.
    page.evaluate(
        "(entries) => window.__elmify_fill(entries)",
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
def test_certificate_keys_match_only_their_own_boxes(browser_context, fixture_server) -> None:
    """Spec 2026-10-12 §4.3: "Test date" must not also read as the test name, and
    "Overall band score" is the overall score."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/certificate_form.html")
    entry = lambda selector, field, value: {  # noqa: E731
        "selector": selector, "method": "fill", "value": value, "profile_field": field,
    }
    entries = [
        entry("#tn", "language.0.test_name", "IELTS"),
        entry("#td", "language.0.test_date", "2025-11-08"),
        entry("#os", "language.0.test_score", "7.0"),
    ]
    assert [v["ok"] for v in _verify_in_page(page, entries)] == [True, True, True]
    swapped = [entry("#td", "language.0.test_name", "IELTS")]
    assert _verify_in_page(page, swapped)[0]["reason"] == "name_mismatch"


_CERTIFICATE_FIELDS = [
    "language.0.language", "language.0.test_variant", "language.0.cefr_level",
    "language.0.score_listening", "language.0.score_reading", "language.0.score_writing",
    "language.0.score_speaking",
]


@pytest.mark.extension
def test_bare_common_labels_match_no_certificate_key(browser_context, fixture_server) -> None:
    """Bare words ("Level of study", "Module", a Europass "Listening" column) must
    fail closed; only certificate phrases match."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/certificate_labels.html")

    def verdict(selector, field):
        entry = {"selector": selector, "method": "fill", "value": "x", "profile_field": field}
        return _verify_in_page(page, [entry])[0]["ok"]

    for selector in ("#a", "#b", "#c", "#d", "#e"):
        assert not any(verdict(selector, f) for f in _CERTIFICATE_FIELDS), selector
    assert verdict("#f", "language.0.score_listening")
    assert verdict("#g", "language.0.cefr_level")
    assert verdict("#h", "language.0.language")


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
        page.evaluate("() => window.__elmify_detect_challenge()")["kind"]
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
    snapshot = page.evaluate("() => window.__elmify_snapshot()")

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
    # __elmify_fill takes the raw entries and verifies them itself
    # (fillVerified(verifyEntries(entries), ...)) -- it is not fed
    # __elmify_verify's output, which is the {profile_field, ok, reason}
    # projection and carries neither a selector nor a value to type.
    page.evaluate(
        "(entries) => window.__elmify_fill(entries)",
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
        """() => window.__elmify_attach([
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
        """() => window.__elmify_attach([
             {filename: "passport-scan.pdf", bytes: new ArrayBuffer(8)},
           ])""",
    )

    assert result["attached"] == []
    assert result["manual"] == ["passport-scan.pdf"]


def _attach_docs(page, docs):
    page.add_script_tag(path=str(DIST / "content.js"))
    return page.evaluate(
        "(docs) => window.__elmify_attach("
        "docs.map((d) => ({...d, bytes: new ArrayBuffer(4)})))",
        docs,
    )


def _landed(page):
    return page.evaluate(
        """() => Array.from(document.querySelectorAll("input[type=file]"))
             .map((i) => [i.id, i.files.length ? i.files[0].name + "|" + i.files[0].type : ""])"""
    )


@pytest.mark.extension
def test_a_prepared_image_lands_with_its_real_type(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/kind_upload_slots.html")
    result = _attach_docs(
        page,
        [
            {
                "filename": "aliyev_passport.jpg",
                "type": "image/jpeg",
                "kind": "PASSPORT",
            }
        ],
    )
    assert result["manual"] == []
    assert dict(_landed(page))["passport"] == "aliyev_passport.jpg|image/jpeg"


@pytest.mark.extension
def test_a_renamed_document_still_lands_by_kind(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/kind_upload_slots.html")
    _attach_docs(
        page,
        [{"filename": "Aysel_Memmedova.pdf", "type": "application/pdf", "kind": "CV"}],
    )
    assert dict(_landed(page))["cv"] == "Aysel_Memmedova.pdf|application/pdf"


@pytest.mark.extension
def test_a_hidden_passport_box_never_receives_a_passport(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/hidden_passport_input.html")
    result = _attach_docs(
        page,
        [{"filename": "passport.pdf", "type": "application/pdf", "kind": "PASSPORT"}],
    )
    assert result["attached"] == []
    assert result["manual"] == ["passport.pdf"]
    assert dict(_landed(page))["hidden_passport"] == ""


def _boxes(*labels):
    return "<form>" + "".join(
        f'<label for="b{i}">{label}</label><input type="file" id="b{i}">'
        for i, label in enumerate(labels)
    ) + "</form>"


def _doc(kind, name=None):
    return {"filename": name or f"{kind.lower()}.pdf", "type": "application/pdf", "kind": kind}


@pytest.mark.extension
@pytest.mark.parametrize("flip", [False, True])
def test_documents_find_their_own_box_in_either_packet_order(browser_context, flip) -> None:
    page = browser_context.new_page()
    page.set_content(_boxes("Language certificate", "Degree certificate"))
    docs = [_doc("DIPLOMA"), _doc("LANGUAGE_CERTIFICATE")]
    result = _attach_docs(page, docs[::-1] if flip else docs)
    assert result["manual"] == []
    assert dict(_landed(page)) == {
        "b0": "language_certificate.pdf|application/pdf",
        "b1": "diploma.pdf|application/pdf",
    }


@pytest.mark.extension
@pytest.mark.parametrize("label", ["Bank statement", "Recommendation letter"])
def test_a_lookalike_box_never_receives_the_motivation_letter(browser_context, label) -> None:
    page = browser_context.new_page()
    page.set_content(_boxes(label))
    result = _attach_docs(page, [_doc("MOTIVATION_LETTER")])
    assert result["attached"] == []
    assert result["manual"] == ["motivation_letter.pdf"]


@pytest.mark.extension
def test_the_bundle_needs_exactly_one_visible_box(browser_context) -> None:
    page = browser_context.new_page()
    page.set_content(_boxes("Application form", "CV"))
    result = _attach_docs(page, [_doc("EVERY_DOCUMENT")])
    assert result["attached"] == []
    assert result["manual"] == ["every_document.pdf"]
    page2 = browser_context.new_page()
    page2.set_content(_boxes("Upload here"))
    result = _attach_docs(page2, [_doc("EVERY_DOCUMENT")])
    assert [a["filename"] for a in result["attached"]] == ["every_document.pdf"]


@pytest.mark.extension
def test_a_note_is_told_in_the_students_language(browser_context) -> None:
    page = _open_panel(browser_context)
    page.select_option("#language", "en")
    _push_state(
        page,
        {"documents": [{"filename": "diploma.pdf", "state": "attached", "note": "signed"}]},
    )
    text = page.locator("#documents").inner_text()
    assert "diploma.pdf" in text
    assert "digitally signed" in text
    page.select_option("#language", "ru")
    assert "цифровую подпись" in page.locator("#documents").inner_text()
    _push_state(
        page,
        {"documents": [{"filename": "x.pdf", "state": "attached", "note": "from_the_future"}]},
    )
    shown = page.locator("#documents").inner_text()
    assert "from_the_future" not in shown
    assert "Мы не смогли полностью подготовить этот файл" in shown


def _attach(page, names):
    page.add_script_tag(path=str(DIST / "content.js"))
    return page.evaluate(
        "(names) => window.__elmify_attach("
        "names.map((n) => ({filename: n, bytes: new ArrayBuffer(4)})))",
        names,
    )


@pytest.mark.extension
def test_a_hidden_upload_box_never_receives_a_document(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/hidden_upload_trap.html")
    result = _attach(page, ["cv.pdf", "transcript.pdf"])
    assert [a["filename"] for a in result["attached"]] == ["cv.pdf"]
    assert result["manual"] == ["transcript.pdf"]


@pytest.mark.extension
def test_a_styled_upload_button_still_gets_its_document(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/styled_upload_button.html")
    result = _attach(page, ["transcript.pdf"])
    assert [a["filename"] for a in result["attached"]] == ["transcript.pdf"]


@pytest.mark.extension
@pytest.mark.parametrize(
    "fixture",
    [
        "offscreen_upload_label",
        "faded_upload_label",
        "covered_upload_label",
        "wrapping_label_two_inputs",
    ],
)
def test_an_unseeable_opener_does_not_receive_a_document(
    browser_context, fixture_server, fixture
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/{fixture}.html")
    result = _attach(page, ["transcript.pdf"])
    assert result["attached"] == []
    assert result["manual"] == ["transcript.pdf"]


@pytest.mark.extension
def test_text_the_student_cannot_see_does_not_name_the_slot(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/hidden_text_in_label.html")
    result = _attach(page, ["transcript.pdf"])
    assert result["attached"] == []
    assert result["manual"] == ["transcript.pdf"]


@pytest.mark.extension
@pytest.mark.parametrize("fixture", ["hidden_input_aria_label", "visible_input_faded_label"])
def test_text_nobody_can_read_does_not_name_the_slot_either(
    browser_context, fixture_server, fixture
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/{fixture}.html")
    result = _attach(page, ["transcript.pdf"])
    assert result["attached"] == []
    assert result["manual"] == ["transcript.pdf"]


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
    page.evaluate("() => window.__elmify_run('app-1', 'form-1')")
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
    assert sent[-1]["patch"]["message"] == "swapped_plain"
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
    assert sent[-1]["patch"]["message"] == "submit_again"
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

    page.evaluate("() => window.__elmify_use_plain()")
    sent = page.evaluate("() => window.__sent")

    assert page.input_value("#em") == PLAIN
    assert (sent[-2]["event"], sent[-2]["evidence"]) == ("rejected", "student")
    assert sent[-1]["patch"]["message"] == "plain_typed"


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
    assert sent[-1]["patch"]["message"] == "check_submit"


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
    assert sent[-1]["patch"]["message"] == "check_submit"


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

    page.evaluate("() => window.__elmify_use_plain()")
    sent = page.evaluate("() => window.__sent")

    assert page.input_value("#em") != PLAIN
    assert [m for m in _of_type(sent, "address") if m["event"] == "rejected"] == []
    assert sent[-1]["patch"]["message"] == "plain_not_typed"


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
    assert sent[-1]["patch"]["message"] == "check_submit"


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

    page.evaluate("() => window.__elmify_use_plain()")
    sent = page.evaluate("() => window.__sent")

    assert page.input_value("#em") == TAGGED
    assert [m for m in _of_type(sent, "address") if m["event"] == "rejected"] == []
    assert sent[-1]["patch"]["message"] == "plain_not_typed"


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
        window.__permissions = [];
        window.__ports = [];
        window.chrome = {
          runtime: {
            sendMessage: async (message) => { window.__sent.push(message); return window.__reply; },
            onMessage: { addListener: (listener) => window.__listeners.push(listener) },
            connect: ({ name }) => {
              window.__ports.push(name);
              return {
                postMessage: () => {},
                onDisconnect: { addListener: () => {} },
              };
            },
          },
          permissions: {
            request: async (request) => {
              window.__permissions.push(request);
              return window.__grant ?? true;
            },
          },
          i18n: { getUILanguage: () => "az-AZ" },
          storage: { local: {
            get: async (key) => ({ ...(window.__stored ?? {}) }),
            set: async (items) => { window.__stored = { ...(window.__stored ?? {}), ...items }; },
          } },
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

    answer = page.evaluate(
        "() => window.__sent.filter((m) => !['language', 'dock:hello'].includes(m.type)).at(-1)"
    )
    assert answer == {
        "type": "registration:answer",
        "applicationId": "app-1",
        "arrived": "plain",
        "sender": "noreply@mail-eu.portalvendor.com",
    }


@pytest.mark.extension
def test_use_my_plain_address_goes_to_the_portal_tab(browser_context) -> None:
    """M4: the bound tab, not whichever tab is active (the stub's is 7)."""
    page = _open_panel(browser_context)
    _push_state(page, {"binding": {"tabId": 9, "origin": PORTAL}})

    page.click("#use-plain")
    page.wait_for_function("() => window.__sent.some((m) => m.tabId !== undefined)")

    last = page.evaluate(
        "() => window.__sent.filter((m) => !['language', 'dock:hello'].includes(m.type)).at(-1)"
    )
    assert last == {
        "tabId": 9,
        "type": "use_plain_address",
    }


@pytest.mark.extension
def test_use_my_plain_address_with_no_portal_tab_sends_nothing(browser_context) -> None:
    page = _open_panel(browser_context)
    page.click("#use-plain")
    page.wait_for_timeout(200)
    assert not any("tabId" in m for m in page.evaluate("() => window.__sent"))


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


@pytest.mark.extension
def test_the_panel_defaults_to_the_browser_language_and_can_switch(browser_context) -> None:
    page = _open_panel(browser_context)
    _push_state(
        page,
        {
            "status": "filling",
            "fields": [
                {"key": "personal.given_name", "state": "filled", "reason": "", "placed": True}
            ],
        },
    )
    assert page.locator("#language").input_value() == "az"
    assert "Ad — " not in page.locator("#fields").inner_text()  # label only, no reason
    assert page.locator("#fields li").first.inner_text() == "Ad"

    page.select_option("#language", "en")

    assert "Given name" in page.locator("#fields").inner_text()
    assert {"type": "language", "lang": "en"} in page.evaluate("() => window.__sent")
    assert page.evaluate("() => window.__stored") == {"language": "en"}


@pytest.mark.extension
def test_the_review_says_the_owner_s_words(browser_context) -> None:
    page = _open_panel(browser_context)
    page.select_option("#language", "en")
    _push_state(page, {"status": "review", "fields": []})

    assert (
        "Check every field and document. When you are sure everything is correct, "
        "press Next / Submit yourself. We never press it for you."
    ) in page.locator("#review").inner_text()


@pytest.mark.extension
def test_a_portal_error_is_shown_as_text_and_marked_as_the_student_s_own(browser_context) -> None:
    page = _open_panel(browser_context)
    page.select_option("#language", "en")
    _push_state(
        page,
        {
            "fields": [
                {
                    "key": "personal.email",
                    "state": "portal_error",
                    "reason": "portal:<b>Invalid</b> email",
                    "placed": True,
                    "theirs": True,
                },
                {
                    "key": "personal.mystery_thing",
                    "state": "your_turn",
                    "reason": "hidden",
                    "placed": False,
                },
            ],
            "documents": [{"filename": "cv.pdf", "state": "attached"}],
        },
    )

    fields = page.locator("#fields")
    assert "Your value — the portal says: <b>Invalid</b> email" in fields.inner_text()
    assert page.locator("#fields b").count() == 0
    assert "mystery thing — The field is hidden" in fields.inner_text()
    assert "cv.pdf" in page.locator("#documents").inner_text()


@pytest.mark.extension
def test_the_field_list_shows_no_raw_keys_or_reason_codes(browser_context) -> None:
    page = _open_panel(browser_context)
    _push_state(
        page,
        {
            "fields": [
                {"key": "personal.given_name", "state": "filled", "reason": "", "placed": True},
                {"key": "personal.email", "state": "your_turn", "reason": "hidden", "placed": True},
                {"key": "personal.phone", "state": "mismatch", "reason": "", "placed": True},
            ],
        },
    )
    text = page.locator("#dock").inner_text()
    assert "personal." not in text
    assert "hidden" not in text
    assert "Telefon" in text
    assert page.evaluate("() => document.documentElement.lang") == "az"
    sent = page.evaluate("() => window.__sent")
    assert {"type": "language", "lang": "az"} in sent


@pytest.mark.extension
def test_every_panel_string_exists_in_all_four_languages(browser_context) -> None:
    page = _open_panel(browser_context)
    table = page.evaluate("() => window.__elmify_strings")

    assert set(table) == {"az", "tr", "ru", "en"}
    keys = set(table["en"])
    for lang, strings in table.items():
        assert set(strings) == keys, lang
        assert all(value.strip() for value in strings.values()), lang
        placeholders = {k: sorted(re.findall(r"\{\w+\}", v)) for k, v in strings.items()}
        assert placeholders == {
            k: sorted(re.findall(r"\{\w+\}", v)) for k, v in table["en"].items()
        }, lang


APP_A = "11111111-1111-4111-8111-111111111111"
APP_B = "22222222-2222-4222-8222-222222222222"


def _load_worker(browser_context, dock, responses, session=None, tabs=None, hold_lock=False):
    """The real service_worker.js, run in a page against a stub `chrome`.

    `dock` is the stored dock state; `responses` maps "METHOD /path" to
    [status, body] for the stubbed fetch. The worker is an IIFE bundle, so it
    runs as a plain script; the stub records every listener it registers so
    the test can fire an alarm or deliver a message exactly as Chrome would.
    `session` adds keys to storage.session (e.g. "bindings"); `tabs` maps a
    tab id to what chrome.tabs.get returns for it. Every tab, scripting and
    side-panel call is recorded in window.__calls as [name, args].
    `hold_lock` keeps storage.local.setAccessLevel pending until the test
    calls window.__unlock().
    """
    page = browser_context.new_page()
    page.evaluate(
        """([dock, responses, session, tabs, holdLock]) => {
            window.__calls = [];
            window.__fetched = [];
            window.__tabs = tabs;
            const record = (name, result) => async (...args) => {
              window.__calls.push([name, args]);
              return result;
            };
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
            window.__session = { dock, ...session };
            window.fetch = async (url, init) => {
              const key = `${(init && init.method) || "GET"} ${new URL(url).pathname}`;
              window.__fetched.push([key, init && init.body ? JSON.parse(init.body) : null]);
              const [status, body, headers] = responses[key] ?? [404, { error: "not_found" }];
              const text = status === 204 ? null : JSON.stringify(body);
              return new Response(text, { status, headers });
            };
            window.chrome = {
              action: { onClicked: listeners("action") },
              alarms: {
                create: record("alarms.create"),
                clear: record("alarms.clear", true),
                onAlarm: listeners("alarm"),
              },
              runtime: {
                getURL: (path) => `chrome-extension://elmify/${path}`,
                getManifest: () => ({ version: "0.1.0" }),
                sendMessage: async () => {},
                onMessage: listeners("message"),
                onConnect: listeners("connect"),
              },
              scripting: { executeScript: record("executeScript", []) },
              sidePanel: {
                setOptions: record("sidePanel.setOptions"),
                open: record("sidePanel.open"),
              },
              permissions: {
                remove: record("permissions.remove", true),
                request: record("permissions.request", true),
              },
              storage: {
                local: {
                  ...area({ device_token: "t", origin: "https://dash.example" }),
                  setAccessLevel: async (...args) => {
                    window.__calls.push(["storage.local.setAccessLevel", args]);
                    if (holdLock) await new Promise((resolve) => { window.__unlock = resolve; });
                  },
                },
                session: area(window.__session),
              },
              tabs: {
                onActivated: listeners("tab"),
                onUpdated: listeners("updated"),
                onRemoved: listeners("removed"),
                get: async (id) => window.__tabs[id] ?? {},
                create: async (...args) => {
                  window.__calls.push(["tabs.create", args]);
                  return window.__created ?? { id: 7 };
                },
                sendMessage: record("tabs.sendMessage"),
              },
            };
        }""",
        [
            dock,
            responses,
            session or {},
            {str(k): v for k, v in (tabs or {}).items()},
            hold_lock,
        ],
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
            { url: "chrome-extension://elmify/panel.html" },
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


def _plain_packet(form_url, extra=()):
    """given/family name entries against plain_form.html's #gn / #fn."""
    packet = _email_packet(form_url)
    packet["packet"]["entries"] = [
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
        *extra,
    ]
    packet["packet"]["plain_email"] = ""
    return packet


def _two_page_packet(form_url):
    return _plain_packet(
        form_url,
        extra=[{
            "selector": "#ph",
            "method": "fill",
            "value": "+994501234567",
            "profile_field": "contact.phone",
        }],
    )


def _dock_fields(sent):
    docks = [m["patch"] for m in sent if m.get("type") == "dock"]
    patches = [p for p in docks if "fields" in p]
    return {f["key"]: f for f in patches[-1]["fields"]}


@pytest.mark.extension
def test_a_value_already_on_the_page_is_never_typed_over_and_needs_a_check(
    browser_context, fixture_server
) -> None:
    """I5 (controller ruling): a differing value found at fill time is not
    "changed by you" -- nobody saw the student type it. It is amber "Check
    this" (mismatch / held_other), never retyped, and it needs the student."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/prefilled_by_student.html")
    sent = _run_with_stubbed_messaging(page, {"packet": _plain_packet(fixture_server)})
    assert page.input_value("#gn") == "Aysel M."
    fields = _dock_fields(sent)
    given = fields["personal.given_name"]
    assert (given["state"], given["reason"]) == ("mismatch", "held_other")
    assert fields["personal.family_name"]["state"] == "filled"
    marks = {m["key"]: m["state"] for m in page.evaluate("() => window.__elmify_marks()")}
    assert marks["personal.given_name"] == "mismatch"


@pytest.mark.extension
def test_fields_of_another_page_are_elsewhere_not_your_turn(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/two_page_form_page2.html")
    sent = _run_with_stubbed_messaging(page, {"packet": _two_page_packet(fixture_server)})
    fields = _dock_fields(sent)
    assert fields["personal.given_name"]["state"] == "elsewhere"
    assert fields["contact.phone"]["state"] == "filled"
    assert not any(f["state"] == "your_turn" for f in fields.values())


@pytest.mark.extension
def test_a_student_edit_after_our_fill_is_reported_as_theirs(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    _run_with_stubbed_messaging(page, {"packet": _plain_packet(fixture_server)})
    page.fill("#gn", "Aysel")  # the TEST types as the student (trusted input events)
    sent = page.evaluate("() => window.__sent")
    assert _dock_fields(sent)["personal.given_name"]["state"] == "changed_by_you"


@pytest.mark.extension
def test_a_held_value_is_not_a_read_back_mismatch(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/prefilled_by_student.html")
    sent = _run_with_stubbed_messaging(page, {"packet": _plain_packet(fixture_server)})
    [read_back] = [m for m in _of_type(sent, "event") if m["kind"] == "READ_BACK"]
    assert read_back["detail"]["mismatches"] == []
    final = [m["patch"] for m in sent if m.get("type") == "dock" and "message" in m["patch"]][-1]
    # no READ_BACK mismatch, so no consultant escalation: the only check is the held value
    assert all(
        f["reason"] == "held_other" for f in final["fields"] if f["state"] == "mismatch"
    )
    assert final["status"] == "blocked"  # but the student must check it


@pytest.mark.extension
def test_a_select_on_its_placeholder_is_filled(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/select_placeholder.html")
    packet = _plain_packet(fixture_server)
    packet["packet"]["entries"] = [
        {
            "selector": "#co",
            "method": "selectOption",
            "value": "AZ",
            "profile_field": "personal.country",
        }
    ]
    sent = _run_with_stubbed_messaging(page, {"packet": packet})
    assert page.input_value("#co") == "AZ"
    assert _dock_fields(sent)["personal.country"]["state"] == "filled"


@pytest.mark.extension
@pytest.mark.parametrize("slash", ["", "/"])  # "/apply" and "/apply/" are one page
def test_a_wrong_selector_on_the_forms_own_page_is_not_elsewhere(
    browser_context, fixture_server, slash
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    packet = _plain_packet(
        f"{fixture_server}/plain_form.html{slash}",
        extra=[
            {
                "selector": "#nope",
                "method": "fill",
                "value": "x",
                "profile_field": "contact.phone",
            }
        ],
    )
    sent = _run_with_stubbed_messaging(page, {"packet": packet})
    field = _dock_fields(sent)["contact.phone"]
    assert (field["state"], field["reason"]) == ("your_turn", "not_found")


@pytest.mark.extension
def test_marks_sit_beside_filled_fields_and_ignore_the_page_css(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/hostile_css_form.html")
    url = f"{fixture_server}/hostile_css_form.html"
    _run_with_stubbed_messaging(page, {"packet": _plain_packet(url)})
    marks = {m["key"]: m for m in page.evaluate("() => window.__elmify_marks()")}
    assert marks["personal.given_name"]["state"] == "filled"
    assert marks["personal.given_name"]["placed"]
    assert marks["personal.given_name"]["rect"]["h"] >= 12  # not shrunk to the page's 4px
    host = page.evaluate(
        "() => { const h = document.querySelector('[data-elmify-marks]');"
        " return h && { open: !!h.shadowRoot, pe: getComputedStyle(h).pointerEvents }; }"
    )
    assert host == {"open": False, "pe": "none"}  # closed root, never clickable


@pytest.mark.extension
def test_a_page_that_keeps_removing_the_marks_falls_back_to_the_panel(
    browser_context, fixture_server
):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/rerender_form.html")
    url = f"{fixture_server}/rerender_form.html"
    _run_with_stubbed_messaging(page, {"packet": _plain_packet(url)})
    page.wait_for_timeout(1200)
    marks = page.evaluate("() => window.__elmify_marks()")
    assert all(not m["placed"] for m in marks)
    sent = page.evaluate("() => window.__sent")
    assert all(not f["placed"] for f in _dock_fields(sent).values())


@pytest.mark.extension
def test_a_mark_carries_no_student_value(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    _run_with_stubbed_messaging(
        page, {"packet": _plain_packet(f"{fixture_server}/plain_form.html")}
    )
    text = page.evaluate("() => window.__elmify_marks_text()")
    assert text.strip()
    assert "Leyla" not in text and "Aliyeva" not in text


@pytest.mark.extension
def test_the_portal_s_own_error_turns_the_field_red_with_its_text(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/portal_error_form.html")
    sent = _run_with_stubbed_messaging(
        page, {"packet": _plain_packet(f"{fixture_server}/portal_error_form.html")}
    )
    fields = _dock_fields(sent)
    assert fields["personal.family_name"]["state"] == "portal_error"
    assert fields["personal.family_name"]["reason"] == "portal:Ungültiger Nachname"
    assert fields["personal.given_name"]["state"] == "filled"
    # an error that appears later (in-page validation) is picked up too
    page.evaluate(
        """() => { const e = document.getElementById('gn');
          e.setAttribute('aria-invalid','true'); e.setAttribute('aria-describedby','g');
          const s = document.createElement('span'); s.id='g'; s.textContent='Required';
          document.body.append(s); }"""
    )
    page.wait_for_timeout(500)
    later = _dock_fields(page.evaluate("() => window.__sent"))
    assert later["personal.given_name"]["reason"] == "portal:Required"


@pytest.mark.extension
def test_error_lookalikes_do_not_turn_a_clean_field_red(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/portal_error_traps.html"
    page.goto(url)
    packet = _plain_packet(url)
    packet["packet"]["entries"].append(
        {"selector": "#em", "method": "fill", "value": "a@b.az", "profile_field": "contact.email"}
    )
    sent = _run_with_stubbed_messaging(page, {"packet": packet})
    fields = _dock_fields(sent)
    # a: next sibling is a wrapper holding another control; hint class is not an error
    assert fields["personal.given_name"]["state"] != "portal_error"
    assert fields["contact.email"]["state"] != "portal_error"


@pytest.mark.extension
def test_aria_error_targets_are_chosen_by_the_rules(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/portal_error_aria.html"
    page.goto(url)
    packet = _plain_packet(url)
    packet["packet"]["entries"].append(
        {"selector": "#em", "method": "fill", "value": "a@b.az", "profile_field": "contact.email"}
    )
    fields = _dock_fields(_run_with_stubbed_messaging(page, {"packet": packet}))
    assert fields["personal.given_name"]["reason"] == "portal:Zu kurz"  # not the plain hint
    assert fields["personal.family_name"]["reason"] == "portal:Pflichtfeld"  # errormessage only
    assert fields["contact.email"]["reason"] == "portal:Ungueltig"  # empty errormessage ignored


# --- Task 6: start from the dashboard, follow each page, stop, review --------

PORTAL = "https://portal.example"
DASHBOARD = "https://dash.example"
FORM_ID = "33333333-3333-4333-8333-333333333333"
ACTION_ID = "44444444-4444-4444-8444-444444444444"
PANEL_SENDER = {"url": "chrome-extension://elmify/panel.html"}
TAB_SENDER = {"tab": {"id": 7}, "url": f"{PORTAL}/apply"}
INJECT_7 = [{"target": {"tabId": 7}, "files": ["content.js"]}]
# What a content script in the bound tab's top frame looks like to the worker.
# sender.origin is set by the browser from the frame's real origin.
CONTENT = {"tab": {"id": 7}, "frameId": 0, "origin": PORTAL, "url": f"{PORTAL}/apply"}


def _start_message(language, resume=False):
    return {
        "type": "start",
        "applicationId": APP_A,
        "portalFormId": FORM_ID,
        "language": language,
        "origin": PORTAL,
        "resume": resume,
    }


def _binding(active=True, tab_id=7):
    return {
        "bindings": {
            str(tab_id): {
                "tabId": tab_id,
                "applicationId": APP_A,
                "portalFormId": FORM_ID,
                "origin": PORTAL,
                "active": active,
                "pages": [],
            }
        }
    }


def _calls(page, name):
    return page.evaluate(
        "(name) => window.__calls.filter((c) => c[0] === name).map((c) => c[1])", name
    )


def _send(page, message, sender):
    return page.evaluate(
        """([message, sender]) => new Promise((resolve) => {
            const keep = window.__on.message[0](message, sender, resolve);
            if (!keep) resolve(undefined);
        })""",
        [message, sender],
    )


def _connect_dock(page):
    page.evaluate(
        """(sender) => {
            const port = {
              name: "dock", sender,
              onDisconnect: { addListener: (fn) => { port.disconnect = fn; } },
              onMessage: { addListener: () => {} },
            };
            window.__port = port;
            return Promise.all(window.__on.connect.map((fn) => fn(port)));
        }""",
        PANEL_SENDER,
    )


def _page_loaded(page, tab_id, url):
    page.evaluate(
        """([id, url]) => Promise.all(
            window.__on.updated.map((fn) => fn(id, { status: "complete" }, { id, url })))""",
        [tab_id, url],
    )


def _start_fill_responses(packet_reply):
    return {
        "GET /ext/actions": [
            200,
            {
                "actions": [
                    {
                        "id": ACTION_ID,
                        "kind": "START_FILL",
                        "application_id": APP_A,
                        "payload": {},
                        "expires_at": "2099-01-01T00:00:00Z",
                    }
                ]
            },
        ],
        f"GET /ext/applications/{APP_A}/packet": packet_reply,
        f"POST /ext/actions/{ACTION_ID}/result": [200, {"completed": True}],
    }


def _portal_packet(form_url=f"{PORTAL}/apply"):
    packet = _email_packet(form_url)["packet"]
    packet.update(application_id=APP_A, portal_form_id=FORM_ID)
    return packet


@pytest.mark.extension
@pytest.mark.parametrize(
    ("trigger", "packet_reply"),
    [
        ("activated", [200, _portal_packet()]),
        # First encounter: no map yet. The 424 still names the form and its id.
        (
            "reloaded",
            [
                424,
                {
                    "error": "no_field_map",
                    "form_url": f"{PORTAL}/apply",
                    "portal_form_id": FORM_ID,
                },
            ],
        ),
    ],
)
def test_a_start_fill_action_opens_the_portal_tab_and_binds_it(
    browser_context, trigger, packet_reply
) -> None:
    page = _load_worker(
        browser_context,
        {"language": "tr"},
        _start_fill_responses(packet_reply),
        tabs={1: {"id": 1, "url": f"{DASHBOARD}/dashboard/"}},
    )

    if trigger == "activated":
        page.evaluate("() => Promise.all(window.__on.tab.map((fn) => fn({ tabId: 1 })))")
    else:  # Apply is a POST that redirects back to the dashboard: a page load
        _page_loaded(page, 1, f"{DASHBOARD}/dashboard/")

    assert _calls(page, "tabs.create") == [[{"url": f"{PORTAL}/apply"}]]
    assert _calls(page, "sidePanel.setOptions") == [
        [{"enabled": False}],  # the global default, at load
        [{"tabId": 7, "path": "panel.html", "enabled": True}],
    ]
    binding = page.evaluate("() => window.__session.bindings['7']")
    assert binding["applicationId"] == APP_A
    assert binding["portalFormId"] == FORM_ID
    assert binding["origin"] == PORTAL
    assert "language" not in binding  # the dock holds it (P5)
    assert binding["active"] is False  # nothing runs until the student presses Start
    dock = page.evaluate("() => window.__session.dock")
    assert (dock["status"], dock["applicationId"]) == ("ready", APP_A)
    assert dock["binding"] == {"tabId": 7, "origin": PORTAL}
    assert _calls(page, "executeScript") == []
    fetched = page.evaluate("() => window.__fetched")
    result = {"ok": True, "detail": {"opened": True}}
    assert [f"POST /ext/actions/{ACTION_ID}/result", result] in fetched


@pytest.mark.extension
@pytest.mark.parametrize(
    ("application_id", "form_url"),
    [
        ("app-1", f"{PORTAL}/apply"),
        (APP_A, "http://portal.example/apply"),
        (APP_A, "javascript:alert(1)"),
        (APP_A, "https://user:pw@portal.example/apply"),
    ],
)
def test_a_start_fill_action_with_a_bad_id_or_url_opens_nothing(
    browser_context, application_id, form_url
) -> None:
    responses = _start_fill_responses([200, _portal_packet(form_url)])
    responses["GET /ext/actions"][1]["actions"][0]["application_id"] = application_id
    page = _load_worker(
        browser_context, {}, responses, tabs={1: {"id": 1, "url": f"{DASHBOARD}/"}}
    )

    page.evaluate("() => Promise.all(window.__on.tab.map((fn) => fn({ tabId: 1 })))")

    assert _calls(page, "tabs.create") == []
    assert page.evaluate("() => window.__session.bindings ?? null") is None
    fetched = page.evaluate("() => window.__fetched")
    result = {"ok": False, "detail": {"refused": "invalid_action"}}
    assert [f"POST /ext/actions/{ACTION_ID}/result", result] in fetched


@pytest.mark.extension
def test_start_injects_into_the_bound_tab_with_the_student_s_language(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {},
        session=_binding(active=False),
        tabs={7: {"id": 7, "url": f"{PORTAL}/apply"}},
    )
    assert _send(page, {"type": "language", "lang": "ru"}, PANEL_SENDER) == {"ok": True}
    assert page.evaluate("() => window.__session.dock.language") == "ru"

    assert _send(page, {"type": "start-fill", "tabId": 7}, PANEL_SENDER) == {"ok": True}

    assert _calls(page, "executeScript") == [INJECT_7]
    assert _calls(page, "tabs.sendMessage") == [
        [7, _start_message("ru")]
    ]
    assert page.evaluate("() => window.__session.bindings['7'].active") is True


@pytest.mark.extension
@pytest.mark.parametrize(
    "message",
    [
        {"type": "start-fill", "tabId": 7},
        {"type": "stop-fill", "tabId": 7},
        {"type": "language", "lang": "ru"},
    ],
)
def test_start_stop_and_language_are_refused_from_a_portal_page(browser_context, message) -> None:
    page = _load_worker(
        browser_context,
        {"language": "az"},
        {},
        session=_binding(active=False),
        tabs={7: {"id": 7, "url": f"{PORTAL}/apply"}},
    )

    assert _send(page, message, TAB_SENDER) == {"ok": False, "code": "untrusted_sender"}
    assert _calls(page, "executeScript") == []
    assert _calls(page, "tabs.sendMessage") == []
    assert page.evaluate("() => window.__session.dock.language") == "az"


@pytest.mark.extension
@pytest.mark.parametrize(
    "message",
    [{"type": "start-fill", "tabId": "7"}, {"type": "language", "lang": "de"}],
)
def test_a_malformed_dock_message_is_refused(browser_context, message) -> None:
    page = _load_worker(browser_context, {}, {}, session=_binding(active=False))
    assert _send(page, message, PANEL_SENDER) == {"ok": False, "code": "invalid_message"}


@pytest.mark.extension
def test_start_refuses_a_tab_that_is_not_on_the_bound_origin(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {},
        session=_binding(active=False),
        tabs={
            7: {"id": 7, "url": "https://evil.example/"},
            9: {"id": 9, "url": f"{PORTAL}/apply"},
        },
    )

    _send(page, {"type": "start-fill", "tabId": 7}, PANEL_SENDER)
    _send(page, {"type": "start-fill", "tabId": 9}, PANEL_SENDER)  # never bound

    assert _calls(page, "executeScript") == []
    assert page.evaluate("() => window.__session.dock.message") == "wrong_page"


@pytest.mark.extension
def test_a_closed_panel_pauses_and_a_reopened_panel_resumes(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"language": "en"},
        {},
        session=_binding(),
        tabs={7: {"id": 7, "url": f"{PORTAL}/p2"}},
    )

    _page_loaded(page, 7, f"{PORTAL}/p2")
    assert _calls(page, "executeScript") == []  # no panel: paused

    _connect_dock(page)
    assert _calls(page, "executeScript") == [INJECT_7]

    _page_loaded(page, 7, f"{PORTAL}/p3")  # panel open: followed
    assert len(_calls(page, "executeScript")) == 2

    page.evaluate("() => window.__port.disconnect()")
    _page_loaded(page, 7, f"{PORTAL}/p4")
    assert len(_calls(page, "executeScript")) == 2
    assert page.evaluate("() => window.__session.dock.page") == 2  # p2, then p3


@pytest.mark.extension
def test_another_origin_in_the_bound_tab_is_never_injected(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {},
        {},
        session=_binding(),
        tabs={7: {"id": 7, "url": "https://evil.example/"}},
    )
    _connect_dock(page)  # resume finds the tab on another origin: nothing

    _page_loaded(page, 7, "https://evil.example/")
    _page_loaded(page, 9, f"{PORTAL}/apply")  # right origin, unbound tab

    assert _calls(page, "executeScript") == []


@pytest.mark.extension
def test_stop_tells_the_tab_and_ends_the_following(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {},
        {},
        session=_binding(),
        tabs={7: {"id": 7, "url": f"{PORTAL}/apply"}},
    )

    assert _send(page, {"type": "stop-fill", "tabId": 7}, PANEL_SENDER) == {"ok": True}

    assert _calls(page, "tabs.sendMessage") == [[7, {"type": "stop"}]]
    assert page.evaluate("() => window.__session.bindings['7'].active") is False
    assert page.evaluate("() => window.__session.dock.status") == "stopped"
    _connect_dock(page)
    _page_loaded(page, 7, f"{PORTAL}/p2")
    assert _calls(page, "executeScript") == []


@pytest.mark.extension
def test_a_closed_portal_tab_drops_its_binding(browser_context) -> None:
    page = _load_worker(browser_context, {}, {}, session=_binding())
    page.evaluate("() => Promise.all(window.__on.removed.map((fn) => fn(7, {})))")
    assert page.evaluate("() => window.__session.bindings") == {}
    # Final review M2: a closed tab hands its portal's permission back, as Stop does.
    assert _calls(page, "permissions.remove") == [[{"origins": [f"{PORTAL}/*"]}]]


# The panel's side.


def _panel_with_permission(browser_context, grant):
    page = _open_panel(browser_context)
    page.evaluate(f"() => {{ window.__grant = {'true' if grant else 'false'}; }}")
    page.select_option("#language", "en")
    _push_state(page, {"status": "ready", "binding": {"tabId": 7, "origin": PORTAL}})
    return page


@pytest.mark.extension
def test_start_asks_for_the_portal_permission_in_the_click_then_starts(browser_context) -> None:
    page = _panel_with_permission(browser_context, True)
    page.click("#start")  # the TEST presses the student's button
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'start-fill')")

    assert page.evaluate("() => window.__permissions") == [{"origins": [f"{PORTAL}/*"]}]
    assert {"type": "start-fill", "tabId": 7} in page.evaluate("() => window.__sent")
    assert page.evaluate("() => window.__ports") == ["dock"]

    page.click("#stop")
    assert {"type": "stop-fill", "tabId": 7} in page.evaluate("() => window.__sent")


@pytest.mark.extension
def test_a_refused_permission_starts_nothing_and_says_why(browser_context) -> None:
    page = _panel_with_permission(browser_context, False)
    page.click("#start")
    page.wait_for_function("() => document.getElementById('message').textContent !== ''")

    assert not any(m.get("type") == "start-fill" for m in page.evaluate("() => window.__sent"))
    strings = page.evaluate("() => window.__elmify_strings.en")
    assert page.inner_text("#message") == strings["permission_needed"]


_PANEL_FIELDS = [
    {"key": "personal.given_name", "state": "filled", "reason": "", "placed": True},
    {"key": "personal.family_name", "state": "already", "reason": "", "placed": True},
    {"key": "contact.phone", "state": "changed_by_you", "reason": "", "placed": True},
    {"key": "contact.email", "state": "your_turn", "reason": "hidden", "placed": False},
    {"key": "personal.country", "state": "elsewhere", "reason": "", "placed": False},
]


@pytest.mark.extension
def test_the_panel_is_slim_while_filling_and_wide_for_the_review(browser_context) -> None:
    page = _open_panel(browser_context)
    page.select_option("#language", "en")
    _push_state(page, {"status": "filling", "page": 2, "fields": _PANEL_FIELDS, "documents": []})

    assert page.inner_text("#progress") == "Page 2 · 3 of 4 done · 1 need you"
    assert "slim" in page.get_attribute("#dock", "class")
    assert page.is_hidden("#fields")
    assert page.is_visible("#progress")

    manual = [{"filename": "cv.pdf", "state": "manual"}]
    _push_state(page, {"status": "blocked", "documents": manual})

    assert "slim" not in (page.get_attribute("#dock", "class") or "")
    assert page.is_visible("#fields")
    review = page.inner_text("#review")
    assert review.index("Email") < review.index("cv.pdf") < review.index("Check every field")
    # No Next / Submit anywhere: the one button is the student telling us they
    # checked the page (the answers channel's trigger), which submits nothing.
    assert page.locator("#review button").all_inner_texts() == ["I have checked this page"]


# The content script's side.


def _content_with_listener(page, replies):
    """content.js with a stub chrome that also captures its onMessage listener."""
    page.evaluate(
        """(replies) => {
            window.__sent = [];
            window.__listeners = [];
            window.chrome = {
              runtime: {
                sendMessage: async (message) => {
                  window.__sent.push(message);
                  return replies[message.type] ?? { ok: true };
                },
                onMessage: { addListener: (fn) => window.__listeners.push(fn) },
              },
            };
        }""",
        replies,
    )
    page.add_script_tag(path=str(DIST / "content.js"))


def _deliver(page, message):
    page.evaluate("(m) => window.__listeners.forEach((fn) => fn(m, {}, () => {}))", message)


def _start(language, origin=None, resume=False):
    return {
        "type": "start",
        "applicationId": "app-1",
        "portalFormId": "form-1",
        "language": language,
        "origin": origin,
        "resume": resume,
    }


def _final_status(page):
    page.wait_for_function(
        "() => window.__sent.some((m) => m.type === 'dock' && 'message' in m.patch"
        " && m.patch.status !== 'filling')"
    )
    docks = [m["patch"] for m in page.evaluate("() => window.__sent") if m["type"] == "dock"]
    return [p for p in docks if "status" in p][-1]


@pytest.mark.extension
def test_start_runs_in_the_student_s_language_and_ends_in_review(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/plain_form.html"
    page.goto(url)
    _content_with_listener(page, {"packet": _plain_packet(url)})

    _deliver(page, _start("az", fixture_server))

    assert _final_status(page)["status"] == "review"
    assert "Dolduruldu" in page.evaluate("() => window.__elmify_marks_text()")


@pytest.mark.extension
def test_anything_left_for_the_student_ends_blocked_not_review(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/plain_form.html"
    page.goto(url)
    nope = {"selector": "#nope", "method": "fill", "value": "x", "profile_field": "contact.phone"}
    packet = _plain_packet(url, extra=[nope])
    _content_with_listener(page, {"packet": packet})
    _deliver(page, _start("en", fixture_server))
    assert _final_status(page)["status"] == "blocked"


@pytest.mark.extension
def test_a_login_page_asks_the_student_to_log_in_and_touches_nothing(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    _content_with_listener(
        page,
        {
            "packet": _plain_packet(fixture_server),
            "portal-login": {"ok": False, "code": "no_portal_password"},
        },
    )

    _deliver(page, _start("en", fixture_server))

    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    page.wait_for_timeout(200)
    sent = page.evaluate("() => window.__sent")
    docks = [m["patch"] for m in sent if m["type"] == "dock"]
    assert docks == [{"status": "login", "message": "log_in"}]
    assert _of_type(sent, "event") == []
    assert page.input_value("#username") == ""


@pytest.mark.extension
def test_a_login_page_gets_the_held_login_typed_and_nothing_pressed(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "portal-login": {"ok": True, **LOGIN_REPLY}},
    )
    page.evaluate(
        "() => { window.__submitted = false; document.querySelector('form')"
        ".addEventListener('submit', (e) => { window.__submitted = true; e.preventDefault(); }); }"
    )

    _deliver(page, _start("en", fixture_server))

    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    sent = page.evaluate("() => window.__sent")
    asked = [m for m in sent if m["type"] == "portal-login"]
    assert asked == [
        {"type": "portal-login", "applicationId": "app-1", "page": "login", "host": "127.0.0.1"}
    ]
    assert page.input_value("#username") == TAGGED
    assert page.input_value("#password") == LOGIN_REPLY["password"]
    assert [m["patch"] for m in sent if m["type"] == "dock"] == [
        {"status": "login", "message": "log_in_typed"}
    ]
    assert page.evaluate("() => window.__submitted") is False
    assert LOGIN_REPLY["password"] not in json.dumps(sent)  # nothing the page sent carries it


@pytest.mark.extension
def test_with_no_login_held_the_student_logs_in_and_nothing_is_typed(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    _content_with_listener(
        page,
        {
            "packet": _plain_packet(fixture_server),
            "portal-login": {"ok": False, "code": "no_portal_password"},
        },
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    assert page.input_value("#password") == ""
    docks = [m["patch"] for m in page.evaluate("() => window.__sent") if m["type"] == "dock"]
    assert docks == [{"status": "login", "message": "log_in"}]


@pytest.mark.extension
def test_a_login_the_portal_did_not_accept_is_not_typed_again(
    browser_context, fixture_server
) -> None:
    """The worker typed a login and the portal came back to a login page: the
    stored password is not the account's. Typing it again risks a lockout."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    _content_with_listener(
        page,
        {
            "packet": _plain_packet(fixture_server),
            "portal-login": {"ok": False, "code": "login_not_accepted"},
        },
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    page.wait_for_timeout(200)
    assert page.input_value("#username") == ""
    assert page.input_value("#password") == ""
    docks = [m["patch"] for m in page.evaluate("() => window.__sent") if m["type"] == "dock"]
    assert docks == [{"status": "login", "message": "login_not_accepted"}]


@pytest.mark.extension
def test_two_boxes_before_the_password_mean_nothing_is_typed(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login_two_boxes.html")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "portal-login": {"ok": True, **LOGIN_REPLY}},
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    sent = page.evaluate("() => window.__sent")
    assert _of_type(sent, "portal-login") == []
    assert page.input_value("#password") == "" and page.input_value("#number") == ""


@pytest.mark.extension
def test_a_box_the_student_already_typed_in_is_not_overwritten(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    page.fill("#password", "their-own")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "portal-login": {"ok": True, **LOGIN_REPLY}},
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    assert page.input_value("#password") == "their-own"
    assert page.input_value("#username") == ""  # not even the address: it is their turn
    sent = page.evaluate("() => window.__sent")
    assert _of_type(sent, "portal-login") == []  # no password minted or fetched for it
    assert [m["patch"] for m in sent if m["type"] == "dock"] == [
        {"status": "login", "message": "log_in"}
    ]


@pytest.mark.extension
def test_a_sign_up_gets_the_address_and_one_password_in_both_boxes(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/signup.html")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "portal-login": {"ok": True, **LOGIN_REPLY}},
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function(
        "() => window.__sent.some((m) => m.type === 'dock' && m.patch.message === 'sign_up_typed')"
    )
    sent = page.evaluate("() => window.__sent")
    asked = _of_type(sent, "portal-login")
    assert asked[0]["page"] == "signup" and asked[0]["max_length"] == 30
    assert page.input_value("#email") == TAGGED
    assert page.input_value("#pw") == LOGIN_REPLY["password"] == page.input_value("#pw2")
    assert page.input_value("#given") == ""  # the rest of a sign-up page is the ordinary fill's
    assert {"type": "address", "applicationId": "app-1", "event": "given"} in sent


# Page shapes a real portal serves, from the Task 6 review probe. Each is a body
# swapped into login.html, so the bodies read here rather than in fixture files.

OFF_SCREEN = "position:absolute;left:-9999px;top:0"
SIDE_BY_SIDE = """
  <form id="login"><input id="le" type="email"><input id="lp" type="password">
    <button>Log in</button></form>
  <form id="reg"><input id="re" type="email"><input id="rp" type="password">
    <input id="rp2" type="password"><button>Register</button></form>"""
NEWSLETTER_FORMLESS = """
  <header><input id="news" type="email" placeholder="Newsletter"></header>
  <div><input id="u" type="text"><input id="p" type="password"></div>"""
CHANGE_PASSWORD_FORMLESS = """
  <header><input id="search" type="text" placeholder="Search"></header>
  <div><input id="cur" type="password"><input id="new" type="password">
    <input id="conf" type="password"></div>"""
HONEYPOT_EMAIL = f"""<form>
  <input id="hp" type="email" name="email_confirm" tabindex="-1" autocomplete="off"
    style="{OFF_SCREEN}">
  <label for="u">Username</label><input id="u" type="text">
  <label for="p">Password</label><input id="p" type="password"></form>"""
HONEYPOT_PASSWORD = f"""<form>
  <input id="u" type="email"><input id="p" type="password">
  <input id="hpp" type="password" style="{OFF_SCREEN}"></form>"""
SIGN_UP = """<form>
  <input id="email" type="email"><input id="pw" type="password" autocomplete="new-password">
  <input id="pw2" type="password"></form>"""
SIGN_UP_CAME_BACK = f"""<form>
  <input id="email" type="email" value="{TAGGED}" aria-invalid="true" aria-describedby="err">
  <span id="err">This address is not allowed</span>
  <input id="pw" type="password"><input id="pw2" type="password"></form>"""


def _credential_shape(browser_context, fixture_server, body, plain="", before=None):
    """Start a run on `body`; return the page and every message it sent once docked."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    page.evaluate("(b) => { document.body.innerHTML = b; }", body)
    if before:
        before(page)
    packet = _plain_packet(fixture_server)
    packet["packet"]["plain_email"] = plain
    _content_with_listener(
        page, {"packet": packet, "portal-login": {"ok": True, **LOGIN_REPLY}}
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    return page, page.evaluate("() => window.__sent")


def _values(page):
    return page.evaluate(
        "() => Object.fromEntries(Array.from(document.querySelectorAll('input'))"
        ".map((i) => [i.id, i.value]))"
    )


def _docks(sent):
    return [m["patch"] for m in sent if m["type"] == "dock"]


@pytest.mark.extension
def test_a_login_beside_a_register_form_types_into_the_login_form_only(
    browser_context, fixture_server
) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, SIDE_BY_SIDE)
    assert [m["page"] for m in _of_type(sent, "portal-login")] == ["login"]
    assert _values(page) == {
        "le": TAGGED, "lp": LOGIN_REPLY["password"], "re": "", "rp": "", "rp2": ""
    }
    assert _of_type(sent, "address") == []
    assert _docks(sent) == [{"status": "login", "message": "log_in_typed"}]


@pytest.mark.extension
def test_a_change_password_page_is_not_a_login_and_gets_nothing(
    browser_context, fixture_server
) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, CHANGE_PASSWORD_FORMLESS)
    assert _of_type(sent, "portal-login") == []
    assert set(_values(page).values()) == {""}  # not the header's search box either
    assert _docks(sent) == [{"status": "login", "message": "log_in"}]


@pytest.mark.extension
def test_a_formless_login_ignores_the_newsletter_box_in_the_header(
    browser_context, fixture_server
) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, NEWSLETTER_FORMLESS)
    assert _values(page) == {"news": "", "u": TAGGED, "p": LOGIN_REPLY["password"]}
    assert _docks(sent) == [{"status": "login", "message": "log_in_typed"}]


@pytest.mark.extension
def test_an_off_screen_honeypot_address_box_gets_nothing(
    browser_context, fixture_server
) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, HONEYPOT_EMAIL)
    assert _values(page) == {"hp": "", "u": TAGGED, "p": LOGIN_REPLY["password"]}
    assert _docks(sent) == [{"status": "login", "message": "log_in_typed"}]


@pytest.mark.extension
def test_an_off_screen_honeypot_password_does_not_make_a_login_a_sign_up(
    browser_context, fixture_server
) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, HONEYPOT_PASSWORD)
    assert [m["page"] for m in _of_type(sent, "portal-login")] == ["login"]
    assert _values(page) == {"u": TAGGED, "p": LOGIN_REPLY["password"], "hpp": ""}
    assert _docks(sent) == [{"status": "login", "message": "log_in_typed"}]


@pytest.mark.extension
def test_a_sign_up_the_student_started_asks_for_no_password_and_types_nothing(
    browser_context, fixture_server
) -> None:
    page, sent = _credential_shape(
        browser_context, fixture_server, SIGN_UP, before=lambda p: p.fill("#pw", "their-own-1")
    )
    assert _of_type(sent, "portal-login") == []  # the server mints nothing the portal never gets
    assert _values(page) == {"email": "", "pw": "their-own-1", "pw2": ""}
    assert _of_type(sent, "address") == []
    assert _docks(sent) == [{"status": "login", "message": "log_in"}]


@pytest.mark.extension
def test_a_sign_up_sent_back_refusing_the_tag_gets_the_plain_address(
    browser_context, fixture_server
) -> None:
    page, sent = _credential_shape(
        browser_context, fixture_server, SIGN_UP_CAME_BACK, plain=PLAIN
    )
    password = LOGIN_REPLY["password"]
    assert _values(page) == {"email": PLAIN, "pw": password, "pw2": password}
    assert {
        "type": "address", "applicationId": "app-1", "event": "rejected", "evidence": "after_submit"
    } in sent
    # The server only reads on a came-back ask: it never mints a second password.
    assert [m.get("came_back") for m in _of_type(sent, "portal-login")] == [True]
    assert _docks(sent) == [{"status": "login", "message": "submit_again"}]


@pytest.mark.extension
def test_a_sign_up_holding_some_other_address_is_the_student_s(
    browser_context, fixture_server
) -> None:
    body = SIGN_UP_CAME_BACK.replace(TAGGED, "leyla.apply+zz99zz@outlook.com")  # not the account's
    page, sent = _credential_shape(browser_context, fixture_server, body, plain=PLAIN)
    assert _values(page) == {"email": "leyla.apply+zz99zz@outlook.com", "pw": "", "pw2": ""}
    assert _of_type(sent, "address") == []
    assert _docks(sent) == [{"status": "login", "message": "log_in_untyped"}]


@pytest.mark.extension
def test_the_plain_address_button_works_on_a_sign_up(browser_context, fixture_server) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, SIGN_UP, plain=PLAIN)
    assert _values(page)["email"] == TAGGED
    page.evaluate("() => window.__elmify_use_plain()")
    page.wait_for_function(
        "() => window.__sent.some((m) => m.type === 'dock' && m.patch.message === 'plain_typed')"
    )
    assert _values(page)["email"] == PLAIN
    assert {
        "type": "address", "applicationId": "app-1", "event": "rejected", "evidence": "student"
    } in page.evaluate("() => window.__sent")


RESET_FORMLESS = """
  <header><input id="search" type="text" placeholder="Search"></header>
  <div><input id="new" type="password"><input id="conf" type="password"></div>"""
RIGHT_HONEYPOT = """<form>
  <input id="hp" type="email" style="position:absolute;left:99999px;top:0">
  <input id="u" type="text"><input id="p" type="password"></form>"""
WHOLE_PAGE_FORM = """<form id="aspnetForm">
  <header><input id="news" type="email" placeholder="Newsletter"></header>
  <div><label for="u">Username</label><input id="u" type="text">
    <label for="p">Password</label><input id="p" type="password"></div></form>"""
# The same page with the newsletter box outside any landmark: only the
# nearest-area rule keeps it out.
WHOLE_PAGE_FORM_NO_LANDMARK = WHOLE_PAGE_FORM.replace("header>", "div>")


@pytest.mark.extension
def test_a_formless_reset_page_with_a_header_search_box_is_not_a_sign_up(
    browser_context, fixture_server
) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, RESET_FORMLESS, plain=PLAIN)
    assert _of_type(sent, "portal-login") == []  # nothing minted for it
    assert set(_values(page).values()) == {""}
    assert _of_type(sent, "address") == []
    assert _docks(sent) == [{"status": "login", "message": "log_in"}]


@pytest.mark.extension
def test_a_honeypot_parked_off_the_right_edge_gets_nothing(
    browser_context, fixture_server
) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, RIGHT_HONEYPOT)
    assert _values(page) == {"hp": "", "u": TAGGED, "p": LOGIN_REPLY["password"]}
    assert _docks(sent) == [{"status": "login", "message": "log_in_typed"}]


@pytest.mark.extension
@pytest.mark.parametrize(
    "body", [WHOLE_PAGE_FORM, WHOLE_PAGE_FORM_NO_LANDMARK], ids=["header", "no_landmark"]
)
def test_one_form_around_the_whole_page_types_the_login_not_the_newsletter(
    browser_context, fixture_server, body
) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, body)
    assert _values(page) == {"news": "", "u": TAGGED, "p": LOGIN_REPLY["password"]}
    assert _docks(sent) == [{"status": "login", "message": "log_in_typed"}]


@pytest.mark.extension
@pytest.mark.parametrize("remembered", [TAGGED, TAGGED.upper()], ids=["exact", "other_case"])
def test_a_remembered_username_gets_only_the_password(
    browser_context, fixture_server, remembered
) -> None:
    body = f"""<form><input id="u" type="email" value="{remembered}">
      <input id="p" type="password"></form>"""
    page, sent = _credential_shape(browser_context, fixture_server, body)
    assert [m["page"] for m in _of_type(sent, "portal-login")] == ["login"]
    assert _values(page) == {"u": remembered, "p": LOGIN_REPLY["password"]}  # address untouched
    assert _docks(sent) == [{"status": "login", "message": "log_in_typed"}]


@pytest.mark.extension
def test_a_remembered_username_that_is_not_the_account_s_gets_nothing(
    browser_context, fixture_server
) -> None:
    body = """<form><input id="u" type="email" value="someone.else@example.com">
      <input id="p" type="password"></form>"""
    page, sent = _credential_shape(browser_context, fixture_server, body)
    assert _values(page) == {"u": "someone.else@example.com", "p": ""}
    assert _docks(sent) == [{"status": "login", "message": "log_in_untyped"}]


# One ASP.NET <form> holding two panels (fix round 3).
LOGIN_THEN_REGISTER = """<form id="aspnetForm">
  <div id="loginPanel"><input id="le" type="email"><input id="lp" type="password"></div>
  <div id="regPanel"><input id="re" type="email"><input id="rp" type="password"></div></form>"""
REGISTER_THEN_LOGIN = """<form id="aspnetForm">
  <div id="regPanel"><input id="re" type="email"><input id="rp" type="password"></div>
  <div id="loginPanel"><input id="le" type="email"><input id="lp" type="password"></div></form>"""
LOGIN_AND_PASSWORD_ONLY_PANEL = """<form id="aspnetForm">
  <div id="loginPanel"><input id="le" type="email">
    <input id="lp" type="password" autocomplete="current-password"></div>
  <div id="regPanel"><input id="rp" type="password"></div></form>"""
# Ordinary sign-ups whose repeat box sits in a row of its own.
SIGN_UP_REPEAT_ROW = """<form>
  <div class="row"><input id="email" type="email"><input id="pw" type="password"></div>
  <div class="row"><input id="pw2" type="password"></div></form>"""
SIGN_UP_EACH_IN_ROW = """<form>
  <div class="row"><input id="email" type="email"></div>
  <div class="row"><input id="pw" type="password"></div>
  <div class="row"><input id="pw2" type="password"></div></form>"""
# A login widget that lives in site furniture is still a login.
LOGIN_IN_ASIDE = """<main><p>Welcome</p></main><aside><form>
  <input id="u" type="email"><input id="p" type="password"></form></aside>"""
LOGIN_IN_HEADER = """<header><form>
  <input id="u" type="text"><input id="p" type="password"></form></header><main>x</main>"""


@pytest.mark.extension
@pytest.mark.parametrize(
    "body",
    [LOGIN_THEN_REGISTER, REGISTER_THEN_LOGIN, LOGIN_AND_PASSWORD_ONLY_PANEL],
    ids=["login_then_register", "register_then_login", "current_password_beside_another"],
)
def test_a_form_holding_two_panels_gets_nothing(browser_context, fixture_server, body) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, body, plain=PLAIN)
    assert _of_type(sent, "portal-login") == []  # no password minted for either panel
    assert set(_values(page).values()) == {""}
    assert _of_type(sent, "address") == []
    assert _docks(sent) == [{"status": "login", "message": "log_in"}]


@pytest.mark.extension
@pytest.mark.parametrize(
    "body", [SIGN_UP_REPEAT_ROW, SIGN_UP_EACH_IN_ROW], ids=["repeat_row", "each_in_row"]
)
def test_a_sign_up_whose_repeat_box_has_its_own_row_gets_both(
    browser_context, fixture_server, body
) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, body)
    assert [m["page"] for m in _of_type(sent, "portal-login")] == ["signup"]
    password = LOGIN_REPLY["password"]
    assert _values(page) == {"email": TAGGED, "pw": password, "pw2": password}
    assert _docks(sent) == [{"status": "login", "message": "sign_up_typed"}]


@pytest.mark.extension
@pytest.mark.parametrize("body", [LOGIN_IN_ASIDE, LOGIN_IN_HEADER], ids=["aside", "header"])
def test_a_login_widget_in_site_furniture_is_still_typed(
    browser_context, fixture_server, body
) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, body)
    assert _values(page) == {"u": TAGGED, "p": LOGIN_REPLY["password"]}
    assert _docks(sent) == [{"status": "login", "message": "log_in_typed"}]


ARIA_HIDDEN_BOX = """<form><div aria-hidden="true"><input id="hp" type="email"></div>
  <input id="u" type="text"><input id="p" type="password"></form>"""
UNFOCUSABLE_BOX = """<form><input id="hp" type="email" tabindex="-1">
  <input id="u" type="text"><input id="p" type="password"></form>"""
def _login(identifier):
    return {"kind": "login", "identifier": identifier, "passwords": 1, "maxLength": None}


def _sign_up():
    return {"kind": "signup", "identifier": "email", "passwords": 2, "maxLength": None}


THREE_PASSWORDS = """<form><input id="u" type="email"><input id="a" type="password">
  <input id="b" type="password"><input id="c" type="password"></form>"""


@pytest.mark.extension
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (SIDE_BY_SIDE, _login("le")),
        (NEWSLETTER_FORMLESS, _login("u")),
        (CHANGE_PASSWORD_FORMLESS, None),
        (THREE_PASSWORDS, None),
        (HONEYPOT_EMAIL, _login("u")),
        (HONEYPOT_PASSWORD, _login("u")),
        (ARIA_HIDDEN_BOX, _login("u")),
        (UNFOCUSABLE_BOX, _login("u")),
        (SIGN_UP, _sign_up()),
        (RESET_FORMLESS, None),
        (WHOLE_PAGE_FORM, _login("u")),
        (WHOLE_PAGE_FORM_NO_LANDMARK, _login("u")),
        (RIGHT_HONEYPOT, _login("u")),
        (LOGIN_THEN_REGISTER, None),
        (REGISTER_THEN_LOGIN, None),
        (LOGIN_AND_PASSWORD_ONLY_PANEL, None),
        (SIGN_UP_REPEAT_ROW, _sign_up()),
        (SIGN_UP_EACH_IN_ROW, _sign_up()),
        (LOGIN_IN_ASIDE, _login("u")),
        (LOGIN_IN_HEADER, _login("u")),
    ],
    ids=[
        "side_by_side", "newsletter", "change_password", "three_passwords", "honeypot_email",
        "honeypot_password", "aria_hidden", "tabindex_minus_one", "sign_up",
        "reset_formless", "whole_page_form", "whole_page_form_no_landmark", "right_honeypot",
        "login_then_register", "register_then_login", "current_password_beside_another",
        "sign_up_repeat_row", "sign_up_each_in_row", "login_in_aside", "login_in_header",
    ],
)
def test_what_credentials_reads_off_each_page_shape(
    browser_context, fixture_server, body, expected
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    page.evaluate("(b) => { document.body.innerHTML = b; }", body)
    _content_with_listener(page, {})
    assert page.evaluate("() => window.__elmify_credential_page()") == expected


@pytest.mark.extension
def test_stop_takes_the_marks_down_and_ends_the_watchers(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/plain_form.html"
    page.goto(url)
    _content_with_listener(page, {"packet": _plain_packet(url)})
    _deliver(page, _start("en", fixture_server))
    _final_status(page)
    assert page.evaluate("() => !!document.querySelector('[data-elmify-marks]')")

    _deliver(page, {"type": "stop"})
    before = len(page.evaluate("() => window.__sent"))
    page.fill("#gn", "Aysel")  # the student's edit after Stop
    page.mouse.wheel(0, 50)
    page.wait_for_timeout(300)

    assert page.evaluate("() => document.querySelector('[data-elmify-marks]')") is None
    assert page.evaluate("() => window.__elmify_marks()") == []
    assert len(page.evaluate("() => window.__sent")) == before


@pytest.mark.extension
def test_a_second_injection_does_not_listen_twice(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    _content_with_listener(page, {})
    page.add_script_tag(path=str(DIST / "content.js"))
    assert page.evaluate("() => window.__listeners.length") == 1


@pytest.mark.extension
def test_scrolling_before_any_mark_draws_no_layer(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    _content_with_listener(page, {})
    page.evaluate(
        "() => { dispatchEvent(new Event('scroll')); dispatchEvent(new Event('resize')); }"
    )
    page.wait_for_timeout(100)
    assert page.evaluate("() => document.querySelector('[data-elmify-marks]')") is None


@pytest.mark.extension
def test_a_mark_at_the_right_edge_moves_left_instead_of_covering_the_page(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/right_edge_form.html"
    page.goto(url)
    _run_with_stubbed_messaging(page, {"packet": _plain_packet(url)})

    marks = {m["key"]: m for m in page.evaluate("() => window.__elmify_marks()")}
    field = page.evaluate("() => document.getElementById('gn').getBoundingClientRect().left")
    given = marks["personal.given_name"]
    assert given["placed"]
    assert given["rect"]["x"] + given["rect"]["w"] <= field  # beside it, on the left
    # A field as wide as the page has room on neither side: the panel carries it.
    assert not marks["personal.family_name"]["placed"]


# --- Task 6, fix round 1 ------------------------------------------------------

DOC_PATH = "/documents/abc/download"
PDF = {"Content-Type": "application/pdf"}


def _cached_packet():
    packet = _portal_packet()
    packet["documents"] = [{"filename": "cv.pdf", "download_path": DOC_PATH, "draft_id": "d1"}]
    return {f"packet:{APP_A}": packet}


def _content_worker(browser_context, dock=None):
    return _load_worker(
        browser_context,
        dock or {"language": "az", "binding": {"tabId": 7, "origin": PORTAL}},
        {
            f"GET /ext/applications/{APP_A}/packet": [200, _portal_packet()],
            f"GET /ext/applications/{APP_B}/packet": [200, _portal_packet()],
            f"GET {DOC_PATH}": [200, {}, PDF],
            "GET /documents/other/download": [200, {}, PDF],
        },
        session={**_binding(), **_cached_packet()},
    )


@pytest.mark.extension
@pytest.mark.parametrize(
    ("message", "sender"),
    [
        ({"type": "packet", "applicationId": APP_A}, {**CONTENT, "origin": "https://evil.example"}),
        ({"type": "packet", "applicationId": APP_A}, {**CONTENT, "frameId": 3}),
        ({"type": "packet", "applicationId": APP_A}, {**CONTENT, "tab": {"id": 9}}),
        ({"type": "packet", "applicationId": APP_B}, CONTENT),
        ({"type": "document", "path": "/documents/other/download"}, CONTENT),
        ({"type": "event", "applicationId": APP_B, "kind": "FILL", "detail": {}}, CONTENT),
        ({"type": "snapshot", "portalFormId": APP_B, "snapshot": {}}, CONTENT),
    ],
)
def test_a_content_request_is_answered_only_for_its_own_bound_tab(
    browser_context, message, sender
) -> None:
    page = _content_worker(browser_context)

    assert _send(page, message, sender) == {"ok": False, "code": "untrusted_sender"}
    assert page.evaluate("() => window.__fetched") == []


@pytest.mark.extension
def test_a_content_request_from_the_bound_tab_still_works(browser_context) -> None:
    page = _content_worker(browser_context)

    reply = _send(page, {"type": "packet", "applicationId": APP_A}, CONTENT)
    assert reply["ok"] is True and reply["packet"]["application_id"] == APP_A
    assert _send(page, {"type": "document", "path": DOC_PATH}, CONTENT)["ok"] is True
    assert [f"GET {DOC_PATH}", None] in page.evaluate("() => window.__fetched")


def _worker_listing(browser_context, path):
    """A content worker whose cached packet lists `path`, so contentRefusal passes it and
    only the document handler's own check stands between it and a fetch."""
    packet = _portal_packet()
    packet["documents"] = [{"filename": "cv.pdf", "download_path": path, "draft_id": "d1"}]
    return _load_worker(
        browser_context,
        {"language": "az", "binding": {"tabId": 7, "origin": PORTAL}},
        {f"GET {path}": [200, {}, PDF]},
        session={**_binding(), f"packet:{APP_A}": packet},
    )


@pytest.mark.extension
@pytest.mark.parametrize(
    "path",
    [
        "@evil.example/documents/x",  # concatenated after the origin, this is another host
        "https://evil.example/documents/x",
        "//evil.example/documents/x",
        "/student/documents/",  # same origin, not a document route
        "/ext/pair",  # an /ext/ path that is not a document
    ],
)
def test_a_document_path_off_the_document_routes_is_never_fetched(browser_context, path) -> None:
    page = _worker_listing(browser_context, path)

    reply = _send(page, {"type": "document", "path": path}, CONTENT)
    assert reply == {"ok": False, "code": "document_unavailable"}
    assert page.evaluate("() => window.__fetched") == []


@pytest.mark.extension
@pytest.mark.parametrize(
    "path",
    [
        DOC_PATH,
        "/prepared/22222222-2222-4222-8222-222222222222/cv.pdf",
        "/ext/documents/33333333-3333-4333-8333-333333333333",
    ],
)
def test_each_document_route_still_attaches(browser_context, path) -> None:
    page = _worker_listing(browser_context, path)

    assert _send(page, {"type": "document", "path": path}, CONTENT)["ok"] is True
    assert page.evaluate("() => window.__fetched") == [[f"GET {path}", None]]


@pytest.mark.extension
def test_a_portal_page_cannot_patch_the_dock_s_own_keys(browser_context) -> None:
    page = _content_worker(browser_context)
    patch = {
        "binding": {"tabId": 7, "origin": "https://evil.example"},
        "language": "toString",
        "registration": {"applicationId": APP_A, "portalHost": "evil", "address": "x"},
        "status": "filling",
    }

    assert _send(page, {"type": "dock", "patch": patch}, CONTENT) == {"ok": True}

    dock = page.evaluate("() => window.__session.dock")
    assert dock["binding"] == {"tabId": 7, "origin": PORTAL}
    assert dock["language"] == "az"
    assert "registration" not in dock
    assert dock["status"] == "filling"


@pytest.mark.extension
def test_a_reopened_panel_resumes_as_a_resume(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"language": "en"},
        {},
        session=_binding(),
        tabs={7: {"id": 7, "url": f"{PORTAL}/p2"}},
    )
    _connect_dock(page)
    assert _calls(page, "tabs.sendMessage") == [[7, _start_message("en", resume=True)]]


@pytest.mark.extension
def test_two_polls_at_once_open_one_tab(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {},
        _start_fill_responses([200, _portal_packet()]),
        tabs={1: {"id": 1, "url": f"{DASHBOARD}/"}},
    )
    page.evaluate(
        "() => Promise.all([...window.__on.tab, ...window.__on.tab].map((fn) => fn({ tabId: 1 })))"
    )
    assert len(_calls(page, "tabs.create")) == 1


@pytest.mark.extension
def test_a_tab_that_did_not_open_answers_the_action(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {},
        _start_fill_responses([200, _portal_packet()]),
        tabs={1: {"id": 1, "url": f"{DASHBOARD}/"}},
    )
    page.evaluate("() => { window.__created = {}; }")
    page.evaluate("() => Promise.all(window.__on.tab.map((fn) => fn({ tabId: 1 })))")
    result = {"ok": False, "detail": {"refused": "no_tab"}}
    fetched = page.evaluate("() => window.__fetched")
    assert [f"POST /ext/actions/{ACTION_ID}/result", result] in fetched


@pytest.mark.extension
def test_stop_gives_the_portal_permission_back(browser_context) -> None:
    page = _load_worker(browser_context, {}, {}, session=_binding())
    _send(page, {"type": "stop-fill", "tabId": 7}, PANEL_SENDER)
    assert _calls(page, "permissions.remove") == [[{"origins": [f"{PORTAL}/*"]}]]


@pytest.mark.extension
def test_start_for_another_origin_asks_nothing(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})

    _deliver(page, _start("en", "https://evil.example"))
    page.wait_for_timeout(200)

    assert page.evaluate("() => window.__sent") == []


@pytest.mark.extension
def test_a_resume_on_the_same_page_re_reports_without_re_posting(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/plain_form.html"
    page.goto(url)
    _content_with_listener(page, {"packet": _plain_packet(url)})
    _deliver(page, _start("en", fixture_server))
    _final_status(page)
    before = len(page.evaluate("() => window.__sent"))

    _deliver(page, _start("en", fixture_server, resume=True))
    page.wait_for_function(f"() => window.__sent.length > {before}")
    page.wait_for_timeout(200)

    sent = page.evaluate("() => window.__sent")
    kinds = [m["kind"] for m in _of_type(sent, "event")]
    assert kinds.count("FILL") == 1 and kinds.count("READ_BACK") == 1
    assert _of_type(sent, "packet") == _of_type(sent[:before], "packet")
    assert sent[-1]["type"] == "dock" and sent[-1]["patch"]["status"] == "review"
    assert page.evaluate("() => !!document.querySelector('[data-elmify-marks]')")


@pytest.mark.extension
def test_an_unknown_language_falls_back_to_english_marks(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/plain_form.html"
    page.goto(url)
    _content_with_listener(page, {"packet": _plain_packet(url)})
    _deliver(page, _start("toString", fixture_server))
    _final_status(page)
    assert "Filled" in page.evaluate("() => window.__elmify_marks_text()")


@pytest.mark.extension
@pytest.mark.parametrize(
    ("message", "key"),
    [
        ("start", "m_start"),
        ("log_in", "m_log_in"),
        ("login_not_accepted", "m_login_not_accepted"),
        ("wrong_page", "m_wrong_page"),
        ("unreachable", "m_unreachable"),
        ("automation_prohibited", "m_automation_prohibited"),
        # The run's own outcomes (final review I2): codes, never English sentences.
        ("check_submit", "m_check_submit"),
        ("swapped_plain", "m_swapped_plain"),
        ("submit_again", "m_submit_again"),
        ("captcha", "m_captcha"),
        ("confirmed", "m_confirmed"),
        ("plain_not_started", "m_plain_not_started"),
        ("plain_not_typed", "m_plain_not_typed"),
        ("plain_typed", "m_plain_typed"),
        ("disconnected", "m_disconnected"),
        ("some_new_code", "m_code_other"),
    ],
)
def test_dock_message_codes_are_shown_in_the_student_s_language(
    browser_context, message, key
) -> None:
    page = _open_panel(browser_context)  # az by default
    _push_state(page, {"message": message})
    strings = page.evaluate("() => window.__elmify_strings.az")
    assert page.inner_text("#message") == strings[key]


@pytest.mark.extension
def test_a_sentence_in_the_dock_message_is_shown_as_it_is(browser_context) -> None:
    """Only the worker's registration replies are still sentences; every
    message the run sends is a code (the test above)."""
    page = _open_panel(browser_context)
    _push_state(page, {"message": "Thanks. This portal keeps your tagged address."})
    assert page.inner_text("#message") == "Thanks. This portal keeps your tagged address."


# --- Final review fix wave --------------------------------------------------


@pytest.mark.extension
def test_a_second_start_fill_stops_the_first_binding(browser_context) -> None:
    """I1: one portal at a time. The first tab is stopped and told so, its
    permission goes back, and its reports can no longer reach the dock."""
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        _start_fill_responses([200, _portal_packet()]),
        session=_binding(),
        tabs={1: {"id": 1, "url": f"{DASHBOARD}/"}},
    )
    page.evaluate("() => { window.__created = { id: 9 }; }")

    page.evaluate("() => Promise.all(window.__on.tab.map((fn) => fn({ tabId: 1 })))")

    assert page.evaluate("() => window.__session.bindings['7'].active") is False
    assert _calls(page, "tabs.sendMessage") == [[7, {"type": "stop"}]]
    assert _calls(page, "permissions.remove") == [[{"origins": [f"{PORTAL}/*"]}]]
    assert page.evaluate("() => window.__session.dock.binding") == {"tabId": 9, "origin": PORTAL}
    reply = _send(page, {"type": "dock", "patch": {"status": "review"}}, CONTENT)
    assert reply == {"ok": False, "code": "untrusted_sender"}
    assert page.evaluate("() => window.__session.dock.status") == "ready"


@pytest.mark.extension
def test_a_dock_patch_from_a_tab_the_dock_does_not_show_is_refused(browser_context) -> None:
    """I1: an active, correctly bound tab still may not write a dock that
    shows another tab."""
    page = _content_worker(
        browser_context, {"language": "az", "binding": {"tabId": 9, "origin": PORTAL}}
    )
    reply = _send(page, {"type": "dock", "patch": {"status": "review"}}, CONTENT)
    assert reply == {"ok": False, "code": "untrusted_sender"}
    assert "status" not in page.evaluate("() => window.__session.dock")


@pytest.mark.extension
def test_the_toolbar_on_the_bound_portal_tab_opens_the_panel(browser_context) -> None:
    """I4: sidePanel.open runs before any await -- checked synchronously,
    in the same turn as the click -- and nothing asks for a permission."""
    page = _load_worker(browser_context, {}, {}, session=_binding(active=False))
    opened = page.evaluate(
        """() => {
            window.__on.action[0]({ id: 7, url: "https://portal.example/apply" });
            return window.__calls.filter((c) => c[0] === "sidePanel.open").map((c) => c[1]);
        }"""
    )
    assert opened == [[{"tabId": 7}]]
    page.wait_for_timeout(100)
    assert _calls(page, "permissions.request") == []


@pytest.mark.extension
def test_the_toolbar_on_the_dashboard_still_pairs(browser_context) -> None:
    """I4's negative control: an unbound tab keeps the old order."""
    page = _load_worker(browser_context, {}, {}, session=_binding(active=False))
    page.evaluate(
        "() => window.__on.action[0]({ id: 1, url: 'https://dash.example/dashboard/' })"
    )
    assert _calls(page, "permissions.request") == [[{"origins": [f"{DASHBOARD}/*"]}]]
    # T1: the click's first open (refused by Chrome while the dashboard's panel
    # is still disabled), then the pairing path's, after it enables the panel.
    assert _calls(page, "sidePanel.open") == [[{"tabId": 1}], [{"tabId": 1}]]


@pytest.mark.extension
def test_unpair_stops_every_bound_tab_and_gives_permissions_back(browser_context) -> None:
    """M3: nothing keeps running, or keeps a host permission, after Disconnect."""
    page = _load_worker(
        browser_context, {}, {"DELETE /ext/pair": [204, None]}, session=_binding()
    )
    _send(page, {"type": "unpair"}, PANEL_SENDER)
    page.wait_for_function("() => window.__session.dock?.status === 'idle'")
    assert page.evaluate("() => window.__session.dock.message") == "disconnected"

    assert _calls(page, "tabs.sendMessage") == [[7, {"type": "stop"}]]
    assert _calls(page, "permissions.remove") == [[{"origins": [f"{PORTAL}/*"]}]]
    assert "bindings" not in page.evaluate("() => window.__session")


def _doc_packet(url):
    """No fields, one CV: two_upload_slots.html has a visible CV input for it."""
    packet = _plain_packet(url)
    packet["packet"]["entries"] = []
    packet["packet"]["documents"] = [
        {"filename": "cv-standard.pdf", "download_path": DOC_PATH, "draft_id": "d1"}
    ]
    return packet


def _cv_size(page):
    return page.evaluate(
        "() => { const f = document.getElementById('cv').files; return f.length ? f[0].size : 0; }"
    )


def _send_or_timeout(page, message, sender):
    """_send, but a handler that never answers resolves to "no reply"."""
    return page.evaluate(
        """([message, sender]) => Promise.race([
            new Promise((resolve) => window.__on.message[0](message, sender, resolve)),
            new Promise((resolve) => setTimeout(() => resolve("no reply"), 1000)),
        ])""",
        [message, sender],
    )


@pytest.mark.extension
def test_a_document_crosses_to_the_page_as_base64(browser_context) -> None:
    """I6: runtime.sendMessage is JSON; an ArrayBuffer arrives as {}."""
    page = _content_worker(browser_context)  # the stub serves {} -> the bytes "{}"
    reply = _send(page, {"type": "document", "path": DOC_PATH}, CONTENT)
    assert reply == {"ok": True, "base64": "e30="}


@pytest.mark.extension
def test_a_document_from_the_worker_lands_with_its_bytes(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/two_upload_slots.html"
    page.goto(url)
    _run_with_stubbed_messaging(
        page, {"packet": _doc_packet(url), "document": {"ok": True, "base64": "aGVsbG8="}}
    )
    assert _cv_size(page) == 5  # "hello"


@pytest.mark.extension
def test_a_document_fetch_that_throws_is_answered(browser_context) -> None:
    """M1: a network failure answers document_unavailable instead of nothing."""
    page = _content_worker(browser_context)
    page.evaluate("() => { window.fetch = async () => { throw new TypeError('offline'); }; }")
    reply = _send_or_timeout(page, {"type": "document", "path": DOC_PATH}, CONTENT)
    assert reply == {"ok": False, "code": "document_unavailable"}


@pytest.mark.extension
@pytest.mark.parametrize(
    ("redirected", "content_type", "ok"),
    [
        (True, "application/pdf", False),  # the login page, even if it claimed to be a PDF
        (False, "text/html; charset=utf-8", False),
        (False, "application/pdf; foo=bar", True),
    ],
)
def test_only_a_real_file_response_is_attached(
    browser_context, redirected, content_type, ok
) -> None:
    """An expired session redirects to a login page that answers 200 HTML."""
    page = _content_worker(browser_context)
    page.evaluate(
        """([redirected, type]) => { window.fetch = async () => {
            const r = new Response("x", { status: 200, headers: { "Content-Type": type } });
            Object.defineProperty(r, "redirected", { value: redirected });
            return r;
        }; }""",
        [redirected, content_type],
    )
    reply = _send(page, {"type": "document", "path": DOC_PATH}, CONTENT)
    gone = {"ok": False, "code": "document_unavailable"}
    expected = {"ok": True, "base64": "eA=="} if ok else gone
    assert reply == expected


@pytest.mark.extension
def test_an_unavailable_document_is_left_to_the_student(browser_context, fixture_server) -> None:
    """M1: the run goes on, lists the document as manual, and ends blocked."""
    page = browser_context.new_page()
    url = f"{fixture_server}/two_upload_slots.html"
    page.goto(url)
    _content_with_listener(
        page,
        {"packet": _doc_packet(url), "document": {"ok": False, "code": "document_unavailable"}},
    )
    _deliver(page, _start("en", fixture_server))
    final = _final_status(page)
    assert final["status"] == "blocked"
    assert final["documents"] == [{"filename": "cv-standard.pdf", "state": "manual"}]


@pytest.mark.extension
def test_stop_while_a_document_is_fetched_attaches_nothing(browser_context, fixture_server) -> None:
    """I3: Stop arrives while the worker is still fetching the CV."""
    page = browser_context.new_page()
    url = f"{fixture_server}/two_upload_slots.html"
    page.goto(url)
    page.evaluate(
        """(packet) => {
            window.__sent = [];
            window.__listeners = [];
            window.chrome = { runtime: {
              sendMessage: (message) => {
                window.__sent.push(message);
                if (message.type === "packet") return Promise.resolve(packet);
                if (message.type === "document") return new Promise((resolve) => {
                  window.__release = () => resolve({ ok: true, base64: "aGVsbG8=" });
                });
                return Promise.resolve({ ok: true });
              },
              onMessage: { addListener: (fn) => window.__listeners.push(fn) },
            } };
        }""",
        _doc_packet(url),
    )
    page.add_script_tag(path=str(DIST / "content.js"))
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => !!window.__release")

    _deliver(page, {"type": "stop"})
    page.evaluate("() => window.__release()")
    page.wait_for_timeout(200)

    assert _cv_size(page) == 0
    assert _of_type(page.evaluate("() => window.__sent"), "event") == []


@pytest.mark.extension
def test_the_run_s_review_line_reaches_an_azerbaijani_panel_in_azerbaijani(
    browser_context, fixture_server
) -> None:
    """I2: the line the student is told every run, end to end."""
    page = browser_context.new_page()
    url = f"{fixture_server}/plain_form.html"
    page.goto(url)
    _content_with_listener(page, {"packet": _plain_packet(url)})
    _deliver(page, _start("az", fixture_server))
    message = _final_status(page)["message"]

    panel = _open_panel(browser_context)  # az by default
    _push_state(panel, {"message": message})
    strings = panel.evaluate("() => window.__elmify_strings")
    assert panel.inner_text("#message") == strings["az"]["m_check_submit"]
    assert panel.inner_text("#message") != strings["en"]["m_check_submit"]


@pytest.mark.extension
def test_a_captcha_is_a_code_too(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/challenge.html")
    sent = _run_with_stubbed_messaging(page, {"packet": _plain_packet(fixture_server)})
    assert sent[-1]["patch"] == {"status": "blocked", "message": "captcha"}


@pytest.mark.extension
def test_the_plain_address_button_after_stop_types_nothing(browser_context, fixture_server) -> None:
    """M4: Stop forgets the email control the run held."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    _content_with_listener(page, {"packet": _email_packet(fixture_server)})
    _deliver(page, _start("en", fixture_server))
    _final_status(page)
    _deliver(page, {"type": "stop"})

    page.evaluate("() => window.__elmify_use_plain()")
    sent = page.evaluate("() => window.__sent")

    assert page.input_value("#em") == TAGGED
    assert [m for m in _of_type(sent, "address") if m["event"] == "rejected"] == []
    assert sent[-1]["patch"]["message"] == "plain_not_started"


@pytest.mark.extension
def test_a_held_value_is_explained_in_the_panel(browser_context) -> None:
    page = _open_panel(browser_context)
    page.select_option("#language", "en")
    _push_state(
        page,
        {
            "status": "blocked",
            "fields": [
                {"key": "personal.given_name", "state": "mismatch", "reason": "held_other",
                 "placed": True},
            ],
        },
    )
    text = page.locator("#fields").inner_text()
    assert "Check this" in text
    assert (
        "Given name — This field already held another value — we left it. Please check it."
        in text
    )
    assert "1 need you" in page.inner_text("#progress")


@pytest.mark.extension
def test_the_next_step_chip_shows_where_the_student_must_answer(
    browser_context, fixture_server
) -> None:
    """M5: the chip was never passed in production; a portal error needs an answer."""
    page = browser_context.new_page()
    url = f"{fixture_server}/portal_error_form.html"
    page.goto(url)
    _run_with_stubbed_messaging(page, {"packet": _plain_packet(url)})
    assert "Answer this" in page.evaluate("() => window.__elmify_marks_text()")


@pytest.mark.extension
def test_no_chip_when_nothing_needs_the_student(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/plain_form.html"
    page.goto(url)
    _run_with_stubbed_messaging(page, {"packet": _plain_packet(url)})
    assert "Answer this" not in page.evaluate("() => window.__elmify_marks_text()")


@pytest.mark.extension
def test_a_field_whose_mark_could_not_be_placed_says_so_in_the_panel(browser_context) -> None:
    """M6: the panel is the only place such a field is shown."""
    page = _open_panel(browser_context)
    page.select_option("#language", "en")
    _push_state(
        page,
        {
            "status": "blocked",
            "fields": [
                {"key": "personal.given_name", "state": "filled", "reason": "", "placed": False},
                {"key": "personal.family_name", "state": "filled", "reason": "", "placed": True},
                {"key": "personal.country", "state": "elsewhere", "reason": "", "placed": False},
            ],
        },
    )
    items = page.locator("#fields li").all_inner_texts()
    # grouped by state: "On another page" comes before "Filled"; elsewhere has no mark
    assert items == ["Country", "Given name · shown here only", "Family name"]


# --- Security + ponytail fix wave ---------------------------------------------


@pytest.mark.extension
def test_storage_local_is_locked_to_trusted_contexts_before_any_injection(browser_context) -> None:
    """S1: content scripts may read storage.local unless the worker locks it,
    and the token is there. Nothing is injected until the lock has landed."""
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {},
        session=_binding(active=False),
        tabs={7: {"id": 7, "url": f"{PORTAL}/apply"}},
        hold_lock=True,
    )
    assert _calls(page, "storage.local.setAccessLevel") == [[{"accessLevel": "TRUSTED_CONTEXTS"}]]
    page.evaluate(
        """(sender) => { window.__on.message[0](
            { type: "start-fill", tabId: 7 }, sender, (r) => { window.__started = r; }); }""",
        PANEL_SENDER,
    )
    page.wait_for_timeout(150)
    assert _calls(page, "executeScript") == []

    page.evaluate("() => window.__unlock()")
    page.wait_for_function("() => window.__started !== undefined")
    assert _calls(page, "executeScript") == [INJECT_7]


@pytest.mark.extension
def test_a_page_s_dock_message_is_a_code_or_nothing(browser_context) -> None:
    """S2: a sentence from a portal page would be shown verbatim in our panel."""
    page = _content_worker(browser_context)
    lure = {"message": "Your session expired. Sign in at https://evil.example", "status": "filling"}

    assert _send(page, {"type": "dock", "patch": lure}, CONTENT) == {"ok": True}
    dock = page.evaluate("() => window.__session.dock")
    assert "message" not in dock
    assert dock["status"] == "filling"

    _send(page, {"type": "dock", "patch": {"message": "check_submit"}}, CONTENT)
    assert page.evaluate("() => window.__session.dock.message") == "check_submit"


@pytest.mark.extension
def test_a_page_s_dock_status_fields_and_documents_come_from_our_own_vocabulary(
    browser_context,
) -> None:
    """The S2 lure through the other keys the panel prints: a status, a field
    key and a filename must be ours (a known status, the packet's own fields
    and documents), never text a page made up."""
    page = _content_worker(browser_context)
    lure = "Your session expired. Sign in at https://evil.example"
    field = {"state": "filled", "reason": "", "placed": True}
    patch = {
        "status": lure,
        "fields": [{**field, "key": "contact.email"}, {**field, "key": "your_session_expired"}],
        "documents": [
            {"filename": "cv.pdf", "state": "attached"},
            {"filename": lure, "state": "manual"},
        ],
    }
    assert _send(page, {"type": "dock", "patch": patch}, CONTENT) == {"ok": True}
    dock = page.evaluate("() => window.__session.dock")
    assert "status" not in dock
    assert [f["key"] for f in dock["fields"]] == ["contact.email"]
    assert dock["documents"] == [{"filename": "cv.pdf", "state": "attached"}]

    _send(page, {"type": "dock", "patch": {"status": "review"}}, CONTENT)
    assert page.evaluate("() => window.__session.dock.status") == "review"


@pytest.mark.extension
def test_the_panel_is_off_by_default_and_on_only_for_the_tabs_we_enable(browser_context) -> None:
    """T1: a global default of disabled lets the toolbar open the panel without
    knowing which tabs are bound."""
    page = _load_worker(browser_context, {}, {})
    assert _calls(page, "sidePanel.setOptions")[0] == [{"enabled": False}]


@pytest.mark.extension
def test_a_click_on_a_cold_worker_opens_the_panel_in_the_same_turn(browser_context) -> None:
    """T1: the worker woke for this click and has not read its bindings yet.
    Chrome opens the panel only where it is enabled for the tab."""
    page = _load_worker(browser_context, {}, {})  # nothing primed: boundTabs is empty
    opened = page.evaluate(
        """() => {
            window.__on.action[0]({ id: 7, url: "https://portal.example/apply" });
            return window.__calls.filter((c) => c[0] === "sidePanel.open").map((c) => c[1]);
        }"""
    )
    assert opened == [[{"tabId": 7}]]
    page.wait_for_timeout(100)
    assert _calls(page, "permissions.request") == []  # the portal is not the paired dashboard


@pytest.mark.extension
def test_stop_disables_the_tab_s_panel_and_a_page_load_re_enables_a_started_one(
    browser_context,
) -> None:
    page = _load_worker(
        browser_context,
        {},
        {},
        session=_binding(),
        tabs={7: {"id": 7, "url": f"{PORTAL}/apply"}},
    )
    enable = [{"tabId": 7, "path": "panel.html", "enabled": True}]

    _page_loaded(page, 7, f"{PORTAL}/p2")
    assert enable in _calls(page, "sidePanel.setOptions")

    _send(page, {"type": "stop-fill", "tabId": 7}, PANEL_SENDER)
    calls = _calls(page, "sidePanel.setOptions")
    assert calls[-1] == [{"tabId": 7, "enabled": False}]

    _page_loaded(page, 7, f"{PORTAL}/p3")  # stopped: stays off
    assert _calls(page, "sidePanel.setOptions") == calls


@pytest.mark.extension
def test_start_after_stop_turns_the_tab_s_panel_back_on(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {},
        session=_binding(),
        tabs={7: {"id": 7, "url": f"{PORTAL}/apply"}},
    )
    _send(page, {"type": "stop-fill", "tabId": 7}, PANEL_SENDER)
    assert _calls(page, "sidePanel.setOptions")[-1] == [{"tabId": 7, "enabled": False}]

    _send(page, {"type": "start-fill", "tabId": 7}, PANEL_SENDER)
    assert _calls(page, "sidePanel.setOptions")[-1] == [
        {"tabId": 7, "path": "panel.html", "enabled": True}
    ]


@pytest.mark.extension
def test_a_page_load_before_start_keeps_the_tab_s_panel(browser_context) -> None:
    """Apply opens the portal; a login redirect before Start must not lose the
    panel the student has not used yet."""
    page = _load_worker(
        browser_context,
        {},
        {},
        session=_binding(active=False),
        tabs={7: {"id": 7, "url": f"{PORTAL}/login"}},
    )
    _page_loaded(page, 7, f"{PORTAL}/apply")
    assert [{"tabId": 7, "path": "panel.html", "enabled": True}] in _calls(
        page, "sidePanel.setOptions"
    )
    assert _calls(page, "executeScript") == []  # not started: nothing injected


@pytest.mark.extension
def test_the_dashboard_panel_is_enabled_before_it_is_opened(browser_context) -> None:
    page = _load_worker(browser_context, {}, {})
    page.evaluate(
        "() => window.__on.action[0]({ id: 1, url: 'https://dash.example/dashboard/' })"
    )
    page.wait_for_timeout(100)
    names = page.evaluate(
        """() => window.__calls
            .filter((c) => c[0].startsWith('sidePanel'))
            .map((c) => [c[0], c[1][0]])"""
    )
    enable = ["sidePanel.setOptions", {"tabId": 1, "path": "panel.html", "enabled": True}]
    assert enable in names
    assert names.index(enable) < len(names) - 1
    assert names[-1] == ["sidePanel.open", {"tabId": 1}]


@pytest.mark.extension
def test_start_from_a_panel_that_shows_another_tab_is_refused(browser_context) -> None:
    """M1: a stale Start for an old tab must not re-activate it."""
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 9, "origin": PORTAL}},
        {},
        session=_binding(active=False),
        tabs={7: {"id": 7, "url": f"{PORTAL}/apply"}},
    )
    reply = _send(page, {"type": "start-fill", "tabId": 7}, PANEL_SENDER)
    assert reply["ok"] is False
    assert _calls(page, "executeScript") == []
    assert page.evaluate("() => window.__session.bindings['7'].active") is False


@pytest.mark.extension
def test_the_chip_shows_when_only_a_held_value_needs_the_student(
    browser_context, fixture_server
) -> None:
    """M2: a held_other check needs the student as much as a red field does."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/prefilled_by_student.html")
    _run_with_stubbed_messaging(page, {"packet": _plain_packet(fixture_server)})
    assert "Answer this" in page.evaluate("() => window.__elmify_marks_text()")


LOGIN_REPLY = {"username": TAGGED, "password": "Gq7-xR2!mN8_vL4.kP9#wT3z"}


def _portal_login(page, extra=None, sender=CONTENT):
    message = {
        "type": "portal-login",
        "applicationId": APP_A,
        "page": "login",
        "host": "portal.example",
    }
    return _send(page, {**message, **(extra or {})}, sender)


@pytest.mark.extension
def test_the_worker_hands_the_login_to_its_own_tab_and_keeps_no_copy(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    assert _portal_login(page) == {"ok": True, **LOGIN_REPLY}
    assert LOGIN_REPLY["password"] not in json.dumps(page.evaluate("() => window.__session"))
    fetched = page.evaluate("() => window.__fetched")
    sent = [body for key, body in fetched if key.endswith("/portal-login")]
    assert sent == [{"page": "login", "host": "portal.example"}]


@pytest.mark.extension
@pytest.mark.parametrize(
    ("extra", "sender", "code"),
    [
        ({"host": "login.example.com"}, CONTENT, "untrusted_sender"),
        ({"page": "reset"}, CONTENT, "invalid_message"),
        ({"max_length": "24"}, CONTENT, "invalid_message"),
        ({}, PANEL_SENDER, "untrusted_sender"),
        ({}, {**CONTENT, "frameId": 3}, "untrusted_sender"),
        ({}, {**CONTENT, "origin": "https://evil.example"}, "untrusted_sender"),
    ],
)
def test_a_login_goes_to_no_other_host_frame_or_sender(
    browser_context, extra, sender, code
) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    assert _portal_login(page, extra, sender) == {"ok": False, "code": code}
    fetched = page.evaluate("() => window.__fetched")
    assert not [k for k, _ in fetched if k.endswith("/portal-login")]


@pytest.mark.extension
def test_a_server_refusal_reaches_the_page_as_its_code(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [409, {"error": "student_managed"}]},
        session=_binding(),
    )
    assert _portal_login(page) == {"ok": False, "code": "student_managed"}


def _login_fetches(page) -> int:
    fetched = page.evaluate("() => window.__fetched")
    return len([key for key, _ in fetched if key.endswith("/portal-login")])


@pytest.mark.extension
def test_a_second_login_page_without_reaching_the_form_gets_no_password(browser_context) -> None:
    """We typed a login and the next page is a login page again: the portal
    did not take it. Asking again would retype a wrong password toward a lockout."""
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    assert _portal_login(page)["ok"] is True
    assert _portal_login(page) == {"ok": False, "code": "login_not_accepted"}
    assert _login_fetches(page) == 1
    session = page.evaluate("() => window.__session")
    assert session["bindings"]["7"]["loginTyped"] is True
    assert LOGIN_REPLY["password"] not in json.dumps(session)
    assert LOGIN_REPLY["username"] not in json.dumps(session["bindings"])


@pytest.mark.extension
def test_reaching_the_form_lets_the_next_login_through(browser_context) -> None:
    """A portal that logs the student out mid-form still gets its login typed."""
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    assert _portal_login(page)["ok"] is True
    _send(page, {"type": "dock", "patch": {"status": "login", "message": "log_in_typed"}}, CONTENT)
    assert _send(page, {"type": "dock", "patch": {"status": "filling"}}, CONTENT) == {"ok": True}
    assert _portal_login(page)["ok"] is True
    assert _login_fetches(page) == 2


@pytest.mark.extension
def test_a_sign_up_does_not_count_as_a_login_typed(browser_context) -> None:
    """Portals commonly send a new account to their login page next; that is
    not a refused login."""
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    assert _portal_login(page, {"page": "signup"})["ok"] is True
    assert _portal_login(page)["ok"] is True
    assert _login_fetches(page) == 2


def _type_code(page, code, origin):
    return page.evaluate(
        """([code, origin]) => new Promise((resolve) => {
            const keep = window.__listeners[0]({ type: "type-code", code, origin }, {}, resolve);
            if (!keep) resolve(undefined);
        })""",
        [code, origin],
    )


@pytest.mark.extension
@pytest.mark.parametrize(
    ("fixture", "box"), [("code_page.html", "#otp"), ("code_named.html", "#vc")]
)
def test_a_code_page_asks_for_the_mail_and_takes_the_code(
    browser_context, fixture_server, fixture, box
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/{fixture}")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "await-code": {"ok": True, "watching": True}},
    )
    page.evaluate(
        "() => { window.__submitted = false; document.querySelector('form').addEventListener("
        "'submit', (e) => { window.__submitted = true; e.preventDefault(); }); }"
    )

    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'await-code')")
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    sent = page.evaluate("() => window.__sent")
    assert {"type": "await-code", "applicationId": "app-1"} in sent
    assert {"message": "waiting_code"} in [m["patch"] for m in sent if m["type"] == "dock"]

    assert _type_code(page, "482913", fixture_server) == {"typed": True}
    assert page.input_value(box) == "482913"
    assert page.evaluate("() => window.__submitted") is False


@pytest.mark.extension
def test_a_split_code_input_is_left_to_the_student(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/code_split.html")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})
    assert _type_code(page, "482913", fixture_server) == {"typed": False}
    assert page.evaluate(
        "() => [...document.querySelectorAll('input')].every((i) => i.value === '')"
    )


@pytest.mark.extension
def test_a_postal_code_box_is_not_a_code_box(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/postal_code.html")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})
    assert page.evaluate("() => window.__elmify_code_field()") is None
    assert _type_code(page, "482913", fixture_server) == {"typed": False}
    assert page.input_value("#pc") == ""


@pytest.mark.extension
@pytest.mark.parametrize(
    ("code", "origin_of"),
    [
        ("482913", "other"),
        ("48 29", "self"),
        ("<b>1</b>", "self"),
        ("1234567890123", "self"),
        ("", "self"),
    ],
)
def test_a_code_from_elsewhere_or_not_a_code_is_never_typed(
    browser_context, fixture_server, code, origin_of
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/code_page.html")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})
    origin = fixture_server if origin_of == "self" else "https://evil.example"
    assert _type_code(page, code, origin) == {"typed": False}
    assert page.input_value("#otp") == ""


@pytest.mark.extension
def test_a_code_never_types_over_what_the_student_typed(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/code_page.html")
    page.fill("#otp", "111111")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})
    assert _type_code(page, "482913", fixture_server) == {"typed": False}
    assert page.input_value("#otp") == "111111"


@pytest.mark.extension
def test_a_sign_up_starts_watching_for_the_portal_s_mail(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/signup.html")
    _content_with_listener(
        page, {"packet": _plain_packet(fixture_server), "portal-login": {"ok": True, **LOGIN_REPLY}}
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'await-code')")
    sent = page.evaluate("() => window.__sent")
    assert {"type": "await-code", "applicationId": "app-1"} in sent


CODE_ACTION = {
    "id": ACTION_ID,
    "kind": "TYPE_CODE",
    "application_id": APP_A,
    "payload": {"code": "482913"},
    "expires_at": "2099-01-01T00:00:00Z",
}


def _watching(page):
    return page.evaluate("() => window.__session.codeWatch ?? {}")


def _tick(page):
    page.evaluate(
        "(id) => Promise.all(window.__on.alarm.map((fn) => fn({ name: `code-watch:${id}` })))",
        APP_A,
    )


def _typing_tab(page, typed):
    page.evaluate(
        """(typed) => { chrome.tabs.sendMessage = async (...args) => {
            window.__calls.push(["tabs.sendMessage", args]); return { typed }; }; }""",
        typed,
    )


def _results(page):
    fetched = page.evaluate("() => window.__fetched")
    return [body for key, body in fetched if key.endswith("/result")]


def _code_worker(
    browser_context,
    actions,
    *,
    check=(202, {"queued": 1}),
    tab_url=f"{PORTAL}/verify",
    watch=None,
    binding_app=APP_A,
):
    session = _binding()
    session["bindings"]["7"]["applicationId"] = binding_app
    if watch:
        session["codeWatch"] = watch
    return _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {
            "POST /ext/mailbox/check": list(check),
            "GET /ext/actions": [200, {"actions": actions}],
            f"POST /ext/actions/{ACTION_ID}/result": [200, {"completed": True}],
        },
        session=session,
        tabs={7: {"id": 7, "url": tab_url}},
    )


@pytest.mark.extension
def test_a_code_from_the_inbox_is_typed_into_its_own_tab(browser_context) -> None:
    page = _code_worker(browser_context, [CODE_ACTION])
    _typing_tab(page, True)

    assert _send(page, {"type": "await-code", "applicationId": APP_A}, CONTENT) == {
        "ok": True,
        "watching": True,
    }
    assert APP_A in _watching(page)
    _tick(page)

    assert _calls(page, "tabs.sendMessage") == [
        [7, {"type": "type-code", "code": "482913", "origin": PORTAL}, {"frameId": 0}]
    ]
    dock = page.evaluate("() => window.__session.dock")
    assert dock["message"] == "code_typed" and dock.get("code") is None
    assert _results(page) == [{"ok": True, "detail": {"typed": True}}]
    assert _watching(page) == {}


@pytest.mark.extension
@pytest.mark.parametrize(
    ("typed", "tab_url", "binding_app"),
    [
        (False, f"{PORTAL}/verify", APP_A),  # the page has no single code box any more
        (True, "https://elsewhere.example/x", APP_A),  # the tab left the portal
        (True, f"{PORTAL}/verify", APP_B),  # no tab bound to this application
    ],
)
def test_a_code_that_cannot_be_typed_is_shown_in_the_panel(
    browser_context, typed, tab_url, binding_app
) -> None:
    page = _code_worker(browser_context, [CODE_ACTION], tab_url=tab_url, binding_app=binding_app)
    _typing_tab(page, typed)

    _page_loaded(page, 9, "https://dash.example/student/")  # a dashboard load polls actions

    dock = page.evaluate("() => window.__session.dock")
    assert dock["message"] == "code_shown" and dock["code"] == "482913"
    if tab_url.startswith("https://elsewhere") or binding_app == APP_B:
        assert _calls(page, "tabs.sendMessage") == []
    assert _results(page) == [{"ok": True, "detail": {"typed": False}}]


@pytest.mark.extension
@pytest.mark.parametrize("code", ["48 29", "<b>1</b>", "1234567890123", 482913])
def test_a_payload_that_is_not_a_code_goes_nowhere(browser_context, code) -> None:
    page = _code_worker(browser_context, [{**CODE_ACTION, "payload": {"code": code}}])
    _typing_tab(page, True)
    _page_loaded(page, 9, "https://dash.example/student/")
    assert _calls(page, "tabs.sendMessage") == []
    assert page.evaluate("() => window.__session.dock.code ?? null") is None
    assert _results(page) == [{"ok": False, "detail": {"refused": "invalid_action"}}]


@pytest.mark.extension
def test_a_link_from_the_inbox_opens_in_a_new_tab_and_ends_the_watch(browser_context) -> None:
    link = {
        **CODE_ACTION,
        "kind": "OPEN_VERIFICATION_URL",
        "payload": {"url": f"{PORTAL}/verify?t=abc"},
    }
    page = _code_worker(browser_context, [link], watch={APP_A: {"until": 9e15, "ticks": 0}})
    _tick(page)
    assert _calls(page, "tabs.create") == [[{"url": f"{PORTAL}/verify?t=abc", "active": False}]]
    assert page.evaluate("() => window.__session.dock.message") == "link_opened"
    assert _watching(page) == {}


@pytest.mark.extension
@pytest.mark.parametrize("check", [[202, {"queued": 0}], [409, {"error": "mailbox_disconnected"}]])
def test_no_inbox_means_the_student_is_told_at_once(browser_context, check) -> None:
    page = _code_worker(browser_context, [], check=check)
    _send(page, {"type": "await-code", "applicationId": APP_A}, CONTENT)
    assert page.evaluate("() => window.__session.dock.message") == "type_code_yourself"
    assert _watching(page) == {}


@pytest.mark.extension
def test_ten_minutes_without_mail_hands_it_to_the_student(browser_context) -> None:
    page = _code_worker(browser_context, [], watch={APP_A: {"until": 1, "ticks": 3}})
    page.evaluate(
        "() => { window.__session.dock = { ...window.__session.dock, message: 'waiting_code' }; }"
    )
    _tick(page)
    assert page.evaluate("() => window.__session.dock.message") == "type_code_yourself"
    assert _watching(page) == {}


@pytest.mark.extension
def test_a_watch_checks_the_mailbox_three_times_at_most(browser_context) -> None:
    page = _code_worker(browser_context, [])
    _send(page, {"type": "await-code", "applicationId": APP_A}, CONTENT)
    _send(page, {"type": "await-code", "applicationId": APP_A}, CONTENT)  # extends, spends nothing
    for _ in range(12):
        _tick(page)
    fetched = page.evaluate("() => window.__fetched")
    checks = [k for k, _ in fetched if k == "POST /ext/mailbox/check"]
    assert len(checks) == 3


@pytest.mark.extension
@pytest.mark.parametrize(
    ("message", "sender"),
    [
        ({"type": "await-code", "applicationId": APP_B}, CONTENT),
        ({"type": "await-code", "applicationId": APP_A}, PANEL_SENDER),
        ({"type": "await-code", "applicationId": APP_A}, {**CONTENT, "frameId": 2}),
    ],
)
def test_only_the_bound_tab_may_start_a_watch_for_its_own_application(
    browser_context, message, sender
) -> None:
    page = _code_worker(browser_context, [])
    assert _send(page, message, sender) == {"ok": False, "code": "untrusted_sender"}
    assert _watching(page) == {}


@pytest.mark.extension
def test_a_watch_ask_without_an_application_is_refused(browser_context) -> None:
    page = _code_worker(browser_context, [])
    assert _send(page, {"type": "await-code"}, CONTENT) == {"ok": False, "code": "invalid_message"}
    assert _watching(page) == {}
    assert not [k for k, _ in page.evaluate("() => window.__fetched") if k.endswith("/check")]


@pytest.mark.extension
def test_the_panel_shows_a_code_only_when_it_could_not_be_typed(browser_context) -> None:
    page = _open_panel(browser_context)
    assert page.is_hidden("#code")
    _push_state(page, {"message": "code_shown", "code": "482913"})
    assert page.is_visible("#code")
    assert "482913" in page.inner_text("#code")
    _push_state(page, {"message": "code_typed", "code": None})
    assert page.is_hidden("#code")
    # The panel speaks the browser's language (az in this test browser), so the
    # check is "this message's own line", in whichever language is showing.
    lines = page.evaluate(
        "() => Object.values(window.__elmify_strings).map((table) => table.m_code_typed)"
    )
    assert page.inner_text("#message") in lines


@pytest.mark.extension
def test_a_code_reaches_the_panel_as_text_never_markup(browser_context) -> None:
    page = _open_panel(browser_context)
    _push_state(page, {"message": "code_shown", "code": "<b>1</b>"})
    assert "<b>1</b>" in page.inner_text("#code")
    assert page.evaluate("() => document.querySelector('#code b')") is None


@pytest.mark.extension
@pytest.mark.parametrize(
    "code", ["waiting_code", "code_typed", "code_shown", "link_opened", "type_code_yourself"]
)
def test_every_mail_message_has_its_own_line(browser_context, code) -> None:
    strings = _open_panel(browser_context).evaluate("() => window.__elmify_strings.en")
    assert f"m_{code}" in strings


# Final review of plan 3: each test below reproduces one finding.


@pytest.mark.extension
def test_a_code_page_with_no_inbox_keeps_type_it_yourself(browser_context, fixture_server) -> None:
    """The worker said "type it yourself" and started no watch: the page must
    not then claim the code is being fetched."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/code_page.html")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "await-code": {"ok": True, "watching": False}},
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'await-code')")
    page.wait_for_timeout(300)
    docks = [m["patch"] for m in page.evaluate("() => window.__sent") if m["type"] == "dock"]
    assert {"message": "waiting_code"} not in docks


@pytest.mark.extension
@pytest.mark.parametrize("check", [[202, {"queued": 0}], [409, {"error": "mailbox_disconnected"}]])
def test_the_watch_ask_says_whether_a_watch_runs(browser_context, check) -> None:
    page = _code_worker(browser_context, [], check=check)
    reply = _send(page, {"type": "await-code", "applicationId": APP_A}, CONTENT)
    assert reply == {"ok": True, "watching": False}
    running = _code_worker(browser_context, [])
    assert _send(running, {"type": "await-code", "applicationId": APP_A}, CONTENT) == {
        "ok": True,
        "watching": True,
    }


@pytest.mark.extension
@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("code_number_box.html", "AB12CD"),  # a number box blanks letters
        ("code_short_box.html", "AB12CD34"),  # maxlength 6 cannot hold 8
        ("code_first_marked.html", "482913"),  # a split box marked on its first digit only
    ],
)
def test_a_code_the_box_cannot_hold_is_not_reported_typed(
    browser_context, fixture_server, fixture, code
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/{fixture}")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})
    assert _type_code(page, code, fixture_server) == {"typed": False}
    assert page.evaluate(
        "() => [...document.querySelectorAll('input')].every((i) => i.value === '')"
    )


@pytest.mark.extension
@pytest.mark.parametrize("fixture", ["code_bank_reference.html", "code_login_captcha.html"])
def test_a_code_of_another_kind_is_not_the_mail_s_code_box(
    browser_context, fixture_server, fixture
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/{fixture}")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})
    assert page.evaluate("() => window.__elmify_code_field()") is None
    assert _type_code(page, "482913", fixture_server) == {"typed": False}


@pytest.mark.extension
def test_an_expired_watch_does_not_overwrite_the_fill_s_own_message(browser_context) -> None:
    page = _code_worker(browser_context, [], watch={APP_A: {"until": 1, "ticks": 3}})
    page.evaluate(
        "() => { window.__session.dock = { ...window.__session.dock, "
        "status: 'filling', message: 'fill_done' }; }"
    )
    _tick(page)
    assert page.evaluate("() => window.__session.dock.message") == "fill_done"
    assert _watching(page) == {}


@pytest.mark.extension
def test_reaching_the_form_ends_the_watch(browser_context) -> None:
    page = _code_worker(browser_context, [], watch={APP_A: {"until": 9e15, "ticks": 0}})
    assert _send(page, {"type": "dock", "patch": {"status": "filling"}}, CONTENT) == {"ok": True}
    assert _watching(page) == {}


@pytest.mark.extension
def test_a_code_for_no_application_ends_the_watch(browser_context) -> None:
    shared = {**CODE_ACTION, "application_id": None}
    page = _code_worker(browser_context, [shared], watch={APP_A: {"until": 9e15, "ticks": 0}})
    _tick(page)
    dock = page.evaluate("() => window.__session.dock")
    assert dock["message"] == "code_shown" and dock["code"] == "482913"
    assert _watching(page) == {}


@pytest.mark.extension
def test_an_action_without_a_handler_leaves_the_code_message_alone(browser_context) -> None:
    other = {
        **CODE_ACTION,
        "id": "55555555-5555-4555-8555-555555555555",
        "kind": "OPEN_UPLOAD_PAGE",
    }
    page = _code_worker(
        browser_context, [CODE_ACTION, other], watch={APP_A: {"until": 9e15, "ticks": 0}}
    )
    _typing_tab(page, True)
    _tick(page)
    assert page.evaluate("() => window.__session.dock.message") == "code_typed"


@pytest.mark.extension
@pytest.mark.parametrize(("label", "kind"), [
    ("CVs", "CV"), ("Resumes", "CV"), ("Transcripts", "TRANSCRIPT"),
    ("Academic records", "TRANSCRIPT"), ("Grade lists", "TRANSCRIPT"), ("Diplomas", "DIPLOMA"),
    ("Degree certificates", "DIPLOMA"), ("Recommendations", "REFERENCE_LETTER"),
    ("Referees", "REFERENCE_LETTER"), ("Reference letters", "REFERENCE_LETTER"),
    ("Language certificates", "LANGUAGE_CERTIFICATE"), ("Language tests", "LANGUAGE_CERTIFICATE"),
    ("Passports", "PASSPORT"),
])
def test_a_plural_label_still_names_its_kind(browser_context, label, kind) -> None:
    page = browser_context.new_page()
    page.set_content(_boxes(label))
    result = _attach_docs(page, [_doc(kind)])
    assert result["manual"] == []


@pytest.mark.extension
def test_a_longer_word_is_not_a_plural(browser_context) -> None:
    page = browser_context.new_page()
    page.set_content(_boxes("Upload your cvsomething"))
    result = _attach_docs(page, [_doc("CV")])
    assert result["attached"] == []


@pytest.mark.extension
def test_a_kindless_document_never_takes_a_box_naming_another_kind(browser_context) -> None:
    page = browser_context.new_page()
    page.set_content(_boxes("Transcript or other file (scan_2026)", "Scan 2026 notes"))
    result = _attach_docs(page, [{"filename": "scan-2026.pdf", "type": "application/pdf"}])
    assert dict(_landed(page)) == {"b0": "", "b1": "scan-2026.pdf|application/pdf"}
    assert result["manual"] == []


# --- Plan 4b final review I1/M5: upload notes and the refused bundle reach the panel ---

_NOTES = [{"kind": "DIPLOMA", "note": "signed"}, {"kind": "EVERY_DOCUMENT", "note": "too_large"}]


@pytest.mark.extension
def test_i1_the_packet_s_notes_reach_the_final_dock_patch(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    packet = _plain_packet(fixture_server)
    packet["packet"]["notes"] = _NOTES
    sent = _run_with_stubbed_messaging(page, {"packet": packet})
    final = [m["patch"] for m in sent if m.get("type") == "dock" and "message" in m["patch"]][-1]
    assert final["notes"] == _NOTES


@pytest.mark.extension
def test_i1_the_panel_says_each_note_in_words_and_the_bundle_once(browser_context) -> None:
    page = _open_panel(browser_context)
    page.select_option("#language", "en")
    _push_state(page, {"documents": [], "notes": _NOTES})
    shown = page.locator("#documents").inner_text()
    assert "Diploma — This document is digitally signed" in shown
    assert "all your documents in one PDF" in shown and "too large to read clearly" in shown
    assert shown.count("separately") == 1  # M5: the instruction is never repeated
    for code in ("DIPLOMA", "EVERY_DOCUMENT", "too_large", "signed\n"):
        assert code not in shown
    page.select_option("#language", "ru")
    shown = page.locator("#documents").inner_text()
    assert "Диплом" in shown and "цифровую подпись" in shown and "одним PDF" in shown
    _push_state(page, {"documents": [], "notes": [{"kind": "FROM_THE_FUTURE", "note": "x_y"}]})
    shown = page.locator("#documents").inner_text()
    assert "FROM_THE_FUTURE" not in shown and "x_y" not in shown


@pytest.mark.extension
@pytest.mark.parametrize("language", ["az", "tr", "ru", "en"])
def test_m5_the_bundle_line_says_its_instruction_once_in_every_language(
    browser_context, language
) -> None:
    page = _open_panel(browser_context)
    page.select_option("#language", language)
    strings = page.evaluate(f"() => window.__elmify_strings[{language!r}]")
    _push_state(page, {"documents": [], "notes": [{"kind": "EVERY_DOCUMENT", "note": "too_large"}]})
    shown = page.locator("#documents").inner_text()
    assert strings["n_bundle_failed"] in shown and strings["nb_too_large"] in shown
    assert strings["n_too_large"] not in shown


@pytest.mark.extension
def test_i1_a_page_s_dock_notes_are_only_the_packet_s_own(browser_context) -> None:
    """The S2 lure through notes: a page may report only the packet's own notes."""
    page = _content_worker(browser_context)
    session = page.evaluate("() => window.__session")
    key = f"packet:{APP_A}"
    page.evaluate(
        "([key, notes]) => { window.__session[key].notes = notes; }", [key, _NOTES[:1]]
    )
    assert key in session
    patch = {"notes": [*_NOTES, {"kind": "Sign in at https://evil.example", "note": "signed"}]}
    assert _send(page, {"type": "dock", "patch": patch}, CONTENT) == {"ok": True}
    assert page.evaluate("() => window.__session.dock.notes") == _NOTES[:1]


@pytest.mark.extension
def test_the_snapshot_says_which_section_each_control_is_in(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/repeated_degrees.html")
    page.fill("#i1", "Baku State University")
    page.add_script_tag(path=str(DIST / "content.js"))
    snapshot = page.evaluate("() => window.__elmify_snapshot()")
    by_id = {c["id"]: c for c in snapshot["controls"]}

    assert by_id["i2"]["heading"] == "Degree 2"
    assert by_id["t2o"]["heading"] == "Degree 2" and by_id["t2o"]["type"] == "file"
    assert by_id["cv"]["heading"] == ""  # a closed fieldset's legend must not leak
    assert "English translation" in by_id["t1e"]["context"]
    assert by_id["t1o"]["accept"] == ".pdf"
    assert "Baku State University" not in json.dumps(snapshot)  # still no values


@pytest.mark.extension
def test_a_hint_is_never_typed_and_is_the_students_turn(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    packet = {
        "application_id": "app-1", "portal_form_id": "form-1", "field_map_version": 1,
        "form_url": fixture_server, "documents": [],
        "issued_at": "2026-10-09T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z",
        "min_extension_version": "0.1.0", "confirmation_markers": None,
        "entries": [{"selector": "#gn", "method": "fill", "value": "Leyla",
                     "profile_field": "personal.given_name"}],
        "hints": [{"selector": "#em", "profile_field": "contact.email", "reason": "unsure"}],
    }
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": packet}})
    assert page.input_value("#gn") == "Leyla"
    assert page.input_value("#em") == ""
    dock = [m for m in sent if m.get("type") == "dock" and "fields" in m["patch"]][-1]["patch"]
    row = next(f for f in dock["fields"] if f["key"] == "contact.email")
    assert (row["state"], row["reason"]) == ("your_turn", "our_guess")


@pytest.mark.extension
def test_a_hint_on_a_prefilled_box_is_check_this_not_changed_by_you(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.fill("#em", "typed-earlier@example.com")
    packet = {
        "application_id": "app-1", "portal_form_id": "form-1", "field_map_version": 1,
        "form_url": fixture_server, "documents": [],
        "issued_at": "2026-10-09T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z",
        "min_extension_version": "0.1.0", "confirmation_markers": None,
        "entries": [],
        "hints": [{"selector": "#em", "profile_field": "contact.email", "reason": "unsure"}],
    }
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": packet}})
    assert page.input_value("#em") == "typed-earlier@example.com"
    dock = [m for m in sent if m.get("type") == "dock" and "fields" in m["patch"]][-1]["patch"]
    row = next(f for f in dock["fields"] if f["key"] == "contact.email")
    assert (row["state"], row["reason"]) == ("mismatch", "held_other")
    assert dock["status"] == "blocked"


@pytest.mark.extension
def test_two_degrees_with_the_same_label_each_fill_their_own_box(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/repeated_degrees.html")
    page.add_script_tag(path=str(DIST / "content.js"))
    page.evaluate("(entries) => window.__elmify_fill(entries)", [
        {"selector": "#i1", "method": "fill", "value": "Baku State University",
         "profile_field": "education.1.institution_original"},
        {"selector": "#i2", "method": "fill", "value": "ADA University",
         "profile_field": "education.2.institution_original"},
    ])
    assert page.input_value("#i1") == "Baku State University"
    assert page.input_value("#i2") == "ADA University"


@pytest.mark.extension
def test_a_slot_attaches_into_its_own_box_by_selector(browser_context, fixture_server) -> None:
    """The boxes' own rows say "Transcript"; the map's selector says which is which."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/repeated_degrees.html")
    page.add_script_tag(path=str(DIST / "content.js"))
    result = page.evaluate("""() => window.__elmify_attach([
        {filename: "transcript-en.pdf", bytes: new ArrayBuffer(8), selector: "#t1e",
         kind: "TRANSCRIPT"},
        {filename: "transcript-az.pdf", bytes: new ArrayBuffer(8), selector: "#t1o",
         kind: "TRANSCRIPT"},
    ])""")
    assert result["manual"] == []
    names = page.evaluate("""() => Object.fromEntries(
        Array.from(document.querySelectorAll("input[type=file]"))
          .map((i) => [i.id, i.files.length ? i.files[0].name : ""]))""")
    assert names["t1e"] == "transcript-en.pdf" and names["t1o"] == "transcript-az.pdf"


@pytest.mark.extension
def test_two_documents_for_one_slot_box_attach_one_and_leave_one_manual(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/repeated_degrees.html")
    page.add_script_tag(path=str(DIST / "content.js"))
    result = page.evaluate("""() => window.__elmify_attach([
        {filename: "first.pdf", bytes: new ArrayBuffer(8), selector: "#t1e", kind: "TRANSCRIPT"},
        {filename: "second.pdf", bytes: new ArrayBuffer(8), selector: "#t1e", kind: "TRANSCRIPT"},
    ])""")
    assert [a["filename"] for a in result["attached"]] == ["first.pdf"]
    assert result["manual"] == ["second.pdf"]
    assert page.evaluate("() => document.querySelector('#t1e').files[0].name") == "first.pdf"


@pytest.mark.extension
def test_a_slot_whose_visible_text_does_not_name_the_kind_is_left_to_the_student(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/repeated_degrees.html")
    page.add_script_tag(path=str(DIST / "content.js"))
    result = page.evaluate("""() => window.__elmify_attach([
        {filename: "passport.pdf", bytes: new ArrayBuffer(8), selector: "#t1e",
         kind: "PASSPORT"},
    ])""")
    assert result["attached"] == [] and result["manual"] == ["passport.pdf"]


@pytest.mark.extension
def test_a_slot_on_a_hidden_box_is_left_to_the_student(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/hidden_slot_trap.html")
    page.add_script_tag(path=str(DIST / "content.js"))
    result = page.evaluate("""() => window.__elmify_attach([
        {filename: "passport.pdf", bytes: new ArrayBuffer(8), selector: "#trap",
         kind: "PASSPORT"},
    ])""")
    assert result["attached"] == [] and result["manual"] == ["passport.pdf"]
    assert page.evaluate("() => document.querySelector('#trap').files.length") == 0


def _choice_packet(form_url, selectors):
    return {
        "application_id": "app-1", "portal_form_id": "form-1", "field_map_version": 1,
        "form_url": form_url, "documents": [], "entries": [],
        "issued_at": "2026-10-09T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z",
        "min_extension_version": "0.1.0", "confirmation_markers": None,
        "choices": [{"filename": "bsc.pdf", "download_path": "/ext/documents/x",
                     "kind": "TRANSCRIPT", "upload_id": "x", "selectors": selectors}],
    }


def _last_dock_with(sent, key):
    return [m for m in sent if m.get("type") == "dock" and key in m["patch"]][-1]["patch"]


@pytest.mark.extension
def test_a_choice_is_put_to_the_student_and_their_pick_is_attached(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/repeated_degrees.html"
    page.goto(url)
    sent = _run_with_stubbed_messaging(page, {
        "packet": {"ok": True, "packet": _choice_packet(url, ["#t1o", "#t2o"])},
        "document": {"ok": True, "base64": "e30="},
    })
    dock = _last_dock_with(sent, "choices")
    [choice] = dock["choices"]
    descriptions = [option["description"] for option in choice["options"]]
    assert "Degree 1" in descriptions[0] and "Degree 2" in descriptions[1]
    assert dock["status"] == "blocked"  # an open choice is the student's turn
    assert page.evaluate("() => document.querySelector('#t2o').files.length") == 0

    assert page.evaluate("() => window.__elmify_choice('bsc.pdf', '#t2o')") is True
    assert page.evaluate("() => document.querySelector('#t2o').files[0].name") == "bsc.pdf"
    after = _last_dock_with(page.evaluate("() => window.__sent"), "choices")
    assert after["choices"] == []
    assert after["documents"] == [{"filename": "bsc.pdf", "state": "attached"}]
    assert after["status"] == "review"
    # Answered once: a second pick, or a box the packet never offered, attaches nothing.
    assert page.evaluate("() => window.__elmify_choice('bsc.pdf', '#t1o')") is False
    assert page.evaluate("() => document.querySelector('#t1o').files.length") == 0


@pytest.mark.extension
def test_a_choice_never_attaches_into_a_box_it_did_not_offer(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/repeated_degrees.html"
    page.goto(url)
    _run_with_stubbed_messaging(page, {
        "packet": {"ok": True, "packet": _choice_packet(url, ["#t1o", "#t2o"])},
        "document": {"ok": True, "base64": "e30="},
    })
    assert page.evaluate("() => window.__elmify_choice('bsc.pdf', '#cv')") is False
    assert page.evaluate("() => document.querySelector('#cv').files.length") == 0


@pytest.mark.extension
def test_a_choice_with_one_visible_box_is_attach_manually_not_a_choice(
    browser_context, fixture_server
) -> None:
    """Nothing to choose between: the hidden box is no option, and code does
    not take the one left over either -- the student attaches it."""
    page = browser_context.new_page()
    url = f"{fixture_server}/hidden_slot_trap.html"
    page.goto(url)
    sent = _run_with_stubbed_messaging(page, {
        "packet": {"ok": True, "packet": _choice_packet(url, ["#cv", "#trap"])},
        "document": {"ok": True, "base64": "e30="},
    })
    dock = _last_dock_with(sent, "choices")
    assert dock["choices"] == []
    assert dock["documents"] == [{"filename": "bsc.pdf", "state": "manual"}]
    assert dock["status"] == "blocked"
    assert not [m for m in sent if m.get("type") == "document"]
    assert page.evaluate("() => document.querySelector('#cv').files.length") == 0


@pytest.mark.extension
def test_the_dock_asks_which_box_and_sends_the_student_s_pick(browser_context) -> None:
    page = _open_panel(browser_context)
    assert page.is_hidden("#choices")
    _push_state(page, {
        "status": "blocked",
        "binding": {"tabId": 7, "origin": "https://apply.example.edu"},
        "choices": [{"filename": "bsc.pdf", "options": [
            {"selector": "#t1o", "description": "<b>Degree 1</b> · Transcript"},
            {"selector": "#t2o", "description": "Degree 2 · Upload"},
        ]}],
    })
    assert page.is_visible("#choices")
    buttons = page.locator("#choice-list button")
    # Page text is shown as text: the markup is not rendered.
    assert buttons.nth(0).inner_text() == "<b>Degree 1</b> · Transcript"
    assert page.locator("#choice-list b").count() == 0
    buttons.nth(1).click()
    last = page.evaluate("() => window.__sent.at(-1)")
    assert last == {"type": "choice:answer", "tabId": 7, "filename": "bsc.pdf",
                    "selector": "#t2o"}


@pytest.mark.extension
def test_a_box_one_pick_filled_is_never_offered_again(browser_context, fixture_server) -> None:
    """Two choices over the same two boxes. The first pick takes #t1o; the
    second choice is left with #t2o alone, so it becomes the student's to
    attach -- and nothing ever lands on top of the first document."""
    page = browser_context.new_page()
    url = f"{fixture_server}/repeated_degrees.html"
    page.goto(url)
    packet = _choice_packet(url, ["#t1o", "#t2o"])
    packet["choices"].append({**packet["choices"][0], "filename": "msc.pdf",
                              "download_path": "/ext/documents/y", "upload_id": "y"})
    sent = _run_with_stubbed_messaging(page, {
        "packet": {"ok": True, "packet": packet}, "document": {"ok": True, "base64": "e30="},
    })
    assert len(_last_dock_with(sent, "choices")["choices"]) == 2

    assert page.evaluate("() => window.__elmify_choice('bsc.pdf', '#t1o')") is True
    after = _last_dock_with(page.evaluate("() => window.__sent"), "choices")
    assert after["choices"] == []
    assert after["documents"] == [
        {"filename": "bsc.pdf", "state": "attached"},
        {"filename": "msc.pdf", "state": "manual"},
    ]
    assert after["status"] == "blocked"
    for box in ("#t1o", "#t2o"):
        assert page.evaluate(f"() => window.__elmify_choice('msc.pdf', '{box}')") is False
    assert page.evaluate("() => document.querySelector('#t1o').files[0].name") == "bsc.pdf"
    assert page.evaluate("() => document.querySelector('#t2o').files.length") == 0


@pytest.mark.extension
def test_a_box_a_slot_filled_is_not_offered_to_a_choice(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/repeated_degrees.html"
    page.goto(url)
    packet = _choice_packet(url, ["#t1o", "#t1e", "#t2o"])
    packet["documents"] = [{"filename": "en.pdf", "download_path": "/ext/documents/z",
                            "upload_id": "z", "draft_id": None, "selector": "#t1e",
                            "kind": "TRANSCRIPT"}]
    sent = _run_with_stubbed_messaging(page, {
        "packet": {"ok": True, "packet": packet}, "document": {"ok": True, "base64": "e30="},
    })
    [choice] = _last_dock_with(sent, "choices")["choices"]
    assert [option["selector"] for option in choice["options"]] == ["#t1o", "#t2o"]


@pytest.mark.extension
def test_a_failed_download_after_a_pick_puts_the_choice_back_on_the_dock(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/repeated_degrees.html"
    page.goto(url)
    _run_with_stubbed_messaging(page, {
        "packet": {"ok": True, "packet": _choice_packet(url, ["#t1o", "#t2o"])},
        "document": {"ok": False, "code": "document_unavailable"},
    })
    before = len(page.evaluate("() => window.__sent"))
    assert page.evaluate("() => window.__elmify_choice('bsc.pdf', '#t2o')") is False
    later = page.evaluate("() => window.__sent")[before:]
    dock = _last_dock_with(later, "choices")
    assert [c["filename"] for c in dock["choices"]] == ["bsc.pdf"]
    assert dock["status"] == "blocked"


@pytest.mark.extension
def test_stop_and_a_new_page_clear_the_choice_buttons(browser_context) -> None:
    choices = [{"filename": "bsc.pdf", "options": [{"selector": "#a", "description": "A"}]}]
    page = _load_worker(
        browser_context, {"choices": choices}, {}, session=_binding(),
        tabs={7: {"id": 7, "url": f"{PORTAL}/apply"}},
    )
    _connect_dock(page)
    page.evaluate(f"() => {{ window.__session.dock.choices = {json.dumps(choices)}; }}")
    _page_loaded(page, 7, f"{PORTAL}/p2")
    assert page.evaluate("() => window.__session.dock.choices") == []

    page.evaluate(f"() => {{ window.__session.dock.choices = {json.dumps(choices)}; }}")
    assert _send(page, {"type": "stop-fill", "tabId": 7}, PANEL_SENDER) == {"ok": True}
    assert page.evaluate("() => window.__session.dock.choices") == []


def _plan5_worker(browser_context):
    """A worker whose cached packet carries plan 5's hints, a choice and an upload."""
    packet = _portal_packet()
    packet["documents"] = [
        {"filename": "cv.pdf", "download_path": DOC_PATH, "draft_id": "d1"},
        {"filename": "az.pdf", "download_path": "/ext/documents/u1", "draft_id": None,
         "upload_id": "u1", "selector": "#t1o", "kind": "TRANSCRIPT"},
    ]
    packet["hints"] = [{"selector": "#city", "profile_field": "address.city", "reason": "no_fact"}]
    packet["choices"] = [{"filename": "bsc.pdf", "download_path": "/ext/documents/x",
                          "kind": "TRANSCRIPT", "upload_id": "x", "selectors": ["#t1o", "#t2o"]}]
    return _load_worker(
        browser_context,
        {"language": "az", "binding": {"tabId": 7, "origin": PORTAL}},
        {},
        session={**_binding(), f"packet:{APP_A}": packet},
    )


@pytest.mark.extension
def test_a_page_s_hints_and_choices_pass_the_dock_filter_only_as_the_packet_s_own(
    browser_context,
) -> None:
    """Plan 5 on plan 1's filter: a hint's field, a choice's filename and its
    offered boxes are the packet's own; anything else a page writes is dropped."""
    page = _plan5_worker(browser_context)
    field = {"state": "your_turn", "reason": "no_fact", "placed": True}
    patch = {
        "fields": [{**field, "key": "address.city"}, {**field, "key": "made_up"}],
        "documents": [{"filename": "bsc.pdf", "state": "attached"},
                      {"filename": "lure.pdf", "state": "manual"}],
        "choices": [
            {"filename": "bsc.pdf", "options": [
                {"selector": "#t1o", "description": "Degree 1 · Transcript"},
                {"selector": "#evil", "description": "Sign in again"},
            ]},
            {"filename": "lure.pdf", "options": [{"selector": "#t1o", "description": "x"}]},
        ],
    }
    assert _send(page, {"type": "dock", "patch": patch}, CONTENT) == {"ok": True}
    dock = page.evaluate("() => window.__session.dock")
    assert [f["key"] for f in dock["fields"]] == ["address.city"]
    assert dock["documents"] == [{"filename": "bsc.pdf", "state": "attached"}]
    assert dock["choices"] == [
        {
            "filename": "bsc.pdf",
            "options": [{"selector": "#t1o", "description": "Degree 1 · Transcript"}],
        }
    ]


@pytest.mark.extension
def test_an_upload_crosses_as_base64_fetched_with_the_token_and_no_cookie(browser_context) -> None:
    page = _plan5_worker(browser_context)
    page.evaluate(
        """() => { window.fetch = async (url, init) => {
            const auth = init.headers.Authorization;
            window.__init = { url, credentials: init.credentials, auth };
            const headers = { "Content-Type": "image/png; charset=binary" };
            return new Response("{}", { status: 200, headers });
        }; }"""
    )
    reply = _send(page, {"type": "document", "path": "/ext/documents/u1"}, CONTENT)
    assert reply == {"ok": True, "base64": "e30="}
    assert page.evaluate("() => window.__init") == {
        "url": "https://dash.example/ext/documents/u1", "credentials": "omit", "auth": "Bearer t",
    }


def _gone_packet(form_url: str) -> dict[str, object]:
    return {
        "application_id": "app-1", "portal_form_id": "form-1", "field_map_version": 1,
        "form_url": form_url, "documents": [],
        "issued_at": "2026-10-09T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z",
        "min_extension_version": "0.1.0", "confirmation_markers": None,
        "entries": [
            {"selector": "#gone-1", "method": "fill", "value": "x",
             "profile_field": "personal.family_name"},
            {"selector": "#gone-2", "method": "fill", "value": "y",
             "profile_field": "contact.email"},
            {"selector": "#gn", "method": "fill", "value": "Leyla",
             "profile_field": "personal.given_name"},
        ],
    }


@pytest.mark.extension
def test_a_form_that_lost_most_of_its_controls_is_learned_again_once(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    packet = _gone_packet(f"{fixture_server}/plain_form.html")
    sent = _run_with_stubbed_messaging(page, {
        "packet": {"ok": True, "packet": packet}, "snapshot": {"ok": True},
    })
    snapshots = [m for m in sent if m["type"] == "snapshot"]
    assert len(snapshots) == 1  # once per run, never a loop
    assert snapshots[0]["applicationId"] == "app-1"
    assert page.input_value("#gn") == "Leyla"  # the run went on afterwards


@pytest.mark.extension
def test_a_page_that_is_not_the_form_page_never_triggers_a_relearn(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    packet = _gone_packet(f"{fixture_server}/two_page_form_page2.html")
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": packet}})
    assert not [m for m in sent if m["type"] == "snapshot"]


# --- Plan 5 Task 7: the answers channel ---------------------------------------


def _answers_packet(fixture_server, entries, hints):
    return {
        "application_id": "app-1", "portal_form_id": "form-1", "field_map_version": 1,
        "form_url": f"{fixture_server}/plain_form.html", "documents": [],
        "issued_at": "2026-10-09T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z",
        "min_extension_version": "0.1.0", "confirmation_markers": None,
        "entries": entries, "hints": hints,
    }


@pytest.mark.extension
def test_answers_carry_only_named_boxes_and_never_a_password(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.evaluate("""() => {
        const p = document.createElement("input");
        p.type = "password"; p.id = "pw";
        document.querySelector("form").appendChild(p);
    }""")
    packet = _answers_packet(
        fixture_server,
        [{"selector": "#gn", "method": "fill", "value": "Leyla",
          "profile_field": "personal.given_name"}],
        [
            {"selector": "#em", "profile_field": "contact.email", "reason": "unsure"},
            {"selector": "#pw", "profile_field": "identity.full_name", "reason": "unsure"},
        ],
    )
    _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": packet}})
    page.type("#em", "leyla@example.org")
    page.type("#pw", "secret")
    page.type("#fn", "Aliyeva")  # a box the packet never named
    page.fill("#gn", "Aysel")  # the student changes a box we filled
    page.evaluate("() => window.__elmify_review()")
    sent = page.evaluate("() => window.__sent")
    [message] = [m for m in sent if m["type"] == "answers"]
    assert message == {
        "type": "answers",
        "applicationId": "app-1",
        "answers": [
            {"selector": "#gn", "kind": "changed", "value": "Aysel"},
            {"selector": "#em", "kind": "hint", "value": "leyla@example.org"},
        ],
    }
    docks = [m["patch"] for m in sent if m["type"] == "dock"]
    fields = [f["key"] for f in [d for d in docks if "fields" in d][-1]["fields"]]
    assert "identity.full_name" not in fields  # the password box is never one of ours
    for typed in ("leyla@example.org", "secret", "Aliyeva", "Aysel"):
        assert typed not in json.dumps(docks), typed  # values never enter the dock


@pytest.mark.extension
def test_nothing_is_sent_before_the_student_presses_checked(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    packet = _answers_packet(
        fixture_server, [],
        [{"selector": "#em", "profile_field": "contact.email", "reason": "unsure"}],
    )
    _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": packet}})
    page.type("#em", "leyla@example.org")
    sent = page.evaluate("() => window.__sent")
    assert not [m for m in sent if m["type"] == "answers"]


@pytest.mark.extension
def test_an_earlier_answer_is_typed_back_past_the_label_check_and_labelled(
    browser_context, fixture_server
) -> None:
    """Decision B: the student chose this box for this answer before, so its
    label ("Family name") is not ours to judge; it is filled and labelled."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    packet = _answers_packet(
        fixture_server,
        [{"selector": "#fn", "method": "fill", "value": "Ganja",
          "profile_field": "personal.home_town", "from_answer": True}],
        [],
    )
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": packet}})
    assert page.input_value("#fn") == "Ganja"
    dock = [m for m in sent if m.get("type") == "dock" and "fields" in m["patch"]][-1]["patch"]
    [row] = dock["fields"]
    assert (row["key"], row["state"], row["reason"]) == (
        "personal.home_town", "filled", "from_your_answer",
    )
    # Without the flag the same entry is refused on its label, as every entry is.
    entry = {**packet["entries"][0], "from_answer": False}
    [verdict] = page.evaluate("(entries) => window.__elmify_verify(entries)", [entry])
    assert (verdict["ok"], verdict["reason"]) == (False, "name_mismatch")


@pytest.mark.extension
def test_the_review_press_is_the_dock_s_and_answers_post_for_the_bound_application(
    browser_context,
) -> None:
    answers = [{"selector": "#em", "kind": "hint", "value": "leyla@example.org"}]
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/answers": [201, {"recorded": 1}]},
        session=_binding(),
    )
    review = {"type": "review:open", "tabId": 7}
    assert _send(page, review, CONTENT) == {"ok": False, "code": "untrusted_sender"}
    assert _calls(page, "tabs.sendMessage") == []
    assert _send(page, review, PANEL_SENDER) == {"ok": True}
    assert _calls(page, "tabs.sendMessage") == [[7, {"type": "review:open"}]]

    message = {"type": "answers", "applicationId": APP_A, "answers": answers}
    assert _send(page, message, CONTENT) == {"ok": True}
    assert page.evaluate("() => window.__fetched") == [
        [f"POST /ext/applications/{APP_A}/answers", {"answers": answers}],
    ]
    other = {**message, "applicationId": APP_B}
    assert _send(page, other, CONTENT) == {"ok": False, "code": "untrusted_sender"}
    assert _send(page, message, PANEL_SENDER) == {"ok": False, "code": "untrusted_sender"}


@pytest.mark.extension
def test_a_file_box_the_student_filled_is_never_sent_as_an_answer(
    browser_context, fixture_server, tmp_path
) -> None:
    """A file box's value is a local path ("C:\\fakepath\\..."), not an answer."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.evaluate("""() => {
        const label = document.createElement("label");
        label.htmlFor = "up"; label.textContent = "Upload";
        const box = document.createElement("input");
        box.type = "file"; box.id = "up";
        document.querySelector("form").append(label, box);
    }""")
    packet = _answers_packet(
        fixture_server, [],
        [
            {"selector": "#up", "profile_field": "personal.home_town", "reason": "unsure"},
            {"selector": "#em", "profile_field": "contact.email", "reason": "unsure"},
        ],
    )
    _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": packet}})
    chosen = tmp_path / "cv.pdf"
    chosen.write_bytes(b"%PDF-1.4")
    page.set_input_files("#up", str(chosen))
    page.type("#em", "leyla@example.org")
    page.evaluate("() => window.__elmify_review()")
    sent = page.evaluate("() => window.__sent")
    fields = {
        f["key"]: f["state"]
        for f in [m["patch"] for m in sent if m["type"] == "dock" and "fields" in m["patch"]][-1][
            "fields"
        ]
    }
    assert fields["personal.home_town"] == "changed_by_you"  # the pick was the student's
    [message] = [m for m in sent if m["type"] == "answers"]
    assert message["answers"] == [
        {"selector": "#em", "kind": "hint", "value": "leyla@example.org"},
    ]


@pytest.mark.extension
def test_a_saved_copy_carries_no_value_and_no_script(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.fill("#gn", "Orkhan")
    page.fill("#em", "owner@example.org")
    page.evaluate("""() => {
        const s = document.createElement("script"); s.textContent = "window.x = 1";
        document.body.appendChild(s);
        document.querySelector("#gn").setAttribute("onblur", "steal()");
        document.querySelector("#fn").setAttribute("value", "Abdullayev");
        const essay = document.createElement("div");
        essay.id = "essay"; essay.setAttribute("contenteditable", "true");
        essay.textContent = "My motivation, by Orkhan";
        document.body.appendChild(essay);
    }""")
    page.add_script_tag(path=str(DIST / "content.js"))
    html = page.evaluate("() => window.__elmify_saved_copy()")
    assert "Orkhan" not in html and "owner@example.org" not in html
    assert "Abdullayev" not in html  # a served, pre-filled value attribute too
    assert "My motivation" not in html  # a rich-text box's text (preflight #7)
    assert "<script" not in html.lower() and "onblur" not in html.lower()
    assert 'id="gn"' in html and 'id="essay"' in html  # the structure survives
    # The live page is untouched: the copy is built on a clone.
    assert page.input_value("#gn") == "Orkhan"
    assert page.evaluate("() => document.querySelectorAll('script').length") >= 1


@pytest.mark.extension
def test_a_saved_copy_scrubs_templates_and_disguised_script_urls(
    browser_context, fixture_server
) -> None:
    """querySelectorAll never enters a <template>, while outerHTML serializes
    it; and the URL parser drops a tab or a control character from a scheme."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.evaluate("""() => {
        document.body.insertAdjacentHTML("beforeend",
            '<template id="t"><input value="owner@x.org"><script>s()</script>' +
            '<img src="x" onerror="e()"><template><textarea>Orkhan essay</textarea>' +
            '</template></template>' +
            '<a id="tab" href="java&#9;script:steal()">a</a>' +
            '<a id="ctl" href="\u0001javascript:steal()">b</a>' +
            '<input type="checkbox" id="cb" checked><select id="sel">' +
            '<option>A</option><option selected>Baku</option></select>' +
            '<textarea id="ta">served essay</textarea>');
    }""")
    page.add_script_tag(path=str(DIST / "content.js"))
    html = page.evaluate("() => window.__elmify_saved_copy()")
    assert "owner@x.org" not in html and "Orkhan essay" not in html
    assert "<script" not in html.lower() and "onerror" not in html.lower()
    assert "steal()" not in html
    assert "checked" not in html and "selected" not in html and "served essay" not in html
    assert 'id="t"' in html and 'id="tab"' in html  # the structure survives


@pytest.mark.extension
def test_a_snapshot_context_never_carries_a_rich_text_box_s_text(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.evaluate("""() => {
        const fieldset = document.createElement("fieldset");
        fieldset.innerHTML = '<legend>Motivation</legend><input id="title" name="title">' +
            '<div contenteditable="true">My essay, by Orkhan</div>';
        document.querySelector("form").appendChild(fieldset);
    }""")
    page.add_script_tag(path=str(DIST / "content.js"))
    snapshot = page.evaluate("() => window.__elmify_snapshot()")
    control = next(c for c in snapshot["controls"] if c["id"] == "title")
    assert "Motivation" in control["context"]
    assert "Orkhan" not in json.dumps(snapshot)


@pytest.mark.extension
@pytest.mark.parametrize("typed, shown, rule, green", [
    ("Işıl", "IŞIL", "casefold", True),  # Turkish dotless i, upper on both sides
    ("İpek", "İPEK", "casefold", True),
    ("Leyla", "LEYLA", None, False),  # no rule taught: amber
    ("Lala", "LEYLA", "casefold", False),  # a different name never passes
    ("2001-03-17", "17.03.2001", "date", True),
    ("2001-03-07", "07.03.2001", "date", False),  # 7 March or 3 July: stays amber
    ("+994 50 123", "99450123", "digits", True),
    ("Baku", "B a k u", "digits", False),  # no digits on either side is no match
])
def test_read_back_honours_only_the_rule_the_bench_taught(
    browser_context, fixture_server, typed: str, shown: str, rule: str | None, green: bool
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.fill("#gn", shown)
    page.add_script_tag(path=str(DIST / "content.js"))
    entry = {"selector": "#gn", "method": "fill", "value": typed,
             "profile_field": "personal.given_name"}
    equivalences = {"personal.given_name": rule} if rule else {}
    result = page.evaluate("([e, q]) => window.__elmify_read_back(e, q)", [[entry], equivalences])
    assert (result["mismatches"] == []) is green


# Known gaps after plans 2 and 3: each test below reproduces one.


@pytest.mark.extension
def test_a_password_handed_out_but_never_typed_does_not_stop_the_next_login(
    browser_context,
) -> None:
    """A page that asked and then typed none of it (the box went away, the
    address was someone else's) must not send the student to delete a working
    password. It says so; the panel shows the ordinary "log in" line."""
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    assert _portal_login(page)["ok"] is True
    untyped = {"type": "dock", "patch": {"status": "login", "message": "log_in_untyped"}}
    assert _send(page, untyped, CONTENT) == {"ok": True}
    assert page.evaluate("() => window.__session.dock.message") == "log_in"
    assert _portal_login(page)["ok"] is True
    assert _login_fetches(page) == 2


@pytest.mark.extension
def test_the_worker_passes_a_came_back_sign_up_on_to_the_server(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    assert _portal_login(page, {"page": "signup", "came_back": True})["ok"] is True
    fetched = page.evaluate("() => window.__fetched")
    sent = [body for key, body in fetched if key.endswith("/portal-login")]
    assert sent == [{"page": "signup", "host": "portal.example", "came_back": True}]


@pytest.mark.extension
def test_closing_a_stopped_tab_leaves_another_tab_s_watch_alone(browser_context) -> None:
    page = _code_worker(browser_context, [], watch={APP_A: {"until": 9e15, "ticks": 0}})
    page.evaluate("() => { window.__session.bindings['7'].active = false; }")

    page.evaluate("() => Promise.all(window.__on.removed.map((fn) => fn(7)))")

    assert APP_A in _watching(page)


LOGIN_ADDRESS_REWRITTEN = """<form>
  <input id="u" type="text" oninput="if (!this.value.endsWith('!')) this.value += '!'">
  <input id="p" type="password"></form>"""


@pytest.mark.extension
def test_a_login_typed_only_in_part_still_counts_as_typed(browser_context, fixture_server) -> None:
    """The address box rewrote its value, the password box holds ours: the
    student can press Log in with our password, so the lockout guard must
    count it."""
    page, sent = _credential_shape(browser_context, fixture_server, LOGIN_ADDRESS_REWRITTEN)
    assert page.input_value("#p") == LOGIN_REPLY["password"]
    assert _docks(sent) == [{"status": "login", "message": "log_in_typed"}]


@pytest.mark.extension
def test_a_login_ask_without_an_application_is_refused(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    message = {"type": "portal-login", "page": "login", "host": "portal.example"}
    assert _send(page, message, CONTENT) == {"ok": False, "code": "invalid_message"}
    assert _login_fetches(page) == 0


@pytest.mark.extension
def test_a_storage_failure_answers_the_page_instead_of_leaving_it_waiting(
    browser_context,
) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    page.evaluate(
        "() => { const get = chrome.storage.local.get; chrome.storage.local.get = async (k) => "
        "{ if ([].concat(k).includes('origin')) throw new Error('storage'); return get(k); }; }"
    )
    message = {
        "type": "portal-login", "applicationId": APP_A, "page": "login", "host": "portal.example"
    }
    assert _send_or_timeout(page, message, CONTENT) == {"ok": False, "code": "pairing_required"}


@pytest.mark.extension
def test_stop_ends_the_watch_and_takes_the_code_down(browser_context) -> None:
    page = _code_worker(browser_context, [], watch={APP_A: {"until": 9e15, "ticks": 0}})
    page.evaluate("() => { window.__session.dock.code = '482913'; }")

    assert _send(page, {"type": "stop-fill", "tabId": 7}, PANEL_SENDER) == {"ok": True}

    assert _watching(page) == {}
    assert ["alarms.clear", [f"code-watch:{APP_A}"]] in page.evaluate("() => window.__calls")
    assert page.evaluate("() => window.__session.dock.code") is None


@pytest.mark.extension
def test_closing_the_portal_tab_ends_its_watch(browser_context) -> None:
    page = _code_worker(browser_context, [], watch={APP_A: {"until": 9e15, "ticks": 0}})

    page.evaluate("() => Promise.all(window.__on.removed.map((fn) => fn(7)))")

    assert _watching(page) == {}


@pytest.mark.extension
def test_reaching_the_form_takes_a_shown_code_down(browser_context) -> None:
    page = _code_worker(browser_context, [])
    page.evaluate("() => { window.__session.dock.code = '482913'; }")

    _send(page, {"type": "dock", "patch": {"status": "filling"}}, CONTENT)

    assert page.evaluate("() => window.__session.dock.code") is None


@pytest.mark.extension
@pytest.mark.parametrize(
    ("sender", "shown"),
    [("portal.uni-bonn.de", "portal.uni-bonn.de"), ("<b>x</b>", None), (None, None)],
)
def test_a_shown_code_names_the_portal_that_sent_it(browser_context, sender, shown) -> None:
    payload = {"code": "482913", **({"from": sender} if sender is not None else {})}
    page = _code_worker(browser_context, [{**CODE_ACTION, "payload": payload}], binding_app=APP_B)

    _page_loaded(page, 9, "https://dash.example/student/")

    dock = page.evaluate("() => window.__session.dock")
    assert dock["code"] == "482913"
    assert dock.get("code_from") == shown


@pytest.mark.extension
def test_the_panel_says_which_portal_a_code_is_for(browser_context) -> None:
    page = _open_panel(browser_context)
    _push_state(
        page, {"message": "code_shown", "code": "482913", "code_from": "portal.uni-bonn.de"}
    )
    text = page.inner_text("#code")
    assert "482913" in text and "portal.uni-bonn.de" in text


LOGIN_WITH_CAPTCHA = """<form>
  <input id="u" type="text"><input id="p" type="password">
  <div class="g-recaptcha" style="width:300px;height:80px"></div></form>"""
LOGIN_UNDER_A_BANNER = """<form><input id="u" type="text"><input id="p" type="password"></form>
  <div style="position:fixed;inset:0;background:#fff">We use cookies <button>OK</button></div>"""


@pytest.mark.extension
def test_a_login_page_with_a_captcha_is_typed_and_says_so(browser_context, fixture_server) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, LOGIN_WITH_CAPTCHA)
    assert _values(page) == {"u": TAGGED, "p": LOGIN_REPLY["password"]}
    events = [m for m in sent if m["type"] == "event"]
    assert [(m["kind"], m["detail"]) for m in events] == [("CHALLENGE", {"kind": "recaptcha"})]
    # "log_in_typed" first: it is what the worker's lockout guard counts.
    assert _docks(sent)[0] == {"status": "login", "message": "log_in_typed"}
    page.wait_for_function("() => window.__sent.filter((m) => m.type === 'dock').length === 2")
    assert _docks(page.evaluate("() => window.__sent"))[1] == {"message": "typed_captcha"}


@pytest.mark.extension
def test_a_login_under_a_cookie_banner_says_to_close_it(browser_context, fixture_server) -> None:
    page, sent = _credential_shape(browser_context, fixture_server, LOGIN_UNDER_A_BANNER)
    assert _of_type(sent, "portal-login") == []
    assert _values(page) == {"u": "", "p": ""}
    assert _docks(sent) == [{"status": "login", "message": "log_in_covered"}]


@pytest.mark.extension
@pytest.mark.parametrize("code", ["typed_captcha", "log_in_covered"])
def test_every_new_login_message_has_its_own_line(browser_context, code) -> None:
    strings = _open_panel(browser_context).evaluate("() => window.__elmify_strings")
    assert all(f"m_{code}" in table for table in strings.values())


@pytest.mark.extension
def test_an_unconfirmed_browser_tells_the_student_how_to_allow_it(
    browser_context, fixture_server
) -> None:
    """The server holds back portal passwords from a browser paired without the
    student's password; the panel says where to allow it, and nothing is typed."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    _content_with_listener(
        page,
        {
            "packet": _plain_packet(fixture_server),
            "portal-login": {"ok": False, "code": "browser_unconfirmed"},
        },
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    assert page.input_value("#password") == ""
    docks = [m["patch"] for m in page.evaluate("() => window.__sent") if m["type"] == "dock"]
    assert docks == [{"status": "login", "message": "browser_unconfirmed"}]
    strings = _open_panel(browser_context).evaluate("() => window.__elmify_strings")
    assert all("m_browser_unconfirmed" in table for table in strings.values())


FACT_ID = "55555555-5555-4555-8555-555555555555"


def _passport_packet(form_url, *, offer=True, upload_kind="", expired_on=""):
    hint = {"selector": "#dob", "profile_field": "identity.date_of_birth", "reason": "no_fact",
            "upload_kind": upload_kind, "expired_on": expired_on}
    if offer:
        hint["offer"] = {"fact_id": FACT_ID, "value": "1998-03-14", "method": "fill",
                         "source_kind": "passport"}
    return {
        "application_id": "app-1", "portal_form_id": "form-1", "field_map_version": 1,
        "form_url": form_url, "documents": [],
        "entries": [{"selector": "#pno", "method": "fill", "value": "C01X00T47",
                     "profile_field": "id_document.number", "source_kind": "passport"}],
        "hints": [hint],
        "issued_at": "2026-10-12T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z",
        "min_extension_version": "0.1.0", "confirmation_markers": None,
    }


@pytest.mark.extension
def test_an_offered_value_waits_for_the_tap_then_fills_its_one_box(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/passport_form.html"
    page.goto(url)
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True,
                                                         "packet": _passport_packet(url)}})
    fields = {f["key"]: f for f in _last_dock_with(sent, "fields")["fields"]}
    assert fields["identity.date_of_birth"]["reason"] == "offer"
    assert page.input_value("#dob") == ""  # nothing typed before the tap
    assert fields["id_document.number"]["reason"] == "from_passport"
    assert page.input_value("#pno") == "C01X00T47"

    assert page.evaluate("() => window.__elmify_offer('identity.date_of_birth', '1998-03-14')")
    assert page.input_value("#dob") == "1998-03-14"
    after = {f["key"]: f for f in _last_dock_with(page.evaluate("() => window.__sent"),
                                                   "fields")["fields"]}
    assert after["identity.date_of_birth"]["state"] == "filled"
    assert after["identity.date_of_birth"]["reason"] == "from_passport"
    page.focus("#dob")  # the why-tag shows on focus (marks.ts)
    assert "From your passport" in page.evaluate("() => window.__elmify_marks_text()")


@pytest.mark.extension
def test_an_offer_never_types_over_what_the_student_typed(browser_context, fixture_server):
    page = browser_context.new_page()
    url = f"{fixture_server}/passport_form.html"
    page.goto(url)
    _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": _passport_packet(url)}})
    page.fill("#dob", "1998-03-15")
    assert page.evaluate(
        "() => window.__elmify_offer('identity.date_of_birth', '1998-03-14')") is False
    assert page.input_value("#dob") == "1998-03-15"


@pytest.mark.extension
def test_an_offer_for_a_field_the_packet_did_not_offer_types_nothing(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/passport_form.html"
    page.goto(url)
    _run_with_stubbed_messaging(page, {"packet": {"ok": True,
                                                  "packet": _passport_packet(url, offer=False)}})
    assert page.evaluate("() => window.__elmify_offer('identity.date_of_birth', 'x')") is False
    assert page.evaluate("() => window.__elmify_offer('identity.citizenship', 'x')") is False
    assert page.input_value("#dob") == "" and page.input_value("#cit") == ""


@pytest.mark.extension
@pytest.mark.parametrize(("upload_kind", "expired_on", "reason"), [
    ("PASSPORT", "", "upload_once"),
    ("", "2026-03-01", "document_expired"),
])
def test_a_box_no_upload_supplies_says_what_to_upload(
    browser_context, fixture_server, upload_kind, expired_on, reason
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/passport_form.html"
    page.goto(url)
    packet = _passport_packet(url, offer=False, upload_kind=upload_kind, expired_on=expired_on)
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": packet}})
    fields = {f["key"]: f for f in _last_dock_with(sent, "fields")["fields"]}
    assert fields["identity.date_of_birth"]["reason"] == reason


@pytest.mark.extension
def test_a_passport_s_two_birth_boxes_each_verify_as_their_own(browser_context) -> None:
    """Plan 3 Task 3: "Place of birth" no longer also reads as the date of birth, so a
    passport fills both boxes; "Doğum yeri" is the place."""
    page = browser_context.new_page()
    page.set_content('<label for="d">Date of birth</label><input id="d">'
                     '<label for="p">Place of birth</label><input id="p">'
                     '<label for="y">Doğum yeri</label><input id="y">')
    entry = lambda selector, field: {  # noqa: E731
        "selector": selector, "method": "fill", "value": "x", "profile_field": field,
    }
    both = [entry("#d", "identity.date_of_birth"), entry("#p", "identity.place_of_birth")]
    assert [v["ok"] for v in _verify_in_page(page, both)] == [True, True]
    turkish = [entry("#y", "identity.place_of_birth"), entry("#d", "identity.date_of_birth")]
    assert [v["ok"] for v in _verify_in_page(page, turkish)] == [True, True]


@pytest.mark.extension
def test_an_offer_the_page_reformats_ends_as_check_this(browser_context, fixture_server):
    """Review minor 1: a read-back mismatch after the tap is a mismatch row, not a live offer."""
    page = browser_context.new_page()
    url = f"{fixture_server}/passport_form.html"
    page.goto(url)
    _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": _passport_packet(url)}})
    page.evaluate("""() => document.querySelector('#dob').addEventListener('input', (e) => {
        e.target.value = e.target.value.replaceAll('-', '/'); })""")
    assert page.evaluate(
        "() => window.__elmify_offer('identity.date_of_birth', '1998-03-14')") is False
    after = {f["key"]: f for f in _last_dock_with(page.evaluate("() => window.__sent"),
                                                   "fields")["fields"]}
    assert after["identity.date_of_birth"]["state"] == "mismatch"
    assert after["identity.date_of_birth"]["reason"] != "offer"


@pytest.mark.extension
@pytest.mark.parametrize(("lang", "generic"), [
    ("en", "From your verified facts"), ("az", "Təsdiqlənmiş məlumatlarınızdan"),
    ("tr", "Doğrulanmış bilgilerinizden"), ("ru", "Из ваших подтверждённых данных"),
])
def test_an_unknown_document_kind_shows_the_generic_word_never_a_code(
    browser_context, fixture_server, lang, generic
) -> None:
    page = browser_context.new_page()
    url = f"{fixture_server}/passport_form.html"
    page.goto(url)
    packet = _passport_packet(url)
    packet["entries"][0]["source_kind"] = "transcript"
    packet["hints"][0]["offer"]["source_kind"] = "transcript"
    page.evaluate("() => { window.__sent = []; window.chrome = { runtime: { sendMessage: "
                  "async (m) => { window.__sent.push(m); return m.type === 'packet' ? "
                  "{ ok: true, packet: window.__p } : { ok: true }; } } }; }")
    page.evaluate("(p) => { window.__p = p; }", packet)
    page.add_script_tag(path=str(DIST / "content.js"))
    page.evaluate(f"() => window.__elmify_run('app-1', 'form-1', '{lang}')")
    assert page.evaluate("() => window.__elmify_offer('identity.date_of_birth', '1998-03-14')")
    sent = page.evaluate("() => window.__sent")
    reasons = {f["key"]: f["reason"] for f in _last_dock_with(sent, "fields")["fields"]}
    assert not any("transcript" in r for r in reasons.values())
    page.focus("#dob")
    assert generic in page.evaluate("() => window.__elmify_marks_text()")


def _offer_worker(browser_context, confirm_reply):
    packet = _portal_packet()
    packet["hints"] = [{"selector": "#dob", "profile_field": "identity.date_of_birth",
                        "reason": "no_fact", "upload_kind": "", "expired_on": "",
                        "offer": {"fact_id": FACT_ID, "value": "1998-03-14", "method": "fill",
                                  "source_kind": "passport"}}]
    return _load_worker(
        browser_context,
        {"language": "en", "binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/facts/{FACT_ID}/confirm": confirm_reply},
        session={**_binding(), f"packet:{APP_A}": packet},
    )


_TAP = {"type": "offer:use", "tabId": 7, "key": "identity.date_of_birth"}


@pytest.mark.extension
def test_the_tap_confirms_on_the_server_and_sends_the_server_s_value_to_the_tab(
    browser_context,
) -> None:
    page = _offer_worker(browser_context, [201, {"profile_field": "identity.date_of_birth",
                                                 "value": "14.03.1998"}])
    _send(page, _TAP, PANEL_SENDER)
    fetched = [key for key, _body in page.evaluate("() => window.__fetched")]
    assert f"POST /ext/applications/{APP_A}/facts/{FACT_ID}/confirm" in fetched
    assert _calls(page, "tabs.sendMessage")[-1] == [
        7, {"type": "offer:fill", "key": "identity.date_of_birth", "value": "14.03.1998"}]


@pytest.mark.extension
@pytest.mark.parametrize(("status", "body", "code"), [
    (404, {"error": "not_found"}, "not_found"),
    (429, {"error": "rate_limited"}, "rate_limited"),
])
def test_a_refused_tap_types_nothing(browser_context, status, body, code) -> None:
    page = _offer_worker(browser_context, [status, body])
    reply = _send(page, _TAP, PANEL_SENDER)
    assert reply == {"ok": False, "code": code}
    assert _calls(page, "tabs.sendMessage") == []


@pytest.mark.extension
def test_a_tap_for_a_field_the_packet_does_not_offer_never_reaches_the_server(
    browser_context,
) -> None:
    page = _offer_worker(browser_context, [201, {"profile_field": "x", "value": "x"}])
    reply = _send(page, {**_TAP, "key": "identity.surname"}, PANEL_SENDER)
    assert reply == {"ok": False, "code": "not_found"}
    assert page.evaluate("() => window.__fetched.length") == 0


@pytest.mark.extension
def test_a_tap_while_the_bound_tab_has_gone_away_types_nothing(browser_context) -> None:
    page = _offer_worker(browser_context, [201, {"profile_field": "x", "value": "1"}])
    reply = _send(page, {**_TAP, "tabId": 99}, PANEL_SENDER)
    assert reply["ok"] is False
    assert _calls(page, "tabs.sendMessage") == []
    assert page.evaluate("() => window.__fetched.length") == 0


@pytest.mark.extension
def test_a_page_cannot_tap_or_forge_an_offer(browser_context) -> None:
    page = _offer_worker(browser_context, [201, {"profile_field": "x", "value": "x"}])
    reply = _send(page, _TAP, CONTENT)
    assert reply == {"ok": False, "code": "untrusted_sender"}
    assert _send(page, {"type": "open:documents"}, CONTENT) == {
        "ok": False, "code": "untrusted_sender"}
    forged = {"key": "identity.date_of_birth", "state": "your_turn", "reason": "offer",
              "placed": True, "offer": {"value": "evil", "source_kind": "passport"}}
    assert _send(page, {"type": "dock", "patch": {"fields": [forged]}}, CONTENT) == {"ok": True}
    [row] = page.evaluate("() => window.__session.dock.fields")
    assert row["offer"] == {"value": "1998-03-14", "source_kind": "passport"}  # the packet's own


@pytest.mark.extension
def test_the_panel_offers_the_value_and_sends_the_tap(browser_context) -> None:
    page = _open_panel(browser_context)
    _push_state(page, {
        "status": "blocked", "binding": {"tabId": 7, "origin": PORTAL},
        "fields": [{"key": "identity.date_of_birth", "state": "your_turn", "reason": "offer",
                    "placed": True, "offer": {"value": "1998-03-14", "source_kind": "passport"}}],
        "documents": [],
    })
    text = page.inner_text("#fields")
    assert "1998-03-14" in text and "Pasportunuzdan" in text  # the panel defaults to az here
    page.locator("#fields button").first.click()
    assert page.evaluate("() => window.__sent.at(-1)") == {
        "type": "offer:use", "tabId": 7, "key": "identity.date_of_birth"}


@pytest.mark.extension
def test_the_panel_links_to_the_documents_page_for_an_upload(browser_context) -> None:
    page = _open_panel(browser_context)
    _push_state(page, {
        "status": "blocked", "binding": {"tabId": 7, "origin": PORTAL},
        "fields": [{"key": "id_document.number", "state": "your_turn", "reason": "upload_once",
                    "placed": True, "upload_kind": "PASSPORT"}],
        "documents": [],
    })
    page.locator("#fields button").first.click()
    assert page.evaluate("() => window.__sent.at(-1)") == {"type": "open:documents"}


@pytest.mark.extension
def test_the_panel_names_diploma_and_certificate_fields_in_the_students_language(
    browser_context,
) -> None:
    page = _open_panel(browser_context)
    keys = ["education.diploma_number", "education.degree_english", "language.test_name",
            "language.cefr_level", "language.certificate_number", "language.test_date"]
    _push_state(page, {
        "status": "blocked", "binding": {"tabId": 7, "origin": PORTAL},
        "fields": [{"key": k, "state": "your_turn", "reason": "", "placed": True}
                   for k in keys],
        "documents": [],
    })
    text = page.inner_text("#fields").lower()
    assert "diploma number" not in text and "cefr level" not in text
    assert "test name" not in text and "certificate number" not in text


@pytest.mark.extension
def test_open_documents_opens_the_dashboard_s_documents_page(browser_context) -> None:
    page = _offer_worker(browser_context, [201, {}])
    _send(page, {"type": "open:documents"}, PANEL_SENDER)
    assert _calls(page, "tabs.create")[-1] == [{"url": f"{DASHBOARD}/student/documents/#upload"}]


_OFFER_STATE = {
    "status": "blocked", "binding": {"tabId": 7, "origin": PORTAL},
    "fields": [{"key": "identity.date_of_birth", "state": "your_turn", "reason": "offer",
                "placed": True, "offer": {"value": "1998-03-14", "source_kind": "passport"}}],
    "documents": [],
}


@pytest.mark.extension
@pytest.mark.parametrize(("reply", "az_words"), [
    ({"ok": False, "code": "not_found"}, "artıq cavablandırılıb"),
    ({"ok": False, "code": "busy"}, "hələ saxlanılır"),
    ({"ok": False, "code": "rate_limited"}, "Çox tez-tez"),
    ({"ok": False, "code": "request_failed"}, "saxlaya bilmədik"),
    ({"ok": False, "code": "not_shown"}, "göstərdiyi səhifəni"),
    ({"ok": False, "code": "not_started"}, "Doldurmağa başla"),
    ({"ok": False, "code": "not_typed"}, "özünüz yazın"),
    ({"ok": False}, "saxlaya bilmədik"),
    ({"ok": False, "code": "A server sentence."}, "saxlaya bilmədik"),
])
def test_a_refused_tap_says_so_in_the_panel(browser_context, reply, az_words) -> None:
    page = _open_panel(browser_context)
    page.evaluate("(r) => { window.__reply = r; }", reply)
    _push_state(page, _OFFER_STATE)
    page.locator("#fields button").first.click()
    page.wait_for_function(
        "(w) => document.getElementById('message').textContent.includes(w)", arg=az_words)
    assert "server sentence" not in page.inner_text("#message")
    assert "not found" not in page.inner_text("#message").lower()


@pytest.mark.extension
@pytest.mark.parametrize("break_it", ["gone_tab", "refused_box"])
def test_a_tap_confirmed_but_not_typed_answers_not_typed(browser_context, break_it) -> None:
    page = _offer_worker(browser_context, [201, {"profile_field": "identity.date_of_birth",
                                                 "value": "14.03.1998"}])
    page.evaluate(
        "(b) => { window.chrome.tabs.sendMessage = async () => "
        "{ if (b === 'gone_tab') throw new Error('gone'); return { ok: false }; }; }",
        break_it)
    assert _send(page, _TAP, PANEL_SENDER) == {"ok": False, "code": "not_typed"}


@pytest.mark.extension
def test_a_page_sent_reason_the_packet_does_not_back_is_cleared(browser_context) -> None:
    page = _offer_worker(browser_context, [201, {}])
    rows = [{"key": "identity.date_of_birth", "state": "your_turn", "reason": "upload_once",
             "placed": True},
            {"key": "identity.date_of_birth", "state": "your_turn", "reason": "offer",
             "placed": True}]
    assert _send(page, {"type": "dock", "patch": {"fields": rows[:1]}}, CONTENT) == {"ok": True}
    [row] = page.evaluate("() => window.__session.dock.fields")
    assert row["reason"] == ""
    # the packet's offer backs "offer" on that key, so it stays
    assert _send(page, {"type": "dock", "patch": {"fields": rows[1:]}}, CONTENT) == {"ok": True}
    [row] = page.evaluate("() => window.__session.dock.fields")
    assert row["reason"] == "offer"


@pytest.mark.extension
def test_open_documents_answers_when_the_tab_cannot_be_created(browser_context) -> None:
    page = _offer_worker(browser_context, [201, {}])
    page.evaluate("() => { window.chrome.tabs.create = async () => { throw new Error('x'); }; }")
    assert _send(page, {"type": "open:documents"}, PANEL_SENDER) == {"ok": False}


@pytest.mark.extension
def test_open_ended_narrative_fields_and_fuzzy_select_options_fill_and_read_back_cleanly(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.set_content(
        """<!doctype html><html><body><form>
        <label for="mot">Motivation letter</label>
        <textarea id="mot" name="motivation" maxlength="1500"></textarea>
        <label for="why">Why this programme</label>
        <textarea id="why" name="why_prog"></textarea>
        <label for="cnt">Country</label>
        <select id="cnt" name="country">
          <option value="">-- Select --</option>
          <option value="AZ">AZ - Azerbaijan (+994)</option>
          <option value="DE">DE - Germany (+49)</option>
        </select>
        </form></body></html>"""
    )
    page.add_script_tag(path=str(DIST / "content.js"))
    snapshot = page.evaluate("() => window.__elmify_snapshot()")
    by_id = {c["id"]: c["max_length"] for c in snapshot["controls"]}
    assert by_id == {"mot": 1500, "why": 0, "cnt": 0}

    entries = [
        {
            "selector": "#mot",
            "method": "fill",
            "value": "Dear Admissions Committee, I am applying for the MSc in Data Science.",
            "profile_field": "narrative.motivation_letter",
        },
        {
            "selector": "#why",
            "method": "fill",
            "value": "Your curriculum in statistical machine learning fits my research goals.",
            "profile_field": "narrative.why_programme",
        },
        {
            "selector": "#cnt",
            "method": "selectOption",
            "value": "Azerbaijan",
            "profile_field": "personal.country",
        },
    ]
    filled = page.evaluate("(entries) => window.__elmify_fill(entries)", entries)
    assert filled == [
        "narrative.motivation_letter",
        "narrative.why_programme",
        "personal.country",
    ]
    assert page.input_value("#mot").startswith("Dear Admissions Committee")
    assert page.input_value("#why").startswith("Your curriculum")
    assert page.input_value("#cnt") == "AZ"

    rb = page.evaluate("(entries) => window.__elmify_read_back(entries, {})", entries)
    assert all(v["ok"] for v in rb["verdicts"])
    assert rb["mismatches"] == []


@pytest.mark.extension
def test_wrapped_select_strips_option_text_and_infers_label_limits(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.set_content(
        """<!doctype html><html><body><form>
        <label>
          Country of residence
          <select id="cnt" name="country">
            <option value="">Select</option>
            <option value="DE">First choice: Deutschland</option>
            <option value="AZ">Aserbaidschan</option>
          </select>
        </label>
        <label for="plan">Career goals (max 120 words)</label>
        <textarea id="plan" name="career"></textarea>
        </form></body></html>"""
    )
    page.add_script_tag(path=str(DIST / "content.js"))
    snapshot = page.evaluate("() => window.__elmify_snapshot()")
    by_id = {c["id"]: c for c in snapshot["controls"]}
    assert by_id["cnt"]["label"] == "Country of residence"
    assert "First choice" not in by_id["cnt"]["label"]
    assert by_id["plan"]["max_length"] == 600

    entries = [
        {
            "selector": "#cnt",
            "method": "selectOption",
            "value": "Azerbaijan",
            "profile_field": "personal.country",
        }
    ]
    filled = page.evaluate("(entries) => window.__elmify_fill(entries)", entries)
    assert filled == ["personal.country"]
    assert page.input_value("#cnt") == "AZ"


@pytest.mark.extension
def test_multilingual_labels_with_non_decomposing_letters_verify_and_fill(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.set_content(
        """<!doctype html><html><body><form>
        <label for="mot">Motivasiya məktubu</label>
        <textarea id="mot" name="mot"></textarea>
        <label for="res">Araştırma planı</label>
        <textarea id="res" name="res"></textarea>
        <label for="str">Straße und Hausnummer</label>
        <input id="str" name="str" type="text">
        <label for="unp">Ödənişsiz / Könüllü (Unpaid)</label>
        <select id="unp" name="unp">
          <option value="">Seçin</option>
          <option value="1">Bəli</option>
          <option value="0">Xeyr</option>
        </select>
        </form></body></html>"""
    )
    page.add_script_tag(path=str(DIST / "content.js"))
    entries = [
        {
            "selector": "#mot",
            "method": "fill",
            "value": "Motivation text",
            "profile_field": "narrative.motivation_letter",
        },
        {
            "selector": "#res",
            "method": "fill",
            "value": "Research plan text",
            "profile_field": "narrative.research_plan",
        },
        {
            "selector": "#str",
            "method": "fill",
            "value": "Nizami 10",
            "profile_field": "contact.address",
        },
        {
            "selector": "#unp",
            "method": "selectOption",
            "value": "yes",
            "profile_field": "experience.unpaid",
        },
    ]
    filled = page.evaluate("(entries) => window.__elmify_fill(entries)", entries)
    assert filled == [
        "narrative.motivation_letter",
        "narrative.research_plan",
        "contact.address",
        "experience.unpaid",
    ]
    assert page.input_value("#unp") == "1"


@pytest.mark.extension
def test_cross_section_same_key_and_compound_phrase_labels_verify_without_false_ambiguity(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.set_content(
        """<!doctype html><html><body><form>
        <label for="em1">Applicant email</label><input id="em1" type="email">
        <label for="em2">Referee email</label><input id="em2" type="email">
        <label for="sd1">Education start date</label><input id="sd1" type="text">
        <label for="sd2">Employment start date</label><input id="sd2" type="text">
        <label for="cnt">Country</label><input id="cnt" type="text">
        <label for="iss">Issuing country</label><input id="iss" type="text">
        <label for="why_c">Why did you choose this country?</label><textarea id="why_c"></textarea>
        <label for="deg">Degree</label><input id="deg" type="text">
        <label for="deg_en">Degree in English</label><input id="deg_en" type="text">
        <label for="gn">First name</label><input id="gn" type="text">
        <label for="fn">Last name</label><input id="fn" type="text">
        <label for="mt">First language</label><input id="mt" type="text">
        <label for="ed">End date</label><input id="ed" type="text">
        <label for="gd">Graduation date</label><input id="gd" type="text">
        <label for="pub_t">Publication title</label><input id="pub_t" type="text">
        <label for="awd_t">Award title</label><input id="awd_t" type="text">
        <label for="amb">Ad Soyad</label><input id="amb" type="text">
        </form></body></html>"""
    )
    page.add_script_tag(path=str(DIST / "content.js"))

    def row(selector: str, field: str, value: str) -> dict[str, str]:
        return {"selector": selector, "method": "fill", "value": value, "profile_field": field}

    entries = [
        row("#em1", "contact.email", "a@example.org"),
        row("#em2", "reference.1.email", "r@example.org"),
        row("#sd1", "education.1.start_date", "2020-09"),
        row("#sd2", "experience.1.start_date", "2022-06"),
        row("#cnt", "personal.country", "Azerbaijan"),
        row("#iss", "id_document.issuing_country", "Azerbaijan"),
        row("#why_c", "narrative.why_country", "Strong research labs."),
        row("#deg", "education.1.degree", "Bakalavr"),
        row("#deg_en", "education.1.degree_english", "BSc"),
        row("#gn", "personal.given_name", "Leyla"),
        row("#fn", "personal.family_name", "Aliyeva"),
        row("#mt", "language.mother_tongue", "Azerbaijani"),
        row("#ed", "education.1.end_date", "2024-06"),
        row("#gd", "education.1.graduation_date", "2024-07"),
        row("#pub_t", "publication.1.title", "Graph Nets"),
        row("#awd_t", "award.1.title", "Dean's List"),
    ]
    verdicts = page.evaluate("(entries) => window.__elmify_verify(entries)", entries)
    assert all(v["ok"] for v in verdicts), verdicts

    # Swapping publication.title and award.title refuses as name_mismatch.
    swapped = [
        row("#awd_t", "publication.1.title", "Graph Nets"),
        row("#pub_t", "award.1.title", "Dean's List"),
    ]
    swap_verdicts = page.evaluate("(entries) => window.__elmify_verify(entries)", swapped)
    assert [v["reason"] for v in swap_verdicts] == ["name_mismatch", "name_mismatch"]

    # Genuine multi-field ambiguity ("Ad Soyad" with given_name + family_name) still refuses.
    amb_entries = [
        row("#amb", "personal.given_name", "Leyla"),
        row("#fn", "personal.family_name", "Aliyeva"),
    ]
    amb_verdicts = page.evaluate("(entries) => window.__elmify_verify(entries)", amb_entries)
    assert amb_verdicts[0]["ok"] is False
    assert amb_verdicts[0]["reason"] == "ambiguous_name"

