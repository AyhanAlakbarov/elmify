from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PortalMessage(BaseModel):
    """Identifiers only -- never content. The worker reads everything else from
    the database under tenant scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    kind: Literal["prepare_application", "resume_application"]
    tenant_id: UUID
    application_id: UUID
