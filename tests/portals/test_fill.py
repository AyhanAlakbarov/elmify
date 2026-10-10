import pytest

from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db


def _map_with(form, entries):
    from apps.portals.models import FieldMap

    return FieldMap.objects.create(portal_form=form, version=1, entries=entries)


def test_replay_fills_every_field_without_any_llm_call():
    from apps.portals.fill import fill_form
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="personal-details"
    )
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "personal.given_name",
                "action": {"selector": "#fn", "method": "fill", "arguments": ["%value%"]},
            },
            {
                "profile_field": "personal.family_name",
                "action": {"selector": "#ln", "method": "fill", "arguments": ["%value%"]},
            },
        ],
    )
    session = FakePortalSession()

    filled = fill_form(
        session, field_map, {"personal.given_name": "Leyla", "personal.family_name": "Aliyeva"}
    )

    assert filled == ["personal.given_name", "personal.family_name"]
    assert session.values == {"#fn": "Leyla", "#ln": "Aliyeva"}
    assert session.observe_calls == 0


def test_replay_raises_when_a_required_value_is_absent():
    from apps.portals.fill import MissingFact, fill_form
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="personal-details"
    )
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "personal.given_name",
                "action": {"selector": "#fn", "method": "fill", "arguments": ["%value%"]},
            }
        ],
    )

    with pytest.raises(MissingFact) as excinfo:
        fill_form(FakePortalSession(), field_map, {})

    assert "personal.given_name" in str(excinfo.value)


def test_replay_fills_nothing_when_a_later_field_is_missing():
    """A form left half-filled on a real portal is worse than one never
    started, so the raise must precede every act, not just the first."""
    from apps.portals.fill import MissingFact, fill_form
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="personal-details"
    )
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "personal.given_name",
                "action": {"selector": "#fn", "method": "fill", "arguments": ["%value%"]},
            },
            {
                "profile_field": "personal.family_name",
                "action": {"selector": "#ln", "method": "fill", "arguments": ["%value%"]},
            },
        ],
    )
    session = FakePortalSession()

    with pytest.raises(MissingFact):
        fill_form(session, field_map, {"personal.given_name": "Leyla"})

    assert session.values == {}, "a field was filled before MissingFact was raised"


def test_replay_treats_a_blank_value_as_missing():
    """An empty string is not a value: filling it leaves a required portal
    field blank while read_back agrees the page matches the profile."""
    from apps.portals.fill import MissingFact, fill_form, read_back
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="personal-details"
    )
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "personal.given_name",
                "action": {"selector": "#fn", "method": "fill", "arguments": ["%value%"]},
            }
        ],
    )
    session = FakePortalSession()

    with pytest.raises(MissingFact):
        fill_form(session, field_map, {"personal.given_name": "   "})
    with pytest.raises(MissingFact):
        read_back(session, field_map, {"personal.given_name": ""})

    assert session.values == {}


@pytest.mark.parametrize("method", ["click", "press", "dragAndDrop"])
def test_replay_refuses_a_stored_action_that_does_not_type_a_value(method):
    """The learn-time allowlist did not exist when older rows were written, and a
    compromised learn pass could write one anyway. Replay re-checks."""
    from apps.portals.fill import UnsafeAction, fill_form
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "personal.given_name",
                "action": {"selector": "#submit", "method": method, "arguments": ["%value%"]},
            }
        ],
    )
    session = FakePortalSession()

    with pytest.raises(UnsafeAction):
        fill_form(session, field_map, {"personal.given_name": "Leyla"})

    assert session.values == {}, "an unsafe action was executed before the check"


def test_replay_refuses_a_stored_action_carrying_a_literal():
    from apps.portals.fill import UnsafeAction, fill_form
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "personal.given_name",
                "action": {"selector": "#fn", "method": "fill", "arguments": ["attacker text"]},
            }
        ],
    )
    session = FakePortalSession()

    with pytest.raises(UnsafeAction):
        fill_form(session, field_map, {"personal.given_name": "Leyla"})

    assert session.values == {}


