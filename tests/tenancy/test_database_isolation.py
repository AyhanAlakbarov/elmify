from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from django.apps import apps
from django.db import IntegrityError, connection
from psycopg import sql

from apps.tenancy.models import TenantScopedModel

#: The `runtime_connection` fixture moved to tests/conftest.py (2026-09-23) so
#: packages other than this one can verify a policy against a NOBYPASSRLS role.
#: This constant stays because the table-owner test below mints its own role.
_RUNTIME_PASSWORD = "test-runtime-password"

_SHARED_TABLES = (
    "funding_institution",
    "funding_program",
    "funding_fundingopportunity",
    "funding_fundingbenefit",
    "funding_costcomponent",
    "funding_benefitrule",
    "funding_officialsource",
    "funding_officialevidenceclaim",
    "funding_institution_evidence_claims",
    "funding_program_evidence_claims",
    "funding_program_awarding_institutions",
    "funding_fundingopportunity_programs",
    "funding_fundingopportunity_evidence_claims",
    "funding_fundingbenefit_evidence_claims",
    "funding_costcomponent_evidence_claims",
    "funding_benefitrule_evidence_claims",
    "funding_catalogrule",
    "funding_programstatement",
    "funding_applicationprompt",
    # The Organisation register (research/0003). Hosts and organisations, never
    # a person -- which is what lets every tenant read them.
    "research_organisation",
    "research_organisationdomain",
    "research_organisationidentifier",
    # The fetch engine's memory and its trail (research/0004, 0005). Which rung
    # reads a ministry's website is the same fact for every tenant, and a host
    # is not a person.
    "research_hostprofile",
    "research_fetchattempt",
    # The closed-list denominator (research/0007). What a public register
    # prints about a body, minus its e-mail; never a person.
    "research_registerentry",
    # The funnel's search ledger (research/0008, 0009). Which pages a
    # university publishes about a programme is the same fact for every
    # tenant, and no student data is ever in one of these rows.
    "research_sitejobrecord",
    # The closed-list registry and EMJM partner bindings (research/0010).
    # A list's URL and terms, an organisation's PIC and website -- never a
    # person.
    "research_closedlist",
    "research_registerentrypartner",
    # The decision layer's answers and cache (research/0021, 0022). A label on a
    # public page's sentence is the same fact for every tenant; no state ever
    # carries student data.
    "research_decisionrecord",
    # The institution provenance gate's verdict tables (research/0019). Whether
    # a body may reach a student is the same fact for every tenant, never a
    # person.
    "research_provenanceverdict",
    "research_provenanceverdictchange",
    # The sweep harness (research/0012). Which query found which host, and
    # what an angle said -- facts about the web, never a person; the angle
    # generator's input has no field a student fact could travel in.
    "research_sweepangle",
    "research_sweeprun",
    "research_sweepquery",
    "research_sweepdiscovery",
    # The bounded cell-sweep queue (demand cells, build item 14): an area
    # (country, family), its demand count and its pass's cost -- no tenant, no
    # student and no count below the area.
    "research_areasweep",
    # Cycle verification (funding engine item 11). Whether an award's money is
    # there for an intake is the same fact for every tenant; the row describes
    # a page and a scheme, never a person.
    "funding_fundingcycleverification",
    # Which page replaced which (research/0014, 0015), written by the
    # resolution applier when an operator pastes a moved page. A URL pair,
    # never a person.
    "research_movedpage",
)
_TASK7_TABLES = (*_SHARED_TABLES, "tenancy_agencydatauseagreementversion")

#: Platform-only (the third RLS case, research/0013_resolution_item_rls):
#: outside tenant RLS, readable and updatable only when app.tenant_id is the
#: platform agency (research_platformagency), written by runtime_engine and the
#: owner. Never in _SHARED_TABLES -- shared_catalog_select would show the queue
#: to every agency, which spec 2026-09-22 decision 26 forbids -- and not a
#: catalogue table either, so runtime_web keeps its default DML grant and the
#: policy is the gate (tests/research/resolution/test_rls.py proves it as that
#: role). research_platformagency itself is in neither list: it holds one
#: agency id and no RLS; its guard is a GRANT (SELECT only, for both runtime
#: roles), pinned in the same module.
_PLATFORM_TABLES = ("research_resolutionitem", "research_golditem")

