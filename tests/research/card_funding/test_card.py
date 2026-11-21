from apps.research.candidates import Date
from apps.research.card_engine import Quote
from apps.research.card_funding.card import (
    FIELDS,
    HOLD_REASONS,
    Hold,
    award_card,
    unread_award,
)
from apps.research.card_funding.parse import AwardDate, Nationality, Parsed, Value

URL = "https://example.edu.az/scholarships"


def _date(role, day, cycle=None, places=()):
    date = Date(f"{day} May 2027", 0, 10, 2027, 5, day)
    return Value(AwardDate(role, date, False, places, cycle), Quote(f"{day} May 2027", "L1.text"),
                 URL, ())


def test_every_field_is_shown_held_or_not_stated():
    card = award_card("Rector's Scholarship", Quote("Rector's Scholarship", "L0.text"), {
        "target_level": Parsed((Value("master", Quote("master", "L2.text"), URL, ()),)),
        "benefits": Parsed(problem="unresolved_split", detail="pays_m1"),
    })
    assert tuple(card.fields) == FIELDS
    assert {f.state for f in card.fields.values()} <= {"shown", "held", "not_stated"}
    assert card.fields["target_level"].state == "shown"
    assert card.fields["benefits"].state == "held" and card.fields["dates"].state == "not_stated"
    assert card.holds == (Hold("unresolved_split", "benefits", "pays_m1"),)
    assert {h.reason for h in card.holds} <= set(HOLD_REASONS)


def test_two_deadlines_of_one_cycle_or_of_no_cycle_conflict():
    dates = Parsed((_date("application_deadline", 15), _date("application_deadline", 20)))
    card = award_card("A", None, {"dates": dates})
    assert (card.fields["dates"].state, card.fields["dates"].hold, card.fields["dates"].detail) == (
        "held", "conflicting_values", "application_deadline")
    dates = Parsed((_date("application_deadline", 15, 2026),
                    _date("application_deadline", 20, 2026)))
    assert award_card("A", None, {"dates": dates}).fields["dates"].hold == "conflicting_values"


def test_the_newest_stated_cycle_wins_and_place_dates_never_conflict():
    old, new = _date("application_deadline", 15, 2026), _date("application_deadline", 20, 2027)
    for_az = _date("application_deadline", 1, places=("AZ",))
    card = award_card("A", None, {"dates": Parsed((old, new, for_az))})
    assert card.fields["dates"].state == "shown"
    assert set(card.fields["dates"].values) == {new, for_az}
    same = Parsed((_date("application_deadline", 15), _date("application_deadline", 15)))
    assert len(award_card("A", None, {"dates": same}).fields["dates"].values) == 1


def test_a_partly_held_group_is_shown_and_held_for_its_countries_only():
    nationality = Nationality(frozenset({"AZ", "KZ"}), frozenset(), frozenset({"UA"}),
                              "citizenship", ("CIS",))
    card = award_card("A", None, {"nationality": Parsed((Value(nationality, None, URL, ()),))})
    assert card.fields["nationality"].state == "shown"
    assert card.holds == (Hold("held_country_group", "nationality", "CIS", frozenset({"UA"})),)


def test_an_unread_award_holds_every_field_for_one_reason():
    card = unread_award("A", None, "deadline")
    assert {(f.state, f.hold) for f in card.fields.values()} == {("held", "deadline")}
    assert card.holds == (Hold("deadline", "*", ""),)


def _day_value(day, spelling, start=0, cycle=None, places=(), role="application_deadline"):
    date = Date(spelling, start, start + 10, 2027, 5, day)
    return Value(AwardDate(role, date, False, places, cycle), Quote(spelling, "L1.text"), URL, ())


def test_one_deadline_written_twice_is_one_value():
    for a, b in ((_day_value(15, "15 May 2027", 0), _day_value(15, "15 May 2027", 40)),
                 (_day_value(15, "15 May 2027"), _day_value(15, "15.05.2027"))):
        field = award_card("A", None, {"dates": Parsed((a, b))}).fields["dates"]
        assert field.state == "shown" and len(field.values) == 1


