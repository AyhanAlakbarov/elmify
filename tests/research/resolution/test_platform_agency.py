"""At most one agency is the platform, and only an admin command says which.

Spec 2026-09-22 section 11: "the master agency sees everything". PLATFORM_ADMIN
is a role any agency can hold, so there was nothing to key that on until
`research.PlatformAgency`. It lives on the research side rather than as a
tenancy column so that neither runtime role can write it (the grant tests are
in test_rls.py); `manage.py set_platform_agency`, run as the migration role, is
the only writer.
"""

import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction

from apps.research.models import PlatformAgency
from apps.research.resolution.platform import platform_agency
from apps.tenancy.models import Agency

pytestmark = pytest.mark.django_db


def test_no_platform_agency_is_an_error_not_a_default(agency_a) -> None:
    with pytest.raises(Agency.DoesNotExist):
        platform_agency()


def test_two_platform_agencies_are_refused_by_the_database(agency_a, agency_b) -> None:
    PlatformAgency.objects.create(agency=agency_a)
    with pytest.raises(IntegrityError), transaction.atomic():
        PlatformAgency.objects.create(agency=agency_b)
    # Nor can the one row be forged into a second shape: `singleton` is True or
    # nothing, so "two rows with different singletons" is refused by the CHECK.
    with pytest.raises(IntegrityError), transaction.atomic():
        PlatformAgency.objects.create(agency=agency_b, singleton=False)


def test_the_command_sets_one_and_refuses_a_second(agency_a, agency_b) -> None:
    call_command("set_platform_agency", str(agency_a.id))
    assert platform_agency().id == agency_a.id
    # Idempotent for the same agency: re-running a runbook step is not an error.
    call_command("set_platform_agency", str(agency_a.id))
    with pytest.raises(CommandError, match="already the platform"):
        call_command("set_platform_agency", str(agency_b.id))
    assert platform_agency().id == agency_a.id


def test_the_command_refuses_an_unknown_agency() -> None:
    with pytest.raises(CommandError, match="no agency"):
        call_command("set_platform_agency", "00000000-0000-0000-0000-000000000000")
    with pytest.raises(CommandError, match="no agency"):
        call_command("set_platform_agency", "not-a-uuid")
    assert not PlatformAgency.objects.exists()


@pytest.fixture
def two_agencies(django_db_setup, django_db_blocker):
    """Committed before ``web_role_orm`` swaps the connection, which must be
    requested after this."""
    with django_db_blocker.unblock():
        agencies = (Agency.objects.create(name="One"), Agency.objects.create(name="Two"))
    yield agencies
    with django_db_blocker.unblock():
        PlatformAgency.objects.all().delete()
        Agency.objects.filter(id__in=[a.id for a in agencies]).delete()


@pytest.mark.django_db(transaction=True)
def test_the_command_cannot_run_as_the_web_role(two_agencies, web_role_orm) -> None:
    """Run as a real runtime_web member, the command stops with the runbook's
    words -- a refused write, not a silent no-op -- and nothing is written."""
    with pytest.raises(CommandError, match="cannot write research_platformagency"):
        call_command("set_platform_agency", str(two_agencies[0].id))
    assert not PlatformAgency.objects.exists()
