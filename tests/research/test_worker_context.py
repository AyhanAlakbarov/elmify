import pytest
from django.db import connection

from apps.research.schemas import ResearchMessage
from apps.research.worker import process_research_message
from apps.tenancy.context import TenantContextMissing, current_tenant_id


@pytest.mark.django_db(transaction=True)
def test_worker_sets_application_and_database_tenant_context(agency_a) -> None:
    observed = []
    message = ResearchMessage(kind="run_research", tenant_id=agency_a.id, run_id=agency_a.id)

    def handler(_message: ResearchMessage) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.tenant_id', true)")
            observed.append((current_tenant_id(), cursor.fetchone()[0]))

    process_research_message(message, handler)

    assert observed == [(agency_a.id, str(agency_a.id))]
    with pytest.raises(TenantContextMissing):
        current_tenant_id()
