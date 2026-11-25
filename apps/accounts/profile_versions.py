from django.db import models, transaction
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from apps.tenancy.context import TenantContextMissing, current_tenant_id
from apps.tenancy.models import Membership

from .models import StudentProfileVersion
from .schemas import MinimalProfile, StudentProfileSnapshot


class ProfileVersionRejected(ValueError):
    pass


def _nationality_backed_by_fact(student: Membership, nationality: str) -> bool:
    from apps.documents.models import VerifiedFact
    from apps.documents.verification import (
        disowned_refs,
        live_retired_refs,
        retired_hides,
        retired_refs,
        unsuperseded_facts,
    )

    from .forms import normalize_country_code

    target_code = normalize_country_code(nationality)
    disowned = disowned_refs(student)
    retired, live = retired_refs(student), live_retired_refs(student)
    for fact in (
        unsuperseded_facts(student)
        .filter(
            category=VerifiedFact.Category.IDENTITY,
            confirmed_at__isnull=False,
        )
        .exclude(source_ref__in=disowned)
    ):
        if retired_hides(fact, retired, live) or not isinstance(fact.payload, dict):
            continue
        cit = normalize_country_code(fact.payload.get("citizenship"))
        if cit and cit == target_code:
            return True
    return False


_BROAD_ROOT_UMBRELLAS = frozenset(
    {
        "natural sciences",
        "physical sciences",
        "social sciences",
        "humanities",
        "engineering",
        "life sciences",
        "arts",
        "health sciences",
        "business & management",
        "computer & information sciences",
    }
)


def _fields_match(prev_field: str, cur_field: str) -> bool:
    p_cf = prev_field.strip().casefold()
    c_cf = cur_field.strip().casefold()
    if p_cf == c_cf or p_cf == "not stated":
        return True
    if not p_cf or not c_cf or c_cf == "not stated":
        return False
    from .field_taxonomy import resolve_field_taxonomy

    prev_tax = resolve_field_taxonomy(prev_field)
    cur_tax = resolve_field_taxonomy(cur_field)
    if set(prev_tax.canonical_degree_titles) & set(cur_tax.canonical_degree_titles):
        return True
    prev_domains = (
        set(prev_tax.canonical_degree_titles) | set(prev_tax.parent_fields)
    ) - _BROAD_ROOT_UMBRELLAS
    cur_domains = (
        set(cur_tax.canonical_degree_titles) | set(cur_tax.parent_fields)
    ) - _BROAD_ROOT_UMBRELLAS
    return bool(prev_domains & cur_domains)


def _identity_continuity_holds(
    student: Membership, validated: StudentProfileSnapshot
) -> bool:
    from apps.documents.degree_match import same_degree, same_name

    prev_row = (
        StudentProfileVersion.objects.filter(student=student, schema_version=3)
        .order_by("-version")
        .first()
    )
    if prev_row is None or not isinstance(prev_row.snapshot, dict):
        return True
    raw_snap = (
        {k: v for k, v in prev_row.snapshot.items() if k != "weights"}
        if prev_row.snapshot.get("weights") == {}
        else prev_row.snapshot
    )
    try:
        prev = StudentProfileSnapshot.model_validate(raw_snap)
    except ValidationError:
        return True
    if prev.date_of_birth != validated.date_of_birth:
        return False
    if prev.nationality != validated.nationality and not _nationality_backed_by_fact(
        student, validated.nationality
    ):
        return False
    used_indices: set[int] = set()
    for prev_deg in prev.academic_history:
        prev_end = prev_deg.completed_on or prev_deg.expected_completion
        prev_fact = {
            "institution_original": prev_deg.institution,
            "country": prev_deg.country_code,
            "degree_as_awarded": prev_deg.qualification,
            "end_date": prev_end.isoformat() if prev_end else None,
        }
        match_idx = next(
            (
                idx
                for idx, cur_deg in enumerate(validated.academic_history)
                if idx not in used_indices
                and _fields_match(prev_deg.field, cur_deg.field)
                and (
                    (
                        same_name(prev_deg.institution, cur_deg.institution)
                        and prev_deg.qualification.casefold() == cur_deg.qualification.casefold()
                    )
                    or same_degree(
                        prev_fact,
                        {
                            "institution": cur_deg.institution,
                            "country_code": cur_deg.country_code,
                            "qualification": cur_deg.qualification,
                            "completed_on": (
                                cur_deg.completed_on.isoformat()
                                if cur_deg.completed_on
                                else None
                            ),
                            "expected_completion": (
                                cur_deg.expected_completion.isoformat()
                                if cur_deg.expected_completion
                                else None
                            ),
                        },
                    )
                    == "same"
                )
            ),
            None,
        )
        if match_idx is None:
            return False
        used_indices.add(match_idx)
    return True


def create_profile_version(
    *,
    student: Membership,
    snapshot: MinimalProfile | StudentProfileSnapshot,
    allow_identity_override: bool = False,
) -> StudentProfileVersion:
    with transaction.atomic():
        try:
            tenant_id = current_tenant_id()
            locked = Membership.objects.select_for_update().get(id=student.id)
        except (TenantContextMissing, Membership.DoesNotExist) as exc:
            raise ProfileVersionRejected("profile subject unavailable") from exc
        if (
            locked.tenant_id != tenant_id
            or not locked.active
            or locked.role != Membership.Role.STUDENT
        ):
            raise ProfileVersionRejected("active student membership required")

        schema = (
            StudentProfileSnapshot
            if isinstance(snapshot, StudentProfileSnapshot)
            else MinimalProfile
        )
        try:
            validated = schema.model_validate(
                snapshot.model_dump(mode="python", warnings="none")
            )
        except (PydanticSerializationError, ValidationError) as exc:
            raise ProfileVersionRejected("invalid profile snapshot") from exc

        if (
            isinstance(validated, StudentProfileSnapshot)
            and not allow_identity_override
            and not _identity_continuity_holds(locked, validated)
        ):
            from apps.documents.id_reading import raise_identity_mismatch_alert

            raise_identity_mismatch_alert(
                locked,
                message=(
                    "Identity continuity violation on profile update for "
                    f"{locked.user.get_full_name() or locked.user.email}."
                ),
            )
            violation = True
        else:
            violation = False

        if not violation:
            latest = (
                StudentProfileVersion.objects.filter(student=locked).aggregate(
                    value=models.Max("version")
                )["value"]
                or 0
            )
            schema_version = 3 if isinstance(validated, StudentProfileSnapshot) else 0
            return StudentProfileVersion.objects.create(
                student=locked,
                version=latest + 1,
                schema_version=schema_version,
                snapshot=validated.model_dump(mode="json"),
            )
    raise ProfileVersionRejected("identity continuity violation")
