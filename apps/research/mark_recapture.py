"""Nonparametric species-richness (Chao1/Chao2), Good-Turing sample coverage,
and Chapman mark-recapture estimators for scale-invariant discovery stopping.

References:
- Chao (1984), Scand. J. Stat. 11(4):265-270 (bias-corrected Chao1).
- Chao (1987), Biometrics 43(4):783-791 (Chao2 incidence estimator).
- Good (1953), Biometrika 40(3-4):237-264 (Good-Turing sample coverage).
- Chapman (1951), Univ. Calif. Publ. Stat. 1:131-160 (mark-recapture).
- Chao & Colwell (2017), SORT 41(1):3-54 (coverage-standardized stopping).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class RichnessEstimate:
    """Unseen-species and sample-coverage summary for a cell or country."""

    s_obs: int
    n_sightings: int
    f1: int
    f2: int
    s_hat_chao1: float
    unseen_chao1: float
    coverage_chao1: float
    coverage_good_turing: float
    missing_mass_gt: float
    m_register: int = 0
    c_sweep: int = 0
    r_recaptured: int = 0
    n_hat_chapman: float | None = None
    var_chapman: float | None = None
    coverage_chapman: float | None = None

    @property
    def s_hat(self) -> float:
        return self.s_hat_chao1

    @property
    def chapman_hat(self) -> float | None:
        return self.n_hat_chapman

    @property
    def chapman_coverage(self) -> float | None:
        return self.coverage_chapman

    @property
    def effective_coverage(self) -> float:
        """Conservative scale-invariant coverage in [0, 1].

        Combines Chao1 completeness with Good-Turing sample coverage (and
        Chapman dual-frame coverage when a register denominator is present)
        so an uncorroborated singleton sample (f1 == n -> C_GT == 0) never
        masquerades as 100% coverage, while a small country (S = 1..3) whose
        institutions are corroborated (f1 == 0) reaches 1.0 immediately.
        """
        if self.s_obs <= 0 or self.n_sightings <= 0:
            if self.coverage_chapman is not None and self.r_recaptured > 0:
                return self.coverage_chapman
            return 0.0
        base = min(self.coverage_chao1, self.coverage_good_turing)
        if self.coverage_chapman is not None:
            return max(base, min(self.coverage_chapman, self.coverage_good_turing))
        return base


def chao2_incidence_richness(
    s_obs: int, q1: int, q2: int, n_units: int = 0, *, t_units: int | None = None
) -> float:
    """Bias-corrected Chao2 incidence richness across n_units queries/providers (Chao 1987).

    S_hat_Chao2 = S_obs + ((T - 1) / T) * Q1 * (Q1 - 1) / (2 * (Q2 + 1))
    """
    if s_obs <= 0:
        return 0.0
    units = t_units if t_units is not None else n_units
    if units <= 1:
        return float(s_obs)
    q1_pos = max(0, int(q1))
    q2_pos = max(0, int(q2))
    scale = (units - 1.0) / float(units)
    if q2_pos > 0:
        unseen = scale * (q1_pos * q1_pos) / (2.0 * q2_pos)
    else:
        unseen = scale * (q1_pos * (q1_pos - 1)) / 2.0
    return float(s_obs) + unseen


def chao1_richness(s_obs: int, f1: int, f2: int) -> float:
    """Bias-corrected Chao1 richness estimator (Chao 1984; Chao & Colwell 2017).

    Uses classic f1^2 / (2 * f2) when f2 > 0 and bias-corrected f1 * (f1 - 1) / 2 when f2 == 0.
    Satisfies S_hat_Chao1 >= S_obs for all non-negative integers f1, f2.
    """
    if s_obs <= 0:
        return 0.0
    f1_pos = max(0, int(f1))
    f2_pos = max(0, int(f2))
    if f2_pos > 0:
        unseen = (f1_pos * f1_pos) / (2.0 * f2_pos)
    else:
        unseen = (f1_pos * (f1_pos - 1)) / 2.0
    return float(s_obs) + unseen


def chao1_coverage(s_obs: int, f1: int, f2: int) -> float:
    """Scale-invariant Chao1 completeness ratio S_obs / S_hat_Chao1 in (0, 1]."""
    if s_obs <= 0:
        return 0.0
    s_hat = chao1_richness(s_obs, f1, f2)
    if s_hat <= 0.0:
        return 0.0
    return min(1.0, max(0.0, float(s_obs) / s_hat))


def good_turing_coverage(f1: int, n_total: int, f2: int = 0) -> float:
    """Good-Turing sample coverage C_hat_GT in [0, 1] (Good 1953; Chao & Jost 2012).

    Uses the Turing-Chao improved coverage estimator when f2 > 0:
        C_hat = 1 - (f1 / n) * ((n - 1) * f1 / ((n - 1) * f1 + 2 * f2))
    which reduces to 1 - f1 / n when f2 == 0 or n <= 1.
    Satisfies C_hat == 0 when f1 == n (all observations are singletons)
    and C_hat == 1 when f1 == 0 and n >= 1.
    """
    if n_total <= 0:
        return 0.0
    f1_clamped = min(max(0, int(f1)), int(n_total))
    f2_pos = max(0, int(f2))
    if f1_clamped == 0:
        return 1.0
    if f1_clamped >= n_total:
        return 0.0
    if n_total > 1 and f2_pos > 0:
        denom = (n_total - 1) * f1_clamped + 2.0 * f2_pos
        correction = ((n_total - 1) * f1_clamped) / denom if denom > 0 else 1.0
        missing = (f1_clamped / float(n_total)) * correction
    else:
        missing = f1_clamped / float(n_total)
    return min(1.0, max(0.0, 1.0 - missing))


def chapman_estimator(
    m_register: int, c_sweep: int, r_recaptured: int
) -> tuple[float, float]:
    """Chapman (1951) bias-corrected mark-recapture population & variance estimator.

    Args:
        m_register: M >= 0 known entities in authoritative register.
        c_sweep: C >= 0 distinct entities captured in open-web sweep (novel + recaptured).
        r_recaptured: R in [0, min(M, C)] register entities re-discovered in sweep.

    Returns:
        (n_hat_chapman, var_chapman) satisfying:
        n_hat_chapman - (M + C - R) = (M - R)*(C - R)/(R + 1) >= 0.
    """
    m = max(0, int(m_register))
    c = max(0, int(c_sweep))
    r = min(max(0, int(r_recaptured)), min(m, c))
    if m == 0 or c == 0:
        return float(m + c), 0.0
    n_hat = ((m + 1.0) * (c + 1.0)) / (r + 1.0) - 1.0
    var_hat = (
        (m + 1.0)
        * (c + 1.0)
        * (m - r)
        * (c - r)
        / (((r + 1.0) ** 2) * (r + 2.0))
    )
    return n_hat, var_hat


def chapman_coverage(
    m_register: int, c_sweep: int, r_recaptured: int
) -> float | None:
    """Dual-frame coverage |M union C| / N_hat_Chapman in (0, 1]."""
    m = max(0, int(m_register))
    c = max(0, int(c_sweep))
    r = min(max(0, int(r_recaptured)), min(m, c))
    if m <= 0 or c <= 0:
        return None
    union_known = m + c - r
    n_hat, _ = chapman_estimator(m, c, r)
    if n_hat <= 0.0:
        return None
    return min(1.0, max(0.0, float(union_known) / n_hat))


def estimate_from_sightings(
    sighting_counts: Iterable[int],
    *,
    n_units: int = 0,
    m_register: int = 0,
    r_recaptured: int = 0,
) -> RichnessEstimate:
    """Build a RichnessEstimate from per-entity sighting/incidence counts."""
    counts = [int(c) for c in sighting_counts if int(c) > 0]
    s_obs = len(counts)
    n_sightings = sum(counts)
    freq = Counter(counts)
    f1 = freq.get(1, 0)
    f2 = freq.get(2, 0)

    if n_units > 1:
        s_hat = chao2_incidence_richness(s_obs, f1, f2, n_units)
    else:
        s_hat = chao1_richness(s_obs, f1, f2)

    cov_chao1 = (float(s_obs) / s_hat) if s_hat > 0 else 0.0
    cov_gt = good_turing_coverage(f1, n_sightings, f2=f2)

    r_clamped = max(0, int(r_recaptured))
    # If sighting_counts already includes recaptured hosts, c_sweep is at least s_obs;
    # otherwise c_sweep is novel observed + recaptured.
    c_sweep = max(s_obs, r_clamped) if s_obs >= r_clamped > 0 else s_obs + r_clamped
    n_chap: float | None = None
    v_chap: float | None = None
    cov_chap: float | None = None
    if m_register > 0 and c_sweep > 0:
        n_chap, v_chap = chapman_estimator(m_register, c_sweep, r_clamped)
        cov_chap = chapman_coverage(m_register, c_sweep, r_clamped)

    return RichnessEstimate(
        s_obs=s_obs,
        n_sightings=n_sightings,
        f1=f1,
        f2=f2,
        s_hat_chao1=s_hat,
        unseen_chao1=max(0.0, s_hat - s_obs),
        coverage_chao1=cov_chao1,
        coverage_good_turing=cov_gt,
        missing_mass_gt=1.0 - cov_gt,
        m_register=max(0, int(m_register)),
        c_sweep=c_sweep,
        r_recaptured=r_clamped,
        n_hat_chapman=n_chap,
        var_chapman=v_chap,
        coverage_chapman=cov_chap,
    )
