"""Replay saved copies of a portal's pages offline, from synthetic students
(spec §9). Never a live portal: pages are served from a temporary directory on
127.0.0.1, every other host fails name resolution in Chromium itself, and every
other request is aborted and counted. Never a click: the replay types through
the content script's own fill and reads back, nothing else. Loads the TEST
bundle (extension/dist-test): __elmify_read_back exists only there, so the
production bundle never ships it.

Nothing on a saved copy runs. Stripping scripts is not what guarantees that:
both sanitisers are deny-lists over a parse that differs from Chromium's, and a
mutation-XSS payload (MathML <mglyph><style>) has been shown to come back alive
on Chromium's re-parse. Every page is served with REPLAY_CSP, so no page
script, inline handler, frame or plugin runs, and the content script goes in as
an init script, which a page CSP does not block. Chromium also gets a bare
environment: a child process inherits the parent's otherwise, and this one is
manage.py's, holding the database password and the secret key.

What a replay cannot see: saved copies run no scripts, so a portal's own
transforms (uppercasing, reformatting a date) never happen here. Those are
taught by hand from the owner's live walk; `transforms` is a test seam that
stands in for them, never a production input."""


from __future__ import annotations

import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from .bench_students import SAMPLE_STUDENTS, SampleStudent
from .learn import DocumentSlot
from .packets import PacketRefused, _parse_entry
from .rules import RulesForm, apply_rules
from .session import FieldAction, is_fillable
from .slots import HeldDocument, pair_slots, parse_slots

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Playwright, Route

DIST = Path(__file__).resolve().parents[2] / "extension" / "dist-test"

#: Chromium resolves no host but the bench's own, so preconnect, dns-prefetch
#: and WebSockets -- which context.route() never sees -- go nowhere either.
#: --no-sandbox mirrors test_extension_e2e's launch (Playwright adds it anyway
#: unless chromiumSandbox is set); it is not a choice made for this path. With
#: no page script running and no secret in Chromium's environment, a renderer
#: escape reaches neither the verdict nor the database.
_LAUNCH_ARGS = ["--no-sandbox", "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"]

_UPPER = (
    "(s) => { const el = document.querySelector(s);"
    " if (el) el.value = el.value.toUpperCase(); }"
)

#: (raw row, profile_field, action) for every row mint_packet would accept.
Row = tuple[dict[str, object], str, FieldAction]


class BenchMap(Protocol):
    entries: list[dict[str, object]]
    slots: object


#: Served on every saved copy: nothing on a portal's page runs in the replay.
REPLAY_CSP = (
    "script-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; "
    "base-uri 'none'; form-action 'none'"
)


class _QuietHandler(SimpleHTTPRequestHandler):
    """The bench's file server, without a stderr line per request."""

    def end_headers(self) -> None:
        self.send_header("Content-Security-Policy", REPLAY_CSP)
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


@dataclass
class StudentRun:
    ambers: list[dict[str, str]] = field(default_factory=list)
    refused: list[dict[str, object]] = field(default_factory=list)
    manual_documents: list[str] = field(default_factory=list)
    #: The per-degree choices pairing leaves to the student (plan 5): printed,
    #: never blocking -- it is the designed question, not a defect.
    open_choices: int = 0
    #: Entries this sample did not prove: no value to type, or a box on no
    #: recorded page. Blocking only when NO sample proved the entry.
    untested: list[str] = field(default_factory=list)


@dataclass
class BenchReport:
    per_student: dict[str, StudentRun] = field(default_factory=dict)
    blocked_requests: int = 0
    #: Map rows mint_packet would refuse (malformed_field_map, unsafe_action):
    #: a defect of the map, so reported once for the run, not per sample.
    refused_rows: list[dict[str, object]] = field(default_factory=list)
    #: Map rows marked `sure: False`: guesses, never verified, so never promotable.
    unsure: list[dict[str, str]] = field(default_factory=list)
    #: Upload boxes no sample's document went into on any recorded page.
    untested_slots: list[str] = field(default_factory=list)
    #: The boxes the map asks the bench to prove (sure entries + sure slots).
    boxes: int = 0
    #: OTHER upload boxes: the student's by design, like a declaration (spec
    #: D8). Printed, never paired, never blocking.
    left_to_student: list[str] = field(default_factory=list)

    @property
    def untested(self) -> list[str]:
        """Entries no sample typed and verified on any recorded page."""
        runs = list(self.per_student.values())
        if not runs:
            return []
        common = set(runs[0].untested).intersection(*(r.untested for r in runs[1:]))
        return sorted(common)

    @property
    def clean(self) -> bool:
        """Something was proved, by someone, and nothing failed. An empty map or
        a run with no samples proved nothing, so it is never clean."""
        return (
            bool(self.per_student)
            and self.boxes > 0
            and not self.refused_rows
            and not self.unsure
            and not self.untested_slots
            and not self.untested
            and all(
                not r.ambers and not r.refused and not r.manual_documents
                for r in self.per_student.values()
            )
        )


