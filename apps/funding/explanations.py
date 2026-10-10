from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from django.conf import settings
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.research.extraction import (
    ExtractedClaims,
    ModelMetadata,
    OpenAIClient,
    _has_refusal,
    privacy_safe_identifier,
    response_metadata,
)


class ExplanationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=4_000)
    caveats: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()


#: The only claim fields an explanation is allowed to see. An allowlist, not a
#: denylist: the next field added to ExtractedClaims must be considered here
#: deliberately rather than reaching a student-facing prompt by default.
EXPLAINABLE_FIELDS = frozenset(
    {
        "eligibility",
        "fees",
        "duration_months",
        "teaching_languages",
        "required_documents",
        "benefits",
        "costs",
        "uncertainty",
        "confidence",
    }
)


@dataclass(frozen=True)
class ExplanationResult:
    draft: ExplanationDraft | None
    metadata: ModelMetadata
    consultant_review_required: bool
    escalation_reason: str | None = None


def _fallback(model_id: str, reason: str) -> ExplanationResult:
    return ExplanationResult(
        draft=None,
        metadata=ModelMetadata(
            model_id=model_id,
            schema_version=settings.OPENAI_MODEL_SCHEMA_VERSION,
            response_id=None,
            usage={},
            failure_state=reason,
        ),
        consultant_review_required=True,
        escalation_reason=reason,
    )


def draft_explanation(
    claims: ExtractedClaims, client: OpenAIClient | None = None
) -> ExplanationResult:
    """Explain a recommendation's structured facts. No caller yet.

    Standing constraint for whoever wires it (catalog-read-split spec §11): run
    it in the worker and WRITE the result to a tenant row the web tier then
    reads. Never compute it at render time from catalogue content -- the web
    role (`runtime_web`) holds no grant on the catalogue, so that fails with
    "permission denied".
    """
    low_confidence = claims.confidence < 0.5
    model_id = (
        settings.OPENAI_ESCALATION_MODEL if low_confidence else settings.OPENAI_EXPLANATION_MODEL
    )
    parser: OpenAIClient = client if client is not None else cast(OpenAIClient, OpenAI())
    try:
        response = parser.responses.parse(
            model=model_id,
            input=[
                {
                    "role": "developer",
                    "content": (
                        "Explain only the supplied structured facts. "
                        "Do not invent facts or hidden reasoning."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        claims.model_dump(mode="json", include=set(EXPLAINABLE_FIELDS)),
                        sort_keys=True,
                    ),
                },
            ],
            text_format=ExplanationDraft,
            safety_identifier=privacy_safe_identifier("explanation"),
            max_output_tokens=1_000,
            store=False,
        )
    except Exception:
        return _fallback(model_id, "model_failure")

    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        reason = "model_refusal" if _has_refusal(response) else "malformed_output"
        return _fallback(model_id, reason)
    try:
        draft = (
            parsed
            if isinstance(parsed, ExplanationDraft)
            else ExplanationDraft.model_validate(parsed)
        )
    except ValidationError:
        return _fallback(model_id, "malformed_output")
    return ExplanationResult(
        draft=draft,
        metadata=response_metadata(
            response, model_id=model_id, schema_version=settings.OPENAI_MODEL_SCHEMA_VERSION
        ),
        consultant_review_required=False,
        escalation_reason="low_confidence" if low_confidence else None,
    )
