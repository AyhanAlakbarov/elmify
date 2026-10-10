import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from apps.accounts.models import StudentProfileVersion
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


@pytest.fixture
def typed(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": answers.pop(0))
    return answers


def _run(agency, host, username="amina"):
    call_command(
        "create_student",
        "--agency",
        str(agency.id),
        "--host",
        host,
        "--username",
        username,
    )


def test_it_creates_a_user_and_one_student_membership_and_nothing_else(
    agency_a, domain_a, typed
) -> None:
    typed.extend(["correct-horse-battery", "correct-horse-battery"])
    _run(agency_a, domain_a.host)

    user = get_user_model().objects.get(username="amina")
    assert user.check_password("correct-horse-battery")
    with tenant_scope(agency_a.id):
        membership = Membership.objects.get(user=user)
        assert membership.role == Membership.Role.STUDENT
        assert not StudentProfileVersion.objects.filter(student=membership).exists()


def test_an_unverified_host_is_refused(agency_a, unverified_domain, typed) -> None:
    with pytest.raises(CommandError, match="not a verified domain"):
        _run(agency_a, unverified_domain.host)
    assert not get_user_model().objects.filter(username="amina").exists()


def test_another_agency_s_host_is_refused(agency_a, domain_b, typed) -> None:
    with pytest.raises(CommandError, match="not a verified domain"):
        _run(agency_a, domain_b.host)


def test_mismatched_passwords_create_nothing(agency_a, domain_a, typed) -> None:
    typed.extend(["correct-horse-battery", "different-horse-battery"])
    with pytest.raises(CommandError, match="do not match"):
        _run(agency_a, domain_a.host)
    assert not get_user_model().objects.filter(username="amina").exists()


def test_a_weak_password_is_refused(agency_a, domain_a, typed) -> None:
    typed.extend(["123", "123"])
    with pytest.raises(CommandError):
        _run(agency_a, domain_a.host)


def test_a_password_is_never_an_argument(agency_a, domain_a) -> None:
    with pytest.raises(CommandError):
        call_command(
            "create_student", "--agency", str(agency_a.id), "--host", domain_a.host,
            "--username", "amina", "--password", "x",
        )


def test_a_taken_username_is_refused(agency_a, domain_a, typed, user_a) -> None:
    with pytest.raises(CommandError, match="already taken"):
        _run(agency_a, domain_a.host, username=user_a.username)


def test_a_malformed_agency_uuid_creates_nothing(agency_a, domain_a, typed) -> None:
    typed.extend(["correct-horse-battery", "correct-horse-battery"])
    with pytest.raises(CommandError, match="No agency with that id"):
        call_command(
            "create_student",
            "--agency",
            "not-a-uuid",
            "--host",
            domain_a.host,
            "--username",
            "amina",
        )
    assert not get_user_model().objects.filter(username="amina").exists()


def test_help_text_mentions_signup_and_privacy_accept() -> None:
    from apps.accounts.management.commands.create_student import Command

    cmd = Command()
    assert "/signup/" in cmd.help
    assert "/privacy/accept/" in cmd.help
