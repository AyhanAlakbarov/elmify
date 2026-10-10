"""Each category heading appears once, in the applicant's own order."""

from apps.documents.schemas import SkillEntry
from apps.documents.templatetags.cv_skills import by_category


def _skills(*pairs):
    return tuple(SkillEntry(name=name, category=category) for name, category in pairs)


def test_interleaved_categories_still_produce_one_heading_each():
    """The real failure: skills arrive scrambled, not grouped.

    Django's regroup groups adjacent runs only, so this input rendered five
    headings for three categories -- a measured CV produced 14 headings for 22
    skills, with "Chemoinformatics & Data Libraries" appearing four times.
    """
    grouped = by_category(
        _skills(
            ("PyTorch", "Libraries"),
            ("Computational Chemistry", "Core"),
            ("Git", "Tools"),
            ("RDKit", "Libraries"),
            ("Deep Learning", "Core"),
            ("Python", "Tools"),
            ("NumPy", "Libraries"),
        )
    )
    assert [category for category, _ in grouped] == ["Libraries", "Core", "Tools"]
    assert [[s.name for s in group] for _, group in grouped] == [
        ["PyTorch", "RDKit", "NumPy"],
        ["Computational Chemistry", "Deep Learning"],
        ["Git", "Python"],
    ]


def test_categories_keep_first_appearance_order_not_alphabetical():
    """dictsort+regroup would fix the repetition and introduce this bug.

    The applicant chose the order of their own headings; alphabetising it
    would put "Core Competencies" above the libraries a chemist leads with.
    """
    grouped = by_category(_skills(("Z-thing", "Zeta"), ("A-thing", "Alpha")))
    assert [category for category, _ in grouped] == ["Zeta", "Alpha"]


def test_uncategorised_skills_group_under_one_empty_heading():
    """SkillEntry's category is optional; those render as a flat line."""
    grouped = by_category(_skills(("Python", None), ("Git", None)))
    assert grouped == [("", list(grouped[0][1]))]
    assert [s.name for s in grouped[0][1]] == ["Python", "Git"]


def test_no_skills_is_no_groups():
    assert by_category(()) == []
    assert by_category(None) == []
