"""Eligibility badge: tri-state mapping and rendered contract.

Deliberately db-free: the mapping is a pure property on an unsaved model
instance, and the badge template renders from that instance directly.
"""

from apps.funding.models import RecommendationCandidate

Status = RecommendationCandidate.EligibilityStatus


def _candidate(*, eligible: bool, confidence: str) -> RecommendationCandidate:
    return RecommendationCandidate(eligible=eligible, evidence_confidence=confidence)


def test_tri_state_mapping_low_is_the_review_threshold():
    # Confirmed product decision: LOW -> review needed, matching the pack
    # approval gate; MEDIUM is accepted there so it is accepted here.
    assert _candidate(eligible=True, confidence="HIGH").eligibility_status == Status.ELIGIBLE
    assert _candidate(eligible=True, confidence="MEDIUM").eligibility_status == Status.ELIGIBLE
    assert (
        _candidate(eligible=True, confidence="LOW").eligibility_status == Status.POSSIBLY_ELIGIBLE
    )
    # Ineligibility wins regardless of confidence.
    for confidence in ("HIGH", "MEDIUM", "LOW"):
        assert (
            _candidate(eligible=False, confidence=confidence).eligibility_status
            == Status.NOT_ELIGIBLE
        )
