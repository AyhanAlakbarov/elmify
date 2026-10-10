from django.db import models, transaction
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from apps.tenancy.context import TenantContextMissing, current_tenant_id
from apps.tenancy.models import Membership

from .models import StudentProfileVersion
from .schemas import MinimalProfile, StudentProfileSnapshot


class ProfileVersionRejected(ValueError):
    pass


@transaction.atomic
def create_profile_version(
    *,
    student: Membership,
    snapshot: MinimalProfile | StudentProfileSnapshot,
) -> StudentProfileVersion:
    try:
        tenant_id = current_tenant_id()
        locked = Membership.objects.select_for_update().get(id=student.id)
    except (TenantContextMissing, Membership.DoesNotExist) as exc:
        raise ProfileVersionRejected("profile subject unavailable") from exc
    if locked.tenant_id != tenant_id or not locked.active or locked.role != Membership.Role.STUDENT:
        raise ProfileVersionRejected("active student membership required")

    schema = (
        StudentProfileSnapshot if isinstance(snapshot, StudentProfileSnapshot) else MinimalProfile
    )
    try:
        validated = schema.model_validate(snapshot.model_dump(mode="python", warnings="none"))
    except (PydanticSerializationError, ValidationError) as exc:
        raise ProfileVersionRejected("invalid profile snapshot") from exc
    latest = (
        StudentProfileVersion.objects.filter(student=locked).aggregate(value=models.Max("version"))[
            "value"
        ]
        or 0
    )
    schema_version = 3 if isinstance(validated, StudentProfileSnapshot) else 0
    return StudentProfileVersion.objects.create(
        student=locked,
        version=latest + 1,
        schema_version=schema_version,
        snapshot=validated.model_dump(mode="json"),
    )
