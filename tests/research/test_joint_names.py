import pytest

from apps.research.catalog import names_several_providers

# Every composite name manage.py discover has actually written, 2026-09-13.
COMPOSITE = (
    "University of Belgrade; Libera Università Maria SS. Assunta (LUMSA); Örebro University",
    "University of Murcia; Lund University; Friedrich-Alexander-Universität Erlangen-Nürnberg",
    "IMLEX consortium: University of Eastern Finland; Toyohashi University of Technology",
    "Art Academy of Latvia / SDSI consortium",
    "ECT+ Consortium",
    "Erasmus Mundus Journalism Consortium",
    "Copernicus Master in Digital Earth consortium universities",
)

# Plain university names from the same run, and the two false-positive families
# measured against DEQAR's 9,030 institutions. Both families are real single
# institutions and must stay single: bilingual names joined by a slash, and the
# Finnish "University Consortium", which is one legal institution.
SINGLE = (
    "University of Glasgow",
    "Université de Lille",
    "Norwegian University of Science and Technology (NTNU)",
    "Università degli Studi di Padova",
    "Western Norway University of Applied Sciences (HVL)",
)


@pytest.mark.parametrize("name", COMPOSITE)
def test_a_composite_provider_name_is_joint(name: str) -> None:
    assert names_several_providers(name) is True


@pytest.mark.parametrize("name", SINGLE)
def test_a_plain_university_name_is_not_joint(name: str) -> None:
    assert names_several_providers(name) is False


@pytest.mark.parametrize(
    "name",
    (
        "Universidad del País Vasco / Euskal Herriko Unibertsitatea",
        "Kirchliche Hochschule Wuppertal / Bethel (ev)",
        "Kajaani University Consortium",
        "Lahti University Consortium",
    ),
)
def test_the_measured_false_positives_are_accepted_deliberately(name: str) -> None:
    """19 of DEQAR's 9,030 institutions trip this rule -- bilingual names joined
    by a slash, and Finnish university consortia. They are flagged on purpose:
    a false JOINT costs one human glance and creates nothing, while a false
    SINGLE mints an Institution that can never bind to a register. Task 5's
    loader resolves them to SINGLE with no special case. Do not tune the rule
    to pass these."""
    assert names_several_providers(name) is True
