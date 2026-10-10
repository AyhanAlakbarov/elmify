import pytest

from apps.portals.models import PortalForm


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")
