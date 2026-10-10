# tests/migrations/test_documents_tenant_guards.py
import pytest
from django.db import connection

_RLS_TABLES = (
    "documents_verifiedfact",
    "documents_documentdraft",
    "documents_documentdraftfact",
    "documents_revisionrequest",
    "documents_consentevent",
    "documents_europassrendercache",
    "documents_narrativeinput",
    "funding_constraintoverride",
    "documents_transcriptupload",
    "documents_transcriptpage",
)

_COMPOSITE_FKS = {
    "documents_verifiedfact": {
        "verifiedfact_student_tenant_fk",
        "verifiedfact_created_by_tenant_fk",
        "verifiedfact_confirmed_by_tenant_fk",
        "verifiedfact_supersedes_tenant_fk",
    },
    "documents_documentdraft": {
        "documentdraft_student_tenant_fk",
        "documentdraft_approved_by_tenant_fk",
        "documentdraft_derived_from_tenant_fk",
    },
    "documents_narrativeinput": {
        "narrativeinput_student_tenant_fk",
    },
    "documents_documentdraftfact": {
        "documentdraftfact_document_tenant_fk",
        "documentdraftfact_fact_tenant_fk",
    },
    "documents_revisionrequest": {
        "revisionrequest_document_tenant_fk",
        "revisionrequest_requested_by_tenant_fk",
        "revisionrequest_resulting_draft_tenant_fk",
        "revisionrequest_superseding_fact_tenant_fk",
    },
    "documents_consentevent": {
        "consentevent_document_tenant_fk",
        "consentevent_granted_by_tenant_fk",
    },
    "documents_transcriptupload": {
        "transcriptupload_student_tenant_fk",
        "transcriptupload_cycle_tenant_fk",
        "transcriptupload_document_tenant_fk",
    },
    "documents_transcriptpage": {
        "transcriptpage_student_tenant_fk",
        "transcriptpage_cycle_tenant_fk",
        "transcriptpage_upload_tenant_fk",
    },
    "documents_transcriptreading": {
        "transcriptreading_student_tenant_fk",
        "transcriptreading_document_tenant_fk",
        "transcriptreading_cycle_tenant_fk",
    },
    "funding_constraintoverride": {
        "constraintoverride_student_tenant_fk",
        "constraintoverride_decided_by_tenant_fk",
    },
}


@pytest.mark.django_db
@pytest.mark.parametrize("table", _RLS_TABLES)
def test_table_forces_row_level_security_with_a_tenant_policy(table):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = %s::regclass",
            [f"public.{table}"],
        )
        assert cursor.fetchone() == (True, True)
        cursor.execute(
            "SELECT polname FROM pg_policy WHERE polrelid = %s::regclass",
            [f"public.{table}"],
        )
        assert {row[0] for row in cursor.fetchall()} == {"tenant_isolation"}


@pytest.mark.django_db
@pytest.mark.parametrize(("table", "expected"), sorted(_COMPOSITE_FKS.items()))
def test_composite_tenant_foreign_keys_exist(table, expected):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = %s::regclass AND contype = 'f'",
            [f"public.{table}"],
        )
        names = {row[0] for row in cursor.fetchall()}
    assert expected <= names, f"missing on {table}: {sorted(expected - names)}"
