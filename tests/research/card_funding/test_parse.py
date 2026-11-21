import datetime as dt
from decimal import Decimal

from apps.research.candidates import Line, find_all
from apps.research.card_engine import Decision, Quote, Section, locate
from apps.research.card_funding.parse import (
    AwardDate,
    Benefit,
    Condition,
    Nationality,
    parse_award,
)
from apps.research.card_funding.questions import code_questions

URL = "https://example.edu.az/scholarships"
TODAY = dt.date(2026, 10, 13)


def _section(*texts):
    return Section("Rector's Scholarship", "en", tuple(Line(t) for t in texts))


def _decisions(section, answers, unresolved=()):
    """An agreed decision for every code question: scripted (value, quote) or its absence."""
    out = []
    for q in code_questions(find_all(section.lines)):
        if q.id in unresolved:
            out.append(Decision(q.id, "unresolved", None, None, {}))
            continue
        value, quote = answers.get(q.id, (sorted(set(q.options) & q.unquoted)[0], ""))
        out.append(Decision(q.id, "agreed", value, locate(quote, section) if quote else None, {}))
    return out


def _parse(section, answers, unresolved=(), proposed=None, funder_country="", **extra):
    decisions = _decisions(section, answers, unresolved) + list(extra.pop("more", ()))
    return parse_award(decisions, find_all(section.lines), proposed or {}, source=URL,
                       funder_country=funder_country, lang="en", today=TODAY)


def _key(section, group, text):
    c = find_all(section.lines)
    return next(k for k, f in getattr(c, group).items() if f.value.text == text)


def test_an_amount_is_the_candidate_code_read_with_the_labels_the_readers_chose():
    s = _section("Monthly stipend of AZN 300 for living costs",
                 "Application fee: AZN 20")
    m1, m2 = _key(s, "amounts", "AZN 300"), _key(s, "amounts", "AZN 20")
    fields = _parse(s, {
        f"pays_{m1}": ("paid_to_student", "Monthly stipend of AZN 300"),
        f"covers_living_{m1}": ("yes", "living costs"),
        f"frequency_{m1}": ("monthly", "Monthly"),
        f"bound_{m1}": ("exact", "AZN 300"),
        f"for_student_{m1}": ("yes", "stipend"),
        f"pays_{m2}": ("application_fee", "Application fee"),
        f"frequency_{m2}": ("one_off", "Application fee"),
    })
    [stipend] = fields["benefits"].values
    benefit = stipend.value
    assert isinstance(benefit, Benefit)
    assert (benefit.amount.low, benefit.amount.currency) == (Decimal("300"), "AZN")
    assert (benefit.covers, benefit.frequency, benefit.bound) == ({"living"}, "monthly", "exact")
    assert stipend.quote == Quote("AZN 300", "L0.text") and stipend.source == URL
    assert {d.question for d in stipend.decisions} >= {f"pays_{m1}", f"frequency_{m1}"}
    [fee] = fields["fees"].values  # a fee charged to the student never becomes a benefit
    assert fee.value.pays == "application_fee"


def test_an_unresolved_label_holds_the_field_and_only_that_field():
    s = _section("Monthly stipend of AZN 300", "Apply by 15 May 2027.")
    m1, d1 = _key(s, "amounts", "AZN 300"), _key(s, "dates", "15 May 2027")
    fields = _parse(s, {f"pays_{m1}": ("paid_to_student", "AZN 300"),
                        f"role_{d1}": ("application_deadline", "Apply by 15 May 2027.")},
                    unresolved={f"frequency_{m1}"})
    assert (fields["benefits"].problem, fields["benefits"].detail) == (
        "unresolved_split", f"frequency_{m1}")
    [deadline] = fields["dates"].values
    assert deadline.value == AwardDate("application_deadline", find_all(s.lines).dates[d1].value,
                                       False, ())


def test_an_ambiguous_date_needs_its_order_and_a_year():
    s = _section("Deadline 10/11/2026", "Opens 1 March")
    d1, d2 = _key(s, "dates", "10/11/2026"), _key(s, "dates", "1 March")
    roles = {f"role_{d1}": ("application_deadline", "Deadline 10/11/2026"),
             f"role_{d2}": ("application_opening", "Opens 1 March")}
    fields = _parse(s, {**roles, f"order_{d1}": ("day_first", "10/11/2026")})
    assert (fields["dates"].problem, fields["dates"].detail) == ("unparseable_value", d2)
    fields = _parse(_section("Deadline 10/11/2026"),
                    {f"role_{d1}": roles[f"role_{d1}"], f"order_{d1}": ("day_first", "10/11/2026")})
    [deadline] = fields["dates"].values
    assert (deadline.value.date.day, deadline.value.date.month) == (10, 11)
    fields = _parse(_section("Deadline 10/11/2026"), {f"role_{d1}": roles[f"role_{d1}"]})
    assert fields["dates"].problem == "unparseable_value"  # order not answered: never guessed


