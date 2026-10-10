"""RLS on SiteJobRecord, verified through a role that cannot bypass it.

CLAUDE.md: the test role bypasses RLS, so a policy test that uses it proves
nothing. The read goes through `runtime_connection` (a tenant-policy login
with SELECT everywhere); the write goes through `role_connection`, as a member
of `runtime_engine` (allowed) and of `runtime_web` (refused by the missing
table grant), because the write policy names `runtime_engine` and
`runtime_connection` is a member of neither.
"""
from uuid import uuid4

import psycopg
import pytest

from apps.research.models import SiteJobRecord

pytestmark = pytest.mark.django_db


def _row(**overrides):
    fields = dict(
        program_id=uuid4(),
        source_url="https://uni.example.org/msc-ai/",
        admissions_cycle="2027",
        outcome=SiteJobRecord.Outcome.NOT_FOUND,
        stopped_at_stage=4,
        searched={"map": 76, "crawl": 25, "guided_map": 50, "navigator": 4},
        leads=["https://uni.example.org/apply/"],
        credits={"FIRECRAWL": 31, "SCRAPE_DO": 0},
    )
    fields.update(overrides)
    return SiteJobRecord.objects.create(**fields)


@pytest.mark.django_db(transaction=True)
def test_a_record_is_readable_by_every_tenant(runtime_connection):
    """Shared catalog: which pages a university publishes about a programme is
    the same fact for every agency, and no student data is ever in one of
    these rows.

    `transaction=True`: `runtime_connection` is a second, real connection --
    the row it must see has to be committed on the Django connection first,
    which the plain (savepoint-rollback) `django_db` marker never does.
    """
    _row()

    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM research_sitejobrecord")
        assert cursor.fetchone()[0] == 1


_INSERT = (
    "INSERT INTO research_sitejobrecord "
    "(id, program_id, source_url, admissions_cycle, outcome, "
    " stopped_at_stage, searched, leads, credits, reason, created_at) "
    "VALUES (gen_random_uuid(), gen_random_uuid(), 'https://x.example/', "
    "'2027', 'not_found', 4, '{}', '[]', '{}', '', now())"
)


@pytest.mark.django_db(transaction=True)
def test_only_the_engine_can_write_one(role_connection):
    """`runtime_engine` writes (`runtime_engine_write`, renamed from
    `catalog_ingestion_write` by funding/0049); `runtime_web` holds no grant at
    all. Without the refusal, a tenant request could write a programme's search
    record -- a row every other tenant then reads.

    The two halves control each other. The engine's INSERT succeeding is what
    shows the refusal below is about the web ROLE, not a malformed row; and
    the web refusal is the table grant (`permission denied for table`), never a
    policy returning zero rows -- CLAUDE.md: the catalogue boundary is a GRANT.
    Both connect as a member of the fixed role, never the superuser test role,
    which bypasses grants and RLS alike. `transaction=True` because those
    connections autocommit: the flush after the test is what removes the row.
    """
    with role_connection("runtime_engine") as conn, conn.cursor() as cursor:
        cursor.execute(_INSERT)
        assert cursor.rowcount == 1

    with role_connection("runtime_web") as conn, conn.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(_INSERT)
        assert "permission denied for table research_sitejobrecord" in str(refused.value)


def test_the_not_found_row_carries_what_was_searched():
    """Spec 7.6: never a bare label. A `not found` with no record of what was
    searched cannot be acted on by a person or scored by the corpus, and it
    is exactly the row that distinguishes 'no such page' from 'we did not
    look far enough'."""
    row = _row()

    assert row.searched["map"] == 76
    assert row.stopped_at_stage == 4


def test_nothing_waits_on_the_row():
    """Owner decision 2026-09-23. There is no state column, no assignee and no
    resolution: this is a ledger, not a queue. A `state` field here is how
    the pipeline grows a person in it again."""
    field_names = {field.name for field in SiteJobRecord._meta.get_fields()}

    assert "state" not in field_names
    assert "assignee" not in field_names
