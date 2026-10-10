from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class ResearchMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    kind: Literal["run_research", "revalidate_source", "check_provenance", "check_named_program"]
    tenant_id: UUID
    run_id: UUID
    source_id: UUID | None = None
    snapshot_id: UUID | None = None
    #: check_provenance only: the run's pending bodies, carried so the worker
    #: checks them without opening a tenant transaction (spec §7.1).
    body_ids: tuple[UUID, ...] = ()
    #: check_named_program only: the named candidate whose verdict the worker
    #: computes and writes back as its tenant copy (spec §7.4).
    candidate_id: UUID | None = None

    @model_validator(mode="after")
    def validate_revalidation_target(self) -> ResearchMessage:
        targets = (self.source_id is not None) + (self.snapshot_id is not None)
        if self.kind == "revalidate_source" and targets != 1:
            raise ValueError("revalidation requires exactly one source or snapshot target")
        if self.kind != "revalidate_source" and targets:
            raise ValueError("only a revalidation carries a revalidation target")
        if (self.kind == "check_provenance") != bool(self.body_ids):
            raise ValueError("body_ids are required by, and only by, check_provenance")
        if (self.kind == "check_named_program") != (self.candidate_id is not None):
            raise ValueError("candidate_id is required by, and only by, check_named_program")
        return self