def test_a_page_date_moves_the_group_lists_to_its_own_day():
    s = _section("Open to citizens of CIS countries.", "Updated 1 May 2027")
    p1, d1 = _key(s, "places", "CIS countries"), _key(s, "dates", "1 May 2027")
    [value] = _parse(s, {f"eligible_{p1}": ("yes", "CIS countries"),
                         f"role_{d1}": ("page_published_or_updated", "Updated 1 May 2027")})[
        "nationality"].values
    assert "MD" in value.value.held  # Moldova's exit took effect on 2027-04-08


def test_year_of_study_names_a_level_through_the_funders_country():
    s = _section("Open to 1st–3rd year students")
    answer = {"target_level": ("year_of_study", "1st–3rd year students")}
    for funder_country in ("AZ", "DE"):  # an Azerbaijani and a German funder
        assert _parse(s, answer, funder_country=funder_country)["target_level"].values[
            0].value == "bachelor", funder_country
    held = _parse(s, answer, funder_country="")["target_level"]  # an unknown funder
    assert (held.values, held.problem, held.detail) == ((), "unparseable_value", "target_level")


def test_a_named_country_list_is_the_nationality_and_both_answers_are_not_stated():
    s = _section("Citizens of Azerbaijan and Georgia may apply; Georgia excluded this year.")
    az, ge = _key(s, "places", "Azerbaijan"), _key(s, "places", "Georgia")
    fields = _parse(s, {f"eligible_{az}": ("yes", "Citizens of Azerbaijan"),
                        f"eligible_{ge}": ("yes", "Georgia may apply"),
                        f"excluded_{ge}": ("yes", "Georgia excluded"),
                        "place_basis": ("citizenship", "Citizens")})
    [value] = fields["nationality"].values
    assert value.value == Nationality(frozenset({"AZ"}), frozenset(), frozenset(), "citizenship",
                                      ())


def test_a_group_with_no_list_on_the_page_reads_through_the_fallback():
    s = _section("Open to citizens of CIS countries.")
    p1 = _key(s, "places", "CIS countries")
    [value] = _parse(s, {f"eligible_{p1}": ("yes", "citizens of CIS countries")})[
        "nationality"].values
    assert "AZ" in value.value.eligible and value.value.held == {"UA"}
    assert "GE" not in value.value.eligible | value.value.held


def test_developing_countries_holds_a_dac_country_unless_the_page_says_dac():
    s = _section("Open to applicants from developing countries.")
    p1 = _key(s, "places", "developing countries")
    [value] = _parse(s, {f"eligible_{p1}": ("yes", "developing countries")})["nationality"].values
    assert value.value.eligible == set() and "AZ" in value.value.held
    s = _section("Open to applicants from developing countries (DAC list).")
    p1 = _key(s, "places", "developing countries")
    [value] = _parse(s, {f"eligible_{p1}": ("yes", "developing countries")})["nationality"].values
    assert "AZ" in value.value.eligible and value.value.held == set()


def test_the_funders_own_list_comes_before_the_group():
    s = _section("Developing countries, namely Azerbaijan and Kenya, are eligible.")
    keys = {f.value.text: k for k, f in find_all(s.lines).places.items()}
    answers = {f"eligible_{k}": ("yes", "are eligible") for k in keys.values()}
    [value] = _parse(s, answers)["nationality"].values
    assert value.value.eligible == {"AZ", "KE"} and value.value.held == set()
    assert value.value.groups == ("DEVELOPING:beside_list",)


def test_vague_groups_and_pointers_hold_or_hunt():
    s = _section("Open to students from the Global South.")
    p1 = _key(s, "places", "Global South")
    fields = _parse(s, {f"eligible_{p1}": ("yes", "Global South")})
    assert (fields["nationality"].problem, fields["nationality"].detail) == (
        "held_country_group", "GLOBAL_SOUTH")
    s = _section("International students are welcome to apply.")
    fields = _parse(s, {"internationals": ("yes", "International students are welcome")})
    assert fields["nationality"].problem == "needs_hunt"
    s = _section("See the list of eligible countries.")
    fields = _parse(s, {"eligibility_elsewhere": ("yes", "See the list of eligible countries")})
    assert (fields["nationality"].problem, fields["nationality"].detail) == (
        "needs_hunt", "eligibility_elsewhere")
    s = _section("Open to partner countries only.")
    p1 = _key(s, "places", "partner countries")
    fields = _parse(s, {f"eligible_{p1}": ("yes", "partner countries")})
    assert (fields["nationality"].problem, fields["nationality"].detail) == (
        "unparseable_value", p1)


def test_requirements_union_code_and_proposed_quotes():
    s = _section("IELTS 6.5 required.", "Stateless persons may also apply.")
    c1 = _key(s, "requirements", "IELTS 6.5")
    proposed = {"requirements": (Quote("Stateless persons may also apply", "L1.text"),)}
    kind = Decision("kind_0", "agreed", "stateless",
                    Quote("Stateless persons may also apply", "L1.text"), {})
    fields = _parse(s, {f"requires_{c1}": ("yes", "IELTS 6.5 required")}, proposed=proposed,
                    more=[kind])
    conditions = [v.value for v in fields["requirements"].values]
    assert conditions[0].kind == "language_test" and conditions[0].requirement.score == Decimal(
        "6.5")
    assert conditions[1] == Condition("stateless", None)


