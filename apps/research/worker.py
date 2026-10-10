from collections.abc import Callable

from django.db import transaction

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant

from .schemas import ResearchMessage


def process_research_message(
    message: ResearchMessage, handler: Callable[[ResearchMessage], None]
) -> None:
    with transaction.atomic(), tenant_scope(message.tenant_id):
        set_local_tenant(message.tenant_id)
        handler(message)
