# Lanes Plan 2 — Lanes Board, Card and Programme Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the flat five-column board into one lane per programme. Give each lane a programme page. Show deadlines in both time zones, the award lines, the extension-only "Apply to <programme>" button and country notices. Remove the funding page's "not stated", "(unstructured)" and "Not confirmed" lines.

**Architecture:**
- Lanes are a pure grouping over the cards `board_for` already builds (`apps/dashboard/lanes.py`), plus one `ApplicationLink` query.
- Deadlines come from the card's `route_snapshot` copy through a pure module (`apps/dashboard/dates.py`). It falls back to `Application.deadline`.
- The programme page is the lane's own view. It reuses `board_for`, so it reads the same tenant copies and never a catalogue table.
- Everything this plan renders exists today. What depends on data plan 1b or the tailored build has not written yet is listed under "Deferred to plan 2b" and is not built here.

**Tech Stack:** Django 5.2 views and plain templates, frozen dataclasses, pydantic `RouteSnapshot` (already in `apps/portals/route_snapshot.py`), `zoneinfo`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-programme-lanes-and-money-design.md`. Plan 2 covers §5, §5.1, §9.2–§9.4 and §13a. §2's line texts are also corrected here.

## Scope ruling: plan 2 now, plan 2b later

Spec §14 lists plan 2 as needing "plan 1", meaning both 1a and 1b. Only 1a is merged. 1b waits on the verified catalogue's §3.4 tables. Everything below runs on 1a's data, the agency fallback snapshot and today's candidate copies.

**Deferred to plan 2b**, each blocked on the data named:

| Spec | Deferred item | Blocked on |
|---|---|---|
| §6 | Cascades | `WAITS_FOR` links, which need `route_order` (1b). |
| §6 | `funding_outcome` on the application, offer acceptance and "Compare your offers" | The acceptance deadline and deposit (not read from offer mail yet). |
| §8 | National rounds | `portal_system`, `choice_limit`, `one_fee_per_round` (1b). |
| §9.1 | Start-by lead times | `prep_lead_days` (1b), referee leads (plan 4), language-test need (tailored build). Until then Needs sorts by the counting deadline, which is start-by with no lead. |
| §5.1 | "Why it fits you", the risk label, requirement statuses (Met / Still to do / Nearly met) | The tailored-programme build. Spec §16 says the page ships without them. |
| §5.1 | EMJM tracks and mobility paths | Verified-catalog §3.2, which has no copied field yet. |
| §5.1 | Scholarship renewal and obligations | The award copy (1b). Today's `funding_card` has none. |
| §2 / §5.1 | A nomination contact with a drafted-email Needs task | The award copy (1b). |
| §4 | "Apply" opening the first step not `DONE` | `step_progress` (1b). The extension opens the packet's `form_url`, which is step 1. |
| §7 | Money lines, holds, ≈ AZN | Plan 3. |

## Global Constraints

- **Gates:**
  - tests: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider` (this worktree's own DB name; never run two suites on one DB);
  - lint: `uv run ruff check .`, never `ruff format`;
  - types: `uv run mypy apps config`;
  - Django: `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run`;
  - security: `uv run bandit -c pyproject.toml -r apps config`.
- **Git:** run every git command as `git -C /home/orkhan/Desktop/lanes-plan-2 …`, because the shell's cwd resets to the main repo. Never push to master.
- **Reads:** the web tier reads tenant tables only. Every board and programme-page test runs inside `reads_no_catalogue()` (`tests/conftest.py:572`). Never read `candidate.program` or `candidate.opportunity`; `*_id` access is fine.
- **Rule 11:** no application steps, portal instructions or "which box to tick" anywhere the student sees, on the card or the programme page.
- **Never "not stated":** an unsure fact is never shown as a guess or as "not stated" (verified-catalog §5.5). The one exception is spec §2's `UNSTATED` line, which says how to apply is not stated and links the official page.
- **Student words:** Scholarship, Tuition waiver, Discount, Assistantship. Never "award", "HOLDER", "scope" or route codes in student-facing text.
- **Country notice wording is the owner's** (spec §13a, Russia). Do not edit it; only fill in `{check date}`.
- **The counsellor never gets the Apply button** (spec §5.1). `action_url(counselor_view=True, "start", …)` already returns "".
- **No new dependency.** Country names come from `apps/documents/templatetags/cv_countries.py::country_name`.

## Review Focus

1. **A student with no time zone set** (`Membership.timezone == ""`): the deadline shows the portal's zone only, with no "( … Baku time)" part. This is pinned in Task 1.
2. **Bad snapshot data** (an unparseable date, an unknown IANA zone, a date with no zone): the card never 500s. An unknown zone renders the date with "(time not stated)", and a bad date falls back to `Application.deadline`. Pinned in Task 1.
3. **An award card linked to two programmes, one of which is withdrawn:**
   - the award still has its own lane;
   - the withdrawn programme's lane moves to Done;
   - nothing is listed twice.

   Pinned in Task 2.
4. **The programme page for another student's application, or an invented id:** both get the same 404 as an invented id, whether the viewer is a student or a counsellor. Pinned in Task 6.
5. **No User-Agent at all** (the test client, curl): treated as "not Chrome or Edge". The Apply button is replaced by the sentence; the POST route itself is unchanged. Pinned in Task 4.

---

### Task 1: Which deadline counts, in both time zones

**Files:**
- Create: `apps/dashboard/dates.py`
- Modify: `apps/dashboard/board.py` (`Card` fields, `build_card`, `board_for`)
- Modify: `templates/student/_card.html` (the deadline line)
- Modify: `tests/dashboard/test_needs.py` (`_card` helper: `deadline_local` → `deadline_text`)
- Test: `tests/dashboard/test_dates.py`, `tests/dashboard/test_board.py`

**Interfaces:**
- Produces:
  - `Deadline(at: datetime | None, zone: str, wording: str = "")`;
  - `counting_deadline(application: Application, *, mandatory: bool) -> Deadline | None`;
  - `both_zones(at: datetime, zone: str, student_zone: str) -> str`;
  - `pre_checks(application: Application, student_zone: str) -> tuple[str, ...]`;
  - `final_passed(application: Application, now: datetime) -> bool`.
- `Card` loses `deadline_local` and gains:
  - `deadline_text: str = ""`;
  - `deadline_wording: str = ""`;
  - `closed: bool = False`;
  - `pre_checks: tuple[str, ...] = ()`.

  `Card.deadline` stays the aware datetime used for sorting.
- `build_card` gains the keyword arguments `mandatory: bool = False` and `student_zone: str = ""`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dashboard/test_dates.py
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.dashboard.dates import (
    DECENTRALISED, ROLLING, both_zones, counting_deadline, final_passed, pre_checks,
)
from apps.portals.models import Application


def _app(dates=(), *, pre=None, **fields) -> Application:
    steps = []
    if pre is not None:
        steps.append({"position": 1, "purpose": "PRE_CHECK", "channel": "PORTAL",
                      "portal_system": "uni-assist", "dates": [pre]})
    steps.append({"position": len(steps) + 1, "purpose": "APPLY", "channel": "PORTAL",
                  "dates": list(dates)})
    snapshot = {"source": "CATALOGUE", "steps": steps}
    return Application(program_id=uuid4(), route_snapshot=snapshot, **fields)


def _d(role, date, tz="Europe/Stockholm"):
    return {"role": role, "date": date, "timezone": tz}


@pytest.mark.parametrize(
    ("mandatory", "expected"),
    [(True, "2027-01-05"), (False, "2027-01-10")],
)
def test_the_mandatory_student_works_to_the_funding_date(mandatory, expected) -> None:
    app = _app([_d("FINAL", "2027-01-15"), _d("PRIORITY", "2027-01-10"),
                _d("FUNDING_CONSIDERATION", "2027-01-05")])
    deadline = counting_deadline(app, mandatory=mandatory)
    assert deadline is not None and deadline.at is not None
    assert deadline.at.date().isoformat() == expected
    assert (deadline.at.hour, deadline.at.minute) == (23, 59)
    assert deadline.zone == "Europe/Stockholm"


def test_final_when_nothing_earlier_is_stated() -> None:
    deadline = counting_deadline(_app([_d("FINAL", "2027-01-15")]), mandatory=True)
    assert deadline is not None and deadline.at.date().isoformat() == "2027-01-15"


@pytest.mark.parametrize(("role", "wording"), [("ROLLING", ROLLING), ("DECENTRALISED", DECENTRALISED)])
def test_rolling_and_decentralised_have_wording_not_a_date(role, wording) -> None:
    deadline = counting_deadline(_app([{"role": role}]), mandatory=False)
    assert deadline == counting_deadline(_app([{"role": role}]), mandatory=True)
    assert deadline is not None and deadline.at is None and deadline.wording == wording


def test_a_bad_date_falls_back_to_the_stored_deadline() -> None:
    stored = datetime(2027, 2, 1, 22, 59, tzinfo=UTC)
    app = _app([_d("FINAL", "15/01/2027")], deadline=stored, deadline_timezone="Europe/Berlin")
    deadline = counting_deadline(app, mandatory=False)
    assert deadline is not None and (deadline.at, deadline.zone) == (stored, "Europe/Berlin")


def test_no_snapshot_and_no_stored_deadline_is_none() -> None:
    assert counting_deadline(Application(program_id=uuid4()), mandatory=False) is None


def test_a_date_with_no_zone_counts_at_the_earliest_instant() -> None:
    deadline = counting_deadline(_app([_d("FINAL", "2027-01-15", tz="")]), mandatory=False)
    assert deadline is not None and deadline.zone == ""
    # 23:59 at UTC+14 is the earliest that day ends anywhere.
    assert deadline.at == datetime(2027, 1, 15, 9, 59, tzinfo=UTC)
    assert both_zones(deadline.at, "", "Asia/Baku") == "15 Jan (time not stated)"


def test_both_zones_names_the_student_day_when_it_differs() -> None:
    at = datetime(2027, 1, 15, 22, 59, tzinfo=UTC)  # 23:59 Stockholm
    assert both_zones(at, "Europe/Stockholm", "Asia/Baku") == (
        "15 Jan, 23:59 Stockholm time (02:59 Baku time, 16 Jan)"
    )


def test_both_zones_without_a_student_zone_shows_one() -> None:
    at = datetime(2027, 1, 15, 22, 59, tzinfo=UTC)
    assert both_zones(at, "Europe/Stockholm", "") == "15 Jan, 23:59 Stockholm time"
    assert both_zones(at, "Europe/Stockholm", "Not/AZone") == "15 Jan, 23:59 Stockholm time"


def test_an_unknown_portal_zone_shows_the_date_only() -> None:
    at = datetime(2027, 1, 15, 22, 59, tzinfo=UTC)
    assert both_zones(at, "Not/AZone", "Asia/Baku") == "15 Jan (time not stated)"


def test_a_pre_check_is_its_own_earlier_date() -> None:
    app = _app([_d("FINAL", "2027-01-31")], pre=_d("FINAL", "2027-01-15", "Europe/Berlin"))
    assert pre_checks(app, "") == ("uni-assist check: send by 15 Jan, 23:59 Berlin time",)


def test_final_passed_only_without_a_submission() -> None:
    now = datetime(2027, 2, 1, tzinfo=UTC)
    app = _app([_d("FINAL", "2027-01-15")])
    assert final_passed(app, now) is True
    app.state = Application.State.SUBMITTED
    assert final_passed(app, now) is False
    assert final_passed(_app([_d("FINAL", "2027-03-01")]), now) is False
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/dashboard/test_dates.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.dashboard.dates'`.

- [ ] **Step 3: Write `apps/dashboard/dates.py`**

```python
"""Which deadline counts and how it reads (lanes spec §9.2-§9.4).

Pure functions over an Application's own copy (`route_snapshot`), falling back
to `Application.deadline`. Never reads the catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from apps.portals.models import Application, zone_named
from apps.portals.route_snapshot import RouteSnapshot, SnapshotDate, read_snapshot

ROLLING = "Apply early: places fill as applications arrive"
DECENTRALISED = "Deadline set by each university"
CLOSED = "Closed for this intake"
#: §9.2: no zone stated means the earliest instant the day ends anywhere.
_EARLIEST = ZoneInfo("Etc/GMT-14")
_ORDER = {
    True: ("FUNDING_CONSIDERATION", "PRIORITY", "FINAL"),
    False: ("PRIORITY", "FINAL"),
}
_SUBMITTED = (Application.State.SUBMITTED, Application.State.CONFIRMED)


@dataclass(frozen=True)
class Deadline:
    at: datetime | None
    #: The IANA zone the date is stated in; "" when not stated.
    zone: str
    wording: str = ""


def _end_of_day(when: SnapshotDate) -> datetime | None:
    try:
        day = date.fromisoformat(when.date)
    except ValueError:
        return None
    where = zone_named(when.timezone) if when.timezone else _EARLIEST
    return datetime.combine(day, time(23, 59), tzinfo=where or _EARLIEST)


def _dates(snapshot: RouteSnapshot | None, purpose: str) -> dict[str, SnapshotDate]:
    if snapshot is None:
        return {}
    return {d.role: d for s in snapshot.steps if s.purpose == purpose for d in s.dates}


def counting_deadline(application: Application, *, mandatory: bool) -> Deadline | None:
    """§9.3: FUNDING_CONSIDERATION, then PRIORITY, then FINAL for a student whose
    funding is MANDATORY; PRIORITY, then FINAL for everyone else."""
    roles = _dates(read_snapshot(application), "APPLY")
    if "ROLLING" in roles:
        return Deadline(None, "", ROLLING)
    if "DECENTRALISED" in roles:
        return Deadline(None, "", DECENTRALISED)
    for role in _ORDER[mandatory]:
        when = roles.get(role)
        at = _end_of_day(when) if when is not None else None
        if at is not None:
            assert when is not None
            return Deadline(at, when.timezone if zone_named(when.timezone) else "")
    if application.deadline is not None:
        return Deadline(application.deadline, application.deadline_timezone)
    return None


def _city(zone: str) -> str:
    return zone.rsplit("/", 1)[-1].replace("_", " ")


def both_zones(at: datetime, zone: str, student_zone: str) -> str:
    """§9.2: "15 Jan, 23:59 Stockholm time (02:59 Baku time, 16 Jan)"."""
    where = zone_named(zone) if zone else None
    if where is None:
        # The UTC day: right for an earliest-instant date (09:59 UTC, same day)
        # and for a stored instant whose zone name is unknown.
        local = at.astimezone(UTC)
        return f"{local.day} {local:%b} (time not stated)"
    local = at.astimezone(where)
    text = f"{local.day} {local:%b}, {local:%H:%M} {_city(zone)} time"
    home = zone_named(student_zone) if student_zone and student_zone != zone else None
    if home is None:
        return text
    mine = at.astimezone(home)
    day = "" if mine.date() == local.date() else f", {mine.day} {mine:%b}"
    return f"{text} ({mine:%H:%M} {_city(student_zone)} time{day})"


def pre_checks(application: Application, student_zone: str) -> tuple[str, ...]:
    """§5.1: a pre-check (uni-assist) is its own earlier deadline -- a date, never
    an instruction."""
    snapshot = read_snapshot(application)
    if snapshot is None:
        return ()
    lines = []
    for step in snapshot.steps:
        if step.purpose != "PRE_CHECK":
            continue
        roles = {d.role: d for d in step.dates}
        when = roles.get("FINAL") or next(iter(roles.values()), None)
        at = _end_of_day(when) if when is not None else None
        if at is None or when is None:
            continue
        name = step.portal_system or "Pre-check"
        lines.append(f"{name} check: send by {both_zones(at, when.timezone, student_zone)}")
    return tuple(lines)


def final_passed(application: Application, now: datetime) -> bool:
    """§9.4: the FINAL date passed with no submission -- "Closed for this intake"."""
    if application.state in _SUBMITTED or application.outcome:
        return False
    when = _dates(read_snapshot(application), "APPLY").get("FINAL")
    at = _end_of_day(when) if when is not None else application.deadline
    return at is not None and at < now
```

`zone_named` must return `None` for an unknown name. Check `apps/portals/models.py:18` first. If it raises instead, wrap the call in `try/except` inside `zone_named` itself, not in each caller.

- [ ] **Step 4: Run `test_dates.py` until it passes**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/dashboard/test_dates.py`
Expected: PASS.

- [ ] **Step 5: Wire the deadline into the card**

In `apps/dashboard/board.py`:
- Delete `_local`.
- Replace the `Card` field `deadline_local: datetime | None` with these, placed after `conditions` because they have defaults:

  ```python
  deadline_text: str = ""
  deadline_wording: str = ""
  closed: bool = False
  pre_checks: tuple[str, ...] = ()
  ```
- In `build_card(...)`, add the keyword arguments `mandatory: bool = False, student_zone: str = ""`. Replace `deadline = application.deadline` with:

  ```python
  counted = counting_deadline(application, mandatory=mandatory)
  deadline = counted.at if counted is not None else None
  ```

  and set the fields:

  ```python
  deadline=deadline,
  deadline_text=(
      both_zones(deadline, counted.zone, student_zone)
      if counted is not None and deadline is not None else ""
  ),
  deadline_wording=counted.wording if counted is not None else "",
  closed=final_passed(application, now),
  pre_checks=pre_checks(application, student_zone),
  days_left=(deadline - now).days if deadline is not None else None,
  ```
- In `board_for`, read the student's latest profile once (a tenant table; same query as `apps/documents/profile_bridge.py:16`):

  ```python
  from apps.accounts.models import StudentProfileVersion
  ...
  profile = StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
  mandatory = (profile.snapshot or {}).get("funding_dependency") == "MANDATORY" if profile else False
  ```

  Pass `mandatory=mandatory, student_zone=student.timezone` to every `build_card` call.

In `templates/student/_card.html`, replace the `{% if card.deadline_local %}…{% endif %}` block with:

```django
{% if card.deadline_text %}
  <p>Deadline: {{ card.deadline_text }} — {% if card.days_left < 0 %}passed{% else %}{{ card.days_left }} day{{ card.days_left|pluralize }} left{% endif %}</p>
{% elif card.deadline_wording %}
  <p>{{ card.deadline_wording }}</p>
{% endif %}
{% if card.closed %}<p>Closed for this intake</p>{% endif %}
```

In `tests/dashboard/test_needs.py::_card`, replace `deadline_local=None` with `deadline_text=""`. Run `grep -rn "deadline_local" apps templates tests` and fix every remaining hit.

- [ ] **Step 6: Add the board test for the student's zone, from Review Focus 1**

Append to `tests/dashboard/test_board.py`:

```python
@pytest.mark.django_db
def test_the_card_shows_both_zones_and_only_one_without_a_student_zone(
    agency_a, membership_a, pack
) -> None:
    programme, _award = pack
    snapshot = {"source": "CATALOGUE", "steps": [{
        "position": 1, "purpose": "APPLY", "channel": "PORTAL",
        "dates": [{"role": "FINAL", "date": "2027-01-15", "timezone": "Europe/Stockholm"}],
    }]}
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme, route_snapshot=snapshot)
        with reads_no_catalogue():
            alone = board_for(membership_a, now=NOW)
        membership_a.timezone = "Asia/Baku"
        membership_a.save(update_fields=["timezone"])
        with reads_no_catalogue():
            both = board_for(membership_a, now=NOW)
    assert alone.cards[0].deadline_text == "15 Jan, 23:59 Stockholm time"
    assert both.cards[0].deadline_text == (
        "15 Jan, 23:59 Stockholm time (02:59 Baku time, 16 Jan)"
    )
