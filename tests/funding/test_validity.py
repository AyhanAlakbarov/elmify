"""Only OPEN and UPCOMING reach a student, so every state gets a row.

Table-driven on purpose: the cases are data, and no scheme, funder or country
is named in the module under test.
"""

import datetime as dt

import pytest

from apps.funding.validity import (
    Evidence,
    RegisterCadence,
    cycle_validity,
    intake_start_year,
    project_window,
    select_deadline,
)

TODAY = dt.date(2026, 9, 18)


def _state(evidence, intake, *, student=None, today=TODAY):
    return cycle_validity(
        evidence, student=student or {}, target_intake=intake, today=today
    )


@pytest.mark.parametrize(
    ("text", "year"),
    [
        ("2026-2028", 2026),
        ("2026/27", 2026),
        ("2026-27", 2026),
        ("Fall 2026", 2026),
        ("UNSTATED", None),
        ("", None),
    ],
)
def test_intake_start_year(text, year):
    assert intake_start_year(text) == year


@pytest.mark.parametrize(
    ("evidence", "intake", "expected"),
    [
        # A dated statement inside the cycle window naming this intake.
        (
            Evidence(offered="YES", applies_to="2026-2028", stated_on=dt.date(2026, 5, 12)),
            "2026-2028",
            "OPEN",
        ),
        (Evidence(offered="YES", deadline=dt.date(2027, 1, 15)), "2027-2028", "OPEN"),
        # A later dated contradiction for this intake beats an undated yes.
        (
            Evidence(
                offered="YES", deadline=dt.date(2027, 1, 15), contrary_on=dt.date(2026, 8, 1),
                contrary_intake="2027-2028",
            ),
            "2027-2028",
            "SUSPENDED",
        ),
        (
            Evidence(offered="NO", applies_to="2026-2028", stated_on=dt.date(2025, 10, 15)),
            "2026-2028",
            "SUSPENDED",
        ),
        # The same negation says nothing about another intake.
        (
            Evidence(offered="NO", applies_to="2026-2028", stated_on=dt.date(2025, 10, 15)),
            "2028-2030",
            "UNVERIFIED",
        ),
        # The owner's case: a March-May window for a September start, in September.
        (
            Evidence(
                offered="YES",
                past_calls=(
                    (dt.date(2026, 3, 3), dt.date(2026, 5, 15)),
                    (dt.date(2025, 3, 4), dt.date(2025, 5, 16)),
                ),
            ),
            "2027-2028",
            "UPCOMING",
        ),
        (Evidence(offered="YES", recurrence_stated="March"), "2027-2028", "UPCOMING"),
        # One cycle is not a cadence.
        (
            Evidence(offered="YES", past_calls=((dt.date(2026, 3, 3), dt.date(2026, 5, 15)),)),
            "2027-2028",
            "UNVERIFIED",
        ),
        (
            Evidence(
                offered="YES",
                past_calls=(
                    (dt.date(2026, 3, 3), dt.date(2026, 5, 15)),
                    (dt.date(2025, 3, 4), dt.date(2025, 5, 16)),
                ),
                contrary_on=dt.date(2026, 9, 1),
                contrary_intake="2027-2028",
            ),
            "2027-2028",
            "SUSPENDED",
        ),
        (Evidence(offered="YES", deadline=dt.date(2026, 3, 1)), "2026-2027", "CLOSED_FOR_INTAKE"),
        # A dated yes about a different intake verifies nothing.
        (
            Evidence(offered="YES", applies_to="2025-2026", stated_on=dt.date(2025, 4, 1)),
            "2026-2027",
            "UNVERIFIED",
        ),
        (Evidence(offered="YES"), "2027-2028", "UNVERIFIED"),
        (
            Evidence(offered="YES", from_register=True, grant_window_end=dt.date(2026, 8, 31)),
            "2027-2028",
            "ENDED",
        ),
        (Evidence(offered="YES", page_removed=True), "2027-2028", "ENDED"),
    ],
)
def test_validity_states(evidence, intake, expected):
    assert _state(evidence, intake) == expected


def test_the_students_own_deadline_decides_open_or_closed():
    evidence = Evidence(
        offered="YES",
        deadlines=(
            (dt.date(2026, 10, 15), "NATIONALITY:IN"),
            (dt.date(2026, 11, 30), "NATIONALITY:TR"),
            (dt.date(2026, 12, 15), "ALL"),
        ),
    )
    today = dt.date(2026, 11, 1)
    assert _state(evidence, "2027-2028", student={"nationality": "IN"}, today=today) == (
        "CLOSED_FOR_INTAKE"
    )
    assert _state(evidence, "2027-2028", student={"nationality": "TR"}, today=today) == "OPEN"
    # No condition of theirs: the unconditional date is theirs.
    assert _state(evidence, "2027-2028", student={"nationality": "NG"}, today=today) == "OPEN"


