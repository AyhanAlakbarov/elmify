"""`GRADE` joins the eligibility vocabulary; `TALENT` goes back to sports/arts.

Owner decision 2026-09-22 (master spec section 17 row 25): two unrelated
conditions were sharing one key, and the rename is free *now* and a data
migration later.

**This migration touches zero rows, and that is structural rather than lucky.**
Nothing in `apps/` or `scripts/` constructs a `BenefitRule` -- the model has no
writer outside its own definition, and the only migration that ever wrote to the
table is `0042_condition_type_to_key`, which fills `key` from rows that would
have had to exist already. So `BenefitRule.objects.count() == 0` in every
environment this chain has ever run in.

Even if it did not: the constraint only WIDENS. `GRADE` is added and `TALENT` is
kept, so no existing row can violate the new check. What a non-empty table would
cost is silent and semantic, not a failed migration -- a row written as `TALENT`
meaning a grade bar would keep its key and quietly become a sports/arts label
that no longer decides anything. That is the cost this rename is being taken
early to avoid, so if this file ever needs re-running against real rows, it needs
a `RunPython` that repoints them and does not have one.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('funding', '0042_condition_type_to_key'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='benefitrule',
            name='benefit_rule_key_valid',
        ),
        migrations.AddConstraint(
            model_name='benefitrule',
            constraint=models.CheckConstraint(condition=models.Q(('key', ''), ('key__in', ('CITIZENSHIP', 'RESIDENCE', 'DESCENT', 'FIELD', 'PRIOR_DEGREE', 'PRIOR_INSTITUTION', 'GRADE', 'TALENT', 'WORK_EXPERIENCE', 'LANGUAGE', 'AGE', 'GENDER', 'NEED', 'REFUGEE_OR_DISPLACED', 'DISABILITY', 'EMPLOYMENT', 'AFFINITY', 'GUARANTOR', 'OPEN', 'OTHER')), _connector='OR'), name='benefit_rule_key_valid'),
        ),
    ]
