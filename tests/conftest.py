from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import boto3
import psycopg
import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from psycopg import sql

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Agency, Membership, TenantDomain
from config.settings.database import database_config


def _connect_as(database_role: str, user: str, password: str) -> psycopg.Connection:
    """Build a `database_config` selection for `database_role` and open it.

    Shared by `role_connection` and `runtime_connection`, which otherwise
    duplicated this same "fill in `database_config(...)["default"]` then
    `psycopg.connect(...)`" block with different credential values.
    """
    selected = database_config(
        {
            "DATABASE_ROLE": database_role,
            "POSTGRES_ENGINE_USER": user,
            "POSTGRES_ENGINE_PASSWORD": password,
            "POSTGRES_WEB_USER": user,
            "POSTGRES_WEB_PASSWORD": password,
            "POSTGRES_DB": str(connection.settings_dict["NAME"]),
            "POSTGRES_HOST": str(connection.settings_dict["HOST"]),
            "POSTGRES_PORT": str(connection.settings_dict["PORT"]),
        },
        require_explicit_role=True,
    )["default"]
    return psycopg.connect(
        dbname=selected["NAME"],
        user=selected["USER"],
        password=selected["PASSWORD"],
        host=selected["HOST"],
        port=selected["PORT"],
        autocommit=True,
    )


