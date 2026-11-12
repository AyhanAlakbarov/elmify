import datetime as dt

from apps.research.candidates import Date, RelativeDate
from apps.research.card_engine import Quote
from apps.research.card_funding.awards import PAGE_WORDS_FILE, fold, nameable, names_award
from apps.research.card_funding.card import award_card, unread_award
from apps.research.card_funding.hunt import _ahead, merge, wanted
from apps.research.card_funding.parse import AwardDate, Condition, Nationality, Parsed, Value

URL = "https://example.edu.az/scholarships"
TODAY = dt.date(2026, 10, 14)


def _date(role, year, month, day):
    date = Date(f"{day}.{month}.{year}", 0, 10, year, month, day)
    return Value(AwardDate(role, date, True, ()), Quote(date.text, "L1.text"), URL, ())


def _label(value):
    return Parsed((Value(value, Quote(value, "L2.text"), URL, ()),))


def test_the_hunt_looks_for_pointers_splits_missing_facts_and_a_passed_deadline():
    card = award_card("A", None, {
        "nationality": Parsed(problem="needs_hunt", detail="eligibility_elsewhere"),
        "holder_kind": Parsed(problem="unresolved_split", detail="holder_kind"),
        "fees": Parsed(problem="unparseable_value", detail="m1"),  # a wording fix, not a hunt
        "dates": Parsed((_date("application_deadline", 2026, 1, 15),)),  # last cycle's
    })
    # target_level and benefits are not stated: code found nothing, so they are looked for
    assert wanted(card, TODAY) == {"nationality", "holder_kind", "dates", "target_level",
                                   "benefits"}
    ahead = award_card("A", None, {"dates": Parsed((_date("application_deadline", 2027, 1, 15),)),
                                   "target_level": _label("master"),
                                   "nationality": Parsed(problem="held_country_group",
                                                         detail="GLOBAL_SOUTH"),
                                   "benefits": Parsed(problem="page_budget")})
    assert wanted(ahead, TODAY) == set()


def test_an_award_given_on_admission_is_not_hunted_for_a_date():
    card = award_card("A", None, {"route": _label("automatic_on_admission"),
                                  "target_level": _label("master"),
                                  "benefits": Parsed(problem="page_budget"),
                                  "nationality": Parsed((Value(Nationality(
                                      frozenset({"AZ"}), frozenset(), frozenset(), "citizenship",
                                      ()), None, URL, ()),))})
    assert wanted(card, TODAY) == set()


def test_a_page_attaches_only_when_it_names_the_same_award_by_code():
    assert names_award("TÜRKİYE BURSLARI 2026 Başvuru Takvimi", "Türkiye Bursları")
    assert names_award("How to apply for the Stipendium Hungaricum", "Stipendium Hungaricum")
    # the Bolashak trap (§5.5 step 4): a different scheme's window on the same site
    assert not names_award("Стипендиальная программа для обучения в вузах Казахстана",
                           "Международная стипендия «Болашак»")
    assert names_award("Стипендия «Болашак» — сроки приёма", "Стипендия Болашак")
    assert not names_award("Hungaricumfoo", "Hungaricum")  # whole words only


def test_a_name_made_only_of_generic_words_never_attaches():
    assert not nameable("Scholarships") and not nameable("Master's Scholarship 2026")
    assert not names_award("Merit Scholarships", "Scholarships")
    assert nameable("Rector's Scholarship") and nameable("DAAD")


def test_a_heading_that_adds_a_word_names_another_award():
    for name, heading in (
            ("Stipendium Hungaricum", "Stipendium Hungaricum Dissertation Scholarship - call"),
            ("Türkiye Bursları", "Türkiye Bursları Research Scholarships"),
            ("Rector's Scholarship", "Vice-Rector's Scholarship"),
            ("Chevening", "Chevening Fellowships - apply"),
            ("Erasmus+", "Erasmus Mundus Joint Masters"),
            ("Merit Scholarship", "International Merit Scholarship"),
            ("Excellence Scholarship", "Excellence Scholarship for PhD"),
            ("DAAD", "DAAD Helmut-Schmidt-Programme | DAAD")):
        assert not names_award(heading, name), heading
    assert nameable("DAAD")
    assert names_award("Stipendium Hungaricum \u2013 call for applications 2026/27",
                       "Stipendium Hungaricum")
    assert names_award("How to apply: Chevening Scholarship", "Chevening")
    assert names_award("Turkiye Burslari 2026", "Türkiye Bursları")


