import pytest

from apps.research.engine_eval.questions import TIERS
from apps.research.engine_eval.score import (
    binom_cdf,
    certify,
    joint,
    learn_bars,
    ltt_bar,
    score_rows,
    sprt,
)

DEADLINE_Q = next(q for q, kind in TIERS.items() if kind == "deadline")


def test_binomial_cdf_matches_a_hand_value():
    assert binom_cdf(0, 300, 0.01) == pytest.approx((0.99) ** 300)


def test_ltt_keeps_the_loosest_bar_whose_test_rejects():
    clean = [(0.99, True)] * 400 + [(0.7, True)] * 50 + [(0.7, False)] * 50
    bar = ltt_bar(clean, delta=0.01)
    assert bar == 0.8


def test_ltt_stops_at_the_first_failure_even_if_a_looser_bar_would_pass():
    # strictest bar has too few items to reject; fixed-sequence testing must stop there
    rows = [(0.995, True)] * 10 + [(0.9, True)] * 1000
    assert ltt_bar(rows, delta=0.01, grid=(0.99, 0.9)) is None


def test_joint_is_the_minimum_and_missing_is_missing():
    assert joint(0.9, 0.97) == 0.9
    assert joint(None, 0.97) is None


def test_certification_needs_the_owners_count_with_zero_errors():
    deadline = certify([("a", True)] * 2995, "deadline")
    assert deadline["certified"] and deadline["needed"] == 2995
    assert not certify([("a", True)] * 2994, "deadline")["certified"]
    money = certify([("a", True)] * 298 + [("b", False)], "money")
    assert not money["certified"] and money["errors"] == 1


def test_sprt_raises_an_alarm_on_a_jump_from_one_to_three_percent():
    outcomes = [i % 25 == 0 for i in range(2000)]   # 4% errors
    assert sprt(outcomes, p0=0.01, p1=0.03) == "alarm"
    assert sprt([False] * 2000, p0=0.01, p1=0.03) == "ok"


def test_binomial_cdf_survives_large_strata():
    for k, n, p in [(500, 1100, 0.01), (1000, 5000, 0.5), (0, 5000, 0.5)]:
        assert 0.0 <= binom_cdf(k, n, p) <= 1.0
    assert binom_cdf(5, 10, 0.0) == 1.0 and binom_cdf(5, 10, 1.0) == 0.0
    assert binom_cdf(10, 10, 0.3) == 1.0
    assert binom_cdf(3, 10, 0.3) == pytest.approx(0.6496107184)


def test_ltt_on_thousands_of_rows_with_many_errors_does_not_overflow():
    rows = [(0.5, i % 4 == 0) for i in range(4200)]
    assert ltt_bar(rows, delta=0.01) is None


def _row(question, truth, jev, second, *, half="score", language="az", evidence=True):
    return {"id": "x", "language": language, "page": "p", "half": half, "question": question,
            "truth": truth, "jev": jev, "second": second, "third": None, "evidence": evidence}


def test_bars_come_from_tune_rows_only_and_per_kind_and_evidence_stratum():
    tune = (
        [_row("amount_role", True, 0.99, 0.99, half="tune", evidence=True)] * 400
        + [_row("amount_role", True, 0.99, 0.99, half="tune", evidence=False)] * 20
        + [_row(DEADLINE_Q, True, 0.99, 0.99, half="tune", evidence=True)] * 400
    )
    wrong_in_score_half = [_row("amount_role", False, 0.99, 0.99, evidence=True)] * 30
    bars = learn_bars(tune + wrong_in_score_half, "both")
    assert bars[("money", True)] == 0.5          # the 30 score-half errors did not leak in
    assert bars[("money", False)] is None        # 20 clean rows cannot reject delta=0.01
    assert ("deadline", True) in bars and bars[("deadline", True)] is None  # 400 vs delta 0.001


def test_score_rows_counts_missing_never_accepts_and_splits_by_language():
    rows = [
        _row("amount_role", True, 0.95, 0.95, language="az"),
        _row("amount_role", False, 0.95, 0.95, language="tr"),
        _row("amount_role", True, 0.95, None, language="tr"),      # second reader missing
        _row("amount_role", True, 0.95, 0.95, half="tune"),        # tune half is not scored
    ]
    out = score_rows(rows, "both", {("money", True): 0.9})
    assert out["money"]["accepted"] == 2 and out["money"]["wrong"] == 1
    assert out["money"]["missing"] == 1
    assert out["money/tr"]["accepted"] == 1 and out["money/tr"]["missing"] == 1
    assert out["money/az"]["accepted"] == 1 and out["money/az"]["wrong"] == 0
    assert out["money"]["recall"] == 0.5  # 1 kept of 2 true-yes rows
    # with no bar a row is never accepted, even when both readers are confident
    assert score_rows(rows, "both", {})["money"]["accepted"] == 0


def test_per_language_check_passes_only_when_the_language_meets_the_kind_bound():
    rows = [_row("amount_role", True, 0.95, 0.95, language="az")] * 400
    rows += [_row("amount_role", True, 0.95, 0.95, language="tr")] * 48
    rows += [_row("amount_role", False, 0.95, 0.95, language="tr")] * 2
    out = score_rows(rows, "both", {("money", True): 0.9})
    assert out["money/az"]["passes"]            # 0 errors in 400 -> upper bound ~0.0075 <= 0.01
    assert not out["money/tr"]["passes"]        # 2 errors in 50
    assert "passes" not in out["money"] and out["money"]["upper_error_95"] > 0


def test_report_shows_every_bar_and_says_why_ltt_gave_none():
    from apps.research.engine_eval.score import report, zero_error_rows_needed
    rows = [_row(DEADLINE_Q, True, 0.99, 0.99, half="tune", evidence=True)] * 90
    rows += [_row(DEADLINE_Q, False, 0.96, 0.96, half="tune", evidence=True)] * 10
    bars = learn_bars(rows, "both")
    assert bars[("deadline", True)] is None
    assert zero_error_rows_needed(0.001) == 2995
    text = report({}, {"both/ds_pro/jev-a": bars}, {}, {},
                  sweeps={"both/ds_pro/jev-a": rows}, votes={"ds_pro": 7})
    assert "no LTT bar at n=100 (needs ≥2995 zero-error rows)" in text
    assert "| deadline | 0.97 | 90 | 0 | 1.0000 |" in text
    assert "| deadline | 0.95 | 100 | 10 | 0.9000 |" in text
    assert "uncalibrated" in text and "| ds_pro | 7 |" in text


def test_a_big_enough_stratum_blocked_by_errors_says_so():
    from apps.research.engine_eval.score import report
    rows = [_row(DEADLINE_Q, False, 0.999, 0.999, half="tune", evidence=True)] * 3000
    bars = learn_bars(rows, "both")
    assert bars[("deadline", True)] is None
    text = report({}, {"both/ds_pro/jev-a": bars}, {}, {}, sweeps={"both/ds_pro/jev-a": rows})
    assert "no LTT bar at n=3000 (errors at every bar blocked it)" in text
