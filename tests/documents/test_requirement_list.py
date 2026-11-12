"""The requirement list's model and builder (spec 2026-10-12 §6.3). Pure: no
database, no model call -- programmes and catalog rows are stand-ins."""

from dataclasses import fields
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.documents.constraints import ConstraintRule, Enforcement
from apps.documents.letter_shape import _SHAPE_TO_KEY, LetterShape
from apps.documents.requirement_list import (
    LETTER_FIELD_KEYS,
    Requirement,
    RequirementList,
    build_requirements,
)


def test_an_item_round_trips_through_json():
    rule = ConstraintRule(rule_id="P-1", key="max_pages", value=2,
                          enforcement=Enforcement.ADVISORY_HIGH_RISK, rule_text="Two pages.")
    listed = RequirementList(items=(
        Requirement(key="max_pages", value=2, document="cv", origin="programme",
                    force="soft", rule=rule, contributors=("P-1",), sentence="Two pages."),
        Requirement(key="order", value=["cv", "chronological"], document="cv",
                    origin="programme", force="soft"),
    ))
    assert RequirementList.model_validate_json(listed.model_dump_json()) == listed


def test_an_item_key_outside_the_closed_lists_is_refused():
    with pytest.raises(ValidationError):
        Requirement(key="nobel_prize", document="cv", origin="programme", force="soft")


def test_the_letter_field_keys_are_exactly_the_letter_shapes_own_fields():
    """A LetterShape field added without an item key would never reach the list."""
    not_items = {"sources", "written_requirements", "student_actions", "track",
                 "portfolio_led", *_SHAPE_TO_KEY}
    assert set(LETTER_FIELD_KEYS) == {f.name for f in fields(LetterShape)} - not_items


def test_the_cv_projection_and_the_conflict_groups():
    rule = ConstraintRule(rule_id="P-1", key="language", value="de",
                          enforcement=Enforcement.ADVISORY_HIGH_RISK, rule_text="German.")
    listed = RequirementList(items=(
        Requirement(key="language", value="de", document="cv", origin="programme",
                    force="soft", rule=rule, conflict="language"),
        Requirement(key="max_words", value=800, document="letter", origin="programme",
                    force="strict"),
    ))
    assert listed.cv_rules() == (rule,)
    assert list(listed.conflicts()) == ["language"]
    assert [i.key for i in listed.for_document("letter")] == ["max_words"]


def test_info_items_reach_render_only_for_the_three_keys_it_surfaces():
    font = ConstraintRule(rule_id="P-1", key="font", value="Arial",
                          enforcement=Enforcement.ADVISORY_HIGH_RISK, rule_text="Arial.")
    undecided = ConstraintRule(rule_id="P-2", key="undecided", value="x",
                               enforcement=Enforcement.ADVISORY_HIGH_RISK, rule_text="Unclear.")
    listed = RequirementList(items=(
        Requirement(key="font", value="Arial", document="cv", origin="programme",
                    force="info", rule=font),
        Requirement(key="undecided", value="x", document="cv", origin="programme",
                    force="info", rule=undecided),
    ))
    assert listed.cv_rules() == (undecided,)


def _programme(**overrides):
    base = dict(
        cv_constraints=[], cv_directives=[], cv_format_requirement="any",
        cv_format_source_url="", country_code="DE", academic_track="taught",
        institution=SimpleNamespace(canonical_key="de:tum"),
    )
    return SimpleNamespace(**(base | overrides))


def _row(rule_id, scope_kind, scope_values, key, value, enforcement="BINDING"):
    return SimpleNamespace(
        rule_id=rule_id, scope_kind=scope_kind, scope_values=scope_values, key=key,
        value=value, enforcement=enforcement, rule_text=f"{rule_id} says so.", source_url="",
    )


def test_catalog_scopes_land_as_theirs_or_ours():
    catalog = [
        _row("C-1", "COUNTRY", ["DE"], "photo_allowed", True, "ADVISORY_STYLE"),
        _row("I-1", "INSTITUTION", ["de:tum"], "ai_use_policy", "PROHIBITS",
             "ADVISORY_HIGH_RISK"),
        _row("F-1", "FUNDER", ["daad"], "max_pages", 3),
    ]
    funder = SimpleNamespace(canonical_key="daad", cv_format_requirement="")
    listed = build_requirements(_programme(), funder, catalog=catalog, track="taught")
    origins = {item.contributors[0]: item.origin for item in listed.items if item.contributors}
    assert origins == {"C-1": "ours", "I-1": "institution", "F-1": "scholarship"}


def test_the_format_is_the_funders_then_the_programmes():
    programme = _programme(cv_format_requirement="europass_required",
                           cv_format_source_url="https://tum.example/apply")
    funder = SimpleNamespace(canonical_key="rhodes", cv_format_requirement="funder_template")
    [own] = [i for i in build_requirements(programme).items if i.key == "cv_format"]
    [theirs] = [i for i in build_requirements(programme, funder).items if i.key == "cv_format"]
    assert (own.value, own.origin, own.force) == ("europass_required", "programme", "strict")
    assert (theirs.value, theirs.origin) == ("funder_template", "scholarship")
    [unclear] = [i for i in build_requirements(_programme()).items if i.key == "cv_format"]
    assert (unclear.value, unclear.force) == ("any", "info")


