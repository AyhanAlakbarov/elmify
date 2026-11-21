"""Locale-independent date formatting for CV and letter templates.

Django's ``date:"M Y"`` runs the month abbreviation through the active
translation, which is the server-locale dependency that
``test_dates_are_locale_independent`` exists to prevent -- a CV rendered on a
worker with a German locale would read "Okt 2021" for a document whose
language is English. The month table here is fixed, so the same content
renders the same bytes on any server.
"""

from __future__ import annotations

from datetime import date

from django import template

register = template.Library()

_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


@register.filter
def month_year(value: date | None, default: str = "") -> str:
    """Format a date as "Sep 2017"; ``default`` covers an open-ended entry."""
    if value is None:
        return default
    return f"{_MONTHS[value.month - 1]} {value.year}"


@register.simple_tag(takes_context=True)
def date_range(context: template.Context, start: date | None, end: date | None) -> str:
    """One entry's dates, true on the day of the render (spec 3.2).

    "Present" for an open entry; "(expected)" when the end is after today; an
    entry that has not started yet reads "Admitted; starts Nov 2026". That last
    is only ever printed when it is the CV's sole education entry, because
    render.without_future_starts drops every other future start. ``today``
    comes from the render context so tests can fix it; funder templates have
    none and fall back to the real date.
    """
    today = context.get("today") or date.today()
    if start is not None and start > today:
        return f"Admitted; starts {month_year(start)}"
    if end is None:
        return f"{month_year(start)} – Present"
    label = " (expected)" if end > today else ""
    return f"{month_year(start)} – {month_year(end)}{label}"
