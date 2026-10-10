"""The catalogue grant surface, asserted as the roles that hold it.

`runtime_web` (the agency-facing web tier) holds no privilege on any
shared-catalogue table; `runtime_engine` (workers) reads and writes them. Every
assertion that a role can or cannot do something connects AS that role
(through a disposable member of it): the default test role is a superuser and
bypasses grants and RLS alike, so nothing it does proves a grant.
"""

import ast
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from django.apps import apps as django_apps

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.conftest import catalogue_tables
from tests.tenancy.test_database_isolation import _PLATFORM_TABLES

_DML = ("SELECT", "INSERT", "UPDATE", "DELETE")


def test_the_catalogue_is_not_empty_and_names_the_corpus(db_cursor) -> None:
    tables = catalogue_tables(db_cursor)
    assert tables, "no shared_catalog_select policies found -- the query is wrong"
    assert "funding_program" in tables and "funding_fundingopportunity" in tables


def test_an_agency_connection_cannot_read_the_catalogue(role_connection, db_cursor) -> None:
    """The requirement, asserted at the layer that enforces it. Not 'sees no
    rows' -- `permission denied`, because an absent GRANT fails closed and a
    policy that returns zero rows is indistinguishable from an empty table."""
    tables = catalogue_tables(db_cursor)
    with role_connection("runtime_web") as conn:
        for table in tables:
            with conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(f"SELECT 1 FROM {table} LIMIT 1")


def test_the_engine_connection_can_read_the_catalogue(role_connection, db_cursor) -> None:
    tables = catalogue_tables(db_cursor)
    with role_connection("runtime_engine") as conn, conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT 1 FROM {table} LIMIT 1")  # must not raise


def test_every_catalogue_table_is_revoked_from_web_and_granted_to_engine(db_cursor) -> None:
    """The guard for the NEXT catalogue table. Default privileges grant every
    new table to both roles, because tenant tables need that; so a migration
    that adds a catalogue table fails here until it also revokes it from
    runtime_web. `has_table_privilege` on the superuser connection is honest
    here: it evaluates the NAMED role's privileges, not the caller's."""
    for table in catalogue_tables(db_cursor):
        for privilege in _DML:
            db_cursor.execute(
                "SELECT has_table_privilege('runtime_web', %s, %s), "
                "has_table_privilege('runtime_engine', %s, %s)",
                [f"public.{table}", privilege] * 2,
            )
            assert db_cursor.fetchone() == (False, True), (table, privilege)


def test_no_catalogue_sequence_is_usable_by_web(db_cursor) -> None:
    db_cursor.execute(
        """
        SELECT sequence.oid::regclass::text
          FROM pg_class AS sequence
          JOIN pg_depend AS dep
            ON dep.objid = sequence.oid
           AND dep.classid = 'pg_class'::regclass
           AND dep.refclassid = 'pg_class'::regclass
          JOIN pg_class AS owner ON owner.oid = dep.refobjid
         WHERE sequence.relkind = 'S' AND owner.relname = ANY(%s)
        """,
        [catalogue_tables(db_cursor)],
    )
    for (sequence,) in db_cursor.fetchall():
        db_cursor.execute(
            "SELECT has_sequence_privilege('runtime_web', %s, 'USAGE'), "
            "has_sequence_privilege('runtime_web', %s, 'SELECT')",
            [sequence, sequence],
        )
        assert db_cursor.fetchone() == (False, False), sequence


def test_the_web_role_holds_no_membership_of_the_engine_role(db_cursor) -> None:
    """SET ROLE does not need inherited attributes. Membership would make the
    boundary a discipline instead of a boundary -- the erasure-guard lesson.
    Asked of pg_auth_members directly, and transitively via pg_has_role."""
    db_cursor.execute(
        """
        SELECT count(*) FROM pg_auth_members AS m
          JOIN pg_roles AS granted ON granted.oid = m.roleid
          JOIN pg_roles AS member ON member.oid = m.member
         WHERE member.rolname = 'runtime_web'
        """
    )
    assert db_cursor.fetchone() == (0,), "runtime_web holds a role membership"
    db_cursor.execute("SELECT pg_has_role('runtime_web', 'runtime_engine', 'MEMBER')")
    assert db_cursor.fetchone() == (False,), (
        "runtime_web is a member of runtime_engine -- SET ROLE makes the "
        "boundary a discipline instead of a boundary"
    )