def test_labels_flags_and_route_order():
    s = _section("Students apply to the ministry before admission. Travel is covered.")
    fields = _parse(s, {"route": ("student_applies_separately", "Students apply"),
                        "route_order": ("before_admission", "before admission"),
                        "extra_travel": ("yes", "Travel is covered"),
                        "apply_elsewhere": ("yes", "apply to the ministry")})
    assert fields["route_order"].values[0].value == "before_admission"
    assert fields["extras"].values[0].value == {"travel"}
    assert fields["apply_elsewhere"].values[0].value == "yes"
    assert fields["discontinued"].values == ()
    fields = _parse(s, {"route": ("considered_with_admission", "Students apply"),
                        "route_order": ("before_admission", "before admission")})
    assert fields["route_order"].values == ()


def test_an_excluded_group_keeps_its_held_members_held():
    s = _section("Open to all except citizens of CIS countries.")
    p1 = _key(s, "places", "CIS countries")
    [value] = _parse(s, {f"excluded_{p1}": ("yes", "except citizens of CIS countries")})[
        "nationality"].values
    assert "UA" in value.value.held and "AZ" in value.value.excluded


def test_an_excluded_developing_countries_group_holds_instead_of_answering_empty():
    s = _section("Applicants from developing countries cannot apply.")
    p1 = _key(s, "places", "developing countries")
    [value] = _parse(s, {f"excluded_{p1}": ("yes", "developing countries")})["nationality"].values
    assert "AZ" in value.value.held  # no DAC mention: held, not an empty answer


def test_none_is_a_stated_level_label_not_an_absent_one():
    s = _section("The scholarship does not cover tuition.")
    fields = _parse(s, {"tuition_level": ("none", "does not cover tuition")})
    [value] = fields["tuition_level"].values
    assert value.value == "none" and value.quote is not None


def test_a_place_limit_code_cannot_read_holds_the_amount():
    s = _section("AZN 500 per month for applicants from partner countries")
    m1, p1 = _key(s, "amounts", "AZN 500"), _key(s, "places", "partner countries")
    fields = _parse(s, {f"pays_{m1}": ("paid_to_student", "AZN 500"),
                        f"for_{p1}_{m1}": ("yes", "partner countries")})
    assert (fields["benefits"].problem, fields["benefits"].detail) == ("unparseable_value", p1)


def test_a_date_limit_code_cannot_read_holds_the_dates():
    s = _section("Apply by 15 May 2027 if from partner countries")
    d1, p1 = _key(s, "dates", "15 May 2027"), _key(s, "places", "partner countries")
    fields = _parse(s, {f"role_{d1}": ("application_deadline", "15 May 2027"),
                        f"for_{p1}_{d1}": ("yes", "partner countries")})
    assert (fields["dates"].problem, fields["dates"].detail) == ("unparseable_value", p1)


def test_all_applicants_together_with_a_place_limit_is_a_contradiction():
    s = _section("AZN 500 per month for applicants from Georgia")
    m1, p1 = _key(s, "amounts", "AZN 500"), _key(s, "places", "Georgia")
    fields = _parse(s, {f"pays_{m1}": ("paid_to_student", "AZN 500"),
                        f"for_all_{m1}": ("yes", "AZN 500"), f"for_{p1}_{m1}": ("yes", "Georgia")})
    assert (fields["benefits"].problem, fields["benefits"].detail) == ("unparseable_value", m1)


def test_funding_period_is_the_one_intake_on_the_line_pointed_at():
    s = _section("The 2024/25 round is closed.", "Funded for the 2026/27 academic year.")
    fields = _parse(s, {"funding_period": ("yes", "Funded for the 2026/27 academic year.")})
    [period] = fields["funding_period"].values
    assert period.value.start_year == 2026 and len(fields["funding_period"].values) == 1
    s = _section("Funded for the 2025/26 and 2026/27 academic years.")
    fields = _parse(s, {"funding_period": ("yes", "Funded for the 2025/26")})
    assert fields["funding_period"].problem == "unparseable_value"


def test_a_proposed_requirement_with_no_answer_holds_the_field():
    s = _section("Stateless persons may also apply.")
    proposed = {"requirements": (Quote("Stateless persons may also apply", "L0.text"),)}
    fields = _parse(s, {}, proposed=proposed)
    assert (fields["requirements"].problem, fields["requirements"].detail) == (
        "unparseable_value", "too_many_proposals")


def test_amounts_found_but_none_of_them_money_hold_instead_of_not_stated():
    s = _section("Monthly stipend of AZN 300")
    m1 = _key(s, "amounts", "AZN 300")
    fields = _parse(s, {f"pays_{m1}": ("not_stated", "")})
    assert (fields["benefits"].problem, fields["benefits"].detail) == ("unparseable_value", m1)


def test_a_conversion_pair_is_one_benefit():
    s = _section("Stipend of AZN 500 (about USD 300) per month")
    c = find_all(s.lines)
    assert c.conversion_of, "fixture must produce a conversion pair"
    base = next(iter(c.conversion_of.values()))
    fields = _parse(s, {f"pays_{base}": ("paid_to_student", "AZN 500")})
    [benefit] = fields["benefits"].values
    assert benefit.value.conversion is not None and benefit.value.conversion.currency == "USD"


