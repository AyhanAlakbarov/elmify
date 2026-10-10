"""0018_sweep_home_language fails forward on a database that already holds a
diaspora SweepAngle or SweepRun, unless its backfill runs before the new
CheckConstraint: a pre-existing row has home_language='' (the column's
default), which the constraint then rejects. This migrates a database from
0017 to 0018 through rows written at the 0017 shape and checks the
backfill filled them in, the way `test_every_pre_existing_audit_event_...`
does for funding/0015."""

from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def _targets(executor: MigrationExecutor, selected: dict[str, str]):
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] not in selected]
    targets.extend(selected.items())
    return targets


def _migrate(selected: dict[str, str]):
    executor = MigrationExecutor(connection)
    executor.migrate(_targets(executor, selected))


def _restore_latest() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(_targets(executor, {}))


@pytest.mark.django_db(transaction=True)
def test_a_pre_existing_diaspora_angle_and_run_get_a_home_language_on_migrating() -> None:
    angle_id, run_id = uuid4(), uuid4()
    try:
        _migrate({"research": "0017_merge_20260927_0833"})
        executor = MigrationExecutor(connection)
        SweepAngle = executor.loader.project_state(
            ("research", "0017_merge_20260927_0833")
        ).apps.get_model("research", "SweepAngle")
        SweepRun = executor.loader.project_state(
            ("research", "0017_merge_20260927_0833")
        ).apps.get_model("research", "SweepRun")
        SweepAngle.objects.create(
            id=angle_id, country_code="DE", family="AFFINITY_OR_DIASPORA", language="tr",
            angle="APPLICATION", sample=0, version=1, cycle="2026-2027",
            query="q", written_by="t",
        )
        SweepRun.objects.create(
            id=run_id, country_code="DE", family="AFFINITY_OR_DIASPORA",
            languages=["tr", "en"], rung=4, cycle="2026-2027", started_at="2026-09-27T00:00:00Z",
        )

        _migrate({"research": "0018_sweep_home_language"})

        from apps.research.models import SweepAngle as CurrentSweepAngle
        from apps.research.models import SweepRun as CurrentSweepRun

        assert CurrentSweepAngle.objects.get(id=angle_id).home_language == "tr"
        assert CurrentSweepRun.objects.get(id=run_id).home_language == "tr"
    finally:
        from apps.research.models import SweepAngle as CurrentSweepAngle
        from apps.research.models import SweepRun as CurrentSweepRun

        CurrentSweepAngle.objects.filter(id=angle_id).delete()
        CurrentSweepRun.objects.filter(id=run_id).delete()
        _restore_latest()
