from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


PRIOR = {
    "accounts": "0002_tenant_guards",
    "tenancy": "0003_agency_branding",
    "funding": "0003_packversion_approved_version_id",
}
LATEST = {
    "accounts": "0003_phase1_profile",
    "tenancy": "0004_data_use_agreement",
    "funding": "0004_phase1_catalog",
}
TASK7_SHARED_TABLES = {
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
    "funding_fundingopportunity_programs",
    "funding_fundingopportunity_evidence_claims",
    "funding_fundingbenefit_evidence_claims",
    "funding_costcomponent_evidence_claims",
    "funding_benefitrule_evidence_claims",
}
TASK7_TABLES = {
    *TASK7_SHARED_TABLES,
    "tenancy_agencydatauseagreementversion",
}
TASK7_FUNCTIONS = {
    "accounts_reject_profile_version_mutation",
    "tenancy_reject_data_use_agreement_mutation",
}
TASK7_TRIGGERS = {
    "accounts_profile_version_immutable",
    "tenancy_data_use_agreement_append_only",
}


def _targets(executor: MigrationExecutor, selected: dict[str, str]):
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] not in selected]
    targets.extend(selected.items())
    return targets


#: research/0022 depends on funding/0049 (it creates the `runtime_engine` role
#: the new table's write policy targets), so leaving `research` unselected --
#: at its own head -- while PRIOR/LATEST hold `funding` at a Task-7-era
#: migration asks the executor for an infeasible mixed forward/backward plan.
#: Pin research at its pre-decision-layer leaf whenever a call also pins
#: `funding`, so this file's Task 7 rollback keeps working; every catalogue
#: table added after funding/0049 will need the same treatment. Never applied
#: when `funding` is absent (a bare `_migrate({})` call must still reach
#: research's true head).
# privacy/0002 also depends on funding/0049 (the owner-only grant), same hazard.
_RESEARCH_PIN = {"research": "0009_site_job_record_rls", "privacy": "0001_initial"}


def _migrate(selected: dict[str, str]):
    executor = MigrationExecutor(connection)
    if "funding" in selected:
        selected = {**_RESEARCH_PIN, **selected}
    targets = _targets(executor, selected)
    executor.migrate(targets)
    return MigrationExecutor(connection), targets


def _restore_latest() -> None:
    """Put every app back at its real head.

    Selecting nothing makes _targets return the graph's own leaf nodes, so
    this cannot drift. The hardcoded map it replaced had: tenancy pinned three
    migrations behind, funding three behind. That was invisible until a later
    migration added a column the fixtures touch, at which point every test
    after the first teardown failed on a column that does not exist.
    """
    executor = MigrationExecutor(connection)
    executor.migrate(_targets(executor, {}))