```

- [ ] **Step 7: Run the dashboard tests and the gates**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/dashboard tests/concierge tests/portals`, then `uv run ruff check . && uv run mypy apps config`.
Expected: PASS. Fix any test that asserted the old `deadline_local` text. The rendered string changes from "15 Jan 2027, 23:59 Europe/Stockholm" to the §9.2 wording.

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/lanes-plan-2 add apps/dashboard/dates.py apps/dashboard/board.py templates/student/_card.html tests/dashboard
git -C /home/orkhan/Desktop/lanes-plan-2 commit -m "feat(dashboard): the deadline that counts, in the portal's and the student's zone (lanes §9.2-9.4)"
```

---

### Task 2: One lane per programme, and a Done section

**Files:**
- Create: `apps/dashboard/lanes.py`
- Modify: `apps/dashboard/board.py` (`Card.is_award`; drop `Card.funds`, `Card.needs` and `_links`; `Board` becomes lanes; `board_for` reads `ApplicationLink`)
- Modify: `apps/dashboard/routes.py` (the "programme" action, a URL name added in Task 6). In this task, add only the map entries, guarded so a missing name returns "" (below).
- Modify: `templates/student/_board.html`, `templates/student/_card.html` (drop the Funds/Needs lines; `h4` becomes `h5`)
- Modify: `tests/dashboard/test_needs.py` (`_card`: drop `funds`/`needs`, add nothing else; the new fields have defaults)
- Test: `tests/dashboard/test_lanes.py`, `tests/dashboard/test_board.py`

**Interfaces:**
- Consumes: `Card` (Task 1), `Column`.
- Produces:
  - `Lane(key: UUID, title: str, status: str, columns: tuple[tuple[Column, tuple[Card, ...]], ...], also_funded: tuple[str, ...] = (), programmes: tuple[str, ...] = (), done_line: str = "", page_url: str = "", award_lines: tuple[AwardLine, ...] = ())`, with the properties `cards` and `lead`.
  - `lanes_for(cards: Sequence[Card], links: Iterable[tuple[UUID, UUID]], *, page_url: Callable[[UUID], str]) -> tuple[tuple[Lane, ...], tuple[Lane, ...]]`, which returns `(open, done)`.
  - `Board(lanes: tuple[Lane, ...], done: tuple[Lane, ...])`, whose `.cards` property covers both.
  - `Card.is_award: bool = False`.

`award_lines` stays empty in this task; Task 3 fills it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dashboard/test_lanes.py
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from apps.dashboard.board import Card, Column
from apps.dashboard.lanes import lanes_for

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def _card(title, *, award=False, column=Column.TO_START, outcome="", outcome_line="",
          deadline=None, institution="KTH", country="SE") -> Card:
    return Card(
        application_id=uuid4(), title=title, institution=institution, country=country,
        column=column, created_at=NOW, deadline=deadline, days_left=None,
        documents=(0, 0), answers=(0, 0), funding=(), funding_outcome_line="", gap="",
        fee=None, fee_currency="", badges=(), missing=(), outcome_line=outcome_line,
        offer=None, button=None, has_portal=True, portal_url="", kit_url="",
        documents_url="", outcome_url="", remove_url="", portal_record_url="",
        outcome=outcome, conditions=(), is_award=award,
    )


def _page(key):
    return f"/p/{key}/"


def test_a_programme_and_its_one_award_share_a_lane() -> None:
    kth, si = _card("MSc Computer Science"), _card("SI Scholarship", award=True)
    open_, done = lanes_for([kth, si], [(si.application_id, kth.application_id)], page_url=_page)
    assert done == ()
    (lane,) = open_
    assert lane.title == "KTH — MSc Computer Science (Sweden)"
    assert {c.title for c in lane.cards} == {"MSc Computer Science", "SI Scholarship"}
    assert lane.page_url == f"/p/{kth.application_id}/"
    assert lane.status == "Not started"


def test_an_award_for_several_programmes_gets_its_own_lane() -> None:
    a, b = _card("MSc A", institution="UCL", country="GB"), _card("MSc B", institution="LSE", country="GB")
    chev = _card("Chevening Scholarship", award=True)
    links = [(chev.application_id, a.application_id), (chev.application_id, b.application_id)]
    open_, _done = lanes_for([a, b, chev], links, page_url=_page)
    by_title = {lane.title: lane for lane in open_}
    assert by_title["Chevening Scholarship"].programmes == ("MSc A", "MSc B")
    assert by_title["UCL — MSc A (United Kingdom)"].also_funded == (
        "Also funded by your Chevening Scholarship application",
    )
    assert sum(len(lane.cards) for lane in open_) == 3  # the award appears once


def test_a_withdrawn_programme_moves_to_done_and_the_award_keeps_its_lane() -> None:
    a = _card("MSc A", outcome="WITHDRAWN", outcome_line="Withdrawn — by you, 1 Nov",
              column=Column.DECISION)
    b = _card("MSc B")
    chev = _card("Chevening Scholarship", award=True)
    links = [(chev.application_id, a.application_id), (chev.application_id, b.application_id)]
    open_, done = lanes_for([a, b, chev], links, page_url=_page)
    assert [lane.title for lane in done] == ["KTH — MSc A (Sweden)"]
    assert done[0].done_line == "Withdrawn — by you, 1 Nov"
    assert {lane.title for lane in open_} == {"Chevening Scholarship", "KTH — MSc B (Sweden)"}


def test_lanes_order_by_nearest_deadline_undated_last() -> None:
    late = _card("Late", deadline=NOW + timedelta(days=30))
    soon = _card("Soon", deadline=NOW + timedelta(days=3))
    none = _card("Undated")
    open_, _ = lanes_for([late, none, soon], [], page_url=_page)
    assert [lane.lead.title for lane in open_] == ["Soon", "Late", "Undated"]


def test_status_follows_the_lead_card() -> None:
    sub = _card("MSc", column=Column.SUBMITTED)
    dec = _card("MSc 2", column=Column.DECISION, outcome="ADMITTED",
                outcome_line="Admitted — from kth.se's email, 3 Oct")
    open_, _ = lanes_for([sub, dec], [], page_url=_page)
    status = {lane.lead.title: lane.status for lane in open_}
    assert status == {"MSc": "Applied — waiting for a decision",
                      "MSc 2": "Admitted — from kth.se's email, 3 Oct"}


def test_a_link_to_a_card_not_on_the_board_is_ignored() -> None:
    kth, si = _card("MSc"), _card("SI", award=True)
    open_, _ = lanes_for([kth, si], [(si.application_id, uuid4())], page_url=_page)
    assert len(open_) == 2
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/dashboard/test_lanes.py`
Expected: FAIL. The cause is `ModuleNotFoundError`, or `TypeError: unexpected keyword 'is_award'`.

