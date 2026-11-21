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
    a = _card("MSc A", institution="UCL", country="GB")
    b = _card("MSc B", institution="LSE", country="GB")
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


def test_a_withdrawn_shared_award_adds_no_also_funded_line() -> None:
    a, b = _card("MSc A"), _card("MSc B")
    chev = _card("Chevening Scholarship", award=True, outcome="WITHDRAWN",
                 outcome_line="Withdrawn", column=Column.DECISION)
    links = [(chev.application_id, a.application_id), (chev.application_id, b.application_id)]
    open_, done = lanes_for([a, b, chev], links, page_url=_page)
    assert [lane.title for lane in done] == ["Chevening Scholarship"]
    assert all(lane.also_funded == () for lane in open_)


def test_closed_lanes_sort_after_open_ones() -> None:
    from dataclasses import replace

    early = replace(_card("Closed one", deadline=NOW - timedelta(days=9)), closed=True)
    late = _card("Open one", deadline=NOW + timedelta(days=90))
    open_, _done = lanes_for([early, late], [], page_url=_page)
    assert [lane.lead.title for lane in open_] == ["Open one", "Closed one"]
