"""The bar each mail decision question must clear, and when they were learned.

Written by hand from `manage.py decision_eval score`'s report (it prints this
dict). Until MEASURED_ON is set every bar is DEFAULT_BAR and no outcome is
recorded automatically: the card shows the reading and asks a person.
A bar of None means Learn-then-Test passed no bar: that question never acts.
"""

from __future__ import annotations

DEFAULT_BAR = 0.95
#: The date of the decision_eval run these bars came from, "" until one has.
MEASURED_ON = ""
#: Positive RCPS thresholds tau_pos in [0.5, 1.0] (or legacy scalar / (bar_pos, bar_neg) tuple)
#: controlling False Discovery Rate P(Y=0 | p >= tau_pos).
BARS: dict[str, float | tuple[float | None, float | None] | None] = {}
#: Independent negative RCPS thresholds tau_neg in [0.0, 0.5] controlling False Omission Rate
#: P(Y=1 | p <= tau_neg) on binary Noul questions ("is_decision", "other_programme").
NEGATIVE_BARS: dict[str, float | None] = {}


def bar(question_id: str) -> float:
    """Return positive threshold tau_pos in [0.5, 1.01] that P(true) must meet to decide True."""
    value = BARS.get(question_id, DEFAULT_BAR)
    if isinstance(value, tuple):
        pos_val = value[0]
        return 1.01 if pos_val is None else pos_val
    return 1.01 if value is None else value


def negative_bar(question_id: str) -> float:
    """Return negative threshold tau_neg in [-0.01, 0.5] that P(true) must be at or below to
    decide False.

    Uses `NEGATIVE_BARS[question_id]` (or the second element when `BARS[question_id]` is a
    `(bar_pos, bar_neg)` tuple) if configured; otherwise falls back to `1.0 - bar(question_id)`
    for backward compatibility. A calibrated bar of `None` returns `-0.01` so the negative
    branch safely abstains.
    """
    if question_id in NEGATIVE_BARS:
        neg_val = NEGATIVE_BARS[question_id]
        return -0.01 if neg_val is None else neg_val
    raw = BARS.get(question_id)
    if isinstance(raw, tuple):
        neg_val = raw[1]
        return -0.01 if neg_val is None else neg_val
    pos = bar(question_id)
    return -0.01 if pos > 1.0 else round(1.0 - pos, 6)


def measured() -> bool:
    return bool(MEASURED_ON)