def verify_mfa_session(client, user):
    """Confirm a real TOTPDevice and mark the test-client session verified.

    Exercises django-otp's actual session/device machinery (real
    OTPMiddleware + TOTPDevice, not a mocked is_verified()), for staff-role
    tests that need to get past the mandatory MFA gate in
    apps.tenancy.middleware.TenantMembershipMiddleware.
    """
    device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()
    return device


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Run scripts/create_erasure_guard.sql, which production runs as an admin.

    The guard function is not created by a migration -- only a role that already
    has BYPASSRLS may create one with it, and the migration role has neither
    (see the script's own header). The test database migrates as a superuser,
    which can, so running the real script here reproduces the production shape
    and keeps `pytest` on a fresh clone a single command.

    The one thing psql does for this file that psycopg does not: meta-commands,
    which are stripped. The script takes no psql variables, and the
    runtime_engine role it grants to exists by then (funding/0049 creates it).
    """
    script = Path(__file__).resolve().parents[1] / "scripts" / "create_erasure_guard.sql"
    statements = "\n".join(
        line for line in script.read_text().splitlines() if not line.startswith("\\")
    )
    with django_db_blocker.unblock(), connection.cursor() as cursor:
        cursor.execute(statements)
    yield


_PASSWORD = "test-runtime-password"


@pytest.fixture
def rls_enforced_orm(django_db_blocker):
    """Point Django's own default connection at a NOBYPASSRLS role.

    The suite otherwise runs as the test superuser, which is BYPASSRLS, so a
    tenant-scoped read taken outside a ``tenant_transaction`` passes here and
    returns zero rows in production. Two modules need that difference to be
    observable: tests/portals/test_rls_spine.py (lazy FK traversal) and
    tests/audit/test_identity_rls.py (the cross-tenant erasure guard).

    NOT the shape of either production runtime role: LOGIN, NOSUPERUSER,
    NOBYPASSRLS, with DML on EVERY table in the public schema -- the catalogue
    included, which `runtime_web` holds no grant on -- and EXECUTE on every
    function, where production grants the erasure guard to `runtime_engine`
    only. It isolates the one property these tests are about, RLS, and proves
    nothing about grants; for those use ``role_connection`` / ``web_role_orm``,
    which connect as members of the real roles. Swapping ``settings_dict`` and
    reconnecting is what puts the ORM -- managers, FK descriptors, everything --
    behind that role.
    """
    role_name = f"tehsil_rls_{uuid4().hex}"
    role = sql.Identifier(role_name)
    database = sql.Identifier(str(connection.settings_dict["NAME"]))
    with django_db_blocker.unblock(), connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(role),
            [_PASSWORD],
        )
        cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, role))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        cursor.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(role)
        )
        cursor.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
        )
        # The bootstrap's ALTER DEFAULT PRIVILEGES ... GRANT EXECUTE ON FUNCTIONS
        # equivalent: the erasure guard's migration revokes EXECUTE from PUBLIC,
        # so without this the runtime role cannot call it.
        cursor.execute(
            sql.SQL("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {}").format(role)
        )

    try:
        with _orm_logged_in_as(role_name):
            yield role_name
    finally:
        with django_db_blocker.unblock(), connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(role))
            cursor.execute(sql.SQL("DROP ROLE {}").format(role))


@contextmanager
def _orm_logged_in_as(login: str):
    """Swap Django's default connection to ``login`` and back. Swapping
    ``settings_dict`` and reconnecting is what puts the ORM -- managers, FK
    descriptors, everything -- behind that role."""
    saved = (connection.settings_dict["USER"], connection.settings_dict["PASSWORD"])
    connection.close()
    connection.settings_dict["USER"] = login
    connection.settings_dict["PASSWORD"] = _PASSWORD
    try:
        yield
    finally:
        connection.close()
        connection.settings_dict["USER"], connection.settings_dict["PASSWORD"] = saved


@contextmanager
def _member_of(role_name: str, django_db_blocker):
    """A disposable LOGIN role whose only privileges are its membership of the
    fixed, cluster-global ``role_name``. See ``role_connection``."""
    if role_name not in ("runtime_engine", "runtime_web"):
        raise ValueError(f"unexpected role_name {role_name!r}")

    with django_db_blocker.unblock(), connection.cursor() as cursor:
        # DO block, not SELECT-then-CREATE: parallel worktrees' test DBs
        # share this cluster-global role, so a plain existence check races.
        # Two concurrent CREATE ROLEs can also collide on pg_authid's unique
        # index, which raises unique_violation rather than duplicate_object.
        cursor.execute(
            sql.SQL(
                "DO $$ BEGIN CREATE ROLE {} NOLOGIN; "
                "EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL; END $$;"
            ).format(sql.Identifier(role_name))
        )

    throwaway = f"tehsil_test_{uuid4().hex}_{role_name}"
    role = sql.Identifier(throwaway)
    try:
        with django_db_blocker.unblock(), connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE INHERIT NOREPLICATION NOBYPASSRLS"
                ).format(role),
                [_PASSWORD],
            )
            cursor.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(role_name), role))
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(str(connection.settings_dict["NAME"])), role
                )
            )
        yield throwaway
    finally:
        # DROP OWNED BY has no IF EXISTS; guard it so a CREATE ROLE that never
        # succeeded above doesn't make this drop raise and mask the real failure.
        with django_db_blocker.unblock(), connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [throwaway])
            if cursor.fetchone() is not None:
                cursor.execute(sql.SQL("DROP OWNED BY {}").format(role))
            cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(role))


@pytest.fixture
def web_role_orm(django_db_setup, django_db_blocker):
    """Django's default connection, logged in as a member of ``runtime_web``
    and nothing else -- the agency-facing web tier's real surface. A view that
    reaches the catalogue fails here with ``permission denied``, which no
    SQL-text heuristic and no superuser test can show. Request it LAST: rows
    other fixtures write must be committed before the swap, so tests using it
    are ``django_db(transaction=True)``."""
    with _member_of("runtime_web", django_db_blocker) as login, _orm_logged_in_as(login):
        yield login


@pytest.fixture
def engine_role_orm(django_db_setup, django_db_blocker):
    """``web_role_orm``'s sibling for the worker tier: Django's default
    connection as a member of ``runtime_engine`` and nothing else, so a
    catalogue write-back runs behind the real grants and policies it will meet
    in production. Same rules: request it last, ``django_db(transaction=True)``."""
    with _member_of("runtime_engine", django_db_blocker) as login, _orm_logged_in_as(login):
        yield login


@pytest.fixture
def role_connection(django_db_setup, django_db_blocker):
    """Factory fixture: connect as a throwaway role that is a MEMBER of a
    fixed, cluster-global role (``runtime_engine`` / ``runtime_web``).

    This is the instrument later tasks verify GRANTs with, so what it proves
    has to come from the fixed role and nothing else. ``runtime_engine`` and
    ``runtime_web`` are shared by every worktree's test database -- they are
    cluster-global, not per-database -- so this fixture never ALTERs them:
    it only ensures each exists (``CREATE ROLE ... NOLOGIN``, skipped if
    already present -- Task 5's migration does the same ``IF NOT EXISTS``,
    so this is harmless and lets the fixture work before that migration
    lands). Per test, it creates a unique, disposable
    ``tehsil_test_<hex>_<role_name>`` role, ``GRANT``s it membership in the
    fixed role, and connects as the throwaway -- never the fixed role
    itself, and the throwaway gets no table or sequence grants of its own.
    If a query succeeds through this connection, that privilege came from
    the fixed role via membership, exactly as production will hold it.

    Same rule ``runtime_connection`` below is built on: the default test
    connection is a superuser and bypasses grants and RLS alike, so proving
    what a role can or cannot do means literally connecting as that role --
    never the default connection with ``SET ROLE``, which doesn't need role
    attributes to be inherited to work (the erasure-guard ``SET ROLE``
    lesson in CLAUDE.md is exactly this trap one layer up).
    """

    @contextmanager
    def _connect(role_name: str):
        with _member_of(role_name, django_db_blocker) as throwaway:
            with _connect_as(role_name, throwaway, _PASSWORD) as role_database:
                yield role_database

    yield _connect


@pytest.fixture
def db_cursor(django_db_setup, django_db_blocker):
    """A cursor on Django's own default (superuser) connection.

    For READING catalog state only -- ``pg_policies``, ``pg_has_role``,
    ``has_table_privilege`` -- never for proving a grant: this connection is
    a superuser, so it bypasses every GRANT and every RLS policy. Anything
    that must prove a privilege or a policy actually restricts something
    needs ``role_connection``/``runtime_connection`` instead, which connect
    as a real, unprivileged role.
    """
    with django_db_blocker.unblock(), connection.cursor() as cursor:
        yield cursor


@pytest.fixture
def runtime_connection(django_db_setup, django_db_blocker):
    """A second psycopg connection, logged in as a real NOBYPASSRLS role.

    The sibling of ``rls_enforced_orm`` and the sharper of the two: this one is
    raw SQL on its own connection, so a test can set ``app.tenant_id`` by hand
    and watch a policy decide. It lived inside
    tests/tenancy/test_database_isolation.py until 2026-09-23, which made it
    invisible to every other package -- and CLAUDE.md's rule is that RLS is
    verified against a NOBYPASSRLS role or it is not verified at all.

    ``GRANT SELECT ON ALL TABLES`` rather than the one table the isolation suite
    needed, for the same reason: a table absent from the grant is refused at the
    PERMISSION layer, and a test asserting "the policy hid this row" passes
    identically on a permission error. Read is all it gets -- a test that wants
    to prove a WRITE is refused by the policy must grant the DML itself, or its
    refusal proves nothing either.

    Because it is a separate connection, a test using it must be
    ``@pytest.mark.django_db(transaction=True)``: rows written through Django's
    own connection are invisible here until they commit.
    """
    runtime_role = f"tehsil_runtime_test_{uuid4().hex}"
    role = sql.Identifier(runtime_role)
    with django_db_blocker.unblock(), connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(role),
            [_PASSWORD],
        )

    try:
        with django_db_blocker.unblock(), connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(str(connection.settings_dict["NAME"])), role
                )
            )
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cursor.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(role)
            )
            # Without this, a test that grants itself DML on a BigAutoField
            # table and inserts without an explicit id fails on "permission
            # denied for sequence" (42501, InsufficientPrivilege) --
            # indistinguishable from the policy refusing. rls_enforced_orm
            # (below) and the production runtime role
            # (scripts/create_runtime_role.sql) both already grant this.
            cursor.execute(
                sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(
                    role
                )
            )

        runtime_database = None
        try:
            runtime_database = _connect_as("runtime_engine", runtime_role, _PASSWORD)
            yield runtime_database
        finally:
            if runtime_database is not None:
                runtime_database.close()
    finally:
        with django_db_blocker.unblock(), connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(role))
            cursor.execute(sql.SQL("DROP ROLE {}").format(role))


@pytest.fixture
def agency_a(db):
    return Agency.objects.create(
        name="Agency A",
        brand_logo_url="https://assets.example.test/agency-a.svg",
        brand_primary_color="#123456",
    )


@pytest.fixture
def agency_b(db):
    return Agency.objects.create(name="Agency B")


@pytest.fixture
def domain_a(agency_a):
    return TenantDomain.objects.create(
        agency=agency_a, host="a.example.test", verified_at=timezone.now()
    )


@pytest.fixture
def domain_b(agency_b):
    return TenantDomain.objects.create(
        agency=agency_b, host="b.example.test", verified_at=timezone.now()
    )


@pytest.fixture
def unverified_domain(agency_a):
    return TenantDomain.objects.create(agency=agency_a, host="pending.example.test")


@pytest.fixture
def user_a(db):
    return get_user_model().objects.create_user(username="student-a")


@pytest.fixture
def user_b(db):
    return get_user_model().objects.create_user(username="student-b")


@pytest.fixture
def membership_a(agency_a, user_a):
    with tenant_scope(agency_a.id):
        return Membership.objects.create(tenant=agency_a, user=user_a, role=Membership.Role.STUDENT)


@pytest.fixture
def paid_cycle_a(agency_a, membership_a):
    from django.utils import timezone

    from apps.concierge.models import StudentCycle

    with tenant_scope(agency_a.id):
        return StudentCycle.objects.create(
            student=membership_a, academic_year="2026-2027", paid_at=timezone.now()
        )


@pytest.fixture
def membership_b(agency_b, user_b):
    with tenant_scope(agency_b.id):
        return Membership.objects.create(tenant=agency_b, user=user_b, role=Membership.Role.STUDENT)


@pytest.fixture
def counselor_user(db):
    return get_user_model().objects.create_user(username="counselor-a")


@pytest.fixture
def counselor_membership(agency_a, counselor_user):
    with tenant_scope(agency_a.id):
        return Membership.objects.create(
            tenant=agency_a,
            user=counselor_user,
            role=Membership.Role.COUNSELOR,
        )


class FakeObjectStore:
    """In-memory ObjectStore for tests: no real S3 calls."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._versions: dict[str, list[bytes]] = {}

    def put(self, key: str, body: bytes) -> str:
        """Versioned like EvidenceBucket: the Nth put of a key is test-version-N."""
        self._data[key] = body
        self._versions.setdefault(key, []).append(body)
        return f"test-version-{len(self._versions[key])}"

    def get(self, key: str) -> bytes:
        return self._data[key]

    def get_version(self, key: str, version_id: str) -> bytes:
        number = version_id.removeprefix("test-version-")
        versions = self._versions.get(key, [])
        if not number.isdigit() or not 1 <= int(number) <= len(versions):
            raise KeyError(f"{key}@{version_id}")
        return versions[int(number) - 1]


@pytest.fixture
def fake_store():
    return FakeObjectStore()


@pytest.fixture
def slice_driver(
    client,
    domain_a,
    user_a,
    membership_a,
    paid_cycle_a,
    counselor_user,
    counselor_membership,
    monkeypatch,
):
    from apps.research.schemas import ResearchMessage
    from tests.acceptance.helpers import SliceDriver

    queue = []

    def capture_after_commit(message, **_kwargs):
        assert not connection.in_atomic_block
        queue.append(message)

    monkeypatch.setattr(
        "apps.accounts.views.dispatch_recommendation_run",
        lambda *, tenant_id, run_id: capture_after_commit(
            ResearchMessage(kind="run_research", tenant_id=tenant_id, run_id=run_id)
        ),
    )
    return SliceDriver(client, domain_a.host, user_a, queue)


@pytest.fixture
def institution_factory(db):
    """Institution/Program are shared-catalog models (apps.funding), not
    funding-app-internal scaffolding, so this factory lives at the root
    rather than tests/funding/conftest.py -- any test directory can need one
    without pytest's sibling-conftest visibility problem."""

    def _make(**overrides):
        from apps.funding.models import Institution

        fields = {
            "canonical_key": f"inst-{uuid4()}",
            "name": "Example University",
            "country_code": "DE",
            "official_website": "https://university.example.test",
        }
        fields.update(overrides)
        return Institution.objects.create(**fields)

    return _make


@pytest.fixture
def program_factory(db, institution_factory):
    def _make(**overrides):
        from apps.funding.models import Program

        fields = {
            "institution": overrides.pop("institution", None) or institution_factory(),
            "canonical_key": f"prog-{uuid4()}",
            "name": "MSc Computer Science",
            "campus_name": "Main",
            "city": "Berlin",
            "country_code": "DE",
            "location_key": "de:berlin",
            "degree_level": "MASTER",
            "teaching_languages": ["English"],
            "duration_months": 24,
        }
        fields.update(overrides)
        return Program.objects.create(**fields)

    return _make


def pytest_collection_modifyitems(config, items):
    """Skip markup assertions while there is no presentation layer to assert on.

    Keyed on the directory rather than a flag: `templates/` exists again
    (2026-10-04, student dashboard), so these run. The skip stays only as a
    guard for a checkout that lacks the directory.
    """
    if (Path(__file__).resolve().parents[1] / "templates").is_dir():
        return
    skip = pytest.mark.skip(reason="no templates/ yet; rebuild the frontend to run these")
    for item in items:
        if "frontend" in item.keywords:
            item.add_marker(skip)


def catalogue_tables(cursor) -> list[str]:
    """Every table carrying the shared read policy, from the database.

    NOT from grepping migrations: `funding_registerlisting` and
    `funding_institutionidentifier` are named in migration text and were
    dropped with the 2026-09-14 register removal, so a grep over-counts. A
    hardcoded list also goes stale the next time a catalogue table is added,
    which is exactly when this test most needs to be right.
    """
    cursor.execute(
        "SELECT tablename FROM pg_policies "
        "WHERE policyname = 'shared_catalog_select' ORDER BY tablename"
    )
    return [row[0] for row in cursor.fetchall()]


@contextmanager
def reads_no_catalogue():
    """Fail if any SQL sent inside the block names a shared-catalogue table.

    For web-tier code paths, whose role holds no grant on the catalogue.
    Checked on the SQL actually sent rather than by connecting as the web
    role: the test role is a superuser, so only the query text is honest
    evidence, and Postgres refuses a whole query that names an ungranted
    table, whatever rows it would return. Limits: it watches only Django's
    default connection, and matches only quoted table names as Django emits
    them -- raw SQL naming a table unquoted slips past it.
    """
    with CaptureQueriesContext(connection) as captured:
        yield
    with connection.cursor() as cursor:
        catalogue = catalogue_tables(cursor)
    touched = sorted(
        {
            table
            for query in captured.captured_queries
            for table in catalogue
            if f'"{table}"' in query["sql"]
        }
    )
    assert not touched, f"web path read catalogue tables: {touched}"


@pytest.fixture(autouse=True)
def _no_decision_provider_by_accident(request, settings):
    """derive_page_rules asks the decision layer first and falls back to the
    frontier judge only when no key is configured (addendum §2), so a key in a
    developer's environment would turn every read_and_derive test into a paid
    network call. Live tests carry their own marker and keep the real keys."""
    if request.node.get_closest_marker("live"):
        return
    settings.TYPESAFE_API_KEY = ""
    settings.OPENROUTER_API_KEY = ""


#: Every place botocore looks for credentials outside the two files below.
_AWS_CREDENTIAL_VARIABLES = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
)