- [ ] **Step 3: Change `Card` and `Board` in `apps/dashboard/board.py`**

- Delete the fields `funds: tuple[str, ...]` and `needs: tuple[str, ...]` from `Card`.
- Add `is_award: bool = False` after `pre_checks` (it has a default, so it goes after the required fields).
- Delete `_links` and the `linked=` parameter of `build_card`.
- In `build_card`, set `is_award=candidate is not None and candidate.opportunity_id is not None`.
- Replace the `Board` class with:

```python
@dataclass(frozen=True)
class Board:
    lanes: tuple[Lane, ...]
    done: tuple[Lane, ...]

    @property
    def cards(self) -> tuple[Card, ...]:
        return tuple(card for lane in (*self.lanes, *self.done) for card in lane.cards)
```

`Lane` is imported from `.lanes`. `lanes.py` imports `Card` and `Column` from `.board` only under `TYPE_CHECKING`, so there is no import cycle at runtime.

- [ ] **Step 4: Write `apps/dashboard/lanes.py`**

```python
"""One lane per programme (lanes spec §5). Pure: groups the cards board_for built.

A separate award card joins the lane of the one programme it is linked to. An
award linked to several programmes gets its own lane, named for the award, and
each of those programmes' lanes says "Also funded by your <award> application".
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from apps.documents.templatetags.cv_countries import country_name
from apps.portals.award_links import AwardLine

from .dates import CLOSED

if TYPE_CHECKING:
    from .board import Card, Column

_FAR = datetime.max.replace(tzinfo=UTC)
_FINISHED = frozenset({"REJECTED", "WITHDRAWN"})


@dataclass(frozen=True)
class Lane:
    key: UUID
    title: str
    status: str
    columns: tuple[tuple[Column, tuple[Card, ...]], ...]
    also_funded: tuple[str, ...] = ()
    programmes: tuple[str, ...] = ()
    done_line: str = ""
    page_url: str = ""
    award_lines: tuple[AwardLine, ...] = ()

    @property
    def cards(self) -> tuple[Card, ...]:
        return tuple(card for _column, cards in self.columns for card in cards)

    @property
    def lead(self) -> Card:
        return next(card for card in self.cards if card.application_id == self.key)


def _title(card: Card) -> str:
    if card.is_award or not card.institution:
        return card.title
    where = f" ({country_name(card.country)})" if card.country else ""
    return f"{card.institution} — {card.title}{where}"


def _status(card: Card) -> str:
    from .board import Column

    if card.closed:
        return CLOSED
    if card.outcome_line:
        return card.outcome_line
    return {
        Column.TO_START: "Not started",
        Column.IN_PROGRESS: "In progress",
        Column.SUBMITTED: "Applied — waiting for a decision",
        Column.CONFIRMED: "Applied — the portal confirmed it, waiting for a decision",
        Column.DECISION: "Decision available",
    }[card.column]


def lanes_for(
    cards: Sequence[Card],
    links: Iterable[tuple[UUID, UUID]],
    *,
    page_url: Callable[[UUID], str],
) -> tuple[tuple[Lane, ...], tuple[Lane, ...]]:
    """(open lanes, done lanes). `links` are (award card, programme card) pairs."""
    from .board import Column

    by_id = {card.application_id: card for card in cards}
    programmes_of: dict[UUID, list[UUID]] = {}
    for award_id, programme_id in links:
        if award_id in by_id and programme_id in by_id:
            programmes_of.setdefault(award_id, []).append(programme_id)
    shared = {a for a, ps in programmes_of.items() if len(ps) > 1}
    members: dict[UUID, list[Card]] = {}
    for card in cards:
        linked = programmes_of.get(card.application_id, [])
        key = linked[0] if card.is_award and len(linked) == 1 else card.application_id
        members.setdefault(key, []).append(card)

    lanes = []
    for key, lane_cards in members.items():
        lead = by_id[key]
        lanes.append(Lane(
            key=key,
            title=_title(lead),
            status=_status(lead),
            columns=tuple(
                (column, tuple(sorted(
                    (c for c in lane_cards if c.column is column),
                    key=lambda c: (c.deadline or _FAR, c.created_at),
                )))
                for column in Column
            ),
            also_funded=tuple(
                f"Also funded by your {by_id[a].title} application"
                for a in sorted(shared, key=lambda a: by_id[a].title)
                if key in programmes_of[a]
            ),
            programmes=(
                tuple(by_id[p].title for p in programmes_of[key]) if key in shared else ()
            ),
            done_line=(
                " · ".join(c.outcome_line for c in lane_cards if c.outcome_line)
                if lead.outcome in _FINISHED else ""
            ),
            page_url=page_url(key),
        ))
    lanes.sort(key=lambda lane: (
        min((c.deadline for c in lane.cards if c.deadline), default=_FAR),
        lane.lead.created_at,
    ))
    return (
        tuple(lane for lane in lanes if not lane.done_line),
        tuple(lane for lane in lanes if lane.done_line),
    )
```

