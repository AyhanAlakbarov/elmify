from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.dashboard.dates import (
    DECENTRALISED,
    ROLLING,
    both_zones,
    counting_deadline,
    final_passed,
    pre_checks,
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


@pytest.mark.parametrize(
    ("role", "wording"), [("ROLLING", ROLLING), ("DECENTRALISED", DECENTRALISED)]
)
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
    assert both_zones(deadline.at, "", "Asia/Baku") == "15 Jan (end of day)"


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
    assert both_zones(at, "Not/AZone", "Asia/Baku") == "15 Jan (end of day)"


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


def test_a_zoneless_final_date_is_closed_only_once_it_ended_everywhere() -> None:
    app = _app([_d("FINAL", "2027-01-15", tz="")])
    # 23:59 at UTC-12 is 11:59 UTC on the 16th: before it, some place is still open.
    assert final_passed(app, datetime(2027, 1, 16, 11, 0, tzinfo=UTC)) is False
    assert final_passed(app, datetime(2027, 1, 16, 12, 0, tzinfo=UTC)) is True
    # ...while the counting deadline stays the cautious, earliest instant.
    assert counting_deadline(app, mandatory=False).at == datetime(2027, 1, 15, 9, 59, tzinfo=UTC)


def test_an_unreadable_final_falls_back_to_the_stored_deadline_when_closing() -> None:
    now = datetime(2027, 2, 1, tzinfo=UTC)
    stored = datetime(2027, 1, 20, tzinfo=UTC)
    assert final_passed(_app([_d("FINAL", "15/01/2027")], deadline=stored), now) is True
    later = datetime(2027, 3, 1, tzinfo=UTC)
    assert final_passed(_app([_d("FINAL", "15/01/2027")], deadline=later), now) is False
