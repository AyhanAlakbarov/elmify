"""The register's key. A wrong answer here merges two universities into one row."""

import pytest

from apps.research.hosts import (
    HOSTING_PLATFORMS,
    is_hosting_platform,
    is_institutional_url,
    registrable_domain,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # The case the probe's two-label rule got wrong: edu.tr is a public
        # suffix, so metu.edu.tr is the registrable domain and edu.tr is not.
        ("www.metu.edu.tr", "metu.edu.tr"),
        ("https://www.metu.edu.tr/en/admissions", "metu.edu.tr"),
        ("ox.ac.uk", "ox.ac.uk"),
        # gov.az is a public suffix; edu.gov.az is a real organisation.
        ("edu.gov.az", "edu.gov.az"),
        ("zeit-stiftung.de", "zeit-stiftung.de"),
        # Deep subdomains collapse to the organisation that owns them.
        ("ai.study.fau.eu", "fau.eu"),
        ("sub.dept.uni-hamburg.de", "uni-hamburg.de"),
        ("HTTPS://WWW.Uni-Hamburg.DE/", "uni-hamburg.de"),
    ],
)
def test_registrable_domain_uses_the_public_suffix_list(value: str, expected: str) -> None:
    assert registrable_domain(value) == expected


@pytest.mark.parametrize("value", ["", "localhost", "192.0.2.1", "https://192.0.2.1/x", "   "])
def test_no_registrable_domain_is_an_empty_string_not_a_guess(value: str) -> None:
    """A caller must be able to skip a host rather than store a wrong key."""
    assert registrable_domain(value) == ""


def test_resolution_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """The snapshot ships with the package. A discovery sweep must not fetch
    the suffix list mid-run, and an air-gapped test run must not hang."""
    import socket

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("registrable_domain attempted a network call")

    monkeypatch.setattr(socket, "socket", refuse)
    assert registrable_domain("www.metu.edu.tr") == "metu.edu.tr"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Spec §5.6's measured table: one blog anchored all of blogspot, and
        # one Russian university stood for all of edu.ru.
        ("foo.github.io", "foo.github.io"),
        ("bar.blogspot.com", "bar.blogspot.com"),
        ("tspu.edu.ru", "tspu.edu.ru"),
        # Not on the PSL's private section: only extra_suffixes separates them.
        ("x.wordpress.com", "x.wordpress.com"),
        ("z.weebly.com", "z.weebly.com"),
        ("y.wixsite.com", "y.wixsite.com"),
        # A platform root names the landlord, never a publisher: unkeyable.
        ("wordpress.com", ""),
        ("sites.google.com", ""),
        ("https://sites.google.com/view/some-university", ""),
    ],
)
def test_private_suffixes_and_hosting_platforms_key_their_tenants(value, expected) -> None:
    assert registrable_domain(value) == expected


def test_the_hosting_platform_list_is_pinned() -> None:
    assert HOSTING_PLATFORMS == (
        "github.io", "gitlab.io", "blogspot.com", "wordpress.com", "wixsite.com",
        "weebly.com", "sites.google.com", "squarespace.com", "webflow.io",
        "netlify.app", "vercel.app", "pages.dev", "herokuapp.com",
        "firebaseapp.com", "web.app", "tumblr.com", "medium.com", "substack.com",
        "notion.site", "000webhostapp.com",
    )


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("foo.github.io", True),
        ("bar.blogspot.com", True),
        ("x.wordpress.com", True),
        ("github.io", True),
        ("tum.de", False),
        ("google.com", False),
    ],
)
def test_a_body_on_a_hosting_platform_is_recognised_as_one(domain, expected) -> None:
    assert is_hosting_platform(domain) is expected


@pytest.mark.parametrize(
    ("url", "domain", "expected"),
    [
        ("https://www.tum.de/en/studies/msc", "tum.de", True),
        ("https://www.cit.tum.de/cit/studium/", "tum.de", True),
        ("https://tum.de/", "tum.de", True),
        ("https://blogs.tum.de/robotics/", "tum.de", False),
        ("https://wiki.cs.tum.de/x", "tum.de", False),
        ("https://students.tum.de/club", "tum.de", False),
        ("https://people.tum.de/~ada", "tum.de", False),
        ("https://www.tum.de/~ada/msc", "tum.de", False),
        ("https://fake-tum.example/msc", "tum.de", False),
        ("https://foo.github.io/msc", "foo.github.io", False),
        ("https://www.tum.de/x", "", False),
    ],
)
def test_institutional_urls_exclude_user_content(url, domain, expected) -> None:
    assert is_institutional_url(url, domain) is expected
