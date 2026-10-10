"""The tap's three bins and its deterministic slot-filling (spec 10.5)."""

import ast
from pathlib import Path

from apps.accounts.schemas import StudentProfileSnapshot
from apps.research.providers import SearchRequest
from apps.research.tap_query import (
    NEVER,
    OUTPUT_FILTERS,
    QUERY_WORDS,
    TapQueryInputs,
    inputs_from,
    render_tap_queries,
)
from apps.research.tap_seams import AngleRow

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
    profile = profile_snapshot(allowed_countries=("DE", "FR"))
    assert inputs_from(profile).destinations == ("Germany", "France")


def test_rendering_is_deterministic_bounded_and_tagged(profile_snapshot) -> None:
    angles = tuple(
        AngleRow(id=f"a{i}", language="en" if i % 2 else "tr", template="{field} {intake}")
        for i in range(60)
    )
    first = render_tap_queries(inputs_from(profile_snapshot()), angles)
    assert first == render_tap_queries(inputs_from(profile_snapshot()), angles)
    assert len(first) == 20
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
