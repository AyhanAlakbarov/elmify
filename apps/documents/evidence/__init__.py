"""Turn artefacts a student already has into facts in the shared ledger."""

from .intake import EvidenceRateLimited, IntakeResult, Outcome, ingest_evidence

__all__ = ["EvidenceRateLimited", "IntakeResult", "Outcome", "ingest_evidence"]