def _migration_rows() -> set[tuple[str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT app, name
              FROM django_migrations
             WHERE (app, name) IN (
                 ('accounts', '0003_phase1_profile'),
                 ('tenancy', '0004_data_use_agreement'),
                 ('funding', '0004_phase1_catalog')
             )
            """
        )
        return set(cursor.fetchall())


def _assert_task7_schema_present() -> None:
    assert TASK7_TABLES <= set(connection.introspection.table_names())
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(
                cursor, "accounts_studentprofileversion"
            )
        }
        assert "schema_version" in columns
        cursor.execute(
            """
            SELECT conname
              FROM pg_constraint
             WHERE conrelid = 'public.accounts_studentprofileversion'::regclass
               AND conname IN ('profile_version_positive', 'profile_schema_version_valid')
            """
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "profile_version_positive",
            "profile_schema_version_valid",
        }
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE tgname = ANY(%s) AND NOT tgisinternal",
            [list(TASK7_TRIGGERS)],
        )
        assert {row[0] for row in cursor.fetchall()} == TASK7_TRIGGERS
        cursor.execute(
            "SELECT proname FROM pg_proc WHERE proname = ANY(%s)",
            [list(TASK7_FUNCTIONS)],
        )
        assert {row[0] for row in cursor.fetchall()} == TASK7_FUNCTIONS
        cursor.execute(
            "SELECT tablename FROM pg_policies WHERE schemaname = 'public' AND tablename = ANY(%s)",
            [list(TASK7_TABLES)],
        )
        assert {row[0] for row in cursor.fetchall()} == TASK7_TABLES
    assert _migration_rows() == set(LATEST.items())


@pytest.mark.django_db(transaction=True)
def test_task7_forward_preserves_legacy_profiles_evidence_and_packs() -> None:
    try:
        executor, prior_targets = _migrate(PRIOR)
        apps = executor.loader.project_state(prior_targets).apps
        User = apps.get_model("auth", "User")
        Agency = apps.get_model("tenancy", "Agency")
        Membership = apps.get_model("tenancy", "Membership")
        Profile = apps.get_model("accounts", "StudentProfileVersion")
        Evidence = apps.get_model("funding", "EvidenceClaim")
        Run = apps.get_model("funding", "RecommendationRun")
        Candidate = apps.get_model("funding", "RecommendationCandidate")
        Pack = apps.get_model("funding", "PackVersion")

        tenant = Agency._base_manager.create(name="Legacy")
        user = User._base_manager.create(username="legacy")
        member = Membership._base_manager.create(
            tenant_id=tenant.id, user_id=user.id, role="STUDENT", active=True
        )
        profile = Profile._base_manager.create(
            tenant_id=tenant.id, student_id=member.id, version=1, snapshot={}
        )
        evidence = Evidence._base_manager.create(
            tenant_id=tenant.id,
            source_url="https://official.example.test",
            claim="Legacy",
            last_checked_at=timezone.now(),
        )
        run = Run._base_manager.create(tenant_id=tenant.id, profile_version_id=profile.id)
        candidate = Candidate._base_manager.create(
            tenant_id=tenant.id,
            run_id=run.id,
            evidence_id=evidence.id,
            program_name="Legacy program",
            funding_gap="0.00",
            currency="EUR",
            eligible=True,
        )
        pack = Pack._base_manager.create(
            tenant_id=tenant.id,
            run_id=run.id,
            candidate_id=candidate.id,
            version=1,
        )

        executor, latest_targets = _migrate(LATEST)
        apps = executor.loader.project_state(latest_targets).apps
        migrated_profile = apps.get_model("accounts", "StudentProfileVersion")._base_manager.get(
            id=profile.id
        )
        assert migrated_profile.schema_version == 0
        assert (
            apps.get_model("funding", "EvidenceClaim")._base_manager.filter(id=evidence.id).exists()
        )
        assert apps.get_model("funding", "PackVersion")._base_manager.filter(id=pack.id).exists()
    finally:
        _restore_latest()


@pytest.mark.django_db(transaction=True)
def test_old_profile_insert_shape_keeps_database_default_zero(agency_a, membership_a) -> None:
    try:
        _migrate(LATEST)
        profile_id = uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.accounts_studentprofileversion
                    (id, tenant_id, student_id, version, snapshot, created_at)
                VALUES (%s, %s, %s, 1, '{}'::jsonb, now())
                """,
                [profile_id, agency_a.id, membership_a.id],
            )
            cursor.execute(
                "SELECT schema_version FROM public.accounts_studentprofileversion WHERE id = %s",
                [profile_id],
            )
            assert cursor.fetchone() == (0,)
    finally:
        _restore_latest()


@pytest.mark.django_db(transaction=True)
def test_empty_task7_schema_reverses_without_residue() -> None:
    try:
        _migrate(LATEST)
        executor, prior_targets = _migrate(PRIOR)
        tables = set(connection.introspection.table_names())
        assert TASK7_TABLES.isdisjoint(tables)
        with connection.cursor() as cursor:
            columns = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor, "accounts_studentprofileversion"
                )
            }
            cursor.execute(
                """
                SELECT conname
                  FROM pg_constraint
                 WHERE conrelid = 'public.accounts_studentprofileversion'::regclass
                   AND conname IN (
                       'profile_version_positive', 'profile_schema_version_valid'
                   )
                """
            )
            assert cursor.fetchall() == []
            cursor.execute(
                "SELECT tgname FROM pg_trigger WHERE tgname = ANY(%s) AND NOT tgisinternal",
                [list(TASK7_TRIGGERS)],
            )
            assert cursor.fetchall() == []
            cursor.execute(
                "SELECT proname FROM pg_proc WHERE proname = ANY(%s)",
                [list(TASK7_FUNCTIONS)],
            )
            assert cursor.fetchall() == []
            cursor.execute(
                "SELECT tablename FROM pg_policies WHERE schemaname = 'public' "
                "AND tablename = ANY(%s)",
                [list(TASK7_TABLES)],
            )
            assert cursor.fetchall() == []
        assert "schema_version" not in columns
        assert _migration_rows() == set()
        assert executor.loader.project_state(prior_targets).apps.get_model(
            "funding", "EvidenceClaim"
        )
    finally:
        _restore_latest()


