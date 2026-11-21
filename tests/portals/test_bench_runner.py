"""The offline bench replay (spec §9). Browser tests are marked `extension` and
need extension/dist-test (npm --prefix extension run check)."""

import os
import pathlib

import pytest

from apps.portals.bench_students import SAMPLE_STUDENTS, SampleStudent

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

#: The two-box name form (bench_leaky_page.html) asks for keys no fact carries,
#: so these tests bring their own samples (preflight ruling 12).
NAMES = (
    SampleStudent("two names", {"personal.given_name": "Işıl", "personal.family_name": "Öztürk"}),
    SampleStudent("single name, no family name", {"personal.given_name": "Aynur"}),
)


def _map(entries: list[dict[str, object]], slots: object = ()):
    return type("Map", (), {"entries": entries, "slots": list(slots)})()


def _form(**rules: object):
    defaults: dict[str, object] = {
        "value_formats": {}, "option_synonyms": {}, "readback_equivalences": {},
    }
    return type("Form", (), {**defaults, **rules})()


def _page(name: str) -> tuple[object, bytes]:
    record = type("Record", (), {"page_kind": "FORM", "step": 1})()
    return record, (FIXTURES / name).read_bytes()


def _entry(field: str, selector: str, method: str = "fill") -> dict[str, object]:
    return {"profile_field": field, "sure": True,
            "action": {"selector": selector, "method": method, "arguments": ["%value%"]}}


def _bundle() -> None:
    dist = pathlib.Path(__file__).resolve().parents[2] / "extension" / "dist-test"
    if not (dist / "content.js").exists():
        message = "extension/dist-test is missing -- npm --prefix extension run check"
        if os.environ.get("CI"):
            pytest.fail(message)  # as test_extension_e2e: CI builds it, so absent is a bug
        pytest.skip(message)


def test_the_samples_hold_every_key_a_map_can_ask_for_and_nothing_else() -> None:
    """A key no sample holds is untested on every map that asks for it, so such
    a map could never be clean."""
    from apps.portals.profile import LEARNABLE_FIELDS

    keys = {key for student in SAMPLE_STUDENTS for key in student.values}
    assert set(LEARNABLE_FIELDS) <= keys
    assert keys <= {*LEARNABLE_FIELDS, "contact.email"}


def test_the_samples_hold_a_document_of_every_slot_kind() -> None:
    from typing import get_args

    from apps.portals.learn import DocKind

    kinds = {kind for student in SAMPLE_STUDENTS for _name, kind, _variant in student.documents}
    assert set(get_args(DocKind)) <= kinds


def test_a_malformed_or_unsafe_row_is_a_refusal_not_a_skip() -> None:
    """As mint_packet reads a map (preflight ruling 14): either refuses a real
    packet, so the bench must never call that map clean."""
    from apps.portals.bench_runner import _rows

    rows, refused, unsure = _rows(_map([
        {"profile_field": "identity.full_name"},  # no action
        _entry("identity.phone", "#ph", method="click"),
        _entry("contact.email", "#em"),
    ]))
    assert [field for _raw, field, _action in rows] == ["contact.email"]
    assert refused == [
        {"profile_field": "identity.full_name", "reason": "malformed_field_map"},
        {"profile_field": "identity.phone", "reason": "unsafe_action"},
    ]
    assert unsure == []


def test_an_unsure_row_is_reported_and_blocks_a_clean_verdict() -> None:
    from apps.portals.bench_runner import BenchReport, StudentRun, _rows

    rows, _refused, unsure = _rows(_map([
        _entry("contact.email", "#em"),
        {**_entry("identity.phone", "#ph"), "sure": False},
    ]))
    assert [field for _raw, field, _action in rows] == ["contact.email"]
    assert unsure == [{"profile_field": "identity.phone", "selector": "#ph"}]
    assert BenchReport(boxes=1, per_student={"a": StudentRun()}).clean
    assert not BenchReport(boxes=1, per_student={"a": StudentRun()}, unsure=unsure).clean