def test_names_in_other_languages_are_generic_and_other_scripts_stay_whole():
    for generic in ("장학금", "奨学金", "Стипендию", "奖学金", "Bolsas", "Stypendium"):
        assert not nameable(generic), generic
    assert not names_award("Graduate Tuition Fee Waiver", "Tuition Fee Waiver")
    assert fold("राष्ट्रीय छात्रवृत्ति") == "राष्ट्रीय छात्रवृत्ति"
    assert fold("ทุนรัฐบาล") == "ทุนรัฐบาล"
    assert names_award("राष्ट्रीय छात्रवृत्ति 2026", "राष्ट्रीय छात्रवृत्ति")
    assert names_award("ทุนรัฐบาลไทย", "ทุนรัฐบาลไทย")
    assert not names_award("ทุนรัฐบาลไทย", "ทุนรัฐบาล")  # whole words only
    assert fold("Türkiye") == "turkiye"


def test_a_date_with_no_year_is_passed_and_a_relative_date_is_ahead():
    undated = Value(AwardDate("application_deadline", Date("15 Jan", 0, 6, None, 1, 15), True, ()),
                    None, URL, ())
    assert not _ahead(undated, TODAY)
    relative = Value(AwardDate("application_deadline",
                               RelativeDate("3 months", 0, 8, 3, 3, "month", "before", "start",
                                            False), True, ()), None, URL, ())
    assert _ahead(relative, TODAY)


HEADINGS = (  # (name, heading) in each round-2 language
    ("Türkiye Bursları", "Türkiye Bursları Başvuru Koşulları"),
    ("Стипендия Болашак", "Стипендия «Болашак» — сроки приёма"),
    ("Stipendium Hungaricum", "Stipendium Hungaricum \u2013 Bewerbung und Fristen"),
    ("Bourse Eiffel", "Bourse Eiffel : calendrier et candidature"),
    ("Beca Fundación Carolina", "Beca Fundación Carolina \u2013 convocatoria 2026"),
    ("Global Korea Scholarship", "Global Korea Scholarship 모집요강"),
    ("MEXT", "MEXT 奨学金 募集要項"),
    ("Prezident təqaüdü", "Prezident təqaüdü \u2014 müraciət qaydaları"),
    ("中国政府奖学金", "中国政府奖学金 申请指南"),
    ("中国政府奖学金", "中国政府奖学金申请指南"),
    ("Bolashak", "Bolashak бағдарламасы \u2014 құжаттарды қабылдау"),
    ("Holland Scholarship", "Holland Scholarship aanmelden"),
    ("Borsa Regione Lazio", "Borsa Regione Lazio bando 2026"),
    ("Chevening", "Chevening Scholarship key dates and timeline"),
)


def test_a_heading_in_each_round_two_language_attaches_and_a_level_word_does_not():
    for name, heading in HEADINGS:
        assert names_award(heading, name), heading
    for name, heading in (("Türkiye Bursları", "Türkiye Bursları Araştırma Bursu"),
                          ("Стипендия Болашак", "Стипендия «Болашак» для научных стажировок"),
                          ("Global Korea Scholarship", "Global Korea Scholarship 학부"),
                          ("Bourse Eiffel", "Bourse Eiffel doctorat")):
        assert not names_award(heading, name), heading


def test_page_words_csv_has_known_languages_and_concepts():
    import csv
    langs = {"en", "de", "fr", "es", "it", "nl", "ko", "ja", "zh", "az", "tr", "ru", "kk"}
    concepts = {"application", "call", "deadline", "dates", "eligibility", "documents", "guide",
                "info", "award", "function"}
    with PAGE_WORDS_FILE.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows and all(r["language"] in langs and r["concept"] in concepts for r in rows)
    assert {r["language"] for r in rows} == langs


def test_multi_word_generic_numbers_and_plus():
    assert not nameable("Học bổng")
    assert not names_award("Chevening H2020", "Chevening")
    assert names_award("Chevening 2026/27", "Chevening")
    assert names_award("2nd Chevening", "Chevening")
    assert not names_award("Erasmus Scholarship", "Erasmus+")
    assert names_award("Erasmus+ Programme", "Erasmus+")


def test_full_width_plus_ambiguous_words_and_cjk_years():
    assert not names_award("Erasmus\uff0b Programme", "Erasmus")
    assert not names_award("エラスムス\uff0b", "エラスムス")
    assert names_award("Erasmus+ Programme", "Erasmus+")
    assert not names_award("Chevening son", "Chevening")
    assert not names_award("Prezident təqaüdü tarix", "Prezident təqaüdü")
    assert names_award("Antr\u00e4ge Stipendium Hungaricum", "Stipendium Hungaricum")
    assert names_award("2026年度 国費外国人留学生 募集要項", "国費外国人留学生")
    assert names_award("Стипендия «Болашак»: требования к кандидатам", "Стипендия Болашак")


def _found(cycle, source, **parsed):
    """One hunted page's restricted card of the award, its values sourced to that page."""
    sourced = {name: Parsed(tuple(Value(v.value, v.quote, source, v.decisions)
                                  for v in p.values), p.problem, p.detail)
               for name, p in parsed.items()}
    return award_card("Merit Award", None, sourced, cycle)