_PLATFORM_PREDICATE_FRAGMENT = "research_platformagency"


@pytest.mark.django_db
def test_platform_tables_have_exactly_the_platform_policies() -> None:
    with connection.cursor() as cursor:
        for table in _PLATFORM_TABLES:
            assert table not in _SHARED_TABLES
            cursor.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass",
                [f"public.{table}"],
            )
            assert cursor.fetchone() == (True, False)
            cursor.execute(
                "SELECT policyname, cmd, roles::text FROM pg_policies"
                " WHERE schemaname = 'public' AND tablename = %s ORDER BY policyname",
                [table],
            )
            assert cursor.fetchall() == [
                ("platform_operator_select", "SELECT", "{public}"),
                ("platform_operator_update", "UPDATE", "{public}"),
                ("runtime_engine_write", "ALL", "{runtime_engine}"),
            ]
            cursor.execute(
                "SELECT qual, with_check FROM pg_policies WHERE tablename = %s"
                " AND policyname LIKE 'platform_operator_%%'",
                [table],
            )
            for qual, with_check in cursor.fetchall():
                assert _PLATFORM_PREDICATE_FRAGMENT in qual
                assert "app.tenant_id" in qual
                assert with_check in (None, qual)
            cursor.execute(
                "SELECT qual, with_check FROM pg_policies WHERE tablename = %s"
                " AND policyname = 'runtime_engine_write'",
                [table],
            )
            assert cursor.fetchone() == ("true", "true")


def test_runtime_role_bootstrap_is_fail_closed() -> None:
    """Two roles, runtime_engine and runtime_web, each put through the same
    fail-closed shape the single `runtime` role used to get -- from one VALUES
    list, so the two cannot drift apart. The role names are literal
    (2026-09-25 catalog-read-split design), not a psql variable. Table and
    sequence grants are NOT here: funding/0049_catalog_grants owns them, where
    a test can see them; this script keeps only what needs the database name."""
    bootstrap = (Path(__file__).parents[2] / "scripts" / "create_runtime_role.sql").read_text()

    for clause in (
        r"\if :{?migration_role}",
        "BEGIN;",
        "BEFORE the first `migrate`",
        "runtime_roles_administrable",
        "rolsuper OR rolcreatedb OR rolreplication OR rolbypassrls",
        "CONNECTION LIMIT -1",
        "VALID UNTIL ''infinity''",
        "ALTER ROLE %I RESET ALL",
        "IN DATABASE %I RESET ALL",
        "pg_auth_members",
        "GRANTED BY %I CASCADE",
        "runtime_memberships_cleared",
        "relrowsecurity",
        "RAISE EXCEPTION",
        "rolname NOT IN ('runtime_engine', 'runtime_web')",
        "GRANT CONNECT ON DATABASE %I TO %I",
        "COMMIT;",
    ):
        assert clause in bootstrap, clause
    assert "runtime_password" not in bootstrap
    assert bootstrap.count("FROM (VALUES ('runtime_engine'), ('runtime_web')) AS role(name)") == 6
    for role in ("runtime_engine", "runtime_web"):
        assert f"\\password {role}" in bootstrap
    # funding/0049_catalog_grants's own GRANT USAGE ON SCHEMA public only
    # works when the runner owns the schema (dev/test/CI superuser); in
    # production the migration role does not, so this is the grant that
    # actually reaches runtime_engine/runtime_web -- it must run before COMMIT.
    assert "GRANT USAGE ON SCHEMA public TO %I" in bootstrap
    assert bootstrap.index("GRANT USAGE ON SCHEMA public TO %I") < bootstrap.index("COMMIT;")
    statements = "\n".join(
        line for line in bootstrap.splitlines() if not line.lstrip().startswith("--")
    )
    assert "GRANT SELECT" not in statements
    assert "ALTER DEFAULT PRIVILEGES" not in statements
    assert "GRANT runtime_engine" not in statements
    # PG 17 lets only a holder change these, even to NO: setting them would
    # make the script superuser-only, so they are asserted instead.
    alter = bootstrap[bootstrap.index("ALTER ROLE %I WITH LOGIN") :]
    alter = alter[: alter.index("\\gexec")]
    for attribute in ("NOSUPERUSER", "NOCREATEDB", "NOREPLICATION", "NOBYPASSRLS"):
        assert attribute not in alter, attribute

    transaction = bootstrap[bootstrap.index("BEGIN;") : bootstrap.index("COMMIT;")]
    assert "CREATE ROLE %I" in transaction
    # The migration-role guard runs before any role is touched, and the
    # memberships are revoked before they are asserted cleared.
    assert transaction.index("migration_role_is_constrained") < transaction.index(
        "CREATE ROLE %I"
    )
    assert transaction.index("GRANTED BY %I CASCADE") < transaction.index(
        "runtime_memberships_cleared"
    )
    # PG16+: only a role holding ADMIN OPTION may ALTER a role, so whether the
    # running admin can is checked after the create and before the first ALTER.
    assert (
        transaction.index("CREATE ROLE %I")
        < transaction.index("runtime_roles_administrable")
        < transaction.index("ALTER ROLE %I WITH LOGIN")
        < transaction.index("runtime_attributes_constrained")
    )


