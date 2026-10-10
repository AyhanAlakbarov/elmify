"""`https_only`: the one gate between third-party URLs and an href.

Django escapes a URL as text, which keeps it from breaking out of the
attribute but not from being `javascript:` -- that scheme survives autoescaping
inside href (apps/funding/requirements.py says so of RequirementItem.source_url).
Every template that renders a URL it did not build passes it through here.
"""

from urllib.parse import urlsplit

from django import template
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

register = template.Library()
_validate = URLValidator(schemes=["https"])


@register.filter
def https_only(value: object) -> str:
    """The URL if it is a plain https link, else "".

    No userinfo and no backslash: a browser and Python's urlsplit disagree about
    both (apps/mailbox/actions.py::_verification_url measured it), so a URL
    carrying either is refused rather than parsed.
    """
    url = str(value or "").strip()
    if not url or "\\" in url or len(url) > 2048:
        return ""
    try:
        _validate(url)
        parts = urlsplit(url)
    except (ValidationError, ValueError):
        return ""
    if parts.username or parts.password:
        return ""
    return url


@register.filter
def lookup(mapping: object, key: object) -> object:
    """mapping[key], or "" -- for the dicts keyed by id that views pass."""
    return mapping.get(key, "") if isinstance(mapping, dict) else ""


@register.filter
def answer(value: object) -> str:
    """A consultation answer as a person reads it: a list joined, a record as
    "field: value" pairs -- never a Python repr (Task 18 minor)."""
    if isinstance(value, dict):
        return ", ".join(
            f"{str(key).replace('_', ' ')}: {answer(item)}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        )
    if isinstance(value, list):
        return "; ".join(answer(item) for item in value) if value else "none"
    return "" if value is None else str(value)