def _nat(*eligible):
    return Parsed((Value(Nationality(frozenset(eligible), frozenset(), frozenset(), "citizenship",
                                     ()), None, URL, ()),))


def test_the_newest_stated_cycle_wins_and_a_dated_page_beats_an_undated_one():
    start = award_card("Merit Award", None, {
        "dates": Parsed((_date("application_deadline", 2026, 1, 15),))})
    new = _date("application_deadline", 2027, 1, 15)
    merged = merge(start, frozenset({"dates", "nationality"}), [
        _found(2027, "https://beu.edu.az/calendar", dates=Parsed((new,))),
        _found(None, "https://beu.edu.az/old", nationality=_nat("AZ", "KZ")),
        _found(2026, "https://edu.gov.az/list", nationality=_nat("AZ")),
    ], TODAY, complete=True)
    [deadline] = merged.fields["dates"].values
    assert (deadline.value.date.year, deadline.source) == (2027, "https://beu.edu.az/calendar")
    assert merged.fields["dates"].label == ""
    [who] = merged.fields["nationality"].values
    assert (who.value.eligible, who.source) == ({"AZ"}, "https://edu.gov.az/list")


def test_pages_that_cannot_be_ordered_go_to_the_hold_queue():
    start = award_card("Merit Award", None, {})
    undated = merge(start, frozenset({"nationality"}), [
        _found(None, "https://a.edu.az/x", nationality=_nat("AZ")),
        _found(None, "https://a.edu.az/y", nationality=_nat("KZ"))], TODAY, complete=True)
    assert (undated.fields["nationality"].hold, undated.fields["nationality"].detail) == (
        "conflicting_values", "hunt:nationality")
    same = merge(start, frozenset({"nationality"}), [
        _found(2026, "https://a.edu.az/x", nationality=_nat("AZ")),
        _found(2026, "https://a.edu.az/y", nationality=_nat("KZ"))], TODAY, complete=True)
    assert same.fields["nationality"].hold == "conflicting_values"
    agree = merge(start, frozenset({"nationality"}), [
        _found(None, "https://a.edu.az/x", nationality=_nat("AZ")),
        _found(None, "https://a.edu.az/y", nationality=_nat("AZ"))], TODAY, complete=True)
    assert agree.fields["nationality"].state == "shown"
    dates = merge(start, frozenset({"dates"}), [
        _found(None, "https://a.edu.az/x",
               dates=Parsed((_date("application_deadline", 2027, 1, 15),))),
        _found(None, "https://a.edu.az/y",
               dates=Parsed((_date("application_deadline", 2027, 2, 1),)))], TODAY,
        complete=True)
    assert dates.fields["dates"].hold == "conflicting_values"
    assert ("conflicting_values", "dates") in {(h.reason, h.field) for h in dates.holds}


def test_only_last_cycles_date_is_shown_labelled_and_nothing_found_keeps_or_holds():
    start = award_card("Merit Award", None, {
        "dates": Parsed((_date("application_deadline", 2026, 1, 15),)),
        "nationality": Parsed(problem="needs_hunt", detail="eligibility_elsewhere"),
        "holder_kind": Parsed(problem="unresolved_split", detail="holder_kind")})
    merged = merge(start, frozenset({"dates", "nationality", "holder_kind", "target_level"}), [],
                   TODAY, complete=True)
    assert (merged.fields["dates"].state, merged.fields["dates"].label) == ("shown", "last_cycle")
    assert (merged.fields["nationality"].hold, merged.fields["nationality"].detail) == (
        "hunt_not_found", "eligibility_elsewhere")
    assert merged.fields["holder_kind"].hold == "unresolved_split"  # the operator's, as it was
    assert merged.fields["target_level"].state == "not_stated"  # code found it nowhere
    assert ("hunt_not_found", "nationality") in {(h.reason, h.field) for h in merged.holds}
    # Ruling P1 / T5 carry: a search that did not run to the end found nothing, it did not
    # search: the pointer stays needs_hunt, never "not found"
    unsearched = merge(start, frozenset({"nationality"}), [], TODAY, complete=False)
    assert unsearched.fields["nationality"] == start.fields["nationality"]


FALLBACK = Value(Nationality(frozenset(), frozenset({"HU"}), frozenset(), "not_stated",
                             ("INTERNATIONAL",)), None, URL, ())


