import pytest
from pydantic import ValidationError

from apps.portals.session import FieldAction
from tests.portals.fakes import FakePortalSession


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


def test_fake_session_records_filled_values():
    session = FakePortalSession(
        observed=[FieldAction(selector="#fn", description="given name")]
    )
    action = session.observe("the given name field")[0]
    session.act(action, {"value": "Leyla"})

    assert session.read_value("#fn") == "Leyla"


def test_the_fake_answers_the_three_query_primitives():
    from tests.portals.fakes import FakePortalSession

    session = FakePortalSession(elements={".g-recaptcha": {"data-sitekey": "abc"}})

    assert session.exists(".g-recaptcha") is True
    assert session.exists("#nothing") is False
    assert session.query_attribute(".g-recaptcha", "data-sitekey") == "abc"
    assert session.query_attribute(".g-recaptcha", "data-missing") is None
    assert session.query_attribute("#nothing", "data-sitekey") is None

    session.press_enter()
    assert session.enter_presses == 1