@pytest.mark.django_db(transaction=True)
def test_runtime_connection_uses_restricted_non_owner_login(runtime_connection) -> None:
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        assert cursor.fetchone() == (runtime_connection.info.user,)

        cursor.execute(
            """
            SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                   rolinherit, rolreplication, rolbypassrls, rolconnlimit,
                   rolvaliduntil IS NULL OR rolvaliduntil > now()
            FROM pg_roles
            WHERE rolname = current_user
            """
        )
        assert cursor.fetchone() == (
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            -1,
            True,
        )

        cursor.execute(
            """
            SELECT count(*)
            FROM pg_class
            WHERE relrowsecurity
              AND relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
            """
        )
        assert cursor.fetchone() == (0,)


@pytest.mark.django_db(transaction=True)
def test_rls_denies_when_setting_is_absent(runtime_connection, membership_a) -> None:
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM tenancy_membership")
        assert cursor.fetchone() == (0,)


@pytest.mark.django_db(transaction=True)
def test_set_local_expires_after_commit(runtime_connection, agency_a) -> None:
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(agency_a.id)])

    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.tenant_id', true)")
        assert cursor.fetchone()[0] in (None, "")


@pytest.mark.django_db(transaction=True)
def test_runtime_role_sees_only_selected_tenant(
    runtime_connection, agency_a, membership_a, membership_b
) -> None:
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(agency_a.id)])
        cursor.execute("SELECT id FROM tenancy_membership")
        assert cursor.fetchall() == [(membership_a.id,)]


@pytest.mark.django_db(transaction=True)
def test_composite_foreign_key_rejects_cross_tenant_pair(agency_a, membership_b) -> None:
    with connection.cursor() as cursor:
        try:
            cursor.execute(
                """
            CREATE TABLE assignment_probe (
                tenant_id uuid NOT NULL,
                membership_id uuid NOT NULL,
                FOREIGN KEY (tenant_id, membership_id)
                    REFERENCES tenancy_membership (tenant_id, id)
            )
            """
            )
            with pytest.raises(IntegrityError):
                cursor.execute(
                    "INSERT INTO assignment_probe VALUES (%s, %s)",
                    [agency_a.id, membership_b.id],
                )
        finally:
            cursor.execute("DROP TABLE IF EXISTS assignment_probe")


def _grant_task7_runtime_dml(runtime_connection) -> None:
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        for table in _TASK7_TABLES:
            cursor.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}").format(
                    sql.Identifier("public", table), role
                )
            )


@pytest.fixture
def shared_institution(db):
    from apps.funding.models import Institution

    return Institution.objects.create(
        canonical_key="rls:institution",
        name="RLS University",
        country_code="AZ",
        official_website="https://university.example.test",
    )


@pytest.fixture
def data_use_agreement(agency_a, membership_a):
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import AgencyDataUseAgreementVersion

    with tenant_scope(agency_a.id):
        return AgencyDataUseAgreementVersion.objects.create(
            agreement_id=uuid4(),
            version=1,
            agreement_reference="RLS-DPA",
            permitted_purposes=["EVALUATION"],
            eligible_categories=["STRUCTURED_PROFILE_FACTS"],
            lawful_basis_review_state="NOT_REVIEWED",
            effective_at=__import__("django.utils.timezone", fromlist=["now"]).now(),
            created_by=membership_a,
        )