def test_every_country_but_the_host_is_shown_only_after_a_clean_page_gave_no_list():
    """Ruling P1: the fallback is shown only when a hunted page that named the award was read
    cleanly and still gave no list, and the search ran to the end; otherwise it stays held."""
    start = award_card("Merit Award", None, {
        "nationality": Parsed((FALLBACK,), "needs_hunt", "internationals")})
    hunted = frozenset({"nationality"})
    no_list = _found(2027, "https://a.edu.az/merit", target_level=_label("master"))
    merged = merge(start, hunted, [no_list], TODAY, complete=True)
    assert (merged.fields["nationality"].state, merged.fields["nationality"].values) == (
        "shown", (FALLBACK,))
    assert merged.holds == ()
    # no page named the award: nothing was read, so nothing says there is no list
    nowhere = merge(start, hunted, [], TODAY, complete=True).fields["nationality"]
    assert (nowhere.state, nowhere.hold, nowhere.detail) == (
        "held", "hunt_not_found", "internationals")
    # a stage failed, a domain was left unproven or a lead could not be fetched: not searched
    failed = merge(start, hunted, [no_list], TODAY, complete=False).fields["nationality"]
    assert (failed.state, failed.hold) == ("held", "needs_hunt")
    # a page that named the award was cut by its deadline: its list may be in what was not read
    cut = unread_award("Merit Award", None, "deadline")
    for found in ([cut], [no_list, cut]):
        held = merge(start, hunted, found, TODAY, complete=True).fields["nationality"]
        assert (held.state, held.hold) == ("held", "needs_hunt"), found
    # a page that points to a list elsewhere says a list exists
    pointer = _found(2027, "https://a.edu.az/merit",
                     nationality=Parsed(problem="needs_hunt", detail="eligibility_elsewhere"))
    held = merge(start, hunted, [pointer], TODAY, complete=True).fields["nationality"]
    assert (held.state, held.hold) == ("held", "hunt_not_found")
    # a page with a list code could not read is a list, never "no list"
    unreadable = _found(2027, "https://a.edu.az/merit",
                        nationality=Parsed(problem="unparseable_value", detail="p1"))
    held = merge(start, hunted, [unreadable], TODAY, complete=True).fields["nationality"]
    assert (held.state, held.hold, held.detail) == ("held", "unparseable_value", "p1")


def test_a_hunted_page_never_touches_a_field_that_was_not_hunted():
    start = award_card("Merit Award", None, {"target_level": _label("master")})
    merged = merge(start, frozenset({"dates"}), [
        _found(2027, "https://a.edu.az/x", target_level=_label("phd"))], TODAY, complete=True)
    assert merged.fields["target_level"] == start.fields["target_level"]


def test_a_date_is_shown_as_its_page_printed_it():
    new = _date("application_deadline", 2027, 1, 15)
    merged = merge(award_card("Merit Award", None, {}), frozenset({"dates"}),
                   [_found(2027, URL, dates=Parsed((new,)))], TODAY, complete=True)
    assert merged.fields["dates"].values == (new,) and new.value.cycle is None


def test_a_value_found_only_on_an_older_cycles_page_is_labelled_last_cycle():
    """Owner, 2026-10-14: amounts, benefits and eligibility rules are labelled as dates are."""
    start = award_card("Merit Award", None, {}, cycle=2027)
    merged = merge(start, frozenset({"nationality", "target_level"}), [
        _found(2026, "https://a.edu.az/2026", nationality=_nat("AZ")),
        _found(None, "https://a.edu.az/x", target_level=_label("master"))], TODAY,
        complete=True)
    assert (merged.fields["nationality"].state, merged.fields["nationality"].label) == (
        "shown", "last_cycle")  # the start page states 2027; this list is 2026's
    assert merged.fields["target_level"].label == ""  # an undated page has no cycle to place
    current = merge(start, frozenset({"nationality"}), [
        _found(2027, "https://a.edu.az/2027", nationality=_nat("AZ"))], TODAY, complete=True)
    assert current.fields["nationality"].label == ""
    passed = award_card("Merit Award", None, {
        "dates": Parsed((_date("application_deadline", 2026, 1, 15),))})
    merged = merge(passed, frozenset({"dates", "nationality"}), [
        _found(2026, "https://a.edu.az/2026", nationality=_nat("AZ"))], TODAY, complete=True)
    # every application date has passed, and the list is that cycle's: both are last cycle's
    assert merged.fields["dates"].label == merged.fields["nationality"].label == "last_cycle"
    ahead = award_card("Merit Award", None, {
        "dates": Parsed((_date("application_deadline", 2027, 1, 15),))})
    merged = merge(ahead, frozenset({"nationality"}), [
        _found(2026, "https://a.edu.az/2026", nationality=_nat("AZ"))], TODAY, complete=True)
    assert merged.fields["nationality"].label == "last_cycle"  # a 2027 deadline is still ahead


def test_a_page_is_never_last_cycle_by_its_own_deadline_still_ahead():
    """A page stating intake 2026/27 whose own deadline (Jan 2027) is still ahead is current."""
    page = _found(2026, "https://a.edu.az/merit", nationality=_nat("AZ"),
                  dates=Parsed((_date("application_deadline", 2027, 1, 15),)))
    merged = merge(award_card("Merit Award", None, {}), frozenset({"dates", "nationality"}),
                   [page], TODAY, complete=True)
    assert merged.fields["dates"].label == merged.fields["nationality"].label == ""