@pytest.mark.django_db(transaction=True)
def test_accounts_reverse_allows_schema_zero_history(agency_a, membership_a) -> None:
    try:
        _migrate(LATEST)
        profile_id = uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.accounts_studentprofileversion
                    (id, tenant_id, student_id, version, schema_version, snapshot, created_at)
                VALUES (%s, %s, %s, 1, 0, '{}'::jsonb, now())
                """,
                [profile_id, agency_a.id, membership_a.id],
            )
        _migrate(
            {
                "accounts": PRIOR["accounts"],
                "tenancy": LATEST["tenancy"],
                "funding": LATEST["funding"],
            }
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM public.accounts_studentprofileversion WHERE id = %s",
                [profile_id],
            )
            assert cursor.fetchone() == (profile_id,)
    finally:
        _restore_latest()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["profile", "agreement", "catalog"])
def test_populated_task7_reverse_guards_refuse_unapply(kind, agency_a, membership_a) -> None:
    try:
        _migrate(LATEST)
        row_id = uuid4()
        if kind == "profile":
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.accounts_studentprofileversion
                        (id, tenant_id, student_id, version, schema_version, snapshot, created_at)
                    VALUES (%s, %s, %s, 1, 1, '{"guard": true}'::jsonb, now())
                    """,
                    [row_id, agency_a.id, membership_a.id],
                )
        elif kind == "agreement":
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.tenancy_agencydatauseagreementversion
                        (id, tenant_id, agreement_id, version, agreement_reference,
                         permitted_purposes, eligible_categories,
                         lawful_basis_review_state, effective_at, created_by_id, created_at)
                    VALUES (%s, %s, %s, 1, 'guard', '["EVALUATION"]'::jsonb,
                            '["STRUCTURED_PROFILE_FACTS"]'::jsonb,
                            'NOT_REVIEWED', now(), %s, now())
                    """,
                    [row_id, agency_a.id, uuid4(), membership_a.id],
                )
        else:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.funding_institution
                        (id, canonical_key, name, country_code, official_website)
                    VALUES (%s, 'guard', 'Guard', 'AZ', 'https://example.test')
                    """,
                    [row_id],
                )
        app = {"profile": "accounts", "agreement": "tenancy", "catalog": "funding"}[kind]
        selected = dict(LATEST)
        selected[app] = PRIOR[app]
        with pytest.raises(RuntimeError, match="refus|populated|schema.version.1"):
            _migrate(selected)
        _assert_task7_schema_present()
        query, expected = {
            "profile": (
                "SELECT schema_version, snapshot "
                "FROM public.accounts_studentprofileversion WHERE id = %s",
                (1, '{"guard": true}'),
            ),
            "agreement": (
                "SELECT version, agreement_reference "
                "FROM public.tenancy_agencydatauseagreementversion WHERE id = %s",
                (1, "guard"),
            ),
            "catalog": (
                "SELECT canonical_key, name, country_code "
                "FROM public.funding_institution WHERE id = %s",
                ("guard", "Guard", "AZ"),
            ),
        }[kind]
        with connection.cursor() as cursor:
            cursor.execute(query, [row_id])
            assert cursor.fetchone() == expected
    finally:
        _restore_latest()
