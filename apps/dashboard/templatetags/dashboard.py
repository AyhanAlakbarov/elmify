"""`https_only`: the one gate between third-party URLs and an href.

Django escapes a URL as text, which keeps it from breaking out of the
attribute but not from being `javascript:` -- that scheme survives autoescaping
inside href (apps/funding/requirements.py says so of RequirementItem.source_url).
Every template that renders a URL it did not build passes it through here.
"""

from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

from django import template
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.templatetags.static import static
from django.utils.html import format_html

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


_COVERAGE = {
    "FULL": "Fully covered",
    "PARTIAL": "Partly covered",
    "HALF": "Half covered",
    "NONE": "Not covered",
    "UNSTATED": "Not stated",
}


@register.filter
def coverage(value: object) -> str:
    """An award card's tuition or living-cost field as a student reads it."""
    raw = str(value or "").strip().upper()
    if not raw:
        return "Not stated"
    return _COVERAGE.get(raw, raw.replace("_", " ").lower().capitalize())


_FLAG_DIR = Path(__file__).resolve().parents[3] / "static" / "elmify" / "flags"


@cache
def _flag_codes() -> frozenset[str]:
    return frozenset(path.stem for path in _FLAG_DIR.glob("??.svg"))


@register.filter
def flag(code: object) -> str:
    """A country's flag as an image, from a two-letter ISO code.

    An SVG file, not an emoji: Windows renders flag emoji as two letters. The
    image is decorative -- the country is always named in text beside it -- so
    alt is empty. An unknown or malformed code renders nothing.
    """
    raw = str(code or "").strip().lower()
    if len(raw) != 2 or raw not in _flag_codes():
        return ""
    return format_html(
        '<img class="flag" src="{}" alt="" width="20" height="15" loading="lazy">',
        static(f"elmify/flags/{raw}.svg"),
    )


#: Coverage, as a tone the page colours by: good, part, none or unknown.
_COVERAGE_TONE = {"FULL": "good", "PARTIAL": "part", "HALF": "part", "NONE": "none"}


@register.filter
def coverage_tone(value: object) -> str:
    return _COVERAGE_TONE.get(str(value or "").strip().upper(), "unknown")


#: Accent colours a funding group can wear, picked by a stable hash of its
#: name, so one scholarship keeps its colour across visits and pages.
_GROUP_TONES = ("indigo", "teal", "amber", "rose", "sky", "violet", "emerald")


@register.filter
def tone(value: object) -> str:
    text = str(value or "")
    return _GROUP_TONES[sum(text.encode()) % len(_GROUP_TONES)]


_MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@register.filter
def month_year(value: object) -> str:
    """A stored CV date ('2021-09-01', '2021-09' or '2021') as 'Sep 2021'."""
    text = str(value or "")
    parts = text.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit() and 1 <= int(parts[1]) <= 12:
        return f"{_MONTH_NAMES[int(parts[1]) - 1]} {parts[0]}"
    return text
