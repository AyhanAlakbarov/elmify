"""The bar each mail decision question must clear, and when they were learned.

Written by hand from `manage.py decision_eval score`'s report (it prints this
dict). Until MEASURED_ON is set every bar is DEFAULT_BAR and no outcome is
recorded automatically: the card shows the reading and asks a person.
A bar of None means Learn-then-Test passed no bar: that question never acts.
"""

DEFAULT_BAR = 0.95
#: The date of the decision_eval run these bars came from, "" until one has.
MEASURED_ON = ""
BARS: dict[str, float | None] = {}


def bar(question_id: str) -> float:
    value = BARS.get(question_id, DEFAULT_BAR)
    return 1.01 if value is None else value


def measured() -> bool:
    return bool(MEASURED_ON)