def test_a_report_with_an_entry_nobody_tested_is_not_clean() -> None:
    from apps.portals.bench_runner import BenchReport, StudentRun

    report = BenchReport(boxes=2, per_student={
        "a": StudentRun(untested=["identity.phone"]),
        "b": StudentRun(untested=["identity.phone", "contact.email"]),
    })
    assert report.untested == ["identity.phone"]  # b's email was tested by a
    assert not report.clean
    report.per_student["a"].untested = []
    assert report.clean
    report.per_student["a"].open_choices = 2  # the student's own per-degree choice
    assert report.clean
    report.untested_slots = ["#diploma"]
    assert not report.clean


def test_an_empty_map_or_a_run_with_no_samples_is_never_clean() -> None:
    from apps.portals.bench_runner import BenchReport, StudentRun

    assert not BenchReport(boxes=0, per_student={"a": StudentRun()}).clean
    assert not BenchReport(boxes=3).clean


@pytest.mark.extension
def test_the_replay_never_reaches_the_live_portal() -> None:
    from apps.portals.bench_runner import replay

    _bundle()
    report = replay(_form(), _map([_entry("personal.given_name", "#gn")]),
                    pages=[_page("bench_leaky_page.html")], students=NAMES)
    assert report.blocked_requests >= 2


@pytest.mark.extension
def test_a_clean_page_reports_clean_and_a_missing_family_name_is_not_an_amber() -> None:
    from apps.portals.bench_runner import replay

    _bundle()
    report = replay(_form(), _map([
        _entry("personal.given_name", "#gn"), _entry("personal.family_name", "#fn"),
    ]), pages=[_page("bench_leaky_page.html")], students=NAMES)
    single = report.per_student["single name, no family name"]
    assert single.ambers == []  # a hint, not amber
    assert single.untested == ["personal.family_name"]  # the other sample typed it
    assert report.clean


@pytest.mark.extension
def test_a_control_on_a_later_page_is_not_a_refusal() -> None:
    """Multi-page: an entry counts as refused only if it verified on no page,
    and a control simply absent from a page is never a refusal."""
    from apps.portals.bench_runner import replay

    _bundle()
    report = replay(_form(), _map([_entry("personal.given_name", "#gn")]), pages=[
        _page("two_page_form_page2.html"), _page("bench_leaky_page.html"),
    ], students=NAMES)
    assert all(run.refused == [] for run in report.per_student.values())
    assert report.clean


@pytest.mark.extension
def test_a_selector_on_no_recorded_page_is_untested_and_not_clean() -> None:
    """A map whose selector matches nothing would otherwise replay as clean."""
    from apps.portals.bench_runner import replay

    _bundle()
    report = replay(_form(), _map([_entry("personal.given_name", "#nowhere")]),
                    pages=[_page("bench_leaky_page.html")], students=NAMES)
    assert report.untested == ["personal.given_name"]
    assert not report.clean


@pytest.mark.extension
def test_a_portal_that_uppercases_is_an_amber_until_the_rule_exists() -> None:
    """Saved copies carry no scripts (Task 3), so a portal's own uppercasing
    cannot replay. `transforms` stands in for what the owner's live walk saw."""
    from apps.portals.bench_runner import replay

    _bundle()
    entries = [_entry("personal.given_name", "#gn")]
    page = _page("bench_leaky_page.html")
    upper = {"#gn": "upper"}
    assert not replay(_form(), _map(entries), pages=[page], students=NAMES,
                      transforms=upper).clean
    taught = _form(readback_equivalences={"personal.given_name": "casefold"})
    assert replay(taught, _map(entries), pages=[page], students=NAMES,
                  transforms=upper).clean


#: A recorded page whose own script forges the read-back. The sanitisers are
#: deny-lists, and a mutation-XSS payload has come back alive through both, so
#: the replay itself must refuse to run anything a page carries.
_FORGED = (
    "(()=>{const v={mismatches:[],verdicts:[{profile_field:'personal.given_name',ok:true}]};"
    "Object.defineProperty(window,'__elmify_read_back',"
    "{configurable:true,get(){return ()=>v},set(){}})})()"
)
HOSTILE = (
    '<!doctype html><html><body><form><label for="gn">First name</label><input id="gn">'
    f'</form><img src="missing.gif" onerror="{_FORGED}"><script>{_FORGED}</script>'
    "</body></html>"
).encode()


