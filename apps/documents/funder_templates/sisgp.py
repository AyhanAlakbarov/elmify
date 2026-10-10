"""Swedish Institute SISGP (R-064, R-078, R-079).

Five fixed sections in a fixed order, WORK EXPERIENCE capped at three entries,
and Sex / Date of birth / Citizenship mandatory in PERSONAL INFORMATION. The
template is a schema, not a stylesheet: no section may be added or reordered.
"""

from __future__ import annotations

from django.template.loader import render_to_string

from apps.documents.entry_selection import select_best_entries
from apps.documents.render import RenderedArtifact, hygienic_content, render_html_to_artifact
from apps.documents.schemas import CVContent

_WORK_EXPERIENCE_CAP = 3


def render_sisgp(content: CVContent) -> RenderedArtifact:
    clean = hygienic_content(content)
    # R-064 gives NETWORK/CIVIL SOCIETY ENGAGEMENT its own mandated heading, so
    # unpaid work belongs there, not under WORK EXPERIENCE. Same
    # ExperienceEntry.unpaid split Rhodes uses for R-080; splitting before the
    # cap is deliberate -- R-078 caps what appears under WORK EXPERIENCE, and
    # counting volunteering against that cap would evict paid roles for entries
    # the section never shows.
    paid = tuple(entry for entry in clean.experience if not entry.unpaid)
    unpaid = tuple(entry for entry in clean.experience if entry.unpaid)
    capped = select_best_entries(
        paid, limit=_WORK_EXPERIENCE_CAP, key=lambda entry: entry.start_date
    )
    engagement = select_best_entries(
        unpaid, limit=len(unpaid), key=lambda entry: entry.start_date
    )
    # R-078: reverse-chronological within every category, not just the
    # capped WORK EXPERIENCE -- select_best_entries already does the sort,
    # so reuse it at limit=len(...) to reorder EDUCATION AND TRAINING too.
    education = select_best_entries(
        clean.education, limit=len(clean.education), key=lambda entry: entry.start_date
    )
    html = render_to_string(
        "documents/cv_funder_sisgp.html",
        {
            "content": clean,
            "experience": capped,
            "education": education,
            "engagement": engagement,
        },
    )
    return render_html_to_artifact(html, variant="FUNDER_TEMPLATE")
