"""Stored evidence -> validity.Evidence. One known-answer row per state (spec 9.3)."""
import datetime as dt

from apps.funding.cycle_evidence import deadline_student, observations, past_calls, to_evidence
from apps.funding.validity import RegisterCadence, cycle_validity

TODAY = dt.date(2026, 9, 26)


def _entry(**overrides):
    entry = {
        "step": "0", "url": "https://funder.example/award", "sha256": "a" * 64,
        "at": "2026-09-20", "archived": False, "captured_at": "", "offered": "YES",
        "applies_to": "UNSTATED", "intake_year": None, "stated_on": None,
        "deadlines": [], "quote": "The Example Award funds master's study.",
        "agreement": "AGREED",
    }
    entry.update(overrides)
    return entry


def _state(entries, intake, **kwargs):
    evidence = to_evidence(entries, target_year=intake, cadence=kwargs.pop("cadence", None),
                           page_removed=False, lapsed=kwargs.pop("lapsed", False))
    return cycle_validity(evidence, student=kwargs.pop("student", {}),
                          target_intake=str(intake), today=kwargs.pop("today", TODAY))


def test_suspended_the_chemoinformatics_shape():
    """A dated disclaimer naming the intake beats an undated 'about 20 each year'."""
    entries = [
        _entry(quote="about 20 Erasmus Mundus scholarships"),
        _entry(offered="NO", applies_to="2026-2028", intake_year=2026, stated_on="2025-10-15",
               quote="the 2026-2028 intake will be without scholarship"),
    ]
    assert _state(entries, 2026, today=dt.date(2025, 11, 1)) == "SUSPENDED"


def test_upcoming_a_march_may_scheme_in_september_with_two_past_calls():
    entries = [
        _entry(stated_on="2026-03-03", deadlines=[["2026-05-15", "ALL", "ALL"]]),
        _entry(archived=True, captured_at="2025-04-01", stated_on="2025-03-04",
               deadlines=[["2025-05-16", "ALL", "ALL"]]),
    ]
    assert _state(entries, 2027) == "UPCOMING"


def test_unverified_a_first_year_scheme():
    entries = [_entry(stated_on="2026-03-03", deadlines=[["2026-05-15", "ALL", "ALL"]])]
    assert _state(entries, 2027) == "UNVERIFIED"


def test_last_cycles_deadline_is_an_observation_not_this_intakes_deadline():
    """An undated line 'Deadline: 15 January 2026' says nothing about 2027 --
    read as 2027's deadline it would close an award that has not opened."""
    entries = [_entry(deadlines=[["2026-01-15", "ALL", "ALL"]])]
    evidence = to_evidence(entries, target_year=2027, cadence=None, page_removed=False,
                           lapsed=False)
    assert evidence.deadlines == ()
    assert [o["intake_year"] for o in observations(entries)] == [2026]


def test_a_cycle_seen_only_by_its_deadline_is_observed_but_not_a_dated_call():
    entries = [_entry(deadlines=[["2025-05-16", "ALL", "ALL"]]),
               _entry(deadlines=[["2026-05-15", "ALL", "ALL"]])]
    assert past_calls(observations(entries), before=2027) == ()


def test_a_lapsed_projection_is_withheld_so_validity_says_unverified():
    entries = [
        _entry(stated_on="2026-03-03", deadlines=[["2026-05-15", "ALL", "ALL"]]),
        _entry(archived=True, stated_on="2025-03-04", deadlines=[["2025-05-16", "ALL", "ALL"]]),
    ]
    cadence = RegisterCadence(open_month=3, deadline_month=5, source="https://r.example",
                              verified_for_cycle=2026)
    assert _state(entries, 2027, cadence=cadence, lapsed=True) == "UNVERIFIED"


def test_the_students_own_deadline_survives_the_round_trip():
    entries = [_entry(deadlines=[["2026-10-15", "applicants from India", "NATIONALITY:IN"],
                                 ["2026-12-15", "ALL", "ALL"]])]
    assert _state(entries, 2027, student={"nationality": "IN"},
                  today=dt.date(2026, 11, 1)) == "CLOSED_FOR_INTAKE"
    assert _state(entries, 2027, student={"nationality": "TR"},
                  today=dt.date(2026, 11, 1)) == "OPEN"


