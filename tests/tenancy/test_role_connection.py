import pytest


@pytest.mark.django_db(transaction=True)
def test_a_role_connection_is_actually_that_role(role_connection) -> None:
    """The instrument this whole design is verified with. If it silently
    connects as the test superuser, every later assertion is vacuous."""
    with role_connection("runtime_web") as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT current_user, "
            "  (SELECT rolsuper FROM pg_roles WHERE rolname = current_user), "
            "  (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user), "
            "  pg_has_role(current_user, 'runtime_web', 'MEMBER'), "
            "  CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'runtime_engine') "
            "       THEN pg_has_role(current_user, 'runtime_engine', 'MEMBER') "
            "       ELSE false END"
        )
        name, is_super, bypasses, is_web_member, is_engine_member = cur.fetchone()
    assert name.endswith("web") and not is_super and not bypasses
    assert is_web_member is True
    # Vacuous until Task 5's migration creates runtime_engine: the CASE above
    # short-circuits to false whenever the role doesn't exist yet, same as
    # "is not a member" would read.
    assert is_engine_member is False
