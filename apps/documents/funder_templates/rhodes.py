"""Rhodes Scholarship (R-066, R-080).

Six numbered sections, in R-066's exact order, and deliberately NO education
section -- education is collected by the separate Embark form, and adding it
here is the mistake the rule exists to prevent:

    1 Professional/Research/Internship
    2 Volunteering/Community/Leadership
    3 Publications and presentations
    4 Awards/prizes/scholarships
    5 Skills/hobbies/extracurricular
    6 Other

R-080 routes paid work to section 1 and unpaid/voluntary work to section 2 --
ExperienceEntry.unpaid (default False) carries that split; every other
variant ignores the field. The 2-page cap is a BINDING ConstraintRule
enforced by render.py's pre-flight, not re-implemented here.
"""

from __future__ import annotations

from django.template.loader import render_to_string

from apps.documents.render import RenderedArtifact, hygienic_content, render_html_to_artifact
from apps.documents.schemas import CVContent


def render_rhodes(content: CVContent) -> RenderedArtifact:
    clean = hygienic_content(content)
    paid_experience = tuple(entry for entry in clean.experience if not entry.unpaid)
    unpaid_experience = tuple(entry for entry in clean.experience if entry.unpaid)
    html = render_to_string(
        "documents/cv_funder_rhodes.html",
        {
            "content": clean,
            "paid_experience": paid_experience,
            "unpaid_experience": unpaid_experience,
        },
    )
    return render_html_to_artifact(html, variant="FUNDER_TEMPLATE")