@pytest.mark.django_db(transaction=True)
def test_shared_catalog_is_readable_in_every_tenant_context(
    runtime_connection, shared_institution, agency_a, agency_b
) -> None:
    _grant_task7_runtime_dml(runtime_connection)
    for tenant_id in (None, agency_a.id, agency_b.id):
        with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
            if tenant_id is not None:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
            cursor.execute("SELECT id FROM public.funding_institution")
            assert cursor.fetchall() == [(shared_institution.id,)]


@pytest.mark.django_db(transaction=True)
def test_shared_catalog_runtime_dml_is_denied_by_rls(
    runtime_connection, shared_institution
) -> None:
    _grant_task7_runtime_dml(runtime_connection)
    with runtime_connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                """
                INSERT INTO public.funding_institution
                    (id, canonical_key, name, country_code, official_website)
                VALUES (%s, 'runtime:denied', 'Denied', 'AZ', 'https://example.test')
                """,
                [uuid4()],
            )
        cursor.execute(
            "UPDATE public.funding_institution SET name = 'changed' WHERE id = %s",
            [shared_institution.id],
        )
        assert cursor.rowcount == 0
        cursor.execute(
            "DELETE FROM public.funding_institution WHERE id = %s",
            [shared_institution.id],
        )
        assert cursor.rowcount == 0
    from apps.funding.models import Institution

    assert Institution.objects.get(id=shared_institution.id).name == "RLS University"


