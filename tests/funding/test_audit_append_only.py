"""The audit trail is append-only at the database, not just by convention.

Nothing asserted this before: tests/migrations/test_task7_migrations.py only
checked that the migration *name* existed, so dropping the triggers added in
0011_audit_event_append_only would not have failed a single test.

TRUNCATE is deliberately not covered by a trigger -- FOR EACH ROW triggers
never fire on it, and a statement-level one would break pytest-django's
transaction=True teardown (which truncates every table). The control against
TRUNCATE is the privilege model instead: the runtime role is never granted it.
See test_runtime_role_cannot_truncate_the_audit_trail below.
"""

import pytest
from django.db import connection, transaction
from django.db.utils import ProgrammingError

from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope


@pytest.fixture
def audit_event(agency_a):
    with tenant_scope(agency_a.id):
        return AuditEvent.objects.create(event="probe", object_id=agency_a.id)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE funding_auditevent SET event = 'tampered'",
        "DELETE FROM funding_auditevent",
    ],
)
def test_audit_events_cannot_be_rewritten(agency_a, audit_event, statement) -> None:
    with (
        pytest.raises(ProgrammingError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(statement)

    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_runtime_role_cannot_truncate_the_audit_trail() -> None:
    """funding/0049_catalog_grants grants SELECT/INSERT/UPDATE/DELETE only.

    Postgres never grants TRUNCATE implicitly, so the audit table cannot be
    wiped by the credentials the application actually runs as.
    """
    grants = "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public"
    from pathlib import Path

    migration = (
        Path(__file__).parents[2] / "apps" / "funding" / "migrations" / "0049_catalog_grants.py"
    ).read_text()
    assert grants in migration
    assert "TRUNCATE" not in migration
