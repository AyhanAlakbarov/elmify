"""What one card needs from its referees (lanes spec §11.1).

Pure: the card's copied `referee_requirements` records in, one RefereeNeed out.
A record is `{"field", "value", "date", "conditional", "condition", "rule_text",
"source_url"}` (apps/documents/rule_sinks.py::to_referee). A field with no record
was not stated, and stays None here: the page says "Not stated — check the page",
never a default.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: rule_sinks writes these five fields (grammar.REFEREE_FIELDS).
FIELDS = ("count", "kind", "mode", "institutional_email_required", "due")
#: count -> letters. THREE_OR_MORE is read as its floor: three.
_LETTERS = {"ONE": 1, "TWO": 2, "THREE_OR_MORE": 3, "NONE_REQUIRED": 0}
#: The only condition kind a card can answer: "scholarship applicants also need..."
#: (grammar.CONDITION_KINDS). nationality, degree_level, work_experience and other
#: need the student's facts, which this function does not hold; such a record never
#: applies here and is shown beside the need instead.
_TRACK = "track"
NOT_STATED = "Not stated — check the page"


@dataclass(frozen=True)
class Stated:
    value: str
    rule_text: str


@dataclass(frozen=True)
class RefereeNeed:
    count: Stated | None = None
    kind: Stated | None = None
    mode: Stated | None = None
    institutional_email_required: Stated | None = None
    due: Stated | None = None
    #: Conditional sentences that did not apply to this card, shown as they are.
    other_conditions: tuple[str, ...] = ()

    @property
    def letters(self) -> int | None:
        """How many letters, or None when the page does not say."""
        return _LETTERS.get(self.count.value) if self.count is not None else None

    @property
    def institutional_email(self) -> bool:
        return (
            self.institutional_email_required is not None
            and self.institutional_email_required.value == "YES"
        )


def _applies(record: dict[str, object], *, route_kind: str, award: bool) -> bool:
    if not record.get("conditional"):
        return True
    if record.get("condition") != _TRACK:
        return False
    # A track condition is a funded route: the card is a scholarship's own, or its
    # route is not the self-funded one.
    return award or (bool(route_kind) and route_kind != "SELF_FUNDED")


def needs_for(
    records: Sequence[dict[str, object]], *, route_kind: str = "", award: bool = False
) -> RefereeNeed:
    """One need per card. For each field the first applicable conditional record wins
    over an unconditional one (it is the rule for this route); otherwise the first."""
    chosen: dict[str, Stated] = {}
    specific: set[str] = set()
    others: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        field, value = str(record.get("field", "")), str(record.get("value", ""))
        if field not in FIELDS or not value or value == "NOT_STATED":
            continue
        text = str(record.get("rule_text", ""))
        if not _applies(record, route_kind=route_kind, award=award):
            if text and text not in others:
                others.append(text)
            continue
        conditional = bool(record.get("conditional"))
        if field in specific or (field in chosen and not conditional):
            continue
        chosen[field] = Stated(value, text)
        if conditional:
            specific.add(field)
    return RefereeNeed(**chosen, other_conditions=tuple(others))
