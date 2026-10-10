from __future__ import annotations

from django.db import transaction

from apps.funding.models import ConstraintOverride, Program
from apps.tenancy.models import Membership

from .constraints import Enforcement
from .render import ConstraintViolation


class OverrideRefused(ValueError):
    pass


def _has_override(*, student: Membership, programme: Program, rule_id: str) -> bool:
    return ConstraintOverride.objects.filter(
        student=student, programme=programme, rule_id=rule_id
    ).exists()


def resolve_violations(
    violations: tuple[ConstraintViolation, ...], *, student: Membership, programme: Program
) -> tuple[ConstraintViolation, ...]:
    """Filter violations down to the ones still worth showing.

    ADVISORY_STYLE is honoured silently -- ceremony here trains people to click
    through the warnings that matter. ADVISORY_HIGH_RISK survives until the
    student has accepted it for this exact programme and rule. BINDING always
    survives; render_cv already raised on it before this function is reached.
    """
    remaining = []
    for violation in violations:
        if violation.rule.enforcement == Enforcement.ADVISORY_STYLE:
            continue
        if violation.rule.enforcement == Enforcement.ADVISORY_HIGH_RISK and _has_override(
            student=student, programme=programme, rule_id=violation.rule.rule_id
        ):
            continue
        remaining.append(violation)
    return tuple(remaining)


@transaction.atomic
def record_override(
    *,
    student: Membership,
    programme: Program,
    violation: ConstraintViolation,
    decided_by: Membership,
) -> ConstraintOverride:
    """Record the student's decision to proceed against an ADVISORY_HIGH_RISK rule.

    ``decided_by`` must be the student: a counselor may show the risk, but the
    risk lands on the student's application, so the decision is theirs. BINDING
    rules have no override path at all.

    Scoped to (student, programme, rule_id) by a database unique index, so a
    second decision replaces the first instead of racing it.
    """
    if violation.rule.enforcement != Enforcement.ADVISORY_HIGH_RISK:
        raise OverrideRefused(
            f"{violation.rule.enforcement} rules cannot be overridden; only ADVISORY_HIGH_RISK can"
        )
    if decided_by.id != student.id:
        raise OverrideRefused("only the student may accept a risk on their own application")
    override, _created = ConstraintOverride.objects.update_or_create(
        student=student,
        programme=programme,
        rule_id=violation.rule.rule_id,
        defaults={
            "decided_by": decided_by,
            "risk_text_shown": violation.rule.rule_text,
        },
    )
    return override