A finished lead whose `outcome_line` is empty would never reach Done. `outcome_line` is never empty when `outcome` is set (see `board.outcome_line`), so this cannot happen. Keep the test above as the pin.

- [ ] **Step 5: Wire `board_for` and the template**

In `board_for`, after building `cards`:

```python
from apps.portals.models import ApplicationLink
...
links = ApplicationLink.objects.filter(from_app__in=applications).values_list(
    "from_app_id", "to_app_id"
)
open_lanes, done = lanes_for(
    cards, links,
    page_url=lambda key: action_url(counselor_view, "programme", student.id, key),
)
return Board(lanes=open_lanes, done=done)
```

In `apps/dashboard/routes.py`, make `action_url` return "" when the URL name does not exist yet. Task 6 adds the names `student-programme` and `counselor-student-programme`. Add the entries `"programme": "student-programme"` to `_STUDENT`, `"programme": "counselor-student-programme"` to `_COUNSELOR`, and `"add"` (used by Task 3) in the same way: `"add": "student-application-add"` / `"add": "counselor-student-application-add"`.

```python
from django.urls import NoReverseMatch, reverse
...
    try:
        if counselor_view:
            name = _COUNSELOR.get(action)
            return reverse(name, args=[student_id, *args]) if name else ""
        name = _STUDENT.get(action)
        return reverse(name, args=list(args)) if name else ""
    except NoReverseMatch:  # ponytail: only until Task 6 adds the programme page
        return ""
```

Task 6 removes this `try/except` once both names exist.

Replace `templates/student/_board.html` with:

```django
<section aria-labelledby="board-heading">
  <h2 id="board-heading">Your applications</h2>
  {% if not board.cards %}<p>No applications yet. Add one from Programmes &amp; funding.</p>{% endif %}
  {% for lane in board.lanes %}
    <section id="lane-{{ lane.key }}" aria-labelledby="lane-title-{{ lane.key }}">
      <h3 id="lane-title-{{ lane.key }}">{% if lane.page_url %}<a href="{{ lane.page_url }}">{{ lane.title }}</a>{% else %}{{ lane.title }}{% endif %}</h3>
      <p>{{ lane.status }}</p>
      {% for line in lane.also_funded %}<p>{{ line }}</p>{% endfor %}
      {% if lane.programmes %}<p>For: {{ lane.programmes|join:", " }}</p>{% endif %}
      {% include "student/_award_lines.html" %}
      {% for column, cards in lane.columns %}{% if cards %}
        <h4>{{ column }}</h4>
        {% for card in cards %}{% include "student/_card.html" %}{% endfor %}
      {% endif %}{% endfor %}
    </section>
  {% endfor %}
  {% if board.done %}
    <section aria-labelledby="done-heading">
      <h3 id="done-heading">Done</h3>
      <ul>{% for lane in board.done %}<li>{% if lane.page_url %}<a href="{{ lane.page_url }}">{{ lane.title }}</a>{% else %}{{ lane.title }}{% endif %}: {{ lane.done_line }}</li>{% endfor %}</ul>
    </section>
  {% endif %}
</section>
```

Create `templates/student/_award_lines.html` as an empty file for now; Task 3 fills it. In `_card.html`, change `<h4 …>` to `<h5 …>` and delete the `Funds:` and `Needs:` lines.

Fix every reader of the old shape: `grep -rn "board.columns\|\.funds\b\|card.needs\|linked=" apps templates tests`. `needs.items_for` reads `board.cards`, which still exists. In `tests/dashboard/test_needs.py::_card`, delete `funds=(), needs=()`.

- [ ] **Step 6: Add the board integration test, from Review Focus 3**

Append to `tests/dashboard/test_board.py`:

```python
@pytest.mark.django_db
def test_the_board_groups_a_programme_and_its_linked_award(agency_a, membership_a, pack) -> None:
    from apps.portals.models import ApplicationLink

    programme, award = pack
    with tenant_scope(agency_a.id):
        p = add_card(agency_a, membership_a, programme)
        a = add_card(agency_a, membership_a, award, portal=False)
        ApplicationLink.objects.create(tenant=agency_a, from_app=a, to_app=p)
        with reads_no_catalogue():
            board = board_for(membership_a)
    (lane,) = board.lanes
    assert lane.key == p.id and {c.application_id for c in lane.cards} == {p.id, a.id}
```