def test_place_deadlines_are_checked_per_place_group():
    two = Parsed((_day_value(1, "1 May", cycle=2026, places=("AZ",)),
                  _day_value(9, "9 May", cycle=2026, places=("AZ",))))
    assert award_card("A", None, {"dates": two}).fields["dates"].hold == "conflicting_values"
    old = _day_value(1, "1 May 2026", cycle=2026, places=("AZ",))
    new = _day_value(9, "9 May 2027", cycle=2027, places=("AZ",))
    field = award_card("A", None, {"dates": Parsed((old, new))}).fields["dates"]
    assert field.values == (new,)


def test_a_stated_cycle_beats_an_undated_deadline():
    new, undated = _day_value(20, "20 May 2027", cycle=2027), _day_value(15, "15 May 2027")
    field = award_card("A", None, {"dates": Parsed((undated, new))}).fields["dates"]
    assert field.state == "shown" and field.values == (new,)


def test_other_roles_pass_through_unchanged():
    two = Parsed((_day_value(1, "1 May", role="programme_start"),
                  _day_value(9, "9 May", role="programme_start")))
    assert len(award_card("A", None, {"dates": two}).fields["dates"].values) == 2


def test_not_stated_route_leaves_route_order_held():
    from datetime import date

    from apps.research.candidates import find_all
    from apps.research.card_engine import Decision
    from apps.research.card_funding.parse import parse_award

    c = find_all([])
    decisions = [Decision("route", "agreed", "not_stated", None, {}),
                 Decision("route_order", "unresolved", None, None, {})]
    parsed = parse_award(decisions, c, {}, source=URL, funder_country="", lang="en",
                         today=date(2026, 1, 1))
    assert set(parsed) == set(FIELDS)
    assert parsed["route_order"].problem == "unresolved_split"


def test_hold_validates_its_reason_and_whole_group_hold_renders():
    import pytest

    with pytest.raises(ValueError):
        Hold("bogus", "benefits")
    card = award_card("A", None, {"nationality": Parsed(problem="held_country_group",
                                                         detail="CIS")})
    assert card.fields["nationality"].hold == "held_country_group"
    n = Nationality(frozenset(), frozenset(), frozenset({"UA"}), "citizenship",
                    ("CIS:beside_list", "EU"))
    held = award_card("A", None, {"nationality": Parsed((Value(n, None, URL, ()),))}).holds
    assert held[0].detail == "EU"


def _held(values):
    f = award_card("A", None, {"dates": Parsed(tuple(values))}).fields["dates"]
    return f.state, f.hold, f.detail


def _y(year, month, day, cycle=None, places=()):
    date = Date(f"{day}/{month}/{year}", 0, 8, year, month, day)
    return Value(AwardDate("application_deadline", date, False, places, cycle), None, URL, ())


def test_an_extra_parse_key_raises():
    import pytest

    with pytest.raises(ValueError):
        award_card("A", None, {"bogus": Parsed()})


def test_a_newer_date_is_never_dropped_by_an_older_cycle():
    assert _held([_y(2025, 3, 1, 2025), _y(2027, 3, 1)])[:2] == ("held", "conflicting_values")
    assert _held([_y(2025, 3, 1, 2026), _y(2027, 3, 1, 2025)])[:2] == (
        "held", "conflicting_values")
    ok = award_card("A", None, {"dates": Parsed((_y(2027, 3, 1, 2027), _y(2025, 3, 1)))})
    assert ok.fields["dates"].state == "shown"


def test_places_group_as_a_set_and_each_country_must_agree():
    assert award_card("A", None, {"dates": Parsed((
        _y(2027, 3, 1, places=("AZ", "GE")), _y(2027, 3, 1, places=("GE", "AZ"))))}
    ).fields["dates"].state == "shown"
    assert len(award_card("A", None, {"dates": Parsed((
        _y(2027, 3, 1, places=("AZ", "AZ")), _y(2027, 3, 1, places=("AZ",))))}
    ).fields["dates"].values) == 1
    state, hold, detail = _held([_y(2027, 3, 1, 2027, ("AZ",)),
                                 _y(2027, 5, 1, 2027, ("AZ", "GE"))])
    assert (state, hold, detail) == ("held", "conflicting_values", "application_deadline:AZ")


