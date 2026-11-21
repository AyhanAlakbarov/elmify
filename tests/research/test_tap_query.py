"""The tap's three bins and its deterministic slot-filling (spec 10.5)."""

import ast
from pathlib import Path

from apps.accounts.schemas import StudentProfileSnapshot
from apps.research.providers import SearchRequest
from apps.research.tap_query import (
    NEVER,
    OUTPUT_FILTERS,
    QUERY_WORDS,
    inputs_from,
    render_tap_queries,
)
from apps.research.tap_seams import AngleRow, TapQueryInputs

_ANGLE = AngleRow(
    id="p1", language="en",
    template="Our M.Sc. in {field}, {teaching_language} — {money}, {intake} intake, {destination}",
)


def test_every_profile_field_is_in_exactly_one_bin() -> None:
    fields = set(StudentProfileSnapshot.model_fields) - {"schema_version"}
    bins = [set(QUERY_WORDS), set(OUTPUT_FILTERS), set(NEVER)]
    assert set().union(*bins) == fields
    assert sum(len(b) for b in bins) == len(fields)


def test_the_inputs_type_carries_the_query_word_bin_and_nothing_else() -> None:
    # The shape IS the allow-list (spec 10.5, D.6): a fact with no field cannot travel.
    assert set(TapQueryInputs.__dataclass_fields__) == {
        "field_words", "interest_words", "teaching_languages", "money_words", "money_first",
        "intake_year", "duration_words", "research_pathway", "destinations",
    }


def test_a_school_or_supervisor_name_in_free_text_never_reaches_a_query(profile_snapshot) -> None:
    profile = profile_snapshot(
        target_field="Chemistry at Middle East Technical University",
        research_interests=("catalysis with Prof Aydın",),
    )
    inputs = inputs_from(profile)
    text = " ".join([*inputs.field_words, *inputs.interest_words]).lower()
    assert "middle east technical" not in text and "aydın" not in text
    assert inputs.field_words == ("chemistry",) and inputs.interest_words == ("catalysis",)


def test_the_students_own_school_is_banned_even_without_a_marker_word(profile_snapshot) -> None:
    from apps.accounts.schemas import AcademicRecord

    school = AcademicRecord(
        institution="Khazar", country_code="AZ", qualification="BSc", field="Chemistry",
        grade="90", grading_scale="100",
    )
    profile = profile_snapshot(academic_history=(school,), target_field="Khazar style chemistry")
    assert inputs_from(profile).field_words == ("style chemistry",)


def test_a_title_case_field_survives_the_guard(profile_snapshot) -> None:
    """guard_phrase alone strips every capitalised run -- "Computer Science" too."""
    assert inputs_from(profile_snapshot(target_field="Computer Science")).field_words == (
        "computer science",
    )


def test_nationality_residence_and_notes_never_reach_a_rendered_query(profile_snapshot) -> None:
    profile = profile_snapshot(
        nationality="AZ", country_of_residence="GE",
        additional_notes="I am Azerbaijani, from Ganja", allowed_countries=("DE",),
        target_field="Chemistry in Azerbaijan",
    )
    rendered = render_tap_queries(inputs_from(profile), (_ANGLE,))
    assert len(rendered) == 1
    for angle_id, request in rendered:
        assert angle_id == "p1" and isinstance(request, SearchRequest)
        lowered = f" {request.query.lower()} "
        for never in ("azerbaijan", "georgia", "ganja", " az ", " ge "):
            assert never not in lowered
        assert "germany" in lowered and "chemistry" in lowered


def test_an_excluded_country_is_never_a_destination(profile_snapshot) -> None:
    profile = profile_snapshot(allowed_countries=("DE", "FR"), excluded_countries=("IT",))
    assert inputs_from(profile).destinations == ("DE", "FR")


def test_rendering_is_deterministic_complete_and_tagged(profile_snapshot) -> None:
    angles = tuple(
        AngleRow(id=f"a{i}", language="en" if i % 2 else "tr", template="{field} {intake}")
        for i in range(60)
    )
    first = render_tap_queries(inputs_from(profile_snapshot()), angles)
    assert first == render_tap_queries(inputs_from(profile_snapshot()), angles)
    assert len(first) == 60
    assert all(10 <= request.max_results <= 15 for _, request in first)
    assert [angle_id for angle_id, _ in first[:2]] == ["a0", "a1"]
    assert first[0][1].phrasing == "local" and first[1][1].phrasing == "english"
    assert first[0][1].query == "computer science 2027"