- [ ] **Step 7: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/dashboard tests/concierge tests/portals tests/funding`, then `uv run ruff check . && uv run mypy apps config`.
Expected: PASS. Update any view test that asserted "Funds:" or "Needs:" on a card. Those relations are now lanes.

```bash
git -C /home/orkhan/Desktop/lanes-plan-2 add apps/dashboard templates/student tests/dashboard
git -C /home/orkhan/Desktop/lanes-plan-2 commit -m "feat(dashboard): one lane per programme, an award for several programmes gets its own, finished lanes go to Done (lanes §5)"
```

---

### Task 3: The award lines on a lane, and "Does this apply to you?"

**Files:**
- Modify: `apps/portals/award_links.py` (`AwardLine` fields, texts, the batch function)
- Modify: `apps/dashboard/board.py` (`board_for` attaches the lines to each lane)
- Modify: `templates/student/_award_lines.html`
- Modify: `tests/portals/test_award_links.py` (the line texts, lines ~312-400)
- Test: `tests/portals/test_award_links.py`, `tests/dashboard/test_home.py`

**Interfaces:**
- Consumes: `Lane.award_lines` (Task 2), `action_url(…, "add", …)` (Task 2).
- Produces:
  - `AwardLine(name, kind, text, candidate_id, claim: str = "", source_url: str = "", add_url: str = "")`;
  - `award_lines_for(applications: Sequence[Application]) -> dict[UUID, list[AwardLine]]`;
  - `award_lines(card)`, kept as a thin wrapper.
- `LineKind` replaces `"SUGGESTED"` with `"ASK"`.

- [ ] **Step 1: Change the expected texts in the existing tests, which then fail**

In `tests/portals/test_award_links.py`, change the expected values:
- the SUGGESTED line → kind `"ASK"`, text `"Does this apply to you?"`, `claim` equal to the award's `evidence.claim`;
- the INSTITUTION_NOMINATES text → `"Nominated by the university"`;
- the not-stated text → `"How to apply for this is not stated — see its official page"`, with `source_url` equal to the award's `evidence.source_url`.

Add one test:

```python
def test_award_lines_for_the_whole_board_reads_the_pool_once_per_run(
    agency_a, membership_a, django_assert_max_num_queries, ...
):
    # Two programme cards from the same run: one pool query, one board query.
    ...
    with django_assert_max_num_queries(3):
        lines = award_lines_for([first_card, second_card])
    assert set(lines) == {first_card.id, second_card.id}
```

Fill in the `...` using the file's own `_award` and `_pack` helpers, as the neighbouring tests do. The budget is 3: one query for the applications' candidates, one per run's pool, and one for evidence (via `select_related`).

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/portals/test_award_links.py`
Expected: FAIL on the old texts, and on the missing `award_lines_for`.

- [ ] **Step 3: Implement the change in `apps/portals/award_links.py`**

```python
LineKind = Literal["AUTOMATIC", "SAME_APPLICATION", "NOMINATED", "COMBINED", "ASK", "NOT_STATED"]

_NOT_STATED: tuple[LineKind, str] = (
    "NOT_STATED", "How to apply for this is not stated — see its official page",
)
_LINE_FOR_ROUTE: dict[str, tuple[LineKind, str]] = {
    "AUTOMATIC_ON_ADMISSION": ("AUTOMATIC", "Considered automatically — nothing to do"),
    "CONSIDERED_WITH_ADMISSION": (
        "SAME_APPLICATION", "Considered with your application — nothing extra to submit",
    ),
    "INSTITUTION_NOMINATES": ("NOMINATED", "Nominated by the university"),
    "JOINT_SELECTION": ("COMBINED", "Programme + scholarship, one application"),
}
#: Spec §4.3 (amended 2026-10-10): the one-tap question, with the funder's sentence.
_ASK: tuple[LineKind, str] = ("ASK", "Does this apply to you?")


@dataclass(frozen=True)
class AwardLine:
    name: str
    kind: LineKind
    text: str
    candidate_id: UUID
    claim: str = ""
    source_url: str = ""
    add_url: str = ""


def award_lines_for(applications: Sequence[Application]) -> dict[UUID, list[AwardLine]]:
    """Each programme card's lines (lanes spec §2). `applications` is the
    student's whole board, so "already its own card" is read from it."""
    on_board = {a.candidate_id for a in applications if a.candidate_id is not None}
    pools: dict[UUID, list[RecommendationCandidate]] = {}
    out: dict[UUID, list[AwardLine]] = {}
    for card in applications:
        candidate = card.candidate
        out[card.id] = []
        if candidate is None or _is_award(candidate):
            continue
        if candidate.run_id not in pools:
            pools[candidate.run_id] = list(
                RecommendationCandidate.objects.filter(run_id=candidate.run_id)
                .select_related("evidence").order_by("id")
            )
        for award in pools[candidate.run_id]:
            if (
                not _is_award(award) or award.id in on_board
                or award.state != RecommendationCandidate.State.VISIBLE
                or award.eligibility_status
                == RecommendationCandidate.EligibilityStatus.NOT_ELIGIBLE
                or not funds(award, candidate)
            ):
                continue
            route = (award.funding_card or {}).get("route", "")
            kind, text = _ASK if route in SEPARATE_ROUTES else _LINE_FOR_ROUTE.get(route, _NOT_STATED)
            out[card.id].append(AwardLine(
                award.program_name, kind, text, award.id,
                claim=award.evidence.claim if kind == "ASK" else "",
                source_url=award.evidence.source_url if kind == "NOT_STATED" else "",
            ))
        out[card.id].sort(key=lambda line: line.name.casefold())
    return out


def award_lines(card: Application) -> list[AwardLine]:
    """One card's lines; the board calls `award_lines_for` once instead."""
    board = list(Application.objects.filter(student=card.student).select_related("candidate"))
    return award_lines_for(board).get(card.id, [])
```

Delete `_SUGGESTED`. Keep `_run_pool`, because `link_awards` still uses it. Add `Sequence` to the imports.

- [ ] **Step 4: Attach the lines in `board_for`**

```python
from dataclasses import replace

from apps.portals.award_links import award_lines_for
...
lines = award_lines_for(applications)
open_lanes = tuple(
    replace(lane, award_lines=tuple(
        replace(line, add_url=action_url(counselor_view, "add", student.id, line.candidate_id))
        if line.kind == "ASK" else line
        for line in lines.get(lane.key, [])
    ))
    for lane in open_lanes
)
```

`board_for` already selects `candidate__evidence`, so `award_lines_for` reads `card.candidate` with no extra query.

- [ ] **Step 5: Write `templates/student/_award_lines.html`**

```django
{% for line in lane.award_lines %}
  <p>{{ line.name }}: {{ line.text }}{% if line.source_url %} <a href="{{ line.source_url|https_only }}">Official page</a>{% endif %}</p>
  {% if line.kind == "ASK" %}
    {% if line.claim %}<blockquote>{{ line.claim }}</blockquote>{% endif %}
    {% if line.add_url and not read_only %}<form method="post" action="{{ line.add_url }}">{% csrf_token %}<button type="submit">Yes, add {{ line.name }}</button></form>{% endif %}
  {% endif %}
{% endfor %}
```

Add `{% load dashboard %}` at the top for `https_only`.

- [ ] **Step 6: Add a view test**

Append to `tests/dashboard/test_home.py`. Follow that file's own login and pack helpers. The test adds a programme card whose pack holds a `POSSIBLY_ELIGIBLE` award with `funding_card["route"] = "STUDENT_APPLIES_SEPARATELY"`, then asserts:
- `"Does this apply to you?"` is in the body;
- the award's claim sentence is in the body;
- `f"/student/applications/add/{award.id}/"` is in the body;
- `"Suggested"` is not in the body.

Reaching `POSSIBLY_ELIGIBLE` means setting the fields `eligibility_status` derives from. Read the property in `apps/funding/models.py`.

- [ ] **Step 7: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/portals tests/dashboard`, then `uv run ruff check . && uv run mypy apps config`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-2 add apps/portals/award_links.py apps/dashboard/board.py templates/student/_award_lines.html tests
git -C /home/orkhan/Desktop/lanes-plan-2 commit -m "feat(dashboard): a lane's award lines; 'Does this apply to you?' replaces Suggested (lanes §2, §4.3)"
```

---

### Task 4: "Apply to <programme>", and the extension-required states

**Files:**
- Create: `apps/dashboard/device.py`
- Modify: `apps/dashboard/board.py` (`Button.apply`, `_button`)
- Modify: `apps/concierge/views.py` (`_student_dashboard_page` passes `apply_blocker`)
- Modify: `templates/student/_card.html` (the button block)
- Modify: `tests/dashboard/test_needs.py` (the `_card` default button label)
- Test: `tests/dashboard/test_device.py`, `tests/dashboard/test_home.py`

