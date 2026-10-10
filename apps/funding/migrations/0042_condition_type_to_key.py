"""Fill `key` from the six pre-vocabulary condition types.

Free today: no code writes a BenefitRule row, so this runs over an empty
table. It is written as a real backfill anyway, because a fixture or a
hand-seeded row is exactly the case a no-op migration would strand.

`condition_type` is never cleared, forward or backward: two constraints
(benefit_rule_condition_type_shape_valid, benefit_rule_comparable_shape_valid)
still require it on every APPLICANT_CONDITION row, and clearing it would make
the row illegal under both.
"""

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

_KEYS = {
    "WORK_EXPERIENCE": ("WORK_EXPERIENCE", "GTE"),
    "AGE_CAP": ("AGE", "LTE"),
    "MEANS_TEST": ("NEED", "LTE"),
    "AFFILIATION": ("AFFINITY", "PRESENT"),
    "LANGUAGE": ("LANGUAGE", "PRESENT"),
    "GUARANTOR": ("GUARANTOR", "PRESENT"),
}


def fill_keys(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    BenefitRule = apps.get_model("funding", "BenefitRule")
    for condition_type, (key, operator) in _KEYS.items():
        BenefitRule.objects.filter(condition_type=condition_type, key="").update(
            key=key, operator=operator
        )


def clear_keys(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    # Mirrors fill_keys's SELECTION, not just its column list: a row is only
    # cleared if it still carries the exact (condition_type, key, operator)
    # triple fill_keys would have written for that condition_type -- never
    # `value`, which fill_keys never wrote either. A plain
    # condition_type__in=_KEYS filter (the first version of this function)
    # blanked every legacy-typed row regardless of who set its key, which wipes
    # a row the forward pass deliberately skipped (one already carrying its own
    # key) -- the fixture/hand-seeded case this migration exists not to strand.
    # This cannot tell such a row apart from one this backfill actually wrote if
    # it happens to carry the identical triple -- unknowable in principle -- but
    # it narrows the blast radius from "every legacy-typed row" to "rows
    # indistinguishable from ones this backfill wrote".
    BenefitRule = apps.get_model("funding", "BenefitRule")
    for condition_type, (key, operator) in _KEYS.items():
        BenefitRule.objects.filter(
            condition_type=condition_type, key=key, operator=operator
        ).update(key="", operator="")


class Migration(migrations.Migration):
    dependencies = [("funding", "0041_eligibility_vocabulary")]
    operations = [migrations.RunPython(fill_keys, clear_keys)]
