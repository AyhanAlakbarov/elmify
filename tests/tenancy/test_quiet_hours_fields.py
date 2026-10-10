from datetime import time

import pytest
from django.core.exceptions import ValidationError

from apps.audit.redaction import REDACT
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import validate_timezone_name


def test_a_membership_starts_with_no_zone_and_no_quiet_hours(membership_a):
    assert membership_a.timezone == ""
    assert membership_a.quiet_hours_start is None
    assert membership_a.quiet_hours_end is None


def test_a_real_zone_validates():
    validate_timezone_name("Europe/Berlin")


def test_junk_in_the_timezone_field_is_refused():
    with pytest.raises(ValidationError):
        validate_timezone_name("Not/AZone")


def test_the_quiet_window_round_trips(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        membership_a.timezone = "Asia/Baku"
        membership_a.quiet_hours_start = time(22, 0)
        membership_a.quiet_hours_end = time(7, 0)
        membership_a.save(
            update_fields=["timezone", "quiet_hours_start", "quiet_hours_end"]
        )
        membership_a.refresh_from_db()

    assert membership_a.timezone == "Asia/Baku"
    assert membership_a.quiet_hours_start == time(22, 0)


def test_the_new_fields_are_classified_for_erasure():
    """A quiet window and a zone say when someone sleeps and where they live."""
    spec = REDACT["tenancy.Membership"]

    assert "timezone" in spec.fields
    assert "quiet_hours_start" in spec.fields
    assert "quiet_hours_end" in spec.fields