**Interfaces:**
- Produces:
  - `Blocker(text: str, url: str = "")` and `apply_blocker(user_agent: str, *, paired: bool) -> Blocker | None` in `apps/dashboard/device.py`;
  - `Button(label, url, method="get", apply: bool = False)`.
- The template context key is `apply_blocker`, holding a `Blocker | None`. Task 6 passes it on the programme page too.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dashboard/test_device.py
import pytest

from apps.dashboard.device import INSTALL, OTHER_BROWSER, PHONE, apply_blocker
from apps.dashboard.needs import EXTENSION_URL

CHROME = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
EDGE = CHROME + " Edg/129.0"
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
ANDROID = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/129.0 Mobile Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"


@pytest.mark.parametrize(
    ("agent", "paired", "text"),
    [
        (CHROME, True, None),
        (EDGE, True, None),
        (CHROME, False, INSTALL),
        (FIREFOX, True, OTHER_BROWSER),
        ("", True, OTHER_BROWSER),
        (ANDROID, True, PHONE),
        (IPHONE, False, PHONE),
    ],
)
def test_apply_needs_the_extension_on_a_computer(agent, paired, text) -> None:
    blocker = apply_blocker(agent, paired=paired)
    assert (blocker.text if blocker else None) == text


def test_install_links_the_extension_settings() -> None:
    blocker = apply_blocker(CHROME, paired=False)
    assert blocker is not None and blocker.url == EXTENSION_URL
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/dashboard/test_device.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `apps/dashboard/device.py`**

```python
"""Applying needs the extension, in Chrome or Edge, on a computer (lanes spec §5.1).

Read from the request's User-Agent. A wrong guess costs a sentence in place of
the button, never a refused application: the start route checks pairing itself.
"""

from __future__ import annotations

from dataclasses import dataclass

INSTALL = "Install the extension to apply"
OTHER_BROWSER = "Open this in Chrome or Edge to apply"
PHONE = "Open this on a computer to apply"
_PHONE_MARKS = ("Mobi", "Android", "iPhone", "iPad")


@dataclass(frozen=True)
class Blocker:
    text: str
    url: str = ""


def apply_blocker(user_agent: str, *, paired: bool) -> Blocker | None:
    """None when the Apply button can show."""
    from .needs import EXTENSION_URL

    if any(mark in user_agent for mark in _PHONE_MARKS):
        return Blocker(PHONE)
    if "Chrome/" not in user_agent and "Edg/" not in user_agent:
        return Blocker(OTHER_BROWSER)
    if not paired:
        return Blocker(INSTALL, EXTENSION_URL)
    return None
```

- [ ] **Step 4: Change the button**

In `apps/dashboard/board.py`, add `apply: bool = False` to `Button`. In `_button`, add a `title: str` keyword and pass `title=application.title` from `build_card`. Then replace the two portal branches:

```python
if column in (Column.TO_START, Column.IN_PROGRESS):
    if not has_portal:
        return Button("Open programme page", programme_url) if programme_url else None
    # Guidance spec D2/§3: the extension opens the portal page with its panel.
    return Button(f"Apply to {title}", start_url, "post", apply=True) if start_url else None
```

In `apps/concierge/views.py::_student_dashboard_page`, add to the context:

```python
from apps.dashboard.device import apply_blocker
from apps.portals.pairing import active_pairings
...
"apply_blocker": apply_blocker(
    request.headers.get("User-Agent", ""), paired=bool(active_pairings(student))
),
```

In `templates/student/_card.html`, wrap the button block:

```django
{% if card.button %}
  {% if card.button.apply and apply_blocker %}
    <p>{% if apply_blocker.url %}<a href="{{ apply_blocker.url }}">{{ apply_blocker.text }}</a>{% else %}{{ apply_blocker.text }}{% endif %}</p>
  {% elif card.button.method == "post" %}
    {% if not read_only %}<form method="post" action="{{ card.button.url }}">{% csrf_token %}<button type="submit">{{ card.button.label }}</button></form>{% endif %}
  {% else %}
    <p><a href="{{ card.button.url }}">{{ card.button.label }}</a></p>
  {% endif %}
{% endif %}
```

The counsellor view never builds an `apply=True` button, because its `start_url` is "". It never passes `apply_blocker` either.

In `tests/dashboard/test_needs.py::_card`, change the default button to `Button("Apply to TUM M.Sc.", "/start", "post", apply=True)`, and update the assertion `by_button["Start application"]` to `by_button["Apply to TUM M.Sc."]`.

- [ ] **Step 5: Add the view tests, from Review Focus 5**

Append to `tests/dashboard/test_home.py`, using its own fixtures. The test adds a TO_START card with a portal and no pairing, then:
1. GETs `/student/` with no `HTTP_USER_AGENT` and asserts `"Open this in Chrome or Edge to apply"` is in the body and `"Apply to M.Sc. Informatics"` is not.
2. GETs again with `HTTP_USER_AGENT=CHROME`, the constant from `test_device.py`, and asserts `"Install the extension to apply"` and `/student/settings/extension/`.
3. Creates an active `ExtensionPairing` the way `tests/portals/test_pairing.py` does, GETs with Chrome, and asserts `"Apply to M.Sc. Informatics"` is in the body.

Then GET the counsellor board and assert that `"Apply to"` is not in its body.

- [ ] **Step 6: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/dashboard tests/concierge tests/portals`. Then fix any test asserting "Start application" or "Continue filling". Then run `uv run ruff check . && uv run mypy apps config`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-2 add apps/dashboard apps/concierge/views.py templates/student/_card.html tests
git -C /home/orkhan/Desktop/lanes-plan-2 commit -m "feat(dashboard): 'Apply to <programme>', replaced by the extension, browser or computer sentence (lanes §5.1)"
```

---

### Task 5: Country notices (Russia)

**Files:**
- Create: `apps/dashboard/notices.py`
- Create: `templates/student/_notice.html`
- Modify: `apps/dashboard/board.py` (`Card.notice_line`)
- Modify: `templates/student/_card.html` (one line)
- Test: `tests/dashboard/test_notices.py`

**Interfaces:**
- Produces:
  - `Notice(card_line: str, title: str, intro: str, points: tuple[tuple[str, str], ...], footer: str, checked_on: date, sources: tuple[str, ...])`;
  - `notice_for(country_code: str) -> Notice | None`;
  - `Card.notice_line: str = ""`.
- `_notice.html` expects the context variable `notice`. Task 6 includes it.

- [ ] **Step 1: Check the facts first.** This step is research, not code.

Spec §13a says: "Before it ships: every fact is checked against official sources and shown with its check date." Check each of the four points against an official or primary source:
- **Payments:** Visa's and Mastercard's own March 2022 statements; the EU Council's sanctions page on the SWIFT disconnection.
- **Travel:** the EU airspace closure (Council Regulation (EU) 2022/334), and the UK and US equivalents.
- **Recognition:** the EHEA statement suspending Russia (ehea.info, April 2022).
- **Exchanges:** the European Commission's statement on Erasmus+ cooperation with Russian institutions.

Record each URL in `sources`, and today's date as `checked_on`.

If any point is no longer true, stop and report BLOCKED with the source. Do not edit the owner's wording.

- [ ] **Step 2: Write the failing test**

```python
# tests/dashboard/test_notices.py
from apps.dashboard.notices import notice_for


def test_russia_has_the_owner_wording() -> None:
    notice = notice_for("RU")
    assert notice is not None
    assert notice.card_line == (
        "⚠ Studying in Russia: check payments, travel and degree recognition first — see details."
    )
    assert notice.title == "Before you apply to a programme in Russia"
    assert [label for label, _text in notice.points] == [
        "Payments.", "Travel.", "Degree recognition.", "Exchanges.",
    ]
    assert notice.footer.startswith("This is general information as of ")
    assert "{" not in notice.footer  # the check date is filled in
    assert notice.sources, "every fact is checked against a source before it ships"


def test_no_notice_for_other_countries() -> None:
    assert notice_for("SE") is None
    assert notice_for("") is None
```

- [ ] **Step 3: Write `apps/dashboard/notices.py`**