def test_a_template_slot_outside_the_allow_list_refuses_the_angle(profile_snapshot) -> None:
    angles = (AngleRow(id="bad", language="en", template="{nationality} students {field}"),)
    assert render_tap_queries(inputs_from(profile_snapshot()), angles) == ()


def test_an_angle_whose_input_the_student_did_not_give_is_not_asked(profile_snapshot) -> None:
    angles = (AngleRow(id="d", language="en", template="{field} {duration}"),)
    assert render_tap_queries(inputs_from(profile_snapshot()), angles) == ()


def test_funding_dependency_picks_the_money_vocabulary(profile_snapshot) -> None:
    must = inputs_from(profile_snapshot(funding_dependency="MANDATORY"))
    optional = inputs_from(profile_snapshot(funding_dependency="OPTIONAL"))
    assert "fully funded" in must.money_words
    assert "partial scholarship" in optional.money_words


def test_funding_first_runs_the_money_angles_first(profile_snapshot) -> None:
    angles = (
        AngleRow(id="plain", language="en", template="{field}"),
        AngleRow(id="money", language="en", template="{field} {money}"),
    )
    balanced = render_tap_queries(inputs_from(profile_snapshot(strategy="BALANCED")), angles)
    first = render_tap_queries(inputs_from(profile_snapshot(strategy="FUNDING_FIRST")), angles)
    assert [a for a, _ in balanced] == ["plain", "money"]
    assert [a for a, _ in first] == ["money", "plain"]


def test_phd_intent_adds_the_research_pathway(profile_snapshot) -> None:
    angle = (AngleRow(id="r", language="en", template="{field} {pathway}"),)
    abroad = inputs_from(profile_snapshot(career_intent="WORK_ABROAD"))
    assert render_tap_queries(abroad, angle) == ()
    ((_, request),) = render_tap_queries(inputs_from(profile_snapshot(career_intent="PHD")), angle)
    assert "research assistantship" in request.query


def test_duration_preference_uses_the_schemas_values(profile_snapshot) -> None:
    one = profile_snapshot(
        duration_preference="ONE_YEAR", duration_flexibility="NON_NEGOTIABLE",
    )
    assert inputs_from(one).duration_words[0] == "one-year master's"


def test_the_area_sweep_side_never_imports_the_tap_query() -> None:
    """Destination words apply at the tap only (decision 33)."""
    research = Path(__file__).resolve().parents[2] / "apps" / "research"
    for module in ("harness.py", "angles.py", "seam_bindings.py"):
        tree = ast.parse((research / module).read_text(encoding="utf-8"))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not any("tap_query" in name for name in imported), module


# 2026-10-14 fixes: a field led by a word that also names bodies, C++, every
# interest, and one destination per query.

def test_a_field_that_starts_with_a_body_word_survives(profile_snapshot) -> None:
    """"Hospital Management" was wiped whole: the run carries "hospital"."""
    for typed, expected in (
        ("Hospital Management", "hospital management"),
        ("Laboratory Medicine", "laboratory medicine"),
        ("School Psychology", "school psychology"),
        ("Company Law", "company law"),
    ):
        assert inputs_from(profile_snapshot(target_field=typed)).field_words == (expected,)


def test_a_body_named_with_a_shared_word_is_still_stripped(profile_snapshot) -> None:
    for typed in ("Nursing at Charité Hospital", "Finance at Bank of America",
                  "Data science with Max Planck Lab", "Harvard Medical School pathology"):
        words = inputs_from(profile_snapshot(target_field=typed)).field_words
        text = " ".join(words)
        for name in ("charité", "bank", "planck", "harvard"):
            assert name not in text, (typed, text)


def test_programming_language_names_keep_their_symbols(profile_snapshot) -> None:
    inputs = inputs_from(profile_snapshot(
        target_field="C++ and C# programming", research_interests=("F# compilers",),
    ))
    assert inputs.field_words == ("c++ and c# programming",)
    assert inputs.interest_words == ("f# compilers",)