def _rows(
    field_map: BenchMap,
) -> tuple[list[Row], list[dict[str, object]], list[dict[str, str]]]:
    """The map's rows read exactly as mint_packet reads them. A row mint_packet
    refuses (`malformed_field_map`, `unsafe_action`) is a refusal here too, so
    such a map is never clean."""
    rows: list[Row] = []
    refused: list[dict[str, object]] = []
    unsure: list[dict[str, str]] = []
    for raw in field_map.entries:
        try:
            profile_field, action = _parse_entry(raw)
        except PacketRefused as exc:
            refused.append({"profile_field": str(raw.get("profile_field") or ""),
                            "reason": exc.reason})
            continue
        if not is_fillable(action):
            refused.append({"profile_field": profile_field, "reason": "unsafe_action"})
            continue
        if raw.get("sure", True) is False:
            # A hint in a real packet, never typed -- but promotion would copy
            # a tenant's guess into the verified map, so it blocks.
            unsure.append({"profile_field": profile_field, "selector": action.selector})
            continue
        rows.append((raw, profile_field, action))
    return rows, refused, unsure


def _entries(
    portal_form: RulesForm, rows: list[Row], student: SampleStudent
) -> list[dict[str, str]]:
    """The entries a packet for this student would type."""
    typed: list[dict[str, str]] = []
    for _raw, profile_field, action in rows:
        value = student.values.get(profile_field, "")
        if not value.strip():
            continue  # no fact: a hint in a real packet, never typed, never amber
        typed.append({
            "selector": action.selector,
            "method": (action.method or "").strip(),
            "value": apply_rules(portal_form, profile_field, value),
            "profile_field": profile_field,
        })
    return typed


