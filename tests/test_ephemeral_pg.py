"""The throwaway test Postgres (tests/ephemeral_pg.py): when it starts, and that it works."""

import psycopg
import pytest

from tests import ephemeral_pg


@pytest.mark.parametrize(
    ("environ", "installed", "expected"),
    [
        ({}, True, True),  # a worktree with `pixi install` and no database configured
        ({"POSTGRES_HOST": "127.0.0.1"}, True, False),  # CI and docker users keep their server
        ({"ELMIFY_EPHEMERAL_PG": "0"}, True, False),  # explicit opt-out
        ({}, False, False),  # no pixi Postgres: the existing setup, unchanged
    ],
)
def test_wanted(environ, installed, expected, monkeypatch, tmp_path):
    binary = tmp_path / "postgres"
    if installed:
        binary.write_text("")
    monkeypatch.setattr(ephemeral_pg, "BIN", tmp_path)
    assert ephemeral_pg.wanted(environ) is expected


@pytest.mark.skipif(not (ephemeral_pg.BIN / "postgres").exists(), reason="needs `pixi install`")
def test_start_connect_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    pg = ephemeral_pg.start()
    try:
        with psycopg.connect(host=pg.host, port=pg.port, user="elmify", dbname="postgres") as conn:
            assert conn.execute("show server_version").fetchone()[0].startswith("17.")
            assert conn.execute("show unix_socket_directories").fetchone()[0] == ""
    finally:
        pg.stop()
    assert not pg.data.exists()
    # The second start copies the cached template instead of running initdb.
    assert (tmp_path / "cache" / "elmify-pg-template").is_dir()
    ephemeral_pg.start().stop()


@pytest.mark.django_db
def test_session_database_is_the_ephemeral_one_when_wanted():
    """With `pixi install` done and no POSTGRES_HOST, the session's database is the throwaway
    server, not the host's 127.0.0.1:5432 -- the one a sandboxed command cannot reach."""
    from django.db import connection

    if not ephemeral_pg.wanted():
        pytest.skip("this session uses a configured server")
    with connection.cursor() as cursor:
        cursor.execute("show port")
        assert cursor.fetchone()[0] != "5432"
        cursor.execute("show unix_socket_directories")
        assert cursor.fetchone()[0] == ""
