import pytest
from django.db import connection

_INSERT = (
    "INSERT INTO privacy_legaldocument"
    " (id, kind, language, version, body, sha256, material, effective_at)"
    " VALUES (gen_random_uuid(), 'terms', 'en', 2, 'x', repeat('a', 64), true, now())"
)
_WRITES = {
    "INSERT": _INSERT,
    "UPDATE": "UPDATE privacy_legaldocument SET body = 'edited'",
    "DELETE": "DELETE FROM privacy_legaldocument",
    # Listed with its referrer: alone, Postgres refuses on the foreign key before
    # the trigger runs, which would test the key rather than the trigger.
    "TRUNCATE": "TRUNCATE privacy_legaldocument, privacy_acceptance",
}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("role", ["runtime_web", "runtime_engine"])
def test_runtime_roles_read_but_never_write_legal_documents(role, role_connection):
    from apps.privacy import documents

    documents.publish("terms", "en", "Terms", material=True)  # as the owner
    with role_connection(role) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM privacy_legaldocument")
        assert cur.fetchone()[0] == 1
        with pytest.raises(Exception, match="permission denied"):
            cur.execute(_INSERT)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("role", ["runtime_web", "runtime_engine"])
@pytest.mark.parametrize("verb", list(_WRITES))
def test_owner_only_trigger_refuses_a_runtime_role_that_was_granted_the_write(
    role, verb, role_connection
):
    """The REVOKE is the first guard; the trigger holds if a later grant undoes it."""
    from apps.privacy import documents

    documents.publish("terms", "en", "Terms", material=True)
    roles = "runtime_web, runtime_engine"
    grants = "INSERT, UPDATE, DELETE, TRUNCATE"
    with connection.cursor() as owner:
        owner.execute(f"GRANT {grants} ON privacy_legaldocument TO {roles}")
        owner.execute(f"GRANT TRUNCATE ON privacy_acceptance TO {roles}")  # see _WRITES
    try:
        with role_connection(role) as conn, conn.cursor() as cur:
            with pytest.raises(Exception, match="only the owner"):
                cur.execute(_WRITES[verb])
    finally:
        with connection.cursor() as owner:
            owner.execute(f"REVOKE {grants} ON privacy_legaldocument FROM {roles}")
            owner.execute(f"REVOKE TRUNCATE ON privacy_acceptance FROM {roles}")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("role", ["runtime_web", "runtime_engine"])
def test_acceptances_are_append_only_for_the_runtime_roles(role, role_connection, membership_a):
    """Consent evidence: the runtime may record and read an acceptance, never change one.

    Erasure redacts only REDACT models and Acceptance is KEEP-only, so no runtime
    path needs to rewrite or remove a row.
    """
    from apps.privacy import acceptance, documents
    from apps.tenancy.context import tenant_scope

    terms, _ = documents.publish("terms", "en", "Terms", material=True)
    notice, _ = documents.publish("privacy_notice_agency", "en", "Notice", material=True)
    with tenant_scope(membership_a.tenant_id):
        acceptance.record(membership_a, [terms], surface="signup", language="en")
    with role_connection(role) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            tenant = str(membership_a.tenant_id)
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", [tenant])
            cur.execute("SELECT count(*) FROM privacy_acceptance")
            assert cur.fetchone()[0] == 1
            cur.execute(
                "INSERT INTO privacy_acceptance (id, tenant_id, student_id, document_id,"
                " accepted_at, surface, language)"
                " VALUES (gen_random_uuid(), %s, %s, %s, now(), 'signup', 'en')",
                [str(membership_a.tenant_id), str(membership_a.id), str(notice.id)],
            )
            for statement in (
                "UPDATE privacy_acceptance SET surface = 'reacceptance'",
                "DELETE FROM privacy_acceptance",
            ):
                with pytest.raises(Exception, match="permission denied"):
                    cur.execute(statement)
            cur.execute("SELECT count(*) FROM privacy_acceptance")
            assert cur.fetchone()[0] == 2
