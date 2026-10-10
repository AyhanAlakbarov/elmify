"""RLS and grants on DecisionRecord, verified through roles that cannot bypass them.

CLAUDE.md: the test role is a superuser and bypasses grants and RLS alike, so a
test that uses it proves nothing. The read goes through `runtime_connection` (a
NOBYPASSRLS login with SELECT everywhere). The write goes through
`role_connection`, as a member of `runtime_engine` (allowed by
`runtime_engine_write`) and of `runtime_web` (refused by the missing table
grant) -- `runtime_connection` is a member of neither, so a refusal there
would prove nothing about who may write.
"""

from uuid import uuid4

import psycopg
import pytest
from django.db import IntegrityError

from apps.research.models import DecisionRecord

pytestmark = pytest.mark.django_db

_FIELDS = dict(
    state_digest="a" * 64, question_digest="b" * 64, decision="D6",
    question_id="document", value="cv", confidence=0.97,
    probabilities={"cv": 0.97, "motivation_letter": 0.03},
    model="typesafe/jev-1.13", served_model="typesafe/jev-1.13-20260917",
    provider="typesafe", language="en", input_tokens=120,
)

_INSERT = (
    "INSERT INTO research_decisionrecord "
    "(id, state_digest, question_digest, decision, question_id, value, confidence, "
    " probabilities, model, served_model, provider, language, input_tokens, refused, "
    " created_at) "
    "VALUES (gen_random_uuid(), repeat('a', 64), repeat('b', 64), 'D6', 'q', 'cv', 0.9, "
    "'{}', 'typesafe/jev-1.13', '', 'typesafe', 'en', 1, false, now())"
)


@pytest.mark.django_db(transaction=True)
def test_a_record_is_readable_by_every_tenant(runtime_connection):
    """`transaction=True`: `runtime_connection` is a second, real connection, so
    the row must be committed on Django's connection before it can see it."""
    DecisionRecord.objects.create(**_FIELDS)
    with runtime_connection.cursor() as cursor:
        for _ in range(2):
            cursor.execute("SELECT set_config('app.tenant_id', %s, false)", [str(uuid4())])
            cursor.execute("SELECT count(*) FROM research_decisionrecord")
            assert cursor.fetchone()[0] == 1


@pytest.mark.django_db(transaction=True)
def test_only_the_engine_can_write_one_and_the_web_cannot_even_read(role_connection):
    """The engine's INSERT succeeding shows the web refusal is about the ROLE,
    not a malformed row. The web refusal is the table grant (`permission denied
    for table`), never a policy returning zero rows -- CLAUDE.md: the catalogue
    boundary is a GRANT. `transaction=True` because these connections
    autocommit; the flush after the test removes the row."""
    with role_connection("runtime_engine") as conn, conn.cursor() as cursor:
        cursor.execute(_INSERT)
        assert cursor.rowcount == 1

    with role_connection("runtime_web") as conn:
        for statement in (_INSERT, "SELECT 1 FROM research_decisionrecord LIMIT 1"):
            with conn.cursor() as cursor:
                with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
                    cursor.execute(statement)
                assert "permission denied for table research_decisionrecord" in str(
                    refused.value
                )


def test_the_digest_pair_is_unique_per_model():
    """The row is the cache (spec §9a): the same state and question set under the
    same model answer once. Two rows would make the cache a coin flip."""
    DecisionRecord.objects.create(**_FIELDS)
    with pytest.raises(IntegrityError, match="unique|duplicate"):
        DecisionRecord.objects.create(**_FIELDS)


def test_a_different_model_is_a_different_cache_entry():
    """The uniqueness is per model, not just per state/question -- a pin change
    must be able to write its own row beside the old one (review focus 4)."""
    DecisionRecord.objects.create(**_FIELDS)
    DecisionRecord.objects.create(**{**_FIELDS, "model": "typesafe/jev-1.14"})
    assert DecisionRecord.objects.count() == 2


def test_it_is_in_the_shared_tables_list():
    """A shared-catalog table absent from this list is one the isolation test
    never checks -- which is how a table ends up with no policy at all."""
    from tests.tenancy.test_database_isolation import _SHARED_TABLES

    assert "research_decisionrecord" in _SHARED_TABLES