@pytest.mark.django_db(transaction=True)
def test_ordinary_table_owner_can_seed_shared_catalog_and_only_insert_agreement(
    django_db_blocker, agency_a, membership_a
) -> None:
    owner_name = f"task7_owner_{uuid4().hex}"
    owner = sql.Identifier(owner_name)
    catalog_table = sql.Identifier("public", "funding_institution")
    agreement_table = sql.Identifier("public", "tenancy_agencydatauseagreementversion")
    owner_connection = None
    role_created = False
    owned_tables: list[sql.Identifier] = []
    catalog_id = uuid4()
    agreement_id = uuid4()
    try:
        with django_db_blocker.unblock(), connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                ).format(owner),
                [_RUNTIME_PASSWORD],
            )
            role_created = True
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(str(connection.settings_dict["NAME"])), owner
                )
            )
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(owner))
            cursor.execute(sql.SQL("ALTER TABLE {} OWNER TO {}").format(catalog_table, owner))
            owned_tables.append(catalog_table)
            cursor.execute(sql.SQL("ALTER TABLE {} OWNER TO {}").format(agreement_table, owner))
            owned_tables.append(agreement_table)
        owner_connection = psycopg.connect(
            dbname=connection.settings_dict["NAME"],
            user=owner_name,
            password=_RUNTIME_PASSWORD,
            host=connection.settings_dict["HOST"],
            port=connection.settings_dict["PORT"],
            autocommit=True,
        )
        with owner_connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.funding_institution
                    (id, canonical_key, name, country_code, official_website)
                VALUES (%s, 'owner:seed', 'Owner Seed', 'AZ', 'https://example.test')
                """,
                [catalog_id],
            )
            cursor.execute(
                """
                INSERT INTO public.tenancy_agencydatauseagreementversion
                    (id, tenant_id, agreement_id, version, agreement_reference,
                     permitted_purposes, eligible_categories,
                     lawful_basis_review_state, effective_at, created_by_id, created_at)
                VALUES (%s, %s, %s, 1, 'owner', '["EVALUATION"]'::jsonb,
                        '["STRUCTURED_PROFILE_FACTS"]'::jsonb, 'NOT_REVIEWED',
                        now(), %s, now())
                """,
                [uuid4(), agency_a.id, agreement_id, membership_a.id],
            )
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
                cursor.execute(
                    "UPDATE public.tenancy_agencydatauseagreementversion "
                    "SET agreement_reference = 'changed' WHERE agreement_id = %s",
                    [agreement_id],
                )
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
                cursor.execute(
                    "DELETE FROM public.tenancy_agencydatauseagreementversion "
                    "WHERE agreement_id = %s",
                    [agreement_id],
                )
    finally:
        if owner_connection is not None:
            owner_connection.close()
        if role_created:
            with django_db_blocker.unblock(), connection.cursor() as cursor:
                for table in reversed(owned_tables):
                    cursor.execute(sql.SQL("ALTER TABLE {} OWNER TO CURRENT_USER").format(table))
                cursor.execute(sql.SQL("DROP OWNED BY {}").format(owner))
                cursor.execute(sql.SQL("DROP ROLE {}").format(owner))


@pytest.mark.django_db(transaction=True)
def test_task7_rls_policy_shapes_and_runtime_acl(runtime_connection) -> None:
    _grant_task7_runtime_dml(runtime_connection)
    with connection.cursor() as cursor:
        for table in _SHARED_TABLES:
            cursor.execute(
                """
                SELECT relrowsecurity, relforcerowsecurity
                  FROM pg_class
                 WHERE oid = %s::regclass
                """,
                [f"public.{table}"],
            )
            assert cursor.fetchone() == (True, False)
            cursor.execute(
                """
                SELECT policyname, cmd, roles::text, qual, with_check
                  FROM pg_policies
                 WHERE schemaname = 'public' AND tablename = %s
                 ORDER BY policyname
                """,
                [table],
            )
            # Task 9 (0006_official_snapshots) added the write policy alongside
            # Task 7's read policy; funding/0049_catalog_grants repointed it from
            # catalog_ingestion to runtime_engine. Only the engine may write the
            # shared catalog -- and runtime_web holds no table grant on it at all
            # (tests/tenancy/test_catalog_grants.py), so the read policy's
            # PUBLIC reaches only roles that also hold the grant.
            assert cursor.fetchall() == [
                ("runtime_engine_write", "ALL", "{runtime_engine}", "true", "true"),
                ("shared_catalog_select", "SELECT", "{public}", "true", None),
            ]
        cursor.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
              FROM pg_class
             WHERE oid = 'public.tenancy_agencydatauseagreementversion'::regclass
            """
        )
        assert cursor.fetchone() == (True, False)
        cursor.execute(
            """
            SELECT policyname, cmd, permissive, qual, with_check
              FROM pg_policies
             WHERE schemaname = 'public'
               AND tablename = 'tenancy_agencydatauseagreementversion'
            """
        )
        policies = cursor.fetchall()
        assert len(policies) == 1
        name, command, permissive, qualifier, with_check = policies[0]
        assert (name, command, permissive) == (
            "agreement_tenant_select",
            "SELECT",
            "PERMISSIVE",
        )
        assert qualifier is not None
        assert with_check is None
        for table in _TASK7_TABLES:
            cursor.execute(
                """
                SELECT has_table_privilege(%s, %s, 'TRUNCATE'),
                       has_table_privilege(%s, %s, 'REFERENCES'),
                       has_table_privilege(%s, %s, 'TRIGGER')
                """,
                [runtime_connection.info.user, f"public.{table}"] * 3,
            )
            assert cursor.fetchone() == (False, False, False)
    with runtime_connection.cursor() as cursor, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cursor.execute("TRUNCATE public.funding_institution")


@pytest.mark.django_db(transaction=True)
def test_agreement_runtime_rls_is_select_only_and_tenant_scoped(
    runtime_connection, data_use_agreement, agency_a, agency_b, membership_a
) -> None:
    _grant_task7_runtime_dml(runtime_connection)
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT id FROM public.tenancy_agencydatauseagreementversion")
        assert cursor.fetchall() == []
    for tenant_id, expected in (
        (agency_a.id, [(data_use_agreement.id,)]),
        (agency_b.id, []),
    ):
        with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
            cursor.execute("SELECT id FROM public.tenancy_agencydatauseagreementversion")
            assert cursor.fetchall() == expected
            cursor.execute(
                "UPDATE public.tenancy_agencydatauseagreementversion "
                "SET agreement_reference = 'x' WHERE id = %s",
                [data_use_agreement.id],
            )
            assert cursor.rowcount == 0
            cursor.execute(
                "DELETE FROM public.tenancy_agencydatauseagreementversion WHERE id = %s",
                [data_use_agreement.id],
            )
            assert cursor.rowcount == 0
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(agency_a.id)])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                """
                INSERT INTO public.tenancy_agencydatauseagreementversion
                    (id, tenant_id, agreement_id, version, agreement_reference,
                     permitted_purposes, eligible_categories,
                     lawful_basis_review_state, effective_at, created_by_id, created_at)
                VALUES (%s, %s, %s, 2, 'runtime', '["EVALUATION"]'::jsonb,
                        '["STRUCTURED_PROFILE_FACTS"]'::jsonb, 'NOT_REVIEWED',
                        now(), %s, now())
                """,
                [uuid4(), agency_a.id, uuid4(), membership_a.id],
            )


