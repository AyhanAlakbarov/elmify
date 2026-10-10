"""Replay pass: fill a form from a stored FieldMap, with no LLM call.

Student values are passed as Stagehand variables at act() time, so they never
enter a stored map and never reach a model prompt.
"""

import logging
from collections.abc import Collection

from .engine import ActFailed
from .models import FieldMap
from .session import FieldAction, PortalSession, UnsafeAction, is_fillable

# UnsafeAction is re-exported rather than defined here: _require_fillable below
# raises it, so does the engine's own act(), and neither module can import the
# other. __all__ is what keeps that a deliberate export.
__all__ = [
    "FillInterrupted",
    "MissingFact",
    "ReadBackMismatch",
    "UnsafeAction",
    "already_correct",
    "fill_form",
    "read_back",
]

logger = logging.getLogger(__name__)


class MissingFact(Exception):
    """The form needs a value the verified profile does not have."""


def _require_values(field_map: FieldMap, values: dict[str, str]) -> None:
    """Raise unless every field-map entry has a non-blank verified value.

    Blank counts as missing: typing "" into a required portal field leaves the
    form incomplete while read_back happily agrees the page matches.
    """
    for entry in field_map.entries:
        if not (values.get(entry["profile_field"]) or "").strip():
            raise MissingFact(f"no verified value for {entry['profile_field']}")


def _require_fillable(field_map: FieldMap) -> None:
    """Reject every unsafe stored action before typing any of them.

    A pre-pass, not a per-entry check inside the act loop: raising on the third
    entry after typing the first two is the half-filled form this module exists
    to prevent. The engine's act() refuses the same actions anyway -- that is
    the structural boundary; this is the one that keeps the form intact.

    Re-checked at replay and not only at learn time: a row written before the
    allowlist existed, or by a compromised learn pass, is still replayable.
    """
    for entry in field_map.entries:
        action = FieldAction.model_validate(entry["action"])
        if not is_fillable(action):
            raise UnsafeAction(
                f"{entry['profile_field']}: refusing to replay {action.method!r}"
            )


class FillInterrupted(Exception):
    """An act() failed partway. Carries what was already typed so a recovery
    can finish the form instead of starting it again -- and so the caller can
    record what went into a real person's live application."""

    def __init__(
        self, filled: list[str], profile_field: str, *, after_relearn: bool = False
    ) -> None:
        super().__init__(f"{profile_field}: fill interrupted after {len(filled)} field(s)")
        self.filled = filled
        self.profile_field = profile_field
        #: Set by fill_with_recovery on the second miss. "Nothing works on a
        #: freshly re-learned map" is the one place the stall heuristic's
        #: premise is genuinely true -- see prepare_application.
        self.after_relearn = after_relearn


def already_correct(
    session: PortalSession, field_map: FieldMap, values: dict[str, str]
) -> set[str]:
    """Fields the rendered page already holds correctly.

    The only fields safe to skip on a resume. A portal that persisted its own
    draft returns most of them; one that did not returns none and the form is
    filled from scratch, which is the behaviour we want in both cases.
    """
    correct = set()
    for entry in field_map.entries:
        action = FieldAction.model_validate(entry["action"])
        try:
            rendered = session.read_value(action.selector)
        except Exception:
            # A selector that no longer resolves raises rather than returning
            # "". That is drift, and drift is the re-learn path's business --
            # this function's only job is to answer "safe to skip?", and the
            # answer for a field it cannot read is no. The log line is not
            # decoration: bandit's B112 fires on a bare except/continue, which
            # is verified against this repo's own bandit config.
            logger.debug("cannot read %s, not skipping it", action.selector)
            continue
        if rendered == values.get(entry["profile_field"]):
            correct.add(entry["profile_field"])
    return correct


def fill_form(
    session: PortalSession,
    field_map: FieldMap,
    values: dict[str, str],
    *,
    skip: Collection[str] = (),
) -> list[str]:
    """Fill a form from a stored map. Makes no LLM call.

    Validation is a separate first pass: a form left half-filled on a real
    portal is worse than one never started, so nothing is typed until every
    required value is known to be present.
    """
    _require_values(field_map, values)
    _require_fillable(field_map)

    filled: list[str] = []
    for entry in field_map.entries:
        profile_field = entry["profile_field"]
        if profile_field in skip:
            continue
        action = FieldAction.model_validate(entry["action"])
        try:
            session.act(action, {"value": values[profile_field]})
        except ActFailed as error:
            # Not swallowed and not retried here: the caller decides whether a
            # re-learn is warranted, and it needs to know how far we got.
            raise FillInterrupted(filled, profile_field) from error
        filled.append(profile_field)
    return filled


class ReadBackMismatch(Exception):
    """The rendered page does not hold the value we believe we filled."""

    def __init__(self, field: str, expected: str, actual: str) -> None:
        super().__init__(f"{field}: expected {expected!r}, page holds {actual!r}")
        self.field = field
        self.expected = expected
        self.actual = actual


def read_back(session: PortalSession, field_map: FieldMap, values: dict[str, str]) -> None:
    """Compare the rendered page against the verified profile.

    Runs against the page, not against what the caller believes it typed --
    that is the whole point, so a mis-resolved selector is caught here.
    """
    _require_values(field_map, values)

    for entry in field_map.entries:
        profile_field = entry["profile_field"]
        expected = values[profile_field]
        action = FieldAction.model_validate(entry["action"])
        actual = session.read_value(action.selector)
        if actual != expected:
            raise ReadBackMismatch(profile_field, expected, actual)
