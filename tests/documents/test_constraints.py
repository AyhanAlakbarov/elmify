import pytest
from pydantic import ValidationError

from apps.documents.constraints import ConstraintRule, Enforcement


def test_constraint_rule_rejects_unknown_key():
    with pytest.raises(ValidationError):
        ConstraintRule(
            rule_id="R-999",
            key="not_a_real_key",
            value=True,
            enforcement=Enforcement.BINDING,
            rule_text="x",
            source_url="",
        )


def test_constraint_rule_binding_example():
    rule = ConstraintRule(
        rule_id="R-078",
        key="max_entries_per_section",
        value={"experience": 3},
        enforcement=Enforcement.BINDING,
        rule_text="alterations will render your application ineligible",
        source_url="https://example.org/sisgp",
    )
    assert rule.enforcement == Enforcement.BINDING


def test_constraint_rule_advisory_high_risk_photo_example():
    rule = ConstraintRule(
        rule_id="R-032",
        key="photo_allowed",
        value=False,
        enforcement=Enforcement.ADVISORY_HIGH_RISK,
        rule_text="US admissions offices commonly discard CVs containing photographs",
        source_url="https://example.org/r-032",
    )
    assert rule.value is False


def test_constraint_rule_rejects_extra_field():
    with pytest.raises(ValidationError):
        ConstraintRule(
            rule_id="R-032",
            key="photo_allowed",
            value=False,
            enforcement=Enforcement.ADVISORY_HIGH_RISK,
            rule_text="x",
            source_url="",
            unexpected="nope",
        )


def test_constraint_rule_is_frozen():
    rule = ConstraintRule(
        rule_id="R-032",
        key="photo_allowed",
        value=False,
        enforcement=Enforcement.ADVISORY_HIGH_RISK,
        rule_text="x",
        source_url="",
    )
    with pytest.raises(ValidationError):
        rule.value = True


@pytest.mark.parametrize("key", ["undecided", "unapplied"])
def test_a_surfaced_rule_validates_with_its_quote(key):
    rule = ConstraintRule(
        rule_id=f"PAGE-3-{key}",
        key=key,
        value="cv_format",
        enforcement=Enforcement.ADVISORY_HIGH_RISK,
        rule_text="(Europass) CV",
        source_url="https://emship.eu/how-to-apply/",
    )
    assert rule.key == key


def test_constraint_rule_accepts_min_words():
    rule = ConstraintRule(
        rule_id="L-008", key="min_words", value=800, enforcement=Enforcement.BINDING,
        rule_text="minimum of 800 words for postgraduates", source_url="https://example.org/csc",
    )
    assert rule.value == 800


def test_constraint_rule_accepts_max_chars_incl_spaces():
    rule = ConstraintRule(
        rule_id="L-016", key="max_chars_incl_spaces", value=17_000, enforcement=Enforcement.BINDING,
        rule_text="17,000 English characters including spaces", source_url="https://example.org/gks",
    )
    assert rule.value == 17_000