def test_every_date_role_from_an_older_cycles_page_is_last_cycle_or_dropped():
    """Ruling P3a: results and start dates from an older cycle's page are labelled, and never
    shown unlabelled beside this cycle's deadline."""
    start = award_card("Merit Award", None, {}, cycle=2027)
    old = _found(2026, "https://a.edu.az/2026", dates=Parsed((
        _date("results_announced", 2026, 11, 20), _date("programme_start", 2026, 9, 1))))
    only_old = merge(start, frozenset({"dates"}), [old], TODAY, complete=True)
    assert (only_old.fields["dates"].state, only_old.fields["dates"].label) == (
        "shown", "last_cycle")  # Nov 2026 is still ahead, but the page is 2026's, not 2027's
    new = _date("application_deadline", 2027, 1, 15)
    both = merge(award_card("Merit Award", None, {}), frozenset({"dates"}), [
        _found(2027, "https://a.edu.az/2027", dates=Parsed((new,))),
        _found(None, "https://a.edu.az/old", dates=Parsed((
            _date("results_announced", 2026, 5, 1), _date("programme_start", 2026, 9, 1))))],
        TODAY, complete=True)
    assert both.fields["dates"].values == (_found(2027, "https://a.edu.az/2027", dates=Parsed(
        (new,))).fields["dates"].values) and both.fields["dates"].label == ""


def test_an_older_pages_date_later_than_the_kept_one_is_held_never_dropped():
    merged = merge(award_card("Merit Award", None, {}, cycle=2027), frozenset({"dates"}), [
        _found(2027, "https://a.edu.az/2027",
               dates=Parsed((_date("application_deadline", 2027, 1, 15),))),
        _found(2026, "https://a.edu.az/2026",
               dates=Parsed((_date("application_deadline", 2027, 3, 1),)))],
        TODAY, complete=True)
    assert (merged.fields["dates"].hold, merged.fields["dates"].detail) == (
        "conflicting_values", "hunt:application_deadline")


def test_two_sections_of_one_page_naming_the_award_are_one_page():
    """T4 carry: a page with two headings naming the award gives two cards; they combine."""
    src = "https://a.edu.az/merit"
    who = _found(2027, src, nationality=_nat("AZ"), requirements=_label(Condition("cv", None)))
    when = _found(None, src, dates=Parsed((_date("application_deadline", 2027, 1, 15),)),
                  requirements=Parsed((Value(Condition("cv", None), None, URL, ()),
                                       Value(Condition("transcript", None), None, URL, ()))))
    hunted = frozenset({"dates", "nationality", "requirements"})
    merged = merge(award_card("Merit Award", None, {}), hunted, [who, when], TODAY,
                   complete=True)
    assert {f: merged.fields[f].state for f in hunted} == dict.fromkeys(hunted, "shown")
    assert [v.value.kind for v in merged.fields["requirements"].values] == [
        "cv", "transcript"]  # a list field: both sections' items, each once
    # the page's two sections disagree on a one-value field: the page contradicts itself
    other = _found(None, src, nationality=_nat("KZ"))
    held = merge(award_card("Merit Award", None, {}), frozenset({"nationality"}), [who, other],
                 TODAY, complete=True).fields["nationality"]
    assert (held.hold, held.detail) == ("conflicting_values", "hunt:nationality")
    # and a newer page still beats the combined older one
    newer = _found(2028, "https://a.edu.az/2028", nationality=_nat("GE"))
    shown = merge(award_card("Merit Award", None, {}), frozenset({"nationality"}),
                  [who, other, newer], TODAY, complete=True).fields["nationality"]
    assert shown.values[0].value.eligible == {"GE"}


def _held(field):
    return field.state, field.hold, field.detail


def test_current_pages_that_disagree_are_held_whatever_their_calendar_years():
    """T6 I1: a calendar year is not a cycle. Two deadlines still ahead disagree -- same intake
    or none stated -- and a page's own conflict is never released by the merge."""
    dec = _date("application_deadline", 2026, 12, 15)
    jan = _date("application_deadline", 2027, 1, 15)
    for cycle in (None, 2027):  # probes 2c and 2d
        merged = merge(award_card("Merit Award", None, {}), frozenset({"dates"}), [
            _found(cycle, "https://a.edu.az/dec", dates=Parsed((dec,))),
            _found(cycle, "https://a.edu.az/jan", dates=Parsed((jan,)))], TODAY, complete=True)
        assert _held(merged.fields["dates"]) == (
            "held", "conflicting_values", "hunt:application_deadline"), cycle
    own = Parsed((dec, _date("application_deadline", 2027, 1, 31)))  # probe S2
    assert award_card("Merit Award", None, {"dates": own}).fields["dates"].hold == (
        "conflicting_values")  # 2b holds it on its own page
    merged = merge(award_card("Merit Award", None, {}), frozenset({"dates"}),
                   [_found(None, "https://a.edu.az/p", dates=own)], TODAY, complete=True)
    assert merged.fields["dates"].hold == "conflicting_values"