```python
"""Country notices (lanes spec §13a): display text keyed on a country code.

Owner-approved wording, never catalogue data. New countries are added only by
the owner. Re-check every 3 months: update `checked_on` and `sources`, or report
a fact that changed -- never reword it here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Notice:
    card_line: str
    title: str
    intro: str
    points: tuple[tuple[str, str], ...]
    footer: str
    checked_on: date
    sources: tuple[str, ...]


_RU_CHECKED = date(2026, 10, 11)  # the date Step 1's check was made
_RU = Notice(
    card_line=(
        "⚠ Studying in Russia: check payments, travel and degree recognition first — see details."
    ),
    title="Before you apply to a programme in Russia",
    intro="International sanctions in place since 2022 can affect you as a student:",
    points=(
        ("Payments.", "Visa and Mastercard cards issued outside Russia don't work there, and many Russian banks are cut off from international transfers. Ask your bank, before you pay any fee, how you'll pay the tuition and receive money."),
        ("Travel.", "Flights between Russia and the EU, UK and US are suspended. Depending on where you live, you may need a connection through a country that still flies to Russia, so check routes from your home city."),
        ("Degree recognition.", "Some countries and employers now check Russian degrees more strictly, and Russia's participation in the European Higher Education Area (Bologna) is suspended. If you plan to work or study further in the EU, UK or US, check how your degree will be recognised there."),
        ("Exchanges.", "EU programmes such as Erasmus+ no longer work with Russian universities."),
    ),
    footer=(
        f"This is general information as of {_RU_CHECKED.day} {_RU_CHECKED:%B %Y}, "
        "not legal advice. Rules change; your counsellor can help you check what applies to you."
    ),
    checked_on=_RU_CHECKED,
    sources=(),  # Step 1 fills these; the test refuses an empty tuple
)

_NOTICES = {"RU": _RU}


def notice_for(country_code: str) -> Notice | None:
    return _NOTICES.get((country_code or "").upper())
```

Replace `_RU_CHECKED` and `sources` with what Step 1 found. The `points` text is copied verbatim from spec §13a.

- [ ] **Step 4: Show it**

In `Card`, add `notice_line: str = ""`. In `build_card`, set:

```python
notice_line=(n.card_line if (n := notice_for(candidate.country_code if candidate else "")) else ""),
```

`templates/student/_notice.html`:

```django
<section aria-labelledby="notice-title">
  <h3 id="notice-title">{{ notice.title }}</h3>
  <p>{{ notice.intro }}</p>
  <ul>{% for label, text in notice.points %}<li><strong>{{ label }}</strong> {{ text }}</li>{% endfor %}</ul>
  <p><em>{{ notice.footer }}</em></p>
</section>
```

In `_card.html`, add this after the institution line:

```django
{% if card.notice_line %}<p>{{ card.notice_line }}</p>{% endif %}
```

The "see details" part reaches the programme page through the lane title link (Task 2).

- [ ] **Step 5: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/dashboard`, then `uv run ruff check . && uv run mypy apps config`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-2 add apps/dashboard/notices.py apps/dashboard/board.py templates/student/_notice.html templates/student/_card.html tests/dashboard/test_notices.py
git -C /home/orkhan/Desktop/lanes-plan-2 commit -m "feat(dashboard): the Russia country notice, checked against official sources (lanes §13a)"
```

---

### Task 6: The programme page

