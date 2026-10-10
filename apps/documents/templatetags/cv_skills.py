"""Group skills under each category heading exactly once.

Django's ``regroup`` groups only *adjacent* runs, so it is correct only when
the input already arrives sorted by the grouping key. cv_base.html used it on
the strength of a premise that was not true: the skills reach the template in
whatever order the model emitted, which is whatever order the fact rows came
back in, which -- before this was fixed -- was Postgres's arbitrary order. A
real CV rendered 22 skills under 14 headings, "Chemoinformatics & Data
Libraries" appearing four times.

``dictsort`` + ``regroup`` would fix the repetition and introduce a different
bug, which is why the template said "regroup, not dictsort+regroup": it orders
categories alphabetically and so reorders a real CV's own grouping. This keeps
first-appearance order on both axes -- categories in the order they first
occur, skills in their order within each category -- which is the grouping the
applicant chose.
"""

from __future__ import annotations

from collections.abc import Iterable

from django import template

from apps.documents.schemas import SkillEntry

register = template.Library()


@register.filter
def by_category(skills: Iterable[SkillEntry] | None) -> list[tuple[str, list[SkillEntry]]]:
    """[(category, [skill, ...]), ...], each category appearing exactly once.

    An uncategorised skill groups under "", which cv_base.html renders as one
    plain line with no heading -- the flat-list behaviour SkillEntry's
    docstring promises for content that carries no headings.
    """
    grouped: dict[str, list[SkillEntry]] = {}
    for skill in skills or ():
        grouped.setdefault(skill.category or "", []).append(skill)
    return list(grouped.items())