def test_a_condition_for_the_students_group_without_a_date_is_reported_not_guessed():
    evidence = Evidence(
        offered="YES",
        deadlines=((dt.date(2026, 12, 15), "ALL"),),
        conditions_without_dates=("NATIONALITY:IN",),
    )
    chosen = select_deadline(evidence, student={"nationality": "IN"})
    assert chosen is not None
    assert chosen.date == dt.date(2026, 12, 15) and chosen.missing_for == "NATIONALITY:IN"


def test_a_condition_nothing_can_match_is_nobodys_deadline():
    """OTHER:<text> is a group we cannot test a student against. It must not
    become somebody's date by accident."""
    evidence = Evidence(
        offered="YES",
        deadlines=(
            (dt.date(2026, 10, 1), "OTHER:members of the Karajan-Akademie"),
            (dt.date(2026, 12, 15), "ALL"),
        ),
    )
    chosen = select_deadline(evidence, student={"nationality": "IN"})
    assert chosen is not None and chosen.condition == "ALL"


def test_register_cadence_verified_this_cycle_is_recurrence_evidence():
    evidence = Evidence(
        offered="YES",
        register_cadence=RegisterCadence(
            open_month=10, deadline_month=1,
            source="https://funder.example/how-to-apply", verified_for_cycle=2026,
        ),
    )
    assert _state(evidence, "2027-2028") == "UPCOMING"


def test_a_stale_register_cadence_verifies_nothing():
    evidence = Evidence(
        offered="YES",
        register_cadence=RegisterCadence(
            open_month=10, deadline_month=1,
            source="https://funder.example/how-to-apply", verified_for_cycle=2024,
        ),
    )
    assert _state(evidence, "2027-2028") == "UNVERIFIED"


def test_history_without_an_annual_statement_is_upcoming():
    evidence = Evidence(
        offered="YES",
        past_calls=(
            (dt.date(2025, 10, 1), dt.date(2026, 1, 8)),
            (dt.date(2024, 10, 2), dt.date(2025, 1, 9)),
            (dt.date(2023, 10, 3), dt.date(2024, 1, 10)),
        ),
    )
    assert _state(evidence, "2027-2028") == "UPCOMING"


def test_a_gap_year_breaks_the_chain():
    evidence = Evidence(
        offered="YES",
        past_calls=(
            (dt.date(2026, 3, 3), dt.date(2026, 5, 15)),
            (dt.date(2024, 3, 4), dt.date(2024, 5, 16)),
        ),
    )
    assert _state(evidence, "2027-2028") == "UNVERIFIED"


def test_the_projection_is_arithmetic_on_the_last_observed_cycle():
    past = (
        (dt.date(2026, 3, 3), dt.date(2026, 5, 15)),
        (dt.date(2025, 3, 4), dt.date(2025, 5, 16)),
    )
    assert project_window(past, target_year=2027) == (dt.date(2027, 3, 3), dt.date(2027, 5, 15))


def test_a_cycle_that_spans_the_new_year_projects_before_its_intake():
    """An October call with a January deadline serves the following autumn's
    intake, so projecting it for 2027 must land in October 2026 -- not inside
    the intake it is meant to fund."""
    past = (
        (dt.date(2025, 10, 1), dt.date(2026, 1, 8)),
        (dt.date(2024, 10, 2), dt.date(2025, 1, 9)),
    )
    assert project_window(past, target_year=2027) == (dt.date(2026, 10, 1), dt.date(2027, 1, 8))


def test_a_southern_hemisphere_intake_takes_its_own_start_date():
    """The September default is a default. A February intake with a November
    deadline is open, and reading it against 1 September would close it."""
    evidence = Evidence(offered="YES", deadline=dt.date(2027, 11, 30))
    assert _state(evidence, "2028") == "OPEN"
    assert (
        cycle_validity(
            evidence, student={}, target_intake="2028", today=TODAY,
            intake_starts_on=dt.date(2028, 2, 1),
        )
        == "OPEN"
    )


def test_a_deadline_condition_uses_the_same_decider_as_eligibility():
    """NATIONALITY:IN on a deadline row and CITIZENSHIP on an award row must
    agree about the same student, or the pack shows one date and gates on another."""
    evidence = Evidence(
        offered="YES",
        deadlines=(
            (dt.date(2026, 10, 15), "NATIONALITY:EASTERN_PARTNERSHIP"),
            (dt.date(2026, 12, 15), "ALL"),
        ),
    )
    chosen = select_deadline(evidence, student={"nationality": "AZ"})
    assert chosen is not None and chosen.date == dt.date(2026, 10, 15)

    other = select_deadline(evidence, student={"nationality": "BR"})
    assert other is not None and other.date == dt.date(2026, 12, 15)


