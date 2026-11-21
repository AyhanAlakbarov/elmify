import pytest
from pydantic import ValidationError

from apps.portals.session import FieldAction


def test_field_action_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        FieldAction(
            selector="#fn",
            description="given name",
            sneaky="nope",
        )


def test_field_action_round_trips_through_json():
    action = FieldAction(
        selector="#fn",
        description="given name",
        method="fill",
        arguments=["%value%"],
    )
    assert FieldAction.model_validate(action.model_dump()) == action

