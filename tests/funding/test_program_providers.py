import pytest
from django.db import IntegrityError, transaction

from apps.funding.models import Institution, Program

pytestmark = pytest.mark.django_db


def _institution(key: str = "de:aalen") -> Institution:
    return Institution._base_manager.create(
        canonical_key=key,
        name="Aalen University",
        country_code="DE",
        official_website="https://www.hs-aalen.de/",
    )


def _program(**overrides: object) -> Program:
    fields: dict[str, object] = {
        "canonical_key": "master:imlex",
        "name": "IMLEX",
        "campus_name": "Joensuu",
        "city": "Joensuu",
        "country_code": "FI",
        "location_key": "fi:joensuu",
        "degree_level": "MASTER",
        "teaching_languages": ["English"],
        "duration_months": 24,
    }
    fields.update(overrides)
    return Program._base_manager.create(**fields)


def test_a_joint_programme_needs_no_institution() -> None:
    program = _program(
        institution=None,
        provision_type=Program.ProvisionType.JOINT,
        provider_text="University of Eastern Finland; Toyohashi University of Technology",
    )

    assert program.institution_id is None
    assert program.awarding_institutions.count() == 0


def test_a_joint_programme_may_not_carry_an_institution() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _program(institution=_institution(), provision_type=Program.ProvisionType.JOINT)


def test_a_single_programme_must_carry_an_institution() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _program(institution=None, provision_type=Program.ProvisionType.SINGLE)


def test_a_single_programme_may_not_carry_provider_text() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _program(
            institution=_institution(),
            provision_type=Program.ProvisionType.SINGLE,
            provider_text="University of Eastern Finland; Toyohashi",
        )


def test_two_joint_programmes_may_not_share_a_key() -> None:
    """Without nulls_distinct=False Postgres treats NULL as distinct from NULL
    and admits both rows, silently retiring the constraint for exactly the rows
    this change creates most of."""
    _program(institution=None, provision_type=Program.ProvisionType.JOINT)

    with pytest.raises(IntegrityError), transaction.atomic():
        _program(institution=None, provision_type=Program.ProvisionType.JOINT)


def test_a_joint_programme_holds_several_awarding_institutions() -> None:
    program = _program(institution=None, provision_type=Program.ProvisionType.JOINT)
    program.awarding_institutions.add(_institution("fi:uef"), _institution("jp:toyohashi"))

    assert program.awarding_institutions.count() == 2