def test_the_letter_part_is_its_own_document():
    """A 1-page letter limit never becomes the CV's (spec 6.3)."""
    shape = LetterShape(
        max_pages=1.0, form="FORMAL_LETTER",
        sources={"max_pages": {"text": "One page.", "source_url": "u"},
                 "form": {"text": "A formal letter.", "source_url": "u"}},
        written_requirements=({"text": "Say why this programme.", "source_url": "u"},),
        student_actions=({"text": "Sign it by hand.", "source_url": "u"},),
    )
    listed = build_requirements(_programme(), letter_shape=shape)
    letter = {(i.key, i.force) for i in listed.for_document("letter")}
    assert letter == {("max_pages", "strict"), ("form", "strict"),
                      ("written_requirement", "soft"), ("student_action", "info")}
    assert all(rule.key != "max_pages" for rule in listed.cv_rules())


def test_competencies_rank_relevance_only_and_never_reach_render():
    listed = build_requirements(_programme(), competencies=("Linear algebra.",))
    [item] = [i for i in listed.items if i.key == "competency"]
    assert (item.relevance_only, item.force, item.rule) == (True, "info", None)
    assert listed.cv_rules() == ()


def test_a_style_rule_held_in_code_loses_to_any_catalog_rule():
    style = ConstraintRule(rule_id="S-022", key="min_final_page_fill", value=0.2,
                           enforcement=Enforcement.ADVISORY_STYLE, rule_text="Fill it.",
                           scope="UNIVERSAL")
    catalog = [_row("U-9", "UNIVERSAL", [], "min_final_page_fill", 0.3, "ADVISORY_STYLE")]
    listed = build_requirements(_programme(), catalog=catalog, style_rules=(style,))
    assert [(r.rule_id, r.value) for r in listed.cv_rules()] == [("U-9", 0.3)]


def test_a_malformed_stored_directive_raises_rather_than_being_skipped():
    with pytest.raises(ValidationError):
        build_requirements(_programme(cv_directives=[{"action": "exclude", "target": "x"}]))


def test_no_content_only_key_merges_as_information_or_first_seen():
    """render._blocked_by_content_only_rules inspects BINDING rules only, and
    every derived page rule is ADVISORY. `info` caps force at ADVISORY_HIGH_RISK
    and `first` keeps whichever came first, so either row on a content-only key
    (date_of_issue_required above all: Europass can never carry it) could let
    a page sentence open the Europass PII egress. They need a strictness row."""
    from apps.documents.render import _CONTENT_ONLY_KEYS
    from apps.documents.requirement_list import MERGE

    assert {k: MERGE[k] for k in _CONTENT_ONLY_KEYS if MERGE[k] in {"info", "first"}} == {}


def test_two_caps_on_one_section_resolve_to_the_lowest():
    catalog = [
        _row("C-1", "COUNTRY", ["DE"], "max_entries_per_section", {"publications": 5}),
        _row("F-1", "FUNDER", ["daad"], "max_entries_per_section", {"publications": 3}),
    ]
    funder = SimpleNamespace(canonical_key="daad", cv_format_requirement="")
    listed = build_requirements(_programme(), funder, catalog=catalog, track="taught")
    [rule] = [r for r in listed.cv_rules() if r.key == "max_entries_per_section"]
    assert rule.value == {"publications": 3}


# --- ids and digest (spec §6.12) ---------------------------------------------


def _rule(rule_id, key, value, text=None, enforcement="BINDING"):
    row = _row(rule_id, "UNIVERSAL", [], key, value, enforcement)
    return SimpleNamespace(**(row.__dict__ | {"rule_text": text})) if text else row


def _list_from(rules):
    return build_requirements(_programme(), catalog=rules, track="taught")


def _written(text):
    return Requirement(key="written_requirement", document="letter", origin="programme",
                       force="soft", sentence=text)


def _two_builds_of_the_same_programme():
    catalog = [_rule("C-1", "max_pages", 2), _rule("C-2", "photo_allowed", False)]
    a = _list_from(catalog)
    b = _list_from([_rule("C-1", "max_pages", 2), _rule("C-2", "photo_allowed", False)])
    return a, b


def test_item_ids_are_the_same_across_two_builds():
    a, b = _two_builds_of_the_same_programme()
    assert [i.id for i in a.items] == [i.id for i in b.items]
    assert all(len(i.id) == 16 for i in a.items)


def test_true_duplicates_get_distinct_ids():
    built = RequirementList(items=(_written("Send a CV"), _written("Send a CV")))
    assert len({i.id for i in built.items}) == 2


def test_a_reread_that_changes_only_rule_ids_and_order_keeps_ids_and_digest():
    before = _list_from([_rule("PAGE-3", "max_pages", 2), _rule("PAGE-7", "photo_allowed", False)])
    after = _list_from([_rule("PAGE-9", "photo_allowed", False), _rule("PAGE-1", "max_pages", 2)])
    assert {i.key: i.id for i in before.items} == {i.key: i.id for i in after.items}
    assert before.digest() == after.digest()


def test_the_digest_changes_when_a_value_changes():
    assert _list_from([_rule("PAGE-3", "max_pages", 2)]).digest() != \
           _list_from([_rule("PAGE-3", "max_pages", 3)]).digest()


def test_the_digest_ignores_sentences_and_contributors():
    a = _list_from([_rule("PAGE-3", "max_pages", 2, text="Two pages max.")])
    b = _list_from([_rule("PAGE-3", "max_pages", 2, text="CV: at most 2 pages")])
    assert a.digest() == b.digest()


def test_a_ruled_items_sentence_is_dumped_once_and_read_back():
    built = _list_from([_rule("PAGE-3", "max_pages", 2, text="Two pages max.")])
    dumped = built.model_dump(mode="json")
    assert "sentence" not in dumped["items"][0]
    assert RequirementList.model_validate(dumped).items[0].sentence == "Two pages max."


def test_an_item_has_no_state_field():
    assert "state" not in Requirement.model_fields