def test_a_place_group_older_than_the_general_cycle_holds():
    assert _held([_y(2025, 3, 1, 2025, ("AZ",)), _y(2027, 5, 1, 2027)])[1] == (
        "conflicting_values")


def test_place_and_general_on_different_days_of_one_cycle_show_both():
    card = award_card("A", None, {"dates": Parsed((_y(2027, 3, 1, 2027, ("AZ",)),
                                                    _y(2027, 5, 1, 2027)))})
    assert len(card.fields["dates"].values) == 2


def test_about_three_months_is_kept_apart_from_three_months():
    from apps.research.candidates import RelativeDate

    def rel(approx):
        d = RelativeDate("3 months", 0, 5, 3, 3, "months", "before", "start", approx)
        return Value(AwardDate("fee_deadline", d, False, (), None), None, URL, ())

    assert _held([rel(True), rel(False)])[1] == "conflicting_values"


def test_f2_f3_a_country_deadline_with_no_cycle_is_compared_by_its_own_year():
    """Probes F2 and F3: AZ's 1 May 2024 has no cycle label; its year is 2024, older than the
    general deadline's (a stated 2027 cycle, or the date's own 2027)."""
    for general in (_y(2027, 5, 9, 2027), _y(2027, 5, 9)):
        assert _held([_y(2024, 5, 1, places=("AZ",)), general]) == (
            "held", "conflicting_values", "application_deadline:AZ")


def test_f4_a_stale_general_deadline_beside_a_current_country_one_holds():
    """Probe F4: the reverse direction -- the GENERAL group is the stale one."""
    assert _held([_y(2025, 5, 1, 2025), _y(2027, 5, 9, 2027, ("AZ",))]) == (
        "held", "conflicting_values", "application_deadline")


def test_r_a_relative_only_newest_cycle_never_drops_an_absolute_date():
    from apps.research.candidates import RelativeDate

    rel = RelativeDate("2 weeks", 0, 7, 2, 2, "weeks", "before", "start", False)
    newest = Value(AwardDate("application_deadline", rel, False, (), 2027), None, URL, ())
    assert _held([newest, _y(2027, 5, 1)])[:2] == ("held", "conflicting_values")


def test_no_cycle_place_and_general_deadlines_of_one_year_are_both_shown():
    """"Azerbaijanis: 1 March 2027; others: 1 May 2027" -- decision 13, with no cycle at all."""
    card = award_card("A", None, {"dates": Parsed((_y(2027, 3, 1, places=("AZ",)),
                                                    _y(2027, 5, 1)))})
    assert card.fields["dates"].state == "shown" and len(card.fields["dates"].values) == 2


def test_a_conflicting_nationality_holds_only_its_countries():
    n = Nationality(frozenset({"KZ"}), frozenset({"RU"}), frozenset(), "citizenship", (),
                    frozenset({"AZ"}))
    card = award_card("A", None, {"nationality": Parsed((Value(n, None, URL, ()),))})
    assert card.fields["nationality"].state == "shown"
    assert card.holds == (Hold("conflicting_values", "nationality", "", frozenset({"AZ"})),)


def test_a_held_field_keeps_what_the_hunt_may_fall_back_to_and_the_card_its_cycle():
    from apps.research.card_funding.card import Field

    fallback = Value(Nationality(frozenset(), frozenset({"HU"}), frozenset(), "not_stated",
                                 ("INTERNATIONAL",)), None, URL, ())
    card = award_card("A", None, {"nationality": Parsed((fallback,), "needs_hunt",
                                                        "internationals")}, cycle=2026)
    nationality = card.fields["nationality"]
    assert (nationality.state, nationality.hold, nationality.values) == (
        "held", "needs_hunt", (fallback,))
    assert card.cycle == 2026 and nationality.label == ""
    assert "hunt_not_found" in HOLD_REASONS
    assert Field("dates", "shown", label="last_cycle").label == "last_cycle"
