import pytest
from django.core.exceptions import ValidationError

from apps.tenancy.context import TenantContextMissing, tenant_scope
from apps.tenancy.models import Agency, Membership


def test_branding_tokens_reject_executable_values() -> None:
    agency = Agency(
        name="Unsafe",
        brand_logo_url="javascript:alert(1)",
        brand_primary_color="red;display:none",
    )
    with pytest.raises(ValidationError):
        agency.full_clean(validate_unique=False, validate_constraints=False)


@pytest.mark.django_db
def test_tenant_queryset_fails_without_context() -> None:
    with pytest.raises(TenantContextMissing):
        list(Membership.objects.all())


@pytest.mark.django_db
def test_sequential_tenant_queries_are_isolated(
    agency_a, agency_b, membership_a, membership_b
) -> None:
    with tenant_scope(agency_a.id):
        assert list(Membership.objects.values_list("id", flat=True)) == [membership_a.id]
    with tenant_scope(agency_b.id):
        assert list(Membership.objects.values_list("id", flat=True)) == [membership_b.id]


@pytest.mark.django_db
def test_save_rejects_conflicting_tenant(agency_a, agency_b, user_a) -> None:
    with tenant_scope(agency_a.id), pytest.raises(ValueError, match="tenant mismatch"):
        Membership(tenant=agency_b, user=user_a, role=Membership.Role.STUDENT).save()


@pytest.mark.django_db
def test_application_email_is_empty_until_provisioned(agency_a, django_user_model) -> None:
    """The platform-issued mailbox is not the signup address.

    There is deliberately no fallback: an application_email that defaulted to
    user.email would publish the login address to a funder and send the reply
    to a mailbox nothing scrapes.
    """
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(
            username="identity-1", email="signup@example.com"
        )
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        assert student.application_email == ""
        assert student.user.email == "signup@example.com"