def test_an_exclusion_never_cancels_the_hunt_for_who_may_apply():
    for group, sentence in (("CIS countries", "citizens of CIS countries"),
                            ("Russia", "citizens of Russia"),
                            ("developing countries", "citizens of developing countries")):
        s = _section(f"International students may apply, except {sentence}.")
        p1 = _key(s, "places", group)
        fields = _parse(s, {"internationals": ("yes", "International students may apply"),
                            f"excluded_{p1}": ("yes", f"except {sentence}")})
        assert fields["nationality"].problem == "needs_hunt", group


def test_a_group_never_shows_an_uncertain_excluded_country_eligible():
    s = _section("Open to developing countries (DAC list), except CIS countries.")
    p1, p2 = _key(s, "places", "developing countries"), _key(s, "places", "CIS countries")
    [value] = _parse(s, {f"eligible_{p1}": ("yes", "developing countries"),
                         f"excluded_{p2}": ("yes", "except CIS countries")})["nationality"].values
    assert "UA" in value.value.held and "UA" not in value.value.eligible
    assert "AZ" in value.value.excluded


def test_a_country_named_outright_stays_eligible_beside_an_excluded_group():
    s = _section("Open to Ukraine and developing countries, except CIS countries.")
    keys = {f.value.text: k for k, f in find_all(s.lines).places.items()}
    [value] = _parse(s, {f"eligible_{keys['Ukraine']}": ("yes", "Open to Ukraine"),
                         f"eligible_{keys['developing countries']}": ("yes", "developing"),
                         f"excluded_{keys['CIS countries']}": ("yes", "except CIS countries")})[
        "nationality"].values
    assert "UA" in value.value.eligible and "UA" not in value.value.held


def test_international_students_from_a_group_are_unchanged():
    s = _section("International students from CIS countries may apply.")
    p1 = _key(s, "places", "CIS countries")
    [value] = _parse(s, {f"eligible_{p1}": ("yes", "CIS countries"),
                         "internationals": ("yes", "International students")})["nationality"].values
    assert len(value.value.eligible) == 9 and value.value.held == {"UA"}


def _card(fields):
    from apps.research.card_funding.card import award_card

    return award_card("A", None, fields)


def test_a_country_named_eligible_and_excluded_through_a_group_is_held_for_it_only():
    """Ruling F-I1: the page names Azerbaijan outright and excludes the CIS, which certainly
    holds it. Held for AZ alone, never told "not eligible"; everyone else still sees the award.
    (Georgia keeps a named country shown: with none left the whole field holds, Task 8 B.)"""
    from apps.research.card_funding.card import Hold

    s = _section("Open to Azerbaijan, Georgia and developing countries, except CIS countries.")
    keys = {f.value.text: k for k, f in find_all(s.lines).places.items()}
    fields = _parse(s, {f"eligible_{keys['Azerbaijan']}": ("yes", "Open to Azerbaijan"),
                        f"eligible_{keys['Georgia']}": ("yes", "Georgia"),
                        f"excluded_{keys['CIS countries']}": ("yes", "except CIS countries")})
    [value] = fields["nationality"].values
    assert value.value.conflicting == {"AZ"} and value.value.eligible == {"GE"}
    assert "AZ" not in value.value.eligible | value.value.excluded | value.value.held
    assert "KZ" in value.value.excluded and "UA" in value.value.held
    card = _card(fields)
    assert card.fields["nationality"].state == "shown"
    assert Hold("conflicting_values", "nationality", "", frozenset({"AZ"})) in card.holds


def test_a_country_named_eligible_on_one_line_and_excluded_on_another_holds_the_field():
    """The two-line probe of Task 8 B: AZ was the only country named eligible, so nothing is
    left to show and the whole field holds (it used to read as open to everyone)."""
    s = _section("Citizens of Azerbaijan may apply.", "Citizens of Azerbaijan are excluded.")
    p1, p2 = sorted(find_all(s.lines).places)
    fields = _parse(s, {f"eligible_{p1}": ("yes", "Citizens of Azerbaijan may apply"),
                        f"excluded_{p2}": ("yes", "Citizens of Azerbaijan are excluded")})
    assert (fields["nationality"].problem, fields["nationality"].detail) == (
        "conflicting_values", "nationality")


