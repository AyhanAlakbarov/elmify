"""The narrow browser surface the fill engine depends on.

Mirrors Stagehand's ActionInput shape so a stored FieldAction can be handed
straight back to act(). Keeping this a Protocol is what lets learn.py and
fill.py be unit-tested without a browser.
"""

from typing import Protocol

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
    """What observe() returned. Faithful to the model's output, including output
    we will refuse to execute -- see is_fillable for what may actually run."""

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


class UnsafeAction(Exception):
    """An action would do something other than type a verified value.

    Beside is_fillable rather than in fill.py, because both places that raise
    it -- the stored-map pre-pass and the engine's own act() chokepoint -- are
    modules fill.py cannot be imported from without a cycle.
    """


class PortalSession(Protocol):
    def goto(self, url: str) -> None:
        ...

    def observe(
        self, instruction: str, variables: dict[str, str] | None = None
    ) -> list[FieldAction]:
        ...

    def act(self, action: FieldAction, variables: dict[str, str]) -> None:
        ...

    def read_value(self, selector: str) -> str:
        ...

    def exists(self, selector: str) -> bool:
        ...

    def query_attribute(self, selector: str, attribute: str) -> str | None:
        ...

    def press_enter(self) -> None:
        ...