def test_replay_refuses_a_placeholder_that_is_not_the_first_argument():
    """Every allowed handler reads args[0] and ignores the rest, so a placeholder
    parked at index 1 means the literal at index 0 is what gets typed -- for
    every student, with the real profile value discarded."""
    from apps.portals.fill import UnsafeAction, fill_form
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "personal.given_name",
                "action": {
                    "selector": "#fn",
                    "method": "fill",
                    "arguments": ["ATTACKER-LITERAL", "%value%"],
                },
            }
        ],
    )
    session = FakePortalSession()

    with pytest.raises(UnsafeAction):
        fill_form(session, field_map, {"personal.given_name": "Leyla"})

    assert session.values == {}


def test_replay_types_nothing_when_a_later_entry_is_unsafe():
    """The unsafe check is a pre-pass. Raising on entry three after typing one
    and two is exactly the half-filled form this module refuses to create."""
    from apps.portals.fill import UnsafeAction, fill_form
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "a",
                "action": {"selector": "#a", "method": "fill", "arguments": ["%value%"]},
            },
            {
                "profile_field": "b",
                "action": {"selector": "#b", "method": "fill", "arguments": ["%value%"]},
            },
            {
                "profile_field": "c",
                "action": {"selector": "#submit", "method": "click", "arguments": ["%value%"]},
            },
        ],
    )
    session = FakePortalSession()

    with pytest.raises(UnsafeAction):
        fill_form(session, field_map, {"a": "A", "b": "B", "c": "C"})

    assert session.values == {}, "earlier fields were typed before the unsafe entry raised"


def test_a_failed_act_reports_what_was_already_filled():
    """Recovery has to know where it got to. Without this the choice is
    retyping every field (two values in one input on a portal that appends) or
    skipping fields that were never filled."""
    from apps.portals.engine import ActFailed
    from apps.portals.fill import FillInterrupted, fill_form
    from apps.portals.models import PortalForm

    class Failing(FakePortalSession):
        def act(self, action, variables):
            if action.selector == "#city":
                raise ActFailed("boom")
            super().act(action, variables)

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "identity.full_name",
                "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]},
            },
            {
                "profile_field": "personal.city",
                "action": {"selector": "#city", "method": "fill", "arguments": ["%value%"]},
            },
        ],
    )
    values = {"identity.full_name": "Ada Byron", "personal.city": "London"}

    with pytest.raises(FillInterrupted) as raised:
        fill_form(Failing(), field_map, values)

    assert raised.value.filled == ["identity.full_name"]
    assert raised.value.profile_field == "personal.city"


def test_skip_leaves_a_field_untouched():
    from apps.portals.fill import fill_form
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "identity.full_name",
                "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]},
            },
            {
                "profile_field": "personal.city",
                "action": {"selector": "#city", "method": "fill", "arguments": ["%value%"]},
            },
        ],
    )
    values = {"identity.full_name": "Ada Byron", "personal.city": "London"}
    session = FakePortalSession()

    fill_form(session, field_map, values, skip={"identity.full_name"})

    assert session.values == {"#city": "London"}


def test_already_correct_is_what_the_page_holds_not_what_we_believe():
    """Used on resume: skip only fields the portal's own draft still holds.
    A portal that lost the draft is then refilled rather than half-skipped."""
    from apps.portals.fill import already_correct
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    field_map = _map_with(
        form,
        [
            {
                "profile_field": "identity.full_name",
                "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]},
            },
            {
                "profile_field": "personal.city",
                "action": {"selector": "#city", "method": "fill", "arguments": ["%value%"]},
            },
        ],
    )
    values = {"identity.full_name": "Ada Byron", "personal.city": "London"}
    session = FakePortalSession()
    session.values["#name"] = "Ada Byron"

    assert already_correct(session, field_map, values) == {"identity.full_name"}
