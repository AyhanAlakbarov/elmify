"""Is this page asking a human to prove they are one?

Deterministic by design. Every entry in MARKERS is a container class the
provider's own script renders, and the site key is read from the attribute that
script reads. Nothing here infers a challenge from page text, timing alone, or
a model's opinion, because a false positive sends an ordinary application to a
consultant and a false negative strands it.
"""

from dataclasses import dataclass

from .session import PortalSession

UNKNOWN_KIND = "unknown"

#: (kind, container selector, site-key attribute, response field selector).
#: The response selector is where a solved token is written back -- always a
#: form field the provider's own script fills, never a control.
MARKERS: tuple[tuple[str, str, str, str], ...] = (
    ("recaptcha", ".g-recaptcha", "data-sitekey", "textarea[name='g-recaptcha-response']"),
    ("hcaptcha", ".h-captcha", "data-sitekey", "textarea[name='h-captcha-response']"),
    ("turnstile", ".cf-turnstile", "data-sitekey", "input[name='cf-turnstile-response']"),
)

#: Consecutive failed actions on a page that previously worked. Three, not one:
#: a single miss is ordinary drift and belongs to the re-learn path.
STALL_THRESHOLD = 3


@dataclass(frozen=True)
class Challenge:
    kind: str
    site_key: str
    page_url: str
    response_selector: str


def detect_challenge(
    session: PortalSession, *, page_url: str, act_failures: int = 0
) -> Challenge | None:
    for kind, container, site_key_attribute, response_selector in MARKERS:
        if not session.exists(container):
            continue
        return Challenge(
            kind=kind,
            # An invisible widget renders its key elsewhere. No key is a
            # resolvable state (the consultant path needs none), so it is an
            # empty string rather than a reason to report nothing.
            site_key=session.query_attribute(container, site_key_attribute) or "",
            page_url=page_url,
            response_selector=response_selector,
        )
    if act_failures >= STALL_THRESHOLD:
        # No marker and nothing working. This cannot be handed to a resolution
        # service -- there is no site key and no kind to send -- so it exists
        # purely to reach a consultant with the session preserved.
        return Challenge(
            kind=UNKNOWN_KIND, site_key="", page_url=page_url, response_selector=""
        )
    return None