def test_a_page_pointing_to_a_list_elsewhere_blocks_the_fallback():
    """T6 I2 (probe 5c): one page gave no list, another says a list exists elsewhere."""
    start = award_card("Merit Award", None, {
        "nationality": Parsed((FALLBACK,), "needs_hunt", "internationals")})
    pointer = _found(2027, "https://a.edu.az/other",
                     nationality=Parsed(problem="needs_hunt", detail="eligibility_elsewhere"))
    no_list = _found(2027, "https://a.edu.az/merit", target_level=_label("master"))
    held = merge(start, frozenset({"nationality"}), [no_list, pointer], TODAY,
                 complete=True).fields["nationality"]
    assert held.state == "held"


def test_a_page_with_no_intake_is_placed_by_its_own_passed_dates():
    """T6 I3 (probe S1): its list is last cycle's, as its deadline is."""
    merged = merge(award_card("Merit Award", None, {}), frozenset({"nationality", "dates"}), [
        _found(None, "https://a.edu.az/old", nationality=_nat("AZ"),
               dates=Parsed((_date("application_deadline", 2026, 1, 15),)))], TODAY,
        complete=True)
    assert merged.fields["dates"].label == "last_cycle"
    assert (merged.fields["nationality"].state, merged.fields["nationality"].label) == (
        "shown", "last_cycle")


def test_each_section_of_a_page_keeps_its_own_intake_for_dates():
    """T6 I4 (probe 6b): a 2025 section's results are not shown as this cycle's."""
    src = "https://a.edu.az/merit"
    new = _date("application_deadline", 2027, 1, 15)
    merged = merge(award_card("Merit Award", None, {}), frozenset({"dates"}), [
        _found(2025, src, dates=Parsed((_date("results_announced", 2025, 5, 1),))),
        _found(2027, src, dates=Parsed((new,)))], TODAY, complete=True)
    assert [v.value.role for v in merged.fields["dates"].values] == ["application_deadline"]
    assert merged.fields["dates"].label == ""


def test_a_dropped_deadline_later_than_every_kept_application_date_is_held():
    """T6 I5 (probe S3): compared with the kept application period, not only deadlines."""
    period = Value(AwardDate("application_period",
                             Date("1.11.2026-1.2.2027", 0, 10, 2026, 11, 1, 2027, 2, 1), True,
                             ()), Quote("x", "L1.text"), URL, ())
    merged = merge(award_card("Merit Award", None, {}, cycle=2027), frozenset({"dates"}), [
        _found(2027, "https://a.edu.az/2027", dates=Parsed((period,))),
        _found(2026, "https://a.edu.az/2026",
               dates=Parsed((_date("application_deadline", 2027, 3, 1),)))],
        TODAY, complete=True)
    assert _held(merged.fields["dates"]) == (
        "held", "conflicting_values", "hunt:application_deadline")


def _for(places, year, month, day, source):
    date = Date(f"{day}.{month}.{year}", 0, 10, year, month, day)
    return Value(AwardDate("application_deadline", date, False, places),
                 Quote(date.text, "L1.text"), source, ())


def test_a_place_deadline_in_another_year_than_the_general_one_is_held():
    """T6 R2 (probe C): 2b's cross-place year rule holds across current pages too; the same
    year on different days is shown (decision 13)."""
    general = _date("application_deadline", 2027, 1, 15)
    merged = merge(award_card("Merit Award", None, {}), frozenset({"dates"}), [
        _found(None, "https://a.edu.az/gen", dates=Parsed((general,))),
        _found(None, "https://a.edu.az/az",
               dates=Parsed((_for(("AZ",), 2026, 12, 1, "https://a.edu.az/az"),)))],
        TODAY, complete=True)
    assert _held(merged.fields["dates"]) == (
        "held", "conflicting_values", "hunt:application_deadline:AZ")
    same_year = merge(award_card("Merit Award", None, {}), frozenset({"dates"}), [
        _found(None, "https://a.edu.az/gen", dates=Parsed((general,))),
        _found(None, "https://a.edu.az/az",
               dates=Parsed((_for(("AZ",), 2027, 1, 1, "https://a.edu.az/az"),)))],
        TODAY, complete=True)
    assert same_year.fields["dates"].state == "shown"
    assert len(same_year.fields["dates"].values) == 2


def test_dates_held_for_a_disagreement_still_make_an_older_list_last_cycles():
    """T6 R2 (probe A): the newer cycle is read from every page's dates, not only those shown."""
    merged = merge(award_card("Merit Award", None, {}), frozenset({"nationality", "dates"}), [
        _found(None, "https://a.edu.az/old", nationality=_nat("AZ"),
               dates=Parsed((_date("application_deadline", 2026, 1, 15),))),
        _found(None, "https://a.edu.az/x",
               dates=Parsed((_date("application_deadline", 2026, 12, 15),))),
        _found(None, "https://a.edu.az/y",
               dates=Parsed((_date("application_deadline", 2027, 1, 15),)))],
        TODAY, complete=True)
    assert merged.fields["dates"].hold == "conflicting_values"
    assert (merged.fields["nationality"].state, merged.fields["nationality"].label) == (
        "shown", "last_cycle")