def test_a_benefit_limited_to_a_group_is_limited_to_its_countries():
    """Ruling F-I2a: a group on a benefit is its countries at the page's date (its held members
    beside them, Task 8 A), never the string "CIS"; "international students" is no limit; a
    group that holds everyone holds the field."""
    s = _section("AZN 500 per month for applicants from CIS countries")
    m1, p1 = _key(s, "amounts", "AZN 500"), _key(s, "places", "CIS countries")
    [benefit] = _parse(s, {f"pays_{m1}": ("paid_to_student", "AZN 500"),
                           f"for_{p1}_{m1}": ("yes", "CIS countries")})["benefits"].values
    assert {"AZ", "KZ"} <= set(benefit.value.places) and "CIS" not in benefit.value.places
    assert benefit.value.held_places == {"UA"}  # an uncertain member is held (Task 8 A)
    assert "GE" not in benefit.value.places
    s = _section("AZN 500 per month for international students")
    m1, p1 = _key(s, "amounts", "AZN 500"), _key(s, "places", "international students")
    [benefit] = _parse(s, {f"pays_{m1}": ("paid_to_student", "AZN 500"),
                           f"for_{p1}_{m1}": ("yes", "international students")})["benefits"].values
    assert benefit.value.places == ()
    s = _section("AZN 500 per month for students from the Global South")
    m1, p1 = _key(s, "amounts", "AZN 500"), _key(s, "places", "Global South")
    fields = _parse(s, {f"pays_{m1}": ("paid_to_student", "AZN 500"),
                        f"for_{p1}_{m1}": ("yes", "Global South")})
    assert (fields["benefits"].problem, fields["benefits"].detail) == (
        "held_country_group", "GLOBAL_SOUTH")


def test_m_a_group_deadline_and_a_country_deadline_conflict_for_that_country():
    """Probe M: (CIS) 1 May beside (AZ) 9 May, one year. An AZ student would see two
    deadlines; the CIS is expanded in parse, so the per-country check holds AZ."""
    s = _section("Deadline for citizens of CIS countries: 1 May 2027.",
                 "Deadline for citizens of Azerbaijan: 9 May 2027.")
    d1, d2 = _key(s, "dates", "1 May 2027"), _key(s, "dates", "9 May 2027")
    p1, p2 = _key(s, "places", "CIS countries"), _key(s, "places", "Azerbaijan")
    fields = _parse(s, {f"role_{d1}": ("application_deadline", "1 May 2027"),
                        f"role_{d2}": ("application_deadline", "9 May 2027"),
                        f"for_{p1}_{d1}": ("yes", "CIS countries"),
                        f"for_{p2}_{d2}": ("yes", "Azerbaijan")})
    dates = _card(fields).fields["dates"]
    assert (dates.state, dates.hold, dates.detail) == (
        "held", "conflicting_values", "application_deadline:AZ")


def test_f2_a_stale_country_deadline_beside_a_current_general_one_holds():
    """Probe F2, through parse: AZ's 1 May 2024 (no cycle: its year is 2024) beside the general
    9 May 2027 of the 2027/28 intake. Both used to be shown."""
    s = _section("Deadline for citizens of Azerbaijan: 1 May 2024.",
                 "Deadline for all other applicants: 9 May 2027 (2027/28 intake).")
    d1, d2 = _key(s, "dates", "1 May 2024"), _key(s, "dates", "9 May 2027")
    p1 = _key(s, "places", "Azerbaijan")
    fields = _parse(s, {f"role_{d1}": ("application_deadline", "1 May 2024"),
                        f"role_{d2}": ("application_deadline", "9 May 2027"),
                        f"for_{p1}_{d1}": ("yes", "Azerbaijan")})
    dates = _card(fields).fields["dates"]
    assert (dates.state, dates.hold, dates.detail) == (
        "held", "conflicting_values", "application_deadline:AZ")


def test_r_a_later_date_is_held_not_dropped_beside_a_relative_only_newest_cycle():
    """Probe R, through parse: the 2027/28 intake states only "2 weeks before the programme
    starts"; the absolute 1 May 2027 used to vanish in silence."""
    s = _section("For the 2027/28 intake, apply 2 weeks before the programme starts.",
                 "Apply by 1 May 2027.")
    d1 = _key(s, "dates", "1 May 2027")
    r1 = _key(s, "relative_dates", "2 weeks before the programme starts")
    fields = _parse(s, {f"role_{r1}": ("application_deadline", "2 weeks before"),
                        f"role_{d1}": ("application_deadline", "Apply by 1 May 2027.")})
    dates = _card(fields).fields["dates"]
    assert (dates.state, dates.hold) == ("held", "conflicting_values")


def test_an_estimate_or_a_budget_is_an_agreed_non_benefit_not_a_hold():
    """Ruling F-I3: the readers agreed "living costs approx. EUR 934" is not a benefit, so
    benefits and fees are not stated, and the award is not hidden from every student."""
    s = _section("Living costs are approx. EUR 934 per month.")
    m1 = _key(s, "amounts", "EUR 934")
    for pays in ("cost_estimate", "total_budget_or_count"):
        fields = _parse(s, {f"pays_{m1}": (pays, "Living costs are approx. EUR 934")})
        assert (fields["benefits"].problem, fields["benefits"].values) == ("", ()), pays
        assert (fields["fees"].problem, fields["fees"].values) == ("", ()), pays
        card = _card(fields)
        assert card.fields["benefits"].state == card.fields["fees"].state == "not_stated"