@pytest.mark.extension
def test_a_recorded_pages_own_script_never_runs_in_the_replay() -> None:
    """An uppercasing portal with no rule is an amber; a page that forges the
    read-back must not turn that into a clean verdict."""
    from apps.portals.bench_runner import replay

    _bundle()
    record = type("Record", (), {"page_kind": "FORM", "step": 1})()
    report = replay(_form(), _map([_entry("personal.given_name", "#gn")]),
                    pages=[(record, HOSTILE)], students=NAMES, transforms={"#gn": "upper"})
    assert not report.clean
    assert all(run.ambers for run in report.per_student.values())


def test_chromium_gets_none_of_the_parents_secrets(monkeypatch) -> None:
    """A child process inherits the parent's environment, and this parent is
    manage.py: the database password and the secret key."""
    from apps.portals import bench_runner

    monkeypatch.setenv("POSTGRES_RUNTIME_PASSWORD", "hunter2")
    launched: dict[str, object] = {}
    chromium = type("C", (), {"launch": lambda self, **kw: launched.update(kw)})()
    bench_runner._launch(type("P", (), {"chromium": chromium})())
    env = launched["env"]
    assert isinstance(env, dict) and "POSTGRES_RUNTIME_PASSWORD" not in env
    assert set(env) <= {"PATH", "HOME", "LANG"}


@pytest.mark.extension
def test_a_document_its_box_cannot_take_is_attached_by_hand_and_blocks() -> None:
    from apps.portals.bench_runner import replay

    _bundle()
    turkish = (SAMPLE_STUDENTS[2],)  # holds cv.pdf only
    page = _page("two_upload_slots.html")

    def slot(selector: str) -> dict[str, object]:
        return {"selector": selector, "kind": "CV", "variant": "ANY", "degree": None, "sure": True}

    assert replay(_form(), _map([], [slot("#cv")]), pages=[page], students=turkish).clean
    report = replay(_form(), _map([], [slot("#gone")]), pages=[page], students=turkish)
    assert report.per_student[turkish[0].name].manual_documents == ["cv.pdf"]
    assert not report.clean


@pytest.mark.extension
def test_a_diploma_box_no_document_reached_is_untested_and_not_clean() -> None:
    from apps.portals.bench_runner import replay

    _bundle()
    diploma = {"selector": "#diploma", "kind": "DIPLOMA", "variant": "ANY", "degree": None,
               "sure": True}
    report = replay(_form(), _map([], [diploma]), pages=[_page("two_upload_slots.html")])
    assert report.untested_slots == ["#diploma"]
    assert not report.clean


@pytest.mark.extension
def test_a_per_degree_box_is_proved_by_the_students_pick() -> None:
    """Degree 2's box is reached only through a choice; the bench stands in for
    the student's pick, so the box is proved and the choice stays the student's."""
    from apps.portals.bench_runner import replay

    _bundle()

    def slot(selector: str, variant: str, degree: int) -> dict[str, object]:
        return {"selector": selector, "kind": "TRANSCRIPT", "variant": variant,
                "degree": degree, "sure": True}

    report = replay(_form(), _map([], [
        slot("#t1o", "ORIGINAL", 1), slot("#t1e", "TRANSLATION", 1), slot("#t2o", "ORIGINAL", 2),
    ]), pages=[_page("repeated_degrees.html")])
    assert report.untested_slots == []
    assert report.per_student["two degrees"].open_choices == 2
    assert report.clean


