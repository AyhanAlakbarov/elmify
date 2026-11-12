"""Applying needs the extension, in Chrome or Edge, on a computer (lanes spec §5.1).

Read from the request's User-Agent. A wrong guess costs a sentence in place of
the button, never a refused application: the start route checks pairing itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from .needs import EXTENSION_URL

INSTALL = "Install the extension to apply"
OTHER_BROWSER = "Open this in Chrome or Edge to apply"
PHONE = "Open this on a computer to apply"
_PHONE_MARKS = ("Mobi", "Android", "iPhone", "iPad")


@dataclass(frozen=True)
class Blocker:
    text: str
    url: str = ""


def apply_blocker(user_agent: str, *, paired: bool) -> Blocker | None:
    """None when the Apply button can show."""
    if any(mark in user_agent for mark in _PHONE_MARKS):
        return Blocker(PHONE)
    if "Chrome/" not in user_agent and "Edg/" not in user_agent:
        return Blocker(OTHER_BROWSER)
    if not paired:
        return Blocker(INSTALL, EXTENSION_URL)
    return None