def _documents(
    slots: list[DocumentSlot], student: SampleStudent
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    """The student's documents through plan 5's own pairing: what a packet
    attaches, and a stand-in pick for each choice (the first free box, marked
    `chosen` as the panel marks the student's pick) so per-degree boxes are
    proved too. Only the assigned ones can be manual: a pick is the student's."""
    held = [
        HeldDocument(source="upload", id=uuid4(), filename=name, kind=kind,
                     variant=variant, download_path="")
        for name, kind, variant in student.documents
    ]
    degrees = {
        key.split(".")[1] for key in student.values if re.fullmatch(r"education\.\d+\.\w+", key)
    }
    pairing = pair_slots(slots, held, len(degrees))
    attach: list[dict[str, object]] = [
        {"filename": doc.filename, "selector": slot.selector, "kind": doc.kind}
        for slot, doc in pairing.assigned
    ]
    taken = {slot.selector for slot, _doc in pairing.assigned}
    picks: list[dict[str, object]] = []
    for doc, options in pairing.choices:
        free = next((slot for slot in options if slot.selector not in taken), None)
        if free is not None:
            taken.add(free.selector)
            picks.append({"filename": doc.filename, "selector": free.selector,
                          "kind": doc.kind, "chosen": True})
    return attach, picks, len(pairing.choices)


def _launch(playwright: Playwright) -> Browser:
    bare: dict[str, str | float | bool] = {
        key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ
    }
    return playwright.chromium.launch(headless=True, args=_LAUNCH_ARGS, env=bare)


def replay(
    portal_form: RulesForm,
    field_map: BenchMap,
    *,
    pages: list[tuple[object, bytes]],
    students: tuple[SampleStudent, ...] = SAMPLE_STUDENTS,
    transforms: dict[str, str] | None = None,
) -> BenchReport:
    """`transforms` is a test seam ({selector: "upper"}, applied after typing):
    the owner's live walk is what teaches a portal's own transforms."""
    from playwright.sync_api import sync_playwright

    rows, refused_rows, unsure_rows = _rows(field_map)
    sure = [profile_field for _raw, profile_field, _action in rows]
    sure_slots = [slot for slot in parse_slots(field_map.slots) if slot.sure]
    slots = [slot for slot in sure_slots if slot.kind != "OTHER"]
    report = BenchReport(
        refused_rows=refused_rows,
        unsure=unsure_rows,
        boxes=len(sure) + len(slots),
        left_to_student=[slot.selector for slot in sure_slots if slot.kind == "OTHER"],
    )
    slots_proved: set[str] = set()
    with tempfile.TemporaryDirectory() as root:
        for index, (_record, body) in enumerate(pages):
            Path(root, f"page-{index}.html").write_bytes(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=root))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}/"
        try:
            with sync_playwright() as playwright:
                browser = _launch(playwright)
                context = browser.new_context()
                context.add_init_script(path=str(DIST / "content.js"))

                def gate(route: Route) -> None:
                    if route.request.url.startswith(base):
                        route.continue_()
                    else:
                        report.blocked_requests += 1
                        route.abort()

                context.route("**/*", gate)
                for student in students:
                    run = report.per_student.setdefault(student.name, StudentRun())
                    entries = _entries(portal_form, rows, student)
                    attach, picks, run.open_choices = _documents(slots, student)
                    box_of = {str(d["filename"]): str(d["selector"]) for d in attach + picks}
                    verified_somewhere: set[str] = set()
                    refusals: dict[str, dict[str, object]] = {}
                    attached: set[str] = set()
                    for index in range(len(pages)):
                        page = context.new_page()
                        page.goto(f"{base}page-{index}.html")
                        _assert_on_bench(page.url, base)
                        page.evaluate("(e) => window.__elmify_fill(e)", entries)
                        for selector, kind in (transforms or {}).items():
                            if kind == "upper":
                                page.evaluate(_UPPER, selector)
                        result = page.evaluate(
                            "([e, q]) => window.__elmify_read_back(e, q)",
                            [entries, dict(portal_form.readback_equivalences or {})],
                        )
                        run.ambers.extend(result["mismatches"])
                        for verdict in result["verdicts"]:
                            if verdict["ok"]:
                                verified_somewhere.add(verdict["profile_field"])
                            elif verdict["reason"] != "no_such_control":
                                refusals[verdict["profile_field"]] = verdict
                        if attach or picks:
                            placed = page.evaluate(
                                "(docs) => window.__elmify_attach("
                                "docs.map((d) => ({...d, bytes: new ArrayBuffer(8)})))",
                                attach + picks,
                            )
                            names = {a["filename"] for a in placed["attached"]}
                            attached |= names
                            slots_proved.update(box_of[name] for name in names)
                        _assert_on_bench(page.url, base)
                        page.close()
                    # Multi-page: refused only if it verified on no page at all;
                    # absent from every page (no_such_control) is untested.
                    run.refused = [v for f, v in refusals.items() if f not in verified_somewhere]
                    run.untested = [
                        f for f in sure if f not in verified_somewhere and f not in refusals
                    ]
                    run.manual_documents = [
                        str(d["filename"]) for d in attach if d["filename"] not in attached
                    ]
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    report.untested_slots = [s.selector for s in slots if s.selector not in slots_proved]
    return report


def _assert_on_bench(url: str, base: str) -> None:
    if not url.startswith(base):
        raise RuntimeError(f"the replay left the bench: {url}")


def suggest_rule(expected: str, actual: str) -> str:
    """The rule kind most likely to turn this amber green. A suggestion only:
    the command never writes a rule, the owner does."""
    if actual == "":
        return (
            "option_synonyms (no option matched; name the option's value where it "
            "differs from its text), or a map correction"
        )
    if expected.upper() == actual.upper():
        return "readback_equivalences: casefold"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", expected) and sorted(
        re.findall(r"\d+", expected)
    ) == sorted(re.findall(r"\d+", actual)):
        return f"value_formats: the portal writes this date as {actual!r}"
    if digits := re.sub(r"\D", "", expected):
        if digits == re.sub(r"\D", "", actual):
            return "readback_equivalences: digits"
    if " ".join(expected.split()) == " ".join(actual.split()):
        return "readback_equivalences: collapse_spaces"
    return "a map correction (the box asks for something else)"