@pytest.mark.django_db(transaction=True)
def test_legacy_evidence_remains_tenant_isolated_and_candidate_linked(
    runtime_connection, agency_a, agency_b, membership_a, membership_b
) -> None:
    from django.utils import timezone

    from apps.accounts.models import StudentProfileVersion
    from apps.funding.models import EvidenceClaim, RecommendationCandidate, RecommendationRun
    from apps.tenancy.context import tenant_scope

    rows = []
    for agency, membership, suffix in (
        (agency_a, membership_a, "a"),
        (agency_b, membership_b, "b"),
    ):
        with tenant_scope(agency.id):
            profile = StudentProfileVersion.objects.create(
                student=membership, version=1, snapshot={}
            )
            run = RecommendationRun.objects.create(profile_version=profile)
            evidence = EvidenceClaim.objects.create(
                source_url=f"https://official.example.test/{suffix}",
                claim=f"Legacy claim {suffix}",
                last_checked_at=timezone.now(),
            )
            candidate = RecommendationCandidate.objects.create(
                run=run,
                evidence=evidence,
                program_name=f"Legacy program {suffix}",
                funding_gap="0.00",
                currency="EUR",
                eligible=True,
            )
            rows.append((agency.id, evidence.id, candidate.id))
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT ON TABLE public.funding_evidenceclaim TO {}").format(role)
        )
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT id FROM public.funding_evidenceclaim")
        assert cursor.fetchall() == []
    for tenant_id, evidence_id, candidate_id in rows:
        with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
            cursor.execute("SELECT id FROM public.funding_evidenceclaim")
            assert cursor.fetchall() == [(evidence_id,)]
        with tenant_scope(tenant_id):
            assert RecommendationCandidate.objects.get(id=candidate_id).evidence_id == evidence_id


# tenancy_agencydatauseagreementversion deliberately runs ENABLE without FORCE:
# it's a shared, SELECT-only-for-runtime catalog table whose only writers are
# owner-level migration SQL (see apps/tenancy/migrations/0004_data_use_agreement.py
# and the pinned shape assertions in test_task7_rls_policy_shapes_and_runtime_acl
# above). FORCE is intentionally omitted so the owning role can still write it.
_RLS_ENABLED_NOT_FORCED_EXEMPTIONS = frozenset({"tenancy_agencydatauseagreementversion"})


@pytest.mark.django_db
def test_every_tenant_scoped_model_has_rls_enabled_and_forced() -> None:
    """Regression guard: every TenantScopedModel table must have RLS enabled and
    forced (except the documented exemptions above). This is the cheap check that
    would have caught tenancy_counselorassignment and funding_evaluationexample
    shipping without RLS."""
    tenant_scoped_tables = sorted(
        model._meta.db_table
        for model in apps.get_models()
        if issubclass(model, TenantScopedModel) and not model._meta.abstract
    )
    assert tenant_scoped_tables, "expected at least one TenantScopedModel subclass"
    with connection.cursor() as cursor:
        for table in tenant_scoped_tables:
            cursor.execute(
                """
                SELECT relrowsecurity, relforcerowsecurity
                  FROM pg_class
                 WHERE oid = %s::regclass
                """,
                [f"public.{table}"],
            )
            row = cursor.fetchone()
            assert row is not None, f"table {table} not found"
            expected = (True, table not in _RLS_ENABLED_NOT_FORCED_EXEMPTIONS)
            assert row == expected, (
                f"{table} must have RLS ENABLE/FORCE = {expected}, got {row}"
            )