def test_the_catalogue_writer_is_the_engine_and_nothing_names_catalog_ingestion(
    db_cursor,
) -> None:
    """Every write policy now targets runtime_engine, with its command
    unchanged, and this database holds no reference to the dropped role --
    whether or not the cluster still has it (another database may)."""
    db_cursor.execute(
        """
        SELECT tablename, cmd FROM pg_policies
         WHERE schemaname = 'public' AND policyname = 'runtime_engine_write'
           AND roles = '{runtime_engine}'
        """
    )
    writers = dict(db_cursor.fetchall())
    # The platform-only queue (research_resolutionitem) is written by the
    # engine too -- its writers and applier run as runtime_engine -- but it is
    # NOT catalogue: it carries no shared_catalog_select (every agency would
    # read the queue) and runtime_web keeps its grant, because the platform's
    # console runs as runtime_web behind the platform-only policies.
    assert set(writers) == set(catalogue_tables(db_cursor)) | set(_PLATFORM_TABLES)
    assert not set(_PLATFORM_TABLES) & set(catalogue_tables(db_cursor))
    assert writers.pop("funding_officialsourcesnapshot") == "INSERT"
    assert set(writers.values()) == {"ALL"}

    db_cursor.execute(
        """
        SELECT count(*) FROM pg_policies
         WHERE policyname LIKE '%%catalog_ingestion%%'
            OR 'catalog_ingestion' = ANY(roles)
        """
    )
    assert db_cursor.fetchone() == (0,)
    db_cursor.execute(
        """
        SELECT count(*) FROM pg_shdepend AS dep
          JOIN pg_roles AS role ON role.oid = dep.refobjid
         WHERE role.rolname = 'catalog_ingestion'
           AND dep.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
        """
    )
    assert db_cursor.fetchone() == (0,)


@pytest.fixture
def web_world(
    agency_a, membership_a, counselor_membership, program_factory
) -> dict[str, object]:
    """Everything the web views read, written as the superuser BEFORE
    ``web_role_orm`` swaps the connection (it is requested after this). Each
    catalogue FK is populated -- the candidates', the drafts', the
    application's -- because a NULL FK joins nothing and would prove nothing."""
    from apps.documents.models import DocumentDraft
    from apps.funding.models import RecommendationCandidate
    from apps.tenancy.models import CounselorAssignment
    from tests.documents.test_api import _candidate, _draft_for, _education_candidate
    from tests.funding.conftest import make_db_candidate, make_published_pack, make_run
    from tests.portals.test_kit_view import _application

    program = program_factory()
    run = make_run(agency_a, membership_a)
    chosen = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    considered = make_db_candidate(agency_a, run, program_name="MSc Physics")
    draft = _draft_for(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        # What `approve` and `generate` check before they enqueue: confirmed
        # identity and education facts, and an application e-mail.
        for fact in (_candidate(membership_a), _education_candidate(membership_a)):
            fact.confirmed_by = membership_a
            fact.confirmed_at = fact.created_at
            fact.save(update_fields=["confirmed_by", "confirmed_at"])
        membership_a.application_email = "student@mail.example.test"
        membership_a.save(update_fields=["application_email"])
        RecommendationCandidate.objects.filter(id__in=[chosen.id, considered.id]).update(
            program_id=program.id
        )
        make_published_pack(agency_a, run, (chosen,))
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application(agency_a, membership_a)
        application.program_id = program.id
        application.save(update_fields=["program_id"])
        kit_draft = DocumentDraft.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=DocumentDraft.Kind.CV,
            version=2,
            content={},
            status=DocumentDraft.Status.APPROVED,
            programme=program,
            rendered_filename="cv-german-tabular.pdf",
        )
        DocumentDraft.objects.filter(id=draft.id).update(programme=program)
    return {
        "run": run,
        "application": application,
        "kit_draft": kit_draft,
        "draft": draft,
        "program": program,
    }


@pytest.mark.django_db(transaction=True)
def test_a_students_pack_renders_end_to_end_without_the_catalogue(
    client, agency_a, domain_a, user_a, counselor_user, monkeypatch, web_world, web_role_orm
) -> None:
    """§3 claims RecommendationCandidate and EvidenceClaim carry everything an
    agency shows a student. This is that claim under the role that cannot fall
    back to the catalogue if it is wrong: the pack, the counselor's review, the
    kit, the draft endpoint, approving that draft and generating for a
    programme, each through Django's own connection logged in
    as a runtime_web member, so a regression is a real `permission denied`.

    The stand-in templates render nothing (tests/templates/README.md), so the
    lazy querysets the pack hands its template are walked here the way a
    template would. What the real template will traverse is not knowable
    until it exists; this test is where it will fail."""
    from tests.conftest import verify_mfa_session

    client.force_login(user_a)
    pack = client.get("/student/recommendation/", HTTP_HOST=domain_a.host)
    assert pack.status_code == 200
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert [m.candidate.evidence.claim for m in pack.context["pool"]]
        assert [c.evidence.claim for c in pack.context["considered"]]

    application = web_world["application"]
    kit = client.get(f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host)
    assert kit.status_code == 200
    assert [d.draft_id for d in kit.context["kit"].documents] == [web_world["kit_draft"].id]

    draft = web_world["draft"]
    detail = client.get(f"/api/documents/drafts/{draft.id}", HTTP_HOST=domain_a.host)
    assert detail.status_code == 200, detail.content

    import apps.documents.api as documents_api

    queued: list[object] = []
    monkeypatch.setattr(
        documents_api, "enqueue_document_work", lambda message, **_kw: queued.append(message)
    )
    approve = client.post(
        f"/api/documents/drafts/{draft.id}/approve", "{}",
        content_type="application/json", HTTP_HOST=domain_a.host,
    )
    assert approve.status_code == 202, approve.content
    program_id = web_world["program"].id
    generate = client.post(
        "/api/documents/generate",
        json.dumps({"kind": "CV", "programme_id": str(program_id)}),
        content_type="application/json", HTTP_HOST=domain_a.host,
    )
    assert generate.status_code == 202, generate.content
    assert [m.action for m in queued] == ["render", "generate"]
    assert queued[1].programme_id == program_id
    # The pack-membership check's refusal path reads the pack AND the
    # student's applications, all by program_id column -- still no catalogue.
    outside = client.post(
        "/api/documents/generate",
        json.dumps({"kind": "CV", "programme_id": str(uuid4())}),
        content_type="application/json", HTTP_HOST=domain_a.host,
    )
    assert outside.status_code == 400, outside.content
    assert outside.json() == {"error": "programme_not_in_pack"}
    assert len(queued) == 2

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    run = web_world["run"]
    review = client.get(f"/counselor/runs/{run.id}/approve/", HTTP_HOST=domain_a.host)
    assert review.status_code == 200
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert [m.candidate.evidence.claim for m in review.context["pool"]]


