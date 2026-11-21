"""The CAPTCHA widgets the extension's content script detects.

The extension does the detecting, in the student's own tab, and tells the
student; tests/portals/test_extension_bundle.py asserts its markers equal
these. Deterministic by design: every entry is a container class the
provider's own script renders, never page text, timing or a model's opinion.
"""

#: (kind, container selector, site-key attribute, response field selector).
MARKERS: tuple[tuple[str, str, str, str], ...] = (
    ("recaptcha", ".g-recaptcha", "data-sitekey", "textarea[name='g-recaptcha-response']"),
    ("hcaptcha", ".h-captcha", "data-sitekey", "textarea[name='h-captcha-response']"),
    ("turnstile", ".cf-turnstile", "data-sitekey", "input[name='cf-turnstile-response']"),
)