def test_fees_are_never_held_along_with_benefits():
    """Ruling F-I3: a benefit's own problem, or money nobody could place, holds benefits only."""
    s = _section("Monthly stipend of AZN 300", "Application fee: AZN 20")
    m1, m2 = _key(s, "amounts", "AZN 300"), _key(s, "amounts", "AZN 20")
    fields = _parse(s, {f"pays_{m1}": ("paid_to_student", "Monthly stipend of AZN 300"),
                        f"pays_{m2}": ("application_fee", "Application fee"),
                        f"frequency_{m2}": ("one_off", "Application fee")},
                    unresolved={f"frequency_{m1}"})
    assert fields["benefits"].problem == "unresolved_split"
    [fee] = fields["fees"].values
    assert fee.value.pays == "application_fee"
    s = _section("Monthly stipend of AZN 300")
    m1 = _key(s, "amounts", "AZN 300")
    fields = _parse(s, {f"pays_{m1}": ("other", "")})
    assert fields["benefits"].problem == "unparseable_value"
    assert (fields["fees"].problem, fields["fees"].values) == ("", ())


def test_a_country_deadline_earlier_in_the_same_year_is_still_shown():
    """Decision 13 stands under F-I2: the same year on different days, place against general."""
    s = _section("Citizens of Azerbaijan: 1 March 2027; others: 1 May 2027.")
    d1, d2 = _key(s, "dates", "1 March 2027"), _key(s, "dates", "1 May 2027")
    p1 = _key(s, "places", "Azerbaijan")
    fields = _parse(s, {f"role_{d1}": ("application_deadline", "1 March 2027"),
                        f"role_{d2}": ("application_deadline", "1 May 2027"),
                        f"for_{p1}_{d1}": ("yes", "Citizens of Azerbaijan")})
    dates = _card(fields).fields["dates"]
    assert dates.state == "shown" and {v.value.places for v in dates.values} == {("AZ",), ()}


def test_a_groups_uncertain_members_are_held_on_an_amount_never_shown_it():
    """Task 8 A (residual I-B): "developing countries" with no DAC mention makes AZ only a
    held member, so AZ is held on the benefit and never shown AZN 500; with the page's own
    "(DAC list)" KE is a certain member and still sees it."""
    from apps.research.card_funding.card import Hold

    s = _section("AZN 500 per month for students from developing countries")
    m1, p1 = _key(s, "amounts", "AZN 500"), _key(s, "places", "developing countries")
    fields = _parse(s, {f"pays_{m1}": ("paid_to_student", "AZN 500"),
                        f"for_{p1}_{m1}": ("yes", "developing countries")})
    [benefit] = fields["benefits"].values
    assert "AZ" not in benefit.value.places and "AZ" in benefit.value.held_places
    assert benefit.value.held_groups == ("DEVELOPING",)
    card = _card(fields)
    assert card.fields["benefits"].state == "shown"
    [hold] = [h for h in card.holds if h.field == "benefits"]
    assert (hold.reason, hold.detail) == ("held_country_group", "DEVELOPING")
    assert hold.countries == benefit.value.held_places and "AZ" in hold.countries
    assert Hold("held_country_group", "benefits", "DEVELOPING", hold.countries) in card.holds

    s = _section("AZN 500 per month for students from developing countries (DAC list)")
    m1, p1 = _key(s, "amounts", "AZN 500"), _key(s, "places", "developing countries")
    fields = _parse(s, {f"pays_{m1}": ("paid_to_student", "AZN 500"),
                        f"for_{p1}_{m1}": ("yes", "developing countries")})
    [benefit] = fields["benefits"].values
    assert "KE" in benefit.value.places and "KE" not in benefit.value.held_places
    assert not [h for h in _card(fields).holds if "KE" in h.countries]


def test_a_groups_uncertain_members_are_held_on_a_date_and_others_still_see_theirs():
    """Task 8 A: UA is only held for the CIS, so a UA student is held on the dates, never shown
    1 May; GE, outside the CIS, still sees the general 1 June."""
    s = _section("Deadline for citizens of CIS countries: 1 May 2027; others: 1 June 2027.")
    d1, d2 = _key(s, "dates", "1 May 2027"), _key(s, "dates", "1 June 2027")
    p1 = _key(s, "places", "CIS countries")
    fields = _parse(s, {f"role_{d1}": ("application_deadline", "1 May 2027"),
                        f"role_{d2}": ("application_deadline", "1 June 2027"),
                        f"for_{p1}_{d1}": ("yes", "citizens of CIS countries")})
    cis = next(v.value for v in fields["dates"].values if v.value.date.month == 5)
    assert "UA" not in cis.places and cis.held_places == {"UA"} and "AZ" in cis.places
    card = _card(fields)
    dates = card.fields["dates"]
    assert dates.state == "shown"
    [hold] = [h for h in card.holds if h.field == "dates"]
    assert (hold.reason, hold.detail, hold.countries) == (
        "held_country_group", "CIS", frozenset({"UA"}))
    general = [v.value for v in dates.values if not v.value.places and not v.value.held_places]
    assert [(d.date.day, d.date.month) for d in general] == [(1, 6)]  # GE's deadline
    assert all("GE" not in {*v.value.places, *v.value.held_places} for v in dates.values)


