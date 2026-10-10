"""Membership.display_name: dashboards show people, not UUIDs. Db-free."""

from django.contrib.auth.models import User

from apps.tenancy.models import Membership


def test_full_name_wins():
    user = User(username="l.mammadova", first_name="Leyla", last_name="Mammadova")
    assert Membership(user=user).display_name == "Leyla Mammadova"


def test_username_fallback_when_no_name_set():
    user = User(username="student-42")
    assert Membership(user=user).display_name == "student-42"
