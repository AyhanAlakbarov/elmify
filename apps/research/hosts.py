"""The registrable domain of a host -- the key every discovery route dedupes on.

One function, because getting it wrong is expensive in a specific way: a crude
"last two labels" rule reads `metu.edu.tr` as `edu.tr` and merges every Turkish
university into a single register row. `edu.tr`, `ac.uk` and `gov.az` are public
suffixes, and only the Public Suffix List knows that.

The suffix list is the snapshot bundled with tldextract, never fetched:
`suffix_list_urls=()` disables the live download, and a discovery sweep that
paused to refresh a suffix list would be making an unbudgeted outbound call
from inside a loop that is already rate-limited on other grounds.

**Private suffixes are on, and hosting platforms are suffixes too** (institution
provenance gate spec §5.6, 2026-09-26). With private suffixes off, one blog
anchored all of blogspot and one Russian university stood for all of edu.ru
(`tspu.edu.ru -> edu.ru`). The PSL's private section fixes github.io and
blogspot.com but not wordpress.com, weebly.com or sites.google.com, so the
platform list is passed as `extra_suffixes` as well (measured, tldextract
5.3.2). A platform's own root is then unkeyable (""), which is correct: it
names the landlord, never a publisher.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import tldextract

#: Hosting platforms (spec §5.6). A body whose domain is one of these, or under
#: one, can be UNCONFIRMED and never RECOGNISED through its domain. 205 active
#: ROR records, 37 of them education, keep their website on such a platform
#: (wordpress.com 59, google.com 26, wixsite 23, weebly 20, blogspot 15).
#: Pinned by tests/research/test_hosts.py.
HOSTING_PLATFORMS: tuple[str, ...] = (
    "github.io", "gitlab.io", "blogspot.com", "wordpress.com", "wixsite.com",
    "weebly.com", "sites.google.com", "squarespace.com", "webflow.io",
    "netlify.app", "vercel.app", "pages.dev", "herokuapp.com",
    "firebaseapp.com", "web.app", "tumblr.com", "medium.com", "substack.com",
    "notion.site", "000webhostapp.com",
)

#: A label left of the registrable domain that marks user content rather than
#: the institution's own voice (spec §3). Any label counts: blogs.cs.tum.de is
#: a blog however deep it sits.
USER_CONTENT_LABELS = frozenset(
    {"blog", "blogs", "wiki", "forum", "forums", "people", "users", "sites",
     "student", "students"}
)

#: `suffix_list_urls=()` is the documented offline mode; `fallback_to_snapshot`
#: keeps the bundled list in play. Built once at import: the constructor reads
#: the snapshot, and building it per call would parse it per call.
_EXTRACT = tldextract.TLDExtract(
    suffix_list_urls=(),
    fallback_to_snapshot=True,
    include_psl_private_domains=True,
    extra_suffixes=HOSTING_PLATFORMS,
)


def registrable_domain(value: str) -> str:
    """The registrable domain of a host or URL, lowercased, or "" if there is none.

    "" is returned for an IP address, an unknown suffix, a hosting platform's
    own root and an empty input -- never a guess. A caller that cannot key a
    host must skip it, because a wrong key is a silently merged organisation
    rather than a visible failure.
    """
    text = value.strip()
    if not text:
        return ""
    host = urlsplit(text).hostname if "//" in text else text
    if not host:
        return ""
    # `registered_domain` is deprecated in tldextract 5.3; this is the same
    # value under the accurate name.
    return _EXTRACT(host.casefold()).top_domain_under_public_suffix


def is_hosting_platform(domain: str) -> bool:
    normalized = domain.casefold().strip(".")
    return any(
        normalized == platform or normalized.endswith(f".{platform}")
        for platform in HOSTING_PLATFORMS
    )


def is_institutional_url(url: str, domain: str) -> bool:
    """Whether `url` is the institution's own voice on `domain` (spec §3).

    On the domain's main host or an institutional subdomain; never a user
    subdomain, a `/~user` path, or a hosting platform.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    if not domain or is_hosting_platform(domain) or registrable_domain(host) != domain:
        return False
    labels = host[: -len(domain)].rstrip(".").split(".") if host != domain else []
    if any(label in USER_CONTENT_LABELS for label in labels):
        return False
    return not parts.path.startswith("/~")
