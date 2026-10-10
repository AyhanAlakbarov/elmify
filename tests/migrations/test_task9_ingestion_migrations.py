import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


TASK9_TABLES = {
    "funding_officialsourcesnapshot",
}


@pytest.fixture
def task9_schema(db):
    executor = MigrationExecutor(connection)
    non_funding_targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "funding"]
    executor.migrate(non_funding_targets)
    executor = MigrationExecutor(connection)  # fresh executor: graph/state must be recomputed after the first migrate
    executor.migrate([("funding", "0006_official_snapshots")])
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_task9_adds_immutable_official_snapshot_metadata_and_writer_policy(task9_schema) -> None:
    assert TASK9_TABLES <= set(connection.introspection.table_names())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
              FROM pg_class
             WHERE oid = 'public.funding_officialsourcesnapshot'::regclass
            """
        )
        assert cursor.fetchone() == (True, False)
        cursor.execute(
            """
            SELECT polname, polcmd
              FROM pg_policy
             WHERE polrelid = 'public.funding_officialsourcesnapshot'::regclass
             ORDER BY polname
            """
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "shared_catalog_select",
            "catalog_ingestion_write",
        }
        cursor.execute(
            """
            SELECT polname
              FROM pg_policy
             WHERE polrelid = 'public.funding_officialsource'::regclass
            """
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "shared_catalog_select",
            "catalog_ingestion_write",
        }


@pytest.mark.django_db
def test_task9_snapshot_metadata_has_no_response_body_column(task9_schema) -> None:
    columns = {
        column.name
        for column in connection.introspection.get_table_description(
            connection.cursor(), "funding_officialsourcesnapshot"
        )
    }

    assert {"s3_key", "s3_version_id", "sha256", "final_url", "redirect_chain"} <= columns
    assert "body" not in columns
