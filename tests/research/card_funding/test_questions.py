from uuid import uuid4

from apps.research.candidates import Line, find_all
from apps.research.card_engine import Limit, Quote, Section
from apps.research.card_engine.engine import read
from apps.research.card_engine.screen import Screen
from apps.research.card_funding.questions import (
    AWARD,
    BATCH,
    CRITERIA,
    Funding,
    batches,
    code_questions,
    kind_questions,
)

from .oracle import Oracle

SECTION = Section("Stipendium Hungaricum", "en", (
    Line("Stipendium Hungaricum", heading=""),
    Line("Monthly stipend of HUF 43,700 (approx. 110 EUR) for master students",
         heading="Stipendium Hungaricum"),
    Line("Tuition support between EUR 1,000 and EUR 2,000", heading="Stipendium Hungaricum"),
    Line("Apply by 10/11/2026 if you are from Azerbaijan", heading="Stipendium Hungaricum"),
    Line("Open to citizens of low- and middle-income countries. IELTS 6.0 required.",
         heading="Stipendium Hungaricum"),
    Line("Applicants must not have lived in Hungary for more than 12 months.",
         heading="Stipendium Hungaricum"),
))


def _limit():
    return Limit("card-funding-test", uuid4(), 500, 3600)


def test_every_question_refers_to_page_text_by_key_only():
    questions = code_questions(find_all(SECTION.lines))
    page_only = ("Hungaricum", "43,700", "10/11/2026", "Azerbaijan", "Hungary", "IELTS", "low-")
    for q in questions:
        assert not [w for w in page_only if w in q.text + q.criteria + " ".join(q.options)], q.id
    assert len({q.id for q in questions}) == len(questions)
    assert "HUF" not in CRITERIA


def test_code_questions_follow_the_candidates():
    c = find_all(SECTION.lines)
    ids = {q.id for q in code_questions(c)}
    assert {qid for qid, *_ in AWARD} <= ids
    [conversion] = c.conversion_of  # "(approx. 110 EUR)" converts HUF 43,700: asked once, with it
    assert f"pays_{conversion}" not in ids and f"pays_{c.conversion_of[conversion]}" in ids
    ranged = next(k for k, f in c.amounts.items() if f.value.bound == "range")
    assert f"pays_{ranged}" in ids and f"bound_{ranged}" not in ids  # code set the range
    [date] = c.dates  # 10/11/2026: day or month first is asked, never guessed
    assert f"order_{date}" in ids
    places = {f.value.text: k for k, f in c.places.items()}
    assert f"for_{places['Azerbaijan']}_{date}" in ids  # a place on the date's own line
    lmy = places["low- and middle-income countries"]
    assert f"sole_{lmy}" in ids and f"sole_{places['Azerbaijan']}" not in ids
    level = next(iter(c.levels))
    first = next(k for k in c.amounts if k not in c.conversion_of)
    assert any(q.id == f"level_{first}" and level in q.options for q in code_questions(c))


def test_batches_cover_every_code_question_once():
    c = find_all(SECTION.lines)
    every = [q.id for q in code_questions(c)]
    seen = []
    for n in range(1, batches(SECTION) + 1):
        asked = Funding(batch=n).questions(SECTION, c, {})
        assert 0 < len(asked) <= BATCH
        seen += [q.id for q in asked]
    assert seen == every
    assert Funding(batch=1).proposals(SECTION) == ()
    assert [q.id for q in Funding(batch=0).proposals(SECTION)] == ["requirements"]


def test_a_proposed_quote_that_repeats_a_code_candidate_is_not_asked_again():
    c = find_all(SECTION.lines)
    proposed = {"requirements": (
        Quote("IELTS 6.0 required", "L4.text"),
        Quote("must not have lived in Hungary for more than 12 months", "L5.text"),
    )}
    assert [q.id for q in kind_questions(c, proposed)] == ["kind_1"]


def test_batch_zero_reads_the_proposals_and_asks_their_kinds():
    oracle = Oracle({
        "requirements": ["must not have lived in Hungary for more than 12 months"],
        "kind_0": ("residence_limit", "must not have lived in Hungary for more than 12 months"),
    })
    reading = read(Funding(batch=0), SECTION, screen=Screen("clear", SECTION.texts()),
                   limit=_limit(), transport=oracle)
    assert reading.proposed["requirements"] == (
        Quote("must not have lived in Hungary for more than 12 months", "L5.text"),)
    [kind] = reading.decisions
    assert (kind.question, kind.status, kind.value) == ("kind_0", "agreed", "residence_limit")


def test_target_level_can_say_several_levels_or_students_in_general():
    """Task 8 D (owner serve rule, slice 3): two cases the single choice could not express."""
    [options] = [opts for qid, _text, opts, _crit in AWARD if qid == "target_level"]
    assert options == ("master", "bachelor", "phd", "postdoc", "master_among_several",
                       "higher_education_general", "any", "year_of_study", "not_stated")
    for option in ("master_among_several", "higher_education_general"):
        assert option in CRITERIA
    assert "the first of bachelor, phd, postdoc" in CRITERIA


def test_a_hunt_asks_only_the_questions_its_fields_are_parsed_from():
    """2c: the same set, restricted to the hunted fields; no fields is every question, in order."""
    c = find_all(SECTION.lines)
    assert code_questions(c, frozenset()) == code_questions(c)
    assert [q.id for q in code_questions(c, frozenset({"target_level"}))] == ["target_level"]
    places = {f"{side}_{k}" for k in c.places for side in ("eligible", "excluded")}
    nationality = {q.id for q in code_questions(c, frozenset({"nationality"}))}
    assert nationality - places == {"place_basis", "internationals", "eligibility_elsewhere",
                                    *(f"sole_{k}" for k in c.places
                                      if c.places[k].value.text.startswith("low-"))}
    dates = [q.id for q in code_questions(c, frozenset({"dates"}))]
    [date] = c.dates
    assert dates[0] == f"role_{date}" and all(q.endswith(date) for q in dates)
    money = {q.id for q in code_questions(c, frozenset({"fees"}))}
    assert money == {q.id for q in code_questions(c, frozenset({"benefits"}))}
    assert all(not q.startswith(("role_", "eligible_", "target_level")) for q in money)


def test_a_hunt_without_requirements_proposes_nothing_and_batches_only_its_own_questions():
    c = find_all(SECTION.lines)
    only = frozenset({"target_level", "dates"})
    assert Funding(batch=0, fields=only).proposals(SECTION) == ()
    assert [q.id for q in Funding(batch=0, fields=frozenset({"requirements"})).proposals(
        SECTION)] == ["requirements"]
    assert batches(SECTION, only) == 1 < batches(SECTION)
    asked = [q.id for q in Funding(batch=1, fields=only).questions(SECTION, c, {})]
    assert asked == [q.id for q in code_questions(c, only)]
