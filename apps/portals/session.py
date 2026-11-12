"""The shape of one stored fill action, and the rule for which may run.

A FieldMap entry's action is a FieldAction; the extension's content script
mirrors FILL_METHODS and is_fillable, and a test asserts the two agree.
"""

from pydantic import BaseModel, ConfigDict

#: The only methods a replay pass may execute. takeDeterministicAction dispatches
#: sixteen -- click, doubleClick, press, dragAndDrop and the scroll family among
#: them -- and rejects only "" and "not-supported". Mirroring that check would let
#: a stored click fire on a submit or consent control for every student of every
#: tenant. A replay only ever types a value, so only these four are allowed.
FILL_METHODS = frozenset({"fill", "type", "selectOption", "selectOptionFromDropdown"})

#: Learn-time variable name. The model is asked to return this placeholder in
#: action.arguments; substituteVariablesInArguments swaps the real value in at
#: act() time. An action carrying a literal instead means the value came from the
#: page rather than from the verified profile.
VALUE_PLACEHOLDER = "%value%"


class FieldAction(BaseModel):
    """One stored fill action. Rows from the retired server pass hold whatever
    its model returned, so is_fillable, not this shape, decides what may run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selector: str
    description: str = ""
    method: str | None = None
    arguments: list[str] | None = None


def is_fillable(action: FieldAction) -> bool:
    """True when this action types a verified value and nothing else.

    Enforced at learn time (an unfillable action is an unmapped field) and again
    at replay, because a row stored before this check existed outlives it.
    """
    # Position-pinned, not membership: every allowed handler reads args[0] and
    # ignores the rest, so ["literal", "%value%"] would type the literal and
    # discard the student's real value. An embedded placeholder
    # ("prefix%value%") is rejected too -- Stagehand would substitute it
    # correctly, but the surrounding text came from the page, not the profile.
    return (
        (action.method or "").strip() in FILL_METHODS
        and action.arguments is not None
        and action.arguments[:1] == [VALUE_PLACEHOLDER]
    )
