import pytest

from apps.portals.session import FieldAction
from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db

GIVEN_NAME = FieldAction(
    selector="#fn", description="given name", method="fill", arguments=["%value%"]
)


def _form():
    from apps.portals.models import PortalForm

    return PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="personal-details"
    )


def test_learn_stores_a_versioned_field_map(agency_a):
    from apps.portals.learn import learn_form
    from apps.portals.models import FieldMap

    form = _form()
    session = FakePortalSession(observed=[GIVEN_NAME])

    field_map = learn_form(
        session,
        form,
        profile_fields=["personal.given_name"],
        tenant_id=agency_a.id,
        forbidden_values=[],
    )

    assert field_map.version == 1
    assert field_map.entries == [
        {
            "profile_field": "personal.given_name",
            # description is deliberately absent: it is model free-text over page
            # content, nothing reads it back at replay, and FieldMap is shared
            # across every tenant.
            "action": {
                "selector": "#fn",
                "method": "fill",
                "arguments": ["%value%"],
            },
        }
    ]
    assert FieldMap.current_for(form, None) == field_map


def test_learn_asks_observe_for_a_placeholder_not_a_literal(agency_a):
    """Stagehand only emits %value% in action.arguments when the variable name
    is exposed to observe(); without it the model returns a literal and the
    stored map is both PII-bearing and unfillable."""
    from apps.portals.learn import LEARN_VARIABLES, learn_form

    session = FakePortalSession(observed=[GIVEN_NAME])

    learn_form(
        session,
        _form(),
        profile_fields=["personal.given_name"],
        tenant_id=agency_a.id,
        forbidden_values=[],
    )

    assert session.observe_variables == [LEARN_VARIABLES]
    assert LEARN_VARIABLES == {"value": "%value%"}


def test_learn_supersedes_the_previous_version(agency_a):
    from apps.portals.learn import learn_form

    form = _form()
    session = FakePortalSession(observed=[GIVEN_NAME])

    first = learn_form(
        session,
        form,
        profile_fields=["personal.given_name"],
        tenant_id=agency_a.id,
        forbidden_values=[],
    )
    second = learn_form(
        session,
        form,
        profile_fields=["personal.given_name"],
        tenant_id=agency_a.id,
        forbidden_values=[],
    )

    first.refresh_from_db()
    assert first.superseded_at is not None
    assert second.version == 2


def test_learn_refuses_an_action_carrying_student_data(agency_a):
    from apps.portals.learn import PIILeak, learn_form
    from apps.portals.models import FieldMap

    form = _form()
    leaking = FakePortalSession(
        observed=[
            FieldAction(
                selector="#fn", description="given name", method="fill", arguments=["Leyla"]
            )
        ]
    )

    with pytest.raises(PIILeak):
        learn_form(
            leaking,
            form,
            profile_fields=["personal.given_name"],
            tenant_id=agency_a.id,
            forbidden_values=["Leyla"],
        )

    assert FieldMap.objects.count() == 0
    assert FieldMap.current_for(form, None) is None


def test_learn_refuses_student_data_carried_in_method(agency_a):
    from apps.portals.learn import PIILeak, learn_form

    leaking = FakePortalSession(
        observed=[
            FieldAction(selector="#fn", description="given name", method="fillWithLeyla")
        ]
    )

    with pytest.raises(PIILeak):
        learn_form(
            leaking,
            _form(),
            profile_fields=["personal.given_name"],
            tenant_id=agency_a.id,
            forbidden_values=["Leyla"],
        )


def test_learn_refuses_to_store_a_partly_mapped_form(agency_a):
    """fill_form and read_back both validate over the stored entries, never
    over the fields that were asked for, so a dropped field would fill and
    verify clean while the portal form stayed incomplete."""
    from apps.portals.learn import UnmappedField, learn_form
    from apps.portals.models import FieldMap

    form = _form()

    class OneFieldOnly(FakePortalSession):
        """observe() finds the given-name field and nothing else."""

        def observe(self, instruction, variables=None):
            self.observe_calls += 1
            return [GIVEN_NAME] if "given_name" in instruction else []

    with pytest.raises(UnmappedField) as excinfo:
        learn_form(
            OneFieldOnly(),
            form,
            profile_fields=["personal.given_name", "personal.family_name"],
            tenant_id=agency_a.id,
            forbidden_values=[],
        )

    assert "personal.family_name" in str(excinfo.value)
    assert FieldMap.objects.count() == 0


