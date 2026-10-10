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