@pytest.fixture(autouse=True)
def _no_real_aws_credentials(request, monkeypatch):
    """An unfaked boto3 call fails here instead of signing with the developer's
    credentials. A test that commits (``transaction=True``) runs on_commit hooks,
    and several of those enqueue to SQS and swallow the error, so a real signed
    call passed silently. ``live`` and ``aws`` tests need real AWS on purpose.
    The region is left alone: CI has none, and a test that needs one sets it."""
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("aws"):
        return
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    for name in _AWS_CREDENTIAL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    # boto3 caches its default session, credentials included, across tests.
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)


@pytest.fixture(autouse=True)
def _rate_limit_clock_stands_still(monkeypatch):
    """`rate_limited` keys its counter by `time.time() // window_seconds`, so a test that
    sends `limit + 1` requests on the real clock passes only when they all land in one
    window. On a 60 s window (pack commands, concierge messages) a run straddling the
    minute boundary resets the count and the expected 429 never comes -- measured: a
    clock crossing the boundary mid-test fails
    `test_pack_commands_are_rate_limited_per_student` with `302 == 429` every time.

    Only `apps.ratelimit`'s own `time` name is replaced, never the global `time.time`.
    A test that needs the window to move patches `apps.ratelimit.time.time` itself, which
    now sets the attribute on this stand-in."""
    monkeypatch.setattr("apps.ratelimit.time", SimpleNamespace(time=lambda: 1_700_000_000.0))