def test_a_partition_condition_is_still_matched_verbatim():
    """ROUND and APPLICANT_CLASS are not eligibility keys and decide by equality."""
    evidence = Evidence(
        offered="YES",
        deadlines=((dt.date(2026, 10, 1), "ROUND:2"), (dt.date(2026, 12, 15), "ALL")),
    )
    chosen = select_deadline(evidence, student={"round": "2"})
    assert chosen is not None and chosen.date == dt.date(2026, 10, 1)


def test_a_descent_condition_matches_by_equality_not_the_eligibility_decider():
    """decide()'s DESCENT branch abstains unconditionally -- the profile never
    collects descent -- so a descent-conditioned deadline must not route
    through it, or it always falls back to the general date."""
    evidence = Evidence(
        offered="YES",
        deadlines=(
            (dt.date(2026, 10, 1), "DESCENT:POLISH"),
            (dt.date(2026, 12, 15), "ALL"),
        ),
    )
    chosen = select_deadline(evidence, student={"descent": "polish"})
    assert chosen is not None and chosen.date == dt.date(2026, 10, 1)

    other = select_deadline(evidence, student={"descent": "italian"})
    assert other is not None and other.date == dt.date(2026, 12, 15)


def test_an_undecidable_condition_still_flags_missing_for():
    """UNDECIDABLE means the shared decider could not tell, not that the
    student fails the condition -- for missing_for that is still worth
    reporting, unlike for choosing a date."""
    evidence = Evidence(
        offered="YES",
        deadlines=((dt.date(2026, 12, 15), "ALL"),),
        conditions_without_dates=("NATIONALITY:AZ",),
    )
    chosen = select_deadline(evidence, student={})
    assert chosen is not None
    assert chosen.date == dt.date(2026, 12, 15) and chosen.missing_for == "NATIONALITY:AZ"


def test_a_residence_condition_reads_country_of_residence():
    """The student-dict key contract: RESIDENCE reads `country_of_residence`,
    the name every other profile in this codebase uses -- see
    select_deadline's docstring for the full contract."""
    evidence = Evidence(
        offered="YES",
        deadlines=((dt.date(2026, 10, 1), "RESIDENCE:DE"), (dt.date(2026, 12, 15), "ALL")),
    )
    chosen = select_deadline(evidence, student={"country_of_residence": "DE"})
    assert chosen is not None and chosen.date == dt.date(2026, 10, 1)


def test_a_null_profile_field_does_not_crash_the_shared_decider():
    """A student-dict entry recorded as None must mean the same thing as a key
    that was never asked. PRIOR_INSTITUTION reads academic_history with its
    own () default; a null there used to reach tuple(None) and crash out of
    select_deadline uncaught, rather than abstaining like a missing key."""
    evidence = Evidence(
        offered="YES",
        deadlines=(
            (dt.date(2026, 10, 1), "PRIOR_INSTITUTION:AZ"),
            (dt.date(2026, 12, 15), "ALL"),
        ),
    )
    chosen = select_deadline(evidence, student={"academic_history": None})
    assert chosen is not None and chosen.date == dt.date(2026, 12, 15)


def test_an_open_row_never_outranks_a_students_own_specific_deadline():
    """decide()'s OPEN key is SATISFIED unconditionally -- an OPEN row is
    exactly as unconditional as ALL and must not beat a genuinely specific
    condition for "most specific"."""
    evidence = Evidence(
        offered="YES",
        deadlines=(
            (dt.date(2026, 10, 1), "OPEN"),
            (dt.date(2026, 12, 15), "NATIONALITY:AZ"),
        ),
    )
    chosen = select_deadline(evidence, student={"nationality": "AZ"})
    assert chosen is not None and chosen.date == dt.date(2026, 12, 15)


def test_a_bare_partition_condition_matches_nobody():
    """ROUND with no value names no student's group; it must not match every
    student whose dict happens to lack a "round" key and outrank the ALL date."""
    evidence = Evidence(
        offered="YES",
        deadlines=((dt.date(2026, 10, 1), "ROUND"), (dt.date(2026, 12, 15), "ALL")),
    )
    chosen = select_deadline(evidence, student={})
    assert chosen is not None and chosen.date == dt.date(2026, 12, 15)


def test_the_intake_a_call_serves_is_the_first_intake_start_after_it():
    """A deadline before September serves that year's intake; one after it
    serves the next. Measuring from the calendar year instead projected every
    autumn call a year late (the October/November case, cycle_verification)."""
    from apps.funding.validity import served_intake_year

    assert served_intake_year(dt.date(2026, 5, 15)) == 2026
    assert served_intake_year(dt.date(2026, 9, 1)) == 2026
    assert served_intake_year(dt.date(2025, 11, 30)) == 2026


def test_an_autumn_call_with_an_autumn_deadline_projects_before_its_intake():
    past = (
        (dt.date(2025, 10, 1), dt.date(2025, 11, 30)),
        (dt.date(2024, 10, 1), dt.date(2024, 11, 30)),
    )
    assert project_window(past, target_year=2027) == (dt.date(2026, 10, 1), dt.date(2026, 11, 30))
