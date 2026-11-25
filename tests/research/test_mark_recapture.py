"""Unit tests for nonparametric mark-recapture richness and unseen-species estimators."""

from __future__ import annotations

import pytest

from apps.research.mark_recapture import (
    chao1_coverage,
    chao1_richness,
    chao2_incidence_richness,
    chapman_coverage,
    chapman_estimator,
    estimate_from_sightings,
    good_turing_coverage,
)


def test_chao1_richness_zero_singletons_equals_observed_count() -> None:
    """When f1 == 0, all observed species have been seen >= 2 times so S_hat == S_obs."""
    assert chao1_richness(s_obs=12, f1=0, f2=5) == 12.0
    assert chao1_coverage(s_obs=12, f1=0, f2=5) == 1.0


def test_chao1_richness_bias_corrected_when_f2_is_zero() -> None:
    """When f2 == 0 and f1 > 0, bias-corrected Chao1 adds f1*(f1-1)/2 instead of dividing by 0."""
    # s_obs = 5, f1 = 5, f2 = 0 -> 5 + 5*4/2 = 15.0
    assert chao1_richness(s_obs=5, f1=5, f2=0) == pytest.approx(15.0)
    assert chao1_coverage(s_obs=5, f1=5, f2=0) == pytest.approx(5.0 / 15.0)


def test_chao1_richness_classic_formula_when_f2_positive() -> None:
    """When f2 > 0, classic Chao1 adds f1^2 / (2 * f2)."""
    # s_obs = 10, f1 = 4, f2 = 2 -> 10 + 16 / 4 = 14.0
    assert chao1_richness(s_obs=10, f1=4, f2=2) == pytest.approx(14.0)
    assert chao1_coverage(s_obs=10, f1=4, f2=2) == pytest.approx(10.0 / 14.0)


def test_chao2_incidence_richness_finite_sample_correction() -> None:
    """Chao2 scales the unseen term by (T - 1) / T for T sampling units."""
    # s_obs = 10, q1 = 4, q2 = 2, t_units = 10 -> 10 + 0.9 * (16 / 4) = 13.6
    assert chao2_incidence_richness(s_obs=10, q1=4, q2=2, t_units=10) == pytest.approx(13.6)
    # Single unit (T=1) adds 0 unseen species
    assert chao2_incidence_richness(s_obs=3, q1=3, q2=0, t_units=1) == pytest.approx(3.0)


def test_good_turing_coverage_all_singletons_is_zero() -> None:
    """Lakatosian boundary: when every sighting is a singleton (f1 == n), coverage is 0.0."""
    assert good_turing_coverage(f1=1, n_total=1, f2=0) == 0.0
    assert good_turing_coverage(f1=5, n_total=5, f2=0) == 0.0


def test_good_turing_coverage_chao_jost_improved_formula() -> None:
    """Chao & Jost (2012) Turing-inspired coverage with f1 and f2."""
    # No singletons -> 100% sample coverage
    assert good_turing_coverage(f1=0, n_total=20, f2=6) == 1.0
    # f1 = 2, f2 = 1, n = 10 -> 1 - (2/10) * (9*2 / (9*2 + 2*1)) = 1 - 0.2 * (18/20) = 0.82
    assert good_turing_coverage(f1=2, n_total=10, f2=1) == pytest.approx(0.82)


def test_chapman_estimator_and_coverage_invariants() -> None:
    """Chapman dual-frame estimator satisfies N_hat >= M + C - R and equals M when R == C."""
    # Complete recapture: R == C -> N_hat == M and coverage == 1.0
    n_hat_full, var_full = chapman_estimator(m_register=50, c_sweep=15, r_recaptured=15)
    assert n_hat_full == pytest.approx(50.0)
    assert var_full == pytest.approx(0.0)
    assert chapman_coverage(m_register=50, c_sweep=15, r_recaptured=15) == pytest.approx(1.0)

    # Partial overlap: M = 40, C = 20, R = 10 -> (41 * 21) / 11 - 1 = 861/11 - 1 = 77.2727...
    n_hat, var_hat = chapman_estimator(m_register=40, c_sweep=20, r_recaptured=10)
    assert n_hat == pytest.approx((41 * 21) / 11 - 1.0)
    assert n_hat >= 40 + 20 - 10
    assert var_hat > 0.0
    cov = chapman_coverage(m_register=40, c_sweep=20, r_recaptured=10)
    assert cov == pytest.approx(50.0 / n_hat)


def test_estimate_from_sightings_effective_coverage_takes_min_of_chao1_and_gt() -> None:
    """Single-singleton sample (S_obs=1, f1=1, f2=0) has Chao1=1.0 but GT=0.0 -> effective=0.0."""
    single = estimate_from_sightings([1])
    assert single.s_obs == 1
    assert single.f1 == 1
    assert single.coverage_chao1 == 1.0
    assert single.coverage_good_turing == 0.0
    assert single.effective_coverage == 0.0

    # Two species each sighted twice -> f1=0, f2=2 -> both Chao1 and GT are 1.0
    corroborated = estimate_from_sightings([2, 2], n_units=4)
    assert corroborated.s_obs == 2
    assert corroborated.f1 == 0
    assert corroborated.f2 == 2
    assert corroborated.s_hat == 2.0
    assert corroborated.effective_coverage == 1.0