def test_a_value_a_current_page_also_gives_is_never_last_cycle_in_either_order():
    """T6 R2 (probe B): one page's deadline has passed, the other's is ahead; both list AZ."""
    old = _found(None, "https://a.edu.az/old", nationality=_nat("AZ"),
                 dates=Parsed((_date("application_deadline", 2026, 1, 15),)))
    new = _found(None, "https://a.edu.az/new", nationality=_nat("AZ"),
                 dates=Parsed((_date("application_deadline", 2027, 1, 15),)))
    for found in ([old, new], [new, old]):
        merged = merge(award_card("Merit Award", None, {}), frozenset({"nationality", "dates"}),
                       found, TODAY, complete=True)
        assert (merged.fields["nationality"].state, merged.fields["nationality"].label) == (
            "shown", ""), found[0].fields["nationality"].values[0].source


def test_a_passed_page_is_last_cycles_beside_any_date_still_ahead_whatever_the_years():
    """T6 R3 (probes L3, L3c): the old page's 15 Jan 2026 has passed and another page's
    15 Dec 2026 is ahead -- the same calendar year, so no year comparison could see it."""
    for cycle, ahead in ((None, (2026, 12, 15)), (2026, (2026, 12, 15)), (None, (2027, 1, 15))):
        merged = merge(award_card("Merit Award", None, {}), frozenset({"nationality", "dates"}), [
            _found(cycle, "https://a.edu.az/old", nationality=_nat("AZ"),
                   dates=Parsed((_date("application_deadline", 2026, 1, 15),))),
            _found(None, "https://a.edu.az/new",
                   dates=Parsed((_date("application_deadline", *ahead),)))], TODAY,
            complete=True)
        assert (merged.fields["nationality"].state, merged.fields["nationality"].label) == (
            "shown", "last_cycle"), (cycle, ahead)


def test_a_value_a_current_page_backs_cites_that_page_in_either_order():
    """T6 R3 (probe L4)."""
    old = _found(None, "https://a.edu.az/old", nationality=_nat("AZ"),
                 dates=Parsed((_date("application_deadline", 2026, 1, 15),)))
    new = _found(None, "https://a.edu.az/new", nationality=_nat("AZ"),
                 dates=Parsed((_date("application_deadline", 2027, 1, 15),)))
    for found in ([old, new], [new, old]):
        merged = merge(award_card("Merit Award", None, {}), frozenset({"nationality", "dates"}),
                       found, TODAY, complete=True)
        [who] = merged.fields["nationality"].values
        assert (who.source, merged.fields["nationality"].label) == ("https://a.edu.az/new", "")


def test_a_found_pointer_decides_when_the_start_page_did_not_state_the_field():
    """F-I2: the start page says nothing about nationality; the page found says where."""
    start = award_card("Merit Award", None, {})
    hunted = frozenset({"nationality"})
    fallback = Value(FALLBACK.value, None, "https://a.edu.az/merit", ())
    internationals = _found(2027, "https://a.edu.az/merit",
                            nationality=Parsed((fallback,), "needs_hunt", "internationals"))
    shown = merge(start, hunted, [internationals], TODAY, complete=True).fields["nationality"]
    assert (shown.state, shown.values) == ("shown", (fallback,))
    cut = merge(start, hunted, [internationals], TODAY, complete=False).fields["nationality"]
    assert (cut.state, cut.hold, cut.detail) == ("held", "needs_hunt", "internationals")
    elsewhere = _found(2027, "https://a.edu.az/other",
                       nationality=Parsed(problem="needs_hunt", detail="eligibility_elsewhere"))
    for found in ([elsewhere], [internationals, elsewhere]):
        held = merge(start, hunted, found, TODAY, complete=True).fields["nationality"]
        assert _held(held) == ("held", "hunt_not_found", "eligibility_elsewhere"), len(found)


def test_a_current_page_giving_another_value_than_last_cycles_is_held():
    """F-I3 (N1): the intake-2027 page's deadline has passed; the page with no intake has one
    still ahead and lists another country. Neither is shown over the other."""
    old = _found(2027, "https://a.edu.az/old", nationality=_nat("AZ"),
                 dates=Parsed((_date("application_deadline", 2026, 1, 15),)))
    new = _found(None, "https://a.edu.az/new", nationality=_nat("KZ"),
                 dates=Parsed((_date("application_deadline", 2026, 12, 15),)))
    for found in ([old, new], [new, old]):
        merged = merge(award_card("Merit Award", None, {}), frozenset({"nationality", "dates"}),
                       found, TODAY, complete=True)
        field = merged.fields["nationality"]
        assert _held(field) == ("held", "conflicting_values", "hunt:nationality")
        assert {c for v in field.values for c in v.value.eligible} == {"AZ", "KZ"}


