"""The evidence-intake command's one gate: whose repository is this?

``repo.authorship()`` reduces to ``contributors.get(owner_login, 0) > 0``, so
an owner_login nobody verified turns the gate off and a stranger's repository
becomes the student's skills. There is no verified GitHub account link on a
profile yet; the command uses a CONFIRMED identity fact instead.
"""

import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.documents.management.commands.ingest_evidence import confirmed_github_login
from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model, *, handle=None, url=None, confirmed=True):
    user = django_user_model.objects.create(username=f"u{uuid.uuid4().hex[:12]}")
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    payload = {"full_name": "Jane Doe"}
    if handle:
        payload["github_username"] = handle
    if url:
        payload["github_url"] = url
    VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.IDENTITY,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="upload:test",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        created_by=student,
    )
    return student


def test_a_confirmed_handle_is_found_by_name_or_by_url(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        by_name = _student(agency_a, django_user_model, handle="0rkhann")
        by_url = _student(agency_a, django_user_model, url="https://github.com/0rkhann")
        assert confirmed_github_login(by_name) == "0rkhann"
        assert confirmed_github_login(by_url) == "0rkhann"


def test_an_unconfirmed_handle_is_not_a_handle(agency_a, django_user_model):
    """Ingestion writes every fact confirmed_by=None; a human accepting it is
    what turns the CV's printed handle into something we may act on."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, handle="0rkhann", confirmed=False)
        assert confirmed_github_login(student) == ""


def test_the_command_refuses_a_repository_the_student_has_not_claimed(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, handle="0rkhann")
    with pytest.raises(CommandError, match="confirmed GitHub handle"):
        call_command(
            "ingest_evidence",
            tenant=str(agency_a.id),
            student=str(student.id),
            source="https://github.com/torvalds/linux",
        )


def test_the_command_refuses_a_source_it_cannot_classify(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, handle="0rkhann")
    with pytest.raises(CommandError, match="unusable source"):
        call_command(
            "ingest_evidence",
            tenant=str(agency_a.id),
            student=str(student.id),
            source="https://example.com/whatever",
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/?r=github.com/torvalds",
        "https://github.com.evil.example/torvalds",
        "https://not-github.com/torvalds",
    ],
)
def test_a_handle_is_only_taken_from_github_itself(agency_a, django_user_model, url):
    """The handle decides authorship -- repo.authorship() reduces to
    `contributors.get(owner_login, 0) > 0` -- so the host it came from is part
    of the claim. Substring matching on "github.com/" reads all three of these
    as GitHub; schemas._anchor_text already got this right for the same field
    ("github.com.evil.example is not GitHub")."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, url=url)
        assert confirmed_github_login(student) == ""


def test_a_repository_url_is_not_a_profile(agency_a, django_user_model):
    """A CV linking a project it merely used would otherwise claim that
    project's owner as the applicant's handle."""
    with tenant_scope(agency_a.id):
        student = _student(
            agency_a, django_user_model, url="https://github.com/tensorflow/models"
        )
        assert confirmed_github_login(student) == ""
