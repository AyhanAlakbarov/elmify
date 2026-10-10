import pytest

from apps.documents.evidence.sources import (
    DoiRef,
    RepoRef,
    UnsupportedSource,
    parse_source,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://github.com/0rkhann/MicroKatc", RepoRef("github", "0rkhann", "MicroKatc")),
        ("https://github.com/0rkhann/MicroKatc/", RepoRef("github", "0rkhann", "MicroKatc")),
        ("https://github.com/0rkhann/MicroKatc.git", RepoRef("github", "0rkhann", "MicroKatc")),
        ("github.com/0rkhann/MicroKatc", RepoRef("github", "0rkhann", "MicroKatc")),
        ("https://gitlab.com/dgarayr/thermochange", RepoRef("gitlab", "dgarayr", "thermochange")),
        (
            "https://github.com/0rkhann/MicroKatc/tree/main/pics",
            RepoRef("github", "0rkhann", "MicroKatc"),
        ),
    ],
)
def test_a_repository_url_becomes_a_typed_reference(raw, expected):
    assert parse_source(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "10.1021/acscatal.5c00348",
        "https://doi.org/10.1021/acscatal.5c00348",
        "doi:10.1021/acscatal.5c00348",
        "  10.1021/acscatal.5c00348  ",
    ],
)
def test_a_doi_in_any_common_form_becomes_a_doi_reference(raw):
    assert parse_source(raw) == DoiRef("10.1021/acscatal.5c00348")


@pytest.mark.parametrize(
    "raw",
    [
        # A host we do not talk to is refused, never fetched.
        "https://evil.example.test/0rkhann/MicroKatc",
        "https://gitlab.mycompany.internal/team/project",
        "https://bitbucket.org/team/project",
        # Path traversal must never survive parsing.
        "https://github.com/../../etc/passwd",
        "https://github.com/0rkhann/../../../secrets",
        "https://github.com/%2e%2e%2f/x",
        "https://github.com/0rkhann/Micro%2FKatc",
        # Credentials or a port smuggled into the authority.
        "https://user:pass@github.com/0rkhann/MicroKatc",
        "https://github.com:22/0rkhann/MicroKatc",
        "https://github.com.evil.test/0rkhann/MicroKatc",
        # A malformed port makes urllib's own `.port` accessor raise a bare
        # ValueError; that must come out as UnsupportedSource, not leak.
        "https://github.com:abc/0rkhann/MicroKatc",
        # No "://", so we prepend "https://"; the resulting netloc
        # "javascript:github.com" hits the same malformed-port accessor.
        "javascript:github.com/x/y",
        # Not enough path segments.
        "https://github.com/0rkhann",
        # Not a DOI.
        "10.x/nope",
        "my chemistry project",
        "",
        # DOI path traversal and unescaped-path-segment cases: the DOI
        # suffix is interpolated raw into the Crossref URL (publication.py),
        # so this module's own docstring promise -- "no student-supplied
        # string ever becomes a hostname or an unescaped path segment" --
        # must hold for it exactly as it does for owner/repo.
        "10.1234/../../admin",
        "10.1234/x#@evil.com",
        "10.1234/a%2f..%2fb",
        "doi:10.1234/..",
        # A DOI built to be needlessly long, to pin the length cap.
        "10.1234/" + "a" * 300,
    ],
)
def test_anything_we_do_not_understand_is_refused(raw):
    with pytest.raises(UnsupportedSource):
        parse_source(raw)


def test_the_parsed_owner_and_name_can_never_contain_a_separator():
    """The whole point of this module: what survives parsing is safe to
    interpolate into a path we build, because it cannot contain a slash, a
    dot-segment, or an encoded one."""
    ref = parse_source("https://github.com/0rkhann/MicroKatc")
    for value in (ref.owner, ref.name):
        assert "/" not in value
        assert "\\" not in value
        assert ".." not in value
        assert "%" not in value
