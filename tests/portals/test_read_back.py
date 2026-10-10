import pytest

from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db


def _map_with(form, entries):
    from apps.portals.models import FieldMap

    return FieldMap.objects.create(portal_form=form, version=1, entries=entries)


def test_read_back_passes_when_the_page_matches_the_profile():
    from apps.portals.fill import fill_form, read_back
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
    values = {"personal.given_name": "Leyla"}

    fill_form(session, field_map, values)
    read_back(session, field_map, values)


def test_read_back_fails_when_the_page_diverges():
    from apps.portals.fill import ReadBackMismatch, fill_form, read_back
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
    values = {"personal.given_name": "Leyla"}
    fill_form(session, field_map, values)

    session.values["#fn"] = "Leyl"  # portal truncated the input

    with pytest.raises(ReadBackMismatch) as excinfo:
        read_back(session, field_map, values)

    assert excinfo.value.field == "personal.given_name"
    assert excinfo.value.expected == "Leyla"
    assert excinfo.value.actual == "Leyl"


def test_read_back_raises_missing_fact_rather_than_key_error():
    """A caller with an incomplete values dict gets the module's own
    exception, not a bare KeyError from a dict lookup."""
    from apps.portals.fill import MissingFact, read_back
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

    with pytest.raises(MissingFact):
        read_back(FakePortalSession(), field_map, {})