def test_every_research_interest_is_asked(profile_snapshot) -> None:
    angle = (AngleRow(id="i", language="en", template="{field} {interest}"),)
    profile = profile_snapshot(research_interests=("catalysis", "polymers", "spectroscopy"))
    queries = [r.query for _, r in render_tap_queries(inputs_from(profile), angle)]
    assert queries == ["computer science catalysis", "computer science polymers",
                       "computer science spectroscopy"]


def test_each_destination_gets_its_own_query(profile_snapshot) -> None:
    angle = (AngleRow(id="d", language="en", template="{field} in {destination}"),)
    profile = profile_snapshot(allowed_countries=("DE", "NL", "SE"))
    queries = [r.query for _, r in render_tap_queries(inputs_from(profile), angle)]
    # Measured 2026-10-12: one query naming three countries returned 5 universities, all
    # German; one query per country returned 16 across the three.
    assert queries == ["computer science in Germany", "computer science in Netherlands",
                       "computer science in Sweden"]


def test_every_country_is_asked_before_any_country_repeats(profile_snapshot) -> None:
    """Measured 2026-10-14 on c093e77a: 15 templates x 3 countries under the cap
    gave Germany 15 queries, the Netherlands 5 and Sweden none."""
    angles = tuple(
        AngleRow(id=f"a{i}", language="en", template=f"v{i} {{field}} {{destination}}")
        for i in range(15)
    )
    profile = profile_snapshot(allowed_countries=("DE", "NL", "SE"))
    queries = [r.query for _, r in render_tap_queries(inputs_from(profile), angles)]
    assert len(queries) == 45
    assert [q.split()[-1] for q in queries[:3]] == ["Germany", "Netherlands", "Sweden"]
    names = ("Germany", "Netherlands", "Sweden")
    counts = [sum(country in q for q in queries) for country in names]
    assert counts == [15, 15, 15]


def test_every_interest_is_reached_early_when_countries_are_many(profile_snapshot) -> None:
    angle = (AngleRow(id="i", language="en", template="{interest} M.Sc. in {destination}"),)
    profile = profile_snapshot(
        research_interests=("catalysis", "polymers", "spectroscopy"),
        allowed_countries=tuple("DE NL SE FR IT ES PT BE AT CH".split()),
    )
    queries = [r.query for _, r in render_tap_queries(inputs_from(profile), angle)]
    assert {q.split()[0] for q in queries[:6]} == {"catalysis", "polymers", "spectroscopy"}


def test_a_country_is_named_in_the_templates_language(profile_snapshot) -> None:
    angles = (
        AngleRow(id="de", language="de", template="Masterstudiengang {field} in {destination}"),
        AngleRow(id="en", language="en", template="M.Sc. in {field} in {destination}"),
    )
    queries = [r.query for _, r in render_tap_queries(
        inputs_from(profile_snapshot(allowed_countries=("DE",))), angles)]
    assert queries == ["Masterstudiengang computer science in Deutschland",
                       "M.Sc. in computer science in Germany"]


def test_every_render_is_returned_uncapped_and_each_country_gets_its_own_query(
    profile_snapshot,
) -> None:
    codes = tuple("DE NL SE FR IT ES PT".split())
    angle = (AngleRow(id="d", language="en", template="M.Sc. in {field} in {destination}"),)
    many = tuple(AngleRow(id=f"a{i}", language="en", template=f"v{i} {{field}}") for i in range(60))
    profile = profile_snapshot(allowed_countries=codes)
    assert len(render_tap_queries(inputs_from(profile), many)) == 60
    queries = [r.query for _, r in render_tap_queries(inputs_from(profile), angle)]
    assert len(queries) == 7 and all("," not in q for q in queries)


def test_unconstrained_self_funded_student_omits_money_words_and_money_angles(
    profile_snapshot,
) -> None:
    angles = (
        AngleRow(id="plain", language="en", template="{field} in {destination}"),
        AngleRow(id="money", language="en", template="{field} {money} in {destination}"),
    )
    profile = profile_snapshot(
        funding_dependency="OPTIONAL",
        self_funding_capacity=None,
        allowed_countries=("GB",),
    )
    inputs = inputs_from(profile)
    assert inputs.money_words == ()
    rendered = render_tap_queries(inputs, angles)
    assert [angle_id for angle_id, _ in rendered] == ["plain"]