@pytest.mark.parametrize("method", [None, "", "not-supported"])
def test_learn_treats_an_unusable_method_as_unmapped(agency_a, method):
    """takeDeterministicAction rejects an action with no method outright, so
    storing one would guarantee a fill that types nothing."""
    from apps.portals.learn import UnmappedField, learn_form
    from apps.portals.models import FieldMap

    session = FakePortalSession(
        observed=[FieldAction(selector="#fn", description="given name", method=method)]
    )

    with pytest.raises(UnmappedField):
        learn_form(
            session,
            _form(),
            profile_fields=["personal.given_name"],
            tenant_id=agency_a.id,
            forbidden_values=[],
        )

    assert FieldMap.objects.count() == 0


def test_learn_is_rate_limited(agency_a, settings):
    from apps.portals.learn import RateLimited, learn_form

    settings.PORTAL_LEARN_RATE_LIMIT = 1
    form = _form()
    session = FakePortalSession(observed=[GIVEN_NAME])

    learn_form(
        session,
        form,
        profile_fields=["personal.given_name"],
        tenant_id=agency_a.id,
        forbidden_values=[],
    )
    with pytest.raises(RateLimited):
        learn_form(
            session,
            form,
            profile_fields=["personal.given_name"],
            tenant_id=agency_a.id,
            forbidden_values=[],
        )


def test_rate_limit_counts_every_observe_not_every_learn_pass(agency_a, settings):
    """One learn_form makes one LLM call per field. Metering per call is the
    only way the tenant budget matches the tokens actually spent."""
    from apps.portals.learn import RateLimited, learn_form

    settings.PORTAL_LEARN_RATE_LIMIT = 2
    session = FakePortalSession(observed=[GIVEN_NAME])

    with pytest.raises(RateLimited):
        learn_form(
            session,
            _form(),
            profile_fields=["a", "b", "c"],
            tenant_id=agency_a.id,
            forbidden_values=[],
        )

    assert session.observe_calls == 2


@pytest.mark.parametrize("method", ["click", "doubleClick", "press", "dragAndDrop", "hover"])
def test_learn_refuses_an_action_that_does_not_type_a_value(agency_a, method):
    """takeDeterministicAction will dispatch all sixteen of its methods. A stored
    click would fire on a submit or consent control for every student of every
    tenant, so anything outside the fill allowlist is an unmapped field."""
    from apps.portals.learn import UnmappedField, learn_form
    from apps.portals.session import FieldAction

    session = FakePortalSession(
        observed=[FieldAction(selector="#fn", method=method, arguments=["%value%"])]
    )

    with pytest.raises(UnmappedField):
        learn_form(
            session,
            _form(),
            profile_fields=["personal.given_name"],
            tenant_id=agency_a.id,
            forbidden_values=[],
        )


def test_learn_refuses_an_action_carrying_a_literal_instead_of_the_placeholder(agency_a):
    """Without %value% the action would type whatever the page supplied, for
    every student, instead of the verified profile value."""
    from apps.portals.learn import UnmappedField, learn_form
    from apps.portals.session import FieldAction

    session = FakePortalSession(
        observed=[FieldAction(selector="#fn", method="fill", arguments=["Leyla"])]
    )

    with pytest.raises(UnmappedField):
        learn_form(
            session,
            _form(),
            profile_fields=["personal.given_name"],
            tenant_id=agency_a.id,
            forbidden_values=[],
        )


def test_learn_never_persists_the_model_description(agency_a):
    """The description is free text over attacker-controllable page content and
    FieldMap has no tenant column -- it must not reach storage at all."""
    from apps.portals.learn import learn_form
    from apps.portals.session import FieldAction

    session = FakePortalSession(
        observed=[
            FieldAction(
                selector="#fn",
                description="Given name, currently showing NUR ALIYEVA",
                method="fill",
                arguments=["%value%"],
            )
        ]
    )

    field_map = learn_form(
        session,
        _form(),
        profile_fields=["personal.given_name"],
        tenant_id=agency_a.id,
        forbidden_values=[],
    )

    stored = field_map.entries[0]["action"]
    assert "description" not in stored
    assert "ALIYEVA" not in str(field_map.entries)