def test_a_page_saying_students_apply_elsewhere_sends_the_application_facts_to_the_hunt():
    """F-M1 (spec §5.5 step 4): `apply_elsewhere` points to the facts of applying."""
    stated = {"dates": Parsed((_date("application_deadline", 2027, 1, 15),)),
              "target_level": _label("master"), "benefits": Parsed(problem="page_budget"),
              "nationality": _nat("AZ")}
    assert wanted(award_card("A", None, stated), TODAY) == set()
    pointer = award_card("A", None, {**stated, "apply_elsewhere": _label("yes")})
    assert wanted(pointer, TODAY) == {"requirements"}
    both = award_card("A", None, {**stated, "apply_elsewhere": _label("yes"),
                                  "apply_here": _label("yes")})  # contradicts itself: not hunted
    assert wanted(both, TODAY) == set()


def test_every_country_but_the_host_from_a_last_cycle_found_page_is_labelled():
    """R1 (probes A, B): the fallback a found page's "international students" pointer shows is
    that page's: an older stated intake, or its own deadline passed beside one still ahead."""
    pointer = Parsed((FALLBACK,), "needs_hunt", "internationals")
    older = merge(award_card("Merit Award", None, {}, cycle=2027), frozenset({"nationality"}),
                  [_found(2025, "https://a.edu.az/old", nationality=pointer)], TODAY,
                  complete=True).fields["nationality"]
    passed = merge(award_card("Merit Award", None, {}), frozenset({"nationality", "dates"}), [
        _found(None, "https://a.edu.az/old", nationality=pointer,
               dates=Parsed((_date("application_deadline", 2026, 1, 15),))),
        _found(None, "https://a.edu.az/new",
               dates=Parsed((_date("application_deadline", 2026, 12, 15),)))], TODAY,
        complete=True).fields["nationality"]
    for field in (older, passed):
        assert (field.state, field.label, field.values[0].source) == (
            "shown", "last_cycle", "https://a.edu.az/old")


def test_every_country_but_the_host_from_a_last_cycle_start_page_is_labelled():
    """R3 (probe E): the start page's own deadline passed; a found intake-2027 page's is ahead."""
    start = award_card("Merit Award", None, {
        "nationality": Parsed((FALLBACK,), "needs_hunt", "internationals"),
        "dates": Parsed((_date("application_deadline", 2026, 1, 15),))})
    field = merge(start, frozenset({"nationality", "dates"}), [
        _found(2027, "https://a.edu.az/new",
               dates=Parsed((_date("application_deadline", 2026, 12, 15),)))], TODAY,
        complete=True).fields["nationality"]
    assert (field.state, field.label, field.values) == ("shown", "last_cycle", (FALLBACK,))


def test_a_current_page_whose_own_reading_is_held_holds_last_cycles_value():
    """R2 (probe D): F-I3 with the current page's nationality held, not shown -- in both orders."""
    old = _found(2027, "https://a.edu.az/old", nationality=_nat("AZ"),
                 dates=Parsed((_date("application_deadline", 2026, 1, 15),)))
    ahead = Parsed((_date("application_deadline", 2026, 12, 15),))
    for reading in (Parsed(_nat("KZ").values, "conflicting_values", "nationality"),
                    Parsed(problem="unparseable_value", detail="p1")):
        new = _found(None, "https://a.edu.az/new", nationality=reading, dates=ahead)
        for found in ([old, new], [new, old]):
            field = merge(award_card("Merit Award", None, {}),
                          frozenset({"nationality", "dates"}), found, TODAY,
                          complete=True).fields["nationality"]
            assert _held(field) == ("held", "conflicting_values", "hunt:nationality"), (
                reading.problem, found[0] is old)
            assert {c for v in field.values for c in v.value.eligible} == (
                {"AZ"} | {c for v in reading.values for c in v.value.eligible})


def test_a_current_start_page_whose_own_reading_is_held_holds_last_cycles_value():
    """R2 on the start page (final review of the residual round): its own deadline is ahead and
    its nationality held; a found page whose deadline passed lists AZ."""
    start = award_card("Merit Award", None, {
        "nationality": Parsed(problem="unresolved_split", detail="nationality"),
        "dates": Parsed((_date("application_deadline", 2026, 12, 15),))})
    old = _found(None, "https://a.edu.az/old", nationality=_nat("AZ"),
                 dates=Parsed((_date("application_deadline", 2026, 1, 15),)))
    field = merge(start, frozenset({"nationality", "dates"}), [old], TODAY,
                  complete=True).fields["nationality"]
    assert _held(field) == ("held", "conflicting_values", "hunt:nationality")