def test_only_the_engine_can_call_the_erasure_guard(role_connection) -> None:
    """`scripts/create_erasure_guard.sql` (run by the session fixture exactly as
    production's admin runs it) grants EXECUTE to `runtime_engine` alone: the
    worker's `execute_due_erasures` is the one caller. A web connection is
    refused outright, not handed a false answer."""
    with role_connection("runtime_engine") as conn, conn.cursor() as cur:
        cur.execute("SELECT public.user_has_active_membership(0)")
        assert cur.fetchone() == (False,)
    with role_connection("runtime_web") as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("SELECT public.user_has_active_membership(0)")


# --- The static tripwire -----------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
#: The web tier's entry points. Everything they import from apps/ is scanned
#: too, transitively -- worker-only modules are out of it by construction,
#: because nothing a web entry point imports reaches them.
_WEB_ENTRY_POINTS = (
    *sorted(_ROOT.glob("apps/*/views.py")),
    *sorted(_ROOT.glob("apps/*/api.py")),
    _ROOT / "apps" / "portals" / "ext_api.py",
)


def _module_path(dotted: str) -> Path | None:
    base = _ROOT / Path(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imports(path: Path) -> set[Path]:
    package = ".".join(path.relative_to(_ROOT).with_suffix("").parts[:-1])
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = ".".join(package.split(".")[: len(package.split(".")) - node.level + 1])
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            names = [module, *(f"{module}.{alias.name}" for alias in node.names)]
        for name in names:
            if name.startswith("apps.") and (target := _module_path(name)):
                found.add(target)
    return found


def _web_modules() -> set[Path]:
    seen: set[Path] = set()
    pending = [p for p in _WEB_ENTRY_POINTS if p.is_file()]
    while pending:
        path = pending.pop()
        if path in seen or "migrations" in path.parts or "management" in path.parts:
            continue
        seen.add(path)
        pending.extend(_imports(path) - seen)
    return seen


def test_nothing_traverses_a_foreign_key_from_a_tenant_row_into_the_catalogue(
    db_cursor,
) -> None:
    """`select_related("program")` on a RecommendationCandidate would make the
    web tier query a table it has no grant on. Verified absent 2026-09-25; this
    keeps it absent. Same forward-FK hazard CLAUDE.md records for
    TenantManager, one layer down.

    A cheap tripwire, not the proof: it sees only string arguments to
    select_related/prefetch_related in code the web entry points import, and
    matches on field NAME, not on the queryset's model. A lazy attribute
    traversal (`candidate.program.name`) is invisible to it; the end-to-end
    test above, run as runtime_web, is what catches that."""
    catalogue = set(catalogue_tables(db_cursor))
    fk_names = {
        field.name
        for model in django_apps.get_models()
        if model._meta.db_table not in catalogue
        for field in model._meta.get_fields()
        if field.is_relation
        and field.concrete
        and field.related_model is not None
        and field.related_model._meta.db_table in catalogue
    }
    assert {"program", "programme", "opportunity", "funding_opportunity"} <= fk_names

    modules = _web_modules()
    assert _ROOT / "apps" / "portals" / "packets.py" in modules, "import walk is broken"
    offenders = []
    for path in sorted(modules):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("select_related", "prefetch_related")
            ):
                for arg in node.args:
                    if (
                        isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                        and set(arg.value.split("__")) & fk_names
                    ):
                        offenders.append(f"{path.relative_to(_ROOT)}:{node.lineno} {arg.value}")
    assert not offenders, offenders

