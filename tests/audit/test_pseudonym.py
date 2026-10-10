"""Pseudonym is an empty table whose foreign key is a GDPR guarantee.

Derived and ML data references a student through Pseudonym and never through
Membership. Erasure deletes the Pseudonym row and the database removes the
derived rows with it -- propagation enforced by the schema rather than by a
policy comment someone can forget. See CLAUDE.md, "Derived data and the ML
corpus", and docs/superpowers/specs/2026-09-10-erasure-console-design.md.
"""

import pytest
from django.apps import apps as django_apps
from django.db import models
from django.db.models import ForeignKey, OneToOneField
from django.utils import timezone

from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, Pseudonym, RetentionPolicy
from apps.tenancy.context import tenant_scope


def test_every_foreign_key_to_pseudonym_cascades():
    """The whole propagation guarantee is one on_delete argument.

    Passes vacuously today because nothing references Pseudonym yet, and that
    is exactly its job: it fails on the day someone adds the first derived
    table with SET_NULL or PROTECT, which would leave a row describing an
    erased person behind. SET_NULL becomes correct only for a schema that has
    passed the re-identification assessment in `phased requirements.md` §6.1,
    and nothing has.
    """
    # A vacuous pass and a broken test look identical, so pin the one way
    # this could silently stop scanning: Pseudonym dropping out of the app
    # registry. Verified 2026-09-11 that the loop below detects violations --
    # pointed at Membership it finds 31 FKs and flags all 31 as non-CASCADE.
    assert Pseudonym in django_apps.get_models()

    offenders = []
    for model in django_apps.get_models():
        for field in model._meta.get_fields():
            if not isinstance(field, (ForeignKey, OneToOneField)):
                continue
            if field.related_model is not Pseudonym:
                continue
            if field.remote_field.on_delete is not models.CASCADE:
                offenders.append(f"{model._meta.label}.{field.name}")
    assert not offenders, (
        f"these must be on_delete=CASCADE: {offenders}. A derived row that "
        "outlives its student is personal data the erasure did not reach."
    )


@pytest.mark.django_db
def test_pseudonym_has_no_writer_yet(agency_a):
    """The empty table is the design, not an omission.

    When the §6.1 extraction pipeline is built and starts creating rows here,
    this test fails and whoever built it must confirm three things before
    replacing the assertion:

      1. Every derived table points at Pseudonym with CASCADE, never at
         Membership directly (test above).
      2. Extraction happens during ordinary use, inside the tenant boundary.
         An erasure never manufactures a dataset.
      3. Nothing retains a derived row through an erasure until a schema has
         passed the §6.1 re-identification assessment.
    """
    with tenant_scope(agency_a.id):
        assert not Pseudonym.objects.exists()


@pytest.mark.django_db
def test_erasure_deletes_the_pseudonym(agency_a, django_user_model, monkeypatch):
    """The one thing this table does today.

    Both AWS calls on the EXECUTED path are patched, following
    tests/audit/test_deletion_purges_documents.py: unpatched,
    delete_student_portal_credentials builds a real secretsmanager client,
    which needs an ambient AWS region -- so the test passes on a laptop with
    ~/.aws/config and fails in CI, which has none.
    """
    from apps.audit import deletion
    from apps.tenancy.models import Membership

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)

    user = django_user_model.objects.create_user(username="pseudo-student")
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        Pseudonym.objects.create(tenant=agency_a, student=student)

        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")

        assert not Pseudonym.objects.filter(student_id=student.id).exists()
