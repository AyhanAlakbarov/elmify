"""Phase 1 recommendation-quality benchmark gates (Task 18, Step 1).

All numbers here come from the SYNTHETIC placeholder fixtures under
tests/benchmarks/ (see tests/benchmarks/README.md). A pass proves the
scoring/evaluation pipeline is wired correctly end to end; it is NOT proof
that Phase 1 has passed real recommendation-quality acceptance, which
requires an independent researcher's blinded reference lists and a
consultant's reviewed profiles.
"""

import json
from decimal import Decimal

from scripts.evaluate_phase1 import CITIES_DIR, MIN_PROFILES, PROFILES_DIR, REFERENCES_DIR


def _load_profiles() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(PROFILES_DIR.glob("*.json"))}


def test_benchmark_evidence_is_present_and_of_the_required_shape() -> None:
    profiles = _load_profiles()
    assert len(profiles) >= MIN_PROFILES

    cities = {p.stem for p in CITIES_DIR.glob("*.json")}
    assert len(cities) >= 5

    references = {p.stem for p in REFERENCES_DIR.glob("*.json")}
    assert len(references) >= 5
    assert references <= set(profiles)  # every reference list has a paired profile


def test_precision_recall_official_support_and_lift_meet_threshold(benchmark_scorecard) -> None:
    assert benchmark_scorecard.precision >= Decimal("0.90")
    assert benchmark_scorecard.recall >= Decimal("0.80")
    assert benchmark_scorecard.official_claim_support == Decimal("1")
    assert benchmark_scorecard.unsupported_funding_claims == 0
    assert benchmark_scorecard.verified_funded_lift >= Decimal("0.20")


def test_evaluator_fails_red_with_no_benchmark_evidence(tmp_path, monkeypatch) -> None:
    """Step 2: confirm the evaluator refuses to report success on empty evidence."""
    import scripts.evaluate_phase1 as evaluate_phase1

    empty_profiles = tmp_path / "profiles"
    empty_references = tmp_path / "reference_opportunities"
    empty_cities = tmp_path / "cities"
    for directory in (empty_profiles, empty_references, empty_cities):
        directory.mkdir()

    monkeypatch.setattr(evaluate_phase1, "PROFILES_DIR", empty_profiles)
    monkeypatch.setattr(evaluate_phase1, "REFERENCES_DIR", empty_references)
    monkeypatch.setattr(evaluate_phase1, "CITIES_DIR", empty_cities)

    score, missing, used_synthetic = evaluate_phase1.compute_scorecard()

    assert missing, "empty evidence must be reported as missing, not silently skipped"
    assert not evaluate_phase1.passes(score)


def test_selected_non_english_language_evidence_profile_exists() -> None:
    profiles = _load_profiles()
    non_english = [p for p in profiles.values() if p.get("language") not in (None, "English")]
    assert non_english, "need at least one explicitly selected non-English profile"
    assert any(p["language"] == "German" for p in non_english)


def test_funding_first_trade_off_profile_exists() -> None:
    profiles = _load_profiles()
    funding_first = [p for p in profiles.values() if p.get("strategy") == "FUNDING_FIRST"]
    assert funding_first, "need at least one funding-dependent-strategy profile"

    dedicated = profiles["profile-07"]
    assert dedicated["strategy"] == "FUNDING_FIRST"
    assert dedicated["reason_code"] == "FUNDING_FIRST_TRADEOFF"
    assert dedicated["verified_funded"] is True
    assert "notes" in dedicated and dedicated["notes"]


def test_five_distinct_cities_are_covered_by_the_benchmark() -> None:
    profiles = _load_profiles()
    cities_used = {p["city"] for p in profiles.values()}
    city_fixture_ids = {p.stem for p in CITIES_DIR.glob("*.json")}
    assert len(city_fixture_ids) >= 5
    assert cities_used & city_fixture_ids


def test_city_benefit_rules_have_no_cross_border_transfer_or_capacity_limited_deduction() -> None:
    for path in CITIES_DIR.glob("*.json"):
        city = json.loads(path.read_text())
        for benefit in city.get("benefits", []):
            assert benefit["transferable_to_other_city"] is False
            assert benefit["capacity_limited"] is False
            assert benefit["emergency_support"] is False


def test_paired_one_and_two_year_duration_profiles_exist_and_diverge() -> None:
    profiles = _load_profiles()
    one_year = profiles.get("profile-08")
    two_year = profiles.get("profile-09")
    assert one_year is not None and two_year is not None
    assert one_year["duration_preference"] == "ONE_YEAR"
    assert two_year["duration_preference"] == "TWO_YEAR"
    assert one_year["duration_flexibility"] == "NON_NEGOTIABLE"
    assert two_year["duration_flexibility"] == "NON_NEGOTIABLE"
    # Distinct recommended opportunities: the two durations are not collapsed
    # into the same ranked result.
    assert set(one_year["recommended_opportunity_ids"]).isdisjoint(
        two_year["recommended_opportunity_ids"]
    )


def test_synthetic_fixtures_are_unambiguously_labeled() -> None:
    """Every benchmark fixture must self-identify as SYNTHETIC (Task 18 guardrail)."""
    for directory in (PROFILES_DIR, REFERENCES_DIR, CITIES_DIR):
        for path in directory.glob("*.json"):
            data = json.loads(path.read_text())
            assert data.get("_synthetic") is True, f"{path} is not marked _synthetic"
