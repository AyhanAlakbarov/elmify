"""The worker may record a page's status on its snapshot, and nothing else.

funding/0006 created `funding_officialsourcesnapshot` with an INSERT-only write
policy. Every UPDATE -- `funding_read_at` and `funding_read_cost` from
`discover --funding`, `readability` from `reader` and `pipeline`, and
`retrieval_status` from `poll_monitor_checks` and the Firecrawl webhook -- was
legal SQL matching zero rows. Before the catalog split the funding stamp still
landed, because operators ran as the table owner and the table is ENABLE, not
FORCE, row level security. Under `runtime_engine` it vanished
(docs/superpowers/plans/2026-09-26-snapshot-status-writes.md).

Two halves, both needed:
- GRANT, the boundary: the engine's table-wide UPDATE becomes UPDATE on exactly
  the status and read-stamp columns (`retrieval_status`, `readability`,
  `funding_read_at`, `funding_read_cost`). The archived page, its digests, its
  URL and its dates are evidence and stay non-updatable. A write to them fails
  with `permission denied`, loudly.
- POLICY, the row filter: without an UPDATE policy, RLS hides every row from
  the UPDATE even where the grant allows it.
`runtime_web` holds no privilege on this table (funding/0049) and gets none here.
"""

from django.db import migrations

TABLE = "public.funding_officialsourcesnapshot"
_COLUMNS = "retrieval_status, readability, funding_read_at, funding_read_cost"

FORWARD = f"""
REVOKE UPDATE ON {TABLE} FROM runtime_engine;
GRANT UPDATE ({_COLUMNS}) ON {TABLE} TO runtime_engine;
CREATE POLICY runtime_engine_update ON {TABLE}
    FOR UPDATE TO runtime_engine USING (true) WITH CHECK (true);
"""

REVERSE = f"""
DROP POLICY IF EXISTS runtime_engine_update ON {TABLE};
REVOKE UPDATE ({_COLUMNS}) ON {TABLE} FROM runtime_engine;
GRANT UPDATE ON {TABLE} TO runtime_engine;
"""


class Migration(migrations.Migration):
    dependencies = [("funding", "0066_outcome_calibration_rls")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