def test_deadline_student_carries_the_eu_class_from_the_sourced_region():
    assert deadline_student("DE", "DE")["applicant_class"] == "EU"
    assert deadline_student("AZ", "TR")["applicant_class"] == "NON_EU"
    assert deadline_student("", "")["applicant_class"] == ""


def test_a_stated_on_after_its_intake_started_is_not_that_intakes_opening():
    """An archived 'intake 2026' page stamped 2026-10-01 was stamped after the
    2026 intake began; taken as 2026's opening it invents a second past call."""
    last = _entry(archived=True, stated_on="2025-03-04", deadlines=[["2025-05-16", "ALL", "ALL"]])
    stamped_late = _entry(archived=True, intake_year=2026, stated_on="2026-10-01")
    assert past_calls(observations([last, stamped_late]), before=2027) == (
        (dt.date(2025, 3, 4), dt.date(2025, 5, 16)),
    )
    today = dt.date(2027, 6, 1)
    assert _state([last, stamped_late], 2027, today=today) != "UPCOMING"
    genuine = _entry(archived=True, stated_on="2026-03-03",
                     deadlines=[["2026-05-15", "ALL", "ALL"]])
    assert _state([last, genuine], 2027, today=today) == "CLOSED_FOR_INTAKE"


def test_a_deadline_is_the_target_intakes_by_intake_of_across_a_leap_year():
    """2027-09-02 falls in intake 2028's window, which is 366 days long."""
    entries = [_entry(deadlines=[["2027-09-02", "ALL", "ALL"]])]
    evidence = to_evidence(entries, target_year=2028, cadence=None, page_removed=False,
                           lapsed=False)
    assert evidence.deadlines == ((dt.date(2027, 9, 2), "ALL"),)


def test_an_unparseable_stated_on_does_not_outrank_an_undated_no():
    entries = [
        _entry(offered="NO", applies_to="2027", intake_year=2027,
               quote="the 2027 intake will be without scholarship"),
        _entry(applies_to="2027", intake_year=2027, stated_on="garbage"),
    ]
    assert _state(entries, 2027) == "SUSPENDED"


def test_cycles_observed_names_each_intake_once():
    entries = [_entry(deadlines=[["2026-10-15", "ALL", "ALL"], ["2026-12-15", "ALL", "ALL"]])]
    evidence = to_evidence(entries, target_year=2027, cadence=None, page_removed=False,
                           lapsed=False)
    assert evidence.cycles_observed == ("2027",)


def test_a_dated_call_whose_deadline_has_passed_is_closed_not_open():
    entries = [_entry(intake_year=2027, applies_to="2027", stated_on="2026-10-01",
                      deadlines=[["2027-01-15", "ALL", "ALL"]])]
    assert _state(entries, 2027, today=dt.date(2027, 4, 1)) == "CLOSED_FOR_INTAKE"


def test_an_unagreed_no_does_not_suspend_an_agreed_yes():
    """Three readings that did not agree on a NO have not established one."""
    entries = [
        _entry(applies_to="2027-2028", intake_year=2027, deadlines=[["2027-01-15", "ALL", "ALL"]]),
        _entry(offered="NO", applies_to="2027-2028", intake_year=2027, stated_on="2026-09-01",
               agreement="UNAGREED", quote="no scholarships for the 2027 intake"),
    ]
    assert _state(entries, 2027) != "SUSPENDED"


def test_an_unagreed_yes_alone_verifies_nothing():
    entries = [_entry(applies_to="2027-2028", intake_year=2027, stated_on="2026-09-01",
                      deadlines=[["2027-01-15", "ALL", "ALL"]], agreement="UNAGREED")]
    assert _state(entries, 2027) == "UNVERIFIED"
    assert observations(entries) == []


def test_an_entry_without_an_agreement_is_not_agreed():
    entry = _entry(applies_to="2027-2028", intake_year=2027,
                   deadlines=[["2027-01-15", "ALL", "ALL"]])
    del entry["agreement"]
    assert _state([entry], 2027) == "UNVERIFIED"