def test_a_held_member_of_one_date_group_never_conflicts_as_a_member():
    """Task 8 A: the per-country deadline check counts a group's held countries as held, never
    as members. UA is named outright on 9 May and only held for the CIS's 1 May: no conflict for
    UA (the CIS hold already holds UA's dates)."""
    s = _section("Deadline for citizens of CIS countries: 1 May 2027.",
                 "Deadline for citizens of Ukraine: 9 May 2027.")
    d1, d2 = _key(s, "dates", "1 May 2027"), _key(s, "dates", "9 May 2027")
    p1, p2 = _key(s, "places", "CIS countries"), _key(s, "places", "Ukraine")
    fields = _parse(s, {f"role_{d1}": ("application_deadline", "1 May 2027"),
                        f"role_{d2}": ("application_deadline", "9 May 2027"),
                        f"for_{p1}_{d1}": ("yes", "CIS countries"),
                        f"for_{p2}_{d2}": ("yes", "Ukraine")})
    card = _card(fields)
    assert card.fields["dates"].state == "shown"
    assert any(h.field == "dates" and h.countries == {"UA"} for h in card.holds)


def test_a_nationality_list_wholly_contradicted_holds_the_whole_field():
    """Task 8 B (residual I-A): every country the page names eligible is also excluded, so
    nothing is left to show and the field would read as open to everyone. Held whole."""
    s = _section("Open to citizens of Azerbaijan, except CIS countries.")
    az, cis = _key(s, "places", "Azerbaijan"), _key(s, "places", "CIS countries")
    fields = _parse(s, {f"eligible_{az}": ("yes", "Open to citizens of Azerbaijan"),
                        f"excluded_{cis}": ("yes", "except CIS countries")})
    assert (fields["nationality"].problem, fields["nationality"].detail) == (
        "conflicting_values", "nationality")
    assert _card(fields).fields["nationality"].state == "held"


def test_a_nationality_list_with_a_country_left_holds_only_the_contradicted_one():
    from apps.research.card_funding.card import Hold

    s = _section("Open to Azerbaijan and Georgia, except CIS countries.")
    keys = {f.value.text: k for k, f in find_all(s.lines).places.items()}
    fields = _parse(s, {f"eligible_{keys['Azerbaijan']}": ("yes", "Open to Azerbaijan"),
                        f"eligible_{keys['Georgia']}": ("yes", "Georgia"),
                        f"excluded_{keys['CIS countries']}": ("yes", "except CIS countries")})
    [value] = fields["nationality"].values
    assert value.value.eligible == {"GE"} and value.value.conflicting == {"AZ"}
    card = _card(fields)
    assert card.fields["nationality"].state == "shown"
    assert Hold("conflicting_values", "nationality", "", frozenset({"AZ"})) in card.holds


def test_a_fee_limited_to_a_group_holds_its_uncertain_members_too():
    """Task 8 fix round 1: fees are Benefit values built through `_scope`, so a group's held
    members on a fee are held on the card exactly as on benefits and dates."""
    from apps.research.card_funding.card import Hold

    s = _section("Application fee: AZN 50 for students from developing countries")
    m1, p1 = _key(s, "amounts", "AZN 50"), _key(s, "places", "developing countries")
    fields = _parse(s, {f"pays_{m1}": ("application_fee", "Application fee"),
                        f"for_{p1}_{m1}": ("yes", "developing countries")})
    [fee] = fields["fees"].values
    assert fee.value.places == () and "AZ" in fee.value.held_places
    card = _card(fields)
    assert card.fields["fees"].state == "shown"
    assert Hold("held_country_group", "fees", "DEVELOPING", fee.value.held_places) in card.holds


def test_an_uncertain_only_date_group_stays_limited_beside_a_general_date():
    """Pins the slice-3 contract: a date whose group has no certain member keeps
    `places == ()` with its `held_places`, and the card holds those countries on dates -- it is
    a limited date, never read as the general one."""
    from apps.research.card_funding.card import Hold

    s = _section("Deadline for students from developing countries: 1 May 2027; "
                 "others: 1 June 2027")
    d1, d2 = _key(s, "dates", "1 May 2027"), _key(s, "dates", "1 June 2027")
    p1 = _key(s, "places", "developing countries")
    fields = _parse(s, {f"role_{d1}": ("application_deadline", "1 May 2027"),
                        f"role_{d2}": ("application_deadline", "1 June 2027"),
                        f"for_{p1}_{d1}": ("yes", "developing countries")})
    by_month = {v.value.date.month: v.value for v in fields["dates"].values}
    may, june = by_month[5], by_month[6]
    assert may.places == () and "AZ" in may.held_places and may.held_groups == ("DEVELOPING",)
    assert june.places == () and june.held_places == frozenset()
    card = _card(fields)
    assert card.fields["dates"].state == "shown" and len(card.fields["dates"].values) == 2
    assert Hold("held_country_group", "dates", "DEVELOPING", may.held_places) in card.holds