@pytest.mark.extension
def test_an_other_upload_box_is_left_to_the_student_and_never_blocks() -> None:
    """Spec D8: an OTHER box is the student's, like a declaration."""
    from apps.portals.bench_runner import replay

    _bundle()
    other = {"selector": "#other", "kind": "OTHER", "variant": "ANY", "degree": None,
             "sure": True}
    students = (*NAMES, SampleStudent("holds an OTHER file", {}, (("x.pdf", "OTHER", "ORIGINAL"),)))
    report = replay(_form(), _map([_entry("personal.given_name", "#gn")], [other]),
                    pages=[_page("bench_leaky_page.html")], students=students)
    assert report.left_to_student == ["#other"]
    assert report.untested_slots == []
    assert all(run.manual_documents == [] for run in report.per_student.values())
    assert report.clean


@pytest.mark.extension
def test_a_refused_row_is_reported_once_for_the_run() -> None:
    from apps.portals.bench_runner import replay

    _bundle()
    rows = [_entry("personal.given_name", "#gn"), _entry("personal.family_name", "#fn", "click")]
    report = replay(_form(), _map(rows), pages=[_page("bench_leaky_page.html")], students=NAMES)
    assert report.refused_rows == [{"profile_field": "personal.family_name",
                                    "reason": "unsafe_action"}]
    assert all(run.refused == [] for run in report.per_student.values())
    assert not report.clean


@pytest.mark.extension
def test_the_bench_browser_resolves_no_host_but_127_0_0_1() -> None:
    """Without route(): `localhost` names the very server the page came from, so
    only the resolver rules can make that fetch fail. A plain launch reaching
    it shows the probe would see a leak."""
    import threading
    from functools import partial
    from http.server import ThreadingHTTPServer

    from playwright.sync_api import sync_playwright

    from apps.portals.bench_runner import _launch, _QuietHandler

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=FIXTURES))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_port
    probe = "(u) => fetch(u, {mode: 'no-cors'}).then(() => 'reached', () => 'nothing')"
    try:
        with sync_playwright() as playwright:
            plain = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            for browser, expected in ((plain, "reached"), (_launch(playwright), "nothing")):
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{port}/plain_form.html")
                assert page.evaluate(probe, f"http://localhost:{port}/plain_form.html") == expected
                assert page.evaluate(probe, f"http://127.0.0.1:{port}/plain_form.html") == "reached"
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("expected, actual, kind", [
    ("Işıl", "IŞIL", "casefold"),
    ("2001-03-07", "07.03.2001", "value_formats"),
    ("+994 50 123", "99450123", "digits"),
    ("Azerbaijan", "", "option_synonyms"),
])
def test_every_amber_gets_a_suggested_rule(expected: str, actual: str, kind: str) -> None:
    from apps.portals.bench_runner import suggest_rule

    assert kind in suggest_rule(expected, actual)


@pytest.mark.django_db
def test_the_command_refuses_a_form_with_no_recorded_walk(operator, portal_form) -> None:
    """A superseded walk is history: it is never replayed."""
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from django.utils import timezone

    from apps.portals.models import PageRecord

    PageRecord.objects.create(
        portal_form=portal_form, source=PageRecord.Source.BENCH_WALK, page_kind="FORM",
        snapshot={}, html_key="bench/old.html", superseded_at=timezone.now(),
    )
    with pytest.raises(CommandError, match="no recorded walk"):
        call_command("portal_bench", str(portal_form.id), "--operator", "owner@example.org")


@pytest.mark.django_db
def test_the_command_refuses_anyone_but_a_bench_operator(platform, portal_form) -> None:
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="no bench operator"):
        call_command("portal_bench", str(portal_form.id), "--operator", "owner@example.org")


@pytest.mark.django_db
def test_the_command_replays_only_the_current_walk_and_exits_1_when_not_clean(
    operator, portal_form, bench_store, monkeypatch
) -> None:
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from django.utils import timezone

    from apps.portals.bench_runner import BenchReport, StudentRun
    from apps.portals.management.commands import portal_bench
    from apps.portals.models import FieldMap, PageRecord

    FieldMap.objects.create(portal_form=portal_form, version=1, entries=[])
    for key, superseded in (("bench/old.html", timezone.now()), ("bench/new.html", None)):
        bench_store.put(key, key.encode())
        PageRecord.objects.create(
            portal_form=portal_form, source=PageRecord.Source.BENCH_WALK, page_kind="FORM",
            snapshot={}, html_key=key, superseded_at=superseded,
        )
    seen: list[bytes] = []

    def fake_replay(form, field_map, *, pages):
        seen.extend(body for _record, body in pages)
        return BenchReport(per_student={"s": StudentRun(manual_documents=["cv.pdf"])})

    monkeypatch.setattr(portal_bench, "replay", fake_replay)
    with pytest.raises(CommandError, match="not clean"):
        call_command("portal_bench", str(portal_form.id), "--operator", "owner@example.org")
    assert seen == [b"bench/new.html"]