**Files:**
- Modify: `apps/dashboard/board.py` (Card page fields: `requirements`, `source_url`, `source_domain`, `last_checked`; `FundingLine` gains `duration`, `deadline`, `source_url`, `source_domain`, `last_checked`)
- Modify: `apps/dashboard/views.py` (`student_programme`, `counselor_programme`, and the shared `_programme_page`)
- Modify: `apps/dashboard/urls.py` (two paths)
- Modify: `apps/dashboard/routes.py` (remove Task 2's `NoReverseMatch` guard)
- Create: `templates/student/programme.html`
- Test: `tests/dashboard/test_programme_page.py`

**Interfaces:**
- Consumes: `Board.lanes` and `Board.done` (Task 2), `Lane.lead`, `notice_for` (Task 5), `apply_blocker` (Task 4), the `Card.deadline_text` and `Card.pre_checks` fields (Task 1).
- Produces:
  - the URL `student/applications/<uuid:application_id>/`, named `student-programme`;
  - the URL `counselor/students/<uuid:student_id>/applications/<uuid:application_id>/`, named `counselor-student-programme`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dashboard/test_programme_page.py
from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import reads_no_catalogue, verify_mfa_session
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db


def _get(client, url, domain):
    return client.get(url, HTTP_HOST=domain.host)


def test_the_student_sees_their_programme_page(client, agency_a, domain_a, membership_a, user_a, pack):
    programme, award = pack
    with tenant_scope(agency_a.id):
        app = add_card(agency_a, membership_a, programme,
                       kit_requirements=["A CV in English"])
    client.force_login(user_a)
    with reads_no_catalogue():
        response = _get(client, f"/student/applications/{app.id}/", domain_a)
    body = response.content.decode()
    assert response.status_code == 200
    assert "TUM — M.Sc. Informatics (Germany)" in body
    assert "A CV in English" in body                    # requirements
    assert "75.00 EUR" in body                          # application fee
    assert "DAAD Study Scholarship" in body             # funding line
    assert "934 EUR a month" in body
    assert "Official source" in body and "last checked" in body
    for never in ("not stated", "Not confirmed", "(unstructured)", "Step 1", "how to apply"):
        assert never not in body


def test_another_students_application_is_the_random_id_404(
    client, agency_a, domain_a, membership_a, user_b, pack
):
    programme, _ = pack
    with tenant_scope(agency_a.id):
        app = add_card(agency_a, membership_a, programme)
    client.force_login(user_b)
    real = _get(client, f"/student/applications/{app.id}/", domain_a)
    invented = _get(client, f"/student/applications/{uuid4()}/", domain_a)
    assert real.status_code == invented.status_code == 404 or (
        real.status_code == invented.status_code == 403
    )


def test_the_assigned_counsellor_sees_it_and_no_one_else(
    client, agency_a, domain_a, membership_a, counselor_user, counselor_membership, pack
):
    programme, _ = pack
    with tenant_scope(agency_a.id):
        app = add_card(agency_a, membership_a, programme)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    url = f"/counselor/students/{membership_a.id}/applications/{app.id}/"
    assert _get(client, url, domain_a).status_code == 404  # not assigned yet
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    with reads_no_catalogue():
        response = _get(client, url, domain_a)
    assert response.status_code == 200
    assert "Apply to" not in response.content.decode()


def test_a_russian_programme_shows_the_full_notice(
    client, agency_a, domain_a, membership_a, user_a, pack
):
    programme, _ = pack
    with tenant_scope(agency_a.id):
        programme.country_code = "RU"
        programme.save(update_fields=["country_code"])
        app = add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    body = _get(client, f"/student/applications/{app.id}/", domain_a).content.decode()
    assert "Before you apply to a programme in Russia" in body
    assert "This is general information as of" in body
```

A user from another membership in the same agency is refused at `current_membership` or by the ownership lookup. Before writing the assertion, check what `user_b`'s membership is in `tests/conftest.py`. Then tighten the second test to the one status code that applies, and assert `_same_response`-style equality the way `tests/portals/test_kit_view.py` does.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/dashboard/test_programme_page.py`
Expected: FAIL with 404 on the student page (no route yet).

- [ ] **Step 3: Add the page fields to the card**

In `apps/dashboard/board.py`:

```python
@dataclass(frozen=True)
class FundingLine:
    name: str
    covers: str
    amounts: str
    duration: str = ""
    deadline: str = ""
    source_url: str = ""
    source_domain: str = ""
    last_checked: datetime | None = None
```

In `build_card`, build each `FundingLine` with:

```python
FundingLine(
    award.program_name,
    _covers(award.funding_card or {}),
    "; ".join(str(a) for a in (award.funding_card or {}).get("amounts", [])),
    duration=str((award.funding_card or {}).get("duration_text") or ""),
    deadline=str((award.funding_card or {}).get("deadline") or ""),
    source_url=https_only(award.evidence.source_url),
    source_domain=award.evidence.source_domain,
    last_checked=award.evidence.last_checked_at,
)
```

`pack_awards` must `select_related("evidence")`. Check `apps/funding/services.py::pack_awards`. If it does not, add it there, because otherwise the board makes one query per award.

Add these `Card` fields with defaults:

```python
requirements: tuple[str, ...] = ()
source_url: str = ""
source_domain: str = ""
last_checked: datetime | None = None
```

and set them in `build_card`:

```python
requirements=tuple(str(r) for r in application.kit_requirements or ()),
source_url=programme_url,
source_domain=candidate.evidence.source_domain if candidate is not None else "",
last_checked=candidate.evidence.last_checked_at if candidate is not None else None,
```

`funding_card["unconfirmed"]` is deliberately not read: unsure facts are never shown (verified-catalog §5.5).

- [ ] **Step 4: Add the views and URLs**

In `apps/dashboard/views.py`:

```python
from django.views.decorators.http import require_safe

from .device import apply_blocker
from .notices import notice_for
from apps.portals.pairing import active_pairings


def _programme_page(
    request: HttpRequest, student: Membership, application_id: UUID, *,
    counselor_view: bool, read_only: str = "", blocker=None,
) -> HttpResponse:
    board = board_for(student, counselor_view=counselor_view)
    lane = next(
        (lane for lane in (*board.lanes, *board.done)
         if any(card.application_id == application_id for card in lane.cards)),
        None,
    )
    if lane is None:
        raise Http404
    return render(request, "student/programme.html", {
        "lane": lane,
        "notice": notice_for(lane.lead.country),
        "outcome_choices": Application.Outcome.choices,
        "read_only": read_only,
        "apply_blocker": blocker,
        "counselor_view": counselor_view,
        "student": student,
    })


@login_required
@require_safe
def student_programme(request: HttpRequest, application_id: UUID) -> HttpResponse:
    try:
        student = current_membership(request, Membership.Role.STUDENT)
    except PermissionDenied:
        raise Http404 from None
    return _programme_page(
        request, student, application_id, counselor_view=False,
        blocker=apply_blocker(
            request.headers.get("User-Agent", ""), paired=bool(active_pairings(student))
        ),
    )


@login_required
@require_safe
def counselor_programme(request: HttpRequest, student_id: UUID, application_id: UUID) -> HttpResponse:
    _counselor, student = _assigned(request, student_id)
    return _programme_page(
        request, student, application_id, counselor_view=True, read_only=paused_reason(student),
    )
```

In `apps/dashboard/urls.py`, add:

```python
path("student/applications/<uuid:application_id>/", views.student_programme, name="student-programme"),
path(_BASE + "applications/<uuid:application_id>/", views.counselor_programme, name="counselor-student-programme"),
```

In `apps/dashboard/routes.py`, delete Task 2's `try/except NoReverseMatch`, because both names now exist.

- [ ] **Step 5: Write `templates/student/programme.html`**

```django
{% extends "base.html" %}
{% load dashboard %}
{% block title %}{{ lane.title }}{% endblock %}
{% block content %}
<h1>{{ lane.title }}</h1>
<p>{{ lane.status }}</p>
{% if read_only %}<p>{{ read_only }}</p>{% endif %}
{% for line in lane.also_funded %}<p>{{ line }}</p>{% endfor %}
{% if lane.programmes %}<p>For: {{ lane.programmes|join:", " }}</p>{% endif %}

{% with lead=lane.lead %}
  <section aria-labelledby="deadlines">
    <h2 id="deadlines">Deadlines</h2>
    {% if lead.deadline_text %}<p>{{ lead.deadline_text }}</p>{% elif lead.deadline_wording %}<p>{{ lead.deadline_wording }}</p>{% endif %}
    {% for line in lead.pre_checks %}<p>{{ line }}</p>{% endfor %}
    {% if lead.closed %}<p>Closed for this intake</p>{% endif %}
  </section>

  {% if lead.requirements %}
    <section aria-labelledby="requirements">
      <h2 id="requirements">Requirements</h2>
      <ul>{% for item in lead.requirements %}<li>{{ item }}</li>{% endfor %}</ul>
    </section>
  {% endif %}

  <section aria-labelledby="money">
    <h2 id="money">Money</h2>
    {% if lead.fee %}<p>Application fee: {{ lead.fee }} {{ lead.fee_currency }} — you pay this at submission</p>{% endif %}
    {% if lead.gap %}<p>Remaining gap: {{ lead.gap }}</p>{% endif %}
  </section>

  <section aria-labelledby="funding">
    <h2 id="funding">Funding</h2>
    {% include "student/_award_lines.html" %}
    {% for line in lead.funding %}
      <h3>{{ line.name }}</h3>
      <dl>
        {% if line.covers %}<dt>Covers</dt><dd>{{ line.covers }}</dd>{% endif %}
        {% if line.amounts %}<dt>Amount</dt><dd>{{ line.amounts }}</dd>{% endif %}
        {% if line.duration %}<dt>Pays for</dt><dd>{{ line.duration }}</dd>{% endif %}
        {% if line.deadline %}<dt>Deadline</dt><dd>{{ line.deadline }}</dd>{% endif %}
      </dl>
      {% if line.source_url %}<p><a href="{{ line.source_url }}">Official source</a> · {{ line.source_domain }}{% if line.last_checked %} · last checked {{ line.last_checked|date:"j M Y" }}{% endif %}</p>{% endif %}
    {% empty %}
      {% if not lane.award_lines %}<p>No scholarship found for this programme yet.</p>{% endif %}
    {% endfor %}
  </section>

  {% if lead.source_url %}
    <p><a href="{{ lead.source_url }}">Official source</a> · {{ lead.source_domain }}{% if lead.last_checked %} · last checked {{ lead.last_checked|date:"j M Y" }}{% endif %}</p>
  {% endif %}
{% endwith %}

{% if notice %}{% include "student/_notice.html" %}{% endif %}

<section aria-labelledby="cards">
  <h2 id="cards">Applications</h2>
  {% for card in lane.cards %}{% include "student/_card.html" %}{% endfor %}
</section>
<p><a href="{% if counselor_view %}{% url 'counselor-student-board' student.id %}{% else %}{% url 'concierge-student-dashboard' %}{% endif %}">Back to your applications</a></p>
{% endblock %}
```

Check `templates/base.html` for the block names (`title`, `content`) and use the ones it defines.

- [ ] **Step 6: Run the tests and the gates, then commit**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/dashboard tests/concierge tests/portals tests/funding`, then `uv run ruff check . && uv run mypy apps config && uv run python manage.py check`.

```bash
git -C /home/orkhan/Desktop/lanes-plan-2 add apps/dashboard apps/funding/services.py templates/student/programme.html tests/dashboard/test_programme_page.py
git -C /home/orkhan/Desktop/lanes-plan-2 commit -m "feat(dashboard): the programme page -- deadlines, requirements, money, funding, source, country notice (lanes §5.1)"
```

---

### Task 7: Programmes & funding without "not stated", "(unstructured)" or "Not confirmed", and the spec's plan-2b note

**Files:**
- Modify: `templates/student/_funding_group.html`
- Modify: `apps/funding/grouping.py` (`group_label`: the country name)
- Modify: `tests/funding/test_grouped_page.py` (the `:30` and `:148` assertions)
- Modify: `docs/superpowers/specs/2026-10-09-programme-lanes-and-money-design.md` (§14: plan 2 / 2b)
- Test: `tests/funding/test_grouped_page.py`, `tests/funding/test_grouping.py` (or wherever `group_label` is tested: `grep -rn group_label tests`)

- [ ] **Step 1: Change the tests first**

In `tests/funding/test_grouped_page.py`:
- change the `"(unstructured)"` assertion at `:30` to assert `"Who can apply"` is present and `"(unstructured)"` is absent;
- add the assertions `"not stated" not in body` and `"Not confirmed" not in body` to the same test;
- update the `group_label` test so that a COUNTRY-scope award with `country_code="DE"` gives `"Eligible programmes in Germany"`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider tests/funding/test_grouped_page.py $(grep -rln group_label tests)`
Expected: FAIL.

- [ ] **Step 3: Edit the template and the label**

In `templates/student/_funding_group.html`, replace lines 6–11 (the `<dl>` body) with:

```django
{% if card.holder %}<dt>Holder</dt><dd>{{ card.holder }}</dd>{% endif %}
{% if card.tuition or card.living %}<dt>Covers</dt><dd>{% if card.tuition %}Tuition: {{ card.tuition|lower }}{% endif %}{% if card.tuition and card.living %}; {% endif %}{% if card.living %}living: {{ card.living|lower }}{% endif %}</dd>{% endif %}
{% if card.amounts %}<dt>Amount</dt><dd>{{ card.amounts|join:"; " }}</dd>{% endif %}
{% if card.deadline %}<dt>Deadline</dt><dd>{{ card.deadline }}</dd>{% endif %}
{% if award.evidence.claim %}<dt>Who can apply</dt><dd>{{ award.evidence.claim }}</dd>{% endif %}
```

In `apps/funding/grouping.py::group_label`:

```python
from apps.documents.templatetags.cv_countries import country_name
...
        return f"Eligible programmes in {country_name(award.country_code)}"
```

- [ ] **Step 4: Record the split in the spec**

In spec §14's table:
- change the plan 2 row's "Contents" to name this plan's scope;
- add a row: `| 2b. Lanes, the rest | cascades and outcomes (§6), rounds (§8), start-by lead times (§9.1), fit/risk/requirement statuses, EMJM tracks, scholarship renewal and obligations, the nomination task, Apply to the first step not DONE | plan 1b, the tailored build, plan 4 |`.

Copy the "Deferred to plan 2b" table from this plan's header into §16 as one bullet that points to this plan file.

- [ ] **Step 5: Run the tests and the gates, then commit**

Run the full suite once: `POSTGRES_DB=elmify_lanes2 uv run pytest -q -p no:cacheprovider`. Then run all five gates from Global Constraints.

```bash
git -C /home/orkhan/Desktop/lanes-plan-2 add templates/student/_funding_group.html apps/funding/grouping.py tests/funding docs/superpowers/specs/2026-10-09-programme-lanes-and-money-design.md
git -C /home/orkhan/Desktop/lanes-plan-2 commit -m "fix(funding): no 'not stated', '(unstructured)' or 'Not confirmed'; country names in group labels; spec records plan 2b"
```
