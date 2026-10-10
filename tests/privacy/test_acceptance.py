import pytest

from apps.privacy import acceptance, documents
from apps.privacy.models import Acceptance
from apps.tenancy.context import tenant_scope


@pytest.fixture
def published(db):
    for kind in documents.KINDS:
        documents.publish(kind, "en", f"{kind} v1", material=True)


@pytest.mark.django_db
def test_agency_students_accept_the_agency_notice(agency_a, published):
    assert acceptance.required_kinds(agency_a.id) == ("terms", "privacy_notice_agency")


@pytest.mark.django_db
def test_platform_students_accept_the_direct_notice(agency_a, published):
    from apps.research.models import PlatformAgency

    PlatformAgency.objects.create(agency=agency_a)
    assert acceptance.required_kinds(agency_a.id) == ("terms", "privacy_notice_direct")


@pytest.mark.django_db
def test_accepting_clears_the_need_and_a_material_change_brings_it_back(membership_a, published):
    with tenant_scope(membership_a.tenant_id):
        assert acceptance.needs_acceptance(membership_a)
        docs = acceptance.documents_to_accept(membership_a.tenant_id, "en")
        acceptance.record(membership_a, docs, surface="signup", language="en")
        assert not acceptance.needs_acceptance(membership_a)
        assert Acceptance.objects.filter(student=membership_a).count() == 2

        documents.publish("terms", "en", "terms v2 typo fix", material=False)
        assert not acceptance.needs_acceptance(membership_a)
        documents.publish("terms", "en", "terms v3 new purpose", material=True)
        assert acceptance.needs_acceptance(membership_a)


@pytest.mark.django_db
def test_counselors_never_need_student_acceptance(counselor_membership, published):
    with tenant_scope(counselor_membership.tenant_id):
        assert not acceptance.needs_acceptance(counselor_membership)


@pytest.mark.django_db
def test_no_published_documents_means_nothing_to_accept(membership_a):
    with tenant_scope(membership_a.tenant_id):
        assert not acceptance.needs_acceptance(membership_a)


@pytest.mark.django_db(transaction=True)
def test_acceptance_rows_are_tenant_isolated(membership_a, agency_b, published, rls_enforced_orm):
    from apps.tenancy.db import tenant_transaction

    with tenant_scope(membership_a.tenant_id), tenant_transaction(membership_a.tenant_id):
        docs = acceptance.documents_to_accept(membership_a.tenant_id, "en")
        acceptance.record(membership_a, docs, surface="signup", language="en")
    with tenant_scope(membership_a.tenant_id), tenant_transaction(membership_a.tenant_id):
        assert Acceptance._base_manager.count() == 2
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert Acceptance._base_manager.count() == 0


def _accept_all(student, language):
    docs = acceptance.documents_to_accept(student.tenant_id, language)
    acceptance.record(student, docs, surface="signup", language=language)


@pytest.mark.django_db
def test_a_translation_published_later_does_not_relock_a_student_who_accepted_the_fallback(
    membership_a, published
):
    with tenant_scope(membership_a.tenant_id):
        _accept_all(membership_a, "az")  # no az text yet: the en rows are what was accepted
        assert not acceptance.needs_acceptance(membership_a)
        documents.publish("terms", "az", "terms az v1", material=True)
        documents.publish("privacy_notice_agency", "az", "notice az v1", material=True)
        assert not acceptance.needs_acceptance(membership_a)


@pytest.mark.django_db
def test_a_material_change_locks_only_students_of_that_language(membership_a, published):
    with tenant_scope(membership_a.tenant_id):
        documents.publish("terms", "az", "terms az v1", material=True)
        documents.publish("privacy_notice_agency", "az", "notice az v1", material=True)
        _accept_all(membership_a, "az")
        assert not acceptance.needs_acceptance(membership_a)
        documents.publish("terms", "en", "terms en v2", material=True)
        assert not acceptance.needs_acceptance(membership_a)  # en-only change, az student
        documents.publish("terms", "az", "terms az v2", material=True)
        assert acceptance.needs_acceptance(membership_a)


@pytest.mark.django_db
def test_a_material_english_change_locks_an_english_student(membership_a, published):
    with tenant_scope(membership_a.tenant_id):
        _accept_all(membership_a, "en")
        documents.publish("terms", "en", "terms en v2", material=True)
        assert acceptance.needs_acceptance(membership_a)