def test_international_students_carry_the_all_but_the_host_fallback_for_the_hunt():
    """Definitions v3: "international students" is no list, so it is hunted; the value the hunt
    shows if it finds none -- every country but the host, minus the page's own exclusions -- is
    carried beside the hold, never shown by 2b."""
    s = _section("International students may apply, except citizens of Russia.")
    p1 = _key(s, "places", "Russia")
    fields = _parse(s, {"internationals": ("yes", "International students may apply"),
                        f"excluded_{p1}": ("yes", "except citizens of Russia")},
                    funder_country="HU")
    nationality = fields["nationality"]
    assert (nationality.problem, nationality.detail) == ("needs_hunt", "internationals")
    [fallback] = nationality.values
    assert fallback.value.eligible == set() and fallback.value.excluded == {"HU", "RU"}
    assert fallback.quote.text == "International students may apply"
    unknown = _parse(s, {"internationals": ("yes", "International students may apply")})
    assert unknown["nationality"].values == ()  # no host known: nothing to fall back to
    s = _section("See the list of eligible countries.")
    elsewhere = _parse(s, {"eligibility_elsewhere": ("yes", "See the list of eligible countries")},
                       funder_country="HU")
    assert elsewhere["nationality"].values == ()  # the page says a list exists: never assumed


def test_named_countries_beside_internationals_get_no_fallback():
    s = _section("International students from Kazakhstan or Georgia may apply.")
    keys = [_key(s, "places", t) for t in ("Kazakhstan", "Georgia")]
    answers = {f"eligible_{k}": ("yes", "Kazakhstan") for k in keys}
    answers["internationals"] = ("yes", "International students")
    nationality = _parse(s, answers, funder_country="HU")["nationality"]
    assert nationality.problem == "" and nationality.values[0].value.eligible == {"KZ", "GE"}


def test_a_sections_stated_cycle_is_its_newest_intake_label():
    from apps.research.card_funding.parse import stated_cycle

    assert stated_cycle(find_all(_section("Call for applications 2026/27").lines)) == 2026
    assert stated_cycle(find_all(_section("Academic year 2025-2026",
                                          "Call for applications 2026/27").lines)) == 2026
    assert stated_cycle(find_all(_section("Apply by 15 January 2027.").lines)) is None


def test_a_contradicted_country_is_held_by_the_fallback_never_made_eligible():
    s = _section("International students may apply, except citizens of Russia.")
    p1 = _key(s, "places", "Russia")
    n = _parse(s, {"internationals": ("yes", "International students may apply"),
                   f"eligible_{p1}": ("yes", "Russia"),
                   f"excluded_{p1}": ("yes", "except citizens of Russia")},
               funder_country="HU")["nationality"]
    [fallback] = n.values
    assert "RU" in fallback.value.held and "RU" not in fallback.value.excluded
    assert fallback.value.eligible == set()
    assert fallback.quote.text == "International students may apply"


def test_the_fallback_quote_survives_a_hunt_started_by_an_international_place():
    s = _section("Scholarships for international students.")
    p1 = _key(s, "places", "international students")
    n = _parse(s, {f"eligible_{p1}": ("yes", "for international students")},
               funder_country="HU")["nationality"]
    assert n.problem == "needs_hunt" and n.values  # the hunt came from the place, not the question
    assert n.values[0].quote is not None
    assert n.values[0].value.groups[-1] == "INTERNATIONAL"


def test_an_excluded_group_is_carried_by_the_fallback_with_its_uncertain_members_held():
    s = _section("International students may apply, except CIS countries.")
    p1 = _key(s, "places", "CIS countries")
    n = _parse(s, {"internationals": ("yes", "International students may apply"),
                   f"excluded_{p1}": ("yes", "except CIS countries")},
               funder_country="HU")["nationality"]
    value = n.values[0].value
    assert "AZ" in value.excluded and "UA" in value.held and "UA" not in value.excluded
    assert value.groups == ("CIS", "INTERNATIONAL")


def test_internationals_beside_a_group_of_only_uncertain_members_get_no_fallback():
    s = _section("International students from developing countries may apply.")
    p1 = _key(s, "places", "developing countries")
    n = _parse(s, {"internationals": ("yes", "International students"),
                   f"eligible_{p1}": ("yes", "developing countries")},
               funder_country="HU")["nationality"]
    # held members, no eligible ones: no hunt starts, so no fallback is built either
    assert n.problem == "" and "INTERNATIONAL" not in n.values[0].value.groups


def test_a_contradicted_group_builds_no_fallback():
    s = _section("International students may apply, except CIS countries.")
    p1 = _key(s, "places", "CIS countries")
    n = _parse(s, {"internationals": ("yes", "International students may apply"),
                   f"eligible_{p1}": ("yes", "CIS countries"),
                   f"excluded_{p1}": ("yes", "except CIS countries")},
               funder_country="HU")["nationality"]
    assert (n.problem, n.values) == ("needs_hunt", ())


def test_excluded_international_students_build_no_fallback():
    s = _section("Not open to international students.")
    p1 = _key(s, "places", "international students")
    n = _parse(s, {"internationals": ("yes", "international students"),
                   f"excluded_{p1}": ("yes", "Not open to international students")},
               funder_country="HU")["nationality"]
    assert (n.problem, n.values) == ("needs_hunt", ())


def test_excluded_international_students_hold_nationality_whatever_internationals_says():
    s = _section("Not open to international students.")
    p1 = _key(s, "places", "international students")
    n = _parse(s, {"internationals": ("no", ""),
                   f"excluded_{p1}": ("yes", "Not open to international students")},
               funder_country="HU")["nationality"]
    assert (n.problem, n.values) == ("needs_hunt", ())