@pytest.mark.django_db
def test_the_queue_lists_unverified_live_forms_and_changed_ones(operator, agency_a) -> None:
    from io import StringIO

    from django.core.management import call_command

    from apps.portals.models import FieldMap, PageRecord, PortalForm

    met = PortalForm.objects.create(portal_host="met.example.edu", form_key="q-1")
    PageRecord.objects.create(
        portal_form=met, source="LIVE_LEARN", page_kind="FORM", step=1,
        snapshot={"page_url": "https://met.example.edu", "controls": []},
        learned_by_tenant=agency_a,
    )
    FieldMap.objects.create(portal_form=met, version=3, entries=[])
    changed = PortalForm.objects.create(
        portal_host="changed.example.edu", form_key="q-2", needs_bench=True
    )
    FieldMap.objects.create(
        portal_form=changed, version=7, entries=[], learned_by_tenant=agency_a
    )
    PortalForm.objects.create(portal_host="nobody.example.edu", form_key="q-3")
    out = StringIO()
    call_command("portal_bench", "--operator", "owner@example.org", "--queue", stdout=out)
    lines = out.getvalue().splitlines()
    assert any(str(met.id) in line and "unverified" in line and "bench=v3" in line
               for line in lines)
    assert any(str(changed.id) in line and "changed" in line and "bench=v7" in line
               for line in lines)
    assert not any("nobody.example.edu" in line for line in lines)


@pytest.mark.django_db
def test_new_walk_supersedes_the_current_walk_and_walk_ok_marks_the_newest(
    operator, portal_form
) -> None:
    from django.core.management import call_command

    from apps.portals.models import PageRecord

    def record(**kwargs):
        return PageRecord.objects.create(
            portal_form=portal_form, source=PageRecord.Source.BENCH_WALK, snapshot={}, **kwargs
        )

    old = record(page_kind="LOGIN")
    new = record(page_kind="LOGIN")
    call_command("portal_bench", str(portal_form.id), "--operator", "owner@example.org",
                 "--walk-ok", "LOGIN")
    old.refresh_from_db()
    new.refresh_from_db()
    assert (new.walk_ok, old.walk_ok) == (True, False)
    call_command("portal_bench", str(portal_form.id), "--operator", "owner@example.org",
                 "--new-walk")
    new.refresh_from_db()
    assert new.superseded_at is not None
    assert not PageRecord.objects.filter(
        portal_form=portal_form, superseded_at__isnull=True
    ).exists()


@pytest.mark.django_db
def test_walk_ok_signup_marks_the_newest_current_page_that_has_rules(
    operator, portal_form
) -> None:
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from django.utils import timezone

    from apps.portals.models import PageRecord

    def signup(**kwargs):
        return PageRecord.objects.create(
            portal_form=portal_form, source=PageRecord.Source.BENCH_WALK, snapshot={},
            page_kind="SIGNUP", **kwargs,
        )

    def walk_ok():
        call_command("portal_bench", str(portal_form.id), "--operator", "owner@example.org",
                     "--walk-ok", "SIGNUP")

    signup(password_rules="")
    with pytest.raises(CommandError, match="password rules"):
        walk_ok()
    with_rules = signup(password_rules="12 characters")
    signup(password_rules="old", superseded_at=timezone.now())
    signup(password_rules="")  # newest, but has no rules
    walk_ok()
    assert list(PageRecord.objects.filter(walk_ok=True)) == [with_rules]
