import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from apps.funding.explanations import draft_explanation
from apps.research.extraction import ExtractedClaims

FIXTURE = Path(__file__).parents[1] / "fixtures" / "model_outputs" / "claims.json"


@dataclass
class FakeResponse:
    output_parsed: object
    id: str = "resp_explanation_123"
    usage: object = field(
        default_factory=lambda: SimpleNamespace(input_tokens=11, output_tokens=9, total_tokens=20)
    )
    output: list[object] | None = None


class FakeResponses:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return self.response


class FakeOpenAI:
    def __init__(self, response: FakeResponse) -> None:
        self.responses = FakeResponses(response)


def claims(confidence: float) -> ExtractedClaims:
    payload = json.loads(FIXTURE.read_text())
    payload["confidence"] = confidence
    return ExtractedClaims.model_validate(payload)


def test_terra_drafts_explanation_for_confident_claims() -> None:
    fake = FakeOpenAI(FakeResponse(output_parsed={"summary": "Funding is available."}))

    result = draft_explanation(claims(0.86), fake)

    assert fake.responses.calls[0]["model"] == "gpt-5.6-terra"
    assert fake.responses.calls[0]["store"] is False
    assert result.draft.summary == "Funding is available."
    assert result.consultant_review_required is False
    assert result.metadata.response_id == "resp_explanation_123"


def test_sol_is_used_only_for_low_confidence_claims() -> None:
    fake = FakeOpenAI(FakeResponse(output_parsed={"summary": "Needs review."}))

    result = draft_explanation(claims(0.42), fake)

    assert fake.responses.calls[0]["model"] == "gpt-5.6-sol"
    assert result.escalation_reason == "low_confidence"


def test_refusal_has_deterministic_consultant_fallback() -> None:
    fake = FakeOpenAI(
        FakeResponse(
            output_parsed=None,
            output=[SimpleNamespace(type="refusal", refusal="unsafe")],
        )
    )

    result = draft_explanation(claims(0.86), fake)

    assert result.draft is None
    assert result.consultant_review_required is True
    assert result.escalation_reason == "model_refusal"


def test_malformed_explanation_has_consultant_fallback() -> None:
    fake = FakeOpenAI(FakeResponse(output_parsed={"unexpected": "field"}))

    result = draft_explanation(claims(0.86), fake)

    assert result.draft is None
    assert result.consultant_review_required is True
    assert result.escalation_reason == "malformed_output"


def test_competitiveness_inputs_never_reach_the_explanation_prompt() -> None:
    """§9: no outcome promises. A model handed '200 awards, 8,000 applicants'
    in a free-text task will state odds, and §3.3 puts every competitiveness
    judgement in evaluation.py, not in a prompt."""
    from apps.research.extraction import CountClaim, ExtractedClaims

    claims = ExtractedClaims(
        confidence=0.86,
        duration_months=24,
        awards_per_cycle=CountClaim(
            value=200, cycle_label="2026 intake", evidence="200 scholarships are awarded."
        ),
        applicants_per_cycle=CountClaim(
            value=8000, cycle_label="2026 intake", evidence="8,000 applications were received."
        ),
        selectivity_signals=("Awarded to exceptional candidates at the top of their cohort.",),
    )
    fake = FakeOpenAI(FakeResponse(output_parsed={"summary": "x", "reasons": ["y"]}))

    draft_explanation(claims, fake)

    prompt = fake.responses.calls[0]["input"][1]["content"]
    assert "8000" not in prompt
    assert "awards_per_cycle" not in prompt
    assert "selectivity_signals" not in prompt
    assert "exceptional candidates" not in prompt
    assert "duration_months" in prompt
